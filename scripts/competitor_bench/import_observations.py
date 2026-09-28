"""Import only user-supplied authorized snapshots. Does not contact a product."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json


def _time(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return dt


def manifest_hash(manifest):
    body = {k: v for k, v in manifest.items() if k != "preregistration_hash"}
    return sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def freeze_manifest(payload):
    frozen = deepcopy(payload)
    frozen["preregistration_hash"] = manifest_hash(frozen)
    validate_manifest(frozen)
    return frozen


def validate_manifest(manifest):
    fields = ("run_id", "hypothesis", "preregistered_at", "decision_cutoff", "topics", "query_grid", "planned_observation_times",
              "actual_observation_times", "rights_refs", "cost_cap", "input_hashes", "candidate_versions", "metric_definitions", "exclusions", "counterexamples", "reviewer")
    if any(k not in manifest for k in fields):
        raise ValueError("incomplete benchmark manifest")
    if manifest.get("preregistration_hash") != manifest_hash(manifest):
        raise ValueError("frozen manifest digest mismatch")
    if _time(manifest["preregistered_at"]) > _time(manifest["decision_cutoff"]):
        raise ValueError("future preregistration")
    if not 1 <= len(manifest["topics"]) <= 50 or len(manifest["query_grid"]) > 5000:
        raise ValueError("benchmark size outside bounds")
    ids = [r["topic_id"] for r in manifest["topics"]]
    if len(set(ids)) != len(ids) or any(r.get("split") not in {"development", "holdout"} for r in manifest["topics"]):
        raise ValueError("invalid topic split")
    for value in manifest["actual_observation_times"]:
        if _time(value) > _time(manifest["decision_cutoff"]):
            raise ValueError("future actual observation")
    return manifest


def build_query_grid(payload):
    result = []
    for language, aliases in sorted(payload["aliases_by_language"].items()):
        for query in aliases:
            for window in payload.get("windows", ["24h", "7d", "30d"]):
                for geography in payload.get("permitted_geographies", ["global"]):
                    if window not in {"24h", "7d", "30d"} or not isinstance(query, str) or len(query) > 200:
                        raise ValueError("invalid query perturbation")
                    result.append({"query": query, "language": language, "window": window, "geography": geography})
                    if len(result) > 5000:
                        raise ValueError("query grid bound exceeded")
    return result


def import_observations(payload):
    manifest = validate_manifest(payload["manifest"])
    rows = payload.get("observations", [])
    if len(rows) > 10000:
        raise ValueError("snapshot import bound exceeded")
    if not rows:
        return {"state": "NOT_RUN", "observations": [], "reason": "no_authorized_product_observations"}
    accepted, rejected = [], []
    cutoff = _time(manifest["decision_cutoff"])
    for row in rows:
        reasons = []
        rights = row.get("rights", {})
        if (rights.get("import") is not True or rights.get("analysis") is not True
                or row.get("rights_ref") not in manifest["rights_refs"] or row.get("revoked") is True):
            reasons.append("rights_unavailable")
        required = ("snapshot_id", "product", "source_at", "retrieved_at", "available_at", "retention_until", "evidence_hash", "query", "language", "window", "geography")
        if any(k not in row for k in required):
            reasons.append("missing_snapshot_contract")
        else:
            if any(_time(row[k]) > cutoff for k in ("retrieved_at", "available_at")) or (row["source_at"] is not None and _time(row["source_at"]) > cutoff):
                reasons.append("future_availability")
            if row.get("membership_available_at") and _time(row["membership_available_at"]) > cutoff:
                reasons.append("future_membership")
            if _time(row["retention_until"]) <= cutoff:
                reasons.append("retention_expired")
            if row["evidence_hash"] not in manifest["input_hashes"]:
                reasons.append("input_not_frozen")
            query = {k: row[k] for k in ("query", "language", "window", "geography")}
            if query not in manifest["query_grid"]:
                reasons.append("query_outside_frozen_grid")
        if reasons:
            rejected.append({"snapshot_id": row.get("snapshot_id"), "reasons": reasons})
            continue
        clean = {k: deepcopy(row.get(k)) for k in required}
        clean.update(visible_fields=deepcopy(row.get("visible_fields", {})), missingness=deepcopy(row.get("missingness", {})),
                     comparable=bool(row.get("source_at") and row.get("size_definition") and row.get("refresh_time") and row.get("coverage_ref")),
                     size_definition=row.get("size_definition"), refresh_time=row.get("refresh_time"), coverage_ref=row.get("coverage_ref"))
        accepted.append(clean)
    return {"state": "observed" if accepted else "NOT_RUN", "observations": accepted, "rejected": rejected,
            "coverage": {"submitted": len(rows), "accepted": len(accepted), "incomparable": sum(not r["comparable"] for r in accepted)}}
