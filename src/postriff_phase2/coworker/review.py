"""Read-only, rights-bound review projections over existing native observations (Rafii POC-1 candidate).

The minimal subset of the Analytics review candidate (PR #126) needed for one account, one native metric and one
fixed post-age cohort: strict cohort qualification, an immutable weekly report snapshot rendered from one frozen
payload, and deterministic takeaways that may lead to the existing Growth Loop. Saved Views, classifications,
Trends lineage, reuse and personalization from PR #126 are deliberately not part of this candidate; a publication
carrying Trends lineage is excluded (fail closed) instead of being shown without its own source checks.

POC-1 increments over PR #126:
- the post-age window has an upper bound (`metric_schedule.WINDOW_TOLERANCE`, from PR #142): a reading taken after
  publication + horizon + tolerance is `window_late`, never part of the cohort; every candidate reading keeps its
  actual age and window qualification;
- rights come from `operation_eligibility` (the capability contract), not from a local capability query;
- groups below the descriptive minimum carry no aggregate, and the projection states its qualification.

Saved reports and replay receipts use the workspace aggregate (`coworker.review`); this adapter owns no acquisition,
model, publishing, scheduling or approval engine, and no provider or model is called.
"""
from __future__ import annotations

import copy
import csv
import html
import io
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError
from .. import insights, locales
from ..contracts import digest
from ..growth.metric_schedule import WINDOW_TOLERANCE
from .growth_loop import verified_at

SCHEMA_VERSION = '1.0'
FLAG = 'RAFII_REVIEW_SNAPSHOTS_ENABLED'
HORIZONS = {'1h': 3600, '24h': 86400, '7d': 604800}
FRESHNESS_POLICY = 'scheduled-native-offset-v1'
ALGORITHM_VERSION = 'review-qualification-v2-window-tolerance'
MAX_POSTS = 300
MAX_SNAPSHOTS = 64
MAX_REJECTED = 5
LIMITATIONS = ['Cumulative native readings at the chosen post age; not events during this week.', 'Promotion status unknown.',
               'Observational evidence; causal=false.', 'Platforms and distinct account cohorts are shown separately.',
               f'The minimum of {insights.MIN_COMPARABLE} comparable publications is a descriptive floor, not statistical confidence.']


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) or isinstance(value, Decimal) and value.is_finite()


def connection_expired(channel, now):
    return finite(channel.get('expiresAt')) and channel['expiresAt'] <= now


def iso(value):
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat().replace('+00:00', 'Z')


def stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise AlphaError('Use a UTC ISO timestamp.', 400)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError()
        return parsed.timestamp()
    except (ValueError, OverflowError):
        raise AlphaError('Use a UTC ISO timestamp.', 400) from None


def zone(name):
    try:
        if not isinstance(name, str) or len(name) > 80:
            raise ValueError()
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise AlphaError('Choose a valid IANA timezone.', 400) from None


def period(value):
    if not isinstance(value, dict) or set(value) != {'start', 'end', 'timezone'}:
        raise AlphaError('Choose a publication period and timezone.', 400)
    zone(value['timezone'])
    start, end = stamp(value['start']), stamp(value['end'])
    if not start < end or end - start > 366 * 86400:
        raise AlphaError('Choose a period of at most one year with start before end.', 400)
    return {'start': iso(start), 'end': iso(end), 'timezone': value['timezone']}


def resolve_relative_period(rule, now):
    if not isinstance(rule, dict) or set(rule) != {'kind', 'timezone'} or rule['kind'] not in ('this_week', 'last_week', 'this_month', 'last_month'):
        raise AlphaError('Choose a supported relative date rule.', 400)
    local = datetime.fromtimestamp(now, zone(rule['timezone'])).replace(hour=0, minute=0, second=0, microsecond=0)
    if 'week' in rule['kind']:
        start = local - timedelta(days=local.weekday())
        if rule['kind'] == 'last_week':
            start -= timedelta(days=7)
        end = start + timedelta(days=7)
    else:
        start = local.replace(day=1)
        if rule['kind'] == 'last_month':
            end = start
            start = (start - timedelta(days=1)).replace(day=1)
        else:
            end = (start + timedelta(days=32)).replace(day=1)
    return {'start': iso(start.timestamp()), 'end': iso(end.timestamp()), 'timezone': rule['timezone']}


def previous_period(chosen, relative_rule=None):
    local_zone = zone(chosen['timezone'])
    end = datetime.fromtimestamp(stamp(chosen['start']), local_zone)
    if relative_rule and 'month' in relative_rule['kind']:
        start = (end - timedelta(days=1)).replace(day=1)
    else:
        current_end = datetime.fromtimestamp(stamp(chosen['end']), local_zone)
        # Civil duration preserves a local week across daylight-saving changes.
        start = end - (current_end - end)
    return period({'start': iso(start.timestamp()), 'end': iso(end.timestamp()), 'timezone': chosen['timezone']})


def review_state(state):
    return (state.get('coworker') or {}).get('review') or {}


def _root(state):
    root = state.setdefault('coworker', {}).setdefault('review', {})
    for key, default in (('snapshots', []), ('requests', {})):
        root.setdefault(key, copy.deepcopy(default))
    return root


def _request(state, workspace_id, operation, body, build):
    key = body.get('idempotencyKey')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', key):
        raise AlphaError('Use a bounded idempotency key.', 400)
    root = _root(state)
    request_id = digest([workspace_id, key])
    request_digest = digest([operation, {k: v for k, v in body.items() if k != 'workspaceRevision'}])
    existing = root['requests'].get(request_id)
    if existing:
        if existing['digest'] != request_digest:
            raise AlphaError('This request key belongs to different content.', 409)
        return copy.deepcopy(existing['result'])
    if len(root['requests']) >= 1024:
        raise AlphaError('The review command history is full. Review retained records first.', 409)
    result = build(root, request_id)
    root['requests'][request_id] = {'digest': request_digest, 'result': copy.deepcopy(result)}
    return result


def resolve_review_context(workspace_id, value, state, now, *, rights_epoch='unknown'):
    if not isinstance(value, dict):
        raise AlphaError('Review scope must be structured.', 400)
    allowed = {'schemaVersion', 'workspaceId', 'channelIds', 'publicationPeriod', 'relativeDateRule', 'horizon', 'language', 'formatIds', 'tagSelection',
               'nativeMetric', 'comparison', 'cutoffAt', 'scopeKind', 'aggregation', 'attributionState'}
    if set(value) - allowed or value.get('workspaceId', workspace_id) != workspace_id or value.get('schemaVersion', SCHEMA_VERSION) != SCHEMA_VERSION:
        raise AlphaError('This review scope is not compatible with this workspace.', 400)
    channels = {c['id']: c for c in state.get('phase2', {}).get('channels', [])}
    selected = value.get('channelIds', [])
    if not isinstance(selected, list) or not 1 <= len(selected) <= 8 or any(not isinstance(c, str) or c not in channels for c in selected):
        raise AlphaError('Choose accounts from this workspace.', 400)
    selected = sorted(set(selected))
    providers = sorted({str(channels[c].get('platform', '')).lower() for c in selected})
    formats = value.get('formatIds', [])
    # Format identities come from existing manifests and the existing publishing catalog.
    from postriff_phase2 import content_types
    known = set(content_types.FORMAT_IDS)
    known |= {j.get('manifest', {}).get('contentType', {}).get('formatId') for j in state.get('phase2', {}).get('jobs', [])}
    if not isinstance(formats, list) or len(formats) > 12 or any(not isinstance(f, str) or f not in known for f in formats):
        raise AlphaError('Choose known content formats.', 400)
    if value.get('tagSelection', []) != []:
        raise AlphaError('Classification filters are not part of this review.', 400)
    native = value.get('nativeMetric')
    if native is None:
        native = [{'provider': p, 'nativeName': n, 'definitionVersion': insights.DEFINITION_VERSION, 'unit': 'count'} for p in providers for n in insights.INSIGHT_METRICS.get(p, ())]
    if not isinstance(native, list) or not native or len(native) > 48:
        raise AlphaError('Choose supported native metrics.', 400)
    for m in native:
        if not isinstance(m, dict) or set(m) != {'provider', 'nativeName', 'definitionVersion', 'unit'} or m['provider'] not in providers or m['nativeName'] not in insights.INSIGHT_METRICS.get(m['provider'], ()) or m['definitionVersion'] != insights.DEFINITION_VERSION or m['unit'] != 'count':
            raise AlphaError('Use the current provider-native metric definition.', 400)
    language = value.get('language')
    if language is not None:
        language = locales.canonical(language)
        if language is None:
            raise AlphaError('Choose a canonical language or all languages.', 400)
    horizon = value.get('horizon', '24h')
    aggregation = value.get('aggregation', 'median')
    if horizon not in HORIZONS or aggregation not in ('median', 'mean') or value.get('scopeKind', 'published_content_cohort') != 'published_content_cohort':
        raise AlphaError('Choose a supported horizon and aggregation.', 400)
    if value.get('attributionState', 'unknown') != 'unknown':
        raise AlphaError('Promotion status must come from native evidence; it is currently unknown.', 400)
    if bool(value.get('relativeDateRule')) == bool(value.get('publicationPeriod')):
        raise AlphaError('Choose one publication date scope.', 400)
    chosen = resolve_relative_period(value['relativeDateRule'], now) if value.get('relativeDateRule') else period(value.get('publicationPeriod'))
    comparison = value.get('comparison', {'kind': 'none'})
    if not isinstance(comparison, dict) or comparison.get('kind') not in ('none', 'previous_period'):
        raise AlphaError('Choose a supported comparison.', 400)
    if comparison['kind'] == 'previous_period':
        if set(comparison) == {'kind', 'relativeToPublicationPeriod'} and comparison['relativeToPublicationPeriod'] is True:
            baseline = previous_period(chosen, value.get('relativeDateRule'))
        elif set(comparison) == {'kind', 'publicationPeriod'}:
            baseline = previous_period(chosen, value['relativeDateRule']) if value.get('relativeDateRule') else period(comparison['publicationPeriod'])
        else:
            raise AlphaError('Choose one fixed or relative comparison period.', 400)
        if stamp(baseline['end']) > stamp(chosen['start']):
            raise AlphaError('The baseline must precede this publication cohort.', 400)
        comparison = {'kind': 'previous_period', 'publicationPeriod': baseline}
    elif set(comparison) != {'kind'}:
        raise AlphaError('A comparison with no baseline cannot contain a period.', 400)
    cutoff = stamp(value['cutoffAt']) if value.get('cutoffAt') else now
    if cutoff > now:
        raise AlphaError('The observation cutoff cannot be in the future.', 400)
    result = {'schemaVersion': SCHEMA_VERSION, 'workspaceId': workspace_id, 'channelIds': selected, 'providers': providers,
              'publicationPeriod': chosen, 'horizon': horizon, 'language': language, 'formatIds': sorted(set(formats)), 'tagSelection': [],
              'nativeMetric': sorted(native, key=lambda m: (m['provider'], m['nativeName'])),
              'comparison': comparison, 'cutoffAt': iso(cutoff), 'scopeKind': 'published_content_cohort', 'aggregation': aggregation,
              'attributionState': 'unknown', 'contextRevision': 0, 'rightsEpoch': rights_epoch,
              'windowTolerance': {horizon: WINDOW_TOLERANCE[horizon]}, 'algorithmVersion': ALGORITHM_VERSION}
    result['contextDigest'] = digest(result)
    return result


def safe_source(value):
    """Only known native reader endpoints. Never persist queries, fragments or credentials."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.hostname not in ('graph.threads.net', 'graph.instagram.com') or parsed.username or parsed.password:
            return None
        return urlunsplit((parsed.scheme, parsed.hostname, parsed.path, '', ''))
    except ValueError:
        return None


def matched_ratio(numerator, denominator):
    keys = ('jobId', 'connectionId', 'provider', 'nativePostId', 'readOffset', 'observedAt', 'ingestedAt', 'definitionVersion')
    if any(numerator.get(k) is None or numerator.get(k) != denominator.get(k) for k in keys):
        return {'value': None, 'reason': 'incompatible_readings'}
    n, d = numerator.get('value'), denominator.get('value')
    if not finite(n) or not finite(d) or n < 0 or d < 0:
        return {'value': None, 'reason': 'missing_reading'}
    return {'value': float(n / d) if d else None, 'reason': None if d else 'zero_denominator', 'numerator': float(n), 'denominator': float(d)}


def scoped_jobs(state, context):
    """Apply the requested cohort before the bounded observation load."""
    periods = [context['publicationPeriod']]
    if context['comparison'].get('publicationPeriod'):
        periods.append(context['comparison']['publicationPeriod'])
    bounds = [(stamp(p['start']), stamp(p['end'])) for p in periods]
    selected = []
    for job in state.get('phase2', {}).get('jobs', []):
        manifest = job.get('manifest') or {}
        published = verified_at(job)
        if job.get('state') != 'verified' or not job.get('providerReference') or manifest.get('channelId') not in context['channelIds'] or not finite(published):
            continue
        if context['language'] is not None and locales.canonical(manifest.get('payload', {}).get('language')) != context['language']:
            continue
        if context['formatIds'] and manifest.get('contentType', {}).get('formatId') not in context['formatIds']:
            continue
        if any(start <= published < end for start, end in bounds):
            selected.append(job)
    return sorted(selected, key=lambda j: verified_at(j), reverse=True)


def after_cutoff(row, cutoff):
    """A reading observed or ingested after the scope's cutoff does not exist for that scope (as-of semantics), so a
    later reading can never change what a fixed report or a bound proposal showed."""
    return any(finite(row.get(k)) and row[k] > cutoff for k in ('observedAt', 'ingestedAt'))


def window_check(row, published, horizon):
    """(reason|None, windowQualification, actualAgeSeconds) for one candidate reading. Pure."""
    observed = row.get('observedAt')
    age = float(observed) - float(published) if finite(observed) and finite(published) else None
    if row.get('readOffset') is None:
        return 'unknown_read_offset', 'unknown', age
    if row['readOffset'] != horizon:
        return 'wrong_horizon', 'unknown', age
    if not finite(observed) or not finite(row.get('ingestedAt')):
        return 'missing_observation_time', 'unknown', age
    target = published + HORIZONS[horizon]
    # Compare at microsecond precision: SQL epochs round, and a reading exactly at its due time is on time.
    if datetime.fromtimestamp(observed, timezone.utc) < datetime.fromtimestamp(target, timezone.utc):
        return 'window_unqualified', 'early', age
    if datetime.fromtimestamp(observed, timezone.utc) > datetime.fromtimestamp(target + WINDOW_TOLERANCE[horizon], timezone.utc):
        return 'window_late', 'missed', age
    return None, 'within_tolerance', age


def access_state(state, channel, eligibility, now):
    """('allowed'|'revoked'|'disconnected'|'not_authorized', reason|None, blockedReasons)."""
    if state.get('accountDeletion'):
        return 'revoked', 'revoked', ['account_deletion']
    if not channel:
        return 'disconnected', 'disconnected', ['account_not_in_workspace']
    if channel.get('revoked'):
        return 'revoked', 'revoked', ['connection_revoked']
    if connection_expired(channel, now):
        return 'not_authorized', 'expired', ['connection_expired']
    if eligibility and eligibility.get('usableNow'):
        return 'allowed', None, []
    return 'not_authorized', 'not_authorized', list((eligibility or {}).get('blockedReasons') or ['eligibility_unknown'])


def project_review(state, context, observations, eligibility, now, *, tracking_index=None):
    """Pure projection. Current rights override even a previously measured zero.

    eligibility: {connection_id: operation_eligibility.analytics_read projection}."""
    cutoff = stamp(context['cutoffAt'])
    horizon = context['horizon']
    selected = context['publicationPeriod']
    baseline = context['comparison'].get('publicationPeriod')
    channels = {c['id']: c for c in state.get('phase2', {}).get('channels', [])}
    jobs = scoped_jobs(state, context)
    all_count = len(jobs)
    jobs = jobs[:MAX_POSTS]
    rows = defaultdict(list)
    for row in observations:
        rows[(row.get('jobId'), row.get('nativeName'))].append(row)
    results, cohort_groups, excluded = [], defaultdict(lambda: {'current': [], 'baseline': []}), Counter()
    publications = set()
    for job in jobs:
        manifest = job.get('manifest') or {}
        account, provider = manifest.get('channelId'), str(manifest.get('platform', '')).lower()
        published = verified_at(job)
        language = locales.canonical(manifest.get('payload', {}).get('language'))
        form = manifest.get('contentType', {}).get('formatId')
        side = 'current' if stamp(selected['start']) <= published < stamp(selected['end']) else 'baseline' if baseline and stamp(baseline['start']) <= published < stamp(baseline['end']) else None
        if side is None:
            continue
        access, access_reason, blocked = access_state(state, channels.get(account), (eligibility or {}).get(account), now)
        lineage = bool(manifest.get('trendLineage'))
        publications.add(job['id'])
        binding = {'workspaceId': context['workspaceId'], 'jobId': job['id'], 'connectionId': account, 'provider': provider,
                   'nativePostId': str(job['providerReference']), 'manifestDigest': digest([manifest, job.get('verification')]), 'publicationAt': iso(published)}
        allowed = access == 'allowed' and not lineage
        for metric in context['nativeMetric']:
            if metric['provider'] != provider:
                continue
            valid, reasons, rejected = [], [], []
            for row in rows[(job['id'], metric['nativeName'])]:
                if after_cutoff(row, cutoff):
                    continue
                if any(row.get(k) != binding[k] for k in ('connectionId', 'provider', 'nativePostId')):
                    reasons.append('publication_mismatch')
                    continue
                if row.get('definitionVersion') != metric['definitionVersion'] or row.get('unit') != metric['unit']:
                    reasons.append('definition_mismatch')
                    continue
                reason, qualification, age = window_check(row, published, horizon)
                if reason:
                    reasons.append(reason)
                    rejected.append({'observationId': row.get('observationId') if allowed else None, 'readOffset': row.get('readOffset'),
                                     'actualAgeSeconds': age, 'windowQualification': qualification, 'reason': reason})
                else:
                    valid.append({**row, 'actualAgeSeconds': age, 'windowQualification': qualification})
            valid.sort(key=lambda r: (r['observedAt'], r['ingestedAt'], r.get('observationId') or ''), reverse=True)
            latest = valid[0] if valid else {}
            reading = next((r for r in valid if r.get('availability') == 'available' and finite(r.get('value')) and r['value'] >= 0), latest)
            value = reading.get('value')
            value_state = 'measured' if reading.get('availability') == 'available' and finite(value) and value >= 0 else 'invalid' if value is not None else 'unsupported' if reading.get('availability') == 'not_supported' else 'missing'
            stale = bool(reading and latest != reading)
            reason = ('trend_lineage_out_of_scope' if lineage else access_reason if access != 'allowed' else 'stale_reading' if stale else reasons[0] if not valid and reasons else
                      'invalid_value' if value_state == 'invalid' else 'unsupported' if value_state == 'unsupported' else 'missing_reading' if value_state != 'measured' else
                      'missing_observation_identity' if not reading.get('observationId') else None)
            collection = (tracking_index or {}).get((job['id'], horizon), {}).get('state', latest.get('collectionState', 'pending_horizon' if published + HORIZONS[horizon] > now else 'unscheduled'))
            if reason is None and collection != 'measured':
                reason = collection
            e = {'observationId': reading.get('observationId') if allowed else None, 'publicationBinding': binding,
                 **metric, 'value': float(value) if value_state == 'measured' and allowed else None,
                 'valueState': value_state if allowed else 'missing', 'reason': reason, 'collectionState': collection,
                 'accessState': access, 'accessReasons': blocked, 'freshnessState': 'stale' if stale else 'current' if reading else 'unknown',
                 'freshnessPolicyVersion': FRESHNESS_POLICY, 'readOffset': reading.get('readOffset') if allowed else None,
                 'targetAgeWindow': horizon, 'actualAgeSeconds': reading.get('actualAgeSeconds') if allowed else None,
                 'windowQualification': reading.get('windowQualification', 'unknown') if allowed else 'unknown',
                 'rejectedReadings': rejected[:MAX_REJECTED] if allowed else [],
                 'observedAt': iso(reading['observedAt']) if reading and allowed else None,
                 'ingestedAt': iso(reading['ingestedAt']) if reading and allowed else None,
                 'nativeWindow': 'cumulative_at_observation', 'measurementKind': 'native', 'sourceKind': 'OWNED_ANALYTICS',
                 'sourceRef': safe_source(reading.get('sourceRef')) if allowed else None,
                 'displayPermission': 'allowed' if allowed else 'restricted', 'periodSide': side,
                 'lastAttemptState': latest.get('availability') if allowed else None,
                 'language': language, 'formatId': form, 'eligible': reason is None and value_state == 'measured' and allowed}
            results.append(e)
            if e['eligible']:
                key = (provider, account, language, form, metric['nativeName'], metric['definitionVersion'], metric['unit'], horizon)
                cohort_groups[key][side].append(e)
            else:
                excluded[reason or 'unavailable'] += 1
    groups, comparisons = [], []
    aggregate = statistics.median if context['aggregation'] == 'median' else statistics.mean
    for key, sides in sorted(cohort_groups.items(), key=lambda item: str(item[0])):
        cohort = dict(zip(('provider', 'connectionId', 'language', 'formatId', 'nativeName', 'definitionVersion', 'unit', 'horizon'), key))
        current, previous = sides['current'], sides['baseline']
        enough, enough_baseline = len(current) >= insights.MIN_COMPARABLE, len(previous) >= insights.MIN_COMPARABLE
        a = float(aggregate(e['value'] for e in current)) if enough else None
        b = float(aggregate(e['value'] for e in previous)) if enough_baseline else None
        groups.append({'cohort': cohort, 'sampleSize': len(current), 'baselineSampleSize': len(previous), 'value': a, 'baselineValue': b,
                       'aggregation': context['aggregation'], 'minimumSample': insights.MIN_COMPARABLE,
                       'qualification': 'descriptive_only' if enough else 'insufficient_sample',
                       'evidenceIds': [e['observationId'] for e in current]})
        if baseline:
            reason = 'insufficient_sample' if not (enough and enough_baseline) else 'zero_baseline' if b == 0 else None
            comparisons.append({'cohort': cohort, 'current': a, 'baseline': b, 'relativeChange': (a - b) / b if reason is None else None,
                                'reason': reason, 'sampleSize': len(current), 'baselineSampleSize': len(previous), 'causal': False, 'aggregation': context['aggregation']})
    measured = [e for e in results if e['eligible']]
    observed = [e['observedAt'] for e in results if e['observedAt']]
    usable = [c for c in context['channelIds'] if ((eligibility or {}).get(c) or {}).get('usableNow')]
    qualification = ('not_comparable' if not usable else 'descriptive_only' if any(g['qualification'] == 'descriptive_only' for g in groups)
                     else 'insufficient_sample')
    coverage = {'eligible': len({e['publicationBinding']['jobId'] for e in measured}), 'publications': len(publications),
                'measured': len(measured), 'missing': len(results) - len(measured), 'excludedByReason': dict(excluded),
                'earliestAvailableAt': min(observed, key=stamp) if observed else None, 'collectionStartAt': None,
                'lastSuccessfulRead': max(observed, key=stamp) if observed else None, 'cutoffAt': context['cutoffAt'],
                'truncated': all_count > MAX_POSTS, 'maximumPosts': MAX_POSTS,
                'historyLimitations': ['Available stored records only; HistoryImport OFF.', 'Collection start is unknown.']}
    eligibility_view = {c: copy.deepcopy((eligibility or {}).get(c)) for c in context['channelIds']}
    projection = {'schemaVersion': SCHEMA_VERSION, 'resolvedContext': context, 'contextDigest': context['contextDigest'],
                  'algorithmVersion': ALGORITHM_VERSION, 'qualification': qualification, 'sampleN': len(measured),
                  'nativeResults': results, 'groups': groups, 'comparisons': comparisons, 'coverage': coverage,
                  'eligibility': eligibility_view, 'limitations': list(LIMITATIONS)}
    projection['basisDigest'] = basis_digest(projection)
    return projection


def basis_digest(projection):
    """The exact readings, exclusions and rights the projection used. Freshness timestamps of eligibility are left
    out: a newer reading for another publication does not change what this cohort showed."""
    rights = {c: ({k: v for k, v in p.items() if k not in ('lastVerifiedAt', 'evidenceReceiptId', 'dataFreshness', 'nativeVerification', 'unverifiedAxes')} if p else None)
              for c, p in projection['eligibility'].items()}
    return digest({'contextDigest': projection['contextDigest'], 'nativeResults': projection['nativeResults'], 'coverage': projection['coverage'],
                   'qualification': projection['qualification'], 'eligibility': rights})


def review_hypothesis_eligible(state, projection, hypothesis, now):
    from . import performance
    h, ctx = hypothesis, projection['resolvedContext']
    cohort = h.get('cohort', {})
    if ctx['horizon'] != '24h' or h.get('expiresAt', 0) <= now or min(h.get('sample_a', 0), h.get('sample_b', 0)) < performance.MIN_ARM:
        return False
    if not all(cohort.get(k) for k in ('connectionId', 'language', 'contentTypeId', 'definitionVersion')) or h.get('dimension') not in performance.DIMENSIONS:
        return False
    jobs = {j['id']: j for j in state.get('phase2', {}).get('jobs', [])}
    qualified = {e['publicationBinding']['jobId'] for e in projection['nativeResults'] if e['eligible'] and e['nativeName'] == h.get('metric') and
                 e['publicationBinding']['connectionId'] == cohort['connectionId'] and e['provider'] == cohort.get('provider') and
                 e['language'] == cohort['language'] and e['definitionVersion'] == cohort['definitionVersion'] and
                 jobs.get(e['publicationBinding']['jobId'], {}).get('manifest', {}).get('contentType', {}).get('id') == cohort['contentTypeId']}
    source_ids = set((h.get('evidence_ids') or []) + (h.get('counter_evidence_ids') or []))
    if not source_ids or not source_ids <= qualified:
        return False
    a, b, _ = performance.DIMENSIONS[h['dimension']]
    counts = Counter(performance.features(jobs[jid]).get(h['dimension']) for jid in qualified)
    return counts[a] >= performance.MIN_ARM and counts[b] >= performance.MIN_ARM


def review_takeaways(projection, state, now):
    """Bounded deterministic observations; every number comes from eligible native results in this projection."""
    result = []
    for group in projection['groups']:
        if group['qualification'] != 'descriptive_only' or group['value'] is None:
            continue
        cohort = group['cohort']
        def same(e):
            return (e['eligible'] and all(e.get(k) == cohort.get(k) for k in ('provider', 'nativeName', 'language', 'formatId', 'definitionVersion'))
                    and e['publicationBinding']['connectionId'] == cohort['connectionId'])
        current = [e for e in projection['nativeResults'] if same(e) and e['periodSide'] == 'current']
        baseline = [e for e in projection['nativeResults'] if same(e) and e['periodSide'] == 'baseline']
        comparison = next((c for c in projection['comparisons'] if c['cohort'] == cohort and c['relativeChange'] is not None), None)
        # Every current publication supports a descriptive aggregate. Counter-evidence exists only for a comparison:
        # the current publications on the other side of the previous period's aggregate.
        support = current
        counter = []
        if comparison:
            rose = comparison['current'] >= comparison['baseline']
            counter = [e for e in current if (e['value'] < comparison['baseline'] if rose else e['value'] > comparison['baseline'])]
        values = [e['value'] for e in current]
        statement = f"The {group['aggregation']} {cohort['nativeName']} was {group['value']:g} across {len(current)} comparable publications in this account cohort"
        if comparison:
            statement += f", against {comparison['baseline']:g} across {comparison['baselineSampleSize']} in the previous period ({comparison['relativeChange']:+.0%}; descriptive, not a cause)"
        experiment = next((e for e in state.get('coworker', {}).get('growthLoop', {}).get('experiments', []) if e.get('reviewContextDigest') == projection['contextDigest'] and e.get('reviewBasisDigest') == projection['basisDigest']), None)
        next_step = {'kind': 'experiment', 'existingExperimentId': experiment['id'], 'href': '/app/growth', 'label': 'Review this existing experiment'} if experiment else {
            'kind': 'collect', 'existingExperimentId': None, 'href': '/app/weekly', 'label': 'Prepare one controlled test in Weekly Operator'}
        hypothesis = next((h for h in projection.get('_hypotheses', []) if h['metric'] == cohort['nativeName'] and h['cohort'].get('connectionId') == cohort['connectionId'] and review_hypothesis_eligible(state, projection, h, now)), None)
        if not experiment and hypothesis:
            next_step = {'kind': 'propose', 'existingExperimentId': None, 'hypothesisId': hypothesis['id'], 'href': '/app/growth', 'label': 'Propose this controlled test in Growth Loop'}
        result.append({'id': digest([projection['contextDigest'], cohort])[:24], 'contextDigest': projection['contextDigest'],
                       'basisDigest': projection['basisDigest'], 'status': 'observation', 'actualPeriod': projection['resolvedContext']['publicationPeriod'],
                       'nativeMetric': {k: cohort[k] for k in ('provider', 'nativeName', 'definitionVersion', 'unit')},
                       'sampleSize': len(current), 'minimumSample': group['minimumSample'], 'coverage': projection['coverage'],
                       'supportBindings': copy.deepcopy(support), 'counterEvidenceBindings': copy.deepcopy(counter),
                       'counterEvidenceRule': 'current publications on the other side of the previous-period aggregate' if comparison else
                                              'none: a descriptive aggregate without a comparison has no counter-evidence; the range is shown',
                       'range': [min(values), max(values)], 'baselineBindings': copy.deepcopy(baseline),
                       'excludedByReason': copy.deepcopy(projection['coverage']['excludedByReason']),
                       'limitations': projection['limitations'],
                       'statement': statement + '.',
                       'unknowns': ['Why the numbers differ is not known; promotion, audience mix and timing are not measured.'] +
                                   ([f"{n} publication readings were excluded and are not counted." for n in [projection['coverage']['missing']] if n]),
                       'generatedBy': 'deterministic', 'nextStep': next_step, 'expiresAt': iso(now + 3600), 'causal': False})
        if len(result) == 3:
            break
    return result


def build_review_snapshot(projection, state, notes, actor, source_sha, now, *, previous=None, frequency='weekly'):
    if not isinstance(source_sha, str) or not re.fullmatch(r'[a-f0-9]{40}', source_sha):
        raise AlphaError('The runtime source SHA is unavailable. Snapshot creation is blocked.', 503)
    if frequency not in ('weekly', 'monthly') or not isinstance(notes, list) or len(notes) > 12 or any(not isinstance(n, str) or len(n) > 4000 for n in notes):
        raise AlphaError('Use a weekly/monthly report and at most twelve bounded notes.', 400)
    from .growth_loop import view, period as proof_period, proof_counts
    start, end = proof_period(now, frequency)
    proof = next((p for p in reversed(view(state)['proofs']) if p.get('frequency') == frequency), None)
    scope = {'kind': 'workspace_wide', 'timezone': 'UTC', 'start': iso(start), 'end': iso(end)}
    work = {'proofId': None, 'scope': scope, 'counts': proof_counts(state, start, end), 'countingRules': 'Existing Growth Loop proof counting rules; completed, accepted and verified are separate.'}
    time_back = {'value': None, 'unit': 'seconds', 'state': 'unavailable', 'estimationMethodVersion': 'existing-time-back-ledger-v1', 'inputs': []}
    if proof:
        work = {'proofId': proof['id'], 'scope': {'kind': 'workspace_wide', 'timezone': 'UTC', 'originalPeriod': copy.deepcopy(proof.get('period'))},
                'counts': copy.deepcopy(proof.get('counts', {})), 'countingRules': copy.deepcopy(proof.get('countingRules', 'Existing Growth Loop proof rules.'))}
        tb = proof.get('timeBack') or {}
        if tb.get('coverage') == 'available':
            time_back.update(value=sum(r.get('savedSeconds', 0) for r in tb.get('byConfidence', [])), state='estimated', inputs=copy.deepcopy(tb.get('byConfidence', [])))
    family = previous['snapshotId'] if previous else 'rs_' + digest([projection['resolvedContext']['workspaceId'], projection['contextDigest'], now, actor, notes])[:24]
    result = {'snapshotId': family, 'schemaVersion': SCHEMA_VERSION, 'version': previous['version'] + 1 if previous else 1,
              'generatedAt': iso(now), 'createdBy': actor, 'frequency': frequency, 'resolvedContext': copy.deepcopy(projection['resolvedContext']),
              'contextDigest': projection['contextDigest'], 'basisDigest': projection['basisDigest'], 'inputDigest': projection['basisDigest'],
              'algorithmVersion': projection['algorithmVersion'], 'qualification': projection['qualification'], 'sampleN': projection['sampleN'],
              'sourceSha': source_sha, 'nativeResults': copy.deepcopy(projection['nativeResults']), 'coverage': copy.deepcopy(projection['coverage']),
              'groups': copy.deepcopy(projection['groups']), 'comparisons': copy.deepcopy(projection['comparisons']),
              'eligibility': copy.deepcopy(projection['eligibility']),
              'observationBindings': [copy.deepcopy(e) for e in projection['nativeResults'] if e['observationId']],
              'workProof': work, 'timeBack': time_back, 'takeaways': copy.deepcopy(projection.get('takeaways', review_takeaways(projection, state, now))),
              'humanNotes': copy.deepcopy(notes), 'limitations': copy.deepcopy(projection['limitations']),
              'sourceMethodVersions': [insights.DEFINITION_VERSION, FRESHNESS_POLICY, ALGORITHM_VERSION], 'rightsEpoch': projection['resolvedContext']['rightsEpoch'],
              'rendererVersion': 'review-export-v2', 'supersedes': f"{previous['snapshotId']}@v{previous['version']}" if previous else None,
              'changeReason': 'Notes or observations refreshed' if previous else 'Initial fixed report'}
    result['payloadDigest'] = digest(result)
    return result


def format_snapshot(snapshot, format_):
    """All renderers receive one frozen payload. No database, provider or model."""
    s = snapshot
    ctx = s['resolvedContext']
    period_ = ctx['publicationPeriod']
    def dumps(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    preamble = [f"# Rafii {s['frequency']} review", f"Snapshot: {s['snapshotId']} / version {s['version']}",
                f"Context: {s['contextDigest']}", f"Payload: {s['payloadDigest']}", f"Input: {s['inputDigest']}", f"Source SHA: {s['sourceSha']}",
                f"Qualification: {s['qualification']} · comparable n={s['sampleN']} · algorithm {s['algorithmVersion']}",
                f"Publication cohort: [{period_['start']}, {period_['end']}) · {period_['timezone']}",
                f"Accounts: {', '.join(ctx['channelIds']) or 'None'} · {ctx['horizon']} (+{ctx['windowTolerance'][ctx['horizon']]}s tolerance) · {ctx['aggregation']}",
                f"Filters: {dumps(ctx)}", '\n## Account rights (operation eligibility)', dumps(s['eligibility']),
                '\n## Scope and coverage', dumps(s['coverage']),
                '\n## Comparable native groups', dumps(s['groups']),
                '\n## Descriptive comparisons', dumps(s['comparisons']),
                '\n## Completed work (separate workspace scope)', dumps(s['workProof']),
                'Time Back (estimated when available): ' + dumps(s['timeBack']), '\n## Native results']
    metric_lines = [f"{e['publicationBinding']['connectionId']} / {e['publicationBinding']['jobId']} · {e['nativeName']}: {e['value'] if e['value'] is not None else 'null'} · {e['valueState']} · {e['reason'] or 'measured'} · {e['definitionVersion']} · {e['readOffset'] or 'unknown'} · age {e['actualAgeSeconds'] if e['actualAgeSeconds'] is not None else 'unknown'}s ({e['windowQualification']}) · observed {e['observedAt'] or 'unknown'} · ingested {e['ingestedAt'] or 'unknown'} · {e['sourceRef'] or 'source unavailable'}" for e in s['nativeResults']]
    tail = ['\n## Observations and one next test'] + [t['statement'] + ' Next: ' + t['nextStep']['label'] + ' Support: ' + ','.join(e['observationId'] for e in t['supportBindings']) + ' Counter-evidence: ' + (','.join(e['observationId'] for e in t['counterEvidenceBindings']) or 'none') + ' Unknown: ' + ' '.join(t['unknowns']) for t in s['takeaways']]
    tail += ['\n## Human notes', *s['humanNotes'], '\n## Sources and limitations', *s['limitations'],
             'Collection start is unknown; HistoryImport OFF. Offline downloaded files cannot be remotely revoked.']
    markdown = '\n\n'.join(preamble + metric_lines + tail) + '\n'
    if format_ == 'markdown':
        content, content_type, extension = markdown, 'text/markdown; charset=utf-8', 'md'
    elif format_ == 'csv':
        fields = ['snapshotId', 'version', 'payloadDigest', 'contextDigest', 'basisDigest', 'inputDigest', 'qualification', 'sourceSha', 'rendererVersion', 'channelId', 'jobId', 'nativePostId', 'manifestDigest', 'observationId', 'provider', 'nativeName', 'value', 'valueState', 'reason', 'definitionVersion', 'unit', 'readOffset', 'targetAgeWindow', 'actualAgeSeconds', 'windowQualification', 'nativeWindow', 'observedAt', 'ingestedAt', 'accessState', 'freshnessState', 'collectionState', 'sourceRef', 'publicationAt', 'periodStart', 'periodEnd', 'timezone', 'filters', 'eligibility', 'coverage', 'groups', 'comparisons', 'humanNotes', 'workProof', 'timeBack', 'takeaways', 'limitations']
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        def cell(value):
            text = '' if value is None else str(value)
            return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text
        for e in s['nativeResults'] or [None]:
            values = {k: s[k] for k in ('snapshotId', 'version', 'payloadDigest', 'contextDigest', 'basisDigest', 'inputDigest', 'qualification', 'sourceSha', 'rendererVersion')}
            values.update(periodStart=period_['start'], periodEnd=period_['end'], timezone=period_['timezone'], filters=dumps(ctx),
                          humanNotes=' | '.join(s['humanNotes']), workProof=json.dumps(s['workProof'], ensure_ascii=False), timeBack=json.dumps(s['timeBack'], ensure_ascii=False),
                          takeaways=json.dumps(s['takeaways'], ensure_ascii=False), limitations=' | '.join(s['limitations']))
            values.update({k: dumps(s.get(k)) for k in ('eligibility', 'coverage', 'groups', 'comparisons')})
            if e:
                values.update({k: e.get(k) for k in fields if k in e})
                b = e['publicationBinding']
                values.update(channelId=b['connectionId'], jobId=b['jobId'], nativePostId=b['nativePostId'], manifestDigest=b['manifestDigest'], publicationAt=b['publicationAt'])
                values['value'] = e['value'] if e['value'] is not None else 'null'
                values['actualAgeSeconds'] = e['actualAgeSeconds'] if e['actualAgeSeconds'] is not None else 'null'
            else:
                values.update(value='null', valueState='missing', reason='no_native_readings')
            writer.writerow({k: cell(v) for k, v in values.items()})
        content, content_type, extension = output.getvalue(), 'text/csv; charset=utf-8', 'csv'
    elif format_ == 'pdf':
        # The user prints this fixed document to PDF in the browser; the HTML is the frozen payload's rendering.
        content = '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>Rafii ' + html.escape(s['snapshotId']) + '</title><style>@page{size:A4;margin:18mm}body{font:11pt system-ui,"Noto Sans CJK TC","PingFang TC",sans-serif;line-height:1.6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}h1{font-size:22pt}table{border-collapse:collapse;width:100%;font-size:9pt}th,td{border:1px solid #ccc;padding:5px;overflow-wrap:anywhere}thead{display:table-header-group}tr{break-inside:avoid}</style><h1>Rafii fixed review</h1><pre>' + html.escape('\n\n'.join(preamble)) + '</pre><table><thead><tr><th>Publication / metric</th><th>Value / state</th><th>Age / reading / source</th></tr></thead><tbody>'
        for e in s['nativeResults']:
            content += ('<tr><td>' + html.escape(e['publicationBinding']['jobId'] + ' / ' + e['nativeName']) + '</td><td>' + html.escape(str(e['value']) if e['value'] is not None else 'null') + ' · ' + html.escape(e['valueState']) + ' · ' + html.escape(e['reason'] or 'measured') +
                        '</td><td>' + html.escape(f"{e['actualAgeSeconds'] if e['actualAgeSeconds'] is not None else 'unknown'}s ({e['windowQualification']}) / " + (e['observedAt'] or 'unknown') + ' / ' + (e['ingestedAt'] or 'unknown') + ' / ' + (e['sourceRef'] or 'unavailable')) + '</td></tr>')
        content += '</tbody></table><pre>' + html.escape('\n\n'.join(tail)) + '</pre></html>'
        content_type, extension = 'text/html; charset=utf-8', 'html'
    else:
        raise AlphaError('Choose PDF, Markdown or CSV.', 400)
    return {'snapshotId': s['snapshotId'], 'version': s['version'], 'payloadDigest': s['payloadDigest'], 'inputDigest': s['inputDigest'],
            'rendererVersion': s['rendererVersion'], 'contentType': content_type, 'filename': f"{s['snapshotId']}-v{s['version']}.{extension}",
            'content': content, 'rendering': 'browser_print_pdf' if format_ == 'pdf' else 'download'}


def context_input(context):
    return {k: copy.deepcopy(context[k]) for k in ('schemaVersion', 'channelIds', 'publicationPeriod', 'horizon', 'language', 'formatIds', 'tagSelection', 'nativeMetric', 'comparison', 'cutoffAt', 'scopeKind', 'aggregation', 'attributionState')}


class ReviewService:
    def __init__(self, coworker):
        self.c = coworker

    @property
    def repository(self):
        return self.c.repository

    def _rights(self, cur, workspace_id, state):
        # The same cursor/transaction as membership and workspace state; capability and credential rows are held
        # FOR SHARE against a concurrent demotion, downgrade or disconnect during export or commit.
        from ..operation_eligibility import load_analytics_read, rights_epoch
        eligibility = load_analytics_read(cur, workspace_id, state, self.c.clock(), lock=True)
        return eligibility, rights_epoch(eligibility)

    def _project(self, cur, workspace_id, state, actor, value):
        from ..growth.closed_loop import collection_enabled
        from ..growth.trends.beta import tracking
        eligibility, epoch = self._rights(cur, workspace_id, state)
        now = self.c.clock()
        context = resolve_review_context(workspace_id, value, state, now, rights_epoch=epoch)
        jobs = scoped_jobs(state, context)[:MAX_POSTS]
        growth = getattr(self.c.hosted, 'growth', None)
        tracked = tracking(cur, workspace_id, {'phase2': {**state.get('phase2', {}), 'jobs': jobs}}, now,
                           enabled=collection_enabled(growth, workspace_id) if growth else False, limit=MAX_POSTS)
        tracking_index = {(p['job_id'], h['window']): h for p in tracked['posts'] for h in p['horizons']}
        rows = []
        if jobs:
            offset = insights.read_offset_column(cur)
            cur.execute(f"""SELECT o.id::text,o.job_id,o.connection_id,o.provider,o.provider_post_id,o.metric,o.definition_version,
                        o.value,o.unit,o.availability,extract(epoch from o.observed_at),extract(epoch from o.ingested_at),{offset},o.source_endpoint
                        FROM public.pr_metric_observations o WHERE o.workspace_id=%s AND o.job_id=ANY(%s)
                        ORDER BY o.observed_at DESC,o.ingested_at DESC,o.id DESC LIMIT 12001""", (workspace_id, [j['id'] for j in jobs]))
            for r in cur.fetchall():
                row = dict(zip(('observationId', 'jobId', 'connectionId', 'provider', 'nativePostId', 'nativeName', 'definitionVersion', 'value', 'unit', 'availability', 'observedAt', 'ingestedAt', 'readOffset', 'sourceRef'), r))
                row['observedAt'] = float(row['observedAt'])
                row['ingestedAt'] = float(row['ingestedAt'])
                if isinstance(row['value'], Decimal):
                    row['value'] = float(row['value'])
                row['collectionState'] = tracking_index.get((row['jobId'], row['readOffset']), {}).get('state', 'unscheduled')
                rows.append(row)
        projection = project_review(state, context, rows[:12000], eligibility, now, tracking_index=tracking_index)
        if len(rows) > 12000:
            projection['coverage']['truncated'] = True
            projection['comparisons'] = []
            projection['groups'] = []
            projection['qualification'] = 'not_comparable'
            projection['limitations'].append('Observation loading bound reached; comparison withheld.')
            projection['basisDigest'] = basis_digest(projection)
        cur.execute("""SELECT id::text,cohort,metric,dimension,sample_a,sample_b,evidence_ids,counter_evidence_ids,extract(epoch from expires_at)
                       FROM public.pr_strategy_hypotheses WHERE workspace_id=%s AND causal=false AND status IN ('candidate','experiment','supported') AND expires_at>to_timestamp(%s)
                       ORDER BY id LIMIT 80""", (workspace_id, now))
        projection['_hypotheses'] = [dict(zip(('id', 'cohort', 'metric', 'dimension', 'sample_a', 'sample_b', 'evidence_ids', 'counter_evidence_ids', 'expiresAt'), r)) for r in cur.fetchall()]
        for h in projection['_hypotheses']:
            h['expiresAt'] = float(h['expiresAt'])
        projection['takeaways'] = review_takeaways(projection, state, now)
        projection.pop('_hypotheses')
        projection['workspaceRevision'] = None
        return projection

    def read(self, workspace_id, token, value):
        self.c._require(FLAG)
        with self.repository.transaction(token, workspace_id) as (cur, row, actor):
            state = self.c.hosted.ideas._state(row)
            result = self._project(cur, workspace_id, state, actor, value)
            result['workspaceRevision'] = row[0]
            return result

    def _snapshot_current(self, cur, workspace_id, state, actor, snapshot):
        eligibility, _ = self._rights(cur, workspace_id, state)
        channels = {c['id']: c for c in state.get('phase2', {}).get('channels', [])}
        selected = snapshot['resolvedContext']['channelIds']
        if state.get('accountDeletion') or any(c not in channels or channels[c].get('revoked') or connection_expired(channels[c], self.c.clock()) for c in selected):
            raise AlphaError('A report account is no longer available.', 410)
        jobs = {j['id']: j for j in state.get('phase2', {}).get('jobs', []) if j.get('state') == 'verified'}
        for evidence in snapshot['nativeResults']:
            binding = evidence['publicationBinding']
            job = jobs.get(binding['jobId'])
            if (not job or digest([job.get('manifest'), job.get('verification')]) != binding['manifestDigest']
                    or str(job.get('providerReference')) != binding['nativePostId']
                    or job.get('manifest', {}).get('channelId') != binding['connectionId']
                    or str(job.get('manifest', {}).get('platform', '')).lower() != binding['provider']
                    or binding['workspaceId'] != workspace_id):
                raise AlphaError('A report publication changed or was removed.', 410)
            if evidence['value'] is not None and not (eligibility.get(binding['connectionId']) or {}).get('usableNow'):
                raise AlphaError('The current analytics grant no longer permits this report.', 403)
        stored = {e['observationId']: e for e in snapshot['nativeResults'] if e['observationId']}
        if stored:
            cur.execute('''SELECT id::text,value,extract(epoch from observed_at),extract(epoch from ingested_at),definition_version,connection_id,provider,provider_post_id,job_id,metric,unit,read_offset,availability
                           FROM public.pr_metric_observations WHERE workspace_id=%s AND id::text=ANY(%s) FOR SHARE''', (workspace_id, list(stored)))
            found = cur.fetchall()
            if len(found) != len(stored):
                raise AlphaError('Report observation data was removed.', 410)
            for row in found:
                e = stored[row[0]]
                b = e['publicationBinding']
                if (e['value'] is not None and (row[1] is None or float(row[1]) != e['value'] or row[12] != 'available')) or iso(row[2]) != e['observedAt'] or iso(row[3]) != e['ingestedAt'] or tuple(row[4:12]) != (e['definitionVersion'], b['connectionId'], b['provider'], b['nativePostId'], b['jobId'], e['nativeName'], e['unit'], e['readOffset']):
                    raise AlphaError('Report observations changed; create a new reviewed version.', 409)
        expected = digest({k: v for k, v in snapshot.items() if k != 'payloadDigest'})
        if expected != snapshot['payloadDigest']:
            raise AlphaError('Report snapshot integrity check failed.', 409)

    def create_snapshot(self, workspace_id, token, body):
        self.c._require(FLAG)
        scope = body.get('scope')
        with self.repository.transaction(token, workspace_id) as (cur, row, actor):
            from ..permissions import require
            require(self.c.hosted.ideas._member(row), 'edit')
            state = self.c.hosted.ideas._state(row)
            request_id = digest([workspace_id, body.get('idempotencyKey')])
            existing_request = review_state(state).get('requests', {}).get(request_id)
            if existing_request:
                request_digest = digest(['snapshot', {k: v for k, v in body.items() if k != 'workspaceRevision'}])
                if request_digest != existing_request['digest']:
                    raise AlphaError('This request key belongs to a different report.', 409)
                saved = existing_request['result']
                self._snapshot_current(cur, workspace_id, state, actor, saved)
                return {'record': saved, 'workspaceRevision': row[0], 'verified': True, 'existing': True}
            projection = self._project(cur, workspace_id, state, actor, scope)
            if projection['contextDigest'] != body.get('contextDigest') or projection['basisDigest'] != body.get('basisDigest'):
                raise AlphaError('Review the current scope and evidence before saving a report.', 409)
            previous = next((s for s in reversed(review_state(state).get('snapshots', [])) if s['snapshotId'] == body.get('snapshotId')), None)
            if body.get('snapshotId') and not previous:
                raise AlphaError('Report unavailable in this workspace.', 404)
            if previous and body.get('expectedVersion') != previous['version']:
                raise AlphaError('Report version changed. Reload it.', 409)
            source_sha = self.c.values.get('POSTRIFF_SOURCE_SHA') or os.environ.get('VERCEL_GIT_COMMIT_SHA') or os.environ.get('POSTRIFF_SOURCE_SHA')
            prepared = build_review_snapshot(projection, state, body.get('humanNotes', []), actor, source_sha, self.c.clock(), previous=previous, frequency=body.get('frequency', 'weekly'))
            expected_revision = body.get('workspaceRevision')
        box = {}
        def command(state, actor):
            def add(root, request_id):
                if len(root['snapshots']) >= MAX_SNAPSHOTS:
                    raise AlphaError('Report retention limit reached; no existing version was overwritten.', 409)
                root['snapshots'].append(copy.deepcopy(prepared))
                return prepared
            box['record'] = _request(state, workspace_id, 'snapshot', body, add)
            return state
        def recheck(cur, state, actor):
            current = self._project(cur, workspace_id, state, actor, context_input(projection['resolvedContext']))
            if current['basisDigest'] != projection['basisDigest']:
                raise AlphaError('Evidence changed during report preparation.', 409)
            self._snapshot_current(cur, workspace_id, state, actor, box['record'])
        saved = self.repository.command(workspace_id, token, expected_revision, command, requirement='edit',
                                        audit_event=lambda _: ('review.snapshot', prepared['snapshotId'], {'version': prepared['version']}), after=recheck)
        return {'record': box['record'], 'workspaceRevision': saved['revision'], 'verified': True, 'existing': False}

    def stored_snapshot(self, state, snapshot_id, version):
        snapshot = next((s for s in review_state(state).get('snapshots', []) if s['snapshotId'] == snapshot_id and s['version'] == version), None)
        if snapshot is None:
            raise AlphaError('Report unavailable in this workspace.', 404)
        return snapshot

    def snapshot(self, workspace_id, token, snapshot_id, version, *, format_=None):
        self.c._require(FLAG)
        with self.repository.transaction(token, workspace_id) as (cur, row, actor):
            state = self.c.hosted.ideas._state(row)
            snapshot = self.stored_snapshot(state, snapshot_id, version)
            self._snapshot_current(cur, workspace_id, state, actor, snapshot)
            result = format_snapshot(snapshot, format_) if format_ else copy.deepcopy(snapshot)
            self._snapshot_current(cur, workspace_id, state, actor, snapshot)
            return result
