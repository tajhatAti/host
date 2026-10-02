"""Read a bot's environment back off the runner, so a database row this site
cannot decode is never the end of the bot.

WHY THIS EXISTS (this happened in production, it is not theoretical)
--------------------------------------------------------------------
A deploy came up unable to read its own ``jobs.env`` rows, and every affected
bot stopped with "the saved bot token is unavailable" and stayed down until
somebody re-typed the token by hand. Bots with perfectly valid tokens, all dark,
all waiting on a human.

But the site is not the only copy. The runner writes a ``job.json`` manifest into
each job's own directory (runner/app.py:_write_manifest) holding the plain env it
launched the process with, and it serves that file over the internal file
endpoint. So whenever the runner still knows the job — running, stopped, or
adopted after a restart — the variables can be read back and written into the
database again, and the bot starts itself.

    read_manifest_env()      what the runner is actually using
    rescue_job_env(row)      fix ONE row, return the usable env
    rescue_unreadable_rows() boot-time sweep over every broken row

Nothing here knows about keys or ciphers. A rescued row is written back as plain
JSON, which is how variables are stored now (services/secrets_store.py).
"""

from __future__ import annotations

import json
import logging

from database import get_db_connection
# Same timestamp helper every other writer uses, so updated_at stays comparable
# across the jobs table (bot_ops imports it from here too).
from routes.deps import now_utc_str
from services import secrets_store

logger = logging.getLogger("codenest.env_rescue")

# The runner's per-job manifest: name, language, entrypoint, env, repo_url.
MANIFEST_NAME = "job.json"

# Outcome tags, so callers can report honestly instead of guessing which
# branch they took.
FINE = "fine"                # the row was readable; nothing was done
LEGACY_OK = "legacy"         # readable via an old format; rewritten as plain
RESCUED = "rescued"          # row was unreadable, the runner had it, DB fixed
UNAVAILABLE = "unavailable"  # nobody has it — the owner must re-enter the vars

# Result of the most recent boot sweep, reported by /health and the admin
# overview: "did the rescue actually run, and did anything survive it?"
LAST_SWEEP = {"unreadable": 0, "rescued": 0, "unavailable": 0, "names": []}


def _fields(row) -> dict:
    """Accept either a dict or a sqlite3.Row without callers caring."""
    try:
        return dict(row)
    except Exception:                                    # noqa: BLE001
        return {}


def read_manifest_env(runner_job_id: str, worker_url: str = "") -> dict:
    """The env dict from the runner's ``job.json`` for this job, or ``{}``.

    ``{}`` means "the runner could not tell us" — job gone, worker offline,
    manifest missing, or a body we cannot parse. Callers must read that as
    *unknown*, never as "this bot has no variables".
    """
    if not runner_job_id:
        return {}
    # Imported lazily: runner_client pulls in the rest of the service layer, and
    # this module is imported from the startup path.
    from services import runner_client

    try:
        resp = runner_client._runner_http(
            "GET",
            f"/internal/jobs/{runner_job_id}/file?path={MANIFEST_NAME}",
            worker=worker_url or "",
        )
    except Exception as e:                               # noqa: BLE001
        logger.info("env rescue: cannot reach the runner for %s: %s", runner_job_id, e)
        return {}
    if getattr(resp, "status_code", 0) != 200:
        logger.info("env rescue: runner returned %s for %s",
                    getattr(resp, "status_code", "?"), runner_job_id)
        return {}
    try:
        content = (resp.json() or {}).get("content") or ""
        env = (json.loads(content) or {}).get("env") or {}
        if not isinstance(env, dict):
            return {}
    except Exception as e:                               # noqa: BLE001
        logger.info("env rescue: unreadable manifest for %s: %s", runner_job_id, e)
        return {}
    return {k: ("" if v is None else str(v)) for k, v in env.items() if isinstance(k, str)}


def _save_env(job_db_id, env: dict) -> bool:
    """Persist a plain-text env onto the jobs row. False if the write failed."""
    try:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE jobs SET env = ?, updated_at = ? WHERE id = ?",
                         (secrets_store.pack_env(env), now_utc_str(), job_db_id))
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as e:                               # noqa: BLE001
        logger.error("env rescue: could not save the recovered variables for job %s: %s",
                     job_db_id, e)
        return False


def rescue_job_env(row, worker_url: str = "") -> tuple:
    """``(env, outcome)`` for one ``jobs`` row, repairing the row if it can.

    Reads the stored env first. If that decodes, nothing happens. If it does
    not, the runner's copy is fetched and — when it has one — written back as
    plain JSON, so the repair survives and later starts never need rescuing.
    """
    item = _fields(row)
    values, readable = secrets_store.read_env(item.get("env"))
    if readable:
        if str(item.get("env") or "").startswith(secrets_store.LEGACY_PREFIX):
            # Readable only while an old key is still around: rewrite it plain
            # now so the row stops depending on that variable.
            if values and _save_env(item.get("id"), values):
                return values, LEGACY_OK
            return values, LEGACY_OK
        return values, FINE

    rid = item.get("runner_job_id") or ""
    if not rid:
        return {}, UNAVAILABLE
    worker = worker_url or (item.get("worker_url") or "")
    got = read_manifest_env(rid, worker)
    if not got:
        return {}, UNAVAILABLE
    saved = _save_env(item.get("id"), got)
    logger.error(
        "BOT VARIABLES RESCUED — %s (runner job %s) had a stored env this site "
        "could not read. Restored %d variable(s) from the runner's own copy: %s%s",
        item.get("name") or item.get("id"), rid, len(got),
        ",".join(sorted(got))[:160] or "none",
        "" if saved else " — WARNING: the database write failed, this will need rescuing again",
    )
    return got, (RESCUED if saved else UNAVAILABLE)


def unreadable_rows() -> list:
    """Every jobs row whose stored env cannot be decoded right now."""
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT id,user_id,name,runner_job_id,worker_url,env,desired_state "
                "FROM jobs WHERE env IS NOT NULL AND env != '' ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
    except Exception as e:                               # noqa: BLE001
        logger.error("env rescue: cannot read the jobs table: %s", e)
        return []
    out = []
    for row in rows:
        item = _fields(row)
        _values, readable = secrets_store.read_env(item.get("env"))
        if not readable:
            out.append(item)
    return out


def unreadable_count() -> int:
    """How many rows are still unreadable. Zero is the healthy answer."""
    return len(unreadable_rows())


def rescue_unreadable_rows() -> dict:
    """Boot-time sweep: repair every row this site cannot read, from its runner.

    Runs at startup before bot recovery, because a bot with an unreadable env
    cannot be started at all — recovery would otherwise log the same failure
    every cycle and the bot would stay down. The report is exposed on /health
    and the admin overview.
    """
    report = {"unreadable": 0, "rescued": 0, "unavailable": 0, "names": []}
    for item in unreadable_rows():
        report["unreadable"] += 1
        _env, outcome = rescue_job_env(item)
        if outcome == RESCUED:
            report["rescued"] += 1
        else:
            report["unavailable"] += 1
            report["names"].append(str(item.get("name") or item.get("id")))
    if report["rescued"]:
        logger.error("env rescue: restored %d bot(s) from their runner(s) — %s",
                     report["rescued"], ", ".join(report["names"][:10]) or "ok")
    if report["unavailable"]:
        logger.error(
            "env rescue: %d bot(s) have no readable variables anywhere (site or "
            "runner): %s — their owners must re-enter them in the Env tab",
            report["unavailable"], ", ".join(report["names"][:20]))
    LAST_SWEEP.clear()
    LAST_SWEEP.update(report)
    return report
