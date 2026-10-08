#!/usr/bin/env bash
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Library validation requires cloud Linux CI.' >&2; exit 64
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/src:$PWD/tests"
python -m unittest test_library_extract test_hosted_storage_library test_hosted_storage_video
if ! command -v pg_config >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq install postgresql
fi
export POSTRIFF_PG_BIN="$(pg_config --bindir)"
sudo -n mkdir -p /var/run/postgresql
sudo -n chmod 1777 /var/run/postgresql
python scripts/postriff_pg_suite.py postgres_library_lifecycle
