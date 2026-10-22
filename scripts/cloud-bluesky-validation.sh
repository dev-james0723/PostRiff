#!/usr/bin/env bash
# Bluesky launch validation. Offline only: never calls a real Bluesky account or a production database.
set -euo pipefail
if [ "${CI:-}" != "true" ] && [ "${CI:-}" != "1" ]; then echo 'Use JCB cloud execution.' >&2; exit 64; fi
if [ "$(uname -s)" != 'Linux' ]; then echo 'Cloud-only validation.' >&2; exit 64; fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests
scope="${1:-all}"
case "$scope" in all|python|web) ;; *) echo 'Choose all, python or web validation.' >&2; exit 64 ;; esac
if [ "$scope" != web ]; then
  "$TREND_VISUAL_TEST_PYTHON" -m unittest -v test_bluesky_launch_readiness test_bluesky_p0_hardening test_hosted_wave1_connectors \
    test_social_readiness_hardening test_postriff_channels test_connection_health test_youtube_refresh_projection \
    test_postriff_phase2 test_postriff_phase2_hosted test_rafii_origin_migration \
    test_founder_product_events \
    test_youtube_worker_refresh test_postriff_orchestration test_wave4_hosted_publish test_postriff_platforms_x \
    test_mastodon_management test_r0_hotfixes test_migration_numbers \
    control.test_founder_ops control.test_founder_connections control.test_founder_risk control.test_business_workspace
  if [ ! -x /usr/lib/postgresql/16/bin/initdb ]; then
    sudo -n apt-get -qq update
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
  fi
  export POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin
  [ -d /var/run/postgresql ] || sudo -n install -d -m 0775 -o "$(id -un)" /var/run/postgresql
  "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_bluesky_launch postgres_connection_health
fi
if [ "$scope" != python ]; then
  cd web
  node --test tests/channel-list.test.cjs tests/channels-connect-deeplink.test.cjs tests/publishing-status.test.mjs tests/publishing-support.test.mjs
  npm run lint -- --format=unix
  npm run typecheck
fi
