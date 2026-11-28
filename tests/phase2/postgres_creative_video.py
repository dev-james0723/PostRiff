"""Real WSGI, workspace permissions, PostgreSQL, ledger, analysis and rendering on a disposable database.

The test storage is workspace-keyed memory. The video provider is a counting double; its acceptance cannot
establish live model generation. The MP4s are the original, explicitly licensed timer-study fixtures.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for folder in ("scripts", "tests", "src"):
    sys.path.insert(0, str(ROOT / folder))

from postriff_alpha.domain import AlphaError
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.creative_video import CreativeVideoService
from postriff_phase2.creative_video_media_provider import ProviderError, VideoProvider
from postriff_phase2.credit_meter import POLICY_VERSION, millicredits
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.video_uploads import VideoPolicy, VideoUploads
from postriff_dev_hosted import DevAssets
from test_postriff_phase2_hosted import invoke
from consumer_fixtures import approve_budgets


FOUNDER_TEST_PREREQUISITES = """create schema if not exists rafii_control;
          do $$begin
            if not exists(select 1 from pg_roles where rolname='rafii_control_reader') then create role rafii_control_reader; end if;
            if not exists(select 1 from pg_roles where rolname='rafii_control_session') then create role rafii_control_session; end if;
            if not exists(select 1 from pg_roles where rolname='rafii_control_business_projection') then
                create role rafii_control_business_projection nologin nosuperuser bypassrls; end if;
          end$$;
          grant usage on schema rafii_control to rafii_control_reader;
          grant usage on schema rafii_control,public to rafii_control_business_projection;
          create table if not exists rafii_control.workspace_classifications(workspace_id uuid primary key,kind text,environment text)"""


def run(connect, *, sample_export=None, native_concurrency=False):
    with patch.dict(os.environ, {"POSTRIFF_BUDGET_POLICY":"launch-2026-09-24"}):
        return _run(connect, sample_export, native_concurrency)


def _run(connect, sample_export, native_concurrency):
    files = ROOT / "docs/creative-intelligence/examples/timer-study"
    people = {role: str(uuid.uuid4()) for role in ("owner", "editor", "viewer", "foreign","approver")}
    workspace, foreign = str(uuid.uuid4()), str(uuid.uuid4())
    tokens = {role: "fixture-" + user for role, user in people.items()}
    principals = {tokens[role]: user for role, user in people.items()}
    def verify(token):
        if token not in principals:
            raise AlphaError("Test identity unavailable.", 401)
        return principals[token]
    storage = DevAssets()
    hosted = HostedWorkspaceService(connect, verify, assets=storage, credits_enabled=True)
    hosted.video_uploads = VideoUploads(hosted, VideoPolicy(enabled=True), storage=storage)
    provider_calls = []
    class RecordedProvider:
        model, provider = VideoProvider.model, VideoProvider.provider
        estimate = staticmethod(VideoProvider.estimate)
        ambiguous = False
        receipt_cost = None
        output = (files / "original-cut.mp4").read_bytes()
        def submit(self, **args):
            provider_calls.append(args)
            if self.ambiguous:
                raise ProviderError("Uncertain transport outcome.", uncertain=True)
            return "fixture-operation"
        def poll(self, handle):
            assert handle == "fixture-operation"
            return {"state": "completed", "video": self.output, "costUsdMicro": self.receipt_cost}
    provider = RecordedProvider()
    hosted.creative_video = CreativeVideoService(hosted, provider_factory=lambda: provider)
    app = HostedApplication(hosted, None, {}, "local-validation-only")
    with connect() as db:
        for person in people.values():
            db.execute("INSERT INTO auth.users(id) VALUES(%s)", (person,))
            db.execute("INSERT INTO public.pr_profiles(user_id) VALUES(%s)", (person,))
        for wid, owner in ((workspace, people["owner"]), (foreign, people["foreign"])):
            state = initial_phase2_state(wid, owner, "Fixture", "studio", time.time(), execution="synthetic")
            state["brandHub"].update(speaker="Stillwell", subject="a mechanical timer", audience="home cooks")
            state["memoryEgress"] = {"cloud": True}
            state["speaker"].update(activeRevision=1, revisions=[{"revision":1, "profile":{"tone":"Quiet and precise"}}])
            state["learning"] = {"revision": 3, "active":[{"id":"quiet-edit", "status":"active", "statement":"Hold on the dial.",
                                 "scope":{}, "confirmedBy":owner, "evidenceState":"user_confirmed"}]}
            db.execute("INSERT INTO public.pr_workspaces(id,state) VALUES(%s,%s::jsonb)", (wid,json.dumps(state)))
        for role, person in people.items():
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,%s,'active')",
                       (foreign if role=="foreign" else workspace, person,"owner" if role=="foreign" else role))
    base = f"/api/workspaces/{workspace}/creative-video/projects"
    passed = []
    def call(method, path=base, data=None, *, role="owner", expect=200):
        status, _, body = invoke(app, method, path, data, {"Authorization":"Bearer "+tokens[role],
                                  "X-PostRiff-Request":"founder-alpha"})
        assert status == expect, (method, path, expect, status, body)
        return body
    def check(name, value):
        assert value, name
        passed.append(name)
    def upload(name, *, wid=workspace, role="owner"):
        raw = (files / name).read_bytes()
        started = hosted.video_uploads.begin(wid, tokens[role], {"mime":"video/mp4", "bytes":len(raw)})["upload"]
        key = started["assetId"]
        storage.put_reserved_video(wid, key+".mp4", raw)
        return hosted.video_uploads.commit(wid, tokens[role], key, {"locationCleared":True})["video"]["assetId"]
    reference = upload("reference.mp4")
    other_workspace = upload("original-2.mp4", wid=foreign, role="foreign")
    originals = [upload(f"original-{i}.mp4") for i in (1,2,3)]
    brief = {"referenceAssetId":reference, "title":"The kitchen timer", "brief":"Show our timer in motion, then invite the viewer to try it.",
             "aspectRatio":"9:16","rightsConfirmed":True,"platform":"Instagram","requestId":uuid.uuid4().hex}
    check("Workspace read and cross-tenant denial", call("GET")["projects"]==[] and call("GET", role="foreign",expect=403)["code"]=="permission_denied")
    call("POST",data=brief,role="viewer",expect=403)
    call("POST",data={**brief,"referenceAssetId":other_workspace},expect=404)
    call("POST",data={**brief,"rightsConfirmed":False},expect=400)
    project = call("POST",data=brief,role="editor",expect=201)["project"]
    path = base+"/"+project["id"]
    call("GET",f"/api/workspaces/{foreign}/creative-video/projects/{project['id']}",role="foreign",expect=404)
    check("Actual analysis recovers two known cuts", [s["startMs"] for s in project["analysis"]["scenes"]]==[0,1250,2750])
    sheet = call("GET", path+"/reference-frames?revision=1&page=0", role="viewer")
    check("A read-only member can inspect private representative frames within the three analyzed shot ranges",
          sheet["totalShots"] == 3 and len(sheet["frames"]) == 3 and
          all(f["jpeg"] and f["startMs"] <= f["timeMs"] < f["endMs"] for f in sheet["frames"]))
    call("GET", path+"/reference-frames?revision=1&page=1", role="viewer", expect=404)
    call("GET", path+"/reference-frames?revision=1&page=0", role="foreign", expect=403)
    check("Approved brand, voice and scoped learning used", project["context"]["brand"]=="Stillwell" and project["context"]["preferences"]==["Hold on the dial."] and project["context"]["tone"]=="Quiet and precise")
    check("Idempotent creation", call("POST",data=brief,expect=201)["project"]["id"]==project["id"])
    call("POST",data={**brief,"title":"Changed"},expect=409)
    call("POST",path+"/render",{"revision":1},expect=409)
    first = project["scenes"][0]["sceneId"]
    scene_req = {"revision":1,"sceneId":first}
    settings = {"mode":"manual","model":provider.model,"audio":"generated","level":"balanced"}
    def quoted(endpoint, *, revision=1, options=None, role="owner"):
        spec = {"revision":revision,"sceneId":first}
        view = call("POST", endpoint+"/quote", {**spec,"settings":options or settings}, role=role)["quote"]
        assert view["eligible"] and view["id"] and view["expiresAt"] > time.time(), (view.get("reason"), view.get("limitations"))
        return {**spec,"quoteId":view["id"],"confirmed":True}
    def take(endpoint, request, *, expected=200):
        return call("POST", endpoint+"/generate", request, expect=expected)
    invalid = {**scene_req,"quoteId":str(uuid.uuid4()),"confirmed":True}
    call("POST",path+"/quote",{**scene_req,"settings":settings},role="editor",expect=403)
    call("POST",path+"/generate",{**invalid,"maxUsdMicro":1},expect=400)
    call("POST",path+"/generate",invalid,expect=409)
    rejected = call("POST",path+"/quote",{**scene_req,"settings":settings})["quote"]
    check("An allowance-only workspace can inspect a price but cannot authorize paid footage", rejected["id"] is None and not rejected["eligible"] and not provider_calls)
    with connect() as db:
        hosted.ledger.ensure_entitlement(db.cursor(), workspace, None)
        terms = {"writingBatches":10, "mediaCredits":0, "members":3, "connectedAccounts":3, "storageMb":200, "creditPolicy":POLICY_VERSION}
        db.execute("""INSERT INTO public.pr_plan_terms(id,plan,version,label,price_cents,status,entitlements)
                      VALUES('video-qa-credits','studio',998,'Synthetic credit fixture',0,'active',%s::jsonb)""", (json.dumps(terms),))
        db.execute("UPDATE public.pr_entitlements SET plan_terms_id='video-qa-credits' WHERE workspace_id=%s", (workspace,))
        hosted.ledger.credits.grant(db.cursor(), workspace, people["owner"], "video-qa-funding", 1_000_000, None)
    approve_budgets(connect, workspace)
    limited = call("POST",path+"/quote",{**scene_req,"settings":{**settings,"maxMilliCredits":1}})["quote"]
    check("Role and budget refusal precede provider dispatch", limited["id"] is None and limited["estimatedMilliCredits"]==120000 and not provider_calls)
    generation = quoted(path)
    replacement = quoted(path)
    take(path,generation,expected=409)
    generation = replacement
    call("POST",path+"/generate",generation,role="foreign",expect=403)
    with connect() as db:
        db.execute("UPDATE public.pr_creative_video_quotes SET expires_at=now()-interval '1 second' WHERE id=%s", (generation["quoteId"],))
    take(path,generation,expected=409)
    generation = quoted(path)
    check("Superseded, expired and cross-tenant quotes cannot dispatch", not provider_calls)
    whole = call("POST",path+"/plan",{"revision":1,"settings":{"mode":"hybrid","level":"balanced","maxMilliCredits":240000},
        "sceneSettings":{first:{"mode":"manual","model":"storyboard-v1","level":"draft"}}})
    check("Hybrid planning prices different sources within one whole-project budget",
          whole["totalMilliCredits"]==240000 and [r["mediaKind"] for r in whole["scenes"]]==["composed","generated","generated"])
    over_plan = call("POST",path+"/plan",{"revision":1,"settings":{"level":"balanced","maxMilliCredits":150000}})
    check("An incomplete funding plan names the missing shots and never issues spending authority",over_plan["totalMilliCredits"] is None and over_plan["unpricedScenes"]==2)
    with connect() as db:
        db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{memoryEgress}',%s::jsonb) WHERE id=%s",
                   (json.dumps({"cloud":False}),workspace))
    call("POST",path+"/generate",generation,expect=403)
    with connect() as db:
        db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{memoryEgress}',%s::jsonb) WHERE id=%s",
                   (json.dumps({"cloud":True}),workspace))
    generated = call("POST",path+"/generate",generation)["project"]["scenes"][0]
    call("POST",path+"/generate",generation)
    check("Approval and reserve precede exactly one fixture submit",generated["generation"]["state"]=="pending" and len(provider_calls)==1)
    check("Approved brand memory present in actual adapter arguments","Hold on the dial." in provider_calls[0]["prompt"] and "Stillwell" in provider_calls[0]["prompt"])
    edit_first = {"revision":1,"scenes":[{"sceneId":first,"direction":"New take"}]}
    call("POST",path+"/edit",edit_first,expect=409)
    finished = call("POST",path+"/poll",{"revision":1,"sceneId":first})["project"]
    finished_again = call("POST",path+"/poll",{"revision":1,"sceneId":first})["project"]
    check("Provider double result stored once with unknown invoice", finished["scenes"][0]["clipOrigin"]=="generated" and
          finished_again["scenes"][0]["clipId"]==finished["scenes"][0]["clipId"] and finished["scenes"][0]["generation"]["actualUsdMicro"] is None)
    patches = [{"sceneId":s["sceneId"], "clipId":originals[i],"clipRightsConfirmed":True,"caption":f"Beat {i+1}"} for i,s in enumerate(project["scenes"])]
    call("POST",path+"/edit",{"revision":1,"scenes":[{**patches[0],"clipId":other_workspace}]},expect=404)
    changed = call("POST",path+"/edit",{"revision":1,"scenes":patches})["project"]
    check("Saved a targeted editorial revision", changed["revision"]==2)
    call("POST",path+"/edit",edit_first,expect=409)
    with_output = call("POST",path+"/render",{"revision":2})["project"]
    old = with_output["export"]
    from creative_video_performance_cases import exercise as verify_performance, owned_link
    verify_performance(connect, call, check, path, workspace, old)
    owned_link(connect, call, check, hosted, workspace, people["owner"], brief, old["assetId"])
    repeat = call("POST",path+"/render",{"revision":2})["project"]["export"]
    check("Real H.264 export retained across repeated request", old==repeat and old["manifest"]["frameCount"]==96)
    frame_path = path + "/frame?revision=2&frame=30"
    frame_status, frame_headers, png = invoke(app, "GET", frame_path, headers={"Authorization":"Bearer "+tokens["viewer"]})
    check("A viewer can download the exact picture frame from a saved revision",
          frame_status == 200 and frame_headers["Content-Type"] == "image/png" and "no-store" in frame_headers["Cache-Control"]
          and png.startswith(b"\x89PNG\r\n\x1a\n") and png[16:24] == (720).to_bytes(4, "big") + (1280).to_bytes(4, "big"))
    call("GET", frame_path, role="foreign", expect=403)
    call("GET", path+"/frame?revision=2&frame=96", role="viewer", expect=400)
    check("Actual stored bytes agree with the MP4 receipt", old["manifest"]["sha256"] ==
          hashlib.sha256(storage.get(workspace,"video",old["assetId"]+".mp4")).hexdigest())
    new_clip = upload("revised-intro.mp4")
    revised = call("POST",path+"/edit",{"revision":2,"scenes":[{**patches[0],"clipId":new_clip,"caption":"New opening"}]})["project"]
    revised = call("POST",path+"/render",{"revision":revised["revision"]})["project"]
    check("Revised export differs, other asset hashes and timings preserved",old["manifest"]["sha256"] != revised["export"]["manifest"]["sha256"] and
          old["manifest"]["scenes"][1:] == revised["export"]["manifest"]["scenes"][1:])
    check("Earlier editorial revision and export can be reopened",call("GET",path+"?revision=2",role="viewer")["project"]["export"]==old)
    batch = {"revision": 2, "requestId": uuid.uuid4().hex, "reuseRightsConfirmed": True,
             "targets": [{"platform": "Instagram", "aspectRatio": "1:1"}, {"platform": "YouTube", "aspectRatio": "16:9"}]}
    call("POST", path+"/variants", batch, role="viewer", expect=403)
    call("POST", path+"/variants", {**batch, "reuseRightsConfirmed": False}, expect=400)
    variants = call("POST", path+"/variants", batch, role="editor")["projects"]
    check("Retrying a two-platform batch returns the original two independent projects",
          len(variants) == 2 and variants == call("POST", path+"/variants", batch, role="editor")["projects"])
    call("POST", path+"/variants", {**batch, "targets": batch["targets"][:1]}, role="editor", expect=409)
    for result, target in zip(variants, batch["targets"]):
        variant_path = base + "/" + result["id"]
        variant = call("GET", variant_path)["project"]
        check("Variant reuses exact historical footage " + target["platform"], variant["origin"] == {"projectId": project["id"], "revision": 2}
              and variant["aspectRatio"] == target["aspectRatio"] and variant["platform"] == target["platform"]
              and [s["clipId"] for s in variant["scenes"]] == originals and variant["export"] is None)
        rendered = call("POST", variant_path+"/render", {"revision": 1})["project"]["export"]["manifest"]
        check("Variant renders its own frame with the same three source hashes " + target["platform"],
              rendered["aspectRatio"] == target["aspectRatio"] and
              [s["clipSha256"] for s in rendered["scenes"]] == [s["clipSha256"] for s in old["manifest"]["scenes"]])
    check("Batch variants leave source revision and provider submissions unchanged",
          call("GET", path)["project"]["revision"] == 3 and len(provider_calls) == 1)
    call("GET",path,role="foreign",expect=403)
    fresh = call("POST",path+"/edit",{"revision":3,"scenes":[{"sceneId":first,"retake":True}]})["project"]
    check("Preparing another take preserves shot direction and spends nothing", fresh["scenes"][0]["direction"]==revised["scenes"][0]["direction"]
          and fresh["scenes"][0]["clipId"] is None and len(provider_calls)==1)
    provider.ambiguous=True
    generation = quoted(path,revision=4)
    take(path, generation, expected=502)
    unknown = call("POST",path+"/generate",{**generation,"revision":4})["project"]["scenes"][0]
    check("An ambiguous submit remains held and is never replayed",unknown["generation"]["state"]=="unknown" and len(provider_calls)==2)
    with connect() as db:
        counts=dict(db.execute("SELECT cost_state,count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s GROUP BY cost_state",(workspace,)).fetchall())
        check("Two reservations and both unknown actual costs retained in native ledger",int(counts["estimated"])==2 and int(counts["estimated_unknown"])==2)
        for table in ("pr_creative_video_projects","pr_creative_video_revisions","pr_creative_video_quotes","pr_creative_video_model_policy"):
            row=db.execute("SELECT has_table_privilege('authenticated',%s,'SELECT'),has_table_privilege('anon',%s,'INSERT')",(table,table)).fetchone()
            check(table+" service-only",list(row)==[False,False])
        rid = db.execute("""SELECT body->>'reservationId' FROM public.pr_jobs WHERE workspace_id=%s
                          AND body->>'state'='unknown'""", (workspace,)).fetchone()[0]
        hosted.ledger.reconcile_unknown(db.cursor(), workspace, rid, "failed", 12340,
                                        operator="test-operator", evidence="synthetic invoice for this fixture")
    settled = call("GET",path)["project"]["scenes"][0]["generation"]
    check("Canonical settlement exposes the known cost and frees the scene", settled["actualUsdMicro"]==12340 and
          settled["state"]=="failed" and settled["reason"]=="submission_reconciled_without_clip")
    provider.ambiguous = False
    crash = call("POST", data={**brief, "requestId":uuid.uuid4().hex}, expect=201)["project"]
    crash_path = base+"/"+crash["id"]
    generation = quoted(crash_path)
    take(crash_path,generation)
    with connect() as db:
        db.execute("""UPDATE public.pr_jobs SET body=(body - 'operation') || '{"state":"submitting"}'::jsonb,
                      created_at=now()-interval '6 minutes' WHERE workspace_id=%s AND body->>'projectId'=%s""", (workspace,crash["id"]))
    before = len(provider_calls)
    lost = call("POST", crash_path+"/poll", {"revision":1,"sceneId":first})["project"]["scenes"][0]["generation"]
    call("POST", crash_path+"/generate", generation)
    check("An interrupted acknowledgement becomes an unresolved cost without replay", lost["state"]=="unknown" and len(provider_calls)==before)
    for category in ("invalid media", "withdrawn consent"):
        another = call("POST", data={**brief, "requestId":uuid.uuid4().hex}, expect=201)["project"]
        endpoint = base + "/" + another["id"]
        run_scene = quoted(endpoint)
        call("POST", endpoint+"/generate", run_scene)
        if category == "invalid media":
            provider.output = b"this operation returned no movie"
            expected_reason = "provider_output_unusable"
        else:
            with connect() as db:
                db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{memoryEgress}',%s::jsonb) WHERE id=%s",
                           (json.dumps({"cloud":False}),workspace))
            expected_reason = "authorization_changed"
        rejected = call("POST", endpoint+"/poll", {"revision":1, "sceneId":run_scene["sceneId"]})["project"]["scenes"][0]
        check("Completed or recalled take safely reconciled for " + category, rejected["clipId"] is None and
              rejected["generation"]["state"] == "failed" and rejected["generation"]["reason"] == expected_reason)
    with connect() as db:
        db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{memoryEgress}',%s::jsonb) WHERE id=%s",
                   (json.dumps({"cloud":True}),workspace))
    # Outside providers are disabled. Exercise the real Studio entry points, local renderer,
    # public approval, private Library and export with an editor who cannot spend credits.
    hosted.creative_video = CreativeVideoService(hosted)
    brief_only = {**brief, "requestId":uuid.uuid4().hex, "referenceAssetId":None, "rightsConfirmed":False,
                  "title":"Stillwell tea study", "brief":"Introduce our tea with a clear hook, a demonstration and an invitation."}
    local = call("POST",data=brief_only,role="editor",expect=201)["project"]
    local_path = base+"/"+local["id"]
    with connect() as db:
        original_balance = hosted.ledger.credits.view(db.cursor(), workspace)["availableMilliCredits"]
    mid = local["scenes"][1]["sceneId"]
    last = local["scenes"][2]["sceneId"]
    calendar = call("POST",data={**brief_only, "requestId":uuid.uuid4().hex,"aspectRatio":"1:1"},role="editor",expect=201)["project"]
    check("Square project accepts a real local storyboard profile",call("POST",base+"/"+calendar["id"]+"/quote",
            {"revision":1,"sceneId":first,"settings":{"level":"draft"}},role="editor")["quote"]["outputProfile"]["width"]==720)
    local = call("POST",local_path+"/edit",{"revision":1,"scenes":[{"sceneId":mid,"durationMs":1500,"clipId":originals[1],"clipRightsConfirmed":True},
        {"sceneId":last,"durationMs":1250,"clipId":originals[2],"clipRightsConfirmed":True}]},role="editor")["project"]
    local_req = {"revision":local["revision"], "sceneId":first}
    draft = call("POST",local_path+"/quote",{**local_req,"settings":{"level":"draft"}},role="editor")["quote"]
    check("Brief-only Draft quote with Google and Runway disabled", draft["id"] and draft["maximumMilliCredits"]==0 and draft["mediaKind"]=="composed")
    local_approval = {**local_req,"quoteId":draft["id"],"confirmed":True}
    call("POST",local_path+"/generate",local_approval,role="editor")
    check("Reopen only resumes the saved local take",call("GET",local_path,role="editor")["project"]["scenes"][0]["generation"]["state"]=="pending")
    tick = hosted.creative_video.worker_tick()
    check("Background worker harvests an authorized saved operation with no user session",tick["state"]=="polled")
    result = call("GET",local_path,role="editor")["project"]["scenes"][0]
    check("Real composed motion is private, decoded and distinguished from generated output",result["clipOrigin"]=="composed" and result["generation"]["actualUsdMicro"]==0)
    decision = call("POST",local_path+"/review",{**local_req,"accepted":True},role="editor")["project"]["scenes"][0]
    check("Explicit creative acceptance is saved independently of technical completion",decision["generation"]["accepted"] is True)
    movie = call("POST",local_path+"/render",{"revision":local["revision"]},role="editor")["project"]["export"]
    local_bytes = storage.get(workspace,"video",movie["assetId"]+".mp4")
    check("Composed and reused shots export through the private Library without new paid calls",
          movie["manifest"]["sha256"]==hashlib.sha256(local_bytes).hexdigest() and movie["manifest"]["frameCount"]==162)
    if sample_export:
        Path(sample_export).write_bytes(local_bytes)
    with connect() as db:
        check("Local media leaves the canonical credit balance intact",hosted.ledger.credits.view(db.cursor(), workspace)["availableMilliCredits"]==original_balance)
    free_project = call("POST",data={**brief_only,"requestId":uuid.uuid4().hex},role="editor",expect=201)["project"]
    free_path = base+"/"+free_project["id"]
    free_approval = quoted(free_path,options={"level":"draft"},role="editor")
    call("POST",free_path+"/generate",free_approval,role="editor")
    with connect() as db:
        db.execute("""UPDATE public.pr_jobs SET body=(body-'operation') || '{"state":"submitting"}'::jsonb,
                   created_at=now()-interval '6 minutes' WHERE workspace_id=%s AND body->>'quoteId'=%s""",(workspace,free_approval["quoteId"]))
    check("An interrupted free storyboard can be replaced without a nonexistent ledger settlement",hosted.creative_video.worker_tick()["state"]=="recovered_claim"
          and call("GET",free_path,role="editor")["project"]["scenes"][0]["generation"]["state"]=="failed")
    blocked_project = call("POST",data={**brief_only,"requestId":uuid.uuid4().hex},role="editor",expect=201)["project"]
    blocked_path = base+"/"+blocked_project["id"]
    blocked_auth = quoted(blocked_path,options={"level":"draft"},role="editor")
    call("POST",blocked_path+"/generate",blocked_auth,role="editor")
    with connect() as db:
        db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(workspace,people["editor"]))
    revoked_second = call("POST",blocked_path+"/poll",scene_req)["project"]["scenes"][0]
    check("Interactive owner poll rechecks the original editor before attaching footage",revoked_second["clipId"] is None and
          revoked_second["generation"]["reason"]=="authorization_changed")
    with connect() as db:
        db.execute("UPDATE public.pr_memberships SET role='editor' WHERE workspace_id=%s AND user_id=%s",(workspace,people["editor"]))
    background_project = call("POST",data={**brief_only,"requestId":uuid.uuid4().hex},role="editor",expect=201)["project"]
    blocked_path=base+"/"+background_project["id"]
    free_approval=quoted(blocked_path,options={"level":"draft"},role="editor")
    call("POST",blocked_path+"/generate",free_approval,role="editor")
    with connect() as db:
        db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(workspace,people["editor"]))
    check("A revoked editor cannot materialize a saved operation in the background",hosted.creative_video.worker_tick()["state"]=="authorization_changed"
          and call("GET",blocked_path)["project"]["scenes"][0]["clipId"] is None)
    with connect() as db:
        db.execute("UPDATE public.pr_memberships SET role='editor' WHERE workspace_id=%s AND user_id=%s",(workspace,people["editor"]))
    hosted.creative_video = CreativeVideoService(hosted, provider_factory=lambda:provider)
    # Reusing the same provider fixture with a reported cost verifies real settlement on the canonical ledger.
    settled_project = call("POST",data={**brief,"requestId":uuid.uuid4().hex},expect=201)["project"]
    settled_path = base+"/"+settled_project["id"]
    provider.output = (files/"original-cut.mp4").read_bytes()
    provider.receipt_cost = 205000
    approval = quoted(settled_path)
    take(settled_path,approval)
    with connect() as db:
        held = hosted.ledger.credits.view(db.cursor(),workspace)["availableMilliCredits"]
    scene_done = call("POST",settled_path+"/poll",scene_req)["project"]["scenes"][0]
    call("POST",settled_path+"/poll",scene_req)
    take(settled_path,approval)
    with connect() as db:
        after = hosted.ledger.credits.view(db.cursor(),workspace)["availableMilliCredits"]
    check("Known cost settles exactly once and releases the unused hold",scene_done["generation"]["actualUsdMicro"]==205000 and after-held==120000-millicredits(205000))
    provider.receipt_cost = None
    check("Export preserves the origin of uploaded and procedural footage",
          [s["sourceMediaKind"] for s in movie["manifest"]["scenes"]]==["composed","user-provided","user-provided"])
    from postriff_phase2 import creative_video_runway
    runway_env = {"RAFII_CREATIVE_VIDEO_PROVIDERS":"runway", "RAFII_CREATIVE_VIDEO_RUNWAY_MODELS":"veo3.1_fast,gen4.5",
                  "RAFII_CREATIVE_VIDEO_RUNWAY_KEY":"synthetic-test-only"}
    hosted.creative_video = CreativeVideoService(hosted, provider_environment=runway_env)
    rq = call("POST",data={**brief, "requestId":uuid.uuid4().hex},expect=201)["project"]
    rq_path = base+"/"+rq["id"]
    partner = {"level":"balanced","mode":"manual","model":"veo3.1_fast","audio":"generated"}
    partner_approval=quoted(rq_path, options=partner, role="approver")
    handle = str(uuid.uuid4())
    sent=[]
    def fake_request(method, url, body, key):
        assert key=="synthetic-test-only"
        sent.append(method)
        if method=="POST":
            return 200,{"id":handle}
        assert url.endswith(handle)
        if method=="DELETE":
            return 204,{}
        return 200,{"id":handle,"status":"CANCELED","cost":{"credits":7}}
    with patch.object(creative_video_runway,"_request",fake_request):
        call("POST",rq_path+"/generate",partner_approval,role="approver")
        call("POST",rq_path+"/cancel",scene_req,role="foreign",expect=403)
        call("POST",rq_path+"/cancel",scene_req)
        call("POST",rq_path+"/cancel",scene_req)
        cancelled = call("POST",rq_path+"/poll",scene_req)["project"]["scenes"][0]["generation"]
    with connect() as db:
        recorded = db.execute("SELECT body->'providerUsage' FROM public.pr_jobs WHERE workspace_id=%s AND body->>'quoteId'=%s",
                              (workspace,partner_approval["quoteId"])).fetchone()[0]
    check("Runway gateway cancellation and unknown USD retain exact reported units on the same operation",
          sent==["POST","DELETE","GET"] and cancelled["state"]=="cancelled" and cancelled["actualUsdMicro"] is None
          and recorded["quantity"]==7 and recorded["costSource"]=="provider_invoice_pending" and not recorded["verifiedUsdMicroPerUnit"])
    # Interrupt between a verified usage record and output attachment, then expire the remote
    # download. Recovery must use the original saved units and never manufacture a new charge.
    runway_env["RAFII_CREATIVE_VIDEO_RUNWAY_VERIFIED_UNIT_USD_MICRO"]="9600"
    hosted.creative_video = CreativeVideoService(hosted, provider_environment=runway_env)
    recovery = call("POST",data={**brief,"requestId":uuid.uuid4().hex},expect=201)["project"]
    recovery_path=base+"/"+recovery["id"]
    reviewed=quoted(recovery_path,options={"mode":"manual","model":"gen4.5","level":"balanced"},role="approver")
    with patch.object(creative_video_runway,"_request",fake_request):
        call("POST",recovery_path+"/generate",reviewed,role="approver")
    with connect() as db:
        saved=db.execute("SELECT body FROM public.pr_jobs WHERE workspace_id=%s AND body->>'quoteId'=%s",(workspace,reviewed["quoteId"])).fetchone()[0]
        receipt={"provider":"runway","unit":"provider_credit","quantity":12,"verifiedUsdMicroPerUnit":9600,
                 "pricingVersion":saved["pricingVersion"],"costUsdMicro":115200,"costSource":"provider_task_usage"}
    def concurrent_receipt_before_response(*_):
        # The polling caller already holds a stale copy. A companion worker records units
        # in another committed transaction before the caller receives the expired task.
        with connect() as db:
            hosted.creative_video.store.remember_usage(db.cursor(),workspace,saved,receipt)
        return 404,{}
    with patch.object(creative_video_runway,"_request",concurrent_receipt_before_response):
        expired=call("POST",recovery_path+"/poll",scene_req)["project"]["scenes"][0]["generation"]
    check("An overlapping provider receipt survives a stale poll and a subsequently expired output",expired["actualUsdMicro"]==115200
          and expired["state"]=="failed" and expired["settlementState"]=="released")
    hosted.creative_video = CreativeVideoService(hosted,provider_factory=lambda:provider)
    with connect() as db:
        hosted.ledger.credits.grant(db.cursor(),workspace,people["owner"],"headroom-for-open-job-limit",1_000_000,None)
    candidates = []
    for _ in range(3):
        item = call("POST", data={**brief, "requestId":uuid.uuid4().hex}, expect=201)["project"]
        candidates.append(base + "/" + item["id"])
    for endpoint in candidates[:2]:
        take(endpoint,quoted(endpoint))
    admitted = len(provider_calls)
    take(candidates[2],quoted(candidates[2]),expected=429)
    check("Three outstanding takes exhaust the workspace limit before another submission", len(provider_calls)==admitted)
    with connect() as db:
        db.execute("""INSERT INTO public.pr_creative_video_model_policy(environment,model,actor,paused)
            VALUES('local',%s,%s,true)""",(provider.model,people["owner"]))
    disabled = call("GET",candidates[2])["provider"]["models"]
    check("Pausing one provider leaves independent composition available",not next(m["available"] for m in disabled if m["id"]==provider.model)
          and next(m["available"] for m in disabled if m["id"]=="storyboard-v1"))
    # The general application harness omits Founder Control. Install only this projection's
    # actual prerequisites in the disposable database; test the actual migration and restricted reader.
    with connect() as db:
        db.execute("SET LOCAL ROLE rafii_control_reader")
        db.execute("SELECT set_config('rafii_control.environment','local',true)")
        rows = db.execute('SELECT model,plan,"actualUsdMicro","consumedMilliCredits","reservedMilliCredits","pendingReconciliations",accepted FROM rafii_control.creative_video_usage').fetchall()
        paid = next(row for row in rows if row[0]==provider.model)
        local_row = next(row for row in rows if row[0]=="storyboard-v1")
        check("Restricted founder aggregation reconciles known spend, held credits and explicit acceptance",
              int(paid[2])==217340 and int(paid[3])==millicredits(205000) and int(paid[4])>0 and int(paid[5])>0 and int(local_row[6])==1)
        check("Founder reader and projection owner cannot read raw job bodies", db.execute("""
            SELECT NOT has_column_privilege('rafii_control_reader', 'public.pr_jobs', 'body', 'SELECT')
               AND NOT has_column_privilege('rafii_control_business_projection', 'public.pr_jobs', 'body', 'SELECT')
        """).fetchone()[0])
        check("Only the projection role can read the intermediate job fields", db.execute("""
            SELECT has_table_privilege('rafii_control_business_projection', 'rafii_control.creative_video_job_metrics', 'SELECT')
               AND NOT EXISTS (
                   SELECT 1 FROM unnest(ARRAY['anon','authenticated','service_role','rafii_control_reader','rafii_control_session']) AS r(role_name)
                   WHERE has_any_column_privilege(r.role_name, 'rafii_control.creative_video_job_metrics', 'SELECT')
               )
        """).fetchone()[0])
    # Two independent callers may both obtain quotes against the same remaining balance.
    # Only the ordinary PostgreSQL harness exercises concurrent native transactions. Embedded
    # PostgreSQL deliberately uses two pre-issued quotes in sequence and labels that distinction.
    other_root = f"/api/workspaces/{foreign}/creative-video/projects"
    with connect() as db:
        db.execute("UPDATE public.pr_creative_video_model_policy SET paused=false WHERE environment='local' AND model=%s",(provider.model,))
        hosted.ledger.ensure_entitlement(db.cursor(),foreign,None)
        db.execute("UPDATE public.pr_entitlements SET plan_terms_id='video-qa-credits' WHERE workspace_id=%s",(foreign,))
        hosted.ledger.credits.grant(db.cursor(),foreign,people["foreign"],"exact-one-take",120000,None)
        state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s",(foreign,)).fetchone()[0]
        state["memoryEgress"]={"cloud":True}
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s",(json.dumps(state),foreign))
    approve_budgets(connect, foreign)
    contenders=[]
    for _ in range(2):
        fresh = call("POST",other_root, {**brief_only,"requestId":uuid.uuid4().hex},role="foreign",expect=201)["project"]
        lane = other_root+"/"+fresh["id"]
        contenders.append((lane, quoted(lane,role="foreign")))
    def attempt(candidate):
        lane, auth = candidate
        status,_,_=invoke(app,"POST",lane+"/generate",auth,{"Authorization":"Bearer "+tokens["foreign"],
                         "X-PostRiff-Request":"founder-alpha"})
        return status
    previous = len(provider_calls)
    if native_concurrency:
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        gate=Barrier(2)
        def race(candidate):
            gate.wait(timeout=5)
            return attempt(candidate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(race,contenders))
    else:
        statuses=list(map(attempt,contenders))
    with connect() as db:
        left=hosted.ledger.credits.view(db.cursor(),foreign)["availableMilliCredits"]
    check("Competing preissued quotes cannot both consume the last 120 credits",sorted(statuses)==[200,402] and len(provider_calls)-previous==1 and left==0)
    # Only the final transport is replaced: exercise a real decoded photo, scoped owner grant, quote, ledger and Veo serializer.
    import base64
    import io
    from PIL import Image
    with connect() as db:
        hosted.ledger.credits.grant(db.cursor(), foreign, people["foreign"], "first-frame-fixture", 240000, None)
    def frame_permission(wid, role, enabled, expect=200):
        rev = hosted.repository.get(wid, tokens[role])["revision"]
        return call("POST", f"/api/workspaces/{wid}/actions", {"expectedRevision":rev, "action":"media_egress",
                    "payload":{"cloud":enabled, "confirmed":True, "purpose":"video_first_frame"}}, role=role, expect=expect)
    frame_permission(workspace, "approver", True, 403)
    with io.BytesIO() as png:
        Image.new("RGB", (720, 1280), (37, 90, 120)).save(png, format="PNG")
        uploaded = hosted.upload_media(foreign, tokens["foreign"], hosted.repository.get(foreign, tokens["foreign"])["revision"],
                                       {"data":base64.b64encode(png.getvalue()).decode("ascii")})
    photo = next(a for a in reversed(uploaded["state"]["phase2"]["assets"]) if a["mime"] == "image/jpeg")
    frame_options = {**settings, "firstFrameAssetId":photo["id"], "firstFrameConsent":True}
    fixture = VideoProvider("fixture-project", "fixture-token")
    wire = []
    def capture_image_request(_path, body, _token, _limit):
        wire.append(body)
        return 200, {"name":fixture.model_path + "/operations/first-frame"}
    fixture.transport = capture_image_request
    hosted.creative_video = CreativeVideoService(hosted, provider_factory=lambda: fixture)
    project = call("POST", other_root, {**brief_only,"requestId":uuid.uuid4().hex}, role="foreign", expect=201)["project"]
    lane = other_root + "/" + project["id"]
    call("POST",lane+"/quote",{**scene_req,"settings":frame_options},role="foreign",expect=403)
    frame_permission(foreign, "foreign", True)
    check("Workspace allows Veo opening frames without enabling photo reading",
          not hosted.repository.get(foreign, tokens["foreign"])["state"]["mediaEgress"]["cloud"])
    frame_quote = quoted(lane, options=frame_options, role="foreign")
    saved_bytes = storage.get(foreign, "media", photo["objectName"])
    storage.objects[(foreign, "media", photo["objectName"])] = b"x" * len(saved_bytes)
    call("POST", lane+"/generate", frame_quote, role="foreign", expect=409)
    storage.objects[(foreign, "media", photo["objectName"])] = saved_bytes
    with connect() as db:
        check("Changed first-frame bytes block dispatch and credit reservation",
              not wire and hosted.ledger.credits.view(db.cursor(), foreign)["availableMilliCredits"] == 240000)
    call("POST", lane+"/generate", frame_quote, role="foreign")
    call("POST", lane+"/generate", frame_quote, role="foreign")
    check("Exactly one Veo wire request contains the pinned Library rendition",
          len(wire) == 1 and wire[0]["instances"][0]["image"] == {"mimeType":"image/jpeg",
          "bytesBase64Encoded":base64.b64encode(saved_bytes).decode("ascii")} and wire[0]["parameters"]["sampleCount"] == 1)
    frame_permission(foreign, "foreign", False)
    stopped = call("POST", lane+"/poll", scene_req, role="foreign")["project"]["scenes"][0]
    check("Revoking the image grant blocks polling and Library attachment",
          stopped["generation"]["reason"] == "authorization_changed" and not stopped["clipId"] and len(wire) == 1)
    result = {"scope":"WSGI, PostgreSQL, real media, synthetic storage, identities and provider", "passed":passed, "count":len(passed),
              "nativeMultiConnectionRace":native_concurrency, "gatewayFixtureSubmits":2, "providerFixtureSubmits":len(provider_calls),
              "firstFrameFixtureSubmits":len(wire), "externalProviderCalls":0,
              "localMixedExportSha256":movie["manifest"]["sha256"], "firstExportSha256":old["manifest"]["sha256"], "revisedExportSha256":revised["export"]["manifest"]["sha256"]}
    print(json.dumps(result,indent=2))
    return result


if __name__=="__main__":
    import psycopg
    dsn = os.environ["POSTRIFF_TEST_DSN"]
    if "host=127.0.0.1" not in dsn.split():
        raise SystemExit("This fixture requires the disposable local PostgreSQL test harness.")
    with psycopg.connect(dsn, client_encoding="utf8") as db:
        db.execute((ROOT / "migrations/postriff/020_credit_quotes.sql").read_text())
        db.execute(FOUNDER_TEST_PREREQUISITES)
        db.execute((ROOT / "migrations/postriff/133_founder_creative_video.sql").read_text())
    run(lambda: psycopg.connect(dsn, client_encoding="utf8"), native_concurrency=True)
