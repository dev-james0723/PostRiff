"""Opt-in read-only Meta public sampling. NOT production-bound without App Review.

This module implements fixed-host, bounded provider reads and normalized sampled
observations. It does not fetch credentials, register itself, acquire Meta access,
claim full-network coverage or perform any model evaluation. Callers must supply
verified workspace-scoped policies, connected identity proof and durable quota
admission. Tests use injected HTTP transports only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata
from urllib.parse import urlencode

from ..contracts import ContractError, digest, instant, iso, permits
from ..policy import ProviderCapability, SourcePolicy, admit
from .base import Batch, JsonTransport, observation, safe_url
from ....provider_base import GRAPH_VERSION

THREADS_HOST = "graph.threads.net"
FACEBOOK_HOST = "graph.facebook.com"
THREADS_URL = f"https://{THREADS_HOST}/{GRAPH_VERSION}/keyword_search"
INSTAGRAM_URL = f"https://{FACEBOOK_HOST}/{GRAPH_VERSION}/ig_hashtag_search"
FACEBOOK_BASE = f"https://{FACEBOOK_HOST}/{GRAPH_VERSION}"
PROTOCOL = f"meta-graph-{GRAPH_VERSION}-read-only-20261008"
MAX_ITEMS = 50
MAX_BYTES = 400_000

CAPABILITIES = {
    ("threads", "keyword_search"): ProviderCapability(
        "threads", "keyword_search", PROTOCOL, ("raw_post",), THREADS_URL,
        "official_graph_json", "threads_user_oauth",
        ("threads_basic", "threads_keyword_search"), MAX_ITEMS, MAX_BYTES, 15, 1,
        "threads_search_quota", "refresh/deletion/revocation"),
    ("instagram", "hashtag_discovery"): ProviderCapability(
        "instagram", "hashtag_discovery", PROTOCOL, ("raw_post",), INSTAGRAM_URL,
        "official_graph_json", "facebook_login_instagram_professional",
        ("instagram_basic", "instagram_public_content_access"),
        MAX_ITEMS, MAX_BYTES, 15, 1, "ig_rolling_7_day_hashtag_quota",
        "refresh/deletion/revocation"),
    ("facebook", "page_public_posts"): ProviderCapability(
        "facebook", "page_public_posts", PROTOCOL, ("raw_post",), FACEBOOK_BASE,
        "official_graph_json", "app_or_system_user_with_ppca",
        ("pages_public_content_access",), MAX_ITEMS, MAX_BYTES, 15, 1,
        "facebook_ppca_page_quota", "refresh/deletion/revocation"),
}

_POST_HOSTS = {
    "threads": frozenset({"threads.net", "www.threads.net", "threads.com", "www.threads.com"}),
    "instagram": frozenset({"instagram.com", "www.instagram.com"}),
    "facebook": frozenset({"facebook.com", "www.facebook.com", "m.facebook.com"}),
}
_CURSOR = re.compile(r"^[A-Za-z0-9+/=_~.%-]{1,512}$")
_ID = re.compile(r"^[0-9]{1,40}$")


def _token(token: str):
    """Never place this credential in a URL or persisted error/receipt."""
    if (not isinstance(token, str) or not 16 <= len(token) <= 8192
            or any(ord(ch) <= 32 or ord(ch) >= 127 for ch in token)):
        raise ContractError("meta_token_unavailable")


def _query(query: str, *, hashtag: bool = False) -> str:
    if not isinstance(query, str) or query != query.strip() or not 1 <= len(query) <= 160:
        raise ContractError("meta_query_invalid")
    if any(ord(c) < 32 or ord(c) == 127 for c in query):
        raise ContractError("meta_query_invalid")
    if hashtag:
        query = query.removeprefix("#")
        if not 1 <= len(query) <= 80 or not all(
            c == "_" or unicodedata.category(c).startswith(("L", "N")) for c in query
        ):
            raise ContractError("meta_hashtag_invalid")
    return query


def _permit(capability, policy, *, enabled, entitled, limit, reservation, at):
    if not policy.scope_key.startswith("workspace:"):
        raise ContractError("meta_public_workspace_required")
    admit(capability, policy, at=at, requested_scope=policy.scope_key, enabled=enabled,
          item_limit=limit, byte_limit=capability.max_response_bytes,
          reservation_microusd=reservation, entitlement_current=entitled,
          billable=policy.price_ref is not None)


def _quota(reserve, name: str, key: str, units: int):
    if not callable(reserve):
        raise ContractError("meta_durable_quota_required")
    try:
        reserve(name, key, units)
    except ContractError:
        raise
    except Exception:
        raise ContractError("meta_quota_unavailable") from None


def _cursor(cursor, cap, query_key):
    if not cursor:
        return None
    if not isinstance(cursor, dict) or set(cursor) != {"protocol", "query_digest", "after"}:
        raise ContractError("meta_cursor_domain_mismatch")
    if cursor["protocol"] != cap.version or cursor["query_digest"] != digest(query_key):
        raise ContractError("meta_cursor_domain_mismatch")
    after = cursor["after"]
    if not isinstance(after, str) or not _CURSOR.fullmatch(after):
        raise ContractError("meta_cursor_invalid")
    return after


def _next_page(data, cap, query_key):
    paging = data.get("paging") or {}
    if not isinstance(paging, dict):
        raise ContractError("meta_paging_invalid")
    cursors = paging.get("cursors") or {}
    if not isinstance(cursors, dict):
        raise ContractError("meta_paging_invalid")
    after = cursors.get("after")
    if after is None:
        return None
    if not isinstance(after, str) or not _CURSOR.fullmatch(after):
        raise ContractError("meta_paging_invalid")
    # Provider paging.next URLs are intentionally ignored (SSRF protection).
    return {"protocol": cap.version, "query_digest": digest(query_key), "after": after}


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("no offset")
        return iso(parsed.astimezone(timezone.utc))
    except (TypeError, ValueError, OverflowError):
        raise ContractError("meta_timestamp_invalid") from None


def _normalize(item, *, platform, policy, at, available_at, epoch, source_key,
               content_key, time_key, url_key, page_id=None):
    if not isinstance(item, dict):
        raise ContractError("meta_item_invalid")
    native_id = item.get("id")
    if not isinstance(native_id, str) or not re.fullmatch(r"[0-9]{1,40}(?:_[0-9]{1,40})?", native_id):
        raise ContractError("meta_identity_invalid")
    payload = {"platform": platform, "native_id": native_id,
               "author_status": "known" if page_id else "unknown",
               "language": "und", "represented_scope": {
                   "threads": "public_keyword_search_sample",
                   "instagram": "public_professional_hashtag_sample",
                   "facebook": "approved_public_page_posts_sample",
               }[platform]}
    if page_id:
        payload["author_key"] = f"facebook-page:{page_id}"
    link = item.get(url_key)
    if link is not None:
        if not isinstance(link, str) or len(link) > 2048:
            raise ContractError("meta_post_url_invalid")
        payload["canonical_url"] = safe_url(
            link, allowed_hosts=_POST_HOSTS[platform], resolve=False)
    published_at = _timestamp(item.get(time_key)) if item.get(time_key) is not None else None
    if permits(policy.rights, "store_raw", policy.scope_key, available_at):
        content = item.get(content_key)
        if isinstance(content, str):
            payload["text"] = content[:8000]
    return observation(
        policy=policy, source_identity=f"{platform}:{native_id}",
        revision_identity=digest([at, payload]),
        sequence=int(instant(at).timestamp() * 1_000_000), kind="raw_post",
        operation="create", payload=payload, event_at=published_at,
        received_at=at, available_at=available_at, coverage_epoch=epoch,
        contract_version=PROTOCOL, access_method=f"official_meta_{platform}_public_sample",
        deletion_key=f"{platform}:{native_id}")


def _fold(data, *, capability, policy, received_at, available_at, epoch,
          source_key, content_key, time_key, url_key, page_id=None, limit, size,
          query_key):
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ContractError("meta_page_invalid")
    items = data["data"]
    if len(items) > limit:
        raise ContractError("meta_page_limit")
    # Never infer a public platform population from Graph pagination.
    next_cursor = _next_page(data, capability, query_key)
    result, quarantine, seen = [], [], set()
    for index, item in enumerate(items):
        try:
            row = _normalize(
                item, platform=capability.provider_id, policy=policy, at=received_at,
                available_at=available_at, epoch=epoch, source_key=source_key,
                content_key=content_key, time_key=time_key, url_key=url_key, page_id=page_id)
            if row["source_identity"] in seen:
                continue
            seen.add(row["source_identity"])
            result.append(row)
        except ContractError as exc:
            quarantine.append({"index": index, "reason_code": exc.code})
    return Batch(tuple(result), None if quarantine else next_cursor,
                 "gap" if quarantine else "partial",
                 "health_degraded" if quarantine else "available",
                 "meta_sample_not_platform_population", bytes_received=size,
                 terminal_page=not next_cursor and not quarantine,
                 cost_microusd=0 if policy.price_ref is None else None,
                 quarantined=tuple(quarantine))


def collect_threads_keyword(*, policy: SourcePolicy, token: str, query: str,
                            received_at: str, available_at: str, coverage_epoch: str,
                            enabled: bool, entitlement_current: bool, quota_reserve,
                            limit: int = 25, search_type: str = "RECENT",
                            cursor: dict | None = None, transport=None,
                            reservation_microusd: int = 0) -> Batch:
    cap = CAPABILITIES["threads", "keyword_search"]
    query = _query(query)
    _permit(cap, policy, enabled=enabled, entitled=entitlement_current, limit=limit,
            reservation=reservation_microusd, at=received_at)
    _token(token)
    if search_type not in ("TOP", "RECENT"):
        raise ContractError("meta_search_type_invalid")
    key = ["threads", query, search_type, policy.scope_key]
    after = _cursor(cursor, cap, key)
    params = {"q": query, "search_type": search_type, "fields": "id,text,permalink,timestamp,media_type",
              "limit": limit}
    if after:
        params["after"] = after
    _quota(quota_reserve, "threads_keyword_search", policy.scope_key, 1)
    transport = transport or JsonTransport(frozenset({THREADS_HOST}))
    data, _headers, size = transport.get(
        THREADS_URL + "?" + urlencode(params), max_bytes=cap.max_response_bytes,
        timeout=cap.timeout_seconds, headers={"Authorization": "Bearer " + token})
    return _fold(data, capability=cap, policy=policy, received_at=received_at,
                 available_at=available_at, epoch=coverage_epoch, source_key=digest(key),
                 content_key="text", time_key="timestamp", url_key="permalink",
                 limit=limit, size=size, query_key=key)


def collect_instagram_hashtag(*, policy: SourcePolicy, token: str, ig_user_id: str,
                              hashtag: str, received_at: str, available_at: str,
                              coverage_epoch: str, enabled: bool, entitlement_current: bool,
                              quota_reserve, limit: int = 25, cursor: dict | None = None,
                              transport=None, reservation_microusd: int = 0) -> Batch:
    cap = CAPABILITIES["instagram", "hashtag_discovery"]
    hashtag = _query(hashtag, hashtag=True)
    _permit(cap, policy, enabled=enabled, entitled=entitlement_current, limit=limit,
            reservation=reservation_microusd, at=received_at)
    _token(token)
    if not isinstance(ig_user_id, str) or not _ID.fullmatch(ig_user_id):
        raise ContractError("meta_professional_identity_required")
    key = ["instagram", ig_user_id, hashtag, policy.scope_key]
    after = _cursor(cursor, cap, key)
    # Caller must reserve atomically per professional account and rolling seven-day
    # distinct hashtag window. A process-local counter is never sufficient.
    _quota(quota_reserve, "instagram_distinct_hashtag_7d", ig_user_id + ":" + hashtag, 1)
    transport = transport or JsonTransport(frozenset({FACEBOOK_HOST}))
    auth = {"Authorization": "Bearer " + token}
    params = {"user_id": ig_user_id, "q": hashtag}
    first, _headers, size1 = transport.get(
        INSTAGRAM_URL + "?" + urlencode(params), max_bytes=10_000,
        timeout=cap.timeout_seconds, headers=auth)
    hashtags = first.get("data") if isinstance(first, dict) else None
    if not isinstance(hashtags, list) or len(hashtags) > 1:
        raise ContractError("meta_hashtag_lookup_invalid")
    if not hashtags:
        return Batch((), None, "partial", "available", "meta_hashtag_not_found",
                     bytes_received=size1, terminal_page=True,
                     cost_microusd=0 if policy.price_ref is None else None)
    hashtag_id = hashtags[0].get("id") if isinstance(hashtags[0], dict) else None
    if not isinstance(hashtag_id, str) or not _ID.fullmatch(hashtag_id):
        raise ContractError("meta_hashtag_identity_invalid")
    params = {"user_id": ig_user_id, "fields": "id,caption,media_type,permalink,timestamp",
              "limit": limit}
    if after:
        params["after"] = after
    _quota(quota_reserve, "instagram_graph_request", policy.scope_key, 1)
    second, _headers, size2 = transport.get(
        f"{FACEBOOK_BASE}/{hashtag_id}/recent_media?" + urlencode(params),
        max_bytes=cap.max_response_bytes-size1, timeout=cap.timeout_seconds,
        headers=auth)
    return _fold(second, capability=cap, policy=policy, received_at=received_at,
                 available_at=available_at, epoch=coverage_epoch, source_key=digest(key),
                 content_key="caption", time_key="timestamp", url_key="permalink",
                 limit=limit, size=size1+size2, query_key=key)


def collect_facebook_public_page(*, policy: SourcePolicy, token: str,
                                 reviewed_page_id: str, received_at: str,
                                 available_at: str, coverage_epoch: str, enabled: bool,
                                 entitlement_current: bool, quota_reserve,
                                 limit: int = 25, cursor: dict | None = None,
                                 transport=None, reservation_microusd: int = 0) -> Batch:
    cap = CAPABILITIES["facebook", "page_public_posts"]
    _permit(cap, policy, enabled=enabled, entitled=entitlement_current, limit=limit,
            reservation=reservation_microusd, at=received_at)
    _token(token)
    if not isinstance(reviewed_page_id, str) or not _ID.fullmatch(reviewed_page_id):
        raise ContractError("meta_page_identity_unreviewed")
    key = ["facebook", reviewed_page_id, policy.scope_key]
    after = _cursor(cursor, cap, key)
    params = {"fields": "id,message,created_time,permalink_url", "limit": limit}
    if after:
        params["after"] = after
    _quota(quota_reserve, "facebook_public_page_read", reviewed_page_id, 1)
    transport = transport or JsonTransport(frozenset({FACEBOOK_HOST}))
    data, _headers, size = transport.get(
        f"{FACEBOOK_BASE}/{reviewed_page_id}/posts?" + urlencode(params),
        max_bytes=cap.max_response_bytes, timeout=cap.timeout_seconds,
        headers={"Authorization": "Bearer " + token})
    return _fold(data, capability=cap, policy=policy, received_at=received_at,
                 available_at=available_at, epoch=coverage_epoch, source_key=reviewed_page_id,
                 content_key="message", time_key="created_time",
                 url_key="permalink_url", page_id=reviewed_page_id,
                 limit=limit, size=size, query_key=key)
