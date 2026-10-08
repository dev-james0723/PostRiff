"""Library intelligence jobs, capabilities and intake (T02) against disposable PostgreSQL with fake private storage.

Runs in both LIBRARY_PG_PHASE=no_vector and LIBRARY_PG_PHASE=vector (scripts/library-intelligence-validation.sh); nothing
here depends on pgvector. Covers enqueue idempotency, concurrent claims with SKIP LOCKED, lease-expiry recovery, the
attempts ceiling, cancellation (queued and mid-run), budget denial through the real Ledger, revocation mid-job through
the real policy/lifecycle, per-asset capability states, legacy-media keys and note/link intake into the real schema.
Processors are synthetic test processors; storage and the link transport are fakes. No provider or network calls.
"""
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

os.environ["RAFII_LIBRARY_ENRICHMENT_ENABLED"] = "1"
for _name in ("POSTRIFF_BUDGET_POLICY", "RAFII_AI_UNLIMITED_USER_IDS", "POSTRIFF_AI_PAUSED"):
    os.environ.pop(_name, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_storage import PrivateAssetService  # noqa: E402
from postriff_phase2.library_intelligence import capabilities, intake, jobs, policy  # noqa: E402
from postriff_phase2.library_intelligence import providers as providers_module  # noqa: E402
from postriff_phase2.library_intelligence.http import read_context, write_context  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
PHASE = os.environ.get("LIBRARY_PG_PHASE", "no_vector")
ONE = "00000000-0000-0000-0000-000000000001"
VIEWER = "00000000-0000-0000-0000-000000000033"
clock = [1789524000.0]
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in ("one", "viewer"):
        raise AlphaError("Verified session required.", 401)
    return ONE if token == "one" else VIEWER


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    checks.append(name)


class Storage:
    def __init__(self):
        self.objects = {}
        self.file_bucket = "postriff-library"

    def signed_upload_url(self, ws, category, name):
        return f"https://upload.invalid/{ws}/{name}?token=fake"

    def put(self, ws, name, raw, mime):
        self.objects[(ws, "file", name)] = (raw, mime, hashlib.sha256(raw).hexdigest()[:24])

    def put_immutable(self, ws, category, name, raw, content_type="image/jpeg"):
        assert category == "file", category
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


def scalar(sql, args=()):
    with connection() as db:
        row = db.execute(sql, args).fetchone()
    return row[0] if row else None


def job_row(job_id):
    with connection() as db:
        return db.execute("SELECT status,attempts,error_category,error_code,lease_token IS NULL FROM public.pr_library_jobs WHERE id=%s",
                          (uuid.UUID(hex=job_id),)).fetchone()


def cap_state(key, capability):
    with connection() as db:
        row = db.execute("SELECT state FROM public.pr_library_capabilities WHERE workspace_id=%s AND asset_key=%s AND capability=%s",
                         (wid, key, capability)).fetchone()
    return row[0] if row else None


def due_now(job_id):
    with connection() as db:
        db.execute("UPDATE public.pr_library_jobs SET next_attempt_at=now() WHERE id=%s", (uuid.UUID(hex=job_id),))


def enqueue(capability, version, key=None):
    with write_context(service, "one", wid) as ctx:
        from postriff_phase2.library_intelligence import versions
        v = versions.get(ctx, key or doc)
        return jobs.enqueue_capability(ctx, versions.ref(v), capability, version, requested_by=ONE)


def register(capability, version, *, location="local", category="extract", kinds=("document",), run=None, estimate=None):
    calls = []

    def runner(job):
        calls.append(job.attempt)
        return run(job) if run else {"state": "ready"}
    capabilities.register({"capability": capability, "version": version, "location": location, "category": category,
                           "applies": lambda v, kinds=kinds: v["kind"] in kinds, "run": runner, "estimate": estimate})
    return calls


# --- schema phase --------------------------------------------------------------------------------------------------------
with connection() as db:
    has_vector = bool(db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_library_embeddings' "
                                 "AND column_name='embedding'").fetchone())
    for table in ("pr_library_jobs", "pr_library_capabilities"):
        row = db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (f"public.{table}",)).fetchone()
        check(f"{table}: forced RLS", row and all(row), row)
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
# Recorded, not asserted: these jobs never touch the vector column, so the suite must pass whichever way the runner is set up.
observed_phase = {"requested": PHASE, "embeddingColumn": has_vector}

storage = Storage()
service = HostedWorkspaceService(connection, verify, assets=PrivateAssetService(storage), clock=lambda: clock[0])
service.bootstrap("one", "studio")
library = service.library
intel = service.library_intelligence

# Only synthetic test processors: the other workstreams' processors are exercised by their own suites.
capabilities._loaded = True
capabilities.PROCESSORS.clear()
seen_raw = []


def extract_run(job):
    raw = job.raw()  # bounded private read with identity and sha256 check
    seen_raw.append(hashlib.sha256(raw).hexdigest() == job.version["sha256"])
    return {"state": "ready", "media": {"pages": 3, "notAMediaFact": True}}


extract_calls = register("extract", "pg-extract-1", run=extract_run)
preview_calls = register("preview", "pg-preview-1", run=lambda job: {"state": "partial", "errorCode": "library_partial_preview", "detail": "Some pages only."})

# --- upload -> hook -> default local capabilities -------------------------------------------------------------------------
raw = b"Brahms intermezzo practice notes.\nVoicing in bar 12."
ticket = library.begin(wid, "one", {"filename": "notes.md", "mime": "text/markdown", "bytes": len(raw)})["upload"]
doc = ticket["assetId"]
storage.put(wid, doc + ".md", raw, "text/markdown")
committed = library.commit(wid, "one", doc)
check("upload: original processed by the existing path", committed["status"] == "ready", committed)
with connection() as db:
    rows = db.execute("SELECT capability,status,consent_revision,idempotency_key FROM public.pr_library_jobs WHERE workspace_id=%s AND asset_key=%s ORDER BY capability",
                      (wid, doc)).fetchall()
check("hook: local defaults enqueued once each", [(r[0], r[1]) for r in rows] == [("extract", "queued"), ("preview", "queued")], rows)
check("hook: idempotency key derived, not random", all(r[3] == jobs.idempotency_key(wid, doc, r[0], f"pg-{r[0]}-1", r[2]) for r in rows), rows)
check("hook: capability rows queued", (cap_state(doc, "extract"), cap_state(doc, "preview")) == ("queued", "queued"))

jobs.on_asset_processed(connection, wid, doc)
again_a = enqueue("extract", "pg-extract-1")
again_b = enqueue("extract", "pg-extract-1")
check("idempotency: duplicate events return the same job", again_a["duplicate"] and again_b["duplicate"] and again_a["job"]["jobId"] == again_b["job"]["jobId"])
check("idempotency: still exactly two jobs", scalar("SELECT count(*) FROM public.pr_library_jobs WHERE workspace_id=%s", (wid,)) == 2)

# --- concurrent claims: SKIP LOCKED hands each worker a different job -----------------------------------------------------
a, b, d = connection(), connection(), connection()
try:
    ra = a.execute(jobs.CLAIM, (uuid.uuid4(), jobs.LEASE_SECONDS)).fetchone()
    rb = b.execute(jobs.CLAIM, (uuid.uuid4(), jobs.LEASE_SECONDS)).fetchone()
    rd = d.execute(jobs.CLAIM, (uuid.uuid4(), jobs.LEASE_SECONDS)).fetchone()
    check("concurrency: two workers claim two different jobs", ra and rb and ra[0] != rb[0], (ra, rb))
    check("concurrency: a third worker skips locked rows instead of waiting", rd is None, rd)
finally:
    for conn in (a, b, d):
        conn.rollback()
        conn.close()

# --- tick: independent capability outcomes --------------------------------------------------------------------------------
summary = intel.tick(connection, max_jobs=10, max_seconds=60)["jobs"]
check("tick: both jobs ran", summary["claimed"] == 2 and summary["completed"] == 1 and summary["partial"] == 1, summary)
check("tick: raw bytes were hash-verified", seen_raw == [True], seen_raw)
check("capabilities: extract ready, preview partial", (cap_state(doc, "extract"), cap_state(doc, "preview")) == ("ready", "partial"))
check("derivative: media merged into the version row", scalar("SELECT media->>'pages' FROM public.pr_library_assets WHERE id=%s", (doc,)) == "3")
check("derivative: only allowlisted media facts are stored", scalar("SELECT media ? 'notAMediaFact' FROM public.pr_library_assets WHERE id=%s", (doc,)) is False)

# --- lease expiry recovery ------------------------------------------------------------------------------------------------
lease_calls = register("visual", "pg-lease-1", category="vision", run=lambda job: {"state": "ready", "media": {"leaseAttempt": job.attempt}})
lease_job = enqueue("visual", "pg-lease-1")["job"]["jobId"]
crashed = jobs.claim_next(intel, connection)
check("lease: crashed worker held the job", crashed and crashed["job"]["id"] == lease_job and job_row(lease_job)[:2] == ("processing", 1))
check("lease: a live lease is not stolen", intel.tick(connection, max_jobs=10, max_seconds=60)["jobs"]["claimed"] == 0)
with connection() as db:
    db.execute("UPDATE public.pr_library_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (uuid.UUID(hex=lease_job),))
summary = intel.tick(connection, max_jobs=10, max_seconds=60)["jobs"]
check("lease: expired lease recovered by the next tick", summary["claimed"] == 1 and job_row(lease_job)[:2] == ("completed", 2), (summary, job_row(lease_job)))
late = jobs.run_claimed(intel, connection, crashed)
check("lease: the late worker writes nothing", late in ("lost", "completed") and
      scalar("SELECT media->>'leaseAttempt' FROM public.pr_library_assets WHERE id=%s", (doc,)) == "2", late)

# --- attempts ceiling with backoff ----------------------------------------------------------------------------------------
def flaky(job):
    raise jobs.RetryableError("Temporarily unavailable.")


flaky_calls = register("embed_text", "pg-flaky-1", category="embedding", run=flaky)
flaky_job = enqueue("embed_text", "pg-flaky-1")["job"]["jobId"]
intel.tick(connection, max_jobs=10, max_seconds=60)
wait = scalar("SELECT extract(epoch from next_attempt_at-now()) FROM public.pr_library_jobs WHERE id=%s", (uuid.UUID(hex=flaky_job),))
check("ceiling: backoff with jitter after attempt 1", 25 <= float(wait) <= jobs.BACKOFF_BASE * (1 + jobs.JITTER) + 2, wait)
check("ceiling: queued while retrying", job_row(flaky_job)[0] == "queued" and cap_state(doc, "embed_text") == "queued")
for _ in range(2):
    due_now(flaky_job)
    intel.tick(connection, max_jobs=10, max_seconds=60)
check("ceiling: failed after exactly three attempts", job_row(flaky_job)[:2] == ("failed", 3) and len(flaky_calls) == 3, (job_row(flaky_job), flaky_calls))
due_now(flaky_job)
check("ceiling: never claimed again", intel.tick(connection, max_jobs=10, max_seconds=60)["jobs"]["claimed"] == 0 and len(flaky_calls) == 3)
check("ceiling: capability failed honestly", cap_state(doc, "embed_text") == "failed")

# --- cancellation: queued, and mid-run (no derivative) --------------------------------------------------------------------
cancel_calls = register("preview", "pg-cancel-1")
queued_job = enqueue("preview", "pg-cancel-1")["job"]["jobId"]
with write_context(service, "one", wid) as ctx:
    out = jobs.cancel_http(ctx, {"params": {"key": doc}, "body": {"capabilities": ["preview"]}, "query": {}})
check("cancel: queued job cancelled", out["cancelled"] == 1 and job_row(queued_job)[0] == "cancelled" and cap_state(doc, "preview") == "cancelled")
check("cancel: cancelled job never runs", intel.tick(connection, max_jobs=10, max_seconds=60)["jobs"]["claimed"] == 0 and cancel_calls == [])


def cancel_mid_run(job):
    with write_context(service, "one", wid) as ctx:
        jobs.cancel(ctx, doc, ["preview"])
    return {"state": "ready", "media": {"midCancel": True}}


register("preview", "pg-midcancel-1", run=cancel_mid_run)
mid_job = enqueue("preview", "pg-midcancel-1")["job"]["jobId"]
summary = intel.tick(connection, max_jobs=10, max_seconds=60)["jobs"]
check("cancel: mid-run cancellation wins at finalize", summary["cancelled"] == 1 and job_row(mid_job)[0] == "cancelled", summary)
check("cancel: no derivative after cancellation", scalar("SELECT media ? 'midCancel' FROM public.pr_library_assets WHERE id=%s", (doc,)) is False)
check("cancel: capability shows cancelled", cap_state(doc, "preview") == "cancelled")

# --- cloud: no grant -> no job; budget refusal -> provider never called ---------------------------------------------------
cloud_calls = register("understand", "pg-cloud-1", location="cloud", category="llm", estimate=lambda job: 1000)
denied = enqueue("understand", "pg-cloud-1")
check("permission: cloud without a grant creates no job", denied["job"] is None and denied["state"] == "blocked_permission" and
      scalar("SELECT count(*) FROM public.pr_library_jobs WHERE workspace_id=%s AND capability='understand'", (wid,)) == 0)
check("permission: capability blocked_permission", cap_state(doc, "understand") == "blocked_permission")
with write_context(service, "one", wid) as ctx:
    granted = policy.grant(ctx, {"grantType": "processing", "scope": {"kind": "workspace"}, "location": "cloud", "category": "llm"})
budget_job = enqueue("understand", "pg-cloud-1")["job"]["jobId"]
summary = intel.tick(connection, max_jobs=10, max_seconds=60)["jobs"]
check("budget: unapproved budget blocks before any provider call", summary["blocked"] == 1 and cloud_calls == [], (summary, cloud_calls))
check("budget: job and capability blocked_budget", job_row(budget_job)[:3] == ("blocked", 1, "budget") and cap_state(doc, "understand") == "blocked_budget",
      job_row(budget_job))

# --- revocation mid-job through the real policy and lifecycle -------------------------------------------------------------
settled = []
real_reserve, real_settle = providers_module.reserve, providers_module.settle
providers_module.reserve = lambda cur, ws, member, **kw: {"status": "reserved", "reservationId": str(uuid.uuid4()), "duplicate": False}
providers_module.settle = lambda cur, ws, reservation, result, failed=False: settled.append(reservation["reservationId"]) or {"state": "unknown"}


def revoke_mid_run(job):
    with write_context(service, "one", wid) as ctx:
        policy.revoke(ctx, granted["grantId"])
    return {"state": "ready", "media": {"afterRevoke": True}, "provider": {"provider": "synthetic", "model": "m", "cost": {"kind": "unknown", "usdMicro": None}}}


try:
    register("understand", "pg-cloud-2", location="cloud", category="llm", estimate=lambda job: 1000, run=revoke_mid_run)
    revoked_job = enqueue("understand", "pg-cloud-2")["job"]["jobId"]
    intel.tick(connection, max_jobs=10, max_seconds=60)
finally:
    providers_module.reserve, providers_module.settle = real_reserve, real_settle
check("revocation: no derivative written", scalar("SELECT media ? 'afterRevoke' FROM public.pr_library_assets WHERE id=%s", (doc,)) is False)
check("revocation: job stopped, capability blocked_permission", job_row(revoked_job)[0] in ("cancelled", "blocked") and cap_state(doc, "understand") == "blocked_permission",
      (job_row(revoked_job), cap_state(doc, "understand")))
check("revocation: the provider attempt is still settled once", len(settled) == 1, settled)

# --- per-asset capability states and isolation ----------------------------------------------------------------------------
with read_context(service, "one", wid) as ctx:
    listed = {s["capability"]: s for s in capabilities.capabilities_http(ctx, {"params": {"key": doc}, "query": {}, "body": {}})["capabilities"]}
check("states: each capability independent", {k: listed[k]["state"] for k in ("extract", "preview", "visual", "embed_text", "understand")} ==
      {"extract": "ready", "preview": "cancelled", "visual": "ready", "embed_text": "failed", "understand": "blocked_permission"}, listed)
check("states: no unmeasured progress", all("progress" not in s for s in listed.values()), listed)
with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (VIEWER,))
viewer_ws = service.bootstrap("viewer", "studio")["workspaceId"]
try:
    with read_context(service, "viewer", viewer_ws) as ctx:
        capabilities.capabilities_http(ctx, {"params": {"key": doc}, "query": {}, "body": {}})
    check("isolation: foreign key is 404", False)
except AlphaError as error:
    check("isolation: foreign key is 404", error.status == 404 and error.code == "library_unavailable", (error.status, error.code))

# --- legacy photo: capability rows keyed by its 32-hex id ------------------------------------------------------------------
legacy = uuid.uuid4().hex
image = b"\xff\xd8\xff\xe0legacy-jpeg"
image_sha = hashlib.sha256(image).hexdigest()
storage.objects[(wid, "media", f"{legacy}-{image_sha}.jpg")] = (image, "image/jpeg", "e")
with connection() as db:
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
    state.setdefault("phase2", {}).setdefault("assets", []).append({"id": legacy, "mime": "image/jpeg", "hash": image_sha, "bytes": len(image),
                                                                    "objectName": f"{legacy}-{image_sha}.jpg", "deleted": False})
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), wid))
image_reads = []
register("embed_visual", "pg-image-1", category="vision", kinds=("image",), run=lambda job: image_reads.append(job.raw() == image) or {"state": "ready"})
jobs.on_asset_processed(connection, wid, legacy)
intel.tick(connection, max_jobs=10, max_seconds=60)
check("legacy: capability row keyed by the legacy id", cap_state(legacy, "embed_visual") == "ready" and image_reads == [True], (cap_state(legacy, "embed_visual"), image_reads))

# --- intake: note and link rows in the real schema, then the existing worker ----------------------------------------------
note_body = {"text": "Programme idea: pair Op. 118 with spoken poetry.", "authoredByMe": True, "idempotencyKey": "pg-note-key-000000001"}
with write_context(service, "one", wid) as ctx:
    note = intake.note_http(ctx, {"params": {}, "query": {}, "body": note_body})
with write_context(service, "one", wid) as ctx:
    replay = intake.note_http(ctx, {"params": {}, "query": {}, "body": note_body})
note_key = note["asset"]["assetRef"]["assetId"]
check("note: idempotent on key", replay["asset"]["assetRef"]["assetId"] == note_key and replay.get("replayed") is True)
with connection() as db:
    row = db.execute("SELECT source_kind,processing_status,provenance->>'authoredByMe',etag IS NOT NULL FROM public.pr_library_assets WHERE id=%s",
                     (note_key,)).fetchone()
check("note: normalized row with authorship provenance", row == ("note", "queued", "true", True), row)
library.sweep(connection)
check("note: processed by the same worker as uploads", scalar("SELECT processing_status FROM public.pr_library_assets WHERE id=%s", (note_key,)) == "ready")


class _Net:
    def resolver(self, host, port, type=None):
        return [(None, None, None, "", ("93.184.216.34", port))]

    def connector(self, scheme, host, address, port, path, timeout, deadline, clock_fn):
        return {"status": 200, "headers": {"content-type": "text/html; charset=utf-8"},
                "body": b"<html><title>Recital</title><body><p>Spring programme</p><script>x()</script></body></html>"}


net = _Net()
real_resolver, real_connector = intake.RESOLVER, intake.CONNECTOR
intake.RESOLVER, intake.CONNECTOR = net.resolver, net.connector
try:
    with write_context(service, "one", wid) as ctx:
        link = intake.link_http(ctx, {"params": {}, "query": {}, "body": {"url": "https://news.example.org/recital", "idempotencyKey": "pg-link-key-000000001"}})
finally:
    intake.RESOLVER, intake.CONNECTOR = real_resolver, real_connector
link_key = link["asset"]["assetRef"]["assetId"]
with connection() as db:
    row = db.execute("SELECT source_kind,mime,provenance->>'sourceUrl',provenance ? 'retrievedAt' FROM public.pr_library_assets WHERE id=%s", (link_key,)).fetchone()
check("link: normalized row with provenance", row == ("link", "text/plain", "https://news.example.org/recital", True), row)
check("link: sanitized text stored, scripts dropped", b"x()" not in storage.objects[(wid, "file", link_key + ".txt")][0])

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "phase": observed_phase, "checks": checks}, indent=2))
