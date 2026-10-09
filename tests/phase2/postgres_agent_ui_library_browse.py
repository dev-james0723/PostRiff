"""D-A51 on a disposable PostgreSQL: the Rafii Manager's metadata-level `library_browse` tool and the GenUI J03 `ids` / date
inputs, on the real HostedWorkspaceService + UniversalLibrary, real roles and two tenants.

- owner, editor and viewer browse and see the same rows; a revoked member and a member whose profile was deleted are refused
  before anything is read, and so is a person from another workspace;
- workspace B's items are never returned to workspace A (tool, collection filter and the J03 `ids` binding), and B's upload
  rows never date A's videos;
- media-store photos/videos (labelled through the Library service) and pr_library_assets files (with a collection) are listed
  together; a document that mentions a word only in its summary or extracted text is not matched by it;
- a video's added date comes from its committed pr_media_uploads row; photos have none and are never inside a date window;
- the tool opens exactly one workspace transaction and writes nothing; the J03 query savepoint leaves no writes;
- with the flag off (or the workspace not on the canary list) the Manager has no library_browse and the tool refuses.

Nothing is asserted through a service-role bypass of the code under test. Migration 102 is applied inline (J03 artifacts).

Run: PYTHONPATH=src:tests python scripts/postriff_pg_suite.py postgres_agent_ui_library_browse
"""
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.agent_runtime_v2 import (config, contracts, context as rt_context, domain_tools, library_browse, manager, tool_adapter,  # noqa: E402
                                              ui_capabilities, ui_contracts, ui_http, ui_queries)
from postriff_phase2.agent_runtime_v2.ui_domain import shapes  # noqa: E402
from consumer_fixtures import approve_budgets  # noqa: E402

domain_tools.ensure_registered()

PORT = os.environ.get("POSTRIFF_PG_PORT", "55438")
DSN = f"host=127.0.0.1 port={PORT} dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
EDITOR_ID = "00000000-0000-0000-0000-000000000003"
OTHER_ID = "00000000-0000-0000-0000-000000000004"
VIEWER_ID = "00000000-0000-0000-0000-000000000005"
REVOKED_ID = "00000000-0000-0000-0000-000000000006"
DELETED_ID = "00000000-0000-0000-0000-000000000007"
EMPTY_ID = "00000000-0000-0000-0000-000000000008"
TOKENS = {"owner-token-0000000000000000000": ONE, "editor-token-000000000000000000": EDITOR_ID, "other-token-0000000000000000000": OTHER_ID,
          "viewer-token-000000000000000000": VIEWER_ID, "revoked-token-00000000000000000": REVOKED_ID, "deleted-token-00000000000000000": DELETED_ID,
          "empty-token-0000000000000000000": EMPTY_ID}
OWNER, EDITOR, OTHER, VIEWER, REVOKED, DELETED, EMPTY = list(TOKENS)
HK = "Asia/Hong_Kong"
RESULTS = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required.", 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: f"session-{principal}-0123456789abcdef"
verify.auth_time = lambda token, principal: time.time()


def one(sql, *params):
    with connection() as db:
        return db.execute(sql, params).fetchone()


def scenario(sid, title):
    def wrap(fn):
        started = time.monotonic()
        record = {"id": sid, "title": title}
        try:
            detail = fn() or {}
            record.update({"result": "PASS", **detail})
        except Exception as error:  # noqa: BLE001
            record.update({"result": "FAIL", "error": f"{type(error).__name__}: {error}", "trace": traceback.format_exc()[-2000:]})
        record["ms"] = round((time.monotonic() - started) * 1000)
        RESULTS.append(record)
        print(f"{record['result']:5} {sid} {title}" + (f"\n      {record.get('error')}\n{record.get('trace')}" if record["result"] == "FAIL" else ""), flush=True)
        return fn
    return wrap


# --- setup ----------------------------------------------------------------------------------------------------------------
with connection() as db:
    db.execute((ROOT / "migrations/postriff/102_agent_ui_artifacts.sql").read_text())
    db.execute("INSERT INTO auth.users VALUES(%s),(%s),(%s),(%s),(%s),(%s) ON CONFLICT DO NOTHING", (EDITOR_ID, OTHER_ID, VIEWER_ID, REVOKED_ID, DELETED_ID, EMPTY_ID))
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
    db.execute("UPDATE public.pr_memberships SET status='active', role='owner' WHERE user_id=%s", (ONE,))

service = HostedWorkspaceService(connection, verify, clock=time.time)
service.bootstrap(OWNER, "studio")
other_wid = service.bootstrap(OTHER, "studio")["workspaceId"]
empty_wid = service.bootstrap(EMPTY, "studio")["workspaceId"]
for token in (EDITOR, VIEWER, REVOKED, DELETED):
    service.bootstrap(token, "studio")
with connection() as db:
    for user, role in ((EDITOR_ID, "editor"), (VIEWER_ID, "viewer"), (REVOKED_ID, "viewer"), (DELETED_ID, "editor")):
        db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_publish) VALUES(%s,%s,%s,'active',false)", (wid, user, role))
approve_budgets(connection, wid)
approve_budgets(connection, other_wid)
approve_budgets(connection, empty_wid)
ON_ENV = {"RAFII_AGENT_V2_ENABLED": "1", "RAFII_GENUI_ENABLED": "1", "RAFII_AGENT_LIBRARY_BROWSE_ENABLED": "1",
          "RAFII_AGENT_LIBRARY_BROWSE_WORKSPACES": ",".join((wid, other_wid, empty_wid))}
CFG = config.RuntimeConfig.from_environment(ON_ENV)
runtime = SimpleNamespace(service=service, cfg=CFG)

P1, P2, P3, P4, V1, V2 = (uuid.uuid4().hex for _ in range(6))     # workspace A media store
D1, D2, D3 = (uuid.uuid4() for _ in range(3))                      # workspace A files
BP, BD = uuid.uuid4().hex, uuid.uuid4()                             # workspace B photo, file
CONTENT_ONLY = "Chopin Ballade rehearsal recital notes"


def media(workspace, assets):
    """Add media-store records the way the stores keep them (state.phase2.assets), straight into the workspace row."""
    with connection() as db:
        state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace,)).fetchone()[0]
        state = json.loads(state) if isinstance(state, str) else state
        state.setdefault("phase2", {}).setdefault("assets", []).extend(assets)
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), workspace))


def photo(ident, n):
    return {"id": ident, "mime": "image/jpeg", "hash": uuid.uuid4().hex * 2, "bytes": 200_000 + n, "width": 1080, "height": 1350, "duration": 0,
            "processing": "decoded", "deleted": False, "objectName": f"{ident}.jpg", "storagePath": f"x/media/{ident}.jpg", "alt": "private alt text"}


def video(ident, n):
    return {"id": ident, "kind": "video", "mime": "video/mp4", "category": "video", "bucket": "postriff-video", "objectName": f"{ident}.mp4",
            "storagePath": f"x/video/{ident}.mp4", "bytes": 40_000_000 + n, "duration": 95.0, "durationSource": "container", "width": 1920, "height": 1080,
            "etag": "e", "hash": uuid.uuid4().hex * 2, "processing": "ready", "deleted": False, "uploadedBy": ONE,
            "poster": {"objectName": "poster.jpg", "hash": "d" * 64, "width": 640, "height": 360, "bytes": 10}, "frames": []}


def library_file(asset, workspace, owner, filename, title, created, *, summary=None, tags=(), chunk=None, kind="document"):
    with connection() as db:
        db.execute("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,display_title,summary,tags,kind,mime,extension,bytes,sha256,bucket,"
                   "object_name,processing_status,analysis_status,indexing_status,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s::text[],%s,'text/plain','txt',160,%s,'postriff-library',"
                   "%s,'ready','ready','ready',%s)", (asset, workspace, owner, filename, title, summary, list(tags), kind, "e" * 64, uuid.uuid4().hex + ".txt", created))
        if chunk:
            db.execute("INSERT INTO public.pr_library_chunks(asset_id,workspace_id,ordinal,text) VALUES(%s,%s,0,%s)", (asset, workspace, chunk))


def upload_row(ident, workspace, owner, created, status="committed"):
    with connection() as db:
        db.execute("INSERT INTO public.pr_media_uploads(id,workspace_id,created_by,bucket,object_name,mime,declared_bytes,status,token_expires_at,created_at) "
                   "VALUES(%s,%s,%s,'postriff-video',%s,'video/mp4',10,%s,now()+interval '1 hour',%s)", (ident, workspace, owner, f"{ident}.mp4", status, created))


media(wid, [photo(P1, 1), photo(P2, 2), photo(P3, 3), photo(P4, 4), video(V1, 5), video(V2, 6)])
media(other_wid, [photo(BP, 9)])
lib = service.library
lib.metadata(wid, OWNER, P1, {"title": "Piano practice Monday", "tags": ["piano practice"]})
lib.metadata(wid, OWNER, P2, {"title": "Piano practice scales", "tags": ["piano practice"]})
lib.metadata(wid, OWNER, P3, {"title": "Recital bow", "tags": ["recital"]})
lib.metadata(wid, OWNER, V1, {"title": "Recital run-through"})
lib.metadata(other_wid, OTHER, BP, {"title": "Piano practice in B", "tags": ["piano practice"]})
library_file(D1, wid, ONE, "recital-programme.txt", "Recital programme", "2026-08-15 04:00:00+00", tags=["recital"])
library_file(D2, wid, ONE, "notes.txt", None, "2026-09-10 04:00:00+00", summary=CONTENT_ONLY, chunk="Chopin: recital pacing, bar 1-24.")
library_file(D3, wid, ONE, "ledger.txt", "Studio ledger", "2026-07-01 04:00:00+00", kind="file")
library_file(BD, other_wid, OTHER_ID, "recital-b.txt", "Recital programme in B", "2026-08-16 04:00:00+00", tags=["recital"])
upload_row(V1, wid, ONE, "2026-08-20 04:00:00+00")
upload_row(V2, other_wid, OTHER_ID, "2026-08-21 04:00:00+00")   # B's row with A's video id: never dates A's video
COLLECTION = next(c["id"] for c in lib.collections(wid, OWNER, {"name": "Spring recital"})["collections"] if c["name"] == "Spring recital")
B_COLLECTION = next(c["id"] for c in lib.collections(other_wid, OTHER, {"name": "B only"})["collections"] if c["name"] == "B only")
lib.metadata(wid, OWNER, D1.hex, {"tags": ["recital"], "collections": [COLLECTION]})   # a label row then carries the tags
lib.metadata(wid, OWNER, P3, {"collections": [COLLECTION]})
with connection() as db:
    db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (wid, REVOKED_ID))
    db.execute("UPDATE public.pr_profiles SET deleted_at=now() WHERE user_id=%s", (DELETED_ID,))
A_IDS = {P1, P2, P3, P4, V1, V2, D1.hex, D2.hex, D3.hex}
B_IDS = {BP, BD.hex}


def ctx_for(token, workspace=None, cfg=None):
    return rt_context.RafiiRunContext(service=service, workspace_id=workspace or wid, token=token, principal=TOKENS[token], membership=None,
                                      conversation_id=str(uuid.uuid4()), trace_id=contracts.new_trace_id(), zone=HK, now=time.time, config=cfg or CFG)


def browse(token=OWNER, workspace=None, cfg=None, **args):
    ctx = ctx_for(token, workspace, cfg)
    return ctx, tool_adapter.execute(ctx, tool_adapter.REGISTRY["library_browse"], args, scope=frozenset(manager.tool_names(ctx)))


def ids_of(out):
    return [i["assetId"] for i in out["data"]["items"]]


def workspace_counts(workspace=None):
    workspace = workspace or wid
    with connection() as db:
        return {"revision": db.execute("SELECT revision FROM public.pr_workspaces WHERE id=%s", (workspace,)).fetchone()[0],
                "audit": db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s", (workspace,)).fetchone()[0],
                "actions": db.execute("SELECT count(*) FROM public.pr_ui_actions WHERE workspace_id=%s", (workspace,)).fetchone()[0],
                "messages": db.execute("SELECT count(*) FROM public.pr_messages WHERE workspace_id=%s", (workspace,)).fetchone()[0],
                "labels": db.execute("SELECT count(*) FROM public.pr_library_labels WHERE workspace_id=%s", (workspace,)).fetchone()[0],
                "uploads": db.execute("SELECT count(*) FROM public.pr_media_uploads WHERE workspace_id=%s", (workspace,)).fetchone()[0]}


# --- GenUI artifacts (the J03 binding through lane D's real query path) ------------------------------------------------------
def auth_for(token, workspace=None):
    with service.repository.transaction(token, workspace or wid) as (_cur, row, principal):
        member = service.ideas._member(row)
    return ui_http.UiAuth(workspace_id=workspace or wid, principal=str(principal), member=member, role=member.role, scope="workspace", scope_key="")


def make_artifact(journeys, *, token=OWNER, workspace=None):
    workspace = workspace or wid
    owner_id = TOKENS[token]
    with connection() as db:
        conv = str(db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'Library browse') RETURNING id",
                              (workspace, owner_id)).fetchone()[0])
        result = {"composedBy": "manager", "usage": {"billing": "metered"}, "answerText": "x", "toolActivity": [], "ui": {"journeyIds": journeys}}
        run = str(db.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) "
                             "VALUES(%s,%s,%s,'completed','rafii-agent','standard',%s,%s,%s,%s::jsonb) RETURNING id",
                             (conv, workspace, owner_id, "a" * 64, "b" * 64, "agent:" + uuid.uuid4().hex, json.dumps({"version": 1, "result": result}))).fetchone()[0])
    auth = auth_for(token, workspace)
    manifest = ui_capabilities.build_manifest(None, auth, {"journey_ids": journeys}, scope="workspace")
    with connection() as db:
        artifact = str(db.execute(
            "INSERT INTO public.pr_ui_artifacts(workspace_id,scope,scope_key,conversation_id,parent_run_id,actor,surface,journey_ids,revision,source_hash,generation_state,"
            "validation_state,manifest,manifest_id,binding_version) VALUES(%s,'workspace','',%s,%s,%s,'chat',%s,1,%s,'ready','accepted',%s::jsonb,%s,1) RETURNING id",
            (workspace, conv, run, auth.principal, journeys, "c" * 64, json.dumps(manifest), manifest["manifestId"])).fetchone()[0])
    return {"artifactId": artifact, "conversation": conv}


def query(binding, inputs, *, art, token=OWNER, workspace=None):
    body = {"artifactId": art["artifactId"], "artifactRevision": 1, "bindingId": binding, "inputs": inputs or {}}
    out = ui_queries.query_http(runtime, workspace or wid, token, ui_contracts.validate_query(body))
    assert set(out) == {"state", "data", "asOf", "sourceRefs", "revision", "nextCursor", "coverage", "warnings"}, sorted(out)
    if out["data"] is not None:
        declared = shapes.SHAPES[binding]
        assert set(out["data"]) <= set(declared["keys"]), sorted(set(out["data"]) - set(declared["keys"]))
        for row in out["data"].get("items") or []:
            assert set(row) <= set(declared["lists"]["items"]), sorted(set(row) - set(declared["lists"]["items"]))
    return out


# ===========================================================================================================================
@scenario("LB-1", "owner, editor and viewer browse the whole Library (both stores) and see the same rows; row keys are exactly the allowlist")
def _():
    seen = {}
    for token in (OWNER, EDITOR, VIEWER):
        _ctx, out = browse(token)
        assert out["ok"] is True and out["verified"] is True, out
        seen[token] = ids_of(out)
        for item in out["data"]["items"]:
            assert tuple(item) == library_browse.ROW_KEYS, sorted(item)
    assert seen[OWNER] == seen[EDITOR] == seen[VIEWER], seen
    assert set(seen[OWNER]) == A_IDS, (sorted(set(seen[OWNER]) ^ A_IDS))
    _ctx, out = browse(OWNER)
    dumped = json.dumps(out)
    for private in (CONTENT_ONLY, "private alt text", "poster.jpg", "x/video/", "e" * 64, ONE, "pypdf"):
        assert private not in dumped, private
    assert out["data"]["counts"] == {"listed": 9, "matched": 9, "dateUnknown": 5, "complete": True}, out["data"]["counts"]
    return {"rows": len(seen[OWNER])}


@scenario("LB-2", "a revoked member, a member whose profile was deleted and a person from another workspace are refused before anything is read")
def _():
    for token in (REVOKED, DELETED, OTHER):
        _ctx, out = browse(token)
        assert out["ok"] is False and out["code"] in ("permission_denied", "forbidden"), (token, out)
        assert "data" not in out, out
    try:
        with service.repository.transaction(REVOKED, wid):
            raise AssertionError("a revoked member opened the workspace")
    except AlphaError as error:
        assert error.status == 403, error
    return {}


@scenario("LB-3", "cross-workspace isolation: zero rows from another workspace through the tool, a foreign collection id, or text that names B's items")
def _():
    _ctx, a = browse(OWNER)
    assert not set(ids_of(a)) & B_IDS, ids_of(a)
    _ctx, b = browse(OTHER, workspace=other_wid)
    assert set(ids_of(b)) == B_IDS, ids_of(b)
    assert not set(ids_of(b)) & A_IDS
    _ctx, named = browse(OWNER, q="in B")
    assert ids_of(named) == [], ids_of(named)
    _ctx, foreign_collection = browse(OWNER, collection=B_COLLECTION)
    assert ids_of(foreign_collection) == [], ids_of(foreign_collection)
    _ctx, in_collection = browse(OWNER, collection=COLLECTION)
    assert set(ids_of(in_collection)) == {D1.hex, P3}, ids_of(in_collection)
    assert all(COLLECTION in i["collections"] for i in in_collection["data"]["items"])
    for text in (json.dumps(a), json.dumps(foreign_collection)):
        assert "Piano practice in B" not in text and "Recital programme in B" not in text
    return {}


@scenario("LB-4", "metadata-only matching across stores: labels, tags and collections; a word only in a document's summary/text never matches it")
def _():
    _ctx, practice = browse(OWNER, q="piano practice", kind="image")
    assert set(ids_of(practice)) == {P1, P2}, ids_of(practice)
    _ctx, recital = browse(OWNER, q="recital")
    assert set(ids_of(recital)) == {P3, V1, D1.hex}, ids_of(recital)
    assert D2.hex not in ids_of(recital), "D2's 'recital' is only in its summary and extracted text"
    assert recital["data"]["counts"]["matched"] == 3
    _ctx, chopin = browse(OWNER, q="chopin")
    assert ids_of(chopin) == [] and chopin["data"]["libraryEmpty"] is False, chopin["data"]
    _ctx, tagged = browse(OWNER, tag="piano practice")
    assert set(ids_of(tagged)) == {P1, P2}
    _ctx, videos = browse(OWNER, kind="video")
    assert set(ids_of(videos)) == {V1, V2} and {i["kind"] for i in videos["data"]["items"]} == {"video"}
    _ctx, files = browse(OWNER, kind="file")
    assert ids_of(files) == [D3.hex]
    item = next(i for i in recital["data"]["items"] if i["assetId"] == D1.hex)
    assert item["store"] == "file" and item["kind"] == "document" and item["title"] == "Recital programme" and item["tags"] == ["recital"], item
    clip = next(i for i in recital["data"]["items"] if i["assetId"] == V1)
    assert clip["store"] == "media" and clip["title"] == "Recital run-through" and clip["duration"] == 95.0 and clip["width"] == 1920, clip
    return {}


@scenario("LB-5", "dates: a video's added date is its committed pr_media_uploads row in this workspace; photos have none; windows never include an undated item")
def _():
    _ctx, out = browse(OWNER)
    items = {i["assetId"]: i for i in out["data"]["items"]}
    assert items[V1]["addedAt"] == "2026-08-20T12:00", items[V1]
    assert items[V2]["addedAt"] is None, "B's upload row with this id must not date A's video"
    for ident in (P1, P2, P3, P4):
        assert items[ident]["addedAt"] is None, ident
    assert items[D1.hex]["addedAt"] == "2026-08-15T12:00" and items[D2.hex]["addedAt"] == "2026-09-10T12:00"
    _ctx, august = browse(OWNER, addedFrom="2026-08-01", addedTo="2026-08-31")
    assert set(ids_of(august)) == {V1, D1.hex}, ids_of(august)
    assert august["data"]["counts"]["dateUnknown"] == 5, august["data"]["counts"]
    _ctx, september_videos = browse(OWNER, kind="video", addedFrom="2026-09-01", addedTo="2026-09-30")
    assert ids_of(september_videos) == [] and "no recorded date" in september_videos["data"]["note"], september_videos["data"]
    _ctx, refused = browse(OWNER, addedFrom="2026-09-01", addedTo="2026-08-01")
    assert refused["ok"] is False and refused["code"] == "tool_input", refused
    return {}


@scenario("LB-6", "one workspace transaction per call, the Library read on its cursor, no writes; references carry ids only")
def _():
    original = service.repository.transaction
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[1] if len(args) > 1 else kwargs.get("workspace_id"))
        return original(*args, **kwargs)

    before = workspace_counts()
    service.repository.transaction = counted
    try:
        ctx, out = browse(OWNER, q="recital", addedFrom="2026-08-01", addedTo="2026-08-31")
    finally:
        del service.repository.transaction
    assert out["ok"] is True, out
    assert calls == [wid], calls
    assert workspace_counts() == before, (before, workspace_counts())
    refs = [r for r in ctx.ledger.references if r["type"] == "asset"]
    assert [r["id"] for r in refs] == ids_of(out) and all(r["title"] is None for r in refs), refs
    return {"transactions": len(calls)}


@scenario("LB-7", "GenUI J03 ids: exactly this workspace's items in the given order, foreign ids only counted; B's view of A's ids is empty; no writes")
def _():
    art = make_artifact(["J03"])
    before = workspace_counts()
    picked = query("library_search", {"ids": [D1.hex, P3, BD.hex, V1, BP]}, art=art)
    assert [i["assetId"] for i in picked["data"]["items"]] == [D1.hex, P3, V1], picked["data"]["items"]
    assert picked["coverage"]["total"] == 3 and picked["warnings"] == ["2 of the chosen items aren't available here."], picked
    assert BD.hex not in json.dumps(picked) and BP not in json.dumps(picked["data"])
    assert workspace_counts() == before, "the query savepoint leaves no writes"
    clip = next(i for i in picked["data"]["items"] if i["assetId"] == V1)
    assert clip["createdAt"] == "2026-08-20T04:00:00Z", clip
    foreign = make_artifact(["J03"], token=OTHER, workspace=other_wid)
    theirs = query("library_search", {"ids": [D1.hex, P3, V1]}, art=foreign, token=OTHER, workspace=other_wid)
    assert theirs["state"] == "empty" and theirs["data"]["items"] == [] and theirs["coverage"]["note"] == "Nothing in your Library matches these filters.", theirs
    dated = query("library_search", {"addedFrom": "2026-08-01", "addedTo": "2026-08-31"}, art=art)
    assert {i["assetId"] for i in dated["data"]["items"]} == {V1, D1.hex}, dated["data"]["items"]
    try:
        query("library_search", {"ids": [D1.hex]}, art=art, token=REVOKED)
        raise AssertionError("a revoked member read the view's data")
    except AlphaError as error:
        assert error.status in (401, 403, 404), error
    empty_art = make_artifact(["J03"], token=EMPTY, workspace=empty_wid)
    nothing = query("library_search", {}, art=empty_art, token=EMPTY, workspace=empty_wid)
    assert nothing["state"] == "empty" and nothing["coverage"]["note"] == "Your Library has no items yet.", nothing
    return {}


@scenario("LB-8", "flag off or workspace not listed: no library_browse on the Manager and the tool refuses; an empty Library says so")
def _():
    off = config.RuntimeConfig.from_environment({"RAFII_AGENT_V2_ENABLED": "1"})
    unlisted = config.RuntimeConfig.from_environment({**ON_ENV, "RAFII_AGENT_LIBRARY_BROWSE_WORKSPACES": other_wid})
    for cfg in (off, unlisted):
        ctx = ctx_for(OWNER, cfg=cfg)
        assert "library_browse" not in manager.tool_names(ctx) and "library_read" not in manager.tool_names(ctx)
        out = tool_adapter.execute(ctx, tool_adapter.REGISTRY["library_browse"], {})
        assert out["ok"] is False and out["code"] == "library_browse_off", out
    ctx = ctx_for(OWNER)
    assert {"library_browse", "library_read"} <= set(manager.tool_names(ctx))
    _ctx, empty = browse(EMPTY, workspace=empty_wid)
    assert empty["data"]["libraryEmpty"] is True and empty["data"]["items"] == [] and empty["data"]["note"] == library_browse.EMPTY_LIBRARY, empty["data"]
    return {}


failed = [r for r in RESULTS if r["result"] != "PASS"]
print(json.dumps({"script": "postgres_agent_ui_library_browse", "passed": len(RESULTS) - len(failed), "failed": len(failed),
                  "scenarios": [{k: r.get(k) for k in ("id", "result", "ms")} for r in RESULTS]}), flush=True)
sys.exit(1 if failed else 0)
