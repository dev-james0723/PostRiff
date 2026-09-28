"""Eligibility for supplied permitted media references; never fetches media."""
from .context import bounded, envelope, finite, source_index, supported, timestamp

MODALITIES = ("transcript", "visual", "audio", "ocr")


def check_media_eligibility(payload):
    clips = bounded(payload.get("clips", []), 100)
    sources = source_index(payload, "creative")
    cutoff = timestamp(payload["decision_cutoff"])
    limits = payload.get("limits", {})
    required = ("max_bytes", "max_tokens", "max_processing_seconds", "max_cost")
    if any(k not in limits for k in required):
        return envelope(payload, state="unavailable", reasons=["explicit_resource_caps_required"], clips=[])
    for key in required:
        finite(limits[key], minimum=0)
    totals = {"max_bytes": 0, "max_tokens": 0, "max_processing_seconds": 0, "max_cost": 0}
    results = []
    for clip in clips:
        reasons = []
        if len(clips) > 2:
            reasons.append("clip_count_limit")
        if not supported(clip, sources, cutoff):
            reasons.append("rights_or_source_unavailable")
        duration = finite(clip.get("duration_seconds", 0), minimum=0)
        if duration <= 0 or duration > 90:
            reasons.append("duration_limit")
        if len(bounded(clip.get("keyframes", []), 1000)) > 12:
            reasons.append("keyframe_limit")
        for field, key in (("size_bytes", "max_bytes"), ("processing_tokens", "max_tokens"),
                           ("processing_seconds", "max_processing_seconds"), ("estimated_cost", "max_cost")):
            if field not in clip:
                reasons.append("missing_" + field)
            else:
                totals[key] += finite(clip[field], minimum=0)
        permitted = {}
        for modality in MODALITIES:
            available = clip.get("available_modalities", [])
            allowed = bool(clip.get("evidence_refs")) and all(
                r in sources and sources[r]["rights"].get(modality) is True for r in clip.get("evidence_refs", []))
            permitted[modality] = "eligible" if allowed and modality in available else "unknown"
        results.append({"clip_id": clip["clip_id"], "state": "eligible" if not reasons else "unavailable",
                        "modalities": permitted, "reasons": reasons})
    global_reasons = [key + "_exceeded" for key, value in totals.items() if value > limits[key]]
    if payload.get("enabled", True) is not True:
        global_reasons.append("module_disabled")
    if global_reasons:
        for row in results:
            row["state"] = "unavailable"
            row["reasons"].extend(global_reasons)
    return envelope(payload, state="eligible" if results and all(r["state"] == "eligible" for r in results) else "unavailable",
                    clips=results, resource_totals=totals, reasons=global_reasons,
                    retrieval_executed=False, audio_reuse_rights="unknown")
