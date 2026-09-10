"""THE 'YOUR TOKEN IS OUT OF DATE' VERDICT WAS STRUCTURALLY WRONG.

Reported: a new bot was created, the token was saved in Render, the bot runs —
and the Mini App still answers

    "The server's Telegram token is out of date. If you own this site: copy
     the API Token again from @BotFather and update BOT_TOKEN."

with this in the log:

    miniapp bad_hash: bot_id=8221572217 fields=['auth_date','query_id','user']
                      lengths={...} culprit=None age_s=8
    TELEGRAM TOKEN IS STALE OR WRONG ...

WHY THE ADVICE COULD NEVER HELP. The 503 fired on

    _tok_ok and _id_agrees and culprit is None and age < 300

where _id_agrees compared str(getMe(OUR token).id) against the id parsed out
of OUR OWN token. Both sides come from the same token and Telegram can only
answer getMe with the id inside the token it was called with, so _id_agrees is
a TAUTOLOGY — True for every live token, never able to detect anything.

The consequences, all reproduced end to end before being fixed:

  * ANY fresh bad_hash from a well-formed live token was reported as a stale
    token, whatever the real cause was;
  * the `hint` built immediately above — which NAMES the bot this server
    accepts, the one actionable fact — was unreachable;
  * getMe had just returned ok=True, i.e. Telegram had confirmed the token is
    LIVE, at the moment we told the owner it was revoked. A genuinely revoked
    token answers getMe with 401 and is already reported as
    rejected_by_telegram at boot, so the real case never reached this branch.

WHAT THE FIELD SET SAYS, AND WHY IT IS NOW USED. Telegram sends query_id only
when the Mini App is launched from a button inside a chat message; the menu
button and t.me links send chat_type/chat_instance instead. The failing
payload carried query_id — so it came from a MESSAGE BUTTON, and after
switching bots the likeliest such button is an old message from the OLD bot,
still sitting in the chat and still tappable, still signed with the old
token. That is the actual failure, and it is fixed by opening the new bot,
not by re-copying anything.
"""
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

_tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp
os.environ["DB_PATH"] = os.path.join(_tmp, "bh.db")
os.environ["LIVE_PORT_MIN"] = "17900"
os.environ["LIVE_PORT_MAX"] = "17999"

SERVER_BOT_ID = "8221572217"
SERVER_TOKEN = SERVER_BOT_ID + ":AAF_server_secret_aaaaaaaaaaaaaaaa"
OTHER_TOKEN = "7111111111:AAE_other_secret_bbbbbbbbbbbbbbbb"
os.environ["BOT_TOKEN"] = SERVER_TOKEN
os.environ.pop("TELEGRAM_PING_BOT_TOKEN", None)

from fastapi.testclient import TestClient  # noqa: E402
import app as APP  # noqa: E402
from services import miniapp_auth  # noqa: E402

_pass, _fail = 0, 0


def check(name, cond, extra=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  ok   {name}")
    else:
        _fail += 1
        print(f"  FAIL {name}" + (f" -> {extra}" if extra else ""))


def initdata(token, with_query_id=True):
    """Real Telegram initData, signed the way Telegram signs it."""
    user = {"id": 6543210, "first_name": "Ahad", "username": "ahad_r",
            "language_code": "bn"}
    f = {"user": json.dumps(user, separators=(",", ":")),
         "auth_date": str(int(time.time()))}
    if with_query_id:
        f["query_id"] = "AAHdF6IQAAAAAN0XohDhrOrc"       # message button
    else:
        f["chat_type"] = "sender"                        # menu button / link
        f["chat_instance"] = "-1234567890123456789"
    dcs = "\n".join(f"{k}={f[k]}" for k in sorted(f))
    sec = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(sec, dcs.encode(), hashlib.sha256).hexdigest()
    return "&".join(f"{k}={quote(f[k], safe='')}" for k in sorted(f)) + f"&hash={h}"


# getMe is a network call the sandbox cannot make. Simulate the ONLY answer
# Telegram can give for a live token: the id inside that very token. That is
# the whole point — the old code treated this tautology as evidence.
miniapp_auth.whoami = lambda timeout_s=6.0: {
    "ok": True, "bot_id": int(miniapp_auth._bot_token().split(":")[0]),
    "username": "CodeNestNewBot"}
APP._BOT_IDENTITY.update(checked=False, value=None)
client = TestClient(APP.app)


# ---------------------------------------------------------------------------
print("[1] a payload from ANOTHER bot is not blamed on our token")
# ---------------------------------------------------------------------------
r = client.post("/auth/telegram/miniapp",
                json={"init_data": initdata(OTHER_TOKEN), "init_data_alt": []})
detail = r.json().get("detail", "")

check("it is a 400 (bad request), not a 503 'server misconfigured'",
      r.status_code == 400, f"HTTP {r.status_code}")
check("it does NOT tell the owner to re-copy a working token",
      "out of date" not in detail.lower()
      and "copy the api token" not in detail.lower(), detail)
check("it names the bot this server DOES accept",
      "@CodeNestNewBot" in detail, detail)
check("and says what to do about it",
      "/start" in detail, detail)


# ---------------------------------------------------------------------------
print("[2] the tautology is gone from the code")
# ---------------------------------------------------------------------------
SRC = open(os.path.join(ROOT, "routes/auth.py"), encoding="utf-8").read()
_live = "\n".join(l for l in SRC.splitlines() if not l.strip().startswith("#"))

check("no branch still compares getMe's id to our own token's id",
      "_id_agrees" not in _live)
check("the 503 'token is out of date' response is gone",
      "token is out of date" not in _live)
check("the misleading log line is gone",
      "TOKEN IS STALE OR WRONG" not in _live)


# ---------------------------------------------------------------------------
print("[3] the launch surface is reported, because it names the culprit")
# ---------------------------------------------------------------------------
check("a query_id payload is identified as a message button",
      "query_id" in _live and "OLD MESSAGE BUTTON" in _live)
check("a menu-button/link payload gets the other explanation",
      "SIGNED BY A DIFFERENT BOT" in _live)

# Both launch surfaces must still fail closed — this is authentication.
r2 = client.post("/auth/telegram/miniapp",
                 json={"init_data": initdata(OTHER_TOKEN, with_query_id=False),
                       "init_data_alt": []})
check("a menu-button payload from another bot is still rejected",
      r2.status_code == 400, f"HTTP {r2.status_code}")


# ---------------------------------------------------------------------------
print("[4] a correctly signed payload still works (no security loosening)")
# ---------------------------------------------------------------------------
r3 = client.post("/auth/telegram/miniapp",
                 json={"init_data": initdata(SERVER_TOKEN), "init_data_alt": []})
check("our own bot's payload signs in", r3.status_code == 200,
      f"HTTP {r3.status_code} {r3.text[:120]}")
check("and it returns a session token", bool(r3.json().get("token")))

# Tampering must still fail: the fix must not have widened what is accepted.
good = initdata(SERVER_TOKEN)
tampered = good.replace("6543210", "6543211")
r4 = client.post("/auth/telegram/miniapp",
                 json={"init_data": tampered, "init_data_alt": []})
check("a tampered payload is still refused", r4.status_code == 400,
      f"HTTP {r4.status_code}")


# ---------------------------------------------------------------------------
print("[5] two token env vars holding different bots is reported")
# ---------------------------------------------------------------------------
# BOT_TOKEN silently outranks TELEGRAM_PING_BOT_TOKEN, but render.yaml
# documents only the latter — so replacing the bot by editing the documented
# name, with a stale BOT_TOKEN still present, keeps the OLD bot in force and
# nothing said so.
os.environ["BOT_TOKEN"] = OTHER_TOKEN
os.environ["TELEGRAM_PING_BOT_TOKEN"] = SERVER_TOKEN
src = miniapp_auth.token_sources()
check("the conflict is detected", src["conflict"] is True, str(src))
check("and it reports which one actually wins",
      src["used"] == "BOT_TOKEN"
      and src["bot_ids"]["BOT_TOKEN"] == OTHER_TOKEN.split(":")[0], str(src))
check("only the PUBLIC bot-id half is exposed",
      not any(":" in str(v) for v in src["bot_ids"].values()), str(src))

os.environ["BOT_TOKEN"] = SERVER_TOKEN
os.environ["TELEGRAM_PING_BOT_TOKEN"] = SERVER_TOKEN
check("the same bot in both names is NOT a conflict",
      miniapp_auth.token_sources()["conflict"] is False)
os.environ.pop("TELEGRAM_PING_BOT_TOKEN", None)

BSRC = open(os.path.join(ROOT, "services/pingbot.py"), encoding="utf-8").read()
check("the bot warns about it at boot", "TWO DIFFERENT BOT TOKENS" in BSRC)
ASRC = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
check("/health exposes it too", "telegram_token_source" in ASRC)


# ---------------------------------------------------------------------------
print("[6] the Mini App offers a way OUT, not just a failing retry")
# ---------------------------------------------------------------------------
PRO = open(os.path.join(ROOT, "static/pro.js"), encoding="utf-8").read()
check("_tgFatal can render a link to the correct bot", "tgFatalGo" in PRO)
check("the @username is taken from the server's own message",
      re.search(r"match\(\s*/@\(\[A-Za-z0-9_\]", PRO) is not None)
check("it opens the chat inside Telegram, not inside the webview",
      "openTelegramLink" in PRO)
check("'Try again' stops being the primary action when it cannot help",
      'btn.className = "btn-ghost"' in PRO)

CSS = open(os.path.join(ROOT, "static/app.css"), encoding="utf-8").read()
check("the link is styled as a button (it is an <a>)",
      "a.btn-primary" in CSS and ".tg-fatal [hidden]" in CSS)


print(f"\ntest_badhash_verdict: {_pass} passed, {_fail} failed")
sys.exit(1 if _fail else 0)
