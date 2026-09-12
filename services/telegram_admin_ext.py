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

ADMIN_HEALTH_MAX_AGE_S = 30


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
