"""Rafii POC-1 candidate on a real disposable PostgreSQL: one Instagram account, native reach, one 24h cohort.

SYNTHETIC publications, observations, providers and transports only: no OAuth, token refresh, provider call, model
call, payment or publication. Covers the database half of the POC-1 acceptance IDs (see tests/test_rafii_poc1_review.py
for the pure half).
"""
import csv
import io
import json
import os
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2 import insights, locales
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.coworker import flags, runtime
from postriff_phase2.growth import metric_schedule as M

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
USERS = {name: str(uuid.uuid4()) for name in ("owner", "other")}
DAY = 86400
# The synthetic clock follows the database's real clock, so scheduled due times and leases agree with now().
clock = [float(int(time.time()))]
SHA = "b" * 40
CONN = "ig-poc1-connection"
SCOPES = sorted(M.NATIVE_ANALYTICS_SCOPES["instagram"])
LANG = locales.canonical("en")
checks = []


def connection(): return psycopg.connect(DSN)
def verify(token): return USERS[token]
def iso(value): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))
def passed(name): checks.append(name); print("PASS rafii-poc1: " + name, flush=True)


def refused(fn, statuses):
    try:
        fn()
    except AlphaError as error:
        assert error.status in statuses, (error.status, str(error))
        return error
    raise AssertionError("Expected the action to be refused")


VALUES = {name: "1" for name in flags.FLAGS}
VALUES["POSTRIFF_SOURCE_SHA"] = SHA
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
runtime.attach(service, VALUES)
with connection() as db:
    for user in USERS.values():
        db.execute("INSERT INTO auth.users VALUES(%s)", (user,))
wid = service.bootstrap("owner", "studio")["workspaceId"]
other = service.bootstrap("other", "studio")["workspaceId"]
review, loop = service.coworker.review, service.coworker.growth_loop


class OAuth:
    """Fake worker grant source; counts calls. No token is ever exchanged or refreshed."""
    providers = {"instagram": SimpleNamespace(platform="Instagram", production_reviewed=True)}
    calls = 0

    def token_for_worker(self, workspace_id, connection_id):
        OAuth.calls += 1
        return {"accessToken": "synthetic-token", "provider": "instagram", "scopes": SCOPES}


class Transport:
    def __init__(self):
        self.urls = []

    def __call__(self, method, url, **kw):
        self.urls.append(url)
        return {"status": 200, "body": {"data": [{"name": "reach", "values": [{"value": 42}]}]}}


transport = Transport()
scheduler = M.MetricScheduler(connection, OAuth(), transport=transport, workspace_allowlist={wid}, clock=lambda: clock[0])
service.metric_reads = scheduler
service.growth = SimpleNamespace(hosted=service, env={M.FLAG: "1"})


def mutate(fn):
    return service.coworker._command(wid, "owner", lambda state, actor: fn(state), "owner", "poc1.test_fixture")


# ---- Fixture: 12 comparable posts (6 short, 6 long) plus the case table's edge posts --------------------------------
jobs, readings = [], []
def publication(jid, days, text):
    at = clock[0] - days * DAY - 3600
    jobs.append({"id": jid, "state": "verified", "providerReference": "native-" + jid, "verification": {"method": "synthetic_lookup", "at": at},
                 "manifest": {"channelId": CONN, "platform": "Instagram", "contentType": {"id": "text", "formatId": "text"},
                              "payload": {"text": text, "language": "en"}, "timing": {"timestamp": at, "timeZone": "UTC"}}})
    return at

SHORT, LONG = "Would you practise this way?", "A longer reflection about practice. " * 12
for i in range(12):
    at = publication(f"core-{i}", 2 + i, SHORT if i < 6 else LONG)
    readings.append((f"core-{i}", "reach", (200 + i * 10) if i < 6 else (100 + i), "available", at + DAY + 600, "24h", insights.DEFINITION_VERSION))
edge = {"zero": 14, "missing": 15, "late": 16, "legacy": 17, "definition": 18}
for name, days in edge.items():
    at = publication(f"edge-{name}", days, SHORT)
    readings.append({"zero": (f"edge-zero", "reach", 0, "available", at + DAY + 60, "24h", insights.DEFINITION_VERSION),
                     "missing": (f"edge-missing", "reach", None, "unavailable", at + DAY + 60, "24h", insights.DEFINITION_VERSION),
                     "late": (f"edge-late", "reach", 500, "available", at + DAY + 4 * 3600, "24h", insights.DEFINITION_VERSION),
                     "legacy": (f"edge-legacy", "reach", 900, "available", at + DAY, None, insights.DEFINITION_VERSION),
                     "definition": (f"edge-definition", "reach", 700, "available", at + DAY + 60, "24h", "2025-01")}[name])
channel = {"id": CONN, "platform": "Instagram", "configured": True, "revoked": False, "expiresAt": clock[0] + 90 * DAY,
           "identityVerified": True, "capabilityVerified": True, "verifiedAt": clock[0], "account": "@poc1-fixture"}
mutate(lambda state: state.setdefault("phase2", {}).update({"channels": [channel], "jobs": jobs}))
by_id = {j["id"]: j for j in jobs}
with connection() as db, db.cursor() as cur:
    cur.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'analytics','Direct')", (wid, CONN))
    cur.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'instagram','synthetic-account','sealed','k1',%s)",
                (wid, CONN, SCOPES))
    for jid, metric, value, availability, observed, offset, definition in readings:
        job = by_id[jid]
        cur.execute("""INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at,ingested_at,read_offset,source_endpoint)
                       VALUES(%s,%s,'instagram',%s,%s,%s,%s,%s,'count',%s,to_timestamp(%s),to_timestamp(%s),%s,%s)""",
                    (wid, CONN, job["providerReference"], jid, metric, definition, value, availability, observed, observed + 1, offset,
                     "https://graph.instagram.com/v25.0/native/insights?access_token=SYNTHETIC-SECRET"))
        if offset is not None:
            M.schedule(cur, wid, CONN, "instagram", job["providerReference"], jid, job["verification"]["at"], "verification", (("24h", DAY),))
            cur.execute("UPDATE public.pr_metric_reads SET status='done' WHERE workspace_id=%s AND job_id=%s", (wid, jid))
    hypothesis_id = str(uuid.uuid4())
    cohort = {"provider": "instagram", "connectionId": CONN, "language": LANG, "contentTypeId": "text", "definitionVersion": insights.DEFINITION_VERSION}
    cur.execute("""INSERT INTO public.pr_strategy_hypotheses(id,workspace_id,platform,dimension,cohort,statement,metric,arm_a,arm_b,sample_a,sample_b,effect,confidence,expires_at,evidence_ids,counter_evidence_ids)
                   VALUES(%s,%s,'Instagram','length',%s::jsonb,'Shorter posts may reach more people on Instagram for this account.','reach','short','long',6,6,0.5,'low',to_timestamp(%s),%s::jsonb,'[]')""",
                (hypothesis_id, wid, json.dumps(cohort), clock[0] + 60 * DAY, json.dumps([f"core-{i}" for i in range(6)])))
    db.commit()
SCOPE = {"channelIds": [CONN], "publicationPeriod": {"start": iso(clock[0] - 20 * DAY), "end": iso(clock[0]), "timezone": "UTC"},
         "horizon": "24h", "language": "en", "formatIds": ["text"],
         "nativeMetric": [{"provider": "instagram", "nativeName": "reach", "definitionVersion": insights.DEFINITION_VERSION, "unit": "count"}],
         "comparison": {"kind": "none"}, "aggregation": "median"}


def counts():
    """Rows that would show provider, model, paid or state work. GET/mount/filter must not move any of them."""
    out = {}
    with connection() as db:
        for table in ("pr_metric_reads", "pr_metric_observations", "pr_model_usage_events", "pr_usage_ledger", "pr_product_events", "pr_ai_call_events"):
            exists = db.execute("SELECT to_regclass(%s) IS NOT NULL", ("public." + table,)).fetchone()[0]
            out[table] = db.execute(f"SELECT count(*) FROM public.{table}").fetchone()[0] if exists else None
        out["revision"] = db.execute("SELECT revision FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
    out["providerCalls"], out["grantCalls"] = len(transport.urls), OAuth.calls
    return out


# ---- Flag default off -----------------------------------------------------------------------------------------------
from postriff_phase2.coworker import review as review_module
baseline = counts()
flags.attach({**VALUES, review_module.FLAG: "0"})
refused(lambda: review.read(wid, "owner", SCOPE), (404,))
flags.attach(VALUES)
passed("the review and report routes are off unless RAFII_REVIEW_SNAPSHOTS_ENABLED is on")

# ---- A-D01/02/03/05: qualification on stored rows; A-S07: reads and filters do no paid or provider work ----------------
before = counts()
first = review.read(wid, "owner", SCOPE)
json.dumps(first)
results = {e["publicationBinding"]["jobId"]: e for e in first["nativeResults"]}
assert first["qualification"] == "descriptive_only" and first["sampleN"] == 13, (first["qualification"], first["sampleN"])
assert first["coverage"]["excludedByReason"] == {"missing_reading": 1, "window_late": 1, "unknown_read_offset": 1, "definition_mismatch": 1}, first["coverage"]
assert (results["edge-zero"]["value"], results["edge-zero"]["valueState"], results["edge-zero"]["eligible"]) == (0.0, "measured", True)
assert (results["edge-missing"]["value"], results["edge-missing"]["valueState"]) == (None, "missing")
late = results["edge-late"]
assert late["value"] is None and late["rejectedReadings"][0]["windowQualification"] == "missed" and late["rejectedReadings"][0]["actualAgeSeconds"] == DAY + 4 * 3600, late
assert results["edge-legacy"]["reason"] == "unknown_read_offset" and results["edge-definition"]["reason"] == "definition_mismatch"
group = first["groups"][0]
assert (group["sampleSize"], group["value"], group["qualification"]) == (13, 111.0, "descriptive_only"), group
assert first["eligibility"][CONN]["usableNow"] is True and first["eligibility"][CONN]["platformApproval"] == "unknown"
takeaway_view = first["takeaways"][0]
assert takeaway_view["nextStep"] == {"kind": "propose", "existingExperimentId": None, "hypothesisId": hypothesis_id, "href": "/app/growth",
                                     "label": "Propose this controlled test in Growth Loop"}, takeaway_view["nextStep"]
assert "access_token" not in json.dumps(first)
for variant in ({**SCOPE, "aggregation": "mean"}, {**SCOPE, "language": None}, {**SCOPE, "formatIds": []}):
    review.read(wid, "owner", variant)
assert counts() == before, (before, counts())
passed("A-D01/02/03/05 stored rows: zero vs missing, late/legacy/definition exclusions with actual age, 13 comparable; A-S07 reads and filters wrote nothing and called no provider, model or grant")

# ---- A-D13: one frozen report, screen payload and three exports -----------------------------------------------------
body = {"scope": SCOPE, "contextDigest": first["contextDigest"], "basisDigest": first["basisDigest"], "idempotencyKey": "poc1-report-0001",
        "workspaceRevision": first["workspaceRevision"], "humanNotes": ["=HYPERLINK(\"x\")", "週報註記"]}
refused(lambda: review.create_snapshot(wid, "owner", {**body, "basisDigest": "stale", "idempotencyKey": "poc1-report-stale"}), (409,))
created = review.create_snapshot(wid, "owner", body)
saved = created["record"]
assert created["verified"] and not created["existing"] and saved["version"] == 1 and saved["sourceSha"] == SHA
assert review.create_snapshot(wid, "owner", {**body, "workspaceRevision": created["workspaceRevision"]})["existing"] is True
refused(lambda: review.create_snapshot(wid, "owner", {**body, "humanNotes": ["different"], "workspaceRevision": created["workspaceRevision"]}), (409,))
sid = saved["snapshotId"]
before = counts()
screen = review.snapshot(wid, "owner", sid, 1)
exports = {f: review.snapshot(wid, "owner", sid, 1, format_=f) for f in ("markdown", "csv", "pdf")}
assert screen["payloadDigest"] == saved["payloadDigest"] and all(e["payloadDigest"] == saved["payloadDigest"] and e["inputDigest"] == saved["inputDigest"] for e in exports.values())
rows = list(csv.DictReader(io.StringIO(exports["csv"]["content"])))
by_job = {e["publicationBinding"]["jobId"]: e for e in screen["nativeResults"]}
assert len(rows) == len(by_job) == 17
for row in rows:
    assert row["value"] == ("null" if by_job[row["jobId"]]["value"] is None else str(by_job[row["jobId"]]["value"])), row
assert rows[0]["humanNotes"].startswith("'=") and "週報註記" in exports["markdown"]["content"] and "週報註記" in exports["pdf"]["content"]
assert all("SYNTHETIC-SECRET" not in e["content"] for e in exports.values())
assert counts() == before
passed("A-D13 the report JSON (screen payload), Markdown, CSV and printable HTML share one snapshot id, payload and input digest; replay is idempotent; exports wrote nothing")

# ---- A-S01: no cross-workspace reach ----------------------------------------------------------------------------------
refused(lambda: review.snapshot(wid, "other", sid, 1), (403, 404))
refused(lambda: review.snapshot(other, "other", sid, 1), (404,))
refused(lambda: review.read(other, "other", SCOPE), (400,))
refused(lambda: review.read(wid, "owner", {**SCOPE, "workspaceId": other}), (400,))
refused(lambda: review.create_snapshot(other, "other", {**body, "idempotencyKey": "poc1-foreign-01"}), (400, 409))
assert "review" not in (service.get(wid, "owner")["state"].get("coworker") or {})
with connection() as db:
    db.execute("SET LOCAL ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (USERS["other"],))
    assert db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone() is None
passed("A-S01 another member or workspace cannot read, export, scope or create this report; generic workspace state and direct RLS reads do not expose it")

# ---- A-U01/A-U02: takeaway → existing Growth Loop experiment → versioned draft, nothing published -------------------
takeaway = saved["takeaways"][0]
assert takeaway["supportBindings"] and all(e["observationId"] for e in takeaway["supportBindings"])
assert takeaway["excludedByReason"] == first["coverage"]["excludedByReason"]
request = {"hypothesisId": hypothesis_id, "idempotencyKey": "poc1-experiment-01", "reviewSnapshot": {"snapshotId": sid, "version": 1, "takeawayId": takeaway["id"]}}
refused(lambda: loop.propose(wid, "owner", {**request, "idempotencyKey": "poc1-experiment-x", "reviewSnapshot": {**request["reviewSnapshot"], "takeawayId": "not-in-report"}}), (409,))
refused(lambda: loop.propose(wid, "owner", {**request, "idempotencyKey": "poc1-experiment-y", "reviewSnapshot": {**request["reviewSnapshot"], "version": 2}}), (404,))
experiment = loop.propose(wid, "owner", request)["record"]
eid = experiment["id"]
assert experiment["status"] == "proposed" and experiment["reviewSnapshot"] == {"snapshotId": sid, "version": 1, "payloadDigest": saved["payloadDigest"]}
assert experiment["takeawayId"] == takeaway["id"] and experiment["reviewBasisDigest"] == saved["basisDigest"]
assert loop.propose(wid, "owner", request)["record"]["id"] == eid
state = service.get(wid, "owner")["state"]
jobs_before, reviews_before = len(state["phase2"]["jobs"]), len(state["phase2"].get("reviews") or [])
draft = {"id": "poc1-draft", "revision": 1, "platform": "Instagram", "language": "en", "text": "Would you try a shorter practice note?",
         "needsReview": True, "unknowns": [], "sourceIds": [], "warnings": []}
mutate(lambda state: state.setdefault("variants", []).append(dict(draft)))
refused(lambda: loop.experiment_action(wid, "owner", eid, {"action": "attach_draft", "variantId": "poc1-draft", "variantRevision": 1}), (409,))   # not accepted yet
for action in ("accept", "prepare"):
    assert loop.experiment_action(wid, "owner", eid, {"action": action})["verified"]
refused(lambda: loop.experiment_action(wid, "other", eid, {"action": "attach_draft", "variantId": "poc1-draft", "variantRevision": 1}), (403, 404))
attached = loop.experiment_action(wid, "owner", eid, {"action": "attach_draft", "variantId": "poc1-draft", "variantRevision": 1})["record"]
assert attached["status"] == "preparing" and attached["generatedVariantIds"] == ["poc1-draft"] and attached["draftBindings"][0]["reviewSnapshot"]["snapshotId"] == sid
state = service.get(wid, "owner")["state"]
assert len(state["phase2"]["jobs"]) == jobs_before and len(state["phase2"].get("reviews") or []) == reviews_before
assert next(v for v in state["variants"] if v["id"] == "poc1-draft")["needsReview"] is True
summary = loop.summary(wid, "owner")
assert next(e for e in summary["experiments"] if e["id"] == eid)["draftState"] == [{"variantId": "poc1-draft", "revision": 1, "state": "current"}]
with connection() as db:
    events = db.execute("SELECT event,properties FROM public.pr_product_events WHERE workspace_id=%s AND event LIKE 'growth_experiment.%%'", (wid,)).fetchall()
assert ("growth_experiment.draft_attached", {"recordId": eid}) in [(n, p) for n, p in events] and all(set(p) == {"recordId"} for _, p in events), events
passed("A-U01/A-U02 the report takeaway (support, exclusions) proposes the existing Growth Loop test; owner accept + prepare, then an existing versioned draft is linked; no review, approval or publishing job is created")

# ---- A-U03: the existing approval model stays authoritative; an edited draft is a stale link --------------------------
def edit(state):
    variant = next(v for v in state["variants"] if v["id"] == "poc1-draft")
    variant.update(revision=2, text="An edited practice note.")
mutate(edit)
summary = loop.summary(wid, "owner")
assert next(e for e in summary["experiments"] if e["id"] == eid)["draftState"][0]["state"] == "revision_changed"
refused(lambda: loop.experiment_action(wid, "owner", eid, {"action": "attach_draft", "variantId": "poc1-draft", "variantRevision": 1}), (409,))
passed("A-U03 an edit after linking makes the link stale and a stale revision cannot be attached; approval itself stays with the existing manifest/revision check (tests/test_postriff_phase2.py)")

# ---- A-D02 scheduler half: a late read is closed and never stored under 24h; an on-time read records its read time ------
with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, "instagram", "native-late-read", "late-read", clock[0] - 30 * 3600, "verification", (("24h", DAY),))
    M.schedule(cur, wid, CONN, "instagram", "native-ontime-read", "ontime-read", clock[0] - DAY - 600, "verification", (("24h", DAY),))
    db.commit()
calls = len(transport.urls)
result = scheduler.tick()
with connection() as db:
    states = dict(db.execute("SELECT provider_post_id, status || ':' || coalesce(failure_class,'') FROM public.pr_metric_reads WHERE provider_post_id IN ('native-late-read','native-ontime-read')").fetchall())
    late_rows = db.execute("SELECT count(*) FROM public.pr_metric_observations WHERE provider_post_id='native-late-read'").fetchone()[0]
    ontime = db.execute("SELECT read_offset, extract(epoch from observed_at)::float8 FROM public.pr_metric_observations WHERE provider_post_id='native-ontime-read' AND metric='reach'").fetchone()
assert states == {"native-late-read": "unavailable:window_missed", "native-ontime-read": "done:"}, states
assert late_rows == 0 and len(transport.urls) == calls + 1 and "/native-ontime-read/insights" in transport.urls[-1], (late_rows, transport.urls)
assert ontime == ("24h", clock[0]) and result["missed"] == 1, (ontime, result)
passed("A-D02 scheduler: a reading past +24h+3h is closed as window_missed without a provider call or observation; an on-time reading is stored at its read time")

# ---- A-C05/A-S02: a downgraded scope stops display, export and pending reads; restored rights restore the report -----
with connection() as db:
    db.execute("UPDATE public.pr_encrypted_credentials SET scopes=%s WHERE workspace_id=%s AND connection_id=%s", (["instagram_business_basic"], wid, CONN))
refused(lambda: review.snapshot(wid, "owner", sid, 1), (403,))
refused(lambda: review.snapshot(wid, "owner", sid, 1, format_="csv"), (403,))
downgraded = review.read(wid, "owner", SCOPE)
assert downgraded["qualification"] == "not_comparable" and downgraded["groups"] == []
assert all(e["value"] is None and e["sourceRef"] is None and "scope_missing" in e["accessReasons"] for e in downgraded["nativeResults"])
assert downgraded["eligibility"][CONN]["userGrant"] == "downgraded" and downgraded["eligibility"][CONN]["repairAction"] == "reconnect"
refused(lambda: loop.experiment_action(wid, "owner", eid, {"action": "start"}), (409,))
with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, "instagram", "native-pending", "pending-read", clock[0] - 600, "verification", (("t0", 0),))
    db.commit()
grants, calls = OAuth.calls, len(transport.urls)
scheduler.tick()
with connection() as db:
    pending = db.execute("SELECT status, failure_class FROM public.pr_metric_reads WHERE provider_post_id='native-pending'").fetchone()
assert pending == ("cancelled", "not_eligible") and OAuth.calls == grants and len(transport.urls) == calls, pending
with connection() as db:
    db.execute("UPDATE public.pr_encrypted_credentials SET scopes=%s WHERE workspace_id=%s AND connection_id=%s", (SCOPES, wid, CONN))
assert review.snapshot(wid, "owner", sid, 1)["payloadDigest"] == saved["payloadDigest"]
passed("A-C05/A-S02 a scope downgrade withholds stored values, sources, aggregates and exports, blocks the bound experiment and cancels a pending read before any grant or provider call; the unchanged rights epoch restores the frozen report")

# ---- A-C09/A-S02: disconnect cancels pending reads and the report is no longer shown ---------------------------------
with connection() as db:
    db.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported',evidence='Disconnected by the customer.' WHERE workspace_id=%s AND connection_id=%s", (wid, CONN))
    db.execute("UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s", (wid, CONN))
mutate(lambda state: state["phase2"]["channels"][0].update(revoked=True))
with connection() as db, db.cursor() as cur:
    M.schedule(cur, wid, CONN, "instagram", "native-after-disconnect", "after-disconnect", clock[0] - 600, "verification", (("t0", 0),))
    db.commit()
grants, calls = OAuth.calls, len(transport.urls)
scheduler.tick()
with connection() as db:
    after = db.execute("SELECT status FROM public.pr_metric_reads WHERE provider_post_id='native-after-disconnect'").fetchone()[0]
assert after == "cancelled" and OAuth.calls == grants and len(transport.urls) == calls
refused(lambda: review.snapshot(wid, "owner", sid, 1, format_="markdown"), (410,))
gone = review.read(wid, "owner", SCOPE)
assert all(e["accessState"] == "revoked" and e["value"] is None for e in gone["nativeResults"]) and gone["qualification"] == "not_comparable"
passed("A-C09/A-S02 after disconnect pending reads are cancelled before any grant or provider call; the report and stored values are withheld")

# ---- A-S08: this path makes no model attempt, so it creates no usage rows ---------------------------------------------
final = counts()
assert all(final[t] == baseline[t] for t in ("pr_model_usage_events", "pr_usage_ledger", "pr_ai_call_events")), (baseline, final)
passed("A-S08 (scope): qualification, report, takeaway and draft link made zero model attempts and wrote zero usage or ledger rows")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres; synthetic providers and observations", "checks": checks}, indent=2))
