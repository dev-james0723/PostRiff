"""Task5 real Growth/ledger on disposable PG17; injected Gateway transport only."""
from local_pg_target import selected_target
import json
import math
import os
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from pathlib import Path
from unittest.mock import patch

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.service import GrowthService, ROUTES
from postriff_phase2.model_runtime import ServerModelRuntime
from postriff_phase2.hosted import HostedWorkspaceService
from growth_phase1_fixtures import ENV, Models

ROOT = Path(__file__).resolve().parents[2]
DSN = selected_target().dsn()
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
            assert db.info.host == '127.0.0.1' and db.info.port == selected_target().port
            for name in ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql',
                         '089_pricing_credit_catalog_v2.sql', '090_free_lifecycle_bootstrap.sql'):
                db.execute((ROOT / 'migrations/postriff' / name).read_text())

    def setUp(self):
        self.now = [time.time()]
        self.actor = str(uuid.uuid4())
        self.sent = []
        self.cost = .004
        self.malformed = False
        self.envelope = False
        self.execution_provider = 'google'
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
            usage = {'cost': .99, 'gateway': {'cost': self.cost, 'routing': {'finalProvider': 'google'}}}
            return {'status': 200, 'body': {'id': 'synthetic', 'choices': [] if self.envelope else [{'message': {'content': json.dumps(value)}}], 'usage': usage, 'providerMetadata': {'gateway': {'cost': self.cost, 'routing': {'finalProvider': self.execution_provider}}}}}
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
            self.denied(lambda: self.g._begin(self.wid, 'fixture', kind, self.body(), lambda *a: (_ for _ in ()).throw(AlphaError('Preparation reached without authority', code='unexpected_preparation'))), 'free_managed_writing_unavailable')
            self.assertEqual(prepared, [])
        self.assertEqual(self.sent, [])

    def test_actual_v2_managed_rewrite_and_other_unpriced_routes_fail_closed(self):
        with connection() as db:
            db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1',source='subscription' WHERE workspace_id=%s", (self.wid,))
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'creator-v1','active',now()+interval '1 month') ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='creator-v1',status='active',current_period_end=excluded.current_period_end", (self.wid,))
        self.approve()
        for kind in ('check', 'genome', 'audience', 'postmortem'):
            self.g.env.update(POSTRIFF_AUDIENCE_MINER='1', POSTRIFF_POSTMORTEM='1')
            prepared = []
            self.denied(lambda: self.g._begin(self.wid, 'fixture', kind, self.body(), lambda *a: (_ for _ in ()).throw(AlphaError('Preparation reached without authority', code='unexpected_preparation'))), 'growth_credit_bridge_unavailable')
            self.assertEqual(prepared, [])
        # Rewrite is the v2 managed-credit route. A generic preview body has no approved
        # rewrite request/maximum, so it must fail validation before preparation or I/O.
        self.denied(lambda: self.g._begin(self.wid, 'fixture', 'rewrite', self.body(), lambda *a: (_ for _ in ()).throw(AlphaError('Preparation reached without authority', code='unexpected_preparation'))), 'invalid_request')
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
        self.denied(lambda: self.g.rewrite(self.wid, 'fixture', self.body()), 'invalid_request')
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
            self.assertEqual(db.execute('SELECT body FROM pr_post_doctor_runs WHERE workspace_id=%s', (self.wid,)).fetchall(), [({'_usageRecorded': True},)])

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


    def test_approved_cap_is_exact_even_for_catalog_thinking_model(self):
        from postriff_phase2.model_runtime import thinking, output_cap
        self.assertTrue(thinking(MODEL))
        self.assertGreater(output_cap(MODEL), 1500)
        # Tight approval covers 1500 output tokens but cannot cover the adapter's old 4500.
        self.approve(attemptMaxUsdMicro=7026)
        self.check()
        self.assertEqual(self.sent[0]['max_tokens'], 1500)
        self.assertLessEqual(self.runtime._cost(MODEL, 64256, self.sent[0]['max_tokens']), .007026)

    def test_persisted_budget_withdrawal_stops_next_attempt_and_cannot_reapprove(self):
        self.approve()
        def withdraw():
            with connection() as db:
                db.execute("UPDATE pr_budgets SET status='candidate' WHERE scope='platform-preview:month'")
        self.before = withdraw
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body(1)))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.g.preview_status(self.wid, 'fixture')['postDoctor']['reason'], 'funding_unavailable')
        self.denied(self.check)
        self.assertEqual(len(self.sent), 1)
        with connection() as db:
            self.assertEqual(db.execute("SELECT status FROM pr_budgets WHERE scope='platform-preview:month'").fetchone()[0], 'candidate')

    def test_tightened_budget_stops_next_attempt(self):
        self.approve()
        def tighten():
            with connection() as db:
                db.execute("UPDATE pr_budgets SET stop_usd_micro=20000 WHERE scope='platform-preview:day'")
        self.before = tighten
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body(1)))
        self.assertEqual(len(self.sent), 1)

    def test_shared_known_loss_stops_other_reserved_run(self):
        self.approve()
        owner = self.actor
        self.actor = str(uuid.uuid4())
        with connection() as db: db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.actor,))
        other = self.host.bootstrap('fixture')['workspaceId']
        saved = self.host.get(other, 'fixture')
        self.g.action(other, 'fixture', saved['revision'], 'growth_consent', {'confirmed':True, 'routes':list(ROUTES)})
        other_run = self.g._begin(other, 'fixture', 'check', self.body(), lambda *args: {'draft': {'text':'Other check.'}})
        self.actor = owner
        def invoice():
            with connection() as db:
                self.host.ledger.settle(db.cursor(), other, other_run['reservationId'], 'failed', 2000001)
        self.before = invoice
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body(1)))
        self.assertEqual(len(self.sent), 1)

    def test_expired_running_authority_stops_next_attempt_without_sweep(self):
        self.approve()
        def expire():
            with connection() as db:
                db.execute("UPDATE pr_post_doctor_runs SET expires_at=now()-interval '1 second' WHERE workspace_id=%s", (self.wid,))
        self.before = expire
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body(1)))
        self.assertEqual(len(self.sent), 1)
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_genome_versions WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 0)

    def test_settled_original_reservation_stops_next_attempt(self):
        self.approve()
        def settle():
            with connection() as db:
                rid = str(db.execute("SELECT id FROM pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", (self.wid,)).fetchone()[0])
                self.host.ledger.settle(db.cursor(), self.wid, rid, 'failed', 4000)
        self.before = settle
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body(1)))
        self.assertEqual(len(self.sent), 1)

    def test_expiry_before_finalization_accounts_once_without_restoring_content(self):
        self.approve()
        captured = []
        finish = self.g._finish
        def delay(*args, **kwargs):
            captured.append((args, kwargs))
            with connection() as db:
                db.execute("UPDATE pr_post_doctor_runs SET expires_at=now()-interval '1 second' WHERE workspace_id=%s", (self.wid,))
            self.g.sweep()
            return finish(*args, **kwargs)
        self.g._finish = delay
        self.denied(self.check, 'growth_input_changed')
        args, kwargs = captured[0]
        finish(*args, **kwargs)  # duplicate after cancellation does not store or account again
        self.g.sweep()
        with connection() as db:
            self.assertEqual(db.execute('SELECT cost_usd_micro FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(4000,)])
            self.assertEqual(db.execute("SELECT actual_usd_micro FROM pr_usage_ledger WHERE workspace_id=%s AND kind='release'", (self.wid,)).fetchall(), [(4000,)])
            self.assertEqual(db.execute('SELECT body FROM pr_post_doctor_runs WHERE workspace_id=%s', (self.wid,)).fetchone()[0], {'_usageRecorded':True})

    def test_expired_unknown_finalization_preserves_hold_once(self):
        self.approve()
        self.timeout = True
        finish = self.g._finish
        captured = []
        def delay(*args, **kwargs):
            captured.append((args, kwargs))
            with connection() as db:
                db.execute("UPDATE pr_post_doctor_runs SET expires_at=now()-interval '1 second' WHERE workspace_id=%s", (self.wid,))
            self.g.sweep()
            return finish(*args, **kwargs)
        self.g._finish = delay
        self.denied(self.check)
        finish(*captured[0][0], **captured[0][1])
        with connection() as db:
            self.assertEqual(db.execute("SELECT cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='settle'", (self.wid,)).fetchall(), [('estimated_unknown',)])
            self.assertEqual(db.execute("SELECT reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone()[0], 20000)
            self.assertEqual(db.execute('SELECT count(*) FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 1)

    def test_actual_legacy_audience_consent_cancellation_keeps_cost_once(self):
        from postriff_phase2.growth.usage import MemoryUsageSink, UsageEvent
        # Use the real shared legacy run/finalizer and actual consent invalidation effect.
        with connection() as db:
            db.execute("UPDATE pr_entitlements SET plan_terms_id='studio-v1',source='subscription' WHERE workspace_id=%s", (self.wid,))
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'studio-v1','active',now()+interval '1 month') ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='studio-v1',status='active',current_period_end=excluded.current_period_end", (self.wid,))
        self.g.env['POSTRIFF_AUDIENCE_MINER'] = '1'
        run = self.g._begin(self.wid, 'fixture', 'audience', self.body(), lambda *args: {})
        sink = MemoryUsageSink()
        sink.record(UsageEvent('audience.classify', MODEL, 'fallback', 'ok', 1, workspace_id=self.wid, cost_usd=.004, cost_source='gateway'))
        self.consent([])
        self.denied(lambda: self.g._finish(self.wid, 'fixture', run, sink, {'private':'discard'}), 'growth_input_changed')
        self.g._finish(self.wid, 'fixture', run, sink, {'private':'discard'})
        self.consent()  # repeated invalidation must retain the opaque fence
        self.g._finish(self.wid, 'fixture', run, sink, {'private':'discard'})
        with connection() as db:
            self.assertEqual(db.execute('SELECT cost_usd_micro FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(4000,)])
            self.assertEqual(db.execute('SELECT body FROM pr_post_doctor_runs WHERE workspace_id=%s', (self.wid,)).fetchone()[0], {'_usageRecorded':True})

    def test_two_actual_genome_finalizers_store_one_winning_version(self):
        self.approve()
        finish = self.g._finish
        transaction = self.g.repository.transaction
        barrier = Barrier(2)
        @contextmanager
        def synchronized(*args, **kwargs):
            # Both accounting transactions commit before either real content transaction.
            barrier.wait(timeout=10)
            with transaction(*args, **kwargs) as value: yield value
        def race(*args, **kwargs):
            with patch.object(self.g.repository, 'transaction', synchronized), ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(finish, *args, **kwargs) for _ in range(2)]
                results = [f.result(timeout=20) for f in futures]
            self.assertEqual(results[0], results[1])
            return results[0]
        self.g._finish = race
        result = self.g.imports(self.wid, 'fixture', self.import_body(1))
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_genome_versions WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 1)
            saved = db.execute('SELECT body FROM pr_post_doctor_runs WHERE workspace_id=%s', (self.wid,)).fetchone()[0]
            self.assertEqual(saved['genome']['id'], result['genome']['id'])
            self.assertEqual(db.execute('SELECT count(*) FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchone()[0], 2)

    def test_unapproved_execution_provider_fails_closed_and_books_known_loss(self):
        self.approve()
        self.execution_provider = 'unapproved-provider'
        self.denied(lambda: self.g.imports(self.wid, 'fixture', self.import_body(1)))
        self.assertEqual(len(self.sent), 1)
        with connection() as db:
            self.assertEqual(db.execute("SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='release'", (self.wid,)).fetchone(), (4000, 'released'))

    def test_missing_execution_provider_fails_closed_and_books_known_loss(self):
        self.approve()
        self.execution_provider = None
        self.denied(self.check)
        with connection() as db:
            self.assertEqual(db.execute("SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='release'", (self.wid,)).fetchone(), (4000, 'released'))

    def test_first_use_policy_caps_cover_each_advertised_action_without_budget_rows(self):
        self.approve(dailyUsdMicro=20000, monthlyUsdMicro=20000)
        status = self.g.preview_status(self.wid, 'fixture')
        self.assertEqual(status['postDoctor'], {'remaining':1, 'eligible':True, 'reason':None})
        self.assertEqual(status['genome'], {'remaining':1, 'eligible':False, 'reason':'funding_unavailable', 'maxPosts':20})
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_budgets WHERE scope LIKE 'platform-preview:%'").fetchone()[0], 0)
        self.approve(dailyUsdMicro=800000, monthlyUsdMicro=800000)
        self.assertTrue(self.g.preview_status(self.wid, 'fixture')['genome']['eligible'])
        self.approve(attemptMaxUsdMicro=1)
        self.assertFalse(self.g.preview_status(self.wid, 'fixture')['postDoctor']['eligible'])

    def test_costed_malformed_envelope_books_known_failed_loss_once(self):
        self.approve()
        self.envelope = True
        self.denied(self.check)
        self.assertEqual(len(self.sent), 1)
        with connection() as db:
            self.assertEqual(db.execute('SELECT cost_usd_micro,cost_source FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(4000,'gateway')])
            self.assertEqual(db.execute("SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='release'", (self.wid,)).fetchone(), (4000,'released'))
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (4000,0))

    def test_malformed_envelope_invalid_cost_is_unknown_not_zero(self):
        self.approve()
        self.envelope = True
        self.cost = 'invalid'
        self.denied(self.check)
        with connection() as db:
            self.assertEqual(db.execute('SELECT cost_usd_micro FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(None,)])
            self.assertEqual(db.execute("SELECT cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='settle'", (self.wid,)).fetchone()[0], 'estimated_unknown')


    def test_expired_legacy_audience_retains_fence_until_late_accounting(self):
        from postriff_phase2.growth.usage import MemoryUsageSink, UsageEvent
        # Legacy Audience can also expire during an in-flight response; retain only its fence.
        with connection() as db:
            db.execute("UPDATE pr_entitlements SET plan_terms_id='studio-v1',source='subscription' WHERE workspace_id=%s", (self.wid,))
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'studio-v1','active',now()+interval '1 month') ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='studio-v1',status='active',current_period_end=excluded.current_period_end", (self.wid,))
        self.g.env['POSTRIFF_AUDIENCE_MINER'] = '1'
        run = self.g._begin(self.wid, 'fixture', 'audience', self.body(), lambda *args: {})
        sink = MemoryUsageSink()
        sink.record(UsageEvent('audience.classify', MODEL, 'fallback', 'ok', 1, workspace_id=self.wid, cost_usd=.004, cost_source='gateway'))
        with connection() as db:
            db.execute("UPDATE pr_post_doctor_runs SET expires_at=now()-interval '1 second' WHERE workspace_id=%s", (self.wid,))
        self.g.sweep()
        self.denied(lambda: self.g._finish(self.wid, 'fixture', run, sink, {'private':'discard'}), 'growth_input_changed')
        self.g._finish(self.wid, 'fixture', run, sink, {'private':'discard'})
        with connection() as db:
            self.assertEqual(db.execute('SELECT cost_usd_micro FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(4000,)])
            self.assertEqual(db.execute('SELECT body FROM pr_post_doctor_runs WHERE workspace_id=%s', (self.wid,)).fetchone()[0], {'_usageRecorded':True})


    def _storage_finalizes(self, fn):
        try: return fn()
        except (OverflowError, psycopg.Error) as error:
            self.fail('Cost must finalize as storable known or durable unknown, not '+type(error).__name__)

    def _invalid_gateway_cost_is_durable_unknown(self, cost):
        self.approve()
        self.cost = cost
        # Exercise both valid and malformed envelopes in distinct workspaces/lifetime slots.
        self.envelope = True
        finish = self.g._finish
        captured = []
        def capture(*args, **kwargs):
            captured.append((args, kwargs)); return finish(*args, **kwargs)
        self.g._finish = capture
        self._storage_finalizes(lambda: self.denied(self.check))
        self.assertEqual(len(self.sent), 1)
        finish(*captured[0][0], **captured[0][1])
        with connection() as db:
            self.assertEqual(db.execute('SELECT cost_usd_micro,cost_source FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(None,'unknown')])
            self.assertEqual(db.execute("SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='settle'", (self.wid,)).fetchall(), [(None,'estimated_unknown')])
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (0,20000))
            status,body=db.execute('SELECT status,body FROM pr_post_doctor_runs WHERE workspace_id=%s', (self.wid,)).fetchone()
            self.assertEqual(status,'unknown')
            self.assertTrue(body['_usageRecorded'])
        self.denied(self.check, 'growth_preview_used')
        self.assertEqual(len(self.sent),1)

    def test_numeric_finite_multiplication_overflow_is_durable_unknown_once(self):
        self._invalid_gateway_cost_is_durable_unknown(1e308)

    def test_string_finite_multiplication_overflow_is_durable_unknown_once(self):
        self._invalid_gateway_cost_is_durable_unknown('1e308')

    def test_numeric_finite_bigint_overflow_is_durable_unknown_once(self):
        self._invalid_gateway_cost_is_durable_unknown(1e13)

    def test_string_finite_bigint_overflow_is_durable_unknown_once(self):
        self._invalid_gateway_cost_is_durable_unknown('1e13')

    def test_successful_envelope_nonrepresentable_cost_is_unknown_once(self):
        self.approve()
        self.cost = 1e13
        finish = self.g._finish
        captured = []
        def capture(*args, **kwargs):
            captured.append((args, kwargs)); return finish(*args, **kwargs)
        self.g._finish = capture
        result = self._storage_finalizes(self.check)
        self.assertEqual(finish(*captured[0][0], **captured[0][1]),result)
        with connection() as db:
            self.assertEqual(db.execute('SELECT cost_usd_micro,cost_source FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(None,'unknown')])
            self.assertEqual(db.execute("SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='settle'", (self.wid,)).fetchall(), [(None,'estimated_unknown')])
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (0,20000))

    def test_representable_big_gateway_loss_is_not_clipped_to_policy(self):
        self.approve()
        self.cost = 9e12  # below signed bigint after converting to microdollars, far above policy
        self.envelope = True
        self._storage_finalizes(lambda: self.denied(self.check))
        with connection() as db:
            expected=9_000_000_000_000_000_000
            self.assertEqual(db.execute('SELECT cost_usd_micro,cost_source FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(expected,'gateway')])
            self.assertEqual(db.execute("SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='release'", (self.wid,)).fetchall(), [(expected,'released')])
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (expected,0))

    def test_zero_gateway_charge_is_known_and_releases_hold(self):
        self.approve()
        self.cost = 0
        self.envelope = True
        self._storage_finalizes(lambda: self.denied(self.check))
        with connection() as db:
            self.assertEqual(db.execute('SELECT cost_usd_micro,cost_source FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(0,'gateway')])
            self.assertEqual(db.execute("SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='release'", (self.wid,)).fetchall(), [(0,'released')])
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (0,0))

    def test_individually_storable_genome_costs_with_unstorable_sum_hold_once(self):
        self.approve()
        # Explicit reported decimal USD and its exact micro-dollar value.
        # Binary float multiplication is not an invoice rounding oracle.
        near_max=9223372036854.773
        charge=9223372036854773000
        self.assertLessEqual(charge,2**63-1)
        self.assertGreater(charge+4000,2**63-1)
        transport=self.runtime.transport
        def costs(*args,**kwargs):
            self.cost=.004 if not self.sent else near_max
            return transport(*args,**kwargs)
        self.runtime.transport=costs
        finish=self.g._finish
        captured=[]
        def capture(*args,**kwargs):
            captured.append((args,kwargs));return finish(*args,**kwargs)
        self.g._finish=capture
        result=self._storage_finalizes(lambda:self.g.imports(self.wid,'fixture',self.import_body(1)))
        self.assertEqual(len(self.sent),2)
        self.assertEqual(finish(*captured[0][0],**captured[0][1]),result)
        with connection() as db:
            self.assertCountEqual(db.execute('SELECT cost_usd_micro,cost_source FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(4000,'gateway'),(charge,'gateway')])
            self.assertEqual(db.execute("SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='settle'", (self.wid,)).fetchall(), [(None,'estimated_unknown')])
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (0,40000))
            self.assertTrue(db.execute('SELECT body FROM pr_post_doctor_runs WHERE workspace_id=%s', (self.wid,)).fetchone()[0]['_usageRecorded'])

    def test_budget_aggregate_overflow_keeps_known_event_and_hold_once(self):
        self.approve()
        def near_limit():
            with connection() as db:
                db.execute("UPDATE pr_budgets SET spent_usd_micro=%s WHERE scope='platform-preview:month'", (2**63-1-1000,))
        self.before=near_limit
        finish=self.g._finish
        captured=[]
        def capture(*args,**kwargs):
            captured.append((args,kwargs));return finish(*args,**kwargs)
        self.g._finish=capture
        result=self._storage_finalizes(self.check)
        self.assertEqual(finish(*captured[0][0],**captured[0][1]),result)
        with connection() as db:
            self.assertEqual(db.execute('SELECT cost_usd_micro,cost_source FROM pr_model_usage_events WHERE workspace_id=%s', (self.wid,)).fetchall(), [(4000,'gateway')])
            self.assertEqual(db.execute("SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='settle'", (self.wid,)).fetchall(), [(None,'estimated_unknown')])
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (2**63-1-1000,20000))
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:day'").fetchone(), (0,20000))


    def test_genome_cost_sum_at_exact_bigint_max_is_known(self):
        self.approve()
        # Explicit reported decimal USD and its exact micro-dollar value.
        # Binary float multiplication is not an invoice rounding oracle.
        near_max=9223372036854.773
        charge=9223372036854773000
        remainder=2**63-1-charge
        first_cost=.002807
        self.assertEqual(remainder,2807)
        self.assertEqual(str(first_cost),'0.002807')
        transport=self.runtime.transport
        def costs(*args,**kwargs):
            self.cost=first_cost if not self.sent else near_max
            return transport(*args,**kwargs)
        self.runtime.transport=costs
        self.g.imports(self.wid,'fixture',self.import_body(1))
        with connection() as db:
            self.assertEqual(db.execute("SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='settle'", (self.wid,)).fetchall(), [(2**63-1,'actual')])
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (2**63-1,0))

    def test_budget_total_at_exact_bigint_max_is_known(self):
        self.approve()
        def near_limit():
            with connection() as db:
                db.execute("UPDATE pr_budgets SET spent_usd_micro=%s WHERE scope='platform-preview:month'", (2**63-1-4000,))
        self.before=near_limit
        self.check()
        with connection() as db:
            self.assertEqual(db.execute("SELECT actual_usd_micro,cost_state FROM pr_usage_ledger WHERE workspace_id=%s AND kind='settle'", (self.wid,)).fetchall(), [(4000,'actual')])
            self.assertEqual(db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope='platform-preview:month'").fetchone(), (2**63-1,0))

if __name__ == '__main__': unittest.main(verbosity=2)
