"""Owner-only runner diagnostics and explicit saved-setting reveal routes."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ.setdefault("RUNNER_SERVICE_SECRET", "embedded-test-secret")
os.environ.setdefault("SITE_BASE_URL", "https://codenest.test")

import database  # noqa: E402
database.init_db()

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402
from routes.deps import hash_password, now_utc_str  # noqa: E402
from services import runner_admin, runner_client, secrets_store, telegram_admin_ext  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
URL = "https://admin-runner.example"
RUNNER_SECRET = "admin-runner-secret-long-enough"
BOT_TOKEN = "987654:AA-settings-reveal-test-token"
SOURCE = "print('saved-job-source-marker')"


class Resp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code = status
        self._data = data or {}
        self.text = text
        self.headers = {}

    def json(self):
        return self._data


def setup_module():
    conn = database.get_db_connection()
    now = now_utc_str()
    conn.execute(
        "INSERT INTO users(username,email,password,is_verified,is_admin,created_at,updated_at) "
        "VALUES(?,?,?,1,1,?,?)",
        ("runner-detail-admin", "runner-detail@gmail.com", hash_password("Passw0rd!x"), now, now),
    )
    conn.commit()
    conn.close()


def headers():
    response = client.post("/login", json={"username": "runner-detail@gmail.com",
                                             "email": "runner-detail@gmail.com",
                                             "password": "Passw0rd!x"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def test_runner_detail_actions_and_explicit_settings_reveal(monkeypatch):
    auth = headers()
    conn = database.get_db_connection()
    admin_id = conn.execute("SELECT id FROM users WHERE username=?",
                            ("runner-detail-admin",)).fetchone()["id"]
    now = now_utc_str()
    conn.execute(
        "INSERT INTO runner_nodes(label,url,encrypted_secret,enabled,created_by,created_at,updated_at) "
        "VALUES(?,?,?,1,?,?,?)",
        ("Diagnostics runner", URL, secrets_store.pack_env({"secret": RUNNER_SECRET}), admin_id, now, now),
    )
    node_id = conn.execute("SELECT id FROM runner_nodes WHERE url=?", (URL,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO jobs(user_id,name,language,code,env,desired_state,runner_job_id,worker_url,created_at,updated_at) "
        "VALUES(?,?,?,?,?,'running','runner-job-1',?,?,?)",
        (admin_id, "diagnostic-bot", "python", SOURCE,
         secrets_store.pack_env({"BOT_TOKEN": BOT_TOKEN, "ADMIN_ID": "123"}), URL, now, now),
    )
    job_id = conn.execute("SELECT id FROM jobs WHERE name=?", ("diagnostic-bot",)).fetchone()["id"]
    conn.commit()
    conn.close()

    live = {
        "id": "runner-job-1", "name": f"u{admin_id}-diagnostic-bot", "language": "python",
        "status": "running", "uptime_s": 91, "restarts": 2, "mem_mb": 44,
        "peak_mem_mb": 87, "last_exit_reason": "crash", "last_exit_code": 1,
        "web_slug": "diagnostic-bot", "web_public": True,
        # These runner-internal values must never leak into ordinary detail JSON.
        "env": {"BOT_TOKEN": BOT_TOKEN}, "access_key": "private-access-key", "dir": "/secret/path",
    }

    monkeypatch.setattr(runner_admin.requests, "get", lambda *_a, **_k: Resp(200, {
        "jobs": 1, "capacity": 8, "mem_mb": 44, "safe_mb": 512, "free_mb": 468,
    }))
    monkeypatch.setattr(runner_client, "_runner_http",
                        lambda method, path, body=None, worker=None: Resp(200, {"jobs": [live]}))

    detail = client.get(f"/admin/runners/{node_id}", headers=auth)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["runner"]["online"] is True
    assert body["runner"]["url"] == URL
    assert body["jobs"][0]["status"] == "running"
    assert body["jobs"][0]["last_exit_reason"] == "crash"
    ordinary = json.dumps(body)
    assert RUNNER_SECRET not in ordinary
    assert BOT_TOKEN not in ordinary
    assert "private-access-key" not in ordinary
    assert "/secret/path" not in ordinary
    assert SOURCE not in ordinary

    # A visible button requests this separate no-store endpoint; only then are
    # the saved source and plain-DB environment values returned to the admin.
    revealed = client.get(f"/admin/jobs/{job_id}/settings", headers=auth)
    assert revealed.status_code == 200, revealed.text
    assert revealed.headers.get("cache-control") == "no-store, private"
    settings = revealed.json()
    assert settings["job"]["code"] == SOURCE
    assert settings["env"]["BOT_TOKEN"] == BOT_TOKEN
    assert settings["env"]["ADMIN_ID"] == "123"

    # The runner credential has its own explicit reveal endpoint and is never
    # mixed into ordinary runner detail or written into audit details.
    secret = client.get(f"/admin/runners/{node_id}/secret", headers=auth)
    assert secret.status_code == 200, secret.text
    assert secret.headers.get("cache-control") == "no-store, private"
    assert secret.json()["secret"] == RUNNER_SECRET

    # Admin actions use the existing isolated bot-ops path. The returned JSON
    # contains no source/env row, and the action history records who requested it.
    monkeypatch.setattr(telegram_admin_ext, "admin_restart_job", lambda _id: {"ok": True})
    monkeypatch.setattr(telegram_admin_ext, "admin_stop_job", lambda _id: {"ok": True})
    assert client.post(f"/admin/jobs/{job_id}/restart", headers=auth).status_code == 200
    assert client.post(f"/admin/jobs/{job_id}/stop", headers=auth).status_code == 200
    runner_admin.record_action(URL, "Automatic recovery succeeded", "workspace snapshot restored",
                               job_id=job_id, job_name="diagnostic-bot")
    refreshed = client.get(f"/admin/runners/{node_id}", headers=auth).json()
    actions = " ".join(str(event.get("action")) for event in refreshed["history"])
    assert "admin_job_restart" in actions
    assert "admin_job_stop" in actions
    assert "Automatic recovery succeeded" in actions
    assert RUNNER_SECRET not in json.dumps(refreshed["history"])

    assert client.get(f"/admin/jobs/{job_id}/settings").status_code == 404
    assert client.get(f"/admin/runners/{node_id}/secret").status_code == 404

    # Keep this module safe when run alongside older DB-backed tests that share
    # the imported database module rather than opening one connection per test.
    conn = database.get_db_connection()
    try:
        conn.execute("DELETE FROM runner_action_events WHERE runner_url=?", (URL,))
        conn.execute("DELETE FROM admin_audit_log WHERE target=? OR target=?",
                     (URL, f"job:{job_id}"))
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.execute("DELETE FROM runner_nodes WHERE id=?", (node_id,))
        conn.commit()
    finally:
        conn.close()


def test_environment_runner_gets_same_details_wake_and_secret_reveal(monkeypatch):
    auth = headers()
    url = "https://env-runner.example"
    monkeypatch.delenv("RUNNER_SERVICE_URL", raising=False)
    monkeypatch.setattr(runner_client, "runner_pool", lambda: [url])
    monkeypatch.setattr(runner_client, "_secret_for_runner", lambda _url: "pool-env-secret")
    monkeypatch.setattr(runner_admin.requests, "get", lambda *_a, **_k: Resp(200, {
        "jobs": 0, "capacity": 6, "mem_mb": 15, "safe_mb": 512, "free_mb": 497,
    }))
    monkeypatch.setattr(runner_client, "_runner_http",
                        lambda method, path, body=None, worker=None: Resp(200, {"jobs": []}))

    detail = client.get("/admin/runners/by-url", params={"url": url}, headers=auth)
    assert detail.status_code == 200, detail.text
    assert detail.json()["runner"]["id"] is None
    assert detail.json()["runner"]["url"] == url
    assert detail.json()["runner"]["online"] is True

    secret = client.get("/admin/runners/by-url/secret", params={"url": url}, headers=auth)
    assert secret.status_code == 200 and secret.json()["secret"] == "pool-env-secret"
    monkeypatch.setattr(runner_admin, "_audit", lambda *_a: None)
    class _Thread:
        def __init__(self, **kw): self.kw = kw
        def start(self): pass
    monkeypatch.setattr(runner_admin.threading, "Thread", _Thread)
    wake = client.post("/admin/runners/by-url/wake", params={"url": url}, headers=auth)
    assert wake.status_code == 200 and wake.json()["online"] is True
    assert client.get("/admin/runners/by-url", params={"url": "https://outside.example"},
                      headers=auth).status_code == 404
