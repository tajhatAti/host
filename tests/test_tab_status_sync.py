# TAB-SWITCH STALE STATUS (§1)
#
# Symptom: switching Job A -> Job B -> Job A showed A as "not running" even
# though it WAS running, until the user interacted again.
#
# Root cause: both /api/jobs and /api/jobs/{id} treated "could not reach the
# runner" as "the job is offline". On the free tier the runner sleeps/cold-
# starts and returns 503, so a perfectly healthy running job was reported as
# stopped, and that wrong value was cached into the UI's job list.
#
# Fix: distinguish "runner answered and does not know this job" (offline) from
# "runner did not answer" (unknown + status_stale), so the client can keep the
# last known state and re-check instead of painting a lie.
import os
import sqlite3
import sys
import tempfile
import time

DB = tempfile.mktemp(suffix=".db")
os.environ["DB_PATH"] = DB
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ["SIGNUP_DAILY_MAX"] = "50"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.email as _email  # noqa: E402
_email.send_email = lambda *a, **k: None
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402
import services.runner_client as rc  # noqa: E402

client = TestClient(app)
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("\u2713 " if cond else "\u2717 FAIL ") + f"{name:58s}" + (f" \u2014 {extra}" if not cond else ""))


client.post("/signup", json={"username": "tabsync", "email": "tabsync@gmail.com",
                             "password": "Str0ng!Pass9", "agreed_terms": True, "captcha": "12"})
otp = db.execute("SELECT otp FROM users WHERE username='tabsync'").fetchone()["otp"]
TOK = client.post("/verify", json={"username": "tabsync", "otp": otp}).json()["token"]
H = {"Authorization": "Bearer " + TOK}

LONG = "import time\ntime.sleep(120)\n"
a = client.post("/api/jobs", json={"name": "jobA", "language": "python", "code": LONG}, headers=H)
b = client.post("/api/jobs", json={"name": "jobB", "language": "python", "code": LONG}, headers=H)
check("two jobs created", a.status_code == 200 and b.status_code == 200)
ida, idb = a.json()["job_db_id"], b.json()["job_db_id"]
time.sleep(6)

# --- the reported flow: A -> B -> A, each "switch" is a detail fetch --------
sa1 = client.get(f"/api/jobs/{ida}", headers=H).json()
check("job A starts running", sa1["status"] == "running", sa1.get("status"))
client.get(f"/api/jobs/{idb}", headers=H)                      # switch to B
sa2 = client.get(f"/api/jobs/{ida}", headers=H).json()         # switch back to A
check("A still running after switching away and back",
      sa2["status"] == "running", sa2.get("status"))
check("switch back reports fresh uptime", sa2.get("uptime_s", 0) >= sa1.get("uptime_s", 0))

# --- the actual root cause: runner momentarily unreachable ------------------
_real = rc._runner_http


def _unreachable(*a, **k):
    raise HTTPException(status_code=503, detail="Waking up your RunSpace…")


rc._runner_http = _unreachable
try:
    d = client.get(f"/api/jobs/{ida}", headers=H).json()
    check("unreachable runner does NOT report 'offline'", d["status"] != "offline", d["status"])
    check("unreachable runner reports 'unknown'", d["status"] == "unknown", d["status"])
    check("response is flagged stale", d.get("status_stale") is True)

    lst = client.get("/api/jobs", headers=H).json()["jobs"]
    check("list does NOT report running jobs offline",
          all(j["status"] != "offline" for j in lst), str([j["status"] for j in lst]))
    check("list flags staleness", all(j.get("status_stale") for j in lst))
finally:
    rc._runner_http = _real

# --- recovery must be automatic, with no user action -----------------------
rec = client.get(f"/api/jobs/{ida}", headers=H).json()
check("status recovers to running once the runner answers",
      rec["status"] == "running", rec.get("status"))
check("recovered response is not stale", not rec.get("status_stale"))

# --- a genuinely stopped job must still read as offline --------------------
client.post(f"/api/jobs/{idb}/stop", headers=H)
time.sleep(3)
sb = client.get(f"/api/jobs/{idb}", headers=H).json()
check("a truly stopped job still reports stopped/offline",
      sb["status"] in ("stopped", "offline"), sb.get("status"))

for j in (ida, idb):
    client.post(f"/api/jobs/{j}/stop", headers=H)
    client.delete(f"/api/jobs/{j}", headers=H)

passed = sum(1 for _, ok in results if ok)
failed = len(results) - passed
print(f"\n================ {passed} pass, {failed} fail ================")
sys.exit(1 if failed else 0)
