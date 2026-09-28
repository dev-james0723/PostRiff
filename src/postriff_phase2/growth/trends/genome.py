"""Evidence map; unsupported dimensions are unknown rather than generated."""
from copy import deepcopy
from .context import bounded, envelope, source_index, stored_projection, supported, timestamp

DIMENSIONS = ("topic_narrative", "emotional_framing", "language_cultural_usage", "hook",
              "format_social_function", "visual_grammar", "audio", "community_audience_context", "platform_timing")


def build_genome(payload):
    sources = source_index(payload, "creative")
    cutoff = timestamp(payload["decision_cutoff"])
    dimensions = {}
    for name in DIMENSIONS:
        row = payload.get("dimensions", {}).get(name, {})
        modality = {"visual_grammar": "visual", "audio": "audio"}.get(name)
        refs = row.get("evidence_refs", [])
        reason = "unsupported"
        ok = payload.get("enabled", True) is True and supported(row, sources, cutoff)
        if modality and ok:
            ok = all(sources[r]["rights"].get(modality) is True for r in refs) and row.get("inspected") is True
            reason = "modality_unavailable"
        if row.get("derivation_kind") not in {"observation", "deterministic_extraction", "model_interpretation"}:
            ok = False
        if row.get("derivation_kind") == "model_interpretation" and ok:
            ok = all(sources[r]["rights"].get("llm") is True for r in refs)
        dimensions[name] = {"value": deepcopy(row.get("value")) if ok else None,
                            "state": "supported" if ok else "unknown",
                            "null_reason": None if ok else reason,
                            "evidence_refs": deepcopy(refs) if ok else [],
                            "observation_scope": payload["scope_key"],
                            "derivation_kind": row.get("derivation_kind") if ok else None,
                            "confidence_basis": row.get("confidence_basis", "unqualified") if ok else None,
                            "contradictions": deepcopy(row.get("contradictions", [])) if ok else [],
                            "method_version": row.get("method_version") if ok else None,
                            "review_status": row.get("review_status", "unreviewed") if ok else "unavailable"}
    return envelope(payload, dimensions=dimensions, qualified=False, origin="unknown")


def to_stored_projection(result):
    """Canonical genomeSchema payload from an already computed evidence projection."""
    dimensions = []
    for name, row in result["dimensions"].items():
        value = row["value"]
        # Structured evidence remains in the bound manifest, never coerced into a new claim.
        finding = value if isinstance(value, str) else None
        dimensions.append({"dimension": name, "finding": finding, "evidence_refs": row["evidence_refs"],
                           "uncertainty": str(row.get("null_reason") or row.get("confidence_basis") or "unqualified")})
    return stored_projection("genome", {"version": "1", "dimensions": dimensions, "narrative_variants": []})
