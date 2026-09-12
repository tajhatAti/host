"""
Telegram Bot - Advanced RunSpace Controller (Pure requests)
Features:
- /code <name> → create a new app (send code as text or a file next)
- /update <name> → redeploy an existing app in place (text or a file next)
- Inline buttons after deploy
- Real logs, Uptime, Download DB
"""
import io
import json
import os
import re
import threading
import time
import zipfile
import requests
from collections import defaultdict

BOT_TOKEN = (os.getenv("BOT_TOKEN", "").strip()
             or os.getenv("TELEGRAM_PING_BOT_TOKEN", "").strip())
# Every command that DOES something is gated on this: the chat must be bound
# to a CodeNest account. Before it existed, an unknown chat could deploy code
# — reproduced, a stranger's os.system('whoami') ran on the server.
from services import telegram_link  # noqa: E402
from services import bot_ops  # noqa: E402
from services import runner_client  # noqa: E402
from services import bot_analytics  # noqa: E402

import logging
logger = logging.getLogger("codenest-app")

# Hardcoded, not an env var (by request) — this Telegram account always has
# full admin rights over the bot regardless of the users.is_admin DB flag,
# so there's never a chicken-and-egg problem bootstrapping the very first
# admin. It can grant/revoke admin and zip-upload permission for anyone
# else via /admin — see cmd_admin below.
SUPER_ADMIN_TG_ID = 8768764605


def _is_admin(user, telegram_user_id=None) -> bool:
    if telegram_user_id == SUPER_ADMIN_TG_ID:
        return True
    return bool(user and user.get("is_admin"))


def _admin_menu_kb():
    return {"inline_keyboard": [
        [{"text": "📊 Overview", "callback_data": "admin:overview"},
         {"text": "👥 Users", "callback_data": "admin:users:0"}],
    ]}


def _admin_user_row_kb(target: dict):
    uid = target["id"]
    admin_lbl = "➖ Revoke admin" if target.get("is_admin") else "➕ Grant admin"
    zip_lbl = "🚫 Deny zip" if target.get("can_upload_zip") else "📦 Allow zip"
    susp_lbl = "✅ Unsuspend" if target.get("is_suspended") else "⛔ Suspend"
    rows = [
        [{"text": admin_lbl, "callback_data": f"admin:togadmin:{uid}"},
         {"text": zip_lbl, "callback_data": f"admin:togzip:{uid}"}],
        [{"text": susp_lbl, "callback_data": f"admin:togsuspend:{uid}"}],
        [{"text": "⬅️ Users", "callback_data": "admin:users:0"}],
    ]
    return {"inline_keyboard": rows}


def _admin_user_detail_text(target: dict) -> str:
    flags = []
    if target.get("is_admin"): flags.append("admin")
    if target.get("can_upload_zip"): flags.append("zip-allowed")
    if target.get("is_suspended"): flags.append("suspended")
    tag = ", ".join(flags) or "no special flags"
    tid = target.get("telegram_id") or "not linked"
    return (f"*{target.get('username') or '(no username)'}* (#{target['id']})\n"
            f"Telegram: `{tid}`\n"
            f"Flags: {tag}")


def cmd_admin(chat_id, telegram_user_id, arg):
    """/admin — inline-button panel. The hardcoded SUPER_ADMIN_TG_ID or any
    user with is_admin=1 can open it; every button re-checks admin status
    on press, since callback_data is attacker-suppliable in principle."""
    caller = telegram_link.user_for_chat(telegram_user_id)
    if not _is_admin(caller, telegram_user_id):
        _send(chat_id, "🔒 Admin only.")
        return
    _send(chat_id, "🛠 *Admin panel*", reply_markup=_admin_menu_kb())


def _admin_users_kb(page: int):
    rows = telegram_link.list_admin_overview(limit=200)
    per_page = 8
    start = page * per_page
    page_rows = rows[start:start + per_page]
    kb = []
    for r in page_rows:
        flags = []
        if r.get("is_admin"): flags.append("A")
        if r.get("can_upload_zip"): flags.append("Z")
        if r.get("is_suspended"): flags.append("S")
        label = r.get("username") or f"#{r['id']}"
        if flags:
            label += " [" + "".join(flags) + "]"
        kb.append([{"text": label, "callback_data": f"admin:user:{r['id']}"}])
    nav = []
    if start > 0:
        nav.append({"text": "◀️ Prev", "callback_data": f"admin:users:{page-1}"})
    if start + per_page < len(rows):
        nav.append({"text": "Next ▶️", "callback_data": f"admin:users:{page+1}"})
    if nav:
        kb.append(nav)
    kb.append([{"text": "⬅️ Menu", "callback_data": "admin:menu"}])
    return {"inline_keyboard": kb}


def handle_admin_callback(chat_id, telegram_user_id, action, ref):
    """Every admin: callback lands here. Re-checks admin status on every
    single press — a button label is not a permission, whoever crafted the
    tap is."""
    caller = telegram_link.user_for_chat(telegram_user_id)
    if not _is_admin(caller, telegram_user_id):
        _send(chat_id, "🔒 Admin only.")
        return

    if action == "menu":
        _send(chat_id, "🛠 *Admin panel*", reply_markup=_admin_menu_kb())
        return

    if action == "overview":
        s = telegram_link.admin_overview_stats()
        text = ("📊 *Overview*\n"
                f"Users: *{s['users']}* ({s['tg_linked']} linked to Telegram)\n"
                f"Admins: *{s['admins']}* · Zip-allowed: *{s['zip_allowed']}* · Suspended: *{s['suspended']}*\n"
                f"Jobs: *{s['jobs_total']}* total, *{s['jobs_deployed']}* deployed")
        _send(chat_id, text, reply_markup={"inline_keyboard": [[{"text": "⬅️ Menu", "callback_data": "admin:menu"}]]})
        return

    if action == "users":
        page = int(ref) if ref.isdigit() else 0
        _send(chat_id, "👥 *Users* — tap one to manage:", reply_markup=_admin_users_kb(page))
        return

    if action == "user":
        target = telegram_link.get_user_by_id(int(ref)) if ref.isdigit() else None
        if not target:
            _send(chat_id, "That user no longer exists.")
            return
        _send(chat_id, _admin_user_detail_text(target), reply_markup=_admin_user_row_kb(target))
        return

    if action in ("togadmin", "togzip", "togsuspend"):
        target = telegram_link.get_user_by_id(int(ref)) if ref.isdigit() else None
        if not target:
            _send(chat_id, "That user no longer exists.")
            return
        if action == "togadmin":
            if target.get("telegram_id") == SUPER_ADMIN_TG_ID and target.get("is_admin"):
                _send(chat_id, "Can't revoke the built-in super-admin.")
            else:
                telegram_link.set_admin(target["id"], not target.get("is_admin"))
        elif action == "togzip":
            telegram_link.set_zip_permission(target["id"], not target.get("can_upload_zip"))
        else:
            telegram_link.set_suspended(target["id"], not target.get("is_suspended"))
        target = telegram_link.get_user_by_id(target["id"])  # fresh flags
        _send(chat_id, _admin_user_detail_text(target), reply_markup=_admin_user_row_kb(target))
        return

# CODE-VIA-CHAT — READ THIS BEFORE TOUCHING /code, /update, or _pending.
#
# This used to accept a pasted snippet with no account check and deploy it
# straight to the runner, bypassing the jobs table entirely — removed after
# an unlinked chat was able to run arbitrary code on the server. /code and
# /update are back by request, rebuilt with the hole closed:
#   · Both commands are gated through _require_link() in poll_loop() below,
#     the SAME gate /restart, /stop and /delete already use. Nothing here
#     skips it.
#   · The actual create/redeploy logic lives in services/bot_ops.py
#     (create_app / update_code), which goes through the jobs table and
#     MAX_JOBS_PER_USER cap exactly like the website's editor does — see
#     that module's docstring for the full reasoning.
#   · Code arrives in the message AFTER the command, as plain text (~4096
#     char Telegram cap — fine for a quick one-line fix) or as an uploaded
#     document (up to 20MB, enough for a real app), tracked per-chat in
#     _pending{} with a 5-minute expiry so a stale "waiting for code" state
#     can never quietly capture an unrelated later message.
RUNNER_SECRET = os.getenv("RUNNER_SERVICE_SECRET", "")


def _site_base() -> str:
    """The URL the Mini App button opens — THIS deployment's own URL.

    THE HARDCODED DEFAULT WAS A TRAP, and it is the single most likely reason
    a working deployment still shows "nothing happens" on tap.

    It used to be:

        SITE_BASE = os.getenv("SITE_BASE_URL", "https://ahadorg.onrender.com")

    SITE_BASE_URL is `sync: false` in render.yaml, i.e. it is NOT set for you
    — a fresh deploy has to add it by hand. Miss that one step and the button
    is still built, still rendered, and still tappable, but it opens somebody
    else's host. What happens then depends on what lives there:

      * host gone / renamed  -> Telegram opens a webview on a dead URL and
                                closes it. Tap, flicker, nothing.
      * host alive           -> a DIFFERENT server verifies the initData with
                                a DIFFERENT bot token, so sign-in fails with
                                bad_hash and the phone shows an error naming
                                a bot the user has never heard of.

    Neither says "your SITE_BASE_URL is wrong", and the deploy is green
    throughout. Render sets RENDER_EXTERNAL_URL to the service's own public
    URL automatically, so the right default is knowable without asking: use
    it, and treat an explicit SITE_BASE_URL as an override for a custom
    domain. Falling back to a literal host that belongs to one particular
    deployment can only ever be right for that one deployment.
    """
    for name in ("SITE_BASE_URL", "PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL"):
        val = os.getenv(name, "").strip().rstrip("/")
        if val:
            return val
    return ""


SITE_BASE = _site_base()

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
TG_FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# Extension -> runtime. Matches RS_EXT_LANG in static/pro.js — RunSpace can
# only ever RUN these five languages, so anything else is rejected up front
# with a clear reason instead of failing later inside the runner.
_CODE_EXT_LANG = {
    "py": "python", "pyw": "python",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript",
    "sh": "bash", "bash": "bash",
    "rb": "ruby",
    "php": "php",
}

# chat_id -> {"mode": "create"|"update", "user_id", "ref"/"name", "expires"}
# One pending slot per chat: sending a new /code or /update just overwrites
# whatever was waiting, so there is never a stale slot fighting a fresh one.
_pending = {}
_PENDING_TTL_S = 300




def _tg(method, **params):
    """Call a Telegram Bot API method.

    POST + JSON body (not GET + query params): nested structures such as
    reply_markup's inline_keyboard cannot survive urlencoding — requests
    flattens them to "reply_markup=inline_keyboard" and the buttons vanish.
    """
    if not TG_API:
        return {}
    try:
        r = requests.post(f"{TG_API}/{method}", json=params, timeout=50)
        return r.json()
    except Exception as e:  # noqa: BLE001
        print(f"Telegram {method} failed: {e}")
        return {}


TG_MAX_UPLOAD_BYTES = 50 * 1024 * 1024   # Telegram bot upload ceiling


def _send_document(chat_id, filepath, caption=""):
    """Upload a real file to the chat (multipart, not the JSON endpoint)."""
    if not TG_API:
        return {}
    try:
        with open(filepath, "rb") as fh:
            r = requests.post(
                f"{TG_API}/sendDocument",
                data={"chat_id": chat_id, "caption": caption[:1024]},
                files={"document": (os.path.basename(filepath), fh)},
                timeout=120,
            )
        return r.json()
    except Exception as e:  # noqa: BLE001
        print("sendDocument failed:", e)
        _send(chat_id, "❌ Upload failed.")
        return {}


def _send(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        # Telegram expects reply_markup as a JSON-serialised string.
        data["reply_markup"] = json.dumps(reply_markup)
    _tg("sendMessage", **data)


# ==================== IDENTITY ====================
# An unlinked chat gets the SAME reply as an unknown command. Saying "you need
# to link first" confirms the bot is attached to something worth attacking;
# saying nothing useful costs a legitimate user one visit to /start, which
# does explain the link step — but only to a chat that asked for help, not to
# one probing for a deploy endpoint.
UNKNOWN_REPLY = "🤔 Unknown command. Send /start to see what I can do."


def _require_link(chat_id):
    """The account this chat speaks for, or None (and the chat is answered).

    Returns None for unlinked AND for suspended accounts, so a suspension
    closes the Telegram door too — otherwise suspending someone on the web
    would leave them a second way in.
    """
    user = telegram_link.user_for_chat(chat_id)
    if not user:
        _send(chat_id, UNKNOWN_REPLY)
        return None
    return user


def handle_link(chat_id, text, display_name=""):
    """/link 123456 — redeem a code issued by the website."""
    parts = (text or "").split()
    if len(parts) < 2:
        _send(chat_id,
              "🔗 *Connect your account*\n\n"
              "Open your CodeNest dashboard → Settings → *Connect Telegram* "
              "and tap the button. It brings you back here and connects you "
              "automatically — nothing to type.",
              reply_markup=_menu_buttons())
        return

    already = telegram_link.user_for_chat(chat_id)
    if already:
        _send(chat_id, f"✅ This chat is already connected to *{already['username']}*.")
        return

    # A 6-digit code is a million wide; without a per-chat cap the bot itself
    # becomes the brute-force tool.
    guard = _link_rate_ok(chat_id)
    if not guard:
        _send(chat_id, "⏳ Too many attempts. Wait a few minutes and try again.")
        return

    res = telegram_link.redeem_code(parts[1], chat_id, display_name)
    if res.get("ok"):
        # A button back, because the user arrived here FROM the dashboard and
        # the dashboard is where the connection now shows up. Telling them to
        # "go back" without a link is how a two-tap flow becomes a hunt again.
        rows = [[{"text": "📦 Open dashboard", "url": f"{SITE_BASE}/bots"}]] \
            if SITE_BASE else []
        _send(chat_id,
              f"✅ Connected to *{res['username']}*.\n\n" +
              _help_text({"username": res["username"]}).split("\n\n", 1)[1],
              reply_markup={"inline_keyboard": rows} if rows else None)
        return

    telegram_link.note_failed_attempt(parts[1])
    reason = res.get("reason")
    if reason == "chat_already_linked":
        _send(chat_id, "❌ This Telegram account is already connected to another CodeNest account.")
    elif reason == "expired":
        _send(chat_id, "⌛ That code has expired. Generate a new one on the site.")
    elif reason == "suspended":
        _send(chat_id, "❌ That account is suspended.")
    else:
        # "unknown" and "malformed" get one message on purpose: telling a
        # guesser that a code was well-formed but wrong is a hint.
        _send(chat_id, "❌ That code is not valid. Generate a fresh one on the site.")


def _cmd_arg(text):
    """Everything after the command word. "/logs my bot" -> "my bot"."""
    parts = (text or "").split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


def _tg_display(msg):
    """A human label for whoever sent this message.

    Prefers @username because that is what a person recognises; falls back to
    the first name, which Telegram always provides.
    """
    frm = (msg or {}).get("from") or {}
    uname = (frm.get("username") or "").strip()
    if uname:
        return "@" + uname
    return (frm.get("first_name") or "").strip()


# A Mini App button needs an HTTPS URL — Telegram refuses http:// and refuses
# to render the button at all, so a local dev SITE_BASE must fall back to a
# plain link rather than producing a keyboard Telegram will reject.
def _miniapp_ok() -> bool:
    return SITE_BASE.startswith("https://")


def _open_button(label="🚀 Open CodeNest"):
    """The Mini App launch button, or a plain link when that is not possible.

    `web_app` opens the existing site INSIDE Telegram, where initData signs
    the user in automatically. `url` opens a browser, where they would have to
    log in — the same destination, a worse trip, but better than no button.
    """
    if not SITE_BASE:
        return None
    if _miniapp_ok():
        return {"text": label, "web_app": {"url": f"{SITE_BASE}/bots"}}
    return {"text": label, "url": f"{SITE_BASE}/bots"}


def _open_kb(label="🚀 Open CodeNest"):
    """A keyboard holding just the launch button, or None."""
    btn = _open_button(label)
    return {"inline_keyboard": [[btn]]} if btn else None


def _menu_buttons():
    """Kept as the name older call sites use; same single button."""
    return _open_kb()


def set_menu_button():
    """Register the persistent 'Open CodeNest' button next to the input box.

    This is the always-available entry point — it does not depend on the user
    finding an old message with an inline button in it.
    """
    if not BOT_TOKEN:
        return False
    if not _miniapp_ok():
        # SAY WHY THE BUTTON IS MISSING. This returned False in silence, so a
        # deployment with no SITE_BASE_URL (or an http:// one, which Telegram
        # refuses for web_app) produced a bot with no Open button and no
        # explanation anywhere — indistinguishable from a broken Mini App.
        logger.error(
            "TELEGRAM: no 'Open CodeNest' button — the Mini App URL is %s. "
            "Telegram only accepts an https:// URL for a web_app button. Set "
            "SITE_BASE_URL to this service's public https URL and redeploy.",
            f"'{SITE_BASE}'" if SITE_BASE else "not configured (SITE_BASE_URL "
            "and RENDER_EXTERNAL_URL are both unset)")
        return False
    res = _tg("setChatMenuButton", menu_button={
        "type": "web_app",
        "text": "Open CodeNest",
        "web_app": {"url": f"{SITE_BASE}/bots"},
    })
    ok = bool((res or {}).get("ok"))
    if not ok:
        print("menu button not set:", res)
    return ok


def _help_text(user):
    """What the bot can do, including /code and /update — see the
    "CODE-VIA-CHAT" comment near the top of this file for how those two are
    kept safe (account-gated, same rails as the website's editor)."""
    return (
        f"👋 Hi *{user['username']}*!\n\n"
        "Tap *Open CodeNest* to write, edit and deploy — it opens right here "
        "in Telegram and signs you in automatically.\n\n"
        "*From chat you can also:*\n"
        "`/code <new app name>` — create an app, then send the source "
        "(text or a file)\n"
        "`/update <name>` — push new code to an existing app, then send it "
        "(auto-saves & restarts)\n"
        "`/import <github url> [name]` — clone a public repo and deploy it\n"
        "`/apps` — everything you have, with live status\n"
        "`/status [name]` — account summary, or one app in full\n"
        "`/logs <name>` — the last lines it printed\n"
        "`/restart <name>`  `/stop <name>`  `/delete <name>`\n"
        "`/rename <name> <new>`\n"
        "`/cancel` — stop a pending /code or /update\n"
        "`/ping [url]` — check a URL\n"
        "`/unlink` — disconnect this chat\n\n"
        "I message you if an app stops on its own."
    )


def handle_start(chat_id, first_name, payload=""):
    """/start, with or without a deep-link payload.

    Telegram delivers "t.me/<bot>?start=CODE" as the literal message
    "/start CODE" once the user taps START. Handling that payload is what
    turns the old nine-step flow — read a code, leave the site, find the bot,
    retype the code from memory — into two taps. The three steps a human could
    get wrong are exactly the three this removes.

    The payload is redeemed through the SAME redeem_code() the typed command
    uses. A shortcut that took a different path would be a second front door
    with its own rules to get wrong.
    """
    payload = (payload or "").strip()
    if payload:
        # Deliberately BEFORE the already-linked check: someone re-linking a
        # chat should hear that it is already connected, which handle_link
        # says, rather than have their tap silently ignored.
        handle_link(chat_id, f"/link {payload}", first_name)
        return

    user = telegram_link.user_for_chat(chat_id)
    if user:
        _send(chat_id, _help_text(user), reply_markup=_open_kb())
        return

    # UNLINKED: one button, and no instructions at all.
    #
    # There is nothing left to explain. Opening the Mini App verifies the same
    # Telegram identity and writes the same telegram_id the /link code used to
    # write — verified: user_for_chat() returns None before the first open and
    # the account straight after. So the button IS the connect step, and a
    # printed URL would only offer a worse route to the same place (a browser,
    # where the user would have to log in by hand).
    kb = _open_kb()
    if not kb:
        # A MESSAGE THAT SAYS "TAP BELOW" WITH NOTHING BELOW IT IS THE BUG,
        # NOT A COSMETIC ISSUE. _open_kb() returns None whenever the Mini App
        # URL is unusable, and the old code sent the invitation anyway — so
        # the very first thing a new user saw was an instruction pointing at
        # a button that was not there. Reproduced with SITE_BASE_URL unset.
        _send(chat_id,
              f"👋 Hi {first_name}!\n\n"
              "⚠️ CodeNest is not finished setting up: the owner still has to "
              "set `SITE_BASE_URL` to this site's public https address. "
              "Until then I cannot open the app for you.")
        return
    _send(chat_id,
          f"👋 Hi {first_name}!\n\n"
          "Tap below to open CodeNest — writing, editing and deploying all "
          "happen there, and you are signed in automatically.",
          reply_markup=kb)


def handle_unlink(chat_id):
    user = telegram_link.user_for_chat(chat_id)
    if not user:
        _send(chat_id, UNKNOWN_REPLY)
        return
    telegram_link.unlink(user["id"])
    _send(chat_id,
          "🔌 Disconnected. This chat can no longer deploy or see your apps.\n\n"
          "Your apps keep running — nothing was stopped.",
          reply_markup=_menu_buttons())


_link_attempts = defaultdict(list)
LINK_TRIES_PER_HOUR = int(os.getenv("TELEGRAM_LINK_TRIES_PER_HOUR", "8"))


def _link_rate_ok(chat_id):
    now = time.time()
    _link_attempts[chat_id] = [t for t in _link_attempts[chat_id] if now - t < 3600]
    if len(_link_attempts[chat_id]) >= LINK_TRIES_PER_HOUR:
        return False
    _link_attempts[chat_id].append(now)
    return True


# ==================== /ping ====================
def handle_ping(chat_id, text):
    target = text.split()[1] if len(text.split()) > 1 else "https://ahadorg.onrender.com"
    try:
        t0 = time.time()
        r = requests.head(target, timeout=8, allow_redirects=True)
        ms = round((time.time() - t0) * 1000, 1)
        _send(chat_id, f"🟢 {ms}ms | HTTP {r.status_code}")
    except Exception as e:
        _send(chat_id, f"❌ {str(e)}")


# ==================== APP BUTTONS ====================
def _app_buttons(job_id, url="", bot_username=""):
    """Buttons keyed on the SITE job id, not the runner id.

    The runner id changes when a job is recreated, so buttons attached to an
    old message silently stopped working. The site id is stable for the life
    of the app, and it is also what scopes every action to its owner.
    """
    rows = [
        [{"text": "📜 Logs", "callback_data": f"logs:{job_id}"},
         {"text": "📊 Status", "callback_data": f"stat:{job_id}"}],
        [{"text": "🔄 Restart", "callback_data": f"restart:{job_id}"},
         {"text": "⏹ Stop", "callback_data": f"stop:{job_id}"}],
        [{"text": "📥 Download data", "callback_data": f"db:{job_id}"}],
    ]
    # The whole point of this platform is deploying a Telegram bot — so the
    # single most relevant thing to do right after a deploy is open THAT
    # bot and talk to it. This button was missing entirely; every other
    # action here manages the deployment, none of them let you use it.
    if bot_username:
        rows.append([{"text": "🤖 Open your bot", "url": f"https://t.me/{bot_username.lstrip('@')}"}])
    if url:
        rows.append([{"text": "🌐 Open live URL", "url": url}])
    btn = _open_button("🚀 Open in CodeNest")
    if btn:
        rows.append([btn])
    return {"inline_keyboard": rows}


# Kept under its old name: the reply_markup regression test drives it, and
# that regression (a nested dict urlencoded into "reply_markup=inline_keyboard"
# so every button vanished) is still worth guarding.
def get_job_buttons(runner_id, url):
    return _app_buttons(runner_id, url)


# ==================== APP COMMANDS ====================
def _fmt_uptime(sec):
    sec = int(sec or 0)
    if sec <= 0:
        return "—"
    d, h, m = sec // 86400, (sec % 86400) // 3600, (sec % 3600) // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m {sec % 60}s"


_ICON = {"running": "🟢", "crashed": "🔴", "installing": "🟡",
         "starting": "🟡", "restarting": "🟡", "recovering": "🟡", "stopped": "⚪", "offline": "⚪"}


def cmd_apps(chat_id, user):
    apps = bot_ops.list_apps(user["id"])
    if not apps:
        _send(chat_id, "You have no apps yet. `/code <name>` to create one.")
        return
    lines = [f"*Your apps* ({len(apps)}/{bot_ops.MAX_JOBS_PER_USER} running slots)\n"]
    for a in apps:
        icon = _ICON.get(a["status"], "⚪")
        bits = [f"{icon} *{a['name']}* — {a['status']}"]
        if a.get("mem_mb"):
            bits.append(f"{round(a['mem_mb'])}MB")
        if a.get("uptime_s"):
            bits.append(_fmt_uptime(a["uptime_s"]))
        if a.get("restarts"):
            bits.append(f"{a['restarts']}× restarted")
        lines.append(" · ".join(bits))
    lines.append("\n`/logs <name>` `/restart <name>` `/stop <name>`")
    lines.append("`/update <name>` `/rename <name> <new>` `/delete <name>`")
    _send(chat_id, "\n".join(lines))


def cmd_status(chat_id, user, ref=""):
    """Whole-account summary, or one app in full."""
    if ref:
        res = bot_ops.logs(user["id"], ref, lines=0)
        if not res.get("ok"):
            _send(chat_id, f"❌ {res['error']}")
            return
        job, info = res["job"], res["info"]
        icon = _ICON.get(info.get("status"), "⚪")
        txt = [f"{icon} *{job['name']}*",
               f"Status: `{info.get('status', 'unknown')}`",
               f"Language: `{job.get('language') or '—'}`",
               f"Memory: {round(info.get('mem_mb') or 0)}MB now · "
               f"{round(info.get('peak_mem_mb') or 0)}MB peak",
               f"Uptime: {_fmt_uptime(info.get('uptime_s'))}",
               f"Restarts: {info.get('restarts', 0)}"]
        if info.get("last_exit_reason"):
            txt.append(f"Last exit: `{info['last_exit_reason']}`")
        if info.get("libs"):
            txt.append(f"Packages: `{', '.join(info['libs'])}`")
        if info.get("env_keys"):
            # KEY NAMES ONLY — the values are bot tokens.
            txt.append(f"Env keys: `{', '.join(info['env_keys'])}`")
        _send(chat_id, "\n".join(txt),
              reply_markup=_app_buttons(job["id"], bot_username=job.get("telegram_bot_username") or ""))
        return

    apps = bot_ops.list_apps(user["id"])
    running = [a for a in apps if a["status"] == "running"]
    mem = sum(a.get("mem_mb") or 0 for a in apps)
    _send(chat_id,
          f"*{user['username']}*\n\n"
          f"Apps: {len(apps)} · running {len(running)}/{bot_ops.MAX_JOBS_PER_USER}\n"
          f"Memory in use: {round(mem)}MB\n\n"
          "`/apps` for the list · `/status <name>` for one app")


def cmd_logs(chat_id, user, ref):
    if not ref:
        _send(chat_id, "Which app? `/logs <name>` — /apps lists them.")
        return
    res = bot_ops.logs(user["id"], ref)
    if not res.get("ok"):
        _send(chat_id, f"❌ {res['error']}")
        return
    body = res["logs"] or "(no output yet)"
    # Telegram rejects a message over ~4096 chars; trim from the FRONT so the
    # most recent lines — the ones that explain a crash — always survive.
    if len(body) > 3500:
        body = "…\n" + body[-3500:]
    head = "📜 last lines" + (" (trimmed)" if res.get("truncated") else "")
    _send(chat_id, f"*{res['job']['name']}* — {head}\n```\n{body}\n```",
          reply_markup=_app_buttons(res["job"]["id"], bot_username=res["job"].get("telegram_bot_username") or ""))


def cmd_restart(chat_id, user, ref):
    if not ref:
        _send(chat_id, "Which app? `/restart <name>`")
        return
    res = bot_ops.restart(user["id"], ref)
    _send(chat_id, f"🔄 Restarting *{res['job']['name']}*…" if res.get("ok")
          else f"❌ {res['error']}")


def cmd_stop(chat_id, user, ref):
    if not ref:
        _send(chat_id, "Which app? `/stop <name>`")
        return
    res = bot_ops.stop(user["id"], ref)
    _send(chat_id, f"⏹ Stopped *{res['job']['name']}*." if res.get("ok")
          else f"❌ {res['error']}")


def cmd_delete(chat_id, user, ref):
    if not ref:
        _send(chat_id, "Which app? `/delete <name>` — this cannot be undone.")
        return
    app = bot_ops.find_app(user["id"], ref)
    if not app:
        _send(chat_id, f"❌ No app called “{ref}”.")
        return
    _send(chat_id, f"Delete *{app['name']}*? This cannot be undone.",
          {"inline_keyboard": [
              [{"text": "🗑 Yes, delete", "callback_data": f"delconfirm:{app['id']}"},
               {"text": "✖️ Cancel", "callback_data": f"delcancel:{app['id']}"}],
          ]})


def _cmd_delete_confirmed(chat_id, user, ref):
    res = bot_ops.delete(user["id"], ref)
    _send(chat_id, f"🗑 Deleted *{res['job']['name']}*." if res.get("ok")
          else f"❌ {res['error']}")


def cmd_rename(chat_id, user, args):
    parts = (args or "").split()
    if len(parts) < 2:
        _send(chat_id, "Usage: `/rename <current name> <new name>`")
        return
    res = bot_ops.rename(user["id"], parts[0], " ".join(parts[1:]))
    _send(chat_id, f"✏️ *{res['old']}* is now *{res['name']}*." if res.get("ok")
          else f"❌ {res['error']}")


# ==================== /code AND /update — see the module comment above ====

def cmd_import(chat_id, user, arg):
    """/import <github url> [name] — clone a public GitHub repo and deploy it.
    The runner auto-detects which file to run (main.py/bot.py/app.py first,
    then a manifest-aware fallback — see runner/app.py:_detect_entry). A
    static site (index.html, no requirements.txt/package.json) is served
    as-is."""
    if not arg:
        _send(chat_id, "Usage: `/import <github.com/user/repo>`\n"
                       "Optionally name it yourself: `/import <url> myapp`\n"
                       "Only public repos are supported right now.")
        return
    parts = arg.split(None, 1)
    url = parts[0]
    name = parts[1].strip() if len(parts) > 1 else ""
    m = re.search(r"github\.com/([^/\s]+)/([^/\s]+)", url)
    if not m:
        _send(chat_id, "That doesn't look like a github.com repo URL — "
                       "expected something like `github.com/user/repo`.")
        return
    if not name:
        name = m.group(2).replace(".git", "")
    clean = bot_ops.slugify_name(name)
    if not clean:
        _send(chat_id, "That name has no usable characters — letters, numbers, "
                       "spaces, `-` and `_` only.")
        return
    if bot_ops.find_app(user["id"], clean):
        _send(chat_id, f"You already have an app called “{clean}”. Pick a "
                       f"different name: `/import {url} <name>`.")
        return
    _send(chat_id, f"📥 Cloning and deploying *{clean}*… this can take a "
                   f"little longer than /code, since the repo has to be "
                   f"fetched first.")
    res = bot_ops.create_app_from_repo(user["id"], clean, url)
    if not res.get("ok"):
        _send(chat_id, f"❌ {res['error']}")
        return
    url_web = res.get("web") or ""
    _send(chat_id, f"✅ *{res['name']}* imported and running.\n"
                   + (url_web + "\n" if url_web else "")
                   + "⚠️ No Telegram bot token check on import yet — if this "
                     f"is meant to be a Telegram bot, run `/status {res['name']}` "
                     f"to confirm it's actually polling.\n"
                   + f"`/logs {res['name']}` if anything looks wrong.",
          reply_markup=_app_buttons(res["job_db_id"], url=url_web))


def cmd_code_start(chat_id, user, name):
    """/code <new app name> — the NEXT message from this chat becomes the
    app's source (text or a file)."""
    if not name:
        _send(chat_id, "Usage: `/code <new app name>`, then send the source "
                       "as a message or upload a file.")
        return
    clean = bot_ops.slugify_name(name)
    if not clean:
        _send(chat_id, "That name has no usable characters — letters, numbers, "
                       "spaces, `-` and `_` only.")
        return
    if bot_ops.find_app(user["id"], clean):
        _send(chat_id, f"You already have an app called “{clean}”. "
                       f"Use `/update {clean}` to change its code instead.")
        return
    _pending[chat_id] = {
        "mode": "create", "user_id": user["id"], "name": clean,
        "step": "requirements",
        "expires": time.time() + _PENDING_TTL_S,
    }
    _send(chat_id, f"📦 Creating *{clean}*. Any pip packages it needs? "
                   f"Reply with names (e.g. `python-telegram-bot==21.4, requests`), "
                   f"or `/skip` if none. `/cancel` to stop.")


def cmd_update_start(chat_id, user, ref):
    """/update <existing app name> — the NEXT message becomes its new code,
    redeployed in place (workspace data preserved)."""
    if not ref:
        _send(chat_id, "Usage: `/update <app name>`, then send the new "
                       "source as a message or upload a file.")
        return
    row = bot_ops.find_app(user["id"], ref)
    if not row:
        _send(chat_id, f"No app called “{ref}”. `/apps` lists yours.")
        return
    _pending[chat_id] = {
        "mode": "update", "user_id": user["id"], "ref": row["name"],
        "step": "requirements",
        "expires": time.time() + _PENDING_TTL_S,
    }
    _send(chat_id, f"📦 Updating *{row['name']}*. Any pip packages the new "
                   f"code needs? Reply with names, or `/skip` to leave "
                   f"requirements as they are. `/cancel` to stop.")


def cmd_cancel_pending(chat_id):
    had = _pending.pop(chat_id, None)
    _send(chat_id, "❎ Cancelled." if had else "Nothing pending.")


def _get_pending(chat_id):
    """The chat's pending /code or /update slot, or None if there isn't one
    or it has expired (and is cleaned up on the way out either way)."""
    p = _pending.get(chat_id)
    if not p:
        return None
    if time.time() > p["expires"]:
        _pending.pop(chat_id, None)
        return None
    return p


TG_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024   # Telegram bot API download ceiling

# .zip bundles: RunSpace only ever runs ONE source file (see _CODE_EXT_LANG —
# the runner has no multi-file support), so a zip is just a convenience for
# "my code plus a requirements.txt in one upload", not a real multi-file app.
# Extraction reads member bytes straight out of the ZipFile object in memory
# — nothing is ever written to disk — so there's no zip-slip path-traversal
# surface here at all.
ZIP_MAX_UNCOMPRESSED_BYTES = 5 * 1024 * 1024   # 5MB unzipped, plenty for source
ZIP_MAX_ENTRIES = 500
_ZIP_ENTRY_PREFERENCE = ("main", "bot", "app", "index", "run")


def _pick_zip_entry(code_names: list) -> str:
    """Choose which code file in the zip to deploy, preferring conventional
    entry-point names and shallower paths."""
    def sort_key(name):
        base = name.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0].lower()
        depth = name.count("/")
        pref_rank = (_ZIP_ENTRY_PREFERENCE.index(stem)
                     if stem in _ZIP_ENTRY_PREFERENCE else len(_ZIP_ENTRY_PREFERENCE))
        return (depth, pref_rank, name)
    return sorted(code_names, key=sort_key)[0]


def _extract_zip_document(raw: bytes) -> tuple:
    """Pull one runnable source file (+ optional requirements.txt) out of an
    uploaded .zip. Returns (code, lang, requirements, note, error) — same
    error-tuple convention as _download_document, just two extra slots for
    the requirements text pulled from the zip and a heads-up note to show
    the user (e.g. "other files were ignored")."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return None, None, None, None, "That .zip file looks corrupted — try re-exporting it."

    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > ZIP_MAX_ENTRIES:
        return None, None, None, None, f"That zip has {len(infos)} files — over the {ZIP_MAX_ENTRIES} limit."
    total = sum(i.file_size for i in infos)
    if total > ZIP_MAX_UNCOMPRESSED_BYTES:
        mb = ZIP_MAX_UNCOMPRESSED_BYTES // (1024 * 1024)
        return None, None, None, None, f"Unzipped that's over {mb}MB — too big for a RunSpace bundle."

    names = [
        i.filename for i in infos
        if not i.filename.startswith("__MACOSX/")
        and not i.filename.rsplit("/", 1)[-1].startswith(".")
    ]
    code_names = [
        n for n in names
        if "." in n.rsplit("/", 1)[-1]
        and n.rsplit(".", 1)[-1].lower() in _CODE_EXT_LANG
    ]
    if not code_names:
        return None, None, None, None, ("No runnable file found inside — need one of "
                                         ".py/.js/.sh/.rb/.php (e.g. `main.py`).")

    entry = _pick_zip_entry(code_names)
    lang = _CODE_EXT_LANG[entry.rsplit(".", 1)[-1].lower()]
    try:
        code = zf.read(entry).decode("utf-8")
    except UnicodeDecodeError:
        return None, None, None, None, f"`{entry}` isn't plain text — can't deploy a binary as source code."

    req_name = next((n for n in names if n.rsplit("/", 1)[-1].lower() == "requirements.txt"), None)
    reqs = None
    if req_name:
        try:
            reqs = zf.read(req_name).decode("utf-8").strip() or None
        except UnicodeDecodeError:
            reqs = None

    ignored = len(code_names) - 1
    note = None
    if ignored > 0:
        note = (f"📦 Using `{entry}` as the entry point ({ignored} other code "
                f"file(s) in the zip were ignored — RunSpace apps run a single file).")

    return code, lang, reqs, note, None


def _download_document(doc) -> tuple:
    """Fetch an uploaded document and resolve it to deployable source.

    Returns (code, lang, requirements, note, error):
      - error is a user-facing string, or None on success.
      - lang/requirements/note are None for a plain source file; a .zip can
        populate lang (from whichever entry file it picked) and requirements
        (from a requirements.txt inside it) and note (a heads-up about
        files that were ignored).
    Binary files (images, compiled anything) are rejected — RunSpace runs
    source text, nothing else. .zip is the one archive format supported,
    handled by _extract_zip_document.
    """
    size = doc.get("file_size") or 0
    if size > TG_MAX_DOWNLOAD_BYTES:
        return None, None, None, None, f"That file is {size // (1024*1024)}MB — Telegram bots can only download up to 20MB."
    try:
        meta = _tg("getFile", file_id=doc["file_id"])
        file_path = (meta.get("result") or {}).get("file_path")
        if not file_path:
            return None, None, None, None, "Telegram didn't return that file. Try sending it again."
        r = requests.get(f"{TG_FILE_API}/{file_path}", timeout=60)
        r.raise_for_status()
        raw = r.content
    except Exception as exc:  # noqa: BLE001
        logger.warning("bot document download failed: %s", exc)
        return None, None, None, None, "Couldn't download that file from Telegram. Try again."

    filename = doc.get("file_name") or ""
    if filename.lower().endswith(".zip"):
        return _extract_zip_document(raw)

    try:
        code = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, None, None, None, "That file isn't plain text (looks binary) — RunSpace runs source code, not compiled files or archives."
    return code, _lang_for_document(filename), None, None, None


def _lang_for_document(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return _CODE_EXT_LANG.get(ext)


def handle_pending_code(chat_id, msg, pending):
    """A text or document message arrived while /code or /update was
    waiting on this chat. Resolve it to source + language and deploy."""
    # Requirements are asked as their OWN step, before code — pasting code
    # that must also correctly contain a hand-typed "# requirements: ..."
    # comment is exactly what caused trouble: easy to forget, easy to
    # place wrong, easy to mistype. This way the runner still only ever
    # reads that same comment line (nothing changes downstream) — it's
    # just the bot's job to write it correctly, not the user's.
    if pending.get("step") == "requirements":
        text = (msg.get("text") or "").strip()
        if text and text.lower() != "/skip":
            pending["requirements"] = text
        pending["step"] = "code"
        pending["expires"] = time.time() + _PENDING_TTL_S
        _send(chat_id, "Now send the source — paste it as a message, or "
                       "upload a file (.py/.js/.sh/.rb/.php) or a .zip bundle. `/cancel` to stop.")
        return

    doc = msg.get("document")
    zip_raw = None
    if doc and (doc.get("file_name") or "").lower().endswith(".zip"):
        tg_uid = (msg.get("from") or {}).get("id")
        linked_user = telegram_link.user_for_chat(tg_uid)
        if not (_is_admin(linked_user, tg_uid) or (linked_user or {}).get("can_upload_zip")):
            _send(chat_id, "🔒 .zip uploads need admin approval on this account. "
                           "Ask an admin to run `/admin allowzip` for you, or send a "
                           "single source file instead.")
            return
        # Multi-file path for BOTH create and update: hand the WHOLE zip to
        # the runner, which extracts it for real (see
        # runner/app.py:_extract_zip_bundle / the PATCH re-extraction added
        # alongside it) instead of the old behaviour of reading one file out
        # of the zip and dropping every other file in it — which is exactly
        # what broke any app whose entry file imported a sibling module.
        size = doc.get("file_size") or 0
        if size > TG_MAX_DOWNLOAD_BYTES:
            _send(chat_id, f"❌ That file is {size // (1024*1024)}MB — "
                           f"Telegram bots can only download up to 20MB.\nSend it again, or `/cancel`.")
            return
        try:
            meta = _tg("getFile", file_id=doc["file_id"])
            file_path = (meta.get("result") or {}).get("file_path")
            r = requests.get(f"{TG_FILE_API}/{file_path}", timeout=60)
            r.raise_for_status()
            zip_raw = r.content
        except Exception as exc:  # noqa: BLE001
            logger.warning("bot zip download failed: %s", exc)
            _send(chat_id, "❌ Couldn't download that zip from Telegram. Try again, or `/cancel`.")
            return

    if zip_raw is not None:
        _pending.pop(chat_id, None)
        if pending["mode"] == "create":
            _send(chat_id, f"📦 Extracting *{pending['name']}*…")
            res = bot_ops.create_app_from_zip(pending["user_id"], pending["name"], zip_raw)
            if not res.get("ok"):
                _send(chat_id, f"❌ {res['error']}")
                return
            url = res.get("web") or ""
            _send(chat_id, f"✅ *{res['name']}* created and running.\n"
                           + (url + "\n" if url else "")
                           + "⚠️ No Telegram bot token check on a zip import yet — if this is a "
                             f"bot, `/update {res['name']}` once (with the same entry file's code) "
                             f"to verify it.\n`/status {res['name']}` for details.",
                  reply_markup=_app_buttons(res["job_db_id"], url=url))
        else:
            _send(chat_id, f"📦 Extracting into *{pending['ref']}*…")
            res = bot_ops.update_from_zip(pending["user_id"], pending["ref"], zip_raw)
            if not res.get("ok"):
                _send(chat_id, f"❌ {res['error']}")
                return
            _send(chat_id, f"✅ *{res['job']['name']}* updated from zip and restarted.\n"
                           f"Existing data files (databases, sessions) were left alone — "
                           f"only what's in the zip was written.",
                  reply_markup=_app_buttons(res["job"]["id"],
                                             bot_username=res["job"].get("telegram_bot_username") or ""))
        return

    if doc:
        code, doc_lang, zip_reqs, note, err = _download_document(doc)
        if err:
            _send(chat_id, f"❌ {err}\nSend the file again, or `/cancel`.")
            return  # slot stays open — let them retry without re-typing the command
        if note:
            _send(chat_id, note)
        if zip_reqs and not (pending.get("requirements") or "").strip():
            pending["requirements"] = zip_reqs
    else:
        code = (msg.get("text") or "").strip()
        doc_lang = None
        if not code:
            _send(chat_id, "Send the source as text or a file, or `/cancel`.")
            return

    reqs = (pending.get("requirements") or "").strip()
    if reqs and not re.search(r"^#\s*requirements:", code, re.I | re.M):
        code = f"# requirements: {reqs}\n{code}"

    _pending.pop(chat_id, None)  # slot consumed either way from here on

    if pending["mode"] == "create":
        lang = doc_lang or "python"
        res = bot_ops.create_app(pending["user_id"], pending["name"], lang, code)
        if not res.get("ok"):
            _send(chat_id, f"❌ {res['error']}")
            return
        url = res.get("web") or ""
        note = ""
        if not res.get("telegram_bot_username"):
            note = "\n⚠️ Couldn't verify a Telegram bot token in this code — no “Open your bot” button yet."
        _send(chat_id, f"✅ *{res['name']}* created and running ({lang}).\n"
                       + (url + "\n" if url else "") + note
                       + f"\n`/status {res['name']}` for details.",
              reply_markup=_app_buttons(res["job_db_id"], url=url,
                                         bot_username=res.get("telegram_bot_username") or ""))
    else:
        # /update never changes the runtime on its own — a .js file dropped
        # onto a python app would silently swap what it runs. Only apply the
        # inferred language if it MATCHES what's already there; otherwise
        # keep the app's existing language and let the code speak for itself.
        row = bot_ops.find_app(pending["user_id"], pending["ref"])
        lang = doc_lang if (doc_lang and row and doc_lang == row.get("language")) else None
        res = bot_ops.update_code(pending["user_id"], pending["ref"], code, lang)
        if not res.get("ok"):
            _send(chat_id, f"❌ {res['error']}")
            return
        _send(chat_id, f"✅ *{res['job']['name']}* updated, saved and restarted.",
              reply_markup=_app_buttons(res["job"]["id"],
                                         bot_username=res["job"].get("telegram_bot_username") or ""))


# ==================== CALLBACK HANDLER ====================
def handle_callback(chat_id, data):
    """Inline buttons. Every action re-resolves the app FOR THIS USER.

    callback_data is attacker-supplied — anyone can craft a button press with
    someone else's job id — so the id is looked up scoped to the pressing
    chat's account, never trusted on its own.
    """
    try:
        action, ref = data.split(":", 1)
    except Exception:
        return

    if action == "admin":
        try:
            sub_action, sub_ref = ref.split(":", 1)
        except ValueError:
            sub_action, sub_ref = ref, ""
        # Private chat: chat_id IS the Telegram user id of whoever pressed
        # the button — same identity handle_admin_callback re-checks itself.
        handle_admin_callback(chat_id, chat_id, sub_action, sub_ref)
        return

    user = telegram_link.user_for_chat(chat_id)
    if not user:
        return

    if action == "logs":
        cmd_logs(chat_id, user, ref)
    elif action == "stat":
        cmd_status(chat_id, user, ref)
    elif action == "restart":
        cmd_restart(chat_id, user, ref)
    elif action == "stop":
        cmd_stop(chat_id, user, ref)
    elif action == "db":
        _send_job_data(chat_id, user, ref)
    elif action == "delconfirm":
        _cmd_delete_confirmed(chat_id, user, ref)
    elif action == "delcancel":
        _send(chat_id, "Cancelled — nothing was deleted.")


def _send_job_data(chat_id, user, ref):
    """Upload the app's data file (SQLite/JSON) to the chat."""
    app = bot_ops.find_app(user["id"], ref)
    if not app:
        _send(chat_id, "❌ That app is not yours or no longer exists.")
        return
    rid = app.get("runner_job_id")
    if not rid:
        _send(chat_id, "❌ That app was never deployed.")
        return
    try:
        r = runner_client._runner_http("GET", f"/internal/jobs/{rid}",
                                       worker=bot_ops._worker_of(app))
        jdir = (r.json() or {}).get("dir") or ""
    except Exception:
        _send(chat_id, "❌ The worker did not answer.")
        return
    if not jdir or not os.path.isdir(jdir):
        # Remote workers do not share a filesystem with this process, so the
        # path is only readable in the embedded/single-service layout. Say so
        # instead of reporting "no database".
        _send(chat_id, "📭 Data files are not reachable from here — "
                       "download them from the dashboard.")
        return
    best, best_size = None, -1
    for root, dirs, files in os.walk(jdir):
        dirs[:] = [d for d in dirs if d not in
                   ("__pycache__", ".git", "node_modules", "pylibs", ".cache")]
        for fn in files:
            if not fn.lower().endswith((".db", ".sqlite", ".sqlite3", ".json")):
                continue
            fp = os.path.join(root, fn)
            try:
                sz = os.path.getsize(fp)
            except OSError:
                continue
            if sz > best_size:
                best, best_size = fp, sz
    if not best:
        _send(chat_id, "📭 No data file yet — the app has not created one.")
        return
    if best_size > TG_MAX_UPLOAD_BYTES:
        _send(chat_id, f"❌ `{os.path.basename(best)}` is "
                       f"{best_size // (1024 * 1024)}MB — over Telegram's 50MB "
                       f"limit. Download it from the dashboard.")
        return
    _send_document(chat_id, best,
                   caption=f"📥 {os.path.basename(best)} ({best_size} bytes)")


# ==================== UPDATE DISPATCH ====================
def _command_parts(text):
    """Return Telegram command + argument; accept /cmd@BotName in groups."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return "", ""
    head, _, arg = text.partition(" ")
    command = head.split("@", 1)[0].lower()
    return command, arg.strip()


def _row_id(row):
    try:
        return row["id"] if row else None
    except (KeyError, TypeError):
        return None


def handle_update(upd):
    """Dispatch one Telegram update and always leave an analytics record."""
    event = {"chat_id": "", "event_type": "unknown", "command": "",
             "payload": "", "outcome": "ok", "error": "",
             "display_name": "", "telegram_user_id": None, "user_id": None}
    try:
        if "message" in upd:
            msg = upd["message"]
            chat_id = msg["chat"]["id"]
            text = msg.get("text", "") or ""
            command, arg = _command_parts(text)
            event.update(chat_id=chat_id,
                         event_type="command" if command else
                                    ("document" if "document" in msg else "message"),
                         command=command, payload=arg if command else "",
                         display_name=_tg_display(msg),
                         telegram_user_id=msg.get("from", {}).get("id"))
            linked = telegram_link.user_for_chat(chat_id)
            event["user_id"] = _row_id(linked)

            # A pending upload/text is claimed before normal non-command input.
            # "/skip" is the one command-shaped exception: it's only ever
            # meaningful as the answer to the requirements step below, so it
            # must reach handle_pending_code instead of falling through to
            # "unknown command" like every other slash-word would.
            pending_now = _get_pending(chat_id)
            skipping = command == "/skip" and pending_now and pending_now.get("step") == "requirements"
            if not command or skipping:
                pending = pending_now
                if pending:
                    event["event_type"] = "code_upload"
                    event["payload"] = str(pending.get("name") or pending.get("ref") or "")
                    handle_pending_code(chat_id, msg, pending)
                    return
                if "document" in msg:
                    _send(chat_id, "I wasn't expecting a file — send "
                                   "`/code <new app name>` or `/update <app name>` first, "
                                   "then the file.")
                else:
                    _send(chat_id, UNKNOWN_REPLY, reply_markup=_open_kb())
                return

            def gated(fn):
                user = _require_link(chat_id)
                if user:
                    event["user_id"] = _row_id(user)
                    fn(user)
                else:
                    event["outcome"] = "refused"

            handlers = {
                "/start": lambda: handle_start(chat_id, _tg_display(msg) or
                                                 msg.get("from", {}).get("first_name", "user"), arg),
                "/link": lambda: handle_link(chat_id, text, _tg_display(msg)),
                "/unlink": lambda: handle_unlink(chat_id),
                "/ping": lambda: gated(lambda _u: handle_ping(chat_id, text)),
                "/cancel": lambda: cmd_cancel_pending(chat_id),
                "/apps": lambda: gated(lambda u: cmd_apps(chat_id, u)),
                "/jobs": lambda: gated(lambda u: cmd_apps(chat_id, u)),
                "/status": lambda: gated(lambda u: cmd_status(chat_id, u, arg)),
                "/logs": lambda: gated(lambda u: cmd_logs(chat_id, u, arg)),
                "/restart": lambda: gated(lambda u: cmd_restart(chat_id, u, arg)),
                "/stop": lambda: gated(lambda u: cmd_stop(chat_id, u, arg)),
                "/delete": lambda: gated(lambda u: cmd_delete(chat_id, u, arg)),
                "/rename": lambda: gated(lambda u: cmd_rename(chat_id, u, arg)),
                "/code": lambda: gated(lambda u: cmd_code_start(chat_id, u, arg)),
                "/update": lambda: gated(lambda u: cmd_update_start(chat_id, u, arg)),
                "/import": lambda: gated(lambda u: cmd_import(chat_id, u, arg)),
                "/admin": lambda: cmd_admin(chat_id, msg.get("from", {}).get("id"), arg),
                "/help": lambda: handle_start(chat_id, _tg_display(msg) or
                                                msg.get("from", {}).get("first_name", "user")),
            }
            handler = handlers.get(command)
            if handler:
                handler()
            else:
                event["outcome"] = "unknown"
                _send(chat_id, UNKNOWN_REPLY, reply_markup=_open_kb())

        elif "callback_query" in upd:
            cb = upd["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            data = str(cb.get("data") or "")
            linked = telegram_link.user_for_chat(chat_id)
            event.update(chat_id=chat_id, event_type="callback",
                         command=data.partition(":")[0], payload=data.partition(":")[2],
                         display_name=_tg_display(cb.get("message", {})),
                         telegram_user_id=cb.get("from", {}).get("id"),
                         user_id=_row_id(linked))
            # Telegram requires answerCallbackQuery within ~30s or the
            # button sits in a spinner / looks unresponsive on the user's
            # phone. This used to run AFTER handle_callback with no
            # try/finally, so any exception in handle_callback (a runner
            # timeout, a job already deleted, a network hiccup) skipped
            # the answer entirely — "the button sometimes doesn't work",
            # intermittent because it only happened when the action
            # itself failed. Now it's answered no matter what.
            try:
                if linked:
                    handle_callback(chat_id, data)
                else:
                    event["outcome"] = "refused"
                _tg("answerCallbackQuery", callback_query_id=cb["id"])
            except Exception as cb_exc:
                event["outcome"] = "error"
                event["error"] = f"{type(cb_exc).__name__}: {cb_exc}"
                try:
                    _tg("answerCallbackQuery", callback_query_id=cb["id"],
                        text="Something went wrong — try again.", show_alert=False)
                except Exception:
                    logger.exception("Could not even answer the callback query")
                raise
    except Exception as exc:
        event["outcome"] = "error"
        event["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            if event["chat_id"] != "":
                bot_analytics.record(**event)
        except Exception:
            # A monkeypatched/broken recorder still cannot replace the command result.
            logger.exception("Bot analytics recorder failed")


# ==================== MAIN LOOP ====================
def poll_loop():
    if not BOT_TOKEN:
        return
    print("🤖 Advanced Bot starting...")
    offset = 0

    _fail_streak = 0
    _webhook_cleared = False

    while True:
        try:
            updates = _tg("getUpdates", offset=offset, timeout=40)

            # A REJECTED getUpdates USED TO BE INVISIBLE.
            #
            # This branch was `time.sleep(1); continue` with no logging at
            # all, and it is the branch Telegram takes for the two failures
            # that actually stop a bot dead:
            #
            #   409 "can't use getUpdates method while webhook is active"
            #       — someone (often a hosting UI or an old deploy) left a
            #         webhook registered on this token. Polling can NEVER
            #         work until it is deleted.
            #   409 "terminated by other getUpdates request"
            #       — a second instance is polling the same token: a stale
            #         Render service, or a local run left open. The two
            #         steal each other's updates and both look broken.
            #
            # Reproduced against a fake Telegram API: in both cases the loop
            # spun forever, wrote NOTHING to the log, and the bot answered no
            # message. From the outside "the bot is dead" — with a healthy
            # /health endpoint and a green deploy.
            if not updates or not updates.get("ok"):
                _fail_streak += 1
                desc = str((updates or {}).get("description") or
                           "no response from Telegram")

                if "webhook is active" in desc.lower() and not _webhook_cleared:
                    # Self-heal, once. This service polls; a webhook on the
                    # same token is always wrong for it, and deleting it is
                    # the documented remedy. Once only, so a genuine webhook
                    # deployment is not fought over in a loop.
                    _webhook_cleared = True
                    logger.error(
                        "TELEGRAM: a webhook is registered on this bot token, so "
                        "getUpdates is refused and the bot receives NOTHING. "
                        "Deleting it automatically (this service polls).")
                    res = _tg("deleteWebhook", drop_pending_updates=False)
                    if (res or {}).get("ok"):
                        logger.warning("TELEGRAM: webhook deleted — polling resumes.")
                        _fail_streak = 0
                        continue
                    logger.error("TELEGRAM: deleteWebhook failed: %s", res)

                elif "terminated by other getupdates" in desc.lower():
                    logger.error(
                        "TELEGRAM: another instance is polling this same bot "
                        "token — updates are being split between them and both "
                        "look broken. Run ONE service per token, or give this "
                        "deployment its own bot.")

                # Never silent again, but never a flood either: the first few
                # failures are logged, then one line a minute.
                elif _fail_streak <= 3 or _fail_streak % 60 == 0:
                    logger.error("TELEGRAM getUpdates failed (%d in a row): %s",
                                 _fail_streak, desc)

                # Back off so a hard failure is not a hot loop against
                # Telegram's API — the old code retried every second forever.
                time.sleep(min(2 * _fail_streak, 30))
                continue

            if _fail_streak:
                logger.warning("TELEGRAM: polling recovered after %d failures.",
                               _fail_streak)
                _fail_streak = 0

            for upd in updates.get("result", []):
                offset = upd["update_id"] + 1
                handle_update(upd)

        except Exception as e:
            print("Poll error:", e)
            time.sleep(3)


def start_bot():
    if not BOT_TOKEN:
        print("TELEGRAM_PING_BOT_TOKEN not set")
        return

    # ASK TELEGRAM WHO WE ARE, ONCE, AT BOOT.
    #
    # A token belonging to a different bot than the Mini App is opened from
    # produces bad_hash, and nothing in the running system could say so — the
    # only way to find out was to open the app, fail, read the log, and guess.
    # getMe answers it in one call at startup, so the fact is in the logs
    # before anyone tries to sign in.
    try:
        from services import miniapp_auth

        # TWO TOKEN NAMES, ONE WINNER, AND NOTHING SAID WHICH. BOT_TOKEN
        # silently outranks TELEGRAM_PING_BOT_TOKEN — but render.yaml only
        # documents the latter, so an owner who replaced their bot by editing
        # the documented name, while a stale BOT_TOKEN sat above it, kept
        # running the OLD bot and had no way to see that. Reproduced.
        src = miniapp_auth.token_sources()
        if src.get("conflict"):
            logger.error(
                "TWO DIFFERENT BOT TOKENS ARE CONFIGURED: %s. Only %s is used "
                "(it takes priority), so every Mini App sign-in is checked "
                "against bot %s. If that is not the bot you are opening, "
                "DELETE the unused variable and redeploy.",
                ", ".join(f"{k}=bot {v}" for k, v in src["bot_ids"].items()),
                src["used"], src["bot_ids"].get(src["used"]))

        who = miniapp_auth.whoami()
        if who.get("ok"):
            # PRINT THE FINGERPRINT AT BOOT, so the value this process is
            # actually running with can be compared against BotFather BEFORE
            # anyone fails to sign in. Every diagnosis so far had to wait for
            # a user to hit the error and then reason backwards; this puts the
            # decisive fact in the deploy log. It is a one-way digest — the
            # secret is never written anywhere.
            fp = miniapp_auth.token_fingerprint()
            logger.warning(
                "TELEGRAM BOT: this server is @%s (id %s), token sha256:%s "
                "(secret %d chars). The Mini App must be opened from THIS bot. "
                "To confirm the deployed token matches BotFather, run: "
                "printf '%%s' '<token>' | sha256sum  — the first 12 characters "
                "must equal %s.",
                who.get("username"), who.get("bot_id"), fp.get("sha256_12"),
                fp.get("secret_length", 0), fp.get("sha256_12"))
            # A truncated or partially-selected paste is invisible in a
            # dashboard field and produces exactly this failure, so measure it.
            _sl = fp.get("secret_length")
            if _sl and _sl != fp.get("secret_length_expected"):
                logger.error(
                    "TELEGRAM TOKEN LOOKS TRUNCATED: the secret half is %d "
                    "characters, expected %d. A partial paste still passes "
                    "getMe in some cases but can never verify a Mini App "
                    "sign-in. Re-copy the whole token.",
                    _sl, fp.get("secret_length_expected"))
            env_name = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
            if env_name and env_name.lower() != (who.get("username") or "").lower():
                logger.error(
                "TELEGRAM MISCONFIGURED: TELEGRAM_BOT_USERNAME is @%s but the "
                    "token belongs to @%s. These must be the same bot.",
                    env_name, who.get("username"))
        else:
            logger.error(
                "TELEGRAM TOKEN REJECTED by getMe (%s). Sign-in will fail until "
                "BOT_TOKEN is a valid token: %s",
                who.get("reason"), who.get("detail", ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning("bot identity check skipped: %s", exc)

    # Register the persistent Mini App button before polling starts, so the
    # entry point exists even for a user who never sends a command.
    try:
        set_menu_button()
    except Exception as exc:  # noqa: BLE001
        print("menu button registration failed:", exc)
    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()
    print("✅ Advanced Bot started (with 5s buffer + inline controls)")