# RUNNER SERVICE BOOT — crash-loop regression.
#
# The runner ships in TWO layouts:
#   * embedded   — the whole repo is importable, so it is `runner.terminal`
#   * standalone — runner/Dockerfile does `COPY . .` from inside runner/, so
#                  the files land FLAT in /app and there is no `runner`
#                  package at all.
#
# runner/app.py hardcoded `from runner import terminal`, so the standalone
# service died on boot with:
#     ModuleNotFoundError: No module named 'runner'
# uvicorn never started and Render restarted it forever.
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("\u2713 " if cond else "\u2717 FAIL ") + f"{name:56s}" + (f" \u2014 {extra}" if not cond else ""))


# The import must tolerate BOTH layouts.
src = open(os.path.join(ROOT, "runner", "app.py"), encoding="utf-8").read()
check("package import is attempted", "from runner import terminal as _term" in src)
check("flat import is the fallback", "import terminal as _term" in src)
check("fallback catches ModuleNotFoundError", "except ModuleNotFoundError:" in src)

# 1. STANDALONE: replicate runner/Dockerfile — copy runner/* flat, no package.
sim = tempfile.mkdtemp()
for f in os.listdir(os.path.join(ROOT, "runner")):
    s = os.path.join(ROOT, "runner", f)
    if os.path.isfile(s):
        shutil.copy(s, os.path.join(sim, f))
os.remove(os.path.join(sim, "__init__.py"))       # a flat copy has no package marker
check("simulated layout has no runner/ package",
      not os.path.isdir(os.path.join(sim, "runner")))

env = dict(os.environ,
           DATA_DIR=tempfile.mkdtemp(),
           JOBS_DATA_DIR=tempfile.mkdtemp(),
           TERM_HOMES_DIR=tempfile.mkdtemp())
p = subprocess.run([sys.executable, "-c", "import app; print('BOOT_OK')"],
                   cwd=sim, env=env, capture_output=True, text=True, timeout=180)
check("standalone runner boots", "BOOT_OK" in p.stdout,
      (p.stderr or "")[-200:])
check("no ModuleNotFoundError for 'runner'",
      "No module named 'runner'" not in (p.stderr or ""),
      (p.stderr or "")[-200:])

# 2. EMBEDDED: the same file must still import as a package.
p2 = subprocess.run(
    [sys.executable, "-c", "import runner.app as ra; print('PKG_OK', ra.app.title)"],
    cwd=ROOT, env=dict(os.environ, DATA_DIR=tempfile.mkdtemp()),
    capture_output=True, text=True, timeout=180)
check("embedded (package) import still works", "PKG_OK" in p2.stdout,
      (p2.stderr or "")[-200:])

passed = sum(1 for _, ok in results if ok)
failed = len(results) - passed
print(f"\n================ {passed} pass, {failed} fail ================")
sys.exit(1 if failed else 0)
