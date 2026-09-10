"""Practical starter bots. Every template reads the token from BOT_TOKEN."""


def _item(name, description, category, language, framework, code, badge="", env_fields=None, after_deploy=""):
    return {"name": name, "description": description, "category": category,
            "language": language, "framework": framework, "badge": badge,
            "env_fields": list(env_fields or []), "after_deploy": after_deploy,
            "code": code.strip() + "\n"}


TEMPLATES = {
    "command-bot": _item(
        "Command bot", "A clean /start and /help foundation.", "Basics",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I am online. Send /help to begin.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Commands:\\n/start — start the bot\\n/help — show help")

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.run_polling()
''', "Popular"),

    "aiogram-echo": _item(
        "Aiogram echo", "Replies with the same text a user sends.", "Basics",
        "python", "aiogram", '''
# requirements: aiogram==3.13.1
import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

@dp.message(F.text)
async def echo(message: Message):
    await message.answer(message.text)

async def main():
    await dp.start_polling(bot)

asyncio.run(main())
''', "Simple"),

    "telebot-menu": _item(
        "Reply menu", "A simple keyboard with Help, About, and Contact buttons.", "Menus",
        "python", "pyTelegramBotAPI", '''
# requirements: pyTelegramBotAPI==4.23.0
import os
import telebot
from telebot import types

bot = telebot.TeleBot(os.getenv("BOT_TOKEN"))

@bot.message_handler(commands=["start"])
def start(message):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add("Help", "About", "Contact")
    bot.send_message(message.chat.id, "Choose an option:", reply_markup=keyboard)

@bot.message_handler(func=lambda m: True)
def menu(message):
    replies = {"Help": "How can I help?", "About": "Hosted on CodeNest.", "Contact": "Send your message here."}
    bot.reply_to(message, replies.get(message.text, "Use the menu below."))

bot.infinity_polling(skip_pending=True)
''', "Popular"),

    "inline-buttons": _item(
        "Inline buttons", "Clickable buttons with callback responses.", "Menus",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Status", callback_data="status"), InlineKeyboardButton("Help", callback_data="help")]]
    await update.message.reply_text("Choose an action:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Bot is running." if query.data == "status" else "Send /start to open the menu.")

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))
app.run_polling()
'''),

    "welcome-bot": _item(
        "Group welcome", "Welcomes new group members and shows /rules.", "Groups",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

RULES = "1. Be respectful\\n2. No spam\\n3. Stay on topic"

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        await update.message.reply_text(f"Welcome, {member.first_name}!\\n\\n{RULES}")

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(RULES)

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
app.add_handler(CommandHandler("rules", rules))
app.run_polling()
''', "Groups"),

    "file-info": _item(
        "File ID helper", "Returns Telegram file IDs for photos and documents.", "Utilities",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

async def file_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document:
        item = update.message.document
        text = f"Document: {item.file_name}\\nFile ID: {item.file_id}"
    else:
        item = update.message.photo[-1]
        text = f"Photo size: {item.width}×{item.height}\\nFile ID: {item.file_id}"
    await update.message.reply_text(text)

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, file_info))
app.run_polling()
'''),

    "poll-bot": _item(
        "Quick poll", "Creates a Telegram poll from one command.", "Utilities",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

async def poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args)
    parts = [part.strip() for part in raw.split("|") if part.strip()]
    if len(parts) < 3:
        await update.message.reply_text("Use: /poll Question | Option one | Option two")
        return
    await update.message.reply_poll(parts[0], parts[1:11], is_anonymous=False)

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("poll", poll))
app.run_polling()
'''),

    "reminder-bot": _item(
        "Simple reminder", "Sends a reminder after a number of seconds.", "Utilities",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import asyncio
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

async def send_later(chat_id, seconds, text, context):
    await asyncio.sleep(seconds)
    await context.bot.send_message(chat_id, f"⏰ {text}")

async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2 or not context.args[0].isdigit():
        await update.message.reply_text("Use: /remind 60 Drink water")
        return
    seconds = min(int(context.args[0]), 86400)
    text = " ".join(context.args[1:])
    context.application.create_task(send_later(update.effective_chat.id, seconds, text, context))
    await update.message.reply_text(f"Reminder set for {seconds} seconds.")

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("remind", remind))
app.run_polling()
'''),

    "notes-bot": _item(
        "Personal notes", "Saves small notes in SQLite and retrieves them by key.", "Storage",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

DB = sqlite3.connect("notes.db", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS notes (chat_id INTEGER, name TEXT, value TEXT, PRIMARY KEY(chat_id, name))")

async def save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Use: /save name your note")
        return
    name, value = context.args[0].lower(), " ".join(context.args[1:])
    DB.execute("INSERT OR REPLACE INTO notes VALUES (?, ?, ?)", (update.effective_chat.id, name, value))
    DB.commit()
    await update.message.reply_text(f"Saved: {name}")

async def note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.args[0].lower() if context.args else ""
    row = DB.execute("SELECT value FROM notes WHERE chat_id=? AND name=?", (update.effective_chat.id, name)).fetchone()
    await update.message.reply_text(row[0] if row else "Note not found. Use /save first.")

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("save", save))
app.add_handler(CommandHandler("note", note))
app.run_polling()
''', "Storage"),

    "url-checker": _item(
        "Website checker", "Checks a public URL and reports its HTTP status.", "Utilities",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4 requests==2.32.3
import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].startswith(("http://", "https://")):
        await update.message.reply_text("Use: /check https://example.com")
        return
    try:
        response = requests.get(context.args[0], timeout=8, allow_redirects=True)
        await update.message.reply_text(f"Status: {response.status_code}\\nFinal URL: {response.url}")
    except requests.RequestException:
        await update.message.reply_text("The website did not respond in time.")

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("check", check))
app.run_polling()
'''),

    "master-referral": _item(
        "Master referral rewards", "Channel join verification, referral rewards, withdrawals, leaderboard, broadcast, and in-bot admin panel.", "Growth",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
import sqlite3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

DB = sqlite3.connect("master_referral.db", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
DB.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, referrer INTEGER, active INTEGER DEFAULT 0, balance REAL DEFAULT 0, banned INTEGER DEFAULT 0, joined_at TEXT DEFAULT CURRENT_TIMESTAMP)")
DB.execute("CREATE TABLE IF NOT EXISTS withdrawals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
DB.commit()

def get_setting(key, default=""):
    row = DB.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default

def set_setting(key, value):
    DB.execute("INSERT OR REPLACE INTO settings VALUES(?, ?)", (key, str(value))); DB.commit()

def admin_id(): return int(get_setting("admin_id", "0") or 0)
def reward(): return float(get_setting("reward", "10"))
def currency(): return get_setting("currency", "Points")
def minimum(): return float(get_setting("minimum", "100"))
def channel(): return get_setting("channel", "")

def user_row(user_id):
    return DB.execute("SELECT user_id, referrer, active, balance, banned FROM users WHERE user_id=?", (user_id,)).fetchone()

async def is_member(user_id, context):
    if not channel(): return False
    try:
        member = await context.bot.get_chat_member(channel(), user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

async def main_menu(chat_id, context):
    keys = [
        [InlineKeyboardButton("👥 Invite & Earn", callback_data="ref"), InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="top"), InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ]
    await context.bot.send_message(chat_id, "Choose an option:", reply_markup=InlineKeyboardMarkup(keys))

async def join_prompt(chat_id, context):
    if not channel():
        await context.bot.send_message(chat_id, "The admin is still configuring this bot. Please try again later.")
        return
    username = channel().lstrip("@")
    keys = [[InlineKeyboardButton("📢 Join channel", url=f"https://t.me/{username}")],
            [InlineKeyboardButton("✅ I joined — check", callback_data="check_join")]]
    await context.bot.send_message(chat_id, "Join the channel first. Your referral reward unlocks only after membership is verified.", reply_markup=InlineKeyboardMarkup(keys))

async def activate(user_id, context):
    row = user_row(user_id)
    if not row or row[2]: return False
    DB.execute("UPDATE users SET active=1 WHERE user_id=?", (user_id,))
    if row[1]:
        DB.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward(), row[1]))
    DB.commit()
    if row[1]:
        try: await context.bot.send_message(row[1], f"🎉 New verified referral! +{reward():g} {currency()}")
        except Exception: pass
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not admin_id():
        set_setting("admin_id", uid)
        DB.execute("INSERT OR IGNORE INTO users(user_id, active) VALUES(?, 1)", (uid,)); DB.commit()
        await update.message.reply_text("You are the master admin because you opened the bot first.\\n\\n1. Add this bot as an administrator in your channel.\\n2. Send /setchannel @yourchannel\\n3. Open /panel for controls.")
        return
    row = user_row(uid)
    if row and row[4]: return
    referrer = None
    if not row and context.args and context.args[0].isdigit():
        candidate = int(context.args[0])
        if candidate != uid:
            owner = user_row(candidate)
            if owner and owner[2] and not owner[4]: referrer = candidate
    DB.execute("INSERT OR IGNORE INTO users(user_id, referrer) VALUES(?, ?)", (uid, referrer)); DB.commit()
    if uid == admin_id():
        await main_menu(uid, context); return
    if await is_member(uid, context):
        await activate(uid, context); await main_menu(uid, context)
    else: await join_prompt(uid, context)

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); uid = q.from_user.id
    row = user_row(uid)
    if not row or row[4]: return
    if q.data == "check_join":
        if await is_member(uid, context):
            await activate(uid, context); await q.edit_message_text("✅ Membership verified. Reward access unlocked."); await main_menu(uid, context)
        else: await q.answer("Join the channel first.", show_alert=True)
    elif not row[2]: await join_prompt(uid, context)
    elif q.data == "ref":
        me = await context.bot.get_me(); count = DB.execute("SELECT COUNT(*) FROM users WHERE referrer=? AND active=1", (uid,)).fetchone()[0]
        await q.message.reply_text(f"Your referral link:\\nhttps://t.me/{me.username}?start={uid}\\n\\nVerified referrals: {count}\\nReward: {reward():g} {currency()} each")
    elif q.data == "balance": await q.message.reply_text(f"Balance: {row[3]:g} {currency()}")
    elif q.data == "top":
        rows = DB.execute("SELECT user_id,balance FROM users WHERE active=1 ORDER BY balance DESC LIMIT 10").fetchall()
        await q.message.reply_text("🏆 Leaderboard\\n" + "\\n".join(f"{i+1}. {r[0]} — {r[1]:g} {currency()}" for i,r in enumerate(rows)))
    elif q.data == "withdraw":
        if row[3] < minimum(): await q.message.reply_text(f"Minimum withdrawal: {minimum():g} {currency()}")
        elif DB.execute("SELECT 1 FROM withdrawals WHERE user_id=? AND status='pending'", (uid,)).fetchone(): await q.message.reply_text("You already have a pending request.")
        else:
            cur = DB.execute("INSERT INTO withdrawals(user_id,amount) VALUES(?,?)", (uid,row[3])); DB.commit()
            await q.message.reply_text("Withdrawal request sent to admin.")
            await context.bot.send_message(admin_id(), f"Withdrawal #{cur.lastrowid}\\nUser: {uid}\\nAmount: {row[3]:g} {currency()}\\n/approve {cur.lastrowid} or /reject {cur.lastrowid}")
    elif q.data == "help": await q.message.reply_text("Invite real users. A referral counts only after the new user joins the required channel.")

async def setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != admin_id(): return
    if not context.args or not context.args[0].startswith("@"): await update.message.reply_text("Use: /setchannel @publicchannel"); return
    target = context.args[0]
    try:
        me = await context.bot.get_me(); member = await context.bot.get_chat_member(target, me.id)
        if member.status not in ("administrator", "creator"): raise ValueError()
    except Exception: await update.message.reply_text("Add the bot as channel admin first, then retry."); return
    set_setting("channel", target); await update.message.reply_text(f"Channel connected: {target}")

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != admin_id(): return
    users=DB.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]; pending=DB.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
    await update.message.reply_text(f"Admin panel\\nChannel: {channel() or 'not set'}\\nUsers: {users}\\nReward: {reward():g} {currency()}\\nMinimum: {minimum():g}\\nPending withdrawals: {pending}\\n\\n/setchannel @name\\n/setreward 10\\n/setminimum 100\\n/setcurrency Points\\n/broadcast text\\n/ban USER_ID\\n/unban USER_ID")

async def admin_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != admin_id() or not context.args: return
    command = update.message.text.split()[0].split("@")[0]
    if command == "/setreward" and context.args[0].replace('.','',1).isdigit(): set_setting("reward", context.args[0])
    elif command == "/setminimum" and context.args[0].replace('.','',1).isdigit(): set_setting("minimum", context.args[0])
    elif command == "/setcurrency": set_setting("currency", " ".join(context.args)[:20])
    else: return
    await update.message.reply_text("Setting updated.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != admin_id(): return
    text = " ".join(context.args)
    if not text: await update.message.reply_text("Use: /broadcast message"); return
    sent=0
    for (uid,) in DB.execute("SELECT user_id FROM users WHERE active=1 AND banned=0").fetchall():
        try: await context.bot.send_message(uid,text); sent+=1
        except Exception: pass
    await update.message.reply_text(f"Delivered to {sent} user(s).")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != admin_id() or not context.args or not context.args[0].isdigit(): return
    request_id=int(context.args[0]); row=DB.execute("SELECT user_id,amount,status FROM withdrawals WHERE id=?",(request_id,)).fetchone()
    if not row or row[2] != "pending": await update.message.reply_text("Pending request not found."); return
    DB.execute("UPDATE users SET balance=MAX(0,balance-?) WHERE user_id=?",(row[1],row[0])); DB.execute("UPDATE withdrawals SET status='approved' WHERE id=?",(request_id,)); DB.commit()
    await context.bot.send_message(row[0],f"Withdrawal approved: {row[1]:g} {currency()}"); await update.message.reply_text("Approved.")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != admin_id() or not context.args or not context.args[0].isdigit(): return
    request_id=int(context.args[0]); row=DB.execute("SELECT user_id FROM withdrawals WHERE id=? AND status='pending'",(request_id,)).fetchone()
    if not row: return
    DB.execute("UPDATE withdrawals SET status='rejected' WHERE id=?",(request_id,)); DB.commit(); await context.bot.send_message(row[0],"Withdrawal request rejected."); await update.message.reply_text("Rejected.")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != admin_id() or not context.args or not context.args[0].isdigit(): return
    value = 0 if update.message.text.startswith("/unban") else 1; DB.execute("UPDATE users SET banned=? WHERE user_id=?",(value,int(context.args[0]))); DB.commit(); await update.message.reply_text("User status updated.")

app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("start",start)); app.add_handler(CallbackQueryHandler(callback))
app.add_handler(CommandHandler("setchannel",setchannel)); app.add_handler(CommandHandler("panel",panel))
for cmd in ("setreward","setminimum","setcurrency"): app.add_handler(CommandHandler(cmd,admin_setting))
app.add_handler(CommandHandler("broadcast",broadcast)); app.add_handler(CommandHandler("approve",approve)); app.add_handler(CommandHandler("reject",reject)); app.add_handler(CommandHandler("ban",ban)); app.add_handler(CommandHandler("unban",ban)); app.run_polling()
''', "Master", [], "Open the bot first; the first /start user becomes master admin. Then add the bot as channel admin and use /setchannel @channel."),

    "referral-bot": _item(
        "Referral bot", "Real deep-link referrals with SQLite counts and personal invite links.", "Growth",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

DB = sqlite3.connect("referrals.db", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, referrer_id INTEGER, joined_at TEXT DEFAULT CURRENT_TIMESTAMP)")
DB.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    existing = DB.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
    referrer = None
    if not existing and context.args and context.args[0].isdigit():
        candidate = int(context.args[0])
        if candidate != user_id and DB.execute("SELECT 1 FROM users WHERE user_id=?", (candidate,)).fetchone():
            referrer = candidate
    DB.execute("INSERT OR IGNORE INTO users(user_id, referrer_id) VALUES(?, ?)", (user_id, referrer))
    DB.commit()
    await update.message.reply_text("Welcome! Use /ref to get your referral link and /stats to see referrals.")

async def referral_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={update.effective_user.id}"
    await update.message.reply_text(f"Your referral link:\\n{link}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = DB.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (update.effective_user.id,)).fetchone()[0]
    await update.message.reply_text(f"You invited {count} user(s).")

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("ref", referral_link))
app.add_handler(CommandHandler("stats", stats))
app.run_polling()
''', "Real use"),

    "contact-support": _item(
        "Live support inbox", "Livegram-style anonymous inbox with admin replies, bans, and stats.", "Business",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

CLAIM_CODE = os.getenv("ADMIN_CLAIM_CODE", "")
DB = sqlite3.connect("live_support.db", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
DB.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, banned INTEGER DEFAULT 0)")
DB.execute("CREATE TABLE IF NOT EXISTS tickets (admin_message_id INTEGER PRIMARY KEY, user_id INTEGER)")
DB.commit()

def setting(key):
    row = DB.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None

def admin_id():
    value = setting("admin_id")
    return int(value) if value else 0

async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if admin_id():
        await update.message.reply_text("Admin is already connected.")
    elif context.args and context.args[0] == CLAIM_CODE:
        DB.execute("INSERT OR REPLACE INTO settings VALUES('admin_id', ?)", (str(update.effective_user.id),))
        DB.commit()
        await update.message.reply_text("You are now the support admin. Reply to forwarded messages to answer users.")
    else:
        await update.message.reply_text("Invalid claim code.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_id() and context.args and context.args[0] == "claim_" + CLAIM_CODE:
        DB.execute("INSERT INTO settings VALUES('admin_id', ?)", (str(update.effective_user.id),)); DB.commit()
        await update.message.reply_text("You are now the support admin. Reply to copied messages to answer users.")
        return
    DB.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (update.effective_user.id,))
    DB.commit()
    await update.message.reply_text("Send any message, photo, or file. Support will reply here.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != admin_id(): return
    users = DB.execute("SELECT COUNT(*) FROM users WHERE banned=0").fetchone()[0]
    banned = DB.execute("SELECT COUNT(*) FROM users WHERE banned=1").fetchone()[0]
    await update.message.reply_text(f"Users: {users}\\nBanned: {banned}")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != admin_id() or not update.message.reply_to_message: return
    row = DB.execute("SELECT user_id FROM tickets WHERE admin_message_id=?", (update.message.reply_to_message.message_id,)).fetchone()
    if row:
        DB.execute("UPDATE users SET banned=1 WHERE user_id=?", (row[0],)); DB.commit()
        await update.message.reply_text(f"User {row[0]} banned.")

async def route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = admin_id()
    if not admin: return
    if update.effective_user.id == admin and update.message.reply_to_message:
        row = DB.execute("SELECT user_id FROM tickets WHERE admin_message_id=?", (update.message.reply_to_message.message_id,)).fetchone()
        if row:
            await context.bot.copy_message(row[0], update.effective_chat.id, update.message.message_id)
            await update.message.reply_text("Reply delivered.")
        return
    row = DB.execute("SELECT banned FROM users WHERE user_id=?", (update.effective_user.id,)).fetchone()
    if row and row[0]: return
    DB.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (update.effective_user.id,)); DB.commit()
    header = await context.bot.send_message(admin, f"Message from {update.effective_user.full_name}\\nUser ID: {update.effective_user.id}")
    copied = await context.bot.copy_message(admin, update.effective_chat.id, update.message.message_id, reply_to_message_id=header.message_id)
    DB.execute("INSERT OR REPLACE INTO tickets VALUES(?, ?)", (copied.message_id, update.effective_user.id)); DB.commit()
    await update.message.reply_text("Your message reached support.")

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("claim", claim))
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("ban", ban))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, route))
app.run_polling()
''', "Real use", [{"key":"ADMIN_CLAIM_CODE","type":"generated","label":"One-time admin claim code","help":"After deploy, send /claim CODE to the bot. It securely learns your Telegram ID and disables further claims.","required":True}], "Send /claim CODE from your own account. Then users can contact you and you can reply to copied messages."),

    "admin-broadcast": _item(
        "Admin broadcast bot", "Self-claiming subscriber bot with admin stats and broadcasts.", "Admin",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
import sqlite3
from telegram import Update
from telegram.error import Forbidden
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

CLAIM_CODE = os.getenv("ADMIN_CLAIM_CODE", "")
DB = sqlite3.connect("broadcast.db", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
DB.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
DB.commit()

def admin_id():
    row = DB.execute("SELECT value FROM settings WHERE key='admin_id'").fetchone()
    return int(row[0]) if row else 0

async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if admin_id(): await update.message.reply_text("Admin already connected.")
    elif context.args and context.args[0] == CLAIM_CODE:
        DB.execute("INSERT INTO settings VALUES('admin_id', ?)", (str(update.effective_user.id),)); DB.commit()
        await update.message.reply_text("Admin connected. Use /stats and /broadcast message.")
    else: await update.message.reply_text("Invalid claim code.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_id() and context.args and context.args[0] == "claim_" + CLAIM_CODE:
        DB.execute("INSERT INTO settings VALUES('admin_id', ?)", (str(update.effective_user.id),)); DB.commit()
        await update.message.reply_text("Admin connected. Use /stats and /broadcast message.")
        return
    DB.execute("INSERT OR IGNORE INTO users VALUES(?)", (update.effective_user.id,)); DB.commit()
    await update.message.reply_text("You are subscribed to announcements.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != admin_id(): return
    await update.message.reply_text(f"Subscribers: {DB.execute('SELECT COUNT(*) FROM users').fetchone()[0]}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != admin_id(): return
    text = " ".join(context.args)
    if not text: await update.message.reply_text("Use: /broadcast Your announcement"); return
    sent = 0
    for (user_id,) in DB.execute("SELECT user_id FROM users").fetchall():
        try: await context.bot.send_message(user_id, text); sent += 1
        except Forbidden: DB.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    DB.commit(); await update.message.reply_text(f"Delivered to {sent} user(s).")

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("claim", claim)); app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats)); app.add_handler(CommandHandler("broadcast", broadcast))
app.run_polling()
''', "Admin", [{"key":"ADMIN_CLAIM_CODE","type":"generated","label":"One-time admin claim code","help":"After deploy, send /claim CODE. No numeric Telegram ID is needed.","required":True}], "Send /claim CODE, then share the bot. Use /broadcast message and /stats as admin."),

    "file-store": _item(
        "File sharing bot", "Stores Telegram file IDs and creates reusable deep links for downloads.", "Storage",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
import secrets
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

DB = sqlite3.connect("files.db", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS files (code TEXT PRIMARY KEY, file_id TEXT, kind TEXT, name TEXT)")
DB.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].startswith("file_"):
        row = DB.execute("SELECT file_id, kind, name FROM files WHERE code=?", (context.args[0][5:],)).fetchone()
        if row:
            if row[1] == "document":
                await context.bot.send_document(update.effective_chat.id, row[0], caption=row[2])
            else:
                await context.bot.send_photo(update.effective_chat.id, row[0], caption=row[2])
            return
    await update.message.reply_text("Send me a photo or document. I will create a share link.")

async def save_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document:
        item, kind, name = update.message.document, "document", update.message.document.file_name or "Document"
    else:
        item, kind, name = update.message.photo[-1], "photo", "Photo"
    code = secrets.token_urlsafe(6)
    DB.execute("INSERT INTO files VALUES(?, ?, ?, ?)", (code, item.file_id, kind, name))
    DB.commit()
    me = await context.bot.get_me()
    await update.message.reply_text(f"Share link:\\nhttps://t.me/{me.username}?start=file_{code}")

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, save_file))
app.run_polling()
''', "Storage"),

    "order-bot": _item(
        "Simple order bot", "Product buttons, order confirmation, and self-claimed admin notifications.", "Business",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
import sqlite3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

CLAIM_CODE = os.getenv("ADMIN_CLAIM_CODE", "")
DB = sqlite3.connect("orders.db", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"); DB.commit()
PRODUCTS = {"basic": "Basic plan — $5", "pro": "Pro plan — $10"}

def admin_id():
    row=DB.execute("SELECT value FROM settings WHERE key='admin_id'").fetchone()
    return int(row[0]) if row else 0

async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if admin_id(): await update.message.reply_text("Admin already connected.")
    elif context.args and context.args[0] == CLAIM_CODE:
        DB.execute("INSERT INTO settings VALUES('admin_id', ?)", (str(update.effective_user.id),)); DB.commit()
        await update.message.reply_text("Admin connected. New orders will arrive here.")
    else: await update.message.reply_text("Invalid claim code.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_id() and context.args and context.args[0] == "claim_" + CLAIM_CODE:
        DB.execute("INSERT INTO settings VALUES('admin_id', ?)", (str(update.effective_user.id),)); DB.commit()
        await update.message.reply_text("Admin connected. New orders will arrive here.")
        return
    buttons=[[InlineKeyboardButton(label,callback_data=f"order:{key}")] for key,label in PRODUCTS.items()]
    await update.message.reply_text("Choose a product:",reply_markup=InlineKeyboardMarkup(buttons))

async def order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query; await query.answer(); key=query.data.split(":",1)[1]; user=query.from_user
    await query.edit_message_text(f"Order received: {PRODUCTS[key]}")
    if admin_id(): await context.bot.send_message(admin_id(),f"New order: {PRODUCTS[key]}\\nUser: @{user.username or user.id}\\nID: {user.id}")

app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("claim",claim)); app.add_handler(CommandHandler("start",start))
app.add_handler(CallbackQueryHandler(order,pattern=r"^order:")); app.run_polling()
''', "Business", [{"key":"ADMIN_CLAIM_CODE","type":"generated","label":"One-time admin claim code","help":"After deploy, send /claim CODE. Orders will then be sent to you.","required":True}], "Send /claim CODE first. Edit PRODUCTS in code for your real catalog."),

    "channel-poster": _item(
        "Channel poster", "Claim ownership, connect a channel, and publish text or replied media.", "Channels",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

CLAIM_CODE=os.getenv("ADMIN_CLAIM_CODE","")
DB=sqlite3.connect("channel_poster.db",check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"); DB.commit()
def get(key):
    row=DB.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone(); return row[0] if row else ""
def admin_id(): return int(get("admin_id") or 0)
async def claim(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if admin_id(): await update.message.reply_text("Admin already connected.")
    elif context.args and context.args[0]==CLAIM_CODE:
        DB.execute("INSERT INTO settings VALUES('admin_id',?)",(str(update.effective_user.id),));DB.commit();await update.message.reply_text("Admin connected. Add this bot as channel admin, then /setchannel @channel.")
    else: await update.message.reply_text("Invalid claim code.")
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not admin_id() and context.args and context.args[0] == "claim_" + CLAIM_CODE:
        DB.execute("INSERT INTO settings VALUES('admin_id',?)",(str(update.effective_user.id),));DB.commit()
        await update.message.reply_text("Admin connected. Add this bot as channel admin, then /setchannel @channel.")
    elif admin_id(): await update.message.reply_text("Use /setchannel @channel or /post message.")
async def setchannel(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=admin_id(): return
    if not context.args: await update.message.reply_text("Use: /setchannel @channelusername"); return
    channel=context.args[0]
    try:
        me=await context.bot.get_me(); member=await context.bot.get_chat_member(channel,me.id)
        if member.status not in ("administrator","creator"): raise ValueError()
    except Exception: await update.message.reply_text("Add the bot as channel admin first, then retry."); return
    DB.execute("INSERT OR REPLACE INTO settings VALUES('channel',?)",(channel,));DB.commit();await update.message.reply_text(f"Channel connected: {channel}")
async def post(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=admin_id(): return
    channel=get("channel")
    if not channel: await update.message.reply_text("Connect a channel with /setchannel first."); return
    if update.message.reply_to_message:
        await context.bot.copy_message(channel,update.effective_chat.id,update.message.reply_to_message.message_id)
    else:
        text=" ".join(context.args)
        if not text: await update.message.reply_text("Use /post text, or reply to media with /post."); return
        await context.bot.send_message(channel,text)
    await update.message.reply_text("Posted to channel.")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("claim",claim));app.add_handler(CommandHandler("start",start));app.add_handler(CommandHandler("setchannel",setchannel));app.add_handler(CommandHandler("post",post));app.run_polling()
''', "Channels", [{"key":"ADMIN_CLAIM_CODE","type":"generated","label":"One-time admin claim code","help":"After deploy, send /claim CODE, then add the bot as a channel admin.","required":True}], "Claim admin, add the bot as channel admin, then send /setchannel @channel."),

    "channel-gate": _item(
        "Channel join gate", "Requires users to join your channel before using the bot.", "Channels",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os, sqlite3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes
CLAIM_CODE=os.getenv("ADMIN_CLAIM_CODE","");DB=sqlite3.connect("channel_gate.db",check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT)");DB.commit()
def get(k):
    r=DB.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone();return r[0] if r else ""
def admin_id():return int(get("admin_id") or 0)
async def claim(u:Update,c:ContextTypes.DEFAULT_TYPE):
    if not admin_id() and c.args and c.args[0]==CLAIM_CODE: DB.execute("INSERT INTO settings VALUES('admin_id',?)",(str(u.effective_user.id),));DB.commit();await u.message.reply_text("Admin connected. Use /setchannel @channel.")
async def setchannel(u:Update,c:ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id!=admin_id() or not c.args:return
    DB.execute("INSERT OR REPLACE INTO settings VALUES('channel',?)",(c.args[0],));DB.commit();await u.message.reply_text("Channel saved. Make this bot an admin there for reliable checks.")
async def membership(user_id,c):
    try:return (await c.bot.get_chat_member(get("channel"),user_id)).status in ("member","administrator","creator")
    except Exception:return False
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
    if not admin_id() and c.args and c.args[0] == "claim_" + CLAIM_CODE:
        DB.execute("INSERT INTO settings VALUES('admin_id',?)",(str(u.effective_user.id),));DB.commit();await u.message.reply_text("Admin connected. Use /setchannel @channel.");return
    channel=get("channel")
    if channel and await membership(u.effective_user.id,c):await u.message.reply_text("Access granted. Welcome!");return
    name=channel.lstrip("@")
    keys=[[InlineKeyboardButton("Join channel",url=f"https://t.me/{name}")],[InlineKeyboardButton("Check again",callback_data="check_join")]]
    await u.message.reply_text("Join the channel to continue.",reply_markup=InlineKeyboardMarkup(keys))
async def check(u:Update,c:ContextTypes.DEFAULT_TYPE):
    await u.callback_query.answer()
    await u.callback_query.edit_message_text("Access granted. Welcome!" if await membership(u.effective_user.id,c) else "Not joined yet. Join and try again.")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build();app.add_handler(CommandHandler("claim",claim));app.add_handler(CommandHandler("setchannel",setchannel));app.add_handler(CommandHandler("start",start));app.add_handler(CallbackQueryHandler(check,pattern="^check_join$"));app.run_polling()
''', "Channels", [{"key":"ADMIN_CLAIM_CODE","type":"generated","label":"One-time admin claim code","help":"Claim the bot, then connect your public channel with /setchannel.","required":True}], "Claim admin, add the bot as channel admin, then /setchannel @channel for reliable membership checks."),

    "group-helper": _item(
        "Group helper", "Welcome messages, editable rules, warnings, and reply cleanup for group admins.", "Groups",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os,sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes,MessageHandler,filters
DB=sqlite3.connect("groups.db",check_same_thread=False);DB.execute("CREATE TABLE IF NOT EXISTS settings(chat_id INTEGER,key TEXT,value TEXT,PRIMARY KEY(chat_id,key))");DB.execute("CREATE TABLE IF NOT EXISTS warns(chat_id INTEGER,user_id INTEGER,count INTEGER,PRIMARY KEY(chat_id,user_id))");DB.commit()
async def is_admin(u,c):
    m=await c.bot.get_chat_member(u.effective_chat.id,u.effective_user.id);return m.status in ("administrator","creator")
def rules(chat):
    r=DB.execute("SELECT value FROM settings WHERE chat_id=? AND key='rules'",(chat,)).fetchone();return r[0] if r else "Be respectful. No spam."
async def welcome(u:Update,c:ContextTypes.DEFAULT_TYPE):
    for m in u.message.new_chat_members:await u.message.reply_text(f"Welcome {m.first_name}!\\n{rules(u.effective_chat.id)}")
async def show_rules(u:Update,c:ContextTypes.DEFAULT_TYPE):await u.message.reply_text(rules(u.effective_chat.id))
async def setrules(u:Update,c:ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u,c):return
    text=" ".join(c.args)
    if not text:await u.message.reply_text("Use: /setrules your group rules");return
    DB.execute("INSERT OR REPLACE INTO settings VALUES(?, 'rules', ?)",(u.effective_chat.id,text));DB.commit();await u.message.reply_text("Rules updated.")
async def warn(u:Update,c:ContextTypes.DEFAULT_TYPE):
    if not await is_admin(u,c) or not u.message.reply_to_message:return
    target=u.message.reply_to_message.from_user;row=DB.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?",(u.effective_chat.id,target.id)).fetchone();count=(row[0] if row else 0)+1
    DB.execute("INSERT OR REPLACE INTO warns VALUES(?,?,?)",(u.effective_chat.id,target.id,count));DB.commit();await u.message.reply_text(f"{target.first_name} warning {count}/3")
async def clean(u:Update,c:ContextTypes.DEFAULT_TYPE):
    if await is_admin(u,c) and u.message.reply_to_message:await u.message.reply_to_message.delete();await u.message.delete()
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build();app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS,welcome));app.add_handler(CommandHandler("rules",show_rules));app.add_handler(CommandHandler("setrules",setrules));app.add_handler(CommandHandler("warn",warn));app.add_handler(CommandHandler("clean",clean));app.run_polling()
''', "Groups", [], "Add the bot to a group as admin. Group administrators can then use /setrules, /warn, and /clean."),

    "referral-rewards": _item(
        "Referral rewards", "Referral links, points, balance, leaderboard, and a self-claimed admin.", "Growth",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os,sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes
CLAIM_CODE=os.getenv("ADMIN_CLAIM_CODE","");DB=sqlite3.connect("rewards.db",check_same_thread=False);DB.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)");DB.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,referrer INTEGER,points INTEGER DEFAULT 0)");DB.commit()
def admin_id():
    r=DB.execute("SELECT value FROM settings WHERE key='admin_id'").fetchone();return int(r[0]) if r else 0
async def claim(u:Update,c:ContextTypes.DEFAULT_TYPE):
    if not admin_id() and c.args and c.args[0]==CLAIM_CODE:DB.execute("INSERT INTO settings VALUES('admin_id',?)",(str(u.effective_user.id),));DB.commit();await u.message.reply_text("Admin connected.")
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
    if not admin_id() and c.args and c.args[0] == "claim_" + CLAIM_CODE:
        DB.execute("INSERT INTO settings VALUES('admin_id',?)",(str(u.effective_user.id),));DB.commit();await u.message.reply_text("Admin connected.");return
    uid=u.effective_user.id;exists=DB.execute("SELECT 1 FROM users WHERE user_id=?",(uid,)).fetchone();ref=None
    if not exists and c.args and c.args[0].isdigit() and int(c.args[0])!=uid and DB.execute("SELECT 1 FROM users WHERE user_id=?",(int(c.args[0]),)).fetchone():ref=int(c.args[0])
    DB.execute("INSERT OR IGNORE INTO users(user_id,referrer) VALUES(?,?)",(uid,ref))
    if not exists and ref:DB.execute("UPDATE users SET points=points+10 WHERE user_id=?",(ref,))
    DB.commit();await u.message.reply_text("Welcome! Use /ref, /balance, and /top.")
async def ref(u:Update,c:ContextTypes.DEFAULT_TYPE):
    me=await c.bot.get_me();await u.message.reply_text(f"https://t.me/{me.username}?start={u.effective_user.id}")
async def balance(u:Update,c:ContextTypes.DEFAULT_TYPE):
    r=DB.execute("SELECT points FROM users WHERE user_id=?",(u.effective_user.id,)).fetchone();await u.message.reply_text(f"Points: {r[0] if r else 0}")
async def top(u:Update,c:ContextTypes.DEFAULT_TYPE):
    rows=DB.execute("SELECT user_id,points FROM users ORDER BY points DESC LIMIT 10").fetchall();await u.message.reply_text("Leaderboard\\n"+"\\n".join(f"{i+1}. {x[0]} — {x[1]}" for i,x in enumerate(rows)))
async def addpoints(u:Update,c:ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id!=admin_id() or len(c.args)!=2 or not all(x.lstrip('-').isdigit() for x in c.args):return
    DB.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)",(int(c.args[0]),));DB.execute("UPDATE users SET points=points+? WHERE user_id=?",(int(c.args[1]),int(c.args[0])));DB.commit();await u.message.reply_text("Points updated.")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build();app.add_handler(CommandHandler("claim",claim));app.add_handler(CommandHandler("start",start));app.add_handler(CommandHandler("ref",ref));app.add_handler(CommandHandler("balance",balance));app.add_handler(CommandHandler("top",top));app.add_handler(CommandHandler("addpoints",addpoints));app.run_polling()
''', "Growth", [{"key":"ADMIN_CLAIM_CODE","type":"generated","label":"One-time admin claim code","help":"After deploy, send /claim CODE to unlock admin point controls.","required":True}], "Send /claim CODE to become admin. Users then use /ref, /balance, and /top."),

    "python-echo": _item(
        "Python echo", "A clean Python text echo bot with /start.", "Basics",
        "python", "python-telegram-bot", '''
# requirements: python-telegram-bot==21.4
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Your Python bot is online.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(update.message.text[:4096])

app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
app.run_polling()
''', "Simple"),
}

# Public catalog: seven complete products, one template = one job. The legacy
# definitions above remain only as source-history while this migration settles;
# they are not listed or retrievable through the template API.
from services.flagship_templates import build_flagship_templates
TEMPLATES = build_flagship_templates()


def list_templates():
    return [{"id": key, "name": value["name"],
             "description": value["description"], "category": value["category"],
             "language": value["language"], "framework": value["framework"],
             "badge": value.get("badge", ""),
             "requires_setup": bool(value.get("env_fields"))}
            for key, value in TEMPLATES.items()]


def get_template(template_id):
    value = TEMPLATES.get(template_id)
    return dict(value) if value else None
