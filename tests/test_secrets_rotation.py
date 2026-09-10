from services import secrets_store


def test_adding_job_key_can_read_and_rewrap_legacy_runner_cipher(monkeypatch):
    monkeypatch.delenv("JOB_SECRETS_KEY", raising=False)
    monkeypatch.setenv("RUNNER_SERVICE_SECRET", "legacy-runner-secret-material")
    legacy = secrets_store.pack_env({"BOT_TOKEN": "123:example-token", "AI_API_KEY": "private"})
    assert legacy.startswith(secrets_store.PREFIX)

    monkeypatch.setenv("JOB_SECRETS_KEY", "new-dedicated-job-secret")
    values, key_index = secrets_store._unpack_with_key_index(legacy)
    assert values["BOT_TOKEN"] == "123:example-token"
    assert key_index == 1  # recovered through legacy RUNNER_SERVICE_SECRET

    rewrapped = secrets_store.pack_env(values)
    values2, key_index2 = secrets_store._unpack_with_key_index(rewrapped)
    assert values2 == values
    assert key_index2 == 0  # now protected by JOB_SECRETS_KEY
