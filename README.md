# CodeNest — Managed Telegram Bot Hosting

CodeNest is a FastAPI + vanilla-JavaScript platform for analyzing, connecting, deploying, and monitoring Telegram bots. Users can paste/upload bot code, verify a BotFather token, review framework and delivery-mode analysis, and run up to three bots.

## Render deploy

This is a **Docker** web service (`runtime: docker` in `render.yaml`). Do **not** set Node as the runtime.

| Field | Value |
|---|---|
| Runtime | Docker |
| Dockerfile path | `./Dockerfile` |
| Health check | `/health` |
| Build Command | leave Render's Docker default (the image builds itself) |

Set `DATABASE_URL`, `JOB_SECRETS_KEY`, `SITE_BASE_URL` (or rely on `RENDER_EXTERNAL_URL`), and `TELEGRAM_PING_BOT_TOKEN` in the dashboard.

The default `claude` branch of the old repo shipped a truncated `index.html` stub that never loaded `pro.js`/`miniapp.js`, so the boot overlay stayed on **“Securing your session…”** forever. This copy uses the full shell and hides that splash after 2.5s even if JS fails.

## Add Bot flow

1. **Source** — optionally choose a practical template, or simply name the bot and paste/upload custom code. Continue performs analysis automatically.
2. **Connect & Deploy** — enter the BotFather token; successful verification deploys immediately and opens a single-action **Go to bot** page. Hardcoded tokens are changed to read the write-only `BOT_TOKEN` environment secret.

Supported analysis signals include aiogram, python-telegram-bot, pyTelegramBotAPI/telebot, Telethon, Pyrogram, Telegraf, grammY, and node-telegram-bot-api.

## Practical starter gallery

The Add Bot flow includes 21 searchable, categorized starters rather than demo snippets: a master channel-referral/reward system, Livegram-style two-way support, simpler referral modes, self-claimed admin broadcasts, channel posting, channel join gates, group welcome/rules/warnings, order notifications, deep-link file sharing, inline menus, polls, reminders, SQLite notes, URL checks, and Python/Node foundations.

Admin-capable templates do not ask users to discover a numeric Telegram ID. The wizard generates an encrypted one-time `ADMIN_CLAIM_CODE`, then puts it into the **Go to bot** deep link after deployment. Pressing Start through that link makes the bot store the sender's real Telegram user ID and refuse future claims—no ID or command needs to be typed. The Master Referral template follows the requested first-opener rule instead.

## Bot Store

The **Store** tab (`/store`) is a shelf of complete bots — and every listing is
one complete **Python** file, not a set of commands in a platform dialect. Read
the whole source before you deploy, deploy it in one tap, then keep editing the
same file. The seven curated products are mirrored from `services/bot_templates`
so installs, ratings and favourites attach to them like any other listing, and
signed-in users can publish their own bots: the file must compile, read
`BOT_TOKEN` from the environment and embed no token, then an owner approves it.
Full details in `STORE.md`.

## Main capabilities

- Email and Telegram authentication
- Telegram Mini App sign-in verification
- Code-first bot hosting wizard with Python/Node starter templates
- Bot Store: curated + community listings, each one raw Python file
- Encrypted bot environment secrets at rest
- Duplicate-token deployment prevention
- Polling/webhook diagnostics and duplicate-poller detection
- Run/stop/restart, live logs, CPU/memory and uptime
- Immutable deployment versions, failed-candidate isolation, and one-click rollback
- Per-job URLs and direct `t.me` links
- Bot workspace snapshots and restore
- Admin bot inventory, usage history, abuse controls, and audit log
- SQLite locally; PostgreSQL/Supabase in production
- Embedded runner for development and remote runner pool support

## Security model

- Raw BotFather tokens are never returned in bot/admin metadata.
- Secret-looking environment values are write-only in owner APIs.
- `JOB_SECRETS_KEY` encrypts bot environments at rest with Fernet.
- A keyed token fingerprint prevents the same Telegram token from being deployed twice on CodeNest.
- Verification proofs are authenticated, expire after 15 minutes, and are consumed after creation.
- Admin routes are 404-stealth for non-admin callers.

> **Production warning:** the embedded runner executes user code in the main container and is intended for development/single-owner deployments. Public multi-tenant production should set `RUNNER_SERVICE_URL` and `RUNNER_SERVICE_SECRET` and run the execution service separately. Strong per-job container/microVM isolation is still recommended for hostile public code.

## Local UI preview (no backend)

If you only want to review/fix the UI without starting the Python server, the
front-end has a self-contained demo mode. It serves sample bots, store items,
snippets and admin numbers from the browser — no database, no runner, no
backend touched.

```bash
git clone <your-repo-url>
cd Claude
python3 -m http.server 8080
```

Then open `http://localhost:8080`. The app detects the static server and shows
the dashboard in **Demo UI** mode with a small pill in the header. To force
demo mode anywhere, append `?demo=1` (for example `http://localhost:8080/?demo=1`).

In demo mode the **···** menu's **Stop**, **Restart** and **Bot details**
actions are simulated locally, and the left drawer's **Overview / Bots /
Store / Profile / Admin** items are fully clickable.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx websockets

DB_PATH=/tmp/codenest.db \
DATA_DIR=/tmp/codenest-data \
RUNNER_MODE=embedded \
.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

For encrypted local bot secrets, also set a stable key:

```bash
export JOB_SECRETS_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

Do not rotate or lose this key while encrypted bot environments exist.

## Adding runner capacity

Admins can add runners from **Admin → Runners → Add runner** without editing `RUNNER_SERVICE_URLS` or redeploying the main site:

1. In Render create a Web Service from this repository.
2. Set Root Directory to `runner` and Runtime to Docker.
3. In CodeNest click **Generate secret**, then set it as the runner's `RUNNER_SERVICE_SECRET`.
4. Deploy the Render service.
5. Paste its public URL and the same secret into CodeNest; **Test & add runner** verifies health and authentication before enabling placement.

Runner credentials are encrypted with `JOB_SECRETS_KEY` and never returned by the API. **Drain** removes a runner from new-job placement while keeping existing assigned jobs addressable. Deletion is blocked until no deployed jobs remain. When the first remote runner is added, already-running embedded jobs are explicitly pinned to the embedded engine while new bots use the remote pool. Environment-configured runners continue to work beside database-managed runners.

## Production topology

Recommended:

```text
Browser / Telegram Mini App
            |
       Main FastAPI site
       (users + Postgres)
            |
   authenticated runner API
            |
      Isolated runner pool
```

Required/important environment variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Durable PostgreSQL database |
| `JOB_SECRETS_KEY` | Encrypt hosted-bot environment secrets |
| `ADMIN_EMAILS` | Comma-separated platform owners |
| `RUNNER_SERVICE_URL` | Remote execution service |
| `RUNNER_SERVICE_SECRET` | Shared main-site/runner credential |
| `SITE_BASE_URL` | Public custom domain override |
| `TELEGRAM_PING_BOT_TOKEN` | CodeNest control/login bot |
| `TELEGRAM_BOT_USERNAME` | Public control bot username |
| `BREVO_API_KEY` | Email OTP delivery |
| `SENDER_EMAIL` | Verified email sender |
| `CORS_ALLOWED_ORIGINS` | Optional comma-separated trusted external origins |

`render.yaml` generates `JOB_SECRETS_KEY`; configure the remaining secret values in Render.

## Safe deployments and rollback

Every successful creation/update is stored as an immutable source revision. An update remains a `building` candidate until the runner accepts it; a rejected candidate is marked `failed` and never replaces the last healthy source. The Versions tab lists status/error history and can restore any healthy revision. Rollback reuses the current encrypted environment secrets and preserves the bot workspace.

## Bot health

The owner bot card separates:

- Telegram token validity
- Runner process status
- Polling/webhook configuration
- Webhook error and pending-update information
- Duplicate `getUpdates` poller conflicts detected from runtime logs

“Process running” is not presented as proof that every command handler works.

## Persistence

Bot source and encrypted environment configuration live in the main database. Runtime workspaces live on the runner. A snapshot service stores bot-generated SQLite/JSON/data files for cold-start recovery. For larger production workloads, move snapshot payloads from PostgreSQL to object storage.

## Tests

GitHub Actions runs the same core gate used locally:

```bash
pip install -r requirements-dev.txt
npm ci --ignore-scripts
PYTHON_BIN=.venv/bin/python scripts/test-core.sh
```

The gate compiles Python/JavaScript, runs backend security and bot-hosting tests, executes jsdom UI suites, parses emitted SQL as PostgreSQL, checks npm high-severity advisories, and rejects whitespace errors.

Focused suites live under `tests/` and `tests/js/`. Typical commands:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/test_telegram_job_detection.py \
  tests/test_admin_abuse_controls.py \
  tests/test_bot_analytics.py

node tests/js/test_telegram_job_ui.js
node tests/js/test_admin_live.js
```

Some integration scripts require isolated paths:

```bash
DATA_DIR=$(mktemp -d) DB_PATH=$(mktemp -d)/test.db \
  .venv/bin/python tests/test_admin_dashboard.py
```

## Additional documentation

- `STORE.md`
- `TELEGRAM_JOB_DETECTION.md`
- `BOT_TEMPLATE_GUIDE.md`
- `JOB_URLS_AND_BOT_ANALYTICS.md`
- `runner/README.md`
- `runner/SYSTEM_TOOLS.md`
