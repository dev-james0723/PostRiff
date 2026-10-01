"""Founder briefing schedules and occurrences (Founder Admin v2, CONTRACTS §5).

Boundaries. Time arithmetic reuses `postriff_phase2.campaigns.next_occurrence` (weekly slots across chosen weekdays): a
skipped wall time (spring gap) moves to the next valid local minute and a repeated one (autumn fold) uses its first,
earlier-offset instance. The cron commits the next slot before any briefing or dial, as `phone/runtime.schedule_tick`
does, so a crash can skip one briefing but never replay an ambiguous dial. One occurrence row per (schedule, local date,
slot) makes duplicate cron invocations idempotent; a slot found more than LATE_SECONDS after its time is recorded as
'missed' (inbox fallback, no catch-up call); a daily slot on a day that also has a weekly briefing is 'coalesced'.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError
from postriff_phase2 import campaigns

from .auth import ControlError

KINDS = ('daily', 'weekly')
OCCURRENCE_STATES = ('planned', 'claimed', 'delivered', 'missed', 'coalesced', 'failed')
LATE_SECONDS = 15 * 60
LEASE_SECONDS = 10 * 60
MAX_SCHEDULES = 4
_LOCAL_TIME = re.compile(r'([01][0-9]|2[0-3]):([0-5][0-9])\Z')
_FIELDS = {'kind': 'kind', 'localTime': 'local_time', 'weekdays': 'weekdays', 'timeZone': 'time_zone', 'enabled': 'enabled'}


def validate_schedule(body):
    """A daily or weekly schedule: HH:MM local time, weekdays (Monday=0) for weekly, a valid IANA zone."""
    if not isinstance(body, dict) or set(body) - set(_FIELDS) or not {'kind', 'localTime', 'timeZone'} <= set(body):
        raise ControlError('VALIDATION_FAILED', 400)
    kind, local_time, zone = body['kind'], body['localTime'], body['timeZone']
    if kind not in KINDS or not isinstance(local_time, str) or not _LOCAL_TIME.fullmatch(local_time):
        raise ControlError('VALIDATION_FAILED', 400)
    try:
        if not isinstance(zone, str) or not 1 <= len(zone) <= 64:
            raise ValueError
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ControlError('VALIDATION_FAILED', 400) from None
    enabled = body.get('enabled', True)
    if not isinstance(enabled, bool):
        raise ControlError('VALIDATION_FAILED', 400)
    if kind == 'daily':
        weekdays = list(range(7))
    else:
        raw = body.get('weekdays')
        if not isinstance(raw, list) or not raw or any(type(d) is not int or not 0 <= d <= 6 for d in raw):
            raise ControlError('VALIDATION_FAILED', 400)
        weekdays = sorted(set(raw))
    return {'kind': kind, 'local_time': local_time, 'weekdays': weekdays, 'time_zone': zone, 'enabled': enabled}


def campaign_schedule(schedule):
    return {'weekdays': [campaigns.WEEKDAY_NAMES[day] for day in schedule['weekdays']], 'localTime': schedule['local_time'],
            'timeZone': schedule['time_zone']}


def next_occurrence(schedule, after):
    """{scheduledFor, local, utc, offset, fold} for the first slot strictly after `after` (epoch). DST gap and fold rules
    come from the shared campaign scheduler."""
    try:
        due = campaigns.next_occurrence(campaign_schedule(schedule), after)
    except AlphaError:
        raise ControlError('VALIDATION_FAILED', 400) from None
    if due is None:
        raise ControlError('VALIDATION_FAILED', 400)
    return due


def slot_minutes(schedule):
    hour, minute = _LOCAL_TIME.fullmatch(schedule['local_time']).groups()
    return int(hour) * 60 + int(minute)


def local_slot(schedule, scheduled_at):
    """(local ISO date, configured slot minutes) of one scheduled instant. The slot keeps the configured wall time even
    when a DST gap moved the instant, so the occurrence key stays stable."""
    local = datetime.fromtimestamp(float(scheduled_at), ZoneInfo(schedule['time_zone']))
    return local.date().isoformat(), slot_minutes(schedule)


def public_schedule(row):
    return {'id': row['id'], 'kind': row['kind'], 'localTime': row['local_time'], 'weekdays': list(row['weekdays']), 'timeZone': row['time_zone'],
            'enabled': bool(row['enabled']), 'nextAt': float(row['next_at']), 'revision': int(row['revision']), 'createdAt': float(row['created_at'])}


def public_occurrence(row):
    return {'id': row['id'], 'scheduleId': row['schedule_id'], 'localDate': row['local_date'], 'slot': int(row['slot']),
            'scheduledAt': float(row['scheduled_at']), 'state': row['state'], 'reportId': row.get('report_id'), 'attemptId': row.get('attempt_id')}


def create_schedule(fstore, principal, body, *, now):
    """POST /briefing-schedules (control.settings). Up to MAX_SCHEDULES per operator; next_at is committed on creation."""
    operator = principal['operator']['user_id']
    schedule = validate_schedule(body)
    if len(fstore.schedules(operator)) >= MAX_SCHEDULES:
        raise ControlError('BUDGET_EXCEEDED', 409)
    due = next_occurrence(schedule, now)
    row = {'id': str(uuid.uuid4()), 'operator_id': operator, 'environment': fstore.environment, **schedule, 'next_at': due['scheduledFor'],
           'revision': 1, 'created_at': now}
    return {'schedule': public_schedule(fstore.insert_schedule(row)), 'next': due}


def delete_schedule(fstore, principal, schedule_id, *, now=None):
    """DELETE /briefing-schedules/{id}. Occurrences cascade; a report already composed stays immutable."""
    try:
        str(uuid.UUID(str(schedule_id)))
    except (ValueError, TypeError):
        raise ControlError('VALIDATION_FAILED', 400) from None
    return {'deleted': bool(fstore.delete_schedule(principal['operator']['user_id'], schedule_id))}


# Route names used by rafii_control.http (CONTRACTS §3).
create = create_schedule
delete = delete_schedule


def list_schedules(fstore, principal, *, now, occurrences=10):
    operator = principal['operator']['user_id']
    rows = fstore.schedules(operator)
    recent = []
    for row in rows:
        recent.extend(public_occurrence(o) for o in fstore.occurrences(row['id'], limit=occurrences))
    recent.sort(key=lambda o: o['scheduledAt'], reverse=True)
    return {'schedules': [public_schedule(r) for r in rows], 'occurrences': recent[:occurrences * 2]}


# --- cron claim -------------------------------------------------------------------------------------------------------------
def weekly_covers(fstore, daily, local_date):
    """True when one of the operator's enabled weekly schedules already has (or will have today) a briefing on this date."""
    for other in fstore.schedules(daily['operator_id']):
        if other['kind'] != 'weekly' or not other['enabled'] or other['id'] == daily['id']:
            continue
        if any(o['local_date'] == local_date and o['state'] not in ('missed', 'failed') for o in fstore.occurrences(other['id'], limit=20)):
            return True
        if local_slot(other, float(other['next_at']))[0] == local_date:
            return True
    return False


def claim_due(fstore, now, *, lease_owner, operator_id=None):
    """Advance every due schedule and claim its occurrence. Returns {'claimed', 'missed', 'coalesced'} occurrences, each
    with its schedule attached. Re-claims occurrences whose lease expired (a crash between claim and completion)."""
    out = {'claimed': [], 'missed': [], 'coalesced': []}
    for stale in fstore.expired_claims(now):
        schedule = fstore.schedule(stale['schedule_id'])
        if schedule is None or (operator_id and schedule['operator_id'] != operator_id):
            continue
        occurrence = fstore.update_occurrence(stale['id'], lease_owner=lease_owner, lease_until=now + LEASE_SECONDS, updated_at=now)
        out['claimed'].append({**occurrence, 'schedule': schedule})
    for schedule in fstore.due_schedules(now):
        if operator_id and schedule['operator_id'] != operator_id:
            continue
        scheduled_at = float(schedule['next_at'])
        following = next_occurrence(schedule, max(now, scheduled_at) + 1)['scheduledFor']
        # Compare-and-set on the slot: a concurrent invocation that already advanced this schedule owns the slot.
        if fstore.update_schedule(schedule['id'], next_at=following, expected_next_at=scheduled_at) is None:
            continue
        local_date, slot = local_slot(schedule, scheduled_at)
        late = now - scheduled_at > LATE_SECONDS
        row = {'id': str(uuid.uuid4()), 'schedule_id': schedule['id'], 'environment': fstore.environment, 'local_date': local_date, 'slot': slot,
               'scheduled_at': scheduled_at, 'state': 'missed' if late else 'planned', 'lease_owner': None, 'lease_until': None,
               'report_id': None, 'attempt_id': None, 'created_at': now, 'updated_at': now}
        occurrence = fstore.insert_occurrence(row)
        if occurrence['id'] != row['id']:
            continue  # the slot already has an occurrence (duplicate invocation)
        if late:
            out['missed'].append({**occurrence, 'schedule': schedule})
            continue
        if schedule['kind'] == 'daily' and weekly_covers(fstore, schedule, local_date):
            out['coalesced'].append({**fstore.update_occurrence(occurrence['id'], state='coalesced', updated_at=now), 'schedule': schedule})
            continue
        claimed = fstore.update_occurrence(occurrence['id'], state='claimed', lease_owner=lease_owner, lease_until=now + LEASE_SECONDS, updated_at=now)
        out['claimed'].append({**claimed, 'schedule': schedule})
    return out


def finish_occurrence(fstore, occurrence_id, *, state, now, report_id=None, attempt_id=None):
    if state not in OCCURRENCE_STATES:
        raise ValueError(state)
    fields = {'state': state, 'lease_owner': None, 'lease_until': None, 'updated_at': now}
    if report_id is not None:
        fields['report_id'] = report_id
    if attempt_id is not None:
        fields['attempt_id'] = attempt_id
    return fstore.update_occurrence(occurrence_id, **fields)


# --- SQL (rafii_control_session role, environment GUC policies; see 055) -----------------------------------------------
_SCHEDULE_SELECT = ('SELECT id::text,operator_id::text AS operator_id,environment,kind,local_time,weekdays,time_zone,enabled,'
                    'extract(epoch from next_at) AS next_at,revision,extract(epoch from created_at) AS created_at FROM rafii_control.founder_briefing_schedules')
_OCCURRENCE_SELECT = ('SELECT id::text,schedule_id::text AS schedule_id,environment,local_date::text AS local_date,slot,extract(epoch from scheduled_at) AS scheduled_at,'
                      'state,lease_owner,extract(epoch from lease_until) AS lease_until,report_id::text AS report_id,attempt_id::text AS attempt_id,'
                      'extract(epoch from created_at) AS created_at,extract(epoch from updated_at) AS updated_at FROM rafii_control.founder_briefing_occurrences')
_OCCURRENCE_FIELDS = frozenset(('state', 'lease_owner', 'lease_until', 'report_id', 'attempt_id', 'updated_at'))


def _schedule_row(row):
    return {**row, 'weekdays': [int(d) for d in (row['weekdays'] or [])], 'next_at': float(row['next_at']), 'created_at': float(row['created_at'])}


def _occurrence_row(row):
    return {**row, 'scheduled_at': float(row['scheduled_at']), 'lease_until': None if row['lease_until'] is None else float(row['lease_until']),
            'created_at': float(row['created_at']), 'updated_at': float(row['updated_at'])}


class ScheduleSQL:
    """Schedule and occurrence rows. `self.store` is a rafii_control.store.PostgresStore."""

    def schedules(self, operator_id):
        with self.store.transaction() as con:
            rows = con.execute(_SCHEDULE_SELECT + ' WHERE operator_id=%s AND environment=%s ORDER BY created_at,id', (operator_id, self.environment)).fetchall()
        return [_schedule_row(r) for r in rows]

    def schedule(self, schedule_id):
        with self.store.transaction() as con:
            row = con.execute(_SCHEDULE_SELECT + ' WHERE id=%s AND environment=%s', (schedule_id, self.environment)).fetchone()
        return _schedule_row(row) if row else None

    def insert_schedule(self, row):
        with self.store.transaction() as con:
            stored = con.execute('INSERT INTO rafii_control.founder_briefing_schedules(id,operator_id,environment,kind,local_time,weekdays,time_zone,enabled,next_at,revision,created_at) '
                                 'VALUES(%s,%s,%s,%s,%s,%s::smallint[],%s,%s,to_timestamp(%s),%s,to_timestamp(%s)) RETURNING id::text',
                                 (row['id'], row['operator_id'], self.environment, row['kind'], row['local_time'], row['weekdays'], row['time_zone'],
                                  row['enabled'], row['next_at'], row['revision'], row['created_at'])).fetchone()
            stored = con.execute(_SCHEDULE_SELECT + ' WHERE id=%s', (stored['id'],)).fetchone()
        return _schedule_row(stored)

    def update_schedule(self, schedule_id, *, next_at=None, expected_next_at=None, enabled=None):
        """Returns the row, or None when the compare-and-set on next_at found another writer first."""
        assignments, values = ['revision=revision+1'], []
        if next_at is not None:
            assignments.append('next_at=to_timestamp(%s)'); values.append(next_at)
        if enabled is not None:
            assignments.append('enabled=%s'); values.append(enabled)
        values.extend([schedule_id, self.environment])
        guard = ''
        if expected_next_at is not None:
            guard = ' AND abs(extract(epoch from next_at)-%s)<0.5'
            values.append(expected_next_at)
        with self.store.transaction() as con:
            row = con.execute(f'UPDATE rafii_control.founder_briefing_schedules SET {",".join(assignments)} WHERE id=%s AND environment=%s{guard} RETURNING id::text',
                              values).fetchone()
            if not row:
                return None
            stored = con.execute(_SCHEDULE_SELECT + ' WHERE id=%s', (schedule_id,)).fetchone()
        return _schedule_row(stored)

    def delete_schedule(self, operator_id, schedule_id):
        with self.store.transaction() as con:
            row = con.execute('DELETE FROM rafii_control.founder_briefing_schedules WHERE id=%s AND operator_id=%s AND environment=%s RETURNING id::text',
                              (schedule_id, operator_id, self.environment)).fetchone()
        return row is not None

    def due_schedules(self, now):
        with self.store.transaction() as con:
            rows = con.execute(_SCHEDULE_SELECT + ' WHERE environment=%s AND enabled AND next_at<=to_timestamp(%s) ORDER BY next_at,id LIMIT 50',
                               (self.environment, now)).fetchall()
        return [_schedule_row(r) for r in rows]

    def insert_occurrence(self, row):
        with self.store.transaction() as con:
            con.execute('INSERT INTO rafii_control.founder_briefing_occurrences(id,schedule_id,environment,local_date,slot,scheduled_at,state,lease_owner,lease_until,report_id,attempt_id,created_at,updated_at) '
                        'VALUES(%s,%s,%s,%s::date,%s,to_timestamp(%s),%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s)) ON CONFLICT(schedule_id,local_date,slot) DO NOTHING',
                        (row['id'], row['schedule_id'], self.environment, row['local_date'], row['slot'], row['scheduled_at'], row['state'], row['lease_owner'],
                         row['lease_until'], row['report_id'], row['attempt_id'], row['created_at'], row['updated_at']))
            stored = con.execute(_OCCURRENCE_SELECT + ' WHERE schedule_id=%s AND local_date=%s::date AND slot=%s', (row['schedule_id'], row['local_date'], row['slot'])).fetchone()
        return _occurrence_row(stored)

    def update_occurrence(self, occurrence_id, **fields):
        if set(fields) - _OCCURRENCE_FIELDS:
            raise ValueError('unknown occurrence field')
        assignments, values = [], []
        for key, value in fields.items():
            if key in ('lease_until', 'updated_at') and value is not None:
                assignments.append(f'{key}=to_timestamp(%s)')
            else:
                assignments.append(f'{key}=%s')
            values.append(value)
        with self.store.transaction() as con:
            row = con.execute(f'UPDATE rafii_control.founder_briefing_occurrences SET {",".join(assignments)} WHERE id=%s AND environment=%s RETURNING id::text',
                              (*values, occurrence_id, self.environment)).fetchone()
            if not row:
                raise ControlError('VALIDATION_FAILED', 404)
            stored = con.execute(_OCCURRENCE_SELECT + ' WHERE id=%s', (occurrence_id,)).fetchone()
        return _occurrence_row(stored)

    def occurrences(self, schedule_id, *, limit=20):
        with self.store.transaction() as con:
            rows = con.execute(_OCCURRENCE_SELECT + ' WHERE schedule_id=%s AND environment=%s ORDER BY scheduled_at DESC LIMIT %s',
                               (schedule_id, self.environment, max(1, min(int(limit), 200)))).fetchall()
        return [_occurrence_row(r) for r in rows]

    def expired_claims(self, now):
        with self.store.transaction() as con:
            rows = con.execute(_OCCURRENCE_SELECT + " WHERE environment=%s AND state='claimed' AND lease_until<to_timestamp(%s) ORDER BY scheduled_at LIMIT 20",
                               (self.environment, now)).fetchall()
        return [_occurrence_row(r) for r in rows]
