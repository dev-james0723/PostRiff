"""FINAL-06/10 on disposable PostgreSQL: the owner's billing email is sent after the webhook commits.

The mail transport probes, at send time, whether the workspace's subscription row is still locked by the
webhook transaction (SELECT ... FOR UPDATE NOWAIT from another connection). The address lookup and the
send are network calls; neither may run while billing rows are locked. Nothing is sent anywhere.
"""
import hashlib, hmac, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.email import Mailer, NullTransport
from postriff_phase2.hosted import HostedWorkspaceService

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
ONE = '00000000-0000-0000-0000-000000000001'
clock = [time.time()]


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


def verify(token):
    if token != 'one':
        raise AlphaError('Verified session required.', 401)
    return ONE


verify.session_id = lambda token, principal: 'notice-locks-session'
verify.auth_time = lambda token, principal: clock[0]
lookups = []
wid = None


class Identity:
    def email_for(self, user_id):
        lookups.append(row_locked())
        return 'owner@example.com'


def row_locked():
    if wid is None:
        return None  # the welcome email during bootstrap, before this workspace exists
    # Both rows exist before the webhook (the trial subscription is created on first usage read).
    with connection() as probe:
        try:
            rows = probe.execute('SELECT (SELECT count(*) FROM (SELECT 1 FROM public.pr_workspaces WHERE id=%s FOR UPDATE NOWAIT) w) + (SELECT count(*) FROM (SELECT 1 FROM public.pr_subscriptions WHERE workspace_id=%s FOR UPDATE NOWAIT) s)', (wid, wid)).fetchone()[0]
            assert rows == 2, rows
            return False
        except psycopg.errors.LockNotAvailable:
            return True


class ProbingTransport(NullTransport):
    def __init__(self):
        super().__init__()
        self.locked_at_send = []

    def send(self, message):
        self.locked_at_send.append(row_locked())
        super().send(message)
        return {'id': f'fixture-accepted-{len(self.sent)}'}


provider = StripePaymentProvider('sk_test_x', 'whsec_test', transport=lambda *a, **k: {'status': 404, 'headers': {}, 'body': {}}, clock=lambda: clock[0])
mail = ProbingTransport()
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], identity=Identity(), public_base_url='https://app.postriff.test/', billing_provider=provider, mailer=Mailer(mail, 'PostRiff <hello@postriff.test>', 'https://app.postriff.test'))
wid = service.bootstrap('one', 'studio')['workspaceId']
with connection() as db:
    db.execute("UPDATE public.pr_plan_terms SET status='active', provider_price_id='price_studio' WHERE id='studio-v1'")
service.usage(wid, 'one')  # creates the trial subscription row the probe locks
body = json.dumps({'id': 'evt_notice_1', 'type': 'checkout.session.completed', 'created': int(clock[0]), 'livemode': False, 'data': {'object': {'mode': 'subscription', 'client_reference_id': wid, 'customer': 'cus_1', 'subscription': 'sub_1', 'metadata': {'workspace_id': wid, 'plan_terms_id': 'studio-v1'}}}}).encode()
signature = 't=%d,v1=%s' % (int(clock[0]), hmac.new(b'whsec_test', f'{int(clock[0])}.'.encode() + body, hashlib.sha256).hexdigest())
lookups.clear()
mail.locked_at_send.clear()
result = service.billing_webhook(signature, body)
assert result['outcome'] == 'applied' and result['notification']['sent'] is True, result
assert mail.locked_at_send == [False], ('email sent while billing rows were locked', mail.locked_at_send)
assert lookups == [False], ('address looked up while billing rows were locked', lookups)
with connection() as db:
    sent = db.execute("SELECT sent FROM public.pr_notifications WHERE workspace_id=%s AND kind='subscription_activated'", (wid,)).fetchall()
assert sent == [(True,)], sent
again = service.billing_webhook(signature, body)
assert again['outcome'] == 'duplicate' and len(mail.locked_at_send) == 1, again
print('PASS: owner billing email: address lookup and send happen after commit (no row lock held), recorded once as sent, replay sends nothing')
