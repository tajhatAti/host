# Bot Store — ready-made bots in raw Python

The Store is the shelf: complete, working Telegram bots that a person can
deploy in one tap and then keep editing as ordinary Python.

It is deliberately the opposite of a visual command builder. On platforms such
as Bots.Business each bot is assembled from *commands*, and the logic inside
each command is written in **BJS** — the platform's own JavaScript dialect
(`Bot.sendMessage`, `User.setProperty`, `Libs.ResourcesLib…`). You learn their
language, and you cannot take the file anywhere else.

Here a listing **is the program**. One `.py` file, real libraries
(`python-telegram-bot`, `aiogram`, `httpx`, `sqlite3`), the token read from
`BOT_TOKEN`. You can read the whole file before you deploy it, and after you
deploy it you are editing the same file you would have written yourself — no
export step, no dialect, no lock-in.

| | Bots.Business | CodeNest Store |
|---|---|---|
| Unit of work | a *command* with a trigger | one complete Python file |
| Language | BJS (custom JavaScript dialect) | raw Python |
| Storage | `Bot.setProperty` / `User.setProperty` | whatever the file uses (`sqlite3`, JSON, …) |
| Reading the source | after install | before install, in the listing |
| After deploy | stays on the platform | ordinary Python you own |

## What a listing carries

`store_items` holds everything the card and the detail page need:

| Field | Meaning |
|---|---|
| `slug` | stable URL/id (`complete-commerce`) |
| `source` | `built-in` (curated, version-controlled) or `community` (submitted) |
| `title`, `summary`, `description` | the shop window |
| `category`, `tags`, `difficulty` | how the shelf is filtered |
| `features` | one line per capability, shown as a checklist |
| `code` | the complete Python file |
| `code_hash` | lets the built-in mirror detect upstream changes |
| `env_fields` | optional secrets the file reads (`AI_API_KEY`, …) |
| `setup_notes` | the "after deploy" instruction |
| `version`, `status`, `review_note` | release + moderation state |
| `install_count`, `rating_sum`, `rating_count`, `featured` | shelf signals |

`store_installs`, `store_reviews` and `store_favorites` keep the per-person
history: what you deployed, what you rated, what you saved.

## Two sources, one catalog

**Built-in.** The seven complete products in `services/bot_templates` are
mirrored into `store_items` on every read (`store.sync_builtins`). The mirror
refreshes content when `code_hash` changes and **never** resets installs,
ratings or favourites, so the curated products behave exactly like community
listings while their source stays under version control.

**Community.** Any signed-in user can publish a bot. It is validated, then
waits in the owner review queue.

## The submission gate

`services/store.check_code` + `store.validate_submission` run before anything
is written:

- the file **compiles** (`compile(..., "exec")`);
- the token comes from the **environment** — a token-shaped literal is a hard
  rejection, a missing `BOT_TOKEN` reference is a hard rejection;
- size limit 400 KB;
- title ≥ 3 chars, summary ≥ 10 chars, category and difficulty from the fixed
  lists;
- warnings (not rejections) for a non-Telegram file, a missing polling loop,
  credential-looking literals, or destructive shell commands — the reviewer
  sees them in the queue.

A rejected form never reaches the review queue, so it does **not** cost the
author one of their five submissions per hour. The budget is spent only when a
listing actually enters the queue.

## API

| Method | Path | Who |
|---|---|---|
| GET | `/api/store?q=&category=&sort=&source=&limit=&offset=` | public |
| GET | `/api/store/categories` | public |
| GET | `/api/store/{slug}` | public (full source needs a session) |
| POST | `/api/store/{slug}/install` | signed in |
| POST | `/api/store/{slug}/rate` | signed in |
| POST / DELETE | `/api/store/{slug}/favorite` | signed in |
| GET | `/api/store/mine/library` | signed in |
| POST | `/api/store/items` | signed in |
| PATCH | `/api/store/items/{slug}` | the author |
| GET | `/api/store/admin/queue?status=` | owner (404-stealth) |
| POST | `/api/store/admin/{slug}/{approve\|reject\|remove\|restore\|feature}` | owner (404-stealth) |
| GET | `/api/store/admin/stats` | owner (404-stealth) |

Sorting: `popular` (default), `rating`, `newest`, `name`.

The detail endpoint returns `code_preview` (first 40 lines) to an anonymous
visitor and the full `code` to a signed-in reader — the store sells raw
Python, so hiding the file from the person about to deploy it would hide the
product.

## Deploying a listing

`POST /api/store/{slug}/install` records the install and returns the complete
deploy payload (`code`, `language`, `env_fields`, `after_deploy`). The browser
then hands that payload to the **one** Add Bot wizard the rest of the product
uses (`openAddBot` → token verification → `_analyzeRunSpaceBot` → deploy).
There is no second deploy path.

## UI

- Desktop: a real **Store** tab (`/store`), search, sort chips, category rail,
  card grid, listing modal with the full file, ratings, save, deploy.
- Mobile: the bottom nav stays *Bots · Add · Account* (that rule is enforced
  by `tests/js/test_bot_product_shell.js`), so the Store is reached from the
  **Bot Store** row in the one Bots menu.
- **Publish a bot** posts the file for review; **My library** lists saved,
  deployed and published listings with their moderation state.

## Portable SQL

The store runs on SQLite locally and PostgreSQL in production from the same
code: no `INSERT OR REPLACE`, no `IFNULL`, no `COLLATE NOCASE`, no
`datetime('now')`, and ratings/favourites are upserted with an explicit
`SELECT` + `UPDATE`/`INSERT` because the unique index is created separately.
`tests/validate_postgres_sql.py` parses every statement in
`services/store.py` and `routes/store.py` with the real PostgreSQL grammar.

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_store.py   # 17 checks
node tests/js/test_store_ui.js                                   # 62 checks
```

Both run in `scripts/test-core.sh` (and therefore in CI).
