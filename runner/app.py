I'm uploading the full zip of my project, "CodeNest" — a platform where users deploy and manage Telegram bots (and small web apps) that run 24/7. It's a FastAPI backend + vanilla JS/HTML frontend + a separate "runner" service that actually executes user code, plus a Telegram bot ("pingbot") that lets me (the owner) control everything from chat.

Please read this whole message before touching any code.

## How I want you to work
- Never guess. Before changing anything, actually open the relevant file(s) and read the real code. If you're not sure where something lives, search for it first.
- When you give me a fix, always tell me the exact file path it goes in (e.g. `services/pingbot.py`), so I know exactly what to replace.
- After editing a Python file, compile-check it (`python3 -m py_compile <file>`) before handing it to me. For JS, use `node --check`. For HTML, parse it. Never give me code you haven't verified is syntactically valid.
- If a bug could have more than one cause, investigate the actual code first — don't guess-and-patch. I've been burned before by fixes that assumed a cause without checking.
- Keep changes scoped and minimal — don't rewrite things that already work. If you find something that looks broken but isn't what I asked about, tell me, don't silently "fix" it.
- I'm on mobile, testing via Termux/browser. Keep explanations short and in Bangla/Banglish, matching how I write to you.

## Project facts that matter
- **Deploy target:** Render, free tier. This means the whole web service SLEEPS after inactivity and takes 30-60s to wake on the next request. This has caused multiple confusing bugs already (slow loads, Telegram buttons needing 10-20 taps). If something seems "randomly slow" or "sometimes doesn't respond," check whether it's this before assuming it's a code bug.
- **static/app.css and static/pro.js are loaded with a cache-busting version query string** (`?v=YYYYMMDDx`) in `index.html`. Every time you edit either file, bump that version string too, or the browser will keep serving the old cached copy and my testing will look like your fix didn't work.
- **Dark theme hex spec** (the whole site uses this now, no exceptions): background `#0F0F11`, card `#1E1E22`, border `#27272A`, text white `#FFFFFF`, muted text `#A1A1AA`, primary buttons white bg / dark text. No indigo/purple anywhere — I've had it leak back in from old CSS blocks multiple times, so if you touch app.css, grep for `4f46e5`, `6366f1`, `99 102 241`, `79 70 229` first and make sure nothing reintroduces it.
- **The bot deploy model:** each job normally runs ONE entry file, but multi-file apps now work too — via GitHub import (`repo_url`) or a `.zip` upload (`zip_b64`), both extracted into the job's real directory on the runner, then auto-detected via `_detect_entry` in `runner/app.py`. This applies on both create AND update now.
- **Requirements (pip packages)** are declared via a `# requirements: pkg==1.0` comment on the first line of the code — this is the runner's actual parsing mechanism, don't change it. Both the web editor and the Telegram bot have their own UI on top of it (a labeled box / an asked question) so nobody has to hand-type that comment.
- **pingbot.py runs in WEBHOOK mode now**, not long-polling — this was the fix for the Render-sleep button-lag problem. There's a `webhook_router` registered in `app.py` at `/telegram/webhook`, secured by a secret token derived from `BOT_TOKEN`. Don't reintroduce polling as the primary mode; it's kept only as an automatic fallback if webhook registration fails.
- **The Telegram admin panel** (`/admin` in chat) is fully inline-button-driven now — I explicitly don't want typed subcommands as the primary interface. If you add a new admin feature, it needs a button reachable from the `/admin` main menu, not just a slash command I have to remember.
- **A hardcoded super-admin Telegram ID** exists in `services/pingbot.py` as `SUPER_ADMIN_TG_ID` — intentionally not an env var, by my request.
- **Multi-step admin actions use a conversational flow** (bot asks one field at a time) rather than requiring everything on one line — see `ADMIN_FLOWS` / `_admin_flow` in `pingbot.py`. Follow that pattern for any new multi-field admin action instead of a single long command.

## Known-fragile areas (double-check before trusting)
- There have been multiple incidents where a fix worked in the code but never showed up live because it wasn't actually deployed yet, or was deployed to the wrong branch/repo copy. If I say "it's still broken" right after you gave me a fix, your first question should be "did you redeploy?", not "let me guess a new cause."
- CSS has previously had duplicate/stale `:root` blocks silently overriding earlier fixes. If a color or style change "doesn't take," grep the whole file for other definitions of the same property before assuming your edit was wrong.

## What's already built (don't rebuild from scratch — extend it)
Telegram bot commands: `/start /link /unlink /code /update /import /apps /status /logs /restart /stop /delete /rename /admin /zip /unzip /see`. Admin panel covers: user management (admin/zip-permission/suspend, suspend cascades to stop jobs), runners (add/enable/disable/delete/rotate secret/health-check), jobs (list/detail/restart/stop/delete/revision-rollback), audit log (incl. per-admin filter), abuse reports, Telegram-level bans, per-user job-limit override, broadcast, search (users/jobs), CSV export, recent signups, store moderation queue, fingerprint-cluster view, terms-agreement status, maintenance-mode flag (flag only — doesn't block traffic yet, that needs `app.py` wiring if I ask for it).

Ask me for the zip now if you haven't received it yet, then start by exploring the project structure before I ask for anything specific.
