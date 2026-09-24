"""👑 /queen — the unlimited-memory flag, end to end.

WHAT THE FLAG IS
----------------
users.mem_unlimited = 1  →  the site tells the runner mem_limit_mb = 0 for that
account's bots  →  runner/app.py's _set_limits() skips the per-job RLIMIT_AS
entirely. Nothing else about the job changes: same directory, same port, same
data. Job COUNT is a separate knob (/admin limit → job_limit_override).

WHY THIS FILE EXISTS
--------------------
The flag had a database column, a setter (telegram_link.set_unlimited_permission),
a reader (bot_ops._mem_limit_for) and a runner that honoured it — and NO command
that set it. Everything below the surface was built; the surface was missing.
So these checks are written against the paths an admin actually uses:

  * /queen <user>, /queen off <user>, /unqueen <user>, bare /queen to list —
    driven through the REAL dispatcher (handle_update), not by calling
    cmd_queen() directly. The dispatcher is where an admin command gets
    silently eaten (a link gate, a pending upload, an admin flow), and a test
    that skips it proves nothing about what a typed message does.
  * A non-admin gets NOTHING back — no reply, no change. Same posture as
    /admin and /see: the command must not even be discoverable.
  * The grant reaches bots that are ALREADY RUNNING. This was the second half
    of the bug: the runner stores a job's RLIMIT at creation, so a flag flip
    only applied to the NEXT deploy and "/queen did nothing" was a fair
    complaint. bot_ops.reapply_mem_limit() must PATCH each running job.
  * The website's deploy path sends the same value as the bot's. Two copies of
    "who is unlimited" is how the two surfaces drift apart.
  * /admin queen, /admin queens and the 👑 button on a user card all drive the
    same decision as the typed /queen.

Run:  DATA_DIR=$(mktemp -d) python3 tests/test_queen_flag.py
"""
import os
import sys
import tempfile
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# DB_PATH, not DATABASE_PATH — the wrong name writes to the repo's real
# database.db, which is how an earlier test dirtied it.
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, uuid.uuid4().hex + ".db")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("RUNNER_SERVICE_SECRET", "test-secret")
os.environ.setdefault("TELEGRAM_PING_BOT_TOKEN", "123:fake")
os.environ.setdefault("TELEGRAM_BOT_USERNAME", "MyCodeNestBot")
os.environ.setdefault("SITE_BASE_URL", "https://codenest.test")
os.environ.setdefault("LIVE_PORT_MIN", "17900")
os.environ.setdefault("LIVE_PORT_MAX", "17999")

import database as DB  # noqa: E402
DB.init_db()

from routes.deps import now_utc_str  # noqa: E402
from services import telegram_link as TL  # noqa: E402
from services import bot_ops  # noqa: E402
import services.pingbot as PB  # noqa: E402
import services.runner_client as RC  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -> {extra}" if extra else ""))


# ---- fixtures -------------------------------------------------------------
BOSS_TG = 8768764605          # pingbot.SUPER_ADMIN_TG_ID — admin without a link
ADMIN_TG = 111                # an admin who DID link an account
ALICE_TG = 222                # an ordinary linked user
STRANGER_TG = 333             # no account at all

conn = DB.get_db_connection()
now = now_utc_str()
conn.execute("INSERT INTO users (id,username,email,password,is_verified,is_admin,"
             "telegram_id,created_at,updated_at) VALUES (1,'adminuser','a@x.com','x',1,1,?,?,?)",
             (ADMIN_TG, now, now))
conn.execute("INSERT INTO users (id,username,email,password,is_verified,"
             "telegram_id,created_at,updated_at) VALUES (2,'alice','alice@x.com','x',1,?,?,?)",
             (ALICE_TG, now, now))
conn.execute("INSERT INTO users (id,username,email,password,is_verified,"
             "created_at,updated_at) VALUES (3,'bob','bob@x.com','x',1,?,?)", (now, now))
# Alice has one bot that is supposed to be running, so reapply_mem_limit has
# something to push the new ceiling to.
conn.execute("INSERT INTO jobs (id,user_id,name,language,code,runner_job_id,worker_url,"
             "desired_state,created_at,updated_at) "
             "VALUES (10,2,'alice-bot','python','print(1)','abc123',NULL,'running',?,?)",
             (now, now))
# …and one she stopped, which must be left alone.
conn.execute("INSERT INTO jobs (id,user_id,name,language,code,runner_job_id,desired_state,"
             "created_at,updated_at) VALUES (11,2,'old-bot','python','print(1)','def456',"
             "'stopped',?,?)", (now, now))
conn.commit()
conn.close()

ADMIN_ID, ALICE_ID, BOB_ID = 1, 2, 3

# Capture what the bot sends instead of talking to Telegram.
SENT = []
EDITED = []
PB._send = lambda chat_id, text, **kw: SENT.append((chat_id, text, kw))
PB._edit_or_send = lambda chat_id, message_id, text, **kw: EDITED.append((chat_id, text, kw))
PB.bot_analytics.record = lambda **event: None      # analytics is not under test here


def said(text=None):
    """Everything the bot has said so far, joined — assertions read better."""
    blob = "\n".join(str(t) for _, t, _ in SENT) + "\n" + "\n".join(str(t) for _, t, _ in EDITED)
    return blob if text is None else blob


def reset():
    SENT.clear()
    EDITED.clear()


def mem_flag(user_id):
    c = DB.get_db_connection()
    try:
        row = c.execute("SELECT mem_unlimited FROM users WHERE id=?", (user_id,)).fetchone()
        return int(row["mem_unlimited"])
    finally:
        c.close()


def msg(text, tg_id):
    return {"update_id": 1,
            "message": {"chat": {"id": tg_id}, "from": {"id": tg_id, "first_name": "T"},
                        "text": text}}


def run(text, tg_id=BOSS_TG):
    reset()
    PB.handle_update(msg(text, tg_id))
    return said()


# Track every attempt to push the flag to a running bot, without HTTP.
REAPPLIED = []
_real_reapply = bot_ops.reapply_mem_limit
bot_ops.reapply_mem_limit = lambda uid: (REAPPLIED.append(uid), 0)[1]


# ---- 1. a stranger learns nothing -----------------------------------------
out = run("/queen alice", STRANGER_TG)
check("an unlinked chat gets no reply at all", out.strip() == "", out[:120])
check("and the flag did not move", mem_flag(ALICE_ID) == 0)

out = run("/queen alice", ALICE_TG)
check("a linked NON-admin gets no reply either", out.strip() == "", out[:120])
check("and still no flag change", mem_flag(ALICE_ID) == 0)


# ---- 2. the super-admin grants it -----------------------------------------
out = run("/queen alice", BOSS_TG)
check("👑 grant is confirmed", "👑" in out, out[:160])
check("the confirmation names the user", "alice" in out, out[:160])
check("users.mem_unlimited is now 1", mem_flag(ALICE_ID) == 1)
check("the running bots were told about it", REAPPLIED == [ALICE_ID], str(REAPPLIED))
check("mem_limit_for() reports 'no ceiling'", bot_ops.mem_limit_for(ALICE_ID) == 0)
check("an ordinary user is still capped", bot_ops.mem_limit_for(BOB_ID) is None)

# Idempotent: a second grant must not pretend to change something.
REAPPLIED.clear()
out = run("/queen alice", BOSS_TG)
check("granting twice says 'already'", "already" in out.lower(), out[:160])
check("granting twice does not restart bots", REAPPLIED == [], str(REAPPLIED))
check("and the flag stays 1", mem_flag(ALICE_ID) == 1)


# ---- 3. listing, revoking, and the other spellings -------------------------
out = run("/queen", BOSS_TG)
check("bare /queen lists the queens", "alice" in out, out[:200])
check("the list says what the flag does", "memory" in out.lower(), out[:200])

out = run("/queen off alice", BOSS_TG)
check("revoke is confirmed", mem_flag(ALICE_ID) == 0, out[:160])
check("mem_limit_for() goes back to the default", bot_ops.mem_limit_for(ALICE_ID) is None)

out = run("/queen nobody-here", BOSS_TG)
check("an unknown user is reported, not swallowed", "no user found" in out.lower(), out[:160])

out = run("/queen", BOSS_TG)
check("after the revoke the list is empty", "alice" not in out, out[:200])

# /unqueen — one word shorter, same decision.
run("/queen alice", BOSS_TG)
check("re-granted before testing /unqueen", mem_flag(ALICE_ID) == 1)
out = run("/unqueen alice", BOSS_TG)
check("/unqueen revokes", mem_flag(ALICE_ID) == 0, out[:160])

# Resolving by Telegram id, the way an admin usually has it.
out = run(f"/queen {ALICE_TG}", BOSS_TG)
check("a telegram id resolves too", mem_flag(ALICE_ID) == 1, out[:160])
run("/unqueen alice", BOSS_TG)

# No argument where one is required → usage, not a silent no-op.
out = run("/queen off", BOSS_TG)
check("/queen off with no user explains itself", "usage" in out.lower(), out[:160])


# ---- 4. the linked admin, and /admin's own spellings -----------------------
out = run("/queen alice", ADMIN_TG)
check("a linked is_admin=1 account can grant it", mem_flag(ALICE_ID) == 1, out[:160])
run("/unqueen alice", ADMIN_TG)

out = run("/admin queen alice", BOSS_TG)
check("/admin queen grants", mem_flag(ALICE_ID) == 1, out[:160])
out = run("/admin queens", BOSS_TG)
check("/admin queens lists", "alice" in out, out[:200])
out = run("/admin unqueen alice", BOSS_TG)
check("/admin unqueen revokes", mem_flag(ALICE_ID) == 0, out[:160])


# ---- 5. reapply_mem_limit actually talks to the runner ---------------------
PATCHES = []


class _Resp:
    status_code = 200

    def json(self):
        return {"id": "abc123"}


def _fake_http(method, path, body=None, worker=None):
    PATCHES.append((method, path, body, worker))
    return _Resp()


RC._runner_http = _fake_http
run("/unqueen alice", BOSS_TG)                   # start from a known state: capped
check("starting from capped", mem_flag(ALICE_ID) == 0)
run("/queen alice", BOSS_TG)                     # flag on…
PATCHES.clear()
count = _real_reapply(ALICE_ID)                  # …now push it live for real
check("reapply restarted the running bot", count == 1, str(count))
check("it used PATCH on that job", PATCHES and PATCHES[0][0] == "PATCH"
      and PATCHES[0][1] == "/internal/jobs/abc123", str(PATCHES[:1]))
check("it sent 'no ceiling' (0)", PATCHES and PATCHES[0][2] == {"mem_limit_mb": 0},
      str(PATCHES[:1]))
check("the stopped bot was left alone", len(PATCHES) == 1, str(PATCHES))

run("/unqueen alice", BOSS_TG)                   # flag off (reapply is stubbed above)
PATCHES.clear()
_real_reapply(ALICE_ID)
check("revoking pushes the default back (None)",
      PATCHES and PATCHES[-1][2] == {"mem_limit_mb": None}, str(PATCHES[-1:]))
PATCHES.clear()


# ---- 6. the runner understands it -----------------------------------------
import runner.app as R  # noqa: E402

check("PATCH /internal/jobs accepts mem_limit_mb",
      "mem_limit_mb" in R.JobUpdateRequest.model_fields,
      str(sorted(R.JobUpdateRequest.model_fields)))
check("the manifest keeps it across a runner restart",
      "mem_limit_mb" in open(os.path.join(ROOT, "runner", "app.py"), encoding="utf-8").read()
      and '"mem_limit_mb": j.get("mem_limit_mb")' in
      open(os.path.join(ROOT, "runner", "app.py"), encoding="utf-8").read())
check("_job_public reports the ceiling a job was spawned under",
      R._job_public({"id": "x", "name": "n", "lang": "python", "proc": None,
                     "status": "stopped", "restarts": 0, "started_at": 0,
                     "mem_limit_mb": 0})["mem_limit_mb"] == 0)


# ---- 7. the admin panel's 👑 button ---------------------------------------
kb = PB._admin_user_row_kb({"id": ALICE_ID, "mem_unlimited": 0})
blob = str(kb)
check("a user card has a 👑 button", "admin:togqueen:%d" % ALICE_ID in blob, blob[:200])
kb2 = PB._admin_user_row_kb({"id": ALICE_ID, "mem_unlimited": 1})
check("its label flips once she is a queen", "Remove" in str(kb2), str(kb2)[:200])
check("👑 Queens is on the panel menu", "admin:queens" in str(PB._admin_menu_kb()))

REAPPLIED.clear()
TL.set_unlimited_permission(ALICE_ID, False)     # the button TOGGLES — pin the start
reset()
PB.handle_callback(BOSS_TG, f"admin:togqueen:{ALICE_ID}", None)
check("the button writes the same flag", mem_flag(ALICE_ID) == 1)
check("and pushes it to running bots", REAPPLIED == [ALICE_ID], str(REAPPLIED))
check("the card it redraws says so", "👑" in said(), said()[:200])

reset()
PB.handle_callback(BOSS_TG, "admin:queens", None)
check("the Queens view lists her", "alice" in said(), said()[:200])

reset()
PB.handle_callback(BOSS_TG, f"admin:unqueen:{ALICE_ID}", None)
check("Remove 👑 revokes", mem_flag(ALICE_ID) == 0)

reset()
PB.handle_callback(STRANGER_TG, f"admin:togqueen:{ALICE_ID}", None)
check("a stranger pressing the button is refused", "Admin only" in said(), said()[:160])
check("and the flag did not move", mem_flag(ALICE_ID) == 0)


# ---- 8. the flag survives a restart of the site ----------------------------
run("/queen alice", BOSS_TG)
check("granted before re-reading from a fresh connection", mem_flag(ALICE_ID) == 1)
fresh = TL.get_user_by_id(ALICE_ID)
check("get_user_by_id carries mem_unlimited", fresh.get("mem_unlimited") == 1, str(fresh))
rows = TL.list_admin_overview(limit=50)
alice_row = [r for r in rows if r["id"] == ALICE_ID]
check("list_admin_overview carries it too (the panel's 👑 depends on it)",
      alice_row and alice_row[0].get("mem_unlimited") == 1, str(alice_row))
check("list_queens returns exactly the queens",
      [r["id"] for r in TL.list_queens()] == [ALICE_ID], str(TL.list_queens()))


# ---- 9. the website's deploy path asks the same question -------------------
import routes.runspace as RS  # noqa: E402

check("routes/runspace has one shared reader (0 = no ceiling)",
      RS._mem_limit_for(ALICE_ID) == 0, str(RS._mem_limit_for(ALICE_ID)))
check("and it agrees with bot_ops", RS._mem_limit_for(ALICE_ID) == bot_ops.mem_limit_for(ALICE_ID))
check("an ordinary user is still None there", RS._mem_limit_for(BOB_ID) is None)
src = open(os.path.join(ROOT, "routes", "runspace.py"), encoding="utf-8").read()
check("the web editor's create sends it", src.count('"mem_limit_mb": _mem_limit_for(') >= 4,
      str(src.count('"mem_limit_mb": _mem_limit_for(')))


print(f"\ntest_queen_flag: {PASS} passed, {FAIL} failed")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
