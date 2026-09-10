from services import job_recovery, runner_client, secrets_store, snapshots


class Response:
    status_code = 201
    placed_on = "https://runner-two.example"
    def json(self):
        return {"id": "new-runner-id"}


def test_missing_desired_bot_is_recreated_with_saved_token(monkeypatch):
    monkeypatch.setenv("JOB_SECRETS_KEY", "recovery-test-key")
    encrypted = secrets_store.pack_env({"BOT_TOKEN": "123:saved-token"})
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [{
        "id": 9, "user_id": 4, "name": "support", "language": "python",
        "code": "print('bot')", "env": encrypted,
        "runner_job_id": "old-id", "worker_url": "embedded",
        "telegram_bot_detected": 1,
    }])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})
    sent = {}
    def call(method, path, body=None, worker=None):
        sent.update(method=method, path=path, body=body, worker=worker)
        return Response()
    monkeypatch.setattr(runner_client, "_runner_http", call)
    remembered = {}
    monkeypatch.setattr(job_recovery, "_remember", lambda jid, rid, worker: remembered.update(job=jid, runner=rid, worker=worker))
    monkeypatch.setattr(snapshots, "restore_snapshot", lambda *a, **k: {"restored": 0})

    assert job_recovery.recover_once() == 0
    assert sent["path"] == "/internal/jobs"
    assert sent["body"]["env"]["BOT_TOKEN"] == "123:saved-token"
    assert remembered == {"job": 9, "runner": "new-runner-id", "worker": "https://runner-two.example"}


def test_recovery_never_crash_loops_telegram_bot_without_token(monkeypatch):
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [{
        "id": 10, "user_id": 4, "name": "broken", "language": "python",
        "code": "print('bot')", "env": None, "runner_job_id": "old",
        "worker_url": None, "telegram_bot_detected": 1,
    }])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})
    monkeypatch.setattr(runner_client, "_runner_http", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not start")))
    assert job_recovery.recover_once() == 1
