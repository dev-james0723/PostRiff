import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from james_au_social.studio import StudioError, StudioStore
from james_au_social.studio_xiaohongshu_publish import XiaohongshuPublishing
from PIL import Image


class XiaohongshuPublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        self.store = StudioStore(Path(self.temp.name) / "studio", root)
        image = Image.new("RGB", (2, 2), "#203040")
        output = io.BytesIO()
        image.save(output, format="PNG")
        self.png = output.getvalue()
        self.asset = self.store.add_asset(self.png, "cover.png", "Abstract AI and piano illustration", "image/png")
        self.broker = Mock()
        self.broker.xiaohongshu_identity.status.return_value = {
            "state": "identity_connected", "nickname": "小红薯6AA7E810", "rednoteId": "94556602041",
        }
        self.broker.xiaohongshu_mcp.verify_published_title.return_value = True
        self.service = XiaohongshuPublishing(self.store, self.broker, 4310)

    def tearDown(self):
        self.temp.cleanup()

    def manifest(self):
        return {
            "account": "小红薯6AA7E810", "rednoteId": "94556602041",
            "destination": "public_profile_feed", "nativeFormat": "xiaohongshu.note",
            "title": "AI 能替我們更快產出，卻不能替我們判斷", "content": "這是一則經過審閱的 AI 筆記。",
            "assetId": self.asset["id"], "altText": "Abstract AI and piano illustration",
            "tags": [], "visibility": "公开可见", "scheduledAt": None,
            "originality": True, "products": [],
        }

    def test_review_binds_the_exact_asset_hash_and_creates_receipt(self):
        review = self.service.review(self.manifest())
        self.assertEqual(review["manifest"]["assetSha256"], self.asset["sha256"])
        self.assertTrue(review["approvalReceiptHash"].startswith("sha256:"))
        self.assertEqual(len(review["idempotencyKey"]), 64)
        self.assertEqual(review["policy"], "exact_publication_approval_required")

    def test_publish_replays_verified_result_without_second_driver_call(self):
        review = self.service.review(self.manifest())
        request = self.manifest() | {
            "approvalReceiptHash": review["approvalReceiptHash"],
            "idempotencyKey": review["idempotencyKey"], "publicationConsent": True,
        }
        first = self.service.publish(request)
        second = self.service.publish(request)
        self.assertEqual(first["publication"]["state"], "published")
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.broker.xiaohongshu_mcp.publish_image_note.assert_called_once()
        driver_payload = self.broker.xiaohongshu_mcp.publish_image_note.call_args.args[0]
        self.assertEqual(driver_payload["tags"], [])
        self.assertTrue(driver_payload["is_original"])
        self.assertEqual(driver_payload["visibility"], "公开可见")
        self.assertRegex(driver_payload["images"][0], r"^http://127\.0\.0\.1:4310/api/xiaohongshu-publishing/assets/[A-Za-z0-9_-]{43}$")

    def test_single_approval_endpoint_derives_the_server_side_receipt(self):
        result = self.service.publish_approved(self.manifest() | {"publicationConsent": True})
        self.assertEqual(result["publication"]["state"], "published")
        self.assertTrue(result["publication"]["approvalReceiptHash"].startswith("sha256:"))
        self.broker.xiaohongshu_mcp.publish_image_note.assert_called_once()

    def test_tampered_approval_receipt_is_rejected_before_driver_call(self):
        request = self.manifest() | {
            "approvalReceiptHash": "sha256:" + "0" * 64,
            "idempotencyKey": "0" * 64, "publicationConsent": True,
        }
        with self.assertRaises(StudioError) as error:
            self.service.publish(request)
        self.assertEqual(error.exception.code, "exact_publication_approval_required")
        self.broker.xiaohongshu_mcp.publish_image_note.assert_not_called()

    def test_lease_is_short_lived_capability_with_bounded_reads(self):
        lease = self.service._lease(self.asset["id"])
        token = lease.rsplit("/", 1)[-1]
        data, mime = self.service.asset_content(token)
        self.assertEqual(data, self.png)
        self.assertEqual(mime, "image/png")
        self.assertEqual(self.service._leases[token].remaining_reads, 4)
