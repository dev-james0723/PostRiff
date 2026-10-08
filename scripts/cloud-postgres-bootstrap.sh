#!/usr/bin/env bash
# Remote-only PostgreSQL fixture validation using the existing pinned Python venv.
set -euo pipefail

case "${CI:-}" in
  1|true|TRUE) ;;
  *) echo "PostgreSQL validation requires cloud CI; use JCB." >&2; exit 64 ;;
esac
if [ "$(uname -s)" != "Linux" ]; then
  echo "PostgreSQL validation refuses execution on the Mac; use JCB." >&2
  exit 64
fi
if [ "$#" -ne 0 ]; then
  echo "cloud-postgres-bootstrap.sh runs only the fixed synthetic regression selection." >&2
  exit 64
fi
if [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ] || [ ! -x "$TREND_VISUAL_TEST_PYTHON" ]; then
  echo "Start PostgreSQL validation through cloud-python-bootstrap.sh." >&2
  exit 64
fi

jcb_pg_repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Reuse, rather than install or replace, the repository's isolated Python runtime.
"$TREND_VISUAL_TEST_PYTHON" - "$jcb_pg_repo_root/.python-version" <<'PY'
from pathlib import Path
import sys
expected = Path(sys.argv[1]).read_text().strip()
actual = '.'.join(str(part) for part in sys.version_info[:len(expected.split('.'))])
if actual != expected or sys.prefix == sys.base_prefix:
    raise SystemExit('PostgreSQL validation requires the existing pinned Python venv.')
PY

jcb_pg_bin="${POSTRIFF_PG_BIN:-}"
if [ -z "$jcb_pg_bin" ]; then
  for jcb_pg_candidate in /usr/lib/postgresql/17/bin /usr/lib/postgresql/16/bin; do
    if [ -x "$jcb_pg_candidate/initdb" ] && [ -x "$jcb_pg_candidate/pg_ctl" ]; then
      jcb_pg_bin="$jcb_pg_candidate"
      break
    fi
  done
fi
if [ -z "$jcb_pg_bin" ]; then
  # Ubuntu 24.04's official server package is PostgreSQL 16. No external repository
  # is added, and package installation is confined to this ephemeral CI runner.
  if [ ! -r /etc/os-release ]; then
    echo "validation_unavailable: cannot identify the cloud Linux distribution." >&2
    exit 3
  fi
  . /etc/os-release
  if [ "${ID:-}" != "ubuntu" ] || [ "${VERSION_ID:-}" != "24.04" ]; then
    echo "validation_unavailable: provide PostgreSQL 16/17 binaries on this runner." >&2
    exit 3
  fi
  if [ "$(id -u)" -eq 0 ]; then
    apt-get -qq update
    DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
  else
    sudo -n apt-get -qq update
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
  fi
  jcb_pg_bin=/usr/lib/postgresql/16/bin
fi
for jcb_pg_tool in initdb pg_ctl psql postgres; do
  if [ ! -x "$jcb_pg_bin/$jcb_pg_tool" ]; then
    echo "validation_unavailable: PostgreSQL tool missing: $jcb_pg_tool." >&2
    exit 3
  fi
done
jcb_pg_version="$("$jcb_pg_bin/postgres" --version)"
case "$jcb_pg_version" in
  'postgres (PostgreSQL) 16.'*|'postgres (PostgreSQL) 17.'*) ;;
  *) echo "validation_unavailable: PostgreSQL 16 or 17 is required." >&2; exit 3 ;;
esac
echo "Cloud disposable database: $jcb_pg_version; 127.0.0.1:55438."

jcb_pg_temp_root="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
mkdir -p -- "$jcb_pg_temp_root"
jcb_pg_home="$(mktemp -d "$jcb_pg_temp_root/jcb-postgres-home.XXXXXXXX")"
trap 'rm -rf -- "$jcb_pg_home"' EXIT
cd -- "$jcb_pg_repo_root"

# These tests inject Google, storage and agent transports. A clean environment
# excludes application credentials, production DSNs, proxy settings and research
# switches. Only the disposable cluster can be reached by the libpq defaults.
# Keep concurrent fleet claims in their own clean cluster: prior fixture accounts
# must not be blocked or mutated merely to make claim selection deterministic.
for jcb_pg_group in creator fleet revocation; do
  if [ "$jcb_pg_group" = creator ]; then
    jcb_pg_scripts=(tests/phase2/postgres_youtube_creator.py tests/phase2/postgres_video.py
      tests/phase2/postgres_consumer_campaign_worker.py tests/phase2/postgres_youtube_acceptance.py
      tests/phase2/postgres_youtube_capacity.py tests/phase2/postgres_youtube_scale.py
      tests/phase2/postgres_library_lifecycle.py tests/phase2/postgres_reverify.py)
  elif [ "$jcb_pg_group" = fleet ]; then
    jcb_pg_scripts=(tests/phase2/postgres_youtube_fleet.py)
  else
    jcb_pg_scripts=(tests/phase2/postgres_youtube_revocation.py)
  fi
env -i \
  PATH="$PATH" HOME="$jcb_pg_home" TMPDIR="$jcb_pg_temp_root" \
  CI=true LC_ALL=C PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$jcb_pg_repo_root/src:$jcb_pg_repo_root/tests" \
  POSTRIFF_PG_BIN="$jcb_pg_bin" POSTRIFF_RESEARCH=0 \
  PGUSER=postriff_test PGHOST=127.0.0.1 PGPORT=55438 PGDATABASE=postgres \
  PGCONNECT_TIMEOUT=5 PGPASSFILE=/dev/null PGSERVICEFILE=/dev/null \
  POSTRIFF_TEST_DSN='host=127.0.0.1 port=55438 dbname=postgres user=postriff_test' \
  "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_disposable_postgres.py "${jcb_pg_scripts[@]}"
done
