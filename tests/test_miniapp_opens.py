"""THE MINI APP OPENS AND NOTHING HAPPENS — the four causes, pinned down.

Every check here was written against a REPRODUCTION, not a reading of the
code. The reproductions ran the real boot (index.html + miniapp.js + pro.js in
jsdom) against the real server, and the real poll loop against a fake Telegram
API. What they showed:

  1. NO DEADLINE ON THE SIGN-IN REQUEST.
     Render's free plan stops an idle service; the first request wakes it and
     takes 30-60s. fetch() has no default timeout, so __tgAutoLogin's promise
     never settled — .then() never ran, the boot never finished. Measured
     against a 30s-delayed login: the phone showed an empty dashboard for the
     whole wait, because index.html's 4s splash net had already fired.

  2. THE 4-SECOND SPLASH NET UNCOVERED NOTHING.
     Right in a browser (there is always a page underneath), wrong inside
     Telegram (there is not, until a token exists).

  3. THE AUTH-SCREEN HIDE LIST WAS AN ALLOW-LIST BY OMISSION.
     Observed visible during a slow boot:
         how, features, section, foot, screen-forgot-success, screen-dashboard
     — the marketing site and a "Password updated! Redirecting in 3…" card on
     top of the dashboard. #screen-forgot-success was in no list.

  4. A HARDCODED SITE_BASE DEFAULT.
     SITE_BASE_URL is `sync: false` in render.yaml (not set for you). The
     fallback was a literal host belonging to one particular install, so a
     deployment that missed that step built a button that opened SOMEONE
     ELSE'S site. Tap, and either the webview closes on a dead URL or a
     different server rejects the sign-in with a bot mismatch. Deploy green
     throughout.

Plus the bot-side counterpart: a 409 from getUpdates (stale webhook, or two
instances on one token) hit a branch that was `sleep(1); continue` with NO
logging, so the bot answered nothing and said nothing.
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")

_pass, _fail = 0, 0


def check(name, cond, extra=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  ok   {name}")
    else:
        _fail += 1
        print(f"  FAIL {name}" + (f" -> {extra}" if extra else ""))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


MINIAPP = read("static/miniapp.js")
PRO = read("static/pro.js")
INDEX = read("index.html")
CSS = read("static/app.css")
PINGBOT = read("services/pingbot.py")


# ---------------------------------------------------------------------------
print("[1] the sign-in request has a deadline and retries once")
# ---------------------------------------------------------------------------
check("miniapp.js aborts a request that never answers",
      "AbortController" in MINIAPP and "abort()" in MINIAPP)
check("the first attempt is bounded (20s)", "20000" in MINIAPP)
check("a second attempt is made, with a longer budget", "45000" in MINIAPP)

# The retry must be a NEW request, not a second await on the same promise: a
# queued retry behind a hung connection is not a retry. Two separate CALLS to
# a helper that builds a fresh fetch() each time is what proves that.
_calls = len(re.findall(r"await attempt\(", MINIAPP))
check("the retry issues a fresh request (two distinct calls)",
      _calls == 2, f"await attempt() x{_calls}")
check("...and each call builds its own fetch",
      re.search(r"const attempt\s*=.*?fetch\(", MINIAPP, re.S) is not None)

check("an aborted login reports something the user can act on",
      "AbortError" in MINIAPP and "waking up" in MINIAPP)


# ---------------------------------------------------------------------------
print("[2] the splash belongs to the Mini App until sign-in resolves")
# ---------------------------------------------------------------------------
check("pro.js claims ownership of the splash inside Telegram",
      "__tgBootOwned" in PRO)
check("index.html's 4s net stands down when it does",
      re.search(r"if\s*\(window\.__tgBootOwned\)\s*return", INDEX) is not None)
check("the 4s net still protects a normal browser", "4000" in INDEX)
check("a backstop still exists, so the splash cannot become permanent",
      "70000" in PRO)
check("the wait explains itself instead of spinning silently",
      "__tgBootNote" in PRO and "__tgBootNote" in MINIAPP)


# ---------------------------------------------------------------------------
print("[3] no marketing or auth surface can leak into the Mini App")
# ---------------------------------------------------------------------------
# By CLASS, so a screen added tomorrow is covered on the day it is added.
for sel in (".hero", ".section", ".foot", ".auth"):
    check(f"html.tg-no-auth {sel} is hidden",
          re.search(r"html\.tg-no-auth\s+" + re.escape(sel) + r"\b", CSS) is not None)

# THE CONTRACT: every id the stylesheet hides must also be refused by
# showScreen(), or the app hides the dashboard and then "shows" an element at
# display:none — a blank phone.
hidden_ids = set(re.findall(r"html\.tg-no-auth\s+#([\w-]+)", CSS))
block = re.search(r"const _TG_FORBIDDEN_SCREENS = \{(.*?)\};", PRO, re.S)
guarded = set(re.findall(r'"([\w-]+)"', block.group(1) if block else ""))
check("every CSS-hidden screen is also refused by showScreen()",
      hidden_ids and not (hidden_ids - guarded),
      f"unguarded: {sorted(hidden_ids - guarded)}")

# The one that was actually on screen in the reproduction.
check("the password-reset confirmation is covered (it was in neither list)",
      "screen-forgot-success" in hidden_ids
      and "screen-forgot-success" in guarded)


# ---------------------------------------------------------------------------
print("[4] the Mini App URL is this deployment's own, or it says so")
# ---------------------------------------------------------------------------
# Only CODE counts. The docstring quotes the old line verbatim to explain why
# it was removed, so a plain substring search matches its own explanation —
# strip comments and docstrings before looking.
_code_only = re.sub(r'"""[\s\S]*?"""', "", PINGBOT)
_code_only = "\n".join(l for l in _code_only.splitlines()
                       if not l.strip().startswith("#"))
_site_fn = _code_only[_code_only.index("def _site_base"):
                      _code_only.index("SITE_BASE = _site_base()")]
check("no hardcoded host is baked in as the Mini App fallback",
      "onrender.com" not in _site_fn,
      "a literal host is still used as the default SITE_BASE")
check("Render's own service URL is the fallback",
      "RENDER_EXTERNAL_URL" in PINGBOT)

import services.pingbot as PB  # noqa: E402

for name in ("SITE_BASE_URL", "PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL"):
    os.environ.pop(name, None)
check("with nothing configured, the URL is empty — not someone else's site",
      PB._site_base() == "")

os.environ["RENDER_EXTERNAL_URL"] = "https://svc-a.onrender.com"
check("Render's URL is used when present",
      PB._site_base() == "https://svc-a.onrender.com")

os.environ["SITE_BASE_URL"] = "https://custom.example/"
check("an explicit SITE_BASE_URL wins (custom domain), trailing / trimmed",
      PB._site_base() == "https://custom.example")
os.environ.pop("SITE_BASE_URL")
os.environ.pop("RENDER_EXTERNAL_URL")

# A button that is not there must not be advertised.
_saved_base, _saved_sent = PB.SITE_BASE, []
PB.SITE_BASE = ""
PB._send = lambda cid, text, reply_markup=None: _saved_sent.append((text, reply_markup))
PB.handle_start(1, "Ahad")
_txt, _kb = _saved_sent[-1]
check("with no URL configured, /start does NOT say 'tap below'",
      "Tap below" not in _txt, _txt[:80])
check("it names the missing setting instead",
      "SITE_BASE_URL" in _txt, _txt[:120])
check("and sends no empty keyboard", _kb is None, str(_kb))
PB.SITE_BASE = _saved_base


# ---------------------------------------------------------------------------
print("[5] a bot that cannot poll says so instead of dying quietly")
# ---------------------------------------------------------------------------
_loop = PINGBOT[PINGBOT.index("def poll_loop"):]
_loop = _loop[:_loop.index("def start_bot")]

check("a stale webhook is detected", "webhook is active" in _loop)
check("and deleted automatically, since this service polls",
      "deleteWebhook" in _loop)
check("a second poller on the same token is named",
      "terminated by other getupdates" in _loop.lower())
check("a rejected getUpdates is logged, not swallowed",
      "getUpdates failed" in _loop)
check("failures back off instead of hot-looping Telegram",
      "_fail_streak" in _loop and "time.sleep(min(" in _loop)
check("recovery is logged too", "polling recovered" in _loop)


# ---------------------------------------------------------------------------
print("[6] /health can answer 'where does the button point?'")
# ---------------------------------------------------------------------------
APP = read("app.py")
check("/health reports the resolved Mini App URL", '"miniapp_url"' in APP)
check("and explains an unusable one", "not_https" in APP and "not_configured" in APP)


print(f"\ntest_miniapp_opens: {_pass} passed, {_fail} failed")
sys.exit(1 if _fail else 0)
