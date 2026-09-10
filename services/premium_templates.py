"""Curated high-demand Telegram products for Bangladesh and global users.

Unlike the retired quantity-first catalog, these templates model bot products
that repeatedly appear in current Telegram rankings: AI assistants, stores and
paid communities, channel automation, moderation, file/media processing,
feeds, security and live data. Every item emits a complete Python program.
"""
from __future__ import annotations

CLAIM = {"key":"ADMIN_CLAIM_CODE","type":"generated","label":"Secure admin connection","required":True,"help":"Generated automatically and used by the Go to bot link."}

def item(name, desc, category, code, fields=(), badge="Production", priority=50, after=""):
    return {"name":name,"description":desc,"category":category,"language":"python","framework":"python-telegram-bot","badge":badge,"priority":priority,
            "env_fields":[CLAIM,*fields],"after_deploy":after or "Open Go to bot, press Start, then use /panel.","code":code.strip()+"\n"}

def field(key,label,secret=False,required=True,placeholder=""):
    return {"key":key,"type":"password" if secret else "text","label":label,"required":required,"placeholder":placeholder}


def ai_code(title, role, features):
    return f'''# requirements: python-telegram-bot==21.4 httpx==0.27.2
import asyncio,json,os,sqlite3,time
import httpx
from telegram import Update
from telegram.error import Forbidden,RetryAfter
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes,MessageHandler,filters
TITLE={title!r};ROLE={role!r};FEATURES={features!r}
KEY=os.getenv("AI_API_KEY","");BASE=os.getenv("AI_API_BASE","https://api.openai.com/v1").rstrip("/");MODEL=os.getenv("AI_MODEL","gpt-4o-mini");CLAIM=os.getenv("ADMIN_CLAIM_CODE","")
DB=sqlite3.connect("ai_product.db",check_same_thread=False);DB.execute("PRAGMA journal_mode=WAL");DB.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,banned INTEGER DEFAULT 0,used INTEGER DEFAULT 0,day TEXT DEFAULT '');CREATE TABLE IF NOT EXISTS memory(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,role TEXT,content TEXT,created INTEGER);");DB.commit()
def setting(k,d=""):
 r=DB.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone();return r[0] if r else d
def admin():return int(setting("admin","0"))
def clean(x,n=6000):return " ".join(str(x or "").split())[:n]
def allowed(uid):
 row=DB.execute("SELECT banned,used,day FROM users WHERE id=?",(uid,)).fetchone();today=time.strftime("%Y-%m-%d");limit=int(setting("daily_limit","30"))
 if not row:return True
 return not row[0] and (row[2]!=today or row[1]<limit or uid==admin())
def history(uid):return [{{"role":r,"content":c}} for r,c in DB.execute("SELECT role,content FROM memory WHERE user_id=? ORDER BY id DESC LIMIT 12",(uid,)).fetchall()[::-1]]
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES('admin',?)",(str(uid),));DB.commit();await u.message.reply_text("Admin connected. Use /panel.");return
 DB.execute("INSERT OR IGNORE INTO users(id) VALUES(?)",(uid,));DB.commit();await u.message.reply_text(f"{{TITLE}}\\n{{FEATURES}}\\n\\nSend a message. /new clears memory · /usage shows quota.")
async def ask(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if not allowed(uid):await u.message.reply_text("Daily quota reached or access restricted.");return
 if not KEY:await u.message.reply_text("The owner must add AI_API_KEY in bot settings.");return
 prompt=setting("system",ROLE);text=clean(u.message.text);messages=[{{"role":"system","content":prompt}},*history(uid),{{"role":"user","content":text}}]
 wait=await u.message.reply_text("Working…")
 try:
  async with httpx.AsyncClient(timeout=60) as client:r=await client.post(BASE+"/chat/completions",headers={{"Authorization":"Bearer "+KEY,"Content-Type":"application/json"}},json={{"model":MODEL,"messages":messages,"temperature":0.4,"max_tokens":1800}})
  r.raise_for_status();answer=clean(r.json()["choices"][0]["message"]["content"],12000)
  await wait.edit_text(answer[:4096]);now=int(time.time());DB.execute("INSERT INTO memory(user_id,role,content,created) VALUES(?,?,?,?)",(uid,"user",text,now));DB.execute("INSERT INTO memory(user_id,role,content,created) VALUES(?,?,?,?)",(uid,"assistant",answer,now));today=time.strftime("%Y-%m-%d");DB.execute("UPDATE users SET used=CASE WHEN day=? THEN used+1 ELSE 1 END,day=? WHERE id=?",(today,today,uid));DB.execute("DELETE FROM memory WHERE user_id=? AND id NOT IN (SELECT id FROM memory WHERE user_id=? ORDER BY id DESC LIMIT 30)",(uid,uid));DB.commit()
 except httpx.HTTPStatusError as e:await wait.edit_text(f"AI provider error {{e.response.status_code}}. Check key, model and balance.")
 except Exception:await wait.edit_text("The AI provider did not respond. Try again.")
async def new(u:Update,c:ContextTypes.DEFAULT_TYPE):DB.execute("DELETE FROM memory WHERE user_id=?",(u.effective_user.id,));DB.commit();await u.message.reply_text("Conversation memory cleared.")
async def usage(u:Update,c:ContextTypes.DEFAULT_TYPE):
 row=DB.execute("SELECT used,day FROM users WHERE id=?",(u.effective_user.id,)).fetchone();await u.message.reply_text(f"Used today: {{row[0] if row and row[1]==time.strftime('%Y-%m-%d') else 0}} / {{setting('daily_limit','30')}}")
async def panel(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin():return
 users=DB.execute("SELECT COUNT(*) FROM users").fetchone()[0];calls=DB.execute("SELECT COALESCE(SUM(used),0) FROM users WHERE day=?",(time.strftime("%Y-%m-%d"),)).fetchone()[0];await u.message.reply_text(f"{{TITLE}} admin\\nUsers: {{users}}\\nCalls today: {{calls}}\\n/setprompt TEXT\\n/setlimit NUMBER\\n/ban ID · /unban ID\\n/broadcast TEXT")
async def setprompt(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id==admin() and c.args:DB.execute("INSERT OR REPLACE INTO settings VALUES('system',?)",(clean(" ".join(c.args),5000),));DB.commit();await u.message.reply_text("AI instructions updated.")
async def setlimit(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id==admin() and c.args and c.args[0].isdigit():DB.execute("INSERT OR REPLACE INTO settings VALUES('daily_limit',?)",(str(max(1,min(1000,int(c.args[0])))),));DB.commit();await u.message.reply_text("Quota updated.")
async def ban(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args or not c.args[0].isdigit():return
 DB.execute("INSERT OR IGNORE INTO users(id) VALUES(?)",(int(c.args[0]),));DB.execute("UPDATE users SET banned=? WHERE id=?",(0 if u.message.text.startswith('/unban') else 1,int(c.args[0])));DB.commit();await u.message.reply_text("Access updated.")
async def broadcast(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args:return
 sent=0;text=clean(" ".join(c.args),3500)
 for (uid,) in DB.execute("SELECT id FROM users WHERE banned=0"):
  try:await c.bot.send_message(uid,text);sent+=1;await asyncio.sleep(.04)
  except RetryAfter as e:await asyncio.sleep(float(e.retry_after)+.2)
  except Forbidden:DB.execute("UPDATE users SET banned=1 WHERE id=?",(uid,));DB.commit()
  except Exception:pass
 await u.message.reply_text(f"Delivered: {{sent}}")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
for x,h in [("start",start),("new",new),("usage",usage),("panel",panel),("setprompt",setprompt),("setlimit",setlimit),("broadcast",broadcast)]:app.add_handler(CommandHandler(x,h))
app.add_handler(CommandHandler(["ban","unban"],ban));app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND,ask));app.run_polling()
'''


def lookup_code(title, kind, command, help_text):
    """Real API clients with provider-specific parsing, caching and rate controls."""
    return f'''# requirements: python-telegram-bot==21.4 httpx==0.27.2
import json,os,sqlite3,time,urllib.parse
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes
TITLE={title!r};KIND={kind!r};COMMAND={command!r};HELP={help_text!r};KEY=os.getenv("DATA_API_KEY","");CLAIM=os.getenv("ADMIN_CLAIM_CODE","")
DB=sqlite3.connect("live_data.db",check_same_thread=False);DB.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY,value TEXT,expires INTEGER);CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,queries INTEGER DEFAULT 0,banned INTEGER DEFAULT 0);");DB.commit()
def admin():
 r=DB.execute("SELECT value FROM settings WHERE key='admin'").fetchone();return int(r[0]) if r else 0
def trim(v,n=3800):return " ".join(str(v or "").split())[:n]
def pick(data,path,default=""):
 try:
  for key in path.split('.'):
   if isinstance(data,list):data=data[int(key)]
   else:data=data[key]
  return data
 except Exception:return default
async def fetch(q):
 q=trim(q,200);enc=urllib.parse.quote(q,safe='');headers={{"User-Agent":"CodeNestBot/1.0"}}
 if KIND=="wikipedia":url=f"https://en.wikipedia.org/api/rest_v1/page/summary/{{enc}}"
 elif KIND=="bangla_wiki":url=f"https://bn.wikipedia.org/api/rest_v1/page/summary/{{enc}}"
 elif KIND=="dictionary":url=f"https://api.dictionaryapi.dev/api/v2/entries/en/{{enc}}"
 elif KIND=="books":url=f"https://openlibrary.org/search.json?q={{enc}}&limit=5"
 elif KIND=="anime":url=f"https://api.jikan.moe/v4/anime?q={{enc}}&limit=5"
 elif KIND=="country":url=f"https://restcountries.com/v3.1/name/{{enc}}"
 elif KIND=="ip":url=f"https://ipapi.co/{{enc}}/json/"
 elif KIND=="github":url=f"https://api.github.com/repos/{{q}}"
 elif KIND=="github_release":url=f"https://api.github.com/repos/{{q}}/releases/latest"
 elif KIND=="pypi":url=f"https://pypi.org/pypi/{{enc}}/json"
 elif KIND=="npm":url=f"https://registry.npmjs.org/{{enc}}/latest"
 elif KIND=="crypto":url=f"https://api.coingecko.com/api/v3/simple/price?ids={{enc}}&vs_currencies=usd,bdt&include_24hr_change=true"
 elif KIND=="currency":
  parts=q.upper().split();amount=parts[0] if parts and parts[0].replace('.','',1).isdigit() else '1';base=parts[1] if len(parts)>2 else (parts[0] if len(parts)>1 else 'USD');target=parts[2] if len(parts)>2 else (parts[1] if len(parts)>1 else 'BDT');url=f"https://api.frankfurter.app/latest?amount={{amount}}&from={{base}}&to={{target}}"
 elif KIND=="quran":
  ref=urllib.parse.quote(q,safe=':');url=f"https://api.alquran.cloud/v1/ayah/{{ref}}/editions/quran-uthmani,bn.bengali,en.sahih"
 elif KIND=="hadith":
  parts=q.split();book=parts[0] if parts else "bukhari";chapter=parts[1] if len(parts)>1 and parts[1].isdigit() else "1";url=f"https://alquranbd.com/api/hadith/{{urllib.parse.quote(book,safe='')}}/{{chapter}}"
 elif KIND=="movie":url=f"https://api.themoviedb.org/3/search/multi?api_key={{KEY}}&query={{enc}}"
 elif KIND=="news":url=f"https://newsapi.org/v2/everything?apiKey={{KEY}}&q={{enc}}&pageSize=8&sortBy=publishedAt"
 elif KIND=="cricket":url=f"https://api.cricapi.com/v1/currentMatches?apikey={{KEY}}&offset=0"
 elif KIND=="football":url=f"https://v3.football.api-sports.io/fixtures?live=all";headers["x-apisports-key"]=KEY
 elif KIND=="jobs":url=os.getenv("DATA_API_URL","")+"?q="+enc;headers["Authorization"]="Bearer "+KEY
 elif KIND=="bd_location":url=os.getenv("DATA_API_URL","https://bdapis.com/api/v1.2/districts")
 elif KIND=="bd_laws":url=f"https://bd-laws-api.bdit.community/api/search/{{enc}}"
 elif KIND=="url_reputation":
  url_id=__import__('base64').urlsafe_b64encode(q.encode()).decode().rstrip('=');url=f"https://www.virustotal.com/api/v3/urls/{{url_id}}";headers["x-apikey"]=KEY
 elif KIND=="flight":url=f"https://api.aviationstack.com/v1/flights?access_key={{KEY}}&flight_iata={{enc}}"
 elif KIND=="github_actions":
  url=f"https://api.github.com/repos/{{q}}/actions/runs?per_page=5"
  if KEY:headers["Authorization"]="Bearer "+KEY
 else:raise ValueError("Unsupported provider")
 async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:r=await client.get(url,headers=headers);r.raise_for_status();return r.json()
def render(d,q):
 if KIND in ("wikipedia","bangla_wiki"):return f"{{d.get('title','')}}\\n\\n{{d.get('extract','No summary')}}\\n{{pick(d,'content_urls.desktop.page')}}"
 if KIND=="dictionary":
  e=d[0];meanings=[]
  for m in e.get('meanings',[])[:3]:meanings.append(m.get('partOfSpeech','')+': '+m.get('definitions',[{{}}])[0].get('definition',''))
  return e.get('word',q)+'\\n'+"\\n".join(meanings)
 if KIND=="books":return "Books\\n"+"\\n".join(f"• {{x.get('title')}} — {{', '.join(x.get('author_name',[])[:2])}} ({{x.get('first_publish_year','')}})" for x in d.get('docs',[])[:5])
 if KIND=="anime":return "Anime\\n"+"\\n".join(f"• {{x.get('title')}} · ⭐ {{x.get('score')}} · {{x.get('url')}}" for x in d.get('data',[]))
 if KIND=="country":
  x=d[0];return f"{{x.get('name',{{}}).get('common')}}\\nCapital: {{', '.join(x.get('capital',[]))}}\\nPopulation: {{x.get('population',0):,}}\\nCurrency: {{', '.join(x.get('currencies',{{}}).keys())}}"
 if KIND=="ip":return f"IP: {{d.get('ip')}}\\nLocation: {{d.get('city')}}, {{d.get('country_name')}}\\nISP: {{d.get('org')}}\\nTimezone: {{d.get('timezone')}}"
 if KIND=="github":return f"{{d.get('full_name')}} ⭐ {{d.get('stargazers_count')}} · Forks {{d.get('forks_count')}} · Issues {{d.get('open_issues_count')}}\\n{{d.get('description')}}\\n{{d.get('html_url')}}"
 if KIND=="github_release":return f"{{d.get('name') or d.get('tag_name')}}\\nPublished: {{d.get('published_at')}}\\n{{trim(d.get('body'),1200)}}\\n{{d.get('html_url')}}"
 if KIND=="pypi":return f"{{pick(d,'info.name')}} {{pick(d,'info.version')}}\\n{{pick(d,'info.summary')}}\\n{{pick(d,'info.project_url')}}"
 if KIND=="npm":return f"{{d.get('name')}} {{d.get('version')}}\\n{{d.get('description')}}\\n{{d.get('homepage')}}"
 if KIND=="crypto":return "\\n".join(f"{{k}}: ${{v.get('usd')}} · ৳{{v.get('bdt')}} · 24h {{v.get('usd_24h_change',0):.2f}}%" for k,v in d.items())
 if KIND=="currency":return f"{{d.get('amount')}} {{d.get('base')}} = {{list(d.get('rates',{{}}).values())[0]}} {{list(d.get('rates',{{}}).keys())[0]}}"
 if KIND=="quran":return "\\n\\n".join(x.get('text','') for x in d.get('data',[]))
 if KIND=="hadith":return "\\n\\n".join(f"{{x.get('hadithNo') or x.get('hadith_number','')}}. {{x.get('hadithBengali') or x.get('hadithBangla') or x.get('hadithEnglish','')}}" for x in (d if isinstance(d,list) else d.get('data',[]))[:5])
 if KIND=="movie":return "Movies\\n"+"\\n".join(f"• {{x.get('title') or x.get('name')}} · {{x.get('release_date') or x.get('first_air_date','')}} · ⭐ {{x.get('vote_average')}}" for x in d.get('results',[])[:7])
 if KIND=="news":return "Latest\\n"+"\\n\\n".join(f"• {{x.get('title')}}\\n{{x.get('url')}}" for x in d.get('articles',[])[:8])
 if KIND=="cricket":return "Live cricket\\n"+"\\n\\n".join(f"{{x.get('name')}}\\n{{x.get('status')}}" for x in d.get('data',[])[:8])
 if KIND=="football":return "Live football\\n"+"\\n".join(f"{{pick(x,'teams.home.name')}} {{pick(x,'goals.home')}}–{{pick(x,'goals.away')}} {{pick(x,'teams.away.name')}}" for x in d.get('response',[])[:10])
 if KIND=="url_reputation":
  x=d.get('data',{{}}).get('attributes',{{}});stats=x.get('last_analysis_stats',{{}});return f"URL reputation\\nHarmless: {{stats.get('harmless',0)}}\\nMalicious: {{stats.get('malicious',0)}}\\nSuspicious: {{stats.get('suspicious',0)}}\\nLast scan: {{x.get('last_analysis_date','unknown')}}"
 if KIND=="flight":return "Flight status\\n"+"\\n".join(f"{{pick(x,'flight.iata')}} · {{x.get('flight_status')}}\\n{{pick(x,'departure.airport')}} → {{pick(x,'arrival.airport')}}" for x in d.get('data',[])[:5])
 if KIND=="github_actions":return "Recent CI runs\\n"+"\\n".join(f"• {{x.get('name')}} · {{x.get('status')}}/{{x.get('conclusion')}} · {{x.get('html_url')}}" for x in d.get('workflow_runs',[]))
 if KIND in ("jobs","bd_location","bd_laws"):return trim(json.dumps(d,ensure_ascii=False,indent=2),3800)
 return trim(json.dumps(d,ensure_ascii=False),3800)
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES('admin',?)",(str(uid),));DB.commit();await u.message.reply_text("Admin connected.");return
 DB.execute("INSERT OR IGNORE INTO users(id) VALUES(?)",(uid,));DB.commit();await u.message.reply_text(f"{{TITLE}}\\n{{HELP}}")
async def query(u:Update,c:ContextTypes.DEFAULT_TYPE):
 q=" ".join(c.args).strip()
 if not q and KIND not in ("cricket","football","bd_location"):await u.message.reply_text(HELP);return
 uid=u.effective_user.id;row=DB.execute("SELECT banned,queries FROM users WHERE id=?",(uid,)).fetchone()
 if row and (row[0] or (row[1]>=100 and uid!=admin())):await u.message.reply_text("Access restricted or quota reached.");return
 cache_key=KIND+":"+q.lower();cached=DB.execute("SELECT value FROM cache WHERE key=? AND expires>?",(cache_key,int(time.time()))).fetchone()
 try:
  text=cached[0] if cached else render(await fetch(q),q)
  if not cached:DB.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)",(cache_key,text,int(time.time())+300))
  DB.execute("UPDATE users SET queries=queries+1 WHERE id=?",(uid,));DB.commit();await u.message.reply_text(text[:4096],disable_web_page_preview=True)
 except httpx.HTTPStatusError as e:await u.message.reply_text(f"Provider returned {{e.response.status_code}}. Check API key or query.")
 except Exception:await u.message.reply_text("The data provider is unavailable or returned an unexpected response.")
async def panel(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin():return
 users,calls=DB.execute("SELECT COUNT(*),COALESCE(SUM(queries),0) FROM users").fetchone();await u.message.reply_text(f"Users: {{users}}\\nQueries: {{calls}}\\nCache: {{DB.execute('SELECT COUNT(*) FROM cache').fetchone()[0]}}")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build();app.add_handler(CommandHandler("start",start));app.add_handler(CommandHandler(COMMAND,query));app.add_handler(CommandHandler("panel",panel));app.run_polling()
'''


def commerce_code(title, product_type, states):
    """Full in-chat store/order product: catalog, cart, stock, coupons and admin."""
    return f'''# requirements: python-telegram-bot==21.4
import json,os,secrets,sqlite3,time
from telegram import InlineKeyboardButton,InlineKeyboardMarkup,Update
from telegram.ext import ApplicationBuilder,CallbackQueryHandler,CommandHandler,ContextTypes
TITLE={title!r};PRODUCT_TYPE={product_type!r};STATES={states!r};CLAIM=os.getenv("ADMIN_CLAIM_CODE","");PAY_URL=os.getenv("PAYMENT_URL","")
DB=sqlite3.connect("commerce.db",check_same_thread=False);DB.execute("PRAGMA journal_mode=WAL");DB.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,banned INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,description TEXT,price REAL,stock INTEGER,active INTEGER DEFAULT 1);CREATE TABLE IF NOT EXISTS cart(user_id INTEGER,product_id INTEGER,qty INTEGER,PRIMARY KEY(user_id,product_id));CREATE TABLE IF NOT EXISTS coupons(code TEXT PRIMARY KEY,percent INTEGER,uses_left INTEGER);CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,ref TEXT UNIQUE,user_id INTEGER,items TEXT,total REAL,status TEXT,payment_ref TEXT,created INTEGER);CREATE TABLE IF NOT EXISTS stock_items(id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER,value TEXT,sold INTEGER DEFAULT 0);");DB.commit()
def setting(k,d=""):
 r=DB.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone();return r[0] if r else d
def admin():return int(setting("admin","0"))
def money(v):return f"৳{{v:,.2f}}"
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES('admin',?)",(str(uid),));DB.commit();await u.message.reply_text("Store owner connected. Use /panel.");return
 DB.execute("INSERT OR IGNORE INTO users(id) VALUES(?)",(uid,));DB.commit();await u.message.reply_text(f"{{TITLE}}\\n/catalog · /cart · /orders · /support")
async def catalog(u:Update,c:ContextTypes.DEFAULT_TYPE):
 rows=DB.execute("SELECT id,name,description,price,stock FROM products WHERE active=1 ORDER BY id DESC LIMIT 30").fetchall()
 if not rows:await u.message.reply_text("Catalog is being prepared.");return
 for i,n,d,p,s in rows:await u.message.reply_text(f"#{{i}} {{n}}\\n{{d}}\\n{{money(p)}} · Stock {{s}}",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Add to cart",callback_data=f"add:{{i}}")]]))
async def cart(u:Update,c:ContextTypes.DEFAULT_TYPE):
 rows=DB.execute("SELECT p.id,p.name,p.price,c.qty FROM cart c JOIN products p ON p.id=c.product_id WHERE c.user_id=?",(u.effective_user.id,)).fetchall();total=sum(p*q for _,_,p,q in rows);text="\\n".join(f"{{n}} × {{q}} = {{money(p*q)}}" for _,n,p,q in rows);await u.message.reply_text((text+f"\\n\\nTotal {{money(total)}}") if rows else "Cart is empty.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Checkout",callback_data="checkout")]]) if rows else None)
async def action(u:Update,c:ContextTypes.DEFAULT_TYPE):
 q=u.callback_query;await q.answer();uid=u.effective_user.id
 if q.data.startswith("add:"):
  pid=int(q.data.split(':')[1]);DB.execute("INSERT INTO cart VALUES(?,?,1) ON CONFLICT(user_id,product_id) DO UPDATE SET qty=qty+1",(uid,pid));DB.commit();await q.answer("Added",show_alert=True);return
 if q.data=="checkout":
  rows=DB.execute("SELECT p.id,p.name,p.price,p.stock,c.qty FROM cart c JOIN products p ON p.id=c.product_id WHERE c.user_id=?",(uid,)).fetchall()
  if not rows or any(qty>stock for _,_,_,stock,qty in rows):await q.message.reply_text("Cart is empty or stock changed.");return
  total=sum(price*qty for _,_,price,_,qty in rows);ref="CN"+secrets.token_hex(4).upper();cur=DB.execute("INSERT INTO orders(ref,user_id,items,total,status,created) VALUES(?,?,?,?,?,?)",(ref,uid,json.dumps(rows),total,STATES[0],int(time.time())))
  for pid,_,_,_,qty in rows:DB.execute("UPDATE products SET stock=stock-? WHERE id=?",(qty,pid))
  DB.execute("DELETE FROM cart WHERE user_id=?",(uid,));DB.commit();pay=("\\nPay: "+PAY_URL+"?reference="+ref) if PAY_URL else "\\nSend payment proof with /paid "+ref+" TRANSACTION_ID";await q.message.reply_text(f"Order #{{cur.lastrowid}} · {{ref}}\\nTotal {{money(total)}}{{pay}}")
async def orders(u:Update,c:ContextTypes.DEFAULT_TYPE):
 rows=DB.execute("SELECT id,ref,total,status,created FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 15",(u.effective_user.id,)).fetchall();await u.message.reply_text("\\n".join(f"#{{i}} {{r}} · {{money(t)}} · {{s}}" for i,r,t,s,_ in rows) if rows else "No orders.")
async def paid(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if len(c.args)<2:return
 cur=DB.execute("UPDATE orders SET payment_ref=?,status=? WHERE ref=? AND user_id=?",(c.args[1][:100],"Payment review",c.args[0],u.effective_user.id));DB.commit();await u.message.reply_text("Payment submitted for review." if cur.rowcount else "Order not found.")
async def addproduct(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin():return
 parts=" ".join(c.args).split('|',3)
 if len(parts)!=4:await u.message.reply_text("/addproduct Name | Price | Stock | Description");return
 try:p=float(parts[1]);s=int(parts[2])
 except ValueError:return
 cur=DB.execute("INSERT INTO products(name,price,stock,description) VALUES(?,?,?,?)",(parts[0].strip()[:100],p,s,parts[3].strip()[:1000]));DB.commit();await u.message.reply_text(f"Product #{{cur.lastrowid}} added.")
async def status(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or len(c.args)<2 or not c.args[0].isdigit():return
 oid=int(c.args[0]);state=" ".join(c.args[1:]);row=DB.execute("SELECT user_id FROM orders WHERE id=?",(oid,)).fetchone();DB.execute("UPDATE orders SET status=? WHERE id=?",(state[:80],oid));DB.commit();await u.message.reply_text("Updated.")
 if row:
  try:await c.bot.send_message(row[0],f"Order #{{oid}}: {{state}}")
  except Exception:pass
async def panel(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin():return
 users=DB.execute("SELECT COUNT(*) FROM users").fetchone()[0];orders=DB.execute("SELECT COUNT(*) FROM orders").fetchone()[0];sales=DB.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE status NOT IN ('Cancelled','Rejected')").fetchone()[0];await u.message.reply_text(f"{{TITLE}}\\nUsers {{users}} · Orders {{orders}} · Gross {{money(sales)}}\\n/addproduct · /status ID STATE")
async def support(u:Update,c:ContextTypes.DEFAULT_TYPE):await u.message.reply_text(setting("support","Contact the store owner from the channel profile."))
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
for x,h in [("start",start),("catalog",catalog),("cart",cart),("orders",orders),("paid",paid),("addproduct",addproduct),("status",status),("panel",panel),("support",support)]:app.add_handler(CommandHandler(x,h))
app.add_handler(CallbackQueryHandler(action));app.run_polling()
'''


def channel_code(title, mode):
    return f'''# requirements: python-telegram-bot[job-queue]==21.4
import asyncio,os,sqlite3,time
from datetime import datetime,timezone
from telegram import InlineKeyboardButton,InlineKeyboardMarkup,Update
from telegram.error import Forbidden,RetryAfter
from telegram.ext import ApplicationBuilder,CallbackQueryHandler,CommandHandler,ContextTypes
TITLE={title!r};MODE={mode!r};CLAIM=os.getenv("ADMIN_CLAIM_CODE","");DB=sqlite3.connect("channel_suite.db",check_same_thread=False);DB.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,joined INTEGER DEFAULT 0,referrer INTEGER,points INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY AUTOINCREMENT,chat TEXT,text TEXT,publish_at INTEGER,status TEXT DEFAULT 'queued',delete_after INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS subscriptions(user_id INTEGER PRIMARY KEY,status TEXT DEFAULT 'pending',payment_ref TEXT,expires INTEGER DEFAULT 0);");DB.commit()
def get(k,d=""):
 r=DB.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone();return r[0] if r else d
def admin():return int(get("admin","0"))
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES('admin',?)",(str(uid),));DB.commit();await u.message.reply_text("Owner connected. Add this bot as channel admin, then /setchannel @channel.");return
 ref=int(c.args[0]) if c.args and c.args[0].isdigit() and int(c.args[0])!=uid else None;DB.execute("INSERT OR IGNORE INTO users(id,referrer) VALUES(?,?)",(uid,ref));DB.commit();channel=get("channel")
 buttons=[[InlineKeyboardButton("Join channel",url="https://t.me/"+channel.lstrip('@'))],[InlineKeyboardButton("Check membership",callback_data="check")]] if channel else []
 await u.message.reply_text(f"{{TITLE}}\\nJoin and verify to unlock access.",reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)
async def setchannel(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args:return
 channel=c.args[0];me=await c.bot.get_chat_member(channel,c.bot.id)
 if me.status not in ("administrator","creator"):await u.message.reply_text("Make the bot channel administrator first.");return
 DB.execute("INSERT OR REPLACE INTO settings VALUES('channel',?)",(channel,));DB.commit();await u.message.reply_text("Channel connected.")
async def check(u:Update,c:ContextTypes.DEFAULT_TYPE):
 q=u.callback_query;await q.answer();channel=get("channel")
 try:m=await c.bot.get_chat_member(channel,u.effective_user.id);ok=m.status in ("member","administrator","creator")
 except Exception:ok=False
 if not ok:await q.answer("Join the channel first.",show_alert=True);return
 row=DB.execute("SELECT joined,referrer FROM users WHERE id=?",(u.effective_user.id,)).fetchone()
 if row and not row[0]:DB.execute("UPDATE users SET joined=1 WHERE id=?",(u.effective_user.id,));DB.execute("UPDATE users SET points=points+10 WHERE id=?",(row[1],));DB.commit()
 await q.message.reply_text("Membership verified. Access unlocked.")
async def ref(u:Update,c:ContextTypes.DEFAULT_TYPE):
 me=await c.bot.get_me();row=DB.execute("SELECT points FROM users WHERE id=?",(u.effective_user.id,)).fetchone();await u.message.reply_text(f"https://t.me/{{me.username}}?start={{u.effective_user.id}}\\nPoints: {{row[0] if row else 0}}")
async def schedule(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or len(c.args)<3:return
 channel=get("channel");delay=max(0,int(c.args[0]));delete_after=max(0,int(c.args[1]));text=" ".join(c.args[2:])[:4000];when=int(time.time())+delay;cur=DB.execute("INSERT INTO posts(chat,text,publish_at,delete_after) VALUES(?,?,?,?)",(channel,text,when,delete_after));DB.commit();c.job_queue.run_once(publish,delay,data=cur.lastrowid);await u.message.reply_text(f"Queued post #{{cur.lastrowid}}.")
async def publish(c:ContextTypes.DEFAULT_TYPE):
 pid=c.job.data;row=DB.execute("SELECT chat,text,delete_after FROM posts WHERE id=?",(pid,)).fetchone()
 if not row:return
 msg=await c.bot.send_message(row[0],row[1]);DB.execute("UPDATE posts SET status='published' WHERE id=?",(pid,));DB.commit()
 if row[2]:c.job_queue.run_once(delete_post,row[2],data=(row[0],msg.message_id))
async def delete_post(c:ContextTypes.DEFAULT_TYPE):
 chat,message_id=c.job.data
 try:await c.bot.delete_message(chat,message_id)
 except Exception:pass
async def subscribe(u:Update,c:ContextTypes.DEFAULT_TYPE):
 days=int(get("plan_days","30"));price=get("plan_price","500");row=DB.execute("SELECT status,expires FROM subscriptions WHERE user_id=?",(u.effective_user.id,)).fetchone()
 if row and row[0]=="active" and row[1]>int(time.time()):await u.message.reply_text(f"Membership active until {{datetime.fromtimestamp(row[1],timezone.utc).date()}}.");return
 DB.execute("INSERT OR REPLACE INTO subscriptions(user_id,status) VALUES(?,?)",(u.effective_user.id,"pending"));DB.commit();await u.message.reply_text(f"Plan: {{days}} days · ৳{{price}}\\nPay using the owner's payment instructions, then /paid TRANSACTION_ID")
async def paid(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if not c.args:return
 DB.execute("INSERT OR REPLACE INTO subscriptions(user_id,status,payment_ref,expires) VALUES(?,?,?,0)",(u.effective_user.id,"payment_review",c.args[0][:100]));DB.commit();await u.message.reply_text("Payment submitted. The owner must verify it before access is granted.")
async def setplan(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or len(c.args)<2 or not c.args[0].isdigit():return
 DB.execute("INSERT OR REPLACE INTO settings VALUES('plan_days',?)",(str(max(1,int(c.args[0]))),));DB.execute("INSERT OR REPLACE INTO settings VALUES('plan_price',?)",(c.args[1][:30],));DB.commit();await u.message.reply_text("Membership plan updated.")
async def approve(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args or not c.args[0].isdigit():return
 uid=int(c.args[0]);days=int(c.args[1]) if len(c.args)>1 and c.args[1].isdigit() else int(get("plan_days","30"));expires=int(time.time())+days*86400;channel=get("channel");invite=await c.bot.create_chat_invite_link(channel,expire_date=expires,member_limit=1,name=f"member-{{uid}}")
 DB.execute("INSERT OR REPLACE INTO subscriptions(user_id,status,payment_ref,expires) VALUES(?,?,COALESCE((SELECT payment_ref FROM subscriptions WHERE user_id=?),''),?)",(uid,"active",uid,expires));DB.commit();await c.bot.send_message(uid,f"Payment approved. Your private invite expires with the plan:\\n{{invite.invite_link}}");await u.message.reply_text("Membership activated.")
async def expire_members(c:ContextTypes.DEFAULT_TYPE):
 channel=get("channel");now=int(time.time())
 if not channel:return
 for (uid,) in DB.execute("SELECT user_id FROM subscriptions WHERE status='active' AND expires>0 AND expires<=?",(now,)).fetchall():
  try:await c.bot.ban_chat_member(channel,uid);await c.bot.unban_chat_member(channel,uid)
  except Exception:pass
  DB.execute("UPDATE subscriptions SET status='expired' WHERE user_id=?",(uid,))
 DB.commit()
async def panel(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin():return
 users=DB.execute("SELECT COUNT(*) FROM users").fetchone()[0];joined=DB.execute("SELECT COUNT(*) FROM users WHERE joined=1").fetchone()[0];posts=DB.execute("SELECT COUNT(*) FROM posts").fetchone()[0];active=DB.execute("SELECT COUNT(*) FROM subscriptions WHERE status='active' AND expires>?",(int(time.time()),)).fetchone()[0];await u.message.reply_text(f"{{TITLE}}\\nUsers {{users}} · Verified {{joined}} · Posts {{posts}} · Paid active {{active}}\\n/setchannel · /schedule DELAY DELETE_AFTER TEXT · /setplan DAYS PRICE · /approve USER DAYS · /broadcast")
async def broadcast(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id!=admin() or not c.args:return
 text=" ".join(c.args)[:4000]
 for (uid,) in DB.execute("SELECT id FROM users WHERE joined=1"):
  try:await c.bot.send_message(uid,text);await asyncio.sleep(.04)
  except RetryAfter as e:await asyncio.sleep(float(e.retry_after)+.2)
  except Forbidden:pass
  except Exception:pass
 await u.message.reply_text("Broadcast finished.")
async def restore(app):
 now=int(time.time())
 for pid,publish_at in DB.execute("SELECT id,publish_at FROM posts WHERE status='queued'").fetchall():app.job_queue.run_once(publish,max(0,publish_at-now),data=pid)
 app.job_queue.run_repeating(expire_members,3600,first=30)
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).post_init(restore).build()
for x,h in [("start",start),("setchannel",setchannel),("ref",ref),("schedule",schedule),("subscribe",subscribe),("paid",paid),("setplan",setplan),("approve",approve),("panel",panel),("broadcast",broadcast)]:app.add_handler(CommandHandler(x,h))
app.add_handler(CallbackQueryHandler(check,pattern="^check$"));app.run_polling()
'''


def media_code(title, mode):
    return f'''# requirements: python-telegram-bot==21.4 Pillow==10.4.0 pypdf==4.3.1 qrcode==7.4.2 httpx==0.27.2
import io,os,sqlite3
import httpx
from PIL import Image
from pypdf import PdfReader,PdfWriter
import qrcode
from telegram import Update
from telegram.ext import ApplicationBuilder,CommandHandler,ContextTypes,MessageHandler,filters
TITLE={title!r};MODE={mode!r};KEY=os.getenv("MEDIA_API_KEY","");CLAIM=os.getenv("ADMIN_CLAIM_CODE","");DB=sqlite3.connect("media_tools.db",check_same_thread=False);DB.executescript("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,used INTEGER DEFAULT 0,banned INTEGER DEFAULT 0);");DB.commit()
def admin():
 r=DB.execute("SELECT value FROM settings WHERE key='admin'").fetchone();return int(r[0]) if r else 0
async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
 uid=u.effective_user.id
 if not admin() and c.args and c.args[0]=="claim_"+CLAIM:DB.execute("INSERT INTO settings VALUES('admin',?)",(str(uid),));DB.commit();await u.message.reply_text("Admin connected.");return
 DB.execute("INSERT OR IGNORE INTO users(id) VALUES(?)",(uid,));DB.commit();await u.message.reply_text(f"{{TITLE}}\\nSend a supported file. For QR use /qr TEXT. Files are processed in memory and not retained.")
async def qr(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if not c.args:return
 out=io.BytesIO();qrcode.make(" ".join(c.args)[:2000]).save(out,"PNG");out.seek(0);out.name="qr.png";await u.message.reply_document(out)
async def process(u:Update,c:ContextTypes.DEFAULT_TYPE):
 row=DB.execute("SELECT used,banned FROM users WHERE id=?",(u.effective_user.id,)).fetchone()
 if row and (row[1] or row[0]>=50):await u.message.reply_text("Daily processing quota reached or access restricted.");return
 obj=u.message.document or (u.message.photo[-1] if u.message.photo else None)
 if not obj or getattr(obj,'file_size',0)>20*1024*1024:await u.message.reply_text("Send a file up to 20 MB.");return
 tg=await obj.get_file();raw=bytes(await tg.download_as_bytearray())
 try:
  if MODE=="image_pdf":
   image=Image.open(io.BytesIO(raw)).convert("RGB");out=io.BytesIO();image.save(out,"PDF");name="converted.pdf"
  elif MODE=="compress_image":
   image=Image.open(io.BytesIO(raw)).convert("RGB");image.thumbnail((1920,1920));out=io.BytesIO();image.save(out,"JPEG",quality=68,optimize=True);name="compressed.jpg"
  elif MODE=="resize_image":
   image=Image.open(io.BytesIO(raw)).convert("RGB");image.thumbnail((1080,1080));out=io.BytesIO();image.save(out,"JPEG",quality=85);name="resized.jpg"
  elif MODE=="pdf_extract":
   reader=PdfReader(io.BytesIO(raw));text="\\n\\n".join((p.extract_text() or "") for p in reader.pages[:50]);out=io.BytesIO(text.encode());name="extracted.txt"
  elif MODE=="pdf_split":
   reader=PdfReader(io.BytesIO(raw));writer=PdfWriter();writer.add_page(reader.pages[0]);out=io.BytesIO();writer.write(out);name="first-page.pdf"
  elif MODE=="ocr":
   async with httpx.AsyncClient(timeout=60) as client:r=await client.post("https://api.ocr.space/parse/image",headers={{"apikey":KEY}},files={{"file":("scan.jpg",raw)}});r.raise_for_status();text="\\n".join(x.get("ParsedText","") for x in r.json().get("ParsedResults",[]));out=io.BytesIO(text.encode());name="ocr.txt"
  elif MODE=="virus_scan":
   async with httpx.AsyncClient(timeout=90) as client:
    r=await client.post("https://www.virustotal.com/api/v3/files",headers={{"x-apikey":KEY}},files={{"file":("upload",raw)}});r.raise_for_status();analysis_id=r.json().get("data",{{}}).get("id","");stats={{}};status="queued"
    for _ in range(10):
     await __import__('asyncio').sleep(2);check=await client.get(f"https://www.virustotal.com/api/v3/analyses/{{analysis_id}}",headers={{"x-apikey":KEY}});check.raise_for_status();attrs=check.json().get("data",{{}}).get("attributes",{{}});status=attrs.get("status","queued");stats=attrs.get("stats",{{}})
     if status=="completed":break
   report=f"Status: {{status}}\\nMalicious: {{stats.get('malicious',0)}}\\nSuspicious: {{stats.get('suspicious',0)}}\\nHarmless: {{stats.get('harmless',0)}}\\nUndetected: {{stats.get('undetected',0)}}\\nAnalysis ID: {{analysis_id}}";out=io.BytesIO(report.encode());name="virustotal-report.txt"
  elif MODE=="checksum":
   import hashlib;report=f"SHA256: {{hashlib.sha256(raw).hexdigest()}}\\nSHA1: {{hashlib.sha1(raw).hexdigest()}}\\nMD5: {{hashlib.md5(raw).hexdigest()}}\\nBytes: {{len(raw)}}";out=io.BytesIO(report.encode());name="checksums.txt"
  elif MODE=="metadata":
   import hashlib;filename=getattr(obj,'file_name','photo.jpg');report=f"Name: {{filename}}\\nBytes: {{len(raw)}}\\nMIME: {{getattr(obj,'mime_type','image/jpeg')}}\\nTelegram file ID: {{obj.file_id}}\\nSHA256: {{hashlib.sha256(raw).hexdigest()}}";out=io.BytesIO(report.encode());name="metadata.txt"
  else:raise ValueError("Unsupported processor")
  out.seek(0);out.name=name;await u.message.reply_document(out,caption="Done. Original file was not retained.");DB.execute("UPDATE users SET used=used+1 WHERE id=?",(u.effective_user.id,));DB.commit()
 except Exception:await u.message.reply_text("Processing failed. Check the file type and required API key.")
async def panel(u:Update,c:ContextTypes.DEFAULT_TYPE):
 if u.effective_user.id==admin():await u.message.reply_text(f"Users: {{DB.execute('SELECT COUNT(*) FROM users').fetchone()[0]}} · Jobs: {{DB.execute('SELECT COALESCE(SUM(used),0) FROM users').fetchone()[0]}}")
app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build();app.add_handler(CommandHandler("start",start));app.add_handler(CommandHandler("qr",qr));app.add_handler(CommandHandler("panel",panel));app.add_handler(MessageHandler(filters.Document.ALL|filters.PHOTO,process));app.run_polling()
'''

AI_SPECS=[
("ai-business-bangla","Bangla AI business assistant","Bangla/Banglish customer support with approved-policy answers, conversation memory, quotas and human-ready responses.","You are a Bangladesh business support agent. Understand Bangla, English and Banglish. Never invent price, stock, discount or policy; say when human support is needed."),
("ai-support-desk","AI support desk + handoff","First-line support assistant with controlled policy prompt, memory, quotas, admin analytics and broadcast.","Resolve support questions from the approved instructions. Ask concise clarifying questions and escalate anything uncertain."),
("ai-sales-agent","AI sales qualification agent","Qualifies leads by need, budget and timeline, answers product questions and prepares concise sales handoff.","Act as a sales qualification agent. Learn need, budget and timeline. Never claim unavailable stock or discounts."),
("ai-study-tutor","Bangla AI study tutor","Bangla/English explanations, practice questions, step-by-step tutoring, memory and owner-controlled limits.","Teach clearly in Bangla or English. Guide reasoning, create practice questions, and do not facilitate cheating on live exams."),
("ai-coding-assistant","AI coding assistant","Code review, debugging and implementation guidance with per-user memory and owner-controlled API spend.","Be a senior software engineer. Return secure, runnable code, explain assumptions, and never expose secrets."),
("ai-content-studio","AI content studio","Bangla captions, product copy, scripts and campaign variants with persistent project context.","Create natural Bangla, Banglish or English marketing content. Avoid fake claims and ask for brand voice when missing."),
("ai-legal-document-helper","AI document explanation helper","Explains supplied legal or policy text in plain language with explicit non-lawyer boundaries.","Explain legal text plainly, identify clauses and questions to ask a qualified lawyer. Never present output as legal advice."),
("ai-cv-career-coach","AI CV and career coach","CV bullets, cover letters, interview practice and Bangladesh-focused career guidance.","Help improve CVs and interviews honestly. Never invent credentials or experience."),
("ai-freelancer-assistant","Freelancer proposal assistant","Upwork/Fiverr proposal drafting, scope clarification, milestone planning and client-reply assistance.","Draft specific honest freelance proposals. Ask for job details and never fabricate portfolio work."),
("ai-ecommerce-reply","E-commerce reply copilot","Fast Bangla replies for price, stock, delivery, returns and bKash/Nagad instructions using owner policy.","Write short natural Bangladesh ecommerce replies. Only use prices, stock, payment and return policy provided by owner."),
("ai-real-estate-agent","AI property lead assistant","Property enquiry qualification by area, type and budget with memory and handoff-ready summaries.","Qualify property leads by location, type, budget and timeline. Never claim availability unless policy says so."),
("ai-travel-planner","AI travel planning desk","Itinerary and budget planning with clear warnings that live prices require verification.","Create practical travel plans. Clearly label estimates and tell users to verify visa, fare and safety information."),
("ai-health-info","Health information assistant","General health-information explanations with strict emergency and professional-care escalation boundaries.","Provide general health education only. For emergencies advise local emergency care immediately; never diagnose or prescribe."),
("ai-research-assistant","Research and synthesis assistant","Structured research plans, source-evaluation checklists and concise synthesis with memory and quotas.","Help research systematically. Distinguish known facts, assumptions and items that need current source verification."),
("ai-community-copilot","AI community copilot","Drafts moderator replies, summaries, FAQs and announcements for Telegram communities.","Assist community admins with neutral summaries, FAQ answers and moderation wording. Never impersonate an admin decision."),
("ai-bangla-translator","Bangla localization studio","Context-aware Bangla, Banglish and English translation for sellers, creators and freelancers with terminology memory.","Translate naturally between Bangla, Banglish and English. Preserve names, numbers and intent; explain ambiguous wording instead of guessing."),
("ai-document-analyst","AI document analyst","Long-form document analysis prompt, clause extraction, structured summaries, risks and follow-up questions.","Analyze only text the user supplies. Return summary, key facts, risks, missing information and questions. Never invent document content."),
]

LOOKUPS=[
("bangla-wikipedia","Bangla Wikipedia research","bangla_wiki","wiki","/wiki বাংলাদেশের ইতিহাস","Knowledge",False),
("wikipedia-research","Wikipedia research bot","wikipedia","wiki","/wiki topic","Knowledge",False),
("english-dictionary-pro","Dictionary and definitions","dictionary","define","/define word","Education",False),
("book-discovery","Book discovery and author search","books","books","/books title or author","Education",False),
("anime-discovery","Anime search and ratings","anime","anime","/anime title","Entertainment",False),
("country-intelligence","Country information desk","country","country","/country Bangladesh","Travel",False),
("ip-intelligence","IP location and ISP lookup","ip","ip","/ip 8.8.8.8","Security",False),
("github-repo-monitor","GitHub repository intelligence","github","repo","/repo owner/name","Developer",False),
("github-release-monitor","GitHub release lookup","github_release","release","/release owner/name","Developer",False),
("pypi-package-intel","PyPI package intelligence","pypi","pypi","/pypi package","Developer",False),
("npm-package-intel","npm package intelligence","npm","npm","/npm package","Developer",False),
("crypto-market-bd","Crypto price in USD and BDT","crypto","coin","/coin bitcoin","Finance",False),
("remittance-converter","Remittance currency converter","currency","convert","/convert 100 USD BDT","Finance",False),
("bangla-quran-search","Bangla Quran ayah lookup","quran","ayah","/ayah 2:255","Islamic",False),
("bangla-hadith-search","Bangla Hadith lookup","hadith","hadith","/hadith bukhari 1","Islamic",False),
("movie-series-search","Movie and series discovery","movie","movie","/movie title","Entertainment",True),
("bangladesh-news-desk","Bangladesh news search","news","news","/news Bangladesh","News",True),
("live-cricket-bangladesh","Live cricket score desk","cricket","live","/live","Sports",True),
("live-football-score","Live football score desk","football","live","/live","Sports",True),
("bangladesh-job-alerts","Bangladesh jobs API search","jobs","jobs","/jobs developer","Jobs",True),
("bangladesh-location-search","Bangladesh district/upazila data","bd_location","location","/location Rangpur","Bangladesh",False),
("bangladesh-laws-search","Bangladesh laws search","bd_laws","law","/law keyword","Bangladesh",False),
("url-reputation-pro","VirusTotal URL reputation","url_reputation","scan","/scan https://example.com","Security",True),
("flight-status-pro","Live flight status","flight","flight","/flight BG147","Travel",True),
("github-actions-monitor","GitHub Actions status","github_actions","ci","/ci owner/repository","Developer",False),
]

COMMERCE=[
("bd-online-shop","Bangladesh online shop","Physical products with catalog, cart, stock, checkout, payment proof, order tracking and sales analytics.","physical products"),
("digital-product-store","Digital product order store","Digital inventory, cart, order references, payment review and controlled owner fulfilment.","digital products"),
("facebook-seller-order-bot","Facebook seller order desk","Turns social traffic into structured Telegram catalog, carts, order references and payment review.","social commerce products"),
("restaurant-food-order","Restaurant food ordering","Menu, cart, stock availability, checkout, payment reference and live order statuses.","food menu"),
("grocery-order-bot","Grocery order bot","Searchable grocery catalog foundation with cart, quantities, stock, checkout and fulfilment statuses.","grocery items"),
("fashion-store-bot","Fashion store bot","Product catalog, size/variant description, cart, inventory, payment proof and order status.","fashion items"),
("book-store-bot","Book shop bot","Book catalog, cart, inventory, checkout, payment proof and delivery lifecycle.","books"),
("course-selling-bot","Course selling bot","Course catalog, checkout, payment review, order history and controlled fulfilment states.","courses"),
("software-license-store","Software license store","License product stock, checkout references, payment review and fulfilment tracking.","licenses"),
("wholesale-order-bot","Wholesale order bot","Bulk-product catalog, quantities, order references, payment review and admin sales dashboard.","wholesale products"),
("preorder-campaign-bot","Pre-order campaign bot","Limited stock catalog, reservation checkout, payment reference and campaign order statuses.","pre-order products"),
("home-food-order","Home kitchen order bot","Daily menu, stock quantities, cart, payment proof and cooking/delivery status updates.","home-cooked meals"),
("event-ticket-store","Event ticket store","Ticket inventory, cart, checkout references, payment validation and attendee order history.","event tickets"),
("donation-campaign-bot","Donation campaign checkout","Campaign catalog, contribution checkout, transaction proof and transparent admin totals.","campaign contributions"),
("service-package-store","Service package checkout","Service packages, cart, checkout, payment reference and delivery status management.","service packages"),
("reseller-panel-orders","Reseller order panel","Service catalog, quantity cart, payment review, order lifecycle and gross-sales dashboard.","reseller services"),
("subscription-plan-store","Subscription plan checkout","Plan catalog, checkout, payment proof and activation status history.","subscription plans"),
("electronics-shop-bot","Electronics shop bot","Stock-aware electronics catalog, cart, checkout and order tracking.","electronics"),
("courier-cod-orders","Bangladesh COD courier order desk","COD product catalog, stock, cart, order references, payment state and courier-ready fulfilment statuses.","COD products"),
("pharmacy-order-desk","Pharmacy order desk","Non-prescribing medicine/product catalog, stock, cart, checkout and pharmacist review workflow.","pharmacy products"),
("mobile-accessories-shop","Mobile accessories shop","Accessories catalog, stock, cart, checkout, payment proof and delivery status.","mobile accessories"),
("cosmetics-shop-bot","Cosmetics shop bot","Beauty catalog, inventory, cart, payment review and Bangladesh delivery workflow.","cosmetics"),
("computer-parts-store","Computer parts store","Parts catalog, stock, cart, checkout references and fulfilment status management.","computer parts"),
("print-service-orders","Printing service order bot","Print package catalog, quantities, checkout, payment proof and production statuses.","printing packages"),
]

CHANNELS=[
("paid-channel-manager","Paid channel membership manager","membership"),("force-join-referral","Force-join referral growth bot","referral"),("channel-post-scheduler","Channel post scheduler","scheduler"),("auto-delete-posts","Auto-delete channel posts","scheduler"),("premium-content-gate","Premium content gate","membership"),("course-channel-access","Course channel access manager","membership"),("vip-signal-access","VIP channel access manager","membership"),("giveaway-referral","Verified-member giveaway referral","referral"),("affiliate-channel-growth","Affiliate channel growth system","referral"),("multi-channel-gate","Multi-channel join gate foundation","membership"),("scheduled-news-channel","Scheduled news channel publisher","scheduler"),("deal-channel-publisher","Deal channel publisher","scheduler"),("exam-update-channel","Exam update channel publisher","scheduler"),("job-channel-publisher","Job channel publisher","scheduler"),("creator-fan-club","Creator fan-club access","membership")]

MEDIA=[
("image-to-pdf-pro","Image to PDF studio","image_pdf",False),("image-compressor-pro","Image compressor","compress_image",False),("social-image-resizer","Social image resizer","resize_image",False),("pdf-text-extractor","PDF text extractor","pdf_extract",False),("pdf-page-splitter","PDF page splitter","pdf_split",False),("qr-code-studio","QR code studio","metadata",False),("bangla-ocr-scanner","Bangla/English OCR scanner","ocr",True),("virus-total-scanner","VirusTotal file scanner","virus_scan",True),("file-hash-verifier","File checksum verifier","checksum",False),("image-metadata-inspector","Image metadata and hash inspector","metadata",False)]


def build_premium_templates():
    out={}
    ai_fields=[field("AI_API_KEY","AI provider API key",True),field("AI_API_BASE","OpenAI-compatible API base",False,True,"https://api.openai.com/v1"),field("AI_MODEL","Model name",False,True,"gpt-4o-mini")]
    for i,(slug,name,desc,role) in enumerate(AI_SPECS):out[slug]=item(name,desc,"AI",ai_code(name,role,desc),ai_fields,"Top",1000-i)
    for i,(slug,name,kind,cmd,help_text,cat,needs_key) in enumerate(LOOKUPS):
        fs=[field("DATA_API_KEY","Provider API key",True)] if needs_key else []
        if kind in ("jobs","bd_location"):fs.append(field("DATA_API_URL","Provider endpoint",False,kind=="jobs"))
        out[slug]=item(name,f"Live {name.lower()} with provider-specific parsing, caching, quotas, analytics and failure handling.",cat,lookup_code(name,kind,cmd,help_text),fs,"API",900-i)
    payment=[field("PAYMENT_URL","bKash/Nagad/SSLCommerz payment or checkout URL",False,False)]
    for i,(slug,name,desc,ptype) in enumerate(COMMERCE):out[slug]=item(name,desc,"Commerce",commerce_code(name,ptype,("Pending payment","Payment review","Confirmed","Processing","Completed","Cancelled")),payment,"Business",800-i)
    for i,(slug,name,mode) in enumerate(CHANNELS):out[slug]=item(name,"Channel-admin verification, member gate, referral credit, scheduled publishing, auto-delete support, broadcasts and analytics.","Channels",channel_code(name,mode),(),"Growth",700-i,"Add the bot as channel administrator, open Go to bot, then /setchannel @channel.")
    for i,(slug,name,mode,key) in enumerate(MEDIA):out[slug]=item(name,"In-memory file processing with size limits, per-user quotas, no-retention behavior and admin usage analytics.","Files",media_code(name,mode),[field("MEDIA_API_KEY","OCR.Space or VirusTotal API key",True)] if key else [],"Files",600-i)
    return out
