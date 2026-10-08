#!/usr/bin/env bash
# Invoke only through cloud-python-bootstrap.sh on the remote Linux runner.
set -euo pipefail

case "${CI:-}" in
  1|true|TRUE) ;;
  *) echo "YouTube validation requires cloud CI; use JCB." >&2; exit 64 ;;
esac
if [ "$(uname -s)" != "Linux" ]; then
  echo "YouTube validation refuses execution on the Mac; use JCB." >&2
  exit 64
fi
if [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ] || [ ! -x "$TREND_VISUAL_TEST_PYTHON" ]; then
  echo "Start YouTube validation through cloud-python-bootstrap.sh." >&2
  exit 64
fi

jcb_youtube_repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$jcb_youtube_repo_root"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$jcb_youtube_repo_root/src:$jcb_youtube_repo_root/tests"

"$TREND_VISUAL_TEST_PYTHON" "$jcb_youtube_repo_root/scripts/cloud-dependency-security.py"

echo "YouTube Python contracts: injected transports; no creator acceptance calls."
"$TREND_VISUAL_TEST_PYTHON" - <<'PY'
import sys
import unittest

loader = unittest.TestLoader()
suite = unittest.TestSuite()
# Include the existing creator tests and new test_youtube*.py OAuth regressions.
suite.addTests(loader.discover('tests', pattern='test_youtube*.py', top_level_dir='tests'))
suite.addTests(loader.loadTestsFromNames([
    'test_hosted_wave3_connectors',
    'test_instagram_full_capabilities',
    'test_hosted_storage_video',
    'test_library_extract',
    'test_hosted_storage_library',
    'test_video_uploads',
    'test_postriff_phase2',
    'test_postriff_phase2_hosted',
    'test_postriff_phase2_learning',
    'test_wave4_hosted_publish',
    'test_asset_kinds',
    'test_postriff_audience_contract',
    'test_reply_writer',
    'test_postriff_content_types',
    'test_postriff_receipt_contract',
]))
if loader.errors:
    for error in loader.errors:
        print(error, file=sys.stderr)
    raise SystemExit(1)
count = suite.countTestCases()
if count < 220:
    raise SystemExit(f'Incomplete YouTube regression selection: {count} cases; expected at least 220.')
print(f'Selected {count} Python regression cases.', flush=True)
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
PY

bash "$jcb_youtube_repo_root/scripts/cloud-postgres-bootstrap.sh"

# Preserve the existing ci:jcb checks while reusing the isolated Python runtime.
# PostgreSQL above is disposable with synthetic providers; no deployed database is used.
cd -- "$jcb_youtube_repo_root/web"
npm run lint
npm run typecheck
node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs
npm run build
