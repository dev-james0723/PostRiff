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
"$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_mastodon_automation
