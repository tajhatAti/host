#!/usr/bin/env python3
"""
migrate_to_supabase.py — Copy your local SQLite database into PostgreSQL (Supabase).

This lets you move ALL existing users, sessions, vault entries, notes, bookmarks,
2FA settings, etc. from your old local SQLite file into your new permanent
PostgreSQL database (e.g. Supabase free tier) without losing anything.

USAGE
-----
1. Make sure your app can already talk to Postgres:
       export DATABASE_URL='postgresql://postgres.<proj>:<pw>@aws-0-<reg>.pooler.supabase.com:5432/postgres'

2. Point at your source SQLite file (default: ./database.db):
       export DB_PATH='/path/to/database.db'

3. (First run) Create the schema in Postgres:
       python migrate_to_supabase.py --init-schema

4. Copy the data:
       python migrate_to_supabase.py

The script is safe to re-run: by default it TRUNCATEs the destination tables
(within one transaction) before copying, so ids stay consistent. Nothing is
committed until every table copies successfully; on any error it rolls back.

NOTES
-----
* Primary-key ids and foreign-key relationships are preserved exactly.
* After copying, each table's SERIAL sequence is advanced past the max id, so
  new rows created by the app will not collide.
* Your SQLite source file is opened READ-ONLY and is never modified.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Table definitions in dependency order (parents first).
# Each entry: (table_name, [columns...])
# ---------------------------------------------------------------------------
TABLES = [
    ("users", [
        "id", "username", "email", "password", "otp", "otp_created_at",
        "is_verified", "reset_otp", "reset_otp_created_at", "reset_verified",
        "role", "phone", "custom_code", "links", "created_at", "updated_at",
    ]),
    ("sessions", [
        "id", "user_id", "token", "device_info", "ip_address", "created_at", "last_seen",
    ]),
    ("vault_entries", [
        "id", "user_id", "type", "label", "value", "created_at", "updated_at",
    ]),
    ("user_2fa", [
        "id", "user_id", "secret", "is_enabled", "backup_codes", "created_at", "updated_at",
    ]),
    ("login_history", [
        "id", "user_id", "ip_address", "device_info", "location", "success", "created_at",
    ]),
    ("user_preferences", [
        "id", "user_id", "theme", "language", "timezone", "notifications_enabled",
        "email_notifications", "created_at", "updated_at",
    ]),
    ("user_notes", [
        "id", "user_id", "title", "content", "color", "pinned", "created_at", "updated_at",
    ]),
    ("user_bookmarks", [
        "id", "user_id", "title", "url", "description", "category", "created_at", "updated_at",
    ]),
    ("user_categories", [
        "id", "user_id", "name", "icon", "color", "created_at",
    ]),
    ("api_keys", [
        "id", "user_id", "name", "key_hash", "last_used", "created_at",
    ]),
    ("activity_log", [
        "id", "user_id", "action", "details", "ip_address", "created_at",
    ]),
    ("notifications", [
        "id", "user_id", "type", "title", "message", "is_read", "created_at",
    ]),
    ("user_cards", [
        "id", "user_id", "label", "holder", "number", "expiry", "cvv", "brand", "note", "color", "created_at", "updated_at",
    ]),
    ("user_tasks", [
        "id", "user_id", "title", "completed", "priority", "created_at", "updated_at",
    ]),
    ("user_identities", [
        "id", "user_id", "type", "label", "fields", "created_at", "updated_at",
    ]),
    ("user_contacts", [
        "id", "user_id", "name", "email", "phone", "company", "address", "note", "created_at", "updated_at",
    ]),
    ("user_wifi", [
        "id", "user_id", "label", "ssid", "password", "security", "hidden", "location", "created_at", "updated_at",
    ]),
    ("user_servers", [
        "id", "user_id", "name", "host", "port", "username", "password", "keyfile", "note", "created_at", "updated_at",
    ]),
    ("user_recovery", [
        "id", "user_id", "label", "words", "word_count", "created_at", "updated_at",
    ]),
    ("snippets", [
        "id", "user_id", "title", "language", "content", "share_token", "is_public", "views", "created_at", "updated_at",
    ]),
]


def read_sqlite_rows(sqlite_path: Path):
    """Yield (table, columns, rows) for every table that exists in SQLite."""
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        for table, cols in TABLES:
            try:
                cur = conn.execute(f"SELECT {', '.join(cols)} FROM {table}")
            except sqlite3.OperationalError:
                # Table doesn't exist in this (older) SQLite file — skip it.
                continue
            rows = [tuple(r[c] for c in cols) for r in cur.fetchall()]
            yield table, cols, rows
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Migrate SQLite -> PostgreSQL (Supabase)")
    ap.add_argument("--db-path", default=os.getenv("DB_PATH", "database.db"),
                    help="Source SQLite file (default: $DB_PATH or ./database.db)")
    ap.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""),
                    help="Destination PostgreSQL URL (default: $DATABASE_URL)")
    ap.add_argument("--init-schema", action="store_true",
                    help="Create tables in Postgres via the app's init_db() before copying")
    ap.add_argument("--no-truncate", action="store_true",
                    help="Do NOT clear destination tables first (errors if ids clash)")
    ap.add_argument("--force", action="store_true",
                    help="Skip the interactive confirmation")
    args = ap.parse_args()

    if not args.database_url or not args.database_url.startswith(("postgres://", "postgresql://")):
        print("ERROR: set DATABASE_URL to a postgresql://... URL (or pass --database-url).")
        sys.exit(2)

    sqlite_path = Path(args.db_path)
    if not sqlite_path.exists():
        print(f"ERROR: source SQLite file not found: {sqlite_path}")
        sys.exit(2)

    print(f"Source (SQLite)  : {sqlite_path}")
    print(f"Destination (PG) : {args.database_url.split('@')[-1] if '@' in args.database_url else '(url set)'}")
    if args.init_schema:
        print("Mode             : init schema + copy data")
    else:
        print("Mode             : copy data only (schema must already exist)")
    if not args.no_truncate:
        print("WARNING: destination tables will be TRUNCATED (RESTART IDENTITY CASCADE).")
    if not args.force:
        if input("\nProceed? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)

    # Optionally create schema using the app's own init_db (guarantees parity)
    if args.init_schema:
        os.environ["DATABASE_URL"] = args.database_url
        import database
        database.init_db()
        print("Schema ensured in PostgreSQL.")

    # Connect to Postgres directly for the bulk copy
    import psycopg2
    connect_kwargs = {}
    if "sslmode" not in args.database_url:
        connect_kwargs["sslmode"] = os.getenv("PG_SSLMODE", "prefer")
    pg = psycopg2.connect(args.database_url, **connect_kwargs)
    pg.autocommit = False
    cur = pg.cursor()

    total = 0
    try:
        if not args.no_truncate:
            names = ", ".join(t for t, _ in TABLES)
            cur.execute(f"TRUNCATE {names} RESTART IDENTITY CASCADE")
            print(f"Truncated: {names}")

        for table, cols, rows in read_sqlite_rows(sqlite_path):
            if not rows:
                print(f"  {table:<20} 0 rows (skipped)")
                continue
            placeholders = ", ".join(["%s"] * len(cols))
            col_list = ", ".join(cols)
            cur.executemany(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
                rows,
            )
            print(f"  {table:<20} {len(rows)} rows copied")
            total += len(rows)

        # Advance each SERIAL sequence past the highest id we just inserted.
        for table, cols in TABLES:
            if "id" in cols:
                cur.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    "COALESCE((SELECT MAX(id) FROM {t}), 1), true)".format(t=table),
                    (table,),
                )

        pg.commit()
        print(f"\n✅ Migration complete — {total} rows copied. Transaction committed.")
    except Exception as exc:
        pg.rollback()
        print(f"\n❌ Migration FAILED and was rolled back: {exc}")
        raise
    finally:
        cur.close()
        pg.close()


if __name__ == "__main__":
    main()
