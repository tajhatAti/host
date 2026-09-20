#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

export PYTHONPATH=.
export DATA_DIR="${DATA_DIR:-$(mktemp -d)}"
export DB_PATH="${DB_PATH:-$(mktemp -d)/codenest-test.db}"
export JOB_SECRETS_KEY="${JOB_SECRETS_KEY:-core-test-secret-not-for-production}"
PYTHON_BIN="${PYTHON_BIN:-python}"

"$PYTHON_BIN" -m py_compile \
  app.py database.py routes/*.py services/*.py runner/app.py runner/terminal.py

"$PYTHON_BIN" -m pytest -q \
  tests/test_telegram_job_detection.py \
  tests/test_bot_templates.py \
  tests/test_runner_registry.py \
  tests/test_admin_abuse_controls.py \
  tests/test_bot_analytics.py \
  tests/test_bot_dispatch_analytics.py \
  tests/test_job_url_routes.py \
  tests/test_bot_list_fast.py \
  tests/test_secrets_plain.py \
  tests/test_job_recovery.py \
  tests/test_bot_ops_multirunner.py \
  tests/test_store.py \
  tests/test_overview_analytics.py

# Script-style suites: they drive the bot's real dispatch path against their own
# throwaway database and exit non-zero on failure, so they are run directly
# rather than collected by pytest.
"$PYTHON_BIN" tests/test_queen_flag.py

npm run check:js
npm run test:js
npm audit --audit-level=high

"$PYTHON_BIN" tests/validate_postgres_sql.py
git diff --check
