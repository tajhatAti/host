"""BOT_TOKEN may live in the source — Env is optional."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "tok.db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

from services import bot_ops


def test_token_from_source_finds_literal():
    code = "BOT_TOKEN = \"123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw\"\n"
    tok = bot_ops.token_from_source(code, {})
    assert tok.startswith("123456789:")


def test_ensure_promotes_code_token_into_env():
    row = {"code": "TOKEN=\"123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw\"\nprint(TOKEN)\n",
           "name": "x"}
    env = bot_ops.ensure_bot_token_in_env(row, {})
    assert env["BOT_TOKEN"].startswith("123456789:")


def test_ensure_keeps_existing_env_token():
    row = {"code": "TOKEN=\"999999999:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB\"\n"}
    env = bot_ops.ensure_bot_token_in_env(row, {"BOT_TOKEN": "111:already"})
    assert env["BOT_TOKEN"] == "111:already"


def test_ensure_empty_when_nothing():
    env = bot_ops.ensure_bot_token_in_env({"code": "print(1)"}, {})
    assert "BOT_TOKEN" not in env or not env.get("BOT_TOKEN")
