# Per-job URLs and Telegram bot analytics

## Per-job URLs

Canonical links no longer contain a username:

- `/runspace/{job}` — editor
- `/runspace/{job}/logs`
- `/runspace/{job}/details`
- `/runspace/{job}/database`
- `/runspace/{job}/env`
- `/runspace/{job}/settings`

Old `/runspace/{username}/{job}` and `/page` links remain readable. The browser router selects the named job and opens the requested drawer tab. Written URLs are generated from the job name only; API authorization remains the ownership boundary.

Measured against the running FastAPI server on 2026-08-18: the editor, logs, and database forms each returned the SPA shell with HTTP 200. The parser's canonical, legacy, section, ambiguity, and invalid-path cases are covered in `tests/js/test_job_urls.js`.

## Bot event recording

`services/bot_analytics.py` stores dispatched Telegram updates in `bot_events`. It records commands, callbacks, pending code uploads, unknown input, refusals, and handler failures. It intentionally stores a command target but not arbitrary message text.

Important properties:

- People are distinct `chat_id` values, including chats not linked to a CodeNest account.
- Handler outcomes are written from `finally`, including crashes.
- Recording is best effort and cannot replace or break a command's outcome.
- `/command@BotName` works in groups.
- Commands are exact, so `/stopall` cannot invoke `/stop`.
- `GET /admin/bot-usage?days=N` returns aggregates and a recent event feed.
- `GET /admin/bot-usage.csv?days=N` returns UTF-8-with-BOM CSV using Python's CSV writer.
- Both routes use the existing admin-only 404-stealth gate.

The admin console shows people, linked/unlinked split, actions, today's actions, failures, daily activity, ranked commands, people, and recent events. All Telegram-controlled strings are rendered with `textContent`, not `innerHTML`.

Measured against the running server: authenticated JSON and CSV returned HTTP 200; an unauthenticated analytics request returned HTTP 404.

## Verification

Passing checks added for this work:

- `tests/test_bot_analytics.py` — aggregation, failures, robust CSV, fail-open recording
- `tests/test_bot_dispatch_analytics.py` — group commands, exact matching, crash recording
- `tests/test_job_url_routes.py` — canonical and legacy server routes
- `tests/js/test_job_urls.js` — URL parser
- `tests/js/test_admin_bot_usage.js` — safe DOM rendering, sparkline, timestamps

No screenshot or browser-layout claim is made. UI wiring and DOM safety were tested in jsdom; the live preview is available for visual review.
