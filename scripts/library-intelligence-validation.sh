#!/usr/bin/env bash
# Library intelligence (2026-10-08 package): unit tests, disposable PostgreSQL suites first WITHOUT pgvector (honest
# lexical-only degradation) and then WITH pgvector, the web source tests, and adjacent regressions. Cloud Linux only.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Library intelligence validation requires cloud Linux CI.' >&2; exit 64
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/src:$PWD/tests"
echo "CANDIDATE_SHA=$(git rev-parse HEAD 2>/dev/null || echo unknown) TREE=$(git write-tree 2>/dev/null || echo unknown)"
python -m unittest discover -s tests -p 'test_library_intelligence_*.py' -v
if ! command -v pg_config >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq install postgresql
fi
export POSTRIFF_PG_BIN="$(pg_config --bindir)"
sudo -n mkdir -p /var/run/postgresql
sudo -n chmod 1777 /var/run/postgresql
suites=$(ls tests/phase2/postgres_library_intelligence*.py 2>/dev/null | xargs -n1 basename | sed 's/\.py$//' | tr '\n' ' ')
if [ -n "$suites" ]; then
  echo "PG_PHASE=no_vector"
  LIBRARY_PG_PHASE=no_vector python scripts/postriff_pg_suite.py $suites
  major="$(pg_config --version | sed -E 's/^PostgreSQL ([0-9]+).*/\1/')"
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq install "postgresql-${major}-pgvector"
  echo "PG_PHASE=vector (pgvector for PostgreSQL ${major})"
  LIBRARY_PG_PHASE=vector python scripts/postriff_pg_suite.py $suites
fi
# Adjacent PostgreSQL regressions on the same candidate (postgres_library_lifecycle already ran in the caller).
python scripts/postriff_pg_suite.py postgres_agent_runtime postgres_agent_style
# Web source tests (node --test, no browser). All web tests, so adjacent features regress here too.
shopt -s nullglob
web_tests=(web/tests/*.test.cjs web/tests/*.test.mjs)
node --test "${web_tests[@]}"
# Every Python unit test in the repository (fast; no providers, no network).
python -m unittest discover -s tests -p 'test_*.py'
