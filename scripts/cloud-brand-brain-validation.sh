#!/usr/bin/env bash
# Real application/database validation on the cloud runner; external providers are injected.
set -euo pipefail
case "${CI:-}" in 1|true|TRUE) ;; *) echo 'Use JCB for Brand Brain validation.' >&2; exit 64 ;; esac
if [ "$(uname -s)" != Linux ] || [ -z "${TREND_VISUAL_TEST_PYTHON:-}" ] || [ ! -x "$TREND_VISUAL_TEST_PYTHON" ]; then
  echo 'Requires Linux CI and the pinned isolated Python bootstrap.' >&2; exit 64
fi
bb_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
bb_mode="${1:-all}"
case "$bb_mode" in all|backend|frontend) ;; *) exit 64 ;; esac
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$bb_root/src:$bb_root/tests"
export POSTRIFF_RESEARCH=0 POSTRIFF_LOCAL_CLI=0
export NEXT_PUBLIC_BRAND_BRAIN_V11=1 NEXT_PUBLIC_SENTRY_DISABLED=1 NEXT_TELEMETRY_DISABLED=1
export POSTRIFF_API_ORIGIN=http://127.0.0.1:4348 NEXT_PUBLIC_APP_URL=http://127.0.0.1:4448 POSTRIFF_DEV_SSR=1
cd -- "$bb_root"
bb_pg=''
for bb_candidate in /usr/lib/postgresql/17/bin /usr/lib/postgresql/16/bin; do
  if [ -x "$bb_candidate/initdb" ]; then bb_pg="$bb_candidate"; break; fi
done
if [ -z "$bb_pg" ]; then
  if [ "$(id -u)" -eq 0 ]; then
    apt-get -qq update
    DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
  else
    sudo -n apt-get -qq update
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -y -qq --no-install-recommends install postgresql-16
  fi
  bb_pg=/usr/lib/postgresql/16/bin
fi
export POSTRIFF_PG_BIN="$bb_pg"
bb_failed=0
if [ "$bb_mode" != frontend ]; then
  "$TREND_VISUAL_TEST_PYTHON" - <<'PY' || bb_failed=1
import sys, unittest
loader = unittest.TestLoader()
suite = unittest.TestSuite()
suite.addTests(loader.discover('tests', pattern='test_brand_brain*.py', top_level_dir='tests'))
suite.addTests(loader.loadTestsFromNames(['test_voice_ai_analysis', 'test_postriff_voice_analysis',
 'test_postriff_voice_sources', 'test_postriff_memory_egress', 'test_postriff_voice_generation',
 'test_postriff_phase2_learning', 'test_reply_writer', 'test_r0_hotfixes', 'test_social_voice_services', 'test_postriff_profiles_auth']))
if loader.errors:
 print('\n'.join(loader.errors), file=sys.stderr); raise SystemExit(1)
print(f'Brand Brain Python selection: {suite.countTestCases()} tests', flush=True)
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
  # Each suite owns its disposable cluster; no fixture state leaks between suites.
  for bb_suite in tests/phase2/postgres_brand_brain*.py tests/phase2/postgres_raffi_voice_sources.py tests/phase2/postgres_memory_proposals.py tests/phase2/postgres_growth_phase1.py; do
    [ -f "$bb_suite" ] || { echo "Missing required suite $bb_suite" >&2; exit 3; }
    "$TREND_VISUAL_TEST_PYTHON" scripts/postriff_disposable_postgres.py "$bb_suite" || bb_failed=1
  done
fi
if [ "$bb_mode" != backend ]; then
  cd -- "$bb_root/web"
  node node_modules/next/dist/bin/next typegen || bb_failed=1
  npm run lint -- --format=unix || bb_failed=1
  npm run typecheck || bb_failed=1
  node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs || bb_failed=1
  if npm run build; then
    bash "$bb_root/scripts/cloud-brand-brain-browser.sh" || bb_failed=1
  else
    bb_failed=1
  fi
fi

exit "$bb_failed"
