"""Acceptance-import SQL contracts in the existing disposable cloud PostgreSQL.

All credentials, attestations and PASS-shaped inputs are synthetic test fixtures.
They never establish real YouTube acceptance. No application DSN or Google calls.
Run fourth via scripts/postriff_disposable_postgres.py, after migration 089.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Cloud CI and the disposable PostgreSQL harness are required.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
import psycopg
from postriff_phase2.youtube.acceptance import AcceptanceError, make_preview, write_acceptance
import test_youtube_acceptance as fixtures

spec = importlib.util.spec_from_file_location('youtube_acceptance_cli', ROOT / 'scripts/youtube_acceptance.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
# Use only the harness's fixed loopback cluster; never POSTRIFF_DATABASE_URL.
DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
fixtures.BINDINGS = {**fixtures.BINDINGS, 'workspaceId': str(uuid4())}
BINDINGS = copy.deepcopy(fixtures.BINDINGS)
FOREIGN_WORKSPACE = str(uuid4())
FOREIGN_CHANNEL = 'UC' + 'b' * 22
FOREIGN_EVIDENCE = {'foreignWorkspaceSentinel': True}
PRESERVED = {'eligibility': {'live': {'verified': False, 'channelId': fixtures.CHANNEL}},
    'acceptance': {'reply': {'status': 'unverified', 'reference': 'synthetic-preservation-sentinel'}},
    'unrelated': {'keep': ['synthetic', 7]}}
PASSED = []


def connection(read_only=False):
    db = psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5)
    db.read_only = read_only
    return db


def begin(cursor):
    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    cursor.execute("SET LOCAL statement_timeout='5s'")


def settings(workspace=None):
    with connection(True) as db:
        return db.execute('SELECT monetary_authorized,memberships_authorized,evidence,updated_at FROM public.pr_youtube_settings WHERE workspace_id=%s AND connection_id=%s',
            (workspace or BINDINGS['workspaceId'], BINDINGS['connectionId'])).fetchone()


def db_preview(cursor, capabilities=('identity',), lock=False, bindings=None):
    args = fixtures.bundle(capabilities)
    args['current'] = cli.current_context(cursor, bindings or BINDINGS, set(), lock=lock)
    return make_preview(**args)


def preview(capabilities=('identity',)):
    with connection(True) as db, db.cursor() as cursor:
        begin(cursor)
        cursor.execute('SHOW transaction_read_only')
        assert cursor.fetchone() == ('on',)
        return db_preview(cursor, capabilities)


def apply(expected_digest, capabilities=('identity',)):
    # The production CLI rebuilds from locked current rows; it never applies an
    # old plan directly. Exercise that same contract against actual SQL here.
    with connection() as db, db.cursor() as cursor:
        begin(cursor)
        current_preview = db_preview(cursor, capabilities, lock=True)
        write_acceptance(cursor, current_preview, expected_digest)


def rejected(operation):
    try:
        operation()
    except AcceptanceError:
        return
    raise AssertionError('Acceptance contract unexpectedly permitted the operation.')


def check(label, condition=True):
    assert condition, label
    PASSED.append(label)


class IntentionalRollback(Exception):
    pass


try:
    with connection() as db:
        assert db.execute("SELECT to_regclass('public.pr_youtube_settings') IS NOT NULL").fetchone() == (True,)
        for workspace, channel in ((BINDINGS['workspaceId'], fixtures.CHANNEL), (FOREIGN_WORKSPACE, FOREIGN_CHANNEL)):
            db.execute('INSERT INTO public.pr_workspaces(id) VALUES(%s)', (workspace,))
            db.execute('''INSERT INTO public.pr_encrypted_credentials
                (workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes,updated_at)
                VALUES(%s,%s,'youtube',%s,'synthetic-not-a-token','synthetic-key',%s,%s)''',
                (workspace, BINDINGS['connectionId'], channel, [fixtures.MANAGE, fixtures.READ], fixtures.VERIFIED))
        db.execute('INSERT INTO public.pr_youtube_settings(workspace_id,connection_id,evidence) VALUES(%s,%s,%s::jsonb)',
            (FOREIGN_WORKSPACE, BINDINGS['connectionId'], json.dumps(FOREIGN_EVIDENCE)))

    # Rejection occurs before any private table access, even on a valid binding.
    with connection(True) as db, db.cursor() as cursor:
        begin(cursor)
        cursor.execute('SET LOCAL ROLE authenticated')
        rejected(lambda: cli.current_context(cursor, BINDINGS, set()))
    check('ordinary database role rejected')
    with connection(True) as db, db.cursor() as cursor:
        begin(cursor)
        cursor.execute('SET LOCAL ROLE service_role')
        context = cli.current_context(cursor, BINDINGS, set())
        check('trusted service role reads exact active credential', context['providerAccountId'] == fixtures.CHANNEL)
        check('missing settings default without insertion', context['settingsEvidence'] == {} and
            context['authorizations'] == {'monetary': False, 'memberships': False})
    assert settings() is None

    for changed in ({'workspaceId': str(uuid4())}, {'connectionId': 'youtube:missing-connection'}):
        with connection(True) as db, db.cursor() as cursor:
            begin(cursor)
            rejected(lambda: cli.current_context(cursor, {**BINDINGS, **changed}, set()))
    for changed in ({'workspaceId': FOREIGN_WORKSPACE}, {'channelId': FOREIGN_CHANNEL}):
        with connection(True) as db, db.cursor() as cursor:
            begin(cursor)
            rejected(lambda: db_preview(cursor, bindings={**BINDINGS, **changed}))
    check('workspace connection and channel bindings cannot substitute foreign credentials')

    initial = preview()
    check('read-only preview does not create settings', settings() is None and initial['execution'] == 'PREVIEW' and not initial['applied'])
    try:
        with connection(True) as db, db.cursor() as cursor:
            begin(cursor)
            value = db_preview(cursor)
            write_acceptance(cursor, value, value['digest'])
        raise AssertionError('A read-only transaction allowed an acceptance write.')
    except psycopg.errors.ReadOnlySqlTransaction:
        pass
    check('PostgreSQL enforces preview read-only even if writer is called', settings() is None)

    # A missing settings row cannot itself be locked. Migration 089's credential
    # FK must block a concurrent first insert while apply owns the parent lock.
    with connection() as db, db.cursor() as cursor:
        begin(cursor)
        cli.current_context(cursor, BINDINGS, set(), lock=True)
        try:
            with connection() as other:
                other.execute("SET LOCAL lock_timeout='250ms'")
                other.execute('INSERT INTO public.pr_youtube_settings(workspace_id,connection_id) VALUES(%s,%s)',
                    (BINDINGS['workspaceId'], BINDINGS['connectionId']))
            raise AssertionError('Missing-row insert did not respect the credential FK lock.')
        except psycopg.errors.LockNotAvailable:
            pass
    check('credential foreign key serializes first settings insert', settings() is None)

    rejected(lambda: apply('0' * 64))
    check('wrong preview digest performs no insertion', settings() is None)
    apply(initial['digest'])
    inserted = settings()
    check('new settings contain only selected acceptance with sensitive flags false',
        inserted[:2] == (False, False) and set(inserted[2]) == {'acceptance'} and set(inserted[2]['acceptance']) == {'identity'})

    with connection() as db:
        db.execute('UPDATE public.pr_youtube_settings SET evidence=%s::jsonb,monetary_authorized=true,memberships_authorized=false WHERE workspace_id=%s AND connection_id=%s',
            (json.dumps(PRESERVED), BINDINGS['workspaceId'], BINDINGS['connectionId']))
    before = settings()
    reviewed = preview()
    assert settings() == before
    apply(reviewed['digest'])
    merged = settings()
    check('acceptance merge preserves authorization flags eligibility and unrelated evidence',
        merged[:2] == before[:2] and merged[2]['eligibility'] == PRESERVED['eligibility'] and
        merged[2]['unrelated'] == PRESERVED['unrelated'] and merged[2]['acceptance']['reply'] == PRESERVED['acceptance']['reply'] and
        set(merged[2]['acceptance']) == {'identity', 'reply'})
    assert settings(FOREIGN_WORKSPACE)[2] == FOREIGN_EVIDENCE
    check('exact-workspace apply leaves same connection in foreign workspace untouched')

    old = preview()
    with connection() as db:
        db.execute('UPDATE public.pr_youtube_settings SET memberships_authorized=true WHERE workspace_id=%s AND connection_id=%s',
            (BINDINGS['workspaceId'], BINDINGS['connectionId']))
    changed = settings()
    rejected(lambda: apply(old['digest']))
    check('changed settings snapshot rejects old digest without write', settings() == changed)
    old = preview()
    with connection() as db:
        db.execute('UPDATE public.pr_encrypted_credentials SET updated_at=updated_at+interval \'1 second\' WHERE workspace_id=%s AND connection_id=%s',
            (BINDINGS['workspaceId'], BINDINGS['connectionId']))
    rejected(lambda: apply(old['digest']))
    check('changed credential snapshot rejects old digest without write', settings() == changed)

    before = settings()
    try:
        with connection() as db, db.cursor() as cursor:
            begin(cursor)
            value = db_preview(cursor, ('connected',), lock=True)
            write_acceptance(cursor, value, value['digest'])
            cursor.execute('SELECT evidence FROM public.pr_youtube_settings WHERE workspace_id=%s AND connection_id=%s',
                (BINDINGS['workspaceId'], BINDINGS['connectionId']))
            assert 'connected' in cursor.fetchone()[0]['acceptance']
            raise IntentionalRollback()
    except IntentionalRollback:
        pass
    check('error after SQL write rolls back all acceptance changes', settings() == before)

    with connection() as db:
        db.execute('DELETE FROM public.pr_youtube_settings WHERE workspace_id=%s AND connection_id=%s',
            (BINDINGS['workspaceId'], BINDINGS['connectionId']))
    missing = preview()
    with connection() as db:
        db.execute('INSERT INTO public.pr_youtube_settings(workspace_id,connection_id,evidence,monetary_authorized) VALUES(%s,%s,%s::jsonb,true)',
            (BINDINGS['workspaceId'], BINDINGS['connectionId'], json.dumps(PRESERVED)))
    appeared = settings()
    rejected(lambda: apply(missing['digest']))
    check('settings created after preview reject old missing-row snapshot', settings() == appeared)
finally:
    with connection() as db:
        db.execute('DELETE FROM public.pr_workspaces WHERE id IN (%s,%s)', (BINDINGS['workspaceId'], FOREIGN_WORKSPACE))

print(json.dumps({'status': 'pass', 'execution': 'disposable-cloud-postgres; synthetic contract fixtures; NOT real YouTube E2E',
    'checks': PASSED}))
