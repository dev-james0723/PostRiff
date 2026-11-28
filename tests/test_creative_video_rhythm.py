"""Measure timing from authored audio in a real MP4 and carry it into an original shot."""
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

from postriff_phase2 import creative_video_media as media
from postriff_phase2.creative_video_blueprint import adapt


def reference(pulses=None):
    rate = 8000
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=s=96x64:r=24:d=2"]
    audio = b""
    if pulses is not None:
        samples = array("h", (round(9000 * math.sin(2 * math.pi * 400 * i / rate))
                              if any(start <= i < end for start, end in pulses) else 0 for i in range(2 * rate)))
        if sys.byteorder != "little":
            samples.byteswap()
        audio = samples.tobytes()
        args += ["-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0", "-c:a", "aac"]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "audio-study.mp4"
        subprocess.run([*args, "-c:v", "libx264", "-threads", "1", "-movflags", "+faststart", str(path)],
                       input=audio, check=True, timeout=10)
        return path.read_bytes()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg and FFprobe")
class RhythmTests(unittest.TestCase):
    def test_observes_irregular_rises_on_the_reference_timeline(self):
        sample_times = (250, 750, 1450)
        pulses = [(ms * 8, (ms + 120) * 8) for ms in sample_times]
        analysis = media.analyze_reference(reference(pulses))
        rhythm = analysis["measured"]["audioRhythm"]
        self.assertEqual(rhythm["state"], "measured")
        self.assertEqual(len(rhythm["onsetMs"]), len(sample_times))
        for detected, expected in zip(rhythm["onsetMs"], sample_times):
            self.assertLessEqual(abs(detected - expected), rhythm["resolutionMs"])
        self.assertLessEqual(abs(rhythm["medianSpacingMs"] - 600), rhythm["resolutionMs"])
        self.assertNotIn("bpm", rhythm)

        context = {"brand": "Rafii", "subject": "a green notebook", "audience": "", "tone": "", "preferences": []}
        analysis["scenes"] = [{"startMs": 0, "endMs": 1000}, {"startMs": 1000, "endMs": 2000}]
        opening, ending = adapt({"brief": "Introduce the notebook."}, analysis, context)
        for shot, relative_ms in ((opening, rhythm["onsetMs"][0]), (ending, rhythm["onsetMs"][2] - 1000)):
            self.assertIn(f"{relative_ms / 1000:.2f} s", shot["direction"])
            self.assertIn("notebook", shot["direction"])

    def test_distinguishes_silence_steady_audio_and_absence(self):
        for label, pulses, expected in (("silence", [], "measured"), ("steady", [(0, 16000)], "measured"),
                                        ("no track", None, "no_audio_track")):
            with self.subTest(label=label):
                signal = media.analyze_reference(reference(pulses))["measured"]["audioRhythm"]
                self.assertEqual(signal["state"], expected)
                self.assertEqual(signal["onsetMs"], [])
                self.assertIsNone(signal["medianSpacingMs"])

    def test_clip_validation_can_skip_editorial_work(self):
        with patch.object(media, "_audio_rhythm", side_effect=AssertionError("reference-only measurement")):
            result = media.analyze_reference(reference([]), count_frames=True, include_audio_rhythm=False)
        self.assertNotIn("audioRhythm", result["measured"])
        self.assertEqual(result["decodedFrameCount"], 48)
