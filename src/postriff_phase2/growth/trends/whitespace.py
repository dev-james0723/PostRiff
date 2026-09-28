"""Demand-supported gaps within an explicit, qualified comparison sample."""
from copy import deepcopy
from .context import bounded, canonical_key, envelope, finite, source_index, stored_projection, supported, timestamp

GAP_TYPES = {"unanswered_question", "counterargument", "practical_example", "language_explanation", "platform_adaptation", "declared_audience_need"}


def find_whitespace(payload):
    sources = source_index(payload, "creative", originals=True)
    cutoff = timestamp(payload["decision_cutoff"])
    opportunities, rejected = [], []
    for row in bounded(payload.get("candidates", []), 100):
        reasons = []
        demand = {r for r in row.get("demand_evidence_refs", []) if r in sources}
        demand_support = len({canonical_key(sources[r]) for r in demand})
        sample = row.get("supply_search_scope", {})
        if finite(sample.get("retrieval_coverage", 0), minimum=0) > 1:
            raise ValueError("retrieval coverage must be a ratio in [0, 1]")
        if payload.get("enabled", True) is not True:
            reasons.append("module_disabled")
        if row.get("gap_type") not in GAP_TYPES or not supported(row, sources, cutoff):
            reasons.append("candidate_evidence_unavailable")
        if demand_support < 2 or row.get("demand_strength") != "supported":
            reasons.append("weak_or_missing_observed_demand")
        if (sample.get("qualified") is not True or not sample.get("frame_id")
                or finite(sample.get("retrieval_coverage", 0), minimum=0) < 0.8
                or not supported(sample, sources, cutoff)):
            reasons.append("supply_comparison_insufficient")
        if row.get("gap_type") == "unanswered_question" and sample.get("context_complete") is not True:
            reasons.append("uncollected_or_deleted_replies")
        if not set(row.get("supporting_supply_refs", []) + row.get("opposing_supply_refs", [])) <= sources.keys():
            reasons.append("supply_evidence_unavailable")
        credibility = row.get("credibility", {})
        if credibility.get("workspace_id") != payload["workspace_id"] or credibility.get("approved") is not True or not supported(credibility, sources, cutoff):
            reasons.append("brand_capability_unsupported")
        confirmed = set(row.get("confirmed_user_fact_refs", []))
        if row.get("requires_user_fact") is True and not (confirmed and confirmed <= set(payload.get("approved_user_fact_refs", []))):
            reasons.append("user_fact_required")
        if row.get("risk_blocked") is True or row.get("originality_review") not in {"supported", "mixed"}:
            reasons.append("originality_or_risk_review_required")
        if reasons:
            rejected.append({"candidate_id": row["candidate_id"], "reasons": reasons})
            continue
        opportunities.append({k: deepcopy(row.get(k)) for k in (
            "candidate_id", "gap_type", "demand_evidence_refs", "supply_search_scope", "supporting_supply_refs",
            "opposing_supply_refs", "angle_occupancy", "credibility", "proposed_contribution", "risks", "disconfirming_evidence")})
    return envelope(payload, workspace_id=payload["workspace_id"], opportunities=opportunities, rejected=rejected,
                    claim_scope="observed_comparison_sample", semantic_qualification="unqualified")


def to_stored_projection(result):
    """Internal gap payload; service maps admitted gaps to its owned Opportunity schema."""
    return stored_projection("whitespace", {k: deepcopy(result[k]) for k in (
        "opportunities", "rejected", "claim_scope", "semantic_qualification")})
