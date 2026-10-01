"""Founder notices: the founder's in-app centre, email/push behind policy and flags, quiet hours and the daily digest
(Founder Admin P1/P2, CONTRACTS §8.E; PRD §6.7 and §8.7).

Boundaries.

* Events. The four founder notices `founder.incident_opened|incident_recovered|briefing_ready|source_unavailable`
  (`founder_incidents.NOTIFICATION_EVENTS`) and `founder.digest_ready` (the daily digest email) are registered as
  `notifications.catalog.EXTENSION_EVENTS`; `catalog.EVENTS`, which the locked notification-planning policy hashes and the
  customer settings page shows, is never touched. `founder.test_notice` exists only in the founder centre.
* In-app always. Every notice is recorded for each active founder operator in `rafii_control.founder_notices`
  (migration 067; restricted session role, forced RLS) whatever the consumer notification flags say. When the consumer
  outbox is on, the same notice also reaches the founder's personal notification centre through the shared outbox
  (workspace_id=None, user_id=operator: the security-event precedent), payload title/href only.
* Email and push need every gate: the founder contact policy enables live delivery and lists the channel, the deployment
  flag (RAFII_FOUNDER_EMAIL_ENABLED / RAFII_FOUNDER_PUSH_ENABLED, default off) is set, and the founder has not turned the
  channel off for that notice. Routing is deterministic code (PRD §6.7), never a model: critical/security → immediate
  email and push; warning → in-app and the daily digest; recovery → in-app and digest; briefing ready → in-app, push and
  digest. Founder quiet hours hold every channel except for critical/security: held email waits for the digest, held
  push is not sent. The consumer planner then applies its own (stricter) rules to what reaches the outbox.
* Daily digest. The `founder_digest` cron stage gathers, once per founder-local day at or after the digest hour and
  outside quiet hours, every notice planned for the digest into one digest notice; its email passes the same gates.
* Consumer writes are best-effort: one short connection per notice, one SAVEPOINT per operator, and a missing table,
  column or grant reads as "not installed yet" (logged once per process, exception class only). Nothing here raises into
  the cron tick or the caller's transaction, and no content beyond fixed titles, ids, enums and counts is stored.
* Routes (registered at import): GET/PUT /notifications/preferences (control.read / control.settings + step_up),
  GET /notifications, POST /notifications/{id}/read, POST /notifications/test (in-app only), and the report routes of
  founder_briefings (GET /reports, GET /reports/{id}).
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_phase2.notifications.planner import in_quiet_hours
from psycopg.types.json import Jsonb

from . import founder_cron, http
from .auth import ControlError
from .founder_contact import DEFAULT_POLICY, load_policy, truthy
from .live_metrics import MISSING_SOURCE, TIME_ZONE

log = logging.getLogger('rafii_control.founder_notifications')

NOTICE_EVENTS = ('founder.incident_opened', 'founder.incident_recovered', 'founder.briefing_ready', 'founder.source_unavailable')
DIGEST_EVENT = 'founder.digest_ready'
TEST_EVENT = 'founder.test_notice'
EVENT_TYPES = NOTICE_EVENTS + (DIGEST_EVENT, TEST_EVENT)
SEVERITIES = ('info', 'warning', 'critical', 'security')
BREAKS_QUIET = ('critical', 'security')
FLAGS = {'email': 'RAFII_FOUNDER_EMAIL_ENABLED', 'push': 'RAFII_FOUNDER_PUSH_ENABLED'}
# The digest email: one outbox event per founder-local day (catalogue extension; the 'digest' template says urgent items
# were sent straight away).
DIGEST_SPEC = {'category': 'founder', 'severity': 'info', 'audience': 'actor', 'email': 'immediate', 'push': 'off', 'template': 'digest', 'sms': 'off'}
EVENT_LABELS = {'founder.incident_opened': 'Incident opened', 'founder.incident_recovered': 'Incident recovered',
                'founder.briefing_ready': 'Briefing ready', 'founder.source_unavailable': 'Data source unavailable'}
EVENT_SEVERITIES = {'founder.incident_opened': ('warning', 'critical'), 'founder.source_unavailable': ('warning', 'critical'),
                    'founder.incident_recovered': ('info',), 'founder.briefing_ready': ('info',)}
HREFS = {'founder_incident': '/founder/operations?tab=incidents', 'founder_report': '/founder/settings?tab=reports',
         'founder_digest': '/founder/settings?tab=notifications', 'founder_test': '/founder/settings?tab=notifications'}
RETENTION_SECONDS = 400 * 86400
DIGEST_LIMIT = 200
MAX_OPERATORS = 10
DEFAULT_PREFERENCES = {'revision': 0, 'events': {name: {'email': True, 'push': True} for name in NOTICE_EVENTS}, 'digest_enabled': True, 'digest_email': True,
                       'digest_hour': 9, 'quiet_start': 1320, 'quiet_end': 480, 'time_zone': TIME_ZONE, 'updated_at': None}
_ZONE_NAME = re.compile(r'[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+){0,2}\Z')
_UUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z')
_SUBJECT_ID = re.compile(r'[A-Za-z0-9_-]{1,80}\Z')
_LOGGED = set()


class NotInstalled(ControlError):
    """409 POLICY_DISABLED with the fixed blocker `notifications_not_installed` (migration 067 not applied yet)."""

    def __init__(self):
        super().__init__('POLICY_DISABLED', 409)
        self.blocker = 'notifications_not_installed'


def _log_once(event, error):
    """One warning per (event, exception class) per process; never the message, which could carry a DSN or a path."""
    key = (event, type(error).__name__)
    if key in _LOGGED:
        return
    _LOGGED.add(key)
    log.warning(json.dumps({'event': event, 'error': type(error).__name__}, sort_keys=True))


def register_events():
    """The founder notices and the digest email as catalogue extensions (idempotent; catalog.EVENTS stays untouched)."""
    from postriff_phase2.notifications import catalog

    from . import founder_incidents
    founder_incidents.register_notification_events()
    catalog.register_extension_events({DIGEST_EVENT: dict(DIGEST_SPEC)})


def deployment_flags(values=None):
    """The two founder delivery flags from `values` (the cron's environment or Control's RAFII_FOUNDER_* flags), else the
    process environment. Absent means off."""
    source = values if values is not None else os.environ
    return {name: source.get(name) for name in FLAGS.values()}


# --- preferences ---------------------------------------------------------------------------------------------------------------
def merge_preferences(row):
    """A stored preferences row over the defaults; unknown events in storage are ignored, missing ones default on."""
    out = {**DEFAULT_PREFERENCES, 'events': {name: dict(value) for name, value in DEFAULT_PREFERENCES['events'].items()}}
    if not row:
        return out
    for key in ('revision', 'digest_enabled', 'digest_email', 'digest_hour', 'quiet_start', 'quiet_end', 'time_zone', 'updated_at'):
        if row.get(key) is not None:
            out[key] = row[key]
    for name, value in (row.get('events') or {}).items():
        if name in out['events'] and isinstance(value, dict):
            out['events'][name].update({channel: flag for channel, flag in value.items() if channel in ('email', 'push') and isinstance(flag, bool)})
    return out


def public_preferences(prefs):
    return {'revision': int(prefs.get('revision') or 0), 'events': {name: dict(prefs['events'][name]) for name in NOTICE_EVENTS},
            'digest': {'enabled': bool(prefs['digest_enabled']), 'hour': int(prefs['digest_hour']), 'email': bool(prefs['digest_email'])},
            'quietHours': {'start': int(prefs['quiet_start']), 'end': int(prefs['quiet_end']), 'timeZone': prefs['time_zone']},
            'updatedAt': prefs.get('updated_at')}


def _bool(value):
    if type(value) is not bool:
        raise ControlError('VALIDATION_FAILED', 400)
    return value


def _int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ControlError('VALIDATION_FAILED', 400)
    return value


def _section(body, key, allowed):
    value = body[key]
    if not isinstance(value, dict) or not value or set(value) - allowed:
        raise ControlError('VALIDATION_FAILED', 400)
    return value


def validate_preferences(body, current):
    """A camelCase patch {events?, digest?, quietHours?} over the current preferences, every field checked. In-app cannot be
    turned off, and nothing here can enable a channel the contact policy or the deployment flags keep closed."""
    if not isinstance(body, dict) or not body or set(body) - {'events', 'digest', 'quietHours'}:
        raise ControlError('VALIDATION_FAILED', 400)
    out = merge_preferences(current)
    if 'events' in body:
        events = _section(body, 'events', set(NOTICE_EVENTS))
        for name, value in events.items():
            if not isinstance(value, dict) or not value or set(value) - {'email', 'push'}:
                raise ControlError('VALIDATION_FAILED', 400)
            out['events'][name].update({channel: _bool(flag) for channel, flag in value.items()})
    if 'digest' in body:
        digest = _section(body, 'digest', {'enabled', 'hour', 'email'})
        if 'enabled' in digest:
            out['digest_enabled'] = _bool(digest['enabled'])
        if 'email' in digest:
            out['digest_email'] = _bool(digest['email'])
        if 'hour' in digest:
            out['digest_hour'] = _int(digest['hour'], 0, 23)
    if 'quietHours' in body:
        quiet = _section(body, 'quietHours', {'start', 'end', 'timeZone'})
        if 'start' in quiet:
            out['quiet_start'] = _int(quiet['start'], 0, 1439)
        if 'end' in quiet:
            out['quiet_end'] = _int(quiet['end'], 0, 1439)
        if 'timeZone' in quiet:
            zone = quiet['timeZone']
            try:
                if not isinstance(zone, str) or not 1 <= len(zone) <= 64 or not _ZONE_NAME.match(zone):
                    raise ValueError
                ZoneInfo(zone)
            except (ZoneInfoNotFoundError, ValueError, TypeError):
                raise ControlError('VALIDATION_FAILED', 400) from None
            out['time_zone'] = zone
    return out


def load_preferences(centre, operator_id):
    """The operator's preferences, or the defaults when there is no centre or it cannot be read (logged once)."""
    if centre is None:
        return merge_preferences(None)
    try:
        return merge_preferences(centre.preferences(operator_id))
    except Exception as error:  # noqa: BLE001 - unreadable preferences fall back to the defaults, which send nothing external
        _log_once('founder_notice.preferences_unavailable', error)
        return merge_preferences(None)


def _quiet(prefs):
    return {'quiet_start': prefs['quiet_start'], 'quiet_end': prefs['quiet_end'], 'time_zone': prefs['time_zone']}


def _zone(name):
    try:
        return ZoneInfo(name or TIME_ZONE)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo(TIME_ZONE)


# --- deterministic routing ----------------------------------------------------------------------------------------------------
def route(event_type, severity):
    """The channel modes a notice gets before any gate (PRD §6.7): 'immediate', 'digest' or 'off'."""
    if event_type == TEST_EVENT:
        return {'email': 'off', 'push': 'off'}
    if event_type == DIGEST_EVENT:
        return {'email': 'immediate', 'push': 'off'}
    if severity in BREAKS_QUIET:
        return {'email': 'immediate', 'push': 'immediate'}
    if severity == 'warning':
        return {'email': 'digest', 'push': 'off'}
    if event_type == 'founder.briefing_ready':
        return {'email': 'digest', 'push': 'immediate'}
    return {'email': 'digest', 'push': 'off'}


def delivery_blockers(channel, policy, flags):
    """Every gate an external channel fails, in order (empty = it may be used): the contact policy must enable live
    delivery and list the channel, and the deployment flag must be set."""
    policy, out = policy or {}, []
    if not policy.get('live_delivery_enabled'):
        out.append('live_delivery_disabled')
    if channel not in (policy.get('channels') or []):
        out.append('channel_not_in_policy')
    if not truthy((flags or {}).get(FLAGS[channel])):
        out.append('deployment_flag_unset')
    return out


def plan_notice(event_type, severity, prefs, policy, flags, now):
    """{in_app, email, push, digest, outbox} for one notice and one operator. Pure: no clock beyond `now`, no I/O.
    Each external channel is {'mode': immediate|digest|off, 'reason', 'blockers'}; `outbox` is the channel filter for the
    shared outbox (in_app plus the channels that go out now); `digest` says whether the notice joins the daily digest."""
    routes = route(event_type, severity)
    quiet = severity not in BREAKS_QUIET and in_quiet_hours(now, _quiet(prefs))
    wanted = (prefs.get('events') or {}).get(event_type) or {}
    digest_on = bool(prefs.get('digest_enabled', True))
    plan, digest = {'in_app': {'mode': 'immediate', 'reason': None, 'blockers': []}}, False
    for channel in ('email', 'push'):
        mode, reason = routes[channel], ('not_routed' if routes[channel] == 'off' else None)
        if mode == 'immediate' and quiet:
            mode, reason = ('digest', 'quiet_hours') if channel == 'email' and event_type != DIGEST_EVENT else ('off', 'quiet_hours')
        # A notice routed to the digest is summarised in the next daily digest (in-app always; the digest email has its own
        # gates), whatever this notice's own email preference says.
        digest = digest or (mode == 'digest' and digest_on)
        if mode != 'off' and ((event_type == DIGEST_EVENT and not prefs.get('digest_email', True)) or wanted.get(channel) is False):
            mode, reason = 'off', 'preference_off'
        if mode == 'digest' and not digest_on:
            mode, reason = 'off', 'digest_disabled'
        blockers = delivery_blockers(channel, policy, flags) if mode != 'off' else []
        if mode == 'immediate' and blockers:
            mode, reason = 'off', blockers[0]
        plan[channel] = {'mode': mode, 'reason': reason, 'blockers': blockers}
    plan['digest'] = digest
    plan['outbox'] = sorted(['in_app'] + [channel for channel in ('email', 'push') if plan[channel]['mode'] == 'immediate'])
    return plan


# --- notices ----------------------------------------------------------------------------------------------------------------------
def describe(event_type, subject):
    """The notice for one subject: fixed vocabulary only (detector, scope, severity, report kind and version), so neither
    a customer record nor free text can reach a title. The subject id travels separately (the outbox redacts digit runs)."""
    if event_type not in NOTICE_EVENTS or not isinstance(subject, dict) or not _SUBJECT_ID.match(str(subject.get('id') or '')):
        raise ValueError('unknown founder notice')
    if 'detector' in subject:
        detector, scope = str(subject['detector'])[:60], str(subject['scope'])[:60]
        incident_severity = subject.get('severity') if subject.get('severity') in SEVERITIES else 'warning'
        severity = 'info' if event_type == 'founder.incident_recovered' else incident_severity
        title = (f'Recovered: {detector} ({scope})' if event_type == 'founder.incident_recovered' else
                 f'Source unavailable: {scope} ({incident_severity})' if event_type == 'founder.source_unavailable' else
                 f'{incident_severity} incident: {detector} ({scope})')
        version = int(subject['version'])
        return {'event_type': event_type, 'severity': severity, 'subject_type': 'founder_incident', 'subject_id': str(subject['id']),
                'dedupe_key': f"{event_type}:{subject['id']}:{version}", 'title': title[:200], 'href': HREFS['founder_incident'],
                'entity_type': 'founder_incident', 'facts': {'detector': detector, 'scope': scope, 'severity': incident_severity,
                                                             'state': str(subject.get('state') or '')[:20] or None, 'version': version}}
    kind, version = str(subject['kind'])[:20], int(subject['version'])
    return {'event_type': event_type, 'severity': 'info', 'subject_type': 'founder_report', 'subject_id': str(subject['id']),
            'dedupe_key': f"{event_type}:{subject['id']}", 'title': f'Founder {kind} briefing v{version} is ready', 'href': HREFS['founder_report'],
            'entity_type': 'founder_report', 'facts': {'kind': kind, 'version': version, 'receipts': len(subject.get('receipt_ids') or [])}}


def _channels(plan, outbox_available):
    """What the centre records per channel: the planned mode, the reason and the gates, and whether an outbox exists."""
    out = {'in_app': {'mode': 'immediate', 'state': 'delivered'}}
    for channel in ('email', 'push'):
        item = plan[channel]
        entry = {'mode': item['mode']}
        if item.get('reason'):
            entry['reason'] = item['reason']
        if item.get('blockers'):
            entry['blockers'] = list(item['blockers'])
        if item['mode'] == 'immediate':
            entry['outbox'] = 'planned' if outbox_available else 'disabled'
        out[channel] = entry
    return out


def record(centre, operator_id, notice, plan, now, *, outbox_available):
    """Write one notice to the founder centre: (row, created), or (None, False) when there is no centre or it is not
    installed / unavailable (logged once). Idempotent per (operator, environment, dedupe key)."""
    if centre is None:
        return None, False
    row = {'id': str(uuid.uuid4()), 'operator_id': operator_id, 'event_type': notice['event_type'], 'severity': notice['severity'],
           'subject_type': notice['subject_type'], 'subject_id': notice['subject_id'], 'dedupe_key': notice['dedupe_key'][:200], 'title': notice['title'][:200],
           'href': notice['href'], 'channels': _channels(plan, outbox_available), 'facts': dict(notice.get('facts') or {}),
           'digest_state': 'pending' if plan.get('digest') else 'none', 'created_at': float(now)}
    try:
        return centre.insert_notice(row)
    except Exception as error:  # noqa: BLE001 - the centre never fails a notifier caller; the outbox still runs
        _log_once('founder_notice.centre_unavailable' if isinstance(error, MISSING_SOURCE) else 'founder_notice.centre_failed', error)
        return None, False


def outbox_service(service):
    """The consumer NotificationService when its feature flag is on, else None (never raises)."""
    notifications = getattr(service, 'notifications', None)
    if notifications is None:
        return None
    try:
        return notifications if notifications.enabled() else None
    except Exception:  # noqa: BLE001
        return None


def emit_outbox(service, outbox, notice, plans, *, payload=None):
    """{operator: emit result} through the shared outbox: one short consumer connection per notice (never a caller's
    transaction), one SAVEPOINT per operator, deliveries limited to each plan's channel filter. Missing tables, columns
    or grants are 'not installed yet'; every failure is logged once by class and returned per operator, never raised."""
    out = {}
    try:
        register_events()
        with founder_cron._consumer_connection(service)() as db, db.cursor() as cur:
            for operator, plan in plans.items():
                cur.execute('SAVEPOINT founder_notice')
                try:
                    out[operator] = outbox.emit(cur, workspace_id=None, user_id=operator, event_type=notice['event_type'], dedupe_key=notice['dedupe_key'],
                                                entity_type=notice['entity_type'], entity_id=notice['subject_id'],
                                                payload=dict(payload) if payload is not None else {'title': notice['title'], 'href': notice['href']},
                                                channel_filter=plan['outbox'])
                    cur.execute('RELEASE SAVEPOINT founder_notice')
                except Exception as error:  # noqa: BLE001 - one operator's failure stays with that operator
                    cur.execute('ROLLBACK TO SAVEPOINT founder_notice')
                    _log_once('founder_notice.outbox_unavailable' if isinstance(error, MISSING_SOURCE) else 'founder_notice.outbox_failed', error)
                    out[operator] = {'eventId': None, 'created': False, 'deliveries': [], 'error': type(error).__name__}
            db.commit()
    except Exception as error:  # noqa: BLE001 - no consumer connection, or the outbox schema is not installed
        _log_once('founder_notice.outbox_unavailable', error)
    return out


def notice_store(fstore):
    """The founder centre for a founder store: an injected centre (`fstore.notice_centre`, tests), else the 067 tables
    over the store's restricted PostgresStore, else None (no centre: the outbox alone carries the notice)."""
    if fstore is None:
        return None
    custom = getattr(fstore, 'notice_centre', None)
    if custom is not None:
        return custom
    store = getattr(fstore, 'store', None)
    if store is not None and callable(getattr(store, 'transaction', None)):
        return NoticeSQL(store)
    return None


def _policy(fstore, operator_id):
    if fstore is None or not callable(getattr(fstore, 'policy', None)):
        return dict(DEFAULT_POLICY)
    try:
        return load_policy(fstore, operator_id)
    except Exception as error:  # noqa: BLE001 - an unreadable policy is the default policy: nothing external
        _log_once('founder_notice.policy_unavailable', error)
        return dict(DEFAULT_POLICY)


def notifier(service, operators, now, fstore=None, values=None):
    """notify(event_type, subject) for founder_cron (incidents and briefings), or None when there is neither a founder
    centre nor an enabled outbox. Each call records the notice for every operator (in-app, always), then emits it through
    the outbox with each operator's channel filter; it returns the outbox results and never raises for delivery reasons."""
    operators = [str(operator) for operator in (operators or [])][:MAX_OPERATORS]
    if not operators:
        return None
    outbox, centre = outbox_service(service), notice_store(fstore)
    if outbox is None and centre is None:
        return None
    flags = deployment_flags(values)

    def notify(event_type, subject):
        notice = describe(event_type, subject)
        plans = {}
        for operator in operators:
            prefs = load_preferences(centre, operator)
            plans[operator] = plan_notice(event_type, notice['severity'], prefs, _policy(fstore, operator), flags, now)
            record(centre, operator, notice, plans[operator], now, outbox_available=outbox is not None)
        emitted = emit_outbox(service, outbox, notice, plans) if outbox is not None else {}
        return [emitted[operator] for operator in operators if operator in emitted]
    return notify


def public_notice(row):
    subject_type, subject_id = row['subject_type'], row['subject_id']
    href = {'founder_incident': f"{HREFS['founder_incident']}&incident={subject_id}", 'founder_report': f"{HREFS['founder_report']}&report={subject_id}"}.get(
        subject_type, f"{row.get('href') or HREFS['founder_test']}&notice={row['id']}")
    read_at = row.get('read_at')
    return {'id': row['id'], 'type': row['event_type'], 'severity': row['severity'], 'title': row['title'], 'href': href,
            'subject': {'type': subject_type, 'id': subject_id}, 'channels': dict(row.get('channels') or {}), 'facts': dict(row.get('facts') or {}),
            'digest': {'state': row.get('digest_state') or 'none', 'id': row.get('digest_id')}, 'createdAt': float(row['created_at']),
            'readAt': float(read_at) if read_at is not None else None, 'read': read_at is not None}


# --- daily digest (cron stage) ----------------------------------------------------------------------------------------------
def _digest_notice(pending, local_date):
    severities = Counter(row['severity'] for row in pending)
    events = Counter(row['event_type'] for row in pending)
    warnings, others = severities.get('warning', 0), len(pending) - severities.get('warning', 0)
    title = (f'Founder daily digest · {local_date}: {warnings} warning{"s" if warnings != 1 else ""}, '
             f'{others} other notice{"s" if others != 1 else ""}')
    return {'event_type': DIGEST_EVENT, 'severity': 'info', 'subject_type': 'founder_digest', 'subject_id': local_date, 'dedupe_key': f'{DIGEST_EVENT}:{local_date}',
            'title': title, 'href': HREFS['founder_digest'], 'entity_type': 'founder_notice',
            'facts': {'localDate': local_date, 'items': len(pending), 'severities': dict(sorted(severities.items())), 'events': dict(sorted(events.items()))}}


def _digest_payload(notice):
    facts = notice['facts']
    metrics = [{'label': EVENT_LABELS.get(name, name), 'value': str(count)} for name, count in sorted(facts['events'].items())][:4]
    return {'title': notice['title'], 'href': notice['href'], 'count': facts['items'], 'metrics': metrics}


def digest_one(centre, fstore, service, flags, operator_id, now):
    """The digest of one operator at `now`: a fixed outcome code. Once per founder-local day, at or after the digest hour,
    outside quiet hours, only when notices are pending; the email goes out only through the founder gates."""
    prefs = load_preferences(centre, operator_id)
    if not prefs['digest_enabled']:
        return 'disabled'
    local = datetime.fromtimestamp(float(now), _zone(prefs['time_zone']))
    if local.hour < int(prefs['digest_hour']):
        return 'not_due'
    if in_quiet_hours(now, _quiet(prefs)):
        return 'quiet_hours'
    local_date = local.date().isoformat()
    if centre.notice_by_dedupe(operator_id, f'{DIGEST_EVENT}:{local_date}'):
        return 'done'
    pending = centre.pending_digest(operator_id, limit=DIGEST_LIMIT)
    if not pending:
        return 'nothing_pending'
    notice = _digest_notice(pending, local_date)
    plan = plan_notice(DIGEST_EVENT, 'info', prefs, _policy(fstore, operator_id), flags, now)
    outbox = outbox_service(service) if plan['email']['mode'] == 'immediate' else None
    stored, created = record(centre, operator_id, notice, plan, now, outbox_available=outbox is not None)
    if stored is None:
        return 'centre_unavailable'
    if not created:
        return 'done'
    centre.include_in_digest(operator_id, [row['id'] for row in pending], stored['id'])
    if outbox is None:
        return 'in_app'
    plan = {**plan, 'outbox': ['email']}   # the digest itself is an email; its in-app copy is the founder centre's digest notice
    emitted = emit_outbox(service, outbox, {**notice, 'subject_id': stored['id'], 'dedupe_key': f"{DIGEST_EVENT}:{stored['id']}"}, {operator_id: plan},
                          payload=_digest_payload(notice))
    return 'emailed' if (emitted.get(operator_id) or {}).get('eventId') else 'email_unavailable'


def digest_stage(fstore, service, values, now):
    """Cron stage `founder_digest` (CONTRACTS §8 register_stage): the daily digest of warnings for every active founder
    operator, then a bounded purge of notices past retention. Bounded and JSON-serialisable; never raises into the tick."""
    centre = notice_store(fstore)
    if centre is None:
        return {'status': 'unavailable', 'reason': 'notice_centre_unavailable'}
    try:
        operators = [str(operator) for operator in fstore.founder_operators()][:MAX_OPERATORS]
        flags = deployment_flags(values)
        outcomes = {operator: digest_one(centre, fstore, service, flags, operator, now) for operator in operators}
        purged = centre.purge(float(now) - RETENTION_SECONDS)
        return {'status': 'ok', 'operators': outcomes, 'purged': int(purged or 0)}
    except MISSING_SOURCE as error:
        _log_once('founder_notice.centre_unavailable', error)
        return {'status': 'unavailable', 'reason': 'notifications_not_installed'}
    except Exception as error:  # noqa: BLE001 - a broken digest never breaks the tick
        _log_once('founder_notice.digest_failed', error)
        return {'status': 'unavailable', 'error': type(error).__name__}


# --- routes -------------------------------------------------------------------------------------------------------------------------
def app_centre(app):
    """The founder centre over Control's own restricted store, or None when Control has no store here."""
    store = getattr(getattr(app, 'queries', None), 'store', None)
    return NoticeSQL(store) if store is not None and callable(getattr(store, 'transaction', None)) else None


def outbox_config(app):
    """What the consumer outbox could carry, from its configuration only (no network, no database): None on a separate
    mount, where Control has no consumer runtime."""
    try:
        service = app.consumer()
    except Exception:  # noqa: BLE001 - separate mount (503) or a runtime that does not build
        return None
    notifications = getattr(service, 'notifications', None)
    if notifications is None:
        return {'enabled': False, 'email': False, 'push': False}
    try:
        enabled = bool(notifications.enabled())
        return {'enabled': enabled, 'email': enabled and bool(notifications.email_available()), 'push': bool(notifications.push_enabled())}
    except Exception:  # noqa: BLE001
        return None


def readiness(policy, flags, config):
    """Per channel: ready or the gates it fails (policy, deployment flag, outbox transport). In-app is always ready."""
    out = {'inApp': {'ready': True, 'blockers': []}}
    for channel in ('email', 'push'):
        blockers = delivery_blockers(channel, policy, flags)
        transport = None if config is None else bool(config.get(channel))
        if transport is False:
            blockers.append('outbox_unavailable')
        out[channel] = {'ready': not blockers, 'blockers': blockers, 'policyListed': channel in (policy.get('channels') or []),
                        'liveDeliveryEnabled': bool(policy.get('live_delivery_enabled')), 'flag': truthy(flags.get(FLAGS[channel])), 'transport': transport}
    return out


def event_catalog():
    """The deterministic routing table the Settings page explains (no channel can be widened from the browser)."""
    return [{'type': name, 'label': EVENT_LABELS[name], 'routes': {severity: route(name, severity) for severity in EVENT_SEVERITIES[name]}} for name in NOTICE_EVENTS]


def _operator(principal):
    return principal['operator']['user_id']


def get_preferences(app, principal, request):
    """GET /notifications/preferences (control.read): the founder's notice preferences, each channel's readiness and the
    routing table. Settings, not data: the same in either data mode."""
    operator, centre, installed = _operator(principal), app_centre(app), True
    row = None
    if centre is None:
        installed = False
    else:
        try:
            row = centre.preferences(operator)
        except MISSING_SOURCE as error:
            _log_once('founder_notice.preferences_unavailable', error)
            installed = False
    policy = _policy(app.founder_store() if centre is not None else None, operator)
    flags = deployment_flags(getattr(app, 'flags', {}) or {})
    return {'preferences': public_preferences(merge_preferences(row)), 'installed': installed, 'readiness': readiness(policy, flags, outbox_config(app)),
            'policy': {'liveDeliveryEnabled': bool(policy.get('live_delivery_enabled')), 'channels': [c for c in (policy.get('channels') or []) if c in ('email', 'push')],
                       'revision': int(policy.get('revision') or 0)},
            'flags': {'founderEmailEnabled': truthy(flags.get(FLAGS['email'])), 'founderPushEnabled': truthy(flags.get(FLAGS['push']))},
            'events': event_catalog()}


def put_preferences(app, principal, request):
    """PUT /notifications/preferences (control.settings + step_up): validate the patch, bump the revision, return it."""
    operator, centre = _operator(principal), app_centre(app)
    if centre is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    try:
        prefs = validate_preferences(request['body'], centre.preferences(operator))
        saved = centre.save_preferences(operator, prefs, request['now'])
    except MISSING_SOURCE as error:
        _log_once('founder_notice.preferences_unavailable', error)
        raise NotInstalled() from None
    return {'preferences': public_preferences(merge_preferences(saved))}


def list_notices(app, principal, request):
    """GET /notifications?limit= (control.read): the founder centre, newest first, with the unread count. Demo has no
    simulated notices and never shows Live ones."""
    if request['mode'] == 'demo':
        return {'mode': 'demo', 'notices': [], 'unread': 0, 'reason': 'demo_not_simulated', '_dataState': 'not_applicable'}
    centre = app_centre(app)
    if centre is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    limit = app.query_int(request['query'], 'limit', 50, 200)
    try:
        rows, unread = centre.notices(_operator(principal), limit=limit), centre.unread(_operator(principal))
    except MISSING_SOURCE as error:
        _log_once('founder_notice.centre_unavailable', error)
        return {'mode': 'live', 'notices': [], 'unread': 0, 'installed': False, 'reason': 'notifications_not_installed', '_dataState': 'unavailable'}
    return {'mode': 'live', 'notices': [public_notice(row) for row in rows], 'unread': int(unread), 'installed': True}


def read_notice(app, principal, request):
    """POST /notifications/{id}/read (control.read + CSRF): mark one of this founder's notices read."""
    notice_id = (request.get('match') or [None])[0]
    centre = app_centre(app)
    if not isinstance(notice_id, str) or not _UUID.match(notice_id) or (request.get('body') or {}):
        raise ControlError('VALIDATION_FAILED', 400)
    if centre is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    try:
        row = centre.mark_read(_operator(principal), str(uuid.UUID(notice_id)), request['now'])
        unread = centre.unread(_operator(principal))
    except MISSING_SOURCE as error:
        _log_once('founder_notice.centre_unavailable', error)
        raise NotInstalled() from None
    if row is None:
        raise ControlError('VALIDATION_FAILED', 404)
    return {'notice': public_notice(row), 'unread': int(unread)}


def test_notice(app, principal, request):
    """POST /notifications/test (control.read + CSRF): one test notice in the founder centre only. It never reaches the
    outbox, email or push, so it proves the in-app path without any external effect."""
    body = request.get('body') or {}
    if not isinstance(body, dict) or set(body) - {'requestId'}:
        raise ControlError('VALIDATION_FAILED', 400)
    source = body.get('requestId', request['requestId'])
    if not isinstance(source, str) or not _UUID.match(source):
        raise ControlError('VALIDATION_FAILED', 400)
    centre = app_centre(app)
    if centre is None:
        raise ControlError('SOURCE_UNAVAILABLE', 503)
    operator, now = _operator(principal), request['now']
    notice = {'event_type': TEST_EVENT, 'severity': 'info', 'subject_type': 'founder_test', 'subject_id': str(uuid.UUID(source)),
              'dedupe_key': f'{TEST_EVENT}:{uuid.UUID(source)}', 'title': 'Test notice from Founder Admin (in-app only; nothing was emailed or pushed)',
              'href': HREFS['founder_test'], 'entity_type': 'founder_notice', 'facts': {}}
    try:
        plan = plan_notice(TEST_EVENT, 'info', merge_preferences(centre.preferences(operator)), dict(DEFAULT_POLICY), {}, now)
        row, created = centre.insert_notice({'id': str(uuid.uuid4()), 'operator_id': operator, 'event_type': TEST_EVENT, 'severity': 'info', 'subject_type': 'founder_test',
                                             'subject_id': notice['subject_id'], 'dedupe_key': notice['dedupe_key'], 'title': notice['title'], 'href': notice['href'],
                                             'channels': _channels(plan, False), 'facts': {}, 'digest_state': 'none', 'created_at': float(now)})
        unread = centre.unread(operator)
    except MISSING_SOURCE as error:
        _log_once('founder_notice.centre_unavailable', error)
        raise NotInstalled() from None
    return {'notice': public_notice(row), 'replayed': not created, 'unread': int(unread)}


# --- SQL (rafii_control_session role, environment GUC policies; see migration 067) ----------------------------------------------
_PREF_COLUMNS = 'revision,events,digest_enabled,digest_email,digest_hour,quiet_start,quiet_end,time_zone,extract(epoch from updated_at) AS updated_at'
_NOTICE_SELECT = ('SELECT id::text AS id,operator_id::text AS operator_id,environment,event_type,severity,subject_type,subject_id,dedupe_key,title,href,'
                  'channels,facts,digest_state,digest_id::text AS digest_id,extract(epoch from created_at) AS created_at,extract(epoch from read_at) AS read_at '
                  'FROM rafii_control.founder_notices')


def _pref_row(row):
    return {**row, 'events': dict(row.get('events') or {}), 'updated_at': float(row['updated_at']) if row.get('updated_at') is not None else None}


def _notice_row(row):
    return {**row, 'channels': dict(row.get('channels') or {}), 'facts': dict(row.get('facts') or {}), 'created_at': float(row['created_at']),
            'read_at': float(row['read_at']) if row.get('read_at') is not None else None}


class NoticeSQL:
    """The founder centre and notice preferences over a rafii_control.store.PostgresStore (session role)."""

    def __init__(self, store):
        self.store, self.environment = store, store.environment

    def preferences(self, operator_id):
        with self.store.transaction() as con:
            row = con.execute(f'SELECT {_PREF_COLUMNS} FROM rafii_control.founder_notification_preferences WHERE operator_id=%s AND environment=%s',
                              (operator_id, self.environment)).fetchone()
        return _pref_row(row) if row else None

    def save_preferences(self, operator_id, prefs, now):
        with self.store.transaction() as con:
            row = con.execute(
                'INSERT INTO rafii_control.founder_notification_preferences(operator_id,environment,revision,events,digest_enabled,digest_email,digest_hour,'
                'quiet_start,quiet_end,time_zone,updated_at) VALUES(%s,%s,1,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s)) '
                'ON CONFLICT(operator_id,environment) DO UPDATE SET revision=founder_notification_preferences.revision+1,events=excluded.events,'
                'digest_enabled=excluded.digest_enabled,digest_email=excluded.digest_email,digest_hour=excluded.digest_hour,quiet_start=excluded.quiet_start,'
                f'quiet_end=excluded.quiet_end,time_zone=excluded.time_zone,updated_at=excluded.updated_at RETURNING {_PREF_COLUMNS}',
                (operator_id, self.environment, Jsonb(prefs['events']), prefs['digest_enabled'], prefs['digest_email'], prefs['digest_hour'],
                 prefs['quiet_start'], prefs['quiet_end'], prefs['time_zone'], now)).fetchone()
        return _pref_row(row)

    def insert_notice(self, row):
        with self.store.transaction() as con:
            created = con.execute(
                'INSERT INTO rafii_control.founder_notices(id,operator_id,environment,event_type,severity,subject_type,subject_id,dedupe_key,title,href,'
                'channels,facts,digest_state,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s)) '
                'ON CONFLICT(operator_id,environment,dedupe_key) DO NOTHING RETURNING id::text',
                (row['id'], row['operator_id'], self.environment, row['event_type'], row['severity'], row['subject_type'], row['subject_id'], row['dedupe_key'],
                 row['title'], row['href'], Jsonb(row['channels']), Jsonb(row['facts']), row['digest_state'], row['created_at'])).fetchone()
            stored = con.execute(_NOTICE_SELECT + ' WHERE operator_id=%s AND environment=%s AND dedupe_key=%s',
                                 (row['operator_id'], self.environment, row['dedupe_key'])).fetchone()
        return _notice_row(stored), created is not None

    def notice_by_dedupe(self, operator_id, dedupe_key):
        with self.store.transaction() as con:
            row = con.execute(_NOTICE_SELECT + ' WHERE operator_id=%s AND environment=%s AND dedupe_key=%s', (operator_id, self.environment, dedupe_key)).fetchone()
        return _notice_row(row) if row else None

    def notices(self, operator_id, *, limit=50):
        with self.store.transaction() as con:
            rows = con.execute(_NOTICE_SELECT + ' WHERE operator_id=%s AND environment=%s ORDER BY created_at DESC,id DESC LIMIT %s',
                               (operator_id, self.environment, max(1, min(int(limit), 200)))).fetchall()
        return [_notice_row(row) for row in rows]

    def unread(self, operator_id):
        with self.store.transaction() as con:
            return int(con.execute('SELECT count(*) AS n FROM rafii_control.founder_notices WHERE operator_id=%s AND environment=%s AND read_at IS NULL',
                                   (operator_id, self.environment)).fetchone()['n'])

    def mark_read(self, operator_id, notice_id, now):
        with self.store.transaction() as con:
            found = con.execute('UPDATE rafii_control.founder_notices SET read_at=coalesce(read_at,to_timestamp(%s)) WHERE id=%s AND operator_id=%s AND environment=%s '
                                'RETURNING id::text', (now, notice_id, operator_id, self.environment)).fetchone()
            row = con.execute(_NOTICE_SELECT + ' WHERE id=%s', (notice_id,)).fetchone() if found else None
        return _notice_row(row) if row else None

    def pending_digest(self, operator_id, *, limit=DIGEST_LIMIT):
        with self.store.transaction() as con:
            rows = con.execute(_NOTICE_SELECT + " WHERE operator_id=%s AND environment=%s AND digest_state='pending' ORDER BY created_at,id LIMIT %s",
                               (operator_id, self.environment, max(1, min(int(limit), DIGEST_LIMIT)))).fetchall()
        return [_notice_row(row) for row in rows]

    def include_in_digest(self, operator_id, notice_ids, digest_id):
        with self.store.transaction() as con:
            return con.execute("UPDATE rafii_control.founder_notices SET digest_state='included',digest_id=%s WHERE operator_id=%s AND environment=%s "
                               "AND digest_state='pending' AND id=ANY(%s::uuid[])", (digest_id, operator_id, self.environment, list(notice_ids))).rowcount

    def purge(self, before):
        with self.store.transaction() as con:
            return con.execute('DELETE FROM rafii_control.founder_notices WHERE id IN (SELECT id FROM rafii_control.founder_notices WHERE environment=%s '
                               'AND created_at<to_timestamp(%s) ORDER BY created_at LIMIT 500)', (self.environment, before)).rowcount


# --- registration (CONTRACTS §8.0: routes and cron stages from the slice's own module) ----------------------------------------------
ROUTES = (('GET', r'/notifications/preferences', 'control.read', 'founder_notifications', 'get_preferences', {}),
          ('PUT', r'/notifications/preferences', 'control.settings', 'founder_notifications', 'put_preferences', {'step_up': True}),
          ('GET', r'/notifications', 'control.read', 'founder_notifications', 'list_notices', {}),
          ('POST', r'/notifications/test', 'control.read', 'founder_notifications', 'test_notice', {}),
          ('POST', r'/notifications/([0-9a-fA-F-]{36})/read', 'control.read', 'founder_notifications', 'read_notice', {}),
          ('GET', r'/reports', 'control.read', 'founder_briefings', 'http_reports', {}),
          ('GET', r'/reports/([0-9a-fA-F-]{36})', 'control.read', 'founder_briefings', 'http_report', {}))
STAGE = 'founder_digest'


def register():
    """Register the routes and the digest stage once per process (a re-import never duplicates them)."""
    for method, pattern, capability, module, function, options in ROUTES:
        if not any(existing[0] == method and existing[1].pattern == pattern for existing in http.EXTENSION_ROUTES):
            http.register_route(method, pattern, capability, module, function, **options)
    if not any(name == STAGE for name, _work in founder_cron.STAGES):
        founder_cron.register_stage(STAGE, digest_stage)


register()
