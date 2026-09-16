"""Deterministic approved-profile projection and local-only decorative artwork.

No model, network, shell, raw-source lookup, or personality inference exists here.
"""
import copy
import hashlib
import json
import re
from . import profiles

CATEGORIES = [
    ("knowledge", "What I know", ["expertise", "subject", "strengths"]),
    ("goals", "What I care about", ["purpose", "values", "goals"]),
    ("voice", "How I sound", ["voiceTraits", "antiStyle", "tone", "writingExample"]),
    ("audience", "Who I serve", ["audience"]),
    ("working", "How I work", ["workingStyle", "selfDescription"]),
    ("support", "Where support helps", ["support"]),
    ("languages", "Languages & contexts", ["languages", "culturalAudience"]),
    ("boundaries", "Boundaries", ["boundaries"]),
]
SAFE_THEMES = {"clear": "clarity", "clarity": "clarity", "curious": "curiosity", "curiosity": "curiosity", "learning": "learning", "warm": "warmth", "practical": "craft", "craft": "craft", "reflective": "reflection", "calm": "stillness", "structured": "structure"}
ART_KEYS = {"voiceTraits", "purpose", "workingStyle", "support"}


def ensure(s):
    s.setdefault("you", {"identitySentence": "", "artFieldIds": [], "artwork": None, "events": []})


def active(s):
    return next((r for r in s["speaker"]["revisions"] if r["revision"] == s["speaker"]["activeRevision"]), {})


def approved_fields(s):
    return [f for f in active(s).get("profile", {}).get("fields", []) if f.get("decision") == "approved" and f.get("privacy") != "excluded" and f.get("value")]


def art_brief(s):
    ensure(s)
    themes, sources = [], []
    for f in approved_fields(s):
        if f["id"] not in s["you"]["artFieldIds"] or f["privacy"] != "public" or f["key"] not in ART_KEYS:
            continue
        # Only allowlisted abstract words leave this filter, never user text.
        found = [SAFE_THEMES[t] for t in re.findall(r"[a-z]+", f["value"].lower()) if t in SAFE_THEMES]
        if found:
            themes.extend(found)
            sources.append(f["id"])
    themes = list(dict.fromkeys(themes))[:4]
    enough = len(themes) >= 2
    brief = {"status": "local_preview_only" if enough else "insufficient_approved_context", "profileRevisionId": s["speaker"]["activeRevision"], "themes": themes if enough else [], "energy": "quiet momentum", "visualRhythm": "layered but spacious", "motifs": ["open horizon", "soft ripples"], "palette": ["paper cream", "moss green", "muted rust", "ink blue"], "light": "soft morning light", "avoid": ["portraits", "text", "identifiable places", "personality symbols"], "sourceFieldIds": sources if enough else [], "promptVersion": "abstract-allowlist-v1", "provider": None, "model": None, "consent": "not_requested_no_model_call", "remoteRequest": None}
    brief["hash"] = hashlib.sha256(json.dumps(brief, sort_keys=True).encode()).hexdigest()
    return brief


def watercolor(variant=0):
    """Original procedural SVG; fixed decorative geometry, no profile input."""
    colors = [("#97aa86", "#64796c", "#b57350"), ("#8199a0", "#749071", "#b49166"), ("#b9ac79", "#708d83", "#be886f")][variant % 3]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1536" height="512" viewBox="0 0 1536 512"><defs><filter id="wash" x="-25%" y="-50%" width="150%" height="200%"><feTurbulence type="fractalNoise" baseFrequency=".011 .02" numOctaves="3" seed="{17 + variant}" result="noise"/><feDisplacementMap in="SourceGraphic" in2="noise" scale="46"/><feGaussianBlur stdDeviation="9"/></filter></defs><rect width="1536" height="512" fill="#eeeede"/><g filter="url(#wash)"><path d="M550 250Q800 30 1010 180T1600 70L1600 530H530Z" fill="{colors[0]}" opacity=".65"/><path d="M690 530Q830 120 1110 300T1610 165L1600 530Z" fill="{colors[1]}" opacity=".45"/><ellipse cx="1310" cy="165" rx="190" ry="110" fill="{colors[2]}" opacity=".33"/><path d="M680 185Q1050 370 1540 225" fill="none" stroke="#f6f1dd" stroke-width="60" opacity=".58"/></g><path d="M620 420Q850 215 1070 360T1540 250" stroke="#405b50" stroke-width="1.2" fill="none" opacity=".3"/></svg>'''


def projection(s):
    ensure(s)
    fields = approved_fields(s)
    center = {"id": "speaker", "label": s["speaker"]["label"], "revision": s["speaker"]["activeRevision"]}
    groups, nodes, edges = [], [], []
    for category, label, keys in CATEGORIES:
        grouped = [f for f in fields if f["key"] in keys]
        projected = []
        for f in grouped:
            node = {"id": f["id"], "workspace_id": s["workspace"]["id"], "profile_revision_id": center["revision"], "category": category, "label": f["label"], "short_description": f["value"], "evidence_state": f["evidence"], "privacy_state": f["privacy"], "source_ids": f["sourceIds"], "approved_at": f.get("decidedAt"), "status": "approved"}
            nodes.append(node); projected.append(node)
            edges.append({"source_node_id": "speaker", "target_node_id": f["id"], "relationship": "approved profile field", "evidence_state": f["evidence"], "source_ids": f["sourceIds"]})
        groups.append({"id": category, "label": label, "nodes": projected})
    art = s["you"]["artwork"]
    variant = art["variant"] if art else 0
    svg = watercolor(variant)
    return {"center": center, "groups": groups, "nodes": nodes, "edges": edges, "artBrief": art_brief(s), "artworkSvg": svg, "assetHash": hashlib.sha256(svg.encode()).hexdigest(), "artEligibleFields": [{"id": f["id"], "label": f["label"]} for f in fields if f["key"] in ART_KEYS and f["privacy"] == "public"], "storageBytes": len(json.dumps(s, ensure_ascii=False).encode()), "approvedAt": active(s).get("approvedAt"), "needsReview": sum(f["decision"] == "pending" for f in s["profileSetup"]["candidate"]), "unknown": sum(f["decision"] == "unknown" for f in s["profileSetup"]["candidate"])}


def apply(store, s, action, p):
    ensure(s)
    if action == "you_identity":
        s["you"]["identitySentence"] = profiles.text(p.get("value", ""), 240)
    elif action == "you_art_scope":
        allowed = {f["id"] for f in approved_fields(s) if f["privacy"] == "public" and f["key"] in ART_KEYS}
        selected = p.get("fieldIds", [])
        if not isinstance(selected, list) or any(not isinstance(i, str) or i not in allowed for i in selected):
            raise ValueError("Only explicitly selected, approved public fields may shape this local ArtBrief.")
        s["you"]["artFieldIds"] = list(dict.fromkeys(selected))
    elif action == "you_art_refresh":
        prior = s["you"]["artwork"]
        variant = (prior["variant"] + 1) % 3 if prior else 0
        brief = art_brief(s)
        s["you"]["artwork"] = {"variant": variant, "state": "local_procedural", "profileRevisionId": s["speaker"]["activeRevision"], "artBrief": brief, "promptVersion": "procedural-wash-v1", "provider": None, "model": None, "consent": "local_refresh_only", "assetHash": hashlib.sha256(watercolor(variant).encode()).hexdigest(), "selectedAt": profiles.timestamp()}
    elif action == "you_art_remove":
        current = s["you"]["artwork"] or {"variant": 0}
        s["you"]["artwork"] = {**current, "state": "removed", "removedAt": profiles.timestamp()}
    elif action == "you_restore_voice":
        revision = next((r for r in s["speaker"]["revisions"] if r["revision"] == p.get("revision")), None)
        if not revision:
            raise ValueError("Choose an existing approved voice revision.")
        store._voice(s, revision["profile"], "Explicit restore of voice revision " + str(revision["revision"]))
        s["profileSetup"]["candidate"] = copy.deepcopy(revision["profile"].get("fields", []))
        restored_ids = {v["id"] for v in revision["profile"].get("preferences", [])}
        for preference in s["preferences"]:
            if preference["id"] in restored_ids:
                preference["status"] = "remembered"
            elif preference["status"] == "remembered":
                preference["status"] = "undone"
        values = {f["key"]: f["value"] for f in revision["profile"].get("fields", [])}
        for key in ("purpose", "audience", "subject", "speaker"):
            if key in values:
                s["brandHub"][key] = values[key]
        if "layers" in values:
            s["brandHub"]["layers"] = values["layers"].split(", ")
        s["speaker"]["label"] = s["brandHub"]["speaker"] or "The author"
        store._mark_stale(s)
    else:
        raise ValueError("This profile action is not available in the founder alpha.")
    s["you"]["events"].append({"action": action, "at": profiles.timestamp(), "profileRevision": s["speaker"]["activeRevision"]})
