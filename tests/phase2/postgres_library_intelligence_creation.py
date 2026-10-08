"""T08 against disposable PostgreSQL: source packs, a real Ideas draft and final-artifact return (R12, R13; D2, D5; A049–A053).

End to end through HostedWorkspaceService and real SQL: notes ingested through the intake route and processed by the Library
worker, segments, one note imported into Ideas with approved facts and cloud sharing, a consented voice span, a source pack
recommended by the real search (purpose draft_evidence), attached to a real draft made by quick_start + apply, the draft
accepted by the person (variant_review) so the repository effect writes and registers the deliverable, a replayed
completion event that yields the same asset, the normal Library worker processing it, lineage, a grant change that blocks a
second attach, and cross-workspace denial.

Runs twice in cloud CI (LIBRARY_PG_PHASE=no_vector, then vector); lexical search only, so nothing depends on pgvector.
Fake private storage; the Ideas writer is the built-in deterministic preview. No provider or network call.
"""
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

for _flag in ("RAFII_LIBRARY_VOICE_ENABLED", "RAFII_LIBRARY_RETRIEVAL_ENABLED", "RAFII_LIBRARY_TASK_UI_ENABLED"):
    os.environ[_flag] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import voice_sources  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_storage import PrivateAssetService  # noqa: E402
from postriff_phase2.library_intelligence import api, artifacts, segments, versions  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
PHASE = os.environ.get("LIBRARY_PG_PHASE", "no_vector")
OWNER = "7e1c0de0-0000-4000-8000-0000000008a1"
OTHER = "7e1c0de0-0000-4000-8000-0000000008a2"
VIEWER = "7e1c0de0-0000-4000-8000-0000000008a3"
TOKENS = {"owner": OWNER, "other": OTHER, "viewer": VIEWER}
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
        check(name, (status is None or error.status == status) and (code is None or error.code == code), (error.status, error.code, str(error)))
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

    def put_immutable(self, ws, category, name, raw, content_type="application/octet-stream"):
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
        return self.get(ws, category, name)

    def get(self, ws, category, name):
        value = self.objects.get((ws, category, name))
        if not value:
            raise AlphaError("missing", 404)
        return value[0]

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


def mutate(ws, token, action, payload):
    revision, _ = state_of(ws)
    return service.repository.mutate(ws, token, revision, action, payload)


def envelope(action, refs, payload, key, expected=None):
    return {"actionId": "pg-creation", "uiInstanceId": "pg-library", "actionType": action, "targetRefs": list(refs), "expectedRevision": expected,
            "idempotencyKey": "pg-creation-" + key, "payload": payload}


def ingest_note(ws, token, paragraphs, key):
    status, note = route("POST", ws, ["ingest", "note"], token, {"text": "\n\n".join(paragraphs), "authoredByMe": True, "idempotencyKey": key})
    assert status == 201, (status, note)
    asset = note["asset"]["assetRef"]["assetId"]
    service.library.process(connection, ws, asset)
    items, offset = [], 0
    for paragraph in paragraphs:
        items.append({"kind": "text", "text": paragraph, "language": "en", "locator": {"kind": "text", "start": offset, "end": offset + len(paragraph)}})
        offset += len(paragraph) + 2
    principal = TOKENS[token]
    with ctx(principal, ws) as c1:
        version = versions.get(c1, asset)
        segments.write_segments(c1.cur, ws, version, items, extractor="pg-creation-fixture", extractor_version="1")
        return asset, versions.ref(version)


# --- setup -----------------------------------------------------------------------------------------------------------------
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
# Coordinator hook (b) as proposed for hosted.py: accepted drafts come home in the accepting command's transaction.
service.repository.effects.append(artifacts.capture_effect)
w1 = service.bootstrap("owner", "studio")["workspaceId"]
w2 = service.bootstrap("other", "studio")["workspaceId"]
service.bootstrap("viewer", "studio")
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active') "
               "ON CONFLICT(workspace_id,user_id) DO UPDATE SET role='viewer',status='active'", (w1, VIEWER))

DIARY = ["I practise Brahms slowly before every recital.", "Then I play the whole programme once at tempo."]
FACTS = ["Brahms recital at City Hall on 12 October 2026.", "The programme pairs the Op.118 Intermezzi with the Ballades."]
diary, diary_ref = ingest_note(w1, "owner", DIARY, "pg-creation-note-0001")
facts, facts_ref = ingest_note(w1, "owner", FACTS, "pg-creation-note-0002")
foreign, foreign_ref = ingest_note(w2, "other", ["A Brahms recital note from another workspace."], "pg-creation-note-0003")
check("setup: notes processed with verified hashes", len(diary_ref["sha256"]) == 64 and len(facts_ref["sha256"]) == 64)

# The facts note is imported into Ideas, its facts approved and cloud sharing allowed: approved evidence for drafts.
revision, _ = state_of(w1)
imported = service.library.as_source(w1, "owner", facts, {"expectedRevision": revision})
_, state = state_of(w1)
fact_source = next(s for s in state["sources"] if s["id"] == imported["sourceId"])
mutate(w1, "owner", "approve_source", {"sourceId": fact_source["id"], "factIds": [f["id"] for f in fact_source["facts"]]})
mutate(w1, "owner", "source_policy", {"sourceId": fact_source["id"], "policy": "rewrite_approval", "egressConsent": ["local", "cloud"], "confirmed": True})

# A consented voice span on the diary (T07 path).
status, voice_grant = route("POST", w1, ["grants"], "owner", {"grantType": "purpose", "purpose": "voice", "scope": {"kind": "asset", "assetId": diary},
                                                             "attestation": WROTE})
status, span = route("POST", w1, ["actions"], "owner", envelope("voice.approve_span", [diary_ref], {
    "locator": {"kind": "text", "start": 0, "end": len(DIARY[0])}, "attestation": WROTE, "uses": USES, "confirmed": True, "select": True}, "voice-span-01"))
check("voice: span approved", span["status"] == "applied", span)
sample = span["result"]

# A real Ideas draft: quick_start with the deterministic preview, then apply.
revision, _ = state_of(w1)
quick = service.ideas.quick_start(w1, "owner", revision, {"text": "Brahms recital announcement for my students.", "ownContent": True, "confirmUse": True,
                                                          "destinations": [{"platform": "LinkedIn", "language": "English"}]})
check("draft: quick start completed a run", quick["status"] == "completed", quick.get("status"))
revision, _ = state_of(w1)
applied = service.ideas.apply(w1, "owner", revision, quick["runId"], quick["artifactHash"])
draft_id = applied["variantIds"][0]["variantId"]
_, state = state_of(w1)
draft = next(v for v in state["variants"] if v["id"] == draft_id)
check("draft: a real variant from that run", draft.get("runId") == quick["runId"] or (draft.get("provenance") or {}).get("runId") == quick["runId"], draft)
check("artifact: a working draft is not registered", scalar("SELECT count(*) FROM public.pr_library_artifacts WHERE workspace_id=%s", (w1,)) == 0)

# --- source pack ---------------------------------------------------------------------------------------------------------------
back = {"query": "brahms", "scope": {"kind": "workspace"}, "sort": "newest", "selection": [diary, facts], "anchor": facts}
task = {"userGoal": "Announce my Brahms recital", "scope": {"kind": "workspace"}, "locale": "en", "channels": ["LinkedIn"],
        "selectedSourceRefs": [{"assetRef": diary_ref}], "returnTo": back}
expect_error("pack: a task without an explicit scope is refused", lambda: route("POST", w1, ["source-packs"], "owner",
             {"userGoal": "Announce my Brahms recital", "locale": "en"}), 422, "library_pack_scope_required")
status, pack = route("POST", w1, ["source-packs"], "owner", task)
check("pack: created", status == 201 and pack["revision"] == 1 and pack["status"] == "draft", (status, pack.get("status")))
evidence = {e["assetRef"]["versionId"]: e for e in pack["evidenceRefs"]}
check("pack: approved evidence found by the real search", facts in evidence and evidence[facts]["selection"] == "recommended"
      and evidence[facts]["review"] == "approved", pack["evidenceRefs"])
check("pack: the selected diary is evidence pending review", evidence[diary]["review"] == "needs_review" and evidence[diary]["selection"] == "user")
check("pack: foreign workspace never searched", foreign not in evidence)
check("pack: style is the approved span only, apart from evidence", [s["sampleId"] for s in pack["styleRefs"]] == [sample["sampleId"]]
      and all(e["purpose"] == "evidence" for e in pack["evidenceRefs"]))
gap_codes = {g["code"] for g in pack["gaps"]}
check("pack: the approved date and venue close those gaps", not {"missing_fact_date", "missing_fact_venue"} & gap_codes, pack["gaps"])
check("pack: public use not approved is a warning, never cleared", any(w["code"] == "public_use_not_approved" for w in pack["rightsWarnings"])
      and "cleared" not in json.dumps(pack).lower())
with connection() as db:
    row = db.execute("SELECT revision,status,grant_revision,jsonb_array_length(evidence_refs),jsonb_array_length(style_refs) FROM public.pr_library_source_packs "
                     "WHERE workspace_id=%s AND id=%s", (w1, pack["packId"])).fetchone()
    used = db.execute("SELECT count(*) FROM public.pr_library_relations WHERE workspace_id=%s AND relation='used_in' AND to_kind='source_pack' AND to_key=%s",
                      (w1, pack["packId"])).fetchone()[0]
    events = db.execute("SELECT count(*) FROM public.pr_library_usage_events WHERE workspace_id=%s AND event_type='source_pack'", (w1,)).fetchone()[0]
check("pack: persisted at revision 1 with the grant snapshot", row[:2] == (1, "draft") and row[2] >= 1 and row[3] == len(pack["evidenceRefs"]) and row[4] == 1, row)
check("pack: used_in relations and usage events recorded", used >= 2 and events >= 2, (used, events))
status, read = route("GET", w1, ["source-packs", pack["packId"]], "viewer")
check("pack: readable with its return state and attachable", read["returnTo"] == back and read["validity"]["attachable"], read.get("validity"))

# --- attach to the real draft --------------------------------------------------------------------------------------------------
attach = envelope("source_pack.attach", [], {"packId": pack["packId"], "draftId": draft_id}, "attach-0000001", expected=1)
status, attached = route("POST", w1, ["actions"], "owner", attach)
check("attach: applied at pack revision 2", attached["status"] == "applied" and attached["revision"] == 2, attached)
result = attached["result"]
_, state = state_of(w1)
draft = next(v for v in state["variants"] if v["id"] == draft_id)
library_sources = draft["librarySources"]
check("attach: the draft carries refs, purposes, rationale, gaps, warnings and return state",
      {e["assetRef"]["versionId"] for e in library_sources["evidence"]} >= {diary, facts} and library_sources["style"][0]["sampleId"] == sample["sampleId"]
      and library_sources["rationale"] and library_sources["returnTo"] == back, library_sources)
diary_source = next(s for s in state["sources"] if (s.get("origin") or {}).get("kind") == "library" and s["origin"].get("assetId") == diary)
check("attach: the diary entered Ideas for fact review, nothing approved", not any(f["approved"] for f in diary_source["facts"])
      and diary_source["egressConsent"] == ["local"])
check("attach: the reviewed facts source is reused", fact_source["id"] in result["composer"]["sourceIds"])
check("attach: the voice sample goes to the voice context only", result["composer"]["voiceSourceIds"] == [sample["voiceSourceId"]]
      and sample["voiceSourceId"] not in result["composer"]["sourceIds"])
with connection() as db:
    rels = {r for r in db.execute("SELECT from_version,to_kind FROM public.pr_library_relations WHERE workspace_id=%s AND relation='used_in' AND to_key IN (%s,%s)",
                                  (w1, draft_id, diary_source["id"])).fetchall()}
    attached_events = db.execute("SELECT count(*) FROM public.pr_library_usage_events WHERE workspace_id=%s AND event_type='draft_attached' AND draft_id=%s",
                                 (w1, draft_id)).fetchone()[0]
check("attach: used_in relations to the draft and the imported idea", {(diary, "draft"), (facts, "draft"), (diary, "idea")} <= rels, rels)
check("attach: draft_attached usage recorded", attached_events >= 2, attached_events)
status, replay = route("POST", w1, ["actions"], "owner", attach)
check("attach: replayed key returns the receipt", replay.get("replayed") is True)
status, stale = route("POST", w1, ["actions"], "owner", envelope("source_pack.attach", [], {"packId": pack["packId"], "draftId": draft_id}, "attach-0000002",
                                                                 expected=1))
check("attach: a stale pack revision conflicts", stale["status"] == "conflict", stale)

# --- the draft is accepted: the deliverable comes home once -----------------------------------------------------------------
_, state = state_of(w1)
draft = next(v for v in state["variants"] if v["id"] == draft_id)
mutate(w1, "owner", "p2_variant_review", {"variantId": draft_id, "variantRevision": draft["revision"], "confirmed": True, "excludedUnknowns": draft["unknowns"]})
with connection() as db:
    registrations = db.execute("SELECT run_id,output_id,status,asset_key,replace(source_pack_id::text,'-',''),attempts FROM public.pr_library_artifacts "
                               "WHERE workspace_id=%s", (w1,)).fetchall()
check("artifact: registered once by the accepting command", len(registrations) == 1 and registrations[0][2] == "registered"
      and registrations[0][0] == quick["runId"] and registrations[0][4] == pack["packId"], registrations)
artifact_key = registrations[0][3]
with connection() as db, db.cursor() as cur:
    replayed = artifacts.store_text_deliverable(api.context(cur, OWNER, w1, service=service, now=clock[0]), quick["runId"], draft_id)
check("artifact: a replayed completion event returns the same asset", replayed["replayed"] and replayed["assetRef"]["assetId"] == artifact_key, replayed)
mutate(w1, "owner", "p2_variant_review", {"variantId": draft_id, "variantRevision": draft["revision"], "confirmed": True, "excludedUnknowns": []})
check("artifact: one Library row, one registration", scalar("SELECT count(*) FROM public.pr_library_assets WHERE workspace_id=%s AND source_kind='artifact'", (w1,)) == 1
      and scalar("SELECT count(*) FROM public.pr_library_artifacts WHERE workspace_id=%s", (w1,)) == 1)
service.library.process(connection, w1, artifact_key)
with connection() as db:
    stored = db.execute("SELECT processing_status,sha256,source_kind,provenance->>'runId' FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s",
                        (w1, artifact_key)).fetchone()
    lineage = {r[0] for r in db.execute("SELECT to_version FROM public.pr_library_relations WHERE workspace_id=%s AND relation='derived_from' AND from_version=%s",
                                        (w1, artifact_key)).fetchall()}
check("artifact: processed by the normal Library worker with the verified hash", stored[0] == "ready" and stored[1] == replayed["assetRef"]["sha256"]
      and stored[2] == "artifact" and stored[3] == quick["runId"], stored)
check("artifact: lineage to the source pack's evidence", {diary, facts} <= lineage, lineage)
with connection() as db, db.cursor() as cur:
    expect_error("artifact: the same output with other content (an ingested note's object) conflicts",
                 lambda: artifacts.register_final_artifact(api.context(cur, OWNER, w1, service=service), {
                     "runId": quick["runId"], "outputId": f"{draft_id}:r{draft['revision']}", "contentSha256": facts_ref["sha256"],
                     "storageRef": {"category": "file", "objectName": f"{facts}.txt"}, "mime": "text/plain", "displayTitle": "Copy",
                     "originalFilename": "copy.txt", "artifactRole": "final", "parentRefs": [], "idempotencyKey": "pg-creation-loop-0001"}),
                 409, "library_artifact_conflict")
with connection() as db, db.cursor() as cur:
    expect_error("artifact: a scratch log never registers", lambda: artifacts.register_final_artifact(api.context(cur, OWNER, w1, service=service), {
        "runId": quick["runId"], "outputId": f"{draft_id}:r{draft['revision']}", "contentSha256": "0" * 64,
        "storageRef": {"category": "file", "objectName": "1" * 32 + ".log"}, "mime": "text/plain", "displayTitle": "Run log",
        "originalFilename": "agent-run.log", "artifactRole": "final", "parentRefs": [], "idempotencyKey": "pg-creation-scratch-01"}), 422,
        "library_artifact_scratch")

# --- a narrowed permission blocks a second attach --------------------------------------------------------------------------------
status, second = route("POST", w1, ["source-packs"], "owner", {**task, "returnTo": None})
status, revoked = route("DELETE", w1, ["grants", voice_grant["grantId"]], "owner", {})
check("grant revoke: the voice span is withdrawn", revoked["propagation"]["voiceSpansWithdrawn"] == 1, revoked)
before = state_of(w1)[1]
status, blocked = route("POST", w1, ["actions"], "owner", envelope("source_pack.attach", [], {"packId": second["packId"], "draftId": draft_id}, "attach-0000003",
                                                                   expected=1))
check("changed grant: attach blocked with what changed", blocked["status"] == "conflict"
      and any(ch["purpose"] == "style" and ch["change"] in ("permission_narrowed", "voice_example_withdrawn") for ch in blocked["result"]["changes"]), blocked)
check("changed grant: nothing written to the draft", next(v for v in state_of(w1)[1]["variants"] if v["id"] == draft_id)["librarySources"]["packId"] == pack["packId"]
      and state_of(w1)[1]["sources"] == before["sources"])

# --- isolation ---------------------------------------------------------------------------------------------------------------------
expect_error("isolation: another workspace cannot read this pack", lambda: route("GET", w1, ["source-packs", pack["packId"]], "other"), 403)
expect_error("isolation: the pack id is unknown in another workspace", lambda: route("GET", w2, ["source-packs", pack["packId"]], "other"), 404)
status, foreign_attach = route("POST", w2, ["actions"], "other", envelope("source_pack.attach", [], {"packId": pack["packId"], "draftId": draft_id},
                                                                         "foreign-attach-1", expected=2))
check("isolation: attaching another workspace's pack is denied", foreign_attach["status"] in ("denied", "conflict") and draft_id not in json.dumps(foreign_attach.get("result") or {}),
      foreign_attach)
status, cross = route("POST", w1, ["actions"], "owner", envelope("source_pack.create", [foreign_ref], {
    "taskContext": {"userGoal": "x", "scope": {"kind": "workspace"}}, "evidence": [{"assetRef": foreign_ref}]}, "foreign-create-1"))
check("isolation: another workspace's item can't enter a pack", cross["status"] == "denied" and foreign not in json.dumps(cross), cross)
for table in ("pr_library_source_packs", "pr_library_artifacts"):
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (OWNER,))
        try:
            db.execute(f"SELECT * FROM public.{table}")
        except psycopg.errors.InsufficientPrivilege:
            db.rollback()
            checks.append(f"rls: authenticated role cannot read {table}")
        else:
            raise AssertionError("browser role could read " + table)

print(json.dumps({"status": "pass", "phase": PHASE, "execution": "disposable-local-postgres", "checks": checks}, indent=2, ensure_ascii=False))
