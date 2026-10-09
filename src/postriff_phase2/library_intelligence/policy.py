"""Purpose-aware access for Library intelligence (engineering spec §3, §6).

Storage access, AI egress, retrieval purpose, Memory admission, voice learning and public-use approval are separate
checks. Upload alone grants nothing beyond browsing and private local indexing. Existing Ideas source-policy denials
remain denials. Every decision carries the grant revision it was made at; `recheck` repeats it before delivery so a
revocation that lands mid-request wins (time-of-check/time-of-use).
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field

from postriff_alpha.domain import AlphaError

from .. import memory, source_policy
from . import contracts as c

# Feature flags (spec §12). All default off; rollback is turning them off again.
FLAGS = {
    "enrichment": "RAFII_LIBRARY_ENRICHMENT_ENABLED",
    "retrieval": "RAFII_LIBRARY_RETRIEVAL_ENABLED",
    "voice": "RAFII_LIBRARY_VOICE_ENABLED",
    "suggestions": "RAFII_LIBRARY_SUGGESTIONS_ENABLED",
    "task_ui": "RAFII_LIBRARY_TASK_UI_ENABLED",
    "artifacts": "RAFII_LIBRARY_ARTIFACTS_ENABLED",
    "asr": "RAFII_LIBRARY_ASR_ENABLED",
    "embeddings": "RAFII_LIBRARY_EMBEDDINGS_ENABLED",
    "vision": "RAFII_LIBRARY_VISION_ENABLED",
}
TRUE = ("1", "true", "yes", "on")


def enabled(name: str, environ=None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(FLAGS[name], "")).strip().lower() in TRUE


def flag_state(environ=None) -> dict:
    return {name: enabled(name, environ) for name in FLAGS}


# Private local processing that never leaves Rafii's own runtime: deterministic parsing, perceptual image features and
# local lexical indexing. Everything cloud-side needs an explicit processing grant.
LOCAL_DEFAULTS = {("local", "extract"), ("local", "vision"), ("local", "embedding"), ("local", "ocr")}
# Who may create a grant. Cloud egress and public use are workspace privacy decisions (owner), like media_egress.
GRANT_REQUIREMENT = {"browse": "edit", "answer": "edit", "draft_evidence": "edit", "memory": "owner", "voice": "owner", "public_use": "owner"}
AI_PURPOSES = ("answer", "draft_evidence", "voice", "memory", "public_use")


@dataclass
class Decision:
    allowed: bool
    purpose: str
    asset_key: str
    reason: str | None = None
    attribution_only: bool = False
    candidate_only: bool = False
    grant_revision: int = 0
    source_sha256: str = ""
    processing: dict | None = None
    grant_ids: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "purpose": self.purpose, "assetId": self.asset_key, "reason": self.reason,
                "attributionOnly": self.attribution_only, "candidateOnly": self.candidate_only,
                "grantRevision": self.grant_revision, "processing": self.processing}


REASONS = {
    "unavailable": "This item is unavailable.",
    "not_ready": "This item has not finished processing.",
    "legacy_denied": "This source's use policy does not allow it.",
    "grant_required": "This item has not been allowed for that use.",
    "processing_grant_required": "Cloud processing has not been allowed for this item.",
    "memory_egress_required": "Memory cloud sharing is off for this workspace.",
    "not_imported_source": "Import this item as a reviewed source first.",
    "no_approved_facts": "Review and approve this source's facts first.",
    "public_use_requires_approval": "Public use of this source has not been approved.",
    "egress_consent_required": "Cloud sharing is off for this source.",
    "policy_review_required": "Review how this source may be used first.",
    "prohibited": "This source's use policy does not allow it.",
    "retracted": "This source was withdrawn.",
    "internal_reference_excluded_from_public_draft": "Internal references stay out of public drafts.",
}


def message(reason: str | None) -> str:
    return REASONS.get(reason or "", "This item is not available for that use.")


# --- revisions -------------------------------------------------------------------------------------------------------
def revisions(ctx, *, fresh: bool = False) -> dict:
    if fresh or "policy" not in ctx.caches:
        ctx.cur.execute("SELECT grant_revision,index_generation,organization_revision FROM public.pr_library_policy WHERE workspace_id=%s", (ctx.workspace_id,))
        row = ctx.cur.fetchone()
        ctx.caches["policy"] = {"grantRevision": int(row[0]), "indexGeneration": int(row[1]), "organizationRevision": int(row[2])} if row else {"grantRevision": 0, "indexGeneration": 1, "organizationRevision": 0}
    return dict(ctx.caches["policy"])


def bump(ctx, *, grant: bool = False, index: bool = False, organization: bool = False) -> dict:
    """Advance revisions inside the caller's transaction and invalidate this request's caches."""
    ctx.cur.execute(
        "INSERT INTO public.pr_library_policy(workspace_id,grant_revision,index_generation,organization_revision) VALUES(%s,%s,%s,%s) "
        "ON CONFLICT(workspace_id) DO UPDATE SET grant_revision=pr_library_policy.grant_revision+%s,index_generation=pr_library_policy.index_generation+%s,"
        "organization_revision=pr_library_policy.organization_revision+%s,updated_at=now() RETURNING grant_revision,index_generation,organization_revision",
        (ctx.workspace_id, int(grant), 1 + int(index), int(organization), int(grant), int(index), int(organization)))
    row = ctx.cur.fetchone()
    ctx.caches.clear()
    ctx.caches["policy"] = {"grantRevision": int(row[0]), "indexGeneration": int(row[1]), "organizationRevision": int(row[2])}
    return dict(ctx.caches["policy"])


# --- grants ----------------------------------------------------------------------------------------------------------
def active_grants(ctx) -> list[dict]:
    if "grants" not in ctx.caches:
        ctx.cur.execute("SELECT id::text,grant_type,scope_kind,scope_key,member_keys,purpose,location,category,attestation,granted_by::text,granted_revision,extract(epoch from granted_at) "
                        "FROM public.pr_library_grants WHERE workspace_id=%s AND revoked_at IS NULL ORDER BY granted_at", (ctx.workspace_id,))
        ctx.caches["grants"] = [{"id": r[0].replace("-", ""), "grantType": r[1], "scopeKind": r[2], "scopeKey": r[3], "memberKeys": list(r[4] or []),
                                 "purpose": r[5], "location": r[6], "category": r[7], "attestation": r[8] or {}, "grantedBy": r[9],
                                 "grantedRevision": int(r[10]), "grantedAt": float(r[11])} for r in ctx.cur.fetchall()]
    return ctx.caches["grants"]


def _covers(grant: dict, key: str) -> bool:
    """`key` is always a version key. Asset grants cover exactly the versions that existed when granted (snapshotted in
    member_keys): linking another item into the lineage later never broadens an owner's grant. Collection grants are
    likewise fixed to the members captured when granted."""
    if grant["scopeKind"] == "workspace":
        return True
    if grant["scopeKind"] == "asset":
        return key in grant["memberKeys"] if grant["memberKeys"] else grant["scopeKey"] == key
    return key in grant["memberKeys"]


def purpose_grants(ctx, purpose: str, key: str) -> list[dict]:
    return [g for g in active_grants(ctx) if g["grantType"] == "purpose" and g["purpose"] == purpose and _covers(g, key)]


def processing_grants(ctx, location: str, category: str, key: str) -> list[dict]:
    return [g for g in active_grants(ctx) if g["grantType"] == "processing" and g["location"] == location and g["category"] == category and _covers(g, key)]


def _ideas_source(ctx, version: dict):
    source_id = version.get("sourceId")
    if not source_id:
        return None
    if "stamped" not in ctx.caches:
        source_policy.stamp(ctx.state)
        ctx.caches["stamped"] = True
    return next((s for s in ctx.state.get("sources", []) if s.get("id") == source_id), None)


ideas_source = _ideas_source  # public name for comparison/relations; the private one stays for existing callers


def _legacy_denial(ctx, version: dict, location: str | None = None) -> str | None:
    """Existing Ideas source decisions stay authoritative: retracted/prohibited deny everything beyond browsing, and for
    any cloud location an unreviewed policy or missing per-source cloud sharing denies too."""
    source = _ideas_source(ctx, version)
    if source is None:
        return None
    if not source.get("active"):
        return "retracted"
    if source.get("sourcePolicy") == "prohibited":
        return "legacy_denied"
    if location == "cloud":
        if source.get("sourcePolicy") is None:
            return "policy_review_required"
        if "cloud" not in (source.get("egressConsent") or []):
            return "egress_consent_required"
    return None


def authorize_processing(ctx, version: dict, location: str, category: str) -> Decision:
    """May this version's content be processed at this location by this provider category?"""
    c.processing_grant({"location": location, "category": category})
    revs = revisions(ctx)
    key = version["versionId"]
    base = Decision(False, "processing", key, grant_revision=revs["grantRevision"], source_sha256=version.get("sha256") or "",
                    processing={"location": location, "category": category})
    if version.get("status") in ("deleting", "duplicate", "missing"):
        base.reason = "unavailable"
        return base
    denial = _legacy_denial(ctx, version, location)
    if denial:
        base.reason = denial
        return base
    if (location, category) in LOCAL_DEFAULTS:
        base.allowed = True
        return base
    grants = processing_grants(ctx, location, category, key)
    if not grants:
        base.reason = "processing_grant_required"
        return base
    base.allowed, base.grant_ids = True, [g["id"] for g in grants]
    return base


def authorize_source(ctx, version: dict, purpose: str, processing: dict | None = None) -> Decision:
    """authorize_source(ctx, ref, purpose, processing=None) -> Decision (implementation plan T01).

    `version` is a resolved version (versions.resolve), so workspace isolation already happened: a foreign or missing
    key never reaches this function. The decision does not reveal why a foreign item is missing."""
    purpose = c.purpose(purpose)
    processing = c.processing_grant(processing)
    revs = revisions(ctx)
    key = version["versionId"]
    decision = Decision(False, purpose, key, grant_revision=revs["grantRevision"], source_sha256=version.get("sha256") or "", processing=processing)
    if not ctx.allows("read"):
        decision.reason = "unavailable"
        return decision
    if version.get("status") in ("deleting", "duplicate", "missing"):
        decision.reason = "unavailable"
        return decision
    if purpose == "browse" and (processing is None or processing["location"] == "local"):
        decision.allowed = True
        return decision
    # Showing an item's content to a cloud model is not browsing: it needs the same answer + processing grants.
    effective = "answer" if purpose == "browse" else purpose
    if version.get("status") not in ("ready", "unsupported", "legacy"):
        decision.reason = "not_ready"
        return decision
    denial = _legacy_denial(ctx, version)
    if denial:
        decision.reason = denial
        return decision
    if processing is not None:
        proc = authorize_processing(ctx, version, processing["location"], processing["category"])
        if not proc.allowed:
            decision.reason = proc.reason
            return decision
        decision.grant_ids += proc.grant_ids
    if purpose in ("draft_evidence", "public_use"):
        # The existing Ideas fact review and publication gates stay authoritative for these purposes.
        source = _ideas_source(ctx, version)
        if source is None:
            decision.reason = "not_imported_source"
            return decision
        if (source.get("origin") or {}).get("sha256") not in (None, version.get("sha256")):
            decision.reason = "not_imported_source"
            return decision
        if purpose == "draft_evidence":
            provider = (processing or {}).get("location", "cloud")
            included, reason, candidate_only = source_policy.classify(source, "draft", provider)
            if not included:
                decision.reason = reason
                return decision
            if not any(f.get("approved") for f in source.get("facts", [])):
                decision.reason = "no_approved_facts"
                return decision
            decision.allowed, decision.candidate_only = True, candidate_only
            return decision
        policy = source.get("sourcePolicy")
        if policy == "public_quote" or (policy == "rewrite_approval" and source_policy.use_approved(source)):
            decision.allowed = True
            return decision
        decision.reason = "public_use_requires_approval"
        return decision
    grants = purpose_grants(ctx, effective, key)
    if not grants:
        decision.reason = "grant_required"
        return decision
    if purpose == "memory" and (processing or {}).get("location") == "cloud" and memory.egress(ctx.state).get("cloud") is not True:
        decision.reason = "memory_egress_required"
        return decision
    decision.allowed, decision.grant_ids = True, decision.grant_ids + [g["id"] for g in grants]
    # A private answer may attribute what a source says; it never turns those statements into approved facts.
    decision.attribution_only = effective in ("answer", "memory")
    return decision


def require(decision: Decision) -> Decision:
    if not decision.allowed:
        status = 404 if decision.reason == "unavailable" else 403
        raise AlphaError(message(decision.reason), status, code="library_" + (decision.reason or "denied"))
    return decision


def recheck(ctx, decisions):
    """Before delivering a response or finalizing a derivative: if the grant revision moved, re-authorize from fresh
    state and drop anything no longer allowed. A plain read of the committed revision: taking a row lock here would let a
    slow answer or job (which may still wait on a provider) block every revocation in the workspace."""
    single = isinstance(decisions, Decision)
    items = [decisions] if single else list(decisions)
    ctx.cur.execute("SELECT grant_revision FROM public.pr_library_policy WHERE workspace_id=%s", (ctx.workspace_id,))
    row = ctx.cur.fetchone()
    current = int(row[0]) if row else 0
    if all(d.grant_revision == current for d in items):
        return decisions
    from . import versions
    ctx.caches.clear()
    loaded = versions.load(ctx, [d.asset_key for d in items])
    fresh = []
    for d in items:
        version = loaded.get(d.asset_key)
        if version is None:
            fresh.append(Decision(False, d.purpose, d.asset_key, reason="unavailable", grant_revision=current))
        elif d.purpose == "processing":
            fresh.append(authorize_processing(ctx, version, d.processing["location"], d.processing["category"]))
        else:
            fresh.append(authorize_source(ctx, version, d.purpose, d.processing))
    return fresh[0] if single else fresh


def eligible(ctx, purpose: str, versions_by_key: dict, processing: dict | None = None) -> dict:
    """Bulk decisions for search: purpose filters run before ranking, never after."""
    return {key: authorize_source(ctx, version, purpose, processing) for key, version in versions_by_key.items()}


def grant(ctx, body: dict) -> dict:
    """Create one explicit, scoped, auditable grant. Collections snapshot their current members."""
    if not isinstance(body, dict) or not set(body) <= {"grantType", "scope", "purpose", "location", "category", "attestation", "expectedRevision"}:
        c.fail("Send a grant with a type, scope and purpose or processing.")
    grant_type = body.get("grantType")
    if grant_type not in ("purpose", "processing"):
        c.fail("Choose a purpose or processing grant.")
    scope = body.get("scope") or {"kind": "workspace"}
    if not isinstance(scope, dict) or scope.get("kind") not in ("workspace", "asset", "collection"):
        c.fail("Choose the workspace, one item or one collection.")
    if grant_type == "purpose":
        purpose = c.purpose(body.get("purpose"))
        if purpose == "browse":
            c.fail("Browsing needs no grant.")
        if purpose in ("draft_evidence", "public_use"):
            c.fail("Draft evidence and public use are approved through source review, not a Library grant.", 409, "library_use_source_review")
        requirement = GRANT_REQUIREMENT[purpose]
        location = category = None
    else:
        processing = c.processing_grant({"location": body.get("location"), "category": body.get("category")})
        location, category, purpose = processing["location"], processing["category"], None
        if (location, category) in LOCAL_DEFAULTS:
            c.fail("Private local processing needs no grant.")
        requirement = "owner"
    ctx.require(requirement)
    attestation = body.get("attestation") or {}
    if not isinstance(attestation, dict) or len(json.dumps(attestation)) > 2000:
        c.fail("Keep the attestation short.")
    if purpose == "voice" and attestation.get("authoredByMe") is not True:
        c.fail("Confirm that you wrote this material before it can teach your voice.", 422, "library_voice_attestation")
    if purpose == "voice" and scope["kind"] != "asset":
        c.fail("Voice can only be allowed one item at a time, after you confirm you wrote it.", 422, "library_voice_scope")
    revs = revisions(ctx, fresh=True)
    expected = body.get("expectedRevision")
    if expected is not None and expected != revs["grantRevision"]:
        raise AlphaError("Library permissions changed. Review them again.", 409, code="library_grant_conflict")
    members, scope_key = [], "*"
    if scope["kind"] == "asset":
        from . import versions
        version = versions.get(ctx, c.asset_key(scope.get("assetId")))
        scope_key = version["assetId"]
        # Pin the grant to the versions that exist now; a later version or a linked item needs its own decision.
        members = [version["versionId"]]
        if not version.get("legacy"):
            try:
                members = list(dict.fromkeys([v["versionId"] for v in versions.stack(ctx, version["assetId"])] + members))
            except AlphaError:
                pass  # no stack row visible: the grant covers exactly the resolved version
    elif scope["kind"] == "collection":
        scope_key = c.asset_key(scope.get("collectionId"))
        ctx.cur.execute("SELECT 1 FROM public.pr_library_collections WHERE workspace_id=%s AND id=%s", (ctx.workspace_id, uuid.UUID(hex=scope_key)))
        if not ctx.cur.fetchone():
            raise AlphaError("Collection unavailable.", 404, code="library_unavailable")
        ctx.cur.execute("SELECT asset_key FROM public.pr_library_collection_items WHERE workspace_id=%s AND collection_id=%s ORDER BY asset_key LIMIT 5000", (ctx.workspace_id, uuid.UUID(hex=scope_key)))
        members = [r[0] for r in ctx.cur.fetchall()]
    revs = bump(ctx, grant=True)
    grant_id = uuid.uuid4()
    ctx.cur.execute("INSERT INTO public.pr_library_grants(id,workspace_id,grant_type,scope_kind,scope_key,member_keys,purpose,location,category,attestation,granted_by,granted_revision) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)",
                    (grant_id, ctx.workspace_id, grant_type, scope["kind"], scope_key, members, purpose, location, category, json.dumps(attestation), ctx.actor, revs["grantRevision"]))
    _audit(ctx, "library.grant_created", grant_id.hex, {"type": grant_type, "scope": scope["kind"], "purpose": purpose, "location": location, "category": category, "members": len(members)})
    return {"grantId": grant_id.hex, "grantRevision": revs["grantRevision"]}


def revoke(ctx, grant_id: str, expected_revision: int | None = None) -> dict:
    """Revocation increments the grant revision and propagates in the same transaction: queued jobs cancel, embeddings
    tombstone, voice spans withdraw, packs and suggestions stop. Already-issued signed URLs expire on their own (≤300 s)."""
    key = c.asset_key(grant_id)
    ctx.cur.execute("SELECT grant_type,scope_kind,scope_key,member_keys,purpose,location,category FROM public.pr_library_grants WHERE workspace_id=%s AND id=%s AND revoked_at IS NULL FOR UPDATE",
                    (ctx.workspace_id, uuid.UUID(hex=key)))
    row = ctx.cur.fetchone()
    if not row:
        raise AlphaError("This permission is unavailable or already withdrawn.", 404, code="library_unavailable")
    grant_type, scope_kind, scope_key, members, purpose, location, category = row
    ctx.require(GRANT_REQUIREMENT.get(purpose, "owner") if grant_type == "purpose" else "owner")
    revs = revisions(ctx, fresh=True)
    if expected_revision is not None and expected_revision != revs["grantRevision"]:
        raise AlphaError("Library permissions changed. Review them again.", 409, code="library_grant_conflict")
    revs = bump(ctx, grant=True)
    ctx.cur.execute("UPDATE public.pr_library_grants SET revoked_at=now(),revoked_by=%s,revoked_revision=%s WHERE workspace_id=%s AND id=%s",
                    (ctx.actor, revs["grantRevision"], ctx.workspace_id, uuid.UUID(hex=key)))
    scope = {"kind": scope_kind, "key": scope_key, "members": list(members or [])}
    from . import lifecycle
    receipt = lifecycle.propagate_revocation(ctx, {"grantType": grant_type, "purpose": purpose, "location": location, "category": category, "scope": scope})
    _audit(ctx, "library.grant_revoked", key, {"type": grant_type, "purpose": purpose, "location": location, "category": category})
    return {"grantId": key, "grantRevision": revs["grantRevision"], "propagation": receipt,
            "residual": "Private download links already issued expire within 5 minutes; material already sent to a provider cannot be recalled."}


def list_grants(ctx) -> dict:
    ctx.require("read")
    return {"grants": active_grants(ctx), "revisions": revisions(ctx), "flags": flag_state()}


def _audit(ctx, kind: str, subject: str, meta: dict):
    from ..hosted import audit
    audit(ctx.cur, ctx.workspace_id, ctx.actor, kind, subject, meta)
