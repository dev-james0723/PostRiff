#!/usr/bin/env bash
# Complete only failed/not-run gates; reuse unchanged299 Python and six PG passes.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Use the separately authorized JCB/cloud recovery route.' >&2; exit 64
fi
cd "$(dirname "$0")/.."
export PYTHONPATH=src:tests PYTHONDONTWRITEBYTECODE=1
bash scripts/cloud-pinterest-postgres.sh tests/phase2/postgres_rapv2_acceptance.py
node --test web/tests/agent-ui-bridges-coverage.test.cjs
cd web
node node_modules/next/dist/bin/next typegen
npm run typecheck
npm run lint
npm run build
cd ..
bash scripts/cloud-pinterest-preview-browser.sh
