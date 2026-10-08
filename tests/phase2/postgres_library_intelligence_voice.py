"""T07 against disposable PostgreSQL: Library voice spans through the canonical voice system (A007, A044–A048).

Real SQL through HostedWorkspaceService: a note ingested by the real intake and Library worker, segments written by
segments.write_segments, the Library 'voice' grant with its attestation, span approval through the actions route
(canonical voice_samples_import/voice_sample_grant/voice_sample_select in the same transaction as the
pr_library_voice_samples row and the repository effects), a negative example, a derived profile built by the canonical
commands, revocation (speaker revision stale, growth genome stale, retrieve() excludes it), grant-revocation
withdrawal, a concurrent revoke that wins against an in-flight approval (TOCTOU), and cross-workspace denial.

Runs twice in cloud CI (LIBRARY_PG_PHASE=no_vector, then vector); nothing here depends on pgvector. Fake private
storage; no provider or network calls. Users are fresh synthetic UUIDs (rls.sql marks …0002 deleted).
"""
import hashlib
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

os.environ["RAFII_LIBRARY_VOICE_ENABLED"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import memory, voice_sources  # noqa: E402
from postriff_phase2.growth.service import GrowthService  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_storage import PrivateAssetService  # noqa: E402
from postriff_phase2.library_intelligence import api, policy, segments, versions, voice  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
PHASE = os.environ.get("LIBRARY_PG_PHASE", "no_vector")
OWNER = "7e1c0de0-0000-4000-8000-0000000007e1"
OTHER = "7e1c0de0-0000-4000-8000-0000000007e2"
VIEWER = "7e1c0de0-0000-4000-8000-0000000007e3"
TOKENS = {"owner": OWNER, "other": OTHER, "viewer": VIEWER}
WRITER = "cloud:vercel-ai-gateway:openai/gpt-5.1"
USES = [{"purpose": "analysis", "route": "local-rules"}, {"purpose": "generation", "route": voice_sources.MANAGED_WRITER_ROUTE}]
WROTE = {"authoredByMe": True, "method": "written_by_me"}
clock = [1789524000.0]
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required.", 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    checks.append(name)


def expect_error(name, fn, status=None, code=None):
    try:
        fn()
    except AlphaError as error:
        ok = (status is None or error.status == status) and (code is None or error.code == code)
        check(name, ok, (error.status, error.code, str(error)))
        return error
    check(name, False, "no error raised")


def scalar(sql, args=()):
    with connection() as db:
        row = db.execute(sql, args).fetchone()
    return row[0] if row else None


class Storage:
    def __init__(self):
        self.objects = {}
        self.file_bucket = "postriff-library"

    def signed_upload_url(self, ws, category, name):
        return f"https://upload.invalid/{ws}/{name}?token=fake"

    def put_immutable(self, ws, category, name, raw, content_type="text/plain"):
        if (ws, category, name) in self.objects:
            raise AlphaError("This immutable object already exists.", 409)
        self.objects[(ws, category, name)] = (raw, content_type, hashlib.sha256(raw).hexdigest()[:24])
        return f"{ws}/{category}/{name}"

    def object_info(self, ws, category, name):
        value = self.objects.get((ws, category, name))
        if not value:
            raise AlphaError("missing", 404)
        raw, mime, etag = value
        return {"bytes": len(raw), "mime": mime, "etag": etag}

    def get_bounded(self, ws, category, name, limit):
        raw = self.objects[(ws, category, name)][0]
        if len(raw) > limit:
            raise AlphaError("too large", 413)
        return raw

    def get(self, ws, category, name):
        return self.objects[(ws, category, name)][0]

    def signed_url(self, ws, category, name, expires_in=300):
        return f"https://download.invalid/{ws}/{name}?token=fake"

    def delete(self, ws, category, name):
        self.objects.pop((ws, category, name), None)

    def list_prefix(self, prefix, bucket=None):
        ws, category = prefix.split("/", 1)
        return [f"{ws}/{category}/{name}" for (owner, cat, name) in self.objects if owner == ws and cat == category]


def route(method, ws, rest, token, body=None):
    return service.library_intelligence.route(method, ws, rest, {}, lambda: body or {}, token)


@contextmanager
def ctx(principal=OWNER, workspace=None):
    with connection() as db, db.cursor() as cur:
        yield api.context(cur, principal, workspace or w1, service=service, now=clock[0])


def state_of(ws):
    with connection() as db:
        row = db.execute("SELECT revision,state FROM public.pr_workspaces WHERE id=%s", (ws,)).fetchone()
    return int(row[0]), (json.loads(row[1]) if isinstance(row[1], str) else row[1])


def samples_in(state):
    return [s for s in state.get("sources", []) if s.get("kind") == "voice_sample"]


def voice_rows(ws):
    with connection() as db:
        return db.execute("SELECT replace(id::text,'-',''),voice_source_id,persona_id,language,polarity,status,text,revision,consent_revision "
                          "FROM public.pr_library_voice_samples WHERE workspace_id=%s ORDER BY created_at,id", (ws,)).fetchall()


def envelope(action, ref, payload, key, expected=None):
    return {"actionId": "pg-voice", "uiInstanceId": "pg-library", "actionType": action, "targetRefs": [ref] if ref else [],
            "expectedRevision": expected, "idempotencyKey": "pg-voice-key-" + key, "payload": payload}


def ingest_note(ws, token, text, key):
    # Through the HTTP route: ingest runs in read mode and stores through ctx.open_write (worker A), as in production.
    status, note = route("POST", ws, ["ingest", "note"], token, {"text": text, "authoredByMe": True, "idempotencyKey": key})
    assert status == 201, (status, note)
    asset = note["asset"]["assetRef"]["assetId"]
    service.library.process(connection, ws, asset)
    return asset


def write_paragraphs(ws, principal, asset, paragraphs):
    items, offset = [], 0
    for paragraph in paragraphs:
        items.append({"kind": "text", "text": paragraph, "language": "en", "locator": {"kind": "text", "start": offset, "end": offset + len(paragraph)}})
        offset += len(paragraph) + 2
    with ctx(principal, ws) as c1:
        version = versions.get(c1, asset)
        written = segments.write_segments(c1.cur, ws, version, items, extractor="pg-voice-fixture", extractor_version="1")
        return versions.ref(version), written


def span(index, paragraphs):
    start = sum(len(p) + 2 for p in paragraphs[:index])
    return {"kind": "text", "start": start, "end": start + len(paragraphs[index])}


# --- setup: fresh synthetic members, workspaces, growth effect ------------------------------------------------------------
with connection() as db:
    has_vector = bool(db.execute("SELECT 1 FROM information_schema.columns WHERE table_name='pr_library_embeddings' AND column_name='embedding'").fetchone())
    for user in TOKENS.values():
        db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (user,))
if PHASE == "vector":
    check("phase vector: pgvector column present", has_vector)
elif PHASE == "no_vector":
    check("phase no_vector: lexical-only database", not has_vector)

storage = Storage()
service = HostedWorkspaceService(connection, verify, assets=PrivateAssetService(storage), clock=lambda: clock[0])
service.growth = GrowthService(service, env={})  # its invalidate hook joins repository.effects, as hosted_app wires it
seen_effects = []
service.repository.effects.append(lambda cur, ws, before, after, principal: seen_effects.append(
    (ws, len(samples_in(before)), len(samples_in(after)), sum(1 for s in samples_in(after) if s.get("active")))))
w1 = service.bootstrap("owner", "studio")["workspaceId"]
w2 = service.bootstrap("other", "studio")["workspaceId"]
service.bootstrap("viewer", "studio")
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active') "
               "ON CONFLICT(workspace_id,user_id) DO UPDATE SET role='viewer',status='active'", (w1, VIEWER))

P0 = "Every morning I practise scales slowly, then I play the piece once at tempo."
P1 = "“Slow practice is fast learning.”"
P2 = "Tonight's programme opens with Brahms and you will not want to miss it!!! Book now!!!"
note = ingest_note(w1, "owner", "\n\n".join([P0, P1, P2]), "pg-voice-note-0000001")
check("setup: note processed by the Library worker", scalar("SELECT processing_status FROM public.pr_library_assets WHERE id=%s", (note,)) == "ready")
ref, written = write_paragraphs(w1, OWNER, note, [P0, P1, P2])
check("setup: three active segments with text locators", written == 3 and len(ref["sha256"]) == 64, (written, ref))
foreign = ingest_note(w2, "other", "A note that belongs to another workspace.", "pg-voice-note-0000002")
foreign_ref, _ = write_paragraphs(w2, OTHER, foreign, ["A note that belongs to another workspace."])

# --- admission requires the voice grant and its attestation ---------------------------------------------------------------
payload = {"locator": span(0, [P0, P1, P2]), "attestation": WROTE, "uses": USES, "confirmed": True, "select": True}
status, outcome = route("POST", w1, ["actions"], "owner", envelope("voice.approve_span", ref, payload, "storage-only-001"))
check("storage-only: no voice grant, no admission", status == 200 and outcome["status"] == "denied", outcome)
check("storage-only: nothing written", samples_in(state_of(w1)[1]) == [] and voice_rows(w1) == [])
status, viewer = route("POST", w1, ["actions"], "viewer", envelope("voice.approve_span", ref, payload, "viewer-approve-1"))
check("roles: a viewer cannot approve a voice span", viewer["status"] == "denied", viewer)
expect_error("grant: voice needs the authorship attestation",
             lambda: route("POST", w1, ["grants"], "owner", {"grantType": "purpose", "purpose": "voice", "scope": {"kind": "asset", "assetId": note}}),
             422, "library_voice_attestation")
status, grant_a = route("POST", w1, ["grants"], "owner", {"grantType": "purpose", "purpose": "voice", "scope": {"kind": "asset", "assetId": note},
                                                          "attestation": WROTE})
check("grant: owner grants voice for this note with the attestation", status == 201, grant_a)
check("grant: attestation stored with the grant",
      scalar("SELECT attestation->>'method' FROM public.pr_library_grants WHERE workspace_id=%s AND purpose='voice' AND revoked_at IS NULL", (w1,)) == "written_by_me")

# --- refusals happen before any write ---------------------------------------------------------------------------------------
whole = {"kind": "text", "start": 0, "end": span(2, [P0, P1, P2])["end"]}
expect_error("span: the whole note is refused", lambda: route("POST", w1, ["actions"], "owner",
             envelope("voice.approve_span", ref, {**payload, "locator": whole}, "whole-doc-000001")), 422, "library_voice_whole_document")
status, quoted = route("POST", w1, ["actions"], "owner", envelope("voice.approve_span", ref, {**payload, "locator": span(1, [P0, P1, P2])}, "quoted-0000001"))
check("span: a quotation is refused", quoted["status"] == "denied", quoted)
check("refusals: nothing written", samples_in(state_of(w1)[1]) == [] and voice_rows(w1) == [])

# --- approve one passage through the actions route ------------------------------------------------------------------------
revision_before, _ = state_of(w1)
status, applied = route("POST", w1, ["actions"], "owner", envelope("voice.approve_span", ref, payload, "approve-p0-00001"))
check("approve: applied", status == 200 and applied["status"] == "applied", applied)
sample = applied["result"]
revision_after, state = state_of(w1)
[canonical] = samples_in(state)
check("approve: workspace state saved once in the same transaction", revision_after == revision_before + 1, (revision_before, revision_after))
check("approve: canonical sample via voice_samples_import", canonical["text"] == P0 and canonical["voiceOrigin"] == "user_provided" and canonical["active"], canonical)
check("approve: library origin on the canonical sample", canonical["libraryOrigin"]["assetId"] == note and canonical["libraryOrigin"]["sha256"] == ref["sha256"]
      and canonical["libraryOrigin"]["locator"] == span(0, [P0, P1, P2]), canonical.get("libraryOrigin"))
check("approve: granted through voice_sample_grant", sorted(canonical["purposeGrants"]) == ["analysis", "generation"] and canonical["selected"], canonical)
rows = voice_rows(w1)
check("approve: indexed span links the canonical sample", len(rows) == 1 and rows[0][1] == canonical["id"] and rows[0][2:6] == ("default", "en", "positive", "approved"), rows)
check("approve: consent revision recorded", rows[0][8] == grant_a["grantRevision"], rows[0])
check("approve: effects ran inside the command", any(e[0] == w1 and e[2] == 1 for e in seen_effects), seen_effects)
check("approve: audited without content", scalar("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s AND kind='library.voice_span_approved' "
                                                  "AND meta::text NOT LIKE %s", (w1, "%practise%")) == 1)
status, replay = route("POST", w1, ["actions"], "owner", envelope("voice.approve_span", ref, payload, "approve-p0-00001"))
check("approve: replayed key returns the receipt, writes nothing", replay.get("replayed") is True and len(voice_rows(w1)) == 1 and len(samples_in(state_of(w1)[1])) == 1)

# --- a negative example stays in the Library index only -----------------------------------------------------------------------
negative_payload = {"locator": span(2, [P0, P1, P2]), "attestation": WROTE, "confirmed": True, "polarity": "negative"}
status, negative = route("POST", w1, ["actions"], "owner", envelope("voice.approve_span", ref, negative_payload, "negative-p2-0001"))
check("negative: applied", negative["status"] == "applied", negative)
rows = voice_rows(w1)
check("negative: indexed without a canonical sample", rows[1][1] is None and rows[1][4] == "negative" and len(samples_in(state_of(w1)[1])) == 1, rows)

# --- a derived profile built by the canonical commands ------------------------------------------------------------------------
revision, _ = state_of(w1)
service.repository.mutate(w1, "owner", revision, "voice_profile_analyze", {"sourceIds": [canonical["id"]], "route": "local-rules"})
revision, _ = state_of(w1)
service.repository.mutate(w1, "owner", revision, "profile_decide", {"decision": "approve"})
_, state = state_of(w1)
active = memory.active_profile(state)
check("profile: approved from the Library sample", active and canonical["id"] in active["profile"]["evidenceSourceIds"], active)
with connection() as db:
    db.execute("INSERT INTO public.pr_genome_versions(workspace_id,body,status,created_by) VALUES(%s,'{}'::jsonb,'approved',%s)", (w1, OWNER))
status, summary = route("GET", w1, ["voice"], "viewer")
default = next(p for p in summary["personas"] if p["personaId"] == "default")
check("summary: counts and current profile, readable by a viewer", status == 200 and default["profile"]["status"] == "current"
      and [(g["language"], g["positiveCount"], g["negativeCount"]) for g in default["groups"]] == [("en", 1, 1)], summary)
status, view = route("GET", w1, ["assets", note, "voice"], "owner")
check("asset voice: samples and negatives with status", [s["status"] for s in view["samples"]] == ["approved"] and len(view["negatives"]) == 1
      and view["sourceRole"]["role"] == "own_note", view)
with ctx() as c1:
    exemplars = voice.style_exemplars(c1, "default", "en", 6)
check("exemplars: positive and negative with provenance", [x["sampleId"] for x in exemplars["positive"]] == [sample["sampleId"]]
      and exemplars["negative"][0]["text"] == P2 and exemplars["positive"][0]["locator"] == span(0, [P0, P1, P2]), exemplars)
with ctx() as c1:
    check("exemplars: another persona or language sees nothing", voice.style_exemplars(c1, "teacher", "en", 6)["positive"] == []
          and voice.style_exemplars(c1, "default", "yue", 6)["positive"] == [])
check("retrieve: canonical retrieval returns the sample before revocation",
      [s["id"] for s in voice_sources.retrieve(state_of(w1)[1], [canonical["id"]], "generation", WRITER)["samples"]] == [canonical["id"]])


def keys_of(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys_of(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys_of(item)


banned = ("score", "percent", "match", "confidence", "similarity", "probability")
check("no score: summary, asset view and exemplars carry examples and counts, never a score",
      not [k for blob in (summary, view, exemplars, sample) for k in keys_of(blob) if any(word in k.lower() for word in banned)])

# --- revocation: canonical revoke, stale profile, growth invalidation, withdrawn span -----------------------------------------
status, revoked = route("POST", w1, ["actions"], "owner", envelope("voice.revoke", ref, {"sampleId": sample["sampleId"], "confirmed": True}, "revoke-p0-000001", expected=1))
check("revoke: applied", revoked["status"] == "applied", revoked)
receipt = revoked["result"]
check("revoke: speaker revision invalidated", receipt["invalidated"]["speakerRevisions"] == [active["revision"]] and receipt["invalidated"]["activeProfileStale"], receipt)
check("revoke: future retrieval excludes it", receipt["retrieval"] == {"excludedFromFutureRetrieval": True, "canonicalReason": "revoked"}, receipt)
_, state = state_of(w1)
canonical_after = next(s for s in samples_in(state) if s["id"] == canonical["id"])
check("revoke: canonical sample inactive and emptied", not canonical_after["active"] and canonical_after["text"] == "" and canonical_after["useGrants"] == [])
check("revoke: persistent profile stale; VOICE.md no longer uses it", memory.active_profile(state)["stale"]
      and "No active voice profile yet" in next(f["body"] for f in memory.render_files(state) if f["name"] == "VOICE.md"))
check("revoke: retrieve() excludes it", voice_sources.retrieve(state, [canonical["id"]], "generation", WRITER)["samples"] == [])
check("revoke: growth genome staled by the repository effect", scalar("SELECT status FROM public.pr_genome_versions WHERE workspace_id=%s", (w1,)) == "stale")
rows = voice_rows(w1)
check("revoke: index row withdrawn without its text", rows[0][5:8] == ("revoked", "(withdrawn)", 2), rows[0])
status, summary = route("GET", w1, ["voice"], "owner")
default = next(p for p in summary["personas"] if p["personaId"] == "default")
check("revoke: summary reports the stale profile and no approved example", default["profile"]["status"] == "stale"
      and sum(g["positiveCount"] for g in default["groups"]) == 0, summary)
status, stale = route("POST", w1, ["actions"], "owner", envelope("voice.revoke", ref, {"sampleId": rows[1][0], "confirmed": True}, "revoke-neg-stale1", expected=7))
check("revoke: a stale expected revision conflicts and changes nothing", stale["status"] == "conflict" and voice_rows(w1)[1][5] == "approved", stale)

# --- revoking the Library voice grant withdraws every span of the note ----------------------------------------------------------
status, again = route("POST", w1, ["actions"], "owner", envelope("voice.approve_span", ref, {**payload, "select": False}, "approve-p0-again1"))
check("re-approve: a fresh canonical sample after revocation", again["status"] == "applied" and again["result"]["voiceSourceId"] != canonical["id"], again)
status, revoked_grant = route("DELETE", w1, ["grants", grant_a["grantId"]], "owner", {})
check("grant revoke: both remaining spans withdrawn", revoked_grant["propagation"]["voiceSpansWithdrawn"] == 2, revoked_grant)
_, state = state_of(w1)
check("grant revoke: canonical sample revoked in the same transaction",
      not next(s for s in samples_in(state) if s["id"] == again["result"]["voiceSourceId"])["active"])
check("grant revoke: no approved span remains", all(r[5] == "revoked" for r in voice_rows(w1)), voice_rows(w1))

# --- TOCTOU: a revoke that commits while an approval is between its check and its write wins -----------------------------------
status, grant_b = route("POST", w1, ["grants"], "owner", {"grantType": "purpose", "purpose": "voice", "scope": {"kind": "asset", "assetId": note},
                                                          "attestation": WROTE})
outcome_box = {}
original_recheck = policy.recheck


def recheck_after_concurrent_revoke(rctx_unused, decisions):
    # Deterministic interleaving: the approval has passed its first check; another session commits the revoke before
    # the approval's recheck runs (recheck reads the committed revision without holding a lock).
    policy.recheck = original_recheck
    with connection() as db, db.cursor() as cur:
        rctx = api.context(cur, OWNER, w1, service=service, now=clock[0])
        outcome_box["revoke"] = policy.revoke(rctx, grant_b["grantId"])
    outcome_box["interleaved"] = True
    return original_recheck(rctx_unused, decisions)


policy.recheck = recheck_after_concurrent_revoke
try:
    with ctx() as c1:
        expect_error("toctou: approval refused after the concurrent revoke",
                     lambda: voice.approve_voice_span(c1, ref, span(0, [P0, P1, P2]), "default", WROTE, uses=USES, confirmed=True), 403, "library_grant_required")
finally:
    policy.recheck = original_recheck
check("toctou: the revoke committed between the approval's check and its write", outcome_box.get("interleaved") is True and outcome_box.get("revoke"), outcome_box)
check("toctou: nothing admitted", all(r[5] == "revoked" for r in voice_rows(w1))
      and not any(s.get("active") for s in samples_in(state_of(w1)[1])), voice_rows(w1))

# --- cross-workspace isolation -------------------------------------------------------------------------------------------------
expect_error("isolation: a non-member cannot read this workspace's voice summary", lambda: route("GET", w1, ["voice"], "other"), 403)
expect_error("isolation: a non-member cannot act in this workspace", lambda: route("POST", w1, ["actions"], "other",
             envelope("voice.approve_span", ref, payload, "foreign-actor-01")), 403)
with connection() as db, db.cursor() as cur:
    expect_error("isolation: api context refuses a non-member", lambda: api.context(cur, OTHER, w1), 403)
status, cross = route("POST", w1, ["actions"], "owner", envelope("voice.approve_span", foreign_ref, payload, "foreign-ref-0001"))
check("isolation: another workspace's item is denied without detail", cross["status"] == "denied" and foreign not in json.dumps(cross), cross)
status, other_summary = route("GET", w2, ["voice"], "other")
check("isolation: the other workspace sees none of these examples", all(g["positiveCount"] == 0 and g["negativeCount"] == 0
      for p in other_summary["personas"] for g in p["groups"]) and voice_rows(w2) == [], other_summary)
with connection() as db:
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (OWNER,))
    try:
        db.execute("SELECT * FROM public.pr_library_voice_samples")
    except psycopg.errors.InsufficientPrivilege:
        db.rollback()
        checks.append("rls: authenticated role cannot read pr_library_voice_samples")
    else:
        raise AssertionError("browser role could read pr_library_voice_samples")

print(json.dumps({"status": "pass", "phase": PHASE, "execution": "disposable-local-postgres", "checks": checks}, indent=2, ensure_ascii=False))
