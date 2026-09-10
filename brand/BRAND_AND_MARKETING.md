# CodeNest — Brand + Telegram Channel Marketing Playbook

শেষ আপডেট: 2026-07-27

---

## 0. আগে সত্যি কথাটা

তুমি ঠিকই ধরেছ — **"৫-৬ টা পয়েন্ট" লিখে দিলে কেউ পড়বে না।** তুমি নিজেও পড়ো না, আমিও না।
লোকে চ্যানেলে ঢুকে **৩ সেকেন্ড** দেয়। ওই ৩ সেকেন্ডে তিনটা প্রশ্নের উত্তর পেতে হবে:

1. এটা কী? (এক লাইনে)
2. এটা আমার কী কাজে লাগবে? (আমার bot চলবে ফ্রিতে)
3. এখন কী করব? (একটা বাটন / একটা লিংক)

বাকি সব — features list, "we provide", "our mission" — **ডিলিট**। ওগুলো কেউ পড়ে না।

এই ডকুমেন্টে সব কপি-পেস্ট রেডি করে দিলাম। তোমার শুধু paste করা লাগবে।

---

## 1. Brand Identity

### লোগো

| ফাইল | কোথায় ব্যবহার |
|---|---|
| `brand/mark-dark-512.png` | Telegram channel avatar, bot avatar |
| `brand/mark-light-512.png` | সাদা ব্যাকগ্রাউন্ডে (docs, invoice) |
| `brand/mark-transparent-512.png` | যেকোনো ব্যাকগ্রাউন্ডে overlay |
| `brand/mark-dark-64.png` / `-32.png` | favicon |
| `brand/codenest-mark.svg` | vector — যেকোনো সাইজে, ওয়েবসাইটে inline |
| `brand/codenest-lockup.svg` | icon + "CodeNest" wordmark, header/banner-এ |
| `brand/tg-avatar-dark.png` | Telegram avatar (wordmark সহ ভার্সন) |
| `brand/post-template-1.png` | পোস্ট টেমপ্লেট — headline স্টাইল |
| `brand/post-template-2.png` | পোস্ট টেমপ্লেট — terminal স্টাইল |

লোগোটা ইচ্ছাকৃতভাবে `</>` — কারণ:
- Telegram-এ ৩২px avatar-এও পড়া যায় (কোনো detail নেই বলে ছোট হলে নষ্ট হয় না)
- যেকোনো ডেভেলপার ০.৩ সেকেন্ডে বোঝে "এটা কোড রিলেটেড"
- কপি করা যায় না এমন কিছু না — কিন্তু consistent থাকলে ওটাই brand হয়ে যায়

### Colour (মাত্র ৫টা — এর বাইরে কিছু ব্যবহার করবে না)

```
Accent / Primary   #5B6CFF   (indigo — বাটন, লিংক, লোগো)
Background dark    #0E1116   (চ্যানেল ব্যানার, পোস্ট গ্রাফিক)
Surface            #14181F   (কার্ড, terminal box)
Text muted         #9AA3B2   (সাব-টেক্সট)
Success            #3FB950   (LIVE / online badge)
```

### Font style

তোমার প্রশ্ন ছিল "Font Style Need"। Telegram-এ custom font বসানো যায় না, কিন্তু **Unicode font trick** কাজ করে। তবে সাবধান:

> ⚠️ **Unicode fancy font চ্যানেলের নামে ব্যবহার কোরো না।** কারণ:
> - Telegram search-এ তোমার চ্যানেল খুঁজে পাওয়া যাবে না (`𝗖𝗼𝗱𝗲𝗡𝗲𝘀𝘁` লিখে কেউ সার্চ করে না)
> - স্ক্রিন রিডারে "mathematical bold capital C" পড়ে
> - অনেক Android device-এ □□□ box দেখায়
>
> Fancy font শুধু **পোস্টের ভিতরে একটা-দুইটা হাইলাইট শব্দে** ব্যবহার করো, নামে না।

**চ্যানেলের নাম (এটাই ব্যবহার করো):**

```
CodeNest
```

শুধু এটুকু। description-এ বাকিটা।

চাইলে এই ভ্যারিয়েন্টগুলো আছে (৫টার বেশি চেয়েছিলে):

| # | স্টাইল | দেখতে | সুপারিশ |
|---|---|---|---|
| 1 | Plain (সেরা) | `CodeNest` | ✅ **এটাই নাও** |
| 2 | Emoji prefix | `</> CodeNest` | ✅ ভালো — searchable থাকে |
| 3 | Tagline সহ | `CodeNest — Free Bot Hosting` | ✅ ভালো — SEO-তে সাহায্য করে |
| 4 | Sans Bold | `𝗖𝗼𝗱𝗲𝗡𝗲𝘀𝘁` | ⚠️ শুধু পোস্টে |
| 5 | Monospace | `𝙲𝚘𝚍𝚎𝙽𝚎𝚜𝚝` | ⚠️ শুধু পোস্টে |
| 6 | Small caps | `ᴄᴏᴅᴇɴᴇsᴛ` | ⚠️ শুধু পোস্টে |
| 7 | Bold Italic | `𝘾𝙤𝙙𝙚𝙉𝙚𝙨𝙩` | ❌ পুরনো লাগে |
| 8 | Double-struck | `ℂ𝕠𝕕𝕖ℕ𝕖𝕤𝕥` | ❌ অপেশাদার |

**আমার চূড়ান্ত সুপারিশ:**

- **Channel name:** `CodeNest`
- **Username:** `@codenest_bd` অথবা `@CodeNestHost` (যেটা খালি পাও)
- **Discussion group:** `CodeNest Chat`
- **Bot:** `@CodeNestBot`

তিনটার avatar একই `mark-dark-512.png` — এটাই brand consistency। মানুষ ৩ জায়গায় একই আইকন দেখলে মনে রাখে।

---

## 2. Channel Description (কপি-পেস্ট)

Telegram description limit ২৫৫ ক্যারেক্টার। এটা তোমার **বিজ্ঞাপন**, features list না:

```
Telegram bot বানিয়েছ, কিন্তু PC বন্ধ করলেই bot অফ?

CodeNest-এ কোড আপলোড করো — bot ২৪/৭ চলবে। ফ্রি। কার্ড লাগবে না।

Python · Node.js · Live logs · Web editor

▸ শুরু করো: [তোমার লিংক]
```

লক্ষ্য করো — শুরুই হয়েছে **ব্যথা দিয়ে** ("PC বন্ধ করলেই bot অফ"), feature দিয়ে না। এটাই পুরো marketing-এর মূল কথা।

---

## 3. Pinned Post (সবচেয়ে গুরুত্বপূর্ণ পোস্ট)

চ্যানেলে ঢুকে মানুষ প্রথম যেটা দেখবে। এটা লম্বা হতে পারে, কিন্তু **scannable** হতে হবে।

> `post-template-2.png` ছবিটা এর সাথে attach করো।

```
</> CodeNest — তোমার bot কখনো ঘুমাবে না

━━━━━━━━━━━━━━━━━━

সমস্যাটা চেনা:

তুমি রাত ৩টা পর্যন্ত বসে bot বানালে। চলল। 
ল্যাপটপ বন্ধ করলে — bot মরে গেল।

Heroku টাকা চায়। Render ১৫ মিনিটে ঘুমিয়ে যায়। 
VPS-এর জন্য কার্ড নাই।

━━━━━━━━━━━━━━━━━━

সমাধান:

1️⃣  সাইন আপ করো (Telegram দিয়ে, ১০ সেকেন্ড)
2️⃣  কোড paste করো বা file আপলোড করো
3️⃣  Run চাপো

ব্যস। bot লাইভ। তুমি ফোন বন্ধ করে ঘুমাতে যাও।

━━━━━━━━━━━━━━━━━━

কী কী আছে:

⚡  ২৪/৭ চলে — sleep নাই
🐍  Python + Node.js
📟  Live log — কী হচ্ছে চোখের সামনে দেখো
✏️  ব্রাউজারেই এডিটর, ফোন থেকেও চলে
🔑  Env variable (BOT_TOKEN নিরাপদে রাখো)
🔄  Crash করলে নিজেই restart

━━━━━━━━━━━━━━━━━━

খরচ: ০ টাকা। কার্ড লাগবে না। Trial না।

▸  এখনই শুরু করো: [লিংক]
▸  আটকে গেলে: @CodeNestChat
```

---

## 4. তোমার আসল প্রশ্ন: `ahadorg.onrender.com` লিংকটা লুকানো যায়?

**হ্যাঁ, যায়। এবং অবশ্যই করা উচিত।** তুমি ঠিক ধরেছ — চালাক লোক `onrender.com` দেখলেই বুঝে ফেলে এটা free tier-এ চলছে, আর তখন "এটা কি কাল বন্ধ হয়ে যাবে?" ভাবে। Trust কমে যায়।

### সমাধান: Custom domain

Render-এর **free plan-এও custom domain কাজ করে**, SSL সহ, ফ্রিতে। ২টা domain পর্যন্ত।

তোমার লাগবে শুধু একটা domain name। অপশন:

| অপশন | খরচ | মন্তব্য |
|---|---|---|
| `.xyz` / `.site` / `.online` (Namecheap/Porkbun) | ~$১-৩/বছর প্রথম বছর | 💰 সবচেয়ে সস্তা, ভালো দেখায় |
| `.dev` / `.app` (Porkbun/Cloudflare) | ~$১২/বছর | Google-owned, HTTPS forced, ডেভেলপারদের কাছে trustworthy |
| `.com` | ~$১০/বছর | সবচেয়ে বিশ্বাসযোগ্য |
| **`is-a.dev`** (GitHub PR দিয়ে) | **ফ্রি** | `codenest.is-a.dev` — ডেভ কমিউনিটিতে respected |
| **`js.org`** | **ফ্রি** | `codenest.js.org` — JS প্রজেক্টের জন্য |
| **`eu.org`** | **ফ্রি** | `codenest.eu.org` |

**আমার সুপারিশ:** `codenest.xyz` অথবা `codenest.dev` কিনে ফেলো। বছরে ১-২ ডলার। এটা তোমার সবচেয়ে বড় credibility upgrade — কোড লেখার চেয়েও বেশি।

টাকা একদমই না দিতে চাইলে → **`is-a.dev`** নাও (GitHub-এ একটা PR, ফ্রি, forever)।

### Render-এ কীভাবে সেট করবে

```
1. Render Dashboard → ahadorg service → Settings → Custom Domains
2. "Add Custom Domain" → codenest.xyz  এবং  www.codenest.xyz
3. Render তোমাকে DNS record দেবে
4. Domain registrar-এ (Namecheap/Porkbun/Cloudflare) গিয়ে বসাও:

   Type    Name    Value
   ─────────────────────────────────────────
   A       @       216.24.57.1          ← Render যেটা দেবে সেটাই
   CNAME   www     ahadorg.onrender.com

5. ১০-৩০ মিনিট অপেক্ষা → Render নিজেই SSL সার্টিফিকেট বসাবে
6. তোমার সাইট এখন  https://codenest.xyz
```

**Runner service (`ahadrunspace`) কে domain দেওয়ার দরকার নাই** — ওটা ইউজার কখনো দেখে না, main site ভিতরে ভিতরে কল করে।

### Domain কেনার পর কোডে যা বদলাবে

Render Dashboard → main service → Environment:
```
PUBLIC_BASE_URL = https://codenest.xyz
SITE_BASE_URL   = https://codenest.xyz
```
Runner service-এ:
```
SITE_BASE_URL   = https://codenest.xyz
```
তারপর দুটোই redeploy। বলো, আমি `render.yaml`-এর পুরনো `ahad-code-runner` reference গুলোও ঠিক করে দেব।

### Domain কেনার আগ পর্যন্ত: লিংক ঢেকে রাখো

এখনই যা করতে পারো — bio/পোস্টে কাঁচা URL না দিয়ে:

- Telegram-এ **hyperlink** ব্যবহার করো: `[এখানে শুরু করো](https://ahadorg.onrender.com)` → ইউজার শুধু "এখানে শুরু করো" দেখবে
- অথবা bot-কে entry point বানাও: bio-তে `@CodeNestBot` → bot একটা বাটন দেবে → ওখান থেকে সাইটে
- `t.me/codenest_bd` লিংক শেয়ার করো, সাইটের লিংক না

**bot-কে গেটওয়ে বানানোটাই আসলে সবচেয়ে ভালো** — এতে URL-ও লুকায়, আর প্রত্যেক ভিজিটর bot-এ subscribe হয়ে যায় (পরে notification পাঠাতে পারবে)। এটা free hosting-এর সবচেয়ে বড় growth hack।

---

## 5. মেম্বার কোথা থেকে আসবে (আসল কথা)

চ্যানেল সুন্দর করলেই মেম্বার আসে না। **মেম্বার আসে ওখান থেকে যেখানে লোকজন এই সমস্যায় ভুগছে।** তোমার টার্গেট খুব নির্দিষ্ট: *যারা Telegram bot বানায় কিন্তু হোস্ট করতে পারে না।* এরা কোথায় থাকে জানা আছে।

### Tier 1 — এখানেই তোমার লোক (সপ্তাহে ২-৩ ঘণ্টা দাও)

**Telegram groups:**
- Bangla programming/bot groups (BD Python, BD Developers, Telegram Bot Bangladesh)
- `@BotTalk`, pyTelegramBotAPI / aiogram / Telethon সাপোর্ট গ্রুপ
- BD freelancing গ্রুপ

**কীভাবে:** স্প্যাম করবে না। গ্রুপে বসে থাকো। কেউ যখনই জিজ্ঞেস করে *"ভাই bot টা ২৪ ঘণ্টা কিভাবে চালাব?"* — **আসলেই তার সমস্যাটার সমাধান দাও**, তারপর শেষে এক লাইন:

> "আমি নিজেই এইটার জন্য একটা free hosting বানিয়েছি — codenest.xyz. Telegram bot-এর জন্যই বানানো। চাইলে ট্রাই করো।"

এইভাবে দিনে ২-৩ জন। মাসে ৬০-৯০ জন **টার্গেটেড** মেম্বার। ১০০০ random মেম্বারের চেয়ে ভালো।

**এই একটা প্রশ্নই তোমার সোনার খনি।** Telegram-এ প্রতিদিন কয়েকশ বার জিজ্ঞেস করা হয়।

### Tier 2 — Reddit / Stack Overflow (SEO, দীর্ঘমেয়াদি)

- r/TelegramBots, r/learnpython, r/SideProject, r/selfhosted
- "Where to host telegram bot for free" — এই প্রশ্নের পুরনো থ্রেডগুলো Google-এ র‍্যাঙ্ক করে। কমেন্ট করো।
- Stack Overflow-এ একই প্রশ্নে answer দাও

এগুলো একবার লিখলে **বছরের পর বছর** ট্রাফিক দেয়।

### Tier 3 — YouTube (সবচেয়ে বেশি রিটার্ন, সবচেয়ে বেশি খাটনি)

একটা ৩-৫ মিনিটের বাংলা স্ক্রিন রেকর্ডিং:

> **"ফ্রিতে Telegram Bot ২৪ ঘণ্টা চালান | কোনো VPS বা কার্ড ছাড়াই"**

স্ক্রিপ্ট: bot বানানো (৩০s) → local-এ চালানো (২০s) → ল্যাপটপ বন্ধ, bot মরল (১৫s) → CodeNest-এ আপলোড (৬০s) → ল্যাপটপ বন্ধ, bot **এখনো চলছে** (২০s) → CTA (১৫s)

ওই "ল্যাপটপ বন্ধ করলাম কিন্তু bot চলছে" মুহূর্তটাই পুরো ভিডিওর point. Description-এ চ্যানেল লিংক।

বাংলায় এই কনটেন্ট প্রায় নাই। একটা ভিডিও ৬ মাস ধরে মেম্বার দেবে।

### Tier 4 — GitHub

- রিপো public করো, ভালো README (উপরের লোগো দিয়ে)
- Topics: `telegram-bot`, `free-hosting`, `paas`, `bot-hosting`
- জনপ্রিয় bot library-র README-তে "Deployment" সেকশনে PR পাঠাও
- `awesome-telegram-bots` টাইপ লিস্টে PR

### যা করবে না ❌

- গ্রুপে গ্রুপে লিংক ছুড়ে মারা → ban খাবে, brand নষ্ট হবে
- মেম্বার কেনা → fake, engagement ০, Telegram reach কমিয়ে দেয়
- "🔥🔥 BEST FREE HOSTING 🔥🔥" — কেউ বিশ্বাস করে না
- দিনে ১০টা পোস্ট → মানুষ mute করে দেয়

---

## 6. Content Plan — কী পোস্ট করবে

**সপ্তাহে ৩টা পোস্ট। এর বেশি না।** খালি চ্যানেলের চেয়ে খারাপ শুধু স্প্যামি চ্যানেল।

### ফরম্যাট A: "এক সমস্যা, এক সমাধান" (সপ্তাহে ১টা)

```
❓ বট crash করলে কী হয়?

অনেকে জিজ্ঞেস করে। উত্তর:

CodeNest নিজেই দেখে বট বেঁচে আছে কিনা।
মরে গেলে — অটো restart। তুমি কিছুই করবে না।

Log-এ গিয়ে দেখতে পারবে কেন মরেছিল।

▸ codenest.xyz
```

### ফরম্যাট B: কোড স্নিপেট (সপ্তাহে ১টা)

দরকারি ছোট কোড, শেষে soft CTA। মানুষ এগুলো save করে, forward করে।

```
📌 Bot-এ ইউজার কাউন্ট করার সবচেয়ে সহজ উপায়

from telebot import TeleBot
import json, os

def track(uid):
    users = set(json.load(open('u.json'))) if os.path.exists('u.json') else set()
    users.add(uid)
    json.dump(list(users), open('u.json','w'))
    return len(users)

@bot.message_handler(commands=['start'])
def start(m):
    n = track(m.from_user.id)
    bot.reply_to(m, f"স্বাগতম! তুমি {n} নম্বর ইউজার 🎉")

CodeNest-এ file persist থাকে, তাই u.json মুছে যাবে না।
```

### ফরম্যাট C: Proof / Update (সপ্তাহে ১টা)

```
📊 এই সপ্তাহে CodeNest-এ:

• ৪৭টা bot চলছে
• ১২ দিন — সবচেয়ে বেশি uptime একটা bot-এর
• ০ টাকা খরচ কারো

নতুন: env variable এখন এডিটর থেকেই সেট করা যায়

▸ codenest.xyz
```

সংখ্যা ছোট হলেও পোস্ট করো। **সত্যিকারের ছোট সংখ্যা মিথ্যা বড় সংখ্যার চেয়ে বেশি বিশ্বাসযোগ্য।**

### ৩০ দিনের ক্যালেন্ডার

| দিন | পোস্ট |
|---|---|
| 1 | Pinned launch post (উপরে সেকশন ৩) |
| 3 | "কেন বানালাম" — তোমার নিজের গল্প, ২ প্যারা |
| 5 | কোড স্নিপেট: bot-এ inline keyboard |
| 7 | "৩ ধাপে bot deploy" — স্ক্রিনশট বা GIF |
| 10 | ভুল: "BOT_TOKEN কোডে হার্ডকোড কোরো না" → env var দেখাও |
| 12 | ইউজার শাউটআউট / প্রথম ফিডব্যাক |
| 14 | তুলনা: Heroku vs Render vs CodeNest (সৎ থাকো, নিজের দুর্বলতাও লেখো) |
| 17 | কোড স্নিপেট: bot দিয়ে ফাইল পাঠানো |
| 20 | Behind the scenes: uptime কিভাবে রাখি |
| 23 | Poll: "তোমার bot কোন ভাষায়?" Python / Node / দুটোই |
| 26 | "৫টা bot আইডিয়া যেগুলো এক ঘণ্টায় বানানো যায়" |
| 30 | মাসিক আপডেট + সংখ্যা |

---

## 7. Bio-তে কী লিখবে

তোমার ব্যক্তিগত Telegram bio:

```
Building CodeNest — free 24/7 hosting for Telegram bots
👉 @codenest_bd
```

GitHub bio, Twitter/X bio, YouTube about — সব জায়গায় **একই এক লাইন**। Consistency-ই brand.

---

## 8. Bot-কেই সবচেয়ে বড় marketing tool বানাও

এটা সবচেয়ে underrated অংশ। `@CodeNestBot`-এ `/start` চাপলে:

```
👋 CodeNest-এ স্বাগতম

তোমার Telegram bot ২৪/৭ চালাও — ফ্রিতে।

[ 🚀 সাইটে যাও ]        ← ইনলাইন বাটন (URL লুকানো থাকে)
[ 📖 কিভাবে কাজ করে ]
[ 💬 সাপোর্ট গ্রুপ ]
[ 📢 চ্যানেল ]
```

সুবিধা:
- কাঁচা `onrender.com` URL কেউ দেখে না
- প্রত্যেক ভিজিটরের chat ID পেয়ে যাচ্ছ → পরে "নতুন ফিচার এসেছে" পাঠাতে পারবে
- bot-এর ভিতর থেকেই signup → ঘর্ষণ (friction) প্রায় শূন্য

---

## 9. প্রথম ১০০ মেম্বার — সপ্তাহভিত্তিক প্ল্যান

**সপ্তাহ ১ — ঘর গোছাও**
- Avatar, নাম, description, pinned post বসাও
- ৩টা পোস্ট আগেই লিখে রাখো (খালি চ্যানেল কেউ join করে না)
- Discussion group লিংক করো
- Domain কিনে বসাও

**সপ্তাহ ২ — বীজ বপন**
- ৫টা relevant Telegram গ্রুপে join করো, শুধু **সাহায্য** করো
- ৩টা পুরনো Reddit/SO থ্রেডে সৎ কমেন্ট
- বন্ধুদের বলো — ১০-২০ জন

**সপ্তাহ ৩ — প্রমাণ**
- প্রথম কয়েকজন ইউজারের সাথে ব্যক্তিগতভাবে কথা বলো, bug ঠিক করো
- ওদের অনুমতি নিয়ে screenshot পোস্ট করো
- "৩ ধাপে deploy" GIF বানাও

**সপ্তাহ ৪ — স্কেল**
- YouTube ভিডিও আপলোড
- GitHub রিপো public + README
- Poll চালাও (engagement বাড়ে → Telegram reach বাড়ে)

**বাস্তবসম্মত লক্ষ্য:** মাস ১-এ ১০০, মাস ৩-এ ৫০০। এর চেয়ে দ্রুত কেউ বললে সে fake মেম্বার বেচছে।

---

## 10. Positioning — এক লাইনে

সব জায়গায় **এই এক লাইনটাই** ব্যবহার করবে:

> **CodeNest — ফ্রিতে তোমার Telegram bot ২৪/৭ চালাও। PC বন্ধ থাকলেও।**

ইংরেজিতে:

> **CodeNest — Free 24/7 hosting for Telegram bots. No card, no sleep.**

"free hosting platform" বলবে না — খুব সাধারণ, হাজারটা আছে।
**"Telegram bot hosting"** বলবে — নির্দিষ্ট, আর তুমি ঠিক এটাই বানিয়েছ।

ছোট নির্দিষ্ট বাজারে ১ নম্বর হওয়া, বড় বাজারে ১০০০ নম্বর হওয়ার চেয়ে ভালো।

---

## চেকলিস্ট

- [ ] Avatar বসাও (`mark-dark-512.png`)
- [ ] নাম: `CodeNest`, username: `@codenest_bd`
- [ ] Description বসাও (সেকশন ২)
- [ ] Pinned post + `post-template-2.png` (সেকশন ৩)
- [ ] Domain কেনো → Render-এ যোগ করো (সেকশন ৪)
- [ ] `PUBLIC_BASE_URL` / `SITE_BASE_URL` আপডেট → দুই সার্ভিস redeploy
- [ ] Bot-এর `/start` মেনু বানাও (সেকশন ৮)
- [ ] Discussion group খোলো + লিংক করো
- [ ] সব bio-তে এক লাইন (সেকশন ৭)
- [ ] ৫টা Telegram গ্রুপে join করো
- [ ] ৩টা পোস্ট লিখে রেডি রাখো
