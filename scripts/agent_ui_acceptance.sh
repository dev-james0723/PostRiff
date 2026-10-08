#!/usr/bin/env bash
# Lane G acceptance runner for Rafii Generative UI (rafii-genui/1). Called by scripts/agent_ui_validation.sh browser|live|release
# (the agent-ui.yml step "Browser acceptance (lane G)" runs `browser` automatically once this file exists).
#
#   agent_ui_acceptance.sh browser   cloud CI only: real web build + acceptance stack (serve.py: real API, disposable PG 17 with
#                                    migration 102, harness Manager, fixture provider) → API corpus, parser-seam corpus, Playwright
#                                    scenes in Chromium and WebKit (emulation), production-bundle devtools grep, gate summary
#   agent_ui_acceptance.sh api       cloud CI only: the same stack without the browser build (API + parser-seam corpus need the
#                                    Next validator route, so the web app is still built and started; scenes are skipped)
#   agent_ui_acceptance.sh live ...  scripts/agent_ui_live.py (budget-capped live runner against a deployed origin; refuses without
#                                    RAFII_LIVE_CHECKS=1, an explicit --origin, --workspace and --budget-usd)
#   agent_ui_acceptance.sh release   G25: every required gate has pass evidence for the exact candidate SHA (AGENT_UI_CANDIDATE_SHA,
#                                    default HEAD); fails on stale, blocked, absent or unverified evidence
#
# Blocked checks (a lane's route still answers ui_not_ready) are reported, never passed. They fail the run when strict:
# AGENT_UI_REQUIRE_COMPLETE=1, or a pull request into consumer-saas (GITHUB_BASE_REF). Failures always fail.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
ROOT="$PWD"
export PYTHONPATH="$ROOT/src:$ROOT/tests"
export OPENUI_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1 NEXT_TELEMETRY_DISABLED=1 POSTRIFF_RESEARCH=0 LC_ALL=C
EVIDENCE="${AGENT_UI_EVIDENCE_DIR:-${RUNNER_TEMP:-/tmp}/agent-ui-evidence}"
mkdir -p -- "$EVIDENCE"
PY="${RAFII_TEST_PYTHON:-python}"
SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
mode="${1:-browser}"
shift || true

strict=0
if [ "${AGENT_UI_REQUIRE_COMPLETE:-}" = 1 ] || [ "${GITHUB_BASE_REF:-}" = consumer-saas ]; then strict=1; fi

record() { # mode exit tests
  printf '{"mode":"%s","exitCode":%s,"tests":%s,"headSha":"%s","strict":%s}\n' "$1" "$2" "$3" "$SHA" "$strict" | tee -a "$EVIDENCE/results.jsonl"
}

cloud_only() {
  if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
    echo "agent_ui_acceptance.sh $mode runs on cloud Linux CI only (this Mac is a control plane)." >&2; exit 64
  fi
}

API_PORT=4538 WEB_PORT=4539 PROVIDER_PORT=4540 PG_PORT=55538
PIDS=()
BUILD_OK=1   # 0: the production build failed → the run fails; the API/parser corpora still run on `next dev`, scenes are skipped
cleanup() {
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill -TERM "$pid" 2>/dev/null || true; done
  sleep 2
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill -KILL "$pid" 2>/dev/null || true; done
}

start_stack() {
  export POSTRIFF_PG_BIN="${POSTRIFF_PG_BIN:-/usr/lib/postgresql/17/bin}"
  # One random validator secret per run, shared by the API (signer) and the Next route (verifier); never printed or stored.
  RAFII_GENUI_VALIDATOR_SECRET="$("$PY" -c 'import secrets; print(secrets.token_hex(32))')"
  export RAFII_GENUI_VALIDATOR_SECRET
  local web_env=(env -i "PATH=$PATH" "HOME=$HOME" "CI=true" "LC_ALL=C" "NODE_ENV=production" "OPENUI_TELEMETRY_DISABLED=1" "DO_NOT_TRACK=1"
                 "NEXT_TELEMETRY_DISABLED=1" "NEXT_PUBLIC_SENTRY_DISABLED=1" "NEXT_PUBLIC_APP_URL=http://127.0.0.1:$WEB_PORT" "NEXT_PUBLIC_SUPABASE_URL="
                 "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=" "POSTRIFF_API_ORIGIN=http://127.0.0.1:$API_PORT" "POSTRIFF_DEV_SSR=1"
                 "RAFII_GENUI_VALIDATOR_SECRET=$RAFII_GENUI_VALIDATOR_SECRET")
  if [ ! -f web/.next/BUILD_ID ]; then
    echo "::group::web production build (credential-free env)"
    if (cd web && "${web_env[@]}" npm run build) >"$EVIDENCE/web-build.log" 2>&1; then
      tail -n 15 "$EVIDENCE/web-build.log"
    else
      BUILD_OK=0
      grep -E "error TS|Error:|Failed" "$EVIDENCE/web-build.log" | head -n 20 || true
      echo "::error::web production build failed; the run fails. Backend corpora continue on next dev; browser scenes are skipped."
      record web-build 1 0
    fi
    echo "::endgroup::"
  fi
  CI=true RAFII_WEB_INTERNAL_URL="http://127.0.0.1:$WEB_PORT" POSTRIFF_DEV_WEB_ORIGIN="http://127.0.0.1:$WEB_PORT" \
    "$PY" tests/agent_ui_acceptance/serve.py --port "$API_PORT" --pg-port "$PG_PORT" --provider-port "$PROVIDER_PORT" \
    --state-file "$EVIDENCE/stack.json" >"$EVIDENCE/harness.log" 2>&1 &
  PIDS+=("$!")
  if [ "$BUILD_OK" = 1 ]; then
    (cd web && exec "${web_env[@]}" npx next start -p "$WEB_PORT" -H 127.0.0.1) >"$EVIDENCE/web.log" 2>&1 &
  else
    local dev_env=() item
    for item in "${web_env[@]}"; do [ "$item" = "NODE_ENV=production" ] && item="NODE_ENV=development"; dev_env+=("$item"); done
    (cd web && exec "${dev_env[@]}" npx next dev -p "$WEB_PORT" -H 127.0.0.1) >"$EVIDENCE/web.log" 2>&1 &
  fi
  PIDS+=("$!")
  for _ in $(seq 1 200); do
    if curl -sf "http://127.0.0.1:$API_PORT/api/health" >/dev/null && curl -s -o /dev/null --max-time 240 "http://127.0.0.1:$WEB_PORT/" && [ -s "$EVIDENCE/stack.json" ]; then
      # Compile the parser-seam route once (a dev server compiles on first request; an unsigned POST is refused 401).
      curl -s -o /dev/null --max-time 240 -X POST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$WEB_PORT/internal/agent-ui/validate" || true
      echo "acceptance stack ready (api :$API_PORT, web :$WEB_PORT $([ "$BUILD_OK" = 1 ] && echo production || echo 'next dev fallback'), fixture provider :$PROVIDER_PORT)"; return 0
    fi
    sleep 2
  done
  echo "acceptance stack did not start"; tail -n 60 "$EVIDENCE/harness.log" "$EVIDENCE/web.log"; return 1
}

run_py_corpus() { # module name
  local log="$EVIDENCE/$2.log" status=0 count
  AGENT_UI_API_URL="http://127.0.0.1:$API_PORT" AGENT_UI_STACK_STATE="$EVIDENCE/stack.json" AGENT_UI_WEB_URL="http://127.0.0.1:$WEB_PORT" \
    AGENT_UI_VALIDATOR_SECRET="$RAFII_GENUI_VALIDATOR_SECRET" AGENT_UI_EVIDENCE_DIR="$EVIDENCE" \
    "$PY" -m unittest "agent_ui_acceptance.$1" -v >"$log" 2>&1 || status=$?
  tail -n 50 "$log"
  count="$(grep -Eo '^Ran [0-9]+ tests?' "$log" | grep -Eo '[0-9]+' | tail -n1 || echo 0)"
  record "$2" "$status" "${count:-0}"
  [ "$status" -eq 0 ] && [ "${count:-0}" -gt 0 ]
}

run_scenes() {
  local failed=0 engine
  echo "::group::Playwright browsers (cloud install)"
  npx --prefix web playwright install --with-deps chromium webkit >"$EVIDENCE/playwright-install.log" 2>&1 || { tail -n 30 "$EVIDENCE/playwright-install.log"; echo "::endgroup::"; return 1; }
  echo "::endgroup::"
  local provider
  provider="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("providerUrl",""))' "$EVIDENCE/stack.json")"
  for engine in chromium webkit; do
    RAFII_WEB_URL="http://127.0.0.1:$WEB_PORT" AGENT_UI_PROVIDER_URL="$provider" AGENT_UI_EVIDENCE_DIR="$EVIDENCE" \
      node web/tests/agent-ui-e2e/run.cjs --browser="$engine" --out="$EVIDENCE" 2>&1 | tee "$EVIDENCE/e2e-$engine.log" || failed=1
    record "e2e-$engine" "$failed" "$(grep -cE '^(PASS|FAIL|BLOCKED) ' "$EVIDENCE/e2e-$engine.log" || echo 0)"
  done
  return "$failed"
}

bundle_grep() {
  local hits
  hits="$(grep -rl 'cdn.jsdelivr.net/npm/@openuidev/devtools' web/.next/static 2>/dev/null | wc -l | tr -d ' ')"
  printf '{"check":"bundle:devtools-url","chunksWithDevtoolsUrl":%s}\n' "$hits" | tee "$EVIDENCE/bundle-devtools.json"
  [ "$hits" -eq 0 ]
}

summarize() {
  local args=(--dir "$EVIDENCE")
  [ "$strict" = 1 ] && args+=(--strict)
  "$PY" -m agent_ui_acceptance.summarize "${args[@]}"
}

case "$mode" in
  browser|api)
    cloud_only
    trap cleanup EXIT
    failed=0
    start_stack || { record "$mode-stack" 1 0; exit 1; }
    run_py_corpus api_corpus api-corpus || failed=1
    run_py_corpus validator_corpus validator-corpus || failed=1
    if [ "$BUILD_OK" != 1 ]; then
      failed=1   # a red production build always fails the run, whatever the corpora say
    fi
    if [ "$mode" = browser ] && [ "$BUILD_OK" = 1 ]; then
      run_scenes || failed=1
      bundle_grep || failed=1
    elif [ "$mode" = browser ]; then
      echo "browser scenes skipped: they need the production build, which failed (see web-build.log)" | tee "$EVIDENCE/e2e-skipped.txt"
    fi
    summarize || failed=1
    exit "$failed" ;;
  live)
    exec "$PY" scripts/agent_ui_live.py "$@" ;;
  release)
    candidate="${AGENT_UI_CANDIDATE_SHA:-$SHA}"
    "$PY" -m agent_ui_acceptance.release --candidate "$candidate" --out "$EVIDENCE/release-report.json" \
      --records docs/design/openui-production-2026-10-08/evidence/g/results "$@" ;;
  *) echo "usage: agent_ui_acceptance.sh browser|api|live|release" >&2; exit 64 ;;
esac
