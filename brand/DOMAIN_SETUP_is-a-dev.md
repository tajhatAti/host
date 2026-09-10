# `is-a.dev` ফ্রি ডোমেইন → CodeNest — সম্পূর্ণ গাইড

শেষ আপডেট: 2026-07-27
সোর্স: [docs.is-a.dev/guides/render](https://docs.is-a.dev/guides/render/) · [docs.is-a.dev/faq](https://docs.is-a.dev/faq/) · [Render Custom Domains](https://render.com/docs/custom-domains)

---

## দুই প্রশ্নের সরাসরি উত্তর

### ১. "possible ki?"

**হ্যাঁ। ১০০% possible, সম্পূর্ণ ফ্রি, এবং is-a.dev-এর নিজের ডকুমেন্টেশনেই Render-এর জন্য আলাদা গাইড আছে।**

খরচ ০ টাকা। ক্রেডিট কার্ড লাগবে না। তোমার লাগবে শুধু একটা GitHub অ্যাকাউন্ট (আছেই) আর একটা Pull Request।

তুমি নতুন — সমস্যা নাই। নিচে প্রতিটা ক্লিক লিখে দিয়েছি।

### ২. "next a ahad.is-a.dev/runspace cholbe ki?"

**হ্যাঁ, চলবে। আলাদা করে কিচ্ছু করতে হবে না।**

কারণটা বুঝে নাও, এটা গুরুত্বপূর্ণ — তোমার `app.py`-তে আছে:

```python
CLIENT_ONLY_PATHS = [
    "dashboard", "code", "jobs", "runspace", "admin", "activity",
    "sign-in", "sign-up", "login", "forgot",
]
```

মানে `/runspace` কোনো **আলাদা সার্ভার না** — এটা main site-এরই একটা **path**। ডোমেইন বসালে যা হয়:

| আগে | পরে |
|---|---|
| `ahadorg.onrender.com/` | `ahad.is-a.dev/` |
| `ahadorg.onrender.com/runspace` | `ahad.is-a.dev/runspace` ✅ |
| `ahadorg.onrender.com/dashboard` | `ahad.is-a.dev/dashboard` ✅ |
| `ahadorg.onrender.com/live/mybot/` | `ahad.is-a.dev/live/mybot/` ✅ |
| `ahadorg.onrender.com/runspace/ahad/my-bot` | `ahad.is-a.dev/runspace/ahad/my-bot` ✅ |

**সব path অটোমেটিক কাজ করবে।** ডোমেইন পুরো সার্ভিসটাকেই পয়েন্ট করে, path-by-path করতে হয় না।

### `ahadrunspace.onrender.com`-এর কী হবে?

**ওটাকে ডোমেইন দেওয়ার দরকার নাই। ওটা ইউজার কখনো দেখেই না।**

```
ব্রাউজার  ──→  ahad.is-a.dev  ──(ভিতরে ভিতরে)──→  ahadrunspace.onrender.com
              (ইউজার এটা দেখে)                    (ইউজার এটা দেখে না)
```

Main site সার্ভার-টু-সার্ভার কল করে runner-কে (`RUNNER_SERVICE_URL` দিয়ে)। ব্রাউজার কখনো `ahadrunspace.onrender.com`-এ যায় না। তাই ইউজারের কাছে `onrender.com` কোথাও ফাঁস হবে না।

> ✅ **এক ডোমেইনেই তোমার পুরো কাজ হয়ে যাবে।**

---

## ⚠️ শুরুর আগে: নাম নিয়ে একটা কথা

তুমি `ahad.is-a.dev` চাইছ। কাজ করবে, কিন্তু ভেবে দেখো:

| নাম | কেমন | মন্তব্য |
|---|---|---|
| `ahad.is-a.dev` | ব্যক্তিগত পোর্টফোলিও মনে হয় | "আহাদের সাইট" |
| **`codenest.is-a.dev`** | **প্রোডাক্ট মনে হয়** | ✅ **এটাই নাও** |

চ্যানেলের নাম CodeNest, লোগো CodeNest, কিন্তু লিংক `ahad.is-a.dev` — মানুষ বিভ্রান্ত হবে। আর "প্রোডাক্ট" মনে হলে মানুষ বেশি বিশ্বাস করে, "একজনের পার্সোনাল প্রজেক্ট" মনে হলে কম।

**তবে একটা দারুণ ব্যাপার আছে** — is-a.dev-এ **nested subdomain** allowed। মানে `codenest.is-a.dev` নিলে পরে তুমি ফ্রিতে এগুলোও নিতে পারবে:

```
codenest.is-a.dev            → main site
docs.codenest.is-a.dev       → ডকুমেন্টেশন
status.codenest.is-a.dev     → uptime page
api.codenest.is-a.dev        → API
```

(নিয়ম: nested নিতে হলে parent-টা তোমার মালিকানায় থাকতে হবে।)

নিচের গাইডে আমি `codenest` ব্যবহার করলাম। তুমি `ahad` চাইলে শুধু শব্দটা বদলে দিও — বাকি সব একই।

---

# 🚀 সম্পূর্ণ প্রসেস — ধাপে ধাপে

মোট সময়: তোমার কাজ ~২০ মিনিট, তারপর PR merge হওয়ার অপেক্ষা (কয়েক ঘণ্টা – কয়েক দিন)।

---

## ধাপ ১ — নামটা খালি আছে কিনা দেখো (২ মিনিট)

ব্রাউজারে যাও:

```
https://github.com/is-a-dev/register/blob/main/domains/codenest.json
```

- **404 Not Found** দেখালে → 🎉 নামটা খালি, এগিয়ে যাও
- **ফাইল দেখালে** → নামটা নেওয়া হয়ে গেছে, অন্য নাম ভাবো

ব্যাকআপ নাম আগেই ঠিক করে রাখো: `codenest`, `code-nest`, `codenesthost`, `nestcode`, `ahad`

> 💡 এখানেও চেক করতে পারো: https://data.is-a.dev/ (সব registered subdomain-এর লিস্ট)

---

## ধাপ ২ — Render-এ ডোমেইনটা আগে যোগ করো (৩ মিনিট)

**PR পাঠানোর আগেই এটা করে রাখো** — এতে PR merge হওয়ার সাথে সাথেই সাইট লাইভ হয়ে যাবে, দুইবার অপেক্ষা করতে হবে না।

1. https://dashboard.render.com খোলো
2. **`ahadorg`** সার্ভিসে ক্লিক করো (main site — runner-এ **না**)
3. বাম দিকে **Settings**
4. স্ক্রল করে **Custom Domains** সেকশনে যাও
5. **`+ Add Custom Domain`** চাপো
6. লিখো: `codenest.is-a.dev` → **Save**

Render এখন লাল/হলুদ রঙে দেখাবে *"Certificate pending"* বা *"DNS update needed"* — **এটাই স্বাভাবিক**। DNS এখনো সেট হয়নি।

7. **এখন Render যে DNS instruction দেখাচ্ছে সেটা মন দিয়ে পড়ো।** দুইটার একটা দেখাবে:
   - **CNAME** → `ahadorg.onrender.com` ← সাধারণত subdomain-এর জন্য এটাই
   - **A record** → একটা IP (যেমন `216.24.57.1`)

   **যেটা দেখাচ্ছে সেটা লিখে রাখো।** পরের ধাপে লাগবে।

> ⚠️ `www.codenest.is-a.dev` যোগ কোরো না — অপ্রয়োজনীয়, আর is-a.dev-এ ঝামেলা করে।

---

## ধাপ ৩ — is-a.dev রিপো ফর্ক করো (২ মিনিট)

1. যাও: **https://github.com/is-a-dev/register**
2. উপরে ডানদিকে **Fork** বাটন → **Create fork**
3. এখন তোমার নিজের কপি: `https://github.com/তোমার-username/register`

---

## ধাপ ৪ — JSON ফাইল বানাও (৫ মিনিট)

তোমার fork-এ থাকা অবস্থায়:

1. **`domains`** ফোল্ডারে ঢোকো
2. উপরে ডানদিকে **`Add file`** → **`Create new file`**
3. ফাইলের নাম দাও (হুবহু, ছোট হাতের অক্ষরে):

```
codenest.json
```

> ⚠️ পুরো path যেন হয় `domains/codenest.json`
> ⚠️ ফাইলের নামে `is-a.dev` লিখবে না — শুধু `codenest.json`
> ⚠️ শুধু ছোট হাতের অক্ষর, সংখ্যা আর ড্যাশ

4. ভিতরে এই কনটেন্ট বসাও:

### 🅰️ যদি Render **CNAME** দেখিয়ে থাকে (সবচেয়ে সম্ভাবনাময়):

```json
{
    "owner": {
        "username": "তোমার-github-username",
        "email": "তোমার@ইমেইল.com"
    },
    "records": {
        "CNAME": "ahadorg.onrender.com"
    }
}
```

### 🅱️ যদি Render **A record + IP** দেখিয়ে থাকে:

```json
{
    "owner": {
        "username": "তোমার-github-username",
        "email": "তোমার@ইমেইল.com"
    },
    "records": {
        "A": ["216.24.57.1"]
    }
}
```

> ⚠️ `216.24.57.1` হলো is-a.dev-এর ডকে লেখা Render-এর IP। **কিন্তু Render তোমার ড্যাশবোর্ডে যেটা দেখাচ্ছে সেটাই ব্যবহার করো** — IP বদলাতে পারে।

**কোনটা ভালো?** CNAME। কারণ Render IP বদলালে CNAME নিজে নিজে ঠিক থাকে, A record ভেঙে যায়।

5. **কমা, ব্র্যাকেট ঠিক আছে কিনা যাচাই করো** — এখানে পেস্ট করে: https://jsonlint.com
   (একটা কমা ভুল হলেই PR reject হবে)

6. নিচে স্ক্রল → **Commit changes**
   - Commit message: `Register codenest.is-a.dev`
   - **Commit directly to the main branch** সিলেক্ট করো
   - **Commit changes** চাপো

---

## ধাপ ৫ — Pull Request পাঠাও (৫ মিনিট)

1. Commit করার পর GitHub উপরে একটা হলুদ ব্যানার দেখাবে: **`Compare & pull request`** → চাপো
   (না দেখালে: তোমার fork → **Pull requests** ট্যাব → **New pull request**)

2. খেয়াল করো তীরের দিক ঠিক আছে কিনা:
   ```
   base: is-a-dev/register  main   ←  head: তোমার-username/register  main
   ```

3. **Title:**
   ```
   Register codenest.is-a.dev
   ```

4. **Description** — এটাই সবচেয়ে গুরুত্বপূর্ণ অংশ। মেইনটেইনাররা ভলান্টিয়ার, দিনে শত শত PR দেখে। ভালো description দিলে দ্রুত merge হয়, খারাপ দিলে ফেলে রাখে।

   is-a.dev-এর ToS বলে **"root subdomain অবশ্যই software development সম্পর্কিত হতে হবে"** — তোমার প্রজেক্ট একদম পারফেক্ট ফিট, সেটা স্পষ্ট করে লেখো:

```markdown
## What is this?

CodeNest is a free hosting platform for Telegram bots — users paste their
Python / Node.js code in a browser editor and the bot runs 24/7 with live
logs, environment variables and auto-restart on crash.

It is aimed at beginner developers (mostly in Bangladesh) who can't afford
a VPS or a credit card for Heroku.

## Hosting

Deployed on Render — `ahadorg.onrender.com`

## Preview

<!-- এখানে স্ক্রিনশট drag-and-drop করো -->

## Checklist

- [x] Software development related
- [x] Not a redirect / parked page
- [x] JSON validated
- [x] Domain already added in the Render dashboard
```

5. **স্ক্রিনশট অবশ্যই দাও।** is-a.dev-এর Render গাইডে সরাসরি লেখা আছে:

   > *"Don't forget to provide a preview of your website in your pull request."*

   তোমার সাইটের homepage-এর একটা স্ক্রিনশট নাও, description বক্সে drag-and-drop করে ছেড়ে দাও।

6. যদি PR template-এ চেকবক্স থাকে — **সবগুলো পড়ে টিক দাও**।

7. **Create pull request** চাপো ✅

---

## ধাপ ৬ — অপেক্ষা করো (কয়েক ঘণ্টা – কয়েক দিন)

is-a.dev-এর FAQ থেকে হুবহু:

> *"We're a team of volunteers, and is-a.dev is a side project for us, so review times can vary."*

**দ্রুত করানোর একমাত্র বৈধ উপায়:**

- is-a.dev Discord-এ join করো: https://discord.gg/is-a-dev-830872854677422150
- `#pull-requests` চ্যানেলে তোমার PR-এর লিংক একবার পোস্ট করো

**🚫 যা একদম করবে না:**

> FAQ: *"Why does my PR have the 'low priority' label? — This is because you have mentioned or messaged maintainers to get your PR approved."*

মেইনটেইনারদের `@mention` করা বা DM করা = **PR-এ "low priority" লেবেল** = আরো দেরি। ধৈর্য ধরো।

মেইনটেইনার কিছু চেঞ্জ চাইলে — PR-এ কমেন্ট আসবে, ফাইলটা এডিট করে আবার commit করো, PR নিজে নিজে আপডেট হবে।

---

## ধাপ ৭ — Merge হওয়ার পর: DNS ছড়াতে দাও (১০ মিনিট – ২ ঘণ্টা)

PR merge হয়ে গেলে চেক করো:

```bash
nslookup codenest.is-a.dev
```

অথবা ওয়েবসাইটে: https://dnschecker.org → `codenest.is-a.dev` লিখো

Render-এর IP বা `ahadorg.onrender.com` দেখালে → DNS রেডি ✅

তারপর Render Dashboard → `ahadorg` → **Settings → Custom Domains**:
- সবুজ **"Certificate Issued"** দেখাবে → **হয়ে গেছে!**
- এখনো লাল? → **`Verify`** বাটন চাপো, ৫ মিনিট পর আবার

Render নিজেই ফ্রি SSL সার্টিফিকেট বসিয়ে দেবে, নিজেই রিনিউ করবে। তোমার কিছুই করতে হবে না।

**এখন খুলে দেখো:**
```
https://codenest.is-a.dev
https://codenest.is-a.dev/runspace     ← তোমার প্রশ্নের উত্তর, চলবে ✅
https://codenest.is-a.dev/dashboard
```

---

## ধাপ ৮ — ⚠️ কোড/সেটিংস আপডেট (এটা ভুলে গেলে জিনিস ভাঙবে)

**সাইট খুললেই কাজ শেষ না।** এই তিনটা না করলে কিছু ফিচার নীরবে ভেঙে থাকবে।

### 8a. Render env vars

**Main service (`ahadorg`)** → Environment:
```
SITE_BASE_URL   = https://codenest.is-a.dev
PUBLIC_BASE_URL = https://codenest.is-a.dev
```

**Runner service (`ahadrunspace`)** → Environment:
```
SITE_BASE_URL   = https://codenest.is-a.dev
PUBLIC_BASE_URL = https://ahadrunspace.onrender.com   ← এটা বদলাবে না!
```

> `PUBLIC_BASE_URL` runner-এ থাকে `/live/{slug}/` gateway-এর URL বানানোর জন্য (`runner/app.py:528`)। ওটা runner-এর নিজের host-ই থাকবে।

দুটো সার্ভিসেই **Manual Deploy → Deploy latest commit**।

### 8b. 🔴 Telegram Login Widget (সবচেয়ে সহজে ভুলে যাওয়া জিনিস)

Telegram-এর login widget **ডোমেইন-লকড**। ডোমেইন বদলালে লগইন বাটন কাজ করা বন্ধ করে দেবে — কোনো error দেখাবে না, শুধু চুপচাপ fail করবে।

Telegram-এ **@BotFather** খোলো:

```
/setdomain
→ তোমার bot সিলেক্ট করো
→ codenest.is-a.dev
```

তোমার auth পুরোটাই `TELEGRAM_ONLY_AUTH=1` মোডে চলছে — **এটা না করলে কেউ লগইনই করতে পারবে না।**

### 8c. পুরনো লিংক

`ahadorg.onrender.com` **কাজ করতেই থাকবে** — Render দুটোই serve করে। পুরনো লিংক ভাঙবে না।

চাইলে পরে পুরনো ডোমেইনকে নতুনটায় redirect করাতে পারি (কোডে কয়েক লাইন)। এখন দরকার নাই।

---

## ✅ চেকলিস্ট (প্রিন্ট করে রাখার মতো)

```
[ ] ১. github.com/is-a-dev/register/blob/main/domains/codenest.json → 404?
[ ] ২. Render → ahadorg → Settings → Custom Domains → codenest.is-a.dev যোগ
[ ] ৩. Render যে CNAME/A দেখাচ্ছে সেটা লিখে রাখলাম: ____________________
[ ] ৪. github.com/is-a-dev/register → Fork
[ ] ৫. domains/codenest.json বানালাম
[ ] ৬. jsonlint.com-এ JSON চেক করলাম
[ ] ৭. স্ক্রিনশট সহ PR পাঠালাম
[ ] ৮. is-a.dev Discord #pull-requests-এ লিংক দিলাম (mention ছাড়া)
[ ] ৯. Merge হলো
[ ] ১০. dnschecker.org-এ DNS দেখা যাচ্ছে
[ ] ১১. Render-এ সবুজ "Certificate Issued"
[ ] ১২. SITE_BASE_URL / PUBLIC_BASE_URL আপডেট → দুই সার্ভিস redeploy
[ ] ১৩. @BotFather → /setdomain → codenest.is-a.dev   ⚠️ ভুলবে না
[ ] ১৪. লগইন টেস্ট করলাম, /runspace টেস্ট করলাম
```

---

## 🔴 "We weren't able to verify codenest.is-a.dev" — এর মানে কী

Render এই মেসেজ দিলে **তুমি ঠিক পথেই আছ**। এটা ভুল না — এটা ধাপ ২-এর স্বাভাবিক অবস্থা।

### আমি চেক করে দেখেছি — সমস্যাটা কী

`codenest.is-a.dev`-এর DNS জিজ্ঞেস করলাম (Google DNS, 2026-07-27):

```
codenest.is-a.dev        A → 104.18.5.103, 104.18.4.103
```

দেখে মনে হতে পারে "আরে, DNS তো কাজ করছে!" — **কিন্তু না।** আমি একটা সম্পূর্ণ বানানো নাম দিয়েও চেক করেছি:

```
zzzq9-nonexistent-xyz123.is-a.dev   A → 104.18.5.103, 104.18.4.103   ← হুবহু একই!
```

**একই IP।** মানে ওগুলো তোমার রেকর্ড না — ওগুলো is-a.dev-এর **wildcard catch-all** (Cloudflare-এর IP), যেটা প্রতিটা অ-নিবন্ধিত নামের জন্য রিটার্ন হয়।

### 🎯 আসল কারণ

> **তোমার Pull Request এখনো merge হয়নি।**

`codenest.is-a.dev` এখনো তোমার নয়। DNS-এ তোমার কোনো রেকর্ড **নেই**। Render `ahadorg.onrender.com` বা `216.24.57.1` খুঁজছে, পাচ্ছে Cloudflare-এর wildcard IP — তাই verify fail করছে।

**এটা তোমার ভুল না। Render-এর ভুলও না। শুধু PR-টা merge হওয়া বাকি।**

### কোন অবস্থায় আছ তা নিজে চেক করো

ব্রাউজারে খোলো:

```
https://github.com/is-a-dev/register/blob/main/domains/codenest.json
```

| যা দেখছ | মানে | করণীয় |
|---|---|---|
| **404 Not Found** | PR merge হয়নি (বা পাঠাওইনি) | নিচে দেখো ↓ |
| **তোমার JSON ফাইল** | merge হয়ে গেছে ✅ | DNS ছড়াতে ১০ মিনিট – ২ ঘণ্টা দাও, তারপর Render-এ `Verify` |

### 404 দেখালে

**PR পাঠাওনি?** → এই ডকের **ধাপ ৩ থেকে ধাপ ৫** করো।

**PR পাঠিয়েছ কিন্তু এখনো merge হয়নি?** → তোমার কিছুই করার নাই, অপেক্ষা ছাড়া। is-a.dev-এর FAQ:

> *"We're a team of volunteers, and is-a.dev is a side project for us, so review times can vary."*

কয়েক ঘণ্টা থেকে কয়েক দিন লাগতে পারে। এর মধ্যে:

- ✅ Render-এ ডোমেইনটা যোগ করাই থাক — **সরিয়ে ফেলবে না**। merge হওয়ার সাথে সাথে Render নিজেই ধরে ফেলবে।
- ✅ is-a.dev Discord-এর `#pull-requests`-এ PR লিংক একবার পোস্ট করো
- ❌ মেইনটেইনারদের mention/DM কোরো না → **"low priority" লেবেল পড়বে, আরো দেরি হবে**
- ❌ Render-এ বারবার `Verify` চেপে লাভ নাই — DNS না থাকলে কিছুই হবে না

### PR-এ কোন রেকর্ডটা দেবে

Render তোমাকে **দুটো অপশনই** দিয়েছে। যেকোনো একটা কাজ করবে:

**অপশন A — CNAME (আমার সুপারিশ):**
```json
{
    "owner": {
        "username": "তোমার-github-username",
        "email": "তোমার@ইমেইল.com"
    },
    "records": {
        "CNAME": "ahadorg.onrender.com"
    }
}
```

**অপশন B — A record (is-a.dev-এর অফিশিয়াল Render গাইডে এটাই আছে):**
```json
{
    "owner": {
        "username": "তোমার-github-username",
        "email": "তোমার@ইমেইল.com"
    },
    "records": {
        "A": ["216.24.57.1"]
    }
}
```

**CNAME কেন ভালো:** Render ভবিষ্যতে IP বদলালে CNAME নিজে নিজে ঠিক থাকে, A record চুপচাপ ভেঙে যায়।

**A কেন ভালো:** is-a.dev-এর নিজের Render গাইডে এটাই লেখা, মেইনটেইনাররা এটা দেখে অভ্যস্ত — প্রশ্ন কম করবে।

> ⚠️ **দুটো একসাথে দেবে না।** FAQ-তে স্পষ্ট: *"A CNAME cannot be combined with other record types."* একটাই বেছে নাও।
>
> ⚠️ **`"proxied": true` লিখবে না।** Render-এর নিজের ডকে লেখা আছে DNS **"DNY only"** থাকতে হবে, নইলে সার্টিফিকেট ইস্যু হবে না। is-a.dev-এ ডিফল্টই `false` — তাই কিছু লেখার দরকার নেই।
>
> ⚠️ **AAAA রেকর্ড দেবে না।** Render IPv6 সাপোর্ট করে না, AAAA থাকলে ডোমেইন ভেঙে যায়।

### Merge হওয়ার পর কীভাবে বুঝবে

এই ওয়েবসাইটে চেক করো: **https://dnschecker.org** → `codenest.is-a.dev`

| দেখছ | মানে |
|---|---|
| `104.18.x.x` (Cloudflare) | ❌ এখনো wildcard — merge হয়নি |
| `216.24.57.1` অথবা `ahadorg.onrender.com` | ✅ তোমার রেকর্ড লাইভ — Render-এ `Verify` চাপো |

---

## 🔧 সমস্যা হলে

| যা দেখছ | কারণ | সমাধান |
|---|---|---|
| **"We weren't able to verify..."** | **PR এখনো merge হয়নি** | উপরের 🔴 সেকশন দেখো |
| is-a.dev-এর homepage-এ চলে যাচ্ছে | ব্রাউজার ক্যাশ (FAQ-তে লেখা #১ সমস্যা) | ক্যাশ ক্লিয়ার / incognito-তে খোলো |
| `DNS_PROBE_FINISHED_NXDOMAIN` | DNS এখনো ছড়ায়নি | ১-২ ঘণ্টা অপেক্ষা |
| Render-এ "Certificate pending" আটকে আছে | Verify চালানো হয়নি | Render-এ `Verify` চাপো, ১০ মিনিট পর আবার |
| SSL warning | সার্টিফিকেট এখনো ইস্যু হয়নি | ৩০ মিনিট অপেক্ষা, Render নিজেই করবে |
| সাইট খোলে কিন্তু **Telegram লগইন কাজ করে না** | **ধাপ 8b করোনি** | @BotFather → `/setdomain` |
| `/runspace` খালি সাদা পাতা | পুরনো JS ক্যাশ | Hard refresh (Ctrl+Shift+R) |
| job চলছে কিন্তু log আসছে না | runner-এর env আপডেট হয়নি | `ahadrunspace` redeploy |
| PR-এ "low priority" লেবেল | মেইনটেইনারকে mention করেছ | আর কিছু কোরো না, অপেক্ষা করো |
| PR reject | JSON ভুল বা description দুর্বল | কমেন্ট পড়ো, ফাইল ঠিক করে আবার commit |

---

## ❓ তোমার মনে যে প্রশ্নগুলো আসতে পারে

**প্রঃ ডোমেইনটা কি সত্যিই ফ্রি? পরে টাকা চাইবে না তো?**
না। is-a.dev ভলান্টিয়ারদের চালানো ওপেন সোর্স প্রজেক্ট। কোনো টাকা নেই, কোনো বিজ্ঞাপন নেই। Render-এর custom domain-ও ফ্রি প্ল্যানে ফ্রি (২টা পর্যন্ত)।

**প্রঃ তারা কি ডোমেইনটা কেড়ে নিতে পারে?**
ToS ভাঙলে পারে (ম্যালওয়্যার, phishing, স্প্যাম, বা সাইট মরে পড়ে থাকলে)। স্বাভাবিক ব্যবহারে কোনো সমস্যা নেই। এটাই একমাত্র ঝুঁকি — আর এই কারণেই ভবিষ্যতে $২ দিয়ে `codenest.xyz` কিনে রাখলে ভালো, backup হিসেবে।

**প্রঃ `.is-a.dev` কি দেখতে অপেশাদার লাগে?**
ডেভেলপারদের কাছে **না** — বরং উল্টো। `is-a.dev` Public Suffix List-এ আছে, ডেভ কমিউনিটিতে পরিচিত ও সম্মানিত। আর তোমার টার্গেট ইউজারই তো ডেভেলপার। `onrender.com`-এর চেয়ে ১০০ গুণ ভালো।

**প্রঃ পরে নিজের `.com` কিনলে?**
কোনো সমস্যা নাই। Render-এ ২টা custom domain একসাথে রাখা যায়। দুটোই একসাথে চলবে, তারপর ধীরে ধীরে migrate করবে।

**প্রঃ ইমেইল পাবো? `hello@codenest.is-a.dev`?**
হ্যাঁ, MX record support করে। is-a.dev-এর ডকে ImprovMX আর Zoho Mail-এর গাইড আছে। তবে একটা শর্ত (FAQ): **CNAME আর MX একসাথে রাখা যায় না**, যদি না domain "proxied" হয়। ইমেইল লাগলে A record ব্যবহার করতে হবে, CNAME না। এখন দরকার নাই — পরে লাগলে বোলো।

**প্রঃ পরে `runspace.codenest.is-a.dev` বানানো যাবে?**
হ্যাঁ, nested subdomain allowed — parent তোমার হলে। শুধু আরেকটা PR (`domains/runspace.codenest.json`)। **কিন্তু দরকার নাই** — `codenest.is-a.dev/runspace` এমনিতেই কাজ করছে, আর SPA-র জন্য সেটাই সঠিক পদ্ধতি।
