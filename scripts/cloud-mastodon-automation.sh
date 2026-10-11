#!/usr/bin/env bash
# Targeted Automation regression; disposable cloud SQL and synthetic writer/provider.
set -euo pipefail
case "${CI:-}" in 1|true|TRUE) ;; *) echo 'Use JCB cloud execution.' >&2; exit 64 ;; esac
if [ "$(uname -s)" != Linux ]; then echo 'Cloud-only validation.' >&2; exit 64; fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests
pg_major=16
case "${1:-}" in youtube-disconnect-only|release-preflight-only) pg_major=17 ;; esac
if [ ! -x "/usr/lib/postgresql/$pg_major/bin/initdb" ]; then
  sudo -n apt-get -qq update
  if [ "$pg_major" = 17 ]; then
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-common
    sudo -n /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  fi
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install "postgresql-$pg_major"
fi
export POSTRIFF_PG_BIN="/usr/lib/postgresql/$pg_major/bin"
case "${1:-}" in
  youtube-disconnect-only) "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_youtube_workspace_provider_data ;;
  release-preflight-only) "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_consumer_migrations postgres_mastodon_automation_legacy ;;
  sql-only) "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_mastodon_management ;;
  '')
    "$TREND_VISUAL_TEST_PYTHON" -m unittest test_postriff_time_savings test_youtube_workspace_provider_data test_mastodon_management test_agent_runtime test_mastodon_threads test_mastodon_publishing test_hosted_wave1_connectors
    "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_time_savings postgres_mastodon_automation postgres_mastodon_management ;;
  *) echo 'Unknown validation mode.' >&2; exit 64 ;;
esac
