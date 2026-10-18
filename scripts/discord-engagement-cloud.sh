#!/usr/bin/env bash
# One scoped cloud run: consent/replies, real disposable SQL, types and browser.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Use the scoped JCB/Depot Linux engagement route; no local fallback.' >&2; exit 64
fi
engagement_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$engagement_root"
export PYTHONDONTWRITEBYTECODE=1 RAFII_DISCORD_SYNTHETIC_FENCE=1
export PYTHONPATH="$engagement_root/scripts/linkedin_test_fence:$engagement_root/src:$engagement_root/tests"
python -c 'import sitecustomize; sitecustomize.self_check()'
case "${1:-}" in
  '') [ "$#" -eq 0 ] || exit 64
      python -m unittest test_discord_engagement test_discord_publish_authorization test_discord_worker_lifecycle \
        test_discord_presend_retry test_discord_oauth_lifecycle test_discord_destinations test_discord_rate_limits test_hosted_wave1_connectors ;;
  --resume-review-delta)
      [ "$#" -eq 1 ] || exit 64
      # Reuse only the 198 unaffected prior controls. Rerun the full affected
      # engagement suite after the reviewed fail-closed flags and UI delta.
      python tests/discord_engagement_reuse_proof.py
      python -m unittest test_discord_engagement ;;
  --resume-frontend)
      [ "$#" -eq 1 ] || exit 64
      # Backend and SQL passed on the same backend bytes in k2x1lzm0kp.
      python tests/discord_engagement_reuse_proof.py ;;
  --resume-types)
      [ "$#" -eq 1 ] || exit 64
      python tests/discord_engagement_reuse_proof.py ;;
  --resume-browser)
      [ "$#" -eq 1 ] || exit 64
      # Exact product bytes passed lint/types/build in ktx1px0n6g. Only the
      # synthetic API-shape fixture changed; run the affected browser checks.
      python tests/discord_engagement_reuse_proof.py ;;
  --resume-ui-integration)
      [ "$#" -eq 1 ] || exit 64
      python tests/discord_engagement_reuse_proof.py ;;
  *) exit 64 ;;
esac
if [ "${1:-}" != --resume-frontend ] && [ "${1:-}" != --resume-types ] && [ "${1:-}" != --resume-browser ] && [ "${1:-}" != --resume-ui-integration ]; then
engagement_pg=/usr/lib/postgresql/17/bin
if [ ! -x "$engagement_pg/postgres" ]; then
  engagement_suite="$(. /etc/os-release; printf '%s' "$VERSION_CODENAME")"
  engagement_arch="$(dpkg --print-architecture)"
  case "$engagement_suite:$engagement_arch" in noble:amd64|noble:arm64|jammy:amd64|jammy:arm64) ;; *) exit 64 ;; esac
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq --no-install-recommends install curl ca-certificates postgresql-common
  sudo -n install -d /usr/share/postgresql-common/pgdg
  sudo -n curl --proto '=https' --tlsv1.2 --fail --silent --show-error https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
  printf 'Types: deb\nURIs: https://apt.postgresql.org/pub/repos/apt\nSuites: %s-pgdg\nArchitectures: %s\nComponents: main\nSigned-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc\n' "$engagement_suite" "$engagement_arch" | sudo -n tee /etc/apt/sources.list.d/pgdg.sources >/dev/null
  printf '\ncreate_main_cluster = false\n' | sudo -n tee -a /etc/postgresql-common/createcluster.conf >/dev/null
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq --no-install-recommends install postgresql-17
fi
export POSTRIFF_PG_BIN="$engagement_pg"
python scripts/postriff_disposable_postgres.py tests/phase2/postgres_discord_engagement.py
fi
python tests/discord_ui_fixture.py .depot/discord-p0-ui.json
python tests/discord_engagement_ui_fixture.py .depot/discord-engagement-ui.json
cd web
if [ "${1:-}" != --resume-browser ]; then
if [ "${1:-}" = --resume-types ] || [ "${1:-}" = --resume-ui-integration ]; then
  # The full lint passed on the same source except this one loading fallback.
  ./node_modules/.bin/oxlint src/features/inbox/inbox-view.tsx src/features/inbox/coverage-strip.tsx --format json > ../.depot/discord-engagement-lint.json || { cat ../.depot/discord-engagement-lint.json; exit 1; }
else
  npm run --silent lint -- --format json > ../.depot/discord-engagement-lint.json || { cat ../.depot/discord-engagement-lint.json; exit 1; }
fi
npm run typecheck
fi
node node_modules/playwright/cli.js install --with-deps chromium
engagement_browser_status=0
node tests/discord-engagement-browser.cjs || engagement_browser_status=$?
if [ "${1:-}" != --resume-browser ]; then npm run build; fi
[ "$engagement_browser_status" -eq 0 ] || exit "$engagement_browser_status"
printf 'RAFII_DISCORD_ENGAGEMENT_CANDIDATE_PASS cloud-only synthetic provider; no capacity run or real publication\n'
