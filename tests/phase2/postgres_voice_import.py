"""Voice import (migration 140; spec IMP-1 … IMP-7) on disposable PostgreSQL. Every account, post and provider answer
here is synthetic; the transport is a script, so nothing reaches a network.

Run: LC_ALL=C PYTHONPATH=src:tests <venv python> scripts/postriff_disposable_postgres.py tests/phase2/postgres_voice_import.py
"""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2 import voice_import as V
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
ONE = '00000000-0000-0000-0000-000000000001'
TWO = '00000000-0000-0000-0000-000000000002'
CONN, ACCOUNT = 'voice-threads-conn', 'synthetic-threads-account'
CONSENT = {'ownership': 'mine', 'voiceScope': 'brand', 'confirmed': True}
TABLES = ('pr_voice_imports', 'pr_voice_posts', 'pr_voice_analyses')
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


def verify(token):
    if token in ('one', 'two'):
        return ONE if token == 'one' else TWO
    raise AlphaError('Verified session required', 401)


verify.auth_time = lambda token, principal: time.time()   # a fresh sign-in, so disconnect's step-up passes


def refused(status, call):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, status, str(error))
        return error
    raise AssertionError('Expected a refusal')


def sql(query, params=()):
    """One statement in its own transaction; the rows it returned, or [] for a statement that returns none."""
    with connection() as db:
        cur = db.execute(query, params)
        return cur.fetchall() if cur.description else []


# --- the migration ---------------------------------------------------------------------------------------------------
migration = (ROOT / 'migrations/postriff/140_voice_import.sql').read_text(encoding='utf-8')
for _ in range(2):
    with psycopg.connect(DSN, autocommit=True) as db:
        db.execute(migration)
secured = sql("SELECT count(*) FROM pg_class WHERE relname = ANY(%s) AND relrowsecurity AND relforcerowsecurity", (list(TABLES),))[0][0]
policies = sql("SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename = ANY(%s)", (list(TABLES),))[0][0]
assert (secured, policies) == (3, 9), (secured, policies)   # tenant_read, rapv2_browser_session and trusted_write on each
for table in TABLES:
    assert not sql("SELECT has_table_privilege('anon', %s, 'SELECT')", ('public.' + table,))[0][0]
    assert not sql("SELECT has_table_privilege('authenticated', %s, 'INSERT')", ('public.' + table,))[0][0]
    # RAPv2 H-1 (119): the browser-session guard is restrictive, for select, to authenticated.
    guard = sql("SELECT permissive, cmd, roles::text FROM pg_policies WHERE schemaname='public' AND tablename=%s AND policyname='rapv2_browser_session'", (table,))
    assert guard == [('RESTRICTIVE', 'SELECT', '{authenticated}')], (table, guard)
checks.append('migration 140 applies twice; three tables with forced row security, member read behind the restrictive browser-session guard, and server-only write')

# --- a workspace with one connected Threads account ------------------------------------------------------------------
vault = CredentialVault(CredentialVault.generate_key())
threads = SimpleNamespace(platform='Threads', production_reviewed=False, capability_version=1, history_approved=False, revoke=lambda token: True)
service = HostedWorkspaceService(connection, verify, vault=vault, providers={'threads': threads})
service.oauth.token_for_worker = lambda *args, **kwargs: {'accessToken': 'synthetic-token', 'scopes': ['threads_basic'], 'providerAccountId': ACCOUNT}
script, urls = [], []


def transport(method, url, **kwargs):
    urls.append(url)
    answer = script.pop(0)
    if isinstance(answer, Exception):
        raise answer
    return answer


importer = V.mount(service, connection, {V.FLAG: '1', V.PROVIDERS_FLAG: 'threads'}, transport=transport)
assert importer is service.voice_import is service.oauth.voice_import
importer.worker_id = 'pg-voice-worker'
with connection() as db:
    wid = str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s', (ONE,)).fetchone()[0])
    foreign = str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s', (TWO,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET role='owner', status='active' WHERE user_id=%s", (ONE,))
    sealed, key = vault.encrypt('synthetic-token')
    db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) "
               "VALUES(%s,%s,'threads',%s,%s,%s,ARRAY['threads_basic'])", (wid, CONN, ACCOUNT, sealed, key))
    # The state the app writes at sign-up (the SQL bootstrap leaves it bare), with the connected channel.
    state = initial_phase2_state(wid, ONE, 'Synthetic owner', 'studio', time.time())
    state['phase2']['channels'].append({'id': CONN, 'platform': 'Threads', 'account': '@synthetic_studio'})
    db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s', (json.dumps(state), wid))


def text(number):
    return f'Synthetic studio note number {number}: we keep the practice room open late on Thursdays this term.'


def post(number, **extra):
    return {'id': f'p{number}', 'text': text(number), 'timestamp': f'2026-11-{number + 10:02d}T09:00:00+0000', 'media_type': 'TEXT_POST', **extra}


def page(numbers, after=None):
    body = {'data': [post(number) for number in numbers]}
    if after:
        body['paging'] = {'next': 'https://graph.threads.net/never-followed', 'cursors': {'after': after}}
    return {'status': 200, 'headers': {}, 'body': body}


def run(import_id):
    return dict(zip(V._RUN_KEYS, sql(f'SELECT {V._RUN_COLUMNS} FROM public.pr_voice_imports WHERE id=%s', (import_id,))[0]))


def held():
    return {row[0]: row[1] for row in sql('SELECT provider_post_id, routes FROM public.pr_voice_posts WHERE workspace_id=%s', (wid,))}


def reset_throttle():
    sql('DELETE FROM public.pr_auth_throttle')


# --- a full official run over three pages ---------------------------------------------------------------------------
request = {'route': 'official_api', 'provider': 'threads', 'connectionId': CONN, 'consent': CONSENT}
assert refused(400, lambda: importer.request(wid, 'one', {**request, 'consent': {'ownership': 'mine', 'voiceScope': 'brand'}})).code == 'consent_required'
first = importer.request(wid, 'one', request)['import']
assert (first['status'], first['accountKey'], first['accountLabel'], first['consent']['ownership']) == ('pending', ACCOUNT, '@synthetic_studio', 'mine'), first
assert refused(409, lambda: importer.request(wid, 'one', request)).code == 'voice_import_active'
stored_consent = sql('SELECT consent FROM public.pr_voice_imports WHERE id=%s', (first['id'],))[0][0]
assert stored_consent['version'] == 'voice-import.v1' and stored_consent['retainText'] is True and stored_consent['by'] == ONE, stored_consent
checks.append('one consent per account is stored with the run; a second active run for the account is refused (409)')
script += [page([9, 8, 7], 'c1'), page([6, 5, 4], 'c2'), page([3, 2, 1])]
outcome = importer.tick()
assert (outcome['status'], outcome['claimed'], outcome.get('done')) == ('ok', 1, 1), outcome
done = run(first['id'])
assert (done['status'], done['moreRemaining'], done['pages'], done['cursor'], done['leaseOwner']) == ('done', False, 3, None, None), done
assert (done['discovered'], done['retrieved'], done['duplicates'], done['excluded'], done['removed']) == (9, 9, 0, 0, 0), done
assert done['watermark'] and done['observedNewest'] > done['observedOldest']
assert held() == {f'p{n}': ['official_api'] for n in range(1, 10)}
assert 'after=c1' in urls[1] and 'after=c2' in urls[2] and all('never-followed' not in url for url in urls)
view = importer.status(wid, 'one')
receipt = next(item for item in view['imports'] if item['id'] == first['id'])
assert (receipt['moreRemaining'], receipt['counts']['retrieved'], receipt['counts']['removedAtSource']) == (False, 9, 0), receipt
assert 'cursor' not in json.dumps(receipt) and 'synthetic-token' not in json.dumps(view)
assert len(importer.posts(wid, 'one', {'provider': 'threads'})['posts']) == 9
assert importer.tick()['claimed'] == 0
checks.append('a full official run over three pages ends done with more_remaining false; 9 posts, exact counters, no cursor or token shown')

# --- the same post from the API and from an export: one row, two routes --------------------------------------------
reset_throttle()
upload = importer.request(wid, 'one', {'route': 'platform_export', 'provider': 'threads', 'accountKey': ACCOUNT, 'accountLabel': 'Threads export',
                                       'consent': CONSENT})['import']
assert upload['status'] == 'receiving'
batch = {'items': [{'externalId': 'p5', 'text': text(5), 'publishedAt': '2026-11-15T09:00:00+00:00', 'kind': 'original'},
                   {'externalId': 'x1', 'text': 'An export-only synthetic note: the studio piano was tuned this morning.', 'kind': 'original'}],
         'final': True, 'seq': 1}
received = importer.items(wid, 'one', upload['id'], batch)['import']
assert (received['status'], received['counts']['retrieved'], received['counts']['duplicates']) == ('done', 2, 1), received
assert refused(409, lambda: importer.items(wid, 'one', upload['id'], batch)).code == 'voice_import_not_receiving'   # a closed upload takes no more
assert sql("SELECT count(*), max(routes::text) FROM public.pr_voice_posts WHERE workspace_id=%s AND provider_post_id='p5'", (wid,))[0] == (1, '{official_api,platform_export}')
assert held()['x1'] == ['platform_export']
checks.append('the same post from the API and then an export is one row with two routes; the export counts it as a duplicate')

# --- a one-letter provider id (X is `x`) passes the table's provider check -------------------------------------------
reset_throttle()
x_upload = importer.request(wid, 'one', {'route': 'platform_export', 'provider': 'x', 'accountKey': 'export:synthetic_x_account',
                                         'accountLabel': 'X export', 'consent': CONSENT})['import']
assert (x_upload['status'], x_upload['provider']) == ('receiving', 'x'), x_upload
x_done = importer.items(wid, 'one', x_upload['id'], {'items': [{'externalId': '1700000000000000001', 'text': 'A synthetic note for the X export check: rehearsal moved to Thursday.', 'kind': 'original'}],
                                                    'final': True, 'seq': 1})['import']
assert (x_done['status'], x_done['counts']['retrieved']) == ('done', 1), x_done
importer.delete(wid, 'one', x_upload['id'])
assert '1700000000000000001' not in held()   # the rest of this suite counts every post in the workspace
checks.append('an X export (provider id `x`) is accepted by the provider check, completes, and is deleted with its post')

# --- a full pass, interrupted and resumed from its stored cursor, that no longer finds one post ----------------------
p1 = sql("SELECT id::text FROM public.pr_voice_posts WHERE workspace_id=%s AND provider_post_id='p1'", (wid,))[0][0]
with connection() as db:
    state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (wid,)).fetchone()[0]
    state.setdefault('speaker', {})['provisional'] = {'analysisMethod': 'voice_import', 'status': 'proposed',
                                                      'dimensions': [{'id': 'sentence_length', 'evidence': {'postIds': [p1]}}]}
    db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s', (json.dumps(state), wid))
reset_throttle()
full = importer.refresh(wid, 'one', first['id'], {'full': True})['import']
assert (full['status'], full['requestedSince']) == ('pending', None), full
script += [page([9, 8, 7], 'c1'), {'status': 503, 'headers': {}, 'body': {'error': {'message': 'synthetic outage'}}}]
assert importer.tick().get('retry') == 1
interrupted = run(full['id'])
assert (interrupted['status'], interrupted['cursor'], interrupted['pages'], interrupted['failure'], interrupted['leaseOwner']) == ('running', 'c1', 1, 'http_503', None), interrupted
assert interrupted['retryAt'] is not None and importer.tick()['claimed'] == 0         # waits for its retry time
sql("UPDATE public.pr_voice_imports SET retry_at=now() - interval '1 second' WHERE id=%s", (full['id'],))
reads = len(urls)
script += [page([6, 5, 4], 'c2'), page([3, 2])]                                         # p1 was deleted at the source
assert importer.tick().get('done') == 1
assert 'after=c1' in urls[reads] and len(urls) == reads + 2                          # resumed at page 2; page 1 not read again
finished = run(full['id'])
assert (finished['status'], finished['moreRemaining'], finished['pages'], finished['removed']) == ('done', False, 3, 1), finished
assert 'p1' not in held() and held()['p5'] == ['official_api', 'platform_export'] and held()['x1'] == ['platform_export']
assert next(item for item in importer.status(wid, 'one')['imports'] if item['id'] == full['id'])['counts']['removedAtSource'] == 1
proposal = sql('SELECT state FROM public.pr_workspaces WHERE id=%s', (wid,))[0][0]['speaker']['provisional']
assert (proposal['status'], proposal['staleReason']) == ('stale', 'imported_posts_removed'), proposal
checks.append('an interrupted full pass resumes from its stored cursor; a post it no longer finds is deleted (removedAtSource 1) and the proposal citing it goes stale')

# --- a watermark run deletes nothing ---------------------------------------------------------------------------------
reset_throttle()
before = held()
since = importer.refresh(wid, 'one', full['id'], {})['import']
assert since['requestedSince'] == '2026-11-19T09:00:00+00:00', since                 # the newest official post held (p9)
script += [{'status': 200, 'headers': {}, 'body': {'data': [post(12), post(9), post(6)], 'paging': {'next': 'https://n', 'cursors': {'after': 'c9'}}}}]
assert importer.tick().get('done') == 1
watermark = run(since['id'])
assert (watermark['status'], watermark['removed'], watermark['retrieved']) == ('done', 0, 2), watermark   # p6 ends the run unread
assert held() == {**before, 'p12': ['official_api']}
checks.append('a watermark run reads only newer posts and deletes nothing, even where the provider stopped early')

# --- disconnect: purge_connection deletes official-route posts only ----------------------------------------------------
reset_throttle()
pending = importer.refresh(wid, 'one', since['id'], {'full': True})['import']
result = service.oauth.disconnect(wid, 'one', CONN)
assert result['disconnected'] is True
left = {row[0]: (row[1], row[2]) for row in sql('SELECT provider_post_id, routes, connection_id FROM public.pr_voice_posts WHERE workspace_id=%s', (wid,))}
assert left == {'p5': (['platform_export'], None), 'x1': (['platform_export'], None)}, left
assert (run(pending['id'])['status'], run(pending['id'])['failure']) == ('cancelled', 'disconnected')
purged = sql("SELECT meta FROM public.pr_audit_events WHERE kind='voice_import.connection_purged' AND workspace_id=%s", (wid,))
assert purged and purged[0][0] == {'posts': 8}, purged                                # p2-p4, p6-p9 and p12; p5 stays as an upload
assert importer.tick()['claimed'] == 0
checks.append('disconnect purges inside its transaction: official-route posts deleted, uploaded posts kept as uploads, active runs cancelled')

# --- a member of another workspace reads nothing ---------------------------------------------------------------------
sql("UPDATE public.pr_memberships SET status='active' WHERE user_id=%s", (TWO,))
assert importer.status(foreign, 'two')['imports'] == [] and importer.posts(foreign, 'two')['posts'] == []
refused(403, lambda: importer.status(wid, 'two'))
refused(403, lambda: importer.posts(wid, 'two'))
with connection() as db:
    db.execute('SET ROLE authenticated')
    for principal, expected in ((TWO, 0), (ONE, 2)):
        db.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (principal,))
        seen = db.execute('SELECT count(*) FROM public.pr_voice_posts').fetchone()[0]
        runs = db.execute('SELECT count(*) FROM public.pr_voice_imports').fetchone()[0]
        assert seen == expected and (runs > 0) == (expected > 0), (principal, seen, runs)
    db.execute('RESET ROLE')
checks.append('a member of another workspace reads nothing, through the service (403) and through row security (0 rows)')

# --- workspace deletion cascades -------------------------------------------------------------------------------------
with connection() as db:
    db.execute("INSERT INTO public.pr_voice_analyses(workspace_id, group_key, prompt_version, corpus_digest, requested_by) VALUES(%s,'brand','voice-corpus/1','digest',%s)",
               (wid, ONE))
    db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (wid,))
remaining = [sql(f'SELECT count(*) FROM public.{table} WHERE workspace_id=%s', (wid,))[0][0] for table in TABLES]
assert remaining == [0, 0, 0], remaining
checks.append('deleting the workspace removes its runs, posts and analyses')
print(json.dumps({'status': 'PASS', 'execution': 'disposable PostgreSQL; synthetic provider answers only', 'checks': checks}, indent=2))
