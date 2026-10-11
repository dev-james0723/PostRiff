#!/usr/bin/env bash
# Rafii Generative UI validation runner (04-ACCEPTANCE "Suggested runner entrypoints"). Cloud Linux CI only.
#
#   agent_ui_validation.sh unit        Python tests/test_agent_ui_*.py + node web/tests/agent-ui-*.test.cjs (+ agent-ui-*/ dirs)
#   agent_ui_validation.sh database    tests/phase2/postgres_agent_ui_*.py on disposable PostgreSQL (real roles, no service bypass in assertions)
#   agent_ui_validation.sh regression  full existing Python unittest discovery + all top-level web node tests (G20)
#   agent_ui_validation.sh jcb         modes listed in scripts/.agent-ui-jcb-modes (uncommitted lane override), default "unit database"
#   agent_ui_validation.sh browser|live|release   owned by G (tests/agent_ui_acceptance, web/tests/agent-ui-e2e)
#
# Every mode refuses to pass with zero discovered tests and records exit codes + counts to $AGENT_UI_EVIDENCE_DIR.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Agent UI validation requires cloud Linux CI (JCB/Depot or GitHub Actions).' >&2; exit 64
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/src:$PWD/tests"
export OPENUI_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1 POSTRIFF_RESEARCH=0 LC_ALL=C
EVIDENCE="${AGENT_UI_EVIDENCE_DIR:-${RUNNER_TEMP:-/tmp}/agent-ui-evidence}"
mkdir -p -- "$EVIDENCE"
PY="${RAFII_TEST_PYTHON:-python}"
SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"

record() { # mode exit count
  printf '{"mode":"%s","exitCode":%s,"tests":%s,"headSha":"%s","workingTreeProof":"%s"}\n' "$1" "$2" "$3" "$SHA" \
    "$(cat .jcb-working-tree-proof.txt 2>/dev/null | head -c 120 | tr -d '"\n' || true)" | tee -a "$EVIDENCE/results.jsonl"
}

need_pg() {
  if ! command -v pg_config >/dev/null; then
    sudo -n apt-get -qq update
    sudo -n apt-get -y -qq install postgresql
  fi
  export POSTRIFF_PG_BIN="$(pg_config --bindir)"
  sudo -n mkdir -p /var/run/postgresql
  sudo -n chmod 1777 /var/run/postgresql
}

run_unit() {
  local log="$EVIDENCE/unit-python.log" status=0 count
  "$PY" -m unittest discover -s tests -p 'test_agent_ui_*.py' -v >"$log" 2>&1 || status=$?
  tail -n 40 "$log"
  count="$(grep -Eo '^Ran [0-9]+ tests?' "$log" | grep -Eo '[0-9]+' | tail -n1 || echo 0)"
  record unit-python "$status" "${count:-0}"
  [ "$status" -eq 0 ] && [ "${count:-0}" -gt 0 ] || return 1
  local files=() f
  for f in web/tests/agent-ui-*.test.cjs web/tests/agent-ui-*.test.mjs web/tests/agent-ui-*/*.test.cjs web/tests/agent-ui-*/*.test.mjs; do
    [ -f "$f" ] && files+=("$f")
  done
  if [ "${#files[@]}" -eq 0 ]; then record unit-web 1 0; return 1; fi
  log="$EVIDENCE/unit-web.log"; status=0
  node --test "${files[@]}" >"$log" 2>&1 || status=$?
  tail -n 40 "$log"
  count="$(grep -Eo '^(# |ℹ )pass [0-9]+' "$log" | grep -Eo '[0-9]+' | tail -n1 || echo 0)"
  record unit-web "$status" "${count:-0}"
  [ "$status" -eq 0 ] && [ "${count:-0}" -gt 0 ]
}

run_database() {
  need_pg
  local stems=() f
  for f in tests/phase2/postgres_agent_ui_*.py; do
    [ -f "$f" ] && stems+=("$(basename "$f" .py)")
  done
  if [ "${#stems[@]}" -eq 0 ]; then record database 1 0; return 1; fi
  local log="$EVIDENCE/database.log" status=0
  "$PY" scripts/postriff_pg_suite.py "${stems[@]}" >"$log" 2>&1 || status=$?
  tail -n 60 "$log"
  record database "$status" "${#stems[@]}"
  [ "$status" -eq 0 ]
}

run_regression() {
  local log="$EVIDENCE/regression-python.log" status=0 count
  "$PY" -m unittest discover -s tests -p 'test_*.py' >"$log" 2>&1 || status=$?
  tail -n 30 "$log"
  count="$(grep -Eo '^Ran [0-9]+ tests?' "$log" | grep -Eo '[0-9]+' | tail -n1 || echo 0)"
  record regression-python "$status" "${count:-0}"
  [ "$status" -eq 0 ] || return 1
  log="$EVIDENCE/regression-web.log"; status=0
  node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs >"$log" 2>&1 || status=$?
  tail -n 30 "$log"
  count="$(grep -Eo '^(# |ℹ )pass [0-9]+' "$log" | grep -Eo '[0-9]+' | tail -n1 || echo 0)"
  record regression-web "$status" "${count:-0}"
  [ "$status" -eq 0 ]
}

run_mode() {
  case "$1" in
    unit) run_unit ;;
    database) run_database ;;
    regression) run_regression ;;
    browser|live|release)
      if [ -x scripts/agent_ui_acceptance.sh ]; then bash scripts/agent_ui_acceptance.sh "$1"; else echo "mode $1 is not wired yet (lane G)" >&2; record "$1" 1 0; return 1; fi ;;
    *) echo "unknown mode $1" >&2; return 64 ;;
  esac
}

mode="${1:-unit}"
if [ "$mode" = jcb ]; then
  modes="unit"
  compgen -G 'tests/phase2/postgres_agent_ui_*.py' >/dev/null && modes="unit database"
  [ -f scripts/.agent-ui-jcb-modes ] && modes="$(tr -cs 'a-z' ' ' < scripts/.agent-ui-jcb-modes)"
  failed=0
  for m in $modes; do run_mode "$m" || failed=1; done
  exit "$failed"
fi
run_mode "$mode"
