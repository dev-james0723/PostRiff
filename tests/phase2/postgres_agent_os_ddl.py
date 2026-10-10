"""The PROPOSED agent OS migrations 108/109 (docs/design/rafii-agent-os/migrations) on a disposable PostgreSQL 17.

The DDL is a frozen proposal, not yet a numbered migration: this suite applies it on top of the repository's partial disposable-test migration chain
(tests/phase2/rls.sql) and proves the database-level rules the contracts rely on, so the files are freeze-ready before
lane J copies them into migrations/postriff/:
- service-only tables with forced RLS; browser roles can read nothing and call nothing;
- consent history is append-only for the server; membership end keeps it; only account deletion erases it;
- every task belongs to the person whose `task:` run anchors it; one open chat task per person per conversation;
- child rows cannot cross a workspace or a task; cron can only claim reads, observers and waits; every attempt runs as
  the task's creator; new approval kinds are owner-decided on a native surface; closing an approval records when;
- the read-only 'observe' verdict exists only on steps that observe an external effect (publish job, automation item).

Numbering (README §5 register): 108 = task engine (CF-3), 109 = permissions (CF-2). They are applied in number order, as
the runner would; neither depends on the other.

Run (cloud CI): PYTHONPATH=src:tests python scripts/postriff_pg_suite.py postgres_agent_os_ddl
"""
import json
import os
import re
import sys
import time
import traceback
import uuid
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/design/rafii-agent-os/migrations"
PORT = os.environ.get("POSTRIFF_PG_PORT", "55438")
DSN = f"host=127.0.0.1 port={PORT} dbname=postgres"
A = "00000000-0000-0000-0000-000000000001"   # owner of the main workspace (rls.sql bootstrap)
C = "00000000-0000-0000-0000-000000000002"   # owner of another tenant (rls.sql bootstrap)
B = "00000000-0000-0000-0000-000000000005"   # editor of the main workspace (added here)
HEX = "a" * 64
TABLES_PERMISSIONS = ("pr_agent_permission_state", "pr_agent_consent_receipts", "pr_agent_grants", "pr_agent_workspace_policy",
              "pr_agent_autopilot_policies", "pr_agent_permission_reminders")
TABLES_TASKS = ("pr_agent_tasks", "pr_agent_steps", "pr_agent_step_attempts", "pr_agent_checkpoints", "pr_agent_approvals",
              "pr_agent_receipts", "pr_agent_compensations")
EVIDENCE = []
errors = psycopg.errors


def connection(autocommit=False):
    return psycopg.connect(DSN, client_encoding="utf8", autocommit=autocommit)


def scenario(sid, title):
    def wrap(fn):
        started = time.monotonic()
        record = {"id": sid, "title": title}
        try:
            fn()
            record["result"] = "PASS"
        except Exception as error:  # noqa: BLE001
            record.update({"result": "FAIL", "error": f"{type(error).__name__}: {error}", "trace": traceback.format_exc()[-1800:]})
        record["ms"] = round((time.monotonic() - started) * 1000)
        EVIDENCE.append(record)
        print(f"{record['result']:5} {sid} {title}" + (f" — {record.get('error')}" if record["result"] == "FAIL" else ""), flush=True)
        return fn
    return wrap


def expect(db, exc, sql, params=()):
    """The statement must fail with exc; the surrounding transaction continues (savepoint)."""
    try:
        with db.transaction():
            db.execute(sql, params or None)
    except exc:
        return
    raise AssertionError(f"accepted: {' '.join(sql.split())[:160]}")


def trace():
    return "trace_" + uuid.uuid4().hex


def conversation(db, workspace, actor):
    return db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'agent os') RETURNING id::text",
                      (workspace, actor)).fetchone()[0]


def anchor(db, workspace, conv, actor, key="task"):
    return db.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,"
                      "idempotency_key) VALUES(%s,%s,%s,'running','test-model','standard',%s,%s,%s) RETURNING id::text",
                      (conv, workspace, actor, HEX, HEX, f"{key}:{uuid.uuid4()}")).fetchone()[0]


TASK_SQL = ("INSERT INTO public.pr_agent_tasks(id,workspace_id,conversation_id,created_by,origin,title,authz_token,request_key,request_digest,"
            "root_trace_id,expires_at,hard_expires_at) VALUES(%s,%s,%s,%s,%s,'Organize drafts',%s,%s,%s,%s,now()+interval '72 hours',"
            "now()+interval '14 days') RETURNING id::text")


def task_params(run, workspace, conv, actor, origin="chat", key=None):
    return (run, workspace, conv, actor, origin, HEX, key or f"req-{uuid.uuid4().hex}", "b" * 64, trace())


def task(db, run, workspace, conv, actor, origin="chat", key=None):
    return db.execute(TASK_SQL, task_params(run, workspace, conv, actor, origin, key)).fetchone()[0]


STEP_SQL = ("INSERT INTO public.pr_agent_steps(task_id,workspace_id,step_key,label,kind,capability_id,risk_class,effect,background_allowed,"
            "inputs,input_digest) VALUES(%s,%s,%s,'Step',%s,%s,%s,%s,%s,'{}'::jsonb,%s) RETURNING id::text")


def step_params(task_id, workspace, key="s1", risk="R0", effect="READ", background=False, kind="tool"):
    return (task_id, workspace, key, kind, "tool.help_search", risk, effect, background, "c" * 64)


def step(db, task_id, workspace, key="s1", risk="R0", effect="READ", background=False):
    return db.execute(STEP_SQL, step_params(task_id, workspace, key, risk, effect, background)).fetchone()[0]


ATTEMPT_SQL = ("INSERT INTO public.pr_agent_step_attempts(step_id,task_id,workspace_id,actor,attempt_no,generation,executor,lease_owner,"
               "lease_expires_at,deadline_at,authz_token,authz_verdict,trace_id) VALUES(%s,%s,%s,%s,%s,1,%s,%s,now()+interval '60 seconds',"
               "now()+interval '30 seconds',%s,%s,%s) RETURNING id::text")


def attempt_params(step_id, task_id, workspace, actor, executor="inline", no=1, verdict="allow"):
    owner = ("req:" if executor == "inline" else "cron:") + uuid.uuid4().hex
    return (step_id, task_id, workspace, actor, no, executor, owner, HEX, verdict, trace())


DELEGATE_SQL = ("INSERT INTO public.pr_agent_steps(task_id,workspace_id,step_key,label,kind,risk_class,effect,background_allowed,retry_class,"
                "max_attempts,timeout_seconds,delegate_type,delegate_id) VALUES(%s,%s,%s,'Watch it publish','delegate','R0','READ',true,'auto',5,10,%s,%s) "
                "RETURNING id::text")


APPROVAL_SQL = ("INSERT INTO public.pr_agent_approvals(workspace_id,task_id,step_id,generation,requested_for,kind,capability_id,capability_version,"
                "risk_class,confirmation,input_digest,inputs,digest,required_permission,approver_policy,authz_token,expires_at) "
                "VALUES(%s,%s,%s,1,%s,'agent_action','tool.campaign_link',1,'R1','native',%s,'{}'::jsonb,%s,'edit',%s,%s,now()+interval '24 hours') "
                "RETURNING id::text")


def approval_params(workspace, task_id, step_id, requested_for, policy="task_owner"):
    return (workspace, task_id, step_id, requested_for, "c" * 64, "d" * 64, policy, HEX)


def count(db, table, workspace):
    return db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s", (workspace,)).fetchone()[0]


# --- environment: the real chain (rls.sql), then the proposal twice (it must be re-runnable) ---------------------------------
with connection(autocommit=True) as db:
    for _ in range(2):
        db.execute((DOCS / "108_agent_tasks.sql").read_text())
        db.execute((DOCS / "109_agent_permissions.sql").read_text())
    W = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s ORDER BY workspace_id LIMIT 1", (A,)).fetchone()[0])
    W2 = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s AND workspace_id<>%s ORDER BY workspace_id LIMIT 1",
                        (C, W)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET status='active', role='owner' WHERE user_id=%s AND workspace_id=%s", (A, W))
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (B,))
    db.execute("INSERT INTO public.pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (B,))
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active') "
               "ON CONFLICT (workspace_id,user_id) DO UPDATE SET status='active', role='editor'", (W, B))


@scenario("AOS-01", "108 and 109 apply on the partial disposable-test migration chain and re-apply without error")
def _applied():
    with connection() as db:
        for table in TABLES_PERMISSIONS + TABLES_TASKS:
            assert db.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0], table
            forced = db.execute("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=to_regclass(%s)", (f"public.{table}",)).fetchone()[0]
            assert forced, f"{table} must force RLS"


@scenario("AOS-02", "browser roles read nothing and cannot call the erase function")
def _browser():
    with connection() as db:
        for role in ("authenticated", "anon"):
            with db.transaction(force_rollback=True):
                db.execute(f"SET LOCAL ROLE {role}")
                db.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (A,))
                for table in TABLES_PERMISSIONS + TABLES_TASKS:
                    expect(db, errors.InsufficientPrivilege, f"SELECT count(*) FROM public.{table}")
                expect(db, errors.InsufficientPrivilege, "SELECT postriff_private.agent_permissions_erase(%s)", (W,))


def consent(db, user, preset="recommended", epoch=1):
    db.execute("INSERT INTO public.pr_agent_permission_state(workspace_id,user_id,epoch,preset,preset_version,spend_confirmation,consent_version,"
               "copy_digest,catalogue_generation,catalogue_digest,decided_by) VALUES(%s,%s,%s,%s,1,'all','agent-permissions/1',%s,1,%s,%s)",
               (W, user, epoch, preset, HEX, HEX, user))
    receipt = db.execute("INSERT INTO public.pr_agent_consent_receipts(workspace_id,user_id,actor,kind,source,epoch_before,epoch_after,preset_after,"
                         "scopes_before,scopes_after,widened,consent_version,catalogue_digest,idempotency_key,request_fingerprint) "
                         "VALUES(%s,%s,%s,'preset_applied','onboarding',0,%s,%s,'{}','{}',true,'agent-permissions/1',%s,%s,%s) RETURNING id::text",
                         (W, user, user, epoch, preset, HEX, f"idem-{uuid.uuid4().hex}", "e" * 64)).fetchone()[0]
    grant = db.execute("INSERT INTO public.pr_agent_grants(workspace_id,user_id,scope,mode,granted_epoch,granted_by,receipt_id) "
                       "VALUES(%s,%s,'category:create_edit','assist',%s,%s,%s) RETURNING id::text", (W, user, epoch, user, receipt)).fetchone()[0]
    return receipt, grant


@scenario("AOS-03", "server role: consent history is append-only; a revoked grant can never be revived")
def _append_only():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        receipt, grant = consent(db, A)
        expect(db, errors.InsufficientPrivilege, "DELETE FROM public.pr_agent_permission_state WHERE workspace_id=%s", (W,))
        expect(db, errors.InsufficientPrivilege, "DELETE FROM public.pr_agent_grants WHERE id=%s", (grant,))
        expect(db, errors.InsufficientPrivilege, "DELETE FROM public.pr_agent_consent_receipts WHERE id=%s", (receipt,))
        expect(db, errors.InsufficientPrivilege, "UPDATE public.pr_agent_consent_receipts SET widened=false WHERE id=%s", (receipt,))
        expect(db, errors.InsufficientPrivilege, "UPDATE public.pr_agent_grants SET scope='category:read_analyze' WHERE id=%s", (grant,))
        db.execute("UPDATE public.pr_agent_grants SET revoked_epoch=2,revoked_by=%s,revoked_at=now(),revoke_reason='changed' WHERE id=%s", (A, grant))
        expect(db, errors.ObjectNotInPrerequisiteState,
               "UPDATE public.pr_agent_grants SET revoked_epoch=NULL,revoked_by=NULL,revoked_at=NULL,revoke_reason=NULL WHERE id=%s", (grant,))
        # A Full preset without a recorded fresh sign-in is refused by the table itself (DP-4).
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_permission_state SET preset='full' WHERE workspace_id=%s AND user_id=%s", (W, A))
        expect(db, errors.CheckViolation, "INSERT INTO public.pr_agent_consent_receipts(workspace_id,user_id,actor,kind,source,epoch_before,epoch_after,"
               "preset_after,scopes_before,scopes_after,widened,consent_version,catalogue_digest,idempotency_key,request_fingerprint) VALUES(%s,%s,%s,"
               "'preset_applied','genui',1,2,'custom','{}','{}',true,'agent-permissions/1',%s,%s,%s)", (W, A, A, HEX, f"idem-{uuid.uuid4().hex}", "e" * 64))


@scenario("AOS-04", "membership end keeps the history; deleting the membership is refused until account deletion erases it")
def _membership_end():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        consent(db, B)
        db.execute("RESET ROLE")
        db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (W, B))
        db.execute("SET LOCAL ROLE service_role")
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_permission_state SET ended_at=now() WHERE workspace_id=%s AND user_id=%s", (W, B))
        db.execute("UPDATE public.pr_agent_permission_state SET ended_at=now(),preset='none',baseline=NULL,epoch=epoch+1 WHERE workspace_id=%s AND user_id=%s", (W, B))
        db.execute("RESET ROLE")
        expect(db, errors.ForeignKeyViolation, "DELETE FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s", (W, B))
        db.execute("SET LOCAL ROLE service_role")
        expect(db, errors.ObjectNotInPrerequisiteState, "SELECT postriff_private.agent_permissions_erase(%s)", (W,))
        db.execute("RESET ROLE")
        db.execute("""UPDATE public.pr_workspaces SET state=coalesce(state,'{}'::jsonb)||'{"accountDeletion":{"receiptId":"r"}}'::jsonb WHERE id=%s""", (W,))
        db.execute("SET LOCAL ROLE service_role")
        removed = db.execute("SELECT postriff_private.agent_permissions_erase(%s)", (W,)).fetchone()[0]
        assert removed >= 3, removed
        db.execute("RESET ROLE")
        db.execute("DELETE FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s", (W, B))
        for table in TABLES_PERMISSIONS:
            assert count(db, table, W) == 0, table


@scenario("AOS-05", "a task is anchored on its creator's own task: run in the same workspace, and its identity never changes")
def _anchor():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        run = anchor(db, W, conv, A)
        expect(db, errors.CheckViolation, TASK_SQL, task_params(run, W, conv, B))                       # someone else's run
        expect(db, errors.CheckViolation, TASK_SQL, task_params(anchor(db, W, conv, A, key="agent"), W, conv, A))   # not a task: row
        expect(db, errors.CheckViolation, TASK_SQL, task_params(run, W2, conv, A))                      # other workspace
        created = task(db, run, W, conv, A)
        expect(db, errors.ObjectNotInPrerequisiteState, "UPDATE public.pr_agent_tasks SET created_by=%s WHERE id=%s", (B, created))
        db.execute("UPDATE public.pr_agent_tasks SET state='running', version=version+1 WHERE id=%s", (created,))


@scenario("AOS-06", "one open chat task per person per conversation (not per conversation)")
def _one_open():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        first = task(db, anchor(db, W, conv, A), W, conv, A)
        task(db, anchor(db, W, conv, B), W, conv, B)                       # B's own task in A's conversation is separate
        second_run = anchor(db, W, conv, A)
        expect(db, errors.UniqueViolation, TASK_SQL, task_params(second_run, W, conv, A))
        db.execute("UPDATE public.pr_agent_tasks SET state='completed', finished_at=now() WHERE id=%s", (first,))
        task(db, second_run, W, conv, A)


@scenario("AOS-07", "children cannot cross a workspace or a task")
def _composite():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        mine = task(db, anchor(db, W, conv, A), W, conv, A)
        s1 = step(db, mine, W)
        expect(db, errors.ForeignKeyViolation, STEP_SQL, step_params(mine, W2, key="s2"))
        other = task(db, anchor(db, W, conv, A), W, conv, A, origin="task_center")
        step(db, other, W)
        expect(db, errors.ForeignKeyViolation, ATTEMPT_SQL, attempt_params(s1, other, W, A))
        expect(db, errors.ForeignKeyViolation, APPROVAL_SQL, approval_params(W, other, s1, A))


@scenario("AOS-08", "cron claims only reads, observers and waits; every attempt runs as the creator; one live attempt per step")
def _executors():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        owned = task(db, anchor(db, W, conv, A), W, conv, A)
        expect(db, errors.CheckViolation, STEP_SQL, step_params(owned, W, key="s1", risk="R1", effect="CREATE_DRAFT", background=True))
        r1 = step(db, owned, W, key="s2", risk="R1", effect="CREATE_DRAFT")
        expect(db, errors.CheckViolation, ATTEMPT_SQL, attempt_params(r1, owned, W, A, executor="cron"))
        expect(db, errors.CheckViolation, ATTEMPT_SQL, attempt_params(r1, owned, W, B))
        db.execute(ATTEMPT_SQL, attempt_params(r1, owned, W, A))
        expect(db, errors.UniqueViolation, ATTEMPT_SQL, attempt_params(r1, owned, W, A, no=2))
        read = step(db, owned, W, key="s3", background=True)
        db.execute(ATTEMPT_SQL, attempt_params(read, owned, W, A, executor="cron"))


@scenario("AOS-09", "approvals: owner-decided new kinds, native surfaces only, every close records when")
def _approvals():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        owned = task(db, anchor(db, W, conv, A), W, conv, A)
        s1 = step(db, owned, W, risk="R1", effect="MUTATE_REVERSIBLE")
        expect(db, errors.CheckViolation, APPROVAL_SQL, approval_params(W, owned, s1, B))
        expect(db, errors.CheckViolation, APPROVAL_SQL, approval_params(W, owned, s1, A, policy="role_approve"))
        first = db.execute(APPROVAL_SQL, approval_params(W, owned, s1, A)).fetchone()[0]
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_approvals SET state='approved',decided_by=%s,decided_at=now(),decision_surface='panel' "
               "WHERE id=%s", (B, first))
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_approvals SET state='approved',decided_by=%s,decided_at=now(),decision_surface='voice' "
               "WHERE id=%s", (A, first))
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_approvals SET state='expired' WHERE id=%s", (first,))
        db.execute("UPDATE public.pr_agent_approvals SET state='approved',decided_by=%s,decided_at=now(),decision_surface='panel' WHERE id=%s", (A, first))
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_approvals SET state='consumed' WHERE id=%s", (first,))
        db.execute("UPDATE public.pr_agent_approvals SET state='consumed',consumed_at=now() WHERE id=%s", (first,))
        second = db.execute(APPROVAL_SQL, approval_params(W, owned, step(db, owned, W, key="s2"), A)).fetchone()[0]
        db.execute("UPDATE public.pr_agent_approvals SET state='expired',decided_at=now(),decision_surface='system' WHERE id=%s", (second,))
        message = db.execute("INSERT INTO public.pr_messages(conversation_id,workspace_id,seq,role,body) VALUES(%s,%s,1,'assistant','{}') "
                             "RETURNING id::text", (conv, W)).fetchone()[0]
        s3 = db.execute(STEP_SQL, step_params(owned, W, key="s3", kind="approval")).fetchone()[0]
        legacy = db.execute("INSERT INTO public.pr_agent_approvals(workspace_id,task_id,step_id,generation,requested_for,kind,proposal_id,proposal_type,"
                            "conversation_id,message_id,risk_class,confirmation,digest,required_permission,approver_policy,authz_token,expires_at) "
                            "VALUES(%s,%s,%s,1,%s,'proposal','prop-1','schedule_draft',%s,%s,'R2','proposal',%s,'approve','role_approve',%s,"
                            "now()+interval '24 hours') RETURNING id::text", (W, owned, s3, A, conv, message, "d" * 64, HEX)).fetchone()[0]
        db.execute("UPDATE public.pr_agent_approvals SET state='approved',decided_by=%s,decided_at=now(),decision_surface='text' WHERE id=%s", (B, legacy))


@scenario("AOS-10", "a request key is unique per workspace, so another member's reuse conflicts instead of creating a second task")
def _request_key():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        task(db, anchor(db, W, conv, A), W, conv, A, origin="task_center", key="req-shared-key-0000000001")
        expect(db, errors.UniqueViolation, TASK_SQL, task_params(anchor(db, W, conv, B), W, conv, B, origin="task_center", key="req-shared-key-0000000001"))


@scenario("AOS-11", "private model state is cleared when a checkpoint is consumed or discarded")
def _checkpoint():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        owned = task(db, anchor(db, W, conv, A), W, conv, A)
        cp = db.execute("INSERT INTO public.pr_agent_checkpoints(task_id,workspace_id,kind,payload,runtime_version,sdk_version,expires_at) "
                        "VALUES(%s,%s,'sdk_run_state','{\"state\":1}','rafii-v2','0.0.0',now()+interval '24 hours') RETURNING id::text", (owned, W)).fetchone()[0]
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_checkpoints SET state='consumed' WHERE id=%s", (cp,))
        db.execute("UPDATE public.pr_agent_checkpoints SET state='consumed',payload='{}' WHERE id=%s", (cp,))


@scenario("AOS-12", "the server cannot delete engine rows; deleting the conversation removes them with it")
def _cascade():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        owned = task(db, anchor(db, W, conv, A), W, conv, A)
        s1 = step(db, owned, W)
        attempt = db.execute(ATTEMPT_SQL, attempt_params(s1, owned, W, A)).fetchone()[0]
        # The turn rows of the same conversation are deleted with it: their ON DELETE SET NULL on attempts and approvals
        # fires during the cascade and must not be refused by the guards.
        turn = anchor(db, W, conv, A, key="agent")
        db.execute("UPDATE public.pr_agent_step_attempts SET run_id=%s WHERE id=%s", (turn, attempt))
        foreign = anchor(db, W2, conversation(db, W2, C), C, key="agent")
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_step_attempts SET run_id=%s WHERE id=%s", (foreign, attempt))
        pending = db.execute(APPROVAL_SQL, approval_params(W, owned, step(db, owned, W, key="s2", risk="R1", effect="MUTATE_REVERSIBLE"), A)).fetchone()[0]
        db.execute("UPDATE public.pr_agent_approvals SET run_id=%s WHERE id=%s", (turn, pending))
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_approvals SET run_id=%s WHERE id=%s", (foreign, pending))
        expect(db, errors.ObjectNotInPrerequisiteState, "UPDATE public.pr_agent_approvals SET requested_for=%s WHERE id=%s", (B, pending))
        db.execute("INSERT INTO public.pr_agent_receipts(workspace_id,effect_key,task_id,step_id,attempt_id,principal,capability_id,input_digest,trace_id) "
                   "VALUES(%s,%s,%s,%s,%s,%s,'tool.help_search',%s,%s)", (W, f"tsk:{uuid.uuid4().hex}:s1:g1", owned, s1, attempt, A, "c" * 64, trace()))
        expect(db, errors.CheckViolation, "INSERT INTO public.pr_agent_receipts(workspace_id,effect_key,task_id,step_id,principal,capability_id,input_digest,"
               "trace_id) VALUES(%s,%s,%s,%s,%s,'tool.help_search',%s,%s)", (W, f"tsk:{uuid.uuid4().hex}:s1:g1", owned, s1, B, "c" * 64, trace()))
        db.execute("SET LOCAL ROLE service_role")
        for table in TABLES_TASKS:
            expect(db, errors.InsufficientPrivilege, f"DELETE FROM public.{table} WHERE workspace_id=%s", (W,))
        db.execute("RESET ROLE")
        db.execute("DELETE FROM public.pr_conversations WHERE id=%s", (conv,))
        for table in TABLES_TASKS:
            assert count(db, table, W) == 0, table


@scenario("AOS-13", "the read-only 'observe' verdict is accepted only on a step that observes an external effect")
def _observer():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        owned = task(db, anchor(db, W, conv, A), W, conv, A)
        publish = db.execute(DELEGATE_SQL, (owned, W, "s1", "publish_job", "job-1")).fetchone()[0]
        proposal = db.execute(DELEGATE_SQL, (owned, W, "s2", "proposal", "prop-1")).fetchone()[0]
        read = step(db, owned, W, key="s3", background=True)
        assert db.execute("SELECT observes_external FROM public.pr_agent_steps WHERE id=%s", (publish,)).fetchone()[0] is True
        expect(db, errors.CheckViolation, ATTEMPT_SQL, attempt_params(proposal, owned, W, A, executor="cron", verdict="observe"))
        expect(db, errors.CheckViolation, ATTEMPT_SQL, attempt_params(read, owned, W, A, executor="cron", verdict="observe"))
        expect(db, errors.CheckViolation, ATTEMPT_SQL, attempt_params(publish, owned, W, A, executor="inline", verdict="observe"))
        expect(db, errors.CheckViolation, ATTEMPT_SQL, attempt_params(publish, owned, W, A, executor="cron", verdict="watch"))
        # A cancelled task (or an ended membership) still lets its publish observer record a read-only poll, as the creator.
        db.execute("UPDATE public.pr_agent_tasks SET cancel_requested_at=now(), cancel_requested_by=%s WHERE id=%s", (A, owned))
        db.execute(ATTEMPT_SQL, attempt_params(publish, owned, W, A, executor="cron", verdict="observe"))
        expect(db, errors.CheckViolation, ATTEMPT_SQL, attempt_params(publish, owned, W, B, executor="cron", no=2, verdict="observe"))


@scenario("AOS-14", "Full sign-in is fresh at decision time and grants cannot cite another person's receipt")
def _permission_subject_and_freshness():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        receipt_a, _ = consent(db, A)
        consent(db, B)
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_permission_state SET preset='full', step_up_at=decided_at-interval '301 seconds' WHERE workspace_id=%s AND user_id=%s", (W, A))
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_permission_state SET preset='full', step_up_at=decided_at+interval '1 second' WHERE workspace_id=%s AND user_id=%s", (W, A))
        db.execute("UPDATE public.pr_agent_permission_state SET preset='full',step_up_at=decided_at-interval '299 seconds' WHERE workspace_id=%s AND user_id=%s", (W, A))
        expect(db, errors.ForeignKeyViolation, "INSERT INTO public.pr_agent_grants(workspace_id,user_id,scope,mode,granted_epoch,granted_by,receipt_id) VALUES(%s,%s,'category:navigate_interact','assist',1,%s,%s)", (W, B, B, receipt_a))


@scenario("AOS-15", "receipts and compensations cannot cite another task's attempt or effect")
def _receipt_subjects():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        mine = task(db, anchor(db, W, conv, A), W, conv, A)
        other = task(db, anchor(db, W, conv, B), W, conv, B)
        s1, s2 = step(db, mine, W), step(db, other, W)
        a1 = db.execute(ATTEMPT_SQL, attempt_params(s1, mine, W, A)).fetchone()[0]
        a2 = db.execute(ATTEMPT_SQL, attempt_params(s2, other, W, B)).fetchone()[0]
        effect = 'tsk:' + uuid.uuid4().hex + ':s1:g1'
        insert = "INSERT INTO public.pr_agent_receipts(workspace_id,effect_key,task_id,step_id,attempt_id,principal,capability_id,input_digest,trace_id) VALUES(%s,%s,%s,%s,%s,%s,'tool.help_search',%s,%s)"
        expect(db, errors.ForeignKeyViolation, insert, (W, effect, mine, s1, a2, A, HEX, trace()))
        db.execute(insert, (W, effect, mine, s1, a1, A, HEX, trace()))
        undo = "INSERT INTO public.pr_agent_compensations(workspace_id,task_id,step_id,effect_key,inverse_capability_id,target_type,target_id,post_image_digest,inverse_inputs,undo_until) VALUES(%s,%s,%s,%s,'tool.draft_restore','draft','test',%s,'{}',now()+interval '24 hours')"
        expect(db, errors.ForeignKeyViolation, undo, (W, other, s2, effect, HEX))
        db.execute(undo, (W, mine, s1, effect, HEX))


@scenario("AOS-16", "plan runs stay in the workspace and approvals stay in the task's conversation")
def _plan_and_approval_subjects():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        mine = task(db, anchor(db, W, conv, A), W, conv, A)
        s1 = step(db, mine, W)
        foreign = anchor(db, W2, conversation(db, W2, C), C, key="agent")
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_steps SET planned_run_id=%s WHERE id=%s", (foreign, s1))
        local = anchor(db, W, conv, A, key="agent")
        db.execute("UPDATE public.pr_agent_steps SET planned_run_id=%s WHERE id=%s", (local, s1))
        wrong_conv = conversation(db, W, A)
        # Use an explicit INSERT so the same-tenant conversation mismatch is isolated from other validation.
        sql = "INSERT INTO public.pr_agent_approvals(workspace_id,task_id,step_id,generation,requested_for,kind,conversation_id,capability_id,risk_class,confirmation,input_digest,inputs,digest,required_permission,approver_policy,authz_token,expires_at) VALUES(%s,%s,%s,1,%s,'agent_action',%s,'tool.draft_edit','R1','native',%s,'{}',%s,'edit','task_owner',%s,now()+interval '24 hours')"
        expect(db, errors.CheckViolation, sql, (W, mine, s1, A, wrong_conv, HEX, HEX, HEX))
        db.execute(sql, (W, mine, s1, A, conv, HEX, HEX, HEX))


@scenario("AOS-17", "frozen claim SQL preserves external observers after cancel and membership end, even with another approval pending")
def _observer_claim():
    with connection() as db, db.transaction(force_rollback=True):
        db.execute("SET LOCAL ROLE service_role")
        conv = conversation(db, W, A)
        mine = task(db, anchor(db, W, conv, A), W, conv, A)
        publish = db.execute(DELEGATE_SQL, (mine, W, "s1", "publish_job", "job-claim")).fetchone()[0]
        db.execute("UPDATE public.pr_agent_tasks SET state='awaiting_approval',cancel_requested_at=now(),cancel_requested_by=%s,attempts_left=0 WHERE id=%s", (A, mine))
        db.execute("UPDATE public.pr_agent_steps SET next_attempt_at=now(),attempts=20 WHERE id=%s", (publish,))
        db.execute("RESET ROLE")
        db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (W, A))
        db.execute("SET LOCAL ROLE service_role")
        doc = (DOCS.parent / "CF-3-task-engine.md").read_text()
        claim = re.search(r"```sql\n(.*?)```", doc[doc.index("### 5.2"):], re.S).group(1)
        claim = claim[:claim.index(";", claim.index("RETURNING")) + 1]
        args = dict(kinds=['delegate'], engine_all=False, engine_workspaces=[], executor='cron', principal=A, seconds_left=300)
        assert db.execute(claim, args).fetchone() is None, "an unlisted workspace was claimed"
        args['engine_workspaces'] = [W]
        row = db.execute(claim, args).fetchone()
        assert row is not None and str(row[0]) == publish and row[4] == 21, row
        attempt = db.execute(ATTEMPT_SQL, attempt_params(publish, mine, W, A, executor='cron', no=21, verdict='observe')).fetchone()[0]
        expect(db, errors.ObjectNotInPrerequisiteState, "UPDATE public.pr_agent_step_attempts SET attempt_no=22 WHERE id=%s", (attempt,))
        ordinary = step(db, mine, W, key='s2', background=True)
        expect(db, errors.CheckViolation, "UPDATE public.pr_agent_steps SET attempts=21 WHERE id=%s", (ordinary,))
        expect(db, errors.CheckViolation, ATTEMPT_SQL, attempt_params(ordinary, mine, W, A, executor='cron', no=21))
        db.execute("UPDATE public.pr_agent_step_attempts SET state='succeeded',finished_at=now() WHERE id=%s", (attempt,))
        db.execute("UPDATE public.pr_agent_steps SET state='queued',next_attempt_at=now() WHERE id=%s", (publish,))
        db.execute("UPDATE public.pr_agent_tasks SET hard_expires_at=now()-interval '1 second',expires_at=now()-interval '1 second' WHERE id=%s", (mine,))
        assert db.execute(claim, args).fetchone() is None, 'an observer outlived the hard TTL'


summary = {"PASS": sum(1 for e in EVIDENCE if e["result"] == "PASS"), "FAIL": sum(1 for e in EVIDENCE if e["result"] == "FAIL")}
print(json.dumps({"execution": "disposable PostgreSQL; proposed agent OS DDL 108/109 on the partial disposable-test migration chain", "summary": summary,
                  "failed": [e for e in EVIDENCE if e["result"] == "FAIL"]}, default=str))
sys.exit(1 if summary["FAIL"] or not summary["PASS"] else 0)
