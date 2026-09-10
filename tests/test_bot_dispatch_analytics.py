import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("TELEGRAM_PING_BOT_TOKEN", "123:fake")

from services import pingbot


def message(text):
    return {"update_id": 1, "message": {"chat": {"id": 44}, "from": {"id": 55, "first_name": "Ada"}, "text": text}}


def test_group_command_is_dispatched_and_recorded(monkeypatch):
    calls, events = [], []
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat", lambda _chat: {"id": 9, "username": "ada"})
    monkeypatch.setattr(pingbot, "cmd_logs", lambda chat, user, arg: calls.append((chat, user["id"], arg)))
    monkeypatch.setattr(pingbot.bot_analytics, "record", lambda **event: events.append(event))
    pingbot.handle_update(message("/logs@MyBot my-app"))
    assert calls == [(44, 9, "my-app")]
    assert events[0]["command"] == "/logs"
    assert events[0]["payload"] == "my-app"


def test_stopall_does_not_match_stop(monkeypatch):
    stopped, sent, events = [], [], []
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat", lambda _chat: {"id": 9})
    monkeypatch.setattr(pingbot, "cmd_stop", lambda *args: stopped.append(args))
    monkeypatch.setattr(pingbot, "_send", lambda *args, **kwargs: sent.append(args))
    monkeypatch.setattr(pingbot.bot_analytics, "record", lambda **event: events.append(event))
    pingbot.handle_update(message("/stopall"))
    assert stopped == []
    assert sent and events[0]["outcome"] == "unknown"


def test_crash_is_recorded_and_analytics_cannot_replace_it(monkeypatch):
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat", lambda _chat: {"id": 9})
    monkeypatch.setattr(pingbot, "cmd_logs", lambda *args: (_ for _ in ()).throw(ValueError("handler broke")))
    events = []
    monkeypatch.setattr(pingbot.bot_analytics, "record", lambda **event: events.append(event))
    try:
        pingbot.handle_update(message("/logs app"))
    except ValueError:
        pass
    else:
        raise AssertionError("handler exception was swallowed")
    assert events[0]["outcome"] == "error" and "handler broke" in events[0]["error"]

    monkeypatch.setattr(pingbot, "cmd_logs", lambda *args: None)
    monkeypatch.setattr(pingbot.bot_analytics, "record", lambda **event: (_ for _ in ()).throw(RuntimeError("db")))
    pingbot.handle_update(message("/logs app"))
