"""Task5 real Growth/ledger on disposable PG17; injected Gateway transport only."""
import json
import os
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.service import GrowthService, ROUTES
from postriff_phase2.model_runtime import ServerModelRuntime
from postriff_phase2.hosted import HostedWorkspaceService
from growth_phase1_fixtures import ENV, Models

ROOT = Path(__file__).resolve().parents[2]
DSN = 'host=127.0.0.1 port=55438 dbname=postgres'
MODEL = 'google/gemini-2.5-flash-lite'
POLICY = {'approved': True, 'id': 'synthetic-task5', 'model': MODEL, 'provider': 'vercel-ai-gateway',
          'executionProvider': 'google', 'attemptMaxUsdMicro': 20000, 'dailyUsdMicro': 2000000,
          'monthlyUsdMicro': 4000000, 'dailyRuns': 100, 'workspaceDailyRuns': 2,
          'maxInputBytes': 64000, 'maxOutputTokens': 1500, 'paidBaseChecks': False}

def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            assert db.info.host == '127.0.0.1' and db.info.port == 55438
            for name in ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql',
                         '048_pricing_credit_catalog_v2.sql', '050_free_lifecycle_bootstrap.sql'):
                db.execute((ROOT / 'migrations/postriff' / name).read_text())

    def setUp(self):
        self.now = [time.time()]
        self.actor = str(uuid.uuid4())
        self.sent = []
        self.cost = .004
        self.malformed = False
        self.timeout = False
        self.before = None
        self.answers = Models()
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.actor,))
            db.execute("DELETE FROM pr_growth_budgets WHERE scope LIKE 'platform-preview:%'")
            db.execute("DELETE FROM pr_budgets WHERE scope LIKE 'platform-preview:%'")
        def verify(token):
            if token != 'fixture': raise AlphaError('Verified session required.', 401)
            return self.actor
        def transport(method, url, headers=None, body=None, **kwargs):
            self.sent.append(body)
            if self.before:
                hook, self.before = self.before, None
                hook()
            if self.timeout: raise AlphaError('synthetic lost response', 504)
            data = json.loads(body['messages'][-1]['content'])
            answers = self.answers.evaluate(data['state'], data['questions'], timeout_s=1).answers
            value = {} if self.malformed else {'answers': answers}
            usage = {'cost': self.cost, 'gateway': {'cost': self.cost, 'routing': {'finalProvider': 'google'}}}
            return {'status': 200, 'body': {'id': 'synthetic', 'choices': [{'message': {'content': json.dumps(value)}}], 'usage': usage, 'providerMetadata': {'gateway': {'cost': self.cost, 'routing': {'finalProvider': 'google'}}}}}
        self.runtime = ServerModelRuntime('synthetic-test-key', model=MODEL, models=[MODEL],
            prices={MODEL: (.1, .4)}, allowed_providers={MODEL: ['google']}, transport=transport)
        self.host = HostedWorkspaceService(connection, verify, clock=lambda: self.now[0],
            ideas_runtime=self.runtime, credits_enabled=True, pricing_v2_enabled=True)
        self.wid = self.host.bootstrap('fixture')['workspaceId']
        self.g = self.host.growth = GrowthService(self.host, env={**ENV, 'POSTRIFF_POST_DOCTOR_V2': '1'})
        self.consent()

    def consent(self, routes=ROUTES):
        saved = self.host.get(self.wid, 'fixture')
        self.g.action(self.wid, 'fixture', saved['revision'], 'growth_consent', {'confirmed': True, 'routes': list(routes)})

    def approve(self, **values):
        self.g.env['POSTRIFF_GROWTH_PLATFORM_PREVIEW'] = json.dumps({**POLICY, **values})

    def body(self, **values):
        return {'text': 'One practical idea.', 'platform': 'Threads', 'language': 'en',
                'confirmed': True, 'requestKey': str(uuid.uuid4()), **values}

    def check(self, body=None):
        return self.g.check(self.wid, 'fixture', body or self.body())

    def csv(self, count=3):
        return 'text,platform,language,post_id,published_at\n' + ''.join(
            f'Owned idea {i}.,Threads,en,post-{i},2026-09-{i+1:02d}\n' for i in range(count))

    def import_body(self, count=3, **values):
        return {'data': self.csv(count), 'account': 'owned', 'ownContent': True, 'retainText': True,
                'confirmed': True, 'requestKey': str(uuid.uuid4()), **values}

    def denied(self, fn, code=None):
        with self.assertRaises(AlphaError) as caught: fn()
        if code: self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_generic_growth_caps_are_not_platform_authority(self):
        self.denied(self.check, 'growth_platform_funding_unavailable')
        self.assertEqual(self.sent, [])

    def test_success_replay_lifetime_limit_wallet_and_platform_accounting(self):
        self.approve()
        body = self.body(model='forged/client-route', maximumUsdMicro=1)
        result = self.check(body)
        self.assertTrue(result['dimensions'])
        self.assertEqual(result['userCreditsCharged'], 0)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['model'], MODEL)
        self.assertEqual(self.sent[0]['providerOptions']['gateway']['only'], ['google'])
        self.assertEqual(self.check(body), result)
        self.assertEqual(len(self.sent), 1)
        self.now[0] += 86400
        self.denied(self.check, 'growth_preview_used')
        with connection() as db:
            cost = db.execute('SELECT cost_usd_micro FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall()
            self.assertEqual(cost, [(4000,)])  # overlapping Gateway fields counted once
            rows = db.execute('SELECT charge_batch,actual_usd_micro,meta FROM pr_usage_ledger WHERE workspace_id=%s', (self.wid,)).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(not r[0] and not r[2].get('credits') for r in rows))
            self.assertEqual([r[1] for r in rows if r[1] is not None], [4000])
            self.assertEqual(self.host.ledger.usage_view(db.cursor(), self.wid, self.actor)['credits'], None)
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (4000, 0))

    def test_one_recent20_genome_import_lifetime_and_actual_work_cap(self):
        self.approve()
        body = self.import_body(20, quantity=1, maxPosts=999)
        result = self.g.imports(self.wid, 'fixture', body)
        self.assertEqual(result['genome']['postCount'], 20)
        self.assertEqual(len(self.sent), 40)
        self.assertEqual(self.g.imports(self.wid, 'fixture', body), result)
        self.now[0] += 86400
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body()), 'growth_preview_used')
        self.assertEqual(len(self.sent), 40)

    def test_uploaded21_is_refused_before_io_despite_declared20(self):
        self.approve()
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body(21, quantity=20)))
        self.assertEqual(self.sent, [])

    def test_server_selects_latest20_of_actual_granted_samples(self):
        self.approve()
        saved = self.host.get(self.wid, 'fixture')
        from postriff_phase2 import voice_sources
        def seed(state, actor):
            records = [{'text': 'Owned sample '+str(i), 'platform': 'Threads', 'externalId': str(i), 'account': 'owned', 'publishedAt': f'2026-09-{i+1:02d}'} for i in range(25)]
            voice_sources.apply_action(state, 'voice_samples_import', {'format': 'json', 'records': records}, actor, self.now[0])
            for source in state['sources']:
                voice_sources.apply_action(state, 'voice_sample_select', {'sourceId': source['id'], 'selected': True}, actor, self.now[0])
                voice_sources.apply_action(state, 'voice_sample_grant', {'sourceId': source['id'], 'confirmed': True, 'grants': [{'purpose': 'analysis', 'route': ROUTES[1]}]}, actor, self.now[0])
            return state
        self.host.repository.command(self.wid, 'fixture', saved['revision'], seed)
        samples = self.host.get(self.wid, 'fixture')['state']['sources']
        result = self.g.imports(self.wid, 'fixture', {'sourceIds': [samples[0]['id']], 'quantity': 1, 'ownContent': True, 'retainText': True, 'confirmed': True, 'requestKey': str(uuid.uuid4())})
        self.assertEqual(result['genome']['postCount'], 20)
        with connection() as db:
            ids = set(r[0] for r in db.execute('SELECT provider_post_id FROM pr_post_history WHERE workspace_id=%s', (self.wid,)))
        self.assertEqual(ids, {str(i) for i in range(5, 25)})
        self.assertEqual(len(self.sent), 40)

    def test_failed_paid_attempt_books_loss_and_blocks_next_distinct(self):
        self.approve()
        self.malformed = True
        self.denied(self.check)
        self.denied(self.check, 'growth_preview_used')
        self.assertEqual(len(self.sent), 1)
        with connection() as db:
            self.assertEqual(db.execute('SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind=\'release\'', (self.wid,)).fetchone(), (4000, 'released'))
            self.assertEqual(db.execute('SELECT status FROM pr_post_doctor_runs WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 'failed')

    def test_unknown_keeps_platform_hold_and_is_not_zero(self):
        self.approve()
        self.timeout = True
        self.denied(self.check)
        self.denied(self.check, 'growth_preview_used')
        self.assertEqual(len(self.sent), 1)
        with connection() as db:
            self.assertEqual(db.execute('SELECT cost_usd_micro FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchone()[0], None)
            self.assertEqual(db.execute('SELECT cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind=\'settle\'', (self.wid,)).fetchone()[0], 'estimated_unknown')
            self.assertEqual(db.execute("SELECT reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone()[0], 20000)

    def test_concurrent_distinct_attempts_have_one_durable_winner(self):
        self.approve()
        def compete(_):
            try: self.check(); return 'ok'
            except AlphaError as error: return error.code
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(compete, range(2)))
        self.assertCountEqual(results, ['ok', 'growth_preview_used'])
        self.assertEqual(len(self.sent), 1)

    def test_free_general_growth_refuses_before_preparation(self):
        self.approve()
        for kind in ('rewrite', 'audience', 'postmortem'):
            prepared = []
            self.g.env.update(POSTRIFF_AUDIENCE_MINER='1', POSTRIFF_POSTMORTEM='1')
            def prepare(*_args, _prepared=prepared):
                _prepared.append(kind)   # reaching preparation at all is the failure this test guards against
                raise AlphaError('Preparation reached without authority', code='unexpected_preparation')
            self.denied(lambda: self.g._begin(self.wid, 'fixture', kind, self.body(), prepare), 'free_managed_writing_unavailable')
            self.assertEqual(prepared, [])
        self.assertEqual(self.sent, [])

    def test_actual_v2_managed_rewrite_and_other_unpriced_routes_fail_closed(self):
        with connection() as db:
            db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1',source='subscription' WHERE workspace_id=%s", (self.wid,))
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'creator-v1','active',now()+interval '1 month') ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='creator-v1',status='active',current_period_end=excluded.current_period_end", (self.wid,))
        self.approve()
        for kind in ('check', 'rewrite', 'genome', 'audience', 'postmortem'):
            self.g.env.update(POSTRIFF_AUDIENCE_MINER='1', POSTRIFF_POSTMORTEM='1')
            prepared = []
            # Credit bridge: a managed-credit request without its own quote is refused before preparation or I/O.
            self.denied(lambda: self.g._begin(self.wid, 'fixture', kind, self.body(), lambda *a: (_ for _ in ()).throw(AlphaError('Preparation reached without authority', code='unexpected_preparation'))), 'approval_required')
            self.assertEqual(prepared, [])
        self.assertEqual(self.sent, [])

    def test_route_without_run_authority_cannot_bypass_v2_funding(self):
        from postriff_phase2.growth.usage import MemoryUsageSink
        state = self.host.get(self.wid, 'fixture')['state']
        self.denied(lambda: self.g._router(MemoryUsageSink(), state), 'growth_credit_bridge_unavailable')
        self.assertEqual(self.sent, [])

    def test_explicit_paid_basecheck_is_platform_funded_but_not_rewrite(self):
        with connection() as db:
            db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1',source='subscription' WHERE workspace_id=%s", (self.wid,))
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'creator-v1','active',now()+interval '1 month') ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='creator-v1',status='active',current_period_end=excluded.current_period_end", (self.wid,))
        self.approve(paidBaseChecks=True)
        self.assertTrue(self.check()['dimensions'])
        self.denied(lambda: self.g.rewrite(self.wid, 'fixture', self.body()), 'approval_required')
        self.assertEqual(len(self.sent), 1)

    def test_policy_revocation_stops_before_next_io(self):
        self.approve()
        self.before = lambda: self.g.env.pop('POSTRIFF_GROWTH_PLATFORM_PREVIEW')
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body()))
        self.assertEqual(len(self.sent), 1)

    def test_price_change_during_genome_stops_before_next_io(self):
        self.approve()
        self.before = lambda: self.runtime.prices.update({MODEL: (100, 100)})
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body()))
        self.assertEqual(len(self.sent), 1)
        with connection() as db:
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (4000, 0))

    def test_unexpected_invoice_ceiling_stops_following_paid_attempt(self):
        self.approve()
        self.cost = .03  # More than the server-approved per-attempt ceiling.
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body()))
        self.assertEqual(len(self.sent), 1)
        with connection() as db:
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (30000, 0))

    def test_completed_finalization_after_expiry_never_records_cost_twice(self):
        self.approve()
        captured = []
        finish = self.g._finish
        def record(*args, **kwargs):
            captured.append((args, kwargs)); return finish(*args, **kwargs)
        self.g._finish = record
        self.check()
        with connection() as db: db.execute('UPDATE pr_post_doctor_runs SET expires_at=now()-interval \'1 second\' WHERE workspace_id=%s', (self.wid,))
        self.g.sweep()
        args, kwargs = captured[0]
        finish(*args, **kwargs)
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 1)

    def test_budget_and_rate_limits_are_finite_before_io_and_projected(self):
        self.approve(dailyUsdMicro=20000, monthlyUsdMicro=20000, dailyRuns=1, workspaceDailyRuns=1)
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body()))
        self.assertEqual(self.sent, [])
        with connection() as db: self.assertEqual(db.execute('SELECT count(*) FROM pr_post_doctor_runs WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)
        self.assertTrue(self.check()['dimensions'])
        status = self.g.preview_status(self.wid, 'fixture')
        self.assertFalse(status['genome']['eligible'])
        self.assertEqual(status['genome']['remaining'], 1)
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body()))
        self.assertEqual(len(self.sent), 1)

    def test_funding_readiness_rejects_a_ceiling_below_verified_route_cost(self):
        self.approve(attemptMaxUsdMicro=1)
        self.assertEqual(self.g.preview_status(self.wid, 'fixture')['postDoctor']['reason'], 'funding_unavailable')
        self.denied(self.check, 'growth_platform_funding_unavailable')
        self.assertEqual(self.sent, [])
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_post_doctor_runs WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)

    def test_feature_disable_in_flight_stops_the_next_paid_attempt(self):
        self.approve()
        self.before = lambda: self.g.env.update(POSTRIFF_GENOME='0')
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body()))
        self.assertEqual(len(self.sent), 1)
        with connection() as db:
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (4000, 0))

    def test_plain_serialized_platform_authority_cannot_authorize_ledger(self):
        with connection() as db:
            self.denied(lambda: self.host.ledger.reserve(db.cursor(), self.wid, self.actor, 'tool', 1, 'forged-object',
                charge_batch=False, platform_preview=POLICY), 'growth_platform_funding_unavailable')
        self.assertEqual(self.sent, [])

    def test_consent_revocation_still_records_actual_cost(self):
        self.approve()
        self.before = lambda: self.consent([])
        self.denied(self.check, 'growth_input_changed')
        with connection() as db:
            self.assertEqual(db.execute('SELECT cost_usd_micro FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(4000,)])
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (4000, 0))

    def test_expiry_purges_private_body_without_resetting_lifetime(self):
        self.approve()
        self.check()
        with connection() as db: db.execute('UPDATE pr_post_doctor_runs SET expires_at=now()-interval \'1 second\' WHERE workspace_id=%s', (self.wid,))
        self.g.sweep()
        self.denied(self.check, 'growth_preview_used')
        with connection() as db:
            self.assertEqual(db.execute('SELECT body FROM pr_post_doctor_runs WHERE workspace_id=%s', (self.wid,)).fetchall(), [({},)])

    def test_free_ledger_positive_cost_has_no_exemption_or_client_metadata_authority(self):
        from postriff_phase2.developer_usage import ai_usage_exempt
        with patch.dict(os.environ, {'RAFII_AI_UNLIMITED_USER_IDS': self.actor}):
            self.assertTrue(ai_usage_exempt(self.actor))
            with connection() as db:
                self.denied(lambda: self.host.ledger.reserve(db.cursor(), self.wid, self.actor, 'tool', 1, 'fake-preview', charge_batch=False,
                    meta={'platformPreview': True, 'aiUsageExempt': True}), 'free_managed_writing_unavailable')
        with connection() as db:
            reservation = self.host.ledger.reserve(db.cursor(), self.wid, self.actor, 'tool', 0, 'verified-zero', charge_batch=False)
            self.host.ledger.settle(db.cursor(), self.wid, reservation['reservationId'], 'completed', 0)

    def test_eligibility_is_real_remaining_and_never_leaks_budget_or_input(self):
        method = getattr(self.g, 'preview_status', None)
        self.assertTrue(callable(method), 'Growth must provide the persisted preview eligibility interface')
        before = method(self.wid, 'fixture')
        self.assertEqual(before['postDoctor'], {'remaining': 1, 'eligible': False, 'reason': 'funding_unavailable'})
        self.approve()
        ready = method(self.wid, 'fixture')
        self.assertEqual(ready['postDoctor'], {'remaining': 1, 'eligible': True, 'reason': None})
        self.check()
        after = method(self.wid, 'fixture')
        self.assertEqual(after['postDoctor'], {'remaining': 0, 'eligible': False, 'reason': 'used'})
        self.assertEqual(after['genome']['remaining'], 1)
        self.assertEqual(after['genome']['maxPosts'], 20)
        self.assertFalse(any(term in json.dumps(after).lower() for term in ('micro', 'usd', 'sourceid', 'text', 'policy')))
    # --- Credit bridge (Pricing v2: Creator Growth AI pays through its own credit quote) ------------------------------
    def creator(self, milli=600_000):
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='active' WHERE id='creator-v1'")
            db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1',source='subscription' WHERE workspace_id=%s", (self.wid,))
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'creator-v1','active',now()+interval '1 month') "
                       "ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='creator-v1',status='active',current_period_end=excluded.current_period_end", (self.wid,))
            self.host.ledger.credits.grant(db.cursor(), self.wid, self.actor, 'bridge-grant-' + self.wid, milli, None, source='local-test-only')
        from consumer_fixtures import approve_budgets
        approve_budgets(connection, self.wid)   # operator-approved spending budgets, as in every paid-path test
        bridged = GrowthService(self.host, env={**ENV, 'POSTRIFF_POST_DOCTOR_V2': '1'}, router_factory=Models().router)
        self.host.growth = bridged
        return bridged

    def test_credit_bridge_quotes_reserves_and_settles_once(self):
        g = self.creator()
        body = self.body()
        quote = g.credit_quote(self.wid, 'fixture', {'kind': 'check', 'request': body})
        self.assertEqual((quote['kind'], quote['basis']), ('check', 'growth_request_ceiling'))
        result = g.check(self.wid, 'fixture', {**body, 'creditQuoteId': quote['quoteId']})
        self.assertTrue(result['dimensions'])
        self.assertEqual(self.sent, [])   # the fixture router: no provider transport was used
        with connection() as db:
            rows = db.execute("SELECT kind,meta->'credits'->>'op',cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND provider='rafii-growth' ORDER BY at,id",
                              (self.wid,)).fetchall()
        self.assertEqual([r[0] for r in rows], ['reserve', 'settle'])
        self.assertEqual(rows[0][1], 'reserve')
        replay = g.check(self.wid, 'fixture', {**body, 'creditQuoteId': quote['quoteId']})   # same request key: replayed, not charged again
        self.assertIn('dimensions', replay)
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s AND provider='rafii-growth' AND kind='reserve'", (self.wid,)).fetchone()[0], 1)

    def test_credit_bridge_refuses_a_request_that_differs_from_its_quote(self):
        g = self.creator()
        body = self.body()
        quote = g.credit_quote(self.wid, 'fixture', {'kind': 'check', 'request': body})
        changed = {**body, 'text': 'A different draft entirely.', 'creditQuoteId': quote['quoteId']}
        with self.assertRaises(AlphaError) as caught:
            g.check(self.wid, 'fixture', changed)
        self.assertEqual(caught.exception.status, 409)
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s AND provider='rafii-growth'", (self.wid,)).fetchone()[0], 0)

    def test_creator_image_request_is_refused_before_anything_is_written(self):
        """Plan credits are text-only (D-026): a Creator image request says so plainly, writes no message, run or
        reservation and calls no image provider; the same request is refused on every path (turn and quote)."""
        self.creator()
        ideas = self.host.ideas
        called = []
        ideas.image_runtime = type('NoImages', (), {'provider': 'openai', 'model': 'openai/gpt-image-2', 'estimate_usd_micro': 40_000,
                                                  'generate': lambda *a, **k: called.append(1)})()
        ideas.assets = object()
        conversation = ideas.create_conversation(self.wid, 'fixture', 'Images')['conversationId']
        with connection() as db:
            before = db.execute("SELECT (SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s)+(SELECT count(*) FROM pr_agent_runs WHERE workspace_id=%s)"
                                "+(SELECT count(*) FROM pr_messages WHERE workspace_id=%s)", (self.wid, self.wid, self.wid)).fetchone()[0]
        request = {'text': 'A quiet practice room', 'imageGeneration': True, 'idempotencyKey': 'creator-image-1'}
        with self.assertRaises(AlphaError) as caught:
            ideas.turn(self.wid, 'fixture', conversation, request)
        self.assertEqual((caught.exception.status, caught.exception.code), (402, 'image_credits_unavailable'), str(caught.exception))
        with self.assertRaises(AlphaError) as quoted:
            ideas.credit_requests.issue(self.wid, 'fixture', {'operation': 'turn', 'conversationId': conversation, 'request': {**request, 'research': False}, 'maxMilliCredits': 30_000})
        self.assertEqual(quoted.exception.code, 'image_credits_unavailable')
        with connection() as db:
            after = db.execute("SELECT (SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s)+(SELECT count(*) FROM pr_agent_runs WHERE workspace_id=%s)"
                               "+(SELECT count(*) FROM pr_messages WHERE workspace_id=%s)", (self.wid, self.wid, self.wid)).fetchone()[0]
        self.assertEqual((after, called), (before, []))   # no ledger row, run or message; no image provider call

    def test_credit_bridge_needs_credits_and_is_not_for_free(self):
        with self.assertRaises(AlphaError) as caught:   # Free: the bridge does not apply
            self.g.credit_quote(self.wid, 'fixture', {'kind': 'check', 'request': self.body()})
        self.assertEqual(caught.exception.code, 'credit_bridge_not_applicable')
        g = self.creator(milli=1)
        with self.assertRaises(AlphaError) as caught:   # an empty wallet cannot hold the ceiling
            g.credit_quote(self.wid, 'fixture', {'kind': 'rewrite', 'request': self.body()})
        self.assertEqual(caught.exception.status, 402)


if __name__ == '__main__': unittest.main(verbosity=2)
