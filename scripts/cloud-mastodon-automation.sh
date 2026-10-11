#!/usr/bin/env bash
# Targeted Automation regression; disposable cloud SQL and synthetic writer/provider.
set -euo pipefail
case "${CI:-}" in 1|true|TRUE) ;; *) echo 'Use JCB cloud execution.' >&2; exit 64 ;; esac
if [ "$(uname -s)" != Linux ]; then echo 'Cloud-only validation.' >&2; exit 64; fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests
if [ ! -x /usr/lib/postgresql/16/bin/initdb ]; then
  sudo -n apt-get -qq update
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
fi
export POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin
case "${1:-}" in
  sql-only) "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_mastodon_management ;;
  '')
    "$TREND_VISUAL_TEST_PYTHON" -m unittest test_postriff_time_savings test_youtube_workspace_provider_data test_mastodon_management test_agent_runtime test_mastodon_threads test_mastodon_publishing test_hosted_wave1_connectors
    "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_time_savings postgres_mastodon_automation postgres_mastodon_management ;;
  *) echo 'Unknown validation mode.' >&2; exit 64 ;;
esac
