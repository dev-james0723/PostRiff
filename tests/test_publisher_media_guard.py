"""Production safety (plan G3-VIS, G0 code map ⚠): a job with more than one media item is refused before any grant
read, qualification check or provider call by every publisher without verified carousel support — Threads and
Instagram used to take media[0] silently. Single-image publishing is unchanged."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_phase2 import hosted_social  # noqa: E402
from postriff_phase2.hosted_social import CAROUSEL_VERIFIED, HostedSocial  # noqa: E402

PLATFORMS = ("LinkedIn", "Threads", "Instagram", "Bluesky", "Mastodon", "Telegram", "Discord", "X", "Facebook", "YouTube", "TikTok",
             "Pinterest", "Google Business Profile", "Pixelfed", "Douyin", "Kuaishou")


class NoNetwork:
    def __init__(self, responses=()):
        self.calls, self.responses = [], list(responses)

    def __call__(self, method, url, headers=None, form=None, body=None, **_):
        self.calls.append({"method": method, "url": url, "form": form})
        if not self.responses:
            raise AssertionError(f"provider I/O attempted: {method} {url}")
        return self.responses.pop(0)


class NoGrants:
    def __init__(self):
        self.reads = 0

    def token_for_worker(self, *_):
        self.reads += 1
        raise AssertionError("a grant was read for a refused job")


class Grants:
    def token_for_worker(self, *_):
        return {"accessToken": "TOKEN", "scopes": ["threads_basic", "threads_content_publish", "instagram_business_basic", "instagram_business_content_publish"]}


class Reviewed:
    production_reviewed = True


class Providers(dict):
    """Every lookup answers a reviewed provider, so only the guard can stop the job."""
    def get(self, key, default=None):
        return Reviewed()


class Storage:
    def __init__(self):
        self.signed = []

    def signed_url(self, workspace_id, category, name, seconds):
        self.signed.append((category, name))
        return f"https://project.supabase.co/storage/v1/object/sign/postriff-private/{workspace_id}/{category}/{name}?token=t"


class Assets:
    def __init__(self):
        self.storage = Storage()


def image(n):
    return {"id": f"{n:032x}", "objectName": f"{n:032x}-{'a' * 64}.jpg", "mime": "image/jpeg", "alt": f"slide {n}", "hash": "h"}


def manifest(platform, media):
    return {"workspaceId": "00000000-0000-0000-0000-000000000001", "channelId": "conn", "platform": platform, "operation": "post",
            "providerAccountId": "1789", "account": "@studio", "payload": {"text": "Six slides", "language": "en"}, "media": media,
            "idempotencyKey": "k" * 64}


class MultiMediaGuard(unittest.TestCase):
    def test_no_publisher_claims_verified_carousel_support(self):
        self.assertEqual(CAROUSEL_VERIFIED, frozenset())

    def test_every_publisher_refuses_more_than_one_media_item_before_any_io(self):
        for platform in PLATFORMS:
            for count in (2, 6):
                with self.subTest(platform=platform, count=count):
                    wire, grants = NoNetwork(), NoGrants()
                    social = HostedSocial(grants, Providers(), assets=Assets(), transport=wire)
                    result = social.submit(manifest(platform, [image(i) for i in range(count)]))
                    self.assertEqual(result["state"], "failed")
                    self.assertIn("at most one image or video", result["confirmed"])
                    self.assertIn(f"{count} media items", result["confirmed"])
                    self.assertIn("Nothing was posted", result["confirmed"])
                    self.assertEqual((wire.calls, grants.reads, social.assets.storage.signed), ([], 0, []))

    def test_instagram_container_steps_and_direct_calls_refuse_too(self):
        wire = NoNetwork()
        social = HostedSocial(NoGrants(), Providers(), assets=Assets(), transport=wire)
        job = {"container": "123", "progress": {"version": 1, "stage": "publish_attempted"}}
        for action in ("create", "status", "publish"):
            self.assertEqual(social.advance_instagram(manifest("Instagram", [image(1), image(2)]), job, action)["state"], "failed", action)
        self.assertEqual(social._submit_instagram(manifest("Instagram", [image(1), image(2)]), "TOKEN")["state"], "failed")
        self.assertEqual(social._submit_threads(manifest("Threads", [image(1), image(2)]), "TOKEN")["state"], "failed")
        self.assertEqual((wire.calls, social.assets.storage.signed), ([], []))

    def test_single_image_threads_and_instagram_are_unchanged(self):
        wire = NoNetwork([{"status": 200, "body": {"id": "555"}}, {"status": 200, "body": {"id": "999"}}])
        social = HostedSocial(Grants(), Providers(), assets=Assets(), transport=wire)
        accepted = social.submit(manifest("Threads", [image(1)]))
        self.assertEqual((accepted["state"], accepted["reference"]), ("provider_accepted", "999"))
        self.assertEqual((wire.calls[0]["form"]["media_type"], wire.calls[0]["form"]["alt_text"]), ("IMAGE", "slide 1"))
        self.assertEqual(social.assets.storage.signed, [("media", image(1)["objectName"])])
        wire = NoNetwork([{"status": 200, "body": {"id": "777"}}])
        social = HostedSocial(Grants(), Providers(), assets=Assets(), transport=wire)
        created = social.advance_instagram(manifest("Instagram", [image(3)]), {}, "create")
        self.assertEqual((created["state"], created["container"]), ("processing", "777"))
        self.assertEqual(wire.calls[0]["form"]["alt_text"], "slide 3")

    def test_text_only_posts_are_unchanged(self):
        wire = NoNetwork([{"status": 200, "body": {"id": "555"}}, {"status": 200, "body": {"id": "999"}}])
        social = HostedSocial(Grants(), Providers(), assets=Assets(), transport=wire)
        self.assertEqual(social.submit(manifest("Threads", []))["state"], "provider_accepted")
        self.assertEqual(wire.calls[0]["form"]["media_type"], "TEXT")
        self.assertIsNone(hosted_social.HostedSocial._multi_media_refusal({"platform": "X"}))


if __name__ == "__main__":
    unittest.main()
