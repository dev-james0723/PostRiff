"""Phase B on the hosted repository: a standing instruction in chat becomes a pending proposal without a
run or a charge; an owner decides it in one transaction with the state (version row, style revision,
decided event); the next draft receives only the learned items that apply to its destinations; a
bad edit rolls everything back; dismiss keeps the scope quiet; pause and retire follow the state;
reset clears the tables.

Run through scripts/postriff_disposable_postgres.py (rls.sql loads migrations 004+, including 010).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha import learning
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
clock = [time.time()]
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "fixture-one":
        raise AlphaError("Verified session required", 401)
    return ONE


def denied(call, status, fragment=None):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        if fragment:
            assert fragment in str(error), str(error)
    else:
        raise AssertionError("expected a refusal")


def count(sql, *params):
    with connection() as db:
        return db.execute(sql, params).fetchone()[0]


with connection() as db:
    wid = str(db.execute("select workspace_id from public.pr_memberships where user_id=%s", (ONE,)).fetchone()[0])
    db.execute("update public.pr_workspaces set state='{}'::jsonb where id=%s", (wid,))
    db.execute("update public.pr_memberships set status='active', role='owner' where user_id=%s", (ONE,))
    for table in ("pr_memory_versions", "pr_memory_proposals", "pr_learning_events"):
        db.execute(f"delete from public.{table} where workspace_id=%s", (wid,))
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
ideas = service.ideas
snapshot = service.bootstrap("fixture-one", "studio")


def act(action, payload):
    global snapshot
    snapshot = service.mutate(wid, "fixture-one", snapshot["revision"], action, payload)
    return snapshot["state"]


def state():
    global snapshot
    snapshot = service.get(wid, "fixture-one")
    return snapshot["state"]


act("mode", {"mode": "personal"})
act("context", {"purpose": "Make community learning accessible", "audience": "Curious beginners", "subject": "Community workshops", "speaker": "My voice", "layers": []})
act("source", {"kind": "sample"})
source = snapshot["state"]["sources"][-1]
act("approve_source", {"sourceId": source["id"], "factIds": [fact["id"] for fact in source["facts"]]})
act("source_done", {})
act("profile_propose", {"writing": "A small step can be a useful beginning.", "tone": "warm"})
act("profile_decide", {"decision": "approve"})
act("runtime", {"selected": "deterministic-preview"})
cid = ideas.create_conversation(wid, "fixture-one", "preferences")["conversationId"]
runs_before, ledger_before = count("select count(*) from public.pr_agent_runs where workspace_id=%s", wid), count("select count(*) from public.pr_usage_ledger where workspace_id=%s", wid)

# 1. A standing instruction becomes a pending proposal: no run, no reservation, a card in the reply.
turn = ideas.turn(wid, "fixture-one", cid, {"text": "以後 LinkedIn 唔好用 emoji", "timeZone": "Asia/Hong_Kong"})
assert turn["status"] == "memory" and turn["runId"] is None and turn["usage"]["modelRequests"] == 0
proposal = turn["memoryProposal"]
assert proposal and proposal["status"] == "pending" and proposal["statement"] == "No emoji." and proposal["scope"]["platform"] == "LinkedIn" and proposal["scopeLabel"] == "LinkedIn · all languages"
assert count("select count(*) from public.pr_agent_runs where workspace_id=%s", wid) == runs_before
assert count("select count(*) from public.pr_usage_ledger where workspace_id=%s", wid) == ledger_before
assert count("select count(*) from public.pr_memory_proposals where workspace_id=%s and status='pending'", wid) == 1
assert count("select count(*) from public.pr_learning_events where workspace_id=%s and kind='chat.instruction'", wid) == 1
messages = ideas.messages(wid, "fixture-one", cid)["messages"]
assert messages[-1]["role"] == "assistant" and messages[-1]["body"]["memoryProposal"]["id"] == proposal["id"] and messages[-1]["runId"] is None
listing = service.learning.proposals(service.repository, wid, "fixture-one")
assert [p["id"] for p in listing["pending"]] == [proposal["id"]] and listing["learning"]["items"] == []
assert ideas.memory_files(wid, "fixture-one")["learning"]["pendingProposals"] == 1
checks.append("a chat instruction becomes a pending proposal with no run, no charge, and a card in the reply")

# 2. The same instruction again asks nothing new; a fact is refused with the lint's reason.
again = ideas.turn(wid, "fixture-one", cid, {"text": "以後 LinkedIn 唔好用 emoji", "timeZone": "Asia/Hong_Kong"})
assert again["memoryProposal"] is None and "already" in ideas.messages(wid, "fixture-one", cid)["messages"][-1]["body"]["text"]
fact = ideas.turn(wid, "fixture-one", cid, {"text": "Remember that I have 20 years of experience.", "timeZone": "Asia/Hong_Kong"})
assert fact["memoryProposal"] is None and "about you" in ideas.messages(wid, "fixture-one", cid)["messages"][-1]["body"]["text"]
assert count("select count(*) from public.pr_memory_proposals where workspace_id=%s", wid) == 1
checks.append("a repeated instruction proposes nothing new; a fact is refused with the reason")

# 3. Only an owner decides; an edit the lint refuses rolls the whole decision back.
with connection() as db:
    db.execute("update public.pr_memberships set role='editor', can_publish=true where user_id=%s", (ONE,))
state()
denied(lambda: service.learning.decide(service.repository, wid, "fixture-one", snapshot["revision"], proposal["id"], "remember"), 403)
with connection() as db:
    db.execute("update public.pr_memberships set role='owner' where user_id=%s", (ONE,))
state()
denied(lambda: service.learning.decide(service.repository, wid, "fixture-one", snapshot["revision"], proposal["id"], "edit", "Use 3 emoji per post."), 400, "number")
assert count("select count(*) from public.pr_memory_proposals where workspace_id=%s and status='pending'", wid) == 1
assert count("select count(*) from public.pr_memory_versions where workspace_id=%s", wid) == 0
assert learning.active_items(state()) == []
checks.append("deciding is owner-only, and a refused edit leaves proposal, versions and state untouched")

# 4. Remember: a version row, a style revision, a decided event, VOICE.md, and the pending count drops.
decided = service.learning.decide(service.repository, wid, "fixture-one", snapshot["revision"], proposal["id"], "edit", "No emoji on LinkedIn.")
assert decided["status"] == "edited" and decided["item"]["id"] == proposal["id"] and decided["item"]["statement"] == "No emoji on LinkedIn." and decided["versionId"]
current = state()
assert current["learning"]["revision"] == 1 and current["speaker"]["activeRevision"] == 1
assert [i["statement"] for i in learning.active_items(current)] == ["No emoji on LinkedIn."]
assert count("select count(*) from public.pr_memory_versions where workspace_id=%s and status='active' and valid_to is null", wid) == 1
assert count("select count(*) from public.pr_learning_events where workspace_id=%s and kind='proposal.decided'", wid) == 1
files = ideas.memory_files(wid, "fixture-one")
assert files["learning"]["pendingProposals"] == 0 and "- [LinkedIn · all languages] No emoji on LinkedIn. — you edited the wording" in next(f["body"] for f in files["files"] if f["name"] == "VOICE.md")
denied(lambda: service.learning.decide(service.repository, wid, "fixture-one", snapshot["revision"], proposal["id"], "dismiss"), 409)
checks.append("remembering writes the version and the style revision in one transaction and VOICE.md shows it")

# 5. The next draft receives only the items that apply to its destinations, recorded on the run.
linkedin = ideas.turn(wid, "fixture-one", cid, {"text": "Write about the seed swap.", "destinations": [{"platform": "LinkedIn", "language": "English"}], "timeZone": "Asia/Hong_Kong"})
assert linkedin["status"] == "completed" and linkedin["usage"]["memoryBindings"]["used"] == [proposal["id"]] and linkedin["usage"]["memoryBindings"]["styleRevision"] == 1
instagram = ideas.turn(wid, "fixture-one", cid, {"text": "Write about the seed swap for Instagram.", "destinations": [{"platform": "Instagram", "language": "繁體中文"}], "timeZone": "Asia/Hong_Kong"})
assert instagram["status"] == "completed" and instagram["usage"]["memoryBindings"]["used"] == []
last = ideas.messages(wid, "fixture-one", cid)["messages"][-1]["body"]
assert last["memory"] == instagram["usage"]["memoryBindings"]
checks.append("the next LinkedIn draft carries the learned item and the Instagram draft does not; both runs record the binding")

# 6. Dismiss keeps the scope quiet; pause and retire follow the state into the version row.
second = ideas.turn(wid, "fixture-one", cid, {"text": "From now on no hashtags on Threads.", "timeZone": "Asia/Hong_Kong"})["memoryProposal"]
state()
service.learning.decide(service.repository, wid, "fixture-one", snapshot["revision"], second["id"], "dismiss")
assert ideas.turn(wid, "fixture-one", cid, {"text": "From now on no hashtags on Threads.", "timeZone": "Asia/Hong_Kong"})["memoryProposal"] is None
state()
paused = service.learning.update_version(service.repository, wid, "fixture-one", snapshot["revision"], proposal["id"], "paused")
assert paused["status"] == "paused" and count("select count(*) from public.pr_memory_versions where workspace_id=%s and status='paused'", wid) == 1
assert learning.select(state(), [{"platform": "LinkedIn", "language": "English"}])[0] == []
retired = service.learning.update_version(service.repository, wid, "fixture-one", snapshot["revision"], proposal["id"], "retired")
assert retired["status"] == "retired" and count("select count(*) from public.pr_memory_versions where workspace_id=%s and valid_to is not null", wid) == 1
assert learning.active_items(state()) == [] and state()["learning"]["retired"][0]["id"] == proposal["id"]
checks.append("dismiss suppresses the scope; pause and retire update the version row with the state")

# 7. Reset clears the tables together with the state; an editor cannot reset.
with connection() as db:
    db.execute("update public.pr_memberships set role='editor' where user_id=%s", (ONE,))
state()
denied(lambda: act("learning_reset", {"confirmed": True}), 403)
with connection() as db:
    db.execute("update public.pr_memberships set role='owner' where user_id=%s", (ONE,))
state()
reset = act("learning_reset", {"confirmed": True})
assert reset["learning"]["active"] == [] and reset["learning"]["retired"] == [] and reset["learning"]["resetAt"]
for table in ("pr_memory_versions", "pr_memory_proposals", "pr_learning_events"):
    assert count(f"select count(*) from public.{table} where workspace_id=%s", wid) == 0, table
checks.append("reset is owner-only and clears versions, proposals and events with the state")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
