"""Founder briefings: immutable report versions with deterministic text (Founder Admin v2, CONTRACTS §5).

Boundaries. `compose_brief` renders receipts and open incidents into fixed sections and a fixed-format text without any
model: values are quoted as recorded (no totals are computed here), an unavailable receipt is said to be unavailable,
and the text ends by stating that nothing was published, scheduled or spent. Reports are append-only versions per
(operator, environment, kind). Phone playback reads a report (or the incident a call is about) through the restricted
reader role only; the consumer process never reads founder tables through its own connection.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg.types.json import Jsonb

from .auth import ControlError

KINDS = ('daily', 'weekly', 'incident', 'test')
UNITS = ('count', 'usd_micro', 'ratio', 'state', 'text')
MAX_TEXT = 12000
CLOSING = 'This briefing quotes recorded values only. Nothing was published, scheduled or spent.'


def _zone(name):
    try:
        return ZoneInfo(name or 'UTC')
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo('UTC')


def format_value(unit, value, currency=None):
    """Deterministic rendering of one recorded value."""
    if value is None:
        return 'not available'
    if unit == 'usd_micro':
        return f'{(currency or "USD")} {int(value) / 1_000_000:,.2f}'
    if unit == 'count':
        return f'{int(value):,}'
    if unit == 'ratio':
        return f'{float(value) * 100:.1f}%'
    return str(value)[:200]


def _receipt_line(receipt):
    label = str(receipt.get('label') or receipt.get('metricId') or 'metric')[:80]
    state = receipt.get('dataState') or 'unavailable'
    if state in ('measured', 'partial', 'stale'):
        rendered = format_value(receipt.get('unit') if receipt.get('unit') in UNITS else 'text', receipt.get('value'), receipt.get('currency'))
        suffix = '' if state == 'measured' else f' ({state})'
        detail = f' — {str(receipt["detail"])[:160]}' if receipt.get('detail') else ''
        return f'{label}: {rendered}{suffix}{detail}', state
    detail = f' ({str(receipt["detail"])[:160]})' if receipt.get('detail') else ''
    return f'{label}: not available{detail}', 'unavailable'


def _incident_line(incident, zone):
    opened = datetime.fromtimestamp(float(incident['opened_at']), zone).strftime('%H:%M')
    return f'{incident["severity"]} {incident["detector"]} ({incident["scope"]}), {incident["state"]} since {opened}, affecting {int(incident.get("affected_count") or 0)}'


def incident_text(incident, time_zone='UTC'):
    """The spoken form of one incident for a founder call: detector, scope, severity, state, time and counts only."""
    zone = _zone(time_zone)
    evidence = incident.get('evidence') or {}
    facts = ', '.join(f'{key} {value}' for key, value in sorted(evidence.items()) if isinstance(value, (int, float, str)) and key != 'thresholdVersion')
    return (f'Founder incident {incident["id"]}: ' + _incident_line(incident, zone) + '.' + (f' Evidence: {facts}.' if facts else '') +
            ' Acknowledge it in Founder Admin to stop further escalation. ' + CLOSING)


def compose_brief(kind, receipts, *, now, time_zone='UTC', environment='local', incidents=()):
    """An unsaved report: {kind, generated_at, receipt_ids, sections, coverage, text}. Deterministic for equal inputs."""
    if kind not in KINDS:
        raise ControlError('VALIDATION_FAILED', 400)
    zone = _zone(time_zone)
    stamp = datetime.fromtimestamp(float(now), zone)
    sections, measured, unavailable, receipt_ids = [], 0, 0, []
    open_incidents = [i for i in incidents if i.get('state') != 'resolved']
    incident_lines = [_incident_line(i, zone) for i in sorted(open_incidents, key=lambda i: (i['severity'] != 'critical', float(i['opened_at'])))]
    sections.append({'id': 'incidents', 'title': 'Incidents', 'lines': incident_lines or ['No open incidents.'], 'count': len(open_incidents)})
    lines = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        line, state = _receipt_line(receipt)
        lines.append(line)
        if state == 'unavailable':
            unavailable += 1
        else:
            measured += 1
        identifier = receipt.get('id')
        if isinstance(identifier, str):
            try:
                receipt_ids.append(str(uuid.UUID(identifier)))
            except ValueError:
                pass
    sections.append({'id': 'metrics', 'title': 'Recorded values', 'lines': lines or ['No recorded values were available.']})
    total = measured + unavailable
    coverage = {'measured': measured, 'unavailable': unavailable, 'total': total,
                'dataState': 'measured' if total and not unavailable else 'partial' if measured else 'unavailable'}
    header = f'Founder {kind} briefing · {stamp.strftime("%A %d %B %Y, %H:%M")} {zone.key} · {environment} environment'
    body = [header]
    for section in sections:
        body.append(section['title'] + ':')
        body.extend('- ' + line for line in section['lines'])
    body.append(f'Coverage: {measured} of {total} recorded values available; {unavailable} not available.')
    body.append(CLOSING)
    text = '\n'.join(body)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT - 1] + '…'
    return {'kind': kind, 'generated_at': float(now), 'receipt_ids': sorted(set(receipt_ids)), 'sections': sections, 'coverage': coverage, 'text': text}


def save_report(fstore, operator_id, report):
    """Persist a composed brief as the next immutable version for (operator, environment, kind)."""
    row = {'id': str(uuid.uuid4()), 'operator_id': operator_id, 'environment': fstore.environment, **report}
    return fstore.insert_report(row)


def public_report(row, *, with_text=True):
    out = {'id': row['id'], 'kind': row['kind'], 'version': int(row['version']), 'generatedAt': float(row['generated_at']),
           'receiptIds': list(row.get('receipt_ids') or []), 'sections': list(row.get('sections') or []), 'coverage': dict(row.get('coverage') or {})}
    if with_text:
        out['text'] = row['text']
    return out


def list_reports(fstore, principal, *, kind=None, limit=20):
    rows = fstore.reports(principal['operator']['user_id'], kind=kind, limit=max(1, min(int(limit), 100)))
    return {'reports': [public_report(r, with_text=False) for r in rows]}


def read_report(fstore, principal, report_id):
    row = fstore.report(report_id)
    if row is None or row['operator_id'] != principal['operator']['user_id']:
        raise ControlError('VALIDATION_FAILED', 404)
    return {'report': public_report(row)}


# --- phone playback (reader role) --------------------------------------------------------------------------------------------
def _reader_store(values):
    from .store import PostgresStore, connection_factory
    dsn, environment = values.get('RAFII_CONTROL_READER_DSN'), values.get('RAFII_CONTROL_ENVIRONMENT', 'local')
    if not dsn or environment not in ('local', 'staging', 'production') or str(values.get('RAFII_CONTROL_ENABLED', '')).lower() not in ('1', 'true'):
        return None
    reader = connection_factory(dsn, 'rafii_control_reader', environment)
    return PostgresStore(reader, reader, environment)


def playback_text(values, reason_key, *, reader=None):
    """The text a founder call reads: the report named by 'founder:briefing:<report id>' or the incident named by
    'founder:incident:<incident id>'. None when the key is not a founder key, the control store is not configured or
    the row is absent; the caller then uses a fixed unavailable prompt."""
    parts = str(reason_key or '').split(':')
    if len(parts) != 3 or parts[0] != 'founder' or parts[1] not in ('briefing', 'incident'):
        return None
    try:
        identifier = str(uuid.UUID(parts[2]))
    except ValueError:
        return None
    store = reader if reader is not None else _reader_store(values)
    if store is None:
        return None
    with store.transaction(read=True) as con:
        if parts[1] == 'briefing':
            row = con.execute('SELECT text FROM rafii_control.founder_reports WHERE id=%s AND environment=%s', (identifier, store.environment)).fetchone()
            return row['text'] if row else None
        row = con.execute('SELECT id::text,detector,scope,severity,state,extract(epoch from opened_at) AS opened_at,evidence,affected_count '
                          'FROM rafii_control.founder_incidents WHERE id=%s AND environment=%s', (identifier, store.environment)).fetchone()
    return incident_text(row) if row else None


# --- SQL (rafii_control_session role, environment GUC policies; see 055) -----------------------------------------------
_REPORT_SELECT = ('SELECT id::text,operator_id::text AS operator_id,environment,kind,version,extract(epoch from generated_at) AS generated_at,'
                  'receipt_ids::text[] AS receipt_ids,sections,coverage,text FROM rafii_control.founder_reports')


def _report_row(row):
    return {**row, 'generated_at': float(row['generated_at']), 'receipt_ids': list(row['receipt_ids'] or []), 'sections': list(row['sections'] or []),
            'coverage': dict(row['coverage'] or {}), 'version': int(row['version'])}


class ReportSQL:
    """Immutable report rows. `self.store` is a rafii_control.store.PostgresStore."""

    def insert_report(self, row):
        with self.store.transaction() as con:
            stored = con.execute('INSERT INTO rafii_control.founder_reports(id,operator_id,environment,kind,version,generated_at,receipt_ids,sections,coverage,text) '
                                 'SELECT %s,%s,%s,%s,coalesce(max(version),0)+1,to_timestamp(%s),%s::uuid[],%s,%s,%s FROM rafii_control.founder_reports '
                                 'WHERE operator_id=%s AND environment=%s AND kind=%s RETURNING id::text',
                                 (row['id'], row['operator_id'], self.environment, row['kind'], row['generated_at'], row['receipt_ids'], Jsonb(row['sections']),
                                  Jsonb(row['coverage']), row['text'], row['operator_id'], self.environment, row['kind'])).fetchone()
            stored = con.execute(_REPORT_SELECT + ' WHERE id=%s', (stored['id'],)).fetchone()
        return _report_row(stored)

    def report(self, report_id):
        with self.store.transaction() as con:
            row = con.execute(_REPORT_SELECT + ' WHERE id=%s AND environment=%s', (report_id, self.environment)).fetchone()
        return _report_row(row) if row else None

    def reports(self, operator_id, *, kind=None, limit=20):
        clause, values = '', [operator_id, self.environment]
        if kind is not None:
            clause, values = ' AND kind=%s', values + [kind]
        with self.store.transaction() as con:
            rows = con.execute(_REPORT_SELECT + f' WHERE operator_id=%s AND environment=%s{clause} ORDER BY generated_at DESC,version DESC LIMIT %s',
                               (*values, limit)).fetchall()
        return [_report_row(r) for r in rows]
