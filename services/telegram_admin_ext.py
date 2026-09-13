"""Extra admin views for the /admin chat panel: runners, jobs, audit log,
abuse reports, and a security-clusters summary.

WHY A SEPARATE FILE
--------------------
telegram_link.py already holds the user-management admin functions
(admin_overview_stats, set_admin, set_zip_permission, ...). This file adds
the REST of what routes/admin.py exposes on the website, kept apart so
telegram_link.py stays about identity/linking rather than growing into a
second admin.py. Every function here is read-mostly and mirrors an existing
website query — see the matching route in routes/admin.py in each
docstring — so behaviour stays consistent between the two surfaces.
"""

from database import get_db_connection
from services import runner_client
from services import bot_ops
from routes.deps import now_utc_str

ADMIN_HEALTH_MAX_AGE_S = 30


# ── Telegram-level ban — new, not on the website ────────────────────────
# is_suspended on the website always needs a users row to attach to; this
# blocks a raw Telegram id before any account/link exists at all, e.g. for
# someone spamming /start or /code without ever going through the site.

def is_banned(telegram_id: int) -> bool:
    if not telegram_id:
        return False
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT 1 FROM banned_telegram_ids WHERE telegram_id = ?",
                            (telegram_id,)).fetchone()
        return bool(row)
    finally:
        conn.close()


def ban_telegram_id(telegram_id: int, banned_by: int, reason: str = "") -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO banned_telegram_ids (telegram_id, banned_by, reason, created_at) "
            "VALUES (?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET reason=excluded.reason",
            (telegram_id, banned_by, reason, now_utc_str()))
        conn.commit()
    finally:
        conn.close()


def unban_telegram_id(telegram_id: int) -> bool:
    conn = get_db_connection()
    try:
        cur = conn.execute("DELETE FROM banned_telegram_ids WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_banned(limit: int = 30) -> list:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT telegram_id, reason, created_at FROM banned_telegram_ids "
            "ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Per-user job limit override — new, not on the website ──────────────
# MAX_JOBS_PER_USER is currently one fixed number for every account. This
# lets an admin raise (or lower) the ceiling for one specific person
# without touching the global constant.

def set_job_limit_override(user_id: int, limit) -> None:
    """limit=None clears the override, back to the global default."""
    conn = get_db_connection()
    try:
        conn.execute("UPDATE users SET job_limit_override = ?, updated_at = ? WHERE id = ?",
                     (limit, now_utc_str(), user_id))
        conn.commit()
    finally:
        conn.close()


# ── Broadcast — new, not on the website ─────────────────────────────────
# Sending happens in pingbot.py (it already owns _send/rate limiting to
# Telegram's API); this just hands back who to send to.

def all_linked_telegram_ids() -> list:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT telegram_id FROM users WHERE telegram_id IS NOT NULL AND is_suspended = 0"
        ).fetchall()
        return [r["telegram_id"] for r in rows]
    finally:
        conn.close()


# ── Admin-level job control — new, not on the website ───────────────────
# routes/admin.py's job views are read-only (list + detail). An admin
# could not restart, stop, or delete someone ELSE's job without going
# into their own account — bot_ops' restart/stop/delete are deliberately
# owner-scoped (see bot_ops.find_app's docstring) and stay that way; these
# are separate, admin-only entry points into the SAME runner calls.

def admin_find_job(job_id: int) -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def admin_restart_job(job_id: int) -> dict:
    row = admin_find_job(job_id)
    if not row:
        return {"ok": False, "error": "No such job."}
    return bot_ops._act(row["user_id"], str(row["id"]), "restart")


def admin_stop_job(job_id: int) -> dict:
    row = admin_find_job(job_id)
    if not row:
        return {"ok": False, "error": "No such job."}
    return bot_ops._act(row["user_id"], str(row["id"]), "stop")


def admin_delete_job(job_id: int) -> dict:
    row = admin_find_job(job_id)
    if not row:
        return {"ok": False, "error": "No such job."}
    return bot_ops.delete(row["user_id"], str(row["id"]))


# ── Runners / worker pool — mirrors GET /admin/runners ─────────────────

def runners_overview() -> dict:
    conn = get_db_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id,label,url,enabled FROM runner_nodes ORDER BY id"
        ).fetchall()]
    finally:
        conn.close()
    health = runner_client.worker_health(max_age_s=ADMIN_HEALTH_MAX_AGE_S) or {}
    for row in rows:
        h = health.get(row["url"]) or {}
        row.update(online=bool(h.get("online")), jobs=h.get("jobs", 0),
                   capacity=h.get("capacity", 0), mem_mb=h.get("mem_mb", 0))
    embedded = None
    if runner_client.embedded_mode() or runner_client._has_embedded_assignments():
        try:
            h = runner_client._runner_http("GET", "/health", worker="embedded").json()
            embedded = {"online": True, "jobs": h.get("jobs", 0), "capacity": h.get("capacity", 0)}
        except Exception:
            embedded = {"online": False, "jobs": 0, "capacity": 0}
    return {"runners": rows, "embedded": embedded}


def toggle_runner(runner_id: int) -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id,label,enabled FROM runner_nodes WHERE id=?",
                            (runner_id,)).fetchone()
        if not row:
            return None
        new_val = 0 if row["enabled"] else 1
        conn.execute("UPDATE runner_nodes SET enabled=? WHERE id=?", (new_val, runner_id))
        conn.commit()
        return {"id": row["id"], "label": row["label"], "enabled": new_val}
    finally:
        conn.close()


# ── Jobs — mirrors GET /admin/jobs and /admin/jobs/{id}, metadata only ──
# Never the code — same privacy rule the website route follows.

def jobs_recent(limit: int = 8, offset: int = 0) -> list:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT j.id, j.name, j.language, j.runner_job_id, u.username AS owner "
            "FROM jobs j JOIN users u ON u.id = j.user_id "
            "ORDER BY j.id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        total = dict(conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone())["c"]
    finally:
        conn.close()
    live = runner_client.fleet_jobs()
    out = []
    for r in rows:
        d = dict(r)
        info = live.get(d.get("runner_job_id")) or {}
        d["live_status"] = info.get("status") or "unknown"
        out.append(d)
    return out, total


def job_detail(job_id: int) -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT j.id, j.name, j.language, j.created_at, j.runner_job_id, j.worker_url, "
            "j.telegram_bot_username, j.telegram_check_status, "
            "u.username AS owner, u.id AS owner_id, u.is_suspended AS owner_suspended "
            "FROM jobs j JOIN users u ON u.id = j.user_id WHERE j.id = ?", (job_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    d = dict(row)
    live = runner_client.fleet_jobs()
    info = live.get(d.get("runner_job_id")) or {}
    d.update(live_status=info.get("status"), uptime_s=info.get("uptime_s"),
              mem_mb=info.get("mem_mb"), restarts=info.get("restarts"))
    return d


# ── Audit log — mirrors GET /admin/audit-log ────────────────────────────

def audit_log_recent(limit: int = 10) -> list:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT a.id, a.action, a.target, a.created_at, u.username AS admin_name "
            "FROM admin_audit_log a LEFT JOIN users u ON u.id = a.admin_id "
            "ORDER BY a.id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Abuse reports — mirrors GET /admin/abuse-reports ────────────────────

def abuse_reports_open(limit: int = 10) -> list:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, url, reason, status, created_at FROM abuse_reports "
            "WHERE status != 'resolved' ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def resolve_abuse_report(report_id: int) -> bool:
    conn = get_db_connection()
    try:
        cur = conn.execute("UPDATE abuse_reports SET status='resolved' WHERE id=?", (report_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Security clusters — summary only, not a full drill-down. The website's
# fingerprint/IP clustering views are investigative tools meant for a wide
# screen and cross-referencing; a chat message just surfaces the COUNT so
# an admin knows whether it's worth opening the website. ───────────────

def security_clusters_summary() -> dict:
    conn = get_db_connection()
    try:
        fp = dict(conn.execute(
            "SELECT COUNT(*) AS c FROM (SELECT fingerprint FROM users "
            "WHERE fingerprint IS NOT NULL GROUP BY fingerprint HAVING COUNT(*) > 1)"
        ).fetchone())["c"] if _table_has_column(conn, "users", "fingerprint") else 0
        return {"fingerprint_clusters": fp}
    finally:
        conn.close()


def _table_has_column(conn, table, col) -> bool:
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return col in cols
    except Exception:
        return False
