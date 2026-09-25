"""Adaptive user overlays (adaptive coworker spec §9; architecture lock A1).

Global skills never change for one workspace. What a workspace teaches Rafii is kept as scoped, evidence-backed
overlay items in three separate memory types:
- voice: how the person tends to write (approved voice revision, learned writing preferences, explicit voice notes);
- brand: who the brand is (Brand Brain, terminology, claims, explicit brand notes);
- strategy: what appears to work (performance hypotheses; never identity, never a writing rule by itself).

Learned preferences stay where preference learning keeps them (`state.learning`); this module adds the overlay
metadata the spec asks for (evidence ids, counter-evidence, confidence, last support, expiry, replacement) and the
explicit notes a person writes, under `state.coworker.overlays`. Nothing here rewrites a skill file.
"""
from __future__ import annotations

import hashlib
import json
import time

MEMORY_TYPES = ("voice", "brand")
# Inferred items lose confidence without new support and expire; explicit items never decay.
INFERRED_HALF_LIFE_DAYS = 90
INFERRED_EXPIRY_DAYS = 180
EXPLICIT_SOURCES = ("chat", "settings", "explicit", "legacy")
EVIDENCE_CONFIDENCE = {"user_confirmed": 0.9, "observed_in_approved_example": 0.7, "observed_in_edits": 0.6}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def ensure(state):
    coworker = state.setdefault("coworker", {})
    overlays = coworker.setdefault("overlays", {})
    overlays.setdefault("revision", 0)
    overlays.setdefault("items", [])
    overlays.setdefault("meta", {})
    overlays.setdefault("history", [])
    return overlays


def _view(state):
    return ((state.get("coworker") or {}).get("overlays") or {"revision": 0, "items": [], "meta": {}, "history": []})


def revisions(state):
    speaker = state.get("speaker") or {}
    learning = state.get("learning") or {}
    brand = {k: v for k, v in (state.get("brandHub") or {}).items() if k != "id"}
    return {
        "voiceRevision": speaker.get("activeRevision"),
        "brandRevision": "bh_" + _digest(brand)[:12] if any(brand.values()) else None,
        "personalizationRevision": f"{learning.get('revision', 0)}.{_view(state).get('revision', 0)}",
    }


def _in_scope(item_scope, scope):
    item_scope = item_scope or {}
    platform = item_scope.get("platform")
    if platform and scope.get("platforms") and platform not in scope["platforms"]:
        return False
    if platform and not scope.get("platforms"):
        # A platform-scoped item applies only when that platform is in the task.
        return False
    language = item_scope.get("language")
    if language and scope.get("locales"):
        if not any(str(loc).lower().startswith(str(language).lower().split("-")[0]) for loc in scope["locales"]):
            return False
    content_type = item_scope.get("contentTypeId") or item_scope.get("contentType")
    if content_type and scope.get("contentType") and content_type != scope["contentType"]:
        return False
    audience = item_scope.get("audience")
    if audience and scope.get("audience") and audience != scope["audience"]:
        return False
    return True


def confidence(meta, origin, evidence_state=None, now=None):
    """0–1. Explicit items are 1.0. Inferred: support vs counter-evidence, decayed from the last support."""
    if origin == "explicit":
        return 1.0
    now = now or time.time()
    base = EVIDENCE_CONFIDENCE.get(evidence_state or "", 0.5)
    support = len(meta.get("evidenceIds") or [])
    counter = len(meta.get("counterEvidenceIds") or [])
    if support or counter:
        base = min(0.95, 0.4 + 0.1 * support) * (1 - min(0.8, counter / max(1, support + counter)))
    last = meta.get("lastSupportedAt")
    if isinstance(last, (int, float)) and last > 0:
        days = max(0.0, (now - last) / 86400)
        base *= 0.5 ** (days / INFERRED_HALF_LIFE_DAYS)
    return round(base, 3)


def learned_items(state, now=None):
    """Learned preferences as overlay items, with their overlay metadata."""
    from postriff_alpha import learning
    now = now or time.time()
    meta = _view(state).get("meta") or {}
    items = []
    for item in learning.all_items(state) if hasattr(learning, "all_items") else (state.get("learning") or {}).get("active", []):
        if item.get("status") not in (None, "active", "paused"):
            continue
        origin = "explicit" if item.get("source") in EXPLICIT_SOURCES else "inferred"
        extra = meta.get(item.get("id")) or {}
        expires = extra.get("expiresAt")
        if origin == "inferred" and expires is None and isinstance(item.get("since"), (int, float)):
            expires = item["since"] + INFERRED_EXPIRY_DAYS * 86400
        status = item.get("status") or "active"
        if extra.get("disabled"):
            status = "disabled"
        elif origin == "inferred" and isinstance(expires, (int, float)) and expires < now and not extra.get("lastSupportedAt", 0) > now - INFERRED_EXPIRY_DAYS * 86400:
            status = "expired"
        items.append({
            "id": item.get("id"), "memoryType": "voice" if item.get("type") == "writing_preference" else "brand",
            "origin": origin, "statement": item.get("statement"), "scope": item.get("scope") or {},
            "status": status, "source": item.get("source"), "evidenceState": item.get("evidenceState"),
            "evidenceIds": extra.get("evidenceIds") or [], "counterEvidenceIds": extra.get("counterEvidenceIds") or [],
            "confidence": confidence(extra, origin, item.get("evidenceState"), now), "lastSupportedAt": extra.get("lastSupportedAt") or item.get("since"),
            "expiresAt": expires, "replaces": extra.get("replaces") or item.get("replaces"), "since": item.get("since"), "kind": "learned",
        })
    return items


def explicit_items(state):
    """Notes a person wrote (voice or brand). Explicit: confidence 1.0, no decay; disabled or retired ones stay listed."""
    items = []
    for item in _view(state).get("items") or []:
        items.append({**item, "kind": "note", "origin": "explicit", "confidence": 1.0, "scope": item.get("scope") or {},
                      "status": item.get("status") or "active", "memoryType": item.get("memoryType") if item.get("memoryType") in MEMORY_TYPES else "voice"})
    return items


def all_items(state, now=None):
    return explicit_items(state) + learned_items(state, now)


def effective_view(state, scope, cloud_allowed=True, now=None):
    """The overlay items that apply to this task, highest precedence first, and the data block for a prompt."""
    active = [i for i in all_items(state, now) if i["status"] == "active" and _in_scope(i.get("scope"), scope)]
    # Explicit outranks inferred; within each, higher confidence first. Two items with the same rule key and scope
    # keep only the explicit one.
    active.sort(key=lambda i: (0 if i["origin"] == "explicit" else 1, -i["confidence"]))
    seen, chosen = set(), []
    for item in active:
        key = (item.get("ruleKey") or item.get("statement"), json.dumps(item.get("scope") or {}, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        chosen.append(item)
    if not cloud_allowed:
        return {"text": "WORKSPACE PREFERENCES: withheld (this workspace has not allowed its memory to reach a cloud model).",
                "items": [], "revisions": revisions(state)}
    lines = []
    for item in chosen[:24]:
        where = ", ".join(v for v in ((item.get("scope") or {}).get("platform"), (item.get("scope") or {}).get("language"),
                                      (item.get("scope") or {}).get("contentTypeId")) if v) or "all platforms"
        label = "explicit" if item["origin"] == "explicit" else f"inferred, confidence {item['confidence']:.2f}"
        lines.append(f"- [{item['memoryType']} · {label} · {where}] {item.get('statement') or ''}".rstrip())
    text = ""
    if lines:
        text = ("WORKSPACE PREFERENCES (data from this workspace only; explicit ones outrank inferred ones; each applies only "
                "within its scope; they never change approval, publishing or safety rules):\n" + "\n".join(lines))
    return {"text": text, "items": chosen, "revisions": revisions(state)}
