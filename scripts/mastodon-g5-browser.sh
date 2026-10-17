#!/usr/bin/env bash
# Genuine Linux Chromium and WebKit E2E with synthetic local Mastodon provider.
# Scoped 20-minute Depot sandbox, no real OAuth, provider traffic or hosted DB.
set -euo pipefail
test "$(uname -s)" = Linux
test "$CI" = true || test "$CI" = 1
test "$G5_SYNTHETIC_ONLY" = 1
test -z "$OPENAI_API_KEY" && test -z "$POSTRIFF_DATABASE_URL"
test "$POSTRIFF_API_ORIGIN" = "http://127.0.0.1:4348"
test "$NEXT_PUBLIC_APP_URL" = "http://127.0.0.1:4448"
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT"
test -f tests/phase2/mastodon_queue_browser_fixture.py
test -f migrations/postriff/131_mastodon_management.sql
test "$(node -v)" = v24.15.0
PG_BIN=/usr/lib/postgresql/16/bin
if [ ! -x "$PG_BIN/initdb" ] || [ ! -x "$PG_BIN/pg_ctl" ]; then
  echo 'G5_BROWSER: provisioning PG16 server binaries in disposable Depot sandbox only'
  sudo -n apt-get update -qq
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq install --no-install-recommends postgresql-16
fi
test -x "$PG_BIN/initdb" && test -x "$PG_BIN/pg_ctl"
if ! command -v ffmpeg >/dev/null 2>&1; then
  sudo -n apt-get update -qq
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq install --no-install-recommends ffmpeg
fi
TASK_HOME="$(mktemp -d /tmp/rafii-g5-browser.XXXXXXXX)"
API_PID=''
WEB_PID=''
cleanup() {
  result=$?
  trap - EXIT INT TERM
  for pid in "$WEB_PID" "$API_PID"; do
    if [ -n "$pid" ]; then kill -TERM "$pid" 2>/dev/null || true; fi
  done
  sleep 1
  for pid in "$WEB_PID" "$API_PID"; do
    if [ -n "$pid" ]; then
      kill -KILL "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  if [ "$result" -ne 0 ]; then
    echo 'G5_BROWSER_ERROR: last synthetic fixture and Next logs'
    tail -n 35 "$TASK_HOME/fixture.log" "$TASK_HOME/next.log" 2>/dev/null || true
  fi
  rm -rf -- "$TASK_HOME"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ROOT/src:$ROOT/tests"
export POSTRIFF_PG_BIN="$PG_BIN" POSTRIFF_RESEARCH=0
export NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_SENTRY_DISABLED=true
export NEXT_PUBLIC_SUPABASE_URL='' NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=''
export POSTRIFF_DEV_WEB_ORIGIN=http://127.0.0.1:4448
export PLAYWRIGHT_BROWSERS_PATH="$TASK_HOME/browsers"
export TREND_VISUAL_TEST_PYTHON="$TASK_HOME/venv/bin/python"
echo 'G5_BROWSER_PREP: install pinned dependencies only inside disposable Depot runner'
python3 -m venv "$TASK_HOME/venv"
"$TREND_VISUAL_TEST_PYTHON" -m pip --disable-pip-version-check install --no-input --prefer-binary -r requirements.txt
cd "$ROOT/web"
npm ci --no-audit --no-fund
node node_modules/playwright/cli.js install --with-deps chromium webkit
test -d "$PLAYWRIGHT_BROWSERS_PATH"
node node_modules/next/dist/bin/next build
test -f .next/BUILD_ID
cd "$ROOT"
python3 - <<'PY'
import socket
for port in (4348,4448,55448):
 with socket.socket() as s:
  s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
  s.bind(('127.0.0.1',port))
print('G5_BROWSER_LOCALHOST_PORTS_CLEAR=true')
PY
"$TREND_VISUAL_TEST_PYTHON" "$ROOT/tests/phase2/mastodon_queue_browser_fixture.py" --port 4348 --pg-port 55448 > "$TASK_HOME/fixture.log" 2>&1 &
API_PID=$!
(
  cd "$ROOT/web"
  node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 4448
) > "$TASK_HOME/next.log" 2>&1 &
WEB_PID=$!
"$TREND_VISUAL_TEST_PYTHON" - "$API_PID" "$WEB_PID" <<'PY'
import os,sys,time,urllib.request
from pathlib import Path
pids=[int(x) for x in sys.argv[1:]]
for url in ('http://127.0.0.1:4348/api/health','http://127.0.0.1:4448/api/health','http://127.0.0.1:4448/auth/sign-in'):
 limit=time.monotonic()+65
 while True:
  for pid in pids:
   try:
    os.kill(pid,0)
    s=Path(f'/proc/{pid}/stat')
    if s.exists() and s.read_text().rsplit(')',1)[1].split()[0]=='Z':raise ProcessLookupError()
   except ProcessLookupError:raise SystemExit('Owned test fixture exited during readiness.')
  try:
   with urllib.request.urlopen(url,timeout=2) as response:
    if response.status==200:break
  except (OSError,TimeoutError):pass
  if time.monotonic()>=limit:raise SystemExit('Local fixture readiness timed out: '+url)
  time.sleep(.5)
print('G5_BROWSER_LOCAL_SYNTHETIC_FIXTURES_READY=true')
PY
cd "$ROOT/web"
for engine in chromium webkit; do
  export MASTODON_BROWSER_ENGINE="$engine"
  export MASTODON_BROWSER_EVIDENCE_DIR="$TASK_HOME/evidence-$engine"
  mkdir -p "$MASTODON_BROWSER_EVIDENCE_DIR"
  echo "G5_BROWSER_ENGINE=$engine BEGIN"
  node tests/mastodon-account-browser.cjs
  node tests/mastodon-queue-browser.cjs
  node - "$MASTODON_BROWSER_EVIDENCE_DIR" "$engine" <<'JS'
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const dir=process.argv[2],engine=process.argv[3];
const p=path.join(dir,'CLOUD-SYNTHETIC-browser.json');
const result=JSON.parse(fs.readFileSync(p,'utf8'));
if(result.status!=='PASS'||result.checks.length!==3||result.queueChecks?.length!==3||result.realMastodonAcceptance!==false)throw Error('Missing full synthetic browser evidence');
const pictures=fs.readdirSync(dir).filter(n=>n.endsWith('.png')).sort();
console.log('G5_BROWSER_RESULT='+JSON.stringify({engine,status:result.status,accountViewports:result.checks.map(x=>x.width),queueViewports:result.queueChecks.map(x=>x.width),evidenceScreenshots:pictures.length,receiptSha256:crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex'),realMastodonAcceptance:false,productionAcceptance:false}));
JS
done
echo 'G5_BROWSER_BOTH_ENGINES_SUCCESS; no real Mastodon/provider/production calls'
