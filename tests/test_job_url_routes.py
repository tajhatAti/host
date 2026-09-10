import os
import tempfile
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

from fastapi.testclient import TestClient
from app import app

c = TestClient(app)


def test_canonical_bot_paths_serve_spa_shell():
    for path in ("/bots/my-bot", "/bots/my-bot/logs", "/bots/my-bot/details",
                 "/bots/my-bot/database", "/bots/my-bot/env", "/bots/my-bot/settings"):
        r = c.get(path, headers={"Accept": "text/html"})
        assert r.status_code == 200, path
        assert "<html" in r.text.lower()


def test_retired_runspace_paths_redirect_to_bots():
    cases = {
        "/runspace": "/bots",
        "/jobs": "/bots",
        "/runspace/my-bot": "/bots/my-bot",
        "/runspace/owner/my-bot/page": "/bots/owner/my-bot/page",
    }
    for old, new in cases.items():
        response = c.get(old, follow_redirects=False)
        assert response.status_code == 308
        assert response.headers["location"] == new
