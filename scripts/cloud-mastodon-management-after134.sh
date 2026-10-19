#!/usr/bin/env bash
# Dedicated management-only remote validation; no provider calls, browser or release.
set -euo pipefail
case "${CI:-}" in 1|true|TRUE) ;; *) echo 'Use the dedicated JCB management-after134 config.' >&2; exit 64 ;; esac
if [ "$(uname -s)" != Linux ]; then echo 'Cloud-only management validation.' >&2; exit 64; fi
if [ "$#" -ne 0 ]; then echo 'This focused validation takes no arguments.' >&2; exit 64; fi
if [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ] || [ ! -x "$TREND_VISUAL_TEST_PYTHON" ]; then
  echo 'Use the existing pinned cloud-python-bootstrap.sh.' >&2; exit 64
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests POSTRIFF_RESEARCH=0 NO_PRODUCTION_API_CALLS=1

# Discovery includes integrated Mastodon modules without a stale module list.
"$TREND_VISUAL_TEST_PYTHON" -m unittest discover -s tests -p 'test_mastodon_*.py'
"$TREND_VISUAL_TEST_PYTHON" -m unittest test_hosted_wave1_connectors test_wave4c_connectors test_wave4_hosted_publish test_growth_metric_schedule test_native_insights_canary
bash scripts/cloud-mastodon-automation.sh management-after134-only

cd web
node --test tests/channel-list.test.cjs tests/channels-connect-deeplink.test.cjs tests/mastodon-connect.test.cjs tests/publishing-status.test.mjs tests/publishing-support.test.mjs tests/receipt.test.mjs tests/calendar-card.test.cjs
npm run lint
npm run typecheck
POSTRIFF_API_ORIGIN=http://127.0.0.1:4348 NEXT_PUBLIC_APP_URL=http://127.0.0.1:4448 POSTRIFF_DEV_SSR=1 npm run build
printf '%s\n' 'Management validation scope complete: synthetic unit/SQL + UI contracts/typecheck/lint/build. Browser E2E/live OAuth/production: NOT RUN.'
