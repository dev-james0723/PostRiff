"""Library intelligence T03 against disposable PostgreSQL (cloud CI; LIBRARY_PG_PHASE=no_vector and vector).

Real SQL for segment supersede/history, human-correction preservation, annotation layering through the action
receipts table, waveform/moment/metadata writes and understanding-card assembly. Storage and identity are synthetic.
No provider or network call is made: transcript text comes from a labelled contract-test reply, never a real ASR run.
"""
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "library_intelligence" / "media"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_storage import PrivateAssetService  # noqa: E402
from postriff_phase2.library_intelligence import actions, api, media, segments, structure, textnorm, understanding, versions  # noqa: E402
import media_fixtures as fx  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000044"
PHASE = os.environ.get("LIBRARY_PG_PHASE", "unspecified")
clock = [1789524000.0]
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in ("one", "other"):
        raise AlphaError("Verified session required.", 401)
    return ONE if token == "one" else OTHER


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    checks.append(name)


def refused(name, status, call):
    try:
        call()
    except AlphaError as error:
        check(name, error.status == status, (error.status, str(error)))
        return error
    raise AssertionError(f"{name}: expected HTTP {status}")


class Storage:
    def __init__(self):
        self.objects = {}
        self.file_bucket = "postriff-library"

    def signed_upload_url(self, ws, category, name):
        return f"https://upload.invalid/{ws}/{name}?token=fake"

    def put(self, ws, name, raw, mime):
        self.objects[(ws, name)] = (raw, mime, hashlib.sha256(raw).hexdigest()[:24])

    def object_info(self, ws, category, name):
        value = self.objects.get((ws, name))
        if not value:
            raise AlphaError("missing", 404)
        raw, mime, etag = value
        return {"bytes": len(raw), "mime": mime, "etag": etag}

    def get_bounded(self, ws, category, name, limit):
        raw = self.objects[(ws, name)][0]
        if len(raw) > limit:
            raise AlphaError("too large", 413)
        return raw

    def signed_url(self, ws, category, name, expires_in=300):
        return f"https://download.invalid/{ws}/{name}?token=fake"

    def delete(self, ws, category, name):
        self.objects.pop((ws, name), None)

    def list_prefix(self, prefix, bucket=None):
        ws, _ = prefix.split("/", 1)
        return [f"{ws}/file/{name}" for (owner, name) in self.objects if owner == ws]


with connection() as db:
    has_vector = db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_library_embeddings' "
                            "AND column_name='embedding'").fetchone() is not None
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
if PHASE == "vector":
    check("phase vector: pgvector column present", has_vector)
elif PHASE == "no_vector":
    check("phase no_vector: lexical-only database", not has_vector)

storage = Storage()
service = HostedWorkspaceService(connection, verify, assets=PrivateAssetService(storage), clock=lambda: clock[0])
service.bootstrap("one", "studio")
library = service.library


def upload(name, mime, raw):
    ticket = library.begin(wid, "one", {"filename": name, "mime": mime, "bytes": len(raw)})["upload"]
    key = ticket["assetId"]
    storage.put(wid, f"{key}.{name.rsplit('.', 1)[-1]}", raw, mime)
    if library.commit(wid, "one", key)["status"] == "queued":
        library.process(connection, wid, key)
    return key


@contextmanager
def ctx(principal=ONE, workspace=None):
    with connection() as db, db.cursor() as cur:
        yield api.context(cur, principal, workspace or wid, service=service, now=clock[0])


def envelope(action, payload, ref, key):
    return {"actionId": "pg1", "uiInstanceId": "pg-ui", "actionType": action, "targetRefs": [ref], "idempotencyKey": key, "payload": payload}


# --- documents: real extraction from private storage, supersede and history ------------------------------------------------------
doc_raw = "# Spring recital\n\nRehearse the Brahms sonata on Wednesday.\n\n我哋喺大會堂綵排，演奏会之前再練。\n".encode()
doc = upload("plan.md", "text/markdown", doc_raw)
with ctx() as c1:
    version = versions.get(c1, doc)
    batch = structure.extract_segments(c1, versions.ref(version))
    check("extract: verified original parsed into paragraphs", batch["state"] == "ready" and len(batch["segments"]) == 3, batch)
    check("extract: no page locator for a text file", all(s["locator"]["kind"] == "text" for s in batch["segments"]))
    media.write_media(c1.cur, wid, version, batch["media"])
    written = segments.write_segments(c1.cur, wid, version, batch["segments"], extractor=batch["extractor"], extractor_version=batch["extractorVersion"])
    check("write: three active rows", written == 3, written)
with connection() as db:
    rows = db.execute("SELECT text,text_hash,source_sha256,search_terms,normalizer_version,origin,language FROM public.pr_library_segments "
                      "WHERE workspace_id=%s AND version_key=%s ORDER BY ordinal", (wid, doc)).fetchall()
    sha = db.execute("SELECT sha256 FROM public.pr_library_assets WHERE id=%s", (doc,)).fetchone()[0]
    stored_media = db.execute("SELECT media FROM public.pr_library_assets WHERE id=%s", (doc,)).fetchone()[0]
    latin = db.execute("SELECT count(*) FROM public.pr_library_segments WHERE workspace_id=%s AND superseded_at IS NULL "
                       "AND search_vector @@ to_tsquery('simple','brahms')", (wid,)).fetchone()[0]
check("write: hash, source hash and normalizer recorded",
      all(r[1] == hashlib.sha256(r[0].encode()).hexdigest() and r[2] == sha and r[4] == textnorm.NORMALIZER_VERSION and r[5] == "extracted" for r in rows), rows)
check("write: search_terms from textnorm", all(r[3] == textnorm.search_terms(r[0]) for r in rows))
check("write: Cantonese paragraph labelled yue", rows[2][6] == "yue", rows[2])
check("write: media bounds stored", stored_media.get("textLength") == batch["media"]["textLength"], stored_media)
check("generated search_vector indexes the terms", latin == 1, latin)
with ctx() as c2:
    version = versions.get(c2, doc)
    changed = [dict(s, text=s["text"] + " (revised)") for s in batch["segments"]]
    segments.write_segments(c2.cur, wid, version, changed, extractor=batch["extractor"], extractor_version="structure-2")
    try:
        segments.write_segments(c2.cur, wid, version, [{"kind": "text", "text": "x", "locator": {"kind": "text", "start": 0, "end": 10 ** 6}}],
                                extractor=batch["extractor"], extractor_version="structure-3")
        raise AssertionError("out-of-bounds locator accepted")
    except AlphaError as error:
        check("write: locator outside the extracted text refused", error.status == 400)
with connection() as db:
    total, active = db.execute("SELECT count(*),count(*) FILTER (WHERE superseded_at IS NULL) FROM public.pr_library_segments "
                               "WHERE workspace_id=%s AND version_key=%s", (wid, doc)).fetchone()
check("reprocess: previous rows superseded, never deleted", (total, active) == (6, 3), (total, active))

# --- audio: real WAV decode, transcript, corrections that survive reprocessing --------------------------------------------------------
audio = upload("interview.wav", "audio/wav", fx.ramp_wav())
with ctx() as c3:
    version = versions.get(c3, audio)
    check("audio: stored as playable original", version["kind"] == "audio" and version["status"] == "unsupported", version["status"])
    preview = media.preview(version, media.read_original(c3, version))
    check("audio: real waveform decoded on the server", preview["state"] == "ready" and preview["media"]["durationMs"] == 500
          and preview["media"]["peaksSource"] == "server_decoded" and len(preview["media"]["peaks"]) == media.DEFAULT_BUCKETS, preview["state"])
    media.write_media(c3.cur, wid, version, preview["media"])
    reply = {"segments": [{"startMs": 0, "endMs": 200, "text": "大家好，我哋今日講 rehearsal 嘅 schedule"},
                          {"startMs": 200, "endMs": 400, "text": "Then we practise the Brahms sonata"},
                          {"startMs": 400, "endMs": 500, "text": "我們下星期再練習"}]}
    items = media.transcript_items(reply, 500)
    segments.write_segments(c3.cur, wid, versions.get(c3, audio), items, extractor=media.TRANSCRIPT_EXTRACTOR, extractor_version="asr-1:contract-test")
with connection() as db:
    target, language = db.execute("SELECT id,language FROM public.pr_library_segments WHERE workspace_id=%s AND version_key=%s AND superseded_at IS NULL "
                                  "AND (locator->>'startMs')::int=200", (wid, audio)).fetchone()
    first = db.execute("SELECT language,uncertainty,speaker_label FROM public.pr_library_segments WHERE workspace_id=%s AND version_key=%s "
                       "AND (locator->>'startMs')::int=0", (wid, audio)).fetchone()
check("transcript: per-segment language", language == "en" and first[0] == "yue", (language, first))
check("transcript: code-switching labelled, no speaker guessed", "code-switched" in first[1] and first[2] is None, first)
with ctx() as c4:
    corrected = segments.correct(c4, target.hex, "Then we practise the Brahms sonata, second movement", "Speaker 2")
check("correct: same locator, linked history", corrected["locator"] == {"kind": "time", "startMs": 200, "endMs": 400}
      and corrected["correctionOf"] == target.hex and corrected["origin"] == "user", corrected)
with ctx() as c5:
    refused("correct: superseded passage conflicts", 409, lambda: segments.correct(c5, target.hex, "late edit", None))
with ctx() as c6:
    audio_ref = versions.ref(versions.get(c6, audio))
    result = actions.apply(c6, envelope("annotation.correct", {"segmentId": corrected["id"], "text": "Then we practise the Brahms sonata, second movement.",
                                                               "speakerLabel": ""}, audio_ref, "pg-media-segment-0001"))
check("correct via action: applied, speaker label cleared", result["status"] == "applied" and result["result"]["segment"]["speakerLabel"] is None, result)
with ctx() as c7:
    rerun = media.transcript_items({"segments": [{"startMs": 0, "endMs": 200, "text": "大家好"}, {"startMs": 210, "endMs": 400, "text": "Then we practice the Brahms"},
                                                 {"startMs": 400, "endMs": 500, "text": "下星期再練"}]}, 500)
    fresh = segments.write_segments(c7.cur, wid, versions.get(c7, audio), rerun, extractor=media.TRANSCRIPT_EXTRACTOR, extractor_version="asr-1:contract-test-2")
check("reprocess: the re-guessed passage is shadowed by the human correction", fresh == 2, fresh)
with connection() as db:
    active = db.execute("SELECT origin,text FROM public.pr_library_segments WHERE workspace_id=%s AND version_key=%s AND superseded_at IS NULL ORDER BY ordinal",
                        (wid, audio)).fetchall()
    shadow = db.execute("SELECT superseded_at IS NOT NULL FROM public.pr_library_segments WHERE workspace_id=%s AND text=%s", (wid, "Then we practice the Brahms")).fetchone()
    history_total = db.execute("SELECT count(*) FROM public.pr_library_segments WHERE workspace_id=%s AND version_key=%s", (wid, audio)).fetchone()[0]
check("reprocess: human correction stays active", [o for o, _ in active] == ["transcript", "user", "transcript"]
      and active[1][1] == "Then we practise the Brahms sonata, second movement.", active)
check("reprocess: shadowed machine guess kept as history", shadow == (True,), shadow)
with ctx() as c8:
    listing = segments.segments_http(c8, {"params": {"key": audio}, "query": {}, "body": {}})
    seen, cursor = [], None
    while True:
        page = segments.segments_http(c8, {"params": {"key": audio}, "query": {"history": "1", "limit": "2", **({"cursor": cursor} if cursor else {})}, "body": {}})
        seen += page["segments"]
        cursor = page["nextCursor"]
        if not cursor:
            break
check("segments route: active passages in order", [s["locator"]["startMs"] for s in listing["segments"]] == [0, 200, 400], listing)
check("segments route: full history pages without gaps", len(seen) == history_total and len({s["id"] for s in seen}) == history_total, (len(seen), history_total))

# --- annotations: human decisions win over reprocessing ---------------------------------------------------------------------------------
with ctx() as c9:
    version = versions.get(c9, doc)
    ref = versions.ref(version)
    sid = segments.active_segments(c9, version)[0]["id"]
    evidence = [{"assetRef": ref, "segmentId": sid}]
    understanding.write_annotations(c9.cur, wid, version, [{"field": "topic", "value": v, "origin": "ai_suggested", "evidence": evidence}
                                                          for v in ("Brahms", "Rehearsal", "Pencils")], processor_version="understand-llm-1", model="contract-test")
with connection() as db:
    ids = {value: key.hex for key, value in db.execute("SELECT id,value FROM public.pr_library_annotations WHERE workspace_id=%s AND version_key=%s", (wid, doc))}
for n, (value, decision, extra) in enumerate((("Brahms", "confirm", {}), ("Rehearsal", "correct", {"value": "Rehearsal schedule"}), ("Pencils", "reject", {}))):
    with ctx() as cx:
        result = actions.apply(cx, envelope("annotation.correct", {"annotationId": ids[value], "decision": decision, **extra}, ref, f"pg-media-annotation-{n:04d}"))
    check(f"annotation {decision}: applied", result["status"] == "applied", result)
with ctx() as cx:
    replay = actions.apply(cx, envelope("annotation.correct", {"annotationId": ids["Brahms"], "decision": "confirm"}, ref, "pg-media-annotation-0000"))
check("annotation: replayed action returns the original receipt", replay.get("replayed") is True, replay)
with ctx() as c10:
    version = versions.get(c10, doc)
    added = understanding.write_annotations(c10.cur, wid, version, [{"field": "topic", "value": v, "origin": "ai_suggested", "evidence": evidence}
                                                                    for v in ("Brahms", "Concert", "Pencils")], processor_version="understand-llm-2", model="contract-test")
    local = understanding.understand_local(version, segments.active_segments(c10, version))
    understanding.write_annotations(c10.cur, wid, version, local["annotations"], processor_version="understand-local-1", replace_fields=understanding.LOCAL_FIELDS)
check("reprocess: decided values are not offered again", added == 1, added)
with connection() as db:
    state = db.execute("SELECT origin,active,value FROM public.pr_library_annotations WHERE workspace_id=%s AND version_key=%s AND field='topic' ORDER BY created_at",
                       (wid, doc)).fetchall()
check("reprocess: user_confirmed rows never deactivated", all(active for origin, active, _ in state if origin == "user_confirmed")
      and sum(1 for origin, _, _ in state if origin == "user_confirmed") == 3, state)
check("reprocess: only the new suggestion is an active machine topic", [v for o, a, v in state if o == "ai_suggested" and a] == ["Concert"], state)

# --- metadata, moments and browser waveform -------------------------------------------------------------------------------------------------
with ctx() as cx:
    result = actions.apply(cx, envelope("metadata.update", {"title": "Recital plan", "tags": ["recital", "Brahms"]}, versions.ref(versions.get(cx, doc)),
                                        "pg-media-metadata-0001"))
check("metadata: applied", result["status"] == "applied", result)
with connection() as db:
    meta = db.execute("SELECT display_title,title_source,original_filename,tags FROM public.pr_library_assets WHERE id=%s", (doc,)).fetchone()
    labels = db.execute("SELECT display_title,tags FROM public.pr_library_labels WHERE workspace_id=%s AND asset_key=%s", (wid, doc)).fetchone()
check("metadata: user title wins, original filename preserved", meta == ("Recital plan", "user", "plan.md", ["recital", "Brahms"]), meta)
check("metadata: labels follow the existing semantics", labels == ("Recital plan", ["recital", "Brahms"]), labels)
with ctx() as cx:
    result = actions.apply(cx, envelope("moment.save", {"startMs": 100, "endMs": 300, "label": "Brahms intro"}, versions.ref(versions.get(cx, audio)),
                                        "pg-media-moment-0001"))
check("moment: saved", result["status"] == "applied" and result["result"]["segment"]["kind"] == "moment", result)
with ctx() as cx:
    refused("moment: interval beyond the recording refused", 400,
            lambda: actions.apply(cx, envelope("moment.save", {"startMs": 100, "endMs": 900}, versions.ref(versions.get(cx, audio)), "pg-media-moment-0002")))
with connection() as db:
    moment = db.execute("SELECT origin,locator,text FROM public.pr_library_segments WHERE workspace_id=%s AND version_key=%s AND kind='moment'", (wid, audio)).fetchall()
check("moment: one user row with a time locator", moment == [("user", {"kind": "time", "startMs": 100, "endMs": 300}, "Brahms intro")], moment)
flac = upload("take.flac", "audio/flac", fx.RAMP_FLAC.read_bytes())
with ctx() as cx:
    version = versions.get(cx, flac)
    saved = media.waveform_http(cx, {"params": {"key": flac}, "query": {}, "body": {"sha256": version["sha256"], "durationMs": 500, "peaks": [0.1, 0.6, 0.9]}})
check("waveform: browser peaks stored and labelled", saved["media"]["peaksSource"] == "browser_decoded", saved)
with ctx() as cx:
    refused("waveform: wrong version hash", 409, lambda: media.waveform_http(cx, {"params": {"key": flac}, "query": {},
                                                                                  "body": {"sha256": "0" * 64, "durationMs": 500, "peaks": [0.1]}}))
with connection() as db:
    flac_media = db.execute("SELECT media FROM public.pr_library_assets WHERE id=%s", (flac,)).fetchone()[0]
check("waveform: jsonb merge kept the browser peaks", flac_media.get("peaks") == [0.1, 0.6, 0.9] and flac_media.get("durationSource") == "browser_decoded", flac_media)

# --- the understanding card ------------------------------------------------------------------------------------------------------------------
with connection() as db:
    db.execute("INSERT INTO public.pr_library_capabilities(workspace_id,asset_key,capability,state,processor_version,completed_at) "
               "VALUES(%s,%s,'extract','ready','structure-1',now())", (wid, doc))
with ctx() as cx:
    card = understanding.card_http(cx, {"params": {"key": doc}, "query": {}, "body": {}})
    audio_card = understanding.card(cx, versions.ref(versions.get(cx, audio)))
check("card: contract keys", set(card) == {"contractVersion", "assetRef", "displayTitle", "originalFilename", "kind", "mime", "summary", "topics", "usefulSegments",
                                            "suggestedUses", "annotations", "sourceStatus", "capabilityStates", "media", "versions"}, sorted(card))
states = {s["capability"]: s for s in card["capabilityStates"]}
check("card: stored capability state read directly", states["extract"]["state"] == "ready" and states["extract"]["processorVersion"] == "structure-1", states["extract"])
check("card: inapplicable capability honest", states["transcribe"] == {"capability": "transcribe", "state": "unsupported", "errorCode": "not_applicable"})
check("card: title and filename distinct", (card["displayTitle"], card["originalFilename"]) == ("Recital plan", "plan.md"), card["displayTitle"])
check("card: decisions and suggestions distinct", sorted((t["value"], t["origin"]) for t in card["topics"] if t["origin"] != "extracted")
      == [("Brahms", "user_confirmed"), ("Concert", "ai_suggested"), ("Rehearsal schedule", "user_confirmed")], card["topics"])
check("card: extractive summary with evidence", card["summary"] and card["summary"]["origin"] == "extracted", card["summary"])
check("card: every purpose reported", set(card["sourceStatus"]) == {"browse", "answer", "draft_evidence", "voice", "memory", "public_use"}
      and card["sourceStatus"]["browse"]["allowed"] and not card["sourceStatus"]["answer"]["allowed"], card["sourceStatus"])
check("card: version stack", [v["current"] for v in card["versions"]] == [True], card["versions"])
check("card: no uncalibrated confidence", all("confidence" not in a for a in card["annotations"]))
audio_states = {s["capability"]: s for s in audio_card["capabilityStates"]}
check("audio card: transcription blocked without a cloud grant", audio_states["transcribe"]["state"] == "blocked_permission"
      and audio_states["transcribe"]["errorCode"] == "processing_grant_required", audio_states["transcribe"])
check("audio card: real waveform and duration", audio_card["media"]["peaksSource"] == "server_decoded" and audio_card["media"]["durationMs"] == 500)
check("audio card: saved moment is a useful segment", any(s["kind"] == "moment" for s in audio_card["usefulSegments"]))

# --- isolation and roles ------------------------------------------------------------------------------------------------------------------------
with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (OTHER,))
other_workspace = service.bootstrap("other", "studio")["workspaceId"]
with ctx(OTHER, other_workspace) as cx:
    refused("isolation: foreign workspace cannot list passages", 404, lambda: segments.segments_http(cx, {"params": {"key": audio}, "query": {}, "body": {}}))
    refused("isolation: foreign workspace cannot read the card", 404, lambda: understanding.card_http(cx, {"params": {"key": doc}, "query": {}, "body": {}}))
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active') "
               "ON CONFLICT(workspace_id,user_id) DO UPDATE SET role='viewer',status='active'", (wid, OTHER))
with ctx(OTHER) as cx:
    check("viewer: may read passages", len(segments.segments_http(cx, {"params": {"key": audio}, "query": {}, "body": {}})["segments"]) >= 3)
    refused("viewer: may not correct passages", 403, lambda: segments.correct(cx, corrected["id"], "viewer edit", None))
    refused("viewer: may not store a waveform", 403, lambda: media.waveform_http(cx, {"params": {"key": flac}, "query": {},
                                                                                      "body": {"sha256": "0" * 64, "durationMs": 500, "peaks": [0.1]}}))
for table in ("pr_library_segments", "pr_library_annotations", "pr_library_capabilities"):
    with connection() as db:
        db.execute("SET ROLE authenticated")
        try:
            db.execute("SELECT * FROM public." + table)
            raise AssertionError("browser role could read " + table)
        except psycopg.errors.InsufficientPrivilege:
            db.rollback()
    checks.append(f"authenticated browser role cannot read {table}")

print(json.dumps({"status": "pass", "phase": PHASE, "pgvector": has_vector, "execution": "disposable-postgres; synthetic storage; contract-test transcript",
                  "checks": checks}, indent=2, ensure_ascii=False))
