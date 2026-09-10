"""Per-account analytics for the Overview dashboard.

The reference dashboard this is modelled on shows a metric, the change against
the previous period, and the shape of the last few weeks. Those three things
are only honest if the numbers come from events that were actually recorded,
so every figure here is read from tables the product already writes:

  * `jobs`               — what exists, and what is deployed right now
  * `job_deploy_events`  — every deploy / update, with a timestamp
  * `store_installs`     — what was taken from the Store

No sampling, no estimation, and no invented "uptime percentage": a job's
liveness is a runner fact, not something this module may guess at. When a
previous period has nothing to compare against, the delta is reported as
`None` and the UI says "new" instead of printing a fake +100%.

Timestamps are compared as the ISO strings the app already stores, so the
same query runs on SQLite and PostgreSQL (no `julianday`, no `INTERVAL`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _day(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d")


def _delta(current: int, previous: int):
    """Percentage change, or None when there is no baseline to compare to."""
    if not previous:
        return None if not current else None
    return round((current - previous) / previous * 100, 1)


def _count(conn, sql: str, params: tuple) -> int:
    return conn.execute(sql, params).fetchone()["c"]


def overview(conn, user_id: int, days: int = 14) -> dict:
    days = max(1, min(int(days or 14), 90))
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    prev_start = now - timedelta(days=days * 2)

    s, ps, pe = _stamp(start), _stamp(prev_start), _stamp(start)

    # ── KPIs ───────────────────────────────────────────────────────────────
    bots = _count(conn, "SELECT COUNT(*) AS c FROM jobs WHERE user_id = ?", (user_id,))
    bots_new = _count(conn, "SELECT COUNT(*) AS c FROM jobs WHERE user_id = ? AND created_at >= ?",
                      (user_id, s))
    bots_new_prev = _count(conn,
                           "SELECT COUNT(*) AS c FROM jobs WHERE user_id = ?"
                           " AND created_at >= ? AND created_at < ?", (user_id, ps, pe))

    live = _count(conn,
                  "SELECT COUNT(*) AS c FROM jobs WHERE user_id = ? AND runner_job_id IS NOT NULL",
                  (user_id,))
    telegram = _count(conn,
                      "SELECT COUNT(*) AS c FROM jobs WHERE user_id = ? AND telegram_bot_detected = 1",
                      (user_id,))

    deploys = _count(conn,
                     "SELECT COUNT(*) AS c FROM job_deploy_events WHERE user_id = ? AND created_at >= ?",
                     (user_id, s))
    deploys_prev = _count(conn,
                          "SELECT COUNT(*) AS c FROM job_deploy_events WHERE user_id = ?"
                          " AND created_at >= ? AND created_at < ?", (user_id, ps, pe))

    updates = _count(conn,
                     "SELECT COUNT(*) AS c FROM job_deploy_events WHERE user_id = ?"
                     " AND action = 'update' AND created_at >= ?", (user_id, s))
    updates_prev = _count(conn,
                          "SELECT COUNT(*) AS c FROM job_deploy_events WHERE user_id = ?"
                          " AND action = 'update' AND created_at >= ? AND created_at < ?",
                          (user_id, ps, pe))

    installs = _count(conn,
                      "SELECT COUNT(*) AS c FROM store_installs WHERE user_id = ? AND created_at >= ?",
                      (user_id, s))
    installs_prev = _count(conn,
                           "SELECT COUNT(*) AS c FROM store_installs WHERE user_id = ?"
                           " AND created_at >= ? AND created_at < ?", (user_id, ps, pe))

    # ── Daily series, zero-filled so a quiet day is a flat line, not a gap ──
    rows = conn.execute(
        "SELECT created_at FROM job_deploy_events WHERE user_id = ? AND created_at >= ?"
        " ORDER BY created_at", (user_id, s)).fetchall()
    by_day = {}
    for row in rows:
        day = (row["created_at"] or "")[:10]
        if day:
            by_day[day] = by_day.get(day, 0) + 1

    created_rows = conn.execute(
        "SELECT created_at FROM jobs WHERE user_id = ? AND created_at >= ?",
        (user_id, s)).fetchall()
    created_by_day = {}
    for row in created_rows:
        day = (row["created_at"] or "")[:10]
        if day:
            created_by_day[day] = created_by_day.get(day, 0) + 1

    series = []
    for offset in range(days - 1, -1, -1):
        moment = now - timedelta(days=offset)
        key = _day(moment)
        series.append({"day": key,
                       "label": moment.strftime("%d %b"),
                       "deploys": by_day.get(key, 0),
                       "new_bots": created_by_day.get(key, 0)})

    # ── Which bots actually got worked on ──────────────────────────────────
    top = conn.execute(
        "SELECT j.id, j.name, j.language, j.telegram_bot_username,"
        " j.runner_job_id, COUNT(e.id) AS actions"
        " FROM jobs j LEFT JOIN job_deploy_events e"
        "   ON e.job_id = j.id AND e.created_at >= ?"
        " WHERE j.user_id = ?"
        " GROUP BY j.id, j.name, j.language, j.telegram_bot_username, j.runner_job_id"
        " ORDER BY actions DESC, j.updated_at DESC LIMIT 6",
        (s, user_id)).fetchall()

    recent = conn.execute(
        "SELECT action, job_name, telegram_bot_username, created_at"
        " FROM job_deploy_events WHERE user_id = ? ORDER BY created_at DESC LIMIT 8",
        (user_id,)).fetchall()

    return {
        "days": days,
        "range": {"start": _day(start), "end": _day(now),
                  "previous_start": _day(prev_start), "previous_end": _day(start)},
        "kpis": [
            {"key": "bots", "label": "Bots", "value": bots,
             "delta": _delta(bots_new, bots_new_prev), "unit": "new",
             "sub": f"{telegram} Telegram · {bots_new} new this period"},
            {"key": "live", "label": "Deployed now", "value": live, "delta": None,
             "unit": "", "sub": "holding a runner slot this second"},
            {"key": "deploys", "label": "Deploys", "value": deploys,
             "delta": _delta(deploys, deploys_prev), "unit": "",
             "sub": f"{updates} of them updates"},
            {"key": "installs", "label": "Store installs", "value": installs,
             "delta": _delta(installs, installs_prev), "unit": "",
             "sub": "bots started from a store listing"},
        ],
        "series": series,
        "top_bots": [
            {"id": r["id"], "name": r["name"], "language": r["language"],
             "username": r["telegram_bot_username"],
             "live": bool(r["runner_job_id"]), "actions": r["actions"]}
            for r in top
        ],
        "recent": [
            {"action": r["action"], "job_name": r["job_name"],
             "username": r["telegram_bot_username"], "created_at": r["created_at"]}
            for r in recent
        ],
        "totals": {"deploys": deploys, "updates": updates, "installs": installs,
                   "new_bots": bots_new,
                   "previous": {"deploys": deploys_prev, "updates": updates_prev,
                                "installs": installs_prev, "new_bots": bots_new_prev}},
    }
