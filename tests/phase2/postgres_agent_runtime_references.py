"""Chips on an Agent Runtime v2 turn on disposable PostgreSQL (chat-context SPEC §9; PLAN S33): a post and a source chip
reach the writing pipeline through the Manager's `draft_create` (the run records the "Used this time" report), the chip ids
are never counted as reads, malformed chips are refused before anything is stored, and with the runtime off the site agent
answers the same message and reports the chips unused. Deterministic stand-ins only for the model (ScriptedModel).
"""
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")
import psycopg  # noqa: E402
try:
    from agents.testing import ScriptedModel, assistant_message, function_call  # noqa: E402
except ImportError:
    print(json.dumps({"status": "SKIPPED", "script": "postgres_agent_runtime_references", "reason": "openai-agents is not installed in this Python"}), flush=True)
    sys.exit(0)
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.agent_runtime_v2 import config  # noqa: E402
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from consumer_fixtures import approve_budgets  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
OWNER = "one-token-000000000000000000"
clock = [1_790_128_800.0]
passed = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != OWNER:
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: "session-refs-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    passed.append(name)


class ScriptBook:
    def __init__(self):
        self.models = {}

    def set(self, **steps):
        self.models = {name: ScriptedModel(value) for name, value in steps.items()}

    def factory(self, _workload, name):
        return self.models.setdefault(name, ScriptedModel([]))


def reply(answer):
    return assistant_message(json.dumps({"answer": answer, "speakable": answer, "language": "en", "follow_ups": []}))


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
service.bootstrap(OWNER, "studio")
approve_budgets(connection, wid)
ideas = service.ideas

# A draft and a usable source to put on the message as chips.
quick = ideas.quick_start(wid, OWNER, service.get(wid, OWNER)["revision"], {"text": "Slow practice builds accuracy.\nOne bar, three times, half speed.", "ownContent": True,
                                                                             "confirmUse": True, "destinations": [{"platform": "Instagram", "language": "en"}]})
ideas.apply(wid, OWNER, service.get(wid, OWNER)["revision"], quick["runId"], quick["artifactHash"])
draft = service.get(wid, OWNER)["state"]["variants"][0]
source_id = quick["sourceId"]

SCRIPTS = ScriptBook()
CFG = config.RuntimeConfig.from_environment({"OPENAI_API_KEY": "-".join(["fake", "project", "credential"]), "RAFII_AGENT_V2_ENABLED": "1", "RAFII_SPECIALISTS_ENABLED": "1"})
runtime = AgentRuntimeService(service, CFG, model_factory=SCRIPTS.factory, clock=lambda: clock[0])
conversation = ideas.create_conversation(wid, OWNER, "chips")["conversationId"]
chips = [{"kind": "post", "id": draft["id"], "label": "My practice post", "role": "inspire"}, {"kind": "source", "id": source_id, "label": "Practice notes"}]

# 1. Chips through the Manager → content specialist → draft_create: the writing run carries them and reports them.
SCRIPTS.set(rafii_manager=[[function_call("ask_content", {"input": "Write a LinkedIn post from the attached post and source."}, call_id="m1")],
                           [reply("I wrote a LinkedIn draft from your post and notes.")]],
            content=[[function_call("draft_create", {"brief": "A LinkedIn post about slow practice.", "platforms": ["LinkedIn"]}, call_id="d1")],
                     [assistant_message("Drafted.")]])
result = runtime.turn(wid, OWNER, {"message": "Write a LinkedIn post from these", "idempotencyKey": uuid.uuid4().hex, "conversationId": conversation, "references": chips})
with connection() as db:
    runs = db.execute("SELECT usage FROM public.pr_agent_runs WHERE conversation_id::text=%s AND idempotency_key LIKE 'agent-draft:%%' ORDER BY created_at", (conversation,)).fetchall()
check("manager turn answered", bool((result.get("result") or {}).get("answerText")), result.get("result"))
check("one writing run from draft_create", len(runs) == 1, len(runs))
report = (runs[0][0] or {}).get("references") if runs else None
check("the writing run carries the chips and reports them", isinstance(report, dict) and {u["id"] for u in report["used"] + report["unused"]} == {draft["id"], source_id}, report)
check("no client label reaches the report", "My practice post" not in json.dumps(report) and "Practice notes" not in json.dumps(report), report)
check("chip ids are not listed as things Rafii read", draft["id"] not in json.dumps((result.get("result") or {}).get("references") or []), (result.get("result") or {}).get("references"))

# 2. Malformed chips are refused before anything is stored.
with connection() as db:
    before = db.execute("SELECT count(*) FROM public.pr_messages WHERE conversation_id::text=%s", (conversation,)).fetchone()[0]
try:
    runtime.turn(wid, OWNER, {"message": "x", "idempotencyKey": uuid.uuid4().hex, "conversationId": conversation, "references": [{"kind": "post"}]})
    check("malformed chips refused", False)
except AlphaError as error:
    check("malformed chips refused (400)", error.status == 400, error.status)
with connection() as db:
    after = db.execute("SELECT count(*) FROM public.pr_messages WHERE conversation_id::text=%s", (conversation,)).fetchone()[0]
check("nothing stored for a refused turn", after == before, (before, after))

# 3. The runtime off: the site agent answers the same message and keeps the chips (reported, never dropped).
off = AgentRuntimeService(service, config.RuntimeConfig.from_environment({}), model_factory=SCRIPTS.factory, clock=lambda: clock[0])
fallback = off.turn(wid, OWNER, {"message": "How do I connect Instagram?", "idempotencyKey": uuid.uuid4().hex, "conversationId": conversation, "references": chips[:1]})
site = fallback.get("siteAgent") or {}
message = site.get("message") or {}
check("fallback: answered by the site agent", fallback.get("fallback") is not None, fallback.get("fallback"))
check("fallback: the chip is reported unused, not dropped", [(u["kind"], u["reason"]) for u in (message.get("references") or {}).get("unused", [])] == [("post", "not_a_drafting_turn")],
      message.get("references"))

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": passed}, indent=2))
