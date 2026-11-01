#!/usr/bin/env bash
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Discord browser validation requires approved cloud CI.' >&2
  exit 64
fi
if [ "$#" -gt 1 ] || { [ -n "${1:-}" ] && [ "$1" != --with-node-checks ]; }; then
  echo 'Unsupported Discord browser validation argument.' >&2
  exit 64
fi
discord_browser_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [ ! -f "$discord_browser_root/.depot/discord-p0-ui.json" ]; then
  export PYTHONPATH="$discord_browser_root/scripts/linkedin_test_fence:$discord_browser_root/src:$discord_browser_root/tests"
  export RAFII_DISCORD_SYNTHETIC_FENCE=1
  python "$discord_browser_root/tests/discord_ui_fixture.py" "$discord_browser_root/.depot/discord-p0-ui.json"
fi
discord_browser_status=0
discord_browser_gate() {
  local gate="$1" result=0
  shift
  "$@" || result=$?
  printf 'RAFII_DISCORD_BROWSER_GATE {"gate":"%s","exitCode":%d}\n' "$gate" "$result"
  if [ "$result" -ne 0 ]; then discord_browser_status=1; fi
  if [ "$result" -eq 64 ]; then exit 64; fi
}
if [ "${1:-}" = --with-node-checks ]; then
  discord_browser_gate node node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs
fi
node node_modules/playwright/cli.js install --with-deps chromium
discord_browser_gate approval node tests/discord-p0-browser.cjs
discord_browser_gate connections node tests/discord-connections-browser.cjs
exit "$discord_browser_status"
