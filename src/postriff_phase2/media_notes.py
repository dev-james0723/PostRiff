"""Metered, consent-gated notes about a workspace photo or a video's frames (chat-context SPEC §5.6, §8.2).

A note is a machine description ("what is visible") a writer may use for a Reference attachment. Each read is its own
`tool` reservation with the vision provider and model, so ledger rows name the right processor, and a note is cached
per workspace by (asset, asset hash, reader version) so the same photo is read once. Consent (`media_consent`) is
checked before reserving and again right before the provider call; a revocation in between wins. Nothing here runs
inside a writing run.
"""
from __future__ import annotations

import io
import json
import re
import time

from postriff_alpha.domain import AlphaError

from . import ai_call_events, asset_kinds, media_consent

READER_VERSION = "notes-v1"
PROMPT_TOKENS = 700
IMAGE_TOKENS_CEILING = 1600
IMAGE_TOKENS_TYPICAL = 800
OUTPUT_CAP = {"photo": 700, "video_frames": 1200}
OUTPUT_TYPICAL = {"photo": 350, "video_frames": 600}
PHOTO_EDGE = 1536
FRAME_EDGE = 1024
MAX_FRAMES = 4
NOTE_MAX_CHARS = 1200
MAX_ATTEMPTS = 3
ATTEMPT_WINDOW = 24 * 3600
READING_STALE = 120          # a `reading` row older than this is a crashed read and may be retried
TIMEOUT_SECONDS = 30
ASSET_ID = re.compile(r"^[0-9a-f]{32}$")
QUESTION = ("Describe what is visible so a writer can mention it accurately: subject, setting, mood, visible text. "
            "Do not identify people by name.")
TEXT_PREFIX = "Text seen in the image (data):"
SIGN_IN = "Sign in to read photos."

MESSAGES = {
    "consent_required": "The workspace owner hasn't allowed Rafii to look at photos and videos.",
    "reader_unavailable": "Photo reading isn't available here.",
    "media_not_ready": "This upload isn't finished.",
    "no_frames": "Rafii has no frames from this video to look at.",
    "read_failed": "Rafii couldn't read it. Try again from the attachment.",
}


def kind_for(asset):
    return "video_frames" if asset_kinds.kind_of(asset) == "video" else "photo"


def frame_count(asset):
    return min(MAX_FRAMES, len(asset.get("frames") or [])) if kind_for(asset) == "video_frames" else 1


def downscale(raw, edge):
    """JPEG bytes whose longer edge is at most `edge` (Pillow; the same decoder the upload path uses)."""
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB")
        image.thumbnail((edge, edge))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=85)
        return out.getvalue()


def render_note(findings, kind):
    """Plain note text ≤ 1,200 characters. Text seen in the image is quoted and marked as data."""
    parts = [str(findings.get("description") or "").strip()]
    composition = [str(item).strip() for item in findings.get("composition") or [] if str(item).strip()]
    if composition:
        parts.append("; ".join(composition[:4]))
    seen = [str(item).strip() for item in findings.get("visibleText") or [] if str(item).strip()]
    if seen:
        parts.append(TEXT_PREFIX + " " + "; ".join(f"“{text[:200]}”" for text in seen[:6]))
    if kind == "video_frames":
        parts.insert(0, "From frames of the video.")
    text = "\n".join(part for part in parts if part)
    return text[:NOTE_MAX_CHARS]


class MediaReader:
    """One vision request per read: the photo, or up to 4 frames in one request."""

    def __init__(self, cfg, transport=None, *, enabled=False):
        from .agent_runtime_v2 import creative
        self.cfg = cfg
        self.transport = transport or creative.https_json
        self.enabled = bool(enabled)

    def route(self):
        return self.cfg.route("vision", reason="photo and video notes")

    def processor(self):
        route = self.route()
        return media_consent.processor(route.provider, route.model) if route.available else None

    @property
    def available(self):
        route = self.route()
        return self.enabled and route.available and self.cfg.estimate_usd_micro(route.model, 1, 1) is not None

    def estimate(self, kind, frames=1):
        """{typical, ceiling} in micro-USD for one read, from the configured price table (SPEC §8.2)."""
        route = self.route()
        images = max(1, min(MAX_FRAMES, frames))
        typical = self.cfg.estimate_usd_micro(route.model, PROMPT_TOKENS + IMAGE_TOKENS_TYPICAL * images, OUTPUT_TYPICAL[kind])
        ceiling = self.cfg.estimate_usd_micro(route.model, PROMPT_TOKENS + IMAGE_TOKENS_CEILING * images, OUTPUT_CAP[kind])
        return {"typicalUsdMicro": typical, "ceilingUsdMicro": ceiling, "model": route.model, "provider": route.provider}

    def read(self, images, kind, timeout=TIMEOUT_SECONDS):
        """Call the vision route. Raises creative.CreativeError (with `uncertain`) on failure. A request that reached the
        provider is one pr_ai_call_events attempt in the caller's ai_call_events scope (Founder Admin §8.B)."""
        meter = {}
        try:
            return self._read(images, kind, timeout, meter)
        finally:
            if meter:
                began = meter.pop("began")
                ai_call_events.attempt(workload="vision", latency_ms=round((time.monotonic() - began) * 1000), **meter)

    def _read(self, images, kind, timeout, meter):
        from .agent_runtime_v2 import creative
        route = self.route()
        if not route.available:
            raise creative.CreativeError(route.blocker or "No vision route is configured.", 503, code="route_unavailable")
        key = self.cfg.credential(route.provider)
        user_text = f"Question: {QUESTION}\n" + ("These are frames from one video, in order." if kind == "video_frames" else "")
        started = time.monotonic()
        meter.update(began=started, started_at=time.time(), status="unknown", provider=route.provider, model=route.model)
        if route.provider == "openai":
            content = [{"type": "input_text", "text": user_text}] + [{"type": "input_image", "image_url": creative._data_url(raw, mime)} for raw, mime in images]
            response = self.transport("POST", "https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}"}, body={
                "model": route.model, "instructions": creative.VISION_SYSTEM, "store": False, "max_output_tokens": OUTPUT_CAP[kind],
                "input": [{"role": "user", "content": content}],
                "text": {"format": {"type": "json_schema", "name": "media_notes", "schema": creative.VISION_SCHEMA, "strict": True}}}, timeout=timeout)
            status, body = response.get("status"), response.get("body") or {}
            _meter_response(meter, status)
            if status != 200:
                raise creative._status_error(status, body)
            text = body.get("output_text") or "".join(part.get("text", "") for item in body.get("output") or [] if isinstance(item, dict) and item.get("type") == "message"
                                                      for part in item.get("content") or [] if isinstance(part, dict))
        else:
            content = [{"type": "text", "text": user_text}] + [{"type": "image_url", "image_url": {"url": creative._data_url(raw, mime)}} for raw, mime in images]
            response = self.transport("POST", "https://ai-gateway.vercel.sh/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, body={
                "model": route.model, "reasoning_effort": "none", "max_tokens": OUTPUT_CAP[kind],
                "response_format": {"type": "json_schema", "json_schema": {"name": "media_notes", "schema": creative.VISION_SCHEMA, "strict": True}},
                "messages": [{"role": "system", "content": creative.VISION_SYSTEM}, {"role": "user", "content": content}]}, timeout=timeout)
            status, body = response.get("status"), response.get("body") or {}
            _meter_response(meter, status)
            if status != 200:
                raise creative._status_error(status, body)
            text = ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        usage = body.get("usage") or {}
        tokens_in = usage.get("input_tokens") or usage.get("prompt_tokens")
        tokens_out = usage.get("output_tokens") or usage.get("completion_tokens")
        meter.update(input_tokens=tokens_in, output_tokens=tokens_out, **_meter_cost(self.cfg, route.model, tokens_in, tokens_out))
        try:
            findings = json.loads(text)
        except (TypeError, ValueError) as error:
            raise creative.CreativeError("The vision model's answer was unreadable; no note was kept.", 502, uncertain=True, code="vision_unreadable") from error
        if not isinstance(findings, dict):
            raise creative.CreativeError("The vision model's answer was unreadable; no note was kept.", 502, uncertain=True, code="vision_unreadable")
        cost = self.cfg.estimate_usd_micro(route.model, tokens_in, tokens_out) if isinstance(tokens_in, int) and isinstance(tokens_out, int) else None
        return {"text": render_note(findings, kind), "model": route.model, "provider": route.provider, "costUsdMicro": cost,
                "usage": {"inputTokens": tokens_in, "outputTokens": tokens_out}, "latencyMs": round((time.monotonic() - started) * 1000)}


def _meter_response(meter, status):
    """The HTTP outcome of a read for its pr_ai_call_events attempt: a 429 or other 4xx was refused before any work (it costs
    nothing), a 5xx or no answer leaves the outcome unknown, a 200 was answered."""
    meter["http_status"] = status if type(status) is int else None
    if type(status) is int and 400 <= status < 500:
        meter.update(status="rate_limited" if status == 429 else "failed", cost_usd_micro=0, cost_source="provider", input_tokens=0, output_tokens=0)
    elif status == 200:
        meter["status"] = "ok"


def _meter_cost(cfg, model, tokens_in, tokens_out):
    """The read's cost as the settle books it (the agent price table), labelled with that table's version; {} when unknown."""
    from .agent_runtime_v2 import config as runtime_config
    if not (isinstance(tokens_in, int) and isinstance(tokens_out, int)):
        return {}
    cost, price = cfg.estimate_usd_micro(model, tokens_in, tokens_out), cfg.price(model)
    if cost is None or price is None:
        return {}
    default = runtime_config.DEFAULT_PRICES.get(str(model).split("/", 1)[-1])
    version = ai_call_events.AGENT_V2 if default is not None and tuple(price) == tuple(default) else ai_call_events.CONFIGURED
    return {"cost_usd_micro": cost, "cost_source": "table:" + version}


# --- storage of notes (pr_media_notes, migration 031) --------------------------------------------------------------------

def lookup(cur, workspace_id, pairs):
    """{assetId: {status, processor (id), text, hash}} for the current hashes: what turn_references.resolve reads."""
    pairs = [(a, h) for a, h in pairs or [] if isinstance(a, str) and isinstance(h, str)]
    if not pairs:
        return {}
    cur.execute("SELECT asset_id, asset_hash, status, processor, text FROM public.pr_media_notes WHERE workspace_id=%s AND reader_version=%s AND asset_id = ANY(%s)",
                (workspace_id, READER_VERSION, [a for a, _ in pairs]))
    wanted = dict(pairs)
    found = {}
    for asset_id, asset_hash, status, processor, text in cur.fetchall():
        if wanted.get(asset_id) == asset_hash:
            found[asset_id] = {"status": status, "processor": (processor or {}).get("id"), "text": text, "hash": asset_hash}
    return found


def purge_workspace(cur, workspace_id):
    cur.execute("DELETE FROM public.pr_media_notes WHERE workspace_id=%s", (workspace_id,))
    return cur.rowcount or 0


def purge_asset(cur, workspace_id, asset_id):
    cur.execute("DELETE FROM public.pr_media_notes WHERE workspace_id=%s AND asset_id=%s", (workspace_id, asset_id))
    return cur.rowcount or 0


def _row(cur, workspace_id, asset_id, asset_hash):
    # Ages come from the database clock, the same clock that stamped the row.
    cur.execute("SELECT status, text, processor, model, kind, frames, attempts, extract(epoch from updated_at)::float8, reservation_id::text, "
                "extract(epoch from (now() - updated_at))::float8 "
                "FROM public.pr_media_notes WHERE workspace_id=%s AND asset_id=%s AND asset_hash=%s AND reader_version=%s FOR UPDATE",
                (workspace_id, asset_id, asset_hash, READER_VERSION))
    row = cur.fetchone()
    if not row:
        return None
    keys = ("status", "text", "processor", "model", "kind", "frames", "attempts", "updatedAt", "reservationId", "age")
    return dict(zip(keys, row))


def _unavailable(asset_id, reason):
    return {"assetId": asset_id, "status": "unavailable", "reason": reason, "message": MESSAGES[reason]}


def _failed(asset_id, retryable=True):
    return {"assetId": asset_id, "status": "failed", "reason": "read_failed", "message": MESSAGES["read_failed"], "retryable": retryable}


def _ready(asset_id, row, cached, usage=None):
    processor = row.get("processor") or {}
    note = {"kind": row["kind"], "frames": row["frames"], "text": row["text"], "model": row.get("model"), "processor": processor.get("label"), "at": row.get("updatedAt")}
    return {"assetId": asset_id, "status": "ready", "cached": cached, "note": note, **({"usage": usage} if usage else {})}


class MediaNotes:
    """`POST /ideas/media-notes` (SPEC §5.6). `ideas` is the IdeasService (repository, ledger, membership, state)."""

    def __init__(self, ideas, reader, *, fetch_images=None, clock=None):
        self.ideas = ideas
        self.reader = reader
        self.fetch_images = fetch_images
        self.clock = clock or getattr(ideas, "clock", None) or time.time

    def _authorize(self, workspace_id, token, payload):
        """Credit authority for this read when the workspace is in credit mode (operation `media-notes`)."""
        if getattr(getattr(self.ideas, "ledger", None), "credits", None) is None:
            return None
        body = {"assetId": payload["assetId"], **({"creditQuoteId": payload["creditQuoteId"]} if payload.get("creditQuoteId") else {})}
        return self.ideas.credit_requests.authorize(workspace_id, token, payload.get("expectedRevision"), body, "media-notes")

    @staticmethod
    def _payload(payload):
        if not isinstance(payload, dict) or not set(payload) <= {"assetId", "idempotencyKey", "creditQuoteId", "expectedRevision"}:
            raise AlphaError("Invalid media notes request.", 400)
        if not isinstance(payload.get("assetId"), str) or not ASSET_ID.match(payload["assetId"]):
            raise AlphaError("Invalid media notes request.", 400)
        if not isinstance(payload.get("idempotencyKey"), str) or not 1 <= len(payload["idempotencyKey"]) <= 120:
            raise AlphaError("Invalid media notes request.", 400)
        return payload

    def read(self, workspace_id, token, payload):
        from .api_tokens import is_api_token
        from .permissions import require
        if is_api_token(token):
            raise AlphaError(SIGN_IN, 403)
        payload = self._payload(payload)
        asset_id = payload["assetId"]
        if not self.reader.available:
            return _unavailable(asset_id, "reader_unavailable")
        authority = self._authorize(workspace_id, token, payload)
        repo, ledger = self.ideas.repository, self.ideas.ledger

        # Transaction 1: role, asset, consent, cache, attempts, reservation, `reading` row.
        with repo.transaction(token, workspace_id) as (cur, row, actor):
            require(self.ideas._member(row), "edit")
            state = self.ideas._state(row)
            asset = next((a for a in (state.get("phase2") or {}).get("assets", []) if isinstance(a, dict) and a.get("id") == asset_id), None)
            if asset is None or asset.get("deleted") or asset.get("deletionPending") or asset_kinds.kind_of(asset) is None:
                raise AlphaError("This photo or video isn't in this workspace.", 404)
            if not asset_kinds.is_ready(asset):
                return _unavailable(asset_id, "media_not_ready")
            kind, frames = kind_for(asset), frame_count(asset)
            if kind == "video_frames" and frames == 0:
                return _unavailable(asset_id, "no_frames")
            processor = self.reader.processor()
            if not media_consent.allowed(state, processor):
                return _unavailable(asset_id, "consent_required")
            asset_hash = str(asset.get("hash") or "")
            existing = _row(cur, workspace_id, asset_id, asset_hash)
            if existing and existing["status"] == "ready" and (existing.get("processor") or {}).get("id") == processor["id"]:
                return _ready(asset_id, existing, cached=True)
            if existing and existing["status"] == "reading" and existing["age"] < READING_STALE:
                return {"assetId": asset_id, "status": "reading"}
            recent = existing and existing["age"] < ATTEMPT_WINDOW
            attempts = (existing["attempts"] if recent else 0) + 1
            if attempts > MAX_ATTEMPTS:
                return _failed(asset_id, retryable=False)
            estimate = self.reader.estimate(kind, frames)
            if estimate["ceilingUsdMicro"] is None:
                return _unavailable(asset_id, "reader_unavailable")
            # The consent decision is part of the key: turning reading off purges the notes (and their attempt counts), so a
            # read after it is allowed again must not collide with a reservation from the earlier decision.
            decided = int(float(media_consent.decision(state).get("decidedAt") or 0))
            reservation = ledger.reserve(cur, workspace_id, actor, "tool", estimate["ceilingUsdMicro"], f"notes:{asset_id}:{asset_hash}:{READER_VERSION}:{decided}:{attempts}",
                                         charge_batch=False, provider=estimate["provider"] or "", model=estimate["model"] or "",
                                         meta={"via": "media_notes", "assetId": asset_id, "kind": kind, "frames": frames}, credit_authority=authority)
            if reservation.get("duplicate"):
                return {"assetId": asset_id, "status": "reading"}
            cur.execute(
                "INSERT INTO public.pr_media_notes(workspace_id, asset_id, asset_hash, reader_version, processor, status, kind, frames, attempts, reservation_id, created_by, updated_at) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,'reading',%s,%s,%s,%s,%s,now()) "
                "ON CONFLICT (workspace_id, asset_id, asset_hash, reader_version) DO UPDATE SET status='reading', processor=EXCLUDED.processor, kind=EXCLUDED.kind, "
                "frames=EXCLUDED.frames, attempts=EXCLUDED.attempts, reservation_id=EXCLUDED.reservation_id, text=NULL, updated_at=now()",
                (workspace_id, asset_id, asset_hash, READER_VERSION, json.dumps(processor), kind, frames, attempts, reservation["reservationId"], actor))
        reservation_id = reservation["reservationId"]

        def finish(outcome, cost=None, note=None):
            with repo.transaction(token, workspace_id) as (cur, _row2, _actor):
                ledger.settle(cur, workspace_id, reservation_id, outcome, cost)
                if note is not None:
                    cur.execute("UPDATE public.pr_media_notes SET status='ready', text=%s, model=%s, updated_at=now() WHERE workspace_id=%s AND asset_id=%s AND asset_hash=%s AND reader_version=%s",
                                (note["text"], note["model"], workspace_id, asset_id, asset_hash, READER_VERSION))
                    return _row(cur, workspace_id, asset_id, asset_hash)
                cur.execute("UPDATE public.pr_media_notes SET status='failed', text=NULL, updated_at=now() WHERE workspace_id=%s AND asset_id=%s AND asset_hash=%s AND reader_version=%s",
                            (workspace_id, asset_id, asset_hash, READER_VERSION))
                return None

        # A revocation between reserving and calling wins: re-read consent in a fresh transaction.
        with repo.transaction(token, workspace_id) as (cur, row, _actor):
            if not media_consent.allowed(self.ideas._state(row), processor):
                consent_lost = True
            else:
                consent_lost = False
        if consent_lost:
            finish("failed", 0)
            return _unavailable(asset_id, "consent_required")
        try:
            images = self._images(workspace_id, token, asset, kind)
        except (AlphaError, OSError, ValueError):
            finish("failed", 0)   # refused before anything reached the provider
            return _failed(asset_id)
        try:
            # The provider attempt becomes one pr_ai_call_events row (Founder Admin §8.B), written when the read returns.
            with ai_call_events.scope(feature="notes", workspace_id=workspace_id, user_id=actor, reservation_id=reservation_id,
                                      connect=getattr(repo, "connection_factory", None)):
                result = self.reader.read(images, kind)
        except AlphaError as error:
            # Once the request may have reached the provider its cost can't be proven, so it is never settled as free.
            finish("failed", 0) if getattr(error, "code", None) == "route_unavailable" else finish("unknown")
            return _failed(asset_id)
        if result.get("costUsdMicro") is None:
            finish("unknown")
            return _failed(asset_id)
        stored = finish("completed", result["costUsdMicro"], note=result)
        from .credit_meter import millicredits
        return _ready(asset_id, stored, cached=False, usage={"milliCredits": millicredits(result["costUsdMicro"]), "costState": "actual"})

    def _images(self, workspace_id, token, asset, kind):
        if self.fetch_images is None:
            raise AlphaError("Private media storage is not configured.", 503)
        raw = self.fetch_images(workspace_id, token, asset)
        edge = FRAME_EDGE if kind == "video_frames" else PHOTO_EDGE
        return [(downscale(data, edge), "image/jpeg") for data, _mime in raw[:MAX_FRAMES]]

    def estimate(self, kind, frames=1):
        """Credits for the UI and the catalog: typical and ceiling (SPEC §5.11)."""
        from .credit_meter import millicredits
        value = self.reader.estimate(kind, frames)
        if value["ceilingUsdMicro"] is None:
            return None
        return {"typicalMilliCredits": millicredits(value["typicalUsdMicro"]), "ceilingMilliCredits": millicredits(value["ceilingUsdMicro"])}


def estimate_credits(cfg, model, kind, frames=1):
    """Credits (not millicredits) for a read at `model`'s configured price, for quick checks and tests."""
    images = max(1, min(MAX_FRAMES, frames))
    typical = cfg.estimate_usd_micro(model, PROMPT_TOKENS + IMAGE_TOKENS_TYPICAL * images, OUTPUT_TYPICAL[kind])
    ceiling = cfg.estimate_usd_micro(model, PROMPT_TOKENS + IMAGE_TOKENS_CEILING * images, OUTPUT_CAP[kind])
    from .credit_meter import CREDITS_PER_USD
    return {"typical": typical * CREDITS_PER_USD / 1_000_000, "ceiling": ceiling * CREDITS_PER_USD / 1_000_000} if typical is not None and ceiling is not None else None

