#!/usr/bin/env bash
# Non-deploy candidate batch. Invoke only through the authorized Linux runner.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ] || [ "$#" -ne 0 ]; then
  echo 'Use the authorized Linux validation route; no local-heavy fallback.' >&2
  exit 64
fi
multimode_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$multimode_root"
mkdir -p .depot
export PYTHONPATH="$multimode_root/scripts/linkedin_test_fence:$multimode_root/src:$multimode_root/tests"
export RAFII_DISCORD_SYNTHETIC_FENCE=1 PYTHONDONTWRITEBYTECODE=1
result=0
multimode_gate() {
  local name="$1" code=0
  shift
  "$@" || code=$?
  printf 'DISCORD_MULTIMODE_GATE {"name":"%s","exitCode":%d}\n' "$name" "$code"
  if [ "$code" -ne 0 ]; then result=1; fi
}
multimode_gate discord-python python -m unittest discover -s tests -p 'test_discord*.py' -v
multimode_gate discord-postgres bash scripts/discord-multimode-sql-cases-cloud.sh
multimode_gate browser-fixture python tests/discord_ui_fixture.py .depot/discord-p0-ui.json
cd web
multimode_gate web-unit node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs
multimode_gate next-types node node_modules/next/dist/bin/next typegen
multimode_gate types npm run typecheck
multimode_gate lint npm run lint
# The harness creates an isolated loopback app; never attach to personal Chrome.
multimode_gate browser node tests/discord-multimode-browser.cjs
exit "$result"
