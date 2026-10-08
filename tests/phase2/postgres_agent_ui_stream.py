"""Lane B on a disposable PostgreSQL 17 (G13 G09 G07): the SQL ui_stream and ui_metering issue themselves, against migration 102
and the real hosted Ledger, with real caller identity (repository.transaction: verified session + active membership + workspace
row lock). No service-role bypass is used for any assertion about who can see what; nothing calls a provider.

Scenarios (each prints PASS:<id>):
  S1 parent-run read, actor, freshness and cross-tenant invisibility
  S2 artifact head: consumer scope only (a founder-scoped or foreign artifact is the same 404)
  S3 combined admission plan on the real Ledger: room = parent ceiling - settled parent spend - earlier UI holds/spend
  S4 reserve_attempt: key agent:{parent}:ui:{attempt}, run_id = parent, meta, attempt.reservation_id; refusal reserves nothing
  S5 settle_attempt: known usage -> one actual settlement + usage columns; repeat is idempotent; unknown keeps the hold
  S6 not dispatched / refused before work -> released at 0
  S7 one live producer per (artifact, target revision): the partial unique index refuses a second live attempt
  S8 orphaned hold of a terminal attempt -> booked unknown once
  S9 current attempt / attempt state / revision source reads
Run: python scripts/postriff_pg_suite.py postgres_agent_ui_stream (cloud CI: scripts/agent_ui_validation.sh database)
"""
import json
from contextlib import contextmanager
import os
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.agent_runtime_v2 import config, ui_contracts as contracts, ui_http, ui_metering, ui_stream  # noqa: E402
from consumer_fixtures import approve_budgets  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN") or f"host=127.0.0.1 port={os.environ.get('POSTRIFF_PG_PORT', '55438')} dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000004"
TOKENS = {"one-token-000000000000000000": ONE, "two-token-000000000000000000": TWO}
OWNER, OTHER = list(TOKENS)
clock = [time.time()]
os.environ["POSTRIFF_AI_PAUSED"] = ""


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required.", 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: f"session-{principal}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def expect_error(call, status=None, code=None):
    try:
        call()
    except AlphaError as error:
        assert status is None or error.status == status, (error.status, str(error))
        assert code is None or error.code == code, (error.code, str(error))
        return error
    raise AssertionError("the call was accepted")


def one(sql, *params):
    with connection() as db:
        return db.execute(sql, params).fetchone()


def rows(sql, *params):
    with connection() as db:
        return db.execute(sql, params).fetchall()


# --- setup -----------------------------------------------------------------------------------------------------------------------
with connection() as db:
    db.execute((ROOT / "migrations/postriff/058_founder_ai_usage.sql").read_text())
    db.execute((ROOT / "migrations/postriff/102_agent_ui_artifacts.sql").read_text())
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (TWO,))

service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
wid = service.bootstrap(OWNER, "studio")["workspaceId"]
other = service.bootstrap(OTHER, "studio")["workspaceId"]
approve_budgets(connection, wid)
cfg = config.RuntimeConfig.from_environment(values={"OPENAI_API_KEY": "sk-test-not-a-real-key", "RAFII_AGENT_V2_ENABLED": "1", "RAFII_GENUI_ENABLED": "1"})
runtime = SimpleNamespace(service=service, cfg=cfg, _reservation_approval=lambda *args: (None, {}))
route = cfg.route("fast_language", reason="pg test")


def parent_run(*, spent=30_000, ceiling=88_000, actor=ONE, workspace=None, status="completed"):
    workspace = workspace or wid
    with connection() as db:
        conversation = str(db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'ui') RETURNING id", (workspace, actor)).fetchone()[0])
        result = {"composedBy": "manager", "usage": {"billing": "metered"}, "ui": {"eligible": True, "journeyIds": ["J01"]}, "answerText": "ok"}
        run = str(db.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) "
                             "VALUES(%s,%s,%s,%s,'rafii-agent','standard',%s,%s,%s,%s::jsonb) RETURNING id",
                             (conversation, workspace, actor, status, "a" * 64, "b" * 64, "agent:" + uuid.uuid4().hex, json.dumps({"version": 1, "result": result}))).fetchone()[0])
    if ceiling is not None:
        with service.repository.transaction(OWNER if workspace == wid else OTHER, workspace) as (cur, _row, principal):
            reservation = service.ledger.reserve(cur, workspace, principal, "text_model", ceiling, f"agent:{run}", charge_batch=False, provider="openai",
                                                 model="gpt-6-sol", run_id=run, meta={"via": "rafii_agent"})
            if spent is not None:
                service.ledger.settle(cur, workspace, reservation["reservationId"], "completed", spent)
    return run, conversation


def artifact(run, conversation, *, scope="workspace", scope_key="", revision=0, workspace=None):
    workspace = workspace or wid
    with connection() as db:
        return str(db.execute("INSERT INTO public.pr_ui_artifacts(workspace_id,scope,scope_key,conversation_id,parent_run_id,slot,actor,surface,revision,manifest) "
                              "VALUES(%s,%s,%s,%s,%s,'main',%s,'chat',%s,%s::jsonb) RETURNING id",
                              (workspace, scope, scope_key, conversation, run, ONE, revision, json.dumps({"manifestId": "m-1"}))).fetchone()[0])


def attempt(artifact_id, *, kind="generate", state="queued", target=1, owner="b:test", workspace=None):
    workspace = workspace or wid
    with connection() as db:
        attempt_id = str(db.execute("INSERT INTO public.pr_ui_attempts(artifact_id,workspace_id,kind,target_revision,state,idempotency_key,lease_owner,lease_expires_at) "
                                    "VALUES(%s,%s,%s,%s,%s,%s,%s,now()+interval '90 seconds') RETURNING id",
                                    (artifact_id, workspace, kind, target, state, "pg-key-" + uuid.uuid4().hex, owner)).fetchone()[0])
        db.execute("UPDATE public.pr_ui_artifacts SET current_attempt_id=%s WHERE id=%s", (attempt_id, artifact_id))
    return attempt_id


def plan(ceiling, chain=ui_metering.PRESENTATION_CHAIN):
    return SimpleNamespace(route=route, ceiling_usd_micro=ceiling, chain=chain, prompt_hash="a" * 64)


@contextmanager
def tx(token=OWNER, workspace=None):
    with ui_http.ui_transaction(runtime, token, workspace or wid, "edit") as (cur, auth):
        yield cur, auth


checks = []

# S1 -------------------------------------------------------------------------------------------------------------------------------
run, conversation = parent_run()
with tx() as (cur, auth):
    parent = ui_stream._parent_run(cur, wid, run)
    assert parent["actor"] == ONE and parent["status"] == "completed" and parent["result"]["ui"]["eligible"] is True, parent
    assert 0 <= parent["ageSeconds"] < 120, parent["ageSeconds"]
    assert parent["runKey"].startswith("agent:")
    assert ui_stream._parent_run(cur, other, run) is None, "a run is invisible from another workspace"
    assert ui_stream._attempt_key_exists(cur, wid, "missing-key-000000000") is False
expect_error(lambda: tx(OTHER, wid).__enter__(), status=403)          # not a member of this workspace: refused before any read
checks.append("S1")

# S2 -------------------------------------------------------------------------------------------------------------------------------
art = artifact(run, conversation)
founder_art = artifact(parent_run()[0], conversation, scope="founder", scope_key="founder:operator:production")
with tx() as (cur, auth):
    head = ui_stream._artifact_head(cur, wid, art)
    assert head["runId"] == run and head["actor"] == ONE and head["revision"] == 0 and head["manifest"] == {"manifestId": "m-1"}, head
    expect_error(lambda: ui_stream._artifact_head(cur, wid, founder_art), status=404, code="ui_artifact")
    expect_error(lambda: ui_stream._artifact_head(cur, other, art), status=404, code="ui_artifact")
checks.append("S2")

# S3 + S4 ----------------------------------------------------------------------------------------------------------------------------
first = attempt(art)
with tx() as (cur, auth):
    allowance = ui_metering.allowance(cur, wid, run)
    assert allowance["room"] == 88_000 - 30_000 and allowance["ceiling"] == 88_000 and allowance["parentSpent"] == 30_000, allowance
    reservation = ui_metering.reserve_attempt(runtime, cur, auth, {"artifactId": art, "runId": run}, {"attemptId": first, "kind": "generate"}, plan(9_000))
row = one("SELECT idempotency_key, run_id::text, estimated_usd_micro, meta->>'via', meta->>'chain', model FROM public.pr_usage_ledger WHERE id::text=%s",
          reservation["reservationId"])
assert row == (f"agent:{run}:ui:{first}", run, 9_000, "rafii_agent_ui", "presentation", route.model), row
assert one("SELECT reservation_id, provider_attempts FROM public.pr_ui_attempts WHERE id::text=%s", first) == (reservation["reservationId"], 1)
with tx() as (cur, auth):
    assert ui_metering.allowance(cur, wid, run)["room"] == 88_000 - 30_000 - 9_000, "an open hold counts in full"
before = one("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s", wid)[0]
second = attempt(art, state="failed")
with tx() as (cur, auth):
    expect_error(lambda: ui_metering.reserve_attempt(runtime, cur, auth, {"artifactId": art, "runId": run}, {"attemptId": second, "kind": "generate"}, plan(60_000)),
                 status=402, code="ui_budget")
assert one("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s", wid)[0] == before, "a refusal reserves nothing"
unknown_parent, unknown_conversation = parent_run(spent=None)
with tx() as (cur, auth):
    assert ui_metering.allowance(cur, wid, unknown_parent)["room"] is None, "an unsettled parent has no known room"
checks.append("S3")
checks.append("S4")

# S5 -------------------------------------------------------------------------------------------------------------------------------
usage = {"status": "ok", "known": True, "dispatched": True, "inputTokens": 1200, "outputTokens": 300, "model": route.model, "provider": "openai",
         "requestId": "resp_pg", "latencyMs": 1500}
cost = cfg.estimate_usd_micro(route.model, 1200, 300)
for _ in range(2):
    with tx() as (cur, auth):
        settled = ui_metering.settle_attempt(runtime, cur, auth, {"attemptId": first}, usage)
assert settled["costUsdMicro"] == cost and settled["costState"] == "known", settled
terminal = rows("SELECT cost_state, actual_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND kind IN ('settle','release')",
                wid, reservation["reservationId"])
assert terminal == [("actual", cost)], terminal
assert one("SELECT cost_usd_micro, cost_state, usage->>'requestId' FROM public.pr_ui_attempts WHERE id::text=%s", first) == (cost, "known", "resp_pg")
calls = rows("SELECT workload, feature, status, cost_usd_micro, physical_attempt_id, run_id::text FROM public.pr_ai_call_events WHERE reservation_id::text=%s",
             reservation["reservationId"])
assert calls == [("ui_presenter", "agent", "ok", cost, f"{first}:p1", run)], calls
with tx() as (cur, auth):
    assert ui_metering.allowance(cur, wid, run)["room"] == 88_000 - 30_000 - cost, "a settled attempt counts at its actual"
with connection() as db:
    db.execute("UPDATE public.pr_ui_attempts SET state='failed', finished_at=now() WHERE id::text=%s", (first,))   # F's terminal transition
third = attempt(art)
with tx() as (cur, auth):
    held = ui_metering.reserve_attempt(runtime, cur, auth, {"artifactId": art, "runId": run}, {"attemptId": third, "kind": "repair"}, plan(9_000))
    ui_metering.settle_attempt(runtime, cur, auth, {"attemptId": third}, {"status": "cancelled", "known": False, "dispatched": True, "model": route.model})
states = rows("SELECT cost_state FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND kind IN ('settle','release')", wid, held["reservationId"])
assert states == [("estimated_unknown",)], states
with tx() as (cur, auth):
    assert ui_metering.allowance(cur, wid, run)["room"] == 88_000 - 30_000 - cost - 9_000, "an unknown attempt keeps its full hold"
checks.append("S5")

# S6 -------------------------------------------------------------------------------------------------------------------------------
fourth_run, fourth_conversation = parent_run()
fourth_art = artifact(fourth_run, fourth_conversation)
for case in ({"status": "failed", "known": True, "dispatched": False, "costUsdMicro": 0}, {"status": "refused", "known": True, "dispatched": True, "httpStatus": 400}):
    attempt_id = attempt(fourth_art, state="failed")
    with tx() as (cur, auth):
        reservation_four = ui_metering.reserve_attempt(runtime, cur, auth, {"artifactId": fourth_art, "runId": fourth_run}, {"attemptId": attempt_id, "kind": "generate"},
                                                       plan(5_000))
        ui_metering.settle_attempt(runtime, cur, auth, {"attemptId": attempt_id}, {**case, "model": route.model})
    released = rows("SELECT cost_state, actual_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND kind IN ('settle','release')",
                    wid, reservation_four["reservationId"])
    assert released == [("released", 0)], (case, released)
checks.append("S6")

# S7 -------------------------------------------------------------------------------------------------------------------------------
seventh_run, seventh_conversation = parent_run()
seventh = artifact(seventh_run, seventh_conversation)
attempt(seventh, state="streaming")
try:
    attempt(seventh, state="queued")
except psycopg.errors.UniqueViolation:
    pass
else:
    raise AssertionError("a second live producer for the same artifact revision was accepted")
attempt(seventh, state="failed")             # a finished attempt does not block (only live states are unique)
checks.append("S7")

# S8 -------------------------------------------------------------------------------------------------------------------------------
orphan = attempt(fourth_art, state="queued")
with tx() as (cur, auth):
    orphan_hold = ui_metering.reserve_attempt(runtime, cur, auth, {"artifactId": fourth_art, "runId": fourth_run}, {"attemptId": orphan, "kind": "generate"}, plan(5_000))
with connection() as db:
    db.execute("UPDATE public.pr_ui_attempts SET state='canceled', finished_at=now()-interval '1 hour' WHERE id::text=%s", (orphan,))
with tx() as (cur, auth):
    assert ui_metering.settle_orphans(runtime, cur, wid) == 1
with tx() as (cur, auth):
    assert ui_metering.settle_orphans(runtime, cur, wid) == 0
booked = rows("SELECT cost_state FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND kind IN ('settle','release')", wid, orphan_hold["reservationId"])
assert booked == [("estimated_unknown",)], booked
assert one("SELECT cost_state FROM public.pr_ui_attempts WHERE id::text=%s", orphan) == ("unknown",)
checks.append("S8")

# S9 -------------------------------------------------------------------------------------------------------------------------------
ninth_run, ninth_conversation = parent_run()
ninth = artifact(ninth_run, ninth_conversation)
live_attempt = attempt(ninth, state="streaming")
with connection() as db:
    db.execute("INSERT INTO public.pr_ui_revisions(artifact_id,workspace_id,revision,kind,source,source_hash) VALUES(%s,%s,1,'generate',%s,%s)",
               (ninth, wid, "root = RafiiRoot([])", contracts.sha256_text("root = RafiiRoot([])")))
with tx() as (cur, auth):
    current = ui_stream._current_attempt(cur, wid, ninth)
    assert current["attemptId"] == live_attempt and current["state"] == "streaming" and current["leaseExpired"] is False, current
    assert ui_stream._attempt_state(cur, wid, live_attempt) == "streaming"
    assert ui_stream._attempt_state(cur, other, live_attempt) is None, "another workspace can't read the attempt"
    assert ui_stream._revision_source(cur, wid, ninth, 1) == "root = RafiiRoot([])"
    assert ui_stream._revision_source(cur, other, ninth, 1) is None
    ui_stream._lock_workspace(cur, wid)
with connection() as db:
    db.execute("UPDATE public.pr_ui_attempts SET lease_expires_at=now()-interval '1 second' WHERE id::text=%s", (live_attempt,))
with tx() as (cur, auth):
    assert ui_stream._current_attempt(cur, wid, ninth)["leaseExpired"] is True
checks.append("S9")

# --- end to end on the real store (lane F), projection and manifest (lane D), Ledger and caller identity -------------------------
# Only the provider (a scripted stream) and the Node validator seam (accepts programs rooted at RafiiRoot) are stand-ins.
from unittest import mock  # noqa: E402
from postriff_phase2.agent_runtime_v2 import ui_store, ui_validator  # noqa: E402
from test_agent_ui_stream_fakes import FakeValidator, ScriptTransport, Started, parse, usage_final, GOOD_PROGRAM, program_in_pieces  # noqa: E402

with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active') ON CONFLICT DO NOTHING", (wid, TWO))
transport = ScriptTransport()
e2e = SimpleNamespace(service=service, cfg=cfg, _reservation_approval=lambda *args: (None, {}), ui_transport=transport, ui_assets_dir=None)
validator = FakeValidator()
for patch in (mock.patch.object(ui_validator, "validate_and_merge_ui", validator), mock.patch.object(ui_stream, "CANCEL_POLL_SECONDS", 0.05),
              mock.patch.object(ui_stream, "FLUSH_SECONDS", 0.0), mock.patch.object(ui_stream, "REPLAY_TAIL_SECONDS", 0.3),
              mock.patch.object(ui_stream, "REPLAY_POLL_SECONDS", 0.05)):
    patch.start()


def eligible_run():
    with connection() as db:
        conversation = str(db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'ui e2e') RETURNING id", (wid, ONE)).fetchone()[0])
        result = {"composedBy": "manager", "usage": {"billing": "metered", "route": "gpt-6-sol"}, "ui": {"eligible": True, "journeyIds": ["J01"], "slot": "main"},
                  "answerText": "Here are your drafts.", "routes": [{"agent": "rafii_manager", "provider": "openai", "model": "gpt-6-sol"}],
                  "references": [], "toolActivity": [{"tool": "draft_get", "status": "ok", "effect": "READ"}], "language": "en"}
        run_id = str(db.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) "
                                "VALUES(%s,%s,%s,'completed','rafii-agent','standard',%s,%s,%s,%s::jsonb) RETURNING id",
                                (conversation, wid, ONE, "a" * 64, "b" * 64, "agent:" + uuid.uuid4().hex, json.dumps({"version": 1, "result": result}))).fetchone()[0])
        db.execute("INSERT INTO public.pr_messages(conversation_id,workspace_id,seq,role,body,run_id) VALUES(%s,%s,1,'assistant',%s::jsonb,%s)",
                   (conversation, wid, json.dumps({"text": "Here are your drafts.", "agent": {}}), run_id))
    with service.repository.transaction(OWNER, wid) as (cur, _row, principal):
        held = service.ledger.reserve(cur, wid, principal, "text_model", 88_000, f"agent:{run_id}", charge_batch=False, provider="openai", model="gpt-6-sol",
                                      run_id=run_id, meta={"via": "rafii_agent"})
        service.ledger.settle(cur, wid, held["reservationId"], "completed", 30_000)
    return run_id


def post(run_id, key, token=OWNER):
    request = contracts.validate_presentation_request({"parentRunId": run_id, "idempotencyKey": key})
    return ui_stream.create_presentation(e2e, {"postriff.request_id": "e" * 32}, Started(), wid, token, request)


def drain(iterable):
    try:
        return parse(b"".join(iterable))
    finally:
        iterable.close()


# S10 streamed generation → validated, CAS-committed, settled, then ready; recorded on the message ------------------------------
transport.scripts.append(program_in_pieces() + [("final", usage_final(1500, 320))])
run10 = eligible_run()
events = drain(post(run10, "e2e-key-0000000000001"))
kinds = [e["kind"] for e in events]
assert kinds[0] == "ui.started" and kinds[-1] == "ui.ready" and kinds.count("ui.delta") >= 2, kinds
artifact10 = events[0]["artifactId"]
assert "".join(e["payload"]["append"] for e in events if e["kind"] == "ui.delta") == GOOD_PROGRAM
state = one("SELECT revision, generation_state, validation_state, source_hash FROM public.pr_ui_artifacts WHERE id::text=%s", artifact10)
assert state == (1, "ready", "accepted", contracts.sha256_text(GOOD_PROGRAM.strip())), state
assert one("SELECT source FROM public.pr_ui_revisions WHERE artifact_id::text=%s AND revision=1", artifact10) == (GOOD_PROGRAM.strip(),)
attempt10 = one("SELECT id::text, state, cost_state, cost_usd_micro, reservation_id, provider_attempts FROM public.pr_ui_attempts WHERE artifact_id::text=%s", artifact10)
cost10 = cfg.estimate_usd_micro(route.model, 1500, 320)
assert attempt10[1:4] == ("ready", "known", cost10) and attempt10[5] == 1, attempt10
assert rows("SELECT cost_state, actual_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND kind IN ('settle','release')",
            wid, attempt10[4]) == [("actual", cost10)]
assert one("SELECT idempotency_key FROM public.pr_usage_ledger WHERE id::text=%s", attempt10[4]) == (f"agent:{run10}:ui:{attempt10[0]}",)
stored = [r[0] for r in rows("SELECT kind FROM public.pr_ui_events WHERE artifact_id::text=%s ORDER BY seq", artifact10)]
assert stored[0] == "ui.started" and stored[-1] == "ui.ready" and "ui.heartbeat" not in stored, stored
message = one("SELECT body->'agent'->'uiArtifacts' FROM public.pr_messages WHERE run_id::text=%s AND role='assistant'", run10)[0]
assert any(item.get("artifactId") == artifact10 for item in message), message
assert validator.calls[-1]["policy"]["rootName"] == "RafiiRoot" and "drafts_list" in validator.calls[-1]["policy"]["readBindings"], validator.calls[-1]["policy"]
assert len(transport.calls) == 1
checks.append("S10")

# S11 duplicate key and a second tab attach; replay never dispatches; a viewer can replay but not start --------------------------
again = drain(post(run10, "e2e-key-0000000000001"))
assert again[-1]["kind"] == "ui.ready" and again[-1]["artifactId"] == artifact10, [e["kind"] for e in again]
other_tab = drain(post(run10, "e2e-key-0000000000002"))
assert other_tab[-1]["kind"] == "ui.ready", [e["kind"] for e in other_tab]
replayed = parse(b"".join(ui_stream.replay(e2e, {}, Started(), wid, OWNER, artifact10, 0)))
assert replayed[-1]["kind"] == "ui.ready"
viewer_replay = parse(b"".join(ui_stream.replay(e2e, {}, Started(), wid, OTHER, artifact10, 0)))
assert viewer_replay[-1]["kind"] == "ui.ready", "a workspace member can reopen a view"
expect_error(lambda: post(run10, "e2e-key-0000000000003", token=OTHER), status=403)
expect_error(lambda: ui_stream.replay(e2e, {}, Started(), other, OTHER, artifact10, 0), status=404)
assert len(transport.calls) == 1, "duplicate, second tab, reopen and replay made no provider call"
assert one("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key LIKE %s AND kind='reserve'", wid, f"agent:{run10}:ui:%")[0] == 1
checks.append("S11")

# S12 cancel mid-stream: one ui.canceled, the producer settles once (unknown keeps the hold), the turn's answer is untouched ------
transport.scripts.append([("delta", "root = RafiiRoot([a])\n"), ("hang",)])
run12 = eligible_run()
answer_before = one("SELECT artifact FROM public.pr_agent_runs WHERE id::text=%s", run12)[0]
stream12 = post(run12, "e2e-key-0000000000012")
first12 = parse(next(stream12) + next(stream12))
artifact12 = first12[0]["artifactId"]
assert ui_stream.cancel_http(e2e, wid, OWNER, artifact12)["canceled"] is True
rest12 = drain(stream12)
assert [e["kind"] for e in rest12] == ["ui.canceled"], [e["kind"] for e in rest12]
attempt12 = one("SELECT state, reason, cost_state, reservation_id FROM public.pr_ui_attempts WHERE artifact_id::text=%s", artifact12)
assert attempt12[:3] == ("canceled", "canceled_by_user", "unknown"), attempt12
assert rows("SELECT cost_state FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND kind IN ('settle','release')", wid, attempt12[3]) \
    == [("estimated_unknown",)]
assert one("SELECT count(*) FROM public.pr_ui_events WHERE artifact_id::text=%s AND kind='ui.canceled'", artifact12)[0] == 1
assert one("SELECT artifact FROM public.pr_agent_runs WHERE id::text=%s", run12)[0] == answer_before
checks.append("S12")

# S13 the client disconnects mid-stream: interrupted, settled once ----------------------------------------------------------------
transport.scripts.append([("delta", "root = RafiiRoot([a])\n"), ("hang",)])
run13 = eligible_run()
stream13 = post(run13, "e2e-key-0000000000013")
artifact13 = parse(next(stream13) + next(stream13))[0]["artifactId"]
stream13.close()
attempt13 = one("SELECT state, reason, cost_state, reservation_id FROM public.pr_ui_attempts WHERE artifact_id::text=%s", artifact13)
assert attempt13[:3] == ("interrupted", "client_gone", "unknown"), attempt13
assert rows("SELECT cost_state FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id::text=%s AND kind IN ('settle','release')", wid, attempt13[3]) \
    == [("estimated_unknown",)]
checks.append("S13")

# S14 explicit edit: stale base 409 before spend; current base → revision 2, separately metered, revision 1 kept -------------------
reservations_before = one("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", wid)[0]
stale = contracts.validate_patch({"baseRevision": 1, "baseSourceHash": "0" * 64, "instruction": "Add a chart", "idempotencyKey": "e2e-edit-000000000001"})
expect_error(lambda: ui_stream.create_edit(e2e, {}, Started(), wid, OWNER, artifact10, stale), status=409)
assert one("SELECT count(*) FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", wid)[0] == reservations_before
transport.scripts.append([("delta", 'chart = ToolBoundChart("drafts_list", {})\n'), ("final", usage_final(900, 60))])
current = contracts.validate_patch({"baseRevision": 1, "baseSourceHash": state[3], "instruction": "Add a chart", "idempotencyKey": "e2e-edit-000000000002"})
edited = drain(ui_stream.create_edit(e2e, {}, Started(), wid, OWNER, artifact10, current))
assert edited[-1]["kind"] == "ui.ready" and edited[-1]["payload"]["revision"] == 2, [e["kind"] for e in edited]
assert one("SELECT revision FROM public.pr_ui_artifacts WHERE id::text=%s", artifact10) == (2,)
assert one("SELECT count(*) FROM public.pr_ui_revisions WHERE artifact_id::text=%s", artifact10) == (2,)
assert one("SELECT meta->>'chain' FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='reserve' ORDER BY at DESC LIMIT 1", wid)[0].startswith("edit:")
assert validator.calls[-1]["mode"] == "patch" and validator.calls[-1]["base"] == GOOD_PROGRAM.strip()
checks.append("S14")

for check in checks:
    print(f"PASS:{check}", flush=True)
print(json.dumps({"script": "postgres_agent_ui_stream", "passed": checks}), flush=True)
