"""T06 against disposable PostgreSQL: Smart Collections, version lineage, dependent warnings, comparison and isolation.

Runs twice in cloud CI (LIBRARY_PG_PHASE=no_vector, then vector). Fake private storage; no provider or network calls.
Users are fresh synthetic UUIDs inserted into auth.users (rls.sql marks …0002 deleted). Covers: smart collection save via
the action surface, membership after a new matching upload plus re-evaluation, exclude and undo, missed-event repair via
LibraryIntelligence.tick, no new storage objects or asset rows, stale-revision conflicts, cycle rejection, a version link
flagging a dependent source pack / Ideas source / draft / post, replacement acceptance with a revision check, comparison,
near-duplicate suggestions (vector phase) and cross-workspace denial.
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
from postriff_phase2.library_intelligence import api, collections, relations, versions  # noqa: E402
from postriff_phase2.library_intelligence.http import write_context  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
PHASE = os.environ.get("LIBRARY_PG_PHASE", "no_vector")
OWNER = "00000000-0000-0000-0000-0000000000d1"
OTHER = "00000000-0000-0000-0000-0000000000d2"
VIEWER = "00000000-0000-0000-0000-0000000000d3"
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


def upload(ws, token, name, raw, mime="text/markdown"):
    ticket = service.library.begin(ws, token, {"filename": name, "mime": mime, "bytes": len(raw)})["upload"]
    storage.put(ws, ticket["assetId"] + "." + name.rsplit(".", 1)[1], raw, mime)
    service.library.commit(ws, token, ticket["assetId"])
    return ticket["assetId"]


def route(method, ws, rest, token, body=None):
    return service.library_intelligence.route(method, ws, rest, {}, lambda: body or {}, token)


def act(ws, token, action_type, *, targets=(), revision=None, payload=None):
    envelope = {"actionId": "pg-action", "uiInstanceId": "pg-ui", "actionType": action_type, "targetRefs": list(targets),
                "expectedRevision": revision, "idempotencyKey": "pg-" + uuid.uuid4().hex, "payload": payload or {}}
    return route("POST", ws, ["actions"], token, envelope)[1]


def ref(ws, key, principal=OWNER):
    with connection() as db, db.cursor() as cur:
        return versions.ref(versions.get(api.context(cur, principal, ws), key))


def hook(ws, key):
    with connection() as db, db.cursor() as cur:
        return collections.reevaluate_for_asset(cur, ws, key)


def members(cid):
    with connection() as db:
        return dict(db.execute("SELECT asset_key,origin FROM public.pr_library_collection_items WHERE collection_id=%s", (uuid.UUID(hex=cid),)).fetchall())


def scalar(sql, args=()):
    with connection() as db:
        row = db.execute(sql, args).fetchone()
    return row[0] if row else None


def asset_rows(ws):
    with connection() as db:
        return db.execute("SELECT count(*),coalesce(sum(bytes),0) FROM public.pr_library_assets WHERE workspace_id=%s", (ws,)).fetchone()


# --- schema and identities ------------------------------------------------------------------------------------------------
with connection() as db:
    cols = {r[0] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_name='pr_library_collections'").fetchall()}
    check("schema: smart collection columns", {"kind", "rule", "rule_schema", "explanation", "revision", "last_evaluated_revision"} <= cols, cols)
    for table in ("pr_library_collection_overrides", "pr_library_collection_revisions", "pr_library_relations", "pr_library_suggestions"):
        check(f"schema: {table} exists", db.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0] is not None)
    has_vector = bool(db.execute("SELECT 1 FROM information_schema.columns WHERE table_name='pr_library_embeddings' AND column_name='embedding'").fetchone())
    if PHASE == "vector":
        check("schema: vector phase really has pgvector", has_vector)
    for user in TOKENS.values():
        db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (user,))

storage = Storage()
service = HostedWorkspaceService(connection, verify, assets=PrivateAssetService(storage), clock=lambda: clock[0])
w1 = service.bootstrap("owner", "studio")["workspaceId"]
w2 = service.bootstrap("other", "studio")["workspaceId"]
service.bootstrap("viewer", "studio")
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active') "
               "ON CONFLICT(workspace_id,user_id) DO UPDATE SET role='viewer',status='active'", (w1, VIEWER))

RULE = {"all": [{"field": "kind", "op": "in", "value": ["document"]}, {"field": "tag", "op": "has", "value": "rehearsal"}]}
r1 = upload(w1, "owner", "rehearsal-1.md", "Brahms Op.118 rehearsal notes. 演奏會 on 12 October".encode())
r2 = upload(w1, "owner", "budget.md", b"Hall hire 1200 HKD")
r3 = upload(w1, "owner", "rehearsal-2.md", b"Second rehearsal: voicing in bar 12")
r4 = upload(w1, "owner", "rehearsal-3.md", b"Third rehearsal: pedalling")
b1 = upload(w2, "other", "other-tenant.md", b"Private to workspace two")
service.library.metadata(w1, "owner", r1, {"tags": ["Rehearsal"]})
service.library.collections(w1, "owner", {"name": "Hand picked"})
objects_before, rows_before = len(storage.objects), asset_rows(w1)
org_before = scalar("SELECT coalesce((SELECT organization_revision FROM public.pr_library_policy WHERE workspace_id=%s),0)", (w1,))

# --- smart collection save, explanation and membership ---------------------------------------------------------------------
saved = act(w1, "owner", "collection.save", payload={"name": "Rehearsals", "rule": RULE})
check("save: applied through the action surface", saved["status"] == "applied" and saved["revision"] == 1, saved)
cid = saved["result"]["collection"]["id"]
check("save: membership materialized as references", members(cid) == {r1: "rule"}, members(cid))
check("save: explanation generated from the rule", saved["result"]["collection"]["explanation"] ==
      "Current Library items that are documents and are tagged “rehearsal”.", saved["result"]["collection"]["explanation"])
check("save: organization revision bumped", scalar("SELECT organization_revision FROM public.pr_library_policy WHERE workspace_id=%s", (w1,)) == org_before + 1)
check("save: revision snapshot written", scalar("SELECT snapshot->>'action' FROM public.pr_library_collection_revisions WHERE collection_id=%s AND revision=1",
                                                (uuid.UUID(hex=cid),)) == "created")
listed = {c["name"]: c for c in service.library.collections(w1, "owner")["collections"]}
check("manual: existing manual collections keep working alongside smart ones", {"Hand picked", "Rehearsals"} <= set(listed), listed)
status, detail = route("GET", w1, ["collections", cid], "owner")
check("detail: definition, explanation, history and counts", status == 200 and detail["collection"]["memberCount"] == 1
      and detail["history"][0]["revision"] == 1 and detail["collection"]["evaluationCurrent"], detail)
status, preview = route("POST", w1, ["collections", "preview"], "viewer", {"rule": {"all": [{"field": "text_matches", "op": "matches", "value": "演奏会"}]}})
check("preview: viewer may preview; a Simplified query matches Traditional extracted text", status == 200 and
      [m["assetRef"]["versionId"] for m in preview["members"]] == [r1] and "url" not in json.dumps(preview), preview)
expect_error("rules: SQL text is rejected", lambda: route("POST", w1, ["collections", "preview"], "owner", {"rule": "SELECT * FROM public.pr_library_assets"}),
             400, "library_rule_invalid")
expect_error("rules: unknown field is rejected", lambda: route("POST", w1, ["collections", "preview"], "owner",
                                                                 {"rule": {"all": [{"field": "where", "op": "eq", "value": "1=1"}]}}), 400, "library_rule_invalid")

# --- a new matching upload joins after re-evaluation; a missed event is repaired by tick -------------------------------------
service.library.metadata(w1, "owner", r3, {"tags": ["rehearsal"]})
check("incremental: a tag edit joins at once through the metadata hook", members(cid).get(r3) == "rule", members(cid))
result = hook(w1, r3)
check("incremental: re-running the hook for one lineage is idempotent", result["status"] == "ok" and members(cid).get(r3) == "rule", (result, members(cid)))
with connection() as db:
    # A missed event: the tag lands without passing through metadata(), so no hook ran.
    db.execute("UPDATE public.pr_library_assets SET tags=%s WHERE workspace_id=%s AND id=%s", (["rehearsal"], w1, uuid.UUID(hex=r4)))
    db.execute("UPDATE public.pr_library_collections SET updated_at=now()-interval '1 hour' WHERE id=%s", (uuid.UUID(hex=cid),))
check("reconcile: the missed event is not yet reflected", r4 not in members(cid), members(cid))
tick = service.library_intelligence.tick(connection)
check("reconcile: tick repairs the missed event", tick["collections"]["status"] == "ok" and tick["collections"]["checked"] >= 1
      and members(cid).get(r4) == "rule", (tick, members(cid)))

# --- exclude, undo and conflicts ------------------------------------------------------------------------------------------
excluded = act(w1, "owner", "collection.override", targets=[ref(w1, r3)], revision=1, payload={"collectionId": cid, "mode": "exclude"})
check("override: exclude applied", excluded["status"] == "applied" and excluded["revision"] == 2 and r3 not in members(cid), (excluded, members(cid)))
check("override: exclusion survives incremental re-evaluation", hook(w1, r3)["status"] == "ok" and r3 not in members(cid))
undone = act(w1, "owner", "collection.undo", revision=2, payload={"collectionId": cid})
check("undo: a new revision restores the previous state", undone["status"] == "applied" and undone["revision"] == 3 and members(cid).get(r3) == "rule",
      (undone, members(cid)))
check("undo: history keeps every revision", scalar("SELECT count(*) FROM public.pr_library_collection_revisions WHERE collection_id=%s",
                                                   (uuid.UUID(hex=cid),)) == 3)
with write_context(service, "owner", w1) as ctx:
    collections.save_collection(ctx, RULE, 3, collection_id=cid)

def _stale_save():
    with write_context(service, "owner", w1) as ctx:
        collections.save_collection(ctx, {"all": [{"field": "kind", "op": "in", "value": ["document"]}]}, 3, collection_id=cid)


expect_error("conflict: a concurrent save with a stale revision gets 409", _stale_save, 409, "library_collection_conflict")
stale = act(w1, "owner", "collection.save", revision=3, payload={"collectionId": cid, "rule": RULE})
check("conflict: stale action is a conflict, not an overwrite", stale["status"] == "conflict", stale)
check("conflict: rule unchanged by the losing save", scalar("SELECT revision FROM public.pr_library_collections WHERE id=%s", (uuid.UUID(hex=cid),)) == 4)
denied = act(w1, "viewer", "collection.save", revision=4, payload={"collectionId": cid, "rule": RULE})
check("roles: viewer cannot save", denied["status"] == "denied", denied)
check("no byte copy: no new storage objects", len(storage.objects) == objects_before, (len(storage.objects), objects_before))
check("no byte copy: no new or larger asset rows", asset_rows(w1) == rows_before, (asset_rows(w1), rows_before))

# --- cross-workspace denial -----------------------------------------------------------------------------------------------
expect_error("isolation: another workspace cannot read this collection", lambda: route("GET", w2, ["collections", cid], "other"), 404)
expect_error("isolation: non-member cannot open the workspace", lambda: route("GET", w1, ["collections", cid], "other"), 403)
expect_error("isolation: preview against a foreign collection", lambda: route("POST", w2, ["collections", "preview"], "other",
                                                                            {"rule": RULE, "collectionId": cid}), 404)
status, foreign_preview = route("POST", w2, ["collections", "preview"], "other", {"rule": {"all": [{"field": "kind", "op": "in", "value": ["document"]}]},
                                                                                  "overrides": {"include": [r1]}})
check("isolation: a foreign include is just unavailable", foreign_preview["unavailableIncludes"] == 1 and
      r1 not in json.dumps(foreign_preview["members"]), foreign_preview)
forged = act(w1, "owner", "collection.override", targets=[{"assetId": b1, "versionId": b1, "sha256": ""}], revision=4,
             payload={"collectionId": cid, "mode": "include"})
check("isolation: forged cross-workspace include denied without detail", forged["status"] == "denied" and b1 not in json.dumps(forged), forged)
saved2 = act(w2, "other", "collection.save", payload={"name": "Docs", "rule": {"all": [{"field": "kind", "op": "in", "value": ["document"]}]}})
cid2 = saved2["result"]["collection"]["id"]
before_w1 = members(cid)
hook(w2, r1)
check("isolation: a foreign key never enters another workspace's collection", set(members(cid2)) == {b1} and members(cid) == before_w1, members(cid2))
expect_error("isolation: compare with a foreign version", lambda: route("POST", w1, ["compare"], "owner", {"refs": [ref(w1, r1), {"assetId": b1, "versionId": b1, "sha256": ""}]}), 404)
expect_error("isolation: related of a foreign key", lambda: route("GET", w1, ["assets", b1, "related"], "owner"), 404)

# --- version link flags dependents; replacement is explicit ---------------------------------------------------------------
v1 = upload(w1, "owner", "programme.md", b"Concert on 12 October\nVenue: City Hall")
revision = scalar("SELECT revision FROM public.pr_workspaces WHERE id=%s", (w1,))
imported = service.library.as_source(w1, "owner", v1, {"expectedRevision": revision})
source_id = imported["sourceId"]
with connection() as db:
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (w1,)).fetchone()[0]
    state.setdefault("variants", []).append({"id": "variant-pg", "platform": "instagram", "language": "en", "sourceIds": [source_id], "revision": 1})
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), w1))
    pack = uuid.uuid4()
    db.execute("INSERT INTO public.pr_library_source_packs(id,workspace_id,revision,task_context,evidence_refs,style_refs,grant_revision,status,draft_id,created_by) "
               "VALUES(%s,%s,1,%s::jsonb,%s::jsonb,'[]'::jsonb,0,'draft','draft-pg',%s)",
               (pack, w1, json.dumps({"userGoal": "Concert post"}), json.dumps([{"assetRef": ref(w1, v1)}]), OWNER))
used = act(w1, "owner", "version.link", targets=[ref(w1, v1)], payload={"relation": "used_in", "toKind": "post", "toKey": "post-42"})
check("used_in: recorded once as an explicit citation", used["status"] == "applied", used)
v2 = upload(w1, "owner", "programme-v2.md", b"Concert on 13 October\nVenue: City Hall\nTickets from HKD 200")
state_before = scalar("SELECT state FROM public.pr_workspaces WHERE id=%s", (w1,))
pack_refs_before = scalar("SELECT evidence_refs FROM public.pr_library_source_packs WHERE id=%s", (pack,))
linked = act(w1, "owner", "version.link", targets=[ref(w1, v2), ref(w1, v1)], payload={"relation": "version_of"})
check("link: version_of applied and four dependents flagged", linked["status"] == "applied" and linked["result"]["flagged"]["count"] == 4, linked)
with connection() as db:
    lineage = db.execute("SELECT replace(lineage_id::text,'-',''),version_no FROM public.pr_library_assets WHERE id=%s", (v2,)).fetchone()
    edges = {r for r in db.execute("SELECT relation,from_version,to_version FROM public.pr_library_relations WHERE workspace_id=%s AND to_kind='asset' "
                                   "AND relation IN ('version_of','supersedes')", (w1,)).fetchall()}
    stale_rows = {(r[0], r[1]) for r in db.execute("SELECT to_kind,to_key FROM public.pr_library_relations WHERE workspace_id=%s AND from_version=%s "
                                                    "AND relation='used_in' AND status='stale'", (w1, v1)).fetchall()}
    suggestions = db.execute("SELECT category,state,jsonb_array_length(affected) FROM public.pr_library_suggestions WHERE workspace_id=%s", (w1,)).fetchall()
check("link: newer row restacked under the older lineage", lineage == (v1, 2), lineage)
check("link: version_of and supersedes edges", edges == {("version_of", v2, v1), ("supersedes", v2, v1)}, edges)
check("link: pack, Ideas source, draft and post flagged stale", stale_rows == {("source_pack", pack.hex), ("idea", source_id), ("draft", "variant-pg"),
                                                                                ("post", "post-42")}, stale_rows)
check("link: one outdated_source warning listing all four dependents", suggestions == [("outdated_source", "new", 4)], suggestions)
check("link: old citations are not rewritten", scalar("SELECT evidence_refs FROM public.pr_library_source_packs WHERE id=%s", (pack,)) == pack_refs_before)
check("link: Ideas sources and drafts unchanged", scalar("SELECT state FROM public.pr_workspaces WHERE id=%s", (w1,)) == state_before)
status, stack = route("GET", w1, ["assets", v1, "versions"], "owner")
check("versions: stack, current version and affected drafts", status == 200 and stack["current"]["versionId"] == v2
      and {(a["kind"], a["key"]) for a in stack["affected"]} == stale_rows, stack)
check("versions: the new version is never presented as approved", stack["versions"][1]["approval"]["status"] == "not_reviewed", stack["versions"])
status, compared = route("POST", w1, ["compare"], "owner", {"refs": [ref(w1, v1), ref(w1, v2)]})
check("compare: text diff with both version identities", status == 200 and compared["mode"] == "text"
      and compared["text"]["summary"] == {"added": 1, "removed": 0, "changed": 1, "unchanged": 1}
      and compared["left"]["assetRef"]["versionId"] == v1 and compared["right"]["assetRef"]["versionId"] == v2, compared)
old_ref, new_ref = ref(w1, v1), ref(w1, v2)
stale_accept = act(w1, "owner", "version.accept_replacement", targets=[old_ref, new_ref], revision=0,
                   payload={"dependentKind": "source_pack", "dependentKey": pack.hex})
check("replace: stale pack revision is a conflict", stale_accept["status"] == "conflict", stale_accept)
viewer_accept = act(w1, "viewer", "version.accept_replacement", targets=[old_ref, new_ref], revision=1,
                    payload={"dependentKind": "source_pack", "dependentKey": pack.hex})
check("replace: viewer cannot replace", viewer_accept["status"] == "denied", viewer_accept)
accepted = act(w1, "owner", "version.accept_replacement", targets=[old_ref, new_ref], revision=1,
               payload={"dependentKind": "source_pack", "dependentKey": pack.hex})
check("replace: explicit acceptance applied with a new pack revision", accepted["status"] == "applied" and accepted["revision"] == 2, accepted)
with connection() as db:
    refs_after, warnings_after = db.execute("SELECT evidence_refs,rights_warnings FROM public.pr_library_source_packs WHERE id=%s", (pack,)).fetchone()
    history = db.execute("SELECT status,evidence FROM public.pr_library_relations WHERE workspace_id=%s AND from_version=%s AND to_kind='source_pack'",
                         (w1, v1)).fetchone()
check("replace: the pack now cites the new version", refs_after == [{"assetRef": new_ref}], refs_after)
check("replace: approval does not carry over", any(w.get("code") == "replacement_needs_review" for w in warnings_after), warnings_after)
check("replace: the old citation stays retrievable", history[0] == "dismissed" and history[1]["previousRefs"] == pack_refs_before, history)
status, related = route("GET", w1, ["assets", v2, "related"], "owner")
check("related: lineage edge visible both ways", status == 200 and [n["key"] for n in related["lineage"]["ancestors"]["nodes"]] == [v1], related)

# --- cycles -------------------------------------------------------------------------------------------------------------------
c1 = upload(w1, "owner", "excerpt.md", b"Excerpt")
c2 = upload(w1, "owner", "original.md", b"Original")
first = act(w1, "owner", "version.link", targets=[ref(w1, c1), ref(w1, c2)], payload={"relation": "derived_from"})
check("cycle: first derivation applied", first["status"] == "applied", first)
relations_before = scalar("SELECT count(*) FROM public.pr_library_relations WHERE workspace_id=%s", (w1,))
loop = act(w1, "owner", "version.link", targets=[ref(w1, c2), ref(w1, c1)], payload={"relation": "derived_from"})
check("cycle: the reverse link is a conflict", loop["status"] == "conflict", loop)


def _direct_cycle():
    with write_context(service, "owner", w1) as ctx:
        relations.link_versions(ctx, {"relation": "version_of", "from": ref(w1, c2), "to": ref(w1, c1)})


expect_error("cycle: direct call refuses with 422", _direct_cycle, 422, "library_relation_cycle")
check("cycle: nothing written for refused links", scalar("SELECT count(*) FROM public.pr_library_relations WHERE workspace_id=%s", (w1,)) == relations_before)
check("cycle: refused version link did not restack", scalar("SELECT lineage_id FROM public.pr_library_assets WHERE id=%s", (c2,)) is None)

# --- near duplicates: suggestions only ------------------------------------------------------------------------------------------
statuses_before = scalar("SELECT jsonb_object_agg(id::text,processing_status) FROM public.pr_library_assets WHERE workspace_id=%s", (w1,))
if has_vector:
    base = [round(0.01 * (i % 7) + 0.1, 4) for i in range(256)]
    near = list(base)
    near[0] += 0.001
    with connection() as db:
        for key, vector in ((c1, base), (c2, near)):
            db.execute("INSERT INTO public.pr_library_embeddings(id,workspace_id,asset_key,version_key,modality,model_id,dims,index_generation,consent_revision,embedding) "
                       "VALUES(%s,%s,%s,%s,'visual','local/visual-perceptual-v1',256,1,0,%s::vector)", (uuid.uuid4(), w1, key, key, json.dumps(vector)))
    with connection() as db, db.cursor() as cur:
        similar = relations.refresh_similar(cur, w1, c1)
    check("near-duplicate: one suggestion from local perceptual vectors", similar.get("available") is True and similar.get("suggested") == 1, similar)
    with connection() as db:
        rows = db.execute("SELECT status,origin FROM public.pr_library_relations WHERE workspace_id=%s AND relation='similar_to'", (w1,)).fetchall()
    check("near-duplicate: stored as a system suggestion", rows == [("suggested", "system")], rows)
    status, near_view = route("GET", w1, ["assets", c1, "related"], "owner")
    check("near-duplicate: shown as a suggestion", [s["other"]["assetRef"]["versionId"] for s in near_view["nearDuplicates"]["suggestions"]] == [c2], near_view)
else:
    with connection() as db, db.cursor() as cur:
        similar = relations.refresh_similar(cur, w1, c1)
    check("near-duplicate: honestly unavailable without pgvector", similar.get("available") is False, similar)
check("near-duplicate: nothing merged, hidden or deleted",
      scalar("SELECT jsonb_object_agg(id::text,processing_status) FROM public.pr_library_assets WHERE workspace_id=%s", (w1,)) == statuses_before)

print(json.dumps({"status": "pass", "phase": PHASE, "embeddingColumn": has_vector, "execution": "disposable-local-postgres", "checks": checks},
                 indent=2, ensure_ascii=False))
