"""Every INSERT must be valid on PostgreSQL, not only on SQLite.

THE PRODUCTION 500 THIS EXISTS FOR
----------------------------------
    File "/app/services/telegram_link.py", line 63, in issue_code
    psycopg2.errors.UndefinedColumn: column "id" does not exist
    LINE 1: ...,0,'2026-07-28T19:20:40.794627+00:00') RETURNING id

database.py's _Cursor.execute() appended " RETURNING id" to EVERY insert when
the dialect is Postgres, so that cursor.lastrowid would behave like SQLite's.
Three tables have no id column at all — they are keyed by the id of whatever
they hang off:

    term_homes           (user_id PRIMARY KEY)
    job_data_snapshots   (job_id  PRIMARY KEY)
    telegram_link_codes  (user_id PRIMARY KEY)

Every write to those three failed on Postgres and always had. It went unnoticed
because SQLite never takes that branch, so local runs and the whole test suite
passed, and because the two older call sites wrap their insert in a bare
try/except — the workspace-snapshot and terminal-home features had therefore
never once worked on the live site. The new /profile/telegram/code route did
not swallow it, which is the only reason it surfaced.

The fix must not be a hand-written list of three table names: the next id-less
table would reintroduce a bug that only appears in production. The set is
derived from the schema.

Run:  python3 tests/test_pg_returning_id.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DB_PATH", "/tmp/pg_returning_test.db")

import database as D  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -> {extra}" if extra else ""))


# ---------------------------------------------------------------------------
print("\n[1] the id-less tables are found from the schema, not hand-listed")
# ---------------------------------------------------------------------------
no_id = D._tables_without_id()
check("term_homes is recognised", "term_homes" in no_id, str(sorted(no_id)))
check("job_data_snapshots is recognised", "job_data_snapshots" in no_id)
check("telegram_link_codes is recognised", "telegram_link_codes" in no_id)
check("tables that DO have an id are not in the set",
      not ({"users", "jobs", "sessions", "snippets"} & no_id), str(sorted(no_id)))

# Independently re-derive it, so a regex that quietly stops matching is caught
# rather than agreeing with itself.
src = open(os.path.join(ROOT, "database.py"), encoding="utf-8").read()
expected = set()
for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n    \)", src, re.S):
    if not re.search(r"^\s*id\s", m.group(2), re.M):
        expected.add(m.group(1).lower())
check("the detection agrees with an independent parse of the file",
      no_id == expected, f"{sorted(no_id)} vs {sorted(expected)}")
check("the list is not hardcoded in the source",
      '"term_homes", "job_data_snapshots"' not in src
      and "'term_homes', 'job_data_snapshots'" not in src)

# ---------------------------------------------------------------------------
print("[2] the INSERT target is parsed correctly")
# ---------------------------------------------------------------------------
t = D._Cursor._insert_target
check("plain insert", t("INSERT INTO users (a) VALUES (?)") == "users")
check("lowercase", t("insert into users (a) values (?)") == "users")
check("leading whitespace/newline", t("\n   INSERT INTO jobs (a) VALUES (?)") == "jobs")
# runner/terminal.py really does use this form.
check("INSERT OR REPLACE", t("INSERT OR REPLACE INTO term_homes(user_id) VALUES (?)")
      == "term_homes")
check("INSERT OR IGNORE", t("INSERT OR IGNORE INTO users (a) VALUES (?)") == "users")
check("no space before the paren", t("INSERT INTO term_homes(user_id) VALUES (?)")
      == "term_homes")
check("a non-insert yields nothing", t("SELECT * FROM users") == "")

# ---------------------------------------------------------------------------
print("[3] what is actually SENT to Postgres")
# ---------------------------------------------------------------------------
SENT = []


class _FakeCur:
    lastrowid = None

    def execute(self, sql, params):
        SENT.append(sql)

    def fetchone(self):
        return {"id": 7}


_saved_dialect = D.DIALECT
D.DIALECT = "postgres"          # force the branch production takes
try:
    cur = D._Cursor(_FakeCur())

    for sql in ("INSERT INTO users (username) VALUES (?)",
                "INSERT INTO jobs (name) VALUES (?)",
                "INSERT INTO sessions (user_id) VALUES (?)"):
        SENT.clear()
        cur.execute(sql, ("x",))
        check(f"id table still gets RETURNING id: {D._Cursor._insert_target(sql)}",
              SENT[-1].endswith("RETURNING id"), SENT[-1][:70])
    check("and lastrowid still yields the new id", cur.lastrowid == 7, str(cur.lastrowid))

    for sql in ("INSERT INTO telegram_link_codes (user_id, code) VALUES (?,?)",
                "INSERT OR REPLACE INTO term_homes(user_id,tarball_b64) VALUES (?,?)",
                "INSERT INTO job_data_snapshots (job_id, tarball_b64) VALUES (?,?)"):
        SENT.clear()
        cur.execute(sql, ("x", "y"))
        tbl = D._Cursor._insert_target(sql)
        check(f"id-less table gets NO RETURNING id: {tbl}",
              "RETURNING id" not in SENT[-1], SENT[-1][:80])
        check(f"lastrowid is None for {tbl}, not a stale value",
              cur.lastrowid is None, str(cur.lastrowid))

    # A stale id would be worse than None: a caller would silently write the
    # previous row's id somewhere.
    SENT.clear()
    cur.execute("INSERT INTO users (a) VALUES (?)", ("x",))
    check("control: the id path repopulates lastrowid", cur.lastrowid == 7)
    cur.execute("INSERT INTO term_homes(user_id) VALUES (?)", ("x",))
    check("and the id-less path clears it again", cur.lastrowid is None)
finally:
    D.DIALECT = _saved_dialect

# ---------------------------------------------------------------------------
print("[4] no INSERT anywhere in the app targets an unknown table")
# ---------------------------------------------------------------------------
# The guard only works if every insert's table is one the schema declares. An
# insert into a table created outside _SCHEMA_TABLES would be classified as
# "has an id" by default and 500 exactly as before.
# [a-z_]+ was wrong: it truncates user_2fa to "user_" and then reports a table
# that does not exist. Digits are part of an identifier.
out = subprocess.run(
    ["grep", "-rhoE", r"INSERT (OR [A-Z]+ )?INTO [a-z_][a-z0-9_]*",
     "--include=*.py", "--exclude-dir=tests", ROOT],
    capture_output=True, text=True).stdout
targets = {line.split()[-1].lower() for line in out.strip().splitlines()}
declared = set()
for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)", src):
    declared.add(m.group(1).lower())
unknown = targets - declared
check("every INSERT target is a declared table", not unknown, str(sorted(unknown)))
check("user_2fa survives the sweep intact (the regex used to cut it at the digit)",
      "user_2fa" in targets, str(sorted(targets)))
check("the sweep actually found the inserts", len(targets) >= 8, str(len(targets)))

# And the three known-broken ones are genuinely covered.
for tbl in ("term_homes", "job_data_snapshots", "telegram_link_codes"):
    check(f"{tbl} is written to somewhere in the app", tbl in targets, str(sorted(targets)))

# ---------------------------------------------------------------------------
print("[5] INSERT OR REPLACE is really translated, not just claimed")
# ---------------------------------------------------------------------------
# The module docstring said "upsert  INSERT OR REPLACE -> INSERT ... ON
# CONFLICT". It did not. Postgres answers `syntax error at or near "OR"`, so
# runner/terminal.py's home snapshot failed on every single call — silently,
# because that insert sits in a bare try/except.
D.DIALECT = "postgres"
try:
    t = D._translate_sql(
        "INSERT OR REPLACE INTO term_homes(user_id,tarball_b64,updated_at) VALUES (?,?,?)")
    check("the SQLite-only OR REPLACE is gone", "OR REPLACE" not in t, t[:80])
    check("it became an upsert", "ON CONFLICT (user_id) DO UPDATE" in t, t[:120])
    check("the non-key columns are the ones updated",
          "tarball_b64 = EXCLUDED.tarball_b64" in t and "updated_at = EXCLUDED.updated_at" in t,
          t)
    check("the key column is not written to itself",
          "user_id = EXCLUDED.user_id" not in t, t)
    check("INSERT OR IGNORE is handled too",
          "OR IGNORE" not in D._translate_sql("INSERT OR IGNORE INTO users (a) VALUES (?)"))

    # The upsert guesses the conflict target from the first column. That is
    # only correct while every OR REPLACE targets a table whose PRIMARY KEY is
    # its first column — check it against the schema instead of trusting it.
    for m in re.finditer(r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]*)\)",
                         "\n".join(
                             open(os.path.join(ROOT, f), encoding="utf-8").read()
                             for f in ("runner/terminal.py", "routes/auth.py")), re.I):
        tbl, first_col = m.group(1).lower(), m.group(2).split(",")[0].strip()
        ddl = re.search(
            r"CREATE TABLE IF NOT EXISTS " + tbl + r"\s*\((.*?)\n    \)", src, re.S | re.I)
        # Postgres accepts a conflict target that is a PRIMARY KEY *or* a
        # single-column UNIQUE. user_2fa is the second case: it has its own
        # id, and user_id is UNIQUE. Requiring PRIMARY KEY alone made this
        # test fail on a statement that is actually fine.
        body = ddl.group(1) if ddl else ""
        valid = bool(re.search(rf"^\s*{first_col}\b[^,]*(PRIMARY KEY|UNIQUE)", body,
                               re.M | re.I))
        check(f"{tbl}: the upsert's conflict target is enforced by a constraint",
              valid, f"{tbl}.{first_col}")

    # And every translated statement must actually parse as PostgreSQL.
    try:
        import pglast
        for q in ("INSERT OR REPLACE INTO term_homes(user_id,tarball_b64,updated_at) VALUES (?,?,?)",
                  "INSERT INTO telegram_link_codes (user_id, code, expires_at, attempts, created_at) VALUES (?,?,?,?,?)",
                  "INSERT INTO job_data_snapshots (job_id, tarball_b64, file_count, byte_size, updated_at) VALUES (?,?,?,?,?)",
                  "INSERT INTO users (username, email) VALUES (?,?)"):
            tq = D._translate_sql(q).replace("%s", "$1")
            try:
                pglast.parse_sql(tq)
                ok_parse = True
            except Exception as exc:
                ok_parse = False
                detail = str(exc)[:70]
            check(f"PostgreSQL parses: {D._Cursor._insert_target(q)}",
                  ok_parse, locals().get("detail", ""))
    except ImportError:
        print("  (pglast not installed — skipped the real parse)")
finally:
    D.DIALECT = _saved_dialect

print(f"\ntest_pg_returning_id: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
