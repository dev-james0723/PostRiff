"""Read-only, rights-bound review projections over existing native observations.

Saved settings and immutable proof attachments use the workspace aggregate;
this adapter owns no acquisition, model, publishing or calibration engine.
"""
from __future__ import annotations

import copy
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError
from .. import insights, locales
from ..contracts import digest
from .growth_loop import verified_at

SCHEMA_VERSION = '1.0'
HORIZONS = {'1h': 3600, '24h': 86400, '7d': 604800}
FRESHNESS_POLICY = 'scheduled-native-offset-v1'
MAX_POSTS = 300
MAX_VIEWS = 32
MAX_SNAPSHOTS = 64


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) or isinstance(value, Decimal) and value.is_finite()


def iso(value):
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


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


def review_state(state):
    return (state.get('coworker') or {}).get('review') or {}


def resolve_review_context(workspace_id, value, state, now, *, rights_epoch='unknown'):
    if not isinstance(value, dict):
        raise AlphaError('Review scope must be structured.', 400)
    allowed = {'schemaVersion','workspaceId','channelIds','publicationPeriod','relativeDateRule','horizon','language','formatIds','tagSelection',
               'nativeMetric','comparison','cutoffAt','scopeKind','aggregation','attributionState'}
    if set(value) - allowed or value.get('workspaceId', workspace_id) != workspace_id or value.get('schemaVersion', SCHEMA_VERSION) != SCHEMA_VERSION:
        raise AlphaError('This review scope is not compatible with this workspace.', 400)
    channels = {c['id']: c for c in state.get('phase2', {}).get('channels', [])}
    selected = value.get('channelIds', [])
    if not isinstance(selected, list) or len(selected) > 8 or any(not isinstance(c, str) or c not in channels for c in selected):
        raise AlphaError('Choose accounts from this workspace.', 400)
    selected = sorted(set(selected))
    providers = sorted({str(channels[c].get('platform', '')).lower() for c in selected})
    formats = value.get('formatIds', [])
    # Format identities come from existing manifests and the existing publishing catalog.
    from postriff_phase2 import content_types
    known = {f.get('formatId', f.get('id')) for f in content_types.CATALOG} if hasattr(content_types, 'CATALOG') else set()
    known |= {j.get('manifest', {}).get('contentType', {}).get('formatId') for j in state.get('phase2', {}).get('jobs', [])}
    if not isinstance(formats, list) or len(formats) > 12 or any(not isinstance(f, str) or f not in known for f in formats):
        raise AlphaError('Choose known content formats.', 400)
    tags = value.get('tagSelection', [])
    definitions = review_state(state).get('tags', {})
    if not isinstance(tags, list) or len(tags) > 30:
        raise AlphaError('Choose at most 30 classifications.', 400)
    for tag in tags:
        if not isinstance(tag, dict) or set(tag) != {'tagId','kind','classificationVersion'} or tag.get('kind') not in ('theme','campaign','series'):
            raise AlphaError('Classification must include its kind and version.', 400)
        if tag['tagId'] not in definitions or definitions[tag['tagId']]['kind'] != tag['kind'] or type(tag['classificationVersion']) is not int:
            raise AlphaError('Choose classifications from this workspace.', 400)
    native = value.get('nativeMetric')
    if native is None:
        native = [{'provider': p, 'nativeName': n, 'definitionVersion': insights.DEFINITION_VERSION, 'unit': 'count'} for p in providers for n in insights.INSIGHT_METRICS.get(p, ())]
    if not isinstance(native, list) or len(native) > 48:
        raise AlphaError('Choose supported native metrics.', 400)
    for m in native:
        if not isinstance(m, dict) or set(m) != {'provider','nativeName','definitionVersion','unit'} or m['provider'] not in providers or m['nativeName'] not in insights.INSIGHT_METRICS.get(m['provider'], ()) or m['definitionVersion'] != insights.DEFINITION_VERSION or m['unit'] != 'count':
            raise AlphaError('Use the current provider-native metric definition.', 400)
    language = value.get('language')
    if language is not None:
        language = locales.canonical(language)
        if language is None:
            raise AlphaError('Choose a canonical language or all languages.', 400)
    horizon = value.get('horizon', '24h')
    aggregation = value.get('aggregation', 'median')
    if horizon not in HORIZONS or aggregation not in ('median','mean') or value.get('scopeKind', 'published_content_cohort') != 'published_content_cohort':
        raise AlphaError('Choose a supported horizon and aggregation.', 400)
    if value.get('attributionState', 'unknown') != 'unknown':
        raise AlphaError('Promotion status must come from native evidence; it is currently unknown.', 400)
    chosen = resolve_relative_period(value['relativeDateRule'], now) if value.get('relativeDateRule') else period(value.get('publicationPeriod'))
    comparison = value.get('comparison', {'kind': 'none'})
    if not isinstance(comparison, dict) or comparison.get('kind') not in ('none','previous_period'):
        raise AlphaError('Choose a supported comparison.', 400)
    if comparison['kind'] == 'previous_period':
        baseline = period(comparison.get('publicationPeriod'))
        if stamp(baseline['end']) > stamp(chosen['start']):
            raise AlphaError('The baseline must precede this publication cohort.', 400)
        comparison = {'kind':'previous_period', 'publicationPeriod':baseline}
    elif set(comparison) != {'kind'}:
        raise AlphaError('A comparison with no baseline cannot contain a period.', 400)
    cutoff = stamp(value['cutoffAt']) if value.get('cutoffAt') else now
    if cutoff > now:
        raise AlphaError('The observation cutoff cannot be in the future.', 400)
    result = {'schemaVersion':SCHEMA_VERSION, 'workspaceId':workspace_id, 'channelIds':selected, 'providers':providers,
              'publicationPeriod':chosen, 'horizon':horizon, 'language':language, 'formatIds':sorted(set(formats)),
              'tagSelection':sorted(tags,key=lambda t:(t['kind'],t['tagId'])), 'nativeMetric':sorted(native,key=lambda m:(m['provider'],m['nativeName'])),
              'comparison':comparison,'cutoffAt':iso(cutoff),'scopeKind':'published_content_cohort','aggregation':aggregation,
              'attributionState':'unknown','contextRevision':review_state(state).get('classificationVersion',0), 'rightsEpoch':rights_epoch}
    result['contextDigest'] = digest(result)
    return result


def safe_source(value):
    """Only known native reader endpoints. Never persist queries, fragments or credentials."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.hostname not in ('graph.threads.net','graph.instagram.com') or parsed.username or parsed.password:
            return None
        return urlunsplit((parsed.scheme,parsed.hostname,parsed.path,'',''))
    except ValueError:
        return None


def matched_ratio(numerator, denominator):
    keys = ('jobId','connectionId','provider','nativePostId','readOffset','observedAt','ingestedAt','definitionVersion')
    if any(numerator.get(k) is None or numerator.get(k) != denominator.get(k) for k in keys):
        return {'value':None,'reason':'incompatible_readings'}
    n,d = numerator.get('value'),denominator.get('value')
    if not finite(n) or not finite(d) or n < 0 or d < 0:
        return {'value':None,'reason':'missing_reading'}
    return {'value':float(n/d) if d else None,'reason':None if d else 'zero_denominator', 'numerator':float(n),'denominator':float(d)}


def _classification(state, job_id, version):
    rows = review_state(state).get('classifications', {}).get(job_id, [])
    return next((r for r in reversed(rows) if r['version'] <= version), {'tags':[]})


def project_review(state, context, observations, direct_connections, now):
    """Pure projection. Current rights override even a previously measured zero."""
    cutoff = stamp(context['cutoffAt'])
    selected = context['publicationPeriod']
    baseline = context['comparison'].get('publicationPeriod')
    channels = {c['id']:c for c in state.get('phase2',{}).get('channels',[])}
    jobs = [j for j in state.get('phase2',{}).get('jobs',[]) if j.get('state') == 'verified' and j.get('providerReference')]
    all_count = len(jobs)
    jobs = sorted(jobs,key=lambda j:verified_at(j) or 0,reverse=True)[:MAX_POSTS]
    rows = defaultdict(list)
    for row in observations:
        rows[(row.get('jobId'),row.get('nativeName'))].append(row)
    results, cohort_groups, excluded = [], defaultdict(lambda: {'current':[],'baseline':[]}), Counter()
    publications = set()
    for job in jobs:
        manifest = job.get('manifest') or {}
        account, provider = manifest.get('channelId'), str(manifest.get('platform','')).lower()
        published = verified_at(job)
        if account not in context['channelIds'] or not finite(published):
            continue
        language = locales.canonical(manifest.get('payload',{}).get('language'))
        form = manifest.get('contentType',{}).get('formatId')
        if context['language'] is not None and language != context['language'] or context['formatIds'] and form not in context['formatIds']:
            continue
        if any(t['tagId'] not in _classification(state,job['id'],t['classificationVersion'])['tags'] for t in context['tagSelection']):
            continue
        side = 'current' if stamp(selected['start']) <= published < stamp(selected['end']) else 'baseline' if baseline and stamp(baseline['start']) <= published < stamp(baseline['end']) else None
        if side is None:
            continue
        channel = channels.get(account,{})
        access = 'revoked' if channel.get('revoked') or state.get('accountDeletion') else 'disconnected' if not channel else 'allowed' if account in direct_connections else 'not_authorized'
        publications.add(job['id'])
        binding = {'workspaceId':context['workspaceId'],'jobId':job['id'],'connectionId':account,'provider':provider,
                   'nativePostId':str(job['providerReference']),'manifestDigest':digest([manifest,job.get('verification')]),'publicationAt':iso(published)}
        for metric in context['nativeMetric']:
            if metric['provider'] != provider:
                continue
            candidates = rows[(job['id'],metric['nativeName'])]
            valid, reasons = [], []
            for row in candidates:
                reason = ('publication_mismatch' if any(row.get(k) != binding[k] for k in ('connectionId','provider','nativePostId'))
                          else 'unknown_read_offset' if row.get('readOffset') is None
                          else 'wrong_horizon' if row['readOffset'] != context['horizon']
                          else 'definition_mismatch' if row.get('definitionVersion') != metric['definitionVersion'] or row.get('unit') != metric['unit']
                          else 'missing_observation_time' if not finite(row.get('observedAt')) or not finite(row.get('ingestedAt'))
                          else 'after_cutoff' if row['observedAt'] > cutoff or row['ingestedAt'] > cutoff
                          else 'window_unqualified' if row['observedAt'] < published + HORIZONS[context['horizon']]
                          else None)
                if reason:
                    reasons.append(reason)
                else:
                    valid.append(row)
            valid.sort(key=lambda r:(r['observedAt'],r['ingestedAt'],r.get('observationId') or ''),reverse=True)
            latest = valid[0] if valid else {}
            reading = next((r for r in valid if r.get('availability')=='available' and finite(r.get('value')) and r['value']>=0), latest)
            value = reading.get('value')
            value_state = 'measured' if reading.get('availability') == 'available' and finite(value) and value >= 0 else 'invalid' if value is not None else 'missing'
            stale = bool(reading and latest != reading)
            reason = (access if access != 'allowed' else 'stale_reading' if stale else reasons[0] if not valid and reasons else
                      'invalid_value' if value_state=='invalid' else 'missing_reading' if value_state!='measured' else
                      'missing_observation_identity' if not reading.get('observationId') else None)
            collection = latest.get('collectionState','pending_horizon' if published+HORIZONS[context['horizon']] > now else 'unscheduled')
            e = {'observationId':reading.get('observationId') if access=='allowed' else None,'publicationBinding':binding,
                 **metric,'value':float(value) if value_state=='measured' and access=='allowed' else None,
                 'valueState':value_state if access=='allowed' else 'missing','reason':reason,'collectionState':collection,
                 'accessState':access,'freshnessState':'stale' if stale else 'current' if reading else 'unknown',
                 'freshnessPolicyVersion':FRESHNESS_POLICY,'readOffset':reading.get('readOffset') if access=='allowed' else None,
                 'observedAt':iso(reading['observedAt']) if reading and access=='allowed' else None,
                 'ingestedAt':iso(reading['ingestedAt']) if reading and access=='allowed' else None,
                 'nativeWindow':'cumulative_at_observation','sourceRef':safe_source(reading.get('sourceRef')) if access=='allowed' else None,
                 'displayPermission':'allowed' if access=='allowed' else 'restricted', 'periodSide':side,
                 'lastAttemptState':latest.get('availability') if access=='allowed' else None,
                 'language':language,'formatId':form,'eligible':reason is None and value_state=='measured'}
            results.append(e)
            if e['eligible']:
                key = (provider,account,language,form,metric['nativeName'],metric['definitionVersion'],metric['unit'],context['horizon'])
                cohort_groups[key][side].append(e)
            else:
                excluded[reason or 'unavailable'] += 1
    groups,comparisons = [],[]
    for key, sides in sorted(cohort_groups.items(),key=lambda item:str(item[0])):
        cohort = dict(zip(('provider','connectionId','language','formatId','nativeName','definitionVersion','unit','horizon'),key))
        aggregate = statistics.median if context['aggregation']=='median' else statistics.mean
        current,previous = sides['current'],sides['baseline']
        a = float(aggregate(e['value'] for e in current)) if current else None
        b = float(aggregate(e['value'] for e in previous)) if previous else None
        groups.append({'cohort':cohort,'sampleSize':len(current),'baselineSampleSize':len(previous),'value':a,'baselineValue':b,
                       'aggregation':context['aggregation'],'minimumSample':insights.MIN_COMPARABLE,'evidenceIds':[e['observationId'] for e in current]})
        if baseline:
            reason = 'insufficient_sample' if min(len(current),len(previous)) < insights.MIN_COMPARABLE else 'missing_baseline' if b is None else 'zero_baseline' if b==0 else None
            comparisons.append({'cohort':cohort,'current':a,'baseline':b,'relativeChange':(a-b)/b if reason is None else None,
                                'reason':reason,'sampleSize':len(current),'baselineSampleSize':len(previous),'causal':False,'aggregation':context['aggregation']})
    measured = [e for e in results if e['eligible']]
    observed = [e['observedAt'] for e in results if e['observedAt']]
    coverage = {'eligible':len({e['publicationBinding']['jobId'] for e in measured}),'publications':len(publications),
                'measured':len(measured),'missing':len(results)-len(measured),'excludedByReason':dict(excluded),
                'earliestAvailableAt':min(observed) if observed else None,'collectionStartAt':None,
                'lastSuccessfulRead':max(observed) if observed else None,'cutoffAt':context['cutoffAt'],
                'truncated':all_count>MAX_POSTS,'maximumPosts':MAX_POSTS,'historyLimitations':['Available stored records only; HistoryImport OFF.','Collection start is unknown.']}
    basis = digest({'contextDigest':context['contextDigest'],'nativeResults':results,'coverage':coverage})
    return {'schemaVersion':SCHEMA_VERSION,'resolvedContext':context,'contextDigest':context['contextDigest'],'basisDigest':basis,
            'nativeResults':results,'groups':groups,'comparisons':comparisons,'coverage':coverage,
            'limitations':['Cumulative native readings at the chosen post age; not events during this week.','Promotion status unknown.','Observational evidence; causal=false.','Platforms and distinct account cohorts are shown separately.']}
