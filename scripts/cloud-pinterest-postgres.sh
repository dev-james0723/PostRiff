#!/usr/bin/env bash
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Use JCB Linux cloud CI for disposable PostgreSQL.' >&2; exit 64
fi
cd "$(dirname "$0")/.."
pg_bin=/usr/lib/postgresql/16/bin
if [ ! -x "$pg_bin/initdb" ]; then
  sudo -n apt-get -qq update
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
fi
pg_test_home="$(mktemp -d)"
trap 'rm -rf -- "$pg_test_home"' EXIT
env -i PATH="$PATH" HOME="$pg_test_home" CI=true LC_ALL=C PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$PWD/src:$PWD/tests" POSTRIFF_PG_BIN="$pg_bin" POSTRIFF_RESEARCH=0 \
  "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_disposable_postgres.py tests/phase2/postgres_pinterest.py tests/phase2/postgres_browser_session_guard.py
