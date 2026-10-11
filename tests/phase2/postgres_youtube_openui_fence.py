"""Cloud-only disposable PG: actual tenant-pinned OpenUI parent admission.

Synthetic stored parents/artifacts, real session/membership transactions and
real SQL; rejected paths must never claim/store/reserve/read UI content or call
a provider. Historical artifacts are deliberately preserved, not bulk erased.
"""
import copy
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

if not sys.platform.startswith("linux") or os.environ.get("CI", "").lower() not in ("1", "true"):
    raise SystemExit("Cloud CI and the disposable PostgreSQL harness are required.")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.agent_runtime_v2 import config, ui_contracts as contracts, ui_http, ui_metering, ui_presenter, ui_projection, ui_store, ui_stream
from postriff_phase2.youtube import agent_context

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
USERS = {token: str(uuid4()) for token in ("holder", "outsider")}
CHECKS = []


def connection():
    db = psycopg.connect(DSN, client_encoding="utf8", connect_timeout=5,
                        options="-c statement_timeout=10000 -c lock_timeout=5000")
    assert db.info.host == "127.0.0.1" and db.info.port == 55438 and db.info.dbname == "postgres"
    return db


def verify(token):
    if token not in USERS:
        raise AlphaError("Verified session required.", 401)
    return USERS[token]


verify.auth_time = lambda token, actor: time.time()
verify.session_id = lambda token, actor: "synthetic-openui-" + token

with connection() as db:
    assert db.execute("SELECT host(inet_server_addr()),inet_server_port(),current_database()").fetchone() == ("127.0.0.1", 55438, "postgres")
    assert db.execute("SELECT array_agg(column_name::text ORDER BY ordinal_position) FROM information_schema.columns "
                      "WHERE table_schema='auth' AND table_name='users'").fetchone()[0] == ["id"]
    db.execute((ROOT / "migrations/postriff/102_agent_ui_artifacts.sql").read_text())
    for actor in USERS.values():
        db.execute("INSERT INTO auth.users(id) VALUES(%s)", (actor,))

service = HostedWorkspaceService(connection, verify)
WORKSPACE = service.bootstrap("holder", "studio")["workspaceId"]
FOREIGN = service.bootstrap("outsider", "studio")["workspaceId"]
runtime = SimpleNamespace(service=service, cfg=config.RuntimeConfig.from_environment(values={"RAFII_GENUI_ENABLED": "1"}))
BASE = {"composedBy": "manager", "usage": {"billing": "metered"}, "ui": {"eligible": True, "journeyIds": ["J01"]},
        "answerText": "synthetic native answer", "toolActivity": [{"tool": "draft_get", "status": "verified"}],
        "references": [{"type": "draft", "id": "synthetic-draft"}]}
SOURCE = 'root = RafiiRoot([title])\ntitle = Text("synthetic prior view")'
SOURCE_HASH = contracts.sha256_text(SOURCE)
EXISTING_KEY = "synthetic-openui-existing-attempt"


def parent(workspace=WORKSPACE, token="holder"):
    with connection() as db:
        conversation = str(db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'synthetic UI') RETURNING id",
                                      (workspace, USERS[token])).fetchone()[0])
        run = str(db.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) "
                             "VALUES(%s,%s,%s,'completed','synthetic-model','standard',%s,%s,%s,%s::jsonb) RETURNING id",
                             (conversation, workspace, USERS[token], "a" * 64, "b" * 64, "agent:synthetic-" + uuid4().hex,
                              json.dumps({"version": 1, "result": BASE}))).fetchone()[0])
    return run, conversation


RUN, CONVERSATION = parent()
FOREIGN_RUN, _ = parent(FOREIGN, "outsider")
with connection() as db:
    ARTIFACT = str(db.execute("INSERT INTO public.pr_ui_artifacts(workspace_id,conversation_id,parent_run_id,actor,surface,journey_ids,revision,source_hash,"
                              "generation_state,validation_state,manifest,next_seq) VALUES(%s,%s,%s,%s,'chat',ARRAY['J01'],1,%s,'ready','accepted',%s::jsonb,2) RETURNING id",
                              (WORKSPACE, CONVERSATION, RUN, USERS["holder"], SOURCE_HASH, json.dumps({"manifestId": "synthetic-manifest"}))).fetchone()[0])
    ATTEMPT = str(db.execute("INSERT INTO public.pr_ui_attempts(artifact_id,workspace_id,kind,target_revision,state,idempotency_key,lease_owner,lease_expires_at) "
                             "VALUES(%s,%s,'generate',1,'ready',%s,'synthetic-owner',now()+interval '90 seconds') RETURNING id",
                             (ARTIFACT, WORKSPACE, EXISTING_KEY)).fetchone()[0])
    db.execute("UPDATE public.pr_ui_artifacts SET current_attempt_id=%s WHERE id=%s", (ATTEMPT, ARTIFACT))
    db.execute("INSERT INTO public.pr_ui_revisions(artifact_id,workspace_id,revision,kind,attempt_id,source,source_hash) VALUES(%s,%s,1,'generate',%s,%s,%s)",
               (ARTIFACT, WORKSPACE, ATTEMPT, SOURCE, SOURCE_HASH))
    db.execute("INSERT INTO public.pr_ui_events(artifact_id,workspace_id,seq,attempt_id,revision,kind,payload) VALUES(%s,%s,1,%s,1,'ui.ready',%s::jsonb)",
               (ARTIFACT, WORKSPACE, ATTEMPT, json.dumps({"canonicalSource": SOURCE})))


def write_result(result):
    with connection() as db:
        db.execute("UPDATE public.pr_agent_runs SET artifact=jsonb_set(artifact,'{result}',%s::jsonb) WHERE workspace_id=%s AND id=%s",
                   (json.dumps(result), WORKSPACE, RUN))


def state():
    with connection() as db:
        tables = ("pr_ui_artifacts", "pr_ui_attempts", "pr_ui_revisions", "pr_ui_events", "pr_usage_ledger")
        counts = [db.execute("SELECT count(*) FROM public." + table + " WHERE workspace_id=%s", (WORKSPACE,)).fetchone()[0] for table in tables]
        source = db.execute("SELECT source,source_hash FROM public.pr_ui_revisions WHERE workspace_id=%s AND artifact_id=%s", (WORKSPACE, ARTIFACT)).fetchall()
        checkpoints = db.execute("SELECT checkpoint_source FROM public.pr_ui_attempts WHERE workspace_id=%s", (WORKSPACE,)).fetchall()
        return counts, source, checkpoints


def rejected(call, status=409, code="ui_not_eligible"):
    before = state()
    try:
        call()
    except AlphaError as error:
        assert error.status == status and (code is None or error.code == code), (error.status, error.code, str(error))
    else:
        raise AssertionError("The request was admitted")
    assert state() == before, "rejected path changed UI content, attempts or budget ledger"


def create(*, key="synthetic-openui-new-attempt", run=RUN, **extra):
    request = contracts.validate_presentation_request({"parentRunId": run, "idempotencyKey": key, **extra})
    return ui_stream._start_presentation(runtime, ui_stream._consumer_tx(runtime, "holder", WORKSPACE), WORKSPACE, request,
                                        started=time.monotonic(), request_id=None)


def edit(*, key="synthetic-openui-edit-attempt"):
    request = contracts.validate_patch({"baseRevision": 1, "baseSourceHash": SOURCE_HASH, "instruction": "Show a table", "idempotencyKey": key})
    return ui_stream._start_edit(runtime, ui_stream._consumer_tx(runtime, "holder", WORKSPACE), WORKSPACE, ARTIFACT, request,
                                started=time.monotonic(), request_id=None)


markers = {
    "tagged": {agent_context.KEY: [agent_context.source(WORKSPACE, "youtube:synthetic", "UC" + "e" * 22, "synthetic-generation", time.time())]},
    "legacy": {"facts": [{"kind": "youtube_native_analytics", "evidence": {"connectionId": "youtube:synthetic", "channelId": "UC" + "e" * 22}}]},
    "removed": {agent_context.REMOVED: True},
    "malformed": {agent_context.KEY: None},
}
with patch.object(ui_stream, "_sweep") as sweep, patch.object(ui_store, "create_or_resume_artifact") as claim, \
        patch.object(ui_metering, "reserve_attempt") as reserve, patch.object(ui_metering, "settle_attempt") as settle, \
        patch.object(ui_presenter, "build_plan") as plan, patch.object(ui_store, "events_after") as events:
    for label, marker in markers.items():
        write_result({**copy.deepcopy(BASE), **marker})
        rejected(create)
        rejected(lambda: create(key=EXISTING_KEY))
        rejected(lambda: create(retryOfAttemptId=ATTEMPT))
        rejected(edit)
        rejected(lambda: edit(key=EXISTING_KEY))
        rejected(lambda: ui_stream.replay(runtime, {}, lambda *_: None, WORKSPACE, "holder", ARTIFACT, 0))
        CHECKS.append(label + ": real parent create/duplicate/retry/edit/replay denied before UI/budget/provider boundaries")
    for boundary in (sweep, claim, reserve, settle, plan, events):
        boundary.assert_not_called()
    rejected(lambda: create(run=FOREIGN_RUN), 404, "ui_parent_run")
    rejected(lambda: ui_stream.replay(runtime, {}, lambda *_: None, WORKSPACE, "outsider", ARTIFACT, 0), 403, None)

write_result(BASE)
with ui_http.ui_transaction(runtime, "holder", WORKSPACE, "read") as (cur, auth):
    assert ui_stream._assert_parent_context(cur, auth, WORKSPACE, RUN)["runId"] == RUN
    rejected(lambda: ui_stream._assert_parent_context(cur, auth, FOREIGN, FOREIGN_RUN), 404, "ui_parent_run")
    projection = ui_projection.project_ui_context(cur, auth, BASE, "chat", {}, flags={"enabled": True, "actions": False})
    assert projection["journey_ids"] == ["J01"] and projection["fallback_text"] == BASE["answerText"]
before = state()
ordinary = b"".join(ui_stream.replay(runtime, {}, lambda *_: None, WORKSPACE, "holder", ARTIFACT, 0))
assert b"ui.ready" in ordinary and b"synthetic prior view" in ordinary and state() == before
CHECKS.append("ordinary projection/replay remains available; authenticated tenant/scope reads remain pinned; original historical revision preserved")

with ui_http.ui_transaction(runtime, "holder", WORKSPACE, "read") as (cur, auth):
    with cur.connection.transaction(force_rollback=True):
        cur.execute("UPDATE public.pr_agent_runs SET artifact=jsonb_set(artifact,'{result}',%s::jsonb) WHERE workspace_id=%s AND id=%s",
                    (json.dumps({agent_context.REMOVED: True}), WORKSPACE, RUN))
        try:
            ui_stream._assert_parent_context(cur, auth, WORKSPACE, RUN)
        except AlphaError as error:
            assert (error.status, error.code) == (409, "ui_not_eligible")
        else:
            raise AssertionError("Current transactional removal was ignored")
    assert ui_stream._assert_parent_context(cur, auth, WORKSPACE, RUN)["result"] == BASE
assert state() == before
CHECKS.append("uncommitted parent removal rolls back without mutating historical UI; no provider calls or production legal acceptance")
print(json.dumps({"execution": "CLOUD_SYNTHETIC", "externalProviderCalls": 0, "productionAcceptance": False, "checks": CHECKS}))
