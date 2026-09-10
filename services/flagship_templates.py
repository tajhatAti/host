"""Complete bot products, one template = one job.

Every public product covers ONE category exhaustively (force-join, forward,
tag remover, caption, inline buttons all belong to channel management; invite
tracking, points and withdrawals belong to referral & rewards). Nothing is
borrowed from a neighbouring category, and nothing is split into fragments.
"""

from services.premium_templates import ai_code, commerce_code
from services.popular_tools import file_share_code, moderator_code

# Owner-claim secret: generated at deploy time, opened automatically by the
# "Go to bot" deep link. Never required at deploy — instant run stays instant.
CLAIM = {"key": "ADMIN_CLAIM_CODE", "type": "generated", "required": False,
         "label": "Secure admin connection",
         "help": "Generated automatically and used by the Go to bot link."}


def _opt(key, label, placeholder="", secret=True):
    return {"key": key, "type": "password" if secret else "text",
            "label": label, "required": False, "placeholder": placeholder}


def _flagship(name, description, category, code, fields=(), after="", claim=True):
    env = [CLAIM] if claim else []
    return {"name": name, "description": description, "category": category,
            "language": "python", "framework": "python-telegram-bot",
            "badge": "Complete",
            "env_fields": env + list(fields),
            "after_deploy": after or "Open Go to bot and press Start to claim owner controls.",
            "code": code.strip() + "\n"}


def channel_manager_code():
    """Channel management: force-join, approvals, invites, scheduling,
    forwarding, tag remover, captions and inline buttons — no referral/payout."""
    return r'''# requirements: python-telegram-bot[job-queue]==21.4
import asyncio,os,re,sqlite3,time
from telegram import InlineKeyboardButton,InlineKeyboardMarkup,Update
from telegram.error import Forbidden,RetryAfter
from telegram.ext import ApplicationBuilder,CallbackQueryHandler,ChannelPostHandler,CommandHandler,ContextTypes
TITLE="Complete channel manager";CLAIM=os.getenv("ADMIN_CLAIM_CODE","")
DB=sqlite3.connect("channel_manager.db",check_same_thread=False);DB.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS members(user_id INTEGER PRIMARY KEY,status TEXT DEFAULT 'pending',joined_at INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY AUTOINCREMENT,chat TEXT,text TEXT,publish_at INTEGER,status TEXT DEFAULT 'queued',delete_after INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS invites(user_id INTEGER PRIMARY KEY,link TEXT,expires INTEGER DEFAULT 0);");DB.commit()
def get(k,d=""):
 r=DB.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone();return r[0] if r else d
def admin():return int(get("admin","0"))
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES('admin',?)",(str(uid),));DB.commit();await u.message.reply_text("Owner connected. Add the bot as channel administrator, then /setchannel @channel");return
 DB.execute("INSERT OR IGNORE INTO members(user_id) VALUES(?)",(uid,));DB.commit();channel=get("channel")
 if channel and get("gate","on")=="on":
  try:m=await c.bot.get_chat_member(channel,uid);ok=m.status in ("member","administrator","creator")
  except Exception:ok=False
  if ok:
   DB.execute("UPDATE members SET status='active',joined_at=CASE WHEN joined_at=0 THEN ? ELSE joined_at END WHERE user_id=?",(int(time.time()),uid));DB.commit()
  else:
   buttons=[[InlineKeyboardButton("Join channel",url="https://t.me/"+channel.lstrip('@'))],[InlineKeyboardButton("Check membership",callback_data="check")]]
   await u.message.reply_text(f"{TITLE}\nJoin and verify to unlock access.",reply_markup=InlineKeyboardMarkup(buttons));return
 if u.effective_user.id!=admin():await u.message.reply_text(f"{TITLE}\nAccess unlocked. /start re-checks membership anytime.");return
 await u.message.reply_text(f"{TITLE}\nOwner: /setchannel @channel · /gate on|off · /approve USER · /deny USER · /invite · /schedule DELAY DELETE_AFTER TEXT · /forward · /caption TEXT · /button TEXT|URL · /tags on|off · /stats · /broadcast")
async def setchannel(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args:return
 channel=c.args[0];me=await c.bot.get_chat_member(channel,c.bot.id)
 if me.status not in ("administrator","creator"):await u.message.reply_text("Make the bot channel administrator first, then retry.");return
 DB.execute("INSERT OR REPLACE INTO settings VALUES('channel',?)",(channel,));DB.commit();await u.message.reply_text("Channel connected.")
async def gate(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args or c.args[0] not in ("on","off"):return
 DB.execute("INSERT OR REPLACE INTO settings VALUES('gate',?)",(c.args[0],));DB.commit();await u.message.reply_text("Force-join gate: "+c.args[0])
async def check(u:Update,c:ContextTypes.DEFAULT_TYPE):
 q=u.callback_query;await q.answer();channel=get("channel")
 if not channel:await q.answer("Channel not configured yet.",show_alert=True);return
 try:m=await c.bot.get_chat_member(channel,u.effective_user.id);ok=m.status in ("member","administrator","creator")
 except Exception:ok=False
 if not ok:await q.answer("Join the channel first.",show_alert=True);return
 DB.execute("INSERT OR REPLACE INTO members(user_id,status,joined_at) VALUES(?,?,?)",(u.effective_user.id,"active",int(time.time())));DB.commit();await q.message.reply_text("Membership verified. Access unlocked.")
async def approve(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args or not c.args[0].isdigit():return
 uid=int(c.args[0]);channel=get("channel")
 if not channel:await u.message.reply_text("Set the channel first.");return
 link=await c.bot.create_chat_invite_link(channel,member_limit=1,name=f"member-{uid}")
 DB.execute("INSERT OR REPLACE INTO members(user_id,status,joined_at) VALUES(?,?,?)",(uid,"active",int(time.time())));DB.execute("INSERT OR REPLACE INTO invites(user_id,link,expires) VALUES(?,?,0)",(uid,link.invite_link));DB.commit()
 try:await c.bot.send_message(uid,f"Your private invite:\n{link.invite_link}")
 except Exception:await u.message.reply_text("Approved, but the user has not started the bot yet.")
 await u.message.reply_text("Member approved.")
async def deny(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args or not c.args[0].isdigit():return
 DB.execute("UPDATE members SET status='denied' WHERE user_id=?",(int(c.args[0]),));DB.commit();await u.message.reply_text("Request denied.")
async def invite(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin():return
 channel=get("channel")
 if not channel:await u.message.reply_text("Set the channel first.");return
 link=await c.bot.create_chat_invite_link(channel,name="general");await u.message.reply_text(link.invite_link)
async def schedule(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or len(c.args)<3:return
 channel=get("channel");delay=max(0,int(c.args[0]));delete_after=max(0,int(c.args[1]));text=" ".join(c.args[2:])[:4000];when=int(time.time())+delay
 cur=DB.execute("INSERT INTO posts(chat,text,publish_at,delete_after) VALUES(?,?,?,?)",(channel,text,when,delete_after));DB.commit();c.job_queue.run_once(publish,delay,data=cur.lastrowid);await u.message.reply_text(f"Queued post #{cur.lastrowid}.")
async def publish(c:ContextTypes.DEFAULT_TYPE):
 pid=c.job.data;row=DB.execute("SELECT chat,text,delete_after FROM posts WHERE id=?",(pid,)).fetchone()
 if not row:return
 msg=await c.bot.send_message(row[0],row[1]);DB.execute("UPDATE posts SET status='published' WHERE id=?",(pid,));DB.commit()
 if row[2]:c.job_queue.run_once(delete_post,row[2],data=(row[0],msg.message_id))
async def delete_post(c:ContextTypes.DEFAULT_TYPE):
 chat,message_id=c.job.data
 try:await c.bot.delete_message(chat,message_id)
 except Exception:pass
async def forward(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not u.message.reply_to_message:return
 channel=get("channel")
 if not channel:await u.message.reply_text("Set the channel first.");return
 src=u.message.reply_to_message;caption=" ".join(c.args)[:1000] or None
 await c.bot.copy_message(channel,src.chat.id,src.message_id,caption=caption);await u.message.reply_text("Copied to the channel.")
async def caption(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args or not u.message.reply_to_message:return
 ref=u.message.reply_to_message;text=" ".join(c.args)[:1000]
 if ref.forward_from_chat and ref.forward_from_message_id:
  await c.bot.edit_message_caption(ref.forward_from_chat.id,ref.forward_from_message_id,caption=text);await u.message.reply_text("Caption updated.")
 else:await u.message.reply_text("Reply to a message forwarded from the channel.")
async def button(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or len(c.args)<2 or not u.message.reply_to_message:return
 ref=u.message.reply_to_message;label=c.args[0];url=c.args[1]
 if not url.startswith(("http://","https://")):await u.message.reply_text("Second argument must be an https URL.");return
 if ref.forward_from_chat and ref.forward_from_message_id:
  await c.bot.edit_message_reply_markup(ref.forward_from_chat.id,ref.forward_from_message_id,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(label[:60],url=url)]]));await u.message.reply_text("Button attached.")
 else:await u.message.reply_text("Reply to a message forwarded from the channel.")
async def tags(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args or c.args[0] not in ("on","off"):return
 DB.execute("INSERT OR REPLACE INTO settings VALUES('tags',?)",(c.args[0],));DB.commit();await u.message.reply_text("Tag remover: "+c.args[0])
async def on_post(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if get("tags")!="on" or not u.channel_post:return
 msg=u.channel_post;clean=lambda t:re.sub(r"@[A-Za-z0-9_]{4,32}\b","",t or "").strip()
 try:
  if msg.text and "@" in msg.text:await c.bot.edit_message_text(clean(msg.text),msg.chat.id,msg.message_id)
  elif msg.caption and "@" in msg.caption:await c.bot.edit_message_caption(msg.chat.id,msg.message_id,caption=clean(msg.caption))
 except Exception:pass
async def stats(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin():return
 total=DB.execute("SELECT COUNT(*) FROM members").fetchone()[0];active=DB.execute("SELECT COUNT(*) FROM members WHERE status='active'").fetchone()[0];posts=DB.execute("SELECT COUNT(*) FROM posts WHERE status='published'").fetchone()[0];queued=DB.execute("SELECT COUNT(*) FROM posts WHERE status='queued'").fetchone()[0]
 await u.message.reply_text(f"{TITLE}\nMembers {active}/{total} · Published {posts} · Queued {queued}")
async def broadcast(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args:return
 text=" ".join(c.args)[:4000]
 for (uid,) in DB.execute("SELECT user_id FROM members WHERE status='active'"):
  try:await c.bot.send_message(uid,text);await asyncio.sleep(.04)
  except RetryAfter as e:await asyncio.sleep(float(e.retry_after)+.2)
  except Forbidden:pass
  except Exception:pass
 await u.message.reply_text("Broadcast finished.")
async def restore(app):
 now=int(time.time())
 for pid,publish_at in DB.execute("SELECT id,publish_at FROM posts WHERE status='queued'").fetchall():app.job_queue.run_once(publish,max(0,publish_at-now),data=pid)
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).post_init(restore).build()
for x,h in [("start",start),("setchannel",setchannel),("gate",gate),("approve",approve),("deny",deny),("invite",invite),("schedule",schedule),("forward",forward),("caption",caption),("button",button),("tags",tags),("stats",stats),("broadcast",broadcast)]:app.add_handler(CommandHandler(x,h))
app.add_handler(CallbackQueryHandler(check,pattern="^check$"));app.add_handler(ChannelPostHandler(on_post));app.run_polling()
'''


def referral_rewards_code():
    """Referral & rewards: invite links, tracking, points, leaderboard and
    withdrawal requests — no channel management, no paywalls."""
    return r'''# requirements: python-telegram-bot==21.4
import asyncio,os,sqlite3,time
from telegram import Update
from telegram.error import Forbidden,RetryAfter
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes
TITLE="Complete referral & rewards";CLAIM=os.getenv("ADMIN_CLAIM_CODE","")
DB=sqlite3.connect("referral_rewards.db",check_same_thread=False);DB.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,referrer INTEGER,points INTEGER DEFAULT 0,joined_at INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS withdrawals(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,amount REAL,status TEXT DEFAULT 'pending',created INTEGER);");DB.commit()
def get(k,d=""):
 r=DB.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone();return r[0] if r else d
def admin():return int(get("admin","0"))
def rate():return float(get("rate","10"))
def minimum():return float(get("minimum","100"))
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES('admin',?)",(str(uid),));DB.commit();await u.message.reply_text("Owner connected. Use /panel.");return
 ref=int(c.args[0]) if c.args and c.args[0].isdigit() and int(c.args[0])!=uid else None
 row=DB.execute("SELECT points FROM users WHERE id=?",(uid,)).fetchone()
 if row is None:
  DB.execute("INSERT INTO users(id,referrer,joined_at) VALUES(?,?,?)",(uid,ref,int(time.time())));DB.commit()
  if ref:DB.execute("UPDATE users SET points=points+? WHERE id=?",(rate(),ref));DB.commit()
 await u.message.reply_text(f"{TITLE}\nInvite friends: /link · Balance: /points · Earn {rate():g} points per referral · Cash out: /withdraw AMOUNT (min {minimum():g})\n/top · /status")
async def link(u:Update,c:ContextTypes.DEFAULT_TYPE):
 me=await c.bot.get_me();await u.message.reply_text(f"Your invite link:\nhttps://t.me/{me.username}?start={u.effective_user.id}")
async def points(u:Update,c:ContextTypes.DEFAULT_TYPE):
 row=DB.execute("SELECT points FROM users WHERE id=?",(u.effective_user.id,)).fetchone();refs=DB.execute("SELECT COUNT(*) FROM users WHERE referrer=?",(u.effective_user.id,)).fetchone()[0]
 await u.message.reply_text(f"Points: {row[0] if row else 0}\nDirect referrals: {refs}")
async def top(u:Update,c:ContextTypes.DEFAULT_TYPE):
 rows=DB.execute("SELECT id,points FROM users ORDER BY points DESC LIMIT 10").fetchall()
 await u.message.reply_text("\n".join(f"{i+1}. {uid} — {p:g} pts" for i,(uid,p) in enumerate(rows)) if rows else "No users yet.")
async def withdraw(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if not c.args:await u.message.reply_text(f"/withdraw AMOUNT (min {minimum():g})");return
 try:amount=float(c.args[0])
 except ValueError:return
 if amount<minimum():await u.message.reply_text(f"Minimum withdrawal is {minimum():g} points.");return
 row=DB.execute("SELECT points FROM users WHERE id=?",(u.effective_user.id,)).fetchone()
 if not row or row[0]<amount:await u.message.reply_text("Not enough points.");return
 DB.execute("UPDATE users SET points=points-? WHERE id=?",(amount,u.effective_user.id));DB.execute("INSERT INTO withdrawals(user_id,amount,created) VALUES(?,?,?)",(u.effective_user.id,amount,int(time.time())));DB.commit();await u.message.reply_text("Withdrawal requested. The owner will review it.")
async def wdstatus(u:Update,c:ContextTypes.DEFAULT_TYPE):
 rows=DB.execute("SELECT id,amount,status FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 5",(u.effective_user.id,)).fetchall()
 await u.message.reply_text("\n".join(f"#{i} {a:g} · {s}" for i,a,s in rows) if rows else "No withdrawal requests.")
async def setrate(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args:return
 DB.execute("INSERT OR REPLACE INTO settings VALUES('rate',?)",(str(float(c.args[0])),));DB.commit();await u.message.reply_text("Points per referral updated.")
async def setmin(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args:return
 DB.execute("INSERT OR REPLACE INTO settings VALUES('minimum',?)",(str(float(c.args[0])),));DB.commit();await u.message.reply_text("Minimum withdrawal updated.")
async def wd(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or len(c.args)<2 or c.args[0] not in ("approve","decline") or not c.args[1].isdigit():return
 wid=int(c.args[1]);state="paid" if c.args[0]=="approve" else "declined"
 row=DB.execute("SELECT user_id,amount FROM withdrawals WHERE id=? AND status='pending'",(wid,)).fetchone()
 if not row:await u.message.reply_text("Request not found.");return
 DB.execute("UPDATE withdrawals SET status=? WHERE id=?",(state,wid));DB.commit()
 try:await c.bot.send_message(row[0],f"Withdrawal #{wid} ({row[1]:g} pts) was {state}.")
 except Exception:pass
 await u.message.reply_text(f"Withdrawal #{wid} marked {state}.")
async def withdrawals(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin():return
 rows=DB.execute("SELECT id,user_id,amount FROM withdrawals WHERE status='pending' ORDER BY id").fetchall()
 await u.message.reply_text("\n".join(f"#{i} user {uid} · {a:g}\n/wd approve|decline {i}" for i,uid,a in rows) if rows else "No pending withdrawals.")
async def panel(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin():return
 users=DB.execute("SELECT COUNT(*) FROM users").fetchone()[0];pending=DB.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0];points=DB.execute("SELECT COALESCE(SUM(points),0) FROM users").fetchone()[0]
 await u.message.reply_text(f"{TITLE}\nUsers {users} · Points issued {points:g} · Pending withdrawals {pending}\n/setrate POINTS · /setmin AMOUNT · /withdrawals · /broadcast")
async def broadcast(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args:return
 text=" ".join(c.args)[:4000]
 for (uid,) in DB.execute("SELECT id FROM users"):
  try:await c.bot.send_message(uid,text);await asyncio.sleep(.04)
  except RetryAfter as e:await asyncio.sleep(float(e.retry_after)+.2)
  except Forbidden:pass
  except Exception:pass
 await u.message.reply_text("Broadcast finished.")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
for x,h in [("start",start),("link",link),("points",points),("top",top),("withdraw",withdraw),("status",wdstatus),("setrate",setrate),("setmin",setmin),("withdrawals",withdrawals),("wd",wd),("panel",panel),("broadcast",broadcast)]:app.add_handler(CommandHandler(x,h))
app.run_polling()
'''


def media_ai_code():
    """Media & AI conversion: image compress/convert, image→PDF, PDF→text,
    OCR, voice→text, text→voice and QR — no file sharing, no scanning."""
    return r'''# requirements: python-telegram-bot==21.4 Pillow==10.4.0 pypdf==4.3.1 qrcode==7.4.2 httpx==0.27.2
import io,os,sqlite3,time
import httpx,qrcode
from PIL import Image
from pypdf import PdfReader
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes,MessageHandler,filters
TITLE="Complete media & AI converter";CLAIM=os.getenv("ADMIN_CLAIM_CODE","");AI_KEY=os.getenv("AI_API_KEY","");AI_BASE=os.getenv("AI_API_BASE","https://api.openai.com/v1").rstrip("/");OCR_KEY=os.getenv("OCR_API_KEY","")
DB=sqlite3.connect("media_converter.db",check_same_thread=False);DB.execute("PRAGMA journal_mode=WAL");DB.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,mode TEXT DEFAULT 'convert',format TEXT DEFAULT 'jpg',used INTEGER DEFAULT 0,day TEXT DEFAULT '',banned INTEGER DEFAULT 0);");DB.commit()
def admin():
 r=DB.execute("SELECT value FROM settings WHERE key='admin'").fetchone();return int(r[0]) if r else 0
def quota(uid):
 row=DB.execute("SELECT used,day,banned FROM users WHERE id=?",(uid,)).fetchone();return not row or (not row[2] and (row[1]!=time.strftime("%Y-%m-%d") or row[0]<30 or uid==admin()))
def used(uid):
 today=time.strftime("%Y-%m-%d");DB.execute("UPDATE users SET used=CASE WHEN day=? THEN used+1 ELSE 1 END,day=? WHERE id=?",(today,today,uid));DB.commit()
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES('admin',?)",(str(uid),));DB.commit();await u.message.reply_text("Owner connected. Use /panel.");return
 DB.execute("INSERT OR IGNORE INTO users(id) VALUES(?)",(uid,));DB.commit();await u.message.reply_text(f"{TITLE}\n/mode convert|pdf|text|ocr|transcribe|speak · /format jpg|png|webp|pdf · /qr TEXT · /speak TEXT\nSend an image, PDF or voice up to 20 MB.")
async def mode(u:Update,c:ContextTypes.DEFAULT_TYPE):
 allowed={"convert","pdf","text","ocr","transcribe","speak"}
 if not c.args or c.args[0] not in allowed:await u.message.reply_text("Modes: "+", ".join(sorted(allowed)));return
 DB.execute("UPDATE users SET mode=? WHERE id=?",(c.args[0],u.effective_user.id));DB.commit();await u.message.reply_text("Mode: "+c.args[0])
async def fmt(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if c.args and c.args[0] in ("jpg","png","webp","pdf"):DB.execute("UPDATE users SET format=? WHERE id=?",(c.args[0],u.effective_user.id));DB.commit();await u.message.reply_text("Output: "+c.args[0])
async def process(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id;obj=u.message.document or u.message.voice or u.message.audio or (u.message.photo[-1] if u.message.photo else None)
 if not obj:return
 user=DB.execute("SELECT mode,format,banned FROM users WHERE id=?",(uid,)).fetchone()
 if not user or user[2]:return
 selected=user[0];target=user[1]
 if selected=="transcribe" and not (u.message.voice or u.message.audio):return
 if not quota(uid) or (getattr(obj,"file_size",0) or 0)>20*1024*1024:await u.message.reply_text("Daily quota reached or file is over 20 MB.");return
 raw=bytes(await (await obj.get_file()).download_as_bytearray());out=io.BytesIO();filename="result.txt"
 try:
  if selected in ("convert","pdf"):
   image=Image.open(io.BytesIO(raw));image=image.convert("RGB") if target in ("jpg","pdf") else image.convert("RGBA");image.thumbnail((1920,1920));savefmt={"jpg":"JPEG","png":"PNG","webp":"WEBP","pdf":"PDF"}[target];image.save(out,savefmt,quality=80,optimize=True);filename="result."+target
  elif selected=="text":
   reader=PdfReader(io.BytesIO(raw));out.write("\n\n".join((p.extract_text() or "") for p in reader.pages[:100]).encode());filename="extracted.txt"
  elif selected=="ocr":
   if not OCR_KEY:raise ValueError("Owner must add OCR_API_KEY in bot settings")
   async with httpx.AsyncClient(timeout=90) as client:r=await client.post("https://api.ocr.space/parse/image",headers={"apikey":OCR_KEY},files={"file":(getattr(obj,"file_name",None) or "image.png",raw)});r.raise_for_status();text="\n".join(x.get("ParsedText","") for x in r.json().get("ParsedResults",[]));out.write(text.encode());filename="ocr.txt"
  elif selected=="transcribe":
   if not AI_KEY:raise ValueError("Owner must add AI_API_KEY in bot settings")
   async with httpx.AsyncClient(timeout=120) as client:r=await client.post(AI_BASE+"/audio/transcriptions",headers={"Authorization":"Bearer "+AI_KEY},data={"model":"whisper-1"},files={"file":(getattr(obj,"file_name",None) or "audio.ogg",raw,getattr(obj,"mime_type",None) or "audio/ogg")});r.raise_for_status();out.write(r.json().get("text","").encode());filename="transcript.txt"
  out.seek(0);out.name=filename;await u.message.reply_document(out,caption="Processed in memory; the input was not retained.");used(uid)
 except Exception as e:await u.message.reply_text("Could not process: "+str(e)[:180])
async def qr(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if not c.args:return
 out=io.BytesIO();qrcode.make(" ".join(c.args)[:2000]).save(out,"PNG");out.seek(0);out.name="qr.png";await u.message.reply_document(out)
async def speak(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if not c.args:return
 if not AI_KEY:await u.message.reply_text("Owner must add AI_API_KEY in bot settings.");return
 if not quota(u.effective_user.id):await u.message.reply_text("Daily quota reached.");return
 text=" ".join(c.args)[:4000]
 try:
  async with httpx.AsyncClient(timeout=120) as client:r=await client.post(AI_BASE+"/audio/speech",headers={"Authorization":"Bearer "+AI_KEY},json={"model":"tts-1","voice":"alloy","input":text,"response_format":"mp3"});r.raise_for_status();out=io.BytesIO(r.content);out.name="speech.mp3";await u.message.reply_audio(out);used(u.effective_user.id)
 except Exception as e:await u.message.reply_text("Could not generate speech: "+str(e)[:180])
async def panel(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id==admin():await u.message.reply_text(f"Users {DB.execute('SELECT COUNT(*) FROM users').fetchone()[0]} · Jobs {DB.execute('SELECT COALESCE(SUM(used),0) FROM users').fetchone()[0]}")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
for cmd,fn in [("start",start),("mode",mode),("format",fmt),("qr",qr),("speak",speak),("panel",panel)]:app.add_handler(CommandHandler(cmd,fn))
app.add_handler(MessageHandler(filters.Document.ALL|filters.PHOTO|filters.VOICE|filters.AUDIO,process));app.run_polling()
'''


def support_ai_code():
    base = ai_code(
        "AI support, CRM & human inbox",
        "You are a business support agent. Use only approved policy. Never invent price, stock, discounts or guarantees. Escalate uncertain requests to a human.",
        "AI answers, FAQ rules, memory, human handoff, leads, quotas, analytics, bans and broadcasts.",
    )
    # The core AI product remains intentionally one-file; append visible feature
    # guidance to its start text rather than pretending separate products.
    return base.replace(
        'Send a message. /new clears memory · /usage shows quota.',
        'Send a message. /new clears memory · /usage shows quota. Owner: /setprompt /setlimit /broadcast /ban /panel.',
    )


def build_flagship_templates():
    ai_fields = [
        _opt("AI_API_KEY", "OpenAI-compatible API key"),
        _opt("AI_API_BASE", "API base", "https://api.openai.com/v1", secret=False),
        _opt("AI_MODEL", "Model", "gpt-4o-mini", secret=False),
    ]
    media_fields = [
        _opt("AI_API_KEY", "Speech API key"),
        _opt("AI_API_BASE", "OpenAI-compatible API base", "https://api.openai.com/v1", secret=False),
        _opt("OCR_API_KEY", "OCR.Space API key"),
    ]
    products = {
        "complete-group-manager": _flagship(
            "Complete group moderator",
            "One Rose-style bot for captcha, anti-flood, links, blocked words, warnings, timed mute, reports, bans and audit history.",
            "Community", moderator_code(), (),
            "Add it as group administrator, grant Delete/Restrict/Invite permissions, then /setup.",
            claim=False,
        ),
        "complete-channel-manager": _flagship(
            "Complete channel manager",
            "One channel bot for force-join, member approval, private invites, scheduled posts, auto-delete, broadcasts, content forwarding, tag remover, caption editing and inline buttons.",
            "Channels", channel_manager_code(), (),
            "Add it as channel administrator, open Go to bot, then /setchannel @channel.",
        ),
        "complete-referral-rewards": _flagship(
            "Complete referral & rewards",
            "One rewards bot for personal invite links, referral tracking, points balance, leaderboard, withdrawal requests and owner payout approvals.",
            "Rewards", referral_rewards_code(), (),
            "Open Go to bot and press Start to claim owner controls, then /setrate and /setmin.",
        ),
        "complete-commerce": _flagship(
            "Complete Telegram store",
            "One store bot with catalog, stock, cart, checkout, payment reference review, order history, buyer status notifications, support and sales analytics.",
            "Commerce", commerce_code("Complete Telegram store", "physical and digital products", ("Pending payment", "Payment review", "Confirmed", "Processing", "Delivered", "Cancelled")),
            [_opt("PAYMENT_URL", "bKash/Nagad/SSLCommerz checkout URL", secret=False)],
        ),
        "complete-file-share": _flagship(
            "Complete file share",
            "One file sharing bot with Telegram links, expiry dates, download limits, per-user link settings, revoke/delete and owner statistics.",
            "Files", file_share_code(), (),
            "Open Go to bot and press Start to claim owner controls, then /panel.",
        ),
        "complete-media-ai-converter": _flagship(
            "Complete media & AI converter",
            "One conversion bot for image compression, JPG/PNG/WebP/PDF conversion, image-to-PDF, PDF text, OCR, voice transcription, text-to-speech and QR codes.",
            "Media & AI", media_ai_code(), media_fields,
        ),
        "complete-ai-support": _flagship(
            "Complete AI business assistant",
            "One configurable AI support product with Bangla/Banglish, conversation memory, owner policy, quotas, analytics, bans and broadcasts.",
            "AI & Support", support_ai_code(), ai_fields,
        ),
    }
    return products
