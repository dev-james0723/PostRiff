"""Read-only, rights-bound review projections over existing native observations.

Saved settings and immutable proof attachments use the workspace aggregate;
this adapter owns no acquisition, model, publishing or calibration engine.
"""
from __future__ import annotations

import copy
import math
import statistics
import re
import csv
import html
import io
import json
import os
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


def review_state(state):
    return (state.get('coworker') or {}).get('review') or {}


def _root(state):
    root = state.setdefault('coworker',{}).setdefault('review',{})
    for key, default in (('views',[]),('tags',{}),('classifications',{}),('suggestions',[]),('snapshots',[]),('requests',{}),('classificationVersion',0)):
        root.setdefault(key,copy.deepcopy(default))
    return root


def _request(state, workspace_id, operation, body, build):
    key = body.get('idempotencyKey')
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',key):
        raise AlphaError('Use a bounded idempotency key.',400)
    root = _root(state)
    request_id = digest([workspace_id,key])
    request_digest = digest([operation,{k:v for k,v in body.items() if k != 'workspaceRevision'}])
    existing = root['requests'].get(request_id)
    if existing:
        if existing['digest'] != request_digest:
            raise AlphaError('This request key belongs to different content.',409)
        return copy.deepcopy(existing['result'])
    if len(root['requests']) >= 1024:
        raise AlphaError('The review command history is full. Review retained records first.',409)
    result = build(root,request_id)
    root['requests'][request_id] = {'digest':request_digest,'result':copy.deepcopy(result)}
    return result


def save_review_view(state, workspace_id, body, actor, now):
    definition = body.get('filterDefinition')
    resolve_review_context(workspace_id,definition,state,now)
    name = body.get('name')
    if not isinstance(name,str) or not name.strip() or len(name)>120:
        raise AlphaError('Name the Saved View in at most 120 characters.',400)
    def save(root, request_id):
        existing = next((v for v in root['views'] if v['id']==body.get('id')),None)
        if body.get('id') and not existing:
            raise AlphaError('This Saved View is unavailable in this workspace.',404)
        if type(body.get('expectedRevision')) is not int or body['expectedRevision'] != (existing['revision'] if existing else 0):
            raise AlphaError('This Saved View changed. Reload it.',409)
        if not existing and len(root['views'])>=MAX_VIEWS:
            raise AlphaError('Saved View limit reached. Archive an existing view first.',409)
        value = {'id':existing['id'] if existing else 'rv_'+request_id[:24], 'workspaceId':workspace_id,'schemaVersion':SCHEMA_VERSION,
                 'name':name.strip(),'owner':existing['owner'] if existing else actor,'revision':(existing['revision'] if existing else 0)+1,
                 'filterDefinition':copy.deepcopy(definition),'status':'archived' if body.get('archive') is True else 'active',
                 'classificationVersion':root['classificationVersion'],'createdAt':existing['createdAt'] if existing else iso(now),'updatedAt':iso(now)}
        if existing:
            root['views'][root['views'].index(existing)] = value
        else:
            root['views'].append(value)
        return value
    return _request(state,workspace_id,'view',body,save)


def classify_content(state, workspace_id, body, actor, now):
    job = next((j for j in state.get('phase2',{}).get('jobs',[]) if j.get('id')==body.get('jobId') and j.get('state')=='verified'),None)
    if not job or digest([job.get('manifest'),job.get('verification')]) != body.get('manifestDigest'):
        raise AlphaError('Review the current publication before classifying it.',409)
    account = job.get('manifest',{}).get('channelId')
    if not any(c.get('id')==account and not c.get('revoked') for c in state.get('phase2',{}).get('channels',[])):
        raise AlphaError('This publication account is disconnected.',403)
    tags = body.get('tags')
    if not isinstance(tags,list) or len(tags)>30 or body.get('source') not in ('human','ai_suggestion'):
        raise AlphaError('Choose theme, campaign or series classifications.',400)
    for t in tags:
        if not isinstance(t,dict) or set(t)!={'tagId','kind','label'} or t['kind'] not in ('theme','campaign','series') or not isinstance(t['tagId'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',t['tagId']) or not isinstance(t['label'],str) or not 1<=len(t['label'])<=120:
            raise AlphaError('Use bounded classification identities and labels.',400)
    def apply(root, request_id):
        current = _classification(state,job['id'],root['classificationVersion'])
        if type(body.get('expectedRevision')) is not int or body['expectedRevision'] != current.get('version',0):
            raise AlphaError('Content classification changed. Reload it.',409)
        if body.get('confirmed') is not True:
            if body['source'] != 'ai_suggestion':
                raise AlphaError('Confirm the classifications you reviewed.',400)
            if len(root['suggestions'])>=64:
                raise AlphaError('Review existing classification suggestions first.',409)
            suggestion = {'id':'rcs_'+request_id[:24],'jobId':job['id'],'tags':copy.deepcopy(tags),'status':'suggested','manifestDigest':body['manifestDigest']}
            root['suggestions'].append(suggestion)
            return suggestion
        for t in tags:
            old = root['tags'].get(t['tagId'])
            if old and old != t:
                raise AlphaError('This classification ID already has a different definition.',409)
            root['tags'][t['tagId']] = copy.deepcopy(t)
        root['classificationVersion'] += 1
        value = {'version':root['classificationVersion'],'jobId':job['id'],'tags':sorted({t['tagId'] for t in tags}),
                 'source':body['source'],'approvedBy':actor,'approvedAt':iso(now),'manifestDigest':body['manifestDigest'],'affectedPublications':1,'status':'approved'}
        root['classifications'].setdefault(job['id'],[]).append(value)
        return value
    return _request(state,workspace_id,'classification',body,apply)


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
    known = set(content_types.FORMAT_IDS)
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
        if tag['tagId'] not in definitions or definitions[tag['tagId']]['kind'] != tag['kind'] or type(tag['classificationVersion']) is not int or not 0 <= tag['classificationVersion'] <= review_state(state).get('classificationVersion',0):
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
    if bool(value.get('relativeDateRule')) == bool(value.get('publicationPeriod')):
        raise AlphaError('Choose one publication date scope.',400)
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
            if reason is None and collection != 'measured':
                reason = collection
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


def review_hypothesis_eligible(state, projection, hypothesis, now):
    from . import performance
    h,ctx= hypothesis,projection['resolvedContext']
    cohort=h.get('cohort',{})
    if ctx['horizon']!='24h' or h.get('expiresAt',0)<=now or min(h.get('sample_a',0),h.get('sample_b',0))<performance.MIN_ARM:
        return False
    if not all(cohort.get(k) for k in ('connectionId','language','contentTypeId','definitionVersion')) or h.get('dimension') not in performance.DIMENSIONS:
        return False
    jobs={j['id']:j for j in state.get('phase2',{}).get('jobs',[])}
    qualified={e['publicationBinding']['jobId'] for e in projection['nativeResults'] if e['eligible'] and e['nativeName']==h.get('metric') and
               e['publicationBinding']['connectionId']==cohort['connectionId'] and e['provider']==cohort.get('provider') and
               e['language']==cohort['language'] and e['definitionVersion']==cohort['definitionVersion'] and
               jobs.get(e['publicationBinding']['jobId'],{}).get('manifest',{}).get('contentType',{}).get('id')==cohort['contentTypeId']}
    source_ids=set((h.get('evidence_ids') or [])+(h.get('counter_evidence_ids') or []))
    if not source_ids or not source_ids<=qualified:
        return False
    a,b,_=performance.DIMENSIONS[h['dimension']]
    counts=Counter(performance.features(jobs[jid]).get(h['dimension']) for jid in qualified)
    return counts[a]>=performance.MIN_ARM and counts[b]>=performance.MIN_ARM


def review_takeaways(projection, state, now):
    """Bounded deterministic observations. Existing experiment references only."""
    result = []
    for group in projection['groups']:
        if group['sampleSize'] < insights.MIN_COMPARABLE:
            continue
        cohort = group['cohort']
        current = [e for e in projection['nativeResults'] if e['eligible'] and e['periodSide']=='current' and
                   all(e.get(k)==cohort.get(k) for k in ('provider','nativeName','language','formatId','definitionVersion')) and e['publicationBinding']['connectionId']==cohort['connectionId']]
        counter = [e for e in projection['nativeResults'] if e['eligible'] and e['periodSide']=='baseline' and
                   all(e.get(k)==cohort.get(k) for k in ('provider','nativeName','language','formatId','definitionVersion')) and e['publicationBinding']['connectionId']==cohort['connectionId']]
        if not current:
            continue
        experiment = next((e for e in state.get('coworker',{}).get('growthLoop',{}).get('experiments',[]) if e.get('reviewContextDigest')==projection['contextDigest'] and e.get('reviewBasisDigest')==projection['basisDigest']),None)
        next_step = {'kind':'experiment','existingExperimentId':experiment['id'],'href':'/app/growth','label':'Review this existing experiment'} if experiment else {
            'kind':'collect','existingExperimentId':None,'href':'/app/weekly','label':'Prepare one controlled test in Weekly Operator'}
        hypothesis=next((h for h in projection.get('_hypotheses',[]) if h['metric']==cohort['nativeName'] and h['cohort'].get('connectionId')==cohort['connectionId'] and review_hypothesis_eligible(state,projection,h,now)),None)
        if not experiment and hypothesis:
            next_step={'kind':'propose','existingExperimentId':None,'hypothesisId':hypothesis['id'],'href':'/app/growth','label':'Propose this controlled test in Growth Loop'}
        result.append({'id':digest([projection['contextDigest'],cohort])[:24], 'contextDigest':projection['contextDigest'],
                       'basisDigest':projection['basisDigest'],'status':'observation','actualPeriod':projection['resolvedContext']['publicationPeriod'],
                       'nativeMetric':{k:cohort[k] for k in ('provider','nativeName','definitionVersion','unit')},
                       'sampleSize':len(current),'coverage':projection['coverage'],'supportBindings':copy.deepcopy(current),
                       'counterEvidenceBindings':copy.deepcopy(counter),'limitations':projection['limitations'],
                       'statement':f"The {group['aggregation']} {cohort['nativeName']} was {group['value']:g} across {len(current)} comparable publications in this account cohort.",
                       'nextStep':next_step,'expiresAt':iso(now+3600),'causal':False})
        if len(result)==3:
            break
    return result


def build_review_snapshot(projection, state, notes, actor, source_sha, now, *, previous=None, frequency='weekly'):
    if not isinstance(source_sha,str) or not re.fullmatch(r'[a-f0-9]{40}',source_sha):
        raise AlphaError('The runtime source SHA is unavailable. Snapshot creation is blocked.',503)
    if frequency not in ('weekly','monthly') or not isinstance(notes,list) or len(notes)>12 or any(not isinstance(n,str) or len(n)>4000 for n in notes):
        raise AlphaError('Use a weekly/monthly report and at most twelve bounded notes.',400)
    from .growth_loop import view, period as proof_period, proof_counts
    start,end = proof_period(now,frequency)
    proof = next((p for p in reversed(view(state)['proofs']) if p.get('frequency')==frequency),None)
    scope = {'kind':'workspace_wide','timezone':'UTC','start':iso(start),'end':iso(end)}
    work = {'proofId':None,'scope':scope,'counts':proof_counts(state,start,end),'countingRules':'Existing Growth Loop proof counting rules; completed, accepted and verified are separate.'}
    time_back = {'value':None,'unit':'seconds','state':'unavailable','estimationMethodVersion':'existing-time-back-ledger-v1','inputs':[]}
    if proof:
        work = {'proofId':proof['id'],'scope':{'kind':'workspace_wide','timezone':'UTC','originalPeriod':copy.deepcopy(proof.get('period'))},
                'counts':copy.deepcopy(proof.get('counts',{})),'countingRules':copy.deepcopy(proof.get('countingRules','Existing Growth Loop proof rules.'))}
        tb = proof.get('timeBack') or {}
        if tb.get('coverage')=='available':
            time_back.update(value=sum(r.get('savedSeconds',0) for r in tb.get('byConfidence',[])),state='estimated',inputs=copy.deepcopy(tb.get('byConfidence',[])))
    family = previous['snapshotId'] if previous else 'rs_'+digest([projection['resolvedContext']['workspaceId'],projection['contextDigest'],now,actor,notes])[:24]
    result = {'snapshotId':family,'schemaVersion':SCHEMA_VERSION,'version':previous['version']+1 if previous else 1,
              'generatedAt':iso(now),'createdBy':actor,'frequency':frequency,'resolvedContext':copy.deepcopy(projection['resolvedContext']),
              'contextDigest':projection['contextDigest'],'basisDigest':projection['basisDigest'],'sourceSha':source_sha,
              'nativeResults':copy.deepcopy(projection['nativeResults']),'coverage':copy.deepcopy(projection['coverage']),
              'groups':copy.deepcopy(projection['groups']),'comparisons':copy.deepcopy(projection['comparisons']),
              'observationBindings':[copy.deepcopy(e) for e in projection['nativeResults'] if e['observationId']],
              'workProof':work,'timeBack':time_back,'takeaways':copy.deepcopy(projection.get('takeaways',review_takeaways(projection,state,now))),
              'humanNotes':copy.deepcopy(notes),'limitations':copy.deepcopy(projection['limitations']),
              'classificationVersion':projection['resolvedContext']['contextRevision'],
              'sourceMethodVersions':[insights.DEFINITION_VERSION,FRESHNESS_POLICY],'rightsEpoch':projection['resolvedContext']['rightsEpoch'],
              'rendererVersion':'review-export-v1','changeReason':'Notes or observations refreshed' if previous else 'Initial fixed report'}
    result['payloadDigest'] = digest(result)
    return result


def format_snapshot(snapshot, format_):
    """All renderers receive one frozen payload. No database, provider or model."""
    s = snapshot
    ctx = s['resolvedContext']
    period_ = ctx['publicationPeriod']
    preamble = [f"# Rafii {s['frequency']} review",f"Snapshot: {s['snapshotId']} / version {s['version']}",
                f"Context: {s['contextDigest']}",f"Payload: {s['payloadDigest']}",f"Source SHA: {s['sourceSha']}",
                f"Publication cohort: [{period_['start']}, {period_['end']}) · {period_['timezone']}",
                f"Accounts: {', '.join(ctx['channelIds']) or 'None'} · {ctx['horizon']} · {ctx['aggregation']}",
                f"Filters: {json.dumps(ctx,ensure_ascii=False,sort_keys=True)}",'\n## Scope and coverage',json.dumps(s['coverage'],ensure_ascii=False,sort_keys=True),
                '\n## Completed work (separate workspace scope)',json.dumps(s['workProof'],ensure_ascii=False,sort_keys=True),
                'Time Back (estimated when available): '+json.dumps(s['timeBack'],ensure_ascii=False,sort_keys=True),'\n## Native results']
    metric_lines = [f"{e['publicationBinding']['connectionId']} / {e['publicationBinding']['jobId']} · {e['nativeName']}: {e['value'] if e['value'] is not None else 'null'} · {e['valueState']} · {e['reason'] or 'measured'} · {e['definitionVersion']} · {e['readOffset'] or 'unknown'} · observed {e['observedAt'] or 'unknown'} · ingested {e['ingestedAt'] or 'unknown'} · {e['sourceRef'] or 'source unavailable'}" for e in s['nativeResults']]
    tail = ['\n## Observations and one next test'] + [t['statement']+' Next: '+t['nextStep']['label']+' Support: '+','.join(e['observationId'] for e in t['supportBindings'])+' Counter-evidence: '+','.join(e['observationId'] for e in t['counterEvidenceBindings']) for t in s['takeaways']]
    tail += ['\n## Human notes',*s['humanNotes'],'\n## Sources and limitations',*s['limitations'],
             'Collection start is unknown; HistoryImport OFF. Offline downloaded files cannot be remotely revoked.']
    markdown = '\n\n'.join(preamble+metric_lines+tail)+'\n'
    if format_=='markdown':
        content, content_type, extension = markdown,'text/markdown; charset=utf-8','md'
    elif format_=='csv':
        fields = ['snapshotId','version','payloadDigest','contextDigest','sourceSha','channelId','jobId','nativePostId','observationId','provider','nativeName','value','valueState','reason','definitionVersion','unit','readOffset','nativeWindow','observedAt','ingestedAt','accessState','freshnessState','collectionState','sourceRef','publicationAt','periodStart','periodEnd','timezone','filters','humanNotes','workProof','timeBack','takeaways','limitations']
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output,fieldnames=fields,lineterminator='\n');writer.writeheader()
        def cell(value):
            text = '' if value is None else str(value)
            return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r')) else text
        for e in s['nativeResults'] or [None]:
            values = {k:s[k] for k in ('snapshotId','version','payloadDigest','contextDigest','sourceSha')}
            values.update(periodStart=period_['start'],periodEnd=period_['end'],timezone=period_['timezone'],filters=json.dumps(ctx,ensure_ascii=False,sort_keys=True),
                          humanNotes=' | '.join(s['humanNotes']),workProof=json.dumps(s['workProof'],ensure_ascii=False),timeBack=json.dumps(s['timeBack'],ensure_ascii=False),
                          takeaways=json.dumps(s['takeaways'],ensure_ascii=False),limitations=' | '.join(s['limitations']))
            if e:
                values.update({k:e.get(k) for k in fields if k in e})
                b = e['publicationBinding'];values.update(channelId=b['connectionId'],jobId=b['jobId'],nativePostId=b['nativePostId'],publicationAt=b['publicationAt'])
                values['value'] = e['value'] if e['value'] is not None else 'null'
            else:
                values.update(value='null',valueState='missing',reason='no_native_readings')
            writer.writerow({k:cell(v) for k,v in values.items()})
        content, content_type, extension = output.getvalue(),'text/csv; charset=utf-8','csv'
    elif format_=='pdf':
        # Existing web/browser rendering; the user prints this fixed document to
        # PDF. Chromium acceptance renders this exact HTML into an actual PDF.
        content = '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>Rafii '+html.escape(s['snapshotId'])+'</title><style>@page{size:A4;margin:18mm}body{font:11pt system-ui,"Noto Sans CJK TC","PingFang TC",sans-serif;line-height:1.6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}h1{font-size:22pt}table{border-collapse:collapse;width:100%;font-size:9pt}th,td{border:1px solid #ccc;padding:5px;overflow-wrap:anywhere}thead{display:table-header-group}tr{break-inside:avoid}</style><h1>Rafii fixed review</h1><pre>'+html.escape('\n\n'.join(preamble))+'</pre><table><thead><tr><th>Publication / metric</th><th>Value / state</th><th>Reading / source</th></tr></thead><tbody>'
        for e in s['nativeResults']:
            content += '<tr><td>'+html.escape(e['publicationBinding']['jobId']+' / '+e['nativeName'])+'</td><td>'+html.escape(str(e['value']) if e['value'] is not None else 'null')+' · '+html.escape(e['valueState'])+' · '+html.escape(e['reason'] or 'measured')+'</td><td>'+html.escape((e['observedAt'] or 'unknown')+' / '+(e['ingestedAt'] or 'unknown')+' / '+(e['sourceRef'] or 'unavailable'))+'</td></tr>'
        content += '</tbody></table><pre>'+html.escape('\n\n'.join(tail))+'</pre></html>'
        content_type, extension = 'text/html; charset=utf-8','html'
    else:
        raise AlphaError('Choose PDF, Markdown or CSV.',400)
    return {'snapshotId':s['snapshotId'],'version':s['version'],'payloadDigest':s['payloadDigest'],'rendererVersion':s['rendererVersion'],
            'contentType':content_type,'filename':f"{s['snapshotId']}-v{s['version']}.{extension}",'content':content,
            'rendering':'browser_print_pdf' if format_=='pdf' else 'download'}


def reuse_candidates(state, projection, now):
    channels = {c['id']:c for c in state.get('phase2',{}).get('channels',[]) if not c.get('revoked')}
    if state.get('accountDeletion'):
        return []
    result,seen = [],set()
    for job in reversed(state.get('phase2',{}).get('jobs',[])):
        m = job.get('manifest',{})
        if job.get('state')!='verified' or not job.get('providerReference') or m.get('channelId') not in channels or m.get('trendLineage'):
            continue
        canonical = m.get('variantId') or job.get('variantId') or digest([m.get('channelId'),job.get('providerReference')])
        if canonical in seen:
            continue
        seen.add(canonical)
        text = next((m.get('payload',{}).get(k) for k in ('text','caption','body') if isinstance(m.get('payload',{}).get(k),str)),None)
        if text is None:
            continue
        result.append({'contentId':canonical,'jobId':job['id'],'provider':str(m.get('platform','')).lower(),'connectionId':m['channelId'],
                       'nativePostId':str(job['providerReference']),'text':text,'revision':m.get('contentRevision',digest(m)),
                       'manifestDigest':digest([m,job.get('verification')]),'publicationAt':iso(verified_at(job)) if finite(verified_at(job)) else None,
                       'language':locales.canonical(m.get('payload',{}).get('language')),'formatId':m.get('contentType',{}).get('formatId'),
                       'state':'content_only','rights':'allowed','lastReviewedAt':iso(now),
                       'knownMetricHorizons':sorted({e['readOffset'] for e in projection['nativeResults'] if e['publicationBinding']['jobId']==job['id'] and e['valueState']=='measured' and e['readOffset']}),
                       'nextStep':{'href':'/app/weekly','label':'Review and update facts before preparing a new draft'}})
        if len(result)==30:
            break
    return result


def personalization_status(state, projection, now):
    # Creator calibration qualifies writing-rubric associations. It is not a
    # reviewed timing/format/frequency optimization method. Never widen its gate.
    return {'status':'method_unavailable','methodVersion':None,'accuracy':None,'period':projection['resolvedContext']['publicationPeriod'],
            'timezone':projection['resolvedContext']['publicationPeriod']['timezone'],'sampleSize':projection['coverage']['eligible'],
            'variables':['timing','format','frequency'],'reason':'No reviewed out-of-sample timing/format/frequency method is registered.',
            'nextStep':'Propose one bounded test in the existing Growth Loop; owner approval and restore remain required.'}


def _context_input(context):
    return {k:copy.deepcopy(context[k]) for k in ('schemaVersion','channelIds','publicationPeriod','horizon','language','formatIds','tagSelection','nativeMetric','comparison','cutoffAt','scopeKind','aggregation','attributionState')}


class ReviewService:
    def __init__(self, coworker):
        self.c = coworker
        self.repository = coworker.repository

    def _rights(self, cur, workspace_id, state):
        # The same cursor/transaction as membership and workspace state; lock
        # capability rows against concurrent demotion during export/commit.
        cur.execute("SELECT connection_id,level FROM public.pr_channel_capabilities WHERE workspace_id=%s AND capability='analytics' FOR SHARE", (workspace_id,))
        caps = cur.fetchall()
        direct = {r[0] for r in caps if r[1] == 'Direct'}
        epoch = digest({'caps':sorted(caps),'channels':state.get('phase2',{}).get('channels',[]),'deletion':bool(state.get('accountDeletion'))})
        return direct, epoch

    def _project(self, cur, workspace_id, state, actor, value):
        from ..growth.closed_loop import collection_enabled
        from ..growth.trends.beta import tracking
        direct, epoch = self._rights(cur,workspace_id,state)
        now = self.c.clock()
        context = resolve_review_context(workspace_id,value,state,now,rights_epoch=epoch)
        jobs = [j for j in state.get('phase2',{}).get('jobs',[]) if j.get('state')=='verified' and j.get('providerReference')]
        jobs = sorted(jobs,key=lambda j:verified_at(j) or 0,reverse=True)[:MAX_POSTS]
        tracked = tracking(cur,workspace_id,{'phase2':{**state.get('phase2',{}),'jobs':jobs}},now,
                           enabled=collection_enabled(getattr(self.c.hosted,'growth',None),workspace_id) if getattr(self.c.hosted,'growth',None) else False,limit=MAX_POSTS)
        tracking_index = {(p['job_id'],h['window']):h for p in tracked['posts'] for h in p['horizons']}
        rows = []
        if jobs:
            offset = insights.read_offset_column(cur)
            cur.execute(f"""SELECT o.id::text,o.job_id,o.connection_id,o.provider,o.provider_post_id,o.metric,o.definition_version,
                        o.value,o.unit,o.availability,extract(epoch from o.observed_at),extract(epoch from o.ingested_at),{offset},o.source_endpoint
                        FROM public.pr_metric_observations o WHERE o.workspace_id=%s AND o.job_id=ANY(%s)
                        ORDER BY o.observed_at DESC,o.ingested_at DESC,o.id DESC LIMIT 12001""", (workspace_id,[j['id'] for j in jobs]))
            for r in cur.fetchall():
                row = dict(zip(('observationId','jobId','connectionId','provider','nativePostId','nativeName','definitionVersion','value','unit','availability','observedAt','ingestedAt','readOffset','sourceRef'),r))
                row['observedAt'] = float(row['observedAt'])
                row['ingestedAt'] = float(row['ingestedAt'])
                if isinstance(row['value'],Decimal):
                    row['value'] = float(row['value'])
                row['collectionState'] = tracking_index.get((row['jobId'],row['readOffset']),{}).get('state','unscheduled')
                rows.append(row)
        projection = project_review(state,context,rows[:12000],direct,now)
        projection['postTracking'] = tracked
        if len(rows)>12000:
            projection['coverage']['truncated'] = True
            projection['comparisons'] = []
            projection['groups'] = []
            projection['limitations'].append('Observation loading bound reached; comparison withheld.')
        # Current canonical Trends validators, on this same authorized cursor.
        from ..growth.trends.service import validate_stored_bindings
        index = {j['id']:j for j in jobs}
        lineage = []
        for jid in {e['publicationBinding']['jobId'] for e in projection['nativeResults']}:
            job = index[jid]; bindings = job.get('manifest',{}).get('trendLineage',[])
            if not bindings:
                continue
            try:
                validate_stored_bindings(self.c.hosted.connection_factory,cur,workspace_id,actor,state,bindings,now)
            except (AlphaError,ValueError,KeyError,TypeError):
                for e in projection['nativeResults']:
                    if e['publicationBinding']['jobId']==jid:
                        e.update(value=None,valueState='missing',sourceRef=None,observationId=None,eligible=False,reason='trend_source_unavailable',displayPermission='restricted')
                projection['groups'] = []
                projection['comparisons'] = []
                projection['coverage']['excludedByReason']['trend_source_unavailable'] = projection['coverage']['excludedByReason'].get('trend_source_unavailable',0)+1
                continue
            lineage.append({'jobId':jid,'receiptBindings':copy.deepcopy(bindings),'publication':copy.deepcopy(job['manifest'].get('trendPublication')),
                            'verifiedNativeIdentity':{'jobId':jid,'connectionId':job['manifest']['channelId'],'nativePostId':str(job['providerReference'])},
                            'status':'verified_publication','horizon':context['horizon'],'causal':False})
        projection['trendProvenance'] = lineage
        trend_report=self.c._trend_learning_report(cur,workspace_id,actor,window=context['horizon'])
        if trend_report is not None:
            trend_report['choice_options']=[]
        projection['trendLearning']=trend_report
        eligible = [e for e in projection['nativeResults'] if e['eligible']]
        projection['coverage']['eligible'] = len({e['publicationBinding']['jobId'] for e in eligible})
        projection['coverage']['measured'] = len(eligible)
        projection['coverage']['missing'] = len(projection['nativeResults']) - len(eligible)
        projection['basisDigest'] = digest({k:projection[k] for k in ('contextDigest','nativeResults','coverage','trendProvenance')})
        if trend_report is not None:
            projection['basisDigest']=digest([projection['basisDigest'],{k:v for k,v in trend_report.items() if k!='as_of'}])
        cur.execute("""SELECT id::text,cohort,metric,dimension,sample_a,sample_b,evidence_ids,counter_evidence_ids,extract(epoch from expires_at)
                       FROM public.pr_strategy_hypotheses WHERE workspace_id=%s AND causal=false AND status IN ('candidate','experiment','supported') AND expires_at>to_timestamp(%s)
                       ORDER BY id LIMIT 80""",(workspace_id,now))
        projection['_hypotheses']=[dict(zip(('id','cohort','metric','dimension','sample_a','sample_b','evidence_ids','counter_evidence_ids','expiresAt'),r)) for r in cur.fetchall()]
        projection['takeaways'] = review_takeaways(projection,state,now)
        projection.pop('_hypotheses')
        projection['reuseCandidates'] = reuse_candidates(state,projection,now)
        projection['personalization'] = personalization_status(state,projection,now)
        projection['workspaceRevision'] = None
        return projection

    def read(self, workspace_id, token, value):
        with self.repository.transaction(token,workspace_id) as (cur,row,actor):
            state = self.c.hosted.ideas._state(row)
            result = self._project(cur,workspace_id,state,actor,value)
            result['workspaceRevision'] = row[0]
            return result

    def views(self, workspace_id, token):
        with self.repository.transaction(token,workspace_id) as (cur,row,actor):
            state = self.c.hosted.ideas._state(row)
            _, epoch = self._rights(cur,workspace_id,state)
            values = []
            for view in review_state(state).get('views',[]):
                if view['status']=='archived':
                    continue
                try:
                    resolved = resolve_review_context(workspace_id,view['filterDefinition'],state,self.c.clock(),rights_epoch=epoch)
                    selected = {c['id']:c for c in state.get('phase2',{}).get('channels',[])}
                    if any(selected[c].get('revoked') for c in resolved['channelIds']):
                        raise AlphaError('Saved View account disconnected.',410)
                    values.append({**view,'resolvedContext':resolved,'blockedReason':None})
                except AlphaError as error:
                    values.append({**view,'resolvedContext':None,'blockedReason':str(error)})
            return {'schemaVersion':SCHEMA_VERSION,'views':values,'tags':list(review_state(state).get('tags',{}).values()),
                    'classifications':{jid:rows[-1] for jid,rows in review_state(state).get('classifications',{}).items() if rows},
                    'suggestions':copy.deepcopy(review_state(state).get('suggestions',[])),
                    'snapshots':[{'snapshotId':s['snapshotId'],'version':s['version'],'generatedAt':s['generatedAt']} for s in review_state(state).get('snapshots',[])],
                    'classificationVersion':review_state(state).get('classificationVersion',0),'workspaceRevision':row[0]}

    def _mutate(self, workspace_id, token, body, operation, helper):
        revision = body.get('workspaceRevision')
        if type(revision) is not int:
            raise AlphaError('Review the current workspace revision first.',409)
        current = self.repository.get(workspace_id,token)
        request_key = body.get('idempotencyKey')
        if isinstance(request_key,str) and digest([workspace_id,request_key]) in review_state(current['state']).get('requests',{}):
            revision = current['revision']
        box = {}
        def command(state, actor):
            box['record'] = helper(state,workspace_id,body,actor,self.c.clock())
            return state
        def after(cur,state,actor):
            self._rights(cur,workspace_id,state)
            if operation=='view':
                resolve_review_context(workspace_id,box['record']['filterDefinition'],state,self.c.clock())
        saved = self.repository.command(workspace_id,token,revision,command,requirement='edit',
                                        audit_event=lambda _:('review.'+operation,box['record'].get('id',body.get('jobId','')),{'schemaVersion':SCHEMA_VERSION}),after=after)
        return {'record':box['record'],'workspaceRevision':saved['revision'],'verified':True}

    def save_view(self, workspace_id, token, body):
        return self._mutate(workspace_id,token,body,'view',save_review_view)

    def classify(self, workspace_id, token, body):
        return self._mutate(workspace_id,token,body,'classification',classify_content)

    def _snapshot_current(self, cur, workspace_id, state, actor, snapshot):
        direct,_ = self._rights(cur,workspace_id,state)
        channels = {c['id']:c for c in state.get('phase2',{}).get('channels',[])}
        selected = snapshot['resolvedContext']['channelIds']
        if any(c not in channels or channels[c].get('revoked') for c in selected):
            raise AlphaError('A report account is no longer available.',410)
        jobs = {j['id']:j for j in state.get('phase2',{}).get('jobs',[]) if j.get('state')=='verified'}
        from ..growth.trends.service import validate_stored_bindings
        for evidence in snapshot['nativeResults']:
            binding = evidence['publicationBinding'];job = jobs.get(binding['jobId'])
            if not job or digest([job.get('manifest'),job.get('verification')])!=binding['manifestDigest']:
                raise AlphaError('A report publication changed or was removed.',410)
            if evidence['value'] is not None and binding['connectionId'] not in direct:
                raise AlphaError('The current analytics grant no longer permits this report.',403)
            bindings = job.get('manifest',{}).get('trendLineage',[])
            if bindings:
                validate_stored_bindings(self.c.hosted.connection_factory,cur,workspace_id,actor,state,bindings,self.c.clock())
        stored = {e['observationId']:e for e in snapshot['nativeResults'] if e['observationId']}
        if stored:
            cur.execute('''SELECT id::text,value,extract(epoch from observed_at),extract(epoch from ingested_at),definition_version,connection_id,provider,provider_post_id,job_id,metric,unit,read_offset,availability
                           FROM public.pr_metric_observations WHERE workspace_id=%s AND id::text=ANY(%s) FOR SHARE''',(workspace_id,list(stored)))
            found = cur.fetchall()
            if len(found)!=len(stored):
                raise AlphaError('Report observation data was removed.',410)
            for row in found:
                e = stored[row[0]];b = e['publicationBinding']
                if (e['value'] is not None and (row[1] is None or float(row[1])!=e['value'] or row[12]!='available')) or iso(row[2])!=e['observedAt'] or iso(row[3])!=e['ingestedAt'] or row[4:12]!=(e['definitionVersion'],b['connectionId'],b['provider'],b['nativePostId'],b['jobId'],e['nativeName'],e['unit'],e['readOffset']):
                    raise AlphaError('Report observations changed; create a new reviewed version.',409)
        expected = digest({k:v for k,v in snapshot.items() if k!='payloadDigest'})
        if expected!=snapshot['payloadDigest']:
            raise AlphaError('Report snapshot integrity check failed.',409)
        if snapshot.get('trendLearning'):
            current=self.c._trend_learning_report(cur,workspace_id,actor,window=snapshot['resolvedContext']['horizon'])
            if current is None:
                raise AlphaError('Trend feedback is no longer permitted.',410)
            index={e['exposure_id']:e for e in current['exposures']}
            if any(index.get(e['exposure_id'])!=e for e in snapshot['trendLearning']['exposures']):
                raise AlphaError('A report Trend source expired, changed or was removed.',410)

    def create_snapshot(self, workspace_id, token, body):
        scope = body.get('scope')
        with self.repository.transaction(token,workspace_id) as (cur,row,actor):
            from ..permissions import require
            require(self.c.hosted.ideas._member(row),'edit')
            state = self.c.hosted.ideas._state(row)
            projection = self._project(cur,workspace_id,state,actor,scope)
            if projection['contextDigest'] != body.get('contextDigest') or projection['basisDigest'] != body.get('basisDigest'):
                raise AlphaError('Review the current scope and evidence before saving a report.',409)
            previous = next((s for s in reversed(review_state(state).get('snapshots',[])) if s['snapshotId']==body.get('snapshotId')),None)
            if body.get('snapshotId') and not previous:
                raise AlphaError('Report unavailable in this workspace.',404)
            request_id = digest([workspace_id,body.get('idempotencyKey')])
            existing_request = review_state(state).get('requests',{}).get(request_id)
            if existing_request:
                request_digest = digest(['snapshot',{k:v for k,v in body.items() if k!='workspaceRevision'}])
                if request_digest!=existing_request['digest']:
                    raise AlphaError('This request key belongs to a different report.',409)
                saved = existing_request['result']
                self._snapshot_current(cur,workspace_id,state,actor,saved)
                return {'record':saved,'workspaceRevision':row[0],'verified':True,'existing':True}
            if previous and body.get('expectedVersion')!=previous['version']:
                raise AlphaError('Report version changed. Reload it.',409)
            source_sha = self.c.values.get('POSTRIFF_SOURCE_SHA') or os.environ.get('VERCEL_GIT_COMMIT_SHA') or os.environ.get('POSTRIFF_SOURCE_SHA')
            prepared = build_review_snapshot(projection,state,body.get('humanNotes',[]),actor,source_sha,self.c.clock(),previous=previous,frequency=body.get('frequency','weekly'))
            prepared['trendProvenance'] = copy.deepcopy(projection['trendProvenance'])
            prepared['trendLearning'] = copy.deepcopy(projection['trendLearning'])
            prepared['payloadDigest'] = digest({k:v for k,v in prepared.items() if k!='payloadDigest'})
            expected_revision = body.get('workspaceRevision')
        box = {}
        def command(state,actor):
            def add(root,request_id):
                if len(root['snapshots'])>=MAX_SNAPSHOTS:
                    raise AlphaError('Report retention limit reached; no existing version was overwritten.',409)
                root['snapshots'].append(copy.deepcopy(prepared))
                return prepared
            box['record'] = _request(state,workspace_id,'snapshot',body,add)
            return state
        def recheck(cur,state,actor):
            current = self._project(cur,workspace_id,state,actor,_context_input(projection['resolvedContext']))
            if current['basisDigest']!=projection['basisDigest']:
                raise AlphaError('Evidence changed during report preparation.',409)
            self._snapshot_current(cur,workspace_id,state,actor,box['record'])
        saved = self.repository.command(workspace_id,token,expected_revision,command,requirement='edit',
                                        audit_event=lambda _:('review.snapshot',prepared['snapshotId'],{'version':prepared['version']}),after=recheck)
        return {'record':box['record'],'workspaceRevision':saved['revision'],'verified':True,'existing':False}

    def snapshot(self, workspace_id, token, snapshot_id, version, *, format_=None):
        with self.repository.transaction(token,workspace_id) as (cur,row,actor):
            state = self.c.hosted.ideas._state(row)
            snapshot = next((s for s in review_state(state).get('snapshots',[]) if s['snapshotId']==snapshot_id and s['version']==version),None)
            if snapshot is None:
                raise AlphaError('Report unavailable in this workspace.',404)
            self._snapshot_current(cur,workspace_id,state,actor,snapshot)
            result = format_snapshot(snapshot,format_) if format_ else copy.deepcopy(snapshot)
            self._snapshot_current(cur,workspace_id,state,actor,snapshot)
            return result
