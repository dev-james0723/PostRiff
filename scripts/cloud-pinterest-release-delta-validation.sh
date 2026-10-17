#!/usr/bin/env bash
# Synthetic, sanitized cloud delta validation only; no credentials or provider traffic.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Use the authorized JCB/cloud validation route.' >&2; exit 64
fi
cd "$(dirname "$0")/.."
export PYTHONPATH=src:tests PYTHONDONTWRITEBYTECODE=1
python -m unittest -v test_pinterest_analytics test_pinterest_configuration_diagnostics test_pinterest_schedule_reverification test_youtube_worker_refresh test_growth_metric_schedule test_hosted_wave3_connectors test_pinterest_pilot test_pinterest_production_prep test_connection_health
bash scripts/cloud-pinterest-postgres.sh
node --test web/tests/agent-ui-bridges-coverage.test.cjs
cd web
node node_modules/next/dist/bin/next typegen
npm run typecheck
npm run lint
npm run build
cd ..
bash scripts/cloud-pinterest-preview-browser.sh
