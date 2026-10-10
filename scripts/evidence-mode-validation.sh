#!/usr/bin/env bash
set -euo pipefail
[[ "$(uname -s)" == Linux && "${CI:-}" == true ]] || { echo 'Run through JCB cloud CI'; exit 64; }
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src:$PWD/tests" POSTRIFF_RESEARCH=0
python -m unittest test_evidence_mode test_growth_beta test_growth_loop test_rafii_workflows test_r0_hotfixes -v
if [ ! -x /usr/lib/postgresql/17/bin/initdb ]; then
  sudo apt-get update -qq
  sudo apt-get install -y postgresql-common
  sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  sudo apt-get update -qq
  sudo apt-get install -y postgresql-17
fi
sudo mkdir -p /var/run/postgresql
sudo chmod 1777 /var/run/postgresql
export POSTRIFF_PG_BIN=/usr/lib/postgresql/17/bin
python scripts/postriff_pg_suite.py postgres_growth_metric_reads
cd web
npm run typecheck
node --test tests/agent-ui-journeys/evidence-mode.test.cjs tests/agent-ui-journeys/j06-j09.test.cjs tests/agent-ui-journeys/j01-j02.test.cjs
npx playwright install --with-deps chromium webkit
node tests/evidence-mode-browser.cjs
