#!/usr/bin/env bash
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then exit 64; fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/src:$PWD/tests"
mkdir -p docs/consumer-ready/evidence/library
npm --prefix web audit --json > docs/consumer-ready/evidence/library/npm-audit.json || true
python - <<'PY'
import json
x=json.load(open('docs/consumer-ready/evidence/library/npm-audit.json'))
for name,v in x.get('vulnerabilities',{}).items():
 print('SECURITY',name,v['severity'],v.get('range'),v.get('fixAvailable'),json.dumps(v.get('via')))
PY
bash scripts/library-cloud-validation.sh
export POSTRIFF_PG_BIN="$(pg_config --bindir)"
test -x "$POSTRIFF_PG_BIN/initdb"
npm --prefix web run typecheck
npm --prefix web run lint
npm --prefix web run build
python scripts/consumer_ready_secrets.py
sudo -n apt-get -qq update
sudo -n apt-get -y -qq install ffmpeg
python tests/library_samples.py .codex/library-samples
for ext in mp3 m4a ogg flac aac webm; do
  ffmpeg -hide_banner -loglevel error -y -i .codex/library-samples/archive-acceptance.wav ".codex/library-samples/archive-acceptance.$ext"
done
cp .codex/library-samples/archive-acceptance.ogg .codex/library-samples/archive-acceptance.oga
cd web
npx playwright install --with-deps chromium webkit
cd ..
python scripts/consumer_ready_browser.py --library --evidence-dir docs/consumer-ready/evidence/library
if [ -f web/tests/library-intelligence-browser.cjs ]; then
  browser_exit=0
  python scripts/consumer_ready_browser.py --library-intelligence --evidence-dir docs/design/rafii-intelligent-library-2026-10-08/evidence/browser || browser_exit=$?
  # Screenshots return through the log (JCB keeps logs, not artifacts); exported on failure too, then the real exit stands.
  python scripts/library-evidence-export.py emit docs/design/rafii-intelligent-library-2026-10-08/evidence/browser || echo "LIBRARY_EVIDENCE_EXPORT_EXIT=$?"
  if [ "$browser_exit" -ne 0 ]; then exit "$browser_exit"; fi
fi
# A031 search latency at 10,000 mixed assets, 8 concurrent scoped searches (pgvector installed by the intelligence stage).
# Informational: the JSON receipt is the evidence; an over-budget result is reported, never hidden.
python scripts/library-intelligence-bench.py || echo "LIBRARY_BENCH_EXIT=$?"
npm --prefix web audit --audit-level=high
