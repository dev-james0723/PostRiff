"""FINAL-05 on disposable PostgreSQL: estimate and ceiling come from the request the writer would receive.

- The server returns a labelled single-attempt estimate and the conservative ceiling it will hold,
  before any approval; the estimate is below the ceiling and grows with the brief.
- A limit below the ceiling is refused when the quote is issued (not after approval), naming the ceiling.
- A limit at the ceiling completes, holds no more than approved, and charges the actual cost.
- Quick-start sends the newly typed thought as the idea (not the workspace's older saved brief).
Synthetic in-process transport only.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.credit_meter import POLICY_VERSION
from postriff_phase2.model_runtime import ServerModelRuntime
from consumer_fixtures import approve_budgets

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
ONE = '00000000-0000-0000-0000-000000000001'
clock = [time.time()]


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


def verify(token):
    if token != 'one':
        raise AlphaError('No access', 403)
    return ONE


verify.session_id = lambda token, principal: 'estimate-session'
verify.auth_time = lambda token, principal: clock[0]
with connection() as db:
    db.execute((Path(__file__).resolve().parents[2] / 'migrations/postriff/020_credit_quotes.sql').read_text())

sent = []


def transport(method, url, headers=None, body=None):
    sent.append(json.loads(body['messages'][-1]['content'].split('\n\n')[0]) if body['messages'][-1]['content'].startswith('{') else body['messages'][-1]['content'])
    return {'status': 200, 'body': {'choices': [{'message': {'content': json.dumps({'variants': [{'platform': 'LinkedIn', 'language': 'en-US', 'text': 'A small creative habit.', 'sourceIds': []}]})}}], 'usage': {'cost': 0.01, 'prompt_tokens': 10, 'completion_tokens': 20}}}


runtime = ServerModelRuntime('synthetic-test-key', model='test/cloud', models=['test/cloud'], prices={'test/cloud': (3, 15)}, transport=transport)
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], ideas_runtime=runtime, credits_enabled=True)
wid = service.bootstrap('one', 'studio')['workspaceId']
with connection() as db:
    cur = db.cursor()
    service.ledger.ensure_entitlement(cur, wid, None)
    ent = {'writingBatches': 10, 'mediaCredits': 1, 'members': 1, 'connectedAccounts': 3, 'storageMb': 200, 'creditPolicy': POLICY_VERSION}
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('estimate-credits','studio',995,'Synthetic credits',0,'active',%s::jsonb) ON CONFLICT(id) DO NOTHING", (json.dumps(ent),))
    db.execute("UPDATE pr_entitlements SET plan_terms_id='estimate-credits' WHERE workspace_id=%s", (wid,))
    service.ledger.credits.grant(cur, wid, ONE, 'estimate-funding', 5_000_000, None)
approve_budgets(connection, wid)
service.mutate(wid, 'one', service.get(wid, 'one')['revision'], 'idea', {'idea': 'An older saved brief about gardening'})
base = {'ownContent': True, 'confirmUse': True, 'model': 'test/cloud', 'reasoning': 'quick', 'research': False, 'timeZone': 'UTC', 'destinations': [{'platform': 'LinkedIn', 'language': 'en-US'}]}
checks = []

short = service.ideas.credit_requests.estimate(wid, 'one', {'operation': 'quick-start', 'request': {**base, 'text': 'A small creative habit.'}})
long = service.ideas.credit_requests.estimate(wid, 'one', {'operation': 'quick-start', 'request': {**base, 'text': 'A small creative habit. ' * 400}})
for result in (short, long):
    assert 0 < result['estimateMilliCredits'] < result['ceilingMilliCredits'], result
    assert result['estimateMilliCredits'] % 100 == 0 and result['ceilingMilliCredits'] % 100 == 0, result
    assert 'not measured' in result['basis'], result['basis']
    assert (result['model'], result['policy']) == ('test/cloud', POLICY_VERSION), result
assert long['ceilingMilliCredits'] > short['ceilingMilliCredits'] and long['estimateMilliCredits'] > short['estimateMilliCredits'], (short, long)
deep = service.ideas.credit_requests.estimate(wid, 'one', {'operation': 'quick-start', 'request': {**base, 'reasoning': 'deep', 'text': 'A small creative habit.'}})
assert deep['ceilingMilliCredits'] > short['ceilingMilliCredits'], (deep, short)
checks.append(f"estimate {short['estimateMilliCredits']/1000:.1f} / ceiling {short['ceilingMilliCredits']/1000:.1f} credits for a short brief; both grow with the brief and deep mode; labelled as not measured")

latest = service.get(wid, 'one')
request = {**base, 'text': 'A small creative habit.'}
try:
    service.ideas.credit_requests.issue(wid, 'one', {'request': request, 'expectedRevision': latest['revision'], 'maxMilliCredits': short['ceilingMilliCredits'] - 100})
except AlphaError as error:
    assert error.status == 402 and f"{short['ceilingMilliCredits'] / 1000:.1f}" in str(error), (error.status, str(error))
else:
    raise AssertionError('a limit below the ceiling was approved')
checks.append('a limit below the ceiling is refused at quote time, naming the ceiling')

quote = service.ideas.credit_requests.issue(wid, 'one', {'request': request, 'expectedRevision': latest['revision'], 'maxMilliCredits': short['ceilingMilliCredits']})
result = service.ideas.quick_start(wid, 'one', latest['revision'], {**request, 'creditQuoteId': quote['quoteId'], 'idempotencyKey': 'estimate-run'})
assert result['status'] == 'completed', result
with connection() as db:
    view = service.ledger.credits.view(db.cursor(), wid)
assert (view['heldMilliCredits'], view['usedMilliCredits']) == (0, 3000), view
checks.append('a limit at the ceiling completes; the actual 0.01 USD is charged as 3.0 credits and nothing stays held')

idea = sent[-1]['idea'] if isinstance(sent[-1], dict) else ''
assert idea == 'A small creative habit.', idea
checks.append('quick-start sends the typed thought as the idea, not the older saved brief')

for line in checks:
    print('PASS:', line)
