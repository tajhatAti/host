"""Durable Telegram queue: ack after the DB write, handle work off-request."""
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TERM_HOMES_DIR", tempfile.mkdtemp(prefix="telegram-queue-homes-"))

import database  # noqa: E402
database.init_db()

from services.telegram_webhook_queue import TelegramWebhookQueue  # noqa: E402


def _row(update_id):
    conn = database.get_db_connection()
    try:
        return conn.execute(
            "SELECT claimed_at,completed_at,payload FROM telegram_webhook_updates "
            "WHERE update_id=?", (update_id,)).fetchone()
    finally:
        conn.close()


def _delete(update_id):
    conn = database.get_db_connection()
    try:
        conn.execute("DELETE FROM telegram_webhook_updates WHERE update_id=?", (update_id,))
        conn.commit()
    finally:
        conn.close()


def _wait_completed(update_id, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = _row(update_id)
        if row and row["completed_at"] is not None:
            return row
        time.sleep(0.01)
    return _row(update_id)


def test_enqueued_payload_is_cleared_after_worker_finishes():
    update_id = time.time_ns() % 8_000_000_000 + 8_000_000_000
    update = {"update_id": update_id, "message": {"text": "hello"}}
    handled = []
    done = threading.Event()
    queue = TelegramWebhookQueue(poll_s=0.05)
    try:
        assert queue.enqueue(update, lambda item: (handled.append(item), done.set())) == "queued"
        assert done.wait(2)
        row = _wait_completed(update_id)
        assert handled == [update]
        assert row and row["completed_at"] is not None and row["payload"] is None
    finally:
        queue.stop()
        _delete(update_id)


def test_existing_old_claim_saves_retry_payload_for_later_recovery():
    update_id = time.time_ns() % 8_000_000_000 + 8_000_000_000
    update = {"update_id": update_id, "message": {"text": "/admin recover"}}
    queue = TelegramWebhookQueue(poll_s=0.05)
    try:
        old_claim = queue.claim_update(update_id)
        assert isinstance(old_claim, int)
        # A retry inside the old lease is acknowledged as a duplicate, but its
        # payload is made durable in case the prior process disappeared.
        assert queue.claim_update(update_id, json.dumps(update)) is False
        row = _row(update_id)
        assert row and json.loads(row["payload"]) == update

        conn = database.get_db_connection()
        try:
            conn.execute(
                "UPDATE telegram_webhook_updates SET claimed_at=? WHERE update_id=?",
                (time.time_ns() - queue.lease_ns - 1, update_id),
            )
            conn.commit()
        finally:
            conn.close()

        handled = threading.Event()
        queue.start(lambda item: handled.set() if item == update else None)
        assert handled.wait(2)
        row = _wait_completed(update_id)
        assert row and row["completed_at"] is not None and row["payload"] is None
    finally:
        queue.stop()
        _delete(update_id)
