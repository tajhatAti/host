"""CodeNest — RunSpace: free code/bot hosting.

Thin ASGI shell: app init, middleware, static mount, the SPA host (landing +
deep-link negotiation for client-routed sections), /terms, /health, and the
include_router lines for every domain module in routes/.
"""
import hashlib
import os
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from services import secrets_store, runner_client
from database import DIALECT, init_db  # noqa: F401  (init_db already ran via routes.deps)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("codenest-app")

BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "index.html"
TERMS_FILE = BASE_DIR / "terms.html"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="CodeNest — RunSpace")


import asyncio
import random
import httpx

async def _self_ping_loop():
    """Background scheduled task: sends a lightweight HTTP GET to the app's own
    /health endpoint every ~7 minutes to prevent Render free tier web service
    from spinning down after 15 minutes of inactivity. Hitting the external
    Render URL counts as real inbound traffic and keeps the service awake."""
    await asyncio.sleep(15)
    failures = 0
    while True:
        try:
            port = os.getenv("PORT", "8000")
            base = (
                os.getenv("RENDER_EXTERNAL_URL", "").strip()
                or os.getenv("SITE_BASE_URL", "").strip()
                or os.getenv("PUBLIC_BASE_URL", "").strip()
                or f"http://127.0.0.1:{port}"
            ).rstrip("/")
            url = f"{base}/health"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
            if failures:
                logger.info("Self-ping recovered after %d failures", failures)
                failures = 0
            logger.debug("Self-ping to %s ok (%s)", url, resp.status_code)
        except Exception as exc:
            failures += 1
            logger.warning("Self-ping failed (%d in a row): %s", failures, exc)
        # 7–8 min stays safely under Render's 15-minute idle threshold.
        delay = random.uniform(420, 480)
        await asyncio.sleep(delay)

@app.on_event("startup")
async def startup_event():
    # Encrypt any pre-existing plaintext bot environments before serving user
    # traffic. Local SQLite remains zero-config; production health reports a
    # missing key explicitly.
    try:
        from services import secrets_store
        secrets_store.migrate_job_envs()
    except Exception as exc:
        logger.error("Bot secret migration failed: %s", exc)
    try:
        from services import retention
        retention.cleanup()
    except Exception as exc:
        logger.warning("Retention cleanup failed: %s", exc)
    asyncio.create_task(_self_ping_loop())
    # A full Render deploy kills every subprocess. Desired-running bots are
    # recreated from their saved source/env after secret migration completes;
    # this runs in the background so the website still starts immediately.
    try:
        from services import job_recovery
        asyncio.create_task(job_recovery.recover_background())
    except Exception as exc:
        logger.warning("Bot recovery scheduler failed: %s", exc)
    # Telegram server-alive bot — starts automatically if TELEGRAM_PING_BOT_TOKEN is set
    try:
        from services.pingbot import start_bot as _start_pingbot
        _start_pingbot()
    except Exception as e:  # noqa: BLE001
        logger.warning("Ping bot failed to start: %s", e)
    # Watch job state and message the owner when an app stops on its own. The
    # runner cannot do this itself: it has no database and no Telegram token,
    # and with a worker pool that would mean the same credential on every box.
    try:
        from services.bot_notify import start_watcher as _start_watcher
        _start_watcher()
    except Exception as e:  # noqa: BLE001
        logger.warning("Bot state watcher failed to start: %s", e)
    # Periodically copy each job's data files (database.db, session.json, …)
    # into Postgres. On Render's free tier the runner's filesystem is rebuilt
    # on every deploy, so this is what makes a referral bot's points survive.
    try:
        from services.snapshots import start_sweeper as _start_sweeper
        _start_sweeper()
    except Exception as e:  # noqa: BLE001
        logger.warning("Snapshot sweeper failed to start: %s", e)


def _enable_embedded_runner() -> bool:
    """Single-service mode: when RUNNER_SERVICE_URL is NOT set, the job runner
    lives inside THIS process (one Render web service — the whole point of the
    consolidation). Two effects:

      1. services.runner_client talks to the runner through an in-process
         ASGI client instead of the network.
      2. The public /live/{slug}/* gateway (HTTP + WebSocket) is mounted on
         THIS app — the handlers are reused verbatim from runner.app.

    Setting RUNNER_SERVICE_URL restores the classic two-service layout and
    this function leaves everything alone (return False).
    """
    if os.getenv("RUNNER_SERVICE_URL", "").strip():
        return False
    import secrets as _secrets
    # runner.app reads SECRET at import; generate a throwaway internal one
    # unless the operator pinned their own.
    os.environ.setdefault("RUNNER_SERVICE_SECRET", _secrets.token_urlsafe(24))
    import runner.app as _rapp
    # Visitor-facing pages/URLs must point at THIS service, not a runner host.
    base = (os.getenv("SITE_BASE_URL", "").strip()
            or os.getenv("PUBLIC_BASE_URL", "").strip()
            or os.getenv("RENDER_EXTERNAL_URL", "").strip())


    if base and not _rapp.PUBLIC_BASE_URL:
        _rapp.PUBLIC_BASE_URL = base.rstrip("/")
    from services.proxy import router as _proxy_router
    app.include_router(_proxy_router)
    logger.info("Embedded runner ACTIVE — jobs + /live gateway run in this process.")
    return True


EMBEDDED_RUNNER = _enable_embedded_runner()

_cors_origins = [x.strip().rstrip("/") for x in
                 os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if x.strip()]
for _origin in (os.getenv("SITE_BASE_URL", ""), os.getenv("RENDER_EXTERNAL_URL", "")):
    if _origin.strip().rstrip("/") and _origin.strip().rstrip("/") not in _cors_origins:
        _cors_origins.append(_origin.strip().rstrip("/"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=not (not _cors_origins),
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Fingerprint"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# -------------------------------
# Static asset cache-busting
# -------------------------------
# index.html shipped a HARDCODED "?v=20260724m" on every css/js link, so once a
# browser cached those files it kept the old copies after every deploy — fixes
# looked like they had not shipped at all. The version is now derived from the
# real contents of the asset files, so it changes automatically whenever one of
# them changes (and stays stable when nothing changed, preserving caching).
def _asset_version() -> str:
    h = hashlib.sha1()
    try:
        for f in sorted(STATIC_DIR.rglob("*")):
            if f.suffix.lower() in (".css", ".js", ".svg") and f.is_file():
                h.update(f.name.encode())
                h.update(str(f.stat().st_mtime_ns).encode())
                h.update(str(f.stat().st_size).encode())
        if INDEX_FILE.exists():
            h.update(str(INDEX_FILE.stat().st_mtime_ns).encode())
    except Exception as exc:  # pragma: no cover - never block page delivery
        logger.warning("asset version fallback: %s", exc)
        return "dev"
    return h.hexdigest()[:12]


ASSET_VERSION = _asset_version()
logger.info("Static asset version: %s", ASSET_VERSION)

_VERSION_RE = re.compile(r'(/static/[^"\'?]+\.(?:css|js|svg))\?v=[^"\']*')


# The admin console's markup ships inside index.html. The SPA already removes
# it from the DOM for non-admins, but that is client-side: anyone could read
# it straight out of the HTML source. Strip it SERVER-SIDE unless the request
# proves it belongs to an admin, so the console's very existence is not
# advertised in a page every anonymous visitor downloads.
_ADMIN_SECTION_RE = re.compile(
    r'<div class="dash-tab-content" id="tab-admin">.*?</div>\s*</div>\s*</div>',
    re.S,
)
_ADMIN_TABBTN_RE = re.compile(r'<button[^>]*id="tabBtnAdmin".*?</button>', re.S)


def _is_admin_request(request: Request) -> bool:
    """True only for a verified admin session.

    Browsers navigating to a URL send no Authorization header (the token lives
    in localStorage), so a page request cannot be authenticated this way. The
    SPA re-asks over the API once it boots. This function therefore governs
    what the SHELL contains, not whether the app works.
    """
    auth = request.headers.get("authorization") or ""
    if not auth.startswith("Bearer "):
        return False
    try:
        from routes.admin import require_admin
        require_admin(auth)
        return True
    except Exception:
        return False


def _index_html(request: Request = None) -> str:
    """index.html with every ?v= stamp rewritten to the current build."""
    raw = INDEX_FILE.read_text(encoding="utf-8")
    if request is None or not _is_admin_request(request):
        raw = _ADMIN_SECTION_RE.sub("", raw, count=1)
        raw = _ADMIN_TABBTN_RE.sub("", raw, count=1)
    return _VERSION_RE.sub(lambda m: f"{m.group(1)}?v={ASSET_VERSION}", raw)


# -------------------------------
# SPA host (landing + client-routed sections)
# -------------------------------
@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def read_index():
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="index.html not found.")
    # HTML itself must never be cached, or the browser keeps requesting the
    # old asset URLs and the new version stamp never reaches it.
    return HTMLResponse(
        _index_html(),
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


# Client-side routing: every app section has a real URL (/code, /jobs, …).
# Deep links / refreshes on these paths must serve the SPA shell — the
# frontend router reads the path and opens the right section (after auth).
#
# The API lives at ROOT (GET /profile returns JSON), so section URLs that
# collide with an API GET need content negotiation: a browser navigation
# (Accept: text/html, no Authorization header — tokens ride fetch headers,
# never visible in address-bar navigations) gets the SPA shell, while the
# SPA's own authed fetch on the same path gets the JSON data. Registered
# BEFORE the API routes on purpose, since route order decides the match.
def _spa_negotiator(fn_name: str):
    def handler(request: Request):
        accept = (request.headers.get("accept") or "").lower()
        auth_hdr = request.headers.get("authorization")
        if "text/html" in accept and not auth_hdr:
            if not INDEX_FILE.exists():
                raise HTTPException(status_code=404, detail="index.html not found.")
            return HTMLResponse(_index_html(), headers={"Cache-Control": "no-cache, must-revalidate"})
        fn = _NEGOTIATED_FNS.get(fn_name)   # resolved at request time
        if fn is None:
            raise HTTPException(status_code=404, detail="Not found.")
        return fn(authorization=auth_hdr)
    return handler


from routes.profile import get_profile as _negotiated_profile


_NEGOTIATED = {
    "profile": "get_profile",
}
_NEGOTIATED_FNS = {"get_profile": _negotiated_profile}
for _p, _fn in _NEGOTIATED.items():
    app.get("/" + _p, include_in_schema=False)(_spa_negotiator(_fn))

# Section URLs with NO API collision can serve the shell directly.
CLIENT_ONLY_PATHS = [
    "dashboard", "code", "bots", "activity", "store",
    "sign-in", "sign-up", "login", "forgot",
]
for _p in CLIENT_ONLY_PATHS:
    app.get("/" + _p, include_in_schema=False)(read_index)


# /admin is deliberately NOT in the list above. It used to serve the SPA shell
# with a plain 200 to anyone, which confirms the console exists to any stranger
# who guesses the URL. The requirement is an ordinary 404.
#
# The catch: a browser navigation carries no Authorization header (the token is
# in localStorage), so the server cannot tell an admin from anyone else at page
# load. Returning a hard 404 to everyone would lock the real admin out too.
#
# So the shell is served under a NEUTRAL path and status: the response is
# indistinguishable from /dashboard — no admin markup, no admin tab, and a 404
# status so the URL itself reveals nothing. The SPA boots, calls /profile, and
# only then decides whether the console exists for this user. Anyone without
# an admin session sees exactly what they would at any unknown URL.
@app.get("/admin", include_in_schema=False)
def read_admin(request: Request):
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="Not found.")
    return HTMLResponse(
        _index_html(request),
        status_code=200 if _is_admin_request(request) else 404,
        headers={"Cache-Control": "no-store"},
    )

# Bots is the one canonical product URL, including per-bot deep links.
@app.get("/bots/{slug}", include_in_schema=False)
def read_bot_job(slug: str):
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="index.html not found.")
    return HTMLResponse(_index_html(), headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/bots/{username}/{slug:path}", include_in_schema=False)
def read_bot_deep(username: str, slug: str):
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="index.html not found.")
    return HTMLResponse(_index_html(), headers={"Cache-Control": "no-cache, must-revalidate"})


# Old links remain safe, but immediately leave the retired RunSpace URL.
@app.get("/runspace", include_in_schema=False)
@app.get("/jobs", include_in_schema=False)
def redirect_old_bots_root():
    return RedirectResponse("/bots", status_code=308)


@app.get("/runspace/{slug}", include_in_schema=False)
def redirect_runspace_job(slug: str):
    return RedirectResponse("/bots/" + slug, status_code=308)


@app.get("/runspace/{username}/{slug:path}", include_in_schema=False)
def redirect_runspace_deep(username: str, slug: str):
    return RedirectResponse("/bots/" + username + "/" + slug, status_code=308)

# Back-compat heal: a frontend bug once produced published-page links like
# /code/s/<token> (the tab path was glued onto the origin). Redirect any
# shared copies to the real public page instead of a cold JSON 404.
@app.get("/code/s/{token}", include_in_schema=False)
def code_share_redirect(token: str):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/s/{token}", status_code=301)


@app.get("/api/public-config")
def public_config():
    """Non-secret settings the static SPA needs at runtime.

    The Telegram login widget must be told the bot's @username, which differs
    per deployment — hardcoding it in index.html left a dead "YOUR_BOT_USERNAME"
    placeholder that never rendered a button.

    Used to read TELEGRAM_BOT_USERNAME directly, a second env var that had to
    be kept in sync with the token by hand. It now asks Telegram what the
    configured BOT_TOKEN's bot is actually called — one variable to set.
    """
    from services import miniapp_auth
    return {
        "telegram_bot_username": miniapp_auth.bot_username(),
        # E-mail sign-in is shown by DEFAULT now.
        #
        # This used to default to "1", which HID the e-mail form whenever a bot
        # username was configured. The Telegram widget then became the only way
        # in — and if telegram-widget.js is slow, blocked by an extension, or
        # unreachable, the sign-in card renders nothing but the sentence
        # "One tap. No password to remember." with no button under it. A user
        # who signs out is then locked out of their own account.
        #
        # A second sign-in method costs nothing (the whole e-mail flow is
        # already implemented and tested server-side) and removes a
        # single-point-of-failure on a third-party script. Set
        # TELEGRAM_ONLY_AUTH=1 to go back to Telegram-only.
        "telegram_only": os.getenv("TELEGRAM_ONLY_AUTH", "0").strip().lower() in ("1", "true", "yes"),
    }


def _miniapp_bot_id():
    """The configured bot's public ID, or a short reason it is unusable."""
    try:
        from services import miniapp_auth
        shape = miniapp_auth.token_shape()
        if not shape.get("configured"):
            return "not configured"
        if not shape.get("looks_valid"):
            return "malformed"
        return shape.get("bot_id")
    except Exception:
        return "unknown"


# Cached so /health stays a cheap liveness probe. The answer only changes when
# the token changes, which means a restart.
_BOT_IDENTITY = {"checked": False, "value": None}


def _bot_identity():
    """Which bot this server can verify Mini App sign-ins for.

    The @username is what makes a bad_hash diagnosable: it is the single fact
    that says whether the Mini App is being opened from the right bot. It was
    previously only reachable through an admin-gated route, which needs an
    Authorization HEADER — so typing that URL into a browser returned 404 and
    the check was effectively unavailable to the person who needed it.

    A bot's id and @username are PUBLIC: anyone who can message the bot sees
    both. The token's secret half is never read here.
    """
    if _BOT_IDENTITY["checked"]:
        return _BOT_IDENTITY["value"]
    out = None
    try:
        from services import miniapp_auth
        who = miniapp_auth.whoami()
        if who.get("ok"):
            out = {"username": who.get("username"), "id": who.get("bot_id"),
                   "open": f"https://t.me/{who.get('username')}"}
        else:
            out = {"error": who.get("reason")}
    except Exception as exc:  # pragma: no cover - diagnostics must never 500
        out = {"error": "check_failed", "detail": str(exc)[:100]}
    _BOT_IDENTITY.update(checked=True, value=out)
    return out


def _token_fingerprint():
    """A comparable digest of the deployed token; never the token itself."""
    try:
        from services import miniapp_auth
        return miniapp_auth.token_fingerprint()
    except Exception:
        return {"configured": None}


def _token_live():
    """Re-test the configured token against Telegram, not the boot cache."""
    try:
        from services import miniapp_auth
        return miniapp_auth.token_live()
    except Exception:
        return {"ok": None, "reason": "unavailable"}


def _token_sources():
    """Which env var the bot token came from, and whether a second disagrees.

    A conflict here is invisible from a hosting dashboard — both variables
    look set and correct — while only one of them is in force. Reporting it
    turns "I replaced the token and nothing changed" into one glance. Only
    the public bot-id half of each token is ever shown.
    """
    try:
        from services import miniapp_auth
        return miniapp_auth.token_sources()
    except Exception:
        return {"error": "unavailable"}


def _miniapp_url():
    """Where the bot's 'Open CodeNest' button points, or why it cannot."""
    try:
        from services.pingbot import SITE_BASE
    except Exception:
        return {"ok": False, "reason": "unavailable"}
    if not SITE_BASE:
        return {"ok": False, "reason": "not_configured",
                "fix": "Set SITE_BASE_URL to this service's public https URL."}
    if not SITE_BASE.startswith("https://"):
        # Telegram refuses a web_app button on a non-https URL, so the Mini
        # App cannot open at all — it silently degrades to a browser link.
        return {"ok": False, "reason": "not_https", "url": SITE_BASE,
                "fix": "Telegram requires https:// for a Mini App button."}
    return {"ok": True, "url": f"{SITE_BASE}/bots"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "database": DIALECT,
        "runner": "embedded" if runner_client.embedded_mode() else "remote",
        "bot_secrets_encrypted": secrets_store.configured(),
        "production_isolation": "unsafe-embedded" if runner_client.embedded_mode() else "remote-runner",
        "ping_bot": "running" if bool(os.getenv("BOT_TOKEN", "").strip()
                                       or os.getenv("TELEGRAM_PING_BOT_TOKEN", "").strip()) else "not configured",
        # Which bot this server verifies Mini App sign-ins for. The bot ID half
        # of a token is PUBLIC — anyone who can message the bot can see it — so
        # this is safe, and it is the one fact needed to diagnose a bad_hash:
        # it can be compared against the bot the Mini App was actually opened
        # from. The secret half is never read.
        "telegram_bot_id": _miniapp_bot_id(),
        # Open the Mini App from THIS bot or sign-in fails with bad_hash.
        # Public information, and the one thing needed to diagnose it.
        "telegram_bot": _bot_identity(),
        # THE SAME QUESTION, ASKED FRESH. telegram_bot above is cached from a
        # single getMe at boot, so it keeps reporting the bot it saw then —
        # even if the token was replaced in the dashboard afterwards, or the
        # boot-time check never reached Telegram. That gap is how this page
        # could look completely healthy while every Mini App sign-in failed.
        # ok:true = the token is valid right now; ok:false = Telegram rejects
        # it; ok:null = Telegram unreachable, which is not a verdict.
        "telegram_token_live": _token_live(),
        # THE ONE THING THAT WAS STILL UNCHECKABLE. Diagnosis can now show
        # that the running token is not the one BotFather holds — but the
        # owner could not verify that themselves, because the secret must
        # never be printed. This is a salted-free one-way digest of the whole
        # token: run the printed command on the token BotFather shows you and
        # compare sha256_12. Equal -> the right value is deployed. Different
        # -> this process is running something else (a second variable, an
        # environment group, a stale build, a truncated paste), and revoking
        # the token again will not help.
        "telegram_token_fingerprint": _token_fingerprint(),
        # THE URL THE BOT'S BUTTON ACTUALLY OPENS. A deployment that never set
        # SITE_BASE_URL used to fall back to a hardcoded host belonging to a
        # different install, so the button opened someone else's site and
        # sign-in failed there with a bot mismatch — while every check here
        # said "ok". Reporting the resolved value makes that visible in one
        # request instead of being invisible until a user complains.
        "miniapp_url": _miniapp_url(),
        # WHICH env var is actually in force. BOT_TOKEN silently outranks
        # TELEGRAM_PING_BOT_TOKEN, so two names holding two different bots
        # looked fine from the dashboard while sign-ins were checked against
        # the one the owner thought they had replaced.
        "telegram_token_source": _token_sources(),
        "brevo_api_key_set": bool(os.getenv("BREVO_API_KEY", "").strip()),
        "sender_email_set": bool(os.getenv("SENDER_EMAIL", "").strip()),
    }


# ----------------------------
# Signup / Verify (auto-login) / Resend
# ----------------------------


@app.get("/terms", include_in_schema=False)
def terms_page():
    if not TERMS_FILE.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(TERMS_FILE)


# -------------------------------
# Domain routers
# -------------------------------
from routes.auth import router as auth_router
from routes.profile import router as profile_router
from routes.dashboard import router as dashboard_router
from routes.code_editor import router as code_editor_router
from routes.runspace import router as runspace_router
from routes.admin import router as admin_router
from routes.ping import router as ping_router
from routes.store import router as store_router
from services.term_proxy import router as term_router

for _r in (auth_router, profile_router, dashboard_router,
           code_editor_router, runspace_router, admin_router,
           ping_router, term_router, store_router):
    app.include_router(_r)


# ---- back-compat re-exports (tests + drivers import these from `app`) ----
from routes.deps import get_db_connection, hash_password, now_utc_str  # noqa: E402,F401
from services.runner_client import _job_web_fields, _runner_http  # noqa: E402,F401
