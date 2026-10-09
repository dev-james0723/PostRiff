#!/usr/bin/env bash
# Content Skills Integration (2026-10-09): the repository's own release gates, remote-only.
# Python domain contracts (full discovery, as consumer-ready.yml), the disposable PostgreSQL suite, web contracts,
# types, lint and the production build. Invoke only through cloud-python-bootstrap.sh on a JCB/Depot runner.
set -euo pipefail

case "${CI:-}" in
  1|true|TRUE) ;;
  *) echo "Content skills validation requires cloud CI; use JCB." >&2; exit 64 ;;
esac
if [ "$(uname -s)" != "Linux" ] || [ "$#" -ne 0 ] || [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ] || [ ! -x "$TREND_VISUAL_TEST_PYTHON" ]; then
  echo "Requires cloud Linux and the pinned Python bootstrap (cloud-python-bootstrap.sh)." >&2
  exit 64
fi

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$root"
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/src:$root/tests" POSTRIFF_RESEARCH=0 POSTRIFF_LOCAL_CLI=0
export NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_SENTRY_DISABLED=1

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
stage "content-skills: targeted P0/P1/P2 contracts"
"$TREND_VISUAL_TEST_PYTHON" -m unittest -v test_rafii_creation_capabilities 2>&1 | tail -n 60
# CONTENT_SKILLS_STAGES=web reruns only the web and browser gates (after a web-only change on a commit whose Python and
# PostgreSQL gates already passed remotely); the default runs everything.
if [ "${CONTENT_SKILLS_STAGES:-all}" != "web" ]; then
  stage "python: full discovery (consumer-ready.yml parity)"
  "$TREND_VISUAL_TEST_PYTHON" -m unittest discover -s tests -p 'test_*.py'
  stage "postgres: disposable clusters, every tests/phase2/postgres_*.py group ($("$pg_bin/postgres" --version))"
  POSTRIFF_PG_BIN="$pg_bin" "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_pg_suite.py
fi

cd -- "$root/web"
stage "web: contracts and locale checks"
node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs
node tests/trend-contract.cjs
stage "web: types, lint, production build"
node node_modules/next/dist/bin/next typegen
npm run typecheck
npm run lint -- --format=unix
POSTRIFF_API_ORIGIN=http://127.0.0.1:4348 NEXT_PUBLIC_APP_URL=http://127.0.0.1:4448 POSTRIFF_DEV_SSR=1 npm run build
stage "browser: composer facet, native formats, 390px, keyboard (A32)"
POSTRIFF_PG_BIN="$pg_bin" bash "$root/scripts/cloud-content-skills-browser.sh"
stage "content-skills validation complete"
