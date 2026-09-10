import time

from routes import runspace


class _Rows:
    def execute(self, sql, params=()):
        assert "FROM jobs" in sql
        return self

    def fetchall(self):
        return []

    def close(self):
        pass


def test_bot_list_never_waits_for_runner_network(monkeypatch):
    monkeypatch.setattr(runspace, "get_current_user_and_session", lambda _auth: ({"id": 7}, {}))
    monkeypatch.setattr(runspace, "get_db_connection", lambda: _Rows())
    monkeypatch.setattr(
        runspace.runner_client,
        "_runner_http",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("runner network called")),
    )
    started = time.perf_counter()
    result = runspace.list_jobs("Bearer test")
    assert time.perf_counter() - started < 0.05
    assert result == {"jobs": [], "runner": "background", "max_per_user": runspace.MAX_JOBS_PER_USER}


def test_open_bot_editor_never_waits_for_runner_network(monkeypatch):
    monkeypatch.setattr(runspace, "get_current_user_and_session", lambda _auth: ({"id": 7}, {}))
    monkeypatch.setattr(runspace, "_get_own_job", lambda _job, _user: {
        "id": 3, "name": "demo", "code": "print('ok')", "language": "python",
        "status": "running", "env": "{}", "telegram_bot_detected": 0,
        "telegram_bot_username": None, "telegram_bot_id": None,
        "telegram_check_status": None, "telegram_verified_at": None,
    })
    monkeypatch.setattr(
        runspace.runner_client,
        "_runner_http",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("runner network called")),
    )
    started = time.perf_counter()
    result = runspace.get_job(3, "Bearer test")
    assert time.perf_counter() - started < 0.05
    assert result["code"] == "print('ok')"
    assert result["status_stale"] is True
