"""Founder notices (CONTRACTS §8.E; PRD §6.7, §8.7): in-app always, email/push only through the contact policy AND the
deployment flags AND the founder's preference, quiet hours below critical/security, the daily digest stage, the
preference and notice routes through the real Control boundary, and best-effort consumer writes.

In-memory founder centre and founder store, a fake consumer outbox and connection. No PostgreSQL, no network, no email or
push provider (test_founder_notifications_pg.py covers migration 067 on a disposable database).
"""
import copy
import io
import json
import os
import time
import types
import unittest
import uuid
from datetime import datetime, timezone
from unittest import mock

import psycopg

os.environ.setdefault('RAFII_PHONE_PROVIDER', 'fake')

from postriff_phase2.notifications import catalog
from rafii_control import founder_cron, founder_notifications as fn, http
from rafii_control.auth import CAPABILITIES, Boundary, Config, ControlError, VerifiedIdentity
from rafii_control.http import ControlApplication

try:
    from test_boundary import MemoryStore, USER
    from test_founder_contact import OPERATOR, MemoryFounderStore, enabled_policy
    from test_founder_incidents import FakeNotifications
except ImportError:  # python -m unittest control.test_founder_notifications
    from control.test_boundary import MemoryStore, USER
    from control.test_founder_contact import OPERATOR, MemoryFounderStore, enabled_policy
    from control.test_founder_incidents import FakeNotifications

FLAGS_ON = {'RAFII_FOUNDER_EMAIL_ENABLED': '1', 'RAFII_FOUNDER_PUSH_ENABLED': '1'}
FLAGS_OFF = {}


def utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc).timestamp()


# Indianapolis (EDT, UTC-4) on Thursday 2026-10-01; default quiet hours 22:00-08:00 local, digest at 09:00 local.
EARLY = utc('2026-10-01T11:30:00Z')     # 07:30 local: quiet hours, before the digest hour
DAYTIME = utc('2026-10-01T12:30:00Z')   # 08:30 local
MORNING = utc('2026-10-01T13:30:00Z')   # 09:30 local: after the digest hour, outside quiet hours
NIGHT = utc('2026-10-02T03:30:00Z')     # 23:30 local on 1 October: quiet hours again


def incident(severity='critical', version=1, detector='publish_failure_rate', scope='global', state='open'):
    return {'id': str(uuid.uuid4()), 'detector': detector, 'scope': scope, 'severity': severity, 'state': state, 'version': version}


def report(kind='daily', version=1):
    return {'id': str(uuid.uuid4()), 'kind': kind, 'version': version, 'receipt_ids': [str(uuid.uuid4())]}


class MemoryCentre:
    """In-memory founder centre with the NoticeSQL method surface. `missing=True` behaves like migration 067 not applied."""

    def __init__(self, environment='local'):
        self.environment, self.prefs, self.rows, self.missing, self.purged = environment, {}, {}, False, []

    def _check(self):
        if self.missing:
            raise psycopg.errors.UndefinedTable('relation "rafii_control.founder_notices" does not exist')

    def preferences(self, operator_id):
        self._check()
        return copy.deepcopy(self.prefs.get(operator_id))

    def save_preferences(self, operator_id, prefs, now):
        self._check()
        revision = (self.prefs.get(operator_id) or {}).get('revision', 0) + 1
        row = {key: copy.deepcopy(prefs[key]) for key in ('events', 'digest_enabled', 'digest_email', 'digest_hour', 'quiet_start', 'quiet_end', 'time_zone')}
        self.prefs[operator_id] = {**row, 'revision': revision, 'updated_at': now}
        return copy.deepcopy(self.prefs[operator_id])

    def insert_notice(self, row):
        self._check()
        for existing in self.rows.values():
            if (existing['operator_id'], existing['dedupe_key']) == (row['operator_id'], row['dedupe_key']):
                return copy.deepcopy(existing), False
        stored = {**copy.deepcopy(row), 'environment': self.environment, 'digest_id': None, 'read_at': None}
        self.rows[row['id']] = stored
        return copy.deepcopy(stored), True

    def notice_by_dedupe(self, operator_id, dedupe_key):
        self._check()
        return next((copy.deepcopy(r) for r in self.rows.values() if (r['operator_id'], r['dedupe_key']) == (operator_id, dedupe_key)), None)

    def notices(self, operator_id, *, limit=50):
        self._check()
        rows = sorted((r for r in self.rows.values() if r['operator_id'] == operator_id), key=lambda r: (r['created_at'], r['id']), reverse=True)
        return [copy.deepcopy(r) for r in rows[:limit]]

    def unread(self, operator_id):
        self._check()
        return sum(1 for r in self.rows.values() if r['operator_id'] == operator_id and r['read_at'] is None)

    def mark_read(self, operator_id, notice_id, now):
        self._check()
        row = self.rows.get(notice_id)
        if row is None or row['operator_id'] != operator_id:
            return None
        row['read_at'] = row['read_at'] if row['read_at'] is not None else now
        return copy.deepcopy(row)

    def pending_digest(self, operator_id, *, limit=200):
        self._check()
        rows = sorted((r for r in self.rows.values() if r['operator_id'] == operator_id and r['digest_state'] == 'pending'), key=lambda r: (r['created_at'], r['id']))
        return [copy.deepcopy(r) for r in rows[:limit]]

    def include_in_digest(self, operator_id, notice_ids, digest_id):
        self._check()
        count = 0
        for notice_id in notice_ids:
            row = self.rows.get(notice_id)
            if row and row['operator_id'] == operator_id and row['digest_state'] == 'pending':
                row.update(digest_state='included', digest_id=digest_id)
                count += 1
        return count

    def purge(self, before):
        self._check()
        old = [notice_id for notice_id, row in self.rows.items() if row['created_at'] < before][:500]
        for notice_id in old:
            del self.rows[notice_id]
        self.purged.append(before)
        return len(old)


class CentreStore(MemoryFounderStore):
    """The P0 in-memory founder store plus an injected founder centre (founder_notifications.notice_store reads it)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.notice_centre = MemoryCentre(self.environment)


class Outbox(FakeNotifications):
    """The consumer NotificationService surface: records each emit; `fail` raises inside emit (e.g. a missing table)."""

    def __init__(self, enabled=True, fail=None, email=True, push=True):
        super().__init__(enabled)
        self.fail, self.email, self.push = fail, email, push

    def emit(self, cur, **event):
        if self.fail is not None:
            raise self.fail
        self.emitted.append(event)
        return {'eventId': str(uuid.uuid4()), 'created': True,
                'deliveries': [{'channel': c, 'status': 'delivered' if c == 'in_app' else 'pending'} for c in event.get('channel_filter') or []]}

    def email_available(self):
        return self.email

    def push_enabled(self):
        return self.push


class RecordingCursor:
    def __init__(self, statements):
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.statements.append(sql)

    def fetchone(self):
        return (None,)

    def fetchall(self):
        return []


class RecordingDB:
    def __init__(self):
        self.statements, self.commits = [], 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return RecordingCursor(self.statements)

    def commit(self):
        self.commits += 1


def prefs(**changes):
    out = fn.merge_preferences(None)
    out.update(changes)
    return out


class RoutingTests(unittest.TestCase):
    def test_route_table_follows_prd_6_7(self):
        self.assertEqual(fn.route('founder.incident_opened', 'critical'), {'email': 'immediate', 'push': 'immediate'})
        self.assertEqual(fn.route('founder.source_unavailable', 'security'), {'email': 'immediate', 'push': 'immediate'})
        self.assertEqual(fn.route('founder.incident_opened', 'warning'), {'email': 'digest', 'push': 'off'})
        self.assertEqual(fn.route('founder.incident_recovered', 'info'), {'email': 'digest', 'push': 'off'})
        self.assertEqual(fn.route('founder.briefing_ready', 'info'), {'email': 'digest', 'push': 'immediate'})
        self.assertEqual(fn.route(fn.DIGEST_EVENT, 'info'), {'email': 'immediate', 'push': 'off'})
        self.assertEqual(fn.route(fn.TEST_EVENT, 'info'), {'email': 'off', 'push': 'off'})

    def test_email_and_push_need_the_policy_the_flag_and_the_preference(self):
        default = fn.plan_notice('founder.incident_opened', 'critical', prefs(), founder_policy(), FLAGS_ON, DAYTIME)
        self.assertEqual((default['outbox'], default['email']['reason'], default['push']['blockers']),
                         (['in_app'], 'live_delivery_disabled', ['live_delivery_disabled', 'channel_not_in_policy']))
        policy = enabled_policy(channels=['call', 'email', 'push'])
        no_flags = fn.plan_notice('founder.incident_opened', 'critical', prefs(), policy, FLAGS_OFF, DAYTIME)
        self.assertEqual((no_flags['outbox'], no_flags['email']['reason'], no_flags['push']['reason']), (['in_app'], 'deployment_flag_unset', 'deployment_flag_unset'))
        allowed = fn.plan_notice('founder.incident_opened', 'critical', prefs(), policy, FLAGS_ON, DAYTIME)
        self.assertEqual(allowed['outbox'], ['email', 'in_app', 'push'])
        self.assertFalse(allowed['digest'], 'a critical notice goes out now, not in the digest')
        push_only = fn.plan_notice('founder.incident_opened', 'critical', prefs(), enabled_policy(channels=['call', 'push']), FLAGS_ON, DAYTIME)
        self.assertEqual((push_only['outbox'], push_only['email']['reason']), (['in_app', 'push'], 'channel_not_in_policy'))
        email_flag_only = fn.plan_notice('founder.incident_opened', 'critical', prefs(), policy, {'RAFII_FOUNDER_EMAIL_ENABLED': '1'}, DAYTIME)
        self.assertEqual(email_flag_only['outbox'], ['email', 'in_app'])
        muted = prefs()
        muted['events']['founder.incident_opened'] = {'email': False, 'push': True}
        chosen = fn.plan_notice('founder.incident_opened', 'critical', muted, policy, FLAGS_ON, DAYTIME)
        self.assertEqual((chosen['outbox'], chosen['email']['reason']), (['in_app', 'push'], 'preference_off'))
        for flag in ('0', 'false', '', None):
            with self.subTest(flag=flag):
                self.assertEqual(fn.plan_notice('founder.incident_opened', 'critical', prefs(), policy, {'RAFII_FOUNDER_EMAIL_ENABLED': flag}, DAYTIME)['outbox'], ['in_app'])

    def test_quiet_hours_hold_everything_below_critical_and_security(self):
        policy = enabled_policy(channels=['call', 'email', 'push'])
        for severity in ('critical', 'security'):
            with self.subTest(severity=severity):
                self.assertEqual(fn.plan_notice('founder.source_unavailable', severity, prefs(), policy, FLAGS_ON, EARLY)['outbox'], ['email', 'in_app', 'push'])
        briefing = fn.plan_notice('founder.briefing_ready', 'info', prefs(), policy, FLAGS_ON, EARLY)
        self.assertEqual((briefing['outbox'], briefing['push']['reason'], briefing['email']['mode']), (['in_app'], 'quiet_hours', 'digest'))
        self.assertEqual(fn.plan_notice('founder.briefing_ready', 'info', prefs(), policy, FLAGS_ON, DAYTIME)['outbox'], ['in_app', 'push'])
        night = fn.plan_notice('founder.briefing_ready', 'info', prefs(), policy, FLAGS_ON, NIGHT)
        self.assertEqual(night['outbox'], ['in_app'])
        custom = prefs(quiet_start=0, quiet_end=0)   # no quiet window at all
        self.assertEqual(fn.plan_notice('founder.briefing_ready', 'info', custom, policy, FLAGS_ON, NIGHT)['outbox'], ['in_app', 'push'])

    def test_warnings_join_the_daily_digest(self):
        policy = enabled_policy(channels=['call', 'email', 'push'])
        warning = fn.plan_notice('founder.incident_opened', 'warning', prefs(), policy, FLAGS_ON, DAYTIME)
        self.assertEqual((warning['outbox'], warning['email']['mode'], warning['push']['reason'], warning['digest']), (['in_app'], 'digest', 'not_routed', True))
        closed = fn.plan_notice('founder.incident_opened', 'warning', prefs(), founder_policy(), FLAGS_OFF, DAYTIME)
        self.assertTrue(closed['digest'], 'warnings reach the in-app digest even when no email may leave')
        self.assertEqual(closed['email']['blockers'], ['live_delivery_disabled', 'channel_not_in_policy', 'deployment_flag_unset'])
        muted = prefs()
        muted['events']['founder.incident_opened'] = {'email': False, 'push': True}
        held = fn.plan_notice('founder.incident_opened', 'warning', muted, policy, FLAGS_ON, DAYTIME)
        self.assertEqual((held['digest'], held['email']['reason']), (True, 'preference_off'), 'no email for it, but still in the in-app digest')
        off = fn.plan_notice('founder.incident_opened', 'warning', prefs(digest_enabled=False), policy, FLAGS_ON, DAYTIME)
        self.assertEqual((off['digest'], off['email']['reason']), (False, 'digest_disabled'))
        recovered = fn.plan_notice('founder.incident_recovered', 'info', prefs(), policy, FLAGS_ON, DAYTIME)
        self.assertEqual((recovered['outbox'], recovered['digest']), (['in_app'], True))
        test = fn.plan_notice(fn.TEST_EVENT, 'info', prefs(), policy, FLAGS_ON, DAYTIME)
        self.assertEqual((test['outbox'], test['digest'], test['email']['reason']), (['in_app'], False, 'not_routed'))


def founder_policy():
    from rafii_control.founder_contact import DEFAULT_POLICY
    return dict(DEFAULT_POLICY)


class NotifierTests(unittest.TestCase):
    def setUp(self):
        fn._LOGGED.clear()
        self.fstore = CentreStore()
        self.centre = self.fstore.notice_centre
        self.db = RecordingDB()
        self.outbox = Outbox()
        self.service = types.SimpleNamespace(connection_factory=lambda: self.db, notifications=self.outbox)

    def notify(self, event_type, subject, now=DAYTIME, values=FLAGS_OFF, service=None, fstore=None):
        notify = fn.notifier(service or self.service, [OPERATOR], now, self.fstore if fstore is None else fstore, values)
        return notify(event_type, subject)

    def test_in_app_always_even_when_the_consumer_outbox_is_off(self):
        service = types.SimpleNamespace(connection_factory=lambda: self.db, notifications=Outbox(enabled=False))
        subject = incident('warning')
        self.assertEqual(self.notify('founder.incident_opened', subject, service=service), [])
        rows = self.centre.notices(OPERATOR)
        self.assertEqual([(r['event_type'], r['severity'], r['title'], r['digest_state']) for r in rows],
                         [('founder.incident_opened', 'warning', 'warning incident: publish_failure_rate (global)', 'pending')])
        self.assertEqual(rows[0]['channels']['in_app'], {'mode': 'immediate', 'state': 'delivered'})
        self.assertEqual((self.db.statements, self.db.commits), ([], 0), 'no consumer connection without an enabled outbox')
        self.assertIsNone(fn.notifier(service, [OPERATOR], DAYTIME, MemoryFounderStore(), FLAGS_OFF), 'no centre and no outbox: nothing to notify')
        self.assertIsNone(fn.notifier(self.service, [], DAYTIME, self.fstore, FLAGS_OFF))

    def test_critical_notice_leaves_by_email_and_push_only_through_every_gate(self):
        subject = incident('critical')
        self.notify('founder.incident_opened', subject)
        self.assertEqual(self.outbox.emitted[-1]['channel_filter'], ['in_app'], 'default policy: in-app only')
        self.fstore.save_policy(OPERATOR, enabled_policy(channels=['call', 'email', 'push']), DAYTIME)
        self.notify('founder.incident_opened', {**subject, 'version': 2})
        self.assertEqual(self.outbox.emitted[-1]['channel_filter'], ['in_app'], 'policy alone is not enough: the deployment flags are off')
        self.notify('founder.incident_opened', {**subject, 'version': 3}, values=FLAGS_ON)
        event = self.outbox.emitted[-1]
        self.assertEqual(event['channel_filter'], ['email', 'in_app', 'push'])
        self.assertEqual((event['workspace_id'], event['user_id'], event['event_type'], event['entity_type'], event['entity_id']),
                         (None, OPERATOR, 'founder.incident_opened', 'founder_incident', subject['id']))
        self.assertEqual(event['payload'], {'title': 'critical incident: publish_failure_rate (global)', 'href': '/founder/operations?tab=incidents'})
        self.assertEqual(event['dedupe_key'], f"founder.incident_opened:{subject['id']}:3")
        stored = self.centre.notice_by_dedupe(OPERATOR, event['dedupe_key'])
        self.assertEqual((stored['channels']['email'], stored['channels']['push']['outbox']), ({'mode': 'immediate', 'outbox': 'planned'}, 'planned'))
        self.assertEqual(self.db.statements.count('SAVEPOINT founder_notice'), 3)
        self.assertEqual(self.db.commits, 3, 'one short consumer connection per notice')

    def test_replays_are_one_notice_and_text_is_fixed_vocabulary(self):
        subject = report('weekly', 4)
        for _ in range(2):
            self.notify('founder.briefing_ready', subject)
        rows = self.centre.notices(OPERATOR)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['title'], rows[0]['subject_type'], rows[0]['facts']), ('Founder weekly briefing v4 is ready', 'founder_report', {'kind': 'weekly', 'version': 4, 'receipts': 1}))
        self.assertEqual([e['dedupe_key'] for e in self.outbox.emitted], ['founder.briefing_ready:' + subject['id']] * 2, 'the outbox dedupes its own replays')
        public = fn.public_notice(rows[0])
        self.assertEqual(public['href'], '/founder/settings?tab=reports&report=' + subject['id'])
        self.assertFalse(public['read'])
        source = incident('critical', detector='source_silence', scope='database')
        self.notify('founder.source_unavailable', source)
        self.assertEqual(self.outbox.emitted[-1]['payload']['title'], 'Source unavailable: database (critical)')
        with self.assertRaises(ValueError):
            fn.describe('founder.unknown', subject)
        with self.assertRaises(ValueError):
            fn.describe('founder.incident_opened', {**source, 'id': 'not an id; drop'})

    def test_missing_outbox_tables_are_not_installed_yet_and_logged_once(self):
        outbox = Outbox(fail=psycopg.errors.UndefinedTable('relation "public.pr_notification_events" does not exist'))
        service = types.SimpleNamespace(connection_factory=lambda: self.db, notifications=outbox)
        with self.assertLogs('rafii_control.founder_notifications', level='WARNING') as logs:
            first = self.notify('founder.incident_opened', incident('critical'), service=service)
            second = self.notify('founder.incident_opened', incident('critical'), service=service)
        self.assertEqual([r['error'] for r in first + second], ['UndefinedTable', 'UndefinedTable'])
        self.assertEqual(len(logs.records), 1, 'one log line per process and exception class')
        self.assertIn('"error": "UndefinedTable"', logs.output[0])
        self.assertNotIn('pr_notification_events', logs.output[0], 'never the message')
        self.assertEqual(self.db.statements.count('ROLLBACK TO SAVEPOINT founder_notice'), 2)
        self.assertEqual(len(self.centre.notices(OPERATOR)), 2, 'the in-app centre still has both notices')

    def test_missing_centre_table_keeps_the_outbox_and_never_raises(self):
        self.centre.missing = True
        with self.assertLogs('rafii_control.founder_notifications', level='WARNING') as logs:
            emitted = self.notify('founder.incident_opened', incident('critical'))
        self.assertEqual(len(emitted), 1)
        self.assertEqual(self.outbox.emitted[-1]['channel_filter'], ['in_app'])
        self.assertTrue(any('founder_notice.centre_unavailable' in line or 'founder_notice.preferences_unavailable' in line for line in logs.output))

        class Broken:
            def __call__(self):
                raise psycopg.OperationalError('connection refused to host with password')
        service = types.SimpleNamespace(connection_factory=Broken(), notifications=self.outbox)
        self.centre.missing = False
        self.assertEqual(self.notify('founder.incident_opened', incident('critical'), service=service), [], 'no consumer connection: nothing raised')

    def test_cron_tick_records_founder_notices_for_incidents_and_recovery(self):
        def broken(fstore, service, values, now):
            return {'sources_probed': True, 'sources': [{'source_id': s, 'state': 'measured', 'checked_at': now - 30, 'watermark': now - 30, 'reason_code': 'qualified'}
                                                        for s in ('cron', 'database', 'control_database')],
                    'publish': {'available': True, 'failed': 3, 'uncertain': 0, 'verified': 7}, 'cost': {'available': False}, 'payments': {'available': False}}

        def healthy(fstore, service, values, now):
            return {**broken(fstore, service, values, now), 'publish': {'available': True, 'failed': 0, 'uncertain': 0, 'verified': 20}}
        values = {'RAFII_CONTROL_ENABLED': '1'}
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in fn.FLAGS.values():
                os.environ.pop(name, None)
            founder_cron.tick(self.service, values, fstore=self.fstore, calls_factory=lambda operator: None, clock=lambda: DAYTIME, observe=broken, lease_owner='t')
            founder_cron.tick(self.service, values, fstore=self.fstore, calls_factory=lambda operator: None, clock=lambda: DAYTIME + 60, observe=healthy, lease_owner='t')
        rows = sorted(self.centre.notices(OPERATOR), key=lambda r: r['created_at'])
        self.assertEqual([(r['event_type'], r['severity'], r['digest_state']) for r in rows],
                         [('founder.incident_opened', 'warning', 'pending'), ('founder.incident_recovered', 'info', 'pending')])
        self.assertEqual([e['channel_filter'] for e in self.outbox.emitted], [['in_app'], ['in_app']])


class DigestTests(unittest.TestCase):
    def setUp(self):
        fn._LOGGED.clear()
        self.fstore = CentreStore()
        self.centre = self.fstore.notice_centre
        self.db = RecordingDB()
        self.outbox = Outbox()
        self.service = types.SimpleNamespace(connection_factory=lambda: self.db, notifications=self.outbox)

    def seed(self, now=DAYTIME):
        notify = fn.notifier(types.SimpleNamespace(notifications=None), [OPERATOR], now, self.fstore, FLAGS_OFF)
        notify('founder.incident_opened', incident('warning'))
        notify('founder.incident_opened', incident('warning', detector='cost_anomaly'))
        notify('founder.incident_recovered', incident('warning', version=2))
        notify('founder.incident_opened', incident('critical'))   # critical: sent now, never held for the digest

    def stage(self, now, values=FLAGS_OFF):
        return fn.digest_stage(self.fstore, self.service, values, now)

    def test_digest_waits_for_its_hour_and_quiet_hours_then_runs_once_a_day(self):
        self.seed()
        self.assertEqual(self.stage(EARLY)['operators'], {OPERATOR: 'not_due'})
        self.centre.prefs[OPERATOR] = {**fn.merge_preferences(None), 'digest_hour': 7}
        self.assertEqual(self.stage(EARLY)['operators'], {OPERATOR: 'quiet_hours'})
        del self.centre.prefs[OPERATOR]
        result = self.stage(MORNING)
        self.assertEqual((result['status'], result['operators']), ('ok', {OPERATOR: 'in_app'}))
        digest = self.centre.notice_by_dedupe(OPERATOR, 'founder.digest_ready:2026-10-01')
        self.assertEqual(digest['title'], 'Founder daily digest · 2026-10-01: 2 warnings, 1 other notice')
        self.assertEqual(digest['facts']['events'], {'founder.incident_opened': 2, 'founder.incident_recovered': 1})
        included = [r for r in self.centre.notices(OPERATOR) if r['digest_state'] == 'included']
        self.assertEqual((len(included), {r['digest_id'] for r in included}), (3, {digest['id']}))
        self.assertEqual(self.centre.pending_digest(OPERATOR), [])
        self.assertEqual(self.stage(MORNING + 3600)['operators'], {OPERATOR: 'done'})
        self.assertEqual(self.outbox.emitted, [], 'no email: the policy and flags are closed')
        self.assertEqual(digest['channels']['email'], {'mode': 'off', 'reason': 'live_delivery_disabled', 'blockers': ['live_delivery_disabled', 'channel_not_in_policy', 'deployment_flag_unset']})
        tomorrow = utc('2026-10-02T13:30:00Z')
        self.assertEqual(self.stage(tomorrow)['operators'], {OPERATOR: 'nothing_pending'})
        self.centre.prefs[OPERATOR] = {**fn.merge_preferences(None), 'digest_enabled': False}
        self.assertEqual(self.stage(tomorrow)['operators'], {OPERATOR: 'disabled'})

    def test_digest_email_only_through_policy_flags_and_preference(self):
        self.seed()
        self.fstore.save_policy(OPERATOR, enabled_policy(channels=['call', 'email']), DAYTIME)
        result = self.stage(MORNING, FLAGS_ON)
        self.assertEqual(result['operators'], {OPERATOR: 'emailed'})
        (event,) = self.outbox.emitted
        digest = self.centre.notice_by_dedupe(OPERATOR, 'founder.digest_ready:2026-10-01')
        self.assertEqual((event['event_type'], event['channel_filter'], event['dedupe_key'], event['entity_id']),
                         ('founder.digest_ready', ['email'], 'founder.digest_ready:' + digest['id'], digest['id']))
        self.assertEqual(event['payload']['count'], 3)
        self.assertEqual(event['payload']['metrics'], [{'label': 'Incident opened', 'value': '2'}, {'label': 'Incident recovered', 'value': '1'}])
        self.assertEqual(set(event['payload']), {'title', 'href', 'count', 'metrics'})
        self.assertEqual(catalog.spec('founder.digest_ready')['template'], 'digest')

    def test_stage_never_raises_and_purges_past_retention(self):
        self.assertEqual(fn.digest_stage(MemoryFounderStore(), self.service, FLAGS_OFF, MORNING), {'status': 'unavailable', 'reason': 'notice_centre_unavailable'})
        self.centre.missing = True
        self.assertEqual(self.stage(MORNING), {'status': 'unavailable', 'reason': 'notifications_not_installed'})
        self.centre.missing = False
        self.seed(now=MORNING - 401 * 86400)
        self.assertEqual(self.stage(MORNING)['purged'], 4)
        self.assertEqual(self.centre.purged, [MORNING - fn.RETENTION_SECONDS])

        class Exploding(CentreStore):
            def founder_operators(self):
                raise RuntimeError('boom')
        self.assertEqual(fn.digest_stage(Exploding(), self.service, FLAGS_OFF, MORNING), {'status': 'unavailable', 'error': 'RuntimeError'})

    def test_digest_is_a_registered_cron_stage(self):
        self.assertIn(fn.STAGE, [name for name, _work in founder_cron.STAGES])
        self.seed()
        quiet = {'sources_probed': True, 'sources': [], 'publish': {'available': False}, 'cost': {'available': False}, 'payments': {'available': False}}
        result = founder_cron.tick(self.service, {'RAFII_CONTROL_ENABLED': '1'}, fstore=self.fstore, calls_factory=lambda operator: None, clock=lambda: MORNING,
                                   observe=lambda *args: quiet, lease_owner='t')
        self.assertEqual(result[fn.STAGE]['operators'], {OPERATOR: 'in_app'})
        json.dumps(result, allow_nan=False)


class PreferenceTests(unittest.TestCase):
    def test_validation_is_strict_and_never_widens_a_channel(self):
        current = fn.merge_preferences(None)
        merged = fn.validate_preferences({'events': {'founder.briefing_ready': {'push': False}}, 'digest': {'hour': 7, 'email': False},
                                          'quietHours': {'start': 1380, 'end': 420, 'timeZone': 'Asia/Hong_Kong'}}, current)
        self.assertEqual((merged['events']['founder.briefing_ready'], merged['digest_hour'], merged['digest_email'], merged['quiet_start'], merged['time_zone']),
                         ({'email': True, 'push': False}, 7, False, 1380, 'Asia/Hong_Kong'))
        self.assertEqual(merged['events']['founder.incident_opened'], {'email': True, 'push': True}, 'untouched events keep their values')
        for bad in ({}, {'inApp': False}, {'events': {'founder.unknown': {'email': True}}}, {'events': {'founder.incident_opened': {'sms': True}}},
                    {'events': {'founder.incident_opened': {'email': 'yes'}}}, {'events': {'founder.incident_opened': {}}}, {'digest': {'hour': 24}},
                    {'digest': {'hour': True}}, {'digest': {}}, {'quietHours': {'start': 1440}}, {'quietHours': {'timeZone': 'Mars/Olympus'}},
                    {'quietHours': {'timeZone': '../../etc/passwd'}}, {'events': {'founder.incident_opened': {'email': True}}, 'liveDelivery': True}, []):
            with self.subTest(bad=bad), self.assertRaises(ControlError) as caught:
                fn.validate_preferences(bad, current)
            self.assertEqual((caught.exception.code, caught.exception.status), ('VALIDATION_FAILED', 400))

    def test_readiness_names_every_failing_gate(self):
        policy = founder_policy()
        closed = fn.readiness(policy, FLAGS_OFF, None)
        self.assertEqual(closed['email'], {'ready': False, 'blockers': ['live_delivery_disabled', 'channel_not_in_policy', 'deployment_flag_unset'],
                                           'policyListed': False, 'liveDeliveryEnabled': False, 'flag': False, 'transport': None})
        self.assertEqual(closed['inApp'], {'ready': True, 'blockers': []})
        policy = enabled_policy(channels=['call', 'email', 'push'])
        ready = fn.readiness(policy, FLAGS_ON, {'enabled': True, 'email': True, 'push': False})
        self.assertEqual((ready['email']['ready'], ready['push']['blockers']), (True, ['outbox_unavailable']))


class ControlRouteTests(unittest.TestCase):
    """The routes through the real Control boundary: capability, CSRF, step-up, Demo refusal and the envelope."""

    def setUp(self):
        fn._LOGGED.clear()
        self.store = MemoryStore()
        self.store.operator_row['capabilities'] = sorted(CAPABILITIES)
        self.time = time.time()
        self.boundary = Boundary(Config(True, 'local', 'http://localhost:4449'), self.store, lambda token: VerifiedIdentity(USER, 'aal2', 's' * 32, self.time),
                                 clock=lambda: self.time)
        self.app = ControlApplication(self.boundary, types.SimpleNamespace(store=self.store), flags={'RAFII_FOUNDER_EMAIL_ENABLED': '1'})
        self.fstore = CentreStore(operators=(USER,))
        self.centre = self.fstore.notice_centre
        self.app._founder_store = self.fstore
        patcher = mock.patch.object(fn, 'app_centre', lambda app: self.centre)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.token, session = self.boundary.exchange('verified-token', 'http://localhost:4449')
        self.csrf = session['csrfToken']

    def request(self, path, method='GET', body=None):
        raw = json.dumps(body).encode() if body is not None else b''
        path, _, query = path.partition('?')
        env = dict(PATH_INFO='/api/control/v2' + path, QUERY_STRING=query, REQUEST_METHOD=method, CONTENT_LENGTH=str(len(raw)), CONTENT_TYPE='application/json',
                   HTTP_HOST='localhost:4449', HTTP_ORIGIN='http://localhost:4449', HTTP_COOKIE='__Host-rafii-control=' + self.token, HTTP_X_CSRF_TOKEN=self.csrf,
                   **{'wsgi.input': io.BytesIO(raw)})
        result = {}
        data = b''.join(self.app(env, lambda status, headers: result.update(status=int(status[:3]))))
        return result['status'], json.loads(data)

    def test_preferences_get_and_put_with_step_up(self):
        status, body = self.request('/notifications/preferences?mode=demo')
        self.assertEqual(status, 200)
        data = body['data']
        self.assertEqual((data['installed'], data['preferences']['revision'], data['preferences']['digest']), (True, 0, {'enabled': True, 'hour': 9, 'email': True}))
        self.assertEqual(data['readiness']['email']['blockers'], ['live_delivery_disabled', 'channel_not_in_policy'], 'the email flag is set here, the policy is closed')
        self.assertEqual(data['readiness']['push']['blockers'], ['live_delivery_disabled', 'channel_not_in_policy', 'deployment_flag_unset'])
        self.assertEqual((data['flags'], data['readiness']['email']['transport']), ({'founderEmailEnabled': True, 'founderPushEnabled': False}, None))
        self.assertEqual([event['type'] for event in data['events']], list(fn.NOTICE_EVENTS))
        self.assertEqual(self.store.events[-1]['action'], 'control.read')
        patch = {'events': {'founder.briefing_ready': {'push': False}}, 'quietHours': {'start': 1380}}
        self.time += 400   # the second factor is no longer fresh
        status, body = self.request('/notifications/preferences', 'PUT', patch)
        self.assertEqual((status, body['code']), (403, 'STEP_UP_REQUIRED'))
        self.assertEqual(self.centre.prefs, {})
        self.time -= 400
        status, body = self.request('/notifications/preferences?mode=demo', 'PUT', patch)
        self.assertEqual((status, body['code']), (400, 'VALIDATION_FAILED'), 'Demo never writes Live settings')
        status, body = self.request('/notifications/preferences', 'PUT', patch)
        self.assertEqual(status, 200)
        self.assertEqual((body['data']['preferences']['revision'], body['data']['preferences']['quietHours']['start']), (1, 1380))
        self.assertEqual(self.store.events[-1]['action'], 'control.settings')
        status, body = self.request('/notifications/preferences', 'PUT', {'events': {'founder.briefing_ready': {'sms': True}}})
        self.assertEqual((status, body['code']), (400, 'VALIDATION_FAILED'))
        self.centre.missing = True
        status, body = self.request('/notifications/preferences', 'PUT', patch)
        self.assertEqual((status, body['code'], body['blocker']), (409, 'POLICY_DISABLED', 'notifications_not_installed'))
        status, body = self.request('/notifications/preferences')
        self.assertEqual((status, body['data']['installed'], body['data']['preferences']['revision']), (200, False, 0))

    def test_notice_centre_test_notice_and_read(self):
        status, body = self.request('/notifications?mode=demo')
        self.assertEqual((status, body['dataState'], body['data']['notices'], body['data']['reason']), (200, 'not_applicable', [], 'demo_not_simulated'))
        status, body = self.request('/notifications/test', 'POST', {})
        self.assertEqual(status, 200)
        notice = body['data']['notice']
        self.assertEqual((notice['type'], notice['severity'], body['data']['unread'], body['data']['replayed']), ('founder.test_notice', 'info', 1, False))
        self.assertEqual((notice['channels']['email']['mode'], notice['channels']['push']['reason']), ('off', 'not_routed'), 'in-app only, never emailed or pushed')
        status, body = self.request('/notifications/test?mode=demo', 'POST', {})
        self.assertEqual((status, body['code']), (400, 'VALIDATION_FAILED'))
        status, body = self.request('/notifications?limit=5')
        self.assertEqual((status, [n['id'] for n in body['data']['notices']], body['data']['unread']), (200, [notice['id']], 1))
        status, body = self.request(f"/notifications/{notice['id']}/read", 'POST', {})
        self.assertEqual((status, body['data']['notice']['read'], body['data']['unread']), (200, True, 0))
        status, body = self.request(f'/notifications/{uuid.uuid4()}/read', 'POST', {})
        self.assertEqual((status, body['code']), (404, 'VALIDATION_FAILED'))
        status, body = self.request('/notifications/test', 'POST', {'email': 'someone@example.com'})
        self.assertEqual((status, body['code']), (400, 'VALIDATION_FAILED'))

    def test_report_routes_list_versions_and_carry_receipts(self):
        from rafii_control import founder_briefings
        receipt = str(uuid.uuid4())
        brief = founder_briefings.compose_brief('daily', [{'id': receipt, 'metricId': 'ai_cost_actual', 'label': 'AI cost yesterday (actual)', 'unit': 'usd_micro',
                                                          'value': 2_500_000, 'dataState': 'measured'}], now=DAYTIME, basis={'basis': 'metric_receipts', 'receipts': 1})
        saved = founder_briefings.save_report(self.fstore, USER, brief)
        status, body = self.request('/reports')
        self.assertEqual(status, 200)
        self.assertEqual([(r['id'], r['receiptIds']) for r in body['data']['reports']], [(saved['id'], [receipt])])
        self.assertNotIn('text', body['data']['reports'][0])
        status, body = self.request('/reports/' + saved['id'])
        self.assertEqual((status, body['receiptIds'], body['dataState']), (200, [receipt], 'measured'))
        self.assertIn('AI cost yesterday (actual): USD 2.50', body['data']['report']['text'])
        self.assertEqual(body['data']['report']['coverage']['basis'], 'metric_receipts')
        status, body = self.request('/reports?mode=demo')
        self.assertEqual((status, body['data']['reports'], body['data']['reason']), (200, [], 'demo_not_simulated'))
        status, body = self.request('/reports?kind=monthly')
        self.assertEqual((status, body['code']), (400, 'VALIDATION_FAILED'))
        status, body = self.request('/reports/' + str(uuid.uuid4()))
        self.assertEqual((status, body['code']), (404, 'VALIDATION_FAILED'))


class RegistrationTests(unittest.TestCase):
    def test_routes_capabilities_and_the_stage_are_registered_once(self):
        expected = {('GET', '/notifications/preferences'): ('control.read', {}), ('PUT', '/notifications/preferences'): ('control.settings', {'step_up': True}),
                    ('GET', '/notifications'): ('control.read', {}), ('POST', '/notifications/test'): ('control.read', {}),
                    ('POST', '/notifications/([0-9a-fA-F-]{36})/read'): ('control.read', {}), ('GET', '/reports'): ('control.read', {}),
                    ('GET', '/reports/([0-9a-fA-F-]{36})'): ('control.read', {})}
        found = {(route[0], route[1].pattern): (route[2], route[5]) for route in http.EXTENSION_ROUTES if (route[0], route[1].pattern) in expected}
        self.assertEqual(found, expected)
        before = (len(http.EXTENSION_ROUTES), len(founder_cron.STAGES))
        fn.register()
        self.assertEqual((len(http.EXTENSION_ROUTES), len(founder_cron.STAGES)), before, 'a second registration adds nothing')
        self.assertEqual(ControlApplication._capability('/notifications/preferences', 'PUT'), 'control.settings')
        self.assertEqual(ControlApplication._capability('/notifications/preferences', 'GET'), 'control.read')

    def test_customer_catalogue_stays_byte_identical(self):
        before = json.dumps(catalog.EVENTS, sort_keys=True)
        fn.register_events()
        self.assertEqual(json.dumps(catalog.EVENTS, sort_keys=True), before)
        for name in fn.NOTICE_EVENTS + (fn.DIGEST_EVENT,):
            self.assertNotIn(name, catalog.EVENTS)
            self.assertIn(name, catalog.EXTENSION_EVENTS)
            self.assertNotIn(name, catalog.public()['events'])
        self.assertEqual((catalog.spec(fn.DIGEST_EVENT)['audience'], catalog.spec(fn.DIGEST_EVENT)['sms']), ('actor', 'off'))
        self.assertNotIn(fn.TEST_EVENT, catalog.EXTENSION_EVENTS, 'the test notice never reaches the outbox')

    def test_memory_centre_covers_the_sql_surface(self):
        expected = {name for name in dir(fn.NoticeSQL) if not name.startswith('_') and callable(getattr(fn.NoticeSQL, name))}
        provided = {name for name in dir(MemoryCentre) if callable(getattr(MemoryCentre, name))}
        self.assertEqual(expected - provided, set())


if __name__ == '__main__':
    unittest.main()
