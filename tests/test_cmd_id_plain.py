""" /id must be copy-friendly — HTML <code> chips, no admin leak. """
from pathlib import Path
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "id.db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("BOT_TOKEN", "")

from services import pingbot


def test_cmd_id_sends_html_code_chips(monkeypatch):
    sent = []
    monkeypatch.setattr(pingbot, "_send_html", lambda chat, text, reply_markup=None: sent.append(text))
    monkeypatch.setattr(pingbot, "_send", lambda *a, **k: None)
    monkeypatch.setattr(pingbot, "_send_plain", lambda *a, **k: None)
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat", lambda c: None)
    monkeypatch.setattr(pingbot, "_is_admin", lambda u, t=None: False)
    pingbot.cmd_id(42, {"id": 42, "username": "demo_user"})
    assert sent, "must send something"
    body = sent[0]
    assert "<code>42</code>" in body
    assert "<id>" not in body and "&lt;id&gt;" not in body
    assert "/queen" not in body and "/admin" not in body


def test_cmd_id_admin_gets_copyable_commands(monkeypatch):
    sent = []
    monkeypatch.setattr(pingbot, "_send_html", lambda chat, text, reply_markup=None: sent.append(text))
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat",
                        lambda c: {"id": 7, "username": "boss", "is_admin": 1})
    monkeypatch.setattr(pingbot, "_is_admin", lambda u, t=None: True)
    monkeypatch.setattr(pingbot, "_user_is_queen", lambda u: False)
    pingbot.cmd_id(99, {"id": 99})
    body = sent[0]
    assert "<code>/queen 7</code>" in body or "<code>/queen 99</code>" in body


def test_guide_pngs_exist():
    for name in ("guide_start", "guide_import", "guide_id", "guide_token", "guide_code"):
        path = pingbot._guide_path(name)
        assert path is not None and path.is_file(), name


def test_apps_card_renders(tmp_path):
    apps = [
        {"id": 1, "name": "alpha", "status": "running", "mem_mb": 30, "uptime_s": 100},
        {"id": 2, "name": "beta", "status": "stopped", "mem_mb": 0, "uptime_s": 0},
    ]
    path = pingbot._render_apps_card(apps, running=1, limit=3, mem_mb=30)
    assert path and Path(path).is_file() and Path(path).stat().st_size > 1000


def test_no_auto_maybe_guide_on_ops_commands():
    """Operational commands must not call _maybe_guide (spam)."""
    import inspect
    for name in ("cmd_apps", "cmd_logs", "cmd_restart", "cmd_stop", "cmd_status", "cmd_id"):
        src = inspect.getsource(getattr(pingbot, name))
        assert "_maybe_guide" not in src, name
