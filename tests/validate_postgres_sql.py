"""Validate that every SQL statement the app sends is valid PostgreSQL.

No live Postgres server needed: collect every string literal from app.py,
database.py and the Bot Store modules, apply the EXACT transformations the wrapper performs when
DIALECT == 'postgres', then parse each with pglast (the real PostgreSQL grammar).
"""
import ast
import os
import re
import sys

import pglast

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Match strings that really are SQL statements (word-boundary on first keyword),
# so dict keys like "created_at" or prose like "INSERT RETURNING id" are excluded.
SQL_RE = re.compile(
    r"^\s*(?:"
    r"SELECT\s+|UPDATE\s+|DELETE\s+|"
    r"INSERT\s+(?:INTO|OR)\s+|"
    r"CREATE\s+(?:TABLE|EXTENSION|UNIQUE|INDEX)\b|"
    r"ALTER\s+TABLE\s+|PRAGMA\s+"
    r")",
    re.IGNORECASE,
)
# SQLite-only constructs that are never sent to PostgreSQL (the app branches to
# a PG-equivalent instead), so they should not be validated as PG.
SQLITE_ONLY_MARKERS = (" OR REPLACE ",)

SQL_STATEMENTS = []
DOCSTRING_IDS = set()
FSTRING_PART_IDS = set()


def _mark_fstring_parts(tree):
    """Record the literal chunks of every f-string.

    An f-string like f"{lead}INSERT INTO {table} ({cols}){rest}" is stored as
    JoinedStr, and ast.walk() hands back its plain-text pieces as separate
    Constant nodes. Reassembled without the placeholders they read as
    "INSERT INTO  RETURNING id" — a statement that is never executed and
    cannot parse. Skipping the pieces is right: the f-string is validated by
    the runtime tests that call _translate_sql for real.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    FSTRING_PART_IDS.add(id(part))


def _mark_docstrings(tree):
    """Record id() of docstring Constant nodes so we can skip them."""
    containers = []
    containers.extend(getattr(tree, "body", []) or [])
    stack = list(getattr(tree, "body", []) or [])
    # collect all function/class/module nodes
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                DOCSTRING_IDS.add(id(body[0].value))


def collect_from(path):
    src = open(path).read()
    tree = ast.parse(src, filename=path)
    _mark_docstrings(tree)
    _mark_fstring_parts(tree)
    base = os.path.basename(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in DOCSTRING_IDS or id(node) in FSTRING_PART_IDS:
                continue
            s = node.value
            # A REGEX that describes SQL is not SQL. database.py now derives
            # its id-less-table set by matching CREATE TABLE text, and parses
            # an INSERT's target the same way — both literals start with a SQL
            # keyword and are not statements. Backslash escapes and the
            # capture-group syntax only ever appear in the pattern, never in a
            # real query in this codebase.
            if "\\" in s or "(?:" in s or "(.*?)" in s or "[A-Za-z_]" in s:
                continue

            if SQL_RE.match(s):
                SQL_STATEMENTS.append((base, s))


# The Bot Store owns its own tables and queries, so it is scanned too: it is
# the newest place where SQLite-only syntax could sneak into a statement that
# only ever runs on PostgreSQL, i.e. only in production.
for f in ("app.py", "database.py", "services/store.py", "routes/store.py"):
    collect_from(os.path.join(ROOT, f))


def _libpq_to_dollar(sql):
    """libpq %s placeholders -> server-side $1,$2,... for grammar parsing."""
    out, n, i = [], 1, 0
    while i < len(sql):
        if sql[i] == "%" and i + 1 < len(sql) and sql[i + 1] == "s":
            out.append(f"${n}"); n += 1; i += 2
        else:
            out.append(sql[i]); i += 1
    return "".join(out)


def to_pg(sql):
    """Force PostgreSQL transformation regardless of current DIALECT."""
    if sql.lstrip().upper().startswith("CREATE"):
        sql = sql.replace("TEXT NOT NULL UNIQUE COLLATE NOCASE", "CITEXT NOT NULL UNIQUE")
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    else:
        sql = sql.replace("?", "%s")  # qmark -> libpq
        if sql.lstrip()[:6].upper() == "INSERT":
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
    return _libpq_to_dollar(sql)


print(f"Collected {len(SQL_STATEMENTS)} SQL statements. Parsing each as PostgreSQL...\n")

skipped_sqlite_only = errors = checked = 0
for src, raw in SQL_STATEMENTS:
    if raw.lstrip().upper().startswith("PRAGMA"):
        skipped_sqlite_only += 1
        continue
    if any(m in raw.upper() for m in SQLITE_ONLY_MARKERS):
        # e.g. INSERT OR REPLACE — SQLite-only; app emits ON CONFLICT for PG
        skipped_sqlite_only += 1
        continue
    pg_sql = to_pg(raw)
    label = " ".join(pg_sql.split())[:95]
    try:
        pglast.parse_sql(pg_sql)
        checked += 1
    except Exception as e:  # noqa: BLE001
        errors += 1
        print(f"FAIL [{src}] {label}\n      -> {e}\n      full: {pg_sql!r}\n")

print(f"Parsed OK : {checked}")
print(f"Skipped   : {skipped_sqlite_only} (SQLite-only PRAGMA, never sent to PG)")
print(f"Errors    : {errors}")
sys.exit(1 if errors else 0)
