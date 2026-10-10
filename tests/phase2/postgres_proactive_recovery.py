"""Disposable PostgreSQL recovery drills. Storage and social providers are synthetic.

No production credentials, uploads, provider spend, network delivery or publication.
"""
import copy
import hashlib
import json
import os
import time
import threading
import unittest
import uuid
import psycopg
from types import SimpleNamespace
from unittest.mock import patch

import postgres_agent_task_engine as task_fixture
import postgres_repository as publish_fixture
from postriff_alpha.domain import AlphaError
from postriff_phase2 import automation_runs
from postriff_phase2.library_assets import UniversalLibrary
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.agent_runtime_v2.task_engine import delegates, executor, notifications, store
from postriff_phase2.coworker import flags as notification_flags
from postriff_phase2.notifications.service import NotificationService

connect = task_fixture.connect
PUBLISH_BASE = copy.deepcopy(publish_fixture.service.get(publish_fixture.wid,'fixture-one')['state'])


class MemoryStorage:
    """Synthetic bounded private storage, never a cloud transport."""
    def __init__(self):
        self.raw = b'Synthetic recovery document.'
        self.error = None
        self.after_read = None
    def object_info(self,*args):
        if self.error: raise self.error
        return {'bytes':len(self.raw),'mime':'text/plain','etag':'synthetic-etag'}
    def get_bounded(self,*args):
        if self.after_read: self.after_read()
        return self.raw


class UnknownSocial:
    """A timeout means the synthetic POST may have reached its destination."""
    def __init__(self): self.submits=0; self.reconciles=0
    def submit(self,manifest):
        self.submits += 1
        raise TimeoutError('synthetic timeout after dispatch')
    def reconcile(self,manifest,job):
        self.reconciles += 1
        return {'state':'uncertain','confirmed':'Synthetic lookup still unknown'}


class RecoveryPG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        task_fixture.TaskEnginePG.setUpClass()
        cls.helper=task_fixture.TaskEnginePG()
        cls.service=cls.helper.service
        cls.w=cls.helper.w
        cls.runtime=cls.helper.runtime
        cls.prior_flags=notification_flags._values
        notification_flags.attach({'RAFII_NOTIFICATIONS_V2_ENABLED':'1'})
        cls.service.notifications=NotificationService(cls.service)
        cls.env=patch.dict(os.environ,{'RAFII_TASK_ENGINE_WORKSPACES':cls.w+','+publish_fixture.wid})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        notification_flags.attach(cls.prior_flags)
        task_fixture.TaskEnginePG.tearDownClass()

    def setUp(self):
        self.storage=MemoryStorage()
        self.library=UniversalLibrary(self.service,storage=self.storage)
        with connect() as db:
            db.execute('DELETE FROM public.pr_library_assets WHERE workspace_id=%s',(self.w,))
            db.execute('DELETE FROM public.pr_notification_events WHERE workspace_id IN (%s,%s)',(self.w,publish_fixture.wid))
            db.execute("UPDATE public.pr_agent_tasks SET state='cancelled',finished_at=now(),next_wake_at=NULL WHERE workspace_id IN (%s,%s)",(self.w,publish_fixture.wid))

    def asset(self,creator=task_fixture.A):
        ident=uuid.uuid4().hex
        with connect() as db:
            db.execute("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,kind,mime,extension,bytes,bucket,object_name,etag,processing_status) VALUES(%s,%s,%s,'synthetic.txt','document','text/plain','txt',%s,'test-library',%s,'synthetic-etag','queued')",(ident,self.w,creator,len(self.storage.raw),ident+'.txt'))
        return ident

    def row(self,ident):
        with connect() as db:
            return db.execute('SELECT to_jsonb(a) FROM public.pr_library_assets a WHERE id=%s',(ident,)).fetchone()[0]

    def observe(self,kind,ident,helper=None):
        helper=helper or self.helper
        task=helper.create([{'kind':'delegate','label':'Observe synthetic recovery','delegate':{'type':kind,'id':ident}}])
        with store.service_tx(helper.service,helper.w) as cur:
            t=store.load_task(cur,helper.w,task['taskId']);s=store.load_step(cur,helper.w,task['taskId'],'s1')
            result=delegates.poll(cur,t,s)
            executor._poll_delegate(cur,helper.service.ideas,t,s)
            store.refresh(cur,helper.service.ideas,t)
        return task,result

    def assert_notice_once(self,runtime,task):
        self.assertEqual(notifications.scan(runtime)['created'],1)
        self.assertEqual(notifications.scan(runtime)['created'],0)
        with connect() as db:
            rows=db.execute('SELECT e.payload,d.channel FROM public.pr_notification_events e JOIN public.pr_notification_deliveries d ON d.event_id=e.id WHERE e.workspace_id=%s',(runtime.service is self.service and self.w or publish_fixture.wid,)).fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][0]['href'],'/app/tasks?task='+task['taskId'])
        self.assertEqual(rows[0][1],'in_app')
        self.assertNotIn('Synthetic recovery document',str(rows))

    def test_library_429_backoff_cap_native_action_and_one_notice(self):
        ident=self.asset(); self.storage.error=AlphaError('synthetic rate limit',429)
        for attempt in (1,2,3):
            before=time.time()
            self.assertEqual(self.library.process(connect,self.w,ident),'retrying' if attempt<3 else 'failed')
            row=self.row(ident);info=row['provenance']['recovery']
            self.assertEqual(row['attempts'],attempt)
            self.assertEqual(info['automaticRetry'],attempt<3)
            if attempt<3:
                self.assertGreaterEqual(info['retryAt']-before,30*2**(attempt-1)-1)
                self.assertEqual(self.library.process(connect,self.w,ident),'not_claimed')
                with connect() as db: db.execute('UPDATE public.pr_library_assets SET next_attempt_at=now() WHERE id=%s',(ident,))
        self.assertEqual(self.library.process(connect,self.w,ident),'not_claimed')
        task,out=self.observe('library_job',ident)
        self.assertEqual(out.state,'blocked')
        self.assertEqual(out.outputs[0]['type'],'asset')
        self.assertEqual(out.outputs[0]['recovery']['action'],'review_library')
        with store.service_tx(self.service,self.w) as cur:
            saved=store.load_step(cur,self.w,task['taskId'],'s1')
            self.assertEqual(saved['outputs'],out.outputs)
        self.assert_notice_once(self.runtime,task)
        self.storage.error=None
        self.assertEqual(self.library.retry(self.w,task_fixture.OWNER,ident)['status'],'ready')
        self.assertNotIn('recovery',self.row(ident)['provenance'])

    def test_library_permission_and_unsupported_are_manual(self):
        ident=self.asset();self.storage.error=AlphaError('synthetic denied',403)
        self.assertEqual(self.library.process(connect,self.w,ident),'failed')
        self.assertEqual(self.row(ident)['provenance']['recovery']['category'],'permission')
        self.assertEqual(self.library.process(connect,self.w,ident),'not_claimed')
        self.storage.error=None
        other=self.asset()
        with patch('postriff_phase2.library_assets.extract_text',return_value=('unsupported','')):
            self.assertEqual(self.library.process(connect,self.w,other),'unsupported')
        _,out=self.observe('library_job',other)
        self.assertEqual(out.state,'blocked')
        self.assertFalse(out.outputs[0]['recovery']['automaticRetry'])

    def test_expired_library_lease_discards_output_then_restart_recovers(self):
        ident=self.asset()
        def expire():
            with connect() as db: db.execute("UPDATE public.pr_library_assets SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(ident,))
        self.storage.after_read=expire
        self.assertEqual(self.library.process(connect,self.w,ident),'lease_lost')
        with connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM public.pr_library_chunks WHERE asset_id=%s',(ident,)).fetchone()[0],0)
        self.storage.after_read=None
        self.assertEqual(self.library.process(connect,self.w,ident),'ready')
        self.assertEqual(self.row(ident)['attempts'],2)
        _,out=self.observe('library_job',ident)
        self.assertEqual(out.state,'completed')

    def test_library_creator_and_workspace_identity(self):
        ident=self.asset(task_fixture.B)
        _,out=self.observe('library_job',ident)
        self.assertEqual((out.state,out.reason_code),('blocked','target_changed'))
        with connect() as db, db.cursor() as cur:
            out=delegates._library_job(cur,{'workspaceId':self.helper.w2,'createdBy':task_fixture.B},{'delegateId':ident})
            self.assertEqual(out.reason_code,'target_changed')
            out=delegates._library_job(cur,{'workspaceId':self.w,'createdBy':task_fixture.A},{'delegateId':'invalid'})
            self.assertEqual(out.reason_code,'target_changed')

    def test_expired_failure_callback_cannot_write_retry(self):
        ident=self.asset()
        def fail(*args):
            with connect() as db: db.execute("UPDATE public.pr_library_assets SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(ident,))
            raise AlphaError('synthetic late storage error',503)
        with patch.object(self.storage,'object_info',side_effect=fail):
            self.assertEqual(self.library.process(connect,self.w,ident),'lease_lost')
        row=self.row(ident)
        self.assertEqual(row['processing_status'],'processing')
        self.assertNotIn('recovery',row['provenance'])
        self.assertEqual(self.library.process(connect,self.w,ident),'ready')

    def test_exhausted_library_restart_reports_timeout_without_claim(self):
        ident=self.asset()
        with connect() as db:
            db.execute("UPDATE public.pr_library_assets SET processing_status='processing',attempts=3,lease_token=%s,lease_expires_at=now()-interval '1 second' WHERE id=%s",(str(uuid.uuid4()),ident))
        self.assertEqual(self.library.sweep(connect)['processed'],0)
        row=self.row(ident)
        self.assertEqual(row['processing_status'],'failed')
        self.assertEqual(row['provenance']['recovery']['category'],'timeout')
        self.assertFalse(row['provenance']['recovery']['automaticRetry'])

    def test_lease_expiring_while_waiting_for_workspace_lock_discards_completion(self):
        ident=self.asset()
        seen=[]; errors=[]; threads=[]
        def after_read():
            locker=connect()
            locker.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE',(self.w,))
            def release_after_expiry():
                try:
                    deadline=time.monotonic()+5
                    with connect() as observer:
                        while time.monotonic()<deadline:
                            waiting=observer.execute("SELECT 1 FROM pg_stat_activity WHERE application_name='recovery-fence-drill' AND wait_event_type='Lock'").fetchone()
                            observer.commit()
                            if waiting:
                                observer.execute("UPDATE public.pr_library_assets SET lease_expires_at=clock_timestamp()+interval '0.2 seconds' WHERE id=%s",(ident,))
                                observer.commit()
                                time.sleep(.25)
                                seen.append(True)
                                break
                            time.sleep(.01)
                except Exception as error: errors.append(error)
                finally:
                    locker.commit();locker.close()
            thread=threading.Thread(target=release_after_expiry)
            threads.append(thread);thread.start()
        def finisher():
            return psycopg.connect(task_fixture.DSN,client_encoding='utf8',application_name='recovery-fence-drill')
        self.storage.after_read=after_read
        result=self.library.process(finisher,self.w,ident)
        for thread in threads: thread.join(timeout=6)
        self.assertFalse(errors)
        self.assertEqual(seen,[True],'must actually observe the completion waiting on its workspace lock')
        self.assertEqual(result,'lease_lost')
        self.assertIsNone(self.row(ident)['sha256'])

    def publish(self):
        state=copy.deepcopy(PUBLISH_BASE)
        job=state['phase2']['jobs'][0]
        job.update(state='scheduled',attempts=[],checks=0,nextAt=0,leaseUntil=0,leaseOwner=None,cancelRequested=False)
        for key in ('providerReference','providerAcceptedAt','providerConfirmed','verification','verifiedAt','url','progress','containerId'):
            job.pop(key,None)
        with connect() as db: db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),publish_fixture.wid))
        clock=[max(time.time(),publish_fixture.clock[0])]
        social=UnknownSocial()
        worker=PostgresWorker(connect,social=social,clock=lambda:clock[0],worker_id='recovery-drill')
        return worker,social,clock,job['id']

    def test_worker_restart_before_dispatch_never_blind_resubmits(self):
        worker,social,clock,_=self.publish()
        self.assertTrue(worker.step(crash='after_claim'))
        self.assertEqual(social.submits,0)
        clock[0]+=46
        self.assertTrue(worker.step())
        self.assertEqual((social.submits,social.reconciles),(0,1))

    def test_post_timeout_bounded_lookup_manual_attention_and_one_notice(self):
        worker,social,clock,ident=self.publish()
        self.assertTrue(worker.step())
        for _ in range(5):
            clock[0]+=61
            self.assertTrue(worker.step())
        self.assertEqual((social.submits,social.reconciles),(1,5))
        clock[0]+=61
        self.assertFalse(worker.step())
        helper=task_fixture.TaskEnginePG();helper.w=publish_fixture.wid;helper.service=publish_fixture.service
        # This helper defaults to A; override only its explicit server actor.
        original=helper.create
        helper.create=lambda steps: original(steps,actor=publish_fixture.one)
        runtime=SimpleNamespace(service=helper.service,cfg=None,clock=time.time)
        helper.service.notifications=NotificationService(helper.service)
        task,out=self.observe('publish_job',ident,helper)
        self.assertEqual((out.state,out.reason_code),('blocked','outcome_unknown'))
        self.assertFalse(out.outputs[0]['recovery']['automaticRetry'])
        self.assert_notice_once(runtime,task)
        self.assertEqual(social.submits,1)

    def test_revoked_channel_and_expired_dispatch_lease_send_nothing(self):
        worker,social,clock,ident=self.publish()
        claim=worker.claim();self.assertIsNotNone(claim)
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(publish_fixture.wid,)).fetchone()[0]
            state['phase2']['channels'][0]['expiresAt']=clock[0]-1
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),publish_fixture.wid))
        self.assertFalse(worker.authorize_dispatch(claim))
        with connect() as db,db.cursor() as cur:
            out=delegates._publish_job(cur,{'workspaceId':publish_fixture.wid},{'delegateId':ident})
        self.assertEqual(out.state,'blocked')
        self.assertEqual(social.submits,0)
        worker,social,clock,_=self.publish();claim=worker.claim();clock[0]+=46
        self.assertFalse(worker.authorize_dispatch(claim))
        self.assertEqual(social.submits,0)

    def automation(self):
        campaign={'id':uuid.uuid4().hex,'version':1,'status':'active','createdBy':task_fixture.A}
        task={'id':uuid.uuid4().hex,'campaignId':campaign['id'],'version':1,'status':'active','createdBy':task_fixture.A,'activatedBy':task_fixture.A,'name':'Synthetic recovery','emailWatchers':[]}
        item={'key':'synthetic','platform':'LinkedIn','state':'approved','attempts':0,'channelId':uuid.uuid4().hex,'publishAt':time.time()+3600}
        run={'id':uuid.uuid4().hex,'taskId':task['id'],'taskVersion':1,'scheduledFor':time.time(),'state':'completed','lifecycle':'drafted','idempotencyKey':hashlib.sha256(uuid.uuid4().bytes).hexdigest(),'items':[item]}
        with connect() as db:
            state=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(self.w,)).fetchone()[0]
            state.setdefault('raffi',{}).setdefault('campaignPlanning',{}).update(campaigns=[campaign],recurringTasks=[task],occurrences=[run])
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.w))
        return task,run,item

    def current_item(self):
        with connect() as db: return db.execute("SELECT state#>'{raffi,campaignPlanning,occurrences,0,items,0}' FROM public.pr_workspaces WHERE id=%s",(self.w,)).fetchone()[0]

    def test_automation_429_backoff_fresh_admission_cap_and_deduped_notice(self):
        task,run,item=self.automation()
        worker=SimpleNamespace(service=self.service,clock=time.time)
        for attempt in (1,2,3):
            automation_runs._commit_failed(self.service,self.w,run['id'],item['key'],task,AlphaError('synthetic 429',429))
            current=self.current_item()
            self.assertEqual(current['attempts'],attempt)
            self.assertEqual(current['recovery']['automaticRetry'],attempt<3)
            if attempt<3:
                self.assertGreaterEqual(current['retryAt']-time.time(),30*2**(attempt-1)-1)
                with patch('postriff_phase2.automation_runs.capabilities.publish_route',side_effect=AssertionError('premature dispatch')):
                    out=automation_runs.commit_item(worker,self.w,run['id'],item['key'],task_fixture.A,item,task)
                self.assertTrue(out['deferred'])
        self.assertEqual(current['state'],'failed')
        automation_runs._commit_failed(self.service,self.w,run['id'],item['key'],task,AlphaError('again',429))
        self.assertEqual(self.current_item()['attempts'],3)
        with connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_notifications WHERE workspace_id=%s AND meta->>'occurrenceId'=%s",(self.w,run['id'])).fetchone()[0],1)

    def test_automation_revoked_authority_and_permanent_failure_do_not_retry(self):
        for status,target in ((403,'ready_for_review'),(415,'failed')):
            task,run,item=self.automation()
            automation_runs._commit_failed(self.service,self.w,run['id'],item['key'],task,AlphaError('synthetic denied',status))
            current=self.current_item()
            self.assertEqual(current['state'],target)
            self.assertFalse(current['recovery']['automaticRetry'])
            self.assertEqual(current['attempts'],0 if status==403 else 1)

    def test_oauth_429_defers_but_403_requires_manual_reconnection(self):
        worker=SimpleNamespace(service=self.service,clock=time.time)
        for status,target in ((429,'approved'),(403,'platform_disconnected')):
            task,run,item=self.automation()
            def reverify(*args): raise AlphaError('synthetic verification error',status)
            oauth=SimpleNamespace(providers={},reverify_for_worker=reverify)
            with patch.object(self.service,'oauth',oauth,create=True), patch('postriff_phase2.automation_runs.capabilities.publish_route',return_value={'publish':True}):
                automation_runs.commit_item(worker,self.w,run['id'],item['key'],task_fixture.A,item,task)
            current=self.current_item()
            self.assertEqual(current['state'],target)
            self.assertEqual(current['recovery']['automaticRetry'],status==429)
            if status==429: self.assertNotIn('Reconnect',current['lastError'])

    def test_ready_asset_failed_indexing_requires_attention(self):
        ident=self.asset()
        with connect() as db:
            db.execute("UPDATE public.pr_library_assets SET processing_status='ready',indexing_status='failed' WHERE id=%s",(ident,))
        _,out=self.observe('library_job',ident)
        self.assertEqual((out.state,out.reason_code),('blocked','needs_input'))
        self.assertFalse(out.outputs[0]['recovery']['automaticRetry'])
        self.assertTrue(self.library.detail(self.w,task_fixture.OWNER,ident)['asset']['canRetryProcessing'])
        self.assertEqual(self.library.retry(self.w,task_fixture.OWNER,ident)['status'],'ready')

    def test_exhausted_transient_verification_cannot_reconnect_into_retry_loop(self):
        task,run,item=self.automation()
        route={'code':'disconnected','reason':'synthetic temporary verification'}
        for _ in range(3):
            automation_runs._blocked(self.service,self.w,run['id'],item['key'],task,route,transient=True)
        current=self.current_item()
        self.assertEqual((current['state'],current['attempts']),('failed',3))
        self.assertFalse(current['recovery']['automaticRetry'])
        automation_runs._blocked(self.service,self.w,run['id'],item['key'],task,route,transient=True)
        self.assertEqual(self.current_item()['attempts'],3)


if __name__=='__main__': unittest.main()
