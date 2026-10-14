"""Bluesky P0 hardening acceptance (isolated mocked ATproto provider; never a live write)."""
import io
import base64
import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).resolve().parent)]
from PIL import Image
from postriff_alpha.domain import AlphaError
from postriff_phase2.atproto_oauth import BlueskyProvider, generate_jwk
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.oauth import OAuthService
from postriff_phase2.text_measure import measure
from test_hosted_wave1_connectors import BASE, DID, PUBLIC, Grants, Wire, ok, manifest, BlueskyAdapter

RECORD_CID = "b" + base64.b32encode(bytes((1, 0x71, 0x12, 0x20)) + hashlib.sha256(b"test record").digest()).decode().lower().rstrip("=")

NEW = ["atproto", BlueskyProvider.POST_SCOPE, BlueskyProvider.IMAGE_SCOPE]
OLD = ["atproto", BlueskyProvider.LEGACY_SCOPE]


def valid_png():
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (10, 80, 190)).save(buf, format="PNG")
    return buf.getvalue()


class Storage:
    def __init__(self, raw):
        self.raw = raw

    def get(self, workspace, kind, name):
        if (workspace, kind, name) != ("w", "media", "img"):
            raise AssertionError("Unapproved media path")
        return self.raw


class P0Bluesky(unittest.TestCase):
    def social(self, responses=(), *, scopes=NEW, raw=None):
        wire = Wire(responses)
        adapter = BlueskyProvider(generate_jwk(kid="p0-client"), BASE, transport=wire, resolver=PUBLIC)
        adapter.production_reviewed = True  # Fixture only; not a production enablement.
        session = {"v": 1, "did": DID, "at": "fixture-access", "pds": "https://pds.example.com",
                   "jwk": generate_jwk(), "iss": "https://as.example.com", "scope": scopes}
        assets = SimpleNamespace(storage=Storage(raw)) if raw is not None else None
        return HostedSocial(Grants(json.dumps(session), scopes), {"bluesky": adapter}, assets=assets), wire, session

    @staticmethod
    def reference(job):
        return f"at://{DID}/app.bsky.feed.post/{HostedSocial.bluesky_rkey(job)}"

    def test_identity_never_requests_broad_grant_and_metadata_keeps_legacy_compatibility(self):
        provider = BlueskyProvider(generate_jwk(kid="p0"), BASE, transport=Wire([]), resolver=PUBLIC)
        self.assertEqual(provider.capability_scopes("identity"), ["atproto"])
        self.assertNotIn("transition:generic", provider.capability_scopes("publish"))
        self.assertEqual(set(provider.capability_scopes("publish")), set(NEW))
        self.assertIn("transition:generic", provider.client_metadata()["scope"].split())
        self.assertTrue(provider.explain("identity").lower().find("cannot create posts") != -1)

    def test_identity_par_scope_is_exactly_atproto(self):
        responses = BlueskyAdapter().resolution() + [ok({"request_uri": "urn:ietf:params:oauth:request_uri:test"}, 201)]
        provider = BlueskyProvider(generate_jwk(kid="p0"), BASE, transport=Wire(responses), resolver=PUBLIC)
        provider.begin(BASE + "/api/oauth/bluesky/callback", "state", "verifier", "challenge",
                       provider.capability_scopes("identity"), "alice.example.com")
        self.assertEqual(provider.transport.calls[-1]["form"]["scope"], "atproto")
        self.assertNotIn("transition:generic", json.dumps(provider.transport.calls[-1]["form"]))

    def test_did_connection_skips_mutable_handle_lookup(self):
        responses = BlueskyAdapter().resolution()[1:] + [ok({"request_uri": "urn:test"}, 201)]
        wire = Wire(responses)
        provider = BlueskyProvider(generate_jwk(kid="p0"), BASE, transport=wire, resolver=PUBLIC)
        connection = provider.begin(BASE + "/cb", "state", "v", "c", ["atproto"], DID)
        self.assertEqual(connection["context"]["did"], DID)
        self.assertEqual(wire.calls[0]["url"], "https://plc.directory/" + DID)
        self.assertEqual(wire.calls[-1]["form"]["login_hint"], DID)

    def test_legacy_grant_works_but_identity_and_partial_grants_do_not(self):
        self.assertTrue(BlueskyProvider.has_publish_scopes(OLD))
        self.assertTrue(BlueskyProvider.has_publish_scopes(NEW))
        self.assertFalse(BlueskyProvider.has_publish_scopes(["atproto"]))
        self.assertFalse(BlueskyProvider.has_publish_scopes(["atproto", BlueskyProvider.POST_SCOPE]))
        self.assertTrue(BlueskyProvider.has_publish_scopes(["atproto", BlueskyProvider.POST_SCOPE], with_image=False))

    def test_publish_permissions_in_connection_readiness_with_legacy_grant(self):
        channel = {"platform": "Bluesky", "connectionState": "publish_verified", "scopes": OLD,
                   "capabilities": {"publish": {"level": "Direct"}}}
        status = OAuthService.connection_readiness(channel, {"configured": True, "connectReady": True,
                                                         "productionReviewed": True, "executionPaused": False})
        self.assertEqual(status["publishing"], "PUBLISHING_AVAILABLE")

    def test_no_permission_or_identity_only_grant_never_reaches_provider(self):
        job = manifest("Bluesky", DID)
        for scopes in (["atproto"], ["atproto", BlueskyProvider.IMAGE_SCOPE]):
            with self.subTest(scopes=scopes):
                social, wire, _ = self.social(scopes=scopes)
                self.assertEqual(social.submit(job)["state"], "held")
                self.assertEqual(wire.calls, [])

    def test_mismatched_approved_did_is_denied_before_network(self):
        social, wire, _ = self.social()
        job = manifest("Bluesky", "did:plc:zzzzzzzzzzzzzzzzzzzzzzzz")
        self.assertEqual(social.submit(job)["state"], "held")
        self.assertEqual(wire.calls, [])

    def test_unicode_graphemes_300_with_zwj_vs_301(self):
        emoji = "👩🏽‍🎤"
        self.assertEqual(measure("Bluesky", emoji * 300), {"used": 300, "limit": 300, "unit": "grapheme"})
        self.assertEqual(measure("Bluesky", "e\u0301" * 300)["used"], 300)
        job = manifest("Bluesky", DID, emoji * 301)
        social, wire, _ = self.social()
        self.assertEqual(social.submit(job)["state"], "failed")
        self.assertEqual(wire.calls, [])

    def test_cantonese_emoji_link_facets_use_utf8_byte_positions(self):
        text = "你好 👩🏽‍🎤 音樂 https://rafii.io/演出"
        facets = HostedSocial._bluesky_facets(text)
        self.assertEqual(len(facets), 1)
        start, end = facets[0]["index"]["byteStart"], facets[0]["index"]["byteEnd"]
        self.assertEqual(text.encode("utf-8")[start:end].decode("utf-8"), "https://rafii.io/演出")

    def test_granular_text_publish_preserves_exact_payload(self):
        job = manifest("Bluesky", DID, "Cantonese 🎹 https://rafii.io")
        reference = self.reference(job)
        social, wire, _ = self.social([ok({"uri": reference, "cid": RECORD_CID})])
        self.assertEqual(social.submit(job)["state"], "provider_accepted")
        self.assertEqual(wire.calls[0]["body"]["record"]["text"], job["payload"]["text"])
        self.assertEqual(len(wire.calls), 1)

    def test_identity_grant_does_not_upload_media(self):
        raw = valid_png()
        job = manifest("Bluesky", DID, media=[{"id": "img", "mime": "image/png", "alt": "piano"}])
        social, wire, _ = self.social(scopes=["atproto", BlueskyProvider.POST_SCOPE], raw=raw)
        self.assertEqual(social.submit(job)["state"], "held")
        self.assertEqual(wire.calls, [])

    def test_reject_bad_image_bytes_size_and_missing_alt_without_provider_calls(self):
        for raw, mime, alt in [(b"malicious", "image/png", "piano"),
                               (b"\x89PNG\r\n\x1a\n" + b"X" * 2_000_000, "image/png", "piano"),
                               (valid_png(), "image/png", ""), (valid_png(), "image/svg+xml", "piano")]:
            with self.subTest(size=len(raw), mime=mime, alt=alt):
                job = manifest("Bluesky", DID, media=[{"id": "img", "mime": mime, "alt": alt}])
                social, wire, _ = self.social(raw=raw)
                self.assertEqual(social.submit(job)["state"], "failed")
                self.assertEqual(wire.calls, [])

    def test_image_upload_cid_mismatch_never_posts(self):
        raw = valid_png()
        job = manifest("Bluesky", DID, media=[{"id": "img", "mime": "image/png", "alt": "keys"}])
        wrong = {"blob": {"ref": {"$link": "bwrong"}, "mimeType": "image/png", "size": len(raw)}}
        social, wire, _ = self.social([ok(wrong)], raw=raw)
        self.assertEqual(social.submit(job)["state"], "held")
        self.assertEqual(len(wire.calls), 1)

    def test_image_publish_and_readback_verifies_cid_alt_and_blob(self):
        raw = valid_png()
        job = manifest("Bluesky", DID, media=[{"id": "img", "mime": "image/png", "alt": "Concert piano"}])
        blob = {"$type": "blob", "ref": {"$link": HostedSocial._bluesky_blob_cid(raw)}, "mimeType": "image/png", "size": len(raw)}
        reference = self.reference(job)
        social, wire, _ = self.social([ok({"blob": blob}), ok({"uri": reference, "cid": RECORD_CID})], raw=raw)
        result = social.submit(job)
        self.assertEqual(result["state"], "provider_accepted")
        record = wire.calls[1]["body"]["record"]
        self.assertEqual(record["embed"]["images"][0]["alt"], "Concert piano")
        social.providers["bluesky"].transport = Wire([ok({"uri": reference, "cid": RECORD_CID, "value": record})])
        verified = social.reconcile(job, {"providerReference": reference})
        self.assertEqual(verified["state"], "verified")
        self.assertEqual(verified["cid"], RECORD_CID)
        self.assertIn("bsky.app/profile/", verified["url"])

    def test_missing_or_altered_media_or_facet_cannot_claim_verified(self):
        raw = valid_png()
        job = manifest("Bluesky", DID, media=[{"id": "img", "mime": "image/png", "alt": "Concert piano"}])
        reference = self.reference(job)
        base = {"$type": "app.bsky.feed.post", "text": job["payload"]["text"],
                "facets": HostedSocial._bluesky_facets(job["payload"]["text"])}
        candidates = [dict(base),
                      {**base, "embed": {"$type": "app.bsky.embed.images", "images": [{"alt": "different", "image": {"ref": {"$link": "bwrong"}, "mimeType": "image/png", "size": len(raw)}}]}},
                      {**base, "facets": []}]
        for record in candidates:
            with self.subTest(record=record):
                social, _, _ = self.social([ok({"uri": reference, "cid": RECORD_CID, "value": record})], raw=raw)
                self.assertEqual(social.reconcile(job, {"providerReference": reference})["state"], "uncertain")

    def test_missing_cid_or_wrong_uri_cannot_claim_verified(self):
        job = manifest("Bluesky", DID)
        reference = self.reference(job)
        record = {"$type": "app.bsky.feed.post", "text": job["payload"]["text"], "facets": HostedSocial._bluesky_facets(job["payload"]["text"])}
        for record_uri, cid in [(reference, None), ("at://did:plc:other/app.bsky.feed.post/abc", RECORD_CID)]:
            with self.subTest(uri=record_uri, cid=cid):
                social, _, _ = self.social([ok({"uri": record_uri, "cid": cid, "value": record})])
                self.assertEqual(social.reconcile(job, {"providerReference": reference})["state"], "uncertain")

    def test_conflicting_existing_post_must_not_be_called_successful(self):
        job = manifest("Bluesky", DID)
        reference = self.reference(job)
        bad_record = {"text": "OTHER", "$type": "app.bsky.feed.post"}
        responses = [ok({"error": "InvalidRequest", "message": "Record already exists"}, 400),
                     ok({"uri": reference, "cid": RECORD_CID, "value": bad_record})]
        social, wire, _ = self.social(responses)
        result = social.submit(job)
        self.assertEqual(result["state"], "uncertain")
        self.assertEqual(len([c for c in wire.calls if "createRecord" in c["url"]]), 1)

    def test_standing_automation_authority_never_approves_bluesky(self):
        from postriff_phase2.publisher import auto_blockers
        task = {"definitionDigest": "v1", "publishAuthority": {"definitionDigest": "v1", "sourceUse": True}}
        reasons = auto_blockers({"sources": []}, task, {}, {"platform": "Bluesky"},
                                {"text": "Approved? Not by a human", "sourceIds": [], "warnings": []})
        self.assertTrue(any("human" in reason.lower() for reason in reasons))

    def test_standing_automation_cannot_commit_even_marked_approved(self):
        from postriff_phase2.publisher import commit
        item = {"key": "one", "platform": "Bluesky", "state": "approved",
                "approvedVia": "owner_preauthorization", "channelId": "conn"}
        state = {"raffi": {"campaignPlanning": {
            "campaigns": [], "recurringTasks": [{"id": "task", "status": "active"}],
            "occurrences": [{"id": "run", "taskId": "task", "items": [item]}]}}}
        with self.assertRaises(AlphaError) as caught:
            commit(None, state, "owner", {"occurrenceId": "run", "itemKey": "one"}, 10.0)
        self.assertEqual(caught.exception.code, "exact_human_approval_required")
        self.assertIsNone(item.get("jobId"))

    def test_daylight_saving_folds_remain_distinct_in_manifest_time(self):
        import datetime as dt
        from postriff_phase2.publisher import _manifest_time
        first = dt.datetime(2026, 11, 1, 5, 30, tzinfo=dt.timezone.utc).timestamp()
        second = dt.datetime(2026, 11, 1, 6, 30, tzinfo=dt.timezone.utc).timestamp()
        one = _manifest_time(first, "America/New_York", first - 500)
        two = _manifest_time(second, "America/New_York", second - 500)
        self.assertEqual(one["localTime"], two["localTime"])
        self.assertEqual((one["fold"], two["fold"]), (0, 1))

    def test_default_https_transport_rejects_private_pds_before_network(self):
        provider = BlueskyProvider(generate_jwk(kid="p0"), BASE, resolver=lambda *a, **k: [
            (2, 1, 6, "", ("10.0.0.2", 443))])
        with self.assertRaises(AlphaError):
            provider._get_json("https://private.example.com/.well-known/oauth-protected-resource")

    def test_invalid_cid_is_not_record_verification(self):
        job = manifest("Bluesky", DID)
        ref = self.reference(job)
        record = {"$type": "app.bsky.feed.post", "text": job["payload"]["text"],
                  "facets": HostedSocial._bluesky_facets(job["payload"]["text"])}
        for bad in ("b", "b!notvalid", "b" + "a" * 58):
            social, _, _ = self.social([ok({"uri": ref, "cid": bad, "value": record})])
            self.assertEqual(social.reconcile(job, {"providerReference": ref})["state"], "uncertain")

    def test_preview_branch_cannot_trigger_automatic_vercel_deployment(self):
        """The exact Git branch is disabled in both projects' checked-in Vercel config."""
        config = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text())
        self.assertIs(config["git"]["deploymentEnabled"].get("codex/rafii-bluesky-p0-20261013"), False)


if __name__ == "__main__":
    unittest.main()
