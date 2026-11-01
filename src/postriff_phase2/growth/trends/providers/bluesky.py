"""Pinned Jetstream v2 JSON folding boundary; archive replay requires a separate paid admission.

Protocol reference: bluesky-social/jetstream@3fa54fdbb0f47ad3aa43de78a6fbbd8dc362f81d.
Sequence cursors are inclusive and instance-local. Marker events must never be filtered out.

fold_frames distinguishes two failure classes:

* Envelope failures (no valid seq/DID/kind, an unusable #account object, a
  malformed delete identity, an unknown operation, or a policy-wide/systemic
  contract failure) stop BEFORE advancing: skipping them could skip a deletion
  or account decision, or silently discard every record.
* Record failures on a commit create/update whose seq and DID are valid are
  quarantined with a precise content-free code and the cursor advances past
  them. A create/update never carries a deletion, and stopping would make the
  inclusive cursor re-deliver the same poison forever.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import re
import time
from urllib.parse import urlencode

from ..contracts import ContractError, canonical, instant, iso, permits
from ..policy import ProviderCapability, SourcePolicy, admit
from .base import Batch, ProviderTransportError, observation, safe_url

PROTOCOL = "jetstream-v2-json@3fa54fdbb0f47ad3aa43de78a6fbbd8dc362f81d"
HOST = "jetstream.us-west.bsky.network"
PATH = "/xrpc/network.bsky.jetstream.subscribeEvents"
CAPABILITY = ProviderCapability("bluesky", "live_sample", PROTOCOL, ("raw_post",), "wss://" + HOST + PATH,
                                "xrpc.v1.json", "public", (), 250, 1_000_000, 30, 3,
                                "unmetered_live_bytes_bounded", "commit-delete/account/sync")
# Client frame limit and the lexicon's server-side maxMessageSizeBytes skip filter.
MAX_FRAME_BYTES = 65_536
LANGUAGES = ("en", "zh-Hant", "zh-Hans", "yue")
# com.atproto.sync.subscribeRepos#account status knownValues; anything else is not echoed.
ACCOUNT_STATUSES = frozenset(("takendown", "suspended", "deleted", "deactivated", "desynchronized", "throttled"))
# #info names (lexicon knownValues OutdatedCursor; subscribeRepos FutureCursor) -> explicit gap reasons.
INFO_GAPS = {"OutdatedCursor": "cursor_outdated", "FutureCursor": "cursor_future"}
# Allowlisted pre-upgrade XRPC error names; the body is otherwise never read or logged.
HANDSHAKE_ERRORS = frozenset(("CursorTooOld", "UnknownZstdDictionary", "InvalidRequest", "ConsumerTooSlow"))
_RFC3339 = re.compile(r"(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(\.\d{1,9})?([+-]\d{2}:\d{2})")

ENVELOPE_CODES = frozenset(("jetstream_invalid_frame", "jetstream_sequence_required", "jetstream_identity_required",
                            "jetstream_unknown_event", "jetstream_invalid_record", "jetstream_invalid_marker"))
# Raised by validate_observation from policy/configuration, never by one record:
# treat as stop-before-advance so a broken policy cannot silently skip everything.
SYSTEMIC_CODES = frozenset(("invalid_knowledge_or_retention_time", "invalid_rights", "invalid_permission_grant",
                            "invalid_permission_state", "rights_scope_mismatch", "provenance_required",
                            "invalid_scope", "scope_required", "invalid_id", "invalid_observation_fields",
                            "invalid_observation_type", "raw_storage_not_permitted"))
RECORD_CODES = frozenset(("jetstream_invalid_record", "timestamp_must_be_utc", "invalid_timestamp",
                          "invalid_text_field", "payload_limit", "unsupported_language_tag", "invalid_json",
                          "invalid_revision_sequence", "unknown_event_time", "invalid_time_basis",
                          "author_status_required", "payload_digest_mismatch", "invalid_number"))
# Every code fold_frames can persist in a content-free quarantine receipt.
QUARANTINE_CODES = ENVELOPE_CODES | SYSTEMIC_CODES | RECORD_CODES


class RecordQuarantine(ContractError):
    """Record-level failure on a valid commit create/update; the fold may advance past ``sequence``."""
    def __init__(self, code: str, sequence: int):
        super().__init__(code)
        self.sequence = sequence


def event_time(value) -> str:
    """Return a UTC event time or raise a record-level timestamp code.

    Already-UTC values keep their exact original string (unchanged behaviour).
    RFC3339/atproto datetimes with a numeric offset are converted to UTC instead
    of rejected; naive or non-RFC3339 values remain invalid.
    """
    try:
        instant(value)
        return value
    except ContractError as exc:
        if exc.code != "timestamp_must_be_utc" or not isinstance(value, str):
            raise
    match = _RFC3339.fullmatch(value)
    if not match:
        raise ContractError("timestamp_must_be_utc")
    date, clock, fraction, offset = match.groups()
    return iso(datetime.fromisoformat(date + "T" + clock + (fraction or "")[:7] + offset).astimezone(timezone.utc))


def _marker(kind: str, data: dict, did: str, seq: int, available_at: str) -> dict:
    """v2 lexicon: #account/#identity/#sync wrap the upstream event under data[kind]."""
    detail = data.get(kind)
    if kind == "account" and not isinstance(detail, dict):
        # Without the nested account object the deactivation decision is unknown:
        # never advance past a possibly revoking event.
        raise ContractError("jetstream_invalid_marker")
    detail = detail if isinstance(detail, dict) else {}
    marker = {"kind": kind, "did": did, "sequence": seq, "available_at": available_at,
              "requires_reconciliation": kind == "sync"}
    if kind == "account":
        active, status = detail.get("active"), detail.get("status")
        marker["active"] = active if type(active) is bool else None
        marker["status"] = status if isinstance(status, str) and status in ACCOUNT_STATUSES else None
    elif kind == "identity":
        handle = detail.get("handle")
        marker["handle"] = handle if isinstance(handle, str) and 0 < len(handle) <= 253 else None
    return marker


def _post(data: dict, did: str, rkey: str, seq: int, op: str, *, policy: SourcePolicy, received_at: str,
          available_at: str, coverage_epoch: str) -> dict:
    identity = f"at://{did}/app.bsky.feed.post/{rkey}"
    payload = {"platform": "bluesky"}
    event_at = None
    if op != "delete":
        record = data.get("record")
        if not isinstance(record, dict) or record.get("$type") != "app.bsky.feed.post":
            raise ContractError("jetstream_invalid_record")
        if record.get("createdAt") is not None:
            event_at = event_time(record["createdAt"])
        langs = record.get("langs")
        language = (next((x for x in langs if isinstance(x, str) and x in LANGUAGES), "und")
                    if isinstance(langs, list) else "und")
        payload.update(native_id=identity, author_key=f"bluesky:{did}", author_status="known", language=language,
                       canonical_url=f"https://bsky.app/profile/{did}/post/{rkey}", is_repost=False)
        if permits(policy.rights, "store_raw", policy.scope_key, available_at):
            payload["text"] = record.get("text", "")
        reply = record.get("reply")
        if isinstance(reply, dict):
            payload["relations"] = [{"type": "reply", "target": part["uri"]} for part in
                                    [reply.get("parent", {})] if isinstance(part, dict) and isinstance(part.get("uri"), str)]
    return observation(policy=policy, source_identity=identity, revision_identity=f"{data.get('rev', seq)}:{op}:{seq}",
                       sequence=seq, kind="raw_post", operation=op, payload=payload, event_at=event_at,
                       received_at=received_at, available_at=available_at, coverage_epoch=coverage_epoch,
                       contract_version=PROTOCOL, access_method="official_public_stream", deletion_key=identity)


def normalize_frame(frame: dict, *, policy: SourcePolicy, received_at: str, available_at: str,
                    coverage_epoch: str) -> tuple[dict | None, dict | None, int | None]:
    if not isinstance(frame, dict) or frame.get("$type") != "message" or not isinstance(frame.get("payload"), dict):
        raise ContractError("jetstream_invalid_frame")
    data = frame["payload"]
    kind = str(data.get("$type", "")).removeprefix("network.bsky.jetstream.subscribeEvents#")
    if kind == "info":
        name = data.get("name")
        return None, {"kind": "gap", "reason_code": INFO_GAPS.get(name, "cursor_clamped")
                      if isinstance(name, str) else "cursor_clamped"}, None
    seq = data.get("seq")
    if type(seq) is not int or not 1 <= seq < 2**63:
        raise ContractError("jetstream_sequence_required")
    did = data.get("did")
    if not isinstance(did, str) or not did.startswith(("did:plc:", "did:web:")) or len(did) > 256:
        raise ContractError("jetstream_identity_required")
    if kind in ("account", "sync", "identity"):
        return None, _marker(kind, data, did, seq, available_at), seq
    if kind != "commit":
        raise ContractError("jetstream_unknown_event")
    if data.get("collection") != "app.bsky.feed.post":
        return None, None, seq
    op, rkey = data.get("operation"), data.get("rkey")
    if op not in ("create", "update", "delete"):
        # An unknown operation might be a deletion: never skip it.
        raise ContractError("jetstream_invalid_record")
    valid_rkey = isinstance(rkey, str) and 0 < len(rkey) <= 256 and "/" not in rkey
    args = dict(policy=policy, received_at=received_at, available_at=available_at, coverage_epoch=coverage_epoch)
    if op == "delete":
        # A malformed deletion identity keeps stop-before-advance semantics.
        if not valid_rkey:
            raise ContractError("jetstream_invalid_record")
        try:
            return _post(data, did, rkey, seq, op, **args), None, seq
        except ContractError:
            raise
        except (TypeError, ValueError, AttributeError, KeyError, RecursionError):
            raise ContractError("jetstream_invalid_record") from None
    try:
        if not valid_rkey:
            raise ContractError("jetstream_invalid_record")
        return _post(data, did, rkey, seq, op, **args), None, seq
    except ContractError as exc:
        if exc.code in SYSTEMIC_CODES:
            raise
        raise RecordQuarantine(exc.code if exc.code in RECORD_CODES else "jetstream_invalid_record", seq) from None
    except (TypeError, ValueError, AttributeError, KeyError, RecursionError):
        raise RecordQuarantine("jetstream_invalid_record", seq) from None


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
        except RecordQuarantine as exc:
            # Valid envelope, unusable create/update record: quarantine and advance.
            quarantine.append({"index": index, "reason_code": exc.code})
            last = max(last or 0, exc.sequence)
            continue
        except ContractError as exc:
            quarantine.append({"index": index, "reason_code": exc.code if exc.code in QUARANTINE_CODES
                               else "jetstream_invalid_frame"})
            # Without a valid marker/identity it is unsafe to advance past this frame.
            break
        except (TypeError, ValueError, AttributeError, KeyError, RecursionError):
            quarantine.append({"index": index, "reason_code": "jetstream_invalid_frame"})
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


class _CursorTooOld(Exception):
    """Internal signal: the supplied seq is below the live retention floor (HTTP 400 pre-upgrade)."""


class _Never(Exception):
    """Placeholder when websockets is unavailable; never raised."""


def _reject_constant(_value):
    raise ValueError("invalid_number")


def _rejection(exc) -> tuple[int | None, str | None]:
    """Status code and allowlisted XRPC error name only; the body is never returned or logged."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    status = status if type(status) is int else None
    error = None
    body = getattr(response, "body", b"")
    if status == 400 and isinstance(body, (bytes, bytearray)) and body:
        try:
            value = json.loads(bytes(body[:4096]))
            name = value.get("error") if isinstance(value, dict) else None
            error = name if isinstance(name, str) and name in HANDSHAKE_ERRORS else None
        except (ValueError, RecursionError):
            error = None
    return status, error


def _close_code(exc) -> int | None:
    for frame in (getattr(exc, "rcvd", None), getattr(exc, "sent", None)):
        code = getattr(frame, "code", None)
        if type(code) is int:
            return code
    return None


def _receive(connect, cursor: dict | None, end: float, max_items: int) -> list:
    """One bounded live-tail read. Raises _CursorTooOld or a typed, content-free transport error."""
    try:
        from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus, WebSocketException
    except ImportError:  # pragma: no cover - production pins websockets
        ConnectionClosed = InvalidHandshake = InvalidStatus = WebSocketException = _Never
    query = {"collections": "app.bsky.feed.post", "maxMessageSizeBytes": MAX_FRAME_BYTES}
    if cursor:
        query["cursor"] = cursor["sequence"]
    remaining = end - time.monotonic()
    if remaining <= 0:
        raise ProviderTransportError("stream_time_budget_exhausted")
    frames, total, failure = [], 0, None
    try:
        with connect(CAPABILITY.endpoint + "?" + urlencode(query), subprotocols=["xrpc.v1.json"],
                     open_timeout=max(0.01, min(10, remaining)), max_size=MAX_FRAME_BYTES, proxy=None) as stream:
            while len(frames) < max_items and time.monotonic() < end:
                try:
                    raw = stream.recv(timeout=max(0.01, end - time.monotonic()))
                except TimeoutError:
                    break
                except ConnectionClosed as exc:
                    if frames:
                        break  # Keep the bounded partial sample already received.
                    failure = ProviderTransportError("provider_stream_closed", close_code=_close_code(exc))
                    break
                total += len(raw.encode("utf-8") if isinstance(raw, str) else raw)
                if total > CAPABILITY.max_response_bytes:
                    raise ContractError("batch_byte_limit")
                try:
                    frames.append(json.loads(raw, parse_constant=_reject_constant))
                except (ValueError, RecursionError):
                    # Undecodable frame: no trustworthy seq. The fold quarantines this
                    # envelope and stops before it; nothing after it is read.
                    frames.append(None)
                    break
    except InvalidStatus as exc:
        status, error = _rejection(exc)
        failure = (_CursorTooOld() if cursor and status == 400 and error == "CursorTooOld"
                   else ProviderTransportError("provider_handshake_rejected", status=status))
    except ContractError:
        raise
    except (OSError, InvalidHandshake, WebSocketException):
        # TimeoutError is an OSError: handshake/open timeouts and connection errors.
        failure = ProviderTransportError("provider_transport_unavailable")
    if failure is not None:
        # Raised outside the handler so no provider exception/body is chained.
        raise failure
    return frames


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
    end = time.monotonic() + seconds
    args = dict(policy=policy, received_at=received_at, available_at=available_at, coverage_epoch=coverage_epoch,
                max_items=max_items)
    try:
        frames = _receive(connect, cursor or None, end, max_items)
    except _CursorTooOld:
        # The stored seq fell below the live window. Re-anchor ONCE at the live
        # tip inside the same admitted time budget, and record the uncovered
        # interval as an explicit gap; it is never presented as continuous.
        frames = _receive(connect, None, end, max_items)
        batch = fold_frames(frames, cursor=None, **args)
        gap = {"kind": "gap", "reason_code": "cursor_too_old", "previous_sequence": cursor["sequence"]}
        return replace(batch, markers=(gap, *batch.markers), completeness="gap", health="health_degraded",
                       reason_code="stream_cursor_reanchored")
    return fold_frames(frames, cursor=cursor, **args)
