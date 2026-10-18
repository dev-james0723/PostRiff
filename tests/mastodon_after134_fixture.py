"""Locked synthetic management schema setup for the existing disposable cloud PG suites.

Historical registry values below are synthetic precondition fixtures, never evidence
that those production migrations were executed in this disposable database.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

import psycopg
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/mastodon_after134_20261018'


def prepare(connection, dsn, *, fixture_route='management'):
    # Each caller selects one existing harness identity; never accept arbitrary
    # ports/directories merely because an address is loopback.
    routes = {'management': ('55438', ('postriff-cw-pg-', 'consumer-pg-')),
              'management-browser': ('55448', ('postriff-dev-pg-',))}
    if fixture_route not in routes:
        raise RuntimeError('Unknown disposable Mastodon schema fixture route.')
    expected_port, expected_prefixes = routes[fixture_route]
    if fixture_route == 'management-browser' and os.environ.get('POSTRIFF_MASTODON_AFTER134_BROWSER_FIXTURE') != '1':
        raise RuntimeError('Browser schema setup requires the explicit after134 browser fixture opt-in.')
    if (not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true')
            or os.environ.get('POSTRIFF_MASTODON_AFTER134_FIXTURE') != '1'):
        raise RuntimeError('Use only the approved management-after134-only disposable cloud PG route.')
    params = conninfo_to_dict(dsn)
    if (set(params) - {'host', 'port', 'dbname', 'user'} or params.get('host') != '127.0.0.1'
            or params.get('port') != expected_port or params.get('dbname') != 'postgres'):
        raise RuntimeError('Only the existing disposable loopback fixture DSN is accepted.')
    if any(os.environ.get(k) for k in ('PGHOSTADDR', 'PGSERVICE', 'PGPASSWORD', 'PGSSLCERT', 'PGSSLKEY')):
        raise RuntimeError('Unexpected credential or routing environment in synthetic PG fixture.')
    lock = json.loads((FIXTURE / 'FIXTURE-LOCK.json').read_text())
    for name, expected in lock['files'].items():
        if hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Management fixture source hash changed: ' + name)
    meta = json.loads((FIXTURE / 'PROPOSAL-METADATA.json').read_text())
    core = (FIXTURE / meta['custom_ledger_name']).read_text()
    if hashlib.sha256(core.encode()).hexdigest() != meta['payload_sha256']:
        raise RuntimeError('Future core payload hash mismatch.')
    cache = (ROOT / 'migrations/postriff/134_mastodon_connect_applications.sql').read_text()
    if hashlib.sha256(cache.encode()).hexdigest() != meta['requires134_sha256']:
        raise RuntimeError('Current Connect134 source hash mismatch.')
    # The locked SQL itself contains the exact two prerequisite ledger snapshots.
    expected = [json.loads(s) for s in re.findall(r'\$expected\$(.*?)\$expected\$::jsonb', core, re.S)]
    native, custom = expected[:2]
    with connection() as db:
        address, port, database, data = db.execute("SELECT host(inet_server_addr()),inet_server_port(),current_database(),current_setting('data_directory')").fetchone()
        if (address != '127.0.0.1' or str(port) != expected_port or database != 'postgres'
                or not Path(data).parent.name.startswith(expected_prefixes)):
            raise RuntimeError('Server is not the existing harness-owned disposable cluster.')
        marker = db.execute("SELECT to_regclass('postriff_private.mastodon_after134_fixture')").fetchone()[0]
        if marker:
            stored = db.execute('SELECT core_sha256,cache_sha256 FROM postriff_private.mastodon_after134_fixture').fetchall()
            if stored != [(meta['payload_sha256'], meta['requires134_sha256'])]:
                raise RuntimeError('Unrecognized synthetic fixture marker; do not adopt existing schema.')
            _postcheck(db, meta)
            return
        for name in ('pr_mastodon_applications', 'pr_mastodon_actions', 'pr_mastodon_health'):
            if db.execute('SELECT to_regclass(%s)', ('public.' + name,)).fetchone()[0]:
                raise RuntimeError('Unexpected pre-existing Mastodon schema in clean fixture.')
        # Verify the real payload's first fail-closed guard before applying134.
        try:
            with db.transaction():
                db.execute(core, prepare=False)
        except psycopg.errors.RaiseException as error:
            if 'approved Connect134 has not been applied' not in str(error):
                raise
        else:
            raise AssertionError('Future management core accepted a missing134 prerequisite.')
        # Model only the current live provider precondition, within this synthetic DB.
        old = db.execute("SELECT pg_get_constraintdef(oid,true) FROM pg_constraint WHERE conrelid='public.pr_metric_reads'::regclass AND conname='pr_metric_reads_provider_check'").fetchone()[0]
        if set(re.findall(r"'([^']+)'::text", old)) != {'threads', 'instagram'}:
            raise RuntimeError('Unexpected base fixture provider constraint; refresh test setup explicitly.')
        db.execute('ALTER TABLE public.pr_metric_reads DROP CONSTRAINT pr_metric_reads_provider_check')
        db.execute("ALTER TABLE public.pr_metric_reads ADD CONSTRAINT pr_metric_reads_provider_check CHECK(provider IN ('threads','instagram','pinterest'))")
        if db.execute("SELECT to_regclass('supabase_migrations.schema_migrations'),to_regclass('postriff_private.schema_migrations')").fetchone() != (None, None):
            raise RuntimeError('Synthetic baseline ledgers already exist; refusing implicit adoption.')
        db.execute('CREATE SCHEMA supabase_migrations')
        db.execute('CREATE TABLE supabase_migrations.schema_migrations(version text PRIMARY KEY,name text NOT NULL)')
        db.execute('CREATE TABLE postriff_private.schema_migrations(name text PRIMARY KEY,sha256 text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())')
        with db.cursor() as cur:
            cur.executemany('INSERT INTO supabase_migrations.schema_migrations(version,name) VALUES(%s,%s)', [(r['version'], r['name']) for r in native])
            cur.executemany('INSERT INTO postriff_private.schema_migrations(name,sha256) VALUES(%s,%s)', [(r['name'], r['sha256']) for r in custom])
        db.execute(cache, prepare=False)
        db.execute('INSERT INTO postriff_private.schema_migrations(name,sha256) VALUES(%s,%s)', ('134_mastodon_connect_applications.sql', meta['requires134_sha256']))
        db.execute("INSERT INTO supabase_migrations.schema_migrations(version,name) VALUES('20261018160405','mastodon_connect_applications_134_20261018')")
        workspace = str(uuid.uuid4())
        db.execute("INSERT INTO public.pr_workspaces(id,state) VALUES(%s,'{\"syntheticPinterestBeforeCore\":true}')", (workspace,))
        db.execute("INSERT INTO public.pr_metric_reads(workspace_id,connection_id,provider,provider_post_id,read_offset,source,anchor_at,due_at) VALUES(%s,'synthetic-pinterest-before-core','pinterest','synthetic-pin','t0','verification',now(),now())", (workspace,))
        before = db.execute('SELECT to_jsonb(r) FROM public.pr_metric_reads r WHERE workspace_id=%s', (workspace,)).fetchall()
        db.execute(core, prepare=False)  # Exact locked source: no removed/replaced preflight.
        if before != db.execute('SELECT to_jsonb(r) FROM public.pr_metric_reads r WHERE workspace_id=%s', (workspace,)).fetchall():
            raise AssertionError('Existing synthetic Pinterest reading changed during core upgrade.')
        db.execute('INSERT INTO postriff_private.schema_migrations(name,sha256) VALUES(%s,%s)', (meta['custom_ledger_name'], meta['payload_sha256']))
        db.execute("INSERT INTO supabase_migrations.schema_migrations(version,name) VALUES('20261018160406',%s)", (meta['native_name'],))
        db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (workspace,))  # This fixture's row only.
    # Concurrent indexes require one autocommit command at a time, outside core DDL.
    indexes = (FIXTURE / 'SHARED-INDEXES-CONCURRENT-PROPOSAL.sql').read_text()
    end = indexes.index('END; $indexes_preflight$;') + len('END; $indexes_preflight$;')
    statements = re.findall(r'CREATE INDEX CONCURRENTLY\s+.*?;', indexes[end:], re.S)
    if len(statements) != 2:
        raise RuntimeError('Unexpected locked concurrent-index proposal structure.')
    with connection() as db:
        db.autocommit = True
        db.execute(indexes[:end], prepare=False)
        for statement in statements:
            db.execute(statement)
    with connection() as db:
        _postcheck(db, meta)
        db.execute('CREATE TABLE postriff_private.mastodon_after134_fixture(core_sha256 text NOT NULL,cache_sha256 text NOT NULL)')
        db.execute('INSERT INTO postriff_private.mastodon_after134_fixture VALUES(%s,%s)', (meta['payload_sha256'], meta['requires134_sha256']))
    print(json.dumps({'execution': 'synthetic disposable cloud PostgreSQL only', 'schema': meta['custom_ledger_name'],
                      'sha256': meta['payload_sha256'], 'connect134Sha256': meta['requires134_sha256'],
                      'historicalLedgers': 'synthetic precondition models; not production adoption',
                      'preexistingSyntheticPinterestRow': 'unchanged', 'production': 'NOT RUN'}))


def _postcheck(db, meta):
    for name, digest in (('134_mastodon_connect_applications.sql', meta['requires134_sha256']), (meta['custom_ledger_name'], meta['payload_sha256'])):
        assert db.execute('SELECT sha256 FROM postriff_private.schema_migrations WHERE name=%s', (name,)).fetchone() == (digest,)
    for table in ('pr_mastodon_applications', 'pr_mastodon_actions', 'pr_mastodon_health'):
        assert db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass', ('public.' + table,)).fetchone() == (True, True)
        assert db.execute("SELECT policyname,roles::text[],cmd,qual,with_check FROM pg_policies WHERE schemaname='public' AND tablename=%s", (table,)).fetchall() == [('service_only', ['service_role'], 'ALL', 'true', 'true')]
        for role in ('anon', 'authenticated'):
            assert not db.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')", (role, 'public.' + table)).fetchone()[0]
        for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE'):
            assert db.execute('SELECT has_table_privilege(%s,%s,%s)', ('service_role', 'public.' + table, privilege)).fetchone()[0]
    indexes = db.execute("SELECT c.relname,i.indisready,i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname IN ('pr_mastodon_metrics_retention','pr_mastodon_reads_retention') ORDER BY c.relname").fetchall()
    assert indexes == [('pr_mastodon_metrics_retention', True, True), ('pr_mastodon_reads_retention', True, True)]
