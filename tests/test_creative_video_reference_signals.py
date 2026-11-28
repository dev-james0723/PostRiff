"""Bounded reference-only OCR with an authored captioned video and real local executables."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from postriff_phase2 import creative_video_media as media
from postriff_phase2 import creative_video_reference_signals as signals


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg/FFprobe")
class ReferenceTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        font = ImageFont.load_default(size=45)
        backgrounds = [(255, "What makes Orion glow?", 12), (0, "", 0), (255, "Explore Orion. Shop now", 270)]
        raw_frames = bytearray()
        for background, caption, top in backgrounds:
            picture = Image.new("L", (640, 360), background)
            ImageDraw.Draw(picture).text((28, top), caption, font=font, fill=0)
            raw_frames.extend(picture.tobytes() * 7)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "authored-overlay.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray",
                            "-s", "640x360", "-framerate", "8", "-i", "pipe:0", "-c:v", "libx264", "-threads", "1",
                            "-pix_fmt", "yuv420p", "-map_metadata", "-1", "-movflags", "+faststart", str(target)],
                           input=raw_frames, check=True, timeout=12)
            cls.reference = target.read_bytes()
        cls.analysis = media.analyze_reference(cls.reference)

    def test_missing_ocr_is_explicit_and_does_not_change_core_analysis(self):
        with patch.object(signals.shutil, "which", return_value=None):
            result = signals.reference_signals(self.reference, self.analysis)
        self.assertEqual((result["state"], result["reason"], result["frames"]), ("unavailable", "runtime_unavailable", []))
        self.assertNotIn("overlaySignals", self.analysis)

    def test_missing_tsv_output_cannot_masquerade_as_an_empty_frame(self):
        with self.assertRaises(ValueError):
            signals._measure(b"", 640, 360)

    @unittest.skipUnless(shutil.which("tesseract"), "requires offline English Tesseract")
    def test_reports_actual_frame_times_format_and_clues_without_reference_words(self):
        with patch.object(media, "_run", wraps=media._run) as decoder:
            report = signals.reference_signals(self.reference, self.analysis)
        if report.get("reason") == "english_data_unavailable":
            self.skipTest("English Tesseract data is unavailable")
        self.assertEqual(report["state"], "measured")
        self.assertEqual(report["language"], "eng")
        self.assertEqual([f["timeMs"] for f in report["frames"]], [500, 1375, 2250])
        self.assertEqual([f["sceneIndex"] for f in report["frames"]], [0, 1, 2])
        opening, empty, ending = report["frames"]
        self.assertEqual([opening["verticalRegion"], empty["verticalRegion"], ending["verticalRegion"]], ["upper", None, "lower"])
        self.assertEqual([opening["wordCount"], empty["wordCount"], ending["wordCount"]], [4, 0, 4])
        self.assertEqual(opening["interpretiveClues"], ["question"])
        self.assertEqual(ending["interpretiveClues"], ["call_to_action"])
        self.assertIsNone(empty["meanConfidence"])
        for sample in (opening, ending):
            self.assertGreater(sample["meanConfidence"], 70)
            self.assertTrue(3 <= sample["medianWordHeightPct"] <= 18)
        saved = json.dumps(report).lower()
        for authored_word in ("orion", "makes", "glow", "explore", "shop", "now"):
            self.assertNotIn(authored_word, saved)
        self.assertEqual(len(decoder.call_args_list), 3)
        for call in decoder.call_args_list:
            argv = call.args[0]
            self.assertEqual(argv[argv.index("-i") + 1], "fd:")
            self.assertEqual(argv[argv.index("-protocol_whitelist") + 1], "fd,pipe")
            self.assertEqual(argv[argv.index("-frames:v") + 1], "1")

    @unittest.skipUnless(shutil.which("tesseract"), "requires offline English Tesseract")
    def test_one_failed_sample_preserves_the_other_measurements(self):
        original = signals._frame

        def read(source, target, deadline):
            if 876 <= target < 1750:
                raise ValueError("sample unavailable")
            return original(source, target, deadline)

        with patch.object(signals, "_frame", side_effect=read):
            report = signals.reference_signals(self.reference, self.analysis)
        if report.get("reason") == "english_data_unavailable":
            self.skipTest("English Tesseract data is unavailable")
        self.assertEqual((report["state"], report["reason"]), ("partial", "samples_unavailable"))
        self.assertEqual([f["sceneIndex"] for f in report["frames"]], [0, 2])
