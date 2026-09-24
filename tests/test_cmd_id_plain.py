""" /id must be copy-friendly — no broken <id> markup. """
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "id.db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("BOT_TOKEN", "")

from services import pingbot

def test_cmd_id_sends_plain_copyable_ids(monkeypatch):
    sent = []
    monkeypatch.setattr(pingbot, "_send_plain", lambda chat, text: sent.append(("plain", text)))
    monkeypatch.setattr(pingbot, "_send", lambda chat, text, reply_markup=None: sent.append(("md", text)))
    monkeypatch.setattr(pingbot, "_open_kb", lambda: None)
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat", lambda c: None)
    pingbot.cmd_id(42, {"id": 42, "username": "demo_user"})
    assert sent, "must send something"
    plain = "\n".join(t for k, t in sent if k == "plain")
    assert "42" in plain
    assert "<id>" not in plain and "&lt;" not in plain
    assert "/queen" not in plain
    assert "/admin" not in plain
    assert "Admin" not in plain


def test_guide_pngs_exist():
    for name in ("guide_start", "guide_import", "guide_id", "guide_token", "guide_admin"):
        path = pingbot._guide_path(name)
        assert path is not None and path.is_file(), name
