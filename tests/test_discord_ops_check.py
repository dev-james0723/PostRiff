"""H-07 alert rules (scripts/discord_ops_check.py): every rule at and around its thresholds, the healthy baseline,
transitions, the log parser and the command line. Pure: no database, network or credential."""
import copy
import importlib.util
import io
import json
import tempfile
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
                              'invalidWindowSeconds': 600},
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
        self.assertIn(THRESHOLDS['phase'], check.PHASES)
        broken = healthy()
        broken['queue']['oldestDueLagSeconds'] = 10_000
        for section in ('backlog', 'delivery', 'rate_limit', 'silent_halt', 'cross_tenant', 'config'):
            with self.subTest(section=section):
                self.assertIsInstance(THRESHOLDS[section], dict)
        self.assertTrue(alerts(broken))

    def test_pages_sort_before_warnings(self):
        snapshot = with_(('queue', 'oldestDueLagSeconds'), 400.0)
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
        for lag, expected in ((300.0, None), (300.1, 'warn'), (900.0, 'warn'), (900.1, 'page')):
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
    def test_application_budget_spent_for_a_minute(self):
        for admitted, expected in ((1424, None), (1425, 'warn')):
            with self.subTest(admitted=admitted):
                self.assertEqual(found(with_(('coordinator', 'traffic', 'admissions60s'), admitted),
                                       'RATE_APP_BUDGET_SPENT'), expected)

    def test_the_sql_twin_reads_the_budget_from_the_policy_row(self):
        snapshot = with_(('coordinator', 'traffic', 'admissions60s'), 1500)
        del snapshot['config']
        self.assertEqual(found(snapshot, 'RATE_APP_BUDGET_SPENT'), 'warn')

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
        self.assertEqual(self.run_cli(with_(('queue', 'oldestDueLagSeconds'), 400.0), '--phase', 'open')[0], 1)
        code, report = self.run_cli({'unavailable': True, 'reason': 'http_503'})
        self.assertEqual((code, report['worst']), (2, 'page'))

    def test_previous_alerts_give_transitions(self):
        with tempfile.TemporaryDirectory() as folder:
            previous = Path(folder) / 'previous.json'
            previous.write_text(json.dumps({'alerts': [{'id': 'BACKLOG_LAG', 'severity': 'warn'}]}))
            code, report = self.run_cli(healthy(), '--phase', 'open', '--previous', str(previous))
        self.assertEqual((code, report['transitions']['cleared']), (0, ['BACKLOG_LAG']))

    def test_a_failed_fetch_is_an_unavailable_snapshot_and_the_bearer_is_never_printed(self):
        with patch.dict('os.environ', {'DISCORD_OPS_BEARER': 'b' * 32}), patch('sys.stdout', io.StringIO()) as printed:
            self.assertEqual(check.main(['fetch', 'http://127.0.0.1:9/api/ops/discord/health', '--timeout', '1']), 0)
        self.assertEqual(json.loads(printed.getvalue()), {'unavailable': True, 'reason': 'unreachable'})
        self.assertNotIn('b' * 32, printed.getvalue())
        with patch.dict('os.environ', {}, clear=True), patch('sys.stdout', io.StringIO()) as printed:
            check.main(['fetch', 'http://127.0.0.1:9/'])
        self.assertEqual(json.loads(printed.getvalue())['reason'], 'no_bearer')


if __name__ == '__main__':
    unittest.main()
