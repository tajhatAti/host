"""Bots must come back on their own, however often the runner restarts.

THE FAILURE THIS GUARDS AGAINST
-------------------------------
A Render deploy (or a free-tier spin-down) wipes the runner's in-memory job
registry and, on the free tier, its filesystem too. Every bot that was supposed
to be running 24/7 is now gone, while the site's database still says
desired_state='running'. Before this, the ONLY thing that noticed was a single
recovery pass at SITE startup — so when the RUNNER redeployed on its own, nobody
re-created anything: the dashboard showed the bots as stopped, the owners' bots
were dead, and they stayed dead until someone pressed Restart by hand. That is
how a user's bot "just went away".

TWO PARTS
---------
1. recover_once() — for every desired-running job the fleet no longer has,
   re-create it from the code and env stored in the database, then restore the
   last workspace snapshot (database.db, session.json, data/) so the bot comes
   back with its history, not empty.

2. start_reconciler() — run that same pass forever, every
   JOB_RECOVERY_INTERVAL_S (default 300), instead of once at boot. A runner that
   restarts ten times a day is repaired ten times a day, with nobody involved.

WHY IT CANNOT DUPLICATE A RUNNING BOT
-------------------------------------
The dangerous version of this loop is: the runner is asleep or mid-boot, the
fleet probe comes back empty, and the reconciler "recovers" every job — creating
a second copy of each. Two Telegram pollers on one token fight (409 conflict)
and the owner's bot dies anyway. So a job is only re-created when its own worker
ANSWERED the probe and simply does not have it. A worker that did not answer is
skipped this round and retried on the next one; "no information" never means
"the job is gone".
"""
import asyncio
import logging
import os
import threading
import time

from database import get_db_connection
from services import runner_client, secrets_store

logger = logging.getLogger("codenest-job-recovery")

RECOVERY_INTERVAL_S = int(os.getenv("JOB_RECOVERY_INTERVAL_S", "300") or "0")

_reconciler_started = False
_reconciler_lock = threading.Lock()


def _wanted_rows():
    conn = get_db_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id,user_id,name,language,code,env,runner_job_id,worker_url,"
            "telegram_bot_detected FROM jobs "
            "WHERE desired_state='running' AND runner_job_id IS NOT NULL "
            "ORDER BY id"
        ).fetchall()]
    finally:
        conn.close()


def _remember(job_id, runner_id, worker):
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE jobs SET runner_job_id=?,worker_url=? WHERE id=?",
            (runner_id, worker, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def _answered_workers(wanted: list) -> dict:
    """For each worker these jobs belong to: did it ANSWER just now?

    Answered = any HTTP status below 500 came back, including a 404 or a 401:
    those all prove a live process is on the other end whose job list can be
    trusted. A timeout, a connection error, or a 502/503 from a container still
    booting proves nothing about the jobs — so that worker is marked False and
    its jobs are left alone this round.

    Only workers that actually own a wanted job are probed, and the key is the
    row's own worker_url (None = "the default worker", which _runner_http
    resolves to the embedded runner or the primary one). That keeps this off
    runner_pool()/the database: recovery must not depend on a lookup that can
    itself fail while the runner is down.
    """
    keys = {row.get("worker_url") or None for row in wanted}
    out = {}
    for key in keys:
        try:
            resp = runner_client._runner_http("GET", "/health", worker=key)
            status = getattr(resp, "status_code", 0) or 0
            out[key] = bool(0 < status < 500)
        except Exception as exc:
            logger.info("Recovery: worker %s did not answer (%s) — its jobs are "
                        "left alone until it does", key or "default", exc)
            out[key] = False
    return out


def recover_once():
    """Recreate missing desired-running jobs. Returns unresolved count."""
    rows = _wanted_rows()
    if not rows:
        return 0
    try:
        live = runner_client.fleet_jobs(refresh=True)
    except Exception:
        live = {}
    live_ids = set(live)
    missing = [row for row in rows if row.get("runner_job_id") not in live_ids]
    if not missing:
        return 0
    answered = _answered_workers(missing)
    unresolved = 0
    recovered = 0
    skipped_unreachable = 0
    for row in missing:
        if answered.get(row.get("worker_url") or None) is False:
            # The worker that owns this job never answered, so "missing from the
            # fleet" is our blindness, not its absence. Recreating it now would
            # put a second copy of the same bot — and the same Telegram token —
            # on the box. Wait for the next pass.
            skipped_unreachable += 1
            continue
        env = secrets_store.unpack_env(row.get("env"))
        # Never start a Telegram bot without its token: it would crash-loop and
        # make the UI say “processing” while doing no useful work. With secrets
        # stored as plain text this now only happens when the row genuinely has
        # no token (or is undecryptable legacy ciphertext, which is logged).
        if row.get("telegram_bot_detected") and not env.get("BOT_TOKEN"):
            logger.error("Recovery skipped bot %s: no BOT_TOKEN in its stored env", row["id"])
            unresolved += 1
            continue
        from services import bot_ops
        body = {
            "language": row.get("language") or "python",
            "code": row.get("code") or "",
            "name": f"u{row['user_id']}-{row['name']}",
            "env": env,
            # A 👑 user must come back unlimited too: recovery is a fresh create,
            # and a create without this silently re-applies the default ceiling.
            "mem_limit_mb": bot_ops.mem_limit_for(row["user_id"]),
        }
        try:
            response = runner_client._runner_http("POST", "/internal/jobs", body)
            if response.status_code != 201:
                try:
                    detail = response.json().get("detail", response.text[:200])
                except Exception:
                    detail = response.text[:200]
                logger.error("Recovery rejected for bot %s: runner returned %s — %s",
                             row["id"], response.status_code, detail)
                unresolved += 1
                continue
            info = response.json()
            placed = getattr(response, "placed_on", None)
            _remember(row["id"], info["id"], placed)
            try:
                from services import snapshots
                restored = snapshots.restore_snapshot(
                    row["id"], info["id"], overwrite=True, worker=placed)
                if restored.get("restored"):
                    runner_client._runner_http(
                        "POST", f"/internal/jobs/{info['id']}/restart", worker=placed)
            except Exception as exc:
                logger.warning("Recovery snapshot failed for bot %s: %s", row["id"], exc)
            recovered += 1
        except Exception as exc:
            logger.warning("Recovery start failed for bot %s: %s", row["id"], exc)
            unresolved += 1
    if recovered:
        logger.info("Recovered %d desired-running bot(s)", recovered)
    if skipped_unreachable:
        logger.info("Recovery deferred %d bot(s) until their worker answers",
                    skipped_unreachable)
    return unresolved


async def recover_background():
    """Runner services may also be waking; retry without blocking web startup."""
    await asyncio.sleep(5)
    for attempt in range(3):
        unresolved = await asyncio.to_thread(recover_once)
        if not unresolved:
            return
        if attempt < 2:
            await asyncio.sleep(25)
    logger.warning("Bot recovery finished with %d unresolved bot(s)", unresolved)


def _reconcile_loop():
    # Let the startup pass (recover_background) and the runner's own job
    # re-adoption finish first, so the first sweep is not racing them.
    time.sleep(90)
    while True:
        try:
            recover_once()
        except Exception as exc:  # a sweep must never kill its own thread
            logger.warning("Bot recovery sweep crashed: %s", exc)
        time.sleep(RECOVERY_INTERVAL_S)


def start_reconciler():
    """Start the periodic recovery thread (idempotent).

    This is what makes "I restarted the runner" a non-event: whatever the runner
    lost, the site notices within RECOVERY_INTERVAL_S and puts it back with its
    data. Set JOB_RECOVERY_INTERVAL_S=0 to switch it off.
    """
    global _reconciler_started
    if RECOVERY_INTERVAL_S < 60:
        logger.info("Periodic bot recovery disabled (JOB_RECOVERY_INTERVAL_S=%s)",
                    RECOVERY_INTERVAL_S)
        return
    with _reconciler_lock:
        if _reconciler_started:
            return
        _reconciler_started = True
    threading.Thread(target=_reconcile_loop, name="job-recovery",
                     daemon=True).start()
    logger.info("Periodic bot recovery started (every %ds)", RECOVERY_INTERVAL_S)
