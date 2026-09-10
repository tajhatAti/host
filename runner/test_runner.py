"""Test the runner service locally — verify it compiles and executes code."""
import os, sys, subprocess, time, signal, json, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test the language configs and execution logic directly (no network needed).
from app import LANGS, _run_subprocess, _set_limits

passed = 0
failed = 0
def R(ok, msg):
    global passed, failed
    if ok: passed += 1; print("  PASS:", msg)
    else: failed += 1; print("  FAIL:", msg)

print("=== Language configs ===")
for lang in ["python", "javascript", "bash", "c", "cpp", "java"]:
    R(lang in LANGS, f"{lang} configured")
R(len(LANGS) >= 15, f"15+ languages supported ({len(LANGS)})")

print("\n=== Python execution ===")
tmpdir = tempfile.mkdtemp()
src = os.path.join(tmpdir, "main.py")
with open(src, "w") as f:
    f.write("print('Hello from Python!')\nimport sys\nprint(2+3)\n")
out, err, code, timed = _run_subprocess(["python3", src], tmpdir, None, 5)
R("Hello from Python!" in out, "Python stdout correct")
R("5" in out, "Python math works")
R(code == 0, "Python exit code 0")
shutil.rmtree(tmpdir, ignore_errors=True)

print("\n=== Bash execution ===")
tmpdir = tempfile.mkdtemp()
src = os.path.join(tmpdir, "main.sh")
with open(src, "w") as f:
    f.write("echo 'Hello Bash!'\n")
out, err, code, timed = _run_subprocess(["bash", src], tmpdir, None, 5)
R("Hello Bash!" in out, "Bash stdout correct")
shutil.rmtree(tmpdir, ignore_errors=True)

print("\n=== Timeout handling ===")
tmpdir = tempfile.mkdtemp()
src = os.path.join(tmpdir, "main.py")
with open(src, "w") as f:
    f.write("import time\nwhile True:\n  time.sleep(0.1)\n")
out, err, code, timed = _run_subprocess(["python3", src], tmpdir, None, 2)
R(timed == True, "Infinite loop → timeout=True")
R("timed out" in err.lower(), "Timeout message in stderr")
R(code == -1, "Timeout exit code -1")
shutil.rmtree(tmpdir, ignore_errors=True)

print("\n=== Syntax error handling ===")
tmpdir = tempfile.mkdtemp()
src = os.path.join(tmpdir, "main.py")
with open(src, "w") as f:
    f.write("print('hello'\n")  # missing closing paren
out, err, code, timed = _run_subprocess(["python3", src], tmpdir, None, 5)
R(code != 0, "Syntax error → non-zero exit")
R("SyntaxError" in err or "syntax" in err.lower(), "SyntaxError in stderr")
shutil.rmtree(tmpdir, ignore_errors=True)

print("\n=== stdin handling ===")
tmpdir = tempfile.mkdtemp()
src = os.path.join(tmpdir, "main.py")
with open(src, "w") as f:
    f.write("x = input()\nprint('You said:', x)\n")
out, err, code, timed = _run_subprocess(["python3", src], tmpdir, "Hello\n", 5)
R("You said: Hello" in out, "stdin piped correctly")
shutil.rmtree(tmpdir, ignore_errors=True)

print(f"\n{'='*40}")
print(f"RESULT: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
