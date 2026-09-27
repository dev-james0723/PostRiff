"""Pure Radar evidence/ranking. Scores are ordering heuristics, never viral probabilities."""
import math
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from ..contracts import digest
from ..growth.scout import terms, timestamp
from ..coworker.research_broker import injection_flags

MODES = {'quick': {'items': 12, 'judgments': 4, 'analyses': 1, 'verifications': 2, 'seconds': 90},
         'deep': {'items': 40, 'judgments': 10, 'analyses': 3, 'verifications': 5, 'seconds': 240}}
SOURCE_NAMES = {'bluesky': 'Bluesky', 'news': 'News · GDELT', 'exa': 'Exa web search', 'youtube': 'YouTube charts', 'x': 'X recent posts'}
DAY = 86400


def text(value, limit=500):
    return re.sub(r'<[^>]*>', '', ' '.join(str(value or '').split()))[:limit]


def canonical_url(value):
    try:
        u = urlsplit(value)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None, 443): return None
        if u.hostname in ('localhost',) or '.' not in u.hostname: return None
        return urlunsplit(('https', u.netloc.lower(), u.path or '/', urlencode([(k,v) for k,v in parse_qsl(u.query) if not k.lower().startswith('utm_')]), ''))
    except (ValueError, TypeError): return None


def normalize(raw, source, now):
    """Only adapter-attested public metadata is accepted; full text/media are never retained."""
    url = canonical_url(raw.get('url'))
    rights = raw.get('rights', {})
    if not url or rights.get('displayLink') is not True: return None
    published = timestamp(raw.get('publishedAt'))
    if published is not None and (published > now + 300 or published < now - 30 * DAY): return None
    excerpt = text(raw.get('excerpt')) if rights.get('displayExcerpt') else ''
    title = text(raw.get('title'), 180)
    metrics = {k: v for k, v in raw.get('metrics', {}).items() if k in ('likes','replies','reposts','views','comments')
               and type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 10**15}
    return {'id': digest([source, raw.get('nativeId') or url])[:24], 'source': source, 'url': url,
            'title': title, 'excerpt': excerpt, 'publishedAt': published, 'retrievedAt': now,
            'author': text(raw.get('author'), 120), 'nativeId': text(raw.get('nativeId'), 200),
            'rights': {k: rights.get(k) is True for k in ('displayLink','displayExcerpt','deriveFeatures','derivedMetrics')},
            'metrics': metrics, 'coverage': raw.get('coverage', 'search_lead'),
            'contentHash': digest([title.casefold(), excerpt.casefold()]),
            'injection': bool(injection_flags(title + ' ' + excerpt)), 'expiresAt': now + 30 * DAY}


def clusters(items):
    """Conservative lexical grouping; shared headlines count once, not independent corroboration."""
    unique = {}
    hashes = set()
    for item in items:
        if item['url'] in unique or item['contentHash'] in hashes: continue
        unique[item['url']] = item; hashes.add(item['contentHash'])
    groups = []
    for item in unique.values():
        if not item['rights']['deriveFeatures'] or item['injection']: continue
        tokens = terms(item['title'])
        group = next((g for g in groups if tokens and len(tokens & g['tokens']) / max(1, len(tokens | g['tokens'])) >= .4), None)
        if group is None:
            group = {'tokens': tokens, 'items': []}; groups.append(group)
        group['items'].append(item)
    return [g['items'] for g in groups]


def opportunities(items, query, genome, judgments, now, previous=()):
    out = []
    approved = [s for s in (genome or {}).get('statements', []) if s.get('grade') == 'supported'][:12]
    for group in clusters(items):
        cid = digest(sorted(i['id'] for i in group))[:24]
        evidence = group[:12]; first = evidence[0]
        words = terms(' '.join(i['title'] for i in evidence))
        matched = [s for s in approved if words & terms(str(s.get('text') or s.get('label') or s.get('value', '')))]
        relevant = len(words & terms(query)) / max(1, len(terms(query)))
        judgment = judgments.get(cid, {})
        answers = judgment.get('answers', {})
        risk = answers.get('sensitive') is not False or any(i['injection'] for i in evidence)
        known = [i['publishedAt'] for i in evidence if i['publishedAt'] is not None]
        freshness = max(0, 1 - (now - max(known)) / (7 * DAY)) if known else 0
        # Native metrics are shown separately; never combine YouTube values into derived scores.
        origins = {i['author'] if i['source'] in ('bluesky','x') else urlsplit(i['url']).hostname for i in evidence if i['author'] or i['source'] not in ('bluesky','x')}
        old = next((o for o in previous if set(o.get('evidenceIds', [])) & {i['id'] for i in evidence}), None)
        new = len({i['id'] for i in evidence} - set((old or {}).get('evidenceIds', [])))
        stage = 'new_signal' if not old else 'new_coverage' if new else 'unchanged'
        if known and max(known) < now - 7*DAY: stage = 'cooling'
        score = round(100/(1+math.exp(-(1.5*relevant + .4*freshness + min(.6,len(origins)*.15) + min(1,len(matched)*.3) - 1.5*int(risk) - 1))))
        judged = judgment.get('status') == 'ok' and answers.get('useful') is True and answers.get('relevant') is True
        confidence = 'medium' if judged and len(origins) >= 2 and len(known) == len(evidence) else 'low'
        reasons = ['Source coverage is incomplete; this is not measured audience acceleration.']
        if not judged: reasons.append('AI has not established usefulness and relevance.')
        if risk: reasons.append('Sensitivity is unresolved; review before developing this topic.')
        if not matched: reasons.append('No matching supported Genome lesson; fit is based on your search topic.')
        out.append({'id':cid, 'title':first['title'], 'evidenceIds':[i['id'] for i in evidence],
                    'evidence':evidence, 'score':score, 'scoreVersion':'radar-ordering-v1', 'confidence':confidence,
                    'confidenceReasons':reasons, 'stage':stage, 'sourceCount':len({urlsplit(i['url']).hostname for i in evidence}),
                    'independentOrigins':len(origins), 'independence':'not_verified', 'newSignals':new,
                    'forYou':bool(matched), 'genomeReasons':[{'id':s.get('id'), 'text':text(s.get('text') or s.get('label') or s.get('value'),240)} for s in matched],
                    'whyNow':f'{len(evidence)} distinct references; {new} new since the comparable scan.' if old else f'{len(evidence)} distinct references in this scan.',
                    'judgment':judgment, 'eligible':judged and not risk, 'needsFactCheck':True,
                    'angle':'What does this development change for your audience? Add a first-hand example you can verify.',
                    'expiresAt':min(i['expiresAt'] for i in evidence)})
    return sorted(out, key=lambda o:(-o['score'],o['id']))[:12]


def usage(events):
    known = sum(e.cost_usd_micro() or 0 for e in events)
    unknown = sum(e.cost_usd_micro() is None for e in events)
    return {'knownUsdMicro':known, 'unknownAttempts':unknown, 'actualUsdMicro':None if unknown else known}


def release_gate(data):
    """Local evaluator; synthetic examples cannot prove precision, adoption or economics."""
    rows = data.get('scans', [])
    real = data.get('execution') == 'real' and bool(rows)
    ids=[r.get('id') for r in rows]
    valid = real and all(ids) and len(ids)==len(set(ids)) and all(len(r.get('topFive',[]))==5 and all(type(v) is bool for v in r['topFive']) for r in rows)
    precision = sum(sum(r['topFive'])/5 for r in rows)/len(rows) if valid else None
    people=data.get('weeklyUsers',[])
    adoption=sum(p.get('createdDraft') is True for p in people)/len(people) if people and all(p.get('id') for p in people) and len({p['id'] for p in people})==len(people) else None
    economics=bool(rows) and all(type(r.get('actualUsdMicro')) is int and type(r.get('quotedUsdMicro')) is int and 0<=r['actualUsdMicro']<=r['quotedUsdMicro'] for r in rows)
    passed=valid and precision>=.6 and adoption is not None and adoption>=.3 and economics
    return {'status':'PASS' if passed else 'NOT_ESTABLISHED', 'precisionAt5':precision,'weeklyDraftAdoption':adoption,'withinQuote':economics if real else None}
