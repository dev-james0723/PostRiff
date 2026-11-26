"""Workspace-only fit/context. No model, provider, or durable memory mutations."""
from __future__ import annotations

import re

from ... import memory
from .contracts import digest

DIMENSIONS = ("trend_relevance", "audience_relevance", "brand_fit", "timing_opportunity",
              "originality_opportunity", "risk", "confidence")


def campaign_context(campaign):
    return {k: campaign.get(k) for k in ("id", "version", "goal", "audience", "facts")}


def unchanged_handoff(campaign, state):
    """A server-bound copy of an accepted goal adds no new fit context.

    Any brief edit, source withdrawal/text/lineage edit removes this exception.
    No client-supplied marker is accepted by the campaign commands.
    """
    marker = campaign.get("trendHandoff") or {}
    source = next((s for s in state.get("sources", []) if s.get("id") == marker.get("source_id") and s.get("active")), None)
    return bool(source and marker.get("campaign_digest") == digest(campaign_context(campaign))
                and marker.get("source_digest") == digest({"text": source.get("text"), "lineage": (source.get("origin") or {}).get("trendLineage")}))


def context_revision(state):
    """Hard context only. Adding this opportunity's source/draft cannot invalidate itself."""
    hub = state.get("brandHub") or {}
    speaker = state.get("speaker") or {}
    campaigns = ((state.get("raffi") or {}).get("campaignPlanning") or {}).get("campaigns", [])
    channels = (state.get("phase2") or {}).get("channels", [])
    return digest({"brand": hub, "voice": speaker.get("activeRevision"),
                   "learning": (state.get("learning") or {}).get("revision"),
                   "overlays": ((state.get("coworker") or {}).get("overlays") or {}).get("revision"),
                   "campaigns": [campaign_context(c) for c in campaigns if not unchanged_handoff(c, state)],
                   "channels": [{k: c.get(k) for k in ("id", "platform", "language", "revoked", "capabilityVersion")} for c in channels]})


def terms(value):
    """Words of three or more letters, plus every pair of neighbouring Chinese characters.

    Chinese has no spaces, so a whole phrase used to count as one term and two phrases about the same thing never met."""
    text = str(value).lower()
    found = set(re.findall(r"[^\W_一-鿿]{3,}", text))
    for run in re.findall(r"[一-鿿]{2,}", text):
        found.update(run[i:i + 2] for i in range(len(run) - 1))
    return found


def evaluate(trend, state):
    """Cheap evidence-labelled screening; unknown semantic dimensions stay unknown."""
    topic = terms(trend.get("canonical_topic", ""))
    brand = state.get("brandHub") or {}
    dimensions = {name: {"assessment": "unknown", "reason": "Not evaluated", "evidence_refs": []}
                  for name in DIMENSIONS}
    for name, field in (("trend_relevance", "subject"), ("audience_relevance", "audience")):
        overlap = topic & terms(brand.get(field, ""))
        if overlap:
            dimensions[name] = {"assessment": "unknown", "reason": "Lexical overlap only; semantic fit is unqualified",
                                "evidence_refs": ["brandHub." + field]}
    # The approved voice profile's topics and the owner's boundaries are evidence too. Both stay lexical: an
    # overlap names where to look, it never qualifies fit, and a boundary's own wording is never repeated here.
    revision = memory.active_profile(state) or {}
    profile = revision.get("profile") or {}
    if not revision.get("stale") and profile.get("status") != "stale":
        approved = terms(" ".join(t for t in profile.get("topics") or [] if isinstance(t, str)))
        if topic & approved:
            dimensions["brand_fit"] = {"assessment": "unknown", "reason": "Lexical overlap with the approved profile's topics; semantic fit is unqualified",
                                       "evidence_refs": ["speaker.activeRevision.topics"]}
    limits = terms(" ".join(str(f.get("value", "")) for f in memory.boundary_fields(state)))
    if topic & limits:
        dimensions["risk"] = {"assessment": "concern", "reason": "Topic terms overlap a content boundary the owner set; review before using this trend",
                              "evidence_refs": ["BOUNDARIES.md"]}
    recent = " ".join(v.get("text", "") for v in state.get("variants", [])[-30:])
    if topic and topic <= terms(recent):
        dimensions["originality_opportunity"] = {"assessment": "concern", "reason": "Topic terms already occur in recent drafts",
                                                 "evidence_refs": [v["id"] for v in state.get("variants", [])[-30:] if v.get("id")]}
    return {"dimensions": dimensions, "context_digest": context_revision(state),
            "method_version": "workspace-screening.v2", "qualified": False,
            "limitations": ["Lexical screening does not qualify brand fit, originality, timing, or cultural meaning."]}
