"""Private, on-demand shot samples from a locally authored five-color sequence."""
import base64
import io
import shutil
import subprocess
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from PIL import Image
from postriff_alpha.domain import AlphaError
from postriff_phase2.creative_video import CreativeVideoService
from postriff_phase2 import creative_video_contact_sheet as sheet
from postriff_phase2.creative_video_assets import identity
from postriff_phase2.creative_video_media import analyze_reference


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
class ReferenceSheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)]
        frames = b"".join(bytes(color) * (48 * 32 * 4) for color in cls.colors)
        cls.raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", "48x32", "-r", "8", "-i", "pipe:0", "-threads", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-bf", "0", "-f", "mp4", "pipe:1"],
            input=frames, capture_output=True, check=True, timeout=12).stdout
        cls.analysis = analyze_reference(cls.raw)
        cls.photo_id = "a" * 32

    def test_page_frames_match_real_colors_and_timestamps_including_final_page(self):
        for page in (0, 1):
            shots, total = sheet.windows(self.analysis, page)
            self.assertEqual(total, 5)
            result = sheet.decode(self.raw, shots)
            self.assertEqual(len(result), 4 if page == 0 else 1)
            for sample in result:
                i = sample["shotIndex"]
                self.assertEqual((sample["startMs"], sample["timeMs"], sample["endMs"]), (500*i, 500*i+250, 500*i+500))
                with Image.open(io.BytesIO(base64.b64decode(sample["jpeg"], validate=True))) as picture:
                    self.assertEqual(picture.format, "JPEG")
                    rgb = picture.getpixel((20, 20))
                    self.assertLess(max(abs(a-b) for a, b in zip(rgb, self.colors[i])), 10)
        for bad in (-1, 2, True):
            with self.assertRaises(AlphaError):
                sheet.windows(self.analysis, bad)

    def test_very_short_shots_never_borrow_a_neighboring_picture(self):
        shots = [{"shotIndex":0, "startMs":0, "endMs":10}, {"shotIndex":1, "startMs":11, "endMs":29}]
        first, missing = sheet.decode(self.raw, shots)
        self.assertEqual(first["timeMs"], 0)
        self.assertIsNone(missing["timeMs"])
        self.assertIsNone(missing["jpeg"])

    def setUp(self):
        self.item = dict(id=self.photo_id, objectName=self.photo_id+".mp4", mime="video/mp4", etag="v1",
            bytes=len(self.raw), processing="ready", verified={"container":True,"locationChecked":True}, duration=2.5,
            durationSource="container", bucket="private-video")
        self.state = {"phase2":{"assets":[self.item]}}
        self.project = {"referenceAssetId":self.photo_id, "referenceIdentity":list(identity(self.item)),
                        "rights":{"confirmedBy":"editor","scope":"analyze-reference-only"}, "analysis":self.analysis}
        self.store = Mock()
        self.store.get.return_value = self.project
        self.service = CreativeVideoService(Mock(), store=self.store)
        self.service.hosted.video_uploads.storage.get_verified_video.return_value = self.raw
        self.actor_allowed = True
        self.access_checks = []
        @contextmanager
        def access(workspace, token, permission):
            self.access_checks.append((workspace, token, permission))
            if not self.actor_allowed or workspace != 'local' or token != 'member':
                raise AlphaError("Not a member.", 403)
            yield object(), self.state, "reader", 2
        self.service.access = access

    def request(self):
        return self.service.contact_sheet("local", "member", "saved-project", 1, 1)

    def test_saved_analyses_need_no_new_metadata_and_keep_rights_for_analysis_only(self):
        result = self.request()
        self.assertEqual((result["page"], result["pageCount"], result["totalShots"]), (1, 2, 5))
        self.assertEqual(self.access_checks, [("local", "member", "read")]*2)
        with self.assertRaises(AlphaError):
            self.service.contact_sheet("foreign", "member", "saved-project", 1, 0)
        with self.assertRaises(AlphaError):
            self.service.contact_sheet("local", "other", "saved-project", 1, 0)
        for rights in (None, {"scope":"publish"}, {"scope":"analyze-reference-only"}):
            self.project["rights"] = rights
            with self.assertRaises(AlphaError):
                self.request()

    def test_changed_bytes_deletion_replacement_or_revoked_membership_release_no_frames(self):
        self.service.hosted.video_uploads.storage.get_verified_video.return_value = b"other"
        with patch.object(sheet, "decode") as decoder, self.assertRaises(AlphaError):
            self.request()
        decoder.assert_not_called()
        self.service.hosted.video_uploads.storage.get_verified_video.return_value = self.raw
        for during in (lambda: self.item.update(deleted=True), lambda: self.item.update(etag="v2"),
                       lambda: self.project.update(rights=None), lambda: setattr(self, "actor_allowed", False)):
            with self.subTest(during=during), patch.object(sheet, "decode", side_effect=lambda *_: during()), self.assertRaises(AlphaError):
                self.request()
            self.setUp()
