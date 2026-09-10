# 🤖 Bot Feature — Full Check Report (বাংলা)

তারিখ: 2026-07-26 · ব্রাঞ্চ: `arena/019f9d95-h`
রিভিউ করা ফাইল: `services/pingbot.py`, `bot/app.py`, `routes/ping.py`,
`routes/auth.py` (`/auth/telegram`), `index.html` (Telegram widget), `app.py`,
`samples/ping_bot.py`, `runner/app.py`

> ✅ **আপডেট (2026-07-26):** CRITICAL ১-৪ **ফিক্স করা হয়েছে ও টেস্ট করা হয়েছে**
> — `tests/test_bot_critical.py` (19 pass, 0 fail)। নিচে প্রতিটির পাশে স্ট্যাটাস
> দেওয়া আছে। HIGH/MEDIUM আইটেমগুলো এখনো বাকি।

---

## 📍 প্রজেক্টে বট আসলে কয়টা?

| # | কোথায় | টোকেন env | কী করে | চলে কোথায় |
|---|---|---|---|---|
| 1 | `services/pingbot.py` | `TELEGRAM_PING_BOT_TOKEN` | `/ping`, `/code` → RunSpace-এ deploy, inline buttons | মেইন সাইটের ভেতরেই thread (app startup) |
| 2 | `bot/app.py` | `TELEGRAM_BOT_TOKEN` | `/start /help /echo /time /ping` (SSRF-safe) | আলাদা Render service (#3) |
| 3 | `samples/ping_bot.py` | `BOT_TOKEN` | ইউজারদের জন্য sample bot | RunSpace job |
| — | `routes/ping.py` | — | `/ping` পেজ + `/api/ping` JSON | মেইন সাইট |

**সমস্যা:** ১ আর ২ দুটোই একই কাজের ওভারল্যাপ, আলাদা টোকেন, আলাদা কোয়ালিটি।
`bot/app.py` ভালো লেখা (SSRF গার্ড আছে), `services/pingbot.py` দুর্বল — অথচ
production-এ ওটাই auto-start হয় (`app.py:66-70`)।

---

## ✅ CRITICAL — সব ফিক্সড (আগে: এখনই ভাঙা)

### 1. ✅ FIXED — `waiting_for_code` কোথাও ডিফাইন করা নেই → `/code` দিলেই বট মরে
`services/pingbot.py:210, 213` — ভ্যারিয়েবলটা কোনো জায়গায় ডিক্লেয়ার করা নেই।

```python
elif text.startswith("/code"):
    waiting_for_code[chat_id] = True   # NameError!
```

`poll_loop`-এর `except Exception` এটা গিলে ফেলে + `time.sleep(3)` → ইউজার
`/code` লিখলে **কোনো রিপ্লাই পায় না**, শুধু লগে "Poll error" আসে।
ফিক্স: মডিউল লেভেলে `waiting_for_code = {}` (বা `set()`)।

### 2. ✅ FIXED — Inline buttons কখনোই দেখাবে না (`reply_markup` dict করে পাঠানো)
`_send()` (line 36-39) `_tg()`-কে dict দেয়, আর `_tg()` `requests.get(params=...)`
ব্যবহার করে। requests nested dict-কে query string-এ সিরিয়ালাইজ করতে পারে না —
আমি টেস্ট করে দেখেছি এটা হয়ে যায়:

```
?chat_id=1&text=hi&reply_markup=inline_keyboard      ← পুরো keyboard হারিয়ে গেছে
```

Telegram এটা reject/ignore করবে। **Logs / Uptime / Restart / Open URL — চারটা
বাটনের একটাও আসবে না।** ফিক্স: `json.dumps(reply_markup)` + `requests.post(json=...)`।

### 3. ✅ FIXED — Multi-line কোডের শুধু প্রথম মেসেজ deploy হতো (5s buffer)
ডিজাইন ছিল: `/code` → 5 সেকেন্ড বাফার → সব মেসেজ জোড়া দিয়ে deploy।
কিন্তু line 213-215:

```python
elif chat_id in waiting_for_code:
    del waiting_for_code[chat_id]   # ← প্রথম মেসেজেই ফ্ল্যাগ মুছে যায়
    collect_code(chat_id, text, first_name)
```

দ্বিতীয় মেসেজ আর `waiting_for_code`-এ নেই → বাফারে যোগ হয় না → নিচের অংশ চুপচাপ
হারিয়ে যায় (বড় কোড Telegram এমনিতেই ৪০৯৬ ক্যারেক্টারে ভাগ করে)। ফিক্স: টাইমার
ফায়ার হওয়ার আগে ফ্ল্যাগ ডিলিট করবেন না — `flush_code()`-এ ডিলিট করুন।

### 4. ✅ FIXED — `/start`-এ literal `\n` প্রিন্ট হতো
`services/pingbot.py:204` — `f"👋 Hi {first_name}!\\n\\nUse /ping or /code"`
ডাবল-এস্কেপড, ইউজার আক্ষরিক `\n\n` দেখবে।

### 5. ✅ FIXED — `/auth/telegram` HMAC verify ক্র্যাশ করত (500)
`routes/auth.py:620-627`:

```python
f"{k}={v}" for k, v in sorted({...}, key=lambda x: x[0]) if v
```

dict-এর উপর iterate করলে **key (string)** আসে, `(k, v)` জোড়া নয় →
`ValueError: too many values to unpack`। আমি রিপ্রোডিউস করেছি। মানে **Telegram
login বাটন কেউ চাপলেই 500 Internal Server Error।** `sorted(d.items())` লাগবে।

আরও তিনটা বাগ একই এন্ডপয়েন্টে:
- `row.get("is_suspended")` (line 638) — SQLite-এ `sqlite3.Row`-এর `.get()` নেই →
  `AttributeError`। বাকি কোডবেস `"x" in row.keys()` প্যাটার্ন ব্যবহার করে (auth.py:275)।
- `auth_date` **expiry চেক নেই** → পুরোনো (leaked) auth payload চিরকাল রিপ্লে করা যায়।
  Telegram নিজেই ≤86400s চেক করতে বলে।
- টোকেন হিসেবে `TELEGRAM_PING_BOT_TOKEN` ব্যবহার হচ্ছে, কিন্তু widget-এর
  `data-telegram-login` = `YOUR_BOT_USERNAME` (index.html:324) — **placeholder,
  রিয়েল username বসানো হয়নি**, তাই widget রেন্ডারই হবে না।

---

## 🛠 কী কী পরিবর্তন হলো (CRITICAL fix summary)

| ফাইল | পরিবর্তন |
|---|---|
| `services/pingbot.py` | `waiting_for_code = {}` মডিউল-লেভেলে যোগ; `_tg()` এখন `requests.post(json=...)`; `_send()` এ `json.dumps(reply_markup)`; ফ্ল্যাগ এখন `flush_code()`-এ ক্লিয়ার হয় (প্রথম chunk-এ নয়); `/code` নতুন করে দিলে পুরোনো বাফার রিসেট; খালি কোডে deploy হয় না; `/start`-এর `\\n` → আসল newline |
| `routes/auth.py` | data-check-string এখন `sorted(fields.items())` (ValueError গেছে); `hmac.compare_digest` (timing-safe); `row.get()` → `row.keys()` probe; `auth_date` expiry (>24h বা >5min future = reject) |
| `app.py` | নতুন `GET /api/public-config` — bot username সার্ভ করে |
| `index.html` | `YOUR_BOT_USERNAME` placeholder সরানো; widget slot এখন hidden, JS দিয়ে ইনজেক্ট হয় |
| `static/pro.js` | `onTelegramAuth()` callback + রানটাইমে widget mount (bot না থাকলে পুরো ব্লক লুকানো) |
| `.env.example`, `render.yaml` | `TELEGRAM_PING_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `PING_*` ডকুমেন্টেড |
| `tests/test_bot_critical.py` | নতুন — ১৯টি regression টেস্ট |

**টেস্ট রেজাল্ট:** `test_bot_critical` 19/19 · `test_all_routes` 65/65 ·
`test_security_batch` 22/22 · `test_web_batch` 24/24 · `test_routing` 47/47 — কোনো regression নেই।

প্রতিটা টেস্ট পুরোনো (buggy) কোডে ফেলে ভেরিফাই করেছি — যেমন পুরোনো auth কোডে
সত্যিই `ValueError: too many values to unpack` উঠেছিল, তাই টেস্টগুলো আসল বাগ ধরে।

### ⚠️ ডিপ্লয় করার আগে যা করতে হবে
Telegram login চালু করতে Render-এ **দুটো** env var লাগবে:
```
TELEGRAM_PING_BOT_TOKEN=<@BotFather token>
TELEGRAM_BOT_USERNAME=<bot এর @username>
```
আর @BotFather-এ `/setdomain` দিয়ে আপনার সাইটের ডোমেইন সেট করতে হবে, নইলে
Telegram widget লোড হবে না। username না দিলে বাটন এমনিতেই hidden থাকবে (ভাঙা দেখাবে না)।

---

## 🟠 HIGH — সিকিউরিটি

### 6. `services/pingbot.py`-এর `/ping`-এ SSRF গার্ড নেই
`bot/app.py`-তে সুন্দর `_ip_blocked` / `_dns_safe` / redirect re-validation আছে।
কিন্তু production-এ চলা `pingbot.py:44-51` একদম কাঁচা:

```python
r = requests.head(target, timeout=8, allow_redirects=True)
```

যে কেউ `/ping http://169.254.169.254/latest/meta-data/` বা `/ping http://127.0.0.1:8000/internal/jobs`
দিতে পারে → **ইন্টারনাল নেটওয়ার্ক স্ক্যান / cloud metadata প্রোব**। অন্তত status
code আর latency লিক হয়। `bot/app.py`-এর `_ping_target()` রিইউজ করাই সবচেয়ে সহজ ফিক্স।

### 7. `/code` — যে কেউ, কোনো auth ছাড়া, আপনার সার্ভারে কোড চালাতে পারে
`deploy_code()` সরাসরি `_runner_http("POST", "/internal/jobs", ...)` কল করে।
কোনো Telegram-user → CodeNest-account ম্যাপিং নেই, `jobs` টেবিলে row-ও লেখা হয় না।
ফলাফল:
- সাইটের সব guardrail বাইপাস: `MAX_JOBS_PER_USER`, device-fingerprint 3-job limit
  (`routes/runspace.py:134-147`), `rate_limit_user` — কিছুই লাগে না।
- ডিপ্লয় করা job ইউজারের ড্যাশবোর্ডে দেখাবে না (DB-তে নেই), তাই manage/delete করা যাবে না —
  runner রিস্টার্ট না হওয়া পর্যন্ত orphan হয়ে বসে থাকবে।
- Telegram bot-এর লিংক যার হাতে পড়বে সে-ই free compute পাবে → abuse/crypto-miner ঝুঁকি।

**সুপারিশ:** `users.telegram_id` কলাম তো আছেই — `/code` চালানোর আগে
`SELECT id FROM users WHERE telegram_id = ?` দিয়ে লিংক করা অ্যাকাউন্ট বাধ্যতামূলক করুন,
আর `/api/jobs`-এর মতো একই লিমিট + `INSERT INTO jobs` করুন।

### 8. খালি `except:` — ৫ জায়গায়
`pingbot.py:32, 146, 156, 166, 176`। `KeyboardInterrupt`/`SystemExit`ও গিলে ফেলে,
আর error লগ না হওয়ায় ডিবাগ অসম্ভব। `except Exception as e:` + `logger` দরকার।

### 9. `print()` ব্যবহার, logger নয়
`pingbot.py:187, 223, 229, 233` — বাকি পুরো কোডবেস `logging` ব্যবহার করে।
Render-এ লেভেল/টাইমস্ট্যাম্প ছাড়া লগ আসে।

---

## 🟡 MEDIUM — লজিক ও UX

### 10. `requirements` payload silently ড্রপ হয়
`pingbot.py:121` `payload["requirements"] = ...` পাঠায়, কিন্তু runner-এর
`JobStartRequest` (runner/app.py:508-514) এ ফিল্ডটাই নেই — Pydantic extra field
চুপচাপ ফেলে দেয়। মানে **`detect_libs()` যা ডিটেক্ট করে তা কখনো install হয় না**;
বট তবুও "Installing: requests" লিখে মিথ্যা বলে। আসল পথ হলো কোডের ভেতর
`# requirements: ...` কমেন্ট (`_parse_requirements`) — তাই detect করা libs
ওভাবে code-এর মাথায় ইনজেক্ট করতে হবে।

### 11. `detect_libs()` `None` ঢোকাতে পারে
```python
return [common.get(i.lower()) for i in imports if i.lower() in common]
```
`if` ফিল্টার আর `common.get` একসাথে থাকায় এখন সেফ, কিন্তু ভঙ্গুর; আর ম্যাপিং মাত্র ৬টা
লাইব্রেরির (`aiohttp`, `telethon`, `bs4`, `numpy`… সবই মিস)।

### 12. Language detection দুর্বল
`"console.log" in code` → JS ধরে নেয়। কিন্তু কোনো Python কোডে
`print("console.log")` থাকলেই ভুল ভাষা। `<html` চেকও একইরকম। AST/heuristic বা
ইউজারকে জিজ্ঞেস করা ভালো।

### 13. Markdown parse error → মেসেজই যাবে না
`_send()` সবসময় `parse_mode: "Markdown"` দেয়। লগে বা কোডে unbalanced `_`, `*`,
`` ` `` থাকলে (যেমন `handle_callback`-এর `📜 Latest Logs` ব্লক, বা exception
স্ট্রিং) Telegram **400 Bad Request** দেয় এবং ইউজার কিছুই পায় না।
`MarkdownV2` + escape, নয়তো লগের জন্য `parse_mode` বাদ দেওয়া উচিত।

### 14. `runner_id`কে সরাসরি `callback_data`-তে রাখা
`get_job_buttons()` → `logs:{runner_id}`। যে কেউ Telegram থেকে যেকোনো
runner job id দিয়ে callback ফোরজ করে **অন্য ইউজারের লগ পড়তে পারে**
(`handle_callback`-এ কোনো ownership চেক নেই)। Telegram callback_data-র লিমিটও
৬৪ বাইট।

### 15. `📥 Download DB` বাটন ডামি
`handle_callback` → `"coming soon..."`। বাটন দেখানোর মানে হয় না, অথবা
`/api/jobs/{id}/files` দিয়ে ইমপ্লিমেন্ট করা দরকার।

### 16. `time.time()` দিয়ে latency মাপা
`handle_ping` `time.time()` ব্যবহার করে; `bot/app.py` ঠিকভাবে `time.perf_counter()`
ব্যবহার করে। NTP অ্যাডজাস্টমেন্টে `time.time()` পিছিয়ে গিয়ে নেগেটিভ ms দিতে পারে।

### 17. `RUNNER_SECRET` ভ্যারিয়েবল অব্যবহৃত (line 16)
`_runner_http` নিজেই env থেকে নেয় — dead code, বিভ্রান্তিকর।

### 18. Job name collision-প্রবণ
`f"tg-{username}-{int(time.time())}"` — একই সেকেন্ডে দুই deploy = একই slug,
`/live/` gateway-তে সংঘর্ষ।

### 19. একাধিক worker = duplicate polling
`app.py` startup-এ thread স্টার্ট করে। Render-এ যদি কখনো gunicorn multi-worker
করা হয়, প্রতি worker আলাদা `getUpdates` করবে → Telegram `409 Conflict` +
ডুপ্লিকেট রিপ্লাই। এখন `uvicorn` single-process বলে বেঁচে গেছে (Dockerfile:77) —
কমেন্টে সতর্কতা রাখা উচিত।

### 20. ডকুমেন্টেশন গ্যাপ
`.env.example`-এ `TELEGRAM_PING_BOT_TOKEN` / `TELEGRAM_BOT_TOKEN` / `PING_DEFAULT_TARGET`
কোনোটাই নেই। `render.yaml` (main service)-এও নেই, যদিও ওখানেই বট চলে।
`bot/README.md` এখনো পুরোনো রেপো নাম `tajhatAti/AhadOrg` বলে।

---

## ✅ যেগুলো ভালো আছে

- `bot/app.py`-এর SSRF ডিফেন্স (DNS resolve + প্রতি redirect hop-এ re-validate) —
  সলিড, এটাই সব জায়গায় রিইউজ করা উচিত।
- `routes/ping.py`-এর `/api/ping` + মিনিমাল UI পরিষ্কার, HEAD→GET fallback সহ।
- Runner-এর in-place restart workspace preserve করে — বট ডেভদের জন্য ঠিক আচরণ।
- `samples/ping_bot.py`-এ হার্ডকোডেড টোকেন নিয়ে সতর্কবার্তা আছে 👍

---

## 🎯 সাজেস্টেড ফিক্স অর্ডার

| ধাপ | কাজ | ফাইল |
|---|---|---|
| 1 | `waiting_for_code = {}` ডিফাইন + buffer লজিক ঠিক | `services/pingbot.py` |
| 2 | `_send()` → `requests.post(json=...)`, keyboard ঠিক | `services/pingbot.py` |
| 3 | `/auth/telegram` HMAC unpack + `row.get` + auth_date expiry | `routes/auth.py` |
| 4 | widget-এ আসল bot username বসানো | `index.html` |
| 5 | `/ping`-এ SSRF গার্ড (bot/app.py থেকে শেয়ার) | `services/pingbot.py` |
| 6 | `/code`-এ telegram_id দিয়ে auth + job limit + DB row | `services/pingbot.py` |
| 7 | `except:` → `except Exception`, `print` → `logger` | `services/pingbot.py` |
| 8 | requirements ইনজেকশন ঠিক করা, বা মিথ্যা মেসেজ সরানো | `services/pingbot.py` |
| 9 | `.env.example` + `render.yaml` + README আপডেট | docs |
