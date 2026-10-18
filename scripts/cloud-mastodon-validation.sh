#!/usr/bin/env bash
set -euo pipefail
if [ "${CI:-}" != "true" ] && [ "${CI:-}" != "1" ]; then echo 'Use JCB cloud execution.' >&2; exit 64; fi
if [ "$(uname -s)" != 'Linux' ]; then echo 'Cloud-only validation.' >&2; exit 64; fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests
scope="${1:-all}"
case "$scope" in all|frontend) ;; *) echo 'Choose all or frontend validation.' >&2; exit 64 ;; esac
if [ "$scope" = all ] && ! command -v libreoffice >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install ffmpeg libreoffice-writer libreoffice-calc libreoffice-impress libseccomp2
fi
if ! command -v ffmpeg >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install ffmpeg
fi
if [ "$scope" = all ]; then
  "$TREND_VISUAL_TEST_PYTHON" -m unittest test_youtube_workspace_provider_data test_mastodon_health test_mastodon_write_release test_mastodon_insights test_growth_metric_schedule test_native_insights_canary test_mastodon_publishing test_mastodon_threads test_mastodon_native test_mastodon_streaming test_document_renderer_download test_mastodon_media test_mastodon_profile test_agent_capability_registry test_agent_permissions test_postriff_platforms_x test_mastodon_management test_hosted_wave1_connectors test_wave4c_connectors test_wave4_hosted_publish test_postriff_phase2 test_postriff_phase2_hosted test_asset_kinds test_hosted_storage_library test_library_extract test_migration_numbers test_agent_runtime test_agent_runtime_references test_youtube_agent_tools test_postriff_automation_chat
fi
if [ ! -x /usr/lib/postgresql/16/bin/initdb ]; then
  sudo -n apt-get -qq update
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
fi
export POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin
if [ "$scope" = all ]; then
  "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_mastodon_management postgres_mastodon_automation postgres_mastodon_scale postgres_library postgres_library_lifecycle postgres_consumer_migrations
fi
cd web
if [ "$scope" = all ]; then
  node --test tests/channel-list.test.cjs tests/channels-connect-deeplink.test.cjs tests/publishing-status.test.mjs tests/publishing-support.test.mjs tests/receipt.test.mjs tests/calendar-card.test.cjs
fi
npm run lint -- --format=unix
npm run typecheck
POSTRIFF_API_ORIGIN=http://127.0.0.1:4348 NEXT_PUBLIC_APP_URL=http://127.0.0.1:4448 POSTRIFF_DEV_SSR=1 npm run build
bash ../scripts/cloud-mastodon-browser.sh
