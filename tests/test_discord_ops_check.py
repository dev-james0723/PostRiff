"""H-07 alert rules (scripts/discord_ops_check.py): every rule at and around its thresholds, the healthy baseline,
transitions, the log parser and the command line. Pure: no database, network or credential."""
import copy
import http.server
import importlib.util
import io
import json
import math
import secrets
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('discord_ops_check', ROOT / 'scripts/discord_ops_check.py')
check = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check)
THRESHOLDS = check.load_thresholds()
NOW = 1_800_000_000.0


def healthy():
    """An open, healthy production build: everything observed, nothing near a threshold."""
    guard = {'present': True, 'hold': False, 'blocked': False, 'circuit': False, 'embargoSeconds': 0.0,
             'remaining': None, 'limit': None, 'windowSeconds': None, 'remainingRatio': None, 'resetSeconds': None}
    return {
        'version': 1, 'kind': 'rafii.discord.ops.health', 'source': 'health_route', 'observedAt': NOW - 5,
        'build': {'sourceRevision': 'a' * 40, 'deploymentId': 'dpl_Synthetic0001', 'environment': 'production'},
        'lane': {'version': 1, 'enabled': True, 'ready': True, 'blocker': None, 'maxSeconds': 50.0, 'maxSteps': 600,
                 'shards': 12, 'policyDaysLeft': 20.0, 'staticBlocker': None},
        'config': {'providerMounted': True, 'gate': {'mode': 'open', 'workspaces': 0, 'misconfigured': False},
                   'cap': {'value': 10000, 'unlimited': False, 'misconfigured': False}, 'productionEnvironment': True,
                   'reviewed': True, 'connectionsV2': True, 'authorizationV2': True, 'rateLimitsV1': True,
                   'workerV1': True, 'laneFlag': True, 'executionEnabled': True, 'killSwitch': False,
                   'coordinatorDegraded': False,
                   'policy': {'present': True, 'valid': True, 'daysLeft': 20.0, 'revision': 'rafii-w1-20261101',
                              'appCapacity': 25, 'appWindowSeconds': 1, 'invalidCapacity': 2000,
                              'invalidWindowSeconds': 600, 'slotGuardSeconds': 0.1},
                   'servers': {'status': 'observed', 'counted': 120, 'inFlight': 3, 'used': 123, 'ratio': 0.0123}},
        'queue': {'status': 'observed', 'dueWorkspaces': 2, 'dueWithin5Min': 10, 'pendingWorkspaces': 12,
                  'oldestDueLagSeconds': 20.0},
        'progress': {'status': 'observed', 'lastClaimAgeSeconds': 4.0, 'lastAdmissionAgeSeconds': 1.0,
                     'lastAcceptedCreateAgeSeconds': 6.0, 'lastReadbackAgeSeconds': 2.0, 'sampleSpanSeconds': 3000.0},
        'deliveries': {'status': 'observed', 'windowSeconds': 900, 'windowCovered': True, 'sampled': 4000,
                       'sampleLimit': 20000, 'creates': 200, 'accepted': 198, 'rejectedCustomer': 2, 'rejectedSystem': 0,
                       'rateLimited': 0, 'uncertain': 0, 'blocked': 0, 'inFlight': 1, 'stuckSent': 0, 'stuckSentTotal': 0},
        'coordinator': {'status': 'observed', 'rowsPolicyDaysLeft': 20.0, 'kinds': {},
                        'guards': {'policy': {**guard, 'remaining': 20, 'limit': 25, 'windowSeconds': 1.0,
                                              'remainingRatio': 0.8},
                                   'global': dict(guard), 'credential': dict(guard),
                                   'invalid': {**guard, 'remaining': 1990, 'limit': 2000, 'windowSeconds': 600.0,
                                               'remainingRatio': 0.995}},
                        'traffic': {'responses429': 0, 'responses429Global': 0, 'invalid10m': 4,
                                    'invalidWindowCovered': True, 'responses5m': 300, 'serverErrors5m': 0,
                                    'admissions60s': 400, 'uncertainReads': 0, 'unauthorized': 0}},
        'platform': {'status': 'observed', 'ageSeconds': 30.0, 'snapshotStatus': 'ok', 'publicationUncertain': 0,
                     'queueDelayed': 0, 'publicationFailed': 0, 'publicationHeld': 0},
        'security': {'instance': {'scope': 'instance', 'windowSeconds': 900, 'denied': {'discord': 0, 'connections': 0,
                                                                                         'workspace': 1, 'other': 0},
                                  'deniedTotal': 1, 'actors10m': 1, 'topActorDenials10m': 1},
                     'responses4xx': {'status': 'observed', 'windowSeconds': 900, 'workspace': 3, 'connections': 2,
                                      'discord': 4, 'other': 1}},
        'errors': [], 'elapsedMs': 30.0}


def alerts(snapshot, phase='open', thresholds=None, now=NOW):
    return check.evaluate(snapshot, thresholds or THRESHOLDS, now=now, phase=phase)


def found(snapshot, rule, **kw):
    """The severity of `rule`, or None when it does not fire."""
    hits = [a for a in alerts(snapshot, **kw) if a['id'] == rule]
    return hits[0]['severity'] if hits else None


def with_(path, value, base=None):
    snapshot = copy.deepcopy(base or healthy())
    target = snapshot
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return snapshot


class Baseline(unittest.TestCase):
    def test_a_healthy_build_raises_nothing_in_any_phase(self):
        for phase in check.PHASES:
            snapshot = healthy()
            if phase == 'canary':
                snapshot['config']['gate'] = {'mode': 'list', 'workspaces': 3, 'misconfigured': False}
            with self.subTest(phase=phase):
                self.assertEqual(alerts(snapshot, phase=phase), [])

    def test_the_thresholds_file_carries_every_value_the_rules_read(self):
        self.assertNotIn('phase', THRESHOLDS, 'the phase is given on every run (review M3)')
        broken = healthy()
        broken['queue']['oldestDueLagSeconds'] = 10_000
        for section in ('backlog', 'delivery', 'rate_limit', 'silent_halt', 'cross_tenant', 'config'):
            with self.subTest(section=section):
                self.assertIsInstance(THRESHOLDS[section], dict)
        self.assertTrue(alerts(broken))

    def test_pages_sort_before_warnings(self):
        snapshot = with_(('queue', 'oldestDueLagSeconds'), 1000.0)
        snapshot['coordinator']['traffic']['unauthorized'] = 1
        result = alerts(snapshot)
        self.assertEqual([a['severity'] for a in result], ['page', 'warn'])
        self.assertEqual({a['id'] for a in result}, {'DELIVERY_UNAUTHORIZED', 'BACKLOG_LAG'})

    def test_every_alert_names_a_known_class_and_severity_and_carries_counts_only(self):
        snapshot = with_(('queue', 'oldestDueLagSeconds'), 4000.0)
        snapshot['progress'].update(lastClaimAgeSeconds=None, lastAdmissionAgeSeconds=None)
        snapshot['deliveries'].update(uncertain=5, stuckSent=2)
        snapshot['coordinator']['guards']['invalid']['remainingRatio'] = 0.1
        snapshot['config']['servers']['ratio'] = 0.95
        for alert in alerts(snapshot):
            self.assertIn(alert['class'], check.CLASSES)
            self.assertIn(alert['severity'], check.SEVERITIES)
            for value in alert['evidence'].values():
                self.assertIsInstance(value, (int, float, bool, str, list, dict))


class Backlog(unittest.TestCase):
    def test_boundaries(self):
        # Review M2: the standard burst drains in about 23 minutes and one workspace can need 40; page above 45.
        for lag, expected in ((900.0, None), (900.1, 'warn'), (2400.0, 'warn'), (2700.0, 'warn'), (2700.1, 'page')):
            with self.subTest(lag=lag):
                self.assertEqual(found(with_(('queue', 'oldestDueLagSeconds'), lag), 'BACKLOG_LAG'), expected)

    def test_an_unavailable_queue_is_not_a_backlog_alert(self):
        self.assertIsNone(found(with_(('queue',), {'status': 'unavailable'}), 'BACKLOG_LAG'))


class Delivery(unittest.TestCase):
    def deliveries(self, **values):
        snapshot = healthy()
        snapshot['deliveries'].update({'accepted': 0, 'rejectedCustomer': 0, **values})
        return snapshot

    def test_uncertain_creates(self):
        for count, expected in ((0, None), (1, 'warn'), (2, 'warn'), (3, 'page')):
            with self.subTest(count=count):
                self.assertEqual(found(self.deliveries(accepted=200, uncertain=count), 'DELIVERY_UNCERTAIN'), expected)

    def test_system_failure_share_and_count(self):
        for accepted, system, expected in ((99, 1, None), (98, 2, 'warn'), (91, 9, 'warn'), (90, 10, 'page'),
                                           (17, 2, None), (16, 3, 'warn')):
            with self.subTest(attempts=accepted + system, system=system):
                self.assertEqual(found(self.deliveries(accepted=accepted, rejectedSystem=system),
                                       'DELIVERY_SYSTEM_FAILURES'), expected)

    def test_uncertain_and_stuck_creates_count_as_system_failures(self):
        alert = [a for a in alerts(self.deliveries(accepted=10, uncertain=1, stuckSent=2)) if a['id'] == 'DELIVERY_SYSTEM_FAILURES']
        self.assertEqual(alert[0]['evidence']['systemFailures'], 3)

    def test_customer_caused_refusals_warn_only_when_most_attempts_fail(self):
        for accepted, customer, expected in ((21, 19, None), (20, 20, 'warn'), (0, 19, None)):
            with self.subTest(accepted=accepted, customer=customer):
                snapshot = self.deliveries(accepted=accepted, rejectedCustomer=customer)
                self.assertEqual(found(snapshot, 'DELIVERY_CUSTOMER_FAILURES'), expected)
                self.assertIsNone(found(snapshot, 'DELIVERY_SYSTEM_FAILURES'), 'customer-caused is not ours')

    def test_stuck_sent_creates(self):
        self.assertIsNone(found(self.deliveries(accepted=100, stuckSent=0), 'DELIVERY_STUCK_SENT'))
        self.assertEqual(found(self.deliveries(accepted=100, stuckSent=1), 'DELIVERY_STUCK_SENT'), 'warn')

    def test_a_401_pages(self):
        self.assertIsNone(found(healthy(), 'DELIVERY_UNAUTHORIZED'))
        self.assertEqual(found(with_(('coordinator', 'traffic', 'unauthorized'), 1), 'DELIVERY_UNAUTHORIZED'), 'page')

    def test_discord_server_error_share(self):
        for responses, errors, expected in ((100, 2, None), (100, 3, 'warn'), (19, 19, None), (20, 1, 'warn')):
            with self.subTest(responses=responses, errors=errors):
                snapshot = healthy()
                snapshot['coordinator']['traffic'].update(responses5m=responses, serverErrors5m=errors)
                self.assertEqual(found(snapshot, 'DELIVERY_DISCORD_5XX'), expected)

    def test_a_partial_sample_is_said_to_be_a_lower_bound(self):
        snapshot = self.deliveries(accepted=10, uncertain=3, windowCovered=False)
        alert = [a for a in alerts(snapshot) if a['id'] == 'DELIVERY_UNCERTAIN'][0]
        self.assertIn('lower bounds', alert['evidence']['note'])


class RateLimit(unittest.TestCase):
    # The coordinator holds each admission's slot for its window plus a guard of at most a tenth of it
    # (SharedPostgresBudget._span), so under continuous demand 25 a second over 1 s with a 0.1 s guard admits at most
    # 25 x 60 / 1.1 = 1363.6 a minute. "Budget nearly spent" is 95% of what can be admitted, not of the nominal 1,500.
    ACHIEVABLE = 25 * 60 / 1.1

    def spent(self, admitted, **policy):
        snapshot = with_(('coordinator', 'traffic', 'admissions60s'), admitted)
        for key, value in policy.items():
            if value is None:
                snapshot['config']['policy'].pop(key, None)
            else:
                snapshot['config']['policy'][key] = value
        return found(snapshot, 'RATE_APP_BUDGET_SPENT')

    def test_application_budget_spent_against_the_achievable_ceiling(self):
        warn_at = math.ceil(0.95 * self.ACHIEVABLE)
        for admitted, expected in ((warn_at - 1, None), (warn_at, 'warn'), (int(self.ACHIEVABLE), 'warn')):
            with self.subTest(admitted=admitted):
                self.assertEqual(self.spent(admitted, slotGuardSeconds=0.1), expected)

    def test_continuous_demand_under_the_limiters_guard_is_reported(self):
        # Review of D3 on the limiter head: at a 0.1 s guard the ledger shows 0.909 of the nominal ceiling at most, so a
        # rule against the nominal ceiling and 0.95 could never fire again.
        self.assertEqual(self.spent(int(1500 / 1.1), slotGuardSeconds=0.1), 'warn')

    def test_without_a_guard_the_nominal_ceiling_is_the_achievable_one(self):
        for admitted, expected in ((1424, None), (1425, 'warn')):
            with self.subTest(admitted=admitted):
                self.assertEqual(self.spent(admitted, slotGuardSeconds=0.0), expected)

    def test_a_guard_above_a_tenth_of_the_window_counts_as_a_tenth(self):
        self.assertEqual(self.spent(int(self.ACHIEVABLE), slotGuardSeconds=5.0), 'warn')
        self.assertEqual(self.spent(math.ceil(0.95 * self.ACHIEVABLE) - 1, slotGuardSeconds=5.0), None)

    def test_an_unknown_guard_is_the_largest_the_coordinator_allows(self):
        # A snapshot without the build's guard (the SQL twin, an older build) is judged against the smallest achievable
        # ceiling, so no guard the coordinator can use makes the alert unreachable.
        self.assertEqual(self.spent(math.ceil(0.95 * self.ACHIEVABLE), slotGuardSeconds=None), 'warn')
        self.assertEqual(self.spent(math.ceil(0.95 * self.ACHIEVABLE) - 1, slotGuardSeconds=None), None)

    def test_the_evaluators_ceiling_is_the_coordinators_span(self):
        from types import SimpleNamespace
        from postriff_phase2.discord.rate_limits import SharedPostgresBudget
        span = getattr(SharedPostgresBudget, '_span', None)
        guard = getattr(SharedPostgresBudget, 'SLOT_GUARD_SECONDS', None)
        if span is None or guard is None:
            self.skipTest('this build has no slot guard (the limiter line adds it)')
        for window in (1.0, 0.5, 10.0):
            with self.subTest(window=window):
                expected = 25 * 60.0 / span(SimpleNamespace(SLOT_GUARD_SECONDS=guard), window)
                self.assertAlmostEqual(check.achievable_per_minute(25, window, guard), expected)

    def test_the_sql_twin_reads_the_budget_from_the_policy_row(self):
        snapshot = with_(('coordinator', 'traffic', 'admissions60s'), 1500)
        del snapshot['config']
        self.assertEqual(found(snapshot, 'RATE_APP_BUDGET_SPENT'), 'warn')
        snapshot['coordinator']['traffic']['admissions60s'] = math.ceil(0.95 * self.ACHIEVABLE) - 1
        self.assertIsNone(found(snapshot, 'RATE_APP_BUDGET_SPENT'))

    def test_invalid_requests_in_ten_minutes(self):
        for count, expected in ((1000, None), (1001, 'page')):
            with self.subTest(count=count):
                self.assertEqual(found(with_(('coordinator', 'traffic', 'invalid10m'), count), 'RATE_INVALID_REQUESTS'),
                                 expected)

    def test_429_answers(self):
        for total, globals_, expected in ((9, 0, None), (10, 0, 'warn'), (1, 1, 'warn'), (3, 2, 'warn'), (3, 3, 'page')):
            with self.subTest(total=total, globals_=globals_):
                snapshot = healthy()
                snapshot['coordinator']['traffic'].update(responses429=total, responses429Global=globals_)
                self.assertEqual(found(snapshot, 'RATE_429'), expected)

    def test_a_held_bot_credential_pages(self):
        self.assertEqual(found(with_(('coordinator', 'guards', 'credential', 'hold'), True), 'RATE_CREDENTIAL_HOLD'), 'page')

    def test_application_wide_embargoes(self):
        for seconds, expected in ((10.0, 'warn'), (300.0, 'warn'), (300.1, 'page')):
            with self.subTest(seconds=seconds):
                snapshot = healthy()
                snapshot['coordinator']['guards']['global'].update(blocked=True, embargoSeconds=seconds)
                self.assertEqual(found(snapshot, 'RATE_EMBARGO'), expected)
        long = with_(('coordinator', 'kinds'), {'policy': {'holds': 0, 'blocks': 1, 'circuits': 0,
                                                           'persistentCircuits': 0, 'openOver5Min': 1}})
        self.assertEqual(found(long, 'RATE_EMBARGO'), 'page')
        route_only = with_(('coordinator', 'kinds'), {'route': {'holds': 0, 'blocks': 2, 'circuits': 0,
                                                                'persistentCircuits': 0, 'openOver5Min': 2}})
        self.assertIsNone(found(route_only, 'RATE_EMBARGO'), 'a route embargo is not application-wide')

    def test_invalid_request_budget_left(self):
        for ratio, expected in ((0.5, None), (0.4999, 'warn'), (0.25, 'warn'), (0.2499, 'page'), (None, None)):
            with self.subTest(ratio=ratio):
                self.assertEqual(found(with_(('coordinator', 'guards', 'invalid', 'remainingRatio'), ratio),
                                       'RATE_INVALID_BUDGET'), expected)

    def test_transient_route_circuits(self):
        for circuits, persistent, expected in ((7, 3, None), (8, 3, 'warn'), (40, 40, None)):
            with self.subTest(circuits=circuits, persistent=persistent):
                snapshot = with_(('coordinator', 'kinds'), {'route': {'holds': 0, 'blocks': 0, 'circuits': circuits,
                                                                      'persistentCircuits': persistent, 'openOver5Min': 0}})
                self.assertEqual(found(snapshot, 'RATE_ROUTE_CIRCUITS'), expected)

    def test_rate_policy_expiry(self):
        for days, expected in ((7.0, None), (6.99, 'warn'), (1.0, 'warn'), (0.99, 'page')):
            with self.subTest(days=days):
                self.assertEqual(found(with_(('config', 'policy', 'daysLeft'), days), 'RATE_POLICY'), expected)
        self.assertEqual(found(with_(('config', 'policy', 'valid'), False), 'RATE_POLICY'), 'page')
        self.assertEqual(found(with_(('config', 'policy'), {'present': False}), 'RATE_POLICY'), 'page')
        off = with_(('config', 'policy'), {'present': False})
        off['config']['rateLimitsV1'] = False
        self.assertIsNone(found(off, 'RATE_POLICY'), 'no coordinator in use: CONFIG_FLAGS says so instead')


class SilentHalt(unittest.TestCase):
    def test_the_payload_not_answering_is_an_alarm(self):
        for snapshot in (None, {'unavailable': True, 'reason': 'http_503'}, {'unavailable': True, 'reason': 'unreachable'}):
            with self.subTest(snapshot=snapshot):
                result = alerts(snapshot)
                self.assertEqual([(a['id'], a['severity']) for a in result], [('SILENT_HALT_HEALTH_UNANSWERED', 'page')])

    def test_a_stale_snapshot_is_an_alarm(self):
        self.assertIsNone(found(healthy(), 'SILENT_HALT_HEALTH_UNANSWERED', now=NOW - 5 + 180))
        self.assertEqual(found(healthy(), 'SILENT_HALT_HEALTH_UNANSWERED', now=NOW - 5 + 180.5), 'page')

    def test_no_database_and_no_projection(self):
        snapshot = with_(('observedAt',), None)
        snapshot.update(queue={'status': 'unavailable'}, coordinator={'status': 'unavailable'})
        self.assertEqual(found(snapshot, 'SILENT_HALT_DATABASE'), 'page')
        self.assertEqual(found(with_(('queue',), {'status': 'unavailable', 'error': 'UndefinedTable'}),
                               'SILENT_HALT_PROJECTION'), 'page')

    def test_due_work_with_no_claim_and_no_admission(self):
        for lag, claim, admission, expected in ((121, 181, 181, 'page'), (120, 181, 181, None), (121, 180, 181, None),
                                                (121, 181, 180, None), (121, None, None, 'page'), (5000, 1, None, None)):
            with self.subTest(lag=lag, claim=claim, admission=admission):
                snapshot = with_(('queue', 'oldestDueLagSeconds'), float(lag))
                snapshot['progress'].update(lastClaimAgeSeconds=claim, lastAdmissionAgeSeconds=admission)
                self.assertEqual(found(snapshot, 'SILENT_HALT_NO_PROGRESS'), expected)

    def test_under_an_operator_hold_no_progress_is_expected(self):
        snapshot = with_(('queue', 'oldestDueLagSeconds'), 600.0)
        snapshot['progress'].update(lastClaimAgeSeconds=None, lastAdmissionAgeSeconds=900.0)
        snapshot['coordinator']['guards']['policy']['hold'] = True
        self.assertEqual(found(snapshot, 'SILENT_HALT_NO_PROGRESS'), 'warn')
        self.assertEqual(found(snapshot, 'SILENT_HALT_OPERATOR_HOLD'), 'warn')

    def test_lane_flag_on_and_lane_not_ready(self):
        for blocker, expected in (('coordinator_unavailable', 'page'), ('configuration', 'warn'),
                                  ('coordinator_degraded', 'warn')):
            with self.subTest(blocker=blocker):
                snapshot = healthy()
                snapshot['lane'].update(ready=False, blocker=blocker)
                self.assertEqual(found(snapshot, 'SILENT_HALT_LANE_NOT_READY'), expected)
        off = healthy()
        off['lane'].update(enabled=False, ready=False, blocker='disabled')
        self.assertIsNone(found(off, 'SILENT_HALT_LANE_NOT_READY'))

    def test_no_shard_invocations_in_the_logs(self):
        for window, lines, enabled, expected in ((180, 0, True, 'page'), (179, 0, True, None), (180, 1, True, None),
                                                 (600, 0, False, None)):
            with self.subTest(window=window, lines=lines, enabled=enabled):
                snapshot = healthy()
                snapshot['lane']['enabled'] = enabled
                snapshot['fleet'] = {'windowSeconds': window, 'laneLines': lines, 'laneStops': {'idle': lines}}
                self.assertEqual(found(snapshot, 'SILENT_HALT_NO_SHARDS'), expected)

    def test_abnormal_shard_stops(self):
        snapshot = healthy()
        snapshot['fleet'] = {'windowSeconds': 600, 'laneLines': 12, 'laneStops': {'idle': 10, 'schema': 2}}
        self.assertEqual(found(snapshot, 'SILENT_HALT_LANE_STOPS'), 'warn')
        snapshot['fleet']['laneStops'] = {'idle': 10, 'operator_hold': 2}
        self.assertIsNone(found(snapshot, 'SILENT_HALT_LANE_STOPS'))


class CrossTenant(unittest.TestCase):
    def test_one_actor_denied_many_times(self):
        for top, expected in ((9, None), (10, 'warn'), (29, 'warn'), (30, 'page')):
            with self.subTest(top=top):
                self.assertEqual(found(with_(('security', 'instance', 'topActorDenials10m'), top), 'CROSS_TENANT_PROBING'),
                                 expected)

    def test_fleet_logs_count_with_the_instance(self):
        snapshot = healthy()
        snapshot['fleet'] = check.parse_logs(['{"event": "security.cross_tenant_denied", "routeFamily": "workspace", '
                                              '"status": 403, "actorKey": "0123456789", "suppressed": 29}'], 600)
        alert = [a for a in alerts(snapshot) if a['id'] == 'CROSS_TENANT_PROBING'][0]
        self.assertEqual((alert['severity'], alert['evidence']['scope']), ('page', 'fleet_logs'))

    def test_any_denial_on_a_discord_route(self):
        self.assertIsNone(found(healthy(), 'CROSS_TENANT_DISCORD'))
        self.assertEqual(found(with_(('security', 'instance', 'denied', 'discord'), 1), 'CROSS_TENANT_DISCORD'), 'warn')

    def test_client_errors_on_discord_routes(self):
        for count, expected in ((199, None), (200, 'warn')):
            with self.subTest(count=count):
                self.assertEqual(found(with_(('security', 'responses4xx', 'discord'), count), 'CROSS_TENANT_DISCORD_4XX'),
                                 expected)
        self.assertIsNone(found(with_(('security', 'responses4xx'), {'status': 'not_installed', 'discord': 999}),
                                'CROSS_TENANT_DISCORD_4XX'))

    def test_a_failing_isolation_probe_pages(self):
        self.assertIsNone(found(with_(('security', 'probe'), {'failed': 0}), 'CROSS_TENANT_PROBE_FAILED'))
        self.assertEqual(found(with_(('security', 'probe'), {'failed': 1}), 'CROSS_TENANT_PROBE_FAILED'), 'page')


class ConfigDrift(unittest.TestCase):
    def test_gate_after_the_opening(self):
        for mode, expected in (('open', None), ('closed', 'page'), ('list', 'page')):
            with self.subTest(mode=mode):
                snapshot = with_(('config', 'gate', 'mode'), mode)
                self.assertEqual(found(snapshot, 'CONFIG_GATE', phase='open'), expected)
                self.assertIsNone(found(snapshot, 'CONFIG_GATE', phase='pre_open'))

    def test_gate_during_the_canary(self):
        for gate, expected in (({'mode': 'list', 'workspaces': 5}, None), ({'mode': 'list', 'workspaces': 6}, 'page'),
                               ({'mode': 'open', 'workspaces': 0}, 'page'), ({'mode': 'closed', 'workspaces': 0}, None)):
            with self.subTest(gate=gate):
                self.assertEqual(found(with_(('config', 'gate'), {**gate, 'misconfigured': False}), 'CONFIG_GATE',
                                       phase='canary'), expected)

    def test_a_misconfigured_gate_or_cap_pages_in_every_phase(self):
        for phase in check.PHASES:
            with self.subTest(phase=phase):
                self.assertEqual(found(with_(('config', 'gate', 'misconfigured'), True), 'CONFIG_MISCONFIGURED',
                                       phase=phase), 'page')
                self.assertEqual(found(with_(('config', 'cap', 'misconfigured'), True), 'CONFIG_MISCONFIGURED',
                                       phase=phase), 'page')

    def test_cap_below_the_expected_value(self):
        for value, unlimited, expected in ((10000, False, None), (9999, False, 'page'), (90, False, 'page'),
                                           (None, False, 'page'), (None, True, None)):
            with self.subTest(value=value, unlimited=unlimited):
                snapshot = with_(('config', 'cap'), {'value': value, 'unlimited': unlimited, 'misconfigured': False})
                snapshot['config']['servers']['ratio'] = None
                self.assertEqual(found(snapshot, 'CONFIG_CAP', phase='open'), expected)
        self.assertIsNone(found(with_(('config', 'cap', 'value'), 90), 'CONFIG_CAP', phase='canary'))

    def test_cap_used(self):
        for ratio, expected in ((0.79, None), (0.8, 'warn'), (0.89, 'warn'), (0.9, 'page')):
            with self.subTest(ratio=ratio):
                self.assertEqual(found(with_(('config', 'servers', 'ratio'), ratio), 'CONFIG_CAP_USED',
                                       phase='pre_open'), expected)

    def test_reviewed_flag_and_switches(self):
        self.assertEqual(found(with_(('config', 'reviewed'), False), 'CONFIG_REVIEWED', phase='canary'), 'page')
        self.assertIsNone(found(with_(('config', 'reviewed'), False), 'CONFIG_REVIEWED', phase='pre_open'))
        alert = [a for a in alerts(with_(('config', 'rateLimitsV1'), False), phase='open') if a['id'] == 'CONFIG_FLAGS']
        self.assertEqual((alert[0]['severity'], alert[0]['evidence']['missing']), ('page', ['rateLimitsV1']))

    def test_lane_flag_expectation(self):
        thresholds = copy.deepcopy(THRESHOLDS)
        self.assertIsNone(found(with_(('config', 'laneFlag'), False), 'CONFIG_LANE_FLAG', thresholds=thresholds))
        thresholds['config']['expected_lane_flag'] = True
        self.assertEqual(found(with_(('config', 'laneFlag'), False), 'CONFIG_LANE_FLAG', thresholds=thresholds), 'warn')
        self.assertIsNone(found(healthy(), 'CONFIG_LANE_FLAG', thresholds=thresholds))

    def test_kill_switch(self):
        snapshot = with_(('config', 'killSwitch'), True)
        snapshot['config']['executionEnabled'] = False
        self.assertEqual(found(snapshot, 'CONFIG_KILL_SWITCH'), 'warn')

    def test_the_serving_build_against_the_record(self):
        thresholds = copy.deepcopy(THRESHOLDS)
        thresholds['config']['expected_source_revision'] = 'b' * 40
        self.assertEqual(found(healthy(), 'CONFIG_BUILD', thresholds=thresholds), 'warn')
        thresholds['config']['expected_source_revision'] = 'a' * 40
        self.assertIsNone(found(healthy(), 'CONFIG_BUILD', thresholds=thresholds))
        thresholds['config']['expected_deployment_id'] = 'dpl_Other00001'
        self.assertEqual(found(with_(('build', 'sourceRevision'), None), 'CONFIG_BUILD', thresholds=thresholds), 'warn')

    def test_the_sql_twin_without_a_process_view_raises_no_config_alerts(self):
        snapshot = healthy()
        for name in ('config', 'lane', 'build'):
            del snapshot[name]
        snapshot['source'] = 'sql'
        snapshot['servers'] = {'status': 'observed', 'counted': 120, 'inFlight': 3, 'used': 123}
        self.assertEqual(alerts(snapshot), [])


class TransitionsAndLogs(unittest.TestCase):
    def test_transitions(self):
        before = [{'id': 'A', 'severity': 'warn'}, {'id': 'B', 'severity': 'page'}, {'id': 'C', 'severity': 'warn'}]
        after = [{'id': 'A', 'severity': 'page'}, {'id': 'B', 'severity': 'page'}, {'id': 'D', 'severity': 'info'}]
        self.assertEqual(check.transitions(before, after), {'opened': ['D'], 'continuing': ['A', 'B'], 'cleared': ['C'],
                                                            'escalated': ['A']})

    def test_parse_logs_counts_denials_and_shard_lines_and_returns_no_key(self):
        lines = ['2026-10-23T05:00:01Z {"event": "security.cross_tenant_denied", "routeFamily": "discord", "status": 403, '
                 '"actorKey": "aaaaaaaaaa", "suppressed": 4}',
                 '{"event": "security.cross_tenant_denied", "routeFamily": "invented", "status": 403, "actorKey": "bbbbbbbbbb", "suppressed": 0}',
                 '{"event": "discord.lane.completed", "stoppedBy": "idle", "counters": {"posted": 3, "verified": 2, "held": 1}}',
                 '{"event": "discord.lane.completed", "stoppedBy": "schema", "counters": {"posted": "x"}}',
                 '{"event": "discord.lane.lagging", "oldestEligibleLagSeconds": 400}', 'not json {', '{"broken": ']
        fleet = check.parse_logs(lines, 600)
        self.assertEqual(fleet['denials']['denied'], {'discord': 5, 'other': 1})
        self.assertEqual((fleet['denials']['topActorDenials10m'], fleet['denials']['actors10m']), (5, 2))
        self.assertEqual((fleet['laneLines'], fleet['laneStops'], fleet['lagging']), (2, {'idle': 1, 'schema': 1}, 1))
        self.assertEqual(fleet['laneCounters']['posted'], 3)
        self.assertNotIn('aaaaaaaaaa', json.dumps(fleet))


class CommandLine(unittest.TestCase):
    def run_cli(self, snapshot, *extra):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'snapshot.json'
            path.write_text(json.dumps(snapshot))
            with patch('sys.stdout', io.StringIO()) as printed:
                code = check.main(['evaluate', str(path), '--now', str(NOW), *extra])
        return code, json.loads(printed.getvalue())

    def test_exit_codes_follow_the_worst_severity(self):
        self.assertEqual(self.run_cli(healthy(), '--phase', 'open')[0], 0)
        self.assertEqual(self.run_cli(with_(('queue', 'oldestDueLagSeconds'), 1000.0), '--phase', 'open')[0], 1)
        code, report = self.run_cli({'unavailable': True, 'reason': 'http_503'}, '--phase', 'open')
        self.assertEqual((code, report['worst']), (2, 'page'))

    def test_previous_alerts_give_transitions(self):
        with tempfile.TemporaryDirectory() as folder:
            previous = Path(folder) / 'previous.json'
            previous.write_text(json.dumps({'alerts': [{'id': 'BACKLOG_LAG', 'severity': 'warn'}]}))
            code, report = self.run_cli(healthy(), '--phase', 'open', '--previous', str(previous))
        self.assertEqual((code, report['transitions']['cleared']), (0, ['BACKLOG_LAG']))

    def test_a_failed_fetch_is_an_unavailable_snapshot_and_the_bearer_is_never_printed(self):
        bearer = secrets.token_hex(16)
        with patch.dict('os.environ', {'DISCORD_OPS_BEARER': bearer}), patch('sys.stdout', io.StringIO()) as printed:
            self.assertEqual(check.main(['fetch', 'http://127.0.0.1:9/api/ops/discord/health', '--timeout', '1']), 0)
        self.assertEqual(json.loads(printed.getvalue()), {'unavailable': True, 'reason': 'unreachable'})
        self.assertNotIn(bearer, printed.getvalue())
        with patch.dict('os.environ', {}, clear=True), patch('sys.stdout', io.StringIO()) as printed:
            check.main(['fetch', 'http://127.0.0.1:9/'])
        self.assertEqual(json.loads(printed.getvalue())['reason'], 'no_bearer')


class ReviewFindings(unittest.TestCase):
    """The independent review of 8e76afdd (findings M1, M3, M4, M6, M8, L3): each test failed on the reviewed
    evaluator and passes on this one (H07-EVIDENCE.md lists the before and after runs)."""

    def test_M1_a_malformed_snapshot_is_an_alarm_not_silence(self):
        for mutate, detail in ((lambda s: s.update(kind='something.else'), 'kind'),
                               (lambda s: s.update(version=2), 'version'),
                               (lambda s: s.update(source='unknown'), 'source'),
                               (lambda s: s.pop('deliveries'), 'missing:deliveries'),
                               (lambda s: s.pop('coordinator'), 'missing:coordinator'),
                               (lambda s: s.update(errors=None), 'missing:errors')):
            snapshot = healthy()
            mutate(snapshot)
            with self.subTest(detail=detail):
                hits = [a for a in alerts(snapshot) if a['id'] == 'SILENT_HALT_HEALTH_UNANSWERED']
                self.assertEqual([(a['severity'], a['evidence'].get('detail')) for a in hits], [('page', detail)])
        self.assertEqual(alerts({}), [a for a in alerts({}) if a['id'] == 'SILENT_HALT_HEALTH_UNANSWERED'])
        self.assertTrue(alerts({}))

    def test_M1_each_failed_section_warns_then_pages_when_it_persists(self):
        snapshot = healthy()
        snapshot['errors'] = [{'section': 'ledger', 'error': 'QueryCanceled'}, {'section': 'servers', 'error': 'UndefinedTable'}]
        first = [a for a in alerts(snapshot) if a['id'] == 'SILENT_HALT_SECTION']
        self.assertEqual(sorted((a['scope'], a['severity']) for a in first), [('ledger', 'warn'), ('servers', 'warn')])
        second = [a for a in check.evaluate(snapshot, THRESHOLDS, now=NOW, phase='open', previous={'alerts': first})
                  if a['id'] == 'SILENT_HALT_SECTION']
        self.assertEqual(sorted((a['scope'], a['severity']) for a in second), [('ledger', 'page'), ('servers', 'page')])
        snapshot['errors'] = [{'section': 'ledger', 'error': 'QueryCanceled'}]
        third = check.evaluate(snapshot, THRESHOLDS, now=NOW, phase='open', previous={'alerts': second})
        self.assertEqual(check.transitions(second, third)['cleared'], ['SILENT_HALT_SECTION/servers'])

    def test_M1_no_progress_still_pages_when_the_ledger_section_failed(self):
        """Measured by the review (exp_missing): ledger unavailable, work 1,500 s overdue, last claim 4,000 s ago."""
        snapshot = with_(('queue', 'oldestDueLagSeconds'), 1500.0)
        snapshot['deliveries'] = {'status': 'unavailable', 'error': 'UndefinedTable'}
        snapshot['progress'] = {'status': 'partial', 'lastClaimAgeSeconds': 4000.0, 'lastAdmissionAgeSeconds': None,
                                'lastAcceptedCreateAgeSeconds': None, 'lastReadbackAgeSeconds': None, 'sampleSpanSeconds': None}
        snapshot['errors'] = [{'section': 'ledger', 'error': 'UndefinedTable'}]
        result = {(a['id'], a['severity']) for a in alerts(snapshot)}
        self.assertIn(('SILENT_HALT_NO_PROGRESS', 'page'), result)
        self.assertIn(('SILENT_HALT_SECTION', 'warn'), result)
        snapshot['progress']['lastClaimAgeSeconds'] = 10.0          # claims continue: not a halt, but the ledger is blind
        self.assertNotIn('SILENT_HALT_NO_PROGRESS', {a['id'] for a in alerts(snapshot)})

    def test_M3_the_phase_is_required_on_the_command_line_and_the_function_defaults_to_open(self):
        closed = with_(('config', 'gate'), {'mode': 'closed', 'workspaces': 0, 'misconfigured': False})
        self.assertIn('CONFIG_GATE', {a['id'] for a in check.evaluate(closed, THRESHOLDS, now=NOW)})
        with tempfile.TemporaryDirectory() as folder, patch('sys.stderr', io.StringIO()):
            path = Path(folder) / 'snapshot.json'
            path.write_text(json.dumps(closed))
            with self.assertRaises(SystemExit):
                check.main(['evaluate', str(path), '--now', str(NOW)])

    def test_M4_an_unresolved_uncertain_admission_keeps_the_warning_after_its_window(self):
        snapshot = healthy()
        snapshot['unresolved'] = {'status': 'observed', 'uncertainPublishes': 2, 'stuckSentPublishes': 1, 'livePermits': 0,
                                  'oldestUnresolvedAgeSeconds': 5400.0}
        result = {a['id']: a for a in alerts(snapshot)}
        self.assertEqual(result['DELIVERY_UNCERTAIN']['severity'], 'warn')
        self.assertEqual(result['DELIVERY_UNCERTAIN']['evidence']['unresolved'], 2)
        self.assertEqual(result['DELIVERY_STUCK_SENT']['evidence']['unresolved'], 1)
        snapshot['deliveries'] = {'status': 'unavailable'}             # the 15-minute ledger failed: the counts still stand
        self.assertEqual({a['id'] for a in alerts(snapshot)} & {'DELIVERY_UNCERTAIN', 'DELIVERY_STUCK_SENT'},
                         {'DELIVERY_UNCERTAIN', 'DELIVERY_STUCK_SENT'})

    def test_M6_held_and_failed_growth_against_the_previous_report(self):
        before = healthy()
        before['platform'].update(publicationHeld=4, publicationFailed=10)
        memory = check.memory(before)
        after = healthy()
        after['platform'].update(publicationHeld=7, publicationFailed=12)
        result = {a['id']: a for a in check.evaluate(after, THRESHOLDS, now=NOW, previous={'alerts': [], 'memory': memory})}
        self.assertEqual(result['DELIVERY_HELD_GROWTH']['evidence']['growth'], 3)
        self.assertNotIn('DELIVERY_FAILED_GROWTH', result)               # +2 is under the threshold of 3
        after['platform']['publicationFailed'] = 13
        self.assertIn('DELIVERY_FAILED_GROWTH', {a['id'] for a in check.evaluate(after, THRESHOLDS, now=NOW, previous={'memory': memory})})
        self.assertNotIn('DELIVERY_HELD_GROWTH', {a['id'] for a in check.evaluate(after, THRESHOLDS, now=NOW)})

    def test_M6_work_due_and_nothing_reaching_discord(self):
        snapshot = with_(('queue', 'oldestDueLagSeconds'), 1200.0)
        snapshot['progress'].update(lastClaimAgeSeconds=5.0, lastAdmissionAgeSeconds=2.0,     # claims and admissions go on
                                    lastAcceptedCreateAgeSeconds=1900.0, lastReadbackAgeSeconds=650.0)
        self.assertEqual(found(snapshot, 'SILENT_HALT_NO_CREATE'), 'warn')
        snapshot['progress']['lastReadbackAgeSeconds'] = 1850.0
        self.assertEqual(found(snapshot, 'SILENT_HALT_NO_CREATE'), 'page')
        snapshot['coordinator']['guards']['policy']['hold'] = True
        self.assertEqual(found(snapshot, 'SILENT_HALT_NO_CREATE'), 'warn')
        self.assertIsNone(found(with_(('queue', 'oldestDueLagSeconds'), 60.0), 'SILENT_HALT_NO_CREATE'))

    def test_M5_the_probing_message_no_longer_says_hold_first(self):
        snapshot = healthy()
        snapshot['security']['instance']['topActorDenials10m'] = 40
        message = [a['message'] for a in alerts(snapshot) if a['id'] == 'CROSS_TENANT_PROBING'][0]
        self.assertNotIn('hold first', message)
        self.assertIn('hold only if the probe fails or exposure is confirmed', message)

    def test_M8_fetch_refuses_plain_http_to_another_machine(self):
        bearer = secrets.token_hex(16)
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('no request may be made')):
            for url in ('http://rafii.example.invalid/api/ops/discord/health', 'ftp://rafii.example.invalid/', 'file:///etc/hosts'):
                with self.subTest(url=url):
                    self.assertEqual(check.fetch(url, bearer), {'unavailable': True, 'reason': 'insecure_url'})

    def test_M8_fetch_never_follows_a_redirect_and_never_sends_the_bearer_elsewhere(self):
        bearer = secrets.token_hex(16)
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get('Authorization')))
                if self.path.startswith('/moved'):
                    self.send_response(302)
                    self.send_header('Location', 'http://127.0.0.1:%d/elsewhere' % self.server.server_address[1])
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{}')

            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            got = check.fetch('http://127.0.0.1:%d/moved' % server.server_address[1], bearer, timeout=5)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(got, {'unavailable': True, 'reason': 'http_302'})
        self.assertEqual([path for path, _auth in seen], ['/moved'])

    def test_M8_fetch_has_one_overall_deadline(self):
        bearer = secrets.token_hex(16)

        class Slow(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                try:
                    for _ in range(40):              # a byte every 0.1 s: each read is quick, the whole is not
                        self.wfile.write(b' ')
                        self.wfile.flush()
                        time.sleep(0.1)
                except OSError:
                    pass

            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Slow)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            started = time.monotonic()
            got = check.fetch('http://127.0.0.1:%d/' % server.server_address[1], bearer, timeout=1.0)
            took = time.monotonic() - started
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(got, {'unavailable': True, 'reason': 'deadline'})
        self.assertLess(took, 2.5)

    def test_L3_an_internal_error_exits_3_and_a_log_drain_envelope_is_read(self):
        with tempfile.TemporaryDirectory() as folder, patch('sys.stdout', io.StringIO()) as printed, \
                patch.object(check, 'evaluate', side_effect=RuntimeError('bug')):
            path = Path(folder) / 'snapshot.json'
            path.write_text(json.dumps(healthy()))
            self.assertEqual(check.main(['evaluate', str(path), '--phase', 'open', '--now', str(NOW)]), 3)
        self.assertEqual(json.loads(printed.getvalue()), {'error': 'RuntimeError', 'worst': None})
        line = json.dumps({'message': json.dumps({'event': 'discord.lane.completed', 'stoppedBy': 'idle', 'counters': {}})})
        self.assertEqual(check.parse_logs([line], 600)['laneLines'], 1)


def lagging(creates=None, readbacks=None, projected=None, late=(), owns=True):
    return json.dumps({'event': 'discord.lane.lagging', 'oldestEligibleLagSeconds': max(creates or 0, readbacks or 0),
                       'oldestEligibleCreateLagSeconds': creates, 'oldestEligibleReadbackLagSeconds': readbacks,
                       'projectedLagSeconds': projected, 'thresholdSeconds': 300, 'readbackThresholdSeconds': 3600,
                       'lateKinds': list(late), 'report': 'sample', 'projection': 'read', 'laneOwnsDiscord': owns,
                       'laneBlocker': None if owns else 'disabled'})


def with_fleet(lines, snapshot=None, window=600):
    snapshot = snapshot or healthy()
    snapshot['fleet'] = check.parse_logs(lines, window)
    return snapshot


class LaterBranches(unittest.TestCase):
    """What the W-02 head (090c7ce6) and the limiter head (e6aa7db8) added that the rules read: the lane's new counters,
    stop reason and events, the lag split of discord.lane.lagging, failed reads as observed 503, and retention."""

    def test_the_lane_counters_include_quarantined_and_positions_kept(self):
        line = json.dumps({'event': 'discord.lane.completed', 'stoppedBy': 'idle',
                           'counters': {'claimed': 4, 'quarantined': 1, 'positionsKept': 2}})
        fleet = check.parse_logs([line, line], 600)
        self.assertEqual((fleet['laneCounters']['quarantined'], fleet['laneCounters']['positionsKept']), (2, 4))

    def test_a_quarantined_workspace_is_a_warning_with_its_error_class_only(self):
        line = json.dumps({'event': 'discord.lane.quarantined', 'error': 'JSONDecodeError', 'quarantineSeconds': 300})
        fleet = check.parse_logs([line, line], 600)
        self.assertEqual(fleet['quarantine'], {'events': 2, 'errors': {'JSONDecodeError': 2}})
        alert = [a for a in alerts(with_fleet([line])) if a['id'] == 'SILENT_HALT_QUARANTINE']
        self.assertEqual([(a['severity'], a['evidence']['events']) for a in alert], [('warn', 1)])
        self.assertNotIn('SILENT_HALT_QUARANTINE', {a['id'] for a in alerts(with_fleet([]))})

    def test_late_creates_use_the_lanes_split_at_300_seconds_and_page_at_the_backlog_page(self):
        cases = [(lagging(creates=290, readbacks=10), None), (lagging(creates=301, readbacks=10, late=['creates']), 'warn'),
                 (lagging(creates=2701, readbacks=10, late=['creates']), 'page')]
        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(found(with_fleet([line]), 'BACKLOG_LAG'), expected)

    def test_read_backs_deferred_by_a_burst_warn_only_past_an_hour(self):
        deferred = with_fleet([lagging(creates=100, readbacks=3000)], with_(('queue', 'oldestDueLagSeconds'), 3000.0))
        self.assertIsNone(found(deferred, 'BACKLOG_LAG'), 'the projection cannot tell them apart; the split shows a deferral')
        late = with_fleet([lagging(creates=100, readbacks=3601, late=['readbacks'])], with_(('queue', 'oldestDueLagSeconds'), 3601.0))
        self.assertEqual(found(late, 'BACKLOG_LAG'), 'warn')
        self.assertEqual(found(with_(('queue', 'oldestDueLagSeconds'), 3000.0), 'BACKLOG_LAG'), 'page', 'without the split: as before')

    def test_the_newest_lagging_line_is_the_one_read(self):
        snapshot = with_fleet([lagging(creates=2800, readbacks=10, late=['creates']), lagging(creates=20, readbacks=10)])
        self.assertIsNone(found(snapshot, 'BACKLOG_LAG'))

    def test_a_known_pause_never_pages_and_says_so(self):
        paused = with_(('queue', 'oldestDueLagSeconds'), 3000.0)
        paused['config']['executionEnabled'] = False
        paused['progress'].update(lastClaimAgeSeconds=None, lastAdmissionAgeSeconds=None, lastAcceptedCreateAgeSeconds=None,
                                  lastReadbackAgeSeconds=None)
        result = {a['id']: a for a in alerts(paused)}
        for rule in ('BACKLOG_LAG', 'SILENT_HALT_NO_PROGRESS', 'SILENT_HALT_NO_CREATE'):
            with self.subTest(rule=rule):
                self.assertEqual(result[rule]['severity'], 'warn')
                self.assertIn('Discord is paused', result[rule]['message'])
                self.assertTrue(result[rule]['evidence']['discordPaused'])
        by_lanes = with_fleet([json.dumps({'event': 'discord.lane.completed', 'stoppedBy': 'discord_paused', 'counters': {}})],
                              with_(('queue', 'oldestDueLagSeconds'), 3000.0))
        self.assertEqual(found(by_lanes, 'BACKLOG_LAG'), 'warn')
        self.assertNotIn('SILENT_HALT_LANE_STOPS', {a['id'] for a in alerts(by_lanes)}, 'a paused stop is not abnormal')

    def test_the_create_and_read_back_thresholds_are_the_lanes_own(self):
        from postriff_phase2.discord import lane
        self.assertEqual(THRESHOLDS['backlog']['create_warn_seconds'], lane.LAG_WARNING_SECONDS)
        if not hasattr(lane, 'READBACK_LAG_WARNING_SECONDS'):
            self.skipTest('this build has no read-back lag threshold (the W-02 line adds it)')
        self.assertEqual(THRESHOLDS['backlog']['readback_warn_seconds'], lane.READBACK_LAG_WARNING_SECONDS)

    def test_server_errors_include_failed_reads_and_say_so(self):
        snapshot = healthy()
        snapshot['coordinator']['traffic'].update(responses5m=100, serverErrors5m=5, uncertainReads=0)
        alert = [a for a in alerts(snapshot) if a['id'] == 'DELIVERY_DISCORD_5XX'][0]
        self.assertIn('failed before an answer', alert['message'])
        self.assertNotIn('Usually a Discord outage', alert['message'])

    def test_the_hold_message_follows_what_the_serving_build_does_with_a_read_under_a_hold(self):
        """With the limiter's read wait (rate_limits.HOLD_WAIT_SECONDS, B4) a read-back under a hold waits and keeps its
        checks; without it five refusals park the post for a day. The page must not tell the older story on a newer build."""
        held = with_(('coordinator', 'guards', 'policy', 'hold'), True)
        held['config']['holdReadWaitSeconds'] = None
        older = [a for a in alerts(held) if a['id'] == 'SILENT_HALT_OPERATOR_HOLD'][0]
        self.assertIn('parked for 24 hours', older['message'])
        self.assertNotIn('read-backs wait', older['message'])
        twin = with_(('coordinator', 'guards', 'policy', 'hold'), True)
        del twin['config']                      # the SQL twin has no process view: it cannot know the build
        unknown = [a for a in alerts(twin) if a['id'] == 'SILENT_HALT_OPERATOR_HOLD'][0]
        self.assertIn('read-backs wait if the serving build has', unknown['message'])
        self.assertIn('parked for 24 hours', unknown['message'])
        held['config']['holdReadWaitSeconds'] = 300.0
        newer = [a for a in alerts(held) if a['id'] == 'SILENT_HALT_OPERATOR_HOLD'][0]
        self.assertNotIn('parked', newer['message'])
        self.assertIn('read-backs wait', newer['message'])
        self.assertEqual(newer['evidence'].get('holdReadWaitSeconds'), 300.0)

    def retention(self, **values):
        snapshot = healthy()
        snapshot['coordinator']['retention'] = {
            'status': 'observed', 'retentionSeconds': {'reads': 3600, 'publications': 86400},
            'oldestSettledReadAgeSeconds': 5000.0, 'oldestSettledPublicationAgeSeconds': 90000.0, 'liveRowsEstimate': 5400,
            'deadRowsEstimate': 12, 'rowsDeletedTotal': 880, 'lastVacuumAgeSeconds': 120.0, **values}
        return snapshot

    def test_retention_behind_when_settled_rows_outlive_three_retentions(self):
        self.assertIsNone(found(self.retention(), 'RATE_RETENTION_BEHIND'))
        self.assertEqual(found(self.retention(oldestSettledReadAgeSeconds=3 * 3600 + 1), 'RATE_RETENTION_BEHIND'), 'warn')
        self.assertEqual(found(self.retention(oldestSettledPublicationAgeSeconds=3 * 86400 + 1), 'RATE_RETENTION_BEHIND'), 'warn')

    def test_retention_purged_and_remaining_counts_are_read_when_present(self):
        snapshot = self.retention(remaining={'reads': 60000, 'publications': 0, 'capped': False})
        self.assertEqual(found(snapshot, 'RATE_RETENTION_BEHIND'), 'warn')
        purged = self.retention(purged={'status': 'denied', 'reads': 0, 'publications': 0, 'more': False, 'ageSeconds': 30.0})
        self.assertEqual(found(purged, 'RATE_RETENTION_BEHIND'), 'warn')
        line = json.dumps({'event': 'discord.lane.retention', 'status': 'ok', 'reads': 2000, 'publications': 5, 'rounds': 1,
                           'more': False})
        failed = json.dumps({'event': 'discord.lane.retention', 'status': 'timeout', 'reads': 0, 'publications': 0, 'rounds': 0,
                             'more': False, 'error': 'QueryCanceled'})
        fleet = check.parse_logs([line, line, failed], 600)
        self.assertEqual(fleet['retention'], {'lines': 3, 'purgedReads': 4000, 'purgedPublications': 10,
                                              'failures': {'timeout': 1}, 'more': 0})
        self.assertEqual(found(with_fleet([failed], self.retention()), 'RATE_RETENTION_BEHIND'), 'warn')
        self.assertIsNone(found(with_fleet([line], self.retention()), 'RATE_RETENTION_BEHIND'))


if __name__ == '__main__':
    unittest.main()
