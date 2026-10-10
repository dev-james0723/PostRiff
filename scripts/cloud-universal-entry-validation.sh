#!/usr/bin/env bash
# Universal Entry UI proof. Disposable identity and selected-text fixture; no model/provider calls.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Use JCB e2e; this validation cannot run on the Mac.' >&2; exit 64
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/src:$PWD/tests"
export POSTRIFF_PG_BIN="$(pg_config --bindir)"
export POSTRIFF_API_ORIGIN=http://127.0.0.1:4438 NEXT_PUBLIC_APP_URL=http://127.0.0.1:4439 POSTRIFF_DEV_SSR=1
(cd web && node node_modules/next/dist/bin/next typegen && npm run typecheck && node --test tests/universal-entry.test.cjs)
npm --prefix web run build
(cd web && node node_modules/playwright/cli.js install --with-deps chromium webkit)
mkdir -p .jcb-artifacts/universal-entry
finish() {
  code=$?
  if [ "$code" -ne 0 ]; then tail -n 50 .jcb-artifacts/universal-entry/durable-*.log 2>/dev/null || true; fi
  python - <<'PY'
import base64,hashlib,json
from pathlib import Path
root=Path('.jcb-artifacts/universal-entry')
for browser in ('chromium','webkit'):
 for name in [f'{browser}-receipt.json',f'{browser}-1440-entry.png',f'{browser}-390-entry.png']:
  path=root/name
  if path.is_file() and not path.is_symlink() and path.stat().st_size<1024*1024:
   data=path.read_bytes()
   print('RAFII_ENTRY_EVIDENCE '+json.dumps({'name':name,'sha256':hashlib.sha256(data).hexdigest(),'base64':base64.b64encode(data).decode()}),flush=True)
PY
  exit "$code"
}
trap finish EXIT
sudo -n install -d -m 1777 /var/run/postgresql
python scripts/consumer_ready_browser.py --universal-entry --evidence-dir .jcb-artifacts/universal-entry
