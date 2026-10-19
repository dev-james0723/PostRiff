#!/usr/bin/env bash
# Uses the existing disposable cluster harness; no production credentials.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ] || [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ]; then
  echo 'Use the cloud Python bootstrap via JCB.' >&2; exit 64
fi
bluesky_pg_bin=/usr/lib/postgresql/16/bin
if [ ! -x "$bluesky_pg_bin/initdb" ]; then
  . /etc/os-release
  if [ "$ID" != ubuntu ] || [ "$VERSION_ID" != 24.04 ]; then
    echo 'validation_unavailable: PostgreSQL 16 is required on Ubuntu 24.04.' >&2; exit 3
  fi
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq --no-install-recommends install postgresql-16
fi
bluesky_pg_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$bluesky_pg_root"
env -i PATH="$(dirname -- "$TREND_VISUAL_TEST_PYTHON"):/usr/bin:/bin" LC_ALL=C CI=true \
  PYTHONDONTWRITEBYTECODE=1 POSTRIFF_PG_BIN="$bluesky_pg_bin" POSTRIFF_RESEARCH=0 \
  PGUSER=postriff_test PGHOST=127.0.0.1 PGPORT=55438 PGDATABASE=postgres \
  PGCONNECT_TIMEOUT=5 PGPASSFILE=/dev/null PGSERVICEFILE=/dev/null \
  "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_disposable_postgres.py tests/phase2/postgres_bluesky.py
