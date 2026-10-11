#!/usr/bin/env bash
# Cloud browser proof only: real application + disposable SQL, synthetic Mastodon/identity.
set -euo pipefail
case "${CI:-}" in 1|true|TRUE) ;; *) echo 'Browser validation requires cloud CI; use JCB.' >&2; exit 64 ;; esac
if [ "$(uname -s)" != Linux ] || [ "$#" -ne 0 ]; then
  echo 'Browser validation requires Linux CI and accepts no arbitrary command.' >&2; exit 64
fi
if [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ] || [ ! -x "$TREND_VISUAL_TEST_PYTHON" ]; then
  echo 'Reuse cloud-python-bootstrap.sh pinned venv before browser validation.' >&2; exit 64
fi
jcb_yb_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
jcb_yb_pg="${POSTRIFF_PG_BIN:-}"
if [ -z "$jcb_yb_pg" ]; then
  for jcb_yb_candidate in /usr/lib/postgresql/17/bin /usr/lib/postgresql/16/bin; do
    if [ -x "$jcb_yb_candidate/initdb" ]; then jcb_yb_pg="$jcb_yb_candidate"; break; fi
  done
fi
if [ ! -x "$jcb_yb_pg/pg_ctl" ] || [ ! -f "$jcb_yb_root/web/.next/BUILD_ID" ]; then
  echo 'validation_unavailable: reuse installed PostgreSQL and completed Next build.' >&2; exit 3
fi
jcb_yb_out="$jcb_yb_root/.jcb-artifacts/mastodon-browser"
mkdir -p -- "$jcb_yb_out"
jcb_yb_home="$(mktemp -d /tmp/jcb-mastodon-browser.XXXXXXXX)"
jcb_yb_browsers="$jcb_yb_home/browsers"
if [ -d /mnt/jcb-playwright-cache ]; then jcb_yb_browsers=/mnt/jcb-playwright-cache; fi
jcb_yb_fixture_pid=''
jcb_yb_web_pid=''
cleanup() {
  jcb_yb_code=$?
  trap - EXIT INT TERM
  for jcb_yb_pid in "$jcb_yb_web_pid" "$jcb_yb_fixture_pid"; do
    if [ -n "$jcb_yb_pid" ]; then kill -TERM "$jcb_yb_pid" 2>/dev/null || true; fi
  done
  for jcb_yb_wait in {1..60}; do
    jcb_yb_alive=0
    for jcb_yb_pid in "$jcb_yb_web_pid" "$jcb_yb_fixture_pid"; do
      if [ -n "$jcb_yb_pid" ] && kill -0 "$jcb_yb_pid" 2>/dev/null; then jcb_yb_alive=1; fi
    done
    if [ "$jcb_yb_alive" -eq 0 ]; then break; fi
    sleep .25
  done
  for jcb_yb_pid in "$jcb_yb_web_pid" "$jcb_yb_fixture_pid"; do
    if [ -n "$jcb_yb_pid" ]; then
      kill -KILL "$jcb_yb_pid" 2>/dev/null || true
      wait "$jcb_yb_pid" 2>/dev/null || true
    fi
  done
  if [ "$jcb_yb_code" -ne 0 ]; then
    tail -n 60 "$jcb_yb_out/fixture.log" "$jcb_yb_out/next.log" 2>/dev/null || true
  fi
  # Preserve only explicit synthetic browser proofs as a CI artifact. Large
  # log batches can lose the final records even when Depot reports success.
  if ! node "$jcb_yb_root/scripts/cloud-mastodon-artifact.cjs" "$jcb_yb_out" "$jcb_yb_home/artifact-client" "$jcb_yb_code"; then
    if [ "$jcb_yb_code" -eq 0 ]; then jcb_yb_code=3; fi
  fi
  rm -rf -- "$jcb_yb_home"
  exit "$jcb_yb_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Fail before startup if the built rewrite targets a different service. Rebuilding
# here or silently switching to dev would make the source/build evidence ambiguous.
"$TREND_VISUAL_TEST_PYTHON" - "$jcb_yb_root" <<'PY'
import json, socket, sys
from pathlib import Path
r=Path(sys.argv[1]); expected=(r/'.python-version').read_text().strip()
actual='.'.join(str(p) for p in sys.version_info[:len(expected.split('.'))])
assert actual==expected and sys.prefix!=sys.base_prefix, 'Pinned isolated Python runtime required'
manifest=json.loads((r/'web/.next/routes-manifest.json').read_text())
rewrites=manifest.get('rewrites',{})
entries=rewrites if isinstance(rewrites,list) else sum(rewrites.values(),[])
assert any(x.get('source')=='/api/:path*' and x.get('destination')=='http://127.0.0.1:4348/api/:path*' for x in entries), 'Build with POSTRIFF_API_ORIGIN=http://127.0.0.1:4348 before this script'
for port in (4348,4448,55448):
 with socket.socket() as probe:probe.bind(('127.0.0.1',port))
PY
# Pinned client only inside the disposable cloud runner; no repository install.
npm install --prefix "$jcb_yb_home/artifact-client" --no-audit --no-fund --ignore-scripts --package-lock=false @actions/artifact@2.3.2 >"$jcb_yb_out/artifact-install.log" 2>&1
cd -- "$jcb_yb_root/web"
env -i PATH="$PATH" HOME="$jcb_yb_home" TMPDIR=/tmp CI=true \
  PLAYWRIGHT_BROWSERS_PATH="$jcb_yb_browsers" \
  node node_modules/playwright/cli.js install --with-deps chromium

env -i PATH="$PATH" HOME="$jcb_yb_home" TMPDIR=/tmp CI=true LC_ALL=C \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$jcb_yb_root/src:$jcb_yb_root/tests" \
  POSTRIFF_PG_BIN="$jcb_yb_pg" POSTRIFF_RESEARCH=0 POSTRIFF_DEV_WEB_ORIGIN=http://127.0.0.1:4448 \
  PGUSER=postriff_test PGHOST=127.0.0.1 PGPORT=55448 PGDATABASE=postgres \
  PGCONNECT_TIMEOUT=5 PGPASSFILE=/dev/null PGSERVICEFILE=/dev/null \
  "$TREND_VISUAL_TEST_PYTHON" "$jcb_yb_root/tests/phase2/mastodon_queue_browser_fixture.py" --port 4348 --pg-port 55448 \
  >"$jcb_yb_out/fixture.log" 2>&1 &
jcb_yb_fixture_pid=$!
env -i PATH="$PATH" HOME="$jcb_yb_home" TMPDIR=/tmp CI=true NODE_ENV=production \
  POSTRIFF_API_ORIGIN=http://127.0.0.1:4348 POSTRIFF_DEV_SSR=1 \
  NEXT_PUBLIC_APP_URL=http://127.0.0.1:4448 NEXT_PUBLIC_SUPABASE_URL='' NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='' \
  NEXT_PUBLIC_SENTRY_DISABLED=1 NEXT_TELEMETRY_DISABLED=1 \
  node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 4448 \
  >"$jcb_yb_out/next.log" 2>&1 &
jcb_yb_web_pid=$!
"$TREND_VISUAL_TEST_PYTHON" - "$jcb_yb_fixture_pid" "$jcb_yb_web_pid" <<'PY'
import os, sys, time, urllib.request
from pathlib import Path
pids=[int(value) for value in sys.argv[1:]]
deadline=time.monotonic()+120
for url in ('http://127.0.0.1:4348/api/health','http://127.0.0.1:4448/api/health','http://127.0.0.1:4448/auth/sign-in'):
 while True:
  for pid in pids:
   try:
    os.kill(pid,0)
    if Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]=='Z':
     raise ProcessLookupError
   except (ProcessLookupError,FileNotFoundError):
    raise SystemExit('validation_unavailable: owned browser fixture process exited before readiness')
  try:
   with urllib.request.urlopen(url,timeout=2) as response:
    if response.status==200:break
  except (OSError,TimeoutError):pass
  if time.monotonic()>=deadline:raise SystemExit('validation_unavailable: browser fixture readiness deadline exceeded')
  time.sleep(.5)
print('Cloud loopback browser fixtures ready; synthetic Mastodon only',flush=True)
PY
env -i PATH="$PATH" HOME="$jcb_yb_home" TMPDIR=/tmp CI=true \
  PLAYWRIGHT_BROWSERS_PATH="$jcb_yb_browsers" MASTODON_WEB_URL=http://127.0.0.1:4448 \
  MASTODON_BROWSER_EVIDENCE_DIR="$jcb_yb_out" \
  node "$jcb_yb_root/web/tests/mastodon-account-browser.cjs"
env -i PATH="$PATH" HOME="$jcb_yb_home" TMPDIR=/tmp CI=true \
  PLAYWRIGHT_BROWSERS_PATH="$jcb_yb_browsers" MASTODON_BROWSER_EVIDENCE_DIR="$jcb_yb_out" \
  node "$jcb_yb_root/web/tests/mastodon-queue-browser.cjs"
echo "Cloud synthetic browser evidence: $jcb_yb_out"
