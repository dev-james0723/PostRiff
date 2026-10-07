"""Customer risk flags (CONTRACTS §8.C, PRD §7.4) without PostgreSQL: versioned observed rules and the at-risk hypothesis,
saved views bounded to 200 with every chip on each row, Demo from the Demo dataset, Live over fixed reader statements
(a missing source says so and flags nobody), and the route's capability and validation."""
from datetime import datetime, timezone
import unittest
import uuid

import psycopg

from rafii_control import founder_risk as risk, http
from rafii_control.auth import ControlError
from rafii_control.intelligence import Catalog, QueryService

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
AS_OF = '2026-10-01T12:00:00Z'


class Store:
    environment = 'local'

    def __init__(self):
        self.rows, self.missing, self.statements = {}, set(), []

    def read(self, kind, identifier=None):
        return []

    def receipt(self, receipt):
        pass

    def metric_rows(self, statement, params, limit=1000):
        self.statements.append((statement.metric_id, statement.sql, list(params)))
        if any(view in statement.sql for view in self.missing):
            raise psycopg.errors.UndefinedTable('relation does not exist')
        rows = self.rows.get(statement.metric_id, [])
        rows = rows(statement, params) if callable(rows) else rows
        return [dict(row) for row in rows]


def demo_data(count=30, studio=3):
    data = dict(mode='demo', asOf=AS_OF, receipt={'id': 'demo-receipt'}, workspaces=[], subscriptions=[], payments=[], usage=[], activity=[])
    for i in range(1, count + 1):
        wid = f'workspace-{i}'
        plan, price = ('Studio', 14900) if i <= studio else ('Starter', 2900)
        old = i in (6, 8)
        data['workspaces'].append(dict(id=wid, name=f'Company {i}', ownerId=f'customer-{i}', plan=plan, status='active', createdAt='2025-01-01T09:00:00Z',
                                       creditsQuota=1000, creditsUsed=900 if i in (4, 5) else 100))
        data['subscriptions'].append(dict(id=f'sub-{i}', workspaceId=wid, plan=plan, status='past_due' if i == 6 else 'active', paid=True, amountMinor=price,
                                          currency='USD', startedAt='2025-01-01T09:00:00Z'))
        data['payments'].append(dict(id=f'pay-{i}', workspaceId=wid, status='failed' if i == 7 else 'funded', amountMinor=price, currency='USD', at='2026-10-01T08:00:00Z'))
        data['usage'].append(dict(id=f'u-{i}', workspaceId=wid, kind='settle', costState='simulated', actualUsdMicro=None, estimatedUsdMicro=1000 * i,
                                  at='2026-08-01T12:00:00Z' if old else AS_OF))
        if not old:
            data['activity'].append(dict(id=f'a-{i}', workspaceId=wid, at='2026-10-01T08:00:00Z'))
    data['usage'].append(dict(id='u-unknown', workspaceId='workspace-9', kind='settle', costState='estimated_unknown', estimatedUsdMicro=777, at='2026-09-30T12:00:00Z'))
    return data


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.service = QueryService(self.store, Catalog(), clock=lambda: NOW)
        self.app = type('App', (), {'queries': self.service})()
        self.principal = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['control.read', 'metrics.query', 'customers.read', 'workspaces.read']},
                          'session': {'environment': 'local', 'id': str(uuid.uuid4())}}

    def call(self, view=None, mode='live'):
        query = {} if view is None else {'view': [view]}
        return risk.customers_risk(self.app, self.principal, dict(mode=mode, query=query, method='GET', path='/customers/risk'))

    def demo(self, view, data=None):
        data = data or demo_data()
        self.service.demo_data = lambda principal: data
        return self.call(view, mode='demo')

    def test_rules_are_versioned_explainable_and_the_route_is_registered(self):
        self.assertEqual(risk.RULE_IDS, ('high_value', 'high_ai_cost', 'quota_near_limit', 'inactive', 'payment_risk', 'connection_risk', 'unknown_cost_holds', 'at_risk'))
        self.assertEqual([rule['basis'] for rule in risk.RULES].count('hypothesis'), 1)
        self.assertTrue(all(rule['trigger'] and rule['label'] for rule in risk.RULES))
        self.assertEqual(set(risk.VIEWS) >= {'high_value', 'high_ai_cost', 'quota_80', 'inactive_30d', 'payment_risk', 'at_risk'}, True)
        route, _ = http.extension_route('/customers/risk', 'GET')
        self.assertEqual((route[2], route[3], route[4]), ('customers.read', 'founder_risk', 'customers_risk'))
        self.assertEqual(http.ControlApplication._capability('/customers/risk', 'GET'), 'customers.read')

    # -- Demo ----------------------------------------------------------------------------------------------------------
    def test_demo_saved_views_flag_exactly_the_matching_workspaces_with_evidence_and_since(self):
        high = self.demo('high_value')
        self.assertEqual((high['mode'], high['view'], high['_dataState'], high['_receiptIds'], high['rulesVersion']), ('demo', 'high_value', 'synthetic', ['demo-receipt'], 'v1'))
        self.assertEqual([row['workspaceId'] for row in high['rows']], ['workspace-1', 'workspace-2', 'workspace-3'])
        flag = high['rows'][0]['flags'][0]
        self.assertEqual((flag['id'], flag['version'], flag['basis'], flag['since']), ('high_value', 'v1', 'observed', '2025-01-01T09:00:00Z'))
        self.assertEqual((flag['evidence']['highestTier'], flag['evidence']['tierPriceMinor'], flag['evidence']['cashMtdMinor'], flag['evidence']['p90CashMtdMinor']),
                         (True, 14900, 14900, 5300.0))
        self.assertEqual(high['rows'][0]['name'], 'Company 1')
        quota = self.demo('quota_80')
        self.assertEqual([row['workspaceId'] for row in quota['rows']], ['workspace-4', 'workspace-5'])
        self.assertEqual(quota['rows'][0]['flags'][0]['evidence'], {'creditsUsed': 900, 'creditsQuota': 1000, 'usedShare': 0.9, 'source': 'demo_credits'})
        cost = self.demo('high_ai_cost')
        self.assertEqual(cost['rows'][0]['workspaceId'], 'workspace-30', 'the most expensive workspace first')
        self.assertNotIn('workspace-6', [row['workspaceId'] for row in cost['rows']], 'cost outside the 30 days does not count')
        inactive = self.demo('inactive_30d')
        self.assertEqual(sorted(row['workspaceId'] for row in inactive['rows']), ['workspace-6', 'workspace-8'])
        self.assertEqual(inactive['rows'][0]['flags'][0]['evidence']['lastActiveAt'], '2026-08-01T12:00:00Z')
        payment = self.demo('payment_risk')
        self.assertEqual(sorted(row['workspaceId'] for row in payment['rows']), ['workspace-6', 'workspace-7'])
        unknown = self.demo('unknown_cost')
        self.assertEqual([(row['workspaceId'], row['flags'][0]['evidence']['unknownEstimateUsdMicro']) for row in unknown['rows'] if row['flags'][0]['id'] == 'unknown_cost_holds'],
                         [('workspace-9', 777)])

    def test_at_risk_is_a_named_hypothesis_and_every_row_carries_all_its_chips(self):
        at_risk = self.demo('at_risk')
        self.assertEqual([row['workspaceId'] for row in at_risk['rows']], ['workspace-6'])
        flags = {flag['id']: flag for flag in at_risk['rows'][0]['flags']}
        self.assertEqual(set(flags), {'inactive', 'payment_risk', 'at_risk'})
        self.assertEqual((flags['at_risk']['basis'], flags['at_risk']['evidence']['because']), ('hypothesis', ['inactive', 'payment_risk']))
        states = {rule['id']: rule for rule in at_risk['rules']}
        self.assertEqual((states['connection_risk']['state'], states['connection_risk']['reason']), ('unavailable', 'demo_not_simulated'))
        self.assertEqual(states['at_risk']['state'], 'partial', 'connection risk is not simulated in Demo')
        payment = self.demo('payment_risk')
        row = next(row for row in payment['rows'] if row['workspaceId'] == 'workspace-6')
        self.assertEqual([flag['id'] for flag in row['flags']], ['inactive', 'payment_risk', 'at_risk'], 'phase two adds the other chips in rule order')
        flagged = self.demo('flagged')
        self.assertEqual(flagged['rows'][0]['workspaceId'], 'workspace-6', 'most flags first')
        self.assertEqual(flagged['rows'][0]['flagCount'], 3)
        self.assertEqual(set(row['workspaceId'] for row in flagged['rows']) >= {'workspace-1', 'workspace-4', 'workspace-7', 'workspace-8', 'workspace-9', 'workspace-30'}, True)
        self.assertNotIn('workspace-10', [row['workspaceId'] for row in flagged['rows']])

    def test_views_are_bounded_to_two_hundred_rows(self):
        result = self.demo('high_value', demo_data(count=260, studio=250))
        self.assertEqual((len(result['rows']), result['total'], result['truncated'], result['limit']), (200, 250, True, 200))

    def test_validation_and_capabilities(self):
        with self.assertRaises(ControlError) as raised:
            self.demo('everyone')
        self.assertEqual(raised.exception.status, 400)
        self.principal['operator']['capabilities'].remove('workspaces.read')
        self.assertEqual(self.demo('flagged')['mode'], 'demo')
        with self.assertRaises(ControlError):
            self.call('flagged', mode='live')
        self.principal['operator']['capabilities'] = ['control.read', 'workspaces.read']
        with self.assertRaises(ControlError):
            self.demo('flagged')

    # -- Live ----------------------------------------------------------------------------------------------------------
    def test_live_runs_fixed_statements_phase_two_restricted_and_missing_sources_say_so(self):
        self.store.missing = {'business_payments_v2'}
        self.store.rows.update({'customer_risk.tier': [dict(wid='w1', since='2026-01-02T00:00:00+00:00', plan='Studio', price=14900, currency='USD')],
                                'customer_risk.workspaces': [dict(id='w1', name='Fern Studio', ownerId='u1', plan='Studio', status='active', createdAt='2025-12-01T00:00:00+00:00')],
                                'customer_risk.ledger': lambda statement, params: [dict(wid='w1', since='2026-09-30T00:00:00+00:00', rows=2, estimate=1500)] if ['w1'] in params else []})
        result = self.call('high_value')
        self.assertEqual([row['workspaceId'] for row in result['rows']], ['w1'])
        self.assertEqual([flag['id'] for flag in result['rows'][0]['flags']], ['high_value', 'unknown_cost_holds'])
        self.assertEqual(result['rows'][0]['name'], 'Fern Studio')
        rules = {rule['id']: rule for rule in result['rules']}
        self.assertEqual((rules['high_value']['state'], rules['high_value']['reason']), ('partial', 'source_not_configured'), 'cash comes from the purchase views')
        self.assertEqual(result['_dataState'], 'partial')
        phase_one = [params for name, _, params in self.store.statements if name == 'customer_risk.tier']
        self.assertEqual(phase_one[0][:2], [None, None], 'phase one evaluates every workspace')
        phase_two = [params for name, _, params in self.store.statements if name == 'customer_risk.activity']
        self.assertIn(['w1'], phase_two[0], 'phase two is restricted to the shown workspaces')
        for name, sql, params in self.store.statements:
            with self.subTest(statement=name):
                if name != 'customer_risk.workspaces':
                    self.assertIn("c.kind IN ('internal','test','demo')", sql)
                self.assertNotIn('high_value', sql)
                self.assertEqual(sql.count('%s'), len(params))
                self.assertTrue(sql.rstrip().endswith('LIMIT %s'))

    def test_live_at_risk_checks_inactivity_for_payment_and_connection_candidates_and_falls_back_to_reconnect_events(self):
        self.store.missing = {'business_connection_health'}
        self.store.rows.update({'customer_risk.subscription': [dict(wid='w2', since='2026-09-20T00:00:00+00:00', status='past_due', cancelling=False)],
                                'customer_risk.reconnect_events': [dict(wid='w3', since='2026-09-25T00:00:00+00:00', events=1)],
                                'customer_risk.activity': lambda statement, params: [dict(wid='w2', created='2025-01-01T00:00:00+00:00', last_at='2026-08-01T00:00:00+00:00')]
                                if ['w2', 'w3'] in params else []})
        result = self.call('at_risk')
        self.assertEqual([row['workspaceId'] for row in result['rows']], ['w2'])
        flags = {flag['id']: flag for flag in result['rows'][0]['flags']}
        self.assertEqual(flags['at_risk']['evidence']['because'], ['inactive', 'payment_risk'])
        self.assertEqual(flags['at_risk']['since'], '2026-09-20T00:00:00Z', 'since: when every condition held')
        self.assertEqual(flags['inactive']['evidence']['daysInactive'], 61)
        rules = {rule['id']: rule for rule in result['rules']}
        self.assertEqual((rules['connection_risk']['state'], rules['connection_risk'].get('fallback')), ('measured', 'reconnect_events'))
        self.assertEqual(rules['at_risk']['state'], 'measured')

    def test_a_view_whose_only_source_is_missing_is_unavailable_never_empty_and_measured(self):
        self.store.missing = {'business_budgets'}
        result = self.call('quota_80')
        self.assertEqual((result['rows'], result['_dataState']), ([], 'unavailable'))
        self.assertEqual({rule['id']: rule['state'] for rule in result['rules']}['quota_near_limit'], 'unavailable')
        self.store.missing = set()
        measured = self.call('quota_80')
        self.assertEqual((measured['rows'], measured['_dataState'], measured['total']), ([], 'measured', 0))


if __name__ == '__main__':
    unittest.main()
