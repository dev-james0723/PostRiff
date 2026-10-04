"""SHA-pinned, workspace-local Stage 2 operator. No provider call or flag mutation.

Use plan before apply. Configure Vercel flags separately after apply verification.
Rollback is flag-first, then revoke. All output contains only codes/counts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]

from postriff_phase2.growth.trends.activation import (OPERATION, POLICY_VERSION, PROVIDER,
                                                     candidate)
from postriff_phase2.growth.trends.contracts import ContractError, canonical, uuid
from postriff_phase2.growth.trends.jobs import TrendJobs
from postriff_phase2.growth.trends.providers.bluesky import PROTOCOL
from postriff_phase2.growth.trends.revocation import revoke_policy
from postriff_phase2.growth.trends.store import TrendStore, row, rows
from trend_release_migrate import validate_identity

ALIAS = 'https://postriff-phase2-private.vercel.app'
PROJECT = 'postriff-phase2-private'
TEAM = 'jamesau0723-6572s-projects'
REQUIRED_ON = ('RAFII_TREND_INTELLIGENCE_ENABLED', 'RAFII_TREND_RADAR_ENABLED',
               'RAFII_TREND_TRUST_RECEIPTS_ENABLED')
REQUIRED_OFF = ('RAFII_TREND_MODEL_ENRICHMENT_ENABLED', 'RAFII_TREND_NOTIFICATIONS_ENABLED',
                'POSTRIFF_METRIC_READS')


def _run(*argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=30).stdout


def production_state(expected_sha, workspace_id):
    """Compare the live alias, Git source, allowlist and egress flags."""
    if not re.fullmatch(r'[a-f0-9]{40}', expected_sha):
        raise ContractError('release_sha_invalid')
    deployed = json.loads(_run('vercel', 'inspect', ALIAS, '--json'))
    deployment_id = deployed.get('id')
    if (deployed.get('target') != 'production' or deployed.get('readyState') != 'READY'
            or ALIAS.removeprefix('https://') not in deployed.get('aliases', [])):
        raise ContractError('production_alias_unverified')
    detail = json.loads(_run('vercel', 'api', '/v13/deployments/' + deployment_id,
                             '--scope', TEAM, '--raw'))
    source = detail.get('gitSource') or {}
    if source.get('sha') != expected_sha or source.get('ref') != 'consumer-saas':
        raise ContractError('production_sha_mismatch')
    with tempfile.TemporaryDirectory(prefix='trend-stage2-') as directory:
        dest = Path(directory) / 'production.env'
        _run('vercel', 'env', 'pull', str(dest), '--project', PROJECT,
             '--environment', 'production', '--yes')
        values = {}
        for line in dest.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                key, raw = line.split('=', 1)
                value = shlex.split(raw)
                values[key] = value[0] if value else ''
    allowed = [x.strip() for x in values.get('RAFII_TREND_WORKSPACE_ALLOWLIST', '').split(',') if x.strip()]
    if allowed != [uuid(workspace_id)]:
        raise ContractError('workspace_allowlist_mismatch')
    if any(values.get(name) not in ('1', 'true') for name in REQUIRED_ON):
        raise ContractError('stage1_flags_unverified')
    if any(values.get(name, '').lower() in ('1', 'true') for name in REQUIRED_OFF):
        raise ContractError('excluded_feature_enabled')
    permitted = values.get('RAFII_TREND_ALLOWED_OPERATIONS', '')
    if permitted not in ('', PROVIDER + ':' + OPERATION):
        raise ContractError('other_provider_enabled')
    return {'deployment_id': deployment_id, 'sha': expected_sha,
            'provider_operations': values.get('RAFII_TREND_PROVIDER_OPERATIONS_ENABLED', '').lower() in ('1', 'true'),
            'allowed_operations': permitted}


def snapshot(store, workspace_id, *, cursor=None):
    scope = 'workspace:' + uuid(workspace_id)
    with store.transaction(cursor) as cur:
        cur.execute('SELECT operations,valid_from,expires_at,manifest,revoked_at FROM public.pr_trend_provider_contracts WHERE provider_id=%s AND version=%s',
                    (PROVIDER, PROTOCOL))
        contract = row(cur)
        cur.execute('SELECT manifest,provider_contract_version,revoked_at FROM public.pr_trend_source_policies WHERE scope_key=%s AND provider_id=%s AND version=%s',
                    (scope, PROVIDER, POLICY_VERSION))
        policy = row(cur)
        cur.execute("SELECT budget_key,dimension,cap_micro_usd,period_start,period_end FROM public.pr_trend_budget_limits WHERE budget_key=ANY(%s)",
                    ([f'trend:stage2:{dimension}:{workspace_id}' for dimension in ('system', 'provider', 'workspace')],))
        budgets = {x['budget_key']: x for x in rows(cur)}
        cur.execute("""SELECT count(*) AS jobs, count(*) FILTER (WHERE state='succeeded') AS succeeded
            FROM public.pr_trend_jobs WHERE scope_key=%s AND provider_id=%s AND source_policy_version=%s""",
                    (scope, PROVIDER, POLICY_VERSION))
        jobs = row(cur)
        cur.execute('SELECT status,observed_at,notes_code FROM public.pr_trend_source_health WHERE scope_key=%s AND provider_id=%s',
                    (scope, PROVIDER))
        health = row(cur)
        return {'contract': contract, 'policy': policy, 'budgets': budgets, 'jobs': jobs, 'health': health}


def compare(current, desired):
    contract = desired['contract']
    existing = current['contract']
    expected = {k: contract[k] for k in ('operations', 'valid_from', 'expires_at', 'manifest')}
    out = {'contract': 'create' if existing is None else
           'match' if not existing['revoked_at'] and all(existing[k] == v for k, v in expected.items()) else 'conflict'}
    policy = current['policy']
    out['policy'] = ('create' if policy is None else 'match' if not policy['revoked_at']
                     and policy['provider_contract_version'] == contract['version']
                     and policy['manifest'] == desired['policy'] else 'conflict')
    out['budgets'] = {}
    for budget in desired['budgets']:
        key = budget['budget_key']
        old = current['budgets'].get(key)
        out['budgets'][budget['dimension']] = ('create' if old is None else
            'match' if all(old[k] == v for k, v in budget.items()) else 'conflict')
    return out


def audit_release_schema(store):
    """Fail before any write when the production migration ledger or RLS drifts."""
    names = ('035_growth_metric_reads.sql', '040_social_trend_intelligence.sql')
    expected = {name: hashlib.sha256((ROOT / 'migrations/postriff' / name).read_bytes()).hexdigest()
                for name in names}
    tables = ('pr_trend_source_policies', 'pr_trend_provider_contracts',
              'pr_trend_budget_limits', 'pr_trend_jobs', 'pr_trend_ingestion_batches',
              'pr_trend_observations', 'pr_trend_source_health', 'pr_metric_reads')
    with store.transaction() as cur:
        cur.execute('SELECT name,sha256 FROM postriff_private.schema_migrations WHERE name=ANY(%s)', (list(names),))
        if {r['name']: r['sha256'] for r in rows(cur)} != expected:
            raise ContractError('production_migration_mismatch')
        cur.execute("""SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class
            WHERE relnamespace='public'::regnamespace AND relname=ANY(%s)""", (list(tables),))
        actual = {r['relname']: r for r in rows(cur)}
        if set(actual) != set(tables) or any(not r['relrowsecurity'] or not r['relforcerowsecurity']
                                             for r in actual.values()):
            raise ContractError('production_rls_mismatch')


def apply(store, workspace_id, desired):
    with store.transaction() as cur:
        cur.execute("SET LOCAL lock_timeout='5s'")
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('trend-stage2|' + workspace_id,))
        diff = compare(snapshot(store, workspace_id, cursor=cur), desired)
        if 'conflict' in (diff['contract'], diff['policy'], *diff['budgets'].values()):
            raise ContractError('immutable_activation_conflict')
        c = desired['contract']
        store.register_contract(c['provider_id'], c['version'], c['operations'], c['valid_from'],
                                c['expires_at'], c['manifest'], cursor=cur)
        store.register_policy(desired['policy'], provider_contract_version=c['version'], cursor=cur)
        jobs = TrendJobs(store)
        for b in desired['budgets']:
            jobs.configure_budget(b['budget_key'], b['dimension'], b['cap_micro_usd'],
                                  b['period_start'], b['period_end'], cursor=cur)
    return compare(snapshot(store, workspace_id), desired)


def main():
    import psycopg
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('status', 'plan', 'apply', 'revoke'))
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--provider', required=True)
    parser.add_argument('--operation', required=True)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--start-at')
    parser.add_argument('--expires-at')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        wid = uuid(args.workspace)
        if (args.provider, args.operation) != (PROVIDER, OPERATION):
            raise ContractError('operation_not_reviewed')
        production = production_state(args.expected_sha, wid)
        if args.mode in ('apply', 'revoke') and (production['provider_operations']
                or production['allowed_operations']):
            raise ContractError('disable_provider_flags_first')
        if args.mode in ('plan', 'apply'):
            if not args.start_at or not args.expires_at:
                raise ContractError('activation_window_required')
            desired = candidate(wid, args.start_at, args.expires_at,
                                now=datetime.now(timezone.utc).isoformat())
        if not os.environ.get('RAFII_TREND_MIGRATION_DSN'):
            raise ContractError('migration_dsn_missing')
        params = psycopg.conninfo.conninfo_to_dict(os.environ['RAFII_TREND_MIGRATION_DSN'])
        validate_identity(params, 'production')
        params.update(sslmode='require', connect_timeout=10)
        if args.mode in ('status', 'plan') or args.dry_run:
            params['options'] = '-c default_transaction_read_only=on -c statement_timeout=10000'
        store = TrendStore(lambda: psycopg.connect(**params))
        audit_release_schema(store)
        current = snapshot(store, wid)
        result = {'mode': args.mode, 'workspace': wid, 'provider_operation': PROVIDER + ':' + OPERATION,
                  'deployment_id': production['deployment_id'], 'release_sha': production['sha'],
                  'flags_enabled': production['provider_operations'],
                  'contract_state': 'absent' if current['contract'] is None else
                      'revoked' if current['contract']['revoked_at'] else 'present',
                  'policy_state': 'absent' if current['policy'] is None else
                      'revoked' if current['policy']['revoked_at'] else 'present',
                  'budget_dimensions': sorted(x['dimension'] for x in current['budgets'].values()),
                  'jobs': current['jobs'], 'source_health': current['health']}
        if args.mode in ('plan', 'apply'):
            result['candidate_digest'] = hashlib.sha256(canonical(desired).encode()).hexdigest()
            result['diff'] = compare(current, desired)
            if 'conflict' in (result['diff']['contract'], result['diff']['policy'], *result['diff']['budgets'].values()):
                raise ContractError('immutable_activation_conflict')
            if args.mode == 'apply' and not args.dry_run:
                if production_state(args.expected_sha, wid) != production:
                    raise ContractError('production_preflight_changed')
                result['verified_diff'] = apply(store, wid, desired)
        elif args.mode == 'revoke' and not args.dry_run:
            if production_state(args.expected_sha, wid) != production:
                raise ContractError('production_preflight_changed')
            result['revoked_count'] = revoke_policy(store, 'workspace:' + wid, PROVIDER, POLICY_VERSION)
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        code = exc.code if isinstance(exc, ContractError) else 'activation_precondition_failed'
        print(json.dumps({'status': 'blocked', 'reason_code': code}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
