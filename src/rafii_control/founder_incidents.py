"""Founder incidents: deterministic P0 detectors, episode lifecycle and acknowledgement (Founder Admin v2, CONTRACTS §5).

Boundaries. Detectors are pure functions over an `observations` dict that the cron assembles from fixed queries (counts,
states and timestamps only; never customer text). Thresholds are versioned constants, so an incident's evidence names the
threshold version that opened it. One episode per (detector, scope) stays open until its condition is observed to have
cleared: a tick whose inputs were unavailable (`observed_detectors`) is absence of evidence, never recovery. Repeated
findings refresh the same row (evidence, affected count, severity never lowered) instead of opening a duplicate; only a
severity or state transition bumps the version, so an acknowledgement bound to the version the page showed survives
evidence drift between ticks, and the timeline records an event only when the affected count or severity changes. An
acknowledgement cancels pending (not yet dialed) founder contact attempts; it is not a resolution. Notifications go through the shared transactional outbox with workspace_id=None, user_id=operator.
"""
from __future__ import annotations

import statistics
import uuid
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from .auth import ControlError
from .founder_sources import REQUIRED_SOURCES

DETECTORS = ('publish_failure_rate', 'source_silence', 'cost_anomaly', 'payment_failure_spike')
SEVERITIES = ('warning', 'critical')
STATES = ('open', 'acknowledged', 'investigating', 'mitigated', 'resolved')
ACK_CHANNELS = ('web', 'phone', 'agent')
THRESHOLDS = {
    'publish_failure_rate': {'version': 1, 'window_minutes': 60, 'min_samples': 5, 'warning_rate': 0.25, 'critical_rate': 0.5},
    'source_silence': {'version': 1, 'silence_seconds': 180, 'critical_seconds': 900, 'sources': REQUIRED_SOURCES},
    'cost_anomaly': {'version': 1, 'multiplier': 3.0, 'min_today_usd_micro': 5_000_000, 'median_days': 7},
    'payment_failure_spike': {'version': 1, 'window_hours': 24, 'warning_count': 3, 'critical_count': 10},
}
# PRD §8.7 founder events. They are registered at emit time as catalogue extensions (catalog.EXTENSION_EVENTS), never
# written into catalog.EVENTS: that dict is hashed by the locked notification-planning policy and shown to customers.
NOTIFICATION_EVENTS = {
    'founder.incident_opened': {'category': 'founder', 'severity': 'critical', 'audience': 'actor', 'email': 'immediate', 'push': 'immediate', 'template': 'analytics_anomaly'},
    'founder.incident_recovered': {'category': 'founder', 'severity': 'info', 'audience': 'actor', 'email': 'digest', 'push': 'off', 'template': 'analytics_anomaly'},
    'founder.briefing_ready': {'category': 'founder', 'severity': 'info', 'audience': 'actor', 'email': 'digest', 'push': 'immediate', 'template': 'weekly_performance'},
    'founder.source_unavailable': {'category': 'founder', 'severity': 'warning', 'audience': 'actor', 'email': 'immediate', 'push': 'off', 'template': 'analytics_anomaly'},
}


def register_notification_events():
    from postriff_phase2.notifications import catalog
    catalog.register_extension_events({name: {**spec, 'sms': 'off'} for name, spec in NOTIFICATION_EVENTS.items()})


# --- detectors (pure) ----------------------------------------------------------------------------------------------------
def _finding(detector, scope, severity, evidence, affected_count):
    return {'detector': detector, 'scope': scope, 'severity': severity, 'affected_count': int(affected_count),
            'evidence': {**evidence, 'thresholdVersion': THRESHOLDS[detector]['version']}}


def publish_failure_rate(observations, now):
    """Failed+uncertain over all publish outcomes in the window; needs min_samples. Source: publish outcome counts."""
    t, publish = THRESHOLDS['publish_failure_rate'], observations.get('publish') or {}
    if not publish.get('available'):
        return None
    failed, uncertain, verified = (int(publish.get(k) or 0) for k in ('failed', 'uncertain', 'verified'))
    total = failed + uncertain + verified
    if total < t['min_samples']:
        return None
    rate = (failed + uncertain) / total
    if rate < t['warning_rate']:
        return None
    severity = 'critical' if rate >= t['critical_rate'] else 'warning'
    return _finding('publish_failure_rate', 'global', severity, {'windowMinutes': t['window_minutes'], 'failed': failed, 'uncertain': uncertain,
                                                                  'verified': verified, 'rate': round(rate, 4)}, failed + uncertain)


def source_silence(observations, now):
    """A required source is unavailable, or has not been checked, for silence_seconds. One finding per source."""
    t, out = THRESHOLDS['source_silence'], []
    rows = {row['source_id']: row for row in observations.get('sources') or [] if isinstance(row, dict) and row.get('source_id')}
    for source in t['sources']:
        row = rows.get(source)
        checked = float(row['checked_at']) if row and row.get('checked_at') is not None else None
        silent_for = now - checked if checked is not None else None
        down = row is not None and row.get('state') == 'unavailable'
        stale = silent_for is None or silent_for >= t['silence_seconds']
        if not (down or stale):
            continue
        if silent_for is None and row is None and not observations.get('sources_probed'):
            continue  # never probed: no evidence of silence yet
        seconds = silent_for if silent_for is not None else t['silence_seconds']
        severity = 'critical' if (down and seconds >= t['critical_seconds']) or seconds >= t['critical_seconds'] else 'warning'
        out.append(_finding('source_silence', source, severity, {'silentSeconds': int(seconds), 'state': (row or {}).get('state', 'missing'),
                                                                  'reasonCode': (row or {}).get('reason_code')}, 1))
    return out


def cost_anomaly(observations, now):
    """Today's actual AI cost exceeds the 7-day median by the multiplier (and a floor), or the budget stop is reached."""
    t, cost = THRESHOLDS['cost_anomaly'], observations.get('cost') or {}
    if not cost.get('available'):
        return None
    today = int(cost.get('today_usd_micro') or 0)
    history = [int(v) for v in (cost.get('daily_usd_micro') or []) if v is not None][-t['median_days']:]
    median = int(statistics.median(history)) if history else 0
    if cost.get('budget_stop_reached'):
        return _finding('cost_anomaly', 'global', 'critical', {'todayUsdMicro': today, 'medianUsdMicro': median, 'budgetStop': True}, 1)
    if today < t['min_today_usd_micro'] or not history or today < median * t['multiplier']:
        return None
    severity = 'critical' if median and today >= median * t['multiplier'] * 2 else 'warning'
    evidence = {'todayUsdMicro': today, 'medianUsdMicro': median, 'multiplier': t['multiplier'], 'days': len(history)}
    if cost.get('basis'):
        evidence['basis'] = str(cost['basis'])[:80]   # names what the spend covers (e.g. every workspace except exempt rows), unlike the receipted metric
    return _finding('cost_anomaly', 'global', severity, evidence, 1)


def payment_failure_spike(observations, now):
    """New past-due subscriptions in the window reach the warning/critical counts."""
    t, payments = THRESHOLDS['payment_failure_spike'], observations.get('payments') or {}
    if not payments.get('available'):
        return None
    count = int(payments.get('past_due_new') or 0)
    if count < t['warning_count']:
        return None
    severity = 'critical' if count >= t['critical_count'] else 'warning'
    return _finding('payment_failure_spike', 'global', severity, {'windowHours': t['window_hours'], 'pastDueNew': count}, count)


def observed_detectors(observations):
    """The detectors whose inputs this tick actually observed. An open episode of any other detector is left as it is:
    the cron could not see whether its condition cleared."""
    observations = observations or {}
    out = set()
    if (observations.get('publish') or {}).get('available'):
        out.add('publish_failure_rate')
    if (observations.get('cost') or {}).get('available'):
        out.add('cost_anomaly')
    if (observations.get('payments') or {}).get('available'):
        out.add('payment_failure_spike')
    if observations.get('sources_probed'):
        out.add('source_silence')
    return out


def detect(observations, now):
    """Every finding the observations imply, in detector order. Deterministic for equal inputs."""
    out = []
    for detector in (publish_failure_rate, cost_anomaly, payment_failure_spike):
        finding = detector(observations, now)
        if finding:
            out.append(finding)
    out.extend(source_silence(observations, now))
    return out


# --- episodes ----------------------------------------------------------------------------------------------------------------
def _rank(severity):
    return SEVERITIES.index(severity)


def evaluate(fstore, findings, now, *, notify=None, observed=None):
    """Reconcile findings with open episodes: open new ones, refresh or escalate existing ones, resolve cleared ones.
    `observed` is the set of detectors whose inputs were available this tick (`observed_detectors`); an open episode of
    an unobserved detector is reported under 'unobserved' and left open. None (unit callers) means every detector was
    observed. `notify(event_type, incident)` is called after each open/resolve; it must never raise into the loop."""
    open_by_key = {(row['detector'], row['scope']): row for row in fstore.open_incidents()}
    result = {'opened': [], 'updated': [], 'escalated': [], 'refreshed': [], 'resolved': [], 'unobserved': []}
    for finding in findings:
        key = (finding['detector'], finding['scope'])
        current = open_by_key.pop(key, None)
        if current is None:
            incident = fstore.insert_incident({'id': str(uuid.uuid4()), 'environment': fstore.environment, 'detector': finding['detector'],
                                               'scope': finding['scope'], 'episode_key': f"{finding['detector']}:{finding['scope']}:{int(now)}",
                                               'severity': finding['severity'], 'state': 'open', 'opened_at': now, 'acknowledged_at': None,
                                               'resolved_at': None, 'evidence': finding['evidence'], 'affected_count': finding['affected_count'],
                                               'version': 1})
            fstore.insert_incident_event(incident['id'], 'opened', now, {'severity': incident['severity'], 'evidence': incident['evidence']})
            result['opened'].append(incident['id'])
            _notify(notify, 'founder.source_unavailable' if incident['detector'] == 'source_silence' else 'founder.incident_opened', incident)
            continue
        severity = finding['severity'] if _rank(finding['severity']) > _rank(current['severity']) else current['severity']
        count_changed = finding['affected_count'] != current['affected_count']
        if finding['evidence'] == current['evidence'] and not count_changed and severity == current['severity']:
            continue
        fields = {'evidence': finding['evidence'], 'affected_count': finding['affected_count']}
        if severity != current['severity']:
            fields['severity'] = severity   # the only drift that bumps the version (store rule); evidence refreshes keep it
        incident = fstore.update_incident(current['id'], **fields)
        if 'severity' not in fields and not count_changed:
            result['refreshed'].append(incident['id'])   # drifting evidence (silent seconds, spend) is recorded without a timeline event
            continue
        kind = 'escalated' if 'severity' in fields else 'updated'
        fstore.insert_incident_event(incident['id'], kind, now, {'severity': severity, 'evidence': finding['evidence'], 'affectedCount': finding['affected_count']})
        result[kind].append(incident['id'])
    for current in open_by_key.values():
        if observed is not None and current['detector'] not in observed:
            result['unobserved'].append(current['id'])
            continue
        incident = fstore.update_incident(current['id'], state='resolved', resolved_at=now)
        fstore.insert_incident_event(incident['id'], 'resolved', now, {})
        result['resolved'].append(incident['id'])
        _notify(notify, 'founder.incident_recovered', incident)
    return result


def _notify(notify, event_type, incident):
    if notify is None:
        return
    try:
        notify(event_type, incident)
    except Exception:
        pass


def escalations_due(fstore):
    """Open critical incidents nobody has acknowledged: the only incidents that may plan a founder call."""
    return [row for row in fstore.open_incidents() if row['state'] == 'open' and row['severity'] == 'critical']


def acknowledge(fstore, incident_id, version, operator_id, *, now, channel='web'):
    """POST /incidents/{id}/ack (capability incidents.ack). Bound to the exact version; a replay of the same version is a
    no-op that returns the current incident. Cancels reserved founder contact attempts for this incident."""
    if channel not in ACK_CHANNELS or type(version) is not int:
        raise ControlError('VALIDATION_FAILED', 400)
    incident = fstore.incident(incident_id)
    if incident is None:
        raise ControlError('VALIDATION_FAILED', 404)
    if not fstore.insert_ack(incident_id, version, operator_id, now, channel):
        return {'incident': public_incident(incident, fstore.incident_events(incident_id)), 'replayed': True, 'cancelledAttempts': 0}
    if incident['version'] != version:
        raise ControlError('STALE_PREVIEW', 409)
    fields = {'acknowledged_at': incident.get('acknowledged_at') or now}
    if incident['state'] == 'open':
        fields['state'] = 'acknowledged'
    incident = fstore.update_incident(incident_id, **fields)
    cancelled = fstore.cancel_pending_attempts(incident_id, 'acknowledged', now)
    fstore.insert_incident_event(incident_id, 'acknowledged', now, {'version': version, 'channel': channel, 'cancelledAttempts': cancelled})
    if cancelled:
        fstore.insert_incident_event(incident_id, 'contact_cancelled', now, {'count': cancelled, 'reason': 'acknowledged'})
    return {'incident': public_incident(incident, fstore.incident_events(incident_id)), 'replayed': False, 'cancelledAttempts': cancelled}


def public_incident(row, events=None):
    out = {'id': row['id'], 'detector': row['detector'], 'scope': row['scope'], 'episodeKey': row['episode_key'], 'severity': row['severity'],
           'state': row['state'], 'openedAt': float(row['opened_at']), 'acknowledgedAt': _float(row.get('acknowledged_at')),
           'resolvedAt': _float(row.get('resolved_at')), 'evidence': dict(row.get('evidence') or {}), 'affectedCount': int(row.get('affected_count') or 0),
           'version': int(row['version']), 'href': '/founder/operations?incident=' + row['id']}
    if events is not None:
        out['timeline'] = [{'id': e['id'], 'kind': e['kind'], 'at': float(e['at']), 'body': dict(e.get('body') or {})} for e in events]
    return out


def _float(value):
    return None if value is None else float(value)


def list_incidents(fstore, principal, *, limit=50, include_resolved=True):
    """GET /incidents?mode=live. Demo incidents live in the Demo payload (founder_preview_scenarios), never here."""
    rows = fstore.list_incidents(limit=max(1, min(int(limit), 200)))
    if not include_resolved:
        rows = [r for r in rows if r['state'] != 'resolved']
    return {'incidents': [public_incident(r) for r in rows]}


def attention_row(row):
    """One Overview attention item (live_metrics._attention): detector, scope, severity, count and the opened stamp as
    ISO 8601 — never the evidence body."""
    opened = datetime.fromtimestamp(float(row['opened_at']), timezone.utc).isoformat().replace('+00:00', 'Z')
    return {'id': row['id'], 'severity': row['severity'], 'state': row['state'], 'detector': row['detector'], 'scope': row['scope'],
            'title': f"{row['detector'].replace('_', ' ').capitalize()} · {row['scope'].replace('_', ' ')}",
            'affectedCount': int(row.get('affected_count') or 0), 'observedAt': opened, 'version': int(row['version'])}


def open_incidents(service, principal, *, fstore=None):
    """Overview attention hook (live_metrics._open_incidents, Live mode): the environment's unresolved incidents. `service`
    is the QueryService; its control store builds the founder store unless one is given. Without a control store (unit
    fakes, separate mount without 055) there is nothing to report and the overview simply shows no incidents."""
    if fstore is None:
        store = getattr(service, 'store', None)
        if store is None:
            return []
        from .founder_cron import PostgresFounderStore
        fstore = PostgresFounderStore(store)
    try:
        rows = fstore.open_incidents()
    except Exception:
        # The overview must not depend on 055: a missing or failing incident table is a tolerated ControlError there.
        raise ControlError('SOURCE_UNAVAILABLE', 503) from None
    return [attention_row(row) for row in rows]


def read_incident(fstore, principal, incident_id):
    row = fstore.incident(incident_id)
    if row is None:
        raise ControlError('VALIDATION_FAILED', 404)
    return {'incident': public_incident(row, fstore.incident_events(incident_id))}


# --- SQL (rafii_control_session role, environment GUC policies; see 055) -----------------------------------------------
_INCIDENT_SELECT = ('SELECT id::text,environment,detector,scope,episode_key,severity,state,extract(epoch from opened_at) AS opened_at,'
                    'extract(epoch from acknowledged_at) AS acknowledged_at,extract(epoch from resolved_at) AS resolved_at,evidence,affected_count,version '
                    'FROM rafii_control.founder_incidents')
_INCIDENT_FIELDS = frozenset(('severity', 'state', 'acknowledged_at', 'resolved_at', 'evidence', 'affected_count'))


def bumps_version(fields):
    """Whether an update transitions the episode (severity or state) and therefore invalidates shown versions."""
    return bool({'severity', 'state'} & set(fields))


def _incident_row(row):
    return {**row, 'evidence': dict(row['evidence'] or {}), 'opened_at': float(row['opened_at']), 'acknowledged_at': _float(row['acknowledged_at']),
            'resolved_at': _float(row['resolved_at']), 'affected_count': int(row['affected_count'] or 0), 'version': int(row['version'])}


class IncidentSQL:
    """Incident, timeline and acknowledgement rows. `self.store` is a rafii_control.store.PostgresStore."""

    def incident(self, incident_id):
        with self.store.transaction() as con:
            row = con.execute(_INCIDENT_SELECT + ' WHERE id=%s AND environment=%s', (incident_id, self.environment)).fetchone()
        return _incident_row(row) if row else None

    def open_incidents(self):
        with self.store.transaction() as con:
            rows = con.execute(_INCIDENT_SELECT + " WHERE environment=%s AND state<>'resolved' ORDER BY opened_at,id", (self.environment,)).fetchall()
        return [_incident_row(r) for r in rows]

    def list_incidents(self, *, limit=50):
        with self.store.transaction() as con:
            rows = con.execute(_INCIDENT_SELECT + " WHERE environment=%s ORDER BY (state='resolved'),opened_at DESC LIMIT %s", (self.environment, limit)).fetchall()
        return [_incident_row(r) for r in rows]

    def insert_incident(self, row):
        with self.store.transaction() as con:
            con.execute('INSERT INTO rafii_control.founder_incidents(id,environment,detector,scope,episode_key,severity,state,opened_at,evidence,affected_count,version) '
                        'VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s,%s,%s) ON CONFLICT(environment,detector,scope,episode_key) DO NOTHING',
                        (row['id'], self.environment, row['detector'], row['scope'], row['episode_key'], row['severity'], row['state'], row['opened_at'],
                         Jsonb(row['evidence']), row['affected_count'], row['version']))
            stored = con.execute(_INCIDENT_SELECT + ' WHERE environment=%s AND detector=%s AND scope=%s AND episode_key=%s',
                                 (self.environment, row['detector'], row['scope'], row['episode_key'])).fetchone()
        return _incident_row(stored)

    def update_incident(self, incident_id, **fields):
        """The version (what an acknowledgement binds to) moves only on a severity or state transition; evidence and
        affected-count refreshes leave it alone so the version a page showed stays acknowledgeable across cron ticks."""
        if set(fields) - _INCIDENT_FIELDS:
            raise ValueError('unknown incident field')
        assignments, values = (['version=version+1'] if bumps_version(fields) else []), []
        for key, value in fields.items():
            assignments.append(f'{key}=to_timestamp(%s)' if key.endswith('_at') else f'{key}=%s')
            values.append(Jsonb(value) if key == 'evidence' else value)
        with self.store.transaction() as con:
            row = con.execute(f'UPDATE rafii_control.founder_incidents SET {",".join(assignments)} WHERE id=%s AND environment=%s RETURNING id::text',
                              (*values, incident_id, self.environment)).fetchone()
            if not row:
                raise ControlError('VALIDATION_FAILED', 404)
            stored = con.execute(_INCIDENT_SELECT + ' WHERE id=%s', (incident_id,)).fetchone()
        return _incident_row(stored)

    def insert_incident_event(self, incident_id, kind, at, body):
        event = {'id': str(uuid.uuid4()), 'incident_id': incident_id, 'kind': kind, 'at': at, 'body': dict(body or {})}
        with self.store.transaction() as con:
            con.execute('INSERT INTO rafii_control.founder_incident_events(id,incident_id,environment,kind,at,body) VALUES(%s,%s,%s,%s,to_timestamp(%s),%s)',
                        (event['id'], incident_id, self.environment, kind, at, Jsonb(event['body'])))
        return event

    def incident_events(self, incident_id):
        with self.store.transaction() as con:
            rows = con.execute('SELECT id::text,incident_id::text AS incident_id,kind,extract(epoch from at) AS at,body FROM rafii_control.founder_incident_events '
                               'WHERE incident_id=%s AND environment=%s ORDER BY at,id LIMIT 500', (incident_id, self.environment)).fetchall()
        return [{**r, 'at': float(r['at']), 'body': dict(r['body'] or {})} for r in rows]

    def insert_ack(self, incident_id, version, operator_id, at, channel):
        with self.store.transaction() as con:
            row = con.execute('INSERT INTO rafii_control.founder_incident_acks(incident_id,version,environment,operator_id,at,channel) '
                              'VALUES(%s,%s,%s,%s,to_timestamp(%s),%s) ON CONFLICT(incident_id,version) DO NOTHING RETURNING incident_id',
                              (incident_id, version, self.environment, operator_id, at, channel)).fetchone()
        return row is not None
