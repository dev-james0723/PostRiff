"""Observed, like-for-like feedback. Missing readings never become zero or a prediction."""
from __future__ import annotations

import copy
import math
import statistics

HORIZONS = ('1h', '24h', '7d')
MIN_BASELINE = 3


def cohort(post):
    return tuple(post.get(k) or 'unknown' for k in ('platform', 'connectionId', 'format', 'language', 'timeBucket'))


def available(reading):
    value = reading.get('value')
    return (reading.get('availability') == 'available' and type(value) in (int, float)
            and math.isfinite(value) and value >= 0)


def learnable(reading):
    """A numeric reading alone never qualifies as a real platform outcome."""
    return (available(reading) and reading.get('provenance') == 'official' and not reading.get('synthetic')
            and not str(reading.get('definitionVersion') or '').startswith(('fixture', 'synthetic', 'user-export')))


def official_job(job):
    return (job.get('state') == 'verified' and bool(job.get('providerReference'))
            and (job.get('verification') or {}).get('method') in ('provider_lookup', 'provider_receipt')
            and (job.get('manifest') or {}).get('execution') == 'hosted-live')


def compare(post, peers, horizon):
    """Each native metric keeps its own horizon and denominator; exclude the subject itself."""
    if horizon not in HORIZONS:
        raise ValueError('Choose 1h, 24h or 7d')
    observed = (post.get('readings') or {}).get(horizon, {})
    results = {}
    for metric, reading in observed.items():
        if not available(reading):
            results[metric] = {'value': None, 'availability': reading.get('availability', 'unavailable'), 'baselineCount': 0}
            continue
        values = []
        ids = []
        for other in peers:
            if other.get('id') == post.get('id') or cohort(other) != cohort(post):
                continue
            candidate = (other.get('readings') or {}).get(horizon, {}).get(metric, {})
            if learnable(reading) and learnable(candidate) and candidate.get('definitionVersion') == reading.get('definitionVersion'):
                values.append(candidate['value'])
                ids.append(other['id'])
        value = reading['value']
        result = {'value': value, 'availability': 'available', 'observedAt': reading.get('observedAt'),
                  'provenance':reading.get('provenance','unknown'), 'learningEligible': learnable(reading),
                  'baselineCount': len(values), 'evidenceIds': ids, 'median': None, 'multiple': None, 'percentile': None}
        if len(values) >= MIN_BASELINE:
            median = statistics.median(values)
            result.update(median=median, multiple=None if median == 0 else round(value / median, 3),
                          percentile=round(100 * (sum(v < value for v in values) + .5 * sum(v == value for v in values)) / len(values), 1))
        results[metric] = result
    return {'horizon': horizon, 'status': 'observed' if any(available(r) for r in observed.values()) else 'unavailable',
            'metrics': results, 'causal': False, 'minimumBaselinePosts': MIN_BASELINE}


def attach_readings(cur, workspace_id, posts):
    """Only scheduler readings from the official insights endpoint; backfill has unknown age."""
    from ..insights import latest_observations, canonical_metric, insights_endpoint, native_metric
    posts = copy.deepcopy(posts)
    for post in posts:
        supplied=post.get('suppliedMetrics') or {}
        horizon=supplied.get('horizon')
        if horizon in HORIZONS:
            for metric,value in supplied.get('values',{}).items():
                post.setdefault('readings',{}).setdefault(horizon,{})[metric]={
                    'value':value,'availability':'available','definitionVersion':'user-export:'+horizon,
                    'provenance':'user_supplied','observedAt':None}
    index = {(p.get('provider'), p.get('providerPostId'), p.get('connectionId')): p for p in posts}
    for horizon in HORIZONS:
        for provider, post_id, job_id, metric, version, value, unit, availability, observed, _, conn, offset, endpoint in latest_observations(cur, workspace_id, horizon, include_endpoint=True):
            post = index.get((provider, post_id, conn))
            if post is None or offset != horizon:
                continue
            if post.get('jobId') and str(post['jobId']) != str(job_id):
                continue
            provenance = 'official' if post.get('officialOrigin') is True and provider in ('threads', 'instagram') and endpoint == insights_endpoint(provider, post_id) else 'unverified'
            post.setdefault('readings', {}).setdefault(horizon, {})[canonical_metric(provider, metric)] = {
                'value': float(value) if availability == 'available' and value is not None else None,
                'availability': availability, 'definitionVersion': version, 'unit': unit, 'observedAt': float(observed), 'provenance': provenance, 'nativeName': native_metric(provider, metric), 'sourceEndpoint': endpoint}
    return posts


def on_verified(cur, workspace_id, job):
    """Freeze the check bound to the exact approved publication; this hook never schedules or publishes."""
    manifest = job.get('manifest') or {}
    prediction = manifest.get('postDoctor')
    if not prediction or not job.get('verification') or not job.get('providerReference'):
        return
    import json
    body = {**prediction, 'platform': manifest.get('platform'), 'connectionId': manifest.get('channelId'),
            'providerPostId': str(job['providerReference']), 'language': manifest.get('payload', {}).get('language'),
            'contentRevision': manifest.get('contentRevision'), 'format': (manifest.get('contentType') or {}).get('formatId', 'text'),
            'contentDigest': manifest.get('payloadDigest')}
    cur.execute('INSERT INTO public.pr_predictions(workspace_id,job_id,body,verified_at) VALUES(%s,%s,%s::jsonb,to_timestamp(%s)) ON CONFLICT DO NOTHING',
                (workspace_id, job['id'], json.dumps(body), job['verification']['at']))


def then_capture(previous, enabled):
    def hook(cur,workspace_id,job):
        if previous:previous(cur,workspace_id,job)
        if not enabled:return
        # Advisory storage failure must never roll back a verified provider publication.
        cur.execute('SAVEPOINT growth_prediction')
        try:
            on_verified(cur,workspace_id,job)
            cur.execute('RELEASE SAVEPOINT growth_prediction')
        except Exception:
            cur.execute('ROLLBACK TO SAVEPOINT growth_prediction')
            cur.execute('RELEASE SAVEPOINT growth_prediction')
    return hook
