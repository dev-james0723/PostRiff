"""Synthetic Wave 4 write-path checks. No real provider request or publication."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.net_guard import pinned_public_json_transport
from postriff_phase2.provider_media import stream_multipart_video
from postriff_phase2.wave4_connectors import GoogleBusinessProfileProvider
from postriff_phase2.wave4_publishers import DouyinVideos, GoogleBusinessPosts, KuaishouVideos, PixelfedPosts
from postriff_phase2.publish_options import normalize


def reply(body, status=200):
    return {"status": status, "body": body, "headers": {}}


class Wire:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.replies:
            raise AssertionError("Unexpected provider call")
        return self.replies.pop(0)


class Security(unittest.TestCase):
    def test_douyin_video_upload_never_uses_a_provider_supplied_host(self):
        with self.assertRaises(AlphaError):
            stream_multipart_video("https://other.example/upload", "TOKEN", iter((b"video",)), 5)

    def test_public_transport_rejects_private_dns_and_malformed_ports_before_connect(self):
        for url in ("https://photos.example.org:bad/api/v1/apps", "https://photos.example.org:444/api/v1/apps"):
            with self.subTest(url=url), self.assertRaises(AlphaError):
                pinned_public_json_transport("GET", url, resolver=lambda *_a, **_k: [])
        private = lambda *_a, **_k: [(2, 1, 6, "", ("127.0.0.1", 443))]
        with patch("postriff_phase2.net_guard.socket.create_connection") as connect:
            with self.assertRaises(AlphaError):
                pinned_public_json_transport("GET", "https://photos.example.org/api/v2/instance", resolver=private)
            connect.assert_not_called()

    def test_dns_is_resolved_once_and_the_validated_address_is_used_for_tls(self):
        lookups = []

        def resolver(*_a, **_k):
            lookups.append(True)
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        class Response:
            status = 200
            def read(self, _size): return b'{}'
            def getheader(self, _key, _default=""): return "application/json"
            def getheaders(self): return []

        class Connection:
            def __init__(self, host, **_kw):
                self._context = SimpleNamespace(wrap_socket=lambda sock, **_kw: sock)
            def request(self, *_a, **_kw): pass
            def getresponse(self): return Response()
            def close(self): pass

        with patch("postriff_phase2.net_guard.http.client.HTTPSConnection", Connection), patch(
            "postriff_phase2.net_guard.socket.create_connection", return_value=SimpleNamespace(close=lambda: None)
        ) as connect:
            self.assertEqual(pinned_public_json_transport("GET", "https://photos.example.org/api/v2/instance", resolver=resolver)["status"], 200)
        self.assertEqual(len(lookups), 1)
        connect.assert_called_once_with(("93.184.216.34", 443), timeout=20)


class BusinessPosts(unittest.TestCase):
    def test_refresh_keeps_the_exact_selected_location(self):
        provider = GoogleBusinessProfileProvider("app", "secret", transport=Wire([]))
        previous = json.dumps({"v": 1, "at": "old", "location": "accounts/100/locations/10", "locationName": "Downtown"})
        fresh = json.dumps({"v": 1, "at": "new", "location": None})
        result = json.loads(provider.preserve_destination(previous, fresh))
        self.assertEqual(result["location"], "accounts/100/locations/10")
        self.assertEqual(result["locationName"], "Downtown")
        self.assertEqual(result["at"], "new")

    def test_event_and_offer_options_are_exact_and_validated(self):
        schedule = {"startDate": {"year": 2026, "month": 10, "day": 1}, "startTime": {"hours": 10, "minutes": 0},
                    "endDate": {"year": 2026, "month": 10, "day": 2}, "endTime": {"hours": 11, "minutes": 0}}
        chosen = {"gbp": {"topicType": "OFFER", "event": {"title": "Autumn Offer", "schedule": schedule},
                          "offer": {"couponCode": "OCT", "redeemOnlineUrl": "https://example.org/redeem"}}}
        self.assertEqual(normalize("Google Business Profile", chosen, [], "Welcome"), chosen)
        with self.assertRaises(AlphaError):
            normalize("Google Business Profile", {"gbp": {"topicType": "OFFER", "offer": chosen["gbp"]["offer"]}}, [], "Welcome")
        with self.assertRaises(AlphaError):
            normalize("Google Business Profile", {"gbp": {**chosen["gbp"], "offer": {"redeemOnlineUrl": "http://example.org"}}}, [], "Welcome")

    def test_selected_location_and_exact_content_required_for_live_reconciliation(self):
        wire = Wire([
            reply({"accounts": [{"name": "accounts/100"}]}),
            reply({"locations": [{"name": "locations/10", "title": "Downtown"}]}),
            reply({"name": "accounts/100/locations/10/localPosts/post1"}, 201),
            reply({"accounts": [{"name": "accounts/100"}]}),
            reply({"locations": [{"name": "locations/10", "title": "Downtown"}]}),
            reply({"name": "accounts/100/locations/10/localPosts/post1", "summary": "Welcome", "topicType": "STANDARD", "state": "LIVE"}),
        ])
        provider = GoogleBusinessProfileProvider("app", "secret", transport=wire)
        token = json.dumps({"v": 1, "at": "TOKEN", "location": "accounts/100/locations/10"})
        manifest = {"payload": {"text": "Welcome"}, "media": []}
        submitted = GoogleBusinessPosts().submit(manifest, provider, token, SimpleNamespace())
        self.assertEqual(submitted["state"], "provider_accepted")
        verified = GoogleBusinessPosts().reconcile(manifest, {"providerReference": submitted["reference"]}, provider, token, SimpleNamespace())
        self.assertEqual(verified["state"], "verified")
        self.assertTrue(wire.calls[2][1].startswith("https://mybusiness.googleapis.com/v4/accounts/100/locations/10/"))

    def test_no_selected_location_prevents_post(self):
        provider = GoogleBusinessProfileProvider("app", "secret", transport=Wire([]))
        token = json.dumps({"v": 1, "at": "TOKEN", "location": None})
        with self.assertRaisesRegex(AlphaError, "Choose a Business Profile location"):
            GoogleBusinessPosts().submit({"payload": {"text": "Welcome"}, "media": []}, provider, token, SimpleNamespace())


class MediaPublishers(unittest.TestCase):
    def test_pixelfed_upload_then_status_then_exact_owner_and_content_readback(self):
        class Provider:
            def __init__(self):
                self.wire = Wire([
                    reply({"id": "media1"}, 201), reply({"id": "media1", "url": "https://photos.example.org/media1"}),
                    reply({"id": "post1", "account": {"id": "42"}}, 201),
                    reply({"id": "post1", "account": {"id": "42"}, "content": "<p>Hello</p>", "visibility": "public", "url": "https://photos.example.org/p/post1"}),
                ])
            def session(self, _token): return {"instance": "photos.example.org", "at": "TOKEN"}
            def api(self, session, method, path, **kw): return self.wire(method, path, **kw)

        provider = Provider()
        manifest = {"providerAccountId": "42@photos.example.org", "media": [{"mime": "image/jpeg"}],
                    "payload": {"text": "Hello"}, "idempotencyKey": "approved-key"}
        social = SimpleNamespace(_image=lambda _manifest: (b"\xff\xd8fixture", "image/jpeg", ""), sleep=lambda _seconds: None)
        posted = PixelfedPosts().submit(manifest, provider, "TOKEN", social)
        self.assertEqual(posted["state"], "provider_accepted")
        verified = PixelfedPosts().reconcile(manifest, {"providerReference": posted["reference"]}, provider, "TOKEN", social)
        self.assertEqual(verified["state"], "verified")
        self.assertEqual([call[1] for call in provider.wire.calls],
                         ["/api/v1/media", "/api/v1/media/media1", "/api/v1/statuses", "/api/v1/statuses/post1"])
        self.assertEqual(provider.wire.calls[2][2]["form"]["visibility"], "public")

    def test_douyin_create_ambiguity_stays_uncertain_and_is_not_retried(self):
        wire = Wire([reply({"data": {"error_code": 10}})])
        provider = SimpleNamespace(transport=wire, session=lambda _token: {"openId": "owner", "at": "TOKEN"})
        social = SimpleNamespace(_video_stream=lambda _manifest: (iter((b"video",)), {"bytes": 5}))
        manifest = {"payload": {"text": "Hello"}, "providerAccountId": "owner"}
        with patch("postriff_phase2.wave4_publishers.stream_multipart_video", return_value=reply({"data": {"error_code": 0, "video": {"video_id": "video1"}}})):
            result = DouyinVideos().submit(manifest, provider, "TOKEN", social)
        self.assertEqual(result["state"], "uncertain")
        self.assertEqual(len(wire.calls), 1)

    def test_kuaishou_never_accepts_an_arbitrary_upload_gateway(self):
        for host in ("localhost", "evilgifshow.com", "video.gifshow.com.evil.org", "127.0.0.1", "video.gifshow.com:80"):
            with self.subTest(host=host), self.assertRaises(AlphaError):
                KuaishouVideos._gateway(host)


if __name__ == "__main__":
    unittest.main()
