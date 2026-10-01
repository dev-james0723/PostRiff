"""SHA-pinned additive Product Growth v2 release migration. Plan first, apply that exact plan.

Prepared for the release in docs/design/rafii-product-growth/RELEASE.md; running it against staging or production is a
real external operation that needs James's approval for that exact target (DECISIONS D-007). Uses an existing
migration connection in RAFII_GROWTH_MIGRATION_DSN and never logs the connection string or credentials. Identity, the
entire prior checksum ledger, the pending set and every pending file's reviewed digest must still match at execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import postriff_migrate as migrations

# Every file this release may apply, with the digest that was reviewed. A file whose bytes changed refuses the plan;
# anything else pending (another program's migration, a Founder file) refuses it too.
REVIEWED = {
    '047_inbox_operational_sync.sql': 'bcb9be5bf6069c1a80e94362cd473e436b0b56fa277baad51c7c7ba0fa369553',
    '048_pricing_credit_catalog_v2.sql': 'a36357deb034fa32faac10ac9c893d5b09087f01c9689e072e8764adef792ba0',
    '050_free_lifecycle_bootstrap.sql': 'f9aad0a010d8cb1205ed029112be5703c10631870ae3db09076e938b2fbb1e7d',
    '080_customer_results.sql': '846d2be456661a7d012e603bd3bdea54b06b5af61f929820149aa53958e0ed1f',
    '081_relationships.sql': '0d2b181d1d81d2467afa862cc6ac32e42ddea0c8c2368c60b56d996e76f73a33',
    '083_visual_packs.sql': '3aedc1a4a7746489bd85f797e2c0c462a9ea927a77a8291a9dd08800d137955c',
    '087_source_uploads.sql': '0acc1a3fcb0865431f4de2e2114951b7cdff93bdedc808654a064e91b5647b65',
}
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
    pending = [r for r in rows if r['status'] == 'PENDING']
    if any(r['name'] not in REVIEWED for r in pending):
        raise ValueError('unreviewed_migration_dependency')
    if any(r['sha256'] != REVIEWED[r['name']] for r in rows if r['name'] in REVIEWED):
        raise ValueError('reviewed_migration_digest_mismatch')
    body = {'schema': 'rafii.product-growth-migration-plan.v1', 'target': target,
            'project_ref': PROJECTS[target], 'migrations': rows,
            'rollback': 'switch the slice flags off; keep every additive table, row, hold and receipt (no down-migration)'}
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
    return {'schema': 'rafii.product-growth-migration-result.v1', 'target': plan['target'],
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
    params = psycopg.conninfo.conninfo_to_dict(os.environ.get('RAFII_GROWTH_MIGRATION_DSN', ''))
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
