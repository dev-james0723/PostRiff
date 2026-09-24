"""FINAL-06 on disposable PostgreSQL: one-time top-up lifecycle beyond the happy path. Synthetic, signed
events only; no network and no Stripe account.

- Orders end as expired or failed without payment; a repeat never hands back a paid or ended session.
- Money wins: a verified payment for an order already marked expired still funds it once.
- A verified event that cannot be applied (unknown order, mismatched amount, unknown refund status,
  same-second contradictory refunds) is kept in a durable inbox as needs_review and acknowledged,
  instead of failing until the provider stops retrying; nothing is granted or reversed by it.
- Disputes: withdrawn funds reverse the order's credits; won/reinstated restores them; lost stays reversed.
- Debt left by a refund after the credits were spent is repaid by the next grant, and spending resumes.
"""
import hashlib, hmac, json, subprocess, sys, time, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.credit_meter import POLICY_VERSION
from consumer_fixtures import approve_budgets

ROOT = Path(__file__).resolve().parents[2]
DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
NOW = int(time.time()); ACTOR = str(uuid.uuid4()); SECRET = 'synthetic-webhook-only'


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


def verify(token):
    if token != 'fixture':
        raise AlphaError('Denied', 403)
    return ACTOR


verify.session_id = lambda token, principal: 'lifecycle-session'
verify.auth_time = lambda token, principal: NOW
sessions = []


def transport(method, url, headers=None, form=None):
    sessions.append(form)
    sid = 'cs_' + form['metadata[credit_order_id]']
    return {'status': 200, 'body': {'id': sid, 'url': 'https://checkout.stripe.com/c/pay/' + sid}}


provider = StripePaymentProvider('sk_test_fixture', SECRET, transport=transport, clock=lambda: NOW)
with connection() as db:
    db.execute('INSERT INTO auth.users(id) VALUES(%s)', (ACTOR,))
    for file in ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql'):
        db.execute((ROOT / 'migrations/postriff' / file).read_text())
service = HostedWorkspaceService(connection, verify, clock=lambda: NOW, billing_provider=provider, credits_enabled=True, public_base_url='https://example.invalid', email_lookup=lambda actor: 'synthetic@example.invalid')
service.credit_purchases_enabled = True
wid = service.bootstrap('fixture', 'studio')['workspaceId']
with connection() as db:
    cur = db.cursor(); service.ledger.ensure_entitlement(cur, wid, None)
    ent = {'writingBatches': 10, 'mediaCredits': 1, 'members': 2, 'connectedAccounts': 3, 'storageMb': 200, 'creditPolicy': POLICY_VERSION}
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('lifecycle-terms','studio',994,'Synthetic',0,'active',%s::jsonb)", (json.dumps(ent),))
    db.execute("UPDATE pr_entitlements SET plan_terms_id='lifecycle-terms' WHERE workspace_id=%s", (wid,))
    db.execute("INSERT INTO pr_credit_packs VALUES('test-pack','Synthetic credits',%s,'price_fixture',1000,'usd',100000,false,true)", (POLICY_VERSION,))
counter = [0]


def checkout(request_id):
    # The real limit (5 checkouts a minute per workspace) stays on; this disposable test clears its bucket.
    with connection() as db:
        db.execute('DELETE FROM public.pr_auth_throttle')
    return service.billing_credit_checkout(wid, 'fixture', 'test-pack', request_id)




def event(kind, obj, created=NOW):
    counter[0] += 1
    raw = json.dumps({'id': f'evt_{kind}_{counter[0]}', 'type': kind, 'created': created, 'livemode': False, 'data': {'object': obj}}).encode()
    signature = hmac.new(SECRET.encode(), f'{NOW}.'.encode() + raw, hashlib.sha256).hexdigest()
    return f't={NOW},v1={signature}', raw


def wallet():
    with connection() as db:
        view = service.ledger.credits.view(db.cursor(), wid)
    return view['availableMilliCredits'], view['debtMilliCredits']


def order_status(order_id):
    with connection() as db:
        return db.execute('SELECT status FROM public.pr_credit_orders WHERE id::text=%s', (order_id,)).fetchone()[0]


def session(order, pi, **extra):
    return {'id': order['sessionId'], 'mode': 'payment', 'payment_status': 'paid', 'payment_intent': pi, 'amount_total': 1000, 'currency': 'usd', 'client_reference_id': wid, 'metadata': {'credit_order_id': order['orderId']}, **extra}


def refused(call, status, text=''):
    try:
        call()
    except AlphaError as error:
        assert error.status == status and text in str(error), (error.status, str(error))
        return
    raise AssertionError('accepted what must be refused')


checks = []
# 1. Expired and failed orders; a repeat never returns an ended session.
expiring = checkout('lifecycle-request-0001')
assert sessions[-1].get('expires_at') and int(sessions[-1]['expires_at']) - NOW == 3600, sessions[-1]
assert service.billing_webhook(*event('checkout.session.expired', {**session(expiring, None), 'payment_status': 'unpaid', 'status': 'expired'}))['outcome'] == 'applied'
assert order_status(expiring['orderId']) == 'expired'
refused(lambda: checkout('lifecycle-request-0001'), 409, 'ended without payment')
failing = checkout('lifecycle-request-0002')
service.billing_webhook(*event('checkout.session.async_payment_failed', {**session(failing, 'pi_failed'), 'payment_status': 'unpaid'}))
assert order_status(failing['orderId']) == 'failed'
refused(lambda: checkout('lifecycle-request-0002'), 409, 'ended without payment')
assert wallet() == (0, 0)
checks.append('expired and failed orders end without credits; the same request never gets an ended session back; sessions expire after 1 hour')

# 2. Paid: one grant; the repeat request gets no checkout URL. Money wins over an earlier expiry.
paid = checkout('lifecycle-request-0003')
service.billing_webhook(*event('checkout.session.completed', session(paid, 'pi_paid')))
repeat = checkout('lifecycle-request-0003')
assert repeat['status'] == 'funded' and repeat['url'] is None, repeat
late = checkout('lifecycle-request-0004')
service.billing_webhook(*event('checkout.session.expired', {**session(late, None), 'payment_status': 'unpaid', 'status': 'expired'}))
service.billing_webhook(*event('checkout.session.async_payment_succeeded', session(late, 'pi_late')))
assert order_status(late['orderId']) == 'funded' and wallet() == (200000, 0), (order_status(late['orderId']), wallet())
checks.append('a paid order returns no URL on repeat; a verified payment funds an order even after an expiry notice (once)')

# 3. Events that cannot be applied are kept for review and acknowledged, never granted.
before = wallet()
for label, obj, kind in (
    ('unknown order', {**session(paid, 'pi_ghost'), 'id': 'cs_ghost', 'metadata': {'credit_order_id': str(uuid.uuid4())}}, 'checkout.session.completed'),
    ('amount mismatch', {**session(paid, 'pi_paid'), 'amount_total': 1}, 'checkout.session.completed'),
    ('other workspace', {**session(paid, 'pi_paid'), 'client_reference_id': str(uuid.uuid4())}, 'checkout.session.completed'),
    ('unknown refund status', {'id': 're_odd', 'payment_intent': 'pi_paid', 'amount': 100, 'currency': 'usd', 'status': 'mystery'}, 'refund.updated'),
):
    signature, raw = event(kind, obj)
    result = service.billing_webhook(signature, raw)
    assert result['outcome'] == 'needs_review', (label, result)
    assert service.billing_webhook(signature, raw)['outcome'] == 'duplicate', label
assert wallet() == before, (wallet(), before)
with connection() as db:
    inbox = db.execute("SELECT kind, status, reason FROM public.pr_credit_payment_inbox WHERE status='needs_review' ORDER BY received_at").fetchall()
assert len(inbox) == 4 and all(row[2] for row in inbox), inbox
checks.append('unknown order, mismatched amount, another workspace and an unknown refund status are kept as needs_review (acknowledged, replay-safe), nothing granted')

# 4. Same-second contradictory refund statuses are held for review instead of looping on retries.
service.billing_webhook(*event('refund.created', {'id': 're_tie', 'payment_intent': 'pi_paid', 'amount': 500, 'currency': 'usd', 'status': 'succeeded'}, NOW + 10))
assert wallet()[0] == before[0] - 50000, wallet()
result = service.billing_webhook(*event('refund.updated', {'id': 're_tie', 'payment_intent': 'pi_paid', 'amount': 500, 'currency': 'usd', 'status': 'failed'}, NOW + 10))
assert result['outcome'] == 'needs_review', result
assert wallet()[0] == before[0] - 50000, wallet()
checks.append('same-second succeeded/failed refund statuses: the later one is kept for review, credits unchanged by it')

# 5. Disputes.
disputed = checkout('lifecycle-request-0005')
service.billing_webhook(*event('checkout.session.completed', session(disputed, 'pi_dispute')))
funded = wallet()[0]
dispute = {'id': 'dp_one', 'object': 'dispute', 'payment_intent': 'pi_dispute', 'charge': 'ch_dispute', 'amount': 1000, 'currency': 'usd', 'status': 'needs_response', 'reason': 'fraudulent'}
service.billing_webhook(*event('charge.dispute.created', dispute, NOW + 20))
assert wallet()[0] == funded - 100000, (wallet(), funded)
service.billing_webhook(*event('charge.dispute.closed', {**dispute, 'status': 'won'}, NOW + 30))
assert wallet()[0] == funded, (wallet(), funded)
lost = checkout('lifecycle-request-0006')
service.billing_webhook(*event('checkout.session.completed', session(lost, 'pi_lost')))
funded = wallet()[0]
lost_dispute = {**dispute, 'id': 'dp_two', 'payment_intent': 'pi_lost', 'charge': 'ch_lost'}
service.billing_webhook(*event('charge.dispute.created', {**lost_dispute, 'status': 'warning_needs_response'}, NOW + 20))
assert wallet()[0] == funded, 'an inquiry that withdrew no funds reverses nothing'
service.billing_webhook(*event('charge.dispute.funds_withdrawn', {**lost_dispute, 'status': 'needs_response'}, NOW + 21))
service.billing_webhook(*event('charge.dispute.closed', {**lost_dispute, 'status': 'lost'}, NOW + 40))
assert wallet()[0] == funded - 100000, (wallet(), funded)
checks.append('disputes: withdrawn funds reverse the credits, a won dispute restores them, an inquiry reverses nothing, a lost one stays reversed')

# 6. Debt after a refund of spent credits is repaid by the next grant; spending then resumes.
spent_order = checkout('lifecycle-request-0007')
service.billing_webhook(*event('checkout.session.completed', session(spent_order, 'pi_spent')))
with connection() as db:
    cur = db.cursor()
    total = service.ledger.credits.view(cur, wid)['availableMilliCredits']
    q = service.ledger.credits.issue(cur, wid, ACTOR, 0, 'd' * 64, 'fixture-model', 'fixture-provider', total)
    authority = service.ledger.credits.authorize(cur, wid, ACTOR, 0, 'd' * 64, q['quoteId'])
approve_budgets(connection, wid)
with connection() as db:
    cur = db.cursor()
    r = service.ledger.reserve(cur, wid, ACTOR, 'text_model', 1, 'spend-all', charge_batch=True, provider='fixture-provider', model='fixture-model', credit_authority=authority)
with connection() as db:
    service.ledger.settle(db.cursor(), wid, r['reservationId'], 'completed', total * 1_000_000 // 300_000)
assert wallet() == (0, 0), wallet()
service.billing_webhook(*event('refund.created', {'id': 're_spent', 'payment_intent': 'pi_spent', 'amount': 1000, 'currency': 'usd', 'status': 'succeeded'}, NOW + 50))
available, debt = wallet()
assert (available, debt) == (0, 100000), (available, debt)
repay = checkout('lifecycle-request-0008')
service.billing_webhook(*event('checkout.session.completed', session(repay, 'pi_repay')))
assert wallet() == (0, 0), wallet()
second = checkout('lifecycle-request-0009')
service.billing_webhook(*event('checkout.session.completed', session(second, 'pi_second')))
assert wallet() == (100000, 0), wallet()
with connection() as db:
    cur = db.cursor()
    q = service.ledger.credits.issue(cur, wid, ACTOR, 0, 'e' * 64, 'fixture-model', 'fixture-provider', 100000)
    authority = service.ledger.credits.authorize(cur, wid, ACTOR, 0, 'e' * 64, q['quoteId'])
    assert service.ledger.credits.prepare(cur, wid, ACTOR, 1, 'fixture-model', 'fixture-provider', authority)['maximum'] == 100000
checks.append('a refund after spending leaves 100.0 credits of debt; the next 100.0 top-up repays it; spending resumes on the following one')

# 7. The operator can list and resolve review items; nothing is applied by resolving.
tool = [sys.executable, str(ROOT / 'scripts/credit_payment_inbox.py'), '--dsn', DSN]
listed = json.loads(subprocess.run([*tool, 'list'], capture_output=True, text=True, check=True).stdout)
assert len(listed['needsReview']) == 5, listed
first = listed['needsReview'][0]['eventId']
resolved = subprocess.run([*tool, 'resolve', '--event', first, '--operator', 'ops-oncall', '--note', 'checked in the Stripe dashboard: not ours'], capture_output=True, text=True)
assert resolved.returncode == 0, resolved.stderr
listed = json.loads(subprocess.run([*tool, 'list'], capture_output=True, text=True, check=True).stdout)
assert len(listed['needsReview']) == 4 and wallet() == (100000, 0)
checks.append('operator lists 5 review items and resolves one with a note; balances unchanged by resolving')

for line in checks:
    print('PASS:', line)
