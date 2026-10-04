"""FINAL-07 on disposable PostgreSQL: monthly plan credits come only from a verified paid invoice.

Candidate policy under test (not approved commercial terms; synthetic plan and prices only):
- `invoice.paid` with billing_reason subscription_create or subscription_cycle grants the plan's
  monthlyCredits once per invoice id, expiring at that period's end (no rollover).
- Checkout completion, subscription updates, failed payments and proration invoices grant nothing.
- Replays, a second event for the same invoice and out-of-order delivery never grant twice; a late
  verified payment still grants (money wins).
- Top-up lots are never reset or expired by the monthly cycle; monthly credits are spent first.
- A refund of a plan payment takes back that period's credits proportionally.
- A legacy plan (no credit policy) keeps its writing batches and receives no credits.
"""
from local_pg_target import selected_target
import hashlib, hmac, json, sys, time, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.credit_meter import POLICY_VERSION
from postriff_phase2.hosted import HostedWorkspaceService

ROOT = Path(__file__).resolve().parents[2]
DSN = selected_target().dsn()
T0 = int(time.time())
clock = [float(T0)]
USERS = {'one': str(uuid.uuid4()), 'two': str(uuid.uuid4())}
DAY = 86400


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


def verify(token):
    if token not in USERS:
        raise AlphaError('Denied', 403)
    return USERS[token]


verify.session_id = lambda token, principal: 'monthly-session-' + token
verify.auth_time = lambda token, principal: clock[0]
with connection() as db:
    for user in USERS.values():
        db.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))
    for file in ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql'):
        db.execute((ROOT / 'migrations/postriff' / file).read_text())
    base = {'writingBatches': 10, 'mediaCredits': 1, 'members': 2, 'connectedAccounts': 3, 'storageMb': 200}
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements,provider_price_id) VALUES('creator-credits','studio',990,'Synthetic Creator',4900,'active',%s::jsonb,'price_creator')", (json.dumps({**base, 'creditPolicy': POLICY_VERSION, 'monthlyCredits': 3500}),))
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements,provider_price_id) VALUES('legacy-batches','studio',991,'Synthetic legacy',1900,'active',%s::jsonb,'price_legacy')", (json.dumps(base),))
SECRET = 'whsec_monthly'
provider = StripePaymentProvider('sk_test_monthly', SECRET, transport=lambda *a, **k: {'status': 404, 'headers': {}, 'body': {}}, clock=lambda: clock[0])
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], billing_provider=provider, credits_enabled=True)
wid = service.bootstrap('one', 'studio')['workspaceId']
legacy = service.bootstrap('two', 'studio')['workspaceId']
counter = [0]


def deliver(kind, obj, created=None, event_id=None):
    counter[0] += 1
    body = json.dumps({'id': event_id or f'evt_monthly_{counter[0]}', 'type': kind, 'created': int(created or clock[0]), 'livemode': False, 'data': {'object': obj}}).encode()
    stamp = int(clock[0])
    signature = f"t={stamp},v1={hmac.new(SECRET.encode(), f'{stamp}.'.encode() + body, hashlib.sha256).hexdigest()}"
    return service.billing_webhook(signature, body)


def invoice(invoice_id, workspace, terms, reason, start, end, pi, amount=4900):
    return {'id': invoice_id, 'object': 'invoice', 'billing_reason': reason, 'status': 'paid', 'customer': 'cus_' + workspace[:6], 'subscription': 'sub_' + workspace[:6],
            'amount_paid': amount, 'currency': 'usd', 'payment_intent': pi,
            'lines': {'data': [{'period': {'start': start, 'end': end}, 'price': {'id': 'price_x'}}, {'period': {'start': start, 'end': end}, 'price': {'id': 'price_addon'}}]},
            'parent': {'type': 'subscription_details', 'subscription_details': {'subscription': 'sub_' + workspace[:6], 'metadata': {'workspace_id': workspace, 'plan_terms_id': terms}}}}


def wallet(workspace=None):
    with connection() as db:
        view = service.ledger.credits.view(db.cursor(), workspace or wid)
    return view['availableMilliCredits'] // 1000


checks = []
P1, P2, P3 = (T0, T0 + 30 * DAY), (T0 + 30 * DAY, T0 + 60 * DAY), (T0 + 60 * DAY, T0 + 90 * DAY)
deliver('checkout.session.completed', {'mode': 'subscription', 'client_reference_id': wid, 'customer': 'cus_x', 'subscription': 'sub_x', 'metadata': {'workspace_id': wid, 'plan_terms_id': 'creator-credits'}})
assert wallet() == 0, wallet()
checks.append('checkout completion activates the plan but grants no credits before a paid invoice')

first = invoice('in_1', wid, 'creator-credits', 'subscription_create', *P1, 'pi_inv1')
deliver('invoice.paid', first, event_id='evt_inv1')
assert wallet() == 3500, wallet()
deliver('invoice.paid', first, event_id='evt_inv1')
deliver('invoice.paid', first, event_id='evt_inv1_second_delivery')
assert wallet() == 3500, wallet()
checks.append('first paid invoice grants 3,500 credits once (replay and a second event for the same invoice grant nothing)')

deliver('invoice.paid', invoice('in_proration', wid, 'creator-credits', 'subscription_update', P1[0] + 10 * DAY, P1[1], 'pi_proration', 1200))
assert wallet() == 3500, wallet()
deliver('invoice.payment_failed', {**invoice('in_2', wid, 'creator-credits', 'subscription_cycle', *P2, 'pi_inv2'), 'status': 'open', 'amount_paid': 0})
assert wallet() == 3500, wallet()
checks.append('a proration invoice and a failed payment grant nothing')

with connection() as db:
    service.ledger.credits.grant(db.cursor(), wid, USERS['one'], 'topup-fixture', 1_000_000, None, source='local-test-only')
clock[0] = P2[0] + 60
deliver('invoice.paid', invoice('in_2', wid, 'creator-credits', 'subscription_cycle', *P2, 'pi_inv2'), event_id='evt_inv2')
assert wallet() == 3500 + 1000, wallet()
checks.append('after the first period ends its credits expire; the renewal grants 3,500 and the 1,000 top-up is untouched')

clock[0] = P3[0] + 60
deliver('customer.subscription.updated', {'id': 'sub_x', 'status': 'active', 'customer': 'cus_x', 'metadata': {'workspace_id': wid, 'plan_terms_id': 'creator-credits'}, 'items': {'data': [{'price': {'id': 'price_creator'}, 'current_period_end': P3[1]}]}}, created=P3[0] + 300)
late = deliver('invoice.paid', invoice('in_3', wid, 'creator-credits', 'subscription_cycle', *P3, 'pi_inv3'), created=P3[0] + 120, event_id='evt_inv3_late')
assert late['outcome'] == 'stale', late
assert wallet() == 3500 + 1000, (wallet(), late)
checks.append('an invoice.paid delivered after a newer subscription event leaves the status alone (stale) but still grants its period (money wins)')

deliver('refund.created', {'id': 're_inv3', 'payment_intent': 'pi_inv3', 'amount': 2450, 'currency': 'usd', 'status': 'succeeded'}, created=P3[0] + 400)
assert wallet() == 3500 - 1750 + 1000, wallet()
checks.append("a 50% refund of a plan payment takes back 1,750 of that period's credits")

deliver('checkout.session.completed', {'mode': 'subscription', 'client_reference_id': legacy, 'customer': 'cus_l', 'subscription': 'sub_l', 'metadata': {'workspace_id': legacy, 'plan_terms_id': 'legacy-batches'}})
deliver('invoice.paid', invoice('in_legacy', legacy, 'legacy-batches', 'subscription_create', *P3, 'pi_legacy', 1900))
with connection() as db:
    cur = db.cursor()
    batches = service.ledger.ensure_entitlement(cur, legacy, None)['writingBatchesRemaining']
    grants = db.execute("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s AND meta->'credits'->>'op'='grant'", (legacy,)).fetchone()[0]
assert batches == 10 and grants == 0, (batches, grants)
checks.append('a legacy plan keeps its 10 writing batches and gets no credits')

with connection() as db:
    rows = db.execute("SELECT invoice_id, grant_id IS NOT NULL, note FROM public.pr_credit_subscription_grants WHERE workspace_id=%s ORDER BY invoice_id", (wid,)).fetchall()
assert [r[0] for r in rows] == ['in_1', 'in_2', 'in_3', 'in_proration'] and [r[1] for r in rows] == [True, True, True, False] and rows[3][2], rows
checks.append('every plan invoice is recorded with its grant; the proration invoice is recorded with no grant and a note')

for line in checks:
    print('PASS:', line)

# Task2 v2 policy: signed synthetic invoices through the unchanged payment provider.
USERS['v2'] = str(uuid.uuid4())
with connection() as db:
    db.execute('INSERT INTO auth.users(id) VALUES(%s)', (USERS['v2'],))
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements,provider_price_id) VALUES('task2-monthly-v2','studio',992,'Synthetic v2 monthly',4900,'active',%s::jsonb,'price_task2_v2')", (json.dumps({**base, 'creditPolicy': 'credits-v2-2026-09-28', 'monthlyCredits': 3500}),))
v2wid = service.bootstrap('v2', 'studio')['workspaceId']
v2start, v2end = int(clock[0]), int(clock[0]) + 30 * DAY
v2first = invoice('in_v2_first', v2wid, 'task2-monthly-v2', 'subscription_create', v2start, v2end, 'pi_v2_first')
deliver('invoice.paid', v2first, event_id='evt_v2_first')
assert wallet(v2wid) == 3500, 'A verified v2 invoice must grant its monthly credits'
with connection() as db:
    grant_id = db.execute("SELECT grant_id FROM pr_credit_subscription_grants WHERE invoice_id='in_v2_first'").fetchone()[0]
    credit = db.execute("SELECT meta->'credits' FROM pr_usage_ledger WHERE id=%s", (grant_id,)).fetchone()[0]
    assert credit['policy'] == 'credits-v2-2026-09-28' and credit['expiresAt'] == v2end, credit
    assert service.ledger.credits.view(db.cursor(), v2wid).get('currentPeriodGrantMilliCredits') == 3_500_000
    assert service.ledger.credits.view(db.cursor(), v2wid).get('currentPeriodExpiresAt') == v2end
print('PASS: v2 paid invoice grants exactly 3,500 credits with the explicit v2 id and paid period expiry')
deliver('invoice.paid', v2first, event_id='evt_v2_first_replay')
assert wallet(v2wid) == 3500
print('PASS: v2 invoice replay never grants twice')

# Incomplete v2 period evidence must not create a perpetual monthly grant.
for name, period in (('no_start', {'end': v2end}), ('no_end', {'start': v2start}), ('invalid_period', {'start': v2end, 'end': v2start})):
    incomplete = invoice('in_v2_' + name, v2wid, 'task2-monthly-v2', 'subscription_cycle', v2start, v2end, 'pi_v2_' + name)
    incomplete['lines']['data'][0]['period'] = period
    deliver('invoice.paid', incomplete)
    assert wallet(v2wid) == 3500, (name, wallet(v2wid))
print('PASS: incomplete or reversed v2 invoice periods cannot create spendable monthly credits')
clock[0] = v2end
with connection() as db:
    view = service.ledger.credits.view(db.cursor(), v2wid)
assert view['availableMilliCredits'] == 0 and view['currentPeriodGrantMilliCredits'] is None and view['currentPeriodExpiresAt'] is None, view
print('PASS: v2 monthly credits and evidence expire at the actual paid period end')


# Task2 review fix: delayed verified invoices retain the source terms' policy.
import unittest
from concurrent.futures import ThreadPoolExecutor


class DelayedInvoicePolicyTests(unittest.TestCase):
    def assert_transition(self, source_terms, current_terms, source_policy, current_policy):
        token = 'transition-' + source_policy
        USERS[token] = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (USERS[token],))
        workspace = service.bootstrap(token, 'studio')['workspaceId']
        stamp = int(clock[0])
        start, end = stamp, stamp + 30 * DAY
        initial_id = 'in_initial_' + workspace
        late_id = 'in_delayed_' + workspace
        deliver('invoice.paid', invoice(initial_id, workspace, source_terms, 'subscription_create', start, end, 'pi_initial_' + workspace), created=stamp + 100)
        with connection() as db:
            original = db.execute("SELECT id::text,meta FROM pr_usage_ledger WHERE workspace_id=%s AND meta->'credits'->>'op'='grant'", (workspace,)).fetchall()
        self.assertEqual(len(original), 1)
        self.assertEqual(original[0][1]['credits']['policy'], source_policy)
        deliver('customer.subscription.updated', {'id': 'sub_' + workspace[:6], 'status': 'active', 'customer': 'cus_' + workspace[:6],
                'metadata': {'workspace_id': workspace, 'plan_terms_id': current_terms}, 'current_period_end': end}, created=stamp + 600)
        delayed = invoice(late_id, workspace, source_terms, 'subscription_cycle', start, end, 'pi_delayed_' + workspace)
        late_event = 'evt_delayed_' + workspace
        result = deliver('invoice.paid', delayed, created=stamp + 300, event_id=late_event)
        self.assertEqual(result['outcome'], 'stale')
        self.assertEqual(deliver('invoice.paid', delayed, created=stamp + 300, event_id=late_event)['outcome'], 'duplicate')
        # Distinct deliveries for the same invoice remain serialized/idempotent.
        with ThreadPoolExecutor(max_workers=2) as pool:
            repeated = list(pool.map(lambda i: deliver('invoice.paid', delayed, created=stamp + 300, event_id=late_event + '_again_' + str(i)), range(2)))
        self.assertTrue(all(r['outcome'] == 'stale' for r in repeated))
        with connection() as db:
            current = db.execute("SELECT e.plan_terms_id,p.entitlements->>'creditPolicy' FROM pr_entitlements e JOIN pr_plan_terms p ON p.id=e.plan_terms_id WHERE e.workspace_id=%s", (workspace,)).fetchone()
            grants = db.execute("SELECT id::text,meta FROM pr_usage_ledger WHERE workspace_id=%s AND meta->'credits'->>'op'='grant'", (workspace,)).fetchall()
            linked = db.execute("SELECT u.meta->'credits',g.period_end FROM pr_credit_subscription_grants g JOIN pr_usage_ledger u ON u.id=g.grant_id WHERE g.invoice_id=%s", (late_id,)).fetchone()
        self.assertEqual(current, (current_terms, current_policy))
        self.assertEqual(len(grants), 2)
        self.assertIn(original[0], grants, 'Existing policy history must remain byte-for-byte equivalent')
        self.assertEqual(linked[0]['expiresAt'], end)
        self.assertEqual(linked[1], end)
        self.assertEqual(linked[0]['source'], 'verified-stripe-invoice')
        self.assertEqual(linked[0]['policy'], source_policy, 'Use trusted invoice terms, not current entitlement')
        self.assertEqual(wallet(workspace), 7000)

    def test_delayed_candidate_invoice_after_newer_v2_subscription(self):
        self.assert_transition('creator-credits', 'task2-monthly-v2', 'credits-candidate-2026-09-23-v1', 'credits-v2-2026-09-28')

    def test_delayed_v2_invoice_after_newer_candidate_subscription(self):
        self.assert_transition('task2-monthly-v2', 'creator-credits', 'credits-v2-2026-09-28', 'credits-candidate-2026-09-23-v1')


if __name__ == '__main__':
    unittest.main(verbosity=2)
