"""Everything the Telegram bot does to a user's apps, on the SAME rails the
website uses.

WHY THIS EXISTS
---------------
services/pingbot.py called the runner directly. Measured:

    bot deploys a job  ->  rows in jobs table        : 0
                           jobs visible in /admin/jobs: 0
                           runner actually running    : 1

So a bot-deployed app burned real memory while being invisible to the admin
console, exempt from MAX_JOBS_PER_USER, and unable to appear in the owner's own
dashboard. Two deploy paths meant two sets of rules, and only one of them was
enforced.

Everything here goes through the jobs table and runner_client, so an app acted
on from Telegram behaves exactly as it does on the site — same worker routing,
same admin visibility.

CREATION AND CODE EDITING WERE ONCE REMOVED FROM HERE, AND ARE NOW BACK — READ
THIS BEFORE TOUCHING create_app() / update_code().
deploy() and update_code() used to live here while the bot accepted pasted
snippets directly in chat; both were deleted for two reasons: (1) a Telegram
TEXT message caps at ~4096 characters with no editor, so pasted code could
only ever be a toy script, and (2) pingbot.py's code-collection path ran
BEFORE the account-link check existed, so an unlinked stranger's chat could
execute code on the server (reproduced: os.system('whoami') ran unauthenticated).

/code and /update are back for a genuine, requested use case — pushing a fix
from a phone without opening the site — but neither weakness above is allowed
to return:
  · Every command that reaches create_app()/update_code() is gated on
    services.telegram_link.user_for_chat() in pingbot.py's dispatcher, same
    as /restart or /delete. There is no code path here that skips it.
  · Code can arrive as an uploaded FILE (Telegram bot API allows up to 20MB
    on download), not just a 4096-char text message, so a real app's source
    can actually make the trip. Plain-text paste still works too, for quick
    one-line fixes, and still caps out at ~4096 characters — long edits
    should be sent as a file.
  · create_app() and update_code() call the exact same jobs-table insert and
    runner_client calls as POST /api/jobs and PATCH /api/jobs/{id} below —
    same MAX_JOBS_PER_USER cap, same admin visibility. There is still only
    ONE set of rules, just triggered from two UIs now instead of one.
"""
import json
import logging
import re

from database import get_db_connection
from routes.deps import now_utc_str
from services import runner_client
from services import secrets_store
# Re-exported: pingbot reads bot_ops.MAX_JOBS_PER_USER when showing how many

# slots an account has left, so there is one value, not two.
from services.runner_client import MAX_JOBS_PER_USER  # noqa: F401

logger = logging.getLogger("codenest-app")

def slugify_name(raw: str) -> str:
    """A job name the site would also accept. Used by /rename."""
    s = re.sub(r"[^A-Za-z0-9 _-]+", "", (raw or "")).strip()
    s = re.sub(r"\s+", "-", s).strip("-")
    return s[:40]


def list_apps(user_id: int) -> list:
    """This account's apps, with live status from the worker holding each."""
    conn = get_db_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, language, runner_job_id, worker_url, desired_state, created_at "
            "FROM jobs WHERE user_id = ? ORDER BY id DESC", (user_id,)
        ).fetchall()]
    finally:
        conn.close()
    live = runner_client.fleet_jobs()
    for r in rows:
        info = live.get(r.get("runner_job_id")) or {}
        r["status"] = info.get("status") or ("stopped" if r.get("desired_state")=="stopped" else "recovering")
        r["mem_mb"] = info.get("mem_mb")
        r["uptime_s"] = info.get("uptime_s")
        r["restarts"] = info.get("restarts")
        r["last_exit_reason"] = info.get("last_exit_reason")
    return rows


def find_app(user_id: int, ref: str) -> dict:
    """Resolve a name or numeric id to one of THIS user's apps.

    Scoped to user_id on purpose: a bot command must never be able to address
    someone else's job by guessing an id.
    """
    ref = (ref or "").strip()
    if not ref:
        return None
    conn = get_db_connection()
    try:
        row = None
        if ref.isdigit():
            row = conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? AND id = ?",
                (user_id, int(ref))).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? AND LOWER(name) = LOWER(?)",
                (user_id, ref)).fetchone()
        if not row:
            # Partial match, so "/logs mybot" works when the app is
            # "mybot-2" — but only when it is unambiguous.
            hits = conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? AND LOWER(name) LIKE LOWER(?)",
                (user_id, f"%{ref}%")).fetchall()
            if len(hits) == 1:
                row = hits[0]
    finally:
        conn.close()
    return dict(row) if row else None


def _worker_of(row) -> str:
    try:
        return (dict(row).get("worker_url") or "") or None
    except Exception:
        return None


def _row_env(row) -> dict:
    """Env vars saved for a job row (empty when unset / unparsable). Same
    logic as routes/runspace.py's private copy — duplicated rather than
    imported because routes/ should not become an import target for
    services/, but kept in sync deliberately."""
    try:
        raw = dict(row).get("env")
        return secrets_store.unpack_env(raw)
    except Exception:
        return {}


def _set_assignment(row, runner_id, worker, desired="running"):
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE jobs SET runner_job_id=?,worker_url=?,desired_state=?,updated_at=? "
            "WHERE id=? AND user_id=?",
            (runner_id, worker, desired, now_utc_str(), row["id"], row["user_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    row["runner_job_id"] = runner_id
    row["worker_url"] = worker
    row["desired_state"] = desired


def _cold_start(row, code=None, language=None) -> dict:
    """Create a fresh internal job and atomically replace its assignment.

    The jobs-table id/name remains the user's stable identity. Runner ids are
    disposable implementation details and may change after any runner deploy.
    """
    env = _row_env(row)
    if row.get("telegram_bot_detected") and not env.get("BOT_TOKEN"):
        return {"ok": False, "error": "The saved bot token is unavailable. Ask the owner to restore the previous encryption key."}
    # Older Telegram-created rows did not persist worker_url. Before creating
    # anything, find the process by its stable internal name across the whole
    # fleet. This adopts the real assignment and prevents a second poller from
    # being launched with the same Telegram token.
    stable_name = f"u{row['user_id']}-{row['name']}"
    try:
        matches = [info for info in runner_client.fleet_jobs(refresh=True).values()
                   if info.get("name") == stable_name]
    except Exception:
        matches = []
    if matches:
        chosen = next((x for x in matches if x.get("status") == "running"), matches[0])
        worker = chosen.get("worker")
        _set_assignment(row, chosen["id"], worker, "running")
        # Clean up duplicates left by the old ambiguous routing code.
        for duplicate in matches:
            if duplicate.get("id") == chosen.get("id"):
                continue
            try:
                runner_client._runner_http("POST", f"/internal/jobs/{duplicate['id']}/stop",
                                           worker=duplicate.get("worker"))
            except Exception:
                pass
        try:
            restarted = runner_client._runner_http(
                "POST", f"/internal/jobs/{chosen['id']}/restart", worker=worker)
            if restarted.status_code == 200:
                chosen = restarted.json()
        except Exception:
            pass
        return {"ok": True, "job": row, "info": chosen}
    body = {
        "language": language or row.get("language") or "python",
        "code": code if code is not None else (row.get("code") or ""),
        "name": f"u{row['user_id']}-{row['name']}",
        "env": env,
    }
    try:
        response = runner_client._runner_http("POST", "/internal/jobs", body)
    except Exception as exc:
        logger.warning("cold start failed for DB job %s: %s", row.get("id"), exc)
        return {"ok": False, "error": "No runner is ready yet. Try again shortly."}
    if response.status_code != 201:
        try:
            detail = response.json().get("detail", "Runner rejected the bot.")
        except Exception:
            detail = "Runner rejected the bot."
        return {"ok": False, "error": detail}
    info = response.json()
    worker = getattr(response, "placed_on", None)
    _set_assignment(row, info["id"], worker, "running")
    try:
        from services import snapshots
        restored = snapshots.restore_snapshot(
            row["id"], info["id"], overwrite=True, worker=worker)
        if restored.get("restored"):
            restarted = runner_client._runner_http(
                "POST", f"/internal/jobs/{info['id']}/restart", worker=worker)
            if restarted.status_code == 200:
                info = restarted.json()
    except Exception as exc:
        logger.warning("cold start snapshot failed for DB job %s: %s", row.get("id"), exc)
    return {"ok": True, "job": row, "info": info}


def _ensure_present(row) -> dict:
    rid = row.get("runner_job_id")
    if rid:
        try:
            response = runner_client._runner_http(
                "GET", f"/internal/jobs/{rid}", worker=_worker_of(row))
            if response.status_code == 200:
                return {"ok": True, "job": row, "info": response.json() or {}}
            if response.status_code != 404:
                return {"ok": False, "error": f"Runner returned HTTP {response.status_code}."}
        except Exception as exc:
            logger.warning("assignment check failed for DB job %s: %s", row.get("id"), exc)
            return {"ok": False, "error": "The assigned runner did not answer. Try again shortly."}
    if row.get("desired_state") == "stopped":
        return {"ok": False, "error": f"“{row['name']}” is stopped. Use /restart {row['name']}."}
    return _cold_start(row)


def active_count(user_id: int) -> int:
    """Apps the runner reports as alive. Counting rows would lock an account
    out after MAX_JOBS_PER_USER lifetime jobs even with all of them stopped."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT runner_job_id,desired_state FROM jobs WHERE user_id = ?", (user_id,)
        ).fetchall()
    finally:
        conn.close()
    live = set(runner_client.fleet_jobs())
    if not live:
        return sum(1 for r in rows if dict(r).get("desired_state") != "stopped")
    return sum(1 for r in rows if dict(r).get("runner_job_id") in live)


def _act(user_id: int, ref: str, verb: str) -> dict:
    row = find_app(user_id, ref)
    if not row:
        return {"ok": False, "error": f"No app called “{ref}”. /apps lists yours."}
    rid = row.get("runner_job_id")
    if verb == "restart":
        if rid:
            try:
                response = runner_client._runner_http(
                    "POST", f"/internal/jobs/{rid}/restart", worker=_worker_of(row))
                if response.status_code == 200:
                    _set_assignment(row, rid, _worker_of(row), "running")
                    return {"ok": True, "job": row}
                if response.status_code != 404:
                    return {"ok": False, "error": f"Runner rejected restart (HTTP {response.status_code})."}
            except Exception as exc:
                logger.warning("bot restart failed for job %s: %s", row.get("id"), exc)
                return {"ok": False, "error": "The assigned runner did not answer. Try again shortly."}
        # Internal id vanished after a deploy: create on the least-loaded
        # runner and replace the DB assignment instead of claiming success.
        return _cold_start(row)

    # Stop is idempotent: a missing internal id is already stopped.
    if rid:
        try:
            response = runner_client._runner_http(
                "POST", f"/internal/jobs/{rid}/stop", worker=_worker_of(row))
            if response.status_code not in (200, 404):
                return {"ok": False, "error": f"Runner rejected stop (HTTP {response.status_code})."}
        except Exception as exc:
            logger.warning("bot stop failed for job %s: %s", row.get("id"), exc)
            return {"ok": False, "error": "The assigned runner did not answer. Try again shortly."}
    _set_assignment(row, rid, _worker_of(row), "stopped")
    return {"ok": True, "job": row}


def restart(user_id: int, ref: str) -> dict:
    return _act(user_id, ref, "restart")


def stop(user_id: int, ref: str) -> dict:
    return _act(user_id, ref, "stop")


def delete(user_id: int, ref: str) -> dict:
    """Remove the app entirely — runner first, then the row."""
    row = find_app(user_id, ref)
    if not row:
        return {"ok": False, "error": f"No app called “{ref}”. /apps lists yours."}
    rid = row.get("runner_job_id")
    if rid:
        try:
            runner_client._runner_http("DELETE", f"/internal/jobs/{rid}",
                                       worker=_worker_of(row))
        except Exception as exc:
            # Best effort: a worker that is asleep must not strand the row
            # forever, or the user can never get back under their cap.
            logger.warning("bot delete: runner call failed for %s: %s", rid, exc)
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM jobs WHERE id = ? AND user_id = ?",
                     (row["id"], user_id))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "job": row}


def rename(user_id: int, ref: str, new_name: str) -> dict:
    row = find_app(user_id, ref)
    if not row:
        return {"ok": False, "error": f"No app called “{ref}”. /apps lists yours."}
    clean = slugify_name(new_name)
    if not clean:
        return {"ok": False, "error": "That name has no usable characters."}
    conn = get_db_connection()
    try:
        dup = conn.execute(
            "SELECT id FROM jobs WHERE user_id = ? AND LOWER(name) = LOWER(?) AND id != ?",
            (user_id, clean, row["id"])).fetchone()
        if dup:
            return {"ok": False, "error": f"You already have an app called “{clean}”."}
        conn.execute("UPDATE jobs SET name = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                     (clean, now_utc_str(), row["id"], user_id))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "old": row["name"], "name": clean}


def logs(user_id: int, ref: str, lines: int = 40) -> dict:
    row = find_app(user_id, ref)
    if not row:
        return {"ok": False, "error": f"No app called “{ref}”. /apps lists yours."}
    present = _ensure_present(row)
    if not present.get("ok"):
        return present
    info = present.get("info") or {}
    text = (info.get("logs") or "").splitlines()
    return {"ok": True, "job": row, "info": info,
            "logs": "\n".join(text[-lines:]),
            "truncated": len(text) > lines}


# ── /code and /update — see the module docstring before changing these ────

def create_app(user_id: int, name: str, language: str, code: str) -> dict:
    """Make a brand-new app from chat-supplied name + code. Identical rules
    to POST /api/jobs: per-user name uniqueness, the MAX_JOBS_PER_USER cap,
    and a real jobs-table row so the app shows up in the dashboard and
    /admin/jobs exactly like one made on the site."""
    clean = slugify_name(name)
    if not clean:
        return {"ok": False, "error": "That name has no usable characters."}

    conn = get_db_connection()
    try:
        dup = conn.execute(
            "SELECT id FROM jobs WHERE user_id = ? AND LOWER(name) = LOWER(?)",
            (user_id, clean)).fetchone()
        if dup:
            return {"ok": False,
                    "error": f"You already have an app called “{clean}”. Use /update {clean} instead."}
        rows = conn.execute(
            "SELECT runner_job_id,desired_state FROM jobs WHERE user_id = ?", (user_id,)
        ).fetchall()
    finally:
        conn.close()

    live = set(runner_client.fleet_jobs())
    active = (sum(1 for r in rows if dict(r).get("runner_job_id") in live)
              if live else sum(1 for r in rows if dict(r).get("desired_state") != "stopped"))
    if active >= MAX_JOBS_PER_USER:
        return {"ok": False,
                "error": (f"You already have {active} of {MAX_JOBS_PER_USER} bots "
                          f"running — stop one before making another.")}

    body = {"language": language, "code": code, "name": f"u{user_id}-{clean}", "env": {}}
    resp = runner_client._runner_http("POST", "/internal/jobs", body)
    if resp.status_code != 201:
        try:
            detail = resp.json().get("detail", "Runner rejected the app.")
        except Exception:
            detail = "Runner rejected the app."
        return {"ok": False, "error": detail}

    info = resp.json()
    now = now_utc_str()
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO jobs (user_id,name,language,code,runner_job_id,worker_url,desired_state,env,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,'running',?,?,?)",
            (user_id,clean,language,code,info["id"],getattr(resp,"placed_on",None),None,now,now))
        conn.commit()
        job_db_id = cursor.lastrowid
    finally:
        conn.close()

    web = runner_client._job_web_fields(info, getattr(resp, "placed_on", None))
    return {"ok": True, "name": clean, "job_db_id": job_db_id,
            "web": web.get("web") or web.get("web_url")}


def update_code(user_id: int, ref: str, code: str, language: str = None) -> dict:
    """Redeploy an EXISTING app in place with new code — the chat equivalent
    of PATCH /api/jobs/{id}. Same worker, same slug/URL, same persistent
    workspace (SQLite files, session data): only the source changes. Falls
    back to a cold create if the runner no longer holds the job, same as the
    website's edit path does."""
    row = find_app(user_id, ref)
    if not row:
        return {"ok": False, "error": f"No app called “{ref}”. /apps lists yours."}

    rid = row.get("runner_job_id")
    lang = language or row["language"]
    now = now_utc_str()
    conn = get_db_connection()
    try:
        conn.execute("UPDATE jobs SET code = ?, language = ?, updated_at = ? WHERE id = ?",
                     (code, lang, now, row["id"]))
        conn.commit()
    finally:
        conn.close()

    env = _row_env(row)

    if not rid:
        # Never actually deployed (e.g. imported but never started) — bring
        # it up fresh instead of PATCHing a job the runner has never heard of.
        body = {"language": lang, "code": code, "name": f"u{user_id}-{row['name']}", "env": env}
        resp = runner_client._runner_http("POST", "/internal/jobs", body)
        if resp.status_code != 201:
            try:
                detail = resp.json().get("detail", "Runner rejected the app.")
            except Exception:
                detail = "Runner rejected the app."
            return {"ok": False, "error": detail}
        info = resp.json()
        conn = get_db_connection()
        try:
            conn.execute("UPDATE jobs SET runner_job_id=?,worker_url=?,desired_state='running',updated_at=? WHERE id=?",
                         (info["id"],getattr(resp,"placed_on",None),now_utc_str(),row["id"]))
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "job": row}

    # Best-effort backup before touching the running job — mirrors the
    # website's update_job(): an edit is the moment most likely to lose data
    # if the runner has to cold-start.
    try:
        from services import snapshots
        snapshots.save_snapshot(row["id"], rid, worker=_worker_of(row))
    except Exception as exc:
        logger.warning("bot update_code: pre-update snapshot failed for job %s: %s", row["id"], exc)

    patch_body = {"name": row["name"], "language": lang, "code": code, "env": env}
    resp = runner_client._runner_http("PATCH", f"/internal/jobs/{rid}", patch_body,
                                       worker=_worker_of(row))
    if resp.status_code == 200:
        _set_assignment(row, rid, _worker_of(row), "running")
        return {"ok": True, "job": row}

    if resp.status_code == 404:
        # Runner restarted since — fall back to a cold create, same as
        # routes/runspace.py's update_job().
        create_body = {"language": lang, "code": code, "name": f"u{user_id}-{row['name']}", "env": env}
        resp2 = runner_client._runner_http("POST", "/internal/jobs", create_body)
        if resp2.status_code != 201:
            try:
                detail = resp2.json().get("detail", "Runner rejected the update.")
            except Exception:
                detail = "Runner rejected the update."
            return {"ok": False, "error": detail}
        info = resp2.json()
        conn = get_db_connection()
        try:
            conn.execute("UPDATE jobs SET runner_job_id=?,worker_url=?,desired_state='running',updated_at=? WHERE id=?",
                         (info["id"],getattr(resp2,"placed_on",None),now_utc_str(),row["id"]))
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "job": row}

    try:
        detail = resp.json().get("detail", "Runner rejected the update.")
    except Exception:
        detail = "Runner rejected the update."
    return {"ok": False, "error": detail}
