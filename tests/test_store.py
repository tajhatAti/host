"""Bot Store: catalog, install, ratings, favourites, submissions, moderation.

The product rule under test everywhere in here: a store listing is ONE
complete Python file. Nothing in the store may hand out a fragment, a custom
dialect, or a file whose token is baked into the source.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("JOB_SECRETS_KEY", "store-test-key-not-for-production")

import database
from routes.deps import hash_password, now_utc_str

database.init_db()
from app import app
from fastapi.testclient import TestClient
from services import store

client = TestClient(app)

PASSWORD = "Passw0rd!x"

GOOD_BOT = '''# requirements: python-telegram-bot==21.4
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Store sample is online.")


app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
app.add_handler(CommandHandler("start", start))
app.run_polling()
'''

BROKEN_BOT = GOOD_BOT.replace("app.run_polling()", "app.run_polling(")
HARDCODED_BOT = GOOD_BOT.replace('os.getenv("BOT_TOKEN")', '"123456789:AAHfakeTokenValueForStoreTests0123456789abcd"')
NO_TOKEN_BOT = '''import time
while True:
    print("no telegram here")
    time.sleep(5)
'''


def setup_module():
    conn = database.get_db_connection()
    now = now_utc_str()
    conn.execute(
        "INSERT INTO users (username,email,password,is_verified,is_admin,created_at,updated_at)"
        " VALUES (?,?,?,1,1,?,?)",
        ("store-admin", "store-admin@gmail.com", hash_password(PASSWORD), now, now),
    )
    conn.execute(
        "INSERT INTO users (username,email,password,is_verified,created_at,updated_at)"
        " VALUES (?,?,?,1,?,?)",
        ("store-member", "store-member@gmail.com", hash_password(PASSWORD), now, now),
    )
    conn.commit()
    conn.close()


_TOKENS = {}


def _headers(email):
    # One login per account for the whole run: the login endpoint rate-limits
    # per IP, and these tests share a client.
    cached = _TOKENS.get(email)
    if cached:
        return {"Authorization": "Bearer " + cached}
    response = client.post("/login", json={"username": email, "email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    _TOKENS[email] = response.json()["token"]
    return {"Authorization": "Bearer " + _TOKENS[email]}


def member_headers():
    return _headers("store-member@gmail.com")


def admin_headers():
    return _headers("store-admin@gmail.com")


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def test_catalog_lists_the_complete_python_products():
    data = client.get("/api/store").json()
    assert data["total"] == 7
    slugs = {item["slug"] for item in data["items"]}
    assert "complete-group-manager" in slugs and "complete-ai-support" in slugs
    for item in data["items"]:
        assert item["language"] == "python"
        assert item["status"] == "published"
        assert item["code_lines"] > 20
        assert item["features"], item["slug"]
        assert item["requirements"], item["slug"]


def test_anonymous_browsing_never_receives_full_source():
    item = client.get("/api/store/complete-file-share").json()
    assert item["code_full"] is False
    assert "code" not in item
    assert len(item["code_preview"].split("\n")) <= store.PREVIEW_LINES
    assert client.get("/api/store/definitely-not-a-listing").status_code == 404


def test_search_category_and_sort_narrow_the_catalog():
    hit = client.get("/api/store", params={"q": "captcha"}).json()
    assert [item["slug"] for item in hit["items"]] == ["complete-group-manager"]
    channel = client.get("/api/store", params={"category": "Channels"}).json()
    assert [item["slug"] for item in channel["items"]] == ["complete-channel-manager"]
    assert client.get("/api/store", params={"category": "Channels", "q": "captcha"}).json()["total"] == 0
    named = client.get("/api/store", params={"sort": "name"}).json()
    titles = [item["title"] for item in named["items"]]
    assert titles == sorted(titles, key=str.lower)


def test_facets_report_every_category_once():
    facets = client.get("/api/store/categories").json()
    assert facets["listings"] == 7
    assert {row["name"]: row["count"] for row in facets["categories"]}["Commerce"] == 1
    assert "Utilities" in facets["allowed"]


def test_store_page_is_a_real_url():
    response = client.get("/store", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "<html" in response.text.lower()


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def test_install_requires_a_session_and_hands_over_the_whole_file():
    assert client.post("/api/store/complete-file-share/install", json={}).status_code == 401
    headers = member_headers()
    before = client.get("/api/store/complete-file-share").json()["install_count"]
    result = client.post("/api/store/complete-file-share/install", headers=headers, json={})
    assert result.status_code == 200, result.text
    item = result.json()["item"]
    assert item["code"].strip().startswith("# requirements:")
    compile(item["code"], "installed.py", "exec")
    assert 'os.getenv("BOT_TOKEN")' in item["code"]
    assert any(field["key"] == "ADMIN_CLAIM_CODE" for field in item["env_fields"])
    after = client.get("/api/store/complete-file-share").json()["install_count"]
    assert after == before + 1
    library = client.get("/api/store/mine/library", headers=headers).json()
    assert "complete-file-share" in library["installed"]
    assert library["installs"][0]["title"] == "Complete file share"


def test_installing_an_unlisted_slug_is_a_404():
    assert client.post("/api/store/nope/install", headers=member_headers(), json={}).status_code == 404


# ---------------------------------------------------------------------------
# Ratings and favourites
# ---------------------------------------------------------------------------


def test_one_rating_per_person_and_the_average_follows():
    headers = member_headers()
    assert client.post("/api/store/complete-commerce/rate", headers=headers,
                       json={"rating": 9}).status_code == 400
    first = client.post("/api/store/complete-commerce/rate", headers=headers,
                        json={"rating": 5, "comment": "Orders flow works."})
    assert first.status_code == 200, first.text
    assert first.json()["rating_count"] == 1 and first.json()["rating_average"] == 5
    again = client.post("/api/store/complete-commerce/rate", headers=headers,
                        json={"rating": 3, "comment": "Needed a tweak."})
    assert again.json()["rating_count"] == 1 and again.json()["rating_average"] == 3
    listing = client.get("/api/store/complete-commerce", headers=headers).json()
    assert listing["rating"] == 3 and listing["rating_count"] == 1
    assert listing["reviews"][0]["comment"] == "Needed a tweak."


def test_favourites_are_per_person_and_reversible():
    headers = member_headers()
    assert client.post("/api/store/complete-group-manager/favorite", headers=headers,
                       json={"favorite": True}).status_code == 200
    client.post("/api/store/complete-group-manager/favorite", headers=headers,
                json={"favorite": True})
    library = client.get("/api/store/mine/library", headers=headers).json()
    assert library["favorite_slugs"] == ["complete-group-manager"]
    client.delete("/api/store/complete-group-manager/favorite", headers=headers)
    assert client.get("/api/store/mine/library", headers=headers).json()["favorite_slugs"] == []


def test_catalog_marks_what_the_signed_in_person_already_took():
    headers = member_headers()
    data = client.get("/api/store", headers=headers).json()
    assert "complete-file-share" in data["installed_slugs"]
    anonymous = client.get("/api/store").json()
    assert anonymous["installed_slugs"] == [] and anonymous["favorite_slugs"] == []


# ---------------------------------------------------------------------------
# Community submissions
# ---------------------------------------------------------------------------


def _submission(**over):
    body = {
        "title": "Simple echo bot",
        "summary": "Echoes every message back, one complete Python file.",
        "description": "A tiny starter that replies with the text it receives.",
        "category": "Utilities",
        "difficulty": "Beginner",
        "tags": ["echo", "starter"],
        "features": ["Replies to any text", "Reads the token from the environment"],
        "setup_notes": "Press Start in the bot chat.",
        "env_fields": [{"key": "AI_API_KEY", "label": "Optional API key", "secret": True}],
        "code": GOOD_BOT,
    }
    body.update(over)
    return body


def test_submission_rejects_code_that_is_not_one_runnable_python_file():
    headers = member_headers()
    for payload, needle in (
        (_submission(code=BROKEN_BOT), "syntax error"),
        (_submission(code=HARDCODED_BOT), "bot token is embedded"),
        (_submission(code=NO_TOKEN_BOT), "must come from the environment"),
        (_submission(code=""), "empty"),
        (_submission(title="ab"), "title"),
        (_submission(category="Not A Category"), "categor"),
    ):
        response = client.post("/api/store/items", headers=headers, json=payload)
        assert response.status_code == 400, (needle, response.text)
        assert needle.lower() in response.json()["detail"].lower(), (needle, response.text)


def test_submission_validation_reports_lines_and_warnings():
    checks = store.check_code(GOOD_BOT)
    assert checks["ok"] and checks["lines"] > 10
    assert checks["requirements"] == ["python-telegram-bot==21.4"]
    assert store.check_code(NO_TOKEN_BOT)["warnings"], "a non-bot file must warn"


def test_a_good_submission_is_pending_until_an_owner_approves_it():
    headers = member_headers()
    created = client.post("/api/store/items", headers=headers, json=_submission())
    assert created.status_code == 200, created.text
    slug = created.json()["slug"]
    assert created.json()["status"] == "pending"
    assert slug == "simple-echo-bot"

    # Pending listings are invisible to the public catalog…
    assert client.get("/api/store", params={"q": "echo"}).json()["total"] == 0
    assert client.get(f"/api/store/{slug}").status_code == 404
    # …but visible to their author.
    mine = client.get("/api/store/mine/library", headers=headers).json()
    assert mine["submissions"][0]["slug"] == slug
    assert mine["submissions"][0]["status"] == "pending"

    # A second submission with the same title gets a distinct slug.
    again = client.post("/api/store/items", headers=headers, json=_submission())
    assert again.json()["slug"] == "simple-echo-bot-2"


def test_owner_review_publishes_rejects_and_features():
    slug = "simple-echo-bot"
    member = member_headers()
    # Stealth: a member (and a stranger) cannot see the queue at all.
    assert client.get("/api/store/admin/queue").status_code == 404
    assert client.get("/api/store/admin/queue", headers=member).status_code == 404
    assert client.post(f"/api/store/admin/{slug}/approve", headers=member,
                       json={}).status_code == 404

    admin = admin_headers()
    queue = client.get("/api/store/admin/queue", headers=admin).json()
    assert queue["stats"]["pending"] == 2
    assert any(row["slug"] == slug for row in queue["items"])

    approved = client.post(f"/api/store/admin/{slug}/approve", headers=admin,
                           json={"note": "Clean single-file starter."})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "published"

    listing = client.get(f"/api/store/{slug}", headers=member).json()
    assert listing["code"].strip() == GOOD_BOT.strip()
    assert listing["author"] == "store-member"
    assert listing["env_fields"][0]["key"] == "AI_API_KEY"
    assert listing["framework"] == "python-telegram-bot"
    assert client.get("/api/store", params={"source": "community"}).json()["total"] == 1

    featured = client.post(f"/api/store/admin/{slug}/feature", headers=admin, json={})
    assert featured.json()["featured"] is True
    top = client.get("/api/store", params={"sort": "popular"}).json()["items"][0]
    assert top["slug"] == slug and top["featured"] is True

    removed = client.post(f"/api/store/admin/{slug}/remove", headers=admin, json={"note": "dup"})
    assert removed.json()["status"] == "removed"
    assert client.get(f"/api/store/{slug}").status_code == 404
    restored = client.post(f"/api/store/admin/{slug}/restore", headers=admin, json={})
    assert restored.json()["status"] == "published"
    # Restoring one listing puts exactly one back: the second is still pending.
    assert client.get("/api/store", params={"q": "echo"}).json()["total"] == 1

    client.post("/api/store/admin/simple-echo-bot-2/approve", headers=admin, json={})
    assert client.get("/api/store", params={"q": "echo"}).json()["total"] == 2
    assert client.get("/api/store", params={"source": "community"}).json()["total"] == 2

    rejected = client.post("/api/store/admin/simple-echo-bot-2/reject", headers=admin,
                           json={"note": "Duplicate of the first submission."})
    assert rejected.json()["status"] == "rejected"
    assert client.get("/api/store", params={"q": "echo"}).json()["total"] == 1
    mine = client.get("/api/store/mine/library", headers=member).json()
    note = {row["slug"]: row["review_note"] for row in mine["submissions"]}
    assert note["simple-echo-bot-2"] == "Duplicate of the first submission."


def test_author_can_revise_their_own_listing_but_not_someone_elses():
    member = member_headers()
    admin = admin_headers()
    revised = client.patch("/api/store/items/simple-echo-bot", headers=member,
                           json=_submission(code=GOOD_BOT.replace("Store sample", "Revised sample"),
                                            version="1.1.0"))
    assert revised.status_code == 200, revised.text
    assert revised.json()["version"] == "1.1.0"
    assert revised.json()["status"] == "pending"
    assert client.patch("/api/store/items/complete-commerce", headers=member,
                        json=_submission()).status_code == 404
    client.post("/api/store/admin/simple-echo-bot/approve", headers=admin, json={})
    assert "Revised sample" in client.get("/api/store/simple-echo-bot",
                                         headers=member).json()["code"]


# ---------------------------------------------------------------------------
# Built-in mirror keeps its statistics
# ---------------------------------------------------------------------------


def test_resyncing_builtins_keeps_installs_and_ratings():
    conn = database.get_db_connection()
    try:
        before = conn.execute(
            "SELECT install_count, rating_count, rating_sum FROM store_items"
            " WHERE slug = 'complete-file-share'"
        ).fetchone()
        assert before["install_count"] >= 1
        store.sync_builtins(conn, now_utc_str())
        after = conn.execute(
            "SELECT install_count, rating_count, rating_sum FROM store_items"
            " WHERE slug = 'complete-file-share'"
        ).fetchone()
        assert (after["install_count"], after["rating_count"], after["rating_sum"]) == \
               (before["install_count"], before["rating_count"], before["rating_sum"])
        # Every built-in product stays published and complete Python.
        rows = conn.execute(
            "SELECT slug, code, status FROM store_items WHERE source = 'built-in'"
        ).fetchall()
        assert len(rows) == 7
        for row in rows:
            assert row["status"] == "published"
            compile(row["code"], row["slug"] + ".py", "exec")
    finally:
        conn.close()


def test_stats_summarise_the_store_for_the_owner_console():
    stats = client.get("/api/store/admin/stats", headers=admin_headers()).json()
    assert stats["listings"] == 8
    assert stats["installs"] >= 1
    assert stats["ratings"] == 1
    assert stats["top"][0]["install_count"] >= 1
