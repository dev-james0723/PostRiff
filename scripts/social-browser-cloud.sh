#!/usr/bin/env bash
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'This browser acceptance runs only through the cloud CI executor.' >&2
  exit 64
fi
node node_modules/playwright/cli.js install --with-deps chromium
node tests/official-social-browser.cjs
