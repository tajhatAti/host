"""Plain-text storage for hosted bot environment variables.

WHY THIS IS PLAIN NOW
---------------------
This module used to Fernet-encrypt `jobs.env` with `JOB_SECRETS_KEY`. On an
install run by one or two people that key is simply one more thing that can be
lost, rotated, or set to a different value on the site than on the runner — and
when it does not match, `unpack_env()` returns `{}`. Every bot that restarts
then comes back WITHOUT its `BOT_TOKEN`: it crash-loops, the dashboard says
"processing", and the owner's bot is effectively gone. That is not a theoretical
risk here; it already cost a user their bot once.

So values are now stored as plain JSON in your own database, which is already
behind your provider's credentials. Secret-looking values are still masked on
the wire (routes/runspace.py's `_public_env`) — that protects a screen share,
and it is independent of how the value is stored.

The function names and signatures are unchanged, so nothing else in the app had
to move: `pack_env()` writes, `unpack_env()` reads.

WHAT STILL UNDERSTANDS THE OLD CIPHERTEXT
-----------------------------------------
Rows written before this change start with `enc:v1:`. `unpack_env()` still
decrypts those (with `JOB_SECRETS_KEY`, or the legacy `RUNNER_SERVICE_SECRET`
fallback), and `migrate_job_envs()` — called on every startup — rewrites them as
plain JSON, in `jobs.env` AND in `runner_nodes.encrypted_secret`. After one boot
with the old key still available, the database holds no ciphertext at all and
the key can be deleted for good.

If ciphertext is found with no usable key, that is logged as an ERROR naming the
job: those tokens are unrecoverable and have to be re-entered in the Env tab.
Loud is the point — the old code returned `{}` and let the bot crash-loop
instead, which looks like a broken bot rather than a missing key.
"""
import base64
import hashlib
import json
import logging
import os

logger = logging.getLogger("codenest-secrets")

# Rows written by the encrypted version. Kept ONLY so they can be read and then
# rewritten as plain JSON — dropping the ability to read them would destroy
# every bot token saved before the change.
LEGACY_PREFIX = "enc:v1:"
PREFIX = LEGACY_PREFIX  # old public name, still referenced elsewhere


def _materials():
    """Key material that can decrypt a legacy row, best first."""
    values = []
    for raw in (os.getenv("JOB_SECRETS_KEY", ""),
                os.getenv("RUNNER_SERVICE_SECRET", "")):
        value = raw.strip()
        if value and value not in values:
            values.append(value)
    return values


def configured():
    """Is a key available that could still unlock OLD ciphertext?

    Kept because callers ask it, but note what it no longer means: nothing is
    encrypted on the way in any more, so this says nothing about how your
    secrets are stored today. Use legacy_rows() for that."""
    return bool(_materials())


def _fernet(material):
    """Imported lazily on purpose: reading a PLAIN row must never depend on a
    crypto library being installed."""
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(str(material or "").encode()).digest())
    return Fernet(key)


def pack_env(values):
    """Store env vars as plain JSON. None when there is nothing to store."""
    values = dict(values or {})
    if not values:
        return None
    return json.dumps(values, separators=(",", ":"), ensure_ascii=False)


def legacy_encrypt(values):
    """Produce a row in the OLD `enc:v1:` format.

    Nothing in the app calls this any more. It exists so the upgrade path stays
    testable: a test can build a genuine pre-change row and prove it is still
    readable and gets rewritten as plain JSON."""
    values = dict(values or {})
    if not values:
        return None
    materials = _materials()
    if not materials:
        raise ValueError("legacy_encrypt needs JOB_SECRETS_KEY (or RUNNER_SERVICE_SECRET)")
    raw = json.dumps(values, separators=(",", ":"), ensure_ascii=False)
    return LEGACY_PREFIX + _fernet(materials[0]).encrypt(raw.encode()).decode()


def _unpack_with_key_index(value):
    """Return (values, key index). -1 = plain text, None = unreadable.

    "Unreadable" is the case that used to be silent. It is logged as an error
    here, and migrate_job_envs() counts it, because the difference between "this
    bot has no env vars" and "this bot's env vars could not be decrypted" is the
    difference between a working bot and a crash-looping one.
    """
    if not value:
        return {}, -1
    text = str(value)
    used = -1
    if text.startswith(LEGACY_PREFIX):
        encrypted = text[len(LEGACY_PREFIX):].encode()
        text = None
        for index, material in enumerate(_materials()):
            try:
                text = _fernet(material).decrypt(encrypted).decode()
                used = index
                break
            except Exception:
                continue
        if text is None:
            logger.error("Legacy encrypted env could not be decrypted with any "
                         "configured key — set JOB_SECRETS_KEY to the value this "
                         "row was written with, or re-enter the secrets by hand")
            return {}, None
    try:
        parsed = json.loads(text)
        return (parsed if isinstance(parsed, dict) else {}), used
    except Exception:
        return {}, None


def unpack_env(value):
    values, _ = _unpack_with_key_index(value)
    return values


def _is_legacy(value) -> bool:
    return str(value or "").startswith(LEGACY_PREFIX)


def legacy_rows() -> int:
    """How many rows are STILL in the old encrypted form.

    Zero after the first startup that had a usable key. Reported by /health and
    the admin overview so "did the upgrade finish?" is a glance, not a guess.
    """
    from database import get_db_connection
    total = 0
    conn = get_db_connection()
    try:
        for table, column in (("jobs", "env"), ("runner_nodes", "encrypted_secret")):
            try:
                rows = conn.execute(f"SELECT {column} AS v FROM {table} "
                                    f"WHERE {column} IS NOT NULL AND {column} != ''").fetchall()
            except Exception:
                continue          # table not created yet (fresh install mid-boot)
            total += sum(1 for r in rows if _is_legacy(dict(r).get("v")))
    finally:
        conn.close()
    return total


def migrate_job_envs():
    """Rewrite every legacy `enc:v1:` row as plain JSON. Runs at startup.

    This is the one-way door out of encryption, and it is why a lost or rotated
    key can never break bot recovery again: after it runs once successfully
    there is no ciphertext left to need a key for.

    Also fills in a missing telegram_token_fingerprint while it has the token in
    hand — the duplicate-poller check needs it, and the plaintext row is the
    first place the token is readable again.
    """
    from database import get_db_connection
    conn = get_db_connection()
    unwrapped = unreadable = runner_secrets = fingerprints = 0
    try:
        rows = conn.execute("SELECT id,env,telegram_token_fingerprint FROM jobs "
                            "WHERE env IS NOT NULL AND env != ''").fetchall()
        for row in rows:
            item = dict(row)
            values, key_index = _unpack_with_key_index(item.get("env"))
            updates = []
            params = []
            if _is_legacy(item.get("env")):
                if key_index is None:
                    unreadable += 1
                    logger.error("Job %s still holds an undecryptable env blob; "
                                 "its BOT_TOKEN must be re-entered", item["id"])
                    continue
                updates.append("env=?")
                params.append(pack_env(values))
                unwrapped += 1
            token = str(values.get("BOT_TOKEN") or "") if values else ""
            if token and not item.get("telegram_token_fingerprint"):
                from services import telegram_detector
                updates.append("telegram_token_fingerprint=?")
                params.append(telegram_detector.token_fingerprint(token))
                fingerprints += 1
            if updates:
                params.append(item["id"])
                conn.execute(f"UPDATE jobs SET {','.join(updates)} WHERE id=?", tuple(params))

        # The runner credentials are the other thing that must survive a key
        # change: an unreadable secret means the site cannot reach the runner at
        # all, so NO bot can be restarted. The column keeps its old name —
        # renaming it would be a schema migration for no benefit.
        try:
            nodes = conn.execute("SELECT id,encrypted_secret FROM runner_nodes "
                                 "WHERE encrypted_secret IS NOT NULL AND encrypted_secret != ''").fetchall()
        except Exception:
            nodes = []
        for node in nodes:
            item = dict(node)
            if not _is_legacy(item.get("encrypted_secret")):
                continue
            values, key_index = _unpack_with_key_index(item.get("encrypted_secret"))
            if key_index is None:
                unreadable += 1
                logger.error("Runner #%s has an undecryptable secret; re-add the "
                             "runner or set JOB_SECRETS_KEY to the old value", item["id"])
                continue
            conn.execute("UPDATE runner_nodes SET encrypted_secret=? WHERE id=?",
                         (pack_env(values), item["id"]))
            runner_secrets += 1

        if unwrapped or runner_secrets or fingerprints:
            conn.commit()
            logger.info("Secrets are stored as plain text: unwrapped %d job env(s), "
                        "%d runner secret(s), %d fingerprint(s) filled in",
                        unwrapped, runner_secrets, fingerprints)
    finally:
        conn.close()
    return {"unwrapped": unwrapped, "runner_secrets": runner_secrets,
            "fingerprints": fingerprints, "unreadable": unreadable,
            "encrypted": False}
