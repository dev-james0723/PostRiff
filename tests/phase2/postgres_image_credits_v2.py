"""Real owned PostgreSQL, synthetic image transport/storage; no provider calls."""
import base64
import copy
import json
import os
import time
import unittest
import uuid
from pathlib import Path

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.image_runtime import GatewayImageRuntime, ImageGenerationError
from consumer_fixtures import approve_budgets

ROOT = Path(__file__).resolve().parents[2]
NOW = int(time.time())
PORT = int(os.environ.get('POSTRIFF_TEST_PG_PORT', '55438'))
PNG = b'\x89PNG\r\n\x1a\nsynthetic'
MODEL = 'openai/gpt-image-2'


def connection():
    return psycopg.connect(f'host=127.0.0.1 port={PORT} dbname=postgres', client_encoding='utf8')


class Assets:
    def __init__(self):
        self.staged = {}

    def stage_upload(self, workspace_id, payload):
        raw = base64.b64decode(payload['data'])
        key = 'img-' + str(uuid.uuid4())
        self.staged[key] = raw
        return {'id': key, 'hash': key, 'mime': 'image/png', 'width': 1, 'height': 1,
                'bytes': len(raw), 'processing': 'decoded', 'deleted': False, 'name': 'synthetic.png'}

    def remove(self, workspace_id, asset):
        self.staged.pop(asset['id'], None)


class ImageCreditV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            assert db.info.host == '127.0.0.1' and db.info.port == PORT
            for name in ('020_credit_quotes.sql', '021_credit_purchases.sql',
                         '022_credit_payment_lifecycle.sql', '089_pricing_credit_catalog_v2.sql',
                         '090_free_lifecycle_bootstrap.sql'):
                db.execute((ROOT / 'migrations/postriff' / name).read_text())

    def setUp(self):
        self.now = [float(NOW)]
        self.actor = str(uuid.uuid4())
        self.calls = []
        self.manager_calls = []
        self.cancel_during_transport = False
        self.response = {'status': 200, 'body': {
            'data': [{'b64_json': base64.b64encode(PNG).decode()}],
            'providerMetadata': {'gateway': {'cost': 0.04, 'routing': {'finalProvider': 'openai'}}}}}
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.actor,))
            db.execute("UPDATE pr_plan_terms SET status='active',new_checkout_enabled=false WHERE id='creator-v1'")
        def verify(token):
            if token != 'synthetic':
                raise AlphaError('Verified session required.', 401)
            return self.actor
        verify.session_id = lambda token, principal: 'synthetic-image-session'
        verify.auth_time = lambda token, principal: self.now[0]
        def transport(*args, **kwargs):
            with connection() as db:
                reservations = db.execute("SELECT meta->'credits' FROM pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", (self.wid,)).fetchall()
            self.calls.append({'request': kwargs['body'], 'reservations': reservations})
            if self.cancel_during_transport:
                with connection() as db:
                    db.execute("UPDATE pr_agent_runs SET status='cancelled' WHERE workspace_id=%s AND status='running'", (self.wid,))
            return copy.deepcopy(self.response)
        self.runtime = GatewayImageRuntime('synthetic-key', MODEL, transport=transport,
            clock=lambda: self.now[0], credit_policy={
                'model': MODEL, 'provider': 'vercel-ai-gateway', 'executionProviders': ['openai'],
                'count': 1, 'size': '1024x1024', 'ceilingUsdMicro': 100_000,
                'expiresAt': NOW + 3600, 'qualification': 'operator-approved-ceiling',
                'evidenceRef': 'synthetic-fixture-v1'})
        self.service = HostedWorkspaceService(connection, verify, clock=lambda: self.now[0],
            credits_enabled=True, pricing_v2_enabled=True, image_runtime=self.runtime, assets=Assets())
        self.wid = self.service.bootstrap('synthetic')['workspaceId']
        self.conversation = self.service.ideas.create_conversation(self.wid, 'synthetic', 'Images')['conversationId']
        approve_budgets(connection, self.wid)

    def paid(self):
        with connection() as db:
            ent = db.execute("SELECT entitlements FROM pr_plan_terms WHERE id='creator-v1'").fetchone()[0]
            self.service.billing._reconcile_entitlement(db.cursor(), self.wid, 'creator-v1', ent, NOW + 600)
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,status,current_period_end,provider_subscription_id,price_variant_id) VALUES(%s,'creator-v1','stripe','active',to_timestamp(%s),%s,'creator-49-v1')", (self.wid, NOW + 600, 'sub_synthetic_' + self.wid))
            self.service.ledger._credit_book.grant(db.cursor(), self.wid, self.actor,
                                                 'synthetic-image-fund-' + self.wid, 100_000, None)

    def request(self):
        return {'text': 'A piano in a quiet room', 'imageGeneration': True, 'research': False,
                'model': 'deterministic-preview', 'confirmUse': True, 'ownContent': True}

    def quote(self, request, operation='turn', maximum=30_000):
        revision = self.service.get(self.wid, 'synthetic')['revision']
        body = {'operation': operation, 'request': request, 'expectedRevision': revision,
                'maxMilliCredits': maximum}
        if operation == 'turn':
            body['conversationId'] = self.conversation
        quote = self.service.ideas.credit_requests.issue(self.wid, 'synthetic', body)
        return {**request, 'creditQuoteId': quote['quoteId'], 'expectedRevision': revision,
                'idempotencyKey': 'image-' + str(uuid.uuid4())}

    def run_image(self, payload):
        try:
            return self.service.ideas.turn(self.wid, 'synthetic', self.conversation, payload)
        except AlphaError as error:
            self.fail('A funded, explicitly approved image must reach its own reservation: ' + str(error))

    def wallet(self):
        with connection() as db:
            return self.service.ledger._credit_book.view(db.cursor(), self.wid)

    def test_estimate_uses_image_cost_and_capability_is_actual(self):
        self.paid()
        self.assertTrue(self.service.ideas.model_catalog()['imageGeneration']['creditEstimateAvailable'])
        value = self.service.ideas.credit_requests.estimate(self.wid, 'synthetic', {
            'operation': 'turn', 'conversationId': self.conversation, 'request': self.request()})
        self.assertEqual((value['estimateMilliCredits'], value['ceilingMilliCredits']), (30_000, 30_000))
        self.assertEqual((value['model'], value['provider'], value['basis']),
                         (MODEL, 'vercel-ai-gateway', 'approved_image_ceiling'))
        self.assertEqual(self.calls, [])

    def test_quote_reserve_before_image_io_actual_settle_and_replay(self):
        self.paid()
        payload = self.quote(self.request())
        result = self.run_image(payload)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]['reservations'][0][0]['maximum'], 30_000)
        self.assertEqual((self.wallet()['heldMilliCredits'], self.wallet()['usedMilliCredits']), (0, 12_000))
        replay = self.run_image(payload)
        self.assertEqual(replay['runId'], result['runId'])
        self.assertEqual(len(self.calls), 1)

    def test_low_maximum_and_unapproved_image_never_dispatch(self):
        self.paid()
        with self.assertRaises(AlphaError):
            self.quote(self.request(), maximum=29_900)
        with self.assertRaises(AlphaError):
            self.service.ideas.turn(self.wid, 'synthetic', self.conversation, self.request())
        self.assertEqual(self.calls, [])

    def test_known_failed_image_cost_is_platform_loss_customer_zero(self):
        self.paid()
        self.response['body']['providerMetadata']['gateway']['routing']['finalProvider'] = 'runware'
        payload = self.quote(self.request())
        try:
            self.service.ideas.turn(self.wid, 'synthetic', self.conversation, payload)
        except ImageGenerationError:
            pass
        except AlphaError as error:
            self.fail('The known provider failure must reach reservation settlement: ' + str(error))
        else:
            self.fail('An unapproved serving provider must be refused')
        self.assertEqual((self.wallet()['heldMilliCredits'], self.wallet()['usedMilliCredits']), (0, 0))
        self.assertEqual(len(self.calls), 1)
        with connection() as db:
            cost = db.execute("SELECT actual_usd_micro FROM pr_usage_ledger WHERE workspace_id=%s AND kind='release'", (self.wid,)).fetchone()
        self.assertEqual(cost, (40_000,))
        self.assertEqual(self.service.ideas.assets.staged, {})

    def test_unknown_cost_holds_and_over_max_is_absorbed(self):
        self.paid()
        self.response['body']['providerMetadata']['gateway']['cost'] = None
        self.run_image(self.quote(self.request()))
        self.assertEqual((self.wallet()['heldMilliCredits'], self.wallet()['usedMilliCredits']), (30_000, 0))
        self.response['body']['providerMetadata']['gateway']['cost'] = 0.2
        self.run_image(self.quote(self.request()))
        self.assertEqual((self.wallet()['heldMilliCredits'], self.wallet()['usedMilliCredits']), (30_000, 30_000))

    def test_late_cancelled_cost_settles_without_reviving_content(self):
        self.paid()
        payload = self.quote(self.request())
        self.cancel_during_transport = True
        with self.assertRaises(AlphaError):
            self.service.ideas.turn(self.wid, 'synthetic', self.conversation, payload)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual((self.wallet()['heldMilliCredits'], self.wallet()['usedMilliCredits']), (0, 0))
        with connection() as db:
            self.assertEqual(db.execute('SELECT status FROM pr_agent_runs WHERE workspace_id=%s', (self.wid,)).fetchone(), ('cancelled',))
            self.assertEqual(db.execute("SELECT actual_usd_micro FROM pr_usage_ledger WHERE workspace_id=%s AND kind='release'", (self.wid,)).fetchone(), (40_000,))
        self.assertEqual(self.service.ideas.assets.staged, {})

    def reserve_guarded(self):
        self.paid()
        payload = self.quote(self.request())
        authority = self.service.ideas.credit_requests.authorize(self.wid, 'synthetic', payload['expectedRevision'], payload, 'turn', self.conversation)
        with connection() as db:
            value = self.service.ledger.reserve(db.cursor(), self.wid, self.actor, 'image_generation', 100_000, 'guard-' + str(uuid.uuid4()), charge_batch=True, provider='vercel-ai-gateway', model=MODEL, credit_authority=authority)
        return value['reservationId']

    def guard_call(self, reservation, **changes):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('postriff_phase2.credit_task_guard'), 'Managed attempts need the actual persisted credit funding guard')
        from postriff_phase2.credit_task_guard import guard_credit_call
        values = {'next_usd_micro': 30_000, 'spent_usd_micro': 40_000, 'unknown': False, 'model': MODEL, 'provider': 'vercel-ai-gateway'}
        guard_credit_call(self.service.ledger, connection, self.wid, reservation, **{**values, **changes})

    def test_credit_guard_validates_current_active_policy(self):
        reservation = self.reserve_guarded()
        self.guard_call(reservation)
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='retired' WHERE id='creator-v1'")
        with self.assertRaises(AlphaError):
            self.guard_call(reservation)
        self.assertEqual(self.calls, [])

    def test_credit_guard_unknown_over_max_and_route_mismatch(self):
        reservation = self.reserve_guarded()
        self.guard_call(reservation, next_usd_micro=100_000, spent_usd_micro=0)
        for changes in ({'unknown': True}, {'next_usd_micro': 30_000, 'spent_usd_micro': 80_000}, {'model': 'wrong/image'}, {'provider': 'wrong'}):
            with self.subTest(changes=changes), self.assertRaises(AlphaError):
                self.guard_call(reservation, **changes)
        self.assertEqual(self.wallet()['heldMilliCredits'], 30_000)
        self.assertEqual(self.calls, [])

    def test_credit_guard_refuses_changed_budget(self):
        reservation = self.reserve_guarded()
        with connection() as db:
            db.execute("UPDATE pr_budgets SET stop_usd_micro=50_000,warn_usd_micro=40_000 WHERE scope=%s", ('workspace:' + self.wid,))
        with self.assertRaises(AlphaError):
            self.guard_call(reservation)
        self.assertEqual(self.calls, [])

    def test_credit_guard_refuses_known_or_unknown_terminal_attempt(self):
        reservation = self.reserve_guarded()
        with connection() as db:
            self.service.ledger.settle(db.cursor(), self.wid, reservation, 'unknown', None)
        with self.assertRaises(AlphaError):
            self.guard_call(reservation)
        self.assertEqual(self.wallet()['heldMilliCredits'], 30_000)
        with connection() as db:
            self.service.ledger.settle(db.cursor(), self.wid, reservation, 'failed', 40_000)
        with self.assertRaises(AlphaError):
            self.guard_call(reservation)
        self.assertEqual(self.wallet()['heldMilliCredits'], 0)
        self.assertEqual(self.calls, [])

    def test_image_rechecks_funding_immediately_before_transport(self):
        self.paid()
        payload = self.quote(self.request())
        generate = self.runtime.generate
        def changed_budget(*args, **kwargs):
            with connection() as db:
                db.execute("UPDATE pr_budgets SET stop_usd_micro=50_000,warn_usd_micro=40_000 WHERE scope=%s", ('workspace:' + self.wid,))
            return generate(*args, **kwargs)
        self.runtime.generate = changed_budget
        with self.assertRaises(AlphaError):
            self.service.ideas.turn(self.wid, 'synthetic', self.conversation, payload)
        self.assertEqual(self.calls, [])
        self.assertEqual((self.wallet()['heldMilliCredits'], self.wallet()['usedMilliCredits']), (0, 0))

    def managed_writer(self, cost=0.004, *, unknown=False, tighten=False):
        from postriff_phase2.model_runtime import ServerModelRuntime
        self.paid()
        model = 'test/credit-writer'
        attempts = []
        def transport(method, url, **kwargs):
            with connection() as db:
                held = db.execute("SELECT meta->'credits'->>'maximum' FROM pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", (self.wid,)).fetchone()
                if tighten:
                    db.execute("UPDATE pr_budgets SET stop_usd_micro=50_000,warn_usd_micro=40_000 WHERE scope=%s", ('workspace:' + self.wid,))
            attempts.append({'held': held, 'request': kwargs['body']})
            first = len(attempts) == 1
            usage = {'providerMetadata': {'gateway': {'cost': None if unknown else cost if first else 0.003, 'routing': {'finalProvider': 'test'}}}}
            choices = [] if first else [{'message': {'content': json.dumps({'variants': [{'platform': 'LinkedIn', 'language': 'en-US', 'text': 'Synthetic writer candidate.', 'sourceIds': [], 'unknowns': [], 'warnings': []}]})}}]
            return {'status': 200, 'body': {**usage, 'choices': choices}}
        writer = ServerModelRuntime('synthetic-key', model=model, models=[model], prices={model: (2, 2)}, transport=transport)
        self.service.ideas.runtimes.append(writer)
        request = {'text': 'A small creative habit.', 'model': model, 'research': False, 'reasoning': 'quick', 'destinations': [{'platform': 'LinkedIn', 'language': 'en-US'}]}
        return self.quote(request, maximum=80_000), attempts

    def test_actual_writer_retry_charges_all_known_physical_attempts_once(self):
        payload, attempts = self.managed_writer()
        try:
            result = self.service.ideas.turn(self.wid, 'synthetic', self.conversation, payload)
        except AlphaError as error:
            self.fail('Known bounded retries must use the actual committed credit hold: ' + str(error))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(attempts), 2)
        self.assertEqual([a['held'] for a in attempts], [('80000',), ('80000',)])
        self.assertEqual((self.wallet()['heldMilliCredits'], self.wallet()['usedMilliCredits']), (0, 2100))
        replay = self.service.ideas.turn(self.wid, 'synthetic', self.conversation, payload)
        self.assertEqual(replay['runId'], result['runId'])
        self.assertEqual(len(attempts), 2)

    def test_actual_writer_unknown_stops_without_additional_io(self):
        payload, attempts = self.managed_writer(unknown=True)
        with self.assertRaises(AlphaError):
            self.service.ideas.turn(self.wid, 'synthetic', self.conversation, payload)
        self.assertEqual(len(attempts), 1)
        self.assertEqual((self.wallet()['heldMilliCredits'], self.wallet()['usedMilliCredits']), (80_000, 0))

    def test_actual_writer_tightened_budget_stops_and_keeps_known_failed_cost(self):
        payload, attempts = self.managed_writer(tighten=True)
        with self.assertRaises(AlphaError):
            self.service.ideas.turn(self.wid, 'synthetic', self.conversation, payload)
        self.assertEqual(len(attempts), 1)
        self.assertEqual((self.wallet()['heldMilliCredits'], self.wallet()['usedMilliCredits']), (0, 0))
        with connection() as db:
            self.assertEqual(db.execute("SELECT actual_usd_micro FROM pr_usage_ledger WHERE workspace_id=%s AND kind='release'", (self.wid,)).fetchone(), (4000,))

    def test_free_has_no_general_paid_image_funding(self):
        with self.assertRaises(AlphaError):
            self.service.ideas.turn(self.wid, 'synthetic', self.conversation, self.request())
        self.assertEqual(self.calls, [])

    def test_quick_start_image_never_dispatches_unquoted_manager(self):
        self.paid()
        original = self.service.ideas._understand
        def understand(*args, **kwargs):
            self.manager_calls.append(True)
            return original(*args, **kwargs)
        self.service.ideas._understand = understand
        payload = self.quote(self.request(), operation='quick-start')
        try:
            result = self.service.ideas.quick_start(self.wid, 'synthetic', payload['expectedRevision'], payload)
        except AlphaError as error:
            self.fail('Qualified image quick-start must use its image approval: ' + str(error))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.manager_calls, [])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.wallet()['usedMilliCredits'], 12_000)

    def test_unqualified_or_repriced_quote_is_refused_before_io(self):
        self.paid()
        payload = self.quote(self.request())
        self.runtime.credit_policy['ceilingUsdMicro'] = 200_000
        with self.assertRaises(AlphaError):
            self.service.ideas.turn(self.wid, 'synthetic', self.conversation, payload)
        self.runtime.credit_policy = None
        with self.assertRaises(AlphaError):
            self.service.ideas.credit_requests.estimate(self.wid, 'synthetic', {
                'operation': 'turn', 'conversationId': self.conversation, 'request': self.request()})
        self.assertFalse(self.service.ideas.model_catalog()['imageGeneration']['creditEstimateAvailable'])
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
