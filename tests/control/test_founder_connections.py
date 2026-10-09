"""Founder Connections attention queue and approval registry (Rafii API connections ENGINEERING-SPEC §13.2-§13.3; A29-A31).
No PostgreSQL: a reader stub answers the two fixed projection statements; incidents come from a stub founder store.
"""
import json
import types
import unittest
import uuid

import psycopg

from rafii_control import founder_connections as fc
from rafii_control import http, slices
from rafii_control.auth import ControlError
from rafii_control.store import MetricStatement

NOW = 1_791_000_000.0          # 2026-10-03T…Z; any fixed epoch works, nothing reads the wall clock
DAY = 86400
PRINCIPAL = {'operator': {'user_id': str(uuid.uuid4()), 'capabilities': ['control.read']}, 'session': {'environment': 'local', 'id': str(uuid.uuid4())}}


class ReaderStub:
    def __init__(self, coverage=None, rows=(), missing=False):
        self.coverage, self.rows, self.missing, self.statements = coverage, list(rows), missing, []

    def metric_rows(self, statement, params, limit=1000):
        assert isinstance(statement, MetricStatement)
        self.statements.append((statement.metric_id, statement.sql, list(params), limit))
        if self.missing:
            raise psycopg.errors.UndefinedTable('relation does not exist')
        if statement.metric_id.endswith(':coverage'):
            return [self.coverage or {'latest': None, 'total': 0}]
        if len(self.rows) > limit:
            raise ControlError('BUDGET_EXCEEDED', 400)
        return list(self.rows)


class FounderStoreStub:
    def __init__(self, incidents=(), fail=False):
        self.incidents, self.fail = list(incidents), fail

    def open_incidents(self):
        if self.fail:
            raise psycopg.OperationalError('down')
        return list(self.incidents)


def app_for(reader, fstore):
    return types.SimpleNamespace(queries=types.SimpleNamespace(store=reader), founder_store=lambda: fstore,
                                 boundary=types.SimpleNamespace(config=types.SimpleNamespace(environment='production')))


def row(wid, cid, provider, cstate):
    return {'wid': wid, 'cid': cid, 'provider': provider, 'cstate': cstate, 'at': None}


def approved(kind, scopes, *, checked=NOW - DAY, decided=NOW - 30 * DAY, ref='receipt:example/1', status='approved', **extra):
    return {'status': status, 'approvedScopes': list(scopes), 'decidedAt': decided, 'providerReceiptRef': ref, 'verifiedBy': 'operator',
            'evidenceObservedAt': decided, 'lastCheckedAt': checked, 'evidenceSource': 'provider_console_receipt', **extra}


class FreshnessTests(unittest.TestCase):
    def test_fresh_stale_and_unknown_states(self):
        fresh = fc.freshness(now=NOW, observed_at=NOW - 600, stale_after=7200, cadence=3600, source='s')
        self.assertEqual((fresh['freshness'], fresh['ageSeconds']), ('fresh', 600))
        self.assertTrue(fc.green(fresh))
        stale = fc.freshness(now=NOW, observed_at=NOW - 7201, stale_after=7200, source='s')
        self.assertEqual((stale['freshness'], stale['reason']), ('stale', 'stale_after_exceeded'))
        self.assertFalse(fc.green(stale))
        missing = fc.freshness(now=NOW, observed_at=None, stale_after=7200, source='s')
        self.assertEqual((missing['freshness'], missing['reason'], missing['observedAt']), ('unknown', 'missing_timestamp', None))

    def test_clock_skew_and_impossible_order_are_unknown_not_fresh(self):
        future = fc.freshness(now=NOW, observed_at=NOW + 3600, stale_after=7200, source='s')
        self.assertEqual((future['freshness'], future['reason']), ('unknown', 'clock_skew'))
        within = fc.freshness(now=NOW, observed_at=NOW + 60, stale_after=7200, source='s')
        self.assertEqual(within['freshness'], 'fresh', 'small skew inside the tolerance is accepted')
        backwards = fc.freshness(now=NOW, observed_at=NOW - 60, last_checked_at=NOW - 7200, stale_after=7200 * 10, source='s')
        self.assertEqual(backwards['reason'], 'check_precedes_observation')

    def test_failed_check_does_not_refresh_evidence(self):
        # The caller passes the last successful check; an old observation with an old check stays stale.
        envelope = fc.freshness(now=NOW, observed_at=NOW - 9 * DAY, last_checked_at=NOW - 8 * DAY, stale_after=7 * DAY, source='s')
        self.assertEqual(envelope['freshness'], 'stale')
        self.assertEqual(envelope['observedAt'], fc._iso(NOW - 9 * DAY))

    def test_partial_coverage_is_never_green(self):
        envelope = fc.freshness(now=NOW, observed_at=NOW - 60, stale_after=7200, source='s', coverage='partial')
        self.assertEqual(envelope['freshness'], 'fresh')
        self.assertFalse(fc.green(envelope))
        self.assertEqual(fc.freshness(now=NOW, observed_at=NOW, stale_after=1, source='s', coverage='unknown')['freshness'], 'unknown')


class RegistryTests(unittest.TestCase):   # A31
    YT_SCOPES = ['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube.readonly']

    def entry(self, decisions):
        adapters = {'youtube': types.SimpleNamespace(documented_scopes=tuple(self.YT_SCOPES), SCOPES={})}
        return [e for e in fc.registry_entries(adapters, decisions) if e['provider'] == 'youtube']

    def test_shipped_registry_records_no_approval_and_nothing_is_green(self):
        evaluated = fc.evaluate_registry(fc.registry_entries(), NOW)
        self.assertGreater(len(evaluated), 5)
        self.assertFalse(any(app['readiness'] == 'ready' for app in evaluated))
        standings = {req['standing'] for app in evaluated for req in app['requirements']}
        self.assertEqual(standings, {'check_required'})
        self.assertTrue(all(req['nextAction']['requiresHuman'] for app in evaluated for req in app['requirements']))
        sign_in = next(app for app in evaluated if app['appRef'] == 'rafii-sign-in')
        self.assertEqual(sorted(req['kind'] for req in sign_in['requirements']), ['brand_verification', 'callback_registration', 'domain_ownership'])

    def test_brand_approved_does_not_approve_sensitive_scopes(self):
        decisions = {('youtube', 'youtube', 'production', 'brand_verification'): approved('brand_verification', [])}
        app = fc.evaluate_registry(self.entry(decisions), NOW)[0]
        by_kind = {req['kind']: req for req in app['requirements']}
        self.assertEqual(by_kind['brand_verification']['standing'], 'satisfied')
        self.assertEqual(by_kind['sensitive_scope']['standing'], 'check_required')
        self.assertNotEqual(app['readiness'], 'ready')
        self.assertIn('sensitive_scope', app['unsatisfied'])

    def test_each_requirement_is_judged_separately(self):
        decisions = {
            ('youtube', 'youtube', 'production', 'sensitive_scope'): approved('sensitive_scope', self.YT_SCOPES[:1]),                    # scope gap
            ('youtube', 'youtube', 'production', 'production_audience'): approved('production_audience', [], status='testing_only'),      # app-role only
            ('youtube', 'youtube', 'production', 'callback_registration'): approved('callback_registration', [], environment='staging'),  # wrong env
            ('youtube', 'youtube', 'production', 'api_audit'): {'status': 'submitted', 'requestedAt': NOW - DAY},
            ('youtube', 'youtube', 'production', 'domain_ownership'): approved('domain_ownership', [], checked=NOW - 8 * DAY),             # stale
            ('youtube', 'youtube', 'production', 'quota_entitlement'): approved('quota_entitlement', [], ref='https://x.example/?token=1'),  # bad ref
            ('youtube', 'youtube', 'production', 'brand_verification'): approved('brand_verification', [], expiresAt=NOW - 1),
        }
        app = fc.evaluate_registry(self.entry(decisions), NOW)[0]
        got = {req['kind']: (req['standing'], req['blockers']) for req in app['requirements']}
        self.assertEqual(got['sensitive_scope'], ('blocked', ['approved_scopes_do_not_cover_request']))
        self.assertEqual(got['production_audience'], ('blocked', ['testing_only_audience']))
        self.assertEqual(got['callback_registration'], ('blocked', ['environment_mismatch']))
        self.assertEqual(got['api_audit'], ('pending', ['provider_decision_pending']))
        self.assertEqual(got['domain_ownership'], ('stale', ['applicability_not_rechecked']))
        self.assertEqual(got['quota_entitlement'], ('check_required', ['decision_receipt_missing']))
        self.assertEqual(got['brand_verification'], ('blocked', ['approval_expired']))
        self.assertEqual(app['readiness'], 'blocked')
        missing = next(req for req in app['requirements'] if req['kind'] == 'sensitive_scope')['missingScopes']
        self.assertEqual(missing, [self.YT_SCOPES[1]])

    def test_ready_only_when_every_requirement_is_fresh_and_receipted(self):
        kinds = fc.REGISTRY_KINDS['youtube']
        decisions = {('youtube', 'youtube', 'production', kind): approved(kind, self.YT_SCOPES) for kind in kinds}
        app = fc.evaluate_registry(self.entry(decisions), NOW)[0]
        self.assertEqual(app['readiness'], 'ready')
        self.assertEqual(app['unsatisfied'], [])
        self.assertTrue(all(fc.green(req['freshness']) for req in app['requirements']))

    def test_unknown_values_are_rejected(self):
        with self.assertRaises(ValueError):
            fc.evaluate_requirement({'kind': 'vibes', 'status': 'approved'}, NOW, environment='production')
        with self.assertRaises(ValueError):
            fc.evaluate_requirement({'kind': 'app_review', 'status': 'green'}, NOW, environment='production')


class QueueTests(unittest.TestCase):   # A29
    def test_union_counts_distinct_tenants_and_connections(self):
        rows = [row('w1', 'c1', 'linkedin', 'token_expired'), row('w1', 'c2', 'linkedin', 'token_expired'),   # same tenant, two connections
                row('w1', 'c3', 'youtube', 'scope_missing'), row('w2', 'c4', 'youtube', 'scope_missing'),
                row('w9', 'c9', 'x', 'read_verified')]                                                         # healthy: not an item
        items, envelope = fc.connection_items(rows, {'latest': NOW - 600}, NOW, 'production')
        self.assertEqual(envelope['freshness'], 'fresh')
        by = {(i['provider'], i['safeReasonCode']): i for i in items}
        self.assertEqual(set(by), {('linkedin', 'token_expired'), ('youtube', 'scope_missing')})
        linked = by[('linkedin', 'token_expired')]['affected']
        self.assertEqual((linked['tenants'], linked['connections']), ({'value': 1, 'countState': 'exact'}, {'value': 2, 'countState': 'exact'}))
        self.assertEqual(linked['users'], {'value': None, 'countState': 'unknown'}, 'users are not in the projection: unknown, never 0')
        result = fc.queue(items)
        self.assertEqual(result['summary']['tenants'], {'value': 2, 'countState': 'exact'}, 'w1 counted once across items (union, not a sum of 1 + 2)')
        self.assertNotIn('_tenantKeys', json.dumps(result['items']))
        self.assertNotIn('w1', json.dumps(result['items']), 'no workspace identifiers leave the queue')

    def test_priority_order_owner_and_ack_semantics(self):
        envelope = fc.freshness(now=NOW, observed_at=NOW - 60, stale_after=3600, source='s')
        p3 = fc.item(category='stale_telemetry', priority='P3', environment='e', title='t', reason='r3', summary='s', owner_lane='ops', next_action={}, envelope=envelope)
        p2_small = fc.item(category='reconnect_required', priority='P2', environment='e', title='t', reason='r2a', summary='s', owner_lane='connections', next_action={},
                           envelope=envelope, tenants=fc.count(1, 'exact'), tenant_keys=['a'])
        p2_big = fc.item(category='reconnect_required', priority='P2', environment='e', title='t', reason='r2b', summary='s', owner_lane='connections', next_action={},
                         envelope=envelope, tenants=fc.count(5, 'exact'), tenant_keys=['a', 'b', 'c', 'd', 'e'])
        blocker = fc.item(category='launch_blocker', priority='P2', environment='e', title='t', reason='r2c', summary='s', owner_lane='provider_app_owner', next_action={},
                          envelope=envelope, launch_blocker=True)
        p1_acked = fc.item(category='publishing', priority='P1', environment='e', title='t', reason='r1', summary='s', owner_lane='publishing', next_action={},
                           envelope=envelope, state='acknowledged', jobs=fc.count(3, 'estimated'))
        result = fc.queue([p3, p2_small, blocker, p2_big, p1_acked])
        self.assertEqual([i['safeReasonCode'] for i in result['items']], ['r1', 'r2c', 'r2b', 'r2a', 'r3'])
        self.assertEqual(result['items'][0]['state'], 'acknowledged', 'acknowledged items stay visible: acknowledgement is not resolution')
        self.assertEqual(result['items'][0]['owner'], {'lane': 'publishing', 'assigneeRef': None, 'assignmentState': 'unassigned', 'label': fc.UNASSIGNED})
        self.assertEqual(result['summary']['unassigned'], 5)
        self.assertEqual(result['summary']['launchBlockers'], 1)
        self.assertEqual(result['summary']['tenants'], {'value': 5, 'countState': 'lower_bound'},
                         'a job-impact item without tenant identities makes the union a lower bound')

    def test_counts_never_turn_unknown_into_zero(self):
        self.assertEqual(fc.count(7, 'unknown'), {'value': None, 'countState': 'unknown'})
        with self.assertRaises(ValueError):
            fc.count(1, 'guess')
        result = fc.queue([])
        self.assertEqual(result['summary']['tenants'], {'value': 0, 'countState': 'exact'})

    def test_limit_and_dedupe_key_are_stable(self):
        envelope = fc.freshness(now=NOW, observed_at=NOW, stale_after=60, source='s')
        items = [fc.item(category='stale_telemetry', priority='P3', environment='e', title='t', reason=f'r{n}', summary='s', owner_lane='ops', next_action={}, envelope=envelope)
                 for n in range(fc.MAX_ITEMS + 5)]
        result = fc.queue(items)
        self.assertEqual((len(result['items']), result['truncated'], result['total']), (fc.MAX_ITEMS, True, fc.MAX_ITEMS + 5))
        again = fc.item(category='stale_telemetry', priority='P3', environment='e', title='other', reason='r0', summary='x', owner_lane='ops', next_action={}, envelope=envelope)
        self.assertEqual(again['id'], items[0]['id'])


class StaleTelemetryTests(unittest.TestCase):   # A30
    def test_stale_projection_keeps_last_known_counts_and_adds_a_stale_item(self):
        items, envelope = fc.connection_items([row('w1', 'c1', 'linkedin', 'token_expired')], {'latest': NOW - 3 * 3600}, NOW, 'production')
        self.assertEqual(envelope['freshness'], 'stale')
        reconnect = next(i for i in items if i['category'] == 'reconnect_required')
        self.assertEqual(reconnect['freshness']['freshness'], 'stale')
        self.assertFalse(fc.green(reconnect['freshness']))
        stale = next(i for i in items if i['category'] == 'stale_telemetry')
        self.assertEqual((stale['priority'], stale['safeReasonCode']), ('P3', 'connection_health_stale_after_exceeded'))

    def test_missing_projection_is_unknown_impact_not_all_clear(self):
        items, envelope, state = fc.read_connection_health(types.SimpleNamespace(store=ReaderStub(missing=True)), NOW, 'production')
        self.assertEqual((state, envelope['freshness']), ('source_not_configured', 'unknown'))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['affected']['connections'], {'value': None, 'countState': 'unknown'})
        self.assertEqual(fc.queue(items)['summary']['tenants'], {'value': None, 'countState': 'unknown'}, 'nothing observed: unknown, not "at least 0"')

    def test_empty_projection_is_not_instrumented(self):
        items, envelope, state = fc.read_connection_health(types.SimpleNamespace(store=ReaderStub(coverage={'latest': None, 'total': 0})), NOW, 'production')
        self.assertEqual((state, envelope['freshness'], envelope['reason']), ('not_instrumented', 'unknown', 'missing_timestamp'))
        self.assertEqual([i['category'] for i in items], ['stale_telemetry'])

    def test_truncated_read_reports_lower_bounds(self):
        rows = [row(f'w{n}', f'c{n}', 'linkedin', 'token_expired') for n in range(4)]
        original = fc.MAX_CONNECTION_ROWS
        fc.MAX_CONNECTION_ROWS = 3
        try:
            reader = ReaderStub(coverage={'latest': fc._iso(NOW - 60), 'total': 4}, rows=rows)
            items, envelope, _ = fc.read_connection_health(types.SimpleNamespace(store=reader), NOW, 'production')
        finally:
            fc.MAX_CONNECTION_ROWS = original
        reconnect = next(i for i in items if i['category'] == 'reconnect_required')
        self.assertEqual(reconnect['affected']['tenants'], {'value': 3, 'countState': 'lower_bound'})
        self.assertEqual(envelope['coverage'], 'partial')
        self.assertEqual(reader.statements[1][2], [sorted(fc.CONNECTION_ATTENTION), 4])

    def test_statements_are_fixed_and_exclude_internal_workspaces(self):
        reader = ReaderStub(coverage={'latest': fc._iso(NOW - 60), 'total': 1}, rows=[row('w1', 'c1', 'linkedin', 'token_expired')])
        fc.read_connection_health(types.SimpleNamespace(store=reader), NOW, 'production')
        coverage_sql, rows_sql = reader.statements[0][1], reader.statements[1][1]
        self.assertIn('rafii_control.workspace_classifications', rows_sql, 'item rows exclude internal/test/demo workspaces')
        self.assertNotIn('"workspaceId" AS', coverage_sql, 'the coverage probe returns aggregates only, never identifiers')
        for _, sql, _, _ in reader.statements:
            self.assertNotIn('ciphertext', sql)
            self.assertNotIn('pr_encrypted_credentials', sql)


class ReviewFindingTests(unittest.TestCase):
    """Independent review of PR #150: partial failures, scope narrowing, malformed registry rows, per-connection counting."""

    def test_reader_errors_degrade_connection_health_only(self):
        class Broken(ReaderStub):
            def metric_rows(self, statement, params, limit=1000):
                raise psycopg.errors.QueryCanceled('statement timeout')
        items, envelope, state = fc.read_connection_health(types.SimpleNamespace(store=Broken()), NOW, 'production')
        self.assertEqual((state, envelope['freshness'], [i['safeReasonCode'] for i in items]), ('unavailable', 'unknown', ['connection_health_unavailable']))
        out = fc.attention(app_for(Broken(), FounderStoreStub()), PRINCIPAL, {'mode': 'live', 'now': NOW})
        self.assertEqual(out['sources']['connectionHealth']['state'], 'unavailable')
        self.assertEqual(out['summary']['tenants'], {'value': None, 'countState': 'unknown'})

    def test_rows_query_missing_after_coverage_is_not_an_all_clear(self):
        class HalfMissing(ReaderStub):
            def metric_rows(self, statement, params, limit=1000):
                if statement.metric_id.endswith(':rows'):
                    raise psycopg.errors.UndefinedColumn('connectionState')
                return super().metric_rows(statement, params, limit)
        items, _, state = fc.read_connection_health(types.SimpleNamespace(store=HalfMissing(coverage={'latest': fc._iso(NOW - 60), 'total': 3})), NOW, 'production')
        self.assertEqual(state, 'source_not_configured')
        self.assertEqual([i['category'] for i in items], ['stale_telemetry'])

    def test_rows_are_distinct_connections_without_provider_ordering(self):
        reader = ReaderStub(coverage={'latest': fc._iso(NOW - 60), 'total': 1}, rows=[row('w1', 'c1', 'youtube', 'token_expired')])
        fc.read_connection_health(types.SimpleNamespace(store=reader), NOW, 'production')
        sql = reader.statements[1][1]
        self.assertIn('SELECT DISTINCT', sql)
        self.assertNotIn('ORDER BY h.provider', sql)

    def test_recorded_scopes_never_narrow_the_adapter_request(self):
        adapters = {'youtube': types.SimpleNamespace(documented_scopes=('scope.read', 'scope.upload'), SCOPES={})}
        decision = approved('sensitive_scope', ['scope.read'], requestedScopes=['scope.read'])
        entry = [e for e in fc.registry_entries(adapters, {('youtube', 'youtube', 'production', 'sensitive_scope'): decision}) if e['provider'] == 'youtube']
        req = next(r for r in fc.evaluate_registry(entry, NOW)[0]['requirements'] if r['kind'] == 'sensitive_scope')
        self.assertEqual((req['standing'], req['missingScopes']), ('blocked', ['scope.upload']))

    def test_malformed_registry_row_blocks_only_that_row(self):
        adapters = {'youtube': types.SimpleNamespace(documented_scopes=('s',), SCOPES={})}
        decisions = {('youtube', 'youtube', 'production', 'api_audit'): {'status': 'green'}}
        app = fc.evaluate_registry([e for e in fc.registry_entries(adapters, decisions) if e['provider'] == 'youtube'], NOW)[0]
        bad = next(r for r in app['requirements'] if r['kind'] == 'api_audit')
        self.assertEqual((bad['standing'], bad['blockers']), ('blocked', ['invalid_registry_entry']))
        self.assertEqual(app['readiness'], 'blocked')


class SecondReviewFindingTests(unittest.TestCase):
    """Independent acceptance audit of PR #150 (second review)."""

    def youtube(self, decisions):
        adapters = {'youtube': types.SimpleNamespace(documented_scopes=('scope.read', 'scope.upload'), SCOPES={})}
        return fc.evaluate_registry([e for e in fc.registry_entries(adapters, decisions) if e['provider'] == 'youtube'], NOW)[0]

    def test_malformed_decisions_of_any_shape_block_only_their_row(self):
        key = lambda kind: ('youtube', 'youtube', 'production', kind)
        decisions = {key('sensitive_scope'): approved('sensitive_scope', ['scope.read'], approvedScopes=5),
                     key('api_audit'): 'approved',
                     key('quota_entitlement'): approved('quota_entitlement', [], requestedScopes=7),
                     key('brand_verification'): approved('brand_verification', [], requestedScopes='scope.read')}
        app = self.youtube(decisions)
        got = {r['kind']: (r['standing'], r['blockers']) for r in app['requirements']}
        for kind in ('sensitive_scope', 'api_audit', 'quota_entitlement', 'brand_verification'):
            self.assertEqual(got[kind], ('blocked', ['invalid_registry_entry']), kind)
        self.assertEqual(got['domain_ownership'][0], 'check_required')
        original = fc.RECORDED_DECISIONS
        fc.RECORDED_DECISIONS = decisions
        try:
            out = fc.attention(app_for(ReaderStub(coverage={'latest': fc._iso(NOW - 60), 'connections': 0}), FounderStoreStub()), PRINCIPAL, {'mode': 'live', 'now': NOW})
        finally:
            fc.RECORDED_DECISIONS = original
        self.assertEqual(next(a for a in out['registry'] if a['provider'] == 'youtube')['readiness'], 'blocked')

    def test_future_decision_time_and_not_required_scope_gap(self):
        app = self.youtube({('youtube', 'youtube', 'production', 'brand_verification'): approved('brand_verification', [], decided=NOW + 3600),
                            ('youtube', 'youtube', 'production', 'sensitive_scope'): approved('sensitive_scope', ['scope.read'], status='not_required_evidenced')})
        got = {r['kind']: (r['standing'], r['blockers']) for r in app['requirements']}
        self.assertEqual(got['brand_verification'], ('check_required', ['decision_time_in_future']))
        self.assertEqual(got['sensitive_scope'], ('blocked', ['approved_scopes_do_not_cover_request']))

    def test_projection_at_the_stage_cap_is_partial_not_complete(self):
        reader = ReaderStub(coverage={'latest': fc._iso(NOW - 60), 'total': 9 * fc.STAGE_CONNECTION_CAP, 'connections': fc.STAGE_CONNECTION_CAP},
                            rows=[row('w1', 'c1', 'linkedin', 'token_expired')])
        items, envelope, _ = fc.read_connection_health(types.SimpleNamespace(store=reader), NOW, 'production')
        self.assertEqual(envelope['coverage'], 'partial')
        self.assertFalse(fc.green(envelope))
        self.assertEqual(items[0]['affected']['tenants'], {'value': 1, 'countState': 'lower_bound'})
        from rafii_control import founder_metrics_ops
        self.assertEqual(fc.STAGE_CONNECTION_CAP, founder_metrics_ops.MAX_CONNECTIONS)

    def test_missing_adapter_catalogue_is_not_reported_as_no_launch_scope(self):
        evaluated = fc.evaluate_registry(fc.registry_entries(adapters={}), NOW)
        items = fc.registry_items(evaluated, NOW, 'production')
        self.assertEqual([(i['safeReasonCode'], i['launchBlocker']) for i in items], [('launch_provider_not_in_registry', True)])


class RouteTests(unittest.TestCase):
    def setUp(self):
        slices.load()

    def test_route_is_registered_read_only_and_demo_ok(self):
        routes = {(r[0], r[1].pattern): (r[2], r[5]) for r in http.EXTENSION_ROUTES if r[3] == 'founder_connections'}
        self.assertEqual(routes, {('GET', r'/connections/attention'): ('control.read', {'demo_ok': True})})

    def test_live_assembles_sources_and_never_claims_live_verification(self):
        reader = ReaderStub(coverage={'latest': fc._iso(NOW - 600), 'total': 3},
                            rows=[row('w1', 'c1', 'linkedin', 'token_expired'), row('w2', 'c2', 'linkedin', 'reauthorization_required')])
        incidents = [{'id': 'i-1', 'detector': 'publish_failure_rate', 'scope': 'global', 'severity': 'critical', 'state': 'acknowledged',
                      'opened_at': NOW - 3600, 'affected_count': 4, 'version': 3},
                     {'id': 'i-2', 'detector': 'source_silence', 'scope': 'stripe', 'severity': 'warning', 'state': 'open', 'opened_at': NOW - 600,
                      'affected_count': 0, 'version': 1}]
        out = fc.attention(app_for(reader, FounderStoreStub(incidents)), PRINCIPAL, {'mode': 'live', 'now': NOW})
        self.assertEqual((out['mode'], out['_dataState'], out['liveVerified']), ('live', 'live', False))
        self.assertEqual(out['items'][0]['category'], 'publishing')
        self.assertEqual(out['items'][0]['affected']['jobs'], {'value': 4, 'countState': 'estimated'})
        self.assertEqual(out['items'][0]['incidentRef'], 'i-1')
        categories = [i['category'] for i in out['items']]
        self.assertIn('reconnect_required', categories)
        blocker = next(i for i in out['items'] if i['category'] == 'launch_blocker')
        self.assertEqual((blocker['provider'], blocker['priority'], blocker['launchBlocker']), ('youtube', 'P2', True))
        self.assertNotIn('launch_scope', categories, 'the YouTube read-only launch scope is recorded')
        youtube = next(app for app in out['registry'] if app['provider'] == 'youtube')
        self.assertEqual(youtube['readiness'], 'check_required', 'no approval is claimed without a decision receipt')
        self.assertIn('publishing', youtube['launch']['excluded'])
        self.assertTrue(all(req['documentationRef'].startswith('https://developers.google.com/') for req in youtube['requirements'] if req['documentationRef']))
        self.assertEqual(out['summary']['tenants']['countState'], 'lower_bound')
        self.assertEqual(out['sources']['incidents'], {'state': 'connected'})
        self.assertEqual(out['environment'], 'production')
        body = json.dumps(out)
        for forbidden in ('w1', 'w2', 'token":', 'ciphertext', 'secret'):
            self.assertNotIn(forbidden, body)

    def test_incident_store_failure_is_unknown_not_empty(self):
        reader = ReaderStub(coverage={'latest': fc._iso(NOW - 600), 'total': 0})
        out = fc.attention(app_for(reader, FounderStoreStub(fail=True)), PRINCIPAL, {'mode': 'live', 'now': NOW})
        self.assertEqual(out['sources']['incidents'], {'state': 'unavailable'})
        self.assertIn('incidents_unavailable', [i['safeReasonCode'] for i in out['items']])

    def test_demo_is_synthetic_and_never_reads_live(self):
        app = types.SimpleNamespace(queries=None, founder_store=lambda: self.fail('demo must not read the founder store'))
        out = fc.attention(app, PRINCIPAL, {'mode': 'demo', 'now': NOW})
        self.assertEqual((out['mode'], out['_dataState'], out['environment']), ('demo', 'synthetic', 'demo'))
        reconnect = next(i for i in out['items'] if i['provider'] == 'linkedin')
        self.assertEqual((reconnect['affected']['tenants']['value'], reconnect['affected']['connections']['value']), (1, 2))

    def test_launch_scope_turns_registry_gaps_into_launch_blockers(self):
        original = fc.LAUNCH_SCOPE
        fc.LAUNCH_SCOPE = {'linkedin': {'operations': ['identity']}}
        try:
            evaluated = fc.evaluate_registry(fc.registry_entries(), NOW)
            items = fc.registry_items(evaluated, NOW, 'production')
        finally:
            fc.LAUNCH_SCOPE = original
        self.assertEqual([(i['category'], i['provider'], i['launchBlocker']) for i in items], [('launch_blocker', 'linkedin', True)])
        self.assertEqual(items[0]['owner']['lane'], 'provider_app_owner')
        self.assertTrue(items[0]['nextAction']['requiresHuman'])
        self.assertIn('no_decision_recorded', items[0]['nextAction']['blockedBy'])
        self.assertEqual(items[0]['affected']['tenants']['countState'], 'unknown')


class LaunchScopeTests(unittest.TestCase):
    def test_empty_launch_scope_is_a_visible_decision_item(self):
        original = fc.LAUNCH_SCOPE
        fc.LAUNCH_SCOPE = {}
        try:
            items = fc.registry_items(fc.evaluate_registry(fc.registry_entries(), NOW), NOW, 'production')
        finally:
            fc.LAUNCH_SCOPE = original
        self.assertEqual([(i['category'], i['safeReasonCode']) for i in items], [('launch_scope', 'launch_scope_not_recorded')])

    def test_registry_stays_extensible_to_every_adapter(self):
        providers = {app['provider'] for app in fc.registry_entries()}
        self.assertTrue({'youtube', 'instagram', 'threads', 'facebook', 'tiktok', 'linkedin', 'x', 'bluesky', 'google'} <= providers)
        self.assertEqual([app['provider'] for app in fc.registry_entries() if app['launchScope']], ['youtube'])


class EndToEndAuthorizationTests(unittest.TestCase):
    """The route through the real Boundary and ControlApplication: only an active founder operator session with control.read
    reaches the handler; Demo never touches the Live reader."""

    def setUp(self):
        from control.test_boundary import MemoryStore, NOW as BOUNDARY_NOW, USER
        from rafii_control.auth import Boundary, Config, VerifiedIdentity
        from rafii_control.http import ControlApplication
        slices.load()
        self.origin = 'http://localhost:4449'
        self.store = MemoryStore()
        self.reader = ReaderStub(coverage={'latest': fc._iso(BOUNDARY_NOW - 600), 'total': 1}, rows=[row('w-secret-1', 'c1', 'youtube', 'client_binding_missing')])
        self.store.metric_rows = self.reader.metric_rows
        self.user = USER
        self.boundary = Boundary(Config(True, 'local', self.origin), self.store, lambda token: VerifiedIdentity(self.user, 'aal2', 's' * 32, BOUNDARY_NOW),
                                 clock=lambda: BOUNDARY_NOW)
        self.app = ControlApplication(self.boundary, types.SimpleNamespace(store=self.store))
        self.app._founder_store = FounderStoreStub()

    def call(self, query='mode=live', cookie=True, session=None):
        import io
        env = dict(PATH_INFO='/api/control/v2/connections/attention', QUERY_STRING=query, REQUEST_METHOD='GET', CONTENT_LENGTH='0', HTTP_HOST='localhost:4449',
                   HTTP_ORIGIN=self.origin, **{'wsgi.input': io.BytesIO(b'')})
        if cookie:
            token, session = session or self.boundary.exchange('verified-token', self.origin)
            env.update(HTTP_COOKIE='__Host-rafii-control=' + token, HTTP_X_CSRF_TOKEN=session['csrfToken'])
        result = {}
        body = b''.join(self.app(env, lambda status, headers: result.update(status=int(status[:3]))))
        return result['status'], json.loads(body)

    def test_founder_session_reads_the_queue(self):
        status, body = self.call()
        self.assertEqual(status, 200, body)
        reconnect = next(i for i in body['data']['items'] if i['category'] == 'reconnect_required')
        self.assertEqual(reconnect['safeReasonCode'], 'client_binding_missing', 'client_binding_missing is an attention item, never healthy')
        self.assertEqual(body['dataState'], 'live')
        self.assertNotIn('w-secret-1', json.dumps(body))

    def test_anonymous_is_denied(self):
        status, _ = self.call(cookie=False)
        self.assertEqual(status, 401)
        self.assertEqual(self.reader.statements, [])

    def test_operator_without_control_read_is_denied(self):
        self.store.operator_row['capabilities'] = [c for c in self.store.operator_row['capabilities'] if c != 'control.read']
        status, _ = self.call()
        self.assertEqual(status, 403)
        self.assertEqual(self.reader.statements, [])

    def test_operator_suspended_after_sign_in_is_denied_on_the_route(self):
        session = self.boundary.exchange('verified-token', self.origin)
        self.assertEqual(self.call(session=session)[0], 200)
        self.reader.statements.clear()
        self.store.operator_row['status'] = 'suspended'
        status, _ = self.call(session=session)
        self.assertIn(status, (401, 403))
        self.assertEqual(self.reader.statements, [], 'a suspended operator never reaches the reader')

    def test_inactive_or_non_operator_identity_is_denied(self):
        self.store.operator_row['status'] = 'suspended'
        with self.assertRaises(ControlError):
            self.call()
        self.assertEqual(self.reader.statements, [])

    def test_demo_never_reads_live_and_bad_mode_is_rejected(self):
        status, body = self.call('mode=demo')
        self.assertEqual((status, body['dataState'], body['data']['mode'], body['data']['environment']), (200, 'synthetic', 'demo', 'demo'))
        self.assertEqual(self.reader.statements, [], 'Demo must not touch the Live reader')
        status, _ = self.call('mode=staging')
        self.assertEqual(status, 400)


if __name__ == '__main__':
    unittest.main()
