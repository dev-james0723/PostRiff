"""Disposable PostgreSQL recipe policy, actual Task Engine read/report, RLS and revocation proofs.

Synthetic workspaces, signed-session verifier fixture, no models/providers/production activation.
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
from postriff_phase2.agent_runtime_v2 import agent_permissions as grants, authz, domain_tools
from postriff_phase2.agent_runtime_v2.task_engine import executor, store, actions, notifications
from postriff_phase2.workflow_recipes import tools, runner, policy
from postriff_phase2.workflow_recipes.service import Recipes, load

ROOT=Path(__file__).resolve().parents[2]
DSN=os.environ['POSTRIFF_TEST_DSN']
def admin():return psycopg.connect(DSN,client_encoding='utf8')
def connect():
    db=admin();db.execute('SET ROLE service_role');return db


class RecipesPG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with admin() as db:
            for migration in ('102_agent_ui_artifacts.sql','108_agent_tasks.sql','113_workflow_recipes.sql','113_workflow_recipes.sql'):
                db.execute((ROOT/'migrations/postriff'/migration).read_text())
        domain_tools.ensure_registered()

    def setUp(self):
        self.now=float(int(time.time()));self.proof_at=self.now-5
        self.actor,self.other=str(uuid.uuid4()),str(uuid.uuid4())
        self.token,self.other_token='session-'+uuid.uuid4().hex,'session-'+uuid.uuid4().hex
        tokens={self.token:self.actor,self.other_token:self.other}
        def verify(token):return tokens[token]
        verify.session_id=lambda token,principal:'session-'+principal
        verify.auth_time=lambda token,principal:self.now
        verify.method_time=lambda token,principal:('password',self.proof_at)
        verify.aal=lambda token,principal:'aal2'
        with admin() as db:
            for principal in tokens.values():db.execute('INSERT INTO auth.users(id) VALUES(%s)',(principal,))
        self.service=HostedWorkspaceService(connect,verify,clock=lambda:self.now)
        self.w=self.service.bootstrap(self.token,'studio')['workspaceId'];self.w2=self.service.bootstrap(self.other_token,'studio')['workspaceId']
        self.env=patch.dict(os.environ,{'RAFII_AGENT_V2_ENABLED':'1','RAFII_TASK_ENGINE_ENABLED':'1','RAFII_TASK_ENGINE_AUTHORITATIVE':'1','RAFII_TASK_ENGINE_WORKSPACES':self.w,
            'RAFII_WORKFLOW_RECIPES_ENABLED':'1','RAFII_WORKFLOW_RECIPES_WORKSPACES':self.w})
        self.env.start();self.addCleanup(self.env.stop)
        self.cfg=SimpleNamespace(permissions_for=lambda w:'enforce',task_engine_for=lambda w:'on' if w==self.w else 'off')
        self.runtime=SimpleNamespace(service=self.service,cfg=self.cfg,clock=lambda:self.now)
        self.domain=Recipes(self.service,self.cfg)
        with self.service.repository.transaction(self.token,self.w) as (cur,row,principal):
            grants.apply_decision(cur,workspace_id=self.w,principal=principal,member=self.service.ideas._member(row),state=self.service.ideas._state(row),token=self.token,
                payload={'preset':'recommended','expectedEpoch':0,'consentVersion':grants.CONSENT_VERSION,'copyDigest':grants.COPY_DIGEST,'confirmed':True,'source':'settings','idempotencyKey':uuid.uuid4().hex},now=self.now,mode='enforce')

    def one(self,sql,args=()):
        with connect() as db:return db.execute(sql,args).fetchone()

    def recipe(self,**settings):
        recipe=self.domain.save(self.w,self.token,{'settings':{'templateId':'library_review','expiresAt':self.now+86400,'actionsPerDay':5,'actionsTotal':10,**settings},'expectedVersion':None})
        view=self.domain.list(self.w,self.token)
        return self.domain.enable(self.w,self.token,recipe['id'],{'expectedVersion':recipe['version'],'permissionToken':view['permissionToken'],'confirmed':True,'requestKey':uuid.uuid4().hex})

    def admit(self,recipe,key=None):
        with store.service_tx(self.service,self.w) as cur:
            fresh=load(cur,self.w,self.actor,recipe['id'])
            return runner.admit(cur,self.domain,self.w,self.actor,fresh,self.now,manual_key=key or uuid.uuid4().hex)

    def drive(self,task):
        return executor.drive_inline(self.runtime,self.w,self.token,self.actor,task['taskId'],actor_kind='autopilot',seconds=90,max_steps=1)

    def upload(self,**extra):
        ident=uuid.uuid4().hex
        with connect() as db:
            db.execute("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,display_title,kind,mime,extension,bytes,bucket,object_name,processing_status,summary,created_at) VALUES(%s,%s,%s,'private.txt','Readable title','document','text/plain','txt',20,'postriff-library',%s,'ready','FILE CONTENT MUST NOT APPEAR',to_timestamp(%s))",(ident,self.w,self.actor,ident+'.txt',self.now+1))
            for key,value in extra.items():
                if key=='status':db.execute('UPDATE public.pr_library_assets SET processing_status=%s WHERE id=%s',(value,ident))
        return ident

    def revoke(self,scope='domain:library'):
        with self.service.repository.transaction(self.token,self.w) as (cur,row,principal):
            grants.revoke(cur,workspace_id=self.w,principal=principal,member=self.service.ideas._member(row),state=self.service.ideas._state(row),token=self.token,
                payload={'scopes':[scope],'idempotencyKey':uuid.uuid4().hex},now=self.now,mode='enforce')

    def test_01_explicit_policy_binds_version_template_and_no_permission_expansion(self):
        before=self.domain.list(self.w,self.token)['permissionToken'];r=self.recipe()
        after=self.domain.list(self.w,self.token)
        self.assertEqual(before,after['permissionToken']);self.assertTrue(after['recipes'][0]['policyCurrent'])
        row=self.one('SELECT constraints,limits,created_epoch FROM public.pr_agent_autopilot_policies WHERE id=%s',(r['policyId'],))
        self.assertEqual(row[0]['recipeVersion'],r['version']);self.assertEqual(row[1]['usdMicroPerDay'],0);self.assertEqual(len(row[0]['templateDigest']),64)
        self.assertEqual(self.one("SELECT count(*) FROM public.pr_agent_consent_receipts WHERE workspace_id=%s AND kind='autopilot_enabled'",(self.w,))[0],1)

    def test_02_actual_read_stores_private_report_and_content_free_task_receipt(self):
        asset=self.upload();r=self.recipe();t=self.admit(r);self.drive(t)
        state,report=self.one('SELECT t.state,r.report FROM public.pr_agent_tasks t JOIN public.pr_workflow_recipe_runs r ON r.task_id=t.id WHERE t.id=%s',(t['taskId'],))
        self.assertEqual(state,'completed',self.one('SELECT state,reason_code,reason FROM public.pr_agent_steps WHERE task_id=%s',(t['taskId'],)));self.assertEqual(report['items'][0]['assetId'],asset)
        self.assertNotIn('FILE CONTENT',json.dumps(report));self.assertEqual(report['providerRequests'],0)
        self.assertEqual(report['items'][0]['title'],'Readable title')
        steps=self.one('SELECT outputs FROM public.pr_agent_steps WHERE task_id=%s',(t['taskId'],))[0]
        self.assertNotIn('Readable title',json.dumps(steps))
        run=self.one('SELECT id::text FROM public.pr_workflow_recipe_runs WHERE task_id=%s',(t['taskId'],))[0]
        self.assertEqual(self.domain.report(self.w,self.token,run)['report'],report)
        self.assertEqual(steps,[{'type':'workflow_report','id':run}])
        self.drive(t);self.assertEqual(self.one('SELECT count(*) FROM public.pr_workflow_recipe_runs WHERE task_id=%s',(t['taskId'],))[0],1)

    def test_03_duplicate_trigger_one_task(self):
        r=self.recipe();key=uuid.uuid4().hex;t=self.admit(r,key);again=self.admit(r,key)
        self.assertEqual(t['taskId'],again['taskId'])
        self.assertEqual(self.one('SELECT count(*) FROM public.pr_workflow_recipe_runs WHERE recipe_id=%s',(r['id'],))[0],1)

    def test_04_foreign_workspace_creator_and_report_isolation(self):
        r=self.recipe();t=self.admit(r);run=self.one('SELECT id::text FROM public.pr_workflow_recipe_runs WHERE task_id=%s',(t['taskId'],))[0]
        with self.assertRaises(AlphaError):self.domain.report(self.w,self.other_token,run)
        with self.assertRaises(AlphaError):self.domain.stop(self.w,self.other_token,r['id'],{'expectedVersion':r['version'],'status':'revoked'})
        with self.assertRaises(psycopg.Error):
            with connect() as db:db.execute('UPDATE public.pr_workflow_recipes SET workspace_id=%s,created_by=%s WHERE id=%s',(self.w2,self.other,r['id']))

    def test_05_revoke_after_admit_prevents_actual_read(self):
        r=self.recipe();t=self.admit(r);self.domain.stop(self.w,self.token,r['id'],{'expectedVersion':r['version'],'status':'revoked'});self.drive(t)
        self.assertIsNone(self.one('SELECT report FROM public.pr_workflow_recipe_runs WHERE task_id=%s',(t['taskId'],))[0])
        self.assertIsNotNone(self.one('SELECT revoked_at FROM public.pr_agent_autopilot_policies WHERE id=%s',(r['policyId'],))[0])

    def test_06_expiry_and_source_revocation_fail_closed(self):
        r=self.recipe();t=self.admit(r);self.revoke();self.drive(t)
        self.assertIsNone(self.one('SELECT report FROM public.pr_workflow_recipe_runs WHERE task_id=%s',(t['taskId'],))[0])
        with self.assertRaises(AlphaError):self.admit(r)

    def test_07_operation_reservations_are_once_and_zero_cost(self):
        r=self.recipe(actionsPerDay=1,actionsTotal=1);t=self.admit(r);self.drive(t)
        usage=self.one('SELECT usage FROM public.pr_agent_autopilot_policies WHERE id=%s',(r['policyId'],))[0]
        self.assertEqual(usage['actionsTotal'],1);self.assertEqual(usage['spentUsdMicro'],0);self.assertEqual(len(usage['reservations']),1)
        with self.assertRaises(AlphaError):self.admit(r)

    def test_08_stale_signed_auth_cannot_enable(self):
        self.proof_at=self.now-601
        with self.assertRaises(AlphaError) as caught:self.recipe()
        self.assertEqual(caught.exception.code,'step_up_required')
        self.assertEqual(self.one('SELECT count(*) FROM public.pr_agent_autopilot_policies WHERE workspace_id=%s',(self.w,))[0],0)

    def test_09_version_change_revokes_old_and_cannot_reuse_enable_key(self):
        r=self.recipe();view=self.domain.list(self.w,self.token);settings={k:v for k,v in r['config'].items() if k not in ('templateVersion','errorPolicy','approvalPolicy','maxAssets')}
        updated=self.domain.save(self.w,self.token,{'settings':settings,'expectedVersion':r['version']},r['id'])
        self.assertEqual(updated['version'],r['version']+1);self.assertEqual(updated['status'],'draft')
        self.assertIsNotNone(self.one('SELECT revoked_at FROM public.pr_agent_autopilot_policies WHERE id=%s',(r['policyId'],))[0])
        with self.assertRaises(AlphaError):self.domain.enable(self.w,self.token,r['id'],{'expectedVersion':r['version'],'permissionToken':view['permissionToken'],'confirmed':True,'requestKey':uuid.uuid4().hex})

    def test_10_rls_reapply_and_run_immutability(self):
        r=self.recipe();t=self.admit(r);self.drive(t)
        for role in ('anon','authenticated'):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with admin() as db:db.execute('SET ROLE '+role);db.execute('SELECT * FROM public.pr_workflow_recipes')
        with self.assertRaises(psycopg.errors.CheckViolation):
            with connect() as db:db.execute("UPDATE public.pr_workflow_recipe_runs SET report='{}'::jsonb WHERE task_id=%s",(t['taskId'],))
        with self.assertRaises(psycopg.errors.CheckViolation):
            with connect() as db:db.execute("UPDATE public.pr_workflow_recipe_runs SET inputs='{}'::jsonb WHERE task_id=%s",(t['taskId'],))

    def test_11_new_upload_equal_timestamps_and_late_ready_are_not_lost(self):
        r=self.recipe(trigger='new_asset');a=self.upload();b=self.upload(status='processing')
        with store.service_tx(self.service,self.w) as cur:
            fresh=load(cur,self.w,self.actor,r['id']);self.assertEqual(runner.new_assets(cur,self.w,fresh),[a]);t=runner.admit(cur,self.domain,self.w,self.actor,fresh,self.now+2)
        self.drive(t)
        with connect() as db:db.execute("UPDATE public.pr_library_assets SET processing_status='ready' WHERE id=%s",(b,))
        with store.service_tx(self.service,self.w) as cur:
            self.assertEqual(runner.new_assets(cur,self.w,load(cur,self.w,self.actor,r['id'])),[b])

    def test_12_notification_policy_changes_actual_baseline(self):
        r=self.recipe(notificationPolicy='none');t=self.admit(r)
        with store.service_tx(self.service,self.w) as cur:self.assertTrue(notifications.recipe_baseline(cur,{**t,'state':'completed'}))
        r2=self.recipe(notificationPolicy='failures_and_approvals');t2=self.admit(r2)
        with store.service_tx(self.service,self.w) as cur:
            self.assertTrue(notifications.recipe_baseline(cur,{**t2,'state':'completed'}));self.assertFalse(notifications.recipe_baseline(cur,{**t2,'state':'failed'}))
        self.domain.stop(self.w,self.token,r2['id'],{'expectedVersion':r2['version'],'status':'revoked'})
        with store.service_tx(self.service,self.w) as cur:self.assertTrue(notifications.recipe_baseline(cur,{**t2,'state':'failed'}))

    def test_13_cancelled_task_cannot_create_report(self):
        r=self.recipe();t=self.admit(r)
        with connect() as db:db.execute('UPDATE public.pr_agent_tasks SET cancel_requested_at=now(),cancel_requested_by=%s WHERE id=%s',(self.actor,t['taskId']))
        self.drive(t);self.assertIsNone(self.one('SELECT report FROM public.pr_workflow_recipe_runs WHERE task_id=%s',(t['taskId'],))[0])

    def test_14_failure_backoff_then_circuit_pause_persists(self):
        r=self.recipe()
        for n in range(3):
            t=self.admit(r)
            with connect() as db:db.execute("UPDATE public.pr_agent_tasks SET state='failed',finished_at=now() WHERE id=%s",(t['taskId'],))
            with store.service_tx(self.service,self.w) as cur:
                fresh=load(cur,self.w,self.actor,r['id']);self.assertIsNone(runner.admit(cur,self.domain,self.w,self.actor,fresh,self.now,manual_key=uuid.uuid4().hex))
            current=self.domain.list(self.w,self.token)['recipes'][0]
            if n<2:self.assertGreater(current['nextAttemptAt'],self.now);self.now=current['nextAttemptAt']+1
        self.assertEqual(current['status'],'paused');self.assertFalse(current['policyCurrent'])

    def test_15_feature_off_no_admission_and_expired_policy_no_read(self):
        r=self.recipe();t=self.admit(r)
        with patch.dict(os.environ,{'RAFII_WORKFLOW_RECIPES_ENABLED':'0'}):
            self.assertEqual(runner.scan(self.runtime)['status'],'disabled');self.drive(t)
        self.assertIsNone(self.one('SELECT report FROM public.pr_workflow_recipe_runs WHERE task_id=%s',(t['taskId'],))[0])
        self.now+=86401
        with self.assertRaises(AlphaError):self.admit(r)

    def test_16_completed_report_hides_after_source_revoke_but_history_remains(self):
        self.upload();r=self.recipe();t=self.admit(r);self.drive(t)
        run=self.one('SELECT id::text FROM public.pr_workflow_recipe_runs WHERE task_id=%s',(t['taskId'],))[0]
        self.assertIsNotNone(self.domain.report(self.w,self.token,run)['report'])
        self.revoke()
        with self.assertRaises(AlphaError) as caught:self.domain.report(self.w,self.token,run)
        self.assertEqual(caught.exception.code,'agent_permission_revoked')
        self.assertEqual(self.domain.list(self.w,self.token)['runs'][0]['taskId'],t['taskId'])

    def test_17_actual_performance_report_preserves_missing_readings(self):
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            state.setdefault('phase2',{}).setdefault('channels',[]).append({'id':'recipe-account','platform':'linkedin','account':'Stored account'})
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.w))
        r=self.recipe(templateId='weekly_performance',connectionId='recipe-account');t=self.admit(r);self.drive(t)
        status,report=self.one('SELECT t.state,r.report FROM public.pr_agent_tasks t JOIN public.pr_workflow_recipe_runs r ON r.task_id=t.id WHERE t.id=%s',(t['taskId'],))
        self.assertEqual(status,'completed',self.one('SELECT state,reason_code,reason FROM public.pr_agent_steps WHERE task_id=%s',(t['taskId'],)));self.assertEqual(report['kind'],'performance');self.assertEqual(report['state'],'empty')
        self.assertEqual(report['data']['posts'],[]);self.assertIn('Unavailable is never 0',report['coverage']['note']);self.assertEqual(report['providerRequests'],0)

    def test_18_daily_quota_rolls_over_in_configured_zone(self):
        r=self.recipe(actionsPerDay=1,actionsTotal=3,expiresAt=self.now+3*86400);t=self.admit(r);self.drive(t)
        with self.assertRaises(AlphaError):self.admit(r)
        self.now+=86400
        second=self.admit(r);self.assertNotEqual(second['taskId'],t['taskId'])

    def test_19_claim_then_revoke_cannot_read_or_write_report(self):
        r=self.recipe();t=self.admit(r)
        with store.service_tx(self.service,self.w) as cur:
            claim=executor.claim_next(cur,self.service.ideas,workspace_id=self.w,executor='inline',principal=self.actor,task_id=t['taskId'],seconds_left=120,owner=executor.lease_owner('inline'),actor_kind='autopilot',config=self.cfg)
        self.assertIsInstance(claim,executor.Claim)
        self.domain.stop(self.w,self.token,r['id'],{'expectedVersion':r['version'],'status':'paused'})
        executor.execute(self.runtime,claim,token=self.token,seconds_left=120)
        self.assertIsNone(self.one('SELECT report FROM public.pr_workflow_recipe_runs WHERE task_id=%s',(t['taskId'],))[0])

    def test_20_weekly_due_dedupes_calendar_occurrence(self):
        r=self.recipe(planningDay=0,planningHour=0)
        with store.service_tx(self.service,self.w) as cur:
            task=runner.admit(cur,self.domain,self.w,self.actor,load(cur,self.w,self.actor,r['id']),self.now)
        self.assertIsNotNone(task);self.drive(task)
        with store.service_tx(self.service,self.w) as cur:
            repeated=runner.admit(cur,self.domain,self.w,self.actor,load(cur,self.w,self.actor,r['id']),self.now)
        self.assertEqual(task['taskId'],repeated['taskId']);self.assertFalse(repeated['recipeAdmissionCreated'])

    def test_21_background_executor_uses_same_recipe_policy_and_real_report(self):
        r=self.recipe();t=self.admit(r)
        with store.service_tx(self.service,self.w) as cur:
            claim=executor.claim_next(cur,self.service.ideas,workspace_id=self.w,executor='cron',principal=None,task_id=t['taskId'],seconds_left=120,owner=executor.lease_owner('cron'),config=self.cfg)
        self.assertIsInstance(claim,executor.Claim)
        executor.execute(self.runtime,claim,seconds_left=120)
        self.assertEqual(self.one('SELECT state FROM public.pr_agent_tasks WHERE id=%s',(t['taskId'],))[0],'completed')
        self.assertIsNotNone(self.one('SELECT report FROM public.pr_workflow_recipe_runs WHERE task_id=%s',(t['taskId'],))[0])

    def test_22_notification_none_records_one_event_without_delivery(self):
        from postriff_phase2.coworker import flags as notification_flags
        from postriff_phase2.notifications.service import NotificationService
        prior=notification_flags._values
        notification_flags.attach({'RAFII_NOTIFICATIONS_V2_ENABLED':'1'});self.addCleanup(notification_flags.attach,prior)
        self.service.notifications=NotificationService(self.service)
        r=self.recipe(notificationPolicy='none');t=self.admit(r);self.drive(t)
        notifications.scan(self.runtime)
        count=self.one('SELECT count(*),count(d.id) FROM public.pr_notification_events e LEFT JOIN public.pr_notification_deliveries d ON d.event_id=e.id WHERE e.workspace_id=%s AND e.entity_id=%s',(self.w,t['taskId']))
        self.assertEqual(count,(1,0))
        notifications.scan(self.runtime)
        self.assertEqual(self.one('SELECT count(*) FROM public.pr_notification_events WHERE workspace_id=%s AND entity_id=%s',(self.w,t['taskId']))[0],1)



    def test_23_populated_performance_scope_and_unavailable_metrics(self):
        from postriff_phase2 import insights
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            phase=state.setdefault('phase2',{})
            phase.setdefault('channels',[]).extend([{'id':ident,'platform':'threads','account':ident} for ident in ('recipe-account','foreign-account')])
            for account,job in (('recipe-account','recipe-post'),('foreign-account','foreign-post')):
                phase.setdefault('jobs',[]).append({'id':job,'state':'verified','providerReference':job,'publishedAt':self.now-2*86400,
                    'manifest':{'channelId':account,'platform':'threads','payload':{'language':'en'},'contentType':{'id':'text'}}})
                insights.record_observations(db.cursor(),self.w,account,'threads',job,job,{'views':123,'likes':0},'synthetic://stored-metrics',self.now-86400,read_offset='24h',period_start=self.now-2*86400)
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.w))
        r=self.recipe(templateId='weekly_performance',connectionId='recipe-account');t=self.admit(r);self.drive(t)
        status,report=self.one('SELECT t.state,r.report FROM public.pr_agent_tasks t JOIN public.pr_workflow_recipe_runs r ON r.task_id=t.id WHERE t.id=%s',(t['taskId'],))
        self.assertEqual(status,'completed',self.one('SELECT state,reason_code,reason FROM public.pr_agent_steps WHERE task_id=%s',(t['taskId'],)))
        posts=report['data']['posts'];self.assertEqual(len(posts),1);self.assertEqual(posts[0]['jobId'],'recipe-post')
        self.assertEqual(posts[0]['metrics']['views']['value'],123);self.assertEqual(posts[0]['metrics']['likes']['value'],0)
        self.assertIsNone(posts[0]['metrics']['replies']['value']);self.assertEqual(posts[0]['metrics']['replies']['availability'],'unavailable')
        self.assertEqual(posts[0]['cohort']['account'],'recipe-account');self.assertNotIn('foreign-post',json.dumps(report))
        self.assertEqual(report['providerRequests'],0);self.assertEqual(report['costUsdMicro'],0)


if __name__=='__main__':unittest.main()
