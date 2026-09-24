"""/ping tells the truth, /apps counts correctly, and 👑 gets its own interface.

Three complaints from a live deployment, in the order they were reported:

1. `/ping` answered "❌ HTTPSConnectionPool(host='ahadorg.onrender.com',
   port=443): Read timed out." — a raw exception naming somebody else's server,
   because the default target was hardcoded to a host that has nothing to do
   with this install. Now a bare /ping measures THIS site, and every failure is
   one short line a person can act on. (It also refuses to fetch internal
   addresses: a server-side request built from user input is an SSRF hole.)
2. `/apps` said "5/3 running slots" — every app ever created, counted against
   the GLOBAL default, ignoring the per-user override. Both numbers now come
   from the same functions the cap itself uses.
3. A 👑 account saw exactly the same help as everybody else, so the privileges
   an admin had granted were invisible. Queens now get their own block in /help
   and a `/projects` command that lists the owner's ready-made projects, names
   the file that will run, gives the steps, and deploys on one tap — from the
   branch the projects actually live on.

Run:  PYTHONPATH=. pytest -q tests/test_ping_and_queen.py
"""
import json
import os
import socket
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "ping.db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

import pytest                                                    # noqa: E402
from services import bot_ops, pingbot, telegram_link             # noqa: E402

PUBLIC_IP = "93.184.216.34"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _runner_app():
    """The runner's module, loaded under its own name.

    The SITE's app.py is already imported as `app` by other suites in the same
    pytest session, so a plain `import app` would quietly hand back that one.
    """
    if "runner_app_under_test" in sys.modules:
        return sys.modules["runner_app_under_test"]
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "runner_app_under_test", os.path.join(ROOT, "runner", "app.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["runner_app_under_test"] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
@pytest.fixture
def sent(monkeypatch):
    """Every Telegram API call the bot makes, in order."""
    out = []

    def tg(method, **params):
        out.append((method, params))
        return {"ok": True, "result": {"message_id": len(out)}}

    monkeypatch.setattr(pingbot, "_tg", tg)
    return out


def texts(sent):
    return [p.get("text") or "" for m, p in sent if m == "sendMessage"]


def last(sent):
    return texts(sent)[-1] if texts(sent) else ""


def fake_dns(monkeypatch, resolve=None):
    """Keep DNS off the network: resolve= maps host -> ip (None = NXDOMAIN)."""
    resolve = resolve or {}

    def getaddrinfo(host, *a, **k):
        if host in resolve and resolve[host] is None:
            raise socket.gaierror(-2, "Name or service not known")
        return [(2, 1, 6, "", (resolve.get(host, PUBLIC_IP), 0))]

    monkeypatch.setattr(pingbot.socket, "getaddrinfo", getaddrinfo)


class Resp:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text
        self.url = ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


# --------------------------------------------------------------------------
# /ping — default target
# --------------------------------------------------------------------------
def test_bare_ping_measures_this_site_not_a_hardcoded_stranger(monkeypatch):
    monkeypatch.setattr(pingbot, "SITE_BASE", "https://ahadrunspace.onrender.com")
    assert pingbot.ping_default_target() == "https://ahadrunspace.onrender.com"

    # An explicit env var still wins, for an owner who wants a fixed target.
    monkeypatch.setenv("PING_DEFAULT_TARGET", "https://example.org")
    assert pingbot.ping_default_target() == "https://example.org"

    # With neither, the fallback is the one service every install depends on —
    # never a specific person's old host.
    monkeypatch.delenv("PING_DEFAULT_TARGET", raising=False)
    monkeypatch.setattr(pingbot, "SITE_BASE", "")
    assert "ahadorg" not in pingbot.ping_default_target()


def test_ping_reports_speed_and_status(monkeypatch, sent):
    fake_dns(monkeypatch)
    monkeypatch.setattr(pingbot, "SITE_BASE", "https://ahadrunspace.onrender.com")
    monkeypatch.setattr(pingbot.requests, "request",
                        lambda *a, **k: Resp(200, {}))
    pingbot.handle_ping(1, "/ping")
    reply = last(sent)
    assert "🟢" in reply and "HTTP 200" in reply
    assert "ahadrunspace.onrender.com" in reply
    assert "ms" in reply


def test_head_refusal_is_retried_as_get(monkeypatch, sent):
    fake_dns(monkeypatch)
    calls = []

    def request(method, url, **kwargs):
        calls.append(method)
        return Resp(405, {}) if method == "HEAD" else Resp(200, {})

    monkeypatch.setattr(pingbot.requests, "request", request)
    pingbot.handle_ping(1, "/ping https://example.com")
    assert calls == ["HEAD", "GET"]
    assert "HTTP 200" in last(sent)


def test_timeout_is_a_sentence_not_a_traceback(monkeypatch, sent):
    fake_dns(monkeypatch)

    def timeout(*a, **k):
        raise pingbot.requests.exceptions.ReadTimeout(
            "HTTPSConnectionPool(host='ahadrunspace.onrender.com', port=443): "
            "Read timed out. (read timeout=8)")

    monkeypatch.setattr(pingbot.requests, "request", timeout)
    pingbot.handle_ping(1, "/ping")
    reply = last(sent)
    assert "🔴" in reply
    assert "didn't answer" in reply
    # The wrapper that made it look like a crash is gone from the headline.
    assert not reply.startswith("❌ HTTPSConnectionPool")
    assert "port=443" not in reply.splitlines()[0]


def test_dns_failure_says_the_name_does_not_exist(monkeypatch, sent):
    fake_dns(monkeypatch, {"nosuchhost.example": None})
    monkeypatch.setattr(pingbot.requests, "request",
                        lambda *a, **k: pytest.fail("must not fetch an unresolvable host"))
    pingbot.handle_ping(1, "/ping nosuchhost.example")
    reply = last(sent)
    assert "🔴" in reply and "resolve" in reply.lower()


def test_internal_addresses_are_refused_without_fetching(monkeypatch, sent):
    fake_dns(monkeypatch, {"metadata.google.internal": "169.254.169.254",
                           "internal.example": "10.0.0.5"})

    def request(*a, **k):
        raise AssertionError("an internal address must never be fetched")

    monkeypatch.setattr(pingbot.requests, "request", request)
    for target in ("http://127.0.0.1:8000/health", "http://localhost/admin",
                   "http://169.254.169.254/latest/meta-data/",
                   "http://metadata.google.internal/", "http://internal.example/"):
        sent.clear()
        pingbot.handle_ping(1, f"/ping {target}")
        assert "🔴" in last(sent), target


def test_redirect_to_an_internal_address_is_refused(monkeypatch, sent):
    fake_dns(monkeypatch, {"public.example": PUBLIC_IP, "internal.example": "10.1.2.3"})
    monkeypatch.setattr(pingbot.requests, "request",
                        lambda method, url, **k: Resp(
                            302, {}, {"Location": "http://internal.example/secret"}))
    pingbot.handle_ping(1, "/ping http://public.example/")
    reply = last(sent)
    assert "🔴" in reply and "redirect" in reply.lower()


def test_a_url_without_a_scheme_is_accepted(monkeypatch, sent):
    fake_dns(monkeypatch)
    seen = {}
    monkeypatch.setattr(pingbot.requests, "request",
                        lambda method, url, **k: seen.update(url=url) or Resp(200, {}))
    pingbot.handle_ping(1, "/ping example.com")
    assert seen["url"].startswith("https://example.com")


# --------------------------------------------------------------------------
# message delivery
# --------------------------------------------------------------------------
def test_a_message_telegram_cannot_parse_is_still_delivered(monkeypatch):
    calls = []

    def tg(method, **params):
        calls.append(params)
        if params.get("parse_mode"):
            return {"ok": False, "description":
                    "Bad Request: can't parse entities: Unsupported start tag"}
        return {"ok": True}

    monkeypatch.setattr(pingbot, "_tg", tg)
    pingbot._send(7, "*my_bot* is running")
    assert len(calls) == 2
    assert "parse_mode" in calls[0] and "parse_mode" not in calls[1]


def test_a_rejected_message_is_not_sent_twice(monkeypatch):
    calls = []

    def tg(method, **params):
        calls.append(params)
        return {"ok": False, "description": "Bad Request: chat not found"}

    monkeypatch.setattr(pingbot, "_tg", tg)
    pingbot._send(7, "hello")
    assert len(calls) == 1


# --------------------------------------------------------------------------
# /apps — the slot count
# --------------------------------------------------------------------------
def _apps(n, running=0):
    out = []
    for i in range(n):
        out.append({"name": f"app{i}", "status": "running" if i < running else "stopped",
                    "mem_mb": 40, "uptime_s": 60, "restarts": 0})
    return out


def test_apps_header_counts_running_against_this_users_limit(monkeypatch, sent):
    user = {"id": 4, "username": "owner", "is_queen": 0}
    # Five apps exist, two are running, and an admin raised this account to 10.
    # The old header printed "5/3": every app ever made, against the global
    # default, which is not the rule the server enforces.
    monkeypatch.setattr(bot_ops, "list_apps", lambda uid: _apps(5, running=2))
    monkeypatch.setattr(bot_ops, "active_count", lambda uid: 2)
    monkeypatch.setattr(bot_ops, "effective_job_limit", lambda uid: 10)
    pingbot.cmd_apps(1, user)
    reply = last(sent)
    assert "2/10 running" in reply
    assert "5 total" in reply
    assert "5/3" not in reply
    assert "👑" not in reply            # not a queen: no crown, no queen line


def test_apps_header_shows_the_crown_and_the_default_limit(monkeypatch, sent):
    user = {"id": 5, "username": "queen", "is_queen": 1}
    monkeypatch.setattr(bot_ops, "list_apps", lambda uid: _apps(3, running=3))
    monkeypatch.setattr(bot_ops, "active_count", lambda uid: 3)
    monkeypatch.setattr(bot_ops, "effective_job_limit", lambda uid: 3)
    pingbot.cmd_apps(1, user)
    reply = last(sent)
    assert "👑" in reply and "3/3 running" in reply
    # At the cap, the way out is in the message instead of a dead end.
    assert "/stop" in reply


def test_queen_flag_falls_back_to_the_database(monkeypatch):
    monkeypatch.setattr(bot_ops, "is_queen", lambda uid: True)
    assert pingbot._user_is_queen({"id": 9}) is True       # dict without the key
    assert pingbot._user_is_queen({"id": 9, "is_queen": 0}) is False
    assert pingbot._user_is_queen(None) is False


# --------------------------------------------------------------------------
# 👑 help + /projects
# --------------------------------------------------------------------------
def test_help_is_a_separate_screen_for_queens(monkeypatch):
    """A 👑 account gets its own /help, not everybody else's with a footer.

    The old version appended a paragraph to the same screen, which is why the
    complaint was "the interface didn't become separate": the one thing only a
    queen can do was the last item on a list written for everybody.
    """
    plain = pingbot._help_text({"id": 1, "username": "ann", "is_queen": 0})
    royal = pingbot._help_text({"id": 2, "username": "bee", "is_queen": 1})
    assert plain.startswith("👋 Hi *ann*!")
    assert "👑" not in plain and "/projects" not in plain
    assert royal.startswith("👑 *CodeNest — queen access*")
    # the one-tap deploy leads, the privilege list follows, shared commands last
    assert royal.index("Run a project in one tap") < royal.index("Your queen access")
    assert royal.index("Your queen access") < royal.index("*Everything else*")
    for needle in ("No memory ceiling", ".zip", "/projects", "tree/", "/limits",
                   "BOT_TOKEN", "bee"):
        assert needle in royal, needle


def test_projects_explains_itself_to_a_non_queen(monkeypatch, sent):
    deployed = []
    monkeypatch.setattr(bot_ops, "create_app_from_repo",
                        lambda *a, **k: deployed.append(a) or {"ok": False})
    pingbot.cmd_projects(1, {"id": 3, "username": "ann", "is_queen": 0})
    reply = last(sent)
    assert "queen access" in reply.lower()
    assert "/import" in reply           # what they CAN do is still stated
    assert not deployed


TWO_PROJECTS = [
    {"name": "b", "dir": "", "entry": "bot.py", "language": "python",
     "kind": "worker", "manifests": ["requirements.txt"]},
    {"name": "web", "dir": "web", "entry": "web/dashboard.py", "language": "python",
     "kind": "web", "manifests": ["web/requirements.txt"]},
]


def test_projects_lists_what_can_run_as_buttons(monkeypatch, sent):
    """/projects used to print a file list plus a paragraph of placeholders to
    fill in by hand — the complaint was literally "it shows braces". Now every
    runnable thing in the repo is a BUTTON, naming the file that will run and
    the manifests that will be installed: nothing to type, nothing to guess."""
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_REPO", "https://github.com/tajhatAti/b")
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_BRANCH", "arena/01a0ba14-b")
    monkeypatch.setattr(pingbot.github_repo, "scan_projects", lambda *a, **k: TWO_PROJECTS)
    monkeypatch.setattr(bot_ops, "list_apps", lambda uid: [])
    monkeypatch.setattr(bot_ops, "find_app", lambda uid, name: None)

    pingbot.cmd_projects(1, {"id": 2, "username": "bee", "is_queen": 1})
    catalogue = texts(sent)[0]
    for needle in ("tajhatAti/b", "arena/01a0ba14-b", "`bot.py`",
                   "requirements.txt", "web/dashboard.py"):
        assert needle in catalogue, needle

    markups = [p for _m, p in sent if p.get("reply_markup")]
    flat = [b["callback_data"]
            for b in json.loads(markups[0]["reply_markup"])["inline_keyboard"][0]]
    all_data = [b["callback_data"]
                for row in json.loads(markups[0]["reply_markup"])["inline_keyboard"]
                for b in row]
    assert "pick:0" in all_data and "pick:1" in all_data   # one button per project
    assert "pick:all" in all_data                          # ...or the whole repo
    assert "pick:readme" in all_data and "pick:no" in all_data
    # A button carries an INDEX only. callback_data is 64 bytes and
    # attacker-supplied, so a path or a URL in it is both a truncation risk and
    # a way to make the bot clone something else.
    assert flat == ["pick:0"]
    for t in texts(sent):
        assert "<name>" not in t and "{}" not in t and "<user>" not in t


def test_pick_button_deploys_the_chosen_project(monkeypatch, sent):
    """The tap resolves server-side against the list THIS chat was shown."""
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_REPO", "https://github.com/tajhatAti/b")
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_BRANCH", "arena/01a0ba14-b")
    monkeypatch.setattr(pingbot.github_repo, "scan_projects", lambda *a, **k: TWO_PROJECTS)
    monkeypatch.setattr(telegram_link, "user_for_chat",
                        lambda cid: {"id": 2, "username": "bee", "is_queen": 1})
    monkeypatch.setattr(bot_ops, "find_app", lambda uid, name: None)
    created = {}
    monkeypatch.setattr(
        bot_ops, "create_app_from_repo",
        lambda uid, name, url, **kw: created.update(name=name, url=url, **kw)
        or {"ok": True, "name": name, "job_db_id": 7, "web": "", "commit": "3272e0c"})

    pingbot.cmd_import(1, {"id": 2, "username": "bee"}, "https://github.com/tajhatAti/b")
    assert not created                      # nothing deployed before a choice
    pingbot.handle_callback(1, "pick:1")    # the web/ dashboard, not the root bot

    assert created["entry"] == "web/dashboard.py"
    assert created["deps"] == ["web/requirements.txt"]
    assert created["url"].startswith("https://github.com/tajhatAti/b")
    reply = last(sent)
    assert "deployed and running" in reply
    assert "3272e0c" in reply               # which revision is now running
    assert "/latest" in reply               # and how to get the next one


def test_projects_survives_a_rate_limited_github(monkeypatch, sent):
    """A shared Render exit IP runs out of anonymous GitHub calls. The catalogue
    then says so and keeps the one-tap deploy and the steps: the privilege must
    not become unusable because a listing could not be read."""
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_REPO", "https://github.com/tajhatAti/b")
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_BRANCH", "arena/01a0ba14-b")
    monkeypatch.setattr(pingbot.github_repo, "scan_projects", lambda *a, **k: [])
    monkeypatch.setattr(bot_ops, "list_apps", lambda uid: [])

    pingbot.cmd_projects(1, {"id": 2, "username": "bee", "is_queen": 1})
    reply = last(sent)
    assert "Run it now" in reply
    assert "/latest" in reply and "/logs" in reply
    assert any("qproj:run" in p["reply_markup"] for _m, p in sent if p.get("reply_markup"))


def test_repo_apps_show_whether_the_branch_moved(monkeypatch, sent):
    """The Render-shaped question — "did my push deploy?" — answered on the same
    screen as the button that fixes it."""
    monkeypatch.setattr(bot_ops, "list_apps", lambda uid: [
        {"id": 11, "name": "haven", "repo_url": "https://github.com/tajhatAti/b",
         "repo_commit": "aaaaaaa1111", "auto_deploy": 1},
        {"id": 12, "name": "old", "repo_url": "https://github.com/tajhatAti/b",
         "repo_commit": "3272e0c88fb1", "auto_deploy": 0},
    ])
    monkeypatch.setattr(pingbot.github_repo, "head_commit", lambda *a, **k: "3272e0c88fb1")

    pingbot._send_repo_apps(1, {"id": 2, "username": "bee", "is_queen": 1})
    reply = last(sent)
    assert "newer commit waiting" in reply      # haven is behind
    assert "up to date" in reply                # old is not
    assert "auto-deploy on" in reply
    markup = [p for _m, p in sent if p.get("reply_markup")][-1]["reply_markup"]
    assert "latest:11" in markup and "autodep:11" in markup


def test_run_button_deploys_the_branch(monkeypatch, sent):
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_REPO", "https://github.com/tajhatAti/b")
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_BRANCH", "arena/01a0ba14-b")
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_NAME", "haven")
    monkeypatch.setattr(telegram_link, "user_for_chat",
                        lambda cid: {"id": 2, "username": "bee", "is_queen": 1})
    monkeypatch.setattr(bot_ops, "find_app", lambda uid, name: None)
    monkeypatch.setattr(pingbot.github_repo, "scan_projects",
                        lambda *a, **k: [TWO_PROJECTS[0]])
    created = {}
    monkeypatch.setattr(
        bot_ops, "create_app_from_repo",
        lambda uid, name, url, **kw: created.update(uid=uid, name=name, url=url, **kw)
        or {"ok": True, "name": name, "job_db_id": 1, "web": "", "commit": "3272e0c88fb1"})

    pingbot.handle_callback(1, "qproj:run")
    assert created["url"] == "https://github.com/tajhatAti/b/tree/arena/01a0ba14-b"
    assert created["name"] == "haven"
    # exactly one runnable thing in the repo, so the entry and its own manifest
    # are named instead of being left to the runner's detection
    assert created["entry"] == "bot.py"
    assert created["deps"] == ["requirements.txt"]
    reply = last(sent)
    assert "deployed and running" in reply
    assert "arena/01a0ba14-b" in reply          # the branch is named in the reply
    assert "3272e0c" in reply                   # and the commit that was built


def test_run_button_refuses_a_non_queen(monkeypatch, sent):
    monkeypatch.setattr(telegram_link, "user_for_chat",
                        lambda cid: {"id": 3, "username": "ann", "is_queen": 0})
    monkeypatch.setattr(bot_ops, "create_app_from_repo",
                        lambda *a, **k: pytest.fail("must not deploy for a non-queen"))
    pingbot.handle_callback(1, "qproj:run")
    assert "queen access" in last(sent).lower()


def test_a_second_deploy_gets_a_free_name(monkeypatch):
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_NAME", "haven")
    taken = {"haven"}
    monkeypatch.setattr(bot_ops, "find_app", lambda uid, name: name in taken)
    assert pingbot._project_app_name({"id": 2}) == "haven-2"


def test_readme_is_sent_as_plain_text(monkeypatch, sent):
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_REPO", "https://github.com/o/r")
    monkeypatch.setattr(pingbot, "QUEEN_PROJECTS_BRANCH", "br")
    monkeypatch.setattr(pingbot.requests, "get",
                        lambda *a, **k: Resp(200, None, text="# Haven\n\nA *real* README."))
    pingbot._send_project_readme(1)
    method, params = sent[-1]
    assert method == "sendMessage"
    assert "parse_mode" not in params        # Markdown we do not control
    assert "A *real* README." in params["text"]


# --------------------------------------------------------------------------
# branches: what the bot says and what the runner clones
# --------------------------------------------------------------------------
def test_branch_is_read_out_of_a_github_url():
    assert pingbot._repo_branch_of("https://github.com/o/r/tree/dev") == "dev"
    # Slashes belong to the branch until git says otherwise — see the runner's
    # _branch_candidates, which shortens the guess only on a real failure.
    assert pingbot._repo_branch_of(
        "https://github.com/o/r/tree/arena/01a0ba14-b") == "arena/01a0ba14-b"
    assert pingbot._repo_branch_of("https://github.com/o/r#dev") == "dev"
    assert pingbot._repo_branch_of("https://github.com/o/r") == ""


def test_import_passes_the_branch_through(monkeypatch, sent):
    monkeypatch.setattr(bot_ops, "find_app", lambda uid, name: None)
    monkeypatch.setattr(pingbot.github_repo, "scan_projects", lambda *a, **k: [])
    created = {}
    monkeypatch.setattr(
        bot_ops, "create_app_from_repo",
        lambda uid, name, url, **kw: created.update(name=name, url=url, **kw)
        or {"ok": True, "name": name, "job_db_id": 1, "web": ""})
    pingbot.cmd_import(1, {"id": 2, "username": "bee"},
                       "https://github.com/tajhatAti/b/tree/arena/01a0ba14-b haven")
    assert created["url"] == "https://github.com/tajhatAti/b/tree/arena/01a0ba14-b"
    assert created["name"] == "haven"


def test_runner_clone_keeps_the_branch():
    """The runner used to match /tree/<branch> and then THROW THE BRANCH AWAY,
    so a project living off main deployed the wrong code with no error."""
    runner_app = _runner_app()
    cases = {
        "https://github.com/o/r": ("https://github.com/o/r.git", ""),
        "https://github.com/o/r.git": ("https://github.com/o/r.git", ""),
        "https://github.com/o/r/": ("https://github.com/o/r.git", ""),
        "https://github.com/o/r/tree/dev": ("https://github.com/o/r.git", "dev"),
        "https://github.com/o/r/tree/arena/01a0ba14-b":
            ("https://github.com/o/r.git", "arena/01a0ba14-b"),
        # A folder view keeps the whole remainder; the retry loop below is what
        # decides how much of it was the branch.
        "https://github.com/o/r/tree/dev/app/sub":
            ("https://github.com/o/r.git", "dev/app/sub"),
        "https://github.com/o/r/blob/dev/main.py":
            ("https://github.com/o/r.git", "dev/main.py"),
        "https://github.com/o/r#dev": ("https://github.com/o/r.git", "dev"),
        "https://github.com/o/r/settings": ("https://github.com/o/r.git", ""),
    }
    for url, expected in cases.items():
        assert runner_app._repo_clone_target(url) == expected, url

    # Longest reading first, then shorter, and [""] when no branch was asked for.
    assert runner_app._branch_candidates("arena/01a0ba14-b") == ["arena/01a0ba14-b", "arena"]
    assert runner_app._branch_candidates("dev/app/sub") == ["dev/app/sub", "dev/app", "dev"]
    assert runner_app._branch_candidates("main") == ["main"]
    assert runner_app._branch_candidates("") == [""]


# --------------------------------------------------------------------------
# heavy zip uploads
# --------------------------------------------------------------------------
def test_queen_zip_limits_are_bigger(monkeypatch):
    monkeypatch.setattr(bot_ops, "is_queen", lambda uid: False)
    normal = bot_ops.zip_limits_for(4)
    monkeypatch.setattr(bot_ops, "is_queen", lambda uid: True)
    royal = bot_ops.zip_limits_for(4)
    assert normal == {"zip_max_mb": bot_ops.ZIP_MAX_MB,
                      "zip_max_files": bot_ops.ZIP_MAX_FILES}
    assert royal["zip_max_mb"] > normal["zip_max_mb"]
    assert royal["zip_max_files"] > normal["zip_max_files"]


def test_a_zip_deploy_sends_the_limits_for_that_account(monkeypatch):
    body = {}

    class Resp201:
        status_code = 201
        placed_on = "https://runner.example"

        def json(self):
            return {"id": "rid-1", "status": "running", "language": "python"}

    def call(method, path, payload=None, worker=None):
        body.update(payload or {})
        return Resp201()

    monkeypatch.setattr(bot_ops.runner_client, "_runner_http", call)
    monkeypatch.setattr(bot_ops, "find_app", lambda uid, name: None)
    monkeypatch.setattr(bot_ops, "_effective_job_limit", lambda uid: 10)
    monkeypatch.setattr(bot_ops, "active_count", lambda uid: 0)
    monkeypatch.setattr(bot_ops, "is_queen", lambda uid: True)
    monkeypatch.setattr(bot_ops, "_mem_limit_for", lambda uid: 0)
    monkeypatch.setattr(bot_ops, "get_db_connection",
                        lambda: _NullConn())
    result = bot_ops.create_app_from_zip(4, "proj", b"PK\x03\x04fake")
    assert result.get("ok"), result
    assert body["zip_max_mb"] == bot_ops.QUEEN_ZIP_MAX_MB
    assert body["zip_max_files"] == bot_ops.QUEEN_ZIP_MAX_FILES
    assert body["mem_limit_mb"] == 0            # 👑 also means no memory ceiling


class _NullConn:
    """Stands in for the jobs-table write: this test is about the request body."""

    def execute(self, *a, **k):
        return self

    def commit(self):
        return None

    def close(self):
        return None

    lastrowid = 1

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def test_runner_honours_a_requested_limit_up_to_its_ceiling():
    runner = _runner_app()

    class Req:
        zip_max_mb = 0
        zip_max_files = 0

    assert runner._zip_limits(Req()) == (runner.ZIP_BUNDLE_MAX_BYTES,
                                         runner.ZIP_BUNDLE_MAX_ENTRIES)
    req = Req()
    req.zip_max_mb, req.zip_max_files = 60, 5000
    assert runner._zip_limits(req) == (60 * 1024 * 1024, 5000)
    req.zip_max_mb, req.zip_max_files = 10 ** 6, 10 ** 6
    # An absurd ask is clamped, not honoured: the box is shared.
    assert runner._zip_limits(req) == (runner.ZIP_BUNDLE_CEILING_BYTES,
                                       runner.ZIP_BUNDLE_CEILING_ENTRIES)


def test_a_bundle_is_only_accepted_within_its_limit(tmp_path):
    import base64
    import collections
    import io
    import zipfile
    runner = _runner_app()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("main.py", "print('hi')\n" * 200)
    raw = base64.b64encode(buf.getvalue()).decode()

    log = collections.deque()
    tight = tmp_path / "tight"
    assert runner._extract_zip_bundle(raw, str(tight), log, max_bytes=1024) is False
    assert any("unpacks to over" in line for line in log)

    log.clear()
    roomy = tmp_path / "roomy"
    assert runner._extract_zip_bundle(raw, str(roomy), log,
                                      max_bytes=1024 * 1024) is True
    assert (roomy / "main.py").exists()


def test_a_queen_can_send_a_zip_without_a_second_grant(monkeypatch, sent):
    import base64
    import io
    import time as _time
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("main.py", "print('hi')")
    payload = buf.getvalue()

    class File:
        status_code = 200
        content = payload

        def raise_for_status(self):
            return None

    def tg(method, **params):
        if method == "getFile":
            return {"ok": True, "result": {"file_path": "documents/f.zip"}}
        sent.append((method, params))
        return {"ok": True, "result": {"message_id": len(sent)}}

    monkeypatch.setattr(pingbot, "_tg", tg)
    monkeypatch.setattr(pingbot.requests, "get", lambda *a, **k: File())
    monkeypatch.setattr(telegram_link, "user_for_chat",
                        lambda uid: {"id": 2, "username": "bee", "is_queen": 1,
                                     "can_upload_zip": 0})
    uploaded = {}
    monkeypatch.setattr(bot_ops, "create_app_from_zip",
                        lambda uid, name, raw: uploaded.update(uid=uid, name=name, raw=raw)
                        or {"ok": True, "name": name, "job_db_id": 1, "web": ""})

    msg = {"document": {"file_name": "proj.zip", "file_size": len(payload),
                        "file_id": "fid"}, "from": {"id": 2}}
    pending = {"mode": "create", "name": "proj", "user_id": 2, "step": "code",
               "expires": _time.time() + 60}
    pingbot.handle_pending_code(2, msg, pending)
    assert uploaded.get("raw") == payload
    assert any("created and running" in t for t in texts(sent))


def test_a_zip_from_an_ordinary_account_still_needs_approval(monkeypatch, sent):
    monkeypatch.setattr(telegram_link, "user_for_chat",
                        lambda uid: {"id": 3, "username": "ann", "is_queen": 0,
                                     "can_upload_zip": 0})
    monkeypatch.setattr(bot_ops, "create_app_from_zip",
                        lambda *a, **k: pytest.fail("must not deploy"))
    msg = {"document": {"file_name": "proj.zip", "file_size": 100,
                        "file_id": "fid"}, "from": {"id": 3}}
    pending = {"mode": "create", "name": "proj", "user_id": 3, "step": "code",
               "expires": 0}
    pingbot.handle_pending_code(3, msg, pending)
    assert "allowzip" in last(sent)


def test_the_reported_production_message_is_translated():
    """The exact reply a user saw: a raw urllib3 wrapper around "Read timed out"."""
    exc = pingbot.requests.exceptions.ReadTimeout(
        "HTTPSConnectionPool(host='ahadorg.onrender.com', port=443): "
        "Read timed out. (read timeout=8)")
    reply = pingbot._ping_error_text("ahadorg.onrender.com", exc)
    assert "didn't answer within" in reply
    assert "HTTPSConnectionPool" not in reply and "port=443" not in reply


def test_wrapped_connection_errors_keep_only_the_fact():
    cases = [
        ("HTTPSConnectionPool(host='x', port=443): Max retries exceeded with url: / "
         "(Caused by SSLError(SSLZeroReturnError(6, 'TLS/SSL connection has been "
         "closed (EOF) (_ssl.c:992)')))", "secure connection"),
        ("HTTPSConnectionPool(host='y', port=443): Max retries exceeded with url: / "
         "(Caused by NewConnectionError('<urllib3.connection.HTTPSConnection object>: "
         "Failed to establish a new connection: [Errno 111] Connection refused'))",
         "refused the connection"),
    ]
    for text, expect in cases:
        reply = pingbot._ping_error_text(
            "host", pingbot.requests.exceptions.ConnectionError(text))
        assert expect in reply, reply
        for noise in ("HTTPSConnectionPool", "Max retries exceeded", "_ssl.c",
                      "urllib3.connection"):
            assert noise not in reply, (noise, reply)


# --------------------------------------------------------------------------
# 👑 its own interface inside Telegram (buttons, panel, /limits)
# --------------------------------------------------------------------------
def _buttons(sent):
    """Every button label/callback on the last message the bot sent."""
    for method, params in reversed(sent):
        if method != "sendMessage":
            continue
        markup = params.get("reply_markup")
        if not markup:
            return []
        kb = json.loads(markup) if isinstance(markup, str) else markup
        return [str(b.get("callback_data") or b.get("text") or "")
                for row in kb.get("inline_keyboard", []) for b in row]
    return []


def test_queens_get_their_own_keyboard(monkeypatch):
    monkeypatch.setattr(pingbot, "SITE_BASE", "https://site.example")
    plain = pingbot._main_kb({"id": 1, "username": "ann", "is_queen": 0})
    royal = pingbot._main_kb({"id": 2, "username": "bee", "is_queen": 1})
    plain_cb = [b.get("callback_data") for row in plain["inline_keyboard"] for b in row]
    royal_cb = [b.get("callback_data") for row in royal["inline_keyboard"] for b in row]
    assert plain_cb == [None]            # everybody else: just the launch button
    assert "queen:menu" in royal_cb and "qproj:list" in royal_cb
    assert any(b.get("web_app") or b.get("url")
               for row in royal["inline_keyboard"] for b in row)


def test_queen_panel_quotes_the_limits_the_site_enforces(monkeypatch):
    monkeypatch.setattr(bot_ops, "account_privileges",
                        lambda uid: {"is_queen": True, "job_limit": 12,
                                     "mem_limit_mb": 0, "zip_max_mb": 60,
                                     "zip_max_files": 5000})
    monkeypatch.setattr(bot_ops, "active_count", lambda uid: 3)
    text = pingbot._queen_panel_text({"id": 7, "username": "bee"})
    assert "3/12" in text                # the same two numbers the cap uses
    assert "no ceiling" in text          # mem_limit_mb 0 means unlimited
    assert "60MB" in text and "5000 files" in text
    for needle in ("/projects", "/import", "/code", "BOT_TOKEN", "/logs"):
        assert needle in text, needle


def test_cmd_limits_is_the_panel_for_a_queen_and_the_ceiling_for_everyone_else(monkeypatch, sent):
    monkeypatch.setattr(bot_ops, "active_count", lambda uid: 1)
    monkeypatch.setattr(bot_ops, "account_privileges",
                        lambda uid: {"is_queen": False, "job_limit": 3,
                                     "mem_limit_mb": 512, "zip_max_mb": 5,
                                     "zip_max_files": 500})
    pingbot.cmd_limits(1, {"id": 4, "username": "ann", "is_queen": 0})
    plain = last(sent)
    assert "1/3" in plain and "512MB" in plain
    assert "/queen" in plain             # how to get more, said once

    sent.clear()
    monkeypatch.setattr(bot_ops, "account_privileges",
                        lambda uid: {"is_queen": True, "job_limit": 12,
                                     "mem_limit_mb": 0, "zip_max_mb": 60,
                                     "zip_max_files": 5000})
    pingbot.cmd_limits(2, {"id": 5, "username": "bee", "is_queen": 1})
    assert last(sent).startswith("👑 *Queen panel*")
    assert "qproj:run" in _buttons(sent)


def test_queen_buttons_reach_the_queen_screens(monkeypatch, sent):
    calls = []
    monkeypatch.setattr(pingbot, "_queen_panel_text",
                        lambda u: calls.append("panel") or "👑 panel")
    monkeypatch.setattr(pingbot, "cmd_projects",
                        lambda c, u, arg="": calls.append("projects"))
    monkeypatch.setattr(pingbot, "_deploy_queen_project",
                        lambda c, u, name="": calls.append("deploy"))
    monkeypatch.setattr(pingbot, "_send_project_readme", lambda c: calls.append("readme"))
    monkeypatch.setattr(pingbot, "cmd_apps", lambda c, u: calls.append("apps"))
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat",
                        lambda cid: {"id": 9, "username": "bee", "is_queen": 1})
    for data, expect in (("queen:menu", "panel"), ("qproj:list", "projects"),
                         ("qproj:run", "deploy"), ("qproj:readme", "readme"),
                         ("queen:apps", "apps")):
        calls.clear()
        pingbot.handle_callback(9, data)
        assert calls == [expect], (data, calls)


def test_queen_buttons_refuse_someone_without_the_flag(monkeypatch, sent):
    """callback_data is attacker-supplied: a pressed button proves nothing."""
    reached = []
    monkeypatch.setattr(pingbot, "_deploy_queen_project",
                        lambda *a, **k: reached.append("deploy"))
    monkeypatch.setattr(pingbot, "cmd_projects", lambda *a, **k: reached.append("projects"))
    monkeypatch.setattr(pingbot, "_send_project_readme", lambda *a, **k: reached.append("readme"))
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat",
                        lambda cid: {"id": 3, "username": "ann", "is_queen": 0})
    for data in ("queen:menu", "qproj:list", "qproj:run", "qproj:readme"):
        pingbot.handle_callback(3, data)
        assert "queen access" in last(sent).lower()
    assert reached == []


def test_a_queen_who_types_queen_sees_their_panel(monkeypatch, sent):
    monkeypatch.setattr(bot_ops, "account_privileges",
                        lambda uid: {"is_queen": True, "job_limit": 12,
                                     "mem_limit_mb": 0, "zip_max_mb": 60,
                                     "zip_max_files": 5000})
    monkeypatch.setattr(bot_ops, "active_count", lambda uid: 0)
    monkeypatch.setattr(pingbot, "_is_admin", lambda *a, **k: False)
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat",
                        lambda cid: {"id": 5, "username": "bee", "is_queen": 1})
    pingbot.cmd_queen(5, 5, "")
    assert last(sent).startswith("👑 *Queen panel*")

    sent.clear()
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat",
                        lambda cid: {"id": 6, "username": "ann", "is_queen": 0})
    pingbot.cmd_queen(6, 6, "")
    assert texts(sent) == []             # still silent for everybody else


# --------------------------------------------------------------------------
# "❌ Unsupported language: . Available: bash, c, ..." on a 👑 GitHub import
# --------------------------------------------------------------------------
def _job_start(monkeypatch, **fields):
    """Call the runner's /internal/jobs handler directly, no HTTP server.

    Returns (status_code, detail). An accepted request would go on to spawn a
    process, so every caller here fails deliberately after validation.
    """
    from fastapi import HTTPException
    runner_app = _runner_app()
    monkeypatch.setattr(runner_app, "SECRET", "s")
    monkeypatch.setattr(runner_app, "_admission",
                        lambda: {"admit": True, "used_mb": 0, "safe_mb": 4096})
    req = runner_app.JobStartRequest(**fields)
    try:
        runner_app.job_start(req, authorization="Bearer s")
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)
    return 201, ""


def test_runner_no_longer_rejects_a_repo_it_has_not_cloned_yet(monkeypatch):
    """The empty name in "Unsupported language: ." was the tell: the check ran
    BEFORE the clone, and the clone is what detects the language."""
    monkeypatch.setattr(_runner_app(), "_clone_repo", lambda *a, **k: False)
    status, detail = _job_start(monkeypatch, language="", code="", name="q",
                                repo_url="https://github.com/o/r")
    assert status == 400
    assert "Unsupported language" not in detail
    assert "clone failed" in detail.lower()      # validation passed, clone ran


def test_runner_still_says_no_to_a_language_it_cannot_run(monkeypatch):
    status, detail = _job_start(monkeypatch, language="pyton", code="print(1)", name="x")
    assert status == 400 and "Unsupported language: pyton" in detail

    # no language AND nothing to detect one from: say what is missing
    status, detail = _job_start(monkeypatch, language="", code="print(1)", name="x")
    assert status == 400 and "No language given" in detail


def test_runner_folds_common_language_spellings():
    runner_app = _runner_app()
    for said, meant in (("py", "python"), ("node", "javascript"),
                        ("NodeJS", "javascript"), ("ts", "typescript"),
                        ("shell", "bash"), ("golang", "go"), ("AUTO", ""),
                        ("", ""), ("python", "python")):
        assert runner_app._normalize_lang(said) == meant, said


def test_repo_import_names_a_language_the_runner_understands(monkeypatch):
    """The site sent language:"" for a repo import, which an already-deployed
    runner rejects before it ever clones — so this names one it accepts, and the
    runner replaces it with what the checkout actually is."""
    body = {}

    class Resp201:
        status_code = 201
        placed_on = "https://runner.example"

        def json(self):
            return {"id": "rid-9", "status": "running", "language": "javascript"}

    def call(method, path, payload=None, worker=None):
        body.update(payload or {})
        return Resp201()

    monkeypatch.setattr(bot_ops.runner_client, "_runner_http", call)
    monkeypatch.setattr(bot_ops.runner_client, "fleet_jobs", lambda: set())
    monkeypatch.setattr(bot_ops, "_effective_job_limit", lambda uid: 10)
    monkeypatch.setattr(bot_ops, "_mem_limit_for", lambda uid: 0)
    monkeypatch.setattr(bot_ops, "get_db_connection", lambda: _NullConn())
    res = bot_ops.create_app_from_repo(8, "shop", "https://github.com/o/r")
    assert res.get("ok"), res
    assert body["language"] == "python"
    assert body["repo_url"] == "https://github.com/o/r"


def test_connecting_a_queen_opens_on_the_queen_screen(monkeypatch, sent):
    """The first screen a newly linked 👑 sees — it used to be everybody else's.

    user_for_chat returns None until the code is redeemed and the row after it,
    exactly as the real link does.
    """
    monkeypatch.setattr(pingbot, "SITE_BASE", "https://site.example")
    state = {"calls": 0}

    def for_chat(cid):
        state["calls"] += 1
        return None if state["calls"] == 1 else {"id": 11, "username": "bee", "is_queen": 1}

    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat", for_chat)
    monkeypatch.setattr(pingbot.telegram_link, "redeem_code",
                        lambda code, cid, name="": {"ok": True, "username": "bee"})
    pingbot.handle_link(11, "/link 123456", "bee")
    text = last(sent)
    assert text.startswith("✅ Connected to *bee*.")
    assert "👑" in text and "/projects" in text
    assert "queen:menu" in _buttons(sent)
    assert any("Open dashboard" in b for b in _buttons(sent))


# --------------------------------------------------------------------------
# 🩺 admin health: the panel that answers "why doesn't anything work?"
# --------------------------------------------------------------------------
def _fake_tg(sent, webhook=None):
    """A Telegram API that records calls and answers getWebhookInfo on demand."""
    def tg(method, **params):
        sent.append((method, params))
        if method == "getWebhookInfo":
            return {"ok": True, "result": webhook if webhook is not None else {}}
        return {"ok": True, "result": {"message_id": len(sent)}}
    return tg


def _patch_health_sources(monkeypatch):
    monkeypatch.setattr(pingbot.runner_client, "runner_pool", lambda: ["https://r.example"])
    monkeypatch.setattr(pingbot.runner_client, "worker_health",
                        lambda refresh=False, max_age_s=None: {
                            "https://r.example": {"online": True, "jobs": 2, "free": 3,
                                                  "free_mb": 300.0, "total_mb": 512.0,
                                                  "full": False}})
    monkeypatch.setattr(pingbot.telegram_link, "admin_overview_stats",
                        lambda: {"jobs_total": 5, "jobs_deployed": 4, "users": 2,
                                 "tg_linked": 1, "admins": 1, "zip_allowed": 0,
                                 "suspended": 0})
    # no project repo configured → the panel must not go looking for one
    monkeypatch.setattr(pingbot, "_queen_repo_parts", lambda: ("", ""))


def test_admin_health_names_a_webhook_that_silently_drops_buttons(monkeypatch):
    """The one misconfiguration that looks exactly like "the buttons are broken":
    a webhook registered without callback_query receives typed commands and
    throws away every single button press. The panel has to say so in words."""
    sent = []
    monkeypatch.setattr(pingbot, "_tg", _fake_tg(sent, {
        "url": "https://ahadrunspace.onrender.com/telegram/webhook",
        "pending_update_count": 3,
        "allowed_updates": ["message"],
        "last_error_message": "",
    }))
    _patch_health_sources(monkeypatch)

    text = pingbot._admin_health_text()
    assert "callback_query" in text
    assert "dropping every button press" in text
    assert "Re-register webhook" in text
    # the rest of the machinery is reported from itself, not from intent
    assert "https://r.example" in text and "2 job(s)" in text
    assert "Recovery runs every" in text
    assert "How a deploy works now" in text

    data = [b["callback_data"]
            for row in pingbot._admin_health_kb()["inline_keyboard"] for b in row]
    for needle in ("admin:fixwebhook", "admin:autodepnow", "admin:limitflow", "admin:health"):
        assert needle in data, needle
    assert all(len(d) <= 64 for d in data)      # Telegram's hard limit


def test_admin_health_says_when_the_service_is_polling(monkeypatch):
    sent = []
    monkeypatch.setattr(pingbot, "_tg", _fake_tg(sent, {}))
    _patch_health_sources(monkeypatch)
    text = pingbot._admin_health_text()
    assert "No webhook registered" in text and "long-polling" in text
    # ...and the repair button explains a mode change is a restart, not a tap
    assert "SITE_BASE" not in text or "restart" in text


def test_fixwebhook_does_not_fight_a_running_poller(monkeypatch, sent):
    """Registering a webhook over a live poller starts a fight the poller loses
    silently (getUpdates 409 → it deletes the webhook once → then just logs).
    With no webhook registered the button must explain instead of acting."""
    monkeypatch.setattr(pingbot, "_tg", _fake_tg(sent, {}))
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat",
                        lambda cid: {"id": 1, "username": "root", "is_admin": 1})
    registered = []
    monkeypatch.setattr(pingbot, "enable_webhook",
                        lambda: registered.append(1) or True)
    pingbot.handle_admin_callback(1, 1, "fixwebhook", "", None)
    assert not registered
    reply = last(sent)
    assert "restart" in reply and "SITE_BASE" in reply


def test_health_button_is_admin_only(monkeypatch, sent):
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat", lambda cid: None)
    pingbot.handle_admin_callback(1, 1, "health", "", None)
    assert "Admin only" in last(sent)


# --------------------------------------------------------------------------
# the buttons on a repo app: update it, or let it follow its branch
# --------------------------------------------------------------------------
def test_latest_button_with_no_ref_lists_the_repo_apps(monkeypatch, sent):
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat",
                        lambda cid: {"id": 2, "username": "bee"})
    monkeypatch.setattr(bot_ops, "list_apps", lambda uid: [
        {"id": 31, "name": "haven", "repo_url": "https://github.com/o/r", "repo_commit": "a"},
        {"id": 32, "name": "web", "repo_url": "https://github.com/o/r", "repo_commit": "b"}])
    pingbot.handle_callback(1, "latest:")
    assert "Which app should I update" in last(sent)
    markup = [p for _m, p in sent if p.get("reply_markup")][-1]["reply_markup"]
    assert "latest:31" in markup and "latest:32" in markup


def test_autodeploy_button_is_queen_only(monkeypatch, sent):
    """Advanced repo features stay 👑: a normal account is told what it is
    missing and what it can still do, rather than getting the switch."""
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat",
                        lambda cid: {"id": 3, "username": "ann", "is_queen": 0})
    monkeypatch.setattr(bot_ops, "find_app", lambda uid, ref: {
        "id": 31, "name": "haven", "repo_url": "https://github.com/o/r", "auto_deploy": 0})
    monkeypatch.setattr(bot_ops, "set_auto_deploy",
                        lambda *a, **k: pytest.fail("must not toggle for a non-queen"))
    pingbot.handle_callback(1, "autodep:31")
    reply = last(sent)
    assert "queen access" in reply.lower()
    assert "/latest" in reply                    # what they CAN still do


def test_a_button_tap_with_no_message_is_answered_not_crashed(monkeypatch):
    """Telegram keeps delivering taps for a message it has already dropped from
    the chat, with no `message` object at all. Reading
    cb["message"]["chat"]["id"] straight through raised a TypeError, the tap was
    never answered, and the button looked dead — with nothing in the log but a
    stack trace. The person who tapped is always known, so fall back to them."""
    answered, events = [], []
    monkeypatch.setattr(pingbot, "_tg",
                        lambda method, **p: answered.append(method) or {"ok": True, "result": {}})
    monkeypatch.setattr(pingbot.bot_analytics, "record", lambda **e: events.append(e))
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat", lambda cid: None)
    monkeypatch.setattr(pingbot.telegram_admin_ext, "is_banned", lambda uid: False)

    pingbot.handle_update({"update_id": 9, "callback_query": {
        "id": "cb-1", "from": {"id": 77, "first_name": "Ada"}, "data": "admin:health"}})

    assert "answerCallbackQuery" in answered
    assert events and events[0]["event_type"] == "callback"
    assert events[0]["chat_id"] == 77            # fell back to whoever tapped


def test_a_button_from_an_unlinked_chat_says_why(monkeypatch):
    """A job button pressed from a chat with no linked account used to be dropped
    in silence (outcome="refused", nothing sent). Silence is indistinguishable
    from a broken button, so the tap is answered AND the reason is stated."""
    answered, sent, events = [], [], []
    monkeypatch.setattr(pingbot, "_tg",
                        lambda method, **p: (answered.append(method),
                                             sent.append(p.get("text") or ""),
                                             {"ok": True, "result": {}})[-1])
    monkeypatch.setattr(pingbot.bot_analytics, "record", lambda **e: events.append(e))
    monkeypatch.setattr(pingbot.telegram_link, "user_for_chat", lambda cid: None)
    monkeypatch.setattr(pingbot.telegram_admin_ext, "is_banned", lambda uid: False)
    monkeypatch.setattr(pingbot, "cmd_logs",
                        lambda *a, **k: pytest.fail("must not run for an unlinked chat"))

    pingbot.handle_update({"update_id": 10, "callback_query": {
        "id": "cb-2", "from": {"id": 88}, "data": "logs:myapp",
        "message": {"chat": {"id": 88}, "message_id": 5}}})

    assert "answerCallbackQuery" in answered
    assert any("/link" in t for t in sent), sent
    assert events and events[0]["outcome"] == "refused"
