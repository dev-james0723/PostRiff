"""Opt-in customer admission from existing billing facts; never grants plans or provider rights.

Legacy private beta remains unchanged while the switch is off. A public customer
rollout requires current, reconciled Studio/Assist subscription rights and an
actual live paid invoice. Founder capacity, trial/manual grants and test invoices
cannot substitute. Every decision is read afresh; there is no revocation cache.
"""
import logging
import time
import uuid

from postriff_alpha.domain import AlphaError

FLAG = 'POSTRIFF_CUSTOMER_STUDIO_ENABLED'
BINDING = '_RAFII_CUSTOMER_ACCESS'
LOG = logging.getLogger('postriff.customer_access')


def enabled(values):
    return str((values or {}).get(FLAG, '')).strip().lower() in ('1', 'true', 'yes', 'on')


PAID_SQL = """FROM public.pr_workspaces w
    JOIN public.pr_subscriptions s ON s.workspace_id=w.id
    JOIN public.pr_entitlements e ON e.workspace_id=w.id
    JOIN public.pr_plan_terms p ON p.id=s.plan_terms_id
    WHERE NOT (w.state ? 'accountDeletion') AND w.state->'founderOps' IS NULL
      AND p.plan IN ('studio','assist') AND p.status='active' AND p.provider_price_id IS NOT NULL
      AND s.provider='stripe' AND s.status='active' AND s.current_period_end>to_timestamp(%s)
      AND e.source='subscription' AND e.plan_terms_id=s.plan_terms_id
      AND EXISTS(SELECT 1 FROM public.pr_invoices i WHERE i.workspace_id=w.id
        AND i.provider=s.provider AND i.subscription_id=s.provider_subscription_id
        AND i.status='paid' AND i.livemode IS TRUE AND i.amount_paid>0
        AND i.period_start<=to_timestamp(%s) AND i.period_end>to_timestamp(%s)
        AND i.period_end>=s.current_period_end)"""


class CustomerAccess:
    def __init__(self, connection_factory, *, clock=time.time):
        self.connection_factory = connection_factory
        self.clock = clock

    @staticmethod
    def schema_ready(cur):
        cur.execute("SELECT to_regclass('public.pr_invoices') IS NOT NULL")
        return bool(cur.fetchone()[0])

    def _status(self, cur, workspace_id):
        if not self.schema_ready(cur):
            return {'qualified': False, 'reason': 'billing_evidence_unavailable', 'plan': None}
        at = self.clock()
        cur.execute('SELECT p.plan,p.id ' + PAID_SQL + ' AND w.id=%s', (at, at, at, workspace_id))
        row = cur.fetchone()
        return {'qualified': bool(row), 'reason': 'paid_studio' if row else 'current_live_paid_studio_required',
                'plan': row[0] if row else None, 'planTermsId': row[1] if row else None}

    def status(self, workspace_id, *, cursor=None):
        try:
            workspace_id = str(uuid.UUID(str(workspace_id)))
        except (ValueError, TypeError, AttributeError):
            return {'qualified': False, 'reason': 'invalid_workspace', 'plan': None}
        if cursor is not None:
            # Caller already owns the tenant transaction; don't open a second connection under its locks.
            return self._status(cursor, workspace_id)
        try:
            with self.connection_factory() as db, db.cursor() as cur:
                return self._status(cur, workspace_id)
        except Exception as error:
            LOG.warning('customer_admission_unavailable errorClass=%s', type(error).__name__)
            return {'qualified': False, 'reason': 'billing_evidence_unavailable', 'plan': None}

    def allowed(self, workspace_id, *, cursor=None):
        return self.status(workspace_id, cursor=cursor)['qualified'] is True

    def require(self, workspace_id, *, cursor=None):
        if not self.allowed(workspace_id, cursor=cursor):
            raise AlphaError('A current paid Studio or Studio Assist subscription is required.', 403, code='paid_studio_required')

    def workspaces(self, *, cursor=None):
        def read(cur):
            if not self.schema_ready(cur): return []
            at = self.clock()
            cur.execute('SELECT w.id::text ' + PAID_SQL + ' ORDER BY w.id', (at, at, at))
            return [r[0] for r in cur.fetchall()]
        if cursor is not None: return read(cursor)
        try:
            with self.connection_factory() as db, db.cursor() as cur: return read(cur)
        except Exception as error:
            LOG.warning('customer_enumeration_unavailable errorClass=%s', type(error).__name__)
            return []
