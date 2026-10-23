"""Persistence for the on-call engine. One interface, two implementations:

- MemoryStore: tests and drills.
- PostgresStore: the tables of migrations/postriff/140_rafii_control_oncall.sql (NOT applied anywhere), through the
  rafii_control_session role with the environment GUC, like rafii_control.store.PostgresStore.

Guarantees the engine relies on: at most one live (not resolved) incident per dedupe key; optimistic versions on
incidents; append-only events with optional once-keys (an event that must happen once, such as a step starting);
deliveries claimed by a unique key before the provider is called, so two engines never send the same notification.
"""
import copy
import json
from contextlib import contextmanager
from datetime import datetime, timezone

ENVIRONMENTS = ('local', 'staging', 'production')
LIVE = ('open', 'acknowledged')
COUNTED = ('pending', 'accepted')
FAILED = ('failed', 'unconfigured', 'refused')


class Conflict(Exception):
    """The incident changed since it was read (version), or a live incident with the key already exists."""


class StoreUnavailable(Exception):
    pass


class MemoryStore:
    def __init__(self):
        self._incidents, self._events, self._once, self._deliveries, self._beat = {}, [], set(), {}, None

    # incidents
    def insert_incident(self, incident):
        if any(row['key'] == incident['key'] and row['state'] in LIVE for row in self._incidents.values()):
            raise Conflict('live incident exists')
        row = copy.deepcopy(incident)
        row['version'] = 1
        self._incidents[row['id']] = row
        return copy.deepcopy(row)

    def update_incident(self, incident):
        current = self._incidents.get(incident['id'])
        if current is None or current['version'] != incident['version']:
            raise Conflict('version')
        if incident['state'] in LIVE and any(row['key'] == incident['key'] and row['state'] in LIVE and row['id'] != incident['id']
                                             for row in self._incidents.values()):
            raise Conflict('live incident exists')
        row = copy.deepcopy(incident)
        row['version'] = current['version'] + 1
        self._incidents[row['id']] = row
        return copy.deepcopy(row)

    def incident(self, incident_id):
        row = self._incidents.get(incident_id)
        return copy.deepcopy(row) if row else None

    def latest(self, key):
        rows = [row for row in self._incidents.values() if row['key'] == key]
        return copy.deepcopy(max(rows, key=lambda row: (row['openedAt'], row['state'] in LIVE))) if rows else None

    def live(self):
        return [copy.deepcopy(row) for row in sorted(self._incidents.values(), key=lambda row: row['openedAt']) if row['state'] in LIVE]

    def incidents(self):
        return [copy.deepcopy(row) for row in sorted(self._incidents.values(), key=lambda row: row['openedAt'])]

    # events: append-only
    def append(self, event, once=None):
        if once is not None:
            if once in self._once:
                return False
            self._once.add(once)
        row = copy.deepcopy(event)
        row['seq'] = len(self._events) + 1
        self._events.append(row)
        return True

    def once_exists(self, once):
        return once in self._once

    def events(self, incident_id=None):
        return [copy.deepcopy(e) for e in self._events if incident_id is None or e.get('incidentId') == incident_id]

    # deliveries
    def claim(self, row):
        if row['key'] in self._deliveries:
            return False
        self._deliveries[row['key']] = dict(row, status='pending', finishedAt=None, reference=None, reason=None)
        return True

    def finish(self, key, status, reference, reason, at):
        row = self._deliveries[key]
        if row['status'] == 'pending':
            row.update(status=status, reference=reference, reason=reason, finishedAt=at)

    def delivery(self, key):
        row = self._deliveries.get(key)
        return dict(row) if row else None

    def deliveries(self, incident_id=None):
        return [dict(row) for row in self._deliveries.values() if incident_id is None or row['incidentId'] == incident_id]

    def recent(self, person, channel, since):
        return sum(1 for row in self._deliveries.values() if row['person'] == person and row['channel'] == channel
                   and row['kind'] != 'summary' and row['status'] in COUNTED and row['claimedAt'] >= since)

    def failures(self, since):
        return sum(1 for row in self._deliveries.values() if row['status'] in FAILED and row['claimedAt'] >= since)

    # heartbeat
    def save_heartbeat(self, row):
        self._beat = copy.deepcopy(row)

    def heartbeat(self):
        return copy.deepcopy(self._beat)


# --- PostgreSQL ------------------------------------------------------------------------------------------------------------

def _ts(epoch):
    return None if epoch is None else datetime.fromtimestamp(float(epoch), timezone.utc)


def _ep(moment):
    return None if moment is None else moment.timestamp()


_INCIDENT = (('id', 'id'), ('key', 'dedupe_key'), ('rule', 'rule'), ('class', 'alert_class'), ('severity', 'severity'),
             ('priority', 'priority'), ('state', 'state'), ('openedAt', 'opened_at'), ('lastSeenAt', 'last_seen_at'),
             ('updatedAt', 'updated_at'), ('chainStartedAt', 'chain_started_at'), ('suppressedBy', 'suppressed_by'),
             ('forcedStep', 'forced_step'), ('clearCount', 'clear_count'), ('seenCount', 'seen_count'), ('notified', 'notified'),
             ('steps', 'steps'), ('message', 'message'), ('acknowledgedAt', 'acknowledged_at'), ('acknowledgedBy', 'acknowledged_by'),
             ('ackChannel', 'ack_channel'), ('resolvedAt', 'resolved_at'), ('resolution', 'resolution'), ('version', 'version'))
_TIMES = {'openedAt', 'lastSeenAt', 'updatedAt', 'chainStartedAt', 'acknowledgedAt', 'resolvedAt'}
_COLUMNS = ','.join(column for _, column in _INCIDENT)


def _to_row(incident):
    values = []
    for key, column in _INCIDENT:
        value = incident.get(key)
        if key in _TIMES:
            value = _ts(value)
        elif key == 'steps':
            from psycopg.types.json import Jsonb
            value = Jsonb(dict(value or {}))
        elif key == 'notified':
            value = list(value or [])
        elif key == 'id':
            value = str(value)
        values.append(value)
    return values


def _from_row(row):
    incident = {}
    for key, column in _INCIDENT:
        value = row[column]
        if key in _TIMES:
            value = _ep(value)
        elif key == 'id':
            value = str(value)
        elif key == 'notified':
            value = list(value or [])
        elif key == 'steps':
            value = dict(value or {})
        incident[key] = value
    return incident


class PostgresStore:
    """Migration 140's tables through rafii_control_session (never a superuser or a BYPASSRLS role)."""
    ROLE = 'rafii_control_session'

    def __init__(self, session_factory, environment):
        if environment not in ENVIRONMENTS:
            raise ValueError('environment must be local, staging or production')
        self.session_factory, self.environment = session_factory, environment

    @contextmanager
    def _tx(self):
        from psycopg.rows import dict_row
        with self.session_factory() as con:
            con.row_factory = dict_row
            with con.transaction():
                role = con.execute('SELECT current_user AS name, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
                if not role or role['name'] != self.ROLE or role['rolsuper'] or role['rolbypassrls']:
                    raise StoreUnavailable('the on-call store runs only as %s' % self.ROLE)
                con.execute("SELECT set_config('rafii_control.environment',%s,true)", (self.environment,))
                yield con

    def insert_incident(self, incident):
        import psycopg
        row = dict(incident, version=1)
        try:
            with self._tx() as con:
                con.execute('INSERT INTO rafii_control.oncall_incidents(environment,%s) VALUES(%%s,%s)' % (_COLUMNS, ','.join(['%s'] * len(_INCIDENT))),
                            [self.environment, *_to_row(row)])
        except psycopg.errors.UniqueViolation:
            raise Conflict('live incident exists') from None
        return self.incident(row['id'])

    def update_incident(self, incident):
        import psycopg
        assignments = ','.join('%s=%%s' % column for key, column in _INCIDENT if key not in ('id', 'version'))
        values = [value for (key, _), value in zip(_INCIDENT, _to_row(incident)) if key not in ('id', 'version')]
        try:
            with self._tx() as con:
                done = con.execute('UPDATE rafii_control.oncall_incidents SET %s,version=version+1 WHERE id=%%s AND version=%%s' % assignments,
                                   [*values, str(incident['id']), incident['version']])
                if done.rowcount != 1:
                    raise Conflict('version')
        except psycopg.errors.UniqueViolation:
            raise Conflict('live incident exists') from None
        return self.incident(incident['id'])

    def incident(self, incident_id):
        with self._tx() as con:
            row = con.execute('SELECT %s FROM rafii_control.oncall_incidents WHERE id=%%s' % _COLUMNS, (str(incident_id),)).fetchone()
        return _from_row(row) if row else None

    def latest(self, key):
        with self._tx() as con:
            row = con.execute("SELECT %s FROM rafii_control.oncall_incidents WHERE dedupe_key=%%s ORDER BY opened_at DESC, (state<>'resolved') DESC LIMIT 1" % _COLUMNS,
                              (key,)).fetchone()
        return _from_row(row) if row else None

    def live(self):
        with self._tx() as con:
            rows = con.execute("SELECT %s FROM rafii_control.oncall_incidents WHERE state<>'resolved' ORDER BY opened_at" % _COLUMNS).fetchall()
        return [_from_row(row) for row in rows]

    def incidents(self):
        with self._tx() as con:
            rows = con.execute('SELECT %s FROM rafii_control.oncall_incidents ORDER BY opened_at' % _COLUMNS).fetchall()
        return [_from_row(row) for row in rows]

    def append(self, event, once=None):
        with self._tx() as con:
            done = con.execute('INSERT INTO rafii_control.oncall_events(environment,incident_id,at,kind,actor,once_key,detail) '
                               'VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING',
                               (self.environment, event.get('incidentId'), _ts(event['at']), event['kind'], event.get('actor'), once,
                                json.dumps(event.get('detail') or {}, sort_keys=True)))
            return done.rowcount == 1

    def once_exists(self, once):
        with self._tx() as con:
            return con.execute('SELECT 1 FROM rafii_control.oncall_events WHERE once_key=%s', (once,)).fetchone() is not None

    def events(self, incident_id=None):
        with self._tx() as con:
            rows = con.execute('SELECT id,incident_id,at,kind,actor,detail FROM rafii_control.oncall_events '
                               'WHERE (%s::uuid IS NULL OR incident_id=%s::uuid) ORDER BY id', (incident_id, incident_id)).fetchall()
        return [{'seq': row['id'], 'incidentId': str(row['incident_id']) if row['incident_id'] else None, 'at': _ep(row['at']),
                 'kind': row['kind'], 'actor': row['actor'], 'detail': dict(row['detail'])} for row in rows]

    def claim(self, row):
        with self._tx() as con:
            done = con.execute('INSERT INTO rafii_control.oncall_deliveries(environment,dedupe_key,incident_id,person,channel,kind,step,status,claimed_at) '
                               "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending',%s) ON CONFLICT DO NOTHING",
                               (self.environment, row['key'], row.get('incidentId'), row['person'], row['channel'], row['kind'],
                                row.get('step'), _ts(row['claimedAt'])))
            return done.rowcount == 1

    def finish(self, key, status, reference, reason, at):
        with self._tx() as con:
            con.execute("UPDATE rafii_control.oncall_deliveries SET status=%s,reference=%s,reason=%s,finished_at=%s WHERE dedupe_key=%s AND status='pending'",
                        (status, reference, reason, _ts(at), key))

    def _delivery(self, row):
        return {'key': row['dedupe_key'], 'incidentId': str(row['incident_id']) if row['incident_id'] else None, 'person': row['person'],
                'channel': row['channel'], 'kind': row['kind'], 'step': row['step'], 'status': row['status'],
                'claimedAt': _ep(row['claimed_at']), 'finishedAt': _ep(row['finished_at']), 'reference': row['reference'], 'reason': row['reason']}

    def delivery(self, key):
        with self._tx() as con:
            row = con.execute('SELECT * FROM rafii_control.oncall_deliveries WHERE dedupe_key=%s', (key,)).fetchone()
        return self._delivery(row) if row else None

    def deliveries(self, incident_id=None):
        with self._tx() as con:
            rows = con.execute('SELECT * FROM rafii_control.oncall_deliveries WHERE (%s::uuid IS NULL OR incident_id=%s::uuid) ORDER BY claimed_at,dedupe_key',
                               (incident_id, incident_id)).fetchall()
        return [self._delivery(row) for row in rows]

    def recent(self, person, channel, since):
        with self._tx() as con:
            return con.execute("SELECT count(*) AS n FROM rafii_control.oncall_deliveries WHERE person=%s AND channel=%s AND kind<>'summary' "
                               "AND status IN ('pending','accepted') AND claimed_at>=%s", (person, channel, _ts(since))).fetchone()['n']

    def failures(self, since):
        with self._tx() as con:
            return con.execute("SELECT count(*) AS n FROM rafii_control.oncall_deliveries WHERE status IN ('failed','unconfigured','refused') "
                               'AND claimed_at>=%s', (_ts(since),)).fetchone()['n']

    def save_heartbeat(self, row):
        with self._tx() as con:
            con.execute('INSERT INTO rafii_control.oncall_heartbeat(environment,at,payload) VALUES(%s,%s,%s::jsonb) '
                        'ON CONFLICT(environment) DO UPDATE SET at=excluded.at,payload=excluded.payload',
                        (self.environment, _ts(row['at']), json.dumps(row, sort_keys=True)))

    def heartbeat(self):
        with self._tx() as con:
            row = con.execute('SELECT payload FROM rafii_control.oncall_heartbeat').fetchone()
        return dict(row['payload']) if row else None
