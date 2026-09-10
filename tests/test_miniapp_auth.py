"""Telegram Mini App auto-login.

WHY A SEPARATE VERIFIER — measured, not assumed. The Login Widget and the Mini
App prove the same identity but derive the HMAC key differently. Same
data-check string, same bot token:

    Login Widget  secret = sha256(token)             -> b1a8455e4830…
    Mini App      secret = HMAC("WebAppData", token) -> 3b019fac3ba6…

So initData posted to /auth/telegram is rejected as tampered. Reusing that
route would either fail every Mini App login or, if loosened to accept both,
turn one endpoint into two trust rules.

The point of the feature is ZERO taps: if a user still has to log in, the Mini
App offers nothing over a link to the website. So the tests below assert the
whole chain — verified signature, session issued, and the SAME account as
every other door onto the platform.

Run:  DATA_DIR=$(mktemp -d) python3 tests/test_miniapp_auth.py
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from urllib.parse import urlencode, quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATA_DIR", _tmp)
os.environ["DB_PATH"] = os.path.join(_tmp, "miniapp.db")
TOKEN = "123456:AAFakeBotTokenForTests"
os.environ["TELEGRAM_PING_BOT_TOKEN"] = TOKEN
os.environ.setdefault("TELEGRAM_BOT_USERNAME", "MyCodeNestBot")
os.environ.setdefault("RUNNER_SERVICE_SECRET", "test-secret")
os.environ.setdefault("LIVE_PORT_MIN", "17300")
os.environ.setdefault("LIVE_PORT_MAX", "17399")

from fastapi.testclient import TestClient  # noqa: E402

import database as DB  # noqa: E402
DB.init_db()
import app as A  # noqa: E402
from services import miniapp_auth as MA  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -> {extra}" if extra else ""))


c = TestClient(A.app, raise_server_exceptions=False)


def init_data(uid=555, uname="ahadxyz", first="Ahad", when=None, token=TOKEN,
              extra=None, drop_user=False):
    """Build a genuinely signed initData string, exactly as Telegram does."""
    d = {"chat_instance": "-1", "chat_type": "private",
         "auth_date": str(int(when if when is not None else time.time()))}
    if not drop_user:
        u = {"id": uid, "first_name": first}
        if uname:
            u["username"] = uname
        d["user"] = json.dumps(u, separators=(",", ":"))
    if extra:
        d.update(extra)
    check_str = "\n".join(f"{k}={d[k]}" for k in sorted(d))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    d["hash"] = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
    return urlencode(d)


from routes.deps import _attempts  # noqa: E402


def login(data, fresh=True):
    """POST initData.

    The route is IP rate-limited (correctly — it is an auth endpoint), and
    this file makes dozens of calls from one client. Clearing the bucket keeps
    the test measuring verification rather than the limiter; [3b] asserts the
    limiter itself, deliberately, instead of letting it leak into every case.
    """
    if fresh:
        _attempts.clear()
    return c.post("/auth/telegram/miniapp", json={"init_data": data})


# ---------------------------------------------------------------------------
print("\n[1] the two Telegram specs really are different")
# ---------------------------------------------------------------------------
fields = {"auth_date": 1700000000, "first_name": "Ahad", "id": 555}
cs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
widget = hmac.new(hashlib.sha256(TOKEN.encode()).digest(), cs.encode(),
                  hashlib.sha256).hexdigest()
mini = hmac.new(hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest(),
                cs.encode(), hashlib.sha256).hexdigest()
check("the same data signs to two different hashes", widget != mini)
check("so a Mini App payload cannot use the widget route",
      login(urlencode({**fields, "hash": widget})).status_code == 400)

# ---------------------------------------------------------------------------
print("[2] a genuine open signs the user in with zero taps")
# ---------------------------------------------------------------------------
r = login(init_data())
check("verification succeeds", r.status_code == 200, r.text[:120])
body = r.json()
check("a session token comes back", bool(body.get("token")))
check("the account was created on first open", body.get("created") is True)
check("with a stable tg_<id> username", body.get("username") == "tg_555",
      str(body.get("username")))

# The token must be a REAL session, not a placeholder.
H = {"Authorization": "Bearer " + body["token"]}
prof = c.get("/profile", headers=H)
check("the token authenticates against the normal API", prof.status_code == 200,
      str(prof.status_code))
check("and resolves to that account", prof.json().get("username") == "tg_555")

r2 = login(init_data())
check("a second open reuses the account", r2.json().get("created") is False)
conn = DB.get_db_connection()
n = dict(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone())["c"]
conn.close()
check("no duplicate account is created", n == 1, str(n))

# ---------------------------------------------------------------------------
print("[3] forged, stale and malformed data are all refused")
# ---------------------------------------------------------------------------
good = init_data()
check("a flipped hash is rejected",
      login(good[:-1] + ("0" if good[-1] != "0" else "1")).status_code == 400)
check("data signed with another bot's token is rejected",
      login(init_data(token="999999:SomeOtherBotToken")).status_code == 400)
check("a payload with no hash is rejected",
      login(urlencode({"auth_date": str(int(time.time())), "user": "{}"})).status_code == 400)
check("an old payload cannot be replayed",
      login(init_data(when=time.time() - 90000)).status_code == 400)
check("a payload from the future is rejected",
      login(init_data(when=time.time() + 4000)).status_code == 400)
check("empty initData is rejected", login("").status_code == 400)
check("garbage is rejected, not crashed on", login("not-a-query-string").status_code == 400)

# Changing ONE character of the signed content must invalidate it — this is
# what stops someone editing the user id to log in as another account.
tampered = init_data().replace("%22id%22%3A555", "%22id%22%3A999")
check("editing the user id after signing is caught",
      login(tampered).status_code == 400, str(login(tampered).status_code))

# Every failure gets the same message. Telling a forger that the hash was fine
# but the timestamp was stale is a hint about what to fix next.
_rejects = [login(x) for x in
            (good[:-1] + ("0" if good[-1] != "0" else "1"),
             init_data(when=time.time() - 90000), "garbage")]
check("every one of them is refused",
      all(r.status_code == 400 for r in _rejects),
      str([r.status_code for r in _rejects]))
# The rule is NOT "every message is identical" — that is what made a missing
# env var indistinguishable from a forged payload and left the Mini App saying
# "Couldn't connect" with nothing to act on. The rule is that a message may
# only be specific when it tells the OPERATOR something a forger already
# knows. So: causes an attacker controls stay generic.
# A rejected signature has two indistinguishable causes: a forged payload, or
# the server holding a different bot's token. The message must name BOTH —
# blaming only the config would mislead a forger about why they failed, and
# blaming only the payload leaves an owner with nothing to check.
_bad = login(good[:-1] + ("0" if good[-1] != "0" else "1")).json().get("detail") or ""
check("a rejected signature does not claim to know which cause",
      "could not verify" in _bad.lower(), _bad)
check("but it gives the owner something to check",
      "bot ID" in _bad or "TELEGRAM_PING_BOT_TOKEN" in _bad, _bad)
# The bot ID half of a token is public; the secret half is not.
check("and never the secret half of the token",
      TOKEN.split(":")[1] not in _bad and len(_bad) < 250, _bad)
# An unparseable payload tells a prober nothing at all.
_junk = login("garbage").json().get("detail") or ""
check("junk stays fully generic",
      _junk == "Could not verify Telegram sign-in.", _junk)
# A stale timestamp is not a hint: the holder of an expired payload already
# knows it is old, and the user needs to be told to reopen the app.
_stale = login(init_data(when=time.time() - 90000)).json().get("detail") or ""
check("a stale session is explained instead", "expired" in _stale.lower(), _stale)

print("[3b] the endpoint is rate limited, like every other auth route")
_attempts.clear()
codes = [login(init_data(token="999:WRONG"), fresh=False).status_code
         for _ in range(30)]
check("a forger cannot hammer it forever", 429 in codes,
      str(sorted(set(codes))))
check("and legitimate calls still work once the window clears",
      login(init_data()).status_code == 200)

# ---------------------------------------------------------------------------
print("[3c] a failure says WHICH failure, when the user can act on it")
# ---------------------------------------------------------------------------
# Every cause returned one "Could not verify Telegram sign-in.", which the
# Mini App turned into "Couldn't connect". A missing TELEGRAM_PING_BOT_TOKEN,
# a token belonging to a different bot, and a stale session all looked like a
# network problem on the phone, so the only debugging move was guessing.
r = login(init_data(token="999999:SomeOtherBotTokenABCDEFGH"))
_dm = (r.json().get("detail") or "")
check("a token mismatch names the configured bot ID",
      "bot ID" in _dm, _dm)
check("and it points at the bot, not at the network",
      "connect" not in _dm.lower(), _dm)

r = login(init_data(when=time.time() - 90000))
check("a stale session says so", "expired" in (r.json().get("detail") or "").lower(),
      str(r.json().get("detail")))
check("and tells the user to reopen, which actually fixes it",
      "open it again" in (r.json().get("detail") or "").lower())

_saved_tok = os.environ.get("TELEGRAM_PING_BOT_TOKEN", "")
os.environ["TELEGRAM_PING_BOT_TOKEN"] = ""
r = login(init_data())
check("a missing server token is a 503, not a generic 400",
      r.status_code == 503, str(r.status_code))
check("and names the env var the operator must set",
      "TELEGRAM_PING_BOT_TOKEN" in (r.json().get("detail") or ""),
      str(r.json().get("detail")))
os.environ["TELEGRAM_PING_BOT_TOKEN"] = _saved_tok

# Causes a FORGER controls stay generic: telling them the payload was
# well-formed but the user object was missing is a hint about what to fix.
for _junk in ("garbage", urlencode({"auth_date": "1", "user": "{}"})):
    d = (login(_junk).json() or {}).get("detail") or ""
    check("an unusable payload stays generic",
          d == "Could not verify Telegram sign-in.", d)

# The reason must reach the operator's log at a level dashboards keep.
_auth_src = open(os.path.join(ROOT, "routes/auth.py"), encoding="utf-8").read()
check("rejections are logged as warnings, not info",
      'logger.warning("miniapp auth rejected: %s' in _auth_src)
check("and the log says how many payload forms were tried",
      "tried %d payload form" in _auth_src)

# ---------------------------------------------------------------------------
print("[3d] a mangled token is tolerated, and a real mismatch names itself")
# ---------------------------------------------------------------------------
# Production log said exactly one word: bad_hash. FOUR different causes
# produce it and none is distinguishable on a phone:
#     quoted in the hosting UI   "123:ABC"
#     pasted with an @ prefix    @123:ABC
#     the bot username pasted instead of the token
#     genuinely a different bot's token
_orig = os.environ.get("TELEGRAM_PING_BOT_TOKEN", "")

# Two of them are paste accidents around a CORRECT token, so they are cleaned
# rather than left to fail as a signature mismatch.
os.environ["TELEGRAM_PING_BOT_TOKEN"] = '"' + TOKEN + '"'
check("a quoted token still verifies", login(init_data()).status_code == 200,
      str(login(init_data()).status_code))
os.environ["TELEGRAM_PING_BOT_TOKEN"] = "@" + TOKEN
check("an @-prefixed token still verifies", login(init_data()).status_code == 200)
os.environ["TELEGRAM_PING_BOT_TOKEN"] = "  " + TOKEN + "\n"
check("surrounding whitespace still verifies", login(init_data()).status_code == 200)

# The other two are real misconfigurations, so they say which.
os.environ["TELEGRAM_PING_BOT_TOKEN"] = "MyCodeNestBot"
_d = (login(init_data()).json() or {}).get("detail") or ""
check("a username pasted instead of a token says so",
      "not shaped like a bot token" in _d, _d)

os.environ["TELEGRAM_PING_BOT_TOKEN"] = TOKEN
_d = (login(init_data(token="9999999:AAsomeOtherBotTokenABCDEFGH123456")).json()
      or {}).get("detail") or ""
check("a genuine bot mismatch reports the configured bot ID",
      "123456" in _d, _d)
# The INTENT is "the owner can act on this without guessing", not one exact
# sentence. The wording changed when the message stopped saying "check that
# matches" (a comparison the user has to work out) and started naming the step
# that fixes it — send /start to the right bot, because the usual cause is an
# old message button from a bot that has since been replaced. Assert the
# actionable step, so a future improvement to the phrasing is not a failure.
check("so the owner can act on it without guessing",
      "/start" in _d and "bot ID" in _d, _d)

# The bot ID half of a token is public — anyone who can message the bot sees
# it. The SECRET half must never appear.
check("the token's secret half is never echoed",
      "AAFakeBotToken" not in _d, _d)
_shape = MA.token_shape()
check("token_shape exposes only the public id", set(_shape) <= {"configured", "bot_id", "looks_valid"},
      str(_shape))
check("and never the secret", TOKEN.split(":")[1] not in str(_shape), str(_shape))

os.environ["TELEGRAM_PING_BOT_TOKEN"] = _orig

# ---------------------------------------------------------------------------
print("[3e] the diagnostic that settles a bad_hash")
# ---------------------------------------------------------------------------
# Production reached a state nothing could explain from the inside:
#     bad_hash with configured bot_id=8719137492 looks_valid=True
# The token was well-formed, so shape checking had nothing left to say. Only
# Telegram knows WHOSE token it is, so getMe is the check that ends the guess.
import bcrypt as _bcrypt  # noqa: E402
from routes.deps import now_utc_str as _now  # noqa: E402

_pw = "Passw0rd!x"
_conn = DB.get_db_connection()
_conn.execute("INSERT INTO users (username,email,password,is_verified,is_admin,"
              "created_at,updated_at) VALUES (?,?,?,1,1,?,?)",
              ("diagadmin", "diagadmin@gmail.com",
               _bcrypt.hashpw(_pw.encode(), _bcrypt.gensalt()).decode(),
               _now(), _now()))
_conn.commit()
_conn.close()
_at = c.post("/login", json={"username": "diagadmin", "password": _pw}).json()["token"]
_AH = {"Authorization": "Bearer " + _at}

check("the diagnostic is admin-only",
      c.get("/admin/telegram-diagnostic").status_code == 404,
      str(c.get("/admin/telegram-diagnostic").status_code))

_saved_who = MA.whoami
try:
    MA.whoami = lambda timeout_s=6.0: {"ok": True, "bot_id": 123456,
                                       "username": "AhadRealBot"}
    _d = c.get("/admin/telegram-diagnostic", headers=_AH).json()
    check("it names the bot the token really belongs to",
          _d.get("bot_username") == "AhadRealBot", str(_d))
    check("and gives a link to open that exact bot",
          _d.get("open_this_bot") == "https://t.me/AhadRealBot", str(_d.get("open_this_bot")))
    check("with a next step that says what to do",
          "Open the Mini App from @AhadRealBot" in (_d.get("next_step") or ""),
          str(_d.get("next_step")))

    # A widget pointing at one bot while verification expects another is its
    # own bug, and invisible without comparing the two.
    _sv = os.environ.get("TELEGRAM_BOT_USERNAME", "")
    os.environ["TELEGRAM_BOT_USERNAME"] = "ADifferentBot"
    _d2 = c.get("/admin/telegram-diagnostic", headers=_AH).json()
    check("a username/token mismatch is called out",
          "must be the same bot" in (_d2.get("warning") or ""), str(_d2.get("warning")))
    os.environ["TELEGRAM_BOT_USERNAME"] = "AhadRealBot"
    _d3 = c.get("/admin/telegram-diagnostic", headers=_AH).json()
    check("and no warning when they agree", not _d3.get("warning"), str(_d3.get("warning")))
    os.environ["TELEGRAM_BOT_USERNAME"] = _sv

    MA.whoami = lambda timeout_s=6.0: {"ok": False, "reason": "rejected_by_telegram",
                                       "detail": "Unauthorized"}
    _d4 = c.get("/admin/telegram-diagnostic", headers=_AH).json()
    check("a token Telegram rejects says to re-copy it",
          "BotFather" in (_d4.get("next_step") or ""), str(_d4.get("next_step")))

    # The public half only, in every branch.
    import json as _json
    _all = _json.dumps(_d) + _json.dumps(_d4)
    check("the token's secret half never appears",
          TOKEN.split(":")[1] not in _all, _all[:160])
finally:
    MA.whoami = _saved_who

# THE DIAGNOSTIC MUST BE REACHABLE WITHOUT SIGNING IN.
# /admin/telegram-diagnostic needs an Authorization HEADER, so typing that URL
# into a browser returns 404 — the check existed but the person who needed it
# could not reach it. /health needs nothing.
_saved_who2 = MA.whoami
A._BOT_IDENTITY.update(checked=False, value=None)
try:
    MA.whoami = lambda timeout_s=6.0: {"ok": True, "bot_id": 123456,
                                       "username": "AhadRealBot"}
    _hh = c.get("/health").json()
    check("/health names the bot, with no auth at all",
          (_hh.get("telegram_bot") or {}).get("username") == "AhadRealBot", str(_hh.get("telegram_bot")))
    check("and links straight to it",
          (_hh.get("telegram_bot") or {}).get("open") == "https://t.me/AhadRealBot")
    check("/health never carries the token secret",
          TOKEN.split(":")[1] not in str(_hh), str(_hh)[:120])

    # When the configured token's bot id does NOT match what getMe reports,
    # the right message names the bot — the revoked-secret reasoning must not
    # hijack it, because a mismatched id has a better explanation.
    MA.whoami = lambda timeout_s=6.0: {"ok": True, "bot_id": 555000111,
                                       "username": "AhadRealBot"}
    A._BOT_IDENTITY.update(checked=False, value=None)
    _dd = (login(init_data(token="9999999:AAsomeOtherBotTokenABCDEFGH123456")).json()
           or {}).get("detail") or ""
    check("the error names the bot by @username, not just a number",
          "@AhadRealBot" in _dd, _dd)
    # Again the STEP, not the sentence. "Open the Mini App from that bot"
    # assumed the user could tell which bot they had opened it from — and when
    # the cause is a stale button in an old chat, they cannot. Naming /start
    # gives them something to press.
    check("and says what to do with it",
          "/start" in _dd and "@AhadRealBot" in _dd, _dd)
    MA.whoami = lambda timeout_s=6.0: {"ok": True, "bot_id": 123456,
                                       "username": "AhadRealBot"}
    A._BOT_IDENTITY.update(checked=False, value=None)

    # One getMe per process, not per request: /health is a liveness probe.
    _calls = []
    MA.whoami = lambda timeout_s=6.0: (_calls.append(1),
                                       {"ok": True, "bot_id": 1, "username": "X"})[1]
    A._BOT_IDENTITY.update(checked=False, value=None)
    for _ in range(5):
        c.get("/health")
    check("the identity is cached, not re-fetched on every probe",
          len(_calls) == 1, str(len(_calls)))
finally:
    MA.whoami = _saved_who2
    A._BOT_IDENTITY.update(checked=False, value=None)

# /health carries the same public id, so it can be checked without signing in.
_h = c.get("/health").json()
check("/health reports the configured bot id",
      str(_h.get("telegram_bot_id")) == TOKEN.split(":")[0], str(_h.get("telegram_bot_id")))
check("and /health never exposes the secret",
      TOKEN.split(":")[1] not in str(_h), str(_h))

# ---------------------------------------------------------------------------
print("[3f] a bad_hash records the payload's SHAPE, so it can be diagnosed")
# ---------------------------------------------------------------------------
# Production reached a state where getMe confirmed the RIGHT bot and the hash
# still failed. At that point every remaining explanation is "the bytes we
# hashed differ from the bytes Telegram hashed", and nothing in the system
# could say how. The field list is the smallest thing that can.
try:
    MA.verify_init_data(init_data(token="9999999:AAotherBotTokenABCDEFGH12345"), TOKEN)
    _shape_err = None
except MA.BadHash as e:
    _shape_err = e
check("a mismatch raises BadHash", _shape_err is not None)
check("it is still a ValueError, so existing handlers catch it",
      isinstance(_shape_err, ValueError))
check("and still reads 'bad_hash' for callers that compare on it",
      str(_shape_err) == "bad_hash", str(_shape_err))
check("it records which fields were hashed",
      "auth_date" in _shape_err.fields and "user" in _shape_err.fields,
      str(_shape_err.fields))
check("hash itself is excluded from the hashed set",
      "hash" not in _shape_err.fields, str(_shape_err.fields))
# Lengths, never values — a length cannot reconstruct a name or a token.
check("only lengths are recorded, not values",
      all(isinstance(v, int) for v in _shape_err.lengths.values()),
      str(_shape_err.lengths))
check("no field VALUE appears in the diagnostic",
      "Ahad" not in str(_shape_err.lengths) and "ahadxyz" not in str(_shape_err.fields),
      str(_shape_err.lengths))

# Multiple payload forms: the browser may hold two spellings of the same
# initData, and only one carries the bytes that were signed.
_good = init_data()
_r = c.post("/auth/telegram/miniapp",
            json={"init_data": "definitely-not-valid", "init_data_alt": [_good]})
check("a valid alternate form is accepted", _r.status_code == 200, _r.text[:120])
_attempts.clear()
_r2 = c.post("/auth/telegram/miniapp",
             json={"init_data": "junk", "init_data_alt": ["more junk"]})
check("but junk alternates are still refused", _r2.status_code == 400)
_attempts.clear()
_r3 = c.post("/auth/telegram/miniapp",
             json={"init_data": "junk", "init_data_alt": ["a", "b", "c", "d", "e"]})
check("the number of attempts is bounded", _r3.status_code == 400)

# ---------------------------------------------------------------------------
print("[3g] when the field list is normal, name the field whose VALUE differs")
# ---------------------------------------------------------------------------
# Production returned a completely ordinary field list:
#   fields=['auth_date','chat_instance','chat_type','user']
# Nothing dropped, nothing extra. So the mismatch is in a VALUE, and the only
# candidate is how it was decoded. Re-running the HMAC with each field's raw
# (still percent-encoded) form identifies which one.
_u = json.dumps({"id": 5, "first_name": "Ahad",
                 "photo_url": "https://t.me/i/a+b.svg"}, separators=(",", ":"))
_f = {"user": _u, "chat_instance": "-1", "chat_type": "sender",
      "auth_date": str(int(time.time()))}
# Sign over the RAW user value instead of the decoded one.
_signed = dict(_f)
_signed["user"] = quote(_u, safe="")
_cs = "\n".join(f"{k}={_signed[k]}" for k in sorted(_signed))
_sec = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
_h = hmac.new(_sec, _cs.encode(), hashlib.sha256).hexdigest()
_wire = urlencode({**_f, "hash": _h}, quote_via=quote)

try:
    MA.verify_init_data(_wire, TOKEN)
    _cerr = None
except MA.BadHash as e:
    _cerr = e
check("a decoding difference is still rejected", _cerr is not None)
check("and the responsible field is named", _cerr and _cerr.culprit == "user",
      str(_cerr and _cerr.culprit))

# A genuinely forged payload has no culprit — nothing makes it verify.
try:
    MA.verify_init_data(init_data(token="9999999:AAforgedTokenABCDEFGH1234567"), TOKEN)
    _ferr = None
except MA.BadHash as e:
    _ferr = e
check("a forged payload reports no culprit", _ferr and _ferr.culprit is None,
      str(_ferr and _ferr.culprit))

# The finder must DIAGNOSE only. A payload that verifies solely under a
# substitution has not been validly signed for us, and must never be accepted.
_attempts.clear()
check("the substitution is never accepted as a login",
      c.post("/auth/telegram/miniapp", json={"init_data": _wire}).status_code == 400)

_asrc = open(os.path.join(ROOT, "routes/auth.py"), encoding="utf-8").read()
check("the culprit reaches the log", "culprit=%s" in _asrc)

# ---------------------------------------------------------------------------
print("[3h] a wrong-key bad_hash names the bot, and never blames the token")
# ---------------------------------------------------------------------------
# THIS BLOCK USED TO ASSERT THE OPPOSITE, AND IT WAS WRONG. It required a 503
# reading "your Telegram token is out of date", produced by this guard:
#
#     _id_agrees = str(getMe(OUR token).id) == id parsed from OUR OWN token
#     if _tok_ok and _id_agrees and culprit is None and age < 300: -> 503
#
# Two separate faults, both reproduced:
#
#  1. _id_agrees is a TAUTOLOGY. Both sides derive from the same token, and
#     Telegram can only answer getMe with the id inside the token it was
#     called with. It is True for every live token and can detect nothing.
#
#  2. THE GUARD IS INVERTED with respect to its own purpose. Walked through
#     both cases:
#       * token really revoked -> the server's secret is dead -> getMe
#         answers 401 -> whoami() reports rejected_by_telegram -> the
#         identity dict has no "id" -> _id_agrees False -> the 503 does NOT
#         fire. The case it was written for is the one it misses.
#       * payload signed by a DIFFERENT bot (an old message button from a
#         previous bot) -> our token is live -> _id_agrees True -> the 503
#         DOES fire, telling the owner to re-copy a token that is perfectly
#         fine. That is the reported bug: a new bot was created, the token
#         was saved, and the message never changed.
#
# The old test passed only because it MOCKED whoami() into ok=True — an answer
# a revoked token never produces. It encoded the bug rather than catching it.
#
# A genuinely revoked token is already handled, and better: whoami() returns
# rejected_by_telegram and start_bot() logs "TELEGRAM TOKEN REJECTED by getMe"
# at boot, before anyone tries to sign in.
#
# What the server can say honestly is which bot it accepts, so that is what is
# asserted now. tests/test_badhash_verdict.py covers this in full.
_srv = "8719137492:AAserverHoldsThisBotsSecret1234"
_tg = "7111111111:AAaDifferentBotSignedThePayload"
_prev = os.environ.get("TELEGRAM_PING_BOT_TOKEN", "")
os.environ["TELEGRAM_PING_BOT_TOKEN"] = _srv
_prev_who = MA.whoami
MA.whoami = lambda timeout_s=6.0: {"ok": True, "bot_id": 8719137492,
                                   "username": "mytestRenderBot"}
A._BOT_IDENTITY.update(checked=False, value=None)

_u = json.dumps({"id": 123, "first_name": "Ahad"}, separators=(",", ":"))
_f = {"auth_date": str(int(time.time())), "query_id": "AAHdqTcvCH1vGWJx0000",
      "user": _u}
_cs = "\n".join(f"{k}={_f[k]}" for k in sorted(_f))
_sc = hmac.new(b"WebAppData", _tg.encode(), hashlib.sha256).digest()
_f["hash"] = hmac.new(_sc, _cs.encode(), hashlib.sha256).hexdigest()

_r = login(urlencode(_f))
check("a wrong-key sign-in is a 400 (the request), not a 503 (the server)",
      _r.status_code == 400, str(_r.status_code))
_msg = (_r.json() or {}).get("detail") or ""
check("it does NOT blame a token Telegram has just confirmed is live",
      "out of date" not in _msg.lower(), _msg)
check("it names the bot this server accepts",
      "mytestRenderBot" in _msg, _msg)
check("and tells the user how to reach it",
      "/start" in _msg, _msg)

# The reasoning must not fire on anything else.
# `except X as _e` UNBINDS the name at the end of the block in Python 3, so
# _e was undefined on the next line. Capture it deliberately.
_e = None
try:
    MA.verify_init_data(urlencode(_f), _srv)
except MA.BadHash as _exc:
    _e = _exc
check("the diagnosis records freshness", _e is not None and _e.age_s is not None,
      str(_e and _e.age_s))
check("and the payload really is fresh", _e and _e.age_s < 60, str(_e and _e.age_s))

# A stale replay has culprit=None too, so age is what separates them — it must
# NOT be reported as a bad token.
_old = dict(_f)
_old["auth_date"] = str(int(time.time()) - 3600)
_ocs = "\n".join(f"{k}={_old[k]}" for k in sorted(_old) if k != "hash")
_old["hash"] = hmac.new(_sc, _ocs.encode(), hashlib.sha256).hexdigest()
_ro = login(urlencode(_old))
check("an hour-old payload is NOT blamed on the token",
      _ro.status_code != 503 or "out of date" not in
      ((_ro.json() or {}).get("detail") or "").lower(),
      f"{_ro.status_code} {(_ro.json() or {}).get('detail')}")

# And a forger gets nothing helpful.
check("junk still gets the generic message",
      ((login("garbage").json() or {}).get("detail") or "")
      == "Could not verify Telegram sign-in.")

os.environ["TELEGRAM_PING_BOT_TOKEN"] = _prev
MA.whoami = _prev_who
A._BOT_IDENTITY.update(checked=False, value=None)

# ---------------------------------------------------------------------------
print("[4] the verifier's own edge cases")
# ---------------------------------------------------------------------------
try:
    MA.verify_init_data(init_data(drop_user=True))
    ok = False
except ValueError as e:
    ok = str(e) == "no_user"
check("initData with no user (inline/channel open) is refused", ok)

# THIS BLOCK ASSERTED THE BUG, AND IS WHY THE BUG SHIPPED.
#
# It took a payload signed WITHOUT `signature`, glued `signature=abc123` on
# afterwards, and required that to still verify. Telegram never produces such
# a string — when it sends `signature`, that field is part of what it signed.
# The only way to satisfy this test was to pop `signature` before hashing,
# which is exactly the line that broke every real sign-in from a client new
# enough to send the field. A test that can only be passed by breaking
# production is worse than no test.
#
# Proven with Telegram's own @telegram-apps/init-data-node: sign a payload
# containing `signature`, then recompute the hash both ways —
#     HMAC WITH    signature -> bb7b679dc007...  == the library's hash
#     HMAC WITHOUT signature -> 981c1132292c...  != the library's hash
# The field belongs in the HMAC data-check string. It is excluded only from
# the ED25519 third-party check, and conflating the two rules was the error.
#
# Rewritten to test the real contract, both directions.
_sig = "zL-ucjNyREiHDE8aihFwpfR9aggP2xiAo3NSpfe-p7Ib"

# 1. As Telegram actually sends it: signature present AND covered by the hash.
_real = init_data(extra={"signature": _sig})
try:
    _got = MA.verify_init_data(_real)
    _sig_ok = _got["id"] == 555
except ValueError:
    _sig_ok = False
check("initData whose hash COVERS `signature` verifies", _sig_ok)

# 2. The old test's own fixture — a signature bolted on after signing — is a
# payload Telegram never emits, and must be refused.
try:
    MA.verify_init_data(init_data(extra=None) + "&signature=abc123")
    _bolt_ok = False
except ValueError:
    _bolt_ok = True
check("a `signature` glued on after signing is refused", _bolt_ok)

def _reason(data, token=None):
    """The ValueError reason verify_init_data raises, or None on success."""
    try:
        MA.verify_init_data(data) if token is None else MA.verify_init_data(data, token)
        return None
    except ValueError as exc:
        return str(exc)


check("an oversized blob is refused before any parsing",
      _reason("x" * 9000) == "too_large", str(_reason("x" * 9000)))
check("a missing bot token is reported distinctly, not as a bad signature",
      _reason(init_data(), token="") == "not_configured",
      str(_reason(init_data(), token="")))
check("a bad auth_date is named as such, not as a bad hash",
      _reason(init_data(when=time.time() - 90000)) == "expired")
check("no hash means no_hash",
      _reason(urlencode({"auth_date": "1", "user": "{}"})) == "no_hash")

# ---------------------------------------------------------------------------
print("[5] one identity across every door")
# ---------------------------------------------------------------------------
# The Mini App, the website's Telegram Login and the bot must all land on the
# same row when the Telegram id matches. Two accounts for one person would
# split their job list and double their quota.
wf = {"auth_date": int(time.time()), "first_name": "Ahad", "id": 555,
      "username": "ahadxyz", "photo_url": ""}
wcs = "\n".join(f"{k}={v}" for k, v in sorted(wf.items()) if v not in (None, ""))
wf["hash"] = hmac.new(hashlib.sha256(TOKEN.encode()).digest(), wcs.encode(),
                      hashlib.sha256).hexdigest()
rw = c.post("/auth/telegram", json=wf)
check("the website widget still works", rw.status_code == 200, rw.text[:120])
check("and lands on the SAME username", rw.json().get("username") == "tg_555")
# Count rows for THIS telegram id, not every user in the table. Counting all
# users made the assertion depend on how many unrelated fixtures earlier
# sections had created — it broke the moment [3e] added an admin, which says
# nothing about whether the two doors share an account.
conn = DB.get_db_connection()
n2 = dict(conn.execute("SELECT COUNT(*) AS c FROM users WHERE telegram_id = ?",
                       (555,)).fetchone())["c"]
conn.close()
check("still one account for this Telegram id, not two", n2 == 1, str(n2))

check("the Telegram handle is cached for the dashboard",
      c.get("/profile/telegram", headers=H).json().get("telegram_name") == "@ahadxyz",
      str(c.get("/profile/telegram", headers=H).json()))

# A user who renames themselves on Telegram must not show a stale handle.
login(init_data(uname="newhandle"))
check("the cached handle refreshes on a later open",
      c.get("/profile/telegram", headers=H).json().get("telegram_name") == "@newhandle",
      str(c.get("/profile/telegram", headers=H).json().get("telegram_name")))

# A suspended account must not gain a new way in.
conn = DB.get_db_connection()
conn.execute("UPDATE users SET is_suspended = 1 WHERE telegram_id = 555")
conn.commit()
conn.close()
check("a suspended account cannot sign in via the Mini App",
      login(init_data()).status_code == 403, str(login(init_data()).status_code))
conn = DB.get_db_connection()
conn.execute("UPDATE users SET is_suspended = 0 WHERE telegram_id = 555")
conn.commit()
conn.close()

# ---------------------------------------------------------------------------
print("[6] the same limits apply, whichever door was used")
# ---------------------------------------------------------------------------
from services.runner_client import MAX_JOBS_PER_USER  # noqa: E402
from services import bot_ops  # noqa: E402
src_rs = open(os.path.join(ROOT, "routes/runspace.py"), encoding="utf-8").read()
check("the web create path enforces the cap", "MAX_JOBS_PER_USER" in src_rs)
check("and bot_ops enforces the same constant",
      "MAX_JOBS_PER_USER" in open(os.path.join(ROOT, "services/bot_ops.py"),
                                  encoding="utf-8").read())
check("there is only ONE cap value", MAX_JOBS_PER_USER == bot_ops.MAX_JOBS_PER_USER)
# The Mini App is the website, so it uses POST /api/jobs — no third path.
src_ma = open(os.path.join(ROOT, "static/miniapp.js"), encoding="utf-8").read()
check("the Mini App adds no second job-creation path",
      "/internal/jobs" not in src_ma and "/api/jobs" not in src_ma)

# ---------------------------------------------------------------------------
print("[7] the bot's Mini App entry point")
# ---------------------------------------------------------------------------
import services.pingbot as PB  # noqa: E402
SENT = []
PB._tg = lambda m, **p: (SENT.append((m, p)), {"ok": True})[1]

PB.SITE_BASE = "https://ahadorg.onrender.com"
btn = PB._open_button()
check("the launch button is a web_app button", "web_app" in (btn or {}), str(btn))
check("pointing at the dashboard",
      (btn or {}).get("web_app", {}).get("url", "").endswith("/dashboard"), str(btn))

# Telegram REFUSES a web_app button on http:// and drops the whole keyboard.
PB.SITE_BASE = "http://localhost:8000"
btn2 = PB._open_button()
check("an http site falls back to a plain link rather than a rejected button",
      "url" in (btn2 or {}) and "web_app" not in (btn2 or {}), str(btn2))
check("and the menu button is not registered at all on http",
      PB.set_menu_button() is False)
PB.SITE_BASE = "https://ahadorg.onrender.com"

SENT.clear()
check("the menu button registration calls the right API",
      PB.set_menu_button() is True and SENT[0][0] == "setChatMenuButton",
      str(SENT[:1]))
check("with type web_app",
      SENT[0][1]["menu_button"]["type"] == "web_app", str(SENT[0][1]))

src_pb = open(os.path.join(ROOT, "services/pingbot.py"), encoding="utf-8").read()
src_ops = open(os.path.join(ROOT, "services/bot_ops.py"), encoding="utf-8").read()
# Chat-based code deploy is removed outright, so the Mini App is the ONLY
# place code is written — there is no cheaper-looking path competing with it.
check("no /code command", 'startswith("/code")' not in src_pb)
check("no /deploy command", 'startswith("/deploy")' not in src_pb)
check("no /update command", 'startswith("/update")' not in src_pb)
check("no message can reach the runner as a job",
      '"/internal/jobs"' not in src_pb and '"/internal/jobs"' not in src_ops)
check("/jobs is accepted as well as /apps",
      'text.startswith("/jobs")' in src_pb)

# /start: exactly one button, and no URL as text.
SENT.clear()
PB.telegram_link.user_for_chat = lambda cid: None      # unlinked visitor
PB.handle_start(424242, "Stranger")
_msg = [p for m, p in SENT if m == "sendMessage"][-1]
_kb = json.loads(_msg["reply_markup"])["inline_keyboard"]
_btns = [b for row in _kb for b in row]
check("/start shows exactly one button", len(_btns) == 1, str(_btns))
check("labelled Open CodeNest", "Open CodeNest" in _btns[0]["text"], str(_btns[0]))
check("and it is a web_app button, not a link", "web_app" in _btns[0], str(_btns[0]))
check("no URL is printed in the text", "http" not in _msg["text"], _msg["text"][:120])
check("and no code command is advertised",
      not any(x in _msg["text"] for x in ("/code", "/deploy", "/update")),
      _msg["text"][:160])

# ---------------------------------------------------------------------------
print("[8] a normal browser is untouched")
# ---------------------------------------------------------------------------
html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
check("the SDK is loaded", "telegram-web-app.js" in html)
# "pro.js" first appears inside a COMMENT further up the file, so a plain
# indexOf compares against the wrong position. Match the real script tags.
import re as _re  # noqa: E402
_tags = _re.findall(r'<script src="/static/(miniapp|pro)\.js', html)
check("miniapp.js loads BEFORE pro.js, which reads its globals",
      _tags[:2] == ["miniapp", "pro"], str(_tags))
check("the SDK's mere presence is not treated as being inside Telegram",
      "const inTelegram = initData.length > 0;" in src_ma)
# TWO signals now. telegram-web-app.js comes from telegram.org, so when it is
# blocked the SDK never appears — and the app used to conclude it was NOT in
# Telegram, fall through to routeFromUrl() on the protected /dashboard route,
# and show a Create account screen inside the Mini App.
check("a blocked SDK is covered by reading Telegram's own URL fragment",
      "tgWebAppData" in src_ma)
check("the SDK value is preferred when it exists",
      "const initData = sdkData || hashData;" in src_ma)
check("and every SDK call tolerates the script being absent",
      'const has = (fn) => !!(TG && typeof TG[fn] === "function");' in src_ma)
check("outside Telegram the module does nothing and returns early",
      "if (!inTelegram)" in src_ma and "return;" in src_ma)
check("an existing session is reused rather than re-authenticated",
      'localStorage.getItem("ahad_token")' in src_ma)
_pro = open(os.path.join(ROOT, "static/pro.js"), encoding="utf-8").read()
# The FIRST "__tgAutoLogin" is the `typeof` guard; the branch bodies come
# after the call. Slice from the call itself.
_boot = _pro[_pro.index("if (window.__inTelegram) {"):
             _pro.index("// ---- Boot: decide the screen SYNCHRONOUSLY")]
# Comments in this branch name the bug they fix, so strip them before
# asserting the CODE never routes to an auth screen.
_boot_code = _re.sub(r"//.*", "", _boot)
check("no auth screen is reachable from the Mini App boot",
      not _re.search(r'screen-(signin|signup|landing|otp|forgot)', _boot_code),
      str(_re.findall(r'screen-\w+', _boot_code)))
check("a failure shows a retry, never a login form", "_tgFatal(" in _boot_code)
check("the dashboard is what renders underneath",
      'showScreen("screen-dashboard")' in _boot_code)
check("routeFromUrl runs only once a token exists",
      "if (authToken) { try { routeFromUrl()" in _boot_code)
check("and the boot splash is cleared on every path",
      _boot_code.count("done()") >= 3, str(_boot_code.count("done()")))
check("theme colours are validated before being injected into CSS",
      "/^#[0-9a-f]{3,8}$/i" in src_ma)

print(f"\ntest_miniapp_auth: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
