"""v3 Phase 1 application boundary: reserve/commit -> model -> fenced completion.

No model/network call holds a database lock. Workspace data never uses a shared cache.
All features default off; local tests inject models and use a disposable PostgreSQL.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import os
import secrets
import time
import uuid
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from .. import memory, voice_sources
from ..contracts import digest
from ..permissions import require
from . import advice, advice_context, genome, performance, questions, rewrite
from .judgments import JudgmentService, subject_hash
from .jev import JevService
from .post_doctor import PostDoctorService, level_names
from .router import AIModelRouter, RouterError, TASKS, chat_from_runtime
from .usage import MemoryUsageSink, PostgresUsageSink
from .closed_loop import ClosedLoop, ACTIONS as CLOSED_LOOP_ACTIONS, SUMMARY_ROUTE
from . import postmortem, creator_calibration
from ..radar.service import ACTIONS as RADAR_ACTIONS
from .decision_loop import DecisionLoop

ROUTES = ('cloud:vercel-ai-gateway:typesafe-ai/jev', 'cloud:vercel-ai-gateway:google/gemini-2.5-flash-lite')
ACTIONS = ('growth_consent','genome_approve','genome_restore','post_doctor_accept','post_doctor_feedback','share_card_create','share_card_revoke',*CLOSED_LOOP_ACTIONS,*RADAR_ACTIONS)
FLAGS = {'check':'POSTRIFF_POST_DOCTOR','rewrite':'POSTRIFF_POST_DOCTOR','genome':'POSTRIFF_GENOME','public':'POSTRIFF_PUBLIC_POST_DOCTOR',
         'postmortem':'POSTRIFF_POSTMORTEM','audience':'POSTRIFF_AUDIENCE_MINER'}
# Bounded input/output/work caps. Reservations are conservative protection, never reported as actual costs.
RESERVATIONS = {'check':10_000,'rewrite':200_000,'genome':800_000,'public':10_000,'postmortem':200_000,'audience':800_000}


def context_fingerprint(state):
    return advice_context.fingerprint(state)


def bindings_current(state, bindings):
    sources = {s['id']:s for s in state.get('sources',[]) if s.get('active')}
    return all((sources.get(b['id']) or {}).get('revision')==b['revision'] and sources[b['id']].get('selected')
               and not voice_sources.eligibility_reason(sources[b['id']]) and voice_sources.unexpired(sources[b['id']])
               and b.get('grantsDigest') == digest(sources[b['id']].get('useGrants'))
               for b in bindings)


def current_genome(state):
    saved = (state.get('brandHub') or {}).get('genome')
    if (not saved or saved.get('status')!='approved' or not (saved.get('evidenceBindings') or saved.get('outcomeBindings'))
            or not bindings_current(state,saved.get('evidenceBindings',[]))
            or not postmortem.bindings_current(state,saved.get('outcomeBindings',[]))
            or saved.get('consentDigest')!=digest(state.get('growthConsent'))):
        return None
    return saved


def public_result(result):
    """Keep qualitative feedback; never expose draft text, scores/probabilities, private IDs or costs."""
    return {k:copy.deepcopy(result[k]) for k in ('dimensions','risks','confidence','confidenceReasons','helping','hurting','change','status') if k in result}


def serialize(result, lang):
    qs = questions.get(result.question_set)
    names = level_names(qs,lang)
    dimensions = [{'id':d.id,'label':qs.dimensions[d.id]['label'].get('zh-HK' if lang.startswith('zh') else 'en',d.id),
                   'level':d.level,'levelName':names[d.level] if d.level is not None else 'Not enough evidence',
                   'fixes':list(d.fixes),'calibrated':d.calibrated,'missingContext':list(d.missing_context)} for d in result.dimensions]
    actions=advice.prioritize(dimensions,goal=result.context['goal'],missing_context={d.id:d.missing_context for d in result.dimensions if d.missing_context},lang=lang) if result.context else None
    return {**({'_adviceContext':result.context,'priorityActions':actions,'goal':result.context['goal'],'contextDigest':result.context['digest'],
                 'missingContext':{d.id:list(d.missing_context) for d in result.dimensions if d.missing_context}} if result.context else {}),
            'questionSet':result.question_set,'dimensions':dimensions,'risks':list(result.risks),
            'computed':result.computed,'confidence':result.confidence,'confidenceReasons':list(result.confidence_reasons),
            'helping':[d['label'] for d in dimensions if d['level'] is not None and d['level']>=2],
            'hurting':[d['label'] for d in dimensions if d['level'] is not None and d['level']<=1],
            'change':[a['change'] for a in actions] if actions is not None else [hint for d in dimensions for hint in d['fixes']][:4],
            'status':'complete' if result.judgment.status=='ok' else 'partial',
            '_judgment':{'model':result.judgment.model,'route':result.judgment.route,'rubricDigest':result.judgment.digest,
                         'calibrated':result.judgment.calibrated,
                         'answers':{k:{'value':a.value,'probabilities':a.probabilities,'abstained':a.abstained} for k,a in result.judgment.answers.items()}},
            '_scores':{d.id:d.score for d in result.dimensions if d.score is not None}}


def client_result(value):
    """Internal numeric evaluation data stays in the prediction ledger, never the advisory UI."""
    if isinstance(value,dict):
        return {k:client_result(v) for k,v in value.items() if not k.startswith('_')}
    if isinstance(value,list):return [client_result(v) for v in value]
    return value


def prediction(result,run_id,revision,text, *, comparison=None, accepted_change_ids=()):
    return {**({'goal':result['goal'],'contextDigest':result['contextDigest'],'comparison':comparison,
                 'acceptedChangeIds':list(accepted_change_ids),'inputContextFingerprint':result.get('_contextFingerprint')} if 'goal' in result else {}),
            'runId':run_id,'textDigest':digest(text),'revision':revision,'levels':result['dimensions'],
            'baseline':result['baseline'],'questionSet':result['questionSet'],'evaluation':result.get('_judgment',{}),'scores':result.get('_scores',{})}


class GrowthService:
    def __init__(self, hosted, *, env=None, router_factory=None, clock=None, profile=None):
        self.hosted = hosted
        self.repository = hosted.repository
        self.env = dict(os.environ if env is None else env)
        self.clock = clock or hosted.clock
        self.router_factory = router_factory
        self.profile = profile
        self.closed_loop = ClosedLoop(self)
        from ..radar.service import Radar
        self.radar = Radar(self)
        self.repository.effects.append(self.invalidate)

    def _context(self,state):
        base=context_fingerprint(state)
        if self.env.get('POSTRIFF_POST_DOCTOR_V2')!='1':return base
        qs=questions.get('postdoctor',2)
        return digest([base,qs.key,qs.digest,questions.get('postdoctor_compare',1).digest])

    @staticmethod
    def _draft_matches(state,draft):
        if not draft or not draft.get('id'):return True
        current=next((v for v in state.get('variants',[]) if v['id']==draft['id']),{})
        return (current.get('revision')==draft['revision'] and current.get('text')==draft['text']
                and (draft.get('adviceVersion')!=2 or current.get('postDoctorGoal','general')==draft.get('goal','general')))

    def enabled(self,kind):
        return self.env.get('POSTRIFF_GROWTH')=='1' and self.env.get(FLAGS[kind])=='1'

    def gate(self,kind):
        if not self.enabled(kind):
            raise AlphaError('Growth intelligence is not enabled.',404,code='feature_disabled')

    @staticmethod
    def session(token):
        if str(token).startswith('prt_'):
            raise AlphaError('Use an interactive session for growth intelligence.',403)

    def cap(self,name):
        try:
            value = float(self.env.get(name,''))
        except (ValueError,TypeError):
            value = 0
        if not math.isfinite(value) or value<=0 or value>10000:
            raise AlphaError('A finite growth cost limit must be configured.',503,code='growth_budget_unconfigured')
        return math.floor(value*1_000_000)

    def reserve(self,cur,scope,amount,cap,max_calls):
        day = time.strftime('%Y-%m-%d',time.gmtime(self.clock()))
        cur.execute('INSERT INTO public.pr_growth_budgets(scope,day) VALUES(%s,%s) ON CONFLICT DO NOTHING',(scope,day))
        cur.execute('UPDATE public.pr_growth_budgets SET reserved_micro=reserved_micro+%s,calls=calls+1 WHERE scope=%s AND day=%s AND reserved_micro+%s<=%s AND calls<%s RETURNING calls',
                    (amount,scope,day,amount,cap,max_calls))
        if cur.fetchone() is None:
            raise AlphaError('Today’s growth allowance has been used. Your normal drafts still work.',429,code='growth_daily_limit')

    def _router(self,sink,state=None,writer=None,guard=None):
        if self.router_factory:
            return self._guard_router(self.router_factory(sink,writer),guard, self.env.get("POSTRIFF_POST_DOCTOR_V2")=="1")
        tasks = copy.deepcopy(TASKS)
        grant = (state or {}).get('growthConsent',{}).get('routes',[])
        if state is None:
            grant = list(ROUTES)
        for key,value in list(tasks.items()):
            kind,primary,fallbacks,budget,max_tokens = value
            if kind=='evaluate':
                tasks[key]=(kind,primary,tuple(m for m in fallbacks if 'cloud:vercel-ai-gateway:'+m in grant),budget,max_tokens)
        if writer:
            tasks['postdoctor.rewrite']=('chat',writer,(),45.0,4000)
        api_key=self.env.get('AI_GATEWAY_API_KEY')
        jev = JevService(api_key) if api_key and self.env.get('POSTRIFF_JEV')=='1' and ROUTES[0] in grant else None
        runtime = (self.hosted.ideas._select_runtime(writer) if writer else
                   next((r for r in self.hosted.ideas.runtimes if getattr(r,'provider_class',None)=='cloud' and getattr(r,'cost_class',None)=='paid'),None))
        return self._guard_router(AIModelRouter(jev=jev,chat=chat_from_runtime(runtime) if runtime else None,usage=sink,tasks=tasks),guard, self.env.get("POSTRIFF_POST_DOCTOR_V2")=="1")

    @staticmethod
    def _guard_router(router,guard,reconcile_unknown=False):
        router.reconcile_unknown=reconcile_unknown
        if guard is None:return router
        if router.jev:
            evaluate=router.jev.evaluate
            def guarded_evaluate(*args,**kwargs):
                guard()
                return evaluate(*args,**kwargs)
            router.jev=SimpleNamespace(evaluate=guarded_evaluate)
        if router.chat:
            chat=router.chat
            def guarded_chat(*args,**kwargs):
                guard()
                return chat(*args,**kwargs)
            guarded_chat.enforces_timeout=getattr(chat,'enforces_timeout',False)
            router.chat=guarded_chat
        return router

    def guard(self,workspace_id,token,run):
        """Recheck permission/context before every retry, fallback and rewrite/recheck call; no lock across HTTP."""
        from ..hosted import _membership
        with self.repository.transaction(token,workspace_id) as (_,row,_):
            require(_membership(row),run.get('requirement','edit'))
            state=row[1]
            if self._context(state)!=run['context']:
                raise AlphaError('The input or AI permission changed. Check the current version.',409,code='growth_input_changed')
            draft=run['prepared'].get('draft')
            if draft and draft.get('id'):
                current=self._draft(state,{'variantId':draft['id'],'variantRevision':draft['revision']})
                if not self._draft_matches(state,draft):
                    raise AlphaError('This draft changed. Check its current version.',409,code='growth_input_changed')

    def _doctor(self,router, *, legacy=False):
        env={**self.env,"POSTRIFF_POST_DOCTOR":"1"}
        if legacy:env["POSTRIFF_POST_DOCTOR_V2"]="0"
        return PostDoctorService(JudgmentService(router.evaluator("postdoctor.judge")),env=env,profile=self.profile)

    def _consent(self,state):
        routes = (state.get('growthConsent') or {}).get('routes',[])
        if not any(route in routes for route in ROUTES):
            raise AlphaError('The owner must allow the growth analysis routes first.',403,code='growth_consent_required')

    def catalog(self,workspace_id,token):
        self.session(token)
        saved=self.repository.get(workspace_id,token)
        _runtime,writer,_note=self.hosted.ideas.resolve_writer(saved['state'],None)
        return {'radar':self.env.get('POSTRIFF_GROWTH')=='1' and self.env.get('POSTRIFF_RADAR')=='1','postDoctorV2':self.env.get('POSTRIFF_POST_DOCTOR_V2')=='1','postDoctor':self.enabled('check'),'genome':self.enabled('genome'),
                'postmortem':self.enabled('postmortem'),'audienceMiner':self.enabled('audience'),
                'summaryRoute':SUMMARY_ROUTE,'audienceConsent':saved['state'].get('growthConsent',{}).get('audience') is True,
                'consented':bool(saved['state'].get('growthConsent',{}).get('routes')),
                'routes':list(ROUTES),'allowedRoutes':saved['state'].get('growthConsent',{}).get('routes',[]),
                'writer':writer,'writerRoute':'cloud:vercel-ai-gateway:'+writer,
                'maxHistoryPosts':genome.MAX_POSTS,'checksPerDay':10,'rewritesPerDay':1}

    def _history(self,cur,workspace_id,state):
        cur.execute('SELECT id::text,source_id,source_revision,platform,connection_id,provider_post_id,language,format,time_bucket,labels,judgment,supplied_metrics FROM public.pr_post_history WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 300',(workspace_id,))
        sources={s['id']:s for s in state.get('sources',[]) if s.get('kind')=='voice_sample'}
        posts=[]
        for row in cur.fetchall():
            source=sources.get(row[1],{})
            if not source.get('active') or not source.get('selected') or source.get('revision')!=row[2] or voice_sources.eligibility_reason(source):
                continue
            post=dict(zip(('id','sourceId','sourceRevision','platform','connectionId','providerPostId','language','format','timeBucket','labels','scores','suppliedMetrics'),row))
            post['grantsDigest']=digest(source.get('useGrants'))
            post['provider']={'Threads':'threads','Instagram':'instagram'}.get(post['platform'])
            # Uploaded IDs alone cannot attest official provenance, even within the same workspace.
            cur.execute('SELECT 1 FROM public.pr_owned_posts WHERE workspace_id=%s AND connection_id=%s AND provider=%s AND provider_post_id=%s',
                        (workspace_id,post['connectionId'],post['provider'],post['providerPostId']))
            owned=cur.fetchone() is not None
            if not owned:
                owned=any(performance.official_job(j) and str(j.get('providerReference'))==post['providerPostId']
                          and (j.get('manifest') or {}).get('channelId')==post['connectionId']
                          and (j.get('manifest') or {}).get('platform')==post['platform'] for j in state.get('phase2',{}).get('jobs',[]))
            if not owned:
                post['provider']=None
            post['officialOrigin'] = owned
            posts.append(post)
        return performance.attach_readings(cur,workspace_id,posts)

    def _draft(self,state,body):
        variant_id=body.get('variantId')
        if variant_id:
            variant=next((v for v in state.get('variants',[]) if v['id']==variant_id),None)
            if not variant:
                raise AlphaError('Draft unavailable.',404)
            if body.get('variantRevision')!=variant['revision']:
                raise AlphaError('This draft changed. Check its current version.',409,code='draft_revision_conflict')
            return {k:variant.get(k) for k in ('id','text','platform','language','revision','channelId','formatId')}
        text=body.get('text')
        if not isinstance(text,str) or not text.strip() or len(text)>8000:
            raise AlphaError('Paste a draft of at most 8,000 characters.')
        if body.get('platform') not in ('Threads','Instagram','LinkedIn','X','Bluesky','Mastodon'):
            raise AlphaError('Choose a supported draft platform.')
        lang=body.get('language','en')
        if not isinstance(lang,str) or len(lang)>40:
            raise AlphaError('Choose a draft language.')
        return {'text':text,'platform':body['platform'],'language':lang,'revision':None,'id':None}

    def _begin(self,workspace_id,token,kind,body,prepare,requirement='edit'):
        from ..hosted import _membership
        self.session(token);self.gate(kind)
        key=body.get('requestKey')
        if not isinstance(key,str) or not 16<=len(key)<=100:
            raise AlphaError('A request key is required.')
        if body.get('confirmed') is not True:
            raise AlphaError('Confirm the shown AI use before continuing.')
        fingerprint=digest(body)
        with self.repository.transaction(token,workspace_id) as (cur,row,principal):
            require(_membership(row),requirement)
            state=copy.deepcopy(row[1]);self._consent(state)
            cur.execute('SELECT id::text,status,fingerprint,body,context_fingerprint FROM public.pr_post_doctor_runs WHERE workspace_id=%s AND request_key=%s',(workspace_id,key))
            old=cur.fetchone()
            if old:
                if old[2]!=fingerprint:
                    raise AlphaError('That request key belongs to another input.',409,code='growth_key_conflict')
                if old[1]=='completed':
                    draft=old[3].get('draft')
                    if old[4]!=self._context(state) or not self._draft_matches(state,draft):
                        raise AlphaError('This completed request belongs to an older input.',409,code='growth_input_changed')
                    return {'replayed':client_result(old[3])}
                raise AlphaError('This request already started. Its result must be reconciled before trying again.',409,code='growth_request_pending')
            prepared=prepare(cur,state,principal)
            if kind=='check' and prepared['draft'].get('adviceVersion')==2 and prepared['draft'].get('id'):
                variant=next(v for v in state['variants'] if v['id']==prepared['draft']['id'])
                variant['postDoctorGoal']=prepared['draft']['goal']
                variant.pop('postDoctor',None)
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),workspace_id))
            amount=RESERVATIONS[kind]
            if kind=='rewrite':
                runtime=self.hosted.ideas._select_runtime(prepared['writer'])
                if hasattr(runtime,'_cost'):
                    from ..model_runtime import output_cap, thinking
                    cap=max(4000,output_cap(prepared['writer'])) if thinking(prepared['writer']) else 4000
                    cost=runtime._cost(prepared['writer'],prepared['promptBytes']+256,cap)
                    if not isinstance(cost,(int,float)) or not math.isfinite(cost) or cost<0:
                        raise AlphaError('This writer needs verified prices before rewriting.',503)
                    amount=max(amount,math.ceil(cost*1_000_000)+20_000)
            self.reserve(cur,'global',amount,self.cap('POSTRIFF_GROWTH_DAILY_USD_CAP'),10000)
            self.reserve(cur,workspace_id,amount,self.cap('POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP'),1000)
            self.reserve(cur,f'{workspace_id}:{kind}',0,1,{'check':10,'rewrite':1,'genome':1,'postmortem':10,'audience':2}[kind])
            run_id=str(uuid.uuid4());context=self._context(state)
            cur.execute('INSERT INTO public.pr_post_doctor_runs(id,workspace_id,request_key,kind,status,fingerprint,context_fingerprint,created_by) VALUES(%s,%s,%s,%s,\'running\',%s,%s,%s)',
                        (run_id,workspace_id,key,kind,fingerprint,context,principal))
            return {'id':run_id,'state':state,'context':context,'prepared':prepared,'requirement':requirement}

    def _finish(self,workspace_id,token,run,sink,result,error=None,store=None):
        from ..hosted import _membership
        # Record actual attempts even if the member/consent/input changed during the network call.
        with self.hosted.connection_factory() as db,db.cursor() as cur:
            for event in sink.events:
                PostgresUsageSink(cur).record(event)
        try:
            with self.repository.transaction(token,workspace_id) as (cur,row,principal):
                require(_membership(row),run.get('requirement','edit'))
                current=row[1]
                valid=self._context(current)==run['context']
                draft=(run.get('prepared') or {}).get('draft')
                if draft and draft.get('id'):
                    candidate=next((v for v in current.get('variants',[]) if v['id']==draft['id']),{})
                    valid=valid and self._draft_matches(current,draft)
                status='cancelled' if not valid else 'unknown' if error and sink.events else 'failed' if error else 'completed'
                if status=='completed' and store:
                    result=store(cur,current,principal,result)
                saved={**(result or {}),'runId':run['id']} if status=='completed' else {'runId':run['id'],'status':status}
                cur.execute('UPDATE public.pr_post_doctor_runs SET status=%s,body=%s::jsonb WHERE workspace_id=%s AND id=%s AND status=\'running\'',
                            (status,json.dumps(saved),workspace_id,run['id']))
        except Exception:
            with self.hosted.connection_factory() as db,db.cursor() as cur:
                cur.execute("UPDATE public.pr_post_doctor_runs SET status='cancelled',body='{}' WHERE workspace_id=%s AND id=%s AND status='running'",(workspace_id,run['id']))
            raise
        if not valid:
            raise AlphaError('The draft, voice, history or consent changed. Discard this result and check the current version.',409,code='growth_input_changed')
        if error:
            if isinstance(error,AlphaError):raise error
            raise AlphaError('Growth AI could not complete this request. Your normal draft flow is available.',503,code='growth_ai_unavailable') from error
        return client_result(saved)

    def _check(self,router,workspace_id,state,draft,posts):
        creator={}
        if memory.egress(state).get('cloud') is True:
            creator={k:v for k,v in state.get('brandHub',{}).items() if k in ('audience','purpose','subject')}
            active=current_genome(state)
            if active:
                creator['genome']=[s['text'] for s in active.get('statements',[]) if s['grade']=='supported'][:12]
        target={'platform':draft['platform'],'connectionId':draft.get('channelId'),'language':draft['language'],'format':draft.get('formatId') or 'text','timeBucket':'unknown'}
        measured=sum(performance.cohort(p)==performance.cohort(target) and genome.relative(p,posts) is not None for p in posts)
        result=serialize(self._doctor(router,legacy=workspace_id is None).check(workspace_id=workspace_id,draft_text=draft['text'],platform=draft['platform'],
                                                  lang=draft['language'],creator=creator,posts_with_metrics=measured,goal=draft.get('goal','general'),format_id=draft.get('formatId') or 'text'),draft['language'])
        # Imported history currently uses v1; never compare different rubric scores.
        result['computed']['fit_winners']=genome.fit_winners(result['_scores'],posts,target) if result['questionSet']=='postdoctor.v1' else None
        if workspace_id and self.enabled('postmortem'):
            with self.hosted.connection_factory() as db,db.cursor() as cur:
                profile=self.closed_loop.active_calibration(cur,workspace_id,state)
            if profile:
                result['computed']['creatorFit']=creator_calibration.apply(profile,target,result['_judgment']['model'],result['_judgment']['rubricDigest'],result['_scores'])
        result['_contextFingerprint']=context_fingerprint(state)
        result['draft']={**draft,'digest':digest(draft['text'])}
        result['baseline']={'measuredPosts':measured,'basis':'24h','genomeId':(current_genome(state) or {}).get('id')}
        result['judgment']={'model':result['_judgment']['model'],'questionSet':result['questionSet'],'calibrated':result['_judgment']['calibrated']}
        return result

    def check(self,workspace_id,token,body):
        def prepare(cur,state,principal):
            draft=self._draft(state,body)
            if self.env.get('POSTRIFF_POST_DOCTOR_V2')=='1':
                try:ctx=advice_context.build({},goal=body.get('goal','general'),format_id=draft.get('formatId') or 'text')
                except ValueError as e:raise AlphaError(str(e)) from e
                draft.update(goal=ctx['goal'],adviceVersion=2)
            if len(draft['text'])>8000:
                raise AlphaError('Post Doctor checks up to 8,000 characters.',413)
            return {'draft':draft,'posts':self._history(cur,workspace_id,state)}
        run=self._begin(workspace_id,token,'check',body,prepare)
        if 'replayed' in run:return run['replayed']
        sink=MemoryUsageSink();result=None;error=None
        try:
            result=self._check(self._router(sink,run['state'],guard=lambda:self.guard(workspace_id,token,run)),workspace_id,run['state'],**run['prepared'])
        except Exception as caught:error=caught
        def store(cur,state,principal,result):
            draft=result['draft']
            if draft.get('id'):
                variant=next(v for v in state['variants'] if v['id']==draft['id'])
                accepted=variant.get('postDoctorAccepted',{})
                if accepted.get('textDigest')!=digest(draft['text']) or accepted.get('goal')!=result.get('goal') or accepted.get('contextDigest')!=result.get('contextDigest'):accepted={}
                variant['postDoctor']=prediction(result,run['id'],draft['revision'],draft['text'],comparison=accepted.get('comparison'),accepted_change_ids=accepted.get('changeIds',()))
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),workspace_id))
            return result
        return self._finish(workspace_id,token,run,sink,result,error,store)

    def rewrite(self,workspace_id,token,body):
        def prepare(cur,state,principal):
            cur.execute("SELECT body,context_fingerprint FROM public.pr_post_doctor_runs WHERE workspace_id=%s AND id::text=%s AND kind='check' AND status='completed'",(workspace_id,body.get('checkId')))
            row=cur.fetchone()
            if not row:raise AlphaError('Check unavailable.',404)
            check=row[0]
            if row[1]!=self._context(state):raise AlphaError('Check your current voice and history again.',409)
            draft=check['draft']
            if not self._draft_matches(state,draft):raise AlphaError('The draft goal changed. Check again.',409,code='growth_input_changed')
            if draft.get('id'):self._draft(state,{'variantId':draft['id'],'variantRevision':draft['revision']})
            facts=body.get('facts',{})
            if (not isinstance(facts,dict) or len(facts)>10 or any(not isinstance(k,str) or not 1<=len(k)<=40 or not isinstance(v,str) or not 1<=len(v)<=1000 for k,v in facts.items())):
                raise AlphaError('Supply up to ten of your own facts or examples.')
            requested=body.get('model')
            runtime,writer,_=self.hosted.ideas.resolve_writer(state,requested)
            if getattr(runtime,'provider_class',None)!='cloud':
                raise AlphaError('Post Doctor requires a managed cloud writer.',409,code='growth_writer_unavailable')
            route='cloud:vercel-ai-gateway:'+writer
            if route not in state.get('growthConsent',{}).get('routes',[]):
                raise AlphaError('The owner must allow this exact rewrite model first.',403,code='growth_writer_consent_required')
            voice=memory.projection(state,'cloud',voice_route=route)
            payload={'original':draft['text'],'sentences':rewrite.sentences(draft['text']),
                     'creatorFacts':facts,'weakDimensions':check['change'],'voice':voice['files']}
            messages=[{'role':'system','content':rewrite.SYSTEM},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
            prompt_bytes=len(json.dumps(messages,ensure_ascii=False).encode())
            if prompt_bytes>60_000:raise AlphaError('This rewrite context is too large; shorten the draft or examples.',413)
            return {'draft':draft,'check':check,'facts':facts,'writer':writer,'messages':messages,'promptBytes':prompt_bytes,'posts':self._history(cur,workspace_id,state)}
        run=self._begin(workspace_id,token,'rewrite',body,prepare)
        if 'replayed' in run:return run['replayed']
        sink=MemoryUsageSink();result=None;error=None
        try:
            p=run['prepared'];router=self._router(sink,run['state'],p['writer'],guard=lambda:self.guard(workspace_id,token,run))
            result=router.complete_json('postdoctor.rewrite',p['messages'],
                        validate=lambda d:rewrite.validate(d,p['draft']['text'],p['facts']),workspace_id=workspace_id,subject=subject_hash('rewrite',run['id']))
            qs=questions.get('grounding')
            grounding=JudgmentService(router.evaluator('postdoctor.grounding')).judge(qs,{'original':p['draft']['text'],'creatorFacts':p['facts'],'rewrite':result['rewrite']},
                        scope='personal:'+workspace_id,subject=subject_hash('grounding',run['id']),model='typesafe-ai/jev',workspace_id=workspace_id)
            if (grounding.probability('claims_supported') or 0)<.9:
                raise AlphaError('New claims could not be grounded in your facts.',409,code='rewrite_ungrounded')
            after=self._check(router,workspace_id,run['state'],{**p['draft'],'text':result['rewrite']},p['posts'])
            result.update(before=p['check'],after=after,original=p['draft']['text'],facts=p['facts'],checkId=body['checkId'],draft=p['draft'],grounding='passed')
            if p['check']['questionSet']=='postdoctor.v2':
                ctx=after.get('_adviceContext',{})
                comparison_state=advice.comparison_state(p['draft']['text'],result['rewrite'],context=ctx,facts=p['facts'],order='original_first')
                if comparison_state['identical']:
                    comparison={'recommended':'equivalent','status':'review','reasons':['no_material_difference'],'orderChecked':False}
                else:
                    qs=questions.get('postdoctor_compare',1)
                    judge=JudgmentService(router.evaluator('postdoctor.compare'))
                    first=judge.judge(qs,comparison_state,scope='personal:'+workspace_id,subject=subject_hash('comparison',run['id'],'original_first'),model='typesafe-ai/jev',workspace_id=workspace_id)
                    reverse=judge.judge(qs,advice.comparison_state(p['draft']['text'],result['rewrite'],context=ctx,facts=p['facts'],order='candidate_first'),scope='personal:'+workspace_id,subject=subject_hash('comparison',run['id'],'candidate_first'),model='typesafe-ai/jev',workspace_id=workspace_id)
                    comparison=advice.decide(first,grounded=True,voice_preserved=(grounding.probability('voice_preserved') or 0)>=.9,swapped=reverse)
                    comparison.update(model=first.model,swappedModel=reverse.model,questionSet=qs.key,rubricDigest=qs.digest)
                result['comparison']={**comparison,'originalDigest':digest(p['draft']['text']),'candidateDigest':digest(result['rewrite']),'contextDigest':after.get('contextDigest'),'goal':after.get('goal','general')}

        except Exception as caught:error=caught
        return self._finish(workspace_id,token,run,sink,result,error)

    def imports(self,workspace_id,token,body):
        def prepare(cur,state,principal):
            # Retaining/importing a corpus and granting routes is an owner decision.
            if body.get('ownContent') is not True or body.get('retainText') is not True:
                raise AlphaError('Confirm that these are your own posts and that their text may be retained.')
            ids=body.get('sourceIds',[])
            metrics_by_source={}
            previous={p['sourceId']:p for p in self._history(cur,workspace_id,state)}
            if body.get('data'):
                before=copy.deepcopy(state)
                records=genome.parse_upload(body['data'])
                connection=body.get('connectionId','')
                if connection and not any(c['id']==connection for c in state.get('phase2',{}).get('channels',[])):
                    raise AlphaError('Choose an account in this workspace.')
                if not connection:
                    account=body.get('account')
                    if not isinstance(account,str) or not 1<=len(account.strip())<=80:
                        raise AlphaError('Name the one account represented by this CSV.')
                    connection='export:'+digest(account.strip())[:24]
                channel=next((c for c in state.get('phase2',{}).get('channels',[]) if c['id']==connection),None)
                if channel and any(r['platform']!=channel['platform'] for r in records):
                    raise AlphaError('The CSV platform must match the selected account.')
                for rec in records:rec['account']=connection
                imported=voice_sources.apply_action(state,'voice_samples_import_owned',{'format':'json','records':records,
                    'authorshipConfirmed':True, 'representativeConfirmed': body.get('representativeContent') is True},principal,self.clock())
                ids=imported['imported']+imported['revised']+imported['unchanged']
                source_map={s['importIdentity']:s for s in state['sources'] if s.get('kind')=='voice_sample'}
                for rec,normalized in zip(records,voice_sources.normalize_import({'format':'json','records':records})):
                    source=source_map[normalized['importIdentity']]
                    metrics_by_source[source['id']]=rec
                    source['growthConnectionId']=connection
                    voice_sources.apply_action(state,'voice_sample_select',{'sourceId':source['id'],'selected':True},principal,self.clock())
                    voice_sources.apply_action(state,'voice_sample_grant',{'sourceId':source['id'],'confirmed':True,'grants':[{'purpose':'analysis','route':r} for r in ROUTES if r in state['growthConsent']['routes']]},principal,self.clock())
                self.invalidate(cur,workspace_id,before,state,principal)
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),workspace_id))
            if not isinstance(ids,list) or not 1<=len(ids)<=genome.MAX_POSTS or len(set(ids))!=len(ids):
                raise AlphaError('Choose 1–20 distinct owned voice samples.')
            permitted={sample['id'] for route in ROUTES if route in state['growthConsent']['routes']
                       for sample in voice_sources.project(state,ids,'analysis',route)['samples']}
            if permitted!=set(ids):
                raise AlphaError('Every selected sample needs explicit growth analysis permission.',403)
            posts=[]
            for source in state.get('sources',[]):
                if source.get('id') not in ids:continue
                rec=metrics_by_source.get(source['id'],{})
                prior=previous.get(source['id'],{}) if not body.get('data') else {}
                posts.append({'sourceId':source['id'],'sourceRevision':source['revision'],'text':source['text'],'platform':source.get('platform') or 'Threads',
                              'language':source.get('language') or 'en','connectionId':source.get('growthConnectionId') or source.get('connectionId') or '',
                              'providerPostId':source.get('externalId') or '', 'format':rec.get('format') or prior.get('format') or 'text','timeBucket':rec.get('timeBucket') or prior.get('timeBucket') or 'unknown',
                              'suppliedMetrics':({'horizon':rec.get('horizon'),'values':rec.get('metrics',{})} if rec.get('metrics') else prior.get('suppliedMetrics',{}))})
            return {'posts':posts,'sourceIds':ids}
        # Owners grant corpus retention; editor can analyze only already-granted samples.
        run=self._begin(workspace_id,token,'genome',body,prepare,requirement='owner' if body.get('data') else 'edit')
        if 'replayed' in run:return run['replayed']
        sink=MemoryUsageSink();result=None;error=None
        try:
            deadline=time.monotonic()+220;posts=[]
            loop=DecisionLoop(genome.MAX_POSTS)
            while (source_id:=loop.choose([p['sourceId'] for p in run['prepared']['posts']])) is not None:
                post=next(p for p in run['prepared']['posts'] if p['sourceId']==source_id)
                if time.monotonic()>deadline:raise AlphaError('History analysis reached its time limit; no partial Genome was approved.',503)
                source=next(s for s in run['state']['sources'] if s['id']==post['sourceId'])
                # Exact-route grants may differ across existing samples. Never expand them through fallback.
                routes=[r for r in ROUTES if r in run['state']['growthConsent']['routes']
                        and voice_sources.route_granted(source,'analysis',r)]
                sample_state=copy.deepcopy(run['state']);sample_state['growthConsent']['routes']=routes
                sample_router=self._router(sink,sample_state,guard=lambda:self.guard(workspace_id,token,run))
                judgment=JudgmentService(sample_router.evaluator('genome.label')).judge(questions.get('genome'),{'draft':post['text'],'platform':post['platform'],'lang':post['language']},
                            scope='personal:'+workspace_id,subject=subject_hash('genome',post['sourceId'],post['sourceRevision']),model='typesafe-ai/jev',workspace_id=workspace_id)
                post_result=self._doctor(sample_router,legacy=True).check(workspace_id=workspace_id,draft_text=post['text'],platform=post['platform'],lang=post['language'])
                assigned=genome.labels(judgment)
                if judgment.status!='ok' or not assigned:
                    raise AlphaError('This history did not have enough AI evidence to propose a Genome.',503,code='genome_evidence_unavailable')
                posts.append({**post,'labels':assigned,'scores':{d.id:d.score for d in post_result.dimensions if d.score is not None}})
                loop.finish(source_id,'completed')
            result={'posts':posts,'decisions':loop.events}
        except Exception as caught:error=caught
        def store(cur,state,principal,result):
            for p in result['posts']:
                cur.execute('INSERT INTO public.pr_post_history(workspace_id,source_id,source_revision,platform,connection_id,provider_post_id,language,format,time_bucket,labels,judgment,supplied_metrics) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb) ON CONFLICT(workspace_id,source_id) DO UPDATE SET source_revision=excluded.source_revision,platform=excluded.platform,connection_id=excluded.connection_id,provider_post_id=excluded.provider_post_id,language=excluded.language,format=excluded.format,time_bucket=excluded.time_bucket,labels=excluded.labels,judgment=excluded.judgment,supplied_metrics=excluded.supplied_metrics',
                            (workspace_id,p['sourceId'],p['sourceRevision'],p['platform'],p['connectionId'],p['providerPostId'],p['language'],p['format'],p['timeBucket'],json.dumps(p['labels']),json.dumps(p['scores']),json.dumps(p['suppliedMetrics'])))
            proposed=genome.proposal(self._history(cur,workspace_id,state));vid=str(uuid.uuid4());proposed.update(id=vid,consentDigest=digest(state.get('growthConsent')))
            cur.execute('INSERT INTO public.pr_genome_versions(id,workspace_id,body,created_by) VALUES(%s,%s,%s::jsonb,%s)',(vid,workspace_id,json.dumps(proposed),principal))
            return {'genome':proposed,'decisions':result['decisions']}
        return self._finish(workspace_id,token,run,sink,result,error,store)

    def genome(self,workspace_id,token):
        self.session(token);self.gate('genome')
        with self.repository.transaction(token,workspace_id) as (cur,row,_):
            cur.execute('SELECT id::text,status,body FROM public.pr_genome_versions WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 20',(workspace_id,))
            versions=[{**r[2],'id':r[0],'status':r[1] if bindings_current(row[1],r[2].get('evidenceBindings',[])) and postmortem.bindings_current(row[1],r[2].get('outcomeBindings',[])) and r[2].get('consentDigest')==digest(row[1].get('growthConsent')) else 'stale'} for r in cur.fetchall()]
            sources={s['id']:s for s in row[1].get('sources',[]) if s.get('active') and s.get('selected')}
            evidence={p['id']:{'title':sources[p['sourceId']].get('title','Owned post'),'text':sources[p['sourceId']]['text'],
                                'platform':p['platform'],'providerPostId':p['providerPostId']} for p in self._history(cur,workspace_id,row[1]) if p['sourceId'] in sources}
            for job in row[1].get('phase2',{}).get('jobs',[]):
                if job.get('state')=='verified':
                    payload=job.get('manifest',{}).get('payload',{})
                    evidence[job['id']]={'title':'Verified publication','text':payload.get('text',''),'platform':job['manifest'].get('platform'),'providerPostId':job.get('providerReference')}
            cur.execute('SELECT id::text,revoked_at FROM public.pr_share_cards WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 20',(workspace_id,))
            return {'versions':versions,'active':current_genome(row[1]),'evidence':evidence,'shares':[{'id':r[0],'revoked':r[1] is not None} for r in cur.fetchall()]}

    def action(self,workspace_id,token,revision,action,payload):
        from ..hosted import audit
        if action in RADAR_ACTIONS:
            return self.radar.action(workspace_id,token,revision,action,payload)
        if action in CLOSED_LOOP_ACTIONS:
            return self.closed_loop.action(workspace_id,token,revision,action,payload)
        self.session(token)
        kind='genome' if action.startswith(('genome_','share_card_')) else 'check'
        if action=='growth_consent':
            if not (self.env.get('POSTRIFF_GROWTH')=='1' and self.env.get('POSTRIFF_RADAR')=='1') and not any(self.enabled(k) for k in ('genome','check','postmortem','audience')):self.gate('check')
        else:self.gate(kind)
        response={}
        def command(state,principal):
            if action=='growth_consent':
                routes=payload.get('routes')
                if payload.get('confirmed') is not True or not isinstance(routes,list) or len(routes)>8 or any(not isinstance(r,str) or not r.startswith('cloud:vercel-ai-gateway:') or len(r)>120 for r in routes):
                    raise AlphaError('Confirm the exact growth analysis and rewrite routes.')
                # Rewrite grants can name only offered cloud writer models.
                models={r['id'] for r in self.hosted.ideas.model_catalog().get('models',[]) if isinstance(r,dict)}
                if any(r not in (*ROUTES,SUMMARY_ROUTE) and r.removeprefix('cloud:vercel-ai-gateway:') not in models for r in routes):
                    raise AlphaError('Choose currently offered model routes.')
                state['growthConsent']={'routes':list(dict.fromkeys(routes)),'actor':principal,'at':self.clock(),
                                        'audience':payload.get('audience') is True and bool(routes)}
            return state
        def after(cur,state,principal):
            if action in ('genome_approve','genome_restore'):
                cur.execute('SELECT body,status FROM public.pr_genome_versions WHERE workspace_id=%s AND id::text=%s FOR UPDATE',(workspace_id,payload.get('genomeId')))
                row=cur.fetchone()
                if (not row or row[1]=='stale' or not bindings_current(state,row[0].get('evidenceBindings',[]))
                        or not postmortem.bindings_current(state,row[0].get('outcomeBindings',[]))
                        or row[0].get('consentDigest')!=digest(state.get('growthConsent'))):
                    raise AlphaError('This Genome is stale or unavailable.',409)
                if action=='genome_restore' and row[1] not in ('approved','superseded'):
                    raise AlphaError('Restore a previously approved version.',409)
                if payload.get('confirmed') is not True:raise AlphaError('Review and confirm this Genome version.')
                cur.execute("UPDATE public.pr_genome_versions SET status='superseded' WHERE workspace_id=%s AND status='approved'",(workspace_id,))
                cur.execute("UPDATE public.pr_genome_versions SET status='approved',approved_by=%s,approved_at=now() WHERE workspace_id=%s AND id::text=%s",(principal,workspace_id,payload['genomeId']))
                state.setdefault('brandHub',{})['genome']={**row[0],'status':'approved'}
                # Existing brand digest fencing invalidates prior publish approvals on a profile change.
                for v in state.get('variants',[]):v['needsReview']=True
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),workspace_id))
                audit(cur,workspace_id,principal,'genome.approved',payload['genomeId'],{'restored':action=='genome_restore'})
            elif action=='post_doctor_accept':
                cur.execute("SELECT body,context_fingerprint FROM public.pr_post_doctor_runs WHERE workspace_id=%s AND id::text=%s AND kind='rewrite' AND status='completed' FOR UPDATE",(workspace_id,payload.get('rewriteId')))
                row=cur.fetchone()
                if not row or row[1]!=self._context(state):raise AlphaError('This rewrite is stale or unavailable.',409)
                result=row[0];draft=result['draft'];variant=self._draft(state,{'variantId':draft['id'],'variantRevision':draft['revision']}) if draft.get('id') else None
                if not variant or variant['text']!=result['original'] or not self._draft_matches(state,draft):raise AlphaError('Save this draft before accepting changes.',409)
                selected=payload.get('changeIds',[])
                if not selected:raise AlphaError('Select at least one sentence change.')
                text=rewrite.apply(result['original'],result['changes'],selected)
                # Facts still go through the existing source/publication policy. They never silently become approved.
                used={i for c in result['changes'] if c['id'] in selected for i in c['usesFacts']}
                if used:
                    self.hosted.commands(state,principal,'source',{'kind':'text','title':'Post Doctor creator facts','text':'\n'.join(result['facts'][i] for i in sorted(used))})
                    fact_source=state['sources'][-1]
                    target=next(v for v in state['variants'] if v['id']==draft['id'])
                    target.setdefault('sourceIds',[]).append(fact_source['id'])
                    response['factsNeedApproval']=True
                self.hosted.commands(state,principal,'variant_edit',{'variantId':draft['id'],'variantRevision':draft['revision'],'text':text})
                target=next(v for v in state['variants'] if v['id']==draft['id'])
                target['needsReview']=True
                if result.get('missingFacts'):
                    target['unknowns']=list(dict.fromkeys([*target.get('unknowns',[]),*result['missingFacts']]))
                target['postDoctorAccepted']={'runId':payload['rewriteId'],'changeIds':selected,'textDigest':digest(text),
                                            'goal':result['after'].get('goal'),'contextDigest':result['after'].get('contextDigest'),'comparison':result.get('comparison')}
                # Only a full exact rechecked rewrite can carry its recheck to publication. Partial edits need a fresh check.
                if set(selected)=={c['id'] for c in result['changes']}:
                    target['postDoctor']=prediction(result['after'],payload['rewriteId'],target['revision'],text,comparison=result.get('comparison'),accepted_change_ids=selected)
                else:target.pop('postDoctor',None)
                cur.execute('UPDATE public.pr_post_doctor_runs SET accepted_changes=%s::jsonb WHERE workspace_id=%s AND id::text=%s',(json.dumps(selected),workspace_id,payload['rewriteId']))
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),workspace_id))
                audit(cur,workspace_id,principal,'postdoctor.changes_accepted',payload['rewriteId'],{'count':len(selected)})
            elif action=='post_doctor_feedback':
                if type(payload.get('helpful')) is not bool:raise AlphaError('Choose useful or not useful.')
                cur.execute('UPDATE public.pr_post_doctor_runs SET helpful=%s WHERE workspace_id=%s AND id::text=%s RETURNING id::text',(payload['helpful'],workspace_id,payload.get('runId')))
                if not cur.fetchone():raise AlphaError('Check unavailable.',404)
            elif action=='share_card_create':
                active=current_genome(state)
                if not active or payload.get('genomeId')!=active.get('id') or payload.get('confirmed') is not True:
                    raise AlphaError('Review and confirm labels from your approved Genome.',409)
                ids=payload.get('statementIds')
                if not isinstance(ids,list) or not 1<=len(ids)<=6 or len(set(ids))!=len(ids):raise AlphaError('Select 1–6 distinct labels to share.')
                labels={s['id']:s['label'] for s in active['statements'] if s['grade']!='conflicting'}
                if not set(ids)<=labels.keys():raise AlphaError('Choose available, non-conflicting Genome labels.')
                raw=secrets.token_urlsafe(32);card_id=str(uuid.uuid4())
                cur.execute('INSERT INTO public.pr_share_cards(id,workspace_id,genome_id,token_hash,labels,created_by) VALUES(%s,%s,%s,%s,%s::jsonb,%s)',(card_id,workspace_id,active['id'],hashlib.sha256(raw.encode()).hexdigest(),json.dumps([labels[i] for i in ids]),principal))
                response.update(shareId=card_id,path='/dna/'+raw)
                audit(cur,workspace_id,principal,'genome.share_created',card_id,{'labelCount':len(ids)})
            elif action=='share_card_revoke':
                cur.execute('UPDATE public.pr_share_cards SET revoked_at=coalesce(revoked_at,now()) WHERE workspace_id=%s AND id::text=%s RETURNING id::text',(workspace_id,payload.get('shareId')))
                if not cur.fetchone():raise AlphaError('Share card unavailable.',404)
        result=self.repository.command(workspace_id,token,revision,command,requirement='owner' if action in ('growth_consent','genome_approve','genome_restore','share_card_create','share_card_revoke') else 'edit',after=after)
        return {**self.hosted._present(result),**response}

    def invalidate(self,cur,workspace_id,before,after,principal):
        self.radar.invalidate(cur,workspace_id,before,after,principal)
        if context_fingerprint(before)!=context_fingerprint(after):
            removed=False
            for variant in after.get('variants',[]):
                if (variant.get('postDoctor') or {}).get('questionSet')=='postdoctor.v2':
                    variant.pop('postDoctor',None);removed=True
                if (variant.get('postDoctorAccepted') or {}).get('goal') is not None:
                    variant.pop('postDoctorAccepted',None);removed=True
            if removed:
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(after),workspace_id))
        changed=[]
        for old in before.get('sources',[]):
            if old.get('kind')!='voice_sample':continue
            new=next((s for s in after.get('sources',[]) if s['id']==old['id']),{})
            if any(old.get(k)!=new.get(k) for k in ('active','revision','selected','useGrants')):changed.append(old['id'])
        if not changed and before.get('growthConsent')==after.get('growthConsent'):return
        # This effect is also safe before the additive migration is applied.
        cur.execute("SELECT to_regclass('public.pr_post_history')")
        if cur.fetchone()[0] is None:return
        if changed:cur.execute('DELETE FROM public.pr_post_history WHERE workspace_id=%s AND source_id=ANY(%s)',(workspace_id,changed))
        cur.execute("UPDATE public.pr_genome_versions SET status='stale' WHERE workspace_id=%s",(workspace_id,))
        cur.execute('UPDATE public.pr_share_cards SET revoked_at=coalesce(revoked_at,now()) WHERE workspace_id=%s',(workspace_id,))
        cur.execute("SELECT to_regclass('public.pr_audience_clusters')")
        if cur.fetchone()[0] is not None and before.get('growthConsent')!=after.get('growthConsent'):
            cur.execute('DELETE FROM public.pr_audience_clusters WHERE workspace_id=%s',(workspace_id,))
            cur.execute('DELETE FROM public.pr_comment_judgments WHERE workspace_id=%s',(workspace_id,))
            cur.execute("UPDATE public.pr_post_doctor_runs SET body='{}',status='cancelled' WHERE workspace_id=%s AND kind='audience'",(workspace_id,))

    def share(self,token):
        self.gate('genome')
        if not isinstance(token,str) or not 32<=len(token)<=100:raise AlphaError('Content DNA unavailable.',404)
        with self.hosted.connection_factory() as db,db.cursor() as cur:
            cur.execute("SELECT c.labels,g.body,w.state FROM public.pr_share_cards c JOIN public.pr_workspaces w ON w.id=c.workspace_id JOIN public.pr_genome_versions g ON g.id=c.genome_id WHERE c.token_hash=%s AND c.revoked_at IS NULL AND g.status<>'stale' AND NOT(w.state ? 'accountDeletion')",(hashlib.sha256(token.encode()).hexdigest(),))
            row=cur.fetchone()
        if not row or not bindings_current(row[2],row[1].get('evidenceBindings',[])) or not postmortem.bindings_current(row[2],row[1].get('outcomeBindings',[])) or row[1].get('consentDigest')!=digest(row[2].get('growthConsent')):
            raise AlphaError('Content DNA unavailable.',404)
        return {'labels':row[0],'description':'Creator-selected writing labels. No private post text or performance figures.'}

    def public_check(self,body,ip):
        self.gate('public')
        if body.get('confirmed') is not True:raise AlphaError('Allow this draft to be analyzed by Rafii’s AI routes.')
        secret=self.env.get('POSTRIFF_PUBLIC_HASH_KEY','')
        if len(secret)<32:raise AlphaError('Public checks are not configured.',503)
        draft=self._draft({},body);subject=hmac.new(secret.encode(),str(ip).encode(),hashlib.sha256).hexdigest()
        with self.hosted.connection_factory() as db,db.cursor() as cur:
            self.reserve(cur,'global',RESERVATIONS['public'],self.cap('POSTRIFF_GROWTH_DAILY_USD_CAP'),10000)
            self.reserve(cur,'public',RESERVATIONS['public'],self.cap('POSTRIFF_PUBLIC_DAILY_USD_CAP'),10000)
            self.reserve(cur,'public:'+subject,RESERVATIONS['public'],3*RESERVATIONS['public'],3)
            check_id=str(uuid.uuid4())
            cur.execute('INSERT INTO public.pr_public_checks(id,subject_hash) VALUES(%s,%s)',(check_id,subject))
        sink=MemoryUsageSink();result=None;error=None
        try:result=public_result(self._check(self._router(sink),None,{},draft,[]))
        except Exception as caught:error=caught
        with self.hosted.connection_factory() as db,db.cursor() as cur:
            for event in sink.events:PostgresUsageSink(cur).record(event)
            cur.execute('UPDATE public.pr_public_checks SET status=%s,result=%s::jsonb WHERE id=%s',('failed' if error else 'completed',json.dumps(result or {}),check_id))
        if error:raise AlphaError('Post Doctor is temporarily unavailable.',503)
        return result

    def feedback(self,workspace_id,token,job_id):
        self.session(token);self.gate('check')
        with self.repository.transaction(token,workspace_id) as (cur,row,_):
            jobs=[j for j in row[1].get('phase2',{}).get('jobs',[]) if j.get('state')=='verified' and j.get('verification') and j.get('providerReference')]
            selected=next((j for j in jobs if j['id']==job_id),None)
            if not selected:return {'status':'unavailable','reason':'publication_not_verified','readings':[]}
            posts=[]
            for job in jobs:
                m=job.get('manifest') or {}
                posts.append({'id':job['id'], 'jobId':job['id'], 'platform':m.get('platform'),'connectionId':m.get('channelId'),'providerPostId':str(job['providerReference']),
                              'provider':{'Threads':'threads','Instagram':'instagram'}.get(m.get('platform')),'language':m.get('payload',{}).get('language'),
                              'format':m.get('contentType',{}).get('formatId','text'),'timeBucket':'unknown', 'officialOrigin': performance.official_job(job)})
            posts=performance.attach_readings(cur,workspace_id,posts);post=next(p for p in posts if p['id']==job_id)
            cur.execute('SELECT body FROM public.pr_predictions WHERE workspace_id=%s AND job_id=%s',(workspace_id,job_id));prediction=cur.fetchone()
            return {'status':'observed' if post.get('readings') else 'unavailable','prediction':prediction[0] if prediction else None,
                    'readings':[performance.compare(post,posts,h) for h in performance.HORIZONS],
                    'notice':'Observed outcomes are associations. No Genome rule changes without your approval.'}

    def sweep(self):
        with self.hosted.connection_factory() as db,db.cursor() as cur:
            cur.execute("SELECT to_regclass('public.pr_public_checks')")
            if cur.fetchone()[0] is None:return {'status':'not_migrated'}
            cur.execute('DELETE FROM public.pr_public_checks WHERE id IN (SELECT id FROM public.pr_public_checks WHERE expires_at<=now() LIMIT 500)')
            public=cur.rowcount
            cur.execute('DELETE FROM public.pr_post_doctor_runs WHERE id IN (SELECT id FROM public.pr_post_doctor_runs WHERE expires_at<=now() LIMIT 500)')
            cur.execute("DELETE FROM public.pr_growth_budgets WHERE (scope,day) IN (SELECT scope,day FROM public.pr_growth_budgets WHERE day<current_date-interval '30 days' LIMIT 500)")
            cur.execute("SELECT to_regclass('public.pr_postmortems')")
            if cur.fetchone()[0] is not None:
                for table in ('pr_postmortems','pr_audience_clusters'):
                    cur.execute(f'DELETE FROM public.{table} WHERE id IN (SELECT id FROM public.{table} WHERE expires_at<=now() LIMIT 500)')
                cur.execute('DELETE FROM public.pr_comment_judgments WHERE (workspace_id,thread_id) IN (SELECT workspace_id,thread_id FROM public.pr_comment_judgments WHERE expires_at<=now() LIMIT 500)')
                cur.execute("UPDATE public.pr_post_doctor_runs SET body='{}',status='cancelled' WHERE id IN (SELECT id FROM public.pr_post_doctor_runs WHERE kind='audience' AND created_at<now()-interval '90 days' AND body<>'{}'::jsonb LIMIT 500)")
        return {'status':'complete','publicChecksRemoved':public}
