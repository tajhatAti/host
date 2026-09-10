# CRITICAL BOT-FEATURE REGRESSIONS — the four bugs that made the Telegram
# integration unusable in production. Each test below fails against the old
# code and passes after the fix.
#
#   1. services/pingbot.py — `waiting_for_code` was never defined  -> NameError
#      swallowed by poll_loop, so /code silently did nothing.
#   2. services/pingbot.py — reply_markup went out as a nested dict through
#      requests' `params=`, which urlencodes to "reply_markup=inline_keyboard".
#      Every inline button vanished.
#   3. services/pingbot.py — the waiting flag was deleted on the FIRST chunk,
#      so multi-message (>4096 char) code lost everything after message one.
#   4. routes/auth.py     — the data-check-string built `for k, v in sorted(dict)`
#      which unpacks KEYS -> ValueError -> every Telegram login was a 500.
#      Plus sqlite3.Row.get() (AttributeError) and no auth_date replay check.
import hashlib
import hmac
import importlib
import json
import os
import sys
import tempfile
import time

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
TG_TOKEN = "123456:AAFakeBotTokenForTests"
os.environ["TELEGRAM_PING_BOT_TOKEN"] = TG_TOKEN
os.environ["TELEGRAM_BOT_USERNAME"] = "@MyCodeNestBot"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("✓ " if cond else "✗ FAIL ") + f"{name:58s}" + (f" — {extra}" if not cond else ""))


# ---------------------------------------------------------------------------
# Bugs 1-3: services/pingbot.py
# ---------------------------------------------------------------------------
import services.pingbot as pb  # noqa: E402

importlib.reload(pb)

_sent = []


class _Resp:
    status_code = 200

    def __init__(self, payload=None):
        self._payload = payload or {"ok": True}

    def json(self):
        return self._payload


def _fake_post(url, json=None, timeout=None):  # noqa: A002
    method = url.rsplit("/", 1)[-1]
    if method == "getUpdates":
        return _Resp({"ok": True, "result": _updates.pop(0) if _updates else []})
    _sent.append((method, json))
    return _Resp()


_updates = []
pb.requests.post = _fake_post

# --- 1. chat-based code deploy is GONE -------------------------------------
# Bugs 1 and 3 below were both about the code-collection buffer. That whole
# path has since been removed: a Telegram message caps at ~4096 characters and
# has no editor, so it could only ever serve toy scripts while looking like a
# real way to work. The regressions cannot recur because the code cannot.
# What is asserted now is that it stays gone.
for _gone in ("waiting_for_code", "code_buffer", "buffer_timer",
              "collect_code", "flush_code", "deploy_code",
              "cmd_deploy", "cmd_update"):
    check(f"{_gone} is removed", not hasattr(pb, _gone),
          f"{_gone} still exists")

# --- 2. inline keyboard survives the trip to Telegram ----------------------
_sent.clear()
pb._send(42, "hello", reply_markup=pb.get_job_buttons("job123", "https://x.dev/live/y/"))
_method, _body = _sent[0]
check("sendMessage uses a JSON body", _method == "sendMessage" and isinstance(_body, dict))
check("reply_markup is JSON-serialised", isinstance(_body.get("reply_markup"), str),
      repr(_body.get("reply_markup"))[:60])
_kb = json.loads(_body["reply_markup"])["inline_keyboard"]
_labels = [b["text"] for row in _kb for b in row]
# The original bug was that reply_markup was urlencoded and EVERY button
# vanished. Asserting an exact count of 5 made this fail the moment a sixth
# was added, which is a feature, not the regression. Assert the buttons that
# must not disappear instead.
check("the action buttons survive the trip",
      all(any(w in l for l in _labels) for w in ("Logs", "Restart", "Stop")),
      str(_labels))
check("at least the original five are there", len(_labels) >= 5, str(_labels))
check("callback buttons carry data", _kb[0][0]["callback_data"] == "logs:job123")

# --- 3. no message can become a deploy -------------------------------------
_src_pb = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "services", "pingbot.py")).read()
_src_ops = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                             "services", "bot_ops.py")).read()
check("no /code command", 'startswith("/code")' not in _src_pb)
check("no /deploy command", 'startswith("/deploy")' not in _src_pb)
check("no /update command", 'startswith("/update")' not in _src_pb)
check("no plain-text branch that collects a message as source",
      "elif chat_id in waiting_for_code" not in _src_pb)
check("the bot never POSTs a job to the runner",
      '"/internal/jobs"' not in _src_pb and '"/internal/jobs"' not in _src_ops,
      "a create path survives")
check("bot_ops has no deploy()", "def deploy(" not in _src_ops)
check("bot_ops has no update_code()", "def update_code(" not in _src_ops)
# The lifecycle commands must survive — removing creation is not removing the
# bot.
for _keep in ("/apps", "/logs", "/restart", "/stop", "/delete", "/rename",
              "/status"):
    check(f"{_keep} still works", f'"{_keep}": lambda:' in _src_pb)

# --- /start must not print a literal backslash-n ---------------------------
_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "services", "pingbot.py")).read()
check("/start uses real newlines", "\\\\n\\\\nUse /ping" not in _src)


# ---------------------------------------------------------------------------
# Bug 4: POST /auth/telegram
# ---------------------------------------------------------------------------
from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402

client = TestClient(app)


def signed_payload(**overrides):
    """Build a payload signed exactly the way Telegram signs it."""
    data = {
        "id": 555001,
        "first_name": "Ahad",
        "username": "ahad_dev",
        "photo_url": "",
        "auth_date": int(time.time()),
    }
    data.update(overrides)
    check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items()) if v not in (None, "")
    )
    secret = hashlib.sha256(TG_TOKEN.encode()).digest()
    data["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return data


r = client.post("/auth/telegram", json=signed_payload())
check("valid Telegram login -> 200 (was 500)", r.status_code == 200, r.text[:120])
check("session token issued", bool(r.json().get("token")) if r.status_code == 200 else False)

r = client.post("/auth/telegram", json=signed_payload())
check("returning user logs in (no Row.get crash)",
      r.status_code == 200 and "Login successful" in r.json().get("message", ""),
      r.text[:120])

_forged = signed_payload()
_forged["hash"] = "0" * 64
r = client.post("/auth/telegram", json=_forged)
check("forged hash rejected", r.status_code == 400, r.text[:120])

_tampered = signed_payload()
_tampered["id"] = 999999  # changed after signing
r = client.post("/auth/telegram", json=_tampered)
check("tampered field rejected", r.status_code == 400, r.text[:120])

r = client.post("/auth/telegram", json=signed_payload(auth_date=int(time.time()) - 90000))
check("stale auth_date rejected (replay)",
      r.status_code == 400 and "expired" in r.json().get("detail", "").lower(),
      r.text[:120])

# --- widget config endpoint ------------------------------------------------
r = client.get("/api/public-config")
check("/api/public-config serves bot username",
      r.status_code == 200 and r.json().get("telegram_bot_username") == "MyCodeNestBot",
      r.text[:120])

_index = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "index.html")).read()
check("no YOUR_BOT_USERNAME placeholder left", "YOUR_BOT_USERNAME" not in _index)


# ---------------------------------------------------------------------------
_passed = sum(1 for _, ok in results if ok)
_failed = len(results) - _passed
print(f"\n================ {_passed} pass, {_failed} fail ================")
sys.exit(1 if _failed else 0)
