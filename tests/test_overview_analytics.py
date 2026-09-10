"""Overview analytics: KPIs, period deltas, the daily series, and isolation.

The rule under test everywhere: a number on the dashboard must come from a
recorded event. So these tests write the events first, then assert the figures
— and they assert the two cases that are easiest to fake: a delta with no
baseline (must be null, not +100%) and a day with no activity (must be a zero
in the series, not a missing point).
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("JOB_SECRETS_KEY", "overview-test-key")

import database
from routes.deps import hash_password, now_utc_str

database.init_db()
from app import app
from fastapi.testclient import TestClient
from services import user_analytics

client = TestClient(app)
PASSWORD = "Passw0rd!x"
_TOKENS = {}


def setup_module():
    conn = database.get_db_connection()
    now = now_utc_str()
    for name, email in (("ov-owner", "ov-owner@gmail.com"), ("ov-other", "ov-other@gmail.com")):
        conn.execute(
            "INSERT INTO users (username,email,password,is_verified,created_at,updated_at)"
            " VALUES (?,?,?,1,?,?)", (name, email, hash_password(PASSWORD), now, now))
    conn.commit()
    conn.close()


def _headers(email):
    if email not in _TOKENS:
        response = client.post("/login", json={"username": email, "email": email,
                                               "password": PASSWORD})
        assert response.status_code == 200, response.text
        _TOKENS[email] = response.json()["token"]
    return {"Authorization": "Bearer " + _TOKENS[email]}


def _stamp(days_ago, hour=12):
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.replace(hour=hour, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _seed():
    """Two bots, a spread of deploys across this period and the previous one."""
    conn = database.get_db_connection()
    owner = conn.execute("SELECT id FROM users WHERE username='ov-owner'").fetchone()["id"]
    other = conn.execute("SELECT id FROM users WHERE username='ov-other'").fetchone()["id"]
    now = now_utc_str()

    conn.execute("INSERT INTO jobs (user_id,name,language,code,runner_job_id,"
                 "telegram_bot_detected,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                 (owner, "shop-bot", "python", "x", "runner-1", 1, _stamp(3), now))
    conn.execute("INSERT INTO jobs (user_id,name,language,code,runner_job_id,"
                 "telegram_bot_detected,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                 (owner, "scratch-bot", "python", "y", None, 0, _stamp(20), now))
    bot_a = conn.execute("SELECT id FROM jobs WHERE name='shop-bot'").fetchone()["id"]
    bot_b = conn.execute("SELECT id FROM jobs WHERE name='scratch-bot'").fetchone()["id"]

    for days_ago, action in ((1, "deploy"), (1, "update"), (2, "deploy"), (6, "update")):
        conn.execute("INSERT INTO job_deploy_events (user_id,job_id,action,job_name,created_at)"
                     " VALUES (?,?,?,?,?)", (owner, bot_a, action, "shop-bot", _stamp(days_ago)))
    conn.execute("INSERT INTO job_deploy_events (user_id,job_id,action,job_name,created_at)"
                 " VALUES (?,?,?,?,?)", (owner, bot_b, "deploy", "scratch-bot", _stamp(18)))
    conn.execute("INSERT INTO store_installs (item_slug,user_id,version,created_at)"
                 " VALUES (?,?,?,?)", ("complete-commerce", owner, "1.0.0", _stamp(2)))

    # Another account's traffic, which must never appear above. Its deploy
    # event points at a real job of its own — job_deploy_events has a FK.
    conn.execute("INSERT INTO jobs (user_id,name,language,code,created_at,updated_at)"
                 " VALUES (?,?,?,?,?,?)", (other, "their-bot", "python", "z", _stamp(1), now))
    their_bot = conn.execute("SELECT id FROM jobs WHERE name='their-bot'").fetchone()["id"]
    conn.execute("INSERT INTO job_deploy_events (user_id,job_id,action,job_name,created_at)"
                 " VALUES (?,?,?,?,?)", (other, their_bot, "deploy", "their-bot", _stamp(1)))
    conn.commit()
    conn.close()
    return owner


OWNER_ID = None


def test_endpoint_requires_a_session():
    assert client.get("/api/analytics/overview").status_code == 401


def test_kpis_count_only_this_account():
    global OWNER_ID
    OWNER_ID = _seed()
    data = client.get("/api/analytics/overview?days=14",
                      headers=_headers("ov-owner@gmail.com")).json()
    by_key = {k["key"]: k for k in data["kpis"]}
    assert by_key["bots"]["value"] == 2                     # not 3 — theirs is excluded
    assert by_key["live"]["value"] == 1                     # only shop-bot holds a runner
    assert by_key["deploys"]["value"] == 4                  # this period only, not the 18-day one
    assert by_key["installs"]["value"] == 1
    assert by_key["bots"]["sub"].startswith("1 Telegram")
    assert "their-bot" not in str(data)


def test_a_delta_is_real_arithmetic_when_a_baseline_exists():
    conn = database.get_db_connection()
    try:
        data = user_analytics.overview(conn, OWNER_ID, days=14)
    finally:
        conn.close()
    by_key = {k["key"]: k for k in data["kpis"]}
    # This period has 4 deploys, the previous one has the seeded 18-day-old
    # deploy: (4 - 1) / 1 = +300%. The comparison is doing real work.
    assert data["totals"]["previous"]["deploys"] == 1
    assert by_key["deploys"]["delta"] == 300.0
    # "Deployed now" is a present-tense fact; it has no delta by construction.
    assert by_key["live"]["delta"] is None


def test_a_delta_with_no_baseline_is_null_not_invented():
    conn = database.get_db_connection()
    try:
        data = user_analytics.overview(conn, OWNER_ID, days=14)
    finally:
        conn.close()
    by_key = {k["key"]: k for k in data["kpis"]}
    # One store install this period and none before it: there is no honest
    # percentage to print, so the delta is null and the UI says "new".
    assert data["totals"]["previous"]["installs"] == 0
    assert by_key["installs"]["value"] == 1
    assert by_key["installs"]["delta"] is None


def test_the_series_is_zero_filled_and_the_right_length():
    data = client.get("/api/analytics/overview?days=7",
                      headers=_headers("ov-owner@gmail.com")).json()
    assert data["days"] == 7 and len(data["series"]) == 7
    days = [point["day"] for point in data["series"]]
    assert days == sorted(days), "the series must run forward in time"
    assert days[-1] == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Days 3-5 had nothing: they are points on the line, not gaps in it.
    quiet = [point for point in data["series"] if point["deploys"] == 0]
    assert quiet, "a quiet day must still appear as a zero"
    busy = [point for point in data["series"] if point["deploys"] == 2]
    assert busy, "the day with two deploys must be visible"
    # 1 day ago (deploy + update = 2) + 2 days ago (1) + 6 days ago (1) = 4;
    # all four fall inside a 7-day window, the 18-day-old one does not.
    assert sum(p["deploys"] for p in data["series"]) == 4


def test_top_bots_are_ranked_by_activity_and_carry_liveness():
    data = client.get("/api/analytics/overview?days=14",
                      headers=_headers("ov-owner@gmail.com")).json()
    names = [bot["name"] for bot in data["top_bots"]]
    assert names[0] == "shop-bot"
    top = data["top_bots"][0]
    assert top["actions"] == 4 and top["live"] is True
    other = next(bot for bot in data["top_bots"] if bot["name"] == "scratch-bot")
    assert other["actions"] == 0 and other["live"] is False


def test_recent_trail_reports_the_deploy_history():
    data = client.get("/api/analytics/overview?days=14",
                      headers=_headers("ov-owner@gmail.com")).json()
    assert data["recent"], "the trail must not be empty after seeding"
    assert data["recent"][0]["job_name"] == "shop-bot"
    assert data["recent"][0]["created_at"] >= data["recent"][-1]["created_at"]


def test_the_window_is_clamped_to_something_sane():
    headers = _headers("ov-owner@gmail.com")
    assert client.get("/api/analytics/overview?days=9999", headers=headers).json()["days"] == 90
    # 0 is falsy, so it reads as "no preference" and the default applies,
    # rather than rendering a one-day chart nobody asked for.
    assert client.get("/api/analytics/overview?days=0", headers=headers).json()["days"] == 14
    # A negative window is not a preference, it is a mistake: clamp to one day.
    assert client.get("/api/analytics/overview?days=-5", headers=headers).json()["days"] == 1


def test_an_empty_account_gets_zeros_and_an_empty_series_shape():
    data = client.get("/api/analytics/overview?days=14",
                      headers=_headers("ov-other@gmail.com")).json()
    by_key = {k["key"]: k for k in data["kpis"]}
    assert by_key["bots"]["value"] == 1
    assert by_key["deploys"]["value"] == 1
    assert len(data["series"]) == 14
    assert all(point["deploys"] >= 0 for point in data["series"])


def test_every_number_is_portable_sql():
    """No SQLite-only date function in the SQL this module actually sends."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(user_analytics))
    # Only string literals that are NOT docstrings can be SQL. The module
    # docstring names julianday/INTERVAL precisely to say they are unused,
    # and scanning it would flag the documentation instead of the query.
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        # A statement body is a LIST. Several expression nodes also carry a
        # `body` attribute that is a single node (ast.Lambda), and indexing
        # one of those raises rather than returning nothing.
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            docstrings.add(id(first.value))
    sql = [n.value for n in ast.walk(tree)
           if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
    assert sql, "the module must contain SQL to check"
    for statement in sql:
        for banned in ("julianday", "datetime('now')", "IFNULL", "GROUP_CONCAT",
                       "INSERT OR REPLACE", "INTERVAL"):
            assert banned.lower() not in statement.lower(), (banned, statement[:60])
