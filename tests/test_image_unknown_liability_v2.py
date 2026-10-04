"""Offline image liability regressions: real transport/Ideas/ledger, strict fake SQL.

No PostgreSQL, socket, HTTP server or provider is used. All identities, prices,
quotes and HTTP response bytes are synthetic; no estimate proves actual spend.
"""
import copy
import io
import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from postriff_alpha.domain import AlphaError
from postriff_phase2 import image_runtime
from postriff_phase2.billing import Ledger
from postriff_phase2.credit_meter import V2_POLICY_VERSION
from postriff_phase2.credit_wallet import project_credit_wallet, request_digest
from postriff_phase2.ideas import IdeasService

NOW = 1_800_000_000
WID = '00000000-0000-4000-8000-000000000001'
ACTOR = '00000000-0000-4000-8000-000000000002'
QUOTE = '00000000-0000-4000-8000-000000000003'
RUN = '00000000-0000-4000-8000-000000000004'
HOLD = '00000000-0000-4000-8000-000000000005'
GRANT = '00000000-0000-4000-8000-000000000006'
MODEL = 'openai/synthetic-image'
MAXIMUM = 30_000
ESTIMATE = 100_000
REQUEST = {'text': 'Synthetic image', 'imageGeneration': True, 'research': False,
           'model': 'deterministic-preview', 'confirmUse': True, 'ownContent': True}


def policy():
    return {'model': MODEL, 'provider': 'vercel-ai-gateway', 'count': 1,
            'size': '1024x1024', 'ceilingUsdMicro': ESTIMATE,
            'expiresAt': NOW + 3600, 'qualification': 'operator-approved-ceiling',
            'evidenceRef': 'synthetic-fixture-v1', 'executionProviders': ['openai']}


class Response:
    def __init__(self, status, body):
        self.status, self.body = status, body

    def read(self, maximum):
        return self.body[:maximum]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeSQL:
    """Small fail-closed cursor protocol for the real reserve/guard/settle paths."""
    def __init__(self):
        self.rows = [{'id': GRANT, 'reservationId': None,
                      'credits': {'op': 'grant', 'milli': 100_000, 'expiresAt': None}}]
        self.reserve = None
        self.entries, self.events, self.statements = [], [], []
        self.quote_claim = None
        self.quote_digest = request_digest('turn', REQUEST, 'conversation')
        self.run_status = None
        self.run_key = None
        self.budgets = {}
        self.open_transactions = 0
        self.guard_queries = 0
        self.result = None

    def cursor(self):
        return self

    def __enter__(self):
        self.open_transactions += 1
        return self

    def __exit__(self, *args):
        self.open_transactions -= 1
        return False

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result

    def wallet(self):
        return project_credit_wallet(self.rows, NOW)

    def execute(self, sql, args=()):
        q = ' '.join(sql.split())
        self.statements.append((q, copy.deepcopy(args)))
        self.result = None
        if q.startswith("SELECT state->'founderOps'"):
            self.result = None  # synthetic customer workspace has no internal-operations marker
        elif q.startswith('SELECT id FROM public.pr_workspaces'):
            self.result = (WID,)
        elif q.startswith('SELECT status,extract(epoch from grace_until)'):
            self.result = ('active', None, False, NOW + 3600, 'creator-v1')
        elif q.startswith('SELECT plan_terms_id FROM public.pr_entitlements'):
            self.result = ('creator-v1',)
        elif q.startswith('SELECT plan_terms_id,writing_batches_remaining'):
            self.result = ('creator-v1', 0, 0, 3, 1, 100, NOW + 3600, 'subscription', 1)
        elif q.startswith("SELECT p.entitlements->>'creditPolicy',p.status"):
            self.result = (V2_POLICY_VERSION, 'active')
        elif q.startswith('SELECT policy_id,request_digest,workspace_revision'):
            self.result = (V2_POLICY_VERSION, self.quote_digest, 1, MODEL,
                           'vercel-ai-gateway', MAXIMUM, NOW + 600, self.quote_claim)
        elif q.startswith('SELECT id::text,reservation_id::text,meta FROM public.pr_usage_ledger'):
            self.result = None
        elif q.startswith("SELECT id::text,reservation_id::text,meta->'credits'"):
            self.result = [(r['id'], r['reservationId'], r['credits']) for r in self.rows]
        elif q.startswith("SELECT to_regclass('public.pr_credit_subscription_grants')"):
            self.result = (False,)
        elif q.startswith("SELECT to_regclass('public.pr_product_events')"):
            self.result = (True,)
        elif q.startswith('SELECT count(*) FROM public.pr_usage_ledger'):
            self.result = (0,)
        elif q.startswith('INSERT INTO public.pr_budgets'):
            scope, kind, warn, stop, _status = args
            self.budgets.setdefault(scope, {'kind': kind, 'warn': warn, 'stop': stop,
                                            'spent': 0, 'reserved': 0})
        elif q.startswith('SELECT window_kind,window_start,warn_usd_micro'):
            b = self.budgets[args[0]]
            self.result = (b['kind'], 0, b['warn'], b['stop'], b['spent'], b['reserved'], 'approved')
        elif q.startswith('UPDATE public.pr_budgets SET window_start='):
            pass
        elif q.startswith('INSERT INTO public.pr_agent_runs'):
            self.run_status, self.run_key = 'running', args[6]
            self.result = (RUN,)
        elif q.startswith('SELECT status FROM public.pr_agent_runs'):
            self.result = [(self.run_status,)] if 'UNION ALL' in q else (self.run_status,)
        elif q.startswith("UPDATE public.pr_agent_runs SET status='failed'"):
            self.run_status = 'failed'
        elif q.startswith('UPDATE public.pr_agent_runs SET usage=usage ||'):
            pass
        elif q.startswith('INSERT INTO public.pr_usage_ledger') and "'reserve'" in q:
            self.reserve = {'meta': json.loads(args[10]), 'estimate': args[7],
                            'dimension': args[4], 'provider': args[5], 'model': args[6],
                            'run': args[2], 'job': args[3], 'member': args[1], 'charge_batch': args[8]}
            self.rows.append({'id': HOLD, 'reservationId': HOLD, 'credits': self.reserve['meta']['credits']})
            self.result = (HOLD,)
        elif q.startswith('UPDATE public.pr_credit_quotes SET reservation_id='):
            assert args == (HOLD, WID, QUOTE) and self.quote_claim is None
            self.quote_claim, self.result = HOLD, (QUOTE,)
        elif q.startswith('UPDATE public.pr_usage_ledger SET reservation_id=id'):
            assert args == (HOLD,)
        elif q.startswith('UPDATE public.pr_budgets SET reserved_usd_micro=reserved_usd_micro+'):
            self.budgets[args[1]]['reserved'] += args[0]
        elif q.startswith('SELECT estimated_usd_micro,model,provider,meta,run_id::text'):
            r = self.reserve
            self.guard_queries += 1
            self.result = (r['estimate'], r['model'], r['provider'], r['meta'], r['run'])
        elif q.startswith('SELECT 1 FROM public.pr_usage_ledger'):
            if 'kind IN' in q and self.entries:
                self.result = (1,)
            elif 'idempotency_key' in q:
                self.result = (1,) if any(e['key'] == args[1] for e in self.entries) else None
        elif q.startswith('SELECT status,stop_usd_micro,spent_usd_micro,reserved_usd_micro'):
            b = self.budgets[args[0]]
            self.result = ('approved', b['stop'], b['spent'], b['reserved'])
        elif q.startswith('SELECT meta FROM public.pr_usage_ledger'):
            self.result = (self.reserve['meta'],)
        elif q.startswith('SELECT pg_advisory_xact_lock'):
            pass
        elif q.startswith('SELECT cost_state FROM public.pr_usage_ledger'):
            terminal = next((e for e in self.entries if e['state'] in ('released', 'actual')), None)
            self.result = (terminal['state'],) if terminal else None
        elif q.startswith('SELECT dimension,estimated_usd_micro,charge_batch'):
            r = self.reserve
            self.result = (r['dimension'], r['estimate'], r['charge_batch'], r['provider'],
                           r['model'], r['run'], r['job'], r['member'])
        elif q.startswith('SELECT spent_usd_micro FROM public.pr_budgets'):
            self.result = (self.budgets[args[0]]['spent'],)
        elif q.startswith("SELECT meta->'credits' FROM public.pr_usage_ledger"):
            self.result = (self.reserve['meta']['credits'],)
        elif q.startswith('INSERT INTO public.pr_usage_ledger'):
            if "'estimated_unknown'" in q:
                self.entries.append({'kind': 'settle', 'state': 'estimated_unknown', 'actual': None, 'key': args[-2]})
            else:
                self.entries.append({'kind': args[5], 'state': args[11], 'actual': args[10], 'key': args[13]})
                credits = json.loads(args[14]).get('credits')
                if credits:
                    self.rows.append({'id': 'settlement', 'reservationId': HOLD, 'credits': credits})
        elif q.startswith('UPDATE public.pr_budgets SET reserved_usd_micro=greatest'):
            estimate, actual, scope = args
            self.budgets[scope]['reserved'] -= estimate
            self.budgets[scope]['spent'] += actual
        elif q.startswith('INSERT INTO public.pr_product_events'):
            self.events.append((args[1], json.loads(args[2])))
        else:
            raise AssertionError('Unexpected fake-SQL statement: ' + q)


class ImageLiabilityTests(unittest.TestCase):
    def runtime(self):
        return image_runtime.GatewayImageRuntime('synthetic-fixture-v1', MODEL,
            credit_policy=policy(), clock=lambda: NOW)

    @contextmanager
    def http(self, status, raw, before=lambda: None):
        calls = []
        def open_fake(request, **kwargs):
            before()
            calls.append(request)
            if status >= 400:
                raise HTTPError(image_runtime.DEFAULT_ENDPOINT, status, 'synthetic', {}, io.BytesIO(raw))
            return Response(status, raw)
        with patch.object(image_runtime, 'build_opener', return_value=SimpleNamespace(open=open_fake)):
            yield calls

    def service(self):
        sql = FakeSQL()
        @contextmanager
        def transaction(token, wid):
            assert token == 'synthetic' and wid == WID
            with sql:
                yield sql, (1, {'sources': [], 'phase2': {}}, 'owner', False, False, False, False), ACTOR
        repo = SimpleNamespace(transaction=transaction, connection_factory=lambda: sql,
                               verify_session=lambda token: ACTOR)
        svc = IdeasService.__new__(IdeasService)
        svc.repository, svc.ledger, svc.image_runtime = repo, Ledger(credits_enabled=True, clock=lambda: NOW), self.runtime()
        svc.assets = SimpleNamespace(stage_upload=lambda *args: self.fail('A failed image cannot upload media'))
        svc._conversation = lambda *args: None
        svc._lock_run_events = lambda *args: None
        svc._append_message = lambda *args: None
        svc._insert_event = lambda *args: None
        svc._settle_message = lambda *args: None
        svc._keyed_run = lambda cur, wid, key, fingerprint: RUN if sql.run_key == key else None
        svc._events_for = lambda *args: {'runId': RUN, 'status': sql.run_status}
        svc.resolve_writer = lambda *args: (SimpleNamespace(owns=lambda model: False), 'deterministic-preview', None)
        def authorize(wid, token, revision, payload, operation, conversation):
            with transaction(token, wid) as (cur, row, actor):
                return svc.ledger.credits.authorize(cur, wid, actor, revision,
                    request_digest(operation, payload, conversation), payload['creditQuoteId'])
        svc.credit_requests = SimpleNamespace(authorize=authorize)
        payload = {**REQUEST, 'expectedRevision': 1, 'creditQuoteId': QUOTE,
                   'idempotencyKey': 'synthetic-image-task'}
        return svc, sql, payload

    def assert_committed_hold(self, sql):
        self.assertEqual(sql.open_transactions, 0, 'SQL lock scope must finish before transport')
        self.assertEqual(sql.quote_claim, HOLD)
        self.assertEqual(sql.reserve['meta']['credits']['quoteId'], QUOTE)
        self.assertEqual(sql.reserve['meta']['credits']['maximum'], MAXIMUM)
        self.assertEqual(sql.wallet()['heldMilliCredits'], MAXIMUM)
        self.assertEqual(sql.guard_queries, 1)
        self.assertTrue(all(b['reserved'] == ESTIMATE for b in sql.budgets.values()))

    def call_chat(self, status, raw):
        svc, sql, payload = self.service()
        with self.http(status, raw, before=lambda: self.assert_committed_hold(sql)) as calls:
            with self.assertRaises(image_runtime.ImageGenerationError) as caught:
                svc.turn(WID, 'synthetic', 'conversation', payload)
            replay = svc.turn(WID, 'synthetic', 'conversation', payload)
            self.assertEqual(replay, {'runId': RUN, 'status': 'failed'})
            self.assertEqual(len(calls), 1, 'Unknown and failed image attempts are never replayed')
        self.assertEqual(sql.quote_claim, HOLD, 'The consumed quote remains bound to its original hold')
        self.assertEqual(sql.run_status, 'failed')
        self.assertEqual(sql.open_transactions, 0)
        return caught.exception, sql

    def test_direct_actual_transport_unreadable_http200_is_unknown_no_retry(self):
        with self.http(200, b'not JSON after dispatch') as calls:
            with self.assertRaises(image_runtime.ImageGenerationError) as caught:
                self.runtime().generate('Synthetic image', credit_approved=True, credit_guard=lambda **kw: None)
            self.assertEqual(len(calls), 1)
        self.assertTrue(caught.exception.uncertain)
        self.assertIsNone(caught.exception.cost_usd)

    def test_chat_unreadable_http200_keeps_original_max_hold_and_replay(self):
        error, sql = self.call_chat(200, b'not JSON after dispatch')
        self.assertEqual(sql.entries, [{'kind': 'settle', 'state': 'estimated_unknown', 'actual': None,
                                       'key': 'settle:' + HOLD + ':unknown'}])
        self.assertTrue(error.uncertain)
        self.assertEqual((sql.wallet()['heldMilliCredits'], sql.wallet()['usedMilliCredits']), (MAXIMUM, 0))
        self.assertTrue(all(b['reserved'] == ESTIMATE and b['spent'] == 0 for b in sql.budgets.values()))
        self.assertEqual([e for e, _ in sql.events].count('credits.pending'), 1)
        self.assertNotIn('credits.settled', [e for e, _ in sql.events])

    def test_chat_parsed_success_without_cost_or_image_also_stays_unknown(self):
        _, sql = self.call_chat(200, b'{"data": []}')
        self.assertEqual(sql.entries[0]['actual'], None)
        self.assertEqual(sql.wallet()['heldMilliCredits'], MAXIMUM)

    def test_chat_http_failure_verified_cost_is_customer_zero_platform_actual(self):
        raw = json.dumps({'usage': {'cost': 0.04}}).encode()
        error, sql = self.call_chat(503, raw)
        self.assertEqual(error.cost_usd, 0.04)
        self.assertEqual(sql.entries[0]['state'], 'released')
        self.assertEqual(sql.entries[0]['actual'], 40_000)
        self.assertEqual((sql.wallet()['heldMilliCredits'], sql.wallet()['usedMilliCredits']), (0, 0))
        self.assertTrue(all(b['reserved'] == 0 and b['spent'] == 40_000 for b in sql.budgets.values()))
        self.assertIn(('platform.cost', {'funding': 'failed_operation', 'state': 'failed',
                       'actualUsdMicro': 40_000, 'sourceKind': 'usage_ledger',
                       'sourceReference': sql.events[-1][1]['sourceReference'], 'schemaVersion': 1}), sql.events)

    def test_chat_verified_zero_cost_refusal_releases_customer_hold(self):
        error, sql = self.call_chat(400, b'{"usage":{"cost":0}}')
        self.assertEqual(error.cost_usd, 0)
        self.assertEqual((sql.entries[0]['state'], sql.entries[0]['actual']), ('released', 0))
        self.assertEqual(sql.wallet()['heldMilliCredits'], 0)

    def test_chat_preio_guard_refusal_releases_without_physical_attempt(self):
        svc, sql, payload = self.service()
        svc._credit_attempt_guard = lambda *args: lambda **kw: (_ for _ in ()).throw(AlphaError('Synthetic revoked funding', 409))
        with self.http(200, b'not JSON') as calls:
            with self.assertRaises(image_runtime.ImageGenerationError) as caught:
                svc.turn(WID, 'synthetic', 'conversation', payload)
            self.assertEqual(calls, [])
        self.assertEqual(caught.exception.cost_usd, 0.0)
        self.assertEqual((sql.entries[0]['state'], sql.entries[0]['actual']), ('released', 0))
        self.assertEqual(sql.wallet()['heldMilliCredits'], 0)
        self.assertEqual(sql.quote_claim, HOLD)

    def test_failure_handler_cannot_infer_zero_from_uncertain_false(self):
        svc, sql, payload = self.service()
        with sql:
            svc.ledger.reserve(sql, WID, ACTOR, 'image_generation', ESTIMATE, 'synthetic-hold',
                charge_batch=True, provider='vercel-ai-gateway', model=MODEL,
                run_id=RUN, credit_authority={'quoteId': QUOTE, 'requestDigest': sql.quote_digest})
        sql.run_status = 'running'
        svc._fail_image_run(WID, 'synthetic', 'conversation', RUN, HOLD, 'Synthetic failure', uncertain=False)
        self.assertEqual((sql.entries[0]['state'], sql.entries[0]['actual']), ('estimated_unknown', None))
        self.assertEqual(sql.wallet()['heldMilliCredits'], MAXIMUM)

    def test_failure_handler_invalid_cost_evidence_keeps_liability(self):
        for cost in (True, -1, float('nan'), float('inf'), 'bad'):
            with self.subTest(cost=cost):
                svc, sql, _payload = self.service()
                with sql:
                    svc.ledger.reserve(sql, WID, ACTOR, 'image_generation', ESTIMATE, 'synthetic-hold',
                        charge_batch=True, provider='vercel-ai-gateway', model=MODEL,
                        run_id=RUN, credit_authority={'quoteId': QUOTE, 'requestDigest': sql.quote_digest})
                sql.run_status = 'running'
                svc._fail_image_run(WID, 'synthetic', 'conversation', RUN, HOLD, 'Synthetic failure',
                                    usage={'costUsd': cost}, uncertain=False)
                self.assertEqual((sql.entries[0]['state'], sql.entries[0]['actual']), ('estimated_unknown', None))
                self.assertEqual(sql.wallet()['heldMilliCredits'], MAXIMUM)

    def test_direct_unqualified_endpoint_is_verified_preio_zero(self):
        with self.http(200, b'not JSON') as calls:
            with self.assertRaises(image_runtime.ImageGenerationError) as caught:
                image_runtime.image_transport('POST', 'https://synthetic.invalid/unqualified', body={})
            self.assertEqual(calls, [])
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(caught.exception.cost_usd, 0.0)

    def test_direct_unreadable_4xx_preserves_existing_zero_refusal_classification(self):
        with self.http(429, b'unreadable refusal') as calls:
            with self.assertRaises(image_runtime.ImageGenerationError) as caught:
                self.runtime().generate('Synthetic image')
            self.assertEqual(len(calls), 1)
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(caught.exception.cost_usd, 0.0)


if __name__ == '__main__':
    unittest.main()
