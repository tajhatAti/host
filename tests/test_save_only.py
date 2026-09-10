"""Save must persist code without restarting the running bot."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "routes" / "runspace.py").read_text()
JS = (ROOT / "static" / "pro.js").read_text()
HTML = (ROOT / "index.html").read_text()


def test_save_only_field_exists():
    assert "save_only: bool = False" in SRC


def test_save_only_returns_before_runner():
    start = SRC.find("if payload.save_only:")
    assert start > 0
    end = SRC.find("rate_limit_user", start)
    branch = SRC[start:end]
    assert "return out" in branch
    assert "_runner_http" not in branch
    assert "desired_state" not in branch


def test_header_has_save_and_run():
    assert 'id="btnSaveQuick"' in HTML
    assert 'id="btnRunQuick"' in HTML
    assert 'id="rsBotHealth"' not in HTML


def test_client_sends_save_only():
    assert "save_only: true" in JS
    assert "async function saveJobCode" in JS
