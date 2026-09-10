"""Durable, privacy-conscious usage analytics for the Telegram bot.

Recording is deliberately best-effort: analytics must never stop a command from
running.  We retain routing metadata and command arguments, not message bodies.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import csv
import io
import logging

from database import get_db_connection

logger = logging.getLogger("codenest.bot_analytics")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def record(*, chat_id, event_type, command="", payload="", outcome="ok",
           error="", display_name="", telegram_user_id=None, user_id=None):
    """Store one dispatched update. Never raises into the bot dispatch path."""
    try:
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO bot_events (chat_id, telegram_user_id, user_id, "
                "display_name, event_type, command, payload, outcome, error, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(chat_id), str(telegram_user_id) if telegram_user_id is not None else None,
                 user_id, (display_name or "")[:160], (event_type or "unknown")[:32],
                 (command or "")[:80], (payload or "")[:240], (outcome or "ok")[:24],
                 (error or "")[:500], _now()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("Could not record Telegram bot event")


def usage(days=30, event_limit=200):
    days = max(1, min(int(days or 30), 365))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, chat_id, telegram_user_id, user_id, display_name, event_type, "
            "command, payload, outcome, error, created_at FROM bot_events "
            "WHERE created_at >= ? ORDER BY created_at DESC", (cutoff,)).fetchall()]
    finally:
        conn.close()

    people = {}
    commands = {}
    daily = {}
    failures = 0
    for row in rows:
        cid = row.get("chat_id")
        p = people.setdefault(cid, {"chat_id": cid, "display_name": row.get("display_name") or "",
                                    "user_id": row.get("user_id"), "actions": 0,
                                    "last_seen": row.get("created_at")})
        p["actions"] += 1
        if not p["display_name"] and row.get("display_name"):
            p["display_name"] = row["display_name"]
        if not p["user_id"] and row.get("user_id"):
            p["user_id"] = row["user_id"]
        key = row.get("command") or row.get("event_type") or "unknown"
        c = commands.setdefault(key, {"command": key, "count": 0, "failures": 0})
        c["count"] += 1
        if row.get("outcome") == "error":
            failures += 1
            c["failures"] += 1
        day = (row.get("created_at") or "")[:10]
        daily[day] = daily.get(day, 0) + 1

    plist = sorted(people.values(), key=lambda x: x.get("last_seen") or "", reverse=True)
    linked = sum(1 for p in plist if p.get("user_id"))
    return {
        "days": days, "people": len(plist), "linked_people": linked,
        "unlinked_people": len(plist) - linked, "actions": len(rows),
        "today": daily.get(datetime.now(timezone.utc).strftime("%Y-%m-%d"), 0),
        "failures": failures,
        "daily": [{"day": day, "count": daily[day]} for day in sorted(daily)],
        "commands": sorted(commands.values(), key=lambda x: (-x["count"], x["command"])),
        "users": plist, "events": rows[:event_limit] if event_limit else rows,
    }


def usage_csv(days=30):
    data = usage(days, event_limit=None)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["time", "chat_id", "name", "account_user_id", "type", "command",
                     "target", "outcome", "error"])
    for r in data["events"]:
        writer.writerow([r.get("created_at"), r.get("chat_id"), r.get("display_name"),
                         r.get("user_id"), r.get("event_type"), r.get("command"),
                         r.get("payload"), r.get("outcome"), r.get("error")])
    return "\ufeff" + out.getvalue()
