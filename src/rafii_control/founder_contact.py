"""Founder contact policy and outbound contact attempts (Founder Admin v2, CONTRACTS §5).

Boundaries. The policy is deterministic code: no model chooses a destination, a time, a severity or a channel. A call
leaves this module only through `PhoneCalls`, which dials via `postriff_phase2.phone.service.PhoneService.request`
for the ops workspace as the operator (`phone.runtime.principal_phone(..., founder_reason_key=...)`), so every existing
phone invariant still applies: verified number, membership, provider and Live configuration, budgets, quiet hours,
one committed claim per request, ambiguous outcomes reconciled and never redialed. Everything defaults OFF:
`live_delivery_enabled=false` and an unset `RAFII_FOUNDER_CALLS_ENABLED` end every attempt 'suppressed' with a reason.
Demo mode never reaches this module (`founder_preview_delivery` simulates it); it is never a Live fallback.

Persistence goes through a founder store object (`founder_cron.PostgresFounderStore` in production, an in-memory store
in tests) whose contact methods are implemented by `ContactSQL` below.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError
from postriff_phase2.notifications.planner import in_quiet_hours
from postriff_phase2.phone import planner as phone_planner
from postriff_phase2.phone.contracts import FOUNDER_REASON_PREFIX, TERMINAL
from psycopg.types.json import Jsonb

from .auth import ControlError

PURPOSES = ('incident', 'briefing', 'test')
PURPOSE_EVENTS = {'incident': 'founder.incident', 'briefing': 'founder.briefing'}
# PhoneService kind and event per purpose. A test call is explicit (founder-initiated), so the phone planner applies no
# quiet hours or automatic daily limit to it; the founder policy still gates it.
PURPOSE_KINDS = {'incident': ('proactive', 'founder.incident'), 'briefing': ('scheduled', None), 'test': ('explicit', None)}
CHANNELS = ('call', 'email', 'push')
EVENT_CHOICES = tuple(PURPOSE_EVENTS.values())
REASONS = ('POLICY_DISABLED', 'CONSENT_REQUIRED', 'NUMBER_UNVERIFIED', 'TIME_NOT_SELECTED', 'BUDGET_NOT_APPROVED',
           'QUIET_HOURS', 'DAILY_CAP', 'CALL_ACTIVE', 'OK')
FLAG = 'RAFII_FOUNDER_CALLS_ENABLED'
# admin_audit_log action for every dial decision the attempt ledger records (CONTRACTS §3); content-free.
AUDIT_ACTION = 'founder.call.request'
log = logging.getLogger('rafii_control.founder_contact')
MAX_BUDGET_USD_MICRO = 50_000_000
CALL_MAX_SECONDS = 300
# Attempt states beyond phone.contracts.STATES: planned/eligible (policy evaluated), reserved (row committed, not yet
# dialed), suppressed (policy or phone product refused; nothing was dialed).
PLANNING_STATES = ('planned', 'eligible', 'reserved', 'suppressed')
ACTIVE_STATES = frozenset(('reserved', 'requested', 'dialing', 'ringing', 'answered', 'live', 'ending', 'ambiguous'))
COUNTED_STATES = frozenset(('requested', 'dialing', 'ringing', 'answered', 'live', 'ending', 'ambiguous')) | TERMINAL - {'cancelled'}
RECONCILE_AFTER_SECONDS = 60
_SOURCE_ID = re.compile(r'[A-Za-z0-9_-]{1,80}\Z')

DEFAULT_POLICY = {'revision': 0, 'live_delivery_enabled': False, 'channels': [], 'destination_ref': None, 'quiet_start': 1320,
                  'quiet_end': 480, 'time_zone': 'America/Indiana/Indianapolis', 'daily_cap': 2, 'concurrent_cap': 1,
                  'event_allowlist': [], 'budget_usd_micro_daily': 0, 'updated_at': None}
_PUBLIC = {'liveDeliveryEnabled': 'live_delivery_enabled', 'channels': 'channels', 'destinationRef': 'destination_ref',
           'quietStart': 'quiet_start', 'quietEnd': 'quiet_end', 'timeZone': 'time_zone', 'dailyCap': 'daily_cap',
           'concurrentCap': 'concurrent_cap', 'eventAllowlist': 'event_allowlist', 'budgetUsdMicroDaily': 'budget_usd_micro_daily'}


def truthy(value):
    return str(value if value is not None else '').lower() in ('1', 'true', 'yes', 'on')


def destination_ref(operator_id):
    """The only destination a founder policy may name: the operator's own verified phone row."""
    return 'pr_phone_numbers:' + str(operator_id)


def reason_key(purpose, source_id):
    if purpose not in PURPOSES or not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
        raise ControlError('VALIDATION_FAILED', 400)
    return f'{FOUNDER_REASON_PREFIX}{purpose}:{source_id}'


# --- policy --------------------------------------------------------------------------------------------------------------
def validate_policy(body, current, operator_id):
    """Merge a camelCase patch over the current policy and validate every field. Enabling live delivery never bypasses
    the per-attempt gates: it is one of them."""
    if not isinstance(body, dict) or set(body) - set(_PUBLIC):
        raise ControlError('VALIDATION_FAILED', 400)
    out = {**DEFAULT_POLICY, **(current or {})}
    out.update({_PUBLIC[key]: value for key, value in body.items()})
    if not isinstance(out['live_delivery_enabled'], bool):
        raise ControlError('VALIDATION_FAILED', 400)
    channels, allowlist = out['channels'], out['event_allowlist']
    if not isinstance(channels, list) or any(c not in CHANNELS for c in channels):
        raise ControlError('VALIDATION_FAILED', 400)
    if not isinstance(allowlist, list) or any(e not in EVENT_CHOICES for e in allowlist):
        raise ControlError('VALIDATION_FAILED', 400)
    out['channels'] = [c for c in CHANNELS if c in channels]
    out['event_allowlist'] = [e for e in EVENT_CHOICES if e in allowlist]
    ref = out['destination_ref']
    if ref is not None and ref != destination_ref(operator_id):
        raise ControlError('VALIDATION_FAILED', 400)
    for key, low, high in (('quiet_start', 0, 1439), ('quiet_end', 0, 1439), ('daily_cap', 0, 2), ('concurrent_cap', 0, 1),
                           ('budget_usd_micro_daily', 0, MAX_BUDGET_USD_MICRO)):
        if type(out[key]) is not int or not low <= out[key] <= high:
            raise ControlError('VALIDATION_FAILED', 400)
    zone = out['time_zone']
    try:
        if not isinstance(zone, str) or not 1 <= len(zone) <= 64:
            raise ValueError
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ControlError('VALIDATION_FAILED', 400) from None
    return out


def public_policy(policy):
    return {key: policy.get(field) for key, field in _PUBLIC.items()} | {'revision': policy.get('revision', 0), 'updatedAt': policy.get('updated_at')}


def load_policy(fstore, operator_id):
    return fstore.policy(operator_id) or dict(DEFAULT_POLICY)


def get_policy(fstore, principal, *, now, flags=None):
    """GET /contact-policy: the policy, the verified destination state and the blockers an incident call would meet now."""
    operator = principal['operator']['user_id']
    policy = load_policy(fstore, operator)
    verified = fstore.destination_verified(operator)
    state = contact_state(fstore, operator, policy, now, flags=flags or {}, verified=bool(verified), estimate_usd_micro=0)
    return {'policy': public_policy(policy), 'destination': {'ref': destination_ref(operator), 'verified': bool(verified)},
            'readiness': {purpose: plan_contact(policy, purpose, now, {**state, 'scheduled_at': now}) for purpose in PURPOSES},
            'flags': {'founderCallsEnabled': truthy((flags or {}).get(FLAG))}}


def put_policy(fstore, principal, body, *, now):
    """PUT /contact-policy (capability control.settings + step_up): validate, bump the revision, return the saved policy."""
    operator = principal['operator']['user_id']
    policy = validate_policy(body, fstore.policy(operator), operator)
    return {'policy': public_policy(fstore.save_policy(operator, policy, now))}


# --- deterministic planning -----------------------------------------------------------------------------------------------
def _decision(reason, detail, purpose, now):
    if reason not in REASONS:
        raise ValueError(reason)
    return {'decision': reason, 'reason': reason, 'detail': detail, 'purpose': purpose, 'at': now}


def plan_contact(policy, purpose, now, state):
    """Decide one contact. `state` = {flags, verified, daily_calls, active_calls, reserved_usd_micro, estimate_usd_micro,
    scheduled_at}. The first failing gate names the reason; only 'OK' permits a reservation. Pure: no clock, no I/O."""
    if purpose not in PURPOSES:
        raise ControlError('VALIDATION_FAILED', 400)
    flags = state.get('flags') or {}
    if not policy.get('live_delivery_enabled'):
        return _decision('POLICY_DISABLED', 'live_delivery_disabled', purpose, now)
    if not truthy(flags.get(FLAG)):
        return _decision('POLICY_DISABLED', 'deployment_flag_unset', purpose, now)
    if purpose != 'test' and PURPOSE_EVENTS[purpose] not in (policy.get('event_allowlist') or []):
        return _decision('POLICY_DISABLED', 'event_not_allowed', purpose, now)
    if 'call' not in (policy.get('channels') or []):
        return _decision('CONSENT_REQUIRED', 'call_channel_not_consented', purpose, now)
    if not policy.get('destination_ref'):
        return _decision('NUMBER_UNVERIFIED', 'no_destination', purpose, now)
    if not state.get('verified'):
        return _decision('NUMBER_UNVERIFIED', 'destination_not_verified', purpose, now)
    try:
        ZoneInfo(policy.get('time_zone') or '')
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return _decision('TIME_NOT_SELECTED', 'time_zone_invalid', purpose, now)
    if purpose == 'briefing' and not state.get('scheduled_at'):
        return _decision('TIME_NOT_SELECTED', 'no_schedule', purpose, now)
    budget = int(policy.get('budget_usd_micro_daily') or 0)
    if budget <= 0:
        return _decision('BUDGET_NOT_APPROVED', 'no_daily_budget', purpose, now)
    if int(state.get('reserved_usd_micro') or 0) + int(state.get('estimate_usd_micro') or 0) > budget:
        return _decision('BUDGET_NOT_APPROVED', 'daily_budget_exhausted', purpose, now)
    quiet = {'quiet_start': policy['quiet_start'], 'quiet_end': policy['quiet_end'], 'time_zone': policy['time_zone']}
    if purpose != 'test' and in_quiet_hours(now, quiet):
        return _decision('QUIET_HOURS', 'inside_quiet_hours', purpose, now)
    if purpose != 'test' and int(state.get('daily_calls') or 0) >= int(policy.get('daily_cap') or 0):
        return _decision('DAILY_CAP', 'daily_cap_reached', purpose, now)
    if int(state.get('active_calls') or 0) >= int(policy.get('concurrent_cap') or 0):
        return _decision('CALL_ACTIVE', 'concurrent_cap_reached', purpose, now)
    return _decision('OK', 'eligible', purpose, now)


def contact_state(fstore, operator_id, policy, now, *, flags, verified, estimate_usd_micro, scheduled_at=None):
    """The observed inputs of plan_contact for this operator today (policy time zone), from the attempt ledger."""
    try:
        start = phone_planner.day_start(now, policy.get('time_zone') or 'UTC')
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        start = now - 86400
    today = fstore.attempts(operator_id, since=start)
    counted = [a for a in today if a['state'] in COUNTED_STATES]
    active = [a for a in fstore.attempts(operator_id) if a['state'] in ACTIVE_STATES]
    return {'flags': dict(flags or {}), 'verified': bool(verified), 'daily_calls': len(counted), 'active_calls': len(active),
            'reserved_usd_micro': sum(int(a.get('reserved_usd_micro') or 0) for a in counted + [a for a in active if a['state'] == 'reserved']),
            'estimate_usd_micro': int(estimate_usd_micro or 0), 'scheduled_at': scheduled_at}


# --- attempts ---------------------------------------------------------------------------------------------------------------
def reserve_contact(fstore, operator_id, purpose, source_id, now, decision, *, estimate_usd_micro=0, policy_revision=0):
    """Commit one attempt row per (purpose, source). Replays return the existing row untouched: a reservation is the
    single claim that may ever dial for this source."""
    key = reason_key(purpose, source_id)
    existing = fstore.attempt_by_key(key)
    if existing:
        return existing, False
    allowed = decision['decision'] == 'OK'
    row = {'id': str(uuid.uuid4()), 'operator_id': operator_id, 'environment': fstore.environment, 'purpose': purpose,
           'source_id': source_id, 'idempotency_key': key, 'state': 'reserved' if allowed else 'suppressed', 'provider': None,
           'provider_call_ref': None, 'phone_call_id': None, 'reserved_usd_micro': int(estimate_usd_micro or 0) if allowed else 0,
           'outcome': {'decision': decision['decision'], 'detail': decision['detail'], 'policyRevision': policy_revision},
           'created_at': now, 'updated_at': now}
    stored = fstore.insert_attempt(row)
    return stored, stored['id'] == row['id']


def _sync(fstore, attempt, call, now):
    """Copy the phone product's view of the call onto the attempt. Only ids, states and the curated failure class."""
    outcome = {**attempt.get('outcome', {}), 'failure': call.get('failure'), 'execution': call.get('execution')}
    return fstore.update_attempt(attempt['id'], state=call['state'], phone_call_id=call['id'], provider=call.get('provider'),
                                 outcome=outcome, updated_at=now)


def audit_dial(fstore, attempt, result, *, error_code=None):
    """Record the dial decision in admin_audit_log as `founder.call.request` (request id = the attempt id, actor = the
    operator, outcome only). The attempt ledger stays authoritative, so an unavailable audit store is logged, not raised."""
    audit = getattr(fstore, 'audit', None)
    if audit is None:
        return
    try:
        audit(AUDIT_ACTION, result, attempt['operator_id'], attempt['id'], error_code=error_code)
    except Exception as error:  # noqa: BLE001 - the audit trail never decides whether a dial happened
        log.warning(json.dumps({'event': 'founder_contact.audit_unavailable', 'action': AUDIT_ACTION, 'result': result, 'error': type(error).__name__}))


def dispatch_contact(fstore, calls, attempt, now):
    """Dial a reserved attempt once. A refusal by the phone product is a suppression with its curated code; an
    interrupted request keeps the reservation as 'ambiguous' so reconcile re-sends the same idempotency key, which
    PhoneService answers with the existing call rather than a second dial. Every outcome is audited (`audit_dial`)."""
    if attempt['state'] != 'reserved':
        return attempt
    if calls is None:
        attempt = fstore.update_attempt(attempt['id'], state='suppressed', updated_at=now,
                                        outcome={**attempt.get('outcome', {}), 'reason': 'provider_unavailable'})
        audit_dial(fstore, attempt, 'denied', error_code='provider_unavailable')
        return attempt
    try:
        call = calls.request(attempt)
    except AlphaError as error:
        code = getattr(error, 'code', None) or 'phone_rejected'
        attempt = fstore.update_attempt(attempt['id'], state='suppressed', updated_at=now,
                                        outcome={**attempt.get('outcome', {}), 'reason': code, 'message': str(error)[:200]})
        audit_dial(fstore, attempt, 'denied', error_code=str(code)[:64])
        return attempt
    except Exception:
        attempt = fstore.update_attempt(attempt['id'], state='ambiguous', updated_at=now,
                                        outcome={**attempt.get('outcome', {}), 'reason': 'dispatch_interrupted'})
        audit_dial(fstore, attempt, 'failed', error_code='dispatch_interrupted')
        return attempt
    attempt = _sync(fstore, attempt, call, now)
    audit_dial(fstore, attempt, 'succeeded')
    return attempt


def reconcile_attempts(fstore, calls, now, *, operator_id=None):
    """Settle open attempts from the phone ledger. Never dials a second time: an attempt without a call id is re-sent
    with its original idempotency key only after RECONCILE_AFTER_SECONDS, and PhoneService replays an existing call."""
    settled = []
    for attempt in fstore.attempts(operator_id, states=ACTIVE_STATES):
        if not attempt.get('phone_call_id'):
            if now - float(attempt['updated_at']) < RECONCILE_AFTER_SECONDS:
                continue
            if attempt['state'] == 'ambiguous':
                attempt = fstore.update_attempt(attempt['id'], state='reserved', updated_at=attempt['updated_at'])
            settled.append(dispatch_contact(fstore, calls, attempt, now))
            continue
        if calls is None:
            continue
        try:
            call = calls.reconcile(attempt['phone_call_id'])
        except Exception:
            continue
        if call and call['state'] != attempt['state']:
            settled.append(_sync(fstore, attempt, call, now))
    return settled


def public_attempt(attempt):
    return {'id': attempt['id'], 'purpose': attempt['purpose'], 'sourceId': attempt['source_id'], 'state': attempt['state'],
            'provider': attempt.get('provider'), 'phoneCallId': attempt.get('phone_call_id'),
            'reservedUsdMicro': int(attempt.get('reserved_usd_micro') or 0), 'outcome': dict(attempt.get('outcome') or {}),
            'createdAt': float(attempt['created_at']), 'updatedAt': float(attempt['updated_at'])}


def list_attempts(fstore, principal, *, limit=50):
    rows = fstore.attempts(principal['operator']['user_id'])
    return {'attempts': [public_attempt(a) for a in rows[:max(1, min(int(limit), 200))]]}


# --- one contact end to end ---------------------------------------------------------------------------------------------
def contact(fstore, calls, operator_id, purpose, source_id, now, *, flags, scheduled_at=None):
    """plan → reserve → dispatch for one source. Returns (attempt, decision, created). Idempotent per (purpose, source):
    a replay returns the existing attempt and its recorded decision without planning or dialing again."""
    existing = fstore.attempt_by_key(reason_key(purpose, source_id))
    if existing:
        outcome = existing.get('outcome') or {}
        return existing, _decision(outcome.get('decision') or 'OK', outcome.get('detail') or 'replayed', purpose, now), False
    policy = load_policy(fstore, operator_id)
    estimate = calls.estimate_usd_micro() if calls is not None else 0
    verified = fstore.destination_verified(operator_id) if policy.get('destination_ref') else False
    state = contact_state(fstore, operator_id, policy, now, flags=flags, verified=verified, estimate_usd_micro=estimate, scheduled_at=scheduled_at)
    decision = plan_contact(policy, purpose, now, state)
    attempt, created = reserve_contact(fstore, operator_id, purpose, source_id, now, decision, estimate_usd_micro=estimate,
                                       policy_revision=policy.get('revision', 0))
    if created and attempt['state'] == 'reserved':
        attempt = dispatch_contact(fstore, calls, attempt, now)
    return attempt, decision, created


def test_call(fstore, principal, body, *, now, flags, calls):
    """POST /calls/test (control.settings + step_up). 409 POLICY_DISABLED unless the policy enables live delivery, the
    deployment flag is on and a configured provider exists; the attempt itself still passes every gate."""
    if not isinstance(body, dict) or set(body) - {'requestId'}:
        raise ControlError('VALIDATION_FAILED', 400)
    try:
        source_id = str(uuid.UUID(str(body.get('requestId'))))
    except (ValueError, TypeError):
        raise ControlError('VALIDATION_FAILED', 400) from None
    operator = principal['operator']['user_id']
    policy = load_policy(fstore, operator)
    if not policy.get('live_delivery_enabled') or not truthy(flags.get(FLAG)) or calls is None or not calls.configured():
        raise ControlError('POLICY_DISABLED', 409)
    attempt, decision, created = contact(fstore, calls, operator, 'test', source_id, now, flags=flags)
    if decision['decision'] != 'OK' or attempt['state'] == 'suppressed':
        raise ControlError('POLICY_DISABLED', 409)
    return {'attempt': public_attempt(attempt), 'decision': decision, 'replayed': not created}


# --- the only path to a real call -----------------------------------------------------------------------------------------
class PhoneCalls:
    """Live adapter over the phone product for one operator in the ops workspace. No number, provider body or audio is
    read here; the phone ledger (`public.pr_phone_calls`) stays the source of truth for call state."""
    def __init__(self, phone, ops_workspace_id, operator_id):
        self.phone, self.workspace_id, self.operator_id = phone, ops_workspace_id, operator_id

    def configured(self):
        provider = getattr(self.phone, 'provider', None)
        return bool(self.phone and self.workspace_id and provider and provider.configured)

    def estimate_usd_micro(self, max_seconds=CALL_MAX_SECONDS):
        from postriff_phase2.phone import billing
        try:
            return int(sum(billing.estimates(self.phone, seconds=max_seconds)))
        except Exception:
            return 0

    def _scoped(self, reason_key_value):
        from postriff_phase2.phone.runtime import principal_phone
        return principal_phone(self.phone, self.workspace_id, self.operator_id, founder_reason_key=reason_key_value)

    def request(self, attempt):
        scoped, capability = self._scoped(attempt['idempotency_key'])
        kind, event_type = PURPOSE_KINDS[attempt['purpose']]
        return scoped.request(self.workspace_id, capability, {'idempotencyKey': attempt['idempotency_key']}, kind=kind,
                              reason_key=attempt['idempotency_key'], event_type=event_type)

    def read(self, call_id):
        from postriff_phase2.phone import store as phone_store
        with self.phone.hosted.connection_factory() as db, db.cursor() as cur:
            value = phone_store.call(cur, call_id)
        if not value or value['workspace_id'] != self.workspace_id or value['user_id'] != self.operator_id:
            return None
        return phone_store.public_call(value)

    def reconcile(self, call_id):
        from postriff_phase2.phone import delivery
        current = self.read(call_id)
        if current and current['state'] in ('dialing', 'ambiguous', 'ringing', 'ending'):
            delivery.reconcile(self.phone, call_id)
        elif current and current['state'] == 'requested':
            # The request committed its claim but the process stopped before delivery: deliver that same claim once.
            with self.phone.hosted.connection_factory() as db, db.cursor() as cur:
                from postriff_phase2.phone import store as phone_store
                reason = (phone_store.call(cur, call_id) or {}).get('reason_key') or ''
            scoped, _capability = self._scoped(reason)
            delivery.deliver(scoped, call_id)
        return self.read(call_id)


# --- SQL (rafii_control_session role, environment GUC policies; see 055) -----------------------------------------------
_POLICY_COLUMNS = ('operator_id', 'environment', 'revision', 'live_delivery_enabled', 'channels', 'destination_ref', 'quiet_start',
                   'quiet_end', 'time_zone', 'daily_cap', 'concurrent_cap', 'event_allowlist', 'budget_usd_micro_daily')
_POLICY_SELECT = ('SELECT operator_id::text AS operator_id,environment,revision,live_delivery_enabled,channels,destination_ref,quiet_start,'
                  'quiet_end,time_zone,daily_cap,concurrent_cap,event_allowlist,budget_usd_micro_daily,extract(epoch from updated_at) AS updated_at '
                  'FROM rafii_control.founder_contact_policy')
_ATTEMPT_SELECT = ('SELECT id::text,operator_id::text AS operator_id,environment,purpose,source_id,idempotency_key,state,provider,provider_call_ref,'
                   'phone_call_id::text AS phone_call_id,reserved_usd_micro,outcome,extract(epoch from created_at) AS created_at,'
                   'extract(epoch from updated_at) AS updated_at FROM rafii_control.founder_contact_attempts')
_ATTEMPT_FIELDS = frozenset(('state', 'provider', 'provider_call_ref', 'phone_call_id', 'reserved_usd_micro', 'outcome', 'updated_at'))


def _policy_row(row):
    return {**row, 'channels': list(row['channels'] or []), 'event_allowlist': list(row['event_allowlist'] or []),
            'updated_at': float(row['updated_at']) if row.get('updated_at') is not None else None}


def _attempt_row(row):
    return {**row, 'outcome': dict(row['outcome'] or {}), 'reserved_usd_micro': int(row['reserved_usd_micro'] or 0),
            'created_at': float(row['created_at']), 'updated_at': float(row['updated_at'])}


class ContactSQL:
    """Contact policy, destination and attempt rows. `self.store` is a rafii_control.store.PostgresStore."""

    def policy(self, operator_id):
        with self.store.transaction() as con:
            row = con.execute(_POLICY_SELECT + ' WHERE operator_id=%s AND environment=%s', (operator_id, self.environment)).fetchone()
        return _policy_row(row) if row else None

    def save_policy(self, operator_id, policy, now):
        with self.store.transaction() as con:
            row = con.execute(
                'INSERT INTO rafii_control.founder_contact_policy(operator_id,environment,revision,live_delivery_enabled,channels,destination_ref,'
                'quiet_start,quiet_end,time_zone,daily_cap,concurrent_cap,event_allowlist,budget_usd_micro_daily,updated_at) '
                'VALUES(%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s)) '
                'ON CONFLICT(operator_id,environment) DO UPDATE SET revision=founder_contact_policy.revision+1,live_delivery_enabled=excluded.live_delivery_enabled,'
                'channels=excluded.channels,destination_ref=excluded.destination_ref,quiet_start=excluded.quiet_start,quiet_end=excluded.quiet_end,'
                'time_zone=excluded.time_zone,daily_cap=excluded.daily_cap,concurrent_cap=excluded.concurrent_cap,event_allowlist=excluded.event_allowlist,'
                'budget_usd_micro_daily=excluded.budget_usd_micro_daily,updated_at=excluded.updated_at '
                'RETURNING operator_id::text AS operator_id,environment,revision,live_delivery_enabled,channels,destination_ref,quiet_start,quiet_end,'
                'time_zone,daily_cap,concurrent_cap,event_allowlist,budget_usd_micro_daily,extract(epoch from updated_at) AS updated_at',
                (operator_id, self.environment, policy['live_delivery_enabled'], Jsonb(policy['channels']), policy['destination_ref'],
                 policy['quiet_start'], policy['quiet_end'], policy['time_zone'], policy['daily_cap'], policy['concurrent_cap'],
                 policy['event_allowlist'], policy['budget_usd_micro_daily'], now)).fetchone()
        return _policy_row(row)

    def destination_verified(self, operator_id):
        with self.store.transaction() as con:
            row = con.execute('SELECT verified FROM rafii_control.founder_phone_destinations WHERE "operatorId"=%s', (str(operator_id),)).fetchone()
        return bool(row and row['verified'])

    def attempt_by_key(self, key):
        with self.store.transaction() as con:
            row = con.execute(_ATTEMPT_SELECT + ' WHERE idempotency_key=%s AND environment=%s', (key, self.environment)).fetchone()
        return _attempt_row(row) if row else None

    def insert_attempt(self, row):
        with self.store.transaction() as con:
            con.execute('INSERT INTO rafii_control.founder_contact_attempts(id,operator_id,environment,purpose,source_id,idempotency_key,state,provider,'
                        'provider_call_ref,phone_call_id,reserved_usd_micro,outcome,created_at,updated_at) '
                        'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s)) ON CONFLICT(idempotency_key) DO NOTHING',
                        (row['id'], row['operator_id'], self.environment, row['purpose'], row['source_id'], row['idempotency_key'], row['state'],
                         row['provider'], row['provider_call_ref'], row['phone_call_id'], row['reserved_usd_micro'], Jsonb(row['outcome']),
                         row['created_at'], row['updated_at']))
            stored = con.execute(_ATTEMPT_SELECT + ' WHERE idempotency_key=%s', (row['idempotency_key'],)).fetchone()
        return _attempt_row(stored)

    def update_attempt(self, attempt_id, **fields):
        if set(fields) - _ATTEMPT_FIELDS:
            raise ValueError('unknown attempt field')
        assignments, values = [], []
        for key, value in fields.items():
            assignments.append(f'{key}=to_timestamp(%s)' if key == 'updated_at' else f'{key}=%s')
            values.append(Jsonb(value) if key == 'outcome' else value)
        with self.store.transaction() as con:
            row = con.execute(f'UPDATE rafii_control.founder_contact_attempts SET {",".join(assignments)} WHERE id=%s AND environment=%s '
                              'RETURNING id::text', (*values, attempt_id, self.environment)).fetchone()
            if not row:
                raise ControlError('VALIDATION_FAILED', 404)
            stored = con.execute(_ATTEMPT_SELECT + ' WHERE id=%s', (attempt_id,)).fetchone()
        return _attempt_row(stored)

    def attempts(self, operator_id=None, *, since=None, states=None, source_id=None, limit=500):
        clauses, values = ['environment=%s'], [self.environment]
        if operator_id is not None:
            clauses.append('operator_id=%s'); values.append(operator_id)
        if since is not None:
            clauses.append('created_at>=to_timestamp(%s)'); values.append(since)
        if states is not None:
            clauses.append('state=ANY(%s)'); values.append(sorted(states))
        if source_id is not None:
            clauses.append('source_id=%s'); values.append(source_id)
        values.append(max(1, min(int(limit), 1000)))
        with self.store.transaction() as con:
            rows = con.execute(_ATTEMPT_SELECT + ' WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at DESC LIMIT %s', values).fetchall()
        return [_attempt_row(r) for r in rows]

    def cancel_pending_attempts(self, source_id, reason, now):
        """Reserved attempts that have not reached the provider become cancelled (an acknowledgement stops escalation)."""
        with self.store.transaction() as con:
            rows = con.execute("UPDATE rafii_control.founder_contact_attempts SET state='cancelled',outcome=outcome||%s,updated_at=to_timestamp(%s) "
                               "WHERE environment=%s AND source_id=%s AND state='reserved' AND phone_call_id IS NULL RETURNING id::text",
                               (Jsonb({'reason': reason}), now, self.environment, source_id)).fetchall()
        return len(rows)

    def founder_operators(self):
        with self.store.transaction() as con:
            rows = con.execute("SELECT user_id::text AS user_id FROM rafii_control.platform_operators WHERE environment=%s AND role='founder' "
                               "AND status='active' ORDER BY user_id", (self.environment,)).fetchall()
        return [r['user_id'] for r in rows]
