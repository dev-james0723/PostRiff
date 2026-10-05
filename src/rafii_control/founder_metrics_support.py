"""Named support metrics from bounded, content-free original-tenant projections."""
from datetime import timedelta
from . import demo_metrics, live_metrics
from .auth import ControlError
from .founder_metrics_ops import _compose, _dimensions
from .live_metrics import build_row, execute, parse_stamp, stamp

TICKETS = 'rafii_control.business_support_tickets'
OFFERS = 'rafii_control.business_support_survey_offers'
RESPONSES = 'rafii_control.business_support_survey_responses'
CSAT_SOURCE = 'in_app_support_csat_yes_no/v1'


def unavailable(metric, interval, reason):
    return [build_row(metric, interval, {}, value=None, unit=metric['unit'], state='unavailable', reason=reason)]


def open_ticket_rows(service, metric, query, interval, stale):
    # This is a current snapshot. A historical endpoint cannot reconstruct the
    # old status from today's ticket row, so it must never claim to do so.
    if parse_stamp(interval['end']) < service.clock() - timedelta(seconds=60):
        return unavailable(metric, interval, 'historical_ticket_snapshot_not_collected')
    base = 'SELECT t."workspaceId" AS wid,t.category,t.priority,t.status,t."updatedAt" AS at FROM '+TICKETS+" t WHERE t.status IN ('open','waiting_customer')"
    statement, params, groups = _compose(metric['id'], query, base, (), {'category': 'b.category', 'priority': 'b.priority', 'status': 'b.status'},
        (('count', 'count(*)'), ('watermark', 'max(b.at)')), time=False)
    records = execute(service, statement, params)
    if records is None:
        return unavailable(metric, interval, 'source_not_configured')
    if not records:
        records = [{'count': 0, 'watermark': None}]
    snapshot_at = stamp(service.clock())
    return [build_row(metric, interval, _dimensions(row, groups), value=row['count'], unit='count', state='stale' if stale else 'measured',
        known=row['count'], watermark=snapshot_at, sample_count=row['count'], reason='source_stale' if stale else None,
        measures={'snapshotAt': snapshot_at, 'ticketWatermark': row.get('watermark'),
                  'population': 'open_and_waiting_customer_tickets', 'historicalSnapshotAvailable': False}) for row in records]


def csat_rows(service, metric, query, interval, stale):
    base = ('SELECT o."workspaceId" AS wid,t.category,o."offeredAt" AS at,o.id AS offer_id,r.id AS response_id,r.helpful,r."answeredAt" AS answered_at '
            'FROM '+OFFERS+' o JOIN '+TICKETS+' t ON t."workspaceId"=o."workspaceId" AND t.id=o."ticketId" '
            'LEFT JOIN '+RESPONSES+' r ON r."workspaceId"=o."workspaceId" AND r."surveyId"=o.id '
            'AND r."sourceVersion"=o."sourceVersion" AND r."answeredAt">=o."offeredAt" AND r."answeredAt"<%s::timestamptz '
            'WHERE o."sourceVersion"=%s AND o."offeredAt">=%s::timestamptz AND o."offeredAt"<%s::timestamptz')
    statement, params, groups = _compose(metric['id'], query, base, (interval['end'], CSAT_SOURCE, interval['start'], interval['end']),
        {'category': 'b.category'}, (('offers', 'count(b.offer_id)'), ('responses', 'count(b.response_id)'), ('positive', 'count(b.response_id) FILTER(WHERE b.helpful)'), ('watermark', 'max(greatest(b.at,b.answered_at))')))
    records = execute(service, statement, params)
    if records is None:
        return unavailable(metric, interval, 'source_not_configured')
    if not records:
        records = [{'offers': 0, 'responses': 0, 'positive': 0, 'watermark': None}]
    out = []
    for row in records:
        offers, responses, positive = row['offers'], row['responses'], row['positive']
        if not 0 <= positive <= responses <= offers:
            raise ControlError('SOURCE_UNAVAILABLE', 503)
        state = 'unavailable' if offers == 0 else 'not_applicable' if responses == 0 else 'stale' if stale else 'partial'
        reason = 'no_observed_resolution_offers' if offers == 0 else 'no_valid_survey_responses' if responses == 0 else 'source_stale' if stale else 'qualified_resolution_response_sample'
        out.append(build_row(metric, interval, _dimensions(row, groups), value=positive / responses if responses else None,
            unit='ratio', state=state, known=responses, unknown=offers-responses, numerator=positive, denominator=responses,
            watermark=row.get('watermark'), sample_count=responses, reason=reason,
            measures={'surveyOffers': offers, 'validResponses': responses, 'positiveResponses': positive,
                      'responseRate': responses / offers if offers else None, 'responseRateBasis': 'observed_resolution_offers',
                      'sourceVersion': CSAT_SOURCE, 'coverage': 'observed_resolution_offers_only',
                      'unansweredOffers': offers-responses, 'asOf': interval['end']}))
    return out


live_metrics.register(custom={'open_tickets': {'rows': open_ticket_rows, 'previous': None}, 'csat': {'rows': csat_rows}},
                      sources={'open_tickets': 'database', 'csat': 'database'})
demo_metrics.register({'open_tickets': demo_metrics.not_simulated, 'csat': demo_metrics.not_simulated})
