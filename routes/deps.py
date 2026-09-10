"""Shared kernel for every route module: config, rate limiting, validators,
password hashing, sessions, login history, the authed-user dependency, admin
grant, the security-event logger, and ALL cross-module pydantic models.

Route modules import from here (never from app.py) so there is no circularity:
app.py includes the routers; the routers see only deps + services."""
import os
import re
import json
import hashlib
import time
import secrets
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Optional, List

import bcrypt
import pyotp
from fastapi import HTTPException, Header, Request
from pydantic import BaseModel, EmailStr

from database import (
    get_db_connection,
    init_db,
    DIALECT,
    IntegrityError as DBIntegrityError,
)

logger = logging.getLogger("codenest-app")

OTP_EXPIRY_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES", "10"))
MAX_OTP_ATTEMPTS = int(os.getenv("MAX_OTP_ATTEMPTS", "5"))  # wrong codes before the code dies

USERNAME_REGEX = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")

# ----------------------------
# Simple in-memory rate limiter
# ----------------------------
RATE_LIMIT_WINDOW = 300
RATE_LIMIT_MAX_ATTEMPTS = 6
_attempts = defaultdict(list)


# Master prompt §5: max 3 new accounts per IP per 24h.
SIGNUP_DAILY_MAX = int(os.getenv("SIGNUP_DAILY_MAX", "3"))

# Accepted domains for e-mail sign-up (Gmail-only per §2). Matched against the
# FULL domain — never with endswith(), which "notgmail.com" would satisfy.
GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}

# Disposable / temp-mail blocklist (defense-in-depth, §2).
DISPOSABLE_EMAIL_DOMAINS = {
    "0-mail.com", "10minutemail.com", "20minutemail.com", "33mail.com",
    "burnermail.io", "dispostable.com", "emailondeck.com", "fakeinbox.com",
    "getairmail.com", "getnada.com", "guerrillamail.com", "inbox.lv",
    "mail.ru", "mailcatch.com", "maildrop.cc", "mailinator.com",
    "mailnesia.com", "mintemail.com", "mohmal.com", "moakt.com",
    "sharklasers.com", "spamgourmet.com", "temp-mail.org", "tempmail.com",
    "tempmailo.com", "throwawaymail.com", "trashmail.com", "yopmail.com",
    # Gmail lookalikes seen in the wild
    "gmai.com", "gmial.com", "gnail.com", "notgmail.com",
}


def normalise_fingerprint(raw) -> str:
    """Turn a raw client fingerprint payload into a stable 64-char hex hash.

    The browser sends a JSON blob of device signals. Storing that verbatim is
    wasteful and makes SQL grouping fragile (key order, whitespace), so we hash
    it. Already-hashed values pass through unchanged, which keeps old rows and
    the X-Fingerprint header comparable with freshly captured ones.
    """
    if not raw:
        return ""
    s = raw.strip() if isinstance(raw, str) else json.dumps(raw, sort_keys=True)
    if not s:
        return ""
    if len(s) == 64 and all(c in "0123456789abcdef" for c in s.lower()):
        return s.lower()          # already a sha256 hex digest
    try:
        # Canonicalise JSON so key order can't produce two hashes for one device.
        s = json.dumps(json.loads(s), sort_keys=True, separators=(",", ":"))
    except Exception:
        pass
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()


# --- signup burst detection (§5) -------------------------------------------
# FLAG ONLY, never auto-block: legitimate shared devices (a classroom, a
# cyber-cafe) can produce a burst too, so an admin makes the final call.
SIGNUP_BURST_MAX = int(os.getenv("SIGNUP_BURST_MAX", "5"))
SIGNUP_BURST_WINDOW_S = int(os.getenv("SIGNUP_BURST_WINDOW_S", "3600"))
_signup_events = defaultdict(list)   # fingerprint -> [timestamps]


def record_signup_attempt(fingerprint: str) -> bool:
    """Record a signup for this device. Returns True when it looks like a burst."""
    if not fingerprint:
        return False
    now = time.time()
    cutoff = now - SIGNUP_BURST_WINDOW_S
    events = [t for t in _signup_events[fingerprint] if t > cutoff]
    events.append(now)
    _signup_events[fingerprint] = events
    if len(events) >= SIGNUP_BURST_MAX:
        logger.warning(
            "Signup burst flagged: %d accounts from fingerprint %s… within %ds",
            len(events), fingerprint[:12], SIGNUP_BURST_WINDOW_S)
        return True
    return False


def signup_burst_counts() -> dict:
    """Snapshot of recent signup activity per fingerprint (for the admin view)."""
    cutoff = time.time() - SIGNUP_BURST_WINDOW_S
    out = {}
    for fp, events in _signup_events.items():
        recent = [t for t in events if t > cutoff]
        if recent:
            out[fp] = len(recent)
    return out


def rate_limit_custom(key: str, window_s: int, max_attempts: int, detail: str):
    now = time.time()
    window_start = now - window_s
    _attempts[key] = [t for t in _attempts[key] if t > window_start]
    if len(_attempts[key]) >= max_attempts:
        raise HTTPException(status_code=429, detail=detail)
    _attempts[key].append(now)


def rate_limit(key: str):
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    _attempts[key] = [t for t in _attempts[key] if t > window_start]
    if len(_attempts[key]) >= RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again in a few minutes.")
    _attempts[key].append(now)


def rate_limit_user(user_id, bucket: str, max_attempts: int = 30, window_s: int = 300):
    """Per-ACCOUNT limiter for AUTHENTICATED actions (run code, deploy, restart).

    Never key these buckets by IP: our audience (Telegram bot devs, many on
    Bangladeshi mobile networks) sits behind CGNAT — hundreds of strangers
    share ONE public IP, so an IP-keyed bucket lets random people burn the
    allowance of everyone else on that IP ("Limit reached" with zero usage).
    Per-IP limits stay ONLY on unauthenticated anti-bot routes (signup/login)."""
    rate_limit_custom(
        f"u{user_id}:{bucket}", window_s, max_attempts,
        "You are clicking too fast — wait a few seconds and try again.")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def parse_device(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua:
        os_name = "iOS"
    elif "windows" in ua:
        os_name = "Windows"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Unknown OS"

    if "chrome" in ua and "edg" not in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua and "chrome" not in ua:
        browser = "Safari"
    elif "edg" in ua:
        browser = "Edge"
    else:
        browser = "Browser"

    return f"{browser} on {os_name}"


# ----------------------------
# Models
# ----------------------------
class UserSignup(BaseModel):
    username: str
    email: EmailStr
    password: str
    agreed_terms: Optional[bool] = None
    # Undeclared fields are DROPPED by pydantic. These two were read with
    # getattr() in /signup but never declared, so captcha was always None
    # ("CAPTCHA verification failed" on every single signup) and the device
    # fingerprint the browser sent was silently discarded.
    captcha: Optional[str] = None
    captcha_token: Optional[str] = None   # hCaptcha / Turnstile response
    fingerprint: Optional[str] = None


class UserVerify(BaseModel):
    username: str
    otp: str
    fingerprint: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str
    fingerprint: Optional[str] = None


class ResendOTP(BaseModel):
    username: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyResetOTP(BaseModel):
    email: EmailStr
    otp: str


class ResetPassword(BaseModel):
    email: EmailStr
    otp: str
    new_password: str


class LinkItem(BaseModel):
    label: str
    url: str


class ProfileUpdate(BaseModel):
    phone: Optional[str] = None
    custom_code: Optional[str] = None
    links: Optional[List[LinkItem]] = None


class SessionRevoke(BaseModel):
    session_id: int


class AccountDelete(BaseModel):
    password: str


class TwoFactorSetup(BaseModel):
    enable: bool


class TwoFactorVerify(BaseModel):
    code: str
    temp_token: Optional[str] = None


class TwoFactorConfirm(BaseModel):
    """password + current 2FA code — required for disable / regen backup codes."""
    password: str
    code: str


class ChangePassword(BaseModel):
    current_password: str
    new_password: str
    totp_code: Optional[str] = None

# ----------------------------
# DB Helpers
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_utc_str() -> str:
    return now_utc().isoformat()


init_db()


def validate_username(username: str) -> str:
    username = username.strip()
    if not USERNAME_REGEX.fullmatch(username):
        raise HTTPException(status_code=400, detail="Username must be 3-30 characters (letters, numbers, _, ., - only).")
    return username


def validate_password(password: str) -> str:
    password = password.strip()
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password is too long (max 72 characters).")
    return password


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_token() -> str:
    return secrets.token_hex(32)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


SESSION_TTL_DAYS = 90   # extended from 30 days — users reported being logged out
                        # too often across free-tier cold starts.


def _ensure_column(conn, table: str, column: str, ddl_type: str = "TEXT"):
    """Idempotently ensure `table.column` exists (probe first, then ALTER).

    psycopg2 aborts the whole transaction if any statement raises, so we never
    rely on try/except around ALTER — we check information_schema / PRAGMA and
    only then add the column.
    """
    try:
        # Reuse database._column_exists: it already speaks both dialects and
        # goes through the ?-placeholder translation layer. Hand-rolling the
        # psycopg2 query here (with literal %s interpolation) was fragile.
        from database import _column_exists
        if not _column_exists(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
            conn.commit()
            logger.info("Added missing column %s.%s", table, column)
    except Exception as exc:
        logger.warning("_ensure_column(%s.%s): %s", table, column, exc)
        try:
            conn.rollback()
        except Exception:
            pass


def _ensure_expires_column(conn):
    """Idempotently ensure the `sessions.expires_at` column exists.

    psycopg2 aborts the whole transaction if any statement raises an error,
    so we never rely on a try/except around ALTER — we probe first using
    information_schema / PRAGMA and run ALTER only when the column is missing.
    """
    try:
        from database import DIALECT
        cur = conn.cursor()
        exists = False
        if DIALECT == "postgres":
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='sessions' AND column_name='expires_at'"
            )
            exists = cur.fetchone() is not None
        else:
            cur.execute("PRAGMA table_info(sessions)")
            rows = cur.fetchall() or []
            # PRAGMA returns (cid, name, type, notnull, dflt_value, pk)
            exists = any((r[1] if len(r) > 1 else None) == "expires_at" for r in rows)
        if not exists:
            conn.execute("ALTER TABLE sessions ADD COLUMN expires_at TEXT")
            conn.commit()
        cur.close()
    except Exception as exc:
        logger.warning("_ensure_expires_column: %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass


def create_session(user_id: int, request: Request, fingerprint: str = "") -> str:
    """Create a login session.

    §3 requires the device fingerprint on EVERY auth event, so it is recorded
    here — the one place every auth method (email, OTP verify, Telegram)
    funnels through — on both the session row and the account.
    """
    from datetime import datetime, timedelta, timezone
    token = generate_token()
    device_info = parse_device(request.headers.get("user-agent", ""))
    ip = client_ip(request)
    fingerprint = normalise_fingerprint(fingerprint)
    now = datetime.now(timezone.utc)
    created_at = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_at = (now + timedelta(days=SESSION_TTL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    try:
        _ensure_expires_column(conn)
        # Cap concurrent sessions per user at 10 to keep the table tidy.
        try:
            conn.execute("""
                DELETE FROM sessions WHERE id IN (
                    SELECT id FROM sessions WHERE user_id = ?
                    AND id NOT IN (
                        SELECT id FROM sessions WHERE user_id = ?
                        ORDER BY id DESC LIMIT 9
                    )
                )
            """, (user_id, user_id))
        except Exception:
            # Older SQLite (<3.35) doesn't support LIMIT in sub-DELETE; skip cap.
            try: conn.rollback()
            except Exception: pass
        # Signing in must NEVER depend on an optional analytics column. A
        # missing sessions.fingerprint once made every login 500 with
        # `UndefinedColumn`. Write the session first, without it.
        conn.execute(
            "INSERT INTO sessions (user_id, token, device_info, ip_address, created_at, last_seen, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, token, device_info, ip, created_at, created_at, expires_at),
        )
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass
        raise
    finally:
        conn.close()

    # Best-effort telemetry: device fingerprint + last IP. Isolated in its own
    # connection and swallowed on failure, so a schema gap degrades the abuse
    # signal instead of locking users out.
    if fingerprint or ip:
        conn2 = get_db_connection()
        try:
            _ensure_column(conn2, "sessions", "fingerprint")
            conn2.execute("UPDATE sessions SET fingerprint = ? WHERE token = ?",
                          (fingerprint, token))
            _ensure_column(conn2, "users", "fingerprint")
            _ensure_column(conn2, "users", "last_ip")
            conn2.execute(
                "UPDATE users SET fingerprint = COALESCE(NULLIF(?, ''), fingerprint), last_ip = ? WHERE id = ?",
                (fingerprint, ip, user_id),
            )
            conn2.commit()
        except Exception as exc:  # noqa: BLE001 — never block a login
            logger.warning("session telemetry skipped: %s", exc)
            try: conn2.rollback()
            except Exception: pass
        finally:
            conn2.close()

    return token


def record_login_attempt(user_id: int, request: Request, success: bool, location: Optional[str] = None):
    """Persist a login attempt (success or failure) to login_history.

    Failures here must never break the calling request, so all errors are
    swallowed and only logged. Used by the login/verify flows so the user
    can see a real activity trail on their dashboard.
    """
    try:
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO login_history (user_id, ip_address, device_info, location, success, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, client_ip(request), parse_device(request.headers.get("user-agent", "")),
                  location, 1 if success else 0, now_utc_str()))
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to record login attempt: %s", exc)




def get_current_user_and_session(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated. Please sign in.")

    token = authorization.split(" ", 1)[1].strip()
    conn = get_db_connection()
    try:
        # Lazy migration: add expires_at column if missing (no try/except poison)
        _ensure_expires_column(conn)
        session_row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
        if not session_row:
            raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
        # Expiry check (honours expires_at if set; otherwise fall back to a
        # generous 30-day-from-creation window so legacy sessions still work).
        try:
            from datetime import datetime, timezone, timedelta
            exp = session_row["expires_at"] if "expires_at" in session_row.keys() else None
            if exp:
                exp_dt = datetime.strptime(exp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp_dt:
                    conn.execute("DELETE FROM sessions WHERE id = ?", (session_row["id"],))
                    conn.commit()
                    raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
            else:
                # Legacy session without expires_at: enforce 30 days from created_at
                try:
                    created = datetime.strptime(session_row["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) > created + timedelta(days=SESSION_TTL_DAYS):
                        conn.execute("DELETE FROM sessions WHERE id = ?", (session_row["id"],))
                        conn.commit()
                        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
                except Exception:
                    pass
        except HTTPException:
            raise
        except Exception:
            pass

        user_row = conn.execute("SELECT * FROM users WHERE id = ?", (session_row["user_id"],)).fetchone()
        if not user_row:
            raise HTTPException(status_code=401, detail="Account not found.")
        if "is_suspended" in user_row.keys() and user_row["is_suspended"]:
            raise HTTPException(status_code=401, detail="This account is suspended.")

        # Sliding expiry: if session is >24h old, roll expires_at forward by a
        # full TTL window. This way active users are NEVER kicked out — only
        # truly inactive sessions expire (matches how GitHub/Vercel behave).
        try:
            from datetime import datetime, timezone, timedelta as _td
            exp_str = session_row["expires_at"] if "expires_at" in session_row.keys() else None
            if exp_str:
                exp_d = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                now_d = datetime.now(timezone.utc)
                # If less than (TTL - 1 day) remaining → refresh
                if exp_d - now_d < _td(days=SESSION_TTL_DAYS - 1):
                    new_exp = (now_d + _td(days=SESSION_TTL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute("UPDATE sessions SET expires_at = ? WHERE id = ?", (new_exp, session_row["id"]))
        except Exception:
            pass

        conn.execute("UPDATE sessions SET last_seen = ? WHERE id = ?", (now_utc_str(), session_row["id"]))
        conn.commit()

        return user_row, session_row
    finally:
        conn.close()


def require_role(allowed_roles: List[str]):
    """FastAPI dependency to enforce role-based access control (RBAC)."""
    def role_checker(authorization: Optional[str] = Header(None)):
        user_row, session_row = get_current_user_and_session(authorization)
        user_role = user_row["role"] if "role" in user_row.keys() else "user"
        if user_role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Forbidden: You do not have sufficient privileges for this action.")
        return user_row, session_row
    return role_checker


# ----------------------------
# Static / Health
# ----------------------------
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", os.getenv("ADMIN_EMAIL", "")).split(",")
    if e.strip()
}


def _grant_admin_if_configured(user_id: int, email: str):
    """The owner's account (matched by ADMIN_EMAIL(S) env) gets is_admin=1
    automatically on login/verify — no manual DB editing needed."""
    if not ADMIN_EMAILS or not email:
        return
    if email.lower() not in ADMIN_EMAILS:
        return
    try:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE users SET is_admin=1, updated_at=? WHERE id=? AND (is_admin IS NULL OR is_admin=0)",
                         (now_utc_str(), user_id))
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("admin grant failed for user %s: %s", user_id, exc)




def _log_security_event(conn, user_id: int, action: str, details: str):
    """Fire-and-forget security event into the user-visible activity log."""
    try:
        conn.execute(
            "INSERT INTO activity_log (user_id, action, details, ip_address, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, f"security:{action}", details, "", now_utc_str()),
        )
        conn.commit()
    except Exception:
        pass


# `from routes.deps import *` must also export single-underscore helpers
# (_grant_admin_if_configured, _log_security_event, …) — star imports skip
# them by default unless __all__ says otherwise.
__all__ = [n for n in dir() if not n.startswith("__")]
