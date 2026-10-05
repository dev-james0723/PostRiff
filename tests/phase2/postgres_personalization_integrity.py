"""Real disposable PostgreSQL and ordinary service paths; synthetic inputs, zero model calls."""
import json
import os
import time
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.billing import Ledger, Billing, require_publishing

ONE = '00000000-0000-0000-0000-000000000001'
DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')
def connection():
    return psycopg.connect(DSN)
def verify(token):
    if token != 'ordinary-synthetic':
        raise AlphaError('Verified session required.', 401)
    return ONE
verify.session_id = lambda *args: 'synthetic-ordinary-session'
verify.auth_time = lambda *args: time.time()
host = HostedWorkspaceService(connection, verify)
initial = host.bootstrap('ordinary-synthetic', 'studio')
wid = initial['workspaceId']
def state():
    return host.get(wid, 'ordinary-synthetic')
def fixture_profile(revision):
    def command(saved, actor):
        saved['speaker']['activeRevision'] = revision
        saved['speaker'].setdefault('revisions', []).append({'revision': revision, 'profile': {'tone': 'formal', 'observations': ['Synthetic owner direction.']}})
        saved['memoryEgress'] = {'cloud': True}
        return saved
    return host.repository.command(wid, 'ordinary-synthetic', state()['revision'], command)
fixture_profile(1)
run = host.ideas.quick_start(wid, 'ordinary-synthetic', state()['revision'], {'text': 'Synthetic seed swap. Visitors may bring seeds.',
    'ownContent': True, 'confirmUse': True, 'voiceMode': 'personalized', 'destinations': [{'platform': 'LinkedIn', 'language': 'en'}]})
record = run['artifact']['generationProvenance']
assert record['execution'] == 'fixture' and run['usage']['modelRequests'] == 0
assert record['voiceRevision'] == 1 and record['profile']['kind'] == 'owner_direction'
fixture_profile(2)
applied = host.ideas.apply(wid, 'ordinary-synthetic', state()['revision'], run['runId'], run['artifactHash'])
draft = next(v for v in state()['state']['variants'] if v['id'] == applied['variantIds'][0]['variantId'])
assert draft['voiceRevision'] == 1 and draft['generationProvenance'] == record
assert draft['needsReview'] and state()['state']['speaker']['activeRevision'] == 2
thread = host.ideas.messages(wid, 'ordinary-synthetic', run['conversationId'])
assert any(m['body'].get('generationProvenance') == record for m in thread['messages'])
neutral_run = host.ideas.quick_start(wid, 'ordinary-synthetic', state()['revision'], {'text': 'Synthetic neutral invitation: bring seeds.',
    'ownContent': True, 'confirmUse': True, 'voiceMode': 'neutral', 'destinations': [{'platform': 'LinkedIn', 'language': 'en'}]})
neutral_saved = host.ideas.apply(wid, 'ordinary-synthetic', state()['revision'], neutral_run['runId'], neutral_run['artifactHash'], separate=True)
neutral = next(v for v in state()['state']['variants'] if v['id'] == neutral_saved['variantIds'][0]['variantId'])
assert neutral['voiceRevision'] is None and neutral['generationProvenance']['profile']['used'] is False
host.mutate(wid, 'ordinary-synthetic', state()['revision'], 'p2_variant_review', {'variantId': neutral['id'],
    'variantRevision': neutral['revision'], 'confirmed': True, 'excludedUnknowns': neutral['unknowns']})

# Campaign identity and the brief used by the writer survive apply. Changed briefs need a new run.
from postriff_phase2 import campaigns, insights
def mutate(action, payload):
    return host.mutate(wid, 'ordinary-synthetic', state()['revision'], action, payload)
mutate('raffi_campaign_create', {'goal': 'Synthetic seed swap', 'audience': 'Neighbourhood', 'facts': {'date': '2026-10-20'}})
campaign = campaigns._root(state()['state'])['campaigns'][-1]
payload = {'text': 'Write one seed swap invitation.', 'ownContent': True, 'confirmUse': True,
    'materialRef': {'type': 'campaign', 'id': campaign['id']}, 'destinations': [{'platform': 'LinkedIn', 'language': 'en'}]}
campaign_run = host.ideas.quick_start(wid, 'ordinary-synthetic', state()['revision'], payload)
binding = campaign_run['artifact']['generationProvenance']['campaignBinding']
assert binding == campaigns.brief_binding(state()['state'], campaign['id'])
mutate('raffi_campaign_update', {'campaignId': campaign['id'], 'facts': {'date': '2026-10-21'}})
try:
    host.ideas.apply(wid, 'ordinary-synthetic', state()['revision'], campaign_run['runId'], campaign_run['artifactHash'])
    raise AssertionError('changed campaign brief accepted')
except AlphaError as error:
    assert error.status == 409
fresh = host.ideas.quick_start(wid, 'ordinary-synthetic', state()['revision'], payload)
applied_campaign = host.ideas.apply(wid, 'ordinary-synthetic', state()['revision'], fresh['runId'], fresh['artifactHash'], separate=True)
assert next(v for v in state()['state']['variants'] if v['id'] == applied_campaign['variantIds'][0]['variantId'])['campaignId'] == campaign['id']

# Canonical metric names also cover legacy persisted native names, without blending job/definition cohorts.
with connection() as db:
    for metric, value, age, version, job in [('saved', 4, 30, 'native-v1', 'job-one'), ('saves', 7, 10, 'native-v1', 'job-one'),
                                          ('saved', 9, 0, 'other-definition', 'job-two')]:
        db.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at,source_endpoint) VALUES(%s,'synthetic-ig','instagram','synthetic-post',%s,%s,%s,%s,'count','available',now()-%s*interval '1 second',%s)",
                   (wid, job, metric, version, value, age, insights.insights_endpoint('instagram', 'synthetic-post')))
    rows = insights.latest_observations(db.cursor(), wid, include_endpoint=True)
    assert len(rows) == 2 and {r[3] for r in rows} == {'saves'}
    assert {r[2]: (r[4], int(r[5])) for r in rows} == {'job-one': ('native-v1', 7), 'job-two': ('other-definition', 9)}
    summary = insights.summary(db.cursor(), wid, [], time.time())
    assert all(p['metrics']['saves']['nativeName'] == 'saved' for p in summary['posts'])
    assert 'saves' in summary['families']['resonance']

# Remaining allowance and prepaid credit cannot extend an expired trial.
with connection() as db:
    db.execute("UPDATE public.pr_subscriptions SET status='trial',current_period_end=now()-interval '1 second' WHERE workspace_id=%s", (wid,))
    db.execute("UPDATE public.pr_trials SET expires_at=now()-interval '1 second' WHERE workspace_id=%s", (wid,))
for remaining in (10, 0):
    with connection() as db:
        db.execute('UPDATE public.pr_entitlements SET writing_batches_remaining=%s WHERE workspace_id=%s', (remaining, wid))
        before = db.execute('SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s', (wid,)).fetchone()[0]
        for dimension in ('text_model', 'image_generation'):
            try:
                Ledger().reserve(db.cursor(), wid, ONE, dimension, 0, f'expired-{remaining}-{dimension}', charge_batch=True)
                raise AssertionError('expired AI reservation accepted')
            except AlphaError as error:
                assert error.status == 402 and error.code == 'ai_plan_inactive'
        life = Billing().lifecycle(db.cursor(), wid, time.time())
        assert not life['canGenerateAI'] and not life['canPublish'] and life['draftsRetained'] and life['exportAvailable']
        try:
            require_publishing(db.cursor(), wid, time.time())
            raise AssertionError('expired publication accepted')
        except AlphaError as error:
            assert error.status == 402 and error.code == 'publishing_plan_inactive'
        assert db.execute('SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s', (wid,)).fetchone()[0] == before
        assert db.execute('SELECT writing_batches_remaining FROM public.pr_entitlements WHERE workspace_id=%s', (wid,)).fetchone()[0] == remaining
print(json.dumps({'status': 'PASS', 'execution': 'disposable PostgreSQL; synthetic ordinary identity and fixture writer',
    'checks': ['frozen generation revision survives later voice approval and apply', 'conversation and draft retain identical generation record',
               'expired trial with positive or zero allowance refuses writing, media and publishing before any ledger debit'],
    'productModelCalls': 0}))
