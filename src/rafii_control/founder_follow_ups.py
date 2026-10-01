"""Founder follow-ups (Founder Admin v2, CONTRACTS §3 `/follow-ups`).

Boundaries. A follow-up is a reminder Rafii prepared (`founder_tools.founder_reminder_prepare`) and the founder confirmed
in the panel, or one the founder edits on the Overview; it is the founder's own operational record, never customer data,
so the Live rows serve both data modes. Rows live in rafii_control.founder_follow_ups (054: forced RLS, policy
`own_follow_ups` keyed on the rafii_control.operator GUC, which the SQL mixin sets transaction-locally) and are read and
written only through the restricted session store. Nothing here contacts anyone: a due follow-up is shown, never dialed
or sent. Writes are revision-checked (STALE_PREVIEW on a mismatch) and the evidence object is bounded, so a page cannot
park a customer conversation in it. Timestamps are ISO 8601 UTC strings, as the web contract (`lib/founder/types.ts`)
declares them.
"""
from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg.types.json import Jsonb

from .auth import ControlError

STATES = ('draft', 'scheduled', 'due', 'completed', 'cancelled', 'missed')
OPEN_STATES = ('draft', 'scheduled', 'due')
# Which stored states a write may move to (the current state is always allowed, so a title edit needs no state).
TRANSITIONS = {'draft': ('draft', 'scheduled', 'cancelled'), 'scheduled': ('scheduled', 'due', 'completed', 'cancelled', 'missed'),
               'due': ('due', 'scheduled', 'completed', 'cancelled', 'missed'), 'completed': ('completed',), 'cancelled': ('cancelled',),
               'missed': ('missed', 'scheduled')}
DEFAULT_SOURCE_TYPE = 'manual'
DEFAULT_TIME_ZONE = 'America/Indiana/Indianapolis'
MAX_OPEN = 50
MAX_LIST = 200
EVIDENCE_BYTES = 4000
PAST_SECONDS = 24 * 3600
FUTURE_SECONDS = 366 * 24 * 3600
_SOURCE_TYPE = re.compile(r'[a-z][a-z0-9_]{0,39}\Z')
_SOURCE_ID = re.compile(r'[A-Za-z0-9:_.\-/]{1,160}\Z')
_CREATE_FIELDS = {'sourceType', 'sourceId', 'title', 'dueAt', 'timeZone', 'state', 'evidence'}
_UPDATE_FIELDS = {'title', 'dueAt', 'timeZone', 'state', 'evidence', 'revision'}


def stamp(value):
    """Epoch seconds → ISO 8601 UTC with a Z suffix; None stays None."""
    return None if value is None else datetime.fromtimestamp(float(value), timezone.utc).isoformat().replace('+00:00', 'Z')


def parse_due(value):
    """An aware ISO 8601 instant → epoch seconds, or None. A naive stamp is refused rather than guessed."""
    if value is None:
        return None
    if not isinstance(value, str) or not 10 <= len(value) <= 40:
        raise ControlError('VALIDATION_FAILED', 400)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ControlError('VALIDATION_FAILED', 400) from None
    if parsed.tzinfo is None:
        raise ControlError('VALIDATION_FAILED', 400)
    return parsed.timestamp()


def validate_zone(zone):
    try:
        if not isinstance(zone, str) or not 1 <= len(zone) <= 80:
            raise ValueError
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ControlError('VALIDATION_FAILED', 400) from None
    return zone


def validate_title(title):
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        raise ControlError('VALIDATION_FAILED', 400)
    return title.strip()


def validate_evidence(evidence):
    """A small JSON object of ids and receipt ids; size-bounded so it never becomes a transcript."""
    if evidence is None:
        return {}
    if not isinstance(evidence, dict) or any(not isinstance(key, str) for key in evidence):
        raise ControlError('VALIDATION_FAILED', 400)
    try:
        encoded = json.dumps(evidence, allow_nan=False)
    except (TypeError, ValueError):
        raise ControlError('VALIDATION_FAILED', 400) from None
    if len(encoded.encode()) > EVIDENCE_BYTES:
        raise ControlError('VALIDATION_FAILED', 400)
    return json.loads(encoded)


def validate_due_window(due_at, now):
    if due_at is not None and not now - PAST_SECONDS <= due_at <= now + FUTURE_SECONDS:
        raise ControlError('VALIDATION_FAILED', 400)
    return due_at


def validate_create(body, now):
    """POST /follow-ups body → stored fields. Unknown keys are refused; a scheduled follow-up needs a due time."""
    if not isinstance(body, dict) or set(body) - _CREATE_FIELDS or 'title' not in body:
        raise ControlError('VALIDATION_FAILED', 400)
    source_type = body.get('sourceType', DEFAULT_SOURCE_TYPE)
    if not isinstance(source_type, str) or not _SOURCE_TYPE.fullmatch(source_type):
        raise ControlError('VALIDATION_FAILED', 400)
    source_id = body.get('sourceId')
    if source_id is not None and (not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id)):
        raise ControlError('VALIDATION_FAILED', 400)
    due_at = validate_due_window(parse_due(body.get('dueAt')), now)
    state = body.get('state', 'scheduled' if due_at is not None else 'draft')
    if state not in ('draft', 'scheduled') or (state == 'scheduled' and due_at is None):
        raise ControlError('VALIDATION_FAILED', 400)
    return {'source_type': source_type, 'source_id': source_id, 'title': validate_title(body['title']), 'due_at': due_at,
            'time_zone': validate_zone(body.get('timeZone', DEFAULT_TIME_ZONE)), 'state': state, 'evidence': validate_evidence(body.get('evidence'))}


def validate_update(body, now):
    """POST /follow-ups/{id} body → changed fields (snake_case) plus the optional expected revision."""
    if not isinstance(body, dict) or set(body) - _UPDATE_FIELDS or not body:
        raise ControlError('VALIDATION_FAILED', 400)
    fields = {}
    if 'title' in body:
        fields['title'] = validate_title(body['title'])
    if 'dueAt' in body:
        fields['due_at'] = validate_due_window(parse_due(body['dueAt']), now)
    if 'timeZone' in body:
        fields['time_zone'] = validate_zone(body['timeZone'])
    if 'state' in body:
        if body['state'] not in STATES:
            raise ControlError('VALIDATION_FAILED', 400)
        fields['state'] = body['state']
    if 'evidence' in body:
        fields['evidence'] = validate_evidence(body['evidence'])
    revision = body.get('revision')
    if revision is not None and (type(revision) is not int or revision < 1):
        raise ControlError('VALIDATION_FAILED', 400)
    return fields, revision


def validate_id(follow_up_id):
    try:
        return str(uuid.UUID(str(follow_up_id)))
    except (ValueError, TypeError):
        raise ControlError('VALIDATION_FAILED', 400) from None


def effective_state(row, now):
    """A scheduled follow-up whose time has passed reads as 'due'; the stored state changes only through an update."""
    if row['state'] == 'scheduled' and row.get('due_at') is not None and now is not None and float(row['due_at']) <= float(now):
        return 'due'
    return row['state']


def public_follow_up(row, now=None):
    return {'id': row['id'], 'sourceType': row['source_type'], 'sourceId': row['source_id'], 'title': row['title'], 'dueAt': stamp(row.get('due_at')),
            'timeZone': row['time_zone'], 'state': effective_state(row, now), 'evidence': dict(row.get('evidence') or {}), 'revision': int(row['revision']),
            'createdAt': stamp(row['created_at']), 'updatedAt': stamp(row['updated_at']), 'href': '/founder?tab=follow-ups'}


def _order_key(row):
    """Open follow-ups first, soonest due (undated last); closed ones afterwards, most recently changed first."""
    is_open = row['state'] in OPEN_STATES
    due = row.get('due_at')
    return (0 if is_open else 1, 0 if due is not None else 1, float(due) if due is not None and is_open else 0.0, -float(row['updated_at']), row['id'])


def list_follow_ups(fstore, principal, *, now, limit=100):
    """GET /follow-ups: the operator's own rows, open ones first. `due` is derived from `now`."""
    rows = sorted(fstore.follow_ups(principal['operator']['user_id'], limit=max(1, min(int(limit), MAX_LIST))), key=_order_key)
    items = [public_follow_up(row, now) for row in rows]
    return {'followUps': items, 'open': sum(1 for item in items if item['state'] in OPEN_STATES)}


def create(fstore, principal, body, *, now):
    """POST /follow-ups (followups.write). Idempotent on (sourceType, sourceId): a replay returns the stored row with
    `created: false`. Without a sourceId the new row's id is its own source."""
    operator = principal['operator']['user_id']
    fields = validate_create(body, now)
    if sum(1 for row in fstore.follow_ups(operator, limit=MAX_LIST) if row['state'] in OPEN_STATES) >= MAX_OPEN:
        raise ControlError('BUDGET_EXCEEDED', 409)
    follow_up_id = str(uuid.uuid4())
    row = {'id': follow_up_id, 'operator_id': operator, 'environment': fstore.environment, **fields, 'revision': 1, 'created_at': now, 'updated_at': now}
    if row['source_id'] is None:
        row['source_id'] = follow_up_id
    stored = fstore.insert_follow_up(row)
    return {'followUp': public_follow_up(stored, now), 'created': stored['id'] == follow_up_id}


def update(fstore, principal, follow_up_id, body, *, now):
    """POST /follow-ups/{id} (followups.write). The body's `revision`, when given, must match the stored row and the
    update itself is a compare-and-set on that revision, so two tabs cannot silently overwrite each other."""
    operator = principal['operator']['user_id']
    follow_up_id = validate_id(follow_up_id)
    fields, expected = validate_update(body, now)
    current = fstore.follow_up(operator, follow_up_id)
    if current is None:
        raise ControlError('VALIDATION_FAILED', 404)
    if expected is not None and expected != int(current['revision']):
        raise ControlError('STALE_PREVIEW', 409)
    next_state = fields.get('state', current['state'])
    if next_state not in TRANSITIONS[current['state']]:
        raise ControlError('VALIDATION_FAILED', 400)
    due_at = fields['due_at'] if 'due_at' in fields else current.get('due_at')
    if next_state in ('scheduled', 'due') and due_at is None:
        raise ControlError('VALIDATION_FAILED', 400)
    stored = fstore.update_follow_up(operator, follow_up_id, expected_revision=int(current['revision']), **fields, updated_at=now)
    if stored is None:
        raise ControlError('STALE_PREVIEW', 409)
    return {'followUp': public_follow_up(stored, now)}


# --- SQL (rafii_control_session role; 054 policy own_follow_ups on the environment and operator GUCs) ---------------------
_FOLLOW_UP_SELECT = ('SELECT id::text,operator_id::text AS operator_id,environment,source_type,source_id,title,extract(epoch from due_at) AS due_at,'
                     'time_zone,state,evidence,revision,extract(epoch from created_at) AS created_at,extract(epoch from updated_at) AS updated_at '
                     'FROM rafii_control.founder_follow_ups')
_FOLLOW_UP_FIELDS = frozenset(('title', 'due_at', 'time_zone', 'state', 'evidence', 'updated_at'))


def _follow_up_row(row):
    return {**row, 'due_at': None if row['due_at'] is None else float(row['due_at']), 'evidence': dict(row.get('evidence') or {}),
            'created_at': float(row['created_at']), 'updated_at': float(row['updated_at'])}


class FollowUpSQL:
    """Follow-up rows. `self.store` is a rafii_control.store.PostgresStore; every statement runs with the operator GUC set
    transaction-locally (as workspace.py does), which the 054 policy requires before it shows or accepts a row."""

    @contextmanager
    def _operator_transaction(self, operator_id):
        with self.store.transaction() as con:
            con.execute("SELECT set_config('rafii_control.operator',%s,true)", (str(operator_id),))
            yield con

    def follow_ups(self, operator_id, *, limit=100):
        with self._operator_transaction(operator_id) as con:
            rows = con.execute(_FOLLOW_UP_SELECT + ' WHERE operator_id=%s AND environment=%s ORDER BY created_at DESC,id LIMIT %s',
                               (operator_id, self.environment, max(1, min(int(limit), MAX_LIST)))).fetchall()
        return [_follow_up_row(r) for r in rows]

    def follow_up(self, operator_id, follow_up_id):
        with self._operator_transaction(operator_id) as con:
            row = con.execute(_FOLLOW_UP_SELECT + ' WHERE id=%s AND operator_id=%s AND environment=%s', (follow_up_id, operator_id, self.environment)).fetchone()
        return _follow_up_row(row) if row else None

    def insert_follow_up(self, row):
        """Insert, or return the row that already owns (operator, environment, source_type, source_id)."""
        with self._operator_transaction(row['operator_id']) as con:
            con.execute('INSERT INTO rafii_control.founder_follow_ups(id,operator_id,environment,source_type,source_id,title,due_at,time_zone,state,evidence,revision,created_at,updated_at) '
                        'VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s)) '
                        'ON CONFLICT(operator_id,environment,source_type,source_id) DO NOTHING',
                        (row['id'], row['operator_id'], self.environment, row['source_type'], row['source_id'], row['title'], row['due_at'], row['time_zone'],
                         row['state'], Jsonb(row['evidence']), row['revision'], row['created_at'], row['updated_at']))
            stored = con.execute(_FOLLOW_UP_SELECT + ' WHERE operator_id=%s AND environment=%s AND source_type=%s AND source_id=%s',
                                 (row['operator_id'], self.environment, row['source_type'], row['source_id'])).fetchone()
        return _follow_up_row(stored)

    def update_follow_up(self, operator_id, follow_up_id, *, expected_revision, **fields):
        """Compare-and-set on the revision; None when another writer moved the row first."""
        if set(fields) - _FOLLOW_UP_FIELDS:
            raise ValueError('unknown follow-up field')
        assignments, values = ['revision=revision+1'], []
        for key, value in fields.items():
            assignments.append(f'{key}=to_timestamp(%s)' if key in ('due_at', 'updated_at') else f'{key}=%s')
            values.append(Jsonb(value) if key == 'evidence' else value)
        with self._operator_transaction(operator_id) as con:
            row = con.execute(f'UPDATE rafii_control.founder_follow_ups SET {",".join(assignments)} WHERE id=%s AND operator_id=%s AND environment=%s AND revision=%s RETURNING id::text',
                              (*values, follow_up_id, operator_id, self.environment, expected_revision)).fetchone()
            if not row:
                return None
            stored = con.execute(_FOLLOW_UP_SELECT + ' WHERE id=%s AND environment=%s', (follow_up_id, self.environment)).fetchone()
        return _follow_up_row(stored)
