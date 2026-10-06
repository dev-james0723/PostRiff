"""Exact staging-only acceptance; production schedule/security remain authoritative."""
from datetime import datetime, timezone
import uuid
from agent_team.acceptance import as_of_now, document_period, question_report_key
from agent_team.reports import report
from postriff_alpha.domain import AlphaError
from .agent_team_cutover import staging_cutover, team_enabled, call_enabled

def require_acceptance(values, *, phone=False):
    # The opt-in flag alone can never activate this route in another project/preview.
    if (not staging_cutover(values) or not team_enabled(values)
            or str(values.get('JAMES_AGENT_TEAM_ACCEPTANCE_ENABLED', '')).lower() not in ('1', 'true')
            or (phone and not call_enabled(values))):
        raise AlphaError('Staging acceptance is disabled.', 404, code='agent_team_acceptance_disabled')

def acceptance_report(service, values, store, request):
    require_acceptance(values)
    if not isinstance(request, dict) or set(request) != {'acceptanceId'}:
        raise AlphaError('Invalid acceptance request.', 400)
    try:
        acceptance_id = str(uuid.UUID(request['acceptanceId']))
        if acceptance_id != request['acceptanceId']: raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise AlphaError('Invalid acceptance identity.', 400) from None
    now = datetime.fromtimestamp(service.clock(), timezone.utc)
    p = as_of_now(acceptance_id, now)
    prior = store.get_acceptance(acceptance_id)
    if prior:
        # Retry/readback reconciles the same immutable snapshot, never historical data.
        return prior, False
    from .james_agent_team import source_coverage
    events, truncated = store.observations(p, now)
    sources = source_coverage(events, p, now)
    if truncated:
        for meta in sources.values():
            meta.update(complete=False, gaps=meta.get('gaps', []) + ['observation_query_limit'])
    document = report(p, events, now, sources)
    document.update(executionMode='staging_acceptance')
    document['gaps'].append('acceptance_as_of_now_not_historical_or_scheduled')
    document['summary'] = 'Staging acceptance，資料截至目前，並非歷史或排程報告。' + document['summary']
    return store.put_report(document)

def call_gate(values, context, cfg, now):
    require_acceptance(values, phone=True)
    key = question_report_key(context)
    from agent_team.acceptance import acceptance_key
    if not acceptance_key(key):
        raise AlphaError('Invalid acceptance call binding.', 409)
    report = context['agentTeamReport']
    if cfg.time_zone != 'America/Indiana/Indianapolis' or cfg.quiet(now):
        raise AlphaError('Acceptance is inside quiet hours.', 409, code='quiet_hours')
    if not -60 <= now - report['generatedAt'] <= 900:
        raise AlphaError('Acceptance snapshot is stale.', 409, code='agent_team_report_stale')
    from .agent_team_decision import validate_question
    question = validate_question(context.get('agentTeamDecisionQuestion'), actor_id=cfg.user_id,
        workspace_id=cfg.workspace_id, mission_id=report['missionId'], report_id=report['reportId'],
        report_version=report['version'], now=now)
    if question['reportKey'] != key:
        raise AlphaError('Acceptance question changed.', 409, code='decision_question_binding_mismatch')

def call_acceptance(service, values, store, document, mission_id):
    require_acceptance(values, phone=True)
    p = document_period(document)
    if document.get('executionMode') != 'staging_acceptance':
        raise AlphaError('Acceptance snapshot required.', 409)
    from .james_agent_team import _report_question
    question = _report_question(service, document, mission_id)
    # Resolve/check the original immutable registry BEFORE reserving a phone effect.
    question.document(now=service.clock())
    effect = p.key + ':call'
    if not store.reserve_effect(effect, p.key, 'phone'):
        return {'state': 'reconciliation_required', 'reportKey': p.key, 'callsCreated': 0}
    try:
        result = service.james_daily_call.call_report_acceptance(document, mission_id, question)
        store.effect(effect, 'submitted', result.get('id'))
        return result
    except AlphaError as error:
        store.effect(effect, 'failed', failure_class=error.code or 'admission_blocked')
        raise
    except Exception:
        store.effect(effect, 'unknown', failure_class='reconciliation_required')
        raise AlphaError('Acceptance call outcome requires reconciliation.', 409) from None
