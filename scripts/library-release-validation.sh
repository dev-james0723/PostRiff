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
npm --prefix web audit --audit-level=high
