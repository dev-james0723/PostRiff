"""SHA-pinned additive Trend release migration. Plan first, apply that exact plan.

Uses an existing migration connection in RAFII_TREND_MIGRATION_DSN. Never logs
the connection string or credentials. Identity, the entire prior checksum ledger,
pending files and the allowed migration set must still match at execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import postriff_migrate as migrations

# The concurrent Phone release is now in the integrated base. Preserve its
# exact additive enum migration on staging instead of skipping a base dependency.
COMPATIBILITY_DEPENDENCIES = {
    '036_dial_phone_provider.sql': 'd0c9ccd280c96e33b2ff75d52a3746fdb523b364547f4b51c377b5a5d2b7f554',
}
ALLOWED = {'035_growth_metric_reads.sql', '040_social_trend_intelligence.sql'} | COMPATIBILITY_DEPENDENCIES.keys()
PROJECTS = {'staging': 'oxacvkhpfgytkepxcaqh', 'production': 'buoyhkbodnhzngaotoel'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_identity(params, target):
    ref = PROJECTS[target]
    host = params.get('host', '')
    user = params.get('user', '')
    direct = host == 'db.' + ref + '.supabase.co' and user == 'postgres'
    pooler = host.endswith('.pooler.supabase.com') and user == 'postgres.' + ref
    if not (direct or pooler) or params.get('dbname') != 'postgres' or str(params.get('port', '5432')) != '5432':
        raise ValueError('release_database_identity_mismatch')


def make_plan(db, target, *, paths=None):
    rows = migrations.plan(db, paths)
    if any(r['sha256'] != COMPATIBILITY_DEPENDENCIES[r['name']]
           for r in rows if r['name'] in COMPATIBILITY_DEPENDENCIES):
        raise ValueError('compatibility_migration_digest_mismatch')
    pending = {r['name'] for r in rows if r['status'] == 'PENDING'}
    if not pending <= ALLOWED:
        raise ValueError('unreviewed_migration_dependency')
    body = {'schema': 'rafii.trend-migration-plan.v1', 'target': target,
            'project_ref': PROJECTS[target], 'migrations': rows,
            'rollback': 'disable trend dispatch and UI; preserve deletion sweeper and additive tables'}
    return {**body, 'digest': digest(body)}


def apply_plan(db, plan, *, paths=None):
    if plan.get('target') not in PROJECTS or plan.get('digest') != digest({k: v for k, v in plan.items() if k != 'digest'}):
        raise ValueError('migration_plan_digest_mismatch')
    with db.transaction():
        db.execute("SET LOCAL lock_timeout = '5s'")
        db.execute("SET LOCAL statement_timeout = '60s'")
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended('postriff-migrations',0))")
        actual = make_plan(db, plan['target'], paths=paths)
        if actual != plan:
            raise ValueError('migration_plan_stale')
        result = migrations.apply(db, paths)
        verified = migrations.plan(db, paths)
        if any(r['status'] != 'APPLIED' for r in verified):
            raise ValueError('migration_postcondition_failed')
    return {'schema': 'rafii.trend-migration-result.v1', 'target': plan['target'],
            'project_ref': plan['project_ref'], 'plan_digest': plan['digest'],
            'applied': [r for r in result if r['status'] == 'PENDING'],
            'verified': verified, 'status': 'applied_and_checksums_verified'}


def main():
    import psycopg
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('plan', 'apply'))
    parser.add_argument('--target', choices=tuple(PROJECTS), required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    params = psycopg.conninfo.conninfo_to_dict(os.environ.get('RAFII_TREND_MIGRATION_DSN', ''))
    validate_identity(params, args.target)
    params.update(sslmode='require', connect_timeout=10)
    if args.mode == 'plan':
        params['options'] = '-c default_transaction_read_only=on -c statement_timeout=10000'
    with psycopg.connect(**params, autocommit=True) as db:
        if args.mode == 'plan':
            result = make_plan(db, args.target)
            args.plan.write_text(json.dumps(result, indent=2) + '\n')
        else:
            if not args.receipt:
                parser.error('apply requires --receipt')
            plan = json.loads(args.plan.read_text())
            if plan.get('target') != args.target:
                raise ValueError('migration_target_mismatch')
            result = apply_plan(db, plan)
            args.receipt.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'execution': args.mode, 'target': args.target,
                      'status': result.get('status', 'reviewable_plan_saved'),
                      'plan_digest': result.get('plan_digest', result.get('digest'))}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Driver exceptions can contain connection data; keep them out of receipts.
        print(json.dumps({'status': 'migration_failed_closed', 'error_type': type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
