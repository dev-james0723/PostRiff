"""Real Radar state machine on disposable PostgreSQL; no external providers."""
from local_pg_target import selected_target
import sys,json,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.growth.service import GrowthService,ROUTES
from postriff_phase2.growth.closed_loop import SUMMARY_ROUTE
from radar_fixtures import Models,Writer,ENV,Sources
ONE='00000000-0000-0000-0000-000000000001';TWO='00000000-0000-0000-0000-000000000002'
def connection():return psycopg.connect(selected_target().dsn())
def verify(t):
    if t in ('one','two'):return ONE if t=='one' else TWO
    raise AlphaError('Verified session required.',401)
def refused(status,fn):
    try:fn()
    except AlphaError as e:assert e.status==status,(status,e.status,str(e));return
    raise AssertionError('Expected refusal '+str(status))
with connection() as db:
    wid=str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s',(ONE,)).fetchone()[0])
    foreign=str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s',(TWO,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET status='active',role='owner'")
    db.execute("UPDATE public.pr_workspaces SET state='{}' WHERE id=%s",(wid,))
clock=[time.time()];host=HostedWorkspaceService(connection,verify,clock=lambda:clock[0],ideas_runtime=Writer());host.bootstrap('one','studio')
models=Models();g=host.growth=GrowthService(host,env=ENV,router_factory=models.router,clock=lambda:clock[0]);r=g.radar;r.sources=Sources(lambda:clock[0]);checks=[]
def saved():return host.get(wid,'one')
def action(name,payload):return g.action(wid,'one',saved()['revision'],name,payload)
def consent():
    action('growth_consent',{'confirmed':True,'routes':[*ROUTES,SUMMARY_ROUTE]})
    action('radar_consent',{'confirmed':True,'sources':['news','bluesky','youtube'],'ai':True})
def quote(**kw):return r.quote(wid,'one',{'mode':'quick','query':'piano practice','sources':['bluesky','news','youtube'],'useAi':True,'requestKey':str(uuid.uuid4()),**kw})
def run(q):
    result=r.start(wid,'one',q['id'],{'confirmed':True})
    for _ in range(40):
        if result['status']!='running':return result
        result=r.advance(wid,'one',q['id']);clock[0]+=result.get('retryAfter',0)
    raise AssertionError('unbounded scan')
def reset_day():clock[0]+=86400
refused(404,lambda:GrowthService(host,env={}).radar.catalog(wid,'one'))
refused(403,lambda:r.catalog(foreign,'one'));refused(403,lambda:r.catalog(wid,'prt_invalid'))
refused(403,lambda:quote())
consent();q=quote();refused(400,lambda:r.start(wid,'one',q['id'],{}))
n=len(r.sources.calls);assert n==0
x=run(q);assert x['status']=='completed',x
assert x['usefulOpportunities']>=3,x
assert len(x['nativeReferences'])==6 and all(e['source']=='youtube' for e in x['nativeReferences'])
assert all(e['source']!='youtube' for o in x['opportunities'] for e in o['evidence'])
n=len(r.sources.calls);assert run(q)==x and len(r.sources.calls)==n
key=str(uuid.uuid4());a=quote(requestKey=key);assert quote(requestKey=key)['id']==a['id'];refused(409,lambda:quote(requestKey=key,query='different'))
checks.append('consent, workspace/session isolation, explicit quote confirmation, exact replay, capped batches and YouTube separation')
jobcount=len(saved()['state']['phase2']['jobs']);op=x['opportunities'][0]
refused(400,lambda:action('radar_save_idea',{'scanId':x['id'],'opportunityId':op['id']}))
b={'scanId':x['id'],'opportunityId':op['id'],'confirmed':True};s=action('radar_save_idea',b);again=action('radar_save_idea',b)
assert s['sourceId']==again['sourceId'];source=next(s1 for s1 in saved()['state']['sources'] if s1['id']==s['sourceId'])
assert source['needsFactCheck'] and source['radarEvidence']['links'];assert len(saved()['state']['phase2']['jobs'])==jobcount
assert r.list(wid,'one')['scans'][-1]['opportunities'][0]['sourceId']==s['sourceId']
for other in x['opportunities'][1:3]:action('radar_save_idea',{'scanId':x['id'],'opportunityId':other['id'],'confirmed':True})
assert len([i for i in saved()['state']['sources'] if i.get('radarEvidence')])==3
checks.append('multiple reviewed ideas, persistence, replay deduplication and no publication')
with connection() as db:db.execute("UPDATE public.pr_memberships SET role='editor' WHERE workspace_id=%s AND user_id=%s",(wid,ONE))
assert 'actualUsdMicro' not in r.response(wid,'one',x)['usage'] and 'spentCeiling' not in r.response(wid,'one',x)
refused(403,lambda:action('radar_consent',{'confirmed':True,'sources':[],'ai':False}))
with connection() as db:db.execute("UPDATE public.pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s",(wid,ONE))
q=quote();r.start(wid,'one',q['id'],{'confirmed':True});r.sources.before=lambda:action('radar_consent',{'confirmed':True,'sources':[],'ai':False})
result=r.advance(wid,'one',q['id']);assert result['status']=='cancelled' and not result['opportunities']
with connection() as db:
    bodies=db.execute('SELECT body FROM public.pr_radar_runs WHERE workspace_id=%s',(wid,)).fetchall()
    assert all(not b[0]['items'] and not b[0].get('genome') and not b[0].get('analyses') for b in bodies)
consent();q=quote();r.start(wid,'one',q['id'],{'confirmed':True})
with connection() as db:db.execute("UPDATE public.pr_radar_runs SET lease_token='abandoned',lease_until=to_timestamp(%s) WHERE id=%s",(clock[0]-1,q['id']))
n=len(r.sources.calls);assert r.advance(wid,'one',q['id'])['status']=='unknown';assert len(r.sources.calls)==n
refused(409,lambda:r.start(wid,'one',quote()['id'],{'confirmed':True}));action('radar_stop',{'scanId':q['id']})
q=quote();r.start(wid,'one',q['id'],{'confirmed':True});r.sources.before=lambda:clock.__setitem__(0,clock[0]+76)
assert r.advance(wid,'one',q['id'])['status']=='unknown';action('radar_stop',{'scanId':q['id']})
checks.append('owner-only grants, in-flight revocation purge, abandoned and expired lease fencing, unknown replay prevention')
reset_day();r.sources.failure=True;x=run(quote());assert x['status']=='partial' and x['usefulOpportunities']==0 and x['refundReason'];r.sources.failure=False
x=run(quote(useAi=False));assert x['status']=='partial' and all(not o['eligible'] for o in x['opportunities'])
expired=quote();clock[0]+=601;refused(409,lambda:r.start(wid,'one',expired['id'],{'confirmed':True}))
checks.append('partial provider failure, zero useful results, non-AI uncertainty and expired quote')
reset_day();normal_verify=r.sources.verify;r.sources.verify=lambda item:{'status':'removed','costUsdMicro':0}
x=run(quote(sources=['bluesky']));assert sum(s['id'].startswith('judge:') for s in x['steps'])<=4
assert sum(s['id'].startswith('verify:') for s in x['steps'])<=2
r.sources.verify=normal_verify
checks.append('native deletion does not expand the Quick judgment or verification cap')
# Paid-only, opt-in scheduled scans; local day dedupe and quiet hours.
reset_day();clock[0]=int(clock[0]//86400)*86400+12*3600
refused(403,lambda:action('radar_watch',{'enabled':True,'confirmed':True,'query':'piano practice','timezone':'UTC','maximumUsdMicro':1000000}))
from postriff_phase2.credit_meter import POLICY_VERSION
with connection() as db:
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('radar-test','studio',999,'Synthetic Radar',100,'active',%s::jsonb)",(json.dumps({'creditPolicy':POLICY_VERSION,'writingBatches':10,'members':5,'connectedAccounts':3,'storageMb':200}),))
    db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'radar-test','active',to_timestamp(%s)) ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='radar-test',status='active',current_period_end=excluded.current_period_end",(wid,clock[0]+864000))
action('radar_watch',{'enabled':True,'confirmed':True,'query':'piano practice','timezone':'UTC','maximumUsdMicro':1000000})
for _ in range(20):r.tick();clock[0]+=6
with connection() as db:assert db.execute('SELECT checked_at FROM public.pr_radar_watch_schedule WHERE workspace_id=%s',(wid,)).fetchone()
watch=r.list(wid,'one')['scans'][0];assert watch['status']=='completed' and watch['notification'],watch
n=len(r.sources.calls);r.tick();assert len(r.sources.calls)==n
clock[0]=int(clock[0]//86400)*86400+23*3600;r.tick();assert len(r.sources.calls)==n
clock[0]+=13*3600
with connection() as db:db.execute("UPDATE pr_subscriptions SET status='cancelled' WHERE workspace_id=%s",(wid,))
r.tick();assert len(r.sources.calls)==n
action('radar_watch',{'enabled':False})
checks.append('paid-plan monitoring, owner opt-in, daily dedupe, in-app digest only, quiet hours and subscription revocation')
# Existing wallet terms only; deterministic funding is not a payment or plan activation.
reset_day();g.env={**g.env,'POSTRIFF_RADAR_CREDIT_BILLING':'1'}
with connection() as db:
    db.execute((ROOT/'migrations/postriff/020_credit_quotes.sql').read_text())
    host.ledger.ensure_entitlement(db.cursor(),wid,None)
    db.execute("UPDATE pr_entitlements SET plan_terms_id='radar-test' WHERE workspace_id=%s",(wid,))
    r.book.grant(db.cursor(),wid,ONE,'radar-funding',2000000,None)
q=quote(useAi=False);r.start(wid,'one',q['id'],{'confirmed':True})
with connection() as db:assert r.book.view(db.cursor(),wid)['heldMilliCredits']>0
x=run(q);assert x['chargedCredits']==0,x
with connection() as db:assert r.book.view(db.cursor(),wid)['heldMilliCredits']==0
q=quote();x=run(q)
# Fixture writer has no Gateway invoice; unknown costs stay held until reconciliation.
assert x['usage']['actualUsdMicro'] is None and x['chargedCredits'] is None,x
with connection() as db:assert r.book.view(db.cursor(),wid)['heldMilliCredits']>0
action('radar_forget',{'scanId':x['id']})
with connection() as db:assert r.book.view(db.cursor(),wid)['heldMilliCredits']==0
# An unexpected upstream invoice never increases the customer's confirmed ceiling.
reset_day();original_chat=models.chat
models.chat=lambda *a,**k:(original_chat(*a,**k)[0],{'gatewayCost':10.0})
x=run(quote());assert x['usage']['actualUsdMicro']>x['maximumUsdMicro'] and x['chargedCredits']==x['maximumCredits'],x
models.chat=original_chat
checks.append('known actual overage absorbed at the confirmed customer quote')
g.env={**g.env,'POSTRIFF_RADAR_CREDIT_BILLING':'0'}
checks.append('existing wallet reservation, automatic fewer-than-three refund, unknown cost hold and explicit cancellation refund')
# For You uses only the current approved, bound Genome, and invalidates when a binding changes.
reset_day()
from postriff_phase2.contracts import digest
from postriff_phase2.growth.service import current_genome
def with_genome(state,actor):
    state['sources'].append({'id':'radar-voice','kind':'voice_sample','active':True,'selected':True,'revision':1,'useGrants':{'analysis':True}})
    state.setdefault('brandHub',{})['genome']={'status':'approved','consentDigest':digest(state['growthConsent']),'evidenceBindings':[{'id':'radar-voice','revision':1,'grantsDigest':digest({'analysis':True})}],'statements':[{'id':'lesson-1','grade':'supported','text':'Piano practice questions help my audience.'}]}
    return state
host.repository.command(wid,'one',saved()['revision'],with_genome)
assert current_genome(saved()['state'])
x=run(quote(useAi=False));assert any(o['forYou'] and o['genomeReasons'] for o in x['opportunities'])
def revoke_voice(state,actor):
    next(s for s in state['sources'] if s['id']=='radar-voice')['selected']=False;return state
host.repository.command(wid,'one',saved()['revision'],revoke_voice)
assert next(s for s in r.list(wid,'one')['scans'] if s['id']==x['id'])['stale']
refused(409,lambda:action('radar_save_idea',{'scanId':x['id'],'opportunityId':x['opportunities'][0]['id'],'confirmed':True}))
checks.append('supported approved Genome fit, evidence binding and stale context action refusal')
# No provider retry or fallback after an ambiguous Jev timeout.
reset_day();q=quote(sources=['news']);r.start(wid,'one',q['id'],{'confirmed':True});r.advance(wid,'one',q['id'])
from postriff_phase2.growth.jev import JevTimeout
original_evaluate=models.evaluate;attempts=[]
def timed_out(*a,**k):attempts.append(1);raise JevTimeout('Synthetic ambiguous timeout')
models.evaluate=timed_out
result=r.advance(wid,'one',q['id']);assert len(attempts)==1 and result['usage']['unknownAttempts']==1,result
models.evaluate=original_evaluate;action('radar_stop',{'scanId':q['id']})
checks.append('one ambiguous model attempt, no retry or fallback dispatch')
reset_day();x=run(quote());r.tombstone('bluesky','bluesky0');assert next(s for s in r.list(wid,'one')['scans'] if s['id']==x['id'])['status']=='cancelled'
with connection() as db:
    for table in ('pr_radar_runs','pr_radar_source_limits','pr_radar_watch_schedule'):
        for role in ('anon','authenticated'):assert not db.execute("SELECT has_table_privilege(%s,%s,'SELECT')",(role,'public.'+table)).fetchone()[0]
    db.execute('UPDATE public.pr_radar_runs SET expires_at=to_timestamp(%s) WHERE workspace_id=%s',(clock[0]-1,wid))
g.env={**g.env,'POSTRIFF_RADAR':'0'}
assert r.sweep()['expired']>0
g.env={**g.env,'POSTRIFF_RADAR':'1'}
assert not r.list(wid,'one')['scans']
with connection() as db:assert db.execute("SELECT count(*) FROM public.pr_model_usage_events WHERE workspace_id=%s AND task='radar.source'",(wid,)).fetchone()[0]>0
checks.append('deletion tombstone, excerpt retention, service-only RLS and source attempt accounting')
print(json.dumps({'status':'PASS','execution':'disposable PostgreSQL + synthetic providers/models','checks':checks,'realProviderCalls':0}))
