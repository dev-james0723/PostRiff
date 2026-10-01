"""Founder briefing schedules: DST gap/fold, lateness, weekly-replaces-daily, occurrence uniqueness, and the (c)
schedule → cron → briefing → attempt → summary path through founder_cron.tick with the fake telephony provider.

In-memory founder store, fake consumer connection and FakeCalls (real planner + fake provider). No PostgreSQL, no network.
"""
import os
import types
import unittest
from datetime import datetime, timezone

os.environ.setdefault('RAFII_PHONE_PROVIDER', 'fake')

from rafii_control import founder_briefings, founder_cron, founder_schedules
from rafii_control.auth import ControlError
from rafii_control.founder_contact import FLAG
from rafii_control.founder_schedules import LATE_SECONDS, LEASE_SECONDS, claim_due, local_slot, next_occurrence, validate_schedule

try:
    from test_founder_contact import OPERATOR, PRINCIPAL, FakeCalls, MemoryFounderStore, enabled_policy
    from test_founder_incidents import FakeDB, FakeNotifications
except ImportError:  # python -m unittest control.test_founder_schedules
    from control.test_founder_contact import OPERATOR, PRINCIPAL, FakeCalls, MemoryFounderStore, enabled_policy
    from control.test_founder_incidents import FakeDB, FakeNotifications


def utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc).timestamp()


T_START = utc('2026-10-01T07:00:00Z')  # a Thursday
VALUES = {'RAFII_CONTROL_ENABLED': '1', FLAG: '1', 'RAFII_FOUNDER_OPS_WORKSPACE_ID': 'ops'}


def daily(local_time='08:00', zone='UTC'):
    return {'kind': 'daily', 'localTime': local_time, 'timeZone': zone}


def observations(now=T_START, **overrides):
    """Healthy observations as the cron would assemble them at `now`: every probed source fresh, publishing fine."""
    base = {'sources_probed': True,
            'sources': [{'source_id': s, 'state': 'measured', 'checked_at': now - 30, 'watermark': now - 30, 'reason_code': 'qualified'}
                        for s in ('cron', 'database', 'control_database')],
            'publish': {'available': True, 'failed': 1, 'uncertain': 0, 'verified': 12},
            'cost': {'available': True, 'today_usd_micro': 4_200_000, 'daily_usd_micro': [1_100_000] * 7, 'budget_stop_reached': False},
            'payments': {'available': False}}
    base.update(overrides)
    return base


class ScheduleRulesTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(validate_schedule(daily())['weekdays'], list(range(7)))
        weekly = validate_schedule({'kind': 'weekly', 'localTime': '09:15', 'weekdays': [3, 0, 3], 'timeZone': 'America/New_York', 'enabled': False})
        self.assertEqual((weekly['weekdays'], weekly['enabled']), ([0, 3], False))
        for bad in ({'kind': 'monthly', 'localTime': '08:00', 'timeZone': 'UTC'}, {'kind': 'daily', 'localTime': '24:00', 'timeZone': 'UTC'},
                    {'kind': 'weekly', 'localTime': '08:00', 'timeZone': 'UTC'}, {'kind': 'weekly', 'localTime': '08:00', 'weekdays': [7], 'timeZone': 'UTC'},
                    {'kind': 'daily', 'localTime': '08:00', 'timeZone': 'Mars/Olympus'}, {'kind': 'daily', 'localTime': '08:00', 'timeZone': 'UTC', 'extra': 1}):
            with self.subTest(bad=bad), self.assertRaises(ControlError):
                validate_schedule(bad)

    def test_dst_gap_moves_to_next_valid_minute_and_fold_uses_first_instance(self):
        gap = validate_schedule(daily('02:30', 'America/New_York'))
        due = next_occurrence(gap, utc('2026-03-08T06:00:00Z'))
        self.assertEqual((due['local'], due['scheduledFor']), ('2026-03-08T03:00:00-04:00', utc('2026-03-08T07:00:00Z')))
        self.assertEqual(local_slot(gap, due['scheduledFor']), ('2026-03-08', 150), 'the slot keeps the configured wall time')
        fold = validate_schedule(daily('01:30', 'America/New_York'))
        due = next_occurrence(fold, utc('2026-11-01T04:00:00Z'))
        self.assertEqual((due['local'], due['fold'], due['scheduledFor']), ('2026-11-01T01:30:00-04:00', 0, utc('2026-11-01T05:30:00Z')))
        following = next_occurrence(fold, due['scheduledFor'] + 1)
        self.assertEqual(following['local'], '2026-11-02T01:30:00-05:00', 'the repeated hour is not scheduled twice')

    def test_claim_commits_next_slot_first_and_duplicate_invocations_create_one_occurrence(self):
        fstore = MemoryFounderStore()
        created = founder_schedules.create_schedule(fstore, PRINCIPAL, daily(), now=T_START)
        schedule_id, next_at = created['schedule']['id'], created['schedule']['nextAt']
        self.assertEqual(next_at, utc('2026-10-01T08:00:00Z'))
        self.assertEqual(claim_due(fstore, T_START, lease_owner='a'), {'claimed': [], 'missed': [], 'coalesced': []})
        first = claim_due(fstore, next_at + 30, lease_owner='a')
        self.assertEqual(len(first['claimed']), 1)
        occurrence = first['claimed'][0]
        self.assertEqual((occurrence['state'], occurrence['local_date'], occurrence['slot'], occurrence['lease_owner']), ('claimed', '2026-10-01', 480, 'a'))
        self.assertEqual(fstore.schedule(schedule_id)['next_at'], utc('2026-10-02T08:00:00Z'), 'the next slot was committed before any dial')
        again = claim_due(fstore, next_at + 31, lease_owner='b')
        self.assertEqual(again, {'claimed': [], 'missed': [], 'coalesced': []})
        self.assertEqual(len(fstore.occurrences(schedule_id)), 1)
        # A concurrent invocation that read the old next_at loses the compare-and-set and creates nothing.
        self.assertIsNone(fstore.update_schedule(schedule_id, next_at=0, expected_next_at=next_at))
        # A crashed worker: the lease expires and the same occurrence is re-claimed, never a second one.
        reclaimed = claim_due(fstore, next_at + 30 + LEASE_SECONDS + 1, lease_owner='c')
        self.assertEqual([(o['id'], o['lease_owner']) for o in reclaimed['claimed']], [(occurrence['id'], 'c')])
        self.assertEqual(len(fstore.occurrences(schedule_id)), 1)

    def test_late_slot_is_missed_not_caught_up(self):
        fstore = MemoryFounderStore()
        created = founder_schedules.create_schedule(fstore, PRINCIPAL, daily(), now=T_START)
        late = claim_due(fstore, created['schedule']['nextAt'] + LATE_SECONDS + 1, lease_owner='a')
        self.assertEqual(([o['state'] for o in late['missed']], late['claimed']), (['missed'], []))
        self.assertEqual(fstore.schedule(created['schedule']['id'])['next_at'], utc('2026-10-02T08:00:00Z'))

    def test_weekly_replaces_daily_on_the_same_day(self):
        fstore = MemoryFounderStore()
        day = founder_schedules.create_schedule(fstore, PRINCIPAL, daily(), now=T_START)['schedule']
        week = founder_schedules.create_schedule(fstore, PRINCIPAL, {'kind': 'weekly', 'localTime': '09:00', 'weekdays': [3], 'timeZone': 'UTC'}, now=T_START)['schedule']
        self.assertEqual(week['nextAt'], utc('2026-10-01T09:00:00Z'))
        morning = claim_due(fstore, day['nextAt'] + 10, lease_owner='a')
        self.assertEqual(([o['state'] for o in morning['coalesced']], morning['claimed']), (['coalesced'], []))
        later = claim_due(fstore, week['nextAt'] + 10, lease_owner='a')
        self.assertEqual([o['schedule_id'] for o in later['claimed']], [week['id']])
        founder_schedules.finish_occurrence(fstore, later['claimed'][0]['id'], state='delivered', now=week['nextAt'] + 20)
        friday = claim_due(fstore, utc('2026-10-02T08:00:10Z'), lease_owner='a')
        self.assertEqual([o['schedule_id'] for o in friday['claimed']], [day['id']], 'the daily briefing resumes on a day without a weekly one')
        listing = founder_schedules.list_schedules(fstore, PRINCIPAL, now=T_START)
        self.assertEqual(len(listing['schedules']), 2)
        self.assertEqual(sorted(o['state'] for o in listing['occurrences']), ['claimed', 'coalesced', 'delivered'])
        self.assertTrue(founder_schedules.delete_schedule(fstore, PRINCIPAL, week['id'])['deleted'])
        self.assertFalse(founder_schedules.delete_schedule(fstore, PRINCIPAL, week['id'])['deleted'])
        for _ in range(3):
            founder_schedules.create_schedule(fstore, PRINCIPAL, daily('10:00'), now=T_START)
        with self.assertRaises(ControlError):
            founder_schedules.create_schedule(fstore, PRINCIPAL, daily('11:00'), now=T_START)


class BriefingTests(unittest.TestCase):
    def test_compose_is_deterministic_and_quotes_values_only(self):
        receipts = founder_cron.briefing_receipts(observations(), T_START)
        incidents = [{'id': 'i1', 'detector': 'cost_anomaly', 'scope': 'global', 'severity': 'critical', 'state': 'open', 'opened_at': T_START - 600, 'affected_count': 1},
                     {'id': 'i2', 'detector': 'source_silence', 'scope': 'cron', 'severity': 'warning', 'state': 'resolved', 'opened_at': T_START - 900, 'affected_count': 1}]
        first = founder_briefings.compose_brief('daily', receipts, now=T_START, time_zone='UTC', environment='local', incidents=incidents)
        second = founder_briefings.compose_brief('daily', receipts, now=T_START, time_zone='UTC', environment='local', incidents=incidents)
        self.assertEqual(first, second)
        self.assertIn('Founder daily briefing · Thursday 01 October 2026, 07:00 UTC · local environment', first['text'])
        self.assertIn('- critical cost_anomaly (global), open since 06:50, affecting 1', first['text'])
        self.assertNotIn('source_silence', first['text'], 'resolved incidents are not read out')
        self.assertIn('AI cost today (actual): USD 4.20', first['text'])
        self.assertIn('Verified publications (last hour): 12', first['text'])
        self.assertIn('New past-due subscriptions (24 h): not available', first['text'])
        self.assertEqual(first['coverage'], {'measured': 5, 'unavailable': 1, 'total': 6, 'dataState': 'partial'})
        self.assertTrue(first['text'].endswith(founder_briefings.CLOSING))
        self.assertEqual(first['receipt_ids'], [], 'facts without receipt ids never fabricate one')
        with self.assertRaises(ControlError):
            founder_briefings.compose_brief('monthly', receipts, now=T_START)

    def test_reports_are_immutable_versions(self):
        fstore = MemoryFounderStore()
        brief = founder_briefings.compose_brief('daily', [], now=T_START)
        one = founder_briefings.save_report(fstore, OPERATOR, brief)
        two = founder_briefings.save_report(fstore, OPERATOR, brief)
        self.assertEqual((one['version'], two['version']), (1, 2))
        self.assertNotEqual(one['id'], two['id'])
        self.assertEqual([r['version'] for r in founder_briefings.list_reports(fstore, PRINCIPAL)['reports']], [2, 1])
        self.assertEqual(founder_briefings.read_report(fstore, PRINCIPAL, one['id'])['report']['text'], brief['text'])
        with self.assertRaises(ControlError):
            founder_briefings.read_report(fstore, {'operator': {'user_id': 'someone-else'}}, one['id'])


class CronBriefingPathTests(unittest.TestCase):
    """(c) schedule → cron claim → report → attempt → summary, plus duplicate ticks and crash windows."""
    def setUp(self):
        self.fstore = MemoryFounderStore()
        self.fstore.destinations[OPERATOR] = True
        self.notifications = FakeNotifications()
        self.service = types.SimpleNamespace(connection_factory=lambda: FakeDB(self.notifications.emitted), notifications=self.notifications, phone=None)
        # The ops-workspace phone preferences have no quiet hours here; the founder policy's own quiet hours are tested separately.
        self.calls = FakeCalls(clock=lambda: self.now, prefs={'quietStart': 0, 'quietEnd': 0})
        self.now = T_START

    def tick(self, at, observe=None):
        self.now = at
        return founder_cron.tick(self.service, VALUES, fstore=self.fstore, calls_factory=lambda operator: self.calls, clock=lambda: at,
                                 observe=observe or (lambda fstore, service, values, now: observations(now)), lease_owner='test-cron')

    def test_disabled_control_or_missing_store_is_a_no_op(self):
        self.assertEqual(founder_cron.tick(self.service, {}), {'status': 'disabled'})
        self.assertEqual(founder_cron.tick(self.service, {'RAFII_CONTROL_ENABLED': '1'}), {'status': 'disabled', 'reason': 'control_store_not_configured'})
        self.assertIsNone(founder_cron.control_store({'RAFII_CONTROL_SESSION_DSN': 'x', 'RAFII_CONTROL_READER_DSN': 'x', 'RAFII_CONTROL_ENVIRONMENT': 'local'}))

    def test_briefing_is_composed_and_delivered_even_when_calls_are_off(self):
        schedule = founder_schedules.create_schedule(self.fstore, PRINCIPAL, daily(), now=T_START)['schedule']
        result = self.tick(schedule['nextAt'] + 20)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['probes']['cron'], 'measured')
        self.assertEqual(result['snapshot']['status'], 'unavailable', 'no snapshot table in the fake consumer database')
        delivered = result['schedules']['delivered']
        self.assertEqual(len(delivered), 1)
        self.assertEqual((delivered[0]['attemptState'], delivered[0]['decision']), ('suppressed', 'POLICY_DISABLED'))
        report = self.fstore.report(delivered[0]['reportId'])
        self.assertEqual((report['kind'], report['version']), ('daily', 1))
        self.assertIn('Founder daily briefing', report['text'])
        occurrence = self.fstore.occurrences(schedule['id'])[0]
        self.assertEqual((occurrence['state'], occurrence['report_id'], occurrence['attempt_id']), ('delivered', report['id'], delivered[0]['attemptId']))
        self.assertEqual([e['event_type'] for e in self.notifications.emitted], ['founder.briefing_ready'])
        self.assertEqual(self.calls.provider.create_count, 0)

    def test_schedule_to_call_to_summary_with_duplicate_ticks(self):
        self.fstore.save_policy(OPERATOR, enabled_policy(), T_START)
        schedule = founder_schedules.create_schedule(self.fstore, PRINCIPAL, daily(), now=T_START)['schedule']
        at = schedule['nextAt'] + 20
        result = self.tick(at)
        delivered = result['schedules']['delivered'][0]
        self.assertEqual((delivered['attemptState'], delivered['decision']), ('ringing', 'OK'))
        attempt = self.fstore.attempt_by_key('founder:briefing:' + delivered['reportId'])
        self.assertEqual((attempt['purpose'], attempt['state'], self.calls.calls[attempt['phone_call_id']]['kind']), ('briefing', 'ringing', 'scheduled'))
        self.assertEqual(self.calls.provider.create_count, 1)
        duplicate = self.tick(at + 1)
        self.assertEqual((duplicate['schedules'], self.calls.provider.create_count), ({'delivered': [], 'missed': [], 'coalesced': []}, 1))
        self.assertEqual(len(self.fstore.occurrences(schedule['id'])), 1)
        self.assertEqual(len(self.fstore.reports(OPERATOR)), 1)
        self.calls.provider_state(attempt['phone_call_id'], 'answered')
        self.assertEqual(self.tick(at + 40)['reconcile'], {'settled': {OPERATOR: 1}})
        self.calls.provider_state(attempt['phone_call_id'], 'completed')
        self.tick(at + 80)
        final = self.fstore.attempt_by_key(attempt['idempotency_key'])
        self.assertEqual(final['state'], 'completed')
        summary = founder_briefings.read_report(self.fstore, PRINCIPAL, delivered['reportId'])['report']
        self.assertEqual((summary['version'], summary['coverage']['dataState']), (1, 'partial'))
        self.assertEqual(self.fstore.occurrences(schedule['id'])[0]['state'], 'delivered')
        self.assertEqual(self.calls.provider.create_count, 1)

    def test_missed_slot_reaches_the_inbox_without_a_catch_up_call(self):
        self.fstore.save_policy(OPERATOR, enabled_policy(), T_START)
        schedule = founder_schedules.create_schedule(self.fstore, PRINCIPAL, daily(), now=T_START)['schedule']
        result = self.tick(schedule['nextAt'] + LATE_SECONDS + 5)
        self.assertEqual((result['schedules']['delivered'], len(result['schedules']['missed'])), ([], 1))
        self.assertEqual(self.fstore.occurrences(schedule['id'])[0]['state'], 'missed')
        self.assertEqual([e['event_type'] for e in self.notifications.emitted], ['founder.briefing_ready'])
        self.assertEqual((self.calls.provider.create_count, self.fstore.attempts(OPERATOR)), (0, []))

    def test_crash_after_the_claim_is_reconciled_never_redialed(self):
        self.fstore.save_policy(OPERATOR, enabled_policy(), T_START)
        schedule = founder_schedules.create_schedule(self.fstore, PRINCIPAL, daily(), now=T_START)['schedule']
        self.calls.crash_after_create = True
        at = schedule['nextAt'] + 20
        result = self.tick(at)
        delivered = result['schedules']['delivered'][0]
        self.assertEqual(delivered['attemptState'], 'ambiguous')
        self.assertEqual(self.calls.provider.create_count, 1)
        self.assertEqual(self.tick(at + 30)['reconcile'], {'settled': {OPERATOR: 0}}, 'inside the grace period nothing is re-sent')
        self.assertEqual(self.tick(at + 70)['reconcile'], {'settled': {OPERATOR: 1}})
        attempt = self.fstore.attempt_by_key('founder:briefing:' + delivered['reportId'])
        self.assertEqual((attempt['state'], attempt['phone_call_id'] is not None, self.calls.provider.create_count), ('ringing', True, 1))

    def test_critical_incident_from_observations_plans_a_contact_once(self):
        self.fstore.save_policy(OPERATOR, enabled_policy(), T_START)

        def broken(fstore, service, values, now):
            return observations(now, publish={'available': True, 'failed': 6, 'uncertain': 0, 'verified': 4})
        first = self.tick(T_START, observe=broken)
        incidents = first['incidents']
        self.assertEqual((len(incidents['opened']), [c['state'] for c in incidents['contacts']], [c['created'] for c in incidents['contacts']]), (1, ['ringing'], [True]))
        self.assertEqual([e['event_type'] for e in self.notifications.emitted], ['founder.incident_opened'])
        second = self.tick(T_START + 60, observe=broken)
        self.assertEqual(([c['created'] for c in second['incidents']['contacts']], self.calls.provider.create_count), ([False], 1))
        kinds = [e['kind'] for e in self.fstore.incident_events(incidents['opened'][0])]
        self.assertEqual(kinds, ['opened', 'contact_dispatched'])
        recovered = self.tick(T_START + 120)
        self.assertEqual(recovered['incidents']['resolved'], incidents['opened'])
        self.assertEqual([e['event_type'] for e in self.notifications.emitted][-1], 'founder.incident_recovered')

    def test_stage_failures_are_reported_not_raised(self):
        class Broken(MemoryFounderStore):
            def due_schedules(self, now):
                raise RuntimeError('boom')
        store = Broken()
        result = founder_cron.tick(self.service, VALUES, fstore=store, calls_factory=lambda operator: None, clock=lambda: T_START,
                                   observe=lambda fstore, service, values, now: observations(now), lease_owner='test-cron')
        self.assertEqual((result['status'], result['schedules']), ('partial', {'status': 'unavailable', 'error': 'RuntimeError'}))
        self.assertEqual(result['reconcile'], {'settled': {OPERATOR: 0}})


if __name__ == '__main__':
    unittest.main()
