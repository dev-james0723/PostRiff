"""Actual SQL creator admission/approval/projection; synthetic identity and outcomes, no provider calls."""
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
from postriff_phase2 import suggestions
from postriff_phase2.agent_runtime_v2 import creator_pipeline as pipeline
from postriff_phase2.agent_runtime_v2.task_engine import store, approvals, authz_seam, executor
ROOT=Path(__file__).resolve().parents[2]
A='00000000-0000-0000-0000-00000000e701'; B='00000000-0000-0000-0000-00000000e702'; C='00000000-0000-0000-0000-00000000e703'
TOKENS={'creator-owner-session-token':A,'creator-editor-session-token':B,'creator-other-session-token':C}
OWNER,EDITOR,OTHER=TOKENS

def connect(): return psycopg.connect(os.environ['POSTRIFF_TEST_DSN'], client_encoding='utf8')

class CreatorPG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect() as db:
            db.execute((ROOT/'migrations/postriff/108_agent_tasks.sql').read_text())
            for uid in (A,B,C):db.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING',(uid,))
        cls.service=HostedWorkspaceService(connect,lambda token:TOKENS[token])
        cls.w=cls.service.bootstrap(OWNER,'studio')['workspaceId'];cls.w2=cls.service.bootstrap(OTHER,'studio')['workspaceId'];cls.service.bootstrap(EDITOR,'studio')
        cls.env=patch.dict(os.environ,{'RAFII_AGENT_V2_ENABLED':'1','RAFII_TASK_ENGINE_ENABLED':'1','RAFII_TASK_ENGINE_AUTHORITATIVE':'1','RAFII_TASK_ENGINE_WORKSPACES':cls.w,'RAFII_AGENT_PERMISSIONS_MODE':'off'})
        cls.env.start();cls.runtime=SimpleNamespace(service=cls.service,cfg=None,clock=time.time)
    @classmethod
    def tearDownClass(cls):cls.env.stop()
    def setUp(self):
        with connect() as db:
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active') ON CONFLICT(workspace_id,user_id) DO UPDATE SET status='active',role='editor'",(self.w,B))
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            state.setdefault('raffi',{})['campaignPlanning']={'campaigns':[{'id':'campaign-'+uuid.uuid4().hex,'version':1,'goal':'Synthetic recital','audience':'Neighbours','facts':{'venue':'Studio'},'status':'draft','items':[]}]}
            state['raffi']['suggestions']=[]
            suggestion=suggestions.refresh(state,time.time())[0]
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),self.w))
        self.body={'suggestionId':suggestion['id'],'platforms':['Threads'],'budgetCeilingUsdMicro':0}
    def reviewed(self,token=OWNER):
        p=pipeline.preview(self.runtime,self.w,token,self.body)
        return {**self.body,'digest':p['digest'],'idempotencyKey':'creator-'+uuid.uuid4().hex}
    def create(self,token=OWNER):
        body=self.reviewed(token);return pipeline.create(self.runtime,self.w,token,body),body
    def test_exact_approval_zero_provider_dispatch_and_private_experiment(self):
        out,body=self.create()
        with connect() as db,db.cursor() as cur:
            task=store.load_task(cur,self.w,out['taskId']);steps=store.load_steps(cur,self.w,out['taskId']);apps=store.approvals_for(cur,self.w,out['taskId'])
            self.assertEqual(task['state'],'awaiting_approval');self.assertEqual(task['budgetCeilingUsdMicro'],0)
            self.assertEqual(steps[1]['inputs']['platforms'],['Threads']);self.assertEqual(apps[0]['inputDigest'],steps[1]['inputDigest'])
            self.assertEqual(apps[0]['summary']['source']['facts'],{'venue':'Studio'})
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_agent_step_attempts WHERE task_id=%s',(out['taskId'],)).fetchone()[0],0)
        mine=pipeline.listing(self.runtime,self.w,OWNER)['items'];self.assertTrue(any(t['taskId']==out['taskId'] for t in mine))
        self.assertFalse(any(t['taskId']==out['taskId'] for t in pipeline.listing(self.runtime,self.w,EDITOR)['items']))
    def test_same_key_reconciles_after_source_changes(self):
        out,body=self.create()
        with connect() as db:db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{raffi,campaignPlanning,campaigns}','[]'::jsonb) WHERE id=%s",(self.w,))
        self.assertEqual(pipeline.create(self.runtime,self.w,OWNER,body)['taskId'],out['taskId'])
        with self.assertRaises(AlphaError):pipeline.create(self.runtime,self.w,OWNER,{**body,'budgetCeilingUsdMicro':100})
    def test_changed_preview_is_409_no_task(self):
        body=self.reviewed()
        with connect() as db:db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{raffi,campaignPlanning,campaigns,0,facts,venue}','\"Changed\"'::jsonb) WHERE id=%s",(self.w,))
        with self.assertRaises(AlphaError) as e:pipeline.create(self.runtime,self.w,OWNER,body)
        self.assertEqual(e.exception.status,409)
        with connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM public.pr_agent_tasks WHERE request_key=%s',(body['idempotencyKey'],)).fetchone()[0],0)
    def test_duplicate_new_key_keeps_one_conversation_and_task(self):
        out,body=self.create()
        with connect() as db:before=db.execute('SELECT count(*) FROM public.pr_conversations WHERE workspace_id=%s',(self.w,)).fetchone()[0]
        with self.assertRaises(AlphaError) as e:pipeline.create(self.runtime,self.w,OWNER,{**body,'idempotencyKey':'creator-'+uuid.uuid4().hex})
        self.assertEqual(e.exception.code,'creator_task_exists')
        with connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM public.pr_conversations WHERE workspace_id=%s',(self.w,)).fetchone()[0],before)
    def test_role_demotion_and_foreign_scope(self):
        body=self.reviewed(EDITOR)
        with connect() as db:db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(self.w,B))
        for call in (lambda:pipeline.create(self.runtime,self.w,EDITOR,body),lambda:pipeline.listing(self.runtime,self.w,EDITOR),lambda:pipeline.preview(self.runtime,self.w,OTHER,self.body)):
            with self.assertRaises(AlphaError) as e:call()
            self.assertEqual(e.exception.status,403)
    def test_engine_off_and_agent_deny(self):
        with patch.dict(os.environ,{'RAFII_TASK_ENGINE_AUTHORITATIVE':'0'}):
            with self.assertRaises(AlphaError) as e:pipeline.preview(self.runtime,self.w,OWNER,self.body)
            self.assertEqual(e.exception.status,404)
        body=self.reviewed()
        denied=authz_seam.StepVerdict('deny',None,'permission_missing','category_off','0'*64)
        with patch.object(pipeline,'_verdict',return_value=denied):
            self.assertFalse(pipeline.preview(self.runtime,self.w,OWNER,self.body)['canCreate'])
            with self.assertRaises(AlphaError) as e:pipeline.create(self.runtime,self.w,OWNER,body)
            self.assertEqual(e.exception.status,403)
    def test_creator_only_exact_approval_text_refusal_and_decline(self):
        out,_=self.create()
        with connect() as db,db.cursor() as cur:app=store.approvals_for(cur,self.w,out['taskId'])[0]
        payload={'decision':'reject','digest':app['digest'],'idempotencyKey':'decline-'+uuid.uuid4().hex}
        with self.assertRaises(AlphaError):approvals.resolve_approval(self.runtime,self.w,EDITOR,app['approvalId'],payload)
        self.assertEqual(approvals.resolve_approval(self.runtime,self.w,OWNER,app['approvalId'],payload,surface='text')['outcome'],'needs_panel_confirmation')
        with self.assertRaises(AlphaError):approvals.resolve_approval(self.runtime,self.w,OWNER,app['approvalId'],{**payload,'digest':'f'*64})
        self.assertEqual(approvals.resolve_approval(self.runtime,self.w,OWNER,app['approvalId'],payload)['outcome'],'rejected')
    def test_campaign_change_after_creation_blocks_approval_and_claim(self):
        out,_=self.create()
        with connect() as db,db.cursor() as cur:
            app=store.approvals_for(cur,self.w,out['taskId'])[0]
            step=store.load_steps(cur,self.w,out['taskId'])[1]
            self.assertNotIn('campaignId',step['inputs'])
            self.assertIn('Studio',step['inputs']['brief'])
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            campaign=state['raffi']['campaignPlanning']['campaigns'][0];campaign['version']+=1;campaign['facts']['venue']='New unreviewed venue'
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.w))
        with patch.object(executor,'drive_inline',side_effect=AssertionError('Writer must not run')) as drive:
            with self.assertRaises(AlphaError):approvals.resolve_approval(self.runtime,self.w,OWNER,app['approvalId'],{'decision':'approve','digest':app['digest'],'idempotencyKey':'changed-'+uuid.uuid4().hex})
            drive.assert_not_called()
        with connect() as db,db.cursor() as cur:
            saved=store.load_steps(cur,self.w,out['taskId'])
            self.assertEqual(saved[0]['reasonCode'],'target_changed')
            self.assertNotIn('New unreviewed venue',saved[1]['inputs']['brief'])

    def test_campaign_source_grant_revoked_after_admission_denies_writer(self):
        # Explicit enforcement is a disposable fixture; it never enables a live workspace.
        from postriff_phase2.agent_runtime_v2 import agent_permissions
        cfg = SimpleNamespace(permissions_for=lambda _w: 'enforce', task_engine_for=lambda _w: 'on')
        runtime = SimpleNamespace(service=self.service, cfg=cfg, clock=time.time)
        approvals.install()
        with self.service.repository.transaction(OWNER, self.w) as (cur, row, principal):
            existing = agent_permissions.load(cur, self.w, principal, now=time.time())
            agent_permissions.apply_decision(cur, workspace_id=self.w, principal=principal,
                member=self.service.ideas._member(row), state=self.service.ideas._state(row), token=OWNER,
                payload={'preset': 'recommended', 'expectedEpoch': existing.user_epoch,
                    'consentVersion': agent_permissions.CONSENT_VERSION, 'copyDigest': agent_permissions.COPY_DIGEST,
                    'confirmed': True, 'source': 'settings', 'idempotencyKey': 'grant-'+uuid.uuid4().hex},
                now=time.time(), mode='enforce')
        preview = pipeline.preview(runtime, self.w, OWNER, self.body)
        self.assertTrue(preview['canCreate'])
        out = pipeline.create(runtime, self.w, OWNER, {**self.body, 'digest': preview['digest'], 'idempotencyKey': 'grant-task-'+uuid.uuid4().hex})
        with self.service.repository.transaction(OWNER, self.w) as (cur, row, principal):
            task = store.load_task(cur, self.w, out['taskId'])
            step = store.load_steps(cur, self.w, out['taskId'])[1]
            app = store.approvals_for(cur, self.w, out['taskId'])[0]
            self.assertEqual(step['targetRefs'][0]['type'], 'campaign')
            agent_permissions.revoke(cur, workspace_id=self.w, principal=principal,
                member=self.service.ideas._member(row), state=self.service.ideas._state(row), token=OWNER,
                payload={'scopes': ['domain:campaigns'], 'idempotencyKey': 'revoke-campaign-'+uuid.uuid4().hex},
                now=time.time(), mode='enforce')
        with store.service_tx(self.service, self.w) as cur:
            grants = agent_permissions.load(cur, self.w, A, now=time.time())
            self.assertIn('content', grants.domains)
            self.assertNotIn('campaigns', grants.domains)
            verdict = authz_seam.decide_for_step(cur, task, step, actor=authz_seam.Actor('human_ui', A),
                now=time.time(), config=cfg, allowed_before=True)
            self.assertEqual((verdict.verdict, verdict.authz_reason), ('deny', 'domain_off'))
        with patch.object(executor, 'drive_inline', side_effect=AssertionError('Revoked campaign must not reach writer')) as drive:
            with self.assertRaises(AlphaError):
                approvals.resolve_approval(runtime, self.w, OWNER, app['approvalId'],
                    {'decision': 'approve', 'digest': app['digest'], 'idempotencyKey': 'denied-campaign-'+uuid.uuid4().hex})
            drive.assert_not_called()
        with connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_agent_step_attempts WHERE task_id=%s', (out['taskId'],)).fetchone()[0], 0)

    def test_live_output_projection_distinguishes_queued_from_verified(self):
        out,_=self.create()
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            state.setdefault('variants',[]).append({'id':'draft-test','platform':'Threads','revision':1})
            state['phase2']['jobs']=[{'id':'job-test','state':'queued','manifest':{'variantId':'draft-test','platform':'Threads','channelId':'channel-test'}}]
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.w))
            db.execute("UPDATE public.pr_agent_steps SET entities='[{\"type\":\"draft\",\"id\":\"draft-test\"}]'::jsonb WHERE task_id=%s AND step_key='s2'",(out['taskId'],))
        entry=next(i for i in pipeline.listing(self.runtime,self.w,OWNER)['items'] if i['taskId']==out['taskId'])
        self.assertEqual(len(entry['drafts']),1);self.assertFalse(entry['jobs'][0]['verified']);self.assertEqual(entry['measurement']['status'],'unavailable')
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            state['phase2']['jobs'][0].update(state='verified',providerConfirmed=True,providerReference='native-post',verification={'at':time.time()})
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.w))
            for workspace,job,value in [(self.w,'job-test',7),(self.w2,'job-test',999),(self.w,'unrelated-private-job',888)]:
                db.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at) VALUES(%s,'channel-test','threads','native-post',%s,'views','native/1',%s,'count','available',now())",(workspace,job,value))
        entry=next(i for i in pipeline.listing(self.runtime,self.w,OWNER)['items'] if i['taskId']==out['taskId'])
        self.assertTrue(entry['jobs'][0]['verified']);self.assertEqual(entry['measurement']['status'],'observed')
        self.assertEqual([p['metrics']['views']['value'] for p in entry['measurement']['posts']],[7.0])
        self.assertNotIn('999',json.dumps(entry));self.assertNotIn('888',json.dumps(entry));self.assertNotIn('unrelated-private-job',json.dumps(entry))


if __name__=='__main__':unittest.main(verbosity=2)
