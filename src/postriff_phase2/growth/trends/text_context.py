"""Observed wording and bounded provider-linked context, without semantic claims.

This consumer uses current-rights inputs from AdvancedPipeline. Literal wording
is a provisional seed, not an inferred narrative, stance, unmet need or origin.
"""
from collections import defaultdict
from copy import deepcopy

from . import context, narratives

MAX_ROOTS = 20
MAX_SPAN = 240


def _support(inputs, refs):
    return {"evidence_refs": refs, "available_at": inputs["common"]["decision_cutoff"],
            "expires_at": inputs["expires_at"], "derivation_kind": "deterministic_extraction",
            "method_version": "literal_context_v1", "confidence_basis": "Observed wording; semantic meaning and stance unqualified."}


def reconstruct(inputs):
    """Reconstruct at most twenty roots from relations actually in the seal.

    Native spans retain punctuation, emoji, spacing and code switching. Unknown
    relation targets stay missing; sample completeness never proves all replies.
    """
    common = inputs["common"]
    indexed = context.source_index(common, "creative")
    sources = []
    identities = {}
    for sid, source in indexed.items():
        fact = inputs["facts"][sid]
        text = fact.get("text")
        if not isinstance(text, str):
            continue
        sources.append({**source, "text": text})
        identities[(fact["provider_id"], fact["source_identity"])] = sid
    by_id = {s["source_id"]: s for s in sources}
    roots = sorted((s for s in sources if s["original"]), key=lambda s: (s["event_at"], s["source_id"]))
    relations, missing = [], set()
    # The global relation cap is explicit. Truncation cannot become completeness.
    for source in sorted(sources, key=lambda s: s["source_id"]):
        sid = source["source_id"]
        fact = inputs["facts"][sid]
        for rel in context.bounded(fact.get("relations", []), 20):
            if rel.get("type") not in {"reply", "quote", "link"}:
                continue
            target = identities.get((fact["provider_id"], rel.get("target")))
            if target is None:
                missing.add(sid)
                continue
            if len(relations) == 2000:
                missing.add(sid)
                continue
            relations.append({"source_id": sid, "target_id": target, "relation_type": rel["type"],
                              **_support(inputs, [sid, target])})
    bundles, seeds = [], []
    for source in roots[:MAX_ROOTS]:
        sid = source["source_id"]
        bundle = context.build_context_bundle({**common, "sources": sources, "root_id": sid,
            "relations": relations, "collection_complete": False})
        bundle["bundle_id"] = context.digest([common["scope_key"], sid, bundle["member_ids"], relations])
        bundle.update(_support(inputs, bundle["member_ids"]))
        if set(bundle["member_ids"]) & missing:
            bundle["missing_context"] = sorted(set(bundle["missing_context"] + ["uncollected_relation_target"]))
        bundles.append(bundle)
        # Choose a bounded original contiguous span, not an English gloss or an
        # LLM-written paraphrase. A question mark does not prove question intent.
        end = min(len(source["text"].splitlines()[0]) if source["text"] else 0, MAX_SPAN)
        if not end or sid not in bundle["member_ids"]:
            continue
        span = source["text"][:end]
        seeds.append({"seed_id": context.digest([common["scope_key"], sid, span]),
            "concept": None, "claim": None, "stance": "unknown", "language": source["language"],
            "original_spans": [{"source_id": sid, "start": 0, "end": end, "text": span}],
            "bundle_ids": [bundle["bundle_id"]], **_support(inputs, [sid])})
    result = narratives.build_narrative({**common, "sources": sources, "episode_id": inputs["episode_id"],
                                         "bundles": bundles, "seeds": seeds})
    for seed in result["seeds"]:
        seed.update(provisional=True, interpretation_state="literal_unreviewed", stance="unknown")
    result.update(bundles=bundles, selected_root_count=min(len(roots), MAX_ROOTS),
                  eligible_root_count=len(roots), truncated=len(roots) > MAX_ROOTS,
                  selection_method="earliest_observed_within_retained_episode_then_source_id",
                  observed_original_count=len({context.canonical_key(s) for s in sources if s["original"]}),
                  qualified=False, origin="unknown")
    visible = [seed for seed in result["seeds"] if all(by_id[r]["rights"].get("display") is True for r in seed["evidence_refs"])]
    return result, visible


def question_candidates(inputs):
    """Retain actual repeated wording for review, never infer a qualified gap.

    This is an internal candidate index. Reviewed demand, context coverage and
    workspace credibility are separate future inputs; none is invented here.
    """
    groups = defaultdict(list)
    sources = context.source_index(inputs["common"], "creative", originals=True)
    for sid, source in sources.items():
        if not (context.timestamp(inputs['frame']['window_start']) <= context.timestamp(source['event_at'])
                < context.timestamp(inputs['frame']['window_end'])):
            continue
        text = inputs["facts"][sid].get("text")
        if not isinstance(text, str) or not text or len(text) > 2000:
            continue
        opening = text.splitlines()[0]
        if "?" in opening or "？" in opening:
            groups[(source["platform"], source["language"], opening)].append(sid)
    candidates = []
    for (platform, language, opening), ids in sorted(groups.items()):
        creators = {context.creator_key(sources[sid]) for sid in ids if context.creator_key(sources[sid])}
        if len(creators) < 2:
            continue
        candidates.append({"candidate_id": context.digest([inputs["common"]["scope_key"], platform, language, opening]),
            "literal_question_digest": context.digest(opening), "platform": platform, "language": language,
            "observed_original_count": len({context.canonical_key(sources[s]) for s in ids}),
            "known_creator_count": len(creators), "state": "needs_review", "demand_strength": "unknown",
            "supply_frame": deepcopy(inputs["frame"]), "gap_qualified": False,
            "reasons": ["question_intent_unreviewed", "supply_context_incomplete", "workspace_credibility_unreviewed",
                        "originality_and_risk_review_required"], **_support(inputs, sorted(ids))})
    return {"opportunities": [], "candidates": candidates[:100], "total_candidates": len(candidates),
            "truncated": len(candidates) > 100, "claim_scope": "observed_comparison_sample",
            "semantic_qualification": "unqualified", "state": "review_required" if candidates else "unknown"}
