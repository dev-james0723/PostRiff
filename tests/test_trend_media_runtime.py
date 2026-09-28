"""WP17 actual local media extraction and adversarial boundaries; no live I/O."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
import hashlib
import io
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import uuid
import wave

from postriff_phase2.growth.trends import contracts, media_runtime as M

NOW = '2026-09-27T20:01:00Z'
BEFORE = '2026-09-27T19:00:00Z'
AFTER = '2026-09-28T20:01:00Z'
WORKSPACE = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
ACTOR = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
SOURCE = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
CLIP = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
SCOPE = 'workspace:' + WORKSPACE
GRANT = {'state': 'allow', 'policy_ref': 'synthetic-media-policy-v1', 'audience_scope': SCOPE, 'expires_at': AFTER}
PERMISSIONS = {name: deepcopy(GRANT) for name in contracts.PERMISSIONS}
FLAGS = {'RAFII_TREND_WORKSPACE_ALLOWLIST': WORKSPACE,
         **{'RAFII_TREND_' + name + '_ENABLED': 'true' for name in ('INTELLIGENCE', 'RADAR', 'TRUST_RECEIPTS', 'MULTIMODAL')}}
SRT = '1\n00:00:00,000 --> 00:00:00,400\n廣東話原句：今日做咩呀？\n\n2\n00:00:00,400 --> 00:00:00,900\n混合 English，唔好改字😀\n'.encode()


def wav_bytes(seconds=1):
    raw = io.BytesIO()
    with wave.open(raw, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(b''.join(struct.pack('<h', round(10000 * math.sin(2 * math.pi * 440 * n / 8000)))
                               for n in range(int(seconds * 8000))))
    return raw.getvalue()


class Offline(unittest.TestCase):
    def setUp(self):
        for name in ('socket.create_connection', 'socket.socket.connect', 'socket.getaddrinfo',
                     'urllib.request.urlopen', 'urllib.request.OpenerDirector.open'):
            guard = patch(name, side_effect=AssertionError('no network/provider calls in media acceptance'))
            mock = guard.start(); self.addCleanup(guard.stop); self.addCleanup(mock.assert_not_called)


class TranscriptParsing(Offline):
    def test_original_native_text_and_exact_timecodes_are_preserved(self):
        result = M.parse_transcript(SRT, format='srt', duration_seconds=1, max_tokens=1000)
        self.assertEqual([c['text'] for c in result['items']], ['廣東話原句：今日做咩呀？', '混合 English，唔好改字😀'])
        self.assertEqual([(c['start_seconds'], c['end_seconds']) for c in result['items']], [(0, .4), (.4, .9)])
        self.assertEqual(result['items'][1]['original_timecode'], '00:00:00,400 --> 00:00:00,900')
        self.assertFalse(result['translated']); self.assertFalse(result['asr_performed'])
        self.assertEqual(result['text_token_upper_bound'], len(SRT))

    def test_webvtt_multiline_overlap_and_source_markup_preserved(self):
        raw = b'WEBVTT\n\ncue-a\n00:00.100 --> 00:00.600\n<c.en>hello</c>\nsecond line\n\ncue-b\n00:00.500 --> 00:00.900\nworld\n'
        result = M.parse_transcript(raw, format='vtt', duration_seconds=1, max_tokens=1000)
        self.assertEqual(result['items'][0]['text'], '<c.en>hello</c>\nsecond line')
        self.assertEqual(result['quality_flags'], ['overlapping_cues'])

    def test_caption_bytes_time_order_encoding_and_count_are_bounded(self):
        for raw, fmt, duration, cap in ((SRT, 'srt', 1, 1), (SRT, 'srt', .8, 1000),
                (b'1\n00:00:00,900 --> 00:00:00,100\nwrong', 'srt', 1, 1000),
                (b'1\nNaN --> infinity\nwrong', 'srt', 1, 1000),
                (b'1\n00:00:00,000 --> 00:00:00,100\n\xff', 'srt', 1, 1000),
                (b'not WEBVTT', 'vtt', 1, 1000), (SRT, 'ass', 1, 1000),
                ((b'1\n00:00:00,000 --> 00:00:00,100\na\n\n' * 513), 'srt', 1, 65536),
                (SRT, 'srt', float('inf'), 1000), (SRT, 'srt', True, 1000), (SRT, 'srt', 1, True)):
            with self.subTest(fmt=fmt, duration=duration, cap=cap), self.assertRaises(ValueError):
                M.parse_transcript(raw, format=fmt, duration_seconds=duration, max_tokens=cap)


class LocalMedia(Offline):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg, cls.ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
        if not cls.ffmpeg or not cls.ffprobe:
            raise unittest.SkipTest('validation_unavailable: installed ffmpeg+ffprobe required for actual media proof')
        cls.generated = tempfile.TemporaryDirectory(prefix='trend-media-generated-', dir=Path(tempfile.gettempdir()).resolve())
        cls.addClassCleanup(cls.generated.cleanup)
        video = Path(cls.generated.name) / 'generated.mp4'
        command = [cls.ffmpeg, '-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=4:duration=2',
                   '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=8000:duration=2', '-c:v', 'mpeg4',
                   '-q:v', '4', '-c:a', 'aac', '-threads', '1', '-movflags', '+faststart', str(video)]
        subprocess.run(command, check=True, capture_output=True, timeout=15, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        cls.video = video.read_bytes()
        cls.rational_videos = {}
        for rate in ('12', '30000/1001'):
            rational = Path(cls.generated.name) / ('rate-' + rate.replace('/', '-') + '.mp4')
            subprocess.run([cls.ffmpeg, '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                           'testsrc2=size=64x48:rate=' + rate + ':duration=2', '-c:v', 'mpeg4',
                           '-threads', '1', '-movflags', '+faststart', str(rational)],
                           check=True, capture_output=True, timeout=15, env={'PATH':'/usr/bin:/bin','LC_ALL':'C'})
            cls.rational_videos[rate] = rational.read_bytes()

    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory(prefix='trend-media-test-', dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.scratch = self.root / 'scratch'; self.scratch.mkdir()
        self.raw = wav_bytes()
        (self.root / 'clip.wav').write_bytes(self.raw)
        (self.root / 'caption.srt').write_bytes(SRT)
        self.source = {'scope_key': SCOPE, 'revision': 1, 'payload_digest': 'a' * 64, 'deleted': False,
                       'available_at': BEFORE, 'retention_until': AFTER, 'rights': deepcopy(PERMISSIONS),
                       'policy_rights': deepcopy(PERMISSIONS), 'modality_rights': {m: deepcopy(GRANT) for m in M.MODALITIES},
                       'policy_modality_rights': {m: deepcopy(GRANT) for m in M.MODALITIES}}
        self.snapshot = {'workspace_id': WORKSPACE, 'actor_id': ACTOR, 'authorized': True, 'checked_at': NOW,
                         'valid_until': AFTER, 'authorized_source_scopes': [SCOPE], 'sources': {SOURCE: self.source}}
        self.authorizer = Mock(side_effect=lambda job: deepcopy(self.snapshot))
        self.job = {'schema_version': M.SCHEMA, 'job_id': str(uuid.uuid4()), 'workspace_id': WORKSPACE,
                    'actor_id': ACTOR, 'scope_key': SCOPE, 'decision_cutoff': NOW, 'expires_at': AFTER,
                    'limits': {'max_bytes': 2_000_000, 'max_output_bytes': 500_000, 'max_tokens': 2000,
                               'max_processing_seconds': 15, 'max_cost_micro_usd': 0, 'max_frames': 12},
                    'clips': [{'clip_id': CLIP, 'source_id': SOURCE, 'source_scope': SCOPE, 'source_revision': 1,
                               'source_digest': 'a' * 64, 'media_sha256': hashlib.sha256(self.raw).hexdigest(),
                               'caption_sha256': hashlib.sha256(SRT).hexdigest(), 'language': 'yue-en',
                               'modalities': ['transcript', 'audio', 'ocr'], 'frame_count': 0}]}
        self.files = {CLIP: {'media': 'clip.wav', 'transcript': 'caption.srt', 'transcript_format': 'srt'}}
        self.bind_attachment()
        self.runtime = M.MediaRuntime(self.root, values=FLAGS.copy(), temp_root=self.scratch, clock=lambda: NOW)
        self.addCleanup(self.assert_cleanup)

    def assert_cleanup(self):
        self.assertEqual(list(self.scratch.iterdir()), [], 'all owned temporary media must be removed')

    def execute(self):
        return self.runtime.execute(self.job, self.files, authorize=self.authorizer)

    def bind_attachment(self):
        # Explicit synthetic source-to-supplied-attachment authorization.
        self.source['media_bindings'] = [{k: self.job['clips'][0][k] for k in ('media_sha256', 'caption_sha256')}]

    def video_job(self, frames=3):
        (self.root / 'clip.mp4').write_bytes(self.video)
        self.files[CLIP]['media'] = 'clip.mp4'
        self.job['clips'][0].update(media_sha256=hashlib.sha256(self.video).hexdigest(),
                                    modalities=['transcript', 'visual', 'audio', 'ocr'], frame_count=frames)
        self.bind_attachment()

    def test_real_wav_probe_caption_and_numeric_audio_are_not_fixture_outputs(self):
        original = deepcopy(self.job)
        result = self.execute(); manifest = result.manifest
        self.assertEqual(self.job, original)
        self.assertEqual(manifest['state'], 'extracted')
        clip = manifest['clips'][0]
        self.assertEqual(clip['metadata']['duration_seconds'], 1)
        self.assertEqual(clip['metadata']['streams'][0]['codec_name'], 'pcm_s16le')
        audio = clip['modalities']['audio']['items'][0]['descriptor']
        self.assertEqual(audio['sample_count'], 8000)
        self.assertAlmostEqual(audio['peak_amplitude'], 10000 / 32768, places=4)
        self.assertAlmostEqual(audio['rms_amplitude'], 10000 / 32768 / math.sqrt(2), places=4)
        self.assertEqual(clip['modalities']['transcript']['items'][0]['text'], '廣東話原句：今日做咩呀？')
        self.assertEqual(clip['asr']['state'], 'unavailable'); self.assertEqual(clip['ocr']['state'], 'unavailable')
        self.assertEqual(clip['modalities']['audio']['semantic_findings'], [])
        self.assertEqual(manifest['usage']['cost_micro_usd'], 0)
        self.assertEqual(manifest['usage']['model_tokens'], 0)
        self.assertFalse(manifest['full_video_understanding'])
        self.assertEqual(manifest['qualification'], 'unqualified')
        self.assertEqual(manifest['dependencies'][0]['source_digest'], 'a' * 64)
        self.assertTrue(manifest['deletion']['temporary_copies_removed'])
        self.assertEqual((self.root / 'clip.wav').read_bytes(), self.raw)
        self.assertGreaterEqual(self.authorizer.call_count, 5)
        self.assertEqual(manifest['method']['executables']['ffprobe']['sha256'], hashlib.sha256(Path(self.ffprobe).read_bytes()).hexdigest())
        self.assertEqual(manifest['method']['executables']['ffmpeg']['sha256'], hashlib.sha256(Path(self.ffmpeg).read_bytes()).hexdigest())
        self.assertEqual(manifest['method']['artifact_sha256'], hashlib.sha256(Path(M.__file__).read_bytes()).hexdigest())

    def test_authorization_callback_advances_clock_and_returns_current_snapshot(self):
        clock = [contracts.instant(NOW)]
        self.runtime.clock = lambda: contracts.iso(clock[0])
        def authorize(job):
            clock[0] += timedelta(milliseconds=10)
            return {**deepcopy(self.snapshot), 'checked_at': contracts.iso(clock[0])}
        self.authorizer.side_effect = authorize
        self.assertEqual(self.execute().manifest['state'], 'extracted')

    def test_job_expiring_during_authorization_fails_before_file_read(self):
        clock = [contracts.instant(NOW)]
        self.runtime.clock = lambda: contracts.iso(clock[0])
        def authorize(job):
            clock[0] = contracts.instant(AFTER)
            return {**deepcopy(self.snapshot), 'checked_at': contracts.iso(clock[0])}
        self.authorizer.side_effect = authorize
        with patch.object(M, '_safe_open', side_effect=AssertionError('expired read')):
            with self.assertRaisesRegex(ValueError, 'media_job_expired_or_future'): self.execute()

    def test_authorization_future_timestamp_still_rejected_after_callback(self):
        self.snapshot['checked_at'] = contracts.iso(contracts.instant(NOW) + timedelta(seconds=1))
        with patch.object(M, '_safe_open', side_effect=AssertionError('future snapshot read')):
            with self.assertRaisesRegex(ValueError, 'media_current_snapshot_required'): self.execute()

    def test_deadline_expiring_during_authorization_fails_before_file_read(self):
        clock = [0.0]
        def authorize(job):
            clock[0] = 16.0
            return deepcopy(self.snapshot)
        self.authorizer.side_effect = authorize
        with patch.object(M.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(M, '_safe_open', side_effect=AssertionError('late read')):
            with self.assertRaisesRegex(ValueError, 'media_processing_deadline'): self.execute()

    def test_actual_mp4_frames_have_png_bytes_bound_timecodes_and_no_semantics(self):
        self.video_job()
        result = self.execute(); clip = result.manifest['clips'][0]
        frames = clip['modalities']['visual']['items']
        self.assertEqual(len(frames), 3); self.assertEqual(result.manifest['usage']['frames'], 3)
        self.assertEqual([f['at_seconds'] for f in frames], [0, .75, 1.5])
        for frame in frames:
            blob = result.artifacts[frame['frame_id']]
            self.assertTrue(blob.startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertEqual(hashlib.sha256(blob).hexdigest(), frame['frame_id'])
            self.assertEqual(struct.unpack('>II', blob[16:24]), (160, 90))
        self.assertGreater(len(set(result.artifacts)), 1)
        self.assertEqual(clip['modalities']['visual']['semantic_findings'], [])
        self.assertEqual(result.manifest['usage']['output_bytes'], sum(map(len, result.artifacts.values())) + len(contracts.canonical(result.manifest).encode()))

    def test_real_fractional_rate_and_fractional_sampling_preserve_native_pts(self):
        for rate, raw in self.rational_videos.items():
            with self.subTest(rate=rate):
                self.video = raw; self.video_job(frames=6)
                result = self.execute(); frames = result.manifest['clips'][0]['modalities']['visual']['items']
                actual = [f['at_seconds'] for f in frames]
                self.assertEqual(len(frames),6); self.assertEqual(actual, sorted(actual))
                self.assertTrue(all(f['at_seconds'] >= f['requested_at_seconds'] for f in frames))
                if rate == '12': self.assertEqual(actual[1], float(Fraction(1,3)))
                else:
                    self.assertTrue(all(abs(t*30000/1001-round(t*30000/1001)) < 1e-10 for t in actual))

    def test_native_pts_rejects_out_of_order_before_request_future_and_invalid_base(self):
        logs = b'config in time_base: 1/12, frame_rate: 12/1\nn: 0 pts: 16 pts_time:1.33333'
        self.assertEqual(M._frame_time(logs,Fraction(4,3),Fraction(2)),Fraction(4,3))
        for requested,duration,previous in ((Fraction(1),Fraction(2),Fraction(3,2)),
                                            (Fraction(3,2),Fraction(2),None),
                                            (Fraction(1),Fraction(1),None)):
            with self.assertRaisesRegex(ValueError,'media_frame_timecode_invalid'):
                M._frame_time(logs,requested,duration,previous)
        with self.assertRaisesRegex(ValueError,'media_frame_timecode_invalid'):
            M._frame_time(logs.replace(b'1/12',b'1/0'),Fraction(0),Fraction(2))

    def test_process_argv_uses_only_fd_pipe_and_never_supplied_paths_or_shell(self):
        real = subprocess.Popen
        with patch.object(M.subprocess, 'Popen', wraps=real) as spy:
            self.execute()
        self.assertGreaterEqual(spy.call_count, 2)
        for call in spy.call_args_list:
            args = call.args[0]
            self.assertEqual(args[args.index('-protocol_whitelist') + 1], 'fd,pipe')
            self.assertEqual(args[args.index('-i') + 1], 'fd:')
            self.assertFalse(call.kwargs['shell'])
            self.assertTrue(call.kwargs['start_new_session'])
            self.assertNotIn(str(self.root / 'clip.wav'), args)

    def test_shell_metacharacters_in_literal_filename_do_not_execute(self):
        name = 'clip;$(touch OWNED).wav'
        (self.root / name).write_bytes(self.raw)
        self.files[CLIP]['media'] = name
        self.assertEqual(self.execute().manifest['state'], 'extracted')
        self.assertFalse((self.root / 'OWNED').exists())

    def test_flags_off_and_allowlist_missing_do_not_read_or_spawn_or_authorize(self):
        for values in ({}, {**FLAGS, 'RAFII_TREND_WORKSPACE_ALLOWLIST': ''},
                       {**FLAGS, 'RAFII_TREND_MULTIMODAL_ENABLED': 'false'}, {**FLAGS, 'RAFII_TREND_RADAR_ENABLED': 'false'}):
            runtime = M.MediaRuntime('/no/such/root', values=values, clock=lambda: NOW)
            with patch.object(M, '_safe_open', side_effect=AssertionError('disabled read')), patch.object(M, '_run', side_effect=AssertionError('disabled spawn')):
                self.assertEqual(runtime.execute(self.job, self.files, authorize=self.authorizer).manifest['state'], 'disabled')
        self.authorizer.assert_not_called()

    def test_model_and_embedding_denial_does_not_block_permitted_local_measurement(self):
        for kind in ('rights', 'policy_rights'):
            for permission in ('llm_process', 'store_embeddings', 'train_or_finetune'):
                self.source[kind][permission]['state'] = 'deny'
        result = self.execute().manifest
        self.assertEqual(result['clips'][0]['modalities']['audio']['state'], 'available')
        self.assertEqual(result['model_execution'], 'unavailable_no_qualified_model_or_cohort')
        self.assertEqual(result['embedding_execution'], 'not_requested')

    def test_unknown_expired_scope_and_missing_operation_grants_fail_before_file_read(self):
        base = deepcopy(self.source)
        for kind in ('rights', 'policy_rights'):
            for change in ({'state': 'unknown'}, {'expires_at': NOW}, {'audience_scope': 'shared:other'}):
                for permission in M.BASE_RIGHTS:
                    with self.subTest(kind=kind, change=change, permission=permission):
                        self.source.clear(); self.source.update(deepcopy(base))
                        self.source[kind][permission].update(change)
                        with patch.object(M, '_safe_open', side_effect=AssertionError('unauthorized file read')), self.assertRaises(ValueError):
                            self.execute()
        self.source.clear(); self.source.update(base)
        self.source['rights'].pop('store_embeddings')
        with self.assertRaisesRegex(ValueError, 'explicit_operation_grants'):
            self.execute()

    def test_modality_denials_are_independent_and_no_audio_is_decoded(self):
        self.source['modality_rights']['audio']['state'] = 'unknown'
        real = M._run
        with patch.object(M, '_run', wraps=real) as spy:
            output = self.execute().manifest['clips'][0]
        self.assertEqual(spy.call_count, 1)  # probe only
        self.assertEqual(output['modalities']['transcript']['state'], 'available')
        self.assertEqual(output['modalities']['audio']['reason'], 'current_modality_right_not_permitted')

    def test_all_modalities_denied_and_ocr_only_never_read_media(self):
        for grant in self.source['modality_rights'].values(): grant['state'] = 'deny'
        with patch.object(M, '_safe_open', side_effect=AssertionError('no permitted modality read')):
            result = self.execute().manifest
        self.assertEqual(result['state'], 'unavailable')
        self.assertEqual(result['usage']['input_bytes'], 0)
        self.assertEqual(len(result['dependencies']), 1)
        self.source['modality_rights']['ocr']['state'] = 'allow'
        self.job['clips'][0]['modalities'] = ['ocr']
        with patch.object(M, '_run', side_effect=AssertionError('no qualified OCR')):
            self.assertEqual(self.execute().manifest['clips'][0]['ocr']['state'], 'unavailable')

    def test_disabled_during_execution_discards_previously_decoded_content(self):
        calls = [0]
        def authorize(job):
            calls[0] += 1
            if calls[0] >= 2: self.runtime.values['RAFII_TREND_MULTIMODAL_ENABLED'] = 'false'
            return deepcopy(self.snapshot)
        self.authorizer.side_effect = authorize
        with patch.object(M, '_run', side_effect=AssertionError('flag disabled before dispatch')):
            with self.assertRaisesRegex(ValueError, 'disabled_during_execution'): self.execute()

    def test_attachment_binding_mismatch_and_malformed_authority_are_content_free(self):
        self.source['media_bindings'][0]['media_sha256'] = 'f' * 64
        with patch.object(M, '_safe_open', side_effect=AssertionError('unbound attachment')):
            with self.assertRaisesRegex(ValueError, 'attachment_binding'): self.execute()
        self.source.pop('media_bindings')
        with self.assertRaisesRegex(ValueError, '^media_authorization_snapshot_invalid$'): self.execute()

    def test_shared_source_requires_current_share_grants_in_both_snapshots(self):
        shared = 'shared:authorized-media'
        self.job['clips'][0]['source_scope'] = shared
        self.source['scope_key'] = shared
        self.snapshot['authorized_source_scopes'] = [shared]
        for field in ('rights', 'policy_rights', 'modality_rights', 'policy_modality_rights'):
            for grant in self.source[field].values(): grant['audience_scope'] = shared
        self.assertEqual(self.execute().manifest['scope_key'], SCOPE)
        for field in ('rights', 'policy_rights'):
            self.source[field]['share_across_workspaces']['state'] = 'deny'
            with self.assertRaisesRegex(ValueError, 'current_right_not_permitted'): self.execute()
            self.source[field]['share_across_workspaces']['state'] = 'allow'

    def test_current_modality_revoke_before_decode_discards_job(self):
        calls = [0]
        def authorize(job):
            calls[0] += 1
            if calls[0] >= 3:
                self.source['policy_modality_rights']['audio']['state'] = 'deny'
            return deepcopy(self.snapshot)
        self.authorizer.side_effect = authorize
        with self.assertRaisesRegex(ValueError, 'modality_revoked'):
            self.execute()

    def test_source_deleted_after_probe_discards_job_and_cleans_private_copy(self):
        calls = [0]
        def authorize(job):
            calls[0] += 1
            if calls[0] >= 3: self.source['deleted'] = True
            return deepcopy(self.snapshot)
        self.authorizer.side_effect = authorize
        with self.assertRaisesRegex(ValueError, 'source_binding'):
            self.execute()

    def test_tenant_revision_digest_expiry_and_stale_authority_fail_closed(self):
        original = deepcopy(self.snapshot)
        mutations = [lambda: self.snapshot.update(actor_id=str(uuid.uuid4())),
                     lambda: self.snapshot.update(authorized=False),
                     lambda: self.snapshot.update(checked_at=BEFORE),
                     lambda: self.source.update(revision=2),
                     lambda: self.source.update(payload_digest='f' * 64),
                     lambda: self.source.update(retention_until=NOW),
                     lambda: self.source.update(available_at=AFTER)]
        for mutate in mutations:
            self.snapshot = deepcopy(original); self.source = self.snapshot['sources'][SOURCE]
            mutate()
            with self.assertRaises(ValueError): self.execute()

    def test_path_traversal_absolute_url_symlink_hardlink_and_fifo_rejected(self):
        (self.root / 'link').symlink_to(self.root / 'clip.wav')
        (self.root / 'directory-link').symlink_to(self.root, target_is_directory=True)
        os.mkfifo(self.root / 'fifo')
        for path in ('../clip.wav', '/etc/passwd', 'https://example.invalid/file', 'link', 'directory-link/clip.wav', 'fifo'):
            self.files[CLIP]['media'] = path
            with self.subTest(path=path), self.assertRaises(ValueError): self.execute()
        os.link(self.root / 'clip.wav', self.root / 'hardlink')
        self.files[CLIP]['media'] = 'hardlink'
        with self.assertRaisesRegex(ValueError, 'regular_private_file'): self.execute()

    def test_changed_input_bytes_reject_exact_binding(self):
        (self.root / 'clip.wav').write_bytes(self.raw + b'changed')
        with self.assertRaisesRegex(ValueError, 'digest_mismatch'): self.execute()

    def test_input_output_and_caption_token_caps_are_actual_not_declared_estimates(self):
        for key, cap, reason in (('max_bytes', 8, 'input_byte_bound'), ('max_output_bytes', 10, 'output_byte_bound'),
                                 ('max_tokens', 1, 'token_bound')):
            saved = self.job['limits'][key]; self.job['limits'][key] = cap
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, reason): self.execute()
            self.job['limits'][key] = saved

    def test_over90_second_actual_wav_is_rejected_by_probe(self):
        raw = wav_bytes(91); (self.root / 'long.wav').write_bytes(raw)
        self.files[CLIP]['media'] = 'long.wav'; self.job['clips'][0]['media_sha256'] = hashlib.sha256(raw).hexdigest()
        self.bind_attachment()
        with self.assertRaisesRegex(ValueError, 'duration_or_stream_bound'): self.execute()

    def test_container_playlists_are_rejected_before_external_decoder(self):
        raw = b'#EXTM3U\nhttp://127.0.0.1:9/do-not-contact\n'
        (self.root / 'playlist').write_bytes(raw); self.files[CLIP]['media'] = 'playlist'
        self.job['clips'][0]['media_sha256'] = hashlib.sha256(raw).hexdigest()
        self.bind_attachment()
        with patch.object(M, '_run', side_effect=AssertionError('playlist decoded')), self.assertRaisesRegex(ValueError, 'container_not_admitted'):
            self.execute()

    def test_job_clip_frame_numeric_and_arbitrary_command_fields_are_bounded(self):
        for mutate in (lambda j: j['clips'].extend(deepcopy(j['clips']) * 2),
                       lambda j: j['clips'][0].update(frame_count=13, modalities=['visual']),
                       lambda j: j['limits'].update(max_processing_seconds=float('nan')),
                       lambda j: j['limits'].update(max_cost_micro_usd=True),
                       lambda j: j['clips'][0].update(filter='movie=https://example.invalid'),
                       lambda j: j['clips'][0].update(modalities=[{}]),
                       lambda j: j.update(executable='/bin/sh'),
                       lambda j: j['clips'][0].update(source_scope='workspace:' + str(uuid.uuid4()))):
            changed = deepcopy(self.job); mutate(changed)
            with self.assertRaises(ValueError): self.runtime.execute(changed, self.files, authorize=self.authorizer)
        self.authorizer.assert_not_called()

    def test_two_clips_share_input_budget_and_total_frame_limit(self):
        extra = deepcopy(self.job['clips'][0]); extra['clip_id'] = str(uuid.uuid4())
        self.job['clips'].append(extra); self.files[extra['clip_id']] = deepcopy(self.files[CLIP])
        result = self.execute().manifest
        self.assertEqual(len(result['clips']), 2)
        self.assertEqual(result['usage']['input_bytes'], 2 * (len(self.raw) + len(SRT)))
        for clip in self.job['clips']: clip.update(frame_count=7, modalities=['visual'])
        with self.assertRaisesRegex(ValueError, 'frame_bound'): self.execute()

    def test_two_actual_video_clips_reach_twelve_frame_boundary(self):
        self.video_job(frames=6)
        extra = deepcopy(self.job['clips'][0]); extra['clip_id'] = str(uuid.uuid4())
        self.job['clips'].append(extra); self.files[extra['clip_id']] = deepcopy(self.files[CLIP])
        result = self.execute().manifest
        self.assertEqual(result['usage']['frames'], 12)
        self.assertEqual([len(c['modalities']['visual']['items']) for c in result['clips']], [6, 6])
        self.assertLessEqual(result['usage']['output_bytes'], self.job['limits']['max_output_bytes'])

    def test_missing_probe_is_explicit_unavailable_with_no_input_read(self):
        self.runtime.ffprobe = ''
        with patch.object(M, '_safe_open', side_effect=AssertionError('no probe means no media access')):
            result = self.execute().manifest
        self.assertEqual(result['state'], 'unavailable')
        self.assertEqual(result['clips'][0]['metadata']['reason'], 'ffprobe_unavailable')
        self.assertEqual(result['usage']['input_bytes'], 0)

    def test_missing_decoder_keeps_valid_supplied_caption_and_probe(self):
        self.runtime.ffmpeg = ''
        result = self.execute().manifest['clips'][0]
        self.assertEqual(result['metadata']['state'], 'available')
        self.assertEqual(result['modalities']['transcript']['state'], 'available')
        self.assertEqual(result['modalities']['audio']['state'], 'unavailable')

    def test_injected_mid_processing_failure_removes_temp_files(self):
        with patch.object(M, '_run', side_effect=M.MediaRuntimeError('synthetic_failure')), self.assertRaisesRegex(ValueError, 'synthetic_failure'):
            self.execute()
        self.assert_cleanup()


class SubprocessBounds(Offline):
    def test_timeout_kills_and_reaps_actual_child(self):
        original = subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            child = original(*args, **kwargs); children.append(child); return child
        with tempfile.TemporaryFile() as source, patch.object(M.subprocess, 'Popen', side_effect=spawn) as spy:
            with self.assertRaisesRegex(ValueError, 'processing_deadline'):
                M._run([sys.executable, '-c', 'import time; time.sleep(5)'], source,
                       deadline=time.monotonic() + .15, output_cap=64)
            self.assertEqual(spy.call_count, 1)
            self.assertIsNotNone(children[0].poll())
            with self.assertRaises(ChildProcessError): os.waitpid(children[0].pid, os.WNOHANG)

    def test_missing_executable_failure_contains_no_private_path(self):
        with tempfile.TemporaryFile() as source, self.assertRaisesRegex(ValueError, '^media_executable_unavailable$'):
            M._run(['/private/tmp/not-a-real-private-media-executable'], source,
                   deadline=time.monotonic() + 5, output_cap=64)

    def test_actual_child_output_is_capped_without_unbounded_capture(self):
        with tempfile.TemporaryFile() as source, self.assertRaisesRegex(ValueError, 'decoder_output_bound'):
            M._run([sys.executable, '-c', 'import os; os.write(1,b"x"*200000)'], source,
                   deadline=time.monotonic() + 5, output_cap=1000)


if __name__ == '__main__':
    unittest.main()
