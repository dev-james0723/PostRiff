"""A078 migration rehearsal on disposable PostgreSQL: 097 is additive, idempotent and data-preserving.

The suite runner loads rls.sql (001..097). This script recreates the pre-097 shape a production workspace has today
(normalized assets with chunks, labels, manual collections, legacy photo/video ids in workspace JSON), re-applies 097
twice, and proves: every existing row and object reference survives unchanged, new columns take safe defaults, the
existing list/detail/download paths keep working with all Library intelligence flags OFF, and the migration needs no
backfill to be correct. Runs in both LIBRARY_PG_PHASE=no_vector and vector.
"""
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_storage import PrivateAssetService  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
PHASE = os.environ.get("LIBRARY_PG_PHASE", "no_vector")
OWNER = "00000000-0000-0000-0000-000000000071"
checks = []
for flag in [k for k in os.environ if k.startswith("RAFII_LIBRARY_")]:
    os.environ.pop(flag)  # rehearse with every intelligence flag off (rollback state)


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "owner":
        raise AlphaError("Verified session required.", 401)
    return OWNER


verify.session_id = lambda token, principal: "session-owner-0123456789abcdef"
verify.auth_time = lambda token, principal: 1789524000.0


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    checks.append(name)


class Storage:
    file_bucket = "postriff-library"

    def __init__(self):
        self.objects = {}

    def signed_upload_url(self, ws, category, name):
        return f"https://upload.invalid/{ws}/{name}?token=fake"

    def put(self, ws, name, raw, mime):
        self.objects[(ws, name)] = (raw, mime, hashlib.sha256(raw).hexdigest()[:24])

    def object_info(self, ws, category, name):
        raw, mime, etag = self.objects[(ws, name)]
        return {"bytes": len(raw), "mime": mime, "etag": etag}

    def get_bounded(self, ws, category, name, limit):
        return self.objects[(ws, name)][0]

    def signed_url(self, ws, category, name, expires_in=300):
        assert (ws, name) in self.objects
        return f"https://download.invalid/{ws}/{name}?token=fake"

    def delete(self, ws, category, name):
        self.objects.pop((ws, name), None)

    def list_prefix(self, prefix, bucket=None):
        return []


with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (OWNER,))
storage = Storage()
service = HostedWorkspaceService(connection, verify, assets=PrivateAssetService(storage), clock=lambda: 1789524000.0)
ws = service.bootstrap("owner", "studio")["workspaceId"]

# --- a pre-097 shaped Library: normalized files through the existing upload path, labels, manual collection, legacy ids ---
def upload(name, raw, mime="text/markdown"):
    ticket = service.library.begin(ws, "owner", {"filename": name, "mime": mime, "bytes": len(raw)})["upload"]
    storage.put(ws, ticket["assetId"] + "." + name.rsplit(".", 1)[1], raw, mime)
    service.library.commit(ws, "owner", ticket["assetId"])
    return ticket["assetId"]


doc = upload("programme.md", "Brahms Op.118 程序 notes".encode())
dup = upload("programme-copy.md", "Brahms Op.118 程序 notes".encode())  # exact duplicate of doc
service.library.collections(ws, "owner", {"name": "Autumn"})
collection = next(c for c in service.library.collections(ws, "owner")["collections"] if c["name"] == "Autumn")
service.library.metadata(ws, "owner", doc, {"title": "Programme notes", "tags": ["recital"], "collections": [collection["id"]]})
legacy_id = uuid.uuid4().hex
with connection() as db:
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (ws,)).fetchone()[0]
    state.setdefault("phase2", {}).setdefault("assets", []).append({"id": legacy_id, "hash": "c" * 64, "mime": "image/jpeg", "bytes": 10,
                                                                   "objectName": legacy_id + "-" + "c" * 8 + ".jpg"})
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), ws))
    db.execute("INSERT INTO public.pr_library_labels(workspace_id,asset_key,display_title,tags) VALUES(%s,%s,'Concert photo','{hall}')", (ws, legacy_id))


def snapshot():
    with connection() as db:
        assets = db.execute("SELECT id,original_filename,display_title,tags,kind,mime,bytes,sha256,object_name,processing_status,duplicate_of "
                            "FROM public.pr_library_assets WHERE workspace_id=%s ORDER BY id", (ws,)).fetchall()
        chunks = db.execute("SELECT asset_id,ordinal,text FROM public.pr_library_chunks WHERE workspace_id=%s ORDER BY asset_id,ordinal", (ws,)).fetchall()
        labels = db.execute("SELECT asset_key,display_title,tags FROM public.pr_library_labels WHERE workspace_id=%s ORDER BY asset_key", (ws,)).fetchall()
        items = db.execute("SELECT collection_id,asset_key FROM public.pr_library_collection_items WHERE workspace_id=%s ORDER BY 1,2", (ws,)).fetchall()
    return assets, chunks, labels, items


before = snapshot()
check("setup: duplicate recorded the pre-097 way", any(r[9] == "duplicate" for r in before[0]), before[0])

# --- re-apply 097 twice (production may retry a deploy); the database owner runs migrations ----------------------------------
sql = (ROOT / "migrations/postriff/097_library_intelligence.sql").read_text()
for attempt in (1, 2):
    with connection() as db:
        db.execute(sql)
    check(f"migration: 097 re-applies cleanly (attempt {attempt})", True)

after = snapshot()
check("migration: every existing asset row unchanged", after[0] == before[0], (before[0], after[0]))
check("migration: chunks unchanged", after[1] == before[1])
check("migration: labels (incl. legacy photo title) unchanged", after[2] == before[2], after[2])
check("migration: manual collection membership unchanged", after[3] == before[3], after[3])
with connection() as db:
    defaults = db.execute("SELECT count(*) FILTER (WHERE lineage_id IS NULL AND version_no=1 AND source_kind='upload' AND media='{}'::jsonb), count(*) "
                          "FROM public.pr_library_assets WHERE workspace_id=%s", (ws,)).fetchone()
    kinds = db.execute("SELECT DISTINCT kind FROM public.pr_library_collections WHERE workspace_id=%s", (ws,)).fetchall()
    origins = db.execute("SELECT DISTINCT origin FROM public.pr_library_collection_items WHERE workspace_id=%s", (ws,)).fetchall()
    grant_rows = db.execute("SELECT count(*) FROM public.pr_library_grants WHERE workspace_id=%s", (ws,)).fetchone()[0]
check("migration: existing rows get safe version defaults (no backfill needed)", defaults[0] == defaults[1], defaults)
check("migration: existing collections are manual", kinds == [("manual",)], kinds)
check("migration: existing memberships are manual", origins == [("manual",)], origins)
check("migration: no grants are invented (upload grants nothing)", grant_rows == 0, grant_rows)

# --- rollback state: flags off, the existing product paths keep working ----------------------------------------------------------
listed = service.library.list(ws, "owner")
check("rollback: list returns normalized and legacy items with a server total", listed["total"] == 2 and {a["id"] for a in listed["assets"]} >= {doc, legacy_id},
      (listed["total"], [a["id"] for a in listed["assets"]]))
check("rollback: existing search still finds extracted text", [a["id"] for a in service.library.list(ws, "owner", "Brahms")["assets"]] == [doc])
detail = service.library.detail(ws, "owner", doc)
check("rollback: detail keeps title, tags and collection", detail["asset"]["displayTitle"] == "Programme notes" and detail["asset"]["tags"] == ["recital"]
      and detail["asset"]["collections"] == [collection["id"]], detail["asset"])
check("rollback: original download still signs a private URL", service.library.url(ws, "owner", doc, True)["url"].startswith("https://download.invalid/"))
status, flags = service.library_intelligence.route("GET", ws, ["grants"], {}, lambda: {}, "owner")
check("rollback: intelligence reports every flag off", status == 200 and not any(flags["flags"].values()), flags["flags"])
try:
    service.library_intelligence.route("POST", ws, ["search"], {}, lambda: {"query": "Brahms"}, "owner")
    check("rollback: new retrieval refuses honestly while its flag is off", False)
except AlphaError as error:
    check("rollback: new retrieval refuses honestly while its flag is off", error.status in (403, 503) and "retrieval" in (error.code or ""), (error.status, error.code))

# --- deleting the canonical original keeps the duplicate's bytes (A041/A072 with flags off) ----------------------------------------
objects_before = set(storage.objects)
service.library.delete(ws, "owner", doc)
with connection() as db:
    survivor = db.execute("SELECT processing_status,object_name FROM public.pr_library_assets WHERE id=%s", (uuid.UUID(hex=dup),)).fetchone()
check("delete: the exact duplicate survives and is re-queued as canonical", survivor and survivor[0] in ("queued", "ready", "unsupported"), survivor)
check("delete: the bytes the survivor references were not removed", (ws, survivor[1]) in storage.objects, (survivor, sorted(objects_before)))

print(json.dumps({"status": "pass", "phase": PHASE, "execution": "disposable-local-postgres", "checks": checks}, indent=2, ensure_ascii=False))
