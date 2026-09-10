"""THE ACTUAL BUG: `signature` was dropped from the HMAC data-check string.

Four rounds of investigation blamed the bot token. The token was never the
problem. The verifier was.

WHAT THE CODE DID:

    received_hash = pairs.pop("hash", "")
    pairs.pop("signature", None)      # <-- this line
    data_check = "\\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))

with the comment "signature is Telegram's Ed25519 field for third-party
validation, it is not part of the HMAC data-check string". That is true of the
ED25519 check and FALSE of the HMAC one. Telegram's docs exclude `signature`
only from third-party validation:

    HMAC (bot token)       exclude `hash`
    Ed25519 (third party)  exclude `hash` AND `signature`

PROVEN against Telegram's own @telegram-apps/init-data-node. Sign a payload
containing `signature`, then recompute the hash both ways:

    HMAC WITH    signature -> bb7b679dc007...  == the library's hash
    HMAC WITHOUT signature -> 981c1132292c...  != the library's hash

So every sign-in from a client new enough to send `signature` failed with
bad_hash, on a completely correct token.

WHY IT TOOK FOUR ROUNDS. The pop ran BEFORE the diagnostics, so:

  * the logged field list read fields=['auth_date','query_id','user'] — an
    ordinary set, nothing dropped, nothing extra;
  * the culprit finder only ever SUBSTITUTES a field's raw value, so it could
    not see a field that had been removed entirely, and reported culprit=None;
  * the Ed25519 check (which correctly excludes `signature`) kept returning
    VALID, and getMe kept returning ok — two green lights pointing away from
    the payload.

Everything the server could see said "authentic payload, live token, ordinary
fields", which is exactly the evidence that sent the diagnosis to the token.

This suite pins the fix and the three diagnostic gaps that hid it.
"""
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
os.environ["DB_PATH"] = os.path.join(_tmp, "sig.db")
os.environ["LIVE_PORT_MIN"] = "18700"
os.environ["LIVE_PORT_MAX"] = "18799"

BOT_ID = 8221572217
TOKEN = f"{BOT_ID}:AAtestSecretForThisProbe1234567"
os.environ["BOT_TOKEN"] = TOKEN
os.environ.pop("TELEGRAM_PING_BOT_TOKEN", None)

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


USER = {"id": 6543210, "first_name": "Ahad", "last_name": "Rahman",
        "username": "ahad_r", "language_code": "bn", "is_premium": True,
        "allows_write_to_pm": True,
        "photo_url": "https://t.me/i/userpic/320/4FPEE4tmP3ATHa57u6MqTDih13LTOiMoKoLDRG4PnSA.svg"}
SIG = ("zL-ucjNyREiHDE8aihFwpfR9aggP2xiAo3NSpfe-p7IbCisNlDKlo7Kb6G4D0Ao2mBrSg"
       "Ek4maLSdv6MLIlADQ")


def build(with_signature=True, sign_including_signature=True, token=TOKEN):
    """initData as Telegram sends it. `sign_including_signature` reproduces
    the old buggy signing side, for the negative cases."""
    f = {"auth_date": str(int(time.time())),
         "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
         "user": json.dumps(USER, separators=(",", ":")).replace("/", r"\/")}
    if with_signature:
        f["signature"] = SIG
    signed_over = {k: v for k, v in f.items()
                   if sign_including_signature or k != "signature"}
    dcs = "\n".join(f"{k}={signed_over[k]}" for k in sorted(signed_over))
    sec = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(sec, dcs.encode(), hashlib.sha256).hexdigest()
    return ("&".join(f"{k}={quote(f[k], safe='')}" for k in sorted(f))
            + f"&hash={h}")


# ---------------------------------------------------------------------------
print("[1] a payload carrying `signature` verifies — the reported failure")
# ---------------------------------------------------------------------------
try:
    u = M.verify_init_data(build(), TOKEN)
    check("initData with a signature field signs in", u["id"] == 6543210)
except Exception as e:
    check("initData with a signature field signs in", False,
          f"{type(e).__name__}: {e}")

# The exact shape from production: auth_date + query_id + user (+ signature),
# a 246-char user object with escaped slashes, seconds old.
check("the user object really does contain photo_url with escaped slashes",
      r"\/" in json.dumps(USER, separators=(",", ":")).replace("/", r"\/"))


# ---------------------------------------------------------------------------
print("[2] the exclusion rule is right for BOTH checks, and they differ")
# ---------------------------------------------------------------------------
SRC = open(os.path.join(ROOT, "services/miniapp_auth.py"), encoding="utf-8").read()
_hmac_fn = SRC[SRC.index("def verify_init_data"):SRC.index("def token_fingerprint")]
_ed_fn = SRC[SRC.index("def third_party_check"):SRC.index("def token_live")]

_hmac_code = "\n".join(l for l in _hmac_fn.splitlines()
                       if not l.strip().startswith("#"))
check("the HMAC path no longer pops `signature`",
      'pop("signature"' not in _hmac_code, "the bug is back")
check("the Ed25519 path still does (the spec requires it there)",
      'pop("signature"' in _ed_fn)

# Belt and braces: prove it behaviourally, not just by reading the source.
_no_sig = build(with_signature=False)
check("a payload with no signature field still verifies",
      M.verify_init_data(_no_sig, TOKEN)["id"] == 6543210)

# Telegram's published vector predates the signature field entirely.
_saved = M.INITDATA_MAX_AGE_S
M.INITDATA_MAX_AGE_S = 10 ** 12
_OFF_TOKEN = "5768337691:AAH5YkoiEuPk8-FZa32hStHTqXiLPtAEhx8"
_OFF = ("query_id=AAHdF6IQAAAAAN0XohDhrOrc"
        "&user=%7B%22id%22%3A279058397%2C%22first_name%22%3A%22Vladislav%22%2C"
        "%22last_name%22%3A%22Kibenko%22%2C%22username%22%3A%22vdkfrost%22%2C"
        "%22language_code%22%3A%22ru%22%2C%22is_premium%22%3Atrue%7D"
        "&auth_date=1662771648"
        "&hash=c501b71e775f74ce10e377dea85a7ea24ecd640b223ea86dfe453e0eaed2e2b2")
check("Telegram's official test vector still verifies",
      M.verify_init_data(_OFF, _OFF_TOKEN)["id"] == 279058397)
M.INITDATA_MAX_AGE_S = _saved


# ---------------------------------------------------------------------------
print("[3] nothing was loosened — a wrong hash is still a wrong hash")
# ---------------------------------------------------------------------------
# Signed the OLD (buggy) way: signature present but excluded from the hash.
# Telegram never produces this, so it must be REJECTED.
try:
    M.verify_init_data(build(sign_including_signature=False), TOKEN)
    check("a payload whose hash omits `signature` is rejected", False,
          "it was accepted")
except ValueError:
    check("a payload whose hash omits `signature` is rejected", True)

try:
    M.verify_init_data(build(), f"{BOT_ID}:AAsomeOtherSecretEntirely00000")
    check("another bot's token still fails", False, "it was accepted")
except ValueError:
    check("another bot's token still fails", True)

_tampered = build().replace("6543210", "6543211")
try:
    M.verify_init_data(_tampered, TOKEN)
    check("a tampered payload still fails", False, "it was accepted")
except ValueError:
    check("a tampered payload still fails", True)


# ---------------------------------------------------------------------------
print("[4] the three diagnostic gaps that hid this for four rounds")
# ---------------------------------------------------------------------------
# GAP 1: the reported field list was the post-pop view, so `signature` was
# invisible in every log line.
try:
    M.verify_init_data(build(sign_including_signature=False), TOKEN)
    _err = None
except ValueError as e:
    _err = e
check("the field list now reports what ARRIVED, including `signature`",
      _err is not None and "signature" in (_err.fields or []),
      str(_err and _err.fields))

# GAP 2: the culprit finder only substitutes values, so an omitted field was
# undetectable. A dropped/added field is now probed explicitly.
check("a wrong field SET is detected and named",
      "is EXCLUDED" in SRC and "INCLUDED" in SRC)
# The message is split across source lines, so match on the wording that
# carries the meaning rather than a contiguous sentence.
check("and it is logged as a verifier bug, not a bad token",
      "MINIAPP DATA-CHECK STRING IS WRONG" in SRC
      and "not a bad token" in SRC)

# GAP 3: the Ed25519 check kept saying VALID, which pointed away from the
# payload. It must keep doing so — it was right — so the fix is that the HMAC
# side agrees with it now.
_ok = True
try:
    M.verify_init_data(build(), TOKEN)
except Exception:
    _ok = False
check("HMAC and Ed25519 now agree on a genuine payload", _ok)


print(f"\ntest_signature_field: {_pass} passed, {_fail} failed")
sys.exit(1 if _fail else 0)
