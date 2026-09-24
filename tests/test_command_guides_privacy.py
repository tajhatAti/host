"""Guides exist; /id and /guide never leak admin surface to normals."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "g.db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("BOT_TOKEN", "")

from services import pingbot


def test_all_public_guide_pngs_exist():
    for topic in pingbot._COMMAND_GUIDES:
        png = pingbot._COMMAND_GUIDES[topic][0]
        path = pingbot._guide_path(png)
        assert path is not None and path.is_file(), topic


def test_help_guide_kb_hides_admin_for_normals():
    kb = pingbot._help_guide_kb(user=None)
    flat = str(kb)
    assert "help:admin" not in flat
    kb2 = pingbot._help_guide_kb(user={"is_admin": 0, "telegram_id": 1})
    assert "help:admin" not in str(kb2)


def test_help_guide_kb_shows_admin_only_for_admin(monkeypatch):
    monkeypatch.setattr(pingbot, "_is_admin", lambda u, t=None: True)
    kb = pingbot._help_guide_kb(user={"is_admin": 1, "telegram_id": 9})
    assert "help:admin" in str(kb)


def test_cmd_id_hides_admin_cmds_for_normal(monkeypatch):
    sent = []
    monkeypatch.setattr(pingbot, "_send_plain", lambda c, t: sent.append(t))
    monkeypatch.setattr(pingbot, "_send", lambda *a, **k: None)
    monkeypatch.setattr(pingbot, "_open_kb", lambda: None)
    monkeypatch.setattr(pingbot, "_maybe_guide", lambda *a, **k: None)
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat",
                        lambda c: {"id": 7, "username": "u", "is_admin": 0})
    monkeypatch.setattr(pingbot, "_is_admin", lambda u, t=None: False)
    pingbot.cmd_id(99, {"id": 99, "username": "u"})
    plain = "\n".join(sent)
    assert "99" in plain
    assert "/queen" not in plain and "/admin" not in plain


def test_cmd_id_shows_admin_cmds_only_to_admin(monkeypatch):
    sent = []
    monkeypatch.setattr(pingbot, "_send_plain", lambda c, t: sent.append(t))
    monkeypatch.setattr(pingbot, "_send", lambda *a, **k: None)
    monkeypatch.setattr(pingbot, "_open_kb", lambda: None)
    monkeypatch.setattr(pingbot, "_maybe_guide", lambda *a, **k: None)
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat",
                        lambda c: {"id": 7, "username": "boss", "is_admin": 1})
    monkeypatch.setattr(pingbot, "_is_admin", lambda u, t=None: True)
    pingbot.cmd_id(99, {"id": 99})
    plain = "\n".join(sent)
    assert "/queen" in plain and "/admin limit" in plain


def test_bare_ping_reply_hides_hostname(monkeypatch):
    """Bare /ping must not print the deploy hostname."""
    sent = []
    monkeypatch.setattr(pingbot, "_send", lambda c, t, reply_markup=None: sent.append(t))
    monkeypatch.setattr(pingbot, "_ping_kb", lambda: None)
    monkeypatch.setattr(pingbot, "ping_default_target", lambda: "https://secret-host.example")
    monkeypatch.setattr(pingbot, "_ping_host_allowed", lambda h: (True, ""))
    class R:
        status_code = 200
        headers = {}
    monkeypatch.setattr(pingbot.requests, "request", lambda *a, **k: R())
    pingbot.handle_ping(1, "/ping")
    body = "\n".join(sent)
    assert "secret-host" not in body
    assert "Platform is reachable" in body
