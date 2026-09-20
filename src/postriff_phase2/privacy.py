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
    "approvals_receipts": {"retention": "retained as records after publication", "note": "Content-free receipts survive account deletion as tombstones/hashes where required for audit."},
    "analytics_observations": {"retention": "plan-dependent, minimum 90 days", "note": "Native metric observations; never sold or aggregated across tenants with content."},
    "audience_comments": {"retention": "until provider deletion or customer deletion", "note": "Tombstones preserved when a provider requires deletion."},
    "logs_traces": {"retention": "30 days candidate", "note": "Sanitized: no prompts, post bodies, tokens or files by default."},
    "backups": {"retention": "30 days rotation candidate", "note": "Database backups; object storage is backed up separately (Supabase DB backups do not include Storage)."},
}

SUBPROCESSORS = [
    {"name": "Vercel", "purpose": "hosting / API runtime", "status": "in use"},
    {"name": "Supabase", "purpose": "authentication, PostgreSQL, private object storage", "status": "in use", "region": "us-east-1"},
    {"name": "Social providers (LinkedIn, Threads, Instagram)", "purpose": "publishing and metrics for accounts the customer connects", "status": "connected only by the customer's own OAuth grant"},
    {"name": "AI model provider", "purpose": "drafting", "status": "not yet contracted; only the deterministic preview runs today"},
]


def notice():
    return {
        "schema": "postriff.privacy-notice.v1",
        "status": "draft — requires qualified legal review before public sale; not a legal approval",
        "aiProcessing": "Drafts are produced only from sources you select and approve. Today the runtime is a deterministic preview with no model request. When a model provider is contracted, egress requires your explicit per-source consent and is metered to your workspace. Your voice profile, identity and boundaries reach a cloud model only if a workspace owner allows it on the Memory page, and a boundary marked private or local-only never does.",
        "providerAccess": "PostRiff connects social accounts only through your own OAuth grant, requests the minimum scopes for the capability you enable, stores tokens encrypted, and revokes on disconnect.",
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
