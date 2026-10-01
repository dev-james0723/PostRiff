"""Founder actions on disposable PostgreSQL (CONTRACTS §8.F): 062 + 068 applied twice by scripts/rafii_control_pg.py.

The real Control boundary, the restricted session/reader roles, the real consumer SQL (postriff_phase2.operator_actions,
billing.Ledger) and the real enforcement points (session verifier, repository transaction, worker predicate) run end to
end: a block takes effect and an unblock lifts it without touching another account; reconcile executes once with both
audits; refusals change nothing; one founder cannot claim another's preview.
"""
import base64
import hashlib
import io
import json
import os
import re
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import psycopg

from postriff_alpha.domain import AlphaError
from postriff_phase2 import operator_actions
from postriff_phase2.billing import Ledger
from postriff_phase2.hosted import PostgresWorkspaceRepository
from postriff_phase2.hosted_app import supabase_verifier
from rafii_control import founder_actions
from rafii_control.auth import Boundary, CAPABILITIES, Config, VerifiedIdentity
from rafii_control.http import ControlApplication
from rafii_control.intelligence import QueryService
from rafii_control.store import PostgresStore, connection_factory

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = 'http://localhost:4449'


def jwt(user):
    payload = {'sub': user, 'session_id': 'session-1234567890', 'aal': 'aal1'}
    return 'header.' + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=') + '.signature'


def get_user(url, token):
    payload = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '=='))
    return {'status': 200, 'body': {'id': payload['sub'], 'email_confirmed_at': '2026-09-01T00:00:00Z'}}


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable database required')
class FounderActionsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        operator_actions._STATE.update(status=None, checked=0.0, logged=False)
        with psycopg.connect(self.dsn, autocommit=True) as con:
            self.operator, self.operator_ws = self.person(con)
            self.customer, self.customer_ws = self.person(con)
            self.other, self.other_ws = self.person(con)
            con.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s)",
                        (self.operator, sorted(CAPABILITIES)))
        self.store = PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), 'local')
        self.now = self.mfa = time.time()   # founder_sessions: mfa_at <= created_at
        self.boundary = Boundary(Config(True, 'local', ORIGIN), self.store,
                                 lambda token: VerifiedIdentity(self.operator, 'aal2', 'synthetic-session-' + self.operator, self.mfa), clock=lambda: self.now)
        self.consumer = lambda: psycopg.connect(self.dsn, prepare_threshold=None)
        self.service = SimpleNamespace(connection_factory=self.consumer, ledger=Ledger(credits_enabled=False), clock=time.time)
        self.app = ControlApplication(self.boundary, QueryService(self.store), runtime=lambda: self.service, flags={})
        self.sign_in()

    def tearDown(self):
        operator_actions._STATE.update(status=None, checked=0.0, logged=False)
        with psycopg.connect(self.dsn, autocommit=True) as con:
            con.execute('DELETE FROM rafii_control.request_budgets WHERE bucket=%s', (hashlib.sha256(b'exchange:global').hexdigest(),))
            # The ledger is shared by every PostgreSQL test module; reservations seeded here (unknown-cost ones included)
            # must not leak into later modules' all-workspace metric totals.
            users = [user for user in (getattr(self, 'operator', None), getattr(self, 'customer', None), getattr(self, 'other', None)) if user]
            workspaces = [ws for ws in (getattr(self, 'operator_ws', None), getattr(self, 'customer_ws', None), getattr(self, 'other_ws', None)) if ws]
            con.execute('DELETE FROM public.pr_usage_ledger WHERE workspace_id = ANY(%s::uuid[])', (workspaces,))
            if con.execute("SELECT to_regclass('public.pr_account_blocks') IS NOT NULL").fetchone()[0]:
                con.execute('DELETE FROM public.pr_account_blocks WHERE user_id = ANY(%s::uuid[]) OR workspace_id = ANY(%s::uuid[])', (users, workspaces))

    @staticmethod
    def person(con):
        user = str(uuid.uuid4())
        con.execute('INSERT INTO auth.users(id) VALUES(%s)', (user,))
        workspace = str(con.execute("SELECT public.pr_bootstrap(%s,'studio')", (user,)).fetchone()[0])
        return user, workspace

    def sign_in(self):
        self.token, session = self.boundary.exchange('synthetic-identity', ORIGIN)
        self.csrf = session['csrfToken']

    def request(self, path, method='POST', body=None):
        raw = json.dumps(body).encode() if body is not None else b''
        path, _, query = path.partition('?')
        env = dict(PATH_INFO='/api/control/v2' + path, QUERY_STRING=query, REQUEST_METHOD=method, CONTENT_LENGTH=str(len(raw)), CONTENT_TYPE='application/json',
                   HTTP_HOST='localhost:4449', HTTP_ORIGIN=ORIGIN, HTTP_COOKIE='__Host-rafii-control=' + self.token, HTTP_X_CSRF_TOKEN=self.csrf,
                   **{'wsgi.input': io.BytesIO(raw)})
        response = {}
        result = json.loads(b''.join(self.app(env, lambda status, headers: response.update(status=int(status[:3])))))
        return response['status'], result

    @staticmethod
    def confirm(preview, **extra):
        action = preview['data']['action']
        return {'previewId': action['previewId'], 'revision': action['revision'], 'requestId': str(uuid.uuid4()), **extra}

    def query(self, sql, params=()):
        with psycopg.connect(self.dsn) as con:
            return con.execute(sql, params).fetchall()

    def state(self, workspace):
        return self.query('SELECT state,revision FROM public.pr_workspaces WHERE id=%s', (workspace,))[0]

    def enter(self, user, workspace):
        with PostgresWorkspaceRepository(self.consumer, lambda token: user).transaction('session-token', workspace) as (_, _, principal):
            return principal

    def assert_blocked(self, call):
        with self.assertRaises(AlphaError) as refused:
            call()
        self.assertEqual((refused.exception.status, refused.exception.code, str(refused.exception)), (403, 'ACCOUNT_BLOCKED', operator_actions.MESSAGE))

    # --- schema ------------------------------------------------------------------------------------------------------------
    def test_migrations_keep_the_public_fence_apart_from_control_and_lock_down_grants(self):
        sql = (ROOT / 'migrations/postriff/062_founder_admin_actions.sql').read_text()
        self.assertNotIn('rafii_control', '\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('--')))
        for text in (sql, (ROOT / 'migrations/postriff/068_founder_actions_views.sql').read_text()):
            self.assertIsNone(re.search(r'grant\s+[a-z_]+\s+to\s+(current_user|session_user)', text, re.I))   # no role membership for the runner
        flags = self.query("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid IN ('public.pr_account_blocks'::regclass,'rafii_control.founder_action_requests'::regclass)")
        self.assertEqual(flags, [(True, True), (True, True)])
        privilege = lambda role, table, kind: self.query('SELECT has_table_privilege(%s,%s,%s)', (role, table, kind))[0][0]
        column = lambda role, name, kind: self.query("SELECT has_column_privilege(%s,'rafii_control.founder_action_requests',%s,%s)", (role, name, kind))[0][0]
        self.assertFalse(privilege('authenticated', 'public.pr_account_blocks', 'SELECT'))
        self.assertFalse(privilege('anon', 'public.pr_account_blocks', 'SELECT'))
        self.assertTrue(privilege('service_role', 'public.pr_account_blocks', 'INSERT'))
        self.assertFalse(privilege('rafii_control_reader', 'rafii_control.founder_action_requests', 'SELECT'))
        self.assertFalse(privilege('rafii_control_session', 'public.pr_account_blocks', 'SELECT'))
        self.assertTrue(privilege('rafii_control_session', 'rafii_control.founder_action_requests', 'INSERT'))
        self.assertTrue(column('rafii_control_session', 'state', 'UPDATE'))
        for frozen in ('params', 'preview', 'revision', 'operator_id', 'kind', 'target_id', 'request_id', 'expires_at'):
            self.assertFalse(column('rafii_control_session', frozen, 'UPDATE'), frozen)
        self.assertTrue(privilege('rafii_control_reader', 'rafii_control.business_account_blocks', 'SELECT'))
        columns = [r[0] for r in self.query("SELECT column_name FROM information_schema.columns WHERE table_schema='rafii_control' AND table_name='business_account_blocks' ORDER BY ordinal_position")]
        self.assertEqual(columns, ['id', 'userId', 'workspaceId', 'reasonCode', 'blockedAt', 'liftedAt', 'active'])
        with psycopg.connect(self.dsn) as con:
            for values in ((self.customer, self.customer_ws, 'abuse', 'ticket-1'), (None, None, 'abuse', 'ticket-1'), (self.customer, None, 'abuse', 'free text with spaces'),
                           (self.customer, None, 'nonsense', 'ticket-1')):
                with self.subTest(values=values), self.assertRaises(psycopg.errors.CheckViolation):
                    with con.transaction():
                        con.execute('INSERT INTO public.pr_account_blocks(user_id,workspace_id,reason_code,approval_ref,blocked_by,block_action_id) VALUES(%s,%s,%s,%s,%s,%s)',
                                    (*values, self.operator, str(uuid.uuid4())))

    # --- account blocks ---------------------------------------------------------------------------------------------------
    def test_user_block_takes_effect_everywhere_and_unblock_lifts_it_without_touching_others(self):
        verify = supabase_verifier('https://project.supabase.co', 'p' * 24, self.consumer, get_user=get_user)
        self.assertEqual(verify(jwt(self.customer)), self.customer)
        path = f'/actions/accounts/{self.customer}'
        status, preview = self.request(path + '/block/preview', body={'requestId': str(uuid.uuid4()), 'targetType': 'user', 'reasonCode': 'abuse', 'approvalRef': 'ticket-1042'})
        self.assertEqual(status, 200, preview)
        action = preview['data']['action']
        self.assertEqual((action['effect']['frozenWorkspaceIds'], action['effect']['sessionsRefused'], action['current']), ([self.customer_ws], True, {'blocked': False}))
        blocks = lambda: self.query('SELECT count(*) FROM public.pr_account_blocks WHERE user_id=%s', (self.customer,))[0][0]
        self.assertEqual(blocks(), 0)
        before = self.state(self.customer_ws)
        self.assertNotIn('accountBlock', before[0])
        status, stale = self.request(path + '/block/confirm', body=self.confirm(preview, revision='0' * 16, confirmation='BLOCK'))
        self.assertEqual((status, stale['code'], stale['blocker']), (409, 'STALE_PREVIEW', 'revision_mismatch'))
        status, untyped = self.request(path + '/block/confirm', body=self.confirm(preview))
        self.assertEqual(status, 400)
        self.assertEqual(blocks(), 0)
        body = self.confirm(preview, confirmation='BLOCK')
        status, done = self.request(path + '/block/confirm', body=body)
        self.assertEqual((status, done['data']['action']['state']), (200, 'executed'), done)
        block = self.query('SELECT id::text,user_id::text,workspace_id,frozen_workspace_ids::text[],blocked_by::text,block_action_id::text,lifted_at,reason_code,approval_ref '
                           'FROM public.pr_account_blocks WHERE user_id=%s', (self.customer,))
        self.assertEqual(len(block), 1)
        block_id = block[0][0]
        self.assertEqual(block[0][1:], (self.customer, None, [self.customer_ws], self.operator, action['previewId'], None, 'abuse', 'ticket-1042'))
        frozen = self.state(self.customer_ws)
        self.assertEqual((frozen[0]['accountBlock'], frozen[1]), ({'blockIds': [block_id]}, before[1] + 1))
        audit = self.query("SELECT workspace_id,actor,subject,meta FROM public.pr_audit_events WHERE kind='account.blocked' AND subject=%s", (block_id,))
        self.assertEqual(audit, [(None, None, block_id, {'scope': 'user', 'reasonCode': 'abuse', 'frozenWorkspaces': 1, 'operator': 'founder-action:' + action['previewId']})])
        control = self.query('SELECT action,result FROM rafii_control.admin_audit_log WHERE request_id=%s', (done['requestId'],))
        self.assertEqual(sorted(control), [('accounts.block', 'allowed'), ('accounts.block', 'succeeded')])
        stored = self.query('SELECT state,confirm_audit_id::text,preview_audit_id::text FROM rafii_control.founder_action_requests WHERE id=%s', (action['previewId'],))
        self.assertEqual(stored, [('executed', done['requestId'], preview['requestId'])])
        status, again = self.request(path + '/block/confirm', body=body)
        self.assertEqual((status, again['data']['replayed']), (200, True))
        self.assertEqual(blocks(), 1)
        # Enforcement: session, workspace transaction, worker predicate; the other account is untouched.
        self.assert_blocked(lambda: verify(jwt(self.customer)))
        self.assertEqual(verify(jwt(self.other)), self.other)
        self.assert_blocked(lambda: self.enter(self.customer, self.customer_ws))
        self.assertEqual(self.enter(self.other, self.other_ws), self.other)
        claimable = "SELECT id::text FROM public.pr_workspaces WHERE id IN (%s,%s) AND NOT state ? 'accountDeletion' AND NOT state ? 'accountBlock' ORDER BY id"
        self.assertEqual(self.query(claimable, (self.customer_ws, self.other_ws)), [(self.other_ws,)])
        status, listing = self.request('/actions', method='GET')
        self.assertEqual(status, 200, listing)
        self.assertEqual([b['userId'] for b in listing['data']['activeBlocks'] if b['userId'] in (self.customer, self.other)], [self.customer])
        # Unblock: preview, confirm, everything restored.
        status, lift = self.request(path + '/unblock/preview', body={'requestId': str(uuid.uuid4()), 'targetType': 'user', 'reasonCode': 'resolved'})
        self.assertEqual((status, lift['data']['action']['current']['blockId']), (200, block_id), lift)
        status, lifted = self.request(path + '/unblock/confirm', body=self.confirm(lift))
        self.assertEqual((status, lifted['data']['action']['state']), (200, 'executed'), lifted)
        row = self.query('SELECT lifted_by::text,lift_action_id::text,lift_reason_code,retain_until-lifted_at FROM public.pr_account_blocks WHERE id=%s', (block_id,))[0]
        self.assertEqual(row[:3], (self.operator, lift['data']['action']['previewId'], 'resolved'))
        self.assertEqual(row[3].days, 400)
        self.assertNotIn('accountBlock', self.state(self.customer_ws)[0])
        self.assertEqual(self.query("SELECT count(*) FROM public.pr_audit_events WHERE kind='account.unblocked' AND subject=%s", (block_id,))[0][0], 1)
        self.assertEqual(verify(jwt(self.customer)), self.customer)
        self.assertEqual(self.enter(self.customer, self.customer_ws), self.customer)
        status, listing = self.request('/actions', method='GET')
        self.assertNotIn(self.customer, [b['userId'] for b in listing['data']['activeBlocks']])

    def test_workspace_block_freezes_only_that_workspace(self):
        verify = supabase_verifier('https://project.supabase.co', 'p' * 24, self.consumer, get_user=get_user)
        path = f'/actions/accounts/{self.other_ws}'
        status, preview = self.request(path + '/block/preview', body={'requestId': str(uuid.uuid4()), 'targetType': 'workspace', 'reasonCode': 'spam', 'approvalRef': 'case-7'})
        self.assertEqual(status, 200, preview)
        status, done = self.request(path + '/block/confirm', body=self.confirm(preview, confirmation='BLOCK'))
        self.assertEqual((status, done['data']['action']['state']), (200, 'executed'), done)
        self.assert_blocked(lambda: self.enter(self.other, self.other_ws))
        self.assertEqual(verify(jwt(self.other)), self.other)   # the person is not blocked, only that workspace
        self.assertEqual(self.enter(self.customer, self.customer_ws), self.customer)
        self.assertEqual(self.query("SELECT workspace_id::text FROM public.pr_audit_events WHERE kind='account.blocked' AND workspace_id=%s", (self.other_ws,)), [(self.other_ws,)])
        status, lift = self.request(path + '/unblock/preview', body={'requestId': str(uuid.uuid4()), 'targetType': 'workspace', 'reasonCode': 'mistake'})
        status, lifted = self.request(path + '/unblock/confirm', body=self.confirm(lift))
        self.assertEqual((status, lifted['data']['action']['state']), (200, 'executed'), lifted)
        self.assertEqual(self.enter(self.other, self.other_ws), self.other)

    # --- reconcile ----------------------------------------------------------------------------------------------------------
    def test_reconcile_executes_once_with_both_audits_and_refusals_change_nothing(self):
        with psycopg.connect(self.dsn) as con:
            reservation = con.execute("INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,provider,model,estimated_usd_micro,cost_state,idempotency_key,meta) "
                                      "VALUES(%s,'reserve','text_model','gateway','writer-model',5000,'estimated',%s,'{\"budgetScopes\":[]}'::jsonb) RETURNING id::text",
                                      (self.customer_ws, 'run:pg-' + uuid.uuid4().hex)).fetchone()[0]
            con.execute('UPDATE public.pr_usage_ledger SET reservation_id=id WHERE id=%s', (reservation,))
            con.execute("INSERT INTO public.pr_usage_ledger(workspace_id,reservation_id,kind,dimension,provider,model,estimated_usd_micro,cost_state,idempotency_key) "
                        "VALUES(%s,%s,'settle','text_model','gateway','writer-model',5000,'estimated_unknown',%s)", (self.customer_ws, reservation, f'settle:{reservation}:unknown'))
        body = {'requestId': str(uuid.uuid4()), 'workspaceId': self.customer_ws, 'reservationId': reservation, 'outcome': 'failed', 'actualUsdMicro': 4200,
                'evidence': 'gateway req 3f2a91'}
        status, preview = self.request('/usage/reconcile/preview', body=body)
        self.assertEqual(status, 200, preview)
        self.assertEqual((preview['data']['action']['current']['estimatedUsdMicro'], preview['data']['action']['effect']['providerCostBookedUsdMicro']), (5000, 4200))
        # Credits are off and the payment tables are absent here: both refuse honestly, nothing is recorded.
        expires = datetime.fromtimestamp(self.now + 30 * 86400, timezone.utc).isoformat()
        status, credits = self.request('/actions/credits/preview', body={'requestId': str(uuid.uuid4()), 'workspaceId': self.customer_ws, 'operation': 'grant',
                                                                         'milliCredits': 1000, 'expiresAt': expires, 'reasonCode': 'goodwill'})
        self.assertEqual((status, credits['code'], credits['blocker']), (409, 'POLICY_DISABLED', 'credits_not_enabled'))
        status, refund = self.request('/actions/refunds/preview', body={'requestId': str(uuid.uuid4()), 'workspaceId': self.customer_ws, 'paymentIntentId': 'pi_pg0001',
                                                                        'amountMinor': 100, 'currency': 'usd', 'reasonCode': 'other'})
        self.assertEqual((status, refund['code'], refund['blocker']), (409, 'POLICY_DISABLED', 'payments_not_configured'))
        self.assertEqual(self.query('SELECT kind FROM rafii_control.founder_action_requests WHERE operator_id=%s', (self.operator,)), [('reconcile',)])
        settled = "SELECT cost_state,actual_usd_micro,idempotency_key FROM public.pr_usage_ledger WHERE reservation_id=%s AND cost_state IN ('actual','released')"
        status, wrong = self.request('/usage/reconcile/confirm', body=self.confirm(preview, revision='0' * 16))
        self.assertEqual((status, wrong['blocker']), (409, 'revision_mismatch'))
        self.assertEqual(self.query(settled, (reservation,)), [])
        confirm = self.confirm(preview)
        status, done = self.request('/usage/reconcile/confirm', body=confirm)
        self.assertEqual((status, done['data']['action']['state'], done['data']['action']['result']['state']), (200, 'executed', 'released'), done)
        self.assertEqual(self.query(settled, (reservation,)), [('released', 4200, f'reconcile:{reservation}')])
        audit = self.query("SELECT actor,meta FROM public.pr_audit_events WHERE kind='usage.reconciled' AND subject=%s", (reservation,))
        self.assertEqual(audit, [(None, {'outcome': 'failed', 'actualUsdMicro': 4200, 'operator': 'founder-action:' + preview['data']['action']['previewId'],
                                        'evidence': 'gateway req 3f2a91'})])
        status, again = self.request('/usage/reconcile/confirm', body=confirm)
        self.assertEqual((status, again['data']['replayed']), (200, True))
        self.assertEqual(len(self.query(settled, (reservation,))), 1)
        status, waiting = self.request('/usage/reconcile/preview', body={**body, 'requestId': str(uuid.uuid4())})
        self.assertEqual((status, waiting['blocker']), (409, 'not_waiting_for_reconciliation'))

    def test_expired_previews_and_foreign_operators_are_refused(self):
        with psycopg.connect(self.dsn) as con:
            reservation = con.execute("INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,estimated_usd_micro,cost_state,idempotency_key,meta) "
                                      "VALUES(%s,'reserve','text_model',700,'estimated',%s,'{}'::jsonb) RETURNING id::text", (self.other_ws, 'run:pg-' + uuid.uuid4().hex)).fetchone()[0]
            con.execute('UPDATE public.pr_usage_ledger SET reservation_id=id WHERE id=%s', (reservation,))
            con.execute("INSERT INTO public.pr_usage_ledger(workspace_id,reservation_id,kind,dimension,estimated_usd_micro,cost_state,idempotency_key) "
                        "VALUES(%s,%s,'settle','text_model',700,'estimated_unknown',%s)", (self.other_ws, reservation, f'settle:{reservation}:unknown'))
        status, preview = self.request('/usage/reconcile/preview', body={'requestId': str(uuid.uuid4()), 'workspaceId': self.other_ws, 'reservationId': reservation,
                                                                         'outcome': 'completed', 'actualUsdMicro': 650, 'evidence': 'gateway-req-77'})
        self.assertEqual(status, 200, preview)
        preview_id = preview['data']['action']['previewId']
        # Another founder (same environment) cannot see past the operator GUC policy to claim it.
        with psycopg.connect(self.dsn, autocommit=True) as con:
            second, _ = self.person(con)
            con.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s)", (second, sorted(CAPABILITIES)))
        decide = founder_actions._decide(founder_actions.RECONCILE, request_id=str(uuid.uuid4()), revision=preview['data']['action']['revision'], target_id=None,
                                         audit_id=str(uuid.uuid4()), now=self.now)
        with self.assertRaises(founder_actions.ActionError) as foreign:
            founder_actions.ActionStore(self.store).claim(second, preview_id, str(uuid.uuid4()), decide)
        self.assertEqual((foreign.exception.status, foreign.exception.blocker), (404, 'preview_not_found'))
        # Five minutes later: step-up first, then (with a fresh second factor) the preview has expired. Nothing executes.
        self.now += 301
        status, refused = self.request('/usage/reconcile/confirm', body=self.confirm(preview))
        self.assertEqual((status, refused['code']), (403, 'STEP_UP_REQUIRED'))
        self.mfa = self.now
        self.sign_in()
        status, expired = self.request('/usage/reconcile/confirm', body=self.confirm(preview))
        self.assertEqual((status, expired['code'], expired['blocker']), (409, 'STALE_PREVIEW', 'preview_expired'))
        self.assertEqual(self.query("SELECT count(*) FROM public.pr_usage_ledger WHERE reservation_id=%s AND cost_state IN ('actual','released')", (reservation,))[0][0], 0)
        self.assertEqual(self.query('SELECT state FROM rafii_control.founder_action_requests WHERE id=%s', (preview_id,)), [('previewed',)])
        summary = founder_actions.retention_stage(SimpleNamespace(store=self.store), self.service, {}, self.now)
        self.assertGreaterEqual(summary['expiredPreviews'], 1)
        self.assertEqual(self.query('SELECT state FROM rafii_control.founder_action_requests WHERE id=%s', (preview_id,)), [('expired',)])
        status, listing = self.request('/actions?kind=reconcile', method='GET')
        self.assertIn(preview_id, [a['previewId'] for a in listing['data']['actions'] if a['state'] == 'expired'])


if __name__ == '__main__':
    unittest.main()
