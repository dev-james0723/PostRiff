"""Founder contact policy, attempts and the (a) incident → call → ack path with the fake telephony provider.

No PostgreSQL: `MemoryFounderStore` mirrors the founder store protocol and `FakeCalls` stands in for
`founder_contact.PhoneCalls` while still running the real `phone.planner.eligibility` with the founder scope flags that
`phone.runtime.FounderPhoneConfig` produces, so the FOUNDER_CALL_EVENTS branch is exercised end to end. No network.
"""
import copy
import importlib.util
import os
import time
import types
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault('RAFII_PHONE_PROVIDER', 'fake')

from postriff_alpha.domain import AlphaError
from postriff_phase2.phone import contracts, inbound, planner
from postriff_phase2.phone.config import PhoneConfig
from postriff_phase2.phone.providers.fake import FakeTelephonyProvider
from postriff_phase2.phone.runtime import FounderPhoneConfig, principal_phone
from postriff_phase2.phone.session import FOUNDER_PLAYBACK_UNAVAILABLE, founder_playback_prompt
from postriff_phase2.oauth import CredentialVault
from rafii_control import founder_contact, founder_incidents
from rafii_control.auth import ControlError
from rafii_control.founder_briefings import playback_text
from rafii_control.founder_contact import (ACTIVE_STATES, FLAG, PURPOSE_KINDS, destination_ref, plan_contact, public_policy, reserve_contact,
                                           validate_policy)
from rafii_control.founder_cron import PostgresFounderStore

OPERATOR = '00000000-0000-0000-0000-00000000f00d'
OPS = '00000000-0000-0000-0000-0000000000a1'
OTHER = '00000000-0000-0000-0000-0000000000b2'
T0 = 1790000000.0  # 2026-09-21 14:13:20 UTC (a Monday, daytime in every policy zone used below)
PRINCIPAL = {'operator': {'user_id': OPERATOR, 'capabilities': ['control.read', 'control.settings', 'incidents.ack']}, 'session': {'id': 'sess'}}


# --- in-memory founder store (same method surface as founder_cron.PostgresFounderStore) ------------------------------------
class MemoryFounderStore:
    def __init__(self, environment='local', operators=(OPERATOR,)):
        self.environment, self.operators = environment, list(operators)
        self.policies, self.destinations, self.attempt_rows = {}, {}, {}
        self.incident_rows, self.event_rows, self.ack_rows = {}, [], {}
        self.schedule_rows, self.occurrence_rows, self.report_rows, self.sources = {}, {}, {}, {}
        self.follow_up_rows, self.audit_rows = {}, []

    def ping(self):
        return True

    def audit(self, action, result, actor, request_id, *, error_code=None):
        self.audit_rows.append({'action': action, 'result': result, 'actor': actor, 'request_id': request_id, 'environment': self.environment, 'error_code': error_code})

    def founder_operators(self):
        return list(self.operators)

    # contact
    def policy(self, operator_id):
        return copy.deepcopy(self.policies.get(operator_id))

    def save_policy(self, operator_id, policy, now, expected_revision=None):
        if expected_revision is not None and (self.policies.get(operator_id) or {}).get('revision', 0) != expected_revision:
            return None
        revision = (self.policies.get(operator_id) or {}).get('revision', 0) + 1
        row = {**policy, 'operator_id': operator_id, 'environment': self.environment, 'revision': revision, 'updated_at': now}
        self.policies[operator_id] = row
        return copy.deepcopy(row)

    def destination_verified(self, operator_id):
        return bool(self.destinations.get(operator_id))

    def attempt_by_key(self, key):
        return next((copy.deepcopy(a) for a in self.attempt_rows.values() if a['idempotency_key'] == key), None)

    def insert_attempt(self, row):
        existing = self.attempt_by_key(row['idempotency_key'])
        if existing:
            return existing
        self.attempt_rows[row['id']] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def update_attempt(self, attempt_id, **fields):
        if set(fields) - founder_contact._ATTEMPT_FIELDS:
            raise ValueError('unknown attempt field')
        self.attempt_rows[attempt_id].update(fields)
        return copy.deepcopy(self.attempt_rows[attempt_id])

    def attempts(self, operator_id=None, *, since=None, states=None, source_id=None, limit=500):
        rows = [a for a in self.attempt_rows.values() if (operator_id is None or a['operator_id'] == operator_id)
                and (since is None or a['created_at'] >= since) and (states is None or a['state'] in states)
                and (source_id is None or a['source_id'] == source_id)]
        rows.sort(key=lambda a: a['created_at'], reverse=True)
        return [copy.deepcopy(a) for a in rows[:limit]]

    def cancel_pending_attempts(self, source_id, reason, now):
        count = 0
        for row in self.attempt_rows.values():
            if row['source_id'] == source_id and row['state'] == 'reserved' and not row.get('phone_call_id'):
                row.update(state='cancelled', outcome={**row['outcome'], 'reason': reason}, updated_at=now)
                count += 1
        return count

    # follow-ups (founder_follow_ups.FollowUpSQL surface; the per-operator policy is modelled by the operator filter)
    def follow_ups(self, operator_id, *, limit=100):
        rows = sorted((r for r in self.follow_up_rows.values() if r['operator_id'] == operator_id), key=lambda r: (-r['created_at'], r['id']))
        return [copy.deepcopy(r) for r in rows[:limit]]

    def follow_up(self, operator_id, follow_up_id):
        row = self.follow_up_rows.get(follow_up_id)
        return copy.deepcopy(row) if row and row['operator_id'] == operator_id else None

    def insert_follow_up(self, row):
        key = (row['operator_id'], row['environment'], row['source_type'], row['source_id'])
        existing = next((r for r in self.follow_up_rows.values() if (r['operator_id'], r['environment'], r['source_type'], r['source_id']) == key), None)
        if existing:
            return copy.deepcopy(existing)
        self.follow_up_rows[row['id']] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def update_follow_up(self, operator_id, follow_up_id, *, expected_revision, **fields):
        from rafii_control.founder_follow_ups import _FOLLOW_UP_FIELDS
        if set(fields) - _FOLLOW_UP_FIELDS:
            raise ValueError('unknown follow-up field')
        row = self.follow_up_rows.get(follow_up_id)
        if row is None or row['operator_id'] != operator_id or row['revision'] != expected_revision:
            return None
        row.update(fields)
        row['revision'] += 1
        return copy.deepcopy(row)

    # incidents
    def incident(self, incident_id):
        return copy.deepcopy(self.incident_rows.get(incident_id))

    def open_incidents(self):
        rows = sorted((r for r in self.incident_rows.values() if r['state'] != 'resolved'), key=lambda r: (r['opened_at'], r['id']))
        return [copy.deepcopy(r) for r in rows]

    def list_incidents(self, *, limit=50):
        rows = sorted(self.incident_rows.values(), key=lambda r: (r['state'] == 'resolved', -r['opened_at']))
        return [copy.deepcopy(r) for r in rows[:limit]]

    def insert_incident(self, row):
        key = (row['detector'], row['scope'], row['episode_key'])
        existing = next((r for r in self.incident_rows.values() if (r['detector'], r['scope'], r['episode_key']) == key), None)
        if existing:
            return copy.deepcopy(existing)
        self.incident_rows[row['id']] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def update_incident(self, incident_id, **fields):
        if set(fields) - founder_incidents._INCIDENT_FIELDS:
            raise ValueError('unknown incident field')
        row = self.incident_rows[incident_id]
        row.update(fields)
        if founder_incidents.bumps_version(fields):   # IncidentSQL rule: only a severity/state transition moves the version
            row['version'] += 1
        return copy.deepcopy(row)

    def insert_incident_event(self, incident_id, kind, at, body):
        event = {'id': str(uuid.uuid4()), 'incident_id': incident_id, 'kind': kind, 'at': at, 'body': dict(body or {})}
        self.event_rows.append(event)
        return copy.deepcopy(event)

    def incident_events(self, incident_id):
        return [copy.deepcopy(e) for e in self.event_rows if e['incident_id'] == incident_id]

    def insert_ack(self, incident_id, version, operator_id, at, channel):
        if (incident_id, version) in self.ack_rows:
            return False
        self.ack_rows[(incident_id, version)] = {'operator_id': operator_id, 'at': at, 'channel': channel}
        return True

    # schedules
    def schedules(self, operator_id):
        rows = sorted((r for r in self.schedule_rows.values() if r['operator_id'] == operator_id), key=lambda r: (r['created_at'], r['id']))
        return [copy.deepcopy(r) for r in rows]

    def schedule(self, schedule_id):
        return copy.deepcopy(self.schedule_rows.get(schedule_id))

    def insert_schedule(self, row):
        self.schedule_rows[row['id']] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def update_schedule(self, schedule_id, *, next_at=None, expected_next_at=None, enabled=None):
        row = self.schedule_rows.get(schedule_id)
        if row is None or (expected_next_at is not None and abs(row['next_at'] - expected_next_at) >= 0.5):
            return None
        if next_at is not None:
            row['next_at'] = next_at
        if enabled is not None:
            row['enabled'] = enabled
        row['revision'] += 1
        return copy.deepcopy(row)

    def delete_schedule(self, operator_id, schedule_id):
        row = self.schedule_rows.get(schedule_id)
        if row is None or row['operator_id'] != operator_id:
            return False
        del self.schedule_rows[schedule_id]
        for oid in [o['id'] for o in self.occurrence_rows.values() if o['schedule_id'] == schedule_id]:
            del self.occurrence_rows[oid]
        return True

    def due_schedules(self, now):
        rows = sorted((r for r in self.schedule_rows.values() if r['enabled'] and r['next_at'] <= now), key=lambda r: (r['next_at'], r['id']))
        return [copy.deepcopy(r) for r in rows]

    def insert_occurrence(self, row):
        key = (row['schedule_id'], row['local_date'], row['slot'])
        existing = next((o for o in self.occurrence_rows.values() if (o['schedule_id'], o['local_date'], o['slot']) == key), None)
        if existing:
            return copy.deepcopy(existing)
        self.occurrence_rows[row['id']] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def update_occurrence(self, occurrence_id, **fields):
        from rafii_control.founder_schedules import _OCCURRENCE_FIELDS
        if set(fields) - _OCCURRENCE_FIELDS:
            raise ValueError('unknown occurrence field')
        self.occurrence_rows[occurrence_id].update(fields)
        return copy.deepcopy(self.occurrence_rows[occurrence_id])

    def occurrences(self, schedule_id, *, limit=20):
        rows = sorted((o for o in self.occurrence_rows.values() if o['schedule_id'] == schedule_id), key=lambda o: o['scheduled_at'], reverse=True)
        return [copy.deepcopy(o) for o in rows[:limit]]

    def expired_claims(self, now):
        rows = [o for o in self.occurrence_rows.values() if o['state'] == 'claimed' and o['lease_until'] is not None and o['lease_until'] < now]
        return [copy.deepcopy(o) for o in sorted(rows, key=lambda o: o['scheduled_at'])]

    # reports
    def insert_report(self, row):
        version = max((r['version'] for r in self.report_rows.values() if (r['operator_id'], r['kind']) == (row['operator_id'], row['kind'])), default=0) + 1
        stored = {**copy.deepcopy(row), 'version': version}
        self.report_rows[row['id']] = stored
        return copy.deepcopy(stored)

    def report(self, report_id):
        return copy.deepcopy(self.report_rows.get(report_id))

    def reports(self, operator_id, *, kind=None, limit=20):
        rows = [r for r in self.report_rows.values() if r['operator_id'] == operator_id and (kind is None or r['kind'] == kind)]
        rows.sort(key=lambda r: (r['generated_at'], r['version']), reverse=True)
        return [copy.deepcopy(r) for r in rows[:limit]]

    # source health
    def upsert_source_health(self, source_id, state, reason_code, checked_at, watermark=None):
        self.sources[source_id] = {'source_id': source_id, 'state': state, 'reason_code': reason_code, 'checked_at': checked_at,
                                   'watermark': watermark if watermark is not None else (self.sources.get(source_id) or {}).get('watermark')}

    def source_health(self):
        return [copy.deepcopy(self.sources[k]) for k in sorted(self.sources)]


# --- fake phone product -----------------------------------------------------------------------------------------------------
class FakeCalls:
    """founder_contact.PhoneCalls without PostgreSQL: the real planner with the founder scope flags, fake provider
    receipts and PhoneService.request's replay-by-idempotency-key."""
    def __init__(self, *, ops_workspace_id=OPS, workspace_id=None, values=None, prefs=None, provider=None, verified=True,
                 estimate=20_000, clock=lambda: T0, crash_after_create=False):
        self.provider = provider or FakeTelephonyProvider()
        self.values = {**{flag: '1' for flag in contracts.FLAGS}, 'RAFII_FOUNDER_OPS_WORKSPACE_ID': ops_workspace_id, **(values or {})}
        self.workspace_id = workspace_id or ops_workspace_id
        self.prefs = {**contracts.DEFAULTS, 'enabled': True, 'proactiveCalls': True, 'scheduledCalls': True, 'timeZone': 'UTC', **(prefs or {})}
        # Mirror the adapter's server-loaded policy in this synthetic phone scope.
        self.values = {**self.values, 'RAFII_FOUNDER_PHONE_QUIET_START': self.prefs['quietStart'],
                       'RAFII_FOUNDER_PHONE_QUIET_END': self.prefs['quietEnd'], 'RAFII_FOUNDER_PHONE_TIME_ZONE': self.prefs['timeZone'],
                       **(values or {})}
        self.verified, self.estimate, self.clock, self.crash_after_create = verified, estimate, clock, crash_after_create
        self.calls, self.by_key, self.requests = {}, {}, []

    def configured(self):
        return bool(self.provider.configured)

    def estimate_usd_micro(self, max_seconds=300):
        return self.estimate

    def request(self, attempt):
        key = attempt['idempotency_key']
        self.requests.append(key)
        if key in self.by_key:
            return dict(self.calls[self.by_key[key]])
        kind, event_type = PURPOSE_KINDS[attempt['purpose']]
        flags = FounderPhoneConfig(self.values, self.workspace_id, key).public()
        automatic = sum(1 for c in self.calls.values() if c['kind'] != 'explicit')
        blocker = planner.eligibility(kind, self.prefs, now=self.clock(), verified=self.verified, membership=True, configured=self.provider.configured,
                                      live_configured=True, flags=flags, event_type=event_type, daily_calls=automatic if kind != 'explicit' else len(self.calls),
                                      active=any(c['state'] not in contracts.TERMINAL for c in self.calls.values()), reserved_cost=0, estimate=self.estimate,
                                      daily_budget=2_000_000)
        if blocker:
            raise AlphaError(contracts.failure_message(blocker), 409, code=blocker)
        call_id = str(uuid.uuid4())
        receipt = self.provider.create_outbound_call(number='+10000000000', call_id=call_id, max_seconds=300)
        call = {'id': call_id, 'state': receipt.state if receipt.state not in contracts.TERMINAL else 'dialing', 'kind': kind, 'provider': 'fake',
                'failure': None, 'execution': 'fake', 'ref': receipt.call_ref}
        self.calls[call_id], self.by_key[key] = call, call_id
        if self.crash_after_create:
            self.crash_after_create = False
            raise RuntimeError('transport lost after the claim was committed')
        return dict(call)

    def read(self, call_id):
        return dict(self.calls[call_id]) if call_id in self.calls else None

    def reconcile(self, call_id):
        call = self.calls.get(call_id)
        if call is None:
            return None
        receipt = self.provider.reconcile(number='', call_id=call_id, call_ref=call['ref'], requested_at=0)
        if receipt.call_ref:
            call['state'] = receipt.state if receipt.state in contracts.TERMINAL else contracts.transition(call['state'], receipt.state)
        return dict(call)

    def provider_state(self, call_id, state):
        self.provider.calls[self.calls[call_id]['ref']]['state'] = state


def enabled_policy(**overrides):
    body = {'liveDeliveryEnabled': True, 'channels': ['call', 'push'], 'destinationRef': destination_ref(OPERATOR), 'quietStart': 0, 'quietEnd': 0,
            'timeZone': 'UTC', 'dailyCap': 2, 'concurrentCap': 1, 'eventAllowlist': ['founder.incident', 'founder.briefing'],
            'budgetUsdMicroDaily': 1_000_000}
    body.update(overrides)
    return validate_policy(body, None, OPERATOR)


def ready_state(**overrides):
    state = {'flags': {FLAG: '1'}, 'verified': True, 'daily_calls': 0, 'active_calls': 0, 'reserved_usd_micro': 0, 'estimate_usd_micro': 20_000,
             'scheduled_at': T0}
    state.update(overrides)
    return state


def critical_incident(fstore, now=T0, scope='global'):
    return fstore.insert_incident({'id': str(uuid.uuid4()), 'environment': fstore.environment, 'detector': 'publish_failure_rate', 'scope': scope,
                                   'episode_key': f'publish_failure_rate:{scope}:{int(now)}', 'severity': 'critical', 'state': 'open', 'opened_at': now,
                                   'acknowledged_at': None, 'resolved_at': None, 'evidence': {'rate': 0.6, 'thresholdVersion': 1}, 'affected_count': 6,
                                   'version': 1})


class ContactPolicyTests(unittest.TestCase):
    def test_reason_codes_in_gate_order(self):
        policy = validate_policy({}, None, OPERATOR)
        self.assertEqual(plan_contact(policy, 'incident', T0, ready_state())['reason'], 'POLICY_DISABLED')
        policy = enabled_policy()
        self.assertEqual(plan_contact(policy, 'incident', T0, ready_state(flags={}))['detail'], 'deployment_flag_unset')
        self.assertEqual(plan_contact(enabled_policy(eventAllowlist=['founder.briefing']), 'incident', T0, ready_state())['detail'], 'event_not_allowed')
        self.assertEqual(plan_contact(enabled_policy(channels=['push']), 'incident', T0, ready_state())['reason'], 'CONSENT_REQUIRED')
        self.assertEqual(plan_contact(enabled_policy(destinationRef=None), 'incident', T0, ready_state())['reason'], 'NUMBER_UNVERIFIED')
        self.assertEqual(plan_contact(policy, 'incident', T0, ready_state(verified=False))['reason'], 'NUMBER_UNVERIFIED')
        self.assertEqual(plan_contact(policy, 'briefing', T0, ready_state(scheduled_at=None))['reason'], 'TIME_NOT_SELECTED')
        self.assertEqual(plan_contact({**policy, 'time_zone': 'Mars/Olympus'}, 'incident', T0, ready_state())['reason'], 'TIME_NOT_SELECTED')
        self.assertEqual(plan_contact(enabled_policy(budgetUsdMicroDaily=0), 'incident', T0, ready_state())['reason'], 'BUDGET_NOT_APPROVED')
        self.assertEqual(plan_contact(policy, 'incident', T0, ready_state(reserved_usd_micro=990_000))['detail'], 'daily_budget_exhausted')
        quiet = enabled_policy(quietStart=1320, quietEnd=480, timeZone='UTC')
        night = T0 + 9 * 3600  # 23:13 UTC
        self.assertEqual(plan_contact(quiet, 'incident', night, ready_state())['reason'], 'QUIET_HOURS')
        self.assertEqual(plan_contact(quiet, 'test', night, ready_state())['reason'], 'OK', 'an explicit test call ignores quiet hours')
        self.assertEqual(plan_contact(policy, 'incident', T0, ready_state(daily_calls=2))['reason'], 'DAILY_CAP')
        self.assertEqual(plan_contact(policy, 'test', T0, ready_state(daily_calls=2))['reason'], 'OK')
        self.assertEqual(plan_contact(policy, 'incident', T0, ready_state(active_calls=1))['reason'], 'CALL_ACTIVE')
        self.assertEqual(plan_contact(policy, 'incident', T0, ready_state())['reason'], 'OK')
        unlimited = enabled_policy(budgetUsdMicroDaily=None, dailyCap=5, concurrentCap=3)
        self.assertEqual(plan_contact(unlimited, 'incident', T0, ready_state(daily_calls=4, active_calls=2,
                         reserved_usd_micro=20_000_000_000))['reason'], 'OK')
        self.assertEqual(plan_contact(unlimited, 'incident', T0, ready_state(active_calls=3))['reason'], 'CALL_ACTIVE')
        with self.assertRaises(ControlError):
            plan_contact(policy, 'marketing', T0, ready_state())

    def test_policy_validation_and_defaults(self):
        public = public_policy(validate_policy({}, None, OPERATOR))
        self.assertFalse(public['liveDeliveryEnabled'])
        self.assertEqual((public['quietStart'], public['quietEnd'], public['timeZone'], public['dailyCap'], public['concurrentCap'], public['budgetUsdMicroDaily']),
                         (1320, 480, 'America/Indiana/Indianapolis', 2, 1, 0))
        for bad in ({'liveDeliveryEnabled': 'yes'}, {'channels': ['sms']}, {'eventAllowlist': ['publish.failed']}, {'dailyCap': 101}, {'concurrentCap': 11},
                    {'budgetUsdMicroDaily': 10_000_000_001}, {'timeZone': 'Nowhere/Here'}, {'destinationRef': destination_ref(OTHER)}, {'quietStart': 1440},
                    {'unknown': 1}):
            with self.subTest(bad=bad), self.assertRaises(ControlError):
                validate_policy(bad, None, OPERATOR)
        saved = validate_policy({'channels': ['push', 'call', 'call']}, None, OPERATOR)
        self.assertEqual(saved['channels'], ['call', 'push'])

    def test_get_and_put_policy_round_trip(self):
        fstore = MemoryFounderStore()
        first = founder_contact.put_policy(fstore, PRINCIPAL, {'channels': ['call']}, now=T0)['policy']
        second = founder_contact.put_policy(fstore, PRINCIPAL, {'liveDeliveryEnabled': True}, now=T0 + 1)['policy']
        self.assertEqual((first['revision'], second['revision']), (1, 2))
        self.assertEqual(second['channels'], ['call'], 'a patch merges over the saved policy')
        view = founder_contact.get_policy(fstore, PRINCIPAL, now=T0, flags={})
        self.assertFalse(view['destination']['verified'])
        self.assertEqual(view['readiness']['incident']['reason'], 'POLICY_DISABLED')
        self.assertFalse(view['flags']['founderCallsEnabled'])


class ContactPolicyPanelBodyTests(unittest.TestCase):
    def test_the_settings_page_body_saves_and_a_stale_revision_conflicts(self):
        # The page sends back the policy it read (web settings/contact-policy-form.tsx): revision and updatedAt included.
        fstore = MemoryFounderStore()
        read = founder_contact.get_policy(fstore, PRINCIPAL, now=T0, flags={})['policy']
        saved = founder_contact.put_policy(fstore, PRINCIPAL, {**read, 'quietStart': 1260, 'dailyCap': 1}, now=T0)['policy']
        self.assertEqual((saved['revision'], saved['quietStart'], saved['dailyCap'], saved['liveDeliveryEnabled']), (1, 1260, 1, False))
        again = founder_contact.put_policy(fstore, PRINCIPAL, {**saved, 'dailyCap': 2}, now=T0 + 1)['policy']
        self.assertEqual(again['revision'], 2)
        with self.assertRaises(ControlError) as caught:
            founder_contact.put_policy(fstore, PRINCIPAL, {**saved, 'dailyCap': 0}, now=T0 + 2)   # saved is revision 1; the store moved to 2
        self.assertEqual(caught.exception.code, 'STALE_PREVIEW')
        with self.assertRaises(ControlError):
            founder_contact.put_policy(fstore, PRINCIPAL, {**again, 'revision': 'two'}, now=T0 + 3)
        with self.assertRaises(ControlError):
            founder_contact.put_policy(fstore, PRINCIPAL, {**again, 'unknownField': 1}, now=T0 + 3)


class FounderCallEventsTests(unittest.TestCase):
    def prefs(self):
        return {**contracts.DEFAULTS, 'enabled': True, 'proactiveCalls': True, 'timeZone': 'UTC'}

    def eligibility(self, flags, event_type='founder.incident'):
        return planner.eligibility('proactive', self.prefs(), now=T0, verified=True, membership=True, configured=True, live_configured=True,
                                   flags=flags, event_type=event_type, estimate=1, daily_budget=100)

    def test_planner_accepts_founder_events_only_with_scope_in_ops_workspace(self):
        values = {**{flag: '1' for flag in contracts.FLAGS}, 'RAFII_FOUNDER_OPS_WORKSPACE_ID': OPS}
        scoped = FounderPhoneConfig(values, OPS, 'founder:incident:abc').public()
        self.assertIsNone(self.eligibility(scoped))
        self.assertIsNone(self.eligibility(scoped, event_type='founder'), 'delivery.deliver passes the reason key prefix')
        self.assertEqual(self.eligibility(scoped, event_type='publish.failed'), 'event_not_allowed')
        self.assertEqual(self.eligibility(FounderPhoneConfig(values, OTHER, 'founder:incident:abc').public()), 'event_not_allowed')
        self.assertEqual(self.eligibility(FounderPhoneConfig(values, OPS, 'notification:abc').public()), 'event_not_allowed')
        self.assertEqual(self.eligibility(FounderPhoneConfig(values, OPS, 'founder:test:abc').public()), 'event_not_allowed')
        self.assertEqual(self.eligibility(FounderPhoneConfig(values, OPS, 'founder:incident:').public()), 'event_not_allowed')
        unconfigured = FounderPhoneConfig({k: v for k, v in values.items() if k != 'RAFII_FOUNDER_OPS_WORKSPACE_ID'}, OPS, 'founder:incident:abc').public()
        self.assertEqual(self.eligibility(unconfigured), 'event_not_allowed')
        self.assertEqual(self.eligibility(PhoneConfig(values).public()), 'event_not_allowed', 'customer services carry no founder scope')
        self.assertNotIn('founder', PhoneConfig(values).public())

    def test_customer_preferences_cannot_allowlist_founder_events(self):
        with self.assertRaises(AlphaError):
            contracts.preferences({'eventAllowlist': ['founder.incident']})
        self.assertTrue(contracts.FOUNDER_CALL_EVENTS.isdisjoint(contracts.CALL_EVENTS))

    def test_only_server_scoped_founder_calls_use_configured_limits_and_unlimited_budget(self):
        values = {**{flag: '1' for flag in contracts.FLAGS}, 'RAFII_FOUNDER_OPS_WORKSPACE_ID': OPS,
                  'RAFII_FOUNDER_PHONE_AUTOMATIC_DAILY': 5, 'RAFII_FOUNDER_PHONE_CONCURRENT': 3,
                  'RAFII_FOUNDER_PHONE_QUIET_START': 0, 'RAFII_FOUNDER_PHONE_QUIET_END': 0,
                  'RAFII_FOUNDER_PHONE_TIME_ZONE': 'UTC', 'RAFII_FOUNDER_PHONE_DAILY_USD_MICRO': None}
        scoped = FounderPhoneConfig(values, OPS, 'founder:incident:abc')
        self.assertIsNone(scoped.daily_budget)
        args = dict(now=T0, verified=True, membership=True, configured=True, live_configured=True,
                    event_type='founder.incident', daily_calls=4, active_calls=2,
                    reserved_cost=20_000_000_000, estimate=1, daily_budget=scoped.daily_budget)
        self.assertIsNone(planner.eligibility('proactive', self.prefs(), flags=scoped.public(), **args))
        self.assertEqual(planner.eligibility('proactive', self.prefs(), flags=scoped.public(), **{**args, 'daily_calls': 5}), 'daily_limit')
        self.assertEqual(planner.eligibility('proactive', self.prefs(), flags=scoped.public(), **{**args, 'active_calls': 3}), 'call_active')
        self.assertEqual(planner.eligibility('proactive', self.prefs(), flags=PhoneConfig(values).public(), **args), 'call_active')
        self.assertEqual(planner.eligibility('proactive', {**self.prefs(), 'enabled': False}, flags=scoped.public(), **args), 'calling_off')
        disabled = FounderPhoneConfig({**values, 'RAFII_FOUNDER_PHONE_CONTACT_ALLOWED': False}, OPS, 'founder:incident:abc')
        self.assertEqual(planner.eligibility('proactive', self.prefs(), flags=disabled.public(), **args), 'calling_off')

    @unittest.skipUnless(importlib.util.find_spec("cryptography"), "cryptography (consumer requirements) required for the phone credential vault")
    def test_principal_phone_passthrough_attaches_scope_only_on_request(self):
        key = 'founder:briefing:' + str(uuid.uuid4())
        values = {'RAFII_PHONE_ENABLED': '1', 'RAFII_PHONE_ENCRYPTION_KEY': CredentialVault.generate_key(), 'RAFII_FOUNDER_OPS_WORKSPACE_ID': OPS}
        hosted = types.SimpleNamespace(repository=object(), clock=lambda: T0)
        phone = types.SimpleNamespace(hosted=hosted, config=PhoneConfig(values), provider=FakeTelephonyProvider(), agent=lambda: None, clock=lambda: T0)
        with patch('postriff_phase2.automation_runs.principal_repository', return_value=(object(), object())) as repo:
            scoped, _capability = principal_phone(phone, OPS, OPERATOR, founder_reason_key=key)
            plain, _capability = principal_phone(phone, OPS, OPERATOR)
            with self.assertRaises(AlphaError):
                principal_phone(phone, OPS, OPERATOR, founder_reason_key='schedule:' + key)
        self.assertEqual(repo.call_args_list[0].args[1:], (OPS, OPERATOR, 'edit'))
        self.assertEqual(scoped.config.public()['founder'], {'workspaceId': OPS, 'opsWorkspaceId': OPS, 'reasonKey': key,
                         'automaticCallsDaily': 2, 'concurrentCalls': 1, 'quietStart': 1320, 'quietEnd': 480,
                         'timeZone': 'America/Indiana/Indianapolis', 'callingAllowed': True})
        self.assertNotIn('founder', plain.config.public())
        self.assertTrue(scoped.config.enabled('RAFII_PHONE_ENABLED'))


class IncidentCallAckTests(unittest.TestCase):
    """(a) incident → policy → attempt → fake call → ack cancels escalation; disabled policy → suppressed with reason."""
    def setUp(self):
        self.fstore = MemoryFounderStore()
        self.fstore.destinations[OPERATOR] = True
        self.calls = FakeCalls()
        self.flags = {FLAG: '1'}

    def test_disabled_policy_suppresses_with_reason_and_never_dials(self):
        incident = critical_incident(self.fstore)
        attempt, decision, created = founder_contact.contact(self.fstore, self.calls, OPERATOR, 'incident', incident['id'], T0, flags=self.flags)
        self.assertTrue(created)
        self.assertEqual((attempt['state'], decision['reason'], attempt['outcome']['detail']), ('suppressed', 'POLICY_DISABLED', 'live_delivery_disabled'))
        self.assertEqual(self.calls.provider.create_count, 0)
        self.fstore.save_policy(OPERATOR, enabled_policy(), T0)
        again, decision, created = founder_contact.contact(self.fstore, self.calls, OPERATOR, 'incident', incident['id'], T0 + 60, flags={})
        self.assertFalse(created)
        self.assertEqual(again['id'], attempt['id'], 'one attempt per incident; the policy change does not re-plan it')
        other = critical_incident(self.fstore, T0 + 1, scope='other')
        flagged, decision, _ = founder_contact.contact(self.fstore, self.calls, OPERATOR, 'incident', other['id'], T0 + 60, flags={})
        self.assertEqual((flagged['state'], decision['detail']), ('suppressed', 'deployment_flag_unset'))
        self.assertEqual(self.calls.provider.create_count, 0)

    def test_incident_call_answered_then_ack_cancels_pending_escalation(self):
        self.fstore.save_policy(OPERATOR, enabled_policy(), T0)
        incident = critical_incident(self.fstore)
        attempt, decision, created = founder_contact.contact(self.fstore, self.calls, OPERATOR, 'incident', incident['id'], T0, flags=self.flags)
        self.assertEqual(decision['reason'], 'OK')
        self.assertEqual((attempt['state'], attempt['provider'], attempt['idempotency_key']), ('ringing', 'fake', 'founder:incident:' + incident['id']))
        self.assertEqual(self.calls.provider.create_count, 1)
        # The dial is on the admin audit trail as founder.call.request (CONTRACTS §3): ids and outcome, nothing else.
        self.assertEqual(self.fstore.audit_rows, [{'action': 'founder.call.request', 'result': 'succeeded', 'actor': OPERATOR, 'request_id': attempt['id'],
                                                    'environment': 'local', 'error_code': None}])
        self.assertEqual(self.calls.calls[attempt['phone_call_id']]['kind'], 'proactive')
        # The fake provider answers; reconcile copies the ledger state onto the attempt.
        self.calls.provider_state(attempt['phone_call_id'], 'answered')
        settled = founder_contact.reconcile_attempts(self.fstore, self.calls, T0 + 30, operator_id=OPERATOR)
        self.assertEqual([a['state'] for a in settled], ['answered'])
        # A second critical incident is reserved but not yet dialed (the concurrent cap holds it): the ack cancels it.
        second = critical_incident(self.fstore, T0 + 5, scope='second')
        decision = plan_contact(enabled_policy(), 'incident', T0 + 40, ready_state())
        pending, created = reserve_contact(self.fstore, OPERATOR, 'incident', second['id'], T0 + 40, decision, estimate_usd_micro=20_000)
        self.assertEqual((created, pending['state']), (True, 'reserved'))
        result = founder_incidents.acknowledge(self.fstore, second['id'], 1, OPERATOR, now=T0 + 50, channel='web')
        self.assertEqual((result['cancelledAttempts'], result['incident']['state'], result['incident']['version']), (1, 'acknowledged', 2))
        self.assertEqual(self.fstore.attempt_by_key(pending['idempotency_key'])['state'], 'cancelled')
        self.assertIn('contact_cancelled', [e['kind'] for e in result['incident']['timeline']])
        self.assertEqual(founder_incidents.escalations_due(self.fstore), [self.fstore.incident(incident['id'])], 'an acknowledged incident no longer escalates')
        replay = founder_incidents.acknowledge(self.fstore, second['id'], 1, OPERATOR, now=T0 + 60)
        self.assertTrue(replay['replayed'])
        with self.assertRaises(ControlError) as stale:
            founder_incidents.acknowledge(self.fstore, second['id'], 1 + 5, OPERATOR, now=T0 + 70)
        self.assertEqual(stale.exception.code, 'STALE_PREVIEW')
        # The answered call completes; the attempt reaches the terminal ledger state and is never redialed.
        self.calls.provider_state(attempt['phone_call_id'], 'completed')
        founder_contact.reconcile_attempts(self.fstore, self.calls, T0 + 90, operator_id=OPERATOR)
        self.assertEqual(self.fstore.attempt_by_key(attempt['idempotency_key'])['state'], 'completed')
        self.assertEqual(self.calls.provider.create_count, 1)

    def test_phone_product_refusal_is_a_suppression_with_its_code(self):
        self.fstore.save_policy(OPERATOR, enabled_policy(), T0)
        incident = critical_incident(self.fstore)
        calls = FakeCalls(prefs={'proactiveCalls': False})
        attempt, decision, _ = founder_contact.contact(self.fstore, calls, OPERATOR, 'incident', incident['id'], T0, flags=self.flags)
        self.assertEqual((decision['reason'], attempt['state'], attempt['outcome']['reason']), ('OK', 'suppressed', 'proactive_off'))
        self.assertEqual(calls.provider.create_count, 0)
        self.assertEqual([(row['result'], row['error_code']) for row in self.fstore.audit_rows], [('denied', 'proactive_off')])
        wrong_workspace = FakeCalls(workspace_id=OTHER)
        other = critical_incident(self.fstore, T0 + 1, scope='other')
        attempt, _, _ = founder_contact.contact(self.fstore, wrong_workspace, OPERATOR, 'incident', other['id'], T0, flags=self.flags)
        self.assertEqual((attempt['state'], attempt['outcome']['reason']), ('suppressed', 'event_not_allowed'))

    def test_crash_windows_reconcile_without_a_second_dial(self):
        self.fstore.save_policy(OPERATOR, enabled_policy(), T0)
        # Crash between reserve and dispatch: the reservation is re-sent once, after the grace period.
        first = critical_incident(self.fstore)
        decision = plan_contact(enabled_policy(), 'incident', T0, ready_state())
        reserved, _ = reserve_contact(self.fstore, OPERATOR, 'incident', first['id'], T0, decision, estimate_usd_micro=20_000)
        self.assertEqual(founder_contact.reconcile_attempts(self.fstore, self.calls, T0 + 10, operator_id=OPERATOR), [])
        settled = founder_contact.reconcile_attempts(self.fstore, self.calls, T0 + 61, operator_id=OPERATOR)
        self.assertEqual([a['state'] for a in settled], ['ringing'])
        self.assertEqual(self.calls.provider.create_count, 1)
        founder_contact.reconcile_attempts(self.fstore, self.calls, T0 + 200, operator_id=OPERATOR)
        self.assertEqual(self.calls.provider.create_count, 1)
        self.calls.provider_state(reserved['phone_call_id'] or self.calls.by_key[reserved['idempotency_key']], 'completed')
        founder_contact.reconcile_attempts(self.fstore, self.calls, T0 + 300, operator_id=OPERATOR)
        # Crash inside the request after the claim was committed: the same key replays the existing call.
        second = critical_incident(self.fstore, T0 + 1, scope='second')
        self.calls.crash_after_create = True
        attempt, _, _ = founder_contact.contact(self.fstore, self.calls, OPERATOR, 'incident', second['id'], T0 + 400, flags=self.flags)
        self.assertEqual((attempt['state'], attempt['phone_call_id'], attempt['outcome']['reason']), ('ambiguous', None, 'dispatch_interrupted'))
        self.assertEqual(self.calls.provider.create_count, 2)
        settled = founder_contact.reconcile_attempts(self.fstore, self.calls, T0 + 470, operator_id=OPERATOR)
        self.assertEqual([(a['state'], a['phone_call_id'] is not None) for a in settled], [('ringing', True)])
        self.assertEqual(self.calls.provider.create_count, 2, 'the replayed key never dials again')
        self.assertEqual(self.calls.requests.count(attempt['idempotency_key']), 2)

    def test_test_call_is_policy_disabled_until_everything_is_on(self):
        body = {'requestId': str(uuid.uuid4())}
        with self.assertRaises(ControlError) as denied:
            founder_contact.test_call(self.fstore, PRINCIPAL, body, now=T0, flags=self.flags, calls=self.calls)
        self.assertEqual((denied.exception.code, denied.exception.status), ('POLICY_DISABLED', 409))
        self.fstore.save_policy(OPERATOR, enabled_policy(), T0)
        with self.assertRaises(ControlError):
            founder_contact.test_call(self.fstore, PRINCIPAL, body, now=T0, flags={}, calls=self.calls)
        with self.assertRaises(ControlError):
            founder_contact.test_call(self.fstore, PRINCIPAL, body, now=T0, flags=self.flags, calls=None)
        with self.assertRaises(ControlError):
            founder_contact.test_call(self.fstore, PRINCIPAL, {'requestId': 'not-a-uuid'}, now=T0, flags=self.flags, calls=self.calls)
        result = founder_contact.test_call(self.fstore, PRINCIPAL, body, now=T0, flags=self.flags, calls=self.calls)
        self.assertEqual((result['attempt']['purpose'], result['attempt']['state']), ('test', 'ringing'))
        self.assertEqual(self.calls.calls[result['attempt']['phoneCallId']]['kind'], 'explicit')
        self.assertEqual(founder_contact.test_call(self.fstore, PRINCIPAL, body, now=T0 + 1, flags=self.flags, calls=self.calls)['attempt']['id'],
                         result['attempt']['id'], 'the same request id replays the attempt')
        listed = founder_contact.list_attempts(self.fstore, PRINCIPAL)['attempts']
        self.assertEqual([a['purpose'] for a in listed], ['test'])


class InboundAndPlaybackTests(unittest.TestCase):
    """(b) inbound requirements and the founder playback scope, unit-level with fake sessions."""
    def test_inbound_requires_dial_provider_rates_and_flags(self):
        values = {flag: '1' for flag in contracts.FLAGS}
        fake = types.SimpleNamespace(config=PhoneConfig({**values, 'RAFII_PHONE_USD_MICRO_PER_MINUTE': '10000'}), provider=FakeTelephonyProvider())
        self.assertFalse(inbound.available(fake), 'the fake provider never offers dial-in')
        dial = types.SimpleNamespace(name='dial', configured=True, real=True)
        ready = types.SimpleNamespace(config=PhoneConfig({**values, 'RAFII_PHONE_USD_MICRO_PER_MINUTE': '10000'}), provider=dial)
        self.assertTrue(inbound.available(ready))
        self.assertFalse(inbound.available(types.SimpleNamespace(config=PhoneConfig({**values, 'RAFII_PHONE_INBOUND_ENABLED': '0', 'RAFII_PHONE_USD_MICRO_PER_MINUTE': '10000'}), provider=dial)))
        self.assertFalse(inbound.available(types.SimpleNamespace(config=PhoneConfig(values), provider=dial)), 'a telephony rate is required')
        with self.assertRaises(AlphaError) as refused:
            inbound.require_available(fake)
        self.assertEqual(refused.exception.code, 'inbound_disabled')

    def test_playback_reads_report_or_incident_through_reader_scope_only(self):
        report_id, incident_id = str(uuid.uuid4()), str(uuid.uuid4())
        seen = []

        class Reader:
            environment = 'local'

            @contextmanager
            def transaction(self, read=False):
                seen.append(read)
                yield self

            def execute(self, sql, params):
                self.sql, self.params = sql, params
                return self

            def fetchone(self):
                if 'founder_reports' in self.sql and self.params[0] == report_id:
                    return {'text': 'Founder daily briefing · recorded values only.'}
                if 'founder_incidents' in self.sql and self.params[0] == incident_id:
                    return {'id': incident_id, 'detector': 'cost_anomaly', 'scope': 'global', 'severity': 'critical', 'state': 'open', 'opened_at': T0,
                            'evidence': {'todayUsdMicro': 9_000_000, 'thresholdVersion': 1}, 'affected_count': 1}
                return None

        reader = Reader()
        self.assertEqual(playback_text({}, 'founder:briefing:' + report_id, reader=reader), 'Founder daily briefing · recorded values only.')
        self.assertTrue(all(seen), 'playback uses read-only transactions')
        spoken = playback_text({}, 'founder:incident:' + incident_id, reader=reader)
        self.assertIn('cost_anomaly', spoken)
        self.assertIn('todayUsdMicro 9000000', spoken)
        self.assertNotIn('thresholdVersion', spoken)
        self.assertIsNone(playback_text({}, 'founder:briefing:' + str(uuid.uuid4()), reader=reader))
        for key in ('schedule:' + report_id, 'founder:test:' + report_id, 'founder:briefing:not-a-uuid', ''):
            self.assertIsNone(playback_text({}, key, reader=reader), key)
        self.assertIsNone(playback_text({'RAFII_CONTROL_ENABLED': '1'}, 'founder:briefing:' + report_id), 'no reader DSN → no playback, no fallback read')

    def test_session_prompt_is_guarded_and_scoped_to_the_prepared_text(self):
        controller = types.SimpleNamespace(service=types.SimpleNamespace(config=PhoneConfig({})), call={'reason_key': 'founder:briefing:' + str(uuid.uuid4())})
        self.assertEqual(founder_playback_prompt(controller), FOUNDER_PLAYBACK_UNAVAILABLE)
        with patch('rafii_control.founder_briefings.playback_text', return_value='Recorded: 3 verified publications.'):
            prompt = founder_playback_prompt(controller)
        self.assertIn('Recorded: 3 verified publications.', prompt)
        self.assertIn('do not compute new totals', prompt)
        self.assertIn('do not publish, schedule or spend', prompt)
        with patch('rafii_control.founder_briefings.playback_text', side_effect=RuntimeError('store down')):
            self.assertEqual(founder_playback_prompt(controller), FOUNDER_PLAYBACK_UNAVAILABLE)


class StoreSurfaceTests(unittest.TestCase):
    def test_memory_store_covers_the_postgres_store_surface(self):
        expected = {name for name in dir(PostgresFounderStore) if not name.startswith('_') and callable(getattr(PostgresFounderStore, name))}
        provided = {name for name in dir(MemoryFounderStore) if callable(getattr(MemoryFounderStore, name))}
        self.assertEqual(expected - provided, set())
        self.assertEqual(set(founder_contact.REASONS), {'POLICY_DISABLED', 'CONSENT_REQUIRED', 'NUMBER_UNVERIFIED', 'TIME_NOT_SELECTED', 'BUDGET_NOT_APPROVED',
                                                        'QUIET_HOURS', 'DAILY_CAP', 'CALL_ACTIVE', 'OK'})
        self.assertTrue(ACTIVE_STATES <= set(founder_contact.PLANNING_STATES) | set(contracts.STATES))


if __name__ == '__main__':
    unittest.main()
