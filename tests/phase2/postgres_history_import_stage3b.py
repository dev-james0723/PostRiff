"""Stage 3B on disposable PostgreSQL; all provider data and identities are synthetic."""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from local_pg_target import selected_target
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.growth import history_import as H, metric_schedule as M

DSN = selected_target().dsn()
ONE = '00000000-0000-0000-0000-000000000001'
TWO = '00000000-0000-0000-0000-000000000002'
CONN = 'stage3b-threads'
checks = []
def connection(): return psycopg.connect(DSN, client_encoding='utf8')
def verify(token):
    if token != 'one': raise AlphaError('Verified session required', 401)
    return ONE
service = HostedWorkspaceService(connection, verify)
service.oauth.token_for_worker = lambda *args: {'accessToken': 'synthetic'}
responses, urls = [], []
def transport(method, url, **kw):
    urls.append(url)
    return responses.pop(0)
importer = H.HistoryImporter(connection, service.oauth, transport=transport, worker_id='stage3b', hosted=service)
with connection() as db:
    wid = str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s', (ONE,)).fetchone()[0])
    foreign = str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s', (TWO,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET role='owner',status='active' WHERE user_id=%s", (ONE,))
    db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'threads','synthetic-account','sealed','fixture',ARRAY['threads_basic','threads_manage_insights'])", (wid, CONN))
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'analytics','Direct')", (wid, CONN))
def refused(code, fn):
    try: fn()
    except AlphaError as error:
        assert error.status == code, (error.status, code)
        return error
    raise AssertionError('Expected refusal')
def reset_throttle():
    with connection() as db: db.execute('DELETE FROM public.pr_auth_throttle')
def finish_active():
    with connection() as db: db.execute("UPDATE public.pr_history_imports SET status='done' WHERE status IN ('pending','running')")
def request(): return importer.request(wid, 'one', CONN, {'confirmed': True})
for payload in ({}, {'confirmed': False}, {'confirmed': 'true'}, {'confirmed': 1}, None):
    refused(400, lambda: importer.request(wid, 'one', CONN, payload))
assert refused(403, lambda: importer.request(wid, 'prt_synthetic', CONN, {'confirmed': True})).code == 'interactive_required'
assert importer.status(wid, 'one', CONN)['status'] == 'none'
checks.append('strict boolean consent; API tokens cannot request; reading status does not enqueue')
with connection() as db: db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE user_id=%s", (ONE,))
assert importer.status(wid, 'one', CONN)['status'] == 'none'
refused(403, request)
refused(403, lambda: importer.status(foreign, 'one', CONN))
refused(401, lambda: importer.status(wid, 'unknown', CONN))
with connection() as db: db.execute("UPDATE public.pr_memberships SET role='owner' WHERE user_id=%s", (ONE,))
for level in ('Unsupported', 'Assisted', 'Bridge'):
    with connection() as db: db.execute('UPDATE public.pr_channel_capabilities SET level=%s WHERE connection_id=%s', (level, CONN))
    assert refused(409, request).code == 'analytics_required'
with connection() as db: db.execute("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE connection_id=%s", (CONN,))
first = request()
assert all(first[k] == value for k, value in {'windowDays': 90, 'maxPosts': 300, 'maxPages': 12, 'pageLimit': 25, 'purgePending': False}.items())
for _ in range(4): assert request()['importId'] == first['importId']
assert refused(429, request).code == 'history_import_throttled'
with connection() as db:
    audit = db.execute("SELECT meta FROM public.pr_audit_events WHERE kind='history_import.requested'").fetchall()
    assert len(audit) == 1 and audit[0][0] == {'consentVersion': 'history-import.v1', 'windowDays': 90, 'maxPosts': 300, 'maxPages': 12}, audit
checks.append('read/manage/tenant boundaries, Direct analytics, one active run, auditable confirmation and five requests/hour')
reset_throttle()
# Provider ignores limit and returns 100 posts per page; our parser still stores at most 25 each time.
now = first['requestedAt']
iso = lambda ts: time.strftime('%Y-%m-%dT%H:%M:%S+0000', time.gmtime(ts))
for page in range(12):
    responses.append({'status': 200, 'body': {'data': [{'id': f'page-{page}-{i}', 'timestamp': iso(now-60-i), 'text': 'PRIVATE CAPTION'} for i in range(100)], 'paging': {'next': 'https://untrusted.invalid/not-followed', 'cursors': {'after': f'cursor-{page+1}'}}}})
for _ in range(4): importer.tick()
state = importer.status(wid, 'one', CONN)
assert (state['status'], state['pages'], state['posts']) == ('done', 12, 300), state
assert len(urls) == 12 and 'after=cursor-11' in urls[-1]
assert state['metricReads'] == {'pending': 300}
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_owned_posts').fetchone()[0] == 300
    assert db.execute("SELECT count(*) FROM public.pr_owned_posts WHERE row_to_json(pr_owned_posts)::text LIKE '%%PRIVATE CAPTION%%'").fetchone()[0] == 0
assert importer.tick()['claimed'] == 0
assert all('untrusted.invalid' not in url for url in urls)
checks.append('hard 12-page/300-post bound despite provider overdelivery; opaque cursors only; no retained caption text')
# The 90-day window is anchored to the request, including on later ticks; future timestamps are excluded.
with connection() as db: db.execute("DELETE FROM public.pr_metric_reads WHERE connection_id=%s", (CONN,))
reset_throttle()
run = request()
responses.append({'status': 200, 'body': {'data': [{'id':'boundary','timestamp':iso(run['requestedAt']-89*86400)}, {'id':'old','timestamp':iso(run['requestedAt']-91*86400)}, {'id':'future','timestamp':iso(run['requestedAt']+86400)}], 'paging': {'next': 'ignored', 'cursors': {'after': 'old-stop'}}}})
assert importer.tick().get('done') == 1
with connection() as db:
    posts = {r[0] for r in db.execute("SELECT provider_post_id FROM public.pr_owned_posts WHERE provider_post_id IN ('boundary','old','future')").fetchall()}
assert posts == {'boundary'}, posts
checks.append('fixed 90-day request window excludes older and future posts')
reset_throttle()
run = request()
responses.append({'status': 429, 'body': {}})
assert importer.tick().get('retry') == 1
retry = importer.status(wid, 'one', CONN)
assert retry['status'] == 'running' and retry['failure'] == 'http_429' and retry['retryAt'] > time.time()
assert 'cursor' not in retry and 'accessToken' not in json.dumps(retry)
checks.append('status exposes retry delay and independent metric-read progress without cursors or credentials')
# Disconnect fence: a marked purge stops a previously claimed page and metric completion.
with connection() as db: db.execute("UPDATE public.pr_history_imports SET lease_until=now()-interval '1 second' WHERE status='running'")
claimed = importer.claim(1)[0]
with connection() as db, db.cursor() as cur:
    H.mark_for_purge(cur, wid, CONN)
    M.schedule(cur, wid, CONN, 'threads', 'rafii-own', 'synthetic-job', now, 'verification')
with connection() as db: owned_before = db.execute('SELECT count(*) FROM public.pr_owned_posts').fetchone()[0]
page = {'posts':[{'id':'late', 'publishedAt':now-10,'mediaType':None,'mediaProductType':None,'permalink':None,'captionChars':10}], 'next':None}
assert importer._store_page(claimed, page, now-90*86400, True) is None
assert importer.status(wid, 'one', CONN)['purgePending'] is True
assert refused(409, request).code == 'history_purge_pending'
with connection() as db: assert db.execute('SELECT count(*) FROM public.pr_owned_posts').fetchone()[0] == owned_before
# A failed purge remains owed and retains the fence; a later sweep succeeds even with flags OFF.
with patch.object(H, 'purge_connection', side_effect=RuntimeError('synthetic store outage')):
    failed = H.purge_after_disconnect(connection, wid, CONN)
assert failed['failed'] == 1 and importer.status(wid, 'one', CONN)['purgePending']
with connection() as db: db.execute('UPDATE public.pr_growth_purges SET next_attempt_at=now()')
assert H.sweep_pending_purges(connection)['purged'] == 1
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_owned_posts WHERE source='history_import'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM public.pr_metric_reads WHERE source='history_import' AND job_id IS NULL").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM public.pr_metric_reads WHERE provider_post_id='rafii-own'").fetchone()[0] == 4
assert not importer.status(wid, 'one', CONN)['purgePending']
checks.append('late store fenced; reconnect/request blocked during purge; failed purge retries flag-independently; Rafii-owned readings preserved')
# Capability revocation between pages also fences writes, independently of a marker.
reset_throttle()
request()
claimed = importer.claim(1)[0]
with connection() as db: db.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE connection_id=%s", (CONN,))
assert importer._store_page(claimed, page, now-90*86400, True) is None
assert importer.run_one(claimed, time.monotonic()+5) == 'cancelled'
checks.append('loss of Direct analytics cancels running imports and independently fences page writes')
print(json.dumps({'execution':'disposable PostgreSQL; synthetic providers only', 'checks':checks}, indent=2))
