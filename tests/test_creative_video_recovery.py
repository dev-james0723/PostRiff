"""Local media, admission and recovery contracts. No provider or database connections."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.creative_video import CreativeVideoService, local_media_slot
from postriff_phase2.creative_video_assets import validate_generated_clip
from postriff_phase2.creative_video_media import analyze_reference
from postriff_phase2 import creative_video_media_provider as video_provider
from postriff_phase2.creative_video_media_provider import VideoProvider, output_profile
from postriff_phase2.creative_video_store import ProjectStore
from postriff_phase2.credit_meter import millicredits
from postriff_phase2.deployment import isolated_environment


FILES = Path(__file__).resolve().parents[1] / 'docs/creative-intelligence/examples/timer-study'
CONFIG = {'RAFII_CREATIVE_VIDEO_PROVIDER': 'vertex-veo', 'RAFII_CREATIVE_VIDEO_PROJECT': 'test-project',
          'RAFII_CREATIVE_VIDEO_ACCESS_TOKEN': 'fictional-test-value'}


class SafeRouting(unittest.TestCase):
    def test_transport_bounds_the_body_and_does_not_follow_redirects(self):
        with patch.object(video_provider.http.client, 'HTTPSConnection') as make:
            connection = make.return_value
            response = connection.getresponse.return_value
            response.status = 302
            self.assertEqual(video_provider._transport('/v1/test',{},'test-token',16),(302,{}))
            response.read1.assert_not_called()
            make.assert_called_once()
            self.assertEqual(make.call_args.args,(video_provider.HOST,))
            self.assertEqual(connection.request.call_args.args[:2],('POST','/v1/test'))
            response.status = 200
            response.getheader.side_effect = lambda k, *_: {'Content-Type':'application/json','Content-Length':'17'}.get(k)
            with self.assertRaises(ValueError):
                video_provider._transport('/v1/test',{},'test-token',16)
            response.read1.assert_not_called()
            response.getheader.side_effect = lambda k, *_: 'application/json' if k=='Content-Type' else None
            response.read1.side_effect = [b'{"state":',b'"ok"}',b'']
            self.assertEqual(video_provider._transport('/v1/test',{},'test-token',16),(200,{'state':'ok'}))
            self.assertEqual(connection.close.call_count,3)

    def test_provider_reports_a_removed_operation_without_replaying_it(self):
        provider = VideoProvider.from_environment(CONFIG)
        provider.transport = Mock(return_value=(410, {}))
        with self.assertRaises(AlphaError) as missing:
            provider.poll(provider.model_path + '/operations/old-one')
        self.assertEqual(missing.exception.code, 'creative_video_operation_unavailable')
        self.assertEqual(provider.transport.call_count, 1)
        self.assertTrue(provider.transport.call_args.args[0].endswith('fetchPredictOperation'))

    def test_local_worker_capacity_recovers_after_a_rejected_third_request(self):
        with local_media_slot(), local_media_slot():
            with self.assertRaises(AlphaError) as caught, local_media_slot():
                self.fail("A third decoder was admitted.")
            self.assertEqual(caught.exception.code, "creative_video_worker_busy")
        with local_media_slot():
            pass

    def test_unwired_service_cannot_read_ambient_paid_credentials(self):
        with patch.dict(os.environ, CONFIG):
            self.assertFalse(CreativeVideoService(object()).catalog()['available'])
            self.assertTrue(CreativeVideoService(object(), provider_environment=CONFIG).catalog()['available'])
            with self.assertRaises(AlphaError):
                VideoProvider.from_environment({**CONFIG, 'VERCEL_ENV': 'preview'})

    def test_preview_rejects_even_well_formed_paid_configuration(self):
        staging, production = 'a'*20, 'b'*20
        env = {'VERCEL_ENV':'preview','POSTRIFF_ENVIRONMENT':'staging','POSTRIFF_STAGING_PROJECT_REF':staging,
               'POSTRIFF_PRODUCTION_PROJECT_REF':production, 'POSTRIFF_DATABASE_URL':f'postgresql://postgres@db.{staging}.supabase.co/db?sslmode=require',
               'POSTRIFF_SUPABASE_URL':f'https://{staging}.supabase.co','NEXT_PUBLIC_SUPABASE_URL':f'https://{staging}.supabase.co',
               'POSTRIFF_PUBLIC_BASE_URL':'https://preview.example', 'POSTRIFF_STAGING_PUBLIC_BASE_URL':'https://preview.example'}
        self.assertNotEqual(isolated_environment(env).get('RAFII_CREATIVE_VIDEO_PROVIDER'), 'vertex-veo')
        for key, value in CONFIG.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                isolated_environment({**env, key:value})

    def test_credit_policy_and_exact_estimate_required_for_customer(self):
        book = Mock()
        service = CreativeVideoService(SimpleNamespace(ledger=SimpleNamespace(credits=book)))
        approval = {'actor':'member', 'model':'model', 'estimatedUsdMicro':400000}
        provider = SimpleNamespace(model='model', provider='route')
        with patch('postriff_phase2.creative_video.ops_metadata', return_value=None), patch('postriff_phase2.creative_video.ai_usage_exempt', return_value=False):
            book.policy.return_value = None
            with self.assertRaises(AlphaError) as caught:
                service._credit_authority(None, 'workspace', 2, approval, provider, {})
            self.assertEqual(caught.exception.code, 'creative_video_credit_policy_required')
            book.policy.return_value = 'approved'
            with self.assertRaises(AlphaError):
                service._credit_authority(None, 'workspace', 2, approval, provider, {'maxMilliCredits':1})
            book.issue.return_value = {'quoteId':'quote'}
            auth = service._credit_authority(None, 'workspace', 2, approval, provider, {'maxMilliCredits':millicredits(400000)})
            self.assertIs(auth, book.authorize.return_value)
        book.issue.assert_called_once()
        with patch('postriff_phase2.creative_video.ops_metadata', return_value={'operatorId':'member'}):
            self.assertIsNone(service._credit_authority(None, 'workspace', 2, approval, provider, {}))
        book.issue.assert_called_once()


class Recovery(unittest.TestCase):
    def test_final_transition_uses_the_concurrently_saved_provider_usage(self):
        store, ledger = Mock(), Mock()
        service = CreativeVideoService(SimpleNamespace(ledger=ledger), store=store)
        job = {"state":"pending","provider":"runway","idempotencyKey":"take","operation":"saved","reservationId":"hold"}
        store.locked_usage_job.return_value = {"providerUsage":{"costSource":"provider_task_usage","costUsdMicro":480000}}
        self.assertTrue(service._transition(None, "w", job, "failed", outcome="unknown", reason="provider_operation_unavailable"))
        ledger.settle.assert_called_once_with(None,"w","hold","failed",480000)
        self.assertEqual(store.update_job.call_args.args[-1]["actualUsdMicro"],480000)
        store.locked_usage_job.return_value["reason"] = "provider_usage_disputed"
        service._transition(None,"w",job,"failed",outcome="unknown")
        ledger.settle.assert_called_with(None,"w","hold","unknown",None)

    def test_founder_environment_and_worker_pause_use_the_same_scope(self):
        store = Mock()
        store.paused_models.return_value = {"veo-3.1-fast-generate-001"}
        service = CreativeVideoService(None,store=store,provider_environment={"RAFII_CONTROL_ENVIRONMENT":"production"})
        service.catalog("cursor")
        store.paused_models.assert_called_once_with("cursor","production")
        self.assertEqual(service.deployment,"production")
        conflict = CreativeVideoService(None,provider_environment={"VERCEL_ENV":"preview","RAFII_CONTROL_ENVIRONMENT":"production"})
        self.assertIsNone(conflict.deployment)
        self.assertFalse(any(m["available"] for m in conflict.catalog()["models"] if m["mediaKind"]=="generated"))

    def test_revoked_result_is_terminal_and_a_prior_completion_cannot_be_reversed(self):
        store, ledger, output = Mock(), Mock(), Mock()
        key = 'creative-video:take'
        scene = {'sceneId':'one','take':'take'}
        job = {'idempotencyKey': key,'operation':'saved','state':'pending','reservationId':'hold',
               'promptDigest':hashlib.sha256(b'approved').hexdigest()}
        store.jobs.return_value = {key:job}
        service = CreativeVideoService(SimpleNamespace(ledger=ledger),store=store)
        project = {'scenes':[scene,{'sceneId':'two','take':'unrelated-edit'}]}
        with patch('postriff_phase2.creative_video.active_workspace_row', return_value=(1, {}, 'owner',False,False,False,False)), patch.object(service, '_reference'), patch('postriff_phase2.creative_video.blueprint.generation_prompt',
                return_value='approved') as prepare:
            self.assertTrue(service._authorized_result(None,'workspace',project,scene,job,{},output=output))
            store.update_job.assert_not_called()
            prepare.side_effect=AlphaError('Cloud preference revoked.',403)
            self.assertFalse(service._authorized_result(None,'workspace',project,scene,job,{},cost=200,output=output))
            store.update_job.assert_called_once_with(None,'workspace',key,'pending',
                                                     {'state':'failed','reason':'authorization_changed','actualUsdMicro':200})
            ledger.settle.assert_called_once_with(None,'workspace','hold','failed',200)
            output.abort.assert_called_once_with(None,'authorization_changed')
            store.jobs.return_value = {key:{**job,'state':'completed','assetId':output.id}}
            self.assertFalse(service._authorized_result(None,'workspace',project,scene,job,{},output=output))
            output.abort.assert_called_once()

    def test_native_reconciliation_frees_unidentified_take_and_returns_actual_cost(self):
        cur = Mock()
        cur.fetchall.return_value = [({'state':'unknown','reason':'submission_unknown','idempotencyKey':'creative-video:key'},'actual',12345),
                                    ({'state':'completed','idempotencyKey':'creative-video:other','actualUsdMicro':None},'released',0)]
        jobs = ProjectStore().jobs(cur, 'workspace', [{'take':'key'}, {'take':'other'}])
        self.assertEqual(jobs['creative-video:key']['state'],'failed')
        self.assertEqual(jobs['creative-video:key']['actualUsdMicro'],12345)
        self.assertEqual(jobs['creative-video:other']['actualUsdMicro'],0)
        self.assertEqual(jobs['creative-video:other']['state'],'completed')

    def test_stale_claim_records_unknown_once_without_provider_access(self):
        ledger, store = Mock(), Mock()
        service = CreativeVideoService(SimpleNamespace(ledger=ledger),store=store)
        job = {'idempotencyKey':'key','state':'submitting','reservationId':'hold'}
        store.stale_submissions.return_value=[job]
        store.update_job.side_effect=[True,False]
        service._recover_claims(None,'workspace')
        service._recover_claims(None,'workspace')
        ledger.settle.assert_called_once_with(None,'workspace','hold','unknown',None)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'native media worker required')
class RealMedia(unittest.TestCase):
    def test_generated_take_requires_decodable_changing_frames_and_duration(self):
        def encode(source, codec):
            return subprocess.check_output(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',source,'-t','1',*codec,
                '-movflags','+frag_keyframe+empty_moov','-f','mp4','pipe:1'])
        audio_only = encode('sine=f=440:r=8000',['-c:a','aac'])
        still = encode('color=gray:s=64x64:r=24',['-c:v','libx264','-bf','0'])
        self.assertFalse(analyze_reference(still)["measured"]["hasChangingFrames"])
        real = (FILES/'original-cut.mp4').read_bytes()
        target = output_profile(1250, '9:16')
        valid = validate_generated_clip(real,target)
        self.assertEqual((valid['durationMs'],valid['width'],valid['fps'],valid['hasAudio'],valid['decodedFrameCount']),
                         (4000,720,24,True,96))
        static_profile = {'durationMs':1000,'width':64,'height':64,'fps':24,'hasAudio':False}
        cases = ((audio_only,target),(still,static_profile),((FILES/'original-1.mp4').read_bytes(),target),
                 (real,output_profile(7000,'9:16')),(real,output_profile(1000,'16:9')),
                 (real,{**target,'fps':30}),(b'not a video',target))
        for raw, profile in cases:
            with self.subTest(profile=profile,size=len(raw)), self.assertRaises(AlphaError) as error:
                validate_generated_clip(raw,profile)
            self.assertEqual(error.exception.code,'creative_video_provider_output_unusable')
