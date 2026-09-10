"""Behaviour checks for durable Telegram usage recording and admin exports."""
import importlib
import os
import tempfile
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

import database
database.init_db()
from services import bot_analytics


def reset():
    c = database.get_db_connection(); c.execute("DELETE FROM bot_events"); c.commit(); c.close()


def test_record_counts_distinct_chats_and_unlinked_people():
    reset()
    c = database.get_db_connection()
    c.execute("INSERT INTO users (username,email,password,created_at,updated_at) VALUES (?,?,?,?,?)",
              ("linked", "linked@example.com", "x", "2026-01-01", "2026-01-01"))
    c.commit()
    uid = dict(c.execute("SELECT id FROM users WHERE username='linked'").fetchone())["id"]
    c.close()
    bot_analytics.record(chat_id=10, event_type="command", command="/start", display_name="A")
    bot_analytics.record(chat_id=10, event_type="command", command="/apps", display_name="A", user_id=uid)
    bot_analytics.record(chat_id=11, event_type="command", command="/start", display_name="B")
    out = bot_analytics.usage(7)
    assert out["people"] == 2
    assert out["actions"] == 3
    assert out["linked_people"] == 1
    assert out["unlinked_people"] == 1


def test_failure_and_command_rollup():
    reset()
    bot_analytics.record(chat_id=1, event_type="command", command="/logs", outcome="error", error="boom")
    out = bot_analytics.usage(30)
    assert out["failures"] == 1
    assert out["commands"] == [{"command": "/logs", "count": 1, "failures": 1}]


def test_csv_quotes_untrusted_names_and_has_bom():
    reset()
    bot_analytics.record(chat_id=1, event_type="command", command="/start", display_name='A, "B"\nC')
    value = bot_analytics.usage_csv(30)
    assert value.startswith("\ufeff")
    assert '"A, ""B""\nC"' in value


def test_record_never_raises_when_database_is_down(monkeypatch):
    monkeypatch.setattr(bot_analytics, "get_db_connection", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    bot_analytics.record(chat_id=1, event_type="command", command="/start")
