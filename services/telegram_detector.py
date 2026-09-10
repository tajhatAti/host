"""Detect Telegram bots in RunSpace source without exposing their tokens.

The raw token is used only for a short Telegram getMe check. It is never
returned, logged, or copied into analytics/admin metadata; the jobs table
already holds the user's source/env as required to restart their app.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import re
import secrets
import requests

from database import get_db_connection

# Telegram has changed token lengths over time. Keep the structural boundary
# broad and let getMe be the authority instead of rejecting a valid old/new
# token before Telegram sees it.
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])(\d{5,15}:[A-Za-z0-9_-]{20,80})(?![A-Za-z0-9_-])")
LINK_RE = re.compile(r"(?:https?://)?(?:t|telegram)\.me/([A-Za-z][A-Za-z0-9_]{3,31})", re.I)
USER_RE = re.compile(r"(?:BOT_USERNAME|TELEGRAM_BOT_USERNAME)\s*[=:]\s*['\"]?@?([A-Za-z][A-Za-z0-9_]{3,31})", re.I)
VALID_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _text(code, env):
    values = [str(code or "")[:1_000_000]]
    if isinstance(env, dict):
        values.extend(str(v)[:5000] for v in env.values())
    elif env:
        try:
            parsed = json.loads(env)
            if isinstance(parsed, dict):
                values.extend(str(v)[:5000] for v in parsed.values())
        except Exception:
            pass
    return "\n".join(values)


def inspect_bot(code, env=None, timeout=4):
    """Return safe bot metadata. Never includes the token."""
    text = _text(code, env)
    token_match = TOKEN_RE.search(text)
    usernames = LINK_RE.findall(text) + USER_RE.findall(text)
    username = next((u for u in usernames if VALID_USERNAME.match(u)), None)
    if not token_match and not username:
        return {"detected": False, "username": None, "bot_id": None,
                "check_status": "not_detected", "verified_at": None}
    result = {"detected": True, "username": username, "bot_id": None,
              "check_status": "username_only" if not token_match else "unverified",
              "verified_at": None}
    if not token_match:
        return result
    token = token_match.group(1)
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/getMe", json={}, timeout=timeout)
        payload = response.json() if response is not None else {}
        bot = payload.get("result") or {}
        if payload.get("ok") and bot.get("is_bot"):
            safe_username = str(bot.get("username") or "")
            result.update(username=safe_username if VALID_USERNAME.match(safe_username) else username,
                          bot_id=str(bot.get("id") or "") or None,
                          check_status="verified", verified_at=_now())
        elif response is not None and response.status_code in (401, 404):
            result["check_status"] = "invalid_token"
        else:
            result["check_status"] = "telegram_unreachable"
    except Exception:
        # Exception text from requests can contain the URL (and therefore the
        # token), so deliberately retain only this fixed status.
        result["check_status"] = "telegram_unreachable"
    return result


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_fingerprint(token):
    """Stable, irreversible identity used only to prevent duplicate pollers."""
    key = (os.getenv("JOB_TOKEN_HASH_KEY", "").strip()
           or os.getenv("JOB_SECRETS_KEY", "").strip()
           or "local-development-token-fingerprint")
    return hmac.new(key.encode(), token.encode(), hashlib.sha256).hexdigest()


def issue_verification(user_id, token, meta, ttl_minutes=15):
    """Create a short-lived, single-use proof without storing the token."""
    verification_id = secrets.token_urlsafe(24)
    created = datetime.now(timezone.utc)
    expires = created + timedelta(minutes=ttl_minutes)
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM telegram_token_verifications WHERE expires_at < ? OR consumed_at IS NOT NULL",
                     (created.strftime("%Y-%m-%d %H:%M:%S"),))
        conn.execute(
            "INSERT INTO telegram_token_verifications "
            "(id,user_id,token_hash,bot_username,bot_id,created_at,expires_at) VALUES (?,?,?,?,?,?,?)",
            (verification_id, user_id, _token_hash(token), meta["username"], meta.get("bot_id"),
             created.strftime("%Y-%m-%d %H:%M:%S"), expires.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()
    return verification_id


def validate_verification(user_id, verification_id, token):
    if not verification_id or not token:
        return None
    now = _now()
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id,bot_username,bot_id,expires_at,consumed_at,token_hash "
            "FROM telegram_token_verifications WHERE id=? AND user_id=?",
            (verification_id, user_id),
        ).fetchone()
        if not row:
            return None
        row = dict(row)
        if row.get("consumed_at") or row.get("expires_at", "") <= now:
            return None
        if not secrets.compare_digest(row.get("token_hash") or "", _token_hash(token)):
            return None
        return {"detected": True, "username": row["bot_username"],
                "bot_id": row.get("bot_id"), "check_status": "verified",
                "verified_at": now}
    finally:
        conn.close()


def consume_verification(verification_id):
    conn = get_db_connection()
    try:
        conn.execute("UPDATE telegram_token_verifications SET consumed_at=? WHERE id=?",
                     (_now(), verification_id))
        conn.commit()
    finally:
        conn.close()


FRAMEWORKS = (
    ("aiogram", (r"\baiogram\b",)),
    ("python-telegram-bot", (r"telegram\.ext", r"ApplicationBuilder")),
    ("pyTelegramBotAPI", (r"\btelebot\b", r"TeleBot\s*\(")),
    ("Telethon", (r"\btelethon\b", r"TelegramClient\s*\(")),
    ("Pyrogram", (r"\bpyrogram\b",)),
    ("Telegraf", (r"\btelegraf\b", r"new\s+Telegraf")),
    ("grammY", (r"from\s+[\"']grammy[\"']", r"require\([\"']grammy")),
    ("node-telegram-bot-api", (r"node-telegram-bot-api",)),
)


def analyze_code(code, language="python"):
    """Describe Telegram-specific structure without returning source/secrets."""
    source = str(code or "")[:1_000_000]
    low = source.lower()
    framework = "unknown"
    for name, patterns in FRAMEWORKS:
        if any(re.search(pattern, source, re.I) for pattern in patterns):
            framework = name
            break
    if re.search(r"setWebhook|set_webhook|webhook", source, re.I):
        mode = "webhook"
    elif re.search(r"run_polling|start_polling|infinity_polling|polling\s*\(|\.launch\s*\(|getUpdates", source, re.I):
        mode = "polling"
    else:
        mode = "unknown"
    hard = TOKEN_RE.search(source)
    env_ref = re.search(
        r"(?:os\.(?:getenv|environ)|process\.env|ENV\[|getenv\s*\().{0,80}(?:BOT_TOKEN|TELEGRAM_BOT_TOKEN)",
        source, re.I | re.S)
    assignment = re.search(
        r"(?m)^\s*(?:(?:TELEGRAM_)?BOT_TOKEN|TOKEN)\s*=\s*([^\n#;]+)", source)
    if env_ref:
        token_source = "environment"
    elif hard:
        token_source = "hardcoded"
    elif assignment:
        token_source = "example_or_literal"
    else:
        token_source = "not_found"
    match = hard or assignment
    line = source.count("\n", 0, match.start()) + 1 if match else None
    packages = []
    for name, patterns in FRAMEWORKS:
        if any(re.search(pattern, source, re.I) for pattern in patterns):
            packages.append(name)
    detected = bool(packages or hard or assignment or
                    re.search(r"telegram|botfather|t\.me/", low, re.I))
    return {
        "telegram_detected": detected,
        "framework": framework,
        "update_mode": mode,
        "token_source": token_source,
        "token_line": line,
        "needs_token_fix": token_source in ("hardcoded", "example_or_literal"),
        "packages": packages,
        "language": language or "python",
    }


def _token_expression(language):
    lang = (language or "python").lower()
    if lang in ("javascript", "node", "nodejs", "typescript"):
        return "process.env.BOT_TOKEN"
    if lang == "ruby":
        return 'ENV.fetch("BOT_TOKEN")'
    if lang == "php":
        return "getenv('BOT_TOKEN')"
    if lang in ("bash", "sh"):
        return '"$BOT_TOKEN"'
    return 'os.getenv("BOT_TOKEN")'


def secure_bot_source(code, env, token, language="python"):
    """Remove embedded bot secrets and make BOT_TOKEN env authoritative."""
    source = str(code or "")
    expr = _token_expression(language)
    lang = (language or "python").lower()

    # Named token assignments, including placeholders and old real tokens.
    assign = re.compile(
        r"(?m)^(\s*(?:(?:const|let|var)\s+)?(?:(?:TELEGRAM_)?BOT_TOKEN|TOKEN)\s*=\s*)([^\n;]+)(;?)")
    source = assign.sub(lambda m: m.group(1) + expr + m.group(3), source)

    # Direct literals passed to common Telegram constructors/builders.
    ctor = re.compile(
        r"((?:TeleBot|telegram\.Bot|Bot)\s*\(\s*(?:token\s*=\s*)?)([\"'])[^\"']*\2",
        re.S,
    )
    source = ctor.sub(lambda m: m.group(1) + expr, source)
    builder = re.compile(
        r"(ApplicationBuilder\(\)\.token\s*\()([\"'])[^\"']*\2",
        re.S,
    )
    source = builder.sub(lambda m: m.group(1) + expr, source)

    # Any remaining literal that is structurally a real Telegram token.
    quoted = re.compile(r"([\"'])" + TOKEN_RE.pattern + r"\1")
    source = quoted.sub(lambda _m: expr, source)

    # Python expressions need os; add it once, after a shebang when present.
    if lang == "python" and "os.getenv(" in source and not re.search(r"(?:^|\n)\s*(?:import\s+os|from\s+os\s+import)", source):
        if source.startswith("#!") and "\n" in source:
            first, rest = source.split("\n", 1)
            source = first + "\nimport os\n" + rest
        else:
            source = "import os\n" + source

    clean_env = dict(env or {})
    for key, value in list(clean_env.items()):
        clean_env[key] = TOKEN_RE.sub(token, str(value))
    clean_env["BOT_TOKEN"] = token
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN"):
        if key in clean_env:
            clean_env[key] = token
    return source, clean_env


# Backward-compatible internal name; semantics are now secure env injection,
# not putting the verified secret into source code.
def apply_verified_token(code, env, token, language="python"):
    return secure_bot_source(code, env, token, language)


def telegram_delivery_health(token, expected_mode="unknown", timeout=4):
    """Safe current Telegram identity/webhook diagnostics; never returns token."""
    result = {"telegram_reachable": False, "token_valid": None,
              "delivery_status": "unknown", "webhook_configured": False,
              "webhook_host": None, "pending_updates": None,
              "last_error": None}
    try:
        me = requests.post(f"https://api.telegram.org/bot{token}/getMe", json={}, timeout=timeout)
        mp = me.json() if me is not None else {}
        if not mp.get("ok"):
            if me is not None and me.status_code in (401, 404):
                result.update(telegram_reachable=True, token_valid=False,
                              delivery_status="invalid_token")
            return result
        result.update(telegram_reachable=True, token_valid=True)
        wh = requests.post(f"https://api.telegram.org/bot{token}/getWebhookInfo", json={}, timeout=timeout)
        wp = wh.json() if wh is not None else {}
        info = wp.get("result") or {}
        url = str(info.get("url") or "")
        if url:
            from urllib.parse import urlparse
            result["webhook_configured"] = True
            result["webhook_host"] = urlparse(url).hostname
        result["pending_updates"] = info.get("pending_update_count")
        result["last_error"] = str(info.get("last_error_message") or "")[:240] or None
        mode = (expected_mode or "unknown").lower()
        if mode == "polling" and url:
            result["delivery_status"] = "webhook_conflict"
        elif mode == "webhook" and not url:
            result["delivery_status"] = "webhook_missing"
        elif result["last_error"]:
            result["delivery_status"] = "webhook_error"
        elif mode == "webhook":
            result["delivery_status"] = "healthy"
        else:
            result["delivery_status"] = "telegram_ready"
    except Exception:
        pass
    return result


def public_fields(meta):
    username = meta.get("username") if meta else None
    return {
        "telegram_bot_detected": bool(meta and meta.get("detected")),
        "telegram_bot_username": username,
        "telegram_bot_id": meta.get("bot_id") if meta else None,
        "telegram_check_status": meta.get("check_status") if meta else "not_detected",
        "telegram_verified_at": meta.get("verified_at") if meta else None,
        "telegram_bot_url": f"https://t.me/{username}" if username else None,
    }
