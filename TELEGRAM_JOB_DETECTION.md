# Telegram bot hosting flow

RunSpace uses a four-step **Add Bot 🤖** flow:

1. **Code** — paste, upload, or import the bot code.
2. **Connect bot** — verify a BotFather token after analysis.
3. **Review** — confirm bot identity, framework, update mode, runtime, and token handling.
4. **Deploy** — run the bot with secrets supplied through its environment.

## Code analysis

`POST /api/telegram-bot/analyze` identifies common Python and Node Telegram frameworks, polling vs webhook delivery, and whether the source uses an environment variable, a hardcoded token, or an example placeholder. It reports metadata only; it never returns source or secrets.

Supported framework signals include aiogram, python-telegram-bot, pyTelegramBotAPI/telebot, Telethon, Pyrogram, Telegraf, grammY, and node-telegram-bot-api.

## Connecting a bot

After analysis, the owner pastes a BotFather token. The server asks Telegram `getMe`, then returns the verified `@username`, a clickable link, and a 15-minute single-use verification proof. The database stores only the token's SHA-256 digest in that proof—not the token.

The browser submits the token as `BOT_TOKEN` together with the proof. The server checks that the authenticated user, proof, token digest, and expiry all match. The proof is consumed only after successful bot creation. The environment is encrypted at rest with `JOB_SECRETS_KEY`, and owner APIs return secret-looking values as write-only masks.

A keyed token fingerprint is retained separately from the encrypted value. CodeNest rejects a second deployed bot using the same BotFather token, preventing the common Telegram `409 terminated by other getUpdates request` conflict inside the platform.

## Automatic secret repair

Raw tokens do not belong in source code. Before code reaches the runner, CodeNest changes hardcoded/example token assignments and common Telegram constructor arguments to read `BOT_TOKEN` from the environment:

- Python: `os.getenv("BOT_TOKEN")`
- Node.js: `process.env.BOT_TOKEN`
- Ruby: `ENV.fetch("BOT_TOKEN")`
- PHP: `getenv('BOT_TOKEN')`
- Bash: `$BOT_TOKEN`

Old real Telegram token literals are removed from source. The verified token exists only in the job environment. A browser cannot bypass this repair because the token hash must match the server-side verification proof.

Each account can run at most three bots; the fourth is rejected server-side.

## Status and administration

The RunSpace bot card separates:

- Telegram identity verification;
- runner process status;
- framework and polling/webhook analysis;
- direct **Go to your bot** link.

The admin console’s **Telegram bots on RunSpace** section shows owner, bot job, framework, update mode, process status, token-check status, uptime, deployment revision outcomes, and a safe direct link. Immutable run/update/restart/rollback history records who ran what without duplicating secrets. Failed candidate source remains in version history for diagnosis but never replaces the last healthy job source.

“Process running” and “Telegram identity verified” do not falsely claim every command handler is working; application behavior still belongs in logs and activity monitoring.
