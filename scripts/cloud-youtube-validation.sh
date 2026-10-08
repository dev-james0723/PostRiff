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
    'test_rafii_origin_migration',
    'test_hosted_wave3_connectors',
    'test_productivity_connectors',
    'test_instagram_full_capabilities',
    'test_hosted_storage_video',
    'test_library_extract',
    'test_hosted_storage_library',
    'test_video_uploads',
    'test_video_provision',
    'test_dev_hosted_resumable',
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

# Preserve the current production Library's real parser regression. Its legacy
# RTF/Office viewer cases need the same official Ubuntu tools as the existing
# library-release-validation.sh; this installation runs only in cloud Linux CI.
if ! command -v libreoffice >/dev/null || ! command -v ffmpeg >/dev/null; then
  if [ "$(id -u)" -eq 0 ]; then
    apt-get -qq update
    DEBIAN_FRONTEND=noninteractive apt-get -y -qq install ffmpeg libreoffice-writer libreoffice-calc libreoffice-impress libseccomp2
  else
    sudo -n apt-get -qq update
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq install ffmpeg libreoffice-writer libreoffice-calc libreoffice-impress libseccomp2
  fi
fi
bash "$jcb_youtube_repo_root/scripts/cloud-postgres-bootstrap.sh"

# The same frontend checks can be rerun after UI-only repairs without repeating
# the unchanged successful backend/database checks.
bash "$jcb_youtube_repo_root/scripts/cloud-youtube-frontend-validation.sh"
