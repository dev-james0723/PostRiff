"""Media authenticated wire/effect proof; no live storage/provider/model calls."""
import base64
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import io
import json
import os
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker import http as coworker_http
from postriff_phase2.coworker.service import CoworkerService
from postriff_phase2.growth.trends import contracts, media_jobs, media_runtime
from postriff_phase2.growth.trends.service import TrendService
from postriff_phase2.hosted import HostedPhase2Commands, PostgresWorkspaceRepository
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.ideas import IdeasService
import test_trend_media_jobs as durable
import test_trend_service as fixture


class App:
    _json=staticmethod(HostedApplication._json)
    @staticmethod
    def _body(environ):
        return json.loads(environ['wsgi.input'].read())


class Offline(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect','socket.create_connection','socket.getaddrinfo','urllib.request.urlopen','urllib.request.OpenerDirector.open'):
            guard=patch(name,side_effect=AssertionError('no media HTTP egress'))
            mock=guard.start(); self.addCleanup(guard.stop); self.addCleanup(mock.assert_not_called)


class Wire:
    def request(self,tail,*,method='GET',payload=None,query='',token='session',workspace=None,extra=None):
        seen=[]
        raw=json.dumps(payload).encode() if payload is not None else (b'{}' if method=='POST' else b'')
        environ={'QUERY_STRING':query,'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),**(extra or {})}
        result=coworker_http.handle(App(),environ,lambda status,headers:seen.append((status,dict(headers))),
            self.hosted,token,method,['api','workspaces',workspace or self.wid,'coworker','trends',*tail])
        status,headers=seen[0]; data=b''.join(result)
        self.assertEqual(headers['Cache-Control'],'private, no-store'); self.assertEqual(headers['Pragma'],'no-cache')
        self.assertEqual(int(headers['Content-Length']),len(data))
        return int(status.split()[0]),headers,json.loads(data) if headers['Content-Type'].startswith('application/json') else data


class MediaHTTP(Offline,Wire):
    def setUp(self):
        super().setUp()
        self.svc,self.repo,self.store=fixture.make_service()
        self.svc.values['RAFII_TREND_MULTIMODAL_ENABLED']='true'
        self.wid,self.actor,self.result_id,self.job_id=fixture.WID,fixture.ACTOR,fixture.RID,fixture.EID
        self.hosted=SimpleNamespace(coworker=self.svc.coworker,notifications=SimpleNamespace())
        self.active=0; self.sql=[]; original=self.repo.transaction; execute=self.repo.execute
        @contextmanager
        def transaction(*args,**kwargs):
            with original(*args,**kwargs) as value:
                self.active+=1
                try: yield value
                finally: self.active-=1
        self.repo.transaction=transaction
        def sql(text,args): self.sql.append((text,args)); return execute(text,args)
        self.repo.execute=sql; self.repo.fetchone=lambda: (media_jobs.KIND,)
        self.png=media_runtime._png(bytes(range(256))*(media_runtime.WIDTH*media_runtime.HEIGHT//256)+bytes(range(64)))
        self.sha=hashlib.sha256(self.png).hexdigest()
        self.document={'extraction':{'state':'extracted','clips':[{'language':'yue','original_text':'原句 unchanged','at_seconds':.5}]},
                       'pattern':{'qualification':'unqualified'},'artifacts':{self.sha:base64.b64encode(self.png).decode()}}
        self.document['manifest_digest']=contracts.digest(self.document)
        self.coordinator=Mock()
        def read(wid,actor,rid):
            self.assertEqual(self.active,0); self.assertEqual((wid,actor,rid),(self.wid,self.actor,self.result_id))
            return deepcopy(self.document)
        def enqueue(wid,actor,clips,**kwargs):
            self.assertEqual(self.active,1); self.assertIs(kwargs['cursor'],self.repo)
            return {'state':'queued','job_id':self.job_id,'result_id':self.result_id}
        def run(scope,jid,*,deadline):
            self.assertEqual(self.active,0); self.assertEqual((scope,jid),('workspace:'+self.wid,self.job_id))
            return {'state':'extracted','job_id':jid,'result_id':self.result_id,'qualification':'unqualified'}
        self.coordinator.read.side_effect=read; self.coordinator.enqueue.side_effect=enqueue; self.coordinator.run.side_effect=run
        guard=patch.object(media_jobs,'MediaJobs',return_value=self.coordinator); self.factory=guard.start(); self.addCleanup(guard.stop)

    def path(self,artifact=False):
        return ['media','results',self.result_id]+(['artifacts',self.sha] if artifact else [])

    def test_manifest_refs_preserve_metadata_without_embedded_images_and_get_never_dispatches(self):
        status,_,response=self.request(self.path())
        self.assertEqual(status,200); data=response['data']
        self.assertEqual(set(data),{'result_id','manifest_digest','extraction','pattern','artifact_refs'})
        self.assertEqual(data['extraction'],self.document['extraction'])
        self.assertEqual(data['artifact_refs'],[{'sha256':self.sha,'mime_type':'image/png','byte_length':len(self.png),
            'url':f'/api/workspaces/{self.wid}/coworker/trends/media/results/{self.result_id}/artifacts/{self.sha}'}])
        self.assertNotIn(base64.b64encode(self.png).decode(),json.dumps(response))
        self.coordinator.enqueue.assert_not_called(); self.coordinator.run.assert_not_called()

    def test_individual_artifact_is_png_with_exact_digest_and_private_headers(self):
        status,headers,raw=self.request(self.path(True))
        self.assertEqual((status,raw),(200,self.png)); self.assertEqual(headers['Content-Type'],'image/png')
        self.assertEqual(headers['X-Content-Type-Options'],'nosniff'); self.assertEqual(headers['Referrer-Policy'],'no-referrer')
        self.assertIn('sandbox',headers['Content-Security-Policy'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(),self.sha)
        self.coordinator.enqueue.assert_not_called(); self.coordinator.run.assert_not_called()

    def test_admission_in_transaction_run_outside_with_explicit_180_second_deadline(self):
        status,_,data=self.request(['media','jobs'],method='POST',payload={'clips':[],'idempotency_key':'wire-only'})
        self.assertEqual(status,201); self.assertEqual(data['data']['job_id'],self.job_id)
        with patch('time.monotonic',return_value=12345):
            self.assertEqual(self.request(['media','jobs',self.job_id,'run'],method='POST')[0],200)
        self.coordinator.run.assert_called_once_with('workspace:'+self.wid,self.job_id,deadline=12525)
        self.assertTrue(any(args==('workspace:'+self.wid,self.job_id) and 'scope_key=%s AND job_id=%s' in sql for sql,args in self.sql))

    def test_session_api_token_tenant_and_role_are_authorized_before_coordinator_calls(self):
        for token,expected in (('',401),('wrong',401),('prt_example',403)):
            self.assertEqual(self.request(self.path(True),token=token)[0],expected)
        self.assertEqual(self.request(self.path(True),workspace=fixture.OTHER)[0],404)
        self.factory.assert_not_called()
        self.repo.role='viewer'
        self.assertEqual(self.request(self.path(True))[0],200)
        self.assertEqual(self.request(['media','jobs',self.job_id,'run'],method='POST')[0],403)
        self.coordinator.run.assert_not_called()

    def test_default_off_each_required_flag_and_missing_allowlist_never_reads_or_dispatches(self):
        initial=dict(self.svc.values)
        for flags in ({},{**initial,'RAFII_TREND_WORKSPACE_ALLOWLIST':''},
                      *({**initial,'RAFII_TREND_'+name+'_ENABLED':'0'} for name in ('INTELLIGENCE','RADAR','TRUST_RECEIPTS','MULTIMODAL'))):
            self.svc.values=flags
            for path,method in ((self.path(),'GET'),(self.path(True),'GET'),(['media','jobs',self.job_id,'run'],'POST')):
                self.assertEqual(self.request(path,method=method)[0],403)
        self.factory.assert_not_called()

    def test_current_coordinator_expiry_deletion_rights_and_membership_denials_are_safe(self):
        for code in ('media_expired','media_supplied_asset_unavailable','media_current_right_not_permitted','media_current_modality_denied','workspace_access_denied'):
            self.coordinator.read.side_effect=contracts.ContractError(code)
            for path in (self.path(),self.path(True)):
                status,_,data=self.request(path)
                self.assertEqual(status,410); self.assertEqual(data['code'],'evidence_unavailable')
                self.assertNotIn(code,json.dumps(data))
        self.coordinator.run.assert_not_called()

    def test_query_body_method_and_route_negatives_never_dispatch(self):
        for query in ('unknown=1','x=1&x=2','token=session','&','x='*40):
            for path,method in ((self.path(),'GET'),(self.path(True),'GET'),(['media','jobs',self.job_id,'run'],'POST')):
                self.assertEqual(self.request(path,method=method,query=query)[0],400)
        for payload in ([],False,0,'',{'force':True}):
            self.assertEqual(self.request(['media','jobs',self.job_id,'run'],method='POST',payload=payload)[0],400)
        self.assertEqual(self.request(self.path(),payload={'hidden':'body'})[0],400)
        self.assertEqual(self.request(self.path(True),extra={'HTTP_TRANSFER_ENCODING':'chunked'})[0],400)
        for path,method in ((['media','jobs'],'GET'),(['media','jobs',self.job_id,'run'],'GET'),(self.path(),'POST'),
                            (self.path(True),'POST'),(['media','results',self.result_id,'artifacts'],'GET'),
                            (self.path(True)+['extra'],'GET'),(['media'],'GET')):
            self.assertEqual(self.request(path,method=method)[0],404)
        self.factory.assert_not_called()

    def test_identifiers_and_missing_wrong_kind_jobs_do_not_execute(self):
        for path in (['media','results','not-uuid'],['media','results',self.result_id,'artifacts','../x'],
                     ['media','results',self.result_id,'artifacts','A'*64],['media','results',self.result_id,'artifacts','f'*63]):
            self.assertEqual(self.request(path)[0],400)
        for record in (None,('trend.ingest',)):
            self.repo.fetchone=lambda: record
            self.assertEqual(self.request(['media','jobs',self.job_id,'run'],method='POST')[0],404)
        self.coordinator.read.assert_not_called(); self.coordinator.run.assert_not_called()

    def test_missing_corrupt_non_png_and_digest_mismatched_artifacts_fail_closed(self):
        self.assertEqual(self.request(['media','results',self.result_id,'artifacts','0'*64])[0],404)
        for encoded in ('%%%','é',base64.b64encode(b'<script>private</script>').decode(),base64.b64encode(self.png+b'changed').decode()):
            self.document['artifacts'][self.sha]=encoded
            self.assertEqual(self.request(self.path(True))[0],410)

    def test_png_strict_three_mib_and_manifest_utf8_size_limit(self):
        for size,status in ((3*1024*1024-1,200),(3*1024*1024,413)):
            raw=self.png+b'\0'*(size-len(self.png)); self.sha=hashlib.sha256(raw).hexdigest()
            self.document['artifacts']={self.sha:base64.b64encode(raw).decode()}
            self.assertEqual(self.request(self.path(True))[0],status)
        self.document['artifacts']={}
        self.document['extraction']['text']='中'*1_600_000
        status,_,response=self.request(self.path())
        self.assertEqual(status,413); self.assertLess(len(json.dumps(response)),1000)
        self.document['extraction']['text']='中'*100
        self.assertEqual(self.request(self.path())[0],200)

    def test_coworker_registers_media_deletion_effect_once_without_replacing_other_effect(self):
        self.assertIn(self.svc.coworker._trend_edit_effect,self.repo.effects)
        self.assertEqual(self.repo.effects.count(media_jobs.capture_asset_changes),1)
        CoworkerService(self.svc.hosted,values={})
        self.assertEqual(self.repo.effects.count(media_jobs.capture_asset_changes),1)


@unittest.skipUnless(os.environ.get('POSTRIFF_TEST_DSN'),'explicit disposable media HTTP PostgreSQL required')
class MediaHTTPPostgres(Offline,Wire):
    @classmethod
    def setUpClass(cls):
        durable.MediaPostgres.setUpClass()

    def setUp(self):
        super().setUp()
        self.fixture=durable.MediaPostgres('test_actual_asset_job_chunks_private_pattern_and_fenced_completion')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        f=self.fixture; self.wid=f.workspace
        def verify(token):
            if token!='session': raise AlphaError('bad session',401)
            return f.actor
        repository=PostgresWorkspaceRepository(f.store.connection_factory,verify)
        hosted=SimpleNamespace(repository=repository,connection_factory=f.store.connection_factory,assets=f.hosted.assets,
            ideas=SimpleNamespace(_state=IdeasService._state,_member=IdeasService._member))
        cw=CoworkerService(hosted,values=f.flags,clock=time.time)
        self.svc=TrendService(cw,store_factory=lambda factory:f.store); cw._trends=self.svc
        self.hosted=SimpleNamespace(coworker=cw,notifications=SimpleNamespace())
        self.real_coordinator=f.worker
        # Only explicit local storage/runtime fixtures are injected. Service,
        # routes, SQL repository, current rights and durable coordinator are real.
        guard=patch.object(media_jobs,'MediaJobs',return_value=f.worker); guard.start(); self.addCleanup(guard.stop)

    def create(self):
        f=self.fixture
        status,_,response=self.request(['media','jobs'],method='POST',payload={'clips':f.request,'idempotency_key':'actual-http'})
        self.assertEqual(status,201); job=response['data']
        status,_,result=self.request(['media','jobs',job['job_id'],'run'],method='POST')
        self.assertEqual(status,200); self.assertEqual(result['data']['state'],'extracted')
        path=['media','results',job['result_id']]
        status,_,manifest=self.request(path); self.assertEqual(status,200)
        ref=manifest['data']['artifact_refs'][0]
        return job,path,path+['artifacts',ref['sha256']],manifest

    def test_actual_authenticated_admission_run_manifest_and_individual_png_no_get_dispatch(self):
        f=self.fixture; job,path,artifact,manifest=self.create()
        calls=list(f.storage_calls); runtime_calls=f.runtime_calls
        with patch.object(f.worker,'run',side_effect=AssertionError('GET dispatch')),patch.object(f.worker,'enqueue',side_effect=AssertionError('GET admission')):
            self.assertEqual(self.request(path)[0],200)
            status,headers,raw=self.request(artifact)
        self.assertEqual(status,200); self.assertEqual(hashlib.sha256(raw).hexdigest(),artifact[-1])
        self.assertTrue(raw.startswith(b'\x89PNG\r\n\x1a\n')); self.assertLess(len(raw),3*1024*1024)
        self.assertEqual(f.storage_calls,calls); self.assertEqual(f.runtime_calls,runtime_calls)
        self.assertNotIn('artifacts',manifest['data'])
        self.assertEqual(f.query("SELECT to_regclass('public.pr_runtime') IS NULL")[0][0],True)

    def test_real_current_raw_modality_expiry_and_display_gates_both_read_routes(self):
        f=self.fixture; _,path,artifact,_=self.create()
        for operation in ('store_raw','display_excerpt','display_link','retrieve','retain_derivatives'):
            f.mutate_grant(operation)
            for route in (path,artifact): self.assertEqual(self.request(route)[0],410)
            f.mutate_grant(operation,'allow')
        f.query("UPDATE pr_trend_observations SET provenance=jsonb_set(provenance,'{media_modality_rights,visual,state}','\"deny\"') WHERE observation_id=%s",(f.sid,))
        self.assertEqual(self.request(artifact)[0],410)
        f.query("UPDATE pr_trend_observations SET provenance=jsonb_set(provenance,'{media_modality_rights,visual,state}','\"allow\"') WHERE observation_id=%s",(f.sid,))
        f.query("UPDATE pr_trend_observations SET rights=jsonb_set(rights,'{store_raw,expires_at}',%s::jsonb) WHERE observation_id=%s",(json.dumps(durable.BEFORE),f.sid))
        self.assertEqual(self.request(path)[0],410); self.assertEqual(self.request(artifact)[0],410)

    def test_real_membership_tenant_token_default_off_and_account_deletion(self):
        f=self.fixture; _,path,artifact,_=self.create()
        self.assertEqual(self.request(artifact,workspace=str(uuid.uuid4()))[0],404)
        self.assertEqual(self.request(artifact,token='wrong')[0],401)
        self.assertEqual(self.request(artifact,token='prt_example')[0],403)
        self.svc.values['RAFII_TREND_MULTIMODAL_ENABLED']='false'
        self.assertEqual(self.request(artifact)[0],403)
        self.svc.values['RAFII_TREND_MULTIMODAL_ENABLED']='true'
        f.query("UPDATE pr_memberships SET status='revoked' WHERE workspace_id=%s",(self.wid,))
        self.assertEqual(self.request(artifact)[0],404)
        f.query("UPDATE pr_memberships SET status='active' WHERE workspace_id=%s",(self.wid,))
        f.query("UPDATE pr_workspaces SET state=state||'{\"accountDeletion\":true}'::jsonb WHERE id=%s",(self.wid,))
        self.assertNotEqual(self.request(path)[0],200); self.assertNotEqual(self.request(artifact)[0],200)

    def test_actual_repository_effect_hides_completed_artifacts_and_cancels_pending_without_flags(self):
        f=self.fixture; _,path,artifact,_=self.create()
        pending=f.enqueue('pending-effect'); self.svc.values.clear()
        repository=self.svc.repository
        self.assertEqual(repository.effects.count(media_jobs.capture_asset_changes),1)
        revision=f.query('SELECT revision FROM pr_workspaces WHERE id=%s',(self.wid,))[0][0]
        def remove(state,actor):
            state['phase2']['assets'][0]['deletionPending']=True
            return state
        repository.command(self.wid,'session',revision,remove)
        self.assertEqual(f.query('SELECT state FROM pr_trend_jobs WHERE job_id=%s',(pending['job_id'],))[0][0],'cancelled')
        self.svc.values.update(f.flags)
        self.assertEqual(self.request(path)[0],410); self.assertEqual(self.request(artifact)[0],410)
        f.worker.sweep(workspace_id=self.wid)
        self.assertEqual(f.query("SELECT count(*) FROM pr_trend_manifest_chunks WHERE scope_key=%s AND payload<>'{}'",(f.scope,))[0][0],0)


if __name__=='__main__': unittest.main()
