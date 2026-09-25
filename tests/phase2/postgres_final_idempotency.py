"""FINAL-02/05 on disposable PostgreSQL: one request key is one billable task.

- An exact HTTP resend of quick-start or a follow-up turn replays the original run: no second model
  call, no second credit reservation, even though the quote was already claimed.
- The same key with a different request is refused (409), never answered with another request's run.
- A process crash after the reservation leaves one run; a resend with the key finds it instead of
  starting a second paid run. A new click (new key and new quote) is a new task.
All model traffic is a synthetic in-process transport; no external calls.
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


verify.session_id = lambda token, principal: 'idempotency-synthetic-session'
verify.auth_time = lambda token, principal: clock[0]

with connection() as db:
    db.execute((Path(__file__).resolve().parents[2] / 'migrations/postriff/020_credit_quotes.sql').read_text())

calls = []
crash = {'next': False}


def transport(method, url, headers=None, body=None):
    calls.append(body['model'])
    return {'status': 200, 'body': {'choices': [{'message': {'content': json.dumps({'variants': [{'platform': 'LinkedIn', 'language': 'en-US', 'text': 'A small creative habit.', 'sourceIds': []}]})}}], 'usage': {'cost': 0.01, 'prompt_tokens': 10, 'completion_tokens': 20}}}


class CrashingRuntime(ServerModelRuntime):
    def start_turn(self, *args, **kwargs):
        if crash['next']:
            crash['next'] = False
            raise KeyboardInterrupt('simulated process crash after the reservation committed')
        return super().start_turn(*args, **kwargs)


runtime = CrashingRuntime('synthetic-test-key', model='test/cloud', models=['test/cloud'], prices={'test/cloud': (1, 1)}, transport=transport)
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], ideas_runtime=runtime, credits_enabled=True)
snap = service.bootstrap('one', 'studio')
wid = snap['workspaceId']
with connection() as db:
    cur = db.cursor()
    service.ledger.ensure_entitlement(cur, wid, None)
    ent = {'writingBatches': 10, 'mediaCredits': 1, 'members': 1, 'connectedAccounts': 3, 'storageMb': 200, 'creditPolicy': POLICY_VERSION}
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('idem-credits','studio',997,'Synthetic credits',0,'active',%s::jsonb) ON CONFLICT(id) DO NOTHING", (json.dumps(ent),))
    db.execute("UPDATE pr_entitlements SET plan_terms_id='idem-credits' WHERE workspace_id=%s", (wid,))
    service.ledger.credits.grant(cur, wid, ONE, 'idem-funding', 1_000_000, None)
approve_budgets(connection, wid)


def reservations():
    with connection() as db:
        return db.execute("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", (wid,)).fetchone()[0]


def runs():
    with connection() as db:
        return db.execute("SELECT count(*) FROM public.pr_agent_runs WHERE workspace_id=%s", (wid,)).fetchone()[0]


def refused(call, status=409):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return str(error)
    raise AssertionError('accepted a request that must be refused')


base = {'text': 'A small creative habit.', 'ownContent': True, 'confirmUse': True, 'model': 'test/cloud', 'reasoning': 'quick', 'research': False, 'timeZone': 'UTC', 'destinations': [{'platform': 'LinkedIn', 'language': 'en-US'}]}
checks = []

# 1. Exact resend of quick-start replays the first run.
latest = service.get(wid, 'one')
quote = service.ideas.credit_requests.issue(wid, 'one', {'request': base, 'expectedRevision': latest['revision'], 'maxMilliCredits': 90000})
request = {**base, 'creditQuoteId': quote['quoteId'], 'idempotencyKey': 'quick-start-key-1'}
first = service.ideas.quick_start(wid, 'one', latest['revision'], request)
assert first['status'] == 'completed', first
before = (len(calls), reservations(), runs())
again = service.ideas.quick_start(wid, 'one', latest['revision'], request)
assert (again['runId'], again['conversationId'], again['sourceId']) == (first['runId'], first['conversationId'], first['sourceId']), (again, first)
assert (len(calls), reservations(), runs()) == before, ((len(calls), reservations(), runs()), before)
checks.append('quick-start resend replays the original run: no second model call, reservation or run')

# 2. The same key with a different request is refused.
refused(lambda: service.ideas.quick_start(wid, 'one', latest['revision'], {**request, 'text': 'A different request.'}))
assert (len(calls), reservations(), runs()) == before
checks.append('quick-start: same key + different request -> 409, nothing stored or charged')

# 3. Follow-up turn: exact resend replays; different payload with the same key is refused.
conversation = first['conversationId']
turn_body = {'text': 'Make it shorter.', 'model': 'test/cloud', 'reasoning': 'quick', 'research': False, 'timeZone': 'UTC', 'destinations': [{'platform': 'LinkedIn', 'language': 'en-US'}]}
latest = service.get(wid, 'one')
turn_quote = service.ideas.credit_requests.issue(wid, 'one', {'request': turn_body, 'operation': 'turn', 'expectedRevision': latest['revision'], 'maxMilliCredits': 90000, 'conversationId': conversation})
turn_request = {**turn_body, 'expectedRevision': latest['revision'], 'creditQuoteId': turn_quote['quoteId'], 'idempotencyKey': 'turn-key-1'}
turn = service.ideas.turn(wid, 'one', conversation, turn_request)
assert turn['status'] == 'completed', turn
before = (len(calls), reservations(), runs())
turn_again = service.ideas.turn(wid, 'one', conversation, turn_request)
assert turn_again['runId'] == turn['runId'], (turn_again, turn)
assert (len(calls), reservations(), runs()) == before
refused(lambda: service.ideas.turn(wid, 'one', conversation, {**turn_request, 'text': 'Make it longer instead.'}))
assert (len(calls), reservations(), runs()) == before
checks.append('turn: resend replays the original run even though its quote was claimed; different request -> 409')

# 4. Crash after the reservation committed: one run, and the resend does not start a second paid run.
latest = service.get(wid, 'one')
crash_quote = service.ideas.credit_requests.issue(wid, 'one', {'request': {**base, 'text': 'A crash-window idea.'}, 'expectedRevision': latest['revision'], 'maxMilliCredits': 90000})
crash_request = {**base, 'text': 'A crash-window idea.', 'creditQuoteId': crash_quote['quoteId'], 'idempotencyKey': 'crash-key-1'}
crash['next'] = True
calls_before, reservations_before, runs_before = len(calls), reservations(), runs()
try:
    service.ideas.quick_start(wid, 'one', latest['revision'], crash_request)
except KeyboardInterrupt:
    pass
else:
    raise AssertionError('the simulated crash did not happen')
assert (runs(), reservations()) == (runs_before + 1, reservations_before + 1), (runs(), reservations())
resent = service.ideas.quick_start(wid, 'one', latest['revision'], crash_request)
assert (runs(), reservations(), len(calls)) == (runs_before + 1, reservations_before + 1, calls_before), (runs(), reservations(), len(calls))
assert resent['status'] == 'running', resent['status']
checks.append('crash after reservation: resend finds the same run (still running), no second reservation or model call')

# 5. A new click is a new task: new key and new quote.
latest = service.get(wid, 'one')
new_quote = service.ideas.credit_requests.issue(wid, 'one', {'request': base, 'expectedRevision': latest['revision'], 'maxMilliCredits': 90000})
fresh = service.ideas.quick_start(wid, 'one', latest['revision'], {**base, 'creditQuoteId': new_quote['quoteId'], 'idempotencyKey': 'quick-start-key-2'})
assert fresh['status'] == 'completed' and fresh['runId'] != first['runId']
checks.append('a new key with a new quote is a separate task')

for line in checks:
    print('PASS:', line)
