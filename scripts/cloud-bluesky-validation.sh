#!/usr/bin/env bash
# Offline regression only: never calls a real Bluesky account or production DB.
set -euo pipefail
case "${CI:-}" in 1|true|TRUE) ;; *) echo 'Use JCB cloud execution.' >&2; exit 64 ;; esac
if [ "$(uname -s)" != Linux ] || [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ]; then
  echo 'Start through cloud-python-bootstrap.sh on the remote Linux runner.' >&2; exit 64
fi
bluesky_validation_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$bluesky_validation_root"
case "${1:-}" in
  '') bluesky_browser=0; bluesky_full=1 ;;
  --browser) bluesky_browser=1; bluesky_full=1 ;;
  --browser-only) bluesky_browser=1; bluesky_full=0 ;;
  *) echo 'Unsupported Bluesky validation option.' >&2; exit 64 ;;
esac
if [ "$#" -gt 1 ]; then echo 'Only one validation option is allowed.' >&2; exit 64; fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$bluesky_validation_root/src:$bluesky_validation_root/tests"
if [ "$bluesky_full" -eq 1 ]; then
"$TREND_VISUAL_TEST_PYTHON" -m unittest \
  test_bluesky_production test_hosted_wave1_connectors test_social_readiness_hardening \
  test_youtube_worker_refresh test_postriff_phase2 test_postriff_phase2_hosted \
  test_rafii_origin_migration test_founder_product_events.OAuthCallSiteTests
cd -- "$bluesky_validation_root/web"
npm run typecheck
node --test tests/social-learning.test.cjs tests/channels*.test.cjs tests/brand-brain*.test.mjs
bash "$bluesky_validation_root/scripts/cloud-bluesky-postgres.sh"
fi
cd -- "$bluesky_validation_root/web"
if [ "$bluesky_browser" -eq 1 ]; then
  ./node_modules/.bin/oxlint src/features/queue/schedule-dialog.tsx src/features/queue/bluesky-manifest-details.tsx src/features/queue/queue-view.tsx src/features/queue/job-sheet.tsx src/features/channels/bluesky-profile-sheet.tsx
  POSTRIFF_API_ORIGIN=http://127.0.0.1:4348 NEXT_PUBLIC_APP_URL=http://127.0.0.1:4448 POSTRIFF_DEV_SSR=1 npm run build
  RAFII_BROWSER_SUITE=bluesky bash "$bluesky_validation_root/scripts/cloud-youtube-browser.sh"
fi
