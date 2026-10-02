"""Founder actions (CONTRACTS §8.F): preview -> confirm through the real Control boundary and the real consumer adapter.

The consumer SQL layer (postriff_phase2.operator_actions) is replaced by an in-memory stand-in with the same call surface,
so every protocol rule runs for real here: capability, fresh second factor, CSRF, budget, Demo refusal, preview expiry,
revision, moved targets, request-id idempotency, interrupted outcomes, credits/refund policy and the audit linkage.
tests/control/test_founder_actions_pg.py runs the same flows against PostgreSQL with the real SQL.
"""
import copy
import inspect
import io
import json
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from postriff_phase2 import operator_actions
from postriff_phase2.credit_wallet import project_credit_wallet
from rafii_control import founder_actions, http
from rafii_control.auth import Boundary, CAPABILITIES, Config, VerifiedIdentity, READ_BUDGET
from rafii_control.founder_actions import ActionError
from rafii_control.http import ControlApplication
from control.test_boundary import MemoryStore, NOW, USER

WS = '20000000-0000-4000-8000-000000000001'
WS2 = '20000000-0000-4000-8000-000000000002'
OPS_WS = '20000000-0000-4000-8000-0000000000ff'
CUSTOMER = '30000000-0000-4000-8000-000000000001'
OTHER = '30000000-0000-4000-8000-000000000002'
RES = '40000000-0000-4000-8000-000000000001'
GRANT = '50000000-0000-4000-8000-000000000001'
POLICY = 'credits-candidate-2026-09-23-v1'
ORIGIN = 'http://localhost:4449'


def rid():
    return str(uuid.uuid4())


class MemoryActionStore:
    """founder_action_requests in memory, with ActionStore's call surface and row shape."""
    environment = 'local'

    def __init__(self):
        self.rows = {}

    def _match(self, request_id):
        return next((r for r in self.rows.values() if request_id in (r['request_id'], r['confirm_request_id'])), None)

    def by_request(self, operator_id, request_id):
        return copy.deepcopy(self._match(request_id))

    def insert_preview(self, row):
        if any(r['confirm_request_id'] == row['request_id'] for r in self.rows.values()):
            raise ActionError('IDEMPOTENCY_CONFLICT', 409, 'request_id_used')
        existing = next((r for r in self.rows.values() if r['request_id'] == row['request_id']), None)
        if existing:
            return copy.deepcopy(existing), False
        stored = {**json.loads(json.dumps(row)), 'environment': 'local', 'state': 'previewed', 'confirm_request_id': None, 'confirm_audit_id': None,
                  'result': {}, 'error_code': None, 'expires_at': row['created_at'] + founder_actions.PREVIEW_SECONDS, 'confirmed_at': None, 'finished_at': None}
        self.rows[row['id']] = stored
        return copy.deepcopy(stored), True

    def claim(self, operator_id, preview_id, request_id, decide):
        row = self.rows.get(preview_id)
        row = copy.deepcopy(row) if row and row['operator_id'] == operator_id else None
        used = self._match(request_id)
        outcome, changes = decide(row, used['id'] if used else None)
        if changes:
            self.rows[preview_id].update(changes)
            row = copy.deepcopy(self.rows[preview_id])
        return outcome, row

    def finish(self, operator_id, preview_id, state, now, *, result=None, error_code=None, blocker=None):
        stored = self.rows[preview_id]
        if stored['state'] == 'confirmed':
            stored.update(state=state, result=json.loads(json.dumps(result or {})), error_code=error_code, blocker=blocker, finished_at=now)
        return copy.deepcopy(stored)

    def recent(self, operator_id, limit, *, kind=None, target_id=None):
        rows = [r for r in self.rows.values() if (kind is None or r['kind'] == kind) and (target_id is None or target_id in (r['target_id'], r['workspace_id']))]
        return copy.deepcopy(sorted(rows, key=lambda r: (-r['created_at'], r['id']))[:limit])

    def active_blocks(self, limit=200):
        return [{'blockId': 'b-1', 'userId': CUSTOMER, 'workspaceId': None, 'reasonCode': 'abuse', 'blockedAt': '2026-09-21T00:00:00+00:00'}]


class FakeBook:
    clock = staticmethod(lambda: NOW)


class FakeOps:
    """In-memory stand-in for postriff_phase2.operator_actions: the same functions, constants and semantics."""
    CODE, MESSAGE = operator_actions.CODE, operator_actions.MESSAGE
    REASON_CODES, LIFT_REASON_CODES = operator_actions.REASON_CODES, operator_actions.LIFT_REASON_CODES
    CREDIT_REASON_CODES, REFUND_REASON_CODES = operator_actions.CREDIT_REASON_CODES, operator_actions.REFUND_REASON_CODES
    MAX_FROZEN_WORKSPACES = operator_actions.MAX_FROZEN_WORKSPACES
    reconcile_effect = staticmethod(operator_actions.reconcile_effect)
    wallet_after = staticmethod(operator_actions.wallet_after)
    operator_label = staticmethod(operator_actions.operator_label)

    def __init__(self):
        self.status = 'installed'
        self.fail = None
        self.workspaces = {WS, WS2, OPS_WS}
        self.reservations = {(WS, RES): dict(workspaceId=WS, reservationId=RES, dimension='text_model', provider='gateway', model='writer-model',
                                             estimatedUsdMicro=5000, chargeBatch=False, runId=None, creditsMaximumMilli=None, since=NOW - 600,
                                             unknown=True, settled=False, runStatus='failed')}
        self.credit_rows = {WS: [{'id': GRANT, 'reservationId': None, 'credits': {'op': 'grant', 'milli': 10000, 'expiresAt': None}}]}
        self.policies = {WS: POLICY, WS2: None}
        self.users = {CUSTOMER: [WS], OTHER: []}
        self.blocks, self.history = {}, []
        self.payments = {(WS, 'pi_fixture0001'): dict(source='credit_order', sourceId='o-1', paidMinor=1500, currency='usd', status='funded', livemode=False,
                                                      paidAt=NOW - 86400, refundedMinor=0, refunds=0, disputed=False)}
        self.audit, self.writes = [], []

    def _maybe_fail(self, when):
        if self.fail == when:
            self.fail = None
            raise RuntimeError('connection lost')

    # reconcile
    def probe_now(self, cur):
        return self.status

    def lock_workspace(self, cur, workspace_id):
        return workspace_id in self.workspaces

    def reservation_snapshot(self, cur, workspace_id, reservation_id):
        row = self.reservations.get((workspace_id, reservation_id))
        return copy.deepcopy(row) if row else None

    def reconciled_by(self, cur, workspace_id, reservation_id, action_id):
        for kind, subject, meta in self.audit:
            if kind == 'usage.reconciled' and subject == reservation_id and meta['operator'] == operator_actions.operator_label(action_id):
                return {'reservationId': reservation_id, 'state': meta['state'], 'actualUsdMicro': meta['actual'], 'consumerAudit': 'usage.reconciled'}
        return None

    def reconcile(self, cur, ledger, workspace_id, reservation_id, outcome, actual, *, action_id, evidence):
        self._maybe_fail('before')
        state = 'actual' if outcome == 'completed' else 'released'
        self.reservations[(workspace_id, reservation_id)]['settled'] = True
        self.audit.append(('usage.reconciled', reservation_id, {'operator': operator_actions.operator_label(action_id), 'state': state, 'actual': actual, 'evidence': evidence}))
        self.writes.append(('reconcile', action_id))
        self._maybe_fail('after')
        return {'reservationId': reservation_id, 'state': state, 'actualUsdMicro': actual, 'consumerAudit': 'usage.reconciled'}

    # credits
    def wallet_snapshot(self, cur, book, workspace_id):
        if workspace_id not in self.workspaces:
            return {'refused': 'workspace_not_found'}
        if not self.policies.get(workspace_id):
            return {'refused': 'workspace_not_on_credit_terms'}
        rows = copy.deepcopy(self.credit_rows.get(workspace_id, []))
        view = project_credit_wallet(rows, NOW)
        return {'policy': self.policies[workspace_id], 'rows': rows, 'wallet': {k: view[k] for k in ('availableMilliCredits', 'heldMilliCredits', 'usedMilliCredits', 'debtMilliCredits')},
                'lots': [{k: lot.get(k) for k in ('grantId', 'milli', 'expiresAt', 'used', 'held', 'reversed', 'available')} for lot in view['lots']]}

    def credited_by(self, cur, workspace_id, action_id):
        return next((r['id'] for r in self.credit_rows.get(workspace_id, []) if r.get('key') == 'founder-credit:' + action_id), None)

    def adjust_credits(self, cur, book, workspace_id, *, operation, milli, expires_at, grant_id, reason_code, action_id):
        entry = 'entry-' + action_id[:8]
        credit = {'op': 'grant', 'milli': milli, 'expiresAt': expires_at} if operation == 'grant' else {'op': 'reverse', 'grantId': grant_id, 'milli': milli}
        self.credit_rows[workspace_id].append({'id': entry, 'reservationId': None, 'credits': credit, 'key': 'founder-credit:' + action_id})
        self.audit.append(('credit.adjusted_by_operator', entry, {'operator': operator_actions.operator_label(action_id), 'reasonCode': reason_code}))
        self.writes.append(('credits', action_id))
        return {'entryId': entry, 'duplicate': False, 'consumerAudit': 'credit.adjusted_by_operator'}

    # blocks
    def block_snapshot(self, cur, target_type, target_id, *, lock=False):
        if target_type == 'user':
            if target_id not in self.users:
                return None
            frozen, target = list(self.users[target_id]), {'type': 'user', 'id': target_id, 'deleted': False, 'activeMemberships': 1, 'ownedWorkspaces': len(self.users[target_id])}
        else:
            if target_id not in self.workspaces:
                return None
            frozen, target = [target_id], {'type': 'workspace', 'id': target_id, 'ownerId': CUSTOMER, 'memberCount': 1}
        return {'target': target, 'block': copy.deepcopy(self.blocks.get((target_type, target_id))), 'frozenWorkspaceIds': frozen, 'activeApiTokens': 0}

    def block_by_action(self, cur, action_id):
        return next((copy.deepcopy(b) for b in self.history if b['action'] == action_id), None)

    def lift_by_action(self, cur, action_id):
        return next((copy.deepcopy(b) for b in self.history if b.get('liftAction') == action_id), None)

    def apply_block(self, cur, *, target_type, target_id, frozen_workspace_ids, reason_code, approval_ref, operator_id, action_id):
        block = {'blockId': 'block-' + action_id[:8], 'reasonCode': reason_code, 'blockedAt': NOW, 'frozenWorkspaceIds': sorted(frozen_workspace_ids), 'action': action_id}
        self.blocks[(target_type, target_id)] = {k: block[k] for k in ('blockId', 'reasonCode', 'blockedAt', 'frozenWorkspaceIds')}
        self.history.append(block)
        self.audit.append(('account.blocked', block['blockId'], {'operator': operator_actions.operator_label(action_id), 'reasonCode': reason_code}))
        self.writes.append(('block', action_id))
        return {**self.blocks[(target_type, target_id)], 'duplicate': False, 'consumerAudit': 'account.blocked'}

    def lift_block(self, cur, *, target_type, target_id, block_id, reason_code, operator_id, action_id):
        block = self.blocks.pop((target_type, target_id), None)
        if block is None or block['blockId'] != block_id:
            return None
        next(b for b in self.history if b['blockId'] == block_id)['liftAction'] = action_id
        self.audit.append(('account.unblocked', block_id, {'operator': operator_actions.operator_label(action_id), 'reasonCode': reason_code}))
        self.writes.append(('unblock', action_id))
        return {'blockId': block_id, 'thawedWorkspaceIds': block['frozenWorkspaceIds'], 'duplicate': False, 'consumerAudit': 'account.unblocked'}

    # refunds
    def payment_snapshot(self, cur, workspace_id, payment_intent_id):
        if self.status == 'payments_missing':
            return 'not_configured'
        row = self.payments.get((workspace_id, payment_intent_id))
        return copy.deepcopy(row) if row else None


class FakeDB:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self


class ActionRouteTests(unittest.TestCase):
    def setUp(self):
        # These action tests use a MemoryStore; Ops metadata/RLS is independently
        # exercised against PostgreSQL, including invalid/revoked owners.
        from rafii_control import founder_ops
        for name, value in (('ready', True), ('stored', None)):
            ops_patcher = mock.patch.object(founder_ops, name, return_value=value)
            ops_patcher.start()
            self.addCleanup(ops_patcher.stop)
        self.store = MemoryStore()
        self.store.operator_row['capabilities'] = sorted(CAPABILITIES)
        self.budgets = []
        self.store.budget = lambda purpose, actor, limit: self.budgets.append((purpose, limit))
        self.time, self.mfa = NOW, NOW
        self.boundary = Boundary(Config(True, 'local', ORIGIN), self.store, lambda token: VerifiedIdentity(USER, 'aal2', 's' * 32, self.mfa), clock=lambda: self.time)
        self.service = SimpleNamespace(connection_factory=FakeDB, ledger=SimpleNamespace(credits=None))
        self.app = ControlApplication(self.boundary, SimpleNamespace(store=self.store), runtime=lambda: self.service, flags={'RAFII_FOUNDER_OPS_WORKSPACE_ID': OPS_WS})
        self.actions = self.app.founder_action_store = MemoryActionStore()
        self.ops = FakeOps()
        patcher = mock.patch.object(founder_actions, 'operator_actions', self.ops)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sign_in()

    def sign_in(self):
        self.token, session = self.boundary.exchange('verified-token', ORIGIN)
        self.csrf = session['csrfToken']

    def request(self, path, method='POST', body=None, headers=None):
        raw = json.dumps(body).encode() if body is not None else b''
        path, _, query = path.partition('?')
        env = dict(PATH_INFO='/api/control/v2' + path, QUERY_STRING=query, REQUEST_METHOD=method, CONTENT_LENGTH=str(len(raw)), CONTENT_TYPE='application/json',
                   HTTP_HOST='localhost:4449', HTTP_ORIGIN=ORIGIN, HTTP_COOKIE='__Host-rafii-control=' + self.token, HTTP_X_CSRF_TOKEN=self.csrf,
                   **{'wsgi.input': io.BytesIO(raw)})
        env.update(headers or {})
        result = {}
        data = b''.join(self.app(env, lambda status, hs: result.update(status=int(status[:3]))))
        return result['status'], json.loads(data)

    def reconcile_preview(self, **changes):
        body = dict(requestId=rid(), workspaceId=WS, reservationId=RES, outcome='failed', actualUsdMicro=4200, evidence='gateway req 3f2a91')
        body.update(changes)
        return self.request('/usage/reconcile/preview', body=body)

    @staticmethod
    def confirm_body(preview, **changes):
        action = preview['data']['action']
        return {'previewId': action['previewId'], 'revision': action['revision'], 'requestId': rid(), **changes}

    def last_audit(self):
        return self.store.events[-1]

    # --- registration -------------------------------------------------------------------------------------------------------
    def test_routes_carry_capability_step_up_and_the_action_budget(self):
        routes = {(r[0], r[1].pattern): (r[2], r[5]) for r in http.EXTENSION_ROUTES if r[3] == 'founder_actions'}
        expected = {'/usage/reconcile/preview': 'usage.reconcile', '/usage/reconcile/confirm': 'usage.reconcile', '/actions/credits/preview': 'credits.adjust',
                    '/actions/credits/confirm': 'credits.adjust', '/actions/accounts/([A-Za-z0-9_-]{1,80})/block/preview': 'accounts.block',
                    '/actions/accounts/([A-Za-z0-9_-]{1,80})/block/confirm': 'accounts.block', '/actions/accounts/([A-Za-z0-9_-]{1,80})/unblock/preview': 'accounts.block',
                    '/actions/accounts/([A-Za-z0-9_-]{1,80})/unblock/confirm': 'accounts.block', '/actions/refunds/preview': 'refunds.prepare', '/actions/refunds/execute/preview': 'refunds.prepare', '/actions/refunds/confirm': 'refunds.prepare'}
        self.assertEqual({path: capability for (method, path), (capability, _) in routes.items() if method == 'POST'}, expected)
        for (method, path), (capability, options) in routes.items():
            if method == 'POST':
                self.assertEqual(options, {'step_up': True, 'budget': 'founder.action'}, path)
        self.assertEqual(routes[('GET', '/actions')], ('audit.read', {}))
        self.assertEqual(len(routes), 12)
        self.assertIn(('POST', '/actions/refunds/confirm'), routes)  # financial confirmation remains protected

    # --- reconcile ------------------------------------------------------------------------------------------------------------
    def test_reconcile_preview_then_confirm_executes_once_with_both_audits(self):
        status, preview = self.reconcile_preview()
        self.assertEqual(status, 200, preview)
        action = preview['data']['action']
        self.assertEqual((action['kind'], action['state'], action['targetType'], action['targetId']), ('reconcile', 'previewed', 'reservation', RES))
        self.assertRegex(action['revision'], r'^[0-9a-f]{16}$')
        self.assertEqual(action['current']['estimatedUsdMicro'], 5000)
        self.assertEqual(action['effect']['providerCostBookedUsdMicro'], 4200)
        self.assertFalse(action['effect']['customerCharged'])
        self.assertEqual(action['effect']['evidence'], {'provided': True, 'characters': 18})
        self.assertNotIn('gateway req', json.dumps(preview))   # the evidence reference is executed with, never echoed
        self.assertEqual(action['confirm']['path'], '/api/control/v2/usage/reconcile/confirm')
        self.assertEqual(action['confirm']['requires'], ['fresh_second_factor'])
        self.assertEqual(self.ops.writes, [])   # a preview never writes to the consumer
        self.assertEqual((self.last_audit()['action'], self.last_audit()['result']), ('usage.reconcile', 'succeeded'))
        body = self.confirm_body(preview)
        status, confirmed = self.request('/usage/reconcile/confirm', body=body)
        self.assertEqual(status, 200, confirmed)
        done = confirmed['data']['action']
        self.assertEqual((done['state'], done['result']['state'], done['result']['consumerAudit'], confirmed['data']['replayed']), ('executed', 'released', 'usage.reconciled', False))
        self.assertEqual(self.ops.writes, [('reconcile', action['previewId'])])
        self.assertEqual([a[0] for a in self.ops.audit], ['usage.reconciled'])   # consumer audit
        row = self.actions.rows[action['previewId']]
        self.assertEqual((row['preview_audit_id'], row['confirm_audit_id']), (preview['requestId'], confirmed['requestId']))   # links the Control audit rows
        control = [e for e in self.store.events if e['request_id'] == confirmed['requestId']]
        self.assertEqual([(e['action'], e['result']) for e in control], [('usage.reconcile', 'allowed'), ('usage.reconcile', 'succeeded')])
        # The same confirm again: the recorded outcome, no second execution.
        status, again = self.request('/usage/reconcile/confirm', body=body)
        self.assertEqual((status, again['data']['replayed'], again['data']['action']['state']), (200, True, 'executed'))
        self.assertEqual(len(self.ops.writes), 1)
        # A new request id for the used preview: refused.
        status, used = self.request('/usage/reconcile/confirm', body={**body, 'requestId': rid()})
        self.assertEqual((status, used['code'], used['blocker']), (409, 'STALE_PREVIEW', 'preview_executed'))
        # The reservation is no longer waiting: a new preview is refused.
        status, refused = self.reconcile_preview()
        self.assertEqual((status, refused['code'], refused['blocker']), (409, 'VALIDATION_FAILED', 'not_waiting_for_reconciliation'))
        self.assertEqual(len(self.ops.writes), 1)

    def test_refused_confirms_have_no_side_effects(self):
        _, preview = self.reconcile_preview()
        action = preview['data']['action']
        cases = [({'revision': '0' * 16}, 409, 'STALE_PREVIEW', 'revision_mismatch'),
                 ({'previewId': rid()}, 404, 'VALIDATION_FAILED', 'preview_not_found'),
                 ({'revision': 'not-a-revision'}, 400, 'VALIDATION_FAILED', 'invalid_revision'),
                 ({'extra': 1}, 400, 'VALIDATION_FAILED', 'unexpected_fields')]
        for changes, code, error, blocker in cases:
            with self.subTest(changes=changes):
                status, refused = self.request('/usage/reconcile/confirm', body=self.confirm_body(preview, **changes))
                self.assertEqual((status, refused['code'], refused.get('blocker')), (code, error, blocker))
        # Replaying the preview's own request id as the confirm request id.
        preview_request = next(r['request_id'] for r in self.actions.rows.values())
        status, replay = self.request('/usage/reconcile/confirm', body=self.confirm_body(preview, requestId=preview_request))
        self.assertEqual((status, replay['code'], replay['blocker']), (409, 'IDEMPOTENCY_CONFLICT', 'request_id_used'))
        # Another route's confirm for this preview.
        status, mismatch = self.request('/actions/credits/confirm', body=self.confirm_body(preview))
        self.assertEqual((status, mismatch['code']), (409, 'POLICY_DISABLED'))   # credits off is checked before the preview is touched
        self.service.ledger.credits = FakeBook()
        status, mismatch = self.request('/actions/credits/confirm', body=self.confirm_body(preview))
        self.assertEqual((status, mismatch['code'], mismatch['blocker']), (400, 'VALIDATION_FAILED', 'preview_mismatch'))
        self.assertEqual((self.actions.rows[action['previewId']]['state'], self.ops.writes), ('previewed', []))
        # The target moved after the preview: refused inside the consumer transaction, nothing written.
        self.ops.reservations[(WS, RES)]['estimatedUsdMicro'] = 9000
        status, moved = self.request('/usage/reconcile/confirm', body=self.confirm_body(preview))
        self.assertEqual((status, moved['code'], moved['blocker']), (409, 'STALE_PREVIEW', 'target_changed'))
        self.assertEqual((self.actions.rows[action['previewId']]['state'], self.ops.writes), ('failed', []))
        self.assertEqual((self.last_audit()['action'], self.last_audit()['result'], self.last_audit()['error_code']), ('usage.reconcile', 'denied', 'STALE_PREVIEW'))

    def test_missing_step_up_and_expired_previews_are_refused(self):
        _, preview = self.reconcile_preview()
        action = preview['data']['action']
        self.time = NOW + 301   # second factor older than five minutes
        status, refused = self.request('/usage/reconcile/confirm', body=self.confirm_body(preview))
        self.assertEqual((status, refused['code']), (403, 'STEP_UP_REQUIRED'))
        status, refused = self.reconcile_preview()
        self.assertEqual((status, refused['code']), (403, 'STEP_UP_REQUIRED'))
        self.mfa = NOW + 301   # a fresh second factor, but the preview is now past its five minutes
        self.sign_in()
        status, expired = self.request('/usage/reconcile/confirm', body=self.confirm_body(preview))
        self.assertEqual((status, expired['code'], expired['blocker']), (409, 'STALE_PREVIEW', 'preview_expired'))
        self.assertEqual((self.actions.rows[action['previewId']]['state'], self.ops.writes), ('previewed', []))
        status, listing = self.request('/actions', method='GET')
        self.assertEqual(listing['data']['actions'][0]['state'], 'expired')
        self.assertIsNone(listing['data']['actions'][0]['confirm'])

    def test_interrupted_confirm_resumes_with_the_same_request_id_and_executes_once(self):
        for when in ('before', 'after'):
            with self.subTest(when=when):
                self.ops = FakeOps()
                patcher = mock.patch.object(founder_actions, 'operator_actions', self.ops)
                patcher.start()
                self.addCleanup(patcher.stop)
                _, preview = self.reconcile_preview()
                body = self.confirm_body(preview)
                self.ops.fail = when
                status, lost = self.request('/usage/reconcile/confirm', body=body)
                self.assertEqual((status, lost['code'], lost['blocker']), (503, 'SOURCE_UNAVAILABLE', 'outcome_unknown_retry_same_request'))
                self.assertEqual(self.actions.rows[preview['data']['action']['previewId']]['state'], 'confirmed')
                status, resumed = self.request('/usage/reconcile/confirm', body={**body, 'requestId': rid()})
                self.assertEqual((status, resumed['blocker']), (409, 'preview_confirmed'))   # only the same request id may resume it
                status, resumed = self.request('/usage/reconcile/confirm', body=body)
                self.assertEqual((status, resumed['data']['action']['state']), (200, 'executed'))
                self.assertEqual(resumed['data']['replayed'], when == 'after')
                self.assertEqual(len(self.ops.writes), 1)

    def test_demo_mode_refuses_every_write_and_lists_nothing(self):
        for path, body in (('/usage/reconcile/preview', {'requestId': rid()}), ('/actions/credits/preview', {'requestId': rid()}),
                           (f'/actions/accounts/{CUSTOMER}/block/preview', {'requestId': rid()}), ('/actions/refunds/preview', {'requestId': rid()})):
            with self.subTest(path=path):
                status, refused = self.request(path + '?mode=demo', body=body)
                self.assertEqual((status, refused['code']), (400, 'VALIDATION_FAILED'))
        self.assertEqual((self.actions.rows, self.ops.writes), ({}, []))
        status, listing = self.request('/actions?mode=demo', method='GET')
        self.assertEqual((status, listing['data']['actions'], listing['dataState']), (200, [], 'unavailable'))

    # --- credits --------------------------------------------------------------------------------------------------------------
    def credit_body(self, **changes):
        body = dict(requestId=rid(), workspaceId=WS, operation='grant', milliCredits=5000, expiresAt='2026-10-21T00:00:00Z', reasonCode='goodwill')
        body.update(changes)
        return body

    def test_credits_are_refused_while_off_and_adjust_through_the_book_when_on(self):
        status, refused = self.request('/actions/credits/preview', body=self.credit_body())
        self.assertEqual((status, refused['code'], refused['blocker']), (409, 'POLICY_DISABLED', 'credits_not_enabled'))
        self.assertEqual((self.actions.rows, self.ops.writes), ({}, []))
        self.service.ledger.credits = FakeBook()
        for changes, blocker in (({'expiresAt': '2026-09-21T00:00:00Z'}, 'invalid_expiry'), ({'milliCredits': 150}, 'invalid_amount'),
                                 ({'operation': 'gift'}, 'invalid_operation'), ({'reasonCode': 'because'}, 'invalid_reason')):
            status, invalid = self.request('/actions/credits/preview', body=self.credit_body(**changes))
            self.assertEqual((status, invalid['blocker']), (400, blocker))
        status, legacy = self.request('/actions/credits/preview', body=self.credit_body(workspaceId=WS2))
        self.assertEqual((status, legacy['code'], legacy['blocker']), (409, 'POLICY_DISABLED', 'workspace_not_on_credit_terms'))
        status, preview = self.request('/actions/credits/preview', body=self.credit_body())
        self.assertEqual(status, 200, preview)
        action = preview['data']['action']
        self.assertEqual(action['current']['wallet']['availableMilliCredits'], 10000)
        self.assertEqual(action['effect']['walletAfter']['availableMilliCredits'], 15000)
        self.assertEqual((action['effect']['source'], action['effect']['consumerAudit']), ('founder_goodwill', 'credit.adjusted_by_operator'))
        status, done = self.request('/actions/credits/confirm', body=self.confirm_body(preview))
        self.assertEqual((status, done['data']['action']['state']), (200, 'executed'), done)
        self.assertEqual(self.ops.writes, [('credits', action['previewId'])])
        # Reversal beyond the grant is refused at preview; within it, the wallet after is shown.
        reverse = {k: v for k, v in self.credit_body(operation='reverse', grantId=GRANT, milliCredits=20000).items() if k != 'expiresAt'}
        status, over = self.request('/actions/credits/preview', body=reverse)
        self.assertEqual((status, over['blocker']), (409, 'reversal_exceeds_grant'))
        status, within = self.request('/actions/credits/preview', body={**reverse, 'requestId': rid(), 'milliCredits': 4000})
        self.assertEqual((status, within['data']['action']['effect']['walletAfter']['availableMilliCredits']), (200, 11000))
        # Credits switched off between preview and confirm: refused before the preview is claimed.
        _, preview = self.request('/actions/credits/preview', body=self.credit_body())
        self.service.ledger.credits = None
        status, off = self.request('/actions/credits/confirm', body=self.confirm_body(preview))
        self.assertEqual((status, off['code'], off['blocker']), (409, 'POLICY_DISABLED', 'credits_not_enabled'))
        self.assertEqual(self.actions.rows[preview['data']['action']['previewId']]['state'], 'previewed')
        self.assertEqual(len(self.ops.writes), 1)

    # --- account blocks -------------------------------------------------------------------------------------------------------
    def test_block_needs_typed_confirmation_takes_effect_and_unblock_lifts_it(self):
        path = f'/actions/accounts/{CUSTOMER}'
        body = dict(requestId=rid(), targetType='user', reasonCode='abuse', approvalRef='ticket-1042')
        status, preview = self.request(path + '/block/preview', body=body)
        self.assertEqual(status, 200, preview)
        action = preview['data']['action']
        self.assertEqual((action['targetType'], action['targetId'], action['current'], action['effect']['frozenWorkspaceIds']), ('user', CUSTOMER, {'blocked': False}, [WS]))
        self.assertEqual((action['effect']['customerCode'], action['effect']['customerMessage']), ('ACCOUNT_BLOCKED', operator_actions.MESSAGE))
        self.assertEqual((action['confirm']['requires'], action['confirm']['typedConfirmation']), (['fresh_second_factor', 'typed_confirmation'], 'BLOCK'))
        status, missing = self.request(path + '/block/confirm', body=self.confirm_body(preview))
        self.assertEqual((status, missing['blocker']), (400, 'unexpected_fields'))
        status, wrong = self.request(path + '/block/confirm', body=self.confirm_body(preview, confirmation='block'))
        self.assertEqual((status, wrong['blocker']), (400, 'typed_confirmation_required'))
        status, other = self.request(f'/actions/accounts/{OTHER}/block/confirm', body=self.confirm_body(preview, confirmation='BLOCK'))
        self.assertEqual((status, other['blocker']), (400, 'preview_mismatch'))
        self.assertEqual(self.ops.writes, [])
        status, done = self.request(path + '/block/confirm', body=self.confirm_body(preview, confirmation='BLOCK'))
        self.assertEqual((status, done['data']['action']['state'], done['data']['action']['result']['frozenWorkspaceIds']), (200, 'executed', [WS]), done)
        self.assertIn(('user', CUSTOMER), self.ops.blocks)
        self.assertNotIn(('user', OTHER), self.ops.blocks)
        status, again = self.request(path + '/block/preview', body={**body, 'requestId': rid()})
        self.assertEqual((status, again['blocker']), (409, 'already_blocked'))
        status, lift = self.request(path + '/unblock/preview', body=dict(requestId=rid(), targetType='user', reasonCode='resolved'))
        self.assertEqual((status, lift['data']['action']['current']['blocked'], lift['data']['action']['effect']['thawedWorkspaceIds']), (200, True, [WS]))
        status, lifted = self.request(path + '/unblock/confirm', body=self.confirm_body(lift))
        self.assertEqual((status, lifted['data']['action']['state']), (200, 'executed'))
        self.assertEqual(self.ops.blocks, {})
        self.assertEqual([a[0] for a in self.ops.audit], ['account.blocked', 'account.unblocked'])
        status, nothing = self.request(path + '/unblock/preview', body=dict(requestId=rid(), targetType='user', reasonCode='resolved'))
        self.assertEqual((status, nothing['blocker']), (409, 'not_blocked'))

    def test_block_refuses_the_operator_the_ops_workspace_and_an_uninstalled_table(self):
        body = dict(requestId=rid(), targetType='user', reasonCode='abuse', approvalRef='ticket-1')
        status, refused = self.request(f'/actions/accounts/{USER}/block/preview', body=body)
        self.assertEqual((status, refused['blocker']), (409, 'cannot_block_operator'))
        status, refused = self.request(f'/actions/accounts/{OPS_WS}/block/preview', body={**body, 'requestId': rid(), 'targetType': 'workspace'})
        self.assertEqual((status, refused['blocker']), (409, 'cannot_block_ops_workspace'))
        status, refused = self.request(f'/actions/accounts/{CUSTOMER}/block/preview', body={**body, 'requestId': rid(), 'approvalRef': 'customer said hi'})
        self.assertEqual((status, refused['blocker']), (400, 'invalid_approval_ref'))
        self.ops.status = 'UndefinedTable'
        status, refused = self.request(f'/actions/accounts/{CUSTOMER}/block/preview', body={**body, 'requestId': rid()})
        self.assertEqual((status, refused['code'], refused['blocker']), (409, 'POLICY_DISABLED', 'account_blocks_not_installed'))
        self.assertEqual((self.actions.rows, self.ops.writes), ({}, []))

    # --- refunds --------------------------------------------------------------------------------------------------------------
    def test_refund_preview_records_an_intent_that_cannot_execute(self):
        body = dict(requestId=rid(), workspaceId=WS, paymentIntentId='pi_fixture0001', amountMinor=1000, currency='USD', reasonCode='requested_by_customer')
        status, preview = self.request('/actions/refunds/preview', body=body)
        self.assertEqual(status, 200, preview)
        action = preview['data']['action']
        self.assertEqual((action['kind'], action['execution'], action['confirm']), ('refund_intent', {'allowed': False, 'blocker': 'refund_policy_not_decided'}, None))
        self.assertEqual((action['effect']['refundableAfterMinor'], action['effect']['providerRefundCreated']), (500, False))
        self.assertEqual(self.ops.writes, [])
        status, over = self.request('/actions/refunds/preview', body={**body, 'requestId': rid(), 'amountMinor': 1600})
        self.assertEqual((status, over['blocker']), (409, 'amount_exceeds_refundable'))
        status, missing = self.request('/actions/refunds/preview', body={**body, 'requestId': rid(), 'paymentIntentId': 'pi_missing0001'})
        self.assertEqual((status, missing['blocker']), (404, 'payment_not_found'))
        self.ops.status = 'payments_missing'
        status, off = self.request('/actions/refunds/preview', body={**body, 'requestId': rid()})
        self.assertEqual((status, off['code'], off['blocker']), (409, 'POLICY_DISABLED', 'payments_not_configured'))
        status, prohibited = self.request('/actions/refunds/confirm', body=self.confirm_body(preview))
        self.assertEqual((status, self.last_audit()['action']), (400, 'refunds.prepare'))
        # A refund intent's preview id cannot be pushed through another confirm route either.
        status, blocked = self.request('/usage/reconcile/confirm', body=self.confirm_body(preview))
        self.assertEqual((status, blocked['blocker']), (400, 'preview_mismatch'))

    def test_preview_request_ids_are_idempotent(self):
        body = dict(requestId=rid(), workspaceId=WS, reservationId=RES, outcome='failed', actualUsdMicro=4200, evidence='gateway req 3f2a91')
        status, first = self.request('/usage/reconcile/preview', body=body)
        status, again = self.request('/usage/reconcile/preview', body=body)
        self.assertEqual((status, again['data']['replayed'], again['data']['action']['previewId']), (200, True, first['data']['action']['previewId']))
        status, changed = self.request('/usage/reconcile/preview', body={**body, 'actualUsdMicro': 1})
        self.assertEqual((status, changed['code']), (409, 'IDEMPOTENCY_CONFLICT'))
        self.assertEqual(len(self.actions.rows), 1)

    # --- listing, capabilities, budget, agent ---------------------------------------------------------------------------------
    def test_get_actions_lists_recent_requests_and_active_blocks(self):
        self.reconcile_preview()
        self.time = NOW + 1
        self.request('/actions/refunds/preview', body=dict(requestId=rid(), workspaceId=WS, paymentIntentId='pi_fixture0001', amountMinor=100, currency='usd', reasonCode='other'))
        status, listing = self.request('/actions?limit=10', method='GET')
        self.assertEqual(status, 200, listing)
        self.assertEqual([a['kind'] for a in listing['data']['actions']], ['refund_intent', 'reconcile'])
        self.assertEqual(listing['data']['activeBlocks'][0]['userId'], CUSTOMER)
        self.assertEqual(listing['data']['policies'], {'creditsEnabled': False, 'refundExecution': {'allowed': False, 'confirmationRequired': True, 'blocker': 'stripe_refund_provider_not_configured'}})
        self.assertNotIn('gateway req', json.dumps(listing))   # params (the evidence reference) are never listed
        self.service.ledger.credits = FakeBook()
        self.assertTrue(self.request('/actions', method='GET')[1]['data']['policies']['creditsEnabled'])
        self.app.runtime = None   # separate mount: credits are unknown, the listing still answers
        self.assertIsNone(self.request('/actions', method='GET')[1]['data']['policies']['creditsEnabled'])
        with mock.patch.object(self.actions, 'recent', return_value=None):   # before 068 is installed: an empty, labelled list, never a failure
            status, empty = self.request('/actions', method='GET')
        self.assertEqual((status, empty['data']['actions'], empty['data']['actionsState']), (200, [], 'not_installed'))
        status, only = self.request('/actions?kind=reconcile', method='GET')
        self.assertEqual([a['kind'] for a in only['data']['actions']], ['reconcile'])
        for query in ('limit=0', 'limit=201', 'kind=refund', 'targetId=a%20b'):
            status, invalid = self.request('/actions?' + query, method='GET')
            self.assertEqual((status, invalid['code']), (400, 'VALIDATION_FAILED'), query)

    def test_capabilities_are_required_and_the_action_budget_is_used(self):
        self.budgets.clear()
        self.reconcile_preview()
        self.request('/actions', method='GET')
        self.assertEqual(self.budgets, [('founder.action', 10), ('audit.read', READ_BUDGET)])
        self.store.operator_row['capabilities'] = ['control.read', 'metrics.query', 'copilot.use']
        for path, method, capability in (('/usage/reconcile/preview', 'POST', 'usage.reconcile'), ('/actions/credits/preview', 'POST', 'credits.adjust'),
                                         (f'/actions/accounts/{CUSTOMER}/block/preview', 'POST', 'accounts.block'),
                                         ('/actions/refunds/preview', 'POST', 'refunds.prepare'), ('/actions', 'GET', 'audit.read')):
            with self.subTest(path=path):
                status, refused = self.request(path, method=method, body={'requestId': rid()} if method == 'POST' else None)
                self.assertEqual((status, refused['code'], self.last_audit()['action']), (403, 'SCOPE_DENIED', capability))
        status, refused = self.request('/usage/reconcile/preview', body={'requestId': rid()}, headers={'HTTP_X_CSRF_TOKEN': 'forged'})
        self.assertEqual((status, refused['code']), (403, 'SCOPE_DENIED'))

    def test_the_founder_agent_has_no_path_to_any_action(self):
        from postriff_phase2.agent_runtime_v2 import contracts, tool_adapter
        import rafii_control.founder_tools as founder_tools
        founder = [tool for tool in tool_adapter.REGISTRY.values() if tool.spec.tenant == 'founder']
        self.assertTrue(founder)
        for tool in founder:
            self.assertIn(tool.spec.effect, (contracts.READ, contracts.CREATE_DRAFT, contracts.PREPARE_EXTERNAL, contracts.MUTATE_REVERSIBLE), tool.name)
            self.assertNotIn(tool.executor.__module__, ('rafii_control.founder_actions', 'postriff_phase2.operator_actions'), tool.name)
            if tool.spec.effect != contracts.READ:
                self.assertNotRegex(tool.name, r'reconcile|credit|block|refund|ban', tool.name)
        self.assertNotIn('founder_actions', inspect.getsource(founder_tools))
        self.assertNotIn('operator_actions', inspect.getsource(founder_tools))
        # The actions are HTTP routes behind capabilities the agent's turn never needs.
        self.assertTrue({'usage.reconcile', 'credits.adjust', 'accounts.block', 'refunds.prepare'} <= CAPABILITIES)


if __name__ == '__main__':
    unittest.main()
