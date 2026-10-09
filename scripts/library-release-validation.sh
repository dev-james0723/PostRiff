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
(cd web && node node_modules/next/dist/bin/next typegen)
npm --prefix web run typecheck
npm --prefix web run lint
npm --prefix web run build
python scripts/consumer_ready_secrets.py
sudo -n apt-get -qq update
sudo -n apt-get -y -qq install ffmpeg libreoffice-writer libreoffice-calc libreoffice-impress libseccomp2
python tests/library_samples.py .codex/library-samples
# Real encoded tones, with explicit codecs and unique OGA/OGG bytes (deduplication
# must not hide a format under the other extension). Decode every result as well.
for ext in mp3 m4a ogg oga flac aac webm; do
  case "$ext" in
    mp3) codec=libmp3lame ;;
    m4a|aac) codec=aac ;;
    ogg|oga) codec=libvorbis ;;
    flac) codec=flac ;;
    webm) codec=libopus ;;
  esac
  ffmpeg -hide_banner -loglevel error -y -f lavfi -i 'sine=frequency=440:duration=3' -c:a "$codec" -metadata title="Rafii acceptance $ext" ".codex/library-samples/archive-acceptance.$ext"
  ffmpeg -hide_banner -loglevel error -i ".codex/library-samples/archive-acceptance.$ext" -f null -
done
# Preserve the original H264 frames while testing the accepted QuickTime container.
ffmpeg -hide_banner -loglevel error -y -i web/public/onboarding/welcome-loop-dark.mp4 -c copy .codex/library-samples/archive-acceptance.mov
ffmpeg -hide_banner -loglevel error -i .codex/library-samples/archive-acceptance.mov -f null -
cd web
npx playwright install --with-deps chromium webkit
cd ..
# Both browser suites run even if the first fails; every screenshot comes back through the log (JCB keeps logs, not
# artifacts) and the first failure decides the exit, after the bench.
library_exit=0
python scripts/consumer_ready_browser.py --library --evidence-dir docs/consumer-ready/evidence/library || library_exit=$?
python scripts/library-evidence-export.py emit docs/consumer-ready/evidence/library 'library-*.png' || echo "LIBRARY_EVIDENCE_EXPORT_EXIT=$?"
python scripts/library-evidence-export.py emit docs/consumer-ready/evidence/library 'document-viewer-*.png' || echo "LIBRARY_EVIDENCE_EXPORT_EXIT=$?"
python scripts/library-evidence-export.py emit docs/consumer-ready/evidence/library 'debug-*.png' || echo "LIBRARY_EVIDENCE_EXPORT_EXIT=$?"
browser_exit=0
if [ -f web/tests/library-intelligence-browser.cjs ]; then
  python scripts/consumer_ready_browser.py --library-intelligence --evidence-dir docs/design/rafii-intelligent-library-2026-10-08/evidence/browser || browser_exit=$?
  python scripts/library-evidence-export.py emit docs/design/rafii-intelligent-library-2026-10-08/evidence/browser || echo "LIBRARY_EVIDENCE_EXPORT_EXIT=$?"
fi
echo "LIBRARY_BROWSER_EXITS library=$library_exit intelligence=$browser_exit"
# A031 search latency at 10,000 mixed assets, 8 concurrent scoped searches (pgvector installed by the intelligence stage).
# Informational: the JSON receipt is the evidence; an over-budget result is reported, never hidden.
python scripts/library-intelligence-bench.py || echo "LIBRARY_BENCH_EXIT=$?"
npm --prefix web audit --audit-level=high
if [ "$library_exit" -ne 0 ]; then exit "$library_exit"; fi
if [ "$browser_exit" -ne 0 ]; then exit "$browser_exit"; fi
