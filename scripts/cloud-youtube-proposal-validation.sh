#!/usr/bin/env bash
# Narrow affected checks for YouTube proposal/calendar changes and source scanning.
set -euo pipefail
if [ "$#" -gt 1 ]; then echo "Unexpected validation arguments." >&2; exit 64; fi
case "${1:-}" in ""|--backend-only|--projection-only) ;; *) echo "Unknown validation selection." >&2; exit 64 ;; esac
case "${CI:-}" in 1|true|TRUE) ;; *) echo "Use JCB cloud CI." >&2; exit 64 ;; esac
if [ "$(uname -s)" != "Linux" ] || [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ]; then
  echo "Use cloud-python-bootstrap.sh on the Linux cloud runner." >&2; exit 64
fi
jcb_proposal_repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$jcb_proposal_repo"
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$jcb_proposal_repo/src:$jcb_proposal_repo/tests"
if [ "${1:-}" = "--projection-only" ]; then
  "$TREND_VISUAL_TEST_PYTHON" -m unittest test_youtube_workspace_projection
  exit 0
fi
"$TREND_VISUAL_TEST_PYTHON" scripts/consumer_ready_check.py ci-youtube-proposal-secrets "$TREND_VISUAL_TEST_PYTHON" scripts/consumer_ready_secrets.py
"$TREND_VISUAL_TEST_PYTHON" - <<'PYSCAN'
import json
from pathlib import Path
result = json.loads(Path('docs/consumer-ready/evidence/secret-scan.json').read_text())
print(json.dumps({k: result[k] for k in ('status', 'source', 'files', 'unexpected')}))
PYSCAN
"$TREND_VISUAL_TEST_PYTHON" - <<'PYTEST'
import sys, unittest
loader = unittest.TestLoader()
suite = loader.loadTestsFromNames([
    'test_youtube_agent', 'test_youtube_agent_tools', 'test_youtube_agent_calendar',
    'test_youtube_agent_pagination', 'test_youtube_agent_disconnect',
    'test_youtube_agent_history', 'test_site_agent', 'test_site_agent_search', 'test_agent_ui_queries',
    'test_youtube_workspace_projection', 'test_postriff_phase2', 'test_postriff_phase2_hosted', 'test_postriff_phase2_learning',
])
if loader.errors:
    for error in loader.errors: print(error, file=sys.stderr)
    raise SystemExit(1)
print(f'Selected {suite.countTestCases()} injected YouTube and calendar contracts.', flush=True)
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
PYTEST
if [ "${1:-}" != "--backend-only" ]; then
  bash scripts/cloud-youtube-frontend-validation.sh
fi
