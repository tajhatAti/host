"""Bots come back on their own, and never twice.

Three rules, in the order they matter to an owner:

1. A bot marked desired_state='running' that the runner no longer has is
   re-created from the database — code, env (plain JSON now, so the BOT_TOKEN is
   always readable), and the last workspace snapshot.
2. A worker that DID NOT ANSWER is not evidence that its jobs are gone. Treating
   silence as absence re-created every bot on a sleeping runner, which puts two
   pollers on one Telegram token: they fight, and the owner's bot dies anyway.
3. A recovered bot keeps its 👑 (unlimited memory) flag — recovery is a fresh
   create, and a create that forgets mem_limit_mb quietly re-applies the default
   ceiling.

Plus the part that makes a runner restart a non-event: recover_once() runs on an
interval (start_reconciler), not only once at site startup.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "recovery.db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

from services import job_recovery, runner_client, secrets_store, snapshots  # noqa: E402


class Response:
    status_code = 201
    placed_on = "https://runner-two.example"

    def json(self):
        return {"id": "new-runner-id"}


class Health:
    status_code = 200

    def json(self):
        return {"status": "ok"}


def _row(**over):
    row = {"id": 9, "user_id": 4, "name": "support", "language": "python",
           "code": "print('bot')", "env": secrets_store.pack_env({"BOT_TOKEN": "123:saved-token"}),
           "runner_job_id": "old-id", "worker_url": "embedded",
           "telegram_bot_detected": 1}
    row.update(over)
    return row


def test_missing_desired_bot_is_recreated_with_saved_token(monkeypatch):
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [_row()])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})
    sent = {}

    def call(method, path, body=None, worker=None):
        if path == "/health":
            return Health()                     # the worker answers: its empty job list is real
        sent.update(method=method, path=path, body=body, worker=worker)
        return Response()

    monkeypatch.setattr(runner_client, "_runner_http", call)
    remembered = {}
    monkeypatch.setattr(job_recovery, "_remember",
                        lambda jid, rid, worker: remembered.update(job=jid, runner=rid, worker=worker))
    monkeypatch.setattr(snapshots, "restore_snapshot", lambda *a, **k: {"restored": 0})

    assert job_recovery.recover_once() == 0
    assert sent["path"] == "/internal/jobs"
    assert sent["body"]["env"]["BOT_TOKEN"] == "123:saved-token"
    assert remembered == {"job": 9, "runner": "new-runner-id", "worker": "https://runner-two.example"}


def test_recovery_never_crash_loops_telegram_bot_without_token(monkeypatch):
    """The worker is reachable, so this is genuinely a bot with no token: it must
    be reported, not started into a crash-loop that looks like 'processing'."""
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [
        _row(id=10, name="broken", env=None, runner_job_id="old", worker_url=None)])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})

    def call(method, path, body=None, worker=None):
        if path == "/health":
            return Health()
        raise AssertionError("must not start a tokenless Telegram bot")

    monkeypatch.setattr(runner_client, "_runner_http", call)
    assert job_recovery.recover_once() == 1


def test_a_worker_that_does_not_answer_never_causes_a_duplicate(monkeypatch):
    """THE rule that makes an interval reconciler safe to run at all.

    Before this, an empty fleet list was taken as proof the jobs were gone. On a
    runner that is asleep or mid-boot that is false, and the "recovery" created a
    second copy of every bot — two pollers on one token, which is exactly how an
    owner's working bot ends up dead."""
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [
        _row(id=11, runner_job_id="alive-but-unprobed", worker_url="https://sleeping.example")])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})

    def call(method, path, body=None, worker=None):
        if path == "/health":
            raise TimeoutError("runner is asleep")
        raise AssertionError("must not recreate a job on a worker that never answered")

    monkeypatch.setattr(runner_client, "_runner_http", call)
    assert job_recovery.recover_once() == 0      # deferred, not failed
    monkeypatch.setattr(job_recovery, "_remember", lambda *a: (_ for _ in ()).throw(
        AssertionError("nothing should have been remembered")))

    # A 502/503 from a container still booting is the same case: not an answer.
    class Booting:
        status_code = 503

        def json(self):
            return {}

    monkeypatch.setattr(runner_client, "_runner_http",
                        lambda method, path, body=None, worker=None: Booting())
    assert job_recovery.recover_once() == 0


def test_recovered_bot_keeps_its_queen_flag(monkeypatch):
    """Recovery is a fresh create, so it has to carry 👑 with it."""
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [_row(id=12, user_id=77)])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})
    monkeypatch.setattr(job_recovery, "_remember", lambda *a: None)
    monkeypatch.setattr(snapshots, "restore_snapshot", lambda *a, **k: {"restored": 0})
    seen = {}

    def call(method, path, body=None, worker=None):
        if path == "/health":
            return Health()
        seen.update(body)
        return Response()

    monkeypatch.setattr(runner_client, "_runner_http", call)
    from services import bot_ops
    monkeypatch.setattr(bot_ops, "mem_limit_for", lambda user_id: 0 if user_id == 77 else None)

    assert job_recovery.recover_once() == 0
    assert seen["mem_limit_mb"] == 0, seen


def test_reconciler_is_started_once_and_can_be_switched_off(monkeypatch):
    started = []
    monkeypatch.setattr(job_recovery.threading, "Thread",
                        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr(job_recovery, "_reconciler_started", False)
    monkeypatch.setattr(job_recovery, "RECOVERY_INTERVAL_S", 300)
    job_recovery.start_reconciler()
    job_recovery.start_reconciler()               # idempotent — one thread, not two
    assert len(started) == 1, started
    assert started[0]["daemon"] is True and started[0]["name"] == "job-recovery"

    monkeypatch.setattr(job_recovery, "_reconciler_started", False)
    monkeypatch.setattr(job_recovery, "RECOVERY_INTERVAL_S", 0)
    job_recovery.start_reconciler()
    assert len(started) == 1                      # JOB_RECOVERY_INTERVAL_S=0 means off
