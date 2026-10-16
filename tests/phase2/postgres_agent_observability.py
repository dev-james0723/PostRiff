"""P0.7 agent observability on the real hosted services and a disposable PostgreSQL (CI only: scripts/postriff_pg_suite.py).

One scripted Manager turn (Agents SDK ScriptedModel, no provider call) runs twice in fresh conversations: once with
observability on, once with POSTRIFF_AGENT_OBSERVABILITY=0. Proves:
- OB01 correlation: request → plan → tool → verify → response lines share the request id and the stored run's trace id and run
  id, in order, from the real gate (tool_adapter.execute → RafiiRunContext.activity) and the real _persist.
- OB02 content-free: the person's message, the plan title, the answer, the conversation title, the session token and the
  workspace id never appear in any line.
- OB03 golden: what the turn returns and stores (pr_agent_runs artifact and usage, pr_messages bodies, pr_agent_events) is the
  same with observability on and off, after masking only ids and timings.
"""
import json
import logging
import os
import re
import sys
import time
import traceback
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
    print(json.dumps({"status": "SKIPPED", "script": "postgres_agent_observability", "reason": "openai-agents is not installed in this Python"}), flush=True)
    sys.exit(0)
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import agent_observability as obs  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.agent_runtime_v2 import config  # noqa: E402
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService  # noqa: E402
from consumer_fixtures import approve_budgets  # noqa: E402

PORT = os.environ.get("POSTRIFF_PG_PORT", "55438")
DSN = os.environ.get("POSTRIFF_TEST_DSN") or f"host=127.0.0.1 port={PORT} dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
OWNER = "one-token-000000000000000000"
clock = [1_790_128_800.0]
PRIVATE = "PRIVATE-PHRASE-zebra-7f3a"
FAILURES = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != OWNER:
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: f"session-{principal}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(sid, title):
    def wrap(fn):
        try:
            fn()
            print(f"PASS    {sid} {title}", flush=True)
        except Exception as error:  # noqa: BLE001
            FAILURES.append(sid)
            print(f"FAIL    {sid} {title} — {type(error).__name__}: {error}\n{traceback.format_exc()[-1500:]}", flush=True)
        return fn
    return wrap


class ScriptBook:
    def __init__(self):
        self.models = {}

    def set(self, **steps):
        self.models = {name: ScriptedModel(value) for name, value in steps.items()}

    def factory(self, _workload, name):
        if name not in self.models:
            self.models[name] = ScriptedModel([])
        return self.models[name]


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET status='active', role='owner' WHERE user_id=%s", (ONE,))
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
service.bootstrap(OWNER, "studio")
approve_budgets(connection, wid)
SCRIPTS = ScriptBook()
CFG = config.RuntimeConfig.from_environment({"OPENAI_API_KEY": "-".join(["fake", "key", "for", "tests"]), "RAFII_AGENT_V2_ENABLED": "1"})
runtime = AgentRuntimeService(service, CFG, model_factory=SCRIPTS.factory, clock=lambda: clock[0])


def scripted_turn():
    answer = json.dumps({"answer": "Here is your workspace summary.", "speakable": "Here is your workspace summary.", "language": "en", "follow_ups": []})
    # One tool per model step, so the stored tool order is the same in both runs (parallel calls may finish in any order).
    SCRIPTS.set(rafii_manager=[[function_call("task_plan", {"title": f"Plan {PRIVATE}", "steps": [{"label": f"Look {PRIVATE}"}]}, call_id="p1")],
                               [function_call("workspace_summary", {}, call_id="w1")],
                               [assistant_message(answer)]])
    return runtime.turn(wid, OWNER, {"message": f"Summarise my workspace {PRIVATE}", "idempotencyKey": uuid.uuid4().hex, "timeZone": "Asia/Hong_Kong",
                                     "model": "deterministic-preview"})


def stored(out):
    with connection() as db:
        run = db.execute("SELECT status,artifact,usage FROM public.pr_agent_runs WHERE id::text=%s", (out["runId"],)).fetchone()
        messages = [row[0] for row in db.execute("SELECT body FROM public.pr_messages WHERE run_id::text=%s ORDER BY seq", (out["runId"],)).fetchall()]
        events = [row[0] for row in db.execute("SELECT body FROM public.pr_agent_events WHERE run_id::text=%s ORDER BY seq", (out["runId"],)).fetchall()]
    return {"returned": out, "status": run[0], "artifact": run[1], "usage": run[2], "messages": messages, "events": events}


_ID = re.compile(r"trace_[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\b[0-9a-f]{32}\b")
VOLATILE = {"latencyMs", "elapsedMs", "sdkSpans", "durationMs", "startedAt", "endedAt", "ms"}


def masked(value):
    if isinstance(value, dict):
        return {k: ("<t>" if k in VOLATILE else masked(v)) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [masked(v) for v in value]
    if isinstance(value, str):
        return _ID.sub("<id>", value)
    return value


capture = Capture()
obs.log.addHandler(capture)
REQUEST = uuid.uuid4().hex
token = obs.bind_request(REQUEST)
os.environ["POSTRIFF_AGENT_OBSERVABILITY"] = "1"
ON = stored(scripted_turn())
LINES = list(capture.lines)
obs.release_request(token)
os.environ["POSTRIFF_AGENT_OBSERVABILITY"] = "0"
capture.lines.clear()
OFF = stored(scripted_turn())
OFF_LINES = list(capture.lines)
os.environ["POSTRIFF_AGENT_OBSERVABILITY"] = "1"
obs.log.removeHandler(capture)
EVENTS = [json.loads(line) for line in LINES]


@check("OB01", "one turn is correlated from request to response")
def _():
    names = [e["event"] for e in EVENTS]
    assert names[0] == "agent.request" and names[-1] == "agent.response", names
    assert "agent.plan" in names and "agent.tool" in names and "agent.verify" in names, names
    assert names.index("agent.plan") < names.index("agent.verify") < names.index("agent.response"), names
    assert all(e.get("requestId") == REQUEST for e in EVENTS), "every line carries the request id"
    trace, run = ON["returned"]["traceId"], ON["returned"]["runId"]
    assert trace == ON["artifact"]["trace"]["traceId"], "the returned trace id is the stored one"
    assert all(e.get("traceId") == trace for e in EVENTS[1:]), [(e["event"], e.get("traceId")) for e in EVENTS]
    assert all(e.get("runId") == run for e in EVENTS if e["event"] in ("agent.tool", "agent.verify", "agent.response")), EVENTS
    assert [e["seq"] for e in EVENTS] == list(range(1, len(EVENTS) + 1)), [e["seq"] for e in EVENTS]
    response = EVENTS[-1]
    assert (response["path"], response["status"], response["composedBy"]) == ("manager", "completed", "manager"), response
    tools = [e for e in EVENTS if e["event"] in ("agent.plan", "agent.tool")]
    assert {e["tool"] for e in tools} == {"task_plan", "workspace_summary"} and all(e["status"] == "verified" for e in tools), tools


@check("OB02", "no message, plan, answer, title, token or workspace id in any line")
def _():
    text = "\n".join(LINES)
    for secret in (PRIVATE, PRIVATE.lower(), "Summarise my workspace", "Here is your workspace", OWNER, wid, ONE):
        assert secret not in text, secret
    allowed = set(obs.FIELDS) | {"event", "phase", "requestId", "seq", "dropped"}
    for event in EVENTS:
        assert set(event) <= allowed, event


@check("OB03", "returned and stored turn identical with observability on and off")
def _():
    assert OFF_LINES == [], "the kill switch writes no line"
    for key in ("returned", "status", "artifact", "usage", "messages", "events"):
        assert masked(ON[key]) == masked(OFF[key]), key
    assert "observability" not in json.dumps(ON["artifact"]), "nothing new is persisted on the run"


print(json.dumps({"script": "postgres_agent_observability", "failures": FAILURES, "lines": len(LINES)}), flush=True)
sys.exit(1 if FAILURES else 0)
