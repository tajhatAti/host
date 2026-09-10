"""Curated system tooling in the RunSpace base image.

WHY THIS EXISTS
A user's audio-trimming bot failed with "ffmpeg: command not found". The wrong
fix would be to detect the import and run apt-get at job runtime: RunSpace is
a shared, free, multi-tenant container, so letting anonymous job code install
system packages would let one user mutate — or break — the environment every
other bot depends on. The right fix is to bake the tool into the image at
BUILD time, under platform control.

This test guards three things that are easy to get quietly wrong:

  1. the tools are actually in BOTH Dockerfiles (the single-service image and
     the standalone runner). If they drift, a job that works in one
     deployment fails in the other and the platform is silently inconsistent.
  2. no runtime apt-get / sudo path is ever introduced in Python.
  3. a job can genuinely reach a system binary — proven by running one
     through the runner's real environment-construction code, not asserted.

Run:  DATA_DIR=$(mktemp -d) python3 tests/test_system_tools.py
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("RUNNER_SERVICE_SECRET", "test-secret")
os.environ.setdefault("LIVE_PORT_MIN", "14300")
os.environ.setdefault("LIVE_PORT_MAX", "14399")

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -> {extra}" if extra else ""))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


ROOT_DF = read("Dockerfile")
RUNNER_DF = read("runner/Dockerfile")

# Tools the docs promise. imagemagick ships `convert`; ffmpeg ships `ffprobe`.
REQUIRED = ["ffmpeg", "imagemagick", "git", "unzip", "zip", "curl", "sqlite3", "jq"]

# ---------------------------------------------------------------------------
print("\n[1] tools present in the single-service image")
# ---------------------------------------------------------------------------
for tool in REQUIRED:
    check(f"Dockerfile installs {tool}",
          re.search(rf"^\s*.*\b{re.escape(tool)}\b", ROOT_DF, re.M) is not None)

# ---------------------------------------------------------------------------
print("[2] the standalone runner image matches")
# ---------------------------------------------------------------------------
for tool in REQUIRED:
    check(f"runner/Dockerfile installs {tool}",
          re.search(rf"^\s*.*\b{re.escape(tool)}\b", RUNNER_DF, re.M) is not None)

# The two images must not drift: a job working in one deployment but not the
# other is worse than the tool being missing from both.
media = re.compile(r"ffmpeg\s+imagemagick")
check("both images declare the media layer identically",
      bool(media.search(ROOT_DF)) and bool(media.search(RUNNER_DF)))

# ---------------------------------------------------------------------------
print("[3] installs happen at BUILD time, never at job runtime")
# ---------------------------------------------------------------------------
for label, df in (("Dockerfile", ROOT_DF), ("runner/Dockerfile", RUNNER_DF)):
    for line in df.splitlines():
        s = line.strip()
        if "apt-get install" in s and not s.startswith("#"):
            check(f"{label}: apt-get install only inside a RUN layer",
                  s.startswith("RUN") or s.startswith("&&") or "&&" in s, s[:60])
    check(f"{label}: apt lists cleaned (image stays small)",
          "rm -rf /var/lib/apt/lists" in df)

# No Python file may shell out to a system package manager. This is the
# security constraint, so it is asserted rather than trusted.
offenders = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames
                   if d not in {".git", "node_modules", "__pycache__", "design",
                                ".venv", "venv", "editor-src"}]
    for fn in filenames:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(dirpath, fn)
        if os.path.abspath(p) == os.path.abspath(__file__):
            continue
        for i, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
            code = line.split("#", 1)[0]
            if re.search(r"""["'](?:sudo|apt-get|apt)\b""", code):
                offenders.append(f"{os.path.relpath(p, ROOT)}:{i}")
check("no Python code invokes apt-get/sudo", not offenders, ", ".join(offenders[:4]))

# ---------------------------------------------------------------------------
print("[4] a job can actually reach a system binary")
# ---------------------------------------------------------------------------
import runner.app as R  # noqa: E402

# A job must never be able to redirect PATH to its own binaries, or the
# curated toolchain means nothing.
hostile = R._clean_env({
    "PATH": "/tmp/evil", "LD_PRELOAD": "/tmp/x.so",
    "LD_LIBRARY_PATH": "/tmp", "BOT_TOKEN": "keep-me",
})
check("PATH cannot be overridden by a job", "PATH" not in hostile, str(hostile))
check("LD_PRELOAD cannot be overridden", "LD_PRELOAD" not in hostile)
check("LD_LIBRARY_PATH cannot be overridden", "LD_LIBRARY_PATH" not in hostile)
check("ordinary env vars still reach the job", hostile.get("BOT_TOKEN") == "keep-me")

env = dict(os.environ)
env.update(hostile)
check("job PATH includes the system bin dir", "/usr/bin" in env.get("PATH", ""),
      env.get("PATH", "")[:60])

# Run a real system binary the way user bot code would. `convert` (imagemagick)
# is present in CI; ffmpeg may not be, and the MECHANISM under test is
# identical either way — this proves subprocess reaches PATH binaries.
probe = None
for cand in ("ffmpeg", "convert", "git"):
    if subprocess.run(["which", cand], capture_output=True).returncode == 0:
        probe = cand
        break
if probe:
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "main.py"), "w") as fh:
        fh.write(
            "import subprocess\n"
            f"r = subprocess.run(['{probe}', '-version'], capture_output=True, text=True)\n"
            "print('rc=' + str(r.returncode))\n"
        )
    out = subprocess.run([sys.executable, "main.py"], cwd=d, env=env,
                         capture_output=True, text=True, timeout=60)
    check(f"a job invoked '{probe}' successfully", "rc=0" in out.stdout,
          (out.stdout + out.stderr)[:80])
else:
    check("a probe binary was available to test with", False, "none found")

# ---------------------------------------------------------------------------
print("[5] documented for users")
# ---------------------------------------------------------------------------
DOC = read("runner/SYSTEM_TOOLS.md")
for tool in ("ffmpeg", "ffprobe", "imagemagick", "git", "unzip"):
    check(f"docs list {tool}", tool in DOC)
check("docs explain WHY apt-get is unavailable",
      "multi-tenant" in DOC or "shared" in DOC)
check("docs tell users how to request a tool", "Telegram" in DOC)
check("docs note pip/npm are still automatic", "pip" in DOC and "npm" in DOC)
check("maintainer note warns both Dockerfiles must match",
      "lockstep" in DOC and "runner/Dockerfile" in DOC)

HTML = read("index.html")
check("UI surfaces the tool list", "Pre-installed tools" in HTML)
for tool in ("ffmpeg", "imagemagick", "git"):
    check(f"UI chip for {tool}", f">{tool}<" in HTML)
check("UI explains the no-apt policy", "cannot be installed per job" in HTML)

print(f"\ntest_system_tools: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
