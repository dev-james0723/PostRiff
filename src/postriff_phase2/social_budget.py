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
        if not record:
            candidate = getattr(adapter, 'onboarding_budget_policy', {})
            if (candidate.get('appId') == adapter.client_id and candidate.get('purpose') == 'connection_identity'
                    and candidate.get('allowedEndpoints') == ['GET /2/users/me']
                    and type(candidate.get('appLimitMicros')) is int
                    and type(candidate.get('limitMicros')) is int
                    and 0 < candidate['limitMicros'] <= candidate['appLimitMicros'] <= 1_000_000_000):
                record = candidate
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
        # The independent transaction commits before dispatch and survives rollback of
        # the OAuth transaction. Never take a workspace lock here: the caller may hold it.
        with self.oauth.repository.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('x-budget:'+fingerprint,))
                cur.execute('SELECT coalesce(sum(ceiling_micros),0),coalesce(sum(ceiling_micros) FILTER (WHERE workspace_id=%s),0) FROM public.pr_social_cost_reservations WHERE policy_hash=%s', (self.workspace, fingerprint))
                app_reserved, workspace_reserved = cur.fetchone()
                # Include pre-migration reservations; never reset an approved allowance.
                cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (self.workspace,))
                row = cur.fetchone()
                if not row: raise AlphaError('Workspace unavailable.', 404)
                state = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                legacy = sum(item['ceilingMicros'] for item in state.get('phase2', {}).get('apiCostReservations', []) if item.get('policyHash') == fingerprint)
                if (workspace_reserved + legacy + policy['perRequestMicros'] > policy['limitMicros']
                        or app_reserved + policy['perRequestMicros'] > policy.get('appLimitMicros', policy['limitMicros'])):
                    raise AlphaError('X API spending ceiling is exhausted. Review costs before increasing it.', 409, code='x_budget_exhausted')
                cur.execute('INSERT INTO public.pr_social_cost_reservations(id,workspace_id,connection_id,policy_hash,endpoint,ceiling_micros) VALUES(%s,%s,%s,%s,%s,%s)',
                            (secrets.token_hex(12), self.workspace, self.connection, fingerprint, method+' '+route, policy['perRequestMicros']))
        return True
