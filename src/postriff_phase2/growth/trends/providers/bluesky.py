"""Pinned Jetstream v2 JSON folding boundary; archive replay requires a separate paid admission.

Protocol reference: bluesky-social/jetstream@3fa54fdbb0f47ad3aa43de78a6fbbd8dc362f81d.
Sequence cursors are inclusive and instance-local. Marker events must never be filtered out.
"""
from __future__ import annotations

import json
import time
from urllib.parse import urlencode

from ..contracts import ContractError, canonical, instant, permits
from ..policy import ProviderCapability, SourcePolicy, admit
from .base import Batch, observation, safe_url

PROTOCOL = "jetstream-v2-json@3fa54fdbb0f47ad3aa43de78a6fbbd8dc362f81d"
HOST = "jetstream.us-west.bsky.network"
PATH = "/xrpc/network.bsky.jetstream.subscribeEvents"
CAPABILITY = ProviderCapability("bluesky", "live_sample", PROTOCOL, ("raw_post",), "wss://" + HOST + PATH,
                                "xrpc.v1.json", "public", (), 250, 1_000_000, 30, 3,
                                "unmetered_live_bytes_bounded", "commit-delete/account/sync")


def normalize_frame(frame: dict, *, policy: SourcePolicy, received_at: str, available_at: str,
                    coverage_epoch: str) -> tuple[dict | None, dict | None, int | None]:
    if not isinstance(frame, dict) or frame.get("$type") != "message" or not isinstance(frame.get("payload"), dict):
        raise ContractError("jetstream_invalid_frame")
    data = frame["payload"]
    kind = str(data.get("$type", "")).removeprefix("network.bsky.jetstream.subscribeEvents#")
    if kind == "info":
        return None, {"kind": "gap", "reason_code": "cursor_clamped"}, None
    seq = data.get("seq")
    if type(seq) is not int or not 1 <= seq < 2**63:
        raise ContractError("jetstream_sequence_required")
    did = data.get("did")
    if not isinstance(did, str) or not did.startswith(("did:plc:", "did:web:")) or len(did) > 256:
        raise ContractError("jetstream_identity_required")
    if kind in ("account", "sync", "identity"):
        return None, {"kind": kind, "did": did, "sequence": seq, "active": data.get("active"),
                      "status": data.get("status"), "available_at": available_at,
                      "requires_reconciliation": kind == "sync"}, seq
    if kind != "commit":
        raise ContractError("jetstream_unknown_event")
    if data.get("collection") != "app.bsky.feed.post":
        return None, None, seq
    op, rkey = data.get("operation"), data.get("rkey")
    if op not in ("create", "update", "delete") or not isinstance(rkey, str) or not rkey or len(rkey) > 256 or "/" in rkey:
        raise ContractError("jetstream_invalid_record")
    identity = f"at://{did}/app.bsky.feed.post/{rkey}"
    payload = {"platform": "bluesky"}
    event_at = None
    if op != "delete":
        record = data.get("record")
        if not isinstance(record, dict) or record.get("$type") != "app.bsky.feed.post":
            raise ContractError("jetstream_invalid_record")
        if record.get("createdAt") is not None:
            instant(record["createdAt"]); event_at = record["createdAt"]
        language = next((x for x in record.get("langs", []) if x in ("en", "zh-Hant", "zh-Hans", "yue")), "und")
        payload.update(native_id=identity, author_key=f"bluesky:{did}", author_status="known", language=language,
                       canonical_url=f"https://bsky.app/profile/{did}/post/{rkey}", is_repost=False)
        if permits(policy.rights, "store_raw", policy.scope_key, available_at):
            payload["text"] = record.get("text", "")
        reply = record.get("reply")
        if isinstance(reply, dict):
            payload["relations"] = [{"type": "reply", "target": part["uri"]} for part in
                                    [reply.get("parent", {})] if isinstance(part, dict) and isinstance(part.get("uri"), str)]
    row = observation(policy=policy, source_identity=identity, revision_identity=f"{data.get('rev', seq)}:{op}:{seq}",
                      sequence=seq, kind="raw_post", operation=op, payload=payload, event_at=event_at,
                      received_at=received_at, available_at=available_at, coverage_epoch=coverage_epoch,
                      contract_version=PROTOCOL, access_method="official_public_stream", deletion_key=identity)
    return row, None, seq


def fold_frames(frames, *, policy: SourcePolicy, received_at: str, available_at: str,
                coverage_epoch: str, cursor: dict | None = None, max_items: int = 250, max_bytes: int = 1_000_000) -> Batch:
    if not 1 <= max_items <= CAPABILITY.max_items or not 1 <= max_bytes <= CAPABILITY.max_response_bytes:
        raise ContractError("batch_limit")
    if cursor and (cursor.get("host") != HOST or cursor.get("protocol") != PROTOCOL
                   or type(cursor.get("sequence")) is not int or not 1 <= cursor['sequence'] < 2**63):
        raise ContractError("cursor_domain_mismatch")
    observations, markers, quarantine = [], [], []
    total, last, seen = 0, (cursor or {}).get("sequence"), set()
    for index, frame in enumerate(frames):
        if index >= max_items:
            break
        total += len(canonical(frame).encode("utf-8"))
        if total > max_bytes:
            raise ContractError("batch_byte_limit")
        try:
            row, marker, seq = normalize_frame(frame, policy=policy, received_at=received_at,
                                               available_at=available_at, coverage_epoch=coverage_epoch)
        except ContractError as exc:
            quarantine.append({"index": index, "reason_code": exc.code})
            # Without a valid marker/identity it is unsafe to advance past this frame.
            break
        if seq is not None:
            last = max(last or 0, seq)
        if row and row["observation_id"] not in seen:
            observations.append(row); seen.add(row["observation_id"])
        if marker:
            markers.append(marker)
    gap = bool(quarantine) or any(m["kind"] in ("gap", "sync") for m in markers)
    return Batch(tuple(observations), {"host": HOST, "protocol": PROTOCOL, "sequence": last} if last else cursor,
                 "gap" if gap else "partial", "health_degraded" if gap else "available",
                 "stream_requires_watermark" if not gap else "stream_reconciliation_required", tuple(markers), total,
                 cost_microusd=0, quarantined=tuple(quarantine))


def collect(*, policy: SourcePolicy, enabled: bool, entitlement_current: bool, received_at: str,
            available_at: str, coverage_epoch: str, cursor: dict | None = None, connect=None,
            max_items: int = 250, seconds: int = 10) -> Batch:
    """A bounded sample, not a persistent cron stream or a complete-platform window."""
    admit(CAPABILITY, policy, at=received_at, requested_scope=policy.scope_key, enabled=enabled,
          item_limit=max_items, byte_limit=CAPABILITY.max_response_bytes, reservation_microusd=0,
          entitlement_current=entitlement_current, billable=False)
    if not 1 <= seconds <= 30:
        raise ContractError("stream_time_limit")
    if cursor and (cursor.get("host") != HOST or cursor.get("protocol") != PROTOCOL or type(cursor.get("sequence")) is not int):
        raise ContractError("cursor_domain_mismatch")
    if connect is None:
        safe_url("https://" + HOST + PATH, allowed_hosts=frozenset((HOST,)))
        from websockets.sync.client import connect
    query = {"collections": "app.bsky.feed.post"}
    if cursor:
        query["cursor"] = cursor["sequence"]
    frames, total = [], 0
    end = time.monotonic() + seconds
    with connect(CAPABILITY.endpoint + "?" + urlencode(query), subprotocols=["xrpc.v1.json"],
                 open_timeout=min(10, seconds), max_size=65_536, proxy=None) as stream:
        while len(frames) < max_items and time.monotonic() < end:
            try:
                raw = stream.recv(timeout=max(0.01, end - time.monotonic()))
            except TimeoutError:
                break
            total += len(raw.encode("utf-8") if isinstance(raw, str) else raw)
            if total > CAPABILITY.max_response_bytes:
                raise ContractError("batch_byte_limit")
            frames.append(json.loads(raw))
    return fold_frames(frames, policy=policy, received_at=received_at, available_at=available_at,
                       coverage_epoch=coverage_epoch, cursor=cursor, max_items=max_items)
