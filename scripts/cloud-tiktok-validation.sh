#!/usr/bin/env bash
# Synthetic fixtures only, in the sanitized JCB Linux runner. Full Python suite plus the web checks, because the
# TikTok release candidate changes shared OAuth, publishing-gate, webhook and channel-directory code.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Use JCB Linux cloud CI for TikTok launch validation.' >&2; exit 64
fi
cd "$(dirname "$0")/.."
export PYTHONPATH=src:tests PYTHONDONTWRITEBYTECODE=1
python -m unittest -v test_tiktok_sandbox_oauth test_hosted_wave3_connectors test_wave4c_connectors test_postriff_billing test_rafii_creation_capabilities test_postriff_orchestration
python -m unittest discover -s tests -p 'test_*.py' -t tests
cd web
node --test tests/tiktok-composer.test.mjs
node --experimental-strip-types --test tests/creation-capabilities.test.mjs
node node_modules/next/dist/bin/next typegen
npm run typecheck
npm run lint
npm run build
