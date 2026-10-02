"""Owner-only runner fleet diagnostics and recovery helpers.

This module keeps runner-specific queries, health diagnosis, action history and
credential reveal out of routes/admin.py. Secrets are omitted from ordinary
fleet/detail data and can only be fetched by the separately gated reveal route
when an admin explicitly asks to copy the runner setup again.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from urllib.parse import quote

import requests

logger = logging.getLogger("codenest-runner-admin")
_HEALTH_TIMEOUT_S = 8
_EXIT_WORDS = {
    "oom": "Stopped after using more memory than its limit.",
    "crash": "Crashed; open the job detail/log to see the error.",
    "crash_loop": "Stopped after repeated crashes to protect the runner.",
    "manual": "Stopped by an admin or owner.",
    "limit": "Stopped by the runner's resource limit.",
    "isolation": "Stopped by the runner's isolation guard.",
    "exit": "Finished normally.",
    "workspace missing": "Runner could not find this job's saved workspace.",
}


def _db():
    from database import get_db_connection
    return get_db_connection()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def record_action(runner_url: str, action: str, details: str = "", *,
                  job_id: int | None = None, job_name: str = "",
                  actor: str = "system") -> bool:
    """Append a small operational event, separate from analytics/deploy metrics."""
    safe_details = str(details or "")
    try:
        from services import telegram_detector
        safe_details = telegram_detector.TOKEN_RE.sub("[token redacted]", safe_details)
    except Exception:
        pass
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO runner_action_events "
            "(runner_url,job_id,job_name,actor,action,details,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (str(runner_url or "unknown").rstrip("/")[:500],
             int(job_id) if job_id is not None else None,
             str(job_name or "")[:160], str(actor or "system")[:80],
             str(action or "action")[:120], safe_details[:400], _now()),
        )
        conn.commit()
        return True
    except Exception as exc:
        logger.debug("runner action history write failed (%s)", type(exc).__name__)
        return False
    finally:
        conn.close()


def _node(node_id: int) -> dict | None:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id,label,url,enabled,encrypted_secret,created_at,updated_at "
            "FROM runner_nodes WHERE id=?", (int(node_id),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _response_reason(response) -> str:
    status = int(getattr(response, "status_code", 0) or 0)
    body = str(getattr(response, "text", "") or "")[:2000].lower()
    if "suspended by its owner" in body or "service has been suspended" in body:
        return "Render says this service is suspended by its owner. Resume it in Render first."
    if status == 404:
        return "The runner URL returned 404 for /health. Check the deployed service and URL."
    if status in (502, 503, 504):
        return (f"Render returned HTTP {status}; the runner may be sleeping or starting. "
                "Wait a little, then use Check / wake again.")
    if status in (401, 403):
        return f"The public /health check returned HTTP {status}; review the runner's access settings."
    return f"Runner health returned HTTP {status or 'unknown'}, expected 200."


def _exception_reason(exc: Exception) -> str:
    kind = type(exc).__name__
    detail = str(exc).strip()
    if "timeout" in kind.lower() or "timed out" in detail.lower():
        return "Runner health check timed out; Render may still be waking it. Try again shortly."
    if "ssl" in kind.lower() or "tls" in detail.lower():
        return "TLS connection to the runner failed. Check its public URL and Render service state."
    if "name or service not known" in detail.lower() or "getaddrinfo" in detail.lower():
        return "Runner hostname did not resolve. Check the saved service URL and DNS."
    short = detail[:220] if detail else kind
    return f"Could not reach runner ({kind}): {short}"


def _probe(url: str) -> dict:
    result = {"online": False, "checked_at": _now(), "status_code": None,
              "reason": "Runner has not answered yet.", "health": {}}
    try:
        response = requests.get(url.rstrip("/") + "/health", timeout=_HEALTH_TIMEOUT_S)
    except Exception as exc:  # health is best-effort and must not break the panel
        result["reason"] = _exception_reason(exc)
        return result
    result["status_code"] = int(response.status_code)
    if response.status_code != 200:
        result["reason"] = _response_reason(response)
        return result
    try:
        body = response.json() or {}
    except Exception:
        result["reason"] = "Runner returned HTTP 200, but /health was not valid JSON."
        return result
    result.update(online=True, reason="Runner answered /health.", health=body)
    return result


def _main_site_base() -> str:
    return (os.getenv("SITE_BASE_URL", "").strip()
            or os.getenv("SITE_BASE", "").strip()
            or os.getenv("PUBLIC_BASE_URL", "").strip()
            or os.getenv("RENDER_EXTERNAL_URL", "").strip()).rstrip("/")


def _web_url(runner_url: str, info: dict, worker_url: str | None) -> str:
    slug = str(info.get("web_slug") or "").strip().strip("/")
    if not slug or not info.get("web", True):
        return ""
    # A job marked private needs its private access key; never include or return
    # that key in the admin fleet listing.
    if info.get("web_public") is False:
        return ""
    base = _main_site_base() if worker_url == "embedded" else runner_url.rstrip("/")
    return f"{base}/live/{quote(slug, safe='')}/" if base else ""


def _runner_jobs_request(url: str) -> tuple[list[dict], str]:
    try:
        from services import runner_client
        response = runner_client._runner_http("GET", "/internal/jobs", worker=url)
        if response is None:
            return [], "Runner returned no authenticated job-list response."
        if response.status_code != 200:
            try:
                detail = str((response.json() or {}).get("detail") or "")
            except Exception:
                detail = ""
            if response.status_code in (401, 403):
                return [], "Runner is online, but the saved service secret no longer matches."
            if detail:
                return [], f"Authenticated job list returned HTTP {response.status_code}: {detail[:180]}"
            return [], f"Authenticated job list returned HTTP {response.status_code}."
        return list((response.json() or {}).get("jobs") or []), ""
    except Exception as exc:
        return [], _exception_reason(exc)


def _runner_action_history(conn, url: str, label: str, job_ids=()) -> list[dict]:
    out = []
    try:
        where = ["a.target=?"]
        params = [url]
        if label:
            where.append("a.details=?")
            params.append(label)
        if job_ids:
            where.extend("a.target=?" for _ in job_ids)
            params.extend(f"job:{int(job_id)}" for job_id in job_ids)
        rows = conn.execute(
            "SELECT a.action,a.target,a.details,a.created_at,u.username AS admin_name "
            "FROM admin_audit_log a LEFT JOIN users u ON u.id=a.admin_id "
            f"WHERE {' OR '.join(where)} ORDER BY a.id DESC LIMIT 80",
            tuple(params),
        ).fetchall()
        for row in rows:
            item = dict(row)
            out.append({"kind": "runner", "action": item.get("action"),
                        "target": item.get("target"), "details": item.get("details"),
                        "created_at": item.get("created_at"),
                        "admin": item.get("admin_name")})
    except Exception as exc:
        logger.debug("runner control history unavailable (%s)", type(exc).__name__)
    try:
        where = ["runner_url=?"]
        params = [url]
        if job_ids:
            marks = ",".join("?" for _ in job_ids)
            where.append(f"job_id IN ({marks})")
            params.extend(int(value) for value in job_ids)
        events = conn.execute(
            "SELECT runner_url,job_id,job_name,actor,action,details,created_at "
            f"FROM runner_action_events WHERE {' OR '.join(where)} "
            "ORDER BY id DESC LIMIT 80", tuple(params),
        ).fetchall()
        for row in events:
            item = dict(row)
            out.append({"kind": "operation", "action": item.get("action"),
                        "target": item.get("runner_url"), "job_id": item.get("job_id"),
                        "job_name": item.get("job_name"), "details": item.get("details"),
                        "created_at": item.get("created_at"), "actor": item.get("actor")})
    except Exception as exc:
        logger.debug("automatic runner history unavailable (%s)", type(exc).__name__)
    return out


def _configured_node(url: str) -> dict | None:
    """Resolve a runner URL only when it is already in this site's own pool."""
    from urllib.parse import urlparse
    from services import runner_client
    clean = str(url or "").strip().rstrip("/")
    if not clean or clean not in {str(item).rstrip("/") for item in runner_client.runner_pool()}:
        return None
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id,label,url,enabled,encrypted_secret,created_at,updated_at "
            "FROM runner_nodes WHERE url=?", (clean,),
        ).fetchone()
        if row:
            return dict(row)
    finally:
        conn.close()
    return {"id": None, "label": urlparse(clean).hostname or clean, "url": clean,
            "enabled": 1, "created_at": None, "updated_at": None}


def runner_detail(node_id: int) -> dict | None:
    """Current runner health, every assigned job and recorded actions."""
    node = _node(node_id)
    if not node:
        return None
    return _runner_detail_for_node(node)


def runner_detail_for_url(url: str) -> dict | None:
    """Detail for an environment-configured runner, allowlisted by runner_pool()."""
    node = _configured_node(url)
    return _runner_detail_for_node(node) if node else None


def _runner_detail_for_node(node: dict) -> dict | None:
    if not node:
        return None
    url = str(node["url"]).rstrip("/")
    health = _probe(url)
    live, jobs_error = _runner_jobs_request(url)
    live_by_id = {str(item.get("id")): item for item in live if item.get("id")}

    primary = str(os.getenv("RUNNER_SERVICE_URL", "").strip().rstrip("/"))
    include_legacy_default = bool(primary and primary == url)
    conn = _db()
    try:
        if include_legacy_default:
            rows = conn.execute(
                "SELECT j.id,j.name,j.language,j.runner_job_id,j.worker_url,j.desired_state,"
                "j.created_at,j.updated_at,j.telegram_bot_username,j.repo_url,j.repo_entry,"
                "j.repo_commit,j.auto_deploy,u.username AS owner "
                "FROM jobs j JOIN users u ON u.id=j.user_id "
                "WHERE j.worker_url=? OR j.worker_url IS NULL ORDER BY j.id DESC LIMIT 500",
                (url,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT j.id,j.name,j.language,j.runner_job_id,j.worker_url,j.desired_state,"
                "j.created_at,j.updated_at,j.telegram_bot_username,j.repo_url,j.repo_entry,"
                "j.repo_commit,j.auto_deploy,u.username AS owner "
                "FROM jobs j JOIN users u ON u.id=j.user_id "
                "WHERE j.worker_url=? ORDER BY j.id DESC LIMIT 500",
                (url,),
            ).fetchall()
        db_jobs = [dict(row) for row in rows]
        job_ids = [int(row["id"]) for row in db_jobs]
        history = _runner_action_history(conn, url, str(node.get("label") or ""), job_ids)
        deploy_events, revisions = [], []
        if job_ids:
            marks = ",".join("?" for _ in job_ids)
            try:
                evs = conn.execute(
                    "SELECT e.job_id,e.action,e.job_name,e.created_at,u.username AS owner "
                    "FROM job_deploy_events e LEFT JOIN users u ON u.id=e.user_id "
                    f"WHERE e.job_id IN ({marks}) ORDER BY e.id DESC LIMIT 80", tuple(job_ids)
                ).fetchall()
                deploy_events = [dict(e) for e in evs]
            except Exception as exc:
                logger.debug("runner job event history unavailable (%s)", type(exc).__name__)
            try:
                revs = conn.execute(
                    "SELECT job_id,version,action,status,error,created_at,promoted_at "
                    f"FROM bot_revisions WHERE job_id IN ({marks}) ORDER BY id DESC LIMIT 80",
                    tuple(job_ids),
                ).fetchall()
                revisions = [dict(r) for r in revs]
            except Exception as exc:
                logger.debug("runner revision history unavailable (%s)", type(exc).__name__)
    finally:
        conn.close()

    revisions_by_job = {}
    for revision in revisions:
        revisions_by_job.setdefault(int(revision["job_id"]), []).append({
            "version": revision.get("version"), "action": revision.get("action"),
            "status": revision.get("status"), "error": revision.get("error"),
            "created_at": revision.get("created_at"), "promoted_at": revision.get("promoted_at"),
        })
    output_jobs = []
    matched_live_ids = set()
    for row in db_jobs:
        runner_id = str(row.get("runner_job_id") or "")
        info = live_by_id.get(runner_id) or {}
        if info:
            matched_live_ids.add(runner_id)
            status = str(info.get("status") or "unknown")
            status_reason = (_EXIT_WORDS.get(str(info.get("last_exit_reason") or ""),
                                             "The runner reported an exit; see recent logs for the exact reason.")
                             if info.get("last_exit_reason") else "")
        elif not health["online"]:
            status = "unknown"
            status_reason = health.get("reason") or "Assigned runner did not answer."
        elif row.get("desired_state") == "stopped":
            status = "stopped"
            status_reason = "Stopped by request."
        else:
            status = "missing"
            status_reason = "Runner answered but did not list this job; recovery can recreate it from the site's saved source."
        username = str(row.get("telegram_bot_username") or "").strip().lstrip("@")
        output_jobs.append({
            **row,
            "status": status,
            "status_reason": status_reason,
            "restarts": info.get("restarts"),
            "uptime_s": info.get("uptime_s"),
            "mem_mb": info.get("mem_mb"),
            "peak_mem_mb": info.get("peak_mem_mb"),
            "last_exit_reason": info.get("last_exit_reason"),
            "last_exit_text": status_reason,
            "last_exit_code": info.get("last_exit_code"),
            "oom": bool(info.get("oom")),
            "runner_job_id": runner_id or None,
            "web_url": _web_url(url, info, row.get("worker_url")),
            "telegram_bot_url": f"https://t.me/{username}" if username else "",
            "recent_actions": revisions_by_job.get(int(row["id"]), [])[:8],
        })

    # Show runner-only processes too: this helps spot bots left behind by an
    # old deploy or by an interrupted site/database write. Never include code,
    # environment values, working-directory paths, or private access keys.
    for runner_id, info in live_by_id.items():
        if runner_id in matched_live_ids:
            continue
        username = str(info.get("telegram_bot_username") or "").strip().lstrip("@")
        output_jobs.append({
            "id": None, "runner_job_id": runner_id, "name": info.get("name") or "Runner job",
            "language": info.get("language"), "owner": "Not matched in site database",
            "desired_state": "unknown", "status": info.get("status") or "unknown",
            "status_reason": "Runner is running a job with no matching site assignment.",
            "restarts": info.get("restarts"), "uptime_s": info.get("uptime_s"),
            "mem_mb": info.get("mem_mb"), "peak_mem_mb": info.get("peak_mem_mb"),
            "last_exit_reason": info.get("last_exit_reason"),
            "last_exit_text": _EXIT_WORDS.get(str(info.get("last_exit_reason") or ""), ""),
            "last_exit_code": info.get("last_exit_code"), "oom": bool(info.get("oom")),
            "web_url": _web_url(url, info, url),
            "telegram_bot_url": f"https://t.me/{username}" if username else "",
            "orphan": True, "recent_actions": [],
        })

    for event in deploy_events:
        history.append({"kind": "job", "job_id": event.get("job_id"),
                        "job_name": event.get("job_name"), "action": event.get("action"),
                        "created_at": event.get("created_at"), "admin": event.get("owner")})
    for revision in revisions:
        matching = next((j for j in db_jobs if int(j["id"]) == int(revision["job_id"])), {})
        history.append({"kind": "revision", "job_id": revision.get("job_id"),
                        "job_name": matching.get("name"),
                        "action": f"v{revision.get('version')} · {revision.get('action')} · {revision.get('status')}",
                        "details": revision.get("error"), "created_at": revision.get("created_at"),
                        "admin": matching.get("owner")})
    history.sort(key=lambda event: str(event.get("created_at") or ""), reverse=True)

    h = health.get("health") or {}
    return {
        "runner": {
            "id": node["id"], "label": node["label"], "url": url,
            "health_url": f"{url}/health", "enabled": bool(node.get("enabled")),
            "online": bool(health.get("online")), "checked_at": health.get("checked_at"),
            "status_code": health.get("status_code"), "reason": health.get("reason"),
            "jobs": int(h.get("jobs", 0) or 0), "capacity": int(h.get("capacity", 0) or 0),
            "mem_mb": float(h.get("mem_mb", 0) or 0),
            "safe_mb": float(h.get("safe_mb", 0) or 0),
            "free_mb": float(h.get("free_mb", 0) or 0),
            "full": bool(h.get("full", False)),
            "assigned_jobs": len(db_jobs),
            "job_list_error": jobs_error,
            "created_at": node.get("created_at"), "updated_at": node.get("updated_at"),
        },
        "jobs": output_jobs,
        "history": history[:100],
        "setup": {
            "health_url": f"{url}/health",
            "environment_variable": "RUNNER_SERVICE_SECRET",
            "note": "Runner process restart control is not configured here; Check / wake pings health and asks the site's normal recovery loop to restore missing jobs.",
        },
    }


def reveal_runner_secret(node_id: int) -> dict | None:
    """Return credentials only to the caller of the explicit admin reveal route."""
    node = _node(node_id)
    if not node:
        return None
    from services import secrets_store
    env = secrets_store.unpack_env(node.get("encrypted_secret"))
    secret = str((env or {}).get("secret") or "")
    if not secret:
        return {"id": node["id"], "label": node["label"], "url": node["url"], "secret": "",
                "error": "No saved runner secret is available. Re-enter it in the admin setup form."}
    return {"id": node["id"], "label": node["label"], "url": node["url"], "secret": secret,
            "health_url": f"{str(node['url']).rstrip('/')}/health",
            "environment_variable": "RUNNER_SERVICE_SECRET"}


def reveal_runner_secret_for_url(url: str) -> dict | None:
    """Explicit reveal for an already-configured environment runner."""
    node = _configured_node(url)
    if not node:
        return None
    if node.get("id") is not None:
        return reveal_runner_secret(int(node["id"]))
    from services import runner_client
    secret = str(runner_client._secret_for_runner(node["url"]) or "")
    if not secret:
        return {"id": None, "label": node["label"], "url": node["url"], "secret": "",
                "error": "No runner service secret is available in the site environment."}
    return {"id": None, "label": node["label"], "url": node["url"], "secret": secret,
            "health_url": f"{str(node['url']).rstrip('/')}/health",
            "environment_variable": "RUNNER_SERVICE_SECRET"}


def _audit(admin_id: int, action: str, target: str, details: str) -> None:
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO admin_audit_log (admin_id,action,target,details,created_at) VALUES (?,?,?,?,?)",
            (int(admin_id), action, target, (details or "")[:400], _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _recover_after_wake(url: str, admin_id: int) -> None:
    try:
        from services import job_recovery
        unresolved = job_recovery.recover_once()
        detail = f"health=200; recovery sweep finished; unresolved={unresolved}"
    except Exception as exc:
        detail = f"health=200; recovery sweep failed: {type(exc).__name__}: {str(exc)[:220]}"
        logger.exception("runner recovery after wake failed for %s", url)
    try:
        _audit(admin_id, "runner_recovery_sweep", url, detail)
    except Exception:
        logger.exception("could not record runner recovery history")


def wake_runner(node_id: int, admin_id: int) -> dict | None:
    """Ping a runner (which can wake a sleeping host) and queue safe recovery.

    A suspended Render service cannot be resumed with the runner's job secret;
    its owner must resume it in Render. A real provider restart API is not
    configured, so this never claims to restart the host itself.
    """
    node = _node(node_id)
    return _wake_node(node, admin_id) if node else None


def wake_runner_for_url(url: str, admin_id: int) -> dict | None:
    """Health/recovery action for an environment URL already in runner_pool()."""
    node = _configured_node(url)
    return _wake_node(node, admin_id) if node else None


def _wake_node(node: dict, admin_id: int) -> dict:
    url = str(node["url"]).rstrip("/")
    probe = _probe(url)
    _audit(admin_id, "runner_wake_check", url,
           f"online={int(bool(probe['online']))}; {probe.get('reason') or ''}")
    if not probe["online"]:
        return {"ok": False, "online": False, "reason": probe.get("reason"),
                "checked_at": probe.get("checked_at"),
                "message": "Runner did not answer. If Render marks it suspended, resume it in Render first; then press Check / wake again."}
    thread_name = str(node.get("id") or (url.rsplit("/", 1)[-1] or "configured"))[:50]
    threading.Thread(target=_recover_after_wake, args=(url, int(admin_id)),
                     daemon=True, name=f"runner-recover-{thread_name}").start()
    return {"ok": True, "online": True, "checked_at": probe.get("checked_at"),
            "message": "Runner answered. Recovery has been queued; missing desired-running jobs will be restored without starting a second copy on an unreachable runner."}
