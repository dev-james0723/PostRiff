"""Explicit synthetic data for the dedicated disposable review database only."""
import copy
import os
import sys
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from postriff_phase2 import insights
from postriff_phase2.coworker import performance
from postriff_phase2.growth import performance as capture
from postriff_phase2.growth.metric_schedule import schedule
from postriff_phase2.contracts import digest
from growth_phase2_fixtures import seed


def seed_review(host,wid,token,now=None):
    now=now or time.time()
    seed(host,wid,token)
    def command(state,actor):
        original=state['phase2']['jobs'][0]
        jobs=[]
        for i in range(12):
            job=copy.deepcopy(original);job['id']=str(uuid.uuid4());job['providerReference']='review-native-fixture-'+str(i)
            at=now-(36+i*8)*3600
            job['verification']={'at':at,'method':'synthetic_lookup'}
            m=job['manifest'];text=('A bounded question about practice?' if i<6 else 'A longer reflection about practice. '*24)
            m.update(variantId='review-original-'+str(i),payload={'text':text,'language':'en'},contentType={'id':'practice','formatId':'text'},payloadDigest=digest(text),timing={'timestamp':at,'timeZone':'UTC'},idempotencyKey=digest([wid,i]))
            jobs.append(job)
        state['phase2']['jobs']=jobs
        state.pop('accountDeletion',None)
        state.setdefault('coworker',{}).pop('review',None)
        return state
    saved=host.repository.command(wid,token,host.get(wid,token)['revision'],command)
    with host.connection_factory() as db,db.cursor() as cur:
        cur.execute('DELETE FROM public.pr_metric_observations WHERE workspace_id=%s',(wid,))
        cur.execute('DELETE FROM public.pr_metric_reads WHERE workspace_id=%s',(wid,))
        cur.execute('DELETE FROM public.pr_strategy_hypotheses WHERE workspace_id=%s',(wid,))
        for i,job in enumerate(saved['state']['phase2']['jobs']):
            capture.on_verified(cur,wid,job)
            schedule(cur,wid,job['manifest']['channelId'],'threads',job['providerReference'],job['id'],job['verification']['at'],'verification')
            cur.execute("UPDATE public.pr_metric_reads SET status='done' WHERE workspace_id=%s AND job_id=%s AND read_offset='24h'",(wid,job['id']))
            at=job['verification']['at']+86400
            for name,value in (('views',100+i*10 if i<6 else 25+i),('likes',0 if i==0 else i),('replies',None)):
                cur.execute('''INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at,ingested_at,read_offset,source_endpoint)
                               VALUES(%s,%s,'threads',%s,%s,%s,%s,%s,'count',%s,to_timestamp(%s),to_timestamp(%s),'24h',%s)''',
                            (wid,job['manifest']['channelId'],job['providerReference'],job['id'],name,insights.DEFINITION_VERSION,value,'available' if value is not None else 'unavailable',at,at+1,'https://graph.threads.net/v1.0/native/insights?access_token=SYNTHETIC-SECRET'))
        performance.refresh(cur,wid,saved['state'],now)
    return saved['state']['phase2']['jobs']


if __name__=='__main__':
    import json
    import psycopg
    from postriff_phase2.hosted import HostedWorkspaceService
    port,principal,wid=sys.argv[1:4]
    assert port=='55404','Only the dedicated disposable review database'
    uuid.UUID(principal);uuid.UUID(wid)
    host=HostedWorkspaceService(lambda:psycopg.connect(f'host=127.0.0.1 port={port} dbname=postgres'),lambda _:principal)
    mode=sys.argv[4] if len(sys.argv)>4 else 'seed'
    if mode=='seed':
        jobs=seed_review(host,wid,'fixture')
        print(json.dumps({'execution':'synthetic observations on real disposable PG','jobs':len(jobs)}))
    else:
        def change(state,actor):
            if mode=='revoked':state['phase2']['channels'][0]['revoked']=True
            elif mode=='empty':state['phase2']['jobs']=[];state['phase2']['channels']=[]
            elif mode=='manifest_changed':state['phase2']['jobs'][0]['manifest']['contentRevision']+=1
            else:raise ValueError(mode)
            return state
        host.repository.command(wid,'fixture',host.get(wid,'fixture')['revision'],change)
        print(json.dumps({'execution':'disposable mutation','mode':mode}))
