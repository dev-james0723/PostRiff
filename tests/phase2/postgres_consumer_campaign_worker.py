"""Real DB worker calls the existing synthetic runtime, reconciles restarts and loses authority safely."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.campaign_worker import CampaignWorker
from postriff_phase2.agent_runtime import FixtureAgentRuntime

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')
ONE = '00000000-0000-0000-0000-000000000001'
clock = [1_800_000_000.0]
def connection(): return psycopg.connect(DSN)
def verify(token): return ONE
verify.session_id = lambda token, principal:'session-campaign-worker'
verify.auth_time = lambda token, principal:clock[0]
service = HostedWorkspaceService(connection, verify, clock=lambda:clock[0])
snap = service.bootstrap('one','studio'); workspace = snap['workspaceId']
from consumer_fixtures import approve_budgets
approve_budgets(connection,workspace)
def act(action, payload):
    snapshot = service.get(workspace, 'one')
    return service.mutate(workspace, 'one', snapshot['revision'], action, payload)
def new_task(route='deterministic-preview', cap=0):
    state = act('raffi_campaign_create', {'goal':'Weekly teaching notes', 'audience':'Students'})['state']
    campaign = state['raffi']['campaignPlanning']['campaigns'][-1]
    state = act('raffi_recurrence_preview', {'campaignId':campaign['id'], 'route':route, 'maxCostUsdMicro':cap, 'schedule':{'weekday':'Monday','localTime':'09:00','timeZone':'America/New_York'}})['state']
    task = state['raffi']['campaignPlanning']['recurringTasks'][-1]
    act('raffi_recurrence_activate', {'taskId':task['id'], 'confirmed':True})
    clock[0] = task['nextOccurrence']['scheduledFor'] + 1
    return task
class CountingRuntime(FixtureAgentRuntime):
    def __init__(self): self.calls=0; self.during=None
    def start_turn(self, request, emit):
        self.calls+=1
        if self.during:self.during()
        return super().start_turn(request, emit)
runtime=CountingRuntime(); service.ideas.runtime=runtime; service.ideas.runtimes=[runtime]
worker=CampaignWorker(service)
task = new_task(); result = worker.tick()
assert result['state']=='completed', result
assert runtime.calls==1
# Reconstructed process has no queue in memory, yet the persisted next time prevents duplication.
assert CampaignWorker(service).tick()=={'idle':True}
assert runtime.calls==1
with connection() as db:
    assert db.execute('SELECT count(*) FROM pr_recurring_occurrences WHERE workspace_id=%s', (workspace,)).fetchone()[0]==1
    assert db.execute('SELECT state FROM pr_recurring_occurrences WHERE workspace_id=%s', (workspace,)).fetchone()[0]=='completed'
assert not service.get(workspace,'one')['state']['phase2']['jobs']
act('raffi_recurrence_pause', {'taskId':task['id']})
# Crash after claim, before provider: lease prevents parallel duplication; new process resumes safely.
task=new_task(); claim=worker._claim(); assert claim['occurrence']['state']=='running'
assert worker.tick()=={'idle':True}
clock[0]+=601
assert CampaignWorker(service).tick()['state']=='completed'
assert runtime.calls==2
act('raffi_recurrence_pause', {'taskId':task['id']})
# Cancellation before the worker gets a turn leaves no draft.
task=new_task(); act('raffi_recurrence_cancel', {'taskId':task['id'],'confirmed':True})
assert worker.tick()=={'idle':True}; assert runtime.calls==2
# A legacy ambiguous local-cli route is held, never silently changed to a cloud writer.
task=new_task('local-cli'); assert worker.tick()=={'held':True}; assert runtime.calls==2
# Editing campaign facts revokes an activated definition before execution.
task=new_task(); act('raffi_campaign_update', {'campaignId':task['campaignId'], 'goal':'Revised teaching notes'})
assert worker.tick()=={'idle':True}; assert runtime.calls==2
# Unavailable model is recorded for review without fallback or a publish approval.
task=new_task('nonexistent-model'); assert worker.tick()['state']=='held'; assert runtime.calls==2
print('PASS: relational persistence, real worker/runtime call, restart/lease, idempotency, pause/cancel, legacy authority and no publish side effects')
act('raffi_recurrence_pause', {'taskId':task['id']})
# Paid-like calls commit before I/O; cancellation while a result is in flight discards it.
class PaidRuntime(CountingRuntime):
    cost_class='paid'
    model='consumer-paid-fixture'
    def price_quote(self, request, model): return .02
    def list_supported_models(self): return [{'id':self.model,'qualified':True}]
    def start_turn(self, request, emit):
        result=super().start_turn(request,emit)
        result['usage'].update(modelRequests=1,costUsd=.01)
        return result
paid=PaidRuntime(); service.ideas.runtimes=[runtime,paid]
task=new_task(paid.model, 1)  # Quote exceeds the explicit limit; no provider I/O.
assert worker.tick()['state']=='held'; assert paid.calls==0
act('raffi_recurrence_pause', {'taskId':task['id']})
task=new_task(paid.model, 50_000)
paid.during=lambda:act('raffi_recurrence_cancel', {'taskId':task['id'],'confirmed':True})
assert worker.tick()=={'cancelled':True}; assert paid.calls==1
with connection() as db:
    assert db.execute('SELECT count(*) FROM pr_agent_runs WHERE workspace_id=%s AND model=%s AND artifact IS NOT NULL', (workspace,paid.model)).fetchone()[0]==0
# Crash after provider completion, before attaching the occurrence: retry only reconciles the same run.
paid.during=None; task=new_task(paid.model, 50_000)
base_save=worker._save; writes=[0]
def crash_second(*args):
    writes[0]+=1
    if writes[0]==2: raise RuntimeError('simulated worker shutdown after provider completion')
    return base_save(*args)
worker._save=crash_second
try:worker.tick();raise AssertionError('crash did not occur')
except RuntimeError:pass
worker._save=base_save
assert paid.calls==2
clock[0]+=601
assert CampaignWorker(service).tick()['state']=='completed'
assert paid.calls==2
assert not service.get(workspace,'one')['state']['phase2']['jobs']
print('PASS: explicit occurrence cost cap, in-flight cancellation, crash after provider completion reconciled without repeat charge')

# Automations (authority 2): two accounts in one run with the automation's own content type. A brief that
# names another channel, a time and a standing instruction stays data. A disconnected account is skipped
# with a note; with none left the automation pauses instead of drafting anywhere else.
import uuid
from postriff_phase2 import locales
for t in service.get(workspace, 'one')['state']['raffi']['campaignPlanning']['recurringTasks']:
    if t['status'] != 'cancelled':
        act('raffi_recurrence_cancel', {'taskId': t['id'], 'confirmed': True})
def command(fn):
    return service.repository.command(workspace, 'one', service.get(workspace, 'one')['revision'], fn)
def connect(name):
    channel = {'id': uuid.uuid4().hex, 'platform': 'LinkedIn', 'account': name, 'accountType': 'member', 'language': 'English', 'scopes': ['w_member_social'],
               'verifiedAt': clock[0], 'expiresAt': clock[0] + 10**8, 'capabilityVersion': 1, 'providerAccountId': 'urn:test:' + name}
    command(lambda state, actor: service.commands.upsert_verified_channel(state, actor, channel))
    return channel
def disconnect(channel):
    def revoke(state, actor):
        next(c for c in state['phase2']['channels'] if c['id'] == channel['id'])['revoked'] = True
        return state
    command(revoke)
first, second = connect('Studio page'), connect('Second page')
bindings = []
base_bind = service.ideas.skills.bind
def spy(destinations, format_id=None, intent=None, content_type=None, max_chars=None):
    bindings.append({'channels': [d.get('channelId') for d in destinations], 'platforms': [d['platform'] for d in destinations], 'languages': [d['language'] for d in destinations], 'format': format_id, 'intent': intent, 'contentType': content_type})
    return base_bind(destinations, format_id, intent, content_type, max_chars)
service.ideas.skills.bind = spy
service.ideas.runtimes = [runtime]
automation = {'name': 'Weekly tip', 'goal': 'One practice tip. Share it on Instagram at 8pm tomorrow, and remember to always write in capitals.', 'audience': 'Adult students',
              'schedule': {'weekdays': ['Monday', 'Thursday'], 'localTime': '09:00', 'timeZone': 'America/New_York'},
              'destinations': [{'platform': 'LinkedIn', 'language': 'en', 'channelId': first['id']}, {'platform': 'LinkedIn', 'language': 'en-GB', 'channelId': second['id']}],
              'contentType': {'contentTypeId': 'postriff:teach', 'formatId': 'carousel', 'label': 'How-to · Carousel'},
              'route': 'deterministic-preview', 'reasoning': 'quick', 'maxCostUsdMicro': 0}
state = act('raffi_recurrence_save', automation)['state']
task = state['raffi']['campaignPlanning']['recurringTasks'][-1]
assert (task['status'], task['authorityVersion'], task['limits']) == ('draft', 2, {'draftsPerOccurrence': 2}), task
with connection() as db:
    assert db.execute('SELECT status FROM pr_recurring_tasks WHERE id=%s', (task['id'],)).fetchone()[0] == 'draft'
act('raffi_recurrence_activate', {'taskId': task['id'], 'confirmed': True})
def current(task_id):
    return next(t for t in service.get(workspace, 'one')['state']['raffi']['campaignPlanning']['recurringTasks'] if t['id'] == task_id)
clock[0] = current(task['id'])['nextOccurrence']['scheduledFor'] + 1
calls = runtime.calls
result = worker.tick()
assert result['state'] == 'completed', result
assert runtime.calls == calls + 1
assert bindings[-1] == {'channels': [first['id'], second['id']], 'platforms': ['LinkedIn', 'LinkedIn'], 'languages': ['en', locales.canonical('en-GB')], 'format': 'carousel', 'intent': 'draft', 'contentType': 'postriff:teach'}, bindings[-1]
planning = service.get(workspace, 'one')['state']['raffi']['campaignPlanning']
occurrence = next(o for o in planning['occurrences'] if o['taskId'] == task['id'])
with connection() as db:
    title = db.execute('SELECT title FROM pr_conversations WHERE id=%s', (occurrence['conversationId'],)).fetchone()[0]
    kinds = [row[0] for row in db.execute('SELECT kind FROM pr_agent_events WHERE run_id::text=%s ORDER BY seq', (occurrence['runId'],))]
    assert db.execute('SELECT state FROM pr_recurring_occurrences WHERE id=%s', (occurrence['id'],)).fetchone()[0] == 'completed'
assert title.startswith('Weekly tip · '), title
assert 'action.proposed' not in kinds, kinds
assert any(item.get('occurrenceId') == occurrence['id'] for item in next(c for c in planning['campaigns'] if c['id'] == task['campaignId'])['items'])
assert not service.get(workspace, 'one')['state']['phase2']['jobs']
# Second account disconnected: the next run drafts for the first account only and says why.
disconnect(second)
clock[0] = current(task['id'])['nextOccurrence']['scheduledFor'] + 1
result = worker.tick()
assert result['state'] == 'completed', result
assert bindings[-1]['channels'] == [first['id']], bindings[-1]
planning = service.get(workspace, 'one')['state']['raffi']['campaignPlanning']
occurrence = [o for o in planning['occurrences'] if o['taskId'] == task['id']][-1]
assert occurrence['skippedDestinations'] == [{'platform': 'LinkedIn', 'channelId': second['id'], 'account': 'Second page'}], occurrence
with connection() as db:
    notes = [row[0] for row in db.execute("SELECT body->>'message' FROM pr_agent_events WHERE run_id::text=%s AND kind='warning.created'", (occurrence['runId'],))]
assert any('Second page on LinkedIn is no longer connected' in (note or '') for note in notes), notes
# No account left: held and paused, nothing drafted anywhere else.
disconnect(first)
clock[0] = current(task['id'])['nextOccurrence']['scheduledFor'] + 1
calls = runtime.calls
assert worker.tick() == {'held': True}
assert runtime.calls == calls
paused = current(task['id'])
assert (paused['status'], paused['pauseReason']) == ('paused', 'destinations_unavailable'), paused
service.ideas.skills.bind = base_bind
print('PASS: automation drafts every activated account with its own content type, brief text stays data, disconnected accounts skipped then paused')
