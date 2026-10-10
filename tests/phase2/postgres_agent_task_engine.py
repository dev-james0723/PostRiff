"""Real PostgreSQL CF3 lifecycle, isolation, leases, checkpoints and receipts.

No live providers, model calls, OAuth, production flags or production migrations.
"""
import json
import os
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.agent_runtime_v2.task_engine import actions, authz_seam, checkpoints, executor, flags, model, receipts, revocation, store, views
from postriff_phase2.agent_runtime_v2 import task_state

ROOT=Path(__file__).resolve().parents[2]
DSN=os.environ.get('POSTRIFF_TEST_DSN','host=127.0.0.1 port=55438 dbname=postgres')
A='00000000-0000-0000-0000-00000000d101'; B='00000000-0000-0000-0000-00000000d102'; C='00000000-0000-0000-0000-00000000d103'
TOKENS={'owner-task-token-000000000000':A,'editor-task-token-000000000000':B,'other-task-token-000000000000':C}
OWNER,EDITOR,OTHER=TOKENS

def connect():return psycopg.connect(DSN,client_encoding='utf8')
def verify(token):return TOKENS[token]

class TaskEnginePG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect() as db:
            db.execute((ROOT/'migrations/postriff/108_agent_tasks.sql').read_text())
            db.execute((ROOT/'migrations/postriff/108_agent_tasks.sql').read_text())
            for uid in (A,B,C):db.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING',(uid,))
        cls.service=HostedWorkspaceService(connect,verify)
        cls.w=cls.service.bootstrap(OWNER,'studio')['workspaceId'];cls.w2=cls.service.bootstrap(OTHER,'studio')['workspaceId']
        cls.service.bootstrap(EDITOR,'studio')
        with connect() as db:
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active') ON CONFLICT(workspace_id,user_id) DO UPDATE SET status='active',role='editor'",(cls.w,B))
        cls.env=patch.dict(os.environ,{'RAFII_AGENT_V2_ENABLED':'1','RAFII_TASK_ENGINE_ENABLED':'1','RAFII_TASK_ENGINE_AUTHORITATIVE':'1','RAFII_TASK_ENGINE_WORKSPACES':cls.w})
        cls.env.start()
        cls.runtime=SimpleNamespace(service=cls.service,cfg=None,clock=time.time,cancel_running=lambda *a,**k:None)

    @classmethod
    def tearDownClass(cls):cls.env.stop()

    def create(self, steps=None, actor=A, key=None):
        with store.service_tx(self.service,self.w) as cur:
            cur.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'CF3 test') RETURNING id::text",(self.w,actor));conv=cur.fetchone()[0]
            t,_=store.create_task(cur,self.service.ideas,workspace_id=self.w,conversation_id=conv,created_by=actor,origin='chat',title='Engine test',request_key=key or 'request-'+uuid.uuid4().hex,payload={'purpose':'test'},steps=steps or [{'label':'Read memory','kind':'tool','capabilityId':'memory_context','inputs':{}}],trace_id='trace_'+uuid.uuid4().hex)
            return t

    def claim(self,t,executor_kind='inline',actor=A):
        with store.service_tx(self.service,self.w) as cur:
            return executor.claim_next(cur,self.service.ideas,workspace_id=self.w,executor=executor_kind,principal=actor,task_id=t['taskId'],seconds_left=240,owner=('cron:' if executor_kind == 'cron' else 'req:')+uuid.uuid4().hex)

    def test_01_create_request_replay_and_other_actor_conflict(self):
        t=self.create()
        with store.service_tx(self.service,self.w) as cur:
            found=store.existing_request(cur,self.w,t['requestKey'],A,model.request_digest(A,{'purpose':'test'}))
            self.assertEqual(found['taskId'],t['taskId'])
            with self.assertRaises(AlphaError):store.existing_request(cur,self.w,t['requestKey'],B,model.request_digest(B,{'purpose':'test'}))

    def test_02_claim_contention_and_actor(self):
        t=self.create(); self.assertIsNone(self.claim(t,actor=B))
        c=self.claim(t); self.assertIsNotNone(c); self.assertIsNone(self.claim(t))
        with connect() as db:self.assertEqual(db.execute('SELECT actor::text FROM public.pr_agent_step_attempts WHERE id=%s',(c.attempt_id,)).fetchone()[0],A)

    def test_03_nonbackground_never_cron(self):
        t=self.create();self.assertIsNone(self.claim(t,'cron',None))

    def test_04_disabled_never_claimed(self):
        t=self.create()
        with patch.dict(os.environ,{'RAFII_TASK_ENGINE_AUTHORITATIVE':'0'}):self.assertIsNone(self.claim(t))

    def test_05_finish_isolated_and_verified(self):
        t=self.create();c=self.claim(t)
        out=executor.finish(self.runtime,c,{'ok':True,'verified':True})
        self.assertEqual(out['state'],'completed')
        with connect() as db:self.assertEqual(db.execute('SELECT status FROM public.pr_agent_runs WHERE id=%s',(t['taskId'],)).fetchone()[0],'completed')

    def test_06_losing_producer_writes_nothing(self):
        t=self.create();c=self.claim(t)
        with connect() as db:db.execute("UPDATE public.pr_agent_step_attempts SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(c.attempt_id,))
        self.assertEqual(executor.finish(self.runtime,c,{'ok':True,'verified':True})['state'],'lease_lost')

    def test_07_owner_cancel_editor_refused(self):
        t=self.create()
        with self.assertRaises(AlphaError) as e:actions.cancel(self.runtime,self.w,EDITOR,t['taskId'],{'idempotencyKey':'cancel-editor-00000000'})
        self.assertEqual(e.exception.status,403)
        out=actions.cancel(self.runtime,self.w,OWNER,t['taskId'],{'idempotencyKey':'cancel-owner-'+uuid.uuid4().hex})
        self.assertEqual(out['state'],'cancelled')

    def test_08_checkpoint_private_creator_hash_and_version(self):
        t=self.create()
        with store.service_tx(self.service,self.w) as cur:
            cp=checkpoints.store_run(cur,self.service.ideas,t,'private saved state',[],writer_model=None,stored_at=time.time())
            self.assertIsNone(checkpoints.claim(cur,self.w,t['taskId'],B,'req:other'))
            claim=checkpoints.claim(cur,self.w,t['taskId'],A,'req:owner');self.assertEqual(claim[0],cp)
            checkpoints.release(cur,cp)
            cur.execute("UPDATE public.pr_agent_checkpoints SET runtime_version='old' WHERE id=%s",(cp,))
            self.assertIsNone(checkpoints.claim(cur,self.w,t['taskId'],A,'req:again'))
            cur.execute('SELECT state,payload FROM public.pr_agent_checkpoints WHERE id=%s',(cp,));self.assertEqual(cur.fetchone(),('discarded',{}))

    def test_09_checkpoint_claim_expiry_releases(self):
        t=self.create()
        with store.service_tx(self.service,self.w) as cur:
            cp=checkpoints.store_run(cur,self.service.ideas,t,'state',[],writer_model=None,stored_at=time.time())
            checkpoints.claim(cur,self.w,t['taskId'],A,'req:owner')
            cur.execute("UPDATE public.pr_agent_checkpoints SET claim_expires_at=now()-interval '1 second' WHERE id=%s",(cp,))
            self.assertEqual(checkpoints.sweep(cur,self.w)['released'],1)
            self.assertIsNotNone(checkpoints.available(cur,self.w,t['taskId']))

    def test_10_redacted_anchor_and_foreign_task_hidden(self):
        t=self.create([{'label':'Private step','kind':'model','outputs':[{'text':'private'}],'entities':[{'id':'secret'}],'reason':'private reason'}])
        with store.service_tx(self.service,self.w) as cur:
            task=store.load_task(cur,self.w,t['taskId']);s=store.load_steps(cur,self.w,t['taskId'])
            store.mirror_anchor(cur,task,s)
            cur.execute('SELECT artifact FROM public.pr_agent_runs WHERE id=%s',(t['taskId'],));a=cur.fetchone()[0]
            for key in ('outputs','entities','reason','approvals'):self.assertNotIn(key,a['task']['steps'][0])
            self.assertNotIn('pendingRun',a);self.assertIsNone(store.load_task(cur,self.w2,t['taskId']))

    def test_11_receipt_recovery_no_duplicate_domain_effect(self):
        t=self.create();c=self.claim(t);key=model.effect_key(t['taskId'],'s1',1)
        with store.service_tx(self.service,self.w) as cur:
            s=store.load_step(cur,self.w,t['taskId'],'s1');store.set_step(cur,s,effect_key=key)
            store.receipt_begin(cur,t,s,c.attempt_id,c.trace_id)
            cur.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{engineReceiptTest}', '1') WHERE id=%s",(self.w,))
            store.receipt_done(cur,self.w,key,outcome='applied',verified=True,result={'checks':[{'name':'domain','ok':True}]})
            cur.execute("UPDATE public.pr_agent_step_attempts SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(c.attempt_id,))
        self.assertEqual(executor._reap_one(self.runtime,self.w,c.attempt_id),'completedFromReceipt')
        with connect() as db:self.assertEqual(db.execute("SELECT state->'engineReceiptTest' FROM public.pr_workspaces WHERE id=%s",(self.w,)).fetchone()[0],1)

    def test_12_revocation_discards_checkpoint(self):
        t=self.create()
        with store.service_tx(self.service,self.w) as cur:
            checkpoints.store_run(cur,self.service.ideas,t,'state',[],writer_model=None,stored_at=time.time())
            event=SimpleNamespace(workspace_id=self.w,user_id=A,denied_now={'tool.memory_context'},token_after='b'*64,reason='permissions_changed')
            revocation.approvals(cur,event);revocation.tasks(cur,event)
            s=store.load_step(cur,self.w,t['taskId'],'s1');self.assertEqual((s['state'],s['reasonCode']),('blocked','permission_revoked'))
            self.assertIsNone(checkpoints.available(cur,self.w,t['taskId']))

    def test_13_shadow_preserves_anchor(self):
        with patch.dict(os.environ,{'RAFII_TASK_ENGINE_AUTHORITATIVE':'0'}):
            t=self.create()
            with store.service_tx(self.service,self.w) as cur:
                cur.execute('SELECT artifact,status FROM public.pr_agent_runs WHERE id=%s',(t['taskId'],));before=cur.fetchone()
                s=store.load_step(cur,self.w,t['taskId'],'s1');store.set_step(cur,s,state='completed',verified=True)
                store.refresh(cur,self.service.ideas,t)
                cur.execute('SELECT artifact,status FROM public.pr_agent_runs WHERE id=%s',(t['taskId'],));self.assertEqual(cur.fetchone(),before)

    def test_14_expiry_closes_work(self):
        t=self.create()
        with store.service_tx(self.service,self.w) as cur:
            cur.execute("UPDATE public.pr_agent_tasks SET expires_at=now()-interval '1 second' WHERE id=%s",(t['taskId'],))
            executor.expire_task(cur,self.service.ideas,self.w,t['taskId'])
            self.assertEqual(store.load_task(cur,self.w,t['taskId'])['state'],'cancelled')

    def test_15_cancelled_external_observer_is_read_only_and_unbudgeted(self):
        job='job-'+uuid.uuid4().hex
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            state.setdefault('phase2',{}).setdefault('jobs',[]).append({'id':job,'state':'uncertain'})
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.w))
        t=self.create([{'label':'Observe approved publish','kind':'delegate','delegate':{'type':'publish_job','id':job}}])
        actions.cancel(self.runtime,self.w,OWNER,t['taskId'],{'idempotencyKey':'cancel-observer-'+uuid.uuid4().hex})
        with connect() as db:db.execute('UPDATE public.pr_agent_tasks SET attempts_left=0 WHERE id=%s',(t['taskId'],))
        self.assertEqual(self.claim(t,'cron',None),'handled')
        with connect() as db:
            verdict=db.execute('SELECT authz_verdict FROM public.pr_agent_step_attempts WHERE task_id=%s ORDER BY started_at DESC LIMIT 1',(t['taskId'],)).fetchone()[0]
            self.assertEqual(verdict,'observe')
            self.assertEqual(db.execute('SELECT attempts_left,state FROM public.pr_agent_tasks WHERE id=%s',(t['taskId'],)).fetchone(),(0,'queued'))
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            next(j for j in state['phase2']['jobs'] if j['id']==job)['state']='verified'
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.w))
            db.execute('UPDATE public.pr_agent_steps SET next_attempt_at=now() WHERE task_id=%s',(t['taskId'],))
        self.assertEqual(self.claim(t,'cron',None),'handled')
        with connect() as db:self.assertEqual(db.execute('SELECT state,partial FROM public.pr_agent_tasks WHERE id=%s',(t['taskId'],)).fetchone(),('cancelled',True))

    def test_16_concurrent_turn_admission_one_conversation(self):
        from concurrent.futures import ThreadPoolExecutor
        from postriff_phase2.agent_runtime_v2.task_engine import turns
        from postriff_phase2.agent_runtime_v2.service import _same_turn_request
        key='admission-'+uuid.uuid4().hex;payload={'message':'read','idempotencyKey':key}
        def admit():
            with turns.admit(self.runtime,self.w,OWNER,payload):
                with self.service.repository.transaction(OWNER,self.w) as (cur,row,principal):
                    cur.execute('SELECT id::text FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key=%s',(self.w,key));prior=cur.fetchone()
                    if prior:
                        _same_turn_request(cur,self.w,prior[0],principal,'read');return prior[0]
                    cur.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'Admission race') RETURNING id::text",(self.w,A));conv=cur.fetchone()[0]
                    run=store.new_anchor(cur,self.service.ideas,self.w,conv,A,'Admission','trace_'+uuid.uuid4().hex)
                    cur.execute('UPDATE public.pr_agent_runs SET idempotency_key=%s WHERE id=%s',(key,run));turns.record(cur,run)
                turns.release()
                return run
        with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(lambda _:admit(),range(2)))
        self.assertEqual(ids[0],ids[1])
        with connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM public.pr_conversations WHERE workspace_id=%s AND title='Admission race'",(self.w,)).fetchone()[0],1)
        with turns.admit(self.runtime,self.w,EDITOR,payload):
            with self.service.repository.transaction(EDITOR,self.w) as (cur,_row,p):
                with self.assertRaises(AlphaError):_same_turn_request(cur,self.w,ids[0],p,'read')

    def test_17_bound_paid_reservation_ceiling_identity_and_settlement(self):
        from postriff_phase2.agent_runtime_v2.task_engine.spend import TaskLedger
        from consumer_fixtures import approve_budgets
        approve_budgets(connect,self.w)
        t=self.create();c=self.claim(t);key=model.effect_key(t['taskId'],'s1',1)
        b={'workspaceId':self.w,'principal':A,'taskId':t['taskId'],'stepKey':'s1','attemptId':c.attempt_id,'attemptNo':1,'effectKey':key,'traceId':c.trace_id}
        ledger=TaskLedger(self.service.ledger,b)
        with store.service_tx(self.service,self.w) as cur:
            cur.execute('UPDATE public.pr_agent_tasks SET budget_ceiling_usd_micro=9 WHERE id=%s',(t['taskId'],))
            with self.assertRaises(AlphaError) as e:ledger.reserve(cur,self.w,A,'text_model',10,'original-key',charge_batch=False,provider='test',model='test')
            self.assertEqual(e.exception.code,'budget_ceiling')
            cur.execute('UPDATE public.pr_agent_tasks SET budget_ceiling_usd_micro=100 WHERE id=%s',(t['taskId'],))
            reservation=ledger.reserve(cur,self.w,A,'text_model',10,'original-key',charge_batch=False,provider='test',model='test')
            cur.execute("SELECT run_id,job_id,idempotency_key FROM public.pr_usage_ledger WHERE id::text=%s",(reservation['reservationId'],));r=cur.fetchone()
            self.assertEqual(tuple(map(str,r)),(t['taskId'],c.attempt_id,key+':a1'))
            ledger.settle(cur,self.w,reservation['reservationId'],'completed',8)
            cur.execute('SELECT spent_usd_micro,spend_unknown FROM public.pr_agent_tasks WHERE id=%s',(t['taskId'],));self.assertEqual(cur.fetchone(),(8,False))


    def test_18_model_call_domain_receipt_replay_and_undo(self):
        from postriff_phase2.agent_runtime_v2 import domain_tools, tool_adapter
        from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
        campaign,draft=uuid.uuid4().hex,uuid.uuid4().hex
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            state.setdefault('variants',[]).append({'id':draft,'revision':1,'text':'Private draft','platform':'LinkedIn'})
            state.setdefault('raffi',{}).setdefault('campaignPlanning',{}).setdefault('campaigns',[]).append({'id':campaign,'goal':'Test linking','audience':'Test','createdBy':A,'createdAt':time.time(),'status':'draft','items':[],'facts':{},'version':1})
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.w))
        t=self.create([{'label':'Link a draft','kind':'model'}])
        with store.service_tx(self.service,self.w) as cur:
            plan=task_state.load(cur,self.w,t['taskId']);member=authz_seam.membership(cur,self.w,A)
        ctx=RafiiRunContext(self.service,self.w,OWNER,A,member,t['conversationId'],'trace_'+uuid.uuid4().hex,task=plan,request_text='Link this draft to this campaign')
        ctx.ledger.reference('campaign',campaign);ctx.ledger.reference('draft',draft)
        domain_tools.ensure_registered();args={'stepId':'s1','campaignId':campaign,'draftIds':[draft]}
        from postriff_phase2.agent_runtime_v2.task_engine.model_calls import dispatch
        first=dispatch(ctx,tool_adapter.REGISTRY['campaign_link'],args)
        self.assertTrue(first.get('verified'),first)
        second=tool_adapter.execute(ctx,tool_adapter.REGISTRY['campaign_link'],args)
        self.assertTrue(second.get('replayed'),second)
        with store.service_tx(self.service,self.w) as cur:
            cur.execute('SELECT count(*) FROM public.pr_agent_step_attempts WHERE task_id=%s',(t['taskId'],));self.assertEqual(cur.fetchone()[0],1)
            cur.execute('SELECT id::text FROM public.pr_agent_compensations WHERE task_id=%s',(t['taskId'],));comp=cur.fetchone()[0]
        undone=actions.undo(self.runtime,self.w,OWNER,t['taskId'],'s1',{'compensationId':comp,'idempotencyKey':'undo-'+uuid.uuid4().hex})
        self.assertTrue(undone['verified'])
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            self.assertEqual(next(c for c in state['raffi']['campaignPlanning']['campaigns'] if c['id']==campaign)['items'],[])

    def test_19_model_approval_does_not_cover_changed_inputs(self):
        from postriff_phase2.agent_runtime_v2.task_engine import approvals
        t=self.create([{'label':'Review a call','kind':'model'}])
        with store.service_tx(self.service,self.w) as cur:
            step=store.load_step(cur,self.w,t['taskId'],'s1')
            subject={**step,'kind':'tool','capabilityId':'memory_context','inputs':{'layers':['task']},'inputDigest':model.input_digest('memory_context',{'layers':['task']})}
            aid=approvals.request_approval(cur,self.service.ideas,t,subject,None)
            approval=store.load_approval(cur,self.w,aid)
            store.close_approval(cur,approval,'approved',surface='task_center',decided_by=A,decision_key='decision-'+uuid.uuid4().hex,outcome={})
            self.assertIsNotNone(executor._approval_evidence(cur,t,subject))
            self.assertIsNone(executor._approval_evidence(cur,t,{**subject,'inputDigest':model.input_digest('memory_context',{'layers':['identity']})}))
            self.assertIsNone(executor._approval_evidence(cur,t,{**subject,'capabilityId':'campaign_get'}))

    def test_20_native_spend_approval_amount_and_surface_boundary(self):
        from postriff_phase2.agent_runtime_v2.task_engine import approvals
        t=self.create()
        with store.service_tx(self.service,self.w) as cur:
            step=store.load_step(cur,self.w,t['taskId'],'s1')
            verdict=authz_seam.StepVerdict('approve','spend','budget','cost_limit',t['authzToken'])
            aid=approvals.request_approval(cur,self.service.ideas,t,step,verdict,spend_limit=25)
            approval=store.load_approval(cur,self.w,aid)
            cur.execute('UPDATE public.pr_agent_tasks SET budget_ceiling_usd_micro=10 WHERE id=%s',(t['taskId'],))
        payload={'decision':'approve','digest':approval['digest'],'idempotencyKey':'spend-'+uuid.uuid4().hex}
        for surface in ('text','voice'):
            result=approvals.resolve_approval(self.runtime,self.w,OWNER,aid,payload,surface=surface)
            self.assertEqual(result['outcome'],'needs_panel_confirmation')
        with patch.object(executor,'drive_inline',return_value=[]):
            result=approvals.resolve_approval(self.runtime,self.w,OWNER,aid,payload)
        self.assertEqual(result['state'],'approved')
        with connect() as db:self.assertEqual(db.execute('SELECT budget_ceiling_usd_micro FROM public.pr_agent_tasks WHERE id=%s',(t['taskId'],)).fetchone()[0],25)
        again=approvals.resolve_approval(self.runtime,self.w,OWNER,aid,payload)
        self.assertTrue(again['replayed'])

    def test_21_exhausted_task_fails_work_but_not_observers(self):
        t=self.create()
        with connect() as db:db.execute('UPDATE public.pr_agent_tasks SET attempts_left=0 WHERE id=%s',(t['taskId'],))
        self.assertIsNone(self.claim(t))
        with connect() as db:self.assertEqual(db.execute('SELECT state,reason_code FROM public.pr_agent_steps WHERE task_id=%s',(t['taskId'],)).fetchone(),('failed','retry_budget_exhausted'))

    def test_22_continuation_is_creator_owned_and_task_metered(self):
        from postriff_phase2.agent_runtime_v2.task_engine import continuations
        t=self.create([{'label':'Resume later','kind':'model','state':'blocked','reasonCode':'needs_conversation'}])
        self.assertIsNone(continuations.begin(self.runtime,self.w,EDITOR,t['taskId'],None,'trace_'+uuid.uuid4().hex))
        owned=continuations.begin(self.runtime,self.w,OWNER,t['taskId'],None,'trace_'+uuid.uuid4().hex)
        self.assertIsNotNone(owned)
        b,ledger=owned
        self.assertEqual(ledger.binding['taskId'],t['taskId'])
        with connect() as db:
            self.assertEqual(db.execute('SELECT actor::text,executor FROM public.pr_agent_step_attempts WHERE id=%s',(b['attemptId'],)).fetchone(),(A,'inline'))
            self.assertEqual(db.execute('SELECT attempts_left FROM public.pr_agent_tasks WHERE id=%s',(t['taskId'],)).fetchone()[0],23)
        continuations.finish(self.runtime,b,ok=True)
        with connect() as db:self.assertEqual(db.execute('SELECT state FROM public.pr_agent_steps WHERE id=%s',(b['stepId'],)).fetchone()[0],'completed')

    def test_23_e8_requester_creates_one_private_creator_approval(self):
        from postriff_phase2.agent_runtime_v2.task_engine import approvals
        from postriff_phase2.agent_runtime_v2 import capability_registry
        from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
        t=self.create([{'label':'Read after confirmation','kind':'model'}])
        with store.service_tx(self.service,self.w) as cur:
            plan=task_state.load(cur,self.w,t['taskId']);member=authz_seam.membership(cur,self.w,A)
        ctx=RafiiRunContext(self.service,self.w,OWNER,A,member,t['conversationId'],'trace_'+uuid.uuid4().hex,task=plan)
        cap=SimpleNamespace(name='memory_context',risk='R0',permission='read')
        decision=SimpleNamespace(reason='spend_confirmation',token=t['authzToken'])
        first=approvals.request_from_context(ctx,cap,{'stepId':'s1','layers':['task']},decision)
        second=approvals.request_from_context(ctx,cap,{'stepId':'s1','layers':['task']},decision)
        self.assertEqual(first['approvalId'],second['approvalId'])
        with store.service_tx(self.service,self.w) as cur:
            approval=store.load_approval(cur,self.w,first['approvalId'])
            self.assertEqual((approval['requestedFor'],approval['state']),(A,'pending'))
            self.assertEqual(approval['inputs'],{'layers':['task']})

    def test_24_released_reservation_frees_task_ceiling(self):
        from postriff_phase2.agent_runtime_v2.task_engine.spend import TaskLedger
        t=self.create();c=self.claim(t);key=model.effect_key(t['taskId'],'s1',1)
        b={'workspaceId':self.w,'principal':A,'taskId':t['taskId'],'stepKey':'s1','attemptId':c.attempt_id,'attemptNo':1,'effectKey':key,'traceId':c.trace_id}
        ledger=TaskLedger(self.service.ledger,b)
        with store.service_tx(self.service,self.w) as cur:
            cur.execute('UPDATE public.pr_agent_tasks SET budget_ceiling_usd_micro=10 WHERE id=%s',(t['taskId'],))
            first=ledger.reserve(cur,self.w,A,'text_model',10,'original',charge_batch=False,provider='test',model='test')
            ledger.settle(cur,self.w,first['reservationId'],'failed',None)
            cur.execute('SELECT cost_state FROM public.pr_agent_step_attempts WHERE id=%s',(c.attempt_id,));self.assertEqual(cur.fetchone()[0],'known')
            other=TaskLedger(self.service.ledger,{**b,'attemptNo':2})
            self.assertFalse(other.reserve(cur,self.w,A,'text_model',10,'second',charge_batch=False,provider='test',model='test')['duplicate'])

    def test_25_target_revision_drift_revokes_approval(self):
        from postriff_phase2.agent_runtime_v2.task_engine import approvals
        ident=uuid.uuid4().hex
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            state.setdefault('variants',[]).append({'id':ident,'revision':2,'text':'Changed elsewhere'})
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.w))
        t=self.create()
        with store.service_tx(self.service,self.w) as cur:
            step=store.load_step(cur,self.w,t['taskId'],'s1')
            aid=approvals.request_approval(cur,self.service.ideas,t,{**step,'targetRefs':[{'type':'draft','id':ident,'revision':1}]},None)
            approval=store.load_approval(cur,self.w,aid)
        with self.assertRaises(AlphaError) as e:
            approvals.resolve_approval(self.runtime,self.w,OWNER,aid,{'decision':'approve','digest':approval['digest'],'idempotencyKey':'drift-'+uuid.uuid4().hex})
        self.assertEqual(e.exception.code,'approval_stale')
        with connect() as db:self.assertEqual(db.execute('SELECT state,decision_surface FROM public.pr_agent_approvals WHERE id=%s',(aid,)).fetchone(),('revoked','system'))

    def test_26_revocation_finds_dynamic_model_capability(self):
        from postriff_phase2.agent_runtime_v2.task_engine import approvals
        t=self.create([{'label':'Dynamic call','kind':'model'}])
        with store.service_tx(self.service,self.w) as cur:
            step=store.load_step(cur,self.w,t['taskId'],'s1')
            subject={**step,'capabilityId':'memory_context','inputDigest':model.input_digest('memory_context',{}),'inputs':{}}
            aid=approvals.request_approval(cur,self.service.ideas,t,subject,None)
            checkpoints.store_run(cur,self.service.ideas,t,'private',[],writer_model=None,stored_at=time.time())
            event=SimpleNamespace(workspace_id=self.w,user_id=A,denied_now={'tool.memory_context'},token_after='c'*64,reason='permissions_changed')
            self.assertGreaterEqual(revocation.approvals(cur,event),1)
            self.assertGreaterEqual(revocation.tasks(cur,event),1)
            self.assertEqual(store.load_step(cur,self.w,t['taskId'],'s1')['reasonCode'],'permission_revoked')
            self.assertIsNone(checkpoints.available(cur,self.w,t['taskId']))

    def test_27_consumed_approval_authority_requires_exact_live_attempt(self):
        from postriff_phase2.agent_runtime_v2.task_engine import approvals
        t=self.create()
        with store.service_tx(self.service,self.w) as cur:
            step=store.load_step(cur,self.w,t['taskId'],'s1')
            aid=approvals.request_approval(cur,self.service.ideas,t,step,None)
            approval=store.load_approval(cur,self.w,aid)
            store.close_approval(cur,approval,'approved',surface='task_center',decided_by=A,decision_key='bound-'+uuid.uuid4().hex,outcome={})
            store.set_step(cur,step,state='queued',next_attempt_at=time.time())
            store.refresh(cur,self.service.ideas,t)
        c=self.claim(t)
        b={'workspaceId':self.w,'principal':A,'taskId':t['taskId'],'stepId':c.step['stepId'],'attemptId':c.attempt_id,'leaseOwner':c.lease_owner,'approvalId':aid}
        ctx=SimpleNamespace(step_binding=b,workspace_id=self.w,principal=A)
        cap=SimpleNamespace(name='memory_context')
        with store.service_tx(self.service,self.w) as cur:
            executor.consume_approval(cur,{'approvalId':aid})
            actor=approvals.resolve_bound_actor(cur,ctx,cap,{},time.time())
            self.assertEqual(actor.kind,'approval');self.assertEqual(actor.evidence['approval']['capabilityId'],'tool.memory_context')
            self.assertIsNone(approvals.resolve_bound_actor(cur,ctx,cap,{'layers':['identity']},time.time()))
            cur.execute("UPDATE public.pr_agent_step_attempts SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(c.attempt_id,))
            self.assertIsNone(approvals.resolve_bound_actor(cur,ctx,cap,{},time.time()))

    def test_28_native_model_approval_executes_stored_call_once(self):
        from postriff_phase2.agent_runtime_v2.task_engine import approvals
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            campaign=state['raffi']['campaignPlanning']['campaigns'][0]['id'];draft=state['variants'][0]['id']
        t=self.create([{'label':'Confirm campaign link','kind':'model'}])
        values={'campaignId':campaign,'draftIds':[draft]}
        with store.service_tx(self.service,self.w) as cur:
            step=store.load_step(cur,self.w,t['taskId'],'s1')
            subject={**step,'capabilityId':'campaign_link','inputDigest':model.input_digest('campaign_link',values),'inputs':values,'riskClass':'R1','targetRefs':[{'type':'campaign','id':campaign},{'type':'draft','id':draft}]}
            aid=approvals.request_approval(cur,self.service.ideas,t,subject,None)
            approval=store.load_approval(cur,self.w,aid)
        payload={'decision':'approve','digest':approval['digest'],'idempotencyKey':'model-approve-'+uuid.uuid4().hex}
        result=approvals.resolve_approval(self.runtime,self.w,OWNER,aid,payload)
        self.assertEqual(result['resumed'],'inline')
        with connect() as db:
            self.assertEqual(db.execute('SELECT state FROM public.pr_agent_approvals WHERE id=%s',(aid,)).fetchone()[0],'consumed')
            self.assertEqual(db.execute('SELECT state,verified FROM public.pr_agent_steps WHERE task_id=%s',(t['taskId'],)).fetchone(),('completed',True))
        again=approvals.resolve_approval(self.runtime,self.w,OWNER,aid,payload)
        self.assertTrue(again['replayed'])
        with connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM public.pr_agent_step_attempts WHERE task_id=%s',(t['taskId'],)).fetchone()[0],1)

    def test_29_cf2_ask_roundtrip_uses_consumed_live_attempt_authority(self):
        from postriff_phase2.agent_runtime_v2 import agent_permissions,authz,domain_tools,tool_adapter
        from postriff_phase2.agent_runtime_v2.task_engine import approvals
        from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
        cfg=SimpleNamespace(permissions_for=lambda _w:'enforce',task_engine_for=lambda _w:'on')
        runtime=SimpleNamespace(service=self.service,cfg=cfg,clock=time.time)
        approvals.install();self.assertTrue(authz.enforcement_ready())
        with self.service.repository.transaction(OWNER,self.w) as (cur,row,principal):
            agent_permissions.apply_decision(cur,workspace_id=self.w,principal=principal,member=self.service.ideas._member(row),state=self.service.ideas._state(row),token=OWNER,
                payload={'preset':'custom','scopes':{'capability:tool.campaign_link':'ask'},'expectedEpoch':0,'consentVersion':agent_permissions.CONSENT_VERSION,
                         'copyDigest':agent_permissions.COPY_DIGEST,'confirmed':True,'source':'settings','idempotencyKey':'ask-'+uuid.uuid4().hex},now=time.time(),mode='enforce')
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            campaign=state['raffi']['campaignPlanning']['campaigns'][0]['id'];draft=state['variants'][0]['id']
        t=self.create([{'label':'Ask before linking','kind':'model'}])
        with store.service_tx(self.service,self.w) as cur:plan=task_state.load(cur,self.w,t['taskId']);member=authz_seam.membership(cur,self.w,A)
        ctx=RafiiRunContext(self.service,self.w,OWNER,A,member,t['conversationId'],'trace_'+uuid.uuid4().hex,task=plan,config=cfg,request_text='Link draft to campaign')
        ctx.ledger.reference('campaign',campaign);ctx.ledger.reference('draft',draft)
        domain_tools.ensure_registered()
        result=tool_adapter.execute(ctx,tool_adapter.REGISTRY['campaign_link'],{'stepId':'s1','campaignId':campaign,'draftIds':[draft]})
        self.assertTrue(result.get('needsUser'),result)
        with store.service_tx(self.service,self.w) as cur:approval=store.approvals_for(cur,self.w,t['taskId'])[0]
        result=approvals.resolve_approval(runtime,self.w,OWNER,approval['approvalId'],{'decision':'approve','digest':approval['digest'],'idempotencyKey':'approved-'+uuid.uuid4().hex})
        self.assertEqual(result['resumed'],'inline',result)
        with connect() as db:
            self.assertEqual(db.execute('SELECT state,verified FROM public.pr_agent_steps WHERE task_id=%s',(t['taskId'],)).fetchone(),('completed',True))
            self.assertEqual(db.execute('SELECT state FROM public.pr_agent_approvals WHERE id=%s',(approval['approvalId'],)).fetchone()[0],'consumed')

    def test_30_draft_edit_and_conditional_restore_use_domain_revision(self):
        from postriff_phase2.agent_runtime_v2 import domain_tools, tool_adapter
        from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
        draft=uuid.uuid4().hex
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            state['variants'].append({'id':draft,'revision':1,'text':'Original text','platform':'LinkedIn','needsReview':False,
                'revisions':[{'revision':1,'text':'Original text'}]})
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.w))
        t=self.create([{'label':'Edit draft','kind':'model'}])
        with store.service_tx(self.service,self.w) as cur:
            plan=task_state.load(cur,self.w,t['taskId']);member=authz_seam.membership(cur,self.w,A)
        ctx=RafiiRunContext(self.service,self.w,OWNER,A,member,t['conversationId'],'trace_'+uuid.uuid4().hex,task=plan,request_text='Edit the draft')
        ctx.ledger.reference('draft',draft);domain_tools.ensure_registered()
        args={'stepId':'s1','draftId':draft,'revision':1,'text':'Revised text'}
        result=tool_adapter.execute(ctx,tool_adapter.REGISTRY['draft_edit'],args)
        self.assertTrue(result.get('verified'),result)
        self.assertTrue(tool_adapter.execute(ctx,tool_adapter.REGISTRY['draft_edit'],args).get('replayed'))
        with connect() as db:
            comp=db.execute('SELECT id::text FROM public.pr_agent_compensations WHERE task_id=%s',(t['taskId'],)).fetchone()[0]
        result=actions.undo(self.runtime,self.w,OWNER,t['taskId'],'s1',{'compensationId':comp,'idempotencyKey':'draft-undo-'+uuid.uuid4().hex})
        self.assertTrue(result['verified'])
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            saved=next(v for v in state['variants'] if v['id']==draft)
            self.assertEqual((saved['text'],saved['revision'],saved['needsReview']),('Original text',3,True))

    def test_31_trend_disable_atomic_inverse_preserves_identity_and_revision(self):
        from postriff_phase2.agent_runtime_v2 import domain_tools, tool_adapter
        from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
        from postriff_phase2.growth.trends.store import TrendStore
        from postriff_phase2.coworker.runtime import ensure
        with connect() as db:
            if not db.execute("SELECT to_regclass('public.pr_trend_watches')").fetchone()[0]:
                db.execute((ROOT/'migrations/postriff/040_social_trend_intelligence.sql').read_text())
        domain=TrendStore(connect)
        saved=domain.put_watch(self.w,A,{'trend_id':str(uuid.uuid4()),'platforms':['bluesky'],'threshold':'stage_change','notification_policy':'in_app'},idempotency_key='watch-'+uuid.uuid4().hex)
        t=self.create([{'label':'Disable watch','kind':'model'}])
        with store.service_tx(self.service,self.w) as cur:
            plan=task_state.load(cur,self.w,t['taskId']);member=authz_seam.membership(cur,self.w,A)
        ctx=RafiiRunContext(self.service,self.w,OWNER,A,member,t['conversationId'],'trace_'+uuid.uuid4().hex,task=plan,request_text='Disable this watch')
        domain_tools.ensure_registered();svc=ensure(self.service).coworker.trends
        with patch.object(svc,'values',{'RAFII_TREND_INTELLIGENCE_ENABLED':'1','RAFII_TREND_WORKSPACE_ALLOWLIST':self.w}):
            result=tool_adapter.execute(ctx,tool_adapter.REGISTRY['trend_watch_disable'],{'stepId':'s1','watch_id':saved['watch_id'],'expected_revision':1,'idempotency_key':'disable-'+uuid.uuid4().hex})
        self.assertTrue(result.get('verified'),result)
        with connect() as db:
            comp=db.execute('SELECT id::text FROM public.pr_agent_compensations WHERE task_id=%s',(t['taskId'],)).fetchone()[0]
            self.assertEqual(db.execute('SELECT enabled,revision FROM public.pr_trend_watches WHERE workspace_id=%s AND watch_id=%s',(self.w,saved['watch_id'])).fetchone(),(False,2))
        result=actions.undo(self.runtime,self.w,OWNER,t['taskId'],'s1',{'compensationId':comp,'idempotencyKey':'watch-undo-'+uuid.uuid4().hex})
        self.assertTrue(result['verified'])
        with connect() as db:
            self.assertEqual(db.execute('SELECT enabled,revision FROM public.pr_trend_watches WHERE workspace_id=%s AND watch_id=%s',(self.w,saved['watch_id'])).fetchone(),(True,3))
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_trend_watches WHERE workspace_id=%s AND idempotency_key=%s',(self.w,saved['idempotency_key'])).fetchone()[0],1)

    def test_32_live_approval_is_rechecked_between_e1_and_e2(self):
        from postriff_phase2.agent_runtime_v2 import authz,domain_tools,tool_adapter
        from postriff_phase2.agent_runtime_v2.task_engine import approvals
        from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
        cfg=SimpleNamespace(permissions_for=lambda _w:'enforce',task_engine_for=lambda _w:'on')
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            values={'campaignId':state['raffi']['campaignPlanning']['campaigns'][0]['id'],'draftIds':[state['variants'][0]['id']]}
        t=self.create([{'label':'Approved link','kind':'tool','capabilityId':'campaign_link','inputs':values}])
        with store.service_tx(self.service,self.w) as cur:
            step=store.load_step(cur,self.w,t['taskId'],'s1')
            aid=approvals.request_approval(cur,self.service.ideas,t,step,None)
            approval=store.load_approval(cur,self.w,aid)
            store.close_approval(cur,approval,'approved',surface='task_center',decided_by=A,decision_key='race-'+uuid.uuid4().hex,outcome={})
            store.set_step(cur,step,state='queued',next_attempt_at=time.time());store.refresh(cur,self.service.ideas,t)
        c=self.claim(t);self.assertIsNotNone(c)
        with store.service_tx(self.service,self.w) as cur:
            executor.consume_approval(cur,{'approvalId':aid});member=authz_seam.membership(cur,self.w,A)
        ctx=RafiiRunContext(self.service,self.w,OWNER,A,member,t['conversationId'],'trace_'+uuid.uuid4().hex,config=cfg)
        ctx.step_binding={'workspaceId':self.w,'principal':A,'taskId':t['taskId'],'stepId':c.step['stepId'],'attemptId':c.attempt_id,'leaseOwner':c.lease_owner,'approvalId':aid}
        domain_tools.ensure_registered();spec=tool_adapter.REGISTRY['campaign_link'].spec
        self.assertEqual(authz.evaluate_tool(ctx,spec,values).outcome,'allow')
        with connect() as db:db.execute("UPDATE public.pr_agent_step_attempts SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(c.attempt_id,))
        with authz.active_tool(ctx,spec,values):
            with self.assertRaises(AlphaError) as e:
                with self.service.repository.transaction(OWNER,self.w):
                    self.fail('Expired approval attempt reached a write transaction')
        self.assertEqual(e.exception.code,'agent_permission_revoked')

if __name__=='__main__':unittest.main(verbosity=2)
