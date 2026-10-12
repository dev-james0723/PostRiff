#!/usr/bin/env bash
# Real disposable PostgreSQL and synthetic official API contracts. Never live posts.
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'LinkedIn validation requires JCB/Depot Linux CI; no local fallback.' >&2
  exit 64
fi
linkedin_gate_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$linkedin_gate_root"
linkedin_gate_units=''
if [ "${1:-}" = --lifecycle-only ]; then
  linkedin_gate_suites='postgres_linkedin_lifecycle'
elif [ "${1:-}" = --linkedin-sql-only ]; then
  linkedin_gate_suites='postgres_linkedin_lifecycle postgres_linkedin_scale'
elif [ "${1:-}" = --oauth-contracts-only ]; then
  linkedin_gate_suites='postgres_youtube_identity_fence postgres_youtube_revocation'
  linkedin_gate_units='test_youtube_identity_fence test_youtube_oauth_binding'
elif [ "${1:-}" = --automation-only ]; then
  linkedin_gate_suites='postgres_consumer_campaign_worker postgres_final_campaign_destinations postgres_chat_automation postgres_raffi_planning'
  linkedin_gate_units='test_postriff_campaigns test_postriff_automation_chat test_postriff_automation_research test_automation_credit_rebind test_final_linkedin_little_text'
elif [ "$#" -eq 0 ]; then
  linkedin_gate_suites='postgres_official_social postgres_facebook_connection postgres_channels postgres_reverify postgres_x_oauth postgres_linkedin_lifecycle postgres_linkedin_scale'
  linkedin_gate_units='test_connection_health test_founder_product_events test_migration_numbers test_youtube_fleet test_youtube_oauth_binding test_youtube_worker_refresh test_youtube_workspace_provider_data test_youtube_creator test_youtube_identity_fence test_postriff_channels test_postriff_phase2 test_postriff_audience_contract test_official_social test_linkedin_publishing_recovery test_linkedin_token_lifecycle test_linkedin_fleet test_hosted_job_dispatch test_facebook_connection test_postriff_providers test_hosted_wave1_connectors test_hosted_wave3_connectors test_social_readiness_hardening test_postriff_hosted_deployment test_consumer_deployment'
else
  echo 'Unknown LinkedIn validation mode.' >&2
  exit 64
fi
if ! command -v pg_config >/dev/null; then
  sudo -n apt-get -qq update
  sudo -n apt-get -y -qq install postgresql
fi
export POSTRIFF_PG_BIN="$(pg_config --bindir)"
export RAFII_LINKEDIN_SYNTHETIC_FENCE=1
export PYTHONPATH="$linkedin_gate_root/scripts/linkedin_test_fence:$linkedin_gate_root/src:$linkedin_gate_root/tests"
python -c 'import sitecustomize; sitecustomize.self_check()'
if [ -n "$linkedin_gate_units" ]; then
  python -m unittest $linkedin_gate_units
fi
for linkedin_gate_suite in $linkedin_gate_suites; do
  python scripts/postriff_disposable_postgres.py "tests/phase2/$linkedin_gate_suite.py"
done
