"""Hosted personal-writing integration on real disposable PostgreSQL.

All authors, accounts and output are synthetic. The recording runtime makes no
provider call: these checks prove assembly, persistence and review authority, not
personal voice quality. Run with scripts/postriff_disposable_postgres.py.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2 import creation_capabilities, skills
from postriff_phase2.agent_runtime import AgentRuntime, identity_fields
from postriff_phase2.campaign_worker import CampaignWorker
from postriff_phase2.coworker import flags
from postriff_phase2.hosted import HostedWorkspaceService

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
ONE = "00000000-0000-0000-0000-000000000001"
clock = [time.time()]
checks, formats, campaign_platforms = [], [], []
os.environ["RAFII_CREATION_ALL_PLATFORMS_ENABLED"] = "1"
os.environ["RAFII_CREATION_PROJECTION_ENABLED"] = ""
flags.attach(None)
creation_capabilities._CACHE.clear()


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    checks.append(name)


class RecordingRuntime(AgentRuntime):
    """Pure in-process fixture, with cloud egress policy but no network transport."""
    provider = "pwi-recording-fixture"
    provider_class = "cloud"
    cost_class = "subscription"
    asynchronous = False
    model = "pwi-recording-fixture:model"

    def __init__(self):
        self.requests = []

    def list_supported_models(self):
        return [{"id": self.model, "label": "Synthetic recording fixture",
                 "qualified": True, "costClass": self.cost_class,
                 "route": self.provider, "detail": "No model or network call"}]

    def list_supported_reasoning(self):
        return [{"id": "quick", "available": True, "detail": "Fixture"}]

    def supported_platforms(self):
        return tuple(skills.CHANNEL_SKILLS)

    def start_conversation(self, workspace_id, actor):
        return {}

    def start_turn(self, request, emit):
        self.requests.append(request)
        emit({"type": "run.started", "model": self.model, "reasoning": "quick",
              "contextDigest": "synthetic-pwi"})
        # Deterministic output is a transport probe, never a voice-quality score.
        no_hashtags = "No hashtags." in str(request["memory"])
        text = "Synthetic community workshop draft." + ("" if no_hashtags else " #Fixture")
        artifact = {"variants": [
            {"platform": d["platform"], "language": d["language"],
             **identity_fields(d), "text": text, "sourceIds": [], "unknowns": [],
             "warnings": [], "candidateOnly": False}
            for d in request["destinations"]
        ]}
        usage = {"provenance": "fixture", "modelRequests": 0, "costUsd": 0}
        emit({"type": "run.completed", "usage": usage})
        return {"artifact": artifact, "usage": usage}


def fresh_service():
    runtime = RecordingRuntime()
    service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
    service.ideas.runtimes = [service.ideas.runtime, runtime]
    return service, runtime


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
    db.execute("UPDATE public.pr_memberships SET status='active',role='owner' WHERE user_id=%s", (ONE,))
    for table in ("pr_memory_versions", "pr_memory_proposals", "pr_learning_events"):
        db.execute(f"DELETE FROM public.{table} WHERE workspace_id=%s", (wid,))

service, runtime = fresh_service()
service.bootstrap("one", "studio")
from consumer_fixtures import approve_budgets
approve_budgets(connection, wid)
with connection() as db:
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
    state["speaker"]["revisions"] = [{"revision": 7, "approvedAt": "2026-09-01T00:00:00Z",
        "reason": "synthetic approved profile", "profile": {"tone": "plain",
        "observations": ["Use concrete workshop details."]}}]
    state["speaker"]["activeRevision"] = 7
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), wid))
service.mutate(wid, "one", service.get(wid, "one")["revision"],
               "memory_egress", {"cloud": True, "confirmed": True})


def draft(platform="X", mode="personalized", format_id=None):
    cid = service.ideas.create_conversation(wid, "one", "Synthetic PWI held-out brief")["conversationId"]
    destination = {"platform": platform, "language": "en"}
    if format_id:
        destination["format"] = format_id
    result = service.ideas.turn(wid, "one", cid, {
        "text": "Write a short reflection about preparing a community workshop.",
        "destinations": [destination], "model": runtime.model,
        "voiceMode": mode, "timeZone": "Asia/Hong_Kong", "research": False})
    check(f"completed {platform}/{format_id or 'default'}/{mode}", result["status"] == "completed", result)
    return result


projection = creation_capabilities.projection()
check("all 33 installed platforms available under explicit test rollout", len(projection.draftable()) == 33)
for platform in projection.draftable():
    row = projection.by_platform[platform]
    for fmt in projection.offered_formats(row):
        run = draft(platform, format_id=fmt["id"])
        request = runtime.requests[-1]
        bound = request["skills"]
        adapter = skills.CHANNEL_SKILLS[platform]
        expected_adapter = service.ideas.skills.load(adapter)
        platform_bindings = [b for b in bound["bindings"] if b["id"].startswith("postriff-channel-")]
        check(f"exact adapter reaches {platform}/{fmt['id']}",
              [b["id"] for b in platform_bindings] == [adapter]
              and f"## Skill: {adapter} " in bound["text"]
              and platform_bindings[0]["sha256"] == expected_adapter["sha256"]
              and expected_adapter["body"] in bound["text"]
              and not any(o.get("cut") for o in bound["omitted"]))
        native = run["artifact"]["variants"][0]["native"]
        check(f"native format stays truthful {platform}/{fmt['id']}",
              native["formatId"] == fmt["id"]
              and native["skillRoute"]["qualified"]
              and native["readiness"]["publish"] in ("not_checked", "export_only")
              and native["constraints"]["verified"] is False
              and native["media"]["required"] == fmt["mediaKind"])
        check(f"approved voice receipt {platform}/{fmt['id']}",
              "Use concrete workshop details." in str(request["memory"])
              and run["artifact"]["memoryReceipt"]["execution"] == "fixture"
              and run["artifact"]["memoryReceipt"]["effectiveVoiceMode"] == "approved")
        formats.append({"platform": platform, "format": fmt["id"], "skill": adapter,
                        "sha256": platform_bindings[0]["sha256"], "qualified": True,
                        "publish": native["readiness"]["publish"], "media": native["media"]})
check("all native format rows exercised", len(formats) == sum(len(r["formats"]) for r in projection.rows))

before = draft()
check("before learning fixture contains its marker", "#Fixture" in before["artifact"]["variants"][0]["text"])
cid = service.ideas.create_conversation(wid, "one", "Synthetic preference correction")["conversationId"]
calls = len(runtime.requests)
proposal = service.ideas.turn(wid, "one", cid, {"text": "Remember: no hashtags on x", "model": runtime.model})
check("memory instruction creates X-scoped proposal without model", proposal["status"] == "memory"
      and proposal["memoryProposal"]["scope"]["platform"] == "X" and len(runtime.requests) == calls)
pending = draft()
check("pending correction is not applied", "#Fixture" in pending["artifact"]["variants"][0]["text"])
decision = service.learning.decide(service.repository, wid, "one",
    service.get(wid, "one")["revision"], proposal["memoryProposal"]["id"], "remember")
item_id = decision["item"]["id"]
check("accepted preference has durable version", bool(decision["versionId"]))
service, runtime = fresh_service()  # no old in-memory workspace/conversation state
after = draft()
check("fresh conversation after service recreation uses accepted preference",
      "#Fixture" not in after["artifact"]["variants"][0]["text"]
      and after["usage"]["memoryBindings"]["used"] == [item_id])
unrelated = draft("LinkedIn")
check("X correction does not affect LinkedIn",
      "#Fixture" in unrelated["artifact"]["variants"][0]["text"]
      and unrelated["usage"]["memoryBindings"]["used"] == [])
neutral = draft(mode="neutral")
check("neutral mode excludes learned voice",
      "#Fixture" in neutral["artifact"]["variants"][0]["text"]
      and neutral["usage"]["memoryBindings"]["used"] == [])
files = service.ideas.memory_files(wid, "one")["files"]
check("five canonical files read back from hosted service",
      {f["name"] for f in files} == {"VOICE.md", "IDENTITY.md", "BOUNDARIES.md", "BRAND.md", "AGENT.md"})
check("VOICE.md exposes accepted rule and scope",
      any(f["name"] == "VOICE.md" and "No hashtags." in f["body"] and "[X" in f["body"] for f in files))
service.learning.update_version(service.repository, wid, "one",
    service.get(wid, "one")["revision"], item_id, "paused")
paused = draft()
check("pause removes preference from next run", paused["usage"]["memoryBindings"]["used"] == [])
service.learning.update_version(service.repository, wid, "one",
    service.get(wid, "one")["revision"], item_id, "active")
resumed = draft()
check("resume restores preference to next run", resumed["usage"]["memoryBindings"]["used"] == [item_id])
service.learning.update_version(service.repository, wid, "one",
    service.get(wid, "one")["revision"], item_id, "retired")
try:
    service.ideas.apply(wid, "one", service.get(wid, "one")["revision"],
                        resumed["runId"], resumed["artifactHash"])
except AlphaError as error:
    check("retired preference invalidates old candidate apply", error.status == 409, str(error))
else:
    raise AssertionError("Retired preference candidate was accepted")
service, runtime = fresh_service()
retired = draft()
check("retirement survives reload and removes preference",
      retired["usage"]["memoryBindings"]["used"] == []
      and "#Fixture" in retired["artifact"]["variants"][0]["text"])
cid = service.ideas.create_conversation(wid, "one", "Ambiguous scoped instruction")["conversationId"]
calls = len(runtime.requests)
ambiguous = service.ideas.turn(wid, "one", cid, {
    "text": "Remember no emoji on X and LinkedIn", "model": runtime.model})
check("multi-platform instruction requests clarification without proposal or call",
      ambiguous["status"] == "memory" and ambiguous["memoryProposal"] is None and len(runtime.requests) == calls)
with connection() as db:
    versions = db.execute("SELECT status FROM public.pr_memory_versions WHERE workspace_id=%s AND proposal_id::text=%s",
                          (wid, item_id)).fetchall()
check("retirement recorded in PostgreSQL version history", versions and all(r[0] == "retired" for r in versions))
# A one-off instruction is an ordinary draft; a declined proposal stays out of memory.
cid = service.ideas.create_conversation(wid, "one", "One-off correction")['conversationId']
one_off = service.ideas.turn(wid, "one", cid, {
    "text": "For this draft, no emoji on X", "model": runtime.model,
    "voiceMode": "personalized", "destinations": [{"platform": "X", "language": "en"}]})
check("this-draft-only instruction does not create durable memory", one_off["status"] == "completed"
      and one_off["usage"]["memoryBindings"]["used"] == [])
proposal = service.ideas.turn(wid, "one", cid, {"text": "Remember no emoji on X", "model": runtime.model})
service.learning.decide(service.repository, wid, "one", service.get(wid, "one")["revision"],
                       proposal["memoryProposal"]["id"], "dismiss")
service, runtime = fresh_service()
dismissed = draft()
check("dismissed preference stays absent after fresh service", dismissed["usage"]["memoryBindings"]["used"] == []
      and "No emoji." not in str(runtime.requests[-1]["memory"]))

# A remembered length reaches the writer as a number and is measured on the finished draft, on its own channel only.
cid = service.ideas.create_conversation(wid, "one", "Remembered length")['conversationId']
proposal = service.ideas.turn(wid, "one", cid, {"text": "Remember: keep posts on X under 3 words", "model": runtime.model})
check("length instruction becomes an X-scoped length proposal", proposal["status"] == "memory"
      and proposal["memoryProposal"]["ruleKey"] == "length.target" and proposal["memoryProposal"]["scope"]["platform"] == "X")
length_item = service.learning.decide(service.repository, wid, "one", service.get(wid, "one")["revision"],
                                      proposal["memoryProposal"]["id"], "remember")["item"]["id"]
limited = draft()
check("writer request carries the remembered length as a number", runtime.requests[-1].get("lengthLimits") == [{"platform": "X", "language": "en", "words": 2}]
      and limited["usage"]["memoryBindings"]["used"] == [length_item])
check("over-length draft carries the measured count and stays a candidate", limited["status"] == "completed"
      and any("your remembered preference asks for under 3" in w for w in limited["artifact"]["variants"][0]["warnings"]))
elsewhere = draft("LinkedIn")
check("remembered X length neither reaches nor is measured on LinkedIn", "lengthLimits" not in runtime.requests[-1]
      and not any("remembered preference" in w for w in elsewhere["artifact"]["variants"][0]["warnings"]))
unvoiced = draft(mode="neutral")
check("neutral mode carries no remembered length", "lengthLimits" not in runtime.requests[-1]
      and not any("remembered preference" in w for w in unvoiced["artifact"]["variants"][0]["warnings"]))
service.learning.update_version(service.repository, wid, "one", service.get(wid, "one")["revision"], length_item, "retired")
withdrawn = draft()
check("withdrawn length leaves the next request and draft", "lengthLimits" not in runtime.requests[-1]
      and not any("remembered preference" in w for w in withdrawn["artifact"]["variants"][0]["warnings"]))

# A sample's own text reaches the writer only under its separate per-sample, exact-route "examples" permission.
fixture_route = f"cloud:{runtime.provider}:{runtime.model}"
sample_text = "Synthetic sample post.\n\nShort lines.\n\n~ fixture sign-off ~"
before_sources = {s["id"] for s in service.get(wid, "one")["state"].get("sources", [])}
service.mutate(wid, "one", service.get(wid, "one")["revision"], "brand_brain_import", {"format": "pasted", "text": sample_text, "platform": "X", "language": "en",
               "authorshipConfirmed": True, "retentionConfirmed": True, "requestId": "pwi-style-example-0001"})
sample_id = next(s["id"] for s in service.get(wid, "one")["state"]["sources"] if s["id"] not in before_sources and s.get("kind") == "voice_sample")
service.mutate(wid, "one", service.get(wid, "one")["revision"], "voice_sample_select", {"sourceId": sample_id, "selected": True})
style_only = [{"purpose": "generation", "route": fixture_route}]
service.mutate(wid, "one", service.get(wid, "one")["revision"], "voice_sample_grant", {"sourceId": sample_id, "confirmed": True, "grants": style_only})
styled = draft()
check("style permission alone sends no sample text", "voiceSamples" not in runtime.requests[-1]
      and styled["artifact"]["voiceContext"]["bindings"] and "examples" not in styled["artifact"]["voiceContext"])
service.mutate(wid, "one", service.get(wid, "one")["revision"], "voice_sample_grant", {"sourceId": sample_id, "confirmed": True,
               "grants": style_only + [{"purpose": "examples", "route": fixture_route}]})
exampled = draft()
check("example permission sends that sample's text and the run records it",
      [item["text"] for item in runtime.requests[-1].get("voiceSamples", [])] == [sample_text]
      and [item["id"] for item in exampled["artifact"]["voiceContext"].get("examples", [])] == [sample_id])
check("neutral mode never receives sample text", "voiceSamples" not in (draft(mode="neutral") and runtime.requests[-1]))
with connection() as db:
    stored = db.execute("SELECT coalesce(artifact::text,'') || coalesce(usage::text,'') FROM public.pr_agent_runs WHERE id::text=%s", (exampled["runId"],)).fetchone()[0]
    logged = " ".join(str(row[0]) for row in db.execute("SELECT body::text FROM public.pr_agent_events WHERE run_id::text=%s", (exampled["runId"],)).fetchall())
check("the run and its events keep sample ids and hashes, never the sample text", "fixture sign-off" not in stored and "fixture sign-off" not in logged and sample_id in stored)
service.mutate(wid, "one", service.get(wid, "one")["revision"], "memory_egress", {"cloud": False, "confirmed": True})
check("a workspace that keeps memory from cloud models keeps its samples from them too", "voiceSamples" not in (draft() and runtime.requests[-1]))
service.mutate(wid, "one", service.get(wid, "one")["revision"], "memory_egress", {"cloud": True, "confirmed": True})
check("example permission resumes when cloud memory is allowed again", len(draft() and runtime.requests[-1].get("voiceSamples", [])) == 1)
service.mutate(wid, "one", service.get(wid, "one")["revision"], "voice_sample_grant", {"sourceId": sample_id, "confirmed": True, "grants": style_only})
check("withdrawn example permission stops the text at the next draft", "voiceSamples" not in (draft() and runtime.requests[-1]))
try:
    service.ideas.apply(wid, "one", service.get(wid, "one")["revision"], exampled["runId"], exampled["artifactHash"])
except AlphaError as error:
    check("a draft that read the sample is refused after its permission is withdrawn", error.status == 409, str(error))
else:
    raise AssertionError("A draft that read a sample was kept after its example permission was withdrawn")
service.mutate(wid, "one", service.get(wid, "one")["revision"], "voice_sample_revoke", {"sourceId": sample_id, "confirmed": True})

# Every channel also reaches the same personalized writer through a persisted campaign.
# A platform-only destination is a drafting choice; it never implies a live connection.
cid = service.ideas.create_conversation(wid, "one", "Campaign preference")['conversationId']
proposal = service.ideas.turn(wid, "one", cid, {"text": "Remember no exclamation marks", "model": runtime.model})
decision = service.learning.decide(service.repository, wid, "one", service.get(wid, "one")["revision"],
                                   proposal["memoryProposal"]["id"], "remember")
campaign_preference = decision["item"]["id"]
for platform in projection.draftable():
    saved = service.mutate(wid, "one", service.get(wid, "one")["revision"], "raffi_recurrence_save", {
        "name": f"Synthetic {platform} workshop notes", "goal": "Share confirmed workshop planning details.",
        "audience": "Local readers", "schedule": {"weekdays": ["Monday"], "localTime": "09:00", "timeZone": "Asia/Hong_Kong"},
        "destinations": [{"platform": platform, "language": "en"}], "route": runtime.model,
        "voiceMode": "personalized", "maxCostUsdMicro": 0})
    task = saved["state"]["raffi"]["campaignPlanning"]["recurringTasks"][-1]
    service.mutate(wid, "one", saved["revision"], "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True})
    clock[0] = task["nextOccurrence"]["scheduledFor"] + 1
    result = CampaignWorker(service).tick()
    check(f"campaign worker completes {platform}", result.get("state") == "completed", result)
    request = runtime.requests[-1]
    adapter = skills.CHANNEL_SKILLS[platform]
    expected_adapter = service.ideas.skills.load(adapter)
    recorded_adapter = next(b for b in request["skills"]["bindings"] if b["id"] == adapter)
    check(f"campaign receives current approved voice and preference {platform}",
          request["destinations"] == [{"platform": platform, "language": "en"}]
          and request["voiceContext"]["mode"] == "personalized"
          and "Use concrete workshop details." in str(request["memory"])
          and "No exclamation marks." in str(request["memory"])
          and expected_adapter["body"] in request["skills"]["text"]
          and recorded_adapter["sha256"] == expected_adapter["sha256"])
    occurrence = next(o for o in service.get(wid, "one")["state"]["raffi"]["campaignPlanning"]["occurrences"] if o["id"] == result["occurrenceId"])
    with connection() as db:
        usage = db.execute("SELECT usage FROM public.pr_agent_runs WHERE id::text=%s", (occurrence["runId"],)).fetchone()[0]
    check(f"campaign records exact learned preference {platform}", campaign_preference in usage["memoryBindings"]["used"])
    calls = len(runtime.requests)
    check(f"campaign restart does not duplicate {platform}", CampaignWorker(service).tick() == {"idle": True}
          and len(runtime.requests) == calls)
    service.mutate(wid, "one", service.get(wid, "one")["revision"], "raffi_recurrence_pause", {"taskId": task["id"]})
    campaign_platforms.append(platform)

# Accepted suggestions retain only review authority and the current exact brief/account.
with connection() as db:
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
    state["brief"].update({"revision": 12, "idea": "Synthetic workshop planning brief."})
    state["variants"] = [{"id": "already-drafted", "briefRevision": 12, "channelId": "covered"}]
    state["phase2"]["channels"] = [{"id": "synthetic-bilibili", "platform": "Bilibili", "account": "Synthetic account",
        "configured": True, "verifiedAt": clock[0], "identityVerified": True, "capabilityVerified": True, "expiresAt": clock[0] + 86400, "revoked": False}]
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), wid))
refreshed = service.mutate(wid, "one", service.get(wid, "one")["revision"], "raffi_suggestion_refresh", {})
suggestion = next(s for s in refreshed["state"]["raffi"]["suggestions"] if s["kind"] == "missing_variant")
accepted = service.mutate(wid, "one", refreshed["revision"], "raffi_suggestion_accept", {"suggestionId": suggestion["id"]})
service, runtime = fresh_service()
state = service.get(wid, "one")["state"]
ref = next(s for s in state["raffi"]["suggestions"] if s["id"] == suggestion["id"])["actionRef"]
check("hosted suggestion handoff persists exact account and brief revision",
      ref["workspaceId"] == wid and ref["targetId"] == "synthetic-bilibili" and ref["targetRevision"] == 12
      and ref["authority"] == "open_for_review" and state["brief"]["idea"] == "Synthetic workshop planning brief.")
with connection() as db:
    state["brief"]["revision"] += 1
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), wid))
try:
    service.mutate(wid, "one", service.get(wid, "one")["revision"], "raffi_suggestion_accept", {"suggestionId": suggestion["id"]})
except AlphaError as error:
    check("server refuses stale suggestion after brief revision changes", error.status == 409, str(error))
else:
    raise AssertionError("A stale suggestion was accepted")
state = service.get(wid, "one")["state"]
check("all generated drafts remain unpublished", not state.get("phase2", {}).get("jobs"))

report = {"status": "pass", "execution": "synthetic-runtime-real-postgres",
          "providerCalls": 0, "personalVoiceQuality": "NOT_RUN",
          "platformCount": len(projection.draftable()), "nativeFormatCount": len(formats),
          "campaignPlatforms": campaign_platforms,
          "checks": checks, "formats": formats,
          "limitations": ["Synthetic authors and deterministic output; not personal voice acceptance.",
                          "Platform constraints unverified; media drafts are not publish-ready.",
                          "No external social provider or paid model was called."]}
if os.environ.get("RAFII_PWI_REPORT"):
    Path(os.environ["RAFII_PWI_REPORT"]).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "formats"}, ensure_ascii=False))
