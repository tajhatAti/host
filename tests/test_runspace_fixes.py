# RUNSPACE: stuck-state fixes + simple per-account limit + Details route.
#
# Regression coverage for the bugs that made RunSpace unusable:
#   1. runner job_restart()/job_update() self-deadlocked on _jobs_lock
#      (_alloc_port acquires the SAME non-reentrant lock) -> restart-after-stop
#      hung forever holding the lock, freezing every later job operation.
#   2. The SSE log stream was `while True` with no disconnect check and no
#      lifetime bound, pinning a request (and a worker thread per poll) forever.
#   3. runner/terminal.py called database.connect(), which does not exist.
#   4. Per-account job cap counted ROWS EVER CREATED instead of RUNNING jobs,
#      so a user was locked out permanently after 3 lifetime jobs.
#   5. /runspace/{user}/{tab}/page must serve the SPA shell (Details page).
import os
import sqlite3
import sys
import tempfile
import threading
import time

DB = tempfile.mktemp(suffix=".db")
os.environ["DB_PATH"] = DB
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ["SIGNUP_DAILY_MAX"] = "50"
os.environ["SSE_MAX_LIFETIME_S"] = "5"        # keep the stream test quick
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.email as _email_svc  # noqa: E402
_email_svc.send_email = lambda *a, **k: None

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402

client = TestClient(app)
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("✓ " if cond else "✗ FAIL ") + f"{name:58s}" + (f" — {extra}" if not cond else ""))


def signup(username):
    client.post("/signup", json={
        "username": username, "email": f"{username}@gmail.com",
        "password": "Str0ng!Pass9", "agreed_terms": True, "captcha": "12"})
    otp = db.execute("SELECT otp FROM users WHERE username=?", (username,)).fetchone()["otp"]
    return client.post("/verify", json={"username": username, "otp": otp}).json()["token"]


LONG = "import time\nfor i in range(120):\n    print('tick', i, flush=True)\n    time.sleep(1)\n"

tok = signup("rsuser")
H = {"Authorization": "Bearer " + tok}

# ------------------------------------------------- 1/2: lifecycle must not hang
print("\n--- RunSpace lifecycle (previously hung forever) ---")
t0 = time.time()
r = client.post("/api/jobs", json={"name": "lifecycle", "language": "python", "code": LONG}, headers=H)
check("create job", r.status_code == 200, r.text[:110])
jid = r.json().get("job_db_id")
time.sleep(4)

check("job detail", client.get(f"/api/jobs/{jid}", headers=H).status_code == 200)
lg = client.get(f"/api/jobs/{jid}/logs", headers=H)
check("logs readable", lg.status_code == 200 and "[system]" in (lg.json().get("logs") or ""), lg.text[:110])
check("file list", client.get(f"/api/jobs/{jid}/files", headers=H).status_code == 200)
check("stop", client.post(f"/api/jobs/{jid}/stop", headers=H).status_code == 200)

# THE DEADLOCK: restart immediately after stop.
done = []
threading.Thread(
    target=lambda: done.append(client.post(f"/api/jobs/{jid}/restart", headers=H).status_code),
    daemon=True).start()
for _ in range(300):                      # up to 30s
    if done:
        break
    time.sleep(0.1)
check("restart-after-stop does NOT deadlock", bool(done), "still blocked after 30s")
check("restart succeeded", done and done[0] == 200, str(done))
check("whole lifecycle stays responsive", time.time() - t0 < 90, f"{time.time()-t0:.0f}s")

client.post(f"/api/jobs/{jid}/stop", headers=H)
check("delete", client.delete(f"/api/jobs/{jid}", headers=H).status_code == 200)

# ------------------------------------------------------- 2: SSE must terminate
print("\n--- SSE log stream must be bounded ---")
r = client.post("/api/jobs", json={"name": "ssejob", "language": "python", "code": LONG}, headers=H)
sse_jid = r.json()["job_db_id"]
time.sleep(2)
out = []
threading.Thread(
    target=lambda: out.append(client.get(f"/api/jobs/{sse_jid}/logs/stream?token={tok}")),
    daemon=True).start()
for _ in range(400):                      # up to 40s (lifetime cap is 5s)
    if out:
        break
    time.sleep(0.1)
check("log stream terminates (no endless request)", bool(out), "stream never returned")
if out:
    body = out[0].text
    check("stream returned 200", out[0].status_code == 200)
    check("stream sent job data", "data:" in body)
    check("stream asks client to reconnect", "reconnect" in body)
check("stream rejects a missing token",
      client.get(f"/api/jobs/{sse_jid}/logs/stream").status_code == 401)
client.post(f"/api/jobs/{sse_jid}/stop", headers=H)
client.delete(f"/api/jobs/{sse_jid}", headers=H)

# --------------------------------------------- 4: per-account CONCURRENT limit
print("\n--- Per-account concurrent job limit (3) ---")
made = []
for i in range(4):
    rr = client.post("/api/jobs", json={"name": f"cap{i}", "language": "python", "code": LONG}, headers=H)
    if rr.status_code == 200:
        made.append(rr.json()["job_db_id"])
    last = rr
check("first three jobs allowed", len(made) == 3, str(len(made)))
check("fourth job blocked with 429", last.status_code == 429, last.text[:110])
check("limit message explains what to do",
      "stop one" in last.json().get("detail", "").lower(), last.text[:110])

# Stopping one must FREE a slot (the old row-count logic never did).
client.post(f"/api/jobs/{made[0]}/stop", headers=H)
time.sleep(2)
again = client.post("/api/jobs", json={"name": "afterstop", "language": "python", "code": LONG}, headers=H)
check("stopping a job frees a slot", again.status_code == 200, again.text[:110])
if again.status_code == 200:
    made.append(again.json()["job_db_id"])
for j in made:
    client.post(f"/api/jobs/{j}/stop", headers=H)
    client.delete(f"/api/jobs/{j}", headers=H)

# ------------------------------------------------ 5: Details page route serves
print("\n--- Details page route (§5) ---")
for path in ("/bots", "/bots/ahad/mybot", "/bots/ahad/mybot/page",
             "/bots/ahad/my-cool-bot/page"):
    rr = client.get(path, headers={"Accept": "text/html"})
    check(f"SPA shell served for {path}",
          rr.status_code == 200 and "html" in rr.headers.get("content-type", ""),
          f"{rr.status_code}")

# ------------------------------------------ 3: terminal DB helper name is real
print("\n--- Supporting fixes ---")
import database as _dbmod  # noqa: E402
check("database exposes get_db_connection()", hasattr(_dbmod, "get_db_connection"))
check("runner/terminal.py no longer calls db.connect()",
      "db.connect()" not in open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              "..", "runner", "terminal.py")).read())
_runner_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "runner", "app.py")).read()
check("no nested _jobs_lock around _alloc_port()",
      "with _jobs_lock:\n            j[\"port\"] = _alloc_port()" not in _runner_src)
_js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "pro.js")).read()
check("_downloadBlob is defined before use", "function _downloadBlob(" in _js)
check("job-switch animation helper exists", "function _playSwap(" in _js)
check("details route builds /page URLs", '"/page"' in _js)

passed = sum(1 for _, ok in results if ok)
failed = len(results) - passed
print(f"\n================ {passed} pass, {failed} fail ================")
sys.exit(1 if failed else 0)
