"""Lane F on a disposable PostgreSQL 17: durable Generative UI artifacts (migration 102) through the real hosted repository.

Real HostedWorkspaceService transactions (verified session -> active membership -> workspace row lock), real roles
(owner/editor/viewer), a second tenant, a founder-scoped artifact, the real usage ledger and the Supabase-role RLS harness of
tests/phase2/rls.sql. Nothing here calls a provider: presentation source is written as a producer would write it, so every
assertion is about storage, authorization, concurrency and recovery (gates G09 G10 G11 G18, C08).

Run: PYTHONPATH=src:tests python scripts/postriff_pg_suite.py postgres_agent_ui_store   (cloud CI: scripts/agent_ui_validation.sh database)
"""
import hashlib
import json
import os
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.agent_runtime_v2 import config, ui_contracts as contracts, ui_store as store  # noqa: E402
from postriff_phase2.agent_runtime_v2.ui_http import UiAuth, ui_transaction  # noqa: E402
from consumer_fixtures import approve_budgets  # noqa: E402

PORT = os.environ.get("POSTRIFF_PG_PORT", "55438")
DSN = f"host=127.0.0.1 port={PORT} dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"     # owner of the main workspace
THREE = "00000000-0000-0000-0000-000000000003"   # viewer of the main workspace
FOUR = "00000000-0000-0000-0000-000000000004"    # owner of another tenant
FIVE = "00000000-0000-0000-0000-000000000005"    # editor of the main workspace
TOKENS = {"one-token-000000000000000000": ONE, "three-token-00000000000000000": THREE, "four-token-000000000000000000": FOUR,
          "five-token-000000000000000000": FIVE}
OWNER, VIEWER, OTHER, EDITOR = list(TOKENS)
LIB = "b" * 64
OLD_LIB = "f" * 64
EVIDENCE = []
os.environ["RAFII_GENUI_COMPATIBLE_LIBRARIES"] = LIB    # the deployed renderer's library (no generated assets in this checkout)


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required.", 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: f"session-{principal}-0123456789abcdef"
verify.auth_time = lambda token, principal: time.time()


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scenario(sid, title):
    def wrap(fn):
        started = time.monotonic()
        record = {"id": sid, "title": title}
        try:
            detail = fn() or {}
            record.update({"result": "PASS", **detail})
        except Exception as error:  # noqa: BLE001
            record.update({"result": "FAIL", "error": f"{type(error).__name__}: {error}", "trace": traceback.format_exc()[-1800:]})
        record["ms"] = round((time.monotonic() - started) * 1000)
        EVIDENCE.append(record)
        print(f"{record['result']:5} {sid} {title}" + (f" — {record.get('error')}" if record["result"] == "FAIL" else ""), flush=True)
        return fn
    return wrap


def one(sql, *params):
    with connection() as db:
        return db.execute(sql, params).fetchone()


def run_sql(sql, *params):
    with connection() as db:
        db.execute(sql, params)


def denied(call, status=None, code=None):
    try:
        call()
    except AlphaError as error:
        assert status is None or error.status == status, (error.status, error.code, str(error))
        assert code is None or error.code == code, (error.status, error.code, str(error))
        return error
    raise AssertionError("call was accepted")


# --- environment -----------------------------------------------------------------------------------------------------------
with connection() as db:
    db.execute((ROOT / "migrations/postriff/102_agent_ui_artifacts.sql").read_text())
    db.execute("INSERT INTO auth.users VALUES(%s),(%s),(%s) ON CONFLICT DO NOTHING", (THREE, FOUR, FIVE))
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s ORDER BY workspace_id LIMIT 1", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET status='active', role='owner' WHERE user_id=%s AND workspace_id=%s", (ONE, wid))

service = HostedWorkspaceService(connection, verify, clock=time.time)
service.bootstrap(OWNER, "studio")
other = service.bootstrap(OTHER, "studio")["workspaceId"]
service.bootstrap(VIEWER, "studio")
service.bootstrap(EDITOR, "studio")
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active') ON CONFLICT DO NOTHING", (wid, THREE))
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active') ON CONFLICT DO NOTHING", (wid, FIVE))
    db.execute("UPDATE public.pr_workspaces SET state = coalesce(state,'{}'::jsonb) || %s::jsonb WHERE id=%s",
               (json.dumps({"variants": [{"id": "d1"}, {"id": "d2"}, {"id": "d3"}]}), wid))
approve_budgets(connection, wid)
approve_budgets(connection, other)

CFG = config.RuntimeConfig.from_environment({"RAFII_AGENT_V2_ENABLED": "1", "RAFII_GENUI_ENABLED": "1", "RAFII_GENUI_ACTIONS_ENABLED": "1",
                                             "RAFII_GENUI_EDITS_ENABLED": "1", "RAFII_GENUI_FOUNDER_ENABLED": "1"})


class Runtime:
    def __init__(self, svc, cfg, founder=None):
        self.service, self.cfg = svc, cfg
        if founder:
            self.founder = founder


RUNTIME = Runtime(service, CFG)
FOUNDER_KEY = "founder:live:production"
FOUNDER_RUNTIME = Runtime(service, CFG, founder={"namespace": FOUNDER_KEY})


def fixture_run(workspace, actor, *, key=None, status="completed", eligible=True, title="UI test"):
    """A completed agent turn as service._persist leaves it: conversation, run (result.ui) and its assistant message."""
    with connection() as db:
        conversation = db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text",
                                  (workspace, actor, title)).fetchone()[0]
        result = {"answerText": "Native answer text.", "composedBy": "manager", "ui": {"eligible": eligible, "slot": "main", "reason": "table", "journeyIds": ["J06"]}}
        run = db.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) "
                         "VALUES(%s,%s,%s,%s,'rafii-agent','standard',%s,%s,%s,%s::jsonb) RETURNING id::text",
                         (conversation, workspace, actor, status, "0" * 64, "0" * 64, key or f"agent:{uuid.uuid4().hex}", json.dumps({"version": 1, "result": result}))).fetchone()[0]
        db.execute("INSERT INTO public.pr_messages(conversation_id,workspace_id,seq,role,body,run_id) VALUES(%s,%s,1,'user',%s::jsonb,NULL)",
                   (conversation, workspace, json.dumps({"text": "Compare my posts"})))
        message = db.execute("INSERT INTO public.pr_messages(conversation_id,workspace_id,seq,role,body,run_id) VALUES(%s,%s,2,'assistant',%s::jsonb,%s) RETURNING id::text",
                             (conversation, workspace, json.dumps({"text": "Native answer text.", "runId": run, "siteAgent": {"blocks": []},
                                                                  "agent": {"answerText": "Native answer text."}}), run)).fetchone()[0]
    return {"conversation": conversation, "run": run, "message": message}


MANIFEST = {"manifestId": "m-test", "bindingVersion": 1, "journeyIds": ["J06"], "library": "consumer",
            "queries": [{"name": "metrics_summary", "description": "Metrics", "argsSchema": {}, "refreshMinSeconds": 30, "pageSize": 50}],
            "actions": [{"actionId": "draft_save", "label": "Save draft", "effect": "CREATE_DRAFT", "requiresConfirmation": True, "inputSchema": {}, "summary": None}],
            "approvedRefs": [{"type": "draft", "id": "d3"}], "principal": ONE, "egress": {"allowed": True}}
PROJECTION = {"journey_ids": ["J06"], "fallback_text": "Native answer text.", "manifest_id": "m-test"}
SOURCE = 'root = RafiiRoot([table])\ntable = ToolBoundTable(Query("metrics_summary", {"period": $period}, null))\n$period = "30d"'
SOURCE2 = SOURCE + '\nchart = ToolBoundChart(Query("metrics_summary", {"period": $period}, null))'


def key():
    return "k" + uuid.uuid4().hex[:30]


def validation(source, **overrides):
    out = {"accepted": True, "canonicalSource": source, "sourceHash": sha(source), "statementCount": 3, "queryNames": ["metrics_summary"], "actionIds": [],
           "componentNames": ["RafiiRoot", "ToolBoundTable"], "errors": [], "libraryHash": LIB, "libraryVersion": "0.3.2", "stateNames": ["$period"],
           "formNames": ["filters"]}
    out.update(overrides)
    return out


def claim(token, run, idempotency_key, *, kind="generate", retry_of=None, base=None, owner="pid:test", runtime=RUNTIME, surface="chat"):
    with ui_transaction(runtime, token, wid, "edit") as (cur, auth):
        return store.create_or_resume_artifact(cur, auth, run, "main", idempotency_key, surface=surface, manifest=MANIFEST, projection=PROJECTION,
                                               kind=kind, retry_of=retry_of, lease_owner=owner, base=base)


def commit(token, artifact_id, attempt_key, base_revision, base_hash, source, runtime=RUNTIME, **validation_overrides):
    with ui_transaction(runtime, token, wid, "edit") as (cur, auth):
        return store.commit_ui_revision(cur, auth, {"artifactId": artifact_id, "baseRevision": base_revision, "baseSourceHash": base_hash, "patchSource": source,
                                                    "idempotencyKey": attempt_key, "promptHash": "c" * 64}, validation(source, **validation_overrides))


def counts():
    return {"attempts": one("SELECT count(*) FROM public.pr_ui_attempts")[0], "reserves": one("SELECT count(*) FROM public.pr_usage_ledger WHERE kind='reserve'")[0],
            "revisions": one("SELECT count(*) FROM public.pr_ui_revisions")[0]}


MAIN = fixture_run(wid, ONE)
STATE = {}


@scenario("F-S01", "create once; same key resumes the same attempt; message records the artifact; lease has the D-A33 shape")
def _create():
    first_key = key()
    lease = claim(OWNER, MAIN["run"], first_key)
    assert lease["created"] is True and lease["producer"] is True, lease
    assert set(lease) >= {"artifact", "attempt", "created", "replay_cursor"} and isinstance(lease["replay_cursor"], int)
    artifact, attempt = lease["artifact"], lease["attempt"]
    for field in ("artifactId", "runId", "conversationId", "messageId", "revision", "sourceHash", "canonicalSource", "generationState", "validationState",
                  "manifestId", "bindingVersion"):
        assert field in artifact, field
    for field in ("attemptId", "kind", "targetRevision", "baseRevision", "baseSourceHash", "state", "leaseOwner", "idempotencyKey", "reservationId", "retryOf"):
        assert field in attempt, field
    assert artifact["runId"] == MAIN["run"] and artifact["messageId"] == MAIN["message"] and artifact["generationState"] == "queued"
    assert attempt["state"] == "queued" and attempt["targetRevision"] == 1 and attempt["kind"] == "generate"
    again = claim(OWNER, MAIN["run"], first_key)
    assert again["created"] is False and again["attempt"]["attemptId"] == attempt["attemptId"], again
    body = one("SELECT body FROM public.pr_messages WHERE id::text=%s", MAIN["message"])[0]
    assert body["agent"]["uiArtifacts"] == [{"artifactId": artifact["artifactId"], "slot": "main"}], body["agent"]
    assert body["text"] == "Native answer text." and body["siteAgent"] == {"blocks": []}      # native answer untouched
    STATE.update(artifact=artifact["artifactId"], attempt=attempt["attemptId"], key=first_key)
    # The same key for a different request is a conflict, never a second attempt.
    denied(lambda: claim(OWNER, MAIN["run"], first_key, kind="retry", retry_of=attempt["attemptId"]), 409, "ui_idempotency_conflict")
    return {"artifactId": artifact["artifactId"]}


@scenario("F-S02", "two producers/tabs racing on one run: exactly one live producer; the other attaches")
def _two_producers():
    race = fixture_run(wid, ONE, title="race")
    barrier = threading.Barrier(2)
    results, errors = [], []

    def tab(token):
        try:
            barrier.wait(5)
            results.append(claim(token, race["run"], key(), owner=f"pid:{token[:4]}"))
        except Exception as error:  # noqa: BLE001
            errors.append(error)
    threads = [threading.Thread(target=tab, args=(OWNER,)), threading.Thread(target=tab, args=(EDITOR,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not errors, errors
    assert sorted(r["created"] for r in results) == [False, True], [r["created"] for r in results]
    assert len({r["attempt"]["attemptId"] for r in results}) == 1, results
    live = one("SELECT count(*) FROM public.pr_ui_attempts t JOIN public.pr_ui_artifacts a ON a.id=t.artifact_id WHERE a.parent_run_id::text=%s "
               "AND t.state IN ('queued','streaming','validating')", race["run"])[0]
    assert live == 1, live
    # The partial unique index itself refuses a second live producer for the same target revision (across processes).
    artifact = results[0]["artifact"]["artifactId"]
    try:
        run_sql("INSERT INTO public.pr_ui_attempts(artifact_id,workspace_id,kind,target_revision,idempotency_key,lease_owner,lease_expires_at) "
                "VALUES(%s,%s,'generate',1,%s,'pid:rogue',now()+interval '1 minute')", artifact, wid, key())
        raise AssertionError("second live producer inserted")
    except psycopg.errors.UniqueViolation:
        pass
    return {"liveProducers": live}


@scenario("F-S03", "eligibility and authority: not eligible, running, viewer, foreign tenant, founder run via consumer routes")
def _eligibility():
    denied(lambda: claim(OWNER, fixture_run(wid, ONE, eligible=False)["run"], key()), 409, "not_eligible")
    denied(lambda: claim(OWNER, fixture_run(wid, ONE, status="running")["run"], key()), 409, "not_eligible")
    denied(lambda: claim(VIEWER, MAIN["run"], key()), 403)
    foreign = fixture_run(other, FOUR)
    denied(lambda: claim(OWNER, foreign["run"], key()), 404, "ui_parent_run")          # another tenant's run id in my workspace path
    denied(lambda: claim(OTHER, MAIN["run"], key()), 403)                               # not a member of this workspace
    founder_run = fixture_run(wid, ONE, key=f"agent:{FOUNDER_KEY}:{uuid.uuid4().hex}")
    STATE["founder_run"] = founder_run
    denied(lambda: claim(OWNER, founder_run["run"], key()), 404, "ui_parent_run")       # founder data never through consumer routes
    return {}


def _events_in(token, workspace, artifact):
    with ui_transaction(RUNTIME, token, workspace, "read") as (cur, auth):
        return store.events_after(cur, auth, artifact, 0, 10)


@scenario("F-S04", "private events: monotonic seq, bounded replay after a cursor, heartbeats never persisted, scope-checked reads")
def _events():
    artifact, attempt = STATE["artifact"], STATE["attempt"]
    with connection() as db:
        started = store.append_event(db, artifact, attempt, 0, "ui.started", {"libraryVersion": "0.3.2", "manifestId": "m-test"})
        deltas = [store.append_event(db, artifact, attempt, 0, "ui.delta", {"text": part, "offset": i}) for i, part in enumerate(["root = Rafii", "Root([table])\n"])]
    seqs = [started["seq"]] + [d["seq"] for d in deltas]
    assert seqs == sorted(seqs) and len(set(seqs)) == 3 and seqs[0] >= 1, seqs
    assert started["contractVersion"] == contracts.CONTRACT_VERSION and started["artifactId"] == artifact and started["kind"] == "ui.started"
    try:
        with connection() as db:
            store.append_event(db, artifact, attempt, 0, "ui.heartbeat", {})
        raise AssertionError("heartbeat persisted")
    except ValueError:
        pass
    with ui_transaction(RUNTIME, VIEWER, wid, "read") as (cur, auth):
        after = store.events_after(cur, auth, artifact, seqs[0], 500)
    assert [e["seq"] for e in after] == seqs[1:], after
    assert [e["payload"]["text"] for e in after] == ["root = Rafii", "Root([table])\n"]          # fragments kept byte-exact
    denied(lambda: _events_in(OTHER, other, artifact), 404)                                         # another tenant, own workspace path
    STATE["deltas"] = seqs
    return {"seqs": seqs}


@scenario("F-S05", "checkpoint: queued→streaming, lease renewed, other owner refused with ui_lease_lost")
def _checkpoint():
    attempt = STATE["attempt"]
    before = one("SELECT lease_expires_at FROM public.pr_ui_attempts WHERE id::text=%s", attempt)[0]
    with connection() as db:
        store.checkpoint(db, attempt, "root = RafiiRoot([table])\n", lease_owner="pid:test")
    state, after, size = one("SELECT state, lease_expires_at, checkpoint_bytes FROM public.pr_ui_attempts WHERE id::text=%s", attempt)
    assert state == "streaming" and after >= before and size == len("root = RafiiRoot([table])\n"), (state, before, after, size)
    # The artifact row is not touched by checkpoints (no artifact-row contention per chunk); a reader sees the attempt's state.
    snap = store.snapshot_http(RUNTIME, wid, OWNER, STATE["artifact"])
    assert snap["artifact"]["generationState"] == "streaming" and snap["display"]["mode"] == "pending" and snap["attempt"]["live"], snap
    with connection() as db:
        denied(lambda: store.checkpoint(db, attempt, "x", lease_owner="pid:someone-else"), 409, "ui_lease_lost")
        assert store.attempt_state(db, attempt) == "streaming"
    return {}


@scenario("F-S06", "commit: forged validation and query expansion refused; CAS commit makes an immutable ready revision")
def _commit():
    artifact, attempt_key = STATE["artifact"], STATE["key"]
    before = counts()
    denied(lambda: commit(OWNER, artifact, attempt_key, 0, None, SOURCE, sourceHash="0" * 64), 422)                  # hash for another source
    denied(lambda: commit(OWNER, artifact, attempt_key, 0, None, SOURCE, queryNames=["metrics_summary", "drafts_delete"]), 422)   # outside manifest
    denied(lambda: commit(OWNER, artifact, attempt_key, 0, None, SOURCE, actionIds=["account_disconnect"]), 422)
    denied(lambda: commit(OWNER, artifact, attempt_key, 0, None, SOURCE, accepted=False), 422)
    denied(lambda: commit(OWNER, artifact, attempt_key, 3, "a" * 64, SOURCE), 409, "ui_revision_conflict")        # stale/forged base
    assert counts() == before
    ready = commit(OWNER, artifact, attempt_key, 0, None, SOURCE)
    assert ready["revision"] == 1 and ready["generationState"] == "ready" and ready["validationState"] == "accepted", ready
    assert ready["canonicalSource"] == SOURCE and ready["sourceHash"] == sha(SOURCE) and ready["libraryHash"] == LIB
    assert one("SELECT state FROM public.pr_ui_attempts WHERE id::text=%s", STATE["attempt"])[0] == "ready"
    assert one("SELECT count(*) FROM public.pr_ui_events WHERE artifact_id::text=%s AND kind='ui.delta'", artifact)[0] == 0   # compacted
    with connection() as db:
        store.append_event(db, artifact, STATE["attempt"], 1, "ui.ready", {"sourceHash": sha(SOURCE)})
        finished = store.finish_attempt(db.cursor(), STATE["attempt"], "ready")                                     # B's later call: no-op
    assert finished["state"] == "ready"
    STATE["rev1"] = ready
    return {"revision": 1}


@scenario("F-S07", "passive reopen: snapshot, by-message, replay and a duplicate create make zero attempts and zero spend")
def _passive():
    before = counts()
    snap = store.snapshot_http(RUNTIME, wid, VIEWER, STATE["artifact"])
    assert snap["artifact"]["canonicalSource"] == SOURCE and snap["display"]["mode"] == "generated", snap["display"]
    assert snap["access"]["canAct"] is False and snap["manifest"]["actions"] == [] and snap["access"]["role"] == "viewer"   # viewer: no write controls
    owner_snap = store.snapshot_http(RUNTIME, wid, OWNER, STATE["artifact"])
    assert owner_snap["access"]["canAct"] is True and [a["actionId"] for a in owner_snap["manifest"]["actions"]] == ["draft_save"]
    for forbidden in ("principal", "egress", "approvedRefs"):
        assert forbidden not in owner_snap["manifest"], forbidden                                                  # server-only manifest keys
    listed = store.by_message_http(RUNTIME, wid, OWNER, MAIN["message"])
    assert [a["artifact"]["artifactId"] for a in listed["artifacts"]] == [STATE["artifact"]]
    with ui_transaction(RUNTIME, OWNER, wid, "read") as (cur, auth):
        replay = store.replay_view(cur, auth, STATE["artifact"], 0)
    assert replay["done"] is True and replay["events"][-1]["kind"] == "ui.ready"
    again = claim(OWNER, MAIN["run"], key())                         # a remount with a new key still attaches
    assert again["created"] is False and again["artifact"]["revision"] == 1
    assert counts() == before, (before, counts())
    return {"providerAttemptsDelta": 0, "reservesDelta": 0}


@scenario("F-S08", "incremental edit: stale base refused before spend; edit commits revision 2; revision 1 stays immutable and recoverable")
def _edit():
    rev1 = STATE["rev1"]
    before = counts()
    denied(lambda: claim(OWNER, MAIN["run"], key(), kind="edit", base={"revision": 1, "sourceHash": "a" * 64, "instruction": "Add a chart"}), 409, "ui_revision_conflict")
    assert counts() == before                                         # nothing claimed, nothing reserved
    edit_key = key()
    lease = claim(OWNER, MAIN["run"], edit_key, kind="edit", base={"revision": 1, "sourceHash": rev1["sourceHash"], "instruction": "Add a chart"})
    assert lease["created"] and lease["attempt"]["targetRevision"] == 2 and lease["attempt"]["baseRevision"] == 1
    assert lease["artifact"]["canonicalSource"] == SOURCE              # the edit's base source for the presenter
    denied(lambda: claim(OWNER, MAIN["run"], key(), kind="edit", base={"revision": 1, "sourceHash": rev1["sourceHash"], "instruction": "Other"}), 409, "ui_attempt_live")
    snap = store.snapshot_http(RUNTIME, wid, OWNER, STATE["artifact"])
    assert snap["artifact"]["revision"] == 1 and snap["display"] == {"mode": "generated", "reason": None, "updating": True, "revokedRefs": 0}
    ready = commit(OWNER, STATE["artifact"], edit_key, 1, rev1["sourceHash"], SOURCE2)
    assert ready["revision"] == 2 and ready["canonicalSource"] == SOURCE2
    assert one("SELECT source FROM public.pr_ui_revisions WHERE artifact_id::text=%s AND revision=1", STATE["artifact"])[0] == SOURCE
    assert one("SELECT kind, base_revision FROM public.pr_ui_revisions WHERE artifact_id::text=%s AND revision=2", STATE["artifact"]) == ("edit", 1)
    listed = store.snapshot_http(RUNTIME, wid, OWNER, STATE["artifact"])["revisions"]
    assert [r["revision"] for r in listed] == [2, 1], listed
    # A failed edit leaves the last ready revision as the view.
    third = claim(OWNER, MAIN["run"], key(), kind="edit", base={"revision": 2, "sourceHash": sha(SOURCE2), "instruction": "Change the period"})
    denied(lambda: commit(OWNER, STATE["artifact"], third["attempt"]["idempotencyKey"], 1, rev1["sourceHash"], SOURCE), 409, "ui_revision_conflict")
    with connection() as db:
        store.finish_attempt(db.cursor(), third["attempt"]["attemptId"], "failed", "parse_rejected")
    after = store.snapshot_http(RUNTIME, wid, OWNER, STATE["artifact"])
    assert after["artifact"]["revision"] == 2 and after["artifact"]["generationState"] == "ready" and after["artifact"]["canonicalSource"] == SOURCE2
    assert after["attempt"]["state"] == "failed" and after["attempt"]["reason"] == "parse_rejected"
    STATE["rev2"] = ready
    return {"revisions": [2, 1]}


@scenario("F-S09", "single automatic repair after a parse rejection; a second repair is refused")
def _repair():
    run = fixture_run(wid, ONE, title="repair")
    first_key = key()
    initial = claim(OWNER, run["run"], first_key)
    with connection() as db:
        store.finish_attempt(db.cursor(), initial["attempt"]["attemptId"], "failed", "parse_rejected")
    failed = store.snapshot_http(RUNTIME, wid, OWNER, initial["artifact"]["artifactId"])
    assert failed["display"] == {"mode": "fallback", "reason": "parse_rejected", "updating": False} and failed["artifact"]["validationState"] == "rejected"
    repair_key = "r1_" + sha(first_key)[:40]
    repair = claim(OWNER, run["run"], repair_key, kind="repair", retry_of=initial["attempt"]["attemptId"])
    assert repair["created"] and repair["attempt"]["kind"] == "repair" and repair["attempt"]["targetRevision"] == 1
    assert repair["artifact"]["generationState"] == "queued"
    denied(lambda: claim(OWNER, run["run"], key(), kind="repair", retry_of=initial["attempt"]["attemptId"]), 409)
    ready = commit(OWNER, initial["artifact"]["artifactId"], repair_key, 0, None, SOURCE)
    assert ready["revision"] == 1
    assert one("SELECT kind FROM public.pr_ui_revisions WHERE artifact_id::text=%s AND revision=1", initial["artifact"]["artifactId"])[0] == "repair"
    return {}


@scenario("F-S10", "explicit UI-only retry: only after a stop, only of the latest attempt, new key")
def _retry():
    run = fixture_run(wid, ONE, title="retry")
    initial = claim(OWNER, run["run"], key())
    attached = claim(OWNER, run["run"], key(), kind="retry", retry_of=initial["attempt"]["attemptId"])          # still live: attach, no second producer
    assert attached["created"] is False and attached["attempt"]["attemptId"] == initial["attempt"]["attemptId"]
    with connection() as db:
        store.finish_attempt(db.cursor(), initial["attempt"]["attemptId"], "failed", "provider_timeout")
    passive = claim(OWNER, run["run"], key())                                                                      # passive duplicate create
    assert passive["created"] is False and passive["attempt"]["state"] == "failed"
    retry_key = key()
    retry = claim(OWNER, run["run"], retry_key, kind="retry", retry_of=initial["attempt"]["attemptId"])
    assert retry["created"] and retry["attempt"]["retryOf"] == initial["attempt"]["attemptId"] and retry["attempt"]["targetRevision"] == 1
    with connection() as db:
        store.finish_attempt(db.cursor(), retry["attempt"]["attemptId"], "failed", "provider_error")
    denied(lambda: claim(OWNER, run["run"], key(), kind="retry", retry_of=initial["attempt"]["attemptId"]), 409, "ui_retry")   # not the latest
    return {}


@scenario("F-S11", "UI state CAS: stale writes conflict with the current state, merges keep both tabs' edits; undeclared/viewer/oversize refused")
def _state():
    artifact = STATE["artifact"]

    def save(token, expected, patch):
        with ui_transaction(RUNTIME, token, wid, "edit") as (cur, auth):
            return store.persist_ui_state(cur, auth, artifact, expected, patch)
    a = save(OWNER, 0, {"$period": "7d"})
    assert a["stateRevision"] == 1 and a["safeState"] == {"$period": "7d"}
    conflict = denied(lambda: save(EDITOR, 0, {"filters": {"platform": {"value": "Instagram", "componentType": "Select"}}}), 409, "ui_state_conflict")
    assert conflict.current["stateRevision"] == 1 and conflict.current["safeState"] == {"$period": "7d"}
    merged = save(EDITOR, conflict.current["stateRevision"], {"filters": {"platform": {"value": "Instagram", "componentType": "Select"}}})
    assert merged["stateRevision"] == 2 and merged["safeState"]["$period"] == "7d" and merged["safeState"]["filters"]["platform"]["value"] == "Instagram"
    denied(lambda: save(OWNER, 2, {"$undeclared": 1}), 400, "ui_state_field")
    denied(lambda: save(OWNER, 2, {"$password": "hunter2"}), 400)
    denied(lambda: save(OWNER, 2, {"$period": "x" * 1500, "filters": {f"f{i}": {"value": "y" * 1500} for i in range(12)}}), 413)
    denied(lambda: save(VIEWER, 2, {"$period": "1d"}), 403)
    stored = one("SELECT safe_state, state_revision, revision, source_hash FROM public.pr_ui_artifacts WHERE id::text=%s", artifact)
    assert stored[1] == 2 and stored[2] == 2 and stored[3] == sha(SOURCE2)            # typing never touches the accepted source
    STATE["stateRevision"] = 2
    return {"stateRevision": 2}


@scenario("F-S12", "selection memory: stored order at the time of selection, kind for the Manager, ids only in the note, revoked items dropped")
def _selection():
    artifact = STATE["artifact"]

    def save(expected, patch):
        with ui_transaction(RUNTIME, OWNER, wid, "edit") as (cur, auth):
            return store.persist_ui_state(cur, auth, artifact, expected, patch)
    first = save(STATE["stateRevision"], {store.SELECTION_KEY: {"items": [{"type": "draft", "id": "d2", "title": "Spring launch"}, {"type": "draft", "id": "d1", "title": "Teaser"}],
                                                                 "visible": [{"type": "draft", "id": "d1"}, {"type": "draft", "id": "d2"}, {"type": "draft", "id": "d3"}]}})
    later = save(first["stateRevision"], {store.SELECTION_KEY: {"items": [{"type": "draft", "id": "d3"}], "visible": [{"type": "draft", "id": "d3"}]}})
    with ui_transaction(RUNTIME, OWNER, wid, "read") as (cur, auth):
        then = store.selection_context(cur, auth, {"artifactId": artifact, "artifactRevision": 2, "stateRevision": first["stateRevision"]})
        now = store.selection_context(cur, auth, {"artifactId": artifact, "artifactRevision": 2, "stateRevision": later["stateRevision"]})
    assert [(r["id"], r["kind"]) for r in then["references"]] == [("d2", "post"), ("d1", "post")], then
    assert "1. draft d2; 2. draft d1" in then["note"] and "Spring launch" not in then["note"] and "The list as shown then: 1. draft d1; 2. draft d2; 3. draft d3" in then["note"]
    assert [r["id"] for r in now["references"]] == ["d3"]
    # A draft deleted since the selection is dropped from the follow-up context (revoked source re-checked).
    run_sql("UPDATE public.pr_workspaces SET state = jsonb_set(state, '{variants}', %s::jsonb) WHERE id=%s", json.dumps([{"id": "d1"}, {"id": "d3"}]), wid)
    with ui_transaction(RUNTIME, OWNER, wid, "read") as (cur, auth):
        pruned = store.selection_context(cur, auth, {"artifactId": artifact, "artifactRevision": 2, "stateRevision": first["stateRevision"]})
    assert [r["id"] for r in pruned["references"]] == ["d1"] and "no longer available" in pruned["note"], pruned
    # Another tenant's (or a foreign) view yields no selection at all, never an error that fails the turn.
    with ui_transaction(RUNTIME, OTHER, other, "read") as (cur, auth):
        assert store.selection_context(cur, auth, {"artifactId": artifact, "artifactRevision": 2, "stateRevision": 0}) is None
    STATE["stateRevision"] = later["stateRevision"]
    return {"ordered": [r["id"] for r in then["references"]]}


@scenario("F-S13", "revoked on reopen: deleted approved source flagged, removed member refused, deleted answer and conversation revoke the view")
def _revoked():
    artifact = STATE["artifact"]
    snap = store.snapshot_http(RUNTIME, wid, OWNER, artifact)
    assert snap["access"]["revokedRefs"] == [], snap["access"]
    run_sql("UPDATE public.pr_workspaces SET state = jsonb_set(state, '{variants}', %s::jsonb) WHERE id=%s", json.dumps([{"id": "d1"}]), wid)
    snap = store.snapshot_http(RUNTIME, wid, OWNER, artifact)
    assert snap["access"]["revokedRefs"] == ["draft:d3"], snap["access"]
    run_sql("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", wid, FIVE)
    denied(lambda: store.snapshot_http(RUNTIME, wid, EDITOR, artifact), 403)
    run_sql("UPDATE public.pr_memberships SET status='active' WHERE workspace_id=%s AND user_id=%s", wid, FIVE)
    scratch = fixture_run(wid, ONE, title="scratch")
    lease = claim(OWNER, scratch["run"], key())
    run_sql("DELETE FROM public.pr_messages WHERE id::text=%s", scratch["message"])
    denied(lambda: store.snapshot_http(RUNTIME, wid, OWNER, lease["artifact"]["artifactId"]), 404, "ui_artifact_revoked")
    run_sql("DELETE FROM public.pr_conversations WHERE id::text=%s", scratch["conversation"])
    denied(lambda: store.snapshot_http(RUNTIME, wid, OWNER, lease["artifact"]["artifactId"]), 404)
    assert one("SELECT count(*) FROM public.pr_ui_artifacts WHERE id::text=%s", lease["artifact"]["artifactId"])[0] == 0      # cascaded, no orphan
    return {}


@scenario("F-S14", "old library version: native fallback without a model call (canonical source withheld)")
def _old_library():
    run = fixture_run(wid, ONE, title="old library")
    lease = claim(OWNER, run["run"], key())
    commit(OWNER, lease["artifact"]["artifactId"], lease["attempt"]["idempotencyKey"], 0, None, SOURCE, libraryHash=OLD_LIB)
    before = counts()
    snap = store.snapshot_http(RUNTIME, wid, OWNER, lease["artifact"]["artifactId"])
    assert snap["display"]["mode"] == "fallback" and snap["display"]["reason"] == "library_unsupported", snap["display"]
    assert snap["artifact"]["canonicalSource"] is None and snap["compatibility"]["supported"] is False
    # NC18: no write control, read, edit or saved state is offered on a view this build cannot draw; the flag says fallback.
    assert snap["manifest"]["actions"] == [] and snap["fallback"] is True and snap["access"]["fallback"] is True, (snap["manifest"], snap["access"])
    assert not any(snap["access"][k] for k in ("canAct", "canEdit", "canQuery", "canPersistState")), snap["access"]
    listed = store.by_message_http(RUNTIME, wid, OWNER, run["message"])["artifacts"][0]
    assert listed["manifest"]["actions"] == [] and listed["fallback"] is True
    denied(lambda: store.persist_state_http(RUNTIME, wid, OWNER, lease["artifact"]["artifactId"], {"expectedStateRevision": 0, "patch": {"$period": "7d"}}),
           409, "library_unsupported")
    current = store.snapshot_http(RUNTIME, wid, OWNER, STATE["artifact"])
    assert current["fallback"] is False and [a["actionId"] for a in current["manifest"]["actions"]] == ["draft_save"]
    assert counts() == before
    return {"providerAttemptsDelta": 0}


@scenario("F-S15", "disconnect after checkpoint: replay resumes from durable events; expired lease is reaped as interrupted with usage held unknown")
def _disconnect():
    run = fixture_run(wid, ONE, title="disconnect")
    attempt_key = key()
    lease = claim(OWNER, run["run"], attempt_key, owner="pid:dead")
    artifact, attempt = lease["artifact"]["artifactId"], lease["attempt"]["attemptId"]
    with connection() as db:
        store.append_event(db, artifact, attempt, 0, "ui.started", {})
        store.append_event(db, artifact, attempt, 0, "ui.delta", {"text": "root = Rafii", "offset": 0})
        store.checkpoint(db, attempt, "root = Rafii", lease_owner="pid:dead")
        store.append_event(db, artifact, attempt, 0, "ui.checkpoint", {"bytes": 12, "hash": sha("root = Rafii")})
    # The client reconnects (GET events?after=): the durable events are all there; the producer is still live.
    with ui_transaction(RUNTIME, OWNER, wid, "read") as (cur, auth):
        replay = store.replay_view(cur, auth, artifact, 0)
    assert [e["kind"] for e in replay["events"]] == ["ui.started", "ui.delta", "ui.checkpoint"] and replay["done"] is False and replay["attempt"]["live"]
    with ui_transaction(RUNTIME, OWNER, wid, "edit") as (cur, auth):
        reservation = service.ledger.reserve(cur, wid, ONE, "text_model", 2500, f"agent:{run['run']}:ui:{attempt}", charge_batch=False, run_id=run["run"])
    reservation_id = reservation["reservationId"]
    run_sql("UPDATE public.pr_ui_attempts SET lease_expires_at = now() - interval '1 second' WHERE id::text=%s", attempt)
    with connection() as db, db.cursor() as cur:
        reaped = store.reap_expired(cur, wid, time.time())
    assert reaped == 1, reaped
    state, reason = one("SELECT state, reason FROM public.pr_ui_attempts WHERE id::text=%s", attempt)
    assert (state, reason) == ("interrupted", "lease_expired")
    unknown = one("SELECT count(*), bool_and(actual_usd_micro IS NULL) FROM public.pr_usage_ledger WHERE reservation_id::text=%s AND cost_state='estimated_unknown'",
                  str(reservation_id))
    assert unknown == (1, True), unknown                                                        # held as unknown, never zero
    assert one("SELECT count(*) FROM public.pr_usage_ledger WHERE reservation_id::text=%s AND cost_state IN ('actual','released')", str(reservation_id))[0] == 0
    with ui_transaction(RUNTIME, OWNER, wid, "read") as (cur, auth):
        events = store.events_after(cur, auth, artifact, 0, 50)
    assert events[-1]["kind"] == "ui.interrupted" and events[-1]["payload"]["reason"] == "lease_expired"
    snap = store.snapshot_http(RUNTIME, wid, OWNER, artifact)
    assert snap["display"] == {"mode": "fallback", "reason": "lease_expired", "updating": False}, snap["display"]
    before = counts()
    resumed = claim(OWNER, run["run"], attempt_key, owner="pid:new")                             # same key after the crash: no new producer
    assert resumed["created"] is False and resumed["attempt"]["state"] == "interrupted"
    with connection() as db, db.cursor() as cur:
        assert store.reap_expired(cur, wid, time.time()) == 0
    assert counts() == before
    with connection() as db:
        denied(lambda: store.checkpoint(db, attempt, "late", lease_owner="pid:dead"), 409, "ui_attempt_closed")
    return {"reaped": reaped}


def _replay(runtime, artifact_id):
    with ui_transaction(runtime, OWNER, wid, "read") as (cur, auth):
        return store.replay_view(cur, auth, artifact_id, 0)


@scenario("F-S16", "founder scope: founder views exist only on founder routes; consumer views are 404 there")
def _founder():
    founder_run = STATE["founder_run"]
    lease = claim(OWNER, founder_run["run"], key(), runtime=FOUNDER_RUNTIME, surface="founder")
    founder_artifact = lease["artifact"]["artifactId"]
    assert lease["created"] and lease["artifact"]["scope"] == "founder"
    denied(lambda: store.snapshot_http(RUNTIME, wid, OWNER, founder_artifact), 404)
    denied(lambda: store.by_message_http(RUNTIME, wid, OWNER, founder_run["message"]), 404)
    denied(lambda: store.snapshot_http(FOUNDER_RUNTIME, wid, OWNER, STATE["artifact"]), 404)
    denied(lambda: claim(OWNER, founder_run["run"], key(), runtime=Runtime(service, CFG, founder={"namespace": "founder:demo:production"}), surface="founder"), 404)
    with ui_transaction(FOUNDER_RUNTIME, OWNER, wid, "read") as (cur, auth):
        assert auth.scope == "founder" and auth.scope_key == FOUNDER_KEY
    # Every F-owned route works on the founder artifact through the founder runtime (scope from runtime.founder), and each one is
    # the same 404 through the consumer runtime; the founder runtime gets 404 on the consumer artifact.
    founder_key = lease["attempt"]["idempotencyKey"]
    denied(lambda: commit(OWNER, founder_artifact, founder_key, 0, None, SOURCE), 404)                                    # consumer scope
    denied(lambda: commit(OWNER, founder_artifact, founder_key, 0, None, SOURCE, runtime=FOUNDER_RUNTIME, actionIds=["draft_save"]), 422)   # read-only
    ready = commit(OWNER, founder_artifact, founder_key, 0, None, SOURCE, runtime=FOUNDER_RUNTIME)
    assert ready["revision"] == 1
    snap = store.snapshot_http(FOUNDER_RUNTIME, wid, OWNER, founder_artifact)
    assert snap["scope"] == "founder" and snap["access"]["canAct"] is False and snap["manifest"]["actions"] == []
    listed = store.by_message_http(FOUNDER_RUNTIME, wid, OWNER, founder_run["message"])
    assert [a["artifact"]["artifactId"] for a in listed["artifacts"]] == [founder_artifact]
    saved = store.persist_state_http(FOUNDER_RUNTIME, wid, OWNER, founder_artifact, {"expectedStateRevision": 0, "patch": {"$period": "7d"}})
    assert saved["stateRevision"] == 1
    with ui_transaction(FOUNDER_RUNTIME, OWNER, wid, "read") as (cur, auth):
        replay = store.replay_view(cur, auth, founder_artifact, 0)
    assert replay["artifactId"] == founder_artifact and replay["done"] is True
    denied(lambda: store.persist_state_http(RUNTIME, wid, OWNER, founder_artifact, {"expectedStateRevision": 1, "patch": {"$period": "1d"}}), 404)
    denied(lambda: _replay(RUNTIME, founder_artifact), 404)
    denied(lambda: store.persist_state_http(FOUNDER_RUNTIME, wid, OWNER, STATE["artifact"], {"expectedStateRevision": 0, "patch": {}}), 404)
    denied(lambda: _replay(FOUNDER_RUNTIME, STATE["artifact"]), 404)
    denied(lambda: store.by_message_http(FOUNDER_RUNTIME, wid, OWNER, MAIN["message"]), 404)
    demo = Runtime(service, CFG, founder={"namespace": "founder:demo:production"})
    denied(lambda: store.snapshot_http(demo, wid, OWNER, founder_artifact), 404)                                          # Demo never sees Live
    return {"founderRoutes": ["claim", "commit", "snapshot", "byMessage", "state", "events"]}



@scenario("F-S17", "RLS: the authenticated role cannot read any migration-102 table directly (service-only)")
def _rls():
    for table in ("pr_ui_artifacts", "pr_ui_revisions", "pr_ui_attempts", "pr_ui_events", "pr_ui_actions", "pr_ui_activations"):
        with connection() as db:
            db.execute("SET ROLE authenticated")
            db.execute("SELECT set_config('request.jwt.claim.sub', %s, false)", (ONE,))
            try:
                db.execute(f"SELECT count(*) FROM public.{table}").fetchone()
                raise AssertionError(f"{table} readable by authenticated")
            except psycopg.errors.InsufficientPrivilege:
                db.rollback()
    return {}


@scenario("F-S18", "workspace switch: an artifact id from another workspace is the same 404 everywhere")
def _switch():
    artifact = STATE["artifact"]
    denied(lambda: store.snapshot_http(RUNTIME, other, OTHER, artifact), 404)
    denied(lambda: store.persist_state_http(RUNTIME, other, OTHER, artifact, {"expectedStateRevision": 0, "patch": {"$period": "1d"}}), 404)
    denied(lambda: store.by_message_http(RUNTIME, other, OTHER, MAIN["message"]), 404)
    return {}


@scenario("F-S19", "HF-3 revoked Library/media: a deleted or deleting Library file and a deleted photo/generated image are revoked on reopen and dropped from selections")
def _revoked_library_media():
    files = {name: uuid.uuid4() for name in ("kept", "removed", "deleting", "duplicate")}
    with connection() as db:
        for name, ident in files.items():
            db.execute("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,display_title,kind,mime,extension,bytes,sha256,bucket,object_name,"
                       "processing_status,analysis_status,indexing_status) VALUES(%s,%s,%s,%s,%s,'document','text/plain','txt',120,%s,'postriff-library',%s,'ready','ready','ready')",
                       (ident, wid, ONE, f"{name}.txt", name.title(), "e" * 64, uuid.uuid4().hex + ".txt"))
    media = {name: uuid.uuid4().hex for name in ("photo", "generated", "removed_photo", "pending_photo")}
    state = one("SELECT state FROM public.pr_workspaces WHERE id=%s", wid)[0]
    phase2 = dict(state.get("phase2") or {})
    phase2["assets"] = list(phase2.get("assets") or []) + [{"id": ident, "mime": "image/png"} for ident in media.values()]
    run_sql("UPDATE public.pr_workspaces SET state = jsonb_set(state, '{phase2}', %s::jsonb) WHERE id=%s", json.dumps(phase2), wid)
    refs = [{"type": "library_file", "id": files["kept"].hex}, {"type": "library_file", "id": files["removed"].hex},
            {"type": "library_file", "id": str(files["deleting"])}, {"type": "library_file", "id": files["duplicate"].hex},
            {"type": "media", "id": media["photo"]}, {"type": "asset", "id": media["generated"]}, {"type": "media", "id": media["removed_photo"]},
            {"type": "image", "id": media["pending_photo"]}, {"type": "draft", "id": "d1"}]
    run = fixture_run(wid, ONE, title="library refs")
    with ui_transaction(RUNTIME, OWNER, wid, "edit") as (cur, auth):
        lease = store.create_or_resume_artifact(cur, auth, run["run"], "main", key(), surface="chat", manifest={**MANIFEST, "approvedRefs": refs},
                                                projection=PROJECTION, lease_owner="pid:test")
    artifact = lease["artifact"]["artifactId"]
    commit(OWNER, artifact, lease["attempt"]["idempotencyKey"], 0, None, SOURCE)
    snap = store.snapshot_http(RUNTIME, wid, OWNER, artifact)
    assert snap["access"]["revokedRefs"] == [] and snap["display"]["mode"] == "generated", (snap["access"], snap["display"])

    def select(expected):
        items = [{"type": r["type"], "id": r["id"], "title": ""} for r in refs]
        with ui_transaction(RUNTIME, OWNER, wid, "edit") as (cur, auth):
            return store.persist_ui_state(cur, auth, artifact, expected, {store.SELECTION_KEY: {"items": items}})
    selected = select(snap["artifact"]["stateRevision"])
    # Delete one file outright, start deleting another, mark one a duplicate; delete one photo and leave another pending deletion.
    run_sql("DELETE FROM public.pr_library_assets WHERE id=%s", files["removed"])
    run_sql("UPDATE public.pr_library_assets SET processing_status='deleting' WHERE id=%s", files["deleting"])
    run_sql("UPDATE public.pr_library_assets SET processing_status='duplicate' WHERE id=%s", files["duplicate"])
    state = one("SELECT state FROM public.pr_workspaces WHERE id=%s", wid)[0]
    for asset in state["phase2"]["assets"]:
        if asset.get("id") == media["removed_photo"]:
            asset["deleted"] = True
        if asset.get("id") == media["pending_photo"]:
            asset.update({"deleted": True, "deletionPending": True})
    run_sql("UPDATE public.pr_workspaces SET state = jsonb_set(state, '{phase2}', %s::jsonb) WHERE id=%s", json.dumps(state["phase2"]), wid)
    expected = [f"library_file:{files['removed'].hex}", f"library_file:{files['deleting']}", f"library_file:{files['duplicate'].hex}",
                f"media:{media['removed_photo']}", f"image:{media['pending_photo']}"]
    snap = store.snapshot_http(RUNTIME, wid, OWNER, artifact)
    assert snap["access"]["revokedRefs"] == expected, snap["access"]["revokedRefs"]
    # The same treatment as any other revoked source: the generated view stays, with the count the surface explains.
    assert snap["display"] == {"mode": "generated", "reason": None, "updating": False, "revokedRefs": len(expected)}, snap["display"]
    with ui_transaction(RUNTIME, OWNER, wid, "read") as (cur, auth):
        context = store.selection_context(cur, auth, {"artifactId": artifact, "artifactRevision": 1, "stateRevision": selected["stateRevision"]})
    assert [(r["type"], r["id"]) for r in context["references"]] == [("library_file", files["kept"].hex), ("media", media["photo"]),
                                                                      ("asset", media["generated"]), ("draft", "d1")], context["references"]
    assert "no longer available" in context["note"], context["note"]
    # Another workspace's copy of a live file id is not a live file here.
    with ui_transaction(RUNTIME, OTHER, other, "read") as (cur, auth):
        assert store.revoked_refs(cur, auth, {"approvedRefs": [{"type": "library_file", "id": files["kept"].hex}]}) == [f"library_file:{files['kept'].hex}"]
    return {"revoked": len(expected)}


@scenario("F-S20", "HF-3 actor-only edits: a co-member editor reads and keeps their view state but is not offered canEdit; the actor is")
def _actor_only_edit():
    artifact = STATE["artifact"]
    mine = store.snapshot_http(RUNTIME, wid, OWNER, artifact)["access"]
    theirs = store.snapshot_http(RUNTIME, wid, EDITOR, artifact)["access"]
    assert mine["isActor"] is True and mine["canEdit"] is True, mine
    assert theirs["isActor"] is False and theirs["canEdit"] is False, theirs
    assert theirs["canQuery"] is True and theirs["canPersistState"] is True, theirs
    viewer = store.snapshot_http(RUNTIME, wid, VIEWER, artifact)["access"]
    assert viewer["canEdit"] is False and viewer["isActor"] is False, viewer
    return {}


summary ={"PASS": sum(1 for e in EVIDENCE if e["result"] == "PASS"), "FAIL": sum(1 for e in EVIDENCE if e["result"] == "FAIL")}
out = Path(os.environ.get("AGENT_UI_EVIDENCE_DIR") or (ROOT / "docs/design/openui-production-2026-10-08/evidence/lanes"))
try:
    out.mkdir(parents=True, exist_ok=True)
    (out / "F-pg-store.json").write_text(json.dumps({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                     "execution": "disposable PostgreSQL 17; real hosted repository, roles, ledger and RLS harness; no provider",
                                                     "summary": summary, "scenarios": EVIDENCE}, indent=1, default=str))
except OSError:
    pass
print(json.dumps(summary))
sys.exit(1 if summary["FAIL"] or not summary["PASS"] else 0)
