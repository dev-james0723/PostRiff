"""Time Back on the hosted repository (docs/raffi-time-back/ENGINEERING.md §16-17) against a disposable PostgreSQL:
generated work saves nothing until it is used; an accepted draft earns one row with its measured active time; a
provider-verified publication earns exactly one publish row, and replays, retries, published/uncertain/failed results
earn none; a Time Back fault never unverifies a publication or fails a command, and the cron repair fills the gap;
adaptations, languages and non-Raffi drafts follow the counting rules; automation setup counts once; heartbeats are
bounded, idempotent and personal; calibration personalizes the baseline; the summary reconciles; RLS keeps each
person's rows to themselves; ledger rows are immutable and leave with the account.

Run through scripts/postriff_pg_suite.py (rls.sql loads migration 023).
"""
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2 import time_savings as tb
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_worker import PostgresWorker

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"
THREE = "00000000-0000-0000-0000-000000000003"
TOKENS = {"fixture-one": ONE, "fixture-two": TWO}
clock = [time.time()]
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required", 401)
    return TOKENS[token]


def refused(status, call):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return str(error)
    raise AssertionError(f"expected HTTP {status}")


with connection() as db:
    wid = str(db.execute("select workspace_id from public.pr_memberships where user_id=%s", (ONE,)).fetchone()[0])
    foreign = str(db.execute("select workspace_id from public.pr_memberships where user_id=%s", (TWO,)).fetchone()[0])
    db.execute("update public.pr_workspaces set state='{}'::jsonb where id=%s", (wid,))
    db.execute("update public.pr_memberships set status='active', role='owner' where user_id=%s", (ONE,))
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
snapshot = service.bootstrap("fixture-one", "studio")


def act(action, payload):
    global snapshot
    snapshot = service.mutate(wid, "fixture-one", snapshot["revision"], action, payload)
    return snapshot["state"]


def command(fn):
    global snapshot
    saved = service.repository.command(wid, "fixture-one", snapshot["revision"], fn)
    snapshot = service.commands.present(saved["state"], saved["revision"])
    return snapshot["state"]


def refresh():
    """The worker and the repair write the workspace too; read it again before the next command."""
    global snapshot
    snapshot = service.get(wid, "fixture-one")
    return snapshot


def ledger(user=ONE, kind=None):
    with connection() as db:
        rows = db.execute("select task_kind,outcome_ref,baseline_seconds,active_seconds,saved_seconds,baseline_source,confidence,metadata,calculator_version,baseline_version "
                          "from public.pr_time_savings_ledger where workspace_id=%s and beneficiary_user_id=%s" + (" and task_kind=%s" if kind else "") + " order by created_at,id",
                          (wid, user) + ((kind,) if kind else ())).fetchall()
    keys = ("kind", "ref", "baseline", "active", "saved", "source", "confidence", "metadata", "calculator", "baselineVersion")
    return [dict(zip(keys, row)) for row in rows]


# --- generated work saves nothing -------------------------------------------------------------------------------------
act("mode", {"mode": "personal"})
act("context", {"purpose": "Make community learning accessible", "audience": "Curious beginners", "subject": "Community workshops", "speaker": "My voice", "layers": []})
act("source", {"kind": "sample"})
source = snapshot["state"]["sources"][-1]
act("approve_source", {"sourceId": source["id"], "factIds": [fact["id"] for fact in source["facts"]]})
act("source_done", {})
act("profile_propose", {"writing": "A small step can be a useful beginning.", "tone": "warm"})
act("profile_decide", {"decision": "approve"})
act("runtime", {"selected": "deterministic-preview"})
act("generate", {"platform": "LinkedIn", "language": "English"})
variant = snapshot["state"]["variants"][0]
assert variant["revisions"][0]["origin"] == "fixture"
assert ledger() == [], "generating a draft saves nothing"
checks.append("a generated draft that is not used saves nothing")

# --- heartbeats: aggregate seconds only, bounded, idempotent, personal -----------------------------------------------
session_key = "draft-session-" + uuid.uuid4().hex[:12]
workflow = "variant:" + variant["id"]


def beat(seconds, sequence, token="fixture-one", workspace=None, **extra):
    return service.time_savings.activity(workspace or wid, token, {"clientSessionKey": session_key, "workflowKey": workflow, "taskKind": "draft", "activeSeconds": seconds, "sequence": sequence, **extra})


assert beat(200, 1, userId=TWO) == {"accepted": True, "activeSeconds": tb.FIRST_HEARTBEAT, "sequence": 1}, "a new session opens with at most one heartbeat period"
assert beat(200, 1) == {"accepted": False, "activeSeconds": 90, "sequence": 1}, "a retried heartbeat changes nothing"
clock[0] += 30
assert beat(130, 2)["activeSeconds"] == 130
assert beat(100, 3)["activeSeconds"] == 130, "the stored value never decreases"
assert beat(125, 2) == {"accepted": False, "activeSeconds": 130, "sequence": 3}, "a late, lower sequence is ignored"
assert beat(5000, 4)["activeSeconds"] == 130 + tb.HEARTBEAT_SLACK, "no more than the wall-clock time since the last beat"
with connection() as db:
    stored = db.execute("select user_id::text, workflow_key, task_kind, active_seconds, sequence from public.pr_active_work_sessions where workspace_id=%s", (wid,)).fetchall()
    columns = {row[0] for row in db.execute("select column_name from information_schema.columns where table_name='pr_active_work_sessions'").fetchall()}
assert stored == [(ONE, workflow, "draft", 145, 4)], stored
assert not columns & {"text", "key", "keys", "x", "y", "selector", "path", "url", "prompt", "caption"}, columns
refused(403, lambda: beat(10, 5, workspace=foreign))
refused(400, lambda: service.time_savings.activity(wid, "fixture-one", {"clientSessionKey": session_key, "workflowKey": "Draft about our launch party", "taskKind": "draft", "activeSeconds": 10, "sequence": 9}))
refused(409, lambda: service.time_savings.activity(wid, "fixture-one", {"clientSessionKey": session_key, "workflowKey": "variant:" + "0" * 32, "taskKind": "draft", "activeSeconds": 10, "sequence": 9}))
checks.append("heartbeats store aggregate seconds only; retries, late or inflated beats cannot add time; another person's id in the payload is ignored")

# --- an accepted draft earns one measured row ------------------------------------------------------------------------
variant = snapshot["state"]["variants"][0]
act("p2_variant_review", {"variantId": variant["id"], "variantRevision": variant["revision"], "confirmed": True, "excludedUnknowns": variant["unknowns"]})
channel = {"id": uuid.uuid4().hex, "platform": "LinkedIn", "account": "Verified test member", "accountType": "member", "language": "English", "scopes": ["w_member_social"],
           "verifiedAt": clock[0], "expiresAt": clock[0] + 30 * 86400, "capabilityVersion": 1, "providerAccountId": "urn:li:person:test"}
command(lambda state, actor: service.commands.upsert_verified_channel(state, actor, channel))


def approve(minutes_ahead):
    refresh()
    local = datetime.fromtimestamp(clock[0] + minutes_ahead * 60, timezone.utc).replace(tzinfo=None).isoformat()
    current = next(v for v in snapshot["state"]["variants"] if v["id"] == variant["id"])
    act("p2_review", {"channelId": channel["id"], "variantId": current["id"], "localTime": local, "timeZone": "UTC", "acknowledgedWarnings": current["warnings"]})
    review = snapshot["state"]["phase2"]["reviews"][-1]
    act("p2_approve", {"reviewId": review["id"], "digest": review["digest"], "confirmed": True})
    return snapshot["state"]["phase2"]["jobs"][-1]


first_job = approve(2)
rows = ledger()
assert len(rows) == 1, rows
draft = rows[0]
assert (draft["kind"], draft["ref"], draft["baseline"], draft["active"], draft["saved"], draft["source"], draft["confidence"]) == ("draft", workflow, 480, 145, 335, "raffi_default", "measured"), draft
assert draft["metadata"] == {"platform": "LinkedIn", "language": "English", "channelId": channel["id"], "groupRef": "run:" + variant["runId"], "source": "command"}, draft["metadata"]
assert (draft["calculator"], draft["baselineVersion"]) == (tb.CALCULATOR_VERSION, tb.DEFAULTS_VERSION)
checks.append("approving a generated draft for publishing records one draft row: baseline 8m minus 145 measured seconds")


# --- verified publishing ----------------------------------------------------------------------------------------------
class Social:
    def __init__(self, submit, reconcile=None):
        self.submitted, self.reconciled = submit, reconcile

    def submit(self, manifest):
        return self.submitted

    def reconcile(self, manifest, job):
        return self.reconciled


ACCEPTED = {"state": "provider_accepted", "confirmed": "Disposable adapter accepted", "reference": "disposable-1"}
VERIFIED = {"state": "verified", "confirmed": "Disposable lookup matched", "verification": "disposable_lookup", "reference": "disposable-1"}


def current_job(job_id):
    return next(j for j in refresh()["state"]["phase2"]["jobs"] if j["id"] == job_id)


def publish(job, social, on_verified=None, steps=2):
    """Run the worker from the job's scheduled time (its approval expires an hour later): submit, then reconcile."""
    worker = PostgresWorker(connection, social=social, clock=lambda: clock[0], worker_id="disposable-worker",
                            on_verified=on_verified or tb.with_time_back(service.audience.on_post_verified, service.time_savings))
    clock[0] = max(clock[0], job["nextAt"]) + 1
    for _ in range(steps):
        assert worker.step()
        clock[0] += 46
    return current_job(job["id"])


def park(job_id):
    """Keep an unresolved job out of the worker's way for the rest of the test (trusted test command)."""
    def hold(state, actor):
        next(j for j in state["phase2"]["jobs"] if j["id"] == job_id)["nextAt"] = clock[0] + 20 * 86400
        return state
    command(hold)


def publish_rows():
    return ledger(kind="publish")


worker = PostgresWorker(connection, social=Social(ACCEPTED, VERIFIED), clock=lambda: clock[0], worker_id="disposable-worker",
                        on_verified=tb.with_time_back(service.audience.on_post_verified, service.time_savings))
clock[0] += 400
assert worker.step()
assert current_job(first_job["id"])["state"] == "provider_accepted" and publish_rows() == [], "provider acceptance is not verification"
clock[0] += 46
assert worker.step()
job = current_job(first_job["id"])
assert job["state"] == "verified" and "timeSavings" not in job, job
rows = publish_rows()
assert len(rows) == 1 and (rows[0]["ref"], rows[0]["baseline"], rows[0]["active"], rows[0]["saved"], rows[0]["confidence"]) == ("job:" + first_job["id"], 180, None, 180, "estimated"), rows
assert rows[0]["metadata"] == {"platform": "LinkedIn", "channelId": channel["id"], "source": "worker"}
checks.append("a provider-verified publication records exactly one publish row for the approving person")

with connection() as db:
    with db.cursor() as cur:
        assert service.time_savings.record_verified_publish(cur, wid, job)["reason"] == "duplicate"
clock[0] += 400
assert not worker.step(), "a verified job is terminal"
assert len(publish_rows()) == 1 and len(ledger(kind="draft")) == 1
checks.append("replaying the verified outcome or ticking the worker again adds nothing")

second = approve(3)
assert len(ledger(kind="draft")) == 1, "a second schedule of the same draft is not a second draft"
failed = publish(second, Social({"state": "failed", "confirmed": "Provider rejected the post"}), steps=1)
assert failed["state"] == "failed" and len(publish_rows()) == 1, failed["state"]
third = approve(3)
published = publish(third, Social({"state": "published", "confirmed": "Provider accepted the post", "reference": "disposable-2"}), steps=1)
assert published["state"] == "published" and len(publish_rows()) == 1, published["state"]
uncertain = publish(published, Social(None, {"state": "uncertain", "confirmed": "Lookup could not confirm the post"}), steps=1)
assert uncertain["state"] == "uncertain" and len(publish_rows()) == 1, uncertain["state"]
park(third["id"])
checks.append("published, uncertain and failed results earn no publish time; re-scheduling a draft earns no second draft row")

# --- a Time Back fault never unverifies a publication or fails a command; the cron repairs it --------------------------
with connection() as db:
    db.execute("alter table public.pr_time_savings_ledger rename to pr_time_savings_ledger_offline")
fourth = approve(3)
assert fourth["state"] == "scheduled", "the approval command succeeded without Time Back"
repaired_job = publish(fourth, Social(ACCEPTED, VERIFIED))
assert repaired_job["state"] == "verified" and repaired_job["timeSavings"] == "pending", repaired_job
assert "insights" not in repaired_job, "comment ingestion is unaffected"
with connection() as db:
    db.execute("alter table public.pr_time_savings_ledger_offline rename to pr_time_savings_ledger")
assert len(publish_rows()) == 1
maintained = service.time_savings.maintain()
assert (maintained["status"], maintained["repaired"], maintained["pending"]) == ("ok", 1, 0), maintained
repaired_job = current_job(fourth["id"])
assert repaired_job["state"] == "verified" and "timeSavings" not in repaired_job
rows = publish_rows()
assert len(rows) == 2 and rows[-1]["ref"] == "job:" + fourth["id"] and rows[-1]["metadata"]["source"] == "repair", rows
assert service.time_savings.maintain()["repaired"] == 0, "repair runs once"
assert "UndefinedTable" in service.time_savings.failures
checks.append("with the ledger unavailable the approval still succeeds and the publication stays verified; the cron repair then records it once")


def exploding(cur, workspace_id, job):
    raise RuntimeError("comment ingestion failed")


fifth = approve(3)
ingestion_failed = publish(fifth, Social(ACCEPTED, VERIFIED), on_verified=tb.with_time_back(exploding, service.time_savings))
assert ingestion_failed["state"] == "verified" and ingestion_failed["insights"]["availability"] == "unavailable", ingestion_failed
assert [row["ref"] for row in publish_rows()].count("job:" + fifth["id"]) == 1 and len(publish_rows()) == 3
checks.append("a failing comment-ingestion hook neither blocks nor duplicates the publish row")

# --- drafts, adaptations and what does not count ---------------------------------------------------------------------
run, later_run = str(uuid.uuid4()), str(uuid.uuid4())


def generated(platform, provenance, language="English", origin="ideas-candidate", text=None, channel=None):
    variant = {"id": uuid.uuid4().hex, "platform": platform, "language": language, "revisions": [{"origin": origin}], "provenance": provenance, "text": text or f"{platform} {language} {uuid.uuid4().hex[:6]}"}
    return {**variant, "channelId": channel} if channel else variant


account_a, account_b = uuid.uuid4().hex, uuid.uuid4().hex
linkedin = generated("LinkedIn", {"runId": run}, text="Our garden workshop opens on Saturday.")
threads = generated("Threads", {"runId": run})
instagram = generated("Instagram", {"runId": later_run, "derivedFrom": linkedin["id"]})
linkedin_zh = generated("LinkedIn", {"runId": run}, language="Chinese", text="花園工作坊星期六開始。")
linkedin_reworded = generated("LinkedIn", {"runId": later_run, "derivedFrom": linkedin["id"]}, text="Saturday: the garden workshop opens.")
linkedin_account_a = generated("LinkedIn", {"runId": run}, text="Our garden workshop opens on Saturday.", channel=account_a)
linkedin_account_b = generated("LinkedIn", {"runId": run}, text="Neighbours: bring seeds to Saturday's workshop.", channel=account_b)
own_words = generated("Threads", {"runId": str(uuid.uuid4())}, origin="author-edit")
order = (linkedin, threads, instagram, linkedin_zh, linkedin_reworded, linkedin_account_a, linkedin_account_b, own_words)
state = {"variants": list(order)}
with connection() as db:
    with db.cursor() as cur:
        results = [tb.record_acceptance(cur, wid, state, {"variantId": v["id"], "principal": ONE, "at": clock[0]}, clock[0]) for v in order]
        replay = tb.record_acceptance(cur, wid, state, {"variantId": threads["id"], "principal": ONE, "at": clock[0]}, clock[0])
        outsider = tb.record_acceptance(cur, wid, {"variants": [generated("X", {"runId": str(uuid.uuid4())})]}, {"variantId": None, "principal": TWO, "at": clock[0]}, clock[0])
assert [r["taskKind"] if r["recorded"] else r["reason"] for r in results] == [
    "draft", "adapt", "adapt", "adapt", "version_counted", "identical_version", "adapt", "not_generated"], results
assert replay["reason"] == "duplicate" and outsider["recorded"] is False
adapt = ledger(kind="adapt")
assert [(row["saved"], row["confidence"], row["metadata"]["groupRef"]) for row in adapt] == [(240, "estimated", "run:" + run)] * 4, adapt
assert {(row["metadata"]["platform"], row["metadata"]["language"], row["metadata"].get("channelId")) for row in adapt} == {
    ("Threads", "English", None), ("Instagram", "English", None), ("LinkedIn", "Chinese", None), ("LinkedIn", "English", account_b)}
assert "花園" not in json.dumps([row["metadata"] for row in ledger()], ensure_ascii=False), "no draft text is stored"
checks.append("a post's first version is a draft; each separate platform, language or account version is an adaptation (derived ones included); a re-worded version of a counted slot, a version identical to one counted, an author's own draft or a replay adds nothing")

task = {"id": uuid.uuid4().hex, "status": "draft", "schedule": {"kind": "weekly"}}
active = {**task, "status": "active", "activatedBy": ONE, "activatedAt": clock[0]}


def planning(*tasks):
    return {"raffi": {"campaignPlanning": {"recurringTasks": list(tasks)}}}


with connection() as db:
    with db.cursor() as cur:
        service.time_savings.capture(cur, wid, planning(task), planning(active), ONE)
        service.time_savings.capture(cur, wid, planning({**active, "status": "paused"}), planning(active), ONE)
        service.time_savings.capture(cur, wid, planning(task), planning(active), ONE)
rows = ledger(kind="recurring_setup")
assert [(row["ref"], row["saved"]) for row in rows] == [("automation:" + task["id"], 600)], rows
checks.append("activating an automation counts once; a resume or a re-activation after an edit does not")

# --- summary, calibration and provenance ------------------------------------------------------------------------------
summary = service.time_savings.summary(wid, "fixture-one", "30d")
mine = ledger()
assert summary["state"] == "ready" and summary["completedTasks"] == len(mine) == 10, (summary, len(mine))
assert summary["totalSavedSeconds"] == sum(row["saved"] for row in mine) == 335 + 480 + 240 * 4 + 180 * 3 + 600
assert sum(item["minutes"] for item in summary["breakdown"]) == summary["totalMinutes"] == tb.display_minutes(summary["totalSavedSeconds"])
assert sum(item["count"] for item in summary["breakdown"]) == summary["completedTasks"]
assert [item["taskKind"] for item in summary["breakdown"]] == ["draft", "adapt", "publish", "recurring_setup"]
assert summary["confidence"] == {"estimated": 9, "personalized": 0, "measured": 1} and summary["basis"] == "estimated", summary
assert summary["calibration"]["due"] == ["draft", "adapt", "publish", "recurring_setup"] and summary["hasCalibrationPrompt"] is True
assert service.time_savings.summary(wid, "fixture-one", "all")["totalSavedSeconds"] == summary["totalSavedSeconds"]
refused(400, lambda: service.time_savings.summary(wid, "fixture-one", "forever"))
refused(403, lambda: service.time_savings.summary(foreign, "fixture-one"))
refused(403, lambda: service.time_savings.summary(wid, "prt_" + "x" * 40))
checks.append("the summary reconciles: breakdown minutes and counts add up to the displayed total; foreign workspaces and API tokens are refused")

for answer in (600, 900, 1200):
    clock[0] += 60
    answered = service.time_savings.calibrate(wid, "fixture-one", {"taskKind": "draft", "source": "prompt", "manualSeconds": answer})
assert "draft" not in answered["calibration"]["due"], "answering starts the 30-day quiet period"
assert next(b for b in answered["calibration"]["baselines"] if b["taskKind"] == "draft") == {"taskKind": "draft", "seconds": 900, "source": "personalized", "samples": 3, "defaultSeconds": 480, "automaticSeconds": 900}
dismissed = service.time_savings.calibrate(wid, "fixture-one", {"taskKind": "publish", "source": "prompt", "dismissed": True})
assert dismissed["calibration"]["due"] == ["adapt", "recurring_setup"], dismissed["calibration"]["due"]
for payload in ({"taskKind": "draft", "source": "prompt", "manualSeconds": 30}, {"taskKind": "draft", "source": "prompt", "manualSeconds": 20000},
                {"taskKind": "reporting", "source": "prompt", "manualSeconds": 600}, {"taskKind": "draft", "source": "guess", "manualSeconds": 600}):
    refused(400, lambda payload=payload: service.time_savings.calibrate(wid, "fixture-one", payload))


def accept_new(platform="Bluesky"):
    fresh = generated(platform, {"runId": str(uuid.uuid4())})
    with connection() as db:
        with db.cursor() as cur:
            return tb.record_acceptance(cur, wid, {"variants": [fresh]}, {"variantId": fresh["id"], "principal": ONE, "at": clock[0]}, clock[0])


assert accept_new() == {"recorded": True, "reason": None, "taskKind": "draft", "savedSeconds": 900, "confidence": "personalized"}
service.time_savings.calibrate(wid, "fixture-one", {"taskKind": "draft", "source": "settings_override", "manualSeconds": 1800})
assert accept_new()["savedSeconds"] == 1800
assert ledger(kind="draft")[-1]["source"] == "user_override"
service.time_savings.calibrate(wid, "fixture-one", {"taskKind": "draft", "source": "settings_override", "clear": True})
assert accept_new()["savedSeconds"] == 900
earlier = ledger(kind="draft")[0]
assert (earlier["baseline"], earlier["saved"]) == (480, 335), "a new baseline never rewrites earlier rows"
checks.append("three answers personalize the baseline (median), an explicit setting overrides it and can be cleared, dismissing or answering pauses the prompt, earlier rows never change")

# --- another member, RLS, immutability, constraints -------------------------------------------------------------------
with connection() as db:
    db.execute("insert into public.pr_memberships(workspace_id,user_id,role,status) values (%s,%s,'editor','active')", (wid, TWO))
    with db.cursor() as cur:
        other = tb.record_outcome(cur, wid, TWO, "publish", "verified_publication", "job:" + uuid.uuid4().hex, None, clock[0])
assert other["recorded"], other
theirs = service.time_savings.summary(wid, "fixture-two", "30d")
assert theirs["completedTasks"] == 1 and theirs["totalSavedSeconds"] == 180, theirs
assert service.time_savings.summary(wid, "fixture-one", "30d")["completedTasks"] == 13, "one person's rows never appear in another's total"
with connection() as db:
    db.execute("set role authenticated")
    db.execute("select set_config('request.jwt.claim.sub', %s, false)", (ONE,))
    visible = db.execute("select count(*), count(*) filter (where beneficiary_user_id=%s) from public.pr_time_savings_ledger", (TWO,)).fetchone()
    leaks = [db.execute(f"select count(*) from public.{table} where workspace_id=%s", (foreign,)).fetchone()[0]
             for table in ("pr_time_savings_ledger", "pr_time_savings_calibrations", "pr_time_savings_preferences", "pr_active_work_sessions")]
    sessions = db.execute("select count(*) from public.pr_active_work_sessions").fetchone()[0]
    for statement in ("insert into public.pr_time_savings_ledger(workspace_id,beneficiary_user_id,task_kind,outcome_kind,outcome_ref,dedupe_key,baseline_seconds,saved_seconds,baseline_source,baseline_version,confidence,calculator_version,occurred_at) "
                      "values (%s,%s,'publish','verified_publication','job:forged',repeat('a',64),180,180,'raffi_default','x','estimated','x',now())",
                      "insert into public.pr_time_savings_calibrations(workspace_id,user_id,task_kind,baseline_seconds,source) values (%s,%s,'draft',600,'prompt')",
                      "insert into public.pr_active_work_sessions(workspace_id,user_id,workflow_key,client_session_key,task_kind,started_at,last_active_at) values (%s,%s,'variant:x','kkkkkkkkkkkkkkkkkkkk','draft',now(),now())"):
        try:
            db.execute(statement, (wid, ONE))
            raise AssertionError("browser write accepted: " + statement[:60])
        except psycopg.errors.InsufficientPrivilege:
            db.rollback()
            db.execute("set role authenticated")
            db.execute("select set_config('request.jwt.claim.sub', %s, false)", (ONE,))
    db.execute("reset role")
assert visible == (13, 0) and leaks == [0, 0, 0, 0] and sessions == 1, (visible, leaks, sessions)
checks.append("a member reads only their own rows in an active workspace; the browser role cannot insert ledger, calibration or activity rows")

with connection() as db:
    for statement, error in (("update public.pr_time_savings_ledger set saved_seconds=0 where workspace_id=%s", psycopg.errors.InsufficientPrivilege),
                             ("insert into public.pr_time_savings_ledger(workspace_id,beneficiary_user_id,task_kind,outcome_kind,outcome_ref,dedupe_key,baseline_seconds,active_seconds,saved_seconds,baseline_source,baseline_version,confidence,calculator_version,occurred_at) "
                              "values (%s,'" + ONE + "','draft','accepted_draft','variant:inflated',repeat('b',64),480,100,480,'raffi_default','x','measured','x',now())", psycopg.errors.CheckViolation),
                             ("insert into public.pr_time_savings_ledger(workspace_id,beneficiary_user_id,task_kind,outcome_kind,outcome_ref,dedupe_key,baseline_seconds,saved_seconds,baseline_source,baseline_version,confidence,calculator_version,occurred_at) "
                              "values (%s,'" + ONE + "','draft','accepted_draft','variant:mislabelled',repeat('c',64),480,480,'raffi_default','x','measured','x',now())", psycopg.errors.CheckViolation),
                             ("insert into public.pr_time_savings_ledger(workspace_id,beneficiary_user_id,task_kind,outcome_kind,outcome_ref,dedupe_key,baseline_seconds,saved_seconds,baseline_source,baseline_version,confidence,calculator_version,occurred_at) "
                              "values (%s,'" + ONE + "','publish','verified_publication','job:" + first_job["id"] + "',repeat('d',64),180,180,'raffi_default','x','estimated','time-back-v2',now())", psycopg.errors.UniqueViolation)):
        try:
            db.execute(statement, (wid,))
            raise AssertionError("accepted: " + statement[:70])
        except error:
            db.rollback()
checks.append("ledger rows are immutable; saved time and provenance must follow from the row; one outcome cannot be counted again under another calculator version")

# --- unknown beneficiaries, account deletion, retention ---------------------------------------------------------------
with connection() as db:
    db.execute("update public.pr_memberships set status='revoked' where workspace_id=%s and user_id=%s", (wid, TWO))
    with db.cursor() as cur:
        gone = tb.record_verified_publish(cur, wid, {"id": uuid.uuid4().hex, "state": "verified", "approvedBy": TWO, "verification": {"at": clock[0]}, "manifest": {"actor": TWO, "platform": "LinkedIn"}})
assert gone["recorded"] is False and gone["reason"] == "no_beneficiary"
refused(403, lambda: service.time_savings.summary(wid, "fixture-two"))
checks.append("a publication approved by someone no longer in the workspace records no row, and a former member can no longer read Time Back there")

with connection() as db:
    db.execute("insert into auth.users values (%s)", (THREE,))
    three_ws = str(db.execute("select public.pr_bootstrap(%s,'studio')", (THREE,)).fetchone()[0])
    db.execute("insert into public.pr_memberships(workspace_id,user_id,role,status) values (%s,%s,'editor','active')", (wid, THREE))
    with db.cursor() as cur:
        assert tb.record_outcome(cur, wid, THREE, "publish", "verified_publication", "job:" + uuid.uuid4().hex, None, clock[0])["recorded"]
        tb.record_calibration(cur, wid, THREE, {"taskKind": "draft", "source": "settings_override", "manualSeconds": 600}, clock[0])
        tb.upsert_active_session(cur, wid, THREE, {"clientSessionKey": "three-" + uuid.uuid4().hex, "workflowKey": "variant:abc", "taskKind": "draft", "activeSeconds": 20, "sequence": 1}, clock[0])
    # The account-deletion statements (account_deletion.py), after the person left the other workspace.
    db.execute("delete from public.pr_memberships where user_id=%s and workspace_id<>%s", (THREE, three_ws))
    db.execute("delete from public.pr_trials where user_id=%s", (THREE,))
    db.execute("delete from public.pr_memberships where workspace_id=%s", (three_ws,))
    db.execute("delete from public.pr_profiles where user_id=%s", (THREE,))
    db.execute("delete from public.pr_workspaces where id=%s", (three_ws,))
    left = [db.execute(f"select count(*) from public.{table} where {column}=%s", (THREE,)).fetchone()[0]
            for table, column in (("pr_time_savings_ledger", "beneficiary_user_id"), ("pr_time_savings_calibrations", "user_id"), ("pr_time_savings_preferences", "user_id"), ("pr_active_work_sessions", "user_id"))]
assert left == [0, 0, 0, 0], left
checks.append("deleting an account removes that person's Time Back rows in every workspace")

with connection() as db:
    db.execute("insert into public.pr_active_work_sessions(workspace_id,user_id,workflow_key,client_session_key,task_kind,active_seconds,started_at,last_active_at) "
               "values (%s,%s,'conversation:old','old-session-000000000000','draft',60,to_timestamp(%s),to_timestamp(%s))", (wid, ONE, clock[0] - 41 * 86400, clock[0] - 40 * 86400))
assert service.time_savings.maintain()["sessionsDropped"] == 1
checks.append("activity aggregates past the 30-day window are dropped by the cron")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
