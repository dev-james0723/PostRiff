#!/usr/bin/env bash
# Synthetic fixtures only, in the sanitized JCB Linux runner. TikTok-affected suites and the web checks gate the run;
# the full Python suite runs last and is reported, because unrelated lanes (e.g. Library previews that need
# LibreOffice on the runner) and known base failures must not hide the TikTok result.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Use JCB Linux cloud CI for TikTok launch validation.' >&2; exit 64
fi
cd "$(dirname "$0")/.."
export PYTHONPATH=src:tests PYTHONDONTWRITEBYTECODE=1
python -m unittest -v test_tiktok_sandbox_oauth test_hosted_wave3_connectors test_hosted_wave1_connectors test_wave4c_connectors test_postriff_billing test_rafii_creation_capabilities test_postriff_orchestration test_postriff_request_model test_pinterest_production_prep
(
  cd web
  node --test tests/tiktok-composer.test.mjs
  node --experimental-strip-types --test tests/creation-capabilities.test.mjs
  node node_modules/next/dist/bin/next typegen
  npm run typecheck
  npm run lint
  npm run build
)
set +e
python -m unittest discover -s tests -p 'test_*.py' -t tests > /tmp/tiktok-full-suite.log 2>&1
full=$?
set -e
grep -E '^(Ran [0-9]+ tests|OK|FAILED|ERROR: |FAIL: )' /tmp/tiktok-full-suite.log || true
echo "Full Python suite exit (reported, not gating): $full"
