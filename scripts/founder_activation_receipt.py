"""Build reviewable, non-executing full-activation receipts from current source.

Never changes definitions, flags, database state or provider configuration.
Live evidence is added explicitly; code presence is not activation proof.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rafii_control.founder_activation import feature_manifest
from rafii_control.intelligence import Catalog
from postriff_phase2.founder_policy import defaults

SOURCE_GROUPS = {
 'revenue': {'commands': ['billing signed webhook', 'subscription snapshot cron', 'credit payment lifecycle'],
             'tables': ['pr_subscription_events', 'pr_subscription_snapshots', 'pr_invoices', 'pr_credit_orders', 'pr_credit_subscription_grants', 'pr_credit_refunds', 'pr_credit_disputes'],
             'projections': ['business_subscription_events', 'business_subscription_snapshots', 'business_payments_v2', 'business_subscription_grants', 'business_refunds', 'business_disputes'],
             'dedupe': 'provider event/invoice/payment/refund IDs; signed raw-body verification; half-open event windows',
             'test': 'tests/control/test_founder_revenue_pg.py', 'owner': ['merchant activation and per-action charge/refund confirmation'],
             'history': 'Real signed lifecycle and native currency amounts required; fixtures excluded. Forecasts need the catalog-defined history.'},
 'ai': {'commands': ['metered model attempt scope', 'Ledger.reserve/settle/reconcile_unknown', 'voice/phone settlement'],
        'tables': ['pr_ai_call_events', 'pr_ai_call_settlements', 'pr_usage_ledger', 'pr_usage_rollups'],
        'projections': ['business_ai_calls', 'business_usage_v2', 'business_usage_rollups'],
        'dedupe': 'physical_attempt_id/dedupe_key; reservation id; one terminal cost plus immutable late settlement sidecar',
        'test': 'tests/control/test_founder_ai_pg.py', 'owner': [],
        'history': 'Unknown attempts/reservations remain unknown; price version is fixed at use. Forecasts require real mature history.'},
 'product': {'commands': ['workspace bootstrap', 'repository command before/after effect', 'OAuth connect/revoke', 'publish outcome', 'automation run completion'],
             'tables': ['pr_product_events', 'pr_learning_events', 'pr_learning_daily_rollups', 'pr_time_savings_ledger'],
             'projections': ['business_product_events', 'business_product_observations', 'business_learning_events', 'business_learning_rollups', 'business_time_savings'],
             'dedupe': 'event:entity:version and original command/run/publication identifiers',
             'test': 'tests/control/test_founder_product_pg.py', 'owner': [],
             'history': 'First-seen taxonomy coverage, mature cohorts and minimum sample required; no invented prior activity.'},
 'operations': {'commands': ['request completion hook/flush', 'operational snapshot cron', 'notification outbox and callback', 'connection health probe', 'data request command'],
                'tables': ['pr_request_metrics', 'pr_operational_snapshots', 'pr_notification_deliveries', 'pr_notification_provider_events', 'pr_connection_health', 'pr_phone_calls', 'pr_data_requests'],
                'projections': ['business_request_metrics', 'business_operational_snapshots', 'business_notification_deliveries', 'business_connection_health', 'business_data_requests_v2', 'business_telemetry_health'],
                'dedupe': 'minute/route counters, event/delivery keys, provider/event callback IDs, bounded per-stage snapshot keys',
                'test': 'tests/control/test_founder_ops_pg.py', 'owner': [],
                'history': 'Per-stage watermarks and retained coverage required. API/call global operations counts include internal traffic by current definition.'},
 'support': {'commands': ['authenticated in-app ticket creation/reply', 'Founder reply/status/reveal'],
             'tables': ['pr_support_tickets','pr_support_messages','pr_audit_events'], 'projections': ['business_support_tickets','business_data_requests_v2'],
             'dedupe': 'workspace/request UUID and immutable message fingerprint; status CAS; reveal requires fresh MFA and content-free audit.',
             'test': 'tests/control/test_founder_support_refunds.py', 'owner': [],
             'history': 'Elapsed response/resolution seconds use retained original tickets. Business-time SLA and CSAT have no source; activated support_aging v1 remains privacy-request based until a versioned definition replaces it.'},
 'engineering': {'commands': ['attested exact-SHA CI evidence ingestion'], 'tables': ['rafii_control.github_check_snapshots', 'rafii_control.engineering_evidence'],
                 'projections': ['capability-scoped engineering receipts'], 'dedupe': 'repository + candidate SHA + workflow/check identity',
                 'test': 'tests/control/test_founder_engineering.py', 'owner': [], 'history': 'Trusted current required-check manifest and exact deployment SHA required; no arbitrary green snapshots.'},
 'marketing': {'commands': [], 'tables': [], 'projections': [], 'dedupe': 'Requires selected authorized acquisition/GSC/experiment source and ingestion contract.',
               'test': None, 'owner': ['authorized acquisition/GSC account and OAuth'], 'history': 'Source ownership, attribution denominator, native-currency spend and observation window unavailable.'},
}
GROUP_IDS = {
 'revenue': 'paid_workspaces mrr delinquent_mrr logo_churn paid_customers subscriptions_by_plan_status cash_collected payment_failures refunds_disputes cost_vs_cash mrr_movements mrr_forecast mrr_new mrr_expansion mrr_contraction mrr_churn collections refunds dispute_net net_collections recovery_rate nrr grr contribution cost_coverage mrr_reactivation credit_grants credit_consumption credit_available credit_held credit_debt'.split(),
 'ai': 'ai_latency ai_cost_actual ai_cost_unknown ai_cost_by_feature founder_ops_cost budget_remaining ai_calls ai_tokens ai_fallback_retry_rate ai_cost_per_call cost_per_useful_outcome ai_cost_forecast ai_actual_cost ai_failed_cost cost_per_useful ai_quality task_latency'.split(),
 'product': 'active_workspaces time_to_value feature_adoption time_back activation_funnel retention_weekly retention_correlations active_users activation_rate retention_d7 retention_d28 task_success publish_verified useful_outcomes automation_success'.split(),
 'operations': 'api_latency slo_burn publish_outcomes cron_heartbeat notification_delivery phone_calls source_health data_requests_backlog security_events api_error_rate queue_health connection_health publish_by_provider api_errors queue_age affected_workspaces source_lag'.split(),
 'support': 'support_aging open_tickets first_response resolution_time csat repeat_tickets'.split(),
 'engineering': 'required_checks check_failures flake_rate security_open'.split(),
 'marketing': 'gsc_clicks gsc_ctr attribution_coverage source_paid_conversion cac decision_recovered_cash experiment_effect'.split(),
}
REPLACEMENTS = {'mrr_new': ('mrr_movements', 'new'), 'mrr_expansion': ('mrr_movements', 'expansion'),
                'mrr_contraction': ('mrr_movements', 'contraction'), 'mrr_churn': ('mrr_movements', 'churn'),
                'mrr_reactivation': ('mrr_movements', 'reactivation')}
INCOMPATIBLE = {'ai_actual_cost': 'ai_cost_actual', 'cost_per_useful': 'cost_per_useful_outcome', 'api_errors': 'api_error_rate',
                'collections': 'cash_collected', 'refunds': 'refunds_disputes', 'publish_verified': 'publish_outcomes'}


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=ROOT / 'docs/releases/founder-full-activation-20261002')
    parser.add_argument('--governing-catalog', type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    catalog = Catalog().metrics
    if len(catalog) != 97:
        raise ValueError('Reconcile changed catalog against the 97-ID handoff first')
    if args.governing_catalog and {r['id'] for r in json.loads(args.governing_catalog.read_text())} != set(catalog):
        raise ValueError('Governing metric inventory differs')
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    files = [p for folder in ('src', 'migrations/postriff', 'web/src', 'tests', 'scripts') for p in (ROOT / folder).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    tree = hashlib.sha256(json.dumps({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}, sort_keys=True).encode()).hexdigest()
    identity = {'sourceSha': sha, 'sourceState': 'uncommitted_candidate' if dirty else 'committed_source', 'sourceTreeHash': tree,
                'generatedAt': datetime.now(timezone.utc).isoformat(), 'executionState': 'candidate_local_only', 'productionVerified': False}
    metrics = []
    for metric_id, definition in catalog.items():
        group = next((group for group, ids in GROUP_IDS.items() if metric_id in ids), None)
        if group is None:
            raise ValueError('Missing metric disposition: ' + metric_id)
        source = SOURCE_GROUPS[group]
        activated = definition['status'] == 'activated_v1'
        disposition = 'canonical_implementation' if activated else 'owner_source_blocker' if group == 'marketing' or metric_id == 'csat' else 'implementation_task'
        replacement, comparison = None, None
        if not activated and metric_id in REPLACEMENTS:
            target, dimension = REPLACEMENTS[metric_id]
            disposition = 'explicitly_replaced_definition'
            replacement = {'canonicalId': target, 'dimensions': {'movement': dimension}, 'runtimeAliasInstalled': False}
            comparison = 'Same currency_minor/workspace interval; canonical net bridge and fixture exclusions govern. This replaces the proposal, never silently aliases or activates it.'
        elif not activated and metric_id in INCOMPATIBLE:
            target = INCOMPATIBLE[metric_id]
            other = catalog[target]
            comparison = {'candidateId': target, 'compatibleAlias': False,
                          'differences': {key: {'proposed': definition.get(key), 'canonical': other.get(key)}
                                          for key in ('unit', 'grain', 'definition', 'default_exclusions') if definition.get(key) != other.get(key)}}
        metrics.append({'id': metric_id, 'disposition': disposition, 'catalogStatus': definition['status'], 'version': definition['version'],
                        'definition': definition.get('definition'), 'unit': definition.get('unit'), 'grain': definition.get('grain'),
                        'scope': 'global_operations' if metric_id in ('phone_calls','api_errors','api_error_rate','api_latency','slo_burn') else group,
                        'sourceContractId': group, 'requiredSource': definition.get('source_contract'),
                        'queryAdapter': (definition.get('activation') or {}).get('liveAdapter'),
                        'queryTemplate': definition.get('query_template_ref'), 'exclusions': definition.get('default_exclusions', []),
                        'historyGate': source['history'], 'limitations': definition.get('limitations'), 'ownerDependencies': source['owner'],
                        'replacement': replacement, 'aliasComparison': comparison,
                        'validation': {'testPath': source['test'], 'productionState': 'not_run_permission_blocked'},
                        'nextAction': 'Verify fresh source→projection→receipt→UI/agent in staging and production.' if activated else source['history'] if disposition=='owner_source_blocker' else 'Qualify the stated definition/source; keep proposed until implementation and acceptance pass.'})
    write(args.out / 'metric-disposition.json', {**identity, 'count': len(metrics), 'metrics': metrics})
    features = feature_manifest({})
    for row in features:
        row['effectiveFlags'] = {flag: None for flag in row['effectiveFlags']}
        row['blockers'] = [b for b in row['blockers'] if not b.startswith('flag_off:') and not b.startswith('config_missing:')]
        row['blockers'].append('fresh_effective_configuration_and_end_to_end_proof_required')
    write(args.out / 'activation-readiness.json', {**identity, 'features': features, 'acceptedOwnerDefaults': defaults(),
          'sourceVerification': {'database': 'production_read_only_dashboard_verified_connector_grant_mismatch', 'productionAliasSha': '6059664c049bc6eb4da6d533e8926a135ff7e22f',
                                 'deploymentId': 'dpl_6MgiST6Dnyf7ySDjmkKL5RjetcXX', 'configuration': 'audit_snapshot_not_fresh_effective_flags'}})
    contracts = []
    for group, source in SOURCE_GROUPS.items():
        contracts.append({'id': group, **source, 'transactionBoundary': 'Owning command/outbox transaction; callbacks authenticate provider signature; reader is separate and read-only.',
                          'actor': 'Verified customer member, system/provider, or authenticated Founder Ops owner; attribution is server-derived.',
                          'eventVsObservedTime': 'Product occurred_at vs recorded_at (new 088; legacy observed time NULL); AI started_at vs created_at; provider event_at vs received_at.',
                          'writerFailure': 'AI/product savepoint keeps customer request valid; bounded audit journal records failed/suspended receipts. Database-wide outages cannot journal and remain a coverage gap.',
                          'retentionDeletion': 'Owner approved immutable financial history. Candidate 088 retains observed financial versions and deletion tombstones in an original-tenant append-only archive, including an explicitly observed-existing snapshot. Earlier lost change history cannot be reconstructed. Telemetry recovery refuses deleted profiles/tenants and revoked members.',
                          'backfillCoverage': 'New failed/suspended AI/product batches only, from validated journal evidence. No fabricated historical attempts or knowledge time.',
                          'metricIds': GROUP_IDS[group]})
    write(args.out / 'source-contracts.json', {**identity, 'contracts': contracts})
    write(args.out / 'cutover-manifest.json', {**identity, 'mode': 'pending_qualification', 'approval': 'founder-owner-20261002', 'notBefore': None,
          'audiences': ['founder','customer'], 'channels': ['email','push','calls'], 'approvedCanary': {'founderEmails':3,'founderDevicePushes':3,'customerMessages':0},
          'dailyExternalSpendUsd':50,'warnPercent':80,'actualProviderCalls':0,
          'newEventsOnly': True, 'backlogDisposition': 'read_only_preserve_suppressed_unsent_uncertain_expired',
          'templateVersion': None, 'dedupe': 'Durable pre-egress hash/key; exact email payload only within 24h; push keys include device ID and never replay a committed uncertain dispatch.',
          'pending': ['existing verified Rafii/PostRiff sender domain', 'qualified provider billing ceiling', 'H5 owner device consent', 'staging schema and raw-body webhook canary']})
    write(args.out / 'canary-evidence.json', {**identity, 'real': {'state': 'not_run', 'providerCalls': 0, 'providerCostUsd': None,
          'reason': 'Owner defaults accepted; verified Rafii sender, device permission, staging/release gates and real delivery receipts still pending.'},
          'synthetic': {'state': 'tests_in_progress', 'evidence': []}, 'observation24Hours': {'state': 'not_started'}})
    print(json.dumps({'out': str(args.out), 'features': 24, 'metrics': 97, 'sourceTreeHash': tree}))


if __name__ == '__main__':
    main()
