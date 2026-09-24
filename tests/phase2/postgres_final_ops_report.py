"""FINAL-10 on disposable PostgreSQL: the read-only operator report finds every state that needs a person
(unknown usage, payment events waiting for review, uncertain/held/stuck/overdue publishing jobs, budgets
past their stop line or not approved) and prints identifiers only. Nothing is changed by the report."""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
import importlib.util
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from consumer_fixtures import approve_budgets

# Loaded by path: putting scripts/ on sys.path would shadow the postriff_alpha package with scripts/postriff_alpha.py.
_spec = importlib.util.spec_from_file_location('ops_health_report', ROOT / 'scripts' / 'ops_health_report.py')
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
health = _module.health

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
ONE = '00000000-0000-0000-0000-000000000001'
now = time.time()


def connection():
    return psycopg.connect(DSN)


def verify(token):
    if token != 'one':
        raise AlphaError('Verified session required.', 401)
    return ONE


verify.session_id = lambda token, principal: 'ops-report-session'
verify.auth_time = lambda token, principal: now
with connection() as db:
    for file in ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql'):
        db.execute((ROOT / 'migrations/postriff' / file).read_text())
service = HostedWorkspaceService(connection, verify, clock=lambda: now)
wid = service.bootstrap('one', 'studio')['workspaceId']
approve_budgets(connection, wid)


def report():
    with connection() as db:
        db.read_only = True
        with db.cursor() as cur:
            return health(cur, now)


baseline = report()
assert baseline['unknownUsage']['count'] == 0 and baseline['paymentInbox']['needsReview'] == 0, baseline
assert all(v['count'] == 0 for v in baseline['publishing'].values()), baseline['publishing']

with connection() as db:
    cur = db.cursor()
    state = cur.execute('SELECT state FROM pr_workspaces WHERE id=%s', (wid,)).fetchone()[0]
    state['phase2']['jobs'] = [
        {'id': 'job-uncertain', 'state': 'uncertain', 'nextAt': now - 60, 'leaseUntil': 0},
        {'id': 'job-held', 'state': 'held', 'nextAt': now + 600, 'leaseUntil': 0},
        {'id': 'job-stuck', 'state': 'processing', 'nextAt': now - 600, 'leaseUntil': now - 30},
        {'id': 'job-working', 'state': 'processing', 'nextAt': now - 10, 'leaseUntil': now + 120},
        {'id': 'job-overdue', 'state': 'scheduled', 'nextAt': now - 3600, 'leaseUntil': 0},
        {'id': 'job-due-soon', 'state': 'scheduled', 'nextAt': now - 60, 'leaseUntil': 0},
        {'id': 'job-done', 'state': 'verified', 'nextAt': now - 7200, 'leaseUntil': 0},
    ]
    cur.execute('UPDATE pr_workspaces SET state=%s WHERE id=%s', (json.dumps(state), wid))
    reservation = service.ledger.reserve(cur, wid, ONE, 'text_model', 12_000, 'ops-report-unknown', charge_batch=False, provider='vercel-ai-gateway', model='anthropic/claude-sonnet-5')
    service.ledger.settle(cur, wid, reservation['reservationId'], 'unknown')
    cur.execute("INSERT INTO pr_credit_payment_inbox(event_id,kind,event_created,livemode,payload_digest,event,status,reason) VALUES('evt_ops_1','charge.refunded',%s,false,%s,'{}'::jsonb,'needs_review','order not found')", (int(now), hashlib.sha256(b'ops').hexdigest()))
    cur.execute("UPDATE pr_budgets SET spent_usd_micro=stop_usd_micro WHERE scope=%s", (f'workspace:{wid}',))
    before = cur.execute('SELECT count(*) FROM pr_usage_ledger').fetchone()[0]

found = report()
publishing = found['publishing']
assert found['unknownUsage']['count'] == 1 and found['unknownUsage']['items'][0]['reservationId'] == reservation['reservationId'], found['unknownUsage']
assert found['paymentInbox']['needsReview'] == 1, found['paymentInbox']
assert [i['jobId'] for i in publishing['uncertain']['items']] == ['job-uncertain']
assert [i['jobId'] for i in publishing['held']['items']] == ['job-held']
assert [i['jobId'] for i in publishing['expiredLease']['items']] == ['job-stuck'], publishing['expiredLease']
assert [i['jobId'] for i in publishing['overdue']['items']] == ['job-overdue'], publishing['overdue']
assert any(b['scope'] == f'workspace:{wid}' for b in found['budgets']['pastStop']), found['budgets']
assert found['needsAttention'] is True
text = json.dumps(found)
assert 'order not found' not in text and 'caption' not in text, 'identifiers and counts only'
with connection() as db:
    assert db.execute('SELECT count(*) FROM pr_usage_ledger').fetchone()[0] == before, 'the report writes nothing'
print('PASS: the operator report lists unknown usage, payment events awaiting review, uncertain/held/stuck/overdue jobs and budgets past their stop line, with identifiers only and no writes')
