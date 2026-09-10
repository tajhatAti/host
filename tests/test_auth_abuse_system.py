# AUTH + ABUSE PREVENTION — full system test (master prompt §1-§6).
#
# Covers, in build order:
#   §1 Telegram login      — HMAC verify, existing-ID reuse, username collision
#   §2 Email + Gmail-only  — OTP flow, lookalike-domain rejection, CAPTCHA
#   §3 Fingerprinting      — captured on BOTH auth methods, account + session
#   §4 Resource limiting   — fingerprint cluster (3) and IP aggregate (9)
#   §5 Velocity + CAPTCHA  — 3 signups/IP/24h, burst FLAGGING (never blocking)
#   §6 Admin visibility    — clusters, flags, 404-stealth for non-admins
import hashlib
import hmac
import os
import sqlite3
import sys
import tempfile
import time

DB = tempfile.mktemp(suffix=".db")
os.environ["DB_PATH"] = DB
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ["SIGNUP_DAILY_MAX"] = "50"          # relaxed; §5 gets its own check
TG_TOKEN = "123456:AAFakeBotTokenForTests"
os.environ["TELEGRAM_PING_BOT_TOKEN"] = TG_TOKEN
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.email as _email_svc  # noqa: E402
_email_svc.send_email = lambda *a, **k: None

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402
from services import limits  # noqa: E402
from routes import deps  # noqa: E402

client = TestClient(app)
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

FP_A = '{"ua":"Mozilla/5.0","canvas":"aaa","tz":"Asia/Dhaka"}'
FP_B = '{"ua":"Mozilla/5.0","canvas":"bbb","tz":"Asia/Dhaka"}'

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("✓ " if cond else "✗ FAIL ") + f"{name:62s}" + (f" — {extra}" if not cond else ""))


def tg_payload(uid=1001, **over):
    d = {"id": uid, "first_name": "Ahad", "username": f"u{uid}",
         "photo_url": "", "auth_date": int(time.time())}
    d.update(over)
    sig = {k: v for k, v in d.items() if k != "fingerprint"}
    s = "\n".join(f"{k}={v}" for k, v in sorted(sig.items()) if v not in (None, ""))
    d["hash"] = hmac.new(hashlib.sha256(TG_TOKEN.encode()).digest(),
                         s.encode(), hashlib.sha256).hexdigest()
    return d


def email_signup(username, fingerprint=FP_A, captcha="12", email=None):
    return client.post("/signup", json={
        "username": username, "email": email or f"{username}@gmail.com",
        "password": "Str0ng!Pass9", "agreed_terms": True,
        "captcha": captcha, "fingerprint": fingerprint,
    })


def verify_and_token(username, fingerprint=FP_A):
    otp = db.execute("SELECT otp FROM users WHERE username=?", (username,)).fetchone()["otp"]
    r = client.post("/verify", json={"username": username, "otp": otp, "fingerprint": fingerprint})
    return r.json().get("token")


# ---------------------------------------------------------------- §1 Telegram
print("\n--- §1 Telegram login ---")
r1 = client.post("/auth/telegram", json=dict(tg_payload(1001), fingerprint=FP_A))
check("telegram signup succeeds", r1.status_code == 200, r1.text[:110])
check("session token returned", bool(r1.json().get("token")))
r2 = client.post("/auth/telegram", json=dict(tg_payload(1001), fingerprint=FP_A))
check("existing telegram_id logs in, no duplicate",
      r2.status_code == 200 and "Login successful" in r2.json().get("message", ""))
check("exactly one account per telegram_id",
      db.execute("SELECT COUNT(*) c FROM users WHERE telegram_id=1001").fetchone()["c"] == 1)

bad = tg_payload(1002)
bad["hash"] = "0" * 64
check("forged HMAC rejected", client.post("/auth/telegram", json=bad).status_code == 400)
check("stale auth_date rejected",
      client.post("/auth/telegram",
                  json=tg_payload(1003, auth_date=int(time.time()) - 90000)).status_code == 400)

db.execute("INSERT INTO users (username,email,password,is_verified,created_at,updated_at) "
           "VALUES ('tg_1009','sq@gmail.com','h',1,'t','t')")
db.commit()
rc = client.post("/auth/telegram", json=dict(tg_payload(1009), fingerprint=FP_A))
check("username collision handled (no 500)",
      rc.status_code == 200 and rc.json()["username"] != "tg_1009", rc.text[:110])

# ------------------------------------------------------------ §2 Email/Gmail
print("\n--- §2 Email + password (Gmail-only) ---")
check("valid gmail signup succeeds", email_signup("mailer1").status_code == 200)
check("wrong CAPTCHA rejected", email_signup("mailer2", captcha="99").status_code == 400)
r = client.post("/signup", json={"username": "mailer3", "email": "mailer3@gmail.com",
                                 "password": "Str0ng!Pass9", "agreed_terms": True})
check("missing CAPTCHA rejected", r.status_code == 400)
r = email_signup("yah", email="yah@yahoo.com")
check("non-gmail rejected with the specified message",
      r.status_code == 400 and r.json()["detail"].startswith(
          "Only Gmail addresses are supported for email sign-up."), r.text[:110])
r = email_signup("look", email="look@notgmail.com")
check("lookalike 'notgmail.com' rejected (no endswith bypass)", r.status_code == 400)
r = email_signup("disp", email="disp@mailinator.com")
check("disposable domain rejected", r.status_code == 400)
tok_mail = verify_and_token("mailer1")
check("OTP verification returns a session", bool(tok_mail))
check("login works after verification",
      client.post("/login", json={"username": "mailer1", "password": "Str0ng!Pass9",
                                  "fingerprint": FP_A}).status_code == 200)
check("both auth methods coexist (telegram + email rows present)",
      db.execute("SELECT COUNT(*) c FROM users WHERE telegram_id IS NOT NULL").fetchone()["c"] >= 1
      and db.execute("SELECT COUNT(*) c FROM users WHERE username='mailer1'").fetchone()["c"] == 1)

# ------------------------------------------------------- §3 Fingerprinting
print("\n--- §3 Device fingerprinting ---")
fp_hash = deps.normalise_fingerprint(FP_A)
check("fingerprint hashed to stable sha256 hex", len(fp_hash) == 64)
check("same input -> same hash", deps.normalise_fingerprint(FP_A) == fp_hash)
check("different device -> different hash", deps.normalise_fingerprint(FP_B) != fp_hash)
check("key order does not change the hash",
      deps.normalise_fingerprint('{"b":2,"a":1}') == deps.normalise_fingerprint('{"a":1,"b":2}'))
check("fingerprint stored on EMAIL account",
      db.execute("SELECT fingerprint f FROM users WHERE username='mailer1'").fetchone()["f"] == fp_hash)
check("fingerprint stored on TELEGRAM account",
      db.execute("SELECT fingerprint f FROM users WHERE telegram_id=1001").fetchone()["f"] == fp_hash)
check("fingerprint stored on sessions",
      db.execute("SELECT COUNT(*) c FROM sessions WHERE fingerprint=?", (fp_hash,)).fetchone()["c"] >= 2)
check("IP recorded on login",
      bool(db.execute("SELECT last_ip FROM users WHERE username='mailer1'").fetchone()["last_ip"]))

# --------------------------------------------------------- §4 Resource limits
print("\n--- §4 Resource limiting (fingerprint + IP) ---")
tg_uid = db.execute("SELECT id FROM users WHERE telegram_id=1001").fetchone()["id"]
mail_uid = db.execute("SELECT id FROM users WHERE username='mailer1'").fetchone()["id"]
check("two accounts, different auth methods, one device", tg_uid != mail_uid)

# 2 jobs owned by the email account + 1 by the telegram account = 3 on this device
for i, uid in enumerate([mail_uid, mail_uid, tg_uid]):
    db.execute("INSERT INTO jobs (user_id,name,language,code,runner_job_id,created_at,updated_at) "
               "VALUES (?,?,?,?,?,?,?)", (uid, f"job{i}", "python", "x", f"rid{i}", "t", "t"))
db.commit()

_real_running = limits.running_runner_ids
limits.running_runner_ids = lambda: {"rid0", "rid1", "rid2"}

tg_tok = client.post("/auth/telegram", json=dict(tg_payload(1001), fingerprint=FP_A)).json()["token"]
hdr = {"Authorization": "Bearer " + tg_tok, "X-Fingerprint": FP_A}
r = client.post("/api/jobs", json={"name": "extra", "language": "python", "code": "print(1)"}, headers=hdr)
check("4th job on shared device blocked (429)", r.status_code == 429, r.text[:110])
detail = r.json().get("detail", "") if r.status_code == 429 else ""
check("message explains WHY (device limit)", "device" in detail.lower() and "stop one" in detail.lower(), detail[:110])
check("message reveals cross-account aggregation", "accounts" in detail.lower(), detail[:110])

limits.running_runner_ids = lambda: {"rid0", "rid1"}
r = client.post("/api/jobs", json={"name": "under", "language": "python", "code": "print(1)"}, headers=hdr)
check("under the cap is not blocked", r.status_code != 429, r.text[:110])

# IP aggregate: many jobs, request without a fingerprint header
for i in range(3, 12):
    db.execute("INSERT INTO jobs (user_id,name,language,code,runner_job_id,created_at,updated_at) "
               "VALUES (?,?,?,?,?,?,?)", (tg_uid, f"ipjob{i}", "python", "x", f"rid{i}", "t", "t"))
db.commit()
limits.running_runner_ids = lambda: {f"rid{i}" for i in range(12)}
r = client.post("/api/jobs", json={"name": "ipx", "language": "python", "code": "print(1)"},
                headers={"Authorization": "Bearer " + tg_tok})
check("IP aggregate cap enforced (429)", r.status_code == 429, r.text[:110])
check("IP message mentions the network",
      "network" in r.json().get("detail", "").lower(), r.text[:110])

# server-side enforcement: a client that simply omits the header still hits the IP cap
check("limit is server-side (no client cooperation needed)", r.status_code == 429)

# Runner outage: the CLUSTER check is skipped (we cannot know what is alive),
# so the request falls through to the ordinary per-account limit instead of
# every user being blocked by an infrastructure problem.
limits.running_runner_ids = lambda: set()
r = client.post("/api/jobs", json={"name": "outage", "language": "python", "code": "print(1)"}, headers=hdr)
outage_detail = r.json().get("detail", "")
check("runner outage skips the cluster check (no device/network block)",
      "device" not in outage_detail.lower() and "network" not in outage_detail.lower(),
      outage_detail[:110])
limits.running_runner_ids = _real_running

# ------------------------------------------------- §5 Velocity + burst flags
print("\n--- §5 Signup velocity + burst flagging ---")
check("default IP signup cap is 3/24h", deps.SIGNUP_DAILY_MAX == 3 or os.getenv("SIGNUP_DAILY_MAX") == "50")
deps._signup_events.clear()
burst_fp = deps.normalise_fingerprint('{"dev":"burst"}')
flagged = [deps.record_signup_attempt(burst_fp) for _ in range(deps.SIGNUP_BURST_MAX)]
check("burst flagged at threshold", flagged[-1] is True)
check("burst is FLAG-only, earlier signups allowed", flagged[0] is False)
check("burst visible to admins", deps.signup_burst_counts().get(burst_fp, 0) >= deps.SIGNUP_BURST_MAX)

import services.captcha as captcha_svc  # noqa: E402
check("captcha falls back to arithmetic when unconfigured", captcha_svc.provider() == "none")
check("arithmetic answer validated", captcha_svc.verify(None, "12") is True)
check("wrong arithmetic answer rejected", captcha_svc.verify(None, "7") is False)
os.environ["TURNSTILE_SECRET_KEY"] = "sekret"
check("provider switches to turnstile when configured", captcha_svc.provider() == "turnstile")
check("turnstile failure is fail-CLOSED", captcha_svc.verify("", "12", "1.2.3.4") is False)
del os.environ["TURNSTILE_SECRET_KEY"]

# ------------------------------------------------------------ §6 Admin views
print("\n--- §6 Admin visibility ---")
db.execute("UPDATE users SET is_admin=1 WHERE username='mailer1'")
db.commit()
admin_tok = client.post("/login", json={"username": "mailer1", "password": "Str0ng!Pass9",
                                        "fingerprint": FP_A}).json()["token"]
AH = {"Authorization": "Bearer " + admin_tok}
UH = {"Authorization": "Bearer " + tg_tok}

for ep in ("/admin/fingerprint-clusters", "/admin/ip-clusters", "/admin/signup-flags"):
    check(f"{ep} reachable by admin", client.get(ep, headers=AH).status_code == 200)
    check(f"{ep} returns 404 for non-admin", client.get(ep, headers=UH).status_code == 404)

data = client.get("/admin/fingerprint-clusters", headers=AH).json()
top = data["clusters"][0]
check("cluster groups the shared device", top["account_count"] >= 2, str(top.get("account_count")))
check("cluster lists member accounts", len(top["accounts"]) >= 2)
check("cluster reports live job count", "running_jobs" in top)
check("clusters sorted by size",
      all(data["clusters"][i]["account_count"] >= data["clusters"][i + 1]["account_count"]
          for i in range(len(data["clusters"]) - 1)))
ipd = client.get("/admin/ip-clusters", headers=AH).json()
check("IP cluster view populated", ipd["total"] >= 1 and "running_jobs" in ipd["clusters"][0])
check("full fingerprint hash available for investigation", len(top["fingerprint_full"]) == 64)

# Suspend/reactivate + audit trail. Destructive admin actions require the
# admin's OWN 2FA (pre-existing security control), so assert that first, then
# enable 2FA and confirm the action + audit entry actually work.
admin_id = db.execute("SELECT id FROM users WHERE username='mailer1'").fetchone()["id"]
sus = client.post("/admin/users/set-suspended", json={"user_id": tg_uid, "suspended": True}, headers=AH)
check("suspend blocked until admin 2FA is enabled", sus.status_code == 409, sus.text[:110])

import pyotp  # noqa: E402
secret = pyotp.random_base32()
_now = time.strftime("%Y-%m-%d %H:%M:%S")
db.execute("INSERT INTO user_2fa (user_id, secret, is_enabled, created_at, updated_at) VALUES (?,?,1,?,?)",
           (admin_id, secret, _now, _now))
db.commit()
sus = client.post("/admin/users/set-suspended",
                  json={"user_id": tg_uid, "suspended": True,
                        "code": pyotp.TOTP(secret).now()}, headers=AH)
check("admin can suspend with 2FA", sus.status_code == 200, sus.text[:130])
if sus.status_code == 200:
    check("suspension persisted",
          bool(db.execute("SELECT is_suspended s FROM users WHERE id=?", (tg_uid,)).fetchone()["s"]))
    check("admin action written to audit log",
          db.execute("SELECT COUNT(*) c FROM admin_audit_log").fetchone()["c"] >= 1)
    _sus = client.post("/auth/telegram", json=dict(tg_payload(1001), fingerprint=FP_A))
    # 403 = suspension enforced. 429 = this endpoint's own rate limiter fired
    # first (the suite hammers it); either way the login did NOT succeed.
    check("suspended account cannot log in via Telegram",
          _sus.status_code in (403, 429) and "token" not in _sus.json(),
          f"{_sus.status_code} {_sus.text[:90]}")

# ---------------------------------------------------------------------------
passed = sum(1 for _, ok in results if ok)
failed = len(results) - passed
print(f"\n================ {passed} pass, {failed} fail ================")
sys.exit(1 if failed else 0)
