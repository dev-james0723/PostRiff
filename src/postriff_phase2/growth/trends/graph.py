"""Bounded association graphs with immediate read-time support invalidation."""
from copy import deepcopy
from .context import bounded, envelope, source_index, stored_projection, supported, timestamp, visible

NODE_TYPES = {"topic", "narrative_episode", "phrase", "pattern", "community", "creator", "platform", "public_event"}
EDGE_TYPES = {"reply", "quote", "link", "co_occurrence", "semantic_similarity", "continuity", "possible_adaptation", "explicit_identity"}


def project_graph(payload):
    sources = source_index(payload, "creative")
    cutoff = timestamp(payload["decision_cutoff"])
    if payload.get("enabled", True) is not True:
        return envelope(payload, state="disabled", nodes=[], edges=[], claims=[], table=[])
    nodes = {}
    for node in bounded(payload.get("nodes", []), 5000):
        if node.get("node_type") not in NODE_TYPES or node.get("scope_key") != payload["scope_key"]:
            continue
        if not supported(node, sources, cutoff):
            continue
        if node["node_id"] in nodes:
            raise ValueError("duplicate graph node")
        if node["node_type"] == "creator" and not (node.get("platform") and node.get("creator_key")):
            raise ValueError("creator identity must be provider-scoped")
        if node["node_type"] == "creator" and not any(sources[r]["platform"] == node["platform"] and
                sources[r].get("creator_key") == node["creator_key"] for r in node["evidence_refs"]):
            continue
        clean = {k: deepcopy(node.get(k)) for k in ("node_id", "node_type", "label", "platform", "creator_key")}
        if node["node_type"] == "creator" and any(sources[r]["rights"].get("display") is not True for r in node["evidence_refs"]):
            # Do not emit a forbidden provider identity even in hidden table data.
            continue
        nodes[node["node_id"]] = clean
    edges, invalid = [], []
    for edge in bounded(payload.get("edges", []), 10_000):
        eid = edge["edge_id"]
        if (edge.get("edge_type") not in EDGE_TYPES or edge.get("scope_key") != payload["scope_key"]
                or edge.get("source_id") not in nodes or edge.get("target_id") not in nodes
                or not supported(edge, sources, cutoff, all_required=False)):
            invalid.append(eid)
            continue
        kind = edge.get("evidence_kind")
        if kind not in {"provider_relation", "calculated_association", "model_hypothesis"}:
            invalid.append(eid)
            continue
        if edge["edge_type"] in {"reply", "quote", "link"} and kind != "provider_relation":
            invalid.append(eid)
            continue
        if edge["edge_type"] == "explicit_identity" and edge.get("identity_authorized") is not True:
            invalid.append(eid)
            continue
        if edge["edge_type"] == "possible_adaptation" and (kind != "model_hypothesis" or not edge.get("structural_evidence")):
            invalid.append(eid)
            continue
        if timestamp(edge["event_start"]) > timestamp(edge["event_end"]) or timestamp(edge["event_end"]) > cutoff:
            invalid.append(eid)
            continue
        clean = {k: deepcopy(edge.get(k)) for k in ("edge_id", "edge_type", "source_id", "target_id",
                 "event_start", "event_end", "available_at", "method_version", "uncertainty", "evidence_kind", "expires_at")}
        clean["evidence_refs"] = sorted(r for r in edge["evidence_refs"] if r in sources)
        clean["claim_type"] = "hypothesis" if kind == "model_hypothesis" else "observed_association"
        edges.append(clean)
    valid_ids = {e["edge_id"] for e in edges}
    claims = []
    # Dependency closure is checked before truncation, including downstream opportunities.
    pending = bounded(payload.get("claims", []), 2000)[:]
    while pending:
        admitted = []
        for row in pending:
            deps = row.get("depends_on", [])
            if deps and all(d in valid_ids for d in deps) and supported(row, sources, cutoff):
                if row.get("claim_type") not in {"association", "hypothesis"}:
                    continue
                claims.append({k: deepcopy(row.get(k)) for k in ("claim_id", "claim_type", "claim", "depends_on", "evidence_refs", "available_at", "uncertainty")})
                valid_ids.add(row["claim_id"])
                admitted.append(row)
        if not admitted:
            break
        pending = [r for r in pending if r not in admitted]
    start = payload.get("root_node_id")
    selected = set(nodes) if start is None else ({start} & nodes.keys())
    if start is not None:
        for _ in range(2):
            selected |= {e[k] for e in edges if e["source_id"] in selected or e["target_id"] in selected
                         for k in ("source_id", "target_id")}
    selected = set(sorted(selected)[:100])
    output_edges = sorted((e for e in edges if e["source_id"] in selected and e["target_id"] in selected),
                          key=lambda e: e["edge_id"])[:200]
    first_seen = {}
    for source in sources.values():
        platform = source["platform"]
        value = source["event_at"]
        if platform not in first_seen or timestamp(value) < timestamp(first_seen[platform]):
            first_seen[platform] = value
    return envelope(payload, state="available", nodes=[nodes[n] for n in sorted(selected)], edges=output_edges,
                    table=deepcopy(output_edges), claims=claims, invalid_edge_ids=invalid,
                    invalid_claim_ids=[r["claim_id"] for r in pending], first_observed_by_platform=first_seen,
                    coverage=deepcopy(payload.get("coverage", {})), origin="unknown", causal_claims=False,
                    truncated=len(selected) < len(nodes) or len(output_edges) < len(edges))


def to_stored_projection(result):
    """Canonical propagationSchema; a calculated association is never a causal link."""
    nodes = [{"id": n["node_id"], "label": n.get("label") or n["node_type"], "first_seen": None} for n in result["nodes"]]
    edges = [{"id": e["edge_id"], "from": e["source_id"], "to": e["target_id"], "relation": e["edge_type"],
              "basis": "observed" if e["evidence_kind"] == "provider_relation" else "hypothesized",
              "evidence_refs": e["evidence_refs"], "limitation": "Observed sample only; no origin, influence or causal assertion."} for e in result["edges"]]
    return stored_projection("graph", {"version": "1", "scope": result["scope_key"], "nodes": nodes,
                                       "edges": edges, "truncated": result.get("truncated", False)})
