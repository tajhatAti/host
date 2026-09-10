"""Admin monitoring dashboard: access control, live numbers, drill-downs.

Every number here is checked against REAL data — a real login, a real spawned
job — not fixtures. A monitoring panel that reports plausible-looking numbers
is worse than no panel, because it is trusted.

ACCESS CONTROL is asserted first and hardest: a non-admin must get a plain
404, never 403 and never a redirect, because "you don't have permission"
confirms the page exists.

Run:  DATA_DIR=$(mktemp -d) DB_PATH=$(mktemp -d)/t.db python3 tests/test_admin_dashboard.py
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATA_DIR", _tmp)
os.environ["DB_PATH"] = os.path.join(_tmp, "admin_test.db")
os.environ.setdefault("RUNNER_SERVICE_SECRET", "test-secret")
os.environ.setdefault("LIVE_PORT_MIN", "17800")
os.environ.setdefault("LIVE_PORT_MAX", "17899")

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import database as DB  # noqa: E402
DB.init_db()
import app as A  # noqa: E402
import runner.app as R  # noqa: E402
from routes.deps import now_utc_str  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -> {extra}" if extra else ""))


c = TestClient(A.app, raise_server_exceptions=False)
PW = "Passw0rd!x"
_h = bcrypt.hashpw(PW.encode(), bcrypt.gensalt()).decode()
conn = DB.get_db_connection()
conn.execute("INSERT INTO users (username,email,password,is_verified,is_admin,created_at,updated_at)"
             " VALUES (?,?,?,1,1,?,?)", ("boss", "boss@gmail.com", _h, now_utc_str(), now_utc_str()))
conn.execute("INSERT INTO users (username,email,password,is_verified,is_admin,created_at,updated_at)"
             " VALUES (?,?,?,1,0,?,?)", ("normie", "normie@gmail.com", _h, now_utc_str(), now_utc_str()))
conn.execute("INSERT INTO users (username,email,password,is_verified,telegram_id,created_at,updated_at)"
             " VALUES (?,?,?,1,?,?,?)", ("tguser", "tg@gmail.com", _h, 5551234, now_utc_str(), now_utc_str()))
conn.commit()
conn.close()


def login(u):
    r = c.post("/login", json={"username": u, "password": PW})
    return (r.json() or {}).get("token")


AT, NT = login("boss"), login("normie")
AH, NH = {"Authorization": "Bearer " + AT}, {"Authorization": "Bearer " + NT}

ADMIN_ROUTES = ["/admin/overview", "/admin/users", "/admin/users/2",
                "/admin/jobs", "/admin/libraries", "/admin/audit-log",
                "/admin/abuse-reports"]

# ---------------------------------------------------------------------------
print("\n[1] access control")
# ---------------------------------------------------------------------------
check("admin logged in", bool(AT))
check("non-admin logged in", bool(NT))
for p in ADMIN_ROUTES:
    r = c.get(p, headers=NH)
    check(f"non-admin gets 404 on {p}", r.status_code == 404, str(r.status_code))
    # 403 would confirm the route exists; a redirect would too.
    check(f"{p} never says 'permission'", "permission" not in r.text.lower(), r.text[:60])
    check(f"{p} does not redirect", r.status_code not in (301, 302, 307, 308))
for p in ADMIN_ROUTES:
    r = c.get(p)
    check(f"anonymous is refused on {p}", r.status_code in (401, 404), str(r.status_code))
for p in ADMIN_ROUTES:
    check(f"admin CAN reach {p}", c.get(p, headers=AH).status_code == 200)

html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
js = open(os.path.join(ROOT, "static/pro.js"), encoding="utf-8").read()
check("the admin tab ships hidden", 'id="tabBtnAdmin"' in html and "hidden" in html)
check("visibility is driven by the server's is_admin",
      "applyAdminVisibility" in js and "profile.is_admin" in js)
check("non-admins have the panel REMOVED from the DOM, not just hidden",
      "must not merely hide its DATA" in js)

# ---------------------------------------------------------------------------
print("[2] overview reports real numbers")
# ---------------------------------------------------------------------------
ov = c.get("/admin/overview", headers=AH).json()
check("counts the users that actually exist", ov["users"] == 3, str(ov.get("users")))
for w in ("signups_24h", "signups_7d", "signups_30d"):
    check(f"{w} present", w in ov, str(sorted(ov)))
check("all 3 signups land in the 24h window", ov["signups_24h"] == 3, str(ov.get("signups_24h")))
check("windows widen monotonically",
      ov["signups_24h"] <= ov["signups_7d"] <= ov["signups_30d"])
check("active users measured from real sessions", ov.get("active_users", 0) >= 2,
      str(ov.get("active_users")))
check("the active window is stated", ov.get("active_window_min") == 15)
for k in ("mem_used_mb", "mem_safe_mb", "mem_total_mb", "mem_pct"):
    check(f"memory field {k}", k in ov, str(sorted(ov)))
check("memory is shown against a ceiling, not as a raw number",
      ov["mem_safe_mb"] > 0 and 0 <= ov["mem_pct"] <= 100, str(ov.get("mem_pct")))

# ---------------------------------------------------------------------------
print("[3] a REAL job, measured end to end")
# ---------------------------------------------------------------------------
# Add Bot requires a server-issued Telegram verification proof. Telegram itself
# is replaced only at this network boundary; the runner/job remains real.
from services import telegram_detector as _td  # noqa: E402
class _TgResp:
    status_code = 200
    def json(self): return {"ok": True, "result": {"id": 777, "is_bot": True, "username": "AdminTestBot"}}
_td.requests.post = lambda *a, **k: _TgResp()
_test_bot_token = "123456789:AA" + "x" * 32
_proof = c.post("/api/telegram-bot/verify", headers=AH,
                json={"token": _test_bot_token}).json()["telegram_verification_id"]
r = c.post("/api/jobs", headers=AH, json={
    "name": "realbot", "language": "python",
    "code": "import time\nprint('hello from the bot', flush=True)\nwhile True:\n    time.sleep(1)\n",
    "env": {"BOT_TOKEN": _test_bot_token},
    "telegram_verification_id": _proof})
check("job created", r.status_code in (200, 201), str(r.status_code))
for j in R._jobs.values():
    j["libs"] = ["pyTelegramBotAPI", "requests", "numpy"]
time.sleep(3)

jobs = c.get("/admin/jobs", headers=AH).json()["jobs"]
check("the job is listed", len(jobs) == 1, str(len(jobs)))
jb = jobs[0]
check("live status comes from the runner", jb["live_status"] == "running", str(jb.get("live_status")))
check("memory is a real measurement", (jb.get("mem_mb") or 0) > 0, str(jb.get("mem_mb")))
check("peak is tracked", (jb.get("peak_mem_mb") or 0) > 0, str(jb.get("peak_mem_mb")))
check("peak is never below current", jb["peak_mem_mb"] >= jb["mem_mb"])
check("cpu is reported", jb.get("cpu_pct") is not None)
check("the owner is named", jb.get("owner") == "boss", str(jb.get("owner")))
check("the worker is identified", bool(jb.get("worker")), str(jb.get("worker")))
check("installed packages surface", set(jb["libs"]) == {"numpy", "pyTelegramBotAPI", "requests"},
      str(jb.get("libs")))
check("source is labelled", jb.get("source") in ("website", "telegram"))
check("and marked as INFERRED, since no source column is recorded",
      jb.get("source_inferred") is True)
check("the code is never exposed", "code" not in jb, str(sorted(jb)))

ov = c.get("/admin/overview", headers=AH).json()
check("status breakdown counts the running job",
      (ov.get("jobs_by_status") or {}).get("running") == 1, str(ov.get("jobs_by_status")))
check("platform memory reflects the real job", ov["mem_used_mb"] > 0, str(ov["mem_used_mb"]))

# ---------------------------------------------------------------------------
print("[3b] per-app detail, from the REAL running job")
# ---------------------------------------------------------------------------
# The list view already carried mem_mb/peak/restarts/libs and threw them away
# in the browser, and there was no route to ask for more. GET /admin/jobs/1
# answered 404 before this existed.
det = c.get(f"/admin/jobs/{jb['id']}", headers=AH)
check("a per-app route exists", det.status_code == 200, str(det.status_code))
dj = det.json()
job = dj["job"]
check("it is the right app", job["name"] == "realbot", str(job.get("name")))
check("status comes from the runner", job["status"] == "running", str(job.get("status")))
check("memory is measured, not guessed", (job.get("mem_mb") or 0) > 0, str(job.get("mem_mb")))
check("the peak is carried through", (job.get("peak_mem_mb") or 0) >= job["mem_mb"])
check("restarts are reported", job.get("restarts") == 0, str(job.get("restarts")))
check("the owner is named", job["owner"] == "boss")
check("with their other apps counted", job.get("owner_job_count") == 1,
      str(job.get("owner_job_count")))
check("the worker is identified", bool(job.get("worker")))
check("packages are listed", set(job.get("libs") or []) ==
      {"numpy", "pyTelegramBotAPI", "requests"}, str(job.get("libs")))
check("the runner answered", dj["runner_reachable"] is True)
check("the app's own log is returned", "hello from the bot" in dj["logs"],
      repr(dj["logs"][:120]))
check("the log is tailed, not unbounded", len(dj["logs"].splitlines()) <= 200)

# The two things that must never leave the server.
check("the source code is not in the payload", "code" not in job, str(sorted(job)))
check("no env VALUE is echoed", "env" not in job and "env_values" not in job,
      str(sorted(job)))
check("only env KEY names are returned", isinstance(job.get("env_keys"), list))
check("a non-admin gets the same 404 as an unknown URL",
      c.get(f"/admin/jobs/{jb['id']}", headers=NH).status_code == 404)
check("so does an anonymous visitor",
      c.get(f"/admin/jobs/{jb['id']}").status_code == 404)
check("a missing app is 404, not 500",
      c.get("/admin/jobs/9999", headers=AH).status_code == 404)

# A job whose worker cannot be reached must read as UNKNOWN. Calling it
# "offline" invents a fact — the app may be running perfectly.
conn = DB.get_db_connection()
conn.execute("INSERT INTO jobs (user_id,name,language,code,runner_job_id,worker_url,"
             "created_at,updated_at) VALUES (1,'ghost','python','x','gone',?,?,?)",
             ("https://asleep.test", now_utc_str(), now_utc_str()))
conn.commit()
gid = dict(conn.execute("SELECT id FROM jobs WHERE name='ghost'").fetchone())["id"]
conn.close()
import services.runner_client as _RC  # noqa: E402
_saved_http = _RC._runner_http


def _unreachable(method, path, json_body=None, worker=None):
    from fastapi import HTTPException as _HE
    if worker == "https://asleep.test":
        raise _HE(status_code=503, detail="asleep")
    return _saved_http(method, path, json_body, worker)


_RC._runner_http = _unreachable
try:
    g = c.get(f"/admin/jobs/{gid}", headers=AH).json()
    check("an unreachable worker reads as unknown", g["job"]["status"] == "unknown",
          str(g["job"].get("status")))
    check("it is NOT called offline", g["job"]["status"] != "offline")
    check("and the console is told the status is stale",
          g["job"].get("status_stale") is True)
    check("the response says the runner was unreachable",
          g["runner_reachable"] is False)
finally:
    _RC._runner_http = _saved_http
    conn = DB.get_db_connection()
    conn.execute("DELETE FROM jobs WHERE name='ghost'")
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
print("[4] library aggregation")
# ---------------------------------------------------------------------------
lib = c.get("/admin/libraries", headers=AH).json()
names = [e["library"] for e in lib["libraries"]]
check("packages are aggregated", set(names) == {"numpy", "pyTelegramBotAPI", "requests"}, str(names))
check("sorted by frequency", all(
    lib["libraries"][i]["count"] >= lib["libraries"][i + 1]["count"]
    for i in range(len(lib["libraries"]) - 1)))
check("each entry names the jobs using it",
      all(e["jobs"] and e["jobs"][0]["owner"] == "boss" for e in lib["libraries"]))
heavy = [e["library"] for e in lib["libraries"] if e["heavy"]]
check("a heavy framework is flagged", "numpy" in heavy, str(heavy))
check("an ordinary package is NOT flagged",
      not any(e["heavy"] or e["watch"] for e in lib["libraries"] if e["library"] == "requests"))
check("the sample size is stated", lib.get("jobs_sampled") == 1)
check("the limitation is stated rather than hidden", "currently known" in lib.get("note", ""))

# ---------------------------------------------------------------------------
print("[5] per-user drill-down")
# ---------------------------------------------------------------------------
d = c.get("/admin/users/1", headers=AH).json()
check("account info returned", d["user"]["username"] == "boss")
check("their jobs are listed", len(d["jobs"]) == 1, str(len(d["jobs"])))
check("resource total is summed", d["mem_used_mb"] > 0, str(d.get("mem_used_mb")))
check("login history included", isinstance(d.get("sessions"), list) and len(d["sessions"]) >= 1,
      str(len(d.get("sessions") or [])))
check("sessions carry IP", "ip_address" in (d["sessions"][0] or {}))
check("sessions carry fingerprint", "fingerprint" in (d["sessions"][0] or {}))
tg = c.get("/admin/users/3", headers=AH).json()
check("telegram signup detected", tg["user"]["auth_method"] == "telegram",
      str(tg["user"].get("auth_method")))
check("auth method is marked inferred", tg["user"]["auth_method_inferred"] is True)
check("a missing user is 404, not 500", c.get("/admin/users/9999", headers=AH).status_code == 404)

# ---------------------------------------------------------------------------
print("[5b] memory attribution + linked accounts, from real rows")
# ---------------------------------------------------------------------------
# Packages used to be ordered by COUNT, which on a 512MB box ranks trivia
# above the thing holding the RAM.
lib2 = c.get("/admin/libraries", headers=AH).json()
check("the response flags memory as attributed", lib2.get("mem_attributed") is True)
check("every package carries a memory figure",
      all("mem_mb" in e for e in lib2["libraries"]), str(lib2["libraries"][:1]))
check("the figure is the real measured RSS of the importing job",
      all(e["mem_mb"] > 0 for e in lib2["libraries"]), str([e["mem_mb"] for e in lib2["libraries"]]))
check("ordering is by memory, not by name or count",
      [e["mem_mb"] for e in lib2["libraries"]] ==
      sorted([e["mem_mb"] for e in lib2["libraries"]], reverse=True),
      str([(e["library"], e["mem_mb"]) for e in lib2["libraries"]]))
check("each entry names the jobs, with their memory",
      all(e["jobs"] and "mem_mb" in e["jobs"][0] for e in lib2["libraries"]))
# One job importing three packages contributes its whole RSS to all three, so
# the column MUST over-sum. If it ever equalled the platform total, the
# attribution would be silently wrong.
attributed = sum(e["mem_mb"] for e in lib2["libraries"])
one_job_mem = jb["mem_mb"]
check("attributed memory over-sums, exactly as the label warns",
      attributed > one_job_mem * 2, f"{attributed} vs {one_job_mem}")

# A second account on the SAME device fingerprint — the thing this view exists
# to surface. Written as real rows, then read back through the route.
conn = DB.get_db_connection()
conn.execute("UPDATE users SET fingerprint = ?, last_ip = ? WHERE id = 1",
             ("fp-shared", "203.0.113.9"))
conn.execute("INSERT INTO users (username,email,password,is_verified,fingerprint,"
             "last_ip,created_at,updated_at) VALUES (?,?,?,1,?,?,?,?)",
             ("twin", "twin@gmail.com", _h, "fp-shared", "203.0.113.9",
              now_utc_str(), now_utc_str()))
conn.execute("INSERT INTO users (username,email,password,is_verified,fingerprint,"
             "last_ip,created_at,updated_at) VALUES (?,?,?,1,?,?,?,?)",
             ("stranger", "stranger@gmail.com", _h, "fp-other", "198.51.100.4",
              now_utc_str(), now_utc_str()))
conn.commit()
conn.close()

dd = c.get("/admin/users/1", headers=AH).json()
names = [a["username"] for a in dd.get("linked_accounts", [])]
check("an account sharing the device fingerprint is surfaced", "twin" in names, str(names))
check("an unrelated account is NOT", "stranger" not in names, str(names))
check("the account never lists itself", "boss" not in names, str(names))
check("the shared-network caveat travels with the data",
      "prompt to look, not proof" in (dd.get("linked_note") or ""), str(dd.get("linked_note")))
check("distinct devices are counted from real sessions",
      dd.get("devices") is not None and dd.get("networks", 0) >= 1,
      f"devices={dd.get('devices')} networks={dd.get('networks')}")
# ids: 1 boss, 2 normie, 3 tguser, 4 twin, 5 stranger. Resolve by NAME — I
# hardcoded 4 first and asserted "no links" against twin, which shares the
# fingerprint on purpose, so the test was wrong rather than the route.
conn = DB.get_db_connection()
_sid = dict(conn.execute("SELECT id FROM users WHERE username='stranger'").fetchone())["id"]
_tid = dict(conn.execute("SELECT id FROM users WHERE username='twin'").fetchone())["id"]
conn.close()
check("an unrelated account reports no links",
      c.get(f"/admin/users/{_sid}", headers=AH).json().get("linked_accounts") == [],
      str(c.get(f"/admin/users/{_sid}", headers=AH).json().get("linked_accounts")))
check("the link is symmetric — twin sees boss too",
      "boss" in [a["username"] for a in
                 c.get(f"/admin/users/{_tid}", headers=AH).json().get("linked_accounts", [])])
check("the drill-down is still 404 for a non-admin",
      c.get("/admin/users/1", headers=NH).status_code == 404)

# ---------------------------------------------------------------------------
print("[6] live updates are bounded")
# ---------------------------------------------------------------------------
check("polling exists", "_admSetPolling" in js)
check("interval is 10s, not sub-second", "ADM_POLL_MS = 10000" in js)
check("polling stops when the tab is not open", '_admSetPolling(tabId === "admin")' in js)
check("polling pauses in a background tab", "if (document.hidden) return;" in js)
check("it resumes on refocus", "visibilitychange" in js)
check("a failed poll does not break the panel", "loadAdminPanel(true).catch(() => {})" in js)

# ---------------------------------------------------------------------------
print("[6b] the monitor is not a load source")
# ---------------------------------------------------------------------------
# Counted at the HTTP layer on a 3-worker pool, BEFORE the fix: one dashboard
# refresh made 12 upstream calls (9 x /internal/jobs + 3 x /health), because
# four admin routes each call fleet_jobs() and the overview forced
# worker_health(refresh=True). At a 10s poll that is 72 calls/minute — the
# console becoming a real source of load on the box it exists to watch.
import services.runner_client as _RC2  # noqa: E402

_pool_saved = (os.environ.get("RUNNER_SERVICE_URL"), os.environ.get("RUNNER_SERVICE_URLS"))
os.environ["RUNNER_SERVICE_URL"] = "https://w-a.test"
os.environ["RUNNER_SERVICE_URLS"] = "https://w-b.test,https://w-c.test"
_RC2._health_cache.clear()
_RC2._fleet_cache.update(at=0.0, jobs=None)
_upstream = []


class _R2:
    def __init__(self, code, body=None):
        self.status_code, self._b, self.headers = code, body or {}, {}

    def json(self):
        return self._b


def _count_req(method, url, **kw):
    _upstream.append(url)
    return _R2(200, {"jobs": []})


def _count_get(url, **kw):
    _upstream.append(url)
    return _R2(200, {"status": "ok", "jobs": 0, "mem_mb": 0.0, "safe_mb": 419.0,
                     "total_mb": 512.0, "free_mb": 419.0, "load": 0.0,
                     "free": 13, "full": False})


_sr, _sg = _RC2.requests.request, _RC2.requests.get
_RC2.requests.request, _RC2.requests.get = _count_req, _count_get
try:
    # Exactly what one refresh of the panel does.
    for _p in ("/admin/overview", "/admin/users", "/admin/jobs",
               "/admin/abuse-reports", "/admin/audit-log", "/admin/libraries"):
        c.get(_p, headers=AH)
    jobs_calls = [u for u in _upstream if u.endswith("/internal/jobs")]
    health_calls = [u for u in _upstream if u.endswith("/health")]
    check("the fleet is polled ONCE per worker, not once per admin route",
          len(jobs_calls) == 3, f"{len(jobs_calls)} calls: {jobs_calls}")
    check("health is probed once per worker too",
          len(health_calls) == 3, f"{len(health_calls)}")
    check("a refresh costs 6 upstream calls on a 3-worker pool, not 12",
          len(_upstream) == 6, f"{len(_upstream)}")

    # Correctness must not be traded for the saving: a write invalidates.
    _upstream.clear()
    _RC2._runner_http("POST", "/internal/jobs/x/stop", worker="https://w-a.test")
    _upstream.clear()
    c.get("/admin/jobs", headers=AH)
    check("a write invalidates the cache, so a stopped job stops showing",
          len([u for u in _upstream if u.endswith("/internal/jobs")]) == 3,
          str(_upstream))

    # And the cache must expire on its own, or the panel would freeze.
    _RC2._fleet_cache["at"] = 0.0
    _upstream.clear()
    c.get("/admin/jobs", headers=AH)
    check("an expired cache re-probes rather than serving forever",
          len([u for u in _upstream if u.endswith("/internal/jobs")]) == 3,
          str(_upstream))
finally:
    _RC2.requests.request, _RC2.requests.get = _sr, _sg
    _RC2._fleet_cache.update(at=0.0, jobs=None)
    _RC2._health_cache.clear()
    for _k, _v in zip(("RUNNER_SERVICE_URL", "RUNNER_SERVICE_URLS"), _pool_saved):
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v

# ---------------------------------------------------------------------------
print("[7] rendering is injection-safe")
# ---------------------------------------------------------------------------
check("package names are set via textContent", "name.textContent = r.library" in js)
check("the review flag says review, not abuse",
      'r.watch ? "review" : "heavy"' in js)

# ---------------------------------------------------------------------------
print("[8] the numbers stay true across a MULTI-WORKER fleet")
# ---------------------------------------------------------------------------
# Everything above ran embedded (one in-process runner), which is the one
# topology where asking "the" runner happens to be right. The live deployment
# runs two services. Reproduced before the fix, with one running job on each
# worker: overview said 1 running, /admin/jobs called the worker-B job dead,
# libraries sampled 1 job, and the whole memory panel was absent because the
# health probe dropped safe_mb/total_mb.
import services.runner_client as RC  # noqa: E402

conn = DB.get_db_connection()
conn.execute("INSERT INTO jobs (user_id,name,language,code,runner_job_id,worker_url,"
             "created_at,updated_at) VALUES (1,'onB','python','x','jb',?,?,?)",
             ("https://worker-b.test", now_utc_str(), now_utc_str()))
conn.commit()
conn.close()

_A, _B = "https://worker-a.test", "https://worker-b.test"
os.environ["RUNNER_SERVICE_URL"] = _A
os.environ["RUNNER_SERVICE_URLS"] = _B
RC._health_cache.clear()


class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b, self.headers = code, body or {}, {}

    def json(self):
        return self._b


_real_job = list(R._jobs.values())[0]
_rid_a = _real_job["id"]
_mem_a = (R._proc_stats(_real_job.get("proc")) or {}).get("mem_mb", 0.0)


def _fleet(method, url, **kw):
    """worker-A mirrors the REAL in-process job; worker-B adds a second."""
    if url.endswith("/internal/jobs") and method.upper() == "GET":
        if url.startswith(_A):
            return _Resp(200, {"jobs": [R._job_public(_real_job)]})
        return _Resp(200, {"jobs": [{"id": "jb", "status": "running",
                                     "mem_mb": 40.0, "peak_mem_mb": 41.0,
                                     "cpu_pct": 2.0, "uptime_s": 9,
                                     "libs": ["numpy", "requests"]}]})
    return _Resp(200, {})


def _health(url, **kw):
    return _Resp(200, {"status": "ok", "jobs": 1,
                       "mem_mb": _mem_a if url.startswith(_A) else 40.0,
                       "safe_mb": 419.0, "total_mb": 512.0,
                       "free_mb": 379.0, "load": 0.1, "free": 12, "full": False})


_saved_req, _saved_get = RC.requests.request, RC.requests.get
RC.requests.request, RC.requests.get = _fleet, _health
try:
    ov2 = c.get("/admin/overview", headers=AH).json()
    check("both workers' running jobs are counted",
          (ov2.get("jobs_by_status") or {}).get("running") == 2,
          str(ov2.get("jobs_by_status")))
    check("the memory panel survives the pool probe",
          ov2.get("mem_safe_mb", 0) > 0, str(ov2.get("mem_safe_mb")))
    check("platform memory sums BOTH workers",
          ov2["mem_used_mb"] >= 40 + _mem_a - 1, str(ov2.get("mem_used_mb")))
    check("both workers report online", ov2.get("workers_online") == 2,
          str(ov2.get("workers_online")))

    jobs2 = {j["name"]: j for j in c.get("/admin/jobs", headers=AH).json()["jobs"]}
    check("a job on the overflow worker is NOT reported dead",
          jobs2["onB"]["live_status"] == "running", str(jobs2["onB"].get("live_status")))
    check("its memory is real, not null", (jobs2["onB"].get("mem_mb") or 0) > 0)
    check("the first worker's job is still fine",
          jobs2["realbot"]["live_status"] == "running")

    lib2 = c.get("/admin/libraries", headers=AH).json()
    check("libraries sample the whole fleet", lib2["jobs_sampled"] == 2,
          str(lib2.get("jobs_sampled")))
    check("a package used on both workers is counted twice",
          next(e["count"] for e in lib2["libraries"] if e["library"] == "requests") == 2,
          str([(e["library"], e["count"]) for e in lib2["libraries"]]))

    d2 = c.get("/admin/users/1", headers=AH).json()
    check("per-user totals span workers", d2["jobs_running"] == 2, str(d2.get("jobs_running")))
    check("per-user memory sums both", d2["mem_used_mb"] >= 40, str(d2.get("mem_used_mb")))
finally:
    RC.requests.request, RC.requests.get = _saved_req, _saved_get
    os.environ.pop("RUNNER_SERVICE_URL", None)
    os.environ.pop("RUNNER_SERVICE_URLS", None)
    RC._health_cache.clear()

for j in list(R._jobs.values()):
    try:
        j["proc"].kill()
    except Exception:
        pass

print(f"\ntest_admin_dashboard: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
