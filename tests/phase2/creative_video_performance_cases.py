"""Fixture records exercise read-only revision attribution in the existing disposable PostgreSQL suite."""
import json

from postriff_phase2 import creative_video_performance as performance
from postriff_phase2.youtube.service import fingerprint


def exercise(connect, call, check, path, workspace, receipt):
    endpoint = path + "/performance?revision=2"
    call("GET", path + "/performance", expect=400)
    call("GET", endpoint + "&revision=1", expect=400)
    call("GET", endpoint, role="foreign", expect=403)
    check("Older unrendered revision has no post attribution",
          call("GET", path + "/performance?revision=1")["state"] == "unrendered")
    check("Actual export with no job has no reported performance", call("GET", endpoint)["state"] == "unlinked")
    connection, job_id = "performance-connection", "performance-test-job"
    with connect() as db:
        state, = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace,)).fetchone()
        original = json.dumps(state)
        job = {"id":job_id, "state":"verified", "verification":{"at":1800,"method":"provider_lookup"},
               "providerReference":"published-video", "manifest":{"workspaceId":workspace, "execution":"hosted-live",
               "platform":"Kuaishou","channelId":connection,"providerAccountId":"test-account",
               "media":[{"id":receipt["assetId"],"hash":receipt["manifest"]["sha256"],"rightsConfirmed":True}]}}
        state["phase2"]["jobs"].append(job)
        state["phase2"]["channels"].append({"id":connection, "platform":"Kuaishou"})
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state),workspace))
        db.execute("""INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,
                      access_ciphertext,key_id,scopes) VALUES(%s,%s,'kuaishou','test-account','fixture','fixture','{}')""",
                   (workspace, connection))
    result = call("GET", endpoint, role="viewer")
    check("Exact video publication job with no stored metrics stays unmeasured",
          [(p["jobId"],p["providerPostId"],p["metrics"]) for p in result["posts"]] == [(job_id,"published-video",[])])
    with connect() as db:
        db.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s",
                   (workspace, connection))
    check("Disconnect hides previously linked publication", call("GET", endpoint)["state"] == "unlinked")
    # This fixture predates a native Instagram video publisher. Exercise the existing metric-reader SQL separately.
    with connect() as db:
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (original, workspace))
        cur = db.cursor()
        cur.execute("""INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level)
                       VALUES(%s,%s,'analytics','Direct')""", (workspace, connection))
        for exact_job, metric, value, available in ((job_id,"views",0,"available"),(job_id,"shares",None,"unavailable"),
                                                    ("other-job","likes",900,"available")):
            cur.execute("""INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,
                        job_id,metric,value,availability,definition_version,unit,observed_at,period_start,period_end,read_offset)
                        VALUES(%s,%s,'instagram','published-video',%s,%s,%s,%s,'native-test','count',
                               to_timestamp(8050),to_timestamp(5000),to_timestamp(8000),'1h')""",
                        (workspace, connection, exact_job, metric, value, available))
        readings = performance._growth_metrics(cur, workspace, connection, 'instagram', 'published-video', job_id,
                                               performance.NATIVE_ANALYTICS_SCOPES['instagram'])
        check("Native readings keep zero, unavailable, recorded dates and exact publishing job",
              [(r['name'],r['value'],r['periodStart'],r['periodEnd'],r['readOffset']) for r in readings]
              == [('shares',None,5000,8000,'1h'), ('views',0,5000,8000,'1h')])
        query = {"startDate":"2026-10-01","endDate":"2026-10-02","resource":"analytics","report":"daily","videoId":"video-1234"}
        report = {"source":"YouTube Analytics API","channelId":"account","report":"daily","ingestedAt":2000,
                  "coverage":{"startDate":query["startDate"],"endDate":query["endDate"]},
                  "data":{"columnHeaders":[{"name":"day"},{"name":"views"}],"rows":[[query["startDate"],8]]}}
        key = "analytics:" + fingerprint(query)
        cur.execute("""INSERT INTO public.pr_youtube_cache(workspace_id,connection_id,cache_key,source,data,expires_at)
                       VALUES(%s,%s,%s,'YouTube Analytics API',%s::jsonb,now()+interval '1 hour')""",
                    (workspace, connection, key, json.dumps(report)))
        native = performance._youtube_metrics(cur, workspace, connection, "account", "video-1234")
        check("YouTube daily cache identifies this video and ignores a different video",
              len(native) == 1 and native[0]['value'] == 8 and not performance._youtube_metrics(cur, workspace, connection, "account", "other"))
        cur.execute("UPDATE public.pr_youtube_cache SET expires_at=now() WHERE workspace_id=%s AND connection_id=%s",
                    (workspace, connection))
        check("Expired YouTube report is unavailable", not performance._youtube_metrics(cur, workspace, connection, "account", "video-1234"))


def owned_link(connect, call, check, hosted, workspace, owner, brief, rendered_asset):
    """Exercise genuine policy acceptance/binding SQL around simulated published YouTube evidence."""
    from types import SimpleNamespace
    from unittest.mock import patch
    from postriff_phase2 import creative_video
    from postriff_phase2.youtube.model import READ, ANALYTICS
    from postriff_phase2.youtube.workspace_provider_data import source

    connection, account, ident = "published-youtube-test", "fixture-account", "0123456Abcd"
    with connect() as db:
        state, = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace,)).fetchone()
        original = json.dumps(state)
        asset = next(a for a in state["phase2"]["assets"] if a["id"] == rendered_asset)
        media = {k:asset[k] for k in ("id","hash","mime","objectName","etag","bucket","bytes")}
        media["rightsConfirmed"] = True
        job = {"id":"fixture-public-youtube", "state":"verified", "providerReference":ident,
               "approvedAt":hosted.clock()-5, "approvedBy":owner, "verification":{"method":"provider_lookup","at":hosted.clock()},
               "manifest":{"workspaceId":workspace, "platform":"YouTube", "channelId":connection,
                           "execution":"hosted-live","providerAccountId":account,"media":[media]},
               "progress":{"stage":"published","privacyStatus":"public","videoId":ident}}
        generation, = db.execute("""INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,
                          scopes,access_ciphertext,key_id) VALUES(%s,%s,'youtube',%s,ARRAY[%s,%s],'fixture','fixture')
                          RETURNING authorization_generation::text""", (workspace,connection,account,READ,ANALYTICS)).fetchone()
        job["youtubeProviderOutput"] = source(workspace, job, generation, hosted.clock())
        state["phase2"]["jobs"].append(job)
        state["phase2"]["channels"].append({"id":connection,"platform":"YouTube"})
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state),workspace))
        policy, = db.execute("""INSERT INTO public.pr_youtube_policy_revisions(privacy_revision,privacy_url,privacy_sha256,
                        terms_revision,terms_url,terms_sha256,approved_by,approval_reference,approved_at,published_at,is_current)
                        VALUES('fixture','https://fixture.example/privacy',%s,'fixture','https://fixture.example/terms',%s,
                               'fixture','isolated integration',now(),now(),true) RETURNING id::text""", ('a'*64,'b'*64)).fetchone()
        acceptance, = db.execute("""INSERT INTO public.pr_youtube_policy_acceptances(workspace_id,user_id,policy_id)
                         VALUES(%s,%s,%s) RETURNING id::text""",(workspace,owner,policy)).fetchone()
        hosted.oauth.youtube_policy.bind(db.cursor(),workspace,connection,{'receiptId':acceptance})

    link = "https://www.youtube.com/watch?v=" + ident + "&si=discard-this"
    projects = "/api/workspaces/" + workspace + "/creative-video/projects"
    endpoint = projects.rsplit("/",1)[0] + "/reference-link"
    new_brief = {**brief, "requestId":"link_intake_authorized", "referenceAssetId":rendered_asset, "referenceLink":link}
    with patch.dict(hosted.oauth.providers, {"youtube":SimpleNamespace(id="youtube",creator_enabled=True)}), \
            patch.object(hosted.oauth,"youtube_public_base_url","https://fixture.example"):
        call("POST", endpoint, {"url":link}, role="foreign", expect=403)
        call("POST", endpoint, {"url":link}, role="viewer", expect=404)  # Has workspace read but no current YouTube policy receipt.
        check("YouTube share resolves to the existing caller-authorized immutable private Library video",
              call("POST", endpoint, {"url":link}) == {"assetId":rendered_asset,"durationSeconds":asset["duration"]})
        call("POST", projects, {**new_brief,"referenceAssetId":brief["referenceAssetId"]}, expect=409)
        linked = call("POST",projects,new_brief,expect=201)["project"]
        replay = call("POST", projects, {**new_brief,"referenceLink":"https://youtu.be/" + ident}, expect=201)
        check("Reference project request normalizes share tracking and stores the confirmed asset",
              replay["project"]["id"] == linked["id"] and linked["referenceAssetId"] == rendered_asset and
              "discard-this" not in json.dumps(linked) and "referenceLink" not in linked and
              "speechTiming" not in linked["analysis"])
        opted_in = call("POST", projects, {**new_brief, "requestId":"link_local_speech_timing",
                                           "speechTimingLanguage":"zh"}, expect=201)["project"]
        check("Explicit speech timing keeps editing usable when the model is unconfigured",
              opted_in["analysis"]["speechTiming"]["reason"] == "model_unavailable")
        analyze = creative_video.analyze_reference
        def revoke_after_decode(raw):
            result = analyze(raw)
            with connect() as db:
                db.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s",
                           (workspace,connection))
            return result
        with patch.object(creative_video,"analyze_reference",side_effect=revoke_after_decode):
            call("POST",projects,{**new_brief,"requestId":"link_revoked_during_intake"},expect=404)
        call("POST",endpoint,{"url":link},expect=404)
    with connect() as db:
        failed, = db.execute("SELECT count(*) FROM public.pr_creative_video_projects WHERE workspace_id=%s AND request_key=%s",
                             (workspace,"link_revoked_during_intake")).fetchone()
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (original,workspace))
    check("Revoked YouTube authorization during reference analysis prevents persistence", int(failed)==0)
