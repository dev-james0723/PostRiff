#!/usr/bin/env bash
set -euo pipefail
[[ "$(uname -s)" == Linux && "${CI:-}" == true ]] || { echo 'Run via JCB cloud'; exit 64; }
cd "$(dirname "$0")/.."
mode="${1:-all}"
case "$mode" in all|backend|ui|browser) ;; *) exit 64 ;; esac
export PYTHONPATH="$PWD/src:$PWD/tests" POSTRIFF_RESEARCH=0
if [[ "$mode" == all || "$mode" == backend ]]; then
python -m unittest test_creator_pipeline test_final_suggestions test_postriff_suggestions -v
if [ ! -x /usr/lib/postgresql/17/bin/initdb ]; then
 sudo apt-get update -qq
 sudo apt-get install -y postgresql-common
 sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
 sudo apt-get update -qq
 sudo apt-get install -y postgresql-17
fi
sudo install -d -m 1777 /var/run/postgresql
export POSTRIFF_PG_BIN=/usr/lib/postgresql/17/bin
python scripts/postriff_pg_suite.py postgres_creator_pipeline
fi
[[ "$mode" != backend ]] || exit 0
if [[ "$mode" == ui || "$mode" == browser ]]; then
 export POSTRIFF_PG_BIN="$(pg_config --bindir)"
 sudo install -d -m 1777 /var/run/postgresql
fi
cd web
if [[ "$mode" != browser ]]; then
node node_modules/next/dist/bin/next typegen
npm run typecheck
node --test tests/creator-pipeline.test.cjs
node node_modules/oxlint/bin/oxlint src/features/creator-pipeline src/lib/agent-runtime/creator-pipeline.ts src/features/agent/raffi-planner.tsx
fi
npm run build
node node_modules/playwright/cli.js install --with-deps chromium webkit
cd ..
mkdir -p .jcb-artifacts/creator-pipeline
browser_exit=0
python scripts/consumer_ready_browser.py --creator-pipeline --evidence-dir .jcb-artifacts/creator-pipeline || browser_exit=$?
python - <<'PY'
import base64,hashlib,json
from pathlib import Path
for p in Path('.jcb-artifacts/creator-pipeline').glob('*creator*'):
 if p.is_file() and p.stat().st_size<1024*1024:
  data=p.read_bytes();print('RAFII_CREATOR_EVIDENCE '+json.dumps({'name':p.name,'sha256':hashlib.sha256(data).hexdigest(),'base64':base64.b64encode(data).decode()}))
PY
exit "$browser_exit"
