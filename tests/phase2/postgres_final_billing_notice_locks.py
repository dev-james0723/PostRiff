"""Disposable PostgreSQL: signed webhook queues atomically and returns before email I/O.

A separate notification-worker tick performs the identity lookup and simulated
email dispatch after commit. Detector overlap and signed replay cannot duplicate
that durable delivery. No external services are used.
"""
from local_pg_target import selected_target
import hashlib, hmac, json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.email import Mailer, NullTransport
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.notifications.service import NotificationService
from postriff_phase2.notifications import detector

DSN = selected_target().dsn()
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
os.environ['RAFII_NOTIFICATIONS_V2_ENABLED'] = '1'
service.notifications = NotificationService(service, email_transport=mail, clock=lambda: clock[0])
lookups.clear()
mail.locked_at_send.clear()
result = service.billing_webhook(signature, body)
assert result['outcome'] == 'applied' and result['notification']['queued'] is True, result
assert result['notification']['sent'] is False, result
assert mail.locked_at_send == [] and lookups == [], 'webhook performed network I/O'
with connection() as db:
    rows = db.execute("SELECT d.status,d.idempotency_key FROM public.pr_notification_deliveries d "
                      "JOIN public.pr_notification_events e ON e.id=d.event_id WHERE e.workspace_id=%s "
                      "AND e.event_type='billing.subscription_active' AND d.channel='email'", (wid,)).fetchall()
    assert len(rows) == 1 and rows[0][0] == 'pending', rows
    # The database detector must resolve to the same durable notification key.
    with db.cursor() as cur:
        for event in detector.from_database(cur, wid, clock[0]):
            if event['event_type'] == 'billing.subscription_active':
                assert not service.notifications.emit(cur, workspace_id=wid, **event)['created']
again = service.billing_webhook(signature, body)
assert again['outcome'] == 'duplicate' and mail.locked_at_send == [] and lookups == [], again
# A newly created worker can resume the persisted notification after the request/process ended.
worker = service.notifications.worker()
outcome = worker.tick(max_items=10, max_seconds=10)
assert mail.locked_at_send == [False], ('worker did not deliver after commit', outcome, mail.locked_at_send)
assert lookups == [False], ('worker looked up an address with rows locked', lookups)
worker.tick(max_items=10, max_seconds=10)
assert mail.locked_at_send == [False] and lookups == [False], 'worker duplicated delivery'
with connection() as db:
    sent = db.execute("SELECT status FROM public.pr_notification_deliveries d "
                      "JOIN public.pr_notification_events e ON e.id=d.event_id WHERE e.workspace_id=%s "
                      "AND e.event_type='billing.subscription_active' AND d.channel='email'", (wid,)).fetchall()
assert sent == [('sent',)], sent
print('PASS: webhook has zero identity/email I/O; atomic outbox survives request; worker sends once after commit; signed replay and detector overlap dedupe')
