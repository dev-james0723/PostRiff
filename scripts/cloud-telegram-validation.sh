#!/usr/bin/env bash
# Synthetic provider checks only. Real Telegram acceptance remains a release gate.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Telegram validation requires cloud Linux CI.' >&2; exit 64
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/src:$PWD/tests" PYTHONDONTWRITEBYTECODE=1
export NEXT_PUBLIC_APP_URL=http://127.0.0.1:4439 POSTRIFF_API_ORIGIN=http://127.0.0.1:4438 POSTRIFF_DEV_SSR=1
mkdir -p .jcb-artifacts/telegram
mode="${1:-all}"
case "$mode" in all|backend|frontend) ;; *) exit 64 ;; esac
if [ "$mode" != frontend ]; then
python3 scripts/check_social_release_binding.py
python3 -m unittest test_social_release_binding test_consumer_deployment test_telegram_capabilities test_telegram_login test_telegram_agent test_hosted_wave1_connectors test_postriff_phase2 test_postriff_phase2_hosted test_hosted_wave3_connectors test_wave4_hosted_publish test_agent_permissions_surfaces test_agent_runtime_references test_hosted_storage_library
if ! command -v pg_config >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq install postgresql
fi
export POSTRIFF_PG_BIN="$(pg_config --bindir)"
python3 tests/phase2/postgres_telegram.py
fi
if [ "$mode" != backend ]; then
# Isolate generated output from the shared framework cache used by other refs.
# This stays inside the disposable cloud checkout; no shared cache is deleted.
export POSTRIFF_DIST_DIR=.next-telegram-ci
(cd web && node node_modules/next/dist/bin/next typegen && npm run typecheck && npm run lint && npm run build)
(cd web && node node_modules/playwright/cli.js install --with-deps chromium)
web_process=''
cleanup() { if [ -n "$web_process" ]; then kill "$web_process" 2>/dev/null || true; fi; }
trap cleanup EXIT
(cd web && node node_modules/next/dist/bin/next start -H 127.0.0.1 -p 4439) >.jcb-artifacts/telegram/web.log 2>&1 &
web_process=$!
python3 - <<'PYWAIT'
import time,urllib.request
for _ in range(60):
 try:
  urllib.request.urlopen('http://127.0.0.1:4439',timeout=2);break
 except Exception:time.sleep(1)
else:raise SystemExit('Cloud web harness did not become ready')
PYWAIT
TELEGRAM_WEB_URL=http://127.0.0.1:4439 TELEGRAM_EVIDENCE_DIR="$PWD/.jcb-artifacts/telegram" node web/tests/telegram-browser.cjs
fi

# Preserve only explicit synthetic evidence through the existing private CI log.
# No credential, workspace export or real Telegram message body is included.
python3 - <<'PYEVIDENCE'
import base64,io,json,zipfile
from pathlib import Path
root=Path('.jcb-artifacts/telegram')
for name in ('postgres-tests.json','load-tests.json','browser-tests.json'):
 if (root/name).is_file():print('TELEGRAM_RESULT '+name+' '+(root/name).read_text().replace('\n',''))
buffer=io.BytesIO()
with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
 for path in root.iterdir():
  if path.suffix in ('.json','.png'):archive.writestr(path.name,path.read_bytes())
if len(buffer.getvalue())>2000000:raise SystemExit('Synthetic evidence export exceeds bounded size')
print('TELEGRAM_SYNTHETIC_EVIDENCE_ZIP '+base64.b64encode(buffer.getvalue()).decode())
PYEVIDENCE
