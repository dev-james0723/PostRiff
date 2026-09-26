"""Wave 3 hosted connectors (Facebook Pages, YouTube, TikTok, Pinterest): adapters, per-post publish options (the TikTok
Content Sharing Guidelines rules), publishing, reconciliation and the approval checks, offline with injected transports."""
import copy
import hashlib
import hmac
import json
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).resolve().parent)]
from postriff_alpha.domain import AlphaError
from postriff_phase2 import providers, publish_options
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.outcomes import normalize_result
from postriff_phase2.wave3_connectors import FacebookPagesProvider, PinterestProvider, TikTokProvider, YouTubeProvider
from test_hosted_wave1_connectors import BASE, Grants, ServiceFlows, Wire, ok

VIDEO = [{"id": "v1", "mime": "video/mp4", "duration": 30.0, "alt": ""}]
IMAGE = [{"id": "i1", "mime": "image/jpeg", "alt": "A score page"}]


def storage(raw=b"\x00" * 1024):
    return SimpleNamespace(storage=SimpleNamespace(get=lambda *a: raw, signed_url=lambda *a: "https://storage.example/object.jpg?token=x"))


def manifest(platform, account, text="Rehearsal notes", media=None, options=None, timing=None):
    m = {"workspaceId": "w", "channelId": "conn", "platform": platform, "operation": "post", "providerAccountId": account, "account": "@james",
         "payload": {"text": text, "language": "en"}, "media": media or [], "idempotencyKey": "k" * 64, "timing": timing or {"timestamp": time.time()}}
    if options is not None:
        m["publishOptions"] = options
    return m


def tiktok_options(**overrides):
    base = {"privacyLevel": "PUBLIC_TO_EVERYONE", "allowComment": False, "allowDuet": False, "allowStitch": False,
            "commercial": {"enabled": False}, "consent": True, "consentText": publish_options.tiktok_consent_text(False)}
    return {**base, **overrides}


# --- mount rules ----------------------------------------------------------------------------------------------------
class MountRules(unittest.TestCase):
    def test_each_adapter_mounts_from_its_own_pair_and_optional_settings(self):
        values = {f"POSTRIFF_OAUTH_{pid.upper()}_{suffix}": f"{pid}-{suffix.lower()}" for pid in ("facebook", "youtube", "tiktok", "pinterest") for suffix in ("CLIENT_ID", "CLIENT_SECRET")}
        registry = providers.registry_from_environment({**values, "POSTRIFF_FACEBOOK_LOGIN_CONFIG_ID": "2961092884234131", "POSTRIFF_PINTEREST_SANDBOX": "true"})
        self.assertEqual({"facebook", "youtube", "tiktok", "pinterest"} <= set(registry), True)
        self.assertEqual((registry["facebook"].config_id, registry["pinterest"].sandbox), ("2961092884234131", True))
        bad = providers.registry_from_environment({**values, "POSTRIFF_FACEBOOK_LOGIN_CONFIG_ID": "not-a-number"})
        self.assertNotIn("facebook", bad)
        self.assertEqual(bad.diagnostics["facebook"]["configurationState"], "invalid_configuration")

    def test_catalog_names_where_each_destination_is_chosen(self):
        from postriff_phase2.oauth import CredentialVault, OAuthService
        catalog = {p["id"]: p for p in OAuthService(None, None, CredentialVault(CredentialVault.generate_key()), {}, BASE).provider_catalog()}
        self.assertEqual((catalog["facebook"]["destinationScope"], catalog["facebook"]["destinationLabel"]), ("connection", "Page"))
        self.assertEqual((catalog["pinterest"]["destinationScope"], catalog["pinterest"]["destinationLabel"]), ("post", "Board"))
        self.assertIn("private", catalog["tiktok"]["accountRequirement"])


# --- Facebook Pages -------------------------------------------------------------------------------------------------
PAGES = {"data": [{"id": "10001", "name": "James Au Studio", "tasks": ["ANALYZE", "CREATE_CONTENT"], "access_token": "PT1"},
                  {"id": "10002", "name": "Read-only Page", "tasks": ["ANALYZE"], "access_token": "PT2"}]}


class FacebookAdapter(unittest.TestCase):
    def test_login_for_business_config_or_scopes(self):
        with_config = FacebookPagesProvider("app", "secret", config_id="2961092884234131")
        query = parse_qs(urlparse(with_config.authorize_url(BASE + "/cb", "S", "C", ["pages_show_list"])).query)
        self.assertEqual((query["config_id"][0], "scope" in query, query["response_type"][0]), ("2961092884234131", False, "code"))
        plain = parse_qs(urlparse(FacebookPagesProvider("app", "secret").authorize_url(BASE + "/cb", "S", "C", ["pages_show_list", "pages_manage_posts"])).query)
        self.assertEqual(plain["scope"][0], "pages_show_list,pages_manage_posts")

    def test_exchange_makes_a_long_lived_token_proves_every_call_and_picks_the_only_page(self):
        wire = Wire([ok({"access_token": "SHORT"}), ok({"access_token": "LONG", "expires_in": 5184000}), ok({"id": "777", "name": "James Au"}),
                     ok({"data": [{"permission": "pages_manage_posts", "status": "granted"}, {"permission": "pages_read_engagement", "status": "granted"},
                                  {"permission": "business_management", "status": "declined"}]}), ok(PAGES)])
        facebook = FacebookPagesProvider("app", "secret", transport=wire)
        grant = facebook.exchange("CODE", "V", BASE + "/api/oauth/facebook/callback")
        session = json.loads(grant["accessToken"])
        self.assertEqual((session["user"], session["page"]["id"], session["page"]["token"]), ("777", "10001", "PT1"))
        self.assertEqual(grant["scopes"], ["pages_manage_posts", "pages_read_engagement"])
        self.assertNotIn("secret", wire.calls[0]["url"])  # the app secret travels in the form body
        query = parse_qs(urlparse(wire.calls[2]["url"]).query)
        self.assertEqual(query["appsecret_proof"][0], hmac.new(b"secret", b"LONG", hashlib.sha256).hexdigest())
        wire.responses.append(ok({"id": "10001", "name": "James Au Studio"}))
        self.assertEqual(facebook.identity(grant["accessToken"]), {"providerAccountId": "777", "handle": "James Au Studio", "accountType": "page"})
        self.assertIn("access_token=PT1", wire.calls[-1]["url"])  # a chosen Page proves access with its own token

    def test_destinations_are_pages_with_create_content_and_revocation_uses_the_query(self):
        session = json.dumps({"v": 1, "user": "777", "ut": "LONG", "scope": ["pages_manage_posts"], "page": None})
        facebook = FacebookPagesProvider("app", "secret", transport=Wire([ok(PAGES), ok(PAGES), ok({"success": True})]))
        self.assertEqual([d["id"] for d in facebook.destinations(session)], ["10001"])
        self.assertEqual(json.loads(facebook.with_destination(session, "10001"))["page"]["token"], "PT1")
        self.assertTrue(facebook.revoke(session))
        self.assertEqual((facebook.transport.calls[-1]["method"], "access_token=LONG" in facebook.transport.calls[-1]["url"]), ("DELETE", True))
        with self.assertRaises(AlphaError):
            FacebookPagesProvider("app", "secret", transport=Wire([ok(PAGES)])).with_destination(session, "10002")

    def test_scopes_stand_on_the_page_token_after_the_user_token_lapses(self):
        session = json.dumps({"v": 1, "user": "777", "ut": "EXPIRED", "scope": ["pages_manage_posts"], "page": {"id": "10001", "name": "Studio", "token": "PT1"}})
        facebook = FacebookPagesProvider("app", "secret", transport=Wire([ok({"error": {"code": 190}}, 400), ok({"id": "10001", "name": "Studio"})]))
        self.assertEqual(facebook.inspect_scopes(session, "777"), ["pages_manage_posts"])
        self.assertIsNone(FacebookPagesProvider("app", "secret", transport=Wire([])).inspect_scopes(session, "999"))


# --- YouTube --------------------------------------------------------------------------------------------------------
class YouTubeAdapter(unittest.TestCase):
    def test_offline_pkce_consent_and_tokeninfo_bound_to_rafii(self):
        youtube = YouTubeProvider("client.apps.googleusercontent.com", "secret", transport=Wire([
            ok({"access_token": "AT", "refresh_token": "RT", "expires_in": 3599, "scope": f"{YouTubeProvider.UPLOAD_SCOPE} {YouTubeProvider.READ_SCOPE}"}),
            ok({"items": [{"id": "UC" + "a" * 22, "snippet": {"title": "James Au", "customUrl": "@jamesau", "thumbnails": {"default": {"url": "https://yt3.ggpht.com/x"}}}}]}),
            ok({"aud": "client.apps.googleusercontent.com", "scope": f"{YouTubeProvider.UPLOAD_SCOPE} {YouTubeProvider.READ_SCOPE}"}),
            ok({"aud": "someone-else", "scope": YouTubeProvider.UPLOAD_SCOPE}),
            ok({"access_token": "AT2", "expires_in": 3599, "scope": YouTubeProvider.UPLOAD_SCOPE})]))
        query = parse_qs(urlparse(youtube.authorize_url(BASE + "/cb", "S", "CHALLENGE", youtube.capability_scopes("publish"))).query)
        self.assertEqual((query["access_type"][0], query["prompt"][0], query["include_granted_scopes"][0], query["code_challenge_method"][0]), ("offline", "consent", "true", "S256"))
        grant = youtube.exchange("CODE", "VERIFIER", BASE + "/cb")
        self.assertEqual(youtube.transport.calls[0]["form"]["code_verifier"], "VERIFIER")
        self.assertEqual(youtube.identity(grant["accessToken"])["handle"], "@jamesau")
        self.assertIn(YouTubeProvider.UPLOAD_SCOPE, youtube.inspect_scopes(grant["accessToken"]))
        self.assertIsNone(youtube.inspect_scopes(grant["accessToken"]))  # a token issued to another client proves nothing
        self.assertEqual(youtube.refresh("RT")["refreshToken"], "RT")

    def test_an_account_without_a_channel_cannot_connect(self):
        youtube = YouTubeProvider("c", "s", transport=Wire([ok({"items": []})]))
        with self.assertRaises(AlphaError):
            youtube.identity(json.dumps({"v": 1, "at": "AT", "scope": []}))


# --- TikTok ---------------------------------------------------------------------------------------------------------
CREATOR = {"data": {"creator_nickname": "James", "creator_username": "jamesau", "privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
                    "comment_disabled": False, "duet_disabled": True, "stitch_disabled": False, "max_video_post_duration_sec": 60}, "error": {"code": "ok"}}


class TikTokAdapter(unittest.TestCase):
    def test_web_flow_uses_state_without_pkce_and_hex_pkce_is_a_switch(self):
        from postriff_phase2.oauth import pkce_pair
        tiktok = TikTokProvider("clientkey", "secret", transport=Wire([ok({"access_token": "AT", "open_id": "OPEN", "scope": "user.info.basic,video.publish", "expires_in": 86400, "refresh_token": "RT"}),
                                                                       ok({"data": {"user": {"open_id": "OPEN", "display_name": "James"}}}), ok(CREATOR)]))
        verifier, challenge = pkce_pair()
        query = parse_qs(urlparse(tiktok.authorize_url(BASE + "/cb", "S", challenge, ["user.info.basic", "video.publish"])).query)
        self.assertEqual((query["client_key"][0], query["scope"][0], query["state"][0]), ("clientkey", "user.info.basic,video.publish", "S"))
        self.assertNotIn("code_challenge", query)
        grant = tiktok.exchange("CODE", verifier, BASE + "/cb")
        self.assertEqual(tiktok.transport.calls[0]["form"]["client_key"], "clientkey")
        self.assertNotIn("code_verifier", tiktok.transport.calls[0]["form"])
        hexed = TikTokProvider("clientkey", "secret", hex_pkce=True, transport=Wire([ok({"access_token": "AT", "scope": "user.info.basic"})]))
        query = parse_qs(urlparse(hexed.authorize_url(BASE + "/cb", "S", challenge, ["user.info.basic"])).query)
        self.assertEqual((query["code_challenge"][0], query["code_challenge_method"][0]), (hashlib.sha256(verifier.encode()).hexdigest(), "S256"))
        hexed.exchange("CODE", verifier, BASE + "/cb")
        self.assertEqual(hexed.transport.calls[0]["form"]["code_verifier"], verifier)
        mounted = providers.registry_from_environment({"POSTRIFF_OAUTH_TIKTOK_CLIENT_ID": "k", "POSTRIFF_OAUTH_TIKTOK_CLIENT_SECRET": "s", "POSTRIFF_TIKTOK_HEX_PKCE": "true"})
        self.assertTrue(mounted["tiktok"].hex_pkce)
        self.assertEqual(tiktok.identity(grant["accessToken"])["providerAccountId"], "OPEN")
        self.assertEqual(tiktok.inspect_scopes(grant["accessToken"], "OPEN"), ["user.info.basic", "video.publish"])
        self.assertIsNone(tiktok.inspect_scopes(grant["accessToken"], "SOMEONE-ELSE"))
        info = tiktok.creator_info(grant["accessToken"])
        self.assertEqual((info["nickname"], info["privacyLevelOptions"], info["duetDisabled"], info["maxVideoPostDurationSec"]), ("James", ["PUBLIC_TO_EVERYONE", "SELF_ONLY"], True, 60))

    def test_chunking_follows_tiktok_limits(self):
        mb = 1024 * 1024
        self.assertEqual(TikTokProvider.chunks(3 * mb), (3 * mb, 1))
        self.assertEqual(TikTokProvider.chunks(70 * mb), (64 * mb, 1))  # the remainder folds into the last chunk
        self.assertEqual(TikTokProvider.chunks(130 * mb), (64 * mb, 2))


# --- Pinterest ------------------------------------------------------------------------------------------------------
class PinterestAdapter(unittest.TestCase):
    def test_basic_auth_token_identity_and_sandbox_boards(self):
        pinterest = PinterestProvider("pid", "psecret", sandbox=True, transport=Wire([ok({"access_token": "AT", "refresh_token": "RT", "scope": "user_accounts:read,boards:read,pins:read,pins:write"}),
                                                                                      ok({"username": "jamesau", "account_type": "BUSINESS"}),
                                                                                      ok({"items": [{"id": "1234567", "name": "Recitals"}, {"id": "bad"}]})]))
        grant = pinterest.exchange("CODE", "V", BASE + "/cb")
        self.assertTrue(pinterest.transport.calls[0]["headers"]["Authorization"].startswith("Basic "))
        self.assertEqual(pinterest.identity(grant["accessToken"])["handle"], "@jamesau")
        self.assertEqual([b["id"] for b in pinterest.destinations(grant["accessToken"])], ["1234567"])
        self.assertTrue(pinterest.transport.calls[2]["url"].startswith(PinterestProvider.SANDBOX))


# --- per-post options -----------------------------------------------------------------------------------------------
class TikTokRules(unittest.TestCase):
    def check(self, **overrides):
        return publish_options.normalize("TikTok", tiktok_options(**overrides), VIDEO, "caption")

    def test_a_complete_choice_is_frozen(self):
        self.assertEqual(self.check()["privacyLevel"], "PUBLIC_TO_EVERYONE")

    def test_no_default_privacy_and_explicit_interactions(self):
        for overrides in ({"privacyLevel": None}, {"privacyLevel": "EVERYONE"}, {"allowComment": None}, {"allowDuet": "yes"}):
            with self.subTest(overrides=overrides), self.assertRaises(AlphaError):
                self.check(**overrides)

    def test_commercial_content_needs_a_kind_and_branded_is_never_private(self):
        with self.assertRaises(AlphaError):
            self.check(commercial={"enabled": True})
        branded_text = publish_options.tiktok_consent_text(True)
        with self.assertRaises(AlphaError):
            self.check(privacyLevel="SELF_ONLY", commercial={"enabled": True, "brandedContent": True}, consentText=branded_text)
        own = self.check(privacyLevel="SELF_ONLY", commercial={"enabled": True, "yourBrand": True})
        self.assertEqual(own["commercial"], {"enabled": True, "yourBrand": True, "brandedContent": False})

    def test_consent_is_explicit_and_matches_the_exact_declaration(self):
        self.assertEqual(publish_options.tiktok_consent_text(False), "By posting, you agree to TikTok's Music Usage Confirmation")
        self.assertEqual(publish_options.tiktok_consent_text(True), "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation")
        with self.assertRaises(AlphaError):
            self.check(consent=False)
        with self.assertRaises(AlphaError):  # branded content needs the branded declaration
            self.check(commercial={"enabled": True, "brandedContent": True})
        self.assertTrue(self.check(commercial={"enabled": True, "brandedContent": True}, consentText=publish_options.tiktok_consent_text(True))["commercial"]["brandedContent"])

    def test_a_video_is_required(self):
        with self.assertRaises(AlphaError):
            publish_options.normalize("TikTok", tiktok_options(), IMAGE, "caption")


class OtherOptions(unittest.TestCase):
    def test_youtube(self):
        good = {"title": "Nocturne rehearsal", "privacyStatus": "unlisted", "madeForKids": False}
        self.assertEqual(publish_options.normalize("YouTube", good, VIDEO, "notes")["privacyStatus"], "unlisted")
        for bad in ({**good, "title": ""}, {**good, "title": "<b>"}, {**good, "privacyStatus": "friends"}, {**good, "madeForKids": None}):
            with self.subTest(bad=bad), self.assertRaises(AlphaError):
                publish_options.normalize("YouTube", bad, VIDEO, "notes")
        with self.assertRaises(AlphaError):
            publish_options.normalize("YouTube", good, VIDEO, "練" * 2000)  # 6,000 bytes
        with self.assertRaises(AlphaError):
            publish_options.normalize("YouTube", good, IMAGE, "notes")

    def test_pinterest(self):
        self.assertEqual(publish_options.normalize("Pinterest", {"boardId": "1234567", "title": "Score", "link": "https://rafii.example"}, IMAGE, "desc")["boardId"], "1234567")
        for bad in ({"boardId": "abc"}, {"boardId": "1234567", "link": "javascript:alert(1)"}, {"boardId": "1234567", "title": "x" * 101}):
            with self.subTest(bad=bad), self.assertRaises(AlphaError):
                publish_options.normalize("Pinterest", bad, IMAGE, "desc")
        with self.assertRaises(AlphaError):
            publish_options.normalize("Pinterest", {"boardId": "1234567"}, [], "desc")

    def test_other_platforms_need_none(self):
        self.assertIsNone(publish_options.normalize("Facebook", None, [], "text"))
        self.assertIsNone(publish_options.normalize("LinkedIn", {"anything": 1}, [], "text"))


# --- publishing -----------------------------------------------------------------------------------------------------
def reviewed(adapter):
    adapter.production_reviewed = True
    return adapter


class FacebookPublishing(unittest.TestCase):
    session = {"v": 1, "user": "777", "ut": "LONG", "scope": ["pages_manage_posts", "pages_read_engagement"], "page": {"id": "10001", "name": "Studio", "token": "PT1"}}

    def social(self, wire, session=None):
        facebook = reviewed(FacebookPagesProvider("app", "secret", transport=wire))
        return HostedSocial(Grants(json.dumps(session or self.session), ["pages_manage_posts", "pages_read_engagement"]), {"facebook": facebook}, storage())

    def test_text_publishes_at_the_approved_time_and_reads_back(self):
        wire = Wire([ok({"id": "10001_20002"}), ok({"id": "10001_20002", "message": "Rehearsal notes", "is_published": True, "from": {"id": "10001"},
                                                  "permalink_url": "https://www.facebook.com/10001/posts/20002"})])
        social = self.social(wire)
        result = social.submit(manifest("Facebook", "777", timing={"timestamp": time.time() + 3600}))
        self.assertEqual(result["state"], "provider_accepted")
        self.assertFalse({"published", "scheduled_publish_time"} & set(wire.calls[0]["form"]))  # never scheduled on Facebook
        self.assertFalse(FacebookPagesProvider.native_schedule)
        verified = social.reconcile(manifest("Facebook", "777"), {"providerReference": result["reference"]})
        self.assertEqual(normalize_result(verified, {"manifest": {"platform": "Facebook"}})["state"], "verified")
        unpublished = self.social(Wire([ok({"id": "10001_20002", "message": "Rehearsal notes", "is_published": False, "from": {"id": "10001"}})]))
        self.assertEqual(unpublished.reconcile(manifest("Facebook", "777"), {"providerReference": "10001_20002"})["state"], "uncertain")

    def test_a_bare_photo_id_is_read_back_by_its_caption(self):
        wire = Wire([ok({"id": "30003", "name": "Rehearsal notes", "page_story_id": "10001_20003", "from": {"id": "10001"}})])
        verified = self.social(wire).reconcile(manifest("Facebook", "777", media=IMAGE), {"providerReference": "30003"})
        self.assertEqual((verified["state"], verified["reference"]), ("verified", "10001_20003"))
        self.assertIn("name,page_story_id", parse_qs(urlparse(wire.calls[0]["url"]).query)["fields"][0])
        wrong = self.social(Wire([ok({"id": "30003", "name": "Something else", "from": {"id": "10001"}})])).reconcile(manifest("Facebook", "777", media=IMAGE), {"providerReference": "30003"})
        self.assertEqual(wrong["state"], "uncertain")

    def test_photo_page_choice_and_graph_errors(self):
        wire = Wire([ok({"id": "30003", "post_id": "10001_20003"})])
        result = self.social(wire).submit(manifest("Facebook", "777", media=IMAGE))
        self.assertEqual((result["reference"], wire.calls[0]["url"].endswith("/10001/photos")), ("10001_20003", True))
        self.assertEqual(self.social(Wire([]), {**self.session, "page": None}).submit(manifest("Facebook", "777"))["state"], "held")
        self.assertEqual(self.social(Wire([ok({"error": {"code": 190, "message": "Session expired"}}, 400)])).submit(manifest("Facebook", "777"))["state"], "held")
        refused = self.social(Wire([ok({"error": {"code": 100, "message": "Invalid parameter"}}, 400)])).submit(manifest("Facebook", "777"))
        self.assertEqual((refused["state"], "Invalid parameter" in refused["confirmed"]), ("failed", True))


class YouTubePublishing(unittest.TestCase):
    options = {"title": "Nocturne rehearsal", "privacyStatus": "public", "madeForKids": False}
    channel = "UC" + "a" * 22

    def social(self, wire):
        youtube = reviewed(YouTubeProvider("c", "s", transport=wire))
        return HostedSocial(Grants(json.dumps({"v": 1, "at": "AT", "scope": [YouTubeProvider.UPLOAD_SCOPE]}), [YouTubeProvider.UPLOAD_SCOPE]), {"youtube": youtube}, storage(b"\x00" * 2048))

    def test_no_video_means_nothing_is_attempted(self):
        wire = Wire([])
        self.assertEqual(self.social(wire).submit(manifest("YouTube", self.channel, options=self.options))["state"], "failed")
        self.assertEqual(wire.calls, [])

    def test_resumable_upload_privacy_note_quota_and_foreign_upload_host(self):
        wire = Wire([ok({}, 200, {"location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc"}), ok({"id": "abcdefghijk", "status": {"uploadStatus": "uploaded"}})])
        result = self.social(wire).submit(manifest("YouTube", self.channel, media=VIDEO, options=self.options))
        self.assertEqual((result["state"], result["reference"]), ("provider_accepted", "abcdefghijk"))
        self.assertIn("private", result["confirmed"])
        opened = wire.calls[0]
        self.assertEqual((opened["headers"]["X-Upload-Content-Length"], opened["body"]["status"]["privacyStatus"]), ("2048", "public"))
        self.assertEqual((wire.calls[1]["method"], len(wire.calls[1]["data"])), ("PUT", 2048))
        quota = ok({"error": {"code": 403, "message": "quota", "errors": [{"reason": "quotaExceeded"}]}}, 403)
        self.assertEqual(self.social(Wire([quota])).submit(manifest("YouTube", self.channel, media=VIDEO, options=self.options))["state"], "held")
        foreign = Wire([ok({}, 200, {"location": "https://evil.example/upload"})])
        self.assertEqual(self.social(foreign).submit(manifest("YouTube", self.channel, media=VIDEO, options=self.options))["state"], "failed")
        self.assertEqual(len(foreign.calls), 1)  # nothing was sent to the foreign host

    def test_a_rejected_upload_ends_failed_with_youtubes_reason(self):
        rejected = ok({"items": [{"snippet": {"channelId": self.channel, "title": self.options["title"]}, "status": {"uploadStatus": "rejected", "rejectionReason": "duplicate"}}]})
        result = self.social(Wire([rejected])).reconcile(manifest("YouTube", self.channel, options=self.options), {"providerReference": "abcdefghijk"})
        normalized = normalize_result(result, {"manifest": {"platform": "YouTube"}}, reconciliation=True)
        self.assertEqual(normalized["state"], "failed")
        self.assertIn("duplicate", normalized["confirmed"])

    def test_readback_and_finding_an_unanswered_upload(self):
        processed = ok({"items": [{"snippet": {"channelId": self.channel, "title": self.options["title"]}, "status": {"uploadStatus": "processed", "privacyStatus": "private"}}]})
        verified = self.social(Wire([processed])).reconcile(manifest("YouTube", self.channel, options=self.options), {"providerReference": "abcdefghijk"})
        self.assertEqual(normalize_result(verified, {"manifest": {"platform": "YouTube"}})["url"], "https://youtu.be/abcdefghijk")
        self.assertIn("kept it private", verified["confirmed"])
    def recover(self, uploads, job):
        playlist = ok({"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU" + "a" * 22}}}]})
        items = [{"snippet": {"title": self.options["title"], "description": "Rehearsal notes", "publishedAt": at, "resourceId": {"videoId": vid}}} for vid, at in uploads]
        return self.social(Wire([playlist, ok({"items": items})])).reconcile(manifest("YouTube", self.channel, options=self.options), job)

    def test_recovery_adopts_one_upload_made_after_this_attempt_never_an_older_one(self):
        job = {"attempts": [{"number": 1, "startedAt": 1_790_000_000}]}
        older = ("olderupload", "2026-09-20T10:00:00Z")
        newer = ("zyxwvutsrqp", datetime.fromtimestamp(1_790_000_030, timezone.utc).isoformat().replace("+00:00", "Z"))
        self.assertEqual(self.recover([older], job)["state"], "uncertain")  # same words, but uploaded before this job tried
        found = self.recover([older, newer], job)
        self.assertEqual((found["state"], found["reference"]), ("provider_accepted", "zyxwvutsrqp"))
        twin = ("abcdefghijk", datetime.fromtimestamp(1_790_000_040, timezone.utc).isoformat().replace("+00:00", "Z"))
        self.assertEqual(self.recover([newer, twin], job)["state"], "uncertain")  # two candidates: never guess
        self.assertEqual(self.social(Wire([])).reconcile(manifest("YouTube", self.channel, options=self.options), {})["state"], "uncertain")  # no attempt time


class TikTokPublishing(unittest.TestCase):
    def social(self, wire, raw=b"\x00" * 4096):
        tiktok = reviewed(TikTokProvider("key", "secret", transport=wire))
        return HostedSocial(Grants(json.dumps({"v": 1, "at": "AT", "scope": ["video.publish"], "openId": "OPEN"}), ["video.publish"]), {"tiktok": tiktok}, storage(raw))

    def test_creator_settings_are_read_again_and_win(self):
        init = ok({"data": {"publish_id": "v_pub_1", "upload_url": "https://open-upload.tiktokapis.com/video/?upload_id=1"}, "error": {"code": "ok"}})
        wire = Wire([ok(CREATOR), init, ok({}, 201)])
        result = self.social(wire).submit(manifest("TikTok", "OPEN", media=VIDEO, options=tiktok_options(allowDuet=True, allowComment=True)))
        self.assertEqual((result["state"], result["reference"]), ("provider_accepted", "v_pub_1"))
        post_info = wire.calls[1]["body"]["post_info"]
        self.assertEqual((post_info["disable_duet"], post_info["disable_comment"], post_info["disable_stitch"]), (True, False, True))  # duet off by the creator
        self.assertEqual(wire.calls[2]["headers"]["Content-Range"], "bytes 0-4095/4096")
        self.assertIn("private", result["confirmed"])

    def test_privacy_no_longer_offered_duration_and_unaudited(self):
        narrow = {**CREATOR, "data": {**CREATOR["data"], "privacy_level_options": ["SELF_ONLY"]}}
        self.assertEqual(self.social(Wire([ok(narrow)])).submit(manifest("TikTok", "OPEN", media=VIDEO, options=tiktok_options()))["state"], "held")
        long_video = [{**VIDEO[0], "duration": 90.0}]
        self.assertEqual(self.social(Wire([ok(CREATOR)])).submit(manifest("TikTok", "OPEN", media=long_video, options=tiktok_options()))["state"], "failed")
        unaudited = ok({"error": {"code": "unaudited_client_can_only_post_to_private_accounts", "message": "private only"}}, 403)
        refused = self.social(Wire([ok(CREATOR), unaudited])).submit(manifest("TikTok", "OPEN", media=VIDEO, options=tiktok_options()))
        self.assertEqual(refused["state"], "failed")
        self.assertIn("audits Rafii", refused["confirmed"])

    def test_a_foreign_upload_host_sends_nothing_and_fails(self):
        init = ok({"data": {"publish_id": "v_pub_2", "upload_url": "https://uploads.evil.example/video"}, "error": {"code": "ok"}})
        wire = Wire([ok(CREATOR), init])
        self.assertEqual(self.social(wire).submit(manifest("TikTok", "OPEN", media=VIDEO, options=tiktok_options()))["state"], "failed")
        self.assertEqual(len(wire.calls), 2)  # no bytes went to the foreign host

    def test_status_readback(self):
        failed = self.social(Wire([ok({"data": {"status": "FAILED", "fail_reason": "video_pull_failed"}})])).reconcile(manifest("TikTok", "OPEN", options=tiktok_options()), {"providerReference": "v_pub_1"})
        normalized = normalize_result(failed, {"manifest": {"platform": "TikTok"}}, reconciliation=True)
        self.assertEqual((normalized["state"], "video_pull_failed" in normalized["confirmed"]), ("failed", True))
        done = self.social(Wire([ok({"data": {"status": "PUBLISH_COMPLETE"}})])).reconcile(manifest("TikTok", "OPEN", options=tiktok_options()), {"providerReference": "v_pub_1"})
        self.assertEqual(normalize_result(done, {"manifest": {"platform": "TikTok"}})["state"], "verified")
        waiting = self.social(Wire([ok({"data": {"status": "PROCESSING_UPLOAD"}})])).reconcile(manifest("TikTok", "OPEN", options=tiktok_options()), {"providerReference": "v_pub_1"})
        self.assertEqual(waiting["state"], "provider_accepted")


class PinterestPublishing(unittest.TestCase):
    options = {"boardId": "1234567", "title": "Score", "link": "https://rafii.example/score"}

    def social(self, wire, sandbox=False):
        pinterest = reviewed(PinterestProvider("pid", "secret", sandbox=sandbox, transport=wire))
        return HostedSocial(Grants(json.dumps({"v": 1, "at": "AT", "scope": ["pins:write", "boards:read"]}), ["pins:write", "boards:read"]), {"pinterest": pinterest}, storage())

    BOARDS = ok({"items": [{"id": "1234567", "name": "Recitals"}]})

    def test_pin_in_the_sandbox_rejection_and_readback(self):
        wire = Wire([self.BOARDS, ok({"id": "987654321"}, 201)])
        result = self.social(wire, sandbox=True).submit(manifest("Pinterest", "jamesau", media=IMAGE, options=self.options))
        self.assertEqual((result["state"], wire.calls[1]["url"]), ("provider_accepted", PinterestProvider.SANDBOX + "/v5/pins"))
        self.assertTrue(wire.calls[0]["url"].startswith(PinterestProvider.SANDBOX + "/v5/boards"))  # the board is checked where the Pin goes
        body = wire.calls[1]["body"]
        self.assertEqual((body["board_id"], body["media_source"]["source_type"], body["link"], body["alt_text"]), ("1234567", "image_url", "https://rafii.example/score", "A score page"))
        refused = self.social(Wire([self.BOARDS, ok({"code": 1, "message": "Board not found."}, 400)])).submit(manifest("Pinterest", "jamesau", media=IMAGE, options=self.options))
        self.assertEqual((refused["state"], "Board not found." in refused["confirmed"]), ("failed", True))

    def test_a_board_that_is_not_this_accounts_own_is_refused(self):
        wire = Wire([ok({"items": [{"id": "7654321", "name": "Other"}], "bookmark": "next"}), ok({"items": [{"id": "5555555", "name": "More"}]})])
        refused = self.social(wire).submit(manifest("Pinterest", "jamesau", media=IMAGE, options=self.options))
        self.assertEqual((refused["state"], len(wire.calls)), ("failed", 2))  # both pages read, and no Pin was attempted
        self.assertIn("bookmark=next", wire.calls[1]["url"])
        for status, words in ((404, "can't find that board"), (403, "won't let this account pin")):
            with self.subTest(status=status):
                result = self.social(Wire([self.BOARDS, ok({"code": 3, "message": "Board is gone"}, status)])).submit(manifest("Pinterest", "jamesau", media=IMAGE, options=self.options))
                self.assertEqual((result["state"], words in result["confirmed"]), ("failed", True))
        verified = self.social(Wire([ok({"id": "987654321", "board_id": "1234567", "description": "Rehearsal notes"})])).reconcile(
            manifest("Pinterest", "jamesau", options=self.options), {"providerReference": "987654321"})
        self.assertEqual(normalize_result(verified, {"manifest": {"platform": "Pinterest"}})["url"], "https://www.pinterest.com/pin/987654321/")


# --- service flows and approval checks ------------------------------------------------------------------------------
class ServiceChecks(unittest.TestCase):
    def service(self, adapters):
        flows = ServiceFlows()
        service = flows.service(adapters)
        return service, flows.repo

    def credential(self, service, repo, provider, account, blob, scopes):
        ciphertext, key_id = service.vault.encrypt(json.dumps(blob))
        repo.db.credentials["conn"] = {"workspace": "workspace", "provider": provider, "account": account, "access": ciphertext, "key_id": key_id, "scopes": scopes, "expires": None, "revoked": False}

    def test_creator_info_is_fresh_and_sanitized_and_boards_are_per_post(self):
        tiktok = TikTokProvider("key", "secret", transport=Wire([ok(CREATOR)]))
        service, repo = self.service({"tiktok": tiktok})
        self.credential(service, repo, "tiktok", "OPEN", {"v": 1, "at": "AT", "scope": ["video.publish"], "openId": "OPEN"}, ["video.publish"])
        info = service.creator_info("workspace", "session", "conn")
        self.assertEqual(set(info), {"nickname", "username", "avatarUrl", "privacyLevelOptions", "commentDisabled", "duetDisabled", "stitchDisabled", "maxVideoPostDurationSec"})
        tiktok.transport = Wire([ok({"error": {"code": "spam_risk_too_many_posts", "message": "Too many posts"}}, 403)])
        with self.assertRaises(AlphaError):
            service.creator_info("workspace", "session", "conn")
        pinterest = PinterestProvider("pid", "secret", transport=Wire([ok({"items": [{"id": "1234567", "name": "Recitals"}]})]))
        service, repo = self.service({"pinterest": pinterest})
        self.credential(service, repo, "pinterest", "jamesau", {"v": 1, "at": "AT", "scope": ["boards:read"]}, ["boards:read"])
        listed = service.destinations("workspace", "session", "conn")
        self.assertEqual((listed["scope"], listed["destinations"][0]["id"]), ("post", "1234567"))
        with self.assertRaises(AlphaError):
            service.choose_destination("workspace", "session", "conn", "1234567")  # a board is chosen per Pin


class ApprovalChecks(unittest.TestCase):
    """build_manifest: options are required and frozen for Pinterest; video platforms say plainly why they wait."""
    import test_postriff_phase2 as _phase2
    setUp, tearDown = _phase2.Phase2Acceptance.setUp, _phase2.Phase2Acceptance.tearDown
    channel, draft = _phase2.Phase2Acceptance.channel, _phase2.Phase2Acceptance.draft

    def build(self, platform, options=None, image=False):
        from datetime import datetime, timezone
        if not hasattr(self, "prepared"):
            self.prepared = (self.draft(), self.channel())
        variant, channel = self.prepared
        state = copy.deepcopy(self.j.state)
        state["variants"][0].update(platform=platform, text="Rehearsal notes")
        next(c for c in state["phase2"]["channels"] if c["id"] == channel["id"])["platform"] = platform
        payload = {"channelId": channel["id"], "variantId": variant["id"], "localTime": datetime.fromtimestamp(self.now + 60, timezone.utc).replace(tzinfo=None).isoformat(),
                   "timeZone": "UTC", "acknowledgedWarnings": variant["warnings"], "publishOptions": options}
        if image:
            state["phase2"]["assets"].append({"id": "asset-1", "deleted": False, "processing": "decoded", "width": 1000, "height": 1000, "hash": "h", "sourceHash": "s",
                                              "mime": "image/jpeg", "bytes": 10, "duration": 0})
            payload.update(assetId="asset-1", alt="A score page", rightsConfirmed=True)
        return self.store.build_manifest(state, payload, "actor")

    def test_pinterest_options_are_required_and_frozen_into_the_key(self):
        with self.assertRaises(AlphaError):
            self.build("Pinterest", None, image=True)
        first = self.build("Pinterest", {"boardId": "1234567"}, image=True)
        second = self.build("Pinterest", {"boardId": "7654321"}, image=True)
        self.assertEqual(first["publishOptions"]["boardId"], "1234567")
        self.assertNotEqual(first["idempotencyKey"], second["idempotencyKey"])

    def test_video_platforms_wait_honestly_and_others_are_unchanged(self):
        for platform, options in (("YouTube", {"title": "t", "privacyStatus": "private", "madeForKids": False}), ("TikTok", tiktok_options())):
            with self.subTest(platform=platform), self.assertRaises(AlphaError) as refused:
                self.build(platform, options, image=True)
            self.assertIn("video", str(refused.exception))
        self.assertNotIn("publishOptions", self.build("Facebook"))

    def test_youtube_day_is_full_at_one_hundred_planned_uploads(self):
        day = {"jobs": [{"state": "scheduled", "manifest": {"platform": "YouTube", "timing": {"timestamp": 1_790_000_000 + i}}} for i in range(100)]}
        with self.assertRaises(AlphaError):
            self.store._youtube_day_open(day, 1_790_000_500)
        day["jobs"][0]["state"] = "failed"
        self.store._youtube_day_open(day, 1_790_000_500)  # a failed job frees its place


if __name__ == "__main__":
    unittest.main()
