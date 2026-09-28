"""Pure Lab snapshots and advisory patches for the existing draft editor.

The service supplies authorized saved objects. This module cannot authenticate a
client, create a durable job, reserve budget, apply a patch or approve publication.
"""
from copy import deepcopy
import re
from .context import bounded, digest, envelope, source_index, stored_projection, supported, timestamp

DIAGNOSTICS = ("trend_relevance", "audience_fit", "originality", "hook_crowding", "format_fit",
               "timing", "platform_fit", "historical_similarity", "risk")
PERSONAL_CLAIM = re.compile(r"\b(?:I|we|my clients|our clients)\s+(?:tested|tried|earned|achieved|proved|used|made|grew|won)\b|我(?:哋)?(?:測試過|試過|賺咗|實測|亲测|親測)", re.I)


def _refs(payload):
    draft, opportunity, context, receipt = (payload[k] for k in ("draft", "opportunity", "context", "receipt"))
    workspace = payload["workspace_id"]
    if any(obj.get("workspace_id") != workspace for obj in (draft, opportunity, context)):
        raise ValueError("workspace mismatch")
    if receipt.get("scope_key") != payload["scope_key"]:
        raise ValueError("receipt scope mismatch")
    if (opportunity.get("draft_id") != draft["id"] or opportunity.get("trust_receipt_id") != receipt["id"]
            or str(opportunity.get("context_revision")) != str(context["revision"])):
        raise ValueError("opportunity linkage mismatch")
    if draft.get("saved") is not True or not isinstance(draft.get("text"), str):
        raise ValueError("saved draft required")
    if any(payload["target_platform"] not in obj.get("allowed_platforms", []) for obj in (draft, opportunity)):
        raise ValueError("target platform not allowed by saved draft/opportunity")
    for obj in (draft, opportunity):
        if isinstance(obj.get("revision"), bool) or not isinstance(obj.get("revision"), int) or obj["revision"] < 0:
            raise ValueError("nonnegative draft/opportunity revision required")
    return {"draft_id": draft["id"], "draft_revision": draft["revision"], "draft_digest": digest(draft["text"]),
            "opportunity_id": opportunity["id"], "opportunity_revision": opportunity["revision"],
            "opportunity_digest": digest(opportunity), "context_revision": str(context["revision"]),
            "context_digest": digest(context), "trust_receipt_id": receipt["id"], "receipt_digest": digest(receipt),
            "own_history_digest": digest(payload.get("own_history")),
            "comparison_digest": digest(payload.get("comparison_sample")),
            "selected_angle_digest": digest(payload.get("selected_angle")),
            "target_platform": payload["target_platform"], "method_version": payload.get("lab_method_version", "lab_pure_v1")}


def _freshness(payload):
    cutoff = timestamp(payload["decision_cutoff"])
    sources = source_index(payload)
    receipt, opportunity = payload["receipt"], payload["opportunity"]
    reasons = []
    for name, obj in (("receipt", receipt), ("opportunity", opportunity)):
        if obj.get("verification_state") != "verified" or not supported(obj, sources, cutoff):
            reasons.append(name + "_invalid")
        if not obj.get("expires_at") or timestamp(obj["expires_at"]) <= cutoff:
            reasons.append(name + "_expired")
    if payload.get("enabled", True) is not True:
        reasons.append("module_disabled")
    return reasons


def freeze_run(payload):
    """Freeze server objects; returned snapshot alone does not represent a queued job."""
    refs = _refs(payload)
    reasons = _freshness(payload)
    request = payload.get("request", {})
    for name in ("draft_id", "draft_revision", "opportunity_id", "opportunity_revision", "target_platform"):
        if name in request and request[name] != refs[name]:
            raise ValueError("request revision or linkage mismatch: " + name)
    key = payload.get("idempotency_key", request.get("idempotency_key"))
    if not isinstance(key, str) or not key or len(key) > 200:
        raise ValueError("idempotency_key required")
    expiry = min((payload["receipt"]["expires_at"], payload["opportunity"]["expires_at"]), key=timestamp)
    return envelope(payload, kind="lab_run", schema_version=1,
                    id=payload.get("run_id", digest({"workspace": payload["workspace_id"], "key": key, **refs})[:32]),
                    workspace_id=payload["workspace_id"], **{k: v for k, v in refs.items() if k != "method_version"},
                    lab_method_version=refs["method_version"], idempotency_key=key, expires_at=expiry,
                    state="unavailable", failure_reason=",".join(reasons) if reasons else "evaluation_not_executed",
                    diagnostics=[], execution_state="frozen_input_only", stale_reasons=reasons)


def project_run(payload):
    """Project a stored run against current server-resolved draft/context/rights."""
    run = deepcopy(payload["run"])
    if run.get("workspace_id") != payload["workspace_id"] or run.get("scope_key") != payload["scope_key"]:
        raise ValueError("run scope mismatch")
    reasons = _freshness(payload)
    if timestamp(run["decision_cutoff"]) > timestamp(payload["decision_cutoff"]):
        reasons.append("run_not_available_at_cutoff")
    try:
        current = _refs(payload)
        for key, value in current.items():
            stored_key = "lab_method_version" if key == "method_version" else key
            if run.get(stored_key) != value:
                reasons.append(key + "_changed")
    except ValueError:
        reasons.append("linkage_changed")
    if timestamp(run["expires_at"]) <= timestamp(payload["decision_cutoff"]):
        reasons.append("run_expired")
    creative = source_index(payload, "creative")
    for finding in run.get("diagnostics", []):
        if finding.get("evidence_refs") and not set(finding["evidence_refs"]) <= creative.keys():
            reasons.append("finding_support_revoked")
    if reasons:
        run.update(state="stale", diagnostics=[], stale_reasons=sorted(set(reasons)), failure_reason="stale_dependencies")
    return run


def evaluate_run(payload):
    """Deterministic checks plus validated supplied findings, never a model dispatch."""
    run = project_run(payload)
    if run["state"] in {"stale", "cancelled", "failed"}:
        return run
    cutoff = timestamp(payload["decision_cutoff"])
    sources = source_index(payload, "creative")
    draft = payload["draft"]["text"]
    supplied = {}
    for finding in bounded(payload.get("findings", []), 100):
        name = finding.get("dimension")
        if name not in DIAGNOSTICS or name in supplied:
            raise ValueError("unknown or duplicate diagnostic dimension")
        if not supported(finding, sources, cutoff):
            continue
        if finding.get("assessment") not in {"supported", "concern", "mixed", "unknown"}:
            raise ValueError("invalid assessment")
        facts = set(payload["context"].get("approved_user_fact_refs", []))
        asserted = set(finding.get("user_fact_refs", []))
        if PERSONAL_CLAIM.search(finding.get("claim", "")) and not (asserted and asserted <= facts):
            continue
        if name in {"format_fit", "historical_similarity"} and finding.get("historical_claim") is True:
            history = payload.get("own_history", {})
            if (history.get("workspace_id") != payload["workspace_id"] or history.get("comparable") is not True
                    or not supported(history, sources, cutoff) or not history.get("published_count")):
                continue
        clean = {"dimension": name, "assessment": finding["assessment"], "claim": finding.get("claim", ""),
                 "evidence_refs": deepcopy(finding["evidence_refs"]), "comparison_frame": finding.get("comparison_frame", ""),
                 "uncertainty": finding.get("uncertainty", "Semantic accuracy unqualified"),
                 "requires_user_fact": finding.get("requires_user_fact") is True, "suggested_edit": None}
        edit = finding.get("suggested_edit")
        if edit:
            if not edit.get("before") or draft.count(edit["before"]) != 1:
                continue
            requires_fact = clean["requires_user_fact"] or bool(PERSONAL_CLAIM.search(edit.get("after", "")))
            clean["requires_user_fact"] = requires_fact and not (asserted and asserted <= facts)
            if not clean["requires_user_fact"]:
                clean["suggested_edit"] = {k: edit[k] for k in ("id", "before", "after", "reason")}
        supplied[name] = clean
    diagnostics = []
    for name in DIAGNOSTICS:
        diagnostics.append(supplied.get(name, {"dimension": name, "assessment": "unknown", "claim": "",
                           "evidence_refs": [], "comparison_frame": "", "uncertainty": "Insufficient permitted evidence",
                           "requires_user_fact": False, "suggested_edit": None}))
    # Cheap phrase matching reports only observed exact reuse; dissimilarity is not originality.
    repeated = []
    for sid, source in sources.items():
        phrase = source.get("text", "").strip()
        if len(phrase) >= 20 and phrase in draft:
            repeated.append(sid)
    run.update(state="completed", failure_reason=None, execution_state="pure_deterministic",
               diagnostics=diagnostics, exact_phrase_matches=sorted(repeated), qualification="unqualified")
    return run


def select_patches(payload):
    """Return a selective edit proposal; caller must use existing revision-checked edit."""
    run = project_run(payload)
    selected = bounded(payload.get("selected_edit_ids", []), 9)
    if run["state"] != "completed":
        return {"state": "unavailable", "reason": run["state"], "patches": []}
    edits = {f["suggested_edit"]["id"]: f["suggested_edit"] for f in run["diagnostics"] if f.get("suggested_edit") and not f["requires_user_fact"]}
    if len(set(selected)) != len(selected) or not set(selected) <= edits.keys():
        raise ValueError("unknown or duplicate selected edit")
    patches, spans = [], []
    text = payload["draft"]["text"]
    for eid in selected:
        edit = edits[eid]
        if text.count(edit["before"]) != 1:
            raise ValueError("patch anchor changed or ambiguous")
        start = text.index(edit["before"])
        end = start + len(edit["before"])
        if any(start < b and a < end for a, b in spans):
            raise ValueError("selected edits overlap")
        spans.append((start, end))
        patches.append(deepcopy(edit))
    return {"state": "proposal", "draft_id": run["draft_id"], "expected_revision": run["draft_revision"],
            "expected_digest": run["draft_digest"], "context_revision": run["context_revision"],
            "trust_receipt_id": run["trust_receipt_id"], "patches": patches,
            "invalidate_approval": bool(patches), "invalidate_checks": bool(patches),
            "requires_existing_variant_edit": True, "publisher_mutated": False}


def to_stored_projection(result):
    """Canonical labRunSchema; persist the full frozen run separately for stale checks."""
    fields = ("id", "state", "draft_id", "draft_revision", "opportunity_id", "opportunity_revision", "context_revision",
              "trust_receipt_id", "expires_at", "failure_reason", "diagnostics")
    return stored_projection("lab_run", {k: deepcopy(result[k]) for k in fields})
