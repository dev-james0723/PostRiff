#!/usr/bin/env bash
# Offline regression only: never calls a real Bluesky account or production DB.
set -euo pipefail
case "${CI:-}" in 1|true|TRUE) ;; *) echo 'Use JCB cloud execution.' >&2; exit 64 ;; esac
if [ "$(uname -s)" != Linux ] || [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ]; then
  echo 'Start through cloud-python-bootstrap.sh on the remote Linux runner.' >&2; exit 64
fi
bluesky_validation_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$bluesky_validation_root"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$bluesky_validation_root/src:$bluesky_validation_root/tests"
"$TREND_VISUAL_TEST_PYTHON" -m unittest \
  test_bluesky_production test_hosted_wave1_connectors test_social_readiness_hardening \
  test_youtube_worker_refresh test_postriff_phase2 test_postriff_phase2_hosted \
  test_rafii_origin_migration
cd -- "$bluesky_validation_root/web"
npm run typecheck
node --test tests/social-learning.test.cjs tests/channels*.test.cjs tests/brand-brain*.test.mjs
bash "$bluesky_validation_root/scripts/cloud-bluesky-postgres.sh"
