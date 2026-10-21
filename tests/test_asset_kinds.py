"""asset_kinds: kind from mime, readiness per kind, postable images and Library membership (SPEC §5.13, §7.6)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_phase2 import asset_kinds as ak  # noqa: E402

IMAGE = {"id": "a", "mime": "image/jpeg", "processing": "decoded", "deleted": False}
VIDEO = {"id": "b", "mime": "video/quicktime", "category": "video", "processing": "ready", "deleted": False}


class AssetKindTests(unittest.TestCase):
    def test_kind_of(self):
        self.assertEqual(ak.kind_of(IMAGE), "image")
        self.assertEqual(ak.kind_of(VIDEO), "video")
        self.assertEqual(ak.kind_of({"mime": "VIDEO/MP4"}), "video")
        self.assertEqual(ak.kind_of({**IMAGE, "kind": "video"}), "image")   # a stored or client kind never wins over mime
        self.assertEqual(ak.kind_of({"mime": "application/pdf"}), "document")
        self.assertEqual(ak.kind_of({"processing": "decoded"}), "image")   # legacy records have no mime
        self.assertIsNone(ak.kind_of({"mime": "text/plain"}))
        self.assertIsNone(ak.kind_of(None))

    def test_category_default(self):
        self.assertEqual(ak.category(IMAGE), "media")
        self.assertEqual(ak.category(VIDEO), "video")
        self.assertEqual(ak.category({"category": ""}), "media")

    def test_is_ready(self):
        self.assertTrue(ak.is_ready(IMAGE))
        self.assertTrue(ak.is_ready(VIDEO))
        self.assertFalse(ak.is_ready({**IMAGE, "processing": "pending"}))
        self.assertFalse(ak.is_ready({**VIDEO, "processing": "decoded"}))
        self.assertFalse(ak.is_ready({**IMAGE, "deleted": True}))
        self.assertFalse(ak.is_ready({**VIDEO, "deletionPending": True}))
        self.assertFalse(ak.is_ready({"mime": "text/plain", "processing": "decoded"}))

    def test_postable_and_library(self):
        self.assertTrue(ak.is_postable_image(IMAGE))
        self.assertFalse(ak.is_postable_image(VIDEO))
        self.assertTrue(ak.is_library_asset(IMAGE))
        self.assertTrue(ak.is_library_asset(VIDEO))
        self.assertTrue(ak.is_library_asset({**VIDEO, "processing": "uploading"}))
        self.assertFalse(ak.is_library_asset({**IMAGE, "deleted": True}))
        self.assertTrue(ak.is_library_asset({"mime": "application/pdf"}))
        self.assertFalse(ak.is_ready({"mime": "application/pdf"}))
        self.assertTrue(ak.is_ready({"mime": "application/pdf", "processing": "validated"}))


if __name__ == "__main__":
    unittest.main()
