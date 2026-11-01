#!/usr/bin/env bash
# Offline/synthetic checks only; no Pinterest API or production database input.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Pinterest validation requires the JCB Linux CI runner.' >&2
  exit 64
fi
cd "$(dirname "$0")/.."
export PYTHONPATH=src:tests PYTHONDONTWRITEBYTECODE=1
if [ "${1:-}" != --hosted-ui-only ]; then
python -m unittest -v test_hosted_wave3_connectors test_pinterest_trial_readiness test_pinterest_trial_evidence
node --test studio/broker/tests/pinterest-broker.test.mjs
node --experimental-strip-types --test studio/web/tests/connections-api.test.ts
node --experimental-strip-types --test web/src/components/application/post-preview/preview-metadata.test.ts
npm --prefix studio/web ci --no-audit --no-fund
npm --prefix studio/web run build
fi
if [ "${1:-}" = --hosted-ui-only ]; then
  node --experimental-strip-types --test web/src/components/application/post-preview/preview-metadata.test.ts
fi
cd web
node node_modules/next/dist/bin/next typegen
npm run typecheck
npm run lint
npm run build
