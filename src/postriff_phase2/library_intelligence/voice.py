"""Consented voice spans from Library items (engineering spec §4 VoiceSample, §6, §10; T07; R11).

There is one voice memory: the canonical samples in `state.sources` (kind 'voice_sample', `voice_sources`). An approved
Library span is admitted through the same commands Brand → Voice uses (`voice_samples_import`, `voice_sample_grant`,
optional `voice_sample_select`, and `voice_sample_revoke` to withdraw it), applied by the hosted command router to the
locked workspace state with the repository effects (growth invalidation, learning capture) in the same transaction.
`pr_library_voice_samples` only indexes where a span came from: version, locator, persona, brand, language and polarity.
A negative ("don't write like this") example lives only in that index and never becomes a canonical sample.

Admission is explicit and narrow. It needs the owner, the Library 'voice' purpose grant for the item (created here only
when the request asks, with the authorship attestation), an attestation naming how the person authored the passage,
and an exact locator over the version's active segments. A whole document, a cut through a passage, another speaker,
a fully quoted passage, a third-party link, a note the person said they did not write, and storage-only items are
refused. Generated or agent-written text needs a separate owner approval and is labelled 'ai_generated'.

Nothing here computes a voice-match score: drafting receives examples with their provenance and locators.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid

from postriff_alpha.domain import AlphaError

from .. import memory, source_policy, voice_sources
from ..contracts import digest
from . import contracts as c
from . import policy, versions
from . import segments as seg

DEFAULT_PERSONA = "default"  # the workspace speaker (state.speaker); the only persona with a derived profile
POLARITIES = ("positive", "negative")
METHODS = ("written_by_me", "spoken_by_me", "published_by_me")
VOICE_LOCATORS = ("text", "time", "page", "slide")
VOICE_KINDS = ("text", "page", "slide", "transcript", "note")
GENERATED_ORIGINS = frozenset({"agent", "ai", "assistant", "generated", "model", "artifact", "rafii"})
MAX_SPAN_CHARS = 4000  # pr_library_voice_samples.text
MAX_EXEMPLARS = 12
WITHDRAWN = "(withdrawn)"
PERSONA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,79}$")
LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")
QUOTES = {'"': '"', "“": "”", "‘": "’", "'": "'", "「": "」", "『": "』", "«": "»"}
EXPLANATION = ("Rafii shows the passages it learns your style from, where each came from and how many there are. "
               "It does not compute a voice-match percentage.")
COLUMNS = ("id,voice_source_id,asset_key,version_key,source_sha256,locator,text,text_hash,persona_id,brand,language,polarity,attestation,"
           "consent_revision,status,revision,created_by::text,extract(epoch from created_at),extract(epoch from revoked_at)")
TABLE = "public.pr_library_voice_samples"


def _refuse(message: str, status: int, code: str):
    raise AlphaError(message, status, code=code)


# --- index rows --------------------------------------------------------------------------------------------------------
def _json(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _row(r) -> dict:
    sid = r[0] if isinstance(r[0], uuid.UUID) else uuid.UUID(str(r[0]))
    return {"id": sid.hex, "voiceSourceId": r[1], "assetKey": r[2], "versionKey": r[3], "sha256": r[4], "locator": _json(r[5]), "text": r[6],
            "textHash": r[7], "personaId": r[8], "brand": r[9], "language": r[10], "polarity": r[11], "attestation": _json(r[12]) or {},
            "consentRevision": int(r[13]), "status": r[14], "revision": int(r[15]), "createdBy": r[16],
            "createdAt": float(r[17]) if r[17] is not None else None, "revokedAt": float(r[18]) if r[18] is not None else None}


def _select(ctx, tag: str, where: str, args: tuple, *, suffix: str = "") -> list[dict]:
    ctx.cur.execute(f"/*voice.{tag}*/ SELECT {COLUMNS} FROM {TABLE} WHERE workspace_id=%s AND {where}{suffix}", (ctx.workspace_id, *args))
    return [_row(r) for r in ctx.cur.fetchall()]


def _ref(row: dict) -> dict:
    return {"assetId": row["assetKey"], "versionId": row["versionKey"], "sha256": row["sha256"]}


# --- canonical voice commands inside the caller's transaction ---------------------------------------------------------
def _commands(ctx):
    """The hosted command router (HostedPhase2Commands), so voice actions take the exact Brand → Voice path. Outside the
    hosted service (no router mounted) the same canonical functions run directly."""
    commands = getattr(ctx.service, "commands", None)
    if callable(commands):
        return commands

    def direct(state, principal, action, payload):
        voice_sources.apply_action(state, action, payload, principal, ctx.now)
        source_policy.stamp(state)
        return state
    return direct


def _mutate_state(ctx, apply) -> dict:
    """Apply canonical commands to the freshly locked workspace state, save it once and run the repository effects
    (the same hooks `PostgresWorkspaceRepository.command` runs: growth invalidation, learning capture, planning sync).
    Works inside an HTTP write context (row already locked) and inside an in-process caller's cursor alike."""
    ctx.cur.execute("/*voice.workspace_lock*/ SELECT revision,state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (ctx.workspace_id,))
    row = ctx.cur.fetchone()
    if not row:
        raise AlphaError("Workspace unavailable.", 403)
    before = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    state = copy.deepcopy(before)
    commands = _commands(ctx)
    result = apply(state, lambda current, action, payload: commands(current, ctx.actor, action, payload))
    ctx.cur.execute("/*voice.workspace_save*/ UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s RETURNING revision",
                    (json.dumps(state), ctx.workspace_id))
    saved = ctx.cur.fetchone()
    effects = list(getattr(getattr(ctx.service, "repository", None), "effects", None) or [])
    for effect in effects:
        effect(ctx.cur, ctx.workspace_id, before, state, ctx.actor)
    ctx.state = state
    ctx.caches.pop("stamped", None)
    ctx.caches.pop("legacy", None)
    ctx.caches["workspaceRevision"] = int(saved[0]) if saved else int(row[0]) + 1
    return {"result": result, "before": before, "after": state, "effectsRun": len(effects)}


def _canonical(state: dict, source_id: str | None) -> dict | None:
    if not source_id:
        return None
    return next((s for s in state.get("sources", []) if s.get("kind") == "voice_sample" and s.get("id") == source_id), None)


# --- source role ---------------------------------------------------------------------------------------------------------
def source_role(version: dict) -> dict:
    """What the Library knows about who wrote an item. Upload alone proves nothing, so ordinary uploads are
    'unattested' until the owner attests a span; links are third-party references unless the owner says they published
    the page; a note the person said they did not write is a reference; Rafii's own outputs are 'generated'."""
    prov = version.get("provenance") or {}
    origin = str(prov.get("origin") or "").lower()
    source = str(prov.get("source") or "").lower()
    if (version.get("sourceKind") == "artifact" or prov.get("lineage") or prov.get("runId") or prov.get("generated") is True
            or origin in GENERATED_ORIGINS or source in GENERATED_ORIGINS):
        return {"role": "generated", "detail": "Made by Rafii or another AI tool. It can teach your voice only with your separate approval."}
    if version.get("sourceKind") == "note" and prov.get("authoredByMe") is False:
        return {"role": "reference", "detail": "You said someone else wrote this note, so it never teaches your voice."}
    if version.get("sourceKind") == "link" or source == "link":
        return {"role": "reference", "detail": "A saved web page is someone else's writing unless you say you published it."}
    if version.get("sourceKind") == "note" and prov.get("authoredByMe") is True:
        return {"role": "own_note", "detail": "You said you wrote this note. Approve passages to use them as voice examples."}
    return {"role": "unattested", "detail": "Rafii doesn't know who wrote this. Approve only passages you wrote or spoke yourself."}


# --- validation ----------------------------------------------------------------------------------------------------------
def _attestation(value) -> dict:
    if not isinstance(value, dict) or value.get("authoredByMe") is not True or value.get("method") not in METHODS:
        _refuse("Confirm that you wrote, spoke or published this passage yourself before it can teach your voice.", 422, "library_voice_attestation")
    if not set(value) <= {"authoredByMe", "method", "speakerLabel"}:
        c.fail("This attestation has unexpected fields.")
    out = {"authoredByMe": True, "method": value["method"]}
    if value.get("speakerLabel") is not None:
        out["speakerLabel"] = seg.clean_speaker_label(value["speakerLabel"])
    return out


def _persona(value) -> str:
    value = DEFAULT_PERSONA if value is None else value
    if not isinstance(value, str) or not PERSONA.fullmatch(value):
        _refuse("Choose a persona name of up to 80 letters, numbers or - _ . :", 422, "library_voice_persona")
    return value


def _brand(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80 or re.search(r"[\x00-\x1f\x7f]", value):
        _refuse("Use a brand name of up to 80 characters.", 422, "library_voice_persona")
    return value.strip()


def _language(value) -> str:
    if not isinstance(value, str) or not LANGUAGE.fullmatch(value):
        _refuse("Choose the passage's language, such as yue, zh-Hant or en.", 422, "library_voice_language")
    return value


def _uses(value) -> list[dict]:
    if not isinstance(value, list) or not value or len(value) > 10:
        _refuse("Choose how this sample may be used: analysis, writing, or both, with their routes.", 422, "library_voice_uses")
    for item in value:
        if not isinstance(item, dict) or not set(item) <= {"purpose", "route"} or item.get("purpose") not in voice_sources.PURPOSES:
            _refuse("Choose analysis or writing for each use.", 422, "library_voice_uses")
        route = item.get("route")
        if not isinstance(route, str) or not route.strip() or len(route) > 120:
            _refuse("Choose the exact AI route for each use.", 422, "library_voice_uses")
        if route.strip() == voice_sources.MANAGED_WRITER_ROUTE and item["purpose"] != "generation":
            _refuse("AI analysis needs one exact model; only writing may be allowed for every Rafii AI writer model.", 422, "library_voice_uses")
    return [{"purpose": item["purpose"], "route": item["route"].strip()} for item in value]


def _normalize(text: str) -> str:
    # The same normalization voice_sources applies on import, so text hashes match the canonical contentHash.
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- span resolution -------------------------------------------------------------------------------------------------------
def _active_segments(ctx, version: dict) -> list[dict]:
    out, cursor = [], None
    for _ in range(seg.MAX_SEGMENTS // seg.MAX_PAGE_LIMIT):
        page = seg.list_segments(ctx, version, cursor=cursor, limit=seg.MAX_PAGE_LIMIT)
        out += page["segments"]
        cursor = page["nextCursor"]
        if not cursor:
            break
    return out


def _range(segment: dict, page: int | None = None):
    """(start, end, offsets_align) of a text-bearing segment in the locator's coordinate space, or None."""
    loc = segment.get("locator") or {}
    if loc.get("kind") == "text":
        return loc["start"], loc["end"], len(segment["text"]) == loc["end"] - loc["start"]
    if loc.get("kind") == "page" and loc.get("page") == page:
        if "textStart" in loc:
            return loc["textStart"], loc["textEnd"], len(segment["text"]) == loc["textEnd"] - loc["textStart"]
        return 0, len(segment["text"]), False  # a single-passage page has no trustworthy inner offsets
    return None


def _pieces(spans: list, start: int, end: int) -> list[tuple[dict, str]]:
    """Text of [start, end) over offset-carrying segments. Whole segments always; part of a segment only when its
    offsets align with its text (a person's correction may change length, so it must be taken whole)."""
    hits = sorted((s for s in spans if s[1] < end and s[2] > start), key=lambda s: s[1])
    if not hits:
        _refuse("There is no passage at this place in the item.", 422, "library_voice_no_passage")
    if start < hits[0][1] or end > hits[-1][2]:
        _refuse("Select text that starts and ends inside the item's passages.", 422, "library_voice_partial")
    out = []
    for segment, a, b, aligned in hits:
        lo, hi = max(start, a), min(end, b)
        if (lo, hi) == (a, b):
            out.append((segment, segment["text"]))
        elif aligned:
            out.append((segment, segment["text"][lo - a:hi - a]))
        else:
            _refuse("Select this whole passage; its text was corrected or has no exact positions.", 422, "library_voice_partial")
    return out


def resolve_span(ctx, version: dict, loc: dict) -> dict:
    """The exact text at `loc` from the version's active segments, with the segments it came from."""
    if loc["kind"] not in VOICE_LOCATORS:
        _refuse("Spreadsheet cells and image regions can't teach your voice. Select a passage or a spoken moment.", 422, "library_voice_locator")
    segments = [s for s in _active_segments(ctx, version) if s["kind"] in VOICE_KINDS and s.get("locator")]
    if loc["kind"] == "time":
        timed = [s for s in segments if s["locator"]["kind"] == "time"]
        hits = sorted((s for s in timed if s["locator"]["startMs"] < loc["endMs"] and s["locator"]["endMs"] > loc["startMs"]),
                      key=lambda s: s["locator"]["startMs"])
        if not hits:
            _refuse("There is no transcript passage at this moment.", 422, "library_voice_no_passage")
        if any(s["locator"]["startMs"] < loc["startMs"] or s["locator"]["endMs"] > loc["endMs"] for s in hits) \
                or hits[0]["locator"]["startMs"] != loc["startMs"] or max(s["locator"]["endMs"] for s in hits) != loc["endMs"]:
            _refuse("This selection cuts through a spoken passage. Select whole passages from start to end.", 422, "library_voice_partial")
        pieces = [(s, s["text"]) for s in hits]
    elif loc["kind"] == "slide":
        hits = [s for s in segments if s["locator"]["kind"] == "slide" and s["locator"]["slide"] == loc["slide"]]
        if not hits:
            _refuse("There is no text on this slide.", 422, "library_voice_no_passage")
        pieces = [(s, s["text"]) for s in hits]
    elif loc["kind"] == "page" and "textStart" not in loc:
        hits = [s for s in segments if s["locator"]["kind"] == "page" and s["locator"]["page"] == loc["page"]]
        if not hits:
            _refuse("There is no text on this page.", 422, "library_voice_no_passage")
        pieces = [(s, s["text"]) for s in hits]
    else:
        page = loc.get("page") if loc["kind"] == "page" else None
        start, end = (loc["textStart"], loc["textEnd"]) if loc["kind"] == "page" else (loc["start"], loc["end"])
        if end <= start:
            _refuse("Select at least one character.", 422, "library_voice_no_passage")
        spans = [(s, *r) for s in segments if (r := _range(s, page)) is not None and (loc["kind"] == "page") == (s["locator"]["kind"] == "page")]
        pieces = _pieces(spans, start, end)
    used = list({s["id"]: s for s, _ in pieces}.values())
    if len(segments) > 1 and {s["id"] for s in used} == {s["id"] for s in segments}:
        _refuse("Select passages, not the whole file. Only the passages you choose teach your voice.", 422, "library_voice_whole_document")
    text = _normalize("\n\n".join(piece.strip() for _, piece in pieces if piece.strip()))
    if not text:
        _refuse("There is no text at this place in the item.", 422, "library_voice_no_passage")
    if len(text) > MAX_SPAN_CHARS:
        _refuse(f"Select a shorter passage (up to {MAX_SPAN_CHARS:,} characters).", 413, "library_voice_too_long")
    return {"text": text, "segments": used, "speakers": {s.get("speakerLabel") for s in used},
            "generated": any(s.get("origin") == "ai_suggested" for s in used),
            "language": next((s["language"] for s in used if s.get("language")), None)}


def _check_speaker(span: dict, attestation: dict):
    labels = span["speakers"]
    named = {label for label in labels if label}
    if len(named) > 1 or (named and None in labels):
        _refuse("This selection includes more than one speaker. Select only the passages where you speak.", 403, "library_voice_mixed_speakers")
    if named:
        label = next(iter(named))
        if not attestation.get("speakerLabel"):
            _refuse(f"This passage is labelled {label}. Say which speaker is you before approving it.", 422, "library_voice_speaker_required")
        if attestation["speakerLabel"] != label:
            _refuse(f"This passage is spoken by {label}, not by you. A guest's words never teach your voice.", 403, "library_voice_other_speaker")


def _check_quoted(text: str):
    if len(text) >= 2 and text[0] in QUOTES and text[-1] == QUOTES[text[0]]:
        inner = text[1:-1]
        if QUOTES[text[0]] not in inner and (text[0] == QUOTES[text[0]] or text[0] not in inner):
            _refuse("This passage is a quotation. Someone else's words never teach your voice.", 403, "library_voice_quoted")


# --- contracts ---------------------------------------------------------------------------------------------------------------
def _uses_of(source: dict | None) -> list[dict]:
    return [dict(g) for g in (source or {}).get("useGrants", []) if isinstance(g, dict)]


def _effective(row: dict, state: dict, decision=None) -> tuple[str, str | None]:
    if row["status"] != "approved":
        return "revoked", "withdrawn"
    if row["polarity"] == "positive":
        source = _canonical(state, row["voiceSourceId"])
        if source is None or not source.get("active"):
            return "revoked", "revoked_in_voice_settings"
        if source.get("contentHash") != row["textHash"]:
            return "blocked", "sample_changed"
    if decision is not None and not decision.allowed:
        return "blocked", decision.reason
    return "approved", None


def sample_contract(row: dict, state: dict, decision=None) -> dict:
    status, reason = _effective(row, state, decision)
    source = _canonical(state, row["voiceSourceId"])
    loc = row["locator"]
    attestation = {k: v for k, v in row["attestation"].items() if k in ("authoredByMe", "method", "speakerLabel", "generatedTextApproved")}
    return {"contractVersion": c.CONTRACT_VERSION, "sampleId": row["id"], "voiceSourceId": row["voiceSourceId"], "assetRef": _ref(row),
            "locator": loc, "locatorLabel": c.locator_label(loc), "text": row["text"] if status != "revoked" else None, "textHash": row["textHash"],
            "personaId": row["personaId"], "brand": row["brand"], "language": row["language"], "polarity": row["polarity"],
            "status": status, "statusReason": reason, "revision": row["revision"], "consentRevision": row["consentRevision"],
            "attestation": attestation, "uses": _uses_of(source) if status == "approved" else [],
            "selected": bool(source and source.get("active") and source.get("selected")), "createdAt": row["createdAt"], "revokedAt": row["revokedAt"]}


# --- admission -----------------------------------------------------------------------------------------------------------------
def approve_voice_span(ctx, ref, locator, persona_id, author_attestation, *, polarity: str = "positive", brand=None, language=None,
                       uses=None, confirmed: bool = False, grant_voice: bool = False, approve_generated_text: bool = False,
                       select: bool = False, expected_revision: int | None = None) -> dict:
    """approve_voice_span(ctx, ref, locator, persona_id, author_attestation) -> VoiceSample (implementation plan T07).

    Owner only. Every refusal happens before any write; the purpose grant is rechecked (TOCTOU) right before the
    canonical import, which holds the policy row so a concurrent revoke waits and then withdraws this span."""
    ctx.require("owner")
    seg.writable(ctx)
    if not policy.enabled("voice"):
        _refuse("Learning your voice from Library is turned off.", 403, "library_voice_disabled")
    if polarity not in POLARITIES:
        c.fail("Choose a voice example or a don't-write-like-this example.")
    attestation = _attestation(author_attestation)
    persona = _persona(persona_id)
    brand = _brand(brand)
    if confirmed is not True:
        _refuse("Confirm how this passage may be used for your voice.", 422, "library_voice_confirm")
    chosen_uses = _uses(uses) if polarity == "positive" else []
    if polarity == "negative" and uses:
        c.fail("A don't-write-like-this example is never used as a voice sample, so it has no uses to grant.")
    if select and (persona != DEFAULT_PERSONA or polarity != "positive"):
        _refuse("Only your workspace voice's own examples can be selected for every draft.", 422, "library_voice_select_default_only")
    version = versions.resolve(ctx, ref)
    if not version.get("sha256"):
        _refuse("This item's content hash isn't verified yet. Try again after it finishes processing.", 409, "library_voice_no_hash")
    role = source_role(version)
    generated = role["role"] == "generated"
    if role["role"] == "reference" and not (version.get("sourceKind") == "link" and attestation["method"] == "published_by_me"):
        _refuse(role["detail"], 403, "library_voice_reference")
    if generated and approve_generated_text is not True:
        _refuse("This text was written by AI. Approve AI-written text separately before it can teach your voice.", 409,
                "library_voice_generated_needs_approval")
    revisions = policy.revisions(ctx, fresh=True)
    if expected_revision is not None and expected_revision != revisions["grantRevision"]:
        raise AlphaError("Library permissions changed. Review them again.", 409, code="library_grant_conflict")
    loc = c.locator(locator, **seg.bounds(ctx.cur, ctx.workspace_id, version))
    if grant_voice is True and not policy.authorize_source(ctx, version, "voice").allowed:
        policy.grant(ctx, {"grantType": "purpose", "purpose": "voice", "scope": {"kind": "asset", "assetId": version["assetId"]},
                           "attestation": attestation})
    decision = policy.require(policy.authorize_source(ctx, version, "voice"))
    span = resolve_span(ctx, version, loc)
    _check_speaker(span, attestation)
    _check_quoted(span["text"])
    if span["generated"] and approve_generated_text is not True:
        _refuse("Part of this passage was suggested by AI. Approve AI-written text separately before it can teach your voice.", 409,
                "library_voice_generated_needs_approval")
    generated = generated or span["generated"]
    lang = _language(language if language is not None else span["language"] or seg.detect_language(span["text"])["language"])
    loc_json = json.dumps(loc, sort_keys=True)
    existing = _select(ctx, "same_span", "version_key=%s AND locator=%s::jsonb AND persona_id=%s AND coalesce(brand,'')=%s AND language=%s AND status='approved'",
                       (version["versionId"], loc_json, persona, brand or "", lang), suffix=" ORDER BY created_at,id FOR UPDATE")
    # A span whose canonical sample was revoked in Brand → Voice is no longer approved; retire it so it can be re-approved.
    retired = [r for r in existing if _effective(r, ctx.state)[0] == "revoked"]
    existing = [r for r in existing if r not in retired]
    if any(r["polarity"] != polarity for r in existing):
        _refuse("This passage is already an example of the opposite kind. Withdraw that one first.", 409, "library_voice_polarity_conflict")
    if existing:
        out = sample_contract(existing[0], ctx.state)
        return {**out, "alreadyApproved": True, "warnings": ["This passage was already approved."]}
    decision = policy.recheck(ctx, decision)
    policy.require(decision)
    if retired:
        _withdraw(ctx, retired, reason="revoked_in_voice_settings")
    if generated:
        attestation["generatedTextApproved"] = True
    record = {**attestation, "attestedBy": ctx.actor, "attestedAt": ctx.now}
    warnings = []
    source_id = None
    if polarity == "positive":
        title = f"{version['title']} · {c.locator_label(loc)}"[:200]
        external = "library:" + digest([version["versionId"], loc, persona, brand, lang])[:40]
        payload = {"format": "pasted", "text": span["text"], "title": title, "externalId": external, "platform": "Rafii Library", "language": lang,
                   "label": "ai_generated" if generated else None}
        identity = voice_sources.normalize_import(payload)[0]["importIdentity"]
        origin = {"assetId": version["assetId"], "versionId": version["versionId"], "sha256": version["sha256"], "locator": loc,
                  "personaId": persona, "brand": brand, "language": lang}

        def admit(state, run):
            run(state, "voice_samples_import", payload)
            source = next(s for s in state["sources"] if s.get("kind") == "voice_sample" and s.get("active") and s.get("importIdentity") == identity)
            source["libraryOrigin"] = origin
            run(state, "voice_sample_grant", {"sourceId": source["id"], "confirmed": True, "grants": chosen_uses})
            if select:
                run(state, "voice_sample_select", {"sourceId": source["id"], "selected": True})
            return source["id"]

        source_id = _mutate_state(ctx, admit)["result"]
        if select:
            warnings.append("Selected for your workspace voice: Rafii's writer uses selected samples whatever language you draft in.")
    sample_id = uuid.uuid4()
    ctx.cur.execute(f"/*voice.insert*/ INSERT INTO {TABLE}(id,workspace_id,voice_source_id,asset_key,version_key,source_sha256,locator,text,text_hash,"
                    "persona_id,brand,language,polarity,attestation,consent_revision,status,revision,created_by) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'approved',1,%s)",
                    (sample_id, ctx.workspace_id, source_id, version["assetId"], version["versionId"], version["sha256"], loc_json, span["text"],
                     _sha(span["text"]), persona, brand, lang, polarity, json.dumps(record), decision.grant_revision, ctx.actor))
    _audit(ctx, "library.voice_span_approved", sample_id.hex, {"polarity": polarity, "persona": persona, "language": lang, "locator": loc["kind"],
                                                               "generatedTextApproved": generated, "selected": bool(select)})
    row = {"id": sample_id.hex, "voiceSourceId": source_id, "assetKey": version["assetId"], "versionKey": version["versionId"], "sha256": version["sha256"],
           "locator": loc, "text": span["text"], "textHash": _sha(span["text"]), "personaId": persona, "brand": brand, "language": lang,
           "polarity": polarity, "attestation": record, "consentRevision": decision.grant_revision, "status": "approved", "revision": 1,
           "createdBy": ctx.actor, "createdAt": ctx.now, "revokedAt": None}
    return {**sample_contract(row, ctx.state), "alreadyApproved": False, "warnings": warnings}


# --- revocation ------------------------------------------------------------------------------------------------------------------
def _speaker_stale(state: dict) -> dict:
    speaker = state.get("speaker") or {}
    return {"revisions": {r.get("revision") for r in speaker.get("revisions", []) if isinstance(r, dict) and r.get("stale")},
            "provisional": (speaker.get("provisional") or {}).get("status") == "stale",
            "variants": {v.get("id") for v in state.get("variants", []) if v.get("blockedByRetraction")}}


def _withdraw(ctx, rows: list[dict], *, reason: str) -> dict:
    """Withdraw index rows and run the canonical revoke for their active positive samples in one state change."""
    live = [r for r in rows if r["polarity"] == "positive" and (s := _canonical(ctx.state, r["voiceSourceId"])) is not None and s.get("active")]
    receipt = {"canonicalRevoked": [], "speakerRevisions": [], "provisionalProposal": False, "draftsFlagged": [], "effectsRun": 0, "routes": []}
    if live:
        def revoke(state, run):
            done = []
            for r in live:
                source = _canonical(state, r["voiceSourceId"])
                if source is not None and source.get("active"):
                    receipt["routes"] += [g.get("route") for g in source.get("useGrants", []) if isinstance(g, dict)]
                    run(state, "voice_sample_revoke", {"sourceId": source["id"], "confirmed": True})
                    done.append(source["id"])
            return done

        changed = _mutate_state(ctx, revoke)
        old, new = _speaker_stale(changed["before"]), _speaker_stale(changed["after"])
        receipt.update(canonicalRevoked=changed["result"], speakerRevisions=sorted(new["revisions"] - old["revisions"]),
                       provisionalProposal=new["provisional"] and not old["provisional"], draftsFlagged=sorted(new["variants"] - old["variants"]),
                       effectsRun=changed["effectsRun"])
    ctx.cur.execute(f"/*voice.revoke*/ UPDATE {TABLE} SET status='revoked',text=%s,revoked_at=now(),revoked_by=%s,revision=revision+1 "
                    "WHERE workspace_id=%s AND id=ANY(%s::uuid[]) AND status='approved'",
                    (WITHDRAWN, ctx.actor, ctx.workspace_id, [str(uuid.UUID(hex=r["id"])) for r in rows]))
    _audit(ctx, "library.voice_sample_revoked", rows[0]["id"] if len(rows) == 1 else "*", {"count": len(rows), "reason": reason,
                                                                                           "canonical": len(receipt["canonicalRevoked"])})
    return receipt


def _voice_file(state: dict) -> str:
    return next((f["source"] for f in memory.render_files(state) if f["name"] == "VOICE.md"), "")


def revoke_voice_sample(ctx, sample_id, expected_revision: int | None = None, *, asset_key: str | None = None) -> dict:
    """revoke_voice_sample(ctx, sample_id, expected_revision) -> rebuild/invalidation result (implementation plan T07).

    Runs the canonical `voice_sample_revoke` (speaker revisions that used it go stale, its quotes and writing example
    are removed, drafts that read it are flagged, growth genomes go stale through the repository effect), withdraws the
    index row and returns evidence that future retrieval excludes it."""
    ctx.require("owner")
    key = c.asset_key(sample_id)
    rows = _select(ctx, "by_id", "id=%s", (uuid.UUID(hex=key),), suffix=" FOR UPDATE")
    if not rows or (asset_key is not None and asset_key not in (rows[0]["assetKey"], rows[0]["versionKey"])):
        _refuse("This voice example is unavailable.", 404, "library_unavailable")
    row = rows[0]
    if row["status"] == "revoked":
        return {"sampleId": row["id"], "status": "revoked", "alreadyRevoked": True, "revision": row["revision"], "voiceSourceId": row["voiceSourceId"],
                "polarity": row["polarity"], "retrieval": {"excludedFromFutureRetrieval": True, "canonicalReason": "revoked"}}
    if expected_revision is not None and expected_revision != row["revision"]:
        _refuse("This voice example changed. Refresh and try again.", 409, "library_voice_revision_conflict")
    receipt = _withdraw(ctx, [row], reason="revoked")
    state = ctx.state
    source = _canonical(state, row["voiceSourceId"])
    probe = next((r for r in receipt["routes"] if isinstance(r, str) and r and voice_sources.route_class(r) is None and not r.endswith("*")), "local-rules")
    if source is not None:
        excluded = voice_sources.project(state, [source["id"]], "generation", probe)["excluded"]
        reason = excluded[0]["reason"] if excluded else None
    else:
        reason = "revoked" if row["polarity"] == "negative" else "missing"
    active = memory.active_profile(state)
    return {"sampleId": row["id"], "status": "revoked", "alreadyRevoked": False, "revision": row["revision"] + 1, "voiceSourceId": row["voiceSourceId"],
            "polarity": row["polarity"],
            "canonical": {"revoked": bool(receipt["canonicalRevoked"]), "cleanupStatus": (source or {}).get("cleanupStatus")},
            "invalidated": {"speakerRevisions": receipt["speakerRevisions"], "provisionalProposal": receipt["provisionalProposal"],
                            "draftsFlagged": receipt["draftsFlagged"],
                            "activeProfileStale": bool(active and (active.get("stale") or (active.get("profile") or {}).get("status") == "stale")),
                            "voiceFile": _voice_file(state)},
            "retrieval": {"excludedFromFutureRetrieval": reason in ("revoked", "missing") or row["polarity"] == "negative", "canonicalReason": reason},
            "effectsRun": receipt["effectsRun"],
            "residual": ("Future drafts and voice analyses stop using this example. Drafts already written with it keep their text and are "
                         "flagged for review; text already sent to an AI provider for an earlier draft can't be recalled.")}


def withdraw_for_keys(ctx, keys, *, force: bool = False) -> int:
    """Called by lifecycle.propagate_revocation when a 'voice' purpose grant is revoked (keys None = whole workspace).
    Runs inside the caller's open transaction and cursor: the canonical revoke is applied to the locked workspace state
    directly (with the repository effects), not deferred to a follow-up command. Spans still covered by another active
    voice grant stay, unless `force` (deletion) or their version is gone."""
    if keys is not None:
        keys = [k for k in keys if isinstance(k, str) and c.KEY.fullmatch(k)]
        if not keys:
            return 0
    if keys is None:
        rows = _select(ctx, "for_keys", "status='approved'", (), suffix=" ORDER BY created_at,id FOR UPDATE")
    else:
        rows = _select(ctx, "for_keys", "status='approved' AND (asset_key=ANY(%s) OR version_key=ANY(%s))", (keys, keys),
                       suffix=" ORDER BY created_at,id FOR UPDATE")
    if not rows:
        return 0
    if not force:
        ctx.caches.pop("grants", None)
        loaded = versions.load(ctx, [r["versionKey"] for r in rows])
        live = lambda r: (v := loaded.get(r["versionKey"])) is not None and v["status"] not in ("deleting", "duplicate", "missing")  # noqa: E731
        rows = [r for r in rows if not (live(r) and (policy.purpose_grants(ctx, "voice", r["versionKey"]) or policy.purpose_grants(ctx, "voice", r["assetKey"])))]
        if not rows:
            return 0
    _withdraw(ctx, rows, reason="deleted" if force else "voice_grant_revoked")
    return len(rows)


# --- exemplar retrieval for drafting -------------------------------------------------------------------------------------------------
def style_exemplars(ctx, persona_id: str, language: str, limit: int = 6, *, brand=None, allow_languages=(), purpose: str = "generation",
                    route: str | None = None) -> dict:
    """Positive and negative style examples for one persona, brand and language, with provenance and locators. Other
    languages only when the caller explicitly allows them. Never a score. Each positive example must still be an active
    canonical sample with this purpose (and route, when given); the Library voice grant is rechecked before returning."""
    persona = _persona(persona_id)
    brand = _brand(brand)
    langs = [_language(language)] + [_language(x) for x in (allow_languages or ()) if x != language]
    langs = list(dict.fromkeys(langs))
    if type(limit) is not int or not 1 <= limit <= MAX_EXEMPLARS:
        c.fail(f"Ask for 1 to {MAX_EXEMPLARS} examples.")
    if purpose not in voice_sources.PURPOSES:
        c.fail("Choose analysis or generation.")
    out = {"contractVersion": c.CONTRACT_VERSION, "personaId": persona, "brand": brand, "languages": langs, "positive": [], "negative": [],
           "bindings": [], "excluded": [], "explanation": EXPLANATION, "enabled": policy.enabled("voice")}
    if not out["enabled"]:
        out["warnings"] = ["Library voice examples are turned off."]
        return out
    rows = _select(ctx, "scope", "status='approved' AND persona_id=%s AND coalesce(brand,'')=%s AND language=ANY(%s)",
                   (persona, brand or "", langs, MAX_EXEMPLARS * 4 * len(langs)), suffix=" ORDER BY created_at DESC,id LIMIT %s")
    rows.sort(key=lambda r: langs.index(r["language"]))  # stable: newest first within each language
    loaded = versions.load(ctx, [r["versionKey"] for r in rows])
    candidates = []
    for r in rows:
        version = loaded.get(r["versionKey"])
        if version is None:
            out["excluded"].append({"sampleId": r["id"], "reason": "unavailable"})
            continue
        decision = policy.authorize_source(ctx, version, "voice")
        if not decision.allowed:
            out["excluded"].append({"sampleId": r["id"], "reason": decision.reason})
            continue
        text = r["text"]
        if r["polarity"] == "positive":
            source = _canonical(ctx.state, r["voiceSourceId"])
            reason = None
            if source is None or not source.get("active"):
                reason = "revoked"
            elif source.get("contentHash") != r["textHash"]:
                reason = "sample_changed"
            elif purpose not in source.get("purposeGrants", []) or (route is not None and not voice_sources.route_granted(source, purpose, route)):
                reason = "use_not_granted"
            elif source.get("excludedAt") and not source.get("selected"):
                reason = "excluded_in_voice_settings"
            if reason:
                out["excluded"].append({"sampleId": r["id"], "reason": reason})
                continue
            text = source["text"]
        candidates.append((r, decision, text))
    if candidates:
        fresh = policy.recheck(ctx, [d for _, d, _ in candidates])
        candidates = [(r, d, t) for (r, _, t), d in zip(candidates, fresh) if d.allowed]
    used = 0
    for r, _, text in candidates:
        bucket = out[r["polarity"]]
        if len(bucket) >= limit or used + len(text) > voice_sources.MAX_RETRIEVAL_CHARS:
            continue
        used += len(text)
        source = _canonical(ctx.state, r["voiceSourceId"])
        bucket.append({"sampleId": r["id"], "voiceSourceId": r["voiceSourceId"], "text": text, "language": r["language"], "polarity": r["polarity"],
                       "assetRef": _ref(r), "locator": r["locator"], "locatorLabel": c.locator_label(r["locator"]), "untrustedData": True,
                       "provenance": {"method": r["attestation"].get("method"), "speakerLabel": r["attestation"].get("speakerLabel"),
                                      "generatedTextApproved": bool(r["attestation"].get("generatedTextApproved")), "approvedAt": r["createdAt"]}})
        if source is not None:
            out["bindings"].append({"id": source["id"], "revision": source["revision"], "contentHash": source["contentHash"]})
    return out


# --- reads ---------------------------------------------------------------------------------------------------------------------------------
def asset_voice_http(ctx, request):
    """GET .../assets/{key}/voice — this item's voice examples and don't-write-like-this examples with their status,
    its source role, and whether voice use is allowed. No score."""
    version = versions.get(ctx, request["params"]["key"])
    policy.require(policy.authorize_source(ctx, version, "browse"))
    decision = policy.authorize_source(ctx, version, "voice")
    rows = _select(ctx, "by_asset", "asset_key=%s", (version["assetId"],), suffix=" ORDER BY created_at,id LIMIT 500")
    items = [sample_contract(r, ctx.state, decision if r["status"] == "approved" else None) for r in rows]
    return {"contractVersion": c.CONTRACT_VERSION, "assetRef": versions.ref(version),
            "samples": [i for i in items if i["polarity"] == "positive"], "negatives": [i for i in items if i["polarity"] == "negative"],
            "voicePermission": {"allowed": decision.allowed, "reason": decision.reason, "message": None if decision.allowed else policy.message(decision.reason),
                                "grantRevision": decision.grant_revision},
            "sourceRole": source_role(version),
            "admission": {"enabled": policy.enabled("voice"), "canApprove": ctx.allows("owner"), "methods": list(METHODS)},
            "explanation": EXPLANATION}


def _profile(state: dict, persona: str, positive_sources: set) -> dict:
    if persona != DEFAULT_PERSONA:
        return {"status": "not_applicable", "detail": "Rafii keeps one derived voice profile per workspace. This persona uses its approved examples directly."}
    revision = memory.active_profile(state)
    if not revision:
        return {"status": "not_built", "detail": "No approved voice profile yet. Approved examples are still used directly."}
    profile = revision.get("profile") or {}
    evidence = set(profile.get("evidenceSourceIds") or revision.get("evidenceSourceIds") or [])
    out = {"revision": revision.get("revision"), "fromLibraryExamples": len(evidence & positive_sources)}
    if revision.get("stale") or profile.get("status") == "stale":
        return {**out, "status": "stale", "reason": revision.get("staleReason") or "evidence_changed",
                "detail": "A sample this profile used was withdrawn, so writers no longer read it. Analyse your current samples again."}
    pending = len(positive_sources - evidence)
    if pending:
        return {**out, "status": "needs_update", "notYetAnalysed": pending, "detail": "Some approved examples are newer than your profile."}
    return {**out, "status": "current", "detail": "Your profile was built from your current approved samples."}


def summary_http(ctx, request):
    """GET .../voice — per persona, brand and language: approved example counts, a few examples with provenance, and
    whether the derived profile is current or stale. Counts and examples only; no percentages."""
    query = request.get("query") or {}
    wanted = _persona(query["personaId"]) if query.get("personaId") else None
    rows = _select(ctx, "approved", "status='approved'", (), suffix=" ORDER BY created_at,id LIMIT 2000")
    loaded = versions.load(ctx, [r["versionKey"] for r in rows])
    personas: dict = {DEFAULT_PERSONA: {}}
    sources: dict = {}
    for r in rows:
        version = loaded.get(r["versionKey"])
        decision = policy.authorize_source(ctx, version, "voice") if version is not None else None
        status, _ = _effective(r, ctx.state, decision)
        if version is None or status != "approved":
            continue
        group = personas.setdefault(r["personaId"], {}).setdefault((r["brand"] or "", r["language"]), {
            "brand": r["brand"], "language": r["language"], "positiveCount": 0, "negativeCount": 0, "assets": set(), "examples": []})
        group["positiveCount" if r["polarity"] == "positive" else "negativeCount"] += 1
        group["assets"].add(r["assetKey"])
        if r["polarity"] == "positive":
            sources.setdefault(r["personaId"], set()).add(r["voiceSourceId"])
        if len(group["examples"]) < 3:
            group["examples"].append({"sampleId": r["id"], "polarity": r["polarity"], "assetRef": _ref(r), "title": version["title"],
                                      "locatorLabel": c.locator_label(r["locator"]), "excerpt": r["text"][:160], "approvedAt": r["createdAt"]})
    out = []
    for persona, groups in personas.items():
        if wanted and persona != wanted:
            continue
        listed = [{**{k: v for k, v in g.items() if k != "assets"}, "assetCount": len(g["assets"])} for g in groups.values()]
        out.append({"personaId": persona, "isWorkspaceVoice": persona == DEFAULT_PERSONA, "groups": listed,
                    "profile": _profile(ctx.state, persona, sources.get(persona, set()))})
    return {"contractVersion": c.CONTRACT_VERSION, "personas": out, "enabled": policy.enabled("voice"), "explanation": EXPLANATION,
            "coverage": {"approvedExamples": sum(g["positiveCount"] for p in out for g in p["groups"]),
                         "negativeExamples": sum(g["negativeCount"] for p in out for g in p["groups"]),
                         "languages": sorted({g["language"] for p in out for g in p["groups"]})}}


# --- actions ---------------------------------------------------------------------------------------------------------------------------------
APPROVE_FIELDS = {"locator", "personaId", "brand", "language", "polarity", "attestation", "uses", "confirmed", "grantVoice", "approveGeneratedText", "select"}


def approve_span_action(ctx, envelope: dict, targets: list[dict]) -> dict:
    """voice.approve_span on exactly one target. AI-written text answers `requires_confirmation` until the owner sends
    `approveGeneratedText: true`."""
    if len(targets) != 1:
        c.fail("Approve a passage from one item at a time.")
    payload = envelope.get("payload") or {}
    if not set(payload) <= APPROVE_FIELDS:
        c.fail("This voice approval has unexpected fields.")
    for flag in ("confirmed", "grantVoice", "approveGeneratedText", "select"):
        if flag in payload and type(payload[flag]) is not bool:
            c.fail(f"{flag} must be true or false.")
    try:
        sample = approve_voice_span(ctx, versions.ref(targets[0]), payload.get("locator"), payload.get("personaId"), payload.get("attestation"),
                                    polarity=payload.get("polarity", "positive"), brand=payload.get("brand"), language=payload.get("language"),
                                    uses=payload.get("uses"), confirmed=payload.get("confirmed") is True, grant_voice=payload.get("grantVoice") is True,
                                    approve_generated_text=payload.get("approveGeneratedText") is True, select=payload.get("select") is True,
                                    expected_revision=envelope.get("expectedRevision"))
    except AlphaError as error:
        if error.code == "library_voice_generated_needs_approval":
            return c.action_result("requires_confirmation", result={"confirm": "approveGeneratedText"}, warnings=[str(error)])
        raise
    warnings = sample.pop("warnings", [])
    return c.action_result("applied", revision=sample["revision"], result=sample, warnings=warnings)


def revoke_action(ctx, envelope: dict, targets: list[dict]) -> dict:
    """voice.revoke {sampleId, confirmed: true}; expectedRevision is the example's revision. A target, when sent, must be
    the example's own item."""
    payload = envelope.get("payload") or {}
    if not set(payload) <= {"sampleId", "confirmed"}:
        c.fail("Send the example to withdraw and confirm it.")
    if payload.get("confirmed") is not True:
        _refuse("Confirm that this voice example should be withdrawn.", 422, "library_voice_confirm")
    if len(targets) > 1:
        c.fail("Withdraw one example at a time.")
    asset = targets[0]["assetId"] if targets else None
    receipt = revoke_voice_sample(ctx, payload.get("sampleId"), envelope.get("expectedRevision"), asset_key=asset)
    return c.action_result("applied", revision=receipt["revision"], result=receipt)


def _audit(ctx, kind: str, subject: str, meta: dict):
    from ..hosted import audit
    audit(ctx.cur, ctx.workspace_id, ctx.actor, kind, subject, meta)
