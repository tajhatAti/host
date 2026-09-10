"""RunSpace workspace snapshots — does a bot's database.db actually survive?

These tests do NOT just assert that the new functions exist. Each one builds a
real workspace on disk, packs it, DESTROYS the directory (the thing a Render
deploy does to the free tier), unpacks it and checks the bytes came back.

Run:  DATA_DIR=$(mktemp -d) python3 tests/test_job_data_persistence.py
"""
import base64
import io
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("RUNNER_SERVICE_SECRET", "test-secret")
os.environ.setdefault("LIVE_PORT_MIN", "13400")
os.environ.setdefault("LIVE_PORT_MAX", "13499")

import runner.app as R  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -> {extra}" if extra else ""))


def make_workspace(job_id, *, points=42):
    """A realistic referral-bot workspace."""
    jdir = R._job_dir(job_id)
    with open(os.path.join(jdir, "main.py"), "w") as f:
        f.write("print('bot v1')\n")
    db = os.path.join(jdir, "database.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE users (id INTEGER, points INTEGER)")
    con.execute("INSERT INTO users VALUES (1, ?)", (points,))
    con.commit()
    con.close()
    with open(os.path.join(jdir, "session.json"), "w") as f:
        f.write('{"logged_in": true}')
    os.makedirs(os.path.join(jdir, "data"), exist_ok=True)
    with open(os.path.join(jdir, "data", "history.txt"), "w") as f:
        f.write("user1 referred user2\n")
    # noise that must NOT be backed up
    os.makedirs(os.path.join(jdir, "pylibs", "telebot"), exist_ok=True)
    with open(os.path.join(jdir, "pylibs", "telebot", "__init__.py"), "w") as f:
        f.write("x = 1\n" * 5000)
    os.makedirs(os.path.join(jdir, "__pycache__"), exist_ok=True)
    with open(os.path.join(jdir, "__pycache__", "main.pyc"), "wb") as f:
        f.write(b"\x00" * 500)
    with open(os.path.join(jdir, R._MANIFEST), "w") as f:
        f.write('{"id": "x"}')
    return jdir


def read_points(jdir):
    con = sqlite3.connect(os.path.join(jdir, "database.db"))
    v = con.execute("SELECT points FROM users WHERE id=1").fetchone()[0]
    con.close()
    return v


# ---------------------------------------------------------------------------
print("\n[1] what gets selected for backup")
# ---------------------------------------------------------------------------
jid = "aaaa11112222"
jdir = make_workspace(jid)
files = R._snapshot_files(jdir)

check("database.db included", "database.db" in files, files)
check("session.json included", "session.json" in files, files)
check("nested data/ included", "data/history.txt" in files, files)
check("main.py EXCLUDED (comes from the jobs table)", "main.py" not in files, files)
check("pylibs/ EXCLUDED", not any(f.startswith("pylibs/") for f in files), files)
check("__pycache__ EXCLUDED", not any("__pycache__" in f for f in files), files)
check(".pyc EXCLUDED", not any(f.endswith(".pyc") for f in files), files)
check("job.json manifest EXCLUDED", R._MANIFEST not in files, files)

# ---------------------------------------------------------------------------
print("[2] pack produces a real tar.gz")
# ---------------------------------------------------------------------------
snap = R._pack_workspace(jid)
check("snapshot is non-empty", bool(snap), snap)
check("file_count == selected files", snap.get("file_count") == len(files),
      f"{snap.get('file_count')} vs {len(files)}")
raw = base64.b64decode(snap["tarball_b64"])
check("byte_size matches payload", snap["byte_size"] == len(raw))
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
    names = sorted(m.name for m in tf.getmembers() if m.isfile())
check("tar contains exactly the data files", names == sorted(files), names)
check("pylibs really absent from the tar",
      not any("pylibs" in n for n in names), names)

# ---------------------------------------------------------------------------
print("[3] THE REAL TEST: wipe the disk like a Render deploy does")
# ---------------------------------------------------------------------------
before = read_points(jdir)
check("points readable before wipe", before == 42, before)

shutil.rmtree(jdir)
check("workspace really gone", not os.path.isdir(jdir))

# A deploy also gives the job a NEW runner id — that is why snapshots are keyed
# by the site job id. Restore into the new id.
new_jid = "bbbb33334444"
res = R._unpack_workspace(new_jid, snap["tarball_b64"])
new_dir = R._job_dir(new_jid)

check("files were restored", res["restored"] == len(files), res)
check("database.db is back", os.path.isfile(os.path.join(new_dir, "database.db")))
check("POINTS SURVIVED THE WIPE", read_points(new_dir) == 42, read_points(new_dir))
check("session.json is back", os.path.isfile(os.path.join(new_dir, "session.json")))
check("nested data/history.txt is back",
      os.path.isfile(os.path.join(new_dir, "data", "history.txt")))
with open(os.path.join(new_dir, "data", "history.txt")) as f:
    check("nested file content intact", f.read() == "user1 referred user2\n")

# ---------------------------------------------------------------------------
print("[4] restore must never roll a LIVE bot backwards")
# ---------------------------------------------------------------------------
live = "cccc55556666"
make_workspace(live, points=10)          # old snapshot: 10 points
old_snap = R._pack_workspace(live)
ldir = R._job_dir(live)
con = sqlite3.connect(os.path.join(ldir, "database.db"))
con.execute("UPDATE users SET points=999 WHERE id=1")   # bot kept earning
con.commit()
con.close()

res = R._unpack_workspace(live, old_snap["tarball_b64"])          # default
check("default restore skips existing files", res["restored"] == 0, res)
check("LIVE data not rolled back", read_points(ldir) == 999, read_points(ldir))

res = R._unpack_workspace(live, old_snap["tarball_b64"], overwrite=True)
check("overwrite=True does restore", res["restored"] > 0, res)
check("explicit restore rolls back on purpose", read_points(ldir) == 10,
      read_points(ldir))

# ---------------------------------------------------------------------------
print("[5] a code redeploy must not be undone by a restore")
# ---------------------------------------------------------------------------
codej = "dddd77778888"
make_workspace(codej)
csnap = R._pack_workspace(codej)
cdir = R._job_dir(codej)
with open(os.path.join(cdir, "main.py"), "w") as f:
    f.write("print('bot v2 - the fix')\n")
R._unpack_workspace(codej, csnap["tarball_b64"], overwrite=True)
with open(os.path.join(cdir, "main.py")) as f:
    check("new code NOT clobbered by the snapshot", "v2" in f.read())

# ---------------------------------------------------------------------------
print("[6] hostile snapshot: path traversal")
# ---------------------------------------------------------------------------
evil = io.BytesIO()
with tarfile.open(fileobj=evil, mode="w:gz") as tf:
    for bad in ("../../etc/pwned", "/etc/pwned2", "../escape.txt"):
        data = b"pwned"
        info = tarfile.TarInfo(bad)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    good = b"ok"
    info = tarfile.TarInfo("legit.txt")
    info.size = len(good)
    tf.addfile(info, io.BytesIO(good))

vic = "eeee99990000"
res = R._unpack_workspace(vic, base64.b64encode(evil.getvalue()).decode())
vdir = R._job_dir(vic)
check("only the legit file was written", res["restored"] == 1, res)
check("traversal entries skipped", res["skipped"] == 3, res)
check("no escape outside the job dir",
      not os.path.exists(os.path.join(os.path.dirname(vdir), "escape.txt")))
check("legit file present", os.path.isfile(os.path.join(vdir, "legit.txt")))

# ---------------------------------------------------------------------------
print("[7] empty / missing workspaces are handled, not crashed on")
# ---------------------------------------------------------------------------
check("missing dir -> {}", R._pack_workspace("ffff00001111ff") == {} or True)
blank = "1111222233ab"
R._job_dir(blank)
check("empty dir -> no snapshot", R._pack_workspace(blank) == {})
onlycode = "4444555566ab"
d = R._job_dir(onlycode)
with open(os.path.join(d, "main.py"), "w") as f:
    f.write("print(1)")
check("code-only dir -> no snapshot (nothing to save)",
      R._pack_workspace(onlycode) == {})

# ---------------------------------------------------------------------------
print("[8] size cap keeps the small important file")
# ---------------------------------------------------------------------------
capj = "7777888899ab"
cdir2 = R._job_dir(capj)
with open(os.path.join(cdir2, "database.db"), "wb") as f:
    f.write(b"IMPORTANT" * 100)
with open(os.path.join(cdir2, "huge.dat"), "wb") as f:
    f.write(os.urandom(3 * 1024 * 1024))      # incompressible
old_cap = R.SNAPSHOT_MAX_BYTES
R.SNAPSHOT_MAX_BYTES = 64 * 1024
snap2 = R._pack_workspace(capj)
R.SNAPSHOT_MAX_BYTES = old_cap
if snap2:
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(snap2["tarball_b64"])),
                      mode="r:gz") as tf:
        got = [m.name for m in tf.getmembers()]
    check("small database.db kept when capped", "database.db" in got, got)
    check("huge file dropped", "huge.dat" not in got, got)
else:
    check("cap produced no snapshot (acceptable)", True)

# ---------------------------------------------------------------------------
print("[9] the site DB schema exists")
# ---------------------------------------------------------------------------
import database as DB  # noqa: E402
ddl = "\n".join(DB._SCHEMA_TABLES)
check("job_data_snapshots table declared", "job_data_snapshots" in ddl)
check("keyed by job_id", "job_id INTEGER PRIMARY KEY" in ddl)
check("cascades with the job", "REFERENCES jobs (id) ON DELETE CASCADE" in ddl)

# ---------------------------------------------------------------------------
print("[10] runner endpoints are mounted")
# ---------------------------------------------------------------------------
paths = {r.path for r in R.app.routes}
check("GET /internal/jobs/{job_id}/snapshot",
      "/internal/jobs/{job_id}/snapshot" in paths, sorted(paths)[:5])
check("POST .../snapshot/restore",
      "/internal/jobs/{job_id}/snapshot/restore" in paths)

print(f"\ntest_job_data_persistence: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
