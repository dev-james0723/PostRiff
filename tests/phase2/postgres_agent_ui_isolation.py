"""rafii-genui/1 lane D on a disposable PostgreSQL: row-level and scope isolation of the generated-UI tables (G07 G14).

- The six migration-102 tables are service-only: a signed-in member's `authenticated` role (PostgREST) can neither read
  nor write them, in their own workspace or another, so raw source, manifests, receipts and activations never leak
  through the browser database API.
- Scope: a founder-scope artifact answers only on the founder path (founder auth + founder scope), a consumer artifact
  never there; founder data a consumer manifest could name does not exist; absent founder metrics stay unavailable.
- Membership changes take effect on the next request: a member removed from the workspace, or demoted, loses the reads
  or writes at once, even with a manifest issued while they had them.

Run: PYTHONPATH=src:tests python scripts/postriff_pg_suite.py postgres_agent_ui_isolation
"""
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.agent_runtime_v2 import config, ui_actions, ui_capabilities, ui_contracts, ui_http, ui_queries  # noqa: E402

PORT = os.environ.get("POSTRIFF_PG_PORT", "55438")
DSN = f"host=127.0.0.1 port={PORT} dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
MEMBER_ID = "00000000-0000-0000-0000-000000000003"
OTHER_ID = "00000000-0000-0000-0000-000000000004"
TOKENS = {"owner-token-0000000000000000000": ONE, "member-token-000000000000000000": MEMBER_ID, "other-token-0000000000000000000": OTHER_ID}
OWNER, MEMBER, OTHER = list(TOKENS)
TABLES = ("pr_ui_artifacts", "pr_ui_revisions", "pr_ui_attempts", "pr_ui_events", "pr_ui_actions", "pr_ui_activations")
RESULTS = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required.", 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: f"session-{principal}-0123456789abcdef"
verify.auth_time = lambda token, principal: time.time()


def scenario(sid, title):
    def wrap(fn):
        record = {"id": sid, "title": title}
        try:
            record.update({"result": "PASS", **(fn() or {})})
        except Exception as error:  # noqa: BLE001
            record.update({"result": "FAIL", "error": f"{type(error).__name__}: {error}", "trace": traceback.format_exc()[-2000:]})
        RESULTS.append(record)
        print(f"{record['result']:5} {sid} {title}" + (f"\n      {record.get('error')}\n{record.get('trace')}" if record["result"] == "FAIL" else ""), flush=True)
        return fn
    return wrap


def denied(call, status=None, code=None):
    try:
        call()
    except AlphaError as error:
        assert status is None or error.status == status, (error.status, error.code, str(error))
        assert code is None or error.code == code, (error.status, error.code, str(error))
        return error
    raise AssertionError("call was accepted")


with connection() as db:
    db.execute((ROOT / "migrations/postriff/102_agent_ui_artifacts.sql").read_text())
    db.execute("INSERT INTO auth.users VALUES(%s),(%s) ON CONFLICT DO NOTHING", (MEMBER_ID, OTHER_ID))
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
    db.execute("UPDATE public.pr_memberships SET status='active', role='owner' WHERE user_id=%s", (ONE,))
service = HostedWorkspaceService(connection, verify, clock=time.time)
service.bootstrap(OWNER, "studio")
service.bootstrap(MEMBER, "studio")
other_wid = service.bootstrap(OTHER, "studio")["workspaceId"]
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (wid, MEMBER_ID))
runtime = SimpleNamespace(service=service, cfg=config.RuntimeConfig.from_environment({"RAFII_AGENT_V2_ENABLED": "1", "RAFII_GENUI_ENABLED": "1",
                                                                                     "RAFII_GENUI_ACTIONS_ENABLED": "1"}))


def auth_for(token, workspace, scope="workspace", scope_key=""):
    with service.repository.transaction(token, workspace) as (_cur, row, principal):
        member = service.ideas._member(row)
    return ui_http.UiAuth(workspace_id=workspace, principal=str(principal), member=member, role=member.role, scope=scope, scope_key=scope_key)


def artifact(workspace, token, journeys, *, scope="workspace", scope_key="", run_key=None):
    with connection() as db:
        conv = str(db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'iso') RETURNING id", (workspace, TOKENS[token])).fetchone()[0])
        run = str(db.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) "
                             "VALUES(%s,%s,%s,'completed','rafii-agent','standard',%s,%s,%s,'{}'::jsonb) RETURNING id",
                             (conv, workspace, TOKENS[token], "a" * 64, "b" * 64, run_key or ("agent:" + uuid.uuid4().hex))).fetchone()[0])
    auth = auth_for(token, workspace, scope, scope_key)
    manifest = ui_capabilities.build_manifest(None, auth, {"journey_ids": journeys}, scope=scope)
    with connection() as db:
        art = str(db.execute("INSERT INTO public.pr_ui_artifacts(workspace_id,scope,scope_key,conversation_id,parent_run_id,actor,surface,journey_ids,revision,source_hash,"
                             "generation_state,validation_state,manifest,manifest_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1,%s,'ready','accepted',%s::jsonb,%s) RETURNING id",
                             (workspace, scope, scope_key, conv, run, TOKENS[token], "founder" if scope == "founder" else "chat", journeys, "c" * 64, json.dumps(manifest),
                              manifest["manifestId"])).fetchone()[0])
        db.execute("INSERT INTO public.pr_ui_activations(id,workspace_id,principal,artifact_id,artifact_revision,action_id,input_digest,binding_version,expires_at) "
                   "VALUES(%s,%s,%s,%s,1,'draft_edit',%s,1,now()+interval '1 minute')", (ui_contracts.new_activation_id(), workspace, TOKENS[token], art, "d" * 64))
    return {"artifactId": art, "manifest": manifest}


A = artifact(wid, OWNER, ["J01", "J05"])
B = artifact(other_wid, OTHER, ["J01"])
FOUNDER = artifact(wid, OWNER, ["J09"], scope="founder", scope_key="founder:live:test", run_key="agent:founder:live:test:" + uuid.uuid4().hex)


@scenario("I01", "The six UI tables are service-only: a member's authenticated role can't read or write them, own workspace or not")
def _():
    blocked = []
    for user in (ONE, OTHER_ID):
        for table in TABLES:
            with connection() as db:
                db.execute("SET ROLE authenticated")
                db.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (user,))
                for sql in (f"SELECT count(*) FROM public.{table}", f"DELETE FROM public.{table}"):
                    try:
                        db.execute("SAVEPOINT probe")
                        db.execute(sql)
                        raise AssertionError(f"{sql} was allowed for {user}")
                    except psycopg.errors.InsufficientPrivilege:
                        db.execute("ROLLBACK TO SAVEPOINT probe")
                        blocked.append((user[-1], table, sql.split()[0]))
    with connection() as db:
        assert db.execute("SELECT count(*) FROM public.pr_ui_artifacts").fetchone()[0] == 3, "the probes changed nothing"
        for table in TABLES:
            policies = {r[0] for r in db.execute("SELECT policyname FROM pg_policies WHERE schemaname='public' AND tablename=%s", (table,)).fetchall()}
            assert policies == {"service_only"}, (table, policies)
            forced = db.execute("SELECT relforcerowsecurity FROM pg_class WHERE oid=('public.'||%s)::regclass", (table,)).fetchone()[0]
            assert forced is True, table
    return {"blocked": len(blocked)}


@scenario("I02", "Cross-tenant: neither owner reaches the other's artifact, through either workspace; the answers can't be told from a ghost id")
def _():
    req = lambda art, binding="drafts_list": ui_contracts.validate_query({"artifactId": art["artifactId"], "artifactRevision": 1, "bindingId": binding, "inputs": {}})  # noqa: E731
    ghost = denied(lambda: ui_queries.query_http(runtime, wid, OWNER, req({"artifactId": str(uuid.uuid4())})), 404)
    foreign = denied(lambda: ui_queries.query_http(runtime, wid, OWNER, req(B)), 404)
    assert (ghost.code, str(ghost)) == (foreign.code, str(foreign))
    denied(lambda: ui_queries.query_http(runtime, other_wid, OWNER, req(B)), 403)
    denied(lambda: ui_actions.activate_http(runtime, wid, OWNER, ui_contracts.validate_activation(
        {"artifactId": B["artifactId"], "artifactRevision": 1, "actionId": "campaign_create", "inputs": {"goal": "x", "audience": "y"}})), 404)
    # B's activation id used against A's artifact (a forged pairing) is refused as an invalid confirmation.
    with connection() as db:
        b_activation = db.execute("SELECT id FROM public.pr_ui_activations WHERE artifact_id=%s", (B["artifactId"],)).fetchone()[0]
    denied(lambda: ui_actions.execute_http(runtime, wid, OWNER, ui_contracts.validate_action(
        {"artifactId": A["artifactId"], "artifactRevision": 1, "actionId": "campaign_create", "inputs": {"goal": "x", "audience": "y"},
         "idempotencyKey": "k_" + uuid.uuid4().hex, "activationId": b_activation})), 409, "ui_activation")
    return {}


@scenario("I03", "Founder scope: consumer routes 404 it; the founder path serves it read-only and absent metrics stay unavailable")
def _():
    req = ui_contracts.validate_query({"artifactId": FOUNDER["artifactId"], "artifactRevision": 1, "bindingId": "founder_metrics", "inputs": {"metricIds": ["mrr"], "period": "30d"}})
    denied(lambda: ui_queries.query_http(runtime, wid, OWNER, req), 404, "ui_artifact")
    founder_auth = auth_for(OWNER, wid, scope="founder", scope_key="founder:live:test")
    with service.repository.transaction(OWNER, wid) as (cur, _row, _p):
        art, manifest = ui_capabilities.load_artifact(cur, founder_auth, FOUNDER["artifactId"])
        consumer_art = denied(lambda: ui_capabilities.load_artifact(cur, founder_auth, A["artifactId"]), 404)
        out = ui_queries.query_ui_binding(cur, founder_auth, art, manifest, req, runtime=runtime,
                                          founder={"mode": "live", "environment": "test", "principal": {"userId": ONE}, "request_id": "req-1"})
    assert out["state"] in ("unavailable", "denied") and out["data"] is None, out
    # Through query_http exactly as the founder route calls it (founder runtime + its capability): founder artifact served,
    # a consumer artifact of the same workspace is the same 404 as a ghost.
    founder_runtime = SimpleNamespace(service=service, cfg=runtime.cfg, founder={"namespace": "founder:live:test", "mode": "live", "environment": "test",
                                                                                 "principal": {"userId": ONE}, "request_id": "req-2"})
    served = ui_queries.query_http(founder_runtime, wid, OWNER, req)
    assert served["state"] in ("unavailable", "denied"), served
    other_ns = SimpleNamespace(service=service, cfg=runtime.cfg, founder={**founder_runtime.founder, "namespace": "founder:demo:test"})
    denied(lambda: ui_queries.query_http(other_ns, wid, OWNER, req), 404, "ui_artifact")
    denied(lambda: ui_queries.query_http(founder_runtime, wid, OWNER, ui_contracts.validate_query(
        {"artifactId": A["artifactId"], "artifactRevision": 1, "bindingId": "drafts_list"})), 404, "ui_artifact")
    assert manifest["actions"] == [] and all(q["name"].startswith("founder_") for q in manifest["queries"])
    denied(lambda: ui_capabilities.build_manifest(None, auth_for(OWNER, wid), {"journey_ids": ["J09"]}, scope="founder"), 404)
    return {"founderState": out["state"], "consumerOnFounder": consumer_art.code}


@scenario("I04", "Membership is re-read on every request: demotion drops writes at once, removal drops reads")
def _():
    rev = ui_queries.query_http(runtime, wid, MEMBER, ui_contracts.validate_query({"artifactId": A["artifactId"], "artifactRevision": 1, "bindingId": "campaigns_list"}))
    assert rev["state"] in ("empty", "available")
    act = ui_actions.activate_http(runtime, wid, MEMBER, ui_contracts.validate_activation(
        {"artifactId": A["artifactId"], "artifactRevision": 1, "actionId": "campaign_create", "inputs": {"goal": "Spring recital", "audience": "Families"}}))
    with connection() as db:
        db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s", (wid, MEMBER_ID))
    denied(lambda: ui_actions.execute_http(runtime, wid, MEMBER, ui_contracts.validate_action(
        {"artifactId": A["artifactId"], "artifactRevision": 1, "actionId": "campaign_create", "inputs": {"goal": "Spring recital", "audience": "Families"},
         "idempotencyKey": "k_" + uuid.uuid4().hex, "activationId": act["activationId"]})), 404, "ui_action")
    campaigns = service.get(wid, OWNER)["state"].get("raffi", {}).get("campaignPlanning", {}).get("campaigns", [])
    assert not any(c.get("goal") == "Spring recital" for c in campaigns), "the demoted member's confirmed action never ran"
    with connection() as db:
        db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (wid, MEMBER_ID))
    denied(lambda: ui_queries.query_http(runtime, wid, MEMBER, ui_contracts.validate_query({"artifactId": A["artifactId"], "artifactRevision": 1, "bindingId": "campaigns_list"})),
           403)
    return {}


failed = [r for r in RESULTS if r["result"] != "PASS"]
print(json.dumps({"script": "postgres_agent_ui_isolation", "passed": len(RESULTS) - len(failed), "failed": len(failed),
                  "scenarios": [{k: r.get(k) for k in ("id", "result")} for r in RESULTS]}), flush=True)
sys.exit(1 if failed else 0)
