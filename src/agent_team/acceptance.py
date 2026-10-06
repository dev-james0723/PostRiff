"""Explicit as-of-now identities; never substitute an acceptance for a scheduled report."""
from dataclasses import dataclass
from datetime import timedelta
import re
from uuid import UUID
from .periods import Period, TZ, aware, period

KEY = re.compile(r'agent-team:acceptance:v1:(20\d{2}-\d{2}-\d{2}):([0-9a-f-]{36}):half_day')

def acceptance_key(value):
    match = KEY.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return None
    try:
        if str(UUID(match[2])) != match[2]:
            return None
        period(match[1], 'half_day')
    except (ValueError, TypeError):
        return None
    return match[1], match[2]

@dataclass(frozen=True)
class AcceptancePeriod(Period):
    acceptance_id: str

    @property
    def key(self):
        return f'agent-team:acceptance:v1:{self.workday}:{self.acceptance_id}:half_day'

    def as_dict(self):
        return {**super().as_dict(), 'executionMode': 'staging_acceptance',
                'acceptanceId': self.acceptance_id,
                'nominalCutoff': period(self.workday, 'half_day').cutoff.isoformat()}

def as_of_now(acceptance_id, now):
    if str(UUID(acceptance_id)) != acceptance_id:
        raise ValueError('acceptance_uuid_required')
    now = aware(now)
    local = now.astimezone(TZ)
    day = (local.date() - timedelta(days=1 if local.hour < 1 else 0)).isoformat()
    scheduled = period(day, 'half_day')
    return AcceptancePeriod(day, 'half_day', scheduled.start, now, acceptance_id)

def document_period(document):
    p = document['period']
    if p.get('executionMode') == 'staging_acceptance':
        parsed = acceptance_key(p.get('key'))
        if not parsed or parsed != (p['workday'], p['acceptanceId']):
            raise ValueError('acceptance_identity_invalid')
        result = as_of_now(p['acceptanceId'], p['cutoff'])
        if document.get('executionMode') != 'staging_acceptance' or result.as_dict() != p:
            raise ValueError('acceptance_period_invalid')
    else:
        result = period(p['workday'], p['kind'])
        if result.as_dict() != p:
            raise ValueError('scheduled_period_invalid')
    if aware(document['generatedAt']) < result.cutoff:
        raise ValueError('generation_before_cutoff')
    return result

def question_report_key(context):
    report = context.get('agentTeamReport', {})
    acceptance = context.get('agentTeamAcceptance')
    if acceptance is None:
        return 'agent-team:v1:' + str(report.get('workday')) + ':half_day'
    if (not isinstance(acceptance, dict) or set(acceptance) != {'schemaVersion', 'acceptanceId', 'reportKey'}
            or type(acceptance['schemaVersion']) is not int or acceptance['schemaVersion'] != 1
            or acceptance_key(acceptance['reportKey']) != (report.get('workday'), acceptance['acceptanceId'])):
        raise ValueError('acceptance_call_binding_invalid')
    return acceptance['reportKey']
