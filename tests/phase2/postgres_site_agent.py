"""Rafii's side panel on the hosted repository (site agent spec §5.3, §13, §14, §17): a question from any page is a
conversation turn and a run on the existing tables; answers are grounded and cited; a selected post is diagnosed from
its record; a writer model only phrases the answer, its cost is reserved before and settled after, and an answer that
claims an action is thrown away; a viewer gets grounded answers but no drafting and no model spend; writing requests go
through the writing pipeline unchanged; an automation change is a proposal applied through a workspace command that
refuses stale or tampered proposals; another workspace's conversations, runs, posts and proposals are unreachable;
stalled and cancelled answers end cleanly; feedback, help and owner insights work over HTTP too.

Run through scripts/postriff_pg_suite.py postgres_site_agent (PYTHONPATH=src:tests).
"""
import io
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2 import campaigns
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.learning_model import ModelResponse
from consumer_fixtures import approve_budgets

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000004"
THREE = "00000000-0000-0000-0000-000000000003"
TOKENS = {"one-token-000000000000000000": ONE, "two-token-000000000000000000": TWO, "three-token-00000000000000000": THREE}
OWNER, OTHER, VIEWER = list(TOKENS)
HK = "Asia/Hong_Kong"
clock = [time.time()]


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required.", 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: f"session-{principal}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def denied(call, status=None, code=None):
    try:
        call()
    except AlphaError as error:
        assert status is None or error.status == status, (error.status, str(error))
        assert code is None or error.code == code, (error.code, str(error))
        return error
    raise AssertionError("call was accepted")


def one(sql, *params):
    with connection() as db:
        return db.execute(sql, params).fetchone()


with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s),(%s) ON CONFLICT DO NOTHING", (THREE, TWO))
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
    db.execute("UPDATE public.pr_memberships SET status='active', role='owner' WHERE user_id=%s", (ONE,))

service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
service.bootstrap(OWNER, "studio")
other = service.bootstrap(OTHER, "studio")["workspaceId"]
service.bootstrap(VIEWER, "studio")
assert other != wid
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active')", (wid, THREE))
approve_budgets(connection, wid)
agent = service.site_agent
ideas = service.ideas


def state():
    return service.get(wid, OWNER)["state"]


def revision():
    return service.get(wid, OWNER)["revision"]


def command(fn, token=OWNER, workspace=None):
    workspace = workspace or wid
    return service.repository.command(workspace, token, service.get(workspace, token)["revision"], fn)


channel = {"id": uuid.uuid4().hex, "platform": "LinkedIn", "account": "Studio page", "accountType": "member", "language": "English", "scopes": ["w_member_social"],
           "verifiedAt": clock[0], "expiresAt": clock[0] + 10**8, "capabilityVersion": 1, "providerAccountId": "urn:test:studio"}
command(lambda s, actor: service.commands.upsert_verified_channel(s, actor, channel))
HELD = "job-" + uuid.uuid4().hex[:12]


def add_held_job(s, actor):
    s.setdefault("phase2", {}).setdefault("jobs", []).append({
        "id": HELD, "state": "held", "attempts": [], "approvedAt": clock[0] - 100, "approvedBy": actor,
        "manifest": {"platform": "LinkedIn", "account": "Studio page", "channelId": channel["id"], "variantId": "v-held", "payload": {"text": "Slow practice.", "language": "en"},
                     "timing": {"timestamp": clock[0] + 3600, "local": "2026-09-26T16:30", "timeZone": HK}, "execution": "synthetic"},
        "events": [{"at": clock[0] - 50, "state": "held", "message": "Access for the account changed after approval. Bearer abcdefghijklmnopqrstuvwxyz0123"}]})
    return s


command(add_held_job)


class Writer:
    """A managed writer stand-in: the same call shape as request_model.call_for's GatewayCall."""
    local = False
    model = "anthropic/claude-haiku-4.5"

    def __init__(self):
        self.calls, self.answer = [], None

    def __call__(self, system, user, schema):
        self.calls.append((system, user))
        return ModelResponse(self.answer(user) if callable(self.answer) else self.answer, 2345)


writer = Writer()


def ask(message, token=OWNER, workspace=None, **extra):
    body = {"message": message, "idempotencyKey": uuid.uuid4().hex, "model": "deterministic-preview", "timeZone": HK, **extra}
    return agent.turn(workspace or wid, token, body)


def blocks(result, kind=None):
    items = result["message"]["siteAgent"]["blocks"]
    return [b for b in items if kind is None or b["type"] == kind]


# 1. A page question is a conversation turn and a run on the existing tables, answered from help with citations.
first = ask("What is this page?", pageContext={"route": "/app/queue"}, idempotencyKey="k-first")
assert (first["status"], first["needsCompose"]) == ("completed", False), first
run = one("SELECT status,model,reasoning,length(policy_epoch),length(context_digest),idempotency_key FROM public.pr_agent_runs WHERE id::text=%s", first["runId"])
assert run == ("completed", "deterministic-preview", "quick", 64, 64, "site:k-first"), run
kinds = [e["type"] for e in first["events"]]
assert kinds[0] == "run.started" and kinds[-1] == "run.completed" and "artifact.created" in kinds and "message.completed" in kinds, kinds
assert any(e.get("stage") == "tool" and e.get("tool") == "queue.summary" and e.get("status") == "verified" for e in first["events"]), first["events"]
assert blocks(first, "citation_list") and blocks(first, "citation_list")[0]["citations"][0]["href"].startswith("/app/help/"), blocks(first)
site = first["message"]["siteAgent"]
assert site["context"]["read"] and "passwords, tokens and keys" in site["context"]["withheld"], site["context"]
messages = ideas.messages(wid, OWNER, first["conversationId"])["messages"]
assert [m["role"] for m in messages] == ["user", "assistant"] and messages[0]["body"]["siteAgent"]["page"]["routeId"] == "queue", messages
runs = one("SELECT count(*) FROM public.pr_agent_runs WHERE workspace_id=%s", wid)[0]
again = ask("What is this page?", pageContext={"route": "/app/queue"}, idempotencyKey="k-first")
assert again["runId"] == first["runId"] and one("SELECT count(*) FROM public.pr_agent_runs WHERE workspace_id=%s", wid)[0] == runs, "replayed, not repeated"
follow = ask("And what does held mean?", conversationId=first["conversationId"], pageContext={"route": "/app/queue"})
assert follow["conversationId"] == first["conversationId"]
assert len(ideas.messages(wid, OWNER, first["conversationId"])["messages"]) == 4
replay = agent.events(wid, OWNER, follow["runId"], 2)
assert replay["events"] and all(e["seq"] > 2 for e in replay["events"]), replay

# 2. A selected post is diagnosed from its own record, redacted.
held = ask("Why didn't this publish?", pageContext={"route": "/app/queue", "selectedEntity": {"type": "job", "id": HELD}})
card = blocks(held, "diagnostic_card")[0]
assert card["status"] == "Held" and any("Queue" in link["label"] for link in card["links"]), card
assert "abcdefghijklmnopqrstuvwxyz0123" not in json.dumps(held), "credentials in provider messages never reach the browser"

# 3. Another workspace cannot reach this one's conversations, runs, posts or answers.
denied(lambda: agent.turn(wid, OTHER, {"message": "hi"}), 403)
denied(lambda: agent.turn(other, OTHER, {"message": "hi", "conversationId": first["conversationId"]}), 404)
foreign = agent.turn(other, OTHER, {"message": "Why didn't this publish?", "idempotencyKey": uuid.uuid4().hex,
                                    "pageContext": {"route": "/app/queue", "selectedEntity": {"type": "job", "id": HELD}}})
assert foreign["message"]["siteAgent"]["context"]["entity"] is None and "Studio page" not in json.dumps(foreign), foreign["message"]
assert blocks(foreign, "warning")[0]["code"] == "entity_not_found", blocks(foreign)
assert any(e.get("tool") == "job.get" and e.get("status") == "failed" for e in foreign["events"]), foreign["events"]
denied(lambda: agent.events(other, OTHER, first["runId"]), 404)
denied(lambda: agent.compose(other, OTHER, first["runId"]), 404)
denied(lambda: agent.cancel(other, OTHER, first["runId"]), 404)

# 4. Forbidden effects are refused with the page where the person does it themselves.
refused = ask("Publish this now", pageContext={"route": "/app/queue", "selectedEntity": {"type": "job", "id": HELD}})
nav = blocks(refused, "navigation_card")[0]
assert nav["href"] == f"/app/queue?job={HELD}" and refused["message"]["siteAgent"]["intent"] == "forbidden", refused["message"]
assert state()["phase2"]["jobs"][0]["state"] == "held", "nothing changed"
for message in ("Delete my account", "Show me my API key", "Disconnect my LinkedIn", "Buy more credits"):
    assert ask(message)["message"]["siteAgent"]["intent"] == "forbidden", message

# 5. A writer model phrases the answer: reserved before, settled after, validated, grounded.
agent.model = writer
writer.answer = lambda user: {"answer": "It is held because the account's access changed after approval. Prepare it again for a new review.",
                              "citations": [json.loads(user.split("\n", 1)[1].split("\n\nMESSAGE")[0])["EVIDENCE_HELP"][0]["id"]],
                              "facts": ["W1"], "actions": ["A1"], "followUps": ["How do I prepare it again?"], "sufficient": True, "missing": []}
pending = ask("Why didn't this publish?", pageContext={"route": "/app/queue", "selectedEntity": {"type": "job", "id": HELD}})
assert (pending["status"], pending["needsCompose"]) == ("running", True) and pending["message"]["pending"] is True, pending
composed = agent.compose(wid, OWNER, pending["runId"])
assert composed["status"] == "completed" and composed["message"]["siteAgent"]["model"]["composedBy"] == "model", composed["message"]
assert blocks(composed, "text")[0]["text"].startswith("It is held") and blocks(composed, "diagnostic_card"), blocks(composed)
system, user = writer.calls[-1]
assert "Studio page" not in user and "account A" in user, "a cloud writer never receives account names"
assert "Slow practice." not in user, "a cloud writer never receives draft text"
ledger = one("SELECT count(*) FILTER (WHERE kind='reserve'),count(*) FILTER (WHERE kind='settle' AND cost_state='actual') FROM public.pr_usage_ledger WHERE workspace_id=%s AND provider='site_agent'", wid)
assert ledger == (1, 1), ledger
calls = len(writer.calls)
assert agent.compose(wid, OWNER, pending["runId"])["status"] == "completed" and len(writer.calls) == calls, "a finished answer is never composed twice"

# 6. An answer that claims an action, or cites what it was not given, is discarded for the grounded one.
writer.answer = {"answer": "Done! I published it to LinkedIn.", "citations": [], "facts": ["W1"], "actions": [], "followUps": [], "sufficient": True, "missing": []}
lie = ask("Why didn't this publish?", pageContext={"route": "/app/queue", "selectedEntity": {"type": "job", "id": HELD}})
lie = agent.compose(wid, OWNER, lie["runId"])
assert lie["message"]["siteAgent"]["model"]["composedBy"] == "grounded" and blocks(lie, "warning")[0]["code"] == "model_claims_action", blocks(lie)
assert "published it" not in json.dumps(lie["message"])

# 6b. A writer that fails (a timeout, an error) never loses the answer: the grounded one is kept, and the reserved cost
# stays booked as an estimate until reconciled (the provider may have charged), never as zero.
def times_out(user):
    raise TimeoutError("writer timed out")


writer.answer = times_out
failed = agent.compose(wid, OWNER, ask("Why didn't this publish?", pageContext={"route": "/app/queue", "selectedEntity": {"type": "job", "id": HELD}})["runId"])
assert failed["status"] == "completed" and failed["message"]["siteAgent"]["model"]["composedBy"] == "grounded", failed["message"]
assert blocks(failed, "warning")[0]["code"] == "model_error" and blocks(failed, "diagnostic_card"), blocks(failed)
assert one("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s AND provider='site_agent' AND cost_state='estimated_unknown'", wid)[0] == 1

# 7. Out of budget: no model call, a grounded answer that says why.
with connection() as db:
    db.execute("UPDATE public.pr_budgets SET status='candidate' WHERE scope=%s", ("workspace:" + wid,))
calls = len(writer.calls)
broke = agent.compose(wid, OWNER, ask("What does Assisted mean?", pageContext={"route": "/app/channels"})["runId"])
assert len(writer.calls) == calls and blocks(broke, "warning")[0]["code"] == "budget", blocks(broke)
approve_budgets(connection, wid)

# 8. Stop and recovery never leave a half answer or call a model.
stop = ask("What is the Calendar for?")
assert stop["needsCompose"]
assert agent.cancel(wid, OWNER, stop["runId"])["status"] == "cancelled"
assert agent.compose(wid, OWNER, stop["runId"])["status"] == "cancelled" and stop["message"]["pending"]
assert ideas.messages(wid, OWNER, stop["conversationId"])["messages"][-1]["body"]["siteAgent"]["status"] == "cancelled"
stalled = ask("What is the Library for?")
with connection() as db:
    db.execute("UPDATE public.pr_agent_runs SET updated_at=now()-interval '10 minutes' WHERE id::text=%s", (stalled["runId"],))
assert agent.recover_stalled()["recovered"] >= 1
recovered = agent.events(wid, OWNER, stalled["runId"])
assert recovered["status"] == "completed" and blocks(recovered, "warning")[0]["code"] == "composition_interrupted", recovered["message"]
agent.model = None

# 9. A viewer gets grounded answers, no writer spend and no drafting.
writer_runs = one("SELECT count(*) FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key NOT LIKE 'site:%%'", wid)[0]
agent.model = writer
viewer = ask("What is this page?", token=VIEWER, pageContext={"route": "/app/calendar"})
assert viewer["needsCompose"] is False and blocks(viewer, "warning")[0]["code"] == "role_grounded", blocks(viewer)
agent.model = None
draft_refused = ask("Write a LinkedIn post about practising slowly", token=VIEWER)
assert draft_refused["message"]["siteAgent"]["intent"] == "forbidden" and "role" in draft_refused["message"]["text"], draft_refused["message"]
assert one("SELECT count(*) FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key NOT LIKE 'site:%%'", wid)[0] == writer_runs
denied(lambda: agent.insights(wid, VIEWER), 403)

# 10. Writing requests go through the writing pipeline unchanged, in the same conversation.
DESTINATIONS = [{"platform": "LinkedIn", "language": "en", "channelId": channel["id"]}]
drafted = ask("Write a LinkedIn post about practising slowly", destinations=DESTINATIONS)
assert drafted["delegated"] and drafted["kind"] == "draft" and drafted["runId"], drafted
assert one("SELECT idempotency_key NOT LIKE 'site:%%',status FROM public.pr_agent_runs WHERE id::text=%s", drafted["runId"]) == (True, "completed")
automation = ask("Every Friday at 4pm draft a post about practice habits for LinkedIn", destinations=DESTINATIONS)
assert automation["delegated"] and automation["status"] == "automation", automation
task_id = automation["result"]["automation"]["taskId"]

# 11. An automation change is a proposal; applying it re-runs the edit in one command and refuses stale proposals.
before = campaigns.definition_digest(next(t for t in state()["raffi"]["campaignPlanning"]["recurringTasks"] if t["id"] == task_id))
asked = ask("Move it to Thursday at 18:00", pageContext={"route": "/app/automations", "selectedEntity": {"type": "automation", "id": task_id}})
proposal = asked["message"]["siteAgent"]["proposals"][0]
assert proposal["status"] == "proposed" and blocks(asked, "proposal_diff"), asked["message"]
assert campaigns.definition_digest(next(t for t in state()["raffi"]["campaignPlanning"]["recurringTasks"] if t["id"] == task_id)) == before, "nothing changes before apply"
target = {"conversationId": asked["conversationId"], "messageId": asked["messageId"], "proposalId": proposal["id"]}
denied(lambda: agent.apply_proposal(wid, OWNER, {**target, "digest": "0" * 64, "expectedRevision": revision()}), 409, "proposal_digest")
denied(lambda: agent.apply_proposal(other, OTHER, {**target, "digest": proposal["digest"], "expectedRevision": 1}), 404)
denied(lambda: agent.apply_proposal(wid, VIEWER, {**target, "digest": proposal["digest"], "expectedRevision": revision()}), 403)
applied = agent.apply_proposal(wid, OWNER, {**target, "digest": proposal["digest"], "expectedRevision": revision(), "timeZone": HK})
assert applied["proposal"]["status"] == "applied", applied["proposal"]
changed = next(t for t in state()["raffi"]["campaignPlanning"]["recurringTasks"] if t["id"] == task_id)
assert campaigns.definition_digest(changed) != before and "Thursday" in json.dumps(changed["schedule"]), changed["schedule"]
assert one("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s AND kind='automation.changed_by_proposal' AND subject=%s", wid, task_id)[0] == 1
denied(lambda: agent.apply_proposal(wid, OWNER, {**target, "digest": proposal["digest"], "expectedRevision": revision()}), 409, "proposal_closed")
older = ask("Move it to Monday at 09:00", pageContext={"route": "/app/automations", "selectedEntity": {"type": "automation", "id": task_id}})
newer = ask("Move it to Tuesday at 10:00", pageContext={"route": "/app/automations", "selectedEntity": {"type": "automation", "id": task_id}})
for turn in (newer,):
    p = turn["message"]["siteAgent"]["proposals"][0]
    agent.apply_proposal(wid, OWNER, {"conversationId": turn["conversationId"], "messageId": turn["messageId"], "proposalId": p["id"], "digest": p["digest"], "expectedRevision": revision()})
stale = older["message"]["siteAgent"]["proposals"][0]
stale_target = {"conversationId": older["conversationId"], "messageId": older["messageId"], "proposalId": stale["id"], "digest": stale["digest"]}
denied(lambda: agent.apply_proposal(wid, OWNER, {**stale_target, "expectedRevision": revision()}), 409, "proposal_stale")
stored = ideas.messages(wid, OWNER, older["conversationId"])["messages"]
assert next(m for m in stored if m["messageId"] == older["messageId"])["body"]["siteAgent"]["proposals"][0]["status"] == "superseded"
dismissable = ask("Move it to Wednesday at 07:00", pageContext={"route": "/app/automations", "selectedEntity": {"type": "automation", "id": task_id}})
d = dismissable["message"]["siteAgent"]["proposals"][0]
assert agent.dismiss_proposal(wid, OWNER, {"conversationId": dismissable["conversationId"], "messageId": dismissable["messageId"], "proposalId": d["id"]})["proposal"]["status"] == "dismissed"

# 12. Feedback, help and owner insights, over HTTP (origin guard, routing, JSON).
app = HostedApplication(service=service, worker=None, public_auth={}, cron_secret="x" * 32)


def http(method, path, body=None, token=OWNER, guard=True):
    raw = json.dumps(body).encode() if body is not None else b""
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
               "wsgi.input": io.BytesIO(raw), "HTTP_AUTHORIZATION": "Bearer " + token, "HTTP_HOST": "localhost", "HTTP_X_FORWARDED_PROTO": "http"}
    if guard:
        environ["HTTP_X_POSTRIFF_REQUEST"] = "founder-alpha"
    status = []
    chunks = app(environ, lambda s, h, e=None: status.append(int(s.split()[0])))
    return status[0], json.loads(b"".join(chunks) or b"{}")


code, turned = http("POST", f"/api/workspaces/{wid}/site-agent/turns", {"message": "Where do I connect LinkedIn?", "idempotencyKey": uuid.uuid4().hex, "pageContext": {"route": "/app"}})
assert code == 201 and turned["status"] == "completed", (code, turned)
assert http("POST", f"/api/workspaces/{wid}/site-agent/turns", {"message": "hi"}, guard=False)[0] == 403, "the request guard applies"
code, rated = http("POST", f"/api/workspaces/{wid}/site-agent/feedback", {"messageId": turned["messageId"], "value": "not_helpful", "reason": "unclear"})
assert code == 200 and rated["feedback"]["value"] == "not_helpful", rated
assert http("POST", f"/api/workspaces/{wid}/site-agent/feedback", {"messageId": turned["messageId"], "value": "meh"})[0] == 400
code, catalogue = http("GET", f"/api/workspaces/{wid}/site-agent/help")
assert code == 200 and any(d["documentId"] == "help_approvals" for d in catalogue["documents"]), catalogue
code, doc = http("GET", f"/api/workspaces/{wid}/site-agent/help/help_approvals")
assert code == 200 and doc["sections"][0]["anchor"], doc
assert http("GET", f"/api/workspaces/{wid}/site-agent/help/nope")[0] == 404
code, insights = http("GET", f"/api/workspaces/{wid}/site-agent/insights")
assert code == 200 and insights["turns"] >= 10 and insights["feedback"].get("not_helpful") == 1 and insights["outcomes"].get("blocked", 0) >= 1, insights
assert http("GET", f"/api/workspaces/{wid}/site-agent/insights", token=VIEWER)[0] == 403
print("postgres_site_agent: ok")
