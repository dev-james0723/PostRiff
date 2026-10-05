"""Server-owned X request ceilings and durable cost reservations.

Amounts are user-approved ceilings in micro-USD, never claimed actual billing.
Reservations are retained after errors/unknown effects. No approved policy means
no metered request. The provider account's credit balance is not authorization.
"""
import hashlib
import json
import re
import secrets
from urllib.parse import urlsplit
from postriff_alpha.domain import AlphaError


class BudgetedToken(str):
    def __new__(cls, value, budget):
        token = super().__new__(cls, value)
        token.budget = budget
        return token


class XRequestBudget:
    def __init__(self, oauth, workspace, connection, cursor=None):
        self.oauth, self.workspace, self.connection = oauth, workspace, connection
        self.cursor = cursor

    def policy(self):
        adapter = self.oauth._provider('x')
        record = getattr(adapter, 'budget_policies', {}).get(self.workspace+':'+self.connection) or {}
        if (record.get('currency') != 'USD' or not record.get('approvalRef')
                or type(record.get('limitMicros')) is not int or not 0 < record['limitMicros'] <= 1_000_000_000
                or type(record.get('perRequestMicros')) is not int or not 0 < record['perRequestMicros'] <= record['limitMicros']
                or type(record.get('expiresAt')) not in (int, float) or record['expiresAt'] <= self.oauth.clock()):
            raise AlphaError('Approve an X API spending ceiling for this connection before using metered endpoints.', 409, code='x_budget_required')
        return record

    def available(self):
        self.policy()
        return True

    def reserve(self, method, path):
        policy = self.policy()
        # The price ceiling must be sufficient for the documented endpoint/resource
        # count. Configuring it is intentional and belongs to the reviewed policy.
        route = urlsplit(path).path
        if not route.startswith('/2/') or method not in ('GET', 'POST', 'PUT', 'DELETE'):
            raise AlphaError('X budget does not authorize this endpoint.', 409)
        match = any(re.fullmatch(re.escape(endpoint).replace(r'\{id\}', r'[A-Za-z0-9_-]{1,64}'), method+' '+route) for endpoint in policy.get('allowedEndpoints', []) if isinstance(endpoint, str))
        if not match:
            raise AlphaError('This X endpoint has no approved request-cost ceiling.', 409, code='x_budget_required')
        fingerprint = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
        def persist(cur):
            cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (self.workspace,))
            row = cur.fetchone()
            if not row: raise AlphaError('Workspace unavailable.', 404)
            state = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            ledger = state['phase2'].setdefault('apiCostReservations', [])
            reserved = sum(item['ceilingMicros'] for item in ledger if item.get('policyHash') == fingerprint)
            if reserved+policy['perRequestMicros'] > policy['limitMicros'] or len(ledger) >= 10000:
                raise AlphaError('X API spending ceiling is exhausted. Review costs before increasing it.', 409, code='x_budget_exhausted')
            ledger.append({'id': secrets.token_hex(12), 'provider': 'x', 'connectionId': self.connection, 'method': method,
                           'path': route, 'policyHash': fingerprint, 'ceilingMicros': policy['perRequestMicros'],
                           'currency': 'USD', 'kind': 'approved_ceiling_reservation', 'at': self.oauth.clock()})
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), self.workspace))
        if self.cursor is not None:
            persist(self.cursor)
        else:
            with self.oauth.repository.connection_factory() as db:
                with db.cursor() as cur: persist(cur)
        return True
