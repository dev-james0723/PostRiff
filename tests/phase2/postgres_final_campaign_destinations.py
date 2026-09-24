"""FINAL-08 on disposable PostgreSQL: a recurring campaign task drafts for the destination, language and
voice it was confirmed with, whatever words the campaign data contains, and still runs in a workspace on
credit terms when its route is free. Synthetic in-process writer only; nothing is published.
"""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime import FixtureAgentRuntime
from postriff_phase2.campaign_worker import CampaignWorker
from postriff_phase2.credit_meter import POLICY_VERSION
from postriff_phase2.hosted import HostedWorkspaceService
from consumer_fixtures import approve_budgets

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')
ONE = '00000000-0000-0000-0000-000000000001'
clock = [1_800_000_000.0]


def connection():
    return psycopg.connect(DSN)


def verify(token):
    # Strict like production: only a real session token verifies; the worker's in-process capability does not.
    if token != 'one':
        raise AlphaError('Verified session required.', 401)
    return ONE


verify.session_id = lambda token, principal: 'session-campaign-destinations'
verify.auth_time = lambda token, principal: clock[0]
with connection() as db:
    db.execute((Path(__file__).resolve().parents[2] / 'migrations/postriff/020_credit_quotes.sql').read_text())
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], credits_enabled=True)
workspace = service.bootstrap('one', 'studio')['workspaceId']
approve_budgets(connection, workspace)


class Recording(FixtureAgentRuntime):
    def __init__(self):
        self.requests = []

    def start_turn(self, request, emit):
        self.requests.append({'destinations': request['destinations'], 'voice': request['voiceContext']['mode'], 'idea': request['idea']})
        return super().start_turn(request, emit)


runtime = Recording()
service.ideas.runtime = runtime
service.ideas.runtimes = [runtime]


def act(action, payload):
    return service.mutate(workspace, 'one', service.get(workspace, 'one')['revision'], action, payload)


def task_for(goal, **choice):
    state = act('raffi_campaign_create', {'goal': goal, 'audience': 'Students'})['state']
    campaign = state['raffi']['campaignPlanning']['campaigns'][-1]
    state = act('raffi_recurrence_preview', {'campaignId': campaign['id'], 'route': 'deterministic-preview', 'maxCostUsdMicro': 0, 'schedule': {'weekday': 'Monday', 'localTime': '09:00', 'timeZone': 'Asia/Hong_Kong'}, **choice})['state']
    task = state['raffi']['campaignPlanning']['recurringTasks'][-1]
    act('raffi_recurrence_activate', {'taskId': task['id'], 'confirmed': True})
    clock[0] = task['nextOccurrence']['scheduledFor'] + 1
    return task


checks = []
# 1. Confirmed destination and language win over platform/language words inside the campaign data.
task = task_for('Post on Instagram in French every week, and remember to add hashtags', destination={'platform': 'Threads', 'language': 'zh-Hant-HK'})
# Recurring drafts are always neutral (the automation worker never upgrades to a personal voice).
assert task['destination'] == {'platform': 'Threads', 'language': 'zh-Hant-HK'} and 'voiceMode' not in task, task
result = CampaignWorker(service).tick()
assert result.get('state') == 'completed', result
sent = runtime.requests[-1]
assert [(d['platform'], d['language']) for d in sent['destinations']] == [('Threads', 'zh-Hant-HK')], sent
assert sent['voice'] == 'neutral'
checks.append('the task drafts for its confirmed Threads zh-Hant-HK destination although the goal names Instagram and French; not read as a memory instruction')
act('raffi_recurrence_pause', {'taskId': task['id']})

# 2. A destination for a connected account must name one this workspace has; unknown ones are refused.
try:
    task_for('Weekly notes', destination={'platform': 'LinkedIn', 'channelId': 'not-a-connection', 'language': 'en-GB'})
except AlphaError as error:
    assert error.status in (400, 409), error.status
else:
    raise AssertionError('an unknown account was accepted as a recurring destination')
checks.append('a recurring destination naming an unknown account is refused')

# 3. The same free route keeps working when the workspace moves to credit terms (worker credit checks use its own authority).
with connection() as db:
    cur = db.cursor()
    service.ledger.ensure_entitlement(cur, workspace, None)
    ent = {'writingBatches': 10, 'mediaCredits': 1, 'members': 1, 'connectedAccounts': 3, 'storageMb': 200, 'creditPolicy': POLICY_VERSION}
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('campaign-credits','studio',989,'Synthetic credits',0,'active',%s::jsonb) ON CONFLICT(id) DO NOTHING", (json.dumps(ent),))
    db.execute("UPDATE pr_entitlements SET plan_terms_id='campaign-credits' WHERE workspace_id=%s", (workspace,))
task = task_for('Weekly teaching notes', destination={'platform': 'LinkedIn', 'language': 'en-GB'})
result = CampaignWorker(service).tick()
assert result.get('state') == 'completed', result
assert [(d['platform'], d['language']) for d in runtime.requests[-1]['destinations']] == [('LinkedIn', 'en-GB')]
checks.append('in a workspace on credit terms, a free-route recurring task still completes (no false authority failure)')
act('raffi_recurrence_pause', {'taskId': task['id']})

# 4. A task created without a destination keeps the previous behaviour: LinkedIn, the stated language, neutral voice.
task = task_for('Weekly teaching notes')
assert task['destination']['platform'] == 'LinkedIn' and 'voiceMode' not in task, task
result = CampaignWorker(service).tick()
assert result.get('state') == 'completed' and runtime.requests[-1]['voice'] == 'neutral', (result, runtime.requests[-1])
checks.append('a task without a chosen destination keeps LinkedIn and drafts in a neutral voice (no silent upgrade to personalized)')

for line in checks:
    print('PASS:', line)
