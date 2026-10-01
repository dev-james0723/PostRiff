"""Bounded read-only evidence contracts. No network, model or action dispatch."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
import uuid
from .auth import ControlError

REPOSITORY = 'dev-james0723/PostRiff'
ADAPTER_VERSION = 'github-workflow/1'
REQUIRED_WORKFLOWS = ['Rafii Control foundation', 'Rafii local release gates']
WORKFLOW_IDS = {'Rafii Control foundation':370650254, 'Rafii local release gates':365845611}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Timestamp required')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Timezone required')
    return stamp.astimezone(timezone.utc)


def effective_quality(row, now=None, max_age_seconds=900):
    """Stored observation and current trust are distinct, including legacy rows."""
    now = now or datetime.now(timezone.utc)
    result = {key: row.get(key) for key in ('source_id', 'watermark', 'checked_at')}
    result['last_good'] = {key: row.get(key) for key in ('state', 'watermark', 'checked_at')}
    result['last_good']['qualified'] = row.get('qualified') is True
    result.update(state='unavailable', reason_code='unqualified_source', age_seconds=None,
                  provenance=row.get('provenance', 'unqualified'), source_version=row.get('source_version'))
    try:
        checked, watermark = timestamp(row.get('checked_at')), timestamp(row.get('watermark'))
    except (ValueError, TypeError, OverflowError):
        result['reason_code'] = 'missing_or_malformed_timestamp'
        return result
    result['age_seconds'] = max(0, int((now-checked).total_seconds()))
    if checked > now or watermark > now:
        result['reason_code'] = 'future_timestamp'
    elif row.get('state') in ('conflicting', 'conflict') or row.get('conflicts'):
        result.update(state='partial', reason_code='conflicting_evidence')
    elif row.get('qualified') is not True or not row.get('source_version') or row.get('provenance') != 'admitted_operational':
        result['reason_code'] = 'unqualified_source'
    elif row.get('coverage_complete') is not True:
        result.update(state='partial', reason_code='incomplete_coverage')
    elif (now-checked).total_seconds() > max_age_seconds or (now-watermark).total_seconds() > max_age_seconds:
        result.update(state='stale', reason_code='source_observation_aged')
    elif row.get('state') == 'measured':
        result.update(state='measured', reason_code='qualified_manual_snapshot')
    else:
        result.update(state=row.get('state') if row.get('state') in ('partial', 'stale', 'suppressed') else 'unavailable',
                      reason_code='source_not_measured')
    return result


def required_manifest(sha):
    if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{40}', sha):
        raise ControlError('VALIDATION_FAILED', 400)
    return dict(version=1, repository=REPOSITORY, sha=sha, required=REQUIRED_WORKFLOWS.copy(), workflowIds=WORKFLOW_IDS.copy())


def evaluate_checks(runs, manifest, coverage_complete):
    """A bounded manifest observation never proves release/runtime acceptance."""
    if manifest.get('repository') != REPOSITORY or not re.fullmatch('[0-9a-f]{40}', manifest.get('sha', '')):
        raise ControlError('VALIDATION_FAILED', 400)
    required = manifest.get('required')
    if not isinstance(required, list) or not 0 < len(required) <= 20 or len(set(required)) != len(required):
        raise ControlError('VALIDATION_FAILED', 400)
    if len(runs) > 100:
        raise ControlError('BUDGET_EXCEEDED', 400)
    checks = []
    for name in required:
        matches = [r for r in runs if r.get('name') == name and r.get('head_sha') == manifest['sha']
                   and (name not in manifest.get('workflowIds',{}) or r.get('workflow_id') == manifest['workflowIds'][name])]
        matches.sort(key=lambda r: (r.get('run_number', 0), r.get('run_attempt', 1), r.get('id', 0)), reverse=True)
        row = matches[0] if matches else None
        outcome = 'missing'
        if row:
            conclusion = row.get('conclusion')
            outcome = ('incomplete' if row.get('status') != 'completed' or conclusion is None
                       else 'success' if conclusion == 'success'
                       else 'failure' if conclusion in ('failure', 'action_required')
                       else 'skipped' if conclusion in ('skipped', 'neutral')
                       else 'interrupted' if conclusion in ('cancelled','stale')
                       else 'infrastructure_failure')
        checks.append(dict(name=name, outcome=outcome, runId=row.get('id') if row else None,
                           runAttempt=row.get('run_attempt', 1) if row else None,
                           observedSha=row.get('head_sha') if row else None))
    outcomes = {c['outcome'] for c in checks}
    qualification = ('incomplete_coverage' if coverage_complete is not True else
                     'required_checks_succeeded' if outcomes == {'success'} else
                     'required_check_failed' if 'failure' in outcomes else
                     'infrastructure_failure' if 'infrastructure_failure' in outcomes else
                     'required_checks_incomplete')
    return dict(checks=checks, qualification=qualification, requiredCount=len(required),
                observedRequiredCount=sum(c['runId'] is not None for c in checks),
                coverageComplete=coverage_complete is True, releaseAccepted=False)


def validate_capture(capture, *, admit=False, now=None):
    """Validate a manually exported public provider snapshot; no fixture admission."""
    now = now or datetime.now(timezone.utc)
    fields = {'schemaVersion', 'captureId', 'repository', 'exactSha', 'requestId', 'requestedAt',
              'observedAt', 'resourceUrl', 'providerBodyDigest', 'workflowRuns', 'coverage',
              'provenance', 'requiredManifest', 'adapterVersion'}
    try:
        if set(capture) != fields or capture['schemaVersion'] != 1 or capture['repository'] != REPOSITORY:
            raise ValueError()
        uuid.UUID(capture['captureId']); uuid.UUID(capture['requestId'])
        sha = capture['exactSha']
        if capture['requiredManifest'] != required_manifest(sha) or capture['adapterVersion'] != ADAPTER_VERSION:
            raise ValueError()
        if not re.fullmatch('[0-9a-f]{64}', capture['providerBodyDigest']):
            raise ValueError()
        url = f'https://api.github.com/repos/{REPOSITORY}/actions/runs?head_sha={sha}&event=pull_request&per_page=100&page=1'
        if capture['resourceUrl'] != url:
            raise ValueError()
        requested, observed = timestamp(capture['requestedAt']), timestamp(capture['observedAt'])
        if not requested <= observed <= now:
            raise ValueError()
        provenance = capture['provenance']
        if provenance not in ('synthetic', 'provider_observed_test') or (admit and provenance != 'provider_observed_test'):
            raise ValueError()
        runs = capture['workflowRuns']
        if not isinstance(runs, list) or len(runs) > 100 or len(json.dumps(capture).encode()) > 131072:
            raise ValueError()
        permitted = {'id', 'name', 'head_sha', 'status', 'conclusion', 'run_number', 'run_attempt', 'updated_at', 'workflow_id'}
        for row in runs:
            if not isinstance(row, dict) or set(row)-permitted or type(row.get('id')) is not int or row['id'] < 1:
                raise ValueError()
            if not isinstance(row.get('name'), str) or len(row['name']) > 160 or row.get('head_sha') != sha:
                raise ValueError()
            if row.get('status') not in ('completed', 'queued', 'in_progress', 'waiting', 'requested', 'pending'):
                raise ValueError()
            if row.get('conclusion') not in (None, 'success', 'failure', 'neutral', 'cancelled', 'skipped', 'timed_out', 'action_required', 'stale', 'startup_failure'):
                raise ValueError()
            if timestamp(row.get('updated_at')) > observed:
                raise ValueError()
            for field in ('run_number', 'run_attempt'):
                if field in row and (type(row[field]) is not int or row[field] < 1): raise ValueError()
        if len({row['id'] for row in runs}) != len(runs): raise ValueError()
        coverage = capture['coverage']
        if set(coverage) != {'complete', 'returnedRuns', 'totalRuns', 'scope'} or type(coverage['complete']) is not bool:
            raise ValueError()
        if coverage['scope'] != 'pull_request_workflow_runs_first_page' or coverage['returnedRuns'] != len(runs):
            raise ValueError()
        total = coverage['totalRuns']
        if total is not None and (type(total) is not int or total < len(runs)): raise ValueError()
        if coverage['complete'] and (total is None or total != len(runs)): raise ValueError()
        body_digest = hashlib.sha256(json.dumps(runs, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if body_digest != capture['providerBodyDigest']: raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise ControlError('VALIDATION_FAILED', 400)
    return {**capture, 'provenance': 'admitted_operational' if admit else provenance}


def plan_intent(message, now=None):
    """Small explicit grammar; unsupported domains/time expressions never fall back."""
    now = now or datetime.now(timezone.utc)
    words = message.casefold()
    if not re.search(r'\bchecks?\b', words) or re.search(r'\b(spend|activation|revenue|refund|agents?|deployments?|churn|metrics?)\b', words):
        return None
    if re.search(r'\b(month|year|hour|segment|suite|timezone)\b', words):
        return None
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if 'yesterday' in words:
        start, end = day-timedelta(days=1), day
    elif 'this week' in words:
        start, end = day-timedelta(days=day.weekday()), now
    elif 'last week' in words:
        end=day-timedelta(days=day.weekday());start=end-timedelta(days=7)
    elif 'today' in words:
        start, end = day, now
    elif '28 days' in words or not re.search(r'\b(last|since|during|past)\b', words):
        start, end = now-timedelta(days=28), now
    else:
        return None
    return dict(metricIds=['check_failures'], interval={'start':start.isoformat(), 'end':end.isoformat(), 'timeZone':'UTC'},
                groupBy=['suite', 'failure_class'], filters=[], comparison='previous_complete' if re.search(r'\b(compare|comparison)\b', words) else 'none', limit=100)
