"""Plan target-native HyperFrames jobs without scaffolding or rendering."""

from __future__ import annotations

import copy
from collections.abc import Mapping

from .canonical import canonical_hash
from .contracts import validate_contract


TARGET_VARIANTS: dict[str, dict[str, object]] = {
    "youtube_or_embed": {"aspect_ratio": "16:9", "width": 1920, "height": 1080},
    "linkedin_x_instagram_feed": {"aspect_ratio": "1:1", "width": 1080, "height": 1080},
    "shorts_reels_tiktok": {"aspect_ratio": "9:16", "width": 1080, "height": 1920},
}


def select_workflow(
    duration_seconds: int, narration_mode: str, motion_first: bool
) -> str:
    if duration_seconds < 10 and narration_mode == "none" and motion_first:
        return "motion-graphics"
    if 30 <= duration_seconds <= 180:
        return "faceless-explainer"
    raise ValueError("duration_not_supported_by_v14_motion_policy")


def target_variant(target_family: str) -> dict[str, object]:
    if target_family not in TARGET_VARIANTS:
        raise ValueError(f"unsupported_target_family:{target_family}")
    return {"target_family": target_family, **copy.deepcopy(TARGET_VARIANTS[target_family])}


def validate_motion_state(job: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    state = job.get("state")
    outputs = job.get("output_asset_ids")
    if state == "rendered" and not outputs:
        errors.append("rendered_without_output_asset")
    if state == "planned" and outputs:
        errors.append("planned_has_output_asset")
    validation = job.get("validation")
    if state == "rendered" and isinstance(validation, Mapping):
        if validation.get("visual_review") != "passed":
            errors.append("rendered_without_visual_review")
        if validation.get("audio_review") not in {"passed", "not_applicable"}:
            errors.append("rendered_without_audio_review")
    return errors


def plan_motion_job(request: Mapping[str, object]) -> dict[str, object]:
    request_copy = copy.deepcopy(dict(request))
    external_actions = request_copy.get("external_actions", [])
    if external_actions:
        raise ValueError("external_action_not_allowed_in_phase0")
    source_refs = request_copy.get("source_artifact_refs")
    source_hashes = request_copy.get("source_artifact_hashes")
    if not isinstance(source_refs, list) or not source_refs:
        raise ValueError("source_artifact_refs_required")
    if not isinstance(source_hashes, list) or len(source_hashes) != len(source_refs):
        raise ValueError("source_artifact_hashes_must_match_refs")
    rights = request_copy.get("media_rights_refs")
    if not isinstance(rights, list) or not rights:
        raise ValueError("media_rights_refs_required")
    target_families = request_copy.get("target_families")
    if not isinstance(target_families, list) or not target_families:
        raise ValueError("target_families_required")
    if len(set(target_families)) != len(target_families):
        raise ValueError("duplicate_target_family")
    narration_mode = request_copy.get("narration_mode")
    if narration_mode not in {"none", "approved_script", "generated_candidate"}:
        raise ValueError("unsupported_narration_mode")
    duration = request_copy.get("duration_seconds")
    if not isinstance(duration, int):
        raise ValueError("duration_seconds_must_be_integer")
    workflow = select_workflow(
        duration, str(narration_mode), bool(request_copy.get("motion_first"))
    )
    variants = [target_variant(str(family)) for family in target_families]
    artifact = {
        "motion_job_id": request_copy["motion_job_id"],
        "campaign_id": request_copy["campaign_id"],
        "source_artifact_refs": source_refs,
        "source_artifact_hashes": source_hashes,
        "renderer": "hyperframes",
        "workflow": workflow,
        "hyperframes_version": request_copy["hyperframes_version"],
        "angle": request_copy["angle"],
        "narration_mode": narration_mode,
        "duration_seconds": duration,
        "variants": variants,
        "brief_hash": canonical_hash(request_copy["brief"]),
        "storyboard_hash": canonical_hash(request_copy["storyboard"]),
        "composition_hash": canonical_hash(request_copy["composition"]),
        "template_selection_id": request_copy.get("template_selection_id"),
        "caption_and_translation_refs": request_copy.get("caption_and_translation_refs", []),
        "media_rights_refs": rights,
        "state": "planned",
        "validation": {
            "lint": "pending",
            "check": "pending",
            "visual_review": "pending",
            "audio_review": "pending",
        },
        "output_asset_ids": [],
        "not_done": ["not rendered", "not uploaded", "not scheduled", "not published"],
    }
    validated = validate_contract("motion_video_job", artifact)
    state_errors = validate_motion_state(validated)
    if state_errors:
        raise ValueError("motion_state_invalid:" + ",".join(state_errors))
    return validated
