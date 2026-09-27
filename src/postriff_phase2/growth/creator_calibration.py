"""Creator outcome calibration, isolated from human writing-quality calibration.

Chronological holdout, exact account/cohort/metric/rubric/model, at least fifty publications.
Weights and ordinal thresholds are proposed, versioned and explicitly approved. No viral score.
"""
import hashlib
import math
import statistics
from collections import defaultdict
from . import calibration, performance
from .postmortem import METRICS
from ..contracts import digest


def finite(v):
    return type(v) in (int,float) and math.isfinite(v)


def datasets(posts, predictions):
    groups=defaultdict(list)
    for post in posts:
        pred=predictions.get(post['id'],{})
        scores=pred.get('scores',{})
        model=pred.get('evaluation',{}).get('model')
        rubric=pred.get('evaluation',{}).get('rubricDigest')
        if not scores or not model or not rubric:continue
        for metric,value in post.get('readings',{}).get('24h',{}).items():
            if not performance.available(value) or value.get('provenance')!='official':continue
            key=(*performance.cohort(post),metric,value.get('definitionVersion'),model,rubric)
            groups[key].append({'id':post['id'],'at':pred.get('verifiedAt',0),'scores':scores,'value':value['value']})
    return groups


def propose(posts, predictions):
    groups=datasets(posts,predictions)
    candidates=[]
    for key,rows in sorted(groups.items()):
        rows=sorted(rows,key=lambda r:(r['at'],r['id']))
        if len(rows)<50:continue
        split=int(len(rows)*.7);train=rows[:split];test=rows[split:]
        dims={d for r in rows for d in r['scores'] if key[5] in METRICS.get(d,())}
        fitted=[]
        values=sorted(r['value'] for r in train)
        # Training-only quartiles; holdout outcomes never set thresholds or weights.
        quartiles=[values[min(len(values)-1,int(len(values)*q))] for q in (.25,.5,.75)]
        for dim in sorted(dims):
            a=[r for r in train if finite(r['scores'].get(dim))]
            b=[r for r in test if finite(r['scores'].get(dim))]
            if len(a)<35 or len(b)<15:continue
            rho=calibration.spearman([r['scores'][dim] for r in b],[r['value'] for r in b])
            train_rho=calibration.spearman([r['scores'][dim] for r in a],[r['value'] for r in a])
            labels=[sum(r['value']>=q for q in quartiles) for r in a]
            fit=calibration.fit_thresholds([r['scores'][dim] for r in a],labels,4)
            thresholds=fit['thresholds']
            if rho is None or rho<.2 or train_rho is None or train_rho<=0 or len(set(thresholds))!=3:continue
            fitted.append({'id':dim,'thresholds':thresholds,'holdoutSpearman':round(rho,4),
                           'trainingWeight':max(.01,train_rho),'trainCount':len(a),'holdoutCount':len(b)})
        total=sum(d['trainingWeight'] for d in fitted)
        for d in fitted:d['weight']=round(d.pop('trainingWeight')/total,6)
        if fitted:candidates.append({'cohort':list(key[:5]),'metric':key[5],'definitionVersion':key[6],
                                     'model':key[7],'rubricDigest':key[8],'horizon':'24h','postCount':len(rows),
                                     'evidenceIds':[r['id'] for r in rows],'dimensions':fitted,'causal':False})
    return {'candidates':candidates,'minimumPosts':50,'status':'proposed' if candidates else 'insufficient_evidence',
            'largestCohort':max(map(len,groups.values()),default=0),
            'basisDigest':digest([(list(k),v) for k,v in sorted(groups.items())]),
            'notice':'Outcome calibration uses a chronological holdout. It does not establish writing quality or causal lift.'}


def apply(profile, target, model, rubric, scores):
    out=[]
    for item in profile.get('candidates',[]):
        if tuple(item['cohort'])!=performance.cohort(target) or item['model']!=model or item['rubricDigest']!=rubric:continue
        for dimension in item['dimensions']:
            value=scores.get(dimension['id'])
            if not finite(value):continue
            out.append({'dimension':dimension['id'],'metric':item['metric'],
                        'level':['weak','medium','strong','very strong'][calibration.to_level(value,dimension['thresholds'])],
                        'weight':dimension['weight'],
                        'postCount':item['postCount'],'basis':'Your approved outcome calibration; association only.'})
    return sorted(out,key=lambda d:-d['weight'])


def assignment(experiment_id, account_id):
    """Stable account-level assignment, for an explicitly enrolled experiment only."""
    return 'shown' if hashlib.sha256((experiment_id+':'+account_id).encode()).digest()[0]%2 else 'withheld'


def experiment_report(accounts, elapsed_days, synthetic=False):
    """One mean percentile per account. Repeated posts do not pretend to be independent accounts."""
    arms={'shown':[],'withheld':[]};seen=set()
    for row in accounts:
        if row.get('accountId') in seen:raise ValueError('One row per randomized account')
        seen.add(row.get('accountId'))
        values=row.get('percentiles',[])
        if row.get('arm') not in arms or not values or any(not finite(v) or not 0<=v<=100 for v in values):raise ValueError('Invalid experiment evidence')
        arms[row['arm']].append(statistics.mean(values))
    ready=elapsed_days>=28 and all(len(a)>=2 for a in arms.values())
    lift=statistics.mean(arms['shown'])-statistics.mean(arms['withheld']) if ready else None
    return {'status':'fixture' if synthetic else 'observed' if ready else 'insufficient_evidence',
            'elapsedDays':elapsed_days,'accounts':{k:len(v) for k,v in arms.items()},'percentileDifference':lift,
            'targetMet':not synthetic and ready and lift>=5,'causalClaim':False,
            'notice':'A point estimate is not proof of causal improvement. Review enrollment, missingness and uncertainty.'}
