import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import creative_video_speech as speech
from postriff_phase2.creative_video_blueprint import validate_brief
from test_creative_video_blueprint import BRIEF


class SpeechTimingTests(unittest.TestCase):
    def test_requires_real_reference_explicit_language_and_no_client_model_path(self):
        self.assertNotIn('speechTimingLanguage', validate_brief(BRIEF))
        self.assertEqual(validate_brief({**BRIEF,'speechTimingLanguage':'zh'})['speechTimingLanguage'], 'zh')
        for delta in ({'speechTimingLanguage':'../../fake'}, {'speechTimingLanguage':True}, {'speechTimingLanguage':'en',
                      'referenceAssetId':None,'rightsConfirmed':False}, {'speechModelPath':'/tmp/model'}):
            with self.subTest(delta=delta), self.assertRaises(AlphaError):
                validate_brief({**BRIEF,**delta})

    def test_discards_recognized_words_after_reading_valid_local_segment_times(self):
        output = b'[00:00:00.250 --> 00:00:01.460]  private words here\n'
        self.assertEqual(speech._segments(output,2000), [{'startMs':250,'endMs':1460}])
        for malformed in (b'some unknown format', b'[00:00:00.000 --> 00:00:09.000] out of bounds'):
            with self.assertRaises(ValueError):
                speech._segments(malformed,2000)
        self.assertEqual(speech._segments(b'[00:00:00.000 --> 00:00:01.000] [BLANK_AUDIO]',2000), [])

    def test_missing_runtime_or_model_and_no_track_are_unavailable_without_decoding(self):
        with patch.object(speech.media, '_cmd', side_effect=AssertionError('must not decode')):
            for model in ('https://example.test/weights','relative/path','/dev/null',None):
                report = speech.speech_timing(b'',{'durationMs':1000,'hasAudio':True},'en',model)
                self.assertEqual((report['state'],report['segments']),('unavailable',[]))
            self.assertEqual(speech.speech_timing(b'',{'durationMs':1000,'hasAudio':False},'zh',None)['state'],'no_audio_track')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'fake.bin'
            path.write_bytes(b'not model weights')
            self.assertEqual(speech.speech_timing(b'',{'durationMs':1000,'hasAudio':True},'en',str(path))['reason'],
                             'model_unavailable')

    def test_actual_local_model_on_original_cantonese_fixture_if_configured(self):
        import os
        import unicodedata
        model = os.environ.get('RAFII_CREATIVE_VIDEO_WHISPER_MODEL')
        if not model:
            self.skipTest('requires the explicitly configured qualified whisper.cpp model')
        fixture = os.environ.get('RAFII_TEST_CANTONESE_CLIP')
        if not fixture:
            self.skipTest('requires the original four-second Cantonese speech fixture supplied locally')
        raw = Path(fixture).read_bytes()
        analysis = speech.media.analyze_reference(raw)
        expected = '一個念頭變成一條片'
        original = speech._segments
        observed = []
        def inspect(output, duration):
            text = ''.join(c for c in unicodedata.normalize('NFKC',output.decode()) if '\u4e00' <= c <= '\u9fff')
            observed.append(text)
            return original(output,duration)
        with patch.object(speech, '_segments', side_effect=inspect):
            report=speech.speech_timing(raw,analysis,'zh',model)
        self.assertEqual(observed,[expected],report)
        self.assertTrue(report['segments'])
        self.assertEqual(report['state'],'measured')
        self.assertNotIn(expected,json.dumps(report,ensure_ascii=False))
