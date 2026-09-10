"""The Telegram bot as a control surface for apps created in the Mini App.

CODE NEVER ARRIVES THROUGH CHAT any more. The bot used to accept a pasted
snippet; that path is removed because a Telegram message caps at ~4096
characters and offers no editor, so it could only serve toy scripts while
looking like a real way to work. Apps are created in the Mini App and the
website — one UI, one create path. The bot manages what exists.

So these tests create apps the way the product now does (POST /api/jobs, the
web path the Mini App uses) and then drive the bot against them.

WHAT WAS MEASURED BEFORE THIS
-----------------------------
    bot deploys a job  ->  rows in jobs table         : 0
                           jobs visible in /admin/jobs: 0
                           runner actually running     : 1

    admin overview telegram keys : NONE
    /admin/users row telegram    : NONE
    bot commands                 : /code /link /ping /start /unlink
    crash notifications          : none

So a bot-deployed app burned memory while being invisible to the console,
exempt from MAX_JOBS_PER_USER, and absent from its owner's dashboard. Two
deploy paths meant two sets of rules and only one was enforced.

Everything here drives the REAL functions with a REAL spawned process, not
fixtures — the whole point is that the bot and the website now share one path.

Run:  DATA_DIR=$(mktemp -d) python3 tests/test_bot_ops.py
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATA_DIR", _tmp)
os.environ["DB_PATH"] = os.path.join(_tmp, "botops.db")
os.environ.setdefault("RUNNER_SERVICE_SECRET", "test-secret")
os.environ.setdefault("TELEGRAM_PING_BOT_TOKEN", "fake-token")
os.environ.setdefault("LIVE_PORT_MIN", "17400")
os.environ.setdefault("LIVE_PORT_MAX", "17499")

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import database as DB  # noqa: E402
DB.init_db()
import app as A  # noqa: E402
import runner.app as R  # noqa: E402
from routes.deps import now_utc_str  # noqa: E402
from services import bot_ops, bot_notify, runner_client  # noqa: E402
import services.pingbot as PB  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -> {extra}" if extra else ""))


PW = "Passw0rd!x"
_h = bcrypt.hashpw(PW.encode(), bcrypt.gensalt()).decode()
conn = DB.get_db_connection()
conn.execute("INSERT INTO users (username,email,password,is_verified,is_admin,"
             "telegram_id,telegram_name,created_at,updated_at) "
             "VALUES (?,?,?,1,1,?,?,?,?)",
             ("boss", "boss@gmail.com", _h, 555, "@bosstg",
              now_utc_str(), now_utc_str()))
conn.execute("INSERT INTO users (username,email,password,is_verified,"
             "created_at,updated_at) VALUES (?,?,?,1,?,?)",
             ("other", "other@gmail.com", _h, now_utc_str(), now_utc_str()))
conn.commit()
conn.close()

c = TestClient(A.app, raise_server_exceptions=False)
AT = (c.post("/login", json={"username": "boss", "password": PW}).json() or {}).get("token")
AH = {"Authorization": "Bearer " + AT}

SENT = []
PB._tg = lambda m, **p: (SENT.append((m, p)), {"ok": True})[1]
BOSS = {"id": 1, "username": "boss"}
CHAT = 555

LOOP = "import time\nprint('alive', flush=True)\nwhile True:\n    time.sleep(1)\n"


def last_text():
    for m, p in reversed(SENT):
        if m == "sendMessage":
            return p.get("text", "")
    return ""


def kill_all():
    for j in list(R._jobs.values()):
        try:
            j["proc"].kill()
        except Exception:
            pass
    runner_client._fleet_cache.update(at=0.0, jobs=None)


# ---------------------------------------------------------------------------
print("\n[1] the bot sees apps created the way the product creates them")
# ---------------------------------------------------------------------------
# The Mini App IS the website, so it posts to /api/jobs. Anything the bot can
# see must come from there — there is no second create path left.
r = c.post("/api/jobs", headers=AH,
           json={"name": "My-Bot", "language": "python", "code": LOOP})
check("the web/Mini App path creates the app", r.status_code in (200, 201),
      str(r.status_code) + r.text[:100])
time.sleep(3)

conn = DB.get_db_connection()
rows = [dict(r) for r in conn.execute("SELECT * FROM jobs").fetchall()]
conn.close()
check("it is a real row in the jobs table", len(rows) == 1, str(len(rows)))
check("owned by the account", rows and rows[0]["user_id"] == 1)
check("the chosen name is kept", rows and rows[0]["name"] == "My-Bot",
      str(rows and rows[0]["name"]))
check("the runner id is recorded", rows and rows[0]["runner_job_id"])

apps = bot_ops.list_apps(1)
check("the BOT can see the same app", len(apps) == 1 and apps[0]["name"] == "My-Bot",
      str([a["name"] for a in apps]))
check("with live status", apps and apps[0]["status"] == "running",
      str(apps and apps[0]["status"]))

admin_jobs = c.get("/admin/jobs", headers=AH).json()["jobs"]
check("the admin console sees it too", len(admin_jobs) == 1, str(len(admin_jobs)))
check("with a live status from the runner",
      admin_jobs and admin_jobs[0]["live_status"] == "running",
      str(admin_jobs and admin_jobs[0].get("live_status")))
check("and real measured memory", (admin_jobs[0].get("mem_mb") or 0) > 0)
check("the owner is named", admin_jobs[0]["owner"] == "boss")
check("and their Telegram account is named",
      admin_jobs[0].get("owner_telegram_name") == "@bosstg",
      str(admin_jobs[0].get("owner_telegram_name")))

# ---------------------------------------------------------------------------
print("[2] the per-account cap applies to the bot too")
# ---------------------------------------------------------------------------
check("one app counts as one", bot_ops.active_count(1) == 1, str(bot_ops.active_count(1)))
codes = []
for i in range(bot_ops.MAX_JOBS_PER_USER + 2):
    rr = c.post("/api/jobs", headers=AH,
                json={"name": f"filler{i}", "language": "python", "code": LOOP})
    codes.append(rr.status_code)
    if rr.status_code in (200, 201):
        time.sleep(1)
check("the cap refuses the extras", 429 in codes, str(codes))
check("never more than the cap is alive",
      bot_ops.active_count(1) <= bot_ops.MAX_JOBS_PER_USER,
      str(bot_ops.active_count(1)))
# The bot READS the same constant, so its "slots" line cannot drift from the
# limit the create path actually enforces.
check("the bot reports the same ceiling",
      bot_ops.MAX_JOBS_PER_USER == __import__("services.runner_client",
                                              fromlist=["x"]).MAX_JOBS_PER_USER)

conn = DB.get_db_connection()
_fillers = [dict(x)["name"] for x in
            conn.execute("SELECT name FROM jobs WHERE name LIKE 'filler%'").fetchall()]
conn.close()
for nm in _fillers:
    bot_ops.delete(1, nm)
runner_client._fleet_cache.update(at=0.0, jobs=None)

# ---------------------------------------------------------------------------
print("[3] listing, status, logs")
# ---------------------------------------------------------------------------
SENT.clear()
PB.cmd_apps(CHAT, BOSS)
t = last_text()
check("the list names the app", "My-Bot" in t, t[:120])
check("with its live state", "running" in t, t[:120])
check("and its memory", "MB" in t, t[:160])
check("the slot budget is shown", str(bot_ops.MAX_JOBS_PER_USER) in t, t[:80])

SENT.clear()
PB.cmd_status(CHAT, BOSS, "My-Bot")
t = last_text()
check("per-app status reports memory now AND peak", "peak" in t, t[:200])
check("and the restart count", "Restarts" in t, t[:220])
check("env VALUES are never shown, only key names",
      "Env keys" in t or "env" not in t.lower(), t[:220])

SENT.clear()
PB.cmd_logs(CHAT, BOSS, "My-Bot")
t = last_text()
check("logs reach the chat", "alive" in t, t[:160])
check("wrapped so Telegram renders them as a block", "```" in t)

SENT.clear()
PB.cmd_status(CHAT, BOSS)
t = last_text()
check("the account summary counts apps", "Apps:" in t, t[:120])
check("and totals their memory", "Memory in use" in t, t[:160])

# ---------------------------------------------------------------------------
print("[4] rename works; editing code from chat does not exist")
# ---------------------------------------------------------------------------
SENT.clear()
PB.cmd_rename(CHAT, BOSS, "My-Bot renamed-bot")
check("rename reports both names",
      "My-Bot" in last_text() and "renamed-bot" in last_text(), last_text())
check("the row really changed", bot_ops.find_app(1, "renamed-bot") is not None)

conn = DB.get_db_connection()
before_id = dict(conn.execute(
    "SELECT id FROM jobs WHERE name='renamed-bot'").fetchone())["id"]
conn.close()

check("there is no /update command", not hasattr(PB, "cmd_update"))
check("and no code-replacing helper behind it",
      not hasattr(bot_ops, "update_code"))
# Editing happens in the Mini App, which uses the site's own routes.
check("the site still exposes the app for editing there",
      c.get("/api/jobs", headers=AH).status_code == 200)

# ---------------------------------------------------------------------------
print("[5] one user cannot touch another's app")
# ---------------------------------------------------------------------------
OTHER = {"id": 2, "username": "other"}
check("find_app is scoped to the owner", bot_ops.find_app(2, "renamed-bot") is None)
res = bot_ops.restart(2, "renamed-bot")
check("restart refuses", res["ok"] is False, str(res))
res = bot_ops.delete(2, "renamed-bot")
check("delete refuses", res["ok"] is False, str(res))
check("and the app is untouched", bot_ops.find_app(1, "renamed-bot") is not None)

# Buttons carry an id an attacker can forge, so the callback must re-scope.
SENT.clear()
PB.handle_callback(999999, f"restart:{before_id}")
check("a button press from an UNLINKED chat does nothing", not SENT, str(SENT))

# ---------------------------------------------------------------------------
print("[6] the owner is told when an app stops on its own")
# ---------------------------------------------------------------------------
runner_client._fleet_cache.update(at=0.0, jobs=None)
bot_notify._last_state.clear()
bot_notify._last_alert.clear()
bot_notify._primed = False

first = bot_notify.check_once()
check("the first sweep records state silently", first["alerts"] == 0, str(first))
check("but it did look at the app", first["checked"] >= 1, str(first))

for j in list(R._jobs.values()):
    try:
        j["proc"].kill()
    except Exception:
        pass
    j["status"] = "crashed"
time.sleep(1)
runner_client._fleet_cache.update(at=0.0, jobs=None)

SENT.clear()
second = bot_notify.check_once()
check("a crash produces exactly one message", second["alerts"] == 1, str(second))
t = last_text()
check("it names the app", "renamed-bot" in t, t[:120])
check("it explains why in plain words", "stopped" in t.lower(), t[:120])
check("and offers the next step", "/logs" in t and "/restart" in t, t[:160])

# A crash-looping app must not turn into a stream of messages.
SENT.clear()
third = bot_notify.check_once()
check("a steady state sends nothing", third["alerts"] == 0, str(third))
bot_notify._last_state["nonexistent"] = "running"
SENT.clear()
runner_client._fleet_cache.update(at=0.0, jobs=None)
bot_notify.check_once()
check("and the cool-off suppresses a repeat of the same alert",
      not any("renamed-bot" in p.get("text", "") for m, p in SENT), str(SENT))

# An unlinked owner has nowhere to send to; it must be skipped, not crash.
conn = DB.get_db_connection()
conn.execute("UPDATE users SET telegram_id = NULL WHERE id = 1")
conn.commit()
conn.close()
check("an unlinked owner is skipped entirely",
      bot_notify.check_once()["checked"] == 0)
check("notify_owner also declines", bot_notify.notify_owner(1, "hi") is False)
conn = DB.get_db_connection()
conn.execute("UPDATE users SET telegram_id = 555 WHERE id = 1")
conn.commit()
conn.close()

# A suspended account must not keep receiving alerts about its jobs.
conn = DB.get_db_connection()
conn.execute("UPDATE users SET is_suspended = 1 WHERE id = 1")
conn.commit()
conn.close()
check("a suspended owner gets no alerts", bot_notify.check_once()["checked"] == 0)
conn = DB.get_db_connection()
conn.execute("UPDATE users SET is_suspended = 0 WHERE id = 1")
conn.commit()
conn.close()

# ---------------------------------------------------------------------------
print("[7] disconnecting says what it does and does NOT do")
# ---------------------------------------------------------------------------
SENT.clear()
PB.handle_unlink(CHAT)
t = last_text()
check("the user is told the bot is disconnected", "Disconnected" in t, t[:120])
check("and that their apps keep running — the scary part is answered",
      "keep running" in t.lower(), t[:160])
check("there is no half-finished code state left to leak",
      not hasattr(PB, "waiting_for_code") and not hasattr(PB, "pending_update"))

# ---------------------------------------------------------------------------
print("[8] admin console carries the Telegram picture")
# ---------------------------------------------------------------------------
conn = DB.get_db_connection()
conn.execute("UPDATE users SET telegram_id = 555, telegram_name = '@bosstg' WHERE id = 1")
conn.commit()
conn.close()

ov = c.get("/admin/overview", headers=AH).json()
check("the overview counts linked accounts", ov.get("telegram_linked") == 1,
      str(ov.get("telegram_linked")))
users = c.get("/admin/users", headers=AH).json()["users"]
boss = [u for u in users if u["username"] == "boss"][0]
check("the user list carries the chat id", boss.get("telegram_id") == 555)
check("and the recognisable handle", boss.get("telegram_name") == "@bosstg")
other = [u for u in users if u["username"] == "other"][0]
check("an unlinked user shows nothing rather than a stale value",
      not other.get("telegram_id"))

det = c.get("/admin/users/1", headers=AH).json()
check("the drill-down names the Telegram account",
      det["user"].get("telegram_name") == "@bosstg", str(det["user"].get("telegram_name")))

jobs = c.get("/admin/jobs", headers=AH).json()["jobs"]
check("bot apps are still listed after all of this", len(jobs) == 1, str(len(jobs)))
jd = c.get(f"/admin/jobs/{jobs[0]['id']}", headers=AH).json()
check("job detail names the owner's Telegram",
      jd["job"].get("owner_telegram_name") == "@bosstg",
      str(jd["job"].get("owner_telegram_name")))
check("and the app's own log is readable there",
      "version two" in jd["logs"] or "alive" in jd["logs"], jd["logs"][:120])

# ---------------------------------------------------------------------------
print("[9] deletion is complete")
# ---------------------------------------------------------------------------
SENT.clear()
PB.cmd_delete(CHAT, BOSS, "renamed-bot") if bot_ops.find_app(1, "renamed-bot") else None
res = bot_ops.delete(1, "renamed-bot")
check("the row is gone", bot_ops.find_app(1, "renamed-bot") is None)
check("so the admin console stops listing it",
      len(c.get("/admin/jobs", headers=AH).json()["jobs"]) == 0,
      str(len(c.get("/admin/jobs", headers=AH).json()["jobs"])))
check("and the slot is freed", bot_ops.active_count(1) == 0, str(bot_ops.active_count(1)))

# ---------------------------------------------------------------------------
print("[10] every command is behind the account gate")
# ---------------------------------------------------------------------------
src = open(os.path.join(ROOT, "services/pingbot.py"), encoding="utf-8").read()
for cmd in ("/apps", "/status", "/logs", "/restart", "/stop", "/delete",
            "/rename"):
    seg = src.split(f'text.startswith("{cmd}")', 1)
    check(f"{cmd} exists", len(seg) > 1)
    if len(seg) > 1:
        check(f"{cmd} requires a linked account",
              "_require_link(chat_id)" in seg[1][:200], seg[1][:120])
check("callbacks re-resolve the user before acting",
      "user = telegram_link.user_for_chat(chat_id)" in
      src.split("def handle_callback", 1)[1][:600])
check("the bot cannot create a job at all",
      '"/internal/jobs"' not in src)
check("nor can bot_ops",
      '"/internal/jobs"' not in open(os.path.join(ROOT, "services/bot_ops.py"),
                                     encoding="utf-8").read())

kill_all()
print(f"\ntest_bot_ops: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
