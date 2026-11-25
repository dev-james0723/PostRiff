"""Independent040-only durable media proof; synthetic grants/storage, real SQL/FFmpeg."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from postriff_phase2.growth.trends import contracts, media_jobs as M, media_runtime, retention, revocation
from postriff_phase2.growth.trends.store import TrendStore
from test_trend_metrics import fixture

NOW = contracts.iso(datetime.now(timezone.utc)-timedelta(seconds=2))
BEFORE = contracts.iso(contracts.instant(NOW)-timedelta(minutes=10))
AFTER = contracts.iso(contracts.instant(NOW)+timedelta(days=1))
PERMISSIONS = {k:{'state':'allow','policy_ref':'synthetic-media-grant-v1','audience_scope':'shared:fixture','expires_at':AFTER}
               for k in contracts.PERMISSIONS}


def dedicated_test_dsn(environ=None):
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from local_pg_target import selected_target
    env=os.environ if environ is None else environ
    target=selected_target(env, validate_fixture_dsns=False)
    if any(env.get(k) for k in ('PGSERVICE','PGHOSTADDR')): raise ValueError('libpq overrides forbidden')
    raw=env.get('POSTRIFF_TEST_DSN')
    if not raw: raise ValueError('explicit portable local media DSN required')
    p=conninfo_to_dict(raw)
    if set(p)-{'host','port','dbname','user'} or (p.get('host'),p.get('port'),p.get('dbname'))!=('127.0.0.1',str(target.port),'postgres'):
        raise ValueError('only the selected disposable runner database is allowed')
    return make_conninfo(**p,connect_timeout='5')


class Offline(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect','socket.create_connection','socket.getaddrinfo',
                       'urllib.request.urlopen','urllib.request.OpenerDirector.open'):
            guard=patch(target,side_effect=AssertionError('no media network/model/provider calls'))
            mock=guard.start(); self.addCleanup(guard.stop); self.addCleanup(mock.assert_not_called)


class Contracts(Offline):
    def test_dsn_refuses_remote_overrides_and_application_database(self):
        good={'POSTRIFF_TEST_DSN':'host=127.0.0.1 port=55438 dbname=postgres'}
        self.assertIn('connect_timeout=5',dedicated_test_dsn(good))
        for env in ({},{**good,'PGHOSTADDR':'127.0.0.1'}, {**good,'PGSERVICE':'prod'},
                    {'POSTRIFF_TEST_DSN':'host=127.0.0.1 port=5432 dbname=postgres'},
                    {'POSTRIFF_TEST_DSN':'host=remote.invalid port=55438 dbname=postgres'},
                    {'POSTRIFF_TEST_DSN':good['POSTRIFF_TEST_DSN']+' options=-csafe=off'}):
            with self.assertRaises(ValueError): dedicated_test_dsn(env)

    def test_flags_off_never_opens_database_or_resolves_assets(self):
        def forbidden(): raise AssertionError('disabled database connection')
        worker=M.MediaJobs(SimpleNamespace(),store=TrendStore(forbidden),values={})
        wid,actor=str(uuid.uuid4()),str(uuid.uuid4())
        self.assertEqual(worker.enqueue(wid,actor,[],idempotency_key='off')['state'],'disabled')
        self.assertEqual(worker.run('workspace:'+wid,str(uuid.uuid4()))['state'],'disabled')
        with self.assertRaisesRegex(ValueError,'disabled'): worker.read(wid,actor,str(uuid.uuid4()))

    def test_request_rejects_paths_extra_commands_arrays_and_wrong_frame_type(self):
        source=str(uuid.uuid4()); base={'asset_id':uuid.uuid4().hex,'source_id':source,'language':'yue','modalities':['visual'],'frame_count':1}
        for change in ({'asset_id':'../private.mp4'},{'command':'ffmpeg'},{'modalities':[{}]},{'frame_count':True}):
            with self.assertRaises(ValueError): M._requests([{**base,**change}])
        with self.assertRaises(ValueError): M._requests([base,base])


@unittest.skipUnless(os.environ.get('POSTRIFF_TEST_DSN'),'explicit disposable local PG not configured')
class MediaPostgres(Offline):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.pg=psycopg; cls.dsn=dedicated_test_dsn()
        cls.ffmpeg,cls.ffprobe=shutil.which('ffmpeg'),shutil.which('ffprobe')
        if not cls.ffmpeg or not cls.ffprobe: raise RuntimeError('validation_unavailable: installed FFmpeg/ffprobe required')
        with psycopg.connect(cls.dsn) as db:
            if db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0]: raise AssertionError('003 must remain absent')
            if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]: raise RuntimeError('use portable media wrapper')
        with tempfile.TemporaryDirectory(prefix='trend-media-synthetic-') as tmp:
            path=Path(tmp)/'generated.mp4'
            subprocess.run([cls.ffmpeg,'-v','error','-nostdin','-f','lavfi','-i','testsrc2=size=64x48:rate=4:duration=2',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=8000:duration=2','-c:v','mpeg4','-q:v','4','-c:a','aac',
                '-threads','1','-movflags','+faststart',str(path)],check=True,capture_output=True,timeout=15,
                env={'PATH':'/usr/bin:/bin','LC_ALL':'C'})
            cls.video=path.read_bytes()
            noisy=Path(tmp)/'generated-detail.mp4'
            subprocess.run([cls.ffmpeg,'-v','error','-nostdin','-f','lavfi','-i',
                'testsrc2=size=160x90:rate=12:duration=2,noise=alls=30:allf=t:all_seed=42',
                '-c:v','mpeg4','-q:v','2','-threads','1','-movflags','+faststart',str(noisy)],
                check=True,capture_output=True,timeout=15,env={'PATH':'/usr/bin:/bin','LC_ALL':'C'})
            cls.detailed_video=noisy.read_bytes()

    def setUp(self):
        super().setUp()
        self.active=0; self.storage_calls=[]; self.runtime_calls=0
        self.workspace,self.actor,self.sid=map(str,(uuid.uuid4(),uuid.uuid4(),uuid.uuid4()))
        self.scope='workspace:'+self.workspace; self.asset_id=uuid.uuid4().hex
        self.provider='synthetic-media-'+uuid.uuid4().hex
        self.asset={'id':self.asset_id,'kind':'video','category':'video','mime':'video/mp4',
                    'objectName':self.asset_id+'.mp4','bytes':len(self.video),'etag':'synthetic-etag',
                    'hash':hashlib.sha256(b'metadata fingerprint, deliberately not raw bytes').hexdigest(),
                    'processing':'ready','deleted':False,'deletionPending':False}
        self.state={'phase2':{'assets':[self.asset]}}
        with self.pg.connect(self.dsn) as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)',(self.actor,))
            db.execute('INSERT INTO pr_profiles(user_id) VALUES(%s)',(self.actor,))
            db.execute('INSERT INTO pr_workspaces(id,state) VALUES(%s,%s::jsonb)',(self.workspace,json.dumps(self.state)))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')",(self.workspace,self.actor))
        @contextmanager
        def connect():
            with self.pg.connect(self.dsn) as db:
                db.execute('SET ROLE service_role')
                self.active+=1
                try: yield db
                finally: self.active-=1
        self.store=TrendStore(connect,offline_replay=True)
        self.rights={k:{**v,'audience_scope':self.scope} for k,v in PERMISSIONS.items()}
        self.rights['llm_process']['state']='deny'; self.rights['store_embeddings']['state']='deny'
        self.modalities={m:deepcopy(self.rights['retrieve']) for m in media_runtime.MODALITIES}
        self.policy={'id':'synthetic-media','provider_id':self.provider,'version':'media-v1','scope_key':self.scope,
            'operation':'read','rights':self.rights,'effective_at':BEFORE,'expires_at':AFTER,'retention_seconds':2*86400,
            'readiness':'ready','reviewed_by':'synthetic-local-acceptance','review_ref':'synthetic-rights-only',
            'media_extraction':{'version':'1','approved':True,'deployment':{'qualified':True,'review_ref':'synthetic-installed-binary-proof',
                'runtime_sha256':hashlib.sha256(Path(media_runtime.__file__).read_bytes()).hexdigest(),
                'ffmpeg_sha256':hashlib.sha256(Path(self.ffmpeg).read_bytes()).hexdigest(),
                'ffprobe_sha256':hashlib.sha256(Path(self.ffprobe).read_bytes()).hexdigest()},
                'limits':{'max_bytes':1_000_000,'max_output_bytes':500_000,'max_tokens':1000,'max_processing_seconds':10,
                          'max_cost_micro_usd':0,'max_frames':12},'modality_rights':self.modalities,
                'asset_bindings':[{'workspace_id':self.workspace,'asset_id':self.asset_id,'asset_hash':self.asset['hash'],
                                   'source_id':self.sid,'media_sha256':hashlib.sha256(self.video).hexdigest()}]}}
        self.store.register_contract(self.provider,'media-contract-v1',list(contracts.PERMISSIONS),BEFORE,AFTER)
        self.store.register_policy(self.policy,provider_contract_version='media-contract-v1')
        source=deepcopy(fixture()['observations'][0])
        source.update(scope_key=self.scope,provider_id=self.provider,provider_contract_version='media-contract-v1',source_policy_version='media-v1',
            observation_id=self.sid,source_identity='synthetic-source-'+self.sid,revision_identity='v1',revision_sequence=1,
            rights=self.rights,available_at=BEFORE,received_at=BEFORE,event_at=BEFORE,retention_until=AFTER)
        source['payload'].pop('text',None)  # Critical: raw binary must not depend on an invented text field.
        source['payload']['native_id']=self.sid; source['payload_digest']=contracts.digest(source['payload'])
        source['provenance']['media_modality_rights']=self.modalities
        self.store.put_observation(source); self.source=source
        self.flags={'RAFII_TREND_WORKSPACE_ALLOWLIST':self.workspace,**{'RAFII_TREND_'+n+'_ENABLED':'true'
            for n in ('INTELLIGENCE','RADAR','TRUST_RECEIPTS','MULTIMODAL')}}
        self.storage=SimpleNamespace(object_info=self.info,read_range=self.range)
        self.hosted=SimpleNamespace(assets=SimpleNamespace(storage=self.storage),
            billing=SimpleNamespace(pricing_v2_enabled=False),
            clock=lambda:datetime.now(timezone.utc).timestamp())
        self.worker=M.MediaJobs(self.hosted,store=self.store,values=self.flags,runtime_factory=self.make_runtime,
                               storage_factory=self.fixture_storage)
        self.request=[{'asset_id':self.asset_id,'source_id':self.sid,'language':'yue','modalities':['visual','audio'],'frame_count':3}]
        self.addCleanup(self.cleanup_jobs)

    def cleanup_jobs(self):
        with self.pg.connect(self.dsn) as db:
            db.execute("UPDATE pr_trend_jobs SET state='cancelled',payload='{}',lease_owner=NULL,lease_until=NULL WHERE scope_key=%s AND state IN ('queued','retry_wait','leased','running')",(self.scope,))

    def info(self,wid,category,name):
        self.assertEqual(self.active,0,'storage call inside an open DB transaction')
        self.assertEqual((wid,category,name),(self.workspace,'video',self.asset['objectName']))
        self.storage_calls.append('head')
        return {k:self.asset[k] for k in ('bytes','mime','etag')}

    def range(self,wid,category,name,start,length):
        self.assertEqual(self.active,0,'storage call inside an open DB transaction')
        self.assertEqual((wid,category,name,start,length),(self.workspace,'video',self.asset['objectName'],0,len(self.video)))
        self.storage_calls.append('range')
        return {'data':self.video,'ranged':True}

    def make_runtime(self,*args,**kwargs):
        self.assertEqual(self.active,0)
        runtime=media_runtime.MediaRuntime(*args,**kwargs)
        execute=runtime.execute
        def run(*a,**kw):
            self.assertEqual(self.active,0,'decoder started inside transaction')
            self.runtime_calls+=1
            self.last_runtime_job=deepcopy(a[0])
            return execute(*a,**kw)
        runtime.execute=run
        return runtime

    def fixture_storage(self,storage,*,deadline):
        # Explicit in-process local fixture only. Production accepts only the
        # real private adapter and always uses fresh isolated transport children.
        self.assertEqual(self.active,0)
        def call(name,*args):
            M.media_storage.remaining(deadline)
            result=getattr(storage,name)(*args)
            M.media_storage.remaining(deadline)
            return result
        return SimpleNamespace(object_info=lambda *a:call('object_info',*a),read_range=lambda *a:call('read_range',*a))

    def query(self,sql,args=()):
        with self.pg.connect(self.dsn) as db:
            cur=db.execute(sql,args)
            return cur.fetchall() if cur.description else []

    def enqueue(self,key='request-one'):
        return self.worker.enqueue(self.workspace,self.actor,self.request,idempotency_key=key)

    def execute(self):
        job=self.enqueue(); result=self.worker.run(self.scope,job['job_id']); return job,result

    def mutate_grant(self,operation,state='deny',policy=False):
        table='pr_trend_source_policies' if policy else 'pr_trend_observations'
        self.query("UPDATE "+table+" SET rights=jsonb_set(rights,%s,%s::jsonb) WHERE scope_key=%s",
                   ([operation,'state'],json.dumps(state),self.scope))

    def test_actual_asset_job_chunks_private_pattern_and_fenced_completion(self):
        job,thin=self.execute()
        self.assertEqual(thin['state'],'extracted'); self.assertEqual(self.runtime_calls,1)
        self.assertEqual(set(thin),{'job_id','result_id','manifest_id','state','clip_count','qualification'})
        stored=self.worker.read(self.workspace,self.actor,job['result_id'])
        self.assertEqual(stored['extraction']['clips'][0]['metadata']['duration_seconds'],2)
        self.assertEqual(len(stored['pattern']['patterns'][0]['modalities']['visual']['items']),3)
        self.assertEqual(stored['pattern']['qualification'],'unqualified')
        self.assertEqual(len(stored['artifacts']),3)
        self.assertGreater(len(stored['extraction']['method']['executables']),0)
        self.assertEqual(self.query('SELECT state,payload,reservation_id,provider_id FROM pr_trend_jobs WHERE job_id=%s',(job['job_id'],))[0],('succeeded',{},None,None))
        maximum=self.query('SELECT max(octet_length(payload::text)) FROM pr_trend_manifest_chunks WHERE scope_key=%s',(self.scope,))[0][0]
        self.assertLessEqual(maximum,65536)
        self.assertEqual(self.query("SELECT to_regclass('public.pr_runtime') IS NULL")[0][0],True)

    def test_idempotency_does_not_refetch_or_reextract(self):
        job,thin=self.execute(); calls=len(self.storage_calls)
        self.assertEqual(self.enqueue()['job_id'],job['job_id'])
        self.assertTrue(self.worker.run(self.scope,job['job_id'])['replayed'])
        self.assertEqual(self.runtime_calls,1); self.assertEqual(len(self.storage_calls),calls)

    def test_private_asset_metadata_hash_is_never_used_as_raw_digest(self):
        self.assertNotEqual(self.asset['hash'],hashlib.sha256(self.video).hexdigest())
        job,_=self.execute()
        found=self.worker.read(self.workspace,self.actor,job['result_id'])
        self.assertEqual(found['extraction']['clips'][0]['media_sha256'],hashlib.sha256(self.video).hexdigest())

    def test_rollback_after_chunks_leaves_no_projection_or_output_chunks(self):
        job=self.enqueue()
        with patch.object(self.store,'put_projection',side_effect=ValueError('synthetic final insert failure')):
            with self.assertRaisesRegex(ValueError,'synthetic final'): self.worker.run(self.scope,job['job_id'])
        self.assertEqual(self.query('SELECT count(*) FROM pr_trend_projections WHERE scope_key=%s',(self.scope,))[0][0],0)
        self.assertEqual(self.query('SELECT count(*) FROM pr_trend_manifest_chunks WHERE scope_key=%s',(self.scope,))[0][0],0)
        self.assertEqual(self.query('SELECT state,payload FROM pr_trend_jobs WHERE job_id=%s',(job['job_id'],))[0],('failed_terminal',{}))

    def test_current_raw_denial_blocks_metadata_only_ancestors_and_purges_chunks(self):
        job,thin=self.execute()
        self.mutate_grant('store_raw')
        with self.assertRaisesRegex(ValueError,'current_right_not_permitted'): self.worker.read(self.workspace,self.actor,job['result_id'])
        result=self.worker.sweep(workspace_id=self.workspace)
        self.assertGreaterEqual(result['invalidated'],1)
        self.assertEqual(self.query("SELECT count(*) FROM pr_trend_manifest_chunks WHERE scope_key=%s AND payload<>'{}'",(self.scope,))[0][0],0)
        self.assertFalse(self.query('SELECT payload FROM pr_trend_projections WHERE scope_key=%s',(self.scope,))[0][0])

    def test_current_policy_raw_denial_at_final_commit_discards_complete_extraction(self):
        job=self.enqueue(); real=self.worker._pattern
        original=self.make_runtime
        def factory(*a,**kw):
            runtime=original(*a,**kw); execute=runtime.execute
            def wrapped(*x,**y):
                result=execute(*x,**y)
                self.mutate_grant('store_raw',policy=True)
                return result
            runtime.execute=wrapped; return runtime
        self.worker.runtime_factory=factory
        with self.assertRaisesRegex(ValueError,'current_right_not_permitted'): self.worker.run(self.scope,job['job_id'])
        self.assertEqual(self.query('SELECT count(*) FROM pr_trend_manifest_chunks WHERE scope_key=%s',(self.scope,))[0][0],0)

    def test_source_modality_revocation_before_dispatch_makes_zero_storage_calls(self):
        job=self.enqueue()
        self.query("UPDATE pr_trend_observations SET provenance=jsonb_set(provenance,'{media_modality_rights,visual,state}','\"deny\"') WHERE observation_id=%s",(self.sid,))
        with self.assertRaisesRegex(ValueError,'modality_denied'): self.worker.run(self.scope,job['job_id'])
        self.assertEqual(self.storage_calls,[])
        self.assertEqual(self.query('SELECT state FROM pr_trend_jobs WHERE job_id=%s',(job['job_id'],))[0][0],'cancelled')

    def test_modality_expiry_raw_unknown_and_wrong_scope_never_admit(self):
        for operation in M.OPS:
            self.mutate_grant(operation,'unknown')
            with self.assertRaises(ValueError): self.enqueue()
            self.mutate_grant(operation,'allow')
        self.query("UPDATE pr_trend_observations SET provenance=jsonb_set(provenance,'{media_modality_rights,audio,expires_at}',%s::jsonb) WHERE observation_id=%s",(json.dumps(BEFORE),self.sid))
        with self.assertRaisesRegex(ValueError,'modality_denied'): self.enqueue()
        self.assertEqual(self.storage_calls,[])

    def test_membership_and_tenant_are_current_not_the_enqueue_snapshot(self):
        job,_=self.execute()
        with self.assertRaises(ValueError): self.worker.read(self.workspace,str(uuid.uuid4()),job['result_id'])
        self.query("UPDATE pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s",(self.workspace,self.actor))
        with self.assertRaisesRegex(ValueError,'workspace_access_denied'): self.worker.read(self.workspace,self.actor,job['result_id'])

    def test_flag_off_after_enqueue_does_not_dispatch(self):
        job=self.enqueue(); self.flags['RAFII_TREND_MULTIMODAL_ENABLED']='false'
        self.assertEqual(self.worker.run(self.scope,job['job_id'])['state'],'disabled')
        self.assertEqual(self.storage_calls,[])

    def test_unqualified_deployment_and_changed_executable_hash_refuse_admission(self):
        for path,value in (('{media_extraction,deployment,qualified}',False),('{media_extraction,deployment,ffprobe_sha256}','0'*64)):
            self.query('UPDATE pr_trend_source_policies SET manifest=jsonb_set(manifest,%s,%s::jsonb) WHERE scope_key=%s',
                       (path,json.dumps(value),self.scope))
            with self.assertRaises(ValueError): self.enqueue()
            self.query('UPDATE pr_trend_source_policies SET manifest=%s::jsonb WHERE scope_key=%s',(json.dumps(self.policy),self.scope))
        self.assertEqual(self.storage_calls,[])

    def test_queued_method_change_is_cancelled(self):
        job=self.enqueue()
        identity=M.method_identity(); identity['artifact_digest']='0'*64
        with patch.object(M,'method_identity',return_value=identity), self.assertRaisesRegex(ValueError,'method_changed'):
            self.worker.run(self.scope,job['job_id'])
        self.assertEqual(self.query('SELECT state FROM pr_trend_jobs WHERE job_id=%s',(job['job_id'],))[0][0],'cancelled')
        self.assertEqual(self.storage_calls,[])

    def test_asset_effect_invalidates_pending_and_completed_work_before_physical_delete(self):
        completed,thin=self.execute(); pending=self.enqueue('pending')
        before=deepcopy(self.state); after=deepcopy(before); after['phase2']['assets'][0]['deletionPending']=True
        with self.pg.connect(self.dsn) as db,db.cursor() as cur:
            cur.execute('UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(after),self.workspace))
            M.capture_asset_changes(cur,self.workspace,before,after,self.actor)
        self.assertEqual(self.query('SELECT state,payload FROM pr_trend_jobs WHERE job_id=%s',(pending['job_id'],))[0],('cancelled',{}))
        with self.assertRaises(ValueError): self.worker.read(self.workspace,self.actor,completed['result_id'])
        self.flags.clear(); self.worker.sweep(workspace_id=self.workspace)
        self.assertEqual(self.query("SELECT count(*) FROM pr_trend_manifest_chunks WHERE scope_key=%s AND payload<>'{}'",(self.scope,))[0][0],0)

    def test_source_tombstone_cascades_to_media_chunks(self):
        job,thin=self.execute()
        revocation.revoke_source(self.store,self.scope,self.provider,self.source['source_identity'])
        with self.assertRaises(ValueError): self.worker.read(self.workspace,self.actor,job['result_id'])
        retention.sweep(self.store)
        self.assertEqual(self.query("SELECT count(*) FROM pr_trend_manifest_chunks WHERE scope_key=%s AND payload<>'{}'",(self.scope,))[0][0],0)

    def test_storage_digest_mismatch_is_terminal_and_leaves_no_temp_output(self):
        job=self.enqueue(); self.storage.read_range=lambda *a,**kw:{'data':b'x'*len(self.video),'ranged':True}
        with self.assertRaisesRegex(ValueError,'asset_digest_mismatch'): self.worker.run(self.scope,job['job_id'])
        self.assertEqual(self.runtime_calls,0)
        self.assertEqual(self.query('SELECT count(*) FROM pr_trend_manifest_chunks WHERE scope_key=%s',(self.scope,))[0][0],0)

    def test_no_background_fetch_or_requeue_from_sweep(self):
        self.enqueue(); self.worker.sweep()
        self.assertEqual(self.storage_calls,[]); self.assertEqual(self.runtime_calls,0)

    def test_actual_generated_frames_span_multiple_bounded_chunks_and_purge_together(self):
        self.video=self.detailed_video
        self.asset.update(bytes=len(self.video),etag='synthetic-detail-etag',hash=hashlib.sha256(b'detailed metadata').hexdigest())
        binding=self.policy['media_extraction']['asset_bindings'][0]
        binding.update(asset_hash=self.asset['hash'],media_sha256=hashlib.sha256(self.video).hexdigest())
        self.query('UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(self.state),self.workspace))
        self.query('UPDATE pr_trend_source_policies SET manifest=%s::jsonb WHERE scope_key=%s',(json.dumps(self.policy),self.scope))
        self.request[0].update(modalities=['visual'],frame_count=6)
        job,thin=self.execute(); result=self.worker.read(self.workspace,self.actor,job['result_id'])
        self.assertEqual(len(result['artifacts']),6)
        self.assertGreater(self.query('SELECT count(*) FROM pr_trend_manifest_chunks WHERE manifest_id=%s',(thin['manifest_id'],))[0][0],1)
        self.assertTrue(all(base.startswith('iVBOR') for base in result['artifacts'].values()))
        self.assertEqual(result['extraction']['usage']['model_tokens'],0)
        self.assertEqual(result['extraction']['usage']['cost_micro_usd'],0)
        self.assertLessEqual(self.query('SELECT max(octet_length(payload::text)) FROM pr_trend_manifest_chunks WHERE scope_key=%s',(self.scope,))[0][0],65536)
        self.mutate_grant('store_raw'); self.worker.sweep(workspace_id=self.workspace)
        self.assertEqual(self.query("SELECT count(*) FROM pr_trend_manifest_chunks WHERE scope_key=%s AND payload<>'{}'",(self.scope,))[0][0],0)

    def test_sweep_keyset_reaches_invalid_root_after_healthy_page_and_wraps(self):
        roots=[]
        for i in range(4):
            job=self.enqueue('rotation-'+str(i))
            roots.append(self.query('SELECT payload FROM pr_trend_jobs WHERE job_id=%s',(job['job_id'],))[0][0]['binding_manifest_id'])
            self.worker.jobs.cancel(self.scope,job['job_id'])
        roots.sort()
        self.query("UPDATE pr_trend_input_manifests SET recipe=jsonb_set(recipe,'{fingerprint}',%s::jsonb) WHERE manifest_id=%s",
                   (json.dumps('0'*64),roots[-1]))
        self.assertEqual(self.worker.sweep(limit=2,workspace_id=self.workspace)['invalidated'],0)
        self.assertEqual(self.worker.sweep(limit=2,workspace_id=self.workspace)['invalidated'],1)
        self.assertFalse(self.query('SELECT postriff_private.trend_node_valid(%s,%s)',(self.scope,roots[-1]))[0][0])
        self.assertEqual(self.worker.sweep(limit=2,workspace_id=self.workspace)['scanned'],2)
        generation=self.query('SELECT generation FROM pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s',
                              (self.scope,M.SCAN_PROVIDER,M.SCAN_PARTITION))[0][0]
        self.assertEqual(generation,3)
        self.assertEqual(self.storage_calls,[])

    def test_asset_effect_rollback_restores_current_read_and_job_state(self):
        job,_=self.execute(); pending=self.enqueue('pending-rollback')
        after=deepcopy(self.state); after['phase2']['assets'][0]['deletionPending']=True
        with self.assertRaisesRegex(RuntimeError,'rollback asset effect'):
            with self.pg.connect(self.dsn) as db,db.cursor() as cur:
                cur.execute('UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(after),self.workspace))
                M.capture_asset_changes(cur,self.workspace,self.state,after,self.actor)
                raise RuntimeError('rollback asset effect')
        self.assertEqual(self.query('SELECT state FROM pr_trend_jobs WHERE job_id=%s',(pending['job_id'],))[0][0],'queued')
        self.assertEqual(self.worker.read(self.workspace,self.actor,job['result_id'])['extraction']['state'],'extracted')

    def test_revocation_between_storage_calls_prevents_range_read(self):
        job=self.enqueue(); original=self.info
        def info(*a):
            result=original(*a); self.mutate_grant('store_raw'); return result
        self.storage.object_info=info
        with self.assertRaisesRegex(ValueError,'current_right_not_permitted'): self.worker.run(self.scope,job['job_id'])
        self.assertEqual(self.storage_calls,['head']); self.assertEqual(self.runtime_calls,0)

    def test_display_denial_does_not_load_raw_result_chunks(self):
        job,_=self.execute(); self.mutate_grant('display_excerpt')
        with patch.object(self.store,'get_manifest',side_effect=AssertionError('denied raw chunk load')):
            with self.assertRaisesRegex(ValueError,'display_denied'): self.worker.read(self.workspace,self.actor,job['result_id'])

    def test_two_supplied_clips_share_source_without_losing_binding_and_bound_twelve_frames(self):
        other=deepcopy(self.asset); other['id']=uuid.uuid4().hex; other['objectName']=other['id']+'.mp4'
        self.state['phase2']['assets'].append(other)
        binding=deepcopy(self.policy['media_extraction']['asset_bindings'][0]); binding['asset_id']=other['id']
        self.policy['media_extraction']['asset_bindings'].append(binding)
        self.query('UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(self.state),self.workspace))
        self.query('UPDATE pr_trend_source_policies SET manifest=%s::jsonb WHERE scope_key=%s',(json.dumps(self.policy),self.scope))
        self.request[0]['frame_count']=6
        self.request.append({**deepcopy(self.request[0]),'asset_id':other['id']})
        def info(wid,category,name):
            self.assertEqual(self.active,0); self.assertEqual((wid,category),(self.workspace,'video'))
            self.assertIn(name,[self.asset['objectName'],other['objectName']]); self.storage_calls.append('head')
            return {k:self.asset[k] for k in ('bytes','mime','etag')}
        def read_range(wid,category,name,start,length):
            info(wid,category,name); self.assertEqual((start,length),(0,len(self.video)))
            self.storage_calls.append('range'); return {'data':self.video,'ranged':True}
        self.storage.object_info=info; self.storage.read_range=read_range
        job,thin=self.execute(); result=self.worker.read(self.workspace,self.actor,job['result_id'])
        self.assertEqual(thin['clip_count'],2)
        self.assertEqual(result['extraction']['usage']['frames'],12)
        self.assertEqual(len(result['pattern']['patterns']),2)
        self.assertEqual(self.storage_calls.count('range'),2)

    def test_lost_lease_after_extraction_never_commits_chunks_and_staging_is_cleaned(self):
        job=self.enqueue(); original=self.make_runtime; directories=[]; real_temp=M.tempfile.TemporaryDirectory
        def temporary(*a,**kw):
            temp=real_temp(*a,**kw); directories.append(Path(temp.name)); return temp
        def factory(*a,**kw):
            runtime=original(*a,**kw); execute=runtime.execute
            def wrapped(*x,**y):
                result=execute(*x,**y)
                self.query('UPDATE pr_trend_jobs SET lease_generation=lease_generation+1 WHERE job_id=%s',(job['job_id'],))
                return result
            runtime.execute=wrapped; return runtime
        self.worker.runtime_factory=factory
        with patch.object(M.tempfile,'TemporaryDirectory',side_effect=temporary),self.assertRaisesRegex(ValueError,'stale_job_fence'):
            self.worker.run(self.scope,job['job_id'])
        self.assertTrue(directories); self.assertTrue(all(not d.exists() for d in directories))
        self.assertEqual(self.query('SELECT count(*) FROM pr_trend_manifest_chunks WHERE scope_key=%s',(self.scope,))[0][0],0)

    def test_outer_budget_reduces_decoder_budget_and_rejects_unsupported_transport(self):
        job=self.enqueue()
        self.worker.run(self.scope,job['job_id'],deadline=time.monotonic()+5)
        self.assertLess(self.last_runtime_job['limits']['max_processing_seconds'],5)
        other=self.enqueue('unsupported'); self.worker.storage_factory=M.media_storage.BoundedStorage
        previous=len(self.storage_calls)
        with self.assertRaisesRegex(ValueError,'unsupported_transport'): self.worker.run(self.scope,other['job_id'])
        self.assertEqual(len(self.storage_calls),previous)

    def test_deadline_expiring_inside_final_transaction_rolls_back_all_output(self):
        job=self.enqueue(); deadline=time.monotonic()+30; original=self.worker._pattern; timer=[]
        def pattern(*a):
            result=original(*a)
            guard=patch.object(M.time,'monotonic',return_value=deadline+1); guard.start(); timer.append(guard)
            return result
        try:
            with patch.object(self.worker,'_pattern',side_effect=pattern),self.assertRaisesRegex(ValueError,'media_storage_deadline'):
                self.worker.run(self.scope,job['job_id'],deadline=deadline)
        finally:
            for guard in timer: guard.stop()
        self.assertEqual(self.query('SELECT count(*) FROM pr_trend_manifest_chunks WHERE scope_key=%s',(self.scope,))[0][0],0)
        self.assertEqual(self.query('SELECT count(*) FROM pr_trend_projections WHERE scope_key=%s',(self.scope,))[0][0],0)


if __name__=='__main__': unittest.main()
