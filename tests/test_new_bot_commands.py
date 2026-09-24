"""Smoke: new overnight commands exist and parse."""
import os, sys, tempfile, ast
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "c.db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

from services import pingbot


def test_new_commands_are_callable():
    for name in ("cmd_id", "cmd_env", "cmd_backup", "cmd_history",
                 "cmd_commands", "cmd_token_tips", "_cmd_guide",
                 "_cmd_health_smart"):
        assert callable(getattr(pingbot, name)), name


def test_guide_art_and_help_kb():
    assert pingbot._guide_path("guide_token").is_file()
    kb = pingbot._help_guide_kb()
    assert kb and kb.get("inline_keyboard")


def test_handlers_register_new_commands():
    src = open(pingbot.__file__).read()
    for cmd in ('"/env"', '"/backup"', '"/history"', '"/commands"',
                '"/recover"', '"/guide"', '"/token"', '"/whoami"'):
        assert cmd in src, cmd
