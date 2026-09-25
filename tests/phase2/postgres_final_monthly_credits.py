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
import hashlib, hmac, json, sys, time, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.credit_meter import POLICY_VERSION
from postriff_phase2.hosted import HostedWorkspaceService

ROOT = Path(__file__).resolve().parents[2]
DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
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
