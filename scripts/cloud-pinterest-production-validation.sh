#!/usr/bin/env bash
# Synthetic fixtures only, in the sanitized JCB Linux runner.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Use JCB Linux cloud CI for Pinterest production preparation.' >&2; exit 64
fi
cd "$(dirname "$0")/.."
export PYTHONPATH=src:tests PYTHONDONTWRITEBYTECODE=1
python -m unittest -v test_hosted_wave3_connectors test_pinterest_trial_readiness test_pinterest_trial_evidence test_pinterest_pilot test_pinterest_production_prep test_postriff_phase2_hosted test_agent_capability_registry test_rafii_browser_session_guard test_rafii_account_protection_p0 test_postriff_account_security test_rafii_account_protection_a1 test_rafii_creation_capabilities
python tests/pinterest_agent_registration.py
python scripts/pinterest-synthetic-load.py
bash scripts/cloud-pinterest-postgres.sh
node --test studio/broker/tests/pinterest-broker.test.mjs
node --experimental-strip-types --test studio/web/tests/connections-api.test.ts
node --experimental-strip-types --test web/src/components/application/post-preview/preview-metadata.test.ts
cd web
node --test src/lib/channels/onboarding.test.cjs
node --experimental-strip-types --test tests/creation-capabilities.test.mjs
node node_modules/next/dist/bin/next typegen
npm run typecheck
npm run lint
npm run build
cd ..
bash scripts/cloud-pinterest-preview-browser.sh
