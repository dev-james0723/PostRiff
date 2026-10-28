"""The on-call policy as data (docs/ops/h07-oncall-policy.json): priorities, escalation chains, duty hours, roster,
suppression, storm limits and the automatic hold. Pure: no I/O except load(), no clock of its own.

Times of day are wall-clock times in the policy time zone (America/New_York by default), resolved on each actual date,
so a duty window of 09:00 to 23:00 is 14 hours on every day, daylight saving or not. Keys starting with '_' are notes.
"""
import json
import re
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_PATH = Path(__file__).resolve().parents[3] / 'docs' / 'ops' / 'h07-oncall-policy.json'
PRIORITIES = ('P0', 'P1', 'P2')
SEVERITIES = ('page', 'warn', 'info')
CHANNELS = ('push', 'email', 'phone')
TARGETS = ('primary', 'backup')
HOURS = ('any', 'duty')
RECORDS = ('acknowledged', 'resolved')
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
RULE = re.compile(r'^[A-Z][A-Z0-9_]{1,63}$')
PERSON = re.compile(r'^[A-Za-z0-9_.:-]{1,80}$')
_HHMM = re.compile(r'^([01][0-9]|2[0-3]):([0-5][0-9])$|^24:00$')
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class PolicyError(ValueError):
    pass


def _clean(value):
    return {k: v for k, v in value.items() if not str(k).startswith('_')} if isinstance(value, dict) else value


def _minutes(text, *, allow_24=True):
    if not isinstance(text, str) or not _HHMM.match(text) or (text == '24:00' and not allow_24):
        raise PolicyError('time of day must be HH:MM')
    hours, minutes = text.split(':')
    return int(hours) * 60 + int(minutes)


def _zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise PolicyError('unknown time zone') from None


def _list(value, allowed, what):
    if not isinstance(value, list) or not value or any(item not in allowed for item in value):
        raise PolicyError('%s must be a non-empty list of %s' % (what, ', '.join(allowed)))
    return list(dict.fromkeys(value))


def _rules(value, what, *, star=False):
    if not isinstance(value, list) or any(not (RULE.match(str(r)) or (star and r == '*')) for r in value):
        raise PolicyError('%s must be a list of rule ids' % what)
    return list(dict.fromkeys(value))


def _number(value, what, *, minimum=0):
    if type(value) not in (int, float) or value < minimum:
        raise PolicyError('%s must be a number of at least %s' % (what, minimum))
    return float(value)


def validate(raw):
    """A checked copy of the policy. Raises PolicyError on anything malformed; never guesses."""
    if not isinstance(raw, dict) or raw.get('version') != 1:
        raise PolicyError('policy version 1 expected')
    policy = {'version': 1, 'timeZone': raw.get('timeZone', 'America/New_York')}
    _zone(policy['timeZone'])
    duty = _clean(raw.get('dutyHours') or {})
    start, end = _minutes(duty.get('start', '09:00'), allow_24=False), _minutes(duty.get('end', '23:00'))
    if start == end:
        raise PolicyError('duty hours must not be empty')
    holidays = duty.get('holidays', [])
    if not isinstance(holidays, list) or any(not isinstance(h, str) or not _DATE.match(h) for h in holidays):
        raise PolicyError('holidays must be YYYY-MM-DD dates')
    policy['dutyHours'] = {'start': start, 'end': end, 'holidays': sorted(set(holidays))}
    defaults = _clean(raw.get('defaults', {'page': 'P1', 'warn': 'P2'}))
    if not isinstance(defaults, dict) or any(k not in SEVERITIES or v not in PRIORITIES + (None,) for k, v in defaults.items()):
        raise PolicyError('defaults map a severity to a priority')
    policy['defaults'] = dict(defaults)
    rows = []
    for row in raw.get('priorities', []):
        if (not isinstance(row, dict) or not RULE.match(str(row.get('rule', ''))) or row.get('priority') not in PRIORITIES + (None,)
                or row.get('severity', 'page') not in SEVERITIES or not isinstance(row.get('evidence', {}), dict)):
            raise PolicyError('a priority row needs rule, severity and priority')
        rows.append({'rule': row['rule'], 'severity': row.get('severity', 'page'), 'evidence': dict(row.get('evidence', {})),
                     'priority': row['priority']})
    policy['priorities'] = rows
    chains = _clean(raw.get('escalation') or {})
    policy['escalation'] = {}
    for priority in PRIORITIES:
        steps = chains.get(priority)
        if not isinstance(steps, list) or not steps:
            raise PolicyError('every priority needs an escalation chain')
        checked = []
        for step in steps:
            if not isinstance(step, dict):
                raise PolicyError('a step is an object')
            after = _number(step.get('after', 0), 'after')
            if step.get('to') not in TARGETS or step.get('hours', 'any') not in HOURS:
                raise PolicyError('a step goes to primary or backup, in any or duty hours')
            outside = step.get('outsideHours', [])
            if not isinstance(outside, list) or any(channel not in CHANNELS for channel in outside):
                raise PolicyError('outsideHours lists channels')
            if checked and after < checked[-1]['after']:
                raise PolicyError('steps are in order of after')
            checked.append({'after': after, 'to': step['to'], 'channels': _list(step.get('channels'), CHANNELS, 'channels'),
                            'hours': step.get('hours', 'any'), 'outsideHours': list(dict.fromkeys(outside))})
        policy['escalation'][priority] = checked
    repeat = _clean(raw.get('repeat') or {})
    policy['repeat'] = {}
    for priority in PRIORITIES:
        row = _clean(repeat.get(priority) or {'rounds': 1})
        rounds = row.get('rounds', 1)
        if type(rounds) is not int or not 1 <= rounds <= 10:
            raise PolicyError('rounds must be 1 to 10')
        period = _number(row.get('periodSeconds', 0), 'periodSeconds') if rounds > 1 else 0.0
        if rounds > 1 and period <= policy['escalation'][priority][-1]['after']:
            raise PolicyError('a repeat period must be longer than the chain')
        policy['repeat'][priority] = {'rounds': rounds, 'periodSeconds': period}
    records = _clean(raw.get('records', {}))
    policy['records'] = {p: _list(records[p], RECORDS, 'records') if records.get(p) else [] for p in PRIORITIES}
    suppression = _clean(raw.get('suppression') or {})
    never = _rules(suppression.get('neverSuppress', []), 'neverSuppress')
    inhibit = []
    for row in suppression.get('inhibit', []):
        if not isinstance(row, dict) or not RULE.match(str(row.get('when', ''))):
            raise PolicyError('an inhibit row needs when and suppress')
        inhibit.append({'when': row['when'], 'suppress': [r for r in _rules(row.get('suppress'), 'suppress') if r != row['when']]})
    maintenance = []
    for row in suppression.get('maintenance', []):
        if not isinstance(row, dict):
            raise PolicyError('a maintenance window is an object')
        begin, finish = _number(row.get('start'), 'start'), _number(row.get('end'), 'end')
        if finish <= begin:
            raise PolicyError('a maintenance window needs start < end (epoch seconds)')
        maintenance.append({'start': begin, 'end': finish, 'rules': _rules(row.get('rules', ['*']), 'rules', star=True)})
    storm = _clean(suppression.get('storm', {}))
    limits = _clean(storm.get('limits', {}))
    if any(channel not in CHANNELS or type(count) is not int or count < 1 for channel, count in limits.items()):
        raise PolicyError('storm limits are positive integers per channel')
    clear_after = suppression.get('resolveAfterClearEvaluations', 2)
    if type(clear_after) is not int or clear_after < 1:
        raise PolicyError('resolveAfterClearEvaluations must be at least 1')
    policy['suppression'] = {
        'neverSuppress': never, 'inhibit': inhibit, 'maintenance': maintenance,
        'reopenWithinSeconds': _number(suppression.get('reopenWithinSeconds', 600), 'reopenWithinSeconds'),
        'resolveAfterClearEvaluations': clear_after,
        'noDataRules': _rules(suppression.get('noDataRules', ['SILENT_HALT_HEALTH_UNANSWERED', 'SILENT_HALT_DATABASE',
                                                            'SILENT_HALT_SECTION']), 'noDataRules'),
        'storm': {'windowSeconds': _number(storm.get('windowSeconds', 600), 'windowSeconds', minimum=1), 'limits': dict(limits)}}
    fallback = _clean(raw.get('fallback', {}))
    policy['fallback'] = {'escalateNowWhenFirstChannelFails': bool(fallback.get('escalateNowWhenFirstChannelFails', True))}
    hold = _clean(raw.get('autoHold', {}))
    if hold.get('severity', 'page') not in SEVERITIES:
        raise PolicyError('autoHold severity is page, warn or info')
    policy['autoHold'] = {'rules': _rules(hold.get('rules', []), 'autoHold rules'), 'severity': hold.get('severity', 'page')}
    policy['heartbeat'] = {'maxAgeSeconds': _number(_clean(raw.get('heartbeat') or {}).get('maxAgeSeconds', 180), 'maxAgeSeconds', minimum=1)}
    policy['roster'] = validate_roster(raw.get('roster') or {'shifts': [], 'people': {}})
    return policy


def validate_roster(raw):
    """Shifts in the policy time zone ({days, start, end, primary, backup}; first match wins; end may be 24:00 or wrap
    past midnight) and people ({id: {push, email, phone}} holding opaque destination references, never an address)."""
    raw = _clean(raw)
    if not isinstance(raw, dict) or not isinstance(raw.get('shifts', []), list) or not isinstance(raw.get('people', {}), dict):
        raise PolicyError('a roster has shifts and people')
    people = {}
    for person, destinations in _clean(raw.get('people', {})).items():
        destinations = _clean(destinations)
        if not PERSON.match(str(person)) or not isinstance(destinations, dict) or set(destinations) - set(CHANNELS):
            raise PolicyError('a person has push, email and phone references')
        people[person] = {channel: destinations.get(channel) if isinstance(destinations.get(channel), str) and destinations.get(channel) else None
                          for channel in CHANNELS}
    shifts = []
    for shift in raw.get('shifts', []):
        if not isinstance(shift, dict):
            raise PolicyError('a shift is an object')
        days = shift.get('days', 'daily')
        days = list(DAYS) if days == 'daily' else _list(days, DAYS, 'days')
        start, end = _minutes(shift.get('start', '00:00'), allow_24=False), _minutes(shift.get('end', '24:00'))
        if start == end:
            raise PolicyError('a shift must not be empty')
        for role in TARGETS:
            if shift.get(role) is not None and not PERSON.match(str(shift[role])):
                raise PolicyError('a shift names people by id')
        shifts.append({'days': days, 'start': start, 'end': end, 'primary': shift.get('primary'), 'backup': shift.get('backup')})
    return {'shifts': shifts, 'people': people}


def load(path=DEFAULT_PATH):
    return validate(json.loads(Path(path).read_text()))


# --- time ----------------------------------------------------------------------------------------------------------------

def local(now, policy):
    return datetime.fromtimestamp(float(now), _zone(policy['timeZone']))


def _wall(date, minute, zone):
    """Epoch seconds of a local wall time on a date; 24:00 is the next day's 00:00."""
    if minute >= 1440:
        date, minute = date + timedelta(days=1), minute - 1440
    return datetime.combine(date, day_time(minute // 60, minute % 60), zone).timestamp()


def duty_windows(first, last, policy):
    """[(start, end)] epoch seconds of the duty windows that start on local dates first..last (holidays have none)."""
    zone, duty = _zone(policy['timeZone']), policy['dutyHours']
    windows, date = [], first
    while date <= last:
        if date.isoformat() not in duty['holidays']:
            end = duty['end'] if duty['end'] > duty['start'] else duty['end'] + 1440
            windows.append((_wall(date, duty['start'], zone), _wall(date, end, zone)))
        date += timedelta(days=1)
    return windows


def in_duty(now, policy):
    """Inside the routine duty window (every day; a holiday has none), local wall time."""
    day = local(now, policy).date()
    return any(start <= now < end for start, end in duty_windows(day - timedelta(days=1), day, policy))


def next_duty_start(now, policy):
    """Epoch seconds of the next moment inside duty hours (now when inside them)."""
    if in_duty(now, policy):
        return float(now)
    day = local(now, policy).date()
    for offset in range(0, 400, 7):
        for start, _ in duty_windows(day + timedelta(days=offset), day + timedelta(days=offset + 6), policy):
            if start > now:
                return start
    raise PolicyError('no duty hours within a year')


def duty_seconds(since, until, policy):
    """Seconds of [since, until) that fall inside duty hours."""
    if until <= since:
        return 0.0
    first, last = local(since, policy).date() - timedelta(days=1), local(until, policy).date()
    return float(sum(max(0.0, min(until, end) - max(since, start)) for start, end in duty_windows(first, last, policy)))


# --- roster ----------------------------------------------------------------------------------------------------------------

def _shift_at(roster, day_index, minute):
    day, previous = DAYS[day_index], DAYS[(day_index - 1) % 7]
    for shift in roster['shifts']:
        start, end = shift['start'], shift['end']
        if start < end and day in shift['days'] and start <= minute < end:
            return shift
        if start > end and ((day in shift['days'] and minute >= start) or (previous in shift['days'] and minute < end)):
            return shift
    return None


def on_call(now, policy, roster=None):
    """(primary, backup) person ids at `now`, from the first shift that covers that local day and minute."""
    moment = local(now, policy)
    shift = _shift_at(roster or policy['roster'], moment.weekday(), moment.hour * 60 + moment.minute)
    return (shift['primary'], shift['backup']) if shift else (None, None)


def roster_problems(policy, roster=None):
    """Why the roster cannot carry the policy, as fixed codes (empty when it can): every minute of the week needs a
    Primary and a different Backup, each known and with push, e-mail and phone references for P0."""
    roster = roster or policy['roster']
    problems = set()
    for day_index in range(7):
        for minute in range(0, 1440, 15):
            shift = _shift_at(roster, day_index, minute)
            if shift is None:
                problems.add('coverage_gap')
                continue
            if not shift['primary']:
                problems.add('no_primary')
            if not shift['backup']:
                problems.add('no_backup')
            if shift['primary'] and shift['primary'] == shift['backup']:
                problems.add('primary_is_backup')
            for role in TARGETS:
                person = roster['people'].get(shift[role]) if shift[role] else None
                if shift[role] and person is None:
                    problems.add('unknown_person')
                elif person:
                    problems.update('%s_without_%s' % (role, channel) for channel in CHANNELS if not person.get(channel))
    return sorted(problems)


# --- priorities ------------------------------------------------------------------------------------------------------------

def priority_for(alert, policy):
    """The priority of one evaluator alert: the first matching row (rule, severity and every listed evidence value),
    else the default for its severity, else None (not routed)."""
    rule, severity = alert.get('id'), alert.get('severity')
    evidence = alert.get('evidence') if isinstance(alert.get('evidence'), dict) else {}
    for row in policy['priorities']:
        if row['rule'] == rule and row['severity'] == severity and all(evidence.get(k) == v for k, v in row['evidence'].items()):
            return row['priority']
    return policy['defaults'].get(severity)


def rank(priority):
    """P0 is the highest: 3, P1 2, P2 1, anything else 0."""
    return {'P0': 3, 'P1': 2, 'P2': 1}.get(priority, 0)
