"""RunSpace workspace snapshots — keeping bot data across a redeploy.

THE PROBLEM
-----------
Each job runs in its own directory on the runner (JOBS_DATA_DIR/<runner_id>).
That directory already survives Stop, Restart and code edits: job_update()
overwrites only main.*, never the data files. So a referral bot's database.db
was safe day to day.

It was NOT safe across a *deploy*. On Render's free tier the container
filesystem is rebuilt from the image, the directory is gone, and the runner
falls back to creating a brand-new job with a brand-new empty workspace. Points,
referral history, session files — all gone. The documented fix was "mount a
Persistent Disk", which requires a paid plan.

THE FIX
-------
Back the workspace up into the one store that IS durable and already paid for:
Postgres. The runner packs its data files into a tar.gz (it is the only process
that can read that filesystem); this module base64s the result into
job_data_snapshots and pushes it back when the workspace comes up empty.

DESIGN NOTES
------------
* Keyed by the SITE job id, not the runner id. The runner id changes every time
  a job is recreated — which is precisely what happens after a deploy — so
  keying by it would lose the very snapshot we need.

* Restore never overwrites an existing file. A live workspace file is always
  fresher than the last snapshot, so overwriting would roll a running bot
  BACKWARDS. After a deploy the directory is empty and everything is written,
  which is the case this exists for.

* Only data is stored. Code lives in the jobs table already, and pylibs/
  node_modules are re-installable and enormous.

* Every entry point is best-effort. A snapshot failure must never stop a job
  from starting — losing a backup is bad, refusing to run the bot is worse.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# How old a snapshot may get before a periodic sweep refreshes it.
SNAPSHOT_INTERVAL_S = int(os.getenv("SNAPSHOT_INTERVAL_S", str(30 * 60)))
# Postgres TEXT is fine with this; the runner enforces its own byte cap too.
SNAPSHOT_MAX_B64 = int(os.getenv("SNAPSHOT_MAX_B64", str(40 * 1024 * 1024)))
SNAPSHOTS_ENABLED = os.getenv("SNAPSHOTS_ENABLED", "1").strip() not in ("0", "false", "no")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------
def save_snapshot(job_id: int, runner_job_id: str, worker: str = None) -> dict:
    """Ask the runner to pack the workspace, store the result in Postgres."""
    if not SNAPSHOTS_ENABLED or not runner_job_id:
        return {"saved": False, "reason": "disabled"}
    from services import runner_client
    from database import get_db_connection

    try:
        resp = runner_client._runner_http(
            "GET", f"/internal/jobs/{runner_job_id}/snapshot", worker=worker)
    except Exception as exc:  # runner down / restarting — try again later
        logger.info("snapshot: runner unreachable for job %s: %s", job_id, exc)
        return {"saved": False, "reason": "runner unreachable"}
    if resp.status_code != 200:
        return {"saved": False, "reason": f"runner {resp.status_code}"}
    try:
        data = resp.json()
    except Exception:
        return {"saved": False, "reason": "bad runner response"}
    if data.get("empty"):
        # Nothing to back up yet (bot hasn't written a database). Leave any
        # EXISTING snapshot alone — a bot that is mid-restart momentarily has
        # an empty dir, and clobbering the backup there would be the exact
        # data loss this module exists to prevent.
        return {"saved": False, "reason": data.get("reason") or "no data"}

    b64 = data.get("tarball_b64") or ""
    if not b64 or len(b64) > SNAPSHOT_MAX_B64:
        return {"saved": False, "reason": "too large"}

    conn = get_db_connection()
    try:
        now = _now()
        updated = conn.execute(
            "UPDATE job_data_snapshots SET tarball_b64=?, file_count=?, "
            "byte_size=?, updated_at=? WHERE job_id=?",
            (b64, int(data.get("file_count") or 0),
             int(data.get("byte_size") or 0), now, job_id),
        )
        if not getattr(updated, "rowcount", 0):
            conn.execute(
                "INSERT INTO job_data_snapshots "
                "(job_id, tarball_b64, file_count, byte_size, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (job_id, b64, int(data.get("file_count") or 0),
                 int(data.get("byte_size") or 0), now),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("snapshot: DB write failed for job %s: %s", job_id, exc)
        return {"saved": False, "reason": "db error"}
    finally:
        conn.close()

    logger.info("snapshot: job %s saved (%s files, %s bytes)",
                job_id, data.get("file_count"), data.get("byte_size"))
    return {
        "saved": True,
        "files": data.get("file_count"),
        "bytes": data.get("byte_size"),
    }


def load_snapshot(job_id: int) -> Optional[dict]:
    from database import get_db_connection
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT tarball_b64, file_count, byte_size, updated_at "
            "FROM job_data_snapshots WHERE job_id=?", (job_id,)
        ).fetchone()
    except Exception as exc:
        logger.warning("snapshot: DB read failed for job %s: %s", job_id, exc)
        return None
    finally:
        conn.close()
    if not row:
        return None
    d = dict(row)
    return d if d.get("tarball_b64") else None


def snapshot_meta(job_id: int) -> Optional[dict]:
    """Size/age only — used by the UI, never ships the payload to the browser."""
    snap = load_snapshot(job_id)
    if not snap:
        return None
    return {
        "files": snap.get("file_count"),
        "bytes": snap.get("byte_size"),
        "updated_at": snap.get("updated_at"),
    }


def restore_snapshot(job_id: int, runner_job_id: str,
                     overwrite: bool = False, worker: str = None) -> dict:
    """Push the stored workspace back to the runner. Best-effort by design."""
    if not SNAPSHOTS_ENABLED or not runner_job_id:
        return {"restored": 0, "reason": "disabled"}
    snap = load_snapshot(job_id)
    if not snap:
        return {"restored": 0, "reason": "no snapshot"}
    from services import runner_client
    try:
        resp = runner_client._runner_http(
            "POST", f"/internal/jobs/{runner_job_id}/snapshot/restore",
            {"tarball_b64": snap["tarball_b64"], "overwrite": bool(overwrite)},
            worker=worker,
        )
    except Exception as exc:
        logger.warning("snapshot: restore call failed for job %s: %s", job_id, exc)
        return {"restored": 0, "reason": "runner unreachable"}
    if resp.status_code != 200:
        return {"restored": 0, "reason": f"runner {resp.status_code}"}
    try:
        out = resp.json()
    except Exception:
        return {"restored": 0, "reason": "bad runner response"}
    logger.info("snapshot: job %s restored %s file(s)", job_id, out.get("restored"))
    return out


# --------------------------------------------------------------------------
# background sweep
# --------------------------------------------------------------------------
_sweep_started = False
_sweep_lock = threading.Lock()


def _all_live_jobs() -> list:
    from database import get_db_connection
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id,runner_job_id,worker_url FROM jobs WHERE runner_job_id IS NOT NULL "
            "AND runner_job_id != ''"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("snapshot sweep: job query failed: %s", exc)
        return []
    finally:
        conn.close()


def sweep_once() -> dict:
    """Snapshot every job that has a runner id. Returns a small summary."""
    saved = failed = 0
    for row in _all_live_jobs():
        try:
            res = save_snapshot(int(row["id"]),row["runner_job_id"],worker=row.get("worker_url"))
            if res.get("saved"):
                saved += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            logger.warning("snapshot sweep: job %s failed: %s", row.get("id"), exc)
    if saved:
        logger.info("snapshot sweep: %d saved, %d skipped", saved, failed)
    return {"saved": saved, "skipped": failed}


def _sweep_loop():
    # Let the app finish booting (and the runner adopt its jobs) before the
    # first pass, otherwise we snapshot half-initialised workspaces.
    time.sleep(120)
    while True:
        try:
            sweep_once()
        except Exception as exc:  # a sweep must never kill its own thread
            logger.warning("snapshot sweep crashed: %s", exc)
        time.sleep(SNAPSHOT_INTERVAL_S)


def start_sweeper():
    """Start the periodic snapshot thread (idempotent)."""
    global _sweep_started
    if not SNAPSHOTS_ENABLED:
        logger.info("Workspace snapshots disabled (SNAPSHOTS_ENABLED=0)")
        return
    with _sweep_lock:
        if _sweep_started:
            return
        _sweep_started = True
    threading.Thread(target=_sweep_loop, name="snapshot-sweeper",
                     daemon=True).start()
    logger.info("Workspace snapshot sweeper started (every %ds)", SNAPSHOT_INTERVAL_S)
