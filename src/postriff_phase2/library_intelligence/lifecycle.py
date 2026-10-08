"""Deletion, revocation, backfill and index-generation controls for Library intelligence (engineering spec §6, §12; T12).

Everything runs inside the caller's transaction, is bounded and content-free, and returns a receipt that counts what
changed, so the UI and the acceptance evidence show propagation instead of assuming it.

Deletion (`revoke_or_delete_source(ctx, ref)` / `on_source_deleted(cur, ...)`), per deleted content version:
    segments, baseline chunks, annotations   hard-deleted: they hold the deleted file's text; a tombstone would retain it.
                                             Nothing references them by foreign key; citations to them resolve as unavailable.
    embeddings (local and cloud)             hard-deleted for that version (vectors are derived from the content). Not via
                                             index.tombstone: it matches asset_key OR version_key and would also revoke the
                                             other versions' vectors when the deleted version is a lineage root.
    capabilities / jobs                      rows removed / queued and running jobs cancelled (no derivative can land).
    relations                                similar_to suggestions removed; lineage and used_in kept as 'stale' history.
    source packs                             status 'revoked' plus a source_deleted warning; refs are never rewritten.
    suggestions                              suppressed.
    voice spans                              voice.withdraw_for_keys(ctx, keys, force=True) (canonical voice_sample_revoke).
    collection items and overrides           removed (the item no longer exists).
    usage events                             kept for post history but anonymized: segment and source detail dropped.
    cached previews/peaks                    pr_library_assets.media and summary cleared immediately.
    exact duplicates                         the oldest sibling (duplicate_of) takes over the ORIGINAL object and is re-queued
                                             as the canonical copy; the original's bytes are never removed while referenced.
Kept on purpose: the content-free audit log and metrics, job rows (cost history) and artifact registration rows (so a
replayed completion cannot register a deleted deliverable again). Issued signed links expire on their own (≤300 s).

Revocation (`propagate_revocation`, called by policy.revoke after the grant row is revoked) narrows by scope, skips every
item another active grant still covers, and moves a 'ready' embedding capability whose cloud vectors were revoked to
blocked_permission.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from postriff_alpha.domain import AlphaError

from . import capabilities as caps_module
from . import contracts as c
from . import policy, telemetry, versions

RESIDUAL = ("Private download and viewer links already issued expire on their own within 300 seconds; material already sent to an AI provider "
            "cannot be recalled. The audit log keeps content-free records.")
PAUSE_ENV = "RAFII_LIBRARY_BACKFILL_PAUSED"
TRUE = ("1", "true", "yes", "on")
REVOKE_CAPABILITIES = {"asr": ("transcribe",), "vision": ("visual", "embed_visual"), "embedding": ("embed_text", "embed_visual"),
                       "llm": ("understand",), "ocr": ("extract",)}
MODALITY_CAPABILITY = {"text": "embed_text", "visual": "embed_visual"}
MAX_WORKSPACES = 50

ASSET_LOCK = ("/*lil:asset.lock*/ SELECT object_name,bucket,etag,bytes,mime,extension,kind,processing_status FROM public.pr_library_assets "
              "WHERE workspace_id=%s AND id=%s FOR UPDATE")
SIBLINGS = ("/*lil:asset.siblings*/ SELECT replace(id::text,'-',''),object_name FROM public.pr_library_assets WHERE workspace_id=%s AND duplicate_of=%s "
            "AND processing_status='duplicate' ORDER BY created_at,id FOR UPDATE")
RENAME = "/*lil:asset.rename*/ UPDATE public.pr_library_assets SET object_name=%s,updated_at=now() WHERE workspace_id=%s AND id=%s"
PROMOTE = ("/*lil:asset.promote*/ UPDATE public.pr_library_assets SET object_name=%s,bucket=%s,etag=%s,bytes=%s,mime=%s,extension=%s,kind=%s,"
           "transcription_status=CASE WHEN %s='audio' THEN 'unavailable' ELSE 'not_applicable' END,duplicate_of=NULL,processing_status='queued',"
           "indexing_status='pending',attempts=0,next_attempt_at=now(),lease_token=NULL,lease_expires_at=NULL,extraction_error=NULL,updated_at=now() "
           "WHERE workspace_id=%s AND id=%s")
REPOINT = ("/*lil:asset.repoint*/ UPDATE public.pr_library_assets SET duplicate_of=%s,updated_at=now() WHERE workspace_id=%s AND duplicate_of=%s "
           "AND processing_status='duplicate' AND id<>%s")
CLEAR = ("/*lil:asset.clear*/ UPDATE public.pr_library_assets SET media='{}'::jsonb,summary=NULL,updated_at=now() WHERE workspace_id=%s "
         "AND id=ANY(%s::uuid[]) AND (media<>'{}'::jsonb OR summary IS NOT NULL)")
CHUNKS = "/*lil:chunks.delete*/ DELETE FROM public.pr_library_chunks WHERE workspace_id=%s AND asset_id=ANY(%s::uuid[])"
JOBS_CANCEL = ("/*lil:jobs.cancel*/ UPDATE public.pr_library_jobs SET status='cancelled',error_category='cancelled',error_code=%s,lease_token=NULL,"
               "lease_expires_at=NULL,finished_at=now(),updated_at=now() WHERE workspace_id=%s AND asset_key=ANY(%s) AND status IN ('queued','processing')")
CAPS_DELETE = "/*lil:caps.delete*/ DELETE FROM public.pr_library_capabilities WHERE workspace_id=%s AND asset_key=ANY(%s)"
CAPS_WITHDRAW = ("/*lil:caps.withdraw*/ UPDATE public.pr_library_capabilities SET state='blocked_permission',error_code=%s,detail=%s,retryable=false,"
                 "progress=NULL,updated_at=now() WHERE workspace_id=%s AND asset_key=ANY(%s) AND state<>'not_requested'")
SEG_DELETE = "/*lil:segments.delete*/ DELETE FROM public.pr_library_segments WHERE workspace_id=%s AND version_key=ANY(%s)"
SEG_SUPERSEDE = ("/*lil:segments.supersede*/ UPDATE public.pr_library_segments SET superseded_at=now() WHERE workspace_id=%s AND version_key=ANY(%s) "
                 "AND superseded_at IS NULL")
ANN_DELETE = "/*lil:annotations.delete*/ DELETE FROM public.pr_library_annotations WHERE workspace_id=%s AND version_key=ANY(%s)"
ANN_DEACTIVATE = ("/*lil:annotations.deactivate*/ UPDATE public.pr_library_annotations SET active=false,updated_at=now() WHERE workspace_id=%s "
                  "AND version_key=ANY(%s) AND active")
EMB_DELETE = "/*lil:embeddings.delete*/ DELETE FROM public.pr_library_embeddings WHERE workspace_id=%s AND version_key=ANY(%s)"
EMB_REVOKE = "/*lil:embeddings.revoke*/ UPDATE public.pr_library_embeddings SET status='revoked' WHERE workspace_id=%s AND version_key=ANY(%s) AND status='active'"
REL_DROP = ("/*lil:relations.drop*/ DELETE FROM public.pr_library_relations WHERE workspace_id=%s AND relation='similar_to' "
            "AND (from_version=ANY(%s) OR (to_kind='asset' AND to_version=ANY(%s)))")
REL_STALE = ("/*lil:relations.stale*/ UPDATE public.pr_library_relations SET status='stale',evidence=evidence||%s::jsonb,updated_at=now() WHERE workspace_id=%s "
             "AND relation<>'similar_to' AND status IN ('active','suggested') AND (from_version=ANY(%s) OR (to_kind='asset' AND to_version=ANY(%s)))")
PACKS = ("/*lil:packs.revoke*/ UPDATE public.pr_library_source_packs SET status='revoked',rights_warnings=rights_warnings||%s::jsonb,updated_at=now() "
         "WHERE workspace_id=%s AND status IN ('draft','attached') AND (strpos(evidence_refs::text,%s)>0 OR strpos(style_refs::text,%s)>0)")
SUGGESTIONS = ("/*lil:suggestions.suppress*/ UPDATE public.pr_library_suggestions SET state='suppressed',updated_at=now() WHERE workspace_id=%s "
               "AND state IN ('new','seen','snoozed') AND (candidate_refs::text ~ ANY(%s) OR affected::text ~ ANY(%s))")
ITEMS = "/*lil:collections.items*/ DELETE FROM public.pr_library_collection_items WHERE workspace_id=%s AND asset_key=ANY(%s)"
OVERRIDES = "/*lil:collections.overrides*/ DELETE FROM public.pr_library_collection_overrides WHERE workspace_id=%s AND asset_key=ANY(%s)"
USAGE = ("/*lil:usage.anonymize*/ UPDATE public.pr_library_usage_events SET segment_id=NULL,source=%s::jsonb WHERE workspace_id=%s "
         "AND (version_key=ANY(%s) OR (version_key IS NULL AND asset_key=ANY(%s)))")
LINEAGE_OTHERS = ("/*lil:lineage.others*/ SELECT count(*) FROM public.pr_library_assets WHERE workspace_id=%s AND lineage_id=ANY(%s::uuid[]) "
                  "AND NOT (replace(id::text,'-','')=ANY(%s)) AND processing_status NOT IN ('deleting','duplicate')")

REV_KEYS = ("/*lil:rev.keys*/ SELECT replace(id::text,'-','') FROM public.pr_library_assets WHERE workspace_id=%s "
            "AND (replace(id::text,'-','')=%s OR replace(lineage_id::text,'-','')=%s)")
REV_JOBS = ("/*lil:rev.jobs*/ UPDATE public.pr_library_jobs SET status='cancelled',error_category='permission',error_code='grant_revoked',lease_token=null,"
            "lease_expires_at=null,finished_at=now(),updated_at=now() WHERE workspace_id=%s AND status IN ('queued','processing') AND capability=ANY(%s)")
REV_CAPS = ("/*lil:rev.caps*/ UPDATE public.pr_library_capabilities SET state='blocked_permission',error_code='grant_revoked',retryable=false,updated_at=now() "
            "WHERE workspace_id=%s AND state IN ('queued','processing') AND capability=ANY(%s)")
REV_EMB = ("/*lil:rev.embeddings*/ UPDATE public.pr_library_embeddings SET status='revoked' WHERE workspace_id=%s AND status='active' AND modality=ANY(%s) "
           "AND model_id NOT LIKE 'local/%%'")
REV_READY = ("/*lil:rev.ready*/ UPDATE public.pr_library_capabilities c SET state='blocked_permission',error_code='grant_revoked',detail=%s,retryable=false,"
             "updated_at=now() WHERE c.workspace_id=%s AND c.asset_key=ANY(%s) AND c.capability=%s AND c.state IN ('ready','partial') AND NOT EXISTS "
             "(SELECT 1 FROM public.pr_library_embeddings e WHERE e.workspace_id=c.workspace_id AND e.version_key=c.asset_key AND e.modality=%s AND e.status='active')")
REV_PACKS = "/*lil:rev.packs*/ UPDATE public.pr_library_source_packs SET status='revoked',updated_at=now() WHERE workspace_id=%s AND status IN ('draft','attached')"
REV_SUGG = "/*lil:rev.suggestions*/ UPDATE public.pr_library_suggestions SET state='suppressed',updated_at=now() WHERE workspace_id=%s AND state IN ('new','seen','snoozed')"

BF_WORKSPACES = ("/*lil:backfill.workspaces*/ SELECT id::text FROM public.pr_workspaces w WHERE (%s::uuid IS NULL OR w.id=%s::uuid) "
                 "AND (%s::uuid IS NULL OR w.id>=%s::uuid) AND NOT (w.state ? 'accountBlock') AND NOT (w.state ? 'accountDeletion') ORDER BY w.id LIMIT %s")
BF_NORMALIZED = ("/*lil:backfill.normalized*/ SELECT replace(a.id::text,'-',''),to_char(a.created_at AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') "
                 "FROM public.pr_library_assets a WHERE a.workspace_id=%s AND a.processing_status IN ('ready','unsupported') "
                 "AND (a.created_at,a.id)>(%s::timestamptz,%s::uuid) AND (NOT EXISTS (SELECT 1 FROM public.pr_library_segments s WHERE s.workspace_id=a.workspace_id "
                 "AND s.version_key=replace(a.id::text,'-','') AND s.superseded_at IS NULL) OR NOT EXISTS (SELECT 1 FROM public.pr_library_embeddings e "
                 "WHERE e.workspace_id=a.workspace_id AND e.version_key=replace(a.id::text,'-','') AND e.status='active')) ORDER BY a.created_at,a.id LIMIT %s")
BF_QUEUED = "/*lil:backfill.queued*/ SELECT count(*) FROM public.pr_library_jobs WHERE workspace_id=%s AND status='queued'"
BF_CHECKPOINT = ("/*lil:backfill.checkpoint*/ SELECT dims FROM public.pr_library_metrics WHERE feature='library.backfill' AND event='checkpoint' "
                 "AND dims->>'scope'=%s ORDER BY id DESC LIMIT 1")
GEN_SET = ("/*lil:generation.set*/ UPDATE public.pr_library_policy SET index_generation=%s,updated_at=now() WHERE workspace_id=%s "
           "RETURNING grant_revision,index_generation,organization_revision")
GEN_VECTORS = ("/*lil:generation.vectors*/ SELECT index_generation,count(*) FROM public.pr_library_embeddings WHERE workspace_id=%s AND status='active' "
               "GROUP BY index_generation")
EPOCH_START = "1970-01-01T00:00:00.000000Z"
INSTALLED = "/*lil:installed*/ SELECT to_regclass('public.pr_library_jobs') IS NOT NULL"


def _uuids(keys) -> list[str]:
    return [str(uuid.UUID(hex=k)) for k in keys]


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _epoch(iso: str) -> float:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


def _version_needle(key: str) -> str:
    """How a version key appears inside jsonb text refs ({"assetRef": {..., "versionId": "<key>"}})."""
    return f'"versionId": "{key}"'


# --- revocation ---------------------------------------------------------------------------------------------------------
def _keys_for(ctx, scope: dict) -> list[str] | None:
    """Version keys the revoked grant covered; None means the whole workspace. Asset grants list their snapshotted versions."""
    if scope["kind"] == "workspace":
        return None
    members = [k for k in (scope.get("members") or []) if isinstance(k, str) and c.KEY.fullmatch(k)]
    if scope["kind"] == "asset" and not members:
        ctx.cur.execute(REV_KEYS, (ctx.workspace_id, scope["key"], scope["key"]))
        members = [r[0] for r in ctx.cur.fetchall()] or [scope["key"]]
    return members


def _still_covered(ctx, grant: dict) -> tuple[bool, set]:
    """After the revoke: (an equivalent workspace-wide grant remains, version keys another active grant still covers)."""
    ctx.caches.pop("grants", None)
    if grant["grantType"] == "processing":
        remaining = [g for g in policy.active_grants(ctx) if g["grantType"] == "processing" and g["location"] == grant.get("location")
                     and g["category"] == grant.get("category")]
    else:
        remaining = [g for g in policy.active_grants(ctx) if g["grantType"] == "purpose" and g["purpose"] == grant.get("purpose")]
    if any(g["scopeKind"] == "workspace" for g in remaining):
        return True, set()
    covered = set()
    for g in remaining:
        covered.update(g["memberKeys"] or ([g["scopeKey"]] if g["scopeKind"] == "asset" else []))
    return False, covered


def _voice_withdraw(ctx, keys, *, force: bool):
    try:
        from . import voice
        withdraw = voice.withdraw_for_keys
    except (ImportError, AttributeError):
        return "unavailable"
    return withdraw(ctx, keys, force=force)


def propagate_revocation(ctx, grant: dict) -> dict:
    """Called by policy.revoke inside the revoking transaction, after the grant row is marked revoked."""
    keys = _keys_for(ctx, grant["scope"])
    receipt = {"jobsCancelled": 0, "embeddingsRevoked": 0, "capabilitiesWithdrawn": 0, "voiceSpansWithdrawn": 0, "packsRevoked": 0,
               "suggestionsSuppressed": 0, "stillCovered": 0, "residual": RESIDUAL}
    everything, covered = _still_covered(ctx, grant)
    if everything:
        receipt["stillCovered"] = "all"
        ctx.caches.clear()
        return receipt
    if keys is not None:
        receipt["stillCovered"] = sum(1 for k in keys if k in covered)
        keys = [k for k in keys if k not in covered]
        if not keys:
            ctx.caches.clear()
            return receipt
    else:
        receipt["stillCovered"] = len(covered)
    excluded = sorted(covered)
    # Jobs and capabilities are keyed by version (their asset_key column holds the version key); embeddings carry the
    # lineage in asset_key and the version in version_key, so they are matched on both.
    by_version = "" if keys is None else " AND asset_key=ANY(%s)"
    not_covered = "" if not excluded else " AND NOT (asset_key=ANY(%s))"
    args_v = (() if keys is None else (keys,)) + (() if not excluded else (excluded,))
    if grant["grantType"] == "processing" and grant.get("location") == "cloud":
        capabilities = REVOKE_CAPABILITIES.get(grant.get("category"), ())
        if capabilities:
            ctx.cur.execute(REV_JOBS + by_version + not_covered, (ctx.workspace_id, list(capabilities), *args_v))
            receipt["jobsCancelled"] = ctx.cur.rowcount or 0
            ctx.cur.execute(REV_CAPS + by_version + not_covered, (ctx.workspace_id, list(capabilities), *args_v))
        if grant.get("category") in ("embedding", "vision"):
            modality = ["text", "visual"] if grant["category"] == "embedding" else ["visual"]
            sql, args = REV_EMB, [ctx.workspace_id, modality]
            if keys is not None:
                sql += " AND (asset_key=ANY(%s) OR version_key=ANY(%s))"
                args += [keys, keys]
            if excluded:
                sql += " AND NOT (version_key=ANY(%s))"
                args.append(excluded)
            ctx.cur.execute(sql + " RETURNING version_key,modality", tuple(args))
            revoked = ctx.cur.fetchall()
            receipt["embeddingsRevoked"] = len(revoked)
            by_modality: dict[str, set] = {}
            for version_key, mod in revoked:
                by_modality.setdefault(mod, set()).add(version_key)
            for mod, version_keys in sorted(by_modality.items()):
                ctx.cur.execute(REV_READY, ("Permission was withdrawn, so this item's index entries were removed.", ctx.workspace_id, sorted(version_keys),
                                            MODALITY_CAPABILITY[mod], mod))
                receipt["capabilitiesWithdrawn"] += ctx.cur.rowcount or 0
    if grant["grantType"] == "purpose" and grant.get("purpose") == "voice":
        receipt["voiceSpansWithdrawn"] = _voice_withdraw(ctx, keys, force=False)
    if grant["grantType"] == "purpose" and grant.get("purpose") in ("answer", "memory", "voice"):
        sql, args = REV_PACKS, [ctx.workspace_id]
        if keys is not None:
            sql += " AND (evidence_refs::text ~ ANY(%s) OR style_refs::text ~ ANY(%s))"
            args += [keys, keys]
        ctx.cur.execute(sql, tuple(args))
        receipt["packsRevoked"] = ctx.cur.rowcount or 0
    sql, args = REV_SUGG, [ctx.workspace_id]
    if keys is not None:
        sql += " AND candidate_refs::text ~ ANY(%s)"
        args.append(keys)
    ctx.cur.execute(sql, tuple(args))
    receipt["suggestionsSuppressed"] = ctx.cur.rowcount or 0
    telemetry.record(ctx.cur, "library.lifecycle", "revoked", 1, {"grantType": grant["grantType"], "purpose": grant.get("purpose"),
                                                                    "category": grant.get("category"), "jobs": receipt["jobsCancelled"],
                                                                    "embeddings": receipt["embeddingsRevoked"]}, workspace_id=ctx.workspace_id)
    ctx.caches.clear()
    return receipt


# --- deletion -----------------------------------------------------------------------------------------------------------
def _handoff(ctx, key: str) -> dict:
    """Exact duplicates reference the original's bytes. The oldest sibling takes over the original object and becomes the
    canonical copy (re-queued so the existing worker extracts it); the deleted row is left naming only the redundant copy."""
    ctx.cur.execute(ASSET_LOCK, (ctx.workspace_id, uuid.UUID(hex=key)))
    row = ctx.cur.fetchone()
    if not row:
        return {"promoted": None, "objectToDelete": None, "originalKept": False}
    object_name, bucket, etag, size, mime, extension, kind, _ = row
    ctx.cur.execute(SIBLINGS, (ctx.workspace_id, uuid.UUID(hex=key)))
    siblings = ctx.cur.fetchall()
    if not siblings:
        return {"promoted": None, "objectToDelete": object_name, "originalKept": False}
    heir, heir_object = siblings[0]
    a_id, b_id = uuid.UUID(hex=key), uuid.UUID(hex=heir)
    # Three steps so the unique (workspace_id, object_name) holds at every row update.
    ctx.cur.execute(RENAME, (f"{key}.swap", ctx.workspace_id, a_id))
    ctx.cur.execute(PROMOTE, (object_name, bucket, etag, size, mime, extension, kind, kind, ctx.workspace_id, b_id))
    ctx.cur.execute(RENAME, (heir_object, ctx.workspace_id, a_id))
    ctx.cur.execute(REPOINT, (b_id, ctx.workspace_id, a_id, b_id))
    return {"promoted": heir, "objectToDelete": heir_object, "originalKept": True, "repointed": ctx.cur.rowcount or 0}


def _revoke_vectors(ctx, keys) -> int:
    """Revoke mode: index.tombstone when the keys name only these versions; version-scoped otherwise (a lineage root's key is
    also the asset_key of its later versions, which keep their vectors)."""
    ctx.cur.execute(LINEAGE_OTHERS, (ctx.workspace_id, _uuids(keys), keys))
    others = int((ctx.cur.fetchone() or (0,))[0] or 0)
    if not others:
        try:
            from . import index
            return index.tombstone(ctx.cur, ctx.workspace_id, keys, status="revoked")
        except (ImportError, AttributeError):
            pass
    ctx.cur.execute(EMB_REVOKE, (ctx.workspace_id, keys))
    return ctx.cur.rowcount or 0


def revoke_or_delete_source(ctx, ref, *, mode: str = "delete") -> dict:
    """revoke_or_delete_source(ctx, ref) -> receipt (implementation plan T12).

    `ref` is an AssetRef or a 32-hex version key; the cascade applies to that content version (a legacy photo/video id is
    its own version). mode 'delete' removes content-bearing derivatives (the item is being deleted); mode 'revoke'
    withdraws the version from all intelligence use while the file stays stored (tombstones, blocked capabilities)."""
    if mode not in ("delete", "revoke"):
        c.fail("Use delete or revoke.", 500, "library_internal")
    key = c.asset_ref(ref)["versionId"] if isinstance(ref, dict) else c.asset_key(ref)
    keys, ws = [key], ctx.workspace_id
    deleting = mode == "delete"
    receipt = {"mode": mode, "versionKeys": keys, "residual": RESIDUAL}
    # The duplicate handoff needs only the Universal Library columns (093/094): it runs even before migration 097 exists.
    receipt["sibling"] = _handoff(ctx, key) if deleting else {"promoted": None, "objectToDelete": None, "originalKept": False}
    ctx.cur.execute(INSTALLED)
    if not (ctx.cur.fetchone() or (False,))[0]:
        receipt["intelligence"] = "not_installed"  # no derived Library intelligence data can exist yet
        return receipt
    ctx.cur.execute(JOBS_CANCEL, ("library_source_deleted" if deleting else "library_source_withdrawn", ws, keys))
    receipt["jobsCancelled"] = ctx.cur.rowcount or 0
    if deleting:
        for name, sql, args in (("capabilitiesRemoved", CAPS_DELETE, (ws, keys)), ("segmentsDeleted", SEG_DELETE, (ws, keys)),
                                ("chunksDeleted", CHUNKS, (ws, _uuids(keys))), ("annotationsDeleted", ANN_DELETE, (ws, keys)),
                                ("embeddingsDeleted", EMB_DELETE, (ws, keys))):
            ctx.cur.execute(sql, args)
            receipt[name] = ctx.cur.rowcount or 0
    else:
        ctx.cur.execute(CAPS_WITHDRAW, ("library_source_withdrawn", "This item was withdrawn from Library intelligence; the file stays stored.", ws, keys))
        receipt["capabilitiesWithdrawn"] = ctx.cur.rowcount or 0
        ctx.cur.execute(SEG_SUPERSEDE, (ws, keys))
        receipt["segmentsTombstoned"] = ctx.cur.rowcount or 0
        ctx.cur.execute(ANN_DEACTIVATE, (ws, keys))
        receipt["annotationsDeactivated"] = ctx.cur.rowcount or 0
        receipt["embeddingsRevoked"] = _revoke_vectors(ctx, keys)
    ctx.cur.execute(REL_DROP, (ws, keys, keys))
    receipt["relationsRemoved"] = ctx.cur.rowcount or 0
    ctx.cur.execute(REL_STALE, (json.dumps({"sourceDeleted" if deleting else "sourceWithdrawn": True}), ws, keys, keys))
    receipt["relationsStale"] = ctx.cur.rowcount or 0
    receipt["packsRevoked"] = 0
    for k in keys:
        needle = _version_needle(k)
        ctx.cur.execute(PACKS, (json.dumps([{"code": "source_deleted" if deleting else "source_withdrawn", "versionId": k}]), ws, needle, needle))
        receipt["packsRevoked"] += ctx.cur.rowcount or 0
    ctx.cur.execute(SUGGESTIONS, (ws, keys, keys))
    receipt["suggestionsSuppressed"] = ctx.cur.rowcount or 0
    if deleting:
        for name, sql, args in (("collectionItemsRemoved", ITEMS, (ws, keys)), ("overridesRemoved", OVERRIDES, (ws, keys)),
                                ("usageAnonymized", USAGE, (json.dumps({"sourceDeleted": True}), ws, keys, keys)),
                                ("previewsCleared", CLEAR, (ws, _uuids(keys)))):
            ctx.cur.execute(sql, args)
            receipt[name] = ctx.cur.rowcount or 0
    receipt["voiceSpansWithdrawn"] = _voice_withdraw(ctx, keys, force=True)
    counts = {k: v for k, v in receipt.items() if isinstance(v, int) and not isinstance(v, bool)}
    telemetry.record(ctx.cur, "library.lifecycle", "deleted" if deleting else "withdrawn", 1,
                     {**counts, "siblingPromoted": bool(receipt["sibling"]["promoted"])}, workspace_id=ws)
    ctx.caches.clear()
    return receipt


class _Member:
    """The deletion was authorized by the caller (library_assets.delete / hosted.delete_media); the cascade only reads policy."""
    role = "system"

    def allows(self, requirement):
        return requirement == "read"


def on_source_deleted(cur, workspace_id, asset_key, *, actor=None, service=None) -> dict:
    """Deletion hook for library_assets.delete and hosted.delete_media. Call it inside the transaction that marks the item
    deleted, AFTER any workspace-state write of that transaction (voice withdrawal re-reads and saves the locked state).
    Database errors propagate so the deletion and its cascade commit or roll back together. For a normalized file,
    `receipt['sibling']['objectToDelete']` names the ONLY storage object the caller may delete afterwards."""
    from .jobs import SYSTEM_ACTOR, WS_STATE
    cur.execute(WS_STATE, (str(workspace_id),))
    row = cur.fetchone()
    state = (json.loads(row[0]) if isinstance(row[0], str) else row[0]) if row else None
    ctx = c.LibraryContext(workspace_id=str(workspace_id), actor=str(actor or SYSTEM_ACTOR), membership=_Member(), state=state or {}, cur=cur,
                           service=service)
    return revoke_or_delete_source(ctx, c.asset_key(asset_key), mode="delete")


# --- backfill -------------------------------------------------------------------------------------------------------------
def backfill_paused(environ=None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(PAUSE_ENV, "")).strip().lower() in TRUE


def _checkpoint(connect, scope: str) -> dict | None:
    with connect() as db, db.cursor() as cur:
        cur.execute(BF_CHECKPOINT, (scope,))
        row = cur.fetchone()
    return row[0] if row and isinstance(row[0], dict) else None


def _plan(ctx, version: dict) -> tuple[list[dict], int]:
    """LOCAL default processors this version still needs: no state yet, or a newer processor version than the finished one."""
    chosen: dict[str, dict] = {}
    cloud = 0
    for proc in caps_module.processors_for(version):
        if caps_module.is_local(proc):
            chosen[proc["capability"]] = proc
        else:
            cloud += 1
    states = {s["capability"]: s for s in caps_module.states_for(ctx, version)}
    needed = []
    for capability, proc in chosen.items():
        state = states.get(capability) or {"state": "not_requested"}
        if state["state"] == "not_requested" or (state["state"] in ("ready", "partial", "unsupported")
                                                 and state.get("processorVersion") not in (None, proc["version"])):
            needed.append(proc)
    return needed, cloud


def _items(cur, ctx, ws: str, start: dict, limit: int) -> list[tuple[str, str, str]]:
    """Up to `limit` (phase, versionKey, isoTime) after `start`: normalized rows first, then legacy photos/videos."""
    items = []
    if start["phase"] == "normalized":
        cur.execute(BF_NORMALIZED, (ws, start["at"], str(uuid.UUID(hex=start["id"])), limit))
        items += [("normalized", key, at) for key, at in cur.fetchall()]
        legacy_after = None
    else:
        legacy_after = (_epoch(start["at"]), start["id"])
    if len(items) < limit:
        legacy = sorted(((float(v.get("createdAt") or 0.0), k) for k, v in versions.legacy_assets(ctx).items()))
        items += [("legacy", k, _iso(at)) for at, k in legacy if legacy_after is None or (at, k) > legacy_after][:limit - len(items)]
    return items


def backfill(intel, connect, *, workspace_id=None, limit: int = 100, dry_run: bool = True, restart: bool = False, max_queue: int = 200) -> dict:
    """Bounded, resumable enqueue of LOCAL default capabilities for pre-existing assets (normalized and legacy) that lack
    segments or index rows. Cloud capabilities are never enqueued here: they need grants and per-request cost admission.
    A checkpoint per scope is committed with each workspace batch (content-free: ids and times only), so an interruption
    resumes where it stopped; dry_run only counts. Paused by RAFII_LIBRARY_BACKFILL_PAUSED; bounded by `limit` items per
    run and by `max_queue` queued jobs per workspace (admission against the worker's capacity)."""
    from . import jobs
    report = {"status": "ok", "dryRun": bool(dry_run), "scanned": 0, "candidates": 0, "enqueued": 0, "duplicates": 0, "blocked": 0,
              "cloudSkipped": 0, "byCapability": {}, "cursor": None, "done": False}
    if backfill_paused():
        return {**report, "status": "paused"}
    if not dry_run and not policy.enabled("enrichment"):
        return {**report, "status": "disabled"}
    limit = max(1, min(int(limit), 1000))
    scope = str(workspace_id) if workspace_id else "all"
    cursor = None if restart else _checkpoint(connect, scope)
    if cursor and cursor.get("done"):
        if not dry_run:
            return {**report, "status": "complete", "done": True, "cursor": cursor}
        cursor = None
    position = {k: cursor[k] for k in ("ws", "phase", "at", "id")} if cursor else {"ws": None, "phase": "normalized", "at": EPOCH_START, "id": "0" * 32}
    remaining, throttled, finished = limit, False, True
    with connect() as db, db.cursor() as cur:
        cur.execute(BF_WORKSPACES, (workspace_id, workspace_id, position["ws"], position["ws"], MAX_WORKSPACES))
        spaces = [r[0] for r in cur.fetchall()]
    if len(spaces) >= MAX_WORKSPACES:
        finished = False
    for ws in spaces:
        if remaining <= 0:
            finished = False
            break
        start = position if position["ws"] == ws else {"ws": ws, "phase": "normalized", "at": EPOCH_START, "id": "0" * 32}
        with connect() as db, db.cursor() as cur:
            ctx = jobs.system_context(cur, ws)
            if ctx is None:
                continue
            cur.execute(BF_QUEUED, (ws,))
            queued = int((cur.fetchone() or (0,))[0] or 0)
            asked = remaining
            items = _items(cur, ctx, ws, start, asked)
            moved = False
            for phase, key, at in items:
                version = versions.load(ctx, [key]).get(key)
                needed, cloud = _plan(ctx, version) if version is not None else ([], 0)
                if not dry_run and needed and queued + len(needed) > max_queue:
                    throttled = True
                    break
                report["scanned"] += 1
                report["cloudSkipped"] += cloud
                report["candidates"] += 1 if needed else 0
                for proc in needed:
                    report["byCapability"][proc["capability"]] = report["byCapability"].get(proc["capability"], 0) + 1
                    if dry_run:
                        continue
                    out = jobs.enqueue_capability(ctx, versions.ref(version), proc["capability"], proc["version"])
                    if out["duplicate"]:
                        report["duplicates"] += 1
                    elif out["job"] is None:
                        report["blocked"] += 1
                    else:
                        report["enqueued"] += 1
                        queued += 1
                position, moved = {"ws": ws, "phase": phase, "at": at, "id": key}, True
                remaining -= 1
            if not dry_run and moved:
                telemetry.record(cur, "library.backfill", "checkpoint", report["enqueued"], {"scope": scope, **position, "done": False},
                                 workspace_id=workspace_id)
        if throttled or len(items) >= asked:
            finished = False
            break
    report["cursor"] = position
    report["done"] = finished and not throttled
    report["status"] = "dry_run" if dry_run else "throttled" if throttled else "complete" if report["done"] else "partial"
    if not dry_run and report["done"]:
        with connect() as db, db.cursor() as cur:
            telemetry.record(cur, "library.backfill", "checkpoint", report["enqueued"], {"scope": scope, **position, "done": True},
                             workspace_id=workspace_id)
    return report


# --- index generations ---------------------------------------------------------------------------------------------------
def _vectors_by_generation(ctx) -> dict:
    ctx.cur.execute(GEN_VECTORS, (ctx.workspace_id,))
    return {str(int(g)): int(n) for g, n in ctx.cur.fetchall()}


def bump_index_generation(ctx, *, reason: str = "model_change") -> dict:
    """Start a new index generation (e.g. a new embedding model). Search reads only the active generation, so until a
    backfill (restart=True) re-embeds, semantic coverage is reported as partial and lexical results continue."""
    ctx.require("owner")
    revs = policy.bump(ctx, index=True)
    from ..hosted import audit
    audit(ctx.cur, ctx.workspace_id, ctx.actor, "library.index_generation_bumped", str(revs["indexGeneration"]),
          {"reason": reason if isinstance(reason, str) and telemetry.CODE.fullmatch(reason) else "unspecified"})
    return {**revs, "activeVectors": _vectors_by_generation(ctx)}


def rollback_index_generation(ctx, generation: int) -> dict:
    """Make an earlier generation active again (a new model generation misbehaved). Only that generation's still-active
    vectors are read; when none remain (the same model re-embedded and superseded them) search honestly falls back."""
    ctx.require("owner")
    revs = policy.revisions(ctx, fresh=True)
    if type(generation) is not int or not 1 <= generation < revs["indexGeneration"]:
        raise AlphaError("Choose an earlier index generation.", 422, code="library_generation_invalid")
    ctx.cur.execute(GEN_SET, (generation, ctx.workspace_id))
    row = ctx.cur.fetchone()
    ctx.caches.clear()
    ctx.caches["policy"] = {"grantRevision": int(row[0]), "indexGeneration": int(row[1]), "organizationRevision": int(row[2])}
    from ..hosted import audit
    audit(ctx.cur, ctx.workspace_id, ctx.actor, "library.index_generation_rolled_back", str(generation), {"from": revs["indexGeneration"]})
    vectors = _vectors_by_generation(ctx)
    return {**ctx.caches["policy"], "activeVectorsInGeneration": vectors.get(str(generation), 0), "activeVectors": vectors}
