"""Opt-in read-only Meta public sampling. NOT production-bound without App Review.

This module implements fixed-host, bounded provider reads and normalized sampled
observations. It does not fetch credentials, register itself, acquire Meta access,
claim full-network coverage or perform any model evaluation. Callers must supply
verified workspace-scoped policies, connected identity proof and durable quota
admission. Tests use injected HTTP transports only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import hmac
import json
import re
import subprocess
import sys
import time
from types import MappingProxyType
import unicodedata
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit

from ..contracts import ContractError, digest, instant, iso, permits
from ..policy import ProviderCapability, SourcePolicy, admit
from .base import Batch, observation, safe_url
from ....provider_base import GRAPH_VERSION

THREADS_HOST = "graph.threads.net"
FACEBOOK_HOST = "graph.facebook.com"
THREADS_VERSION = "v1.0"
THREADS_URL = f"https://{THREADS_HOST}/{THREADS_VERSION}/keyword_search"
INSTAGRAM_URL = f"https://{FACEBOOK_HOST}/{GRAPH_VERSION}/ig_hashtag_search"
FACEBOOK_BASE = f"https://{FACEBOOK_HOST}/{GRAPH_VERSION}"
PROTOCOL = f"meta-threads-{THREADS_VERSION}-graph-{GRAPH_VERSION}-read-only-20261008"
MAX_ITEMS = 50
MAX_BYTES = 400_000

CAPABILITIES = MappingProxyType({
    ("threads", "keyword_search"): ProviderCapability(
        "threads", "keyword_search", PROTOCOL, ("raw_post",), THREADS_URL,
        "official_graph_json", "threads_user_oauth",
        ("threads_basic", "threads_keyword_search"), MAX_ITEMS, MAX_BYTES, 15, 1,
        "threads_search_quota", "refresh/deletion/revocation"),
    ("instagram", "hashtag_discovery"): ProviderCapability(
        "instagram", "hashtag_discovery", PROTOCOL, ("raw_post",), INSTAGRAM_URL,
        "official_graph_json", "facebook_login_instagram_professional",
        ("instagram_basic",),
        MAX_ITEMS, MAX_BYTES, 15, 1, "ig_rolling_7_day_hashtag_quota",
        "refresh/deletion/revocation"),
    ("facebook", "page_public_posts"): ProviderCapability(
        "facebook", "page_public_posts", PROTOCOL, ("raw_post",), FACEBOOK_BASE,
        "official_graph_json", "app_or_system_user_with_ppca",
        (), MAX_ITEMS, MAX_BYTES, 15, 1,
        "facebook_ppca_page_quota", "refresh/deletion/revocation"),
})

# Reviewed features are independent of OAuth token scopes.
APPROVAL_MANIFEST = MappingProxyType({
    ("threads", "keyword_search"): (THREADS_VERSION, "threads_login", ("user",), ()),
    ("instagram", "hashtag_discovery"): (GRAPH_VERSION, "facebook_login", ("business", "creator"), ("instagram_public_content_access",)),
    ("facebook", "page_public_posts"): (GRAPH_VERSION, "facebook_login", ("app", "system_user"), ("pages_public_content_access",)),
})


@dataclass(frozen=True)
class ReviewProof:
    """Server assertion from the encrypted-vault/authorization resolver, never a job input."""
    review_id: str
    review_ref: str
    app_id: str
    provider_id: str
    operation: str
    api_version: str
    scope_key: str
    login_kind: str
    account_id: str
    account_kind: str
    token_fingerprint: str
    verified_scopes: tuple[str, ...]
    approved_scopes: tuple[str, ...]
    approved_features: tuple[str, ...]
    verified_at: str
    expires_at: str
    quota_rule_ref: str
    quota_limit: int
    quota_window_seconds: int
    reviewed_page_ids: tuple[str, ...] = ()
    page_public: bool = False
    page_restricted: bool = True
    consent_current: bool = False

    def __post_init__(self):
        for name in ("review_id", "review_ref", "app_id", "account_id", "quota_rule_ref"):
            value = getattr(self, name)
            if not isinstance(value, str) or not 1 <= len(value) <= 256 or any(ord(c) < 32 for c in value):
                raise ContractError("meta_review_evidence_required")
        for name in ("verified_scopes", "approved_scopes", "approved_features", "reviewed_page_ids"):
            value = getattr(self, name)
            if type(value) is not tuple or any(not isinstance(item, str) for item in value):
                raise ContractError("meta_review_immutable_required")
        if not isinstance(self.token_fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", self.token_fingerprint):
            raise ContractError("meta_review_token_unverified")
        if any(type(value) is not int or value <= 0 for value in (self.quota_limit, self.quota_window_seconds)):
            raise ContractError("meta_review_quota_unverified")
        if instant(self.verified_at) >= instant(self.expires_at):
            raise ContractError("meta_review_expired")


def token_fingerprint(token: str) -> str:
    _token(token)
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def validate_review(review, capability, policy, token, at, *, account_id=None, page_id=None):
    if not isinstance(review, ReviewProof):
        raise ContractError("meta_review_required")
    version, login, account_kinds, features = APPROVAL_MANIFEST[capability.provider_id, capability.operation]
    if ((review.provider_id, review.operation, review.api_version, review.scope_key) !=
            (capability.provider_id, capability.operation, version, policy.scope_key)
            or review.login_kind != login or review.account_kind not in account_kinds):
        raise ContractError("meta_review_domain_mismatch")
    if not hmac.compare_digest(review.token_fingerprint, token_fingerprint(token)):
        raise ContractError("meta_review_token_unverified")
    if (not set(capability.required_scopes) <= set(review.verified_scopes)
            or not set(capability.required_scopes) <= set(review.approved_scopes)
            or not set(features) <= set(review.approved_features)):
        raise ContractError("meta_review_grant_unverified")
    if review.consent_current is not True:
        raise ContractError("meta_review_consent_required")
    age = (instant(at) - instant(review.verified_at)).total_seconds()
    if not 0 <= age <= 900 or instant(at) >= instant(review.expires_at):
        raise ContractError("meta_review_expired")
    if account_id is not None and review.account_id != account_id:
        raise ContractError("meta_review_account_mismatch")
    if capability.provider_id == "instagram" and (review.quota_limit > 30 or review.quota_window_seconds != 604800):
        raise ContractError("meta_review_quota_unverified")
    if page_id is not None and (page_id not in review.reviewed_page_ids
                               or review.page_public is not True or review.page_restricted is not False):
        raise ContractError("meta_page_identity_unreviewed")

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
    approved = False
    reason = "meta_quota_unavailable"
    try:
        approved = reserve(name, key, units) is True
    except ContractError as exc:
        if exc.code in {"meta_provider_quota_exhausted", "meta_quota_rule_unverified",
                        "meta_quota_invalid", "meta_quota_domain_mismatch"}:
            reason = exc.code
    except Exception:
        pass
    if not approved:
        raise ContractError(reason)


class MetaTransportError(ContractError):
    """Only safe worker admission/backoff metadata; no provider error body or URL."""
    def __init__(self, code: str, *, status: int | None, retry_after_seconds: int | None = None):
        super().__init__(code)
        self.status = status if type(status) is int and 100 <= status <= 599 else None
        self.retry_after_seconds = (max(0, min(retry_after_seconds, 86400))
                                    if type(retry_after_seconds) is int else None)


def _retry_after(headers):
    if headers is None:
        return None
    try:
        value = headers.get("Retry-After")
        if not isinstance(value, str) or not 1 <= len(value) <= 128:
            return None
        value = value.strip()
        if re.fullmatch(r"[0-9]{1,64}", value):
            return min(int(value), 86400)
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return None
        return max(0, min(int(parsed.timestamp() - time.time()), 86400))
    except (TypeError, ValueError, OverflowError, AttributeError):
        return None


# Isolated stdlib process: DNS, TLS and slow reads can all be terminated by the
# parent's monotonic watchdog. No token appears in command args or environment.
_HTTPS_WORKER = r'''
import json, sys, urllib.request, urllib.error
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("redirect_refused")
result = {"error": "meta_transport_unavailable", "status": None}
try:
    request = json.loads(sys.stdin.buffer.read(32769))
    req = urllib.request.Request(request["url"], headers={"Accept": "application/json", **request["headers"]})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=request["timeout"]) as response:
        body = response.read(request["max_bytes"] + 1)
    if len(body) > request["max_bytes"]:
        result = {"error": "meta_response_byte_limit", "status": None}
    else:
        data = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        result = {"data": data, "bytes": len(body)}
except urllib.error.HTTPError as error:
    retry = error.headers.get("Retry-After") if error.headers else None
    result = {"error": "meta_transport_unavailable", "status": error.code,
              "retry_after": retry if isinstance(retry, str) and len(retry) <= 128 else None}
    error.close()
except Exception:
    pass
encoded = json.dumps(result, ensure_ascii=True, allow_nan=False).encode("utf-8")
if len(encoded) > 2000000:
    encoded = b'{"error":"meta_response_byte_limit","status":null}'
sys.stdout.buffer.write(encoded)
'''


class MetaDeadlineTransport:
    """One reaped process per request; hard deadline includes DNS and body read."""
    def __init__(self, allowed_hosts: frozenset[str]):
        if not allowed_hosts or not allowed_hosts <= frozenset({THREADS_HOST, FACEBOOK_HOST}):
            raise ContractError("meta_transport_host_invalid")
        self.allowed_hosts = frozenset(allowed_hosts)

    def get(self, url: str, *, max_bytes: int, timeout: float, headers: dict | None = None,
            deadline: float | None = None):
        if type(timeout) not in (int, float) or not 0 < timeout <= 15:
            raise ContractError("meta_time_budget_exceeded")
        deadline = deadline if deadline is not None else time.monotonic() + timeout
        url = safe_url(url, allowed_hosts=self.allowed_hosts, resolve=False)
        parsed = urlsplit(url)
        valid_path = (parsed.hostname == THREADS_HOST and parsed.path == f"/{THREADS_VERSION}/keyword_search"
                      or parsed.hostname == FACEBOOK_HOST and
                      re.fullmatch(rf"/{re.escape(GRAPH_VERSION)}/(?:ig_hashtag_search|[0-9]{{1,40}}/(?:recent_media|posts))", parsed.path))
        if not valid_path or len(url) > 4096:
            raise ContractError("meta_transport_endpoint_invalid")
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
            raise ContractError("meta_response_byte_limit")
        if (not isinstance(headers, dict) or set(headers) != {"Authorization"}
                or not isinstance(headers["Authorization"], str)
                or not headers["Authorization"].startswith("Bearer ")):
            raise ContractError("meta_transport_headers_invalid")
        _token(headers["Authorization"][7:])
        if any(name.lower() in {"access_token", "token", "authorization", "appsecret_proof"}
               for name, _ in parse_qsl(parsed.query)):
            raise ContractError("meta_transport_endpoint_invalid")
        request = json.dumps({"url": url, "headers": headers, "max_bytes": max_bytes,
                              "timeout": max(0.001, deadline-time.monotonic())}).encode("utf-8")
        if len(request) > 32768 or time.monotonic() >= deadline:
            raise ContractError("meta_time_budget_exceeded")
        child = None
        output = None
        failure = None
        try:
            child = subprocess.Popen([sys.executable, "-I", "-S", "-c", _HTTPS_WORKER],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env={}, cwd="/")
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                failure = "meta_time_budget_exceeded"
            else:
                output, _ = child.communicate(request, timeout=remaining)
                if child.returncode != 0:
                    failure = "meta_transport_unavailable"
        except subprocess.TimeoutExpired:
            failure = "meta_time_budget_exceeded"
        except Exception:
            failure = "meta_transport_unavailable"
        finally:
            if child is not None:
                if child.poll() is None:
                    child.kill()
                child.communicate()
        if failure:
            raise ContractError(failure)
        if time.monotonic() > deadline:
            raise ContractError("meta_time_budget_exceeded")
        if output is None or len(output) > 2_000_000:
            raise ContractError("meta_response_byte_limit")
        result = None
        try:
            result = json.loads(output)
        except (ValueError, UnicodeError):
            pass
        if not isinstance(result, dict):
            raise ContractError("meta_transport_unavailable")
        if "error" in result:
            status = result.get("status")
            status = status if type(status) is int and 100 <= status <= 599 else None
            code = {401:"meta_access_pending", 403:"meta_rights_suspended", 429:"meta_rate_limited"}.get(status, "meta_transport_unavailable")
            if result.get("error") == "meta_response_byte_limit":
                code = "meta_response_byte_limit"
            raise MetaTransportError(code, status=status,
                retry_after_seconds=_retry_after({"Retry-After":result.get("retry_after")}))
        size = result.get("bytes")
        if type(size) is not int or not 0 <= size <= max_bytes or "data" not in result:
            raise ContractError("meta_response_byte_limit")
        return result["data"], {}, size


def _fetch(transport, url, *, max_bytes, deadline, headers, on_http_start=None):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ContractError("meta_time_budget_exceeded")
    if on_http_start is not None:
        if not callable(on_http_start):
            raise ContractError("meta_http_tracking_unavailable")
        tracked = False
        try:
            on_http_start()
            tracked = True
        except Exception:
            pass
        if not tracked:
            raise ContractError("meta_http_tracking_unavailable")
    failure = None
    status = retry_after = None
    try:
        absolute_deadline = {"deadline":deadline} if isinstance(transport, MetaDeadlineTransport) else {}
        data, response_headers, size = transport.get(
            url, max_bytes=max_bytes, timeout=remaining, headers=headers, **absolute_deadline)
    except Exception as exc:
        status = getattr(exc, "status", getattr(exc, "code", None))
        status = status if type(status) is int and 100 <= status <= 599 else None
        retry_after = getattr(exc, "retry_after_seconds", None)
        if type(retry_after) is not int:
            retry_after = _retry_after(getattr(exc, "headers", None))
        failure = {401: "meta_access_pending", 403: "meta_rights_suspended", 429: "meta_rate_limited"}.get(status, "meta_transport_unavailable")
        if isinstance(exc, ContractError) and exc.code in {"meta_time_budget_exceeded", "meta_response_byte_limit"}:
            failure = exc.code
        if isinstance(exc, HTTPError):
            try:
                exc.close()
            except Exception:
                pass
    # Raise outside the handler so credential-bearing exceptions are not chained.
    if failure:
        raise MetaTransportError(failure, status=status, retry_after_seconds=retry_after)
    if time.monotonic() > deadline:
        raise ContractError("meta_time_budget_exceeded")
    if type(size) is not int or not 0 <= size <= max_bytes:
        raise ContractError("meta_response_byte_limit")
    if isinstance(data, dict) and "error" in data:
        raise ContractError("meta_provider_error")
    return data, response_headers, size


def _cursor(cursor, cap, query_key):
    if cursor is None:
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
    paging = data.get("paging", {})
    if not isinstance(paging, dict):
        raise ContractError("meta_paging_invalid")
    cursors = paging.get("cursors", {})
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
    if platform != "facebook" and not _ID.fullmatch(native_id):
        raise ContractError("meta_identity_invalid")
    if page_id and not native_id.startswith(page_id + "_"):
        raise ContractError("meta_page_post_identity_mismatch")
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
        if any(name.lower() in {"access_token", "token", "authorization", "appsecret_proof"}
               for name, _ in parse_qsl(urlsplit(payload["canonical_url"]).query)):
            raise ContractError("meta_post_url_invalid")
    published_at = _timestamp(item.get(time_key)) if item.get(time_key) is not None else None
    if permits(policy.rights, "store_raw", policy.scope_key, available_at):
        content = item.get(content_key)
        if isinstance(content, str):
            payload["text"] = content[:8000]
    # The same native content acquired under a new reviewed grant must get a
    # fresh rights-bound node. Reuse within a policy is still canonical; revoked
    # historical evidence is never rebound or granted a longer retention period.
    value = observation(
        policy=policy, source_identity=f"{platform}:{native_id}",
        revision_identity=digest([policy.version, published_at, payload]),
        sequence=int(instant(at).timestamp() * 1_000_000), kind="raw_post",
        operation="create", payload=payload, event_at=published_at,
        received_at=at, available_at=available_at, coverage_epoch=epoch,
        contract_version=PROTOCOL, access_method=f"official_meta_{platform}_public_sample",
        deletion_key=f"{platform}:{native_id}")
    value['provenance']['content_revision_digest'] = digest([published_at, payload])
    return value


def _fold(data, *, capability, policy, received_at, available_at, epoch,
          source_key, content_key, time_key, url_key, page_id=None, limit, size,
          query_key, review, sampling_mode, synthetic, token):
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ContractError("meta_page_invalid")
    items = data["data"]
    if len(items) > limit:
        raise ContractError("meta_page_limit")
    # Never infer a public platform population from Graph pagination.
    next_cursor = _next_page(data, capability, query_key)
    if next_cursor and token in next_cursor["after"]:
        raise ContractError("meta_paging_invalid")
    result, quarantine, seen = [], [], set()
    for index, item in enumerate(items):
        try:
            if token in str(item):
                raise ContractError("meta_credential_echo_refused")
            row = _normalize(
                item, platform=capability.provider_id, policy=policy, at=received_at,
                available_at=available_at, epoch=epoch, source_key=source_key,
                content_key=content_key, time_key=time_key, url_key=url_key, page_id=page_id)
            row["provenance"].update({"review_id": review.review_id,
                "operation": capability.operation, "api_version": review.api_version,
                "query_digest": digest(query_key), "query": query_key[2] if capability.provider_id == "instagram" else query_key[1],
                "sampling_mode": sampling_mode, "account_id": review.account_id,
                "sampling_frame": row["payload"]["represented_scope"],
                "evidence_kind": "synthetic" if synthetic else "provider_response",
                "third_party": "unverified"})
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
                            reservation_microusd: int = 0, review: ReviewProof | None = None, on_http_start=None) -> Batch:
    deadline = time.monotonic() + 15
    synthetic = transport is not None
    cap = CAPABILITIES["threads", "keyword_search"]
    query = _query(query)
    _permit(cap, policy, enabled=enabled, entitled=entitlement_current, limit=limit,
            reservation=reservation_microusd, at=received_at)
    validate_review(review, cap, policy, token, received_at)
    if search_type not in ("TOP", "RECENT"):
        raise ContractError("meta_search_type_invalid")
    key = ["threads", query, search_type, policy.scope_key, review.review_id, review.app_id, review.account_id]
    after = _cursor(cursor, cap, key)
    params = {"q": query, "search_type": search_type, "fields": "id,text,permalink,timestamp,media_type",
              "limit": limit}
    if after:
        params["after"] = after
    _quota(quota_reserve, "threads_keyword_search", policy.scope_key, 1)
    transport = transport or MetaDeadlineTransport(frozenset({THREADS_HOST}))
    data, _headers, size = _fetch(transport,
        THREADS_URL + "?" + urlencode(params), max_bytes=cap.max_response_bytes,
        deadline=deadline, on_http_start=on_http_start, headers={"Authorization": "Bearer " + token})
    return _fold(data, capability=cap, policy=policy, received_at=received_at,
                 available_at=available_at, epoch=coverage_epoch, source_key=digest(key),
                 content_key="text", time_key="timestamp", url_key="permalink",
                 limit=limit, size=size, query_key=key, review=review,
                 sampling_mode=search_type, synthetic=synthetic, token=token)


def collect_instagram_hashtag(*, policy: SourcePolicy, token: str, ig_user_id: str,
                              hashtag: str, received_at: str, available_at: str,
                              coverage_epoch: str, enabled: bool, entitlement_current: bool,
                              quota_reserve, limit: int = 25, cursor: dict | None = None,
                              transport=None, reservation_microusd: int = 0, review: ReviewProof | None = None, on_http_start=None) -> Batch:
    deadline = time.monotonic() + 15
    synthetic = transport is not None
    cap = CAPABILITIES["instagram", "hashtag_discovery"]
    hashtag = _query(hashtag, hashtag=True)
    _permit(cap, policy, enabled=enabled, entitled=entitlement_current, limit=limit,
            reservation=reservation_microusd, at=received_at)
    validate_review(review, cap, policy, token, received_at, account_id=ig_user_id)
    if not isinstance(ig_user_id, str) or not _ID.fullmatch(ig_user_id):
        raise ContractError("meta_professional_identity_required")
    key = ["instagram", ig_user_id, hashtag, policy.scope_key, review.review_id, review.app_id]
    after = _cursor(cursor, cap, key)
    # Caller must reserve atomically per professional account and rolling seven-day
    # distinct hashtag window. A process-local counter is never sufficient.
    _quota(quota_reserve, "instagram_distinct_hashtag_7d", ig_user_id + ":" + hashtag, 1)
    transport = transport or MetaDeadlineTransport(frozenset({FACEBOOK_HOST}))
    auth = {"Authorization": "Bearer " + token}
    params = {"user_id": ig_user_id, "q": hashtag}
    _quota(quota_reserve, "instagram_graph_request", policy.scope_key, 1)
    first, _headers, size1 = _fetch(transport,
        INSTAGRAM_URL + "?" + urlencode(params), max_bytes=10_000,
        deadline=deadline, on_http_start=on_http_start, headers=auth)
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
    second, _headers, size2 = _fetch(transport,
        f"{FACEBOOK_BASE}/{hashtag_id}/recent_media?" + urlencode(params),
        max_bytes=cap.max_response_bytes-size1, deadline=deadline, on_http_start=on_http_start,
        headers=auth)
    return _fold(second, capability=cap, policy=policy, received_at=received_at,
                 available_at=available_at, epoch=coverage_epoch, source_key=digest(key),
                 content_key="caption", time_key="timestamp", url_key="permalink",
                 limit=limit, size=size1+size2, query_key=key, review=review,
                 sampling_mode="RECENT", synthetic=synthetic, token=token)


def collect_facebook_public_page(*, policy: SourcePolicy, token: str,
                                 reviewed_page_id: str, received_at: str,
                                 available_at: str, coverage_epoch: str, enabled: bool,
                                 entitlement_current: bool, quota_reserve,
                                 limit: int = 25, cursor: dict | None = None,
                                 transport=None, reservation_microusd: int = 0, review: ReviewProof | None = None, on_http_start=None) -> Batch:
    deadline = time.monotonic() + 15
    synthetic = transport is not None
    cap = CAPABILITIES["facebook", "page_public_posts"]
    _permit(cap, policy, enabled=enabled, entitled=entitlement_current, limit=limit,
            reservation=reservation_microusd, at=received_at)
    validate_review(review, cap, policy, token, received_at, page_id=reviewed_page_id)
    if not isinstance(reviewed_page_id, str) or not _ID.fullmatch(reviewed_page_id):
        raise ContractError("meta_page_identity_unreviewed")
    key = ["facebook", reviewed_page_id, policy.scope_key, review.review_id, review.app_id, review.account_id]
    after = _cursor(cursor, cap, key)
    params = {"fields": "id,message,created_time,permalink_url", "limit": limit}
    if after:
        params["after"] = after
    _quota(quota_reserve, "facebook_public_page_read", reviewed_page_id, 1)
    transport = transport or MetaDeadlineTransport(frozenset({FACEBOOK_HOST}))
    data, _headers, size = _fetch(transport,
        f"{FACEBOOK_BASE}/{reviewed_page_id}/posts?" + urlencode(params),
        max_bytes=cap.max_response_bytes, deadline=deadline, on_http_start=on_http_start,
        headers={"Authorization": "Bearer " + token})
    return _fold(data, capability=cap, policy=policy, received_at=received_at,
                 available_at=available_at, epoch=coverage_epoch, source_key=reviewed_page_id,
                 content_key="message", time_key="created_time",
                 url_key="permalink_url", page_id=reviewed_page_id,
                 limit=limit, size=size, query_key=key, review=review,
                 sampling_mode="APPROVED_PAGE", synthetic=synthetic, token=token)
