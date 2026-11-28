"""Run from the repository root with python3 -m unittest app.test_studio_media."""
import base64
from array import array
from copy import deepcopy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

from app import studio_media as studio
from postriff_alpha.domain import AlphaError


def cli(payload):
    return subprocess.run([sys.executable, str(Path(studio.__file__))],
                          input=json.dumps(payload).encode(), capture_output=True, timeout=60)


def frame_hashes(raw):
    result = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-map", "0:v:0",
                             "-f", "framemd5", "pipe:1"], input=raw, capture_output=True,
                            check=True, timeout=30)
    return [line.rsplit(b",", 1)[-1].strip() for line in result.stdout.splitlines()
            if line and not line.startswith(b"#")]


def marker_soundtrack():
    # Independent pips at picture frames 3 and 33. The original third pip
    # at frame 63 must disappear when the new shorter track reaches silence.
    hz = 48000
    values = array("h", [0]) * (hz * 2)
    for frame in (3, 33):
        for index in range(frame * 2000 + 600, frame * 2000 + 1400):
            values[index] = round(30000 * math.sin(2 * math.pi * 1000 * index / hz))
    output = io.BytesIO()
    with wave.open(output, "wb") as track:
        track.setparams((1, 2, hz, 0, "NONE", "not compressed"))
        track.writeframes(values.tobytes())
    return output.getvalue()


class StudioMediaTests(unittest.TestCase):
    def test_overview_samples_one_continuous_shot_and_reduces_for_a_two_frame_clip(self):
        for count in (16, 2):
            values = [25 + 10*i for i in range(count)]
            pixels = b"".join(bytes([v]) * (32 * 32) for v in values)
            video = subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray",
                "-s", "32x32", "-r", "8", "-i", "pipe:0", "-c:v", "libx264", "-threads", "1",
                "-pix_fmt", "yuv420p", "-bf", "0", "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                "-f", "mp4", "pipe:1"], input=pixels, capture_output=True, check=True, timeout=10).stdout
            self.assertEqual(len(studio.analyze_reference(video)["scenes"]), 1)
            payload = {"action": "reference-frames", "file": base64.b64encode(video).decode(),
                       "referenceSha256": hashlib.sha256(video).hexdigest(), "coverage": "intervals"}
            total = min(8, count)
            for page in range((total + 3) // 4):
                result = cli({**payload, "page": page})
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual((data["coverage"], data["totalSamples"], data["pageCount"]), ("intervals", total, (total + 3) // 4))
                self.assertNotIn("totalShots", data)
                expected = range(page * 4, min(total, (page + 1) * 4))
                self.assertEqual([f["intervalIndex"] for f in data["frames"]], list(expected))
                for frame in data["frames"]:
                    i = frame["intervalIndex"]
                    sample = 2*i + 1 if count == 16 else i
                    self.assertEqual(frame["timeMs"], 125 * sample)
                    self.assertLessEqual(frame["startMs"], frame["timeMs"])
                    self.assertLess(frame["timeMs"], frame["endMs"])
                    jpeg = base64.b64decode(frame["jpeg"], validate=True)
                    rgb = subprocess.run(["ffmpeg", "-v", "error", "-f", "image2pipe", "-i", "pipe:0",
                        "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
                        input=jpeg, capture_output=True, check=True, timeout=10).stdout
                    self.assertLess(abs(rgb[0] - values[sample]), 6)
            self.assertEqual(json.loads(cli({**payload, "page": 0, "coverage": "other"}).stderr)["status"], 400)

    def test_reference_frames_show_measured_shots_across_pages(self):
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)]
        pixels = b"".join(bytes(color) * (64 * 48 * 4) for color in colors)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", "64x48", "-r", "8", "-i", "pipe:0", "-c:v", "libx264", "-threads", "1",
            "-pix_fmt", "yuv420p", "-bf", "0", "-movflags", "frag_keyframe+empty_moov+default_base_moof",
            "-f", "mp4", "pipe:1"], input=pixels, capture_output=True, check=True, timeout=10).stdout
        digest = hashlib.sha256(raw).hexdigest()
        payload = {"action": "reference-frames", "file": base64.b64encode(raw).decode(), "referenceSha256": digest}
        for page, expected in ((0, [0, 1, 2, 3]), (1, [4])):
            result = cli({**payload, "page": page})
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual((data["page"], data["pageCount"], data["totalShots"], data["referenceSha256"]),
                             (page, 2, 5, digest))
            self.assertEqual([shot["shotIndex"] for shot in data["frames"]], expected)
            for shot in data["frames"]:
                i = shot["shotIndex"]
                self.assertEqual((shot["startMs"], shot["timeMs"], shot["endMs"]), (500*i, 500*i+250, 500*i+500))
                jpeg = base64.b64decode(shot["jpeg"], validate=True)
                self.assertTrue(jpeg.startswith(b"\xff\xd8"))
                color = subprocess.run(["ffmpeg", "-v", "error", "-f", "image2pipe", "-i", "pipe:0",
                    "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
                    input=jpeg, capture_output=True, check=True, timeout=10).stdout
                self.assertLess(max(abs(a-b) for a, b in zip(colors[i], color)), 10)
        self.assertEqual(json.loads(cli({**payload, "page": 2}).stderr)["status"], 404)
        self.assertEqual(json.loads(cli({**payload, "page": 0, "referenceSha256": "0" * 64}).stderr)["status"], 409)

    def test_worker_termination_unwinds_its_decoder(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "pid"
            probe = Path(directory) / "ffprobe"
            probe.write_text('#!/bin/sh\necho $$ > "' + str(pidfile) + '"\nexec /bin/sleep 15\n')
            probe.chmod(0o700)
            child = subprocess.Popen([sys.executable, studio.__file__], env={**os.environ, "PATH": directory},
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            decoder = None
            try:
                child.stdin.write(b'{"action":"analyze"}')
                child.stdin.close()
                deadline = time.monotonic() + 5
                while not pidfile.is_file() and time.monotonic() < deadline:
                    time.sleep(.03)
                decoder = int(pidfile.read_text())
                child.terminate()
                self.assertEqual(child.wait(timeout=3), 128 + signal.SIGTERM)
                with self.assertRaises(ProcessLookupError):
                    os.kill(decoder, 0)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                child.stdout.close()
                child.stderr.close()

    def test_soundtrack_rejects_video_garbage_and_overlong_audio(self):
        overlong = io.BytesIO()
        with wave.open(overlong, "wb") as track:
            track.setparams((1, 1, 8000, 0, "NONE", "not compressed"))
            track.writeframes(bytes(91 * 8000))
        for data in (studio.sample_reference(), b"unreadable audio", overlong.getvalue()):
            with self.subTest(size=len(data)):
                result = cli({"action": "inspect-audio", "file": base64.b64encode(data).decode()})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(result.stdout)
                self.assertIn(json.loads(result.stderr)["status"], (415, 422))

    def test_replacement_soundtrack_preserves_picture_caption_and_sample_timing(self):
        picture = (studio.SAMPLE_DIR.parent / "presenter-trim/av-markers.mp4").read_bytes()
        clip_id = "upload-" + hashlib.sha256(picture).hexdigest()
        scene = {"sceneId": "marker", "clipId": clip_id, "durationMs": 3000, "caption": "Look for the flash."}
        track = marker_soundtrack()
        encoded = base64.b64encode(track).decode()
        inspected = cli({"action": "inspect-audio", "file": encoded})
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        identified = json.loads(inspected.stdout)
        self.assertEqual(identified, {"audioId": "audio-" + hashlib.sha256(track).hexdigest(), "durationMs": 2000})
        original, _ = studio.render_timeline([scene], uploads={clip_id: picture})
        payload = {"action": "render", "scenes": [scene], "uploads": {clip_id: base64.b64encode(picture).decode()},
                   "soundtrack": {"audioId": identified["audioId"], "file": encoded}}
        result = cli(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(frame_hashes(result.stdout), frame_hashes(original))
        after = studio.analyze_reference(result.stdout)
        self.assertEqual(after["durationMs"], 3000)
        self.assertEqual(after["measured"]["embeddedCaptions"]["cues"], [{"startMs": 0, "endMs": 3000}])
        samples = array("h")
        samples.frombytes(subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-map", "0:a:0",
            "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1"], input=result.stdout,
            capture_output=True, check=True, timeout=10).stdout)
        loud_frames = [i for i in range(72) if max(abs(v) for v in samples[i * 2000:(i + 1) * 2000]) > 5000]
        self.assertEqual(loud_frames, [3, 33])
        scene["durationMs"] = 1000
        shorter = cli(payload)
        self.assertEqual(shorter.returncode, 0, shorter.stderr)
        self.assertEqual(studio.analyze_reference(shorter.stdout)["durationMs"], 1000)
        payload["soundtrack"]["audioId"] = "audio-" + "0" * 64
        self.assertEqual(json.loads(cli(payload).stderr)["status"], 409)

    def test_blueprint_adapts_measured_timing_without_binding_reference_footage(self):
        raw = studio.sample_reference()
        digest = hashlib.sha256(raw).hexdigest()
        request = {"action": "blueprint", "brief": "Show the folding process.",
                   "brand": "Paperworks", "subject": "paper bird", "audience": "makers",
                   "file": base64.b64encode(raw).decode(), "referenceSha256": digest}
        result = cli(request)
        self.assertEqual(result.returncode, 0, result.stderr)
        blueprint = json.loads(result.stdout)
        self.assertEqual(blueprint["referenceSha256"], digest)
        shots = blueprint["scenes"]
        self.assertEqual([s["durationMs"] for s in shots], [1250, 1500, 1250])
        self.assertTrue(all(s["clipId"] is None for s in shots))
        self.assertIn("paper bird", shots[0]["caption"])
        self.assertIn("Paperworks", shots[-1]["caption"])
        self.assertIn("makers", shots[1]["direction"])
        self.assertIn(request["brief"], shots[1]["direction"])
        mismatch = cli({**request, "referenceSha256": "0" * 64})
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertEqual(json.loads(mismatch.stderr)["status"], 409)

    def test_reference_analysis_and_upload_inspection_use_selected_bytes(self):
        sample = cli({"action": "sample"})
        self.assertEqual(sample.returncode, 0, sample.stderr)
        self.assertEqual(json.loads(sample.stdout), studio.sample_timeline())
        analyze = cli({"action": "analyze"})
        self.assertEqual(analyze.returncode, 0, analyze.stderr)
        measured = json.loads(analyze.stdout)
        self.assertEqual([shot["startMs"] for shot in measured["scenes"]], [0, 1250, 2750])
        self.assertEqual(measured["sha256"], hashlib.sha256(studio.sample_reference()).hexdigest())

        track = (studio.SAMPLE_DIR / "revised-intro.mp4").read_bytes()
        encoded = base64.b64encode(track).decode()
        inspected = cli({"action": "inspect", "file": encoded})
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertEqual(json.loads(inspected.stdout),
                         {"clipId": "upload-" + hashlib.sha256(track).hexdigest(), "durationMs": 1250})
        analyzed = cli({"action": "analyze", "file": encoded})
        self.assertEqual(analyzed.returncode, 0, analyzed.stderr)
        self.assertEqual(json.loads(analyzed.stdout)["durationMs"], 1250)

    def test_render_revised_uploaded_opening_and_reordered_unchanged_footage(self):
        sample = studio.sample_timeline()
        before, receipt = studio.render_timeline(sample["scenes"])
        self.assertTrue(receipt["hasAudio"] and receipt["captionTrack"])
        before_frames = frame_hashes(before)
        self.assertEqual(len(before_frames), 96)

        track = (studio.SAMPLE_DIR / "revised-intro.mp4").read_bytes()
        clip_id = "upload-" + hashlib.sha256(track).hexdigest()
        first, second, third = deepcopy(sample["scenes"])
        first.update(clipId=clip_id, trimStartMs=250, durationMs=750, caption="A new opening.")
        result = cli({"action": "render", "aspectRatio": "9:16", "scenes": [first, third, second],
                      "uploads": {clip_id: base64.b64encode(track).decode()}})
        self.assertEqual(result.returncode, 0, result.stderr)
        after_frames = frame_hashes(result.stdout)
        self.assertEqual(len(after_frames), 84)
        self.assertNotEqual(after_frames[:18], before_frames[:18])
        self.assertEqual(after_frames[18:48], before_frames[66:])
        self.assertEqual(after_frames[48:], before_frames[30:66])
        after = studio.analyze_reference(result.stdout)
        self.assertTrue(after["hasAudio"])
        self.assertEqual(after["measured"]["embeddedCaptions"]["cues"],
                         [{"startMs": 0, "endMs": 750}, {"startMs": 750, "endMs": 2000},
                          {"startMs": 2000, "endMs": 3500}])
        captions = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-map", "0:s:0",
                                   "-f", "srt", "pipe:1"], input=result.stdout, capture_output=True,
                                  check=True, timeout=10).stdout.decode()
        self.assertIn("A new opening.", captions)
        self.assertIn(second["caption"], captions)

    def test_rejects_invalid_clip_bindings_before_decoding(self):
        scene = studio.sample_timeline()["scenes"][0]
        track = (studio.SAMPLE_DIR / "original-1.mp4").read_bytes()
        wrong_id = "upload-" + "0" * 64
        with patch.object(studio, "render_composition") as render:
            for clip_id, uploads in [
                    ("../reference.mp4", {}), ("reference", {}), ([], {}),
                    (scene["clipId"], {scene["clipId"]: track}),
                    (wrong_id, {wrong_id: track}), (scene["clipId"], {wrong_id: track})]:
                with self.subTest(clip_id=clip_id), self.assertRaises(AlphaError):
                    studio.render_timeline([{**scene, "clipId": clip_id}], uploads=uploads)
            render.assert_not_called()

    def test_invalid_uploads_and_out_of_bounds_trim_return_clean_errors(self):
        scene = {**studio.sample_timeline()["scenes"][0], "trimStartMs": 1000}
        for payload in ({"action": "render", "scenes": [scene]},
                        {"action": "inspect", "file": "not base64"},
                        {"action": "analyze", "file": base64.b64encode(b"unrecognized").decode()},
                        {"action": "analyze", "file": None},
                        {"action": "render", "scenes": [{}] * 33}, {"action": "other"}):
            with self.subTest(action=payload["action"]):
                result = cli(payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                error = json.loads(result.stderr)
                self.assertTrue(error["code"] and error["message"])


if __name__ == "__main__":
    unittest.main()
