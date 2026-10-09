"""Version comparison and version stacks (engineering spec §9; UI spec §2 "Version comparison"; PRD R10, D3; T06).

Each side keeps its own identity (assetId/versionId/sha256), its approval status (Ideas source review and the purpose
policy) and its usage. The comparison is chosen by format and says so honestly:

    text/metadata  line diff over current segments (with their locators), falling back to extracted text offsets
    images         side-by-side references with dimensions (Rafii does not judge which is better)
    audio/video    durations and timed segment references
    anything else  "Comparison of these two formats is not supported", plus the metadata diff

Nothing here writes; a comparison never implies the newer version was approved.
"""
from __future__ import annotations

import difflib
import uuid

from postriff_alpha.domain import AlphaError

from .. import source_policy
from . import contracts as c
from . import policy, versions

TEXT_KINDS = ("document", "file")
TIME_KINDS = ("audio", "video")
MAX_SEGMENTS = 2000
MAX_LINES = 4000
MAX_CHARS = 200_000
MAX_LINE = 2000
MAX_HUNKS = 300
MAX_HUNK_LINES = 50
MEDIA_SEGMENTS = 50
MAX_AFFECTED = 100
UNSUPPORTED = "Comparison of these two formats is not supported. Their details are compared below."
APPROVAL_LABELS = {
    "approved_for_public_use": "Approved for public use",
    "approved_for_drafts": "Facts approved for drafts",
    "needs_review": "Needs source review",
    "internal_only": "Internal reference only",
    "prohibited": "Not allowed by its use policy",
    "retracted": "Withdrawn",
    "not_reviewed": "Not reviewed as a source",
}

CMP_SEGMENTS = ("/*lio:cmp.segments*/ SELECT id::text,ordinal,kind,text,locator,language FROM public.pr_library_segments WHERE workspace_id=%s "
                "AND version_key=%s AND superseded_at IS NULL ORDER BY ordinal LIMIT %s")
CMP_CHUNKS = "/*lio:cmp.chunks*/ SELECT ordinal,text FROM public.pr_library_chunks WHERE workspace_id=%s AND asset_id=%s ORDER BY ordinal LIMIT %s"
CMP_USAGE = ("/*lio:cmp.usage*/ SELECT event_type,draft_id,post_id,channel,metrics IS NOT NULL FROM public.pr_library_usage_events "
             "WHERE workspace_id=%s AND (version_key=%s OR (version_key IS NULL AND asset_key=%s)) ORDER BY at DESC LIMIT %s")
CMP_USED_IN = ("/*lio:cmp.used_in*/ SELECT to_kind,to_key,status FROM public.pr_library_relations WHERE workspace_id=%s AND from_version=%s "
               "AND relation='used_in' ORDER BY created_at DESC LIMIT %s")
CMP_AFFECTED = ("/*lio:cmp.affected*/ SELECT from_version,to_kind,to_key,status,evidence FROM public.pr_library_relations WHERE workspace_id=%s "
                "AND from_version=ANY(%s) AND relation='used_in' AND status='stale' ORDER BY updated_at DESC LIMIT %s")


def _key(value) -> str:
    return str(value).replace("-", "").lower()


# --- side facts ------------------------------------------------------------------------------------------------------------
def approval(ctx, version: dict) -> dict:
    """Approval as recorded by the existing source review (Ideas source policy, approved facts, useApprovals) plus the
    purpose policy's current decisions. A version without its own reviewed import is 'not_reviewed', never approved."""
    source = policy.ideas_source(ctx, version)
    if source is not None and (source.get("origin") or {}).get("sha256") not in (None, version.get("sha256")):
        source = None  # imported from different bytes: that review does not cover this version
    approved_facts = sum(1 for f in (source or {}).get("facts", []) if isinstance(f, dict) and f.get("approved"))
    use_approved = bool(source) and source_policy.use_approved(source)
    if source is None:
        status = "not_reviewed"
    elif not source.get("active"):
        status = "retracted"
    else:
        name = source.get("sourcePolicy")
        if name is None:
            status = "needs_review"
        elif name == "prohibited":
            status = "prohibited"
        elif name == "internal_reference":
            status = "internal_only"
        elif name == "public_quote" or (name == "rewrite_approval" and use_approved):
            status = "approved_for_public_use"
        elif approved_facts:
            status = "approved_for_drafts"
        else:
            status = "needs_review"
    draft = policy.authorize_source(ctx, version, "draft_evidence")
    public = policy.authorize_source(ctx, version, "public_use")
    return {"status": status, "label": APPROVAL_LABELS[status], "approvedFacts": approved_facts, "useApproved": use_approved,
            "draftEvidence": {"allowed": draft.allowed, "reason": draft.reason}, "publicUse": {"allowed": public.allowed, "reason": public.reason}}


def usage(ctx, version: dict) -> dict:
    """Where this exact version was used. Metrics stay 'unknown' when not recorded; nothing is inferred."""
    ctx.cur.execute(CMP_USAGE, (ctx.workspace_id, version["versionId"], version["assetId"], 20))
    events = [{"type": t, "draftId": d, "postId": p, "channel": ch, "metrics": "recorded" if has else "unknown"} for t, d, p, ch, has in ctx.cur.fetchall()]
    ctx.cur.execute(CMP_USED_IN, (ctx.workspace_id, version["versionId"], 20))
    used_in = [{"kind": kind, "key": key, "status": status} for kind, key, status in ctx.cur.fetchall()]
    return {"count": len(events) + sum(1 for u in used_in if u["status"] in ("active", "stale")), "events": events, "usedIn": used_in}


def _orientation(media: dict):
    w, h = media.get("width"), media.get("height")
    if not isinstance(w, (int, float)) or not isinstance(h, (int, float)) or w <= 0 or h <= 0:
        return None
    return "square" if w == h else ("portrait" if h > w else "landscape")


def _side(ctx, version: dict) -> dict:
    return {"assetRef": versions.ref(version), "versionNo": version["versionNo"], "title": version["title"], "filename": version["filename"],
            "kind": version["kind"], "mime": version["mime"], "bytes": version["bytes"], "createdAt": version["createdAt"],
            "approval": approval(ctx, version), "usage": usage(ctx, version)}


METADATA_FIELDS = ("title", "filename", "kind", "mime", "bytes", "sha256", "tags")


def metadata_diff(left: dict, right: dict) -> list:
    out = []
    for name in METADATA_FIELDS:
        a, b = left.get(name), right.get(name)
        out.append({"field": name, "left": a, "right": b, "changed": a != b})
    for name in ("durationMs", "width", "height"):
        a, b = (left.get("media") or {}).get(name), (right.get("media") or {}).get(name)
        if a is not None or b is not None:
            out.append({"field": name, "left": a, "right": b, "changed": a != b})
    return out


# --- text ------------------------------------------------------------------------------------------------------------------
def _norm(text: str) -> str:
    return " ".join(str(text).split())


def text_diff(left: list, right: list, *, max_hunks: int = MAX_HUNKS) -> dict:
    """Line diff. `left`/`right` are [{text, segmentId?, locator?}]. The summary always counts everything; hunks are bounded."""
    matcher = difflib.SequenceMatcher(None, [_norm(x["text"]) for x in left], [_norm(x["text"]) for x in right], autojunk=False)
    summary = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    hunks, truncated = [], False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        li, lj = i2 - i1, j2 - j1
        if tag == "equal":
            summary["unchanged"] += li
        elif tag == "replace":
            summary["changed"] += min(li, lj)
            summary["removed"] += max(0, li - lj)
            summary["added"] += max(0, lj - li)
        elif tag == "delete":
            summary["removed"] += li
        else:
            summary["added"] += lj
        if len(hunks) >= max_hunks:
            truncated = True
            continue
        if tag == "equal":
            hunks.append({"op": "equal", "count": li})
        else:
            hunks.append({"op": tag, "left": left[i1:i2][:MAX_HUNK_LINES], "right": right[j1:j2][:MAX_HUNK_LINES],
                          **({"clipped": True} if li > MAX_HUNK_LINES or lj > MAX_HUNK_LINES else {})})
    return {"summary": summary, "hunks": hunks, "truncated": truncated}


def _lines(ctx, version: dict) -> tuple[list, str, bool]:
    """Current segments first (each line keeps its segment's locator); else extracted text with exact character offsets."""
    ctx.cur.execute(CMP_SEGMENTS, (ctx.workspace_id, version["versionId"], MAX_SEGMENTS))
    rows = ctx.cur.fetchall()
    out, chars = [], 0
    if rows:
        for sid, _, _, text, locator, _ in rows:
            for line in str(text or "").split("\n"):
                line = line.strip()
                if not line:
                    continue
                out.append({"text": line[:MAX_LINE], "segmentId": _key(sid), "locator": locator if isinstance(locator, dict) else None})
                chars += len(line)
                if chars > MAX_CHARS or len(out) >= MAX_LINES:
                    return out, "segments", True
        return out, "segments", len(rows) >= MAX_SEGMENTS
    if version["legacy"]:
        return [], "none", False
    ctx.cur.execute(CMP_CHUNKS, (ctx.workspace_id, uuid.UUID(hex=version["versionId"]), 400))
    text = "".join(str(t or "") for _, t in ctx.cur.fetchall())  # chunks are contiguous slices of the normalized text
    if not text.strip():
        return [], "none", False
    offset = 0
    for raw in text.split("\n"):
        start, end = offset, offset + len(raw)
        offset = end + 1
        line = raw.strip()
        if not line:
            continue
        out.append({"text": line[:MAX_LINE], "locator": {"kind": "text", "start": start, "end": end}})
        chars += len(line)
        if chars > MAX_CHARS or len(out) >= MAX_LINES:
            return out, "extracted_text", True
    return out, "extracted_text", False


def _media(ctx, version: dict) -> dict:
    ctx.cur.execute(CMP_SEGMENTS, (ctx.workspace_id, version["versionId"], MAX_SEGMENTS))
    segments = []
    for sid, _, kind, text, locator, _ in ctx.cur.fetchall():
        if isinstance(locator, dict) and locator.get("kind") == "time":
            segments.append({"segmentId": _key(sid), "kind": kind, "locator": locator, "text": str(text or "")[:200]})
            if len(segments) >= MEDIA_SEGMENTS:
                break
    duration = (version.get("media") or {}).get("durationMs")
    return {"assetRef": versions.ref(version), "durationMs": int(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
            "segments": segments}


def _image(version: dict) -> dict:
    media = version.get("media") or {}
    return {"assetRef": versions.ref(version), "width": media.get("width"), "height": media.get("height"), "orientation": _orientation(media)}


def _mode(left: dict, right: dict) -> str:
    kinds = (left["kind"], right["kind"])
    if all(k in TEXT_KINDS for k in kinds):
        return "text"
    if kinds == ("image", "image"):
        return "image"
    if all(k in TIME_KINDS for k in kinds):
        return "media"
    return "unsupported"


def compare_versions(ctx, refs) -> dict:
    """compare_versions(ctx, refs) -> ComparisonResult for exactly two versions the caller may browse."""
    ctx.require("read")
    if not isinstance(refs, list) or len(refs) != 2:
        c.fail("Compare exactly two versions.")
    parsed = [c.asset_ref(r) for r in refs]
    if parsed[0]["versionId"] == parsed[1]["versionId"]:
        c.fail("Choose two different versions to compare.")
    left, right = (versions.resolve(ctx, r) for r in parsed)
    for version in (left, right):
        policy.require(policy.authorize_source(ctx, version, "browse"))
    mode = _mode(left, right)
    newer = None
    if left["assetId"] == right["assetId"]:
        newer = "left" if left["versionNo"] > right["versionNo"] else "right"
    result = {"contractVersion": c.CONTRACT_VERSION, "mode": mode, "supported": mode != "unsupported", "left": _side(ctx, left), "right": _side(ctx, right),
              "metadata": metadata_diff(left, right), "relationship": {"sameAsset": left["assetId"] == right["assetId"], "newer": newer}, "warnings": []}
    if mode == "text":
        a, a_source, a_cut = _lines(ctx, left)
        b, b_source, b_cut = _lines(ctx, right)
        result["text"] = {"left": {"source": a_source, "lines": len(a)}, "right": {"source": b_source, "lines": len(b)}, **text_diff(a, b),
                          "available": bool(a or b)}
        if not (a or b):
            result["message"] = "Neither version has extracted text yet, so only their details are compared."
        elif not (a and b):
            result["warnings"].append("One version has no extracted text yet; its side shows as empty.")
        if a_cut or b_cut:
            result["warnings"].append("Long text was compared up to a limit.")
    elif mode == "image":
        a, b = _image(left), _image(right)
        same = None not in (a["width"], a["height"], b["width"], b["height"]) and (a["width"], a["height"]) == (b["width"], b["height"])
        result["image"] = {"left": a, "right": b, "sameDimensions": same, "note": "Shown side by side. Rafii does not judge which version is better."}
    elif mode == "media":
        a, b = _media(ctx, left), _media(ctx, right)
        delta = b["durationMs"] - a["durationMs"] if a["durationMs"] is not None and b["durationMs"] is not None else None
        result["media"] = {"left": a, "right": b, "durationDeltaMs": delta}
    else:
        result["message"] = UNSUPPORTED
    return result


def compare_http(ctx, request):
    """POST .../compare {refs:[AssetRef, AssetRef]}."""
    body = request.get("body") or {}
    if not isinstance(body, dict) or set(body) != {"refs"}:
        c.fail("Send exactly two version references to compare.")
    return compare_versions(ctx, body["refs"])


# --- version stack ---------------------------------------------------------------------------------------------------------
def _dependent_label(ctx, kind: str, key: str) -> str:
    if kind == "draft":
        variant = next((v for v in ctx.state.get("variants") or [] if isinstance(v, dict) and v.get("id") == key), None)
        if variant:
            return f"{str(variant.get('platform') or 'Post').title()} draft"
        return "Draft"
    if kind == "idea":
        source = next((s for s in ctx.state.get("sources") or [] if isinstance(s, dict) and s.get("id") == key), None)
        return str((source or {}).get("title") or "Imported source")[:120]
    return {"source_pack": "Source pack", "post": "Post"}.get(kind, kind)


def versions_http(ctx, request):
    """GET .../assets/{key}/versions: the version stack (oldest first) with approvals, and drafts affected by newer versions."""
    ctx.require("read")
    version = versions.get(ctx, request["params"]["key"])
    try:
        stack = versions.stack(ctx, version["assetId"])
    except AlphaError:
        stack = [version]
    head = stack[-1]
    entries = [{"assetRef": versions.ref(v), "versionNo": v["versionNo"], "title": v["title"], "filename": v["filename"], "createdAt": v["createdAt"],
                "status": v["status"], "current": v["versionId"] == head["versionId"], "approval": approval(ctx, v)} for v in stack[-50:]]
    by_key = {v["versionId"]: v for v in stack}
    olds = [v["versionId"] for v in stack if v["versionId"] != head["versionId"]]
    affected, seen = [], set()
    if olds:
        ctx.cur.execute(CMP_AFFECTED, (ctx.workspace_id, olds, MAX_AFFECTED))
        for from_version, kind, key, status, _ in ctx.cur.fetchall():
            if from_version not in by_key or (kind, key) in seen:
                continue
            seen.add((kind, key))
            affected.append({"kind": kind, "key": key, "label": _dependent_label(ctx, kind, key), "citesVersion": versions.ref(by_key[from_version]),
                             "currentVersion": versions.ref(head), "status": status, "flagged": True})
        # Sources imported from an older version after it was superseded are shown too, honestly marked as not yet flagged.
        for source in (ctx.state.get("sources") or [])[:5000]:
            origin = source.get("origin") if isinstance(source, dict) else None
            if not isinstance(origin, dict) or origin.get("kind") != "library" or origin.get("assetId") not in olds or len(affected) >= MAX_AFFECTED:
                continue
            cited = [("idea", source.get("id"))] + [("draft", v.get("id")) for v in ctx.state.get("variants") or []
                                                     if isinstance(v, dict) and source.get("id") in (v.get("sourceIds") or [])]
            for kind, key in cited:
                if isinstance(key, str) and (kind, key) not in seen:
                    seen.add((kind, key))
                    affected.append({"kind": kind, "key": key, "label": _dependent_label(ctx, kind, key),
                                     "citesVersion": versions.ref(by_key[origin["assetId"]]), "currentVersion": versions.ref(head),
                                     "status": "stale", "flagged": False})
    return {"assetRef": versions.ref(version), "current": versions.ref(head), "versions": entries, "affected": affected[:MAX_AFFECTED],
            "truncated": len(stack) > 50}
