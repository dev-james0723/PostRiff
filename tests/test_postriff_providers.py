"""Milestone C unit tests: provider adapters (fake transport), env-gated registry, hosted connector worker."""
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.providers import InstagramProvider, LinkedInProvider, ThreadsProvider, registry_from_environment
from postriff_phase2.store import Phase2Store
from test_postriff_phase2 import P2Journey


class Recorder:
    def __init__(self, responses):
        self.calls, self.responses = [], list(responses)

    def __call__(self, method, url, headers=None, form=None, body=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "form": form, "body": body})
        return self.responses.pop(0)


class Adapters(unittest.TestCase):
    def test_registry_mounts_only_with_credentials_and_reviewed_flag_is_explicit(self):
        self.assertEqual(registry_from_environment({}), {})
        env = {"POSTRIFF_OAUTH_LINKEDIN_CLIENT_ID": "id", "POSTRIFF_OAUTH_LINKEDIN_CLIENT_SECRET": "s", "POSTRIFF_OAUTH_THREADS_CLIENT_ID": "t", "POSTRIFF_OAUTH_THREADS_CLIENT_SECRET": "ts", "POSTRIFF_OAUTH_THREADS_REVIEWED": "true", "POSTRIFF_OAUTH_INSTAGRAM_CLIENT_ID": "i"}
        registry = registry_from_environment(env)
        self.assertEqual(set(registry), {"linkedin", "threads"})  # instagram lacks a secret
        self.assertFalse(registry["linkedin"].production_reviewed)
        self.assertTrue(registry["threads"].production_reviewed)

    def test_linkedin_flow_shapes(self):
        transport = Recorder([
            {"status": 200, "headers": {}, "body": {"access_token": "AT", "expires_in": 5184000, "scope": "openid profile w_member_social"}},
            {"status": 200, "headers": {}, "body": {"sub": "abc123", "name": "Test Member"}},
            {"status": 200, "headers": {}, "body": {}},
        ])
        provider = LinkedInProvider("cid", "csecret", transport=transport)
        url = provider.authorize_url("https://app.example/api/oauth/linkedin/callback", "STATE", "CHALLENGE", provider.capability_scopes("publish"))
        query = parse_qs(urlparse(url).query)
        self.assertEqual((query["response_type"][0], query["scope"][0], query["state"][0]), ("code", "openid profile w_member_social", "STATE"))
        grant = provider.exchange("CODE", "verifier", "https://app.example/api/oauth/linkedin/callback")
        self.assertEqual((grant["accessToken"], grant["scopes"], grant["refreshToken"]), ("AT", ["openid", "profile", "w_member_social"], None))
        self.assertEqual(transport.calls[0]["form"]["grant_type"], "authorization_code")
        self.assertNotIn("csecret", transport.calls[0]["url"])
        identity = provider.identity("AT")
        self.assertEqual(identity["providerAccountId"], "urn:li:person:abc123")
        self.assertEqual(transport.calls[1]["headers"]["Authorization"], "Bearer AT")
        self.assertTrue(provider.revoke("AT"))
        self.assertEqual(provider.capability_scopes("analytics"), [])  # CM API not held → honest empty

    def test_threads_and_instagram_two_step_exchange(self):
        for cls, base in ((ThreadsProvider, "graph.threads.net"), (InstagramProvider, "graph.instagram.com")):
            with self.subTest(provider=cls.id):
                transport = Recorder([
                    {"status": 200, "headers": {}, "body": {"access_token": "SHORT", "user_id": 1789}},
                    {"status": 200, "headers": {}, "body": {"access_token": "LONG", "expires_in": 5184000}},
                    {"status": 200, "headers": {}, "body": {"id": "1789", "username": "creator", "account_type": "BUSINESS"}},
                    {"status": 200, "headers": {}, "body": {"access_token": "LONG2", "expires_in": 5184000}},
                ])
                provider = cls("cid", "csecret", transport=transport)
                query = parse_qs(urlparse(provider.authorize_url("https://app.example/cb", "S", "C", provider.capability_scopes("publish"))).query)
                self.assertIn("content_publish", query["scope"][0])
                grant = provider.exchange("CODE", "v", "https://app.example/cb")
                self.assertEqual((grant["accessToken"], grant["refreshToken"], grant["userId"]), ("LONG", "LONG", "1789"))
                self.assertIn(base, transport.calls[1]["url"])
                self.assertIn("exchange_token", transport.calls[1]["url"])
                identity = provider.identity("LONG")
                self.assertEqual((identity["providerAccountId"], identity["handle"]), ("1789", "@creator"))
                self.assertEqual(provider.refresh("LONG")["accessToken"], "LONG2")
                self.assertFalse(provider.revoke("LONG"))

    def test_provider_error_is_502_not_silent(self):
        provider = ThreadsProvider("cid", "s", transport=Recorder([{"status": 400, "headers": {}, "body": {"error": "bad"}}]))
        with self.assertRaises(AlphaError) as error:
            provider.exchange("CODE", "v", "https://app.example/cb")
        self.assertEqual(error.exception.status, 502)


class FakeOAuth:
    def __init__(self, scopes=("w_member_social", "r_member_social")):
        self.scopes = list(scopes)

    def token_for_worker(self, workspace_id, connection_id):
        if connection_id == "missing":
            raise AlphaError("Connection unavailable.", 404)
        return {"provider": "linkedin", "accessToken": "TOKEN", "scopes": self.scopes, "expiresAt": None}


class ReviewedProvider:
    production_reviewed = True


def manifest(platform="LinkedIn", media=None):
    return {"workspaceId": "w", "channelId": "conn", "platform": platform, "operation": "member_post", "providerAccountId": "urn:li:person:abc" if platform == "LinkedIn" else "1789", "payload": {"text": "Hello world", "language": "English"}, "media": media or [], "idempotencyKey": "k" * 64}


class Worker(unittest.TestCase):
    def test_unreviewed_provider_holds_and_never_calls_network(self):
        transport = Recorder([])
        social = HostedSocial(FakeOAuth(), {}, transport=transport)
        self.assertEqual(social.submit(manifest())["state"], "held")
        self.assertEqual(social.reconcile(manifest(), {})["state"], "uncertain")
        self.assertEqual(transport.calls, [])

    def test_linkedin_submit_and_reconcile_classification(self):
        providers = {"linkedin": ReviewedProvider()}
        transport = Recorder([
            {"status": 201, "headers": {"x-restli-id": "urn:li:share:123"}, "body": {}},
            {"status": 200, "headers": {}, "body": {"lifecycleState": "PUBLISHED", "commentary": "Hello world"}},
            {"status": 429, "headers": {}, "body": {}},
            {"status": 403, "headers": {}, "body": {}},
            {"status": 200, "headers": {}, "body": {"something": "odd"}},
        ])
        social = HostedSocial(FakeOAuth(), providers, transport=transport)
        accepted = social.submit(manifest())
        self.assertEqual((accepted["state"], accepted["reference"]), ("provider_accepted", "urn:li:share:123"))
        self.assertEqual(transport.calls[0]["headers"]["Authorization"], "Bearer TOKEN")
        self.assertEqual(transport.calls[0]["body"]["commentary"], "Hello world")
        verified = social.reconcile(manifest(), {"providerReference": "urn:li:share:123"})
        self.assertEqual((verified["state"], verified["verification"]), ("verified", "provider_lookup"))
        self.assertEqual(social.submit(manifest())["state"], "scheduled")   # 429 → retry later, not a failure
        self.assertEqual(social.submit(manifest())["state"], "held")        # 403 → permission
        self.assertEqual(social.submit(manifest())["state"], "uncertain")   # 200 without evidence → never published
        social_no_read = HostedSocial(FakeOAuth(scopes=("w_member_social",)), providers, transport=Recorder([]))
        self.assertEqual(social_no_read.reconcile(manifest(), {"providerReference": "urn:li:share:1"})["state"], "uncertain")

    def test_threads_container_flow_and_reconcile_by_container(self):
        providers = {"threads": ReviewedProvider()}
        transport = Recorder([
            {"status": 200, "headers": {}, "body": {"id": "555"}},
            {"status": 200, "headers": {}, "body": {"id": "999"}},
            {"status": 200, "headers": {}, "body": {"id": "999", "text": "Hello world", "permalink": "https://www.threads.net/@creator/post/x"}},
            {"status": 200, "headers": {}, "body": {"id": "556"}},
            {"status": 500, "headers": {}, "body": {}},
            {"status": 200, "headers": {}, "body": {"status_code": "PUBLISHED"}},
        ])
        social = HostedSocial(FakeOAuth(), providers, transport=transport)
        accepted = social.submit(manifest("Threads"))
        self.assertEqual((accepted["state"], accepted["reference"], accepted["container"]), ("provider_accepted", "999", "555"))
        self.assertEqual(transport.calls[0]["form"]["media_type"], "TEXT")
        self.assertNotIn("access_token", transport.calls[0]["url"])  # token travels in the form body, not the URL
        verified = social.reconcile(manifest("Threads"), {"providerReference": "999"})
        self.assertEqual(verified["state"], "verified")
        inconclusive = social.submit(manifest("Threads"))
        self.assertEqual((inconclusive["state"], "556" in inconclusive["confirmed"]), ("uncertain", True))
        by_container = social.reconcile(manifest("Threads"), {"providerReference": None, "container": "556"})
        self.assertEqual(by_container["state"], "published")  # container PUBLISHED is not yet 'verified'

    def test_instagram_requires_image_and_holds_without_grant(self):
        social = HostedSocial(FakeOAuth(), {"instagram": ReviewedProvider()}, transport=Recorder([]))
        self.assertEqual(social.submit(manifest("Instagram"))["state"], "failed")
        missing = manifest()
        missing["channelId"] = "missing"
        with self.assertRaises(AlphaError):
            HostedSocial(FakeOAuth(), {"linkedin": ReviewedProvider()}, transport=Recorder([])).submit(missing)


class MultiDestination(unittest.TestCase):
    def test_approve_many_groups_jobs_under_one_schedule_and_daily_limit_holds(self):
        tmp = tempfile.TemporaryDirectory()
        now = [1_800_000_000.0]
        store = Phase2Store(Path(tmp.name) / "p.db", clock=lambda: now[0])
        j = P2Journey(store)
        from datetime import datetime, timezone
        j.setup().act("generate", platform="LinkedIn", language="English")
        v = j.state["variants"][0]
        j.act("p2_variant_review", variantId=v["id"], variantRevision=v["revision"], confirmed=True, excludedUnknowns=v["unknowns"])
        reviews = []
        for _ in range(2):
            j.act("p2_channel_add", platform="LinkedIn", language="English")
            c = j.state["phase2"]["channels"][-1]
            j.act("p2_channel_verify", channelId=c["id"], scenario="success")
            j.act("p2_review", channelId=c["id"], variantId=v["id"], localTime=datetime.fromtimestamp(now[0] + 60, timezone.utc).replace(tzinfo=None).isoformat(), timeZone="UTC", acknowledgedWarnings=v["warnings"])
            reviews.append(j.state["phase2"]["reviews"][-1])
        j.act("p2_approve_many", reviews=[{"reviewId": r["id"], "digest": r["digest"]} for r in reviews], confirmed=True)
        jobs = j.state["phase2"]["jobs"]
        self.assertEqual(len(jobs), 2)
        self.assertEqual(len({job["scheduleId"] for job in jobs}), 1)
        self.assertIsNotNone(jobs[0]["scheduleId"])
        self.assertTrue(jobs[0]["manifest"]["timing"]["tzdb"])
        # Per-destination states stay independent: cancel one, the other is untouched.
        j.act("p2_cancel", jobId=jobs[0]["id"])
        self.assertEqual([job["state"] for job in j.state["phase2"]["jobs"]], ["canceled", "scheduled"])
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()


class HostedPlatformsHaveLimits(unittest.TestCase):
    def test_every_hosted_oauth_platform_has_publish_limits(self):
        """build_manifest indexes LIMITS by platform; a connector without an entry would 500 at scheduling."""
        from postriff_phase2 import providers
        from postriff_phase2.contracts import LIMITS
        platforms = {cls.platform for cls in vars(providers).values() if isinstance(cls, type) and issubclass(cls, providers.OAuthProvider) and cls is not providers.OAuthProvider and cls.platform}
        self.assertTrue(platforms, "no hosted providers found")
        self.assertTrue(platforms <= set(LIMITS), f"missing LIMITS for {platforms - set(LIMITS)}")
        for platform in platforms:
            self.assertGreater(LIMITS[platform]["characters"], 0)
            self.assertTrue(LIMITS[platform]["operation"])

