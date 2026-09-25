"""Four-class source policy: execution, not labels (improvement SPEC §4; decisions D10).

`project_context()` is the single pure projection consulted at turn entry and again at
worker/approval time. Adapters only ever receive the projection. Sources that lack a
policy (created before this round) are forbidden for public generation until reviewed.
"""
from postriff_alpha.domain import AlphaError
from .contracts import digest

POLICIES = ("public_quote", "rewrite_approval", "internal_reference", "prohibited")
EGRESS = ("local", "cloud")
OPERATIONS = ("draft", "internal_summary")
# Sources created before this instant carry no policy and require review (legacy rule).
INTRODUCED_AT = 1789516800.0  # 2026-09-15T00:00:00Z
# Creation-time defaults by kind: author-owned material may be quoted; pasted or linked
# third-party material needs an explicit use approval before it can leave as a public post.
DEFAULTS = {"sample": "public_quote", "idea": "public_quote", "text": "rewrite_approval", "document": "rewrite_approval", "link": "rewrite_approval"}


def _source(state, source_id):
    found = next((s for s in state.get("sources", []) if s["id"] == source_id), None)
    if found is None:
        raise AlphaError("This item is not available in your workspace.", 404)
    return found


def _created_epoch(value):
    """Domain rows store ISO-8601 strings; hosted rows may store epoch floats. Unparseable → legacy."""
    if type(value) in (int, float):
        return float(value)
    if isinstance(value, str) and value:
        from datetime import datetime, timezone
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return 0.0
    return 0.0


# Why a source was left out of a run, in words a person can act on (reason codes stay in the data).
EXCLUSION_REASONS = {
    "retracted": "it was retracted",
    "policy_review_required": "its use needs review first",
    "prohibited": "its use policy does not allow this",
    "egress_consent_required": "cloud sharing is off for it (allow it on the Memory page)",
    "internal_reference_excluded_from_public_draft": "internal references stay out of public drafts",
}


def exclusion_message(reason):
    return f"A source was left out: {EXCLUSION_REASONS.get(reason, str(reason).replace('_', ' '))}."


def stamp(state):
    """Assign creation-time defaults to new sources; legacy rows stay unreviewed (None)."""
    for source in state.get("sources", []):
        if "sourcePolicy" not in source:
            created = _created_epoch(source.get("createdAt"))
            source["sourcePolicy"] = DEFAULTS.get(source.get("kind")) if created >= INTRODUCED_AT else None
        source.setdefault("egressConsent", [])
        source.setdefault("useApprovals", [])


def facts_digest(source):
    return digest([{"id": f["id"], "text": f["text"]} for f in source.get("facts", []) if f.get("approved")])


def use_approved(source):
    current = facts_digest(source)
    return any(record.get("factsDigest") == current for record in source.get("useApprovals", []))


def classify(source, operation, provider_class):
    """Return (included, exclusion_reason, candidate_only)."""
    policy = source.get("sourcePolicy")
    if not source.get("active"):
        return False, "retracted", False
    if policy is None:
        return False, "policy_review_required", False
    if policy == "prohibited":
        return False, "prohibited", False
    if provider_class == "cloud" and "cloud" not in source.get("egressConsent", []):
        return False, "egress_consent_required", False
    if policy == "internal_reference":
        if operation != "internal_summary":
            return False, "internal_reference_excluded_from_public_draft", False
        return True, None, True
    if policy == "rewrite_approval":
        return True, None, not use_approved(source)
    return True, None, False


def policy_epoch(state):
    return digest([{"id": s["id"], "policy": s.get("sourcePolicy"), "egress": sorted(s.get("egressConsent", [])), "use": use_approved(s), "active": s.get("active")} for s in state.get("sources", [])])


def project_context(state, operation, provider_class, source_ids):
    if operation not in OPERATIONS:
        raise AlphaError("Unsupported context operation.", 400)
    if provider_class not in EGRESS:
        raise AlphaError("Unsupported provider class.", 400)
    if not isinstance(source_ids, list) or len(source_ids) > 20 or len(set(source_ids)) != len(source_ids):
        raise AlphaError("Select at most 20 distinct sources.", 400)
    stamp(state)
    sources, excluded = [], []
    for source_id in source_ids:
        source = _source(state, source_id)
        included, reason, candidate_only = classify(source, operation, provider_class)
        if not included:
            excluded.append({"id": source_id, "policy": source.get("sourcePolicy"), "reason": reason})
            continue
        facts = [{"id": f["id"], "text": f["text"], "sourceId": source_id, "locator": f.get("locator", "")} for f in source.get("facts", []) if f.get("approved")]
        if not facts:
            excluded.append({"id": source_id, "policy": source.get("sourcePolicy"), "reason": "no_approved_facts"})
            continue
        sources.append({"id": source_id, "policy": source["sourcePolicy"], "candidateOnly": candidate_only, "facts": facts, "hash": digest(facts)})
    return {"schema": "postriff.context.v1", "operation": operation, "providerClass": provider_class, "sources": sources, "excluded": excluded, "policyEpoch": policy_epoch(state), "candidateOnly": any(s["candidateOnly"] for s in sources)}


def apply_policy_action(state, action, payload, actor, now):
    """Handle `source_policy` and `source_use_approve`; return True when consumed."""
    if action == "source_policy":
        stamp(state)
        source = _source(state, payload.get("sourceId"))
        policy, egress = payload.get("policy"), payload.get("egressConsent", [])
        if not source.get("active"):
            raise AlphaError("This source was withdrawn.")
        if policy not in POLICIES or payload.get("confirmed") is not True:
            raise AlphaError("Choose a source policy and confirm it.")
        if not isinstance(egress, list) or set(egress) - set(EGRESS):
            raise AlphaError("Egress consent must list 'local' and/or 'cloud'.")
        source["sourcePolicy"] = policy
        source["egressConsent"] = sorted(set(egress))
        source["policyDecidedBy"], source["policyDecidedAt"] = actor, now
        if policy in ("internal_reference", "prohibited"):
            for variant in state.get("variants", []):
                if source["id"] in variant.get("sourceIds", []):
                    variant["policyBlocked"] = True
        # Per-source publication digests invalidate dependent approvals. The shared brief stays current.
        return True
    if action == "source_use_approve":
        stamp(state)
        source = _source(state, payload.get("sourceId"))
        if source.get("sourcePolicy") != "rewrite_approval":
            raise AlphaError("Use approval applies to sources marked 'needs rewrite/approval'.")
        current = facts_digest(source)
        if payload.get("factsDigest") != current or payload.get("confirmed") is not True:
            raise AlphaError("Review the exact approved facts and confirm their public use.", 409)
        source["useApprovals"].append({"actor": actor, "at": now, "factsDigest": current})
        # Per-source publication digests invalidate dependent approvals. The shared brief stays current.
        return True
    return False


def publication_issues(state, source_ids):
    """Blockers that stop a variant referencing these sources from being scheduled/exported."""
    stamp(state)
    issues = []
    for source_id in source_ids:
        source = next((s for s in state.get("sources", []) if s["id"] == source_id), None)
        if source is None or not source.get("active"):
            continue
        policy = source.get("sourcePolicy")
        if policy is None:
            issues.append({"severity": "blocker", "ruleId": "source_policy_review_required", "message": "Review how this source may be used before publishing."})
        elif policy in ("internal_reference", "prohibited"):
            issues.append({"severity": "blocker", "ruleId": "source_not_publishable", "message": "A referenced source is internal-only or prohibited. Remove it and regenerate."})
        elif policy == "rewrite_approval" and not use_approved(source):
            issues.append({"severity": "blocker", "ruleId": "source_use_approval_required", "message": "Approve public use of this rewritten source before publishing."})
    return issues
