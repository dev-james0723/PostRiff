"""Cloud-only history RLS/atomicity/concurrency/keyset acceptance; providerCalls=0."""
import copy
import json
import os
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('History acceptance requires the disposable cloud PostgreSQL harness, never the Mac.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.youtube import history

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
WORKSPACES = [str(uuid4()) for _ in range(3)]
CONNECTIONS = ['synthetic-history-one', 'synthetic-history-two']
NOW, PAIRS = 1_800_000_000, 80
METRICS = {'execution': 'synthetic-cloud-postgres-history', 'status': 'running',
           'providerCalls': 0, 'productionAcceptance': False, 'productionLoadAcceptance': False}


def connection():
    return psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                           options='-c statement_timeout=10000 -c lock_timeout=8000')


def draft(index, connection_id=CONNECTIONS[0]):
    return {'id': 'd' + format(index, '04d'), 'connectionId': connection_id,
            'channelId': 'UC' + 'a' * 22, 'status': 'proposed', 'digest': 'd' * 64,
            'variantId': 'variant-' + str(index), 'assetId': 'owned-original',
            'createdAt': NOW - 1000 + index, 'createdBy': 'synthetic-private-owner',
            'timing': {'timestamp': NOW - 1, 'timeZone': 'UTC'},
            'publishOptions': {'title': 'Synthetic owned video', 'description': 'Private exact description'}}


def policy(index, connection_id=CONNECTIONS[0]):
    return {'id': 'p' + format(index, '04d'), 'connectionId': connection_id,
            'status': 'active', 'digest': 'e' * 64, 'endsAt': NOW - 1,
            'drafts': [{'id': draft(index)['id'], 'digest': 'd' * 64}],
            'createdAt': NOW - 900 + index, 'grantedBy': 'synthetic-private-owner',
            'grantedAt': NOW - 800, 'authorizationGeneration': uuid4().hex,
            'dispatchCounters': {'used': index}}


def state(pairs):
    return {'youtubeAgent': {'drafts': [draft(index) for index in range(pairs)],
                            'policies': [policy(index) for index in range(pairs)],
                            'counter': {'unchanged': 17}},
            'variants': [{'id': 'variant-' + str(index), 'text': 'Retain generated text'} for index in range(pairs)],
            'phase2': {'jobs': [], 'reviews': [], 'assets': [{'id': 'owned-original', 'objectName': 'private/original.mp4'}]}}


def seed(cur, workspace, value):
    cur.execute('INSERT INTO public.pr_workspaces(id,state) VALUES(%s,%s::jsonb)', (workspace, json.dumps(value)))
    for cid in CONNECTIONS:
        cur.execute("""INSERT INTO public.pr_encrypted_credentials
            (workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes)
            VALUES(%s,%s,'youtube',%s,'synthetic-encrypted-only','synthetic-key','{}')""",
            (workspace, cid, 'UC' + 'a' * 22))


def expect_alpha(code, run):
    try:
        run()
    except AlphaError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError('Expected a fail-closed history error')


def expect_sql(code, db, run):
    # A failed assertion never leaves the surrounding test transaction aborted.
    try:
        with db.transaction():
            run()
    except psycopg.Error as error:
        assert error.sqlstate == code, (error.sqlstate, code)
    else:
        raise AssertionError('Expected SQL privilege/immutability rejection')


seeded = False
try:
    with connection() as db:
        observed = db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database()').fetchone()
        assert observed == ('127.0.0.1', 55438, 'postgres'), 'Disposable server guard mismatch'
        directory = Path(db.execute("SELECT current_setting('data_directory')").fetchone()[0])
        assert directory.parent.name.startswith(('postriff-cw-pg-', 'consumer-pg-')), 'Fresh disposable cluster required'
        assert db.execute("SELECT count(*) FROM public.pr_encrypted_credentials WHERE provider='youtube'").fetchone()[0] == 0
        assert not history.schema_ready(db.cursor()), 'Use a fresh cluster so missing-migration gating is exercised'
        expect_alpha(history.UNAVAILABLE, lambda: history.page(db.cursor(), WORKSPACES[0], CONNECTIONS[0], 'draft'))
        assert db.execute('SELECT to_regclass(%s)', (history.TABLE,)).fetchone()[0] is None
        sql = (ROOT / 'migrations/postriff/105_youtube_agent_history.sql').read_text()
        db.execute(sql)
        db.execute(sql)  # Reviewed migration candidate is replayable.
        assert history.schema_ready(db.cursor())
        flags = db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (history.TABLE,)).fetchone()
        assert flags == (True, True)
        original = state(PAIRS)
        seed(db.cursor(), WORKSPACES[0], original)
        seed(db.cursor(), WORKSPACES[1], state(2))
        seed(db.cursor(), WORKSPACES[2], state(2))
    seeded = True

    # Eight callers serialize against one row. Exactly one immutable record per
    # kind/id, <=50 per invocation, no duplicate revision or lost compaction.
    def compact(_index):
        with connection() as db, db.cursor() as cur:
            cur.execute('SET LOCAL ROLE service_role')
            return history.archive_and_compact(cur, WORKSPACES[0], CONNECTIONS[0], NOW)
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(compact, range(8)))
    assert sum(r['archived'] for r in receipts) == PAIRS * 2
    assert all(0 <= r['archived'] <= 50 for r in receipts)
    with connection() as db:
        revision, saved = db.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[0],)).fetchone()
        assert saved['youtubeAgent']['drafts'] == saved['youtubeAgent']['policies'] == []
        assert saved['variants'] == original['variants'] and saved['phase2'] == original['phase2']
        assert saved['youtubeAgent']['counter'] == original['youtubeAgent']['counter']
        assert revision == 1 + sum(r['archived'] > 0 for r in receipts)
        rows = db.execute("SELECT record_kind,record_id,record FROM public.pr_youtube_agent_history WHERE workspace_id=%s", (WORKSPACES[0],)).fetchall()
        originals = {('draft', d['id']): d for d in original['youtubeAgent']['drafts']}
        originals.update({('policy', p['id']): p for p in original['youtubeAgent']['policies']})
        assert len(rows) == len(originals) and {(kind, rid): record for kind, rid, record in rows} == originals
    METRICS['concurrency'] = {'callers': 8, 'exactRecords': PAIRS * 2, 'duplicateArchives': 0,
                              'revisionFence': True, 'perInvocationBound': 50, 'originalMediaRetained': True}

    # Two workspaces and two exact connections have independent keyset scopes.
    with connection() as db, db.cursor() as cur:
        first = history.page(cur, WORKSPACES[0], CONNECTIONS[0], 'draft')
        assert len(first['items']) == 50 and first['nextCursor']
        second = history.page(cur, WORKSPACES[0], CONNECTIONS[0], 'draft', cursor=first['nextCursor'])
        assert len(second['items']) == 30 and second['nextCursor'] is None
        ids = [item['id'] for item in first['items'] + second['items']]
        assert len(set(ids)) == PAIRS
        for wid, cid, kind in ((WORKSPACES[1], CONNECTIONS[0], 'draft'),
                               (WORKSPACES[0], CONNECTIONS[1], 'draft'),
                               (WORKSPACES[0], CONNECTIONS[0], 'policy')):
            expect_alpha('youtube_agent_history_cursor', lambda wid=wid, cid=cid, kind=kind:
                         history.page(cur, wid, cid, kind, cursor=first['nextCursor']))
        assert history.page(cur, WORKSPACES[1], CONNECTIONS[0], 'draft')['items'] == []
        assert history.page(cur, WORKSPACES[0], CONNECTIONS[1], 'draft')['items'] == []
        public = json.dumps(first)
        assert all(secret not in public for secret in ('synthetic-private-owner', 'grantedBy',
                         'authorizationGeneration', 'Private exact description', 'fleetLease'))
    METRICS['keyset'] = {'pages': [50, 30], 'duplicates': 0, 'crossTenantCursorRejected': True,
                         'crossConnectionCursorRejected': True, 'crossKindCursorRejected': True,
                         'metadataOnly': True, 'reactivationAvailable': False}

    # Archive and state share caller rollback. Even a caught immutable conflict
    # rolls back all inserts inside the savepoint before any JSON compaction.
    with connection() as db:
        before = db.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[1],)).fetchone()
    try:
        with connection() as db:
            history.archive_and_compact(db.cursor(), WORKSPACES[1], CONNECTIONS[0], NOW)
            raise RuntimeError('Synthetic crash before caller commit')
    except RuntimeError:
        pass
    with connection() as db:
        assert db.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[1],)).fetchone() == before
        assert db.execute('SELECT count(*) FROM public.pr_youtube_agent_history WHERE workspace_id=%s', (WORKSPACES[1],)).fetchone()[0] == 0
        conflict = copy.deepcopy(before[1]['youtubeAgent']['policies'][0])
        conflict['dispatchCounters']['used'] = -1
        history._archive_record(db.cursor(), WORKSPACES[1], CONNECTIONS[0],
            {'recordKind': 'policy', 'recordId': conflict['id'], 'record': conflict})
    with connection() as db:
        expect_alpha('youtube_agent_history_conflict', lambda:
                     history.archive_and_compact(db.cursor(), WORKSPACES[1], CONNECTIONS[0], NOW))
        assert db.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[1],)).fetchone() == before
        assert db.execute('SELECT count(*) FROM public.pr_youtube_agent_history WHERE workspace_id=%s', (WORKSPACES[1],)).fetchone()[0] == 1
        # No d0000 insert from the failed group survives the caught error.
        assert db.execute("SELECT count(*) FROM public.pr_youtube_agent_history WHERE workspace_id=%s AND record_kind='draft'", (WORKSPACES[1],)).fetchone()[0] == 0
    METRICS['atomicity'] = {'callerRollback': True, 'caughtLogicalConflictSavepointRollback': True,
                           'stateAndArchiveShareTransaction': True}

    with connection() as db:
        assert db.execute("SELECT has_table_privilege('service_role',%s,'UPDATE')", (history.TABLE,)).fetchone()[0] is False
        for role in ('anon', 'authenticated'):
            for command in ('SELECT record FROM ' + history.TABLE,
                            'INSERT INTO ' + history.TABLE + ' SELECT * FROM ' + history.TABLE,
                            'DELETE FROM ' + history.TABLE,
                            "UPDATE " + history.TABLE + " SET record=record"):
                def attempt(role=role, command=command):
                    db.execute('SET LOCAL ROLE ' + role)
                    db.execute(command)
                expect_sql('42501', db, attempt)
        def service_update():
            db.execute('SET LOCAL ROLE service_role')
            db.execute('UPDATE ' + history.TABLE + ' SET record=record')
        expect_sql('42501', db, service_update)
        expect_sql('55000', db, lambda: db.execute('UPDATE ' + history.TABLE + ' SET archived_at=now()'))
        # Defense in depth: even a mistaken authenticated SELECT grant reveals no rows.
        db.execute('GRANT SELECT ON ' + history.TABLE + ' TO authenticated')
        with db.transaction():
            db.execute('SET LOCAL ROLE authenticated')
            assert db.execute('SELECT count(*) FROM ' + history.TABLE).fetchone()[0] == 0
            db.execute('RESET ROLE')
        db.execute('REVOKE SELECT ON ' + history.TABLE + ' FROM authenticated')
        bad = {'id': None, 'connectionId': CONNECTIONS[0]}
        expect_sql('23514', db, lambda: history._archive_record(db.cursor(), WORKSPACES[2], CONNECTIONS[0],
                   {'recordKind': 'draft', 'recordId': 'forged-id', 'record': bad}))
        db.execute("UPDATE public.pr_encrypted_credentials SET provider='linkedin' WHERE workspace_id=%s AND connection_id=%s",
                   (WORKSPACES[2], CONNECTIONS[1]))
        non_youtube = draft(0, CONNECTIONS[1])
        expect_sql('23514', db, lambda: history._archive_record(db.cursor(), WORKSPACES[2], CONNECTIONS[1],
                   {'recordKind': 'draft', 'recordId': non_youtube['id'], 'record': non_youtube}))
        expect_sql('23514', db, lambda: db.execute(
            "UPDATE public.pr_encrypted_credentials SET provider='linkedin' WHERE workspace_id=%s AND connection_id=%s",
            (WORKSPACES[0], CONNECTIONS[0])))
    METRICS['isolation'] = {'forceRls': True, 'anonDenied': True, 'authenticatedDenied': True,
                           'mistakenSelectGrantStillHidden': True, 'serviceUpdateDenied': True,
                           'immutableOrderingTrigger': True, 'nullRecordIdentityRejected': True,
                           'nonYouTubeCredentialRejected': True, 'providerReassignmentRejected': True}

    # Explicit disconnect cleanup deletes only that archive scope. Credential or
    # whole-workspace deletion cascades, while customer-original JSON is unchanged.
    with connection() as db, db.cursor() as cur:
        assets_before = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[0],)).fetchone()[0]
        removed = history.purge_connection_history(cur, WORKSPACES[0], CONNECTIONS[0])
        assert removed == PAIRS * 2
        expect_alpha('youtube_agent_history_cursor', lambda:
                     history.page(cur, WORKSPACES[0], CONNECTIONS[0], 'draft', cursor=first['nextCursor']))
        assert db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[0],)).fetchone()[0] == assets_before
        db.execute('DELETE FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',
                   (WORKSPACES[1], CONNECTIONS[0]))
        assert db.execute('SELECT count(*) FROM public.pr_youtube_agent_history WHERE workspace_id=%s', (WORKSPACES[1],)).fetchone()[0] == 0
        history.archive_and_compact(cur, WORKSPACES[2], CONNECTIONS[0], NOW)
        db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[2],))
        assert db.execute('SELECT count(*) FROM public.pr_youtube_agent_history WHERE workspace_id=%s', (WORKSPACES[2],)).fetchone()[0] == 0
    METRICS['cleanup'] = {'explicitConnectionPurge': True, 'credentialCascade': True,
                          'workspaceCascade': True, 'originalMediaUnchanged': True}
    METRICS['status'] = 'pass'
except Exception as error:
    METRICS.update(status='fail', failureType=type(error).__name__)
    raise
finally:
    if seeded:
        with connection() as db:
            db.execute('DELETE FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES,))
    artifacts = ROOT / '.jcb-artifacts'
    artifacts.mkdir(exist_ok=True)
    (artifacts / 'youtube-agent-history-acceptance.json').write_text(json.dumps(METRICS, indent=2) + '\n')
    print('RAFII_YOUTUBE_AGENT_HISTORY_EVIDENCE ' + json.dumps(METRICS, separators=(',', ':')))
