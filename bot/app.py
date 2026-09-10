"""
CodeNest Telegram Bot — always-on bot service (Service #3).

What this is
------------
A standalone Telegram bot that STAYS ALIVE (unlike the one-shot playground
runs in the main site). It works by "long polling": a background thread keeps
asking Telegram for new messages and replies to them. A tiny FastAPI server
runs alongside purely so Render's health checks have something to ping.

Env vars
--------
    TELEGRAM_BOT_TOKEN   (required) — the token @BotFather gave you.

Commands the bot understands
----------------------------
    /start   — welcome message
    /help    — list of commands
    /echo x  — repeats x back to the user
    /time    — current UTC time
    anything else — echoed back

Keep-alive note
---------------
Render free plan sleeps idle services after ~15 min. Register the service URL
(e.g. https://your-bot.onrender.com/health) in a free UptimeRobot monitor
(5-min interval) to keep the bot awake 24/7.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ahad-bot")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
POLL_TIMEOUT_S = 40          # long-poll wait per request (Telegram max ~50)
ERROR_BACKOFF_S = 5          # wait before retrying after a network hiccup

# Ping feature config (server-side, excludes Telegram API lag)
PING_DEFAULT_TARGET = os.getenv("PING_DEFAULT_TARGET", "https://ahadorg.onrender.com").strip()
PING_TIMEOUT_S = float(os.getenv("PING_TIMEOUT_S", "8"))
PING_MAX_REDIRECTS = 3
PING_UA = "CodeNest-TelegramBot/1.0 (+https://codenest.dev)"

app = FastAPI(title="CodeNest Telegram Bot")

# Session reuses TCP connections — much faster than fresh requests calls.
_http = requests.Session()


# ---------------------------------------------------------------------------
# Server-side ping (SSRF-safe) — used by /ping command
# ---------------------------------------------------------------------------
_PING_BLOCKED_HOSTS = (
    "metadata.google.internal", "metadata",
    "localhost", "ip6-localhost", "ip6-loopback", "0.0.0.0",
)


def _ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str.split("%")[0])
    except ValueError:
        return True
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        or str(ip).startswith("169.254.")
    )


def _dns_safe(host: str) -> tuple[bool, str]:
    """Resolve host; return (ok, first_ip_or_error). Fails if any returned IP is internal."""
    try:
        infos = socket.getaddrinfo(host, None, socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, f"DNS failed: {e.strerror or e}"
    for _f, _t, _p, _c, sa in infos:
        ip = sa[0]
        if isinstance(ip, tuple):
            ip = ip[0]
        if _ip_blocked(ip):
            return False, f"host resolves to internal IP {ip}"
    return (True, infos[0][4][0]) if infos else (False, "no addresses")


def _ping_target(target: str) -> dict:
    """Perform a synchronous SSRF-safe HTTP ping. Returns dict."""
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    try:
        p = urlparse(target)
    except Exception as e:
        return {"ok": False, "error": f"bad URL: {e}"}
    if p.scheme not in ("http", "https"):
        return {"ok": False, "error": "only http/https allowed"}
    if not p.hostname:
        return {"ok": False, "error": "no hostname in URL"}
    if p.username or p.password:
        return {"ok": False, "error": "URLs with credentials not allowed"}
    host = p.hostname.lower()
    for b in _PING_BLOCKED_HOSTS:
        if host == b or host.endswith("." + b):
            return {"ok": False, "error": f"host '{host}' is blocked"}
    # raw IP literal check
    try:
        if _ip_blocked(host):
            return {"ok": False, "error": f"IP {host} is in private/internal range"}
    except ValueError:
        pass

    ok, ip_or_err = _dns_safe(host)
    if not ok:
        return {"ok": False, "error": ip_or_err}
    resolved_ip = ip_or_err

    # HEAD then GET fallback, manual redirects with re-validation
    current = target
    method = "HEAD"
    redirects = 0
    last_err = None
    sess = requests.Session()
    for _ in range(PING_MAX_REDIRECTS + 2):
        # re-validate every hop
        try:
            cp = urlparse(current)
            chost = (cp.hostname or "").lower()
            if not chost:
                return {"ok": False, "error": "redirect has empty hostname"}
            ok2, ie2 = _dns_safe(chost)
            if not ok2:
                return {"ok": False, "error": f"redirect host blocked: {ie2}"}
        except Exception as e:
            return {"ok": False, "error": f"bad redirect: {e}"}
        try:
            t0 = time.perf_counter()
            r = sess.request(
                method, current,
                headers={"User-Agent": PING_UA, "Accept": "*/*", "Connection": "close"},
                allow_redirects=False,
                timeout=PING_TIMEOUT_S,
                verify=True,
            )
            t1 = time.perf_counter()
            r.close()
        except requests.exceptions.ConnectTimeout:
            last_err = f"connection timed out ({int(PING_TIMEOUT_S)}s)"; break
        except requests.exceptions.ReadTimeout:
            last_err = "server read timed out"; break
        except requests.exceptions.SSLError as e:
            last_err = f"TLS error: {e}"; break
        except requests.exceptions.ConnectionError as e:
            if method == "HEAD":
                method = "GET"; continue
            last_err = f"connection error"; break
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"; break
        status = r.status_code
        if status in (301, 302, 303, 307, 308) and r.headers.get("location"):
            if redirects >= PING_MAX_REDIRECTS:
                last_err = f"too many redirects (>{PING_MAX_REDIRECTS})"; break
            nxt = r.headers["location"]
            if nxt.startswith("/"):
                nxt = f"{cp.scheme}://{cp.netloc}{nxt}"
            current = nxt
            redirects += 1
            method = "GET" if status == 303 else "HEAD"
            continue
        if status == 405 and method == "HEAD":
            method = "GET"
            continue
        ms = (t1 - t0) * 1000
        return {
            "ok": True, "target": target, "final_url": current,
            "resolved_ip": resolved_ip, "status": status,
            "latency_ms": round(ms, 2), "redirects": redirects,
            "server": r.headers.get("server", ""),
            "method": method,
        }
    return {"ok": False, "target": target, "resolved_ip": resolved_ip, "error": last_err or "ping failed"}


# ---------------------------------------------------------------------------
# Reply logic (pure function — easy to unit test, no network involved)
# ---------------------------------------------------------------------------
def build_reply(text: str, first_name: str) -> str:
    """Given the raw message text, decide what the bot answers."""
    t = (text or "").strip()
    low = t.lower()

    if low.startswith("/start"):
        return (
            f"👋 Hello {first_name}! CodeNest Bot live achhe!\n\n"
            "Ami ekhon basic — kintu 24/7 thaki. Commands:\n"
            "  /help  — sob command dekhaibo\n"
            "  /echo tomar msg — ami repeat korbo\n"
            "  /time  — somoy dekhaibo\n"
            "Ba ja iccha likhun — echo kore felbo 😄"
        )

    if low.startswith("/help"):
        return (
            "🤖 CodeNest Bot commands:\n\n"
            "/start — intro\n"
            "/help  — ei message\n"
            "/echo <text> — text repeat kore\n"
            "/time  — UTC somoy\n"
            f"/ping [url] — website real response-time (default: {PING_DEFAULT_TARGET})\n\n"
            "/ping server-side e timing kore — Telegram API er delay count hoy na."
        )

    if low.startswith("/echo"):
        payload = t[5:].strip()
        return f"📣 {payload}" if payload else "📣 /echo er pore kichu likhun!"

    if low.startswith("/time"):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return f"🕐 Ekhon: {now}"

    if low.startswith("/ping"):
        # /ping [url]  — server-side latency measurement (NO Telegram hop counted)
        parts = t.split(None, 1)
        target = parts[1].strip() if len(parts) > 1 else PING_DEFAULT_TARGET
        # Run synchronously; the poller is on its own thread so this is fine.
        res = _ping_target(target)
        if not res.get("ok"):
            return (
                f"🌐 *Target:* {res.get('target', target)}\n"
                f"❌ {res.get('error', 'ping failed')}"
            )
        ms = res["latency_ms"]
        if ms < 150: bar = "🟢"
        elif ms < 500: bar = "🟡"
        elif ms < 1500: bar = "🟠"
        else: bar = "🔴"
        s = res["status"]
        bits = [
            f"🌐 *Target:* {res['target']}",
            f"⚡ *Response:* {bar} `{ms:.2f} ms`",
            f"📊 *Status:* `{s}`",
        ]
        ip = res.get("resolved_ip")
        if ip:
            bits.append(f"🖥 *IP:* `{ip}`")
        if res.get("redirects"):
            bits.append(f"↪️ *Redirects:* {res['redirects']}")
        bits.append("")
        bits.append("_server-side timing only — Telegram API delay excluded_")
        return "\n".join(bits)

    # Default: echo back whatever they wrote.
    return f"🪞 Apni likhchen: {t}"


# ---------------------------------------------------------------------------
# Telegram API helpers
# ---------------------------------------------------------------------------
def _tg(method: str, **params) -> dict:
    """Call a Telegram Bot API method; returns the parsed JSON (or {})."""
    if not TG_API:
        return {}
    try:
        r = _http.get(f"{TG_API}/{method}", params=params, timeout=POLL_TIMEOUT_S + 25)
        return r.json()
    except Exception as exc:  # network hiccup — caller retries on next loop
        logger.warning("Telegram %s failed: %s", method, exc)
        return {}


def _send(chat_id: int, text: str) -> None:
    _tg("sendMessage", chat_id=chat_id, text=text)


# ---------------------------------------------------------------------------
# Long-polling loop (runs in a background thread forever)
# ---------------------------------------------------------------------------
def _poll_loop() -> None:
    logger.info("🤖 Bot polling started")
    offset = 0
    while True:
        updates = _tg("getUpdates", offset=offset, timeout=POLL_TIMEOUT_S)

        # Telegram-side rejection (bad token / another instance polling).
        if updates and not updates.get("ok"):
            desc = updates.get("description", "?")
            logger.error("getUpdates error: %s — retrying in %ss", desc, ERROR_BACKOFF_S * 2)
            time.sleep(ERROR_BACKOFF_S * 2)
            continue

        for upd in updates.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat") or {}
            chat_id = chat.get("id")
            text = msg.get("text")
            if not chat_id or not text:
                continue  # ignore photos/stickers/etc for now
            first_name = (msg.get("from") or {}).get("first_name") or "bondhu"
            reply = build_reply(text, first_name)
            _send(chat_id, reply)
            logger.info("↩️  answered %s in chat %s", text[:30], chat_id)

        time.sleep(0.2)  # be polite between empty polls


@app.on_event("startup")
def _start_polling() -> None:
    if not BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot asleep. Web server still up.")
        return
    thread = threading.Thread(target=_poll_loop, name="telegram-poller", daemon=True)
    thread.start()


# ---------------------------------------------------------------------------
# Web endpoints (only for Render health checks + curious visitors)
# ---------------------------------------------------------------------------
@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {
        "service": "ahad-telegram-bot",
        "status": "alive" if BOT_TOKEN else "no token set",
        "note": "Talk to the bot in Telegram. This page is just a health beacon.",
    }


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "bot_configured": bool(BOT_TOKEN)}
