"""Bounded media evidence, independent of any acquisition tool or host machine.

Adapters return observations, never permission. This boundary validates modality,
time ranges, receipts and rights before downstream judgments see the evidence.
No adapter is provisioned implicitly; text listening survives unavailable media.
"""
from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass
from typing import Protocol

from .judgments import subject_hash

STAGES = ("retrieval", "acquisition", "frames", "transcription", "multimodal", "synthesis")
MEDIA_STAGES = ("acquisition", "frames", "transcription", "multimodal")
UTILITIES = {"key_idea", "visual_proof", "demo", "surprise", "explanation", "actionable_step", "quote", "share_trigger", "save_reference", "sequel_seed"}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class MomentCandidate:
    start: float
    end: float
    title: str
    evidence_type: str
    reason: str
    utility_types: tuple
    visual_refs: tuple = ()
    transcript_refs: tuple = ()
    confidence: str = "low"
    standalone: bool = False
    limitations: tuple = ()

    def validate(self, duration, frames, transcript):
        if not number(duration) or not number(self.start) or not number(self.end) or not 0 <= self.start < self.end <= duration:
            raise ValueError("moment outside observed duration")
        if self.evidence_type not in ("visual", "transcript", "mixed") or self.confidence not in ("low", "moderate", "high"):
            raise ValueError("invalid moment evidence/confidence")
        if not self.title or len(self.title) > 160 or not self.reason or len(self.reason) > 800 or not set(self.utility_types) <= UTILITIES:
            raise ValueError("invalid moment description")
        if self.evidence_type in ("visual", "mixed") and (not self.visual_refs or not set(self.visual_refs) <= frames):
            raise ValueError("visual moment requires frame evidence")
        if self.evidence_type in ("transcript", "mixed") and (not self.transcript_refs or not set(self.transcript_refs) <= transcript):
            raise ValueError("spoken moment requires transcript evidence")
        if self.evidence_type == "visual" and self.transcript_refs or self.evidence_type == "transcript" and self.visual_refs:
            raise ValueError("moment modality mismatch")
        return self.confidence != "low"  # abstention is a valid result


@dataclass(frozen=True)
class EvidencePack:
    source_id: str
    content_hash: str
    analyzer: str
    version: str
    analyzed_at: float
    duration: float | None
    transcript_source: str
    transcript: tuple
    frames: tuple
    spoken_highlights: tuple
    visual_highlights: tuple
    moments: tuple[MomentCandidate, ...]
    sampling: str
    provenance: dict
    rights: dict
    source_text: str = ""
    source_metrics: tuple = ()
    features: tuple = ()
    inferences: tuple = ()
    hypotheses: tuple = ()
    limitations: tuple = ()

    def summary(self):
        import json
        from dataclasses import asdict
        if len(json.dumps(asdict(self), allow_nan=False)) > 64000:
            raise ValueError("evidence pack too large")
        if self.transcript_source not in ("native_captions", "whisper", "other_approved", "none"):
            raise ValueError("unsupported transcript source")
        if not self.source_id or not self.content_hash or not self.analyzer or not self.version or not number(self.analyzed_at):
            raise ValueError("missing evidence identity")
        if len(self.frames) > 60 or len(self.transcript) > 120 or len(self.moments) > 30:
            raise ValueError("evidence pack exceeds bounded pass")
        if self.transcript_source == "none" and (self.transcript or self.spoken_highlights):
            raise ValueError("no transcript: spoken evidence forbidden")
        if not self.transcript and self.spoken_highlights:
            raise ValueError("spoken highlights require transcript")
        if not self.frames and self.visual_highlights:
            raise ValueError("visual highlights require frames")
        if self.frames or self.transcript:
            if not number(self.duration) or self.duration <= 0 or self.sampling not in ("sparse", "uniform", "scene", "hybrid", "full", "none"):
                raise ValueError("invalid duration or sampling")
        ids = []
        for kind, rows in (("frame", self.frames), ("transcript", self.transcript)):
            found = set()
            for row in rows:
                if not isinstance(row, dict) or not row.get("id") or row["id"] in found:
                    raise ValueError("missing or duplicate evidence reference")
                stamp = row.get("time")
                if not number(self.duration) or not number(stamp) or not 0 <= stamp <= self.duration:
                    raise ValueError("evidence timestamp outside duration")
                found.add(row["id"])
            ids.append(found)
        for highlights, refs in ((self.visual_highlights, ids[0]), (self.spoken_highlights, ids[1])):
            for row in highlights:
                if not isinstance(row, dict) or not row.get("refs") or not set(row["refs"]) <= refs:
                    raise ValueError("highlight requires observed evidence references")
        limitations = list(self.limitations)
        if not self.transcript:
            limitations.append("Transcript/audio unavailable; no spoken claims.")
        if not self.frames:
            limitations.append("Frames unavailable; no visual claims.")
        elif self.sampling != "full":
            limitations.append("Sampled frames only; intervening visuals were not observed.")
        moments = [asdict(m) for m in self.moments if m.validate(self.duration, *ids)]
        return {"sourceId": self.source_id, "contentHash": self.content_hash, "analyzer": self.analyzer, "version": self.version,
                "analyzedAt": self.analyzed_at, "duration": self.duration, "coverage": "partial" if self.frames or self.transcript else "text_only",
                "videoObserved": bool(self.frames or self.transcript), "transcriptSource": self.transcript_source,
                "transcriptCount": len(self.transcript), "frameCount": len(self.frames), "sampling": self.sampling,
                "visualHighlights": list(self.visual_highlights), "spokenHighlights": list(self.spoken_highlights), "moments": moments,
                "features": list(self.features), "inferences": list(self.inferences), "hypotheses": list(self.hypotheses),
                "provenance": self.provenance, "rights": self.rights, "limitations": list(dict.fromkeys(limitations)),
                "reuse": "authorized_repurpose" if self.rights.get("repurpose") is True else "pattern_learning_only"}


class MediaEnrichmentAdapter(Protocol):
    def supports(self, source: dict) -> bool: ...
    def capabilities(self) -> dict: ...
    def analyze(self, request: dict) -> tuple[EvidencePack, dict]: ...


def enrich(source, *, workspace_id, adapter, ledger, cache, now, deadline, relevant, useful, enabled=False, clock=time.monotonic):
    """Caller owns an exclusive workspace reservation before invoking this routine.

    Limits are stage-specific prepaid *work units*, not invented dollar costs.
    Unknown provider costs remain unknown. Failures are suppressed for one day.
    """
    skipped = lambda reason: {"status": "skipped", "reason": reason, "evidence": None}
    if not enabled or adapter is None:
        return skipped("adapter_unavailable")
    if not relevant or not useful or source.get("ageDays") is None or source["ageDays"] > 7:
        return skipped("not_actionable_or_stale")
    rights = source.get("rights") or {}
    if not all(rights.get(k) is True for k in ("access", "analyze", "storeEvidence")) or not number(rights.get("retainUntil")) or rights["retainUntil"] <= now:
        return skipped("rights_unknown")
    caps = adapter.capabilities()
    if caps.get("requiresDownload") and rights.get("download") is not True:
        return skipped("download_not_permitted")
    if not adapter.supports(source) or caps.get("enforcesDeadline") is not True:
        return skipped("unsupported_or_unbounded_adapter")
    duration = source.get("duration")
    if not number(duration) or not 0 < duration <= 600:
        return skipped("duration_unknown_or_too_long")
    if deadline - clock() < 1:
        return skipped("deadline")
    key = subject_hash(workspace_id, source.get("contentHash"), caps.get("id"), caps.get("version"), rights)
    # Rights expiry applies to success and failure cache; no cross-workspace reuse.
    cache[:] = [e for e in cache if e["expiresAt"] > now][-23:]
    hit = next((e for e in cache if e["key"] == key), None)
    if hit:
        return {**copy.deepcopy(hit["result"]), "cached": True}
    day = int(now // 86400)
    if ledger.get("day") != day:
        ledger.clear()
        ledger.update(day=day, used={})
    stages = tuple(caps.get("stages") or ())
    if not stages or any(s not in MEDIA_STAGES for s in stages):
        return skipped("invalid_adapter_budget")
    if ledger.get("mediaRun", 0) >= 2 or any(ledger["used"].get(s, 0) >= 4 for s in stages):
        return skipped("budget_exhausted")
    for stage in stages:
        ledger["used"][stage] = ledger["used"].get(stage, 0) + 1
    ledger["mediaRun"] = ledger.get("mediaRun", 0) + 1
    try:
        pack, receipt = adapter.analyze({"source": source, "workspaceId": workspace_id, "deadline": deadline,
                                        "maxFrames": 60, "maxDuration": 600, "maxRequests": 1, "retries": 0})
        if pack.source_id != source["id"] or pack.content_hash != source["contentHash"] or pack.rights != rights:
            raise ValueError("evidence identity or rights mismatch")
        if not isinstance(receipt, dict) or receipt.get("requests") != 1 or receipt.get("costSource") not in ("provider", "unknown"):
            raise ValueError("missing usage receipt")
        result = {"status": "ok", "evidence": pack.summary(), "usage": receipt}
    except Exception as error:  # adapter failure never removes a text signal; never persist raw provider errors
        result = {"status": "unavailable", "reason": type(error).__name__, "evidence": None, "usage": {"costSource": "unknown"}}
    cache.append({"key": key, "expiresAt": min(now + 86400, rights["retainUntil"]), "result": copy.deepcopy(result)})
    return result


class SuppliedWatchAdapter:
    """Approved local artifacts only; no filesystem lookup, commands or download.

    A caller supplies already acquired Watch-It evidence as EvidencePack objects.
    This adapter never claims Watch-It ran, and is never installed automatically.
    Native captions, Whisper, frames-only and timestamp validation share the same
    strict boundary as any future hosted adapter.
    """
    def __init__(self, packs):
        self.packs = dict(packs)

    def capabilities(self):
        return {"id": "supplied_watch_artifact", "version": "1", "localOnly": True, "requiresDownload": False,
                "enforcesDeadline": True, "stages": ["multimodal"], "acquisition": "not_supported"}

    def supports(self, source):
        return source.get("mediaType") == "video" and source.get("contentHash") in self.packs

    def analyze(self, request):
        if request["deadline"] <= time.monotonic():
            raise TimeoutError("evidence import deadline")
        pack = self.packs[request["source"]["contentHash"]]
        pack.summary()
        return pack, {"requests": 1, "costSource": "unknown", "execution": "supplied_artifact_import", "providerCalls": 0}
