"""A late native counter is retained only as a current snapshot, never a historic horizon."""
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import psycopg
from postriff_phase2.growth import metric_schedule as M, performance

def connection():return psycopg.connect(os.environ['POSTRIFF_TEST_DSN'])
clock=[time.time()]
calls=[]
def token(*args):
    calls.append('oauth')
    return {'provider':'threads','accessToken':'fixture','scopes':list(M.NATIVE_ANALYTICS_SCOPES['threads'])}
oauth=SimpleNamespace(providers={'threads':SimpleNamespace(platform='Threads',production_reviewed=True)},token_for_worker=token)
late=[False]
def transport(*args,**kwargs):
    calls.append('insights')
    if late[0]:clock[0]+=601
    return {'status':200,'body':{'data':[{'name':'views','total_value':{'value':12}}]}}
with connection() as db:
    wid=str(db.execute('SELECT workspace_id FROM public.pr_memberships LIMIT 1').fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}' WHERE id=%s",(wid,))
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,'horizon-fixture','analytics','Direct')",(wid,))
    db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,'horizon-fixture','threads','fixture','sealed','k',%s)",(wid,list(M.NATIVE_ANALYTICS_SCOPES['threads'])))
s=M.MetricScheduler(connection,oauth,transport=transport,workspace_allowlist=[wid],clock=lambda:clock[0])
def add(ref,anchor):
    with connection() as db,db.cursor() as cur:
        M.schedule(cur,wid,'horizon-fixture','threads',ref,None,anchor,'verification',offsets=(('1h',3600),))
    return s.claim(1)[0]
row=add('missed',clock[0]-3600-601)
outcome=s.read(row,{})
assert outcome['state']=='unavailable' and outcome['failure']=='horizon_missed' and not calls
assert s.complete(row,outcome)
with connection() as db:
    assert db.execute("SELECT status,failure_class FROM public.pr_metric_reads WHERE provider_post_id='missed'").fetchone()==('unavailable','horizon_missed')
    assert db.execute('SELECT count(*) FROM public.pr_metric_observations').fetchone()[0]==0
row=add('late',clock[0]-3601)
late[0]=True
outcome=s.read(row,{})
assert outcome['state']=='unavailable' and outcome['providerRead']
assert s.complete(row,outcome)
with connection() as db,db.cursor() as cur:
    cur.execute("SELECT count(*),count(read_offset) FROM public.pr_metric_observations WHERE provider_post_id='late'")
    count,tagged=cur.fetchone()
    assert count>0 and tagged==0, 'late counter must be retained without a fabricated horizon'
    posts=performance.attach_readings(cur,wid,[{'provider':'threads','providerPostId':'late','connectionId':'horizon-fixture'}])
    assert not posts[0].get('readings')
    # An old/malformed observation tagged 1h is still unqualified at the consumer boundary.
    cur.execute("UPDATE public.pr_metric_observations SET read_offset='1h' WHERE provider_post_id='late'")
    assert not performance.attach_readings(cur,wid,[{'provider':'threads','providerPostId':'late','connectionId':'horizon-fixture'}])[0].get('readings')
print(json.dumps({'execution':'disposable PostgreSQL; synthetic OAuth/native counters','checks':['missed window without dispatch','durable unavailable','late response retained without horizon','unqualified legacy counter excluded']}))
