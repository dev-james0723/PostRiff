"""Explicit asset relations, version lineage and dependent-draft warnings (engineering spec §4 AssetRelation, §9; PRD R10,
D3; T06).

Relations live in pr_library_relations and always name the exact content versions they connect:

    derived_from  excerpt/rendition -> original          (lineage: acyclic)
    version_of    newer version -> older version         (lineage: acyclic; also restacks the newer row)
    supersedes    newer version -> older version         (lineage: acyclic; flags dependents of the older one)
    used_in       version -> draft/post/source_pack/idea (citation; 'stale' when a newer version exists)
    similar_to    version <-> version                    (status 'suggested' only; never a version identity)

Lineage stays acyclic across all three lineage kinds, checked by a bounded breadth-first walk (depth 50, 500 nodes) that
fails closed past its bounds. Linking a newer version never rewrites an old citation: it marks dependents stale, records
an 'outdated_source' suggestion and waits for the user to accept a replacement for one dependent at a time, with a
revision check, keeping the replaced citation retrievable in the relation history. Near duplicates are suggestions from
local perceptual vectors; nothing is ever merged, hidden or deleted here.
"""
from __future__ import annotations

import json
import re
import uuid

from postriff_alpha.domain import AlphaError

from . import contracts as c
from . import policy, versions

LINEAGE = ("derived_from", "version_of", "supersedes")
DEPENDENT_KINDS = ("draft", "post", "source_pack", "idea")
LINKABLE = ("derived_from", "version_of", "supersedes", "used_in")
MAX_DEPTH, MAX_NODES = 50, 500
MAX_RELATED = 200
MAX_DEPENDENTS = 200
MAX_STACK = 50
NEAR_MODEL = "local/visual-perceptual-v1"
NEAR_DISTANCE = 0.05  # cosine distance on the 256-d local perceptual vector; tune with evidence, never auto-merge
NEAR_LIMIT = 10
HIDDEN = ("deleting", "duplicate", "missing")
TO_KEY = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")
PUBLIC_EVIDENCE = ("method", "distance", "reason", "via", "note", "supersededBy", "replacedBy", "replaces", "replacementAccepted", "previousRefs",
                   "packRevision", "pendingSourceReview")
DEPENDENT_LABELS = {"source_pack": "source pack", "draft": "draft", "idea": "imported source", "post": "post"}

REL_COLS = ("id::text,from_key,from_version,from_segment::text,to_kind,to_key,to_version,relation,status,origin,evidence,"
            "extract(epoch from created_at)")
REL_INSERT = ("/*lio:rel.insert*/ INSERT INTO public.pr_library_relations(id,workspace_id,from_key,from_version,from_segment,to_kind,to_key,"
              "to_version,relation,status,origin,evidence,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) "
              "ON CONFLICT DO NOTHING RETURNING id::text")
REL_FIND = ("/*lio:rel.find*/ SELECT id::text,status,evidence FROM public.pr_library_relations WHERE workspace_id=%s AND from_version=%s "
            "AND relation=%s AND to_kind=%s AND to_key=%s AND coalesce(to_version,'')=%s AND from_segment IS NULL ORDER BY created_at LIMIT 1 FOR UPDATE")
REL_SET = ("/*lio:rel.set*/ UPDATE public.pr_library_relations SET status=%s,evidence=evidence||%s::jsonb,updated_at=now() "
           "WHERE workspace_id=%s AND id=%s")
REL_STALE_USED = ("/*lio:rel.stale_used*/ UPDATE public.pr_library_relations SET status='stale',"
                  "evidence=CASE WHEN status='active' THEN evidence||%s::jsonb ELSE evidence END,"
                  "updated_at=CASE WHEN status='active' THEN now() ELSE updated_at END WHERE workspace_id=%s AND from_version=%s "
                  "AND relation='used_in' AND status IN ('active','stale') RETURNING id::text,to_kind,to_key")
REL_OUT = ("/*lio:rel.out*/ SELECT from_version,to_version FROM public.pr_library_relations WHERE workspace_id=%s AND to_kind='asset' "
           "AND relation=ANY(%s) AND status='active' AND from_version=ANY(%s) AND to_version IS NOT NULL LIMIT 2000")
REL_IN = ("/*lio:rel.in*/ SELECT from_version,to_version FROM public.pr_library_relations WHERE workspace_id=%s AND to_kind='asset' "
          "AND relation=ANY(%s) AND status='active' AND to_version=ANY(%s) LIMIT 2000")
REL_LIST_OUT = (f"/*lio:rel.list_out*/ SELECT {REL_COLS} FROM public.pr_library_relations WHERE workspace_id=%s AND from_version=ANY(%s) "
                "ORDER BY created_at DESC LIMIT %s")
REL_LIST_IN = (f"/*lio:rel.list_in*/ SELECT {REL_COLS} FROM public.pr_library_relations WHERE workspace_id=%s AND to_kind='asset' "
               "AND to_version=ANY(%s) ORDER BY created_at DESC LIMIT %s")
ASSET_LOCK = ("/*lio:asset.lock*/ SELECT replace(id::text,'-',''),replace(coalesce(lineage_id,id)::text,'-',''),version_no "
              "FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s FOR UPDATE")
ASSET_CHILDREN = "/*lio:asset.children*/ SELECT count(*) FROM public.pr_library_assets WHERE workspace_id=%s AND lineage_id=%s AND id<>lineage_id"
ASSET_MAXVER = "/*lio:asset.maxver*/ SELECT coalesce(max(version_no),0) FROM public.pr_library_assets WHERE workspace_id=%s AND coalesce(lineage_id,id)=%s"
ASSET_RESTACK = ("/*lio:asset.restack*/ UPDATE public.pr_library_assets SET lineage_id=%s,version_no=%s,updated_at=now() WHERE workspace_id=%s "
                 "AND id=%s AND (lineage_id IS NULL OR lineage_id=id) RETURNING version_no")
PACKS_CITING = ("/*lio:packs.citing*/ SELECT id::text,revision,status,draft_id,created_by::text,evidence_refs,style_refs FROM public.pr_library_source_packs "
                "WHERE workspace_id=%s AND status IN ('draft','attached') AND (strpos(evidence_refs::text,%s)>0 OR strpos(style_refs::text,%s)>0) "
                "ORDER BY created_at LIMIT %s")
PACK_LOCK = ("/*lio:pack.lock*/ SELECT id::text,revision,status,evidence_refs,style_refs,rights_warnings,draft_id FROM public.pr_library_source_packs "
             "WHERE workspace_id=%s AND id=%s FOR UPDATE")
PACK_REPLACE = ("/*lio:pack.replace*/ UPDATE public.pr_library_source_packs SET evidence_refs=%s::jsonb,style_refs=%s::jsonb,rights_warnings=%s::jsonb,"
                "revision=revision+1,updated_at=now() WHERE workspace_id=%s AND id=%s AND revision=%s RETURNING revision")
VEC_COLUMN = ("/*lio:vec.column*/ SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_library_embeddings' "
              "AND column_name='embedding'")
VEC_NEAR = ("/*lio:vec.near*/ SELECT e.asset_key,e.version_key,(e.embedding::vector(256) <=> q.v) AS distance FROM public.pr_library_embeddings e,"
            "(SELECT embedding::vector(256) AS v FROM public.pr_library_embeddings WHERE workspace_id=%s AND version_key=%s AND modality='visual' "
            "AND model_id=%s AND dims=256 AND status='active' AND embedding IS NOT NULL ORDER BY created_at DESC LIMIT 1) q "
            "WHERE e.workspace_id=%s AND e.modality='visual' AND e.model_id=%s AND e.dims=256 AND e.status='active' AND e.embedding IS NOT NULL "
            "AND e.version_key<>%s ORDER BY e.embedding::vector(256) <=> q.v LIMIT %s")
DUP_EXACT = ("/*lio:dup.exact*/ SELECT count(*) FROM public.pr_library_assets WHERE workspace_id=%s AND duplicate_of=%s "
             "AND processing_status='duplicate'")


def _uuid(key) -> uuid.UUID:
    return uuid.UUID(hex=c.asset_key(key))


def _key(value) -> str:
    return str(value).replace("-", "").lower()


def _writable(ctx):
    ctx.require("edit")
    if (ctx.state.get("workspace") or {}).get("sample"):
        raise AlphaError("Hosted sample workspaces are read-only.", 403, code="sample_read_only")


def _audit(ctx, kind: str, subject: str, meta: dict):
    from ..hosted import audit
    audit(ctx.cur, ctx.workspace_id, ctx.actor, kind, subject, meta)


# --- bounded graph walks (pure) ------------------------------------------------------------------------------------------
def _too_large():
    raise AlphaError("This lineage is too large to check safely. Link a closer version instead.", 422, code="library_lineage_too_large")


def creates_cycle(neighbors, source: str, target: str, *, max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES) -> bool:
    """Would adding source -> target close a loop? True when target already reaches source. `neighbors(frontier)` returns
    {node: [next, ...]} for a batch. Past the bounds the answer is unknown, so the link is refused (fail closed)."""
    if source == target:
        return True
    seen, frontier, depth = {target}, [target], 0
    while frontier:
        if depth >= max_depth:
            _too_large()
        depth += 1
        found = neighbors(frontier)
        following = []
        for node in frontier:
            for nxt in found.get(node, ()):
                if nxt == source:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    if len(seen) > max_nodes:
                        _too_large()
                    following.append(nxt)
        frontier = following
    return False


def traverse(neighbors, start: str, *, max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES) -> dict:
    """Breadth-first walk with a cycle guard; reports truncation instead of recursing forever."""
    seen, frontier, depth, nodes, truncated = {start}, [start], 0, [], False
    while frontier and not truncated:
        if depth >= max_depth:
            truncated = True
            break
        depth += 1
        found = neighbors(frontier)
        following = []
        for node in frontier:
            for nxt in found.get(node, ()):
                if nxt in seen:
                    continue
                if len(nodes) >= max_nodes:
                    truncated = True
                    break
                seen.add(nxt)
                nodes.append({"key": nxt, "depth": depth})
                following.append(nxt)
            if truncated:
                break
        frontier = following
    return {"nodes": nodes, "truncated": truncated}


def _neighbors(ctx, direction: str):
    def fetch(nodes):
        ctx.cur.execute(REL_OUT if direction == "out" else REL_IN, (ctx.workspace_id, list(LINEAGE), list(nodes)))
        out: dict = {}
        for frm, to in ctx.cur.fetchall():
            a, b = (frm, to) if direction == "out" else (to, frm)
            out.setdefault(a, [])
            if b not in out[a]:
                out[a].append(b)
        return out
    return fetch


# --- relation rows --------------------------------------------------------------------------------------------------------
def _relation(rid, version: dict, to_kind, to_key, to_version, relation, status, origin, created) -> dict:
    out = {"id": _key(rid), "relation": relation, "status": status, "origin": origin, "from": versions.ref(version),
           "to": {"kind": to_kind, "key": to_key}, "created": created}
    if to_version:
        out["to"]["versionId"] = to_version
    return out


def _upsert(ctx, version: dict, to_kind: str, to_key: str, to_version, relation: str, status: str, origin: str, evidence: dict,
            *, keep=("dismissed",)) -> dict:
    """One relation per (version, relation, target). An existing row changes status unless its status is in `keep`
    (a user's dismissal is never overridden by automation)."""
    ctx.cur.execute(REL_FIND, (ctx.workspace_id, version["versionId"], relation, to_kind, to_key, to_version or ""))
    found = ctx.cur.fetchone()
    if found:
        rid, current = found[0], found[1]
        if current != status and current not in keep:
            ctx.cur.execute(REL_SET, (status, json.dumps(evidence, sort_keys=True), ctx.workspace_id, _uuid(rid)))
            current = status
        return _relation(rid, version, to_kind, to_key, to_version, relation, current, origin, False)
    rid = uuid.uuid4()
    ctx.cur.execute(REL_INSERT, (rid, ctx.workspace_id, version["assetId"], version["versionId"], None, to_kind, to_key, to_version, relation, status,
                                 origin, json.dumps(evidence, sort_keys=True), ctx.actor))
    inserted = ctx.cur.fetchone()
    return _relation(inserted[0] if inserted else rid, version, to_kind, to_key, to_version, relation, status, origin, bool(inserted))


def record_used_in(ctx, version: dict, to_kind: str, to_key: str, *, evidence=None, origin: str = "system") -> dict:
    """Record that this exact version is cited by a draft, post, source pack or idea (source-pack creation and draft/post
    transitions call this). A stale or dismissed citation is never silently reactivated."""
    if to_kind not in DEPENDENT_KINDS or not isinstance(to_key, str) or not TO_KEY.fullmatch(to_key):
        c.fail("Name the draft, post, source pack or idea that used this item.")
    return _upsert(ctx, version, to_kind, to_key, None, "used_in", "active", origin, dict(evidence or {}), keep=("stale", "dismissed"))


def _spec(value) -> dict:
    if not isinstance(value, dict) or not set(value) <= {"relation", "from", "to", "toKind", "toKey", "evidence"}:
        c.fail("Describe the link with a relation, a source and a target.")
    kind = value.get("relation")
    if kind not in c.RELATIONS:
        c.fail("Choose derived_from, version_of, supersedes or used_in.")
    evidence = value.get("evidence") or {}
    note = evidence.get("note") if isinstance(evidence, dict) else None
    if not isinstance(evidence, dict) or set(evidence) - {"note"} or (note is not None and (not isinstance(note, str) or len(note) > 300)):
        c.fail("Keep the link note under 300 characters.")
    return {"relation": kind, "from": value.get("from"), "to": value.get("to"), "toKind": value.get("toKind"), "toKey": value.get("toKey"),
            "evidence": {"note": note} if note else {}}


# --- version stacks --------------------------------------------------------------------------------------------------------
def _restack(ctx, newer: dict, older: dict) -> dict:
    """Make `newer` the next version in `older`'s stack: lineage_id and version_no on the newer row only."""
    if newer["legacy"] or older["legacy"]:
        raise AlphaError("Photos and videos from the original media library can't be stacked as versions yet. Link them as derived instead.",
                         422, code="library_version_legacy")
    if newer["assetId"] == older["assetId"]:
        raise AlphaError("These are already versions of the same item.", 409, code="library_version_linked")
    ctx.cur.execute(ASSET_LOCK, (ctx.workspace_id, _uuid(newer["versionId"])))
    row = ctx.cur.fetchone()
    if not row:
        raise AlphaError("This item is unavailable.", 404, code="library_unavailable")
    if row[1] != row[0]:
        raise AlphaError("This item is already a version of another item.", 409, code="library_version_linked")
    ctx.cur.execute(ASSET_CHILDREN, (ctx.workspace_id, _uuid(newer["versionId"])))
    if int(ctx.cur.fetchone()[0]):
        raise AlphaError("This item already has its own versions. Link its newest version instead.", 409, code="library_version_has_versions")
    ctx.cur.execute(ASSET_MAXVER, (ctx.workspace_id, _uuid(older["assetId"])))
    next_no = int(ctx.cur.fetchone()[0]) + 1
    if next_no > 10000:
        raise AlphaError("This item has too many versions.", 422, code="library_version_limit")
    ctx.cur.execute(ASSET_RESTACK, (_uuid(older["assetId"]), next_no, ctx.workspace_id, _uuid(newer["versionId"])))
    if not ctx.cur.fetchone():
        raise AlphaError("This item changed. Reload and try again.", 409, code="library_version_linked")
    ctx.caches.clear()
    return versions.get(ctx, newer["versionId"])


def _cites(value, version_key: str, depth: int = 0) -> bool:
    if depth > 5:
        return False
    if isinstance(value, dict):
        if value.get("versionId") == version_key:
            return True
        return any(_cites(v, version_key, depth + 1) for v in value.values())
    if isinstance(value, list):
        return any(_cites(v, version_key, depth + 1) for v in value)
    return False


def flag_dependents(ctx, olds: list, new: dict) -> dict:
    """Mark everything that cites an older version stale and raise one 'outdated_source' warning per recipient and link
    through suggestions.evaluate_suggestions. Never rewrites a citation; idempotent for the same (old, new) pair."""
    new_ref = versions.ref(new)
    affected: dict = {}

    def add(old, kind, key, recipient=None):
        entry = affected.setdefault((kind, key), {"old": old, "kind": kind, "key": key, "recipient": None})
        if recipient:
            entry["recipient"] = recipient

    for old in olds[:MAX_STACK]:
        evidence = {"supersededBy": new_ref, "reason": "newer_version"}
        ctx.cur.execute(REL_STALE_USED, (json.dumps(evidence, sort_keys=True), ctx.workspace_id, old["versionId"]))
        for _, to_kind, to_key in ctx.cur.fetchall()[:MAX_DEPENDENTS]:
            add(old, to_kind, to_key)
        ctx.cur.execute(PACKS_CITING, (ctx.workspace_id, old["versionId"], old["versionId"], MAX_DEPENDENTS))
        for pack_id, _, _, _, created_by, evidence_refs, style_refs in ctx.cur.fetchall():
            if not (_cites(evidence_refs, old["versionId"]) or _cites(style_refs, old["versionId"])):
                continue  # a newer version can carry the old key as its assetId; only an exact version citation counts
            key = _key(pack_id)
            _upsert(ctx, old, "source_pack", key, None, "used_in", "stale", "system", evidence)
            add(old, "source_pack", key, created_by)
        for source in (ctx.state.get("sources") or [])[:5000]:
            origin = source.get("origin") if isinstance(source, dict) else None
            source_id = source.get("id") if isinstance(source, dict) else None
            if not isinstance(origin, dict) or origin.get("kind") != "library" or origin.get("assetId") != old["versionId"]:
                continue
            if not isinstance(source_id, str) or not TO_KEY.fullmatch(source_id):
                continue
            _upsert(ctx, old, "idea", source_id, None, "used_in", "stale", "system", evidence)
            add(old, "idea", source_id)
            for variant in (ctx.state.get("variants") or [])[:5000]:
                variant_id = variant.get("id") if isinstance(variant, dict) else None
                if isinstance(variant_id, str) and TO_KEY.fullmatch(variant_id) and source_id in (variant.get("sourceIds") or []):
                    _upsert(ctx, old, "draft", variant_id, None, "used_in", "stale", "system", evidence)
                    add(old, "draft", variant_id)
    created = 0
    if affected:
        from . import suggestions
        by_old: dict = {}
        for entry in list(affected.values())[:MAX_DEPENDENTS]:
            item = {"kind": entry["kind"], "key": entry["key"]}
            if entry["recipient"]:
                item["recipient"] = entry["recipient"]
            by_old.setdefault(entry["old"]["versionId"], (entry["old"], []))[1].append(item)
        for old, items in by_old.values():
            created += len(suggestions.evaluate_suggestions(ctx, {"type": "version_linked", "old": versions.ref(old), "new": new_ref, "affected": items}))
    return {"count": len(affected), "suggestions": created,
            "affected": [{"kind": e["kind"], "key": e["key"], "citesVersion": versions.ref(e["old"])} for e in list(affected.values())[:50]]}


def link_versions(ctx, relation) -> dict:
    """link_versions(ctx, relation) -> relation. `relation` = {relation, from: AssetRef, to: AssetRef} for lineage links, or
    {relation: 'used_in', from: AssetRef, toKind, toKey} for a citation. version_of restacks the newer row, records a
    supersedes edge and flags every dependent of the older versions."""
    _writable(ctx)
    spec = _spec(relation)
    kind = spec["relation"]
    if kind == "similar_to":
        raise AlphaError("Rafii suggests similar items itself; link a version or a derivation instead.", 422, code="library_relation_suggestion_only")
    source = versions.resolve(ctx, spec["from"])
    flagged = {"count": 0, "suggestions": 0, "affected": []}
    if kind == "used_in":
        rel = record_used_in(ctx, source, spec["toKind"], spec["toKey"], evidence=spec["evidence"], origin="user")
    else:
        target = versions.resolve(ctx, spec["to"])
        if creates_cycle(_neighbors(ctx, "out"), source["versionId"], target["versionId"]):
            raise AlphaError("That link would make an item its own ancestor.", 422, code="library_relation_cycle")
        if kind == "version_of":
            source = _restack(ctx, source, target)
            rel = _upsert(ctx, source, "asset", target["assetId"], target["versionId"], "version_of", "active", "user", spec["evidence"])
            _upsert(ctx, source, "asset", target["assetId"], target["versionId"], "supersedes", "active", "system", {"via": "version_of"})
            olds = [v for v in versions.stack(ctx, source["assetId"]) if v["versionId"] != source["versionId"] and v["versionNo"] < source["versionNo"]]
            flagged = flag_dependents(ctx, olds, source)
        elif kind == "supersedes":
            rel = _upsert(ctx, source, "asset", target["assetId"], target["versionId"], "supersedes", "active", "user", spec["evidence"])
            flagged = flag_dependents(ctx, [target], source)
        else:
            rel = _upsert(ctx, source, "asset", target["assetId"], target["versionId"], "derived_from", "active", "user", spec["evidence"])
    revs = policy.bump(ctx, organization=True)
    _audit(ctx, "library.relation_linked", source["versionId"], {"relation": kind, "flagged": flagged["count"]})
    if kind == "version_of":
        from . import collections
        collections.reevaluate_for_asset(ctx.cur, ctx.workspace_id, source["versionId"])  # the old head stops being current
    return {"relation": rel, "flagged": flagged, "organizationRevision": revs["organizationRevision"]}


# --- explicit replacement ----------------------------------------------------------------------------------------------------
def _supersedes(ctx, new: dict, old: dict) -> bool:
    if new["assetId"] == old["assetId"] and new["versionNo"] > old["versionNo"]:
        return True
    ctx.cur.execute(REL_FIND, (ctx.workspace_id, new["versionId"], "supersedes", "asset", old["assetId"], old["versionId"]))
    row = ctx.cur.fetchone()
    return bool(row and row[1] == "active")


def _replace(refs, old_key: str, new_ref: dict) -> tuple[list, list]:
    """Swap whole citations of the old version for the new version. Passages and locators of the old version do not apply
    to the new one, so the replacement cites the whole item and the user chooses passages again."""
    out, replaced = [], []
    for item in refs if isinstance(refs, list) else []:
        cited = item.get("assetRef") if isinstance(item, dict) and isinstance(item.get("assetRef"), dict) else item
        if isinstance(cited, dict) and cited.get("versionId") == old_key:
            replaced.append(item)
            out.append({"assetRef": dict(new_ref)} if cited is not item else dict(new_ref))
        else:
            out.append(item)
    return out, replaced


def _dependent(value) -> dict:
    if not isinstance(value, dict) or value.get("kind") not in DEPENDENT_KINDS or not isinstance(value.get("key"), str) \
            or not TO_KEY.fullmatch(value["key"]):
        c.fail("Choose the draft, post, source pack or idea to update.")
    return {"kind": value["kind"], "key": value["key"]}


def accept_replacement(ctx, old: dict, new: dict, dependent, expected_revision) -> dict:
    """The user replaces the cited old version with the newer one in ONE dependent. A source pack's revision (or, for other
    dependents, the organization revision) must match. The replaced citation stays in the relation history."""
    _writable(ctx)
    dep = _dependent(dependent)
    if not _supersedes(ctx, new, old):
        raise AlphaError("Only a newer linked version can replace this one.", 409, code="library_not_superseded")
    old_ref, new_ref = versions.ref(old), versions.ref(new)
    warnings = ["Review the new version’s facts before relying on it; approval of the old version does not carry over."]
    approval = policy.authorize_source(ctx, new, "draft_evidence")
    previous: list = []
    if dep["kind"] == "source_pack":
        ctx.cur.execute(PACK_LOCK, (ctx.workspace_id, _uuid(dep["key"])))
        row = ctx.cur.fetchone()
        if not row:
            raise AlphaError("This source pack is unavailable.", 404, code="library_unavailable")
        _, revision, status, evidence_refs, style_refs, rights_warnings, _ = row
        if status not in ("draft", "attached"):
            raise AlphaError("This source pack can no longer change.", 409, code="library_pack_closed")
        if type(expected_revision) is not int or expected_revision != int(revision):
            raise AlphaError("This source pack changed. Reload it before replacing the version.", 409, code="library_pack_conflict")
        new_evidence, replaced_evidence = _replace(evidence_refs, old["versionId"], new_ref)
        new_style, replaced_style = _replace(style_refs, old["versionId"], new_ref)
        previous = replaced_evidence + replaced_style
        if not previous:
            raise AlphaError("This source pack no longer cites that version.", 409, code="library_not_cited")
        notes = [w for w in (rights_warnings if isinstance(rights_warnings, list) else []) if isinstance(w, dict)]
        notes.append({"code": "replacement_needs_review", "assetId": new_ref["assetId"], "versionId": new_ref["versionId"],
                      "message": "Choose passages again in the new version and review its facts; approval did not carry over."})
        ctx.cur.execute(PACK_REPLACE, (json.dumps(new_evidence), json.dumps(new_style), json.dumps(notes[-40:]), ctx.workspace_id, _uuid(dep["key"]),
                                       int(revision)))
        replaced = ctx.cur.fetchone()
        if not replaced:
            raise AlphaError("This source pack changed. Reload it before replacing the version.", 409, code="library_pack_conflict")
        out_revision = int(replaced[0])
        _upsert(ctx, old, "source_pack", dep["key"], None, "used_in", "dismissed", "system",
                {"replacedBy": new_ref, "previousRefs": previous, "packRevision": int(revision)}, keep=())
        _upsert(ctx, new, "source_pack", dep["key"], None, "used_in", "active", "user", {"replaces": old_ref, "packRevision": out_revision}, keep=())
    else:
        revs = policy.revisions(ctx, fresh=True)
        if type(expected_revision) is not int or expected_revision != revs["organizationRevision"]:
            raise AlphaError("Library organization changed. Reload and try again.", 409, code="library_relation_conflict")
        ctx.cur.execute(REL_FIND, (ctx.workspace_id, old["versionId"], "used_in", dep["kind"], dep["key"], ""))
        row = ctx.cur.fetchone()
        if not row or row[1] != "stale":
            raise AlphaError("This item isn't waiting on a newer version.", 409, code="library_not_flagged")
        _upsert(ctx, old, dep["kind"], dep["key"], None, "used_in", "dismissed", "system", {"replacementAccepted": new_ref}, keep=())
        _upsert(ctx, new, dep["kind"], dep["key"], None, "used_in", "suggested", "user", {"replaces": old_ref, "pendingSourceReview": True}, keep=())
        warnings.append("The published post was not changed." if dep["kind"] == "post" else
                        "The draft text was not changed. Import the new version as a source and review its facts before using it.")
        out_revision = None
    if not approval.allowed:
        warnings.append(policy.message(approval.reason))
    revs = policy.bump(ctx, organization=True)
    _audit(ctx, "library.version_replacement_accepted", new["versionId"], {"dependent": dep["kind"], "replaced": len(previous)})
    return {"dependent": {**dep, "revision": out_revision}, "replacedBy": new_ref, "replaced": old_ref, "previousRefs": previous,
            "revision": out_revision if out_revision is not None else revs["organizationRevision"], "organizationRevision": revs["organizationRevision"],
            "warnings": warnings}


# --- near duplicates -------------------------------------------------------------------------------------------------------
def _vector_available(ctx) -> bool:
    if "vectorColumn" not in ctx.caches:
        ctx.cur.execute(VEC_COLUMN)
        ctx.caches["vectorColumn"] = bool(ctx.cur.fetchone())
    return ctx.caches["vectorColumn"]


def suggest_near_duplicates(ctx, version: dict) -> dict:
    """Record 'similar_to' suggestions from local perceptual vectors (worker C's local/visual-perceptual-v1). Never merges,
    hides or deletes anything; an existing (including dismissed) suggestion is left exactly as it is."""
    if not _vector_available(ctx):
        return {"available": False, "suggested": 0}
    key = version["versionId"]
    ctx.cur.execute(VEC_NEAR, (ctx.workspace_id, key, NEAR_MODEL, ctx.workspace_id, NEAR_MODEL, key, NEAR_LIMIT))
    rows = [(v, float(d)) for _, v, d in ctx.cur.fetchall() if d is not None and float(d) <= NEAR_DISTANCE]
    others = versions.load(ctx, [v for v, _ in rows]) if rows else {}
    suggested = 0
    for other_key, distance in rows:
        other = others.get(other_key)
        if other is None or other["status"] in HIDDEN or other["assetId"] == version["assetId"]:
            continue
        if not policy.authorize_source(ctx, other, "browse").allowed:
            continue
        a, b = sorted((version, other), key=lambda v: v["versionId"])
        ctx.cur.execute(REL_INSERT, (uuid.uuid4(), ctx.workspace_id, a["assetId"], a["versionId"], None, "asset", b["assetId"], b["versionId"],
                                     "similar_to", "suggested", "system", json.dumps({"method": NEAR_MODEL, "distance": round(distance, 4)}), None))
        if ctx.cur.fetchone():
            suggested += 1
    return {"available": True, "suggested": suggested}


def refresh_similar(cur, workspace_id, asset_key) -> dict:
    """Hook form of suggest_near_duplicates for job finalize (after an embed_visual result). Never raises."""
    try:
        key = c.asset_key(asset_key)
    except AlphaError:
        return {"status": "invalid"}
    try:
        cur.execute("SAVEPOINT library_similar")
    except Exception:
        return {"status": "error"}
    try:
        from .jobs import system_context
        ctx = system_context(cur, workspace_id)
        version = versions.load(ctx, [key]).get(key) if ctx is not None else None
        out = {"status": "skipped"}
        if version is not None and version["status"] not in HIDDEN:
            out = {"status": "ok", **suggest_near_duplicates(ctx, version)}
        cur.execute("RELEASE SAVEPOINT library_similar")
        return out
    except Exception as error:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT library_similar")
        except Exception:
            pass
        print(json.dumps({"event": "library_intelligence.similar_failed", "error": type(error).__name__}), flush=True)
        return {"status": "error"}


# --- reads -------------------------------------------------------------------------------------------------------------------
def _evidence(value) -> dict:
    return {k: value[k] for k in PUBLIC_EVIDENCE if isinstance(value, dict) and k in value}


def _other(version_key, loaded: dict) -> dict:
    v = loaded.get(version_key)
    if v is None or v["status"] in HIDDEN:
        return {"kind": "asset", "available": False}
    return {"kind": "asset", "available": True, "assetRef": versions.ref(v), "title": v["title"], "assetKind": v["kind"], "versionNo": v["versionNo"]}


def related(ctx, key: str) -> dict:
    """Versions, relations both ways, bounded lineage walks and near-duplicate suggestions for one version."""
    ctx.require("read")
    version = versions.get(ctx, key)
    vkey = version["versionId"]
    try:
        stack = versions.stack(ctx, version["assetId"])
    except AlphaError:
        stack = [version]
    ctx.cur.execute(REL_LIST_OUT, (ctx.workspace_id, [vkey], MAX_RELATED))
    outgoing = ctx.cur.fetchall()
    ctx.cur.execute(REL_LIST_IN, (ctx.workspace_id, [vkey], MAX_RELATED))
    incoming = ctx.cur.fetchall()
    ancestors = traverse(_neighbors(ctx, "out"), vkey)
    descendants = traverse(_neighbors(ctx, "in"), vkey)
    wanted = {r[6] for r in outgoing if r[4] == "asset" and r[6]} | {r[2] for r in incoming} | {n["key"] for n in ancestors["nodes"] + descendants["nodes"]}
    loaded = versions.load(ctx, sorted(wanted)) if wanted else {}

    def entry(r, direction):
        rid, _, from_version, segment, to_kind, to_key, to_version, relation, status, origin, evidence, created = r
        if direction == "out":
            other = _other(to_version, loaded) if to_kind == "asset" else {"kind": to_kind, "key": to_key}
        else:
            other = _other(from_version, loaded)
        out = {"id": _key(rid), "relation": relation, "status": status, "origin": origin, "direction": direction, "other": other,
               "evidence": _evidence(evidence), "createdAt": float(created) if created is not None else None}
        if segment:
            out["segmentId"] = _key(segment)
        return out

    entries = [entry(r, "out") for r in outgoing] + [entry(r, "in") for r in incoming]

    def decorate(walk):
        nodes = []
        for node in walk["nodes"]:
            other = _other(node["key"], loaded)
            nodes.append({"key": node["key"], "depth": node["depth"], **({k: other[k] for k in ("assetRef", "title", "versionNo")} if other["available"]
                                                                       else {"available": False})})
        return {"nodes": nodes, "truncated": walk["truncated"]}

    exact = 0
    if not version["legacy"]:
        ctx.cur.execute(DUP_EXACT, (ctx.workspace_id, _uuid(vkey)))
        exact = int(ctx.cur.fetchone()[0])
    head = stack[-1]
    return {
        "assetRef": versions.ref(version),
        "versions": [{"assetRef": versions.ref(v), "versionNo": v["versionNo"], "title": v["title"], "createdAt": v["createdAt"],
                      "current": v["versionId"] == head["versionId"]} for v in stack[-MAX_STACK:]],
        "relations": [e for e in entries if e["relation"] != "similar_to"],
        "lineage": {"ancestors": decorate(ancestors), "descendants": decorate(descendants)},
        "nearDuplicates": {"available": _vector_available(ctx),
                           "suggestions": [e for e in entries if e["relation"] == "similar_to" and e["status"] == "suggested" and e["other"].get("available")],
                           "note": "Similar items are suggestions only. Rafii never merges or deletes them."},
        "exactDuplicates": {"count": exact, "note": "Identical uploads are kept as references to this file, never stored twice."},
        "truncated": len(outgoing) >= MAX_RELATED or len(incoming) >= MAX_RELATED,
    }


def related_http(ctx, request):
    """GET .../assets/{key}/related."""
    return related(ctx, request["params"]["key"])


# --- actions -----------------------------------------------------------------------------------------------------------------
def _payload(envelope: dict, allowed: set) -> dict:
    payload = envelope.get("payload") or {}
    extra = sorted(set(payload) - allowed)
    if extra:
        c.fail(f"This action does not accept “{str(extra[0])[:40]}”.")
    return payload


def link_action(ctx, envelope, targets):
    """version.link: targetRefs [from, to] (newer/derived first), or [from] with payload toKind/toKey for used_in.
    expectedRevision, when given, is the workspace organization revision."""
    payload = _payload(envelope, {"relation", "toKind", "toKey", "note"})
    expected = envelope.get("expectedRevision")
    if expected is not None and expected != policy.revisions(ctx, fresh=True)["organizationRevision"]:
        return c.action_result("conflict", warnings=["Library organization changed. Reload and try again."])
    kind = payload.get("relation")
    spec = {"relation": kind, "evidence": {"note": payload["note"]} if payload.get("note") else {}}
    if kind == "used_in":
        if len(targets) != 1:
            c.fail("Choose the one item that was used.")
        spec.update({"from": versions.ref(targets[0]), "toKind": payload.get("toKind"), "toKey": payload.get("toKey")})
    else:
        if len(targets) != 2:
            c.fail("Choose the newer or derived item first, then the original.")
        spec.update({"from": versions.ref(targets[0]), "to": versions.ref(targets[1])})
    try:
        out = link_versions(ctx, spec)
    except AlphaError as error:
        if error.code in ("library_relation_cycle", "library_lineage_too_large"):
            return c.action_result("conflict", warnings=[str(error)])
        raise
    return c.action_result("applied", revision=out["organizationRevision"], result=out)


def accept_replacement_action(ctx, envelope, targets):
    """version.accept_replacement: targetRefs [cited old version, newer version]; payload dependentKind/dependentKey;
    expectedRevision is the source pack revision (or the organization revision for other dependents)."""
    payload = _payload(envelope, {"dependentKind", "dependentKey"})
    if len(targets) != 2:
        c.fail("Choose the cited version and the version that replaces it.")
    out = accept_replacement(ctx, targets[0], targets[1], {"kind": payload.get("dependentKind"), "key": payload.get("dependentKey")},
                             envelope.get("expectedRevision"))
    return c.action_result("applied", revision=out["revision"], result=out, warnings=out["warnings"])
