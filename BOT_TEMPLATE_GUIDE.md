# Complete bot product guide

CodeNest intentionally exposes **seven complete Python bot products** — one template = one job. Each product covers its category exhaustively (force-join, forwarding, tag remover, captions and inline buttons all belong to channel management; invite tracking, points and withdrawals belong to referral & rewards). Nothing is borrowed from a neighbouring category, and nothing is split into tiny feature fragments:

1. **Complete group moderator** (Community) — captcha, anti-flood, links, blocked words, rules, warnings, timed mute, ban/unban, lock/unlock, reports, stats, and audit history.
2. **Complete channel manager** (Channels) — force-join gate, membership checks, member approval with private invite links, scheduled posts, auto-delete, broadcasts, content forwarding/copying to the channel, tag remover, caption editing, inline buttons on channel posts, and channel statistics.
3. **Complete referral & rewards** (Rewards) — personal invite links, referral tracking, points balance, leaderboard, withdrawal requests, owner payout approvals, rate/minimum settings, and broadcasts.
4. **Complete Telegram store** (Commerce) — catalog, stock, cart, checkout, payment review, order history, buyer notifications, support, and sales analytics.
5. **Complete file share** (Files) — Telegram deep links, expiry dates, download limits, per-user link settings, revoke/delete, and owner statistics.
6. **Complete media & AI converter** (Media & AI) — image compression, JPG/PNG/WebP/PDF conversion, image-to-PDF, PDF text extraction, OCR, voice transcription, text-to-speech, and QR codes.
7. **Complete AI business assistant** (AI & Support) — OpenAI-compatible provider, Bangla/Banglish policy prompt, memory, quota, analytics, ban controls, and broadcast.

Templates are optional. **Own code** accepts pasted Python directly and **Upload file** accepts a `.py` file.

## Scope of each product (one template = one job)

| Product | Category | Scope (what it DOES) | Explicitly OUT of scope |
|---|---|---|---|
| Complete group moderator | Community | Captcha, anti-flood, link guard, blocked words, rules, warn/mute/ban, locks, reports, audit | Channel publishing, store, referrals |
| Complete channel manager | Channels | Force-join gate, membership checks, member approval + private invites, scheduled posts, auto-delete, broadcasts, content forwarding, tag remover, captions, inline buttons, stats | Referral points, paid subscriptions, payouts |
| Complete referral & rewards | Rewards | Invite links, referral tracking, points, leaderboard, withdrawal requests, payout approvals | Channel management, paid memberships |
| Complete Telegram store | Commerce | Catalog, stock, cart, checkout, payment review, orders, notifications, support, analytics | Referrals, channel publishing |
| Complete file share | Files | Deep links, expiry, download limits, per-user settings, revoke/delete, stats | Media conversion, AI, scanning |
| Complete media & AI converter | Media & AI | Image compress/convert, image→PDF, PDF→text, OCR, voice→text, text→voice, QR | File sharing links, malware scanning |
| Complete AI business assistant | AI & Support | AI chat, memory, policy prompt, quotas, analytics, bans, broadcast | Store checkout, file storage |

## One-tap deploy

Add Bot is token-first and stays simple: paste the BotFather token → verify → tap a product → it deploys instantly. There is no second options screen after template selection. Optional API keys (`AI_API_KEY`, `OCR_API_KEY`, `PAYMENT_URL`, …) can be added any time after deploy from the bot's settings — a template never blocks the run.

## Admin identity

Products that need a private owner receive an encrypted generated `ADMIN_CLAIM_CODE`. The post-deploy **Go to bot** link opens with `?start=claim_<code>` and claims the first owner without asking for a numeric Telegram ID.

## Telegram limitations

Membership checks require the bot to be an administrator. Bots cannot silently add arbitrary users. Payment-reference flows require owner/provider verification unless an actual merchant checkout URL is configured.
