"""Wave 4C provider contracts and no-network Pixelfed/Xiaohongshu fixtures."""
import hashlib
import hmac
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.provider_base import NORMALIZED_CAPABILITY_KEYS, NORMALIZED_CAPABILITY_VALUES
from postriff_phase2.providers import registry_from_environment
from postriff_phase2.wave4c_connectors import PixelfedProvider, XiaohongshuProvider, verify_xiaohongshu_webhook


BASE = "https://rafii.example"


def public_address(host, port, type=None):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def response(body=None, status=200):
    return {"status": status, "headers": {}, "body": {} if body is None else body}


def xhs(data, code=0, success=True):
    return response({"code": code, "success": success, "msg": "fixture", "data": data})


class Wire:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, url, headers=None, form=None, body=None, data=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "form": form, "body": body, "data": data})
        if not self.replies:
            raise AssertionError("Unexpected provider request")
        return self.replies.pop(0)


class WebhookDatabase:
    def __init__(self, state):
        self.events = {}
        self.state = state
        self.revoked = False
        self.capabilities_disabled = False
        self.audit = []

    def cursor(self):
        return WebhookCursor(self)


class WebhookCursor:
    def __init__(self, database):
        self.database = database
        self.one = None
        self.many = []

    def execute(self, sql, params=()):
        statement = " ".join(sql.split())
        if statement.startswith("INSERT INTO public.pr_social_provider_events"):
            event_id, event_type, digest = params
            if event_id in self.database.events:
                self.one = None
            else:
                self.database.events[event_id] = {"type": event_type, "digest": digest, "outcome": None}
                self.one = (event_id,)
        elif statement.startswith("SELECT workspace_id::text,connection_id"):
            self.many = [] if self.database.revoked or params[0] != "open-1" else [("workspace", "connection")]
        elif statement.startswith("UPDATE public.pr_encrypted_credentials SET access_ciphertext='',"):
            self.database.revoked = True
        elif statement.startswith("UPDATE public.pr_channel_capabilities"):
            self.database.capabilities_disabled = True
        elif statement.startswith("SELECT state FROM public.pr_workspaces"):
            self.one = (self.database.state,)
        elif statement.startswith("UPDATE public.pr_workspaces SET state="):
            self.database.state = json.loads(params[0])
        elif statement.startswith("INSERT INTO public.pr_audit_events"):
            self.database.audit.append(params[2])
        elif statement.startswith("UPDATE public.pr_social_provider_events SET processed_at"):
            self.database.events[params[1]]["outcome"] = params[0]
        else:
            raise AssertionError("Unexpected SQL: " + statement)

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class WebhookRepository:
    def __init__(self, database):
        self.database = database

    @contextmanager
    def connection_factory(self):
        @contextmanager
        def cursor():
            yield self.database.cursor()
        yield SimpleNamespace(cursor=cursor)


class Wave4CContracts(unittest.TestCase):
    def test_every_provider_declares_the_complete_normalized_contract(self):
        for provider in (PixelfedProvider, XiaohongshuProvider):
            with self.subTest(provider=provider.id):
                matrix = provider.normalized_capabilities()
                self.assertEqual(tuple(matrix), NORMALIZED_CAPABILITY_KEYS)
                self.assertTrue(set(matrix.values()) <= NORMALIZED_CAPABILITY_VALUES)

    def test_content_actions_stay_out_of_the_connect_ui(self):
        for provider in (PixelfedProvider, XiaohongshuProvider):
            matrix = provider.normalized_capabilities()
            self.assertNotEqual(matrix["publish_image"], "supported")
            self.assertEqual(provider.SCOPES, {"identity": ["read"]} if provider is PixelfedProvider else {"identity": ["basic_info"]})

    def test_independent_flags_and_xiaohongshu_provider_approval_fail_closed(self):
        values = {
            "POSTRIFF_OAUTH_XIAOHONGSHU_CLIENT_ID": "fixture-client",
            "POSTRIFF_OAUTH_XIAOHONGSHU_CLIENT_" + "SECRET": "fixture-credential",
            "POSTRIFF_OAUTH_XIAOHONGSHU_ENABLED": "true",
        }
        blocked = registry_from_environment(values, transport=Wire([]))
        self.assertFalse(blocked["xiaohongshu"].execution_enabled)
        service = OAuthService(None, None, CredentialVault(CredentialVault.generate_key()), blocked, BASE)
        item = next(entry for entry in service.provider_catalog() if entry["id"] == "xiaohongshu")
        self.assertFalse(item["connectReady"])
        self.assertFalse(item["capabilities"]["publish"])
        self.assertEqual(item["connectKind"], "device_code")
        with self.assertRaisesRegex(AlphaError, "provider application approval"):
            service.start("workspace", "session", "xiaohongshu", "identity")

        values["POSTRIFF_OAUTH_XIAOHONGSHU_VERIFIED"] = "true"
        values["POSTRIFF_OAUTH_XIAOHONGSHU_WEBHOOK_VERIFIED"] = "true"
        ready = registry_from_environment(values, transport=Wire([]))
        self.assertTrue(ready["xiaohongshu"].execution_enabled)
        self.assertFalse(ready.diagnostics["xiaohongshu"]["webhookVerified"])
        values["POSTRIFF_OAUTH_XIAOHONGSHU_WEBHOOK_SECRET"] = "w" * 32
        ready = registry_from_environment(values, transport=Wire([]))
        self.assertTrue(ready.diagnostics["xiaohongshu"]["webhookVerified"])
        self.assertNotIn("w" * 32, json.dumps(ready.diagnostics))
        ready_item = next(entry for entry in OAuthService(None, None, CredentialVault(CredentialVault.generate_key()), ready, BASE).provider_catalog()
                          if entry["id"] == "xiaohongshu")
        self.assertTrue(ready_item["connectReady"])


class PixelfedOAuth(unittest.TestCase):
    def test_probes_instance_then_reuses_dynamic_registration_pkce_identity_and_revoke(self):
        wire = Wire([
            response({"version": "3.5.3 (compatible; Pixelfed 0.12.4)", "software": {"name": "pixelfed"}}),
            response({"client_id": "instance-client", "client_secret": "instance-credential"}),
            response({"access_token": "TOKEN", "scope": "read"}),
            response({"id": "9001", "username": "creator"}),
            response({"name": "Rafii", "scopes": ["read"]}),
            response({}, 200),
        ])
        provider = PixelfedProvider(BASE, transport=wire, resolver=public_address)
        begun = provider.begin(BASE + "/api/oauth/pixelfed/callback", "STATE", "VERIFIER", "CHALLENGE", ["read"], "photos.example.org")
        self.assertEqual([call["url"] for call in wire.calls[:2]], ["https://photos.example.org/api/v2/instance", "https://photos.example.org/api/v1/apps"])
        query = parse_qs(urlparse(begun["authorizeUrl"]).query)
        self.assertEqual((query["scope"], query["code_challenge_method"]), (["read"], ["S256"]))
        grant = provider.exchange("CODE", json.dumps({"verifier": "VERIFIER", **begun["context"]}), BASE + "/api/oauth/pixelfed/callback")
        identity = provider.identity(grant["accessToken"])
        self.assertEqual((identity["providerAccountId"], identity["handle"]), ("9001@photos.example.org", "@creator@photos.example.org"))
        self.assertEqual(provider.inspect_scopes(grant["accessToken"]), ["read"])
        self.assertTrue(provider.revoke(grant["accessToken"]))

    def test_non_pixelfed_instance_is_rejected_before_dynamic_registration(self):
        wire = Wire([response({"version": "4.3.0", "software": {"name": "mastodon"}})])
        provider = PixelfedProvider(BASE, transport=wire, resolver=public_address)
        with self.assertRaisesRegex(AlphaError, "did not identify"):
            provider.begin(BASE + "/callback", "STATE", "VERIFIER", "CHALLENGE", ["read"], "social.example.org")
        self.assertEqual(len(wire.calls), 1)


class XiaohongshuOAuth(unittest.TestCase):
    def test_device_flow_keeps_device_code_server_side_then_refreshes_and_revokes(self):
        wire = Wire([
            xhs({"device_code": "DEVICE-CREDENTIAL", "user_code": "ABCD-EFGH",
                 "verification_uri_complete": "https://openaccount.xiaohongshu.com/device?user_code=ABCD-EFGH",
                 "expires_in": 600, "interval": 1}),
            xhs(None, code=37002, success=False),
            xhs({"access_token": "AT", "refresh_token": "RT", "expire_time": 2_000_000_000,
                 "refresh_expire_time": 2_100_000_000, "open_id": "open-1", "scope": ["basic_info"]}),
            xhs({"open_id": "open-1", "nickname": "Creator", "avatar": "https://example.invalid/a.jpg"}),
            xhs({"access_token": "AT", "expire_time": 2_000_000_000, "open_id": "open-1", "scope": ["basic_info"]}),
            xhs({"access_token": "AT2", "refresh_token": "RT2", "expire_time": 2_000_000_000,
                 "refresh_expire_time": 2_100_000_000, "open_id": "open-1", "scope": ["basic_info"]}),
            xhs({"open_id": "open-1", "already_revoked": False}),
        ])
        provider = XiaohongshuProvider("fixture-client", "fixture-credential", transport=wire)
        begun = provider.begin_device("state-value", ["basic_info"])
        public_fields = {key: value for key, value in begun.items() if key != "context"}
        self.assertNotIn("DEVICE-CREDENTIAL", json.dumps(public_fields))
        self.assertEqual(begun["context"]["deviceCode"], "DEVICE-CREDENTIAL")
        self.assertEqual(provider.poll_device(begun["context"]), {"pending": True, "reason": "waiting"})
        grant = provider.poll_device(begun["context"])["grant"]
        self.assertEqual(provider.identity(grant["accessToken"])["providerAccountId"], "open-1")
        self.assertEqual(provider.inspect_scopes(grant["accessToken"], "open-1"), ["basic_info"])
        refreshed = provider.refresh("RT")
        self.assertEqual(refreshed["refreshToken"], "RT2")
        self.assertTrue(provider.revoke(refreshed["accessToken"]))
        self.assertEqual(wire.calls[-1]["body"]["reason"], "user_unbind")
        self.assertIn("app_secret", wire.calls[-1]["body"])

    def test_webhook_signature_uses_timestamp_dot_exact_raw_bytes_and_rejects_replay_window(self):
        material = "fixture-webhook-material-at-least-32-chars"
        timestamp = "1786608000000"
        raw = b'{"event_id":"evt_fixture","event_type":"authorization_revoked"}'
        signature = hmac.new(material.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        self.assertTrue(verify_xiaohongshu_webhook(material, timestamp, raw, signature, now_ms=1_786_608_000_000))
        self.assertFalse(verify_xiaohongshu_webhook(material, timestamp, raw + b" ", signature, now_ms=1_786_608_000_000))
        self.assertFalse(verify_xiaohongshu_webhook(material, timestamp, raw, signature, now_ms=1_786_608_300_001))

    def test_revocation_webhook_is_signed_idempotent_and_revokes_every_local_capability(self):
        timestamp = "1786608000000"
        material = "fixture-webhook-material-at-least-32-chars"
        payload = {"event_id": "evt_fixture", "event_type": "authorization_revoked",
                   "app_id": "fixture-client", "open_id": "open-1", "revoke_source": "user_app",
                   "event_time": int(timestamp)}
        raw = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(material.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        state = {"phase2": {"channels": [{"id": "connection", "revoked": False,
                                             "identityVerified": True, "capabilityVerified": True,
                                             "expiresAt": 1_900_000_000}]}}
        database = WebhookDatabase(state)
        provider = XiaohongshuProvider("fixture-client", "fixture-credential", webhook_secret=material)
        commands = SimpleNamespace(engine=SimpleNamespace(invalidate=lambda _state: None))
        service = OAuthService(WebhookRepository(database), commands, CredentialVault(CredentialVault.generate_key()),
                               {"xiaohongshu": provider}, BASE, clock=lambda: int(timestamp) / 1000)
        headers = {"eventId": "evt_fixture", "eventType": "authorization_revoked",
                   "timestamp": timestamp, "signature": signature}
        self.assertEqual(service.xiaohongshu_webhook(headers, raw), {"code": 0, "msg": "success"})
        self.assertEqual(service.xiaohongshu_webhook(headers, raw), {"code": 0, "msg": "success"})
        channel = database.state["phase2"]["channels"][0]
        self.assertTrue(database.revoked)
        self.assertTrue(database.capabilities_disabled)
        self.assertEqual((channel["revoked"], channel["identityVerified"], channel["capabilityVerified"]),
                         (True, False, False))
        self.assertEqual(database.events["evt_fixture"]["outcome"], "revoked")
        self.assertEqual(database.audit, ["channel.revoked_by_provider"])

        bad = {**headers, "signature": "0" * 64}
        self.assertEqual(service.xiaohongshu_webhook(bad, raw)["code"], 1001)

    def test_invalid_provider_payloads_are_mapped_without_upstream_details(self):
        provider = XiaohongshuProvider("fixture-client", "fixture-credential", transport=Wire([response({"code": 50001, "success": False, "msg": "private detail"})]))
        with self.assertRaisesRegex(AlphaError, "did not complete") as caught:
            provider.begin_device("state", ["basic_info"])
        self.assertNotIn("private detail", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
