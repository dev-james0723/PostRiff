"""Explicit instance-local public sample. No federation-wide completeness assertion."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit

from ..contracts import ContractError, digest, instant, permits
from ..policy import ProviderCapability, SourcePolicy, admit
from .base import Batch, JsonTransport, observation, safe_url

VERSION = "mastodon-public-timeline-v1-20260927"


def capability(instance: str) -> ProviderCapability:
    parsed = urlsplit(instance)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment or parsed.username or parsed.port not in (None, 443)):
        raise ContractError('invalid_instance')
    return ProviderCapability('mastodon', 'public_timeline', VERSION, ('raw_post',),
        instance.rstrip('/') + '/api/v1/timelines/public', 'REST-v1',
        'instance_public_or_read_statuses', (), 40, 400_000, 15, 3,
        'instance_contract', 'status-delete/refresh/account-revocation')


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts = []
    def handle_data(self, data):
        self.parts.append(data)
    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br"):
            self.parts.append("\n")
        if tag == "img":
            self.parts.append(dict(attrs).get("alt", ""))


def normalize_status(status: dict, *, policy: SourcePolicy, received_at: str, available_at: str,
                     coverage_epoch: str) -> dict:
    if not isinstance(status, dict) or status.get("visibility") != "public":
        raise ContractError("mastodon_nonpublic_status")
    native_id = status.get("id")
    if not isinstance(native_id, str) or not native_id.isdigit():
        raise ContractError("mastodon_identity_required")
    uri = status.get("uri")
    if not isinstance(uri, str) or not uri.startswith("https://"):
        raise ContractError("mastodon_canonical_identity_required")
    event_at = status.get("created_at")
    if event_at:
        instant(event_at)
    revision = status.get("edited_at") or event_at or received_at
    sequence = int(instant(revision).timestamp() * 1_000_000)
    author = status.get("account") or {}
    author_id = author.get("uri")
    payload = {"platform": "mastodon", "native_id": uri, "instance_item_id": native_id,
               "canonical_url": status.get("url") or uri, "author_key": "mastodon:" + author_id if author_id else None,
               "author_status": "known" if author_id else "unknown", "language": status.get("language") if status.get("language") in
               ("en", "yue", "zh-Hant", "zh-Hans") else "und", "is_repost": bool(status.get("reblog")),
               "represented_scope": "selected_instance_local_public_timeline"}
    if permits(policy.rights, "store_raw", policy.scope_key, available_at):
        parser = _Text(); parser.feed(status.get("content") or ""); payload["text"] = "".join(parser.parts).strip()
    if permits(policy.rights, "store_metrics", policy.scope_key, available_at):
        payload["provider_metrics"] = {k: {"value": status.get(k), "null_reason": "not_returned" if status.get(k) is None else None,
                                          "definition": VERSION + ":" + k, "observed_at": received_at,
                                          "time_basis": "retrieval"} for k in ("replies_count", "reblogs_count", "favourites_count")}
    return observation(policy=policy, source_identity=uri, revision_identity=revision + ":" + digest(payload),
                       sequence=sequence, kind="raw_post", operation="update" if status.get("edited_at") else "create",
                       payload=payload, event_at=event_at, received_at=received_at, available_at=available_at,
                       coverage_epoch=coverage_epoch, contract_version=VERSION, access_method="official_instance_public_timeline")


def collect(*, instance: str, policy: SourcePolicy, enabled: bool, entitlement_current: bool,
            received_at: str, available_at: str, coverage_epoch: str, cursor: dict | None = None,
            limit: int = 40, transport=None, token: str | None = None, reservation_microusd: int = 0) -> Batch:
    parsed = urlsplit(instance)
    if parsed.scheme != "https" or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
        raise ContractError("invalid_instance")
    host = parsed.hostname
    endpoint = instance.rstrip("/") + "/api/v1/timelines/public"
    cap = capability(instance)
    admit(cap, policy, at=received_at, requested_scope=policy.scope_key, enabled=enabled,
          item_limit=limit, byte_limit=400_000, reservation_microusd=reservation_microusd,
          entitlement_current=entitlement_current, billable=policy.price_ref is not None)
    if cursor and (cursor.get("host") != host or cursor.get("protocol") != VERSION):
        raise ContractError("cursor_domain_mismatch")
    if transport is None:
        safe_url(endpoint, allowed_hosts=frozenset((host,)))
        transport = JsonTransport(frozenset((host,)))
    query = {"local": "true", "limit": limit}
    if cursor and cursor.get("max_id"):
        if not str(cursor["max_id"]).isdigit():
            raise ContractError("invalid_cursor")
        query["max_id"] = cursor["max_id"]
    rows, _headers, size = transport.get(endpoint + "?" + urlencode(query), max_bytes=400_000, timeout=15,
                                        headers={"Authorization": "Bearer " + token} if token else {})
    if not isinstance(rows, list) or len(rows) > limit:
        raise ContractError("provider_page_limit")
    observations, quarantine = [], []
    for index, row in enumerate(rows):
        try:
            observations.append(normalize_status(row, policy=policy, received_at=received_at,
                                                 available_at=available_at, coverage_epoch=coverage_epoch))
        except ContractError as exc:
            quarantine.append({"index": index, "reason_code": exc.code})
    last = rows[-1].get("id") if rows and not quarantine else (cursor or {}).get("max_id")
    next_cursor = cursor if quarantine else {"host": host, "protocol": VERSION, "max_id": last}
    return Batch(tuple(observations), next_cursor,
                 "gap" if quarantine else "partial", "health_degraded" if quarantine else "available",
                 "instance_sample_not_federation", bytes_received=size, terminal_page=len(rows) < limit,
                 cost_microusd=0 if policy.price_ref is None else None, quarantined=tuple(quarantine))
