"""Signature Series on a disposable PostgreSQL (PRD R-SER-01/02; AC20, AC21, AC29).

The real hosted repository, the existing `pr_campaigns` projection (status CHECK, RLS), the product-event and audit
tables, the fact-expiry sweep's JSON SQL, source retraction through the real command, and an Evergreen automation
following a series through the real campaign worker with the synthetic writer. Disposable loopback database only:

    RAFII_PG_PORT=55883 PYTHONPATH=src:tests python scripts/rafii_pg_private.py postgres_series
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime import FixtureAgentRuntime
from postriff_phase2.campaign_worker import CampaignWorker
from postriff_phase2.coworker import flags, overlays
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.series import jobs, model as m
from postriff_phase2.series.service import ensure

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000004"      # rls.sql tombstones ...0002
THREE = "00000000-0000-0000-0000-000000000003"
FIVE = "00000000-0000-0000-0000-000000000005"
TOKENS = {"one": ONE, "two": TWO, "three": THREE, "five": FIVE}
clock = [1_800_000_000.0]
DAY = 86400
EN = ("Most adult beginners quit piano because they practise pieces, not skills. Spend five minutes on a single skill "
      "(reading intervals, steady pulse, or hand independence) before touching repertoire.")
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required.", 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: f"session-{token}-series-0123456789"
verify.auth_time = lambda token, principal: clock[0]


def denied(call, status, code=None):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        assert code is None or error.code == code, (error.code, str(error))
        return error
    raise AssertionError("call was accepted")


flags.attach({"RAFII_SERIES_ENABLED": "1", "RAFII_ADAPTIVE_SKILLS_ENABLED": "1"})
with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s),(%s),(%s)", (TWO, THREE, FIVE))
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
wa = service.bootstrap("one", "studio")["workspaceId"]
wb = service.bootstrap("two", "studio")["workspaceId"]
service.bootstrap("three", "studio")
service.bootstrap("five", "studio")
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active'),(%s,%s,'viewer','active')", (wa, THREE, wa, FIVE))
series = ensure(service)
keys = iter(f"pg-series-key-{i:04d}" for i in range(1000))


def command(workspace, token, fn):
    return service.repository.command(workspace, token, service.get(workspace, token)["revision"], fn)


def add(workspace, token, *, jobs_=(), sources=(), variants=()):
    def change(state, _actor):
        state["phase2"]["jobs"].extend(jobs_)
        state["sources"].extend(sources)
        state["variants"].extend(variants)
        return state
    command(workspace, token, change)


def post(job_id, text, days_old):
    return {"id": job_id, "state": "verified", "providerReference": f"ref-{job_id}", "verification": {"at": clock[0] - days_old * DAY},
            "manifest": {"platform": "LinkedIn", "payload": {"text": text, "language": "en"}}}


def variant(variant_id, text):
    return {"id": variant_id, "text": text, "platform": "LinkedIn", "language": "en", "revision": 1, "sourceIds": [], "unknowns": [], "warnings": [],
            "needsReview": False, "blockedByRetraction": False, "voiceRevision": None, "briefRevision": 1}


def act(method, series_id, *args, token="one", workspace=None, **payload):
    workspace = workspace or wa
    revision = series.get(workspace, token, series_id)["series"]["revision"]
    return getattr(series, method)(workspace, token, series_id, *args, {"idempotencyKey": next(keys), "expectedRevision": revision, **payload})


def state_a():
    return service.get(wa, "one")["state"]


add(wa, "one", jobs_=[post("job-old", EN, 45), post("job-other", "Scales and arpeggios: a weekly plan for adult learners who restart.", 90)],
    sources=[{"id": "src-1", "kind": "text", "title": "Studio facts", "text": "Lessons run on Saturdays.\nEach group has six learners.", "fingerprint": "fp-src-1",
              "active": True, "visibility": "private-local", "createdAt": clock[0] - 3 * DAY, "reviewedAt": "2026-09-28T12:00:00+00:00", "sourcePolicy": "publishable",
              "egressConsent": ["local", "cloud"], "useApprovals": [],
              "facts": [{"id": "f1", "text": "Lessons run on Saturdays.", "approved": True, "sourceId": "src-1", "locator": "paragraph 1"},
                        {"id": "f2", "text": "Each group has six learners.", "approved": True, "sourceId": "src-1", "locator": "paragraph 2"}]}])

# 1. Create: a campaign of kind series in the existing projection (status CHECK holds), readable only by members.
created = series.create(wa, "one", {"origin": {"kind": "post", "id": "job-old"}, "audienceQuestion": "How should adult beginners practise?", "goal": "Practice habits",
                                    "sourceIds": ["src-1"], "idempotencyKey": "pg-create-0001"})
sid = created["series"]["id"]
assert created["verified"] and [e["role"] for e in created["series"]["episodes"]] == ["explanation", "worked_example", "faq"], created["series"]["episodes"]
with connection() as db:
    row = db.execute("SELECT status, body->>'kind', version, body#>>'{series,revision}' FROM public.pr_campaigns WHERE id=%s", (sid,)).fetchone()
    assert row == ("active", "series", 1, "1"), row
for user, expected in ((ONE, 1), (TWO, 0)):
    with connection() as db:   # the browser role sees its own workspace's rows only (forced RLS of 018)
        db.execute("SELECT set_config('request.jwt.claim.sub', %s, false)", (user,))
        db.execute("SET ROLE authenticated")
        assert db.execute("SELECT count(*) FROM public.pr_campaigns WHERE id=%s", (sid,)).fetchone()[0] == expected, user
checks.append("series is a pr_campaigns row (kind series, status active, version 1) visible to members only")

# 2. Revision and idempotency conflicts against the real repository.
first, second = created["series"]["episodes"][0]["id"], created["series"]["episodes"][1]["id"]
body = {"idempotencyKey": "pg-approve-0001", "expectedRevision": 1}
assert series.approve(wa, "one", sid, first, dict(body))["verified"]
revision = service.get(wa, "one")["revision"]
assert series.approve(wa, "one", sid, first, dict(body))["replayed"] and service.get(wa, "one")["revision"] == revision
denied(lambda: series.approve(wa, "one", sid, second, dict(body)), 409, "idempotency_conflict")
denied(lambda: series.plan(wa, "one", sid, {"idempotencyKey": "pg-plan-stale-01", "expectedRevision": 1, "count": 2}), 409, "revision_conflict")
assert series.create(wa, "one", {"origin": {"kind": "post", "id": "job-old"}, "audienceQuestion": "How should adult beginners practise?", "goal": "Practice habits",
                                 "sourceIds": ["src-1"], "idempotencyKey": "pg-create-0001"})["replayed"]
denied(lambda: series.create(wa, "one", {"origin": {"kind": "post", "id": "job-old"}, "audienceQuestion": "Q", "goal": "G", "idempotencyKey": "pg-create-0002"}), 409, "duplicate_series")
with connection() as db:
    events = db.execute("SELECT event, properties, dedupe_key FROM public.pr_product_events WHERE workspace_id=%s AND event='series.episode_accepted'", (wa,)).fetchall()
    assert events == [("series.episode_accepted", {"role": "explanation", "episode": 1}, f"series.episode_accepted:{first}:1")], events
    kinds = [r[0] for r in db.execute("SELECT kind FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE 'series.%%' ORDER BY at, kind", (wa,)).fetchall()]
    assert kinds == ["series.created", "series.episode_approved"], kinds
    assert "practise" not in json.dumps(db.execute("SELECT json_agg(meta) FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE 'series.%%'", (wa,)).fetchone()[0])
checks.append("revision/idempotency conflicts, replay without a second write, one episode-accepted event, content-free audit")

# 3. Tenancy and roles: the path workspace selects, membership grants.
denied(lambda: series.get(wa, "two", sid), 403)
denied(lambda: series.get(wb, "two", sid), 404)
add(wb, "two", variants=[variant("foreign-draft", "A draft that lives in workspace B.")])
denied(lambda: act("link", sid, first, variantId="foreign-draft", acknowledgedWarnings=[]), 404)
assert series.get(wa, "five", sid)["series"]["id"] == sid
denied(lambda: act("plan", sid, token="five", count=2), 403)
editor = act("decide", sid, created["series"]["episodes"][2]["id"], token="three", decision="accept")["result"]
assert (editor["storage"], editor["reason"]) == ("series", "owner_required"), editor
checks.append("cross-tenant series and draft ids are unavailable; viewers read only; an editor's decision stays on the series")

# 4. Duplicate refusal, near-duplicate acknowledgement, expiry gate through the real sweep SQL.
add(wa, "one", variants=[variant("copy", EN.upper()), variant("near", EN.replace("five minutes", "ten minutes")), variant("fresh", "Tonight: one five-minute drill, then your piece.")])
denied(lambda: act("link", sid, first, variantId="copy", acknowledgedWarnings=[]), 409, "duplicate_episode")
check = series.draft_check(wa, "one", sid, first, "near")
denied(lambda: act("link", sid, first, variantId="near", acknowledgedWarnings=[]), 409, "warnings_unacknowledged")
act("link", sid, first, variantId="near", acknowledgedWarnings=[w["id"] for w in check["warnings"]])
assert next(v for v in state_a()["variants"] if v["id"] == "near")["seriesEpisode"]["originId"] == "job-old"
assert jobs.tick(service, time.monotonic() + 10)["workspaces"] == 0          # nothing due yet: no write
revision = service.get(wa, "one")["revision"]
clock[0] += 400 * DAY
swept = jobs.tick(service, time.monotonic() + 10)
assert swept == {"status": "ok", "workspaces": 1, "series": 1, "gatedDrafts": 1}, swept
near = next(v for v in state_a()["variants"] if v["id"] == "near")
assert near["needsReview"] and near["unknowns"][0].startswith(m.UNKNOWN_PREFIX), near
assert service.get(wa, "one")["revision"] == revision + 1
assert jobs.tick(service, time.monotonic() + 10)["workspaces"] == 0          # moved on: not picked again
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s AND kind='series.fact_review_swept'", (wa,)).fetchone()[0] == 1
view = series.get(wa, "one", sid)["series"]
for claim_id in view["episodes"][0]["claimIds"]:
    act("claim", sid, claim_id, action="reviewed", reviewBy=time.strftime("%Y-%m-%d", time.gmtime(clock[0] + 200 * DAY)))
assert not any(u.startswith(m.UNKNOWN_PREFIX) for u in next(v for v in state_a()["variants"] if v["id"] == "near")["unknowns"])
checks.append("exact duplicate refused, near duplicate acknowledged, expired claim gated by the real sweep SQL once, lifted after review")

# 5. Deleted (withdrawn) source propagates through the real retraction command and the sweep's watch list.
reviewed_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(clock[0]))
add(wa, "one", sources=[{"id": "src-2", "kind": "text", "title": "Timetable", "text": "Beginner classes start at 10:00.\nEach class lasts 45 minutes.",
                         "fingerprint": "fp-src-2", "active": True, "visibility": "private-local", "createdAt": clock[0] - DAY, "reviewedAt": reviewed_at,
                         "sourcePolicy": "publishable", "egressConsent": ["local", "cloud"], "useApprovals": [],
                         "facts": [{"id": "g1", "text": "Beginner classes start at 10:00.", "approved": True, "sourceId": "src-2", "locator": "paragraph 1"},
                                   {"id": "g2", "text": "Each class lasts 45 minutes.", "approved": True, "sourceId": "src-2", "locator": "paragraph 2"}]}])
src_series = series.create(wa, "one", {"origin": {"kind": "source", "id": "src-2"}, "audienceQuestion": "What do lessons look like?", "goal": "Studio basics",
                                       "idempotencyKey": "pg-create-src-2"})["series"]
act("approve", src_series["id"], src_series["episodes"][0]["id"])
act("link", src_series["id"], src_series["episodes"][0]["id"], variantId="fresh", acknowledgedWarnings=[])
assert jobs.tick(service, time.monotonic() + 10)["workspaces"] == 0
before_job = next(j for j in state_a()["phase2"]["jobs"] if j["id"] == "job-old")
service.mutate(wa, "one", service.get(wa, "one")["revision"], "retract_source", {"sourceId": "src-2"})
swept = jobs.tick(service, time.monotonic() + 10)
assert swept["workspaces"] == 1 and swept["gatedDrafts"] >= 1, swept
fresh = next(v for v in state_a()["variants"] if v["id"] == "fresh")
assert any(u.startswith(m.UNKNOWN_PREFIX) and "withdrawn" in u for u in fresh["unknowns"]), fresh["unknowns"]
view = series.get(wa, "one", src_series["id"])["series"]
assert not view["origin"]["available"] and view["episodes"][0]["factReasons"] == ["source_unavailable"], view["episodes"][0]
assert next(j for j in state_a()["phase2"]["jobs"] if j["id"] == "job-old") == before_job
checks.append("a withdrawn source makes its claims unavailable and gates the linked draft within one sweep; originals unchanged")

# 6. Preferences in workspace memory: an owner's rejection is a scoped strategy overlay, honoured, then revoked.
faq = next(e for e in series.get(wa, "one", sid)["series"]["episodes"] if e["role"] == "faq" and e["workflowState"] == "planned")
decided = act("decide", sid, faq["id"], decision="reject")["result"]
assert decided["storage"] == "overlay"
item = next(i for i in overlays.scoped_items(state_a(), "strategy", seriesId=sid) if i["id"] == decided["overlayId"])
assert item["status"] == "active" and item["scope"] == {"seriesId": sid}
replanned = act("plan", sid, count=4)["series"]
assert faq["angle"]["key"] not in [e["angle"]["key"] for e in replanned["episodes"] if e["workflowState"] != "skipped"]
denied(lambda: act("revoke", sid, decided["id"], token="three"), 403)
act("revoke", sid, decided["id"])
assert next(i for i in overlays.scoped_items(state_a(), "strategy", seriesId=sid) if i["id"] == decided["overlayId"])["status"] == "retired"
checks.append("owner decisions persist as scoped strategy overlays, shape the next plan, and only an owner revokes them")

# 7. Pagination over the real state, then the projection keeps archived series as cancelled campaigns.
listed = series.list(wa, "one", limit=1)
assert len(listed["items"]) == 1 and listed["nextCursor"]
assert [i["id"] for i in series.list(wa, "one", limit=1, cursor=listed["nextCursor"])["items"]] == [sid]
act("set_status", src_series["id"], status="archived")
with connection() as db:
    assert db.execute("SELECT status FROM public.pr_campaigns WHERE id=%s", (src_series["id"],)).fetchone()[0] == "cancelled"
checks.append("cursor pages are deterministic; archiving maps to the allowed campaign status")

# 8. Evergreen follows the series through the real campaign worker: the approved episode, once.
from consumer_fixtures import approve_budgets
approve_budgets(connection, wa)
requests_seen = []


class Recording(FixtureAgentRuntime):
    def start_turn(self, request, emit):
        requests_seen.append(request)
        return super().start_turn(request, emit)


runtime = Recording()
service.ideas.runtime = runtime
service.ideas.runtimes = [runtime]
for claim in series.get(wa, "one", sid)["series"]["claims"]:   # a year has passed: re-check the facts before reuse
    if claim["freshness"]["state"] == "expired":
        act("claim", sid, claim["id"], action="reviewed", reviewBy=time.strftime("%Y-%m-%d", time.gmtime(clock[0] + 200 * DAY)))
episodes = series.get(wa, "one", sid)["series"]["episodes"]
nxt = next(e for e in episodes if e["workflowState"] == "planned" and e["canApprove"])
act("approve", sid, nxt["id"])
saved = service.mutate(wa, "one", service.get(wa, "one")["revision"], "raffi_recurrence_save", {
    "name": "Series follow-up", "goal": "Practice habits, one episode at a time", "audience": "Adult students",
    "schedule": {"weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], "localTime": "09:00", "timeZone": "UTC"},
    "include": {"evergreen": {"minAgeDays": 30, "seriesId": sid}}, "destinations": [{"platform": "LinkedIn", "language": "en"}],
    "route": "deterministic-preview", "maxCostUsdMicro": 0})
task = saved["state"]["raffi"]["campaignPlanning"]["recurringTasks"][-1]
service.mutate(wa, "one", service.get(wa, "one")["revision"], "raffi_recurrence_activate", {"taskId": task["id"], "confirmed": True})
current = lambda: next(t for t in state_a()["raffi"]["campaignPlanning"]["recurringTasks"] if t["id"] == task["id"])
clock[0] = current()["nextOccurrence"]["scheduledFor"] + 1
assert CampaignWorker(service).tick()["state"] == "completed"
run = [o for o in state_a()["raffi"]["campaignPlanning"]["occurrences"] if o["taskId"] == task["id"]][-1]
assert run["evergreen"]["episodeId"] == nxt["id"] and run["evergreen"]["jobId"] == "job-old", run["evergreen"]
assert "approved series episode" in requests_seen[-1]["idea"], requests_seen[-1]["idea"][:300]
assert m.episode_of(m.find(state_a(), sid)["series"], nxt["id"])["state"] == "drafting"
assert "episode:" + nxt["id"] in current()["evergreenUsed"]
clock[0] = current()["nextOccurrence"]["scheduledFor"] + 1
assert CampaignWorker(service).tick()["state"] == "completed"
run = [o for o in state_a()["raffi"]["campaignPlanning"]["occurrences"] if o["taskId"] == task["id"]][-1]
assert run["evergreen"] == {}, run["evergreen"]                                  # never the same episode twice
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_campaigns WHERE workspace_id=%s AND body->>'kind'='series'", (wa,)).fetchone()[0] == 2
checks.append("an evergreen automation following the series drafts its approved episode through the real worker, once")

print(json.dumps({"execution": "disposable PostgreSQL; synthetic writer; no provider or network", "checks": checks}, indent=1))
print(f"PASS: {len(checks)} Signature Series checks")
