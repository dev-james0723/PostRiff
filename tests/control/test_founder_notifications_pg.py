"""Migration 067 and the founder centre on a disposable PostgreSQL (CONTRACTS §8.E).

Skipped without RAFII_CONTROL_TEST_DSN; scripts/rafii_control_pg.py applies every founder migration twice and sets it.
Proves: forced RLS with the environment policy and session-only grants; the NoticeSQL round trip as the restricted
session role; and a founder notice through the real consumer outbox (store.emit) planning in-app only by default and
nothing sendable when the gates are open but no transport exists — no provider, no network.
"""
import os
import time
import types
import unittest
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from rafii_control import founder_notifications as fn
from rafii_control.auth import CAPABILITIES
from rafii_control.founder_contact import validate_policy, destination_ref
from rafii_control.founder_cron import PostgresFounderStore
from rafii_control.store import PostgresStore, connection_factory


def ten_am_after(epoch):
    """The next 10:00 report-time-zone instant at or after `epoch` (after the digest hour, outside default quiet hours)."""
    zone = ZoneInfo(fn.TIME_ZONE)
    local = datetime.fromtimestamp(epoch, zone)
    target = local.replace(hour=10, minute=0, second=0, microsecond=0)
    if target <= local:
        target = datetime.combine(local.date() + timedelta(days=1), target.time(), tzinfo=zone)
    return target.timestamp()


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'), 'disposable control PostgreSQL DSN required')
class FounderNoticesMigrationTests(unittest.TestCase):
    def connect(self, role=None):
        con = psycopg.connect(os.environ['RAFII_CONTROL_TEST_DSN'], autocommit=True, prepare_threshold=None)
        if role:
            con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
        self.addCleanup(con.close)
        return con

    def setUp(self):
        self.dsn = os.environ['RAFII_CONTROL_TEST_DSN']
        owner = self.connect()
        if owner.execute("SELECT to_regclass('rafii_control.founder_notices') IS NULL OR to_regclass('rafii_control.founder_notification_preferences') IS NULL").fetchone()[0]:
            self.skipTest('migration 067 not applied by this harness')
        self.user = str(uuid.uuid4())
        owner.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.user,))
        owner.execute('INSERT INTO public.pr_profiles(user_id) VALUES(%s)', (self.user,))
        owner.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s)",
                      (self.user, sorted(CAPABILITIES)))

    def tearDown(self):
        with psycopg.connect(self.dsn, autocommit=True) as con:
            for sql in ('DELETE FROM rafii_control.founder_notices WHERE operator_id=%s', 'DELETE FROM rafii_control.founder_notification_preferences WHERE operator_id=%s',
                        'DELETE FROM rafii_control.founder_contact_policy WHERE operator_id=%s',
                        "DELETE FROM public.pr_notification_events WHERE scope_key='user:'||%s::text",
                        "UPDATE rafii_control.platform_operators SET status='revoked' WHERE user_id=%s"):
                con.execute(sql, (self.user,))

    def store(self, environment='local'):
        # The harness login is privileged, which connection_factory only accepts for 'local'; the store's own environment
        # (what RLS scopes by) is still `environment`.
        return PostgresStore(connection_factory(self.dsn, 'rafii_control_session', 'local'), connection_factory(self.dsn, 'rafii_control_reader', 'local'), environment)

    def row(self, **changes):
        base = {'id': str(uuid.uuid4()), 'operator_id': self.user, 'event_type': 'founder.incident_opened', 'severity': 'warning', 'subject_type': 'founder_incident',
                'subject_id': str(uuid.uuid4()), 'dedupe_key': 'k-' + uuid.uuid4().hex, 'title': 'warning incident: cost_anomaly (global)',
                'href': '/founder/operations?tab=incidents', 'channels': {'in_app': {'mode': 'immediate', 'state': 'delivered'}}, 'facts': {'detector': 'cost_anomaly'},
                'digest_state': 'pending', 'created_at': time.time()}
        base.update(changes)
        return base

    def test_tables_force_rls_with_the_environment_policy_and_session_only_grants(self):
        owner = self.connect()
        for table in ('founder_notices', 'founder_notification_preferences'):
            with self.subTest(table=table):
                flags = owner.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='rafii_control' AND relname=%s",
                                      (table,)).fetchone()
                self.assertEqual(tuple(flags), (True, True))
                self.assertEqual(owner.execute("SELECT count(*) FROM pg_policies WHERE schemaname='rafii_control' AND tablename=%s AND policyname='founder_environment_all'",
                                               (table,)).fetchone()[0], 1)
                for role in ('rafii_control_reader', 'anon', 'authenticated', 'service_role'):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        self.connect(role).execute(f'SELECT * FROM rafii_control.{table} LIMIT 1')
        session = self.connect('rafii_control_session')
        session.execute("SELECT set_config('rafii_control.environment','local',false)")
        notice = self.row()
        session.execute('INSERT INTO rafii_control.founder_notices(id,operator_id,environment,event_type,severity,subject_type,subject_id,dedupe_key,title,href,channels,facts,digest_state) '
                        "VALUES(%s,%s,'local',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (notice['id'], self.user, notice['event_type'], notice['severity'], notice['subject_type'], notice['subject_id'], notice['dedupe_key'], notice['title'],
                         notice['href'], Jsonb(notice['channels']), Jsonb(notice['facts']), notice['digest_state']))
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            session.execute("INSERT INTO rafii_control.founder_notification_preferences(operator_id,environment) VALUES(%s,'staging')", (self.user,))
        staging = self.connect('rafii_control_session')
        staging.execute("SELECT set_config('rafii_control.environment','staging',false)")
        self.assertEqual(staging.execute('SELECT count(*) FROM rafii_control.founder_notices WHERE operator_id=%s', (self.user,)).fetchone()[0], 0)
        for changes, error in (({'event_type': 'founder.refund_issued'}, psycopg.errors.CheckViolation), ({'href': 'https://evil.example/x'}, psycopg.errors.CheckViolation),
                               ({'subject_id': 'drop table; --'}, psycopg.errors.CheckViolation), ({'operator_id': str(uuid.uuid4())}, psycopg.errors.ForeignKeyViolation)):
            with self.subTest(changes=changes), self.assertRaises(error):
                bad = self.row(**changes)
                session.execute('INSERT INTO rafii_control.founder_notices(id,operator_id,environment,event_type,severity,subject_type,subject_id,dedupe_key,title,href) '
                                "VALUES(%s,%s,'local',%s,%s,%s,%s,%s,%s,%s)",
                                (bad['id'], bad['operator_id'], bad['event_type'], bad['severity'], bad['subject_type'], bad['subject_id'], bad['dedupe_key'], bad['title'], bad['href']))

    def test_notice_sql_round_trip_as_the_restricted_session_role(self):
        centre = fn.NoticeSQL(self.store())
        self.assertIsNone(centre.preferences(self.user))
        prefs = fn.validate_preferences({'events': {'founder.briefing_ready': {'push': False}}, 'digest': {'hour': 7}}, None)
        first = centre.save_preferences(self.user, prefs, time.time())
        second = centre.save_preferences(self.user, {**prefs, 'digest_hour': 8}, time.time())
        self.assertEqual((first['revision'], second['revision'], second['digest_hour'], second['events']['founder.briefing_ready']), (1, 2, 8, {'email': True, 'push': False}))
        self.assertEqual(fn.merge_preferences(centre.preferences(self.user))['digest_hour'], 8)
        now = time.time()
        old = self.row(created_at=now - fn.RETENTION_SECONDS - 60, digest_state='none')
        stored, created = centre.insert_notice(self.row(created_at=now))
        replay, again = centre.insert_notice({**self.row(created_at=now), 'dedupe_key': stored['dedupe_key']})
        self.assertEqual((created, again, replay['id']), (True, False, stored['id']))
        centre.insert_notice(old)
        self.assertEqual(centre.unread(self.user), 2)
        self.assertEqual([r['id'] for r in centre.pending_digest(self.user)], [stored['id']])
        digest, _ = centre.insert_notice(self.row(event_type=fn.DIGEST_EVENT, severity='info', subject_type='founder_digest', subject_id='2026-10-01',
                                                  dedupe_key='founder.digest_ready:2026-10-01', digest_state='none', created_at=now))
        self.assertEqual(centre.include_in_digest(self.user, [stored['id']], digest['id']), 1)
        self.assertEqual(centre.pending_digest(self.user), [])
        self.assertEqual(centre.notice_by_dedupe(self.user, stored['dedupe_key'])['digest_id'], digest['id'])
        read = centre.mark_read(self.user, stored['id'], now)
        self.assertEqual((read['read_at'] is not None, centre.unread(self.user)), (True, 2))
        self.assertIsNone(centre.mark_read(str(uuid.uuid4()), stored['id'], now), 'another operator cannot read this notice')
        self.assertGreaterEqual(centre.purge(now - fn.RETENTION_SECONDS), 1)
        self.assertEqual({r['id'] for r in centre.notices(self.user)}, {stored['id'], digest['id']})
        self.assertEqual(fn.NoticeSQL(self.store('staging')).notices(self.user), [], 'another environment sees nothing')

    def test_founder_notice_through_the_real_outbox_plans_nothing_sendable(self):
        from postriff_phase2.notifications.service import NotificationService

        class Outbox(NotificationService):
            def enabled(self):
                return True   # the consumer flag; the transports stay unconfigured, so nothing can be sent

        outbox = Outbox(types.SimpleNamespace(mailer=None, public_base_url='https://rafii.invalid', phone=None, oauth=None), {})
        service = types.SimpleNamespace(connection_factory=lambda: psycopg.connect(self.dsn), notifications=outbox)
        fstore = PostgresFounderStore(self.store())
        now = time.time()
        subject = {'id': str(uuid.uuid4()), 'detector': 'publish_failure_rate', 'scope': 'global', 'severity': 'critical', 'state': 'open', 'version': 1}
        fn.notifier(service, [self.user], now, fstore, {})('founder.incident_opened', subject)
        owner = self.connect()

        def deliveries(version):
            return sorted(owner.execute('SELECT d.channel,d.status FROM public.pr_notification_deliveries d JOIN public.pr_notification_events e ON e.id=d.event_id '
                                        'WHERE e.dedupe_key=%s AND d.user_id=%s', (f"founder.incident_opened:{subject['id']}:{version}", self.user)).fetchall())
        event = owner.execute("SELECT workspace_id,scope_key,severity,category FROM public.pr_notification_events WHERE dedupe_key=%s",
                              (f"founder.incident_opened:{subject['id']}:1",)).fetchone()
        self.assertEqual(tuple(event), (None, 'user:' + self.user, 'critical', 'founder'))
        self.assertEqual(deliveries(1), [('in_app', 'delivered')], 'the default policy plans the in-app row only')
        policy = validate_policy({'liveDeliveryEnabled': True, 'channels': ['email', 'push'], 'destinationRef': destination_ref(self.user)}, None, self.user)
        fstore.save_policy(self.user, policy, now)
        fn.notifier(service, [self.user], now, fstore, dict.fromkeys(fn.FLAGS.values(), '1'))('founder.incident_opened', {**subject, 'version': 2})
        self.assertEqual(deliveries(2), [('email', 'suppressed'), ('in_app', 'delivered'), ('push', 'suppressed')], 'gates open, but no transport: nothing is sendable')
        centre = fn.NoticeSQL(fstore.store)
        self.assertEqual([r['severity'] for r in centre.notices(self.user)], ['critical', 'critical'])
        warning = {**subject, 'id': str(uuid.uuid4()), 'severity': 'warning'}
        fn.notifier(service, [self.user], now, fstore, {})('founder.incident_opened', warning)
        at = ten_am_after(now)
        result = fn.digest_stage(fstore, service, {}, at)
        self.assertEqual((result['status'], result['operators'][self.user]), ('ok', 'in_app'))
        local_date = datetime.fromtimestamp(at, ZoneInfo(fn.TIME_ZONE)).date().isoformat()
        digest = centre.notice_by_dedupe(self.user, f'{fn.DIGEST_EVENT}:{local_date}')
        self.assertEqual(digest['facts']['events'], {'founder.incident_opened': 1})
        self.assertEqual(owner.execute("SELECT count(*) FROM public.pr_notification_events WHERE event_type=%s AND scope_key=%s", (fn.DIGEST_EVENT, 'user:' + self.user)).fetchone()[0], 0,
                         'without the email gates the digest stays in the founder centre')


if __name__ == '__main__':
    unittest.main()
