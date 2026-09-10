# JOB LIVENESS — "running Telegram bot shows offline" + restart hang.
#
# INVESTIGATION RESULT (the hypothesis in the report was WRONG):
# status is NOT derived from an HTTP ping. runner/_job_public() computes it
# from proc.poll() — real process liveness — and the Details page badge reads
# job.status. The HTTP probe only feeds a SEPARATE "Public URL health" row.
#
# The real cause: runner/_jobs is an in-memory dict that is never rebuilt.
# Children are spawned with start_new_session=True, so they SURVIVE a runner
# restart/redeploy while the registry describing them is lost. The API then
# answered 404 -> "offline" for a process that was still happily running, and
# Restart cold-started a SECOND copy that fought the first for the port.
#
# Fix: persist a per-job manifest and re-adopt live processes on boot; make
# the kill path verify the process actually exited.
import os
import sqlite3
import sys
import tempfile
import time

DB = tempfile.mktemp(suffix=".db")
os.environ["DB_PATH"] = DB
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ["JOBS_DATA_DIR"] = tempfile.mkdtemp()
os.environ["SIGNUP_DAILY_MAX"] = "50"
# Isolated port window so a stray process from another test cannot collide.
os.environ.setdefault("LIVE_PORT_MIN", "12700")
os.environ.setdefault("LIVE_PORT_MAX", "12800")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.email as _email  # noqa: E402
_email.send_email = lambda *a, **k: None
from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402
import runner.app as ra  # noqa: E402

client = TestClient(app)
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("\u2713 " if cond else "\u2717 FAIL ") + f"{name:56s}" + (f" \u2014 {extra}" if not cond else ""))


client.post("/signup", json={"username": "liveness", "email": "liveness@gmail.com",
                             "password": "Str0ng!Pass9", "agreed_terms": True, "captcha": "12"})
otp = db.execute("SELECT otp FROM users WHERE username='liveness'").fetchone()["otp"]
TOK = client.post("/verify", json={"username": "liveness", "otp": otp}).json()["token"]
H = {"Authorization": "Bearer " + TOK}

# --- status must come from process liveness, not an HTTP ping --------------
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        "runner", "app.py")).read()
check("status is computed from proc.poll(), not an HTTP probe",
      'running = j["proc"] is not None and j["proc"].poll() is None' in src)

# =========================== NON-WEB JOB (Telegram bot) ====================
print("\n--- job that binds NO port (Telegram-bot style) ---")
BOT = "import time\nprint('polling', flush=True)\nwhile True:\n    time.sleep(1)\n"
jid = client.post("/api/jobs", json={"name": "tgbot", "language": "python",
                                     "code": BOT}, headers=H).json()["job_db_id"]
time.sleep(6)
check("bot with no port reports running",
      client.get(f"/api/jobs/{jid}", headers=H).json()["status"] == "running")

# The actual bug: registry lost, process still alive.
ra._jobs.clear()
check("registry loss alone would report offline",
      client.get(f"/api/jobs/{jid}", headers=H).json()["status"] == "offline")
ra._recover_jobs()
rec = client.get(f"/api/jobs/{jid}", headers=H).json()
check("recovery re-adopts the live bot", rec["status"] == "running", rec.get("status"))
check("recovered job keeps its uptime", rec.get("uptime_s", 0) > 0)

t0 = time.time()
r = client.post(f"/api/jobs/{jid}/restart", headers=H)
dt = time.time() - t0
check("restart completes without hanging", r.status_code == 200 and dt < 25, f"{dt:.1f}s")
time.sleep(5)
check("bot still running after restart",
      client.get(f"/api/jobs/{jid}", headers=H).json()["status"] == "running")

client.post(f"/api/jobs/{jid}/stop", headers=H)
time.sleep(2)
check("stop is reflected correctly",
      client.get(f"/api/jobs/{jid}", headers=H).json()["status"] in ("stopped", "offline"))
ra._jobs.clear()
ra._recover_jobs()
check("a stopped job is NOT resurrected on boot", len(ra._jobs) == 0, str(len(ra._jobs)))
client.delete(f"/api/jobs/{jid}", headers=H)

# =============================== WEB JOB ===================================
print("\n--- job that DOES bind a port (web server) ---")
WEB = ("import os, http.server, socketserver\n"
       "P = int(os.environ.get('PORT', '8000'))\n"
       "socketserver.TCPServer(('', P), http.server.SimpleHTTPRequestHandler).serve_forever()\n")
wid = client.post("/api/jobs", json={"name": "websrv", "language": "python",
                                     "code": WEB}, headers=H).json()["job_db_id"]
time.sleep(8)
w = client.get(f"/api/jobs/{wid}", headers=H).json()
check("web job reports running", w["status"] == "running", w.get("status"))
check("web job is detected as web", w.get("web") is True)
check("web job exposes its port", bool(w.get("port")), str(w.get("port")))
slug = next((j["web_slug"] for j in ra._jobs.values() if j.get("port")), None)
check("/live gateway serves the web job",
      slug and client.get(f"/live/{slug}/").status_code == 200)

ra._jobs.clear()
ra._recover_jobs()
w2 = client.get(f"/api/jobs/{wid}", headers=H).json()
check("web job survives recovery", w2["status"] == "running", w2.get("status"))
check("web job keeps its port after recovery", w2.get("port") == w.get("port"),
      f"{w.get('port')} -> {w2.get('port')}")
time.sleep(3)
check("/live still serves after recovery",
      slug and client.get(f"/live/{slug}/").status_code == 200)

client.post(f"/api/jobs/{wid}/stop", headers=H)
time.sleep(2)
check("web job stop is reflected",
      client.get(f"/api/jobs/{wid}", headers=H).json()["status"] in ("stopped", "offline"))
client.delete(f"/api/jobs/{wid}", headers=H)

passed = sum(1 for _, ok in results if ok)
failed = len(results) - passed
print(f"\n================ {passed} pass, {failed} fail ================")
sys.exit(1 if failed else 0)
