#!/usr/bin/env bash
# Single-use disposable Linux capacity runner; pinned Python deps, no real provider calls.
set -euo pipefail
test "$(uname -s)" = Linux
test "$CI" = true || test "$CI" = 1
test "$G5_SYNTHETIC_ONLY" = 1
test -z "$OPENAI_API_KEY" && test -z "$POSTRIFF_DATABASE_URL"
test "$(id -u)" -ne 0 || { echo 'BLOCKER: do not run PostgreSQL as OS root'; exit 64; }
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT"
test -f migrations/postriff/131_mastodon_management.sql
PG_BIN=/usr/lib/postgresql/16/bin
if [ ! -x "$PG_BIN/initdb" ] || [ ! -x "$PG_BIN/pg_ctl" ]; then
  echo 'G5_CAPACITY: ephemeral runner lacks PG16 server binaries; install PostgreSQL 16 only inside this Depot sandbox'
  sudo -n apt-get update -qq
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq install --no-install-recommends postgresql-16
fi
test -x "$PG_BIN/initdb" && test -x "$PG_BIN/pg_ctl" && test -x "$PG_BIN/psql"
VENV="$(mktemp -d /tmp/rafii-g5-capacity-venv.XXXXXXXX)"
cleanup() { rm -rf -- "$VENV"; }
trap cleanup EXIT INT TERM
python3 -m venv "$VENV/venv"
"$VENV/venv/bin/python" -m pip --disable-pip-version-check install --no-input --prefer-binary -r requirements.txt
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ROOT/src:$ROOT/tests"
export POSTRIFF_PG_BIN="$PG_BIN" POSTRIFF_RESEARCH=0 G5_SYNTHETIC_ONLY=1
echo 'G5_CAPACITY_RUN_BEGIN genuine Linux, PostgreSQL 16, synthetic transport, no real Mastodon'
"$VENV/venv/bin/python" -B scripts/postriff_pg_suite.py postgres_mastodon_scale
test -f "$ROOT/.jcb-artifacts/mastodon-capacity/CLOUD-SYNTHETIC-capacity.json"
"$VENV/venv/bin/python" - <<'PY'
import json
from pathlib import Path
p=Path('.jcb-artifacts/mastodon-capacity/CLOUD-SYNTHETIC-capacity.json')
m=json.loads(p.read_text())
assert m['simulatedConnectedUsers']==1000
assert m['completedRequests']==1000
assert m['pendingSqlOperationsPeak']==32
assert m['providerCalls']==0
assert m['realAccountAcceptance'] is False
assert m['productionHttpLoadAcceptance'] is False
assert m['queue']['distinctFairTenants']==40
print('G5_CAPACITY_ASSERTED='+json.dumps(m,sort_keys=True))
PY
echo 'G5_CAPACITY_RUN_SUCCESS (synthetic cloud PostgreSQL, not Production HTTP SLA)'
