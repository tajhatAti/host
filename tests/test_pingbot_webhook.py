"""Telegram retries must not replay an admin recovery command."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TERM_HOMES_DIR", tempfile.mkdtemp(prefix="pingbot-webhook-homes-"))

import database  # noqa: E402
database.init_db()

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402
from services import pingbot  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


def test_webhook_retry_is_acknowledged_without_dispatching_twice(monkeypatch):
    update_id = time.time_ns() % 8_000_000_000 + 8_000_000_000
    handled = []
    monkeypatch.setattr(pingbot, "handle_update", lambda update: handled.append(update["update_id"]))
    headers = {"X-Telegram-Bot-Api-Secret-Token": pingbot._WEBHOOK_SECRET}
    update = {"update_id": update_id, "message": {"text": "/admin recover"}}

    first = client.post("/telegram/webhook", json=update, headers=headers)
    retry = client.post("/telegram/webhook", json=update, headers=headers)
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json() == {"ok": True}
    assert handled == [update_id]

    conn = database.get_db_connection()
    try:
        conn.execute("DELETE FROM telegram_webhook_updates WHERE update_id=?", (update_id,))
        conn.commit()
    finally:
        conn.close()


def test_manual_recovery_is_one_queued_sweep_separate_from_auto_deploy(monkeypatch):
    from services import job_recovery
    messages = []
    monkeypatch.setattr(job_recovery, "recover_once", lambda: 0)
    monkeypatch.setattr(job_recovery, "auto_deploy_sweep",
                        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("recovery must not deploy")))
    monkeypatch.setattr(pingbot, "_send",
                        lambda _chat, text, reply_markup=None: messages.append(text))
    monkeypatch.setattr(pingbot, "_edit_or_send",
                        lambda _chat, _message_id, text, reply_markup=None: messages.append(text))

    class ImmediateThread:
        def __init__(self, target, args, **_kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(pingbot.threading, "Thread", ImmediateThread)
    assert pingbot._start_admin_recovery(12345) is True
    assert len(messages) == 2
    assert "Recovery started once" in messages[0]
    assert "Unresolved (still missing token/source): *0*" in messages[1]


def test_abandoned_claim_can_be_retried_after_lease_and_completed_claim_cannot(monkeypatch):
    update_id = time.time_ns() % 8_000_000_000 + 8_000_000_000
    first_claim = pingbot._claim_webhook_update(update_id)
    assert isinstance(first_claim, int)
    assert pingbot._claim_webhook_update(update_id) is False

    conn = database.get_db_connection()
    try:
        conn.execute(
            "UPDATE telegram_webhook_updates SET claimed_at=?,completed_at=NULL WHERE update_id=?",
            (time.time_ns() - pingbot._WEBHOOK_UPDATE_LEASE_NS - 1, update_id),
        )
        conn.commit()
    finally:
        conn.close()

    retry_claim = pingbot._claim_webhook_update(update_id)
    assert isinstance(retry_claim, int) and retry_claim != first_claim
    pingbot._complete_webhook_update(update_id, retry_claim)
    assert pingbot._claim_webhook_update(update_id) is False

    conn = database.get_db_connection()
    try:
        conn.execute("DELETE FROM telegram_webhook_updates WHERE update_id=?", (update_id,))
        conn.commit()
    finally:
        conn.close()
