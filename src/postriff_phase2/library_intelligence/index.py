"""Embedding index for Library retrieval (engineering spec §4 EmbeddingRecord, §8; implementation plan T04).

Processors (registered with capabilities.register when worker A's module is present; always listed in PROCESSORS):

* `embed_visual` — `local/visual-perceptual-v1`, LOCAL and allowed by default (policy.LOCAL_DEFAULTS ('local',
  'embedding')). A 256-d L2-normalised perceptual vector computed with Pillow from the image itself, or from a video's
  poster frame. Design (deterministic, no model, no network):
    - 144 dims: 12×12 grayscale thumbnail, z-scored (brightness/contrast invariant) — layout and structure;
    - 96 dims: joint HSV colour histogram (8 hue × 4 saturation × 3 value bins), square-rooted (Hellinger) — palette;
    - 16 dims: 8-bin gradient-orientation histogram, 4 quadrant brightness offsets, aspect ratio, mean brightness,
      contrast and mean saturation — texture and composition.
  Each block is L2-normalised and weighted (0.6, 0.6, 0.5) before the final L2 normalisation, so cosine distance
  compares layout, colour and texture. It is perceptual similarity, not object or scene understanding, and never
  identifies people. Text captions are lexical evidence and never count as visual similarity.
* `embed_text` — cloud gateway text embeddings (providers.embed, 1024-d), grant-gated as processing ('cloud',
  'embedding'): storage-only or unconsented items are never sent. Embeds the version's active segments.

An optional cloud multimodal visual model (text → image search) is not available: providers.py has no multimodal
embedding route. Visual search therefore needs an example item (similarTo) and says so; enabling a multimodal model
needs a provider adapter plus James's paid-inference authorisation.

write_embeddings detects the pgvector `embedding` column at runtime. Without it nothing is stored and the caller is told
(`vector: False`), so capability states can say "unavailable" instead of pretending vectors exist. Stored rows carry
model_id, dims, index_generation and consent_revision; searches never compare different models, sizes or generations.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import uuid
from collections import OrderedDict
from contextlib import contextmanager

from postriff_alpha.domain import AlphaError

from . import contracts as c
from . import providers as providers_module

VISUAL_MODEL = "local/visual-perceptual-v1"
VISUAL_DIMS = 256
TEXT_DIMS = providers_module.EMBED_DIMS
TEXT_PROCESSOR_VERSION = "gateway-text-1024-v1"
MAX_VISUAL_BYTES = 40 * 1024 * 1024
MAX_VISUAL_PIXELS = 64_000_000
MAX_TEXT_SEGMENTS = 512
EMBED_BATCH = 64
QUERY_CACHE_SIZE = 256

VECTOR_COLUMN_SQL = ("/* lib:vector-column */ SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
                     "AND table_name='pr_library_embeddings' AND column_name='embedding'")
SUPERSEDE_SQL = ("/* lib:embeddings-supersede */ UPDATE public.pr_library_embeddings SET status='superseded',superseded_at=now() WHERE workspace_id=%(w)s "
                 "AND version_key=%(vk)s AND modality=%(modality)s AND model_id=%(model)s AND status='active'")
INSERT_SQL = ("/* lib:embeddings-insert */ INSERT INTO public.pr_library_embeddings(id,workspace_id,asset_key,version_key,segment_id,modality,model_id,"
              "dims,index_generation,consent_revision,status,embedding) VALUES(%(id)s,%(w)s,%(ak)s,%(vk)s,%(sid)s,%(modality)s,%(model)s,%(dims)s,"
              "%(gen)s,%(consent)s,'active',%(vec)s::vector)")
TOMBSTONE_SQL = ("/* lib:embeddings-tombstone */ UPDATE public.pr_library_embeddings SET status=%(status)s,"
                 "superseded_at=CASE WHEN %(status)s='superseded' THEN now() ELSE superseded_at END WHERE workspace_id=%(w)s AND status='active' "
                 "AND (asset_key=ANY(%(keys)s::text[]) OR version_key=ANY(%(keys)s::text[])) AND (%(modality)s::text IS NULL OR modality=%(modality)s) "
                 "AND (NOT %(cloud_only)s OR model_id NOT LIKE 'local/%%')")
INACTIVE_SEGMENTS_SQL = ("/* lib:embeddings-inactive-segments */ UPDATE public.pr_library_embeddings e SET status='superseded',superseded_at=now() "
                         "WHERE e.workspace_id=%(w)s AND e.version_key=%(vk)s AND e.status='active' AND e.segment_id IS NOT NULL AND EXISTS ("
                         "SELECT 1 FROM public.pr_library_segments s WHERE s.id=e.segment_id AND s.workspace_id=e.workspace_id AND s.superseded_at IS NOT NULL)")
SEGMENTS_FOR_EMBEDDING_SQL = ("/* lib:segments-for-embedding */ SELECT replace(id::text,'-',''),text FROM public.pr_library_segments "
                              "WHERE workspace_id=%(w)s AND version_key=%(vk)s AND superseded_at IS NULL ORDER BY ordinal LIMIT %(n)s")

# Test seams for budget admission; production uses the coordinator's providers.reserve/settle.
_reserve = providers_module.reserve
_settle = providers_module.settle
_QUERY_CACHE: OrderedDict = OrderedDict()


# --- perceptual visual vectors ---------------------------------------------------------------------------------------
def _unit(values):
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values] if norm > 1e-12 else [0.0 for _ in values]


def visual_features(raw: bytes) -> list[float]:
    """256-d perceptual vector for one image (see module docstring). Raises ValueError/OSError for undecodable input."""
    from PIL import Image, ImageOps

    if not raw or len(raw) > MAX_VISUAL_BYTES:
        raise ValueError("image is empty or too large")
    with Image.open(io.BytesIO(raw)) as opened:
        width, height = opened.size
        if width < 1 or height < 1 or width * height > MAX_VISUAL_PIXELS:
            raise ValueError("image dimensions are out of range")
        opened.draft("RGB", (256, 256))
        image = ImageOps.exif_transpose(opened).convert("RGB")
    width, height = image.size
    image.thumbnail((256, 256), Image.Resampling.BILINEAR)

    gray12 = [v / 255.0 for v in image.convert("L").resize((12, 12), Image.Resampling.BOX).tobytes()]
    mean = sum(gray12) / len(gray12)
    std = math.sqrt(sum((v - mean) ** 2 for v in gray12) / len(gray12))
    structure = _unit([(v - mean) / std for v in gray12]) if std > 1e-6 else [0.0] * 144

    hist = [0.0] * 96
    packed = image.resize((48, 48), Image.Resampling.BOX).convert("HSV").tobytes()
    hsv = list(zip(packed[0::3], packed[1::3], packed[2::3]))
    for h, s, v in hsv:
        hist[(h * 8 // 256) * 12 + (s * 4 // 256) * 3 + (v * 3 // 256)] += 1.0
    palette = _unit([math.sqrt(x / len(hsv)) for x in hist])

    g = [v / 255.0 for v in image.convert("L").resize((32, 32), Image.Resampling.BOX).tobytes()]
    orientation = [0.0] * 8
    for y in range(1, 31):
        for x in range(1, 31):
            gx = g[y * 32 + x + 1] - g[y * 32 + x - 1]
            gy = g[(y + 1) * 32 + x] - g[(y - 1) * 32 + x]
            magnitude = math.hypot(gx, gy)
            if magnitude > 1e-6:
                orientation[int((math.atan2(gy, gx) % math.pi) / math.pi * 8) % 8] += magnitude
    total = sum(orientation)
    orientation = [math.sqrt(v / total) for v in orientation] if total > 1e-9 else [0.0] * 8
    gmean = sum(g) / len(g)
    quadrants = [sum(g[y * 32 + x] for y in range(qy, qy + 16) for x in range(qx, qx + 16)) / 256.0 - gmean
                 for qy in (0, 16) for qx in (0, 16)]
    aspect = max(-1.0, min(1.0, math.log(width / height) / 2))
    gstd = math.sqrt(sum((v - gmean) ** 2 for v in g) / len(g))
    saturation = sum(s for _, s, _ in hsv) / (255.0 * len(hsv))
    texture = _unit(orientation + [2 * q for q in quadrants] + [aspect, gmean, gstd, saturation])

    vector = _unit([0.6 * v for v in structure] + [0.6 * v for v in palette] + [0.5 * v for v in texture])
    assert len(vector) == VISUAL_DIMS
    return [round(v, 6) for v in vector]


# --- storage ---------------------------------------------------------------------------------------------------------
def vector_available(cur) -> bool:
    """Whether pgvector's `embedding` column exists (migration 097 adds it only where the extension is available)."""
    cur.execute(VECTOR_COLUMN_SQL)
    return cur.fetchone() is not None


def vector_available_ctx(ctx) -> bool:
    if "vectorColumn" not in ctx.caches:
        ctx.caches["vectorColumn"] = vector_available(ctx.cur)
    return ctx.caches["vectorColumn"]


def vector_literal(values) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def _segment_uuid(value):
    if value is None:
        return None
    key = str(value).replace("-", "").lower()
    if not c.KEY.fullmatch(key):
        c.fail("Embedding segment ids must be Library segment ids.")
    return str(uuid.UUID(hex=key))


def _validate(item) -> dict:
    if not isinstance(item, dict):
        c.fail("Send embedding records.")
    modality, model, dims, vector = item.get("modality"), item.get("modelId"), item.get("dims"), item.get("vector")
    if modality not in ("text", "visual"):
        c.fail("Embedding modality must be text or visual.")
    if not isinstance(model, str) or not 1 <= len(model) <= 120:
        c.fail("Name the embedding model.")
    if type(dims) is not int or not 8 <= dims <= 4096 or not isinstance(vector, list) or len(vector) != dims:
        c.fail("Embedding dimensions do not match the vector.")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector):
        c.fail("Embedding values must be finite numbers.")
    normalised = _unit([float(v) for v in vector])
    if not any(normalised):
        c.fail("An embedding cannot be all zeros.")
    return {"modality": modality, "modelId": model, "dims": dims, "vector": normalised, "segmentId": _segment_uuid(item.get("segmentId"))}


def write_embeddings(cur, workspace_id, version: dict, items, *, consent_revision: int, index_generation: int) -> dict:
    """Store one version's embeddings, superseding that version's earlier rows for the same modality and model.

    Called by the job completion path after the grant recheck. Returns {stored, superseded, vector, reason?}; without the
    pgvector column nothing is written and `vector` is False (the capability is honestly unavailable)."""
    version_key = c.asset_key(version["versionId"])
    asset_key = c.asset_key(version.get("assetId") or version_key)
    parsed = [_validate(item) for item in (items or [])]
    if type(consent_revision) is not int or type(index_generation) is not int or consent_revision < 0 or index_generation < 1:
        c.fail("Embeddings need their consent revision and index generation.")
    if not parsed:
        return {"stored": 0, "superseded": 0, "vector": None}
    if not vector_available(cur):
        return {"stored": 0, "superseded": 0, "vector": False, "reason": "vector_unavailable"}
    superseded = 0
    for modality, model in sorted({(p["modality"], p["modelId"]) for p in parsed}):
        cur.execute(SUPERSEDE_SQL, {"w": workspace_id, "vk": version_key, "modality": modality, "model": model})
        superseded += cur.rowcount or 0
    for p in parsed:
        cur.execute(INSERT_SQL, {"id": str(uuid.uuid4()), "w": workspace_id, "ak": asset_key, "vk": version_key, "sid": p["segmentId"],
                                 "modality": p["modality"], "model": p["modelId"], "dims": p["dims"], "gen": index_generation,
                                 "consent": consent_revision, "vec": vector_literal(p["vector"])})
    return {"stored": len(parsed), "superseded": superseded, "vector": True, "models": sorted({p["modelId"] for p in parsed})}


def tombstone(cur, workspace_id, keys, *, status: str, modality: str | None = None, cloud_only: bool = False) -> int:
    """Mark active embeddings of these asset/version keys 'revoked' or 'superseded'. Never deletes rows."""
    if status not in ("revoked", "superseded"):
        c.fail("Use revoked or superseded.", 500, "library_internal")
    keys = [c.asset_key(k) for k in keys]
    if not keys:
        return 0
    cur.execute(TOMBSTONE_SQL, {"status": status, "w": workspace_id, "keys": keys, "modality": modality, "cloud_only": bool(cloud_only)})
    return cur.rowcount or 0


def tombstone_inactive_segments(cur, workspace_id, version_key: str) -> int:
    """Supersede the active embeddings of this version whose passage was corrected or re-extracted. The corrected text is
    embedded again by the next embed_text run. Cleanup inside its own savepoint: search's kNN independently refuses
    embeddings of superseded passages, so a failure here only delays this cleanup and never resurfaces old wording or
    aborts the caller's transaction."""
    savepoint = _savepoint(cur, "lib_tombstone")
    try:
        cur.execute(INACTIVE_SEGMENTS_SQL, {"w": workspace_id, "vk": c.asset_key(version_key)})
        changed = cur.rowcount or 0
    except Exception as error:
        if savepoint is None:
            raise
        _rollback(cur, savepoint)
        print(json.dumps({"event": "library_intelligence.embedding_tombstone_failed", "error": type(error).__name__}), flush=True)
        return 0
    _release(cur, savepoint)
    return changed


# --- query embeddings ------------------------------------------------------------------------------------------------
def providers_for(ctx):
    if "providers" not in ctx.caches:
        intelligence = getattr(ctx.service, "library_intelligence", None)
        found = getattr(intelligence, "providers", None) if intelligence is not None else None
        ctx.caches["providers"] = found if found is not None else providers_module.Providers()
    return ctx.caches["providers"]


@contextmanager
def ledger_cursor(ctx):
    """A short transaction of its own for one budget reservation or settlement, committed on exit. Ledger.reserve locks
    workspace and global budget rows; holding them across a provider call would block every paid reservation in every
    tenant, and a request rollback would erase a settlement. Without a connection factory (unit tests, detached
    callers) it falls back to a savepoint on the request cursor."""
    factory = getattr(getattr(ctx.service, "repository", None), "connection_factory", None)
    if callable(factory):
        with factory() as db, db.cursor() as cur:
            yield cur
        return
    savepoint = _savepoint(ctx.cur, "lib_ledger")
    try:
        yield ctx.cur
    except BaseException:
        _rollback(ctx.cur, savepoint)
        raise
    _release(ctx.cur, savepoint)


def possibly_billed(error) -> bool:
    """The provider answered 200 but the body was unusable, so the call may have been billed (settle as unknown, never as
    a free failure). Refusals, rate limits and timeouts are not billed."""
    text = str(error).lower()
    return isinstance(error, AlphaError) and error.code == "library_provider_failed" and ("unreadable" in text or "unexpected shape" in text)


def _settle_committed(ctx, settle, reservation, result, *, failed: bool):
    try:
        with ledger_cursor(ctx) as cur:
            settle(cur, ctx.workspace_id, reservation, result, failed=failed)
    except Exception as error:  # the reservation stays open for the ledger's own expiry; never hide the provider's outcome
        print(json.dumps({"event": "library_intelligence.settle_failed", "error": type(error).__name__}), flush=True)


def paid_call(ctx, *, capability: str, model: str, estimate_usd_micro: int, key: str, call, reserve=None, settle=None):
    """Reserve (short committed transaction) -> provider call with no budget lock held -> settle (short committed
    transaction). Raises ProviderUnavailable(capability, 'blocked_budget' | 'budget_unavailable') when nothing was
    reserved (then no ledger row exists). A provider failure is settled first (failed, or unknown when possibly billed)
    and then re-raised."""
    reserve = reserve or _reserve
    settle = settle or _settle
    try:
        with ledger_cursor(ctx) as cur:
            reservation = reserve(cur, ctx.workspace_id, ctx.actor, capability=capability, estimate_usd_micro=estimate_usd_micro, key=key, model=model)
    except Exception as error:
        raise providers_module.ProviderUnavailable(capability, "budget_unavailable") from error
    if (reservation or {}).get("status") != "reserved":
        raise providers_module.ProviderUnavailable(capability, "blocked_budget")
    try:
        result = call()
    except Exception as error:
        _settle_committed(ctx, settle, reservation, None, failed=not possibly_billed(error))
        raise
    _settle_committed(ctx, settle, reservation, result, failed=False)
    return result


def embed_query(ctx, text: str) -> tuple[list[float], str]:
    """The user's query text through the gateway (it is the user's own input, not Library content). Budget-reserved in
    short transactions of its own (paid_call); cached per process by (workspace, model, dims, text) so paging never pays
    twice. Raises ProviderUnavailable or AlphaError; the caller degrades to labelled lexical results."""
    prov = providers_for(ctx)
    prov.require("embedding")
    model = prov.model("embedding")
    cache_key = (str(ctx.workspace_id), model, TEXT_DIMS, hashlib.sha256(text.encode()).hexdigest())
    if cache_key in _QUERY_CACHE:
        _QUERY_CACHE.move_to_end(cache_key)
        return list(_QUERY_CACHE[cache_key]), model
    result = paid_call(ctx, capability="embedding", model=model, estimate_usd_micro=prov.estimate("embedding", units=max(1, len(text))),
                       key="search-embed:" + uuid.uuid4().hex, call=lambda: prov.embed([text], dims=TEXT_DIMS))
    vector = [float(v) for v in result.value[0]]
    _QUERY_CACHE[cache_key] = vector
    while len(_QUERY_CACHE) > QUERY_CACHE_SIZE:
        _QUERY_CACHE.popitem(last=False)
    return list(vector), model


def _savepoint(cur, name):
    try:
        cur.execute(f"SAVEPOINT {name}")
        return name
    except Exception:  # autocommit connections have no transaction block; nothing to protect
        return None


def _rollback(cur, name):
    if name:
        cur.execute(f"ROLLBACK TO SAVEPOINT {name}")


def _release(cur, name):
    if name:
        cur.execute(f"RELEASE SAVEPOINT {name}")


# --- processors ------------------------------------------------------------------------------------------------------
def _outcome(state, *, embeddings=(), media=None, provider=None, error_code=None, detail=None, retryable=False) -> dict:
    return {"state": state, "segments": [], "annotations": [], "embeddings": list(embeddings), "media": dict(media or {}),
            "provider": provider, "errorCode": error_code, "detail": detail, "retryable": bool(retryable)}


def _applies_visual(version) -> bool:
    return (version or {}).get("kind") in ("image", "video")


def _visual_source(job):
    """Image bytes, or the video's poster frame through JobContext.poster() (bounded private read with hash check)."""
    version = job.version or {}
    if version.get("kind") == "video":
        poster = getattr(job, "poster", None)
        return ("poster", poster() if callable(poster) else None)
    raw = getattr(job, "raw", None)
    return ("original", raw() if callable(raw) else None)


def _run_visual(job) -> dict:
    try:
        source, raw = _visual_source(job)
    except AlphaError as error:
        return _outcome("failed", error_code=error.code or "storage_unavailable", detail=str(error)[:300], retryable=error.status >= 500)
    if not raw:
        return _outcome("unsupported", error_code="no_visual_source", detail="No image or poster frame is available for visual indexing.")
    try:
        vector = visual_features(raw)
    except Exception:  # untrusted image bytes: any decoder failure is a clear state, never a crash or a retry loop
        return _outcome("failed", error_code="image_decode_failed", detail="This image could not be decoded for visual indexing.")
    return _outcome("ready", embeddings=[{"modality": "visual", "modelId": VISUAL_MODEL, "dims": VISUAL_DIMS, "vector": vector, "segmentId": None}],
                    media={"visualSource": source})


def _job_segments(job):
    segments = getattr(job, "segments", None)
    if callable(segments):
        return [s for s in segments() or [] if isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"].strip()]
    cur = getattr(job, "cur", None)
    if cur is None:
        return None
    cur.execute(SEGMENTS_FOR_EMBEDDING_SQL, {"w": job.workspace_id, "vk": job.version["versionId"], "n": MAX_TEXT_SEGMENTS + 1})
    return [{"id": r[0], "text": r[1]} for r in cur.fetchall() if isinstance(r[1], str) and r[1].strip()]


def _combine_receipts(receipts):
    if not receipts:
        return None
    costs = [r["cost"] for r in receipts]
    if all(cost.get("kind") == "actual" for cost in costs):
        cost = {"kind": "actual", "usdMicro": sum(int(x["usdMicro"]) for x in costs)}
    elif any(cost.get("kind") == "unknown" for cost in costs):
        cost = {"kind": "unknown", "usdMicro": None}
    else:
        cost = {"kind": "estimated", "usdMicro": sum(int(x["usdMicro"] or 0) for x in costs), "version": providers_module.ESTIMATE_VERSION}
    tokens = [r["usage"].get("inputTokens") for r in receipts]
    return {"provider": receipts[0]["provider"], "model": receipts[0]["model"], "latencyMs": sum(r["latencyMs"] for r in receipts),
            "usage": {"inputTokens": sum(tokens) if all(isinstance(t, int) for t in tokens) else None}, "cost": cost, "calls": len(receipts)}


def _job_member(job, name):
    return job.get(name) if isinstance(job, dict) else getattr(job, name, None)


def _may_continue(job) -> bool:
    """Immediately before each provider call: job.recheck() re-authorizes cloud processing in a fresh short transaction
    (worker A's JobContext); without it, job.heartbeat() at least confirms the lease was not cancelled or revoked."""
    for name in ("recheck", "heartbeat"):
        check = _job_member(job, name)
        if callable(check):
            return bool(check())
    return True


def _run_text(job) -> dict:
    prov = getattr(job, "providers", None) or providers_module.Providers()
    try:
        prov.require("embedding")
    except providers_module.ProviderUnavailable as error:
        return _outcome("failed", error_code="provider_unavailable", detail=f"Text embeddings are unavailable ({error.reason}).")
    segments = _job_segments(job)
    if segments is None:
        return _outcome("unsupported", error_code="segments_unavailable", detail="This job cannot read the item's passages.")
    if not segments:
        return _outcome("unsupported", error_code="no_text", detail="This item has no extracted passages to embed.")
    selected = segments[:MAX_TEXT_SEGMENTS]
    model = prov.model("embedding")
    embeddings, receipts = [], []
    for start in range(0, len(selected), EMBED_BATCH):
        batch = selected[start:start + EMBED_BATCH]
        if not _may_continue(job):  # revoked or cancelled while running: send nothing more and keep nothing already made
            return _outcome("blocked_permission", provider=_combine_receipts(receipts), error_code="library_processing_revoked",
                            detail="Cloud processing is no longer allowed for this item.")
        try:
            result = prov.embed([s["text"] for s in batch], dims=TEXT_DIMS)
        except AlphaError as error:
            retryable = error.status >= 500 or error.code in ("library_provider_rate_limited", "library_provider_timeout")
            state = "partial" if embeddings else "failed"
            return _outcome(state, embeddings=embeddings, provider=_combine_receipts(receipts), error_code=error.code, detail=str(error)[:300], retryable=retryable)
        receipts.append(result.receipt())
        for s, vector in zip(batch, result.value):
            embeddings.append({"modality": "text", "modelId": result.model or model, "dims": TEXT_DIMS, "vector": vector, "segmentId": s.get("id")})
    truncated = len(segments) > MAX_TEXT_SEGMENTS
    return _outcome("partial" if truncated else "ready", embeddings=embeddings, provider=_combine_receipts(receipts),
                    detail=f"The first {MAX_TEXT_SEGMENTS} passages were embedded." if truncated else None)


def _estimate_text(job):
    prov = getattr(job, "providers", None) or providers_module.Providers()
    chars = min(int((job.version or {}).get("bytes") or 0), MAX_TEXT_SEGMENTS * 8000)
    return prov.estimate("embedding", units=max(1, chars // 3))


EMBED_VISUAL = {"capability": "embed_visual", "version": VISUAL_MODEL, "location": "local", "category": "embedding", "modality": "visual",
                "dims": VISUAL_DIMS, "applies": _applies_visual, "estimate": lambda job: 0, "run": _run_visual}
EMBED_TEXT = {"capability": "embed_text", "version": TEXT_PROCESSOR_VERSION, "location": "cloud", "category": "embedding", "modality": "text",
              "dims": TEXT_DIMS, "applies": lambda version: (version or {}).get("kind") in ("document", "audio", "video", "image", "file"),
              "estimate": _estimate_text, "run": _run_text}
PROCESSORS = [EMBED_TEXT, EMBED_VISUAL]


def _register() -> bool:
    try:
        from . import capabilities
        register = capabilities.register
    except (ImportError, AttributeError):
        return False
    for processor in PROCESSORS:
        register(processor)
    return True


REGISTERED = _register()
