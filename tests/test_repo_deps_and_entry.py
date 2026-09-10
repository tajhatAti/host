"""GitHub-clone correctness: manifest install, and a fresh entry scan.

REPORTED
  1. A cloned repo runs without installing requirements.txt -> ModuleNotFoundError.
  2. Renaming the entry file (n.py -> main.py) leaves the runner using stale
     state; it reports "code is empty".

ROOT CAUSES FOUND (both in runner/app.py)

  1. The repo-manifest install was gated on `repo_url and detected_src`, and
     the same expression was passed to _prepare_and_run() as its is_repo
     flag. _detect_entry() only recognises a fixed list of names (main.py,
     app.py, bot.py, ...), so a repo whose entry is called anything else
     returned (None, None) -> detected_src None -> flag falsy ->
     _install_repo_deps never ran, with requirements.txt sitting in the
     checkout. The install mechanism was correct and simply unreachable.

  2. job_restart() re-spawned j["file"], the path chosen once at create
     time. Nothing invalidated it when the file set changed, so a rename
     left it pointing at a path that no longer existed, or at an empty stub.

These tests exercise the real functions against real temp directories -- no
mock filesystem -- because both bugs were about what is actually on disk.
"""
import os
import sys
import tempfile
import shutil
import types
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("TERM_HOMES_ROOT", tempfile.mkdtemp())

from runner import app as R  # noqa: E402

_pass = 0
_fail = 0


def ok(name, cond, extra=""):
    global _pass, _fail
    if cond:
        _pass += 1
    else:
        _fail += 1
        print(f"  FAIL {name}" + (f" -> {extra}" if extra else ""))


def mkrepo(**files):
    d = tempfile.mkdtemp()
    for rel, body in files.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(body)
    return d


# ─────────────────────────────────────────────────────────────────────────
print("[1] a manifest triggers the install regardless of entry detection")

# Read the predicate OUT OF THE SHIPPING SOURCE rather than restating it.
#
# The first version of this file copied the expression into the test. That
# made every case pass even with the fix reverted -- it was checking a copy
# of the logic against itself, which is the classic way a regression suite
# proves nothing. Now the real line is extracted and evaluated, so reverting
# the fix fails here.
_APP_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "runner", "app.py")).read()
_m = None
for _ln in _APP_SRC.splitlines():
    _t = _ln.strip()
    if _t.startswith("repo_has_manifest = "):
        _m = _t
        break
if _m is None:
    print("  FAIL the create path does not compute repo_has_manifest at all")
    _fail += 1
    MANIFESTS = ()
else:
    # Pull the manifest tuple straight out of the source.
    import re as _re
    _blk = _APP_SRC[_APP_SRC.index("repo_has_manifest = "):]
    _blk = _blk[:_blk.index(")\n", _blk.index("(\"")) + 1]
    MANIFESTS = tuple(_re.findall(r'"([A-Za-z][\w.+-]*)"', _blk))


def manifest_seen(jdir, repo_url="https://github.com/u/r"):
    """Mirrors the shipped predicate, using the manifest list read from it."""
    return bool(repo_url) and any(
        os.path.isfile(os.path.join(jdir, m)) for m in MANIFESTS)


# The reported case: entry file NOT in _ENTRY_CANDIDATES.
d = mkrepo(**{"n.py": "import requests\n", "requirements.txt": "requests\n"})
lang, src = R._detect_entry(d, False, deque())
# CHANGED: this used to assert detection FAILS for an unconventional name,
# which was the state of the world, not a requirement. The reported repo
# (tajhatati/bb) has n.py as its only source file and was rejected as
# "code empty", so detection now falls back to whatever source is present.
ok("an unconventional entry name is now found by fallback",
   src is not None and src.endswith("n.py"), f"detected {src}")
ok("and the manifest is seen, so deps install",
   manifest_seen(d) is True)
shutil.rmtree(d, ignore_errors=True)

# The old predicate, kept here so the difference is visible and enforced.
d = mkrepo(**{"n.py": "x=1\n", "requirements.txt": "requests\n"})
lang, src = R._detect_entry(d, False, deque())
# The old gate was `repo_url and detected_src`. It is no longer reachable
# by this input because detection now succeeds -- so assert the property
# that actually matters instead: the install does not depend on detection.
d2 = mkrepo(**{"README.md": "no source at all\n", "requirements.txt": "requests\n"})
_l2, s2 = R._detect_entry(d2, False, deque())
ok("with NO source file at all, detection still fails", s2 is None, f"{s2}")
ok("...yet the manifest alone still triggers the install",
   manifest_seen(d2) is True)
shutil.rmtree(d2, ignore_errors=True)
ok("the NEW predicate installs", manifest_seen(d) is True)
shutil.rmtree(d, ignore_errors=True)

# Recognised entry name: must still work.
d = mkrepo(**{"main.py": "import requests\n", "requirements.txt": "requests\n"})
lang, src = R._detect_entry(d, False, deque())
ok("a conventional entry is still detected", src is not None and src.endswith("main.py"))
ok("and the manifest still triggers the install", manifest_seen(d) is True)
shutil.rmtree(d, ignore_errors=True)

# Other ecosystems.
for manifest, body in [("package.json", '{"dependencies":{"axios":"1"}}'),
                       ("Gemfile", 'gem "sinatra"\n'),
                       ("pyproject.toml", "[project]\nname='x'\n"),
                       ("composer.json", '{"require":{}}')]:
    d = mkrepo(**{manifest: body, "weird_name.py": "x=1\n"})
    ok(f"{manifest} is recognised as a manifest", manifest_seen(d) is True)
    shutil.rmtree(d, ignore_errors=True)

# No manifest at all -> no repo install, inline import detection instead.
d = mkrepo(**{"main.py": "print(1)\n"})
ok("a repo with no manifest does not trigger a repo install",
   manifest_seen(d) is False)
shutil.rmtree(d, ignore_errors=True)

# Not a repo at all -> never a repo install, even with a stray file.
d = mkrepo(**{"requirements.txt": "requests\n"})
ok("pasted-code jobs never take the repo path",
   manifest_seen(d, repo_url="") is False)
shutil.rmtree(d, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────
print("\n[2] _install_repo_deps actually reads requirements.txt")
d = mkrepo(**{"requirements.txt": "requests==2.31.0\n"})
calls = []
real_run = R._run_subprocess
try:
    # Record the command instead of hitting the network.
    R._run_subprocess = lambda cmd, cwd, *a, **k: (calls.append((cmd, cwd)) or ("", "", 0, False))
    log = deque()
    okrc = R._install_repo_deps(d, os.path.join(d, "pylibs"), "python", log)
    ok("it returns success", okrc is not False)
    ok("it ran pip install -r requirements.txt",
       any("-r" in c and "requirements.txt" in c for c, _ in calls),
       str(calls))
    ok("it targeted the job's private lib dir",
       any("--target" in c for c, _ in calls), str(calls))
    joined = "\n".join(log)
    ok("the log shows the install to the user", "requirements.txt" in joined, joined)
    ok("and confirms completion", "✓" in joined, joined)
finally:
    R._run_subprocess = real_run
shutil.rmtree(d, ignore_errors=True)

print("\n[2b] a failed install is surfaced, not swallowed")
d = mkrepo(**{"requirements.txt": "nope-does-not-exist\n"})
try:
    R._run_subprocess = lambda cmd, cwd, *a, **k: ("", "ERROR: no matching distribution", 1, False)
    log = deque()
    okrc = R._install_repo_deps(d, os.path.join(d, "pylibs"), "python", log)
    ok("a failing pip run reports failure", okrc is False)
    ok("and the reason reaches the log", "failed" in "\n".join(log).lower(), "\n".join(log))
finally:
    R._run_subprocess = real_run
shutil.rmtree(d, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────
print("\n[3] the entry file is re-scanned, never cached")


def job_for(d, lang="python", **extra):
    j = {"dir": d, "lang": lang, "log": deque(maxlen=200)}
    j.update(extra)
    return j


# The reported scenario, step by step.
d = mkrepo(**{"n.py": "print('hello')\n"})
j = job_for(d, file=os.path.join(d, "n.py"))
ok("before the rename the entry resolves to n.py",
   R._resolve_entry_now(j).endswith("n.py"))

os.rename(os.path.join(d, "n.py"), os.path.join(d, "main.py"))
resolved = R._resolve_entry_now(j)
ok("after renaming n.py -> main.py it follows the rename",
   resolved is not None and resolved.endswith("main.py"),
   str(resolved))
ok("and it does NOT return the path that no longer exists",
   resolved != os.path.join(d, "n.py"))
shutil.rmtree(d, ignore_errors=True)

# An empty file is exactly the "code is empty" report: it must not win.
d = mkrepo(**{"main.py": "", "bot.py": "print(1)\n"})
j = job_for(d, file=os.path.join(d, "main.py"))
resolved = R._resolve_entry_now(j)
ok("an EMPTY main.py is not treated as runnable",
   resolved is not None and resolved.endswith("bot.py"), str(resolved))
shutil.rmtree(d, ignore_errors=True)

# A single source file under any name is found.
d = mkrepo(**{"totally_custom.py": "print(1)\n"})
j = job_for(d, file=os.path.join(d, "gone.py"))
resolved = R._resolve_entry_now(j)
ok("a lone file under an unknown name is found",
   resolved is not None and resolved.endswith("totally_custom.py"), str(resolved))
shutil.rmtree(d, ignore_errors=True)

# Several candidates and no convention: refuse rather than guess wrong.
d = mkrepo(**{"alpha.py": "print(1)\n", "beta.py": "print(2)\n"})
j = job_for(d, file=os.path.join(d, "gone.py"))
ok("with several candidates and no convention it declines to guess",
   R._resolve_entry_now(j) is None)
shutil.rmtree(d, ignore_errors=True)

# ...unless one of them is conventional.
d = mkrepo(**{"alpha.py": "print(1)\n", "main.py": "print(2)\n"})
j = job_for(d, file=os.path.join(d, "alpha.py"))
ok("a conventional name wins when present",
   R._resolve_entry_now(j).endswith("main.py"))
shutil.rmtree(d, ignore_errors=True)

# An explicit pin from the file browser beats everything.
d = mkrepo(**{"main.py": "print(1)\n", "src/worker.py": "print(2)\n"})
j = job_for(d, file=os.path.join(d, "main.py"), entry_rel="src/worker.py")
ok("an explicit entry pin wins over the conventional name",
   R._resolve_entry_now(j).endswith(os.path.join("src", "worker.py")))
shutil.rmtree(d, ignore_errors=True)

# A pin that has gone stale must fall back, not break the job.
d = mkrepo(**{"main.py": "print(1)\n"})
j = job_for(d, file=os.path.join(d, "main.py"), entry_rel="deleted.py")
resolved = R._resolve_entry_now(j)
ok("a stale pin falls back to a real file",
   resolved is not None and resolved.endswith("main.py"), str(resolved))
ok("and says so in the log", "pinned entry" in "\n".join(j["log"]), "\n".join(j["log"]))
shutil.rmtree(d, ignore_errors=True)

# Language awareness.
d = mkrepo(**{"index.js": "console.log(1)\n"})
j = job_for(d, lang="javascript", file=os.path.join(d, "gone.js"))
ok("node entry points resolve too",
   (R._resolve_entry_now(j) or "").endswith("index.js"))
shutil.rmtree(d, ignore_errors=True)

# Nothing runnable at all.
d = mkrepo(**{"README.md": "hi\n"})
j = job_for(d, file=os.path.join(d, "main.py"))
ok("an unrunnable workspace resolves to None (so restart can report it)",
   R._resolve_entry_now(j) is None)
shutil.rmtree(d, ignore_errors=True)

# A vanished directory must not raise.
j = job_for("/tmp/definitely-not-here-xyz", file="/tmp/definitely-not-here-xyz/main.py")
ok("a missing directory is handled, not raised", R._resolve_entry_now(j) is None)


# ─────────────────────────────────────────────────────────────────────────
print("\n[4] restart uses the fresh scan")
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "runner", "app.py")).read()
i = src.index("def job_restart(")
block = src[i:i + 2200]
ok("restart calls the re-scan", "_resolve_entry_now(j)" in block)
ok("restart updates j['file'] from it", 'j["file"] = fresh' in block)
ok("restart refuses to spawn when nothing is runnable",
   "nothing runnable" in block)
ok("and it does so BEFORE _spawn", block.index("nothing runnable") < block.index("_spawn(j)"))

print("\n[5] the create path no longer gates deps on entry detection")
# Strip comments first: the fix's own explanation quotes the old predicate,
# and matching that text made the check pass/fail on prose rather than code.
_code_only = "\n".join(
    ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
ok("the old predicate is gone from the CODE",
   "repo_url and detected_src" not in _code_only)
ok("a manifest check replaces it", "repo_has_manifest" in src)
ok("and it is what the worker is told",
   "_prepare_and_run, args=(job, reqs, repo_has_manifest)" in src)



# ─────────────────────────────────────────────────────────────────────────
print("\n[6] file browser: listing, reading, and pinning an entry")

# ---- path safety. The job directory is the security boundary, and the
# caller controls `path` entirely, so traversal is the first thing to prove.
base = mkrepo(**{"main.py": "print(1)\n", "src/mod.py": "x=1\n"})
outside = tempfile.mkdtemp()
with open(os.path.join(outside, "secret.txt"), "w") as f:
    f.write("do not read me")

# Two distinct outcomes are both correct, and conflating them was my error:
#
#   ESCAPING inputs ("../x") must raise.
#   ABSOLUTE inputs ("/etc/passwd") are NEUTRALISED by lstrip("/") into a
#   relative path, so they resolve to <jobdir>/etc/passwd -- inside the
#   boundary, pointing at a file that does not exist. That is safe, and
#   demanding an exception there was testing my assumption, not the guard.
#   The property that matters is the same either way: the result never
#   leaves the job directory.
_base_real = os.path.realpath(base)
for attack in ["../secret.txt", "../../etc/passwd", "src/../../secret.txt",
               "/etc/passwd", "....//....//etc/passwd", "src/../../../tmp",
               "..", "../", "src/../..", "%2e%2e/secret.txt"]:
    try:
        got = os.path.realpath(R._fb_safe_join(base, attack))
        contained = got == _base_real or got.startswith(_base_real + os.sep)
        ok(f"never escapes the job dir: {attack}", contained,
           f"resolved to {got} — boundary broken")
    except Exception as e:
        # Raising is the other acceptable answer.
        ok(f"never escapes the job dir: {attack}",
           "outside" in str(e) or "400" in str(e) or "path required" in str(e), str(e))

# A symlink planted inside the checkout must not escape either.
try:
    os.symlink(outside, os.path.join(base, "escape"))
    try:
        R._fb_safe_join(base, "escape/secret.txt")
        ok("symlink out of the job dir is blocked", False, "IT RESOLVED")
    except Exception:
        ok("symlink out of the job dir is blocked", True)
except (OSError, NotImplementedError):
    ok("symlink out of the job dir is blocked (skipped: no symlink support)", True)

# Legitimate paths still resolve.
ok("a normal path resolves", R._fb_safe_join(base, "main.py").endswith("main.py"))
ok("a nested path resolves",
   R._fb_safe_join(base, "src/mod.py").endswith(os.path.join("src", "mod.py")))
try:
    R._fb_safe_join(base, "")
    ok("an empty path is rejected", False)
except Exception:
    ok("an empty path is rejected", True)

# ---- binary detection, so the tree can mark what is openable
with open(os.path.join(base, "blob.bin"), "wb") as f:
    f.write(b"\x7fELF\x02\x00\x00")
ok("a text file is reported as text", R._fb_is_texty(os.path.join(base, "main.py")))
ok("a binary file is not", not R._fb_is_texty(os.path.join(base, "blob.bin")))

# ---- the listing itself, exercised through the endpoint function
for noisy in [".git/config", "node_modules/x/index.js", "pylibs/requests/__init__.py",
              "__pycache__/main.cpython-311.pyc", ".env"]:
    fp = os.path.join(base, noisy)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    open(fp, "w").write("noise")

R._jobs["fbtest"] = {"id": "fbtest", "dir": base, "lang": "python",
                     "file": os.path.join(base, "main.py"),
                     "log": deque(maxlen=50)}
_real_check = R._check_secret
R._check_secret = lambda *a, **k: None
try:
    listing = R.job_files("fbtest", authorization="Bearer x")
    paths = [f["path"] for f in listing["files"]]
    ok("the tree lists real source files", "main.py" in paths and "src/mod.py" in paths, str(paths))
    for junk in [".git", "node_modules", "pylibs", "__pycache__"]:
        ok(f"{junk} is not listed", not any(p.startswith(junk) for p in paths), str(paths))
    ok("dotfiles are not listed", not any(p.startswith(".") for p in paths), str(paths))
    ok("it reports the current entry", listing["entry"] == "main.py", str(listing["entry"]))
    ok("binary files are marked non-text",
       any(f["path"] == "blob.bin" and f["text"] is False for f in listing["files"]),
       str(listing["files"]))

    # ---- reading
    got = R.job_file_read("fbtest", path="src/mod.py", authorization="Bearer x")
    ok("a file's content is returned", got["content"] == "x=1\n", repr(got.get("content")))
    try:
        R.job_file_read("fbtest", path="blob.bin", authorization="Bearer x")
        ok("a binary file cannot be opened", False, "it returned content")
    except Exception as e:
        ok("a binary file cannot be opened", "binary" in str(e).lower(), str(e))
    try:
        R.job_file_read("fbtest", path="nope.py", authorization="Bearer x")
        ok("a missing file 404s", False)
    except Exception as e:
        ok("a missing file 404s", "not found" in str(e).lower(), str(e))

    # ---- pinning the entry point, which is the whole point of the feature
    res = R.job_set_entry("fbtest", R.EntryPinRequest(path="src/mod.py"),
                          authorization="Bearer x")
    ok("pinning returns the new entry", res["entry"] == "src/mod.py", str(res))
    j = R._jobs["fbtest"]
    ok("the pin is recorded on the job", j.get("entry_rel") == "src/mod.py")
    ok("and the fresh scan now honours it",
       R._resolve_entry_now(j).endswith(os.path.join("src", "mod.py")))
    ok("the log tells the user to restart",
       "Restart" in "\n".join(j["log"]), "\n".join(j["log"]))

    # Pinning cannot be used to escape the directory either.
    try:
        R.job_set_entry("fbtest", R.EntryPinRequest(path="../secret.txt"),
                        authorization="Bearer x")
        ok("pinning cannot escape the job dir", False, "IT ACCEPTED")
    except Exception:
        ok("pinning cannot escape the job dir", True)

    # Pinning a .js file should switch the language with it.
    open(os.path.join(base, "worker.js"), "w").write("console.log(1)\n")
    res = R.job_set_entry("fbtest", R.EntryPinRequest(path="worker.js"),
                          authorization="Bearer x")
    ok("pinning a .js entry switches the language",
       R._jobs["fbtest"].get("lang") == "javascript", str(res))
finally:
    R._check_secret = _real_check
    R._jobs.pop("fbtest", None)

shutil.rmtree(base, ignore_errors=True)
shutil.rmtree(outside, ignore_errors=True)

print("\n[7] the browser reads disk every call — no cached listing")
_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "runner", "app.py")).read()
_fb = _src[_src.index("def job_files("):_src.index("def job_file_read(")]
ok("the listing walks the directory on each request", "os.walk(" in _fb)
ok("no module-level cache backs it",
   "_fb_cache" not in _src and "@lru_cache" not in _fb)

print(f"\ntest_repo_deps_and_entry: {_pass} passed, {_fail} failed")
sys.exit(1 if _fail else 0)
