"""Canonical JSON contracts. Unknown source permissions never grant a capability.

All times are UTC instants; source time is distinct from the time Rafii learned it.
Provider payloads are data, never authority. These validators have no external effects.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict
from uuid import UUID

SCHEMA_VERSION = "rafii.trend-observation.v1"
KINDS = ("raw_post", "owned_post", "aggregate_metric", "search_lead", "trend_seed")
OPERATIONS = ("create", "update", "delete")
PERMISSIONS = (
    "retrieve", "store_raw", "store_metrics", "store_embeddings", "llm_process",
    "display_excerpt", "display_link", "share_across_workspaces", "derive_metrics",
    "cross_source_combine", "retain_derivatives", "train_or_finetune",
)
READINESS = ("not_configured", "access_pending", "ready", "rate_limited", "budget_paused",
             "health_degraded", "rights_suspended", "revoked", "unsupported")
VERIFICATION_STATES = ("pending", "verified", "mismatch", "inputs_expired", "inputs_deleted",
                       "policy_revoked", "method_unavailable")
LANGUAGES = ("en", "zh-Hant", "zh-Hans", "yue", "yue-en", "und")
STAGES = ("emerging", "rising", "breaking", "hot", "peaking", "saturated", "declining", "evergreen")
MAX_PAYLOAD_BYTES = 65_536
MAX_TEXT = 16_000
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")


class ContractError(ValueError):
    """Safe reason code only; never echo provider/private content in errors."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class PermissionGrant(TypedDict):
    state: Literal["allow", "deny", "unknown"]
    policy_ref: str
    audience_scope: str
    expires_at: str


def canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractError("invalid_json") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def instant(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ContractError("invalid_timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("invalid_timestamp") from exc
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ContractError("timestamp_must_be_utc")
    return result.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ContractError("timestamp_must_be_utc")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def uuid(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContractError("invalid_id") from exc


def scope(value: Any) -> str:
    if not isinstance(value, str):
        raise ContractError("scope_required")
    if value.startswith("workspace:"):
        if value != "workspace:" + uuid(value[10:]):
            raise ContractError("invalid_scope")
    elif value.startswith("shared:"):
        if not re.fullmatch(r"shared:[a-z0-9][a-z0-9_.-]{0,95}", value):
            raise ContractError("invalid_scope")
    else:
        raise ContractError("invalid_scope")
    return value


def bounded_text(value: Any, maximum: int = 256, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value):
        raise ContractError("invalid_text_field")
    return value


def finite(value: Any, *, nonnegative: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError("invalid_number")
    if nonnegative and value < 0:
        raise ContractError("negative_number")
    return value


def validate_rights(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) - set(PERMISSIONS):
        raise ContractError("invalid_rights")
    result = {}
    for permission, grant in value.items():
        if not isinstance(grant, dict) or set(grant) != {"state", "policy_ref", "audience_scope", "expires_at"}:
            raise ContractError("invalid_permission_grant")
        if grant["state"] not in ("allow", "deny", "unknown"):
            raise ContractError("invalid_permission_state")
        bounded_text(grant["policy_ref"])
        scope(grant["audience_scope"])
        instant(grant["expires_at"])
        result[permission] = copy.deepcopy(grant)
    return result


def permits(rights: dict, permission: str, scope_key: str, at: str) -> bool:
    """Missing/unknown/expired grants are denied independently for each operation."""
    if permission not in PERMISSIONS:
        return False
    try:
        grant = rights.get(permission, {})
        return (grant.get("state") == "allow" and grant.get("audience_scope") == scope_key
                and bool(grant.get("policy_ref")) and instant(at) < instant(grant.get("expires_at")))
    except (ContractError, AttributeError, TypeError):
        return False


def validate_coverage(value: Any) -> dict:
    axes = {"availability": ("available", "stale", "unavailable", "not_applicable"),
            "representation": ("raw_posts", "sampled_posts", "aggregate_only", "search_leads", "owned_posts", "trend_seeds"),
            "completeness": ("complete_within_scope", "partial", "truncated", "gap", "unknown"),
            "breadth": ("high", "moderate", "low", "unknown")}
    if not isinstance(value, dict):
        raise ContractError("invalid_coverage")
    for axis, choices in axes.items():
        if value.get(axis) not in choices:
            raise ContractError("invalid_coverage_axis")
    if value["breadth"] != "unknown" and not value.get("denominator_ref"):
        raise ContractError("breadth_denominator_required")
    bounded_text(value.get("scope_ref"))
    bounded_text(value.get("coverage_epoch"))
    return copy.deepcopy(value)


def validate_observation(value: Any) -> dict:
    required = {"observation_id", "scope_key", "provider_id", "provider_contract_version", "source_policy_version",
                "source_identity", "revision_identity", "revision_sequence", "kind", "operation", "event_at",
                "received_at", "available_at", "time_basis", "coverage_epoch", "provenance", "retention_until",
                "rights", "deletion_key", "payload", "payload_digest", "schema_version"}
    if not isinstance(value, dict) or set(value) != required:
        raise ContractError("invalid_observation_fields")
    if value["schema_version"] != SCHEMA_VERSION or value["kind"] not in KINDS or value["operation"] not in OPERATIONS:
        raise ContractError("invalid_observation_type")
    uuid(value["observation_id"]); scope(value["scope_key"])
    for key in ("provider_id", "provider_contract_version", "source_policy_version", "source_identity",
                "revision_identity", "coverage_epoch", "deletion_key"):
        bounded_text(value[key], 1024 if key == "source_identity" else 256)
    seq = value["revision_sequence"]
    if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq < 2**63:
        raise ContractError("invalid_revision_sequence")
    received, available, expiry = (instant(value[key]) for key in ("received_at", "available_at", "retention_until"))
    if received > available or expiry <= available:
        raise ContractError("invalid_knowledge_or_retention_time")
    if value["event_at"] is not None:
        instant(value["event_at"])
    if value["time_basis"] not in ("provider_event", "provider_observation", "retrieval"):
        raise ContractError("invalid_time_basis")
    if value["event_at"] is None and value["time_basis"] == "provider_event":
        raise ContractError("unknown_event_time")
    validate_rights(value["rights"])
    if any(g["audience_scope"] != value["scope_key"] for g in value["rights"].values()):
        raise ContractError("rights_scope_mismatch")
    if not isinstance(value["provenance"], dict) or not value["provenance"].get("access_method"):
        raise ContractError("provenance_required")
    payload = value["payload"]
    if not isinstance(payload, dict) or len(canonical(value).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ContractError("payload_limit")
    if value["payload_digest"] != digest(payload):
        raise ContractError("payload_digest_mismatch")
    if value["operation"] == "delete":
        if set(payload) - {"platform", "reason_code"}:
            raise ContractError("delete_payload_contains_content")
        return copy.deepcopy(value)
    kind = value["kind"]
    if kind in ("raw_post", "owned_post"):
        bounded_text(payload.get("platform"), 80)
        bounded_text(payload.get("native_id"), 1024)
        if payload.get("author_status") not in ("known", "unknown", "withheld"):
            raise ContractError("author_status_required")
        if payload["author_status"] == "known":
            bounded_text(payload.get("author_key"), 1024)
        if payload["author_status"] != "known" and payload.get("author_key") is not None:
            raise ContractError("unknown_author_has_key")
        if payload.get("language", "und") not in LANGUAGES:
            raise ContractError("unsupported_language_tag")
        if "text" in payload:
            bounded_text(payload["text"], MAX_TEXT, empty=True)
            if not permits(value["rights"], "store_raw", value["scope_key"], value["available_at"]):
                raise ContractError("raw_storage_not_permitted")
        if kind == "owned_post":
            if not value["scope_key"].startswith("workspace:") or not payload.get("connection_id"):
                raise ContractError("owned_post_requires_workspace")
    elif kind == "aggregate_metric":
        if set(payload) & {"text", "author_key", "native_id", "representative_posts"}:
            raise ContractError("aggregate_cannot_invent_posts")
        for key in ("dataset_id", "metric_definition", "unit", "population", "aggregation_semantics"):
            bounded_text(payload.get(key))
        if instant(payload.get("window_start")) >= instant(payload.get("window_end")):
            raise ContractError("invalid_window")
        if payload.get("value") is not None:
            finite(payload["value"])
        elif not payload.get("null_reason"):
            raise ContractError("null_reason_required")
        if not permits(value["rights"], "store_metrics", value["scope_key"], value["available_at"]):
            raise ContractError("metric_storage_not_permitted")
    elif kind == "search_lead":
        bounded_text(payload.get("canonical_url"), 2048)
        if set(payload) & {"mention_count", "engagement", "author_key"}:
            raise ContractError("search_lead_is_not_social_measurement")
        if payload.get("text") and not permits(value["rights"], "store_raw", value["scope_key"], value["available_at"]):
            raise ContractError("raw_storage_not_permitted")
    elif kind == "trend_seed":
        bounded_text(payload.get("topic_id"))
        bounded_text(payload.get("native_score_semantics"))
        if set(payload) & {"mention_count", "author_key", "text"}:
            raise ContractError("trend_seed_is_not_post")
    return copy.deepcopy(value)
