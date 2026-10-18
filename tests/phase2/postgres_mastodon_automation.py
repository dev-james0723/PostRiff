"""Cloud disposable SQL: actual Automation/Brand Brain/Queue; synthetic writer and Mastodon."""
import html
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg
from consumer_fixtures import approve_budgets
from postriff_phase2.agent_runtime import FixtureAgentRuntime
from postriff_phase2.campaign_worker import CampaignWorker
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.social_connectors import MastodonProvider
from mastodon_browser_fixture import SyntheticMastodon

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')
clock = [time.time()]
actor = str(uuid.uuid4())
def connection(): return psycopg.connect(DSN, client_encoding='utf8')
def verify(token):
    assert token == actor
    return actor
verify.session_id = lambda *_args: 'synthetic-mastodon-automation-session'
verify.auth_time = lambda *_args: clock[0]

class API(SyntheticMastodon):
    def __init__(self):
        super().__init__(); self.posts = {}; self.keys = {}; self.writes = 0
        self.writes_by_instance = {'mastodon.social': 0, 'mastodon.online': 0}
    def __call__(self, method, url, **kw):
        parts = urlsplit(url)
        if parts.path == '/api/v1/statuses' and method == 'POST':
            assert parts.hostname in self.writes_by_instance
            key = kw.get('headers', {}).get('Idempotency-Key'); assert key
            key = (parts.hostname, key)
            if key in self.keys: return self.keys[key]
            body = kw['body']; self.writes += 1; identifier = str(3000 + self.writes)
            self.writes_by_instance[parts.hostname] += 1
            value = {'id': identifier, 'account': {'id': '100'}, 'content': '<p>' + html.escape(body['status']).replace('\n', '<br />') + '</p>',
                     'visibility': body.get('visibility', 'public'), 'spoiler_text': body.get('spoiler_text', ''),
                     'sensitive': body.get('sensitive', False), 'language': body.get('language'), 'media_attachments': [],
                     'in_reply_to_id': body.get('in_reply_to_id'), 'created_at': datetime.fromtimestamp(clock[0], timezone.utc).isoformat(),
                     'url': 'https://' + parts.hostname + '/@SYNTHETIC/' + identifier}
            self.posts[identifier] = value; self.keys[key] = {'status': 200, 'body': value, 'headers': {}}
            return self.keys[key]
        if parts.path.startswith('/api/v1/statuses/') and method == 'GET' and parts.path.rsplit('/', 1)[1] in self.posts:
            value = self.posts[parts.path.rsplit('/', 1)[1]]
            assert urlsplit(value['url']).hostname == parts.hostname, 'Cross-instance readback must not succeed.'
            return {'status': 200, 'body': value, 'headers': {}}
        return super().__call__(method, url, **kw)

class Writer(FixtureAgentRuntime):
    calls = 0
    clean = False
    def start_turn(self, request, emit):
        self.calls += 1
        assert all(d['platform'] == 'Mastodon' for d in request['destinations'])
        result = super().start_turn(request, emit)
        # Explicit synthetic writer for auto eligibility; production checks remain intact.
        if self.clean:
            for variant in result['artifact']['variants']:
                variant['unknowns'] = []
                variant['warnings'] = [w for w in variant['warnings'] if 'Deterministic writing preview' not in w]
        return result

with connection() as db:
    for name in ('131_mastodon_management.sql', '132_mastodon_native_metrics.sql', '133_mastodon_connection_health.sql'):
        db.execute((ROOT / 'migrations/postriff' / name).read_text())
    db.execute('INSERT INTO auth.users VALUES(%s)', (actor,))
api = API(); provider = MastodonProvider('https://rafii.io', production_reviewed=True, transport=api,
    resolver=lambda *_args, **_kw: [(2, 1, 6, '', ('93.184.216.34', 443))])
provider.publish_live_tested = provider.publishing_permission = True  # Synthetic fixture only.
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], vault=CredentialVault(CredentialVault.generate_key()),
    providers={'mastodon': provider}, public_base_url='https://rafii.io')
workspace = service.bootstrap(actor, 'studio')['workspaceId']; approve_budgets(connection, workspace)
service.publishing_live = True
writer = Writer(); service.ideas.runtime, service.ideas.runtimes = writer, [writer]
started = service.oauth.start(workspace, actor, 'mastodon', 'management', {'instance': 'mastodon.social'})
from urllib.parse import parse_qs
connected = service.oauth.complete(workspace, actor, 'mastodon', parse_qs(urlsplit(started['authorizeUrl']).query)['state'][0], 'synthetic-code')
channel = connected['connectionId']
started_b = service.oauth.start(workspace, actor, 'mastodon', 'management', {'instance': 'mastodon.online'})
connected_b = service.oauth.complete(workspace, actor, 'mastodon', parse_qs(urlsplit(started_b['authorizeUrl']).query)['state'][0], 'synthetic-code-b')
channel_b = connected_b['connectionId']
assert channel_b != channel
destinations = [{'platform': 'Mastodon', 'language': 'en', 'channelId': channel}]
# Local disposable-cluster fixture only. Check default-off before explicitly enabling synthetic drafting.
from postriff_phase2.coworker import flags as creation_flags
from postriff_phase2.creation_capabilities import draftable_platforms
creation_flags.attach({})
assert 'Mastodon' not in draftable_platforms(), 'default-on security regression'
creation_flags.attach({'RAFII_CREATION_ALL_PLATFORMS_ENABLED': 'true'})
assert 'Mastodon' in draftable_platforms(), 'synthetic drafting flag failed'
conversation = service.ideas.create_conversation(workspace, actor, 'Synthetic Mastodon Automation')['conversationId']
# Bounded synthetic-only error diagnostics; never log production provider data.
_original_turn = type(service.ideas).turn
def diagnosed_turn(self, *args, **kwargs):
    try:
        return _original_turn(self, *args, **kwargs)
    except Exception as error:
        import traceback
        frames = traceback.extract_tb(error.__traceback__)[-3:]
        print(json.dumps({'marker': 'SYNTHETIC_AUTOMATION_WRITER_ERROR', 'type': type(error).__name__,
            'key': str(error)[:80] if isinstance(error, KeyError) else None,
            'frames': [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name} for f in frames]}), flush=True)
        raise
type(service.ideas).turn = diagnosed_turn
from postriff_phase2 import automation_runs
_original_advance = automation_runs.advance
def diagnosed_advance(*args, **kwargs):
    try:
        return _original_advance(*args, **kwargs)
    except Exception as error:
        import traceback
        frames = traceback.extract_tb(error.__traceback__)[-4:]
        print(json.dumps({'marker': 'SYNTHETIC_AUTOMATION_ADVANCE_ERROR', 'type': type(error).__name__,
            'attribute': error.name if isinstance(error, AttributeError) else None,
            'objectType': type(error.obj).__name__ if isinstance(error, AttributeError) else None,
            'frames': [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name} for f in frames]}), flush=True)
        raise
automation_runs.advance = diagnosed_advance
campaigns = CampaignWorker(service)
social = HostedSocial(service.oauth, {'mastodon': provider})
def publishing(): return PostgresWorker(connection, social=social, clock=lambda: clock[0])
def state(): return service.get(workspace, actor)['state']
def planning(): return state()['raffi']['campaignPlanning']
def task(identifier): return next(t for t in planning()['recurringTasks'] if t['id'] == identifier)
def run(identifier): return next(o for o in planning()['occurrences'] if o['taskId'] == identifier)
def act(action, payload): return service.mutate(workspace, actor, service.get(workspace, actor)['revision'], action, payload)['state']
def say(text): return service.ideas.turn(workspace, actor, conversation, {'text': text, 'destinations': destinations,
    'model': writer.model, 'timeZone': 'UTC', 'voiceMode': 'neutral'})
def create(topic, policy):
    proposed = say('Post an update about my ' + topic + ' tomorrow at 2 PM')['automation']
    assert proposed['pending']['question'] == 'policy'
    assert not task(proposed['taskId']).get('publishAuthority')
    activated = say(policy)['automation']; assert activated['taskId'] == proposed['taskId']
    assert activated['status'] == 'active', {'status': activated['status'], 'needs': activated.get('needs'), 'taskStatus': task(activated['taskId']).get('status')}
    clock[0] = task(activated['taskId'])['nextOccurrence']['scheduledFor'] + 1
    result = campaigns.tick_many(max_runs=1, max_seconds=10)
    assert not result.get('advance', {}).get('error'), result
    assert run(activated['taskId']).get('items'), {'worker': result, 'stage': run(activated['taskId']).get('stage'), 'runState': run(activated['taskId']).get('state'), 'reason': run(activated['taskId']).get('reason')}
    return activated['taskId']
def jobs(identifier): return [j for j in state()['phase2']['jobs'] if (j.get('automation') or {}).get('taskId') == identifier]
def advance_to_commit(identifier):
    from postriff_phase2.publisher import COMMIT_LEAD
    clock[0] = run(identifier)['items'][0]['publishAt'] - COMMIT_LEAD + 1
    outcome = campaigns.tick_many(max_runs=1, max_seconds=10)
    assert jobs(identifier), {'worker': outcome, 'items': [{k: item.get(k) for k in ('state', 'reason', 'lastError', 'publishAt', 'approvedVia')} for item in run(identifier)['items']]}
def complete(identifier, instance='mastodon.social'):
    [job] = jobs(identifier); clock[0] = job['manifest']['timing']['timestamp'] + 1
    for _ in range(8):
        publishing().tick(max_jobs=1, max_seconds=5)
        job = next(j for j in jobs(identifier) if j['id'] == job['id'])
        assert job['state'] not in ('failed', 'held', 'uncertain', 'canceled'), job
        if job['state'] == 'verified': break
        clock[0] += 70
    assert job['state'] == 'verified', job
    assert job['url'] in [p['url'] for p in api.posts.values()]
    assert job['manifest']['providerAccountId'] == '100@' + instance
    assert urlsplit(job['url']).hostname == instance
    assert publishing().tick(max_jobs=1, max_seconds=5).get('processed', 0) == 0
    return job

review = create('music studio', 'Send them to me for approval first')
item = run(review)['items'][0]
assert item['state'] == 'ready_for_review'; assert not jobs(review); assert api.writes == 0
variant = next(v for v in state()['variants'] if v['id'] == item['variantId'])
act('raffi_run_decide', {'occurrenceId': run(review)['id'], 'itemKey': item['key'], 'decision': 'approve',
    'confirmed': True, 'variantRevision': variant['revision'], 'excludedUnknowns': variant['unknowns'],
    'acknowledgedWarnings': variant.get('warnings') or [], 'sourceUse': []})
advance_to_commit(review); [queued] = jobs(review)
assert queued['automation']['approvedVia'] == 'human'; assert queued['approvedBy'] == actor
complete(review); assert api.writes == 1

writer.clean = True
automatic = create('practice notes', 'Publish automatically')
assert task(automatic)['publishAuthority']['grantedBy'] == actor
assert task(automatic)['publishAuthority']['definitionDigest'] == task(automatic)['definitionDigest']
advance_to_commit(automatic); [queued] = jobs(automatic)
assert queued['automation']['approvedVia'] == 'owner_preauthorization'
complete(automatic); assert api.writes == 2

paused = create('daily practice journal', 'Publish automatically')
advance_to_commit(paused); [pending] = jobs(paused)
act('raffi_recurrence_pause', {'taskId': paused})
clock[0] = pending['manifest']['timing']['timestamp'] + 1
publishing().tick(max_jobs=1, max_seconds=5)
assert api.writes == 2, 'Pause must fence actual provider dispatch after queuing.'
assert jobs(paused)[0]['state'] in ('held', 'canceled'), jobs(paused)[0]

# Both instances deliberately report the same local numeric account ID. The
# exact connection/instance must remain in every draft, authority and receipt.
for identifier in (review, automatic):
    act('raffi_recurrence_pause', {'taskId': identifier})
destinations = [{'platform': 'Mastodon', 'language': 'en', 'channelId': channel_b}]
independent = create('daily practice reflections', 'Publish automatically')
advance_to_commit(independent); complete(independent, 'mastodon.online')
assert api.writes_by_instance == {'mastodon.social': 2, 'mastodon.online': 1}
act('raffi_recurrence_pause', {'taskId': independent})

destinations = [{'platform': 'Mastodon', 'language': 'en', 'channelId': channel}]
revoked = create('weekly practice reflections', 'Publish automatically')
advance_to_commit(revoked); [pending] = jobs(revoked)
service.oauth.disconnect(workspace, actor, channel)
clock[0] = pending['manifest']['timing']['timestamp'] + 1
publishing().tick(max_jobs=1, max_seconds=5)
assert api.writes == 3, 'Revocation must fence the already queued account A dispatch.'
assert jobs(revoked)[0]['state'] in ('held', 'canceled'), jobs(revoked)[0]
with connection() as db:
    credentials = dict(db.execute('SELECT connection_id,revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s', (workspace,)).fetchall())
assert credentials[channel] is True and credentials[channel_b] is False
act('raffi_recurrence_pause', {'taskId': revoked})
destinations = [{'platform': 'Mastodon', 'language': 'en', 'channelId': channel_b}]
survivor = create('daily practice observations', 'Publish automatically')
advance_to_commit(survivor); complete(survivor, 'mastodon.online')
assert api.writes_by_instance == {'mastodon.social': 2, 'mastodon.online': 2}
print(json.dumps({'status': 'PASS', 'execution': 'CLOUD SYNTHETIC writer/provider; actual Automation/Queue/SQL',
    'checks': ['current account/instance and Brand Brain draft routing', 'review default has no provider writes',
               'exact human approval through existing Queue and real worker', 'explicit definition-bound owner authority',
               'persisted verified native status readback and restart no duplicate', 'pause after queuing fences external dispatch',
               'same numeric identity on independent instances has exact destinations',
               'revoke account A after queuing blocks A and leaves B functional'],
    'syntheticWrites': api.writes, 'writesByInstance': api.writes_by_instance,
    'realMastodonAcceptance': False, 'paidModelCalls': 0}))
