"""Asynchronous writing route on disposable PostgreSQL (agent chat design §4.2, route A):
a turn on an asynchronous runtime returns `running` at once, a background sink completes it in
its own transactions, the conversation gets its assistant message, the ledger settles at $0,
cancellation wins over late results, and the model catalog lists the route.

Run through scripts/postriff_disposable_postgres.py (loads rls.sql with migrations 004+005).
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime import AgentRuntime, FixtureAgentRuntime, safe_event
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
clock = [1789524000.0]


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


class FakeCliRuntime(AgentRuntime):
    """Stands in for ClaudeCliRuntime: same contract, completes on a thread when released."""
    provider = "claude-code"
    cost_class = "subscription"
    asynchronous = True
    model = "claude-code:default"

    def __init__(self):
        self.release = threading.Event()
        self.threads = []
        self.behaviour = "complete"

    def list_supported_models(self):
        return [{"id": "claude-code:default", "label": "Claude Code · default", "qualified": True, "costClass": "subscription", "route": "claude-code", "detail": "fake"}]

    def list_supported_reasoning(self):
        return [{"id": "quick", "available": True, "detail": "fake"}]

    def describe(self):
        return {"id": "claude-code", "name": "Claude Code", "installed": True, "authStatus": "ok", "version": "9.9.9", "models": ["claude-code:default"]}

    def supported_platforms(self):
        return ("LinkedIn", "Instagram", "Threads")

    def start_conversation(self, workspace_id, actor):
        return {}

    def dispatch(self, run_id, request, sink):
        self.last_request = request

        def work():
            sink.emit(safe_event("progress.updated", stage="writing", percent=10))
            self.release.wait(10)
            if self.behaviour == "complete":
                sink.emit(safe_event("message.delta", text="Hello "))
                artifact = {"variants": [{"platform": d["platform"], "language": d["language"], "text": f"Draft for {d['platform']} from {request['idea']}", "sourceIds": [], "unknowns": [], "warnings": ["fake"], "candidateOnly": False} for d in request["destinations"]]}
                sink.complete(artifact, {"provenance": "reported_by_cli", "billing": "subscription", "modelRequests": 1, "costUsd": 0, "cliCostUsd": 0.02})
            else:
                sink.fail("Claude Code is not signed in on this machine. Run `claude auth login`.")
        thread = threading.Thread(target=work)
        self.threads.append(thread)
        thread.start()


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))

fake = FakeCliRuntime()
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
service.ideas.runtimes = [service.ideas.runtime, fake]
ideas = service.ideas
snap = service.bootstrap("one", "studio")

# 1. The catalog lists both routes and the agent behind the CLI route.
catalog = ideas.model_catalog()
assert [m["id"] for m in catalog["models"]][:1] == [FixtureAgentRuntime.model] and "claude-code:default" in [m["id"] for m in catalog["models"]]
assert catalog["agents"][0]["id"] == "claude-code" and "email" not in catalog["agents"][0]

# 2. A turn on the CLI route returns immediately as running, with run.started first and a queued progress event.
conversation = ideas.create_conversation(wid, "one", "cli route")
cid = conversation["conversationId"]
run = ideas.turn(wid, "one", cid, {"text": "Write about onboarding for LinkedIn and Threads.", "model": "claude-code:default", "timeZone": "Asia/Hong_Kong"})
assert run["status"] == "running" and run["artifact"] is None and run["model"] == "claude-code:default", run
kinds = [e["type"] for e in run["events"]]
assert kinds[0] == "run.started" and "progress.updated" in kinds and "run.completed" not in kinds, kinds
pending = [m for m in ideas.messages(wid, "one", cid)["messages"] if m["role"] == "assistant"]
assert len(pending) == 1 and pending[0]["runId"] == run["runId"] and pending[0]["body"]["pending"] is True and pending[0]["body"]["text"] == "", pending

# 3. While waiting, the events endpoint replays what the sink has written so far.
deadline = time.time() + 5
while time.time() < deadline and not any(e["type"] == "progress.updated" and e.get("stage") == "writing" for e in ideas.events(wid, "one", run["runId"])["events"]):
    time.sleep(0.05)
assert any(e["type"] == "progress.updated" and e.get("stage") == "writing" for e in ideas.events(wid, "one", run["runId"])["events"])

# 4. Releasing the fake finishes the run: artifact stored, run.completed last, assistant message with the model, $0 settled.
fake.release.set()
fake.threads[-1].join(10)
done = ideas.events(wid, "one", run["runId"])
assert done["status"] == "completed" and [v["platform"] for v in done["artifact"]["variants"]] == ["LinkedIn", "Threads"], done["status"]
kinds = [e["type"] for e in done["events"]]
assert kinds[0] == "run.started" and kinds[-1] == "run.completed" and "message.delta" in kinds, kinds
assert done["usage"]["billing"] == "subscription" and done["usage"]["costUsd"] == 0
assistants = [m for m in ideas.messages(wid, "one", cid)["messages"] if m["role"] == "assistant"]
assert len(assistants) == 1, "the pending turn is filled in, not duplicated"
assistant = assistants[-1]
assert assistant["runId"] == run["runId"] and assistant["body"]["model"] == "claude-code:default" and not assistant["body"].get("pending") and assistant["body"]["text"].startswith("Drafted 2")
# Skills were bound by destination (design §7): the editorial core plus one adapter per platform, hashed and recorded.
bound = fake.last_request["skills"]
if ideas.skills.available():
    assert [b["id"] for b in bound["bindings"]] == ["postriff-content-craft", "postriff-channel-linkedin", "postriff-channel-threads"], bound["bindings"]
    assert all(len(b["sha256"]) == 64 for b in bound["bindings"]) and "## Skill: postriff-content-craft" in bound["text"]
    assert assistant["body"]["skills"] == [b["id"] for b in bound["bindings"]]
    assert [b["id"] for b in done["usage"]["skillBindings"]] == assistant["body"]["skills"]
else:
    assert bound["bindings"] == [] and any("No skill library" in w for w in bound["warnings"])
with connection() as db:
    ledger = db.execute("SELECT cost_state, actual_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND run_id::text=%s", (wid, run["runId"])).fetchall()
assert ("actual", 0) in ledger and not any(row[1] for row in ledger), ledger  # settled at $0: the subscription paid, PostRiff did not

# 5. The candidate applies like any other and cannot be applied against a stale hash.
applied = ideas.apply(wid, "one", service.get(wid, "one")["revision"], run["runId"], done["artifactHash"])
assert applied["status"] == "applied" and applied["variants"] == 2

# 6. Cancellation before completion wins: the late result is absorbed, status stays cancelled.
fake.release.clear()
second = ideas.turn(wid, "one", cid, {"text": "Again.", "model": "claude-code:default", "timeZone": "Asia/Hong_Kong"})
assert ideas.cancel(wid, "one", second["runId"])["status"] == "cancelled"
fake.release.set()
fake.threads[-1].join(10)
late = ideas.events(wid, "one", second["runId"])
assert late["status"] == "cancelled" and late["artifact"] is None and [e["type"] for e in late["events"]][-1] == "run.cancelled", (late["status"], [e["type"] for e in late["events"]])
cancelled_turn = next(m for m in ideas.messages(wid, "one", cid)["messages"] if m["runId"] == second["runId"] and m["role"] == "assistant")
assert cancelled_turn["body"]["cancelled"] is True and cancelled_turn["body"]["pending"] is False

# 7. A failed run reports its guidance, settles as failed and leaves no candidate.
fake.behaviour = "fail"
fake.release.clear()
third = ideas.turn(wid, "one", cid, {"text": "Once more.", "model": "claude-code:default", "timeZone": "Asia/Hong_Kong"})
fake.release.set()
fake.threads[-1].join(10)
failed = ideas.events(wid, "one", third["runId"])
assert failed["status"] == "failed" and failed["events"][-1]["type"] == "run.failed" and "claude auth login" in failed["events"][-1]["message"]
failed_turn = next(m for m in ideas.messages(wid, "one", cid)["messages"] if m["runId"] == third["runId"] and m["role"] == "assistant")
assert failed_turn["body"]["failed"] is True and "claude auth login" in failed_turn["body"]["text"]

# 8. Unknown or unqualified models are refused before any run row exists; the fixture stays the default.
try:
    ideas.turn(wid, "one", cid, {"text": "x", "model": "gpt-9"})
    raise AssertionError("accepted unknown model")
except AlphaError as error:
    assert error.status == 400
default = ideas.turn(wid, "one", cid, {"text": "Default route.", "timeZone": "Asia/Hong_Kong"})
assert default["status"] == "completed" and default["model"] == FixtureAgentRuntime.model

# 9. A quick start carries the chosen model into its first turn (the Home composer path).
fake.behaviour = "complete"
fake.release.set()
quick = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "Thought for the CLI route.", "ownContent": True, "confirmUse": True, "model": "claude-code:default", "timeZone": "Asia/Hong_Kong"})
assert quick["model"] == "claude-code:default" and quick["status"] == "running", (quick["model"], quick["status"])
fake.threads[-1].join(10)
assert ideas.events(wid, "one", quick["runId"])["status"] == "completed"
try:
    ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "x", "ownContent": True, "confirmUse": True, "model": "gpt-9"})
    raise AssertionError("quick start accepted an unknown model")
except AlphaError as error:
    assert error.status == 400

# 10. Memory files render server-side for the same workspace.
files = ideas.memory_files(wid, "one")["files"]
assert [f["name"] for f in files] == ["AGENT.md", "IDENTITY.md", "VOICE.md", "BOUNDARIES.md", "BRAND.md"]
assert "No active voice profile yet" in next(f for f in files if f["name"] == "VOICE.md")["body"]
print("postgres_cli_route: 10/10 checks passed")
