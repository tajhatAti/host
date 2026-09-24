"""Bots come back on their own, and never twice.

Three rules, in the order they matter to an owner:

1. A bot marked desired_state='running' that the runner no longer has is
   re-created from the database — code, env (plain JSON now, so the BOT_TOKEN is
   always readable), and the last workspace snapshot.
2. A worker that DID NOT ANSWER is not evidence that its jobs are gone. Treating
   silence as absence re-created every bot on a sleeping runner, which puts two
   pollers on one Telegram token: they fight, and the owner's bot dies anyway.
3. A recovered bot keeps its 👑 (unlimited memory) flag — recovery is a fresh
   create, and a create that forgets mem_limit_mb quietly re-applies the default
   ceiling.

Plus the part that makes a runner restart a non-event: recover_once() runs on an
interval (start_reconciler), not only once at site startup.
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "recovery.db"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

from services import github_repo, job_recovery, runner_client, secrets_store, snapshots  # noqa: E402


class Response:
    status_code = 201
    placed_on = "https://runner-two.example"

    def json(self):
        return {"id": "new-runner-id"}


class Health:
    status_code = 200

    def json(self):
        return {"status": "ok"}


def _row(**over):
    row = {"id": 9, "user_id": 4, "name": "support", "language": "python",
           "code": "print('bot')", "env": secrets_store.pack_env({"BOT_TOKEN": "123:saved-token"}),
           "runner_job_id": "old-id", "worker_url": "embedded",
           "telegram_bot_detected": 1}
    row.update(over)
    return row


def test_missing_desired_bot_is_recreated_with_saved_token(monkeypatch):
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [_row()])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})
    sent = {}

    def call(method, path, body=None, worker=None):
        if path == "/health":
            return Health()                     # the worker answers: its empty job list is real
        sent.update(method=method, path=path, body=body, worker=worker)
        return Response()

    monkeypatch.setattr(runner_client, "_runner_http", call)
    remembered = {}
    monkeypatch.setattr(job_recovery, "_remember",
                        lambda jid, rid, worker: remembered.update(job=jid, runner=rid, worker=worker))
    monkeypatch.setattr(snapshots, "restore_snapshot", lambda *a, **k: {"restored": 0})

    assert job_recovery.recover_once() == 0
    assert sent["path"] == "/internal/jobs"
    assert sent["body"]["env"]["BOT_TOKEN"] == "123:saved-token"
    assert remembered == {"job": 9, "runner": "new-runner-id", "worker": "https://runner-two.example"}


def test_recovery_never_crash_loops_telegram_bot_without_token(monkeypatch):
    """The worker is reachable, so this is genuinely a bot with no token: it must
    be reported, not started into a crash-loop that looks like 'processing'."""
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [
        _row(id=10, name="broken", env=None, runner_job_id="old", worker_url=None)])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})

    def call(method, path, body=None, worker=None):
        if path == "/health":
            return Health()
        raise AssertionError("must not start a tokenless Telegram bot")

    monkeypatch.setattr(runner_client, "_runner_http", call)
    assert job_recovery.recover_once() == 1


def test_a_worker_that_does_not_answer_never_causes_a_duplicate(monkeypatch):
    """THE rule that makes an interval reconciler safe to run at all.

    Before this, an empty fleet list was taken as proof the jobs were gone. On a
    runner that is asleep or mid-boot that is false, and the "recovery" created a
    second copy of every bot — two pollers on one token, which is exactly how an
    owner's working bot ends up dead."""
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [
        _row(id=11, runner_job_id="alive-but-unprobed", worker_url="https://sleeping.example")])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})

    def call(method, path, body=None, worker=None):
        if path == "/health":
            raise TimeoutError("runner is asleep")
        raise AssertionError("must not recreate a job on a worker that never answered")

    monkeypatch.setattr(runner_client, "_runner_http", call)
    assert job_recovery.recover_once() == 0      # deferred, not failed
    monkeypatch.setattr(job_recovery, "_remember", lambda *a: (_ for _ in ()).throw(
        AssertionError("nothing should have been remembered")))

    # A 502/503 from a container still booting is the same case: not an answer.
    class Booting:
        status_code = 503

        def json(self):
            return {}

    monkeypatch.setattr(runner_client, "_runner_http",
                        lambda method, path, body=None, worker=None: Booting())
    assert job_recovery.recover_once() == 0


def test_recovered_bot_keeps_its_queen_flag(monkeypatch):
    """Recovery is a fresh create, so it has to carry 👑 with it."""
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [_row(id=12, user_id=77)])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})
    monkeypatch.setattr(job_recovery, "_remember", lambda *a: None)
    monkeypatch.setattr(snapshots, "restore_snapshot", lambda *a, **k: {"restored": 0})
    seen = {}

    def call(method, path, body=None, worker=None):
        if path == "/health":
            return Health()
        seen.update(body)
        return Response()

    monkeypatch.setattr(runner_client, "_runner_http", call)
    from services import bot_ops
    monkeypatch.setattr(bot_ops, "mem_limit_for", lambda user_id: 0 if user_id == 77 else None)

    assert job_recovery.recover_once() == 0
    assert seen["mem_limit_mb"] == 0, seen


def test_repo_bot_is_recovered_by_recloning_not_empty_code(monkeypatch):
    """THE production bug: every restart logged 'Code is empty' for repo apps.

    A GitHub import stores repo_url and leaves code=''. Recovery used to POST
    only the empty code, the runner correctly refused with 400, and the next
    sweep did the same thing forever. The bot that "used to work" never came
    back until someone pressed Restart by hand (which goes through
    update_from_repo and does send the URL).
    """
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [
        _row(id=41, name="haven", code="",
             repo_url="https://github.com/tajhatAti/b/tree/arena/01a0ba14-b",
             repo_entry="bot.py", telegram_bot_detected=0)])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})
    monkeypatch.setattr(job_recovery, "_remember", lambda *a: None)
    monkeypatch.setattr(snapshots, "restore_snapshot", lambda *a, **k: {"restored": 0})
    seen = {}

    def call(method, path, body=None, worker=None):
        if path == "/health":
            return Health()
        if path == "/internal/jobs":
            seen.update(body or {})
            return Response()
        return Response()

    monkeypatch.setattr(runner_client, "_runner_http", call)
    from services import bot_ops
    monkeypatch.setattr(bot_ops, "mem_limit_for", lambda uid: None)

    assert job_recovery.recover_once() == 0
    assert seen.get("repo_url", "").startswith("https://github.com/tajhatAti/b")
    assert seen.get("entry") == "bot.py"
    assert (seen.get("code") or "") == ""
    assert seen.get("env", {}).get("BOT_TOKEN") == "123:saved-token"


def test_empty_code_without_repo_is_skipped_not_spammed(monkeypatch):
    """A row with nothing to run must not hit the runner every five minutes."""
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [
        _row(id=99, code="", repo_url="", telegram_bot_detected=0,
             env=secrets_store.pack_env({}))])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})
    hits = []

    def call(method, path, body=None, worker=None):
        if path == "/health":
            return Health()
        hits.append(path)
        raise AssertionError("must not POST an empty job")

    monkeypatch.setattr(runner_client, "_runner_http", call)
    assert job_recovery.recover_once() == 1
    assert hits == []


def test_reconciler_is_started_once_and_can_be_switched_off(monkeypatch):
    started = []
    monkeypatch.setattr(job_recovery.threading, "Thread",
                        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr(job_recovery, "_reconciler_started", False)
    monkeypatch.setattr(job_recovery, "RECOVERY_INTERVAL_S", 300)
    job_recovery.start_reconciler()
    job_recovery.start_reconciler()               # idempotent — one thread, not two
    assert len(started) == 1, started
    assert started[0]["daemon"] is True and started[0]["name"] == "job-recovery"

    monkeypatch.setattr(job_recovery, "_reconciler_started", False)
    monkeypatch.setattr(job_recovery, "RECOVERY_INTERVAL_S", 0)
    job_recovery.start_reconciler()
    assert len(started) == 1                      # JOB_RECOVERY_INTERVAL_S=0 means off


# --------------------------------------------------------------------------
# auto-deploy: follow the branch, the way a platform does
# --------------------------------------------------------------------------
def _repo_row(**over):
    row = {"id": 21, "user_id": 4, "name": "haven",
           "repo_url": "https://github.com/tajhatAti/b",
           "repo_entry": "bot.py", "repo_commit": "aaaaaaa1111",
           "worker_url": "embedded", "runner_job_id": "rid-1"}
    row.update(over)
    return row


def test_auto_deploy_sweep_redeploys_only_the_app_whose_commit_moved(monkeypatch):
    """Two apps follow the same branch; only the one that is BEHIND is touched.

    Redeploying both would restart a healthy bot for nothing — and restarting a
    Telegram bot means a gap in service, so "did the commit change?" has to be
    the only trigger.
    """
    from services import bot_ops
    monkeypatch.setattr(job_recovery, "AUTO_DEPLOY_INTERVAL_S", 600)
    monkeypatch.setattr(bot_ops, "auto_deploy_jobs",
                        lambda: [_repo_row(), _repo_row(id=22, name="web", repo_commit="3272e0c88fb1")])
    monkeypatch.setattr(job_recovery, "_auto_deploy_last", 0.0)
    calls = []
    monkeypatch.setattr(bot_ops, "update_from_repo",
                        lambda uid, name, url: calls.append((uid, name, url)) or {"ok": True})
    # one cached lookup per distinct repo, shared by both apps
    monkeypatch.setattr(github_repo, "head_commit",
                        lambda owner, repo, branch="": "3272e0c88fb1")

    out = job_recovery.auto_deploy_sweep(force=True)
    assert out["checked"] == 2 and out["updated"] == 1 and out["unchanged"] == 1, out
    assert calls == [(4, "haven", "https://github.com/tajhatAti/b")], calls


def test_auto_deploy_sweep_treats_a_silent_github_as_no_change(monkeypatch):
    """A rate limit must never look like a new commit.

    Guessing here would redeploy — and therefore restart — every following app
    whenever GitHub stopped answering, which on a shared exit IP is often.
    """
    from services import bot_ops
    monkeypatch.setattr(job_recovery, "AUTO_DEPLOY_INTERVAL_S", 600)
    monkeypatch.setattr(bot_ops, "auto_deploy_jobs", lambda: [_repo_row()])
    monkeypatch.setattr(job_recovery, "_auto_deploy_last", 0.0)
    monkeypatch.setattr(bot_ops, "update_from_repo",
                        lambda *a, **k: pytest.fail("must not redeploy without a commit"))
    monkeypatch.setattr(github_repo, "head_commit", lambda *a, **k: "")

    out = job_recovery.auto_deploy_sweep(force=True)
    assert out["updated"] == 0 and out["unchanged"] == 1, out


def test_auto_deploy_sweep_keeps_going_after_one_app_fails(monkeypatch):
    """One unreachable runner must not stop the rest of the fleet updating."""
    from services import bot_ops
    monkeypatch.setattr(job_recovery, "AUTO_DEPLOY_INTERVAL_S", 600)
    monkeypatch.setattr(bot_ops, "auto_deploy_jobs",
                        lambda: [_repo_row(), _repo_row(id=22, name="web", repo_commit="old")])
    monkeypatch.setattr(job_recovery, "_auto_deploy_last", 0.0)
    done = []

    def update(uid, name, url):
        if name == "haven":
            return {"ok": False, "error": "Runner rejected the update."}
        done.append(name)
        return {"ok": True}

    monkeypatch.setattr(bot_ops, "update_from_repo", update)
    monkeypatch.setattr(github_repo, "head_commit", lambda *a, **k: "3272e0c88fb1")

    out = job_recovery.auto_deploy_sweep(force=True)
    assert out["failed"] == 1 and out["updated"] == 1, out
    assert done == ["web"]
    assert any("haven" in e for e in out["errors"]), out["errors"]


def test_auto_deploy_sweep_can_be_switched_off_and_waits_between_runs(monkeypatch):
    from services import bot_ops
    monkeypatch.setattr(bot_ops, "auto_deploy_jobs",
                        lambda: pytest.fail("must not read jobs when disabled"))
    monkeypatch.setattr(job_recovery, "AUTO_DEPLOY_INTERVAL_S", 0)
    assert job_recovery.auto_deploy_sweep(force=True) == {"disabled": True}

    monkeypatch.setattr(job_recovery, "AUTO_DEPLOY_INTERVAL_S", 600)
    monkeypatch.setattr(job_recovery, "_auto_deploy_last", job_recovery.time.time())
    assert job_recovery.auto_deploy_sweep() == {"waiting": True}


def test_the_reconciler_runs_the_sweep_after_recovery(monkeypatch):
    """Order matters: a runner that just restarted has to get its jobs back
    BEFORE any of them is redeployed, and the sweep keeps its own longer clock
    so it does not run on every pass of the recovery loop."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "services", "job_recovery.py")).read()
    loop = src[src.index("def _reconcile_loop():"):src.index("def start_reconciler():")]
    assert "recover_once()" in loop and "auto_deploy_sweep()" in loop
    assert loop.index("recover_once()") < loop.index("auto_deploy_sweep()")
    st = job_recovery.auto_deploy_status()
    assert set(st) >= {"enabled", "interval_s", "last"}


def test_token_in_source_is_enough_for_recovery(monkeypatch):
    """Telegram-board deploys often have the token IN the file, not in Env.

    Recovery used to skip whenever env lacked BOT_TOKEN even if the source
    already held a real token — the bot that "used to work" stayed down after
    every runner restart. Code-embedded tokens must recover the same way.
    """
    # A realistic short token-shaped string that TOKEN_RE accepts.
    code = (
        "import os\n"
        "TOKEN = '123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw'\n"
        "print('bot starting', TOKEN[:8])\n"
    )
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [
        _row(id=41, name="code-token", code=code, env=None,
             telegram_bot_detected=1, runner_job_id="old", worker_url=None)])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})
    sent = {}

    def call(method, path, body=None, worker=None):
        if path == "/health":
            return Health()
        sent.update(method=method, path=path, body=body, worker=worker)
        return Response()

    monkeypatch.setattr(runner_client, "_runner_http", call)
    monkeypatch.setattr(job_recovery, "_remember", lambda *a, **k: None)
    monkeypatch.setattr(snapshots, "restore_snapshot", lambda *a, **k: {"restored": 0})

    assert job_recovery.recover_once() == 0
    assert sent.get("path") == "/internal/jobs", sent
    assert sent["body"]["env"]["BOT_TOKEN"].startswith("123456789:"), sent["body"]["env"]


def test_token_still_missing_everywhere_is_skipped(monkeypatch):
    """No env token AND no token in source → skip (do not crash-loop)."""
    monkeypatch.setattr(job_recovery, "_wanted_rows", lambda: [
        _row(id=42, name="empty", code="print('hi')", env=None,
             telegram_bot_detected=1)])
    monkeypatch.setattr(runner_client, "fleet_jobs", lambda refresh=True: {})

    def call(method, path, body=None, worker=None):
        if path == "/health":
            return Health()
        raise AssertionError("must not start")

    monkeypatch.setattr(runner_client, "_runner_http", call)
    assert job_recovery.recover_once() == 1
