# Ping Bot — Telegram website-latency checker.
#
# Paste this straight into CodeNest RunSpace as a Python job, or run locally:
#     pip install python-telegram-bot aiohttp
#     BOT_TOKEN=xxx python ping_bot.py
#
# `/ping [url]`  — measures real HTTP response-time (server -> target, excludes
#                  Telegram API hop) and replies with status + latency.
# Default target when no URL is given can be edited below.
#
# ⚠️ NEVER hardcode your real bot token in code you paste / commit. Put it in
# the RunSpace "Env Vars" panel as BOT_TOKEN (key=value), or export it in your
# shell before running. The old token you see in git history is already
# publicly exposed — rotate it via @BotFather RIGHT NOW if it's still live.
#
# requirements: python-telegram-bot aiohttp

import os
import time
import asyncio
import logging

import aiohttp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("pingbot")

# ---- config -----------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DEFAULT_TARGET = os.environ.get("PING_DEFAULT_TARGET", "https://ahadorg.onrender.com")
REQUEST_TIMEOUT_S = float(os.environ.get("PING_TIMEOUT_S", "5"))
USER_AGENT = "CodeNest-PingBot/1.0 (+https://codenest.dev)"


async def ping_website(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /ping [url]  — pings target and returns real HTTP response time."""
    # parse argument
    args = context.args or []
    target = args[0].strip() if args else DEFAULT_TARGET
    if not target:
        target = DEFAULT_TARGET
    if not target.startswith(("http://", "https://")):
        target = "https://" + target

    # 1. start timer BEFORE we send anything to the target
    start = time.perf_counter()
    status_code = None
    error = None
    try:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)
        headers = {"User-Agent": USER_AGENT}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as sess:
            # HEAD is lighter than GET and enough for a reachability ping.
            # Some hosts block HEAD; fall back to GET on 405/501.
            for method in ("head", "get"):
                try:
                    async with getattr(sess, method)(
                        target, allow_redirects=True
                    ) as resp:
                        status_code = resp.status
                    break
                except aiohttp.ClientResponseError as cre:
                    if cre.status in (405, 501) and method == "head":
                        continue
                    raise
        end = time.perf_counter()  # stop IMMEDIATELY after headers arrive
    except asyncio.TimeoutError:
        error = f"❌ Connection to `{target}` timed out ({int(REQUEST_TIMEOUT_S)}s)."
    except aiohttp.ClientError as e:
        error = f"❌ Error connecting to `{target}`: {e}"
    except Exception as e:  # noqa: BLE001 - surface anything unexpected
        log.exception("ping failed")
        error = f"❌ Unexpected error: {e}"

    if error:
        await update.message.reply_text(error)
        return

    ms = (end - start) * 1000
    # tiny latency bar for quick eyeballing
    if ms < 150:
        bar = "🟢"
    elif ms < 500:
        bar = "🟡"
    elif ms < 1500:
        bar = "🟠"
    else:
        bar = "🔴"

    text = (
        f"🌐 *Target:* {target}\n"
        f"⚡ *Response:* {bar} `{ms:.2f} ms`\n"
        f"📊 *HTTP Status:* `{status_code}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    who = (update.effective_user.first_name or "friend") if update.effective_user else "friend"
    await update.message.reply_text(
        f"👋 Hi {who}! I'm a website-ping bot.\n\n"
        "Send `/ping [url]` to measure real HTTP latency (server → website, "
        "excluding Telegram hop).\n"
        "Example: `/ping google.com`",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *PingBot commands*\n\n"
        "/start — intro\n"
        "/help  — this message\n"
        f"/ping [url] — ping a URL (default: `{DEFAULT_TARGET}`)\n\n"
        f"Request timeout: {int(REQUEST_TIMEOUT_S)}s. Timing stops as soon as HTTP "
        "headers arrive, so the number you see is pure server↔target latency.",
        parse_mode="Markdown",
    )


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN not set. Export it in env, or add it in the RunSpace "
            "Env Vars panel as BOT_TOKEN=<token from @BotFather>."
        )
    app_ = ApplicationBuilder().token(BOT_TOKEN).build()
    app_.add_handler(CommandHandler("start", cmd_start))
    app_.add_handler(CommandHandler("help", cmd_help))
    app_.add_handler(CommandHandler("ping", ping_website))
    log.info("PingBot starting (default target=%s, timeout=%ss)",
             DEFAULT_TARGET, int(REQUEST_TIMEOUT_S))
    app_.run_polling()


if __name__ == "__main__":
    main()
