"""Projection of explicitly supplied narrative assignments, never semantic invention."""
from copy import deepcopy
from .context import bounded, canonical_key, creator_key, envelope, source_index, supported, timestamp


def build_narrative(payload):
    sources = source_index(payload, "creative")
    cutoff = timestamp(payload["decision_cutoff"])
    bundle_members = set()
    valid_bundles = set()
    for bundle in bounded(payload.get("bundles", []), 1000):
        if bundle.get("scope_key") != payload["scope_key"]:
            continue
        if not supported(bundle, sources, cutoff):
            continue
        members = set(bundle.get("member_ids", [])) & sources.keys()
        if members:
            bundle_members.update(members)
            valid_bundles.add(bundle["bundle_id"])
    seeds, rejected = [], 0
    for seed in bounded(payload.get("seeds", []), 1000):
        refs = seed.get("evidence_refs", [])
        if (not supported(seed, sources, cutoff) or not set(refs) <= bundle_members
                or not seed.get("bundle_ids") or not set(seed["bundle_ids"]) <= valid_bundles
                or seed.get("stance") not in {"support", "oppose", "question", "mixed", "unknown"}):
            rejected += 1
            continue
        # Quotes and sarcasm never imply endorsement; an explicit stance remains separate.
        clean = {k: deepcopy(seed.get(k)) for k in ("seed_id", "concept", "claim", "stance", "language",
                                                  "original_spans", "evidence_refs", "bundle_ids")}
        clean["provisional"] = len({creator_key(sources[r]) for r in refs if creator_key(sources[r])}) < 2
        clean["origin"] = "unknown"
        seeds.append(clean)
    originals = {canonical_key(sources[r]) for r in bundle_members if sources[r]["original"]}
    return envelope(payload, episode_id=payload["episode_id"], revision=payload.get("revision", 1),
                    seeds=seeds, rejected_seeds=rejected, unique_original_posts=len(originals),
                    bundle_count=len(valid_bundles), size_definition="unique_deduplicated_original_posts",
                    unknowns=["semantic_accuracy_unqualified", "origin_unknown"])


def link_episodes(payload):
    sources = source_index(payload, "creative")
    cutoff = timestamp(payload["decision_cutoff"])
    links, adjacency = [], {}
    for row in sorted(bounded(payload.get("links", []), 2000), key=lambda r: r.get("available_at", "")):
        if row.get("relation") not in {"continuation", "merge", "split", "recurrence"}:
            raise ValueError("invalid lineage relation")
        if not supported(row, sources, cutoff):
            continue
        parent, child = row["parent_id"], row["child_id"]
        if parent == child or timestamp(row["parent_end"]) >= timestamp(row["child_start"]) or timestamp(row["child_start"]) > cutoff:
            raise ValueError("lineage must advance time")
        seen, todo = set(), [child]
        while todo:
            node = todo.pop()
            if node == parent:
                raise ValueError("lineage cycle")
            if node not in seen:
                seen.add(node)
                todo.extend(adjacency.get(node, []))
        adjacency.setdefault(parent, []).append(child)
        links.append(deepcopy(row))
    return envelope(payload, links=links, history_rewritten=False)
