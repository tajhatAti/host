"""Restore bots whose desired 24/7 state survived a service redeploy."""
import asyncio
import logging

from database import get_db_connection
from services import runner_client, secrets_store

logger = logging.getLogger("codenest-job-recovery")


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
    unresolved = 0
    recovered = 0
    for row in rows:
        if row.get("runner_job_id") in live_ids:
            continue
        env = secrets_store.unpack_env(row.get("env"))
        # Never start a Telegram bot without its token: it would crash-loop and
        # make the UI say “processing” while doing no useful work.
        if row.get("telegram_bot_detected") and not env.get("BOT_TOKEN"):
            logger.error("Recovery skipped bot %s: encrypted BOT_TOKEN unavailable", row["id"])
            unresolved += 1
            continue
        body = {
            "language": row.get("language") or "python",
            "code": row.get("code") or "",
            "name": f"u{row['user_id']}-{row['name']}",
            "env": env,
        }
        try:
            response = runner_client._runner_http("POST", "/internal/jobs", body)
            if response.status_code != 201:
                unresolved += 1
                continue
            info = response.json()
            worker = getattr(response, "placed_on", None)
            _remember(row["id"], info["id"], worker)
            try:
                from services import snapshots
                restored = snapshots.restore_snapshot(
                    row["id"], info["id"], overwrite=True, worker=worker)
                if restored.get("restored"):
                    runner_client._runner_http(
                        "POST", f"/internal/jobs/{info['id']}/restart", worker=worker)
            except Exception as exc:
                logger.warning("Recovery snapshot failed for bot %s: %s", row["id"], exc)
            recovered += 1
        except Exception as exc:
            logger.warning("Recovery start failed for bot %s: %s", row["id"], exc)
            unresolved += 1
    if recovered:
        logger.info("Recovered %d desired-running bot(s)", recovered)
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
