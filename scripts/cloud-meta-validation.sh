#!/usr/bin/env bash
# Synthetic contract/DB checks only; no production credentials or provider traffic.
set -euo pipefail
case "${CI:-}" in 1|true|TRUE) ;; *) echo 'Use JCB cloud CI.' >&2; exit 64 ;; esac
if [ "$(uname -s)" != Linux ] || [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ]; then
  echo 'Use cloud-python-bootstrap.sh on Linux.' >&2; exit 64
fi
case "${1:-}" in ''|--schema-only|--python-only|--full) ;; *) exit 64 ;; esac
meta_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$meta_root"
export PYTHONPATH="$meta_root/src:$meta_root/tests" PYTHONDONTWRITEBYTECODE=1
if [ "${1:-}" != --schema-only ]; then
  "$TREND_VISUAL_TEST_PYTHON" -m unittest discover -s tests -p 'test_trend_meta*.py'
fi
if [ "${1:-}" = --python-only ]; then exit 0; fi
meta_pg_bin=/usr/lib/postgresql/16/bin
if [ ! -x "$meta_pg_bin/initdb" ]; then
  if [ "$(id -u)" = 0 ]; then
    apt-get -qq update
    DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
  else
    sudo -n apt-get -qq update
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
  fi
fi
meta_home="$(mktemp -d)"
trap 'rm -rf -- "$meta_home"' EXIT
meta_scripts=(tests/phase2/postgres_trend_meta.py)
if [ "${1:-}" = --full ]; then
  meta_scripts+=(tests/phase2/postgres_trend_trust.py tests/phase2/postgres_trend_services.py tests/phase2/postgres_trend_pipeline.py)
fi
for meta_script in "${meta_scripts[@]}"; do
  env -i PATH="$PATH" HOME="$meta_home" CI=true LC_ALL=C PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$PYTHONPATH" POSTRIFF_RESEARCH=0 POSTRIFF_PG_BIN="$meta_pg_bin" \
  PGUSER=postriff_test PGHOST=127.0.0.1 PGPORT=55438 PGDATABASE=postgres \
  PGCONNECT_TIMEOUT=5 \
  "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_disposable_postgres.py "$meta_script"
done
if [ "${1:-}" = --full ]; then
  "$TREND_VISUAL_TEST_PYTHON" -m unittest discover -s tests -p 'test_trend_*.py'
  npm --prefix web run typecheck
  npm --prefix web run lint
  npm --prefix web run build
  bash scripts/cloud-meta-browser.sh
fi
