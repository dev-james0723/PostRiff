"""Pinned additive release runner. Default read-only; no credentials/customer rows in output."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import psycopg

SQL_SHA = '78a23c99f1b876426fa4aa5193da67f2e9941901baee89502004ae84f9131554'
PROJECT = 'buoyhkbodnhzngaotoel'
TABLES = ('pr_phone_inbound_codes', 'pr_phone_inbound_sessions')
COLUMNS = {
    TABLES[0]: {'id':'uuid', 'user_id':'uuid', 'workspace_id':'uuid', 'conversation_id':'uuid',
        'code_hash':'text', 'maximum_millicredits':'bigint', 'created_at':'timestamp with time zone',
        'expires_at':'timestamp with time zone', 'consumed_at':'timestamp with time zone',
        'revoked_at':'timestamp with time zone', 'call_id':'uuid'},
    TABLES[1]: {'provider_call_ref':'text', 'caller_hash':'text', 'started_at':'timestamp with time zone',
        'ended_at':'timestamp with time zone', 'attempts':'integer', 'call_id':'uuid'},
}
REQUIRED = {TABLES[0]: {'id','user_id','workspace_id','code_hash','created_at','expires_at'},
            TABLES[1]: {'provider_call_ref','caller_hash','started_at','attempts'}}

def say(**data):
    print('INBOUND-042: ' + json.dumps(data, sort_keys=True), flush=True)

def presence(db):
    tables = [bool(db.execute('SELECT to_regclass(%s)', ('public.'+t,)).fetchone()[0]) for t in TABLES]
    col = db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
                     "AND table_name='pr_phone_calls' AND column_name='direction'").fetchone()
    return tables + [bool(col)]

def shape(db):
    result = {}
    for table in TABLES:
        columns = list(db.execute("SELECT column_name,data_type,is_nullable,column_default FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s ORDER BY column_name", (table,)))
        constraints = list(db.execute("SELECT contype::text,pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid=%s::regclass ORDER BY contype,pg_get_constraintdef(oid)", ('public.'+table,)))
        policies = list(db.execute("SELECT policyname,roles::text,cmd,qual,with_check FROM pg_policies "
            "WHERE schemaname='public' AND tablename=%s ORDER BY policyname", (table,)))
        flags = db.execute("SELECT relrowsecurity,relforcerowsecurity, "
            "NOT EXISTS(SELECT 1 FROM aclexplode(coalesce(relacl,acldefault('r',relowner))) WHERE grantee=0) "
            "FROM pg_class WHERE oid=%s::regclass", ('public.'+table,)).fetchone()
        grants = {role: [db.execute('SELECT has_table_privilege(%s,%s,%s)', (role,'public.'+table,priv)).fetchone()[0]
                        for priv in ('SELECT','INSERT','UPDATE','DELETE')]
                  for role in ('anon','authenticated','service_role')}
        indexes = list(db.execute("SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND tablename=%s ORDER BY indexname", (table,)))
        result[table] = dict(columns=columns, constraints=constraints, policies=policies, flags=flags, grants=grants, indexes=indexes)
    result['direction'] = list(db.execute("SELECT data_type,is_nullable,column_default FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='pr_phone_calls' AND column_name='direction'"))
    result['direction_check'] = list(db.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE "
            "conrelid='public.pr_phone_calls'::regclass AND contype='c' AND conname='pr_phone_calls_direction_check'"))
    return result

def verify(db, expected):
    found = shape(db)
    # Compare canonical PostgreSQL metadata rehearsed from the exact SQL; no tenant data or role owner names.
    assert json.loads(json.dumps(found)) == expected, 'schema differs from rehearsed 042 shape'
    for table in TABLES:
        s = found[table]
        assert {r[0]:r[1] for r in s['columns']} == COLUMNS[table]
        assert {r[0] for r in s['columns'] if r[2]=='NO'} == REQUIRED[table]
        assert all(s['flags']) and not any(s['grants']['anon']) and not any(s['grants']['authenticated'])
        assert all(s['grants']['service_role'])
        assert s['policies'] == [('service_only','{service_role}','ALL','true','true')]

def run(db, sql, expected, apply=False):
    with db.transaction():
        if apply:
            db.execute("SET LOCAL lock_timeout='10s'")
            db.execute("SET LOCAL statement_timeout='60s'")
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended('postriff-migrations',0))")
        else:
            db.execute('SET TRANSACTION READ ONLY')
        assert all(db.execute('SELECT to_regclass(%s) IS NOT NULL', ('public.'+t,)).fetchone()[0]
                   for t in ('pr_phone_calls','pr_profiles','pr_workspaces','pr_conversations')), 'prerequisite missing'
        before = presence(db)
        say(step='before', objects=before, ledger=bool(db.execute("SELECT to_regclass('postriff_private.schema_migrations')").fetchone()[0]))
        assert not any(before) or all(before), 'partial 042 shape; refusing changes'
        if all(before):
            verify(db, expected)
            say(step='verified', applied=False, already_present=True)
            return
        if not apply:
            say(step='plan', pending=['042_phone_inbound.sql'])
            return
        db.execute(sql, prepare=False)
        verify(db, expected)
        if db.execute("SELECT to_regclass('postriff_private.schema_migrations')").fetchone()[0]:
            row=db.execute("SELECT sha256 FROM postriff_private.schema_migrations WHERE name='042_phone_inbound.sql'").fetchone()
            assert not row or row[0]==SQL_SHA, 'ledger checksum conflict'
            if not row:
                db.execute("INSERT INTO postriff_private.schema_migrations(name,sha256) VALUES('042_phone_inbound.sql',%s)",(SQL_SHA,))
        say(step='verified', applied=True, already_present=False)
    say(step='committed', migration='042_phone_inbound.sql', sha256=SQL_SHA)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    sql=Path('042_phone_inbound.sql').read_bytes()
    assert hashlib.sha256(sql).hexdigest()==SQL_SHA, 'SQL checksum mismatch'
    dsn=os.environ['POSTRIFF_DATABASE_URL']
    params=psycopg.conninfo.conninfo_to_dict(dsn)
    host=params.get('host',''); user=params.get('user','')
    assert (host=='db.'+PROJECT+'.supabase.co' or (host.endswith('.pooler.supabase.com') and user=='postgres.'+PROJECT)), 'unexpected database target'
    assert os.environ.get('VERCEL_ENV')=='production', 'runner requires production environment'
    assert os.environ.get('VERCEL_PROJECT_ID')=='prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L', 'unexpected Vercel project'
    expected=json.loads(Path('expected-shape.json').read_text())
    say(step='target', project=PROJECT, mode='apply' if args.apply else 'read-only')
    safe=('RAFII_PHONE_ENABLED','RAFII_PHONE_PROVIDER','RAFII_PHONE_MAX_SECONDS','RAFII_PHONE_USD_MICRO_PER_MINUTE',
          'RAFII_PHONE_DAILY_USD_MICRO','RAFII_PHONE_INBOUND_ENABLED','RAFII_PHONE_INBOUND_AUTH_DAILY_USD_MICRO')
    say(step='configuration', values={k:os.environ.get(k) for k in safe})
    with psycopg.connect(dsn,autocommit=True,prepare_threshold=None,connect_timeout=15) as db:
        run(db,sql.decode(),expected,args.apply)

if __name__=='__main__':
    try: main()
    except Exception as error:
        say(step='error',error_type=type(error).__name__)
        sys.exit(1)
