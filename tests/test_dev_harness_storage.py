"""The local dev harness's in-memory storage (scripts/postriff_dev_hosted.py `DevAssets`), DEV-SYNTHETIC only.

It must satisfy the same contract the real private-storage adapter offers to the slices the browser journeys drive:
the raw-source bucket (preflight, signed upload, HEAD, ranged reads, delete) and immutable PNG writes for rendered
Visual Pack slides. No network, no database.
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402

WS = "5b2e7c1a-0000-4000-8000-000000000001"
PDF = "a" * 32 + ".pdf"
PNG = "b" * 32 + "-" + "c" * 64 + ".png"


def harness():
    """The script as a module, without leaking its process-wide LC_ALL default into the rest of the test run."""
    before = os.environ.get("LC_ALL")
    spec = importlib.util.spec_from_file_location("postriff_dev_hosted_under_test", ROOT / "scripts" / "postriff_dev_hosted.py")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        if before is None:
            os.environ.pop("LC_ALL", None)
        else:
            os.environ["LC_ALL"] = before
    return module


class DevSourceBucket(unittest.TestCase):
    def setUp(self):
        self.assets = harness().DevAssets()

    def test_source_bucket_passes_the_service_preflight(self):
        from postriff_phase2.source_uploads.service import SourceUploads
        service = SourceUploads(type("Hosted", (), {"assets": self.assets})(), values={"RAFII_SOURCE_UPLOADS_ENABLED": "1"})
        limit, mimes = service.bucket()
        self.assertEqual(limit, 30_000_000)
        self.assertIn("application/pdf", mimes)
        self.assertEqual(self.assets.bucket_info()["allowedMimeTypes"], ["video/mp4", "video/quicktime"])   # video unchanged

    def test_signed_upload_head_ranges_and_delete(self):
        url = self.assets.signed_upload_url(WS, "source", PDF)
        self.assertIn("/object/upload/sign/rafii-source-uploads/" + WS + "/source/" + PDF + "?token=", url)
        token = url.rsplit("token=", 1)[1]
        self.assertTrue(self.assets.receive_upload(token, b"%PDF-1.4 body", "application/pdf"))
        self.assertFalse(self.assets.receive_upload(token, b"%PDF-1.4 body", "application/pdf"))   # single use
        self.assertEqual(self.assets.object_info(WS, "source", PDF)["mime"], "application/pdf")
        self.assertEqual(self.assets.read_range(WS, "source", PDF, 0, 4)["data"], b"%PDF")
        self.assets.delete(WS, "source", PDF)
        with self.assertRaises(AlphaError):
            self.assets.object_info(WS, "source", PDF)

    def test_bucket_limits_refuse_other_types(self):
        url = self.assets.signed_upload_url(WS, "source", PDF)
        self.assertFalse(self.assets.receive_upload(url.rsplit("token=", 1)[1], b"<html>", "text/html"))

    def test_video_uploads_keep_working(self):
        name = "d" * 32 + ".mp4"
        url = self.assets.signed_upload_url(WS, "video", name)
        self.assertIn("/postriff-video/" + WS + "/video/", url)
        self.assertTrue(self.assets.receive_upload(url.rsplit("token=", 1)[1], b"\x00\x00\x00\x18ftypmp42", "video/mp4"))
        self.assertEqual(self.assets.object_info(WS, "video", name)["mime"], "video/mp4")
        self.assertEqual(self.assets.list_prefix(f"{WS}/video"), [f"{WS}/video/{name}"])


class DevVisualPackWrites(unittest.TestCase):
    def setUp(self):
        self.assets = harness().DevAssets()

    def test_png_slides_are_immutable_and_listed(self):
        self.assertEqual(self.assets.put_immutable(WS, "visual-pack", PNG, b"\x89PNG", content_type="image/png"), f"{WS}/visual-pack/{PNG}")
        with self.assertRaises(AlphaError) as caught:
            self.assets.put_immutable(WS, "visual-pack", PNG, b"\x89PNG", content_type="image/png")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.assets.get(WS, "visual-pack", PNG), b"\x89PNG")
        self.assertEqual(self.assets.list_prefix(f"{WS}/visual-pack"), [f"{WS}/visual-pack/{PNG}"])

    def test_same_refusals_as_the_real_adapter(self):
        for category, mime in (("source", "application/pdf"), ("video", "video/mp4"), ("visual-pack", "image/jpeg"), ("media", "image/png")):
            with self.assertRaises(AlphaError):
                self.assets.put_immutable(WS, category, PNG, b"x", content_type=mime)


if __name__ == "__main__":
    unittest.main()
