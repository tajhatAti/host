"""Push alerts to a user's Telegram when their app changes state.

WHY A WATCHER AND NOT A CALLBACK
--------------------------------
The runner is a separate service (and, with a worker pool, several). It has no
database and no Telegram token — giving it either would spread credentials
across every box and make each worker able to message any user. So the control
plane polls the fleet it already polls for the dashboard and diffs the result.

WHAT IT WILL NOT DO
-------------------
Notify on every tick. A crash-looping app restarts every few seconds; a naive
watcher would send a message each time and the user would mute the bot, which
loses them the alerts that matter. Rules:

  * only STATE TRANSITIONS are announced, never a steady state
  * a repeated transition for the same app is suppressed for a cool-off window
  * the first observation after a restart of THIS process is recorded silently,
    because everything looks like a transition when you have no prior state
"""
import logging
import os
import threading
import time

from database import get_db_connection
from services import runner_client

logger = logging.getLogger("codenest-app")

WATCH_INTERVAL_S = int(os.getenv("BOT_WATCH_INTERVAL_S", "60"))
# Two alerts about the same app inside this window collapse to one. A bot
# stuck in a restart loop should produce a message, then silence, not a stream.
ALERT_COOLDOWN_S = int(os.getenv("BOT_ALERT_COOLDOWN_S", "900"))

_last_state = {}      # runner_job_id -> status
_last_alert = {}      # (runner_job_id, kind) -> ts
_primed = False       # have we seen the fleet at least once?
_lock = threading.Lock()

# Only these transitions are worth a phone buzzing.
_BAD = {"crashed", "offline", "stopped"}
_GOOD = {"running"}


def _send(chat_id, text, buttons=None):
    """Deliver through pingbot so there is ONE place that talks to Telegram."""
    try:
        from services import pingbot
        pingbot._send(chat_id, text, reply_markup=buttons)
    except Exception as exc:
        logger.warning("bot_notify: send failed for chat %s: %s", chat_id, exc)


def _owners() -> dict:
    """runner_job_id -> {chat_id, app name, ...} for every LINKED account.

    Unlinked owners are skipped entirely rather than looked up and discarded:
    there is nowhere to send their alert.
    """
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT j.runner_job_id, j.name, j.id AS job_id, "
            "       u.telegram_id, u.id AS user_id "
            "FROM jobs j JOIN users u ON u.id = j.user_id "
            "WHERE j.runner_job_id IS NOT NULL "
            "  AND u.telegram_id IS NOT NULL "
            "  AND (u.is_suspended IS NULL OR u.is_suspended = 0)"
        ).fetchall()
    finally:
        conn.close()
    return {dict(r)["runner_job_id"]: dict(r) for r in rows}


def _cooled(rid, kind) -> bool:
    key = (rid, kind)
    now = time.time()
    if now - _last_alert.get(key, 0) < ALERT_COOLDOWN_S:
        return False
    _last_alert[key] = now
    return True


def notify_owner(user_id: int, text: str, buttons=None) -> bool:
    """Send to whichever chat this account is linked to. Used for immediate
    events (a rebuild finishing, a disconnect) rather than the poll."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT telegram_id FROM users WHERE id = ? AND telegram_id IS NOT NULL "
            "AND (is_suspended IS NULL OR is_suspended = 0)", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return False
    _send(dict(row)["telegram_id"], text, buttons)
    return True


def check_once() -> dict:
    """One sweep. Returns a summary so a test can assert on it."""
    global _primed
    owners = _owners()
    if not owners:
        return {"checked": 0, "alerts": 0}

    live = runner_client.fleet_jobs()
    sent = 0
    with _lock:
        first_pass = not _primed
        for rid, meta in owners.items():
            info = live.get(rid) or {}
            # A job the fleet does not report is genuinely gone from every
            # worker — distinct from a worker being unreachable, which
            # fleet_jobs() handles by omitting only that worker's jobs. We
            # cannot tell those apart here, so "offline" is only announced
            # when the fleet answered at all.
            status = info.get("status") or ("offline" if live else None)
            if status is None:
                continue
            prev = _last_state.get(rid)
            _last_state[rid] = status

            # Everything is a "change" the first time we look. Recording
            # silently avoids messaging every user on every deploy of the site.
            if first_pass or prev is None or prev == status:
                continue

            reason = info.get("last_exit_reason")
            if status in _BAD and prev in _GOOD:
                if not _cooled(rid, "down"):
                    continue
                why = {
                    "oom": "it went over its memory limit",
                    "crash": "it exited with an error",
                    "manual": "it was stopped",
                    "exit": "it finished and exited",
                }.get(reason, "it stopped running")
                _send(meta["telegram_id"],
                      f"🔴 *{meta['name']}* stopped — {why}.\n\n"
                      f"`/logs {meta['name']}` to see why · "
                      f"`/restart {meta['name']}` to bring it back")
                sent += 1
            elif status in _GOOD and prev in _BAD:
                if not _cooled(rid, "up"):
                    continue
                _send(meta["telegram_id"], f"🟢 *{meta['name']}* is running again.")
                sent += 1
        _primed = True
    return {"checked": len(owners), "alerts": sent}


def _loop():
    while True:
        try:
            check_once()
        except Exception as exc:
            logger.warning("bot_notify sweep failed: %s", exc)
        time.sleep(WATCH_INTERVAL_S)


def start_watcher():
    """Start the state watcher, if the bot is configured at all."""
    if not (os.getenv("BOT_TOKEN", "").strip()
            or os.getenv("TELEGRAM_PING_BOT_TOKEN", "").strip()):
        return False
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    logger.info("bot_notify: watching job state every %ss", WATCH_INTERVAL_S)
    return True
