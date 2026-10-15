#!/usr/bin/env bash
# Content Skills A32 cloud browser proof: real application + disposable SQL, synthetic identity; Facebook wave on, GenUI default.
set -euo pipefail
case "${CI:-}" in 1|true|TRUE) ;; *) echo 'Browser validation requires cloud CI; use JCB.' >&2; exit 64 ;; esac
if [ "$(uname -s)" != Linux ] || [ "$#" -ne 0 ]; then
  echo 'Browser validation requires Linux CI and accepts no arbitrary command.' >&2; exit 64
fi
if [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ] || [ ! -x "$TREND_VISUAL_TEST_PYTHON" ]; then
  echo 'Reuse cloud-python-bootstrap.sh pinned venv before browser validation.' >&2; exit 64
fi
jcb_cs_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
jcb_cs_pg="${POSTRIFF_PG_BIN:-}"
if [ -z "$jcb_cs_pg" ]; then
  for jcb_cs_candidate in /usr/lib/postgresql/17/bin /usr/lib/postgresql/16/bin; do
    if [ -x "$jcb_cs_candidate/initdb" ]; then jcb_cs_pg="$jcb_cs_candidate"; break; fi
  done
fi
if [ ! -x "$jcb_cs_pg/pg_ctl" ] || [ ! -f "$jcb_cs_root/web/.next/BUILD_ID" ]; then
  echo 'validation_unavailable: reuse installed PostgreSQL and completed Next build.' >&2; exit 3
fi
jcb_cs_out="$jcb_cs_root/.jcb-artifacts/content-skills-browser"
mkdir -p -- "$jcb_cs_out"
jcb_cs_home="$(mktemp -d /tmp/jcb-content-skills-browser.XXXXXXXX)"
jcb_cs_browsers="$jcb_cs_home/browsers"
if [ -d /mnt/jcb-playwright-cache ]; then jcb_cs_browsers=/mnt/jcb-playwright-cache; fi
jcb_cs_fixture_pid=''
jcb_cs_web_pid=''
cleanup() {
  jcb_cs_code=$?
  trap - EXIT INT TERM
  for jcb_cs_pid in "$jcb_cs_web_pid" "$jcb_cs_fixture_pid"; do
    if [ -n "$jcb_cs_pid" ]; then kill -TERM "$jcb_cs_pid" 2>/dev/null || true; fi
  done
  for jcb_cs_wait in {1..60}; do
    jcb_cs_alive=0
    for jcb_cs_pid in "$jcb_cs_web_pid" "$jcb_cs_fixture_pid"; do
      if [ -n "$jcb_cs_pid" ] && kill -0 "$jcb_cs_pid" 2>/dev/null; then jcb_cs_alive=1; fi
    done
    if [ "$jcb_cs_alive" -eq 0 ]; then break; fi
    sleep .25
  done
  for jcb_cs_pid in "$jcb_cs_web_pid" "$jcb_cs_fixture_pid"; do
    if [ -n "$jcb_cs_pid" ]; then
      kill -KILL "$jcb_cs_pid" 2>/dev/null || true
      wait "$jcb_cs_pid" 2>/dev/null || true
    fi
  done
  if [ "$jcb_cs_code" -ne 0 ]; then
    tail -n 60 "$jcb_cs_out/fixture.log" "$jcb_cs_out/next.log" 2>/dev/null || true
  fi
  # JCB retains runner logs but currently has no artifact-export adapter. Emit
  # only bounded, known synthetic proof files so the controller can recover
  # screenshots without uploading any local credentials or arbitrary files.
  "$TREND_VISUAL_TEST_PYTHON" - "$jcb_cs_out" <<'PY'
import base64, hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
names = ['CLOUD-SYNTHETIC-content-skills.json'] + [f'CLOUD-SYNTHETIC-{kind}-{w}.png' for kind in ('composer', 'review') for w in (1440, 390)]
for name in names:
    path = root / name
    if path.is_file() and not path.is_symlink() and path.stat().st_size <= 1024 * 1024:
        data = path.read_bytes()
        print('RAFII_CONTENT_SKILLS_EVIDENCE ' + json.dumps({'name': name, 'sha256': hashlib.sha256(data).hexdigest(), 'base64': base64.b64encode(data).decode('ascii')}, separators=(',', ':')), flush=True)
PY
  rm -rf -- "$jcb_cs_home"
  exit "$jcb_cs_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Fail before startup if the built rewrite targets a different service. Rebuilding
# here or silently switching to dev would make the source/build evidence ambiguous.
"$TREND_VISUAL_TEST_PYTHON" - "$jcb_cs_root" <<'PY'
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
cd -- "$jcb_cs_root/web"
env -i PATH="$PATH" HOME="$jcb_cs_home" TMPDIR=/tmp CI=true \
  PLAYWRIGHT_BROWSERS_PATH="$jcb_cs_browsers" \
  node node_modules/playwright/cli.js install --with-deps chromium

env -i PATH="$PATH" HOME="$jcb_cs_home" TMPDIR=/tmp CI=true LC_ALL=C \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$jcb_cs_root/src:$jcb_cs_root/tests" \
  POSTRIFF_PG_BIN="$jcb_cs_pg" POSTRIFF_RESEARCH=0 POSTRIFF_DEV_WEB_ORIGIN=http://127.0.0.1:4448 \
  RAFII_CREATION_PROJECTION_ENABLED=1 \
  PGUSER=postriff_test PGHOST=127.0.0.1 PGPORT=55448 PGDATABASE=postgres \
  PGCONNECT_TIMEOUT=5 PGPASSFILE=/dev/null PGSERVICEFILE=/dev/null \
  "$TREND_VISUAL_TEST_PYTHON" "$jcb_cs_root/tests/phase2/youtube_browser_fixture.py" --port 4348 --pg-port 55448 \
  >"$jcb_cs_out/fixture.log" 2>&1 &
jcb_cs_fixture_pid=$!
env -i PATH="$PATH" HOME="$jcb_cs_home" TMPDIR=/tmp CI=true NODE_ENV=production \
  POSTRIFF_API_ORIGIN=http://127.0.0.1:4348 POSTRIFF_DEV_SSR=1 \
  NEXT_PUBLIC_APP_URL=http://127.0.0.1:4448 NEXT_PUBLIC_SUPABASE_URL='' NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='' \
  NEXT_PUBLIC_SENTRY_DISABLED=1 NEXT_TELEMETRY_DISABLED=1 \
  node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 4448 \
  >"$jcb_cs_out/next.log" 2>&1 &
jcb_cs_web_pid=$!
"$TREND_VISUAL_TEST_PYTHON" - "$jcb_cs_fixture_pid" "$jcb_cs_web_pid" <<'PY'
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
print('Cloud loopback browser fixtures ready; synthetic Google only',flush=True)
PY
env -i PATH="$PATH" HOME="$jcb_cs_home" TMPDIR=/tmp CI=true \
  PLAYWRIGHT_BROWSERS_PATH="$jcb_cs_browsers" CONTENT_SKILLS_WEB_URL=http://127.0.0.1:4448 \
  CONTENT_SKILLS_EVIDENCE_DIR="$jcb_cs_out" \
  node "$jcb_cs_root/web/tests/content-skills-browser.cjs"
echo "Cloud synthetic content-skills browser evidence: $jcb_cs_out"
