"""Strict validators for the five revision 14 shared records."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass
class ContractViolation(ValueError):
    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} at {self.path}: {self.message}"


REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "source_acquisition_provider": (
        "provider_id",
        "provider_kind",
        "source_repository",
        "reviewed_commit",
        "provider_state",
        "allowed_operations",
        "denied_operations",
        "supported_source_types",
        "auth_mode",
        "license_state",
        "terms_and_robots_review",
        "network_scope",
        "rate_limit_policy_ref",
        "adapter_version",
        "last_reviewed_at",
        "expires_at",
    ),
    "video_source_artifact": (
        "video_source_id",
        "source_url",
        "platform",
        "provider",
        "provider_commit_or_version",
        "title",
        "publisher_or_channel",
        "published_at",
        "retrieved_at",
        "duration_seconds",
        "metadata_hash",
        "rights_and_terms_note",
        "access_state",
        "not_downloaded",
    ),
    "video_transcript_artifact": (
        "transcript_id",
        "video_source_id",
        "source_language",
        "caption_source",
        "caption_track_id",
        "segments",
        "transcript_hash",
        "quality_flags",
        "created_at",
        "not_done",
    ),
    "transcript_translation_artifact": (
        "translation_id",
        "source_transcript_id",
        "source_transcript_hash",
        "source_language",
        "target_language",
        "translation_provider",
        "translation_provider_version",
        "segments",
        "proper_nouns_and_terms",
        "omissions_or_uncertainties",
        "translation_hash",
        "review_state",
    ),
    "motion_video_job": (
        "motion_job_id",
        "campaign_id",
        "source_artifact_refs",
        "source_artifact_hashes",
        "renderer",
        "workflow",
        "hyperframes_version",
        "angle",
        "narration_mode",
        "duration_seconds",
        "variants",
        "brief_hash",
        "storyboard_hash",
        "composition_hash",
        "template_selection_id",
        "caption_and_translation_refs",
        "media_rights_refs",
        "state",
        "validation",
        "output_asset_ids",
        "not_done",
    ),
}

ENUMS: dict[tuple[str, str], frozenset[str]] = {
    ("source_acquisition_provider", "provider_kind"): frozenset(
        {"url_extractor", "platform_research", "video_transcript_acquisition", "motion_renderer"}
    ),
    ("source_acquisition_provider", "provider_state"): frozenset(
        {
            "reference_only",
            "candidate_read_only",
            "approved_read_only",
            "available_local_skill_unbound",
            "enabled_scoped",
            "disabled",
        }
    ),
    ("source_acquisition_provider", "auth_mode"): frozenset(
        {"none", "secret_reference_only", "private_handoff"}
    ),
    ("source_acquisition_provider", "license_state"): frozenset(
        {"reviewed", "unresolved", "incompatible"}
    ),
    ("video_source_artifact", "access_state"): frozenset(
        {"public", "login_required", "unavailable", "blocked"}
    ),
    ("video_transcript_artifact", "caption_source"): frozenset(
        {"manual_caption", "auto_caption", "asr"}
    ),
    ("transcript_translation_artifact", "review_state"): frozenset(
        {"machine_candidate", "reviewed", "blocked"}
    ),
    ("motion_video_job", "workflow"): frozenset({"faceless-explainer", "motion-graphics"}),
    ("motion_video_job", "narration_mode"): frozenset(
        {"none", "approved_script", "generated_candidate"}
    ),
    ("motion_video_job", "state"): frozenset(
        {
            "planned",
            "brief_ready",
            "storyboard_review",
            "composition_ready",
            "validating",
            "rendered",
            "blocked",
            "failed",
        }
    ),
}

HASH_FIELDS = {
    "metadata_hash",
    "transcript_hash",
    "source_transcript_hash",
    "translation_hash",
    "brief_hash",
    "storyboard_hash",
    "composition_hash",
}


def _require_fields(kind: str, value: Mapping[str, object]) -> None:
    for field in REQUIRED_FIELDS[kind]:
        if field not in value:
            raise ContractViolation("missing_required_field", field, f"{field} is required")


def _require_enum(kind: str, field: str, value: object) -> None:
    allowed = ENUMS.get((kind, field))
    if allowed is not None and value not in allowed:
        raise ContractViolation("invalid_enum", field, f"expected one of {sorted(allowed)}")


def _require_hash(field: str, value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ContractViolation("invalid_hash", field, "expected sha256:<64 lowercase hex>")


def _require_segments(kind: str, segments: object) -> None:
    if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)):
        raise ContractViolation("invalid_segments", "segments", "expected a list")
    previous_start = -1
    for index, segment in enumerate(segments):
        path = f"segments[{index}]"
        if not isinstance(segment, Mapping):
            raise ContractViolation("invalid_segment", path, "expected an object")
        for field in ("start_ms", "end_ms"):
            if not isinstance(segment.get(field), int):
                raise ContractViolation("invalid_segment_time", f"{path}.{field}", "expected integer")
        start_ms = segment["start_ms"]
        end_ms = segment["end_ms"]
        if start_ms < 0 or end_ms < start_ms or start_ms < previous_start:
            raise ContractViolation("invalid_segment_time", path, "timestamps must be ordered and non-negative")
        if kind == "video_transcript_artifact" and not isinstance(segment.get("text"), str):
            raise ContractViolation("invalid_segment_text", f"{path}.text", "expected text")
        if kind == "transcript_translation_artifact":
            if not isinstance(segment.get("source_segment_index"), int):
                raise ContractViolation("invalid_source_segment_index", path, "expected integer index")
            if not isinstance(segment.get("translated_text"), str):
                raise ContractViolation("invalid_segment_text", f"{path}.translated_text", "expected text")
        previous_start = start_ms


def validate_contract(kind: str, value: Mapping[str, object]) -> dict[str, object]:
    """Validate and deep-copy a revision 14 record."""

    if kind not in REQUIRED_FIELDS:
        raise ContractViolation("unknown_contract_kind", kind, "unsupported contract")
    if not isinstance(value, Mapping):
        raise ContractViolation("invalid_record", kind, "expected an object")
    _require_fields(kind, value)
    for field in REQUIRED_FIELDS[kind]:
        _require_enum(kind, field, value[field])
        if field in HASH_FIELDS:
            _require_hash(field, value[field])
    if kind == "motion_video_job":
        for index, item in enumerate(value["source_artifact_hashes"]):  # type: ignore[union-attr]
            _require_hash(f"source_artifact_hashes[{index}]", item)
    if kind in {"video_transcript_artifact", "transcript_translation_artifact"}:
        _require_segments(kind, value["segments"])
    return copy.deepcopy(dict(value))
