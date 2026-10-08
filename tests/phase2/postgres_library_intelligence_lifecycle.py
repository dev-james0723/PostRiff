"""T12 against disposable PostgreSQL: deletion cascade, sibling duplicates, revocation narrowing, in-flight revocation,
cost records and status, resumable backfill, index generations and flag rollback (A008, A009, A041/A072, A071, A073, A074).

Runs twice in cloud CI (LIBRARY_PG_PHASE=no_vector, then vector); nothing here reads or writes the pgvector column.
Users are fresh synthetic UUIDs (rls.sql marks …0002 deleted). Fake private storage; synthetic processors; the budget
seam is patched only where a successful reservation is needed (the real Ledger refuses unapproved budgets). No provider or
network calls. The deletion step runs exactly the call sequence requested for library_assets.delete: mark deleting,
lifecycle.on_source_deleted in the same transaction, delete only receipt['sibling']['objectToDelete'], then forget the row.
"""
import hashlib
import json
import os
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

for _flag in ("ENRICHMENT", "RETRIEVAL"):
    os.environ[f"RAFII_LIBRARY_{_flag}_ENABLED"] = "1"
for _name in ("POSTRIFF_BUDGET_POLICY", "RAFII_AI_UNLIMITED_USER_IDS", "POSTRIFF_AI_PAUSED", "RAFII_LIBRARY_BACKFILL_PAUSED"):
    os.environ.pop(_name, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_storage import PrivateAssetService  # noqa: E402
from postriff_phase2.library_intelligence import api, capabilities, jobs, lifecycle, policy, search, segments, telemetry, versions  # noqa: E402
from postriff_phase2.library_intelligence import providers as providers_module  # noqa: E402
from postriff_phase2.library_intelligence.http import write_context  # noqa: E402
from postriff_phase2.library_intelligence import media, ocr, understanding  # noqa: E402,F401  (self-registering; imported before the registry is cleared)

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
PHASE = os.environ.get("LIBRARY_PG_PHASE", "no_vector")
OWNER = "7e12c0de-0000-4000-8000-000000000a01"
OTHER = "7e12c0de-0000-4000-8000-000000000a02"
VIEWER = "7e12c0de-0000-4000-8000-000000000a03"
TOKENS = {"owner": OWNER, "other": OTHER, "viewer": VIEWER}
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

    def put(self, ws, name, raw, mime):
        self.objects[(ws, "file", name)] = (raw, mime, hashlib.sha256(raw).hexdigest()[:24])

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
        if (ws, category, name) not in self.objects:
            raise AlphaError("missing", 404)
        return f"https://download.invalid/{ws}/{name}?token=fake"

    def delete(self, ws, category, name):
        self.objects.pop((ws, category, name), None)

    def list_prefix(self, prefix, bucket=None):
        ws, category = prefix.split("/", 1)
        return [f"{ws}/{category}/{name}" for (owner, cat, name) in self.objects if owner == ws and cat == category]


@contextmanager
def ctx(principal=OWNER, workspace=None):
    with connection() as db, db.cursor() as cur:
        yield api.context(cur, principal, workspace or w1, service=service, now=clock[0])


def upload(ws, token, name, raw, mime="text/markdown"):
    ticket = library.begin(ws, token, {"filename": name, "mime": mime, "bytes": len(raw)})["upload"]
    storage.put(ws, ticket["assetId"] + "." + name.rsplit(".", 1)[-1], raw, mime)
    committed = library.commit(ws, token, ticket["assetId"])
    if committed["status"] == "queued":
        library.process(connection, ws, ticket["assetId"])
    return ticket["assetId"]


def row_of(key):
    with connection() as db:
        return db.execute("SELECT processing_status,object_name,replace(duplicate_of::text,'-',''),etag,bytes,mime FROM public.pr_library_assets WHERE id=%s",
                          (uuid.UUID(hex=key),)).fetchone()


def register(capability, version, *, location="local", category="extract", kinds=("document",), run=None, estimate=None):
    calls = []

    def runner(job):
        calls.append(job.attempt)
        return run(job) if run else {"state": "ready"}
    capabilities.register({"capability": capability, "version": version, "location": location, "category": category,
                           "applies": lambda v, kinds=kinds: v["kind"] in kinds, "run": runner, "estimate": estimate})
    return calls


def grant(ws, token, body):
    with write_context(service, token, ws) as wctx:
        return policy.grant(wctx, body)


def revoke(ws, token, grant_id):
    with write_context(service, token, ws) as wctx:
        return policy.revoke(wctx, grant_id)


def seed_embedding(ws, asset_key, version_key, modality, model, dims=8, generation=1):
    with connection() as db:
        db.execute("INSERT INTO public.pr_library_embeddings(id,workspace_id,asset_key,version_key,modality,model_id,dims,index_generation,consent_revision) "
                   "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,0)", (uuid.uuid4(), ws, asset_key, version_key, modality, model, dims, generation))


def set_capability(ws, key, capability, state):
    with connection() as db, db.cursor() as cur:
        capabilities.set_state(cur, ws, key, capability, state)


def cap_state(ws, key, capability):
    return scalar("SELECT state FROM public.pr_library_capabilities WHERE workspace_id=%s AND asset_key=%s AND capability=%s", (ws, key, capability))


# --- setup --------------------------------------------------------------------------------------------------------------
with connection() as db:
    has_vector = bool(db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_library_embeddings' "
                                 "AND column_name='embedding'").fetchone())
    for user in TOKENS.values():
        db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (user,))
storage = Storage()
service = HostedWorkspaceService(connection, verify, assets=PrivateAssetService(storage), clock=lambda: clock[0])
library, intel = service.library, service.library_intelligence
w1 = service.bootstrap("owner", "studio")["workspaceId"]
w2 = service.bootstrap("other", "studio")["workspaceId"]
service.bootstrap("viewer", "studio")
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active') ON CONFLICT(workspace_id,user_id) "
               "DO UPDATE SET role='viewer',status='active'", (w1, VIEWER))
capabilities._loaded = True
capabilities.PROCESSORS.clear()
extract_calls = register("extract", "pg-lc-extract-1")
register("embed_visual", "pg-lc-visual-1", category="embedding", kinds=("image",))

# --- A072/A041: deletion cascade and sibling duplicates -------------------------------------------------------------------
raw = b"Brahms intermezzo notes for the lifecycle suite.\nVoicing in bar 12."
a = upload(w1, "owner", "notes.md", raw)
b = upload(w1, "owner", "notes-copy.md", raw)
c3 = upload(w1, "owner", "notes-third.md", raw)
a_object = row_of(a)[1]
check("dup: later identical uploads reference the original", row_of(b)[0] == "duplicate" and row_of(b)[2] == a and row_of(c3)[2] == a, (row_of(b), row_of(c3)))
other = upload(w1, "owner", "other.md", b"A different file that stays.")
sha = hashlib.sha256(raw).hexdigest()
ref = {"assetRef": {"assetId": a, "versionId": a, "sha256": sha}}
cid = next(x["id"] for x in library.collections(w1, "owner", {"name": "Lifecycle"})["collections"] if x["name"] == "Lifecycle")
library.metadata(w1, "owner", a, {"collections": [cid]})
library.metadata(w1, "owner", other, {"collections": [cid]})
with connection() as db:
    for n, text in enumerate(("Brahms passage one", "Brahms passage two")):
        db.execute("INSERT INTO public.pr_library_segments(id,workspace_id,asset_key,version_key,ordinal,kind,text,extractor,extractor_version,text_hash,origin) "
                   "VALUES(%s,%s,%s,%s,%s,'text',%s,'pg','1',%s,'extracted')", (uuid.uuid4(), w1, a, a, n, text, hashlib.sha256(text.encode()).hexdigest()))
    db.execute("INSERT INTO public.pr_library_annotations(id,workspace_id,asset_key,version_key,field,value,origin) VALUES(%s,%s,%s,%s,'topic','\"Brahms\"'::jsonb,'ai_suggested')",
               (uuid.uuid4(), w1, a, a))
    db.execute("INSERT INTO public.pr_library_relations(id,workspace_id,from_key,from_version,to_kind,to_key,relation,status,origin) "
               "VALUES(%s,%s,%s,%s,'draft','draft-1','used_in','active','system')", (uuid.uuid4(), w1, a, a))
    db.execute("INSERT INTO public.pr_library_relations(id,workspace_id,from_key,from_version,to_kind,to_key,to_version,relation,status,origin) "
               "VALUES(%s,%s,%s,%s,'asset',%s,%s,'similar_to','suggested','ai_suggested')", (uuid.uuid4(), w1, a, a, other, other))
    db.execute("INSERT INTO public.pr_library_source_packs(id,workspace_id,task_context,evidence_refs,grant_revision,status,created_by) "
               "VALUES(%s,%s,'{}'::jsonb,%s::jsonb,0,'attached',%s)", (uuid.uuid4(), w1, json.dumps([ref]), OWNER))
    db.execute("INSERT INTO public.pr_library_suggestions(id,workspace_id,recipient,dedup_key,category,candidate_refs,reason,consent_revision) "
               "VALUES(%s,%s,%s,'pg-lifecycle-1','unused_relevant',%s::jsonb,'Matches the draft topic.',0)", (uuid.uuid4(), w1, OWNER, json.dumps([ref])))
    db.execute("INSERT INTO public.pr_library_collection_overrides(workspace_id,collection_id,asset_key,mode,created_by) VALUES(%s,%s,%s,'exclude',%s)",
               (w1, uuid.UUID(hex=cid), a, OWNER))
    db.execute("INSERT INTO public.pr_library_usage_events(id,workspace_id,asset_key,version_key,segment_id,event_type,dedup_key,source) "
               "VALUES(%s,%s,%s,%s,%s,'source_pack','pg-usage-lifecycle-1','{\"title\":\"Spring recital notes\"}'::jsonb)", (uuid.uuid4(), w1, a, a, uuid.uuid4()))
    db.execute("INSERT INTO public.pr_library_voice_samples(id,workspace_id,asset_key,version_key,source_sha256,locator,text,text_hash,persona_id,language,"
               "polarity,attestation,consent_revision,created_by) VALUES(%s,%s,%s,%s,%s,'{\"kind\":\"text\",\"start\":0,\"end\":10}'::jsonb,'Brahms pas',%s,"
               "'default','en','positive','{\"authoredByMe\":true}'::jsonb,0,%s)", (uuid.uuid4(), w1, a, a, sha, hashlib.sha256(b"x").hexdigest(), OWNER))
    db.execute("UPDATE public.pr_library_assets SET media='{\"peaks\":[0.1,0.9],\"peaksSource\":\"server_decoded\",\"durationMs\":1200}'::jsonb WHERE id=%s",
               (uuid.UUID(hex=a),))
seed_embedding(w1, a, a, "text", "openai/text-embedding-3-large", 1024)
seed_embedding(w1, a, a, "visual", "local/visual-perceptual-v1", 256)
set_capability(w1, a, "preview", "ready")
check("seed: the hook queued the local job for the original", scalar("SELECT count(*) FROM public.pr_library_jobs WHERE workspace_id=%s AND asset_key=%s AND status='queued'", (w1, a)) == 1)

# The requested library_assets.delete sequence.
with service.repository.transaction("owner", w1) as (cur, _row, principal):
    cur.execute("UPDATE public.pr_library_assets SET processing_status='deleting',lease_token=null,lease_expires_at=null,updated_at=now() WHERE workspace_id=%s AND id=%s",
                (w1, uuid.UUID(hex=a)))
    receipt = lifecycle.on_source_deleted(cur, w1, a, actor=principal, service=service)
storage.delete(w1, "file", receipt["sibling"]["objectToDelete"])
with service.repository.transaction("owner", w1) as (cur, _row, _p):
    library._forget(cur, w1, a)

for table, column in (("pr_library_segments", "version_key"), ("pr_library_annotations", "version_key"), ("pr_library_embeddings", "version_key"),
                      ("pr_library_capabilities", "asset_key"), ("pr_library_collection_items", "asset_key"), ("pr_library_collection_overrides", "asset_key")):
    check(f"delete: {table} has nothing for the deleted version", scalar(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s AND {column}=%s", (w1, a)) == 0)
check("delete: queued job cancelled", scalar("SELECT status FROM public.pr_library_jobs WHERE workspace_id=%s AND asset_key=%s", (w1, a)) == "cancelled")
check("delete: similar_to suggestion removed, used_in kept as stale", scalar("SELECT string_agg(relation||':'||status,',' ORDER BY relation) FROM public.pr_library_relations "
                                                                           "WHERE workspace_id=%s AND from_version=%s", (w1, a)) == "used_in:stale")
pack = scalar("SELECT jsonb_build_array(status,evidence_refs,rights_warnings) FROM public.pr_library_source_packs WHERE workspace_id=%s", (w1,))
check("delete: pack revoked with a warning, refs untouched", pack[0] == "revoked" and pack[1] == [ref] and pack[2] == [{"code": "source_deleted", "versionId": a}], pack)
check("delete: suggestion suppressed", scalar("SELECT state FROM public.pr_library_suggestions WHERE workspace_id=%s", (w1,)) == "suppressed")
usage = scalar("SELECT jsonb_build_array(segment_id,source) FROM public.pr_library_usage_events WHERE workspace_id=%s", (w1,))
check("delete: usage kept but anonymized", usage == [None, {"sourceDeleted": True}], usage)
voice_row = scalar("SELECT jsonb_build_array(status,text) FROM public.pr_library_voice_samples WHERE workspace_id=%s", (w1,))
check("delete: voice span withdrawn through the voice module", voice_row == ["revoked", "(withdrawn)"] and receipt["voiceSpansWithdrawn"] == 1, voice_row)
check("delete: other collection member kept", scalar("SELECT count(*) FROM public.pr_library_collection_items WHERE workspace_id=%s AND asset_key=%s", (w1, other)) == 1)
check("delete: receipt names the residual signed-link window", "300 seconds" in receipt["residual"])
metric = scalar("SELECT dims FROM public.pr_library_metrics WHERE workspace_id=%s AND feature='library.lifecycle' AND event='deleted' ORDER BY id DESC LIMIT 1", (w1,))
check("delete: content-free metric recorded", metric and "Brahms" not in json.dumps(metric) and metric.get("segmentsDeleted") == 2, metric)
sibling = receipt["sibling"]
check("sibling: oldest duplicate promoted", sibling["promoted"] == b and sibling["originalKept"], sibling)
check("sibling: original bytes kept, redundant copy deleted", (w1, "file", a_object) in storage.objects and row_of(b)[1] == a_object and
      (w1, "file", sibling["objectToDelete"]) not in storage.objects, (row_of(b), sibling))
check("sibling: other duplicates point at the new canonical copy", row_of(c3)[2] == b, row_of(c3))
library.sweep(connection)
check("sibling: promoted copy processed by the existing worker", row_of(b)[0] == "ready", row_of(b))
check("sibling: promoted copy downloads", library.url(w1, "owner", b, True)["url"].startswith("https://download.invalid/"))

# --- #10 narrowing, #5 collection members are version keys ----------------------------------------------------------------
p1 = upload(w1, "owner", "p1.md", b"Narrowing case one.")
p2 = upload(w1, "owner", "p2.md", b"Narrowing case two.")
workspace_grant = grant(w1, "owner", {"grantType": "processing", "scope": {"kind": "workspace"}, "location": "cloud", "category": "embedding"})
grant(w1, "owner", {"grantType": "processing", "scope": {"kind": "asset", "assetId": p2}, "location": "cloud", "category": "embedding"})
for key in (p1, p2):
    seed_embedding(w1, key, key, "text", "openai/text-embedding-3-large", 1024)
    set_capability(w1, key, "embed_text", "ready")
narrowed = revoke(w1, "owner", workspace_grant["grantId"])["propagation"]
check("#10: revoked item loses its cloud vectors and ready state", cap_state(w1, p1, "embed_text") == "blocked_permission" and
      scalar("SELECT status FROM public.pr_library_embeddings WHERE workspace_id=%s AND version_key=%s", (w1, p1)) == "revoked", narrowed)
check("#10: item still covered by its own grant keeps both", cap_state(w1, p2, "embed_text") == "ready" and
      scalar("SELECT status FROM public.pr_library_embeddings WHERE workspace_id=%s AND version_key=%s", (w1, p2)) == "active" and narrowed["stillCovered"] >= 1, narrowed)
q1 = upload(w1, "owner", "q1.md", b"Lineage root.")
q2 = upload(w1, "owner", "q2.md", b"Lineage second version.")
with connection() as db:
    db.execute("UPDATE public.pr_library_assets SET lineage_id=%s,version_no=2 WHERE id=%s", (uuid.UUID(hex=q1), uuid.UUID(hex=q2)))
qcid = next(x["id"] for x in library.collections(w1, "owner", {"name": "Second versions"})["collections"] if x["name"] == "Second versions")
library.metadata(w1, "owner", q2, {"collections": [qcid]})
collection_grant = grant(w1, "owner", {"grantType": "processing", "scope": {"kind": "collection", "collectionId": qcid}, "location": "cloud", "category": "embedding"})
seed_embedding(w1, q1, q1, "text", "openai/text-embedding-3-large", 1024)
seed_embedding(w1, q1, q2, "text", "openai/text-embedding-3-large", 1024)  # embeddings carry the lineage in asset_key
revoke(w1, "owner", collection_grant["grantId"])
check("#5: the collection member's vector is revoked by its version key", scalar("SELECT status FROM public.pr_library_embeddings WHERE workspace_id=%s AND version_key=%s",
                                                                                 (w1, q2)) == "revoked")
check("#5: the lineage root outside the collection keeps its vector", scalar("SELECT status FROM public.pr_library_embeddings WHERE workspace_id=%s AND version_key=%s",
                                                                             (w1, q1)) == "active")

# --- A008: a revocation between claim and provider call; JobContext.recheck --------------------------------------------
e1 = upload(w1, "owner", "e1.md", b"In-flight revocation case.")
cloud_grant = grant(w1, "owner", {"grantType": "processing", "scope": {"kind": "asset", "assetId": e1}, "location": "cloud", "category": "embedding"})
rechecks, settled_ids = [], []


def revoke_between_calls(job):
    rechecks.append(job.recheck())
    revoke(w1, "owner", cloud_grant["grantId"])  # commits while the job holds no transaction and no lock
    rechecks.append(job.recheck())
    if not rechecks[-1]:
        return {"state": "blocked_permission", "errorCode": "library_grant_revoked", "charged": False}
    return {"state": "ready", "media": {"textLength": 1}}


register("embed_text", "pg-lc-cloud-1", location="cloud", category="embedding", run=revoke_between_calls, estimate=lambda job: 10)
real_reserve, real_settle = providers_module.reserve, providers_module.settle
providers_module.reserve = lambda cur, ws, member, **kw: {"status": "reserved", "reservationId": str(uuid.uuid4()), "duplicate": False}
providers_module.settle = lambda cur, ws, reservation, result, failed=False: settled_ids.append(reservation["reservationId"]) or {"state": "released"}
try:
    with write_context(service, "owner", w1) as wctx:
        version = versions.get(wctx, e1)
        jobs.enqueue_capability(wctx, versions.ref(version), "embed_text", "pg-lc-cloud-1", requested_by=OWNER)
    intel.tick(connection, max_jobs=10, max_seconds=60)
finally:
    providers_module.reserve, providers_module.settle = real_reserve, real_settle
check("A008: recheck allowed before the revoke, refused after it", rechecks == [True, False], rechecks)
check("A008: nothing written, capability blocked", cap_state(w1, e1, "embed_text") == "blocked_permission" and
      scalar("SELECT media ? 'textLength' FROM public.pr_library_assets WHERE id=%s", (uuid.UUID(hex=e1),)) is False)
check("A008: the reservation is settled once", len(settled_ids) == 1, settled_ids)

# --- A009: a cached search page from before a revocation is refused --------------------------------------------------------
for name in ("s1.md", "s2.md", "s3.md"):
    key = upload(w1, "owner", name, f"stalecursor marker in {name}".encode())
    with ctx() as c1:
        version = versions.get(c1, key)
        text = f"stalecursor marker in {name}"
        segments.write_segments(c1.cur, w1, version, [{"kind": "text", "text": text, "language": "en", "locator": {"kind": "text", "start": 0, "end": len(text)}}],
                                extractor="pg-lifecycle", extractor_version="1")
with ctx() as c1:
    page = search.search_library(c1, {"query": "stalecursor", "limit": 1, "modes": ["lexical"]})
check("A009: a first page with a cursor", page["hits"] and page["nextCursor"], {k: page.get(k) for k in ("nextCursor", "coverage")})
gid = grant(w1, "owner", {"grantType": "processing", "scope": {"kind": "workspace"}, "location": "cloud", "category": "llm"})["grantId"]
revoke(w1, "owner", gid)
try:
    with ctx() as c1:
        search.search_library(c1, {"query": "stalecursor", "limit": 1, "modes": ["lexical"], "cursor": page["nextCursor"]})
    check("A009: stale cursor refused after the revocation", False)
except AlphaError as error:
    check("A009: stale cursor refused after the revocation", error.status == 409 and error.code == "library_cursor_stale", (error.status, error.code))

# --- A071/A073: cost per attempt and the status view -----------------------------------------------------------------------
j1 = upload(w1, "owner", "j1.md", b"Cost case.")
grant(w1, "owner", {"grantType": "processing", "scope": {"kind": "asset", "assetId": j1}, "location": "cloud", "category": "llm"})
register("understand", "pg-lc-cost-1", location="cloud", category="llm", estimate=lambda job: 1000,
         run=lambda job: {"state": "ready", "provider": {"provider": "synthetic", "model": "m", "cost": {"kind": "actual", "usdMicro": 777}}})
providers_module.reserve = lambda cur, ws, member, **kw: {"status": "reserved", "reservationId": str(uuid.uuid4()), "duplicate": False}
providers_module.settle = lambda cur, ws, reservation, result, failed=False: {"state": "actual"}
try:
    with write_context(service, "owner", w1) as wctx:
        jobs.enqueue_capability(wctx, versions.ref(versions.get(wctx, j1)), "understand", "pg-lc-cost-1", requested_by=OWNER)
    intel.tick(connection, max_jobs=10, max_seconds=60)
finally:
    providers_module.reserve, providers_module.settle = real_reserve, real_settle
cost = scalar("SELECT cost FROM public.pr_library_jobs WHERE workspace_id=%s AND capability='understand'", (w1,))
check("cost: one entry per attempt, kind kept", cost == {"byAttempt": {"1": {"kind": "actual", "usdMicro": 777}}}, cost)
with ctx() as c1:
    owner_status = telemetry.status_http(c1, {"params": {}, "query": {}, "body": {}})
with ctx(VIEWER) as c1:
    viewer_status = telemetry.status_http(c1, {"params": {}, "query": {}, "body": {}})
check("status: owner sees costs by kind", owner_status["costs"]["actualUsdMicro"] == 777 and owner_status["costs"]["unknownCount"] == 0, owner_status["costs"])
check("status: viewer sees no cost data", viewer_status["costs"] is None and viewer_status["costsVisible"] is False)
check("status: queue, coverage and providers present", set(owner_status["queue"]) >= {"queued", "processing", "failed", "oldestQueuedSeconds"}
      and owner_status["coverage"]["accessible"] >= 1 and set(owner_status["providers"]) == {"embedding", "asr", "vision", "llm"}, owner_status)
with connection() as db:
    dims = [r[0] for r in db.execute("SELECT dims FROM public.pr_library_metrics WHERE workspace_id=%s", (w1,)).fetchall()]
    events = {r[0] for r in db.execute("SELECT feature||':'||event FROM public.pr_library_metrics WHERE workspace_id=%s", (w1,)).fetchall()}
check("metrics: job outcome, queue age and cost recorded", {"library.jobs:outcome", "library.jobs:queue_age_seconds", "library.jobs:cost"} <= events, events)
check("metrics: no content in any dims", not any(word in json.dumps(dims) for word in ("Brahms", "stalecursor", "Narrowing", "Lineage", "notes.md")), dims[:5])

# --- A074: resumable backfill, pause, generations (isolated workspace w2) -------------------------------------------------
os.environ["RAFII_LIBRARY_ENRICHMENT_ENABLED"] = ""
olds = [upload(w2, "other", f"old-{n}.md", f"Pre-existing item {n}".encode()) for n in range(3)]
check("backfill: pre-existing items have no jobs", scalar("SELECT count(*) FROM public.pr_library_jobs WHERE workspace_id=%s", (w2,)) == 0)
legacy = uuid.uuid4().hex
with connection() as db:
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (w2,)).fetchone()[0]
    state.setdefault("phase2", {}).setdefault("assets", []).append({"id": legacy, "mime": "image/jpeg", "hash": "f" * 64, "objectName": f"{legacy}-{'f' * 64}.jpg",
                                                                    "bytes": 10, "createdAt": 1.0, "deleted": False})
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), w2))
os.environ["RAFII_LIBRARY_ENRICHMENT_ENABLED"] = "1"
dry = lifecycle.backfill(intel, connection, workspace_id=w2, limit=50, dry_run=True)
check("backfill: dry run counts only", dry["status"] == "dry_run" and dry["candidates"] == 4 and dry["byCapability"] == {"extract": 3, "embed_visual": 1}
      and scalar("SELECT count(*) FROM public.pr_library_jobs WHERE workspace_id=%s", (w2,)) == 0, dry)
check("backfill: cloud never enqueued", dry["cloudSkipped"] >= 3, dry)
first = lifecycle.backfill(intel, connection, workspace_id=w2, limit=1, dry_run=False)
second = lifecycle.backfill(intel, connection, workspace_id=w2, limit=1, dry_run=False)
check("backfill: resumes from the persisted checkpoint", first["status"] == second["status"] == "partial" and first["enqueued"] == second["enqueued"] == 1
      and first["cursor"]["id"] != second["cursor"]["id"], (first, second))
rest = lifecycle.backfill(intel, connection, workspace_id=w2, limit=50, dry_run=False)
check("backfill: completes the remaining items", rest["status"] == "complete" and rest["enqueued"] == 2 and
      scalar("SELECT count(*) FROM public.pr_library_jobs WHERE workspace_id=%s", (w2,)) == 4, rest)
again = lifecycle.backfill(intel, connection, workspace_id=w2, limit=50, dry_run=False)
check("backfill: a finished pass does nothing", again["status"] == "complete" and again["scanned"] == 0, again)
os.environ["RAFII_LIBRARY_BACKFILL_PAUSED"] = "1"
check("backfill: pause switch", lifecycle.backfill(intel, connection, workspace_id=w2, restart=True, dry_run=False)["status"] == "paused")
os.environ.pop("RAFII_LIBRARY_BACKFILL_PAUSED")
seed_embedding(w2, olds[0], olds[0], "text", "model-a", 8, 1)
with ctx(OTHER, w2) as c2:
    bumped = lifecycle.bump_index_generation(c2, reason="model_change")
with ctx(OTHER, w2) as c2:
    rolled = lifecycle.rollback_index_generation(c2, 1)
with ctx(OTHER, w2) as c2:
    active = policy.revisions(c2, fresh=True)["indexGeneration"]
check("generations: bump then roll back; search reads the active one", bumped["indexGeneration"] == 2 and rolled["indexGeneration"] == 1 and active == 1
      and rolled["activeVectorsInGeneration"] == 1, (bumped, rolled))

# --- A074: flag rollback preserves originals and the old list/search ------------------------------------------------------
saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("RAFII_LIBRARY_")}
try:
    check("rollback: every Library intelligence flag is off", not any(policy.flag_state().values()))
    kept = upload(w2, "other", "rollback.md", b"rollbackmarker original")
    check("rollback: upload processes", row_of(kept)[0] == "ready")
    check("rollback: old list/search finds it", [x["id"] for x in library.list(w2, "other", "rollbackmarker")["assets"]] == [kept])
    check("rollback: original downloads", library.url(w2, "other", kept, True)["url"].startswith("https://download.invalid/"))
    check("rollback: worker idles", intel.tick(connection)["jobs"]["status"] == "disabled")
    check("rollback: backfill idles", lifecycle.backfill(intel, connection, workspace_id=w2, dry_run=False)["status"] == "disabled")
    try:
        with ctx(OTHER, w2) as c2:
            search.search_library(c2, {"query": "rollbackmarker"})
        check("rollback: new retrieval says it is off", False)
    except AlphaError as error:
        check("rollback: new retrieval says it is off", error.status == 503 and error.code == "library_retrieval_disabled", error.code)
    with ctx(OTHER, w2) as c2:
        check("rollback: status still answers", telemetry.status_http(c2, {"params": {}, "query": {}, "body": {}})["flags"]["enrichment"] is False)
finally:
    os.environ.update(saved)

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "phase": {"requested": PHASE, "embeddingColumn": has_vector},
                  "checks": checks}, indent=2))
