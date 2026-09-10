"""The admin console must be invisible to everyone who is not an admin.

MEASURED BEFORE THIS WORK (both real leaks):

  1. GET /admin returned 200 with the full SPA shell to an ANONYMOUS visitor.
     "admin" sat in CLIENT_ONLY_PATHS, so the router served index.html to
     anyone. The spec asks for a plain 404; a 200 confirms the console exists
     to any stranger who guesses the URL.

  2. index.html SHIPPED the console's markup to every visitor: the
     <div id="tab-admin"> section (1798 chars, 14 adm* element ids) plus the
     nav button. The SPA removed them from the DOM after boot, but that is
     cosmetic — anyone could read them straight out of "view source".

  3. require_admin() answered 401 without a token and 404 with a non-admin
     token. That difference is itself a signal: it tells a stranger the route
     is real and merely gated.

The awkward constraint, stated plainly: the auth token lives in localStorage,
so a browser NAVIGATION carries no Authorization header and the server cannot
identify an admin at page-load time. A hard 404 for everyone would lock the
real admin out. So /admin serves a shell that is byte-identical to a
non-admin's /dashboard shell, under a 404 status. Nothing in the response
distinguishes it from an unknown URL; the SPA asks /profile after boot and
fetches the markup from a gated endpoint only if the session is admin.

Run:  DB_PATH=$(mktemp -d)/t.db python3 tests/test_admin_stealth.py
"""
import os
import sys
import tempfile
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# DB_PATH, not DATABASE_PATH — getting this wrong writes to the repo's real
# database.db, which is how an earlier run of this very test dirtied it.
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), uuid.uuid4().hex + ".db")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("RUNNER_SERVICE_SECRET", "test-secret")
os.environ.setdefault("LIVE_PORT_MIN", "17500")
os.environ.setdefault("LIVE_PORT_MAX", "17599")

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import database as DB  # noqa: E402
DB.init_db()

import app as A  # noqa: E402
from routes.deps import now_utc_str  # noqa: E402

client = TestClient(A.app, raise_server_exceptions=False)

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -> {extra}" if extra else ""))


def make_user(name, admin):
    conn = DB.get_db_connection()
    now = now_utc_str()
    pw = bcrypt.hashpw(b"x", bcrypt.gensalt()).decode()
    conn.execute(
        "INSERT INTO users (username,email,password,is_verified,is_admin,"
        "created_at,updated_at) VALUES (?,?,?,1,?,?,?)",
        (name, name + "@gmail.com", pw, 1 if admin else 0, now, now),
    )
    conn.commit()
    uid = conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]
    token = "tok-" + name
    conn.execute(
        "INSERT INTO sessions (user_id,token,created_at,last_seen) VALUES (?,?,?,?)",
        (uid, token, now, now),
    )
    conn.commit()
    conn.close()
    return token


ADMIN = make_user("boss", True)
USER = make_user("normal", False)
H = lambda t: {"Authorization": "Bearer " + t}          # noqa: E731

ANON, NORMAL = ({}, H(USER))
MARKERS = ("tab-admin", "tabBtnAdmin", "admOverview", "admLibs", "admJobs")


def leaks(text):
    return [m for m in MARKERS if m in text]


# ---------------------------------------------------------------------------
print("\n[1] /admin is a plain 404 for everyone but the admin")
# ---------------------------------------------------------------------------
for label, hdr in (("anonymous", ANON), ("normal user", NORMAL)):
    r = client.get("/admin", headers=hdr)
    check(f"{label}: /admin returns 404", r.status_code == 404, str(r.status_code))
    check(f"{label}: no admin markup in the body", not leaks(r.text),
          ",".join(leaks(r.text)))
    check(f"{label}: body says nothing about permissions",
          not any(w in r.text.lower() for w in
                  ("permission", "forbidden", "not authorized", "admin only")))

r_admin = client.get("/admin", headers=H(ADMIN))
check("admin: /admin returns 200", r_admin.status_code == 200, str(r_admin.status_code))
check("admin: markup IS present", len(leaks(r_admin.text)) >= 2, str(leaks(r_admin.text)))

# The 404 body must be indistinguishable from an ordinary page, not a special
# error screen that hints something is there.
r404 = client.get("/admin", headers=NORMAL)
r_dash = client.get("/dashboard", headers=NORMAL)
check("the 404 body matches a normal page shell byte-for-byte",
      r404.text == r_dash.text,
      f"{len(r404.text)} vs {len(r_dash.text)} bytes")

# ---------------------------------------------------------------------------
print("[2] the shell never ships admin markup to non-admins")
# ---------------------------------------------------------------------------
for path in ("/", "/dashboard", "/runspace", "/code"):
    for label, hdr in (("anonymous", ANON), ("normal user", NORMAL)):
        r = client.get(path, headers=hdr)
        check(f"{label}: {path} leaks no admin markup", not leaks(r.text),
              f"{path}: {','.join(leaks(r.text))}")

# The raw file still contains it; the stripping must happen on the way out.
raw = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
check("control: index.html itself still contains the section",
      'id="tab-admin"' in raw)
check("control: so the 200s above prove server-side stripping, not deletion",
      'id="tabBtnAdmin"' in raw)

# ---------------------------------------------------------------------------
print("[3] every admin API answers identically to non-admins")
# ---------------------------------------------------------------------------
ENDPOINTS = ["/admin/overview", "/admin/users", "/admin/jobs", "/admin/libraries",
             "/admin/audit-log", "/admin/abuse-reports", "/admin/panel-html"]
for ep in ENDPOINTS:
    a = client.get(ep, headers=ANON)
    n = client.get(ep, headers=NORMAL)
    check(f"{ep}: anonymous gets 404", a.status_code == 404, str(a.status_code))
    check(f"{ep}: normal user gets 404", n.status_code == 404, str(n.status_code))
    # If one said 401 and the other 404, the difference would confirm the
    # route exists and is merely gated.
    check(f"{ep}: both non-admins get the SAME status",
          a.status_code == n.status_code, f"{a.status_code} vs {n.status_code}")
    check(f"{ep}: admin gets through",
          client.get(ep, headers=H(ADMIN)).status_code == 200)

# An unknown URL should look the same as a gated one.
unknown = client.get("/definitely-not-a-real-route", headers=NORMAL)
check("a gated admin route matches an unknown route's status",
      client.get("/admin/overview", headers=NORMAL).status_code == unknown.status_code,
      str(unknown.status_code))

# ---------------------------------------------------------------------------
print("[4] destructive admin actions are gated too")
# ---------------------------------------------------------------------------
for label, hdr in (("anonymous", ANON), ("normal user", NORMAL)):
    r = client.post("/admin/users/set-suspended",
                    json={"user_id": 1, "suspended": True}, headers=hdr)
    check(f"{label}: cannot suspend accounts", r.status_code == 404, str(r.status_code))

conn = DB.get_db_connection()
still = conn.execute("SELECT is_suspended FROM users WHERE username='boss'").fetchone()
conn.close()
check("and no account was actually suspended", not dict(still)["is_suspended"])

# ---------------------------------------------------------------------------
print("[5] the client cannot be tricked into revealing it")
# ---------------------------------------------------------------------------
js = open(os.path.join(ROOT, "static/pro.js"), encoding="utf-8").read()
check("markup is fetched from the gated endpoint, not inlined",
      "/admin/panel-html" in js)
check("a failed fetch stays silent", ".catch(() => {})" in js)
check("only one fetch can be in flight", "_adminFetching" in js)
check("non-admins are bounced off the admin tab", 'switchTab("overview")' in js)
check("the /admin URL is scrubbed for non-admins",
      'history.replaceState({}, "", "/dashboard")' in js)

print(f"\ntest_admin_stealth: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
