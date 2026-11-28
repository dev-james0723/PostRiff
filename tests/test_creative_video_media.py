"""Exercise the offline worker with actual encoded media and deterministic provider doubles."""
import base64
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import creative_video_media as media
from postriff_phase2 import creative_video_media_provider as vertex


def fixture(path, filters, *, frequency=None, seconds=2):
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", filters]
    if frequency:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000", "-c:a", "aac"]
    subprocess.run(cmd + ["-t", str(seconds), "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p",
                          "-map_metadata", "-1", "-movflags", "+faststart", str(path)], check=True, timeout=20)
    return path.read_bytes()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg/FFprobe")
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        cls.cut = fixture(root / "reference.mp4",
            "color=c=black:s=96x64:r=24:d=1[a];color=c=white:s=96x64:r=24:d=1[b];[a][b]concat=n=2:v=1:a=0",
            frequency=440)
        cls.motion = fixture(root / "moving product.mov", "testsrc2=size=96x64:rate=24")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_measures_actual_cut_audio_and_lighting(self):
        result = media.analyze_reference(self.cut)
        self.assertEqual([s["startMs"] for s in result["scenes"]], [0, 1000])
        self.assertEqual(result["durationMs"], 2000)
        self.assertTrue(result["hasAudio"])
        dark, bright = [s["measurements"] for s in result["scenes"]]
        self.assertGreater(bright["meanLuma"] - dark["meanLuma"], .8)
        self.assertGreater(dark["audioRms"], 0)
        self.assertIn("retention", " ".join(result["unavailable"]).lower())
        result = media.analyze_reference(self.motion)
        self.assertIsNone(result["scenes"][0]["measurements"]["audioRms"])

    def test_revision_keeps_original_clip_and_timed_caption(self):
        timeline = [{"sceneId": "intro", "clipId": "a", "durationMs": 750, "caption": "A short hook"},
                    {"sceneId": "proof", "clipId": "b", "durationMs": 1000, "trimStartMs": 250}]
        clips = {"a": self.cut, "b": self.motion}
        raw, before = media.render_composition(timeline, clips, aspect_ratio="9:16")
        self.assertEqual((before["frameCount"], before["width"], before["height"]), (42, 720, 1280))
        self.assertEqual(before["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertTrue(before["hasAudio"] and before["captionTrack"])
        self.assertEqual(before["scenes"][1]["startMs"], 750)
        timing = media.analyze_reference(raw)["measured"]["embeddedCaptions"]
        self.assertEqual(timing, {"state": "measured", "cues": [{"startMs": 0, "endMs": 750}]})
        repeat, _ = media.render_composition(timeline, clips, aspect_ratio="9:16")
        self.assertEqual(raw, repeat)
        timeline[0]["caption"] = "A revised hook"
        new, after = media.render_composition(timeline, clips, aspect_ratio="9:16")
        self.assertNotEqual(raw, new)
        self.assertEqual(before["scenes"][1], after["scenes"][1])
        self.assertEqual(before["scenes"][1]["clipSha256"], hashlib.sha256(self.motion).hexdigest())

    def test_descriptor_only_inputs_and_frame_quantized_square_timeline(self):
        scene = {"sceneId": "a", "clipId": "arbitrary title, not an input path", "durationMs": 531}
        with patch.object(media, "_run", wraps=media._run) as runner:
            raw, manifest = media.render_composition([scene, {**scene, "sceneId": "b"}],
                                                     {scene["clipId"]: self.motion}, aspect_ratio="1:1")
        for call in runner.call_args_list:
            argv = call.args[0]
            for offset, option in enumerate(argv):
                if option == "-i":
                    self.assertEqual(argv[offset + 1], "fd:")
                if option == "-protocol_whitelist":
                    self.assertNotIn("file", argv[offset + 1])
            self.assertNotIn(scene["clipId"], argv)
        self.assertTrue(raw)
        self.assertFalse(manifest["hasAudio"] or manifest["captionTrack"])
        self.assertEqual((manifest["width"], manifest["height"], manifest["frameCount"]), (720, 720, 25))
        self.assertEqual(sum(s["frameCount"] for s in manifest["scenes"]), 25)

    def test_rejects_unsupported_sources_and_trim_overrun(self):
        with self.assertRaises(AlphaError):
            media.analyze_reference(b"#EXTM3U\nexample\n")
        scene = {"sceneId": "s", "clipId": "moving", "durationMs": 2000, "trimStartMs": 500}
        with self.assertRaises(AlphaError):
            media.render_composition([scene], {"moving": self.motion})
        with self.assertRaises(AlphaError):
            media.render_composition([scene], {"else": self.motion})

    def test_frame_download_returns_the_selected_decoded_picture(self):
        from postriff_phase2.creative_video_media import picture_frame
        first = picture_frame(self.cut, 0)
        light = picture_frame(self.cut, 30)
        self.assertTrue(first.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertNotEqual(first, light)
        self.assertEqual(light, picture_frame(self.cut, 30))
        for invalid in (True, -1, 48, 2160):
            with self.assertRaises(AlphaError):
                picture_frame(self.cut, invalid)


class ProviderTests(unittest.TestCase):
    config = {"RAFII_CREATIVE_VIDEO_PROVIDER": "vertex-veo", "RAFII_CREATIVE_VIDEO_PROJECT": "test-project",
              "RAFII_CREATIVE_VIDEO_ACCESS_TOKEN": "fictional-token"}

    def test_one_submission_polls_same_operation_and_returns_bytes(self):
        calls = []
        payload = b"\x00\x00\x00\x18ftypisom" + b"\0" * 16
        provider = vertex.VideoProvider.from_environment(self.config)
        operation = provider.model_path + "/operations/unit123"
        replies = [{"name": operation}, {"name": operation}, {"name": operation, "done": True, "response": {
            "videos": [{"mimeType": "video/mp4", "bytesBase64Encoded": base64.b64encode(payload).decode()}]}}]
        def transport(action, body, _token, _limit):
            calls.append((action, body))
            return 200, replies.pop(0)
        provider.transport = transport
        self.assertEqual(provider.estimate(4001), 600000)
        self.assertEqual(provider.submit(prompt="Original fictional product", duration_ms=4001, aspect_ratio="9:16"), operation)
        self.assertEqual(calls[0][1]["parameters"]["durationSeconds"], 6)
        self.assertEqual(provider.poll(operation)["state"], "pending")
        result = provider.poll(operation)
        self.assertEqual(result["video"], payload)
        self.assertIsNone(result["costUsdMicro"])
        self.assertEqual(sum("predictLongRunning" in entry[0] for entry in calls), 1)

    def test_disabled_or_unknown_effect_never_retried(self):
        with self.assertRaises(AlphaError):
            vertex.VideoProvider.from_environment({})
        provider = vertex.VideoProvider.from_environment(self.config)
        calls = []
        def broken(*args):
            calls.append(1)
            raise TimeoutError()
        provider.transport = broken
        with self.assertRaises(vertex.ProviderError) as caught:
            provider.submit(prompt="A sample", duration_ms=2000, aspect_ratio="9:16")
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(calls, [1])
        with self.assertRaises(AlphaError):
            provider.poll("outside/project/operations/123")
        self.assertEqual(calls, [1])

    def test_refused_filtered_and_external_assets_stay_distinct(self):
        provider = vertex.VideoProvider.from_environment(self.config)
        operation = provider.model_path + "/operations/saved-one"
        provider.transport = lambda *_: (403, {})
        with self.assertRaises(vertex.ProviderError) as refused:
            provider.submit(prompt="A fictional device", duration_ms=8000, aspect_ratio="16:9")
        self.assertFalse(refused.exception.uncertain)
        provider.transport = lambda *_: (200, {"name": operation, "done": True,
                                              "response": {"raiMediaFilteredCount": 1, "videos": []}})
        self.assertEqual(provider.poll(operation)["reason"], "provider_content_filtered")
        provider.transport = lambda *_: (200, {"name": operation, "done": True, "response": {
            "videos": [{"mimeType": "video/mp4", "gcsUri": "gs://example/fixture"}]}})
        with self.assertRaises(vertex.ProviderError) as invalid:
            provider.poll(operation)
        self.assertTrue(invalid.exception.uncertain)
        self.assertEqual(invalid.exception.code, "creative_video_provider_output_invalid")
