"""Native outcomes beside frozen writing advice. Associations, never causal explanations."""
from . import performance
from ..contracts import digest

# One writing dimension can relate to several native metrics. Do not add those metrics.
METRICS = {'shareability':('shares','reposts'), 'conversation':('replies','comments'),
           'audience':('likes','saves'), 'specificity':('saves','shares'),
           'hook':('views',), 'clarity':('saves',), 'novelty':('shares','reposts')}


def binding(job):
    return {'id':job['id'],'digest':digest([job.get('manifest'),job.get('providerReference'),job.get('verification')])}


def bindings_current(state, bindings):
    jobs={j['id']:j for j in state.get('phase2',{}).get('jobs',[]) if j.get('state')=='verified' and j.get('verification')}
    revoked={c['id'] for c in state.get('phase2',{}).get('channels',[]) if c.get('revoked')}
    return all(b['id'] in jobs and binding(jobs[b['id']])==b and
               jobs[b['id']].get('manifest',{}).get('channelId') not in revoked for b in bindings)


def comparison(prediction, reading):
    rows=[]
    for dimension in (prediction or {}).get('levels',[]):
        for metric in METRICS.get(dimension['id'],()):
            outcome=reading.get('metrics',{}).get(metric)
            if not outcome or outcome.get('percentile') is None or dimension.get('level') is None:
                continue
            high=outcome['percentile']>=75
            low=outcome['percentile']<=25
            expected=dimension['level']>=2
            status=('aligned' if expected else 'underestimated') if high else ('overestimated' if expected else 'aligned') if low else 'mixed'
            rows.append({'dimension':dimension['id'],'label':dimension['label'],'levelName':dimension['levelName'],
                         'metric':metric,'outcome':outcome,'status':status,'expectedHigh':expected})
    return rows


def build(job, prediction, posts, predictions, horizon):
    post=next(p for p in posts if p['id']==job['id'])
    reading=performance.compare(post,posts,horizon)
    comparisons=comparison(prediction,reading)
    lessons=[]
    for row in comparisons:
        supporting=[];counter=[]
        for peer in posts:
            if performance.cohort(peer)!=performance.cohort(post):continue
            other=comparison(predictions.get(peer['id']),performance.compare(peer,posts,horizon))
            found=next((r for r in other if r['dimension']==row['dimension'] and r['metric']==row['metric']),None)
            if not found:continue
            if found['expectedHigh']!=row['expectedHigh']:continue
            if predictions.get(peer['id'],{}).get('evaluation',{}).get('rubricDigest')!=(prediction or {}).get('evaluation',{}).get('rubricDigest'):continue
            if predictions.get(peer['id'],{}).get('evaluation',{}).get('model')!=(prediction or {}).get('evaluation',{}).get('model'):continue
            # Same direction/expectation and exact native metric definition; never mix causes or populations.
            native=peer.get('readings',{}).get(horizon,{}).get(row['metric'],{})
            target=post.get('readings',{}).get(horizon,{}).get(row['metric'],{})
            if native.get('definitionVersion')!=target.get('definitionVersion'):continue
            if found['status']==row['status']:supporting.append(peer['id'])
            elif found['status']!='mixed':counter.append(peer['id'])
        if row['status']=='mixed':continue
        grade='conflicting' if counter else 'supported' if len(supporting)>=3 else 'limited'
        label=f"{row['label']}: {row['status']} expectations"
        lessons.append({'id':digest([row['dimension'],row['metric'],horizon,row['status']])[:16],
                        'label':label,'text':f"{row['label']} advice {row['status']} the observed {horizon} {row['metric']} outcomes in this account cohort. Treat this as an association, not a cause.",
                        'kind':'performance','grade':grade,'evidenceIds':supporting,'counterEvidenceIds':counter,
                        'metric':row['metric'],'provenance':['official'],'cohort':{k:post.get(k) for k in ('platform','connectionId','format','language','timeBucket')}})
    return {'jobId':job['id'],'horizon':horizon,'title':job.get('manifest',{}).get('payload',{}).get('text','')[:150],
            'platform':post['platform'],'prediction':prediction,'reading':reading,'comparisons':comparisons,
            'lessons':lessons[:6],'status':'observed','causal':False,
            'notice':'Writing advice and native outcomes measure different things. Differences are observations; explanations remain hypotheses.'}
