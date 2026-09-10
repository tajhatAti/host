"""Explicit admin blocks for abusive networks and device fingerprints.

A shared IP is weak evidence, so blocks are never created automatically. They
only prevent new signups and new jobs; admins can still inspect accounts and
existing users can sign in and retrieve data. Every create/revoke is 2FA-gated
and audited by routes/admin.py.
"""
from datetime import datetime, timezone
from fastapi import HTTPException

from database import get_db_connection


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def active_block(scope: str, value: str):
    if not value:
        return None
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, scope, value, reason, expires_at FROM admin_blocks "
            "WHERE scope=? AND value=? AND revoked_at IS NULL "
            "AND (expires_at IS NULL OR expires_at > ?) ORDER BY id DESC LIMIT 1",
            (scope, value, _now()),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def enforce(*, fingerprint: str = "", ip: str = "", action: str):
    """Reject a new signup/job when an explicit block matches."""
    match = active_block("fingerprint", fingerprint) if fingerprint else None
    match = match or (active_block("ip", ip) if ip else None)
    if not match:
        return
    until = f" until {match['expires_at']} UTC" if match.get("expires_at") else ""
    noun = "account creation" if action == "signup" else "starting new jobs"
    raise HTTPException(
        status_code=403,
        detail=f"This device or network is temporarily restricted from {noun}{until}. Contact support if this is a shared network.",
    )
