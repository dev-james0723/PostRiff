#!/usr/bin/env bash
# Real responsive app; API fixtures explicitly synthetic. No provider/model I/O.
set -euo pipefail
if [ "${CI:-}" != true ] || [ "$(uname -s)" != Linux ]; then echo 'Use JCB cloud CI.' >&2; exit 64; fi
meta_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
meta_out="$meta_root/.jcb-artifacts/meta-browser"
mkdir -p "$meta_out"
meta_home="$(mktemp -d)"
meta_web_pid=''
cleanup() {
  meta_code=$?
  trap - EXIT
  if [ -n "$meta_web_pid" ]; then kill -TERM "$meta_web_pid" 2>/dev/null || true; wait "$meta_web_pid" 2>/dev/null || true; fi
  "$TREND_VISUAL_TEST_PYTHON" - "$meta_out" <<'PY'
import base64,hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
for name in ['results.json']+[f'meta-public-{w}.png' for w in (1440,390,320)]+[f'failure-{w}.txt' for w in (1440,390,320)]:
 p=root/name
 if p.is_file() and not p.is_symlink() and p.stat().st_size<1048576:
  d=p.read_bytes();print('RAFII_META_EVIDENCE '+json.dumps(dict(name=name,sha256=hashlib.sha256(d).hexdigest(),base64=base64.b64encode(d).decode()),separators=(',',':')))
PY
  if [ "$meta_code" -ne 0 ]; then tail -40 "$meta_out/next.log"; fi
  rm -rf -- "$meta_home"
  exit "$meta_code"
}
trap cleanup EXIT
cd "$meta_root/web"
export PLAYWRIGHT_BROWSERS_PATH="$meta_home/browsers"
node node_modules/playwright/cli.js install --with-deps chromium
env -i PATH="$PATH" HOME="$meta_home" NODE_ENV=production CI=true \
 POSTRIFF_DEV_SSR=1 POSTRIFF_API_ORIGIN=http://127.0.0.1:4438 NEXT_PUBLIC_APP_URL=http://127.0.0.1:4439 \
 NEXT_PUBLIC_SUPABASE_URL='' NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='' NEXT_TELEMETRY_DISABLED=1 \
 node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 4439 >"$meta_out/next.log" 2>&1 &
meta_web_pid=$!
"$TREND_VISUAL_TEST_PYTHON" - <<'PY'
import time,urllib.request
for _ in range(120):
 try:
  with urllib.request.urlopen('http://127.0.0.1:4439/auth/sign-in',timeout=2) as r:
   if r.status==200:break
 except OSError:pass
 time.sleep(.5)
else:raise SystemExit('Meta UI cloud readiness timeout')
PY
TREND_META_SMOKE_ONLY=1 TREND_WIDTHS=1440,390,320 TREND_WEB_URL=http://127.0.0.1:4439 \
 TREND_EVIDENCE_DIR="$meta_out" node tests/trend-browser.cjs
