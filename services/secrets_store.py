"""Encrypted-at-rest storage for hosted bot environment variables.

`JOB_SECRETS_KEY` is the primary key. Older deployments used
`RUNNER_SERVICE_SECRET` as an implicit fallback; both are kept in the decrypt
keyring so adding a dedicated key can safely re-wrap existing bot tokens.
"""
import base64
import hashlib
import json
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("codenest-secrets")
PREFIX = "enc:v1:"


def _materials():
    values = []
    for raw in (os.getenv("JOB_SECRETS_KEY", ""),
                os.getenv("RUNNER_SERVICE_SECRET", "")):
        value = raw.strip()
        if value and value not in values:
            values.append(value)
    return values


def _material():
    values = _materials()
    return values[0] if values else ""


def configured():
    return bool(_material())


def _fernet(material=None):
    material = _material() if material is None else str(material or "")
    if not material:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
    return Fernet(key)


def pack_env(values):
    values = dict(values or {})
    if not values:
        return None
    raw = json.dumps(values, separators=(",", ":"), ensure_ascii=False)
    cipher = _fernet()
    if not cipher:
        return raw
    return PREFIX + cipher.encrypt(raw.encode()).decode()


def _unpack_with_key_index(value):
    """Return (values, key index). -1 means plaintext, None means unreadable."""
    if not value:
        return {}, -1
    text = str(value)
    used = -1
    if text.startswith(PREFIX):
        encrypted = text[len(PREFIX):].encode()
        text = None
        for index, material in enumerate(_materials()):
            try:
                text = _fernet(material).decrypt(encrypted).decode()
                used = index
                break
            except (InvalidToken, ValueError):
                continue
        if text is None:
            logger.error("Could not decrypt bot environment with any configured key")
            return {}, None
    try:
        parsed = json.loads(text)
        return (parsed if isinstance(parsed, dict) else {}), used
    except Exception:
        return {}, None


def unpack_env(value):
    values, _ = _unpack_with_key_index(value)
    return values


def migrate_job_envs():
    """Encrypt plaintext and re-wrap legacy runner-key ciphertext.

    This is the recovery path for installations that added JOB_SECRETS_KEY
    after bots already existed. Existing ciphertext can still be decrypted by
    RUNNER_SERVICE_SECRET, then is atomically encrypted with the new primary.
    """
    if not configured():
        logger.warning("JOB_SECRETS_KEY is not configured; bot env secrets are not encrypted at rest")
        return {"migrated": 0, "rewrapped": 0, "configured": False}
    from database import get_db_connection
    conn = get_db_connection()
    migrated = rewrapped = changed = 0
    try:
        rows = conn.execute("SELECT id,env,telegram_token_fingerprint FROM jobs WHERE env IS NOT NULL AND env != ''").fetchall()
        for row in rows:
            item = dict(row)
            values, key_index = _unpack_with_key_index(item.get("env"))
            updates = []
            params = []
            encrypted = str(item.get("env") or "").startswith(PREFIX)
            if values and not encrypted:
                updates.append("env=?")
                params.append(pack_env(values))
                migrated += 1
            elif values and encrypted and key_index not in (None, 0):
                updates.append("env=?")
                params.append(pack_env(values))
                rewrapped += 1
            token = str(values.get("BOT_TOKEN") or "") if values else ""
            if token and not item.get("telegram_token_fingerprint"):
                from services import telegram_detector
                updates.append("telegram_token_fingerprint=?")
                params.append(telegram_detector.token_fingerprint(token))
            if updates:
                params.append(item["id"])
                conn.execute(f"UPDATE jobs SET {','.join(updates)} WHERE id=?", tuple(params))
                changed += 1
        if changed:
            conn.commit()
            logger.info("Bot secret migration: encrypted=%d rewrapped=%d", migrated, rewrapped)
    finally:
        conn.close()
    return {"migrated": migrated, "rewrapped": rewrapped, "configured": True}
