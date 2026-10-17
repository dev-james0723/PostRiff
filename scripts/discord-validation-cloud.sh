#!/usr/bin/env bash
# P0–P4 candidate. Remote execution AND disposable SQL require separate approval.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Discord validation requires approved JCB/Depot Linux CI; no local fallback.' >&2
  exit 64
fi
discord_gate_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$discord_gate_root"
discord_sql_script=tests/phase2/postgres_discord_rate_limits.py
unset RAFII_DISCORD_WARM_SEED_PROBE RAFII_DISCORD_LOCKED_CLOCK_PROBE RAFII_DISCORD_SCOPE_STORE_PROBE
case "${1:-}" in
  '') [ "$#" -eq 0 ] || exit 64 ;;
  --admission-index-probe)
    [ "$#" -eq 1 ] || exit 64
    discord_sql_script=tests/phase2/postgres_discord_admission_index_probe.py ;;
  --warm-seed-probe)
    [ "$#" -eq 1 ] || exit 64
    export RAFII_DISCORD_WARM_SEED_PROBE=1
    discord_sql_script=tests/phase2/postgres_discord_admission_index_probe.py ;;
  --locked-clock-probe)
    [ "$#" -eq 1 ] || exit 64
    export RAFII_DISCORD_LOCKED_CLOCK_PROBE=1
    discord_sql_script=tests/phase2/postgres_discord_admission_index_probe.py ;;
  --scope-store-probe)
    [ "$#" -eq 1 ] || exit 64
    export RAFII_DISCORD_SCOPE_STORE_PROBE=1
    discord_sql_script=tests/phase2/postgres_discord_admission_index_probe.py ;;
  *) exit 64 ;;
esac
discord_pg_bin=/usr/lib/postgresql/17/bin
if [ ! -x "$discord_pg_bin/postgres" ]; then
  # Official PGDG installation, inside the separately authorized ephemeral CI
  # runner only. Prevent package scripts from creating/starting a default5432 DB.
  # https://www.postgresql.org/download/linux/ubuntu/
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
export PYTHONPATH="$discord_gate_root/scripts/linkedin_test_fence:$discord_gate_root/src:$discord_gate_root/tests"
if ! python -c 'import sitecustomize; sitecustomize.self_check()'; then exit 64; fi
discord_validation_status=0
discord_validation_gate() {
  local gate="$1" result=0
  shift
  "$@" || result=$?
  printf 'RAFII_DISCORD_BACKEND_GATE {"gate":"%s","exitCode":%d}\n' "$gate" "$result"
  if [ "$result" -ne 0 ]; then discord_validation_status=1; fi
  if [ "$result" -eq 64 ]; then exit 64; fi
}
discord_validation_gate python python -m unittest test_discord_rate_limits test_discord_worker_lifecycle test_discord_oauth_lifecycle test_discord_destinations test_discord_publish_authorization test_hosted_wave1_connectors \
  test_hosted_job_dispatch test_postriff_phase2 test_postriff_campaigns \
  test_postriff_automation_chat test_automation_credit_rebind test_social_readiness_hardening \
  test_hosted_wave3_connectors test_youtube_identity_fence \
  test_youtube_worker_refresh test_youtube_oauth_binding test_discord_presend_retry \
  test_postgres_pool_controls test_discord_capacity_approval_receipt test_rafii_account_holds
discord_validation_gate sql python scripts/postriff_disposable_postgres.py "$discord_sql_script"
python - <<'PY_EVIDENCE'
import json
from pathlib import Path
p=Path('.depot/discord-p4-coordinator-results.json')
if not p.is_file():raise SystemExit('Actual PostgreSQL regression evidence is missing')
d=json.loads(p.read_text())
assert d['status']=='PASS' and d['exactScopedDispatchRegression'] is True
print('RAFII_DISCORD_ACTUAL_SQL_REGRESSIONS '+json.dumps({'status':d['status'],'rateGroups':len(d['checks']),'workerGroups':len(d['workerChecks']),'exactScopedDispatchRegression':True,'realDiscordRequests':d['realDiscordRequests'],'productionDatabaseWrites':d['productionDatabaseWrites']}))
PY_EVIDENCE
if [ "$discord_sql_script" = tests/phase2/postgres_discord_admission_index_probe.py ]; then
  python - <<'PY_INDEX_EVIDENCE'
import hashlib,json
from pathlib import Path
p=Path('.depot/discord-admission-index-probe.json')
if not p.is_file():raise SystemExit('Admission-index diagnostic evidence is missing')
raw=p.read_bytes();data=raw.decode();parts=[data[i:i+2500] for i in range(0,len(data),2500)]
for i,part in enumerate(parts):
    print('RAFII_DISCORD_INDEX_EVIDENCE '+json.dumps({'file':p.name,'index':i,'parts':len(parts),
        'sha256':hashlib.sha256(raw).hexdigest(),'text':part}),flush=True)
PY_INDEX_EVIDENCE
fi
discord_validation_gate fixture python tests/discord_ui_fixture.py .depot/discord-p0-ui.json
exit "$discord_validation_status"
