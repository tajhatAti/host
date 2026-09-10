"""RunSpace capacity: per-account fairness vs per-container RAM limits.

THE BUG
A brand-new account with zero jobs was refused with "Runner at capacity
(5/5)". Cause: runner/app.py counted `_jobs`, which holds EVERY user's jobs on
that container, against MAX_BG_JOBS=5. So once the whole site held 5 bots,
nobody could create a sixth — the message blamed the user for other people's
jobs, and told them to "stop one" when the jobs were not theirs to stop.

THE TWO LIMITS, which were being conflated:
  MAX_JOBS_PER_USER  fairness. Per account, enforced by the main site.
  MAX_BG_JOBS        hardware. How many bots one 512MB container can hold.

Raising MAX_BG_JOBS past what the RAM supports would just OOM. Capacity grows
by ADDING RUNNERS: each extra RUNNER_SERVICE_URLS entry is another 512MB
instance, and a create rolls to the next runner when one reports itself full.

Run:  DATA_DIR=$(mktemp -d) python3 tests/test_runner_capacity.py
"""
import importlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("RUNNER_SERVICE_SECRET", "test-secret")
os.environ.setdefault("LIVE_PORT_MIN", "14600")
os.environ.setdefault("LIVE_PORT_MAX", "14699")

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -> {extra}" if extra else ""))


def fresh_rc(**env):
    for k in ("RUNNER_SERVICE_URL", "RUNNER_SERVICE_URLS", "MAX_JOBS_PER_USER"):
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    import services.runner_client as rc
    return importlib.reload(rc)


class Resp:
    def __init__(self, code, headers=None, body=None):
        self.status_code = code
        self.headers = headers or {}
        self._b = body or {}

    def json(self):
        return self._b


# ---------------------------------------------------------------------------
print("\n[1] the two limits are separate concepts")
# ---------------------------------------------------------------------------
rc = fresh_rc()
import runner.app as R  # noqa: E402

check("per-account default is 3", rc.MAX_JOBS_PER_USER == 3, str(rc.MAX_JOBS_PER_USER))
check("per-account limit is env-tunable",
      fresh_rc(MAX_JOBS_PER_USER="5").MAX_JOBS_PER_USER == 5)
fresh_rc()
check("per-container limit is no longer 5", R.MAX_BG_JOBS != 5, str(R.MAX_BG_JOBS))
check("per-container limit exceeds the per-account limit",
      R.MAX_BG_JOBS > rc.MAX_JOBS_PER_USER, f"{R.MAX_BG_JOBS} vs {rc.MAX_JOBS_PER_USER}")
# With the old value, 2 users at their personal limit already filled the site.
check("one container now holds several users at their full personal quota",
      R.MAX_BG_JOBS >= rc.MAX_JOBS_PER_USER * 4,
      f"{R.MAX_BG_JOBS} < {rc.MAX_JOBS_PER_USER * 4}")

# ---------------------------------------------------------------------------
print("[2] a full runner reports itself as a SERVER condition")
# ---------------------------------------------------------------------------
src = open(os.path.join(ROOT, "runner/app.py"), encoding="utf-8").read()
check("full runner returns 503, not 429",
      'raise HTTPException(\n            503,' in src or "HTTPException(503" in src)
check("it sets the X-Runner-Full marker", '"X-Runner-Full": "1"' in src)
check("it no longer tells the user to stop their own job",
      "Stop one first" not in src)
check("the message says THIS runner, not the whole service",
      "This runner is full" in src)

# ---------------------------------------------------------------------------
print("[3] the pool parses correctly")
# ---------------------------------------------------------------------------
cases = [
    ({}, []),
    ({"RUNNER_SERVICE_URL": "https://a.com"}, ["https://a.com"]),
    ({"RUNNER_SERVICE_URL": "https://a.com/",
      "RUNNER_SERVICE_URLS": "https://b.com, https://c.com"},
     ["https://a.com", "https://b.com", "https://c.com"]),
    ({"RUNNER_SERVICE_URLS": "https://b.com,https://b.com"}, ["https://b.com"]),
    ({"RUNNER_SERVICE_URL": "https://a.com",
      "RUNNER_SERVICE_URLS": "https://a.com"}, ["https://a.com"]),
]
for env, expect in cases:
    rc = fresh_rc(**env)
    check(f"pool {env or '{}'} -> {expect}", rc.runner_pool() == expect,
          str(rc.runner_pool()))
rc = fresh_rc()
check("no URLs means embedded mode (single service still works)", rc.embedded_mode())
rc = fresh_rc(RUNNER_SERVICE_URLS="https://only-secondary.com")
check("a secondary-only config still leaves embedded mode", not rc.embedded_mode())
check("runner_cfg still returns the primary for single-runner callers",
      rc.runner_cfg()[0] == "https://only-secondary.com")

# ---------------------------------------------------------------------------
print("[4] creates overflow to the next runner; other calls do not roam")
# ---------------------------------------------------------------------------
rc = fresh_rc(RUNNER_SERVICE_URL="https://a.test",
              RUNNER_SERVICE_URLS="https://b.test")
calls = []


def full_then_ok(method, url, **kw):
    calls.append(url)
    if url.startswith("https://a.test"):
        return Resp(503, {"X-Runner-Full": "1"})
    return Resp(201, {}, {"id": "newjob"})


rc.requests.request = full_then_ok
r = rc._runner_http("POST", "/internal/jobs", {"code": "x"})
check("create succeeded on the overflow runner", r.status_code == 201, str(r.status_code))
check("it tried runner A first, then B", len(calls) == 2 and "b.test" in calls[1],
      str(calls))

calls.clear()
rc._runner_http("POST", "/internal/jobs/abc/restart")
check("an existing job's call targets only its own runner", len(calls) == 1, str(calls))

# A genuinely full site must still say so rather than looping forever.
calls.clear()
rc.requests.request = lambda m, u, **k: (calls.append(u), Resp(503, {"X-Runner-Full": "1"}))[1]
r = rc._runner_http("POST", "/internal/jobs", {"code": "x"})
check("all runners full -> honest 503", r.status_code == 503)
check("every runner was tried", len(calls) == 2, str(calls))

# An asleep runner must not block placement on a healthy one.
calls.clear()


def asleep_then_ok(method, url, **kw):
    calls.append(url)
    if url.startswith("https://a.test"):
        raise rc.requests.ConnectionError("cold start")
    return Resp(201, {}, {"id": "j2"})


rc.requests.request = asleep_then_ok
r = rc._runner_http("POST", "/internal/jobs", {"code": "x"})
check("a sleeping runner is skipped, not fatal", r.status_code == 201, str(r.status_code))

# ---------------------------------------------------------------------------
print("[5] control: the old behaviour really did block new accounts")
# ---------------------------------------------------------------------------


class P:
    def poll(self):
        return None


R._jobs.clear()
for i in range(5):
    R._jobs[f"j{i}"] = {"proc": P()}
active = sum(1 for j in R._jobs.values() if j["proc"] and j["proc"].poll() is None)
check("5 site-wide jobs would have tripped the OLD cap of 5", active >= 5)
check("but they do NOT trip the new cap", active < R.MAX_BG_JOBS,
      f"{active} vs {R.MAX_BG_JOBS}")
R._jobs.clear()

# ---------------------------------------------------------------------------
print("[6] documented for the operator")
# ---------------------------------------------------------------------------
env_example = open(os.path.join(ROOT, ".env.example"), encoding="utf-8").read()
check("RUNNER_SERVICE_URLS documented", "RUNNER_SERVICE_URLS" in env_example)
check("MAX_BG_JOBS documented", "MAX_BG_JOBS" in env_example)
check("MAX_JOBS_PER_USER documented", "MAX_JOBS_PER_USER" in env_example)

print(f"\ntest_runner_capacity: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
