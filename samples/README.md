# Telegram Ping Bot (sample)

A tiny Telegram bot that measures real HTTP latency from wherever it's running
to any website you throw at it.

## Run it on CodeNest RunSpace (easiest)

1. Open CodeNest → RunSpace → **New Job** (Language: **Python**).
2. Paste the contents of [`ping_bot.py`](./ping_bot.py) into the editor.
3. Set environment variable `BOT_TOKEN` to a bot token you got from
   [@BotFather](https://t.me/BotFather).
   (In RunSpace, open the "Env Vars" drawer and add `BOT_TOKEN=<your-token>`.)
4. Hit **Run**. That's it — no install step; the runner auto-detects the
   `telegram` and `aiohttp` imports and installs them for you.

## Run locally

```bash
pip install python-telegram-bot aiohttp
export BOT_TOKEN=xxxxxxxxxx:yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy
python ping_bot.py
```

## Commands

| Command              | What it does                                           |
|----------------------|--------------------------------------------------------|
| `/start`             | Welcome + usage hint                                   |
| `/help`              | Shows this command list                                |
| `/ping`              | Pings the default target (set via `PING_DEFAULT_TARGET`, default `https://ahadorg.onrender.com`) |
| `/ping <url>`        | Pings `<url>`; auto-adds `https://` if missing         |

The timer starts *right before* the HTTP request is sent and stops *immediately
after* headers come back — so the reported ms is pure server↔target latency
(the Telegram API round-trip for the reply is **not** counted, which is what
you want).

### Latency color key

| Response time | Dot |
|---------------|-----|
| < 150 ms      | 🟢  |
| 150–500 ms    | 🟡  |
| 500–1500 ms   | 🟠  |
| > 1500 ms     | 🔴  |

## Optional env vars

| Name                   | Default                         | Description                        |
|------------------------|---------------------------------|------------------------------------|
| `BOT_TOKEN`            | *(none — required)*             | Telegram bot token from BotFather  |
| `PING_DEFAULT_TARGET`  | `https://ahadorg.onrender.com`  | URL hit when `/ping` has no arg    |
| `PING_TIMEOUT_S`       | `5`                             | Per-request timeout in seconds     |

## ⚠️ Token security

**Never commit your live bot token.** If a token shows up in a chat, a paste,
or a GitHub commit — consider it leaked. Rotate it immediately in
@BotFather (`/revoke` then `/token`) and store the new one only in env vars /
host secret manager.

```
/botfather → /mybots → <your bot> → API Token → Revoke
```
