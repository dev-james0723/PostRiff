"""Real PostgreSQL Audience Miner reads; synthetic owned posts/comments, zero network/model calls."""
import json
import copy
import os
import sys
import time
import uuid
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.growth.service import GrowthService, ROUTES
from postriff_phase2.growth.closed_loop import SUMMARY_ROUTE
from growth_phase2_fixtures import ENV, Models, Writer, seed

ONE = '00000000-0000-0000-0000-000000000001'
TWO = '00000000-0000-0000-0000-000000000002'


def connection(): return psycopg.connect(os.environ['POSTRIFF_TEST_DSN'])
def verify(token):
    if token == 'one': return ONE
    if token == 'two': return TWO
    raise AlphaError('Verified session required.', 401)


host = HostedWorkspaceService(connection, verify, ideas_runtime=Writer())
host.bootstrap('one', 'studio')
with connection() as db:
    wid = str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s', (ONE,)).fetchone()[0])
    foreign = str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s', (TWO,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET status='active',role='owner'")
models = Models()
growth = host.growth = GrowthService(host, env=ENV, router_factory=models.router)
seed(host, wid, 'one')
ig = 'instagram-audience-fixture'
post = 'p2-fixture-5'  # Same post ID as Threads: provider and connection must stay part of ownership.


def change(state, actor):
    channel = copy.deepcopy(state['phase2']['channels'][0])
    channel.update(id=ig, platform='Instagram', scopes=['instagram_business_basic','instagram_business_manage_comments'])
    state['phase2']['channels'].append(channel)
    job = copy.deepcopy(state['phase2']['jobs'][-1])
    job.update(id=str(uuid.uuid4()), providerReference=post)
    job['manifest'].update(channelId=ig,platform='Instagram')
    state['phase2']['jobs'].append(job)
    return state


host.repository.command(wid, 'one', host.get(wid, 'one')['revision'], change)
with connection() as db:
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'comments_read','Direct')", (wid, ig))
    for connection_id, provider, post_id, text in [
        (ig, 'instagram', post, 'How can I practise? Contact me at private@example.com @private'),
        ('phase2-fixture-account', 'instagram', post, 'wrong provider on a Threads connection'),
        (ig, 'threads', post, 'wrong provider on an Instagram connection'),
        (ig, 'instagram', 'not-owned', 'not our publication'),
        (ig, 'youtube', post, 'unsupported provider'),
    ]:
        db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text) VALUES(%s,%s,%s,%s,%s,%s)",
                   (wid, connection_id, provider, post_id, str(uuid.uuid4()), text))
    db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text) VALUES(%s,%s,'instagram',%s,%s,'foreign workspace')", (foreign, ig, post, str(uuid.uuid4())))


def comments():
    with host.repository.transaction('one', wid) as (cur, row, principal):
        return growth.closed_loop._comments(cur, wid, row[1], 30)


found = comments()
assert len(found) == 7, ('qualified Instagram comments must join existing Threads comments', found)
native = [c for c in found if c['connectionId'] == ig]
assert len(native) == 1 and native[0]['provider'] == 'instagram'
assert 'private@example.com' not in native[0]['text'] and '@private' not in native[0]['text']
assert not models.calls
coverage = growth.closed_loop.audience(wid, 'one')['coverage']
assert 'Instagram' in coverage and 'remains unavailable' not in coverage
with connection() as db:
    db.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND connection_id=%s", (wid, ig))
assert len(comments()) == 6
with connection() as db:
    db.execute("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s AND connection_id=%s", (wid, ig))
    db.execute("UPDATE public.pr_audience_threads SET tombstoned_at=now() WHERE id=%s", (native[0]['id'],))
assert len(comments()) == 6
with connection() as db: db.execute("UPDATE public.pr_audience_threads SET tombstoned_at=NULL WHERE id=%s", (native[0]['id'],))
saved = host.get(wid, 'one')
def revoke(state, actor):
    next(c for c in state['phase2']['channels'] if c['id'] == ig)['revoked'] = True
    return state
host.repository.command(wid, 'one', saved['revision'], revoke)
assert len(comments()) == 6
assert not growth.closed_loop._cluster_current({'consentDigest': 'old', 'bindings': [{'id': native[0]['id'], 'digest': native[0]['digest']}]}, {}, {})
try: growth.closed_loop.audience(foreign, 'one')
except AlphaError as error: assert error.status == 403
else: raise AssertionError('Second-workspace read accepted')
assert not models.calls
from postriff_phase2.customer_access import CustomerAccess
from postriff_phase2.providers import InstagramProvider, ThreadsProvider
class CurrentPaidFixture(CustomerAccess):
    def __init__(self): pass
    def allowed(self,wid,**kwargs): return True
growth.customer_access=CurrentPaidFixture()
host.oauth=SimpleNamespace(providers={
    'instagram':InstagramProvider('synthetic','synthetic',production_reviewed=True),
    'threads':ThreadsProvider('synthetic','synthetic',production_reviewed=True)})
def restore(state,actor):
    next(c for c in state['phase2']['channels'] if c['id']==ig)['revoked']=False
    state['growthConsent']={'audience':True,'routes':list(ROUTES)+[SUMMARY_ROUTE]}
    return state
host.repository.command(wid,'one',host.get(wid,'one')['revision'],restore)
with connection() as db:
    for provider,cid in [('instagram',ig),('threads','phase2-fixture-account')]:
        scopes=sorted(set(host.oauth.providers[provider].capability_scopes('comments_read')+host.oauth.providers[provider].capability_scopes('analytics')))
        db.execute("INSERT INTO pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes,access_expires_at) VALUES(%s,%s,%s,'synthetic','sealed','k',%s,to_timestamp(%s))",(wid,cid,provider,scopes,time.time()+3600))
    db.execute("INSERT INTO pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'analytics','Direct')",(wid,ig))
def observations():
    with host.repository.transaction('one',wid) as (cur,row,_):return growth.closed_loop._observations(cur,wid,row[1])[0]
assert len(observations())==7
with connection() as db:db.execute("UPDATE pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'",(wid,ig))
assert len(observations())==6,'Stored native readings cannot override current Unsupported analytics'
with connection() as db:db.execute("UPDATE pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'",(wid,ig))
assert len(comments())==7
adapter=host.oauth.providers['instagram']
adapter.production_reviewed=False
assert len(comments())==6,'Retained app-role comments cannot admit public paid analysis'
adapter.production_reviewed=True;adapter.execution_enabled=False
assert len(comments())==6,'Paused provider must remove retained comments'
adapter.execution_enabled=True
for change in ("scopes=ARRAY['instagram_business_basic']", "access_expires_at=now()-interval '1 second'", "revoked_at=now()", "provider='threads'"):
    with connection() as db:db.execute('UPDATE pr_encrypted_credentials SET '+change+' WHERE workspace_id=%s AND connection_id=%s',(wid,ig))
    assert len(comments())==6,change
    with connection() as db:db.execute("UPDATE pr_encrypted_credentials SET provider='instagram',scopes=%s,access_expires_at=to_timestamp(%s),revoked_at=NULL WHERE workspace_id=%s AND connection_id=%s",(adapter.capability_scopes('comments_read'),time.time()+3600,wid,ig))
# Isolate one eligible provider to exercise preparation, attempt guards and completion.
host.oauth.providers['threads'].production_reviewed=False
adapter.production_reviewed=False
before=len(models.calls)
try:growth.closed_loop.mine(wid,'one',{'days':30,'confirmed':True,'requestKey':'unreviewed-comment-case-01'})
except AlphaError as error:assert error.status==409
else:raise AssertionError('Unreviewed comments reached analysis preparation')
assert len(models.calls)==before
adapter.production_reviewed=True
models.before=lambda:setattr(adapter,'execution_enabled',False)
try:growth.closed_loop.mine(wid,'one',{'days':30,'confirmed':True,'requestKey':'paused-mid-comment-case-01'})
except AlphaError as error:assert error.status==409
else:raise AssertionError('Comment output committed after public provider suspension')
with connection() as db:
    assert db.execute("SELECT status FROM pr_post_doctor_runs WHERE workspace_id=%s AND request_key='paused-mid-comment-case-01'",(wid,)).fetchone()[0]=='cancelled'
print(json.dumps({'execution': 'local disposable PostgreSQL; synthetic posts/comments and deterministic model fixtures; no external model or provider calls',
    'checks': ['mixed native providers', 'provider/connection/post ownership', 'redaction', 'Unsupported capability', 'tombstone', 'revocation', 'second workspace', 'read is free','current public review/execution/scopes/expiry','preparation and completion fences']}))
