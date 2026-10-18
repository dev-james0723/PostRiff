#!/usr/bin/env bash
# Scoped merged-source preflight only. Never a capacity or deployment route.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ] || [ "$#" -ne 0 ]; then
  echo 'Use the reviewed non-deploy cloud integration route without stage arguments.' >&2
  exit 64
fi
integrated_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$integrated_root"
export PYTHONDONTWRITEBYTECODE=1 RAFII_DISCORD_SYNTHETIC_FENCE=1
export PYTHONPATH="$integrated_root/scripts/linkedin_test_fence:$integrated_root/src:$integrated_root/tests"
export POSTRIFF_PG_BIN=/usr/lib/postgresql/17/bin
python -c 'import sitecustomize; sitecustomize.self_check()'
mkdir -p .depot

integrated_sources() {
  python - "$1" <<'PY_SOURCE'
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path('scripts').resolve()))
from discord_capacity_sources import source_paths
root=Path.cwd()
files={}
for name in source_paths(root):
    p=root/name
    assert p.is_file() and not p.is_symlink(), name
    files[name]=hashlib.sha256(p.read_bytes()).hexdigest()
raw=json.dumps({'files':files,'criticalSourceCount':len(files)},sort_keys=True,separators=(',',':')).encode()
phase=sys.argv[1]
assert phase in ('before','after')
Path('.depot/discord-integrated-source-'+phase+'.json').write_bytes(raw)
text=raw.decode()
parts=[text[i:i+2500] for i in range(0,len(text),2500)]
for index,part in enumerate(parts):
    print('RAFII_DISCORD_INTEGRATED_SOURCE '+json.dumps({'phase':phase,'index':index,'parts':len(parts),'sha256':hashlib.sha256(raw).hexdigest(),'text':part}),flush=True)
PY_SOURCE
}

integrated_gate() {
  local gate="$1" result=0
  shift
  "$@" || result=$?
  printf 'RAFII_DISCORD_INTEGRATED_GATE {"gate":"%s","exitCode":%d}\n' "$gate" "$result"
  return "$result"
}

integrated_sources before
integrated_gate additional-python python -m unittest \
  test_discord_engagement test_postriff_pg_suite_controls \
  test_pinterest_analytics test_pinterest_trial_readiness test_pinterest_trial_evidence \
  test_pinterest_pilot test_pinterest_production_prep test_growth_metric_schedule \
  test_connection_health test_postriff_phase2_hosted
# The unchanged focused module list and old SQL chain execute once. The new
# engagement SQL fixture also has its own guarded owned-cluster invocation.
integrated_gate discord-p0-p4 bash scripts/discord-p4-validation-cloud.sh
# Keep the unchanged strict fence and exact postriff_test role/environment.
# Each preserved fixture still gets its own fresh disposable cluster.
integrated_gate preserved-growth-sql python scripts/postriff_disposable_postgres.py tests/phase2/postgres_growth_metric_reads.py
integrated_gate preserved-pinterest-sql python scripts/postriff_disposable_postgres.py tests/phase2/postgres_pinterest.py
python tests/discord_engagement_ui_fixture.py .depot/discord-engagement-ui.json
cd web
integrated_gate web-contracts node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs
integrated_gate types npm run typecheck
integrated_gate lint npm run lint
integrated_gate build npm run build
integrated_gate discord-browser bash ../scripts/discord-browser-cloud.sh
integrated_gate engagement-browser node tests/discord-engagement-browser.cjs
cd ..
integrated_sources after
printf 'RAFII_DISCORD_INTEGRATED_SCOPED_PASS synthetic provider and disposable SQL only; no capacity or deployment\n'
