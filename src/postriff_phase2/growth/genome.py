"""Creator Genome extends the existing retained voice corpus and Brand Brain, never another identity."""
from __future__ import annotations

import csv
import io
import math
import statistics
from collections import defaultdict

from postriff_alpha.domain import AlphaError
from . import performance

MAX_POSTS = 20
LABELS = ('topic','hook','tone','format','purpose','cta','specificity','proof')
METRIC_PRIORITY = ('shares','reposts','saves','replies','comments','likes','views')


def parse_upload(data):
    """A bounded explicit export. A caller cannot label uploaded values platform-verified."""
    if not isinstance(data,str) or len(data.encode('utf-8')) > 100_000:
        raise AlphaError('Upload a UTF-8 CSV of at most 100 KB.',413)
    try:
        rows = list(csv.DictReader(io.StringIO(data.lstrip('\ufeff'))))
    except csv.Error as error:
        raise AlphaError('The history CSV is invalid.') from error
    if not 1 <= len(rows) <= MAX_POSTS:
        raise AlphaError('Choose 1–20 of your own posts for this analysis.')
    out = []
    for row in rows:
        if not isinstance(row.get('text'),str) or not 1 <= len(row['text'].strip()) <= 8000:
            raise AlphaError('Every history row needs text (up to 8,000 characters).')
        if row.get('platform') not in ('Threads','Instagram','LinkedIn','X','Bluesky','Mastodon'):
            raise AlphaError('Every history row needs a supported platform.')
        metrics = {}
        for key in METRIC_PRIORITY:
            raw = row.get(key)
            if raw in (None,''):
                continue
            try:
                number = float(raw)
            except (ValueError,TypeError):
                raise AlphaError('Metric values must be nonnegative finite numbers.') from None
            if not math.isfinite(number) or number < 0 or number > 10**12:
                raise AlphaError('Metric values must be nonnegative finite numbers.')
            metrics[key] = number
        horizon=row.get('horizon') or None
        if horizon is not None and horizon not in performance.HORIZONS:
            raise AlphaError('A supplied metric horizon must be 1h, 24h or 7d.')
        out.append({'text':row['text'], 'platform':row['platform'], 'language':row.get('language') or 'unknown',
                    'externalId':row.get('post_id') or '', 'publishedAt':row.get('published_at') or '',
                    'title':row.get('title') or 'Owned history post', 'metrics':metrics,
                    'format':row.get('format') or 'text', 'timeBucket':row.get('time_bucket') or 'unknown','horizon':horizon})
    return out


def labels(judgment):
    out = {}
    for key, answer in judgment.answers.items():
        if key not in LABELS or answer.abstained or answer.value == 'unsure':
            continue
        if key in ('specificity','proof'):
            probability = judgment.probability(key)
            if probability is not None:
                out[key] = 'present' if probability >= .5 else 'limited'
        else:
            out[key] = str(answer.value)
    return out


def relative(post, posts):
    """One observed native metric. Prefer downstream behavior and name the actual metric."""
    feedback = performance.compare(post, posts, '24h')
    return next(((key,feedback['metrics'][key]) for key in METRIC_PRIORITY
                 if (feedback['metrics'].get(key) or {}).get('percentile') is not None), None)


def proposal(posts):
    groups = defaultdict(list)
    measured = 0
    for post in posts:
        reading = relative(post,posts)
        measured += int(reading is not None)
        for key,value in (post.get('labels') or {}).items():
            if key in LABELS and value != 'unsure':
                # Evidence never pools different accounts/platforms/languages/formats/time cohorts.
                metric=reading[0] if reading else 'writing'
                native=post.get('readings',{}).get('24h',{}).get(metric,{})
                version=native.get('definitionVersion','')
                provenance=native.get('provenance','official') if reading else ''
                groups[(*performance.cohort(post),metric,version,provenance,key,value)].append((post,reading))
    statements = []
    for group, members in sorted(groups.items()):
        platform,connection,format_,language,bucket,metric,version,provenance,key,value = group
        winners = [(p,r) for p,r in members if r and r[1]['percentile'] >= 75]
        losers = [(p,r) for p,r in members if r and r[1]['percentile'] <= 25]
        evidence = [p['id'] for p,r in winners] or [p['id'] for p,r in members]
        counter = [p['id'] for p,r in losers]
        performance_claim = bool(winners)
        grade = 'conflicting' if winners and losers else 'supported' if len(evidence)>=3 else 'limited'
        text = (f'{value.replace("_"," ")} {key} appears among your stronger observed posts.' if performance_claim
                else f'{value.replace("_"," ")} {key} appears in your writing samples.')
        statements.append({'id':str(len(statements)), 'label':f'{key}: {value.replace("_"," ")}', 'text':text,
                           'kind':'performance' if performance_claim else 'writing', 'grade':grade,
                           'evidenceIds':evidence, 'counterEvidenceIds':counter,
                           'metric':metric if winners else None,
                           'definitionVersion':version if winners else None,
                           'provenance':sorted({p.get('readings',{}).get('24h',{}).get(metric,{}).get('provenance','official') for p,r in winners}) if winners else [],
                           'cohort':{'platform':platform,'connectionId':connection,'format':format_,'language':language,'timeBucket':bucket}})
    return {'statements':statements[:60], 'postCount':len(posts), 'measuredPosts':measured,
            'suppliedMetricsPosts':sum(bool(p.get('suppliedMetrics')) for p in posts),
            'evidenceBindings':[{'id':p['sourceId'],'revision':p['sourceRevision'],'grantsDigest':p['grantsDigest']} for p in posts],
            'status':'proposed','causal':False}


def fit_winners(draft_scores, posts, target):
    eligible = [(p,relative(p,posts)) for p in posts if performance.cohort(p) == performance.cohort(target)]
    eligible = [(p,r) for p,r in eligible if r]
    # Match one actual metric and provenance instead of mixing likes with shares or uploaded counts.
    metric_groups=defaultdict(list)
    for p,r in eligible:
        version=p['readings']['24h'][r[0]].get('definitionVersion')
        metric_groups[(r[0],version)].append((p,r))
    eligible=max(metric_groups.values(),key=len,default=[])
    if len(eligible)<10:
        return None
    winners = [p for p,r in eligible if r[1]['percentile']>=75]
    if not winners:
        return None
    pairs = []
    for key,value in draft_scores.items():
        scores = [p.get('scores',{}).get(key) for p in winners]
        scores = [v for v in scores if type(v) in (int,float) and math.isfinite(v)]
        if type(value) in (int,float) and scores:
            pairs.append(abs(value-statistics.mean(scores)))
    if not pairs:
        return None
    proximity = 1-statistics.mean(pairs)
    level = sum(proximity>=threshold for threshold in (.35,.55,.75))
    return {'level':level,'measuredPosts':len(eligible),'evidenceIds':[p['id'] for p in winners],
            'basis':'24h','metric':eligible[0][1][0],
            'provenance':eligible[0][0]['readings']['24h'][eligible[0][1][0]].get('provenance','official'),
            'description':'Similarity to your observed winners; association, not a prediction.'}
