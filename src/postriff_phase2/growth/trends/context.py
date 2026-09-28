"""Bounded, knowledge-time evidence projections. No retrieval or persistence.

Rights are deliberately explicit; callers adapt store contracts at the boundary.
Current deletion/revocation always overrides historical replay permissions.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math

METHOD = "advanced_pure_v1"
MAX_ROWS = 10_000


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timezone-aware ISO timestamp required")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone-aware ISO timestamp required")
    return dt.astimezone(timezone.utc)


def finite(value, *, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite number required")
    if minimum is not None and value < minimum:
        raise ValueError("number below minimum")
    return value


def bounded(rows, limit=MAX_ROWS):
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError("invalid or oversized collection")
    return rows


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def visible(row, cutoff):
    try:
        return (not row.get("revoked", False) and not row.get("deleted", False)
                and timestamp(row["available_at"]) <= cutoff
                and (not row.get("expires_at") or timestamp(row["expires_at"]) > cutoff))
    except (KeyError, TypeError, ValueError):
        return False


def source_index(payload, purpose="analysis", *, originals=False):
    cutoff = timestamp(payload["decision_cutoff"])
    scope = payload["scope_key"]
    if not isinstance(scope, str) or not scope:
        raise ValueError("scope_key required")
    result = {}
    seen = set()
    for row in bounded(payload.get("sources", [])):
        sid = row.get("source_id")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError("unique explicit source_id required")
        seen.add(sid)
        if row.get("scope_key") != scope or not visible(row, cutoff):
            continue
        if row.get("rights", {}).get("analysis") is not True or row["rights"].get(purpose) is not True:
            continue
        if row.get("original") not in (True, False) or not isinstance(row.get("original"), bool):
            continue
        if originals and row["original"] is not True:
            continue
        try:
            if timestamp(row["event_at"]) > cutoff or not row.get("platform"):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        result[sid] = row
    return result


def supported(row, sources, cutoff, *, all_required=True):
    refs = row.get("evidence_refs", [])
    return (visible(row, cutoff) and isinstance(refs, list) and bool(refs)
            and len(refs) <= MAX_ROWS
            and (all(ref in sources for ref in refs) if all_required
                 else any(ref in sources for ref in refs)))


def canonical_key(source):
    # Explicit canonical identities are the only cross-provider deduplication key.
    return ("canonical", source["canonical_id"]) if source.get("canonical_id") else (
        source["platform"], source["source_id"])


def creator_key(source):
    return (source["platform"], source["creator_key"]) if source.get("creator_key") else None


def envelope(payload, **fields):
    return {"method_version": METHOD, "scope_key": payload["scope_key"],
            "decision_cutoff": payload["decision_cutoff"], **fields}


def stored_projection(kind, wire_payload):
    """Projection fragment only; owner must bind full manifest, receipt and retention."""
    if kind not in {"genome", "graph", "saturation", "forecast", "whitespace", "lab_run"}:
        raise ValueError("unsupported advanced projection kind")
    return {"kind": kind, "method_id": "trend_" + kind + "_pure", "method_version": "1", "payload": wire_payload}


def build_context_bundle(payload):
    sources = source_index(payload)
    cutoff = timestamp(payload["decision_cutoff"])
    root_id = payload["root_id"]
    bounds = {"max_related": 20, "max_depth": 2, "window_hours": 48,
              "max_processing_tokens": 4096, **payload.get("bounds", {})}
    for key, ceiling in (("max_related", 20), ("max_depth", 2), ("window_hours", 48),
                         ("max_processing_tokens", 16384)):
        value = bounds[key]
        if not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= ceiling:
            raise ValueError("invalid context bound: " + key)
    if root_id not in sources:
        return envelope(payload, state="unavailable", member_ids=[], missing_context=["root_unavailable"],
                        context_completeness="partial", unique_original_posts=0)
    relations = []
    missing = []
    for rel in bounded(payload.get("relations", []), 2000):
        if rel.get("relation_type") not in {"reply", "quote", "news_thread", "link"}:
            continue
        if supported(rel, sources, cutoff):
            relations.append(rel)
        else:
            missing.append("relation_support_unavailable")
    root_time = timestamp(sources[root_id]["event_at"])
    chosen, queue, links, tokens = [], [(root_id, 0)], [], 0
    visited = set()
    while queue:
        sid, depth = queue.pop(0)
        if sid in visited:
            continue
        visited.add(sid)
        source = sources.get(sid)
        if not source or abs(timestamp(source["event_at"]) - root_time) > timedelta(hours=bounds["window_hours"]):
            missing.append("branch_unavailable_or_outside_window")
            continue
        # Conservative character budget, not a claim of provider token metering.
        cost = len(source.get("text", "")) + 16
        if tokens + cost > bounds["max_processing_tokens"] or len(chosen) >= bounds["max_related"] + 1:
            missing.append("processing_bound")
            continue
        chosen.append(sid)
        tokens += cost
        neighbors = sorted((r for r in relations if r["source_id"] == sid),
                           key=lambda r: (r["target_id"], r["relation_type"]))
        if depth == bounds["max_depth"]:
            if neighbors:
                missing.append("depth_bound")
            continue
        for rel in neighbors:
            links.append(deepcopy(rel))
            queue.append((rel["target_id"], depth + 1))
    links = [r for r in links if r["source_id"] in chosen and r["target_id"] in chosen]
    return envelope(payload, state="available", root_id=root_id, member_ids=chosen,
                    relations=links, bounds=bounds, processing_units=tokens,
                    selection_method="breadth_first_source_id", missing_context=sorted(set(missing)),
                    context_completeness="complete" if len(chosen) > 1 and not missing and
                    payload.get("collection_complete") is True else "partial",
                    unique_original_posts=len({canonical_key(sources[s]) for s in chosen if sources[s]["original"]}))
