"""Privacy notice, retention classes, data requests with receipts, sanitized diagnostics.

This is product plumbing, not legal approval: privacy/terms/tax/jurisdiction need qualified
professional review before public sale (architecture §22). The notice says so.
"""
import json
from postriff_alpha.domain import AlphaError

RETENTION_CLASSES = {
    "drafts": {"retention": "until customer deletion", "note": "Revision history is kept with the draft."},
    "sources": {"retention": "until retraction or deletion", "note": "Retraction blocks future use and dependent drafts; deletion removes text and derived chunks."},
    "generated_media": {"retention": "until customer deletion", "note": "Immutable renditions; provenance kept as hashes."},
    "provider_tokens": {"retention": "until disconnect or revocation", "note": "Encrypted at rest; ciphertext wiped on disconnect."},
    "account_pictures": {"retention": "until disconnect", "note": "The connected account's profile picture, read from the provider at connect and re-verify and re-encoded small, only to draw post previews."},
    "approvals_receipts": {"retention": "retained as records after publication", "note": "Limited deletion, trial and audit records remain after account deletion; workspace publication records are removed."},
    "analytics_observations": {"retention": "until workspace deletion; release policy pending review", "note": "Native metric observations; never sold or aggregated across tenants with content."},
    "audience_comments": {"retention": "until provider deletion or customer deletion", "note": "Tombstones preserved when a provider requires deletion."},
    "time_back": {"retention": "until account or workspace deletion", "note": "Estimated minutes saved per completed task, your answers about how long tasks usually take, and seconds of active use in Rafii workflows. No text, keystrokes, pointer positions, page structure or browsing outside Rafii."},
    "logs_traces": {"retention": "30 days candidate", "note": "Sanitized: no prompts, post bodies, tokens or files by default."},
    "backups": {"retention": "30 days rotation candidate", "note": "Database backups; object storage is backed up separately (Supabase DB backups do not include Storage)."},
}

SUBPROCESSORS = [
    {"name": "Vercel", "purpose": "hosting / API runtime", "status": "configured hosting provider; release environment to be verified"},
    {"name": "Supabase", "purpose": "authentication, PostgreSQL, private object storage", "status": "configured provider; release environment to be verified", "region": "release region to be verified"},
    {"name": "Social providers (LinkedIn, Threads, Instagram)", "purpose": "publishing and metrics for accounts the customer connects", "status": "connected only by the customer's own OAuth grant"},
    {"name": "Vercel Web Analytics; Sentry when configured", "purpose": "website usage and sanitized error diagnostics", "status": "analytics integrated; error delivery depends on configuration"},
    {"name": "Stripe", "purpose": "billing and invoices", "status": "only when an approved plan and payment provider are enabled"},
    {"name": "Resend", "purpose": "transactional email", "status": "only when a reviewed sender is configured"},
    {"name": "Exa; Jina Reader", "purpose": "public web research", "status": "only with owner research consent; release region and contract require review"},
    {"name": "Vercel AI Gateway and selected model provider; configured CLI provider", "purpose": "drafting posts and reply suggestions", "status": "configured cloud or CLI route; contract and region require release review"},
]


def notice():
    return {
        "schema": "postriff.privacy-notice.v1",
        "status": "draft — requires qualified legal review before public sale; not a legal approval",
        "aiProcessing": "Drafts are produced only from sources you select and approve. A reply suggestion you ask for sends the comment, the commenter's public handle and the post it answers to the managed writer, with facts from sources you cleared for public use and the memory you allowed; nothing is sent to the platform until you approve the reply. The deterministic preview makes no model request. A configured cloud writer, including a local CLI connected to its cloud provider, receives your instruction and permitted context. Sources require applicable egress consent; writing samples also require purpose and exact writer-route permission. Only bounded style observations are used for sample-based drafting. Paid routes reserve a workspace budget and keep unknown usage reserved until reconciled. Your voice profile, identity and boundaries reach a cloud model only if a workspace owner allows it on the Memory page, and a boundary marked private or local-only never does.",
        "providerAccess": "Rafii connects social accounts only through your own OAuth grant, requests the minimum scopes for the capability you enable, stores tokens encrypted, wipes them on disconnect, and attempts remote revocation where supported. Any unconfirmed remote revocation must be completed in the platform settings.",
        "ingestion": "Post metrics and comments are read only for accounts you connect with those capabilities enabled, and are shown with native definitions and freshness.",
        "retention": RETENTION_CLASSES,
        "subprocessors": SUBPROCESSORS,
        "rights": ["export your workspace", "disconnect any provider", "retract or delete sources", "delete your account and workspace", "request a sanitized diagnostics package only with your explicit consent"],
        "telemetry": "Operational events carry stable IDs and counts only; customer content never enters cross-tenant telemetry.",
    }


def rights_declaration(payload):
    """Customer confirms rights to uploaded/published content; provider-specific declarations are explicit fields."""
    required = {"ownsOrLicensed": True}
    if any(payload.get(key) is not value for key, value in required.items()):
        raise AlphaError("Confirm that you own or are licensed to publish this content.")
    return {"ownsOrLicensed": True, "aiGenerated": bool(payload.get("aiGenerated")), "brandedContent": bool(payload.get("brandedContent")), "musicRightsConfirmed": bool(payload.get("musicRightsConfirmed"))}


def diagnostics_package(state, consent, workspace_id):
    """Counts, versions, and states only — no prompts, drafts, sources, tokens, emails."""
    if consent is not True:
        raise AlphaError("Diagnostics require your explicit consent for this request.", 403)
    phase2 = state.get("phase2", {})
    return {
        "schema": "postriff.diagnostics.v1",
        "workspaceId": workspace_id,
        "counts": {"sources": len(state.get("sources", [])), "variants": len(state.get("variants", [])), "channels": len(phase2.get("channels", [])), "jobs": len(phase2.get("jobs", [])), "assets": len(phase2.get("assets", []))},
        "jobStates": sorted({j.get("state") for j in phase2.get("jobs", [])}),
        "channelStates": sorted({c.get("platform", "") + ":" + ("revoked" if c.get("revoked") else "active") for c in phase2.get("channels", [])}),
        "execution": phase2.get("execution"),
        "contentTypesVersion": state.get("contentSystem", {}).get("selection", {}).get("contentTypeVersion"),
        "note": "Sanitized. Contains no content, credentials, or personal identifiers.",
    }


class DataRequests:
    def __init__(self, repository, clock):
        self.repository, self.clock = repository, clock

    def record(self, cur, workspace_id, requested_by, kind, status, receipt):
        cur.execute("INSERT INTO public.pr_data_requests(workspace_id,requested_by,kind,status,receipt,completed_at) VALUES(%s,%s,%s,%s,%s::jsonb,CASE WHEN %s='completed' THEN now() END) RETURNING id::text", (workspace_id, requested_by, kind, status, json.dumps(receipt), status))
        return cur.fetchone()[0]

    def list(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, _, _):
            cur.execute("SELECT id::text,kind,status,receipt,extract(epoch from requested_at),extract(epoch from completed_at) FROM public.pr_data_requests WHERE workspace_id=%s ORDER BY requested_at DESC LIMIT 100", (workspace_id,))
            return {"requests": [{"requestId": r[0], "kind": r[1], "status": r[2], "receipt": r[3], "requestedAt": float(r[4]), "completedAt": float(r[5]) if r[5] else None} for r in cur.fetchall()]}
