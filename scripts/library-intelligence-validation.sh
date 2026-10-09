#!/usr/bin/env bash
# Library intelligence (2026-10-08 package): unit tests, disposable PostgreSQL suites first WITHOUT pgvector (honest
# lexical-only degradation) and then WITH pgvector, the web source tests, and adjacent regressions. Cloud Linux only.
# Every stage runs even after an earlier failure, so one run reports everything; the exit code is non-zero if any failed.
set -uo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Library intelligence validation requires cloud Linux CI.' >&2; exit 64
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/src:$PWD/tests"
failed=()
stage() { local name="$1"; shift; echo "STAGE $name"; if "$@"; then echo "STAGE_PASS $name"; else echo "STAGE_FAIL $name"; failed+=("$name"); fi; }
# JCB applies the local working tree as a patch onto the base checkout; the candidate SHA is the receipt's sourceHead.
echo "REMOTE_BASE=$(git rev-parse HEAD 2>/dev/null || echo unknown)"
shopt -s nullglob
# Library lint findings with file:line (the CI lint task prints GitHub annotations without locations). Informational;
# `jcb lint` remains the gate.
if [ -x web/node_modules/.bin/oxlint ]; then
  (cd web && node_modules/.bin/oxlint -f unix src/features/library src/lib/library src/lib/api) || echo "LIBRARY_LINT_FINDINGS_ABOVE"
fi
stage unit python -m unittest discover -s tests -p 'test_library_intelligence_*.py' -v
if ! command -v pg_config >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq install postgresql
fi
export POSTRIFF_PG_BIN="$(pg_config --bindir)"
sudo -n mkdir -p /var/run/postgresql
sudo -n chmod 1777 /var/run/postgresql
suites=""
for path in tests/phase2/postgres_library_intelligence*.py; do suites="$suites $(basename "$path" .py)"; done
if [ -n "$suites" ]; then
  echo "PG_PHASE=no_vector"
  stage pg_no_vector env LIBRARY_PG_PHASE=no_vector python scripts/postriff_pg_suite.py $suites
  major="$(pg_config --version | sed -E 's/^PostgreSQL ([0-9]+).*/\1/')"
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq install "postgresql-${major}-pgvector"
  echo "PG_PHASE=vector (pgvector for PostgreSQL ${major})"
  stage pg_vector env LIBRARY_PG_PHASE=vector python scripts/postriff_pg_suite.py $suites
fi
# Adjacent PostgreSQL regressions on the same candidate (postgres_library_lifecycle already ran in the caller).
stage pg_adjacent python scripts/postriff_pg_suite.py postgres_agent_runtime postgres_agent_style
# Web source tests (node --test, no browser). All web tests, so adjacent features regress here too.
web_tests=(web/tests/*.test.cjs web/tests/*.test.mjs)
stage web_node node --test "${web_tests[@]}"
# Every Python unit test in the repository (fast; no providers, no network).
# Full discovery includes media tests that call ffmpeg; GitHub's runner image has none (Depot's does).
if ! command -v ffmpeg >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq install ffmpeg
fi
stage python_all python -m unittest discover -s tests -p 'test_*.py'
if [ "${#failed[@]}" -gt 0 ]; then
  echo "LIBRARY_INTELLIGENCE_FAILED_STAGES=${failed[*]}"
  exit 1
fi
echo "LIBRARY_INTELLIGENCE_ALL_STAGES_PASS"
