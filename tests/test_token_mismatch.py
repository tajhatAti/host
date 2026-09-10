"""tg_signature=VALID token_live=None — the gap that still left the owner stuck.

WHAT PRODUCTION REPORTED (third round):

    miniapp bad_hash: bot_id=8221572217 fields=['auth_date','query_id','user']
                      culprit=None age_s=2 tg_signature=VALID token_live=None
    TELEGRAM'S OWN SIGNATURE VALIDATES ... FIX: Revoke current token

Two separate problems in that single line.

1. token_live=None MEANS THE QUESTION WAS NEVER ASKED. The live getMe re-check
   was gated behind `if not _tp.get("ok")`, on the reasoning that a valid
   Ed25519 signature had already settled things. It had not: it settles that
   the payload is authentic, not whether the token we hold is still valid.
   Those two answers demand opposite actions, so skipping it left the owner
   with a verdict but no instruction that fits their case.

2. THE ADVICE WAS WRONG FOR THE CASE THAT ACTUALLY OCCURRED. With
   signature VALID *and* getMe accepting the token, both of these are true:
     * Telegram signed the payload for this bot with some secret S1;
     * Telegram accepts our token, so ours is a valid token for this bot.
   Telegram keeps exactly ONE valid token per bot, so if ours were the signing
   token the HMAC would match. It does not — therefore the value THIS PROCESS
   loaded is not the one BotFather holds now, even though it was valid once.
   "Revoke current token" only mints a third token; if the deployment is
   reading from somewhere other than the field being edited (a second
   variable, an env group or Blueprint re-applying an old value, a service
   that never restarted, a truncated paste), the new token lands in the same
   place and nothing changes. Which is exactly what was reported: a new bot,
   a saved token, an unchanged error.

WHAT MAKES IT CHECKABLE BY THE OWNER. Until now the deployed secret could not
be compared with BotFather's, because it must never be printed.
token_fingerprint() publishes a one-way sha256 prefix of the whole token plus
its length, so the owner runs the same digest on the token BotFather shows
them and compares 12 characters. Equal -> the right value is deployed.
Different -> this process is running something else, and revoking is futile.
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
os.environ["DB_PATH"] = os.path.join(_tmp, "tm.db")
os.environ["LIVE_PORT_MIN"] = "18600"
os.environ["LIVE_PORT_MAX"] = "18699"

BOT_ID = 8221572217
DEPLOYED = f"{BOT_ID}:AAdeployedValueNotTheCurrentOne1"
CURRENT = f"{BOT_ID}:AAwhatBotFatherActuallyHasNow12"
os.environ["BOT_TOKEN"] = DEPLOYED
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


def payload(sign_token, ed_priv=None):
    f = {"auth_date": str(int(time.time())),
         "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
         "user": json.dumps(USER, separators=(",", ":")).replace("/", r"\/")}
    dcs = "\n".join(f"{k}={f[k]}" for k in sorted(f))
    sec = hmac.new(b"WebAppData", sign_token.encode(), hashlib.sha256).digest()
    h = hmac.new(sec, dcs.encode(), hashlib.sha256).hexdigest()
    if ed_priv is not None:
        f["signature"] = base64.urlsafe_b64encode(
            ed_priv.sign((f"{BOT_ID}:WebAppData\n" + dcs).encode())
        ).decode().rstrip("=")
    return ("&".join(f"{k}={quote(f[k], safe='')}" for k in sorted(f))
            + f"&hash={h}")


c = TestClient(APP.app)


# ---------------------------------------------------------------------------
print("[1] the live token check always runs — no more token_live=None")
# ---------------------------------------------------------------------------
SRC = open(os.path.join(ROOT, "routes/auth.py"), encoding="utf-8").read()
_live_block = SRC[SRC.index('_live = {"ok": None}'):SRC.index('hint = ""')]
check("it is not gated on the signature result",
      "if not _tp.get" not in _live_block, _live_block[:160])
check("token_live is still reported in the log", "token_live=%s" in SRC)


# ---------------------------------------------------------------------------
print("[2] valid signature + valid token => NOT 'revoke again'")
# ---------------------------------------------------------------------------
if not HAVE_CRYPTO:
    check("cryptography available", False, "pip install cryptography")
else:
    _real = M._TG_PUBKEY_PROD
    tg = Ed25519PrivateKey.generate()
    M._TG_PUBKEY_PROD = tg.public_key().public_bytes_raw().hex()

    # Exactly the reported state: Telegram signed with the CURRENT secret,
    # our deployed token is a different (but getMe-valid) value.
    M.whoami = lambda timeout_s=6.0: {"ok": True, "bot_id": BOT_ID,
                                      "username": "myAutomaitBot"}
    M._LIVE_CACHE.update(token=None, at=0, value=None)
    APP._BOT_IDENTITY.update(checked=False, value=None)

    r = c.post("/auth/telegram/miniapp",
               json={"init_data": payload(CURRENT, ed_priv=tg)})
    d = r.json().get("detail", "")
    check("the owner is NOT told to revoke", "Revoke current token" not in d, d)
    check("it says the running value is not BotFather's",
          "not the one in @BotFather" in d, d)
    check("and points at overrides / restart as the cause",
          "overriding" in d and "restart" in d, d)
    check("still a 400", r.status_code == 400, str(r.status_code))

    # CONTRAST: token genuinely rejected by Telegram -> revoke/copy IS right.
    M.whoami = lambda timeout_s=6.0: {"ok": False,
                                      "reason": "rejected_by_telegram",
                                      "detail": "Unauthorized"}
    M._LIVE_CACHE.update(token=None, at=0, value=None)
    r2 = c.post("/auth/telegram/miniapp",
                json={"init_data": payload(CURRENT, ed_priv=tg)})
    d2 = r2.json().get("detail", "")
    check("a rejected token says so plainly",
          "no longer valid" in d2 and "BotFather" in d2, d2)
    check("and the two cases give DIFFERENT advice", d != d2)
    M._TG_PUBKEY_PROD = _real


# ---------------------------------------------------------------------------
print("[3] the owner can compare the deployed token without seeing it")
# ---------------------------------------------------------------------------
os.environ["BOT_TOKEN"] = DEPLOYED
fp = M.token_fingerprint()
check("a digest of the deployed token is published",
      fp["sha256_12"] == hashlib.sha256(DEPLOYED.encode()).hexdigest()[:12])
check("it differs for the token BotFather holds",
      fp["sha256_12"] != hashlib.sha256(CURRENT.encode()).hexdigest()[:12])
check("the secret itself never appears",
      DEPLOYED.split(":")[1] not in json.dumps(fp))
check("only 12 hex chars are exposed", len(fp["sha256_12"]) == 12)
check("the comparison command is spelled out", "sha256sum" in fp["compare_with"])
check("a truncated paste is measurable",
      fp["secret_length"] == len(DEPLOYED.split(":")[1])
      and fp["secret_length_expected"] == 35)

ASRC = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
check("/health exposes the fingerprint", "telegram_token_fingerprint" in ASRC)
BSRC = open(os.path.join(ROOT, "services/pingbot.py"), encoding="utf-8").read()
check("and it is logged at boot, before anyone fails to sign in",
      "sha256:%s" in BSRC)
check("a short secret is called out at boot", "LOOKS TRUNCATED" in BSRC)


# ---------------------------------------------------------------------------
print("[4] nothing was loosened")
# ---------------------------------------------------------------------------
M.whoami = lambda timeout_s=6.0: {"ok": True, "bot_id": BOT_ID,
                                  "username": "myAutomaitBot"}
M._LIVE_CACHE.update(token=None, at=0, value=None)
good = payload(DEPLOYED)                      # signed with OUR token
r3 = c.post("/auth/telegram/miniapp", json={"init_data": good})
check("a correctly signed payload still signs in", r3.status_code == 200,
      f"{r3.status_code} {r3.text[:100]}")
r4 = c.post("/auth/telegram/miniapp",
            json={"init_data": good.replace("6543210", "6543211")})
check("a tampered payload is still refused", r4.status_code == 400)

# The fingerprint is a diagnostic, never an input to the decision.
check("token_fingerprint is not consulted on the auth path",
      "token_fingerprint" not in SRC)


print(f"\ntest_token_mismatch: {_pass} passed, {_fail} failed")
sys.exit(1 if _fail else 0)
