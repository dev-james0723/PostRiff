#!/usr/bin/env bash
# Mastodon Connect contracts with injected transports; invoke only through cloud-python-bootstrap.sh on JCB/Depot.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Mastodon Connect validation requires JCB/Depot Linux CI; no local fallback.' >&2
  exit 64
fi
if [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ] || [ ! -x "$TREND_VISUAL_TEST_PYTHON" ]; then
  echo 'Start Mastodon Connect validation through cloud-python-bootstrap.sh.' >&2
  exit 64
fi

mastodon_repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$mastodon_repo_root"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$mastodon_repo_root/src:$mastodon_repo_root/tests"

"$TREND_VISUAL_TEST_PYTHON" - <<'PY'
import sys
import unittest

loader = unittest.TestLoader()
suite = loader.loadTestsFromNames(['test_mastodon_connect', 'test_hosted_wave1_connectors', 'test_wave4c_connectors'])
if loader.errors:
    for error in loader.errors:
        print(error, file=sys.stderr)
    raise SystemExit(1)
count = suite.countTestCases()
if count < 60:
    raise SystemExit(f'Incomplete Mastodon Connect selection: {count} cases; expected at least 60.')
print(f'Selected {count} Mastodon Connect regression cases.', flush=True)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
