"""Encrypted, original-source outbox for the remaining direct account mail.

Invitation, welcome and trial-ended mail have no v2 equivalent. Every other
direct kind stays with v2. Queueing never sends, and uncertainty never retries.
"""
import hashlib
import json
import time
import uuid
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError
from . import cutover, founder_email

VERSION = 'legacy-account-v1'
KINDS = ('invitation', 'welcome', 'trial_ended')


def source(cur, kind, address, ctx, now):
    """Re-read the original live source; no arbitrary recipient or event time."""
    cur.execute('SELECT p.user_id::text,p.deleted_at FROM auth.users u LEFT JOIN public.pr_profiles p ON p.user_id=u.id '
                'WHERE lower(u.email)=%s', (address,))
    found = cur.fetchone()
    if found and found[1] is not None:
        raise AlphaError('The recipient account is deleted.', 409)
    user = found[0] if found else None
    if kind == 'invitation':
        token = urlsplit(ctx.get('accept_url', '')).path.rsplit('/', 1)[-1]
        cur.execute('SELECT i.id::text,i.workspace_id::text,extract(epoch from i.created_at),extract(epoch from i.expires_at) '
                    'FROM public.pr_invitations i JOIN public.pr_workspaces w ON w.id=i.workspace_id '
                    'JOIN public.pr_memberships m ON m.workspace_id=i.workspace_id AND m.user_id=i.created_by '
                    'JOIN public.pr_profiles p ON p.user_id=i.created_by '
                    "WHERE i.token_hash=%s AND lower(i.email)=%s AND i.accepted_at IS NULL AND i.revoked_at IS NULL "
                    "AND i.expires_at>to_timestamp(%s) AND m.status='active' AND p.deleted_at IS NULL "
                    "AND NOT w.state ? 'accountDeletion' AND NOT w.state ? 'accountBlock'", (hashlib.sha256(token.encode()).hexdigest(), address, now))
        row = cur.fetchone()
    elif kind == 'welcome' and user:
        cur.execute('SELECT w.id::text,w.id::text,extract(epoch from w.created_at),extract(epoch from w.created_at)+604800 '
                    'FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id '
                    "WHERE m.user_id=%s AND m.role='owner' AND m.status='active' AND NOT w.state ? 'accountDeletion' "
                    "AND NOT w.state ? 'accountBlock' ORDER BY w.created_at,w.id LIMIT 1", (user,))
        row = cur.fetchone()
    elif kind == 'trial_ended' and user:
        cur.execute('SELECT t.workspace_id::text,t.workspace_id::text,extract(epoch from t.expires_at),'
                    'extract(epoch from t.expires_at)+86400 FROM public.pr_trials t '
                    "JOIN public.pr_memberships m ON m.workspace_id=t.workspace_id AND m.user_id=%s AND m.role='owner' AND m.status='active' "
                    'JOIN public.pr_workspaces w ON w.id=t.workspace_id LEFT JOIN public.pr_subscriptions s ON s.workspace_id=t.workspace_id '
                    "WHERE t.expires_at<=to_timestamp(%s) AND t.expires_at>to_timestamp(%s) "
                    "AND (s.status IS NULL OR s.status='trial') AND NOT w.state ? 'accountDeletion' AND NOT w.state ? 'accountBlock' "
                    "ORDER BY t.expires_at DESC LIMIT 2", (user, now, now-86400))
        rows = cur.fetchall()
        row = rows[0] if len(rows) == 1 else None  # never guess which workspace an old direct caller meant
    else:
        row = None
    if not row or float(row[3]) <= now:
        raise AlphaError('The original mail event is no longer eligible.', 409)
    return {'id': str(row[0]) + ':' + str(float(row[2])), 'workspaceId': row[1], 'userId': user,
            'occurredAt': float(row[2]), 'expiresAt': float(row[3])}


class LegacyMailOutbox:
    def __init__(self, factory, mailer, vault, values, ledger, clock=time.time):
        self.connection_factory, self.mailer, self.vault = factory, mailer, vault
        self.values, self.founder_ledger, self.clock = dict(values), ledger, clock
        self.environment = values.get('POSTRIFF_ENVIRONMENT')
        raw = values.get('RAFII_FOUNDER_EMAIL_COST_CEILING_USD_MICRO', '')
        self.email_cost_ceiling = int(raw) if str(raw).isdigit() else None
        self.email_cost_qualification = values.get('RAFII_FOUNDER_EMAIL_COST_QUALIFICATION_REF')

    def enqueue(self, kind, to, ctx):
        if kind not in KINDS:
            return {'sent': False, 'kind': kind, 'reason': 'requires_notifications_v2'}
        now, address = self.clock(), str(to or '').strip().lower()
        try:
            with self.connection_factory() as db, db.cursor() as cur:
                original = source(cur, kind, address, ctx, now)
                content = {'kind': kind, 'to': address, 'context': ctx, 'source': original}
                canonical = json.dumps(content, sort_keys=True, separators=(',', ':'))
                semantic = {'kind': kind, 'sourceId': original['id'], 'workspaceId': original['workspaceId'], 'recipient': address}
                digest = hashlib.sha256(json.dumps(semantic, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                ciphertext, key_id = self.vault.encrypt(canonical)
                identifier = str(uuid.uuid4())
                cur.execute('INSERT INTO public.pr_transactional_mail(id,workspace_id,user_id,kind,semantic_key,recipient_hash,payload_cipher,key_id,occurred_at,expires_at) '
                            'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s)) ON CONFLICT(semantic_key) DO NOTHING',
                            (identifier, original['workspaceId'], original['userId'], kind, digest, hashlib.sha256(address.encode()).hexdigest(),
                             ciphertext, key_id, original['occurredAt'], original['expiresAt']))
                db.commit()
            return {'sent': False, 'queued': True, 'kind': kind, 'reason': 'durable_account_outbox'}
        except Exception:
            return {'sent': False, 'queued': False, 'kind': kind, 'reason': 'account_outbox_source_unavailable'}

    def claim(self, limit):
        with self.connection_factory() as db, db.cursor() as cur:
            # A process may have sent after committing its claim. Never redeliver a lost claim.
            cur.execute("UPDATE public.pr_transactional_mail SET status='uncertain',lease_until=NULL,updated_at=now() "
                        "WHERE status='dispatching' AND lease_until<now()")
            cur.execute("UPDATE public.pr_transactional_mail SET status='dispatching',lease_until=now()+interval '120 seconds',updated_at=now() "
                        "WHERE id IN(SELECT id FROM public.pr_transactional_mail WHERE status='queued' ORDER BY created_at LIMIT %s FOR UPDATE SKIP LOCKED) "
                        'RETURNING id::text,kind,semantic_key,payload_cipher,key_id,user_id::text,extract(epoch from occurred_at)', (limit,))
            rows = cur.fetchall()
            db.commit()
        return rows

    def complete(self, identifier, state, provider_ref=None, reason=None):
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('UPDATE public.pr_transactional_mail SET status=%s,provider_ref=coalesce(provider_ref,%s),failure_code=%s,lease_until=NULL,updated_at=now() '
                        "WHERE id=%s AND status='dispatching'", (state, provider_ref, reason, identifier))
            db.commit()

    def send(self, row):
        identifier, kind, key, cipher, key_id, user, occurred = row
        try:
            payload = json.loads(self.vault.decrypt(cipher, key_id))
            with self.connection_factory() as db, db.cursor() as cur:
                original = source(cur, kind, payload['to'], payload['context'], self.clock())
                if original['id'] != payload['source']['id'] or original['userId'] != user:
                    return ('cancelled', None, 'source_changed')
                cur.execute("SELECT 1 FROM public.pr_transactional_mail WHERE recipient_hash=%s AND status IN('bounced','complained') LIMIT 1",
                            (hashlib.sha256(payload['to'].encode()).hexdigest(),))
                if cur.fetchone():
                    return ('suppressed', None, 'recipient_suppressed')
                if user:
                    cur.execute('SELECT 1 FROM public.pr_notification_preferences WHERE user_id=%s AND email_unsubscribed LIMIT 1', (user,))
                    if cur.fetchone():
                        return ('suppressed', None, 'email_opt_out')
                cur.execute("SELECT operator_id::text FROM public.pr_delivery_cutovers WHERE audience='customer' AND channel='email' ORDER BY revision DESC LIMIT 1")
                approved = cur.fetchone()
            if not approved:
                return ('suppressed', None, 'delivery_cutover_not_approved')
            operator = approved[0]
            workspace, settings = founder_email.context(self, operator)
            subject, text, html = self.mailer.render(kind, **payload['context'])
            message = {'from': self.mailer.from_address, 'to': payload['to'], 'replyTo': settings['replyTo'], 'subject': subject,
                       'text': text, 'html': html, 'idempotencyKey': 'legacy-' + key, 'templateVersion': VERSION,
                       'tags': [{'name': 'legacy_delivery_id', 'value': identifier}, {'name': 'kind', 'value': kind}]}
            decision = cutover.admit(self.connection_factory, [{'id': identifier, 'userId': user}],
                                     [{'type': 'account.' + kind, 'occurredAt': float(occurred)}], message, now=self.clock(),
                                     linked_delivery_id=None,
                                     reserve=lambda cur: founder_email.reserve(self, cur, operator, workspace, settings, 'legacy-' + key))
            if decision:
                return ('uncertain' if decision['state'] == 'uncertain' else 'suppressed', None, decision['detail'])
        except Exception as error:
            return ('suppressed', None, 'account_delivery_not_qualified_' + type(error).__name__)
        # No catch-and-resubmit: a lost provider response is an unknown outcome.
        try:
            receipt = self.mailer.transport.send(message)
            reference = receipt.get('id') if isinstance(receipt, dict) else None
            if not isinstance(reference, str) or not reference or len(reference) > 200:
                return ('uncertain', None, 'provider_acceptance_unknown')
            return ('provider_accepted', reference, None)
        except Exception:
            return ('uncertain', None, 'provider_acceptance_unknown')

    def tick(self, limit=10):
        counts = {}
        try:
            for row in self.claim(min(25, max(0, limit))):
                state, reference, reason = self.send(row)
                self.complete(row[0], state, reference, reason)
                counts[state] = counts.get(state, 0) + 1
            return {'state': 'processed', 'counts': counts, 'deliveryProof': 'provider_callback_required'}
        except Exception:
            return {'state': 'unavailable', 'reason': 'account_outbox_source_unavailable'}


def ingest(cur, identifier, provider_ref, mapped):
    """Apply an already signature-verified callback to a committed dispatch only."""
    try:
        uuid.UUID(str(identifier))
    except (ValueError, TypeError, AttributeError):
        return None
    cur.execute('SELECT status,provider_ref,user_id::text FROM public.pr_transactional_mail m WHERE id=%s '
                "AND EXISTS(SELECT 1 FROM public.pr_notification_provider_events e WHERE e.provider='resend_dispatch' "
                "AND e.event_id='legacy-'||m.semantic_key) FOR UPDATE", (identifier,))
    row = cur.fetchone()
    if not row or row[0] in ('queued', 'cancelled', 'suppressed') or (row[1] and row[1] != provider_ref):
        return None
    status, _, user = row
    state = None
    if mapped == 'delivered' and status in ('dispatching', 'provider_accepted', 'uncertain'):
        state = 'delivered'
    elif mapped in ('bounced', 'complained'):
        state = mapped
    elif mapped == 'failed' and status not in ('delivered', 'bounced', 'complained'):
        state = 'failed'
    if state:
        cur.execute('UPDATE public.pr_transactional_mail SET status=%s,provider_ref=coalesce(provider_ref,%s),'
                    "delivered_at=CASE WHEN %s='delivered' THEN coalesce(delivered_at,now()) ELSE delivered_at END,updated_at=now() WHERE id=%s",
                    (state, provider_ref, state, identifier))
        if mapped in ('bounced', 'complained') and user:
            from .webhooks import _suppress_email
            _suppress_email(cur, user, mapped)
        return 'applied'
    return 'ignored'
