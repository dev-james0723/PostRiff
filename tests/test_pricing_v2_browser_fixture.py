"""Offline fixture boundaries and source-bound real Growth/Jev router units.

FakeCursor is the only DB substitute; a constructor shell supplies attributes,
not customer responses. No PG, SQL, HTTP server, browser or external model IO.
Actual API/PG/browser coverage remains the parent-owned integration run.
"""
import ast
import copy
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/pricing_v2_browser_fixture.py'
spec = importlib.util.spec_from_file_location('pricing_v2_browser_fixture', SOURCE)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)

OFFLINE_ROUTE_COUNTS = {'defaultTransportAttempts': 0, 'supportedSyntheticAttempts': 0}


class DefaultTransportSelected(BaseException):
    """Fatal sentinel, never an HTTPS implementation or a catchable fallback."""


def fatal_default_transport(*_args, **_kwargs):
    OFFLINE_ROUTE_COUNTS['defaultTransportAttempts'] += 1
    raise DefaultTransportSelected('Legacy Growth selected the default HTTPS transport')


def constructed_growth_from_fixture():
    """Execute the fixture's exact Growth constructor expression, without PG.

    The shell supplies only constructor attributes, never customer responses or
    application behavior. All Growth/Jev/router/runtime code is the real source.
    No PricingV2Fixture constructor, connection factory or SQL is executed.
    """
    from postriff_phase2.growth.service import GrowthService
    shell = SimpleNamespace(repository=SimpleNamespace(effects=[]), clock=lambda: 1000,
                            ideas=SimpleNamespace(credit_requests=SimpleNamespace(), runtimes=[]))
    tree = ast.parse(SOURCE.read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == 'GrowthService']
    if len(calls) != 1: raise AssertionError('One source-bound Growth construction required')
    expression = ast.Expression(calls[0])
    return eval(compile(expression, str(SOURCE), 'eval'),
                {**vars(f), 'GrowthService': GrowthService, 'service': shell})


class FakeCursor:
    def __init__(self, rows=()):
        self.rows, self.calls = list(rows), []

    def execute(self, statement, params=None):
        self.calls.append((statement, params))
        if getattr(self,'result_sets',None):self.rows=list(self.result_sets.pop(0))
        return self

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        result, self.rows = self.rows, []
        return result


class RunnerTimeoutBoundaries(unittest.TestCase):
    def runner(self):
        source = SOURCE.with_name('pricing_v2_browser.py')
        spec = importlib.util.spec_from_file_location('pricing_v2_browser_timeout_units', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # Definitions only; main/ports/HTTP never run.
        return module

    def test_host_timeout_defaults_are_finite_and_preserve_operation_budget(self):
        runner = self.runner()
        with patch.object(runner, 'require_free_http_ports', side_effect=AssertionError('No port probes in units')):
            config = runner.timeout_configuration()
        self.assertEqual(config, {'startupSeconds': 120, 'browserSeconds': 1200,
                                  'actionMs': 120000, 'navigationMs': 120000})

    def test_timeouts_reject_disabled_nonfinite_noninteger_or_excessive_limits(self):
        runner = self.runner()
        for key, maximum in [('startup_seconds', 300), ('browser_seconds', 3600),
                             ('action_seconds', 300), ('navigation_seconds', 300)]:
            for value in (0, -1, True, '120', 1.5, float('nan'), float('inf'), maximum+1):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    runner.timeout_configuration(**{key: value})

    def test_browser_deadline_covers_each_configured_operation_and_has_a_hard_ceiling(self):
        runner = self.runner()
        with self.assertRaises(ValueError):
            runner.timeout_configuration(browser_seconds=119, navigation_seconds=120)
        config = runner.timeout_configuration(startup_seconds=300, browser_seconds=3600,
                                               action_seconds=150, navigation_seconds=300)
        self.assertEqual(config['navigationMs'], 300000)
        self.assertEqual(config['actionMs'], 150000)
        self.assertEqual(config['browserSeconds'], 3600)


class FixtureBoundaries(unittest.TestCase):
    def test_legacy_growth_refuses_before_default_https_evaluator_dispatch(self):
        from postriff_alpha.domain import AlphaError
        from postriff_phase2.growth.usage import MemoryUsageSink
        growth = constructed_growth_from_fixture()
        self.assertTrue(growth.enabled('rewrite'), 'Legacy flags remain truthful')
        state = {'growthConsent': {'routes': ['cloud:'+f.PROVIDER+':'+f.JEV_MODEL,
                                            'cloud:'+f.PROVIDER+':'+f.MODEL]}}
        sink = MemoryUsageSink()
        before = OFFLINE_ROUTE_COUNTS['defaultTransportAttempts']
        with patch('postriff_phase2.growth.jev.model_transport', fatal_default_transport), \
                patch('postriff_phase2.model_runtime.model_transport', fatal_default_transport):
            try:
                with self.assertRaises(AlphaError) as refused:
                    router = growth._router(sink, state, guard=lambda: None)
                    # On the reviewed source this physically reaches our fatal
                    # default-transport sentinel. No socket can be opened.
                    router.jev.evaluate({'draft': 'Owned legacy text.'},
                        {'coherent': {'type': 'boolean', 'question': 'Is it coherent?'}}, timeout_s=1)
            except DefaultTransportSelected:
                self.fail('Default HTTPS dispatch selected; fatal offline sentinel prevented external IO')
        self.assertEqual((refused.exception.status, refused.exception.code),
                         (503, 'local_synthetic_legacy_ai_unavailable'))
        self.assertEqual(OFFLINE_ROUTE_COUNTS['defaultTransportAttempts'], before)
        self.assertEqual(sink.events, [])

    def test_legacy_growth_writer_and_unscoped_routes_refuse_without_default_construction(self):
        from postriff_alpha.domain import AlphaError
        from postriff_phase2.growth.usage import MemoryUsageSink
        growth = constructed_growth_from_fixture()
        with patch('postriff_phase2.growth.service.JevService', side_effect=AssertionError('Default Jev constructed')):
            for writer in (None, f.MODEL):
                for state in (None, {'growthConsent': {'routes': ['cloud:'+f.PROVIDER+':'+f.JEV_MODEL]}}):
                    with self.subTest(writer=writer, state=state):
                        with self.assertRaises(AlphaError) as refused:
                            growth._router(MemoryUsageSink(), state, writer, guard=lambda: None)
                        self.assertEqual(refused.exception.code, 'local_synthetic_legacy_ai_unavailable')

    def qualified_bridge(self, hold_rows):
        from postriff_phase2.growth.credit_funding import RewriteFunding
        from postriff_phase2.growth.credit_policy import RewritePolicy
        from postriff_phase2.growth.usage import MemoryUsageSink
        from postriff_phase2.model_runtime import ServerModelRuntime
        order = []
        def committed(cost):
            order.append('committed-hold')
            return f.require_committed_hold(FakeCursor(hold_rows), 'unit-only-no-db', cost)
        gateway = f.SyntheticGatewayTransport(committed, clock=lambda: 1000, expires_at=4600)
        runtime = ServerModelRuntime('local-synthetic-no-provider-key', model=f.MODEL, models=[f.MODEL],
            prices={f.MODEL: (.1, .4)}, allowed_providers={f.MODEL: ['google']}, transport=gateway, clock=lambda: 1000)
        env = {'POSTRIFF_JEV': '1',
               'POSTRIFF_GROWTH_REWRITE_CREDIT_POLICY': json.dumps(f.rewrite_policy(1000))}
        gateway_key = next(value for group in f.PricingV2Fixture.__init__.__code__.co_consts if isinstance(group, tuple) for value in group if isinstance(value, str) and value.startswith('AI_GATEWAY_'))
        env[gateway_key] = 'local-synthetic-never-external'
        policy = RewritePolicy.from_env(env, 1000)
        state = {'growthConsent': {'routes': ['cloud:'+f.PROVIDER+':'+f.MODEL, 'cloud:'+f.PROVIDER+':'+f.JEV_MODEL]}}
        plan = policy.plan(runtime, f.MODEL, 2, state, env)
        self.assertEqual((plan.max_attempts, plan.maximum_micro), (13, 260000))
        def guard(task, model, route, ceiling):
            self.assertEqual((task, model, route, ceiling), ('postdoctor.judge', f.JEV_MODEL, 'primary', 20000))
            order.append('real-bridge-guard')
            # Minimal cursor is the only DB substitution: refuse before transport
            # if the actual committed-hold check finds no authority.
            f.require_committed_hold(FakeCursor(hold_rows), 'unit-only-no-db', ceiling)
        sink = MemoryUsageSink()
        funding = RewriteFunding(plan, sink, guard, now=lambda: 1000)
        router = funding.router(runtime, env)
        return funding, router, gateway, sink, order

    def test_supported_jev_bridge_uses_guarded_synthetic_hold_and_physical_metadata(self):
        rows = [(260000, f.MODEL, f.PROVIDER, {'credits': {'maximum': 78000}})]
        funding, router, gateway, sink, order = self.qualified_bridge(rows)
        before = OFFLINE_ROUTE_COUNTS['defaultTransportAttempts']
        with patch('postriff_phase2.growth.jev.model_transport', fatal_default_transport), \
                patch('postriff_phase2.model_runtime.model_transport', fatal_default_transport):
            physical = funding.invoke('postdoctor.judge', f.JEV_MODEL, 'primary', router.jev.evaluate,
                ({'draft': 'Owned local-synthetic text.'}, {'coherent': {'type': 'boolean', 'question': 'Is it coherent?'}}),
                {'timeout_s': 1}, {'workspace_id': 'unit-only-no-db', 'subject': 'local-synthetic'})
        self.assertEqual(order, ['real-bridge-guard', 'committed-hold'])
        self.assertEqual((physical.model, physical.final_provider, physical.cost_usd), (f.JEV_MODEL, 'typesafe-ai', .01))
        self.assertEqual((len(gateway.calls), gateway.external_io, len(sink.events)), (1, 0, 1))
        self.assertTrue(gateway.calls[0]['committedHold']['committedSeenViaSeparateConnection'])
        self.assertEqual(OFFLINE_ROUTE_COUNTS['defaultTransportAttempts'], before)
        OFFLINE_ROUTE_COUNTS['supportedSyntheticAttempts'] += len(gateway.calls)

    def test_supported_jev_bridge_missing_hold_refuses_before_any_physical_transport(self):
        from postriff_phase2.growth.router import RouterError
        funding, router, gateway, sink, order = self.qualified_bridge([])
        with patch('postriff_phase2.growth.jev.model_transport', fatal_default_transport), \
                patch('postriff_phase2.model_runtime.model_transport', fatal_default_transport):
            with self.assertRaises(RouterError):
                funding.invoke('postdoctor.judge', f.JEV_MODEL, 'primary', router.jev.evaluate,
                    ({'draft': 'Owned text.'}, {'coherent': {'type': 'boolean', 'question': 'Is it coherent?'}}),
                    {'timeout_s': 1}, {'workspace_id': 'unit-only-no-db', 'subject': 'local-synthetic'})
        self.assertEqual(order, ['real-bridge-guard'])
        self.assertEqual((gateway.calls, gateway.external_io, sink.events), ([], 0, []))

    def catalog_rows(self):
        return [[('creator-v1', 'proposed', False, {'monthlyCredits':3500,'creditPolicy':f.POLICY}),
                 ('starter-v1', 'active', True, {'monthlyCredits':1000}),
                 ('studio-v2', 'active', True, {'monthlyCredits':8000})],
                [(f'creator-{price}-v1','creator-v1',price*100,'proposed') for price in (49,59,79)], [(0,)]]

    def test_current_catalog_preflight_checks_real_entitlement_and_all_inactive_variants(self):
        rows=self.catalog_rows();c=FakeCursor()
        # A minimal cursor returning one distinct result-set per execute.
        c.result_sets=rows
        f.validate_catalog(c)
        self.assertEqual(len(c.calls),3)

    def test_catalog_preflight_does_not_turn_invalid_terms_or_legacy_active_pack_into_v2(self):
        for change in ('missing','credits','policy','checkout','variant','price','active-pack'):
            rows=copy.deepcopy(self.catalog_rows())
            if change=='missing':rows[0].pop()
            if change=='credits':rows[0][0][3]['monthlyCredits']=998
            if change=='policy':rows[0][0][3]['creditPolicy']='credits-candidate-2026-09-23-v1'
            if change=='checkout':rows[0][0]=(*rows[0][0][:2],True,rows[0][0][3])
            if change=='variant':rows[1][0]=(*rows[1][0][:3],'active')
            if change=='price':rows[1][0]=(rows[1][0][0],'creator-v1',1,'proposed')
            if change=='active-pack':rows[2]=[(1,)]
            c=FakeCursor();c.result_sets=rows
            with self.subTest(change=change),self.assertRaises(ValueError):f.validate_catalog(c)
            self.assertFalse(any('UPDATE' in s or 'INSERT' in s for s,_ in c.calls))

    def test_committed_hold_refuses_invalid_cost_before_cursor_access(self):
        for cost in (-1,0,True,float('nan'),float('inf'),10**15+1):
            c=FakeCursor()
            with self.subTest(cost=cost),self.assertRaises(ValueError):f.require_committed_hold(c,'wid',cost)
            self.assertEqual(c.calls,[])

    def test_finite_transport_input_output_never_dispatch_unqualified_payload(self):
        t=f.SyntheticGatewayTransport(lambda cost:self.fail('unbounded request reached hold'),clock=lambda:1000,expires_at=2000)
        body={'model':f.MODEL,'providerOptions':{'gateway':{'only':['google']}},'messages':[{'content':'{}'}],'max_tokens':4500}
        for changes in ({'max_tokens':4501},{'max_tokens':True},{'messages':[{'content':'x'*100001}]}):
            with self.subTest(change=list(changes)),self.assertRaises(ValueError):t('POST',f.ENDPOINT,body={**body,**changes})
        self.assertEqual(t.calls,[])

    def test_parent_pg_only_and_explicit_isolated_database(self):
        c = FakeCursor([('pricing_v2_local_synthetic_13', '127.0.0.1', 55439)])
        f.check_database(c, 'pricing_v2_local_synthetic_13')
        self.assertEqual(len(c.calls), 1)
        self.assertNotIn('INSERT', c.calls[0][0])

    def test_reject_foreign_pg_ports_hosts_and_database_before_writes(self):
        for row in [('pricing_v2_local_synthetic_13', '127.0.0.1', 55438),
                    ('pricing_v2_local_synthetic_13', '10.0.0.1', 55439),
                    ('production', '127.0.0.1', 55439)]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                f.check_database(FakeCursor([row]), 'pricing_v2_local_synthetic_13')

    def test_database_name_not_guessed_or_sql_interpolated(self):
        for name in ['', 'postgres', 'pricing_v2_local_synthetic_x;DROP DATABASE x', None]:
            c = FakeCursor()
            with self.subTest(name=name), self.assertRaises(ValueError):
                f.check_database(c, name)
            self.assertEqual(c.calls, [])

    def test_catalog_writes_only_seeded_creator_mapping_no_pack_enable(self):
        c = FakeCursor()
        f.prepare_catalog(c)
        sql = '\n'.join(s for s, _ in c.calls)
        self.assertNotIn('INSERT INTO public.pr_plan_terms', sql)
        self.assertNotIn('pr_credit_packs', sql)
        self.assertNotIn('new_checkout_enabled=true', sql.lower())
        self.assertNotIn('998', sql)
        self.assertEqual(c.calls[0][1], ('creator-v1',))
        self.assertEqual([p[1] for s, p in c.calls if 'pr_plan_price_variants' in s],
                         ['creator-49-v1', 'creator-59-v1', 'creator-79-v1'])

    def test_variant_assignment_is_server_allowlist(self):
        for price in (49, 59, 79):
            v = f.variant(price)
            self.assertEqual((v['terms'], v['monthlyCredits'], v['amountCents']),
                             ('creator-v1', 3500, price * 100))
        for price in (19, 39, 58, '59', True, None):
            with self.subTest(price=price), self.assertRaises(ValueError): f.variant(price)

    def test_unknown_scenario_and_client_extra_keys_refused(self):
        self.assertEqual(f.parse_seed({'scenario': 'creator-59'})['scenario'], 'creator-59')
        for body in [{'scenario': 'unknown'}, {'scenario': 'creator-59', 'priceId': 'price_external'},
                     {'scenario': 'creator-59', 'amount': 1}, [], None]:
            with self.subTest(body=body), self.assertRaises(ValueError): f.parse_seed(body)

    def test_all_required_lifecycle_states_are_named_local_synthetic(self):
        required = {'free-new', 'creator-49', 'creator-59', 'creator-79', 'creator-held',
                    'creator-pending', 'creator-settled', 'creator-over-max', 'creator-failed',
                    'legacy-19', 'legacy-39', 'trial-active', 'trial-expired', 'creator-ended-free'}
        self.assertEqual(set(f.SCENARIOS), required)
        self.assertEqual(f.EXECUTION, 'local-synthetic-real-http-pg')

    def test_signed_invoice_has_consistent_verified_line_binding_and_period(self):
        event = f.invoice_event('00000000-0000-0000-0000-000000000113', 49, 1000, 2000)
        raw, header = f.sign_event(event, 'local-synthetic-secret', 1500)
        self.assertEqual(json.loads(raw), event)
        self.assertEqual(header, 't=1500,v1=' + hmac.new(b'local-synthetic-secret', b'1500.' + raw, hashlib.sha256).hexdigest())
        invoice = event['data']['object']; line = invoice['lines']['data'][0]
        self.assertIs(event['livemode'], False)
        self.assertEqual((line['type'], line['price']['id'], invoice['amount_paid']),
                         ('subscription', 'price_local_synthetic_creator_49', 4900))
        self.assertEqual(line['period'], {'start': 1000, 'end': 2000})
        self.assertEqual(line['subscription'], invoice['subscription'])
        self.assertEqual(invoice['subscription_details']['metadata']['price_variant_id'], 'creator-49-v1')

    def test_same_invoice_distinct_event_delivery_preserves_grant_identity(self):
        a = f.invoice_event('00000000-0000-0000-0000-000000000113', 59, 1000, 2000)
        b = copy.deepcopy(a); b['id'] += '_redelivery'
        self.assertNotEqual(a['id'], b['id'])
        self.assertEqual(a['data']['object']['id'], b['data']['object']['id'])

    def test_preview_policy_has_actual_finite_schema_no_invented_expiry(self):
        p = f.preview_policy(False)
        self.assertNotIn('expiresAt', p)
        self.assertIs(p['paidBaseChecks'], False)
        self.assertTrue(f.preview_policy(True)['paidBaseChecks'])
        for k in ('attemptMaxUsdMicro', 'dailyUsdMicro', 'monthlyUsdMicro', 'dailyRuns',
                  'workspaceDailyRuns', 'maxInputBytes', 'maxOutputTokens'):
            self.assertGreater(p[k], 0)
        self.assertGreaterEqual(p['dailyUsdMicro'], p['attemptMaxUsdMicro'] * 40)

    def test_qualification_pins_current_real_model_route_and_synthetic_prices(self):
        q = f.runtime_contract(1000)
        self.assertEqual(q['model'], 'google/gemini-2.5-flash-lite')
        self.assertEqual(q['provider'], 'vercel-ai-gateway')
        self.assertEqual(q['executionProvider'], 'google')
        self.assertEqual(q['prices'], (0.1, 0.4))
        self.assertEqual(q['expiresAt'], 1000 + 3600)
        self.assertEqual(q['evidence'], 'local-synthetic-pinned-table-not-live-price-qualification')

    def test_no_external_stripe_io_and_counts_are_truthful(self):
        transport = f.SyntheticStripeTransport()
        with self.assertRaises(RuntimeError):
            transport('POST', 'https://api.stripe.com/v1/checkout/sessions', form={})
        self.assertEqual(transport.attempts, 1)
        self.assertEqual(transport.external_io, 0)

    def test_fake_transport_refuses_unapproved_url_model_provider_before_dispatch(self):
        t = f.SyntheticGatewayTransport(lambda: None, clock=lambda: 1000, expires_at=2000)
        body = {'model': f.MODEL, 'providerOptions': {'gateway': {'only': ['google']}},
                'messages': [{'content': '{}'}], 'max_tokens': 100}
        for change in [{'model': 'unqualified/new-model'}, {'providerOptions': {'gateway': {'only': ['other']}}}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                t('POST', f.ENDPOINT, body={**body, **change})
        with self.assertRaises(ValueError): t('POST', 'https://foreign.invalid', body=body)
        self.assertEqual(t.calls, [])

    def test_transport_expiry_checked_before_hold_or_dispatch(self):
        t = f.SyntheticGatewayTransport(lambda: self.fail('expired transport consulted hold'),
                                        clock=lambda: 2000, expires_at=2000)
        with self.assertRaises(ValueError): t('POST', f.ENDPOINT, body={})
        self.assertEqual(t.calls, [])

    def test_missing_committed_hold_prevents_actual_synthetic_writer(self):
        c = FakeCursor([])
        with self.assertRaises(ValueError): f.require_committed_hold(c, 'wid', 10000)
        self.assertIn("kind='reserve'", c.calls[0][0])
        self.assertIn("('actual','released')", c.calls[0][0])

    def test_committed_hold_requires_max_and_exact_current_route(self):
        for row in [(9000, f.MODEL, f.PROVIDER, {'credits': {'maximum': 3000}}),
                    (20000, 'invented', f.PROVIDER, {'credits': {'maximum': 6000}}),
                    (20000, f.MODEL, 'invented', {'credits': {'maximum': 6000}}),
                    (20000, f.MODEL, f.PROVIDER, {}),
                    (20000, f.MODEL, f.PROVIDER, {'credits': {'maximum': 2999}})]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                f.require_committed_hold(FakeCursor([row]), 'wid', 10000)
        f.require_committed_hold(FakeCursor([(20000, f.MODEL, f.PROVIDER, {'credits': {'maximum': 6000}})]), 'wid', 10000)

    def test_ambiguous_multiple_holds_refuse(self):
        row = (20000, f.MODEL, f.PROVIDER, {'credits': {'maximum': 6000}})
        with self.assertRaises(ValueError): f.require_committed_hold(FakeCursor([row, row]), 'wid', 10000)

    def test_physical_metadata_and_cost_are_from_server_synthetic_response(self):
        def committed(cost):
            return f.require_committed_hold(FakeCursor([(20000,f.MODEL,f.PROVIDER,{'credits':{'maximum':6000}})]),'wid',cost)
        t = f.SyntheticGatewayTransport(committed, clock=lambda: 1000, expires_at=2000)
        body = {'model': f.MODEL, 'providerOptions': {'gateway': {'only': ['google']}},
                'max_tokens': 2400, 'messages': [{'content': '{}'},
                {'content': json.dumps({'destinations': [{'platform': 'Threads', 'languageId': 'en'}]})}]}
        result = t('POST', f.ENDPOINT, body=body)['body']
        gateway = result['providerMetadata']['gateway']
        self.assertEqual((gateway['cost'], gateway['routing']['finalProvider']), (0.01, 'google'))
        self.assertEqual((len(t.calls), t.external_io), (1, 0))
        self.assertTrue(t.calls[0]['committedHold']['committedSeenViaSeparateConnection'])
        text = json.loads(result['choices'][0]['message']['content'])['variants'][0]['text']
        self.assertIn('local-synthetic', text)

    def test_auth_control_requires_secret_loopback_exact_origin_and_method(self):
        valid = {'REMOTE_ADDR': '127.0.0.1', 'HTTP_ORIGIN': 'http://127.0.0.1:4439',
                 'HTTP_X_PRICING_V2_FIXTURE': 's' * 32, 'REQUEST_METHOD': 'POST'}
        f.require_control(valid, 's' * 32, 'http://127.0.0.1:4439')
        for delta in [{'REMOTE_ADDR': '8.8.8.8'}, {'HTTP_ORIGIN': 'https://prod.invalid'},
                      {'HTTP_X_PRICING_V2_FIXTURE': ''}, {'REQUEST_METHOD': 'GET'}]:
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                f.require_control({**valid, **delta}, 's' * 32, 'http://127.0.0.1:4439')


if __name__ == '__main__': unittest.main()
