#!/usr/bin/env bash
# Remote-only frontend, build and browser regression; Google remains synthetic.
set -euo pipefail
case "${CI:-}" in 1|true|TRUE) ;; *) echo 'Use JCB e2e for frontend validation.' >&2; exit 64 ;; esac
if [ "$(uname -s)" != Linux ] || [ "$#" -ne 0 ] || [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ] || [ ! -x "$TREND_VISUAL_TEST_PYTHON" ]; then
  echo 'Requires cloud Linux and the existing pinned Python bootstrap.' >&2; exit 64
fi
jcb_youtube_repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

# PostgreSQL above is disposable with synthetic providers; no deployed database is used.
cd -- "$jcb_youtube_repo_root/web"
node node_modules/next/dist/bin/next typegen
npm run lint -- --format=unix
npm run typecheck
node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs
POSTRIFF_API_ORIGIN=http://127.0.0.1:4348 NEXT_PUBLIC_APP_URL=http://127.0.0.1:4448 POSTRIFF_DEV_SSR=1 npm run build
bash "$jcb_youtube_repo_root/scripts/cloud-youtube-browser.sh"
