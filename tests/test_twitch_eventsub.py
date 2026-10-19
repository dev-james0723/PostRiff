"""Offline byte-authentication and custody boundaries for Twitch EventSub.

These tests do not claim live delivery or database durability. The separate
test_twitch_postgres suite exercises real row locks, unique receipts and RLS.
"""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import hmac
import json
import unittest
from unittest.mock import MagicMock, Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.twitch_eventsub import (
    SubscriptionTrust, TwitchWebhookError, TwitchWebhookVerifier,
)
from postriff_phase2.twitch_service import TwitchService


NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc).timestamp()
SECRET = "synthetic-webhook-secret-20261018"
GENERATION = "a" * 32
WS = "00000000-0000-0000-0000-000000000001"
CONNECTION = "twitch-synthetic-owned"
CALLBACK = "00000000-0000-0000-0000-000000000099"
TRUST = SubscriptionTrust(
    "subscription-synthetic", "channel.chat.message", "1",
    {"broadcaster_user_id": "123", "user_id": "123"},
    WS, CONNECTION, GENERATION, SECRET,
)


def event_payload(*, kind="notification", trust=TRUST, **extra):
    status = {
        "notification": "enabled",
        "webhook_callback_verification": "webhook_callback_verification_pending",
        "revocation": "authorization_revoked",
    }.get(kind, "enabled")
    payload = {
        "subscription": {"id": trust.subscription_id, "type": trust.subscription_type,
                         "version": trust.subscription_version,
                         "condition": dict(trust.condition), "status": status},
    }
    if kind == "notification":
        payload["event"] = {"broadcaster_user_id": "123", "message": {"text": "合成聊天，非真實用戶"}}
    if kind == "webhook_callback_verification":
        payload["challenge"] = "synthetic-challenge"
    payload.update(extra)
    return payload


def signed_bytes(raw, *, at=NOW, stamp=None, message_id="message-synthetic",
                 kind="notification", secret=SECRET, trust=TRUST):
    if stamp is None:
        stamp = datetime.fromtimestamp(at, timezone.utc).isoformat().replace("+00:00", "Z")
    signature = "sha256=" + hmac.new(secret.encode("ascii"),
        message_id.encode() + stamp.encode() + raw, hashlib.sha256).hexdigest()
    return {
        "Twitch-Eventsub-Message-Id": message_id,
        "Twitch-Eventsub-Message-Timestamp": stamp,
        "Twitch-Eventsub-Message-Signature": signature,
        "Twitch-Eventsub-Message-Type": kind,
        "Twitch-Eventsub-Subscription-Type": trust.subscription_type,
        "Twitch-Eventsub-Subscription-Version": trust.subscription_version,
    }


def signed_payload(payload=None, **kwargs):
    if payload is None:
        payload = event_payload(kind=kwargs.get("kind", "notification"))
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return signed_bytes(raw, **kwargs), raw


class EventSubVerifierTest(unittest.TestCase):
    def setUp(self):
        self.verifier = TwitchWebhookVerifier(clock=lambda: NOW)

    def reject(self, code, headers, raw, trust=TRUST):
        with self.assertRaises(TwitchWebhookError) as caught:
            self.verifier.verify(headers, raw, trust)
        self.assertEqual(str(caught.exception), code)

    def test_notification_authenticates_exact_unicode_bytes_and_trusted_identity(self):
        headers, raw = signed_payload()
        message = self.verifier.verify(headers, raw, TRUST)
        self.assertEqual(message.event, event_payload()["event"])
        self.assertEqual((message.workspace_id, message.connection_id, message.credential_generation),
                         (WS, CONNECTION, GENERATION))
        self.assertEqual(message.sent_at, datetime.fromtimestamp(NOW, timezone.utc))
        self.assertIsNone(message.challenge)
        self.assertIsNone(message.revocation_reason)

    def test_whitespace_reserialization_and_byte_changes_break_signature(self):
        headers, raw = signed_payload()
        for altered in (raw + b" ", raw.replace(b"123", b"456", 1),
                        json.dumps(json.loads(raw), separators=(",", ":")).encode()):
            with self.subTest(altered_length=len(altered)):
                self.reject("signature_mismatch", headers, altered)

    def test_timestamp_and_message_id_are_both_authenticated(self):
        headers, raw = signed_payload()
        for name, value in (("Twitch-Eventsub-Message-Id", "another-message"),
                            ("Twitch-Eventsub-Message-Timestamp", "2026-10-18T11:59:59Z")):
            with self.subTest(header=name):
                self.reject("signature_mismatch", {**headers, name: value}, raw)

    def test_wrong_secret_fails_before_json_interpretation(self):
        raw = b"not JSON and must never be parsed"
        headers = signed_bytes(raw, secret="another-synthetic-secret")
        self.reject("signature_mismatch", headers, raw)

    def test_signature_requires_exact_algorithm_and_hex_format(self):
        headers, raw = signed_payload()
        signature = headers["Twitch-Eventsub-Message-Signature"]
        for bad in (signature.upper(), signature.replace("sha256", "sha1"), signature + "0",
                    signature + "," + signature, "sha256=" + "z" * 64):
            with self.subTest(signature=bad[:15]):
                self.reject("invalid_signature", {**headers, "Twitch-Eventsub-Message-Signature": bad}, raw)

    def test_ten_minute_old_boundary_is_inclusive(self):
        headers, raw = signed_payload(at=NOW - 600)
        self.assertEqual(self.verifier.verify(headers, raw, TRUST).sent_at.timestamp(), NOW - 600)
        headers, raw = signed_payload(at=NOW - 600.001)
        self.reject("stale_or_future_message", headers, raw)

    def test_sixty_second_future_boundary_is_inclusive(self):
        headers, raw = signed_payload(at=NOW + 60)
        self.assertEqual(self.verifier.verify(headers, raw, TRUST).sent_at.timestamp(), NOW + 60)
        headers, raw = signed_payload(at=NOW + 60.001)
        self.reject("stale_or_future_message", headers, raw)

    def test_timestamp_accepts_rfc3339_fraction_and_offset_without_losing_authority(self):
        for stamp in ("2026-10-18T12:00:00.123456789Z", "2026-10-18T20:00:00+08:00"):
            with self.subTest(stamp=stamp):
                headers, raw = signed_payload(stamp=stamp)
                self.assertEqual(self.verifier.verify(headers, raw, TRUST).sent_at.tzinfo, timezone.utc)

    def test_signed_but_invalid_or_naive_timestamps_fail_closed(self):
        for stamp in ("2026-10-18T12:00:00", "2026-10-18 12:00:00Z", "2026-13-18T12:00:00Z",
                      "2026-10-18T12:00:00.1234567890Z", "2026-10-18T12:00:00+99:99"):
            with self.subTest(stamp=stamp):
                headers, raw = signed_payload(stamp=stamp)
                self.reject("invalid_timestamp", headers, raw)

    def test_nonfinite_clock_cannot_disable_replay_window(self):
        headers, raw = signed_payload()
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(clock=value), self.assertRaises(TwitchWebhookError):
                TwitchWebhookVerifier(clock=lambda: value).verify(headers, raw, TRUST)

    def test_required_headers_are_case_insensitive(self):
        headers, raw = signed_payload()
        self.assertEqual(self.verifier.verify({k.upper(): v for k, v in headers.items()}, raw, TRUST).kind,
                         "notification")

    def test_duplicate_headers_are_rejected_even_if_values_agree(self):
        headers, raw = signed_payload()
        for key, value in headers.items():
            with self.subTest(header=key):
                self.reject("duplicate_header", [*headers.items(), (key.lower(), value)], raw)

    def test_missing_headers_and_invalid_header_syntax_fail(self):
        headers, raw = signed_payload()
        for key in headers:
            with self.subTest(missing=key):
                self.reject("missing_header", {k: v for k, v in headers.items() if k != key}, raw)
        for addition in (("X_Bad", "bad"), ("X-Extra", "value\r\ninjected"), ("X-Extra", "\x7f")):
            with self.subTest(extra=addition):
                self.reject("invalid_header_value", [*headers.items(), addition], raw)
        self.reject("invalid_header_pair", [*headers.items(), ("only-key",)], raw)

    def test_header_count_and_value_size_are_bounded(self):
        headers, raw = signed_payload()
        self.reject("headers_over_limit", [*headers.items(), *[("X-" + str(i), "v") for i in range(75)]], raw)
        self.reject("invalid_header_value", [*headers.items(), ("X-Extra", "x" * 4097)], raw)

    def test_body_is_bytes_and_bounded_before_signature_work(self):
        headers, raw = signed_payload()
        self.reject("body_over_limit", headers, raw.decode())
        self.reject("body_over_limit", headers, b" " * 262145)
        limit = TwitchWebhookVerifier(clock=lambda: NOW, max_bytes=len(raw))
        self.assertEqual(limit.verify(headers, raw, TRUST).kind, "notification")

    def test_authenticated_duplicate_json_keys_at_any_depth_fail(self):
        valid = json.dumps(event_payload(), separators=(",", ":"))
        for text in (valid[:-1] + ',"event":{}}',
                     valid.replace('"broadcaster_user_id":"123"', '"broadcaster_user_id":"123","broadcaster_user_id":"456"', 1)):
            with self.subTest(nested="456" in text):
                raw = text.encode()
                self.reject("duplicate_json_key", signed_bytes(raw), raw)

    def test_authenticated_non_json_nonfinite_and_invalid_utf8_fail(self):
        for raw, code in ((b"{", "invalid_json"), (b"\xff", "invalid_json"),
                          (b'{"x":NaN}', "invalid_number"), (b'{"x":Infinity}', "invalid_number"),
                          (b"[]", "missing_subscription"), (b"null", "missing_subscription")):
            with self.subTest(raw=raw):
                self.reject(code, signed_bytes(raw), raw)

    def test_exact_subscription_id_type_version_and_condition_must_match(self):
        for field, value in (("id", "other-subscription"), ("type", "stream.online"), ("version", "2"),
                             ("condition", {"broadcaster_user_id": "456", "user_id": "123"}),
                             ("condition", {**TRUST.condition, "workspace_id": "another-workspace"})):
            with self.subTest(field=field, value=value):
                payload = event_payload()
                payload["subscription"][field] = value
                headers, raw = signed_payload(payload)
                self.reject("subscription_mismatch", headers, raw)

    def test_unsigned_type_headers_cannot_override_signed_subscription(self):
        headers, raw = signed_payload()
        for key, value in (("Twitch-Eventsub-Subscription-Type", "stream.online"),
                            ("Twitch-Eventsub-Subscription-Version", "2")):
            with self.subTest(header=key):
                self.reject("subscription_mismatch", {**headers, key: value}, raw)

    def test_payload_workspace_and_generation_are_never_used_as_trust(self):
        payload = event_payload(workspace_id="attacker-workspace", connection_id="attacker-connection",
                                credential_generation="b" * 32)
        payload["event"].update(workspace_id="attacker-workspace", generation="b" * 32)
        headers, raw = signed_payload(payload)
        verified = self.verifier.verify(headers, raw, TRUST)
        self.assertEqual((verified.workspace_id, verified.connection_id, verified.credential_generation),
                         (WS, CONNECTION, GENERATION))

    def test_trusted_generation_and_secret_require_valid_server_evidence(self):
        headers, raw = signed_payload()
        for generation in (None, "", "short", "../" + "a" * 32, "é" * 32, "a" * 129):
            with self.subTest(generation=generation):
                self.reject("invalid_generation", headers, raw, replace(TRUST, credential_generation=generation))
        for secret in (None, "short", "x" * 101, "é" * 32, "contains spaces", "new\nline" * 3):
            with self.subTest(secret=secret):
                self.reject("invalid_webhook_secret", headers, raw, replace(TRUST, secret=secret))
        self.reject("trusted_subscription_required", headers, raw, None)
        self.reject("trusted_subscription_required", headers, raw, replace(TRUST, workspace_id=""))

    def test_notification_requires_enabled_subscription_and_event_object(self):
        for status, event in (("authorization_revoked", {}), ("webhook_callback_verification_pending", {}),
                              ("enabled", None), ("enabled", []), ("enabled", "viewer content")):
            with self.subTest(status=status, event=event):
                payload = event_payload(event=event)
                payload["subscription"]["status"] = status
                headers, raw = signed_payload(payload)
                self.reject("invalid_notification", headers, raw)

    def test_challenge_returns_exact_utf8_bytes_and_no_event(self):
        payload = event_payload(kind="webhook_callback_verification", challenge="signed-challenge-驗證")
        headers, raw = signed_payload(payload, kind="webhook_callback_verification")
        verified = self.verifier.verify(headers, raw, TRUST)
        self.assertEqual(verified.challenge, "signed-challenge-驗證".encode())
        self.assertIsNone(verified.event)

    def test_challenge_requires_pending_status_and_safe_nonempty_value(self):
        payload = event_payload(kind="webhook_callback_verification")
        payload["subscription"]["status"] = "enabled"
        headers, raw = signed_payload(payload, kind="webhook_callback_verification")
        self.reject("invalid_challenge_status", headers, raw)
        for challenge in ("", None, "x" * 513, "line\nbreak", "\x00"):
            with self.subTest(challenge=challenge):
                payload = event_payload(kind="webhook_callback_verification", challenge=challenge)
                headers, raw = signed_payload(payload, kind="webhook_callback_verification")
                self.reject("invalid_challenge", headers, raw)

    def test_pending_subscription_can_bind_only_a_valid_signed_challenge(self):
        pending = replace(TRUST, subscription_id="", allow_pending_binding=True)
        headers, raw = signed_payload(kind="webhook_callback_verification")
        verified = self.verifier.verify(headers, raw, pending)
        self.assertEqual(verified.subscription_id, TRUST.subscription_id)
        self.assertEqual(verified.credential_generation, GENERATION)
        for kind in ("notification", "revocation"):
            with self.subTest(kind=kind):
                headers, raw = signed_payload(kind=kind)
                self.reject("subscription_mismatch", headers, raw, pending)

    def test_pending_permission_cannot_rebind_existing_id_or_relax_condition(self):
        existing = replace(TRUST, subscription_id="already-bound", allow_pending_binding=True)
        headers, raw = signed_payload(kind="webhook_callback_verification")
        self.reject("subscription_mismatch", headers, raw, existing)
        pending = replace(TRUST, subscription_id="", allow_pending_binding=True)
        payload = event_payload(kind="webhook_callback_verification")
        payload["subscription"]["condition"]["broadcaster_user_id"] = "456"
        headers, raw = signed_payload(payload, kind="webhook_callback_verification")
        self.reject("subscription_mismatch", headers, raw, pending)

    def test_pending_callback_rejects_malformed_provider_ids(self):
        pending = replace(TRUST, subscription_id="", allow_pending_binding=True)
        for identifier in ("../other", "too long" * 30, None, 123):
            with self.subTest(identifier=identifier):
                payload = event_payload(kind="webhook_callback_verification")
                payload["subscription"]["id"] = identifier
                headers, raw = signed_payload(payload, kind="webhook_callback_verification")
                self.reject("subscription_mismatch", headers, raw, pending)

    def test_pending_callback_never_accepts_an_empty_provider_id(self):
        pending = replace(TRUST, subscription_id="", allow_pending_binding=True)
        for kind in ("notification", "webhook_callback_verification", "revocation"):
            with self.subTest(kind=kind):
                payload = event_payload(kind=kind)
                payload["subscription"]["id"] = ""
                headers, raw = signed_payload(payload, kind=kind)
                self.reject("subscription_mismatch", headers, raw, pending)

    def test_signed_revocation_carries_reason_without_accepting_event_content(self):
        headers, raw = signed_payload(kind="revocation")
        verified = self.verifier.verify(headers, raw, TRUST)
        self.assertEqual(verified.revocation_reason, "authorization_revoked")
        self.assertIsNone(verified.event)
        self.assertIsNone(verified.challenge)

    def test_message_type_tampering_cannot_turn_valid_notification_into_revocation(self):
        # Message-Type is not part of Twitch's HMAC input. Its semantics must agree
        # with the authenticated subscription status inside the original bytes.
        headers, raw = signed_payload()
        self.reject("invalid_revocation", {**headers, "Twitch-Eventsub-Message-Type": "revocation"}, raw)

    def test_revocation_accepts_only_documented_disabled_statuses(self):
        for reason in ("authorization_revoked", "user_removed", "notification_failures_exceeded",
                       "version_removed", "moderator_removed"):
            with self.subTest(reason=reason):
                payload = event_payload(kind="revocation")
                payload["subscription"]["status"] = reason
                headers, raw = signed_payload(payload, kind="revocation")
                self.assertEqual(self.verifier.verify(headers, raw, TRUST).revocation_reason, reason)
        for reason in ("enabled", "webhook_callback_verification_pending", "", "invented-state", None):
            with self.subTest(reason=reason):
                payload = event_payload(kind="revocation")
                payload["subscription"]["status"] = reason
                headers, raw = signed_payload(payload, kind="revocation")
                self.reject("invalid_revocation", headers, raw)

    def test_unknown_message_type_is_not_acknowledged_as_notification(self):
        headers, raw = signed_payload(kind="future-unknown-type")
        self.reject("unknown_message_type", headers, raw)


class EventSubCustodyBoundaryTest(unittest.TestCase):
    """Real service rejection branches with a minimal read-only DB fixture.

    This fixture proves the order and authority of the checks. It does not simulate
    commit/rollback or stand in for the PostgreSQL acceptance suite.
    """
    def setUp(self):
        self.service = object.__new__(TwitchService)
        self.cursor = MagicMock()
        self.cursor.fetchone.return_value = (WS, CONNECTION)
        database = MagicMock()
        database.__enter__.return_value = database
        database.cursor.return_value.__enter__.return_value = self.cursor
        self.service.factory = Mock(return_value=database)
        self.record = {"state": "enabled", "ciphertext": "encrypted-secret", "keyId": "synthetic-key",
                       "providerId": TRUST.subscription_id, "type": TRUST.subscription_type,
                       "version": TRUST.subscription_version, "condition": dict(TRUST.condition),
                       "generation": GENERATION}
        self.service._subscription = Mock(return_value=self.record)
        self.service._credential = Mock(return_value={"generation": GENERATION})
        self.service.vault = Mock()
        self.service.vault.decrypt.return_value = SECRET
        self.service.verifier = Mock(wraps=TwitchWebhookVerifier(clock=lambda: NOW))
        self.service.content_storage_approved = True

    def test_unknown_callback_cannot_select_trust_from_payload(self):
        self.cursor.fetchone.return_value = None
        headers, raw = signed_payload(event_payload(workspace_id="untrusted-workspace"))
        with self.assertRaises(AlphaError) as caught:
            self.service.webhook(CALLBACK, headers, raw)
        self.assertEqual(caught.exception.code, "twitch_webhook_unavailable")
        self.service._subscription.assert_not_called()
        self.service.verifier.verify.assert_not_called()

    def test_current_credential_generation_is_checked_before_signature_or_content(self):
        self.service._credential.return_value = {"generation": "b" * 32}
        headers, raw = signed_payload()
        with self.assertRaises(AlphaError) as caught:
            self.service.webhook(CALLBACK, headers, raw)
        self.assertEqual(caught.exception.code, "twitch_webhook_generation_revoked")
        self.service.verifier.verify.assert_not_called()
        self.service.vault.decrypt.assert_not_called()
        self.assertEqual(self.cursor.execute.call_count, 1)

    def test_revoked_or_cleaned_subscription_is_closed_before_decryption(self):
        for state, ciphertext in (("revoked", "encrypted"), ("cleanup_pending", "encrypted"), ("enabled", "")):
            with self.subTest(state=state, ciphertext=bool(ciphertext)):
                self.record.update(state=state, ciphertext=ciphertext)
                headers, raw = signed_payload()
                with self.assertRaises(AlphaError) as caught:
                    self.service.webhook(CALLBACK, headers, raw)
                self.assertEqual(caught.exception.code, "twitch_webhook_inactive")
                self.service.verifier.verify.assert_not_called()
                self.service.vault.decrypt.assert_not_called()

    def test_wrong_signed_condition_is_safe_403_before_receipt_write(self):
        payload = event_payload()
        payload["subscription"]["condition"]["broadcaster_user_id"] = "456"
        headers, raw = signed_payload(payload)
        with self.assertRaises(AlphaError) as caught:
            self.service.webhook(CALLBACK, headers, raw)
        self.assertEqual(caught.exception.code, "twitch_webhook_authentication_failed")
        self.assertEqual(caught.exception.status, 403)
        self.assertNotIn("456", str(caught.exception))
        self.assertEqual(self.cursor.execute.call_count, 1)
        self.service.vault.encrypt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
