"""Founder P0 detectors (versioned thresholds), episode dedupe, acknowledgement and founder notification events.

Pure detector inputs and the in-memory founder store; the shared notification outbox is exercised through a fake
`notifications` service so the emitted events can be inspected (workspace_id=None, user_id=operator). No network.
"""
import os
import types
import unittest
import uuid
from contextlib import contextmanager

os.environ.setdefault('RAFII_PHONE_PROVIDER', 'fake')

from postriff_phase2.notifications import catalog
from rafii_control import founder_cron, founder_incidents
from rafii_control.auth import ControlError
from rafii_control.founder_incidents import (THRESHOLDS, acknowledge, cost_anomaly, detect, evaluate, observed_detectors, payment_failure_spike,
                                             publish_failure_rate, source_silence)

try:
    from test_founder_contact import OPERATOR, T0, MemoryFounderStore, enabled_policy
except ImportError:  # python -m unittest control.test_founder_incidents
    from control.test_founder_contact import OPERATOR, T0, MemoryFounderStore, enabled_policy


def observations(**overrides):
    base = {'sources_probed': True,
            'sources': [{'source_id': s, 'state': 'measured', 'checked_at': T0 - 30, 'watermark': T0 - 30, 'reason_code': 'qualified'}
                        for s in ('cron', 'database', 'control_database')],
            'publish': {'available': True, 'failed': 0, 'uncertain': 0, 'verified': 20},
            'cost': {'available': True, 'today_usd_micro': 1_000_000, 'daily_usd_micro': [1_000_000] * 7, 'budget_stop_reached': False},
            'payments': {'available': True, 'past_due_new': 0}}
    base.update(overrides)
    return base


class DetectorTests(unittest.TestCase):
    def test_publish_failure_rate_thresholds_and_sample_floor(self):
        self.assertIsNone(publish_failure_rate(observations(publish={'available': False}), T0))
        self.assertIsNone(publish_failure_rate(observations(publish={'available': True, 'failed': 3, 'uncertain': 0, 'verified': 1}), T0), 'below min_samples')
        self.assertIsNone(publish_failure_rate(observations(publish={'available': True, 'failed': 1, 'uncertain': 0, 'verified': 9}), T0))
        warning = publish_failure_rate(observations(publish={'available': True, 'failed': 2, 'uncertain': 1, 'verified': 7}), T0)
        self.assertEqual((warning['severity'], warning['affected_count'], warning['evidence']['rate'], warning['evidence']['thresholdVersion']), ('warning', 3, 0.3, 1))
        critical = publish_failure_rate(observations(publish={'available': True, 'failed': 5, 'uncertain': 1, 'verified': 4}), T0)
        self.assertEqual((critical['severity'], critical['scope']), ('critical', 'global'))

    def test_source_silence_per_source_with_critical_after_long_silence(self):
        self.assertEqual(source_silence(observations(), T0), [])
        stale = observations()
        stale['sources'][1]['checked_at'] = T0 - 200
        findings = source_silence(stale, T0)
        self.assertEqual([(f['scope'], f['severity'], f['evidence']['silentSeconds']) for f in findings], [('database', 'warning', 200)])
        down = observations()
        down['sources'][2].update(state='unavailable', reason_code='provider_unavailable', checked_at=T0 - 1000)
        findings = source_silence(down, T0)
        self.assertEqual([(f['scope'], f['severity'], f['evidence']['reasonCode']) for f in findings], [('control_database', 'critical', 'provider_unavailable')])
        missing = observations(sources=[])
        self.assertEqual(sorted(f['scope'] for f in source_silence(missing, T0)), ['control_database', 'cron', 'database'])
        self.assertEqual(source_silence(observations(sources=[], sources_probed=False), T0), [], 'never probed is not evidence of silence')

    def test_cost_anomaly_uses_seven_day_median_floor_and_budget_stop(self):
        self.assertIsNone(cost_anomaly(observations(cost={'available': False}), T0))
        self.assertIsNone(cost_anomaly(observations(cost={'available': True, 'today_usd_micro': 4_000_000, 'daily_usd_micro': [100] * 7, 'budget_stop_reached': False}), T0),
                          'below the absolute floor')
        self.assertIsNone(cost_anomaly(observations(cost={'available': True, 'today_usd_micro': 6_000_000, 'daily_usd_micro': [3_000_000] * 7, 'budget_stop_reached': False}), T0))
        warning = cost_anomaly(observations(cost={'available': True, 'today_usd_micro': 6_500_000, 'daily_usd_micro': [1_000_000, 2_000_000, 2_000_000, 2_000_000, 2_000_000, 9_000_000, 2_000_000], 'budget_stop_reached': False}), T0)
        self.assertEqual((warning['severity'], warning['evidence']['medianUsdMicro'], warning['evidence']['days']), ('warning', 2_000_000, 7))
        critical = cost_anomaly(observations(cost={'available': True, 'today_usd_micro': 13_000_000, 'daily_usd_micro': [2_000_000] * 7, 'budget_stop_reached': False}), T0)
        self.assertEqual(critical['severity'], 'critical')
        stop = cost_anomaly(observations(cost={'available': True, 'today_usd_micro': 10, 'daily_usd_micro': [], 'budget_stop_reached': True}), T0)
        self.assertEqual((stop['severity'], stop['evidence']['budgetStop']), ('critical', True))

    def test_payment_failure_spike_counts(self):
        self.assertIsNone(payment_failure_spike(observations(payments={'available': False}), T0))
        self.assertIsNone(payment_failure_spike(observations(payments={'available': True, 'past_due_new': 2}), T0))
        self.assertEqual(payment_failure_spike(observations(payments={'available': True, 'past_due_new': 3}), T0)['severity'], 'warning')
        spike = payment_failure_spike(observations(payments={'available': True, 'past_due_new': 10}), T0)
        self.assertEqual((spike['severity'], spike['affected_count'], spike['evidence']['windowHours']), ('critical', 10, 24))

    def test_detect_is_deterministic_and_ordered(self):
        quiet = detect(observations(), T0)
        self.assertEqual(quiet, [])
        noisy = observations(publish={'available': True, 'failed': 5, 'uncertain': 1, 'verified': 4}, payments={'available': True, 'past_due_new': 4})
        noisy['sources'][0]['checked_at'] = T0 - 400
        first, second = detect(noisy, T0), detect(noisy, T0)
        self.assertEqual(first, second)
        self.assertEqual([f['detector'] for f in first], ['publish_failure_rate', 'payment_failure_spike', 'source_silence'])
        self.assertTrue(all(f['evidence']['thresholdVersion'] == THRESHOLDS[f['detector']]['version'] for f in first))


class EpisodeTests(unittest.TestCase):
    def setUp(self):
        self.fstore = MemoryFounderStore()
        self.notified = []

    def notify(self, event_type, incident):
        self.notified.append((event_type, incident['id'], incident['version']))

    def finding(self, severity='warning', rate=0.3, affected=3):
        return {'detector': 'publish_failure_rate', 'scope': 'global', 'severity': severity, 'affected_count': affected,
                'evidence': {'rate': rate, 'thresholdVersion': 1}}

    def test_same_episode_updates_escalates_and_resolves_once(self):
        opened = evaluate(self.fstore, [self.finding()], T0, notify=self.notify)
        self.assertEqual(len(opened['opened']), 1)
        incident_id = opened['opened'][0]
        self.assertEqual(evaluate(self.fstore, [self.finding()], T0 + 60, notify=self.notify), {'opened': [], 'updated': [], 'escalated': [], 'refreshed': [], 'resolved': [], 'unobserved': []})
        self.assertEqual(len(self.fstore.open_incidents()), 1, 'identical findings do not reopen or duplicate the episode')
        updated = evaluate(self.fstore, [self.finding(rate=0.35, affected=4)], T0 + 120, notify=self.notify)
        self.assertEqual(updated['updated'], [incident_id])
        escalated = evaluate(self.fstore, [self.finding('critical', 0.6, 6)], T0 + 180, notify=self.notify)
        self.assertEqual(escalated['escalated'], [incident_id])
        self.assertEqual(self.fstore.incident(incident_id)['severity'], 'critical')
        calmer = evaluate(self.fstore, [self.finding('warning', 0.3, 3)], T0 + 240, notify=self.notify)
        self.assertEqual((calmer['updated'], self.fstore.incident(incident_id)['severity']), ([incident_id], 'critical'), 'severity never lowers inside an episode')
        resolved = evaluate(self.fstore, [], T0 + 300, notify=self.notify)
        self.assertEqual(resolved['resolved'], [incident_id])
        self.assertEqual(self.fstore.incident(incident_id)['state'], 'resolved')
        reopened = evaluate(self.fstore, [self.finding()], T0 + 360, notify=self.notify)
        self.assertEqual(len(reopened['opened']), 1)
        self.assertNotEqual(reopened['opened'][0], incident_id, 'a recurrence after recovery is a new episode')
        kinds = [e['kind'] for e in self.fstore.incident_events(incident_id)]
        self.assertEqual(kinds, ['opened', 'updated', 'escalated', 'updated', 'resolved'])
        self.assertEqual([n[0] for n in self.notified], ['founder.incident_opened', 'founder.incident_recovered', 'founder.incident_opened'])

    def test_unobserved_detectors_are_not_recovery(self):
        """A tick whose inputs were unavailable (consumer DB outage, notifications off) leaves open episodes open and never
        announces a recovery; only a detector that observed its inputs may resolve its episode."""
        cost_finding = {'detector': 'cost_anomaly', 'scope': 'global', 'severity': 'warning', 'affected_count': 1, 'evidence': {'todayUsdMicro': 9_000_000, 'thresholdVersion': 1}}
        publish, cost = evaluate(self.fstore, [self.finding('critical', 0.6, 6), cost_finding], T0, notify=self.notify)['opened']
        blind = {'sources': [], 'sources_probed': False, 'publish': {'available': False}, 'cost': {'available': False}, 'payments': {'available': False}}
        self.assertEqual(observed_detectors(blind), set())
        self.assertEqual(observed_detectors({}), set())
        self.assertEqual(observed_detectors(observations()), {'publish_failure_rate', 'cost_anomaly', 'payment_failure_spike', 'source_silence'})
        result = evaluate(self.fstore, detect(blind, T0 + 60), T0 + 60, notify=self.notify, observed=observed_detectors(blind))
        self.assertEqual((result['resolved'], sorted(result['unobserved'])), ([], sorted([publish, cost])))
        self.assertEqual({row['state'] for row in self.fstore.open_incidents()}, {'open'})
        self.assertEqual([n[0] for n in self.notified], ['founder.incident_opened', 'founder.incident_opened'], 'no recovery was announced')
        # Publishing becomes observable again (and is healthy): only its episode resolves; cost stays open.
        partial = {**blind, 'publish': {'available': True, 'failed': 0, 'uncertain': 0, 'verified': 20}}
        result = evaluate(self.fstore, detect(partial, T0 + 120), T0 + 120, notify=self.notify, observed=observed_detectors(partial))
        self.assertEqual((result['resolved'], result['unobserved']), ([publish], [cost]))
        self.assertEqual(self.notified[-1][0], 'founder.incident_recovered')
        self.assertEqual(founder_incidents.evaluate(self.fstore, [], T0 + 180)['resolved'], [cost], 'observed=None (unit callers) keeps the old behaviour')

    def test_evidence_drift_keeps_the_version_and_the_timeline_quiet(self):
        """The version an acknowledgement binds to moves only on a severity/state transition; drifting evidence between
        60-second ticks refreshes the row silently, so the version the page showed is still acknowledgeable."""
        def silence(seconds):
            return {'detector': 'source_silence', 'scope': 'database', 'severity': 'warning', 'affected_count': 1,
                    'evidence': {'silentSeconds': seconds, 'state': 'unavailable', 'reasonCode': 'provider_unavailable', 'thresholdVersion': 1}}
        incident_id = evaluate(self.fstore, [silence(200)], T0, notify=self.notify)['opened'][0]
        shown = self.fstore.incident(incident_id)['version']
        for tick, seconds in ((1, 260), (2, 320), (3, 380)):
            result = evaluate(self.fstore, [silence(seconds)], T0 + 60 * tick, notify=self.notify)
            self.assertEqual((result['refreshed'], result['updated']), ([incident_id], []))
        row = self.fstore.incident(incident_id)
        self.assertEqual((row['version'], row['evidence']['silentSeconds']), (shown, 380), 'evidence refreshed, version untouched')
        self.assertEqual([e['kind'] for e in self.fstore.incident_events(incident_id)], ['opened'], 'no per-tick timeline noise')
        acked = acknowledge(self.fstore, incident_id, shown, OPERATOR, now=T0 + 240)
        self.assertEqual((acked['incident']['state'], acked['incident']['version']), ('acknowledged', shown + 1))
        # A real transition still bumps: escalation to critical after the ack moves the version once more.
        escalated = evaluate(self.fstore, [{**silence(1000), 'severity': 'critical'}], T0 + 300, notify=self.notify)
        self.assertEqual(escalated['escalated'], [incident_id])
        self.assertEqual(self.fstore.incident(incident_id)['version'], shown + 2)
        self.assertEqual([e['kind'] for e in self.fstore.incident_events(incident_id)], ['opened', 'acknowledged', 'escalated'])

    def test_notifier_failures_never_break_evaluation(self):
        def broken(event_type, incident):
            raise RuntimeError('outbox down')
        result = evaluate(self.fstore, [self.finding()], T0, notify=broken)
        self.assertEqual(len(result['opened']), 1)

    def test_acknowledge_requires_exact_version_and_stops_escalation(self):
        incident_id = evaluate(self.fstore, [self.finding('critical', 0.6, 6)], T0)['opened'][0]
        self.assertEqual([i['id'] for i in founder_incidents.escalations_due(self.fstore)], [incident_id])
        with self.assertRaises(ControlError) as stale:
            acknowledge(self.fstore, incident_id, 7, OPERATOR, now=T0 + 1)
        self.assertEqual(stale.exception.code, 'STALE_PREVIEW')
        with self.assertRaises(ControlError):
            acknowledge(self.fstore, incident_id, 1, OPERATOR, now=T0 + 1, channel='email')
        with self.assertRaises(ControlError):
            acknowledge(self.fstore, incident_id, '1', OPERATOR, now=T0 + 1)
        with self.assertRaises(ControlError) as missing:
            acknowledge(self.fstore, str(uuid.uuid4()), 1, OPERATOR, now=T0 + 1)
        self.assertEqual(missing.exception.status, 404)
        acked = acknowledge(self.fstore, incident_id, 1, OPERATOR, now=T0 + 2, channel='phone')
        self.assertEqual((acked['incident']['state'], acked['incident']['version'], acked['incident']['acknowledgedAt']), ('acknowledged', 2, T0 + 2))
        self.assertEqual(founder_incidents.escalations_due(self.fstore), [])
        evaluate(self.fstore, [self.finding('critical', 0.7, 7)], T0 + 3)
        self.assertEqual(self.fstore.incident(incident_id)['state'], 'acknowledged', 'new evidence updates but does not reopen an acknowledged episode')
        listing = founder_incidents.list_incidents(self.fstore, {'operator': {'user_id': OPERATOR}})['incidents']
        self.assertEqual([i['state'] for i in listing], ['acknowledged'])
        detail = founder_incidents.read_incident(self.fstore, {'operator': {'user_id': OPERATOR}}, incident_id)['incident']
        self.assertEqual(detail['timeline'][1]['kind'], 'acknowledged')
        self.assertEqual(detail['href'], '/founder/operations?incident=' + incident_id)


class FakeCursor:
    def __init__(self, emitted):
        self.emitted = emitted

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        return (None,)

    def fetchall(self):
        return []


class FakeDB:
    def __init__(self, emitted):
        self.emitted, self.commits = emitted, 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        return self

    def cursor(self):
        return FakeCursor(self.emitted)

    def commit(self):
        self.commits += 1


class FakeNotifications:
    def __init__(self, enabled=True):
        self.on, self.emitted = enabled, []

    def enabled(self):
        return self.on

    def emit(self, cur, **event):
        self.emitted.append(event)
        return {'eventId': str(uuid.uuid4()), 'created': True, 'deliveries': []}


class NotificationTests(unittest.TestCase):
    def test_register_adds_founder_events_without_overriding_existing_entries(self):
        before = dict(catalog.EVENTS)
        founder_incidents.register_notification_events()
        for name in ('founder.incident_opened', 'founder.incident_recovered', 'founder.briefing_ready', 'founder.source_unavailable'):
            spec = catalog.spec(name)
            self.assertEqual((spec['sms'], spec['audience'], spec['category']), ('off', 'actor', 'founder'))
            self.assertRegex(name, r'^[a-z_]+\.[a-z_]+$')
        self.assertEqual(catalog.spec('founder.incident_opened')['severity'], 'critical')
        self.assertFalse(catalog.transactional('founder.incident_opened'))
        for name, spec in before.items():
            self.assertIs(catalog.EVENTS[name], spec, 'existing catalogue entries are untouched')
        founder_incidents.register_notification_events()
        self.assertEqual(set(catalog.EVENTS), set(before), 'the shipped catalogue (hashed by the locked notification-planning policy) never changes')
        self.assertTrue(set(founder_incidents.NOTIFICATION_EVENTS) <= set(catalog.EXTENSION_EVENTS), 'registration is idempotent')
        self.assertNotIn('founder.incident_opened', catalog.public()['events'], 'customers never see founder events')

    def test_cron_notifier_emits_person_level_events_per_operator(self):
        notifications = FakeNotifications()
        db = FakeDB(notifications.emitted)
        service = types.SimpleNamespace(connection_factory=lambda: db, notifications=notifications)
        notify = founder_cron._notifier(service, [OPERATOR], T0)
        incident = {'id': str(uuid.uuid4()), 'detector': 'cost_anomaly', 'scope': 'global', 'severity': 'critical', 'version': 1}
        notify('founder.incident_opened', incident)
        report = {'id': str(uuid.uuid4()), 'kind': 'daily', 'version': 3}
        notify('founder.briefing_ready', report)
        self.assertEqual(db.commits, 2)
        opened, ready = notifications.emitted
        self.assertEqual((opened['workspace_id'], opened['user_id'], opened['event_type']), (None, OPERATOR, 'founder.incident_opened'))
        self.assertEqual(opened['dedupe_key'], f"founder.incident_opened:{incident['id']}:1")
        self.assertEqual(set(opened['payload']), {'title', 'href'})
        self.assertEqual((opened['channel_filter'], ready['channel_filter']), (['in_app'], ['in_app']), 'without a policy nothing leaves the in-app centre')
        self.assertEqual(ready['entity_type'], 'founder_report')
        self.assertEqual(ready['dedupe_key'], 'founder.briefing_ready:' + report['id'])
        self.assertIsNone(founder_cron._notifier(types.SimpleNamespace(connection_factory=lambda: db, notifications=FakeNotifications(False)), [OPERATOR], T0))
        self.assertIsNone(founder_cron._notifier(types.SimpleNamespace(connection_factory=lambda: db, notifications=None), [OPERATOR], T0))

    def test_email_and_push_follow_the_founder_contact_policy(self):
        """CONTRACTS §0: real email/push stay OFF. The default policy (live_delivery_enabled=false) plans in-app rows only;
        only an enabled policy that lists a channel lets the outbox plan it, and 'call' never becomes an outbox channel."""
        fstore = MemoryFounderStore()
        self.assertEqual(founder_cron.notification_channels(fstore, OPERATOR), ['in_app'])
        notifications = FakeNotifications()
        service = types.SimpleNamespace(connection_factory=lambda: FakeDB(notifications.emitted), notifications=notifications)
        incident = {'id': str(uuid.uuid4()), 'detector': 'cost_anomaly', 'scope': 'global', 'severity': 'critical', 'version': 1}
        founder_cron._notifier(service, [OPERATOR], T0, fstore)('founder.incident_opened', incident)
        self.assertEqual(notifications.emitted[-1]['channel_filter'], ['in_app'])
        fstore.save_policy(OPERATOR, enabled_policy(channels=['call', 'push']), T0)
        self.assertEqual(founder_cron.notification_channels(fstore, OPERATOR), ['in_app', 'push'])
        fstore.save_policy(OPERATOR, enabled_policy(channels=['call', 'email', 'push']), T0 + 1)
        founder_cron._notifier(service, [OPERATOR], T0, fstore)('founder.incident_opened', {**incident, 'version': 2})
        self.assertEqual(notifications.emitted[-1]['channel_filter'], ['email', 'in_app', 'push'])
        fstore.save_policy(OPERATOR, enabled_policy(liveDeliveryEnabled=False, channels=['call', 'email', 'push']), T0 + 2)
        self.assertEqual(founder_cron.notification_channels(fstore, OPERATOR), ['in_app'], 'channels mean nothing while live delivery is off')

        class Broken(MemoryFounderStore):
            def policy(self, operator_id):
                raise RuntimeError('policy table unavailable')
        self.assertEqual(founder_cron.notification_channels(Broken(), OPERATOR), ['in_app'])


class OverviewAttentionHookTests(unittest.TestCase):
    """live_metrics._open_incidents discovers founder_incidents.open_incidents(service, principal) for the Live overview."""

    def row(self, state, **extra):
        return {'id': str(uuid.uuid4()), 'environment': 'local', 'detector': 'publish_failure_rate', 'scope': 'global', 'episode_key': f'publish_failure_rate:global:{state}',
                'severity': 'critical', 'state': state, 'opened_at': T0, 'acknowledged_at': None, 'resolved_at': None, 'evidence': {'ratio': 0.4, 'note': 'private'},
                'affected_count': 7, 'version': 1, **extra}

    def test_open_incidents_hook_lists_unresolved_episodes_as_content_free_attention_rows(self):
        from rafii_control import live_metrics
        fstore = MemoryFounderStore()
        opened = fstore.insert_incident(self.row('open'))
        fstore.insert_incident(self.row('resolved', resolved_at=T0 + 60))
        rows = founder_incidents.open_incidents(types.SimpleNamespace(), None, fstore=fstore)
        self.assertEqual(rows, [{'id': opened['id'], 'severity': 'critical', 'state': 'open', 'detector': 'publish_failure_rate', 'scope': 'global',
                                 'title': 'Publish failure rate · global', 'affectedCount': 7, 'observedAt': '2026-09-21T14:13:20Z', 'version': 1}])
        self.assertNotIn('evidence', rows[0])
        self.assertEqual(founder_incidents.open_incidents(types.SimpleNamespace(), None), [], 'no control store, nothing to report')
        self.assertEqual(live_metrics._open_incidents(types.SimpleNamespace(), None, 'live', None), [])

        class Broken:
            def open_incidents(self):
                raise RuntimeError('relation founder_incidents does not exist')
        with self.assertRaises(ControlError) as caught:
            founder_incidents.open_incidents(types.SimpleNamespace(), None, fstore=Broken())
        self.assertEqual((caught.exception.code, caught.exception.status), ('SOURCE_UNAVAILABLE', 503))
        # The overview tolerates that error (shows no incidents) instead of failing the whole page.
        self.assertEqual(live_metrics._open_incidents(types.SimpleNamespace(store=None), None, 'live', None), [])
        item = live_metrics._attention.__code__.co_varnames[:3]
        self.assertEqual(item, ('results', 'incidents', 'now'))


if __name__ == '__main__':
    unittest.main()
