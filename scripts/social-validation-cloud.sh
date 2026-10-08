#!/usr/bin/env bash
# Synthetic provider contracts and real disposable SQL, exclusively on cloud CI.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Social validation requires JCB cloud Linux CI; no local fallback.' >&2
  exit 64
fi
jcb_social_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Focused LinkedIn regression before the normal affected/release suites. Never live.
if [ "${1:-}" = --linkedin-publishing-regression ]; then
  cd -- "$jcb_social_root"
  export PYTHONPATH="$jcb_social_root/src:$jcb_social_root/tests"
  python -m unittest -v test_linkedin_publishing_recovery
  cd -- "$jcb_social_root/web"
  node --test src/lib/channels/connection-status.test.cjs
  exit 0
fi
# Reproduce the required GitHub History Import browser suite without unrelated suites.
if [ "${1:-}" = --history-import-regression ]; then
  cd -- "$jcb_social_root"
  export PYTHONPATH="$jcb_social_root/src:$jcb_social_root/tests"
  if ! command -v pg_config >/dev/null; then
    sudo -n apt-get -qq update
    sudo -n apt-get -y -qq install postgresql
  fi
  export POSTRIFF_PG_BIN="$(pg_config --bindir)"
  # Match the required GitHub job: its disposable backend uses the default socket directory.
  sudo -n mkdir -p /var/run/postgresql
  sudo -n chmod 1777 /var/run/postgresql
  python scripts/consumer_ready_web.py --prepare npm ci
  python scripts/consumer_ready_web.py npm run build
  node .codex/consumer-ready/web/node_modules/playwright/cli.js install --with-deps chromium
  if python scripts/consumer_ready_browser.py --history-import; then
    exit 0
  else
    jcb_social_history_status=$?
    for jcb_social_history_log in docs/consumer-ready/evidence/durable-backend.log docs/consumer-ready/evidence/durable-frontend.log; do
      if [ -f "$jcb_social_history_log" ]; then tail -100 "$jcb_social_history_log"; fi
    done
    exit "$jcb_social_history_status"
  fi
fi
# Reproduce the required release gate's paged cleanup contract in isolation.
if [ "${1:-}" = --frontier-regression ]; then
  cd -- "$jcb_social_root"
  export PYTHONPATH="$jcb_social_root/src:$jcb_social_root/tests"
  if ! command -v pg_config >/dev/null; then
    sudo -n apt-get -qq update
    sudo -n apt-get -y -qq install postgresql
  fi
  export POSTRIFF_PG_BIN="$(pg_config --bindir)"
  sudo -n mkdir -p /var/run/postgresql
  sudo -n chmod 1777 /var/run/postgresql
  python scripts/postriff_pg_suite.py postgres_trend_frontier
  exit 0
fi
jcb_social_connection_only=0
case "${1:-}" in
  --connection-regression) jcb_social_connection_only=1 ;;
  '') node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs ;;
  # Deployment isolation spans Python and the browser build configuration.
  --backend-only) node --test tests/deployment-env.test.mjs src/lib/channels/connection-status.test.cjs src/lib/channels/onboarding.test.cjs ;;
  *) echo 'Unknown social validation mode.' >&2; exit 64 ;;
esac
cd -- "$jcb_social_root"
export PYTHONPATH="$jcb_social_root/src:$jcb_social_root/tests"
if [ "$jcb_social_connection_only" -eq 0 ]; then
python -m unittest test_postriff_channels test_postriff_phase2 test_postriff_audience_contract test_official_social test_linkedin_publishing_recovery test_hosted_job_dispatch test_facebook_connection test_postriff_providers test_hosted_wave1_connectors test_hosted_wave3_connectors test_social_readiness_hardening test_hosted_storage_video test_asset_consumers test_asset_kinds test_instagram_full_capabilities test_social_voice_preflight test_postriff_hosted_deployment test_consumer_deployment
fi
if ! command -v pg_config >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq install postgresql
fi
export POSTRIFF_PG_BIN="$(pg_config --bindir)"
if [ "$jcb_social_connection_only" -eq 0 ]; then
  python scripts/postriff_disposable_postgres.py tests/phase2/postgres_instagram_lifecycle.py tests/phase2/postgres_safety.py tests/phase2/postgres_official_social.py tests/phase2/postgres_facebook_connection.py
fi
# Each legacy connection suite requires a fresh cluster. Keep these in the
# scoped Depot gate too so its coverage cannot hide GitHub scope-drift failures.
for jcb_social_connection_suite in postgres_channels postgres_reverify postgres_x_oauth; do
  python scripts/postriff_disposable_postgres.py "tests/phase2/$jcb_social_connection_suite.py"
done
