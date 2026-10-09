"""Cloud-only transactional selection projection regression, synthetic data only.

The projection selects IDs; it neither authorizes a job nor truncates history.
No provider, model, production database or external credentials are used.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from uuid import uuid4

if not sys.platform.startswith('linux') or os.environ.get('CI', '').lower() not in ('1', 'true'):
    raise SystemExit('Cloud CI and the disposable PostgreSQL harness are required.')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_phase2.youtube.workspace_provider_data import _journal_expired

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
NOW, TTL = 1800000000, 30 * 86400
WORKSPACES = [str(uuid4()), str(uuid4()), str(uuid4())]
CONNECTION = 'synthetic-projection-' + uuid4().hex
MIGRATION = (ROOT / 'migrations/postriff/104_youtube_operations_projection.sql').read_text()
TABLES = ('pr_youtube_operations', 'pr_youtube_planner_candidates')
FUNCTIONS = (
    'public.pr_youtube_projection_number(jsonb)',
    'public.pr_youtube_projection_refresh(uuid,jsonb)',
    'public.pr_youtube_workspace_projection_trigger()',
    'public.pr_youtube_upload_projection_trigger()',
)


def connection():
    return psycopg.connect(DSN, client_encoding='utf8', connect_timeout=5,
                           options='-c statement_timeout=20000 -c lock_timeout=5000')


def write_state(db, state, workspace=WORKSPACES[0]):
    db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',
               (json.dumps(state), workspace))


def operations(db, workspace=WORKSPACES[0]):
    return db.execute('SELECT upload_due_at,planner_lease_until,last_planner_dispatch,provider_expires_at '
                      'FROM public.pr_youtube_operations WHERE workspace_id=%s', (workspace,)).fetchone()


def candidates(db, workspace=WORKSPACES[0]):
    return db.execute('SELECT policy_id,draft_id,candidate_at,ends_at FROM public.pr_youtube_planner_candidates '
                      'WHERE workspace_id=%s ORDER BY policy_id,draft_id', (workspace,)).fetchall()


def source_snapshot(db):
    return {
        'workspaces': db.execute('SELECT id::text,revision,state,created_at FROM public.pr_workspaces '
                                'WHERE id=ANY(%s::uuid[]) ORDER BY id', (WORKSPACES,)).fetchall(),
        'journals': db.execute('SELECT workspace_id::text,connection_id,operation_key,state,updated_at '
                              'FROM public.pr_youtube_uploads WHERE workspace_id=ANY(%s::uuid[]) '
                              'ORDER BY workspace_id,connection_id,operation_key', (WORKSPACES,)).fetchall(),
    }


def draft(identifier, workflow='upload_now', **extra):
    return {'id': identifier, 'connectionId': CONNECTION, 'status': 'proposed',
            'uploadWorkflow': workflow, **extra}


def policy(identifier, draft_ids, *, starts=NOW - 60, ends=NOW + 7200, **extra):
    return {'id': identifier, 'connectionId': CONNECTION, 'status': 'active',
            'startsAt': starts, 'endsAt': ends, 'drafts': [{'id': value} for value in draft_ids], **extra}


def job(identifier, **extra):
    manifest = {'platform': 'YouTube', 'workspaceId': WORKSPACES[0], 'channelId': CONNECTION,
                'actor': 'synthetic-owner', 'payload': {'title': 'Keep original ' + identifier}}
    approval = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'id': identifier, 'manifest': manifest, 'state': 'approved', 'approvedBy': 'synthetic-owner',
            'approvedAt': NOW, 'approvalDigest': approval, 'events': [{'at': NOW, 'state': 'approved'}], **extra}


def valid_state():
    return {
        'phase2': {'jobs': [job('current', leaseUntil=NOW - 10, nextAt=NOW - 5),
                           job('lease-delayed', leaseUntil=NOW + 90, nextAt=0),
                           job('upload-delayed', leaseUntil=0, nextAt=NOW + 120),
                           job('old-held', state='held'), job('old-verified', state='verified'),
                           job('old-failed', state='failed'), job('old-canceled', state='canceled'),
                           {'id': 'other-platform', 'state': 'approved', 'manifest': {'platform': 'LinkedIn'}}],
                   'channels': [], 'reviews': [{'id': 'retained-approval', 'digest': 'unchanged-digest'}],
                   'assets': [{'id': 'retained-asset', 'description': 'Original customer note'}]},
        'youtubeAgent': {
            'drafts': [draft('now'), draft('later', 'upload_later', uploadAt=NOW + 3600),
                       draft('other-workflow', 'native_schedule'), draft('null-due', None, uploadAt=NOW + 100),
                       draft('null-missing', None), draft('not-proposed', status='approved'),
                       draft('wrong-connection', connectionId='other'), draft('not-listed')],
            'policies': [policy('current-policy', ['now', 'other-workflow', 'null-due', 'null-missing',
                                                  'not-proposed', 'wrong-connection']),
                         policy('future-policy', ['now'], starts=NOW + 100),
                         policy('second-interval', ['now'], starts=NOW + 8000, ends=NOW + 16000),
                         policy('delayed-policy', ['later']),
                         policy('paused-history', ['now'], status='paused'),
                         policy('revoked-history', ['now'], status='revoked')],
            'lastDispatchAt': NOW - 300, 'fleetLease': {'id': 'retained-lease', 'until': NOW + 120},
        },
        'customerNotes': 'Retain every original approval and all operational history.',
    }


def assert_original_selection(db, state):
    """Independent pre-projection SQL is the oracle for well-formed source state."""
    row = db.execute("""SELECT min(greatest(coalesce((j->>'leaseUntil')::float8,0),coalesce((j->>'nextAt')::float8,0)))
        FROM jsonb_array_elements(%s::jsonb#>'{phase2,jobs}') j
        WHERE j#>>'{manifest,platform}'='YouTube' AND coalesce(j->>'state','') NOT IN ('verified','failed','canceled','held')""",
        (json.dumps(state),)).fetchone()
    assert operations(db)[0] == row[0], (operations(db), row)
    for clock in (NOW - 10, NOW, NOW + 100, NOW + 1800, NOW + 8001, NOW + 16000):
        expected = db.execute("""SELECT p->>'id',d->>'id' FROM (SELECT %s::jsonb AS state) s,
            jsonb_array_elements(s.state#>'{youtubeAgent,policies}') p,
            jsonb_array_elements(s.state#>'{youtubeAgent,drafts}') d
            WHERE p->>'status'='active' AND (p->>'startsAt')::float8<=%s AND (p->>'endsAt')::float8>%s
              AND d->>'status'='proposed' AND d->>'connectionId'=p->>'connectionId'
              AND (d->>'uploadWorkflow'<>'upload_later' OR (d->>'uploadAt')::float8<=%s)
              AND EXISTS(SELECT 1 FROM jsonb_array_elements(p->'drafts') e WHERE e->>'id'=d->>'id')
            ORDER BY p->>'id',d->>'id'""", (json.dumps(state), clock, clock, clock + 1800)).fetchall()
        actual = db.execute('SELECT policy_id,draft_id FROM public.pr_youtube_planner_candidates '
                            'WHERE workspace_id=%s AND candidate_at<=%s AND ends_at>%s ORDER BY policy_id,draft_id',
                            (WORKSPACES[0], clock, clock)).fetchall()
        assert actual == expected, (clock, actual, expected)


def assert_journal_selection(db):
    for clock in (0, NOW - TTL, NOW, NOW + TTL + 10000):
        expected = db.execute('SELECT operation_key FROM public.pr_youtube_uploads WHERE workspace_id=%s '
                              "AND NOT state ? 'youtubeProviderDataRemoved' AND (" + _journal_expired() + ') ORDER BY operation_key',
                              (WORKSPACES[0], clock - TTL, clock - TTL, clock - TTL)).fetchall()
        actual = db.execute('SELECT operation_key FROM public.pr_youtube_uploads WHERE workspace_id=%s '
                            'AND youtube_api_expires_at<=%s ORDER BY operation_key', (WORKSPACES[0], clock)).fetchall()
        assert actual == expected, (clock, actual, expected)


class RollbackFixture(Exception):
    pass


with connection() as db:
    assert db.execute('SELECT host(inet_server_addr()),inet_server_port(),current_database()').fetchone() == ('127.0.0.1', 55438, 'postgres')
    assert db.execute("SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='auth' AND table_name='users'").fetchone()[0] == ['id']
    audit_permissions = tuple(db.execute("SELECT has_table_privilege('service_role','public.pr_audit_events',%s)",
                                         (privilege,)).fetchone()[0] for privilege in ('UPDATE', 'DELETE'))
    for workspace in WORKSPACES:
        db.execute('INSERT INTO public.pr_workspaces(id,state) VALUES(%s,%s::jsonb)', (workspace, json.dumps(valid_state())))
    db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) "
               "VALUES(%s,%s,'youtube',%s,'synthetic-ciphertext','synthetic-key','{}')",
               (WORKSPACES[0], CONNECTION, 'UC' + 'p' * 22))
    journal_states = {
        'numeric-ingestion': {'youtubeProviderDataIngestedAt': NOW - 10, 'createdAt': 0},
        'legacy-created': {'createdAt': NOW - TTL - 60},
        'legacy-updated': {},
        'malformed-ingestion': {'youtubeProviderDataIngestedAt': 'not-a-number', 'createdAt': NOW - TTL - 60},
        'boolean-ingestion': {'youtubeProviderDataIngestedAt': True},
        'string-created': {'createdAt': str(NOW - TTL - 60)},
        'permanent-tombstone': {'youtubeProviderDataRemoved': True, 'manifestDigest': 'permanent-original'},
        'marker-present-false': {'youtubeProviderDataRemoved': False, 'youtubeProviderDataIngestedAt': 0},
    }
    for operation, state in journal_states.items():
        state.update(manifestDigest='original-' + operation, stage='synthetic-retained')
        db.execute('INSERT INTO public.pr_youtube_uploads(workspace_id,connection_id,operation_key,state,updated_at) '
                   'VALUES(%s,%s,%s,%s::jsonb,to_timestamp(%s))',
                   (WORKSPACES[0], CONNECTION, operation, json.dumps(state), NOW - TTL - 30))
    before = source_snapshot(db)

try:
    # A rerun repairs derived rows but must never update customer state, clocks,
    # approvals, digests or journal bodies. It works with/without prior104 setup.
    with connection() as db:
        db.execute(MIGRATION)
        assert source_snapshot(db) == before
        first_projection = (operations(db), candidates(db))
        db.execute('DELETE FROM public.pr_youtube_planner_candidates WHERE workspace_id=%s', (WORKSPACES[0],))
        db.execute('DELETE FROM public.pr_youtube_operations WHERE workspace_id=%s', (WORKSPACES[0],))
        db.commit()
        db.execute(MIGRATION)
        assert source_snapshot(db) == before
        assert (operations(db), candidates(db)) == first_projection
        assert_original_selection(db, valid_state())
        assert len(candidates(db)) == 6, candidates(db)
        assert operations(db) == (NOW - 5, NOW + 120, NOW - 300, None)
        assert db.execute("SELECT public.pr_youtube_projection_number('1e400'::jsonb),public.pr_youtube_projection_number('-1e400'::jsonb),public.pr_youtube_projection_number('1e-400'::jsonb)").fetchone() == (math.inf, -math.inf, 0)
        assert_journal_selection(db)
        assert db.execute('SELECT youtube_api_expires_at FROM public.pr_youtube_uploads WHERE workspace_id=%s AND operation_key=%s',
                          (WORKSPACES[0], 'numeric-ingestion')).fetchone()[0] == NOW - 10 + TTL
        assert tuple(db.execute("SELECT has_table_privilege('service_role','public.pr_audit_events',%s)",
                                (privilege,)).fetchone()[0] for privilege in ('UPDATE', 'DELETE')) == audit_permissions

    # Each due value follows both nextAt and leaseUntil. Terminal history and
    # unrelated platforms never become due; missing clocks preserve zero.
    with connection() as db:
        for saved, expected in (
            (job('missing-clocks'), 0),
            (job('delayed-lease', nextAt=NOW - 10, leaseUntil=NOW + 100), NOW + 100),
            (job('delayed-next', nextAt=NOW + 200, leaseUntil=NOW + 100), NOW + 200),
            (job('null-clocks', nextAt=None, leaseUntil=None), 0),
            (job('bad-lease', leaseUntil='NaN'), None),
            (job('bad-next', nextAt=True), None),
            (job('bad-next-infinite', nextAt='Infinity'), None),
            *((job('terminal-' + status, state=status), None) for status in ('held', 'verified', 'failed', 'canceled')),
        ):
            state = valid_state()
            state['phase2']['jobs'] = [saved]
            write_state(db, state)
            assert operations(db)[0] == expected, (saved, operations(db))
        malformed = {'phase2': {'jobs': 'malformed', 'channels': {}},
                     'youtubeAgent': {'policies': {}, 'drafts': None, 'fleetLease': {'until': 'NaN'}}}
        write_state(db, malformed)
        assert operations(db)[0] is None and math.isinf(operations(db)[1]) and operations(db)[1] > 0
        assert not candidates(db)
        malformed = valid_state()
        malformed['youtubeAgent']['policies'].extend([
            policy('bad-start', ['now'], starts='NaN'), policy('bad-end', ['now'], ends='Infinity'),
            policy('boolean-start', ['now'], starts=True), policy('missing-end', ['now'], ends=None),
        ])
        malformed['youtubeAgent']['drafts'].append(draft('bad-later', 'upload_later', uploadAt='Infinity'))
        malformed['youtubeAgent']['policies'].append(policy('bad-later-policy', ['bad-later']))
        write_state(db, malformed)
        assert len(candidates(db)) == 6 and not any(row[0].startswith('bad-') for row in candidates(db))

    # Provider output timestamps are independent of account dispatch gates.
    # Legacy/malformed output is immediately due; removed markers never replay.
    with connection() as db:
        output_cases = (
            (job('tagged', providerReference='synthetic-video', youtubeProviderOutput={'expiresAt': NOW + 100}), NOW + 100),
            (job('legacy', approvedAt=NOW - TTL, url='synthetic-url'), NOW),
            (job('bad-stamp', progress={}, youtubeProviderOutput=None), -math.inf),
            (job('missing-expiry', verification={}, youtubeProviderOutput={}), -math.inf),
            (job('bad-expiry', comments=[], youtubeProviderOutput={'expiresAt': '123'}), -math.inf),
            (job('legacy-no-clock', approvedAt=None, insights={}), -math.inf),
            (job('removed', providerReference='gone', youtubeProviderDataRemoved=True), None),
            (job('removed-key', progress={}, youtubeProviderDataRemoved=False), None),
            (job('no-output'), None),
        )
        for saved, expected in output_cases:
            state = {'phase2': {'jobs': [saved], 'channels': []}}
            write_state(db, state)
            assert operations(db)[3] == expected, (saved, operations(db))
        channel = {'id': CONNECTION, 'platform': 'YouTube', 'evidenceSource': 'live_provider',
                   'youtubeIdentityIngestedAt': NOW - TTL - 100}
        cleanup_state = valid_state()
        cleanup_state['phase2']['channels'] = [channel]
        write_state(db, cleanup_state)
        assert operations(db)[3] == NOW - 100
        for gate in ('accountBlock', 'accountDeletion'):
            blocked = copy.deepcopy(cleanup_state)
            blocked[gate] = False  # Presence, rather than truthiness, is the dispatch gate.
            write_state(db, blocked)
            assert operations(db)[0] is None and not candidates(db) and operations(db)[3] == NOW - 100
        for extra, expected in (({}, -math.inf), ({'youtubeIdentityIngestedAt': 'bad'}, -math.inf),
                                ({'youtubeIdentityIngestedAt': NOW}, NOW + TTL),
                                ({'youtubeIdentityIngestedAt': NOW, 'youtubeProviderDataRemoved': False}, None),
                                ({'evidenceSource': 'synthetic'}, None)):
            legacy = {'id': CONNECTION, 'platform': 'YouTube', 'evidenceSource': 'live_provider', **extra}
            write_state(db, {'phase2': {'jobs': [], 'channels': [legacy]}})
            assert operations(db)[3] == expected, (legacy, operations(db))
        no_phase2 = {'youtubeAgent': copy.deepcopy(valid_state()['youtubeAgent'])}
        write_state(db, no_phase2)
        assert operations(db)[0] is None and operations(db)[3] is None and len(candidates(db)) == 6
        write_state(db, {'phase2': {'jobs': [job('current')], 'channels': []}})
        assert operations(db)[0] == 0 and not candidates(db)

    # The journal retains its genuine ingestion clock through updated_at changes.
    # Legacy journals use the older of createdAt and updated_at; missing numeric
    # clocks do not acquire a fabricated createdAt from a projection refresh.
    with connection() as db:
        db.execute('UPDATE public.pr_youtube_uploads SET updated_at=to_timestamp(%s) WHERE workspace_id=%s',
                   (NOW + 5000, WORKSPACES[0]))
        values = dict(db.execute('SELECT operation_key,youtube_api_expires_at FROM public.pr_youtube_uploads WHERE workspace_id=%s',
                                 (WORKSPACES[0],)).fetchall())
        assert values['numeric-ingestion'] == NOW - 10 + TTL
        assert values['legacy-created'] == NOW - 60
        assert values['legacy-updated'] == NOW + 5000 + TTL
        assert values['string-created'] == NOW + 5000 + TTL
        assert values['permanent-tombstone'] is None and values['marker-present-false'] is None
        assert_journal_selection(db)
        state = {'manifestDigest': 'unchanged-original', 'youtubeProviderDataIngestedAt': NOW - 40}
        db.execute('UPDATE public.pr_youtube_uploads SET state=%s::jsonb WHERE workspace_id=%s AND operation_key=%s',
                   (json.dumps(state), WORKSPACES[0], 'legacy-updated'))
        assert db.execute('SELECT youtube_api_expires_at,state FROM public.pr_youtube_uploads WHERE workspace_id=%s AND operation_key=%s',
                          (WORKSPACES[0], 'legacy-updated')).fetchone() == (NOW - 40 + TTL, state)
        # A service caller cannot forge a ready journal projection independently.
        db.execute('UPDATE public.pr_youtube_uploads SET youtube_api_expires_at=0 WHERE workspace_id=%s AND operation_key=%s',
                   (WORKSPACES[0], 'legacy-updated'))
        assert db.execute('SELECT youtube_api_expires_at FROM public.pr_youtube_uploads WHERE workspace_id=%s AND operation_key=%s',
                          (WORKSPACES[0], 'legacy-updated')).fetchone()[0] == NOW - 40 + TTL

    with connection() as db:
        write_state(db, valid_state())
        before_rollback = (operations(db), candidates(db), source_snapshot(db))
        try:
            with db.transaction():
                write_state(db, {'accountDeletion': {'status': 'pending'}, 'phase2': {'jobs': [], 'channels': []}})
                assert operations(db)[0] is None and not candidates(db)
                raise RollbackFixture()
        except RollbackFixture:
            pass
        assert (operations(db), candidates(db), source_snapshot(db)) == before_rollback
        try:
            with db.transaction():
                db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[1],))
                assert operations(db, WORKSPACES[1]) is None and not candidates(db, WORKSPACES[1])
                raise RollbackFixture()
        except RollbackFixture:
            pass
        assert operations(db, WORKSPACES[1]) is not None and candidates(db, WORKSPACES[1])
        db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (WORKSPACES[2],))
        assert operations(db, WORKSPACES[2]) is None and not candidates(db, WORKSPACES[2])
        # Revision-only updates cannot reset an existing durable planner cursor.
        projected = (operations(db), candidates(db))
        db.execute('UPDATE public.pr_workspaces SET revision=revision+1 WHERE id=%s', (WORKSPACES[0],))
        assert (operations(db), candidates(db)) == projected

    # Exact schema and privilege checks, including trigger execution by service
    # writers despite revoked direct EXECUTE on every maintenance routine.
    with connection() as db:
        for table in TABLES:
            assert db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass',
                              ('public.' + table,)).fetchone() == (True, True)
            assert db.execute('SELECT cmd,roles FROM pg_policies WHERE schemaname=%s AND tablename=%s',
                              ('public', table)).fetchall() == [('SELECT', ['service_role'])]
            for role in ('anon', 'authenticated', 'service_role'):
                for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'):
                    assert db.execute('SELECT has_table_privilege(%s,%s,%s)',
                                      (role, 'public.' + table, privilege)).fetchone()[0] == (role == 'service_role' and privilege == 'SELECT')
        indexes = dict(db.execute("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public' AND indexname=ANY(%s)",
                                  (['pr_youtube_operations_upload_due_idx', 'pr_youtube_operations_provider_due_idx',
                                    'pr_youtube_operations_planner_dispatch_idx', 'pr_youtube_planner_candidates_due_idx',
                                    'pr_youtube_uploads_api_expiry_idx', 'pr_youtube_uploads_workspace_api_expiry_idx'],)).fetchall())
        assert len(indexes) == 6
        assert '(upload_due_at, workspace_id)' in indexes['pr_youtube_operations_upload_due_idx']
        assert '(provider_expires_at, workspace_id)' in indexes['pr_youtube_operations_provider_due_idx']
        assert '(last_planner_dispatch, workspace_id)' in indexes['pr_youtube_operations_planner_dispatch_idx']
        assert '(workspace_id, candidate_at, ends_at)' in indexes['pr_youtube_planner_candidates_due_idx']
        assert '(youtube_api_expires_at, workspace_id)' in indexes['pr_youtube_uploads_api_expiry_idx']
        assert '(workspace_id, youtube_api_expires_at)' in indexes['pr_youtube_uploads_workspace_api_expiry_idx']
        for signature in FUNCTIONS:
            definer, config = db.execute('SELECT prosecdef,proconfig FROM pg_proc WHERE oid=%s::regprocedure',
                                         (signature,)).fetchone()
            assert definer == ('projection_number' not in signature)
            assert config == ['search_path=""'], (signature, config)
            for role in ('anon', 'authenticated', 'service_role'):
                assert not db.execute('SELECT has_function_privilege(%s,%s,%s)',
                                      (role, signature, 'EXECUTE')).fetchone()[0]
        trigger_defs = dict(db.execute("SELECT tgname,pg_get_triggerdef(oid) FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('pr_youtube_workspace_projection_trg','pr_youtube_upload_projection_trg')").fetchall())
        assert len(trigger_defs) == 2 and 'AFTER INSERT OR UPDATE OF state' in trigger_defs['pr_youtube_workspace_projection_trg']
        assert 'BEFORE INSERT OR UPDATE OF state, updated_at, youtube_api_expires_at' in trigger_defs['pr_youtube_upload_projection_trg']
        db.execute('SET ROLE service_role')
        state = valid_state()
        state['youtubeAgent']['lastDispatchAt'] = NOW + 1
        state['youtubeAgent']['fleetLease']['until'] = NOW + 121
        write_state(db, state)
        assert operations(db)[1:3] == (NOW + 121, NOW + 1)
        for table in TABLES:
            try:
                with db.transaction():
                    db.execute('DELETE FROM public.' + table + ' WHERE workspace_id=%s', (WORKSPACES[0],))
                    raise AssertionError('Service caller mutated derived selection state directly')
            except psycopg.errors.InsufficientPrivilege:
                pass
        db.execute('RESET ROLE')
    for role in ('anon', 'authenticated'):
        with connection() as db:
            db.execute('SET ROLE ' + role)
            try:
                with db.transaction():
                    db.execute('SELECT * FROM public.pr_youtube_operations WHERE workspace_id=%s', (WORKSPACES[0],))
                    raise AssertionError('Browser role read server selection state')
            except psycopg.errors.InsufficientPrivilege:
                pass

    print('PASS: synthetic transactional thin YouTube selection projections, exact multi-policy timing/NULL eligibility, '
          'permanent tombstones, conservative provider/journal retention, blocked-account cleanup, source-preserving bounded '
          'backfill/idempotence, update/rollback/cascade and service-only read/trigger privileges. No provider calls or fleet load claim.')
finally:
    with connection() as db:
        db.execute('DELETE FROM public.pr_workspaces WHERE id=ANY(%s::uuid[])', (WORKSPACES,))
