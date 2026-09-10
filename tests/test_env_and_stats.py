# JOB ENV VARS + LIVE RESOURCE STATS
#
# Both features existed only as dead UI:
#   * The Details "Environment variables" panel wrote to localStorage, so the
#     job process never received the values and they vanished on another
#     device. There was no env column, no API field and no injection at spawn.
#   * The CPU/Memory rows had no data source at all (the runner never reported
#     usage), so they could only ever render "—".
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
from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402

client = TestClient(app)
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("\u2713 " if cond else "\u2717 FAIL ") + f"{name:56s}" + (f" \u2014 {extra}" if not cond else ""))


client.post("/signup", json={"username": "envuser", "email": "envuser@gmail.com",
                             "password": "Str0ng!Pass9", "agreed_terms": True, "captcha": "12"})
otp = db.execute("SELECT otp FROM users WHERE username='envuser'").fetchone()["otp"]
TOK = client.post("/verify", json={"username": "envuser", "otp": otp}).json()["token"]
H = {"Authorization": "Bearer " + TOK}

CODE = ("import os, time\n"
        "print('TOKEN=' + os.environ.get('BOT_TOKEN', 'MISSING'), flush=True)\n"
        "print('PATH_OK=' + str(os.environ.get('PATH', '') != 'HACKED'), flush=True)\n"
        "x = 0\n"
        "for i in range(2000000): x += i\n"
        "time.sleep(90)\n")

r = client.post("/api/jobs", json={
    "name": "envjob", "language": "python", "code": CODE,
    # PATH must be rejected (hijack), "bad key" must be rejected (invalid name)
    "env": {"BOT_TOKEN": "secret123", "PATH": "HACKED", "bad key": "x"},
}, headers=H)
check("job created with env", r.status_code == 200, r.text[:120])
jid = r.json().get("job_db_id")
time.sleep(7)

logs = client.get(f"/api/jobs/{jid}/logs", headers=H).json().get("logs", "")
check("env var reaches the process", "TOKEN=secret123" in logs, logs[-160:])
check("PATH cannot be overridden", "PATH_OK=True" in logs, logs[-160:])

row = client.get("/api/jobs", headers=H).json()["jobs"][0]
check("env returned to the UI", (row.get("env") or {}).get("BOT_TOKEN") == "secret123", str(row.get("env")))
check("invalid key filtered out", "bad key" not in (row.get("env") or {}))
check("PATH not persisted", "PATH" not in (row.get("env") or {}))
check("env persisted in the database",
      "BOT_TOKEN" in (db.execute("SELECT env FROM jobs WHERE id=?", (jid,)).fetchone()["env"] or ""))

check("memory reported", row.get("mem_mb") is not None, str(row.get("mem_mb")))
check("cpu reported", row.get("cpu_pct") is not None, str(row.get("cpu_pct")))
check("port reported", bool(row.get("port")), str(row.get("port")))

# Editing env must reach the RESPAWNED process, not just the database.
check("env edit accepted",
      client.patch(f"/api/jobs/{jid}", json={"env": {"BOT_TOKEN": "updated999"}},
                   headers=H).status_code == 200)
time.sleep(7)
seen = [l for l in client.get(f"/api/jobs/{jid}/logs", headers=H).json().get("logs", "").splitlines()
        if l.startswith("TOKEN=")]
check("edited env applied on redeploy", seen and seen[-1] == "TOKEN=updated999", str(seen[-2:]))

check("restart accepted", client.post(f"/api/jobs/{jid}/restart", headers=H).status_code == 200)
time.sleep(6)
seen2 = [l for l in client.get(f"/api/jobs/{jid}/logs", headers=H).json().get("logs", "").splitlines()
         if l.startswith("TOKEN=")]
check("env survives restart", seen2 and seen2[-1] == "TOKEN=updated999", str(seen2[-2:]))

# Omitting env on an unrelated edit must not wipe it.
client.patch(f"/api/jobs/{jid}", json={"name": "envjob2"}, headers=H)
kept = db.execute("SELECT env FROM jobs WHERE id=?", (jid,)).fetchone()["env"] or ""
check("unrelated edit keeps env", "updated999" in kept, kept[:80])

client.post(f"/api/jobs/{jid}/stop", headers=H)
client.delete(f"/api/jobs/{jid}", headers=H)

passed = sum(1 for _, ok in results if ok)
failed = len(results) - passed
print(f"\n================ {passed} pass, {failed} fail ================")
sys.exit(1 if failed else 0)
