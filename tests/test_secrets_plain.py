"""Bot secrets are PLAIN TEXT in your own database — and old rows are upgraded.

WHY THE ENCRYPTION WENT
-----------------------
`jobs.env` used to be Fernet-encrypted with `JOB_SECRETS_KEY`. The key is one
more thing that can be lost, rotated, or set differently on the site than on the
runner — and when it does not match, `unpack_env()` returns `{}`, so every bot
that restarts comes back WITHOUT its `BOT_TOKEN`: it crash-loops, the dashboard
says "processing", and the owner's bot is effectively gone. That already cost a
user their bot once. Plain JSON in a database that is already behind your
provider's credentials removes the whole failure mode.

WHAT IS ASSERTED
----------------
  * pack_env() writes plain JSON, unpack_env() reads it back
  * a row an OLDER version encrypted (`enc:v1:`) is still readable — losing the
    ability to read it would destroy every token saved before the change
  * migrate_job_envs() rewrites those rows as plain text, in jobs.env AND in
    runner_nodes.encrypted_secret (an unreadable runner secret means the site
    cannot reach the runner at all, so NO bot can be restarted), and afterwards
    legacy_rows() is 0 — which is what /health reports
  * ciphertext with no usable key is counted and logged, never silently `{}`
  * adding a runner works with no key configured at all (this endpoint used to
    answer 409 "Configure JOB_SECRETS_KEY before storing runner credentials")
  * the token still never leaves the server: owner APIs mask secret-looking
    values, so plain storage does not mean plain responses

Run:  PYTHONPATH=. pytest -q tests/test_secrets_plain.py
"""
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
from services import runner_client, secrets_store  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
URL = "https://runner-nokey.example"
SECRET = "runner-secret-longer-than-twenty-four-characters"
TOKEN = "123456:AA-plain-storage-test-token"


class Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}
        self.headers = {}

    def json(self):
        return self._data


def setup_module():
    c = database.get_db_connection()
    n = now_utc_str()
    c.execute("INSERT INTO users(username,email,password,is_verified,is_admin,"
              "created_at,updated_at) VALUES(?,?,?,1,1,?,?)",
              ("plain-admin", "plain@gmail.com", hash_password("Passw0rd!x"), n, n))
    c.commit()
    c.close()


def headers():
    r = client.post("/login", json={"username": "plain@gmail.com",
                                    "email": "plain@gmail.com",
                                    "password": "Passw0rd!x"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _insert_job(job_id, env_value, name="plain-bot", token_fingerprint=None):
    c = database.get_db_connection()
    n = now_utc_str()
    c.execute("INSERT INTO jobs(id,user_id,name,language,code,env,desired_state,"
              "telegram_bot_detected,telegram_token_fingerprint,created_at,updated_at) "
              "VALUES(?,1,?,'python','print(1)',?,'running',1,?,?,?)",
              (job_id, name, env_value, token_fingerprint, n, n))
    c.commit()
    c.close()


def _job_env(job_id):
    c = database.get_db_connection()
    try:
        row = c.execute("SELECT env,telegram_token_fingerprint FROM jobs WHERE id=?",
                        (job_id,)).fetchone()
        return dict(row)
    finally:
        c.close()


def test_pack_is_plain_json_and_reads_back(monkeypatch):
    monkeypatch.setenv("JOB_SECRETS_KEY", "a-key-that-is-set-but-unused")
    packed = secrets_store.pack_env({"BOT_TOKEN": TOKEN, "API_KEY": "k"})
    # Even WITH a key configured, nothing is encrypted on the way in any more.
    assert not packed.startswith(secrets_store.LEGACY_PREFIX)
    assert json.loads(packed)["BOT_TOKEN"] == TOKEN
    assert secrets_store.unpack_env(packed) == {"BOT_TOKEN": TOKEN, "API_KEY": "k"}
    assert secrets_store.pack_env({}) is None
    assert secrets_store.unpack_env(None) == {}


def test_a_row_an_older_version_encrypted_is_still_readable(monkeypatch):
    monkeypatch.setenv("JOB_SECRETS_KEY", "the-key-it-was-written-with")
    legacy = secrets_store.legacy_encrypt({"BOT_TOKEN": TOKEN})
    assert legacy.startswith(secrets_store.LEGACY_PREFIX)
    assert TOKEN not in legacy
    assert secrets_store.unpack_env(legacy) == {"BOT_TOKEN": TOKEN}

    # Rotate the key: the old row is now undecryptable. It must be reported as
    # unreadable, not quietly turned into "this bot has no env vars".
    monkeypatch.setenv("JOB_SECRETS_KEY", "a-different-key")
    monkeypatch.delenv("RUNNER_SERVICE_SECRET", raising=False)
    values, key_index = secrets_store._unpack_with_key_index(legacy)
    assert values == {} and key_index is None


def test_migration_rewrites_legacy_rows_and_fills_fingerprints(monkeypatch):
    monkeypatch.setenv("JOB_SECRETS_KEY", "the-key-it-was-written-with")
    monkeypatch.setenv("RUNNER_SERVICE_SECRET", "embedded-test-secret")
    _insert_job(901, secrets_store.legacy_encrypt({"BOT_TOKEN": TOKEN}), name="legacy-bot")
    assert secrets_store.legacy_rows() >= 1

    report = secrets_store.migrate_job_envs()
    assert report["encrypted"] is False
    assert report["unwrapped"] >= 1, report
    assert report["fingerprints"] >= 1, report      # token was in hand, so fill it in

    row = _job_env(901)
    assert not row["env"].startswith(secrets_store.LEGACY_PREFIX)
    assert json.loads(row["env"])["BOT_TOKEN"] == TOKEN
    assert row["telegram_token_fingerprint"]        # duplicate-poller check needs it
    assert secrets_store.legacy_rows() == 0     # this job's row is plain now

    # Idempotent: a second boot has nothing left to do.
    again = secrets_store.migrate_job_envs()
    assert again["unwrapped"] == 0 and again["unreadable"] == 0


def test_undecryptable_row_is_counted_not_silently_emptied(monkeypatch):
    monkeypatch.setenv("JOB_SECRETS_KEY", "the-key-it-was-written-with")
    legacy = secrets_store.legacy_encrypt({"BOT_TOKEN": TOKEN})
    _insert_job(902, legacy, name="doomed-bot")
    monkeypatch.setenv("JOB_SECRETS_KEY", "the-wrong-key")
    monkeypatch.delenv("RUNNER_SERVICE_SECRET", raising=False)

    report = secrets_store.migrate_job_envs()
    assert report["unreadable"] >= 1, report
    # Left exactly as it was: rewriting it to "{}" would erase the only evidence
    # that a token is in there, and the row could still be rescued by putting
    # the right key back.
    assert _job_env(902)["env"].startswith(secrets_store.LEGACY_PREFIX)


def test_runner_secret_is_upgraded_too(monkeypatch):
    monkeypatch.setenv("JOB_SECRETS_KEY", "the-key-it-was-written-with")
    c = database.get_db_connection()
    n = now_utc_str()
    legacy = secrets_store.legacy_encrypt({"secret": SECRET})
    c.execute("INSERT INTO runner_nodes(id,label,url,encrypted_secret,enabled,"
              "created_by,created_at,updated_at) VALUES(701,'Legacy',?,?,1,1,?,?)",
              ("https://legacy-runner.example", legacy, n, n))
    c.commit()
    c.close()

    report = secrets_store.migrate_job_envs()
    assert report["runner_secrets"] >= 1, report
    c = database.get_db_connection()
    raw = c.execute("SELECT encrypted_secret FROM runner_nodes WHERE id=701").fetchone()[0]
    c.close()
    assert json.loads(raw)["secret"] == SECRET
    assert secrets_store.legacy_rows() == 0


def test_adding_a_runner_needs_no_key_at_all(monkeypatch):
    """THE regression the old 409 caused: a working single-owner install could
    not add its own runner without inventing a second secret first."""
    monkeypatch.delenv("JOB_SECRETS_KEY", raising=False)
    monkeypatch.delenv("RUNNER_SERVICE_SECRET", raising=False)
    monkeypatch.setattr("routes.admin.socket.getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])

    def get(target, headers=None, timeout=None):
        if target == URL + "/health":
            return Resp(200, {"status": "ok", "jobs": 0, "capacity": 5, "free": 5,
                              "load": 0.0, "mem_mb": 10, "safe_mb": 400})
        if target == URL + "/internal/jobs" and headers == {"Authorization": "Bearer " + SECRET}:
            return Resp(200, {"jobs": []})
        return Resp(403, {})

    monkeypatch.setattr("routes.admin.requests.get", get)
    made = client.post("/admin/runners", headers=headers(),
                       json={"label": "No Key Runner", "url": URL, "secret": SECRET})
    assert made.status_code == 200, made.text
    assert "JOB_SECRETS_KEY" not in made.text

    c = database.get_db_connection()
    raw = c.execute("SELECT encrypted_secret FROM runner_nodes WHERE url=?",
                    (URL,)).fetchone()[0]
    listed = client.get("/admin/runners", headers=headers()).json()
    c.close()
    assert json.loads(raw)["secret"] == SECRET        # plain at rest…
    assert SECRET not in json.dumps(listed)           # …still never returned

    # And usable, which is the only part an owner actually cares about.
    runner_client.invalidate_runner_registry()
    assert URL in runner_client.runner_pool()
    sent = {}

    def request(method, url, json=None, headers=None, timeout=None):
        sent.update(headers=headers)
        return Resp(200, {"jobs": []})

    monkeypatch.setattr(runner_client.requests, "request", request)
    runner_client._runner_http("GET", "/internal/jobs", worker=URL)
    assert sent["headers"]["Authorization"] == "Bearer " + SECRET


def test_health_and_admin_report_plain_storage(monkeypatch):
    monkeypatch.delenv("JOB_SECRETS_KEY", raising=False)
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["bot_secrets_storage"] == "plain-text"
    assert body["bot_secrets_legacy_rows"] == 0
    assert "bot_secrets_encrypted" not in body        # the old scary flag is gone

    # Not 0 in this database on purpose: the row from
    # test_undecryptable_row_is_counted_not_silently_emptied is ciphertext whose
    # key is gone, and it must stay visible until someone re-enters the token.
    # What matters is that the endpoint and the module agree.
    assert body["bot_secrets_legacy_rows"] == secrets_store.legacy_rows()

    overview = client.get("/admin/overview", headers=headers()).json()
    assert overview["bot_secrets_storage"] == "plain-text"
    assert overview["bot_secrets_legacy_rows"] == secrets_store.legacy_rows()
