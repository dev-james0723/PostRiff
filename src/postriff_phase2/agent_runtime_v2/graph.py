"""The relationship layer (spec §17), derived from the product's normalized records — no graph store.

Nodes are the records the workspace already holds (campaign, source, draft, draft revision, asset, review, scheduled
job, published post, automation, account, member, agent run). Edges are computed from their fields:

- derived_from      draft → source (variant.sourceIds), draft → draft (provenance.derivedFrom, a rework)
- belongs_to_campaign draft/post → campaign (campaign.items, linked by a person) and draft → campaign through the
                    automation that wrote it (variant.automation.taskId → recurring task → campaign)
- created_by_automation draft → automation (variant.automation)
- reviewed_as / scheduled_as / published_as  draft → review / job (manifest.variantId; published only when verified)
- uses_asset        job → asset (manifest.media), asset → asset (lineage.parentAssetId: an edit or variant)
- supersedes        draft → its proposed update (waiting to be accepted)

Every edge names the record field it came from (`via`), so an answer can show why two things are related. Nothing is
inferred from similar wording, timing or authorship.
"""
from __future__ import annotations

from .. import campaigns

KINDS = ("draft", "campaign", "job", "review", "asset", "automation", "source")


def _phase2(state):
    return state.get("phase2") or {}


def _campaign_of_task(root, task_id):
    task = next((t for t in root.get("recurringTasks") or [] if t.get("id") == task_id), None)
    return (task or {}).get("campaignId")


def _edge(kind, target_type, target_id, via, **extra):
    return {"edge": kind, "type": target_type, "id": target_id, "via": via, **{k: v for k, v in extra.items() if v is not None}}


def neighbours(state: dict, kind: str, ident: str) -> dict:
    state = dict(state)
    root = (state.get("raffi") or {}).get("campaignPlanning") or {"campaigns": [], "recurringTasks": [], "occurrences": []}
    p2 = _phase2(state)
    variants = [v for v in state.get("variants", []) if isinstance(v, dict)]
    jobs = [j for j in p2.get("jobs", []) if isinstance(j, dict)]
    reviews = [r for r in p2.get("reviews", []) if isinstance(r, dict)]
    assets = [a for a in p2.get("assets", []) if isinstance(a, dict)]
    edges: list[dict] = []
    found = False

    if kind == "draft":
        variant = next((v for v in variants if v.get("id") == ident), None)
        if variant is not None:
            found = True
            for source_id in variant.get("sourceIds") or []:
                edges.append(_edge("derived_from", "source", source_id, "draft.sourceIds"))
            parent = (variant.get("provenance") or {}).get("derivedFrom")
            if parent:
                edges.append(_edge("derived_from", "draft", parent, "draft.provenance.derivedFrom"))
            for child in variants:
                if (child.get("provenance") or {}).get("derivedFrom") == ident:
                    edges.append(_edge("adapted_as", "draft", child["id"], "draft.provenance.derivedFrom", platform=child.get("platform")))
            for linked in campaigns.linked_campaigns({"raffi": {"campaignPlanning": root}}, "draft", ident) if hasattr(campaigns, "linked_campaigns") else []:
                edges.append(_edge("belongs_to_campaign", "campaign", linked["campaign"]["id"], "campaign.items (linked by a person)",
                                   title=(linked["campaign"].get("goal") or "")[:80], addedAt=linked["item"].get("addedAt")))
            task_id = (variant.get("automation") or {}).get("taskId")
            if task_id:
                edges.append(_edge("created_by_automation", "automation", task_id, "draft.automation.taskId"))
                campaign_id = _campaign_of_task(root, task_id)
                if campaign_id:
                    edges.append(_edge("belongs_to_campaign", "campaign", campaign_id, "automation.campaignId (the campaign's automation wrote it)"))
            for review in reviews:
                if (review.get("manifest") or {}).get("variantId") == ident:
                    edges.append(_edge("reviewed_as", "review", review.get("id"), "review.manifest.variantId", status=review.get("status")))
            for job in jobs:
                if (job.get("manifest") or {}).get("variantId") == ident:
                    edge = "published_as" if job.get("state") == "verified" else "scheduled_as"
                    edges.append(_edge(edge, "job", job.get("id"), "job.manifest.variantId", state=job.get("state")))
            if variant.get("proposedUpdate"):
                edges.append(_edge("has_proposed_update", "draft_revision", f"{ident}:proposed", "draft.proposedUpdate",
                                   runId=(variant.get("proposedUpdate") or {}).get("runId")))

    elif kind == "campaign":
        campaign = next((c for c in root.get("campaigns") or [] if c.get("id") == ident), None)
        if campaign is not None:
            found = True
            task_ids = []
            for task in root.get("recurringTasks") or []:
                if task.get("campaignId") == ident:
                    task_ids.append(task.get("id"))
                    edges.append(_edge("has_automation", "automation", task.get("id"), "automation.campaignId", status=task.get("status"), title=task.get("name")))
            for item in campaign.get("items") or []:
                if item.get("kind") == "draft":
                    edges.append(_edge("contains", "draft", item.get("variantId"), "campaign.items (linked by a person)", addedAt=item.get("addedAt")))
                elif item.get("kind") == "post":
                    edges.append(_edge("contains", "job", item.get("jobId"), "campaign.items (linked by a person)", addedAt=item.get("addedAt")))
            for variant in variants:
                if (variant.get("automation") or {}).get("taskId") in task_ids:
                    edges.append(_edge("contains", "draft", variant["id"], "draft.automation.taskId → automation.campaignId", platform=variant.get("platform")))

    elif kind in ("job", "review"):
        pool = jobs if kind == "job" else reviews
        item = next((i for i in pool if i.get("id") == ident), None)
        if item is not None:
            found = True
            manifest = item.get("manifest") or {}
            if manifest.get("variantId"):
                edges.append(_edge("made_from", "draft", manifest["variantId"], f"{kind}.manifest.variantId"))
            if manifest.get("channelId"):
                edges.append(_edge("posts_to", "connection", manifest["channelId"], f"{kind}.manifest.channelId", account=manifest.get("account")))
            for media in manifest.get("media") or []:
                edges.append(_edge("uses_asset", "asset", media.get("id"), f"{kind}.manifest.media"))
            if kind == "job":
                for linked in campaigns.linked_campaigns({"raffi": {"campaignPlanning": root}}, "post", ident) if hasattr(campaigns, "linked_campaigns") else []:
                    edges.append(_edge("belongs_to_campaign", "campaign", linked["campaign"]["id"], "campaign.items (linked by a person)"))
                if item.get("automation"):
                    edges.append(_edge("created_by_automation", "automation", (item.get("automation") or {}).get("taskId"), "job.automation"))

    elif kind == "asset":
        asset = next((a for a in assets if a.get("id") == ident and not a.get("deleted")), None)
        if asset is not None:
            found = True
            lineage = asset.get("lineage") or {}
            if lineage.get("parentAssetId"):
                edges.append(_edge("derived_from", "asset", lineage["parentAssetId"], "asset.lineage.parentAssetId", operation=lineage.get("operation")))
            for source in lineage.get("sourceAssetIds") or []:
                if source != lineage.get("parentAssetId"):
                    edges.append(_edge("informed_by", "asset", source, "asset.lineage.sourceAssetIds"))
            for child in assets:
                if (child.get("lineage") or {}).get("parentAssetId") == ident and not child.get("deleted"):
                    edges.append(_edge("edited_as", "asset", child["id"], "asset.lineage.parentAssetId", operation=(child.get("lineage") or {}).get("operation")))
            for job in jobs:
                if any(m.get("id") == ident for m in (job.get("manifest") or {}).get("media") or []):
                    edges.append(_edge("used_by", "job", job.get("id"), "job.manifest.media", state=job.get("state")))

    elif kind == "automation":
        task = next((t for t in root.get("recurringTasks") or [] if t.get("id") == ident), None)
        if task is not None:
            found = True
            if task.get("campaignId"):
                edges.append(_edge("belongs_to_campaign", "campaign", task["campaignId"], "automation.campaignId"))
            for variant in variants:
                if (variant.get("automation") or {}).get("taskId") == ident:
                    edges.append(_edge("wrote", "draft", variant["id"], "draft.automation.taskId", platform=variant.get("platform")))

    elif kind == "source":
        source = next((s for s in state.get("sources", []) if isinstance(s, dict) and s.get("id") == ident), None)
        if source is not None:
            found = True
            for variant in variants:
                if ident in (variant.get("sourceIds") or []):
                    edges.append(_edge("used_by", "draft", variant["id"], "draft.sourceIds", platform=variant.get("platform")))

    return {"node": {"type": kind, "id": ident}, "found": found, "edges": edges[:60], "edgeCount": len(edges),
            "note": "Edges come from stored fields (see `via`); nothing is inferred from wording, timing or authorship."}
