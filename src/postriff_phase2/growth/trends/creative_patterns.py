"""Validated existing extraction results, with per-modality absence and timecodes."""
from copy import deepcopy
from .context import bounded, envelope, finite, source_index, supported, timestamp
from .media_extraction import MODALITIES, check_media_eligibility


def build_creative_pattern(payload):
    eligibility = check_media_eligibility(payload)
    sources = source_index(payload, "creative")
    cutoff = timestamp(payload["decision_cutoff"])
    patterns = []
    for clip, status in zip(payload.get("clips", []), eligibility["clips"]):
        frames = {}
        for frame in bounded(clip.get("keyframes", []), 1000):
            if not supported(frame, sources, cutoff) or not set(frame["evidence_refs"]) <= set(clip["evidence_refs"]):
                continue
            at = finite(frame["at_seconds"], minimum=0)
            if at <= clip["duration_seconds"] and frame.get("frame_id"):
                frames[frame["frame_id"]] = at
        modalities = {}
        for name in MODALITIES:
            items, rejected = [], 0
            for item in bounded(clip.get("extractions", {}).get(name, []), 1000):
                if status["state"] != "eligible" or status["modalities"][name] != "eligible":
                    rejected += 1
                    continue
                if not supported(item, sources, cutoff) or not set(item["evidence_refs"]) <= set(clip["evidence_refs"]):
                    rejected += 1
                    continue
                start, end = finite(item["start_seconds"], minimum=0), finite(item["end_seconds"], minimum=0)
                if start > end or end > clip["duration_seconds"]:
                    rejected += 1
                    continue
                if item.get("derivation_kind") not in {"observation", "deterministic_extraction", "model_interpretation"}:
                    rejected += 1
                    continue
                if item["derivation_kind"] == "model_interpretation" and not all(sources[r]["rights"].get("llm") is True for r in item["evidence_refs"]):
                    rejected += 1
                    continue
                if name in {"visual", "ocr"} and (item.get("frame_ref") not in frames or not start <= frames[item["frame_ref"]] <= end):
                    rejected += 1
                    continue
                items.append({k: deepcopy(item.get(k)) for k in ("start_seconds", "end_seconds", "text", "descriptor",
                              "frame_ref", "evidence_refs", "derivation_kind", "quality", "method_version")})
            if name in {"visual", "ocr"} and len({i["frame_ref"] for i in items}) > 12:
                rejected += len(items)
                items = []
            modalities[name] = {"state": "available" if items else "unknown", "items": items,
                                "rejected_count": rejected, "null_reason": None if items else "no_permitted_inspected_evidence"}
        patterns.append({"clip_id": clip["clip_id"], "duration_seconds": clip["duration_seconds"],
                         "modalities": modalities, "state": status["state"], "reasons": status["reasons"]})
    return envelope(payload, patterns=patterns, qualification="unqualified", full_video_understanding=False,
                    media_downloaded=False, reuse_rights="not_established_by_analysis")
