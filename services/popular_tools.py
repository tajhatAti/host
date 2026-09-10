"""High-demand standalone Telegram tools: files, audio, feeds and moderation."""
from __future__ import annotations

CLAIM={"key":"ADMIN_CLAIM_CODE","type":"generated","label":"Secure admin connection","required":True,"help":"Generated automatically for the Go to bot admin link."}
def fld(key,label,secret=True,required=True,placeholder=""):return {"key":key,"type":"password" if secret else "text","label":label,"required":required,"placeholder":placeholder}
def product(name,desc,category,code,fields=(),badge="Top",priority=950,claim=True,after=""):
 return {"name":name,"description":desc,"category":category,"language":"python","framework":"python-telegram-bot","badge":badge,"priority":priority,"env_fields":([CLAIM] if claim else [])+list(fields),"after_deploy":after or "Open Go to bot and press Start. Use /panel for owner controls.","code":code.strip()+"\n"}


def file_share_code():
 return '''# requirements: python-telegram-bot==21.4
import os,secrets,sqlite3,time
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes,MessageHandler,filters
CLAIM=os.getenv("ADMIN_CLAIM_CODE","");DB=sqlite3.connect("file_share.db",check_same_thread=False);DB.execute("PRAGMA journal_mode=WAL");DB.executescript("CREATE TABLE IF NOT EXISTS settings(user_id INTEGER,key TEXT,value TEXT,PRIMARY KEY(user_id,key));CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,banned INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS files(code TEXT PRIMARY KEY,owner INTEGER,file_id TEXT,kind TEXT,name TEXT,size INTEGER,created INTEGER,expires INTEGER,max_downloads INTEGER,downloads INTEGER DEFAULT 0,active INTEGER DEFAULT 1);");DB.commit()
def cfg(uid,key,default):
 r=DB.execute("SELECT value FROM settings WHERE user_id=? AND key=?",(uid,key)).fetchone();return r[0] if r else default
def admin():
 r=DB.execute("SELECT value FROM settings WHERE user_id=0 AND key='admin'").fetchone();return int(r[0]) if r else 0
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES(0,'admin',?)",(str(uid),));DB.commit();await u.message.reply_text("Owner connected. File sharing is ready.");return
 DB.execute("INSERT OR IGNORE INTO users(id) VALUES(?)",(uid,));DB.commit()
 if c.args and c.args[0].startswith("f_"):await deliver(u,c,c.args[0][2:]);return
 await u.message.reply_text("Send a document, photo, video or audio. I will return a shareable Telegram link.\\n/files · /settings DAYS MAX_DOWNLOADS · /delete CODE")
def media(m):
 if m.document:return m.document,"document",m.document.file_name or "document"
 if m.video:return m.video,"video",m.video.file_name or "video.mp4"
 if m.audio:return m.audio,"audio",m.audio.file_name or "audio.mp3"
 if m.voice:return m.voice,"voice","voice.ogg"
 if m.photo:return m.photo[-1],"photo","photo.jpg"
 return None,None,None
async def save(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id;ban=DB.execute("SELECT banned FROM users WHERE id=?",(uid,)).fetchone()
 if ban and ban[0]:return
 obj,kind,name=media(u.message)
 if not obj:return
 days=max(1,min(365,int(cfg(uid,"days","30"))));limit=max(1,min(100000,int(cfg(uid,"downloads","1000"))));code=secrets.token_urlsafe(8).replace('-','').replace('_','')[:10];expires=int(time.time())+days*86400
 DB.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,0,1)",(code,uid,obj.file_id,kind,name[:200],getattr(obj,'file_size',0) or 0,int(time.time()),expires,limit));DB.commit();me=await c.bot.get_me();await u.message.reply_text(f"Saved: {name}\\nhttps://t.me/{me.username}?start=f_{code}\\nExpires: {days} days · Limit: {limit} downloads")
async def deliver(u,c,code):
 row=DB.execute("SELECT file_id,kind,name,expires,max_downloads,downloads,active FROM files WHERE code=?",(code,)).fetchone()
 if not row or not row[6] or row[3]<int(time.time()) or row[5]>=row[4]:await u.effective_message.reply_text("This link expired, reached its limit, or was removed.");return
 send={"document":c.bot.send_document,"video":c.bot.send_video,"audio":c.bot.send_audio,"voice":c.bot.send_voice,"photo":c.bot.send_photo}.get(row[1],c.bot.send_document);await send(u.effective_chat.id,row[0],caption=row[2]);DB.execute("UPDATE files SET downloads=downloads+1 WHERE code=?",(code,));DB.commit()
async def getfile(u,c):
 if c.args:await deliver(u,c,c.args[0])
async def files(u,c):
 rows=DB.execute("SELECT code,name,downloads,max_downloads,expires FROM files WHERE owner=? AND active=1 ORDER BY created DESC LIMIT 20",(u.effective_user.id,)).fetchall();await u.message.reply_text("\\n".join(f"{x} · {n} · {d}/{m} · expires {time.strftime('%Y-%m-%d',time.gmtime(e))}" for x,n,d,m,e in rows) if rows else "No active files.")
async def settings(u,c):
 if len(c.args)!=2 or not all(x.isdigit() for x in c.args):await u.message.reply_text("/settings DAYS MAX_DOWNLOADS");return
 days=max(1,min(365,int(c.args[0])));limit=max(1,min(100000,int(c.args[1])));DB.execute("INSERT OR REPLACE INTO settings VALUES(?,?,?)",(u.effective_user.id,"days",str(days)));DB.execute("INSERT OR REPLACE INTO settings VALUES(?,?,?)",(u.effective_user.id,"downloads",str(limit)));DB.commit();await u.message.reply_text("Future link limits updated.")
async def delete(u,c):
 if not c.args:return
 cur=DB.execute("UPDATE files SET active=0 WHERE code=? AND owner=?",(c.args[0],u.effective_user.id));DB.commit();await u.message.reply_text("Removed." if cur.rowcount else "File not found.")
async def panel(u,c):
 if u.effective_user.id!=admin():return
 users=DB.execute("SELECT COUNT(*) FROM users").fetchone()[0];files=DB.execute("SELECT COUNT(*) FROM files").fetchone()[0];downloads=DB.execute("SELECT COALESCE(SUM(downloads),0) FROM files").fetchone()[0];await u.message.reply_text(f"Users {users} · Files {files} · Downloads {downloads}")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
for x,h in [("start",start),("get",getfile),("files",files),("settings",settings),("delete",delete),("panel",panel)]:app.add_handler(CommandHandler(x,h))
app.add_handler(MessageHandler(filters.Document.ALL|filters.PHOTO|filters.VIDEO|filters.AUDIO|filters.VOICE,save));app.run_polling()
'''



def audio_code(mode):
 model_default="whisper-1" if mode=="stt" else "tts-1"
 return f'''# requirements: python-telegram-bot==21.4 httpx==0.27.2
import io,os,sqlite3,time
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes,MessageHandler,filters
MODE={mode!r};KEY=os.getenv("AUDIO_API_KEY","");BASE=os.getenv("AUDIO_API_BASE","https://api.openai.com/v1").rstrip("/");MODEL=os.getenv("AUDIO_MODEL",{model_default!r});CLAIM=os.getenv("ADMIN_CLAIM_CODE","")
DB=sqlite3.connect("audio_ai.db",check_same_thread=False);DB.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,used INTEGER DEFAULT 0,day TEXT DEFAULT '',voice TEXT DEFAULT 'alloy',banned INTEGER DEFAULT 0);");DB.commit()
def admin():
 r=DB.execute("SELECT value FROM settings WHERE key='admin'").fetchone();return int(r[0]) if r else 0
def quota(uid):
 row=DB.execute("SELECT used,day,banned FROM users WHERE id=?",(uid,)).fetchone();return not row or (not row[2] and (row[1]!=time.strftime('%Y-%m-%d') or row[0]<30 or uid==admin()))
def used(uid):
 today=time.strftime("%Y-%m-%d");DB.execute("UPDATE users SET used=CASE WHEN day=? THEN used+1 ELSE 1 END,day=? WHERE id=?",(today,today,uid));DB.commit()
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES('admin',?)",(str(uid),));DB.commit();await u.message.reply_text("Owner connected.");return
 DB.execute("INSERT OR IGNORE INTO users(id) VALUES(?)",(uid,));DB.commit();help_text="Send voice/audio up to 20 MB for transcription." if MODE=="stt" else "Send text up to 4000 characters. Use /voice alloy|echo|fable|onyx|nova|shimmer."
 await u.message.reply_text(help_text)
async def transcribe(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id;obj=u.message.voice or u.message.audio or u.message.document
 if MODE!="stt" or not obj:return
 if not quota(uid) or (obj.file_size or 0)>20*1024*1024:await u.message.reply_text("Quota reached, access restricted, or file is over 20 MB.");return
 if not KEY:await u.message.reply_text("Owner must configure AUDIO_API_KEY.");return
 f=await obj.get_file();raw=bytes(await f.download_as_bytearray());wait=await u.message.reply_text("Transcribing…")
 try:
  async with httpx.AsyncClient(timeout=120) as client:r=await client.post(BASE+"/audio/transcriptions",headers={{"Authorization":"Bearer "+KEY}},data={{"model":MODEL}},files={{"file":(getattr(obj,'file_name',None) or "audio.ogg",raw,getattr(obj,'mime_type',None) or "audio/ogg")}});r.raise_for_status();text=r.json().get("text","")
  await wait.edit_text(text[:4096] or "No speech detected.");used(uid)
 except httpx.HTTPStatusError as e:await wait.edit_text(f"Provider returned {{e.response.status_code}}. Check key, model and file format.")
 except Exception:await wait.edit_text("Transcription provider failed.")
async def speak(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if MODE!="tts" or not quota(uid):return
 text=u.message.text[:4000]
 if not KEY:await u.message.reply_text("Owner must configure AUDIO_API_KEY.");return
 voice=DB.execute("SELECT voice FROM users WHERE id=?",(uid,)).fetchone()[0];wait=await u.message.reply_text("Generating voice…")
 try:
  async with httpx.AsyncClient(timeout=120) as client:r=await client.post(BASE+"/audio/speech",headers={{"Authorization":"Bearer "+KEY}},json={{"model":MODEL,"voice":voice,"input":text,"response_format":"mp3"}});r.raise_for_status();data=r.content
  out=io.BytesIO(data);out.name="speech.mp3";await wait.delete();await u.message.reply_audio(out);used(uid)
 except httpx.HTTPStatusError as e:await wait.edit_text(f"Provider returned {{e.response.status_code}}. Check model and voice support.")
 except Exception:await wait.edit_text("Speech provider failed.")
async def voice(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if MODE!="tts" or not c.args:return
 value=c.args[0].lower();allowed={{"alloy","echo","fable","onyx","nova","shimmer"}}
 if value not in allowed:await u.message.reply_text("Choose: "+", ".join(sorted(allowed)));return
 DB.execute("UPDATE users SET voice=? WHERE id=?",(value,u.effective_user.id));DB.commit();await u.message.reply_text("Voice updated.")
async def panel(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin():return
 users,total=DB.execute("SELECT COUNT(*),COALESCE(SUM(used),0) FROM users").fetchone();await u.message.reply_text(f"Users: {{users}} · Completed jobs: {{total}}")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build();app.add_handler(CommandHandler("start",start));app.add_handler(CommandHandler("voice",voice));app.add_handler(CommandHandler("panel",panel));app.add_handler(MessageHandler(filters.VOICE|filters.AUDIO|filters.Document.AUDIO,transcribe));app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND,speak));app.run_polling()
'''


def converter_code():
 return '''# requirements: python-telegram-bot==21.4 Pillow==10.4.0 pypdf==4.3.1
import io,os,sqlite3
from PIL import Image
from pypdf import PdfReader
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes,MessageHandler,filters
CLAIM=os.getenv("ADMIN_CLAIM_CODE","");DB=sqlite3.connect("converter.db",check_same_thread=False);DB.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,format TEXT DEFAULT 'pdf',used INTEGER DEFAULT 0);");DB.commit()
def admin():
 r=DB.execute("SELECT value FROM settings WHERE key='admin'").fetchone();return int(r[0]) if r else 0
async def start(u,c):
 uid=u.effective_user.id
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES('admin',?)",(str(uid),));DB.commit();await u.message.reply_text("Owner connected.");return
 DB.execute("INSERT OR IGNORE INTO users(id) VALUES(?)",(uid,));DB.commit();await u.message.reply_text("Image & PDF converter\\n/format jpg|png|webp|pdf|text, then send an image or PDF up to 20 MB.")
async def fmt(u,c):
 if not c.args or c.args[0].lower() not in ("jpg","png","webp","pdf","text"):return
 DB.execute("UPDATE users SET format=? WHERE id=?",(c.args[0].lower(),u.effective_user.id));DB.commit();await u.message.reply_text("Output format updated.")
async def convert(u,c):
 obj=u.message.document or (u.message.photo[-1] if u.message.photo else None)
 if not obj or (obj.file_size or 0)>20*1024*1024:await u.message.reply_text("Send a supported file up to 20 MB.");return
 f=await obj.get_file();raw=bytes(await f.download_as_bytearray());target=DB.execute("SELECT format FROM users WHERE id=?",(u.effective_user.id,)).fetchone()[0]
 try:
  out=io.BytesIO()
  if target=="text":
   reader=PdfReader(io.BytesIO(raw));out.write("\\n\\n".join((p.extract_text() or "") for p in reader.pages[:100]).encode());name="document.txt"
  else:
   image=Image.open(io.BytesIO(raw));image=image.convert("RGB") if target in ("jpg","pdf") else image.convert("RGBA");savefmt={"jpg":"JPEG","png":"PNG","webp":"WEBP","pdf":"PDF"}[target];image.thumbnail((4096,4096));image.save(out,savefmt,quality=88,optimize=True);name="converted."+target
  out.seek(0);out.name=name;await u.message.reply_document(out,caption="Converted in memory; the input was not retained.");DB.execute("UPDATE users SET used=used+1 WHERE id=?",(u.effective_user.id,));DB.commit()
 except Exception:await u.message.reply_text("That input/output combination is not supported.")
async def panel(u,c):
 if u.effective_user.id==admin():await u.message.reply_text(f"Users: {DB.execute('SELECT COUNT(*) FROM users').fetchone()[0]} · Conversions: {DB.execute('SELECT COALESCE(SUM(used),0) FROM users').fetchone()[0]}")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build();app.add_handler(CommandHandler("start",start));app.add_handler(CommandHandler("format",fmt));app.add_handler(CommandHandler("panel",panel));app.add_handler(MessageHandler(filters.Document.ALL|filters.PHOTO,convert));app.run_polling()
'''


def rss_code():
 return '''# requirements: python-telegram-bot[job-queue]==21.4 feedparser==6.0.11 httpx==0.27.2
import asyncio,ipaddress,os,socket,sqlite3,time,urllib.parse
import feedparser,httpx
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes
CLAIM=os.getenv("ADMIN_CLAIM_CODE","");DB=sqlite3.connect("feeds.db",check_same_thread=False);DB.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS feeds(id INTEGER PRIMARY KEY AUTOINCREMENT,url TEXT UNIQUE,target TEXT,last_id TEXT,active INTEGER DEFAULT 1,failures INTEGER DEFAULT 0,last_check INTEGER DEFAULT 0);");DB.commit()
def admin():
 r=DB.execute("SELECT value FROM settings WHERE key='admin'").fetchone();return int(r[0]) if r else 0
def safe_url(url):
 p=urllib.parse.urlparse(url)
 if p.scheme not in ("http","https") or not p.hostname:return False
 try:
  for x in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM):
   ip=ipaddress.ip_address(x[4][0])
   if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:return False
  return True
 except Exception:return False
async def start(u,c):
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES('admin',?)",(str(u.effective_user.id),));DB.commit();await u.message.reply_text("Feed owner connected.");return
 await u.message.reply_text("RSS/Atom → Telegram publisher. Owner: /addfeed URL @channel · /feeds · /removefeed ID · /checkfeeds")
async def add(u,c):
 if u.effective_user.id!=admin() or len(c.args)<2:return
 url,target=c.args[0],c.args[1]
 if not safe_url(url):await u.message.reply_text("Only public HTTP(S) feed URLs are allowed.");return
 me=await c.bot.get_chat_member(target,c.bot.id)
 if me.status not in ("administrator","creator"):await u.message.reply_text("Make the bot channel administrator first.");return
 DB.execute("INSERT OR IGNORE INTO feeds(url,target,last_id) VALUES(?,?,'')",(url,target));DB.commit();await u.message.reply_text("Feed connected.")
async def poll(c:ContextTypes.DEFAULT_TYPE):
 for fid,url,target,last_id in DB.execute("SELECT id,url,target,last_id FROM feeds WHERE active=1").fetchall():
  try:
   async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:response=await client.get(url,headers={"User-Agent":"CodeNestFeedBot/1.0"});response.raise_for_status()
   parsed=feedparser.parse(response.content);entries=parsed.entries[:10]
   fresh=[]
   for e in entries:
    eid=e.get('id') or e.get('link') or e.get('title')
    if eid==last_id:break
    fresh.append(e)
   for e in reversed(fresh):await c.bot.send_message(target,f"{e.get('title','New update')}\\n{e.get('link','')}",disable_web_page_preview=False);await asyncio.sleep(.05)
   if entries:DB.execute("UPDATE feeds SET last_id=?,failures=0,last_check=? WHERE id=?",(entries[0].get('id') or entries[0].get('link') or entries[0].get('title'),int(time.time()),fid))
  except Exception:DB.execute("UPDATE feeds SET failures=failures+1,last_check=? WHERE id=?",(int(time.time()),fid))
 DB.commit()
async def feeds(u,c):
 if u.effective_user.id!=admin():return
 rows=DB.execute("SELECT id,url,target,failures FROM feeds WHERE active=1").fetchall();await u.message.reply_text("\\n".join(f"#{i} {target} · failures {f}\\n{url}" for i,url,target,f in rows) if rows else "No feeds.")
async def remove(u,c):
 if u.effective_user.id==admin() and c.args and c.args[0].isdigit():DB.execute("UPDATE feeds SET active=0 WHERE id=?",(int(c.args[0]),));DB.commit();await u.message.reply_text("Feed removed.")
async def check(u,c):
 if u.effective_user.id==admin():await poll(c);await u.message.reply_text("Feed check complete.")
async def ready(app):app.job_queue.run_repeating(poll,300,first=10)
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).post_init(ready).build()
for x,h in [("start",start),("addfeed",add),("feeds",feeds),("removefeed",remove),("checkfeeds",check)]:app.add_handler(CommandHandler(x,h))
app.run_polling()
'''


def moderator_code():
 return '''# requirements: python-telegram-bot[job-queue]==21.4
import os,sqlite3,time
from collections import defaultdict,deque
from telegram import ChatPermissions,InlineKeyboardButton,InlineKeyboardMarkup,Update
from telegram.ext import ApplicationBuilder,CallbackQueryHandler,ChatMemberHandler,CommandHandler,ContextTypes,MessageHandler,filters
DB=sqlite3.connect("moderator.db",check_same_thread=False);DB.executescript("CREATE TABLE IF NOT EXISTS config(chat INTEGER,key TEXT,value TEXT,PRIMARY KEY(chat,key));CREATE TABLE IF NOT EXISTS warns(chat INTEGER,user INTEGER,count INTEGER DEFAULT 0,PRIMARY KEY(chat,user));CREATE TABLE IF NOT EXISTS captcha(chat INTEGER,user INTEGER,answer INTEGER,expires INTEGER,PRIMARY KEY(chat,user));CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,chat INTEGER,user INTEGER,action TEXT,created INTEGER);");DB.commit();FLOOD=defaultdict(lambda:deque(maxlen=12))
def cfg(chat,key,default=""):
 r=DB.execute("SELECT value FROM config WHERE chat=? AND key=?",(chat,key)).fetchone();return r[0] if r else default
async def adm(u,c):
 if u.effective_chat.type=="private":return False
 m=await c.bot.get_chat_member(u.effective_chat.id,u.effective_user.id);return m.status in ("administrator","creator")
async def setup(u,c):
 if not await adm(u,c):return
 DB.execute("INSERT OR REPLACE INTO config VALUES(?,?,'1')",(u.effective_chat.id,"enabled"));DB.commit();await u.message.reply_text("Protection enabled. Grant Delete messages, Restrict users and Invite users permissions.")
async def setwords(u,c):
 if await adm(u,c):DB.execute("INSERT OR REPLACE INTO config VALUES(?,?,?)",(u.effective_chat.id,"words",",".join(x.lower() for x in c.args)[:2000]));DB.commit();await u.message.reply_text("Blocked phrases updated.")
async def newcomer(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if not u.chat_member or u.chat_member.new_chat_member.status not in ("member","restricted"):return
 chat=u.effective_chat.id;user=u.chat_member.new_chat_member.user
 if user.is_bot:return
 a,b=__import__('secrets').randbelow(8)+1,__import__('secrets').randbelow(8)+1;DB.execute("INSERT OR REPLACE INTO captcha VALUES(?,?,?,?)",(chat,user.id,a+b,int(time.time())+120));DB.commit();await c.bot.restrict_chat_member(chat,user.id,ChatPermissions(can_send_messages=False));await c.bot.send_message(chat,f"{user.mention_html()} verify: {a}+{b}=?",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(str(x),callback_data=f"cap:{user.id}:{x}") for x in (a+b,a+b+1,a+b-1)]]))
async def captcha(u,c):
 q=u.callback_query;_,raw_uid,raw_answer=q.data.split(':');uid=int(raw_uid)
 if q.from_user.id!=uid:await q.answer("This check belongs to another member.",show_alert=True);return
 row=DB.execute("SELECT answer,expires FROM captcha WHERE chat=? AND user=?",(q.message.chat.id,uid)).fetchone()
 if not row or row[1]<int(time.time()) or int(raw_answer)!=row[0]:await q.answer("Incorrect or expired.",show_alert=True);return
 await c.bot.restrict_chat_member(q.message.chat.id,uid,ChatPermissions.all_permissions());DB.execute("DELETE FROM captcha WHERE chat=? AND user=?",(q.message.chat.id,uid));DB.commit();await q.edit_message_text("Verified.")
async def setlimit(u,c):
 if await adm(u,c) and c.args and c.args[0].isdigit():DB.execute("INSERT OR REPLACE INTO config VALUES(?,?,?)",(u.effective_chat.id,"flood",str(max(3,min(12,int(c.args[0]))))));DB.commit();await u.message.reply_text("Flood limit updated.")
async def setrules(u,c):
 if await adm(u,c) and c.args:DB.execute("INSERT OR REPLACE INTO config VALUES(?,?,?)",(u.effective_chat.id,"rules"," ".join(c.args)[:3500]));DB.commit();await u.message.reply_text("Rules saved.")
async def rules(u,c):await u.message.reply_text(cfg(u.effective_chat.id,"rules","No rules configured."))
async def warn(u,c):
 if not await adm(u,c) or not u.message.reply_to_message:return
 target=u.message.reply_to_message.from_user;chat=u.effective_chat.id;DB.execute("INSERT OR IGNORE INTO warns VALUES(?,?,0)",(chat,target.id));DB.execute("UPDATE warns SET count=count+1 WHERE chat=? AND user=?",(chat,target.id));count=DB.execute("SELECT count FROM warns WHERE chat=? AND user=?",(chat,target.id)).fetchone()[0];DB.execute("INSERT INTO audit(chat,user,action,created) VALUES(?,?,?,?)",(chat,target.id,"manual warning",int(time.time())));DB.commit();await u.message.reply_text(f"Warning {count}/3 for {target.first_name}")
async def mute(u,c):
 if not await adm(u,c) or not u.message.reply_to_message:return
 target=u.message.reply_to_message.from_user;minutes=max(1,min(10080,int(c.args[0]) if c.args and c.args[0].isdigit() else 60));await c.bot.restrict_chat_member(u.effective_chat.id,target.id,ChatPermissions(can_send_messages=False),until_date=int(time.time())+minutes*60);DB.execute("INSERT INTO audit(chat,user,action,created) VALUES(?,?,?,?)",(u.effective_chat.id,target.id,f"mute {minutes}m",int(time.time())));DB.commit();await u.message.reply_text("Member muted.")
async def ban(u,c):
 if not await adm(u,c) or not u.message.reply_to_message:return
 target=u.message.reply_to_message.from_user;await c.bot.ban_chat_member(u.effective_chat.id,target.id);DB.execute("INSERT INTO audit(chat,user,action,created) VALUES(?,?,?,?)",(u.effective_chat.id,target.id,"ban",int(time.time())));DB.commit();await u.message.reply_text("Member banned.")
async def unban(u,c):
 if await adm(u,c) and c.args and c.args[0].isdigit():await c.bot.unban_chat_member(u.effective_chat.id,int(c.args[0]));await u.message.reply_text("Member unbanned.")
async def lock(u,c):
 if await adm(u,c):await c.bot.set_chat_permissions(u.effective_chat.id,ChatPermissions(can_send_messages=False));await u.message.reply_text("Chat locked.")
async def unlock(u,c):
 if await adm(u,c):await c.bot.set_chat_permissions(u.effective_chat.id,ChatPermissions.all_permissions());await u.message.reply_text("Chat unlocked.")
async def stats(u,c):
 if not await adm(u,c):return
 warns=DB.execute("SELECT COALESCE(SUM(count),0) FROM warns WHERE chat=?",(u.effective_chat.id,)).fetchone()[0];actions=DB.execute("SELECT COUNT(*) FROM audit WHERE chat=?",(u.effective_chat.id,)).fetchone()[0];await u.message.reply_text(f"Warnings: {warns} · Moderation actions: {actions}")
async def inspect(u,c):
 if not u.message or u.effective_chat.type=="private" or cfg(u.effective_chat.id,"enabled")!="1":return
 m=await c.bot.get_chat_member(u.effective_chat.id,u.effective_user.id)
 if m.status in ("administrator","creator"):return
 text=(u.message.text or u.message.caption or "").lower();words=[x for x in cfg(u.effective_chat.id,"words").split(',') if x];q=FLOOD[(u.effective_chat.id,u.effective_user.id)];q.append(time.time());bad=any(x in text for x in words) or (('http://' in text or 'https://' in text or 't.me/' in text) and cfg(u.effective_chat.id,"links","0")=='1') or (len(q)>=int(cfg(u.effective_chat.id,"flood","6")) and q[-1]-q[-int(cfg(u.effective_chat.id,"flood","6"))]<8)
 if not bad:return
 try:await u.message.delete()
 except Exception:return
 chat,uid=u.effective_chat.id,u.effective_user.id;DB.execute("INSERT OR IGNORE INTO warns VALUES(?,?,0)",(chat,uid));DB.execute("UPDATE warns SET count=count+1 WHERE chat=? AND user=?",(chat,uid));count=DB.execute("SELECT count FROM warns WHERE chat=? AND user=?",(chat,uid)).fetchone()[0];DB.execute("INSERT INTO audit(chat,user,action,created) VALUES(?,?,?,?)",(chat,uid,"automatic warning",int(time.time())));DB.commit()
 if count>=3:await c.bot.restrict_chat_member(chat,uid,ChatPermissions(can_send_messages=False),until_date=int(time.time())+3600);await c.bot.send_message(chat,f"User {uid} muted for one hour after 3 warnings.")
async def links(u,c):
 if await adm(u,c) and c.args and c.args[0] in ("on","off"):DB.execute("INSERT OR REPLACE INTO config VALUES(?,?,?)",(u.effective_chat.id,"links","1" if c.args[0]=="on" else "0"));DB.commit();await u.message.reply_text("Link guard updated.")
async def report(u,c):
 if not u.message.reply_to_message:return
 for a in await c.bot.get_chat_administrators(u.effective_chat.id):
  if not a.user.is_bot:
   try:await c.bot.send_message(a.user.id,f"Report in {u.effective_chat.title}: message {u.message.reply_to_message.message_id} by user {u.message.reply_to_message.from_user.id}")
   except Exception:pass
 await u.message.reply_text("Report sent to administrators.")
async def audit(u,c):
 if not await adm(u,c):return
 rows=DB.execute("SELECT user,action,created FROM audit WHERE chat=? ORDER BY id DESC LIMIT 20",(u.effective_chat.id,)).fetchall();await u.message.reply_text("\\n".join(f"{x} · {a} · {time.strftime('%Y-%m-%d %H:%M',time.gmtime(t))}" for x,a,t in rows) or "No actions.")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
for x,h in [("setup",setup),("setwords",setwords),("setlimit",setlimit),("setrules",setrules),("rules",rules),("warn",warn),("mute",mute),("ban",ban),("unban",unban),("lock",lock),("unlock",unlock),("stats",stats),("links",links),("report",report),("audit",audit)]:app.add_handler(CommandHandler(x,h))
app.add_handler(CallbackQueryHandler(captcha,pattern="^cap:"));app.add_handler(ChatMemberHandler(newcomer,ChatMemberHandler.CHAT_MEMBER));app.add_handler(MessageHandler((filters.TEXT|filters.PHOTO|filters.VIDEO|filters.Document.ALL)&~filters.COMMAND,inspect));app.run_polling(allowed_updates=Update.ALL_TYPES)
'''


def build_popular_tools():
 audio_fields=[fld("AUDIO_API_KEY","Speech provider API key"),fld("AUDIO_API_BASE","OpenAI-compatible audio API base",False,True,"https://api.openai.com/v1"),fld("AUDIO_MODEL","Audio model",False,True)]
 return {
  "file-share-pro":product("File sharing and deep-link storage","Telegram file_id storage, expiring share links, download limits, owner library, revocation and usage analytics.","Files",file_share_code(),priority=990),
  "voice-to-text-pro":product("Voice to text transcription","Voice/audio transcription through an OpenAI-compatible API with 20 MB limits, daily quotas and provider error handling.","AI Audio",audio_code("stt"),audio_fields,priority=985),
  "text-to-voice-pro":product("Text to voice studio","OpenAI-compatible text-to-speech with selectable voices, MP3 output, daily quotas and usage analytics.","AI Audio",audio_code("tts"),audio_fields,priority=984),
  "universal-converter-pro":product("Image and PDF converter","JPG, PNG, WebP, image-to-PDF and PDF-to-text conversion in memory with no file retention.","Files",converter_code(),priority=982),
  "rss-channel-publisher":product("RSS/Atom channel publisher","Secure public-feed validation, multi-feed channel publishing, duplicate prevention, restart-safe scheduling and failure counters.","Automation",rss_code(),priority=980),
  "rose-style-moderator":product("Advanced group moderation","New-member captcha, anti-flood, link and phrase filters, escalating warnings, timed mute, reports and audit history.","Groups",moderator_code(),claim=False,priority=988,after="Add the bot as group administrator, grant moderation permissions, then send /setup."),
 }
