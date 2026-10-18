"""Offline wire contracts and adversarial authorization tests; no live credentials.

The request vectors below are independent samples from the official Helix
contracts. Every registered operation must have a sample, including read-only
operations. Provider errors deliberately contain synthetic credential canaries.
"""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import traceback
import unittest
from urllib.parse import parse_qs, urlsplit

from postriff_phase2.twitch_native import (
    CAPABILITIES, EVIDENCE_TTL, HELIX, OPERATIONS, UNSUPPORTED,
    PreparedOperation, RightsEvidence, RoleEvidence, TwitchNativeError,
    capabilities, execute, execute_sensitive, operation_scopes, prepare_operation,
    union_supported_scopes, verify_resource_access, verify_roles,
)


NOW = 1792324800.0
CLIENT = "rafii_synthetic_client"
TOKEN = "synthetic_token_NEVER_REAL_abc987654"
BR = "123"
TARGET = "456"
MOD = "789"
ALL_SCOPES = union_supported_scopes()


class Transport:
    def __init__(self, body=None, status=200, *, responses=None, error=None):
        self.calls = []
        self.response = {"status": status, "headers": {}, "body": {"data": []} if body is None else body}
        self.responses = list(responses or [])
        self.error = error

    def __call__(self, method, url, *, headers=None, body=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if self.error:
            raise self.error
        return self.responses.pop(0) if self.responses else self.response


def rights(kind, ids=(), *, now=NOW, subject_id=BR, broadcaster_id=BR, client_id=CLIENT, **kwargs):
    values = dict(subject_id=subject_id, broadcaster_id=broadcaster_id,
                  resource_kind=kind, resource_ids=tuple(ids), client_id=client_id,
                  checked_at=now, expires_at=now + 300, ownership_verified=True)
    values.update(kwargs)
    return RightsEvidence(**values)


def prepare(action, payload=None, **context):
    ctx = dict(subject_id=BR, broadcaster_id=BR, scopes=ALL_SCOPES,
               account_type="partner", live=True, now=NOW)
    ctx.update(context)
    return prepare_operation(action, payload or {}, **ctx)


QBR = {"broadcaster_id": BR}
QMOD = {"broadcaster_id": BR, "moderator_id": BR}
QUSER = {"user_id": BR}
QEDITOR = {"broadcaster_id": BR, "editor_id": BR}
START = "2026-10-20T20:00:00Z"
END = "2026-10-21T20:00:00Z"
SEGMENT = "ZXlKelpXZHRaVzUwSWtRaU9pSXg="

# (method, path, input payload, expected query, expected JSON body)
WIRE = {
    "channel.get": ("GET", "/channels", {}, QBR, None),
    "channel.update": ("PATCH", "/channels", {"title": "Concert", "tags": ["Piano"]}, QBR, {"title": "Concert", "tags": ["Piano"]}),
    "channel.editors.get": ("GET", "/channels/editors", {}, QBR, None),
    "channel.followers.get": ("GET", "/channels/followers", {"user_id": TARGET}, {**QBR, "user_id": TARGET}, None),
    "channel.followers.total": ("GET", "/channels/followers", {}, QBR, None),
    "stream.get": ("GET", "/streams", {}, QUSER, None),
    "stream.key.get": ("GET", "/streams/key", {}, QBR, None),
    "category.search": ("GET", "/search/categories", {"query": "Music"}, {"query": "Music"}, None),
    "channel.labels.get": ("GET", "/content_classification_labels", {}, {}, None),
    "channel.search": ("GET", "/search/channels", {"query": "piano", "live_only": True}, {"query": "piano", "live_only": True}, None),
    "channel.followed.get": ("GET", "/channels/followed", {}, QUSER, None),
    "stream.followed.get": ("GET", "/streams/followed", {}, QUSER, None),
    "profile.get": ("GET", "/users", {}, {}, None),
    "profile.update": ("PUT", "/users", {"description": "Pianist"}, {"description": "Pianist"}, None),
    "schedule.get": ("GET", "/schedule", {"id": [SEGMENT]}, {**QBR, "id": [SEGMENT]}, None),
    "schedule.calendar.get": ("GET", "/schedule/icalendar", {}, QBR, None),
    "schedule.settings.update": ("PATCH", "/schedule/settings", {"is_vacation_enabled": True, "vacation_start_time": START, "vacation_end_time": END, "timezone": "Asia/Hong_Kong"},
        {**QBR, "is_vacation_enabled": True, "vacation_start_time": START, "vacation_end_time": END, "timezone": "Asia/Hong_Kong"}, None),
    "schedule.create": ("POST", "/schedule/segment", {"start_time": START, "timezone": "Asia/Hong_Kong", "duration": 60, "is_recurring": True}, QBR,
        {"start_time": START, "timezone": "Asia/Hong_Kong", "duration": "60", "is_recurring": True}),
    "schedule.update": ("PATCH", "/schedule/segment", {"id": SEGMENT, "duration": 90}, {**QBR, "id": SEGMENT}, {"duration": "90"}),
    "schedule.delete": ("DELETE", "/schedule/segment", {"id": SEGMENT}, {**QBR, "id": SEGMENT}, None),
    "marker.create": ("POST", "/streams/markers", {"description": "Cadenza"}, {}, {"user_id": BR, "description": "Cadenza"}),
    "marker.get": ("GET", "/streams/markers", {"video_id": "100"}, {"video_id": "100"}, None),
    "chat.send": ("POST", "/chat/messages", {"message": "Welcome"}, {}, {"broadcaster_id": BR, "sender_id": BR, "message": "Welcome"}),
    "chat.reply": ("POST", "/chat/messages", {"message": "Thank you", "reply_parent_message_id": "parent-1"}, {},
        {"broadcaster_id": BR, "sender_id": BR, "message": "Thank you", "reply_parent_message_id": "parent-1"}),
    "chat.chatters.get": ("GET", "/chat/chatters", {"first": 50}, {**QMOD, "first": 50}, None),
    "chat.settings.get": ("GET", "/chat/settings", {}, QBR, None),
    "chat.settings.private.get": ("GET", "/chat/settings", {}, QMOD, None),
    "chat.settings.update": ("PATCH", "/chat/settings", {"slow_mode": True, "slow_mode_wait_time": 5}, QMOD, {"slow_mode": True, "slow_mode_wait_time": 5}),
    "chat.announcement.send": ("POST", "/chat/announcements", {"message": "Concert begins", "color": "purple"}, QMOD, {"message": "Concert begins", "color": "purple"}),
    "chat.shoutout.send": ("POST", "/chat/shoutouts", {"to_broadcaster_id": TARGET}, {"from_broadcaster_id": BR, "moderator_id": BR, "to_broadcaster_id": TARGET}, None),
    "chat.shared.get": ("GET", "/shared_chat/session", {}, QBR, None),
    "chat.pin.get": ("GET", "/chat/pins", {}, QMOD, None),
    "chat.pin.create": ("PUT", "/chat/pins", {"message_id": "message-1", "duration_seconds": 60}, {**QMOD, "message_id": "message-1", "duration_seconds": 60}, None),
    "chat.pin.update": ("PATCH", "/chat/pins", {"message_id": "message-1"}, {**QMOD, "message_id": "message-1"}, None),
    "chat.pin.delete": ("DELETE", "/chat/pins", {"message_id": "message-1"}, {**QMOD, "message_id": "message-1"}, None),
    "chat.message.delete": ("DELETE", "/moderation/chat", {"message_id": "message-1"}, {**QMOD, "message_id": "message-1"}, None),
    "chat.clear": ("DELETE", "/moderation/chat", {}, QMOD, None),
    "chat.emotes.get": ("GET", "/chat/emotes", {}, QBR, None),
    "chat.badges.get": ("GET", "/chat/badges", {}, QBR, None),
    "chat.emotes.global.get": ("GET", "/chat/emotes/global", {}, {}, None),
    "chat.emotes.set.get": ("GET", "/chat/emotes/set", {"emote_set_id": ["set-1"]}, {"emote_set_id": ["set-1"]}, None),
    "chat.emotes.user.get": ("GET", "/chat/emotes/user", {}, {"broadcaster_id": BR, "user_id": BR}, None),
    "chat.badges.global.get": ("GET", "/chat/badges/global", {}, {}, None),
    "chat.color.get": ("GET", "/chat/color", {}, QUSER, None),
    "chat.color.update": ("PUT", "/chat/color", {"color": "blue_violet"}, {**QUSER, "color": "blue_violet"}, None),
    "chat.whisper.send": ("POST", "/whispers", {"to_user_id": TARGET, "message": "Hello"}, {"from_user_id": BR, "to_user_id": TARGET}, {"message": "Hello"}),
    "moderation.ban": ("POST", "/moderation/bans", {"user_id": TARGET, "reason": "Spam"}, QMOD, {"data": {"user_id": TARGET, "reason": "Spam"}}),
    "moderation.timeout": ("POST", "/moderation/bans", {"user_id": TARGET, "duration": 600}, QMOD, {"data": {"user_id": TARGET, "duration": 600}}),
    "moderation.unban": ("DELETE", "/moderation/bans", {"user_id": TARGET}, {**QMOD, "user_id": TARGET}, None),
    "moderation.banned.get": ("GET", "/moderation/banned", {"user_id": [TARGET]}, {**QBR, "user_id": [TARGET]}, None),
    "moderation.warn": ("POST", "/moderation/warnings", {"user_id": TARGET, "reason": "Respect chat rules"}, QMOD, {"data": {"user_id": TARGET, "reason": "Respect chat rules"}}),
    "moderation.channels.get": ("GET", "/moderation/channels", {}, QUSER, None),
    "moderation.moderators.get": ("GET", "/moderation/moderators", {}, QBR, None),
    "moderation.moderator.add": ("POST", "/moderation/moderators", {"user_id": TARGET}, {**QBR, "user_id": TARGET}, None),
    "moderation.moderator.remove": ("DELETE", "/moderation/moderators", {"user_id": TARGET}, {**QBR, "user_id": TARGET}, None),
    "moderation.vip.add": ("POST", "/channels/vips", {"user_id": TARGET}, {**QBR, "user_id": TARGET}, None),
    "moderation.vip.remove": ("DELETE", "/channels/vips", {"user_id": TARGET}, {**QBR, "user_id": TARGET}, None),
    "moderation.vips.get": ("GET", "/channels/vips", {}, QBR, None),
    "moderation.blocked_terms.get": ("GET", "/moderation/blocked_terms", {}, QMOD, None),
    "moderation.blocked_terms.add": ("POST", "/moderation/blocked_terms", {"text": "malicious phrase"}, QMOD, {"text": "malicious phrase"}),
    "moderation.blocked_terms.remove": ("DELETE", "/moderation/blocked_terms", {"id": "term-1"}, {**QMOD, "id": "term-1"}, None),
    "moderation.unban_requests.get": ("GET", "/moderation/unban_requests", {"status": "pending"}, {**QMOD, "status": "pending"}, None),
    "moderation.unban_requests.resolve": ("PATCH", "/moderation/unban_requests", {"unban_request_id": "request-1", "status": "denied", "resolution_text": "Repeated spam"},
        {**QMOD, "unban_request_id": "request-1", "status": "denied", "resolution_text": "Repeated spam"}, None),
    "automod.settings.get": ("GET", "/moderation/automod/settings", {}, QMOD, None),
    "automod.settings.update": ("PUT", "/moderation/automod/settings", {"overall_level": 3}, QMOD, {"overall_level": 3}),
    "automod.check": ("POST", "/moderation/enforcements/status", {"data": [{"msg_id": "m1", "msg_text": "Synthetic sample"}]}, QBR, {"data": [{"msg_id": "m1", "msg_text": "Synthetic sample"}]}),
    "automod.message.resolve": ("POST", "/moderation/automod/message", {"msg_id": "m1", "action": "DENY"}, {}, {"user_id": BR, "msg_id": "m1", "action": "DENY"}),
    "shield.get": ("GET", "/moderation/shield_mode", {}, QMOD, None),
    "shield.update": ("PUT", "/moderation/shield_mode", {"is_active": True}, QMOD, {"is_active": True}),
    "moderation.suspicious.add": ("POST", "/moderation/suspicious_users", {"user_id": TARGET, "status": "RESTRICTED"}, QMOD, {"user_id": TARGET, "status": "RESTRICTED"}),
    "moderation.suspicious.remove": ("DELETE", "/moderation/suspicious_users", {"user_id": TARGET}, {**QMOD, "user_id": TARGET}, None),
    "moderation.user_blocks.get": ("GET", "/users/blocks", {}, QBR, None),
    "moderation.user_block.add": ("PUT", "/users/blocks", {"target_user_id": TARGET, "source_context": "chat", "reason": "spam"}, {"target_user_id": TARGET, "source_context": "chat", "reason": "spam"}, None),
    "moderation.user_block.remove": ("DELETE", "/users/blocks", {"target_user_id": TARGET}, {"target_user_id": TARGET}, None),
    "clip.get": ("GET", "/clips", {"is_featured": True}, {**QBR, "is_featured": True}, None),
    "clip.lookup": ("GET", "/clips", {"id": ["ClipOne"]}, {"id": ["ClipOne"]}, None),
    "clip.create": ("POST", "/clips", {"title": "Cadenza", "duration": 12.5}, {**QBR, "title": "Cadenza", "duration": 12.5}, None),
    "clip.vod.create": ("POST", "/videos/clips", {"vod_id": "100", "vod_offset": 120, "duration": 30, "title": "Cadenza"},
        {**QEDITOR, "vod_id": "100", "vod_offset": 120, "duration": 30, "title": "Cadenza"}, None),
    "clip.download": ("GET", "/clips/downloads", {"clip_id": ["ClipOne"]}, {**QEDITOR, "clip_id": ["ClipOne"]}, None),
    "video.get": ("GET", "/videos", {"type": "archive", "sort": "time"}, {**QUSER, "type": "archive", "sort": "time"}, None),
    "video.delete": ("DELETE", "/videos", {"id": ["100", "101"]}, {"id": ["100", "101"]}, None),
    "poll.get": ("GET", "/polls", {}, QBR, None),
    "prediction.get": ("GET", "/predictions", {}, QBR, None),
    "poll.create": ("POST", "/polls", {"title": "Encore?", "choices": [{"title": "Chopin"}, {"title": "Liszt"}], "duration": 60}, {},
        {"broadcaster_id": BR, "title": "Encore?", "choices": [{"title": "Chopin"}, {"title": "Liszt"}], "duration": 60}),
    "poll.end": ("PATCH", "/polls", {"id": "poll-1", "status": "TERMINATED"}, {}, {"broadcaster_id": BR, "id": "poll-1", "status": "TERMINATED"}),
    "prediction.create": ("POST", "/predictions", {"title": "Who wins?", "outcomes": [{"title": "A"}, {"title": "B"}], "prediction_window": 60}, {},
        {"broadcaster_id": BR, "title": "Who wins?", "outcomes": [{"title": "A"}, {"title": "B"}], "prediction_window": 60}),
    "prediction.end": ("PATCH", "/predictions", {"id": "prediction-1", "status": "RESOLVED", "winning_outcome_id": "outcome-1"}, {},
        {"broadcaster_id": BR, "id": "prediction-1", "status": "RESOLVED", "winning_outcome_id": "outcome-1"}),
    "raid.start": ("POST", "/raids", {"to_broadcaster_id": TARGET}, {"from_broadcaster_id": BR, "to_broadcaster_id": TARGET}, None),
    "raid.cancel": ("DELETE", "/raids", {}, QBR, None),
    "reward.get": ("GET", "/channel_points/custom_rewards", {"only_manageable_rewards": True}, {**QBR, "only_manageable_rewards": True}, None),
    "reward.create": ("POST", "/channel_points/custom_rewards", {"title": "Choose encore", "cost": 500}, QBR, {"title": "Choose encore", "cost": 500}),
    "reward.update": ("PATCH", "/channel_points/custom_rewards", {"id": "reward-1", "cost": 750}, {**QBR, "id": "reward-1"}, {"cost": 750}),
    "reward.delete": ("DELETE", "/channel_points/custom_rewards", {"id": "reward-1"}, {**QBR, "id": "reward-1"}, None),
    "redemption.get": ("GET", "/channel_points/custom_rewards/redemptions", {"reward_id": "reward-1", "status": "UNFULFILLED"}, {**QBR, "reward_id": "reward-1", "status": "UNFULFILLED"}, None),
    "redemption.update": ("PATCH", "/channel_points/custom_rewards/redemptions", {"reward_id": "reward-1", "id": ["redemption-1"], "status": "CANCELED"},
        {**QBR, "reward_id": "reward-1", "id": ["redemption-1"]}, {"status": "CANCELED"}),
    "subscription.get": ("GET", "/subscriptions", {"user_id": [TARGET]}, {**QBR, "user_id": [TARGET]}, None),
    "subscription.check": ("GET", "/subscriptions/user", {}, {"broadcaster_id": BR, "user_id": BR}, None),
    "bits.leaderboard.get": ("GET", "/bits/leaderboard", {"count": 10, "period": "day", "started_at": START}, {"count": 10, "period": "day", "started_at": START}, None),
    "bits.cheermotes.get": ("GET", "/bits/cheermotes", {}, QBR, None),
    "bits.powerups.get": ("GET", "/bits/custom_power_ups", {"id": ["power-1"]}, {**QBR, "id": ["power-1"]}, None),
    "hype_train.get": ("GET", "/hypetrain/status", {}, QBR, None),
    "ads.schedule.get": ("GET", "/channels/ads", {}, QBR, None),
    "ads.snooze": ("POST", "/channels/ads/schedule/snooze", {}, QBR, None),
    "ads.commercial.start": ("POST", "/channels/commercial", {"length": 90}, {}, {"broadcaster_id": BR, "length": 90}),
    "goals.get": ("GET", "/goals", {}, QBR, None),
    "charity.get": ("GET", "/charity/campaigns", {}, QBR, None),
    "charity.donations.get": ("GET", "/charity/donations", {"first": 20}, {**QBR, "first": 20}, None),
    "analytics.stream.snapshot": ("GET", "/streams", {}, QUSER, None),
    "analytics.clips.snapshot": ("GET", "/clips", {"first": 10}, {**QBR, "first": 10}, None),
    "analytics.videos.snapshot": ("GET", "/videos", {}, QUSER, None),
    "analytics.extension.get": ("GET", "/analytics/extensions", {"extension_id": "ext-1"}, {"extension_id": "ext-1"}, None),
    "analytics.game.get": ("GET", "/analytics/games", {"game_id": "game-1"}, {"game_id": "game-1"}, None),
}


def _fixture_evidence(short):
    if short in ("schedule.update", "schedule.delete"):
        return rights("schedule", [SEGMENT], metadata_json=json.dumps({"resources": {SEGMENT: {"is_recurring": True}}}))
    if short == "marker.create":
        return rights("marker_settings", metadata_json='{"past_broadcasts_enabled":true,"broadcast_type":"live"}')
    if short == "clip.vod.create":
        return rights("video", ["100"])
    if short == "clip.download":
        return rights("clip", ["ClipOne"], reuse_authorized=True, storage_authorized=True)
    if short == "video.delete":
        return rights("video", ["100", "101"])
    if short in ("reward.update", "reward.delete", "redemption.get", "redemption.update"):
        return rights("reward", ["reward-1"], creator_app_verified=True)
    return None


class NativeWireContracts(unittest.TestCase):
    def test_every_registered_operation_has_independent_wire_vector(self):
        self.assertEqual(set(OPERATIONS), {"twitch." + key for key in WIRE})


def _contract_test(short, vector):
    def test(self):
        method, path, payload, query, body = vector
        command = prepare("twitch." + short, payload, rights=_fixture_evidence(short))
        self.assertEqual((command.method, command.path, command.query, command.body), (method, path, query, body))
        self.assertEqual(command.subject_id, BR)
        self.assertEqual(command.broadcaster_id, BR)
        self.assertEqual(command.payload, payload)
        self.assertEqual(len(command.payload_sha256), 64)
        self.assertNotIn(TOKEN, json.dumps(command.as_dict()))
    return test


for _short, _vector in WIRE.items():
    setattr(NativeWireContracts, "test_contract_" + _short.replace(".", "_"), _contract_test(_short, _vector))


class NativeSecurityTests(unittest.TestCase):
    def assertDenied(self, reason, function, *args, **kwargs):
        with self.assertRaises(TwitchNativeError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.reason, reason)
        return caught.exception

    def test_registry_and_projection_cannot_be_mutated(self):
        with self.assertRaises(TypeError):
            CAPABILITIES["evil"] = object()
        with self.assertRaises(FrozenInstanceError):
            OPERATIONS["twitch.chat.send"].path = "/evil"
        projection = capabilities(subject_id=BR, broadcaster_id=BR, scopes=ALL_SCOPES, account_type="partner", live=True, now=NOW)
        json.dumps(projection)
        projection[0]["fields"]["fake"] = {"type": "string"}
        self.assertNotIn("fake", capabilities()[0]["fields"])
        self.assertTrue(all(item["verification"] == "unverified" and not item["liveVerified"] for item in projection))

    def test_catalog_blocks_missing_connection_scope_and_live_state(self):
        disconnected = {item["action"]: item for item in capabilities(now=NOW)}
        self.assertEqual(disconnected["twitch.chat.send"]["availability"]["reasons"], ["connection_required"])
        connected = {item["action"]: item for item in capabilities(subject_id=BR, broadcaster_id=BR, scopes=[], now=NOW)}
        self.assertEqual(connected["twitch.chat.send"]["availability"]["reasons"], ["missing_scope"])
        self.assertEqual(connected["twitch.stream.get"]["availability"]["state"], "available")

    def test_scope_options_and_official_marker_scope(self):
        self.assertEqual(operation_scopes("twitch.marker.get"), [["user:read:broadcast"], ["channel:manage:broadcast"]])
        self.assertNotIn("channel:read:broadcast", union_supported_scopes())
        self.assertNotIn("openid", union_supported_scopes())
        self.assertDenied("missing_scope", prepare, "twitch.poll.create", WIRE["poll.create"][2], scopes={"channel:read:polls"})
        prepare("twitch.poll.get", scopes={"channel:read:polls"})
        prepare("twitch.poll.get", scopes={"channel:manage:polls"})

    def test_all_scoped_operations_reject_empty_grant(self):
        for action, op in OPERATIONS.items():
            if any(not option for option in op.scope_options):
                continue
            with self.subTest(action=action):
                self.assertDenied("missing_scope", prepare, action, WIRE[action[7:]][2], scopes=[])

    def test_request_cannot_override_any_principal_or_permission(self):
        for forbidden in ("broadcaster_id", "sender_id", "moderator_id", "workspace_id", "scopes", "roles", "rights", "client_id", "url", "headers", "is_approved", "authorization_generation"):
            with self.subTest(field=forbidden):
                self.assertDenied("unknown_payload_field", prepare, "twitch.chat.send", {"message": "hi", forbidden: TARGET})

    def test_unbounded_json_integers_produce_safe_validation_error(self):
        for value in (10 ** 1000, -(10 ** 1000)):
            with self.subTest(positive=value > 0):
                self.assertDenied("invalid_numeric_range", prepare, "twitch.moderation.timeout",
                                  {"user_id": TARGET, "duration": value})

    def test_unbounded_clock_cannot_escape_as_an_overflow_exception(self):
        self.assertDenied("invalid_clock", prepare, "twitch.channel.get", now=10 ** 1000)

    def test_broadcaster_only_actions_reject_other_user_even_with_all_scopes(self):
        for action in ("channel.update", "schedule.create", "poll.create", "prediction.end", "ads.commercial.start", "reward.create"):
            with self.subTest(action=action):
                self.assertDenied("broadcaster_token_required", prepare, "twitch." + action, WIRE[action][2], subject_id=MOD)

    def test_moderator_scope_or_asserted_role_is_not_role_evidence(self):
        for roles_value in ((), {"moderator"}, {"moderator": True}, {"roles": ["moderator"], "expires_at": NOW + 300}):
            with self.subTest(value=roles_value):
                self.assertDenied("verified_role_required", prepare, "twitch.moderation.timeout", {"user_id": TARGET, "duration": 1}, subject_id=MOD, roles=roles_value)

    def test_verified_moderator_identity_is_bound_to_query(self):
        role = RoleEvidence(MOD, BR, frozenset({"moderator"}), NOW, NOW + 60)
        command = prepare("twitch.moderation.ban", {"user_id": TARGET}, subject_id=MOD, roles=role)
        self.assertEqual(command.query, {"broadcaster_id": BR, "moderator_id": MOD})
        self.assertEqual(command.body, {"data": {"user_id": TARGET}})
        self.assertDenied("prepared_operation_expired", execute, CLIENT, TOKEN, command, Transport(), now=NOW + 60)

    def test_wrong_expired_future_or_long_lived_role_evidence_is_denied(self):
        for role, reason in (
            (RoleEvidence(MOD, TARGET, frozenset({"moderator"}), NOW, NOW + 60), "evidence_identity_mismatch"),
            (RoleEvidence(MOD, BR, frozenset({"moderator"}), NOW - 400, NOW - 100), "evidence_expired"),
            (RoleEvidence(MOD, BR, frozenset({"moderator"}), NOW + 1, NOW + 61), "evidence_expired"),
            (RoleEvidence(MOD, BR, frozenset({"moderator"}), NOW, NOW + 301), "evidence_expired"),
            (RoleEvidence(MOD, BR, frozenset({"editor"}), NOW, NOW + 60), "role_required"),
        ):
            with self.subTest(reason=reason):
                self.assertDenied(reason, prepare, "twitch.shield.update", {"is_active": True}, subject_id=MOD, roles=role)

    def test_owner_does_not_need_redundant_moderator_scope_lookup(self):
        command = prepare("twitch.shield.update", {"is_active": True}, scopes={"moderator:manage:shield_mode"})
        self.assertEqual(command.query, QMOD)

    def test_clip_editor_scope_and_role_are_both_required(self):
        role = RoleEvidence(MOD, BR, frozenset({"editor"}), NOW, NOW + 60)
        proof = rights("video", ["100"], subject_id=MOD)
        self.assertDenied("clip_subject_scope_required", prepare, "twitch.clip.vod.create", WIRE["clip.vod.create"][2], subject_id=MOD, roles=role, rights=proof, scopes={"channel:manage:clips"})
        command = prepare("twitch.clip.vod.create", WIRE["clip.vod.create"][2], subject_id=MOD, roles=role, rights=proof, scopes={"editor:manage:clips"})
        self.assertEqual(command.query["editor_id"], MOD)
        self.assertDenied("clip_subject_scope_required", prepare, "twitch.clip.download", {"clip_id": ["ClipOne"]}, scopes={"editor:manage:clips"})

    def test_live_and_monetization_requirements_fail_closed(self):
        for short in ("clip.create", "marker.create", "ads.commercial.start", "raid.start"):
            with self.subTest(short=short):
                self.assertDenied("live_broadcast_required", prepare, "twitch." + short, WIRE[short][2], live=False)
        for short in ("poll.get", "prediction.create", "reward.create", "ads.snooze", "subscription.get", "bits.powerups.get"):
            with self.subTest(short=short):
                self.assertDenied("affiliate_or_partner_required", prepare, "twitch." + short, WIRE[short][2], account_type="")
        self.assertDenied("partner_required", prepare, "twitch.channel.update", {"delay": 30}, account_type="affiliate")

    def test_scheduling_never_creates_encoder_action(self):
        payload = WIRE["schedule.create"][2]
        recurring = prepare("twitch.schedule.create", payload, account_type="")
        self.assertIn("does not start", " ".join(recurring["effects"]))
        self.assertDenied("one_time_schedule_eligibility_required", prepare, "twitch.schedule.create", {**payload, "is_recurring": False}, account_type="")
        for action in ("twitch.stream.start", "twitch.post.text", "twitch.video.upload", "twitch.video.download", "twitch.analytics.dashboard", "twitch.channel_points.grant"):
            self.assertIn(action, UNSUPPORTED)
            self.assertDenied("unsupported_operation", prepare, action)

    def test_schedule_series_evidence_is_required_and_semantic(self):
        self.assertDenied("resource_evidence_required", prepare, "twitch.schedule.delete", {"id": SEGMENT})
        proof = _fixture_evidence("schedule.delete")
        deleted = prepare("twitch.schedule.delete", {"id": SEGMENT}, rights=proof)
        self.assertTrue(deleted["rights"]["is_recurring"])
        self.assertDenied("recurring_start_time_not_editable", prepare, "twitch.schedule.update", {"id": SEGMENT, "start_time": START}, rights=proof)
        nonrecurring = replace(proof, metadata_json=json.dumps({"resources": {SEGMENT: {"is_recurring": False}}}))
        prepare("twitch.schedule.update", {"id": SEGMENT, "title": "New title"}, rights=nonrecurring, account_type="")
        self.assertDenied("one_time_schedule_eligibility_required", prepare, "twitch.schedule.update", {"id": SEGMENT, "duration": 60}, rights=nonrecurring, account_type="")

    def test_vacation_times_and_timezone_are_validated(self):
        self.assertDenied("vacation_bounds_required", prepare, "twitch.schedule.settings.update", {"is_vacation_enabled": True})
        self.assertDenied("invalid_date_range", prepare, "twitch.schedule.settings.update", {"is_vacation_enabled": True, "vacation_start_time": END, "vacation_end_time": START, "timezone": "UTC"})
        self.assertDenied("invalid_timezone", prepare, "twitch.schedule.create", {**WIRE["schedule.create"][2], "timezone": "Mars/Olympus"})
        self.assertDenied("invalid_timestamp", prepare, "twitch.schedule.create", {**WIRE["schedule.create"][2], "start_time": "2026-10-20 20:00:00"})

    def test_strict_numeric_boolean_and_nested_schemas(self):
        for duration in (True, "30", 30.0, None, float("nan"), -1, 1209601):
            with self.subTest(duration=duration):
                with self.assertRaises(TwitchNativeError):
                    prepare("twitch.moderation.timeout", {"user_id": TARGET, "duration": duration})
        self.assertDenied("invalid_boolean", prepare, "twitch.shield.update", {"is_active": 1})
        self.assertDenied("unknown_payload_field", prepare, "twitch.poll.create", {**WIRE["poll.create"][2], "choices": [{"title": "A", "votes": 99}, {"title": "B"}]})
        self.assertDenied("required_field_missing", prepare, "twitch.poll.create", {**WIRE["poll.create"][2], "choices": [{}, {"title": "B"}]})
        self.assertDenied("duplicate_choices", prepare, "twitch.poll.create", {**WIRE["poll.create"][2], "choices": [{"title": "A"}, {"title": "a"}]})
        self.assertDenied("invalid_numeric_precision", prepare, "twitch.clip.create", {"duration": 12.55})

    def test_ban_cannot_silently_become_timeout_or_vice_versa(self):
        self.assertDenied("unknown_payload_field", prepare, "twitch.moderation.ban", {"user_id": TARGET, "duration": 5})
        self.assertDenied("required_field_missing", prepare, "twitch.moderation.timeout", {"user_id": TARGET})
        self.assertDenied("cannot_moderate_broadcaster_or_self", prepare, "twitch.moderation.ban", {"user_id": BR})

    def test_empty_updates_and_mutually_exclusive_controls_are_denied(self):
        self.assertDenied("empty_update", prepare, "twitch.channel.update")
        self.assertDenied("automod_level_and_categories_exclusive", prepare, "twitch.automod.settings.update", {"overall_level": 2, "swearing": 4})
        self.assertDenied("setting_value_requires_enabled_flag", prepare, "twitch.chat.settings.update", {"slow_mode_wait_time": 10})
        self.assertDenied("unknown_payload_field", prepare, "twitch.poll.create", {**WIRE["poll.create"][2], "bits_voting_enabled": True})

    def test_prediction_resolution_requires_exact_winning_outcome(self):
        self.assertDenied("prediction_winner_condition_failed", prepare, "twitch.prediction.end", {"id": "p1", "status": "RESOLVED"})
        self.assertDenied("prediction_winner_condition_failed", prepare, "twitch.prediction.end", {"id": "p1", "status": "CANCELED", "winning_outcome_id": "o1"})
        for status in ("CANCELED", "LOCKED"):
            prepare("twitch.prediction.end", {"id": "p1", "status": status})

    def test_endpoint_specific_pagination_and_reward_cooldown_limits(self):
        prepare("twitch.prediction.get", {"id": ["p" + str(value) for value in range(25)], "first": 25})
        self.assertDenied("invalid_array_size", prepare, "twitch.prediction.get", {"id": ["p" + str(value) for value in range(26)]})
        self.assertDenied("unknown_payload_field", prepare, "twitch.chat.emotes.user.get", {"first": 20})
        self.assertDenied("invalid_numeric_range", prepare, "twitch.reward.create", {"title": "Reward", "cost": 10, "is_global_cooldown_enabled": True, "global_cooldown_seconds": 604801})

    def test_content_download_needs_three_separate_proofs(self):
        self.assertDenied("resource_evidence_required", prepare, "twitch.clip.download", {"clip_id": ["ClipOne"]})
        for owner, reuse, storage, reason in (
            (False, True, True, "resource_ownership_required"),
            (True, False, True, "content_reuse_and_storage_authorization_required"),
            (True, True, False, "content_reuse_and_storage_authorization_required"),
        ):
            proof = rights("clip", ["ClipOne"], ownership_verified=owner, reuse_authorized=reuse, storage_authorized=storage)
            self.assertDenied(reason, prepare, "twitch.clip.download", {"clip_id": ["ClipOne"]}, rights=proof)
        self.assertDenied("resource_evidence_required", prepare, "twitch.clip.download", {"clip_id": ["ClipOne"]}, rights={"ownership_verified": True, "reuse_authorized": True, "storage_authorized": True})

    def test_rights_are_resource_subject_client_and_time_bound(self):
        valid = _fixture_evidence("clip.download")
        for proof, reason in ((replace(valid, resource_ids=("Other",)), "resource_evidence_mismatch"),
                (replace(valid, subject_id=MOD), "evidence_identity_mismatch"),
                (replace(valid, broadcaster_id=TARGET), "evidence_identity_mismatch"),
                (replace(valid, expires_at=NOW), "evidence_expired")):
            self.assertDenied(reason, prepare, "twitch.clip.download", {"clip_id": ["ClipOne"]}, rights=proof)
        command = prepare("twitch.clip.download", {"clip_id": ["ClipOne"]}, rights=valid)
        fake = Transport()
        self.assertDenied("resource_client_mismatch", execute, "other_client", TOKEN, command, fake, now=NOW)
        self.assertEqual(fake.calls, [])

    def test_reward_creator_app_must_be_verified(self):
        self.assertDenied("creator_app_ownership_required", prepare, "twitch.reward.delete", {"id": "reward-1"}, rights=rights("reward", ["reward-1"]))
        proof = _fixture_evidence("reward.delete")
        command = prepare("twitch.reward.delete", {"id": "reward-1"}, rights=proof)
        self.assertIn("fulfilled", " ".join(command["effects"]))
        self.assertDenied("redemption_status_or_ids_required", prepare, "twitch.redemption.get", {"reward_id": "reward-1"}, rights=proof)

    def test_marker_requires_separate_vod_setting_attestation(self):
        self.assertDenied("resource_evidence_required", prepare, "twitch.marker.create", {"description": "Spot"})
        self.assertDenied("past_broadcast_storage_required", prepare, "twitch.marker.create", {"description": "Spot"}, rights=rights("marker_settings"))

    def test_approval_semantics_stable_across_fresh_resource_verifications(self):
        first = prepare("twitch.clip.download", {"clip_id": ["ClipOne"]}, rights=_fixture_evidence("clip.download"))
        second = prepare("twitch.clip.download", {"clip_id": ["ClipOne"]}, rights=rights("clip", ["ClipOne"], now=NOW + 40, reuse_authorized=True, storage_authorized=True), now=NOW + 40)
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(first.payload_sha256, second.payload_sha256)
        self.assertNotEqual(first._signature, second._signature)
        changed = prepare("twitch.chat.send", {"message": "A"})
        changed2 = prepare("twitch.chat.send", {"message": "B"})
        self.assertNotEqual(changed.payload_sha256, changed2.payload_sha256)

    def test_manifest_rejects_serialized_tampered_and_expired_commands(self):
        command = prepare("twitch.chat.send", {"message": "Approved"})
        fake = Transport()
        self.assertDenied("prepared_operation_required", execute, CLIENT, TOKEN, command.as_dict(), fake, now=NOW)
        self.assertDenied("prepared_operation_expired", execute, CLIENT, TOKEN, command, fake, now=NOW + 300)
        changed = command.as_dict()
        changed["body"]["message"] = "Unapproved"
        forged = replace(command, _semantic_json=json.dumps(changed))
        self.assertDenied("prepared_operation_tampered", execute, CLIENT, TOKEN, forged, fake, now=NOW)
        self.assertEqual(fake.calls, [])
        detached = command.body
        detached["message"] = "Unapproved"
        self.assertEqual(command.body["message"], "Approved")

    def test_fixed_origin_query_encoding_and_no_credentials_in_results(self):
        query = "Music & callback=https://evil.example/#x"
        command = prepare("twitch.category.search", {"query": query})
        fake = Transport({"data": [{"id": "99", "name": "Music", "access_token": TOKEN, "nested": {"email": "a@example.invalid", "message": TOKEN}}]})
        result = execute(CLIENT, TOKEN, command, fake, now=NOW)
        request = fake.calls[0]
        self.assertEqual(urlsplit(request["url"]).netloc, "api.twitch.tv")
        self.assertEqual(urlsplit(request["url"]).path, "/helix/search/categories")
        self.assertEqual(parse_qs(urlsplit(request["url"]).query), {"query": [query]})
        self.assertEqual(request["headers"]["Authorization"], "Bearer " + TOKEN)
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertNotIn("email", json.dumps(result))
        self.assertNotIn("access_token", json.dumps(result))

    def test_header_injection_is_rejected_before_transport(self):
        fake = Transport()
        command = prepare("twitch.stream.get")
        for client, token, reason in (("x\r\nHost: evil", TOKEN, "invalid_client_id"), (CLIENT, "bad\r\nHeader: x", "invalid_access_token")):
            self.assertDenied(reason, execute, client, token, command, fake, now=NOW)
        self.assertEqual(fake.calls, [])

    def test_unknown_writes_never_retry_and_errors_hide_upstream(self):
        command = prepare("twitch.chat.send", {"message": "once"})
        for fake in (Transport(error=TimeoutError(TOKEN)), Transport({"message": TOKEN}, status=500), Transport({"data": []}, status=302), Transport({"message": TOKEN}, status=408)):
            with self.subTest(fake=fake.response):
                with self.assertRaises(TwitchNativeError) as caught:
                    execute(CLIENT, TOKEN, command, fake, now=NOW)
                error = caught.exception
                self.assertTrue(error.unknown_result)
                self.assertFalse(error.retryable)
                self.assertEqual(len(fake.calls), 1)
                self.assertNotIn(TOKEN, str(error))
                self.assertNotIn(TOKEN, "".join(traceback.format_exception(error)))

    def test_definite_provider_denials_do_not_claim_unknown_or_success(self):
        command = prepare("twitch.chat.send", {"message": "once"})
        for status, reason in ((400, "provider_rejected_operation"), (401, "token_invalid_or_revoked"), (403, "provider_permission_or_eligibility_denied"), (429, "provider_rate_limited")):
            fake = Transport({"error": TOKEN}, status=status)
            error = self.assertDenied(reason, execute, CLIENT, TOKEN, command, fake, now=NOW)
            self.assertFalse(error.unknown_result)
            self.assertEqual(error.provider_status, status)
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(error.retryable, status == 429)

    def test_chat_http_200_requires_true_is_sent_and_message_id(self):
        command = prepare("twitch.chat.send", {"message": "once"})
        denied = self.assertDenied("chat_message_not_sent", execute, CLIENT, TOKEN, command,
                                  Transport({"data": [{"is_sent": False, "drop_reason": {"message": TOKEN}}]}), now=NOW)
        self.assertFalse(denied.unknown_result)
        unknown = self.assertDenied("chat_result_unknown", execute, CLIENT, TOKEN, command,
                                   Transport({"data": [{"is_sent": True}]}), now=NOW)
        self.assertTrue(unknown.unknown_result)
        result = execute(CLIENT, TOKEN, command, Transport({"data": [{"is_sent": True, "message_id": "msg-1"}]}), now=NOW)
        self.assertTrue(result["confirmed"])

    def test_chat_cannot_suppress_shared_audience_with_user_token(self):
        self.assertDenied("unknown_payload_field", prepare, "twitch.chat.send", {"message": "hi", "for_source_only": True})
        self.assertIn("Shared Chat", " ".join(prepare("twitch.chat.send", {"message": "hi"})["effects"]))

    def test_whisper_204_is_not_a_delivery_confirmation(self):
        command = prepare("twitch.chat.whisper.send", {"to_user_id": TARGET, "message": "Hello"})
        fake = Transport(status=204)
        result = execute(CLIENT, TOKEN, command, fake, now=NOW)
        self.assertEqual(result["status"], "accepted")
        self.assertFalse(result["confirmed"])
        self.assertFalse(result["deliveryVerified"])
        self.assertEqual(len(fake.calls), 1)
        self.assertDenied("whisper_recipient_must_be_other_user", prepare, "twitch.chat.whisper.send", {"to_user_id": BR, "message": "Hello"})

    def test_profile_read_excludes_invalid_deprecated_view_count_and_email(self):
        command = prepare("twitch.profile.get")
        result = execute(CLIENT, TOKEN, command, Transport({"data": [{"id": BR, "description": "Piano", "view_count": 999999, "email": "private@example.invalid"}]}), now=NOW)
        self.assertEqual(result["data"], [{"id": BR, "description": "Piano"}])
        cleared = prepare("twitch.profile.update", {"description": ""})
        self.assertEqual(cleared.query, {"description": ""})

    def test_subscribed_user_lists_may_intentionally_reference_other_channels(self):
        for action in ("twitch.channel.followed.get", "twitch.moderation.channels.get"):
            with self.subTest(action=action):
                result = execute(CLIENT, TOKEN, prepare(action), Transport({"data": [{"broadcaster_id": TARGET}]}), now=NOW)
                self.assertEqual(result["data"][0]["broadcaster_id"], TARGET)

    def test_follower_total_projection_does_not_expose_individual_followers(self):
        result = execute(CLIENT, TOKEN, prepare("twitch.channel.followers.total"),
            Transport({"data": [{"user_id": TARGET, "user_name": "Private follower"}], "total": 5}), now=NOW)
        self.assertEqual(result["data"], [])
        self.assertEqual(result["total"], 5)

    def test_clip_lookup_does_not_mistake_missing_resource_for_creation(self):
        command = prepare("twitch.clip.lookup", {"id": ["ClipOne"]})
        result = execute(CLIENT, TOKEN, command, Transport({"data": []}), now=NOW)
        self.assertFalse(result["resourceVerification"]["creationConfirmed"])
        self.assertEqual(result["resourceVerification"]["missingIds"], ["ClipOne"])

    def test_empty_or_malformed_successful_writes_are_unknown(self):
        command = prepare("twitch.poll.create", WIRE["poll.create"][2])
        for body in ({"data": []}, {"data": "not-array"}, {"error": "wrong"}, {"data": [{"value": float("nan")}]}, {"data": [{"text": "x" * 300000}]}):
            with self.subTest(body_type=type(body.get("data"))):
                with self.assertRaises(TwitchNativeError) as caught:
                    execute(CLIENT, TOKEN, command, Transport(body), now=NOW)
                self.assertTrue(caught.exception.unknown_result)

    def test_clip_creation_is_accepted_until_actual_lookup_succeeds(self):
        command = prepare("twitch.clip.create", {"duration": 30})
        fake = Transport({"data": [{"id": "ClipOne", "edit_url": "https://www.twitch.tv/example/clip/ClipOne"}]}, status=202)
        result = execute(CLIENT, TOKEN, command, fake, now=NOW)
        self.assertEqual(result["status"], "accepted")
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["confirmation"]["action"], "twitch.clip.lookup")
        self.assertEqual(len(fake.calls), 1)
        lookup = prepare("twitch.clip.lookup", {"id": ["ClipOne"]})
        confirmed = execute(CLIENT, TOKEN, lookup, Transport({"data": [{"id": "ClipOne", "broadcaster_id": BR}]}), now=NOW)
        self.assertTrue(confirmed["confirmed"])

    def test_channel_resources_cannot_escape_selected_channel(self):
        cases = (("twitch.stream.get", {}, {"data": [{"user_id": TARGET, "viewer_count": 5}]}),
                 ("twitch.clip.lookup", {"id": ["ClipOne"]}, {"data": [{"id": "ClipOne", "broadcaster_id": TARGET}]}),
                 ("twitch.video.get", {}, {"data": [{"id": "100", "user_id": TARGET}]}),
                 ("twitch.marker.get", {}, {"data": [{"user_id": TARGET}]}),
                 ("twitch.analytics.game.get", {"game_id": "game-1"}, {"data": [{"game_id": "other-game"}]}))
        for action, payload, response in cases:
            with self.subTest(action=action):
                self.assertDenied("provider_resource_identity_mismatch", execute, CLIENT, TOKEN, prepare(action, payload), Transport(response), now=NOW)

    def test_downloads_are_official_expiring_links_without_media_fetch(self):
        command = prepare("twitch.clip.download", {"clip_id": ["ClipOne"]}, rights=_fixture_evidence("clip.download"))
        fake = Transport({"data": [{"clip_id": "ClipOne", "landscape_download_url": "https://production.assets.clips.twitchcdn.net/clip.mp4?sig=abc", "portrait_download_url": None}]})
        result = execute(CLIENT, TOKEN, command, fake, now=NOW)
        self.assertFalse(result["contentRights"]["filesFetched"])
        self.assertEqual(len(fake.calls), 1)
        for link in ("https://evil.example/a.mp4", "http://clips.twitch.tv/a.mp4", "https://twitch.tv@evil.example/a.mp4", "https://evil.twitch.tv.attacker.example/a", "file:///tmp/secret", "https://clips.twitch.tv:444/a"):
            with self.subTest(link=link):
                self.assertDenied("invalid_download_link", execute, CLIENT, TOKEN, command, Transport({"data": [{"clip_id": "ClipOne", "landscape_download_url": link}]}), now=NOW)

    def test_analytics_projection_preserves_real_provenance(self):
        command = prepare("twitch.analytics.stream.snapshot")
        result = execute(CLIENT, TOKEN, command, Transport({"data": [{"user_id": BR, "viewer_count": 17, "title": "Untrusted channel text"}]}), now=NOW)
        self.assertEqual(result["data"][0]["viewer_count"], 17)
        self.assertEqual(result["provenance"]["kind"], "live_viewer_snapshot")
        self.assertFalse(result["provenance"]["estimated"])
        self.assertFalse(result["provenance"]["creatorDashboard"])
        self.assertIn("watch_time", result["provenance"]["unavailableMetrics"])
        follow = execute(CLIENT, TOKEN, prepare("twitch.channel.followers.total"), Transport({"data": [], "total": 23}), now=NOW)
        self.assertEqual(follow["total"], 23)

    def test_secure_stream_key_is_never_in_generic_or_agent_result(self):
        command = prepare("twitch.stream.key.get")
        fake = Transport({"data": [{"stream_key": "synthetic_ingest_SECRET"}]})
        self.assertDenied("interactive_secret_handler_required", execute, CLIENT, TOKEN, command, fake, now=NOW)
        self.assertEqual(fake.calls, [])
        received = []
        result = execute_sensitive(CLIENT, TOKEN, command, fake, secret_sink=received.append, now=NOW)
        self.assertEqual(received, ["synthetic_ingest_SECRET"])
        self.assertNotIn("synthetic_ingest_SECRET", json.dumps(result))
        self.assertTrue(result["data"]["deliveredToSecureSink"])

    def test_secure_sink_failure_does_not_leak_secret_in_traceback(self):
        command = prepare("twitch.stream.key.get")
        def sink(secret):
            raise RuntimeError(secret)
        error = self.assertDenied("secure_secret_delivery_failed", execute_sensitive, CLIENT, TOKEN, command,
                                 Transport({"data": [{"stream_key": "synthetic_ingest_SECRET"}]}), secret_sink=sink, now=NOW)
        self.assertNotIn("synthetic_ingest_SECRET", "".join(traceback.format_exception(error)))

    def test_calendar_requires_complete_bounded_provider_document(self):
        command = prepare("twitch.schedule.calendar.get")
        self.assertDenied("incomplete_calendar_response", execute, CLIENT, TOKEN, command, Transport({"raw": "BEGIN:VCALENDAR\ntruncated"}), now=NOW)
        calendar = "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n"
        result = execute(CLIENT, TOKEN, command, Transport({"raw": calendar}), now=NOW)
        self.assertEqual(result["data"]["calendar"], calendar)

    def test_moderator_preflight_uses_authenticated_subject_and_bounded_cursor(self):
        fake = Transport(responses=[
            {"status": 200, "body": {"data": [{"broadcaster_id": "999"}], "pagination": {"cursor": "next/+="}}},
            {"status": 200, "body": {"data": [{"broadcaster_id": BR}], "pagination": {}}},
        ])
        proof = verify_roles(client_id=CLIENT, access_token=TOKEN, subject_id=MOD, broadcaster_id=BR,
            scopes={"user:read:moderated_channels"}, transport=fake, now=NOW)
        self.assertEqual(proof.roles, frozenset({"moderator"}))
        self.assertEqual(proof.expires_at - proof.checked_at, EVIDENCE_TTL)
        for call in fake.calls:
            self.assertEqual(parse_qs(urlsplit(call["url"]).query)["user_id"], [MOD])
        self.assertEqual(parse_qs(urlsplit(fake.calls[1]["url"]).query)["after"], ["next/+="])
        repeat = Transport({"data": [], "pagination": {"cursor": "repeat"}})
        self.assertDenied("role_required", verify_roles, client_id=CLIENT, access_token=TOKEN, subject_id=MOD,
            broadcaster_id=BR, scopes={"user:read:moderated_channels"}, transport=repeat, now=NOW)
        self.assertEqual(len(repeat.calls), 2)

    def test_editor_preflight_requires_separate_broadcaster_editor_list_grant(self):
        fake = Transport({"data": [{"user_id": MOD}]})
        kwargs = dict(client_id=CLIENT, access_token=TOKEN, subject_id=MOD, broadcaster_id=BR,
                      scopes={"editor:manage:clips"}, transport=fake, now=NOW, role="editor")
        self.assertDenied("broadcaster_editor_lookup_grant_required", verify_roles, **kwargs)
        proof = verify_roles(**kwargs, broadcaster_access_token=TOKEN, broadcaster_scopes={"channel:read:editors"})
        self.assertEqual(proof.roles, frozenset({"editor"}))
        self.assertEqual(urlsplit(fake.calls[0]["url"]).path, "/helix/channels/editors")

    def test_resource_preflight_must_match_every_exact_requested_id(self):
        kwargs = dict(client_id=CLIENT, access_token=TOKEN, subject_id=BR, broadcaster_id=BR,
                      scopes=ALL_SCOPES, now=NOW)
        self.assertDenied("resource_not_owned_by_channel", verify_resource_access, "clip", ["ClipOne"],
            **kwargs, transport=Transport({"data": [{"id": "ClipOne", "broadcaster_id": TARGET}]}))
        self.assertDenied("resource_missing_or_not_manageable", verify_resource_access, "video", ["100", "101"],
            **kwargs, transport=Transport({"data": [{"id": "100", "user_id": BR}]}))
        proof = verify_resource_access("clip", ["ClipOne"], **kwargs,
            transport=Transport({"data": [{"id": "ClipOne", "broadcaster_id": BR}]}))
        self.assertTrue(proof.ownership_verified)
        self.assertFalse(proof.reuse_authorized)
        self.assertFalse(proof.storage_authorized)

    def test_creator_app_preflight_enforces_manageable_reward_filter(self):
        fake = Transport({"data": [{"id": "reward-1", "broadcaster_id": BR}]})
        proof = verify_resource_access("reward", ["reward-1"], client_id=CLIENT, access_token=TOKEN,
            subject_id=BR, broadcaster_id=BR, scopes={"channel:manage:redemptions"}, transport=fake, now=NOW)
        self.assertTrue(proof.creator_app_verified)
        query = parse_qs(urlsplit(fake.calls[0]["url"]).query)
        self.assertEqual(query, {"broadcaster_id": [BR], "id": ["reward-1"], "only_manageable_rewards": ["true"]})

    def test_schedule_preflight_records_actual_recurring_semantics(self):
        fake = Transport({"data": {"broadcaster_id": BR, "segments": [{"id": SEGMENT, "is_recurring": True}]}})
        proof = verify_resource_access("schedule", [SEGMENT], client_id=CLIENT, access_token=TOKEN,
            subject_id=BR, broadcaster_id=BR, scopes=[], transport=fake, now=NOW)
        command = prepare("twitch.schedule.delete", {"id": SEGMENT}, rights=proof)
        self.assertTrue(command["rights"]["is_recurring"])


if __name__ == "__main__":
    unittest.main()
