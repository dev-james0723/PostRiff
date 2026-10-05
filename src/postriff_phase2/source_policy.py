"""Four-class source policy: execution, not labels (improvement SPEC §4; decisions D10).

`project_context()` is the single pure projection consulted at turn entry and again at
worker/approval time. Adapters only ever receive the projection. Sources that lack a
policy (created before this round) are forbidden for public generation until reviewed.
"""
import re
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


MAX_RETRIEVED_FACTS = 12
MAX_RETRIEVED_CHARS = 12000
_STOP = frozenset('a an and are as at be for from in is it of on or the this to with write draft post about use supplied facts source sources'.split())


def _terms(value):
    text = str(value or '').casefold()
    words = {w for w in re.findall(r'[\w]+', text) if len(w) > 1 and w not in _STOP}
    for run in re.findall(r'[\u3400-\u9fff]+', text):
        words.update(run[i:i + 2] for i in range(len(run) - 1))
    return words


def _retrieve(sources, query):
    """Deterministic relevant retrieval; no extra model call and no clipped claims."""
    terms = _terms(query)
    pool = [(s, f, len(terms & _terms(f['text']))) for s in sources for f in s['facts']]
    has_match = any(score for _, _, score in pool)
    selected, omitted, seen, used = {}, [], set(), 0
    for source, fact, score in sorted(pool, key=lambda row: (-row[2], row[0]['id'], row[1]['id'])):
        identity = ' '.join(fact['text'].casefold().split())
        reason = None
        if terms and has_match and score == 0:
            reason = 'not_relevant'
        elif identity in seen:
            reason = 'duplicate'
        elif sum(len(fs) for fs in selected.values()) >= MAX_RETRIEVED_FACTS or used + len(fact['text']) > MAX_RETRIEVED_CHARS:
            reason = 'retrieval_budget'
        if reason:
            omitted.append({'sourceId': source['id'], 'factId': fact['id'], 'reason': reason})
            continue
        seen.add(identity)
        selected.setdefault(source['id'], []).append(fact)
        used += len(fact['text'])
    chosen = [{**s, 'facts': selected[s['id']], 'hash': digest(selected[s['id']])} for s in sources if s['id'] in selected]
    metadata = {'method': 'term-overlap-dedup-v1', 'query': query, 'maxFacts': MAX_RETRIEVED_FACTS, 'maxChars': MAX_RETRIEVED_CHARS,
                'selectedFactIds': [f['id'] for s in chosen for f in s['facts']], 'omitted': omitted, 'chars': used}
    return chosen, metadata


def project_context(state, operation, provider_class, source_ids, *, query=None):
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
        origin = source.get('origin') or {}
        facts = [{"id": f["id"], "text": f["text"], "sourceId": source_id, "locator": f.get("locator", ""),
                  **({'verification': 'unverified_web_claim', 'citation': origin.get('url'), 'ownership': 'third_party'} if origin.get('kind') == 'web_research' else {})}
                 for f in source.get("facts", []) if f.get("approved")]
        if not facts:
            excluded.append({"id": source_id, "policy": source.get("sourcePolicy"), "reason": "no_approved_facts"})
            continue
        sources.append({"id": source_id, "policy": source["sourcePolicy"], "candidateOnly": candidate_only, "facts": facts, "hash": digest(facts)})
    retrieval = None
    if query is not None:
        before = sources
        sources, retrieval = _retrieve(sources, str(query)[:3000])
        selected_ids = {s['id'] for s in sources}
        excluded.extend({'id': s['id'], 'policy': s['policy'], 'reason': 'no_retrieved_facts'} for s in before if s['id'] not in selected_ids)
    return {"schema": "postriff.context.v1", "operation": operation, "providerClass": provider_class, "sources": sources, "excluded": excluded, "policyEpoch": policy_epoch(state), "candidateOnly": any(s["candidateOnly"] for s in sources),
            **({'retrieval': retrieval} if retrieval is not None else {})}


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
