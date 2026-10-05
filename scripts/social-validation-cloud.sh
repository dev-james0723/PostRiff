#!/usr/bin/env bash
# Synthetic provider contracts and real disposable SQL, exclusively on cloud CI.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Social validation requires JCB cloud Linux CI; no local fallback.' >&2
  exit 64
fi
jcb_social_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
case "${1:-}" in
  '') node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs ;;
  --backend-only) ;;
  *) echo 'Unknown social validation mode.' >&2; exit 64 ;;
esac
cd -- "$jcb_social_root"
export PYTHONPATH="$jcb_social_root/src:$jcb_social_root/tests"
python -m unittest test_postriff_phase2 test_postriff_audience_contract test_official_social test_postriff_providers test_hosted_wave1_connectors test_hosted_wave3_connectors test_social_readiness_hardening test_hosted_storage_video
if ! command -v pg_config >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq install postgresql
fi
export POSTRIFF_PG_BIN="$(pg_config --bindir)"
python scripts/postriff_disposable_postgres.py tests/phase2/postgres_instagram_lifecycle.py tests/phase2/postgres_safety.py tests/phase2/postgres_official_social.py
