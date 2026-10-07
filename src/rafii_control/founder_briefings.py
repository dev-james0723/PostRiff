"""Founder briefings: immutable report versions with deterministic text (Founder Admin v2, CONTRACTS §5 and §8.E).

Boundaries. `compose_brief` renders receipts and open incidents into fixed sections and a fixed-format text without any
model: values are quoted as recorded (no totals are computed here), an unavailable receipt is said to be unavailable,
and the text ends by stating that nothing was published, scheduled or spent. Reports are append-only versions per
(operator, environment, kind). Phone playback reads a report (or the incident a call is about) through the restricted
reader role only; the consumer process never reads founder tables through its own connection.

Where the values come from (CONTRACTS §8.E, P0 review item 4). A scheduled briefing reads its numbers through
`QueryService.metric_query`, one receipted query per line, as the operator the briefing is for: the cron principal is
built from that operator's own active founder row in `rafii_control.platform_operators` (`cron_principal`), so the
query service still checks `metrics.query` against the capabilities stored there — nothing is granted or bypassed here,
and a founder without `metrics.query` gets the unreceipted cron observations instead, labelled as such. Every metric
query writes its ordinary receipt (owned by that operator, so the web evidence drawer opens it), and the report keeps
the receipt ids, so `founder_reports.receipt_ids` is never empty when a metric query ran.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, time as clock_time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg.types.json import Jsonb

from .auth import ControlError
# Metric windows are report-time-zone days (live_metrics.TIME_ZONE), never UTC; the header keeps the schedule's own zone.
from .live_metrics import TIME_ZONE as REPORT_TIME_ZONE

KINDS = ('daily', 'weekly', 'incident', 'test')
UNITS = ('count', 'usd_micro', 'currency_minor', 'seconds', 'ratio', 'state', 'text')
MAX_TEXT = 12000
CLOSING = 'This briefing quotes recorded values only. Nothing was published, scheduled or spent.'
BASES = ('metric_receipts', 'cron_observations')
log = logging.getLogger('rafii_control.founder_briefings')


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
    if unit == 'currency_minor':
        return f'{currency or ""} {int(value) / 100:,.2f}'.strip()
    if unit == 'count':
        return f'{int(value):,}'
    if unit == 'seconds':
        return f'{int(value):,} s'
    if unit == 'ratio':
        return f'{float(value) * 100:.1f}%'
    return str(value)[:400]


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


def compose_brief(kind, receipts, *, now, time_zone='UTC', environment='local', incidents=(), basis=None):
    """An unsaved report: {kind, generated_at, receipt_ids, sections, coverage, text}. Deterministic for equal inputs.
    `basis` (from `briefing_facts`) names where the values came from — receipted metric queries or unreceipted cron
    observations, with the reason — and is recorded in the coverage and stated in the text."""
    if kind not in KINDS:
        raise ControlError('VALIDATION_FAILED', 400)
    if basis is not None and (not isinstance(basis, dict) or basis.get('basis') not in BASES):
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
    if basis is not None:
        coverage['basis'] = basis['basis']
        reason = basis.get('reason')
        if isinstance(reason, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,63}', reason):
            coverage['basisReason'] = reason
        if basis['basis'] == 'metric_receipts':
            count = len(set(receipt_ids))
            body.append(f'Basis: {count} receipted metric quer{"y" if count == 1 else "ies"}; days are {REPORT_TIME_ZONE} report days.')
        else:
            body.append('Basis: cron observations without query receipts' + (f' ({coverage["basisReason"]}).' if 'basisReason' in coverage else '.'))
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


# --- report routes (registered by founder_notifications at import; CONTRACTS §8.E, Settings → Reports) ---------------------
_UUID_TEXT = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z')


def http_reports(app, principal, request):
    """GET /reports?mode=&kind=&limit= (control.read): this founder's briefing versions, newest first, without their text.
    Demo has no simulated reports and never shows Live ones."""
    if request['mode'] == 'demo':
        return {'mode': 'demo', 'reports': [], 'reason': 'demo_not_simulated', '_dataState': 'not_applicable'}
    kind = (request['query'].get('kind') or [None])[0]
    if kind is not None and kind not in KINDS:
        raise ControlError('VALIDATION_FAILED', 400)
    limit = app.query_int(request['query'], 'limit', 20, 100)
    return {'mode': 'live', **list_reports(app.founder_store(), principal, kind=kind, limit=limit)}


def http_report(app, principal, request):
    """GET /reports/{id} (control.read): one version with its text, sections, coverage and receipt ids; the envelope
    carries the same receipt ids (the evidence drawer opens each one through /metrics/receipts/{id})."""
    report_id = (request.get('match') or [None])[0]
    if request['mode'] == 'demo' or not isinstance(report_id, str) or not _UUID_TEXT.match(report_id):
        raise ControlError('VALIDATION_FAILED', 404)
    out = read_report(app.founder_store(), principal, str(uuid.UUID(report_id)))
    report = out['report']
    state = (report.get('coverage') or {}).get('dataState')
    return {'mode': 'live', **out, '_receiptIds': list(report['receiptIds']),
            '_dataState': state if state in ('measured', 'partial', 'unavailable') else 'partial'}


# --- receipted briefing values (CONTRACTS §8.E; P0 review item 4) ------------------------------------------------------------
# One QueryService.metric_query per entry: (metric id, label, window, groupBy). A grouped metric gives one line per group;
# no line adds anything up. Kinds without their own list (incident, test) use the daily one.
BRIEF_METRICS = {
    'daily': (('ai_cost_actual', 'AI cost yesterday (actual)', 'day', ()),
              ('ai_cost_actual', 'AI cost this month so far (actual)', 'mtd', ()),
              ('cash_collected', 'Cash collected yesterday', 'day', ('currency',)),
              ('payment_failures', 'Payment failures yesterday', 'day', ()),
              ('publish_outcomes', 'Publish outcomes yesterday', 'day', ('status',)),
              ('active_workspaces', 'Active workspaces yesterday', 'day', ()),
              ('paid_customers', 'Paid customers now', 'day', ()),
              ('source_health', 'Data sources', 'day', ('source',))),
    'weekly': (('ai_cost_actual', 'AI cost, last 7 days (actual)', 'week', ()),
               ('ai_cost_actual', 'AI cost this month so far (actual)', 'mtd', ()),
               ('cash_collected', 'Cash collected, last 7 days', 'week', ('currency',)),
               ('payment_failures', 'Payment failures, last 7 days', 'week', ()),
               ('publish_outcomes', 'Publish outcomes, last 7 days', 'week', ('status',)),
               ('active_workspaces', 'Active workspaces, last 7 days', 'week', ()),
               ('paid_customers', 'Paid customers now', 'day', ()),
               ('source_health', 'Data sources', 'day', ('source',))),
}
QUERY_LIMIT = 100
_CATALOG = {}


def brief_windows(now, time_zone=REPORT_TIME_ZONE):
    """Half-open report-day windows at `now` (epoch seconds): yesterday, the seven complete days before today, and the
    month so far. Midnight always exists in the report time zone (its DST changes happen at 02:00)."""
    zone = _zone(time_zone)
    local = datetime.fromtimestamp(float(now), zone).replace(microsecond=0)

    def midnight(day):
        return datetime.combine(day, clock_time(0), tzinfo=zone)

    def iso(value):
        return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    today = local.date()
    month = midnight(today.replace(day=1))
    return {'day': {'start': iso(midnight(today - timedelta(days=1))), 'end': iso(midnight(today)), 'timeZone': zone.key},
            'week': {'start': iso(midnight(today - timedelta(days=7))), 'end': iso(midnight(today)), 'timeZone': zone.key},
            'mtd': {'start': iso(month), 'end': iso(max(local, month + timedelta(minutes=1))), 'timeZone': zone.key}}


def query_service(store, now):
    """A QueryService over the founder store's restricted PostgresStore (reader role for metrics, session role for the
    receipts), clocked at the briefing's own instant so receipts and staleness are stamped consistently."""
    from .intelligence import Catalog, QueryService
    if 'catalog' not in _CATALOG:
        _CATALOG['catalog'] = Catalog()
    return QueryService(store, _CATALOG['catalog'], clock=lambda: datetime.fromtimestamp(float(now), timezone.utc))


def cron_principal(store, operator_id, environment):
    """The principal a scheduled briefing reads metrics as: the operator's own founder row exactly as
    `rafii_control.platform_operators` stores it (status, role, capabilities, auth epoch), on a non-interactive cron
    marker session. Nothing is granted here: QueryService.require still checks every capability against that row, so a
    revoked operator, another role or a row without metrics.query gets no receipted read. None without an active row."""
    try:
        row = store.operator(operator_id, environment)
    except Exception as error:  # noqa: BLE001 - an unreadable operator row means no receipted read, never a crash
        log.warning(json.dumps({'event': 'founder_briefing.operator_unavailable', 'error': type(error).__name__}))
        return None
    if (not isinstance(row, dict) or row.get('status') != 'active' or row.get('role') != 'founder' or row.get('environment', environment) != environment
            or str(row.get('user_id')) != str(operator_id) or not isinstance(row.get('capabilities'), list)):
        return None
    return {'operator': dict(row), 'session': {'id': None, 'environment': environment, 'kind': 'cron'}}


def _fact(receipt_id, metric_id, label, unit, value, *, currency=None, state='unavailable', detail=None):
    fact = {'id': receipt_id, 'metricId': metric_id, 'label': str(label)[:80], 'unit': unit if unit in UNITS else 'text', 'value': value, 'dataState': state}
    if currency:
        fact['currency'] = currency
    if detail:
        fact['detail'] = str(detail)[:160]
    return fact


def _result_facts(result, metric_id, label, group_by):
    """The lines one receipt supports: one per returned row (a grouped row names its group), the data-health strip as a
    single line, or 'none recorded' for an instrumented source without rows in the window (never a zero it did not say)."""
    receipt = result.get('queryReceiptId')
    rows = [row for row in result.get('rows') or [] if isinstance(row, dict)]
    if metric_id == 'source_health':
        groups = {}
        for row in rows:
            state = row.get('dataState') or 'unavailable'
            reason = row.get('reason') if state != 'measured' else None
            groups.setdefault(state, []).append(str((row.get('dimensions') or {}).get('source') or 'source') + (f' ({reason})' if reason else ''))
        order = ('measured', 'partial', 'stale', 'not_applicable', 'unavailable', 'suppressed')
        parts = [f"{state}: {', '.join(groups[state])}" for state in sorted(groups, key=lambda s: order.index(s) if s in order else len(order))]
        overall = 'unavailable' if not groups else 'measured' if set(groups) <= {'measured', 'not_applicable'} else 'partial'
        return [_fact(receipt, metric_id, label, 'text', '; '.join(parts) if parts else None, state=overall, detail=None if parts else 'no_probe_recorded')]
    if not rows:
        state = result.get('dataState') or 'unavailable'
        return [_fact(receipt, metric_id, label, 'text', 'none recorded' if state == 'measured' else None, state=state)]
    out = []
    for row in rows:
        dimensions = row.get('dimensions') or {}
        group = ' · '.join(str(dimensions[name]) for name in group_by if dimensions.get(name) not in (None, ''))
        state = row.get('dataState') or 'unavailable'
        out.append(_fact(receipt, metric_id, f'{label} · {group}' if group else label, row.get('unit'), row.get('value'), currency=row.get('currency'),
                         state=state, detail=row.get('reason') if state != 'measured' else None))
    return out


def metric_facts(queries, principal, kind, now, *, time_zone=REPORT_TIME_ZONE):
    """(facts, receipt ids): every BRIEF_METRICS line of `kind` through QueryService.metric_query as `principal`. A
    refused capability (SCOPE_DENIED) stops the read and is raised; any other failure leaves that line unavailable with a
    fixed reason and keeps the rest of the briefing."""
    windows = brief_windows(now, time_zone)
    facts, receipts = [], []
    for metric_id, label, window, group_by in BRIEF_METRICS.get(kind) or BRIEF_METRICS['daily']:
        query = {'metricIds': [metric_id], 'interval': dict(windows[window]), 'groupBy': list(group_by), 'filters': [], 'comparison': 'none', 'limit': QUERY_LIMIT}
        try:
            result = queries.metric_query(query, principal, str(uuid.uuid4()))
        except ControlError as error:
            if error.code == 'SCOPE_DENIED':
                raise
            facts.append(_fact(None, metric_id, label, 'text', None, detail=str(error.code).lower()))
            continue
        except Exception as error:  # noqa: BLE001 - one unreadable metric never sinks the briefing
            log.warning(json.dumps({'event': 'founder_briefing.metric_unavailable', 'metricId': metric_id, 'error': type(error).__name__}))
            facts.append(_fact(None, metric_id, label, 'text', None, detail='query_failed'))
            continue
        receipts.append(result['queryReceiptId'])
        facts.extend(_result_facts(result, metric_id, label, group_by))
    return facts, receipts


def _audit_read(store, principal, request_id, result, error_code=None):
    """One content-free admin_audit_log row per briefing read: the operator the cron read as, `metrics.query`, outcome."""
    audit = getattr(store, 'audit', None)
    if not callable(audit):
        return
    try:
        audit(request_id=request_id, actor=principal['operator']['user_id'], session=None, environment=principal['session']['environment'],
              action='metrics.query', result=result, error_code=error_code)
    except Exception as error:  # noqa: BLE001 - the audit trail never decides whether a briefing is written
        log.warning(json.dumps({'event': 'founder_briefing.audit_unavailable', 'result': result, 'error': type(error).__name__}))


def briefing_facts(fstore, operator_id, kind, now, *, fallback=None, queries=None):
    """(facts, basis) for one scheduled briefing. Receipted first: a QueryService over the founder store's restricted
    PostgresStore (`fstore.store`), run as the operator's own active founder row (`cron_principal`). When that path cannot
    produce a receipt — no control store, no active founder row, metrics.query not granted, every query failed — the
    `fallback()` facts (the cron's unreceipted observations) are used and the basis names the reason."""
    reason = None
    if queries is None:
        store = getattr(fstore, 'store', None)
        if store is not None and all(callable(getattr(store, name, None)) for name in ('operator', 'read', 'receipt', 'metric_rows')):
            queries = query_service(store, now)
    if queries is None:
        reason = 'control_store_unavailable'
    else:
        environment = getattr(fstore, 'environment', None) or getattr(queries.store, 'environment', None)
        principal = cron_principal(queries.store, operator_id, environment)
        if principal is None:
            reason = 'operator_not_active'
        else:
            request_id = str(uuid.uuid4())
            try:
                facts, receipts = metric_facts(queries, principal, kind, now)
            except ControlError as error:
                _audit_read(queries.store, principal, request_id, 'denied', error.code)
                reason = 'metrics_query_not_granted'
            else:
                _audit_read(queries.store, principal, request_id, 'allowed')
                if receipts:
                    return facts, {'basis': 'metric_receipts', 'receipts': len(receipts)}
                reason = 'no_receipts'
    facts = [fact for fact in (fallback() if callable(fallback) else []) if isinstance(fact, dict)]
    return facts, {'basis': 'cron_observations', 'reason': reason}


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
