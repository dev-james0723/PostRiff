"""Raffi voice samples through the real hosted repository and disposable PostgreSQL."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import psycopg

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.agent_runtime import AgentRuntime

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"


def connection():
    return psycopg.connect(DSN)


def verify(token):
    return ONE if token == "one" else TWO


verify.session_id = lambda token, principal: "session-raffi-0123456789abcdef"
verify.auth_time = lambda token, principal: __import__("time").time()

service = HostedWorkspaceService(connection, verify)
snapshot = service.bootstrap("one", "studio")
workspace_id = snapshot["workspaceId"]
with connection() as db:
    db.execute(
        "INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active') "
        "ON CONFLICT(workspace_id,user_id) DO UPDATE SET role='editor',status='active'",
        (workspace_id, TWO),
    )


def act(token, action, payload):
    current = service.get(workspace_id, token)
    return service.mutate(workspace_id, token, current["revision"], action, payload)


created = act("two", "voice_samples_import", {"format": "pasted", "text": "廣東話 opening\nEnglish close", "platform": "Threads"})
sample = next(item for item in created["state"]["sources"] if item.get("kind") == "voice_sample")
assert sample["retainedBy"] == TWO
assert sample["text"] == "廣東話 opening\nEnglish close"
act("two", "voice_sample_select", {"sourceId": sample["id"], "selected": True})

try:
    act("two", "voice_sample_grant", {"sourceId": sample["id"], "grants": [{"purpose": "analysis", "route": "local-rules"}], "confirmed": True})
    raise AssertionError("editor granted durable voice route")
except AlphaError as error:
    assert error.status == 403

granted = act("one", "voice_sample_grant", {"sourceId": sample["id"], "grants": [{"purpose": "analysis", "route": "local-rules"}, {"purpose": "generation", "route": "local-cli"}], "confirmed": True})
saved = next(item for item in granted["state"]["sources"] if item["id"] == sample["id"])
assert saved["purposeGrants"] == ["analysis", "generation"]
assert saved["routeGrants"] == ["local-cli", "local-rules"]

conversation = service.ideas.create_conversation(workspace_id, "one", "Voice-bound draft")
candidate = service.ideas.turn(
    workspace_id,
    "one",
    conversation["conversationId"],
    {
        "text": "Share a short reflection on creative practice",
        "sourceIds": [],
        "destinations": [{"platform": "LinkedIn", "language": "English"}],
        "voiceMode": "personalized",
        "voiceSourceIds": [sample["id"]],
    },
)
assert candidate["status"] == "completed"
assert candidate["artifact"]["voiceContext"]["bindings"][0]["id"] == sample["id"]
assert sample["text"] not in str(candidate["artifact"])


class DeferredLocalRuntime(AgentRuntime):
    model = "deferred-local"
    provider = "fixture-deferred"
    cost_class = "none"
    asynchronous = True

    def list_supported_models(self):
        return [{"id": self.model, "label": "Deferred local fixture", "qualified": True, "costClass": "none", "detail": "test fixture"}]

    def list_supported_reasoning(self):
        return [{"id": "quick", "available": True, "detail": "test fixture"}]

    def supported_platforms(self):
        return ("LinkedIn",)

    def dispatch(self, run_id, request, sink):
        self.run_id, self.request, self.sink = run_id, request, sink


deferred = DeferredLocalRuntime()
service.ideas.runtimes.append(deferred)
pending = service.ideas.turn(
    workspace_id,
    "one",
    conversation["conversationId"],
    {
        "text": "Draft after an asynchronous pause",
        "sourceIds": [],
        "destinations": [{"platform": "LinkedIn", "language": "English"}],
        "model": deferred.model,
        "voiceMode": "personalized",
        "voiceSourceIds": [sample["id"]],
    },
)
assert pending["status"] == "running"

with connection() as db:
    db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s", (workspace_id, TWO))
try:
    act("two", "voice_sample_exclude", {"sourceId": sample["id"]})
    raise AssertionError("viewer edited retained voice sample")
except AlphaError as error:
    assert error.status == 403

revoked = act("one", "voice_sample_revoke", {"sourceId": sample["id"], "confirmed": True})
saved = next(item for item in revoked["state"]["sources"] if item["id"] == sample["id"])
assert saved["text"] == "" and saved["revisions"] == [] and saved["cleanupStatus"] == "complete"
completed = deferred.sink.complete(
    {"variants": [{"platform": "LinkedIn", "language": "English", "text": "Candidate", "sourceIds": [], "unknowns": [], "warnings": [], "candidateOnly": False}]},
    {"provenance": "fixture", "modelRequests": 0, "costUsd": 0},
)
assert completed is True
failed = service.ideas.events(workspace_id, "one", pending["runId"], 0)
assert failed["status"] == "failed" and failed["artifact"] is None
assert failed["events"][-1]["type"] == "run.failed"
try:
    service.ideas.apply(workspace_id, "one", revoked["revision"], candidate["runId"], candidate["artifactHash"])
    raise AssertionError("applied candidate after supporting voice sample was revoked")
except AlphaError as error:
    assert error.status == 409

print("PASS: persisted import, exact grant, personalized binding, viewer denial, revocation cleanup, completion race and stale-apply block")
