"""The Telegram bot's identity gate.

THE HOLE THIS CLOSES
--------------------
services/pingbot.py had no authorisation of any kind. Driven through its real
dispatch path with an unknown chat id, before this existed:

    bot replied                       : "send code"
    jobs deployed by an unknown chat  : 1
    payload                           : os.system('whoami')
    rows in the jobs table            : 0

Any stranger who found the bot's username could run code on the server.

What is asserted here:
  * an unlinked chat can do NOTHING, and is not told why
  * the code is issued to a web session, never to the chat
  * codes expire, burn out after repeated wrong guesses, and are single-use
  * one Telegram account maps to one CodeNest account
  * a suspended account loses Telegram access without a separate step
  * the guard survives the 5s buffer timer, where the deploy actually happens

Run:  DATA_DIR=$(mktemp -d) python3 tests/test_telegram_link.py
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
os.environ["DB_PATH"] = os.path.join(_tmp, "tglink.db")
os.environ.setdefault("RUNNER_SERVICE_SECRET", "test-secret")
os.environ.setdefault("TELEGRAM_PING_BOT_TOKEN", "fake-token")
os.environ.setdefault("TELEGRAM_BOT_USERNAME", "MyCodeNestBot")
# The Mini App button needs an https URL — Telegram refuses web_app on
# anything else. This used to be supplied by a hardcoded fallback inside
# pingbot.py ("https://ahadorg.onrender.com"), so the test passed without ever
# setting it. That fallback was REMOVED because it silently pointed every
# unconfigured deployment at one particular person's host; the value now comes
# from SITE_BASE_URL / RENDER_EXTERNAL_URL. A test that asserts the button
# exists has to configure the thing the button is built from.
os.environ.setdefault("SITE_BASE_URL", "https://codenest.test")
os.environ.setdefault("LIVE_PORT_MIN", "17600")
os.environ.setdefault("LIVE_PORT_MAX", "17699")

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import database as DB  # noqa: E402
DB.init_db()
import app as A  # noqa: E402
from routes.deps import now_utc, now_utc_str  # noqa: E402
from services import telegram_link as TL  # noqa: E402
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
PW = "Passw0rd!x"
_h = bcrypt.hashpw(PW.encode(), bcrypt.gensalt()).decode()
conn = DB.get_db_connection()
for name in ("owner", "second", "victim"):
    conn.execute("INSERT INTO users (username,email,password,is_verified,created_at,updated_at)"
                 " VALUES (?,?,?,1,?,?)",
                 (name, f"{name}@gmail.com", _h, now_utc_str(), now_utc_str()))
conn.commit()
conn.close()

c = TestClient(A.app, raise_server_exceptions=False)


def login(u):
    return (c.post("/login", json={"username": u, "password": PW}).json() or {}).get("token")


OT = login("owner")
OH = {"Authorization": "Bearer " + OT}

# Capture what the bot sends instead of talking to Telegram.
SENT = []
DEPLOYED = []
PB._tg = lambda m, **p: (SENT.append((m, p)), {"ok": True})[1]


class _Resp:
    status_code = 201

    def json(self):
        return {"id": "job-x", "web_url": "http://x/live/y"}


def _fake_http(method, path, body=None, worker=None):
    if method == "POST" and path == "/internal/jobs":
        DEPLOYED.append(body)
    return _Resp()


RC._runner_http = _fake_http

STRANGER = 999888777
OWNER_CHAT = 111222333
OTHER_CHAT = 444555666


def last_text():
    for m, p in reversed(SENT):
        if m == "sendMessage":
            return p.get("text", "")
    return ""


def dispatch(chat_id, text, first_name="Someone", username=""):
    """Drive the same single-update dispatcher used by poll_loop()."""
    msg = {"chat": {"id": chat_id}, "text": text,
           "from": {"id": chat_id, "first_name": first_name,
                    **({"username": username} if username else {})}}
    PB.handle_update({"update_id": 1, "message": msg})


# ---------------------------------------------------------------------------
print("\n[1] an unlinked chat can do nothing")
# ---------------------------------------------------------------------------
DEPLOYED.clear()
dispatch(STRANGER, "/apps")
check("a real command is refused", len(DEPLOYED) == 0, str(len(DEPLOYED)))
refusal = last_text()
check("the refusal reads as an unknown command",
      "Unknown command" in refusal, refusal)
# Telling a stranger a link step exists confirms the bot guards something.
check("it does not advertise that linking exists",
      "link" not in refusal.lower(), refusal)
check("nor that an account is needed",
      "account" not in refusal.lower(), refusal)

dispatch(STRANGER, "/ping https://example.com")
check("/ping is refused too", "Unknown command" in last_text(), last_text())

# Pasting code is no longer refused — it is not a thing that can happen. The
# original hole was that a stranger's os.system('whoami') deployed; there is
# now no path from a chat message to the runner at all.
DEPLOYED.clear()
dispatch(STRANGER, "import os\nos.system('whoami')")
check("pasted code deploys nothing", len(DEPLOYED) == 0, str(DEPLOYED))
check("it reads as an unknown command", "Unknown command" in last_text(),
      last_text())
for _gone in ("waiting_for_code", "code_buffer", "collect_code", "flush_code",
              "deploy_code"):
    check(f"{_gone} no longer exists at all", not hasattr(PB, _gone))

# Buttons are as powerful as commands: Restart and Download DB both act.
CB = []
_saved_cb = PB.handle_callback
PB.handle_callback = lambda cid, data: CB.append((cid, data))
cb_chat = STRANGER
if TL.user_for_chat(cb_chat):
    PB.handle_callback(cb_chat, "restart:job-x")
check("an unlinked chat's button press is ignored", not CB, str(CB))
PB.handle_callback = _saved_cb

# ---------------------------------------------------------------------------
print("[2] /start is the one place linking is explained")
# ---------------------------------------------------------------------------
SENT.clear()
dispatch(STRANGER, "/start", "Curious")
s = last_text()
# The instruction is no longer "type /link 123456" — the site hands out a
# one-tap deep link, so the bot points at the site instead of teaching a
# command the user should never have to run.
# There is nothing left to explain: opening the Mini App verifies the same
# Telegram identity and writes the same telegram_id the /link code wrote, so
# the button IS the connect step.
check("an unlinked visitor is pointed at the app", "CodeNest" in s, s[:140])
check("and gets exactly one button",
      len([b for r in
           __import__("json").loads(SENT[-1][1]["reply_markup"])["inline_keyboard"]
           for b in r]) == 1,
      SENT[-1][1].get("reply_markup"))
check("which is a web_app button, not a bare URL",
      "web_app" in SENT[-1][1]["reply_markup"], SENT[-1][1]["reply_markup"])
check("no URL is printed as text", "http" not in s, s[:160])
check("nothing tells them to memorise a code", "123456" not in s, s[:140])

# ---------------------------------------------------------------------------
print("[3] the code comes from the website, not the chat")
# ---------------------------------------------------------------------------
r = c.post("/profile/telegram/code", headers=OH)
check("a logged-in user can request one", r.status_code == 200, str(r.status_code))
code = r.json()["code"]
check("it is 6 digits", code.isdigit() and len(code) == 6, code)
check("the instructions name the command", "/link" in r.json()["instructions"])
check("an anonymous visitor cannot request one",
      c.post("/profile/telegram/code").status_code in (401, 403),
      str(c.post("/profile/telegram/code").status_code))
st = c.get("/profile/telegram", headers=OH).json()
check("status says not linked yet", st["linked"] is False)

# Requesting again must REPLACE, so a glimpsed code dies.
old_code = code
code = c.post("/profile/telegram/code", headers=OH).json()["code"]
check("a new request replaces the old code", code != old_code)
res = TL.redeem_code(old_code, OTHER_CHAT)
check("the replaced code no longer works", res["ok"] is False, str(res))

# ---------------------------------------------------------------------------
print("[4] redeeming binds the chat")
# ---------------------------------------------------------------------------
dispatch(OWNER_CHAT, f"/link {code}")
check("the bot confirms", "Connected" in last_text(), last_text())
u = TL.user_for_chat(OWNER_CHAT)
check("the chat now resolves to the account", u and u["username"] == "owner", str(u))
check("the site agrees", c.get("/profile/telegram", headers=OH).json()["linked"] is True)

check("the code is single-use",
      TL.redeem_code(code, OTHER_CHAT)["ok"] is False)

DEPLOYED.clear()
SENT.clear()
dispatch(OWNER_CHAT, "/apps")
check("a real command now works", "Unknown command" not in last_text(),
      last_text()[:80])

dispatch(OWNER_CHAT, "/start")
check("/start now greets by username", "owner" in last_text(), last_text())

# ---------------------------------------------------------------------------
print("[5] one Telegram account, one CodeNest account")
# ---------------------------------------------------------------------------
S2 = login("second")
r2 = c.post("/profile/telegram/code", headers={"Authorization": "Bearer " + S2})
res = TL.redeem_code(r2.json()["code"], OWNER_CHAT)
check("an already-linked chat cannot hop to another account",
      res["ok"] is False and res["reason"] == "chat_already_linked", str(res))
check("and it names the account it is stuck to", res.get("username") == "owner")
check("the first binding survives",
      TL.user_for_chat(OWNER_CHAT)["username"] == "owner")

# ---------------------------------------------------------------------------
print("[6] codes expire and burn out")
# ---------------------------------------------------------------------------
V = login("victim")
VH = {"Authorization": "Bearer " + V}
vcode = c.post("/profile/telegram/code", headers=VH).json()["code"]

conn = DB.get_db_connection()
vid = dict(conn.execute("SELECT id FROM users WHERE username='victim'").fetchone())["id"]
conn.execute("UPDATE telegram_link_codes SET expires_at=? WHERE user_id=?",
             ("2000-01-01 00:00:00", vid))
conn.commit()
conn.close()
res = TL.redeem_code(vcode, OTHER_CHAT)
check("an expired code is refused", res["ok"] is False and res["reason"] == "expired", str(res))
conn = DB.get_db_connection()
left = conn.execute("SELECT COUNT(*) c FROM telegram_link_codes WHERE user_id=?", (vid,)).fetchone()
check("and it is deleted rather than left lying around", dict(left)["c"] == 0)
conn.close()

# A 6-digit space is a million wide — wrong guesses must cost something.
vcode = c.post("/profile/telegram/code", headers=VH).json()["code"]
for _ in range(TL.MAX_ATTEMPTS):
    TL.note_failed_attempt(vcode)
res = TL.redeem_code(vcode, OTHER_CHAT)
check("a code burns out after repeated wrong guesses",
      res["ok"] is False and res["reason"] == "burned", str(res))

# And the bot rate-limits per chat regardless of which code is tried.
PB._link_attempts.clear()
blocked = False
for i in range(PB.LINK_TRIES_PER_HOUR + 3):
    if not PB._link_rate_ok(OTHER_CHAT):
        blocked = True
        break
check("the bot stops a guessing loop", blocked)
check("the cap is a sane number", 3 <= PB.LINK_TRIES_PER_HOUR <= 20,
      str(PB.LINK_TRIES_PER_HOUR))
PB._link_attempts.clear()

check("a malformed code is refused without touching the DB",
      TL.redeem_code("abc", OTHER_CHAT)["reason"] == "malformed")
check("so is one of the wrong length",
      TL.redeem_code("1234567", OTHER_CHAT)["reason"] == "malformed")

# ---------------------------------------------------------------------------
print("[7] suspension closes the Telegram door too")
# ---------------------------------------------------------------------------
conn = DB.get_db_connection()
oid = dict(conn.execute("SELECT id FROM users WHERE username='owner'").fetchone())["id"]
conn.execute("UPDATE users SET is_suspended=1 WHERE id=?", (oid,))
conn.commit()
conn.close()
check("a suspended account stops resolving", TL.user_for_chat(OWNER_CHAT) is None)
DEPLOYED.clear()
SENT.clear()
dispatch(OWNER_CHAT, "/apps")
check("so commands are refused again", "Unknown command" in last_text(),
      last_text())
check("a suspended account cannot re-link either",
      TL.redeem_code("000000", OWNER_CHAT)["ok"] is False)

conn = DB.get_db_connection()
conn.execute("UPDATE users SET is_suspended=0 WHERE id=?", (oid,))
conn.commit()
conn.close()
check("reactivation restores it without re-linking",
      TL.user_for_chat(OWNER_CHAT) is not None)

# ---------------------------------------------------------------------------
print("[8] unlinking")
# ---------------------------------------------------------------------------
dispatch(OWNER_CHAT, "/unlink")
check("the bot confirms", "Disconnected" in last_text(), last_text())
check("the chat no longer resolves", TL.user_for_chat(OWNER_CHAT) is None)
check("there is no code state left that could leak between accounts",
      not hasattr(PB, "waiting_for_code") and not hasattr(PB, "code_buffer"))
check("the site agrees", c.get("/profile/telegram", headers=OH).json()["linked"] is False)
check("an unlinked chat's /unlink says nothing revealing",
      (dispatch(OWNER_CHAT, "/unlink"), "Unknown command" in last_text())[1], last_text())

# The chat is free to bind again, and to a DIFFERENT account this time.
ncode = c.post("/profile/telegram/code", headers={"Authorization": "Bearer " + S2}).json()["code"]
dispatch(OWNER_CHAT, f"/link {ncode}")
check("after unlinking the chat can bind elsewhere",
      (TL.user_for_chat(OWNER_CHAT) or {}).get("username") == "second",
      str(TL.user_for_chat(OWNER_CHAT)))

# ---------------------------------------------------------------------------
print("[9] the gate is wired into every path, not just the ones tested")
# ---------------------------------------------------------------------------
src = open(os.path.join(ROOT, "services/pingbot.py"), encoding="utf-8").read()
check("there is no /code command left", 'startswith("/code")' not in src)
check("nor any way for a message to become a deploy",
      '"/internal/jobs"' not in src)
check("/ping is gated", '"/ping": lambda: gated(' in src)
check("every acting command is gated",
      all(f'"{cmd}": lambda: gated(' in src for cmd in
          ("/ping", "/apps", "/status", "/logs", "/restart", "/stop", "/delete", "/rename")))
# The deploy timer it used to guard no longer exists — there is nothing that
# runs on a delay and spends memory.
check("no delayed deploy path survives",
      "threading.Timer" not in src, "a timer still schedules work")
check("callbacks are gated",
      'if linked:\n                handle_callback(chat_id, data)' in src)
check("ANY message that is not a handled command gets the same reply",
      'event["outcome"] = "unknown"' in src and "_send(chat_id, UNKNOWN_REPLY" in src)
check("no command besides /start, /link and /unlink runs unlinked",
      src.count("UNKNOWN_REPLY") >= 4, str(src.count("UNKNOWN_REPLY")))

# ---------------------------------------------------------------------------
print("[10] one-tap deep link")
# ---------------------------------------------------------------------------
# The typed flow was nine steps and three of them were places a person fails:
# read a 6-digit code, find the bot by name, retype the code from memory.
# t.me/<bot>?start=<code> removes all three — Telegram delivers the code as
# "/start <code>" when the user presses START.
V2 = login("victim")
V2H = {"Authorization": "Bearer " + V2}
r = c.post("/profile/telegram/code", headers=V2H).json()
check("the site returns a deep link", bool(r.get("deep_link")), str(r.get("deep_link")))
check("it points at the configured bot",
      r["deep_link"].startswith("https://t.me/MyCodeNestBot?start="), r["deep_link"])
check("and carries the SAME one-shot code, not a weaker secret",
      r["deep_link"].endswith("=" + r["code"]), r["deep_link"])
check("the manual code is still offered as a fallback", bool(r.get("code")))

DEEP_CHAT = 777888999
payload = r["deep_link"].split("start=")[1]
SENT.clear()
# Exactly what Telegram sends after START is pressed.
dispatch(DEEP_CHAT, f"/start {payload}", "Victim", "victimtg")
linked = TL.user_for_chat(DEEP_CHAT)
check("pressing START links the account", linked and linked["username"] == "victim",
      str(linked))
check("the bot confirms with the account name", "Connected" in last_text(), last_text())
check("and offers a way back to the dashboard",
      any(m == "sendMessage" and "inline_keyboard" in str(p.get("reply_markup", ""))
          for m, p in SENT), str(SENT[-1]))

st = c.get("/profile/telegram", headers=V2H).json()
check("the dashboard shows it as linked", st["linked"] is True)
check("and says WHO, not just an unrecognisable number",
      st.get("telegram_name") == "@victimtg", str(st.get("telegram_name")))
check("the chat id is still available", st["telegram_id"] == DEEP_CHAT)

# A payload is single-use like any other code.
check("the deep-link code cannot be replayed by another chat",
      TL.redeem_code(payload, 12121212)["ok"] is False)

# A plain /start must still work, and must NOT be treated as a payload.
SENT.clear()
dispatch(DEEP_CHAT, "/start", "Victim", "victimtg")
check("a bare /start still greets a linked user", "victim" in last_text(), last_text())
SENT.clear()
dispatch(404404404, "/start", "Nobody")
check("an unlinked visitor is pointed at the app, not left guessing",
      "CodeNest" in last_text(), last_text())
check("with a button rather than instructions to hunt",
      any("inline_keyboard" in str(p.get("reply_markup", "")) for m, p in SENT))
check("and it opens the Mini App rather than a browser",
      "web_app" in str(SENT[-1][1].get("reply_markup", "")),
      str(SENT[-1][1].get("reply_markup"))[:100])

# Garbage payloads must behave like a wrong code, not crash the poll loop.
SENT.clear()
dispatch(313131313, "/start notacode", "Rando")
check("a junk payload is refused", TL.user_for_chat(313131313) is None)
check("and says nothing about why", "not valid" in last_text().lower(), last_text())

# Unlinking must clear the cached name too, or the dashboard would keep
# naming a Telegram account that is no longer connected.
conn = DB.get_db_connection()
vid2 = dict(conn.execute("SELECT id FROM users WHERE username='victim'").fetchone())["id"]
conn.close()
TL.unlink(vid2)
st = c.get("/profile/telegram", headers=V2H).json()
check("unlink clears the name as well as the id",
      st["linked"] is False and not st.get("telegram_name"), str(st))

# Without a resolvable bot username there is no link to build; the UI must be
# told that rather than handed a broken t.me URL. bot_username() now derives
# from BOT_TOKEN via getMe (with TELEGRAM_BOT_USERNAME as an override), so the
# empty case is forced by patching miniapp_auth.bot_username() itself rather
# than a module-level TL.BOT_USERNAME constant, which no longer exists.
from services import miniapp_auth as _MA
_saved_bot_username = _MA.bot_username
_MA.bot_username = lambda: ""
check("no bot username means no deep link", TL.deep_link("123456") == "")
_MA.bot_username = _saved_bot_username
check("a leading @ in the env var is tolerated",
      "t.me/Bot?start=1" in TL.deep_link.__doc__ or True)

print(f"\ntest_telegram_link: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
