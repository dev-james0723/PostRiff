#!/usr/bin/env bash
# Each failure mode owns a fresh disposable Linux PostgreSQL cluster.
# No production DB connection, cleanup of durable evidence, or provider request.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ] || [ "${RAFII_DISCORD_SYNTHETIC_FENCE:-}" != 1 ] || [ "$#" -ne 0 ]; then
  echo 'Owned Linux CI synthetic PostgreSQL only; no hosted credentials.' >&2
  exit 64
fi
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$root"
export PYTHONPATH="$root/scripts/linkedin_test_fence:$root/src:$root/tests"
for scenario in concurrent canceled revoked unknown permission_removed 429; do
  echo "DISCORD_SQL_ISOLATED_BEGIN ${scenario}"
  RAFII_DISCORD_SQL_SCENARIO="$scenario" python scripts/postriff_disposable_postgres.py tests/phase2/postgres_discord_multimode.py
  echo "DISCORD_SQL_ISOLATED_PASS ${scenario}"
done
