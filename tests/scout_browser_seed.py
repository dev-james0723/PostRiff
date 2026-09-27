"""Seed only the disposable Scout browser harness on its dedicated loopback port."""
import json,sys,time
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parent)]
import psycopg
from postriff_phase2.growth import scout
from postriff_phase2.coworker import listening
from test_growth_scout import item,Judge,WL
wid=sys.argv[1]
with psycopg.connect('host=127.0.0.1 port=55447 dbname=postgres') as db:
    state=db.execute('SELECT state FROM pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]
    if not any(c.get('providerAccountId','').startswith('dev-') or c.get('platform')=='LinkedIn' for c in state.get('phase2',{}).get('channels',[])):
        raise ValueError('Expected synthetic account')
    now=time.time();wl={**WL,'primaryObjective':'shareability'}
    state['brandHub']={'audience':'local bakers'}
    listening.root(state)['watchlists']=[wl]
    items=[item(1),item(2)]
    for i in items:i['provenance']['publishedAt']=now-3600
    prepared=scout.prepare(state,wl,items,wid,now,Judge());scout.store(state,wl,prepared,now)
    for o in listening.root(state)['opportunities']:o['status']='open'
    if '--outcomes' in sys.argv:
        from postriff_phase2 import insights
        op=listening.root(state)['opportunities'][0];op['status']='acted'
        plan=next(p for p in op['executionPlans'] if p['platform']=='Threads')
        jobs=[]
        for n in range(7):
            vid=f'browser-v{n}';jid=f'browser-j{n}'
            state['variants'].append({'id':vid,'scoutLineage':[{'executionPlan':plan}]})
            jobs.append({'id':jid,'state':'verified','providerReference':f'browser-p{n}','approvedAt':now-100000+n*1000,'manifest':{'platform':'Threads','channelId':plan['account'],'variantId':vid,'payload':{'language':'en'},'contentType':{'id':'text'}}})
            with db.cursor() as cur:
                for offset in ('1h','24h','7d'):
                    insights.record_observations(cur,wid,plan['account'],'threads',f'browser-p{n}',jid,{'views':1000,'shares':30 if n==6 else 10},'synthetic-browser',now,read_offset=offset)
        state['phase2']['jobs']=jobs
        db.execute("""INSERT INTO pr_strategy_hypotheses(workspace_id,platform,dimension,cohort,statement,metric,arm_a,arm_b,sample_a,sample_b,effect,evidence_ids,counter_evidence_ids,confidence,expires_at)
                      VALUES(%s,'Threads','scout_browser',%s::jsonb,'Question openings may support shares for this account. Observed association only.','shares/views','question','statement',5,5,0.5,'[]','[]','low',now()+interval '30 days') ON CONFLICT DO NOTHING""",
                   (wid,json.dumps({'account':plan['account'],'provider':'threads','objective':'shareability','language':'en','format':'text','window':'24h','definition':'v1'})))
        # Each browser exercises acceptance independently in this disposable fixture.
        db.execute("UPDATE pr_strategy_hypotheses SET status='candidate',experiment=NULL WHERE workspace_id=%s AND dimension='scout_browser'", (wid,))
    db.execute('UPDATE pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),wid))
print(json.dumps({'execution':'synthetic-local','workspaceId':wid}))
