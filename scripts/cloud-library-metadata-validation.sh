#!/usr/bin/env bash
# Synthetic disposable database and real native UI, cloud only; no provider/account credentials.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ] || [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ]; then
  echo 'Use JCB through cloud-python-bootstrap.sh.' >&2; exit 64
fi
case "${1:---core}" in --core|--browser|--all) ;; *) exit 64 ;; esac
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/src:$PWD/tests" PYTHONDONTWRITEBYTECODE=1 POSTRIFF_RESEARCH=0
if ! command -v pg_config >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
fi
export POSTRIFF_PG_BIN="$(pg_config --bindir)"
sudo -n install -d -m 1777 /var/run/postgresql
if [ "${1:---core}" != --browser ]; then
  python scripts/postriff_pg_suite.py postgres_library_metadata
fi
(cd web && node node_modules/next/dist/bin/next typegen && npm run typecheck && npm run lint)
if [ "${1:---core}" != --core ]; then
  npm --prefix web run build
  (cd web && node node_modules/playwright/cli.js install --with-deps chromium webkit)
  mkdir -p .jcb-artifacts/library-metadata
  finish() {
    code=$?
    if [ "$code" -ne 0 ]; then tail -n 50 .jcb-artifacts/library-metadata/durable-*.log 2>/dev/null || true; fi
    python - <<'PY'
import base64,hashlib,json
from pathlib import Path
root=Path('.jcb-artifacts/library-metadata')
names=['browser-receipt.json']+[f'{browser}-{width}-{step}.png' for browser in ('chromium','webkit') for width in (1440,390) for step in ('preview','undo-conflict')]
for name in names:
 path=root/name
 if path.is_file() and not path.is_symlink() and path.stat().st_size<1024*1024:
  raw=path.read_bytes()
  print('LIBRARY_METADATA_EVIDENCE '+json.dumps({'name':name,'sha256':hashlib.sha256(raw).hexdigest(),'base64':base64.b64encode(raw).decode()}),flush=True)
PY
    exit "$code"
  }
  trap finish EXIT
  python scripts/consumer_ready_browser.py --library-metadata --evidence-dir .jcb-artifacts/library-metadata
fi
