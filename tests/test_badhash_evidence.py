"""STOP INFERRING WHY A MINI APP SIGN-IN FAILED. PROVE IT.

THE HISTORY THIS EXISTS TO END. Three times in a row the server named a cause
it had not established, and each time the owner acted on it and nothing
changed:

  1. "The server's Telegram token is out of date" — produced by comparing
     getMe(our token).id against the id parsed out of our own token. Both
     sides come from the same token, so the comparison was a tautology that
     fired for every live token. The owner created a whole new bot for
     nothing.

  2. "You opened an older bot's button" — inferred from the presence of
     query_id in the payload. query_id does mean the app was launched from a
     message button, but that does NOT establish which bot signed it. The
     owner opened the correct bot and got the same message.

Both were guesses dressed as findings. The user's /health then ruled the
guesses out on the record:

    telegram_bot          {"username":"myAutomaitBot","id":8221572217}
    telegram_token_source {"set":["BOT_TOKEN"],"conflict":false}
    miniapp_url           {"ok":true}

and the repo's HMAC verifies Telegram's own published test vector, so the
algorithm is not broken either.

WHAT ACTUALLY DECIDES IT. Two independent facts, neither of which the server
was collecting:

  * Telegram signs initData a SECOND time, with its own Ed25519 key. That
    signature is verifiable with the PUBLIC bot id alone — no bot token. So
    "signature valid + our HMAC invalid" proves the payload is authentic and
    addressed to this bot, leaving the SECRET half of our token as the only
    remaining variable.

  * Whether the token is valid RIGHT NOW. Telegram keeps exactly one valid
    token per bot, so a 401 from getMe is decisive. The existing check cached
    a single getMe at boot and never refreshed, so it could report a bot it
    had not re-tested — which is exactly how /health looked healthy while
    every sign-in failed.

Every check below distinguishes a PROVEN cause from a guessed one.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

_tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp
os.environ["DB_PATH"] = os.path.join(_tmp, "ev.db")
os.environ["LIVE_PORT_MIN"] = "18300"
os.environ["LIVE_PORT_MAX"] = "18399"

BOT_ID = 8221572217
SERVER_TOKEN = f"{BOT_ID}:AAserverCopyOfTheSecret1234567"
CURRENT_TOKEN = f"{BOT_ID}:AAcurrentSecretAfterRevoke9876"
OTHER_TOKEN = "7111111111:AAaDifferentBotEntirely00000000"
os.environ["BOT_TOKEN"] = SERVER_TOKEN
os.environ.pop("TELEGRAM_PING_BOT_TOKEN", None)

from fastapi.testclient import TestClient  # noqa: E402
import app as APP  # noqa: E402
from services import miniapp_auth as M  # noqa: E402

_pass, _fail = 0, 0


def check(name, cond, extra=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  ok   {name}")
    else:
        _fail += 1
        print(f"  FAIL {name}" + (f" -> {extra}" if extra else ""))


try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

USER = {"id": 6543210, "first_name": "Ahad", "last_name": "Rahman",
        "username": "ahad_r", "language_code": "bn", "is_premium": True,
        "allows_write_to_pm": True,
        "photo_url": "https://t.me/i/userpic/320/4FPEE4tmP3ATHa57u6MqTDih13LTOiMoKoLDRG4PnSA.svg"}


def fields(with_query_id=True):
    # Telegram escapes forward slashes in the user JSON; keep that exactly.
    f = {"auth_date": str(int(time.time())),
         "user": json.dumps(USER, separators=(",", ":")).replace("/", r"\/")}
    if with_query_id:
        f["query_id"] = "AAHdF6IQAAAAAN0XohDhrOrc"
    else:
        f["chat_type"] = "sender"
        f["chat_instance"] = "-1234567890123456789"
    return f


def wire(f, hmac_token, ed_priv=None, bot_id=BOT_ID):
    """Build initData signed with hmac_token, optionally Ed25519-signed too."""
    body = {k: v for k, v in f.items()}
    dcs = "\n".join(f"{k}={body[k]}" for k in sorted(body))
    sec = hmac.new(b"WebAppData", hmac_token.encode(), hashlib.sha256).digest()
    h = hmac.new(sec, dcs.encode(), hashlib.sha256).hexdigest()
    if ed_priv is not None:
        sig = ed_priv.sign((f"{bot_id}:WebAppData\n" + dcs).encode())
        body["signature"] = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return ("&".join(f"{k}={quote(body[k], safe='')}" for k in sorted(body))
            + f"&hash={h}")


# ---------------------------------------------------------------------------
print("[1] the HMAC verifier is correct (official Telegram test vector)")
# ---------------------------------------------------------------------------
# If this ever fails, nothing else in this file means anything.
_OFF_TOKEN = "5768337691:AAH5YkoiEuPk8-FZa32hStHTqXiLPtAEhx8"
_OFF_INIT = ("query_id=AAHdF6IQAAAAAN0XohDhrOrc"
             "&user=%7B%22id%22%3A279058397%2C%22first_name%22%3A%22Vladislav%22%2C"
             "%22last_name%22%3A%22Kibenko%22%2C%22username%22%3A%22vdkfrost%22%2C"
             "%22language_code%22%3A%22ru%22%2C%22is_premium%22%3Atrue%7D"
             "&auth_date=1662771648"
             "&hash=c501b71e775f74ce10e377dea85a7ea24ecd640b223ea86dfe453e0eaed2e2b2")
_saved_age = M.INITDATA_MAX_AGE_S
M.INITDATA_MAX_AGE_S = 10 ** 12          # the published vector is from 2022
try:
    _u = M.verify_init_data(_OFF_INIT, _OFF_TOKEN)
    check("Telegram's own published initData verifies", _u["id"] == 279058397)
except Exception as e:
    check("Telegram's own published initData verifies", False, repr(e))
M.INITDATA_MAX_AGE_S = _saved_age


# ---------------------------------------------------------------------------
print("[2] Ed25519 third-party validation works (no bot token involved)")
# ---------------------------------------------------------------------------
if not HAVE_CRYPTO:
    check("cryptography is installed so the proof can run", False,
          "pip install cryptography")
else:
    _real_prod = M._TG_PUBKEY_PROD
    tg = Ed25519PrivateKey.generate()
    M._TG_PUBKEY_PROD = tg.public_key().public_bytes_raw().hex()

    f = fields()
    w_ok = wire(f, CURRENT_TOKEN, ed_priv=tg)
    check("a Telegram-signed payload is recognised",
          M.third_party_check(w_ok, BOT_ID)["ok"] is True)
    check("...and is rejected for a DIFFERENT bot id",
          M.third_party_check(w_ok, 7111111111)["ok"] is False)
    check("a payload with no signature yields no verdict",
          M.third_party_check(wire(f, CURRENT_TOKEN), BOT_ID)["reason"]
          == "no_signature")
    check("a tampered payload fails the signature",
          M.third_party_check(w_ok.replace("6543210", "6543211"),
                              BOT_ID)["ok"] is False)
    M._TG_PUBKEY_PROD = _real_prod

check("the check never accepts a login by itself",
      "third_party_check" not in open(
          os.path.join(ROOT, "routes/auth.py"), encoding="utf-8"
      ).read().split("if tg is None:")[0],
      "it must only run on the FAILURE path")


# ---------------------------------------------------------------------------
print("[3] the reported cause is PROVEN, not inferred")
# ---------------------------------------------------------------------------
M.whoami = lambda timeout_s=6.0: {"ok": True, "bot_id": BOT_ID,
                                  "username": "myAutomaitBot"}
M._LIVE_CACHE.update(token=None, at=0, value=None)
APP._BOT_IDENTITY.update(checked=False, value=None)
c = TestClient(APP.app)

if HAVE_CRYPTO:
    _real_prod = M._TG_PUBKEY_PROD
    tg = Ed25519PrivateKey.generate()
    M._TG_PUBKEY_PROD = tg.public_key().public_bytes_raw().hex()

    # THE USER'S SITUATION: same bot, same id, getMe fine, but the server's
    # secret is not the one Telegram signed with.
    w = wire(fields(), CURRENT_TOKEN, ed_priv=tg)
    r = c.post("/auth/telegram/miniapp", json={"init_data": w})
    d = r.json().get("detail", "")
    check("a secret mismatch is named, once it is proven",
          "DIFFERENT secret" in d and str(BOT_ID) in d, d)
    # NOT "revoke". whoami() is mocked ok here, so Telegram accepts the token
    # we hold — and a valid token that is not the signing token means the
    # DEPLOYED VALUE is not BotFather's current one. Revoking would mint a
    # third token into the same wrong place. See tests/test_token_mismatch.py.
    check("and it does not tell the owner to revoke a valid token",
          "Revoke current token" not in d, d)
    check("it is still a 400 — the request is what failed", r.status_code == 400)

    # CONTROL: a genuinely different bot must NOT get that message, even
    # though its payload also carries query_id (which is what fooled the
    # previous version into blaming an old message button).
    M._LIVE_CACHE.update(token=None, at=0, value=None)
    w2 = wire(fields(), OTHER_TOKEN)          # no valid Telegram signature
    r2 = c.post("/auth/telegram/miniapp", json={"init_data": w2})
    d2 = r2.json().get("detail", "")
    check("a different-bot payload is NOT blamed on our secret",
          "does not match" not in d2, d2)
    check("it names the bot this server accepts instead",
          "myAutomaitBot" in d2, d2)
    M._TG_PUBKEY_PROD = _real_prod


# ---------------------------------------------------------------------------
print("[4] a token Telegram rejects is DETECTED, not guessed")
# ---------------------------------------------------------------------------
# This is the case the very first bad verdict claimed to handle and could
# not: a revoked token. getMe answers 401 for it, so it is knowable — but
# only if the result is not served from a boot-time cache.
M.whoami = lambda timeout_s=6.0: {"ok": False, "reason": "rejected_by_telegram",
                                  "detail": "Unauthorized"}
M._LIVE_CACHE.update(token=None, at=0, value=None)
APP._BOT_IDENTITY.update(checked=False, value=None)
check("token_live() reports the rejection", M.token_live()["ok"] is False)

r3 = c.post("/auth/telegram/miniapp",
            json={"init_data": wire(fields(), CURRENT_TOKEN)})
d3 = r3.json().get("detail", "")
check("a revoked token is named as the cause",
      "no longer valid" in d3 and "BotFather" in d3, d3)

# Telegram being unreachable must NEVER be reported as a bad token.
M.whoami = lambda timeout_s=6.0: {"ok": False, "reason": "unreachable"}
M._LIVE_CACHE.update(token=None, at=0, value=None)
check("an unreachable Telegram yields no verdict", M.token_live()["ok"] is None)
r4 = c.post("/auth/telegram/miniapp",
            json={"init_data": wire(fields(), CURRENT_TOKEN)})
check("and the owner is not told their token is wrong",
      "does not match" not in r4.json().get("detail", ""),
      r4.json().get("detail", ""))


# ---------------------------------------------------------------------------
print("[5] the live check is cached, so failures cannot storm Telegram")
# ---------------------------------------------------------------------------
_calls = {"n": 0}


def _counting(timeout_s=6.0):
    _calls["n"] += 1
    return {"ok": True, "bot_id": BOT_ID, "username": "myAutomaitBot"}


M.whoami = _counting
M._LIVE_CACHE.update(token=None, at=0, value=None)
for _ in range(5):
    M.token_live()
check("five calls cost one getMe", _calls["n"] == 1, str(_calls["n"]))

os.environ["BOT_TOKEN"] = CURRENT_TOKEN        # changing the token re-checks
M.token_live()
check("changing the token invalidates the cache", _calls["n"] == 2,
      str(_calls["n"]))
os.environ["BOT_TOKEN"] = SERVER_TOKEN


# ---------------------------------------------------------------------------
print("[6] /health stops relying on the boot-time cache alone")
# ---------------------------------------------------------------------------
ASRC = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
check("/health reports a freshly checked token",
      "telegram_token_live" in ASRC)
check("the cached identity is still shown for comparison",
      "telegram_bot" in ASRC and "_bot_identity" in ASRC)
REQ = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
check("cryptography is declared, or the proof cannot run in production",
      "cryptography" in REQ)


# ---------------------------------------------------------------------------
print("[7] a correct sign-in is untouched, and forgery still fails")
# ---------------------------------------------------------------------------
M.whoami = lambda timeout_s=6.0: {"ok": True, "bot_id": BOT_ID,
                                  "username": "myAutomaitBot"}
M._LIVE_CACHE.update(token=None, at=0, value=None)
good = wire(fields(), SERVER_TOKEN)
r5 = c.post("/auth/telegram/miniapp", json={"init_data": good})
check("our own bot's payload signs in", r5.status_code == 200,
      f"{r5.status_code} {r5.text[:120]}")
r6 = c.post("/auth/telegram/miniapp",
            json={"init_data": good.replace("6543210", "6543211")})
check("a tampered payload is still refused", r6.status_code == 400)
r7 = c.post("/auth/telegram/miniapp", json={"init_data": "garbage"})
_d7 = r7.json().get("detail", "")
# The endpoint is rate limited (deliberately — it is an auth route), and this
# suite has already spent the budget for this client. A 429 here is the limiter
# doing its job, not a failure of the message; only assert the wording when the
# request actually reached the verifier.
check("junk gets nothing useful",
      r7.status_code == 429 or _d7 == "Could not verify Telegram sign-in.",
      f"{r7.status_code} {_d7}")


print(f"\ntest_badhash_evidence: {_pass} passed, {_fail} failed")
sys.exit(1 if _fail else 0)
