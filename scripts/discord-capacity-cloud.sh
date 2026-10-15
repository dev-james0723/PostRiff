#!/usr/bin/env bash
# Authorized synthetic cloud validation; human mission authority is recorded.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Discord capacity requires approved JCB/Depot Linux CI; no local fallback.' >&2
  exit 64
fi
if [ "$#" -ne 1 ]; then
  echo 'Explicit --stage-a, --stage-b, --connection-diagnostic or --coordinator-qualification required.' >&2
  exit 64
fi
discord_coordinator_qualification=0
discord_owned_deadline=43m
case "$1" in
  --stage-a) export RAFII_DISCORD_CAPACITY_STAGE=a ;;
  --stage-a-workers16-v3)
    export RAFII_DISCORD_CAPACITY_STAGE=a
    export RAFII_DISCORD_CAPACITY_RESOURCE_PLAN=workers16-v3 ;;
  --pipeline-workers16-v3)
    export RAFII_DISCORD_CAPACITY_STAGE=pipeline-qualification
    export RAFII_DISCORD_CAPACITY_RESOURCE_PLAN=workers16-v3
    discord_coordinator_qualification=1
    discord_owned_deadline=9m ;;
  --burst-workers16-v3)
    export RAFII_DISCORD_CAPACITY_STAGE=burst-diagnostic
    export RAFII_DISCORD_CAPACITY_RESOURCE_PLAN=workers16-v3
    discord_coordinator_qualification=1
    discord_owned_deadline=21m ;;
  --pipeline-qualification)
    export RAFII_DISCORD_CAPACITY_STAGE=pipeline-qualification
    # The caller must retain same-source backend/SQL qualification. Combined
    # CI runs it first, then uses this new owned cluster for pipeline safety.
    discord_owned_deadline=9m ;;
  --pipeline-coordinator-qualification)
    export RAFII_DISCORD_CAPACITY_STAGE=pipeline-qualification
    discord_coordinator_qualification=1
    discord_owned_deadline=9m ;;
  --burst-coordinator-qualification)
    export RAFII_DISCORD_CAPACITY_STAGE=burst-diagnostic
    discord_coordinator_qualification=1
    discord_owned_deadline=21m ;;
  --stage-b) export RAFII_DISCORD_CAPACITY_STAGE=b ;;
  --stage-b-extended-v2)
    export RAFII_DISCORD_CAPACITY_STAGE=b
    export RAFII_DISCORD_CAPACITY_RESOURCE_PLAN=b-extended-v2
    discord_coordinator_qualification=1
    discord_owned_deadline=201m ;;
  --stage-b-workers16-v3)
    export RAFII_DISCORD_CAPACITY_STAGE=b
    export RAFII_DISCORD_CAPACITY_RESOURCE_PLAN=b-extended-workers16-v3
    discord_coordinator_qualification=1
    discord_owned_deadline=201m ;;
  --connection-diagnostic) export RAFII_DISCORD_CAPACITY_STAGE=connection-diagnostic ;;
  --coordinator-qualification)
    export RAFII_DISCORD_CAPACITY_STAGE=connection-diagnostic
    discord_coordinator_qualification=1
    discord_owned_deadline=10m ;;
  *) exit 64 ;;
esac
discord_capacity_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$discord_capacity_root"
discord_capacity_emit_evidence() {
  python - "$@" <<'PY'
from pathlib import Path
import hashlib
import json
import sys
root = Path.cwd()
allowed = {'discord-p4-coordinator-results.json', 'discord-capacity-results.json', 'discord-capacity-events.jsonl'}
for name in sys.argv[1:]:
    if name not in allowed:
        raise SystemExit(64)
    path = root / '.depot' / name
    if not path.is_file():
        print('RAFII_DISCORD_CAPACITY_EVIDENCE ' + json.dumps({'file': name, 'status': 'MISSING'}), flush=True)
        continue
    raw = path.read_bytes()
    data = raw.decode()
    parts = [data[i:i + 2500] for i in range(0, len(data), 2500)]
    for index, part in enumerate(parts):
        print('RAFII_DISCORD_CAPACITY_EVIDENCE ' + json.dumps({'file': name, 'index': index,
              'parts': len(parts), 'sha256': hashlib.sha256(raw).hexdigest(), 'text': part}), flush=True)
PY

}

discord_assert_owned_stopped() {
  # Fail closed on any listener; never stop a server this runner did not own.
  python - <<'PY'
import json
import socket
with socket.socket() as probe:
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    probe.bind(('127.0.0.1', 55438))
print('RAFII_DISCORD_COORDINATOR_GATE ' + json.dumps({'gate': 'owned-port-released', 'status': 'PASS'}), flush=True)
PY
}
# Inert profile arithmetic BEFORE PostgreSQL installation/initialization. A
# blocked StageB resource plan must not create a load fixture or truncate time.
PYTHONPATH="$discord_capacity_root/tests" python - <<'PY'
import json
import os
from phase2.postgres_discord_capacity import budget_lower_bound, connection_diagnostic_profile, fingerprint, profile, selected_profile
stage = os.environ['RAFII_DISCORD_CAPACITY_STAGE']
p = connection_diagnostic_profile() if stage == 'connection-diagnostic' else selected_profile(stage)
result = {'status': 'PASS', 'meaning': 'connection diagnostic only; capacity NOT_RUN'} if stage == 'connection-diagnostic' else budget_lower_bound(p)
print('RAFII_DISCORD_CAPACITY_PREFLIGHT ' + json.dumps({'stage': p['stage'], 'profileSha256': fingerprint(p), **result}), flush=True)
if result['status'] == 'BLOCKED':
    raise SystemExit(64)
PY
discord_pg_bin=/usr/lib/postgresql/17/bin
if [ ! -x "$discord_pg_bin/postgres" ]; then
  # Same qualified PGDG17 setup as the existing P4 wrapper. Run in the
  # authorized ephemeral cloud executor, never install a local/default DB.
  discord_pg_suite="$(. /etc/os-release; printf '%s' "$VERSION_CODENAME")"
  discord_pg_arch="$(dpkg --print-architecture)"
  case "$discord_pg_suite:$discord_pg_arch" in noble:amd64|noble:arm64|jammy:amd64|jammy:arm64) ;; *) exit 64 ;; esac
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq --no-install-recommends install curl ca-certificates postgresql-common
  sudo -n install -d /usr/share/postgresql-common/pgdg
  sudo -n curl --proto '=https' --tlsv1.2 --fail --silent --show-error \
    https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
  printf 'Types: deb\nURIs: https://apt.postgresql.org/pub/repos/apt\nSuites: %s-pgdg\nArchitectures: %s\nComponents: main\nSigned-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc\n' \
    "$discord_pg_suite" "$discord_pg_arch" | sudo -n tee /etc/apt/sources.list.d/pgdg.sources >/dev/null
  printf '\ncreate_main_cluster = false\n' | sudo -n tee -a /etc/postgresql-common/createcluster.conf >/dev/null
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq --no-install-recommends install postgresql-17
fi
case "$("$discord_pg_bin/postgres" --version)" in 'postgres (PostgreSQL) 17.'*) ;; *) exit 64 ;; esac
export POSTRIFF_PG_BIN="$discord_pg_bin"
export RAFII_DISCORD_SYNTHETIC_FENCE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$discord_capacity_root/scripts/linkedin_test_fence:$discord_capacity_root/src:$discord_capacity_root/tests"
python -c 'import sitecustomize; sitecustomize.self_check()'
if [ "$discord_coordinator_qualification" -eq 1 ]; then
  discord_qualification_exit=0
  python -m unittest test_discord_rate_limits test_discord_worker_lifecycle \
    test_discord_oauth_lifecycle test_discord_destinations test_discord_publish_authorization \
    test_discord_capacity_controls test_discord_presend_retry test_postgres_pool_controls test_discord_capacity_approval_receipt test_rafii_account_holds \
    test_founder_product_events test_youtube_fleet || discord_qualification_exit=$?
  printf 'RAFII_DISCORD_COORDINATOR_GATE {"gate":"offline-python","exitCode":%d}\n' "$discord_qualification_exit"
  if [ "$discord_qualification_exit" -ne 0 ]; then exit "$discord_qualification_exit"; fi
  # First owned cluster: existing P0-P3 chain ONCE, then actual P4 regression
  # groups. A failed backend gate stops before the unchanged32-user diagnostic.
  timeout --signal=TERM --kill-after=60s 15m \
    python scripts/postriff_disposable_postgres.py tests/phase2/postgres_discord_rate_limits.py \
    || discord_qualification_exit=$?
  discord_capacity_emit_evidence discord-p4-coordinator-results.json
  printf 'RAFII_DISCORD_COORDINATOR_GATE {"gate":"owned-postgres-p0-p4","exitCode":%d}\n' "$discord_qualification_exit"
  if [ "$discord_qualification_exit" -ne 0 ]; then exit "$discord_qualification_exit"; fi
  discord_assert_owned_stopped
else
  python -m unittest test_discord_capacity_controls test_discord_worker_lifecycle test_discord_presend_retry
fi
# One owned cluster for ordinary capacity/diagnostic; a NEW second cluster
# only for qualification after the first has stopped. No migration re-apply
# into an existing fixture. TERM permits evidence/teardown before KILL grace.
discord_capacity_exit=0
timeout --signal=TERM --kill-after=60s "$discord_owned_deadline" \
  python scripts/postriff_disposable_postgres.py tests/phase2/postgres_discord_capacity.py \
  || discord_capacity_exit=$?
if [ "$discord_coordinator_qualification" -eq 1 ]; then
  discord_cleanup_exit=0
  discord_assert_owned_stopped || discord_cleanup_exit=$?
  if [ "$discord_cleanup_exit" -ne 0 ]; then discord_capacity_exit="$discord_cleanup_exit"; fi
fi
# The existing runner deliberately truncates child stdout. Emit recoverable
# structured chunks AFTER it stops, preserving full aggregate/case evidence.
# No absolute paths, credentials, raw headers or provider bodies are emitted.
discord_capacity_emit_evidence discord-capacity-results.json discord-capacity-events.jsonl
printf 'RAFII_DISCORD_CAPACITY_EXIT {"exitCode":%d,"stage":"%s","realDiscord":"NOT_RUN"}\n' \
  "$discord_capacity_exit" "$RAFII_DISCORD_CAPACITY_STAGE"
exit "$discord_capacity_exit"
