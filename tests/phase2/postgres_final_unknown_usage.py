"""FINAL-05 on disposable PostgreSQL: a failed paid draft settles by what is proven.

- Refused before any provider request (context over the limit): hold released, nothing used, the
  person sees the specific reason.
- Provider rejected the request (4xx): hold released, not charged, provider cost recorded (0 here).
- Provider outcome unknown (5xx): the hold stays as unknown until reconciled; never shown as free.
- Reconciliation settles an unknown hold exactly once with the operator's evidence and actual cost.
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
from postriff_phase2 import model_runtime
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


verify.session_id = lambda token, principal: 'unknown-usage-session'
verify.auth_time = lambda token, principal: clock[0]
with connection() as db:
    db.execute((Path(__file__).resolve().parents[2] / 'migrations/postriff/020_credit_quotes.sql').read_text())

responses = []
calls = []


cancel_during_call = {'on': False}


def transport(method, url, headers=None, body=None):
    calls.append(body['model'])
    if cancel_during_call['on']:
        cancel_during_call['on'] = False
        with connection() as db:
            running = db.execute("SELECT id::text FROM public.pr_agent_runs WHERE workspace_id=%s AND status='running' ORDER BY created_at DESC LIMIT 1", (wid,)).fetchone()[0]
        service.ideas.cancel(wid, 'one', running)  # the person cancels while this request is in flight
    return responses.pop(0)


runtime = ServerModelRuntime('synthetic-test-key', model='test/cloud', models=['test/cloud'], prices={'test/cloud': (1, 1)}, transport=transport)
runtime.sleep = lambda seconds: None
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], ideas_runtime=runtime, credits_enabled=True)
wid = service.bootstrap('one', 'studio')['workspaceId']
with connection() as db:
    cur = db.cursor()
    service.ledger.ensure_entitlement(cur, wid, None)
    ent = {'writingBatches': 10, 'mediaCredits': 1, 'members': 1, 'connectedAccounts': 3, 'storageMb': 200, 'creditPolicy': POLICY_VERSION}
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('unknown-credits','studio',996,'Synthetic credits',0,'active',%s::jsonb) ON CONFLICT(id) DO NOTHING", (json.dumps(ent),))
    db.execute("UPDATE pr_entitlements SET plan_terms_id='unknown-credits' WHERE workspace_id=%s", (wid,))
    service.ledger.credits.grant(cur, wid, ONE, 'unknown-funding', 1_000_000, None)
approve_budgets(connection, wid)
base = {'text': 'A small creative habit.', 'ownContent': True, 'confirmUse': True, 'model': 'test/cloud', 'reasoning': 'quick', 'research': False, 'timeZone': 'UTC', 'destinations': [{'platform': 'LinkedIn', 'language': 'en-US'}]}


def wallet():
    with connection() as db:
        view = service.ledger.credits.view(db.cursor(), wid)
    return view['availableMilliCredits'], view['heldMilliCredits'], view['usedMilliCredits']


def attempt(text, key):
    latest = service.get(wid, 'one')
    request = {**base, 'text': text}
    quote = service.ideas.credit_requests.issue(wid, 'one', {'request': request, 'expectedRevision': latest['revision'], 'maxMilliCredits': 90000})
    try:
        service.ideas.quick_start(wid, 'one', latest['revision'], {**request, 'creditQuoteId': quote['quoteId'], 'idempotencyKey': key})
    except AlphaError as error:
        return error
    raise AssertionError('the failing attempt succeeded')


def last_settle():
    with connection() as db:
        return db.execute("SELECT cost_state, actual_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind IN ('settle','release') ORDER BY at DESC, id DESC LIMIT 1", (wid,)).fetchone()


checks = []
start = wallet()

# 1. Refused before any provider request: the hold is released and the reason is specific.
limit = model_runtime.MAX_CONTEXT_BYTES
model_runtime.MAX_CONTEXT_BYTES = 10
try:
    error = attempt('An idea whose context is over the limit.', 'refused-before-dispatch')
finally:
    model_runtime.MAX_CONTEXT_BYTES = limit
assert calls == [], calls
assert error.status == 413 and 'over the 60 kB limit' in str(error), (error.status, str(error))
assert wallet() == start, (wallet(), start)
checks.append('refused before any provider request: hold released, nothing used, specific reason shown')

# 2. Provider rejected (4xx): not charged, hold released, provider cost recorded as 0.
responses.append({'status': 400, 'body': {'error': 'invalid request'}})
error = attempt('A request the provider rejects.', 'rejected-by-provider')
assert error.status == 502 and 'not charged' in str(error), str(error)
assert wallet() == start, (wallet(), start)
assert last_settle()[1] == 0, last_settle()
checks.append('provider 4xx: not charged, hold released, provider cost recorded (0)')

# 3. Outcome unknown (5xx): the hold stays until reconciled.
responses.append({'status': 503, 'body': {}})
error = attempt('A request whose outcome is unknown.', 'unknown-outcome')
assert error.status == 502 and 'Check this run' in str(error), str(error)
available, held, used = wallet()
assert held == 90000 and used == start[2], (available, held, used)
checks.append('provider 5xx: 90.0 credits stay held as unknown, nothing shown as free or used')

for line in checks:
    print('PASS:', line)

# 4. Reconciliation through the operator tool: once, with evidence, never guessed.
import subprocess
TOOL = [sys.executable, str(Path(__file__).resolve().parents[2] / 'scripts/reconcile_unknown_usage.py'), '--dsn', DSN]


def tool(*args):
    run = subprocess.run([*TOOL, *args], capture_output=True, text=True)
    return run.returncode, json.loads(run.stdout) if run.stdout.strip().startswith('{') else run.stdout + run.stderr


code, listed = tool('list', '--workspace', wid)
assert code == 0 and len(listed['unknown']) == 1, listed
pending = listed['unknown'][0]
assert pending['runStatus'] == 'failed' and pending['estimatedUsdMicro'] > 0, pending
code, refused_missing = subprocess.run([*TOOL, 'settle', '--workspace', wid, '--reservation', pending['reservationId'], '--outcome', 'failed', '--actual-usd', '0.0123', '--operator', 'ops', '--evidence', ''], capture_output=True, text=True).returncode, None
assert code != 0, 'a settlement without evidence must be refused'
code, settled = tool('settle', '--workspace', wid, '--reservation', pending['reservationId'], '--outcome', 'failed', '--actual-usd', '0.0123', '--operator', 'ops-oncall', '--evidence', 'synthetic gateway request 0001')
assert code == 0 and settled['status'] == 'settled', settled
assert wallet() == start, (wallet(), start)
assert last_settle() == ('released', 12300), last_settle()
code, again = tool('settle', '--workspace', wid, '--reservation', pending['reservationId'], '--outcome', 'completed', '--actual-usd', '1', '--operator', 'ops-oncall', '--evidence', 'second try')
assert code == 2 and again['httpStatus'] == 409, again
assert wallet() == start
with connection() as db:
    audit = db.execute("SELECT meta FROM public.pr_audit_events WHERE workspace_id=%s AND kind='usage.reconciled'", (wid,)).fetchall()
assert len(audit) == 1 and audit[0][0]['evidence'] == 'synthetic gateway request 0001' and audit[0][0]['actualUsdMicro'] == 12300, audit
code, listed = tool('list', '--workspace', wid)
assert listed['unknown'] == [], listed
code, remote = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / 'scripts/reconcile_unknown_usage.py'), '--dsn', 'host=db.example.invalid dbname=postgres', 'list'], capture_output=True, text=True).returncode, None
assert code != 0, 'a non-loopback database must need --confirm-host'
print('PASS: operator reconciliation: failed run settled once from evidence (hold released, provider cost 12300 booked, not charged), second attempt 409, audit recorded, remote DSN refused')

# 5. A delivered result whose usage was unknown is charged its actual cost, within what was approved.
responses.append({'status': 503, 'body': {}})
attempt('A second request whose outcome is unknown.', 'unknown-outcome-2')
code, listed = tool('list', '--workspace', wid)
pending = listed['unknown'][0]
code, settled = tool('settle', '--workspace', wid, '--reservation', pending['reservationId'], '--outcome', 'completed', '--actual-usd', '0.02', '--operator', 'ops-oncall', '--evidence', 'synthetic gateway request 0002')
assert code == 0, settled
available, held, used = wallet()
assert (held, used - start[2]) == (0, 6000), (available, held, used)
print('PASS: operator reconciliation to completed charges the actual cost (0.02 USD -> 6.0 credits) and releases the rest of the hold')

# 6. Cancel while a paid request is in flight: no retry is sent and the known cost settles the hold.
before_calls, before = len(calls), wallet()
cancel_during_call['on'] = True
responses.append({'status': 200, 'body': {'choices': [{'message': {'content': 'not json'}}], 'usage': {'prompt_tokens': 1000, 'completion_tokens': 10}}})
responses.append({'status': 200, 'body': {'choices': [{'message': {'content': 'not json either'}}], 'usage': {'prompt_tokens': 1000, 'completion_tokens': 10}}})
error = attempt('A request cancelled mid-flight.', 'cancel-mid-flight')
assert len(calls) == before_calls + 1, (len(calls), before_calls)
assert error.status == 409 and 'Cancelled' in str(error), (error.status, str(error))
available, held, used = wallet()
assert held == 0 and used == before[2], (available, held, used)
settled = last_settle()
assert settled[0] == 'released' and settled[1] > 0, settled
responses.clear()
print('PASS: cancel mid-flight: the retry is not sent, nothing charged, the known provider cost settles the hold (no unknown left)')
