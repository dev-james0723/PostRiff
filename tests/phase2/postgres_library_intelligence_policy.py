"""T01 against disposable PostgreSQL: migration 097, grants, revisions, TOCTOU recheck, isolation and RLS.

Runs twice in cloud CI (LIBRARY_PG_PHASE=no_vector, then vector). Fake private storage; no provider or network calls.
"""
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_storage import PrivateAssetService  # noqa: E402
from postriff_phase2.library_intelligence import api, contracts as c, policy, versions  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
PHASE = os.environ.get("LIBRARY_PG_PHASE", "no_vector")
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000066"  # rls.sql marks …0002 deleted
EDITOR = "00000000-0000-0000-0000-000000000044"
VIEWER = "00000000-0000-0000-0000-000000000055"
TOKENS = {"one": ONE, "two": TWO, "editor": EDITOR, "viewer": VIEWER}
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


class Storage:
    file_bucket = "postriff-library"

    def __init__(self):
        self.objects = {}

    def signed_upload_url(self, ws, category, name):
        return f"https://upload.invalid/{ws}/{name}?token=fake"

    def put(self, ws, name, raw, mime):
        import hashlib
        self.objects[(ws, name)] = (raw, mime, hashlib.sha256(raw).hexdigest()[:24])

    def object_info(self, ws, category, name):
        raw, mime, etag = self.objects[(ws, name)]
        return {"bytes": len(raw), "mime": mime, "etag": etag}

    def get_bounded(self, ws, category, name, limit):
        return self.objects[(ws, name)][0]

    def signed_url(self, ws, category, name, expires_in=300):
        return f"https://download.invalid/{ws}/{name}?token=fake"

    def delete(self, ws, category, name):
        self.objects.pop((ws, name), None)

    def list_prefix(self, prefix, bucket=None):
        return []


def upload(service, storage, ws, token, name, raw, mime="text/markdown"):
    ticket = service.library.begin(ws, token, {"filename": name, "mime": mime, "bytes": len(raw)})["upload"]
    storage.put(ws, ticket["assetId"] + "." + name.rsplit(".", 1)[1], raw, mime)
    service.library.commit(ws, token, ticket["assetId"])
    return ticket["assetId"]


def route(service, method, ws, rest, token, body=None):
    return service.library_intelligence.route(method, ws, rest, {}, lambda: body or {}, token)


# --- schema ------------------------------------------------------------------------------------------------------------
NEW_TABLES = ["pr_library_policy", "pr_library_grants", "pr_library_capabilities", "pr_library_jobs", "pr_library_segments",
              "pr_library_annotations", "pr_library_embeddings", "pr_library_collection_overrides", "pr_library_collection_revisions",
              "pr_library_relations", "pr_library_voice_samples", "pr_library_source_packs", "pr_library_artifacts",
              "pr_library_suggestions", "pr_library_suggestion_prefs", "pr_library_usage_events", "pr_library_action_receipts", "pr_library_metrics"]
with connection() as db:
    for table in NEW_TABLES:
        row = db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (f"public.{table}",)).fetchone()
        check(f"schema: {table} forced RLS", row and all(row), row)
    has_vector = bool(db.execute("SELECT 1 FROM information_schema.columns WHERE table_name='pr_library_embeddings' AND column_name='embedding'").fetchone())
    available = bool(db.execute("SELECT 1 FROM pg_available_extensions WHERE name='vector'").fetchone())
    check("schema: vector column exists exactly when pgvector is available", has_vector == available, (has_vector, available, PHASE))
    if PHASE == "vector":
        check("schema: vector phase really has pgvector", has_vector)
        indexes = {r[0] for r in db.execute("SELECT indexname FROM pg_indexes WHERE tablename='pr_library_embeddings'").fetchall()}
        check("schema: HNSW text and visual indexes", {"pr_library_embeddings_text_1024", "pr_library_embeddings_visual_256"} <= indexes, indexes)
    else:
        check("schema: no_vector phase degrades without the column", not has_vector or available)
    # Existing rows keep working with additive columns and defaults.
    cols = {r[0] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_name='pr_library_assets'").fetchall()}
    check("schema: version columns added", {"lineage_id", "version_no", "source_kind", "media"} <= cols, cols)
    for user in (TWO, EDITOR, VIEWER):
        db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (user,))

storage = Storage()
service = HostedWorkspaceService(connection, verify, assets=PrivateAssetService(storage), clock=lambda: clock[0])
w1 = service.bootstrap("one", "studio")["workspaceId"]
w2 = service.bootstrap("two", "studio")["workspaceId"]
service.bootstrap("editor", "studio")  # creates the member's profile the same way sign-up does
service.bootstrap("viewer", "studio")
with connection() as db:
    for user, role in ((EDITOR, "editor"), (VIEWER, "viewer")):
        db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,%s,'active') ON CONFLICT(workspace_id,user_id) DO UPDATE SET role=excluded.role,status='active'", (w1, user, role))

a1 = upload(service, storage, w1, "one", "recital-notes.md", "Brahms Op.118 演奏會 on 12 October".encode())
a2 = upload(service, storage, w1, "one", "budget.md", b"Hall hire 1200 HKD")
b1 = upload(service, storage, w2, "two", "other-tenant.md", b"Private to workspace two")

# --- isolation ---------------------------------------------------------------------------------------------------------
with connection() as db, db.cursor() as cur:
    ctx = api.context(cur, ONE, w1)
    check("isolation: own versions load", set(versions.load(ctx, [a1, a2])) == {a1, a2})
    check("isolation: foreign key absent from load", versions.load(ctx, [b1]) == {})
    foreign = expect_error("isolation: foreign get is 404", lambda: versions.get(ctx, b1), 404, "library_unavailable")
    missing = expect_error("isolation: missing get is 404", lambda: versions.get(ctx, uuid.uuid4().hex), 404, "library_unavailable")
    check("isolation: foreign and missing are indistinguishable", str(foreign) == str(missing))
    keys = versions.accessible_keys(ctx)
    check("isolation: accessible set excludes the other workspace", b1 not in keys and {a1, a2} <= set(keys), keys)
    outcome = api.apply_action(cur, ONE, w1, {"actionId": "a1", "uiInstanceId": "ui1", "actionType": "metadata.update",
                                              "targetRefs": [{"assetId": b1, "versionId": b1, "sha256": ""}],
                                              "idempotencyKey": "isolation-key-000001", "payload": {"title": "x"}})
    check("isolation: forged cross-workspace action denied", outcome["status"] == "denied" and b1 not in json.dumps(outcome), outcome)
expect_error("isolation: non-member cannot open a read context", lambda: route(service, "GET", w2, ["grants"], "one"), 403)

# --- grants and roles --------------------------------------------------------------------------------------------------
status, listed = route(service, "GET", w1, ["grants"], "one")
check("grants: empty to start, flags reported off by default", status == 200 and listed["grants"] == [] and not any(listed["flags"].values()), listed)
expect_error("grants: viewer cannot grant answer", lambda: route(service, "POST", w1, ["grants"], "viewer", {"grantType": "purpose", "purpose": "answer", "scope": {"kind": "workspace"}}), 403)
expect_error("grants: editor cannot grant cloud processing", lambda: route(service, "POST", w1, ["grants"], "editor", {"grantType": "processing", "location": "cloud", "category": "embedding", "scope": {"kind": "workspace"}}), 403)
expect_error("grants: voice needs authorship attestation", lambda: route(service, "POST", w1, ["grants"], "one", {"grantType": "purpose", "purpose": "voice", "scope": {"kind": "asset", "assetId": a1}}), 422, "library_voice_attestation")
expect_error("grants: public use stays with source review", lambda: route(service, "POST", w1, ["grants"], "one", {"grantType": "purpose", "purpose": "public_use", "scope": {"kind": "workspace"}}), 409, "library_use_source_review")
expect_error("grants: foreign asset scope is unavailable", lambda: route(service, "POST", w1, ["grants"], "one", {"grantType": "purpose", "purpose": "answer", "scope": {"kind": "asset", "assetId": b1}}), 404)
status, answer_grant = route(service, "POST", w1, ["grants"], "editor", {"grantType": "purpose", "purpose": "answer", "scope": {"kind": "asset", "assetId": a1}})
check("grants: editor grants private answers for one item", status == 201 and answer_grant["grantRevision"] == 1, (status, answer_grant))
status, cloud = route(service, "POST", w1, ["grants"], "one", {"grantType": "processing", "location": "cloud", "category": "embedding", "scope": {"kind": "asset", "assetId": a1}})
check("grants: owner grants cloud embedding for one item", status == 201 and cloud["grantRevision"] == 2, cloud)
with connection() as db:
    audits = [r[0] for r in db.execute("SELECT kind FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE 'library.grant%%'", (w1,)).fetchall()]
check("grants: every grant is audited", audits.count("library.grant_created") == 2, audits)

with connection() as db, db.cursor() as cur:
    ctx = api.context(cur, ONE, w1)
    v1, v2 = versions.get(ctx, a1), versions.get(ctx, a2)
    check("purpose: answer allowed only where granted", policy.authorize_source(ctx, v1, "answer").allowed and not policy.authorize_source(ctx, v2, "answer").allowed)
    check("purpose: cloud embedding only for granted item", policy.authorize_processing(ctx, v1, "cloud", "embedding").allowed and not policy.authorize_processing(ctx, v2, "cloud", "embedding").allowed)
    check("purpose: browse never implies cloud", policy.authorize_source(ctx, v2, "browse").allowed and not policy.authorize_processing(ctx, v2, "cloud", "llm").allowed)
    check("purpose: answer attributes, never approves", policy.authorize_source(ctx, v1, "answer").attribution_only)

# --- TOCTOU: a revoke lands between authorize and delivery ------------------------------------------------------------
with connection() as db1:
    cur1 = db1.cursor()
    ctx1 = api.context(cur1, ONE, w1)
    decision = policy.authorize_source(ctx1, versions.get(ctx1, a1), "answer")
    check("toctou: allowed before revoke", decision.allowed and decision.grant_revision == 2, decision.as_dict())
    status, revoked = route(service, "DELETE", w1, ["grants", answer_grant["grantId"]], "one", {"expectedRevision": 2})
    check("toctou: revoke commits and bumps revision", status == 200 and revoked["grantRevision"] == 3 and "expire" in revoked["residual"], revoked)
    fresh = policy.recheck(ctx1, decision)
    check("toctou: recheck before delivery denies", not fresh.allowed and fresh.reason == "grant_required", fresh.as_dict())
expect_error("grants: stale expected revision conflicts", lambda: route(service, "DELETE", w1, ["grants", cloud["grantId"]], "one", {"expectedRevision": 1}), 409, "library_grant_conflict")

# --- revocation propagation ---------------------------------------------------------------------------------------------
with connection() as db:
    job = uuid.uuid4()
    db.execute("INSERT INTO public.pr_library_jobs(id,workspace_id,asset_key,capability,processor_version,consent_revision,idempotency_key,status) VALUES(%s,%s,%s,'embed_text','test-1',2,%s,'queued')",
               (job, w1, a1, "propagation-job-key-0001"))
    db.execute("INSERT INTO public.pr_library_embeddings(id,workspace_id,asset_key,version_key,modality,model_id,dims,index_generation,consent_revision) VALUES(%s,%s,%s,%s,'text','openai/text-embedding-3-large',1024,1,2)",
               (uuid.uuid4(), w1, a1, a1))
    db.execute("INSERT INTO public.pr_library_embeddings(id,workspace_id,asset_key,version_key,modality,model_id,dims,index_generation,consent_revision) VALUES(%s,%s,%s,%s,'visual','local/visual-perceptual-v1',256,1,2)",
               (uuid.uuid4(), w1, a1, a1))
status, revoked = route(service, "DELETE", w1, ["grants", cloud["grantId"]], "one", {"expectedRevision": 3})
check("propagation: receipt counts cancelled job and revoked cloud vector", revoked["propagation"]["jobsCancelled"] == 1 and revoked["propagation"]["embeddingsRevoked"] == 1, revoked)
with connection() as db:
    job_state = db.execute("SELECT status,error_code FROM public.pr_library_jobs WHERE id=%s", (job,)).fetchone()
    vectors = dict(db.execute("SELECT model_id,status FROM public.pr_library_embeddings WHERE workspace_id=%s AND asset_key=%s", (w1, a1)).fetchall())
check("propagation: queued cloud job cancelled for permission", job_state == ("cancelled", "grant_revoked"), job_state)
check("propagation: local private vector survives, cloud vector tombstoned", vectors == {"openai/text-embedding-3-large": "revoked", "local/visual-perceptual-v1": "active"}, vectors)

# --- collection grants are fixed snapshots ------------------------------------------------------------------------------
service.library.collections(w1, "one", {"name": "Recital"})
collection = next(x for x in service.library.collections(w1, "one")["collections"] if x["name"] == "Recital")
service.library.metadata(w1, "one", a1, {"collections": [collection["id"]]})
status, snap = route(service, "POST", w1, ["grants"], "editor", {"grantType": "purpose", "purpose": "answer", "scope": {"kind": "collection", "collectionId": collection["id"]}})
service.library.metadata(w1, "one", a2, {"collections": [collection["id"]]})
with connection() as db, db.cursor() as cur:
    ctx = api.context(cur, ONE, w1)
    check("collections: grant covers members at grant time", policy.authorize_source(ctx, versions.get(ctx, a1), "answer").allowed)
    check("collections: later member not silently covered", not policy.authorize_source(ctx, versions.get(ctx, a2), "answer").allowed)

# --- browser roles cannot read server tables ------------------------------------------------------------------------------
for table in NEW_TABLES:
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
        try:
            db.execute(f"SELECT * FROM public.{table}")
        except psycopg.errors.InsufficientPrivilege:
            db.rollback()
        else:
            raise AssertionError("browser role could read " + table)
checks.append("rls: authenticated role cannot read any Library intelligence table")

print(json.dumps({"status": "pass", "phase": PHASE, "execution": "disposable-local-postgres", "checks": checks}, indent=2, ensure_ascii=False))
