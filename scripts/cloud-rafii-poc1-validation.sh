#!/usr/bin/env bash
# Rafii POC-1 candidate (2026-10-15): remote-only gates for the strict 24h review, report snapshots, operation
# eligibility, window truth and the Growth Loop draft link: targeted contracts, targeted disposable-PostgreSQL groups and
# full Python discovery (consumer-ready.yml parity); every PostgreSQL group as a second run. No web source changed.
# Invoke only through cloud-python-bootstrap.sh on a JCB/Depot runner.
set -euo pipefail

case "${CI:-}" in
  1|true|TRUE) ;;
  *) echo "Rafii POC-1 validation requires cloud CI; use JCB." >&2; exit 64 ;;
esac
if [ "$(uname -s)" != "Linux" ] || [ "$#" -ne 0 ] || [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ] || [ ! -x "$TREND_VISUAL_TEST_PYTHON" ]; then
  echo "Requires cloud Linux and the pinned Python bootstrap (cloud-python-bootstrap.sh)." >&2
  exit 64
fi

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$root"
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/src:$root/tests" POSTRIFF_RESEARCH=0 POSTRIFF_LOCAL_CLI=0

as_root() { if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo -n "$@"; fi; }
if ! command -v libreoffice >/dev/null || ! command -v ffmpeg >/dev/null; then
  as_root apt-get -qq update
  as_root env DEBIAN_FRONTEND=noninteractive apt-get -y -qq install ffmpeg libreoffice-writer libreoffice-calc libreoffice-impress libseccomp2
fi
pg_bin=""
for candidate in /usr/lib/postgresql/17/bin /usr/lib/postgresql/16/bin; do
  if [ -x "$candidate/initdb" ] && [ -x "$candidate/pg_ctl" ]; then pg_bin="$candidate"; break; fi
done
if [ -z "$pg_bin" ]; then
  as_root env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
  pg_bin=/usr/lib/postgresql/16/bin
fi
as_root mkdir -p /var/run/postgresql && as_root chmod 1777 /var/run/postgresql

stage() { echo; echo "=== $1 ==="; }
# The JCB job has a fixed 45-minute limit: RAFII_POC1_STAGES=pg-all runs only the full PostgreSQL regression suite as a
# second run; the default runs the targeted contracts, the targeted PostgreSQL groups and full Python discovery.
if [ "${RAFII_POC1_STAGES:-core}" = "pg-all" ]; then
  stage "postgres: every tests/phase2/postgres_*.py group ($("$pg_bin/postgres" --version))"
  POSTRIFF_PG_BIN="$pg_bin" "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py
  stage "rafii-poc1 full PostgreSQL validation complete"
  exit 0
fi
stage "rafii-poc1: targeted contracts (POC-1 case table, scheduler, growth loop, router ledger, approval model)"
"$TREND_VISUAL_TEST_PYTHON" -m unittest -v test_rafii_poc1_review test_growth_metric_schedule test_growth_loop test_growth_router test_postriff_phase2 2>&1 | tail -n 80
stage "rafii-poc1: disposable PostgreSQL, POC-1 group and the groups it builds on ($("$pg_bin/postgres" --version))"
POSTRIFF_PG_BIN="$pg_bin" "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py postgres_rafii_poc1 postgres_channels postgres_growth_metric_reads postgres_growth_loop
stage "python: full discovery (consumer-ready.yml parity)"
"$TREND_VISUAL_TEST_PYTHON" -m unittest discover -s tests -p 'test_*.py'
stage "rafii-poc1 core validation complete"
