#!/usr/bin/env bash
# Cloud-only, synthetic data and identities. No production activation or provider/model requests.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ] || [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ]; then
  echo 'Use JCB through cloud-python-bootstrap.sh.' >&2; exit 64
fi
case "${1:---core}" in --core|--browser|--browser-only|--all) ;; *) exit 64 ;; esac
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/src:$PWD/tests" PYTHONDONTWRITEBYTECODE=1 POSTRIFF_RESEARCH=0
if ! command -v pg_config >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
fi
export POSTRIFF_PG_BIN="$(pg_config --bindir)"
sudo -n install -d -m 1777 /var/run/postgresql
validation_failed=0
if [ "${1:---core}" = --core ] || [ "${1:---core}" = --all ]; then
  python -m unittest discover -s tests -p 'test_workflow_recipes.py' || validation_failed=1
  python -m unittest discover -s tests -p 'test_agent_capability_registry.py' || validation_failed=1
  python -m unittest test_agent_runtime.GateTest.test_voice_never_gains_more_than_text || validation_failed=1
  python scripts/postriff_pg_suite.py postgres_workflow_recipes || validation_failed=1
fi
if [ "${1:---core}" = --browser ] || [ "${1:---core}" = --all ]; then
  (cd web && node node_modules/next/dist/bin/next typegen && npm run typecheck && npm run lint && node --test tests/agent-tasks.test.cjs) || validation_failed=1
fi
if [ "$validation_failed" -ne 0 ]; then exit "$validation_failed"; fi
if [ "${1:---core}" != --core ]; then
  test -f skills/rafii-registry.json || { echo 'Missing tracked product registry required by coworker/status.' >&2; exit 64; }
  npm --prefix web run build
  (cd web && node node_modules/playwright/cli.js install --with-deps chromium webkit)
  mkdir -p .jcb-artifacts/workflow-recipes
  finish() {
    code=$?
    if [ "$code" -ne 0 ]; then tail -n 50 .jcb-artifacts/workflow-recipes/durable-*.log 2>/dev/null || true; fi
    python - <<'PY'
import base64,hashlib,json
from pathlib import Path
root=Path('.jcb-artifacts/workflow-recipes')
names=['browser-receipt.json','browser-failure.json','browser-failure.png']+[f'{browser}-{width}-report.png' for browser in ('chromium','webkit') for width in (1440,390)]
for name in names:
 path=root/name
 if path.is_file() and not path.is_symlink() and path.stat().st_size<1024*1024:
  raw=path.read_bytes()
  print('WORKFLOW_RECIPE_EVIDENCE '+json.dumps({'name':name,'sha256':hashlib.sha256(raw).hexdigest(),'base64':base64.b64encode(raw).decode()}),flush=True)
PY
    exit "$code"
  }
  trap finish EXIT
  python scripts/consumer_ready_browser.py --workflow-recipes --evidence-dir .jcb-artifacts/workflow-recipes
fi
