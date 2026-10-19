"""Pure X Direct contract. Official OpenAPI 2.172 reviewed 2026-10-19.

Sources: https://docs.x.com/openapi.json
https://docs.x.com/x-api/getting-started/pricing
https://docs.x.com/x-api/posts/create-post
https://docs.x.com/x-api/users/blocks/introduction

A Direct decision is a plan, never execution or provider acceptance. Context is
constructed from authenticated server records. Private acceptance authorizes an
attempt without claiming public access. CostAdmission is planning eligibility;
the provider boundary commits a separate durable reservation before each call.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
from hashlib import sha256
import json
import re
import unicodedata
from types import MappingProxyType
from typing import Any, Mapping

CONTRACT_VERSION = "x-v2.172-2026-10-19.2"
PRICING_SOURCE = "https://docs.x.com/x-api/getting-started/pricing"
OPENAPI_SOURCE = "https://docs.x.com/openapi.json"
R = frozenset({"tweet.read", "users.read"})
_EMPTY: Mapping[str, Any] = MappingProxyType({})


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _plain(value):
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


@dataclass(frozen=True)
class FieldSpec:
    kind: str
    required: bool = False
    maximum: int | None = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilitySpec:
    id: str
    title: str
    method: str | None
    path: str | None
    scopes: frozenset[str]
    body_schema: Mapping[str, FieldSpec] = field(default_factory=lambda: _EMPTY)
    query_schema: Mapping[str, FieldSpec] = field(default_factory=lambda: _EMPTY)
    actor_path_params: frozenset[str] = frozenset()
    required_entitlements: frozenset[str] = frozenset({"x_api_v2"})
    execution_kind: str = "http"
    pricing: str = "unverified"
    collection: bool = False
    restriction_reason: str | None = None
    confirmation_field: str | None = None
    confirmation_value: Any = None
    notes: str = ""
    source_url: str = OPENAPI_SOURCE

    def __post_init__(self):
        object.__setattr__(self, "scopes", frozenset(self.scopes))
        object.__setattr__(self, "body_schema", MappingProxyType(dict(self.body_schema)))
        object.__setattr__(self, "query_schema", MappingProxyType(dict(self.query_schema)))
        object.__setattr__(self, "actor_path_params", frozenset(self.actor_path_params))
        object.__setattr__(self, "required_entitlements", frozenset(self.required_entitlements))

    @property
    def path_params(self):
        return tuple(re.findall(r"\{([a-z_]+)\}", self.path or ""))

    @property
    def input_path_params(self):
        return tuple(p for p in self.path_params if p not in self.actor_path_params)

    @property
    def mutates(self):
        return self.method in {"POST", "PUT", "PATCH", "DELETE"} or self.execution_kind == "workflow"

    @property
    def direct_user_intent_required(self):
        return self.id in {"likes.create", "likes.delete", "follows.create", "follows.delete"}


@dataclass(frozen=True)
class CostAdmission:
    workspace_id: str
    account_id: str
    operation_id: str
    request_fingerprint: str
    admitted_micros: int


@dataclass(frozen=True)
class DirectContext:
    workspace_id: str
    account_id: str
    actor_user_id: str
    granted_scopes: frozenset[str] = frozenset()
    implemented_operations: frozenset[str] = frozenset()
    verified_entitlements: frozenset[str] = frozenset()
    app_public_access_verified: bool = False
    approved_request_fingerprint: str | None = None
    approval_direct_user_initiated: bool = False
    cost_admission: CostAdmission | None = None
    app_acceptance_lane_authorized: bool = False

    def __post_init__(self):
        for name in ("granted_scopes", "implemented_operations", "verified_entitlements"):
            object.__setattr__(self, name, frozenset(getattr(self, name)))


@dataclass(frozen=True)
class NormalizedOperation:
    operation_id: str
    method: str
    path: str
    body: Mapping[str, Any]
    query: Mapping[str, Any]
    fingerprint: str
    estimated_cost_micros: int | None
    max_billable_resources: int

    def __post_init__(self):
        object.__setattr__(self, "body", _freeze(self.body))
        object.__setattr__(self, "query", _freeze(self.query))

    def to_dict(self):
        return {**self.__dict__, "body": _plain(self.body), "query": _plain(self.query)}


@dataclass(frozen=True)
class DirectDecision:
    status: str
    reason_code: str
    reason: str
    capability: CapabilitySpec | None
    request: NormalizedOperation | None = None
    ready_for_preview: bool = False

    @property
    def estimated_cost_micros(self):
        return self.request.estimated_cost_micros if self.request else None


class ContractValidationError(ValueError):
    def __init__(self, reason_code, reason):
        super().__init__(reason)
        self.reason_code, self.reason = reason_code, reason


F = FieldSpec
_PAGE = {"max_results": F("integer", maximum=100), "pagination_token": F("token")}
_TWEET_FIELDS = {"tweet.fields": F("fields", choices=(
    "id", "text", "author_id", "created_at", "public_metrics", "non_public_metrics",
    "organic_metrics", "promoted_metrics", "edit_controls", "edit_history_tweet_ids",
    "conversation_id", "referenced_tweets", "attachments", "entities", "lang",
    "reply_settings", "possibly_sensitive", "withheld"))}
_USER_FIELDS = {"user.fields": F("fields", choices=(
    "id", "name", "username", "created_at", "description", "location", "profile_image_url",
    "protected", "public_metrics", "url", "verified", "verified_type", "withheld"))}
_POST_BODY = {
    "text": F("text", maximum=25000), "media": F("post_media"), "poll": F("poll"),
    "reply_settings": F("enum", choices=("everyone", "mentionedUsers", "following", "subscribers", "verified")),
    "for_super_followers_only": F("bool"), "community_id": F("id"),
    "made_with_ai": F("bool"), "paid_partnership": F("bool")}
_specs = {}


def _add(id, method, path, extra="", *, scopes=None, body=None, query=None, actor=(),
         price="unverified", collection=False, kind="http", enterprise=None, confirm=None,
         value=None, notes="", title=None, source=OPENAPI_SOURCE):
    if id in _specs:
        raise RuntimeError(f"Duplicate X capability: {id}")
    _specs[id] = CapabilitySpec(
        id=id, title=title or id.replace(".", " ").replace("_", " ").capitalize(),
        method=method, path=path, scopes=scopes if scopes is not None else R | frozenset(extra.split()),
        body_schema=body or {}, query_schema=query or {}, actor_path_params=frozenset(actor),
        required_entitlements=frozenset({"x_api_v2", "enterprise"} if enterprise else {"x_api_v2"}),
        execution_kind=kind, pricing=price, collection=collection, restriction_reason=enterprise,
        confirmation_field=confirm, confirmation_value=value, notes=notes, source_url=source)


_add("identity.read", "GET", "/2/users/me", query=_USER_FIELDS, price="user_read", title="Connected X identity")
_add("users.get", "GET", "/2/users/{id}", query=_USER_FIELDS, price="user_read")
_add("users.by_username", "GET", "/2/users/by/username/{username}", query=_USER_FIELDS, price="user_read")
_add("posts.get", "GET", "/2/tweets/{id}", query=_TWEET_FIELDS, price="post_read")
_add("posts.lookup", "GET", "/2/tweets", query={**_TWEET_FIELDS, "ids": F("ids", True, 100)}, price="post_read")
_add("posts.create", "POST", "/2/tweets", "tweet.write", body=_POST_BODY, price="post_create", confirm="id")
_add("posts.reply", "POST", "/2/tweets", "tweet.write", body={**_POST_BODY, "reply": F("reply", True)}, price="post_create", confirm="id")
_add("posts.quote", "POST", "/2/tweets", "tweet.write", body={**_POST_BODY, "quote_tweet_id": F("id", True)}, price="post_url",
     enterprise="The current X Create Post reference restricts quote_tweet_id to Enterprise access.", confirm="id",
     source="https://docs.x.com/x-api/posts/create-post")
_add("posts.edit", "POST", "/2/tweets", "tweet.write", body={**_POST_BODY, "edit_options": F("edit", True)}, price="post_create", confirm="id",
     notes="Requires live edit_controls eligibility, editable_until and edits_remaining; previous_post_id is the documented field.")
_add("posts.delete", "DELETE", "/2/tweets/{id}", "tweet.write", price="content_manage", confirm="deleted", value=True)
_add("posts.hide_reply", "PUT", "/2/tweets/{tweet_id}/hidden", "tweet.moderate.write", body={"hidden": F("bool", True)}, price="content_manage", confirm="hidden",
     notes="Compare hidden with the requested boolean; only the authenticated conversation owner may moderate.")
for op, suffix in (("timelines.user", "tweets"), ("timelines.mentions", "mentions"), ("timelines.home", "timelines/reverse_chronological")):
    _add(op, "GET", "/2/users/{id}/" + suffix, actor=("id",), query={**_PAGE, **_TWEET_FIELDS}, price="post_read", collection=True)
for op, suffix in (("search.recent", "recent"), ("search.all", "all")):
    _add(op, "GET", "/2/tweets/search/" + suffix, query={"query": F("text", True, 4096), "max_results": F("integer", maximum=100), "next_token": F("token"), **_TWEET_FIELDS}, price="post_read", collection=True)
_add("likes.create", "POST", "/2/users/{id}/likes", "like.write", actor=("id",), body={"tweet_id": F("id", True)}, enterprise="X removed Like and Follow mutations from all self-serve tiers effective April 20, 2026; verified Enterprise access is required.", price="interaction_create", confirm="liked", value=True)
_add("likes.delete", "DELETE", "/2/users/{id}/likes/{tweet_id}", "like.write", actor=("id",), enterprise="X removed Like and Follow mutations from all self-serve tiers effective April 20, 2026; verified Enterprise access is required.", price="interaction_delete", confirm="liked", value=False)
_add("likes.list", "GET", "/2/users/{id}/liked_tweets", "like.read", actor=("id",), query={**_PAGE, **_TWEET_FIELDS}, price="post_read", collection=True)
_add("likes.users", "GET", "/2/tweets/{id}/liking_users", "like.read", query={**_PAGE, **_USER_FIELDS}, price="user_read", collection=True,
     notes="Visibility is provider-controlled; this does not expose every user's private likes.")
_add("reposts.create", "POST", "/2/users/{id}/retweets", "tweet.write", actor=("id",), body={"tweet_id": F("id", True)}, price="interaction_create", confirm="retweeted", value=True)
_add("reposts.delete", "DELETE", "/2/users/{id}/retweets/{source_tweet_id}", "tweet.write", actor=("id",), price="interaction_delete", confirm="retweeted", value=False)
_add("reposts.users", "GET", "/2/tweets/{id}/retweeted_by", query={**_PAGE, **_USER_FIELDS}, price="user_read", collection=True)
_add("quotes.list", "GET", "/2/tweets/{id}/quote_tweets", query={**_PAGE, **_TWEET_FIELDS}, price="post_read", collection=True)
_add("follows.create", "POST", "/2/users/{id}/following", "follows.write", actor=("id",), body={"target_user_id": F("id", True)}, enterprise="X removed Like and Follow mutations from all self-serve tiers effective April 20, 2026; verified Enterprise access is required.", price="interaction_create", confirm="following", value=True,
     notes="following=false and pending_follow=true is a pending protected-account request.")
_add("follows.delete", "DELETE", "/2/users/{source_user_id}/following/{target_user_id}", "follows.write", actor=("source_user_id",), enterprise="X removed Like and Follow mutations from all self-serve tiers effective April 20, 2026; verified Enterprise access is required.", price="interaction_delete", confirm="following", value=False)
for op, suffix in (("follows.followers", "followers"), ("follows.following", "following")):
    _add(op, "GET", "/2/users/{id}/" + suffix, "follows.read", actor=("id",), query={**_PAGE, **_USER_FIELDS}, price="user_read", collection=True)
_add("bookmarks.create", "POST", "/2/users/{id}/bookmarks", "bookmark.write", actor=("id",), body={"tweet_id": F("id"), "tweet_ids": F("ids", maximum=25), "folder_id": F("id")}, price="bookmark", confirm="bookmarked", value=True,
     notes="Exactly one of tweet_id or tweet_ids; bulk maximum 25 IDs.")
_add("bookmarks.delete", "DELETE", "/2/users/{id}/bookmarks/{tweet_id}", "bookmark.write", actor=("id",), price="bookmark", confirm="bookmarked", value=False)
_add("bookmarks.list", "GET", "/2/users/{id}/bookmarks", "bookmark.read", actor=("id",), query={**_PAGE, **_TWEET_FIELDS}, price="post_read", collection=True)
_add("bookmarks.folders.list", "GET", "/2/users/{id}/bookmarks/folders", "bookmark.read", actor=("id",), query=_PAGE, collection=True, notes="Read price requires verification.")
_add("bookmarks.folders.get", "GET", "/2/users/{id}/bookmarks/folders/{folder_id}", "bookmark.read", actor=("id",), query={**_PAGE, **_TWEET_FIELDS}, price="post_read", collection=True)
_add("bookmarks.folders.create", "POST", "/2/users/{id}/bookmarks/folders", scopes=frozenset({"users.read", "bookmark.write"}), actor=("id",), body={"name": F("text", True, 25)}, confirm="id", notes="Creation price is not verified.")
for family, noun, read_scope, write_scope in (("mutes", "muting", "mute.read", "mute.write"), ("blocks", "blocking", "block.read", "block.write")):
    restriction = "X documents account block and unblock writes as Enterprise-only; reading the block list has separate availability." if family == "blocks" else None
    _add(family + ".list", "GET", "/2/users/{id}/" + noun, read_scope, actor=("id",), query={**_PAGE, **_USER_FIELDS}, price="user_read", collection=True)
    _add(family + ".create", "POST", "/2/users/{id}/" + noun, write_scope, actor=("id",), body={"target_user_id": F("id", True)}, price="interaction_create", enterprise=restriction, confirm=noun, value=True)
    _add(family + ".delete", "DELETE", "/2/users/{source_user_id}/" + noun + "/{target_user_id}", write_scope, actor=("source_user_id",), price="interaction_delete", enterprise=restriction, confirm=noun, value=False)

_LIST_FIELDS = {"list.fields": F("fields", choices=("id", "name", "created_at", "description", "follower_count", "member_count", "private", "owner_id"))}
_add("lists.create", "POST", "/2/lists", "list.read list.write", body={"name": F("text", True, 25), "description": F("string", maximum=100), "private": F("bool")}, price="list_create", confirm="id")
_add("lists.get", "GET", "/2/lists/{id}", "list.read", query=_LIST_FIELDS, price="list_read")
_add("lists.update", "PUT", "/2/lists/{id}", "list.write", body={"name": F("text", maximum=25), "description": F("string", maximum=100), "private": F("bool")}, price="list_manage")
_add("lists.delete", "DELETE", "/2/lists/{id}", "list.write", price="list_manage")
_add("lists.members.list", "GET", "/2/lists/{id}/members", "list.read", query={**_PAGE, **_USER_FIELDS}, price="user_read", collection=True)
_add("lists.members.add", "POST", "/2/lists/{id}/members", "list.write", body={"user_id": F("id", True)}, price="list_manage")
_add("lists.members.delete", "DELETE", "/2/lists/{id}/members/{user_id}", "list.write", price="list_manage")
_add("lists.followers", "GET", "/2/lists/{id}/followers", "list.read", query={**_PAGE, **_USER_FIELDS}, price="user_read", collection=True)
_add("lists.posts", "GET", "/2/lists/{id}/tweets", "list.read", query={**_PAGE, **_TWEET_FIELDS}, price="post_read", collection=True)
for op, suffix in (("lists.owned", "owned_lists"), ("lists.followed", "followed_lists"), ("lists.memberships", "list_memberships"), ("lists.pinned", "pinned_lists")):
    _add(op, "GET", "/2/users/{id}/" + suffix, "list.read", actor=("id",), query={**_PAGE, **_LIST_FIELDS}, price="list_read", collection=True)
for op, method, suffix in (("lists.follow", "POST", "followed_lists"), ("lists.unfollow", "DELETE", "followed_lists/{list_id}"), ("lists.pin", "POST", "pinned_lists"), ("lists.unpin", "DELETE", "pinned_lists/{list_id}")):
    _add(op, method, "/2/users/{id}/" + suffix, "list.write", actor=("id",), body={"list_id": F("id", True)} if method == "POST" else {}, price="list_manage", notes="Requires dedicated response verification.")
for op, path in (("dm.events", "/2/dm_events"), ("dm.conversation.events", "/2/dm_conversations/{dm_conversation_id}/dm_events"), ("dm.participant.events", "/2/dm_conversations/with/{participant_id}/dm_events")):
    _add(op, "GET", path, "dm.read", query=_PAGE, price="dm_read", collection=True, notes="Legacy events cover the documented 30-day window; encrypted X Chat is separate.")
_add("dm.event", "GET", "/2/dm_events/{id}", "dm.read", price="dm_read")
_DM_BODY = {"text": F("text", maximum=10000), "attachments": F("dm_attachments")}
_add("dm.send", "POST", "/2/dm_conversations/with/{participant_id}/messages", "dm.write", body=_DM_BODY, price="interaction_create", confirm="dm_event_id")
_add("dm.conversation.send", "POST", "/2/dm_conversations/{dm_conversation_id}/messages", "dm.write", body=_DM_BODY, price="interaction_create", confirm="dm_event_id")
_add("dm.group.create", "POST", "/2/dm_conversations", "dm.write", body={"conversation_type": F("enum", True, choices=("Group",)), "participant_ids": F("ids", True, 49), "message": F("dm_message", True)}, price="interaction_create", confirm="dm_event_id")
_add("dm.delete", "DELETE", "/2/dm_events/{event_id}", "dm.write", price="interaction_delete", notes="Removes only the authenticated user's copy; not an unsend promise.")
_add("dm.block", "POST", "/2/users/{id}/dm/block", "dm.write", notes="id is the target account; price and response verification pending.")
_add("dm.unblock", "POST", "/2/users/{id}/dm/unblock", "dm.write", notes="DM blocks are distinct from Enterprise account blocks.")
_add("media.upload", "POST", "/2/media/upload", scopes=frozenset({"media.write"}), kind="multipart", confirm="id")
_add("media.initialize", "POST", "/2/media/upload/initialize", scopes=frozenset({"media.write"}), kind="workflow", confirm="id")
_add("media.append", "POST", "/2/media/upload/{id}/append", scopes=frozenset({"media.write"}), kind="multipart")
_add("media.finalize", "POST", "/2/media/upload/{id}/finalize", scopes=frozenset({"media.write"}), kind="workflow", confirm="id")
_add("media.status", "GET", "/2/media/upload", scopes=frozenset({"media.write"}), query={"command": F("enum", True, choices=("STATUS",)), "media_id": F("id", True)})
_add("media.metadata", "POST", "/2/media/metadata", scopes=frozenset({"media.write"}), body={"id": F("id", True), "metadata": F("media_metadata", True)}, price="media_metadata", notes="metadata.alt_text.text, maximum 1000 characters; dedicated response verifier required.")
_add("analytics.public", "GET", "/2/tweets/{id}", query=_TWEET_FIELDS, price="post_read", notes="Missing metrics are unknown, never zero.")
_add("analytics.owned", "GET", "/2/tweets/{id}", query=_TWEET_FIELDS, price="post_read", kind="workflow", notes="Verify authorship and documented 30-day eligibility before private metrics.")
_add("analytics.posts", "GET", "/2/tweets/analytics", enterprise="X documents this dedicated Post Analytics endpoint under Enterprise APIs.", kind="workflow")
_add("analytics.media", "GET", "/2/media/analytics", enterprise="X documents this dedicated Media Analytics endpoint under Enterprise APIs.", kind="workflow")
for op, scopes, note in (
    ("oauth.connect", R, "Official OAuth 2.0 PKCE S256; exact callback and session/workspace-bound state."),
    ("oauth.reconnect", R, "Repeat official consent and verify account identity."),
    ("oauth.disconnect", R, "Dedicated lifecycle revokes tokens, removes local credential material and cancels pending authority."),
    ("oauth.refresh", frozenset({"offline.access"}), "Official refresh endpoint with atomic encrypted token rotation."),
    ("posts.schedule", R | {"tweet.write"}, "Rafii durable queue dispatches at the approved time; no native X scheduling endpoint."),
    ("profile.update", R, "No current v2 profile mutation verified. Legacy access and implementation need separate verification; no universal X prohibition is claimed."),
    ("profile.image", R, "No verified current v2 profile-image mutation or app entitlement."),
    ("profile.banner", R, "No verified current v2 banner mutation or app entitlement."),
    ("account.security", R, "No verified password, security or account-settings mutation."),
    ("bookmarks.folders.rename", R | {"bookmark.write"}, "Endpoint and application access not verified."),
    ("bookmarks.folders.delete", R | {"bookmark.write"}, "Endpoint and application access not verified."),
    ("media.subtitles", frozenset({"media.write"}), "Official subtitles require a separate validated workflow."),
    ("chat.encrypted", R | {"dm.read","dm.write"}, "Encrypted Chat needs key management and its separate event workflow."),
    ("spaces.manage", R | {"space.read"}, "Creating/hosting a Space differs from read-only lookup; no write contract verified."),
    ("community_notes.manage", R, "Separate participant eligibility, scopes and implementation required."),
    ("ads.manage", frozenset(), "Separate ad-account authority, eligibility and spend."),
    ("activity.subscribe", R, "Separate subscription eligibility, delivery security and billing.")):
    _add(op, None, None, scopes=frozenset(scopes), kind="unverified", notes=note)
_add("articles.draft", "POST", "/2/articles/draft", scopes=frozenset({"tweet.write"}), kind="workflow", notes="Dedicated content_state schema and account eligibility required.")
_add("articles.publish", "POST", "/2/articles/{article_id}/publish", "tweet.write", kind="workflow", notes="Article eligibility and provider receipt workflow required.")
_add("spaces.get", "GET", "/2/spaces/{id}", "space.read", kind="workflow", price="space_read", notes="Spaces IDs require their own validated schema.")
_add("spaces.search", "GET", "/2/spaces/search", "space.read", kind="workflow", price="space_read", collection=True)
_add("communities.get", "GET", "/2/communities/{id}", kind="workflow", price="community_read")
_add("communities.search", "GET", "/2/communities/search", kind="workflow", price="community_read", collection=True)
_add("posts.thread", "POST", "/2/tweets", "tweet.write", body={"posts": F("thread_posts", True, 25)},
     price="thread", kind="workflow", title="Publish a verified thread",
     notes="Each approved text post is dispatched once and verified before the next reply. Self-serve own-thread eligibility must be evidenced.")
# Pinned lists have no documented request page bound. Do not invent max_results.
_specs["lists.pinned"] = __import__("dataclasses").replace(_specs["lists.pinned"], query_schema=_LIST_FIELDS, pricing="unverified",
    notes="X documents no pagination/page-size control here; a maximum billable resource bound is unverified.")
CAPABILITIES: Mapping[str, CapabilitySpec] = MappingProxyType(dict(_specs))
del _specs, _add

_ID = re.compile(r"[1-9][0-9]{0,18}\Z", re.ASCII)
_HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}\Z", re.ASCII)


def _invalid(message):
    raise ContractValidationError("x_invalid_input", message)


def validate_x_id(value, name="id"):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _invalid(f"{name} must be a positive decimal X ID string with 1 to 19 digits.")
    return value


def _id_list(value, name, maximum):
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= maximum:
        _invalid(f"{name} must contain between 1 and {maximum} X ID strings.")
    result = [validate_x_id(v, name) for v in value]
    if len(set(result)) != len(result):
        _invalid(f"{name} must not contain duplicate IDs.")
    return result


def _object(value, schema, name):
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        _invalid(f"{name} must be a JSON object with string keys.")
    unknown = set(value) - set(schema)
    if unknown:
        _invalid(f"Fields outside the implemented {name} schema: {', '.join(sorted(unknown))}.")
    missing = [key for key, spec in schema.items() if spec.required and key not in value]
    if missing:
        _invalid(f"Required {name} fields missing: {', '.join(sorted(missing))}.")
    return {key: _value(item, schema[key], f"{name}.{key}") for key, item in value.items()}


def _content_present(value, name):
    if not value.get("text") and not value.get("attachments") and not value.get("media") and not value.get("poll"):
        _invalid(f"{name} requires text or supported attached content.")


def _value(value, spec, name):
    kind = spec.kind
    if kind == "id":
        return validate_x_id(value, name)
    if kind == "ids":
        return _id_list(value, name, spec.maximum or 100)
    if kind in {"text", "string", "token"}:
        if not isinstance(value, str) or "\x00" in value:
            _invalid(f"{name} must be a string without NUL characters.")
        if kind != "string" and not value.strip():
            _invalid(f"{name} must not be empty.")
        if len(value) > (spec.maximum or (2048 if kind == "token" else 4096)):
            _invalid(f"{name} exceeds the implemented length limit.")
        return unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n") if kind == "text" else value
    if kind == "bool":
        if type(value) is not bool:
            _invalid(f"{name} must be a JSON boolean.")
        return value
    if kind == "integer":
        if type(value) is not int or not 1 <= value <= (spec.maximum or 1000000000):
            _invalid(f"{name} must be a positive integer within its documented bound.")
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec.choices:
            _invalid(f"{name} must be one of {', '.join(spec.choices)}.")
        return value
    if kind == "fields":
        parts = value.split(",") if isinstance(value, str) else value
        if not isinstance(parts, (list, tuple)) or not parts or any(not isinstance(p, str) or p not in spec.choices for p in parts):
            _invalid(f"{name} contains an unimplemented field selection.")
        return ",".join(sorted(set(parts)))
    if kind == "post_media":
        return _object(value, {"media_ids": F("ids", True, 4), "tagged_user_ids": F("ids", maximum=10)}, name)
    if kind == "reply":
        return _object(value, {"in_reply_to_tweet_id": F("id", True), "exclude_reply_user_ids": F("ids", maximum=100)}, name)
    if kind == "edit":
        return _object(value, {"previous_post_id": F("id", True)}, name)
    if kind == "poll":
        if not isinstance(value, Mapping) or set(value) != {"options", "duration_minutes"}:
            _invalid(f"{name} requires exactly options and duration_minutes.")
        options = value["options"]
        if not isinstance(options, (list, tuple)) or not 2 <= len(options) <= 4:
            _invalid(f"{name}.options must contain two to four choices.")
        normalized = [_value(v, F("text", maximum=25), f"{name}.options") for v in options]
        duration = _value(value["duration_minutes"], F("integer", maximum=10080), f"{name}.duration_minutes")
        if duration < 5:
            _invalid(f"{name}.duration_minutes must be at least five minutes.")
        return {"options": normalized, "duration_minutes": duration}
    if kind == "dm_attachments":
        if not isinstance(value, (list, tuple)) or len(value) != 1:
            _invalid(f"{name} requires one uploaded media attachment.")
        return [_object(value[0], {"media_id": F("id", True)}, name)]
    if kind == "dm_message":
        result = _object(value, _DM_BODY, name)
        _content_present(result, name)
        return result
    if kind == "media_metadata":
        if not isinstance(value, Mapping) or set(value) != {"alt_text"}:
            _invalid(f"{name} currently implements only alt_text.")
        return {"alt_text": _object(value["alt_text"], {"text": F("string", True, 1000)}, f"{name}.alt_text")}
    _invalid(f"{name} does not have an implemented validator.")


def _validate_path_value(key, value):
    if key == "username":
        if not isinstance(value, str) or not _HANDLE.fullmatch(value):
            _invalid("username must contain 1–15 ASCII letters, digits or underscores, without @.")
        return value
    if key == "dm_conversation_id":
        if not isinstance(value, str):
            _invalid("dm_conversation_id must be a string.")
        pieces = value.split("-")
        if not 1 <= len(pieces) <= 2:
            _invalid("dm_conversation_id must be a numeric group ID or two numeric user IDs separated by one hyphen.")
        for piece in pieces:
            validate_x_id(piece, key)
        return value
    return validate_x_id(value, key)


def _validate_body_rules(spec, body, actor_user_id):
    if spec.id in {"posts.create", "posts.reply", "posts.quote", "posts.edit"}:
        _content_present(body, "Post")
        if body.get("media") and body.get("poll"):
            _invalid("A post cannot combine a poll and media attachments in this implemented schema.")
    if spec.id == "bookmarks.create" and (("tweet_id" in body) == ("tweet_ids" in body)):
        _invalid("Bookmark creation requires exactly one of tweet_id or tweet_ids.")
    if spec.id == "lists.update" and not body:
        _invalid("List update requires at least one changed field.")
    if spec.id in {"dm.send", "dm.conversation.send"}:
        _content_present(body, "Direct message")
    if spec.id in {"follows.create", "mutes.create", "blocks.create"} and body.get("target_user_id") == actor_user_id:
        _invalid("The target account must differ from the connected X actor.")
    if spec.id == "dm.group.create" and actor_user_id in body["participant_ids"]:
        _invalid("The authenticated actor must not be repeated in participant_ids.")


def usd_to_micros(value):
    if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
        raise ValueError("USD amounts require decimal strings, Decimal, or integers.")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid USD amount.") from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal("1000000000"):
        raise ValueError("USD amount must be finite, nonnegative and within range.")
    if Decimal(0) < amount < Decimal("0.000001"):
        return 1
    with localcontext() as ctx:
        ctx.prec = max(28, len(amount.as_tuple().digits) + 8)
        return int((amount * Decimal(1000000)).to_integral_value(rounding=ROUND_CEILING))


_UNIT_MICROS = MappingProxyType({
    "post_read": 5000, "user_read": 10000, "dm_read": 10000, "list_read": 5000,
    "space_read": 5000, "community_read": 5000, "interaction_create": 15000,
    "interaction_delete": 10000, "content_manage": 5000, "list_create": 10000,
    "list_manage": 5000, "bookmark": 5000, "media_metadata": 5000, "post_url": 200000})
_READ_PRICES = frozenset({"post_read","user_read","dm_read","list_read","space_read","community_read"})
_POSSIBLE_URL = re.compile(r"(?:\b[a-z][a-z0-9+.-]*:\s*\S|www\s*\.|[\w-]\s*[.\u3002\uff0e\uff61]\s*[\w-])", re.IGNORECASE)


def contains_possible_url(value):
    if not isinstance(value, str):
        raise ValueError("URL classification requires text.")
    return bool(_POSSIBLE_URL.search(value))


def _resource_bound(value):
    if type(value) is not int or not 1 <= value <= 10000:
        _invalid("max_billable_resources must bound resources with an integer from 1 to 10000.")
    return value


def estimate_cost_micros(operation_id, *, body=None, max_billable_resources=1):
    spec = CAPABILITIES.get(operation_id)
    if spec is None:
        raise ContractValidationError("x_unknown_operation", "Unknown X operation.")
    units = _resource_bound(max_billable_resources)
    if spec.pricing == "post_create":
        from .x_direct_cost import estimate_request_cost_micros
        return estimate_request_cost_micros(method="POST", path="/2/tweets", body=body, max_resources=units)
    unit = _UNIT_MICROS.get(spec.pricing)
    return None if unit is None else unit * units if spec.pricing in _READ_PRICES else unit


def normalize_operation(operation_id, *, workspace_id, account_id, actor_user_id,
                        path_params=None, body=None, query=None, max_billable_resources=1):
    spec = CAPABILITIES.get(operation_id)
    if spec is None:
        raise ContractValidationError("x_unknown_operation", "Unknown X operation.")
    if spec.method is None or spec.path is None:
        raise ContractValidationError("x_endpoint_unverified", spec.notes or "No executable endpoint contract verified.")
    if spec.id == "posts.thread":
        if path_params or query:
            _invalid("A thread cannot override the official post endpoint or query.")
        from .x_direct_thread import normalize_thread
        from .x_direct_cost import PRICES
        return normalize_thread(body, workspace_id, account_id, actor_user_id,
            write_cost_micros=PRICES["post_write_url"], read_cost_micros=PRICES["post_read"], max_readbacks=3)
    if spec.execution_kind != "http":
        raise ContractValidationError("x_not_implemented", "This specialized operation requires a dedicated validated workflow.")
    for name, value in (("workspace_id", workspace_id), ("account_id", account_id)):
        if not isinstance(value, str) or not value.strip() or len(value) > 200 or "\x00" in value:
            _invalid(f"A server-bound {name} is required.")
    actor = validate_x_id(actor_user_id, "credential-bound actor_user_id")
    units = _resource_bound(max_billable_resources)
    raw_params = {} if path_params is None else path_params
    if not isinstance(raw_params, Mapping) or any(not isinstance(k, str) for k in raw_params):
        _invalid("path_params must be a JSON object with string keys.")
    unknown = set(raw_params) - set(spec.path_params)
    if unknown:
        _invalid(f"Unknown path parameters: {', '.join(sorted(unknown))}.")
    params = {}
    for key in spec.path_params:
        if key in spec.actor_path_params:
            if key in raw_params and raw_params[key] != actor:
                _invalid(f"{key} is credential-bound and cannot be overridden.")
            params[key] = actor
        elif key not in raw_params:
            _invalid(f"Required path parameter missing: {key}.")
        else:
            params[key] = _validate_path_value(key, raw_params[key])
    if spec.id in {"follows.delete","mutes.delete","blocks.delete"} and params.get("target_user_id") == actor:
        _invalid("The target must differ from the connected X actor.")
    normalized_body = _object({} if body is None else body, spec.body_schema, "body")
    _validate_body_rules(spec, normalized_body, actor)
    raw_query = {} if query is None else query
    if not isinstance(raw_query, Mapping) or any(not isinstance(k, str) for k in raw_query):
        _invalid("query must be a JSON object with string keys.")
    raw_query = dict(raw_query)
    if "expansions" in raw_query:
        _invalid("Expansions require a dedicated verified resource-cost envelope.")
    if spec.collection and "max_results" in spec.query_schema:
        raw_query.setdefault("max_results", min(units, 100))
    if "ids" in spec.query_schema and isinstance(raw_query.get("ids"), str):
        raw_query["ids"] = raw_query["ids"].split(",")
    normalized_query = _object(raw_query, spec.query_schema, "query")
    selected_fields = set(normalized_query.get("tweet.fields", "").split(","))
    if selected_fields & {"non_public_metrics", "organic_metrics", "promoted_metrics"} and spec.id != "analytics.owned":
        _invalid("Private metrics require the separately verified owned-analytics operation.")
    page_minimum = {"search.recent": 10, "search.all": 10, "likes.list": 5,
        "timelines.user": 5, "timelines.mentions": 5, "timelines.home": 1}.get(spec.id, 1)
    if "max_results" in normalized_query and normalized_query["max_results"] < page_minimum:
        _invalid(f"This X endpoint requires max_results of at least {page_minimum}.")
    if "max_results" in normalized_query and units < normalized_query["max_results"]:
        _invalid("max_billable_resources must cover requested max_results.")
    if "ids" in normalized_query:
        if units < len(normalized_query["ids"]):
            _invalid("max_billable_resources must cover every lookup ID.")
        normalized_query["ids"] = ",".join(normalized_query["ids"])
    if spec.id == "analytics.public":
        selected = set(normalized_query.get("tweet.fields", "").split(",")) - {""}
        if selected & {"non_public_metrics", "organic_metrics", "promoted_metrics"}:
            _invalid("Public analytics cannot request private metrics.")
        normalized_query["tweet.fields"] = ",".join(sorted(selected | {"public_metrics"}))
    path = spec.path.format(**params)
    canonical = {"contract_version": CONTRACT_VERSION, "workspace_id": workspace_id,
        "account_id": account_id, "actor_user_id": actor, "operation_id": operation_id,
        "method": spec.method, "path": path, "body": normalized_body, "query": normalized_query,
        "max_billable_resources": units}
    digest = sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    from .x_direct_cost import estimate_request_cost_micros, XCostAdmissionError
    try:
        estimate = estimate_request_cost_micros(method=spec.method, path=path, body=normalized_body,
            query=normalized_query, max_resources=units) if spec.pricing != "unverified" else None
    except XCostAdmissionError:
        estimate = None
    return NormalizedOperation(operation_id, spec.method, path, normalized_body, normalized_query, digest, estimate, units)


def _deny(spec, code, reason, request=None, *, ready=False):
    return DirectDecision("unavailable", code, reason, spec, request, ready)


def _availability(spec, context):
    if spec.restriction_reason and "enterprise" not in context.verified_entitlements:
        return _deny(spec, "x_provider_restriction", "Unavailable — X API restriction: " + spec.restriction_reason)
    if spec.method is None or spec.path is None:
        return _deny(spec, "x_endpoint_unverified", spec.notes or "No executable endpoint contract verified.")
    if spec.execution_kind != "http" and spec.id != "posts.thread":
        return _deny(spec, "x_not_implemented", "Unavailable — this specialized capability needs a dedicated Rafii workflow and receipt handler. " + spec.notes)
    if spec.id not in context.implemented_operations:
        return _deny(spec, "x_not_implemented", "Unavailable — Rafii has not bound an execution and response-verification handler.")
    if context.app_public_access_verified is not True and context.app_acceptance_lane_authorized is not True:
        return _deny(spec, "x_app_launch_unverified", "Unavailable — ordinary-customer access is unverified and this request has no authorized private acceptance lane.")
    missing = spec.required_entitlements - context.verified_entitlements
    if missing:
        return _deny(spec, "x_app_access_unverified", "Unavailable — application entitlement evidence missing for: " + ", ".join(sorted(missing)) + ".")
    missing = spec.scopes - context.granted_scopes
    if missing:
        return _deny(spec, "x_missing_scopes", "Reconnect through official X consent to grant: " + ", ".join(sorted(missing)) + ".")
    return None


def _conditional_access(spec, context, request):
    from .x_text import text_eligibility
    required = set()
    if spec.id == "posts.edit":
        required.add("post_edit:" + request.body["edit_options"]["previous_post_id"])
    if spec.id == "posts.reply" and "enterprise" not in context.verified_entitlements:
        required.add("summoned_reply:" + request.body["reply"]["in_reply_to_tweet_id"])
    if spec.id == "posts.thread" and "enterprise" not in context.verified_entitlements:
        required.add("self_thread_reply")
    bodies = request.body["posts"] if spec.id == "posts.thread" else [request.body]
    if spec.id in {"posts.create","posts.reply","posts.quote","posts.edit","posts.thread"}:
        for body in bodies:
            eligibility = text_eligibility(body.get("text", ""))
            if eligibility == "unverified" and "long_posts" not in context.verified_entitlements:
                return _deny(spec, "x_text_validation_unverified",
                    "Unavailable — Rafii must verify this text's weighted URL/emoji length before execution.", request)
            if eligibility == "long":
                required.add("long_posts")
            if "enterprise" not in context.verified_entitlements and len(re.findall(r"(?<![\\w$])\\$[A-Za-z][A-Za-z0-9_]*", body.get("text", ""))) > 1:
                return _deny(spec, "x_provider_restriction", "Unavailable — X API restriction: self-serve posts allow at most one cashtag.", request)
            if body.get("for_super_followers_only"):
                required.add("subscriptions")
            if "community_id" in body:
                required.add("community_posting:" + body["community_id"])
            if body.get("media") or body.get("poll"):
                return _deny(spec, "x_content_verification_unavailable",
                    "Unavailable — uploaded-media ownership, billing and attachment/poll readback must be verified before this content can execute.", request)
    missing = required - context.verified_entitlements
    if missing:
        reason = "Unavailable — account/resource eligibility must be verified for: " + ", ".join(sorted(missing)) + "."
        if any(key.startswith("summoned_reply:") for key in missing):
            reason = "Unavailable — X API restriction: self-serve replies require the original author to summon this account. Read the target post explicitly to verify an account-bound mention."
        elif "self_thread_reply" in missing:
            reason = "Unavailable — X self-serve reply restrictions apply; an exemption for replies within your own thread has not been verified."
        return _deny(spec, "x_account_access_unverified", reason, request)
    return None


def evaluate_direct_operation(operation_id, context, *, path_params=None, body=None, query=None, max_billable_resources=1):
    spec = CAPABILITIES.get(operation_id)
    if spec is None:
        return _deny(None, "x_unknown_operation", "Unknown X operation; arbitrary endpoints are not accepted.")
    unavailable = _availability(spec, context)
    if unavailable is not None:
        return unavailable
    try:
        request = normalize_operation(operation_id, workspace_id=context.workspace_id, account_id=context.account_id,
            actor_user_id=context.actor_user_id, path_params=path_params, body=body, query=query,
            max_billable_resources=max_billable_resources)
    except ContractValidationError as exc:
        return _deny(spec, exc.reason_code, exc.reason)
    conditional = _conditional_access(spec, context, request)
    if conditional is not None:
        return conditional
    if request.estimated_cost_micros is None:
        return _deny(spec, "x_pricing_unverified", "Unavailable — endpoint pricing is unverified; no free request or guaranteed financial cap is assumed.", request)
    admission = context.cost_admission
    if admission is None:
        return _deny(spec, "x_cost_admission_required", "An operation/account/workspace-bound server budget admission is required.", request)
    if not isinstance(admission, CostAdmission):
        return _deny(spec, "x_cost_admission_mismatch", "Budget admission must be a server CostAdmission record.", request)
    expected = (context.workspace_id, context.account_id, operation_id, request.fingerprint)
    actual = (admission.workspace_id, admission.account_id, admission.operation_id, admission.request_fingerprint)
    if actual != expected or type(admission.admitted_micros) is not int or admission.admitted_micros < 0:
        return _deny(spec, "x_cost_admission_mismatch", "Budget admission does not match the exact request.", request)
    if admission.admitted_micros < request.estimated_cost_micros:
        return _deny(spec, "x_cost_ceiling_exceeded", "The request estimate exceeds the admitted budget. A software counter is not a financial cap.", request)
    if spec.mutates and context.approved_request_fingerprint != request.fingerprint:
        return _deny(spec, "x_approval_required", "Explicit approval of this exact operation is required.", request, ready=True)
    if spec.direct_user_intent_required and context.approval_direct_user_initiated is not True:
        return _deny(spec, "x_direct_user_intent_required", "This like/follow action requires recorded direct user intent.", request)
    return DirectDecision("direct", "x_direct_plan_ready", "Eligible for server execution. This plan is not provider execution, success or a receipt.", spec, request, True)


def list_capabilities(context):
    results = []
    for spec in CAPABILITIES.values():
        unavailable = _availability(spec, context)
        if unavailable is not None:
            results.append(unavailable)
        elif spec.pricing == "unverified":
            results.append(_deny(spec, "x_pricing_unverified", "Unavailable — endpoint pricing requires verification."))
        else:
            results.append(_deny(spec, "x_request_required", "Provide exact arguments to check eligibility, cost admission and approval.", ready=True))
    return tuple(results)


def execution_authority(request, context):
    """Recheck frozen authorization at dispatch; provider transport admits actual cost.
    This does not return a Direct plan or bypass the durable cost boundary.
    """
    spec = CAPABILITIES.get(request.operation_id)
    if spec is None:
        return _deny(None,"x_unknown_operation","Unknown X operation.")
    unavailable = _availability(spec,context) or _conditional_access(spec,context,request)
    if unavailable is not None:
        return unavailable
    if spec.mutates and context.approved_request_fingerprint != request.fingerprint:
        return _deny(spec,"x_approval_required","Explicit approval of this exact operation is required.",request)
    if spec.direct_user_intent_required and context.approval_direct_user_initiated is not True:
        return _deny(spec,"x_direct_user_intent_required","This action requires direct customer intent.",request)
    return None


def validate_wire_request(request, *, workspace_id, account_id, actor_user_id, thread_context=None):
    """Reconstruct the server-bound contract immediately before provider I/O."""
    if not isinstance(request, NormalizedOperation):
        _invalid("An immutable X request is required.")
    spec = CAPABILITIES.get(request.operation_id)
    if spec is None or spec.execution_kind != "http" or not spec.path:
        _invalid("No official HTTP contract exists for this request.")
    pattern = re.escape(spec.path)
    for key in spec.path_params:
        pattern = pattern.replace(re.escape("{" + key + "}"), "(?P<" + key + ">[^/]+)")
    match = re.fullmatch(pattern, request.path) if isinstance(request.path, str) else None
    if match is None:
        _invalid("The X request path differs from its official operation.")
    normalized = normalize_operation(request.operation_id, workspace_id=workspace_id,
        account_id=account_id, actor_user_id=actor_user_id, path_params=match.groupdict(),
        body=request.body, query=request.query, max_billable_resources=request.max_billable_resources)
    for name in ("operation_id", "method", "path", "body", "query", "max_billable_resources"):
        if getattr(request, name) != getattr(normalized, name):
            _invalid("The X request differs from its validated wire contract.")
    if thread_context is None:
        expected = normalized
    else:
        if not isinstance(thread_context, tuple) or len(thread_context) != 2:
            _invalid("Invalid durable thread execution context.")
        plan, progress = thread_context
        if not isinstance(plan, NormalizedOperation) or plan.operation_id != "posts.thread":
            _invalid("Invalid parent thread.")
        parent = normalize_operation("posts.thread", workspace_id=workspace_id,
            account_id=account_id, actor_user_id=actor_user_id, body=plan.body)
        if parent != plan:
            _invalid("The thread no longer matches its approved account or text.")
        from .x_direct_thread import current_step
        expected = current_step(parent, progress)
        if expected is None:
            _invalid("No durable thread step is executable.")
    if request != expected:
        _invalid("The X request fingerprint or cost no longer matches its server-bound contract.")
    return request
