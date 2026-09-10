# CodeNest — Auth + Abuse Prevention: build plan & audit

Implemented in 6 sequential steps, each tested before the next begins.

## Pre-flight audit (what actually existed on `main`)

| Area | Claimed | Reality found |
|---|---|---|
| Telegram login | done | HMAC crashed (500) — **fixed previous turn**; widget never rendered |
| Gmail-only + OTP | done | Gmail check OK, but **all signups returned "CAPTCHA verification failed"** |
| Fingerprint capture | "PRIMARY defense" | Frontend sent it; `UserSignup` had no such field → Pydantic dropped it → **never stored** |
| Fingerprint job limit | done | Query used `j.status` — **column does not exist** → SQL error on every job start with a fingerprint |
| IP aggregate cap | — | did not exist |
| CAPTCHA | math question | input existed in HTML but **JS never read it** → hard-blocked every signup |
| Signup velocity | 10/IP/day | present; no burst flagging |
| Admin clusters | done | `/admin/fingerprint-clusters` **defined twice**; no IP view, no job counts |

### Root cause of the signup outage
`routes/deps.py: UserSignup` did not declare `captcha` or `fingerprint`.
Pydantic silently drops undeclared fields, so `getattr(user, 'captcha', None)`
was always `None`, and `None != "12"` rejected **every** signup — including
correct ones. The same mechanism discarded the fingerprint the browser sent.

---

## Step order (per master prompt §7)

- **Step 1** — Telegram login end-to-end (signup / login / existing-ID reuse)
- **Step 2** — Email+password, Gmail-only, OTP; both methods coexist
- **Step 3** — Device fingerprint captured on BOTH methods, per account + session
- **Step 4** — Job limits: fingerprint-level (3) + IP-level (9)
- **Step 5** — CAPTCHA (Turnstile/hCaptcha + math fallback) + velocity/burst flags
- **Step 6** — Admin visibility: fingerprint clusters, IP clusters, burst flags

Test results for each step are appended below as they complete.

---

# UPDATE — simplified scope (Telegram-only) + RunSpace repair

## §0 Existing abuse-prevention work: PRESERVED, not deleted
`services/limits.py`, `services/captcha.py`, the fingerprint helpers in
`routes/deps.py` and the admin cluster views all remain in the tree and still
pass their full test suite (59/59 with `CLUSTER_LIMITS_ENABLED=1`). They are
simply **switched off by default** behind two env flags:

| Flag | Default | Effect |
|---|---|---|
| `CLUSTER_LIMITS_ENABLED` | `0` | cross-account device/IP job limiting off |
| `TELEGRAM_ONLY_AUTH` | `1` | email+password UI hidden (backend intact) |

## §3 RunSpace stuck — root causes found by reproduction

The hang was reproduced first, then diagnosed from a live thread dump — no guessing.

1. **Deadlock (the actual freeze).** `runner/app.py` `job_restart()` and
   `job_update()` ran `with _jobs_lock: j["port"] = _alloc_port()`, but
   `_alloc_port()` acquires that same **non-reentrant** `threading.Lock`.
   Restart-after-stop blocked forever *while holding the lock*, so every later
   create/list/stop/delete queued behind it and the whole UI froze.
   Thread dump showed the smoking gun: `job_restart → _alloc_port → with _jobs_lock`.
2. **Endless SSE.** The log stream was `while True` with no disconnect check and
   no lifetime bound — each opened job pinned a request plus a worker thread per
   poll until capacity ran out. Now checks `request.is_disconnected()`, caps
   lifetime, sends keep-alives and a `reconnect` event.
3. **`db.connect()` does not exist** (module exposes `get_db_connection`), so
   `autostart bootstrap failed` on every boot and 24/7 restore never ran.
4. **`_downloadBlob` undefined** → `ReferenceError` on 2FA backup-code download.

## §2 Per-account limit corrected
The old check counted **every job row ever created**, so a user was locked out
permanently after 3 lifetime jobs even with all of them stopped. It now counts
only jobs the runner reports as **running**, and stopping one frees a slot.

## §4/§5 Polish
* Job→job switching animates with `transform`/`opacity` only (~180ms,
  GPU-composited), and respects `prefers-reduced-motion`.
* Details page lives at `/runspace/{username}/{tabname}/page`, push-stated so
  Back returns to the editor; deep links and refreshes land on it correctly.

## Test results
| Suite | Result |
|---|---|
| `test_runspace_fixes` (new) | 28 / 28 |
| `test_auth_abuse_system` (flag on) | 59 / 59 |
| `test_bot_critical` | 19 / 19 |
| `test_all_routes` | 65 / 65 |
| `test_routing` | 47 / 47 |
| `test_web_batch` | 24 / 24 |
| `test_security_batch` | 22 / 22 |
