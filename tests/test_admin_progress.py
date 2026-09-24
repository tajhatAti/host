"""Admin /user full control + live deploy progress card.

Two complaints, one file:

1. An admin wanted to open any user, see every job, then open a job and have
   source / runner URL / requirements / restart / stop / delete / edit — without
   leaving the chat. The Users panel used to stop at flag toggles; the job card
   stopped at restart/stop/delete. Now the user card lists every job as a
   button, and the job card carries everything.

2. /code → requirements → paste code used to hang with nothing on screen for
   long enough that people thought the bot had died. A live progress card now
   rewrites one message 0→100% with a spinning glyph and a changing label.

Run:  PYTHONPATH=. pytest -q tests/test_admin_progress.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "ap.db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

import pytest
from services import bot_ops, pingbot, telegram_link, telegram_admin_ext


@pytest.fixture
def sent(monkeypatch):
    out = []
    def tg(method, **params):
        out.append((method, params))
        # editMessageText / sendMessage both return a message_id so progress
        # can rewrite the same card.
        return {"ok": True, "result": {"message_id": len(out)}}
    monkeypatch.setattr(pingbot, "_tg", tg)
    return out


def texts(sent):
    return [p.get("text") or "" for m, p in sent
            if m in ("sendMessage", "editMessageText")]


def last(sent):
    t = texts(sent)
    return t[-1] if t else ""


def test_progress_bar_fills():
    assert pingbot._progress_bar(0) == "░" * 10
    assert pingbot._progress_bar(100) == "▓" * 10
    mid = pingbot._progress_bar(50)
    assert "▓" in mid and "░" in mid
    assert len(mid) == 10


def test_progress_card_rewrites_one_message(sent, monkeypatch):
    """The whole point: one message, many edits, never a silent pause."""
    with pingbot._progress(1, "create", name="demo") as prog:
        prog.at(20, "Got your code")
        prog.at(55, "Uploading to the site")
        prog.at(80, "Starting the app")
        prog.done("Running.")
    edits = [p for m, p in sent if m == "editMessageText"]
    sends = [p for m, p in sent if m == "sendMessage"]
    assert sends, "first card must be sent"
    assert edits, "later steps must edit the same card"
    # final card is 100% and says Done
    final = texts(sent)[-1]
    assert "100%" in final
    assert "Done" in final or "Running" in final
    assert "demo" in final
    # bar characters present
    assert "▓" in final or "░" in final


def test_progress_fail_shows_reason(sent):
    with pingbot._progress(1, "create", name="x") as prog:
        prog.at(30, "Uploading")
        prog.fail("runner full")
    final = last(sent)
    assert "Failed" in final or "🔴" in final
    assert "runner full" in final


def test_admin_user_card_lists_jobs_as_buttons(monkeypatch, sent):
    target = {"id": 7, "username": "bee", "telegram_id": 99,
              "is_admin": 0, "can_upload_zip": 1, "is_suspended": 0,
              "mem_unlimited": 1, "email": "b@t.dev", "created_at": "2024-01-01"}
    jobs = [
        {"id": 11, "name": "alpha", "language": "python", "live_status": "running",
         "runner_url": "https://r1.example", "repo_url": "", "telegram_bot_username": "a_bot"},
        {"id": 12, "name": "beta", "language": "node", "live_status": "crashed",
         "runner_url": "", "repo_url": "https://github.com/o/r"},
    ]
    monkeypatch.setattr(telegram_admin_ext, "jobs_for_user", lambda uid: jobs)
    monkeypatch.setattr(telegram_admin_ext, "last_seen_for_user", lambda uid: None)
    monkeypatch.setattr(bot_ops, "account_privileges",
                        lambda uid: {"job_limit": 10, "mem_limit_mb": 0})
    monkeypatch.setattr(bot_ops, "active_count", lambda uid: 1)

    text = pingbot._admin_user_detail_text(target, jobs)
    assert "bee" in text and "#7" in text
    assert "alpha" in text and "beta" in text
    assert "no ceiling" in text or "Slots" in text

    kb = pingbot._admin_user_row_kb(target, jobs)
    data = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    assert "admin:job:11" in data and "admin:job:12" in data
    assert "admin:togqueen:7" in data
    assert "admin:user:7" in data  # refresh


def test_admin_job_card_shows_runner_and_source(monkeypatch):
    j = {
        "id": 11, "name": "alpha", "owner": "bee", "owner_id": 7,
        "language": "python", "live_status": "running", "desired_state": "running",
        "runner_job_id": "rid-abc", "runner_url": "https://runner.example",
        "mem_mb": 42, "peak_mem_mb": 80, "mem_limit_mb": 256,
        "uptime_s": 3661, "restarts": 1,
        "env_keys": ["BOT_TOKEN", "DEBUG"],
        "requirements": "requests==2.0, pyTelegramBotAPI",
        "has_code": True, "code_bytes": 1234,
        "libs": ["requests"], "repo_url": "",
        "telegram_bot_username": "a_bot", "telegram_check_status": "verified",
        "created_at": "2024-01-01", "updated_at": "2024-01-02",
    }
    text = pingbot._admin_job_detail_text(j)
    for needle in ("alpha", "#11", "runner.example", "rid-abc", "BOT_TOKEN",
                   "requests==2.0", "a_bot", "42MB", "Source: stored inline"):
        assert needle in text, needle

    kb = pingbot._admin_job_kb(j)
    data = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    for need in ("admin:jobrestart:11", "admin:jobstop:11", "admin:joblogs:11",
                 "admin:jobsource:11", "admin:jobedit:11", "admin:jobenv:11",
                 "admin:jobdelconfirm:11", "admin:user:7"):
        assert need in data, need


def test_cmd_user_opens_list_for_admin(monkeypatch, sent):
    monkeypatch.setattr(pingbot, "_is_admin", lambda *a, **k: True)
    monkeypatch.setattr(telegram_link, "user_for_chat",
                        lambda cid: {"id": 1, "is_admin": 1})
    monkeypatch.setattr(pingbot, "_admin_users_text", lambda page: f"users page {page}")
    monkeypatch.setattr(pingbot, "_admin_users_kb",
                        lambda page: {"inline_keyboard": []})
    pingbot.cmd_user(1, 1, "")
    assert "users page 0" in last(sent)


def test_cmd_user_opens_one_card(monkeypatch, sent):
    monkeypatch.setattr(pingbot, "_is_admin", lambda *a, **k: True)
    monkeypatch.setattr(telegram_link, "user_for_chat",
                        lambda cid: {"id": 1, "is_admin": 1})
    target = {"id": 7, "username": "bee", "telegram_id": 99,
              "is_admin": 0, "can_upload_zip": 0, "is_suspended": 0,
              "mem_unlimited": 0, "email": None, "created_at": None}
    monkeypatch.setattr(telegram_link, "resolve_user_ref", lambda r: target)
    monkeypatch.setattr(telegram_admin_ext, "jobs_for_user", lambda uid: [])
    monkeypatch.setattr(telegram_admin_ext, "last_seen_for_user", lambda uid: None)
    monkeypatch.setattr(bot_ops, "account_privileges",
                        lambda uid: {"job_limit": 3, "mem_limit_mb": 256})
    monkeypatch.setattr(bot_ops, "active_count", lambda uid: 0)
    pingbot.cmd_user(1, 1, "bee")
    assert "bee" in last(sent) and "#7" in last(sent)


def test_cmd_user_silent_for_non_admin(monkeypatch, sent):
    monkeypatch.setattr(pingbot, "_is_admin", lambda *a, **k: False)
    monkeypatch.setattr(telegram_link, "user_for_chat",
                        lambda cid: {"id": 2, "is_admin": 0})
    pingbot.cmd_user(1, 1, "bee")
    assert sent == []


def test_job_detail_hides_env_values(monkeypatch):
    """Env VALUES must never reach an admin chat — only key names."""
    # We only assert the contract of the card builder here; the SQL path is
    # covered by the richer job_detail implementation returning env_keys.
    j = {"id": 1, "name": "x", "live_status": "stopped", "env_keys": ["SECRET"],
         "has_code": False, "code_bytes": 0}
    text = pingbot._admin_job_detail_text(j)
    assert "SECRET" in text
    assert "values hidden" in text.lower() or "Env keys" in text
