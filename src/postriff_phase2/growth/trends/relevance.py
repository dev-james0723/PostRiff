"""Workspace-only fit/context. No model, provider, or durable memory mutations."""
from __future__ import annotations

import re

from .contracts import digest

DIMENSIONS = ("trend_relevance", "audience_relevance", "brand_fit", "timing_opportunity",
              "originality_opportunity", "risk", "confidence")


def context_revision(state):
    """Hard context only. Adding this opportunity's source/draft cannot invalidate itself."""
    hub = state.get("brandHub") or {}
    speaker = state.get("speaker") or {}
    campaigns = ((state.get("raffi") or {}).get("campaignPlanning") or {}).get("campaigns", [])
    channels = (state.get("phase2") or {}).get("channels", [])
    return digest({"brand": hub, "voice": speaker.get("activeRevision"),
                   "learning": (state.get("learning") or {}).get("revision"),
                   "overlays": ((state.get("coworker") or {}).get("overlays") or {}).get("revision"),
                   "campaigns": [{k: c.get(k) for k in ("id", "version", "goal", "audience", "facts")} for c in campaigns],
                   "channels": [{k: c.get(k) for k in ("id", "platform", "language", "revoked", "capabilityVersion")} for c in channels]})


def evaluate(trend, state):
    """Cheap evidence-labelled screening; unknown semantic dimensions stay unknown."""
    terms = lambda value: set(re.findall(r"[^\W_]{3,}|[一-鿿]{2}", str(value).lower()))
    topic = terms(trend.get("canonical_topic", ""))
    brand = state.get("brandHub") or {}
    dimensions = {name: {"assessment": "unknown", "reason": "Not evaluated", "evidence_refs": []}
                  for name in DIMENSIONS}
    for name, field in (("trend_relevance", "subject"), ("audience_relevance", "audience")):
        overlap = topic & terms(brand.get(field, ""))
        if overlap:
            dimensions[name] = {"assessment": "unknown", "reason": "Lexical overlap only; semantic fit is unqualified",
                                "evidence_refs": ["brandHub." + field]}
    recent = " ".join(v.get("text", "") for v in state.get("variants", [])[-30:])
    if topic and topic <= terms(recent):
        dimensions["originality_opportunity"] = {"assessment": "concern", "reason": "Topic terms already occur in recent drafts",
                                                 "evidence_refs": [v["id"] for v in state.get("variants", [])[-30:] if v.get("id")]}
    return {"dimensions": dimensions, "context_digest": context_revision(state),
            "method_version": "workspace-screening.v1", "qualified": False,
            "limitations": ["Lexical screening does not qualify brand fit, originality, timing, or cultural meaning."]}
