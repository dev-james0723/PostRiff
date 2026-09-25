"""Layered memory for the Agent Runtime (spec §14), read through the product's existing stores — no second memory.

Layers: 1 account identity and locale · 2 workspace facts · 3 Brand Brain · 4 voice profile · 5 learned preferences ·
6 campaign/task state (7 conversation history and 8 working memory are the Manager's input and run context; 9 derived
observations come from the site agent's rules, labelled as derived).

Provenance, as the existing records permit:
- Brand Brain and voice fields are explicit: a person entered or approved them (`source: brand_brain | voice_profile`).
- A learned preference records how it was found (`origin`: said in chat = explicit; learned from edits, a model or
  performance = inferred), whether a person accepted it (`acceptedBy`, only owners can), its evidence state and
  support, and whether it replaced another one (`supersedes`). `confidence` is derived from those, never invented.
- Pending proposals are listed as not in effect.

Egress: this runtime is a cloud processor. Memory bodies reach it only when the owner allowed cloud memory (the same
switch the writing pipeline honours, `memory.projection(state, "cloud")`), and private or unlabelled boundaries are
withheld even then. Without that consent the layer says what exists and that its content is withheld.

Voice and text read this same function; nothing is stored per language or per modality.
"""
from __future__ import annotations

from .. import campaigns, memory

LAYERS = ("identity", "workspace", "brand", "voice", "preferences", "campaigns", "task")
EXPLICIT_ORIGINS = ("chat", "legacy")


def cloud_allowed(state: dict) -> bool:
    return memory.egress(state).get("cloud") is True


def _confidence(item: dict) -> str:
    if item.get("status") != "active":
        return "not_in_effect"
    if item.get("source") in EXPLICIT_ORIGINS or item.get("evidenceState") == "user_confirmed":
        return "high"
    return "medium"


def preference_view(item: dict, *, with_statement: bool) -> dict:
    origin = item.get("source")
    view = {"id": item.get("id"), "rule": item.get("ruleKey"), "polarity": item.get("polarity"), "scope": item.get("scope") or {},
            "status": item.get("status"), "origin": origin, "kind": "explicit" if origin in EXPLICIT_ORIGINS else "inferred",
            "acceptedBy": "owner" if item.get("confirmedBy") else None, "evidenceState": item.get("evidenceState"),
            "evidence": item.get("evidenceSummary"), "since": item.get("since"), "supersedes": item.get("replaces") or item.get("proposalId") if item.get("replaces") else None,
            "retiredReason": item.get("retiredReason"), "confidence": _confidence(item)}
    if with_statement:
        view["statement"] = item.get("statement")
    return view


def read(state: dict, *, member=None, cur=None, workspace_id=None, zone=None, locale=None, task=None, layers=None) -> dict:
    from postriff_alpha import learning
    wanted = [layer for layer in (layers or LAYERS) if layer in LAYERS]
    shared = cloud_allowed(state)
    out = {"cloudMemory": shared, "layers": {}}
    if "identity" in wanted:
        out["layers"]["identity"] = {"source": "account", "kind": "explicit", "role": getattr(member, "role", None), "timeZone": zone, "locale": locale}
    if "workspace" in wanted:
        p2 = state.get("phase2") or {}
        channels = [c for c in p2.get("channels", []) if isinstance(c, dict) and not c.get("revoked")]
        out["layers"]["workspace"] = {"source": "application", "kind": "stored", "name": (state.get("workspace") or {}).get("name"),
                                      "platforms": sorted({c.get("platform") for c in channels if c.get("platform")}),
                                      "drafts": sum(1 for v in state.get("variants", []) if isinstance(v, dict) and not v.get("rejected"))}
    projection = memory.projection(state, "cloud") if shared else {"files": [], "withheldBoundaries": 0}
    files = {f.get("name"): f for f in projection.get("files") or [] if isinstance(f, dict)}
    if "brand" in wanted:
        brand = {"source": "brand_brain", "kind": "explicit", "shared": shared}
        if shared:
            brand["files"] = {name: (f.get("body") or "")[:3000] for name, f in files.items() if name in ("IDENTITY.md", "BOUNDARIES.md", "AUDIENCE.md")}
            brand["withheldBoundaries"] = projection.get("withheldBoundaries", 0)
        else:
            brand["withheld"] = "The owner has not allowed cloud memory, so Brand Brain content is not sent to the agent model."
        out["layers"]["brand"] = brand
    if "voice" in wanted:
        profile = memory.active_profile(state) or {}
        voice = {"source": "voice_profile", "kind": "explicit" if profile else None, "approvedRevision": profile.get("revision"), "shared": shared}
        if shared and "VOICE.md" in files:
            voice["profile"] = (files["VOICE.md"].get("body") or "")[:3000]
        elif not shared:
            voice["withheld"] = "Voice profile content needs the owner's cloud memory setting."
        out["layers"]["voice"] = voice
    if "preferences" in wanted:
        items = learning.all_items(state)
        views = [preference_view(item, with_statement=shared) for item in items][:40]
        pending = []
        if cur is not None and workspace_id:
            from ..learning_service import pending_proposals
            pending = [{"id": p.get("id"), "kind": "explicit" if p.get("source") == "chat" else "inferred", "origin": p.get("source"), "status": "pending",
                        "confidence": "not_in_effect", **({"statement": p.get("statement")} if shared else {})} for p in pending_proposals(cur, workspace_id)][:10]
        out["layers"]["preferences"] = {"source": "learned_preferences", "items": views, "pending": pending, "shared": shared,
                                        "counts": {"active": sum(1 for v in views if v["status"] == "active"), "explicit": sum(1 for v in views if v["kind"] == "explicit"),
                                                   "inferred": sum(1 for v in views if v["kind"] == "inferred")}}
    if "campaigns" in wanted:
        root = campaigns._root(state)
        out["layers"]["campaigns"] = {"source": "application", "kind": "stored", "items": [
            {"campaignId": c.get("id"), "goal": c.get("goal"), "status": c.get("status"), "linkedItems": len(c.get("items") or [])}
            for c in root["campaigns"] if c.get("status") != "cancelled"][:10]}
    if "task" in wanted:
        out["layers"]["task"] = {"source": "task_state", "kind": "stored", "task": task.view() if task is not None else None}
    return out
