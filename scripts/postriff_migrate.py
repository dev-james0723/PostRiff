"""Checksum-ledger hosted migrations. Default is a read-only plan, never implicit adoption.

Local apply only; remote production execution requires its separately reviewed runner/approval.
Historical bundles and local-only 003 are intentionally not in the hosted sequence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]

def migrations(root=ROOT):
    paths=sorted((root/'migrations/postriff').glob('[0-9][0-9][0-9]_*.sql'))
    numbers=[p.name.split('_')[0] for p in paths]
    if len(numbers)!=len(set(numbers)): raise ValueError('Duplicate migration numbers')
    return [p for p in paths if not p.name.startswith('003_')]

def checksum(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def body(path):
    # Existing scripts use optional outer transaction statements. Remove only
    # whole unindented BEGIN/COMMIT lines; function/DO bodies stay untouched.
    return re.sub(r'(?im)^(?:begin|commit);\s*$', '',path.read_text())

def plan(db, paths=None):
    paths=paths if paths is not None else migrations()
    exists=db.execute("SELECT to_regclass('postriff_private.schema_migrations')").fetchone()[0]
    ledger=dict(db.execute('SELECT name,sha256 FROM postriff_private.schema_migrations').fetchall()) if exists else {}
    expected={p.name:checksum(p) for p in paths}
    if any(name not in expected for name in ledger): raise ValueError('Database has migrations absent from this release; do not downgrade schema')
    if any(expected[name]!=value for name,value in ledger.items()): raise ValueError('Applied migration checksum differs; prepare a forward migration')
    if not ledger and db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
        raise ValueError('Existing schema has no verified ledger; explicit reviewed baseline adoption is required')
    return [{'name':p.name,'sha256':expected[p.name],'status':'APPLIED' if p.name in ledger else 'PENDING'} for p in paths]

def apply(db,paths=None):
    paths=paths if paths is not None else migrations()
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended('postriff-migrations',0))")
        rows=plan(db,paths)
        db.execute('CREATE SCHEMA IF NOT EXISTS postriff_private')
        db.execute('CREATE TABLE IF NOT EXISTS postriff_private.schema_migrations (name text primary key, sha256 text not null, applied_at timestamptz not null default now())')
        db.execute('REVOKE ALL ON postriff_private.schema_migrations FROM PUBLIC,anon,authenticated')
        for path,row in zip(paths,rows):
            if row['status']=='APPLIED': continue
            db.execute(body(path),prepare=False)
            db.execute('INSERT INTO postriff_private.schema_migrations(name,sha256) VALUES(%s,%s)',(path.name,row['sha256']))
    return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn',required=True,help='Use loopback disposable DB; never paste production secrets into logs')
    parser.add_argument('--apply-local',action='store_true')
    args=parser.parse_args()
    import psycopg
    params=psycopg.conninfo.conninfo_to_dict(args.dsn)
    if args.apply_local and params.get('host') not in ('127.0.0.1','localhost','::1'):
        parser.error('This runner only applies to an explicitly selected loopback database')
    with psycopg.connect(args.dsn,autocommit=True) as db:
        result=apply(db) if args.apply_local else plan(db)
    print(json.dumps({'execution':'local-apply' if args.apply_local else 'read-only-plan','migrations':result},indent=2))
if __name__=='__main__': main()
