"""Website restart path also accepts BOT_TOKEN living in source."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "rs.db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

from routes import runspace
from services import secrets_store


def test_row_env_promotes_token_from_code():
    code = "BOT_TOKEN = \"123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw\"\nprint(1)\n"
    row = {"code": code, "env": None, "name": "x", "id": 1}
    env = runspace._row_env(row, rescue=False)
    assert env.get("BOT_TOKEN", "").startswith("123456789:")


def test_row_env_keeps_saved_token():
    row = {
        "code": "print(1)",
        "env": secrets_store.pack_env({"BOT_TOKEN": "111:from-env", "OTHER": "x"}),
        "name": "y", "id": 2,
    }
    env = runspace._row_env(row, rescue=False)
    assert env["BOT_TOKEN"] == "111:from-env"
    assert env["OTHER"] == "x"
