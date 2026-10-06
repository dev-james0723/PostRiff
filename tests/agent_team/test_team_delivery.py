"""Synthetic transactional outbox tests. No provider, model, push or phone calls."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
import uuid

from agent_team.periods import period
from agent_team.reports import report
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_team_delivery import (
    EVENT_TYPE, TeamDeliveryService, TeamDeliveryStore, browser_voice_controls,
    browser_voice_payload, delivery_plan, report_href, with_stored_audio,
)
from postriff_phase2.notifications import catalog, store as notifications_store
from postriff_phase2.notifications.email_render import safe_app_path

USER = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'


def document(kind='half_day', version=1, summary=None):
    p = period('2026-10-05', kind)
    doc = report(p, [], p.cutoff + timedelta(minutes=1))
    doc.update(version=version, fingerprint=str(version % 10) * 64)
    if summary is not None:
        doc['summary'] = summary
    return doc


class FakeDatabase:
    """Small SQL model with commit/rollback, uniqueness and exact recipient checks."""
    def __init__(self):
        self.data = {'reports': {}, 'effects': {}, 'events': {}, 'deliveries': {}}
        self.history = []
        self.commits = 0
        self.rollbacks = 0
        self.profile = True
        self.subscribed = True
        self.prefs = []

    def seed(self, doc):
        self.data['reports'][(doc['period']['key'], doc['fingerprint'])] = copy.deepcopy(doc)

    def __call__(self):
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, db):
        self.db = db
        self.data = copy.deepcopy(db.data)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, kind, _value, _trace):
        if kind or not self.committed:
            self.db.rollbacks += 1

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.db.data = copy.deepcopy(self.data)
        self.db.commits += 1
        self.committed = True


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, sql, values=()):
        values = tuple(values)
        self.connection.db.history.append((sql, values))
        data = self.connection.data
        self.result = []
        if sql.startswith('SELECT pg_advisory_xact_lock'):
            self.result = [(None,)]
        elif sql.startswith('SELECT document FROM public.pr_agent_team_reports'):
            doc = data['reports'].get(values)
            self.result = [(doc,)] if doc else []
        elif sql.startswith('SELECT report_key,kind,state,external_id,failure_class'):
            effect = data['effects'].get(values[0])
            self.result = [tuple(effect[k] for k in ('report_key', 'kind', 'state', 'external_id', 'failure_class'))] if effect else []
        elif sql.startswith('INSERT INTO public.pr_agent_team_effects'):
            data['effects'].setdefault(values[0], {'report_key': values[1], 'kind': values[2], 'state': 'reserved',
                                                  'external_id': None, 'failure_class': None})
        elif sql.startswith('UPDATE public.pr_agent_team_effects'):
            data['effects'][values[3]].update(state=values[0], external_id=values[1], failure_class=values[2])
        elif sql.startswith('SELECT id::text,event_type,entity_id,workspace_id::text,payload'):
            event = data['events'].get(values)
            self.result = [(event['id'], event['type'], event['entity'], event['workspace'], event['payload'])] if event else []
        elif sql.startswith('SELECT id::text,channel,mode,status,provider,failure_class'):
            self.result = [tuple(d[k] for k in ('id', 'channel', 'mode', 'status', 'provider', 'failure_class', 'next_at', 'user', 'workspace'))
                           for d in data['deliveries'].values() if d['event'] == values[0]]
        elif sql.startswith('INSERT INTO public.pr_notification_events'):
            assert values[0] is None, 'Workspace fanout is forbidden'
            assert values[1] == 'user:' + USER, 'Exact configured person scope required'
            key = (values[1], values[9])
            if key not in data['events']:
                identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, '|'.join(key)))
                data['events'][key] = {'id': identifier, 'type': values[2], 'entity': values[5], 'workspace': values[0],
                                       'payload': json.loads(values[8]), 'expires': values[13], 'grouping': values[10]}
                self.result = [(identifier,)]
        elif sql.startswith('SELECT coalesce(time_zone'):
            assert values == (USER,), 'No other profile is read'
            self.result = [('America/Indiana/Indianapolis', 'zh-Hant')] if self.connection.db.profile else []
        elif sql.startswith('SELECT scope_key, category, in_app'):
            assert values == (USER,)
            self.result = self.connection.db.prefs
        elif sql.startswith('SELECT 1 FROM public.pr_push_subscriptions'):
            assert values == (USER,)
            self.result = [(1,)] if self.connection.db.subscribed else []
        elif sql.startswith('SELECT channel, count(*)'):
            assert values[0] == USER
        elif sql.startswith('INSERT INTO public.pr_notification_deliveries'):
            assert values[1] is None and values[2] == USER
            key = (values[0], values[2], values[3])
            if key not in data['deliveries']:
                identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, values[7]))
                data['deliveries'][key] = {'id': identifier, 'event': values[0], 'workspace': values[1], 'user': values[2],
                                          'channel': values[3], 'mode': values[4], 'status': values[5], 'next_at': values[6],
                                          'provider': None, 'failure_class': values[9]}
                self.result = [(identifier,)]
        else:
            raise AssertionError('Unexpected SQL: ' + sql)

    def fetchone(self):
        return self.result.pop(0) if self.result else None

    def fetchall(self):
        result, self.result = self.result, []
        return result


class FakeNotifications:
    def __init__(self, clock):
        self.clock = clock
        self.enabled = True
        self.calls = []
        self.fail_after_emit = False

    def emit(self, cur, **event):
        self.calls.append(event)
        if not self.enabled:
            return {'eventId': None, 'created': False, 'deliveries': [], 'disabled': True}
        result = notifications_store.emit(cur, **event, now=self.clock(), email_available=False, push_enabled=True)
        if self.fail_after_emit:
            raise RuntimeError('synthetic transaction failure')
        return result


class TeamDeliveryTests(unittest.TestCase):
    def test_stored_audio_reconciles_availability_without_promoting_delivery_or_view(self):
        doc = document('whole_day')
        receipt = {'deliveryState': 'provider_accepted', 'notificationAcknowledged': False,
                   'reportViewState': 'unverified', 'audioState': 'unavailable'}
        asset = {'reportKey': doc['period']['key'], 'fingerprint': doc['fingerprint'],
                 'version': doc['version'], 'audioState': 'ready', 'sha256': 'a' * 64,
                 'summaryHash': hashlib.sha256(doc['summary'].encode('utf-8')).hexdigest()}
        self.assertEqual(with_stored_audio(receipt, doc, None), receipt)
        result = with_stored_audio(receipt, doc, asset)
        self.assertEqual(result['audioState'], 'ready')
        self.assertEqual(result['audioPlaybackState'], 'unverified')
        self.assertEqual(result['deliveryState'], 'provider_accepted')
        self.assertEqual(result['reportViewState'], 'unverified')
        self.assertFalse(result['notificationAcknowledged'])
        self.assertEqual(receipt['audioState'], 'unavailable')
        for changed in ({'reportKey': 'another'}, {'fingerprint': 'b' * 64},
                        {'version': 2}, {'summaryHash': 'c' * 64}, {'sha256': 'invalid'}):
            with self.subTest(changed=changed), self.assertRaises(AlphaError):
                with_stored_audio(receipt, doc, {**asset, **changed})

    def setup_delivery(self, doc=None, now=None):
        doc = doc or document()
        db = FakeDatabase()
        db.seed(doc)
        now = now or datetime.fromisoformat(doc['generatedAt']).timestamp()
        notices = FakeNotifications(lambda: now)
        store = TeamDeliveryStore(db, USER, clock=lambda: now)
        return doc, db, notices, store

    def test_event_is_narrow_catalog_extension(self):
        self.assertNotIn(EVENT_TYPE, catalog.EVENTS)
        spec = catalog.spec(EVENT_TYPE)
        self.assertEqual((spec['audience'], spec['email'], spec['sms'], spec['push']), ('actor', 'off', 'off', 'immediate'))
        self.assertFalse(spec.get('transactional', False))

    def test_half_day_queues_person_only_and_preserves_auth_href(self):
        doc, db, notices, store = self.setup_delivery()
        result = store.queue(doc, notices)
        event = notices.calls[0]
        self.assertIsNone(event['workspace_id'])
        self.assertEqual(event['user_id'], USER)
        self.assertEqual(event['actor'], USER)
        self.assertEqual(event['channel_filter'], ('in_app', 'push'))
        self.assertEqual(result['state'], 'queued')
        self.assertEqual(result['deliveryState'], 'queued')
        self.assertEqual({r['channel']: r['status'] for r in result['deliveries']}, {'in_app': 'delivered', 'push': 'pending'})
        self.assertEqual(result['effectState'], 'submitted')
        self.assertEqual(result['reportViewState'], 'unverified')
        self.assertFalse(result['notificationAcknowledged'])
        self.assertNotIn(doc['summary'], json.dumps(event['payload'], ensure_ascii=False))
        self.assertEqual(safe_app_path(result['href']), result['href'])
        self.assertNotIn('redacted', next(iter(db.data['events'].values()))['payload']['href'])
        self.assertEqual(db.commits, 1)

    def test_whole_day_at_one_is_in_app_only_without_push_receipt(self):
        doc, db, notices, store = self.setup_delivery(document('whole_day'))
        result = store.queue(doc, notices)
        self.assertEqual(notices.calls[0]['channel_filter'], ('in_app',))
        self.assertEqual(result['state'], 'persisted')
        self.assertEqual(result['deliveryState'], 'in_app_available')
        self.assertEqual([r['channel'] for r in result['deliveries']], ['in_app'])
        self.assertTrue(all(d['channel'] == 'in_app' for d in db.data['deliveries'].values()))
        self.assertEqual(result['audioState'], 'unavailable')

    def test_late_half_day_supplement_never_creates_night_push(self):
        doc = document(version=2)
        night = period('2026-10-05', 'whole_day').cutoff.timestamp() + 60
        doc, _, notices, store = self.setup_delivery(doc, night)
        store.queue(doc, notices)
        self.assertEqual(notices.calls[0]['channel_filter'], ('in_app',))

    def test_same_period_version_replay_does_not_emit_again(self):
        doc, db, notices, store = self.setup_delivery()
        first = store.queue(doc, notices)
        second = store.queue(doc, notices)
        self.assertEqual(first['eventId'], second['eventId'])
        self.assertFalse(second['created'])
        self.assertEqual(len(notices.calls), 1)
        self.assertEqual((len(db.data['events']), len(db.data['effects']), len(db.data['deliveries'])), (1, 1, 2))

    def test_supplement_has_distinct_period_version_dedupe_and_push_topic(self):
        first, db, notices, store = self.setup_delivery()
        result1 = store.queue(first, notices)
        second = document(version=2, summary=first['summary'] + ' Late evidence is recorded.')
        db.seed(second)
        result2 = store.queue(second, notices)
        self.assertNotEqual(result1['eventId'], result2['eventId'])
        self.assertNotEqual(notices.calls[0]['dedupe_key'], notices.calls[1]['dedupe_key'])
        self.assertNotEqual(notices.calls[0]['grouping_key'][:32], notices.calls[1]['grouping_key'][:32])
        self.assertEqual(len(db.data['effects']), 2)

    def test_transaction_failure_rolls_back_notice_and_effect_together(self):
        doc, db, notices, store = self.setup_delivery()
        notices.fail_after_emit = True
        with self.assertRaises(RuntimeError):
            store.queue(doc, notices)
        self.assertEqual(db.data['events'], {})
        self.assertEqual(db.data['effects'], {})
        self.assertEqual(db.data['deliveries'], {})
        self.assertEqual(len(db.data['reports']), 1)
        self.assertEqual((db.commits, db.rollbacks), (0, 1))

    def test_disabled_queue_can_retry_same_transactional_effect_after_enabled(self):
        doc, db, notices, store = self.setup_delivery()
        notices.enabled = False
        disabled = store.queue(doc, notices)
        self.assertEqual((disabled['state'], disabled['effectState']), ('persisted', 'disabled'))
        self.assertEqual(db.data['events'], {})
        notices.enabled = True
        queued = store.queue(doc, notices)
        self.assertEqual(queued['state'], 'queued')
        self.assertEqual(len(db.data['effects']), 1)

    def test_submitted_missing_receipt_is_reconciliation_not_reemit(self):
        doc, db, notices, store = self.setup_delivery()
        queued = store.queue(doc, notices)
        db.data['events'].clear()
        result = store.queue(doc, notices)
        self.assertEqual(result['deliveryState'], 'reconciliation_required')
        self.assertEqual(result['effectState'], 'unknown')
        self.assertEqual(len(notices.calls), 1)
        self.assertEqual(db.data['effects'][queued['effectKey']]['external_id'], queued['eventId'])

    def test_receipt_reconciles_provider_acceptance_without_claiming_report_view(self):
        doc, db, notices, store = self.setup_delivery()
        store.queue(doc, notices)
        push = next(d for d in db.data['deliveries'].values() if d['channel'] == 'push')
        push.update(status='sent', provider='webpush')
        accepted = store.receipt(doc)
        self.assertEqual((accepted['state'], accepted['deliveryState']), ('persisted', 'provider_accepted'))
        self.assertEqual(accepted['effectState'], 'submitted')
        self.assertEqual(accepted['reportViewState'], 'unverified')
        push = next(d for d in db.data['deliveries'].values() if d['channel'] == 'push')
        push.update(status='sent', provider='recording')
        recorded = store.receipt(doc)
        self.assertEqual(recorded['deliveryState'], 'in_app_available')
        self.assertEqual(next(r for r in recorded['deliveries'] if r['channel'] == 'push')['proof'], 'simulation')
        in_app = next(d for d in db.data['deliveries'].values() if d['channel'] == 'in_app')
        in_app['status'] = 'read'
        read = store.receipt(doc)
        self.assertTrue(read['notificationAcknowledged'])
        self.assertEqual(read['effectState'], 'confirmed')
        self.assertEqual(read['reportViewState'], 'unverified')
        self.assertEqual(len(notices.calls), 1)

    def test_preferences_are_preserved_with_no_email_sms_or_phone_fallback(self):
        doc, db, notices, store = self.setup_delivery()
        db.prefs = [('*', 'automation', False, 'immediate', 'off', 'daily', None, None,
                     'America/Indiana/Indianapolis', None, False, 'important_only', True)]
        result = store.queue(doc, notices)
        self.assertEqual(result['deliveryState'], 'suppressed')
        self.assertEqual([r['channel'] for r in result['deliveries']], ['in_app'])
        self.assertEqual(result['deliveries'][0]['status'], 'suppressed')

    def test_no_subscription_is_explicit_not_push_delivery(self):
        doc, db, notices, store = self.setup_delivery()
        db.subscribed = False
        result = store.queue(doc, notices)
        push = next(r for r in result['deliveries'] if r['channel'] == 'push')
        self.assertEqual((push['status'], push['proof']), ('suppressed', 'none'))
        self.assertEqual(result['deliveryState'], 'in_app_available')

    def test_existing_quiet_hours_defer_push_with_same_day_expiry(self):
        doc, db, notices, store = self.setup_delivery()
        db.prefs = [('*', 'automation', True, None, 'immediate', None, 16 * 60, 18 * 60,
                     'America/Indiana/Indianapolis', None, False, None, None)]
        result = store.queue(doc, notices)
        push = next(r for r in result['deliveries'] if r['channel'] == 'push')
        p = period('2026-10-05', 'half_day')
        self.assertEqual(push['status'], 'pending')
        self.assertEqual(push['nextAttemptAt'], (p.cutoff + timedelta(hours=1)).timestamp())
        self.assertEqual(notices.calls[0]['expires_at'], (p.cutoff + timedelta(hours=5)).timestamp())

    def test_existing_event_with_missing_effect_is_reconciled_without_emitting(self):
        doc, db, notices, store = self.setup_delivery()
        queued = store.queue(doc, notices)
        db.data['effects'].clear()
        result = store.queue(doc, notices)
        self.assertEqual(result['eventId'], queued['eventId'])
        self.assertEqual(result['effectState'], 'submitted')
        self.assertEqual(len(notices.calls), 1)
        self.assertEqual(len(db.data['effects']), 1)

    def test_mutated_or_missing_manifest_never_queues(self):
        doc, db, notices, store = self.setup_delivery()
        mutated = {**doc, 'summary': 'Unstored assertion.'}
        with self.assertRaises(AlphaError):
            store.queue(mutated, notices)
        db.data['reports'].clear()
        with self.assertRaises(AlphaError):
            store.queue(doc, notices)
        self.assertEqual(notices.calls, [])
        self.assertEqual(db.data['effects'], {})

    def test_receipt_rejects_any_other_recipient_or_workspace(self):
        for field, value in (('user', OTHER), ('workspace', OTHER)):
            doc, db, notices, store = self.setup_delivery()
            store.queue(doc, notices)
            next(iter(db.data['deliveries'].values()))[field] = value
            with self.assertRaises(AlphaError):
                store.receipt(doc)
            self.assertEqual(len(notices.calls), 1)

    def test_facade_uses_configured_principal_and_unbound_identity_fails_closed(self):
        doc, db, notices, _store = self.setup_delivery()
        service = SimpleNamespace(connection_factory=db, notifications=notices, clock=notices.clock,
                                  james_daily_call=SimpleNamespace(cfg=SimpleNamespace(user_id=USER, workspace_id=OTHER)))
        TeamDeliveryService(service).queue(doc)
        self.assertEqual(notices.calls[0]['user_id'], USER)
        self.assertIsNone(notices.calls[0]['workspace_id'])
        service.james_daily_call.cfg.user_id = None
        with self.assertRaises(AlphaError):
            TeamDeliveryService(service)

    def test_preview_future_and_bad_cutoff_are_rejected_before_database(self):
        doc, db, notices, store = self.setup_delivery()
        for bad in ({**doc, 'executionState': 'preview'}, {**doc, 'version': True},
                    {**doc, 'period': {**doc['period'], 'cutoff': '2026-10-05T22:00:00+00:00'}},
                    {**doc, 'generatedAt': (aware_time(doc['generatedAt']) + timedelta(minutes=2)).isoformat()}):
            with self.assertRaises(AlphaError):
                store.queue(bad, notices)
        self.assertEqual(db.history, [])
        self.assertEqual(notices.calls, [])

    def test_voice_payload_and_controls_use_exact_same_summary_on_demand(self):
        doc = document('whole_day', summary='同一份報告摘要。 </script><img src=x onerror=alert(1)>')
        payload = browser_voice_payload(doc)
        self.assertEqual(payload['text'], doc['summary'])
        self.assertEqual(payload['audioState'], 'unavailable')
        self.assertFalse(payload['autoplay'])
        self.assertFalse(payload['audioFileGenerated'])
        self.assertTrue(payload['requiresUserGesture'])
        controls = browser_voice_controls(doc)
        self.assertNotIn('</script><img', controls)
        self.assertIn('\\u003c/script', controls)
        self.assertIn('play.addEventListener("click"', controls)
        self.assertIn('SpeechSynthesisUtterance', controls)
        self.assertNotIn('<audio', controls)
        self.assertNotIn('fetch(', controls)
        self.assertEqual(report_href(doc), delivery_plan(doc, aware_time(doc['generatedAt']))['href'])


def aware_time(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


if __name__ == '__main__':
    unittest.main()
