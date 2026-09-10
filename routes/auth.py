"""Auth: availability, signup, email OTP, resend, login, logout,
password reset, and TOTP two-factor authentication."""
from typing import Optional, List

from fastapi import APIRouter, Header, HTTPException, Request

from routes.deps import *  # shared kernel (config, helpers, models)


import io
import base64

import pyotp
import qrcode

from services import email as email_service
from services import abuse_control
from services.twofa import _verify_second_factor

router = APIRouter()


class AvailabilityCheck(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None


@router.post("/auth/check-availability")
def check_availability(payload: AvailabilityCheck, request: Request):
    """Early duplicate check for the sign-up form (on blur / before submit).

    Returns which of the two fields is taken by a VERIFIED account, so the UI
    can say \"already registered\" — unverified leftovers don't count as taken,
    matching the /signup rule that refreshes them instead of blocking.
    """
    rate_limit(f"{client_ip(request)}:avail")
    username = (payload.username or "").strip()
    email = (payload.email or "").strip().lower()

    username_taken = False
    email_taken = False
    conn = get_db_connection()
    try:
        if username:
            row = conn.execute(
                "SELECT is_verified FROM users WHERE username = ?", (username,)
            ).fetchone()
            username_taken = bool(row and row["is_verified"] == 1)
        if email:
            row = conn.execute(
                "SELECT is_verified FROM users WHERE email = ?", (email,)
            ).fetchone()
            email_taken = bool(row and row["is_verified"] == 1)
    finally:
        conn.close()

    return {"username_taken": username_taken, "email_taken": email_taken}


@router.post("/signup")
def signup(user: UserSignup, request: Request):
    rate_limit(f"{client_ip(request)}:signup")
    rate_limit_custom(
        f"{client_ip(request)}:signup:daily", 86400, SIGNUP_DAILY_MAX,
        "Too many new accounts from this network today. Please try again tomorrow.")
    if user.agreed_terms is not True:
        raise HTTPException(status_code=400, detail="Please accept the Terms of Use to create an account.")

    # CAPTCHA removed: the arithmetic question stopped no real abuse and cost
    # every genuine user a step. Signup is still protected by the per-IP daily
    # cap (SIGNUP_DAILY_MAX), the rate limiter, and e-mail OTP verification —
    # an address must be real and reachable before the account works.
    # services/captcha.py is kept so a provider can be re-enabled if needed.

    # Device fingerprint (§3) — stored on the account so §4 can aggregate job
    # counts across every account that shares this device.
    fingerprint = normalise_fingerprint(user.fingerprint)
    abuse_control.enforce(fingerprint=fingerprint, ip=client_ip(request), action="signup")

    username = validate_username(user.username)
    email = str(user.email).strip().lower()
    domain = email.rsplit("@", 1)[-1]

    # Gmail-only: compare the FULL domain, never a suffix. endswith("@gmail.com")
    # would happily accept "evil@notgmail.com" — a lookalike bypass.
    if domain not in GMAIL_DOMAINS:
        raise HTTPException(
            status_code=400,
            detail="Only Gmail addresses are supported for email sign-up. "
                   "You can also sign in with Telegram.",
        )

    # Defense-in-depth: the blocklist can no longer be reached through a normal
    # Gmail address, but it still guards against lookalike/punycode tricks and
    # stays in place if the Gmail-only rule is ever relaxed.
    if domain in DISPOSABLE_EMAIL_DOMAINS:
        raise HTTPException(status_code=400, detail="Disposable email addresses are not allowed.")
    password = validate_password(user.password)

    otp = generate_otp()
    hashed_pw = hash_password(password)
    current_time = now_utc_str()

    conn = get_db_connection()
    cursor = conn.cursor()
    inserted_user_id = None

    try:
        existing = cursor.execute(
            "SELECT id, username, email, is_verified FROM users WHERE username = ? OR email = ?",
            (username, email),
        ).fetchone()

        if existing:
            if existing["is_verified"] == 1:
                # Genuinely taken by an active account -> cannot reuse.
                raise HTTPException(status_code=400, detail="Username or email is already taken.")
            # Unverified account from an incomplete signup (e.g. the user lost
            # the OTP page while checking mail). Don't block them: refresh the
            # OTP + password and re-send, so they can finish verifying instead
            # of being stuck on "already taken".
            otp = generate_otp()
            current_time = now_utc_str()
            cursor.execute("""
                UPDATE users SET password=?, otp=?, otp_created_at=?, agreed_terms_at=?,
                    updated_at=?, fingerprint=COALESCE(NULLIF(?, ''), fingerprint), last_ip=?
                WHERE id=?
            """, (hashed_pw, otp, current_time, current_time, current_time,
                  fingerprint, client_ip(request), existing["id"]))
            conn.commit()
            record_signup_attempt(fingerprint)
            email_service.send_email(email, "Verify your CodeNest account", otp, username, "Email Verification")
            return {
                "message": "Welcome back! A fresh verification code was sent to your email.",
                "resent": True,
                "expires_in": OTP_EXPIRY_MINUTES * 60,
            }

        cursor.execute("""
            INSERT INTO users (username, email, password, otp, otp_created_at,
                is_verified, created_at, updated_at, agreed_terms_at,
                fingerprint, last_ip)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
        """, (username, email, hashed_pw, otp, current_time, current_time,
              current_time, current_time, fingerprint, client_ip(request)))
        conn.commit()
        inserted_user_id = cursor.lastrowid
        record_signup_attempt(fingerprint)

        email_service.send_email(email, "Verify your CodeNest account", otp, username, "Email Verification")
        return {"message": "Account created. Check your email for the verification code.", "expires_in": OTP_EXPIRY_MINUTES * 60}

    except HTTPException:
        if inserted_user_id:
            cursor.execute("DELETE FROM users WHERE id = ?", (inserted_user_id,))
            conn.commit()
        raise
    except DBIntegrityError:
        raise HTTPException(status_code=400, detail="Username or email is already taken.")
    finally:
        conn.close()


@router.post("/resend-otp")
def resend_otp(payload: ResendOTP, request: Request):
    username = validate_username(payload.username)
    rate_limit(f"{client_ip(request)}:resend:{username}")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        row = cursor.execute("SELECT id, email, is_verified FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Account not found.")
        if row["is_verified"] == 1:
            return {"message": "Account is already verified."}

        new_otp = generate_otp()
        current_time = now_utc_str()
        cursor.execute("UPDATE users SET otp=?, otp_created_at=?, updated_at=? WHERE id=?",
                        (new_otp, current_time, current_time, row["id"]))
        conn.commit()

        email_service.send_email(row["email"], "Your new verification code", new_otp, username, "Email Verification")
        return {"message": "A new code has been sent to your email.", "expires_in": OTP_EXPIRY_MINUTES * 60}
    finally:
        conn.close()


@router.post("/verify")
def verify_otp(user: UserVerify, request: Request):
    username = validate_username(user.username)
    otp = user.otp.strip()
    rate_limit(f"{client_ip(request)}:verify:{username}")

    if not otp.isdigit() or len(otp) != 6:
        raise HTTPException(status_code=400, detail="Code must be 6 digits.")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        row = cursor.execute(
            "SELECT id, otp, otp_created_at, otp_attempts, is_verified, username, email FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Account not found.")

        if row["is_verified"] == 0:
            db_otp = row["otp"]
            otp_created_at = row["otp_created_at"]
            if not db_otp or not otp_created_at:
                raise HTTPException(status_code=400, detail="No active code found. Please resend.")

            created_time = datetime.fromisoformat(otp_created_at)
            if now_utc() > created_time + timedelta(minutes=OTP_EXPIRY_MINUTES):
                raise HTTPException(status_code=400, detail="Code has expired. Please resend.")
            if db_otp != otp:
                # Wrong-code limiter, server-side: after MAX_OTP_ATTEMPTS wrong
                # tries the code is invalidated and a fresh one is required.
                attempts = (row["otp_attempts"] or 0) + 1
                if attempts >= MAX_OTP_ATTEMPTS:
                    cursor.execute(
                        "UPDATE users SET otp=NULL, otp_created_at=NULL, otp_attempts=0, updated_at=? WHERE id=?",
                        (now_utc_str(), row["id"]))
                    conn.commit()
                    raise HTTPException(status_code=400, detail="Too many incorrect attempts — please request a new code.")
                cursor.execute("UPDATE users SET otp_attempts=?, updated_at=? WHERE id=?",
                               (attempts, now_utc_str(), row["id"]))
                conn.commit()
                raise HTTPException(status_code=400, detail="Incorrect code.")

            cursor.execute("""
                UPDATE users SET is_verified=1, otp=NULL, otp_created_at=NULL, otp_attempts=0, updated_at=?
                WHERE id=?
            """, (now_utc_str(), row["id"]))
            conn.commit()
            record_login_attempt(row["id"], request, success=True, location="Email verification")

        # Auto-login: create a session immediately after successful verification
        _grant_admin_if_configured(row["id"], row["email"])
        token = create_session(row["id"], request, fingerprint=user.fingerprint or "")
        return {"message": "Verification successful!", "token": token, "username": row["username"]}
    finally:
        conn.close()


# ----------------------------
# Login / Logout / Sessions
# ----------------------------
@router.post("/login")
def login(user: UserLogin, request: Request):
    identifier = user.username.strip()
    rate_limit(f"{client_ip(request)}:login:{identifier.lower()}")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if "@" in identifier:
            row = cursor.execute(
                "SELECT id, username, password, is_verified, email, is_suspended FROM users WHERE email = ?", (identifier.lower(),)
            ).fetchone()
        else:
            row = cursor.execute(
                "SELECT id, username, password, is_verified, email, is_suspended FROM users WHERE username = ?", (identifier,)
            ).fetchone()

        if not row or not verify_password(user.password, row["password"]):
            # Record the failed attempt if we could identify the account.
            if row:
                record_login_attempt(row["id"], request, success=False)
            raise HTTPException(status_code=400, detail="Incorrect username/email or password.")
        if row["is_verified"] == 0:
            # Correct credentials, but email not verified yet. Instead of an
            # error, route them straight to verification so they can finish
            # without having to re-signup.
            remaining = OTP_EXPIRY_MINUTES * 60
            try:
                r2 = cursor.execute("SELECT otp_created_at FROM users WHERE id = ?", (row["id"],)).fetchone()
                if r2 and r2["otp_created_at"]:
                    created = datetime.fromisoformat(r2["otp_created_at"])
                    remaining = max(0, OTP_EXPIRY_MINUTES * 60 - int((now_utc() - created).total_seconds()))
            except Exception:
                pass
            return {
                "need_verify": True,
                "username": row["username"],
                "message": "Please verify your email to continue. A code was sent when you signed up.",
                "expires_in": remaining,
            }
        if "is_suspended" in row.keys() and row["is_suspended"]:
            raise HTTPException(
                status_code=403,
                detail="This account is suspended. If you think this is a mistake, contact the site owner.")
    finally:
        conn.close()

    record_login_attempt(row["id"], request, success=True)
    _grant_admin_if_configured(row["id"], row["email"])
    token = create_session(row["id"], request, fingerprint=user.fingerprint or "")
    return {"message": "Login successful!", "username": row["username"], "token": token}


@router.post("/logout")
def logout(authorization: Optional[str] = Header(None)):
    # Idempotent: a double-click, a stale tab, or an already-expired session
    # must NEVER surface "Session expired" — the user asked to be logged out,
    # and being logged out is the end state either way.
    if not authorization:
        return {"message": "Logged out successfully."}
    token = authorization.replace("Bearer ", "").strip()
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id, user_id FROM sessions WHERE token = ?", (token,)).fetchone()
        if row:
            # activity-trail entry first — after the session is gone the
            # client can't post it (and shouldn't see a 401 for trying)
            conn.execute(
                "INSERT INTO activity_log (user_id, action, details, created_at) VALUES (?,?,?,?)",
                (row["user_id"], "info:Signed out", "Session ended", now_utc_str()))
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        return {"message": "Logged out successfully."}
    finally:
        conn.close()




@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request):
    email = str(payload.email).strip().lower()
    rate_limit(f"{client_ip(request)}:forgot:{email}")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        row = cursor.execute("SELECT id, username FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            return {"message": "If this email exists, a reset code has been sent."}

        otp = generate_otp()
        current_time = now_utc_str()
        cursor.execute("""
            UPDATE users SET reset_otp=?, reset_otp_created_at=?, reset_verified=0, updated_at=?
            WHERE id=?
        """, (otp, current_time, current_time, row["id"]))
        conn.commit()

        email_service.send_email(email, "Reset your CodeNest password", otp, row["username"], "Password Reset")
        return {"message": "If this email exists, a reset code has been sent.", "expires_in": OTP_EXPIRY_MINUTES * 60}
    finally:
        conn.close()


@router.post("/verify-reset-otp")
def verify_reset_otp(payload: VerifyResetOTP, request: Request):
    email = str(payload.email).strip().lower()
    otp = payload.otp.strip()
    rate_limit(f"{client_ip(request)}:resetverify:{email}")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        row = cursor.execute(
            "SELECT id, reset_otp, reset_otp_created_at, reset_otp_attempts FROM users WHERE email = ?", (email,)
        ).fetchone()
        if not row or not row["reset_otp"]:
            raise HTTPException(status_code=400, detail="Please request a reset code first.")

        created_time = datetime.fromisoformat(row["reset_otp_created_at"])
        if now_utc() > created_time + timedelta(minutes=OTP_EXPIRY_MINUTES):
            raise HTTPException(status_code=400, detail="Code has expired. Please request a new one.")
        if row["reset_otp"] != otp:
            attempts = (row["reset_otp_attempts"] or 0) + 1
            if attempts >= MAX_OTP_ATTEMPTS:
                cursor.execute(
                    "UPDATE users SET reset_otp=NULL, reset_otp_created_at=NULL, reset_otp_attempts=0, updated_at=? WHERE id=?",
                    (now_utc_str(), row["id"]))
                conn.commit()
                raise HTTPException(status_code=400, detail="Too many incorrect attempts — please request a new code.")
            cursor.execute("UPDATE users SET reset_otp_attempts=?, updated_at=? WHERE id=?",
                           (attempts, now_utc_str(), row["id"]))
            conn.commit()
            raise HTTPException(status_code=400, detail="Incorrect code.")

        cursor.execute("UPDATE users SET reset_verified=1, reset_otp_attempts=0, updated_at=? WHERE id=?", (now_utc_str(), row["id"]))
        conn.commit()
        return {"message": "Code verified. You can now set a new password."}
    finally:
        conn.close()


@router.post("/reset-password")
def reset_password(payload: ResetPassword, request: Request):
    email = str(payload.email).strip().lower()
    new_password = validate_password(payload.new_password)
    rate_limit(f"{client_ip(request)}:resetpw:{email}")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        row = cursor.execute(
            "SELECT id, reset_otp, reset_verified FROM users WHERE email = ?", (email,)
        ).fetchone()
        if not row or row["reset_verified"] != 1 or row["reset_otp"] != payload.otp.strip():
            raise HTTPException(status_code=400, detail="Please verify the reset code first.")

        hashed_pw = hash_password(new_password)
        cursor.execute("""
            UPDATE users SET password=?, reset_otp=NULL, reset_otp_created_at=NULL,
                reset_verified=0, password_changed_at=?, updated_at=?
            WHERE id=?
        """, (hashed_pw, now_utc_str(), now_utc_str(), row["id"]))
        # Reset password -> log out of all devices for safety
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
        conn.commit()
        return {"message": "Password updated successfully. Please sign in again."}
    finally:
        conn.close()


# ----------------------------
# Profile
# ----------------------------


# ----------------------------
# Two-Factor Authentication (2FA)
# ----------------------------
@router.get("/2fa/status")
def get_2fa_status(authorization: Optional[str] = Header(None)):
    user, _ = get_current_user_and_session(authorization)
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM user_2fa WHERE user_id = ?", (user["id"],)).fetchone()
        if not row:
            return {"enabled": False, "backup_codes_count": 0}
        return {
            "enabled": bool(row["is_enabled"]),
            "backup_codes_count": len(json.loads(row["backup_codes"] or "[]"))
        }
    finally:
        conn.close()


@router.post("/2fa/setup")
def setup_2fa(payload: TwoFactorSetup, authorization: Optional[str] = Header(None)):
    user, _ = get_current_user_and_session(authorization)
    conn = get_db_connection()
    try:
        current_time = now_utc_str()
        
        if payload.enable:
            # Generate new TOTP secret
            secret = pyotp.random_base32()
            
            # Generate backup codes (10 × single-use)
            backup_codes = [secrets.token_hex(8) for _ in range(10)]
            
            # Store temporarily (not enabled yet)
            if DIALECT == "postgres":
                conn.execute("""
                    INSERT INTO user_2fa (user_id, secret, is_enabled, backup_codes, created_at, updated_at)
                    VALUES (?, ?, 0, ?, ?, ?)
                    ON CONFLICT (user_id) DO UPDATE SET
                        secret = EXCLUDED.secret,
                        is_enabled = 0,
                        backup_codes = EXCLUDED.backup_codes,
                        updated_at = EXCLUDED.updated_at
                """, (user["id"], secret, json.dumps(backup_codes), current_time, current_time))
            else:
                conn.execute("""
                    INSERT OR REPLACE INTO user_2fa (user_id, secret, is_enabled, backup_codes, created_at, updated_at)
                    VALUES (?, ?, 0, ?, ?, ?)
                """, (user["id"], secret, json.dumps(backup_codes), current_time, current_time))
            conn.commit()
            
            # Generate QR code
            totp = pyotp.TOTP(secret)
            uri = totp.provisioning_uri(name=user["username"], issuer_name="CodeNest")
            
            # Generate QR image
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(uri)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            qr_base64 = base64.b64encode(buffer.getvalue()).decode()
            
            return {
                "secret": secret,
                "qr_code": f"data:image/png;base64,{qr_base64}",
                "backup_codes": backup_codes,
                "message": "Scan the QR code with your authenticator app"
            }
        else:
            # Disabling 2FA is a sensitive action — it MUST go through
            # /2fa/disable, which re-verifies password + a current code.
            raise HTTPException(
                status_code=400,
                detail="To disable 2FA, confirm with your password and an authenticator code."
            )
    finally:
        conn.close()


@router.post("/2fa/disable")
def disable_2fa(payload: TwoFactorConfirm, authorization: Optional[str] = Header(None)):
    """Disable 2FA — requires the account password AND a valid current
    authenticator (or backup) code. One-click disable is never allowed."""
    user, _ = get_current_user_and_session(authorization)
    conn = get_db_connection()
    try:
        if not verify_password(payload.password, user["password"]):
            raise HTTPException(status_code=400, detail="Incorrect password.")
        _verify_second_factor(conn, user["id"], payload.code)
        conn.execute("DELETE FROM user_2fa WHERE user_id = ?", (user["id"],))
        conn.commit()
        _log_security_event(conn, user["id"], "2fa_disabled", "Two-factor authentication was disabled")
        return {"message": "Two-factor authentication disabled."}
    finally:
        conn.close()


@router.post("/2fa/backup-codes")
def regenerate_backup_codes(payload: TwoFactorConfirm, authorization: Optional[str] = Header(None)):
    """Mint 10 fresh single-use backup codes (old ones stop working).
    Requires password + a valid current authenticator code."""
    user, _ = get_current_user_and_session(authorization)
    conn = get_db_connection()
    try:
        if not verify_password(payload.password, user["password"]):
            raise HTTPException(status_code=400, detail="Incorrect password.")
        _verify_second_factor(conn, user["id"], payload.code)
        codes = [secrets.token_hex(8) for _ in range(10)]
        conn.execute("UPDATE user_2fa SET backup_codes=?, updated_at=? WHERE user_id=?",
                     (json.dumps(codes), now_utc_str(), user["id"]))
        conn.commit()
        _log_security_event(conn, user["id"], "2fa_backup_regenerated", "Backup codes were regenerated")
        return {"backup_codes": codes, "message": "New backup codes generated."}
    finally:
        conn.close()


@router.post("/2fa/verify-setup")
def verify_2fa_setup(payload: TwoFactorVerify, authorization: Optional[str] = Header(None)):
    user, _ = get_current_user_and_session(authorization)
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM user_2fa WHERE user_id = ?", (user["id"],)).fetchone()
        if not row or not row["secret"]:
            raise HTTPException(status_code=400, detail="2FA setup not initiated")
        
        if row["is_enabled"]:
            raise HTTPException(status_code=400, detail="2FA is already enabled")
        
        totp = pyotp.TOTP(row["secret"])
        # valid_window=1: tolerate a few seconds of phone clock drift (RFC 6238)
        if not totp.verify(payload.code, valid_window=1):
            raise HTTPException(status_code=400, detail="Invalid verification code")
        
        # Enable 2FA
        conn.execute("UPDATE user_2fa SET is_enabled=1, updated_at=? WHERE user_id=?",
                     (now_utc_str(), user["id"]))
        conn.commit()
        _log_security_event(conn, user["id"], "2fa_enabled", "Two-factor authentication was enabled")

        # Hand the freshly-minted backup codes to the final setup screen so
        # the user can download/copy them (this is the ONLY time they see them).
        codes = json.loads(row["backup_codes"] or "[]")
        return {"message": "2FA enabled successfully!", "backup_codes": codes}
    finally:
        conn.close()


@router.post("/2fa/verify-login")
def verify_2fa_login(payload: TwoFactorVerify, authorization: Optional[str] = Header(None)):
    """Verify 2FA code during login when 2FA is enabled"""
    user, _ = get_current_user_and_session(authorization)
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM user_2fa WHERE user_id = ?", (user["id"],)).fetchone()
        if not row or not row["is_enabled"]:
            raise HTTPException(status_code=400, detail="2FA not enabled")
        
        # Check if it's a backup code
        backup_codes = json.loads(row["backup_codes"] or "[]")
        if payload.code in backup_codes:
            # Remove used backup code
            backup_codes.remove(payload.code)
            conn.execute("UPDATE user_2fa SET backup_codes=? WHERE user_id=?", 
                         (json.dumps(backup_codes), user["id"]))
            conn.commit()
            return {"message": "Backup code accepted", "backup_codes_remaining": len(backup_codes)}
        
        # Verify TOTP (valid_window=1 for clock drift, RFC 6238)
        totp = pyotp.TOTP(row["secret"])
        if not totp.verify(payload.code, valid_window=1):
            raise HTTPException(status_code=400, detail="Invalid 2FA code")
        
        return {"message": "2FA verified successfully"}
    finally:
        conn.close()


# ----------------------------
# Login History
# ----------------------------


# ----------------------------\n# Telegram Login (Widget)\n# ----------------------------\n
import hashlib
import hmac

class TelegramAuthData(BaseModel):
    id: int
    first_name: str
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str
    fingerprint: Optional[str] = None

def _bot_identity_safe():
    """The cached getMe result, or None. Never raises on the auth path."""
    try:
        from app import _bot_identity
        return _bot_identity()
    except Exception:
        return None


class MiniAppAuth(BaseModel):
    init_data: str
    # The SDK's initData and the URL's tgWebAppData are usually the same
    # string, but some clients decode one of them an extra time and a single
    # differing byte fails the HMAC. The browser sends every form it has;
    # accepting whichever verifies weakens nothing, because a candidate is
    # only accepted if it is validly signed with OUR bot token.
    init_data_alt: Optional[List[str]] = None
    fingerprint: Optional[str] = None


@router.post("/auth/telegram/miniapp")
def telegram_miniapp_login(payload: MiniAppAuth, request: Request):
    """Auto-login for the CodeNest Mini App running inside Telegram.

    SEPARATE FROM /auth/telegram ON PURPOSE. Both prove the same Telegram
    identity, but the HMAC key differs — Login Widget uses sha256(token) while
    the Mini App uses HMAC("WebAppData", token). Verified on the same
    data-check string, the two hashes differ, so initData posted to the widget
    route is rejected as tampered. Loosening that route to accept both would
    mean one endpoint with two trust rules.

    Resolution is IDENTICAL though: same telegram_id, same account, whichever
    door the user came through.
    """
    rate_limit(f"{client_ip(request)}:miniapp_login")

    from services import miniapp_auth
    candidates = [payload.init_data] + list(payload.init_data_alt or [])[:3]
    tg, exc = None, None
    for cand in candidates:
        try:
            tg = miniapp_auth.verify_init_data(cand)
            break
        except ValueError as e:
            # Keep the FIRST failure: it describes the value the client
            # considered authoritative, which is the useful one to report.
            exc = exc or e
    if tg is None:
        reason = str(exc)
        # WARNING, not info: this is the only trace of a user who cannot get in,
        # and info level is routinely filtered out in hosting dashboards. It was
        # invisible exactly when it mattered.
        logger.warning("miniapp auth rejected: %s (tried %d payload form%s)",
                       reason, len(candidates), "" if len(candidates) == 1 else "s")

        if reason == "not_configured":
            # The one failure the OPERATOR causes and can fix, so it is named.
            # Hiding it behind a generic message meant a missing env var looked
            # identical to a forged payload, and the Mini App just said
            # "Couldn't connect" forever with no way to tell which it was.
            # NAME BOTH VARIABLES. The code reads BOT_TOKEN first and falls
            # back to TELEGRAM_PING_BOT_TOKEN, and render.yaml documents only
            # the second — so an owner told to "set BOT_TOKEN" may be looking
            # at a dashboard whose field is called something else, and an
            # owner who already set the documented one is left wondering why
            # it was not enough. Either name works; saying so removes the
            # guess.
            raise HTTPException(
                status_code=503,
                detail="Telegram sign-in is not configured on the server. Set "
                       "BOT_TOKEN (or TELEGRAM_PING_BOT_TOKEN) to the token "
                       "from @BotFather and redeploy.")
        if reason == "bad_hash":
            # A rejected signature has exactly two causes and the server cannot
            # tell them apart: a forged payload, or the site verifying with a
            # DIFFERENT bot's token than the one whose Mini App was opened.
            #
            # Naming only the second would MISLEAD a forger — their real
            # problem is that they signed it wrong — so the message states
            # both. It leaks nothing: a forger already knows their hash failed.
            #
            # The BOT ID is included when it is available. A token is
            # "<bot id>:<secret>" and the id half is public — anyone who can
            # message the bot can see it — so printing it lets the owner
            # compare against @BotFather in one glance instead of guessing
            # between four causes that all look identical on a phone. The
            # secret half is never read here.
            shape = miniapp_auth.token_shape()

            # ASK TELEGRAM'S OWN SIGNATURE WHO IS AT FAULT.
            #
            # Everything above this line is inference, and inference is what
            # kept getting it wrong. Telegram also signs initData with its own
            # Ed25519 key, verifiable with nothing but the PUBLIC bot id — so
            # it is independent of whatever is in BOT_TOKEN, and it answers
            # the one question the HMAC cannot:
            #
            #   signature VALID  -> the payload really is from Telegram and
            #                       really is for THIS bot id. The data is
            #                       fine, so the SECRET half of our token is
            #                       the thing that does not match.
            #   signature INVALID-> it was not signed for this bot id at all.
            #
            # getMe cannot distinguish these: it only proves the token is *a*
            # live token, and its answer is cached at boot. That gap is
            # exactly how a deployment could show a healthy /health, a correct
            # @username and a correct bot id while every sign-in failed.
            _tp = {"ok": False, "reason": "unavailable"}
            try:
                _tp = miniapp_auth.third_party_check(
                    payload.init_data, shape.get("bot_id"))
            except Exception:
                pass

            # WHEN THERE IS NO SIGNATURE, ASK TELEGRAM DIRECTLY — AND DO NOT
            # TRUST THE BOOT-TIME CACHE TO ANSWER IT.
            #
            # Older clients omit the Ed25519 `signature`, so the check above
            # returns "no_signature" and cannot decide anything. The remaining
            # question is simply: is the token we hold still a valid token?
            # Telegram keeps exactly ONE valid token per bot — revoking issues
            # a new one and kills the old one immediately — so a 401 from
            # getMe IS the stale-token answer, and a success rules it out.
            #
            # _bot_identity() cannot be used for this: it caches the result of
            # a single getMe at boot and never refreshes. A token replaced in
            # the hosting dashboard after boot, or a boot that ran while
            # Telegram was briefly unreachable, leaves it reporting a stale
            # "ok" — which is precisely how /health could look perfectly
            # healthy while every sign-in failed. This re-checks, live, and
            # miniapp_auth.token_live() caches only briefly so a failing
            # sign-in cannot turn into a request storm against Telegram.
            # RUN THIS EVEN WHEN THE SIGNATURE ALREADY PROVED THE POINT.
            #
            # It used to be skipped whenever the Ed25519 check succeeded,
            # because that check had already established the secret is wrong.
            # Reported from production:
            #
            #     tg_signature=VALID token_live=None
            #
            # and None is not an answer — it means the question was never
            # asked. But it is the question whose two answers demand
            # completely different actions from the owner:
            #
            #   token_live=False -> Telegram rejects this token outright. It
            #                       is revoked/dead. Copy the current one.
            #   token_live=True  -> Telegram accepts it as a live token, yet
            #                       signs initData with a different secret.
            #                       Telegram keeps exactly ONE valid token per
            #                       bot, so both cannot describe the same
            #                       string: what is deployed is not the value
            #                       that is in BotFather right now (a second
            #                       env var, an old value pinned in a Blueprint
            #                       or env group, a stale build, a truncated
            #                       paste).
            #
            # Leaving it unasked sent the owner to "Revoke current token" —
            # which is right for the first case and useless for the second.
            # One extra getMe on an ALREADY-FAILING request, cached 60s, is a
            # trivial price for telling those apart.
            _live = {"ok": None}
            try:
                _live = miniapp_auth.token_live()
            except Exception:
                _live = {"ok": None}

            hint = ""
            if not shape.get("looks_valid"):
                hint = (" The value in BOT_TOKEN is not shaped "
                        "like a bot token — it should look like 123456:ABC-DEF.")
            elif _live.get("ok") is False:
                # TELEGRAM ITSELF REJECTS THE TOKEN. The plainest case, and
                # the only one where "revoke and copy again" is the right
                # instruction: the deployed value is dead.
                hint = (f" This server's bot token is no longer valid — "
                        f"Telegram rejects it. Open @BotFather, /mybots, this "
                        f"bot, API Token, and copy the CURRENT token into "
                        f"BOT_TOKEN, then redeploy.")
            elif _tp.get("ok"):
                # TELEGRAM ACCEPTS THE TOKEN, YET SIGNED WITH A DIFFERENT
                # SECRET. Telegram keeps exactly ONE valid token per bot, so
                # these two facts cannot describe the same string: the value
                # this process is running with is not the value BotFather has
                # right now.
                #
                # Telling this owner to "revoke" would be wrong, and it is the
                # mistake the earlier version made: revoking issues a THIRD
                # token, and if the deployment is reading its value from
                # somewhere other than the field being edited — a second env
                # var, an env group or Blueprint that re-applies an old value,
                # a service that was never actually restarted — the new token
                # lands in the same place the last one did and nothing
                # changes. Reported exactly that way: a new bot was created,
                # the token was saved, the error did not move.
                hint = (f" Telegram accepts this server's token as valid, but "
                        f"it is signing sign-ins for bot ID "
                        f"{shape.get('bot_id')} with a DIFFERENT secret. Only "
                        f"one token per bot is ever valid, so the value this "
                        f"deployment is actually running with is not the one "
                        f"in @BotFather now. Re-copy the API Token, confirm "
                        f"no other variable or environment group is "
                        f"overriding it, and make sure the service really "
                        f"restarted.")
            else:
                # Name the bot, not just its number. "bot ID 8719137492" still
                # left the owner comparing digits by hand against BotFather;
                # an @username is something you can recognise at a glance. The
                # identity is cached from a single getMe at boot, so this adds
                # no network call to a failing request.
                ident = _bot_identity_safe()
                # SAY WHAT TO DO, NOT JUST WHAT IS WRONG. "Open the Mini App
                # from that bot" is true but assumes the user knows they are
                # not already doing so — and the commonest way to get here is
                # tapping a button in an OLD message from a PREVIOUS bot,
                # which looks identical to the right one. Naming the action
                # ("send /start to @X and use the new button") is what makes
                # it fixable without understanding any of the above.
                if ident and ident.get("username"):
                    # The bot ID is kept alongside the @username: the username
                    # is what a human recognises, the ID is what matches
                    # BotFather and the /health output character for
                    # character. Dropping either costs a check somebody needs.
                    hint = (f" This site signs you in through "
                            f"@{ident['username']} (bot ID "
                            f"{shape.get('bot_id')}). Send /start to "
                            f"@{ident['username']} and open the Mini App from "
                            f"that message — an older bot's button cannot "
                            f"work here.")
                elif shape.get("bot_id"):
                    hint = (f" This site signs you in through bot ID "
                            f"{shape['bot_id']}. Send /start to that bot and "
                            f"open the Mini App from its message — an older "
                            f"bot's button cannot work here.")
            # Log the payload's SHAPE. A token that getMe confirms is the right
            # bot, plus a hash that still does not match, means the bytes we
            # signed differ from the bytes Telegram signed — and the field list
            # is the only thing that can show where.
            _age = getattr(exc, "age_s", None)
            _culprit = getattr(exc, "culprit", None)
            logger.warning(
                "miniapp bad_hash: bot_id=%s fields=%s lengths=%s culprit=%s "
                "age_s=%s tg_signature=%s token_live=%s",
                shape.get("bot_id"), getattr(exc, "fields", "?"),
                getattr(exc, "lengths", "?"), _culprit, _age,
                _tp.get("reason") if not _tp.get("ok") else "VALID",
                _live.get("ok"))

            # Telegram rejecting our token is the plainest possible answer,
            # and it is now CHECKED at the moment of failure rather than
            # inherited from a boot-time cache that may predate the problem.
            if _live.get("ok") is False and _live.get("reason") != "not_configured":
                logger.error(
                    "TELEGRAM REJECTED THIS SERVER'S BOT TOKEN (getMe: %s), "
                    "checked just now — not from the boot-time cache. The "
                    "token in BOT_TOKEN is dead, which is why every sign-in "
                    "fails while the bot id still looks correct. FIX: "
                    "@BotFather -> /mybots -> this bot -> API Token, copy the "
                    "CURRENT value into BOT_TOKEN and redeploy.",
                    _live.get("detail", ""))

            # THE PROVEN CASE COMES FIRST, because it is the only one that is
            # not an inference. Telegram's own signature says the payload is
            # authentic and addressed to our bot id; our HMAC disagrees; the
            # only remaining variable is the secret we hold.
            if _tp.get("ok"):
                if _live.get("ok"):
                    # THE TWO FACTS TOGETHER NARROW IT TO ONE THING.
                    #
                    #   Ed25519 valid  -> the payload is authentic, issued for
                    #                     THIS bot id, and byte-identical to
                    #                     what Telegram signed. (The Ed25519
                    #                     and HMAC data-check strings are the
                    #                     same bytes apart from a bot-id
                    #                     prefix, and both are built from the
                    #                     same parse, so this also clears the
                    #                     whole family of decoding bugs.)
                    #   getMe ok       -> the token this process holds is a
                    #                     VALID token for that same bot.
                    #
                    # Telegram keeps exactly one valid token per bot. A valid
                    # token that nonetheless does not verify a payload signed
                    # for its own bot cannot be the token Telegram is signing
                    # with — so the process is holding a value that is no
                    # longer the one in BotFather, even though it was valid
                    # when it was captured.
                    #
                    # Which means the fix is NOT "revoke again". It is to find
                    # out why the running process disagrees with the field the
                    # owner is editing.
                    logger.error(
                        "TOKEN IS VALID BUT IS NOT THE SIGNING TOKEN (bot id "
                        "%s). Telegram's own Ed25519 signature validates this "
                        "payload for this bot, AND getMe accepts the token "
                        "this process is using — but the HMAC does not match, "
                        "so Telegram signed with a different secret. Only one "
                        "token per bot is valid at a time, therefore the value "
                        "THIS PROCESS loaded is not the one BotFather holds "
                        "now. Do NOT revoke again; that just adds a third "
                        "token. Check, in this order: (1) another env var or "
                        "environment group overriding BOT_TOKEN — see "
                        "/health telegram_token_source; (2) an old value "
                        "pinned in render.yaml / a Blueprint / an env group "
                        "that is re-applied on deploy; (3) the service not "
                        "actually restarted after the edit (this process reads "
                        "BOT_TOKEN once, at import); (4) a truncated or "
                        "partially-selected paste. Configured bot id: %s.",
                        shape.get("bot_id"), shape.get("bot_id"))
                else:
                    logger.error(
                        "TELEGRAM'S OWN SIGNATURE VALIDATES THIS PAYLOAD FOR "
                        "BOT ID %s, BUT OUR HMAC DOES NOT, and getMe could not "
                        "confirm the token (%s). The data is authentic, so the "
                        "SECRET half of the configured token is wrong. FIX: "
                        "@BotFather -> /mybots -> this bot -> API Token, copy "
                        "the CURRENT value into BOT_TOKEN and redeploy.",
                        shape.get("bot_id"), _live.get("reason"))
                raise HTTPException(
                    status_code=400,
                    detail="Telegram could not verify this session." + hint)

            # THE "YOUR TOKEN IS STALE" VERDICT USED TO LIVE HERE, AND IT WAS
            # WRONG — not occasionally, but STRUCTURALLY. Removed after being
            # reproduced end to end.
            #
            # It fired when `_tok_ok and _id_agrees and culprit is None and
            # age < 300`, where
            #
            #     _tok_ok    = the token is shaped like a token
            #     _id_agrees = str(getMe(OUR token).id) == id parsed from OUR token
            #
            # Both sides of _id_agrees come from the SAME token, and Telegram
            # can only ever answer getMe with the id inside the token it was
            # called with. So _id_agrees is a TAUTOLOGY: it is True for every
            # live token and the comparison can detect nothing. Verified by
            # running it against a live token and a substituted id — the only
            # way to make it False is an answer Telegram never gives.
            #
            # The consequence is the bug the owner actually hit. Any fresh
            # bad_hash from a well-formed, live token — including the ordinary
            # case of the Mini App being opened from a DIFFERENT bot — took
            # this branch and was reported as "your token is out of date". So:
            #
            #   * the advice was to re-copy the token, which changes nothing,
            #   * the `hint` built directly above, which NAMES the bot this
            #     server accepts, was unreachable — the one sentence that
            #     would have solved it,
            #   * and getMe had just returned ok=True, i.e. Telegram had just
            #     confirmed the token is live, while we told the owner it was
            #     revoked. A genuinely revoked token answers getMe with 401,
            #     which whoami() already reports as rejected_by_telegram, and
            #     start_bot() already logs loudly at boot. That real case was
            #     never the one reaching this branch.
            #
            # Reproduced: server holding bot B's live token, payload signed by
            # bot A -> HTTP 503 "The server's Telegram token is out of date",
            # while the same payload verified perfectly under bot A's token.
            # Nothing was stale. Only the two bots differed.
            #
            # What the server can honestly say is exactly what `hint` says:
            # which bot it accepts. That is a fact, it is public, and it is
            # actionable in one tap. So the specific-but-false 503 is gone and
            # the true 400 is what every bad_hash now returns.
            #
            # ONE MORE FACT WORTH REPORTING: the field set. Telegram includes
            # query_id when the Mini App is launched from a button inside a
            # chat message, and chat_type/chat_instance when it is opened from
            # the menu button or a direct t.me link. A failing open carrying
            # query_id therefore came from a MESSAGE BUTTON — and after
            # switching bots, the likeliest such button is an old message from
            # the old bot, still sitting in the chat and still tappable. That
            # is a five-second check the owner can make, so the log says it.
            _from_message_button = "query_id" in (getattr(exc, "fields", None) or [])
            if _from_message_button:
                logger.error(
                    "MINI APP OPENED FROM AN OLD MESSAGE BUTTON. This payload "
                    "carries query_id, which Telegram only sends when the app "
                    "is launched from a button inside a chat message (the menu "
                    "button and t.me links send chat_type/chat_instance "
                    "instead). If you recently switched bots, an old message "
                    "from the OLD bot still has a working button that opens "
                    "this same URL — and it is signed with the OLD bot's "
                    "token, so it can never verify here. Send /start to the "
                    "CURRENT bot and use the button in the NEW message, or the "
                    "menu button beside the input box.")
            else:
                logger.error(
                    "MINI APP SIGNED BY A DIFFERENT BOT. This server verifies "
                    "with bot id %s. The payload is %ss old and its fields "
                    "decode cleanly, so the data is intact — it was simply "
                    "signed with another bot's token. Open the Mini App from "
                    "the bot whose token is in BOT_TOKEN.",
                    shape.get("bot_id"), _age)

            raise HTTPException(
                status_code=400,
                detail="Telegram could not verify this session." + hint)
        if reason in ("expired", "future"):
            raise HTTPException(
                status_code=400,
                detail="This Telegram session has expired. Close the Mini App "
                       "and open it again.")
        # Malformed / no_user / no_hash: nothing the user can act on, and the
        # detail would only help someone probing.
        raise HTTPException(status_code=400, detail="Could not verify Telegram sign-in.")

    tg_id = tg["id"]
    label = miniapp_auth.display_name(tg)

    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (tg_id,)).fetchone()
        if row:
            if "is_suspended" in row.keys() and row["is_suspended"]:
                raise HTTPException(status_code=403, detail="Account is suspended.")
            # Refresh the cached handle: a user who changed their @name would
            # otherwise show a stale one in the dashboard and admin console
            # forever, since the bot only writes it at link time.
            if label:
                conn.execute(
                    "UPDATE users SET telegram_name = ?, updated_at = ? WHERE id = ?",
                    (label, now_utc_str(), row["id"]))
                conn.commit()
            token = create_session(row["id"], request,
                                   fingerprint=payload.fingerprint or "")
            return {"message": "Signed in via Telegram", "token": token,
                    "username": row["username"], "created": False}

        # No account for this Telegram id yet. Mirrors /auth/telegram exactly,
        # including the username-clash fallback that used to 500 on a UNIQUE
        # violation.
        base_username = f"tg_{tg_id}"
        username = base_username
        for _attempt in range(6):
            clash = conn.execute("SELECT id FROM users WHERE username = ?",
                                 (username,)).fetchone()
            if not clash:
                break
            username = f"{base_username}_{secrets.token_hex(3)}"
        email = f"tg_{tg_id}@telegram.user"
        password = hash_password(secrets.token_urlsafe(16))
        now = now_utc_str()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, email, password, is_verified, "
            "telegram_id, telegram_name, created_at, updated_at) "
            "VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
            (username, email, password, tg_id, label or None, now, now))
        conn.commit()
        user_id = cursor.lastrowid
    finally:
        conn.close()

    token = create_session(user_id, request, fingerprint=payload.fingerprint or "")
    return {"message": "Account created via Telegram", "token": token,
            "username": username, "created": True}


@router.post("/auth/telegram")
def telegram_login(payload: TelegramAuthData, request: Request):
    rate_limit(f"{client_ip(request)}:telegram_login")

    bot_token = (os.getenv("BOT_TOKEN", "").strip()
                 or os.getenv("TELEGRAM_PING_BOT_TOKEN", "").strip())
    if not bot_token:
        raise HTTPException(status_code=500, detail="Telegram login not configured.")

    # Verify HMAC-SHA256 over the data-check-string, exactly as Telegram
    # specifies: "key=value" lines for every NON-EMPTY field, sorted by key,
    # joined with \n. Iterating a dict yields KEYS only — unpacking those as
    # (k, v) raised ValueError and turned every login into a 500.
    fields = {
        "auth_date": payload.auth_date,
        "first_name": payload.first_name,
        "id": payload.id,
        "photo_url": payload.photo_url or "",
        "username": payload.username or "",
    }
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    data_check = "\n".join(
        f"{k}={v}" for k, v in sorted(fields.items()) if v not in (None, "")
    )
    calculated_hash = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, payload.hash):
        raise HTTPException(status_code=400, detail="Invalid Telegram authentication data.")

    # Replay protection: Telegram signs auth_date, so a leaked payload would
    # otherwise stay valid forever. Telegram's own guidance is to reject
    # anything older than a day.
    age_s = time.time() - payload.auth_date
    if age_s > 86400 or age_s < -300:
        raise HTTPException(status_code=400, detail="Telegram login expired. Please try again.")

    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (payload.id,)).fetchone()

        if row:
            # sqlite3.Row has no .get() — use the same key-probe the rest of
            # the codebase uses so this works on SQLite *and* Postgres.
            if "is_suspended" in row.keys() and row["is_suspended"]:
                raise HTTPException(status_code=403, detail="Account is suspended.")
            token = create_session(row["id"], request, fingerprint=payload.fingerprint or "")
            return {"message": "Login successful via Telegram", "token": token, "username": row["username"]}

        # Create new account. The natural username is tg_<id>, but an existing
        # e-mail account may already own that name — fall back to a suffixed
        # variant instead of dying with a UNIQUE-constraint 500.
        base_username = f"tg_{payload.id}"
        username = base_username
        for _attempt in range(6):
            clash = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if not clash:
                break
            username = f"{base_username}_{secrets.token_hex(3)}"
        email = f"tg_{payload.id}@telegram.user"
        password = hash_password(secrets.token_urlsafe(16))
        current_time = now_utc_str()

        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, email, password, is_verified, telegram_id, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
        """, (username, email, password, payload.id, current_time, current_time))
        conn.commit()
        user_id = cursor.lastrowid

        token = create_session(user_id, request, fingerprint=payload.fingerprint or "")
        return {"message": "Account created via Telegram", "token": token, "username": username}
    finally:
        conn.close()

