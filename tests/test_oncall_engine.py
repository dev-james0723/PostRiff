"""H-07 on-call engine (src/rafii_control/oncall/), offline: every line of the owner's reply-15 policy on a simulated
clock, with the in-memory store and fake providers.

What this proves: the engine's decisions (who is notified, on which channel, when, and what is recorded). What it does
not prove: that anything reaches a person. Fake providers accept whatever they are given; real delivery is a
Production test with real people (docs/ops/H07-EVIDENCE.md). No database, network, clock or credential: the
acknowledgement secret is generated at run time.
"""
import copy
import json
import secrets
import unittest
import uuid
from datetime import datetime, timezone

from rafii_control.oncall import ENV_AUTO_HOLD, ENV_ENABLED, autohold, readiness
from rafii_control.oncall import policy as P
from rafii_control.oncall.engine import Engine, heartbeat_alerts, stage
from rafii_control.oncall.providers import FakeProvider, ack_token, verify_ack_token
from rafii_control.oncall.store import MemoryStore

POLICY = P.load()
SATURDAY_3AM = datetime(2026, 10, 24, 7, 0, tzinfo=timezone.utc).timestamp()     # 03:00 EDT, a weekend night
TUESDAY_10AM = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc).timestamp()    # 10:00 EDT, duty hours
TUESDAY_2AM = datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc).timestamp()      # 02:00 EDT
TUESDAY_9AM = datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc).timestamp()     # 09:00 EDT


def roster(**changes):
    people = {name: {'push': 'ref-%s-push' % name, 'email': 'ref-%s-mail' % name, 'phone': 'ref-%s-phone' % name}
              for name in ('ana', 'ben')}
    raw = {'shifts': [{'days': 'daily', 'start': '00:00', 'end': '24:00', 'primary': 'ana', 'backup': 'ben'}], 'people': people}
    raw.update(changes)
    return raw


def alert(rule='CROSS_TENANT_PROBE_FAILED', severity='page', scope=None, **evidence):
    found = {'id': rule, 'class': rule.split('_')[0], 'severity': severity, 'message': 'synthetic %s' % rule, 'evidence': evidence}
    if scope:
        found['scope'] = scope
    return found


class Rig:
    """An engine on the in-memory store with fake providers and deterministic ids."""
    def __init__(self, policy=None, roster_=None, **kw):
        self.store = MemoryStore()
        self.fakes = {c: FakeProvider(c) for c in P.CHANNELS}
        counter = iter(range(1, 100000))
        self.engine = Engine(policy or POLICY, self.store, self.fakes, roster=roster_ or roster(),
                             ids=lambda: str(uuid.UUID(int=next(counter))), **kw)

    def sent(self, kind='page'):
        """[(channel, person)] in the order sent (all channels), for one kind of notification."""
        out = []
        for channel, fake in self.fakes.items():
            out += [(m, channel) for m in fake.sent if m.kind == kind]
        return sorted([(channel, m.person) for m, channel in out])

    def run(self, alerts, start, seconds, step=60):
        """Evaluate every `step` seconds from `start` for `seconds`; returns {offset: [(channel, person), ...]} of pages."""
        timeline = {}
        for offset in range(0, seconds + 1, step):
            before = {c: len(f.sent) for c, f in self.fakes.items()}
            self.engine.process(alerts, start + offset)
            new = sorted((c, m.person) for c, f in self.fakes.items() for m in f.sent[before[c]:] if m.kind == 'page')
            if new:
                timeline[offset] = new
        return timeline

    def incident(self, rule='CROSS_TENANT_PROBE_FAILED'):
        return [i for i in self.store.incidents() if i['rule'] == rule][-1]


class P0Escalation(unittest.TestCase):
    def test_p0_at_night_push_and_email_at_once_call_at_5_backup_at_10(self):
        rig = Rig()
        timeline = rig.run([alert()], SATURDAY_3AM, 660, step=30)
        self.assertEqual(timeline, {0: [('email', 'ana'), ('push', 'ana')], 300: [('phone', 'ana')],
                                    600: [('email', 'ben'), ('phone', 'ben'), ('push', 'ben')]})

    def test_the_boundaries_are_exact(self):
        rig = Rig()
        rig.engine.process([alert()], SATURDAY_3AM)
        rig.engine.process([alert()], SATURDAY_3AM + 299.9)
        self.assertEqual(rig.fakes['phone'].sent, [])
        rig.engine.process([alert()], SATURDAY_3AM + 300)
        self.assertEqual([m.person for m in rig.fakes['phone'].sent], ['ana'])
        rig.engine.process([alert()], SATURDAY_3AM + 599.9)
        self.assertEqual([m.person for m in rig.fakes['phone'].sent], ['ana'])
        rig.engine.process([alert()], SATURDAY_3AM + 600)
        self.assertEqual([m.person for m in rig.fakes['phone'].sent], ['ana', 'ben'])

    def test_an_acknowledgement_stops_the_chain_and_is_recorded(self):
        rig = Rig()
        rig.engine.process([alert()], SATURDAY_3AM)
        incident = rig.incident()
        result = rig.engine.acknowledge(incident['id'], 'ana', 'push', SATURDAY_3AM + 120)
        self.assertTrue(result['ok'])
        rig.run([alert()], SATURDAY_3AM + 180, 1200)
        self.assertEqual(rig.fakes['phone'].sent, [])
        self.assertEqual(rig.sent('record'), [('email', 'ana')])
        kinds = [e['kind'] for e in rig.store.events(incident['id'])]
        self.assertIn('acknowledged', kinds)
        event = [e for e in rig.store.events(incident['id']) if e['kind'] == 'acknowledged'][0]
        self.assertEqual((event['actor'], event['detail']['channel'], event['detail']['secondsToAcknowledge']), ('ana', 'push', 120.0))

    def test_acknowledgement_is_refused_for_an_unknown_person_a_stale_version_or_a_bad_channel(self):
        rig = Rig()
        rig.engine.process([alert()], SATURDAY_3AM)
        incident = rig.incident()
        self.assertEqual(rig.engine.acknowledge(incident['id'], 'mallory', 'push', SATURDAY_3AM + 1)['reason'], 'unknown_person')
        self.assertEqual(rig.engine.acknowledge(incident['id'], 'ana', 'sms', SATURDAY_3AM + 1)['reason'], 'bad_channel')
        self.assertEqual(rig.engine.acknowledge(incident['id'], 'ana', 'push', SATURDAY_3AM + 1, version=99)['reason'], 'stale_version')
        self.assertEqual(rig.engine.acknowledge('missing', 'ana', 'push', SATURDAY_3AM + 1)['reason'], 'not_found')
        self.assertEqual(rig.incident()['state'], 'open')
        self.assertEqual(sum(1 for e in rig.store.events() if e['kind'] == 'ack_refused'), 2)

    def test_a_signed_link_acknowledges_and_a_forged_or_expired_one_does_not(self):
        secret = secrets.token_bytes(32)
        rig = Rig(ack_secret=secret, ack_base='https://rafii.example.invalid/ack')
        rig.engine.process([alert()], SATURDAY_3AM)
        incident = rig.incident()
        push = rig.fakes['push'].sent[0]
        self.assertTrue(push.ack_url.startswith('https://rafii.example.invalid/ack?t='))
        token = push.ack_url.split('?t=', 1)[1]
        self.assertEqual(verify_ack_token(secret, token, SATURDAY_3AM), (incident['id'], 'ana'))
        self.assertIsNone(verify_ack_token(secrets.token_bytes(32), token, SATURDAY_3AM))
        self.assertIsNone(verify_ack_token(secret, token, SATURDAY_3AM + 86400 * 2))
        self.assertIsNone(verify_ack_token(secret, token[:-1] + ('0' if token[-1] != '0' else '1'), SATURDAY_3AM))
        self.assertEqual(rig.engine.acknowledge_token('garbage', SATURDAY_3AM, 'push')['reason'], 'bad_token')
        self.assertTrue(rig.engine.acknowledge_token(token, SATURDAY_3AM + 60, 'push')['ok'])
        self.assertEqual(rig.incident()['acknowledgedBy'], 'ana')
        self.assertIsNone(rig.fakes['phone'].sent[0].ack_url if rig.fakes['phone'].sent else None)
        with self.assertRaises(ValueError):
            ack_token(b'short', incident['id'], 'ana', SATURDAY_3AM)

    def test_unacknowledged_p0_runs_again_every_15_minutes_three_rounds_then_stops(self):
        rig = Rig()
        timeline = rig.run([alert()], SATURDAY_3AM, 3000, step=60)
        self.assertEqual(sorted(timeline), [0, 300, 600, 900, 1200, 1500, 1800, 2100, 2400])
        self.assertEqual(len(rig.fakes['phone'].sent), 6)

    def test_the_person_of_a_step_is_fixed_when_it_fires(self):
        handover = roster(shifts=[{'days': 'daily', 'start': '00:00', 'end': '03:03', 'primary': 'ana', 'backup': 'ben'},
                                  {'days': 'daily', 'start': '03:03', 'end': '24:00', 'primary': 'ben', 'backup': 'ana'}])
        rig = Rig(roster_=handover)
        rig.run([alert()], SATURDAY_3AM, 600, step=60)
        self.assertEqual([m.person for m in rig.fakes['push'].sent], ['ana', 'ana'])   # step 0 to ana; step 2: the backup is ana now
        self.assertEqual([m.person for m in rig.fakes['phone'].sent], ['ben', 'ana'])  # step 1 at 03:05: the primary is ben


class P1AndP2(unittest.TestCase):
    def test_p1_in_duty_hours_push_and_email_then_backup_after_15_minutes(self):
        rig = Rig()
        timeline = rig.run([alert('RATE_429')], TUESDAY_10AM, 960)
        self.assertEqual(timeline, {0: [('email', 'ana'), ('push', 'ana')], 900: [('email', 'ben'), ('push', 'ben')]})
        self.assertEqual(rig.fakes['phone'].sent, [])

    def test_p1_at_night_email_at_once_push_at_nine_backup_at_quarter_past(self):
        rig = Rig()
        timeline = rig.run([alert('RATE_429')], TUESDAY_2AM, int(TUESDAY_9AM - TUESDAY_2AM) + 960)
        start = int(TUESDAY_9AM - TUESDAY_2AM)
        self.assertEqual(timeline, {0: [('email', 'ana')], start: [('push', 'ana')], start + 900: [('email', 'ben'), ('push', 'ben')]})
        self.assertEqual(len(rig.fakes['email'].to('ana', 'page')), 1, 'the night e-mail is not sent again at nine')

    def test_p1_counts_only_duty_minutes_across_the_spring_forward_night(self):
        policy = P.load()
        rig = Rig(policy)
        late = datetime(2026, 3, 8, 3, 50, tzinfo=timezone.utc).timestamp()    # Sat 22:50 EST, ten duty minutes left
        nine = datetime(2026, 3, 8, 13, 0, tzinfo=timezone.utc).timestamp()    # Sun 09:00 EDT (the clocks went forward)
        rig.engine.process([alert('RATE_429')], late)
        for at in (late + 600, nine - 60, nine, nine + 299, nine + 300):
            rig.engine.process([alert('RATE_429')], at)
        backup = [m for m in rig.fakes['push'].sent if m.person == 'ben']
        self.assertEqual(len(backup), 1)
        incident = rig.incident('RATE_429')
        events = [e for e in rig.store.events(incident['id']) if e['kind'] == 'step' and e['detail']['to'] == 'backup']
        self.assertEqual(events[0]['at'], nine + 300)

    def test_p2_is_email_in_duty_hours_only(self):
        rig = Rig()
        timeline = rig.run([alert('RATE_APP_BUDGET_SPENT', 'warn')], TUESDAY_2AM, int(TUESDAY_9AM - TUESDAY_2AM) + 120)
        self.assertEqual(timeline, {int(TUESDAY_9AM - TUESDAY_2AM): [('email', 'ana')]})

    def test_a_holiday_has_no_duty_window_but_p0_still_pages(self):
        raw = json.loads(P.DEFAULT_PATH.read_text())
        raw['dutyHours']['holidays'] = ['2026-10-27']
        rig = Rig(P.validate(raw))
        rig.run([alert('RATE_429'), alert()], TUESDAY_10AM, 600)
        self.assertEqual(rig.fakes['push'].to('ana', 'page')[0].rule, 'CROSS_TENANT_PROBE_FAILED')
        self.assertEqual([m.rule for m in rig.fakes['push'].sent], ['CROSS_TENANT_PROBE_FAILED', 'CROSS_TENANT_PROBE_FAILED'])
        self.assertEqual([m.rule for m in rig.fakes['email'].sent if m.rule == 'RATE_429'], ['RATE_429'])

    def test_a_rise_to_p0_restarts_an_unacknowledged_chain_and_only_informs_an_acknowledger(self):
        rig = Rig()
        rig.engine.process([alert('DELIVERY_UNCERTAIN', 'warn')], TUESDAY_10AM)
        rig.engine.process([alert('DELIVERY_UNCERTAIN', 'page')], TUESDAY_10AM + 60)
        incident = rig.incident('DELIVERY_UNCERTAIN')
        self.assertEqual((incident['priority'], incident['chainStartedAt']), ('P0', TUESDAY_10AM + 60))
        rig.run([alert('DELIVERY_UNCERTAIN', 'warn')], TUESDAY_10AM + 120, 300)
        self.assertEqual(rig.incident('DELIVERY_UNCERTAIN')['priority'], 'P0', 'never lowered by itself')
        self.assertEqual([m.person for m in rig.fakes['phone'].sent], ['ana'])
        other = Rig()
        other.engine.process([alert('DELIVERY_UNCERTAIN', 'warn')], TUESDAY_10AM)
        other.engine.acknowledge(other.incident('DELIVERY_UNCERTAIN')['id'], 'ana', 'dashboard', TUESDAY_10AM + 30)
        other.run([alert('DELIVERY_UNCERTAIN', 'page')], TUESDAY_10AM + 60, 900)
        self.assertEqual(other.fakes['phone'].sent, [])
        self.assertEqual([m.subject for m in other.fakes['push'].sent if m.kind == 'record'],
                         ['[P0] DELIVERY_UNCERTAIN raised to P0 while acknowledged'])


class DedupeSuppressionAndFlapping(unittest.TestCase):
    def test_a_repeating_alert_is_one_incident_and_one_notification_per_step_and_channel(self):
        rig = Rig()
        for minute in range(30):
            rig.engine.process([alert()], SATURDAY_3AM + 60 * minute)
            rig.engine.process([alert()], SATURDAY_3AM + 60 * minute)        # an overlapping run at the same moment
        self.assertEqual(len(rig.store.incidents()), 1)
        keys = [d['key'] for d in rig.store.deliveries()]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(rig.incident()['seenCount'], 60)

    def test_a_maintenance_window_holds_the_chain_until_it_ends(self):
        raw = json.loads(P.DEFAULT_PATH.read_text())
        raw['suppression']['maintenance'] = [{'start': TUESDAY_10AM - 60, 'end': TUESDAY_10AM + 600, 'rules': ['*']}]
        rig = Rig(P.validate(raw))
        timeline = rig.run([alert('SILENT_HALT_DATABASE')], TUESDAY_10AM, 1200)
        self.assertEqual(sorted(timeline)[0], 600)
        self.assertEqual(rig.incident('SILENT_HALT_DATABASE')['openedAt'], TUESDAY_10AM)
        kinds = [e['kind'] for e in rig.store.events()]
        self.assertLess(kinds.index('opened'), kinds.index('unsuppressed'))

    def test_a_security_alert_pages_inside_a_maintenance_window(self):
        raw = json.loads(P.DEFAULT_PATH.read_text())
        raw['suppression']['maintenance'] = [{'start': SATURDAY_3AM - 60, 'end': SATURDAY_3AM + 3600, 'rules': ['*']}]
        rig = Rig(P.validate(raw))
        self.assertEqual(rig.run([alert()], SATURDAY_3AM, 0), {0: [('email', 'ana'), ('push', 'ana')]})

    def test_a_cause_suppresses_its_symptoms(self):
        rig = Rig()
        rig.run([alert('SILENT_HALT_DATABASE'), alert('SILENT_HALT_NO_PROGRESS'), alert('BACKLOG_LAG')], SATURDAY_3AM, 0)
        self.assertEqual({m.rule for m in rig.fakes['push'].sent}, {'SILENT_HALT_DATABASE'})
        self.assertEqual(rig.incident('SILENT_HALT_NO_PROGRESS')['suppressedBy'], 'inhibit:SILENT_HALT_DATABASE')

    def test_a_flapping_alert_reopens_the_same_incident_without_resending_or_escaping_escalation(self):
        rig = Rig()
        rig.engine.process([alert()], SATURDAY_3AM)
        rig.engine.process([], SATURDAY_3AM + 60)
        rig.engine.process([], SATURDAY_3AM + 120)                       # resolved after two clear evaluations
        self.assertEqual(rig.incident()['state'], 'resolved')
        rig.engine.process([alert()], SATURDAY_3AM + 180)                 # back within ten minutes
        rig.engine.process([alert()], SATURDAY_3AM + 300)
        self.assertEqual(len(rig.store.incidents()), 1)
        self.assertEqual(len(rig.fakes['push'].to('ana', 'page')), 1)
        self.assertEqual([m.person for m in rig.fakes['phone'].sent], ['ana'], 'the 5-minute clock kept running')
        rig.engine.process([], SATURDAY_3AM + 360)
        rig.engine.process([], SATURDAY_3AM + 420)
        rig.engine.process([alert()], SATURDAY_3AM + 1100)                # back after more than ten minutes: a new incident
        self.assertEqual(len([i for i in rig.store.incidents() if i['rule'] == 'CROSS_TENANT_PROBE_FAILED']), 2)

    def test_absence_proves_nothing_while_a_no_data_rule_fires(self):
        rig = Rig()
        rig.engine.process([alert('RATE_429')], TUESDAY_10AM)
        for minute in range(1, 5):
            rig.engine.process([alert('SILENT_HALT_HEALTH_UNANSWERED')], TUESDAY_10AM + 60 * minute)
        self.assertEqual(rig.incident('RATE_429')['state'], 'open')

    def test_the_engines_own_alerts_are_resolved_by_a_person(self):
        rig = Rig()
        rig.engine.observe(alert('ONCALL_DELIVERY_FAILED'), 'P0', SATURDAY_3AM)
        for minute in range(1, 5):
            rig.engine.process([], SATURDAY_3AM + 60 * minute)
        incident = rig.incident('ONCALL_DELIVERY_FAILED')
        self.assertEqual(incident['state'], 'open')
        self.assertEqual(rig.engine.resolve(incident['id'], 'mallory', SATURDAY_3AM + 400)['reason'], 'unknown_person')
        self.assertTrue(rig.engine.resolve(incident['id'], 'ben', SATURDAY_3AM + 400)['ok'])
        self.assertEqual(rig.incident('ONCALL_DELIVERY_FAILED')['resolution'], 'manual')


class FallbackStormAndRoster(unittest.TestCase):
    def test_a_failed_push_brings_the_call_forward(self):
        rig = Rig()
        rig.fakes['push'].fail_for('ana')
        timeline = rig.run([alert()], SATURDAY_3AM, 120)
        self.assertEqual(timeline[0], [('email', 'ana'), ('phone', 'ana'), ('push', 'ana')])
        self.assertIn('fallback', [e['kind'] for e in rig.store.events()])

    def test_every_channel_failing_opens_the_engines_own_p0_without_a_loop(self):
        rig = Rig()
        for channel in ('push', 'email', 'phone'):
            rig.fakes[channel].fail_for('ana')
        rig.fakes['push'].raise_next(1)
        rig.run([alert()], SATURDAY_3AM, 900)
        meta = rig.incident('ONCALL_DELIVERY_FAILED')
        self.assertEqual(meta['priority'], 'P0')
        self.assertIn(('push', 'ben'), [(m.channel, m.person) for m in rig.fakes['push'].sent if m.rule == 'ONCALL_DELIVERY_FAILED'])
        self.assertEqual(len([i for i in rig.store.incidents() if i['rule'] == 'ONCALL_DELIVERY_FAILED']), 1)
        failed = [d for d in rig.store.deliveries() if d['status'] == 'failed']
        self.assertIn('provider_exception', {d['reason'] for d in failed})
        self.assertGreater(rig.engine.beat(SATURDAY_3AM + 900)['deliveryFailures1h'], 0)

    def test_a_storm_holds_back_what_is_over_the_limit_sends_one_summary_and_catches_up(self):
        rig = Rig()
        storm = [alert('RATE_429', scope='route%d' % n) for n in range(9)]
        rig.engine.process(storm, TUESDAY_10AM)
        pushes = rig.fakes['push'].to('ana', 'page')
        self.assertEqual(len(pushes), 6)
        self.assertEqual(len(rig.fakes['push'].to('ana', 'summary')), 1)
        self.assertEqual(len(rig.fakes['email'].to('ana', 'page')), 9)
        rig.engine.process(storm, TUESDAY_10AM + 60)
        self.assertEqual(len(rig.fakes['push'].to('ana', 'page')), 6, 'still held inside the window')
        self.assertEqual(len(rig.fakes['push'].to('ana', 'summary')), 1, 'one summary per window')
        rig.engine.process(storm, TUESDAY_10AM + 601)
        self.assertEqual(len([m for m in rig.fakes['push'].to('ana', 'page') if m.rule == 'RATE_429']), 9,
                         'held pages go out when the window allows')

    def test_the_shipped_placeholder_roster_raises_its_own_p0_and_reaches_nobody(self):
        rig = Rig(roster_=json.loads(P.DEFAULT_PATH.read_text())['roster'])
        rig.engine.process([alert()], SATURDAY_3AM)
        self.assertEqual(rig.incident('ONCALL_ROSTER_INVALID')['priority'], 'P0')
        self.assertEqual([d['status'] for d in rig.store.deliveries() if d['kind'] == 'page'][:2], ['unconfigured', 'unconfigured'])
        self.assertTrue(rig.engine.beat(SATURDAY_3AM)['rosterProblems'])

    def test_no_one_on_call_is_recorded_and_escalated(self):
        gap = roster(shifts=[{'days': 'daily', 'start': '09:00', 'end': '23:00', 'primary': 'ana', 'backup': 'ben'}])
        rig = Rig(roster_=gap)
        rig.engine.process([alert()], SATURDAY_3AM)
        self.assertIn('no_recipient', [e['kind'] for e in rig.store.events()])
        self.assertIn('ONCALL_ROSTER_INVALID', {i['rule'] for i in rig.store.incidents()})


class HeartbeatAndStage(unittest.TestCase):
    def test_the_heartbeat_and_what_a_watchdog_concludes_from_it(self):
        rig = Rig()
        rig.engine.process([alert()], SATURDAY_3AM)
        beat = rig.store.heartbeat()
        self.assertEqual((beat['at'], beat['unacknowledgedP0'], beat['open']['P0']), (SATURDAY_3AM, 1, 1))
        self.assertEqual(heartbeat_alerts(beat, SATURDAY_3AM + 60, POLICY), [])
        self.assertEqual([a['id'] for a in heartbeat_alerts(beat, SATURDAY_3AM + 181, POLICY)], ['ONCALL_HEARTBEAT_STALE'])
        self.assertEqual([a['id'] for a in heartbeat_alerts(None, SATURDAY_3AM, POLICY)], ['ONCALL_HEARTBEAT_STALE'])
        late = dict(beat, at=SATURDAY_3AM + 1000, oldestUnacknowledgedP0Seconds=1000)
        self.assertIn('ONCALL_P0_UNACKNOWLEDGED', [a['id'] for a in heartbeat_alerts(late, SATURDAY_3AM + 1000, POLICY)])

    def test_after_a_gap_the_engine_says_it_was_not_running(self):
        rig = Rig()
        rig.engine.process([], TUESDAY_10AM)
        rig.engine.process([], TUESDAY_10AM + 1800)
        gap = rig.incident('ONCALL_ENGINE_GAP')
        self.assertEqual((gap['priority'], gap['state']), ('P1', 'open'))

    def test_the_stage_does_nothing_unless_the_flag_is_exactly_true(self):
        store = MemoryStore()
        for values in ({}, {ENV_ENABLED: 'TRUE'}, {ENV_ENABLED: '1'}):
            self.assertEqual(stage(values, [alert()], SATURDAY_3AM, policy=POLICY, store=store, providers={}), {'skipped': 'disabled'})
        self.assertEqual(store.incidents(), [])
        result = stage({ENV_ENABLED: 'true'}, [alert()], SATURDAY_3AM, policy=POLICY, store=store, providers={}, roster=roster())
        self.assertIn('CROSS_TENANT_PROBE_FAILED', result['routed'])


class Messages(unittest.TestCase):
    def test_push_and_phone_carry_codes_only_and_email_the_evaluators_counts(self):
        rig = Rig()
        hostile = alert()
        hostile['message'] = 'probe failed\n<script>alert(1)</script> workspace 3f6c8d2e-1b7a ‮'
        rig.run([hostile], SATURDAY_3AM, 300)
        push, phone, email = rig.fakes['push'].sent[0], rig.fakes['phone'].sent[0], rig.fakes['email'].sent[0]
        for message in (push, phone):
            self.assertNotIn('script', message.body)
            self.assertNotIn('3f6c8d2e', message.body)
        self.assertNotIn('\n', email.body)
        self.assertNotIn('‮', email.body)
        self.assertEqual(push.destination, 'ref-ana-push')
        self.assertIn('Press 1 to acknowledge', phone.body)


class AutomaticHold(unittest.TestCase):
    """Option D1: an owner decision, off by default and advised against (H07-OPTIONS.md). Logic only, with a fake
    executor; the real statements run on a disposable PostgreSQL in tests/oncall_drills.py."""

    class Executor:
        def __init__(self, rows=1, held=False, fail=False):
            self.rows, self.held, self.fail, self.statements = rows, held, fail, []

        def __call__(self, sql):
            self.statements.append(sql)
            if self.fail:
                raise RuntimeError('database unreachable')
            if sql == autohold.HOLD_ON:
                if self.rows:
                    self.held = True
                return [{'kind': 'policy', 'manual_hold': True}] * self.rows
            return [{'policy_rows': self.rows, 'held': self.rows if self.held else 0}]

    def rig(self, executor):
        rig = Rig()
        rig.engine.hold = autohold.AutoHold(POLICY, executor)
        return rig

    def test_it_engages_once_per_incident_on_a_failed_probe_only_and_never_lifts(self):
        executor = self.Executor()
        rig = self.rig(executor)
        rig.engine.process([alert('CROSS_TENANT_PROBING', 'page')], SATURDAY_3AM)
        self.assertNotIn(autohold.HOLD_ON, executor.statements, 'probing is the gate working, never a hold')
        for minute in range(3):
            rig.engine.process([alert()], SATURDAY_3AM + 60 * (minute + 1))
        self.assertEqual(executor.statements.count(autohold.HOLD_ON), 1)
        self.assertFalse([s for s in executor.statements if 'manual_hold = false' in s])
        self.assertEqual(rig.incident('ONCALL_AUTO_HOLD_ENGAGED')['priority'], 'P0')
        self.assertIn('auto_hold_engaged', [e['kind'] for e in rig.store.events()])

    def test_no_policy_row_or_a_database_error_is_a_failed_hold_page(self):
        for executor in (self.Executor(rows=0), self.Executor(fail=True)):
            rig = self.rig(executor)
            rig.engine.process([alert()], SATURDAY_3AM)
            self.assertEqual(rig.incident('ONCALL_AUTO_HOLD_FAILED')['priority'], 'P0')
            self.assertNotIn('ONCALL_AUTO_HOLD_ENGAGED', {i['rule'] for i in rig.store.incidents()})

    def test_off_unless_both_flags_and_an_executor(self):
        store, executor = MemoryStore(), self.Executor()
        stage({ENV_ENABLED: 'true'}, [alert()], SATURDAY_3AM, policy=POLICY, store=store, providers={}, roster=roster(),
              hold_executor=executor)
        stage({ENV_ENABLED: 'true', ENV_AUTO_HOLD: 'TRUE'}, [alert()], SATURDAY_3AM + 60, policy=POLICY, store=store,
              providers={}, roster=roster(), hold_executor=executor)
        self.assertEqual(executor.statements, [])
        stage({ENV_ENABLED: 'true', ENV_AUTO_HOLD: 'true'}, [alert()], SATURDAY_3AM + 120, policy=POLICY, store=store,
              providers={}, roster=roster(), hold_executor=executor)
        self.assertIn(autohold.HOLD_ON, executor.statements)

    def test_the_default_rules_are_a_confirmed_exposure_only(self):
        self.assertEqual(POLICY['autoHold']['rules'], ['CROSS_TENANT_PROBE_FAILED'])


class Readiness(unittest.TestCase):
    def real(self, name):
        return {'requirement': name, 'kind': 'real', 'result': 'pass', 'people': 'real', 'destination': 'real',
                'at': '2026-10-30T03:00:00Z', 'reference': 'receipt-%s' % name}

    def test_today_it_is_blocked_with_the_alternatives(self):
        report = readiness.status(POLICY)
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertIn('night_cover_not_declared', report['reasons'])
        self.assertIn('roster:primary_without_phone', report['reasons'])
        self.assertEqual(len(report['alternatives']), 4)

    def test_isolated_evidence_never_verifies(self):
        isolated = [dict(self.real(name), kind='isolated') for name, _ in readiness.REQUIREMENTS]
        report = readiness.status(POLICY, isolated, night_cover=True, roster=roster())
        self.assertEqual(report['status'], 'NOT_VERIFIED')
        self.assertEqual(len(report['missingRealTests']), len(readiness.REQUIREMENTS))

    def test_verified_only_with_every_real_test_cover_and_a_valid_roster(self):
        evidence = [self.real(name) for name, _ in readiness.REQUIREMENTS]
        self.assertEqual(readiness.status(POLICY, evidence, night_cover=True, roster=roster())['status'], 'VERIFIED')
        self.assertEqual(readiness.status(POLICY, evidence, night_cover=False, roster=roster())['status'], 'BLOCKED')
        self.assertEqual(readiness.status(POLICY, evidence[:-1], night_cover=True, roster=roster())['status'], 'NOT_VERIFIED')
        failed = copy.deepcopy(evidence)
        failed[0]['result'] = 'fail'
        self.assertEqual(readiness.status(POLICY, failed, night_cover=True, roster=roster())['status'], 'NOT_VERIFIED')
        no_backup = roster(shifts=[{'days': 'daily', 'start': '00:00', 'end': '24:00', 'primary': 'ana', 'backup': None}])
        self.assertEqual(readiness.status(POLICY, evidence, night_cover=True, roster=no_backup)['status'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()
