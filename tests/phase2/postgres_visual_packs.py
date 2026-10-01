"""Visual Pack on disposable PostgreSQL (PRD R-VIS-01..03 · AC22 · AC23 · AC29 · AC30).

Migration 083 (forced RLS, grants, idempotent reapply, append-only trigger), prepare/edit revisions with idempotency
and expected-revision conflicts, edits superseding (and so invalidating) accepted/exported revisions while earlier
revisions and their files stay intact, cross-tenant image refs refused, render/export idempotent with no duplicate
storage writes or events, export_ready → downloaded → user_confirmed_used recorded separately, the Queue handoff
refused truthfully, Library-image deletion purging derivative renders, pagination bounds, and handoff_counts. Storage
is the real SupabaseStorage adapter over an in-memory object store (synthetic; nothing leaves this machine).

    RAFII_PG_PORT=55884 PYTHONPATH=src:tests python scripts/rafii_pg_private.py postgres_visual_packs
"""
import base64
import hashlib
import io
import json
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import psycopg  # noqa: E402
from PIL import Image  # noqa: E402

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.coworker import flags  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_storage import PrivateAssetService, SupabaseStorage  # noqa: E402
from postriff_phase2.visual_pack import checks, jobs as vp_jobs, service as vp_service  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000083"   # a fresh second tenant (rls.sql tombstones its own user two)
REVIEW = {c["id"]: c for c in json.loads((ROOT / "tests/fixtures/product_growth/review_set_v1.json").read_text())["cases"]}
passed = []


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    passed.append(name)


def refused(call, status, code=None):
    try:
        call()
    except AlphaError as error:
        assert error.status == status and (code is None or error.code == code), (error.status, error.code, str(error))
        return error
    raise AssertionError(f"expected {status} {code}")


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    return {"one": ONE, "two": TWO}[token]


verify.session_id = lambda token, principal: f"visual-pack-{token}-session"
verify.auth_time = lambda token, principal: time.time()


class Objects:
    """An in-memory Supabase Storage endpoint behind the real adapter: no upsert, 404 on a missing object, listing."""
    def __init__(self):
        self.objects, self.calls = {}, []

    def __call__(self, method, url, headers, body):
        rest = url.split("/storage/v1/object/", 1)[1]
        self.calls.append((method, rest))
        if method == "POST" and rest.startswith("list/"):
            query = json.loads(body)
            bucket, folder = rest[5:], query["prefix"]
            names = sorted(k[len(bucket) + len(folder) + 2:] for k in self.objects if k.startswith(f"{bucket}/{folder}/"))
            return 200, {}, json.dumps([{"name": n} for n in names[query["offset"]:query["offset"] + query["limit"]]]).encode()
        if method == "POST":
            assert headers.get("x-upsert") == "false"
            if rest in self.objects:
                return 409, {}, b""
            self.objects[rest] = body
            return 200, {}, b"{}"
        if method == "GET":
            return (200, {}, self.objects[rest]) if rest in self.objects else (404, {}, b"")
        if method == "DELETE":
            return (200, {}, b"") if self.objects.pop(rest, None) is not None else (404, {}, b"")
        raise AssertionError(method)

    def under(self, workspace_id, category="visual-pack"):
        return sorted(k for k in self.objects if k.startswith(f"postriff-private/{workspace_id}/{category}/"))

    def writes(self):
        return sum(1 for method, rest in self.calls if method == "POST" and not rest.startswith("list/"))


def jpeg(color, size=(1600, 1200)):
    out = io.BytesIO()
    image = Image.new("RGB", size, color)
    image.putdata([((x // 7 + color[0]) % 256, (y // 5 + color[1]) % 256, color[2]) for y in range(size[1]) for x in range(size[0])])
    image.save(out, "JPEG", quality=90)
    return base64.b64encode(out.getvalue()).decode()


def edit_state(workspace_id, change):
    with connection() as db:
        state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace_id,)).fetchone()[0]
        change(state)
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))


def role(workspace_id, user, value):
    with connection() as db:
        db.execute("UPDATE public.pr_memberships SET role=%s WHERE workspace_id=%s AND user_id=%s", (value, workspace_id, user))


def rows(sql, *params):
    with connection() as db:
        return db.execute(sql, params).fetchall()


objects = Objects()
storage = SupabaseStorage("https://project.supabase.co", "s" * 32, send=objects)
service = HostedWorkspaceService(connection, verify, assets=PrivateAssetService(storage))
with connection() as db:
    db.execute("INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING", (TWO,))
service.bootstrap("one", "studio")
service.bootstrap("two", "studio")
wid = str(rows("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", ONE)[0][0])
other = str(rows("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", TWO)[0][0])
packs = vp_service.ensure(service)

# --- migration 083: forced RLS, least-privilege grants, idempotent reapply (AC30) --------------------------------------
TABLES = ("pr_visual_packs", "pr_visual_pack_revisions", "pr_visual_pack_events")
forced = rows("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname = ANY(%s) ORDER BY relname", list(TABLES))
check("083 tables exist with forced RLS", len(forced) == 3 and all(r[1] and r[2] for r in forced), forced)
grants = rows("SELECT t, has_table_privilege('authenticated','public.'||t,'SELECT'), has_table_privilege('authenticated','public.'||t,'INSERT'),"
              "has_table_privilege('anon','public.'||t,'SELECT'), has_table_privilege('service_role','public.'||t,'INSERT') FROM unnest(%s::text[]) t", list(TABLES))
check("authenticated read-only, anon none, service_role writes", all(r[1:] == (True, False, False, True) for r in grants), grants)
with psycopg.connect(DSN, autocommit=True) as db:
    db.execute((ROOT / "migrations/postriff/083_visual_packs.sql").read_text())
check("083 reapplies cleanly", len(rows("SELECT 1 FROM pg_policies WHERE tablename = ANY(%s)", list(TABLES))) == 6)

# --- fixtures: two Library images through the real decode/storage path, three drafts, one connected account ----------
saved = service.upload_media(wid, "one", service.repository.get(wid, "one")["revision"], {"data": jpeg((30, 80, 150))})
PHOTO = saved["state"]["phase2"]["assets"][-1]["id"]
saved = service.upload_media(wid, "one", saved["revision"], {"data": jpeg((200, 120, 40), (1200, 1600))})
PHOTO2 = saved["state"]["phase2"]["assets"][-1]["id"]
foreign = service.upload_media(other, "two", service.repository.get(other, "two")["revision"], {"data": jpeg((10, 10, 10))})
FOREIGN = foreign["state"]["phase2"]["assets"][-1]["id"]
V_ZH, V_EN, V_EMOJI = "a1" * 16, "b2" * 16, "c3" * 16


def add_drafts(state):
    state.setdefault("variants", [])
    state["variants"] += [
        {"id": V_ZH, "platform": "Instagram", "language": "zh-Hant", "revision": 1, "text": REVIEW["zh-hant-factual-studio"]["source"]},
        {"id": V_EN, "platform": "Threads", "language": "en", "revision": 1, "text": REVIEW["en-factual-workshop"]["source"]},
        {"id": V_EMOJI, "platform": "Instagram", "language": "en", "revision": 1, "text": REVIEW["emoji-and-symbols"]["source"]},
    ]
    state["phase2"].setdefault("channels", []).append({"id": "ig-account", "platform": "Instagram", "account": "@studio", "configured": True, "revoked": False,
                                                       "identityVerified": True, "capabilityVerified": True, "verifiedAt": time.time(),
                                                       "expiresAt": time.time() + 86400, "scopes": ["instagram_business_content_publish"],
                                                       "capabilityVersion": 1, "evidenceSource": "synthetic"})


edit_state(wid, add_drafts)

# --- flag gate ---------------------------------------------------------------------------------------------------------
flags.attach({})
refused(lambda: packs.list(wid, "one"), 404, "feature_disabled")
flags.attach({"RAFII_VISUAL_PACK_ENABLED": "true"})
check("flag off answers feature_disabled; on serves", packs.list(wid, "one")["items"] == [])

# --- prepare: idempotent, permissioned, tenant-scoped -------------------------------------------------------------------
role(wid, ONE, "viewer")
refused(lambda: packs.prepare(wid, "one", {"idempotencyKey": "prep-zh-0001", "variantId": V_ZH}), 403)
role(wid, ONE, "owner")
first = packs.prepare(wid, "one", {"idempotencyKey": "prep-zh-0001", "variantId": V_ZH, "settings": {"palette": "rafii_violet"}})
pack_id = first["pack"]["id"]
again = packs.prepare(wid, "one", {"idempotencyKey": "prep-zh-0001", "variantId": V_ZH, "settings": {"palette": "rafii_violet"}})
check("prepare: six slides from the draft, revision 1 draft", len(first["revision"]["slides"]) == 6 and first["revision"]["revision"] == 1
      and first["revision"]["state"] == "draft" and first["pack"]["language"] == "zh-Hant", first["revision"])
check("prepare replay returns the same pack once", again["pack"]["id"] == pack_id and again.get("replayed")
      and rows("SELECT count(*) FROM public.pr_visual_packs WHERE workspace_id=%s", wid)[0][0] == 1)
refused(lambda: packs.prepare(wid, "one", {"idempotencyKey": "prep-zh-0001", "variantId": V_EN}), 409, "idempotency_conflict")
refused(lambda: packs.prepare(wid, "one", {"idempotencyKey": "prep-missing-01", "variantId": "f" * 32}), 404, "not_found")
refused(lambda: packs.prepare(wid, "two", {"idempotencyKey": "prep-two-0001", "variantId": V_ZH}), 403)
refused(lambda: packs.get(other, "two", pack_id), 404, "not_found")
refused(lambda: packs.get(wid, "two", pack_id), 403)
check("prepare is permissioned and tenant-scoped", True)

# --- edit: new revisions, conflicts, idempotency, cross-tenant images ---------------------------------------------------
slides = first["revision"]["slides"]
stored_first = rows("SELECT slides,content_digest FROM public.pr_visual_pack_revisions WHERE pack_id=%s AND revision_no=1", pack_id)[0]
filled = [{"key": s["key"], "text": s["text"] or "週六體驗課，歡迎報名。"} for s in slides]
second = packs.edit(wid, "one", pack_id, {"idempotencyKey": "edit-0001-fill", "expectedRevision": 1, "slides": filled,
                                          "order": [slides[i]["key"] for i in (0, 1, 3, 2, 4, 5)]})
check("edit creates revision 2 and supersedes revision 1", second["revision"]["revision"] == 2 and second["pack"]["currentRevision"] == 2
      and rows("SELECT state FROM public.pr_visual_pack_revisions WHERE pack_id=%s AND revision_no=1", pack_id)[0][0] == "superseded")
check("reorder kept every slide once", sorted(s["key"] for s in second["revision"]["slides"]) == sorted(s["key"] for s in slides)
      and second["revision"]["slides"][2]["key"] == slides[3]["key"])
check("revision 1 content is intact", rows("SELECT slides,content_digest FROM public.pr_visual_pack_revisions WHERE pack_id=%s AND revision_no=1", pack_id)[0] == stored_first)
refused(lambda: packs.edit(wid, "one", pack_id, {"idempotencyKey": "edit-0002-stale", "expectedRevision": 1, "caption": "x"}), 409, "revision_conflict")
replay = packs.edit(wid, "one", pack_id, {"idempotencyKey": "edit-0001-fill", "expectedRevision": 1, "slides": filled,
                                          "order": [slides[i]["key"] for i in (0, 1, 3, 2, 4, 5)]})
check("edit replay creates nothing", replay.get("replayed") and replay["pack"]["currentRevision"] == 2)
refused(lambda: packs.edit(wid, "one", pack_id, {"idempotencyKey": "edit-0001-fill", "expectedRevision": 2, "caption": "different"}), 409, "idempotency_conflict")
refused(lambda: packs.edit(wid, "one", pack_id, {"idempotencyKey": "edit-0003-foreign", "expectedRevision": 2,
                                                  "slides": [{"key": slides[1]["key"], "imageAssetId": FOREIGN}]}), 404, "not_found")
refused(lambda: packs.edit(wid, "one", pack_id, {"idempotencyKey": "edit-0004-missing", "expectedRevision": 2,
                                                  "slides": [{"key": slides[1]["key"], "imageAssetId": "0" * 32}]}), 404, "not_found")
check("cross-tenant and missing image refs are refused", rows("SELECT max(revision_no) FROM public.pr_visual_pack_revisions WHERE pack_id=%s", pack_id)[0][0] == 2)
same = packs.edit(wid, "one", pack_id, {"idempotencyKey": "edit-0005-noop", "expectedRevision": 2, "caption": second["revision"]["caption"]})
check("an edit that changes nothing makes no revision", same.get("unchanged") and same["pack"]["currentRevision"] == 2)

# Blocking checks: an emoji is reported per slide and blocks rendering; fixed in the next revision.
emoji = packs.edit(wid, "one", pack_id, {"idempotencyKey": "edit-0006-emoji", "expectedRevision": 2, "slides": [{"key": slides[4]["key"], "text": "記得帶圍裙 ✅"}]})
finding = next(f for s in emoji["revision"]["checks"]["slides"] for f in s["findings"] if f["code"] == "missing_glyphs")
check("missing glyphs reported on the exact slide", finding["glyphs"][0]["codePoint"] == "U+2705"
      and emoji["revision"]["checks"]["slides"][4]["ok"] is False and emoji["revision"]["checks"]["ok"] is False)
refused(lambda: packs.render(wid, "one", pack_id, {"expectedRevision": 3}), 409, "unsupported_input")
check("nothing rendered for a blocked revision", objects.under(wid) == [])
ready = packs.edit(wid, "one", pack_id, {"idempotencyKey": "edit-0007-fixed", "expectedRevision": 3,
                                         "slides": [{"key": slides[4]["key"], "text": "記得帶圍裙。"}, {"key": slides[1]["key"], "imageAssetId": PHOTO}],
                                         "settings": {"weight": "bold"}})
check("fixed revision passes checks with an image", ready["revision"]["revision"] == 4 and ready["revision"]["checks"]["ok"]
      and ready["revision"]["slides"][1]["imageAssetId"] == PHOTO and ready["revision"]["settings"] == {"palette": "rafii_violet", "weight": "bold"})
check("default alt text follows the slide", ready["revision"]["slides"][1]["altText"].startswith("第 2 張，共 6 張。") and "圖片" in ready["revision"]["slides"][1]["altText"])

# --- render: six verified PNGs in private storage, idempotent (AC22) -----------------------------------------------------
refused(lambda: packs.accept(wid, "one", pack_id, {"expectedRevision": 4, "confirmed": True}), 409, "render_required")
writes = objects.writes()
rendered = packs.render(wid, "one", pack_id, {"expectedRevision": 4})
files = rendered["revision"]["render"]["slides"]
stored = objects.under(wid)
check("AC22 render: six ordered 1080x1350 PNGs with hashes", [f["position"] for f in files] == [1, 2, 3, 4, 5, 6]
      and all((f["width"], f["height"], f["mime"]) == (1080, 1350, "image/png") for f in files) and len(stored) == 6
      and rendered["revision"]["state"] == "rendered", files)
for f in files:
    raw, sha = packs.slide(wid, "one", pack_id, 4, f["position"])
    check(f"slide {f['position']} bytes verify and match the manifest", checks.verify_png(raw)["sha256"] == sha == f["sha256"] == hashlib.sha256(raw).hexdigest())
writes_after = objects.writes()
replayed = packs.render(wid, "one", pack_id, {"expectedRevision": 4})
check("re-render of the same revision does no work", replayed.get("replayed") and objects.writes() == writes_after and writes_after - writes == 6
      and rows("SELECT count(*) FROM public.pr_visual_pack_events WHERE pack_id=%s AND kind='rendered'", pack_id)[0][0] == 1)
manifest = rows("SELECT render_manifest FROM public.pr_visual_pack_revisions WHERE pack_id=%s AND revision_no=4", pack_id)[0][0]
check("manifest records lineage, fonts and no paid calls", manifest["lineage"]["sourceVariantId"] == V_ZH and manifest["lineage"]["imageAssetIds"] == [PHOTO]
      and manifest["lineage"]["paidCalls"] == 0 and manifest["renderer"]["fonts"]["bold"] == checks.fonts.sha256("bold"))

# --- the Queue handoff is refused truthfully; assisted export offered ------------------------------------------------------
with connection() as db:   # an editor without the publish flag lacks `approve`
    db.execute("UPDATE public.pr_memberships SET role='editor',can_publish=false WHERE workspace_id=%s AND user_id=%s", (wid, ONE))
refused(lambda: packs.queue(wid, "one", pack_id, {"expectedRevision": 4, "channelId": "ig-account"}), 403)
with connection() as db:
    db.execute("UPDATE public.pr_memberships SET role='owner',can_publish=true WHERE workspace_id=%s AND user_id=%s", (wid, ONE))
error = refused(lambda: packs.queue(wid, "one", pack_id, {"expectedRevision": 4, "channelId": "ig-account"}), 409, "unsupported_input")
view = packs.get(wid, "one", pack_id)
check("AC23 Queue handoff refused with its reason; nothing queued", "Export the files" in str(error) and view["handoff"]["queue"]["available"] is False
      and view["handoff"]["queue"]["channels"][0]["supported"] is False and rows("SELECT count(*) FROM public.pr_visual_pack_events WHERE kind='queued'")[0][0] == 0)

# --- accept → export → download → confirm, each a separate fact (AC23) ---------------------------------------------------
refused(lambda: packs.export(wid, "one", pack_id, {"expectedRevision": 4}), 409, "approval_required")
accepted = packs.accept(wid, "one", pack_id, {"expectedRevision": 4, "confirmed": True})
packs.accept(wid, "one", pack_id, {"expectedRevision": 4, "confirmed": True})
check("accept once, one product event", accepted["revision"]["state"] == "accepted" and accepted["revision"]["approvalDigest"]
      and rows("SELECT count(*) FROM public.pr_product_events WHERE workspace_id=%s AND event='visual_pack.accepted'", wid)[0][0] == 1)
refused(lambda: packs.download(wid, "one", pack_id, 4), 409, "approval_required")
exported = packs.export(wid, "one", pack_id, {"expectedRevision": 4})
reads = sum(1 for m, _ in objects.calls if m == "GET")
replay_export = packs.export(wid, "one", pack_id, {"expectedRevision": 4})
check("export once: export_ready, replay rebuilds nothing", exported["revision"]["state"] == "export_ready" and replay_export.get("replayed")
      and sum(1 for m, _ in objects.calls if m == "GET") == reads and exported["revision"]["export"]["handoff"] == "assisted_export"
      and "has not published" in exported["receipt"])
archive, filename = packs.download(wid, "one", pack_id, 4)
second_copy, _ = packs.download(wid, "one", pack_id, 4)
with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
    names = bundle.namelist()
    exported_manifest = json.loads(bundle.read("manifest.json"))
    pngs = [bundle.read(f"slide-{i:02d}.png") for i in range(1, 7)]
    alt = bundle.read("alt-text.txt").decode()
    caption = bundle.read("caption.txt").decode()
check("AC22 export zip: six PNGs, caption, alt text, manifest, handoff note", names == [f"slide-{i:02d}.png" for i in range(1, 7)] + ["caption.txt", "alt-text.txt", "manifest.json", "HANDOFF.txt"])
check("export PNGs are the rendered files", [hashlib.sha256(p).hexdigest() for p in pngs] == [f["sha256"] for f in files])
check("export manifest has no storage locations and says not published", "storagePath" not in json.dumps(exported_manifest)
      and exported_manifest["publication"] == "not_published_by_rafii" and exported_manifest["handoff"] == "assisted_export")
check("alt text and caption exported", all(s["altText"] in alt for s in ready["revision"]["slides"]) and caption.strip() == ready["revision"]["caption"])
check("downloads are byte-identical and counted once as a fact", archive == second_copy and filename.endswith("-r4.zip")
      and rows("SELECT state,download_count FROM public.pr_visual_pack_revisions WHERE pack_id=%s AND revision_no=4", pack_id)[0] == ("downloaded", 2)
      and rows("SELECT count(*) FROM public.pr_visual_pack_events WHERE pack_id=%s AND kind='downloaded'", pack_id)[0][0] == 1)
refused(lambda: packs.confirm_used(wid, "one", pack_id, {"expectedRevision": 4}), 400, "approval_required")
used = packs.confirm_used(wid, "one", pack_id, {"expectedRevision": 4, "confirmed": True})
facts = used["revision"]["facts"]
check("AC23 export_ready, downloaded and user_confirmed_used are separate facts", used["revision"]["state"] == "user_confirmed_used"
      and facts["exportReadyAt"] and facts["downloadedAt"] and facts["userConfirmedUsedAt"] and facts["queuedAt"] is None
      and "did not publish" in used["receipt"])
with connection() as db, db.cursor() as cur:
    counts = vp_service.handoff_counts(cur, wid, time.time() - 3600, time.time() + 60)
    empty = vp_service.handoff_counts(cur, wid, time.time() + 3600, time.time() + 7200)
check("handoff_counts per fact, nothing queued or verified", counts == {"exportReady": 1, "downloaded": 1, "userConfirmedUsed": 1, "queued": 0, "verifiedPublished": 0}
      and set(empty.values()) == {0}, counts)

# --- editing an exported pack invalidates acceptance/export; earlier revisions and files stay (AC23) ----------------------
changed = packs.edit(wid, "one", pack_id, {"idempotencyKey": "edit-0008-after", "expectedRevision": 4, "slides": [{"key": slides[0]["key"], "text": "新的開場：週六陶藝體驗。"}]})
check("AC23 edit after export: new draft revision, the exported one superseded", changed["revision"]["revision"] == 5 and changed["revision"]["state"] == "draft"
      and rows("SELECT state,export_digest IS NOT NULL,confirmed_used_at IS NOT NULL FROM public.pr_visual_pack_revisions WHERE pack_id=%s AND revision_no=4", pack_id)[0] == ("superseded", True, True))
refused(lambda: packs.download(wid, "one", pack_id, 4), 409, "approval_expired")
check("earlier revision files stay readable", packs.slide(wid, "one", pack_id, 4, 1)[1] == files[0]["sha256"] and len(objects.under(wid)) == 6)
rerendered = packs.render(wid, "one", pack_id, {"expectedRevision": 5})
check("AC23 the edited revision renders its own files and manifest", len(objects.under(wid)) == 12 and rerendered["revision"]["render"]["slides"][0]["sha256"] != files[0]["sha256"]
      and rerendered["revision"]["render"]["slides"][1]["sha256"] == files[1]["sha256"])

# A changed draft (claim/CTA) blocks acceptance until the pack is reconciled with it.
edit_state(wid, lambda s: next(v for v in s["variants"] if v["id"] == V_ZH).update(revision=2, text=REVIEW["zh-hant-factual-studio"]["source"].replace("1,200", "1,500")))
check("source change is visible", packs.get(wid, "one", pack_id)["revision"]["sourceStatus"] == "changed")
refused(lambda: packs.accept(wid, "one", pack_id, {"expectedRevision": 5, "confirmed": True}), 409, "revision_conflict")
resplit = packs.edit(wid, "one", pack_id, {"idempotencyKey": "edit-0009-resplit", "expectedRevision": 5, "source": "resplit"})
check("resplit takes the changed claim into the slides", resplit["revision"]["sourceStatus"] == "current" and any("1,500" in s["text"] for s in resplit["revision"]["slides"])
      and resplit["revision"]["slides"][1]["imageAssetId"] == PHOTO)

# --- append-only guard -------------------------------------------------------------------------------------------------
for sql in ("UPDATE public.pr_visual_pack_revisions SET slides='[]'::jsonb WHERE pack_id=%s AND revision_no=1",
            "UPDATE public.pr_visual_pack_revisions SET state='draft' WHERE pack_id=%s AND revision_no=1",
            "UPDATE public.pr_visual_pack_events SET kind='queued' WHERE pack_id=%s"):
    try:
        with connection() as db:
            db.execute(sql, (pack_id,))
        raise AssertionError(sql)
    except psycopg.errors.InsufficientPrivilege:
        pass
check("revisions and events are append-only in the database", True)

# --- RLS: members read their own rows; nobody reads or forges another tenant's (AC29) ---------------------------------------
with connection() as db:
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (TWO,))
    leaked = [db.execute(f"SELECT count(*) FROM public.{t} WHERE workspace_id=%s", (wid,)).fetchone()[0] for t in TABLES]
    try:
        db.execute("INSERT INTO public.pr_visual_packs(workspace_id,idempotency_key,request_digest,created_by) VALUES(%s,'forged-key-01',%s,%s)", (wid, "0" * 64, TWO))
        forged = True
    except psycopg.errors.InsufficientPrivilege:
        forged = False
with connection() as db:
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
    own = db.execute("SELECT count(*) FROM public.pr_visual_pack_revisions WHERE workspace_id=%s", (wid,)).fetchone()[0]
check("RLS: no cross-tenant read or write; members read their own", leaked == [0, 0, 0] and not forged and own == 6, (leaked, forged, own))

# --- Library deletion propagates to derivative renders --------------------------------------------------------------------
before = len(objects.under(wid))
service.delete_media(wid, "one", service.repository.get(wid, "one")["revision"], PHOTO)
after_view = packs.get(wid, "one", pack_id)
purged = rows("SELECT revision_no FROM public.pr_visual_pack_revisions WHERE pack_id=%s AND purged_at IS NOT NULL ORDER BY revision_no", pack_id)
check("deleting a Library image purges every render that embeds it", [r[0] for r in purged] == [4, 5] and before == 12 and objects.under(wid) == []
      and "missing_image" in [f["code"] for s in after_view["revision"]["checks"]["slides"] for f in s["findings"]], (purged, objects.under(wid)))
refused(lambda: packs.slide(wid, "one", pack_id, 4, 1), 404, "not_found")
check("purges are system facts", rows("SELECT count(*),count(actor) FROM public.pr_visual_pack_events WHERE pack_id=%s AND kind='purged'", pack_id)[0] == (2, 0))

# --- pagination: bounded, deterministic, complete ----------------------------------------------------------------------
for i in range(29):
    packs.prepare(wid, "one", {"idempotencyKey": f"prep-many-{i:04d}", "variantId": V_EN if i % 2 else V_EMOJI})
seen, cursor, pages = [], None, []
while True:
    page = packs.list(wid, "one", cursor)
    pages.append(len(page["items"]))
    seen += [item["id"] for item in page["items"]]
    cursor = page["nextCursor"]
    if not cursor:
        break
check("pagination: 25 then 5, no duplicates, newest first", pages == [25, 5] and len(set(seen)) == 30 and seen[-1] == pack_id, pages)
refused(lambda: packs.list(wid, "one", limit=51), 400)
refused(lambda: packs.list(wid, "one", cursor="not-a-cursor"), 400)
check("an emoji draft prepares with its glyph finding instead of tofu", any(f["code"] == "missing_glyphs" for s in packs.get(wid, "one", seen[0])["revision"]["checks"]["slides"]
                                                                            for f in s["findings"]))

# --- the bounded background step purges renders nobody opens ---------------------------------------------------------------
idle = vp_jobs.tick(service, time.monotonic() + 10)
tick_pack = packs.prepare(wid, "one", {"idempotencyKey": "prep-tick-0001", "variantId": V_EN})
tick_id, tick_slides = tick_pack["pack"]["id"], tick_pack["revision"]["slides"]
packs.edit(wid, "one", tick_id, {"idempotencyKey": "edit-tick-0001", "expectedRevision": 1,
                                 "slides": [{"key": tick_slides[0]["key"], "imageAssetId": PHOTO2}]
                                 + [{"key": s["key"], "text": s["text"] or "Written by the person."} for s in tick_slides[1:]]})
packs.render(wid, "one", tick_id, {"expectedRevision": 2})
rendered_objects = len(objects.under(wid))
service.delete_media(wid, "one", service.repository.get(wid, "one")["revision"], PHOTO2)
swept = vp_jobs.tick(service, time.monotonic() + 10)
again = vp_jobs.tick(service, time.monotonic() + 10)
check("cron step purges a deleted image's renders once, and idles otherwise", idle == {"status": "ok", "workspaces": 0, "purged": 0}
      and rendered_objects == 6 and swept == {"status": "ok", "workspaces": 1, "purged": 1} and objects.under(wid) == []
      and again == {"status": "ok", "workspaces": 0, "purged": 0}, (idle, swept, again))

# --- account deletion helper removes every rendered object (rows cascade with the workspace) ------------------------------
second_pack = packs.prepare(wid, "one", {"idempotencyKey": "prep-final-0001", "variantId": V_EN})
packs.edit(wid, "one", second_pack["pack"]["id"], {"idempotencyKey": "edit-final-0001", "expectedRevision": 1, "caption": "Final caption.",
                                                   "slides": [{"key": s["key"], "text": s["text"] or "Written by the person."} for s in second_pack["revision"]["slides"]]})
packs.render(wid, "one", second_pack["pack"]["id"], {"expectedRevision": 2})
check("purge_workspace removes every rendered object", len(objects.under(wid)) == 6 and vp_service.purge_workspace(service, wid) == 24 and objects.under(wid) == [])

print(json.dumps({"status": "pass", "execution": "disposable PostgreSQL; in-memory storage endpoint behind the real SupabaseStorage adapter (synthetic)",
                  "acceptance": ["AC22", "AC23", "AC29", "AC30"], "checks": passed}, ensure_ascii=False))
