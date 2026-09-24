
# Script-style standalone tests (run via `python tests/foo.py`) execute their
# body at import time and must not be collected by pytest — they break the suite.
_SCRIPT_STYLE = {
    "test_admin_batch.py",
    "test_admin_dashboard.py",
    "test_admin_stealth.py",
    "test_auth_abuse_system.py",
    "test_badhash_evidence.py",
    "test_badhash_verdict.py",
    "test_bot_critical.py",
    "test_bot_ops.py",
    "test_embedded_single_service.py",
    "test_env_and_stats.py",
    "test_job_data_persistence.py",
    "test_legacy_db_migration.py",
    "test_memory_admission.py",
    "test_miniapp_auth.py",
    "test_miniapp_opens.py",
    "test_multi_worker.py",
    "test_pg_returning_id.py",
    "test_pool_resilience.py",
    "test_routing.py",
    "test_runner_capacity.py",
    "test_job_liveness.py",
    "test_runner_standalone_boot.py",
    "test_runspace_fixes.py",
    "test_security_batch.py",
    "test_signature_field.py",
    "test_snapshot_routes.py",
    "test_sqlite_flow.py",
    "test_system_tools.py",
    "test_tab_status_sync.py",
    "test_telegram_link.py",
    "test_token_mismatch.py",
    "test_web_batch.py",
    "test_repo_deps_and_entry.py",
    "test_all_routes.py",
    "test_queen_flag.py"
}


def pytest_ignore_collect(collection_path, config):
    try:
        name = collection_path.name
    except Exception:
        return None
    if name in _SCRIPT_STYLE:
        return True
    return None
