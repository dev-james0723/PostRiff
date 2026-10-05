#!/usr/bin/env bash
# First-class JCB E2E adapter for PostRiff/Rafii.
# Runs only on the cloud Linux executor; the Mac remains the control plane.
set -euo pipefail

case "${CI:-}" in
  1|true|TRUE) ;;
  *) echo "JCB E2E harness requires the cloud CI environment." >&2; exit 64 ;;
esac
if [ "$(uname -s)" != "Linux" ]; then
  echo "JCB E2E harness refuses local/macOS execution; use 'jcb e2e'." >&2
  exit 64
fi

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$repo_root"

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

# Match the production/release browser workflows: disposable PostgreSQL 17,
# real production Next build, and a real headless Chromium browser.
if [ ! -x /usr/lib/postgresql/17/bin/postgres ]; then
  run_root apt-get -qq update
  run_root apt-get -y -qq install postgresql-common
  run_root /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  run_root apt-get -y -qq install postgresql-17
fi
run_root mkdir -p /var/run/postgresql
run_root chmod 1777 /var/run/postgresql
export POSTRIFF_PG_BIN=/usr/lib/postgresql/17/bin

echo "JCB E2E: preparing isolated web copy"
python scripts/consumer_ready_web.py --prepare npm ci

# consumer_ready_web.py intentionally builds from an isolated copy. Attach that
# copy to JCB's task-scoped Next cache instead of leaving the mounted cache idle.
if [ -d /mnt/jcb-framework-cache ]; then
  mkdir -p .codex/consumer-ready/web/.next
  rm -rf .codex/consumer-ready/web/.next/cache
  ln -s /mnt/jcb-framework-cache .codex/consumer-ready/web/.next/cache
fi

echo "JCB E2E: building isolated production frontend"
python scripts/consumer_ready_web.py npm run build

echo "JCB E2E: installing Chromium on the cloud runner"
(
  cd .codex/consumer-ready/web
  npx playwright install --with-deps chromium
)

echo "JCB E2E: starting disposable API/PostgreSQL/web harness and running browser acceptance"
python scripts/consumer_ready_browser.py

echo "JCB E2E PASS: Python API + disposable PostgreSQL + production Next + Chromium acceptance"
