"""JOB_SECRETS_KEY is OPTIONAL — the app must not refuse to work without it.

WHAT USED TO HAPPEN
-------------------
POST /admin/runners answered 409 "Configure JOB_SECRETS_KEY before storing
runner credentials", and every boot logged a WARNING that read like a broken
deploy. So a single-owner install — one or two people, their own database,
their own bot tokens — could not add its own runner until it had invented and
deployed a second secret. The encryption layer itself was never the problem
(secrets_store.pack_env has always fallen back to plain JSON); the HARD GATE in
front of it was.

WHAT IS ASSERTED HERE, with the key deliberately UNSET
------------------------------------------------------
  * pack_env() stores plain JSON, unpack_env() reads it straight back
  * adding a runner through the admin API succeeds — 200, not 409
  * the credential stored without a key is still usable: runner_client sends it
    as the Bearer token, so jobs really do deploy to that runner
  * migrate_job_envs() reports configured:False and changes nothing
  * /health still reports bot_secrets_encrypted:false — the fact is surfaced,
    it is simply no longer a precondition

And with the key SET, the same values are ciphertext — so "optional" never
means "silently downgraded for people who did configure it".

Run:  PYTHONPATH=. pytest -q tests/test_secrets_optional.py
"""
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
from services import runner_client, secrets_store  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
URL = "https://runner-nokey.example"
SECRET = "runner-secret-longer-than-twenty-four-characters"


class Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}
        self.headers = {}

    def json(self):
        return self._data


def _no_key(monkeypatch):
    """Simulate an install that never set JOB_SECRETS_KEY.

    Both variables have to go: RUNNER_SERVICE_SECRET is the legacy fallback key
    material, and leaving it in place would mean the test never actually
    exercised the unconfigured path."""
    monkeypatch.delenv("JOB_SECRETS_KEY", raising=False)
    monkeypatch.delenv("RUNNER_SERVICE_SECRET", raising=False)


def setup_module():
    c = database.get_db_connection()
    n = now_utc_str()
    c.execute("INSERT INTO users(username,email,password,is_verified,is_admin,"
              "created_at,updated_at) VALUES(?,?,?,1,1,?,?)",
              ("nokey-admin", "nokey@gmail.com", hash_password("Passw0rd!x"), n, n))
    c.commit()
    c.close()


def headers():
    r = client.post("/login", json={"username": "nokey@gmail.com",
                                    "email": "nokey@gmail.com",
                                    "password": "Passw0rd!x"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _fake_runner(monkeypatch, url=URL, secret=SECRET):
    """The runner answers /health and the authenticated probe, and its DNS is
    public — every check the endpoint makes EXCEPT the one about the key."""
    monkeypatch.setattr("routes.admin.socket.getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])

    def get(target, headers=None, timeout=None):
        if target == url + "/health":
            return Resp(200, {"status": "ok", "jobs": 0, "capacity": 5,
                              "free": 5, "load": 0.0, "mem_mb": 10, "safe_mb": 400})
        if target == url + "/internal/jobs" and headers == {"Authorization": "Bearer " + secret}:
            return Resp(200, {"jobs": []})
        return Resp(403, {})

    monkeypatch.setattr("routes.admin.requests.get", get)


def test_without_a_key_secrets_are_plain_json_and_still_readable(monkeypatch):
    _no_key(monkeypatch)
    assert not secrets_store.configured()
    packed = secrets_store.pack_env({"BOT_TOKEN": "123:abc"})
    assert not packed.startswith(secrets_store.PREFIX)
    assert secrets_store.unpack_env(packed) == {"BOT_TOKEN": "123:abc"}
    assert secrets_store.migrate_job_envs() == {"migrated": 0, "rewrapped": 0,
                                                "configured": False}


def test_adding_a_runner_without_a_key_is_not_a_409(monkeypatch):
    _no_key(monkeypatch)
    _fake_runner(monkeypatch)
    made = client.post("/admin/runners", headers=headers(),
                       json={"label": "No Key Runner", "url": URL, "secret": SECRET})
    # THE regression this file exists for: this used to be 409 with
    # "Configure JOB_SECRETS_KEY before storing runner credentials."
    assert made.status_code == 200, made.text
    assert "JOB_SECRETS_KEY" not in made.text

    c = database.get_db_connection()
    raw = c.execute("SELECT encrypted_secret FROM runner_nodes WHERE url=?",
                    (URL,)).fetchone()["encrypted_secret"]
    c.close()
    assert not raw.startswith(secrets_store.PREFIX)      # stored as plain JSON
    assert secrets_store.unpack_env(raw).get("secret") == SECRET

    # …and it is USABLE, which is the only part an owner actually cares about:
    # the placement pool picks it up and requests carry the real Bearer token.
    runner_client.invalidate_runner_registry()
    assert URL in runner_client.runner_pool()
    sent = {}

    def request(method, url, json=None, headers=None, timeout=None):
        sent.update(url=url, headers=headers)
        return Resp(200, {"jobs": []})

    monkeypatch.setattr(runner_client.requests, "request", request)
    runner_client._runner_http("GET", "/internal/jobs", worker=URL)
    assert sent["headers"]["Authorization"] == "Bearer " + SECRET


def test_health_reports_the_fact_without_gating_on_it(monkeypatch):
    _no_key(monkeypatch)
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["bot_secrets_encrypted"] is False


def test_with_a_key_the_same_values_are_ciphertext(monkeypatch):
    """Optional must not mean "silently weaker for those who opted in"."""
    monkeypatch.setenv("JOB_SECRETS_KEY", "a-key-set-on-purpose-for-this-test")
    assert secrets_store.configured()
    packed = secrets_store.pack_env({"BOT_TOKEN": "123:abc"})
    assert packed.startswith(secrets_store.PREFIX)
    assert "123:abc" not in packed
    assert secrets_store.unpack_env(packed) == {"BOT_TOKEN": "123:abc"}
