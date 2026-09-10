"""Verification for Telegram Mini App `initData`.

WHY THIS IS NOT /auth/telegram
------------------------------
The Login Widget and the Mini App both prove the same Telegram identity, but
they derive the HMAC key differently. Demonstrated on the same data-check
string with the same bot token:

    Login Widget  secret = sha256(token)                  -> b1a8455e4830…
    Mini App      secret = HMAC("WebAppData", token)      -> 3b019fac3ba6…

So initData posted to /auth/telegram is rejected as tampered. A separate
verifier is required; reusing the old one would either fail every Mini App
login or, if "fixed" by loosening the check, accept forged data.

WHAT initData IS
----------------
A urlencoded query string Telegram hands the webview, e.g.

    user=%7B%22id%22%3A555%2C...%7D&chat_instance=-1&auth_date=1700000000&hash=abc

Every field except `hash` (and `signature`, which is Ed25519 for third-party
validation and explicitly excluded) goes into the data-check string as
"key=value" lines sorted by key and joined with \n.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import parse_qsl

logger = logging.getLogger("codenest-app")


class BadHash(ValueError):
    """A signature mismatch, carrying the payload's SHAPE for diagnosis.

    Subclasses ValueError so every existing `except ValueError` still catches
    it and str() still returns "bad_hash" for the callers that compare on that.
    """

    def __init__(self, fields, lengths, culprit=None, age_s=None):
        super().__init__("bad_hash")
        self.fields = fields
        self.lengths = lengths
        # The field whose DECODING differs from Telegram's, when one can be
        # identified. None means the mismatch is not a decoding difference —
        # which leaves only one explanation: the signing KEY differs.
        self.culprit = culprit
        # Seconds since Telegram signed it. A few seconds means the payload is
        # fresh and the secret is wrong right now; a large value would mean a
        # replayed session instead.
        self.age_s = age_s

# Telegram signs auth_date, so without an age limit a leaked initData string
# would be a permanent credential. Telegram's own guidance is to bound it;
# a Mini App session is refreshed on every open, so this can be tight.
INITDATA_MAX_AGE_S = int(os.getenv("MINIAPP_INITDATA_MAX_AGE_S", "86400"))
# Clock skew allowance for a device running slightly ahead of the server.
_FUTURE_SKEW_S = 300


def _bot_token() -> str:
    """The bot token, cleaned of the ways a hosting UI mangles it.

    Reads BOT_TOKEN first — the one variable meant to be set — and falls
    back to TELEGRAM_PING_BOT_TOKEN so a deployment already using the old
    name keeps working with no migration step. Both names mean the same
    thing; BOT_TOKEN is the one to use going forward.

    Every one of these produced bad_hash with a token that was otherwise
    CORRECT, and none of them is distinguishable on a phone:

        quoted in the Render UI   "123:ABC"   -> bad_hash
        pasted with an @ prefix   @123:ABC    -> bad_hash

    strip() already handled stray whitespace and newlines. Quotes and a
    leading @ are the two remaining paste accidents, so they are removed here
    rather than left to fail silently as a signature mismatch.
    """
    raw = (os.getenv("BOT_TOKEN", "").strip()
           or os.getenv("TELEGRAM_PING_BOT_TOKEN", "").strip())
    return _clean_token(raw)


def _clean_token(raw: str) -> str:
    """Strip the wrappers a hosting UI adds to a pasted value."""
    raw = (raw or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1].strip()
    return raw.lstrip("@").strip()


def token_sources() -> dict:
    """Which env var supplied the token, and whether a SECOND one disagrees.

    THE TRAP THIS EXPOSES, reproduced: BOT_TOKEN silently outranks
    TELEGRAM_PING_BOT_TOKEN, but render.yaml documents only the LATTER. So an
    owner who follows render.yaml, pastes a NEW bot's token into
    TELEGRAM_PING_BOT_TOKEN, and leaves an OLD BOT_TOKEN behind from an
    earlier attempt keeps running on the OLD bot:

        only TELEGRAM_PING_BOT_TOKEN = NEW            -> NEW  ok
        only BOT_TOKEN               = NEW            -> NEW  ok
        BOT_TOKEN=OLD + TELEGRAM_PING_BOT_TOKEN=NEW   -> OLD  <- silent

    Nothing reported that two different tokens were configured, so the site
    looked correctly reconfigured while every sign-in was still checked
    against the bot the owner thought they had replaced. Only the bot ID half
    is ever exposed here; it is public.
    """
    names = ("BOT_TOKEN", "TELEGRAM_PING_BOT_TOKEN")
    found = {}
    for n in names:
        tok = _clean_token(os.getenv(n, ""))
        if tok:
            found[n] = tok.partition(":")[0] or None
    used = "BOT_TOKEN" if "BOT_TOKEN" in found else (
        "TELEGRAM_PING_BOT_TOKEN" if found else None)
    ids = set(found.values())
    return {
        "set": sorted(found),
        "used": used,
        "bot_ids": {k: v for k, v in found.items()},
        # Two names holding DIFFERENT bots is always a mistake, and it is the
        # one an owner cannot see from the dashboard.
        "conflict": len(ids) > 1,
    }


def token_fingerprint() -> dict:
    """A safe way to compare the DEPLOYED token against the one in BotFather.

    WHY THIS HAD TO EXIST. A sign-in can now be narrowed all the way down to
    "the value this process is running with is not the one BotFather has" —
    but the owner still cannot SEE that, because the secret must never be
    printed. So the two sides could not be compared, and the only remaining
    advice was to re-paste and hope. Reported twice in exactly that shape: a
    token was replaced, the deploy went green, the error did not move.

    A short salted digest fixes it without revealing anything. The owner runs
    the same one-liner on the token BotFather shows them:

        printf '%s' '<token>' | sha256sum

    and compares the first 12 characters against `sha256_12` here. Equal means
    the right value is deployed and the fault is elsewhere; different means
    the process is running something else — a second variable, an env group,
    a stale build, a truncated paste — and no amount of revoking will help.

    sha256 of the whole token is a one-way digest: 12 hex characters (48 bits)
    is far too little to reverse or brute-force a 35-character secret, and it
    is only ever exposed on an admin-visible diagnostic. `length` is included
    because a truncated paste is the one corruption a digest alone cannot
    describe helpfully — a real token's secret half is 35 characters.
    """
    tok = _bot_token()
    if not tok:
        return {"configured": False}
    bot_id, sep, secret = tok.partition(":")
    return {
        "configured": True,
        "bot_id": bot_id if (sep and bot_id.isdigit()) else None,
        "length": len(tok),
        "secret_length": len(secret),
        "secret_length_expected": 35,
        "sha256_12": hashlib.sha256(tok.encode()).hexdigest()[:12],
        "compare_with": "printf '%s' '<token from BotFather>' | sha256sum",
    }


def token_shape() -> dict:
    """A description of the configured token that reveals nothing secret.

    A bot token is "<numeric bot id>:<35-char secret>". The bot ID half is
    PUBLIC — it is visible to anyone who can message the bot — so reporting it
    lets an owner check at a glance whether the server holds the same bot the
    Mini App was opened from. The secret half is never touched.
    """
    tok = _bot_token()
    if not tok:
        return {"configured": False}
    bot_id, sep, secret = tok.partition(":")
    return {
        "configured": True,
        "bot_id": bot_id if (sep and bot_id.isdigit()) else None,
        # Shape only, and deliberately loose. A real secret half is ~34-35
        # chars, but the point of this flag is to catch a value that is
        # obviously NOT a token — a bot username, a URL, an empty string —
        # not to police length. I first used >= 30, which is close enough to
        # the real length to reject legitimate variation for no benefit.
        "looks_valid": bool(sep and bot_id.isdigit() and len(secret) >= 10),
    }


def _raw_pairs(init_data: str) -> dict:
    """Field values EXACTLY as they arrived, with no percent-decoding.

    parse_qsl decodes, which is correct per Telegram's spec. This is the
    undecoded view, used only to work out which field's decoding differs when
    a signature fails.
    """
    out = {}
    for chunk in (init_data or "").split("&"):
        if "=" in chunk:
            k, _, v = chunk.partition("=")
            out[k] = v
    return out


def verify_init_data(init_data: str, token: str = None) -> dict:
    """Validate initData and return the Telegram user, or raise ValueError.

    Returns {"id": int, "first_name": str, "username": str, "auth_date": int,
             "raw": {...}}.
    """
    token = token if token is not None else _bot_token()
    if not token:
        raise ValueError("not_configured")
    if not init_data or not isinstance(init_data, str):
        raise ValueError("empty")
    # A whole initData string is small; anything large is someone probing.
    if len(init_data) > 8192:
        raise ValueError("too_large")

    # keep_blank_values: Telegram includes empty fields, and dropping them
    # changes the data-check string and therefore the hash.
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        raise ValueError("malformed")

    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise ValueError("no_hash")

    # `signature` STAYS IN. THIS LINE WAS THE BUG.
    #
    # It used to be popped here, with the comment "signature is Telegram's
    # Ed25519 field for third-party validation, it is not part of the HMAC
    # data-check string". That is true of the ED25519 check and false of this
    # one, and conflating the two broke every sign-in from any client new
    # enough to send the field.
    #
    # Telegram's docs spell out the exclusion only for third-party validation:
    #
    #   HMAC (this function)   exclude `hash`
    #   Ed25519 (third party)  exclude `hash` AND `signature`
    #
    # Verified against Telegram's own @telegram-apps/init-data-node: sign a
    # payload containing `signature`, then recompute both ways —
    #
    #   HMAC WITH    signature -> bb7b679dc007...  == the library's hash
    #   HMAC WITHOUT signature -> 981c1132292c...  != the library's hash
    #
    # so the field is part of the signed string. Dropping it changed the bytes
    # and produced bad_hash for a payload that was perfectly valid.
    #
    # WHY IT SURVIVED THIS LONG. The pop happened BEFORE the diagnostics were
    # built, so `signature` was missing from the recorded field list too:
    # every log line read fields=['auth_date','query_id','user'] — an
    # ordinary-looking set with nothing dropped or extra — which is exactly
    # what sent the investigation towards the token instead of the payload.
    # The culprit finder could not see it either: it substitutes each field's
    # raw form one at a time and never re-adds a field that is gone, so it
    # reported culprit=None. Reproduced end to end before this change.
    #
    # The older `pop` was also self-fulfilling: it was added on the reasoning
    # that leaving the field in "makes every verification fail once Telegram
    # starts sending it". The opposite is the case.

    data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    # compare_digest, not ==: a plain comparison leaks the position of the
    # first mismatching byte through timing.
    if not hmac.compare_digest(expected, received_hash):
        # WHY THIS RECORDS DETAIL: bad_hash has been reported with a token that
        # getMe confirms belongs to the right bot. When the token is right and
        # the hash is still wrong, the payload itself must differ from what was
        # signed — and no amount of guessing from outside can say how.
        #
        # Only NON-SECRET structure is recorded: which field names arrived, and
        # their lengths. Never a value, never the token, never the user's data.
        # That is enough to spot the two things that actually break this: a
        # field the signer included but we dropped, or an extra field we kept.
        # The field list came back completely normal — nothing dropped, nothing
        # extra — so the difference is in a VALUE, not the set of keys. The
        # only way to find which one from the outside is to re-run the HMAC
        # with each field's raw (still-percent-encoded) form substituted in
        # turn: whichever substitution makes the hash match is the field whose
        # decoding differs from Telegram's.
        #
        # This is diagnosis, not a fallback: the result is reported, never
        # accepted. A payload that only verifies under a substitution has NOT
        # been validly signed for us.
        # WHICH BOT ACTUALLY SENT THIS?
        #
        # I had been logging the bot_id of the SERVER's token and calling that
        # "the bot", which cannot detect the one case that matters: a payload
        # signed by a different bot. Telegram does not name the bot in
        # initData, but it does not have to — chat_instance and query_id are
        # bot-scoped, and more usefully, if the SAME bot id verifies with a
        # different secret then the token was revoked and reissued.
        #
        # Recording the auth_date age separates those: a freshly signed
        # payload that fails means the secret is wrong NOW, not that a stale
        # session was replayed.
        age_s = None
        try:
            age_s = int(time.time() - int(pairs.get("auth_date") or 0))
        except Exception:
            pass

        culprit = None
        try:
            raw_pairs = _raw_pairs(init_data)
            for k in pairs:
                if raw_pairs.get(k) == pairs[k]:
                    continue                      # nothing was decoded here
                probe = dict(pairs)
                probe[k] = raw_pairs[k]
                pc = "\n".join(f"{kk}={probe[kk]}" for kk in sorted(probe))
                if hmac.compare_digest(
                        hmac.new(secret, pc.encode(), hashlib.sha256).hexdigest(),
                        received_hash):
                    culprit = k
                    break
        except Exception:
            pass

        # DOES THE HASH MATCH IF A FIELD IS DROPPED OR RESTORED?
        #
        # The probe above only ever SUBSTITUTES a field's value. It cannot see
        # the failure that actually happened here: a field being excluded from
        # the data-check string entirely. `signature` was popped before this
        # code ran, so it was invisible to the substitution loop AND absent
        # from the reported field list — every log line looked like an
        # ordinary payload with nothing wrong, which is precisely why the
        # investigation kept pointing at the bot token instead.
        #
        # Trying each single-field omission, and the whole raw string, costs a
        # handful of HMACs on an already-failing request and turns "culprit
        # unknown" into a named field. Diagnosis only — the result is reported,
        # never accepted.
        set_error = None
        try:
            all_pairs = dict(parse_qsl(init_data, keep_blank_values=True))
            all_pairs.pop("hash", None)
            for k in sorted(all_pairs):
                probe = {kk: vv for kk, vv in all_pairs.items() if kk != k}
                pc = "\n".join(f"{kk}={probe[kk]}" for kk in sorted(probe))
                if hmac.compare_digest(
                        hmac.new(secret, pc.encode(), hashlib.sha256).hexdigest(),
                        received_hash):
                    set_error = f"hash matches when '{k}' is EXCLUDED"
                    break
            if set_error is None:
                # And the reverse: the string we hashed is missing a field the
                # signer included. `pairs` is what we used; all_pairs is
                # everything that arrived.
                extra = sorted(set(all_pairs) - set(pairs))
                if extra:
                    pc = "\n".join(f"{kk}={all_pairs[kk]}"
                                   for kk in sorted(all_pairs))
                    if hmac.compare_digest(
                            hmac.new(secret, pc.encode(),
                                     hashlib.sha256).hexdigest(),
                            received_hash):
                        set_error = ("hash matches when these are INCLUDED: "
                                     + ",".join(extra))
        except Exception:
            pass
        if set_error:
            logger.error(
                "MINIAPP DATA-CHECK STRING IS WRONG: %s. This is a bug in the "
                "verifier, not a bad token — the payload is correctly signed "
                "and we hashed the wrong set of fields.", set_error)
        # Report the field list AS IT ARRIVED, not as we chose to hash it.
        # Reporting the post-pop view is what hid `signature` from every log
        # line for three rounds of investigation.
        try:
            _arrived = sorted(
                k for k in dict(parse_qsl(init_data, keep_blank_values=True))
                if k != "hash")
        except Exception:
            _arrived = sorted(pairs.keys())
        raise BadHash(_arrived,
                      {k: len(str(v)) for k, v in sorted(pairs.items())},
                      culprit, age_s)

    try:
        auth_date = int(pairs.get("auth_date") or 0)
    except ValueError:
        raise ValueError("bad_auth_date")
    age = time.time() - auth_date
    if auth_date <= 0 or age > INITDATA_MAX_AGE_S:
        raise ValueError("expired")
    if age < -_FUTURE_SKEW_S:
        raise ValueError("future")

    raw_user = pairs.get("user") or ""
    if not raw_user:
        # Happens when the Mini App is opened from an inline query or a channel
        # rather than a private chat. There is no user to log in as.
        raise ValueError("no_user")
    try:
        user = json.loads(raw_user)
    except Exception:
        raise ValueError("bad_user_json")
    tg_id = user.get("id")
    if not isinstance(tg_id, int) or tg_id <= 0:
        raise ValueError("bad_user_id")

    return {
        "id": tg_id,
        "first_name": (user.get("first_name") or "").strip()[:64],
        "last_name": (user.get("last_name") or "").strip()[:64],
        "username": (user.get("username") or "").strip()[:64],
        "photo_url": (user.get("photo_url") or "").strip()[:500],
        "auth_date": auth_date,
        "raw": user,
    }


# Telegram's Ed25519 public keys for THIRD-PARTY validation. Published by
# Telegram; not secret.
_TG_PUBKEY_PROD = "e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d"
_TG_PUBKEY_TEST = "40055058a4ee38156a06562e52eece92a771bcd8346a8c4615cb7376eddf72ec"


def third_party_check(init_data: str, bot_id) -> dict:
    """Is this payload genuinely from Telegram, judged WITHOUT our bot token?

    THIS IS THE CHECK THAT ENDS THE GUESSING, and it is why it was added.

    Telegram signs initData twice:

        hash       HMAC-SHA256 keyed with the BOT TOKEN   (verify_init_data)
        signature  Ed25519 with TELEGRAM'S OWN key        (this function)

    The Ed25519 half needs only the PUBLIC bot id, so it is independent of
    whatever value sits in BOT_TOKEN. That independence is the whole point:

        signature VALID  + hash invalid  -> the payload is authentic and
                                            issued for THIS bot id, so the
                                            fault is the SECRET half of our
                                            token. Nothing else fits.
        signature INVALID                -> the payload was not signed for
                                            this bot id (another bot, or a
                                            forgery).

    Until now the server could not tell those apart. getMe cannot do it: it
    only proves the token is *a* live token, its result is cached at boot, and
    a token that is live can still be the wrong one for the payload in hand.
    Every previous verdict was therefore inferred, and one of them ("your
    token is out of date") was wrong often enough to send an owner round in
    circles replacing a bot that was never the problem.

    Never used to ACCEPT a login — only to explain a rejection. A payload that
    fails the HMAC is refused whatever this returns.

    Returns {"ok": bool, "reason": str}; "unavailable" when the optional
    cryptography dependency or the signature field is absent, which must never
    be read as a verdict either way.
    """
    if not init_data or bot_id in (None, ""):
        return {"ok": False, "reason": "unavailable"}
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
        from cryptography.exceptions import InvalidSignature
    except Exception:
        return {"ok": False, "reason": "unavailable"}

    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return {"ok": False, "reason": "unavailable"}
    sig_b64 = pairs.pop("signature", "")
    pairs.pop("hash", None)
    if not sig_b64:
        # Older clients do not send it. Absence proves nothing.
        return {"ok": False, "reason": "no_signature"}

    # Telegram omits base64 padding; some decoders reject that.
    try:
        sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
    except Exception:
        return {"ok": False, "reason": "bad_signature_encoding"}

    dcs = (f"{bot_id}:WebAppData\n"
           + "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs)))
    for key_hex, env in ((_TG_PUBKEY_PROD, "prod"), (_TG_PUBKEY_TEST, "test")):
        try:
            Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(key_hex)).verify(sig, dcs.encode())
            return {"ok": True, "reason": f"telegram_{env}"}
        except InvalidSignature:
            continue
        except Exception:
            return {"ok": False, "reason": "unavailable"}
    return {"ok": False, "reason": "not_signed_for_this_bot"}


_LIVE_CACHE = {"token": None, "at": 0.0, "value": None}
_LIVE_TTL_S = 60


def token_live(timeout_s: float = 4.0) -> dict:
    """Is the CONFIGURED token still valid, checked NOW rather than at boot?

    whoami()/_bot_identity() answer a similar question but cache the result
    for the life of the process, and that cache is load-bearing in the wrong
    direction: a token replaced in the hosting dashboard after boot, or a boot
    that happened while api.telegram.org was briefly unreachable, leaves the
    server confidently reporting an identity it has not re-tested. That is how
    /health can show a healthy bot while every Mini App sign-in fails.

    Telegram keeps exactly ONE valid token per bot — revoking issues a new one
    and invalidates the old one immediately — so this is decisive:

        ok=True   the token we hold is current; a bad_hash is NOT a stale
                  secret and must be explained some other way.
        ok=False  Telegram rejects it (401). That IS the stale/wrong token,
                  established rather than guessed.
        ok=None   Telegram unreachable; no verdict, and none is reported.

    Cached for 60s and keyed on the token itself, so a burst of failing
    sign-ins costs one request, and changing the token invalidates it at once.
    """
    tok = _bot_token()
    if not tok:
        return {"ok": False, "reason": "not_configured"}
    now = time.time()
    if (_LIVE_CACHE["token"] == tok
            and now - _LIVE_CACHE["at"] < _LIVE_TTL_S
            and _LIVE_CACHE["value"] is not None):
        return _LIVE_CACHE["value"]

    who = whoami(timeout_s=timeout_s)
    if who.get("ok"):
        out = {"ok": True, "bot_id": who.get("bot_id"),
               "username": who.get("username")}
    elif who.get("reason") == "rejected_by_telegram":
        out = {"ok": False, "reason": "rejected_by_telegram",
               "detail": who.get("detail", "")}
    else:
        # Unreachable is NOT a verdict. Reporting it as one would blame the
        # owner's token for our own network trouble.
        out = {"ok": None, "reason": who.get("reason", "unreachable")}
    _LIVE_CACHE.update(token=tok, at=now, value=out)
    return out


def whoami(timeout_s: float = 6.0) -> dict:
    """Ask Telegram which bot the configured token belongs to.

    This is the one check that settles a bad_hash. token_shape() can only say
    the value LOOKS like a token; getMe proves whose it is. Comparing the
    @username it returns against the bot whose Mini App was opened turns a
    guess into a fact.

    Never called on the auth path — it is a network round-trip, and a
    diagnostic must not slow down or break a working sign-in.
    """
    tok = _bot_token()
    if not tok:
        return {"ok": False, "reason": "not_configured"}
    try:
        import requests
        r = requests.get(f"https://api.telegram.org/bot{tok}/getMe",
                         timeout=timeout_s)
        d = r.json() or {}
    except Exception as exc:
        return {"ok": False, "reason": "unreachable", "detail": str(exc)[:120]}
    if not d.get("ok"):
        # Telegram rejecting the token is the clearest possible answer: the
        # value is not a live bot token at all.
        return {"ok": False, "reason": "rejected_by_telegram",
                "detail": str(d.get("description"))[:160]}
    res = d.get("result") or {}
    return {
        "ok": True,
        "bot_id": res.get("id"),
        "username": res.get("username"),
        "can_join_groups": res.get("can_join_groups"),
    }


def display_name(user: dict) -> str:
    """The label cached on the account, matching what the bot stores."""
    if user.get("username"):
        return "@" + user["username"]
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
    return name.strip()[:80]


_username_cache = {"value": None, "checked": False}


def bot_username() -> str:
    """The bot's @username, WITHOUT needing a second env var to say so.

    TELEGRAM_BOT_USERNAME used to be required alongside the token, and the
    two had to be kept in sync by hand — set the token to bot A but leave
    the username pointing at bot B (a stale value from before a token was
    regenerated) and nothing failed loudly; the Login Widget and deep links
    just quietly pointed at the wrong bot. The token already implies the
    username (that's what whoami() below is for), so this asks Telegram once
    and caches it, and TELEGRAM_BOT_USERNAME now only matters as a manual
    override for the rare case getMe is unreachable.

    Cached for the process lifetime: the token does not change without a
    restart, so neither does the bot it belongs to.
    """
    override = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
    if override:
        return override
    if not _username_cache["checked"]:
        _username_cache["checked"] = True
        who = whoami()
        if who.get("ok"):
            _username_cache["value"] = who.get("username") or None
    return _username_cache["value"] or ""
