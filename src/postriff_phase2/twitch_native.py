"""Twitch native Helix contracts; every request uses an injected, bounded transport.

This module is deliberately independent of OAuth, database approvals and the queue.
The service must load identity/scopes/roles from trusted persistence, verify its
approval against ``PreparedOperation.as_dict()``, and re-prepare at dispatch under
the connection's revocation fence. Nothing supplied in an HTTP permission field
constitutes evidence. There are no real credentials, background threads or network
calls at import time, and execute never retries a request.

Endpoint contracts: https://dev.twitch.tv/docs/api/reference/ (2026-10-18).
Offline contract verification is not evidence of live or commercial approval.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from types import MappingProxyType
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError

HELIX = "https://api.twitch.tv/helix"
REFERENCE = "https://dev.twitch.tv/docs/api/reference/"
EVIDENCE_TTL = 300
RESPONSE_LIMIT = 262144
_SEAL = object()
_MANIFEST_KEY = secrets.token_bytes(32)
_ID_PATTERN = r"^[1-9][0-9]{0,29}$"
_OPAQUE_PATTERN = r"^[A-Za-z0-9_+=./:-]{1,512}$"


class TwitchNativeError(AlphaError):
    """Safe vocabulary only: upstream text and credentials never enter an error."""

    def __init__(self, reason, *, status=400, unknown_result=False, retryable=False,
                 provider_status=None):
        super().__init__("Twitch operation could not complete: " + reason + ".",
                         status, code="twitch_" + reason)
        self.reason = reason
        self.unknown_result = bool(unknown_result)
        self.retryable = bool(retryable) and not self.unknown_result
        self.provider_status = provider_status


def _deny(reason, **kwargs):
    raise TwitchNativeError(reason, **kwargs) from None


def _json(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False)
        encoded.encode("utf-8")
        return encoded
    except (TypeError, ValueError, RecursionError, UnicodeError):
        _deny("invalid_json")


def _clock(now=None):
    value = time.time() if now is None else now
    if type(value) not in (float, int):
        _deny("invalid_clock")
    try:
        value = float(value)
    except (OverflowError, ValueError):
        _deny("invalid_clock")
    if not math.isfinite(value) or value < 0:
        _deny("invalid_clock")
    return value


def _uid(value):
    if not isinstance(value, str) or re.fullmatch(_ID_PATTERN, value) is None:
        _deny("invalid_account_id")
    return value


def _credentials(client_id, token):
    if not isinstance(client_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", client_id) is None:
        _deny("invalid_client_id")
    if (not isinstance(token, str) or not 1 <= len(token) <= 8192 or
            any(ord(c) < 33 or ord(c) > 126 for c in token)):
        _deny("invalid_access_token")


def _string(label, max_length=140, *, required=False, minimum=1, pattern=None, format=None, enum=None):
    result = {"type": "string", "label": label, "required": required,
              "minLength": minimum, "maxLength": max_length}
    if pattern:
        result["pattern"] = pattern
    if format:
        result["format"] = format
    if enum is not None:
        result["enum"] = list(enum)
    return result


def _integer(label, low=0, high=2147483647, *, required=False, enum=None):
    result = {"type": "integer", "label": label, "required": required,
              "minimum": low, "maximum": high}
    if enum is not None:
        result["enum"] = list(enum)
    return result


def _boolean(label, *, required=False):
    return {"type": "boolean", "label": label, "required": required}


def _number(label, low, high, *, required=False, multiple=0.1):
    return {"type": "number", "label": label, "required": required,
            "minimum": low, "maximum": high, "multipleOf": multiple}


def _id(label="User ID", *, required=False, zero=False):
    return _string(label, 30, required=required, pattern=r"^(0|[1-9][0-9]{0,29})$" if zero else _ID_PATTERN)


def _opaque(label="Resource ID", *, required=False):
    return _string(label, 512, required=required, pattern=_OPAQUE_PATTERN)


def _array(label, items, low=0, high=100, *, required=False, unique=True):
    return {"type": "array", "label": label, "required": required, "items": items,
            "minItems": low, "maxItems": high, "uniqueItems": unique}


def _object(label, properties, *, required=False):
    return {"type": "object", "label": label, "required": required,
            "properties": properties, "additionalProperties": False}


def _page(maximum=100):
    return {"first": _integer("Results per page", 1, maximum),
            "after": _opaque("Next-page cursor")}


def _time_field(label, *, required=False):
    return _string(label, 40, required=required, format="date-time")


def _timezone_field(*, required=False):
    return _string("Time zone", 128, required=required, format="iana-timezone")


def _validate_field(value, schema, depth=0):
    if depth > 8:
        _deny("payload_too_deep")
    kind = schema["type"]
    if kind == "string":
        if not isinstance(value, str) or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 8192):
            _deny("invalid_field_length")
        if any(ord(c) < 32 and c not in "\n\t" for c in value) or "\x7f" in value:
            _deny("invalid_control_character")
        if schema.get("minLength", 0) > 0 and not value.strip():
            _deny("empty_field")
        if schema.get("pattern") and re.fullmatch(schema["pattern"], value) is None:
            _deny("invalid_field_format")
        if schema.get("format") == "date-time":
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value):
                _deny("invalid_timestamp")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError
            except ValueError:
                _deny("invalid_timestamp")
        if schema.get("format") == "iana-timezone":
            try:
                ZoneInfo(value)
            except (ValueError, ZoneInfoNotFoundError):
                _deny("invalid_timezone")
    elif kind in ("integer", "number"):
        if (type(value) is not int if kind == "integer" else type(value) not in (int, float)):
            _deny("invalid_numeric_type")
        # Check integer bounds before float conversion inside math.isfinite:
        # a syntactically valid JSON integer may be thousands of digits long.
        if not schema["minimum"] <= value <= schema["maximum"] or not math.isfinite(value):
            _deny("invalid_numeric_range")
        if "multipleOf" in schema:
            try:
                if Decimal(str(value)) % Decimal(str(schema["multipleOf"])) != 0:
                    _deny("invalid_numeric_precision")
            except InvalidOperation:
                _deny("invalid_numeric_precision")
    elif kind == "boolean":
        if type(value) is not bool:
            _deny("invalid_boolean")
    elif kind == "array":
        if not isinstance(value, list) or not schema["minItems"] <= len(value) <= schema["maxItems"]:
            _deny("invalid_array_size")
        value = [_validate_field(item, schema["items"], depth + 1) for item in value]
        if schema.get("uniqueItems") and len({_json(item) for item in value}) != len(value):
            _deny("duplicate_array_items")
    elif kind == "object":
        value = _validate_payload(value, schema["properties"], depth + 1)
    else:
        _deny("unsupported_field_schema", status=500)
    if "enum" in schema and value not in schema["enum"]:
        _deny("invalid_field_value")
    return value


def _validate_payload(payload, fields, depth=0):
    if not isinstance(payload, dict) or not all(isinstance(k, str) for k in payload):
        _deny("payload_object_required")
    if not payload.keys() <= fields.keys():
        _deny("unknown_payload_field")
    if any(s.get("required") and k not in payload for k, s in fields.items()):
        _deny("required_field_missing")
    if len(_json(payload).encode("utf-8")) > 32768:
        _deny("payload_too_large", status=413)
    return {key: _validate_field(value, fields[key], depth) for key, value in payload.items()}


@dataclass(frozen=True)
class Operation:
    action: str
    label: str
    group: str
    method: str
    path: str
    fields_json: str = "{}"
    scope_options: tuple = ((),)
    subject_policy: str = "broadcaster"
    binding: str = "broadcaster_query"
    query_fields: tuple = ()
    body_root: str = ""
    expected: tuple = (200,)
    eligibility: str = ""
    requires_live: bool = False
    resource_policy: str = ""
    risk: str = "read"
    effects: tuple = ()
    schedulable: bool = False
    response_shape: str = "list"
    mutation_fields_required: bool = False
    analytics_kind: str = ""

    @property
    def fields(self):
        return json.loads(self.fields_json)

    @property
    def write(self):
        return self.method != "GET"

    @property
    def required_scopes(self):
        return self.scope_options


_registry = {}


def _op(action, label, method, path, *, fields=None, scopes=(), alternatives=None,
        subject="broadcaster", binding="broadcaster_query", query=(), body_root="",
        expected=None, eligibility="", live=False, resources="", risk=None,
        effects=(), schedulable=False, response="list", changes=False, analytics=""):
    action = "twitch." + action
    if action in _registry:
        raise RuntimeError("Duplicate Twitch operation")
    if expected is None:
        expected = (204,) if method == "DELETE" else (200,)
    _registry[action] = Operation(action, label, action.split(".")[1], method, path,
        _json(fields or {}), tuple(tuple(s) for s in alternatives) if alternatives else (tuple(scopes),),
        subject, binding, tuple(query), body_root, tuple(expected), eligibility, live,
        resources, risk or ("write" if method != "GET" else "read"), tuple(effects),
        schedulable, response, changes, analytics)


_broadcast = ("channel:manage:broadcast",)
_schedule = ("channel:manage:schedule",)
_mod_messages = ("moderator:manage:chat_messages",)
_mod_bans = ("moderator:manage:banned_users",)
_clip_scopes = (("channel:manage:clips",), ("editor:manage:clips",))
_choices = _object("Choice", {"title": _string("Choice title", 25, required=True)})
_labels = _object("Content label", {
    "id": _string("Label", 64, required=True, enum=("DebatedSocialIssuesAndPolitics", "DrugsIntoxication", "Gambling", "MatureGame", "ProfanityVulgarity", "SexualThemes", "ViolentGraphic")),
    "is_enabled": _boolean("Enabled", required=True)})

# Public information is still scoped to the service-selected channel, never a raw URL.
_op("channel.get", "Channel information", "GET", "/channels", subject="any")
_op("channel.update", "Update channel information", "PATCH", "/channels", scopes=_broadcast,
    fields={"title": _string("Stream title"), "game_id": _string("Category ID", 30, minimum=0, pattern=r"^[0-9]{0,30}$"),
            "broadcaster_language": _string("Language", 5, pattern=r"^(?:[a-z]{2}|other)$"),
            "delay": _integer("Broadcast delay (seconds)", 0, 900),
            "tags": _array("Tags", _string("Tag", 25, pattern=r"^[^\s]+$"), 0, 10),
            "content_classification_labels": _array("Content classification labels", _labels, 0, 7),
            "is_branded_content": _boolean("Contains branded content")},
    expected=(204,), changes=True, schedulable=True,
    effects=("Updates channel metadata; does not start a stream.",))
_op("channel.editors.get", "Channel editors", "GET", "/channels/editors", scopes=("channel:read:editors",))
_op("channel.followers.get", "Channel followers", "GET", "/channels/followers",
    scopes=("moderator:read:followers",), subject="moderator", fields={**_page(), "user_id": _id("Follower ID")}, query=("first", "after", "user_id"))
_op("channel.followers.total", "Follower count", "GET", "/channels/followers", subject="any", analytics="follower_count")
_op("stream.get", "Live status", "GET", "/streams", subject="any", binding="broadcaster_user_query")
_op("stream.key.get", "Read stream key", "GET", "/streams/key", scopes=("channel:read:stream_key",),
    risk="secret", effects=("Reveals an encoder credential. Route to a secure secret handler, never the agent or generic UI.",))
_op("category.search", "Search stream categories", "GET", "/search/categories", subject="any", binding="none",
    fields={"query": _string("Search", 100, required=True), **_page()}, query=("query", "first", "after"))
_op("channel.labels.get", "Available content labels", "GET", "/content_classification_labels", subject="any", binding="none")
_op("channel.search", "Search channels", "GET", "/search/channels", subject="any", binding="none",
    fields={"query": _string("Search", 100, required=True), "live_only": _boolean("Live channels only"), **_page()}, query=("query", "live_only", "first", "after"))
_op("channel.followed.get", "Followed channels", "GET", "/channels/followed", scopes=("user:read:follows",), binding="user_query", subject="any", fields=_page(), query=("first", "after"))
_op("stream.followed.get", "Followed live streams", "GET", "/streams/followed", scopes=("user:read:follows",), binding="user_query", subject="any", fields=_page(), query=("first", "after"))
_op("profile.get", "Connected user profile", "GET", "/users", binding="none",
    effects=("Reads the connected user's own profile. Deprecated channel view_count and email are excluded.",))
_op("profile.update", "Update channel description", "PUT", "/users", scopes=("user:edit",), binding="none",
    fields={"description": _string("Description", 300, minimum=0, required=True)}, query=("description",))

_op("schedule.get", "Stream schedule", "GET", "/schedule", subject="any", response="object",
    fields={"id": _array("Segment IDs", _opaque(), 1, 100), "start_time": _time_field("Starting from"), **_page(25)},
    query=("id", "start_time", "first", "after"))
_op("schedule.calendar.get", "Schedule iCalendar", "GET", "/schedule/icalendar", subject="any", response="calendar")
_op("schedule.settings.update", "Update schedule vacation", "PATCH", "/schedule/settings", scopes=_schedule,
    fields={"is_vacation_enabled": _boolean("Vacation enabled", required=True),
            "vacation_start_time": _time_field("Vacation starts"), "vacation_end_time": _time_field("Vacation ends"),
            "timezone": _timezone_field()},
    query=("is_vacation_enabled", "vacation_start_time", "vacation_end_time", "timezone"), expected=(204,), schedulable=True)
_op("schedule.create", "Create stream schedule segment", "POST", "/schedule/segment", scopes=_schedule, response="object",
    fields={"start_time": _time_field("Starts", required=True), "timezone": _timezone_field(required=True),
            "duration": _integer("Duration (minutes)", 30, 1380, required=True),
            "is_recurring": _boolean("Repeats weekly", required=True), "title": _string("Title"), "category_id": _id("Category ID")},
    schedulable=True, effects=("Creates a calendar entry; does not start an encoder or broadcast.", "Weekly entries repeat; one-time entries require affiliate or partner eligibility."))
_op("schedule.update", "Update stream schedule segment", "PATCH", "/schedule/segment", scopes=_schedule, response="object",
    fields={"id": _opaque("Segment ID", required=True), "start_time": _time_field("Starts"),
            "duration": _integer("Duration (minutes)", 30, 1380), "title": _string("Title"),
            "category_id": _id("Category ID"), "timezone": _timezone_field(), "is_canceled": _boolean("Cancel occurrence")},
    query=("id",), resources="schedule", changes=True, schedulable=True,
    effects=("Metadata changes affect every occurrence of a recurring segment; cancellation affects the next occurrence.",))
_op("schedule.delete", "Delete stream schedule segment", "DELETE", "/schedule/segment", scopes=_schedule,
    fields={"id": _opaque("Segment ID", required=True)}, query=("id",), resources="schedule", risk="destructive",
    effects=("Deleting a recurring segment removes its complete weekly series.",))
_op("marker.create", "Create stream marker", "POST", "/streams/markers", scopes=_broadcast, binding="marker_body",
    fields={"description": _string("Description", 140, minimum=0)}, subject="editor", live=True,
    resources="marker_settings", effects=("Marks this moment in the live stream; past broadcasts must be enabled.",))
_op("marker.get", "Stream markers", "GET", "/streams/markers", alternatives=(("user:read:broadcast",), _broadcast),
    subject="editor", binding="marker_query", fields={"video_id": _id("VOD ID"), **_page()}, query=("video_id", "first", "after"))

_chat_fields = {"message": _string("Message", 500, required=True)}
_op("chat.send", "Send live chat message", "POST", "/chat/messages", scopes=("user:write:chat",),
    subject="any", binding="chat_body", fields=_chat_fields, schedulable=True, response="chat",
    effects=("Sends as the connected Twitch user. User-token messages also reach participating Shared Chat channels.",))
_op("chat.reply", "Reply to a live chat message", "POST", "/chat/messages", scopes=("user:write:chat",),
    subject="any", binding="chat_body", fields={**_chat_fields, "reply_parent_message_id": _opaque("Parent message ID", required=True)},
    response="chat", schedulable=True, effects=("Replies as the connected Twitch user; Shared Chat audience applies.",))
_op("chat.chatters.get", "Connected chat users", "GET", "/chat/chatters", scopes=("moderator:read:chatters",),
    subject="moderator", binding="moderator_query", fields=_page(1000), query=("first", "after"),
    effects=("Chat connections are not a list of viewers or a viewer count.",))
_op("chat.settings.get", "Chat settings", "GET", "/chat/settings", subject="any")
_op("chat.settings.private.get", "Chat settings including moderation delays", "GET", "/chat/settings", scopes=("moderator:read:chat_settings",), subject="moderator", binding="moderator_query")
_chat_settings = {"emote_mode": _boolean("Emote only"), "follower_mode": _boolean("Followers only"),
    "follower_mode_duration": _integer("Required follow age (minutes)", 0, 129600),
    "non_moderator_chat_delay": _boolean("Delay non-moderator messages"),
    "non_moderator_chat_delay_duration": _integer("Message delay (seconds)", 2, 6, enum=(2, 4, 6)),
    "slow_mode": _boolean("Slow mode"), "slow_mode_wait_time": _integer("Slow-mode interval (seconds)", 3, 120),
    "subscriber_mode": _boolean("Subscribers only"), "unique_chat_mode": _boolean("Unique messages only")}
_op("chat.settings.update", "Update chat settings", "PATCH", "/chat/settings", scopes=("moderator:manage:chat_settings",),
    subject="moderator", binding="moderator_query", fields=_chat_settings, changes=True)
_op("chat.announcement.send", "Send chat announcement", "POST", "/chat/announcements", scopes=("moderator:manage:announcements",),
    subject="moderator", binding="moderator_query", fields={"message": _string("Announcement", 500, required=True),
    "color": _string("Color", 10, enum=("blue", "green", "orange", "purple", "primary"))}, expected=(204,), schedulable=True,
    effects=("User-token announcements can reach the Shared Chat session.",))
_op("chat.shoutout.send", "Send shoutout", "POST", "/chat/shoutouts", scopes=("moderator:manage:shoutouts",),
    subject="moderator", binding="shoutout_query", fields={"to_broadcaster_id": _id("Destination channel", required=True)},
    query=("to_broadcaster_id",), expected=(204,), live=True)
_op("chat.shared.get", "Shared Chat session", "GET", "/shared_chat/session", subject="any")
_op("chat.pin.get", "Pinned chat message", "GET", "/chat/pins", alternatives=(("moderator:read:chat_messages",), _mod_messages),
    subject="moderator", binding="moderator_query")
for _name, _label, _method in (("create", "Pin chat message", "PUT"), ("update", "Update pinned-message duration", "PATCH"), ("delete", "Unpin chat message", "DELETE")):
    _fields = {"message_id": _opaque("Message ID", required=True)}
    if _name != "delete":
        _fields["duration_seconds"] = _integer("Pinned duration (seconds)", 30, 1800)
    _op("chat.pin." + _name, _label, _method, "/chat/pins", scopes=_mod_messages, subject="moderator", binding="moderator_query",
        fields=_fields, query=tuple(_fields), expected=(204,), effects=("Only one moderator-pinned message can be active in this channel.",))
_op("chat.message.delete", "Delete one chat message", "DELETE", "/moderation/chat", scopes=_mod_messages,
    subject="moderator", binding="moderator_query", fields={"message_id": _opaque("Message ID", required=True)}, query=("message_id",), risk="destructive")
_op("chat.clear", "Clear chat history", "DELETE", "/moderation/chat", scopes=_mod_messages,
    subject="moderator", binding="moderator_query", risk="destructive", effects=("Removes all messages permitted by Twitch's chat-clear operation.",))
_op("chat.emotes.get", "Channel emotes", "GET", "/chat/emotes", subject="any")
_op("chat.badges.get", "Channel chat badges", "GET", "/chat/badges", subject="any")
_op("chat.emotes.global.get", "Global chat emotes", "GET", "/chat/emotes/global", subject="any", binding="none")
_op("chat.emotes.set.get", "Chat emote sets", "GET", "/chat/emotes/set", subject="any", binding="none",
    fields={"emote_set_id": _array("Emote set IDs", _opaque(), 1, 25, required=True)}, query=("emote_set_id",))
_op("chat.emotes.user.get", "Connected user's available emotes", "GET", "/chat/emotes/user", scopes=("user:read:emotes",), subject="any", binding="subscription_query", fields={"after": _opaque("Next-page cursor")}, query=("after",))
_op("chat.badges.global.get", "Global chat badges", "GET", "/chat/badges/global", subject="any", binding="none")
_op("chat.color.get", "Connected user's chat color", "GET", "/chat/color", subject="any", binding="user_query")
_colors = ("blue", "blue_violet", "cadet_blue", "chocolate", "coral", "dodger_blue", "firebrick", "golden_rod", "green", "hot_pink", "orange_red", "red", "sea_green", "spring_green", "yellow_green")
_op("chat.color.update", "Update connected user's chat color", "PUT", "/chat/color", scopes=("user:manage:chat_color",), subject="any", binding="user_query",
    fields={"color": _string("Named color or eligible account hex color", 20, required=True, pattern=r"^(?:#[0-9A-Fa-f]{6}|" + "|".join(_colors) + r")$")}, query=("color",), expected=(204,),
    effects=("Named colors work for all accounts. Twitch checks Turbo or Prime eligibility for custom hex colors.",))
_op("chat.whisper.send", "Send private whisper", "POST", "/whispers", scopes=("user:manage:whispers",), subject="any", binding="whisper_query",
    fields={"to_user_id": _id("Recipient user", required=True), "message": _string("Private message", 500, required=True)}, query=("to_user_id",), expected=(204,), response="whisper",
    effects=("Sends privately as the connected user; Twitch requires a verified phone number.", "Twitch may silently drop whispers even after HTTP 204; delivery cannot be confirmed by this API."))

for _name, _label in (("ban", "Ban chat user"), ("timeout", "Time out chat user")):
    _fields = {"user_id": _id("Target user", required=True), "reason": _string("Reason", 500, minimum=0)}
    if _name == "timeout":
        _fields["duration"] = _integer("Timeout (seconds)", 1, 1209600, required=True)
    _op("moderation." + _name, _label, "POST", "/moderation/bans", fields=_fields, scopes=_mod_bans,
        subject="moderator", binding="moderator_query", body_root="data", risk="destructive")
_op("moderation.unban", "Remove ban or timeout", "DELETE", "/moderation/bans", scopes=_mod_bans,
    subject="moderator", binding="moderator_query", fields={"user_id": _id("Target user", required=True)}, query=("user_id",))
_op("moderation.banned.get", "Bans and timeouts", "GET", "/moderation/banned", alternatives=(("moderation:read",), _mod_bans),
    fields={"user_id": _array("User IDs", _id(), 1, 100), **_page()}, query=("user_id", "first", "after"))
_op("moderation.warn", "Warn chat user", "POST", "/moderation/warnings", scopes=("moderator:manage:warnings",),
    subject="moderator", binding="moderator_query", fields={"user_id": _id("Target user", required=True), "reason": _string("Reason", 500, required=True)}, body_root="data", expected=(200,))
_op("moderation.channels.get", "Channels this user moderates", "GET", "/moderation/channels", scopes=("user:read:moderated_channels",),
    binding="user_query", subject="any", fields=_page(), query=("first", "after"))
_op("moderation.moderators.get", "Channel moderators", "GET", "/moderation/moderators", alternatives=(("moderation:read",), ("channel:manage:moderators",)),
    fields={"user_id": _array("User IDs", _id(), 1, 100), **_page()}, query=("user_id", "first", "after"))
for _name, _method in (("add", "POST"), ("remove", "DELETE")):
    _op("moderation.moderator." + _name, _name.title() + " moderator", _method, "/moderation/moderators", scopes=("channel:manage:moderators",),
        fields={"user_id": _id("Target user", required=True)}, query=("user_id",), expected=(204,), risk="privileged")
    _op("moderation.vip." + _name, _name.title() + " VIP", _method, "/channels/vips", scopes=("channel:manage:vips",),
        fields={"user_id": _id("Target user", required=True)}, query=("user_id",), expected=(204,), risk="privileged")
_op("moderation.vips.get", "Channel VIPs", "GET", "/channels/vips", alternatives=(("channel:read:vips",), ("channel:manage:vips",)),
    fields={"user_id": _array("User IDs", _id(), 1, 100), **_page()}, query=("user_id", "first", "after"))
_op("moderation.blocked_terms.get", "Blocked terms", "GET", "/moderation/blocked_terms", alternatives=(("moderator:read:blocked_terms",), ("moderator:manage:blocked_terms",)),
    subject="moderator", binding="moderator_query", fields=_page(), query=("first", "after"))
_op("moderation.blocked_terms.add", "Add blocked term", "POST", "/moderation/blocked_terms", scopes=("moderator:manage:blocked_terms",),
    subject="moderator", binding="moderator_query", fields={"text": _string("Blocked term", 500, required=True, minimum=2)})
_op("moderation.blocked_terms.remove", "Remove blocked term", "DELETE", "/moderation/blocked_terms", scopes=("moderator:manage:blocked_terms",),
    subject="moderator", binding="moderator_query", fields={"id": _opaque("Term ID", required=True)}, query=("id",))
_op("moderation.unban_requests.get", "Unban requests", "GET", "/moderation/unban_requests", alternatives=(("moderator:read:unban_requests",), ("moderator:manage:unban_requests",)),
    subject="moderator", binding="moderator_query", fields={"status": _string("Status", 32, required=True, enum=("pending", "approved", "denied", "acknowledged", "canceled")),
        "user_id": _id("User ID"), **_page()}, query=("status", "user_id", "first", "after"))
_op("moderation.unban_requests.resolve", "Resolve unban request", "PATCH", "/moderation/unban_requests", scopes=("moderator:manage:unban_requests",),
    subject="moderator", binding="moderator_query", fields={"unban_request_id": _opaque("Request ID", required=True),
        "status": _string("Decision", 16, required=True, enum=("approved", "denied")), "resolution_text": _string("Explanation", 500, minimum=0)},
    query=("unban_request_id", "status", "resolution_text"))

_automod_fields = {name: _integer(name.replace("_", " ").title(), 0, 4) for name in (
    "overall_level", "disability", "aggression", "sexuality_sex_or_gender", "misogyny", "bullying", "swearing", "race_ethnicity_or_religion", "sex_based_terms")}
_op("automod.settings.get", "AutoMod settings", "GET", "/moderation/automod/settings", alternatives=(("moderator:read:automod_settings",), ("moderator:manage:automod_settings",)), subject="moderator", binding="moderator_query")
_op("automod.settings.update", "Update AutoMod settings", "PUT", "/moderation/automod/settings", scopes=("moderator:manage:automod_settings",), subject="moderator", binding="moderator_query", fields=_automod_fields, changes=True)
_op("automod.check", "Check messages with AutoMod", "POST", "/moderation/enforcements/status", scopes=("moderation:read",),
    fields={"data": _array("Messages", _object("Message", {"msg_id": _opaque("Message ID", required=True), "msg_text": _string("Message", 500, required=True)}), 1, 100, required=True)}, risk="read", effects=("Tests submitted messages against the channel's AutoMod policy; does not send chat.",))
_op("automod.message.resolve", "Approve or deny held message", "POST", "/moderation/automod/message", scopes=("moderator:manage:automod",), subject="moderator", binding="automod_body",
    fields={"msg_id": _opaque("Held message ID", required=True), "action": _string("Decision", 8, required=True, enum=("ALLOW", "DENY"))}, expected=(204,))
_op("shield.get", "Shield Mode status", "GET", "/moderation/shield_mode", alternatives=(("moderator:read:shield_mode",), ("moderator:manage:shield_mode",)), subject="moderator", binding="moderator_query")
_op("shield.update", "Set Shield Mode", "PUT", "/moderation/shield_mode", scopes=("moderator:manage:shield_mode",), subject="moderator", binding="moderator_query", fields={"is_active": _boolean("Shield active", required=True)}, risk="privileged")
_op("moderation.suspicious.add", "Monitor or restrict suspicious chatter", "POST", "/moderation/suspicious_users", scopes=("moderator:manage:suspicious_users",), subject="moderator", binding="moderator_query",
    fields={"user_id": _id("Target user", required=True), "status": _string("Treatment", 24, required=True, enum=("ACTIVE_MONITORING", "RESTRICTED"))}, risk="privileged")
_op("moderation.suspicious.remove", "Remove suspicious chatter treatment", "DELETE", "/moderation/suspicious_users", scopes=("moderator:manage:suspicious_users",), subject="moderator", binding="moderator_query",
    fields={"user_id": _id("Target user", required=True)}, query=("user_id",), expected=(200,), risk="privileged")
_op("moderation.user_blocks.get", "Connected user's blocked accounts", "GET", "/users/blocks", scopes=("user:read:blocked_users",), fields=_page(), query=("first", "after"))
_op("moderation.user_block.add", "Block an account", "PUT", "/users/blocks", scopes=("user:manage:blocked_users",), binding="none",
    fields={"target_user_id": _id("Target account", required=True), "source_context": _string("Source", 8, enum=("chat", "whisper")), "reason": _string("Reason", 16, enum=("harassment", "spam", "other"))},
    query=("target_user_id", "source_context", "reason"), expected=(204,), effects=("Blocks interactions with the connected account across Twitch.",))
_op("moderation.user_block.remove", "Unblock an account", "DELETE", "/users/blocks", scopes=("user:manage:blocked_users",), binding="none",
    fields={"target_user_id": _id("Target account", required=True)}, query=("target_user_id",))

_op("clip.get", "Channel clips", "GET", "/clips", subject="any", fields={**_page(), "started_at": _time_field("From"), "ended_at": _time_field("Through"), "is_featured": _boolean("Featured only")}, query=("first", "after", "started_at", "ended_at", "is_featured"))
_op("clip.lookup", "Look up channel clips", "GET", "/clips", subject="any", binding="none", fields={"id": _array("Clip IDs", _opaque(), 1, 100, required=True)}, query=("id",))
_op("clip.create", "Create live clip", "POST", "/clips", scopes=("clips:edit",), subject="any", live=True,
    fields={"title": _string("Clip title"), "duration": _number("Duration (seconds)", 5, 60)}, query=("title", "duration"), expected=(202,), response="clip_async")
_op("clip.vod.create", "Create clip from VOD", "POST", "/videos/clips", alternatives=_clip_scopes, subject="editor", binding="editor_query",
    fields={"vod_id": _id("VOD ID", required=True), "vod_offset": _integer("Clip end (seconds)", 5, 2147483647, required=True),
        "duration": _number("Duration (seconds)", 5, 60), "title": _string("Clip title", 140, required=True)},
    query=("vod_id", "vod_offset", "duration", "title"), expected=(202,), resources="video", response="clip_async")
_op("clip.download", "Get authorized clip downloads", "GET", "/clips/downloads", alternatives=_clip_scopes, subject="editor", binding="editor_query",
    fields={"clip_id": _array("Clip IDs", _opaque(), 1, 10, required=True)}, query=("clip_id",), resources="clip_download", risk="content_export",
    response="downloads", effects=("Returns expiring official download links. Reuse requires recorded rights and consent; files are not fetched automatically.",))
_op("video.get", "Published videos", "GET", "/videos", subject="any", binding="broadcaster_user_query", fields={**_page(),
    "type": _string("Video type", 10, enum=("all", "upload", "archive", "highlight")),
    "period": _string("Period", 10, enum=("all", "day", "week", "month")), "sort": _string("Sort", 10, enum=("time", "trending", "views"))}, query=("first", "after", "type", "period", "sort"))
_op("video.delete", "Delete published videos", "DELETE", "/videos", scopes=("channel:manage:videos",), binding="none", fields={"id": _array("Video IDs", _id(), 1, 5, required=True)}, query=("id",), expected=(200,), resources="video", risk="destructive", response="ids")

for _family, _read_scope, _write_scope in (("poll", "channel:read:polls", "channel:manage:polls"), ("prediction", "channel:read:predictions", "channel:manage:predictions")):
    _op(_family + ".get", _family.title() + " history", "GET", "/" + _family + "s", alternatives=((_read_scope,), (_write_scope,)), eligibility="affiliate_or_partner",
        fields={"id": _array("IDs", _opaque(), 1, 100 if _family == "poll" else 25), **_page(20 if _family == "poll" else 25)}, query=("id", "first", "after"))
_op("poll.create", "Create poll", "POST", "/polls", scopes=("channel:manage:polls",), binding="broadcaster_body", eligibility="affiliate_or_partner",
    fields={"title": _string("Question", 60, required=True), "choices": _array("Choices", _choices, 2, 5, required=True),
        "duration": _integer("Duration (seconds)", 15, 1800, required=True), "channel_points_voting_enabled": _boolean("Allow extra Channel Points votes"),
        "channel_points_per_vote": _integer("Points per extra vote", 1, 1000000)}, schedulable=True,
    effects=("The poll starts immediately when dispatched; only one poll can be active.",))
_op("poll.end", "End poll", "PATCH", "/polls", scopes=("channel:manage:polls",), binding="broadcaster_body", eligibility="affiliate_or_partner",
    fields={"id": _opaque("Poll ID", required=True), "status": _string("Result display", 16, required=True, enum=("TERMINATED", "ARCHIVED"))})
_op("prediction.create", "Create prediction", "POST", "/predictions", scopes=("channel:manage:predictions",), binding="broadcaster_body", eligibility="affiliate_or_partner",
    fields={"title": _string("Question", 45, required=True), "outcomes": _array("Outcomes", _choices, 2, 10, required=True), "prediction_window": _integer("Prediction window (seconds)", 30, 1800, required=True)},
    risk="channel_points", schedulable=True, effects=("Starts immediately; viewers commit Channel Points and only one prediction can be active.",))
_op("prediction.end", "Lock, cancel or resolve prediction", "PATCH", "/predictions", scopes=("channel:manage:predictions",), binding="broadcaster_body", eligibility="affiliate_or_partner",
    fields={"id": _opaque("Prediction ID", required=True), "status": _string("Decision", 16, required=True, enum=("LOCKED", "CANCELED", "RESOLVED")), "winning_outcome_id": _opaque("Winning outcome ID")},
    risk="channel_points", effects=("Resolving distributes Channel Points; canceling refunds them.",))
_op("raid.start", "Start raid", "POST", "/raids", scopes=("channel:manage:raids",), binding="from_query", live=True,
    fields={"to_broadcaster_id": _id("Destination channel", required=True)}, query=("to_broadcaster_id",), risk="audience_transfer",
    effects=("Starts the Twitch raid countdown and transfers viewers when the raid proceeds.",))
_op("raid.cancel", "Cancel pending raid", "DELETE", "/raids", scopes=("channel:manage:raids",))

_reward_fields = {"title": _string("Reward title", 45), "prompt": _string("Viewer prompt", 200, minimum=0),
    "cost": _integer("Channel Points cost", 1, 9007199254740991), "is_enabled": _boolean("Enabled"),
    "background_color": _string("Background color", 7, pattern=r"^#[0-9A-Fa-f]{6}$"),
    "is_user_input_required": _boolean("Require viewer input"), "is_max_per_stream_enabled": _boolean("Limit per stream"),
    "max_per_stream": _integer("Per-stream limit", 1, 9007199254740991), "is_max_per_user_per_stream_enabled": _boolean("Limit per user per stream"),
    "max_per_user_per_stream": _integer("Per-user limit", 1, 9007199254740991), "is_global_cooldown_enabled": _boolean("Enable cooldown"),
    "global_cooldown_seconds": _integer("Cooldown (seconds)", 1, 604800), "should_redemptions_skip_request_queue": _boolean("Automatically fulfill redemptions")}
_op("reward.get", "Custom rewards", "GET", "/channel_points/custom_rewards", alternatives=(("channel:read:redemptions",), ("channel:manage:redemptions",)), eligibility="affiliate_or_partner",
    fields={"id": _array("Reward IDs", _opaque(), 1, 50), "only_manageable_rewards": _boolean("Only rewards created by Rafii")}, query=("id", "only_manageable_rewards"))
_op("reward.create", "Create custom reward", "POST", "/channel_points/custom_rewards", scopes=("channel:manage:redemptions",), eligibility="affiliate_or_partner",
    fields={**_reward_fields, "title": _string("Reward title", 45, required=True), "cost": _integer("Channel Points cost", 1, 9007199254740991, required=True)}, risk="channel_points")
_op("reward.update", "Update Rafii-created reward", "PATCH", "/channel_points/custom_rewards", scopes=("channel:manage:redemptions",), eligibility="affiliate_or_partner",
    fields={**_reward_fields, "id": _opaque("Reward ID", required=True), "is_paused": _boolean("Paused"), "is_in_stock": _boolean("In stock")}, query=("id",), resources="reward", changes=True, risk="channel_points", schedulable=True)
_op("reward.delete", "Delete Rafii-created reward", "DELETE", "/channel_points/custom_rewards", scopes=("channel:manage:redemptions",), eligibility="affiliate_or_partner",
    fields={"id": _opaque("Reward ID", required=True)}, query=("id",), resources="reward", risk="destructive",
    effects=("Deleting a reward marks outstanding unfulfilled redemptions fulfilled.",))
_op("redemption.get", "Rafii reward redemptions", "GET", "/channel_points/custom_rewards/redemptions", alternatives=(("channel:read:redemptions",), ("channel:manage:redemptions",)), eligibility="affiliate_or_partner",
    fields={"reward_id": _opaque("Reward ID", required=True), "id": _array("Redemption IDs", _opaque(), 1, 50),
        "status": _string("Status", 16, enum=("CANCELED", "FULFILLED", "UNFULFILLED")), "sort": _string("Order", 8, enum=("OLDEST", "NEWEST")), **_page(50)},
    query=("reward_id", "id", "status", "sort", "first", "after"), resources="reward")
_op("redemption.update", "Fulfill or refund redemptions", "PATCH", "/channel_points/custom_rewards/redemptions", scopes=("channel:manage:redemptions",), eligibility="affiliate_or_partner",
    fields={"reward_id": _opaque("Reward ID", required=True), "id": _array("Redemption IDs", _opaque(), 1, 50, required=True),
        "status": _string("Decision", 16, required=True, enum=("CANCELED", "FULFILLED"))}, query=("reward_id", "id"), resources="reward", risk="channel_points",
    effects=("Only unfulfilled redemptions may be changed; canceled redemptions refund Channel Points.",))

_op("subscription.get", "Broadcaster subscriptions", "GET", "/subscriptions", scopes=("channel:read:subscriptions",), eligibility="affiliate_or_partner",
    fields={"user_id": _array("Subscriber IDs", _id(), 1, 100), **_page()}, query=("user_id", "first", "after"), analytics="subscription_snapshot")
_op("subscription.check", "Check this user's subscription", "GET", "/subscriptions/user", scopes=("user:read:subscriptions",), subject="any", binding="subscription_query", eligibility="affiliate_or_partner")
_op("bits.leaderboard.get", "Bits leaderboard", "GET", "/bits/leaderboard", scopes=("bits:read",), binding="none",
    fields={"count": _integer("Results", 1, 100), "period": _string("Period", 8, enum=("day", "week", "month", "year", "all")),
        "started_at": _time_field("Period starts"), "user_id": _id("User ID")}, query=("count", "period", "started_at", "user_id"), analytics="bits_leaderboard")
_op("bits.cheermotes.get", "Channel Cheermotes", "GET", "/bits/cheermotes", subject="any")
_op("bits.powerups.get", "Custom Bits Power-ups", "GET", "/bits/custom_power_ups", scopes=("bits:read",), eligibility="affiliate_or_partner",
    fields={"id": _array("Power-up IDs", _opaque(), 1, 50)}, query=("id",))
_op("hype_train.get", "Hype Train status", "GET", "/hypetrain/status", scopes=("channel:read:hype_train",))
_op("ads.schedule.get", "Ad schedule", "GET", "/channels/ads", scopes=("channel:read:ads",), eligibility="affiliate_or_partner")
_op("ads.snooze", "Snooze next ad", "POST", "/channels/ads/schedule/snooze", scopes=("channel:manage:ads",), eligibility="affiliate_or_partner", risk="monetization")
_op("ads.commercial.start", "Run commercial", "POST", "/channels/commercial", scopes=("channel:edit:commercial",), binding="broadcaster_body", eligibility="affiliate_or_partner", live=True,
    fields={"length": _integer("Commercial length (seconds)", 30, 180, required=True, enum=(30, 60, 90, 120, 150, 180))}, risk="monetization")
_op("goals.get", "Creator goals", "GET", "/goals", scopes=("channel:read:goals",))
_op("charity.get", "Current charity campaign", "GET", "/charity/campaigns", scopes=("channel:read:charity",))
_op("charity.donations.get", "Charity donations", "GET", "/charity/donations", scopes=("channel:read:charity",), fields=_page(), query=("first", "after"))

_op("analytics.stream.snapshot", "Live viewer snapshot", "GET", "/streams", binding="broadcaster_user_query", analytics="live_viewer_snapshot",
    effects=("viewer_count is a live snapshot, not unique viewers, watch time or retention.",))
_op("analytics.clips.snapshot", "Clip view snapshots", "GET", "/clips", fields=_page(), query=("first", "after"), analytics="clip_view_snapshot")
_op("analytics.videos.snapshot", "Video view snapshots", "GET", "/videos", binding="broadcaster_user_query", fields=_page(), query=("first", "after"), analytics="video_view_snapshot")
for _kind in ("extensions", "games"):
    _singular = "extension" if _kind == "extensions" else "game"
    _key = _singular + "_id"
    _op("analytics." + _singular + ".get", _singular.title() + " developer report", "GET", "/analytics/" + _kind,
        scopes=("analytics:read:" + _kind,), binding="none", fields={_key: _opaque(_singular.title() + " ID", required=True),
            "started_at": _time_field("From"), "ended_at": _time_field("Through"), **_page()},
        query=(_key, "started_at", "ended_at", "first", "after"), analytics="owned_" + _singular + "_report",
        effects=("Requires ownership of the requested developer resource; this is not broadcaster Creator Dashboard analytics.",))

OPERATIONS = MappingProxyType(_registry)
CAPABILITIES = OPERATIONS
del _registry

UNSUPPORTED = MappingProxyType({
    "twitch.post.text": "Twitch has no general social-feed text-post endpoint.",
    "twitch.stream.start": "Starting an encoder is separate from Helix stream schedules.",
    "twitch.video.upload": "No general Helix VOD upload endpoint is documented.",
    "twitch.video.download": "No general Helix full-VOD download endpoint is documented; authorized clip downloads are supported.",
    "twitch.analytics.dashboard": "Creator Dashboard revenue, retention, watch time and unique viewers are not exposed by the documented general Helix API.",
    "twitch.channel_points.grant": "No arbitrary Channel Points balance or point-grant endpoint is documented.",
    "twitch.subscription.purchase": "Subscriptions are read/notification capabilities; this adapter does not purchase subscriptions.",
    "twitch.chat.history": "Live chat is received through EventSub; Helix does not provide an arbitrary historical-chat archive.",
})


def operation_scopes(action):
    """Each inner list is required in full; outer lists are alternatives."""
    if action not in OPERATIONS:
        _deny("unsupported_operation", status=422)
    return [list(option) for option in OPERATIONS[action].scope_options]


def validate_operation_payload(action, payload):
    """Validate shapes before any service preflight; this grants no permission."""
    if not isinstance(action, str) or action not in OPERATIONS:
        _deny("unsupported_operation", status=422)
    return _validate_payload(payload, OPERATIONS[action].fields)


def resource_ids_for_operation(action, payload):
    """Return only validated IDs used by the operation's required preflight."""
    clean = validate_operation_payload(action, payload)
    return _resource_ids(OPERATIONS[action], clean)


def union_supported_scopes():
    """OAuth allowlist only. Never request this whole set by default."""
    return frozenset(scope for op in OPERATIONS.values()
                     for option in op.scope_options for scope in option)


@dataclass(frozen=True)
class RoleEvidence:
    """A service-created role proof; never deserialize this from an HTTP body.

    A permission scope alone is not a moderator/editor role. Refresh a provider
    role lookup within five minutes and again when an upstream role denial occurs.
    """

    subject_id: str
    broadcaster_id: str
    roles: frozenset
    checked_at: float
    expires_at: float


@dataclass(frozen=True)
class RightsEvidence:
    """Fresh owner/creator-app proof plus separately recorded content consent.

    ``ownership_verified`` refers to provider resource ownership, not copyright.
    ``reuse_authorized`` is the user's explicit rights assertion. The service's
    commercial/storage gate supplies ``storage_authorized``. The three must not
    be collapsed into one boolean or inferred from a granted OAuth scope.
    ``metadata_json`` contains only normalized facts needed for the exact action.
    """

    subject_id: str
    broadcaster_id: str
    resource_kind: str
    resource_ids: tuple
    client_id: str
    checked_at: float
    expires_at: float
    ownership_verified: bool = False
    creator_app_verified: bool = False
    reuse_authorized: bool = False
    storage_authorized: bool = False
    metadata_json: str = "{}"

    @property
    def metadata(self):
        try:
            value = json.loads(self.metadata_json)
        except (TypeError, ValueError):
            _deny("invalid_rights_evidence", status=403)
        if not isinstance(value, dict):
            _deny("invalid_rights_evidence", status=403)
        return value


def _fresh(evidence, subject_id, broadcaster_id, now):
    if evidence.subject_id != subject_id or evidence.broadcaster_id != broadcaster_id:
        _deny("evidence_identity_mismatch", status=403)
    checked = _clock(evidence.checked_at)
    expires = _clock(evidence.expires_at)
    if checked > now or expires <= now or not 0 < expires - checked <= EVIDENCE_TTL:
        _deny("evidence_expired", status=403)
    return expires


def _scope_set(scopes):
    if not isinstance(scopes, (tuple, list, set, frozenset)) or any(
            not isinstance(scope, str) or re.fullmatch(r"[a-z_:]{1,100}", scope) is None
            for scope in scopes):
        _deny("invalid_scope_evidence", status=403)
    return frozenset(scopes)


def _has_scope(op, scopes):
    return any(set(option) <= scopes for option in op.scope_options)


def _authorize(op, subject_id, broadcaster_id, scopes, roles, account_type, live, now):
    _uid(subject_id)
    _uid(broadcaster_id)
    scopes = _scope_set(scopes)
    if not _has_scope(op, scopes):
        _deny("missing_scope", status=403)
    if account_type not in ("", "affiliate", "partner") or type(live) is not bool:
        _deny("invalid_account_evidence", status=403)
    expires = now + EVIDENCE_TTL
    owner = subject_id == broadcaster_id
    if op.subject_policy == "broadcaster" and not owner:
        _deny("broadcaster_token_required", status=403)
    if op.subject_policy in ("moderator", "editor") and not owner:
        if type(roles) is not RoleEvidence:
            _deny("verified_role_required", status=403)
        if not isinstance(roles.roles, frozenset) or not roles.roles <= {"moderator", "editor"}:
            _deny("invalid_role_evidence", status=403)
        expires = min(expires, _fresh(roles, subject_id, broadcaster_id, now))
        if op.subject_policy not in roles.roles:
            _deny("role_required", status=403)
    if op.eligibility == "affiliate_or_partner" and account_type not in ("affiliate", "partner"):
        _deny("affiliate_or_partner_required", status=403)
    if op.requires_live and not live:
        _deny("live_broadcast_required", status=409)
    if op.action in ("twitch.clip.vod.create", "twitch.clip.download"):
        # These permissions describe different token subjects, not interchangeable
        # privileges that a caller may pick merely to bypass an owner/editor gate.
        needed = "channel:manage:clips" if owner else "editor:manage:clips"
        if needed not in scopes:
            _deny("clip_subject_scope_required", status=403)
    return expires


def _paired(payload, flag, amount):
    if flag in payload and payload[flag] is True and amount not in payload:
        _deny("enabled_setting_requires_value")
    if amount in payload and payload.get(flag) is not True:
        _deny("setting_value_requires_enabled_flag")


def _dates(payload, start="started_at", end="ended_at", *, paired=False):
    if paired and (start in payload) != (end in payload):
        _deny("date_range_requires_both_bounds")
    if start in payload and end in payload:
        begin = datetime.fromisoformat(payload[start].replace("Z", "+00:00"))
        finish = datetime.fromisoformat(payload[end].replace("Z", "+00:00"))
        if begin >= finish:
            _deny("invalid_date_range")


def _resource_ids(op, payload):
    if op.resource_policy == "clip_download":
        return "clip", tuple(payload["clip_id"])
    if op.resource_policy == "video":
        return "video", (payload["vod_id"],) if "vod_id" in payload else tuple(payload["id"])
    if op.resource_policy == "reward":
        return "reward", (payload.get("reward_id", payload.get("id")),)
    if op.resource_policy == "schedule":
        return "schedule", (payload["id"],)
    if op.resource_policy == "marker_settings":
        return "marker_settings", ()
    return "", ()


def _rights(op, payload, rights, subject_id, broadcaster_id, now):
    if not op.resource_policy:
        return now + EVIDENCE_TTL, "", {}
    if type(rights) is not RightsEvidence:
        _deny("resource_evidence_required", status=403)
    expires = _fresh(rights, subject_id, broadcaster_id, now)
    kind, ids = _resource_ids(op, payload)
    if (rights.resource_kind != kind or not isinstance(rights.resource_ids, tuple) or
            not all(isinstance(value, str) for value in rights.resource_ids) or
            not set(ids) <= set(rights.resource_ids)):
        _deny("resource_evidence_mismatch", status=403)
    if any(type(value) is not bool for value in (rights.ownership_verified,
            rights.creator_app_verified, rights.reuse_authorized, rights.storage_authorized)):
        _deny("invalid_rights_evidence", status=403)
    if not rights.ownership_verified:
        _deny("resource_ownership_required", status=403)
    if not isinstance(rights.client_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", rights.client_id) is None:
        _deny("invalid_rights_evidence", status=403)
    metadata = rights.metadata
    if kind == "reward" and not rights.creator_app_verified:
        _deny("creator_app_ownership_required", status=403)
    if op.resource_policy == "clip_download" and not (rights.reuse_authorized and rights.storage_authorized):
        _deny("content_reuse_and_storage_authorization_required", status=403)
    if kind == "marker_settings" and (metadata.get("past_broadcasts_enabled") is not True or
                                      metadata.get("broadcast_type") != "live"):
        _deny("past_broadcast_storage_required", status=409)
    if kind == "schedule":
        resources = metadata.get("resources", {})
        if not isinstance(resources, dict) or not isinstance(resources.get(ids[0]), dict) or type(resources[ids[0]].get("is_recurring")) is not bool:
            _deny("schedule_series_evidence_required", status=403)
    # Only semantic consent/ownership facts enter the approved manifest. Expiry
    # remains private so a fresh identical preflight does not invalidate approval.
    semantic = {"resource_kind": kind, "resource_ids": list(ids),
                "ownership_verified": True, "client_id": rights.client_id}
    if kind == "reward":
        semantic["creator_app_verified"] = True
    if op.resource_policy == "clip_download":
        semantic.update(reuse_authorized=True, storage_authorized=True)
    if kind == "schedule":
        semantic["is_recurring"] = metadata["resources"][ids[0]]["is_recurring"]
    if kind == "marker_settings":
        semantic.update(past_broadcasts_enabled=True, broadcast_type="live")
    return expires, rights.client_id, semantic


def _conditions(op, payload, subject_id, broadcaster_id, account_type, semantic_rights):
    if op.mutation_fields_required and not (payload.keys() - set(op.query_fields)):
        _deny("empty_update")
    _dates(payload)
    if op.action.startswith("twitch.analytics.") and op.analytics_kind.startswith("owned_"):
        _dates(payload, paired=True)
    if op.action == "twitch.channel.update":
        if "delay" in payload and account_type != "partner":
            _deny("partner_required", status=403)
        if "tags" in payload and len({tag.casefold() for tag in payload["tags"]}) != len(payload["tags"]):
            _deny("duplicate_tags")
        if "content_classification_labels" in payload:
            labels = [label["id"] for label in payload["content_classification_labels"]]
            if len(set(labels)) != len(labels):
                _deny("duplicate_content_labels")
    if op.action == "twitch.schedule.create" and not payload["is_recurring"] and account_type not in ("affiliate", "partner"):
        _deny("one_time_schedule_eligibility_required", status=403)
    if op.action == "twitch.schedule.update":
        if semantic_rights.get("is_recurring") is True and "start_time" in payload:
            _deny("recurring_start_time_not_editable")
        if semantic_rights.get("is_recurring") is False and {"start_time", "duration"} & payload.keys() and account_type not in ("affiliate", "partner"):
            _deny("one_time_schedule_eligibility_required", status=403)
    if op.action == "twitch.schedule.settings.update":
        keys = {"vacation_start_time", "vacation_end_time", "timezone"}
        if payload["is_vacation_enabled"] is True:
            if not keys <= payload.keys():
                _deny("vacation_bounds_required")
            _dates(payload, "vacation_start_time", "vacation_end_time", paired=True)
        elif payload.keys() & keys:
            _deny("disabled_vacation_has_bounds")
    if op.action == "twitch.chat.settings.update":
        for flag, amount in (("follower_mode", "follower_mode_duration"),
                             ("slow_mode", "slow_mode_wait_time"),
                             ("non_moderator_chat_delay", "non_moderator_chat_delay_duration")):
            # Twitch has defaults when enabling a mode; only require the flag
            # when a new explicit limit is supplied.
            if amount in payload and payload.get(flag) is not True:
                _deny("setting_value_requires_enabled_flag")
    if op.action == "twitch.automod.settings.update" and "overall_level" in payload and len(payload) > 1:
        _deny("automod_level_and_categories_exclusive")
    if op.action in ("twitch.moderation.ban", "twitch.moderation.timeout", "twitch.moderation.warn") and payload["user_id"] in (subject_id, broadcaster_id):
        _deny("cannot_moderate_broadcaster_or_self")
    if op.action in ("twitch.chat.shoutout.send", "twitch.raid.start") and payload["to_broadcaster_id"] == broadcaster_id:
        _deny("destination_must_be_other_channel")
    if op.action == "twitch.chat.whisper.send" and payload["to_user_id"] == subject_id:
        _deny("whisper_recipient_must_be_other_user")
    if op.action.startswith("twitch.moderation.user_block.") and payload["target_user_id"] == subject_id:
        _deny("cannot_block_self")
    if op.action == "twitch.clip.vod.create" and payload["vod_offset"] < payload.get("duration", 30):
        _deny("clip_offset_before_duration")
    if op.action == "twitch.poll.create":
        _paired(payload, "channel_points_voting_enabled", "channel_points_per_vote")
        choices = [choice["title"].casefold() for choice in payload["choices"]]
        if len(set(choices)) != len(choices):
            _deny("duplicate_choices")
    if op.action == "twitch.prediction.create":
        choices = [choice["title"].casefold() for choice in payload["outcomes"]]
        if len(set(choices)) != len(choices):
            _deny("duplicate_choices")
    if op.action == "twitch.prediction.end":
        if (payload["status"] == "RESOLVED") != ("winning_outcome_id" in payload):
            _deny("prediction_winner_condition_failed")
    if op.action in ("twitch.reward.create", "twitch.reward.update"):
        for flag, amount in (("is_max_per_stream_enabled", "max_per_stream"),
                ("is_max_per_user_per_stream_enabled", "max_per_user_per_stream"),
                ("is_global_cooldown_enabled", "global_cooldown_seconds")):
            _paired(payload, flag, amount)
    if op.action == "twitch.redemption.get" and "id" not in payload and "status" not in payload:
        _deny("redemption_status_or_ids_required")
    if op.action == "twitch.bits.leaderboard.get" and "started_at" in payload and payload.get("period", "all") == "all":
        _deny("bits_period_required_for_start")


def _bind(op, payload, subject_id, broadcaster_id):
    query = {key: value for key, value in payload.items() if key in op.query_fields or op.method == "GET"}
    body = {key: value for key, value in payload.items() if key not in query}
    binding = op.binding
    if binding in ("broadcaster_query", "moderator_query", "editor_query", "shoutout_query"):
        query["from_broadcaster_id" if binding == "shoutout_query" else "broadcaster_id"] = broadcaster_id
    if binding in ("moderator_query", "shoutout_query"):
        query["moderator_id"] = subject_id
    if binding == "editor_query":
        query["editor_id"] = subject_id
    if binding in ("broadcaster_user_query", "user_query"):
        query["user_id"] = broadcaster_id if binding == "broadcaster_user_query" else subject_id
    if binding == "from_query":
        query["from_broadcaster_id"] = broadcaster_id
    if binding == "whisper_query":
        query["from_user_id"] = subject_id
    if binding == "subscription_query":
        query.update(broadcaster_id=broadcaster_id, user_id=subject_id)
    if binding == "marker_query" and "video_id" not in payload:
        query["user_id"] = broadcaster_id
    if binding in ("broadcaster_body", "chat_body"):
        body["broadcaster_id"] = broadcaster_id
    if binding == "chat_body":
        body["sender_id"] = subject_id
    if binding in ("marker_body", "automod_body"):
        body["user_id"] = broadcaster_id if binding == "marker_body" else subject_id
    if op.action in ("twitch.schedule.create", "twitch.schedule.update") and "duration" in body:
        body["duration"] = str(body["duration"])
    if op.body_root:
        body = {op.body_root: body}
    return query, body or None


@dataclass(frozen=True)
class PreparedOperation(Mapping):
    """Immutable, time-limited internal command with a stable approval digest."""

    _semantic_json: str
    _expires_at: float
    _client_id: str = ""
    _seal: object = field(default=None, repr=False, compare=False)
    _signature: str = field(default="", repr=False, compare=False)

    def as_dict(self):
        return json.loads(self._semantic_json)

    def __getitem__(self, key):
        return self.as_dict()[key]

    def __iter__(self):
        return iter(self.as_dict())

    def __len__(self):
        return len(self.as_dict())

    @property
    def payload_sha256(self):
        return hashlib.sha256(self._semantic_json.encode("utf-8")).hexdigest()

    @property
    def action(self):
        return self["action"]

    @property
    def method(self):
        return self["method"]

    @property
    def path(self):
        return self["path"]

    @property
    def query(self):
        return self["query"]

    @property
    def body(self):
        return self["body"]

    @property
    def payload(self):
        return self["payload"]

    @property
    def write(self):
        return self["write"]

    @property
    def risk(self):
        return self["risk"]

    @property
    def subject_id(self):
        return self["subject_id"]

    @property
    def broadcaster_id(self):
        return self["broadcaster_id"]


def prepare_operation(action, payload, *, subject_id, broadcaster_id, scopes,
                      roles=(), account_type="", live=False, rights=None, now=None):
    """Normalize an exact operation using trusted server-side authorization facts."""
    if not isinstance(action, str) or action not in OPERATIONS:
        _deny("unsupported_operation", status=422)
    now = _clock(now)
    op = OPERATIONS[action]
    expires = _authorize(op, subject_id, broadcaster_id, scopes, roles, account_type, live, now)
    clean = _validate_payload(payload, op.fields)
    rights_expires, client_id, semantic_rights = _rights(op, clean, rights, subject_id, broadcaster_id, now)
    expires = min(expires, rights_expires)
    _conditions(op, clean, subject_id, broadcaster_id, account_type, semantic_rights)
    query, body = _bind(op, clean, subject_id, broadcaster_id)
    semantic = {"action": action, "method": op.method, "path": op.path,
                "query": query, "body": body, "payload": clean, "write": op.write,
                "risk": op.risk, "effects": list(op.effects), "subject_id": subject_id,
                "broadcaster_id": broadcaster_id}
    if semantic_rights:
        semantic["rights"] = semantic_rights
    encoded = _json(semantic)
    signature = _sign_manifest(encoded, expires, client_id)
    return PreparedOperation(encoded, expires, client_id, _SEAL, signature)


def _sign_manifest(encoded, expires, client_id):
    message = _json([encoded, expires, client_id]).encode("utf-8")
    return hmac.new(_MANIFEST_KEY, message, hashlib.sha256).hexdigest()


def capabilities(*, subject_id=None, broadcaster_id=None, scopes=(), roles=(),
                 account_type="", live=False, now=None):
    """JSON-native form/consent catalog. Offline implementation is not live proof."""
    result = []
    instant = _clock(now)
    for op in OPERATIONS.values():
        reasons = []
        if subject_id is None or broadcaster_id is None:
            reasons.append("connection_required")
        else:
            try:
                _authorize(op, subject_id, broadcaster_id, scopes, roles, account_type, live, instant)
            except TwitchNativeError as error:
                reasons.append(error.reason)
        # Payload-specific ownership and rights are checked by prepare_operation;
        # the catalog explains the gate without claiming an unperformed preflight.
        gates = []
        if op.resource_policy:
            gates.append(op.resource_policy + "_evidence_required")
        if op.risk == "secret":
            reasons.append("interactive_secret_handler_required")
        result.append({"action": op.action, "label": op.label, "group": op.group,
            "method": op.method, "path": op.path, "write": op.write,
            "requiredScopes": operation_scopes(op.action), "fields": op.fields,
            "subjectPolicy": op.subject_policy, "eligibility": op.eligibility,
            "requiresLive": op.requires_live, "risk": op.risk,
            "effects": list(op.effects), "schedulable": op.schedulable,
            "gates": gates, "status": "implemented_offline", "liveVerified": False,
            "verification": "unverified", "availability": {
                "state": "blocked" if reasons else "available", "reasons": reasons},
            "source": REFERENCE})
    return result


def _url(path, query):
    if not isinstance(path, str) or re.fullmatch(r"/[a-z_]+(?:/[a-z_]+)*", path) is None:
        _deny("invalid_provider_path", status=500)
    pairs = []
    for key in sorted(query):
        values = query[key] if isinstance(query[key], list) else [query[key]]
        for value in values:
            if type(value) is bool:
                value = "true" if value else "false"
            pairs.append((key, value))
    encoded = urlencode(pairs)
    return HELIX + path + ("?" + encoded if encoded else "")


def _call(transport, client_id, access_token, method, path, query, body, *, write, expected):
    _credentials(client_id, access_token)
    if not callable(transport):
        _deny("transport_required", status=500)
    try:
        response = transport(method, _url(path, query), headers={
            "Client-Id": client_id, "Authorization": "Bearer " + access_token,
            "Accept": "text/calendar" if path == "/schedule/icalendar" else "application/json"}, body=body)
    except Exception:
        _deny("provider_unreachable", status=502, unknown_result=write, retryable=not write)
    if not isinstance(response, dict) or type(response.get("status")) is not int:
        _deny("invalid_provider_response", status=502, unknown_result=write)
    status = response["status"]
    if status not in expected:
        if status == 401:
            _deny("token_invalid_or_revoked", status=401, provider_status=status)
        if status == 403:
            _deny("provider_permission_or_eligibility_denied", status=403, provider_status=status)
        if status == 429:
            _deny("provider_rate_limited", status=429, retryable=True, provider_status=status)
        if 400 <= status < 500 and status != 408:
            _deny("provider_rejected_operation", status=409 if write else 422, provider_status=status)
        _deny("provider_result_unknown" if write else "provider_unavailable", status=502,
              unknown_result=write, retryable=not write, provider_status=status)
    if status == 204:
        return status, {}
    payload = response.get("body")
    try:
        size = len(_json(payload).encode("utf-8"))
    except TwitchNativeError:
        _deny("invalid_provider_response", status=502, unknown_result=write, provider_status=status)
    if not isinstance(payload, dict) or size > RESPONSE_LIMIT:
        _deny("invalid_provider_response", status=502, unknown_result=write, provider_status=status)
    return status, payload


_REDACT_KEYS = frozenset({"access_token", "refresh_token", "client_secret", "stream_key",
                        "authorization", "password", "email", "cookie", "set-cookie"})


def _redact(value, access_token, depth=0):
    if depth > 24:
        _deny("provider_response_too_deep", status=502)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            _deny("invalid_provider_response", status=502)
        return {key: _redact(item, access_token, depth + 1)
                for key, item in value.items() if key.lower() not in _REDACT_KEYS}
    if isinstance(value, list):
        return [_redact(item, access_token, depth + 1) for item in value]
    if isinstance(value, str):
        return value.replace(access_token, "[redacted]") if access_token in value else value
    return value


def _rows(payload, *, write=False):
    data = payload.get("data")
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        _deny("invalid_provider_response", status=502, unknown_result=write)
    return data


def _check_owners(op, data, broadcaster_id, payload):
    rows = data if isinstance(data, list) else [data]
    for row in rows:
        if not isinstance(row, dict):
            continue
        if op.action not in ("twitch.channel.followed.get", "twitch.stream.followed.get", "twitch.moderation.channels.get") and "broadcaster_id" in row and row["broadcaster_id"] != broadcaster_id:
            _deny("provider_resource_identity_mismatch", status=502, unknown_result=op.write)
        if op.path in ("/channels", "/clips", "/schedule", "/schedule/segment") and op.response_shape not in ("clip_async",) and row.get("broadcaster_id") != broadcaster_id:
            _deny("provider_resource_identity_mismatch", status=502, unknown_result=op.write)
        if op.path in ("/videos", "/streams") and row.get("user_id") != broadcaster_id:
            _deny("provider_resource_identity_mismatch", status=502, unknown_result=op.write)
        if op.action == "twitch.marker.get" and row.get("user_id") != broadcaster_id:
            _deny("provider_resource_identity_mismatch", status=502)
        if op.path == "/users" and row.get("id") != broadcaster_id:
            _deny("provider_resource_identity_mismatch", status=502, unknown_result=op.write)
        if op.action == "twitch.clip.lookup" and (row.get("broadcaster_id") != broadcaster_id or row.get("id") not in payload["id"]):
            _deny("provider_resource_identity_mismatch", status=502)
        if op.action.startswith("twitch.analytics.") and op.analytics_kind.startswith("owned_"):
            key = "extension_id" if "extension" in op.analytics_kind else "game_id"
            if row.get(key) != payload[key]:
                _deny("provider_resource_identity_mismatch", status=502)


def _download_url(value):
    if value is None or value == "":
        return value
    if not isinstance(value, str) or len(value) > 8192:
        _deny("invalid_download_link", status=502)
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        allowed = host == "twitch.tv" or host.endswith(".twitch.tv") or host == "twitchcdn.net" or host.endswith(".twitchcdn.net") or host == "ttvnw.net" or host.endswith(".ttvnw.net")
        if (parts.scheme != "https" or not allowed or parts.username or parts.password or
                parts.port not in (None, 443) or parts.fragment or "\\" in value or
                any(ord(c) < 33 for c in value)):
            raise ValueError
    except ValueError:
        _deny("invalid_download_link", status=502)
    return value


def _manifest(manifest, client_id, now):
    if type(manifest) is not PreparedOperation or manifest._seal is not _SEAL:
        _deny("prepared_operation_required", status=403)
    if not isinstance(manifest._signature, str) or not hmac.compare_digest(
            manifest._signature, _sign_manifest(manifest._semantic_json, manifest._expires_at, manifest._client_id)):
        _deny("prepared_operation_tampered", status=403)
    if manifest._expires_at <= now:
        _deny("prepared_operation_expired", status=403)
    if manifest._client_id and manifest._client_id != client_id:
        _deny("resource_client_mismatch", status=403)
    op = OPERATIONS.get(manifest.action)
    if op is None or manifest.path != op.path or manifest.method != op.method or manifest.write != op.write:
        _deny("prepared_operation_tampered", status=403)
    return op


def execute(client_id, access_token, manifest, transport, *, now=None):
    """Dispatch exactly once. Unknown writes need reconciliation, never replay."""
    now = _clock(now)
    op = _manifest(manifest, client_id, now)
    if op.risk == "secret":
        _deny("interactive_secret_handler_required", status=403)
    status, payload = _call(transport, client_id, access_token, op.method, op.path,
                           manifest.query, manifest.body, write=op.write, expected=op.expected)
    result = {"action": op.action, "status": "accepted" if status == 202 else "confirmed",
              "confirmed": status != 202, "providerStatus": status}
    if status == 204:
        result["data"] = []
        if op.response_shape == "whisper":
            result.update(status="accepted", confirmed=False, deliveryVerified=False)
        return result
    if op.response_shape == "calendar":
        calendar = payload.get("raw")
        if not isinstance(calendar, str) or not calendar.startswith("BEGIN:VCALENDAR") or not calendar.rstrip().endswith("END:VCALENDAR"):
            _deny("incomplete_calendar_response", status=502)
        result["data"] = {"contentType": "text/calendar", "calendar": calendar}
        return result
    if op.response_shape == "object":
        data = payload.get("data")
        if not isinstance(data, dict):
            _deny("invalid_provider_response", status=502, unknown_result=op.write)
    elif op.response_shape == "ids":
        data = payload.get("data")
        if not isinstance(data, list) or not all(isinstance(item, str) and item in manifest.payload["id"] for item in data):
            _deny("invalid_provider_response", status=502, unknown_result=op.write)
        if set(data) != set(manifest.payload["id"]):
            result.update(status="partial", confirmed=False)
    else:
        data = _rows(payload, write=op.write)
    if op.write and not data:
        _deny("write_result_unknown", status=502, unknown_result=True)
    _check_owners(op, data, manifest.broadcaster_id, manifest.payload)
    if op.path == "/users":
        data = [{key: value for key, value in row.items() if key != "view_count"} for row in data]
    if op.action == "twitch.channel.followers.total":
        if type(payload.get("total")) is not int or payload["total"] < 0:
            _deny("invalid_provider_response", status=502)
        data = []
    if op.response_shape == "chat":
        if len(data) != 1 or type(data[0].get("is_sent")) is not bool:
            _deny("chat_result_unknown", status=502, unknown_result=True)
        if data[0]["is_sent"] is False:
            _deny("chat_message_not_sent", status=409)
        if not isinstance(data[0].get("message_id"), str) or not data[0]["message_id"]:
            _deny("chat_result_unknown", status=502, unknown_result=True)
    if op.response_shape == "clip_async":
        if len(data) != 1 or not isinstance(data[0].get("id"), str) or not data[0]["id"]:
            _deny("clip_result_unknown", status=502, unknown_result=True)
        result["confirmation"] = {"action": "twitch.clip.lookup", "payload": {"id": [data[0]["id"]]},
                                  "deadlineSeconds": 60, "automaticRetry": False}
    if op.action == "twitch.clip.lookup":
        found = {row["id"] for row in data}
        requested = manifest.payload["id"]
        result["resourceVerification"] = {"foundIds": [value for value in requested if value in found],
            "missingIds": [value for value in requested if value not in found], "creationConfirmed": set(requested) <= found}
    if op.response_shape == "downloads":
        seen = set()
        for row in data:
            if row.get("clip_id") not in manifest.payload["clip_id"] or row.get("clip_id") in seen:
                _deny("provider_resource_identity_mismatch", status=502)
            seen.add(row["clip_id"])
            for key in ("landscape_download_url", "portrait_download_url"):
                _download_url(row.get(key))
        result["contentRights"] = {"reuseAuthorized": True, "storageAuthorized": True,
                                  "linksExpire": True, "filesFetched": False}
    try:
        result["data"] = _redact(data, access_token)
        for key in ("pagination", "total", "points", "date_range", "template"):
            if key in payload:
                result[key] = _redact(payload[key], access_token)
    except TwitchNativeError:
        _deny("invalid_provider_response", status=502, unknown_result=op.write)
    if op.analytics_kind:
        result["provenance"] = {"source": "Twitch Helix", "endpoint": op.path,
            "kind": op.analytics_kind, "observedAt": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "estimated": False, "creatorDashboard": False,
            "unavailableMetrics": ["creator_revenue", "unique_viewers", "watch_time", "retention"]}
    return result


def execute_sensitive(client_id, access_token, manifest, transport, *, secret_sink, now=None):
    """Use only after the service's fresh interactive session/approval gate.

    The sink may send the key to the user's secure encoder setup or one-time UI;
    it must not enqueue/log it or feed it to an AI agent. This function never
    returns the key, even when a sink fails.
    """
    op = _manifest(manifest, client_id, _clock(now))
    if op.action != "twitch.stream.key.get" or not callable(secret_sink):
        _deny("secure_secret_sink_required", status=403)
    _, response = _call(transport, client_id, access_token, "GET", "/streams/key",
                        manifest.query, None, write=False, expected=(200,))
    data = _rows(response)
    if len(data) != 1 or not isinstance(data[0].get("stream_key"), str) or not 1 <= len(data[0]["stream_key"]) <= 8192:
        _deny("invalid_provider_response", status=502)
    try:
        secret_sink(data[0]["stream_key"])
    except Exception:
        _deny("secure_secret_delivery_failed", status=502)
    return {"action": op.action, "status": "confirmed", "confirmed": True,
            "data": {"deliveredToSecureSink": True}}


def verify_roles(*, client_id, access_token, subject_id, broadcaster_id, scopes,
                 transport, role="moderator", now=None, broadcaster_access_token=None,
                 broadcaster_scopes=()):
    """Bounded official read preflight; no role is inferred from scopes alone."""
    now = _clock(now)
    _uid(subject_id)
    _uid(broadcaster_id)
    if role not in ("moderator", "editor"):
        _deny("unsupported_role")
    if subject_id == broadcaster_id:
        return RoleEvidence(subject_id, broadcaster_id, frozenset({role}), now, now + EVIDENCE_TTL)
    if role == "editor":
        if broadcaster_access_token is None or "channel:read:editors" not in _scope_set(broadcaster_scopes):
            _deny("broadcaster_editor_lookup_grant_required", status=403)
        # The caller must validate that this separate token belongs to broadcaster_id.
        _, response = _call(transport, client_id, broadcaster_access_token, "GET", "/channels/editors",
                            {"broadcaster_id": broadcaster_id}, None, write=False, expected=(200,))
        if not any(row.get("user_id") == subject_id for row in _rows(response)):
            _deny("role_required", status=403)
    else:
        if "user:read:moderated_channels" not in _scope_set(scopes):
            _deny("role_lookup_scope_required", status=403)
        cursor, seen = None, set()
        for _ in range(10):
            query = {"user_id": subject_id, "first": 100}
            if cursor:
                query["after"] = cursor
            _, response = _call(transport, client_id, access_token, "GET", "/moderation/channels",
                                query, None, write=False, expected=(200,))
            if any(row.get("broadcaster_id") == broadcaster_id for row in _rows(response)):
                break
            pagination = response.get("pagination", {})
            cursor = pagination.get("cursor") if isinstance(pagination, dict) else None
            if not isinstance(cursor, str) or not cursor or cursor in seen or len(cursor) > 512:
                _deny("role_required", status=403)
            seen.add(cursor)
        else:
            _deny("role_lookup_page_limit", status=403)
    return RoleEvidence(subject_id, broadcaster_id, frozenset({role}), now, now + EVIDENCE_TTL)


def verify_resource_access(kind, resource_ids, *, client_id, access_token, subject_id,
                           broadcaster_id, scopes, transport, now=None,
                           reuse_authorized=False, storage_authorized=False):
    """Provider preflight proves channel/creator-app ownership, never copyright.

    Reuse/storage booleans may only come from recorded exact-action user consent
    and service configuration. Passing true here does not create that consent.
    """
    now = _clock(now)
    _uid(subject_id)
    _uid(broadcaster_id)
    _scope_set(scopes)
    if kind not in ("clip", "video", "reward", "schedule"):
        _deny("unsupported_resource_preflight")
    limits = {"clip": 100, "video": 100, "reward": 50, "schedule": 100}
    if not isinstance(resource_ids, (tuple, list)):
        _deny("resource_ids_required")
    ids = _validate_field(list(resource_ids), _array("IDs", _id() if kind == "video" else _opaque(), 1, limits[kind], required=True))
    query = {"id": ids}
    if kind in ("reward", "schedule"):
        query["broadcaster_id"] = broadcaster_id
    paths = {"clip": "/clips", "video": "/videos", "reward": "/channel_points/custom_rewards", "schedule": "/schedule"}
    if kind == "reward":
        if subject_id != broadcaster_id:
            _deny("broadcaster_token_required", status=403)
        if not ({"channel:read:redemptions", "channel:manage:redemptions"} & _scope_set(scopes)):
            _deny("missing_scope", status=403)
        query["only_manageable_rewards"] = True
    _, response = _call(transport, client_id, access_token, "GET", paths[kind], query, None,
                        write=False, expected=(200,))
    if kind == "schedule":
        data = response.get("data")
        if not isinstance(data, dict) or data.get("broadcaster_id") != broadcaster_id or not isinstance(data.get("segments"), list):
            _deny("provider_resource_identity_mismatch", status=502)
        rows = data["segments"]
    else:
        rows = _rows(response)
    found, metadata = set(), {}
    for row in rows:
        if not isinstance(row, dict) or row.get("id") not in ids or row["id"] in found:
            _deny("provider_resource_identity_mismatch", status=502)
        owner_key = "user_id" if kind == "video" else "broadcaster_id"
        if kind != "schedule" and row.get(owner_key) != broadcaster_id:
            _deny("resource_not_owned_by_channel", status=403)
        found.add(row["id"])
        if kind == "schedule":
            if type(row.get("is_recurring")) is not bool:
                _deny("invalid_provider_response", status=502)
            metadata[row["id"]] = {"is_recurring": row["is_recurring"]}
    if found != set(ids):
        _deny("resource_missing_or_not_manageable", status=403)
    if type(reuse_authorized) is not bool or type(storage_authorized) is not bool:
        _deny("invalid_rights_evidence", status=403)
    return RightsEvidence(subject_id, broadcaster_id, kind, tuple(ids), client_id,
                          now, now + EVIDENCE_TTL, ownership_verified=True,
                          creator_app_verified=kind == "reward", reuse_authorized=reuse_authorized,
                          storage_authorized=storage_authorized,
                          metadata_json=_json({"resources": metadata}) if metadata else "{}")

