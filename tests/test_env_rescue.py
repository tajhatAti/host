"""A bot whose saved variables cannot be read is rescued from the runner.

THE PRODUCTION FAILURE THIS GUARDS
----------------------------------
A deploy came up unable to read its own `jobs.env` rows. Every affected bot then
stopped with "the saved bot token is unavailable" and STAYED down: recovery
skipped it, restart refused it, and the only way back was a human re-typing the
token. Bots with perfectly valid tokens, all dark.

The runner is the second copy. It writes each job's env into `job.json` in the
job's own directory and serves that file over the internal file endpoint, so the
variables can be read back and repaired into the database — which is what
services/env_rescue.py does, at startup, in recovery, and on any start or edit.

WHAT IS ASSERTED
  * read_manifest_env() parses the runner's manifest, and returns {} (never a
    guess) when the runner 404s, is unreachable, or answers nonsense
  * rescue_job_env() repairs the row: the bot gets its env AND the database now
    holds plain JSON, so the next start needs no rescue
  * nothing anywhere -> ({}, "unavailable") and the row is left untouched
  * recover_once() rescues instead of skipping, so the bot comes back alone
  * _cold_start's refusal message names the fix and says nothing about keys —
    "restore the previous encryption key" was not something an owner could act on
  * editing env on an unreadable row no longer wipes the other variables

Run:  PYTHONPATH=. pytest -q tests/test_env_rescue.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "rescue.db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

import pytest                                                    # noqa: E402
import database                                                  # noqa: E402
from routes.deps import now_utc_str                              # noqa: E402
from services import bot_ops, env_rescue, job_recovery           # noqa: E402
from services import runner_client, secrets_store                # noqa: E402

database.init_db()

TOKEN = "123456:rescued-from-the-runner"
# A row this site cannot read: genuine ciphertext whose key is gone.
BROKEN = secrets_store.LEGACY_PREFIX + "Zm9yZ2V0LW1lLW5vdC1hLXJlYWwtdG9rZW4="


# Several suites in this repo share ONE database file (each sets DB_PATH with
# setdefault, so the first import wins). These rows are `enc:v1:` fixtures, so
# leaving them behind would inflate secrets_store.legacy_rows() for whatever
# runs next — every row this module creates is removed again after each test.
_created = []


@pytest.fixture(autouse=True)
def _remove_created_rows():
    yield
    if not _created:
        return
    conn = database.get_db_connection()
    try:
        marks = ",".join("?" * len(_created))
        conn.execute(f"DELETE FROM jobs WHERE id IN ({marks})", tuple(_created))
        conn.commit()
    finally:
        conn.close()
    _created.clear()


def _owner_id() -> int:
    """The account these jobs belong to — the FIRST one, created if needed.

    jobs.user_id is a real foreign key, and several suites in this repo share a
    single database file (each sets DB_PATH at import, so whoever imports
    `database` first decides). Some of them hardcode user_id=1, so this reuses
    the lowest existing id instead of adding a high one: a new id here would
    shift their AUTOINCREMENT and their inserts would fail the foreign key.
    """
    conn = database.get_db_connection()
    try:
        row = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if row:
            return dict(row)["id"]
        now = now_utc_str()
        conn.execute(
            "INSERT INTO users (id,username,email,password,is_verified,mem_unlimited,"
            "created_at,updated_at) VALUES (1,'rescue-owner','rescue-owner@example.com',"
            "'x',1,0,?,?)", (now, now))
        conn.commit()
        return 1
    finally:
        conn.close()


def _insert_job(name="support", env=BROKEN, runner_job_id="runner-1",
                worker_url="https://runner.example", user_id=None, detected=1):
    user_id = user_id or _owner_id()
    conn = database.get_db_connection()
    try:
        cur = conn.execute(
            "INSERT INTO jobs (user_id,name,language,code,runner_job_id,worker_url,"
            "desired_state,env,telegram_bot_detected,created_at,updated_at) "
            "VALUES (?,?, 'python', 'print(1)', ?,?, 'running', ?,?, ?, ?)",
            (user_id, name, runner_job_id, worker_url, env, detected,
             now_utc_str(), now_utc_str()))
        conn.commit()
        job_id = cur.lastrowid
        _created.append(job_id)
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    return dict(row)


def _stored_env(job_id):
    conn = database.get_db_connection()
    try:
        row = conn.execute("SELECT env FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    return dict(row)["env"] if row else None


class Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _manifest_response(env):
    """What GET /internal/jobs/<id>/file?path=job.json answers with."""
    return Resp(200, {"path": "job.json", "size": 10,
                      "content": json.dumps({"name": "u4-support", "env": env})})


# --------------------------------------------------------------------------
# reading the runner's copy
# --------------------------------------------------------------------------
def test_manifest_env_is_read(monkeypatch):
    seen = {}

    def call(method, path, body=None, worker=None):
        seen.update(method=method, path=path, worker=worker)
        return _manifest_response({"BOT_TOKEN": TOKEN, "OTHER": "x"})

    monkeypatch.setattr(runner_client, "_runner_http", call)
    env = env_rescue.read_manifest_env("runner-1", "https://runner.example")
    assert env == {"BOT_TOKEN": TOKEN, "OTHER": "x"}
    # The manifest is fetched from the job's OWN worker, with the file endpoint.
    assert seen["worker"] == "https://runner.example"
    assert "path=job.json" in seen["path"]


def test_manifest_missing_or_broken_is_never_a_guess(monkeypatch):
    for response in (Resp(404, None, "Job not found."),
                     Resp(200, {"content": "not json at all"}),
                     Resp(200, {"content": json.dumps({"env": "nope"})})):
        monkeypatch.setattr(runner_client, "_runner_http",
                            lambda *a, _r=response, **k: _r)
        assert env_rescue.read_manifest_env("runner-1") == {}

    def boom(*a, **k):
        raise RuntimeError("runner asleep")

    monkeypatch.setattr(runner_client, "_runner_http", boom)
    assert env_rescue.read_manifest_env("runner-1") == {}
    assert env_rescue.read_manifest_env("") == {}      # no runner id, no call


# --------------------------------------------------------------------------
# repairing a row
# --------------------------------------------------------------------------
def test_unreadable_row_is_repaired_from_the_runner(monkeypatch):
    monkeypatch.setattr(runner_client, "_runner_http",
                        lambda *a, **k: _manifest_response({"BOT_TOKEN": TOKEN}))
    row = _insert_job(name="rescued-one")
    _values, readable = secrets_store.read_env(row["env"])
    assert not readable, "the fixture row must start unreadable"

    env, outcome = env_rescue.rescue_job_env(row)
    assert outcome == env_rescue.RESCUED
    assert env["BOT_TOKEN"] == TOKEN

    # …and the database itself is fixed, so the NEXT start needs no rescue.
    stored = _stored_env(row["id"])
    assert not stored.startswith(secrets_store.LEGACY_PREFIX)
    values, readable = secrets_store.read_env(stored)
    assert readable and values["BOT_TOKEN"] == TOKEN


def test_readable_row_is_left_alone(monkeypatch):
    def no_calls(*a, **k):
        raise AssertionError("a readable row must not reach out to the runner")

    monkeypatch.setattr(runner_client, "_runner_http", no_calls)
    row = _insert_job(name="healthy", env=secrets_store.pack_env({"BOT_TOKEN": TOKEN}))
    env, outcome = env_rescue.rescue_job_env(row)
    assert outcome == env_rescue.FINE
    assert env["BOT_TOKEN"] == TOKEN


def test_no_copy_anywhere_is_reported_honestly(monkeypatch):
    monkeypatch.setattr(runner_client, "_runner_http",
                        lambda *a, **k: Resp(404, None, "Job not found."))
    row = _insert_job(name="gone-both-sides")
    before = _stored_env(row["id"])
    env, outcome = env_rescue.rescue_job_env(row)
    assert outcome == env_rescue.UNAVAILABLE
    assert env == {}
    # The row is preserved, not blanked: it may still be readable elsewhere, and
    # wiping it would destroy the last trace of what was there.
    assert _stored_env(row["id"]) == before


def test_boot_sweep_counts_what_it_fixed(monkeypatch):
    # A shared database may already hold unreadable rows from another suite, so
    # the counts are relative to what was there before this test added its own.
    already = len(env_rescue.unreadable_rows())
    monkeypatch.setattr(runner_client, "_runner_http",
                        lambda *a, **k: _manifest_response({"BOT_TOKEN": TOKEN}))
    _insert_job(name="sweep-a")
    _insert_job(name="sweep-b", runner_job_id=None)      # nothing to read back
    report = env_rescue.rescue_unreadable_rows()
    assert report["unreadable"] == already + 2
    assert report["rescued"] >= 1
    assert report["unavailable"] >= 1
    assert "sweep-b" in report["names"]
    # sweep-a was repaired, sweep-b could not be: exactly one of the two is left.
    assert env_rescue.unreadable_count() == report["unavailable"]


# --------------------------------------------------------------------------
# the paths an owner actually hits
# --------------------------------------------------------------------------
def test_recovery_rescues_instead_of_skipping(monkeypatch):
    row = _insert_job(name="recover-me")
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [row])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})
    started = {}

    def call(method, path, body=None, worker=None):
        if path == "/health":
            return Resp(200, {"status": "ok"})           # the worker answers
        if path == "/internal/jobs/runner-1/file?path=job.json":
            return _manifest_response({"BOT_TOKEN": TOKEN})
        if method == "POST" and path == "/internal/jobs":
            started.update(body=body)
            resp = Resp(201, {"id": "fresh-runner-id"})
            resp.placed_on = worker
            return resp
        return Resp(200, {})

    monkeypatch.setattr(runner_client, "_runner_http", call)
    monkeypatch.setattr(job_recovery, "_remember", lambda *a, **k: None)
    from services import snapshots
    monkeypatch.setattr(snapshots, "restore_snapshot", lambda *a, **k: {"restored": 0})

    assert job_recovery.recover_once() == 0              # nothing unresolved
    assert started["body"]["env"]["BOT_TOKEN"] == TOKEN  # started WITH its token


def test_cold_start_refusal_says_what_to_do(monkeypatch):
    monkeypatch.setattr(runner_client, "_runner_http",
                        lambda *a, **k: Resp(404, None, "Job not found."))
    row = _insert_job(name="dark-bot")
    result = bot_ops._cold_start(row, code="import os\nprint(os.getenv('BOT_TOKEN'))")
    assert not result.get("ok")
    message = result["error"]
    # The fix is in the message; the storage mechanism is not the user's problem.
    assert "BOT_TOKEN" in message and "Env" in message
    for word in ("encryption", "encrypted", "key"):
        assert word not in message.lower(), message


def test_cold_start_uses_the_rescued_env(monkeypatch):
    row = _insert_job(name="comes-back")
    created = {}

    def call(method, path, body=None, worker=None):
        if path == "/internal/jobs/runner-1/file?path=job.json":
            return _manifest_response({"BOT_TOKEN": TOKEN})
        if method == "POST" and path == "/internal/jobs":
            created.update(body=body)
            resp = Resp(201, {"id": "new-id"})
            resp.placed_on = worker
            return resp
        return Resp(200, {"jobs": []})

    monkeypatch.setattr(runner_client, "_runner_http", call)
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})
    monkeypatch.setattr(bot_ops, "_set_assignment", lambda *a, **k: None)

    result = bot_ops._cold_start(row, code="print('bot')")
    assert result.get("ok"), result
    assert created["body"]["env"]["BOT_TOKEN"] == TOKEN


def test_editing_env_on_a_broken_row_keeps_the_other_variables(monkeypatch):
    """The quiet data-loss bug: read an unreadable row as {}, add one variable,
    write {} + that one back, and every other secret the app had is gone."""
    def no_calls(*a, **k):
        raise AssertionError("a plain read must not reach out to the runner")

    row = _insert_job(name="edit-me")
    # A list endpoint reads many rows at once, so it must not stall on a
    # sleeping runner: rescue=False reports what the database can say.
    monkeypatch.setattr(runner_client, "_runner_http", no_calls)
    assert bot_ops._row_env(row, rescue=False) == {}

    # A start or an edit DOES rescue, which is what stops the wipe.
    monkeypatch.setattr(runner_client, "_runner_http",
                        lambda *a, **k: _manifest_response({"BOT_TOKEN": TOKEN,
                                                            "API_KEY": "keep-me"}))
    env = bot_ops._row_env(row)
    assert env == {"BOT_TOKEN": TOKEN, "API_KEY": "keep-me"}
    # The repair is written through, so the row is readable from now on.
    values, readable = secrets_store.read_env(_stored_env(row["id"]))
    assert readable and values["API_KEY"] == "keep-me"
