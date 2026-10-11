"""Universal Library against disposable PostgreSQL with fake private storage.

Covers normalized rows/RLS plus begin/commit/search/rename/isolation/delete recovery/sweep.
No provider or network calls.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_storage import PrivateAssetService  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
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
        self.deleted = []
        self.fail_delete = False
        self.file_bucket = "postriff-library"

    def signed_upload_url(self, ws, category, name):
        assert category == "file"
        return f"https://upload.invalid/{ws}/{name}?token=fake"

    def put(self, ws, name, raw, mime):
        self.objects[(ws, name)] = (raw, mime, hashlib.sha256(raw).hexdigest()[:24])

    def object_info(self, ws, category, name):
        assert category == "file"
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

    def put_immutable(self, ws, category, name, raw, content_type='image/jpeg'):
        assert category == 'media'
        if (ws,name) in self.objects: raise AlphaError('Immutable object exists.',409)
        self.put(ws,name,raw,content_type)

    def signed_url(self, ws, category, name, expires_in=300):
        assert (ws, name) in self.objects and category in ('file','media')
        return f"https://download.invalid/{ws}/{name}?token=fake"

    def delete(self, ws, category, name):
        assert category in ("file","media")
        if self.fail_delete:
            raise AlphaError("storage unavailable", 503)
        self.objects.pop((ws, name), None)
        self.deleted.append((ws, name))

    def list_prefix(self, prefix, bucket=None):
        ws, category = prefix.split("/", 1)
        assert category == "file"
        return [f"{ws}/file/{name}" for (owner, name) in self.objects if owner == ws]


with connection() as db:
    for table in ("pr_library_assets", "pr_library_chunks"):
        row = db.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass",
            (f"public.{table}",),
        ).fetchone()
        check(f"{table}: forced RLS", row and all(row), row)
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])

storage = Storage()
service = HostedWorkspaceService(connection, verify, assets=PrivateAssetService(storage), clock=lambda: clock[0])
service.bootstrap("one", "studio")
library = service.library

# Begin is editor-authorized, normalized, and does not mutate the workspace JSON revision.
revision = service.get(wid, "one")["revision"]
raw = b"Brahms rehearsal\nFingering notes."
ticket = library.begin(wid, "one", {"filename": "rehearsal.md", "mime": "text/markdown", "bytes": len(raw)})["upload"]
check("begin: stable asset id", len(ticket["assetId"]) == 32)
check("begin: signed URL not persisted", "token=fake" in ticket["url"])
check("begin: workspace revision unchanged", service.get(wid, "one")["revision"] == revision)
with connection() as db:
    persisted = db.execute(
        "SELECT original_filename,processing_status,token_expires_at is not null FROM public.pr_library_assets WHERE id=%s",
        (ticket["assetId"],),
    ).fetchone()
check("begin: pending normalized row", persisted == ("rehearsal.md", "pending", True), persisted)

storage.put(wid, ticket["assetId"] + ".md", raw, "text/markdown")
committed = library.commit(wid, "one", ticket["assetId"])
check("commit: ready and hashed", committed["status"] == "ready" and len(committed["asset"]["sha256"]) == 64)
detail = library.detail(wid, "one", ticket["assetId"])
check("commit: extracted text persisted", "Brahms rehearsal" in detail["extractedText"], detail)
hits = library.list(wid, "one", "Brahms fingering")["assets"]
check("search: extracted text hit", [a["id"] for a in hits] == [ticket["assetId"]], hits)
digest = hashlib.sha256(raw).hexdigest()
hash_prefix = digest[:16]
check("search: fixture prefix exercises letter casing", hash_prefix.upper() != hash_prefix)
for query in (hash_prefix, hash_prefix.upper(), digest):
    hits = library.list(wid, "one", query)["assets"]
    check("search: normalized SHA prefix or full hash hit " + query, [a["id"] for a in hits] == [ticket["assetId"]], hits)
missing_hash_prefix = ("0" if digest[0] != "0" else "1") + digest[1:16]
check("search: nonmatching SHA prefix empty", not library.list(wid, "one", missing_hash_prefix)["assets"])
renamed = library.rename(wid, "one", ticket["assetId"], "Brahms lesson notes")["asset"]
check("rename: user title wins", renamed["displayTitle"] == "Brahms lesson notes" and renamed["titleSource"] == "user")

# Generic binaries are first-class metadata assets without fabricated extraction.
blob = library.begin(wid, "one", {"filename": "archive.bin", "mime": "application/octet-stream", "bytes": 3})["upload"]
storage.put(wid, blob["assetId"] + ".bin", b"\x01\x02\x03", "application/octet-stream")
generic = library.commit(wid, "one", blob["assetId"])
check("generic: metadata-only asset", generic["status"] == "unsupported" and generic["asset"]["indexingStatus"] == "not_applicable")

# Same asset id through another workspace path is unavailable, not leaked cross-tenant.
with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (VIEWER,))
viewer_workspace = service.bootstrap("viewer", "studio")["workspaceId"]
check("search isolation: foreign workspace cannot find original SHA", not library.list(viewer_workspace, "viewer", hash_prefix)["assets"])
# Identical bytes in two workspaces produce the same fingerprint without sharing rows.
foreign = library.begin(viewer_workspace, "viewer", {"filename": "foreign.md", "mime": "text/markdown", "bytes": len(raw)})["upload"]
storage.put(viewer_workspace, foreign["assetId"] + ".md", raw, "text/markdown")
foreign_result = library.commit(viewer_workspace, "viewer", foreign["assetId"])
check("search isolation: same SHA stored independently", foreign_result["status"] == "ready" and foreign_result["asset"]["sha256"] == digest)
for workspace, token, expected in ((wid, "one", ticket["assetId"]), (viewer_workspace, "viewer", foreign["assetId"])):
    hits = library.list(workspace, token, hash_prefix.upper())["assets"]
    check("search isolation: same SHA returns only own workspace " + token, [a["id"] for a in hits] == [expected], hits)
try:
    library.detail(viewer_workspace, "viewer", ticket["assetId"])
    check("isolation: foreign workspace cannot resolve asset", False)
except AlphaError as error:
    check("isolation: foreign workspace cannot resolve asset", error.status == 404, error.status)
with connection() as db:
    db.execute(
        "INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active') ON CONFLICT(workspace_id,user_id) DO UPDATE SET role='viewer',status='active'",
        (wid, VIEWER),
    )
try:
    library.begin(wid, "viewer", {"filename": "no.txt", "mime": "text/plain", "bytes": 1})
    check("viewer: upload refused", False)
except AlphaError as error:
    check("viewer: upload refused", error.status == 403, error.status)
check("viewer: read allowed", library.detail(wid, "viewer", ticket["assetId"])["asset"]["id"] == ticket["assetId"])

# A storage failure leaves an explicit deleting row; sweep retries idempotently and removes it.
storage.fail_delete = True
try:
    library.delete(wid, "one", ticket["assetId"])
    check("delete: storage failure surfaces", False)
except AlphaError:
    pass
with connection() as db:
    status = db.execute("SELECT processing_status FROM public.pr_library_assets WHERE id=%s", (ticket["assetId"],)).fetchone()[0]
check("delete: failed storage leaves retryable deleting row", status == "deleting", status)
storage.fail_delete = False
swept = library.sweep(connection)
check("sweep: deleting row recovered", swept["removed"] >= 1, swept)
with connection() as db:
    left = db.execute("SELECT count(*) FROM public.pr_library_assets WHERE id=%s", (ticket["assetId"],)).fetchone()[0]
check("sweep: row removed after object cleanup", left == 0, left)

# Browser roles never read the server-owned tables directly.
for statement in ("SELECT * FROM public.pr_library_assets", "SELECT * FROM public.pr_library_chunks"):
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
        try:
            db.execute(statement)
        except psycopg.errors.InsufficientPrivilege:
            db.rollback()
        else:
            raise AssertionError("browser role could read " + statement)
checks.append("authenticated browser role cannot read normalized Library tables")
with connection() as db:
    db.execute("SET ROLE service_role")
    db.execute("SELECT count(*) FROM public.pr_library_assets")
    db.rollback()
checks.append("service_role can access normalized Library tables")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
