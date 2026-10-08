"""One permission-aware Library search for the UI, the Agent and OpenUI (engineering spec §5 SearchRequest/SearchResponse,
§6, §8; implementation plan T04; acceptance A023, A025–A031).

`search_library(ctx, request) -> SearchResponse` is the only retrieval entry point; `search_http` is its route.

Pipeline (bounded at every step, inside the caller's verified workspace context):
1. Scope — the whole workspace (current version of every asset), a collection (manual items and smart members in
   pr_library_collection_items, minus exclude overrides) or a selection resolved through versions (a ref to an old
   version stays on that version). The candidate universe is every browsable normalized row plus the legacy
   photos/videos in workspace JSON. There is no newest-N cap.
2. Snapshot — the first page records the database clock; every page excludes assets, segments and embeddings created
   after it, so later arrivals never shift pages.
3. Purpose — before any ranking. Browse sees everything stored. Other purposes keep exactly what
   policy.authorize_source allows: grant key sets for plain items (a workspace grant means all), the full policy call
   for items linked to an Ideas source, and legacy denials stay denials.
4. Filters — contracts.filters, with createdFrom/createdTo resolved in the request's IANA time zone.
5. Ranking — exact identity first (32-hex id, sha256 prefix of ≥8 hex, exact filename/title, dimensions such as
   1080x1920); then one lexical list (segments via to_tsquery('simple', textnorm.tsquery(q)), asset metadata terms,
   and the legacy chunk index for items not yet segmented, merged by RRF); semantic = pgvector kNN over active text
   embeddings of the query's model/dims/index generation; visual = kNN over local perceptual vectors for similarTo.
   Modes fuse by reciprocal-rank fusion, k=60, equal weights ('rrf-60-v1'). Each mode keeps at most K candidates;
   reaching K is reported, never hidden.
6. Page, passages and snippets, capability states, a grant re-check (policy.recheck) and a signed cursor.

Scores are never returned: order is the only ranking output. Coverage counts and facets are computed on the server over
the caller's eligible scope only. A vector or provider failure yields labelled lexical results with truthful
modesApplied, `partial` and a warning.
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
import uuid
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError

from .. import memory, source_policy
from . import contracts as c
from . import cursors, index, policy, providers, textnorm, versions

RANKING_VERSION = "rrf-60-v1"
RRF_K = 60
WEIGHTS = {"lexical": 1.0, "semantic": 1.0, "visual": 1.0}
LEXICAL_K = 1000
SEMANTIC_K = 200
VISUAL_K = 200
CANDIDATE_LIMITS = {"lexical": LEXICAL_K, "semantic": SEMANTIC_K, "visual": VISUAL_K}
PASSAGES_PER_HIT = 3
SNIPPET_CHARS = 240
MAX_PASSAGE_CHARS = 1500
READY_FOR_PURPOSE = ("ready", "unsupported", "legacy")
PENDING_STATUSES = ("pending", "queued", "processing")
WATCHED_CAPABILITIES = ("extract", "transcribe", "visual", "embed_text", "embed_visual")
LEGACY_INDEX = "legacy text index (not yet segmented)"
CLOUD_LLM = {"location": "cloud", "category": "llm"}

UNIVERSE_SQL = ("/* lib:universe */ SELECT replace(id::text,'-',''),replace(coalesce(lineage_id,id)::text,'-',''),version_no,original_filename,"
                "display_title,tags,kind,mime,bytes,coalesce(sha256,''),processing_status,indexing_status,transcription_status,source_id,media,"
                "extract(epoch from created_at) FROM public.pr_library_assets WHERE workspace_id=%(w)s AND processing_status NOT IN ('deleting','duplicate')")
LABELS_SQL = "/* lib:labels */ SELECT asset_key,display_title,tags FROM public.pr_library_labels WHERE workspace_id=%(w)s AND asset_key=ANY(%(keys)s::text[])"
CLOCK_SQL = "/* lib:clock */ SELECT extract(epoch from now())"
COLLECTION_SQL = "/* lib:collection */ SELECT name FROM public.pr_library_collections WHERE workspace_id=%(w)s AND id=%(id)s"
MEMBERS_SQL = ("/* lib:collection-members */ SELECT i.asset_key FROM public.pr_library_collection_items i WHERE i.workspace_id=%(w)s AND i.collection_id=%(id)s "
               "AND NOT EXISTS (SELECT 1 FROM public.pr_library_collection_overrides o WHERE o.workspace_id=i.workspace_id "
               "AND o.collection_id=i.collection_id AND o.asset_key=i.asset_key AND o.mode='exclude')")
SEGMENT_STATS_SQL = ("/* lib:segment-stats */ SELECT version_key,bool_or(normalizer_version=%(nv)s),count(*) FROM public.pr_library_segments "
                     "WHERE workspace_id=%(w)s AND superseded_at IS NULL AND created_at<=to_timestamp(%(t)s) GROUP BY version_key")
EMBEDDING_STATS_SQL = ("/* lib:embedding-stats */ SELECT version_key,modality,model_id,dims,index_generation,count(*) FROM public.pr_library_embeddings "
                       "WHERE workspace_id=%(w)s AND status='active' AND created_at<=to_timestamp(%(t)s) GROUP BY 1,2,3,4,5")
CAPABILITY_STATS_SQL = ("/* lib:capability-stats */ SELECT asset_key,capability,state FROM public.pr_library_capabilities WHERE workspace_id=%(w)s "
                        "AND state IN ('queued','processing','failed')")
CAPABILITY_FILTER_SQL = "/* lib:capability-filter */ SELECT asset_key,state FROM public.pr_library_capabilities WHERE workspace_id=%(w)s AND capability=%(cap)s"
USAGE_SQL = ("/* lib:usage */ SELECT asset_key FROM public.pr_library_usage_events WHERE workspace_id=%(w)s UNION "
             "SELECT from_key FROM public.pr_library_relations WHERE workspace_id=%(w)s AND relation='used_in' AND status='active'")
LANGUAGES_SQL = ("/* lib:languages */ SELECT DISTINCT version_key FROM public.pr_library_segments WHERE workspace_id=%(w)s AND superseded_at IS NULL "
                 "AND (language=ANY(%(langs)s::text[]) OR split_part(language,'-',1)=ANY(%(langs)s::text[]))")
LEXICAL_SEGMENTS_SQL = (
    "/* lib:lexical-segments */ WITH q AS (SELECT to_tsquery('simple',%(tsq)s) AS q), "
    "m AS (SELECT s.version_key,s.id,s.ordinal,ts_rank(s.search_vector,q.q,1) AS r FROM public.pr_library_segments s, q "
    "WHERE s.workspace_id=%(w)s AND s.superseded_at IS NULL AND s.search_vector@@q.q AND s.normalizer_version=%(nv)s "
    "AND s.created_at<=to_timestamp(%(t)s) AND s.version_key=ANY(%(keys)s::text[])), "
    "best AS (SELECT DISTINCT ON (version_key) version_key,id,ordinal,r FROM m ORDER BY version_key,r DESC,ordinal) "
    "SELECT version_key,replace(id::text,'-',''),r,count(*) OVER () FROM best ORDER BY r DESC,version_key LIMIT %(k)s")
LEXICAL_CHUNKS_SQL = (
    "/* lib:lexical-chunks */ SELECT replace(c.asset_id::text,'-',''),min(c.ordinal),"
    "coalesce(max(ts_rank(c.search_vector,to_tsquery('simple',%(tsq)s))),0) AS r,count(*) OVER () FROM public.pr_library_chunks c "
    "WHERE c.workspace_id=%(w)s AND c.asset_id=ANY(%(ids)s::uuid[]) "
    "AND (%(tsq)s::text IS NULL OR c.search_vector@@to_tsquery('simple',%(tsq)s)) AND c.text ~ ALL(%(rx)s::text[]) "
    "GROUP BY c.asset_id ORDER BY r DESC,c.asset_id LIMIT %(k)s")
KNN_TEXT_SQL = (
    "/* lib:knn */ SELECT e.version_key,replace(e.segment_id::text,'-',''),(e.embedding::vector(1024)) <=> %(vec)s::vector(1024) AS d "
    "FROM public.pr_library_embeddings e WHERE e.workspace_id=%(w)s AND e.status='active' AND e.modality='text' AND e.dims=1024 "
    "AND e.modality=%(modality)s AND e.dims=%(dims)s AND e.model_id=%(model)s AND e.index_generation=%(gen)s AND e.created_at<=to_timestamp(%(t)s) "
    "AND e.version_key=ANY(%(keys)s::text[]) ORDER BY {open}(e.embedding::vector(1024)) <=> %(vec)s::vector(1024){close} LIMIT %(k)s")
KNN_VISUAL_SQL = (
    "/* lib:knn */ SELECT e.version_key,replace(e.segment_id::text,'-',''),(e.embedding::vector(256)) <=> %(vec)s::vector(256) AS d "
    "FROM public.pr_library_embeddings e WHERE e.workspace_id=%(w)s AND e.status='active' AND e.modality='visual' AND e.dims=256 "
    "AND e.modality=%(modality)s AND e.dims=%(dims)s AND e.model_id=%(model)s AND e.index_generation=%(gen)s AND e.created_at<=to_timestamp(%(t)s) "
    "AND e.version_key=ANY(%(keys)s::text[]) ORDER BY {open}(e.embedding::vector(256)) <=> %(vec)s::vector(256){close} LIMIT %(k)s")
VISUAL_REFERENCE_SQL = ("/* lib:visual-reference */ SELECT e.embedding::text FROM public.pr_library_embeddings e WHERE e.workspace_id=%(w)s "
                        "AND e.version_key=%(key)s AND e.status='active' AND e.modality='visual' AND e.model_id=%(model)s AND e.dims=%(dims)s "
                        "AND e.index_generation=%(gen)s ORDER BY e.created_at DESC LIMIT 1")
PASSAGES_SQL = (
    "/* lib:passages */ SELECT version_key,sid,text,locator,kind,language,r,ordinal FROM (SELECT s.version_key,replace(s.id::text,'-','') AS sid,"
    "s.text,s.locator,s.kind,s.language,ts_rank(s.search_vector,q.q,1) AS r,s.ordinal,row_number() OVER (PARTITION BY s.version_key "
    "ORDER BY ts_rank(s.search_vector,q.q,1) DESC,s.ordinal) AS n FROM public.pr_library_segments s, (SELECT to_tsquery('simple',%(tsq)s) AS q) q "
    "WHERE s.workspace_id=%(w)s AND s.version_key=ANY(%(keys)s::text[]) AND s.superseded_at IS NULL AND s.normalizer_version=%(nv)s "
    "AND s.created_at<=to_timestamp(%(t)s) AND s.search_vector@@q.q) ranked WHERE n<=%(per)s ORDER BY version_key,r DESC,ordinal")
SEGMENTS_BY_ID_SQL = ("/* lib:segments-by-id */ SELECT version_key,replace(id::text,'-',''),text,locator,kind,language,ordinal "
                      "FROM public.pr_library_segments WHERE workspace_id=%(w)s AND id=ANY(%(ids)s::uuid[])")
CHUNK_PASSAGES_SQL = ("/* lib:chunk-passages */ SELECT replace(asset_id::text,'-',''),ordinal,text FROM public.pr_library_chunks "
                      "WHERE workspace_id=%(w)s AND asset_id=ANY(%(ids)s::uuid[])")
HIT_CAPABILITIES_SQL = ("/* lib:hit-capabilities */ SELECT asset_key,capability,state,error_code,detail,retryable,progress,processor_version,"
                        "extract(epoch from updated_at) FROM public.pr_library_capabilities WHERE workspace_id=%(w)s AND asset_key=ANY(%(keys)s::text[])")

UUIDISH = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$")
HEX_PREFIX = re.compile(r"^[0-9a-f]{8,64}$")
DIMENSIONS = re.compile(r"^(\d{2,5})\s*[x×*]\s*(\d{2,5})$")
TAG = re.compile(r"<[^<>]{0,400}>")
CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f​-‏ -‮⁦-⁩﻿]")
SPACE = re.compile(r"\s+")


class _Unavailable(Exception):
    """A requested mode cannot run for this request; the message becomes a user-facing warning."""


# --- universe and scope -------------------------------------------------------------------------------------------
def _json(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _row_item(r) -> dict:
    filename = r[3] or ""
    return {"assetId": r[1], "versionId": r[0], "versionNo": int(r[2] or 1), "filename": filename, "title": r[4] or filename.rsplit(".", 1)[0],
            "tags": list(r[5] or []), "kind": r[6], "mime": r[7], "bytes": int(r[8] or 0), "sha256": r[9] or "", "status": r[10],
            "indexingStatus": r[11], "transcriptionStatus": r[12], "sourceId": r[13], "media": _json(r[14]), "createdAt": float(r[15] or 0),
            "legacy": False}


def universe(ctx) -> tuple[dict, dict]:
    """(current, rows): the current version of every browsable asset (normalized + legacy) and every normalized row.

    Bounded by the workspace's storage quota, never by recency. Cached for the request."""
    if "searchUniverse" in ctx.caches:
        return ctx.caches["searchUniverse"]
    ctx.cur.execute(UNIVERSE_SQL, {"w": ctx.workspace_id})
    rows = {}
    for r in ctx.cur.fetchall():
        item = _row_item(r)
        rows[item["versionId"]] = item
    best: dict = {}
    for item in rows.values():
        rank = (item["status"] in ("ready", "unsupported"), item["versionNo"], item["createdAt"], item["versionId"])
        if item["assetId"] not in best or rank > best[item["assetId"]][0]:
            best[item["assetId"]] = (rank, item["versionId"])
    current = {key: dict(rows[key]) for _, key in best.values()}
    for item in rows.values():  # a newer upload of an existing asset that is still processing
        chosen = current.get(best[item["assetId"]][1])
        if item["status"] in PENDING_STATUSES and item["versionNo"] > chosen["versionNo"]:
            chosen["pendingVersion"] = True
    legacy = {k: v for k, v in versions.legacy_assets(ctx).items() if k not in rows}
    if legacy:
        ctx.cur.execute(LABELS_SQL, {"w": ctx.workspace_id, "keys": list(legacy)})
        labels = {k: (title, tags) for k, title, tags in ctx.cur.fetchall()}
        for key, value in legacy.items():
            item = dict(value)
            title, tags = labels.get(key, (None, None))
            if title:
                item.update(title=title, titleSource="user")
            if tags:
                item["tags"] = list(tags)
            if item["createdAt"] > 1e11:  # milliseconds in older JSON records
                item["createdAt"] /= 1000.0
            item.setdefault("indexingStatus", "not_applicable")
            # versions._legacy falls back to "Photo"/"Video" when nothing names the item; that is not a real title.
            item["genericTitle"] = item.get("titleSource") != "user" and item.get("title") in ("Photo", "Video")
            current[key] = item
    ctx.caches["searchUniverse"] = (current, rows)
    return current, rows


def _collection(ctx, collection_id: str) -> tuple[str, set]:
    cache = ctx.caches.setdefault("searchCollections", {})
    if collection_id not in cache:
        params = {"w": ctx.workspace_id, "id": str(uuid.UUID(hex=collection_id))}
        ctx.cur.execute(COLLECTION_SQL, params)
        row = ctx.cur.fetchone()
        if not row:
            raise AlphaError("This collection is unavailable.", 404, code="library_unavailable")
        ctx.cur.execute(MEMBERS_SQL, params)
        cache[collection_id] = (row[0], {r[0] for r in ctx.cur.fetchall()})
    return cache[collection_id]


def _in_members(item, members) -> bool:
    return item["versionId"] in members or item["assetId"] in members


def _scope(ctx, scope: dict, current: dict) -> tuple[dict, str]:
    if scope["kind"] == "workspace":
        return dict(current), "Entire Library"
    if scope["kind"] == "collection":
        name, members = _collection(ctx, scope["collectionId"])
        return {k: v for k, v in current.items() if _in_members(v, members)}, f"Collection “{name}”"
    scoped = {}
    for ref in scope["assetRefs"]:
        version = dict(versions.resolve(ctx, ref))  # 404 for foreign/missing, 409 for a changed hash
        version.setdefault("indexingStatus", "not_applicable")
        if version.get("legacy") and version["createdAt"] > 1e11:
            version["createdAt"] /= 1000.0
        scoped[version["versionId"]] = version
    count = len(scoped)
    return scoped, f"{count} selected item" + ("" if count == 1 else "s")


# --- purpose (before ranking) -------------------------------------------------------------------------------------
def _cover(grants) -> tuple[bool, set]:
    everything, keys = False, set()
    for g in grants:
        if g["scopeKind"] == "workspace":
            everything = True
        elif g["scopeKind"] == "asset":
            keys.add(g["scopeKey"])
        else:
            keys.update(g["memberKeys"])
    return everything, keys


def _covered(cover, item) -> bool:
    return cover[0] or item["versionId"] in cover[1] or item["assetId"] in cover[1]


def eligible_items(ctx, purpose: str, items: dict, processing: dict | None = None) -> dict:
    """Items policy.authorize_source(ctx, item, purpose, processing) allows, computed efficiently for whole libraries:
    grant key sets for plain items, the full policy call for source-linked ones (bounded by imported sources)."""
    if not ctx.allows("read"):
        return {}
    if purpose == "browse":
        return dict(items)
    grants = policy.active_grants(ctx)
    purpose_cover = _cover([g for g in grants if g["grantType"] == "purpose" and g["purpose"] == purpose])
    processing_cover = None
    if processing is not None and (processing["location"], processing["category"]) not in policy.LOCAL_DEFAULTS:
        processing_cover = _cover([g for g in grants if g["grantType"] == "processing" and g["location"] == processing["location"]
                                   and g["category"] == processing["category"]])
    memory_blocked = purpose == "memory" and (processing or {}).get("location") == "cloud" and memory.egress(ctx.state).get("cloud") is not True
    out = {}
    for key, item in items.items():
        if item["status"] not in READY_FOR_PURPOSE:
            continue
        if item.get("sourceId"):
            if policy.authorize_source(ctx, item, purpose, processing).allowed:
                out[key] = item
            continue
        if purpose in ("draft_evidence", "public_use") or memory_blocked:
            continue
        if processing_cover is not None and not _covered(processing_cover, item):
            continue
        if _covered(purpose_cover, item):
            out[key] = item
    return out


# --- filters and facets -------------------------------------------------------------------------------------------
def _date_bounds(filters: dict):
    if "createdFrom" not in filters and "createdTo" not in filters:
        return None, None
    try:
        zone = ZoneInfo(filters.get("timeZone", "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        c.fail("Use an IANA time zone such as Asia/Hong_Kong.")
    try:
        start = datetime.combine(date.fromisoformat(filters["createdFrom"]), dtime.min, tzinfo=zone).timestamp() if "createdFrom" in filters else None
        end = datetime.combine(date.fromisoformat(filters["createdTo"]) + timedelta(days=1), dtime.min, tzinfo=zone).timestamp() if "createdTo" in filters else None
    except ValueError:
        c.fail("Use real calendar dates such as 2026-10-08.")
    return start, end


def _rights(sources: dict, item) -> str | None:
    if not item.get("sourceId"):
        return "unknown"
    source = sources.get(item["sourceId"])
    if source is None:
        return "unknown"
    if not source.get("active") or source.get("sourcePolicy") == "prohibited":
        return None
    policy_name = source.get("sourcePolicy")
    if policy_name == "public_quote" or (policy_name == "rewrite_approval" and source_policy.use_approved(source)):
        return "approved_public"
    if policy_name == "internal_reference":
        return "internal"
    return "needs_review"


def _used_keys(ctx) -> set:
    phase2 = ctx.state.get("phase2") or {}
    used, job_keys = set(), set()
    for job in phase2.get("jobs") or []:
        manifest = job.get("manifest") or {}
        for value in (job.get("approvalDigest"), manifest.get("idempotencyKey")):
            if value:
                job_keys.add(value)
        used.update(m.get("id") for m in manifest.get("media") or [] if isinstance(m, dict) and m.get("id"))
    for review in phase2.get("reviews") or []:
        manifest = review.get("manifest") or {}
        if review.get("status") != "needs_review" or review.get("digest") in job_keys or manifest.get("idempotencyKey") in job_keys:
            continue
        used.update(m.get("id") for m in manifest.get("media") or [] if isinstance(m, dict) and m.get("id"))
    ctx.cur.execute(USAGE_SQL, {"w": ctx.workspace_id})
    used.update(r[0] for r in ctx.cur.fetchall())
    return used


class _Filters:
    """Evaluates contracts.filters against items; lookups run once per request."""

    def __init__(self, ctx, filters: dict):
        self.ctx, self.f = ctx, filters or {}
        self.start, self.end = _date_bounds(self.f)
        self.kinds = set(self.f.get("kinds") or [])
        self.tags = [textnorm.fold(t) for t in self.f.get("tags") or []]
        self.used = _used_keys(ctx) if "usage" in self.f else None
        self.members = _collection(ctx, self.f["collectionId"])[1] if "collectionId" in self.f else None
        self.languages = None
        if "languages" in self.f:
            ctx.cur.execute(LANGUAGES_SQL, {"w": ctx.workspace_id, "langs": list(self.f["languages"])})
            self.languages = {r[0] for r in ctx.cur.fetchall()}
        self.sources = None
        if "rights" in self.f:
            source_policy.stamp(ctx.state)
            self.sources = {s.get("id"): s for s in ctx.state.get("sources", []) if isinstance(s, dict)}
        self.capability = None
        if "capability" in self.f:
            ctx.cur.execute(CAPABILITY_FILTER_SQL, {"w": ctx.workspace_id, "cap": self.f["capability"]})
            self.capability = {k: s for k, s in ctx.cur.fetchall()}

    def passes(self, item, skip=()) -> bool:
        f = self.f
        if self.kinds and "kinds" not in skip and item["kind"] not in self.kinds:
            return False
        if self.tags and "tags" not in skip:
            have = {textnorm.fold(t) for t in item.get("tags") or []}
            if not all(t in have for t in self.tags):
                return False
        if self.start is not None and item["createdAt"] < self.start:
            return False
        if self.end is not None and item["createdAt"] >= self.end:
            return False
        if self.sources is not None and _rights(self.sources, item) != f["rights"]:
            return False
        if self.used is not None and ((item["versionId"] in self.used or item["assetId"] in self.used) != (f["usage"] == "used")):
            return False
        media = item.get("media") or {}
        if "orientation" in f:
            w, h = media.get("width"), media.get("height")
            if not isinstance(w, (int, float)) or not isinstance(h, (int, float)) or w <= 0 or h <= 0:
                return False
            ratio = w / h
            shape = "square" if abs(ratio - 1) <= 0.01 else ("landscape" if ratio > 1 else "portrait")
            if shape != f["orientation"]:
                return False
        if "minDurationMs" in f or "maxDurationMs" in f:
            duration = media.get("durationMs")
            if not isinstance(duration, (int, float)):
                return False
            if duration < f.get("minDurationMs", 0) or duration > f.get("maxDurationMs", float("inf")):
                return False
        if self.members is not None and not _in_members(item, self.members):
            return False
        if self.languages is not None and item["versionId"] not in self.languages:
            return False
        if self.capability is not None:
            state = self.capability.get(item["versionId"]) or self.capability.get(item["assetId"]) or "not_requested"
            if state != f["capabilityState"]:
                return False
        return True


def _facets(filters: _Filters, items: dict) -> dict:
    kinds, tags = {}, {}
    for item in items.values():
        if filters.passes(item, skip=("kinds",)):
            kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
        if filters.passes(item, skip=("tags",)):
            for tag in dict.fromkeys(item.get("tags") or []):
                tags[tag] = tags.get(tag, 0) + 1
    top = sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))[:30]
    return {"kinds": dict(sorted(kinds.items())), "tags": dict(top)}


# --- index statistics (server-side coverage, cursor watermarks) ---------------------------------------------------
def _stats(ctx, snapshot: float) -> dict:
    cache = ctx.caches.setdefault("searchStats", {})
    if snapshot in cache:
        return cache[snapshot]
    ctx.cur.execute(SEGMENT_STATS_SQL, {"w": ctx.workspace_id, "t": snapshot, "nv": textnorm.NORMALIZER_VERSION})
    segmented, segment_rows = {}, 0
    for key, current_norm, count in ctx.cur.fetchall():
        segmented[key] = bool(current_norm)
        segment_rows += int(count)
    ctx.cur.execute(EMBEDDING_STATS_SQL, {"w": ctx.workspace_id, "t": snapshot})
    embedded, embedding_rows = {}, 0
    for key, modality, model, dims, generation, count in ctx.cur.fetchall():
        embedded.setdefault(key, {})[(modality, model, int(dims), int(generation))] = int(count)
        embedding_rows += int(count)
    ctx.cur.execute(CAPABILITY_STATS_SQL, {"w": ctx.workspace_id})
    capabilities: dict = {}
    for key, capability, state in ctx.cur.fetchall():
        capabilities.setdefault(key, {})[capability] = state
    cache[snapshot] = {"segmented": segmented, "segmentRows": segment_rows, "embedded": embedded, "embeddingRows": embedding_rows,
                       "capabilities": capabilities}
    return cache[snapshot]


def _has_embedding(stats, item, signature) -> int:
    return (stats["embedded"].get(item["versionId"]) or {}).get(signature, 0)


def _text_index(stats, item) -> bool:
    if stats["segmented"].get(item["versionId"]) is True:
        return True
    return item["versionId"] not in stats["segmented"] and not item.get("legacy") and item.get("indexingStatus") == "ready"


def _states(stats, item) -> dict:
    out = dict(stats["capabilities"].get(item["assetId"]) or {})
    out.update(stats["capabilities"].get(item["versionId"]) or {})
    return out


def _coverage_counts(items: dict, stats: dict, generation: int) -> dict:
    indexed = pending = failed = 0
    visual_signature = ("visual", index.VISUAL_MODEL, index.VISUAL_DIMS, generation)
    for item in items.values():
        embedded = stats["embedded"].get(item["versionId"]) or {}
        if _text_index(stats, item) or any(sig[0] == "text" and sig[3] == generation for sig in embedded) or visual_signature in embedded:
            indexed += 1
        states = _states(stats, item)
        if (item["status"] in PENDING_STATUSES or item.get("pendingVersion") or stats["segmented"].get(item["versionId"]) is False
                or any(states.get(cap) in ("queued", "processing") for cap in WATCHED_CAPABILITIES)):
            pending += 1
        if item["status"] == "failed" or any(states.get(cap) == "failed" for cap in WATCHED_CAPABILITIES):
            failed += 1
    return {"accessible": len(items), "indexed": indexed, "pending": pending, "failed": failed}


# --- ranking ------------------------------------------------------------------------------------------------------
def rrf(lists, k: int = RRF_K, weights=None) -> list:
    """Reciprocal-rank fusion: score = Σ weight/(k + rank). Ties keep first appearance (list order, then rank)."""
    scores, first = {}, {}
    for li, keys in enumerate(lists):
        weight = 1.0 if weights is None else weights[li]
        for rank, key in enumerate(keys, 1):
            scores[key] = scores.get(key, 0.0) + weight / (k + rank)
            first.setdefault(key, (li, rank))
    return sorted(scores, key=lambda key: (-scores[key], first[key]))


def _exact(query: str, items: dict) -> list[tuple[str, dict]]:
    """Identity matches in priority order: id, content-hash prefix, filename, title, dimensions."""
    q = unicodedata.normalize("NFKC", query).strip()
    folded = q.casefold()
    if not folded:
        return []
    found: list[tuple[str, dict]] = []
    seen = set()

    def add(keys, reason):
        for key in sorted(keys, key=lambda k: (-items[k]["createdAt"], k)):
            if key not in seen:
                seen.add(key)
                found.append((key, reason))

    newest = items.items()
    if UUIDISH.fullmatch(folded):
        target = folded.replace("-", "")
        add([k for k, v in newest if target in (v["versionId"], v["assetId"])], {"kind": "id", "detail": "Library item id"})
    if HEX_PREFIX.fullmatch(folded):
        add([k for k, v in newest if v.get("sha256") and v["sha256"].startswith(folded)], {"kind": "hash", "detail": "content hash"})
    add([k for k, v in newest if (v.get("filename") or "").casefold() == folded or (v.get("filename") or "").rsplit(".", 1)[0].casefold() == folded],
        {"kind": "filename", "detail": "exact filename"})
    add([k for k, v in newest if not v.get("genericTitle") and (v.get("title") or "").strip().casefold() == folded], {"kind": "title", "detail": "exact title"})
    dims = DIMENSIONS.fullmatch(folded)
    if dims:
        w, h = int(dims.group(1)), int(dims.group(2))
        add([k for k, v in newest if (v.get("media") or {}).get("width") == w and (v.get("media") or {}).get("height") == h],
            {"kind": "dimensions", "detail": f"{w}×{h}"})
    return found


def _metadata_text(item) -> str:
    media = item.get("media") or {}
    dims = f"{media['width']}x{media['height']}" if isinstance(media.get("width"), int) and isinstance(media.get("height"), int) else ""
    title = "" if item.get("genericTitle") else (item.get("title") or "")
    return " ".join([title, item.get("filename") or "", " ".join(item.get("tags") or []), dims])


def _metadata_matches(terms: list[str], items: dict) -> list[tuple[str, dict]]:
    if not terms:
        return []
    scored = []
    for key, item in items.items():
        text = _metadata_text(item)
        folded = textnorm.fold(text)
        if not all(t in folded for t in terms):  # cheap prefilter; whole-term check below
            continue
        tokens = set(textnorm.tokens(text))
        if not all(t in tokens for t in terms):
            continue
        title_tokens = set() if item.get("genericTitle") else set(textnorm.tokens(item.get("title") or ""))
        in_title = all(t in title_tokens for t in terms)
        tag_tokens = set(textnorm.tokens(" ".join(item.get("tags") or [])))
        kind = "title" if in_title else ("tag" if all(t in tag_tokens for t in terms) else "filename")
        scored.append((0 if in_title else 1, -item["createdAt"], key, {"kind": kind, "detail": "name and labels"}))
    scored.sort()
    return [(key, reason) for _, _, key, reason in scored[:LEXICAL_K]]


def _latin_tsquery(terms: list[str]) -> str | None:
    parts = []
    for t in terms:
        if textnorm.CJK.match(t):
            continue
        parts += [p for p in re.sub(r"[^0-9a-zà-ɏ']", "", t).split("'") if p]
    parts = list(dict.fromkeys(parts))
    return " & ".join(parts) if parts else None


_VARIANTS: dict = {}
for _source, _target in textnorm.S2T.items():
    _VARIANTS.setdefault(_target, {_target}).add(_source)


def _cjk_patterns(query: str) -> list[str]:
    """Phrase regexes for legacy chunk text: each CJK run, every character widened to its folding class (会|會)."""
    text = unicodedata.normalize("NFKC", query).casefold()
    out = []
    for match in textnorm.TOKEN.finditer(text):
        run = match.group(0)
        if not textnorm.CJK.match(run):
            continue
        parts = []
        for ch in run:
            options = sorted(_VARIANTS.get(textnorm.fold(ch), {ch}) | {ch})
            parts.append(re.escape(ch) if len(options) == 1 else "[" + "".join(options) + "]")
        out.append("".join(parts))
    return list(dict.fromkeys(out))[:16]


def _lexical(ctx, query: str, items: dict, stats: dict, snapshot: float) -> dict:
    terms = textnorm.query_terms(query)
    tsq = textnorm.tsquery(query)
    keys = sorted(items)
    segment_list, chunk_list, reasons, passages = [], [], {}, {}
    bound, matched = False, 0
    if tsq and keys:
        ctx.cur.execute(LEXICAL_SEGMENTS_SQL, {"tsq": tsq, "w": ctx.workspace_id, "nv": textnorm.NORMALIZER_VERSION, "t": snapshot, "keys": keys, "k": LEXICAL_K})
        for key, segment_id, _rank, total in ctx.cur.fetchall():
            segment_list.append(key)
            passages[key] = {"segment": segment_id}
            reasons.setdefault(key, []).append({"kind": "lexical", "detail": "passage"})
            matched = int(total)
        bound = matched > LEXICAL_K
    unsegmented = [k for k in keys if k not in stats["segmented"] and not items[k].get("legacy") and items[k].get("indexingStatus") == "ready"]
    latin, patterns = _latin_tsquery(terms), _cjk_patterns(query)
    if unsegmented and (latin or patterns):
        ctx.cur.execute(LEXICAL_CHUNKS_SQL, {"tsq": latin, "w": ctx.workspace_id, "ids": [str(uuid.UUID(hex=k)) for k in unsegmented], "rx": patterns, "k": LEXICAL_K})
        for key, ordinal, _rank, total in ctx.cur.fetchall():
            chunk_list.append(key)
            passages.setdefault(key, {"chunk": int(ordinal)})
            reasons.setdefault(key, []).append({"kind": "lexical", "detail": LEGACY_INDEX})
            bound = bound or int(total) > LEXICAL_K
    metadata = _metadata_matches(terms, items)
    for key, reason in metadata:
        reasons.setdefault(key, []).append(reason)
    ordered = rrf([segment_list, [k for k, _ in metadata], chunk_list])[:LEXICAL_K]
    return {"keys": ordered, "reasons": reasons, "passages": passages, "bound": bound, "matched": max(matched, len(ordered)), "tsq": tsq}


def _set_local(cur, statement: str):
    try:
        cur.execute("SAVEPOINT lib_guc")
    except Exception:
        return
    try:
        cur.execute(statement)
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT lib_guc")
    else:
        cur.execute("RELEASE SAVEPOINT lib_guc")


def _knn(ctx, sql: str, params: dict, available_rows: int):
    """HNSW kNN with iterative scan where pgvector supports it (guarded); an exact scan when the approximate index
    returned fewer neighbours than this scope holds. Any database error rolls back to a savepoint and returns None."""
    cur = ctx.cur
    _set_local(cur, "SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
    _set_local(cur, f"SET LOCAL hnsw.ef_search = {min(1000, max(40, 2 * int(params['k'])))}")
    try:
        cur.execute("SAVEPOINT lib_knn")
        savepoint = True
    except Exception:
        savepoint = False
    try:
        cur.execute(sql.format(open="", close=""), params)
        rows, method = cur.fetchall(), "hnsw"
        if len(rows) < min(int(params["k"]), available_rows):
            cur.execute(sql.format(open="(", close=") + 0"), params)
            rows, method = cur.fetchall(), "exact"
    except Exception:
        if savepoint:
            cur.execute("ROLLBACK TO SAVEPOINT lib_knn")
        return None, None
    if savepoint:
        cur.execute("RELEASE SAVEPOINT lib_knn")
    return sorted(rows, key=lambda r: (float(r[2]), r[0])), method


def _semantic(ctx, query: str, items: dict, stats: dict, snapshot: float, generation: int) -> dict:
    if not index.vector_available_ctx(ctx):
        raise _Unavailable("Meaning-based search is not installed on this database yet, so results use exact and keyword matching only.")
    prov = index.providers_for(ctx)
    try:
        prov.require("embedding")
    except providers.ProviderUnavailable:
        raise _Unavailable("Meaning-based search isn't enabled here, so results use exact and keyword matching only.") from None
    signature = ("text", prov.model("embedding"), index.TEXT_DIMS, generation)
    keys = sorted(k for k, v in items.items() if _has_embedding(stats, v, signature))
    if not keys:
        raise _Unavailable("Nothing in this scope has a meaning index yet, so results use exact and keyword matching only.")
    try:
        vector, model = index.embed_query(ctx, query)
    except providers.ProviderUnavailable as error:
        if error.reason == "blocked_budget":
            raise _Unavailable("Meaning-based search is paused by the workspace budget, so results use exact and keyword matching only.") from None
        raise _Unavailable("Meaning-based search isn't available right now, so results use exact and keyword matching only.") from None
    except AlphaError:
        raise _Unavailable("Meaning-based search failed for this request, so results use exact and keyword matching only.") from None
    available = sum(_has_embedding(stats, items[k], signature) for k in keys)
    rows, method = _knn(ctx, KNN_TEXT_SQL, {"vec": index.vector_literal(vector), "w": ctx.workspace_id, "modality": "text", "dims": index.TEXT_DIMS,
                                            "model": model, "gen": generation, "t": snapshot, "keys": keys, "k": SEMANTIC_K}, available)
    if rows is None:
        raise _Unavailable("Meaning-based search failed for this request, so results use exact and keyword matching only.")
    ordered, passages = [], {}
    for key, segment_id, _distance in rows:
        if key not in passages:
            ordered.append(key)
            passages[key] = {"segment": segment_id} if segment_id else {}
    reason = {"kind": "semantic", "detail": f"related meaning ({model})"}
    return {"keys": ordered, "reasons": {k: [reason] for k in ordered}, "passages": passages, "bound": len(rows) >= SEMANTIC_K,
            "method": method, "model": model, "missing": sum(1 for v in items.values() if _text_index(stats, v) and not _has_embedding(stats, v, signature))}


def _visual(ctx, similar, query: str, items: dict, stats: dict, snapshot: float, generation: int) -> dict:
    if similar is None:
        raise _Unavailable("Searching images by a description needs the optional cloud multimodal model, which is not enabled. "
                           "Choose an example image for visual similarity instead.")
    example = versions.resolve(ctx, similar)
    if not index.vector_available_ctx(ctx):
        raise _Unavailable("Visual similarity is not installed on this database yet.")
    ctx.cur.execute(VISUAL_REFERENCE_SQL, {"w": ctx.workspace_id, "key": example["versionId"], "model": index.VISUAL_MODEL, "dims": index.VISUAL_DIMS, "gen": generation})
    row = ctx.cur.fetchone()
    if not row:
        raise _Unavailable("This example has no visual index yet, so visual similarity can't run for it.")
    signature = ("visual", index.VISUAL_MODEL, index.VISUAL_DIMS, generation)
    keys = sorted(k for k, v in items.items() if k != example["versionId"] and _has_embedding(stats, v, signature))
    missing = sum(1 for v in items.values() if v.get("kind") in ("image", "video") and not _has_embedding(stats, v, signature))
    reason = {"kind": "visual", "detail": f"visual similarity ({index.VISUAL_MODEL})"}
    if not keys:
        return {"keys": [], "reasons": {}, "passages": {}, "bound": False, "method": "none", "missing": missing}
    available = sum(_has_embedding(stats, items[k], signature) for k in keys)
    rows, method = _knn(ctx, KNN_VISUAL_SQL, {"vec": row[0], "w": ctx.workspace_id, "modality": "visual", "dims": index.VISUAL_DIMS, "model": index.VISUAL_MODEL,
                                              "gen": generation, "t": snapshot, "keys": keys, "k": VISUAL_K}, available)
    if rows is None:
        raise _Unavailable("Visual similarity failed for this request.")
    ordered = list(dict.fromkeys(r[0] for r in rows))
    return {"keys": ordered, "reasons": {k: [reason] for k in ordered}, "passages": {}, "bound": len(rows) >= VISUAL_K, "method": method, "missing": missing}


# --- snippets and hydration ---------------------------------------------------------------------------------------
def _clean(text: str) -> str:
    text = TAG.sub(" ", str(text or ""))
    text = TAG.sub(" ", html.unescape(text))
    text = CONTROL.sub("", text)
    return SPACE.sub(" ", text).strip()


def _match_position(text: str, query: str) -> int | None:
    folded, positions = [], []
    for i, ch in enumerate(text):
        f = textnorm.fold(ch)
        folded.append(f)
        positions += [i] * len(f)
    haystack = "".join(folded)
    candidates = [textnorm.fold(query).strip(), *textnorm.query_terms(query)]
    best = None
    for needle in candidates:
        if needle:
            found = haystack.find(needle)
            if found >= 0 and (best is None or found < best):
                best = found
                if needle == candidates[0]:
                    break
    return positions[best] if best is not None and best < len(positions) else None


def snippet(text: str, query: str, chars: int = SNIPPET_CHARS) -> str:
    """Sanitised plain-text window around the first match (markup, control and bidi characters removed)."""
    clean = _clean(text)
    if len(clean) <= chars:
        return clean
    pos = _match_position(clean, query) if query else None
    if pos is None:
        return clean[:chars].rstrip() + "…"
    start = max(0, pos - chars // 3)
    end = min(len(clean), start + chars)
    start = max(0, end - chars)
    return ("…" if start > 0 else "") + clean[start:end].strip() + ("…" if end < len(clean) else "")


def _locator(value):
    value = _json(value) if isinstance(value, str) else value
    if not isinstance(value, dict):
        return None
    try:
        return c.locator(value)
    except AlphaError:
        return None  # an unverifiable locator is dropped, never invented


def _passage(segment_id, text, locator, kind, language, query, chars) -> dict:
    loc = _locator(locator)
    out = {"segmentId": segment_id, "snippet": snippet(text, query, chars), "kind": kind, "_text": text}
    if loc:
        out.update(locator=loc, locatorLabel=c.locator_label(loc))
    if language:
        out["language"] = language
    return out


def _hydrate_passages(ctx, page: list, query: str, ranked: dict, tsq, snapshot: float, chars: int) -> dict:
    out: dict = {k: [] for k in page}
    lexical_keys = [k for k in page if (ranked["lexical"].get(k) or {}).get("segment")]
    if tsq and lexical_keys:
        ctx.cur.execute(PASSAGES_SQL, {"tsq": tsq, "w": ctx.workspace_id, "keys": lexical_keys, "nv": textnorm.NORMALIZER_VERSION, "t": snapshot, "per": PASSAGES_PER_HIT})
        rows = sorted(ctx.cur.fetchall(), key=lambda r: (r[0], -float(r[6] or 0), r[7]))
        for key, segment_id, text, locator, kind, language, _rank, _ordinal in rows:
            if key in out and len(out[key]) < PASSAGES_PER_HIT:
                out[key].append(_passage(segment_id, text, locator, kind, language, query, chars))
    wanted = {}
    for k in page:
        if not out[k]:
            segment = (ranked["semantic"].get(k) or {}).get("segment") or (ranked["lexical"].get(k) or {}).get("segment")
            if segment:
                wanted[segment] = k
    if wanted:
        ctx.cur.execute(SEGMENTS_BY_ID_SQL, {"w": ctx.workspace_id, "ids": [str(uuid.UUID(hex=s)) for s in wanted]})
        for key, segment_id, text, locator, kind, language, _ordinal in ctx.cur.fetchall():
            if wanted.get(segment_id) == key and key in out and not out[key]:
                out[key].append(_passage(segment_id, text, locator, kind, language, query, chars))
    chunks = {k: (ranked["lexical"].get(k) or {}).get("chunk") for k in page if not out[k] and (ranked["lexical"].get(k) or {}).get("chunk") is not None}
    if chunks:
        ctx.cur.execute(CHUNK_PASSAGES_SQL, {"w": ctx.workspace_id, "ids": [str(uuid.UUID(hex=k)) for k in chunks]})
        for key, ordinal, text in ctx.cur.fetchall():
            if key in chunks and int(ordinal) == chunks[key] and not out[key]:
                out[key].append({"segmentId": None, "snippet": snippet(text, query, chars), "kind": "legacy_chunk", "_text": text})
    return out


def _capabilities(ctx, page_items: list) -> dict:
    keys = sorted({k for item in page_items for k in (item["versionId"], item["assetId"])})
    if not keys:
        return {}
    ctx.cur.execute(HIT_CAPABILITIES_SQL, {"w": ctx.workspace_id, "keys": keys})
    out: dict = {}
    for key, capability, state, code, detail, retryable, progress, processor, updated in ctx.cur.fetchall():
        try:
            entry = c.capability_state(capability, state, errorCode=code, detail=detail, retryable=bool(retryable), progress=_json(progress) or None,
                                       processorVersion=processor, updatedAt=float(updated) if updated is not None else None)
        except AlphaError:
            continue
        out.setdefault(key, {})[capability] = entry
    return out


def _source_status(purpose, decision) -> dict:
    if decision is None:
        return {"purpose": purpose, "allowed": True, "reason": None, "attributionOnly": False, "candidateOnly": False}
    return {"purpose": purpose, "allowed": decision.allowed, "reason": decision.reason, "attributionOnly": decision.attribution_only,
            "candidateOnly": decision.candidate_only}


# --- entry points ---------------------------------------------------------------------------------------------------
def _snapshot(ctx) -> float:
    """The database clock (transaction start), the same clock that stamps assets, segments and embeddings."""
    ctx.cur.execute(CLOCK_SQL)
    row = ctx.cur.fetchone()
    return float(row[0]) if row and row[0] is not None else float(ctx.now)


def search_library(ctx, request, *, processing: dict | None = None, passage_chars: int = SNIPPET_CHARS) -> dict:
    """The shared Library search. `processing` (in-process callers only, e.g. the Agent adapter) additionally requires a
    processing grant such as cloud/llm before an item is eligible; it is bound into the cursor."""
    ctx.require("read")
    request = c.search_request(request)
    if processing is not None:
        processing = c.processing_grant(processing)
    if not policy.enabled("retrieval"):
        raise AlphaError("Library search is not enabled in this environment.", 503, code="library_retrieval_disabled")
    passage_chars = max(80, min(int(passage_chars), MAX_PASSAGE_CHARS))
    revs = policy.revisions(ctx)
    generation, query, purpose = revs["indexGeneration"], request["query"], request["purpose"]
    binding = cursors.binding(workspace_id=ctx.workspace_id, actor=ctx.actor, request={**request, "processing": processing},
                              index_generation=generation, grant_revision=revs["grantRevision"], normalizer_version=textnorm.NORMALIZER_VERSION,
                              ranking_version=RANKING_VERSION)
    page_state = cursors.decode(request["cursor"], binding_digest=binding, now=ctx.now) if request["cursor"] else None
    snapshot = page_state["snapshot"] if page_state else _snapshot(ctx)
    offset = page_state["offset"] if page_state else 0
    query_id = page_state["queryId"] if page_state else uuid.uuid4().hex

    current, _rows = universe(ctx)
    scoped, scope_description = _scope(ctx, request["scope"], current)
    scoped = {k: v for k, v in scoped.items() if v["createdAt"] <= snapshot}
    eligible = eligible_items(ctx, purpose, scoped, processing)
    filters = _Filters(ctx, request["filters"])
    items = {k: v for k, v in eligible.items() if filters.passes(v)}
    facets = _facets(filters, eligible)
    stats = _stats(ctx, snapshot)
    fingerprint = cursors.fingerprint(items, stats["segmentRows"], stats["embeddingRows"])
    if page_state:
        cursors.check_fingerprint(page_state, fingerprint)

    warnings, applied, bounds = [], [], []
    ranked = {"lexical": {}, "semantic": {}, "visual": {}}
    reasons: dict = {}
    mode_lists = []
    missing_index = 0
    semantic_model = None
    requested = request["modes"]
    exact = _exact(query, items) if query else []
    for key, reason in exact:
        reasons.setdefault(key, []).append(reason)
    lexical_tsq = None
    lexical_matched = None
    if query and "lexical" in requested:
        lexical = _lexical(ctx, query, items, stats, snapshot)
        applied.append("lexical")
        lexical_tsq, lexical_matched = lexical["tsq"], lexical["matched"]
        mode_lists.append(lexical["keys"])
        ranked["lexical"] = lexical["passages"]
        for key, rs in lexical["reasons"].items():
            reasons.setdefault(key, []).extend(rs)
        if lexical["bound"]:
            bounds.append("lexical")
    if query and "semantic" in requested:
        try:
            semantic = _semantic(ctx, query, items, stats, snapshot, generation)
        except _Unavailable as error:
            warnings.append(str(error))
        else:
            applied.append("semantic")
            semantic_model = semantic["model"]
            mode_lists.append(semantic["keys"])
            ranked["semantic"] = semantic["passages"]
            for key, rs in semantic["reasons"].items():
                reasons.setdefault(key, []).extend(rs)
            missing_index += semantic["missing"]
            if semantic["bound"]:
                bounds.append("semantic")
    if "visual" in requested and (request["similarTo"] is not None or query):
        try:
            visual = _visual(ctx, request["similarTo"], query, items, stats, snapshot, generation)
        except _Unavailable as error:
            warnings.append(str(error))
        else:
            applied.append("visual")
            mode_lists.append(visual["keys"])
            for key, rs in visual["reasons"].items():
                reasons.setdefault(key, []).extend(rs)
            missing_index += visual["missing"]
            if visual["bound"]:
                bounds.append("visual")
    applicable = [m for m in requested if (m in ("lexical", "semantic") and query) or (m == "visual" and (query or request["similarTo"] is not None))]
    missing_modes = [m for m in applicable if m not in applied]

    if query or request["similarTo"] is not None:
        exact_keys = [k for k, _ in exact]
        exact_set = set(exact_keys)
        fused = [k for k in rrf(mode_lists) if k not in exact_set]
        ordered = exact_keys + fused
    else:
        ordered = sorted(items, key=lambda k: (-items[k]["createdAt"], k))

    counts = _coverage_counts(items, stats, generation)
    if missing_index and query:
        warnings.append(f"{missing_index} item{'s' if missing_index != 1 else ''} in this scope "
                        f"{'are' if missing_index != 1 else 'is'} not yet in the {'meaning' if 'semantic' in applied else 'visual'} index.")
    if bounds:
        warnings.append("Ranking considered the top " + ", ".join(f"{CANDIDATE_LIMITS[m]:,} {m}" for m in bounds)
                        + " candidates; refine the search to reach the rest.")
    if counts["pending"] and (query or request["similarTo"] is not None):
        warnings.append(f"{counts['pending']} item{'s are' if counts['pending'] != 1 else ' is'} still being processed and may be missing from these results.")
    if counts["failed"] and (query or request["similarTo"] is not None):
        warnings.append(f"{counts['failed']} item{'s' if counts['failed'] != 1 else ''} could not be fully processed; their content may be unsearchable.")
    searching = bool(query or request["similarTo"] is not None)
    partial = bool(missing_modes or bounds or (searching and (missing_index or counts["pending"] or counts["failed"])))

    page_keys = ordered[offset:offset + request["limit"]]
    page_items = [items[k] for k in page_keys]
    decisions = None
    if purpose != "browse":
        decisions = [policy.authorize_source(ctx, item, purpose, processing) for item in page_items]
        decisions = policy.recheck(ctx, decisions)
        kept = [(item, d) for item, d in zip(page_items, decisions) if d.allowed]
        if len(kept) != len(page_items):
            warnings.append("Permissions changed while searching; some items were withheld. Refresh to see current results.")
        page_items, decisions = [item for item, _ in kept], [d for _, d in kept]
    passages = _hydrate_passages(ctx, [i["versionId"] for i in page_items], query, ranked, lexical_tsq, snapshot, passage_chars)
    capability_states = _capabilities(ctx, page_items)
    hits = []
    for position, item in enumerate(page_items):
        key = item["versionId"]
        found = passages.get(key) or []
        best = found[0] if found else None
        states = dict(capability_states.get(item["assetId"]) or {})
        states.update(capability_states.get(key) or {})
        hit = {"assetRef": versions.ref(item), "displayTitle": item.get("title") or item.get("filename") or "Untitled", "kind": item["kind"],
               "mime": item.get("mime") or "application/octet-stream", "snippet": snippet(best["_text"], query) if best else "",
               "matchReasons": _dedupe(reasons.get(key) or []), "capabilities": [states[k] for k in sorted(states)],
               "sourceStatus": _source_status(purpose, decisions[position] if decisions is not None else None), "createdAt": item["createdAt"],
               "sourceId": item.get("sourceId"), "passages": [{k: v for k, v in p.items() if k != "_text"} for p in found]}
        if best and best.get("segmentId"):
            hit["segmentId"] = best["segmentId"]
        if best and best.get("locator"):
            hit.update(locator=best["locator"], locatorLabel=best["locatorLabel"])
        hits.append(hit)

    more = offset + request["limit"] < len(ordered)
    next_cursor = cursors.encode(binding_digest=binding, snapshot=snapshot, offset=offset + request["limit"], fingerprint_value=fingerprint,
                                 query_id=query_id) if more else None
    if processing is not None:
        scope_description += f" (items allowed for {processing['location']} {processing['category']} processing)"
    coverage = c.coverage(scope_description=scope_description, accessible=counts["accessible"], indexed=counts["indexed"], pending=counts["pending"],
                          failed=counts["failed"], modes_applied=applied, partial=partial, index_generation=generation)
    total_value = len(ordered)
    if lexical_matched is not None:
        total_value = max(total_value, lexical_matched)
    return {"contractVersion": c.CONTRACT_VERSION, "queryId": query_id, "hits": hits, "nextCursor": next_cursor, "coverage": coverage, "facets": facets,
            "totalHits": {"value": total_value, "relation": "gte" if bounds else "eq"},
            "ranking": {"version": RANKING_VERSION, "k": RRF_K, "weights": dict(WEIGHTS), "exactFirst": True, "orderOnly": True,
                        "candidateLimits": dict(CANDIDATE_LIMITS), "boundsReached": bounds,
                        "semanticModel": semantic_model, "visualModel": index.VISUAL_MODEL if "visual" in applied else None,
                        "normalizerVersion": textnorm.NORMALIZER_VERSION},
            "warnings": list(dict.fromkeys(w for w in warnings if w))}


def _dedupe(reasons: list) -> list:
    seen, out = set(), []
    for reason in reasons:
        marker = (reason.get("kind"), reason.get("detail"))
        if marker not in seen:
            seen.add(marker)
            out.append(reason)
    return out


def search_http(ctx, request) -> dict:
    """POST …/library/intelligence/search — the body is a SearchRequest; identity comes from the verified context."""
    return search_library(ctx, c.search_request(request.get("body") or {}))
