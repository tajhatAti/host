# LEGACY-DATABASE MIGRATION — production login outage regression.
#
# Production crashed on every sign-in with:
#     psycopg2.errors.UndefinedColumn: column "fingerprint" does not exist
#
# Cause: users.telegram_id / users.fingerprint / users.last_ip and
# sessions.fingerprint were added to the CREATE TABLE statements (so a FRESH
# database had them) but no ALTER was ever added for EXISTING databases. The
# live Postgres instance predated those columns, so create_session() wrote to
# columns that were not there.
#
# Two independent guarantees are asserted here:
#   1. init_db() upgrades a legacy schema by adding the missing columns.
#   2. Sign-in still works even when the migration CANNOT run (read-only DB,
#      insufficient grants) — the fingerprint/IP telemetry is best-effort and
#      must never be able to take authentication down again.
import os
import sqlite3
import sys
import tempfile

DB = tempfile.mktemp(suffix=".db")
os.environ["DB_PATH"] = DB
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ["SIGNUP_DAILY_MAX"] = "50"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A pre-migration schema: exactly the columns the old deployment had.
LEGACY = """
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
  otp TEXT, otp_created_at TEXT, is_verified INTEGER NOT NULL DEFAULT 0,
  reset_otp TEXT, reset_otp_created_at TEXT, reset_verified INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
  token TEXT NOT NULL UNIQUE, device_info TEXT, ip_address TEXT,
  created_at TEXT NOT NULL, last_seen TEXT NOT NULL
);
"""

_c = sqlite3.connect(DB)
_c.executescript(LEGACY)
_c.commit()


def cols(table):
    return [r[1] for r in _c.execute(f"PRAGMA table_info({table})")]


results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("\u2713 " if cond else "\u2717 FAIL ") + f"{name:56s}" + (f" \u2014 {extra}" if not cond else ""))


print("\n--- before migration ---")
check("legacy users has NO fingerprint", "fingerprint" not in cols("users"))
check("legacy sessions has NO fingerprint", "fingerprint" not in cols("sessions"))

# init_db() runs on import of routes.deps / app.
import services.email as _email_svc  # noqa: E402
_email_svc.send_email = lambda *a, **k: None
from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402
import routes.deps as deps  # noqa: E402

client = TestClient(app)

print("\n--- after migration ---")
for table, column in (("users", "telegram_id"), ("users", "fingerprint"),
                      ("users", "last_ip"), ("sessions", "fingerprint"),
                      ("sessions", "expires_at")):
    check(f"{table}.{column} added", column in cols(table), str(cols(table)))

print("\n--- auth works on the upgraded legacy DB ---")
r = client.post("/signup", json={"username": "legacy1", "email": "legacy1@gmail.com",
                                 "password": "Str0ng!Pass9", "agreed_terms": True,
                                 "captcha": "12", "fingerprint": '{"dev":"a"}'})
check("signup", r.status_code == 200, r.text[:120])
_c.row_factory = sqlite3.Row
otp = _c.execute("SELECT otp FROM users WHERE username='legacy1'").fetchone()["otp"]
check("verify", client.post("/verify", json={"username": "legacy1", "otp": otp,
                                             "fingerprint": '{"dev":"a"}'}).status_code == 200)
login = client.post("/login", json={"username": "legacy1", "password": "Str0ng!Pass9",
                                    "fingerprint": '{"dev":"a"}'})
check("LOGIN succeeds (was a 500 in production)", login.status_code == 200, login.text[:160])
check("session token issued", bool(login.json().get("token")))
check("fingerprint recorded on the account",
      bool(_c.execute("SELECT fingerprint FROM users WHERE username='legacy1'").fetchone()["fingerprint"]))

print("\n--- auth survives when the migration CANNOT run ---")
_orig = deps._ensure_column


def _boom(*a, **k):
    raise Exception("ALTER denied (read-only database)")


deps._ensure_column = _boom
try:
    hard = client.post("/login", json={"username": "legacy1", "password": "Str0ng!Pass9",
                                       "fingerprint": '{"dev":"b"}'})
    check("login still succeeds when ALTER fails", hard.status_code == 200, hard.text[:160])
    check("token still issued", bool(hard.json().get("token")))
finally:
    deps._ensure_column = _orig

# The telemetry columns are optional; the session row itself is mandatory.
check("session rows persisted",
      _c.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"] >= 2)

passed = sum(1 for _, ok in results if ok)
failed = len(results) - passed
print(f"\n================ {passed} pass, {failed} fail ================")
sys.exit(1 if failed else 0)
