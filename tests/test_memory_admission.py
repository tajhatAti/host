"""Admission by MEASURED memory, not by job count.

WHY
The gate was `active >= MAX_BG_JOBS` with MAX_BG_JOBS≈12, a number derived
from worst-case per-job memory. Real idle Telegram bots never reach worst
case, so a box with plenty of free RAM refused the 13th job. Counting jobs
answers the wrong question.

MEASURED on this codebase (tests below reproduce it): a bare `while True:
sleep(1)` python process is ~7.7MB RSS. pyTelegramBotAPI/aiogram with a
requests session lands ~25-35MB idle. So the assumed footprint for a job that
cannot be measured yet is 30MB, not 45 — over-reserving would quietly
reintroduce the same pessimism.

UNCHANGED ON PURPOSE: MAX_MEMORY_MB, the per-job RLIMIT_AS applied at spawn.
That stops ONE runaway process eating the container. Admission decides whether
there is room for one more. Different jobs; the test asserts both still exist.

Run:  DATA_DIR=$(mktemp -d) python3 tests/test_memory_admission.py
"""
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("RUNNER_SERVICE_SECRET", "test-secret")
os.environ.setdefault("LIVE_PORT_MIN", "16300")
os.environ.setdefault("LIVE_PORT_MAX", "16399")
os.environ["MEM_TOTAL_MB"] = "512"          # pin: CI boxes are not 512MB

import runner.app as R  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -> {extra}" if extra else ""))


class Bot:
    """A job using a fixed amount of memory."""

    def __init__(self, mb):
        self.mb = mb
        self.pid = 1

    def poll(self):
        return None


_real_stats = R._proc_stats
R._proc_stats = lambda p: {"mem_mb": getattr(p, "mb", 0.0)}


def fill(n, mb):
    R._jobs.clear()
    R._jobs.update({f"j{i}": {"proc": Bot(mb)} for i in range(n)})
    return R._admission()


def fits(mb):
    n = 0
    while n <= 200:
        if not fill(n, mb)["admit"]:
            return n - 1
        n += 1
    return n


# ---------------------------------------------------------------------------
print("\n[1] the budget is derived from the CONTAINER, not the host")
# ---------------------------------------------------------------------------
check("MEM_TOTAL_MB honoured", R.MEM_TOTAL_MB == 512, str(R.MEM_TOTAL_MB))
check("safe threshold is ~82% of total",
      0.78 <= R.MEM_SAFE_MB / R.MEM_TOTAL_MB <= 0.86,
      f"{R.MEM_SAFE_MB}/{R.MEM_TOTAL_MB}")
src = open(os.path.join(ROOT, "runner/app.py"), encoding="utf-8").read()
check("cgroup v2 is read before /proc/meminfo", "/sys/fs/cgroup/memory.max" in src)
check("cgroup v1 fallback exists", "memory/memory.limit_in_bytes" in src)
check("a cgroup 'unlimited' sentinel is rejected", "1 << 62" in src)
# Compare the CODE positions, not the first textual mention — a comment above
# the function explains why /proc/meminfo is wrong and would match first.
_fn = src[src.index("def _container_total_mb"):src.index("MEM_TOTAL_MB = _container")]
check("/proc/meminfo is only the last resort",
      _fn.index("/sys/fs/cgroup/memory.max") < _fn.index("/proc/meminfo"))

# ---------------------------------------------------------------------------
print("[2] light jobs are admitted where a count-based cap refused them")
# ---------------------------------------------------------------------------
OLD_COUNT_CAP = 12
light = fits(28)
print(f"      28MB idle bots  -> {light} fit ({light * 28}MB)")
check("more light bots fit than the old count cap allowed",
      light > OLD_COUNT_CAP, f"{light} vs {OLD_COUNT_CAP}")
check("but the box is not oversubscribed", light * 28 <= R.MEM_SAFE_MB,
      f"{light * 28}MB > {R.MEM_SAFE_MB}MB")

heavy = fits(120)
print(f"      120MB heavy bots -> {heavy} fit ({heavy * 120}MB)")
check("heavy jobs are cut off well BEFORE the old count cap",
      heavy < OLD_COUNT_CAP, str(heavy))
check("heavy jobs stay within the threshold too", heavy * 120 <= R.MEM_SAFE_MB)
check("memory, not count, decides", light != heavy, f"{light} vs {heavy}")

# ---------------------------------------------------------------------------
print("[3] the gate refuses only when memory really is short")
# ---------------------------------------------------------------------------
R._jobs.clear()
check("empty worker admits", R._admission()["admit"])
fill(1, R.MEM_SAFE_MB + 50)          # one job already over the threshold
check("an over-budget worker refuses", not R._admission()["admit"])
fill(2, 30)
a = R._admission()
check("admission reports what it measured",
      a["used_mb"] == 60 and a["safe_mb"] == R.MEM_SAFE_MB, str(a))
check("free headroom is exposed", a["free_mb"] == R.MEM_SAFE_MB - 60, str(a))

# An unmeasurable-but-alive job must not read as free capacity.
class Opaque:
    def poll(self):
        return None


R._jobs.clear()
R._jobs["x"] = {"proc": Opaque()}
R._proc_stats = _real_stats           # will raise: Opaque has no .pid
used = R._used_mem_mb()
R._proc_stats = lambda p: {"mem_mb": getattr(p, "mb", 0.0)}
check("an unmeasurable live job still reserves memory",
      used >= R.MEM_ASSUMED_JOB_MB, str(used))

# A pathological swarm of near-zero jobs must still be bounded.
fill(R.MAX_BG_JOBS_HARD + 5, 0.1)
check("a hard count guard remains for PID/fd exhaustion",
      not R._admission()["admit"])
R._jobs.clear()

# ---------------------------------------------------------------------------
print("[4] the assumed footprint matches reality")
# ---------------------------------------------------------------------------
d = tempfile.mkdtemp()
f = os.path.join(d, "b.py")
open(f, "w").write("import time\nwhile True: time.sleep(1)\n")
procs = [subprocess.Popen([sys.executable, f], cwd=d,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
         for _ in range(3)]
time.sleep(2.0)
rss = []
for p in procs:
    try:
        with open(f"/proc/{p.pid}/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    rss.append(int(line.split()[1]) / 1024)
    except Exception:
        pass
for p in procs:
    p.kill()
if rss:
    avg = sum(rss) / len(rss)
    print(f"      bare python process = {avg:.1f}MB RSS")
    check("a bare python process is well under the assumption",
          avg < R.MEM_ASSUMED_JOB_MB, f"{avg:.1f} vs {R.MEM_ASSUMED_JOB_MB}")
    check("the assumption leaves room for bot libraries",
          R.MEM_ASSUMED_JOB_MB >= avg * 2, f"{R.MEM_ASSUMED_JOB_MB} vs {avg:.1f}")
else:
    check("could measure a real process", False, "no /proc data")
check("the assumption is not so large it recreates the old pessimism",
      R.MEM_ASSUMED_JOB_MB <= 40, str(R.MEM_ASSUMED_JOB_MB))

# ---------------------------------------------------------------------------
print("[5] the per-job RLIMIT is untouched")
# ---------------------------------------------------------------------------
check("MAX_MEMORY_MB still exists", R.MAX_MEM_MB > 0, str(R.MAX_MEM_MB))
check("RLIMIT_AS still applied in preexec", "RLIMIT_AS" in src)
check("long-running jobs still spawn with it", "preexec_fn=_set_limits" in src)
check("it is a per-JOB ceiling, not the admission budget",
      R.MAX_MEM_MB != R.MEM_SAFE_MB, f"{R.MAX_MEM_MB} vs {R.MEM_SAFE_MB}")

# ---------------------------------------------------------------------------
print("[6] health reports memory so routing can use it")
# ---------------------------------------------------------------------------
R._jobs.clear()
h = R.health()
for field in ("mem_mb", "safe_mb", "total_mb", "free_mb", "full", "load", "jobs"):
    check(f"/health exposes {field}", field in h, str(sorted(h)))
check("load is a memory fraction", h["load"] == 0.0, str(h["load"]))
fill(1, R.MEM_SAFE_MB)
h = R.health()
check("a saturated worker reports full", h["full"] is True, str(h))
check("load is clamped at 1.0", h["load"] <= 1.0, str(h["load"]))
R._jobs.clear()
check("/health still leaks no job detail",
      not any(k in R.health() for k in ("names", "code", "env")), "")

# ---------------------------------------------------------------------------
print("[7] no preemptive limit is advertised; OOM is explained after the fact")
# ---------------------------------------------------------------------------
check("an OOM kill is named in the log",
      "Process stopped: exceeded memory limit" in src)
check("SIGKILL is treated as OOM", "rc == -9" in src)
check("a Python MemoryError is recognised too", '"MemoryError" in tail' in src)
check("the full-runner message blames the server, not the user",
      "This runner is full" in src and "Stop one first" not in src)
check("the full message quotes memory, not a slot count",
      "in use)" in src)

js = open(os.path.join(ROOT, "static/pro.js"), encoding="utf-8").read()
html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
for phrase in ("you can only", "limit reached", "not allowed",
               "maximum of", "quota exceeded"):
    check(f"UI never preemptively warns: '{phrase}'",
          phrase not in js.lower() and phrase not in html.lower())

# ---------------------------------------------------------------------------
print("[8] admin capacity is memory, not slots")
# ---------------------------------------------------------------------------
adm = open(os.path.join(ROOT, "routes/admin.py"), encoding="utf-8").read()
for field in ("mem_used_mb", "mem_safe_mb", "mem_total_mb", "mem_pct"):
    check(f"overview exposes {field}", f'"{field}"' in adm)
check("per-worker breakdown included", '"workers"' in adm)
check("embedded mode still reports", '"embedded"' in adm)
check("admin UI prints MB, not slots", "MB / ${ov.mem_safe_mb}MB" in js)
check("admin UI still shows the job count alongside", "job${jobs === 1" in js)
check("the old slot wording is gone", "slots used" not in js)

print(f"\ntest_memory_admission: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
