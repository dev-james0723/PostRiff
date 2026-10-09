"""Asset and content-version identity (engineering spec §3, §4 AssetVersion).

A normalized `pr_library_assets` row is one immutable content version; `lineage_id` (defaulting to the row id) is the
stable asset identity shared by a version stack. Legacy photos/videos in workspace JSON are single-version assets whose
id is both asset and version. Every lookup is scoped to ctx.workspace_id: a foreign or missing key is "unavailable" with
the same status and wording, so existence never leaks across workspaces.
"""
from __future__ import annotations

import re
import uuid

from postriff_alpha.domain import AlphaError

from . import contracts as c

HEX64 = re.compile(r"^[0-9a-f]{64}$")
COLUMNS = ("id,lineage_id,version_no,workspace_id,original_filename,display_title,title_source,summary,tags,kind,mime,extension,bytes,sha256,"
           "processing_status,analysis_status,indexing_status,transcription_status,source_id,source_kind,media,duplicate_of,provenance,"
           "extract(epoch from created_at)")


def _row(r) -> dict:
    key = r[0].hex
    lineage = r[1].hex if r[1] else key
    status = r[14]
    return {"assetId": lineage, "versionId": key, "versionNo": int(r[2]), "sha256": r[13] or "", "filename": r[4],
            "title": r[5] or r[4].rsplit(".", 1)[0], "titleSource": r[6], "summary": r[7], "tags": list(r[8] or []),
            "kind": r[9], "mime": r[10], "extension": r[11], "bytes": int(r[12]), "status": status,
            "analysisStatus": r[15], "indexingStatus": r[16], "transcriptionStatus": r[17], "sourceId": r[18],
            "sourceKind": r[19], "media": r[20] or {}, "duplicateOf": r[21].hex if r[21] else None, "provenance": r[22] or {},
            "createdAt": float(r[23]), "legacy": False}


def _legacy(a: dict) -> dict:
    mime = str(a.get("mime") or "image/jpeg")
    sha = str(a.get("hash") or "")
    created = a.get("createdAt") or a.get("uploadedAt") or 0
    try:
        created = float(created)
    except (TypeError, ValueError):
        created = 0.0
    media = {k: a[k] for k in ("width", "height") if isinstance(a.get(k), (int, float))}
    if isinstance(a.get("duration"), (int, float)):
        media["durationMs"] = int(float(a["duration"]) * 1000)
    return {"assetId": a["id"], "versionId": a["id"], "versionNo": 1, "sha256": sha if HEX64.fullmatch(sha) else "",
            "filename": a.get("originalFilename") or a.get("name") or f"{a['id']}.{mime.split('/')[-1]}",
            "title": a.get("displayTitle") or a.get("alt") or a.get("originalFilename") or ("Video" if mime.startswith("video/") else "Photo"),
            "titleSource": "user" if a.get("displayTitle") else "filename", "summary": a.get("alt"), "tags": list(a.get("tags") or []),
            "kind": "video" if mime.startswith("video/") else "image", "mime": mime, "extension": mime.split("/")[-1],
            "bytes": int(a.get("bytes") or 0), "status": "legacy", "analysisStatus": "not_applicable", "indexingStatus": "not_applicable",
            "transcriptionStatus": "not_applicable", "sourceId": None, "sourceKind": "upload", "media": media, "duplicateOf": None,
            "provenance": {"lineage": a.get("lineage")} if a.get("lineage") else {}, "createdAt": created, "legacy": True}


def legacy_assets(ctx) -> dict:
    if "legacy" not in ctx.caches:
        items = {}
        for a in (ctx.state.get("phase2") or {}).get("assets", []):
            if isinstance(a, dict) and isinstance(a.get("id"), str) and c.KEY.fullmatch(a["id"]) and not a.get("deleted") and not a.get("deletionPending"):
                items[a["id"]] = _legacy(a)
        ctx.caches["legacy"] = items
    return ctx.caches["legacy"]


def _labels(ctx, versions: dict):
    keys = [k for k, v in versions.items() if v["legacy"]]
    if not keys:
        return
    ctx.cur.execute("SELECT asset_key,display_title,tags FROM public.pr_library_labels WHERE workspace_id=%s AND asset_key=ANY(%s)", (ctx.workspace_id, keys))
    for key, title, tags in ctx.cur.fetchall():
        if title:
            versions[key].update(title=title, titleSource="user")
        if tags:
            versions[key]["tags"] = list(tags)


def load(ctx, keys) -> dict:
    """Batch-resolve version keys in this workspace. Missing/foreign keys are simply absent."""
    keys = list(dict.fromkeys(k for k in keys if isinstance(k, str) and c.KEY.fullmatch(k)))
    found: dict = {}
    if keys:
        ctx.cur.execute(f"SELECT {COLUMNS} FROM public.pr_library_assets WHERE workspace_id=%s AND id=ANY(%s::uuid[])",
                        (ctx.workspace_id, [str(uuid.UUID(hex=k)) for k in keys]))
        for r in ctx.cur.fetchall():
            v = _row(r)
            found[v["versionId"]] = v
        legacy = legacy_assets(ctx)
        for k in keys:
            if k not in found and k in legacy:
                found[k] = dict(legacy[k])
        _labels(ctx, found)
    return found


def get(ctx, key: str, *, allow_hidden: bool = False) -> dict:
    found = load(ctx, [c.asset_key(key)]).get(c.asset_key(key))
    if found is None or (not allow_hidden and found["status"] in ("deleting", "duplicate")):
        raise AlphaError("This item is unavailable.", 404, code="library_unavailable")
    return found


def resolve(ctx, ref: dict) -> dict:
    """AssetRef -> version, enforcing that versionId belongs to assetId's lineage and the hash still matches.
    A citation or action bound to an old version keeps resolving to that old version, never the newest one."""
    ref = c.asset_ref(ref)
    version = get(ctx, ref["versionId"])
    if ref["assetId"] not in (version["assetId"], version["versionId"]):  # lineage id, or a pre-link self reference
        raise AlphaError("This item is unavailable.", 404, code="library_unavailable")
    if ref["sha256"] and version["sha256"] and ref["sha256"] != version["sha256"]:
        raise AlphaError("This source version changed. Refresh before using it.", 409, code="library_version_mismatch")
    return version


def ref(version: dict) -> dict:
    return {"assetId": version["assetId"], "versionId": version["versionId"], "sha256": version["sha256"]}


def stack(ctx, asset_id: str) -> list[dict]:
    """All versions of one asset, oldest first. Legacy media are single-version stacks."""
    key = c.asset_key(asset_id)
    legacy = legacy_assets(ctx)
    if key in legacy:
        return [dict(legacy[key])]
    ctx.cur.execute(f"SELECT {COLUMNS} FROM public.pr_library_assets WHERE workspace_id=%s AND (id=%s OR lineage_id=%s) "
                    "AND processing_status NOT IN ('deleting','duplicate') ORDER BY version_no,created_at", (ctx.workspace_id, uuid.UUID(hex=key), uuid.UUID(hex=key)))
    rows = [_row(r) for r in ctx.cur.fetchall()]
    if not rows:
        raise AlphaError("This item is unavailable.", 404, code="library_unavailable")
    return rows


def current(ctx, asset_id: str) -> dict:
    return stack(ctx, asset_id)[-1]


def accessible_keys(ctx) -> dict:
    """{versionKey: status} for every browsable version (normalized + legacy) — the candidate universe before purpose
    filtering. Bounded by workspace storage limits, not by recency."""
    if "accessible" not in ctx.caches:
        ctx.cur.execute("SELECT replace(id::text,'-',''),processing_status FROM public.pr_library_assets WHERE workspace_id=%s AND processing_status NOT IN ('deleting','duplicate')", (ctx.workspace_id,))
        out = {k: s for k, s in ctx.cur.fetchall()}
        for k in legacy_assets(ctx):
            out.setdefault(k, "legacy")
        ctx.caches["accessible"] = out
    return dict(ctx.caches["accessible"])
