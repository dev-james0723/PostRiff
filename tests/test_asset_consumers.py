"""Server consumers of Library assets: image channels, unused-image suggestions and campaign links
accept postable images; verified videos are reserved for supported video channels."""
import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import campaigns, suggestions  # noqa: E402
import test_postriff_phase2 as phase2  # noqa: E402

IMAGE = {"id": "a" * 32, "hash": "h", "sourceHash": "s", "mime": "image/jpeg", "bytes": 10, "width": 1080, "height": 1080, "duration": 0, "processing": "decoded", "deleted": False}
VIDEO = {"id": "b" * 32, "hash": "v", "sourceHash": None, "mime": "video/mp4", "bytes": 10, "width": 1080, "height": 1920, "duration": 42.0, "processing": "ready", "deleted": False, "category": "video"}


class ManifestMediaTest(unittest.TestCase):
    setUp, tearDown = phase2.Phase2Acceptance.setUp, phase2.Phase2Acceptance.tearDown
    channel, draft = phase2.Phase2Acceptance.channel, phase2.Phase2Acceptance.draft

    def manifest(self, asset, variant=None):
        variant = variant or self.draft()
        channel = self.channel(platform="LinkedIn")
        state = copy.deepcopy(self.j.state)
        state["variants"][0].update(platform="LinkedIn", text="Spring concert on 3 May.")
        state["phase2"]["assets"] = [dict(asset)]
        payload = {"channelId": channel["id"], "variantId": variant["id"], "localTime": datetime.fromtimestamp(self.now + 60, timezone.utc).replace(tzinfo=None).isoformat(),
                   "timeZone": "UTC", "acknowledgedWarnings": variant["warnings"], "assetId": asset["id"], "alt": "A piano", "rightsConfirmed": True}
        return self.store.build_manifest(state, payload, "actor")

    def test_a_postable_image_goes_with_the_post(self):
        manifest = self.manifest(IMAGE)
        self.assertEqual([m["id"] for m in manifest["media"]], [IMAGE["id"]])

    def test_a_verified_video_is_refused_on_an_image_channel(self):
        verified_video = {**VIDEO, "durationSource": "container", "bucket": "private-videos",
                          "objectName": "b" * 32 + ".mp4", "etag": "etag-1",
                          "verified": {"container": True, "locationChecked": True}}
        with self.assertRaises(AlphaError) as refused:
            self.manifest(verified_video)
        self.assertEqual((refused.exception.status, str(refused.exception)),
                         (409, "This channel doesn't support video posts from Rafii."))

    def test_undecoded_or_deleted_images_are_refused(self):
        variant = self.draft()
        for asset in ({**IMAGE, "processing": "pending"}, {**IMAGE, "deleted": True}, {**IMAGE, "deletionPending": True}):
            with self.subTest(asset=asset), self.assertRaises(AlphaError) as refused:
                self.manifest(asset, variant)
            self.assertIn("Decoded media", str(refused.exception))


class SuggestionAndLinkTest(unittest.TestCase):
    def state(self):
        return {"phase2": {"assets": [dict(IMAGE), dict(VIDEO), {**IMAGE, "id": "c" * 32, "deleted": True}], "jobs": [], "channels": []}, "variants": [], "raffi": {}}

    def test_unused_image_suggestions_count_postable_images_only(self):
        found = [c for c in suggestions._evidence(self.state(), 1_790_000_000.0) if c["kind"] == "unused_asset"]
        self.assertEqual([c["evidence"][0]["id"] for c in found], [IMAGE["id"]])

    def test_campaign_links_take_images_not_videos(self):
        self.assertEqual(campaigns._link_targets(self.state(), {"assetIds": [IMAGE["id"]]}), [("asset", IMAGE["id"])])
        with self.assertRaises(AlphaError) as refused:
            campaigns._link_targets(self.state(), {"assetIds": [VIDEO["id"]]})
        self.assertEqual(refused.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
