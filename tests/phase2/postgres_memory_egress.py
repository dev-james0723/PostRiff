"""Memory files on a cloud route, and the how-to guard, on disposable PostgreSQL:
a cloud route reads no memory file until an owner allows it, the decision is audited and shown on
the Memory page, private boundaries never leave even with consent, and a how-to with nothing
approved to teach is recorded as a request for the steps without a model call.

Run through scripts/postriff_disposable_postgres.py (loads rls.sql with migrations 004+005).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime import AgentRuntime
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
clock = [1789524000.0]
passed = []


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
    passed.append(name)


class FakeCloudRuntime(AgentRuntime):
    """Stands in for ServerModelRuntime: a synchronous cloud route that records what it was sent."""
    provider = "fake-cloud"
    provider_class = "cloud"
    cost_class = "subscription"  # keeps the ledger out of this test; memory follows provider_class alone
    asynchronous = False
    model = "fake-cloud:model"

    def __init__(self):
        self.requests = []

    def list_supported_models(self):
        return [{"id": self.model, "label": "Fake cloud", "qualified": True, "costClass": self.cost_class, "route": "fake-cloud", "detail": "fake"}]

    def list_supported_reasoning(self):
        return [{"id": "quick", "available": True, "detail": "fake"}]

    def supported_platforms(self):
        return ("LinkedIn", "Instagram", "Threads")

    def start_conversation(self, workspace_id, actor):
        return {}

    def start_turn(self, request, emit):
        self.requests.append(request)
        emit({"type": "run.started", "model": self.model, "reasoning": "quick", "contextDigest": "d"})
        artifact = {"variants": [{"platform": d["platform"], "language": d["language"], "text": f"Draft for {d['platform']}", "sourceIds": [], "unknowns": [], "warnings": [], "candidateOnly": False} for d in request["destinations"]]}
        usage = {"provenance": "fake", "modelRequests": 1, "costUsd": 0}
        emit({"type": "run.completed", "usage": usage})
        return {"artifact": artifact, "usage": usage}


def act(action, payload):
    revision = service.get(wid, "one")["revision"]
    return service.mutate(wid, "one", revision, action, payload)


def edit_state(workspace_id, change):
    """Test-only: shape workspace state directly (voice profile, boundaries, content selection)."""
    with connection() as db:
        state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace_id,)).fetchone()[0]
        change(state)
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), workspace_id))


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))

cloud = FakeCloudRuntime()
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
service.ideas.runtimes = [service.ideas.runtime, cloud]
ideas = service.ideas
service.bootstrap("one", "studio")


def with_voice_and_boundaries(state):
    state["speaker"]["revisions"] = [{"revision": 7, "approvedAt": "2026-09-01T00:00:00Z", "reason": "approved", "profile": {"tone": "plain, dry", "observations": ["Short sentences."]}}]
    state["speaker"]["activeRevision"] = 7
    state.setdefault("profile", {})["fields"] = [
        {"section": "boundaries", "key": "students", "label": "Students", "value": "Never name a student", "privacy": "workspace_only"},
        {"section": "boundaries", "key": "health", "label": "Health", "value": "SECRET-HEALTH-DETAIL", "privacy": "local_only"},
    ]


edit_state(wid, with_voice_and_boundaries)
cid = ideas.create_conversation(wid, "one", "cloud memory")["conversationId"]

# 1. Without consent the cloud route receives no memory file, and the turn says so.
run = ideas.turn(wid, "one", cid, {"text": "Write about centering for LinkedIn.", "model": cloud.model, "timeZone": "Asia/Hong_Kong"})
check("no consent: cloud route reads no memory file", cloud.requests[-1]["memory"] == [], cloud.requests[-1]["memory"])
check("no consent: the turn warns that nothing was shared", any(e["type"] == "warning.created" and "were not shared with this cloud model" in e.get("message", "") for e in run["events"]), [e for e in run["events"] if e["type"] == "warning.created"])
check("memory page shows sharing off", ideas.memory_files(wid, "one")["egress"]["cloud"] is False)

# 2. An owner allows it; the decision is audited and visible on the Memory page.
revision = service.get(wid, "one")["revision"]
service.mutate(wid, "one", revision, "memory_egress", {"cloud": True, "confirmed": True})
kinds = [e for e in service.audit_events(wid, "one")["events"] if e["kind"] == "memory.egress_decided"]
check("the decision is audited", kinds and kinds[0]["meta"] == {"cloud": True}, kinds)
egress = ideas.memory_files(wid, "one")["egress"]
check("memory page shows sharing on and what stays back", egress["cloud"] is True and egress["withheldBoundaries"] == 1, egress)

# 3. With consent: voice, identity and shareable boundaries go; the local-only boundary never does.
run = ideas.turn(wid, "one", cid, {"text": "Write about trimming for LinkedIn.", "model": cloud.model, "timeZone": "Asia/Hong_Kong"})
sent = cloud.requests[-1]["memory"]
check("consent: the three prompt files are sent", [f["name"] for f in sent] == ["VOICE.md", "IDENTITY.md", "BOUNDARIES.md"], [f["name"] for f in sent])
check("consent: a local-only boundary never leaves", "SECRET-HEALTH-DETAIL" not in json.dumps(sent) and "Never name a student" in json.dumps(sent))
check("consent: the turn names the withheld boundary", any("marked private or local-only was not shared" in e.get("message", "") for e in run["events"]))
check("consent: the run completed", run["status"] == "completed", run["status"])

# 4. A how-to with nothing approved to teach asks for the steps: failed run, clear message, no model call.
act("p2_content_install_pack", {"packId": "pack.creator", "version": "1.0.0"})
act("p2_content_select", {"contentTypeId": "pack.creator:tutorial_how_to", "contentTypeVersion": "1.0.0", "formatId": "carousel"})
calls = len(cloud.requests)
run = ideas.turn(wid, "one", cid, {"text": "A carousel for first-timers on how to wedge clay.", "model": cloud.model, "timeZone": "Asia/Hong_Kong"})
check("how-to guard: no model request", len(cloud.requests) == calls, len(cloud.requests))
check("how-to guard: the run failed with what is needed", run["status"] == "failed" and any(e["type"] == "run.failed" and "It needs: the steps you actually teach" in e.get("message", "") for e in run["events"]), run)
last = [m for m in ideas.messages(wid, "one", cid)["messages"] if m["role"] == "assistant"][-1]
check("how-to guard: the conversation shows the request", last["body"].get("failed") is True and "It needs" in last["body"]["text"], last["body"])

# 5. The same how-to with its steps in the message is drafted normally.
run = ideas.turn(wid, "one", cid, {"text": "How I wedge:\n1. Cut the clay in half\n2. Slam the halves together\n3. Press and rotate", "model": cloud.model, "timeZone": "Asia/Hong_Kong"})
check("how-to with supplied steps: drafted", run["status"] == "completed" and len(cloud.requests) == calls + 1, run["status"])

# 6. Withdrawing consent stops sharing on the next turn.
act("memory_egress", {"cloud": False, "confirmed": True})
act("p2_content_select", {"contentTypeId": "pack.creator:personal_reflection", "contentTypeVersion": "1.0.0"})
ideas.turn(wid, "one", cid, {"text": "Write about glazing for LinkedIn.", "model": cloud.model, "timeZone": "Asia/Hong_Kong"})
check("withdrawn consent: nothing is sent again", cloud.requests[-1]["memory"] == [])

print(f"postgres_memory_egress: {len(passed)}/{len(passed)} checks passed")
