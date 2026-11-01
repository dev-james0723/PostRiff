#!/usr/bin/env bash
# One cloud Python environment; independent gates collected without masking failures.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Use the approved non-deploy JCB ci route.' >&2; exit 64
fi
discord_ci_pipeline=0
if [ "$#" -gt 0 ]; then
  if [ "$#" -ne 1 ] || [ "$1" != --with-discord-pipeline ]; then exit 64; fi
  discord_ci_pipeline=1
fi
discord_ci_status=0
discord_ci_gate() {
  local gate="$1" result=0
  shift
  "$@" || result=$?
  printf 'RAFII_DISCORD_CI_GATE {"gate":"%s","exitCode":%d}\n' "$gate" "$result"
  if [ "$result" -ne 0 ]; then discord_ci_status=1; fi
  # Environment/fence guards are fatal; do not continue after an unsafe setup.
  if [ "$result" -eq 64 ]; then exit 64; fi
}
discord_ci_gate lint npm run lint
discord_ci_gate typecheck npm run typecheck
discord_ci_gate backend bash ../scripts/discord-validation-cloud.sh
discord_ci_gate node node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs
discord_ci_gate build npm run build
discord_ci_gate browser bash ../scripts/discord-browser-cloud.sh
if [ "$discord_ci_status" -eq 0 ] && [ "$discord_ci_pipeline" -eq 1 ]; then
  discord_ci_gate pipeline bash ../scripts/discord-capacity-cloud.sh --pipeline-qualification
fi
exit "$discord_ci_status"
