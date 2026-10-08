"""Final deliverables come home to Library (engineering spec §5 RegisterArtifact, §10; implementation plan T08; PRD R13, D5;
acceptance A052, A053).

Only a final output of a real, successful run in this workspace registers, once:
- Run: a pr_agent_runs row in this workspace. Text deliverables need the run completed or applied; a generated image is
  final when the creative path saved and verified it (its run may still be running while it saves).
- Final, not scratch: a text deliverable is a draft (variant) written by that run that a person accepted at this exact
  revision. Acceptance is the same rule Time Back uses for "accepted for use" (a publish job a person approved, or an
  automation post a person approved) plus a person's review of that exact revision (variant_review). `apply` alone
  produces reviewable working drafts; candidates in a run artifact, openings, proposed updates, research notes and tool
  output are working material and never register. Temporary, scratch, tool-log and external storage refs are refused.
- Bytes: the object must exist in Rafii private storage with the claimed sha256 (and, for text, decode to the accepted
  draft text) before anything claims registration. A missing or mismatched object leaves the registration 'failed' with
  an error code, retryable, and never reported as archived.
- No ingestion loop: an object the Library already owns, bytes identical to an ingested item, a draft that only repeats a
  Library passage it was given, and Library previews (video posters and frames) are refused.
- Once: pr_library_artifacts is unique per (workspace, run, output) and per idempotency key; a replayed completion event
  returns the same AssetRef and creates nothing.
- Lineage: derived_from relations from the deliverable to the source pack's evidence refs, the declared parents, the
  draft's Library-imported Ideas sources, and an image's own parent/reference images.

A text deliverable becomes a normalized Library row (source_kind 'artifact', queued for the normal Library worker); a
generated image already is a workspace asset, so it is recorded without a second asset.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid

from postriff_alpha.domain import AlphaError

from . import contracts as c
from . import policy, relations, versions

TEXT_RUN_STATES = ("completed", "applied")
IMAGE_RUN_STATES = ("running", "completed", "applied")
SCRATCH_EXT = frozenset({"log", "tmp", "temp", "part", "partial", "trace", "jsonl", "ndjson", "bak", "swp", "crdownload", "lock", "cache", "pid",
                         "out", "err", "dump"})
SCRATCH_MIME = frozenset({"text/x-log", "application/x-ndjson", "application/jsonl", "application/x-jsonlines", "application/x-trash"})
SCRATCH_NAME = re.compile(r"(?i)(?:^|[\s._\-])(?:tmp|temp|scratch|partial|debug|trace|logs?|cache|tool-?output|stdout|stderr|intermediate)(?:[\s._\-]|$)"
                          r"|~$|^\.")
OUTPUT = re.compile(r"^([0-9a-f]{32}):r([1-9][0-9]{0,5})$")
FILE_NAME = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{1,12}$")
MEDIA_NAME = re.compile(r"^[0-9a-f]{32}-[0-9a-f]{64}\.jpg$")
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_PARENTS = 40
MAX_EFFECT_OUTPUTS = 5

ART_NAMES = ("id", "run_id", "output_id", "idempotency_key", "content_sha256", "asset_key", "source_pack_id", "status", "error_code", "attempts")
RUN_GET = "/*lia:run.get*/ SELECT status FROM public.pr_agent_runs WHERE workspace_id=%s AND id=%s"
ART_FIND = ("/*lia:art.find*/ SELECT id::text,run_id,output_id,idempotency_key,content_sha256,asset_key,source_pack_id::text,status,error_code,attempts "
            "FROM public.pr_library_artifacts WHERE workspace_id=%s AND ((run_id=%s AND output_id=%s) OR idempotency_key=%s) ORDER BY created_at FOR UPDATE")
ART_INSERT = ("/*lia:art.insert*/ INSERT INTO public.pr_library_artifacts(id,workspace_id,run_id,output_id,idempotency_key,content_sha256,source_pack_id,"
              "status) VALUES(%s,%s,%s,%s,%s,%s,%s,'registering') ON CONFLICT DO NOTHING RETURNING id::text")
ART_RETRY = ("/*lia:art.retry*/ UPDATE public.pr_library_artifacts SET status='registering',attempts=attempts+1,error_code=NULL,content_sha256=%s,"
             "source_pack_id=%s,updated_at=now() WHERE workspace_id=%s AND id=%s")
ART_DONE = ("/*lia:art.done*/ UPDATE public.pr_library_artifacts SET status='registered',asset_key=%s,error_code=NULL,updated_at=now() "
            "WHERE workspace_id=%s AND id=%s")
ART_FAIL = "/*lia:art.fail*/ UPDATE public.pr_library_artifacts SET status='failed',error_code=%s,updated_at=now() WHERE workspace_id=%s AND id=%s"
OBJECT_OWNED = "/*lia:object.owned*/ SELECT replace(id::text,'-',''),source_kind FROM public.pr_library_assets WHERE workspace_id=%s AND object_name=%s LIMIT 1"
SHA_OWNED = ("/*lia:sha.owned*/ SELECT replace(id::text,'-','') FROM public.pr_library_assets WHERE workspace_id=%s AND sha256=%s "
             "AND source_kind<>'artifact' AND processing_status<>'deleting' LIMIT 1")
ASSET_INSERT = ("/*lia:asset.insert*/ INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,display_title,title_source,kind,"
                "mime,extension,bytes,bucket,object_name,etag,processing_status,next_attempt_at,provenance,transcription_status,source_kind) "
                "VALUES(%s,%s,%s,%s,%s,'generated',%s,%s,%s,%s,%s,%s,%s,'queued',now(),%s::jsonb,'not_applicable','artifact')")
PACK_REFS = "/*lia:pack.refs*/ SELECT evidence_refs,style_refs FROM public.pr_library_source_packs WHERE workspace_id=%s AND id=%s"


def _fail(message: str, status: int, code: str):
    raise AlphaError(message, status, code=code)


def _run_key(value) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def _norm(text) -> str:
    return " ".join(str(text or "").split()).casefold()


# --- what counts as final ---------------------------------------------------------------------------------------------
def accepted_for_use(state: dict, variant: dict) -> bool:
    """A person accepted this exact draft: approved it for publishing (a live publish job whose approver is the manifest
    actor, as Time Back counts it), approved an automation post, or reviewed this exact revision (variant_review)."""
    vid = variant.get("id")
    for job in (state.get("phase2") or {}).get("jobs") or []:
        manifest = job.get("manifest") if isinstance(job, dict) and isinstance(job.get("manifest"), dict) else {}
        if manifest.get("variantId") == vid and job.get("state") not in ("canceled", "failed") and job.get("approvedBy") \
                and job.get("approvedBy") == manifest.get("actor"):
            return True
    planning = ((state.get("raffi") or {}).get("campaignPlanning") or {})
    for occurrence in planning.get("occurrences") or []:
        for item in (occurrence.get("items") or []) if isinstance(occurrence, dict) else []:
            decision = item.get("decision") if isinstance(item, dict) and isinstance(item.get("decision"), dict) else {}
            if item.get("variantId") == vid and item.get("state") == "approved" and item.get("approvedVia") == "human" and decision.get("decision") == "approve":
                return True
    review = variant.get("uncertaintyReview")
    return isinstance(review, dict) and review.get("revision") == variant.get("revision") and not variant.get("needsReview")


def final_text_reason(state: dict, run_id: str, variant: dict) -> str | None:
    """None when `variant` is a final deliverable of `run_id`; otherwise why it is not (plain words)."""
    if variant.get("rejected") or variant.get("blockedByRetraction") or variant.get("sourceReviewRequired") or variant.get("policyBlocked"):
        return "This draft is blocked or was set aside, so it isn't a final deliverable."
    runs = {_run_key(x) for x in [variant.get("runId"), (variant.get("provenance") or {}).get("runId"), *(variant.get("runRefs") or [])] if x}
    if run_id not in runs:
        return "This draft wasn't written by that run."
    if not accepted_for_use(state, variant):
        return "Only a draft you reviewed or approved for publishing is a final deliverable; working drafts stay out of Library."
    return None


def _scratch(req: dict) -> bool:
    name = req["originalFilename"]
    stem, _, ext = name.rpartition(".") if "." in name else (name, "", "")
    return ext.lower() in SCRATCH_EXT or req["mime"] in SCRATCH_MIME or bool(SCRATCH_NAME.search(stem or name))


# --- lineage and loop guards --------------------------------------------------------------------------------------------
def _pack_refs(ctx, pack_key: str | None) -> list:
    if not pack_key:
        return []
    ctx.cur.execute(PACK_REFS, (ctx.workspace_id, uuid.UUID(hex=pack_key)))
    row = ctx.cur.fetchone()
    if not row:
        _fail("This source pack is unavailable.", 404, "library_unavailable")
    evidence = row[0] if isinstance(row[0], list) else json.loads(row[0] or "[]")
    return [e for e in evidence if isinstance(e, dict)]


def _parents(ctx, refs: list) -> list:
    """[(version, segmentId|None)] for (versionKey, segmentId) pairs, bounded, existing in this workspace only."""
    pairs = list(dict.fromkeys((k, s) for k, s in refs if isinstance(k, str) and c.KEY.fullmatch(k)))[:MAX_PARENTS]
    loaded = versions.load(ctx, [k for k, _ in pairs])
    return [(loaded[k], s) for k, s in pairs if k in loaded and loaded[k]["status"] not in ("deleting", "missing")]


def _ref_pairs(items) -> list:
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        ref = item.get("assetRef") if isinstance(item.get("assetRef"), dict) else item
        if isinstance(ref, dict) and ref.get("versionId"):
            out.append((str(ref["versionId"]), item.get("segmentId")))
    return out


def _parent_texts(ctx, parents: list, extra_texts=()) -> set:
    from .source_packs import _active_segments, _segment
    texts = {_norm(t) for t in extra_texts if t}
    for version, segment_id in parents[:10]:
        if segment_id:
            found = _segment(ctx, version["versionId"], segment_id)
            if found:
                texts.add(_norm(found["text"]))
        else:
            passages = _active_segments(ctx, version)[:200]
            texts |= {_norm(p["text"]) for p in passages}
            if passages:
                texts.add(_norm("\n\n".join(p["text"] for p in passages)))
        if version.get("summary"):
            texts.add(_norm(version["summary"]))
    return {t for t in texts if t}


def _lineage(ctx, child: dict, parents: list, evidence: dict) -> int:
    neighbors = relations._neighbors(ctx, "out") if hasattr(relations, "_neighbors") else None
    made = 0
    for version, segment_id in parents:
        if version["versionId"] == child["versionId"]:
            continue
        if neighbors is not None:
            try:
                if relations.creates_cycle(neighbors, child["versionId"], version["versionId"]):
                    continue
            except AlphaError:
                continue  # too large to check safely: lineage stays unrecorded rather than risking a cycle
        detail = {**evidence, **({"segmentId": segment_id} if segment_id else {})}
        ctx.cur.execute(relations.REL_INSERT, (uuid.uuid4(), ctx.workspace_id, child["assetId"], child["versionId"], None, "asset", version["assetId"],
                                               version["versionId"], "derived_from", "active", "system", json.dumps(detail, sort_keys=True), ctx.actor))
        made += 1 if ctx.cur.fetchone() else 0
    return made


# --- plans: refuse first, verify bytes, then register ----------------------------------------------------------------------
def _document_plan(ctx, req: dict, run_id: str, run_status: str, pack_refs: list) -> dict:
    match = OUTPUT.fullmatch(req["outputId"])
    variant = next((v for v in ctx.state.get("variants") or [] if v.get("id") == match.group(1)), None) if match else None
    if variant is None:
        _fail("Only a draft you reviewed or approved for publishing is a final deliverable.", 409, "library_artifact_not_final")
    if run_status not in TEXT_RUN_STATES:
        _fail("That run didn't finish successfully, so its output isn't final.", 409, "library_artifact_not_final")
    reason = final_text_reason(ctx.state, run_id, variant)
    if reason:
        _fail(reason, 409, "library_artifact_not_final")
    if int(variant.get("revision") or 0) != int(match.group(2)):
        _fail("This draft changed since it was accepted. Accept the current version first.", 409, "library_artifact_not_final")
    name = req["storageRef"]["objectName"]
    if req["storageRef"]["category"] != "file" or not FILE_NAME.fullmatch(name):
        _fail("Use a storage reference produced by Rafii storage.", 422, "library_artifact_storage")
    from ..library_assets import _type
    filename, ext, mime, kind = _type(req["originalFilename"], req["mime"])
    ctx.cur.execute(OBJECT_OWNED, (ctx.workspace_id, name))
    if ctx.cur.fetchone():
        _fail("This file is already in your Library.", 422, "library_artifact_loop")
    ctx.cur.execute(SHA_OWNED, (ctx.workspace_id, req["contentSha256"]))
    if ctx.cur.fetchone():
        _fail("This output is identical to an item already in your Library.", 422, "library_artifact_loop")
    library_sources = [s for s in ctx.state.get("sources") or [] if s.get("id") in (variant.get("sourceIds") or [])
                       and (s.get("origin") or {}).get("kind") == "library"]
    pairs = _ref_pairs(req["parentRefs"]) + _ref_pairs(pack_refs)
    pairs += [(str(s["origin"].get("assetId")), s["origin"].get("segmentId")) for s in library_sources]
    parents = _parents(ctx, pairs)
    if _norm(variant.get("text")) in _parent_texts(ctx, parents, [s.get("text") for s in library_sources]):
        _fail("This output only repeats material from your Library, so it isn't registered again.", 422, "library_artifact_loop")
    held: dict = {}

    def verify() -> str | None:
        library = getattr(ctx.service, "library", None)
        storage = getattr(library, "storage", None)
        if storage is None:
            return "library_storage_not_configured"
        try:
            info = storage.object_info(ctx.workspace_id, "file", name)
            raw = storage.get_bounded(ctx.workspace_id, "file", name, MAX_TEXT_BYTES)
        except AlphaError:
            return "library_artifact_bytes_missing"
        if hashlib.sha256(raw).hexdigest() != req["contentSha256"]:
            return "library_artifact_hash_mismatch"
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return "library_artifact_content_mismatch"
        if _norm(text) != _norm(variant.get("text")):
            return "library_artifact_content_mismatch"
        try:
            library.assert_capacity(ctx.cur, ctx.state, ctx.workspace_id, len(raw))
        except AlphaError:
            return "library_quota"
        held.update(raw=raw, etag=info.get("etag"), bucket=getattr(library, "bucket", "postriff-library"))
        return None

    def register() -> dict:
        key = name.split(".", 1)[0]
        provenance = {"source": "artifact", "runId": run_id, "outputId": req["outputId"], "variantId": variant["id"], "variantRevision": variant["revision"],
                      "sourcePackId": req["sourcePackId"], "contentSha256": req["contentSha256"], "registeredBy": ctx.actor}
        title = (req["displayTitle"] or filename.rsplit(".", 1)[0])[:160]
        ctx.cur.execute(ASSET_INSERT, (uuid.UUID(hex=key), ctx.workspace_id, ctx.actor, filename, title, kind, mime, ext, len(held["raw"]), held["bucket"],
                                       name, held["etag"], json.dumps(provenance)))
        return {"assetId": key, "versionId": key, "sha256": req["contentSha256"]}

    return {"verify": verify, "register": register, "parents": parents, "category": "file"}


def _image_plan(ctx, req: dict, run_id: str, run_status: str, pack_refs: list) -> dict:
    name = req["storageRef"]["objectName"]
    if req["storageRef"]["category"] != "media" or not MEDIA_NAME.fullmatch(name):
        _fail("Use a storage reference produced by Rafii storage.", 422, "library_artifact_storage")
    media = [a for a in (ctx.state.get("phase2") or {}).get("assets") or [] if isinstance(a, dict) and not a.get("deleted")]
    asset = next((a for a in media if a.get("objectName") == name), None)
    if asset is None:
        previews = {p.get("objectName") for a in media for p in [a.get("poster")] + list(a.get("frames") or []) if isinstance(p, dict)}
        if name in previews:
            _fail("Video posters and frames are Library previews, not new work.", 422, "library_artifact_loop")
        _fail("Only images Rafii made in this run can be registered.", 422, "library_artifact_loop")
    lineage = asset.get("lineage") if isinstance(asset.get("lineage"), dict) else {}
    if asset.get("origin") != "rafii_agent" or _run_key(lineage.get("runId")) != run_id:
        _fail("Only images Rafii made in this run can be registered.", 422, "library_artifact_loop")
    if asset.get("id") != req["outputId"] or asset.get("hash") != req["contentSha256"]:
        _fail("This output doesn't match the saved image.", 409, "library_artifact_conflict")
    if run_status not in IMAGE_RUN_STATES:
        _fail("That run didn't finish successfully, so its output isn't final.", 409, "library_artifact_not_final")
    keys = [lineage.get("parentAssetId")] + list(lineage.get("sourceAssetIds") or [])
    parents = _parents(ctx, [(k, None) for k in keys if k] + _ref_pairs(req["parentRefs"]) + _ref_pairs(pack_refs))

    def verify() -> str | None:
        storage = getattr(getattr(ctx.service, "assets", None), "storage", None)
        if storage is None:
            return "library_storage_not_configured"
        try:
            raw = storage.get(ctx.workspace_id, "media", name)
        except AlphaError:
            return "library_artifact_bytes_missing"
        return None if hashlib.sha256(raw).hexdigest() == req["contentSha256"] else "library_artifact_hash_mismatch"

    def register() -> dict:
        return {"assetId": asset["id"], "versionId": asset["id"], "sha256": asset["hash"]}  # the saved image is the Library item

    return {"verify": verify, "register": register, "parents": parents, "category": "media"}


def _result(row: dict, *, replayed: bool, lineage: int | None = None) -> dict:
    out = {"contractVersion": c.CONTRACT_VERSION, "status": "registered", "archived": True, "replayed": replayed,
           "assetRef": {"assetId": row["asset_key"], "versionId": row["asset_key"], "sha256": row["content_sha256"]},
           "registrationId": c.asset_key(row["id"]), "runId": row["run_id"], "outputId": row["output_id"],
           "sourcePackId": c.asset_key(row["source_pack_id"]) if row.get("source_pack_id") else None, "attempts": int(row["attempts"])}
    if lineage is not None:
        out["lineage"] = {"derivedFrom": lineage}
    return out


def register_final_artifact(ctx, request) -> dict:
    """register_final_artifact(ctx, request: RegisterArtifact) -> {assetRef, status, ...} (implementation plan T08).

    Refusals raise before anything is written. A byte problem returns status 'failed' with an error code (retryable, not
    archived). A replay returns the original AssetRef with `replayed: true`."""
    ctx.require("edit")
    req = c.register_artifact(request)
    if _scratch(req):
        _fail("Temporary files, logs and tool output stay out of Library.", 422, "library_artifact_scratch")
    run_id = _run_key(req["runId"])
    row = None
    if run_id is not None:
        ctx.cur.execute(RUN_GET, (ctx.workspace_id, uuid.UUID(run_id)))
        row = ctx.cur.fetchone()
    if row is None:
        _fail("That run is unavailable.", 404, "library_artifact_run_unavailable")
    run_status = row[0]
    pack_refs = _pack_refs(ctx, req["sourcePackId"])
    ctx.cur.execute(ART_FIND, (ctx.workspace_id, run_id, req["outputId"], req["idempotencyKey"]))
    rows = [dict(zip(ART_NAMES, r)) for r in ctx.cur.fetchall()]
    mine = next((r for r in rows if r["run_id"] == run_id and r["output_id"] == req["outputId"]), None)
    if mine is None and rows:
        _fail("This registration key was already used for a different output.", 409, "library_artifact_conflict")
    if mine is not None:
        if mine["content_sha256"] != req["contentSha256"]:
            _fail("This output was already registered with different content.", 409, "library_artifact_conflict")
        if mine["status"] == "registered":
            return _result(mine, replayed=True)
    plan = (_document_plan if req["storageRef"]["category"] == "file" else _image_plan)(ctx, req, run_id, run_status, pack_refs)
    pack_uuid = uuid.UUID(hex=req["sourcePackId"]) if req["sourcePackId"] else None
    if mine is None:
        aid = uuid.uuid4()
        ctx.cur.execute(ART_INSERT, (aid, ctx.workspace_id, run_id, req["outputId"], req["idempotencyKey"], req["contentSha256"], pack_uuid))
        if not ctx.cur.fetchone():
            _fail("This output is being registered by another request. Try again shortly.", 409, "library_artifact_busy")
        attempts = 1
    else:
        aid = uuid.UUID(mine["id"])
        ctx.cur.execute(ART_RETRY, (req["contentSha256"], pack_uuid, ctx.workspace_id, aid))
        attempts = int(mine["attempts"]) + 1
    record = {"id": str(aid), "run_id": run_id, "output_id": req["outputId"], "content_sha256": req["contentSha256"], "source_pack_id": req["sourcePackId"],
              "attempts": attempts}
    problem = plan["verify"]()
    if problem:
        ctx.cur.execute(ART_FAIL, (problem, ctx.workspace_id, aid))
        return {"contractVersion": c.CONTRACT_VERSION, "status": "failed", "errorCode": problem, "retryable": True, "archived": False, "assetRef": None,
                "replayed": False, "registrationId": aid.hex, "runId": run_id, "outputId": req["outputId"], "attempts": attempts}
    ref = plan["register"]()
    ctx.cur.execute(ART_DONE, (ref["assetId"], ctx.workspace_id, aid))
    made = _lineage(ctx, ref, plan["parents"], {"via": "artifact", "runId": run_id, "outputId": req["outputId"], "sourcePackId": req["sourcePackId"]})
    from ..hosted import audit
    audit(ctx.cur, ctx.workspace_id, ctx.actor, "library.artifact_registered", ref["assetId"], {"category": plan["category"], "attempts": attempts,
                                                                                                "derivedFrom": made})
    return _result({**record, "asset_key": ref["assetId"]}, replayed=False, lineage=made)


# --- producers ---------------------------------------------------------------------------------------------------------------
def store_text_deliverable(ctx, run_id: str, variant_id: str, *, source_pack_id: str | None = None) -> dict:
    """Write an accepted draft as a Markdown document into private storage (immutable, deterministic name, so a replay finds
    the same object) and register it. The source pack defaults to the one attached to the draft."""
    variant = next((v for v in ctx.state.get("variants") or [] if v.get("id") == variant_id), None)
    if variant is None:
        _fail("This draft is unavailable.", 404, "library_draft_unavailable")
    run = _run_key(run_id)
    if run is None:
        _fail("That run is unavailable.", 404, "library_artifact_run_unavailable")
    revision = int(variant.get("revision") or 1)
    text = str(variant.get("text") or "").replace("\r\n", "\n").strip()
    raw = (text + "\n").encode("utf-8")
    key = hashlib.sha256(f"{ctx.workspace_id}|{run}|{variant_id}|{revision}".encode()).hexdigest()[:32]
    name = f"{key}.md"
    storage = getattr(getattr(ctx.service, "library", None), "storage", None)
    if storage is not None and callable(getattr(storage, "put_immutable", None)):
        try:
            storage.put_immutable(ctx.workspace_id, "file", name, raw, "text/markdown")
        except AlphaError as error:
            if error.status != 409:  # 409: this exact deliverable was already stored by an earlier attempt
                pass  # registration below records the missing bytes as a retryable failure
    pack = source_pack_id or (variant.get("librarySources") or {}).get("packId")
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    request = {"runId": run, "outputId": f"{variant_id}:r{revision}", "sourcePackId": pack, "contentSha256": hashlib.sha256(raw).hexdigest(),
               "storageRef": {"category": "file", "objectName": name}, "mime": "text/markdown",
               "displayTitle": (first_line[:120] or f"Draft for {variant.get('platform') or 'a post'}"),
               "originalFilename": f"rafii-draft-{variant_id[:8]}-r{revision}.md", "artifactRole": "final", "parentRefs": [],
               "idempotencyKey": f"rafii-draft:{run}:{variant_id}:r{revision}"}
    return register_final_artifact(ctx, request)


def register_generated_image(ctx, run_id: str, asset: dict) -> dict:
    """The creative path's hook: record an image Rafii made and verified in this run, without a second asset."""
    run = _run_key(run_id)
    if not isinstance(asset, dict) or run is None:
        _fail("That run is unavailable.", 404, "library_artifact_run_unavailable")
    request = {"runId": run, "outputId": asset.get("id"), "contentSha256": asset.get("hash"),
               "storageRef": {"category": "media", "objectName": asset.get("objectName")}, "mime": "image/jpeg",
               "displayTitle": str(asset.get("alt") or "Generated image")[:160], "originalFilename": f"{asset.get('id')}.jpg", "artifactRole": "final",
               "parentRefs": [], "idempotencyKey": f"agent-image:{run}:{asset.get('id')}"}
    return register_final_artifact(ctx, request)


def newly_accepted(before: dict, after: dict) -> list[str]:
    """Drafts a command accepted: a new publish job or human automation approval (Time Back's rule), or a new review of
    the draft's current revision."""
    from ..time_savings import completed_outcomes
    ids = [o.get("variantId") for o in completed_outcomes(before or {}, after or {}) if isinstance(o.get("variantId"), str)]
    old = {v.get("id"): v for v in (before or {}).get("variants") or [] if isinstance(v, dict)}
    for variant in (after or {}).get("variants") or []:
        if not isinstance(variant, dict):
            continue
        review = variant.get("uncertaintyReview")
        if isinstance(review, dict) and review.get("revision") == variant.get("revision") and not variant.get("needsReview") \
                and (old.get(variant.get("id")) or {}).get("uncertaintyReview") != review:
            ids.append(variant.get("id"))
    return list(dict.fromkeys(i for i in ids if i))


def capture_effect(cur, workspace_id, before, after, principal) -> list:
    """Repository effect (hosted.PostgresWorkspaceRepository.effects): when a command accepts a draft, store and register it
    in the same transaction. Each registration runs under its own savepoint and never fails the person's command; a
    refusal (not final, loop) is skipped and a byte problem stays a retryable 'failed' registration."""
    if not policy.enabled("task_ui"):
        return []
    try:
        accepted = newly_accepted(before, after)
    except Exception:  # noqa: BLE001 — a malformed state must not fail the command that produced it
        return []
    results = []
    for variant_id in accepted[:MAX_EFFECT_OUTPUTS]:
        variant = next((v for v in (after or {}).get("variants") or [] if isinstance(v, dict) and v.get("id") == variant_id), {})
        run_id = variant.get("runId") or (variant.get("provenance") or {}).get("runId")
        if not run_id:
            continue
        cur.execute("SAVEPOINT library_artifact")
        try:
            from . import api
            ctx = api.context(cur, principal, workspace_id)
            results.append(store_text_deliverable(ctx, run_id, variant_id))
            cur.execute("RELEASE SAVEPOINT library_artifact")
        except Exception as error:  # noqa: BLE001
            cur.execute("ROLLBACK TO SAVEPOINT library_artifact")
            results.append({"status": "skipped", "variantId": variant_id, "reason": getattr(error, "code", None) or type(error).__name__})
    return results
