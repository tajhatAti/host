"""
runner/terminal.py — Persistent interactive terminal (PTY) manager.

CodeNest · "Termux-style" live shell.

* Real PTY (os.forkpty) so top/vim/nano/python/node REPL all work.
* Persistent per-session shell (reconnect picks up where you left off).
* Multi-shell switch: bash / python / node REPL.
* Resource limits (RLIMIT_AS) per PTY child.
* Bidirectional WebSocket JSON protocol:
    {type:"in"|"out"|"resize"|"setShell"|"hello"|"exit"|"shell"|"pong"|"ping"|"error"}
* Per-user persistent HOME at /app/data/homes/u<id>/ — bash history,
  pip --user packages, npm globals, files survive restarts.
* Thread-safe async WS bridge: a background thread reads the PTY and hands
  output to an asyncio.Queue which the Starlette/WebSocket task drains,
  so ws.send_text() is always awaited from the event loop (no
  "coroutine was never awaited" warnings).
"""
import os
import pty
import fcntl
import termios
import struct
import signal
import shutil
import select
import threading
import time
import json
import secrets
import logging
import subprocess
import asyncio
import tarfile
import base64
import io
import sys
import atexit
from pathlib import Path
from typing import Optional, Dict, Set
from collections import deque

logger = logging.getLogger("runner.terminal")

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
HOMES_ROOT = os.environ.get("TERM_HOMES_DIR", os.path.join(DATA_DIR, "homes"))
os.makedirs(HOMES_ROOT, exist_ok=True)

# We run the server as root (Render free tier blocks sudo/setuid inside
# unprivileged containers — no way around it). PTY children are also root
# but chdir'd into their own per-user home dir.
SKEL_DIR = os.environ.get("TERM_SKEL_DIR", "/root")

MAX_TERMINALS_PER_USER = int(os.getenv("TERM_MAX_PER_USER", "4"))
MAX_CONCURRENT_TERMINALS_TOTAL = int(os.getenv("TERM_MAX_TOTAL", "16"))
MAX_TERMINAL_MEM_MB = int(os.getenv("TERM_MAX_MEM_MB", "256"))
IDLE_KICK_S = int(os.getenv("TERM_IDLE_S", "1800"))  # 30 min idle (saves RAM on free tier)
READ_BUF = 4096
RING_BUF_MAX_BYTES = 32768  # ~32KB replay buffer per session
HOME_SNAPSHOT_MAX_BYTES = int(os.getenv("TERM_HOME_MAX_BYTES", str(2*1024*1024)))  # 2MB cap per home snapshot
HOME_SNAPSHOT_IDLE_S = int(os.getenv("TERM_SNAPSHOT_IDLE_S", "120"))  # snapshot 2min after last client leaves
AUTOSTART_RESTART_S = int(os.getenv("TERM_AUTOSTART_RESTART_S", "5"))
AUTOSTART_MAX_PER_USER = int(os.getenv("TERM_AUTOSTART_MAX", "2"))
# Per-slot (multi-tab) persistent PTYs — each gets own slot directory
# under ~/.ahad_slots/N/ containing run.sh (autostart), cwd marker, and a log.
SLOT_DIR = ".ahad_slots"

SHELLS = {
    "bash": {
        "argv": ["/bin/bash", "--noprofile", "--rcfile", os.path.join(SKEL_DIR, ".bashrc"), "-i"],
        "prompt": "$ ",
    },
    # python/node stay as keys so stale client setShell messages don't 500
    "python": {"argv": None},
    "node": {"argv": None},
}


class WsBridge:
    """Thread-safe bridge between a sync reader thread and an async websocket.

    The reader thread calls `enqueue({...})`; the websocket handler runs
    `drain(ws)` as a task, which awaits ws.send_text for every item.
    """
    SENTINEL = object()

    def __init__(self, ws, loop):
        self.ws = ws
        self.loop = loop
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False

    def enqueue(self, payload: dict):
        if self.closed:
            return
        asyncio.run_coroutine_threadsafe(self.queue.put(payload), self.loop)

    def close(self):
        self.closed = True
        try:
            asyncio.run_coroutine_threadsafe(self.queue.put(self.SENTINEL), self.loop)
        except Exception:
            pass

    async def drain(self):
        try:
            while True:
                item = await self.queue.get()
                if item is self.SENTINEL:
                    return
                try:
                    await self.ws.send_text(json.dumps(item))
                except Exception:
                    self.closed = True
                    return
        except asyncio.CancelledError:
            pass


class TerminalSession:
    """One live PTY session. Multiple clients can attach via WebSocket."""

    def __init__(self, sess_id: str, user_id: int, home: str, shell: str = "bash",
                 cols: int = 90, rows: int = 28, slot: int = 1, name: str = "", persist: bool = False):
        self.id = sess_id
        self.user_id = user_id
        self.home = home
        self.shell = shell if shell in SHELLS else "bash"
        self.cols = max(20, min(cols, 300))
        self.rows = max(8, min(rows, 200))
        self.slot = max(1, int(slot))
        self.name = (name or f"Shell {self.slot}").strip()[:40] or f"Shell {self.slot}"
        self.persist = bool(persist)  # 24/7 mode: skip idle reaper, auto-restart on boot/crash
        self.fd: Optional[int] = None
        self.child_pid: Optional[int] = None
        self.reader_thread: Optional[threading.Thread] = None
        self.clients: Dict[int, WsBridge] = {}
        self.clients_lock = threading.Lock()
        self.ticket = secrets.token_urlsafe(24)
        self.ticket_created = time.time()
        self.last_io = time.time()
        self.last_client = time.time()
        self.alive = False
        self.cwd = home
        self._lock = threading.Lock()
        self._buf = deque(maxlen=100)
        self._buf_bytes = 0
        # Per-slot workdir + autostart script path
        self.slot_dir = os.path.join(home, SLOT_DIR, str(self.slot))
        os.makedirs(self.slot_dir, exist_ok=True)
        self.slot_autostart = os.path.join(self.slot_dir, "run.sh")
        self.slot_log = os.path.join(self.slot_dir, "session.log")

    # ── lifecycle ──────────────────────────────────────────────
    def _autoboot_slot_script(self):
        """After bash is up, if the slot has a run.sh (24/7 mode), type it
        into the PTY so it runs as if the user launched it. Output stays
        visible when they attach later."""
        if not self.persist:
            return
        if not os.path.isfile(self.slot_autostart):
            return
        # Small delay so the motd/prompt settle first
        def _run():
            time.sleep(1.2)
            if not self.alive or self.fd is None:
                return
            try:
                # Quote the path defensively (spaces in $HOME possible in future)
                cmd = f"cd {self.home} && bash {self.slot_autostart!s}\n"
                os.write(self.fd, cmd.encode())
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def set_persist(self, on: bool, startup_cmd: str = "") -> bool:
        """Toggle 24/7 mode. If startup_cmd is given (new script content),
        write it to slot/run.sh. Returns True if persist is now on."""
        self.persist = bool(on)
        os.makedirs(self.slot_dir, exist_ok=True)
        if on:
            # Make sure a run.sh exists; if user didn't provide one, keep
            # whatever was already there (e.g. they wrote it via nano).
            if startup_cmd.strip() or not os.path.isfile(self.slot_autostart):
                content = startup_cmd.rstrip() + "\n" if startup_cmd.strip() else (
                    "#!/bin/bash\n# 24/7 slot autostart — put your bot command here (e.g. python ~/projects/b.py)\necho \"[slot] starting...\"\ncd \"$HOME\"\n"
                )
                with open(self.slot_autostart, "w") as f:
                    f.write(content)
            try:
                os.chmod(self.slot_autostart, 0o755)
            except Exception:
                pass
        self.last_client = time.time()  # don't reap immediately
        return self.persist

    def rename(self, new_name: str):
        n = (new_name or "").strip()[:40]
        if n:
            self.name = n

    def spawn(self):
        if self.child_pid is not None and self.alive:
            return
        env = os.environ.copy()
        env.update({
            "HOME": self.home,
            "USER": f"u{self.user_id}",
            "LOGNAME": f"u{self.user_id}",
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "SHELL": "/bin/bash",
            "PWD": self.home,
            "PATH": (
                f"{self.home}/.local/bin:{self.home}/.npm-global/bin:"
                "/usr/local/go/bin:/root/.cargo/bin:"
                "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            ),
            "PYTHONUSERBASE": f"{self.home}/.local",
            "PIP_USER": "1",
            "NPM_CONFIG_PREFIX": f"{self.home}/.npm-global",
            "AHAD_MOTD_SHOWN": "1",
            "AHAD_SLOT": str(self.slot),
        })
        os.makedirs(self.slot_dir, exist_ok=True)
        for sub in (".local/bin", ".npm-global", "projects", ".config", SLOT_DIR):
            os.makedirs(os.path.join(self.home, sub), exist_ok=True)

        # Always spawn bash as the PTY root. `self.shell` tracks which
        # quick-launch REPL the user is currently inside (bash/python/node)
        # for UI purposes only — python/node run as child processes of bash.
        argv = SHELLS["bash"]["argv"]

        pid, fd = pty.fork()
        if pid == 0:
            try:
                os.chdir(self.home)
                _set_rlimits()
                _set_winsize(pty.STDOUT_FILENO, self.rows, self.cols)
                try:
                    os.setsid()
                except Exception:
                    # Some environments (sandboxes, containers without CAP_SYS_ADMIN
                    # for certain session ops) may EPERM here; the PTY still works.
                    pass
                os.execvpe(argv[0], argv, env)
            except Exception as exc:
                try:
                    os.write(2, f"[exec failed] {exc}\r\n".encode())
                except Exception:
                    pass
                os._exit(1)
        else:
            self.child_pid = pid
            self.fd = fd
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            self.alive = True
            self.reader_thread = threading.Thread(target=self._reader, daemon=True)
            self.reader_thread.start()
            # Print a slot header + 24/7 badge
            badge = " \x1b[38;5;208m[24/7]\x1b[0m" if self.persist else ""
            banner = f"\r\n\x1b[90m── slot {self.slot} · \x1b[37m{self.name}\x1b[90m{badge} ──\x1b[0m\r\n"
            try:
                os.write(self.fd, banner.encode())
            except Exception:
                pass
            # 24/7 mode: auto-run slot run.sh after bash is up.
            self._autoboot_slot_script()
            logger.info("Terminal %s spawned (pid=%d, shell=%s, user=%d, slot=%d, persist=%s)",
                        self.id, pid, self.shell, self.user_id, self.slot, self.persist)

    def _reader(self):
        """Read loop with output-coalescing: reads up to READ_BUF in a tight loop
        for ~5ms, then broadcasts one combined frame per browser animation tick
        to reduce WS message spam (the cause of the stuttering)."""
        assert self.fd is not None
        pending = bytearray()
        last_flush = 0.0
        while self.alive:
            try:
                # Wait up to 40ms for data
                r, _, _ = select.select([self.fd], [], [], 0.04)
                # Reap zombie children of our PTY
                if self.child_pid:
                    try:
                        while True:
                            wpid, _ = os.waitpid(-self.child_pid, os.WNOHANG)
                            if wpid == 0:
                                break
                    except (ChildProcessError, ProcessLookupError):
                        pass
                if not r:
                    if pending:
                        self._flush_pending(pending); pending.clear(); last_flush = time.time()
                    # Check if bash exited
                    try:
                        wpid, status = os.waitpid(self.child_pid, os.WNOHANG)
                        if wpid != 0:
                            if pending:
                                self._flush_pending(pending); pending.clear()
                            self._broadcast({"type": "exit", "code": os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1})
                            self.alive = False
                            break
                    except ChildProcessError:
                        self.alive = False
                        break
                    continue
                try:
                    data = os.read(self.fd, READ_BUF)
                except OSError:
                    data = b""
                if not data:
                    if pending:
                        self._flush_pending(pending); pending.clear()
                    self._broadcast({"type": "exit", "code": 0})
                    self.alive = False
                    break
                self.last_io = time.time()
                pending.extend(data)
                # Ring buffer (cap total bytes per session)
                self._buf.append(bytes(data))
                self._buf_bytes += len(data)
                while self._buf_bytes > RING_BUF_MAX_BYTES and len(self._buf) > 1:
                    old = self._buf.popleft()
                    self._buf_bytes -= len(old)
                # Flush if we've accumulated >= ~1200 bytes or >= 12ms has passed
                now = time.time()
                if len(pending) >= 1200 or (now - last_flush) >= 0.012:
                    self._flush_pending(pending); pending.clear(); last_flush = now
            except Exception as exc:
                logger.exception("terminal reader error: %s", exc)
                break
        # Final flush before exit
        if pending:
            try: self._flush_pending(pending)
            except Exception: pass
        self.alive = False
        self._close_all_clients()
        self._try_reap()

    def _flush_pending(self, pending):
        if not pending:
            return
        try:
            text = bytes(pending).decode("utf-8", errors="replace")
        except Exception:
            text = bytes(pending).decode("latin-1", errors="replace")
        self._broadcast({"type": "out", "data": text})

    # ── I/O ────────────────────────────────────────────────────
    def _broadcast(self, obj: dict):
        with self.clients_lock:
            bridges = list(self.clients.values())
        for b in bridges:
            try:
                b.enqueue(obj)
            except Exception:
                pass

    def _close_all_clients(self):
        with self.clients_lock:
            bridges = list(self.clients.values())
            self.clients.clear()
        for b in bridges:
            b.close()

    def write(self, data: str):
        if not self.alive or self.fd is None:
            return
        try:
            os.write(self.fd, data.encode("utf-8", errors="replace"))
            self.last_io = time.time()
        except Exception as exc:
            logger.debug("terminal write error: %s", exc)

    def resize(self, cols: int, rows: int):
        self.cols, self.rows = max(20, min(cols, 300)), max(8, min(rows, 200))
        if self.fd is not None:
            try:
                _set_winsize(self.fd, self.rows, self.cols)
                if self.child_pid:
                    os.kill(self.child_pid, signal.SIGWINCH)
            except Exception:
                pass

    def switch_shell(self, shell: str):
        """Deprecated: only bash exists now. Keep method so stale clients
        sending `setShell` don't crash the server."""
        # Intentionally a no-op.
        return

    async def attach(self, ws):
        """Attach a websocket to this session. Starts a drain task, replays
        ring buffer, then awaits drain so the WS handler stays alive.
        """
        loop = asyncio.get_running_loop()
        bridge = WsBridge(ws, loop)
        with self.clients_lock:
            self.clients[id(ws)] = bridge
        self.last_client = time.time()
        # Replay recent ring buffer so reconnects pick up last ~30k of output
        if self._buf:
            bridge.enqueue({"type": "out", "data": b"".join(self._buf).decode("utf-8", errors="replace")})
        bridge.enqueue({
            "type": "hello", "id": self.id, "shell": self.shell,
            "slot": self.slot, "name": self.name, "persist": bool(self.persist),
        })
        try:
            await bridge.drain()
        finally:
            with self.clients_lock:
                self.clients.pop(id(ws), None)
            bridge.close()
            self.last_client = time.time()

    def detach(self, ws):
        """Sync counterpart for abrupt disconnect cleanup."""
        with self.clients_lock:
            bridge = self.clients.pop(id(ws), None)
            remaining = len(self.clients)
        if bridge:
            bridge.close()
        self.last_client = time.time()
        # Last client left — schedule a snapshot after HOME_SNAPSHOT_IDLE_S
        # so a fast reconnect doesn't constantly write to the DB.
        if remaining == 0:
            try:
                mgr = getattr(self,'_manager',None)
                if mgr is not None:
                    uid=self.user_id; hm=self.home
                    threading.Timer(HOME_SNAPSHOT_IDLE_S, lambda: mgr._snapshot_home(uid, hm)).start()
            except Exception: pass

    # ── cleanup ────────────────────────────────────────────────
    def kill_child(self):
        try:
            mgr = getattr(self, '_manager', None)
            if mgr is not None and getattr(self,'user_id',None) is not None:
                mgr._snapshot_home(self.user_id, self.home)
        except Exception: pass
        self.alive = False
        if self.child_pid:
            try:
                os.killpg(os.getpgid(self.child_pid), signal.SIGHUP)
            except Exception:
                pass
            for _ in range(20):
                try:
                    wpid, _ = os.waitpid(self.child_pid, os.WNOHANG)
                    if wpid != 0:
                        break
                except ChildProcessError:
                    break
                except Exception:
                    self.child_pid = None
                    break
                time.sleep(0.05)
            try:
                if self.child_pid:
                    os.killpg(os.getpgid(self.child_pid), signal.SIGKILL)
            except Exception:
                pass
            try:
                os.waitpid(self.child_pid, 0)
            except ChildProcessError:
                pass
            except Exception:
                pass
            self.child_pid = None
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None

    def _try_reap(self):
        if self.child_pid:
            try:
                os.waitpid(self.child_pid, os.WNOHANG)
            except ChildProcessError:
                pass
            except Exception:
                pass

    def destroy(self):
        self.alive = False
        self.kill_child()


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
class TerminalManager:
    def __init__(self):
        self.sessions: Dict[str, TerminalSession] = {}
        self.tickets: Dict[str, str] = {}
        self.user_sessions: Dict[int, Set[str]] = {}
        self._lock = threading.Lock()
        self._reaper = threading.Thread(target=self._idle_reaper, daemon=True)
        self._reaper.start()
        # 24/7 autostart supervisor — keeps ~/.ahad_autostart running
        # independent of any PTY (so TG/Discord bots survive idle kicks
        # and cold reboots, exactly like RunSpace jobs).
        self._autostart_procs: Dict[int, list] = {}
        self._autostart_lock = threading.Lock()
        self._autostart_watcher = threading.Thread(target=self._autostart_supervisor, daemon=True)
        self._autostart_watcher.start()
        # Best-effort snapshot on clean shutdown
        atexit.register(self._snapshot_all)
        # 30s after boot: restore all users' homes from DB and fire autostarts
        threading.Timer(30, self._bootstrap_autostarts).start()

    # Bump this when the skel bashrc/profile change so existing user homes
    # get the new version on next spawn (one-shot overwrite of rc files we
    # manage — user files under projects/ etc. are never touched).
    SKEL_VERSION = 10

    # ---------- 24/7 AUTOSTART (independent of PTY, like RunSpace jobs) ----------
    def _launch_autostart_for(self, user_id: int, home: str) -> bool:
        """Spawn ~/.ahad_autostart as a detached background process in its
        own process group (start_new_session=True), tracked by the
        supervisor so it can be restarted on crash. Returns True if a new
        process was actually launched.
        """
        _as = os.path.join(home, ".ahad_autostart")
        if not os.path.isfile(_as):
            return False
        try:
            os.chmod(_as, 0o755)
        except Exception:
            pass
        with self._autostart_lock:
            alive = [p for p in self._autostart_procs.get(user_id, []) if p.poll() is None]
            if len(alive) >= AUTOSTART_MAX_PER_USER:
                self._autostart_procs[user_id] = alive
                return False
            dn = dout = None
            try:
                dn = open(os.devnull, "rb")
                dout = open(os.path.join(home, ".ahad_autostart.log"), "ab", 0)
                env = {**os.environ,
                       "HOME": home, "USER": f"u{user_id}", "LOGNAME": f"u{user_id}",
                       "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                       "PATH": (f"{home}/.local/bin:{home}/.npm-global/bin:"
                                "/usr/local/go/bin:/root/.cargo/bin:"
                                "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
                       "PYTHONUSERBASE": f"{home}/.local", "PIP_USER": "1",
                       "NPM_CONFIG_PREFIX": f"{home}/.npm-global",
                       "AHAD_AUTOSTART": "1"}
                # start_new_session=True → own process group. The idle
                # reaper's os.killpg() targets only the PTY's pgid, so
                # these bots survive shell exits and idle kicks.
                p = subprocess.Popen(
                    ["/bin/bash", _as],
                    cwd=home, stdin=dn, stdout=dout, stderr=dout,
                    start_new_session=True, close_fds=True, env=env,
                )
                alive.append(p)
                self._autostart_procs[user_id] = alive
                logger.info("autostart launched u%d pid=%d", user_id, p.pid)
                return True
            except Exception as e:
                logger.warning("autostart Popen failed u%d: %s", user_id, e)
                try:
                    if dn: dn.close()
                except Exception: pass
                try:
                    if dout: dout.close()
                except Exception: pass
                return False

    def _autostart_supervisor(self):
        """Watchdog: every AUTOSTART_RESTART_S seconds, restart any autostart
        that has exited (crash/error) — same behavior as RunSpace jobs."""
        while True:
            time.sleep(AUTOSTART_RESTART_S)
            to_launch = []
            try:
                with self._autostart_lock:
                    for uid, plist in list(self._autostart_procs.items()):
                        alive = [p for p in plist if p.poll() is None]
                        self._autostart_procs[uid] = alive
                        if len(alive) < AUTOSTART_MAX_PER_USER:
                            home = os.path.join(HOMES_ROOT, f"u{uid}")
                            if os.path.isdir(home) and os.path.isfile(os.path.join(home, ".ahad_autostart")):
                                to_launch.append((uid, home))
            except Exception:
                pass
            for uid, home in to_launch:
                try:
                    self._launch_autostart_for(uid, home)
                except Exception:
                    pass

    def _bootstrap_autostarts(self):
        """On boot: restore every user's home (from the term_homes snapshot
        table) and launch each user's ~/.ahad_autostart. This runs 30s
        after server start so bots come back 24/7 after a Render redeploy
        WITHOUT anyone needing to open the Terminal tab."""
        try:
            db = self._db()
            if not db:
                return
            with db.get_db_connection() as conn:
                try:
                    rows = conn.execute(
                        "SELECT user_id FROM term_homes WHERE tarball_b64 IS NOT NULL AND tarball_b64 != ''"
                    ).fetchall()
                except Exception:
                    rows = []
            for r in rows:
                try:
                    uid = int(dict(r).get("user_id") or r[0])
                except Exception:
                    continue
                try:
                    home = self._home_for(uid)  # restores snapshot if fresh
                    self._launch_autostart_for(uid, home)
                except Exception as e:
                    logger.warning("bootstrap autostart u%d failed: %s", uid, e)
            logger.info("autostart bootstrap complete (%d users scanned)", len(rows))
        except Exception as e:
            logger.warning("autostart bootstrap failed: %s", e)

    # ---------- HOME SNAPSHOT ↔ DB (persistence across deploys) ----------
    def _db(self):
        try:
            sys.path.insert(0, "/app")
            import database as db  # type: ignore
            return db
        except Exception as e:
            logger.warning("terminal: cannot import database for snapshots: %s", e)
            return None

    def _snapshot_home(self, user_id: int, home: str) -> bool:
        """Tar+gzip the home dir and upsert base64 into term_homes table."""
        try:
            db = self._db()
            if not db: return False
            if not os.path.isdir(home): return False
            skip_names = {'.cache','__pycache__','.npm','.pip','.cargo'}
            def _filter(tarinfo):
                # skip huge/cache entries entirely
                parts = tarinfo.name.split('/')
                if any(p in skip_names for p in parts): return None
                if tarinfo.size > HOME_SNAPSHOT_MAX_BYTES: return None
                return tarinfo
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode='w:gz', compresslevel=6) as tf:
                tf.add(home, arcname='.', recursive=True, filter=_filter)
            data = buf.getvalue()
            if len(data) > HOME_SNAPSHOT_MAX_BYTES:
                logger.info("term home snapshot u%d skipped: %d bytes > cap", user_id, len(data))
                return False
            b64 = base64.b64encode(data).decode('ascii')
            now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            with db.get_db_connection() as conn:
                try:
                    conn.execute(
                        "INSERT INTO term_homes(user_id,tarball_b64,updated_at) VALUES (?,?,?)",
                        (user_id, b64, now))
                except Exception:
                    conn.execute(
                        "UPDATE term_homes SET tarball_b64=?, updated_at=? WHERE user_id=?",
                        (b64, now, user_id))
                conn.commit()
            return True
        except Exception as e:
            logger.warning("term snapshot_home(u%d) failed: %s", user_id, e)
            return False

    def _restore_home(self, user_id: int, home: str) -> bool:
        """Restore home dir from latest DB snapshot (if any) before skel copy."""
        try:
            db = self._db()
            if not db: return False
            with db.get_db_connection() as conn:
                row = conn.execute(
                    "SELECT tarball_b64 FROM term_homes WHERE user_id=?", (user_id,)
                ).fetchone()
            if not row or not row[0]: return False
            raw = base64.b64decode(row[0])
            os.makedirs(home, exist_ok=True)
            with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tf:
                for m in tf.getmembers():
                    if m.name.startswith('/') or '..' in m.name.split('/'):
                        continue
                    try: tf.extract(m, home)
                    except Exception: pass
            return True
        except Exception as e:
            logger.warning("term restore_home(u%d) failed: %s", user_id, e)
            return False

    def _snapshot_all(self):
        for sid, s in list(self.sessions.items()):
            if s.alive:
                try: self._snapshot_home(s.user_id, s.home)
                except Exception: pass

    def _home_for(self, user_id: int) -> str:
        h = os.path.join(HOMES_ROOT, f"u{user_id}")
        os.makedirs(h, exist_ok=True)
        skel = [
            (os.path.join(SKEL_DIR, ".bashrc"), ".bashrc"),
            (os.path.join(SKEL_DIR, ".profile"), ".profile"),
        ]
        ver_marker = os.path.join(h, ".ahad_skel_v")
        try:
            have_ver = int(open(ver_marker).read().strip() or "0")
        except Exception:
            have_ver = 0
        # Fresh home (first boot after deploy/cold start) → restore from DB snapshot
        restored = False
        if have_ver == 0:
            restored = self._restore_home(user_id, h)
        force = have_ver < self.SKEL_VERSION
        for src, name in skel:
            dst = os.path.join(h, name)
            if (not os.path.isfile(dst) or force) and os.path.isfile(src):
                try:
                    shutil.copy(src, dst)
                except Exception:
                    pass
        if force:
            try:
                with open(ver_marker, "w") as f:
                    f.write(str(self.SKEL_VERSION))
            except Exception:
                pass
        for sub in (".local/bin", ".npm-global", "projects", ".config"):
            os.makedirs(os.path.join(h, sub), exist_ok=True)
        # After restoring a snapshot, re-lay skel rc files to guarantee bashrc
        # is current (the restored tarball may contain an older version).
        if restored:
            for src, name in skel:
                try: shutil.copy(src, os.path.join(h, name))
                except Exception: pass
        return h

    def _next_slot(self, user_id: int) -> int:
        owned = self.user_sessions.get(user_id, set()) or set()
        used = set()
        for sid in owned:
            s = self.sessions.get(sid)
            if s and s.alive:
                used.add(s.slot)
        for i in range(1, MAX_TERMINALS_PER_USER + 1):
            if i not in used:
                return i
        return 1

    def _persistent_slots_for(self, user_id: int, home: str) -> list:
        """Scan ~/.ahad_slots/ for existing dirs that have a run.sh — those
        are 24/7 slots that should be restored on boot."""
        out = []
        root = os.path.join(home, SLOT_DIR)
        if not os.path.isdir(root):
            return out
        for name in os.listdir(root):
            p = os.path.join(root, name)
            if not os.path.isdir(p):
                continue
            try:
                slot_n = int(name)
            except ValueError:
                continue
            run = os.path.join(p, "run.sh")
            if os.path.isfile(run):
                out.append(slot_n)
        return sorted(out)[:MAX_TERMINALS_PER_USER]

    def _spawn_session_locked(self, user_id: int, home: str, slot: int,
                              name: str = "", persist: bool = False,
                              cols: int = 90, rows: int = 28) -> TerminalSession:
        """Must be called while holding self._lock."""
        sid = secrets.token_urlsafe(10)
        sess = TerminalSession(
            sid, user_id, home, shell="bash", cols=cols, rows=rows,
            slot=slot, name=name or f"Shell {slot}", persist=persist,
        )
        sess._manager = self
        self.sessions[sid] = sess
        self.tickets[sess.ticket] = sid
        self.user_sessions.setdefault(user_id, set()).add(sid)
        return sess

    def create(self, user_id: int, shell: str = "bash", cols: int = 90, rows: int = 28,
               slot: Optional[int] = None, name: str = "", persist: Optional[bool] = None,
               reuse_existing: bool = True) -> dict:
        """Create (or attach to existing) a terminal session.

        * If slot is given and an alive session with that slot exists, return
          its ticket (reconnect).
        * If reuse_existing=True and no slot given, return the most-recent
          alive session (back-compat for the old single-shell UI).
        * Otherwise allocate a fresh slot and spawn it.
        * persist=True marks the slot as 24/7: idle reaper skips it, and
          it gets respawned on cold boot.
        """
        with self._lock:
            owned = self.user_sessions.setdefault(user_id, set())

            # 1) Slot-specific reconnect
            if slot is not None:
                for sid in list(owned):
                    s = self.sessions.get(sid)
                    if s and s.alive and s.slot == int(slot):
                        if persist is not None:
                            s.set_persist(bool(persist))
                        if name:
                            s.rename(name)
                        s.ticket_created = time.time()
                        s.last_client = time.time()
                        return self._public_info(s)
                # Slot not alive but a 24/7 slot dir exists -> resurrect
                home = self._home_for(user_id)
                sp = int(slot)
                want_persist = bool(persist) if persist is not None else (
                    os.path.isfile(os.path.join(home, SLOT_DIR, str(sp), "run.sh"))
                )
                if len(owned) >= MAX_TERMINALS_PER_USER:
                    self._evict_one_locked(user_id)
                sess = self._spawn_session_locked(
                    user_id, home, slot=sp, name=name or f"Shell {sp}",
                    persist=want_persist, cols=cols, rows=rows,
                )
            else:
                # 2) Back-compat: hand back the most-recent alive session
                if reuse_existing:
                    for sid in list(owned):
                        s = self.sessions.get(sid)
                        if s and s.alive:
                            s.ticket_created = time.time()
                            return self._public_info(s)
                # 3) Brand new slot
                if len(owned) >= MAX_TERMINALS_PER_USER:
                    self._evict_one_locked(user_id)
                home = self._home_for(user_id)
                sp = self._next_slot(user_id)
                sess = self._spawn_session_locked(
                    user_id, home, slot=sp, name=name or f"Shell {sp}",
                    persist=bool(persist), cols=cols, rows=rows,
                )

            # Global cap check (evict idle non-persistent sessions across all users)
            alive_total = sum(1 for x in self.sessions.values() if x.alive)
            if alive_total >= MAX_CONCURRENT_TERMINALS_TOTAL:
                victims = sorted(
                    [x for x in self.sessions.values()
                     if x.alive and not x.clients and not x.persist],
                    key=lambda x: x.last_client,
                )
                if victims:
                    self._destroy_locked(victims[0].id)
        sess.spawn()
        return self._public_info(sess)

    def _public_info(self, s: TerminalSession) -> dict:
        return {
            "id": s.id, "ticket": s.ticket, "shell": s.shell,
            "slot": s.slot, "name": s.name, "persist": bool(s.persist),
        }

    def _evict_one_locked(self, user_id: int):
        """Kill one of the user's non-persistent sessions (oldest idle) to
        make room for a new one."""
        owned = self.user_sessions.get(user_id, set()) or set()
        cand = [self.sessions[sid] for sid in owned
                if sid in self.sessions and self.sessions[sid].alive
                and not self.sessions[sid].persist]
        if not cand:
            cand = [self.sessions[sid] for sid in owned
                    if sid in self.sessions and self.sessions[sid].alive]
        if cand:
            cand.sort(key=lambda x: x.last_client)
            self._destroy_locked(cand[0].id)

    def set_slot_persist(self, sess_id: str, user_id: int, on: bool,
                         startup_cmd: str = "", name: str = "") -> Optional[dict]:
        with self._lock:
            s = self.sessions.get(sess_id)
            if not s or s.user_id != user_id:
                return None
            s.set_persist(on, startup_cmd)
            if name:
                s.rename(name)
            return self._public_info(s)

    def list_for(self, user_id: int):
        with self._lock:
            owned = list(self.user_sessions.get(user_id, set()))
        out = []
        for sid in owned:
            s = self.sessions.get(sid)
            if not s or not s.alive:
                continue
            out.append({
                "id": s.id, "shell": s.shell, "alive": s.alive,
                "slot": s.slot, "name": s.name, "persist": bool(s.persist),
                "cwd": s.cwd, "clients": len(s.clients),
                "started": s.ticket_created,
            })
        out.sort(key=lambda x: x["slot"])
        return out

    def _destroy_locked(self, sid: str):
        s = self.sessions.pop(sid, None)
        if s:
            self.tickets.pop(s.ticket, None)
            for u, ss in self.user_sessions.items():
                ss.discard(sid)
            s.destroy()

    def close(self, sid: str, user_id: int):
        with self._lock:
            s = self.sessions.get(sid)
            if not s or s.user_id != user_id:
                return False
            self._destroy_locked(sid)
        return True

    def by_ticket(self, ticket: str) -> Optional[TerminalSession]:
        with self._lock:
            sid = self.tickets.get(ticket)
            if not sid:
                return None
            return self.sessions.get(sid)

    def _idle_reaper(self):
        while True:
            time.sleep(60)
            now = time.time()
            with self._lock:
                for sid in list(self.sessions.keys()):
                    s = self.sessions[sid]
                    # 24/7 (persist) slots never get reaped — they run like
                    # RunSpace jobs even when no browser is connected.
                    if s.persist:
                        # Still bump last_client so they don't accumulate
                        # (snapshot may still happen via atexit/periodic).
                        continue
                    if not s.clients and (now - s.last_client) > IDLE_KICK_S:
                        logger.info("Reaping idle terminal %s (slot %d)", sid, s.slot)
                        self._destroy_locked(sid)

    def _bootstrap_autostarts(self):
        """On boot: restore every user's home, then spawn PTYs for any
        persistent slots (those with .ahad_slots/N/run.sh) so they come
        back 24/7 after a redeploy WITHOUT the user opening a tab.
        Also launches the legacy single-file ~/.ahad_autostart (back-compat).
        """
        try:
            db = self._db()
            if not db:
                return
            with db.get_db_connection() as conn:
                try:
                    rows = conn.execute(
                        "SELECT user_id FROM term_homes WHERE tarball_b64 IS NOT NULL AND tarball_b64 != ''"
                    ).fetchall()
                except Exception:
                    rows = []
            for r in rows:
                try:
                    uid = int(dict(r).get("user_id") or r[0])
                except Exception:
                    continue
                try:
                    home = self._home_for(uid)
                    # Legacy global autostart
                    self._launch_autostart_for(uid, home)
                    # Persistent per-slot PTYs
                    slots = self._persistent_slots_for(uid, home)
                    for sp in slots:
                        # Spawn outside the lock; create() handles locking
                        try:
                            self.create(
                                uid, slot=sp,
                                name=f"Shell {sp}", persist=True,
                                reuse_existing=False,
                            )
                            time.sleep(0.5)
                        except Exception as e:
                            logger.warning("bootstrap slot u%d/slot%d: %s", uid, sp, e)
                except Exception as e:
                    logger.warning("bootstrap autostart u%d failed: %s", uid, e)
            logger.info("autostart bootstrap complete (%d users)", len(rows))
        except Exception as e:
            logger.warning("autostart bootstrap failed: %s", e)


manager = TerminalManager()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _set_rlimits():
    try:
        import resource
        # NOTE: we intentionally DO NOT set RLIMIT_NPROC here.
        # RLIMIT_NPROC is enforced PER-UID (not per-process), and every PTY
        # child runs as the same `runner` unix user in the container. A low
        # per-PTY value (e.g. 35) bleeds across all other sessions of any
        # user and crashes pip/gcc/etc. with "fork: Resource temporarily
        # unavailable". The safe guard against fork bombs is the combination
        # of: RLIMIT_AS (mem), RLIMIT_CPU, RLIMIT_FSIZE, the hard site-wide
        # concurrent-session cap (MAX_CONCURRENT_TERMINALS_TOTAL=6), and the
        # 30-minute idle reaper.
        mem = MAX_TERMINAL_MEM_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (3600, 3600))
        # Files: 512 soft / 1024 hard — pip/npm/gcc need more than 128.
        resource.setrlimit(resource.RLIMIT_NOFILE, (512, 1024))
        # No core dumps
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except Exception:
            pass
        # Cap single-file write to 64MB to prevent disk-fill
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
        except Exception:
            pass
    except Exception:
        pass


def _set_winsize(fd, rows, cols, xpix=0, ypix=0):
    try:
        s = struct.pack("HHHH", rows, cols, xpix, ypix)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, s)
    except Exception:
        pass
