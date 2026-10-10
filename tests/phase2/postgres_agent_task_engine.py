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
            return executor.claim_next(cur,self.service.ideas,workspace_id=self.w,executor=executor_kind,principal=actor,task_id=t['taskId'],seconds_left=240,owner='req:'+uuid.uuid4().hex)

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

if __name__=='__main__':unittest.main(verbosity=2)
