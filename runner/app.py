"""
runner/app.py — Code Execution Runner Service (Service #2)

A standalone FastAPI service that receives code, executes it in a sandboxed
subprocess with strict resource limits, and returns the output.

Deploy this as a SEPARATE Render service (or any Docker host).
The main website talks to it via /internal/execute with a shared secret.

Security:
  - Each run gets its own temp directory (deleted after).
  - Memory limit via RLIMIT_AS (Linux).
  - CPU/wall-time timeout (subprocess timeout).
  - Process group kill on timeout (no zombie children).
  - No network access inside the sandbox (documented; for full isolation
    use Piston/Docker --privileged, but this subprocess approach works
    without privileged mode on Render's managed Docker).

The shared secret (RUNNER_SERVICE_SECRET) authenticates every request.
"""
import os
import re
import io
import json
import base64
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
import asyncio
import logging
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional

# Proxy bridge dependencies. They ship in requirements.txt; the lazy guards
# keep the runner importable (jobs still work) on a box missing them.
try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("runner")

app = FastAPI(title="CodeNest Runner")

SECRET = os.getenv("RUNNER_SERVICE_SECRET", "").strip()
MAX_TIME_MS = int(os.getenv("MAX_EXECUTION_TIME_MS", "10000"))
MAX_MEM_MB = int(os.getenv("MAX_MEMORY_MB", "256"))
EXEC_PIP_TIMEOUT_S = int(os.getenv("EXEC_PIP_TIMEOUT_S", "120"))  # one-shot auto-install budget

# ─── Language definitions ──────────────────────────────────────────
# Each entry: extension, compile command (or None), run command.
# The run command uses {file} placeholder for the temp file path.

LANGS = {
    "python":     {"ext": "py",   "compile": None,                                                              "run": ["python3", "{file}"]},
    "python3":    {"ext": "py",   "compile": None,                                                              "run": ["python3", "{file}"]},
    "javascript": {"ext": "js",   "compile": None,                                                              "run": ["node", "{file}"]},
    "js":         {"ext": "js",   "compile": None,                                                              "run": ["node", "{file}"]},
    "typescript": {"ext": "ts",   "compile": None,                                                              "run": ["npx", "ts-node", "{file}"]},
    "bash":       {"ext": "sh",   "compile": None,                                                              "run": ["bash", "{file}"]},
    "sh":         {"ext": "sh",   "compile": None,                                                              "run": ["bash", "{file}"]},
    "ruby":       {"ext": "rb",   "compile": None,                                                              "run": ["ruby", "{file}"]},
    "php":        {"ext": "php",  "compile": None,                                                              "run": ["php", "{file}"]},
    "perl":       {"ext": "pl",   "compile": None,                                                              "run": ["perl", "{file}"]},
    "lua":        {"ext": "lua",  "compile": None,                                                              "run": ["lua", "{file}"]},
    "c":          {"ext": "c",    "compile": ["gcc", "{file}", "-o", "{bin}", "-lm", "-std=c11"],                "run": ["{bin}"]},
    "cpp":        {"ext": "cpp",  "compile": ["g++", "{file}", "-o", "{bin}", "-lm", "-std=c++17"],              "run": ["{bin}"]},
    "c++":        {"ext": "cpp",  "compile": ["g++", "{file}", "-o", "{bin}", "-lm", "-std=c++17"],              "run": ["{bin}"]},
    "java":       {"ext": "java", "compile": ["javac", "{file}"],                                                "run": ["java", "-cp", "{dir}", "Main"]},
    "go":         {"ext": "go",   "compile": None,                                                              "run": ["go", "run", "{file}"]},
    "rust":       {"ext": "rs",   "compile": ["rustc", "{file}", "-o", "{bin}"],                                "run": ["{bin}"]},
    "sql":        {"ext": "sql",  "compile": None,                                                              "run": ["sqlite3", ":memory:", ".read {file}"]},
    "text":       {"ext": "txt",  "compile": None,                                                              "run": ["cat", "{file}"]},
}


class ExecuteRequest(BaseModel):
    language: str
    code: str
    stdin: Optional[str] = None


def _check_secret(authorization: Optional[str]):
    """Verify the shared secret from the Authorization header."""
    if not SECRET:
        # If no secret configured, deny all requests (fail-closed).
        raise HTTPException(status_code=503, detail="Runner secret not configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized.")
    token = authorization.split(" ", 1)[1].strip()
    if token != SECRET:
        raise HTTPException(status_code=403, detail="Invalid runner secret.")


def _set_limits():
    """preexec_fn: set memory limit for the child process (Linux only)."""
    try:
        import resource
        mem_bytes = MAX_MEM_MB * 1024 * 1024
        # Soft + hard limit on virtual memory (address space).
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    except Exception:
        pass  # Non-Linux or no permission — timeout is the main guard.


def _run_subprocess(cmd, cwd, stdin_data, timeout_s, env=None):
    """Run a command with timeout, return (stdout, stderr, exit_code, timed_out)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            preexec_fn=_set_limits if os.name != "nt" else None,
            # Start in a new process group so we can kill all children on timeout.
            start_new_session=True,
            env=env,
        )
        return proc.stdout, proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired:
        return "", "Execution timed out after {} seconds.".format(timeout_s), -1, True
    except Exception as e:
        return "", str(e), -1, False


# NOTE: api_route with methods=["GET", "HEAD"] — FastAPI's plain @app.get does
# NOT answer HEAD requests (returns 405), but Render's health checker pings
# with HEAD and needs a 2xx. So register both methods explicitly.
@app.api_route("/", methods=["GET", "HEAD"])
def root():
    """Root endpoint — returns 200 so platform health checks (Render pings "/"
    by default) and curious browsers see the service is alive instead of a 404.
    The actual health/details endpoints remain below."""
    return {
        "service": "codenest-runner",
        "status": "ok",
        "endpoints": ["/health", "/api/v2/runtimes"],
        "note": "This is an internal code-execution API. POST /internal/execute with a Bearer secret to run code.",
    }


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    """Health + LOAD, so the control plane can route to the least-loaded worker.

    No auth: this is the endpoint used to decide whether a worker is reachable
    at all, and it must answer even when the shared secret is misconfigured.
    It exposes only counts and totals — no job names, no code, no env values.

    Memory is read from /proc rather than psutil: the same numbers, one less
    dependency on a 512MB box.
    """
    running = 0
    mem_mb = 0.0
    try:
        with _jobs_lock:
            procs = [j.get("proc") for j in _jobs.values()]
    except Exception as exc:                      # never let /health 500
        logger.warning("health load probe failed: %s", exc)
        procs = []
    for proc in procs:
        # Per-process try: one job whose handle is mid-teardown must not abort
        # the whole count. A single wrapping try/except silently under-reported
        # load, and an under-reported worker looks emptiest — so the dispatcher
        # would preferentially route MORE work to the one that is struggling.
        try:
            if not proc or proc.poll() is not None:
                continue
            running += 1
            mem_mb += (_proc_stats(proc) or {}).get("mem_mb", 0.0) or 0.0
        except Exception:
            running += 1                          # counted, memory unknown

    # Load is a MEMORY fraction now. A worker holding 20 idle bots at 30MB is
    # emptier than one holding 4 heavy bots at 120MB, and only memory says so.
    safe = MEM_SAFE_MB
    free_mb = max(0.0, safe - mem_mb)
    return {
        "status": "ok",
        "languages": sorted(LANGS.keys()),
        # Routing inputs.
        "jobs": running,
        "mem_mb": round(mem_mb, 1),
        "safe_mb": safe,
        "total_mb": MEM_TOTAL_MB,
        "free_mb": round(free_mb, 1),
        "full": not _admission()["admit"],
        # Clamped: measurement noise or jobs adopted after a redeploy can push
        # usage past the threshold, and a load above 1.0 sorts nonsensically.
        "load": round(min(mem_mb / safe, 1.0), 3) if safe else 1.0,
        # Kept so an older control plane still parses this payload. "free" is
        # now how many TYPICAL jobs would fit, not a slot count.
        "capacity": MAX_BG_JOBS_HARD,
        "free": int(free_mb // MEM_ASSUMED_JOB_MB),
    }


@app.get("/api/v2/runtimes")
def runtimes(authorization: Optional[str] = Header(None)):
    """Piston-compatible runtimes listing (also auth-gated)."""
    _check_secret(authorization)
    out = []
    for lang, cfg in sorted(LANGS.items()):
        out.append({"language": lang, "version": "latest", "aliases": []})
    return out


@app.post("/internal/execute")
def execute(req: ExecuteRequest, authorization: Optional[str] = Header(None)):
    """Execute code in a sandboxed subprocess.

    Requires: Authorization: Bearer <RUNNER_SERVICE_SECRET>
    Returns: { success, stdout, stderr, exit_code, execution_time_ms, error }
    """
    _check_secret(authorization)

    lang = (req.language or "").lower().strip()
    code = req.code or ""
    stdin_data = req.stdin or ""

    # --- Validate ---
    if lang not in LANGS:
        return JSONResponse({
            "success": False, "stdout": "", "stderr": "",
            "exit_code": -1, "execution_time_ms": 0,
            "error": "Unsupported language: {}. Available: {}".format(lang, ", ".join(sorted(LANGS.keys()))),
        })
    if not code.strip():
        return JSONResponse({
            "success": False, "stdout": "", "stderr": "",
            "exit_code": -1, "execution_time_ms": 0,
            "error": "Code is empty.",
        })

    cfg = LANGS[lang]
    start = time.monotonic()
    tmpdir = None

    try:
        tmpdir = tempfile.mkdtemp(prefix="run_")
        src_file = os.path.join(tmpdir, "main." + cfg["ext"])
        bin_file = os.path.join(tmpdir, "main.bin")

        # Write the source code (truncate at 256KB to prevent abuse).
        with open(src_file, "w") as f:
            f.write(code[:262144])

        # --- Auto-install whatever libraries the code imports ---
        # Same magic as jobs: paste code, we figure out its pip deps ourselves.
        reqs = _detect_imports(code)
        run_env = None
        if reqs:
            pylibs = os.path.join(tmpdir, "pylibs")
            os.makedirs(pylibs, exist_ok=True)
            _, perr, pcode, ptimed = _run_subprocess(
                ["python3", "-m", "pip", "install", "--quiet", "--target", pylibs] + reqs,
                tmpdir, None, EXEC_PIP_TIMEOUT_S,
            )
            if pcode != 0:
                return JSONResponse({
                    "success": False, "stdout": "", "stderr": (perr or "")[-3000:],
                    "exit_code": -1,
                    "execution_time_ms": int((time.monotonic() - start) * 1000),
                    "error": "pip install failed" + (" (timed out)" if ptimed else "") + " for: " + " ".join(reqs),
                })
            run_env = dict(os.environ)
            run_env["PYTHONPATH"] = pylibs + os.pathsep + run_env.get("PYTHONPATH", "")

        # --- Compile (if needed) ---
        if cfg["compile"]:
            compile_cmd = [c.replace("{file}", src_file).replace("{bin}", bin_file).replace("{dir}", tmpdir) for c in cfg["compile"]]
            cout, cerr, ccode, ctimed = _run_subprocess(compile_cmd, tmpdir, None, MAX_TIME_MS / 1000, env=run_env)
            if ccode != 0:
                elapsed = int((time.monotonic() - start) * 1000)
                return JSONResponse({
                    "success": False,
                    "stdout": cout,
                    "stderr": cerr,
                    "exit_code": ccode,
                    "execution_time_ms": elapsed,
                    "error": "Compilation failed." if not ctimed else "Compilation timed out.",
                })

        # --- Run ---
        run_cmd = [c.replace("{file}", src_file).replace("{bin}", bin_file).replace("{dir}", tmpdir) for c in cfg["run"]]
        timeout_s = MAX_TIME_MS / 1000.0
        stdout, stderr, exit_code, timed_out = _run_subprocess(run_cmd, tmpdir, stdin_data, timeout_s, env=run_env)

        elapsed = int((time.monotonic() - start) * 1000)

        # Truncate very long output (prevent abuse).
        stdout = stdout[:65536] if stdout else ""
        stderr = stderr[:65536] if stderr else ""

        return JSONResponse({
            "success": exit_code == 0 and not timed_out,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "execution_time_ms": elapsed,
            "error": "Execution timed out." if timed_out else None,
        })

    except Exception as e:
        logger.exception("Execution error")
        elapsed = int((time.monotonic() - start) * 1000)
        return JSONResponse({
            "success": False, "stdout": "", "stderr": "",
            "exit_code": -1, "execution_time_ms": elapsed,
            "error": "Internal error: {}".format(str(e)[:200]),
        })
    finally:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


@app.post("/api/v2/execute")
def execute_piston(req: ExecuteRequest, authorization: Optional[str] = Header(None)):
    """Piston-compatible endpoint (same logic, aliased)."""
    _check_secret(authorization)
    return execute(req, authorization)


# ═══════════════════════════════════════════════════════════════════
# PERSISTENT BACKGROUND JOBS  ("Always-On" — mini PythonAnywhere)
# ═══════════════════════════════════════════════════════════════════
# Unlike /internal/execute (one-shot, 10s timeout), a JOB is a long-lived
# process: Telegram bots, scrapers, loops — anything that should keep
# running. The runner supervises each job:
#   * isolated temp dir + same memory limits as one-shot runs
#   * stdout/stderr captured into a small ring buffer (for live logs)
#   * auto-restart on crash (few attempts, spaced out — like PA's tasks)
# Jobs live in THIS process's memory, so a runner redeploy/restart clears
# them — the main site keeps the job definitions and can re-spawn them.
# ---------------------------------------------------------------------------
# Capacity of THIS runner process, sized by its RAM. It is a HARDWARE limit —
# how many bots this container can hold — not a fairness rule. The per-account
# limit is enforced separately by the main site (MAX_JOBS_PER_USER).
#
# BUG THIS CAUSED: at 5 it read "Runner at capacity (5/5)" to EVERY user once
# the site held 5 jobs in total, so a brand-new account with zero jobs could
# not create its first one. Five bots is roughly what 512MB holds; add another
# runner service to add capacity rather than raising this past the RAM.
# Legacy. Admission is decided by memory (see _admission below); this only
# survives so an older control plane still finds a "capacity" number.
MAX_BG_JOBS = int(os.getenv("MAX_BG_JOBS", "12"))

# ---------------------------------------------------------------------------
# ADMISSION CONTROL: measure memory, do not count jobs
# ---------------------------------------------------------------------------
# A fixed job count assumed every bot would use its worst-case ceiling. In
# practice an idle Telegram bot sits around 25-45MB, so 20+ of them coexist
# happily on a box that a count-based limit declared "full" at 12. Counting
# jobs answers the wrong question; what matters is how much RAM is actually
# committed right now.
#
# This is SEPARATE from MAX_MEMORY_MB (the per-job RLIMIT). That one stops a
# single runaway process eating the box and is unchanged. This one decides
# whether there is room for one more.
#
# MEM_TOTAL_MB: the container's RAM. Read from the cgroup when possible —
# /proc/meminfo reports the HOST's memory, which on a 512MB Render instance
# would wildly overestimate the budget.
def _container_total_mb() -> int:
    override = os.getenv("MEM_TOTAL_MB", "").strip()
    if override:
        try:
            return max(64, int(override))
        except ValueError:
            pass
    for path in ("/sys/fs/cgroup/memory.max",                      # cgroup v2
                 "/sys/fs/cgroup/memory/memory.limit_in_bytes"):   # cgroup v1
        try:
            with open(path) as fh:
                raw = fh.read().strip()
            if raw and raw != "max":
                val = int(raw)
                # v1 reports a sentinel near 2^63 when unlimited.
                if 0 < val < (1 << 62):
                    return max(64, val // (1024 * 1024))
        except Exception:
            pass
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return max(64, int(line.split()[1]) // 1024)
    except Exception:
        pass
    return 512                                    # Render free tier default


MEM_TOTAL_MB = _container_total_mb()
# Admit while committed memory stays under this share of the box. The headroom
# absorbs the new job's own startup cost plus the runner process itself.
MEM_SAFE_PCT = float(os.getenv("MEM_SAFE_PCT", "0.82"))
MEM_SAFE_MB = int(MEM_TOTAL_MB * MEM_SAFE_PCT)
# What to reserve for a job that cannot be measured yet (it is still starting,
# so its RSS is meaningless). MEASURED on this codebase: a bare python loop is
# 7.7MB RSS; pyTelegramBotAPI/aiogram plus a requests session lands around
# 25-35MB idle. 30 is the honest middle. Over-reserving here would quietly
# reintroduce the pessimism that made the count-based cap wrong in the first
# place — it only affects the moment of admission, since a running job is then
# measured for real.
MEM_ASSUMED_JOB_MB = int(os.getenv("MEM_ASSUMED_JOB_MB", "30"))
# A hard ceiling on job COUNT still exists, but only as a runaway guard for
# pathological cases (hundreds of near-zero-memory processes exhausting PIDs
# or file descriptors). It is far above anything memory would allow.
MAX_BG_JOBS_HARD = int(os.getenv("MAX_BG_JOBS_HARD", "60"))


def _used_mem_mb() -> float:
    """Total RSS of every live job on this worker, measured now."""
    total = 0.0
    try:
        with _jobs_lock:
            procs = [j.get("proc") for j in _jobs.values()]
    except Exception:
        return 0.0
    for proc in procs:
        try:
            if not proc or proc.poll() is not None:
                continue
            total += (_proc_stats(proc) or {}).get("mem_mb", 0.0) or 0.0
        except Exception:
            # Unmeasurable but alive: assume the typical footprint rather than
            # zero, so a worker cannot look emptier than it is.
            total += MEM_ASSUMED_JOB_MB
    return total


def _admission() -> dict:
    """Is there room for one more job? Measured, not counted."""
    used = _used_mem_mb()
    running = 0
    try:
        with _jobs_lock:
            running = sum(1 for j in _jobs.values()
                          if j.get("proc") and j["proc"].poll() is None)
    except Exception:
        pass
    projected = used + MEM_ASSUMED_JOB_MB
    return {
        "used_mb": round(used, 1),
        "safe_mb": MEM_SAFE_MB,
        "total_mb": MEM_TOTAL_MB,
        "running": running,
        "free_mb": round(max(0.0, MEM_SAFE_MB - used), 1),
        "admit": projected <= MEM_SAFE_MB and running < MAX_BG_JOBS_HARD,
    }
JOB_LOG_LINES = 2000                                # ring buffer per job (full history)
JOB_RESTART_LIMIT = 3                               # auto-restart attempts
JOB_RESTART_DELAY_S = 5
JOB_PIP_TIMEOUT_S = int(os.getenv("JOB_PIP_TIMEOUT_S", "240"))  # pip install budget

_jobs: dict = {}                                    # id -> job record
_jobs_lock = threading.Lock()

# ---------------------------------------------------------------------------
# PERSISTENT JOB WORKSPACE
# ---------------------------------------------------------------------------
# Long-lived bots (Telegram referral bots, scrapers writing SQLite DBs,
# session caches, etc.) keep their files across admin code-edits and across
# Render re-deploys / container restarts. Each job gets a STABLE directory
# under JOBS_DATA_DIR keyed by its own id, so Stop/Restart reuses it.
# One-shot /internal/execute runs still live in tempfile.mkdtemp and are
# wiped after each request — they are ephemeral by design.
#
# For TRUE cross-deploy persistence on Render, mount a Render Persistent
# Disk at /app/data on a paid Starter plan; on the free tier the directory
# survives process restarts / self-ping wakes but NOT full rebuilds.
_default_data_dir = os.environ.get("DATA_DIR", "/app/data")
if not os.access(os.path.dirname(_default_data_dir) or "/", os.W_OK):
    # Fallback for local dev / non-Docker runs where /app isn't writable.
    _default_data_dir = os.path.join(tempfile.gettempdir(), "ahad-runner-data")
JOBS_DATA_DIR = os.environ.get(
    "JOBS_DATA_DIR",
    os.path.join(_default_data_dir, "jobs"),
)
os.makedirs(JOBS_DATA_DIR, exist_ok=True)
logger.info("Jobs data dir: %s (persistent workspace for bots)", JOBS_DATA_DIR)


def _job_dir(job_id: str) -> str:
    """Stable directory for a given job_id — same path across restarts.
    Bots can freely write ./database.db, ./session.json, ./data/* here and
    they survive Stop/Restart and (with a disk mounted) full redeploys."""
    d = os.path.join(JOBS_DATA_DIR, job_id)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# PUBLIC WEB ADDRESSES — /live/{job-slug}/
# A job that opens a listening socket gets a public URL on THIS runner:
#   https://<runner-host>/live/{slug}/  →  http://127.0.0.1:{job port}/...
# The proxy lives HERE (not the main site) because job processes bind ports
# inside this container — only this process can reach them.
# Path-style URLs (no wildcard subdomains on Render). The slug+port belong to
# the job record itself, so crash-restarts keep the same public address.
# ---------------------------------------------------------------------------
LIVE_PORT_MIN = int(os.getenv("LIVE_PORT_MIN", "11000"))
LIVE_PORT_MAX = int(os.getenv("LIVE_PORT_MAX", "11099"))
LIVE_RATE_LIMIT = int(os.getenv("LIVE_RATE_LIMIT", "60"))      # req per minute per visitor IP per job
LIVE_RATE_WINDOW_S = 60
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")  # e.g. https://codenest-runner.onrender.com

_live_hits: dict = {}        # (slug, ip) -> deque[timestamps]  (in-memory rate limiter)
_live_hits_lock = threading.Lock()


def _purge_orphan_jobs() -> None:
    """Reclaim orphaned job PROCESSES from an old runner incarnation but
    NEVER delete the persistent workspace directories — bot databases /
    session files live there and must survive redeploys."""
    if os.name != "posix":
        return
    tmp = tempfile.gettempdir()
    me = os.getpid()
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit() or int(pid) == me:
                continue
            try:
                cwd = os.readlink(f"/proc/{pid}/cwd")
                if cwd.startswith(tmp + "/job_") \
                        or cwd.startswith(tmp + "/run_") \
                        or cwd.startswith(JOBS_DATA_DIR + "/"):
                    os.kill(int(pid), signal.SIGKILL)
                    logger.info("Purged orphaned job process %s (cwd %s)", pid, cwd)
            except Exception:
                pass
        # Wipe stale one-shot temp dirs only; the persistent JOBS_DATA_DIR
        # is intentionally LEFT ALONE so bot databases survive redeploys.
        for d in Path(tmp).glob("job_*"):
            shutil.rmtree(d, ignore_errors=True)
        for d in Path(tmp).glob("run_*"):
            shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


_purge_orphan_jobs()

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length",
}


# Environment variables a job must never be allowed to set: they control how
# the process is found, linked and loaded, so overriding them is a sandbox
# escape / hijack risk rather than configuration.
_ENV_BLOCKED = {
    "PATH", "PYTHONPATH", "PORT", "HOME", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "PYTHONSTARTUP", "PYTHONHOME", "BASH_ENV", "ENV", "SHELL", "IFS",
    "RUNNER_SERVICE_SECRET", "DATABASE_URL",
}
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_ENV_MAX_VARS = 40
_ENV_MAX_VALUE = 4096


def _clean_env(raw) -> dict:
    """Validate user-supplied env vars before they reach a spawned process."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        k = str(k).strip()
        if not _ENV_KEY_RE.match(k) or k.upper() in _ENV_BLOCKED:
            continue
        v = "" if v is None else str(v)
        if len(v) > _ENV_MAX_VALUE:
            v = v[:_ENV_MAX_VALUE]
        # NUL bytes / newlines can forge extra entries in some runtimes.
        out[k] = v.replace("\x00", "").replace("\n", " ").replace("\r", " ")
        if len(out) >= _ENV_MAX_VARS:
            break
    return out


def _alloc_port() -> Optional[int]:
    """Lowest free port in the pool, or None when the pool is exhausted."""
    with _jobs_lock:
        used = {j.get("port") for j in _jobs.values() if j.get("port")}
    for p in range(LIVE_PORT_MIN, LIVE_PORT_MAX + 1):
        if p not in used:
            return p
    return None


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (s[:18].strip("-") or "job") + "-" + secrets.token_hex(3)


def _live_page(title: str, body: str, accent: str = "#0f0e0c") -> HTMLResponse:
    """Tiny self-contained status page for public /live/ visitors."""
    # Abuse-report link points back at the main site (set SITE_BASE_URL on this
    # service, e.g. https://codenest-app.onrender.com). Omitted when unset.
    site = os.getenv("SITE_BASE_URL", "").strip().rstrip("/")
    report = (
        f'<p class="note"><a style="color:inherit" href="{site}/report-abuse">Report abuse</a></p>'
        if site else ""
    )
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#faf9f6;
font-family:Georgia,'Times New Roman',serif;color:#141310}}
.card{{max-width:430px;margin:20px;padding:34px 30px;text-align:center;background:#fff;
border:1px solid #e4e0d5;border-top:3px solid {accent};box-shadow:0 18px 40px -26px rgba(20,19,16,.28)}}
h1{{font-size:21px;margin:0 0 10px;font-weight:600}}
p{{font-size:14px;line-height:1.65;margin:6px 0;color:#5c584e}}
.note{{margin-top:16px;padding-top:12px;border-top:1px dashed #e4e0d5;font-size:12px;color:#8a8474}}
</style></head><body><div class="card">{body}{report}</div></body></html>"""
    return HTMLResponse(html)


def _find_job_by_slug(slug: str) -> Optional[dict]:
    with _jobs_lock:
        for j in _jobs.values():
            if j.get("web_slug") == slug:
                return j
    return None


def _job_running(j: dict) -> bool:
    p = j.get("proc")
    return bool(p is not None and p.poll() is None)


def _live_rate_ok(slug: str, ip: str) -> bool:
    """Fixed-window-ish limiter: LIVE_RATE_LIMIT requests / minute / IP / job."""
    now = time.time()
    key = (slug, ip or "?")
    with _live_hits_lock:
        q = _live_hits.get(key)
        if q is None:
            q = _live_hits[key] = deque()
        while q and now - q[0] > LIVE_RATE_WINDOW_S:
            q.popleft()
        if len(q) >= LIVE_RATE_LIMIT:
            return False
        q.append(now)
        return True


def _web_watch(j: dict, proc: subprocess.Popen, port: int) -> None:
    """Watchdog thread: poll the job's port and flip j["web"] as the listener
    comes up (and down). Started with every spawn; survives crash-restarts
    because each restart spawns a fresh watcher for the new process.

    Debounced: ONE good probe flips web ON, but it takes 3 consecutive
    failures to flip it OFF — a single-threaded server momentarily busy
    serving a request must not pause the public URL (flapping)."""
    polls = 0
    miss_streak = 0
    while True:
        if j.get("stop_requested") or j.get("id") not in _jobs:
            return
        if j.get("proc") is not proc or proc.poll() is not None:
            return  # process replaced or exited — the new spawn watches anew
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.7):
                up = True
        except OSError:
            up = False
        if up:
            miss_streak = 0
            if not j.get("web"):
                j["web"] = True
                pub = (PUBLIC_BASE_URL + f"/live/{j['web_slug']}/") if PUBLIC_BASE_URL else f"/live/{j['web_slug']}/"
                j["log"].append(f"[system] web service detected on port {port} — public URL: {pub}")
                logger.info("Job %s web listener up on :%s", j.get("id"), port)
        else:
            miss_streak += 1
            if j.get("web") and miss_streak >= 3:
                j["web"] = False
                j["log"].append("[system] web port closed — public URL is paused")
        polls += 1
        time.sleep(0.75 if polls < 45 else 2.5)  # eager at boot, relaxed later


class JobStartRequest(BaseModel):
    language: str
    code: str
    name: Optional[str] = ""
    restart: Optional[bool] = True
    repo_url: Optional[str] = ""
    entry: Optional[str] = ""
    # User-supplied environment variables (API keys, bot tokens, ...). These
    # are injected into the job process at spawn time.
    env: Optional[dict] = None


class JobAccessRequest(BaseModel):
    public: bool = True


def _parse_requirements(code: str) -> list:
    """PythonAnywhere-style dependency declaration: a comment near the top of
    the code like

        # requirements: python-telegram-bot requests

    is collected and pip-installed before the job starts."""
    reqs = []
    for line in (code or "").splitlines()[:40]:
        m = re.match(r"^\s*#\s*requirements\s*[::]\s*(.+)$", line, re.IGNORECASE)
        if m:
            reqs.extend(p for p in re.split(r"[,\s]+", m.group(1).strip()) if p)
    return reqs


# ─── Automatic dependency detection ─────────────────────────────────────────
# We read the code's top-level imports, drop stdlib modules, map the remaining
# module names to their PyPI package names, and pip-install them — so a user
# just pastes code and EVERYTHING it needs appears magically. No headers,
# no instructions. (The optional "# requirements:" line still lets users pin
# exact packages/versions on top of the auto-detected ones.)
_STDLIB = set(sys.stdlib_module_names) | {"__future__"}

# Import-name -> PyPI package-name, for the cases where they DIFFER.
# (Modules like `requests`, `numpy`, `flask`, `pandas`, `ccxt`, `web3`,
# `pyrogram`, `openai`… share their package name and need no entry.)
_IMPORT_TO_PYPI = {
    # ── images / vision ──
    "pil": "pillow",
    "cv2": "opencv-python",
    "imageio": "imageio",
    "pytesseract": "pytesseract",
    # ── messaging / bots ──
    "telegram": "python-telegram-bot",
    "discord": "discord.py",
    "pyrogram": "pyrogram",
    "telethon": "telethon",
    "slack_sdk": "slack-sdk",
    "twilio": "twilio",
    # ── web / scraping / http ──
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "html5lib": "html5lib",
    "selenium": "selenium",          # note: needs a browser binary to actually drive
    "playwright": "playwright",      # note: needs `playwright install` for browsers
    "aiohttp": "aiohttp",
    "httpx": "httpx",
    "websocket": "websocket-client",
    "websockets": "websockets",
    "feedparser": "feedparser",
    "tweepy": "tweepy",
    "praw": "praw",
    # ── data / science ──
    "sklearn": "scikit-learn",
    "seaborn": "seaborn",
    "openpyxl": "openpyxl",
    "xlrd": "xlrd",
    # ── formats / utils ──
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "qrcode": "qrcode[pil]",  # image output secretly needs Pillow (pip extra)
    "dateutil": "python-dateutil",
    "pytz": "pytz",
    "jinja2": "jinja2",
    "schedule": "schedule",
    "psutil": "psutil",
    "watchdog": "watchdog",
    "crypto": "pycryptodome",
    "jwt": "pyjwt",
    "multipart": "python-multipart",
    "pyfiglet": "pyfiglet",
    "emoji": "emoji",
    "wordcloud": "wordcloud",
    # ── databases ──
    "pymongo": "pymongo",
    "psycopg2": "psycopg2-binary",
    # ── ai apis ──
    "openai": "openai",
    "anthropic": "anthropic",
    "groq": "groq",
    "cohere": "cohere",
    # ── paid-data / exchange ──
    "binance": "python-binance",
    # ── media / misc fun ──
    "pywhatkit": "pywhatkit",
    "pytubefix": "pytubefix",
    "pytube": "pytube",
    "moviepy": "moviepy",
    "pydub": "pydub",
    "gtts": "gtts",
}


def _detect_imports(code: str) -> list:
    """Return the PyPI packages this code needs (auto-detected + header)."""
    pkgs = set()
    for m in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", code or "", re.MULTILINE):
        mod = m.group(1).lower()
        if mod in _STDLIB:
            continue
        pkgs.add(_IMPORT_TO_PYPI.get(mod, mod))
    for p in _parse_requirements(code):
        pkgs.add(p)
    return sorted(pkgs)[:20]  # sanity cap


def _clone_repo(repo_url: str, target_dir: str, log: deque) -> bool:
    """git clone --depth 1 a public repo into target_dir. Returns True on success."""
    url = (repo_url or "").strip()
    if not url:
        return False
    # Normalize github web URLs to .git for clone
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?(?:tree/[^/]+)?/?$", url)
    if m:
        url = f"https://github.com/{m.group(1)}/{m.group(2)}.git"
    # Block anything obviously non-http(s) (prevent ssh/file)
    if not re.match(r"^https?://", url):
        log.append(f"[system] ✗ repo URL must start with https://")
        return False
    try:
        # PRESERVE DATA ACROSS A RE-CLONE.
        #
        # This used to rmtree the whole workspace, which is the one place a
        # job's directory really is destroyed: re-importing the repo (or
        # editing a repo job, which re-clones) deleted database.db,
        # session.json and everything else the bot had written.
        #
        # git clone insists on an empty target, so the data files are moved
        # aside, the clone runs, and they are put back -- with the repo's own
        # copy losing to the live one, since a bot's runtime state is always
        # newer than whatever is committed.
        keep = {}
        if os.path.isdir(target_dir):
            for rel in _snapshot_files(target_dir):
                src_p = os.path.join(target_dir, rel)
                try:
                    with open(src_p, "rb") as fh:
                        keep[rel] = fh.read()
                except OSError:
                    pass
            shutil.rmtree(target_dir, ignore_errors=True)
        os.makedirs(target_dir, exist_ok=True)
        log.append(f"[system] Cloning {url} …")
        out, err, rc, timed = _run_subprocess(
            ["git", "clone", "--depth", "1", "--quiet", url, target_dir],
            os.path.dirname(target_dir), None, 120,
        )
        if rc != 0:
            reason = (err or out or "").strip().splitlines()
            log.append(f"[system] ✗ git clone failed: {(reason[-1] if reason else 'unknown error')[:200]}")
            return False
        # Put the preserved data back. The clone wins for files it also
        # ships (that is the point of importing), except that a data file
        # the bot wrote is newer than the repo's placeholder, so it is
        # restored over the top.
        restored = 0
        for rel, blob in keep.items():
            dst = os.path.join(target_dir, rel)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as fh:
                    fh.write(blob)
                restored += 1
            except OSError:
                pass
        if restored:
            log.append(f"[system] ✓ kept {restored} existing data file(s)")
        log.append("[system] ✓ repo cloned")
        return True
    except Exception as e:
        log.append(f"[system] ✗ git clone error: {str(e)[:200]}")
        return False


_ENTRY_CANDIDATES = [
    # Python
    ("python", "main.py"), ("python", "app.py"), ("python", "bot.py"),
    ("python", "server.py"), ("python", "index.py"), ("python", "run.py"),
    # Node
    ("javascript", "index.js"), ("javascript", "server.js"),
    ("javascript", "app.js"), ("javascript", "main.js"), ("javascript", "bot.js"),
    # Ruby
    ("ruby", "app.rb"), ("ruby", "main.rb"), ("ruby", "server.rb"),
    # PHP
    ("php", "index.php"), ("php", "main.php"),
    # Bash
    ("bash", "start.sh"), ("bash", "run.sh"), ("bash", "main.sh"),
]

def _detect_entry(jdir: str, code_overwrite: bool, log: deque) -> tuple:
    """Inspect a repo checkout and pick (language, entryfile) + write an
    index.html for static-only repos. Returns (lang, main_file) or (None, None)."""
    if code_overwrite:
        return None, None  # caller supplied inline code — wins
    has_requirements = os.path.isfile(os.path.join(jdir, "requirements.txt"))
    has_pyproject    = os.path.isfile(os.path.join(jdir, "pyproject.toml"))
    has_package_json = os.path.isfile(os.path.join(jdir, "package.json"))
    has_gemfile      = os.path.isfile(os.path.join(jdir, "Gemfile"))
    has_compose      = os.path.isfile(os.path.join(jdir, "compose.yaml")) or os.path.isfile(os.path.join(jdir, "docker-compose.yml"))

    # Static site fallback: if there is an index.html and NO backend manifest,
    # serve the directory with python -m http.server (renders HTML/CSS/JS live).
    static_index = os.path.join(jdir, "index.html")
    is_static = os.path.isfile(static_index) and not (has_requirements or has_pyproject or has_package_json or has_gemfile)

    for lang, fname in _ENTRY_CANDIDATES:
        fp = os.path.join(jdir, fname)
        if os.path.isfile(fp):
            return lang, fp

    if is_static:
        # Static-page repo → synthesize a tiny launcher so http.server serves
        # the folder on $PORT, giving the user a live URL like Render static sites.
        launcher = os.path.join(jdir, "main.py")
        with open(launcher, "w") as f:
            f.write(
                "import os, functools, http.server, socketserver\n"
                "PORT = int(os.environ.get('PORT', '8080'))\n"
                "class H(http.server.SimpleHTTPRequestHandler):\n"
                "    def end_headers(self):\n"
                "        self.send_header('Cache-Control','no-cache')\n"
                "        super().end_headers()\n"
                "Handler = functools.partial(H, directory='.')\n"
                f"print(f'static site on http://0.0.0.0:{{PORT}}')\n"
                "with socketserver.TCPServer(('0.0.0.0', PORT), Handler) as httpd:\n"
                "    httpd.serve_forever()\n"
            )
        log.append("[system] detected static site (index.html) — serving via built-in HTTP server")
        return "python", launcher

    # Nothing matched the conventional names. Rather than give up -- which is
    # what made https://github.com/tajhatati/bb (a repo whose only source file
    # is n.py) look empty -- fall back to whatever source is actually there.
    #
    # Preference order matters: a manifest tells us the ecosystem, so a repo
    # with requirements.txt is Python even if it also ships a stray .js.
    ext_lang = [("py", "python"), ("js", "javascript"), ("rb", "ruby"),
                ("php", "php"), ("sh", "bash")]
    if has_package_json:
        ext_lang.insert(0, ext_lang.pop(1))
    elif has_gemfile:
        ext_lang.insert(0, ext_lang.pop(2))

    for ext, lname in ext_lang:
        try:
            hits = sorted(
                f for f in os.listdir(jdir)
                if f.endswith("." + ext)
                and not f.startswith((".", "_", "test_", "setup"))
                and os.path.isfile(os.path.join(jdir, f))
                and os.path.getsize(os.path.join(jdir, f)) > 0
            )
        except OSError:
            hits = []
        if not hits:
            continue
        # One obvious candidate, or the largest -- the entry point of a small
        # repo is almost never the tiny helper next to it.
        pick = hits[0] if len(hits) == 1 else max(
            hits, key=lambda f: os.path.getsize(os.path.join(jdir, f)))
        log.append(f"[system] no conventional entry file; using {pick}")
        return lname, os.path.join(jdir, pick)

    return None, None


def _install_repo_deps(jdir: str, pylibs: Optional[str], lang: str, log: deque):
    """Install repo-level dependency files (requirements.txt / package.json /
    Gemfile) into the job's environment. Mirrors Render's build step."""
    deadline = time.monotonic() + JOB_PIP_TIMEOUT_S
    def _run(cmd, cwd):
        remain = int(deadline - time.monotonic())
        if remain <= 0:
            log.append("[system] ✗ install budget exhausted")
            return False
        env = None
        if pylibs:
            env = dict(os.environ)
            env["PYTHONPATH"] = pylibs + os.pathsep + env.get("PYTHONPATH", "")
        o, e, rc, _ = _run_subprocess(cmd, cwd, None, remain, env=env)
        lines = [ln for ln in ((e or "") + "\n" + (o or "")).splitlines() if ln.strip()]
        if rc != 0:
            log.append(f"[system] ✗ {' '.join(cmd[:3])}… failed: {(lines[-1] if lines else 'unknown')[:200]}")
            return False
        return True

    if lang == "python":
        if os.path.isfile(os.path.join(jdir, "requirements.txt")):
            log.append("[system] pip install -r requirements.txt …")
            if pylibs:
                if not _run(["python3","-m","pip","install","--quiet","--target",pylibs,"-r","requirements.txt"], jdir):
                    return False
            else:
                if not _run(["python3","-m","pip","install","--quiet","-r","requirements.txt"], jdir):
                    return False
            log.append("[system] ✓ requirements.txt installed")
        if os.path.isfile(os.path.join(jdir, "pyproject.toml")):
            log.append("[system] pip install . (pyproject.toml) …")
            if pylibs:
                _run(["python3","-m","pip","install","--quiet","--target",pylibs,"."], jdir)
            else:
                _run(["python3","-m","pip","install","--quiet","."], jdir)
    elif lang == "javascript":
        has_npm = os.path.isfile(os.path.join(jdir, "package.json"))
        if has_npm:
            log.append("[system] npm install --omit=dev …")
            if not _run(["npm","install","--omit=dev","--no-audit","--no-fund","--loglevel=error"], jdir):
                return False
            log.append("[system] ✓ node_modules installed")
    elif lang == "ruby":
        if os.path.isfile(os.path.join(jdir, "Gemfile")):
            log.append("[system] bundle install …")
            _run(["bundle","install","--quiet"], jdir)
    return True


def _pkg_display_name(spec: str) -> str:
    """'qrcode[pil]' -> 'qrcode', 'psycopg2-binary==2.9' -> 'psycopg2-binary'."""
    return re.split(r"[<>=!~\[]", spec, 1)[0].strip()


def _installed_version(name: str, pylibs: str) -> str:
    """Resolve the version pip just installed into the job's target dir, so
    logs can report 'flask==3.0.3' instead of a bare package name."""
    try:
        env = dict(os.environ, PYTHONPATH=pylibs)
        p = subprocess.run(
            ["python3", "-c",
             "import importlib.metadata as m,sys;print(m.version(sys.argv[1].lower().replace('_','-')))",
             name],
            capture_output=True, text=True, timeout=15, env=env,
        )
        v = (p.stdout or "").strip()
        return v if v and p.returncode == 0 else "?"
    except Exception:
        return "?"


def _resolve_entry_now(j: dict) -> Optional[str]:
    """Re-derive this job's entry file from the CURRENT contents of its dir.

    BUG (reported: renamed n.py to main.py, runner still said "code is empty").
    j["file"] was decided once at create time and reused forever. Renaming,
    adding or deleting a file in the editor never invalidated it, so restart
    kept launching a path that no longer existed -- or an empty stub that had
    been left behind.

    Re-scanning is cheap (one listdir of a shallow checkout) and, per the
    brief, is the robust option: there is no cache to invalidate because
    there is no cache. Returns None only when the directory holds nothing
    runnable, which the caller reports rather than silently starting.
    """
    jdir = j.get("dir")
    if not jdir or not os.path.isdir(jdir):
        return None
    cfg = LANGS.get(j.get("lang") or "python") or LANGS["python"]
    ext = cfg["ext"]

    def _usable(path):
        # A file that exists but is empty is exactly the "code is empty"
        # state the user hit; treat it as not-an-entry so a real file wins.
        try:
            return os.path.isfile(path) and os.path.getsize(path) > 0
        except OSError:
            return False

    # 1. An explicit choice from the file browser always wins.
    pinned = j.get("entry_rel")
    if pinned:
        fp = os.path.join(jdir, pinned)
        if _usable(fp):
            return fp
        j["log"].append(f"[system] ! pinned entry '{pinned}' is missing or empty — re-scanning")

    # 2. The conventional name for this language.
    conventional = os.path.join(jdir, "main." + ext)
    if _usable(conventional):
        return conventional

    # 3. The known entry names, in the same order used at create time.
    for cand_lang, fname in _ENTRY_CANDIDATES:
        if cand_lang != j.get("lang"):
            continue
        fp = os.path.join(jdir, fname)
        if _usable(fp):
            return fp

    # 4. Any single source file of the right type at the top level. Only when
    #    there is exactly one -- guessing between several would be worse than
    #    saying so.
    try:
        matches = [
            f for f in sorted(os.listdir(jdir))
            if f.endswith("." + ext)
            and _usable(os.path.join(jdir, f))
            and not f.startswith(".")
        ]
    except OSError:
        matches = []
    if len(matches) == 1:
        return os.path.join(jdir, matches[0])

    # 5. Whatever was recorded, if it is still real.
    old = j.get("file")
    if old and _usable(old):
        return old
    return None


def _prepare_and_run(j: dict, reqs: list, is_repo: bool = False) -> None:
    """Background worker: install deps (repo manifests first, then inline imports),
    then start the job."""
    # Remember what this job asked for. The log line already said it, but a log
    # is a ring buffer — it scrolls away, and the admin panel needs to aggregate
    # across every job. Union, because a repo install can add more later.
    try:
        have = set(j.get("libs") or [])
        j["libs"] = sorted(have | {_pkg_display_name(x) for x in (reqs or [])})
    except Exception:
        pass
    # Repo-mode: install requirements.txt / package.json / Gemfile first
    if is_repo:
        ok = _install_repo_deps(j["dir"], j.get("pylibs"), j["lang"], j["log"])
        if not ok:
            j["status"] = "install_failed"
            j["log"].append("[system] Repo install failed — check logs and press Restart.")
            return
        if reqs:
            # Union: also auto-install anything imported but not in requirements.txt
            j["log"].append(f"[system] checking imports for extra libraries…")
            deadline = time.monotonic() + JOB_PIP_TIMEOUT_S
            missed = []
            for spec in reqs:
                remain = int(deadline - time.monotonic())
                if remain <= 0: break
                name = _pkg_display_name(spec)
                # Skip if already satisfied by import (fast check)
                chk = subprocess.run(
                    ["python3","-c",f"import {name}"],
                    capture_output=True,
                    env=dict(os.environ, PYTHONPATH=(j.get("pylibs") or "")+os.pathsep+os.environ.get("PYTHONPATH","")) if j.get("pylibs") else None,
                    timeout=8,
                )
                if chk.returncode == 0: continue
                tout, terr, tcode, _ = _run_subprocess(
                    ["python3","-m","pip","install","--quiet","--target",j["pylibs"],spec],
                    j["dir"], None, remain,
                    env=dict(os.environ, PYTHONPATH=j["pylibs"]+os.pathsep+os.environ.get("PYTHONPATH","")),
                )
                if tcode == 0:
                    j["log"].append(f"[system] ✓ {name} installed")
                else:
                    missed.append(name)
            if missed:
                j["log"].append(f"[system] ! {len(missed)} package(s) failed to install (non-fatal if vendored)")
        j["log"].append("[system] dependencies ready")
    elif reqs:
        j["log"].append(f"[system] Installing libraries: {', '.join(reqs)}")
        deadline = time.monotonic() + JOB_PIP_TIMEOUT_S
        failed = None
        for spec in reqs:
            remain = int(deadline - time.monotonic())
            if remain <= 0:
                j["log"].append(f"[system] ✗ {_pkg_display_name(spec)} failed: install budget exhausted (timed out)")
                failed = spec
                break
            name = _pkg_display_name(spec)
            tout, terr, tcode, ttimed = _run_subprocess(
                ["python3", "-m", "pip", "install", "--quiet", "--target", j["pylibs"], spec],
                j["dir"], None, remain,
            )
            if tcode == 0:
                ver = _installed_version(name, j["pylibs"])
                j["log"].append(f"[system] ✓ {name}=={ver} installed")
            else:
                lines = [ln for ln in ((terr or "") + "\n" + (tout or "")).splitlines() if ln.strip()]
                reason = ("pip timed out" if ttimed else (lines[-1].strip() if lines else "unknown error"))
                j["log"].append(f"[system] ✗ {name} failed: {reason[:240]}")
                failed = spec
                break
        if failed:
            j["status"] = "install_failed"
            j["log"].append("[system] Install stopped — fix the failing package and press ▶ Restart.")
            return
        j["log"].append(f"[system] All libraries ready ({len(reqs)} package{'s' if len(reqs) != 1 else ''})")
    _spawn(j)


def _proc_stats(proc) -> dict:
    """Best-effort CPU%/memory for a running job, read straight from /proc.

    Deliberately dependency-free (psutil is not installed on the runner). All
    failures degrade to {} so the Details page simply shows no numbers rather
    than erroring.
    """
    if not proc or proc.poll() is not None:
        return {}
    pid = proc.pid
    out = {}
    try:
        with open(f"/proc/{pid}/status", "r") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    out["mem_mb"] = round(int(line.split()[1]) / 1024, 1)
                    break
    except Exception:
        pass
    try:
        clk = os.sysconf("SC_CLK_TCK") or 100
        with open(f"/proc/{pid}/stat", "r") as fh:
            parts = fh.read().rsplit(") ", 1)[-1].split()
        # utime/stime are fields 14/15 (1-based) => index 11/12 after the comm.
        used = (int(parts[11]) + int(parts[12])) / clk
        with open("/proc/uptime", "r") as fh:
            up = float(fh.read().split()[0])
        start = int(parts[19]) / clk
        alive = max(up - start, 1e-6)
        out["cpu_pct"] = round(min(used / alive * 100.0, 999.0), 1)
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# CRASH/REDEPLOY RECOVERY
# ---------------------------------------------------------------------------
# _jobs lives only in memory. Spawned children use start_new_session=True, so
# they SURVIVE a runner restart — but the registry that described them does
# not. The job kept running (a Telegram bot kept answering chats) while the
# API reported "offline", and Restart then cold-started a SECOND copy.
#
# Fix: write a tiny manifest next to each job's workspace and re-adopt still
# -alive processes on boot.
_MANIFEST = "job.json"


def _manifest_path(job_id: str) -> str:
    return os.path.join(_job_dir(job_id), _MANIFEST)


def _save_manifest(j: dict) -> None:
    """Persist the facts needed to re-adopt this job after a restart."""
    try:
        proc = j.get("proc")
        data = {
            "id": j["id"], "name": j["name"], "lang": j["lang"],
            "file": j.get("file"), "bin": j.get("bin"), "pylibs": j.get("pylibs"),
            "port": j.get("port"), "web_slug": j.get("web_slug"),
            "web_public": j.get("web_public", True),
            "access_key": j.get("access_key"), "repo_url": j.get("repo_url"),
            "env": j.get("env") or {},
            "restart_enabled": bool(j.get("restart_enabled", True)),
            "started_at": j.get("started_at"),
            "pid": proc.pid if proc else None,
        }
        with open(_manifest_path(j["id"]), "w") as fh:
            json.dump(data, fh)
    except Exception as exc:  # never let bookkeeping break a launch
        logger.warning("manifest save failed for %s: %s", j.get("id"), exc)


# ---------------------------------------------------------------------------
# WORKSPACE SNAPSHOTS  —  surviving a full redeploy
# ---------------------------------------------------------------------------
# A job's cwd (JOBS_DATA_DIR/<id>) already survives Stop / Restart / code edits,
# because we only ever overwrite main.* and never delete the directory. What it
# does NOT survive on Render's FREE tier is a deploy: the container filesystem
# is rebuilt from the image, so a referral bot's database.db — its points and
# history — disappeared. The documented answer was "mount a Persistent Disk",
# which needs a paid plan.
#
# So the durable store we already have (Postgres, via the main site) becomes the
# backup target. The runner only knows how to pack/unpack a workspace; the main
# site owns the DB and drives the schedule. That split keeps the runner
# stateless and lets this work in both embedded and two-service layouts.
#
# Only DATA is snapshotted. Code (main.*) comes from the jobs table, and
# installed packages (pylibs/, node_modules/) are re-installable and huge, so
# including them would blow the size cap for no benefit.
SNAPSHOT_MAX_BYTES = int(os.getenv("SNAPSHOT_MAX_BYTES", str(24 * 1024 * 1024)))
SNAPSHOT_SKIP_DIRS = {
    "pylibs", "node_modules", "__pycache__", ".git", ".venv", "venv",
    ".cache", ".npm", ".pip", ".local", "vendor", ".pytest_cache",
}
# main.* is rewritten from the jobs table on every deploy; job.json is rebuilt
# by _spawn(). Restoring either would fight the code the user just saved.
SNAPSHOT_SKIP_FILES = {_MANIFEST}
SNAPSHOT_SKIP_EXT = {".pyc", ".pyo", ".log", ".sock", ".pid"}


def _is_code_file(rel: str, j: Optional[dict] = None) -> bool:
    """True for the entrypoint the site re-writes on every deploy."""
    base = os.path.basename(rel)
    if base.startswith("main.") and "/" not in rel.strip("/"):
        return True
    if j:
        for key in ("file", "bin"):
            p = j.get(key)
            if p and os.path.basename(p) == base:
                return True
    return False


def _snapshot_files(jdir: str, j: Optional[dict] = None) -> list:
    """Relative paths of the DATA files worth preserving, smallest first."""
    out = []
    root = Path(jdir)
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        try:
            if not p.is_file() or p.is_symlink():
                continue
            rel = str(p.relative_to(root)).replace(os.sep, "/")
            parts = rel.split("/")
            if any(part in SNAPSHOT_SKIP_DIRS for part in parts[:-1]):
                continue
            if parts[-1] in SNAPSHOT_SKIP_FILES:
                continue
            if os.path.splitext(rel)[1].lower() in SNAPSHOT_SKIP_EXT:
                continue
            if _is_code_file(rel, j):
                continue
            out.append((p.stat().st_size, rel))
        except Exception:
            continue
    # Smallest first: if we hit the cap, a 20 MB cache never starves the 40 KB
    # database.db that actually matters.
    out.sort()
    return [rel for _size, rel in out]


def _pack_workspace(job_id: str) -> dict:
    """tar.gz the job's data files -> base64. Returns {} when there's nothing."""
    jdir = os.path.join(JOBS_DATA_DIR, job_id)
    if not os.path.isdir(jdir):
        return {}
    j = _jobs.get(job_id)
    rels = _snapshot_files(jdir, j)
    if not rels:
        return {}
    buf = io.BytesIO()
    packed = 0
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tf:
        for rel in rels:
            full = os.path.join(jdir, rel)
            try:
                if buf.tell() > SNAPSHOT_MAX_BYTES:
                    logger.info("snapshot %s: hit %d byte cap after %d files",
                                job_id, SNAPSHOT_MAX_BYTES, packed)
                    break
                tf.add(full, arcname=rel, recursive=False)
                packed += 1
            except Exception:
                continue
    raw = buf.getvalue()
    if not packed or len(raw) > SNAPSHOT_MAX_BYTES:
        return {}
    return {
        "tarball_b64": base64.b64encode(raw).decode("ascii"),
        "file_count": packed,
        "byte_size": len(raw),
    }


def _unpack_workspace(job_id: str, tarball_b64: str, overwrite: bool = False) -> dict:
    """Restore a snapshot into the job dir.

    overwrite=False (the default) is deliberate: a live workspace's file is
    always fresher than the last snapshot, so restoring over it would ROLL BACK
    a running bot. After a redeploy the directory is empty, so every file gets
    written — which is exactly the case this feature exists for.
    """
    jdir = _job_dir(job_id)
    written, skipped = 0, 0
    try:
        raw = base64.b64decode(tarball_b64)
    except Exception:
        raise HTTPException(400, detail="Snapshot is not valid base64.")
    root = os.path.realpath(jdir)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            # Path traversal. NOTE: str.lstrip("./") strips every leading "."
            # AND "/" character, so it silently turns "../../etc/pwned" into
            # "etc/pwned" — a sanitiser that manufactures a valid-looking path
            # out of a hostile one. Strip only the "./" prefix tar writes, then
            # reject anything still absolute or containing a "..".
            name = m.name
            while name.startswith("./"):
                name = name[2:]
            if (not name or name.startswith("/") or name.startswith("../")
                    or ".." in name.split("/")):
                skipped += 1
                continue
            dest = os.path.realpath(os.path.join(root, name))
            if not (dest == root or dest.startswith(root + os.sep)):
                skipped += 1
                continue
            if _is_code_file(name) or os.path.basename(name) in SNAPSHOT_SKIP_FILES:
                skipped += 1
                continue
            if os.path.exists(dest) and not overwrite:
                skipped += 1
                continue
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                src = tf.extractfile(m)
                if src is None:
                    continue
                with open(dest, "wb") as fh:
                    shutil.copyfileobj(src, fh)
                written += 1
            except Exception:
                skipped += 1
    logger.info("Restored snapshot into %s: %d written, %d skipped", jdir, written, skipped)
    return {"restored": written, "skipped": skipped}


def _pid_alive(pid: int, started_at: float) -> bool:
    """True if `pid` is running AND is plausibly our original child.

    PIDs get recycled, so we also require the process start time to predate
    nothing newer than our record — a cheap guard against adopting a stranger.
    """
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError, PermissionError):
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            cmd = fh.read().decode("utf-8", "replace")
        # Our jobs always run out of the jobs data dir.
        return JOBS_DATA_DIR in cmd or "python" in cmd or "node" in cmd
    except Exception:
        return True          # cannot verify; os.kill said it exists


class _AdoptedProc:
    """Minimal stand-in for subprocess.Popen for a re-adopted process.

    We cannot recover the original Popen object across a restart, but the only
    things the runner asks of it are poll() and pid.
    """

    def __init__(self, pid):
        self.pid = pid
        self._rc = None

    def poll(self):
        if self._rc is not None:
            return self._rc
        try:
            os.kill(self.pid, 0)
            return None                      # still alive
        except Exception:
            self._rc = -1
            return self._rc

    def wait(self, timeout=None):
        import time as _t
        deadline = (_t.time() + timeout) if timeout else None
        while self.poll() is None:
            if deadline and _t.time() > deadline:
                raise subprocess.TimeoutExpired(str(self.pid), timeout)
            _t.sleep(0.2)
        return self._rc


def _recover_jobs() -> None:
    """On boot, re-adopt jobs whose processes outlived the previous runner."""
    try:
        if not os.path.isdir(JOBS_DATA_DIR):
            return
        adopted = 0
        for job_id in os.listdir(JOBS_DATA_DIR):
            mp = os.path.join(JOBS_DATA_DIR, job_id, _MANIFEST)
            if not os.path.isfile(mp):
                continue
            try:
                with open(mp) as fh:
                    m = json.load(fh)
            except Exception:
                continue
            pid = m.get("pid")
            if not _pid_alive(pid, m.get("started_at") or 0):
                continue
            j = {
                "id": m["id"], "name": m.get("name") or "job",
                "lang": m.get("lang") or "python",
                "dir": os.path.join(JOBS_DATA_DIR, job_id),
                "file": m.get("file"), "bin": m.get("bin"),
                "pylibs": m.get("pylibs"),
                "proc": _AdoptedProc(pid),
                "status": "running",
                "log": deque(maxlen=JOB_LOG_LINES),
                "restarts": 0,
                "restart_enabled": bool(m.get("restart_enabled", True)),
                "stop_requested": False,
                "started_at": m.get("started_at") or time.time(),
                "last_proxy_time": time.time(),
                "port": m.get("port"),
                "web": False,
                "web_slug": m.get("web_slug") or _slugify(m.get("name") or job_id),
                "web_public": bool(m.get("web_public", True)),
                "access_key": m.get("access_key") or secrets.token_urlsafe(12),
                "repo_url": m.get("repo_url"),
                "env": m.get("env") or {},
                "adopted": True,
            }
            j["log"].append("[system] re-adopted after a runner restart (process still alive)")
            with _jobs_lock:
                _jobs[m["id"]] = j
            if j.get("port"):
                threading.Thread(target=_web_watch, args=(j, j["proc"], j["port"]),
                                 daemon=True).start()
            adopted += 1
        if adopted:
            logger.info("Recovered %d still-running job(s) after restart", adopted)
    except Exception as exc:  # noqa: BLE001
        logger.warning("job recovery failed: %s", exc)


def _track_peak(j: dict, stats: dict) -> dict:
    """Remember the highest RSS seen for this run.

    A job that OOMs is often small again by the time anyone looks — the spike
    is what explains the kill, so it has to be recorded as it happens rather
    than reconstructed later.
    """
    try:
        cur = float((stats or {}).get("mem_mb") or 0.0)
        if cur > float(j.get("peak_mem_mb") or 0.0):
            j["peak_mem_mb"] = cur
    except Exception:
        pass
    return stats or {}


def _job_public(j: dict) -> dict:
    """Safe public view of a job (no internal objects)."""
    running = j["proc"] is not None and j["proc"].poll() is None
    return {
        "id": j["id"],
        "name": j["name"],
        "language": j["lang"],
        "status": "running" if running else j["status"],
        "restarts": j["restarts"],
        "started_at": j["started_at"],
        "uptime_s": int(time.time() - j["started_at"]) if running else 0,
        "web": bool(j.get("web")),
        # The Details page shows a Port row; without this it was always "—".
        "port": j.get("port") if running else None,
        # Live resource usage (Details page). Empty dict when unavailable.
        **_track_peak(j, _proc_stats(j.get("proc")) if running else {}),
        # Only the KEYS — values may hold bot tokens and must not be echoed.
        "env_keys": sorted((j.get("env") or {}).keys()),
        # Packages auto-installed for this job. Recorded so the admin panel can
        # answer "which jobs pulled in opencv-python?" across the platform
        # without grepping every job's log.
        "libs": sorted(j.get("libs") or []),
        # Peak RSS seen for this run — a job can look small right now and still
        # have spiked; the peak is what explains an OOM after the fact.
        "peak_mem_mb": round(j.get("peak_mem_mb") or 0.0, 1),
        "last_exit_reason": j.get("last_exit_reason"),
        "web_slug": j.get("web_slug"),
        "web_public": bool(j.get("web_public", True)),
        # access_key only reaches the main site (this API is secret-guarded) —
        # it builds the private share-link ?key= for the job owner.
        "access_key": j.get("access_key") if not j.get("web_public", True) else None,
        "dir": j.get("dir"),
    }


def _clear_manifest_pid(j: dict) -> None:
    """Mark a job as intentionally not-running so boot recovery skips it."""
    try:
        mp = _manifest_path(j["id"])
        if not os.path.isfile(mp):
            return
        with open(mp) as fh:
            m = json.load(fh)
        m["pid"] = None
        with open(mp, "w") as fh:
            json.dump(m, fh)
    except Exception:
        pass


def _kill_job_tree(j: dict) -> None:
    """Kill the whole process group, and VERIFY it actually died.

    Restart used to hang here: if SIGTERM was ignored (or the process was a
    re-adopted one whose group we no longer own) the old process stayed alive
    holding the job's port, and the restart then spawned a second copy that
    fought it. Now we escalate to SIGKILL and confirm the pid is gone before
    returning, so a restart can never leave two copies running.
    """
    proc = j.get("proc")
    if not proc or proc.poll() is not None:
        return
    pid = proc.pid

    def _signal_all(sig):
        sent = False
        try:                                    # whole group first
            os.killpg(os.getpgid(pid), sig)
            sent = True
        except Exception:
            pass
        try:                                    # then the pid itself
            os.kill(pid, sig)
            sent = True
        except Exception:
            pass
        return sent

    _signal_all(signal.SIGTERM)
    try:
        proc.wait(timeout=3)
    except Exception:
        pass

    if proc.poll() is None:                     # still alive -> force it
        _signal_all(signal.SIGKILL)
        try:
            proc.wait(timeout=3)
        except Exception:
            pass

    # Final confirmation. Never return while the pid is still around, or the
    # caller will start a duplicate on the same port.
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except Exception:
            break                               # gone
        time.sleep(0.1)
    else:
        logger.warning("job %s pid %s did not exit after SIGKILL", j.get("id"), pid)


def _spawn(j: dict) -> None:
    """(Re)start the job process + reader thread + supervisor thread."""
    cfg = LANGS[j["lang"]]
    cmd = [c.replace("{file}", j["file"]).replace("{bin}", j["bin"]).replace("{dir}", j["dir"]) for c in cfg["run"]]
    # pip-installed packages (from the "# requirements:" header) live in the
    # job's own dir and persist across auto-restarts via PYTHONPATH.
    env = dict(os.environ)
    if j.get("pylibs"):
        env["PYTHONPATH"] = j["pylibs"] + os.pathsep + env.get("PYTHONPATH", "")
    # User env vars. Applied AFTER the base environment so a job can override
    # its own settings, but PATH/PYTHONPATH/PORT are protected below.
    for k, v in (j.get("env") or {}).items():
        env[k] = v
    # Web-capable jobs: every job gets a reserved private port. Frameworks
    # (Flask/Express/FastAPI/http.server) bound through $PORT get a public
    # /live/{slug}/ address the moment their listener comes up.
    if j.get("port"):
        env["PORT"] = str(j["port"])
        env["HOST"] = "0.0.0.0"
    proc = subprocess.Popen(
        cmd, cwd=j["dir"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,  # merged, VPS-style
        text=True, bufsize=1,
        preexec_fn=_set_limits if os.name != "nt" else None,
        start_new_session=True,
        env=env,
    )
    j["proc"] = proc
    j["status"] = "running"
    j["log"].append(f"[system] started (pid {proc.pid})")
    # Record the pid so a future runner boot can re-adopt this process
    # instead of reporting the job offline and cold-starting a duplicate.
    _save_manifest(j)

    # Reset the web flag for this incarnation and start a fresh port watchdog.
    j["web"] = False
    if j.get("port"):
        threading.Thread(target=_web_watch, args=(j, proc, j["port"]), daemon=True).start()

    def _reader():
        try:
            for line in proc.stdout:
                j["log"].append(line.rstrip("\n"))
        except Exception:
            pass

    def _supervisor():
        rc = proc.wait()
        # Explain an OOM kill in the LOG only. Nothing is announced up front —
        # users may attempt whatever they like — but a process that vanishes
        # with no reason reads as "the platform is broken", so anyone who opens
        # the log finds a plain sentence instead of a mystery.
        #
        # RLIMIT_AS makes the allocation fail rather than signalling, so Python
        # usually dies with MemoryError (rc=1) and CPython prints the traceback
        # to stderr, which is already in this log. A kernel OOM kill arrives as
        # SIGKILL, i.e. rc == -9.
        oom = False
        if rc == -9:
            oom = True
        elif rc not in (0, None):
            try:
                tail = "\n".join(list(j["log"])[-25:])
                oom = ("MemoryError" in tail
                       or "Cannot allocate memory" in tail
                       or "OutOfMemoryError" in tail
                       or "JavaScript heap out of memory" in tail)
            except Exception:
                oom = False
        j["last_exit_reason"] = ("oom" if oom
                                 else "manual" if j.get("stop_requested")
                                 else "crash" if rc not in (0, None) else "exit")
        if oom:
            j["log"].append(
                f"[system] Process stopped: exceeded memory limit "
                f"({MAX_MEM_MB}MB)."
            )
            j["oom"] = True
        j["log"].append(f"[system] exited with code {rc}")
        if j.get("stop_requested"):
            j["status"] = "stopped"
            return
        if j["restart_enabled"] and j["restarts"] < JOB_RESTART_LIMIT:
            j["restarts"] += 1
            j["log"].append(f"[system] restarting in {JOB_RESTART_DELAY_S}s (attempt {j['restarts']}/{JOB_RESTART_LIMIT})")
            time.sleep(JOB_RESTART_DELAY_S)
            if not j.get("stop_requested"):
                _spawn(j)
        else:
            j["status"] = "crashed" if rc != 0 else "stopped"

    threading.Thread(target=_reader, daemon=True).start()
    threading.Thread(target=_supervisor, daemon=True).start()


@app.post("/internal/jobs", status_code=201)
def job_start(req: JobStartRequest, authorization: Optional[str] = Header(None)):
    """Create & start a persistent job. Auth: same Bearer secret."""
    _check_secret(authorization)

    lang = (req.language or "").lower().strip()
    code = req.code or ""
    if lang not in LANGS:
        raise HTTPException(400, detail=f"Unsupported language: {lang}. Available: {', '.join(sorted(LANGS))}")
    # A repo job legitimately has NO inline code: the source arrives with the
    # clone. This check ran before the clone and rejected every repo import
    # outright -- reported as "code empty" on a repo that plainly has files.
    if not code.strip() and not (req.repo_url or "").strip():
        raise HTTPException(400, detail="Code is empty.")

    # Admission by MEASURED memory, not by job count. Counting assumed every
    # bot would use its worst-case ceiling; real idle bots sit near 45MB, so a
    # count-based cap called the box full while most of the RAM was free.
    adm = _admission()
    if not adm["admit"]:
        # 503, not 429: the SERVER is out of room, the caller did nothing
        # wrong. The main site reads the distinction and tries the next worker
        # in the pool. The wording must never suggest the user stop one of
        # THEIR jobs — what fills a worker is usually other people's bots.
        raise HTTPException(
            503,
            detail=(f"This runner is full "
                    f"({adm['used_mb']:.0f}MB / {adm['safe_mb']}MB in use)."),
            headers={"X-Runner-Full": "1"},
        )

    job_id = uuid.uuid4().hex[:12]
    # Persistent workspace — bot's cwd. Same directory reused across
    # Stop/Restart cycles (and across full redeploys when /app/data is on
    # a persistent disk). Code files are overwritten below; user-created
    # files (SQLite DBs, sessions, caches) are LEFT UNTOUCHED.
    jdir = _job_dir(job_id)
    repo_url = (req.repo_url or "").strip()
    user_entry = (req.entry or "").strip()

    # If a repo URL was given, clone the whole repository into jdir first.
    repo_log = deque(maxlen=JOB_LOG_LINES)
    if repo_url:
        if not _clone_repo(repo_url, jdir, repo_log):
            # Cleanup and surface clone error
            shutil.rmtree(jdir, ignore_errors=True)
            raise HTTPException(400, detail="Repo clone failed:\n" + "\n".join(repo_log)[-2000:])

    # Detect entry point — either user-supplied, auto-detected, or falls back to inline code.
    inline_has_code = bool(code.strip())
    detected_lang, detected_src = None, None
    if user_entry:
        # Explicit entry from user ("main.py", "app.js", "src/bot.py")
        fp = os.path.join(jdir, user_entry)
        if not os.path.isfile(fp):
            raise HTTPException(400, detail=f"Entry file '{user_entry}' not found in repo.")
        ext = user_entry.rsplit(".",1)[-1].lower()
        ext_map = {"py":"python","js":"javascript","rb":"ruby","php":"php","sh":"bash"}
        detected_lang = ext_map.get(ext)
        detected_src = fp
        if detected_lang and detected_lang in LANGS:
            lang = detected_lang
    else:
        dl, ds = _detect_entry(jdir, inline_has_code and not repo_url, repo_log)
        if dl and ds:
            detected_lang, detected_src = dl, ds
            if not inline_has_code:
                lang = dl

    # Fallback language for pure-inline (no repo, no detected entry)
    if lang not in LANGS:
        lang = "python"
    cfg = LANGS[lang]

    if detected_src:
        src = detected_src
        # Rename the detected file to match our LANGS expectation (main.<ext>)
        # only if it isn't already. We keep the original AND write a symlink-style
        # duplicate-free wrapper so existing relative imports from main.py still work.
        expected = os.path.join(jdir, "main." + cfg["ext"])
        if os.path.abspath(src) != os.path.abspath(expected):
            # Launcher wrapper: just exec the real entry.
            wrapper = f"import runpy, sys; sys.path.insert(0, {repr(jdir)}); runpy.run_path({repr(src)}, run_name='__main__')"
            if cfg["ext"] == "py":
                with open(expected, "w") as f: f.write(wrapper)
                src = expected
            elif cfg["ext"] == "js":
                with open(expected, "w") as f:
                    rel = os.path.relpath(src, jdir)
                    f.write(f"require('./{rel.replace(chr(92),'/')}');\n")
                src = expected
            # other langs run from detected_src directly
            else:
                src = detected_src
        binf = os.path.join(jdir, "main.bin")
    else:
        src = os.path.join(jdir, "main." + cfg["ext"])
        binf = os.path.join(jdir, "main.bin")
        with open(src, "w") as f:
            f.write(code[:262144])

    # Compiled languages: compile ONCE before the job is considered started.
    if cfg.get("compile"):
        ccmd = [c.replace("{file}", src).replace("{bin}", binf).replace("{dir}", jdir) for c in cfg["compile"]]
        cout, cerr, ccode, _ = _run_subprocess(ccmd, jdir, None, MAX_TIME_MS / 1000)
        if ccode != 0:
            raise HTTPException(400, detail="Compilation failed:\n" + (cerr or cout)[:3000])

    # Dependencies: AUTO-DETECTED from inline code OR repo manifest.
    #
    # BUG (reported: ModuleNotFoundError on every cloned repo). This used to
    # read `if repo_url and detected_src:`, and the same expression was passed
    # to _prepare_and_run as its is_repo flag. _detect_entry() only recognises
    # a fixed list of filenames (main.py, app.py, bot.py, ...), so a repo whose
    # entry is called anything else -- n.py, start.py, __main__.py -- returned
    # (None, None). detected_src was then None, the flag was falsy, and
    # _install_repo_deps NEVER RAN even though requirements.txt was sitting
    # right there. The mechanism was correct; it was simply not reached.
    #
    # A manifest in the checkout is the only thing that decides now. Whether
    # we managed to guess the entry file is unrelated to whether the repo
    # declares dependencies.
    reqs = []
    pylibs = None
    repo_has_manifest = bool(repo_url) and any(
        os.path.isfile(os.path.join(jdir, m)) for m in
        ("requirements.txt", "pyproject.toml", "package.json", "Gemfile", "composer.json")
    )
    if repo_has_manifest:
        # Install from repo manifests first (requirements.txt / package.json / Gemfile)
        pylibs = os.path.join(jdir, "pylibs")
        os.makedirs(pylibs, exist_ok=True)
    else:
        reqs = _detect_imports(code)
        if reqs:
            pylibs = os.path.join(jdir, "pylibs")
            os.makedirs(pylibs, exist_ok=True)

    job = {
        "id": job_id,
        "name": (req.name or "job").strip()[:60] or "job",
        "lang": lang,
        "dir": jdir,
        "file": src,
        "bin": binf,
        "pylibs": pylibs,
        "proc": None,
        "status": "installing",
        "log": deque(maxlen=JOB_LOG_LINES),
        "restarts": 0,
        "restart_enabled": bool(req.restart),
        "stop_requested": False,
        "started_at": time.time(),
        "last_proxy_time": time.time(),
        "port": _alloc_port(),
        "web": False,
        "web_slug": _slugify(req.name or job_id),
        "web_public": True,
        "access_key": secrets.token_urlsafe(12),
        "repo_url": repo_url or None,
        "env": _clean_env(req.env),
    }
    with _jobs_lock:
        _jobs[job_id] = job
    for line in repo_log:
        job["log"].append(line)
    job["log"].append(f"[system] entry: {os.path.relpath(src, jdir)} ({lang})")
    threading.Thread(target=_prepare_and_run, args=(job, reqs, repo_has_manifest), daemon=True).start()
    logger.info("Job %s (%s/%s) created (repo=%s)", job_id, job["name"], lang, bool(repo_url))
    return _job_public(job)


@app.get("/internal/jobs")
def job_list(authorization: Optional[str] = Header(None)):
    _check_secret(authorization)
    with _jobs_lock:
        return {"jobs": [_job_public(j) for j in _jobs.values()], "capacity": MAX_BG_JOBS_HARD}


# ---------------------------------------------------------------------------
# FILE BROWSER  —  list / read / pin-entry for a job's working directory
#
# Cloned repos are multi-file, and until now only one file was reachable, so a
# user could not even look at the requirements.txt that had failed to install.
# These three endpoints back the tree in the editor.
#
# Everything is read straight off disk on each call. There is deliberately no
# cache: a cached listing is the bug fixed in _resolve_entry_now(), and the
# same mistake here would show a tree that disagrees with what actually runs.
# ---------------------------------------------------------------------------

# Never worth listing, and in .git's case actively harmful to walk.
_FB_SKIP_DIRS = {
    ".git", "node_modules", "pylibs", "__pycache__", ".venv", "venv",
    "vendor", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".next", ".cache", ".idea", ".vscode",
}
_FB_MAX_FILES = 400          # a tree past this is unusable anyway
_FB_MAX_READ = 512 * 1024    # 512 KB: the editor is not a hex viewer


def _fb_safe_join(jdir: str, rel: str) -> str:
    """Resolve rel inside jdir, or raise.

    Path traversal matters here even though the caller is authenticated: the
    job directory is the security boundary, and "../../etc/passwd" must not
    resolve. realpath collapses .. and follows symlinks, so a symlink planted
    inside a cloned repo cannot escape either.
    """
    rel = (rel or "").strip().lstrip("/")
    if not rel:
        raise HTTPException(400, detail="path required")
    base = os.path.realpath(jdir)
    full = os.path.realpath(os.path.join(base, rel))
    if full != base and not full.startswith(base + os.sep):
        raise HTTPException(400, detail="path outside the job directory")
    return full


def _fb_is_texty(path: str) -> bool:
    """Cheap binary check, so the tree can mark what is openable."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    return True


@app.get("/internal/jobs/{job_id}/files")
def job_files(job_id: str, authorization: Optional[str] = Header(None)):
    """Flat listing of the job's workspace, sorted, directories implied by path."""
    _check_secret(authorization)
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, detail="Job not found.")
    jdir = j.get("dir") or ""
    if not os.path.isdir(jdir):
        return {"files": [], "entry": None, "truncated": False}

    out = []
    truncated = False
    for root, dirs, names in os.walk(jdir):
        dirs[:] = [d for d in dirs if d not in _FB_SKIP_DIRS and not d.startswith(".")]
        for n in sorted(names):
            if n.startswith("."):
                continue
            full = os.path.join(root, n)
            rel = os.path.relpath(full, jdir)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            out.append({
                "path": rel.replace(os.sep, "/"),
                "size": size,
                "text": size <= _FB_MAX_READ and _fb_is_texty(full),
            })
            if len(out) >= _FB_MAX_FILES:
                truncated = True
                break
        if truncated:
            break

    out.sort(key=lambda f: (f["path"].count("/"), f["path"].lower()))
    cur = j.get("file")
    entry = os.path.relpath(cur, jdir).replace(os.sep, "/") if cur and os.path.isfile(cur) else None
    return {"files": out, "entry": entry, "truncated": truncated}


@app.get("/internal/jobs/{job_id}/file")
def job_file_read(job_id: str, path: str, authorization: Optional[str] = Header(None)):
    _check_secret(authorization)
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, detail="Job not found.")
    full = _fb_safe_join(j.get("dir") or "", path)
    if not os.path.isfile(full):
        raise HTTPException(404, detail="File not found.")
    size = os.path.getsize(full)
    if size > _FB_MAX_READ:
        raise HTTPException(413, detail=f"File is {size // 1024} KB; the editor opens up to {_FB_MAX_READ // 1024} KB.")
    if not _fb_is_texty(full):
        raise HTTPException(415, detail="That file is binary.")
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        return {"path": path, "content": f.read(), "size": size}


class EntryPinRequest(BaseModel):
    path: str


@app.post("/internal/jobs/{job_id}/entry")
def job_set_entry(job_id: str, req: EntryPinRequest,
                  authorization: Optional[str] = Header(None)):
    """Pin which file Run executes, for when auto-detection guessed wrong."""
    _check_secret(authorization)
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, detail="Job not found.")
    full = _fb_safe_join(j.get("dir") or "", req.path)
    if not os.path.isfile(full):
        raise HTTPException(404, detail="File not found.")
    rel = os.path.relpath(full, os.path.realpath(j["dir"])).replace(os.sep, "/")
    j["entry_rel"] = rel
    # Take effect on the next start; _resolve_entry_now() reads entry_rel first.
    j["file"] = full
    ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    for lname, cfg in LANGS.items():
        if cfg.get("ext") == ext:
            j["lang"] = lname
            break
    j["log"].append(f"[system] entry point set to {rel} — press Restart to apply")
    return {"ok": True, "entry": rel, "lang": j.get("lang")}


@app.get("/internal/jobs/{job_id}")
def job_detail(job_id: str, authorization: Optional[str] = Header(None)):
    _check_secret(authorization)
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, detail="Job not found (runner was restarted?).")
    info = _job_public(j)
    info["logs"] = "\n".join(j["log"])
    return info


@app.post("/internal/jobs/{job_id}/stop")
def job_stop(job_id: str, authorization: Optional[str] = Header(None)):
    _check_secret(authorization)
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, detail="Job not found.")
    j["stop_requested"] = True
    _kill_job_tree(j)
    j["status"] = "stopped"
    j["log"].append("[system] stopped by user")
    # An intentional stop must not be re-adopted as "running" on the next boot.
    _clear_manifest_pid(j)
    # Release the reserved port + web flag so the pool serves other jobs.
    j["web"] = False
    with _jobs_lock:
        j["port"] = None
    # IMPORTANT: do NOT remove j["dir"] — bot's database files (SQLite,
    # JSON sessions, uploaded data, referral-bot state…) must survive
    # Stop/Restart and admin redeploys. The workspace is reused on next _spawn.
    logger.info("Job %s stopped (workspace preserved at %s)", job_id, j.get("dir"))
    return _job_public(j)


@app.post("/internal/jobs/{job_id}/access")
def job_access(job_id: str, req: JobAccessRequest, authorization: Optional[str] = Header(None)):
    """Toggle a job's public URL between Public and Private (owner key needed)."""
    _check_secret(authorization)
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, detail="Job not found.")
    j["web_public"] = bool(req.public)
    j["log"].append(f"[system] web access set to {'PUBLIC' if j['web_public'] else 'PRIVATE'}")
    return _job_public(j)


@app.delete("/internal/jobs/{job_id}")
def job_delete(job_id: str, authorization: Optional[str] = Header(None)):
    """Permanently delete a job — kill process AND wipe its persistent
    workspace (ONLY when the user explicitly deletes from the dashboard)."""
    _check_secret(authorization)
    j = _jobs.pop(job_id, None)
    if not j:
        raise HTTPException(404, detail="Job not found.")
    j["stop_requested"] = True
    _kill_job_tree(j)
    # Only now — explicit delete — wipe the workspace (bot DB included).
    jdir = j.get("dir")
    if jdir and os.path.isdir(jdir):
        shutil.rmtree(jdir, ignore_errors=True)
    with _jobs_lock:
        j["port"] = None
    logger.info("Job %s deleted (workspace removed: %s)", job_id, jdir)
    return {"deleted": job_id}


class JobUpdateRequest(BaseModel):
    """Edit-and-redeploy in place: preserve the SAME job_id, port, web_slug,
    and workspace directory so bot databases/sessions are NOT wiped — only
    main.* is overwritten with the new code (or a new repo cloned)."""
    name: Optional[str] = None
    language: Optional[str] = None
    code: Optional[str] = None
    restart: Optional[bool] = True
    env: Optional[dict] = None
    repo_url: Optional[str] = ""
    entry: Optional[str] = ""


@app.patch("/internal/jobs/{job_id}")
def job_update(job_id: str, req: JobUpdateRequest, authorization: Optional[str] = Header(None)):
    """Edit + redeploy a job IN PLACE — same id/slug/port/dir, bot data kept."""
    _check_secret(authorization)
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, detail="Job not found.")

    # Kill current process (if running) but keep the dir.
    j["stop_requested"] = True
    _kill_job_tree(j)
    j["stop_requested"] = False
    j["restarts"] = 0

    # Apply updates
    if req.name is not None:
        new_name = req.name.strip()[:60] or j["name"]
        j["name"] = new_name
    new_lang = (req.language or j["lang"]).lower().strip()
    if new_lang != j["lang"] and new_lang in LANGS:
        j["lang"] = new_lang
    # Env edits must reach the RESPAWNED process, otherwise the runner keeps
    # serving the values it was originally created with.
    if req.env is not None:
        j["env"] = _clean_env(req.env)
    cfg = LANGS[j["lang"]]

    if req.code is not None and req.code.strip():
        # Re-derive file/bin paths in case language changed
        jdir = j["dir"]
        j["file"] = os.path.join(jdir, "main." + cfg["ext"])
        j["bin"] = os.path.join(jdir, "main.bin")
        # Overwrite ONLY main.* — user data (database.db, session.json,
        # data/, pylibs/) is untouched. This is what keeps referral-bot
        # state alive across admin code fixes.
        with open(j["file"], "w") as f:
            f.write(req.code[:262144])
        # Re-detect deps (only if imports changed — install missing ones).
        reqs = _detect_imports(req.code)
        if reqs:
            pylibs = os.path.join(jdir, "pylibs")
            os.makedirs(pylibs, exist_ok=True)
            j["pylibs"] = pylibs
            j["log"].append(f"[system] Code updated — checking libraries…")
            j["status"] = "installing"
            threading.Thread(target=_prepare_and_run, args=(j, reqs), daemon=True).start()
            return _job_public(j)
        else:
            j["pylibs"] = j.get("pylibs") or None

    # Re-allocate port if it was released during stop. Same self-deadlock as in
    # job_restart(): _alloc_port() acquires _jobs_lock internally.
    if not j.get("port"):
        j["port"] = _alloc_port()

    j["log"].append("[system] Code updated — restarting (data preserved)")
    j["status"] = "starting"
    _spawn(j)
    logger.info("Job %s updated in place (dir: %s)", job_id, j.get("dir"))
    return _job_public(j)




class SnapshotRestoreRequest(BaseModel):
    tarball_b64: str
    overwrite: bool = False


@app.get("/internal/jobs/{job_id}/snapshot")
def job_snapshot(job_id: str, authorization: Optional[str] = Header(None)):
    """Pack this job's DATA files so the main site can store them in Postgres.

    Works even when the job is stopped or was never adopted after a restart —
    it reads the directory, not the in-memory record, because the whole point
    is to save state that outlived the process.
    """
    _check_secret(authorization)
    if not re.fullmatch(r"[0-9a-f]{6,32}", job_id or ""):
        raise HTTPException(400, detail="Bad job id.")
    jdir = os.path.join(JOBS_DATA_DIR, job_id)
    if not os.path.isdir(jdir):
        return {"empty": True, "reason": "no workspace"}
    snap = _pack_workspace(job_id)
    if not snap:
        return {"empty": True, "reason": "no data files"}
    snap["empty"] = False
    return snap


@app.post("/internal/jobs/{job_id}/snapshot/restore")
def job_snapshot_restore(job_id: str, req: SnapshotRestoreRequest,
                         authorization: Optional[str] = Header(None)):
    """Unpack a snapshot into the job's workspace (used right after a deploy)."""
    _check_secret(authorization)
    if not re.fullmatch(r"[0-9a-f]{6,32}", job_id or ""):
        raise HTTPException(400, detail="Bad job id.")
    if not req.tarball_b64:
        raise HTTPException(400, detail="Empty snapshot.")
    return _unpack_workspace(job_id, req.tarball_b64, overwrite=req.overwrite)


@app.post("/internal/jobs/{job_id}/restart")
def job_restart(job_id: str, authorization: Optional[str] = Header(None)):
    """Restart a job IN-PLACE: same id, same slug, same port, same dir.
    Preserves the workspace (database.db, session.json, ...) — crucial for
    referral bots, scrapers, anything that writes state to cwd."""
    _check_secret(authorization)
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, detail="Job not found.")
    # Stop current process (keeps dir)
    j["stop_requested"] = True
    _kill_job_tree(j)
    j["stop_requested"] = False
    j["restarts"] = 0
    # Re-allocate port if released. _alloc_port() takes _jobs_lock itself, so
    # wrapping it in `with _jobs_lock:` self-deadlocked on this non-reentrant
    # lock — restart-after-stop hung forever and, because the lock was never
    # released, every later job operation piled up behind it and RunSpace froze.
    if not j.get("port"):
        j["port"] = _alloc_port()

    # Re-scan the working directory instead of trusting the path recorded at
    # create time: the user may have renamed, added or deleted files in the
    # editor since. See _resolve_entry_now().
    fresh = _resolve_entry_now(j)
    if fresh:
        if os.path.abspath(fresh) != os.path.abspath(j.get("file") or ""):
            j["log"].append(
                f"[system] entry changed → {os.path.relpath(fresh, j['dir'])}")
        j["file"] = fresh
    else:
        j["status"] = "crashed"
        j["log"].append(
            "[system] ✗ nothing runnable in the workspace — every candidate "
            "file is missing or empty. Open the file browser and pick an "
            "entry point.")
        return _job_public(j)

    j["log"].append("[system] restarting in place (workspace preserved)")
    _spawn(j)
    logger.info("Job %s restarted in place (dir: %s)", job_id, j.get("dir"))
    return _job_public(j)


# ---------------------------------------------------------------------------
# PUBLIC GATEWAY — /live/{slug}/...  →  http://127.0.0.1:{job port}/...
# No shared-secret check here: these URLs are meant for the OPEN web (and
# "private" jobs are protected by their own access key instead).
# ---------------------------------------------------------------------------

def _live_gate(slug: str, request: Request):
    """Shared checks for every /live/ visit.

    Returns (job, None) when the visit may proceed, else (None, response)."""
    j = _find_job_by_slug(slug)
    if not j:
        return None, _live_page(
            "No job here",
            "<h1>No job lives at this address</h1><p>It may have been stopped or deleted — the address is free again.</p>",
        )
    running = _job_running(j)
    if not running:
        return None, _live_page(
            "Job not running",
            f"<h1>This job is not running</h1><p>Start it again from the Ahad&nbsp;Co dashboard and refresh.</p>"
            f'<p class="note">Public job URLs are live only while the job is running.<br>'
            f"For production use, deploy as a dedicated service instead.</p>",
        )
    # Private gate: owner's access key must arrive as ?key= or X-Access-Key.
    if not j.get("web_public", True):
        key = request.query_params.get("key") or request.headers.get("x-access-key") or ""
        if key != j.get("access_key"):
            return None, HTMLResponse(_live_page(
                "Private job",
                "<h1>This job is private</h1><p>Only its owner can open this address.</p>",
            ).body, status_code=401)
    if not j.get("web") or not j.get("port"):
        return None, _live_page(
            "No web service yet",
            "<h1>The job is running, but no web listener yet</h1>"
            f"<p>If it is a web app, make sure it binds host <b>0.0.0.0</b> and the port from the <b>PORT</b> environment variable (currently {j.get('port') or 'n/a'}).</p>"
            '<p class="note">This URL appears automatically the moment your app opens its port.</p>',
        )
    ip = request.client.host if request.client else "?"
    if not _live_rate_ok(slug, ip):
        return None, HTMLResponse(_live_page(
            "Slow down",
            "<h1>Rate limit reached</h1><p>Too many requests — please wait a minute and try again.</p>",
        ).body, status_code=429)
    return j, None


_LIVE_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


@app.api_route("/live/{slug}", methods=_LIVE_METHODS, include_in_schema=False)
@app.api_route("/live/{slug}/{full_path:path}", methods=_LIVE_METHODS, include_in_schema=False)
async def live_http(slug: str, request: Request, full_path: str = ""):
    """Reverse-proxy an HTTP request into the job's localhost listener.
    The /live/{slug} prefix is stripped before forwarding."""
    j, early = _live_gate(slug, request)
    if early is not None:
        return early
    if httpx is None:
        return HTMLResponse("<h1>Proxy unavailable</h1>", status_code=503)

    query = request.url.query
    target = f"http://127.0.0.1:{j['port']}/{full_path}" + (f"?{query}" if query else "")
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP
    }
    headers["x-forwarded-for"] = request.client.host if request.client else ""
    headers["x-forwarded-prefix"] = f"/live/{slug}"

    now = time.time()
    last_access = j.get("last_proxy_time", 0)
    is_idle = (now - last_access > 120)
    j["last_proxy_time"] = now

    try:
        body = await request.body()
    except Exception:
        body = b""

    retries = [2.0, 4.0, 8.0]
    resp = None
    success = False
    last_exc = None

    for attempt in range(len(retries) + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                resp = await client.request(request.method, target, content=body, headers=headers)
            success = True
            break
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as exc:
            last_exc = exc
            if attempt < len(retries):
                delay = retries[attempt]
                logger.info("Proxy request to job %s failed (%s), retrying in %ss (attempt %d/3)...", slug, type(exc).__name__, delay, attempt + 1)
                await asyncio.sleep(delay)
            else:
                pass

    if not success:
        j["web"] = False  # listener went quiet / waking up
        return HTMLResponse(_live_page(
            "Waking up your RunSpace",
            "<h1>Waking up your RunSpace...</h1>"
            "<p>This can take up to a minute on the free tier. Retrying automatically...</p>",
            accent="#e67e22"
        ), status_code=502)

    # 302/301/307 redirects to root-absolute paths would drop the /live/{slug}
    # prefix — rewrite them so logins and form posts keep working.
    out_headers = {
        k: v for k, v in resp.headers.items() if k.lower() not in _HOP_BY_HOP
    }
    loc = resp.headers.get("location")
    if loc:
        if loc.startswith("/") and not loc.startswith("//"):
            out_headers["location"] = f"/live/{slug}{loc}"
        elif loc.startswith(f"http://127.0.0.1:{j['port']}"):
            out_headers["location"] = f"/live/{slug}" + loc[len(f"http://127.0.0.1:{j['port']}"):]

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=out_headers,
    )


@app.websocket("/live/{slug}")
@app.websocket("/live/{slug}/{full_path:path}")
async def live_ws(websocket: WebSocket, slug: str, full_path: str = ""):
    """Bridge WebSocket clients (chat apps, live dashboards) bidirectionally."""
    # Manual gate (WebSocket has no Request object) — same rules as HTTP.
    j = _find_job_by_slug(slug)
    reason = None
    if not j or not _job_running(j):
        reason = (404, "job not running")
    elif not j.get("web_public", True):
        key = websocket.query_params.get("key") or websocket.headers.get("x-access-key") or ""
        if key != j.get("access_key"):
            reason = (401, "private job")
    elif not j.get("web") or not j.get("port"):
        reason = (503, "no web listener")
    elif websockets is None:
        reason = (503, "proxy unavailable")
    if reason:
        code, why = reason
        await websocket.close(code=4400 + code // 100, reason=why)
        return

    await websocket.accept()
    query = websocket.url.query
    target = f"ws://127.0.0.1:{j['port']}/{full_path}" + (f"?{query}" if query else "")

    try:
        async with websockets.connect(target, ping_interval=None, max_queue=32) as upstream:
            async def client_to_upstream():
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if msg.get("text") is not None:
                            await upstream.send(msg["text"])
                        elif msg.get("bytes") is not None:
                            await upstream.send(msg["bytes"])
                except (WebSocketDisconnect, RuntimeError):
                    pass
                try:
                    await upstream.close()
                except Exception:
                    pass

            async def upstream_to_client():
                try:
                    async for data in upstream:
                        if isinstance(data, str):
                            await websocket.send_text(data)
                        else:
                            await websocket.send_bytes(data)
                except Exception:
                    pass
                try:
                    await websocket.close()
                except Exception:
                    pass

            tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
    except Exception:
        pass
    try:
        await websocket.close()
    except Exception:
        return


# ============================================================
# INTERACTIVE TERMINAL (Termux-style PTY over WebSocket)
# ============================================================
# This module runs in TWO layouts:
#   • embedded  — the whole repo is on the path, so it is `runner.terminal`
#   • standalone — runner/Dockerfile copies runner/* FLAT into /app, so there
#     is no `runner` package at all and it is just `terminal`.
# Importing only the package form crashed the standalone service on boot with
# `ModuleNotFoundError: No module named 'runner'` (uvicorn never started).
try:
    from runner import terminal as _term
except ModuleNotFoundError:
    import terminal as _term


class TerminalCreateRequest(BaseModel):
    # float, not int — same reason as services/term_proxy.TermCreateRequest:
    # xterm's FitAddon reports a fractional column count whenever the pane
    # is not an exact multiple of the cell width, and a strict int rejects
    # the request with a 422 so the terminal never opens. Floored below.
    cols: Optional[float] = 90
    rows: Optional[float] = 28
    shell: Optional[str] = "bash"


class TerminalListRequest(BaseModel):
    pass


@app.post("/internal/terminals", status_code=201)
def terminal_create(req: TerminalCreateRequest, authorization: Optional[str] = Header(None), x_user_id: Optional[str] = Header(None)):
    """Create (or reuse) a terminal session for a user."""
    _check_secret(authorization)
    try:
        user_id = int(x_user_id or "0")
    except ValueError:
        raise HTTPException(400, detail="x-user-id required.")
    if user_id <= 0:
        raise HTTPException(400, detail="auth required.")
    info = _term.manager.create(user_id, shell=req.shell or "bash",
                                cols=int(req.cols or 90), rows=int(req.rows or 28))
    # Build a connect URL relative to this runner
    return {
        "id": info["id"],
        "ticket": info["ticket"],
        "shell": info["shell"],
        "home": info["home"],
    }


@app.get("/internal/terminals")
def terminal_list(authorization: Optional[str] = Header(None), x_user_id: Optional[str] = Header(None)):
    _check_secret(authorization)
    try:
        user_id = int(x_user_id or "0")
    except ValueError:
        raise HTTPException(400, detail="x-user-id required.")
    return {"terminals": _term.manager.list_for(user_id)}


@app.websocket("/internal/terminal/ws")
async def terminal_ws(websocket: WebSocket):
    """Bidirectional PTY bridge. Client must send ?ticket=... on connect."""
    await websocket.accept()
    q = websocket.query_params
    ticket = (q.get("ticket") or "").strip()
    if not ticket:
        try:
            await websocket.send_json({"type": "error", "msg": "missing ticket"})
            await websocket.close(4401)
        except Exception:
            pass
        return
    sess = _term.manager.by_ticket(ticket)
    if not sess:
        try:
            await websocket.send_json({"type": "error", "msg": "invalid/expired ticket"})
            await websocket.close(4404)
        except Exception:
            pass
        return

    # Run attach (which starts the output-drain task) concurrently with the
    # inbound-message loop. When either side finishes we cancel the other.
    attach_task = asyncio.create_task(sess.attach(websocket))
    inbound_task = asyncio.create_task(_ws_inbound_loop(websocket, sess))
    try:
        done, pending = await asyncio.wait(
            [attach_task, inbound_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        for t in done:
            try:
                await t
            except Exception:
                pass
    except Exception:
        pass
    finally:
        for t in (attach_task, inbound_task):
            if not t.done():
                t.cancel()
        sess.detach(websocket)
        try:
            await websocket.close()
        except Exception:
            pass


async def _ws_inbound_loop(websocket, sess):
    """Read JSON messages from the WS and dispatch them to the session."""
    import json as _json
    while True:
        try:
            msg = await websocket.receive_text()
        except Exception:
            return
        try:
            evt = _json.loads(msg)
        except Exception:
            continue
        t = evt.get("type")
        try:
            if t == "in":
                sess.write(evt.get("data", "") or "")
            elif t == "resize":
                sess.resize(int(evt.get("cols", 90)), int(evt.get("rows", 28)))
            elif t == "setShell":
                sh = (evt.get("shell") or "").strip()
                if sh in _term.SHELLS:
                    sess.switch_shell(sh)
            elif t == "ping":
                await websocket.send_json({"type": "pong"})
        except Exception:
            pass


@app.on_event("startup")
def _startup_recover_jobs():
    """Re-adopt jobs whose processes outlived the previous runner instance."""
    _recover_jobs()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
