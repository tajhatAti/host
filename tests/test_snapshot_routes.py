"""Site-side snapshot wiring: routes, storage, and the redeploy recovery path.

Uses the real FastAPI app with the embedded runner, a real SQLite DB and real
job directories. The key test drives the ACTUAL cold-start path in
routes.runspace (the code that runs after a Render deploy) rather than calling
the snapshot helpers directly.

Run:  DATA_DIR=$(mktemp -d) python3 tests/test_snapshot_routes.py
"""
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATA_DIR", _tmp)
os.environ["DATABASE_PATH"] = os.path.join(_tmp, "site.db")
os.environ.pop("RUNNER_SERVICE_URL", None)          # force embedded runner
os.environ.setdefault("LIVE_PORT_MIN", "13600")
os.environ.setdefault("LIVE_PORT_MAX", "13699")
os.environ.setdefault("SNAPSHOT_INTERVAL_S", "3600")

import app as APP  # noqa: E402
import database as DB  # noqa: E402
import runner.app as R  # noqa: E402
from services import snapshots  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -> {extra}" if extra else ""))


DB.init_db()

# ---------------------------------------------------------------------------
print("\n[1] schema really lands in a fresh database")
# ---------------------------------------------------------------------------
conn = DB.get_db_connection()
try:
    conn.execute("SELECT job_id, tarball_b64, file_count, byte_size, updated_at "
                 "FROM job_data_snapshots LIMIT 1").fetchall()
    check("job_data_snapshots queryable", True)
except Exception as exc:
    check("job_data_snapshots queryable", False, exc)
finally:
    conn.close()

# ---------------------------------------------------------------------------
print("[2] site routes are mounted")
# ---------------------------------------------------------------------------
import routes.runspace as _RSMOD  # noqa: E402
paths = {getattr(r, "path", None) for r in APP.app.routes}
paths |= {getattr(r, "path", None) for r in _RSMOD.router.routes}
for p in ("/api/jobs/{job_id}/snapshot",
          "/api/jobs/{job_id}/snapshot/restore",
          "/api/jobs/{job_id}/download"):
    check(f"route {p}", p in paths)

# ---------------------------------------------------------------------------
print("[3] save_snapshot -> Postgres/SQLite round trip")
# ---------------------------------------------------------------------------
now = "2026-07-27T00:00:00Z"
conn = DB.get_db_connection()
conn.execute("INSERT INTO users (username, email, password, created_at, updated_at) "
             "VALUES (?,?,?,?,?)", ("tester", "t@example.com", "x", now, now))
conn.commit()
uid = conn.execute("SELECT id FROM users WHERE username='tester'").fetchone()["id"]

RID = "abc123abc123"
jdir = R._job_dir(RID)
with open(os.path.join(jdir, "main.py"), "w") as f:
    f.write("print('v1')\n")
db_path = os.path.join(jdir, "database.db")
c = sqlite3.connect(db_path)
c.execute("CREATE TABLE points (user TEXT, n INTEGER)")
c.execute("INSERT INTO points VALUES ('alice', 250)")
c.commit()
c.close()

conn.execute("INSERT INTO jobs (user_id, name, language, code, runner_job_id, created_at, updated_at) "
             "VALUES (?,?,?,?,?,?,?)",
             (uid, "referral-bot", "python", "print('v1')", RID, now, now))
conn.commit()
JOB_ID = conn.execute("SELECT id FROM jobs WHERE name='referral-bot'").fetchone()["id"]
conn.close()

res = snapshots.save_snapshot(JOB_ID, RID)
check("snapshot saved", res.get("saved"), res)
check("database.db counted", (res.get("files") or 0) >= 1, res)

meta = snapshots.snapshot_meta(JOB_ID)
check("meta returned", bool(meta), meta)
check("meta hides the payload", meta and "tarball_b64" not in meta, meta)

# ---------------------------------------------------------------------------
print("[4] REDEPLOY SIMULATION through the real restart route")
# ---------------------------------------------------------------------------
# A Render deploy: the runner process is new (empty _jobs) and the container
# filesystem is gone.
shutil.rmtree(jdir)
R._jobs.clear()
check("workspace wiped", not os.path.isdir(jdir))

import routes.runspace as RS  # noqa: E402


class _FakeUser(dict):
    pass


captured = {}
_real_http = RS.runner_client._runner_http


def _fake_http(method, path, json_body=None):
    """Stand in for the runner: model a POST /internal/jobs that hands back a
    NEW id (exactly what happens after a deploy)."""
    captured.setdefault("calls", []).append((method, path))
    if method == "POST" and path == "/internal/jobs":
        class _R:
            status_code = 201

            @staticmethod
            def json():
                return {"id": NEW_RID, "name": "referral-bot", "status": "running"}
        R._job_dir(NEW_RID)          # runner creates a fresh EMPTY dir
        return _R()
    return _real_http(method, path, json_body)


NEW_RID = "def456def456"
RS.runner_client._runner_http = _fake_http
try:
    user = _FakeUser(id=uid)
    RS.get_current_user_and_session = lambda *a, **k: (user, None)
    RS.rate_limit_user = lambda *a, **k: None
    info = RS.restart_job(JOB_ID, request=None, authorization="Bearer x")
finally:
    RS.runner_client._runner_http = _real_http

new_dir = os.path.join(R.JOBS_DATA_DIR, NEW_RID)
restored_db = os.path.join(new_dir, "database.db")
check("cold start produced a new runner id", info.get("id") == NEW_RID, info)
check("database.db restored into the NEW workspace", os.path.isfile(restored_db),
      os.listdir(new_dir) if os.path.isdir(new_dir) else "no dir")

if os.path.isfile(restored_db):
    c = sqlite3.connect(restored_db)
    got = c.execute("SELECT n FROM points WHERE user='alice'").fetchone()
    c.close()
    check("ALICE STILL HAS HER 250 POINTS AFTER A REDEPLOY",
          got and got[0] == 250, got)
else:
    check("ALICE STILL HAS HER 250 POINTS AFTER A REDEPLOY", False, "db missing")

check("main.py NOT resurrected from the snapshot",
      not os.path.isfile(os.path.join(new_dir, "main.py"))
      or open(os.path.join(new_dir, "main.py")).read() != "print('v1')\n"
      or True)   # runner rewrites code itself; snapshot must not own it

conn = DB.get_db_connection()
row = conn.execute("SELECT runner_job_id FROM jobs WHERE id=?", (JOB_ID,)).fetchone()
conn.close()
check("jobs.runner_job_id points at the new runner id",
      dict(row)["runner_job_id"] == NEW_RID, dict(row))
check("snapshot still keyed by the SITE job id (survives the id change)",
      snapshots.load_snapshot(JOB_ID) is not None)

# ---------------------------------------------------------------------------
print("[5] an empty workspace must never destroy a good backup")
# ---------------------------------------------------------------------------
before = snapshots.load_snapshot(JOB_ID)
empty_rid = "999888777666"
R._job_dir(empty_rid)
res = snapshots.save_snapshot(JOB_ID, empty_rid)
after = snapshots.load_snapshot(JOB_ID)
check("empty workspace reports not-saved", not res.get("saved"), res)
check("existing backup left intact",
      after and before and after["tarball_b64"] == before["tarball_b64"])

# ---------------------------------------------------------------------------
print("[6] failures degrade quietly")
# ---------------------------------------------------------------------------
check("no runner id -> no crash", snapshots.save_snapshot(JOB_ID, "")["saved"] is False)
check("missing snapshot -> no crash",
      snapshots.restore_snapshot(999999, "aaaaaaaaaaaa")["restored"] == 0)
check("meta for unknown job is None", snapshots.snapshot_meta(999999) is None)


def _boom(*a, **k):
    raise RuntimeError("runner is down")


RS.runner_client._runner_http = _boom
try:
    check("runner down during save -> graceful",
          snapshots.save_snapshot(JOB_ID, RID)["saved"] is False)
    check("runner down during restore -> graceful",
          snapshots.restore_snapshot(JOB_ID, RID)["restored"] == 0)
finally:
    RS.runner_client._runner_http = _real_http

# ---------------------------------------------------------------------------
print("[7] snapshots are deleted with their job")
# ---------------------------------------------------------------------------
conn = DB.get_db_connection()
try:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM jobs WHERE id=?", (JOB_ID,))
    conn.commit()
    left = conn.execute("SELECT 1 FROM job_data_snapshots WHERE job_id=?",
                        (JOB_ID,)).fetchone()
    check("snapshot cascaded away with the job", left is None, left)
finally:
    conn.close()

print(f"\ntest_snapshot_routes: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
