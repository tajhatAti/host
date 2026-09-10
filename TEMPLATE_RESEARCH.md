# Telegram bot product research

Research updated: 2026-08-25

There is no trustworthy official global installation ranking. Repeated categories across current Telegram directories and mature open-source products were used instead:

- group moderation/captcha/anti-spam;
- channel management (force-join, approvals, scheduling, forwarding, tag removal, captions, inline buttons);
- referral & rewards (invite tracking, points, withdrawals);
- file storage/sharing;
- media & AI conversion (image/PDF/voice/text);
- AI assistants and business support;
- shops, carts, payments and order tracking.

References:

- Telegram Bot API: https://core.telegram.org/bots/api
- Telegram Bot FAQ/rate limits: https://core.telegram.org/bots/faq
- python-telegram-bot examples: https://github.com/python-telegram-bot/python-telegram-bot/tree/master/examples
- current Telegram bot category directory: https://www.itechguides.com/70-best-telegram-bots-list/
- business workflow research: https://blog.bothero.ai/the-telegram-bot-list-that-actually-matters-27-bots-organized-by-what-they-do-for-small-businesses-and-what-you-can-steal-for-your-own
- shop architecture: https://github.com/ilyarolf/AiogramShopBot
- support architecture: https://github.com/bostrot/telegram-support-bot

## One template = one job

The previous 101-entry catalog reused a few engines across many names and merged neighbouring categories (e.g. channel management with referral payouts). It was removed. The public catalog now has seven integrated products; each product owns exactly one category exhaustively — depth inside the category is welcome, borrowing another category's core feature is not.

## One-tap deploy

Template selection deploys immediately after token verification. No second options screen: optional API keys are added later from bot settings, and the admin claim code is generated automatically into the Go-to-bot link.

## Validation

Automated tests require every public product to:

- be standalone Python;
- read `BOT_TOKEN` from the environment;
- contain no token-shaped literal;
- compile successfully;
- use polling correctly;
- execute its embedded SQLite schema;
- contain the advertised integrated controls for its category;
- contain **no** marker from a neighbouring category (no `referrer` inside channel management, no `Image.open` inside file share, no `virustotal` inside the media converter, …).
