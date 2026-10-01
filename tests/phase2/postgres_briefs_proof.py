"""G4-LOOP on a disposable PostgreSQL: opportunity briefs, proof revisions and the next-week strategy loop.

Real SQL, real repository/notification/weekly services; listening and Radar records are stored fixtures, trends are
not allow-listed, every paid path (Radar quote/start/advance and source search, research search, HTTP) is patched to
fail the test if reached. Covers AC24, AC25, AC26, AC27, AC34, migration/RLS, cross-tenant and pagination.
"""
import copy
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.coworker import flags, growth_loop, runtime, research_broker
from postriff_phase2.growth.service import GrowthService
from postriff_phase2.notifications.service import NotificationService
from postriff_phase2.radar.service import Radar
from postriff_phase2.radar.sources import Sources
from postriff_phase2.briefs import composer
from postriff_phase2.briefs.http import ensure as briefs_ensure
from postriff_phase2.proof.http import ensure as proof_ensure
from postriff_phase2.proof import model, strategy

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
USERS = {name: str(uuid.uuid4()) for name in ("owner", "editor", "viewer", "other")}
NY = ZoneInfo("America/New_York")
DAY = 86400


def at(zone, *parts):
    return datetime(*parts, tzinfo=zone if isinstance(zone, ZoneInfo) else ZoneInfo(zone)).timestamp()


clock = [at("UTC", 2026, 10, 7, 15, 0)]
connection = lambda: psycopg.connect(DSN)  # noqa: E731


def verify(token):
    if token not in USERS:
        raise AlphaError("Verified session required.", 401)
    return USERS[token]


class Mail:
    name = "test_mail"

    def send(self, message):
        return {"id": "mail-" + uuid.uuid4().hex[:8]}


VALUES = {**{name: "1" for name in flags.FLAGS}, "RAFII_OPPORTUNITY_BRIEF_ENABLED": "1", "RAFII_PROOF_V2_ENABLED": "1"}
VALUES.pop("RAFII_WEB_PUSH_ENABLED")
VALUES.pop("RAFII_SMS_ENABLED")
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
service.notifications = NotificationService(service, VALUES, email_transport=Mail(), clock=lambda: clock[0])
service.repository.effects.append(service.notifications.effect)
runtime.attach(service, VALUES)
service.growth = GrowthService(service, env={"POSTRIFF_GROWTH": "1", "POSTRIFF_RADAR": "1"}, clock=lambda: clock[0])
briefs, proofs = briefs_ensure(service), proof_ensure(service)
with connection() as db:
    for user in USERS.values():
        db.execute("INSERT INTO auth.users VALUES(%s)", (user,))
wid = service.bootstrap("owner", "studio")["workspaceId"]
wid2 = service.bootstrap("other", "studio")["workspaceId"]
service.bootstrap("editor", "studio")
service.bootstrap("viewer", "studio")
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active'),(%s,%s,'viewer','active'),(%s,%s,'editor','active')",
               (wid, USERS["editor"], wid, USERS["viewer"], wid2, USERS["owner"]))


def passed(name):
    print("PASS briefs-proof: " + name, flush=True)


def sql(query, *args):
    with connection() as db:
        cur = db.execute(query, args)
        return cur.fetchall() if cur.description else []


def refused(fn, status, code=None):
    try:
        fn()
    except AlphaError as error:
        assert error.status == status, (status, error.status, str(error))
        assert code is None or error.code == code, (code, error.code, str(error))
        return error
    raise AssertionError(f"expected a {status} refusal")


def raw_state(workspace):
    return sql("SELECT state FROM public.pr_workspaces WHERE id=%s", workspace)[0][0]


def patch_state(workspace, fn):
    with connection() as db:
        state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace,)).fetchone()[0]
        fn(state)
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s", (json.dumps(state), workspace))


def iso(epoch):
    return datetime.fromtimestamp(epoch, ZoneInfo("UTC")).isoformat()


def op(ident, title, now, *, confidence="high", age=1.0, status="open", injection=False):
    created = now - age * DAY
    return {"id": ident, "watchlistId": "wl1", "title": title, "url": f"https://news.example/{ident}", "status": status, "confidence": confidence,
            "relevance": 0.8, "novelty": 0.5, "freshness": 0.9, "score": 0.8, "createdAt": created, "expiresAt": created + 10 * DAY,
            "why": "Matches “adult piano practice”.", "proposedAction": "Draft a post that responds to it",
            "note": "A search result is a lead; read the source before relying on it.",
            "evidence": [{"url": f"https://news.example/{ident}", "snippet": "fixture snippet",
                          "provenance": {"provider": "fixture", "kind": "fixture", "retrievedAt": created, "publishedAt": iso(created - DAY),
                                         "injectionFlags": [{"rule": "injection.0"}] if injection else []}}]}


def listening(workspace, ops):
    def change(state):
        coworker = state.setdefault("coworker", {})
        coworker["listening"] = {"watchlists": [{"id": "wl1", "query": "adult piano practice", "goal": "teach adults", "sources": ["public_web"], "active": True,
                                                 "createdAt": clock[0], "updatedAt": clock[0], "lastRunAt": clock[0]}],
                                 "opportunities": ops}
    patch_state(workspace, change)


# Paid or external paths: any call fails the test.
PAID = mock.Mock(side_effect=AssertionError("paid or external I/O reached from a stored-only path"))
for target in (mock.patch.object(Radar, "quote", PAID), mock.patch.object(Radar, "start", PAID), mock.patch.object(Radar, "advance", PAID),
               mock.patch.object(Sources, "search", PAID), mock.patch.object(Sources, "verify", PAID),
               mock.patch.object(research_broker.ResearchBroker, "search_items", PAID), mock.patch.object(research_broker.ResearchBroker, "fetch_item", PAID),
               mock.patch("postriff_phase2.research._http", PAID)):
    target.start()

# --- workspace fixture: channels, an active goal, own material -------------------------------------------------------
def base(state):
    verified = {"configured": True, "revoked": False, "expiresAt": clock[0] + 400 * DAY, "identityVerified": True, "capabilityVerified": True, "verifiedAt": clock[0]}
    state.setdefault("phase2", {})["channels"] = [{"id": "ch1", "platform": "Threads", "account": "@studio", "language": "en", **verified},
                                                  {"id": "ch2", "platform": "LinkedIn", "account": "Studio page", **verified}]
    state.setdefault("coworker", {})["growthLoop"] = {"goals": [{"id": "gg_goal", "name": "Teach adults piano", "goalType": "consistency", "primaryMetric": "verified_posts",
                                                                 "status": "active", "createdAt": clock[0] - 6 * DAY, "channelId": None}],
                                                      "experiments": [], "proofs": []}
    state.setdefault("sources", []).append({"id": "src-material", "kind": "text", "title": "Practice routine handout", "text": "Three short sessions.",
                                            "fingerprint": "f" * 64, "visibility": "private-local", "active": True, "createdAt": clock[0] - 10 * DAY,
                                            "facts": [{"id": "fact1", "text": "Three short sessions a day.", "approved": True, "sourceId": "src-material"}]})
    state.setdefault("brandHub", {})["subject"] = "Piano lessons for adults"


patch_state(wid, base)
def identity(state):
    """Voice, brand and learned preferences; a one-time locale-migration stamp in `learning` is not a preference."""
    learning = state.get("learning") or {}
    return copy.deepcopy({"speaker": state.get("speaker"), "brandHub": state.get("brandHub"), "overlays": (state.get("coworker") or {}).get("overlays"),
                          "learning": {k: learning.get(k) for k in ("active", "retired", "revision", "enabled")}})


identity_before = identity(raw_state(wid))

# === AC24: stored-only composition, at most three sourced items, GET writes nothing ===================================
now = clock[0]
listening(wid, [op("L1", "How do adult beginners keep a practice routine?", now), op("L2", "Metronome drills that beginners actually enjoy", now),
                op("L3", "Sight reading tips", now, confidence="low"), op("L4", "Recital nerves for adults", now, age=9),
                op("L5", "An older dismissed lead", now, status="dismissed"), op("L6", "Pedal technique myths", now, injection=True)])
state = raw_state(wid)
radar_body = {"query": "piano practice", "finishedAt": now - 3600, "notice": "Signals for your review. Source coverage and causal impact are not established.",
              "opportunities": [
                  {"id": "R1", "title": "New research on spaced piano practice", "eligible": True, "evidenceIds": ["e1"], "angle": "What spacing means for a busy adult learner.",
                   "expiresAt": now + 20 * DAY, "confidenceReasons": ["Source coverage is incomplete."],
                   "evidence": [{"id": "e1", "url": "https://research.example/spacing", "title": "Spacing study", "source": "news", "publishedAt": now - 2 * DAY,
                                 "retrievedAt": now - 3600, "excerpt": "A short permitted excerpt.", "rights": {"displayLink": True, "displayExcerpt": True}}]},
                  {"id": "R2", "title": "Scale warmups for busy adults", "eligible": True, "evidenceIds": ["e2"], "angle": "Five-minute warmups you already teach.",
                   "expiresAt": now + 20 * DAY, "evidence": [{"id": "e2", "url": "https://blog.example/warmups", "title": "Warmups", "source": "news",
                                                            "publishedAt": now - DAY, "retrievedAt": now - 3600, "rights": {"displayLink": True}}]},
                  {"id": "R3", "title": "Not judged useful", "eligible": False, "evidenceIds": ["e3"], "expiresAt": now + 20 * DAY, "evidence": []}]}
radar_run = sql("""INSERT INTO public.pr_radar_runs(workspace_id,request_key,created_by,status,fingerprint,context_digest,body,created_at,expires_at)
                   VALUES(%s,'fixture-scan',%s,'completed','fp',%s,%s::jsonb,to_timestamp(%s),to_timestamp(%s)) RETURNING id::text""",
                wid, USERS["owner"], Radar.context(state), json.dumps(radar_body), now - 3600, now + 30 * DAY)[0][0]
revision_before = sql("SELECT revision FROM public.pr_workspaces WHERE id=%s", wid)[0][0]
brief = briefs.current(wid, "owner")
items = brief["edition"]["items"]
assert len(items) == 3, items
assert [i["sourceRef"] for i in items] == ["L1", f"{radar_run}:R1", f"{radar_run}:R2"], [i["sourceRef"] for i in items]
for item in items:
    assert item["dataMode"] == "stored" and item["evidence"] and item["retrievedAt"] and item["coverage"]["availability"] == "available", item
    assert item["relevance"]["reason"] and item["angle"]["text"] and item["effort"] in composer.EFFORTS and item["action"]["kind"] in ("save_idea", "accept"), item
assert len({i["angle"]["text"] for i in items}) == 3
assert items[1]["excerpt"] == "A short permitted excerpt." and items[0]["excerpt"] is None
assert brief["excluded"] == {"low_confidence": 1, "stale": 1, "unsafe_source_text": 1, "over_limit": 1}, brief["excluded"]
coverage = {c["source"]: c for c in brief["coverage"]}
assert coverage["trends"]["state"] == "unavailable" and coverage["trends"]["reason"] == "trends_not_enabled"
assert coverage["listening"]["selected"] == 1 and coverage["radar"]["selected"] == 2 and brief["dataState"] == "partial"
assert brief["edition"]["persisted"] is False and brief["edition"]["id"] is None and brief["canAct"] is True
assert sql("SELECT count(*) FROM public.pr_brief_editions")[0][0] == 0
assert sql("SELECT revision FROM public.pr_workspaces WHERE id=%s", wid)[0][0] == revision_before
assert briefs.current(wid, "owner")["edition"]["materialDigest"] == brief["edition"]["materialDigest"]
viewer = briefs.current(wid, "viewer")
assert viewer["canAct"] is False and len(viewer["edition"]["items"]) == 3
refused(lambda: briefs.current(wid, "other"), 403)
refused(lambda: briefs.current(wid, "prt_token"), 403)
assert not PAID.called
passed("AC24 three sourced stored items with source, times, coverage, relevance, distinct angle, effort and one action; GET writes nothing, no paid I/O")

# Unsupported coverage: every source off → zero items, nothing fabricated.
with mock.patch.object(flags, "_values", {**VALUES, "RAFII_LISTENING_ENABLED": ""}), mock.patch.object(service.growth, "env", {}):
    empty = briefs.current(wid, "owner")
assert empty["edition"]["items"] == [] and empty["dataState"] == "unavailable", empty
assert {c["reason"] for c in empty["coverage"]} == {"trends_not_enabled", "listening_not_enabled", "radar_not_enabled"}
fresh = briefs.current(wid2, "other")
assert fresh["edition"]["items"] == [] and fresh["dataState"] == "partial"
passed("AC24 zero is valid: unsupported or empty coverage composes no opportunity")

# === Brief actions: reasons, outcome references, idempotency, versions, permissions =====================================
digest = brief["edition"]["materialDigest"]
by_ref = {i["sourceRef"]: i for i in items}
R1, R2, L1 = by_ref[f"{radar_run}:R1"], by_ref[f"{radar_run}:R2"], by_ref["L1"]
refused(lambda: briefs.action(wid, "owner", R2["id"], {"action": "dismiss", "reasonCode": "not_now", "idempotencyKey": "dismiss-r2-0001", "materialDigest": "0" * 64}),
        409, "revision_conflict")
refused(lambda: briefs.action(wid, "owner", R2["id"], {"action": "not_relevant", "idempotencyKey": "nr-r2-000001", "materialDigest": digest}), 400, "reason_required")
refused(lambda: briefs.action(wid, "viewer", R2["id"], {"action": "dismiss", "reasonCode": "not_now", "idempotencyKey": "dismiss-viewer1", "materialDigest": digest}), 403)
refused(lambda: briefs.action(wid, "other", R2["id"], {"action": "dismiss", "reasonCode": "not_now", "idempotencyKey": "dismiss-other01", "materialDigest": digest}), 403)
dismissed = briefs.action(wid, "owner", R2["id"], {"action": "dismiss", "reasonCode": "not_now", "idempotencyKey": "dismiss-r2-0002", "materialDigest": digest})
edition_id = dismissed["edition"]["id"]
assert dismissed["verified"] and dismissed["edition"]["revision"] == 1 and dismissed["action"]["reasonCode"] == "not_now"
assert briefs.action(wid, "owner", R2["id"], {"action": "dismiss", "reasonCode": "not_now", "idempotencyKey": "dismiss-r2-0002", "materialDigest": digest})["replayed"]
refused(lambda: briefs.action(wid, "owner", R2["id"], {"action": "dismiss", "reasonCode": "other", "idempotencyKey": "dismiss-r2-0002", "materialDigest": digest}),
        409, "idempotency_conflict")
refused(lambda: briefs.action(wid, "owner", R2["id"], {"action": "dismiss", "reasonCode": "other", "idempotencyKey": "dismiss-r2-0003", "editionId": edition_id}),
        409, "restore_first")
saved = briefs.action(wid, "owner", L1["id"], {"action": "save_idea", "idempotencyKey": "save-l1-00001", "editionId": edition_id})
source_id = saved["outcome"]["sourceId"]
state = raw_state(wid)
source = next(s for s in state["sources"] if s["id"] == source_id)
assert source["origin"]["kind"] == "opportunity_brief" and source["origin"]["editionId"] == edition_id and source["needsFactCheck"] is True
assert not any(f.get("approved") for f in source.get("facts") or [])
assert next(o for o in state["coworker"]["listening"]["opportunities"] if o["id"] == "L1")["status"] == "acted"
radar_saved = briefs.action(wid, "owner", R1["id"], {"action": "save_idea", "idempotencyKey": "save-r1-00001", "editionId": edition_id})
radar_source = radar_saved["outcome"]["sourceId"]
assert next(s for s in raw_state(wid)["sources"] if s["id"] == radar_source)["radarEvidence"]["scanId"] == radar_run
assert sql("SELECT body->'opportunities'->0->>'sourceId' FROM public.pr_radar_runs WHERE id=%s", radar_run)[0][0] == radar_source
refused(lambda: briefs.action(wid, "owner", L1["id"], {"action": "dismiss", "reasonCode": "not_now", "idempotencyKey": "dismiss-l1-0001", "editionId": edition_id}),
        409, "already_acted")
refused(lambda: briefs.action(wid, "owner", L1["id"], {"action": "restore", "idempotencyKey": "restore-l1-001", "editionId": edition_id}), 409, "already_acted")
restored = briefs.action(wid, "owner", R2["id"], {"action": "restore", "idempotencyKey": "restore-r2-001", "editionId": edition_id})
assert restored["action"]["action"] == "restore"
after = briefs.current(wid, "owner")
assert {i["sourceRef"] for i in after["edition"]["items"]} == {"L2", f"{radar_run}:R2"}, after["edition"]["items"]
assert after["edition"]["materialDigest"] != digest and after["edition"]["persisted"] is False
history = briefs.edition(wid, "owner", edition_id)
assert [a["action"] for a in history["actions"]] == ["dismiss", "save_idea", "save_idea", "restore"]
assert {a["outcomeRefs"][0]["id"] for a in history["actions"] if a["outcomeRefs"]} == {source_id, radar_source}
assert sql("SELECT count(*) FROM public.pr_product_events WHERE workspace_id=%s AND event='brief.action'", wid)[0][0] == 4
assert sql("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s AND kind='brief.item_action'", wid)[0][0] == 4
refused(lambda: briefs.edition(wid, "editor", edition_id), 404)          # a brief belongs to its recipient
# Decided items stay reachable after they leave the open list: the saved ideas keep their outcome link, and a
# "not relevant" item can be restored from the stored edition it came from.
handled = {i["sourceRef"]: i for i in after["edition"]["handled"]}
assert set(handled) == {"L1", f"{radar_run}:R1"}, after["edition"]["handled"]
assert handled["L1"]["editionId"] == edition_id and handled["L1"]["decision"]["action"] == "save_idea"
assert handled["L1"]["decision"]["outcomeRefs"] == [{"type": "source", "id": source_id}]
assert handled[f"{radar_run}:R1"]["decision"]["outcomeRefs"] == [{"type": "source", "id": radar_source}]
L2 = next(i for i in after["edition"]["items"] if i["sourceRef"] == "L2")
briefs.action(wid, "owner", L2["id"], {"action": "not_relevant", "reasonCode": "wrong_topic", "idempotencyKey": "nr-l2-0000001", "materialDigest": after["edition"]["materialDigest"]})
hidden = briefs.current(wid, "owner")
assert "L2" not in {i["sourceRef"] for i in hidden["edition"]["items"]}
l2 = next(i for i in hidden["edition"]["handled"] if i["sourceRef"] == "L2")
assert (l2["decision"]["action"], l2["decision"]["reasonCode"]) == ("not_relevant", "wrong_topic") and l2["editionId"] != edition_id
briefs.action(wid, "owner", l2["id"], {"action": "restore", "idempotencyKey": "restore-l2-0001", "editionId": l2["editionId"]})
back = briefs.current(wid, "owner")
assert "L2" in {i["sourceRef"] for i in back["edition"]["items"]} and all(i["sourceRef"] != "L2" for i in back["edition"]["handled"])
assert sql("SELECT count(*) FROM public.pr_product_events WHERE workspace_id=%s AND event='brief.action'", wid)[0][0] == 6
assert not PAID.called
passed("actions keep reason codes and outcome sources; decided items stay reachable (outcome link, restore); replay, key and version conflicts, recipient-only reads, viewer and cross-tenant refusals")

# === AC26 / AC34: proof revisions reconcile to evidence; late data appends; prior kept; immature and in-progress =======
clock[0] = at(NY, 2026, 10, 14, 12, 0)   # Wednesday; the latest completed NY week is Mon 5 – Mon 12 October
recipe = service.coworker.weekly_save_recipe(wid, "owner", {"name": "Studio week", "goals": ["Teach adults piano"], "timeZone": "America/New_York",
                                                            "contentMix": {"tutorial_how_to": 1.0}, "maxCostUsdMicroPerWeek": 0,
                                                            "destinations": [{"channelId": "ch1", "postsPerWeek": 2, "language": "en"}]})["recipe"]
week_start = at(NY, 2026, 10, 5)


def fixtures(state):
    state["phase2"]["jobs"] = [
        {"id": "job-verified", "state": "verified", "providerReference": "p1", "variantId": "v-job", "approvedAt": week_start + DAY,
         "verification": {"at": week_start + DAY + 600}, "manifest": {"channelId": "ch1", "variantId": "v-job"}},
        {"id": "job-failed", "state": "failed", "providerReference": None, "approvedAt": week_start + DAY, "manifest": {"channelId": "ch1", "variantId": "v-failed"}},
        {"id": "job-next-week", "state": "verified", "providerReference": "p3", "verification": {"at": week_start + 8 * DAY}, "manifest": {"channelId": "ch1"}}]
    # A Queue review as Phase2Store writes it (status, manifest); its approval is counted through the job it created.
    state["phase2"]["reviews"] = [{"id": "rev1", "status": "approved", "manifest": {"variantId": "v-job", "channelId": "ch1"}, "digest": "d" * 64,
                                   "createdAt": week_start + DAY}]
    state["coworker"]["weekly"]["weeks"] = [{"id": "wk_fixture", "recipeId": recipe["id"], "weekOf": "2026-10-05", "state": "ready_for_review", "slots": [
        {"id": "sl_accepted", "status": "accepted", "variantId": "v-slot", "acceptedAt": week_start + DAY, "localTime": "2026-10-06T09:00", "timeZone": "America/New_York"},
        {"id": "sl_blocked", "status": "needs_source", "localTime": "2026-10-08T09:00", "timeZone": "America/New_York"},
        {"id": "sl_skipped", "status": "rejected", "localTime": "2026-10-09T09:00", "timeZone": "America/New_York"}]}]
    state["coworker"]["growthLoop"]["experiments"] = [{"id": "ge_fixture", "status": "complete", "decision": None, "hypothesisRevision": 1, "dimension": "opening",
                                                       "expiresAt": clock[0] + 40 * DAY, "updatedAt": week_start + 3 * DAY, "createdAt": week_start,
                                                       "cohort": {"provider": "threads", "connectionId": "ch1", "language": "en", "contentTypeId": "tutorial_how_to"},
                                                       "result": {"supportedFactor": "question"}}]


patch_state(wid, fixtures)
ledger = {}
with connection() as db:
    for name, confidence, active_seconds in (("estimated", "estimated", None), ("measured", "measured", 120)):
        saved_seconds = 480 if active_seconds is None else 360
        ledger[name] = db.execute("""INSERT INTO public.pr_time_savings_ledger(workspace_id,beneficiary_user_id,task_kind,outcome_kind,outcome_ref,dedupe_key,baseline_seconds,
                                        active_seconds,saved_seconds,baseline_source,baseline_version,confidence,calculator_version,occurred_at)
                                     VALUES(%s,%s,'draft','accepted_draft',%s,%s,480,%s,%s,'raffi_default','raffi-default-v1',%s,'time-back-v1',to_timestamp(%s)) RETURNING id::text""",
                                  (wid, USERS["owner"], "ref-" + name, hashlib.sha256(name.encode()).hexdigest(), active_seconds, saved_seconds, confidence,
                                   week_start + 2 * DAY)).fetchone()[0]
    # The usage ledger as billing.settle writes it: a reservation, then `actual` (completed), `released` (failed, the
    # provider cost still booked) or `estimated_unknown` (outcome unknown until reconciled).
    reservations, cost = {}, {}
    for name in ("completed", "failed", "unknown"):
        reservations[name] = db.execute("""INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,provider,model,estimated_usd_micro,cost_state,idempotency_key,at)
                                           VALUES(%s,'reserve','text_model','fixture','fixture-model',5000,'estimated',%s,to_timestamp(%s)) RETURNING id::text""",
                                        (wid, "reserve-" + name, week_start + 3 * DAY - 60)).fetchone()[0]
    for name, reservation, kind, state_name, actual in (("actual", "completed", "settle", "actual", 1200), ("released", "failed", "release", "released", 300),
                                                        ("unknown", "unknown", "settle", "estimated_unknown", None)):
        cost[name] = db.execute("""INSERT INTO public.pr_usage_ledger(workspace_id,reservation_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,
                                   idempotency_key,at) VALUES(%s,%s,%s,'text_model','fixture','fixture-model',5000,%s,%s,%s,to_timestamp(%s)) RETURNING id::text""",
                                (wid, reservations[reservation], kind, actual, state_name, "settle-" + name, week_start + 3 * DAY)).fetchone()[0]
proofs._modules.update({"postriff_phase2.visual_pack.service": None, "postriff_phase2.results.service": None})   # slices not present: unavailable, never zero
first = proofs.refresh(wid, "owner", {"frequency": "weekly"})
assert first["appended"] and first["revision"] == 1 and first["verified"], first
proof = first["proof"]
figures = proof["latest"]["counts"]["figures"]
assert proof["proofId"] == model.proof_id(wid, "weekly", week_start) and proof["timeZone"] == "America/New_York" and proof["timeZoneSource"] == "recipe"
assert (proof["periodStart"], proof["periodEnd"]) == (week_start, at(NY, 2026, 10, 12))
assert figures["acceptedWork"]["value"] == 2 and figures["acceptedWork"]["evidence"]["variantIds"] == ["v-job", "v-slot"], figures["acceptedWork"]
assert figures["acceptedWork"]["approved"] == 1                                                         # the approved job; unused or failed drafts excluded
assert figures["verifiedPublications"]["value"] == 1 and figures["verifiedPublications"]["evidence"]["jobIds"] == ["job-verified"]
assert figures["unresolvedSlots"]["value"] == 1 and figures["unresolvedSlots"]["evidence"]["slotIds"] == ["sl_blocked"]
assert figures["assistedExports"] == {**figures["assistedExports"], "value": None, "dataState": "unavailable", "reason": "visual_pack_unavailable"}
assert figures["outcomes"]["value"] is None and figures["outcomes"]["reason"] == "results_unavailable"
assert figures["timeBack"]["value"] == [{"confidence": "estimated", "outcomes": 1, "savedSeconds": 480}, {"confidence": "measured", "outcomes": 1, "savedSeconds": 360}]
assert figures["timeBack"]["evidence"] == {"estimatedLedgerIds": [ledger["estimated"]], "measuredLedgerIds": [ledger["measured"]]}
assert figures["providerCost"]["value"] == {"actualUsdMicro": 1500, "actualEntries": 2, "unknownEntries": 1, "unknownReservedEstimateUsdMicro": 5000}
assert figures["providerCost"]["evidence"] == {"actualLedgerIds": sorted([cost["actual"], cost["released"]]), "unknownLedgerIds": [cost["unknown"]]}
assert proof["latest"]["dataState"] == "partial" and not proof["maturity"]["mature"]                     # AC34: not matured yet
assert proof["latest"]["counts"]["sourceWatermark"]["queue"] == week_start + DAY + 600
again = proofs.refresh(wid, "owner", {"frequency": "weekly"})
assert not again["appended"] and again["revision"] == 1
passed("AC26 proof figures reconcile to Queue, weekly, Time Back and usage-ledger evidence ids; unchanged data appends nothing")

patch_state(wid, lambda s: s["phase2"]["jobs"].append({"id": "job-late", "state": "verified", "providerReference": "p4", "verification": {"at": week_start + 4 * DAY},
                                                        "manifest": {"channelId": "ch1"}}))
late = proofs.refresh(wid, "owner", {"frequency": "weekly"})
assert late["appended"] and late["revision"] == 2
assert late["proof"]["latest"]["reason"] == "late_data"
assert late["proof"]["latest"]["correction"] == [{"figure": "verifiedPublications", "before": 1, "after": 2}], late["proof"]["latest"]["correction"]
prior = proofs.revision(wid, "owner", proof["proofId"], "1")["revision"]
assert prior["counts"]["figures"]["verifiedPublications"]["value"] == 1 and prior["revision"] == 1
assert [r["revision"] for r in late["proof"]["revisions"]] == [2, 1]
passed("AC26 late data appends revision 2 with a material-correction note; revision 1 is preserved")


class VisualPack:
    @staticmethod
    def handoff_counts(cur, workspace_id, start, end):
        return {"exportReady": 3, "downloaded": 2, "userConfirmedUsed": 5, "queued": 4, "verifiedPublished": 7, "packIds": ["pack-1"]}


class Results:
    @staticmethod
    def period_summary(cur, workspace_id, start, end):
        return {"provider_native": None, "first_party_reported": {"counts": {"lead": 2}, "money": {}, "reversed": 0, "unattributed": 1, "associated": 1},
                "user_declared": {"counts": {"booking": 1}, "money": {"usd": {"minor": 9000, "events": 1}}, "reversed": 0, "unattributed": 1, "associated": 0},
                "definition": "rafii.result-link-association.v1", "asOf": clock[0], "dataState": "partial", "evidenceIds": ["res-1", "res-2"]}


proofs._modules.update({"postriff_phase2.visual_pack.service": VisualPack, "postriff_phase2.results.service": Results})
joined = proofs.refresh(wid, "owner", {"frequency": "weekly"})
figures = joined["proof"]["latest"]["counts"]["figures"]
assert joined["revision"] == 3
assert figures["assistedExports"]["value"] == {"exportReady": 3, "downloaded": 2, "userConfirmedUsed": 5}
assert figures["verifiedPublications"]["value"] == 2                                                   # AC34: exports never inflate verified publications
assert figures["outcomes"]["value"]["provider_native"] is None and figures["outcomes"]["value"]["user_declared"]["counts"] == {"booking": 1}
assert figures["outcomes"]["evidence"]["resultIds"] == ["res-1", "res-2"] and figures["outcomes"]["dataState"] == "partial"
in_progress = proofs.refresh(wid, "owner", {"frequency": "weekly", "periodStart": "2026-10-12"})
assert in_progress["proof"] is None and in_progress["dataState"] == "unavailable" and in_progress["reason"] == "period_in_progress"
assert sql("SELECT count(*) FROM public.pr_proof_revisions WHERE proof_id=%s", model.proof_id(wid, "weekly", at(NY, 2026, 10, 12)))[0][0] == 0
refused(lambda: proofs.refresh(wid, "owner", {"frequency": "weekly", "periodStart": "2026-10-06"}), 400)
refused(lambda: proofs.refresh(wid, "editor", {"frequency": "weekly"}), 403)
editor_view = proofs.get(wid, "editor", proof["proofId"])["proof"]
assert editor_view["latest"]["counts"]["figures"]["providerCost"] == {**editor_view["latest"]["counts"]["figures"]["providerCost"], "value": None, "dataState": "restricted"}
assert proofs.get(wid, "owner", proof["proofId"])["proof"]["latest"]["counts"]["figures"]["providerCost"]["value"]["actualUsdMicro"] == 1500
refused(lambda: proofs.get(wid, "other", proof["proofId"]), 403)
refused(lambda: proofs.get(wid2, "other", proof["proofId"]), 404)
passed("AC34 in-progress periods are unavailable, immature ones partial; assisted exports and outcomes stay separate; cost is owner-only")

# A later reconciliation finalizes the unknown cost: it belongs to the period of the settlement it replaces (late data, a
# new revision there), the unknown entry stops counting, nothing is counted twice; non-owners never see the amounts.
with connection() as db:
    db.execute("""INSERT INTO public.pr_usage_ledger(workspace_id,reservation_id,kind,dimension,provider,model,estimated_usd_micro,actual_usd_micro,cost_state,idempotency_key,at)
                  VALUES(%s,%s,'settle','text_model','fixture','fixture-model',5000,4200,'actual','reconcile-fixture',to_timestamp(%s))""",
               (wid, reservations["unknown"], clock[0]))
reconciled = proofs.refresh(wid, "owner", {"frequency": "weekly"})
cost_figure = reconciled["proof"]["latest"]["counts"]["figures"]["providerCost"]
assert reconciled["appended"] and reconciled["revision"] == 4 and reconciled["proof"]["latest"]["reason"] == "late_data"
assert cost_figure["value"] == {"actualUsdMicro": 5700, "actualEntries": 3, "unknownEntries": 0, "unknownReservedEstimateUsdMicro": 0} and cost_figure["dataState"] == "available"
assert [e for e in reconciled["proof"]["latest"]["correction"] if e["figure"] == "providerCost"][0]["after"]["actualUsdMicro"] == 5700
editor_view = proofs.get(wid, "editor", proof["proofId"])["proof"]
assert {"figure": "providerCost", "restricted": True} in editor_view["latest"]["correction"] and "usage" not in editor_view["latest"]["sourceWatermark"]
assert all(e.get("restricted") or e["figure"] != "providerCost" for r in editor_view["revisions"] for e in r["correction"])
editor_revision = proofs.revision(wid, "editor", proof["proofId"], "4")["revision"]
assert {"figure": "providerCost", "restricted": True} in editor_revision["correction"] and "usage" not in editor_revision["sourceWatermark"]
assert "actualUsdMicro" not in json.dumps(editor_view) and "actualUsdMicro" not in json.dumps(editor_revision)
passed("reconciled unknown cost moves to actual in its own period without double counting; cost corrections and watermarks stay owner-only")

# === AC27: proposals, versioned decisions, applied in the next plan, rejected/revoked never recur ======================
listing = proofs.strategy(wid, "owner")
proposals = {d["kind"] + ":" + (d["basis"].get("sourceId") or d["basis"].get("experimentId")): d for d in listing["decisions"]}
assert set(proposals) == {"experiment_preference:ge_fixture", f"brief_topic:{source_id}", f"brief_topic:{radar_source}"}, set(proposals)
assert all(d["status"] == "proposed" and d["revision"] == 1 for d in listing["decisions"]) and listing["canDecide"] is True
exp = proposals["experiment_preference:ge_fixture"]
topic_reject, topic_edit = proposals[f"brief_topic:{source_id}"], proposals[f"brief_topic:{radar_source}"]
assert exp["scope"] == {"goalId": "gg_goal", "channelId": "ch1", "language": "en", "contentType": "tutorial_how_to"}
refused(lambda: proofs.decide(wid, "editor", exp["id"], {"action": "accept", "expectedRevision": 1, "idempotencyKey": "editor-accept-1"}), 403)
refused(lambda: proofs.decide(wid, "owner", exp["id"], {"action": "accept", "expectedRevision": 2, "idempotencyKey": "accept-exp-0001"}), 409, "revision_conflict")
clock[0] = at(NY, 2026, 10, 15, 10, 0)
accepted = proofs.decide(wid, "owner", exp["id"], {"action": "accept", "expectedRevision": 1, "idempotencyKey": "accept-exp-0002"})
assert accepted["verified"] and accepted["decision"]["status"] == "accepted" and accepted["decision"]["revision"] == 2
assert accepted["planning"] == {**accepted["planning"], "inEffect": True, "appliesFromDate": "2026-10-19"}
assert proofs.decide(wid, "owner", exp["id"], {"action": "accept", "expectedRevision": 1, "idempotencyKey": "accept-exp-0002"})["replayed"]
refused(lambda: proofs.decide(wid, "owner", exp["id"], {"action": "revoke", "expectedRevision": 1, "idempotencyKey": "accept-exp-0002"}), 409, "idempotency_conflict")
rejected = proofs.decide(wid, "owner", topic_reject["id"], {"action": "reject", "expectedRevision": 1, "idempotencyKey": "reject-topic-01"})
assert rejected["decision"]["status"] == "rejected" and rejected["planning"]["inEffect"] is False
refused(lambda: proofs.decide(wid, "owner", topic_reject["id"], {"action": "accept", "expectedRevision": 2, "idempotencyKey": "reaccept-topic1"}), 409, "invalid_transition")
refused(lambda: proofs.decide(wid, "owner", topic_edit["id"], {"action": "edit", "expectedRevision": 1, "idempotencyKey": "edit-topic-0001", "scope": {"goalId": "other"}}), 409, "scope_widened")
edited = proofs.decide(wid, "owner", topic_edit["id"], {"action": "edit", "expectedRevision": 1, "idempotencyKey": "edit-topic-0002", "scope": {"channelId": "ch1"},
                                                         "statement": "Plan one Threads post next week from the spaced-practice idea."})
assert edited["decision"]["status"] == "edited" and edited["decision"]["scope"]["channelId"] == "ch1"
state = raw_state(wid)
assert {d["id"] for d in strategy.active(state)} == {exp["id"], topic_edit["id"]}
assert identity(state) == identity_before, (identity(state), identity_before)                        # identity and voice untouched
prepared = service.coworker.weekly_prepare(wid, "owner", recipe["id"], max_slots=2)
week = prepared["week"]
assert week["weekOf"] == "2026-10-19", week["weekOf"]
applied = {a["id"]: a for a in week["appliedDecisions"]}
assert set(applied) == {exp["id"], topic_edit["id"]} and week["notApplied"] == [], week["appliedDecisions"]
assert len(applied[exp["id"]]["slotIds"]) == 2 and len(applied[topic_edit["id"]]["slotIds"]) == 1
stored_week = next(w for w in raw_state(wid)["coworker"]["weekly"]["weeks"] if w["id"] == week["id"])
assert stored_week["appliedDecisions"] == week["appliedDecisions"]
assert not sql("SELECT 1 FROM public.pr_agent_runs WHERE workspace_id=%s", wid)                     # planned with a $0 limit: no writer run
first_slot = next(s for s in stored_week["slots"] if s["id"] == applied[topic_edit["id"]]["slotIds"][0])
context = growth_loop.planning_context(raw_state(wid), first_slot, clock[0])
assert {d["decisionId"] for d in context["strategyDecisions"]} == {exp["id"], topic_edit["id"]}
assert "Queue approval remain required" in context["constraints"]
passed("AC27 accepted and edited decisions are versioned, scoped and recorded as applied in the next Weekly plan; identity unchanged")

before_rows = sql("SELECT count(*) FROM public.pr_strategy_decisions WHERE workspace_id=%s", wid)[0][0]
proofs.refresh(wid, "owner", {"frequency": "weekly", "periodStart": "2026-10-05"})
assert sql("SELECT count(*) FROM public.pr_strategy_decisions WHERE workspace_id=%s", wid)[0][0] == before_rows   # rejected/accepted never re-proposed
# Decided proposals never crowd out a new one: a fourth candidate (ordered after the three decided ones) is offered.
patch_state(wid, lambda s: s["sources"].append({"id": "src-new-idea", "kind": "idea", "title": "Duets for adult students", "text": "Idea.", "fingerprint": "e" * 64,
                                                "visibility": "private-local", "active": True, "createdAt": week_start, "facts": []}))
sql("""INSERT INTO public.pr_brief_actions(workspace_id,edition_id,item_id,source,source_ref,action,outcome_refs,actor_user_id,idempotency_key,request_digest,created_at)
       VALUES(%s,%s,'bi_11111111111111111111','listening','L-new','save_idea',%s::jsonb,%s,'fixture-new-idea',%s,to_timestamp(%s))""",
    wid, edition_id, json.dumps([{"type": "source", "id": "src-new-idea"}]), USERS["owner"], "f" * 64, week_start + 4 * DAY)
proofs.refresh(wid, "owner", {"frequency": "weekly", "periodStart": "2026-10-05"})
fresh_ids = {d["id"] for d in proofs.strategy(wid, "owner", status="proposed")["decisions"]}
assert fresh_ids == {strategy.decision_id(wid, "brief_topic", sql("SELECT id::text FROM public.pr_brief_actions WHERE idempotency_key='fixture-new-idea'")[0][0])}, fresh_ids
before_rows += 1
revoked = proofs.decide(wid, "owner", exp["id"], {"action": "revoke", "expectedRevision": 2, "idempotencyKey": "revoke-exp-0001"})
assert revoked["decision"]["status"] == "revoked" and revoked["planning"]["inEffect"] is False
context = growth_loop.planning_context(raw_state(wid), first_slot, clock[0])
assert [d["decisionId"] for d in context["strategyDecisions"]] == [topic_edit["id"]]                   # revocation stops future use at once
clock[0] = at(NY, 2026, 10, 22, 10, 0)
next_week = service.coworker.weekly_prepare(wid, "owner", recipe["id"], max_slots=2)["week"]
assert next_week["weekOf"] == "2026-10-26" and next_week["appliedDecisions"] == []
assert next_week["notApplied"] == [{"id": topic_edit["id"], "revision": 2, "reason": "already_applied"}], next_week["notApplied"]
versions = {d["id"]: d["versions"] for d in proofs.strategy(wid, "owner")["decisions"]}
assert [v["status"] for v in versions[exp["id"]]] == ["proposed", "accepted", "revoked"]
assert [v["status"] for v in proofs.strategy(wid, "owner", status="rejected")["decisions"][0]["versions"]] == ["proposed", "rejected"]
assert sql("SELECT count(*) FROM public.pr_product_events WHERE workspace_id=%s AND event='strategy.decided'", wid)[0][0] == 4
assert identity(raw_state(wid)) == identity_before
passed("AC27 revoked and rejected decisions never recur; a brief topic is one post; every version is kept")

# === AC25: delivery through the existing outbox — quiet hours over DST, weekly cadence, daily cap across workspaces =====
service.notifications.set_preference(wid, "owner", {"scope": "all", "category": "*", "time_zone": "America/New_York", "quiet_start": 22 * 60, "quiet_end": 7 * 60})
service.notifications.set_preference(wid, "owner", {"scope": "all", "category": "opportunities", "email_mode": "immediate"})
clock[0] = at(NY, 2026, 11, 1, 0, 30)          # 00:30 EDT on the fall-back Sunday; the local day is 25 hours long
listening(wid, [op("N1", "Practice journals for adult learners", clock[0]), op("N2", "Teaching scales to adults", clock[0])])
run = briefs.cron(time.monotonic() + 60)
assert run["recipients"] == 2 and run["delivered"] == 2 and run["persisted"] == 2, run              # owner and editor; viewers get no brief
event = sql("""SELECT id::text, dedupe_key, payload, actor::text FROM public.pr_notification_events WHERE workspace_id=%s AND event_type='opportunity.brief_ready'
               AND actor=%s""", wid, USERS["owner"])
assert len(event) == 1 and event[0][1].startswith(f"brief:{USERS['owner']}:2026-W44:") and event[0][2]["count"] == 2, event
deliveries = {r[0]: r for r in sql("""SELECT channel, mode, status, extract(epoch from next_attempt_at), failure_detail FROM public.pr_notification_deliveries
                                       WHERE event_id=%s""", event[0][0])}
assert deliveries["in_app"][2] == "delivered"
assert deliveries["email"][1:4] == ("immediate", "pending", at(NY, 2026, 11, 1, 7, 0)), deliveries["email"]   # 07:00 EST, not 07:00 EDT
assert float(deliveries["email"][3]) - clock[0] == 7.5 * 3600
editor_email = sql("""SELECT d.mode, d.status FROM public.pr_notification_deliveries d JOIN public.pr_notification_events e ON e.id=d.event_id
                      WHERE e.event_type='opportunity.brief_ready' AND d.user_id=%s AND d.channel='email'""", USERS["editor"])
assert editor_email == [("digest", "pending")], editor_email
assert briefs.cron(time.monotonic() + 60)["recipients"] == 0                                            # bounded: re-checked at most every six hours
with connection() as db:
    failure = service.notifications.emit(db.cursor(), workspace_id=wid, event_type="publish.failed", dedupe_key="job:fixture-fail", entity_type="job",
                                         entity_id="fixture-fail", payload={"title": "A post did not go out", "href": "/app/queue"})
lanes = {d["channel"]: d for d in failure["deliveries"] if d["userId"] == USERS["owner"]}
assert lanes["email"]["mode"] == "immediate" and lanes["email"]["next_attempt_at"] == clock[0] and lanes["email"]["reason"] is None, lanes
passed("AC25 in-app always, email by preference, quiet hours resolved on the DST date; operational alerts keep their immediate lane")

clock[0] += 7 * 3600                           # 07:30 EST, same edition (ISO week 44): new material, no second alert
patch_state(wid, lambda s: s["coworker"]["listening"]["opportunities"].append(op("N3", "Duet ideas for adult students", clock[0])))
run = briefs.cron(time.monotonic() + 60)
assert run["persisted"] == 2 and run["delivered"] == 0 and run["skipped"].get("edition_already_delivered") == 2, run
assert sql("SELECT max(revision) FROM public.pr_brief_editions WHERE workspace_id=%s AND recipient_user_id=%s AND edition_key='2026-W44'", wid, USERS["owner"])[0][0] == 2
clock[0] = at(NY, 2026, 11, 1, 23, 30)         # 24 hours after the first alert, still the same 25-hour local day
listening(wid2, [op("M1", "Group lessons for adult beginners", clock[0])])
run = briefs.cron(time.monotonic() + 60)
owner_wid2 = sql("""SELECT revision, delivered_at FROM public.pr_brief_editions WHERE workspace_id=%s AND recipient_user_id=%s""", wid2, USERS["owner"])
assert owner_wid2 and owner_wid2[0][1] is None and run["skipped"].get("daily_cap") == 1, (owner_wid2, run)   # one opportunity alert per person per local day
assert sql("SELECT count(*) FROM public.pr_brief_editions WHERE workspace_id=%s AND recipient_user_id=%s AND delivered_at IS NOT NULL", wid2, USERS["other"])[0][0] == 1
clock[0] = at(NY, 2026, 11, 2, 6, 0)           # the next local day (and ISO week 45)
briefs.cron(time.monotonic() + 60)
start_day, end_day = composer.local_day(clock[0], "America/New_York")
owner_today = sql("""SELECT workspace_id::text, edition_key FROM public.pr_brief_editions WHERE recipient_user_id=%s AND delivered_at>=to_timestamp(%s)
                     AND delivered_at<to_timestamp(%s)""", USERS["owner"], start_day, end_day)
assert len(owner_today) == 1 and owner_today[0][1] == "2026-W45", owner_today                        # across both workspaces
assert sql("SELECT count(*) FROM public.pr_product_events WHERE event='brief.delivered'")[0][0] == 5
passed("AC25 weekly cadence (one alert per edition), material-change revisions without re-alerting, one alert per recipient per local day across workspaces and DST")

service.notifications.set_preference(wid, "editor", {"scope": "workspace", "category": "opportunities", "mute_hours": 24})
service.notifications.set_preference(wid, "viewer", {"scope": "all", "category": "*", "email_unsubscribed": True})
with connection() as db:
    muted = service.notifications.emit(db.cursor(), workspace_id=wid, event_type="opportunity.brief_ready", dedupe_key="brief:mute-check", actor=USERS["editor"],
                                       entity_type="brief_edition", entity_id="mute-check", payload={"title": "x", "count": 1})
    unsubscribed = service.notifications.emit(db.cursor(), workspace_id=wid, event_type="opportunity.brief_ready", dedupe_key="brief:unsub-check",
                                              actor=USERS["viewer"], entity_type="brief_edition", entity_id="unsub-check", payload={"title": "x", "count": 1})
assert {d["channel"]: (d["status"], d.get("reason")) for d in muted["deliveries"]} == {"in_app": ("delivered", None), "email": ("suppressed", "muted")}
assert {d["channel"]: (d["status"], d.get("reason")) for d in unsubscribed["deliveries"]} == {"in_app": ("delivered", None), "email": ("suppressed", "unsubscribed")}
assert all(d["userId"] in (USERS["editor"], USERS["viewer"]) for d in muted["deliveries"] + unsubscribed["deliveries"])   # actor-scoped: nobody else
assert not PAID.called
passed("AC25 mute and unsubscribe hold for brief alerts, which reach only their recipient")

# A dismissal lapses after the cooldown: the item may be offered again, and then every action is available
# (no "restore first"), while the dismissal itself stays in the action history.
current = briefs.current(wid, "owner")
n1 = next(i for i in current["edition"]["items"] if i["sourceRef"] == "N1")
briefs.action(wid, "owner", n1["id"], {"action": "dismiss", "reasonCode": "already_covered", "idempotencyKey": "dismiss-n1-0001",
                                       **({"editionId": current["edition"]["id"]} if current["edition"]["id"] else {"materialDigest": current["edition"]["materialDigest"]})})
assert "N1" not in {i["sourceRef"] for i in briefs.current(wid, "owner")["edition"]["items"]}
clock[0] += 8 * DAY
listening(wid, [op("N1", "Practice journals for adult learners", clock[0])])          # the same lead, retrieved again
again = briefs.current(wid, "owner")
n1 = next(i for i in again["edition"]["items"] if i["sourceRef"] == "N1")
assert n1["decision"] is None
assert briefs.action(wid, "owner", n1["id"], {"action": "save_idea", "idempotencyKey": "save-n1-00001", "materialDigest": again["edition"]["materialDigest"]})["outcome"]
assert [a for (a,) in sql("SELECT action FROM public.pr_brief_actions WHERE workspace_id=%s AND source_ref='N1' ORDER BY seq", wid)] == ["dismiss", "save_idea"]
passed("a lapsed dismissal offers the item again with every action available")

# === Pagination, migration replay, forced RLS, composite foreign keys, append-only rows ================================
with connection() as db:
    for n in range(30):
        db.execute("""INSERT INTO public.pr_brief_editions(workspace_id,recipient_user_id,edition_key,revision,period_start,period_end,time_zone,material_digest,
                                     data_state,coverage,items,created_at)
                      VALUES(%s,%s,%s,1,to_timestamp(%s),to_timestamp(%s),'UTC',%s,'available','[]','[]',to_timestamp(%s))""",
                   (wid, USERS["owner"], f"2025-W{n + 1:02d}", 1.7e9 + n * 7 * DAY, 1.7e9 + (n + 1) * 7 * DAY, hashlib.sha256(str(n).encode()).hexdigest(),
                    1.7e9 + (n // 2) * 7 * DAY + 0.1234567))   # fractional and pairwise-equal instants: the cursor must be exact
page = briefs.history(wid, "owner")
total = sql("SELECT count(*) FROM public.pr_brief_editions WHERE workspace_id=%s AND recipient_user_id=%s", wid, USERS["owner"])[0][0]
assert len(page["editions"]) == 25 and page["nextCursor"]
rest = briefs.history(wid, "owner", page["nextCursor"], "50")
seen = [e["id"] for e in page["editions"] + rest["editions"]]
assert len(seen) == total == len(set(seen)) and rest["nextCursor"] is None
assert [e["createdAt"] for e in page["editions"]] == sorted((e["createdAt"] for e in page["editions"]), reverse=True)
refused(lambda: briefs.history(wid, "owner", None, "51"), 400)
refused(lambda: briefs.history(wid, "owner", "not-a-cursor", None), 400, "invalid_cursor")
for week_day in ("2026-09-14", "2026-09-21", "2026-09-28"):
    proofs.refresh(wid, "owner", {"frequency": "weekly", "periodStart": week_day})
listed, cursor, pages = [], None, 0
while True:
    result = proofs.list(wid, "owner", "weekly", cursor, "2")
    listed += [p["proofId"] for p in result["proofs"]]
    pages += 1
    cursor = result["nextCursor"]
    if not cursor:
        break
assert pages >= 2 and len(listed) == len(set(listed)) == sql("SELECT count(DISTINCT proof_id) FROM public.pr_proof_revisions WHERE workspace_id=%s AND frequency='weekly'", wid)[0][0]
decisions, cursor = [], None
while True:
    result = proofs.strategy(wid, "owner", None, cursor, "1")
    decisions += [d["id"] for d in result["decisions"]]
    cursor = result["nextCursor"]
    if not cursor:
        break
assert len(decisions) == len(set(decisions)) == 4
passed("bounded cursor pagination (25 default, 50 maximum, deterministic order, no duplicates) for editions, proofs and decisions")

with connection() as db:
    db.execute((ROOT / "migrations/postriff/084_briefs_proof_strategy.sql").read_text())               # re-applies cleanly
edition_row = sql("SELECT id::text FROM public.pr_brief_editions WHERE workspace_id=%s LIMIT 1", wid)[0][0]
for statement, args, expected in (
        ("INSERT INTO public.pr_brief_actions(workspace_id,edition_id,item_id,source,source_ref,action,actor_user_id,idempotency_key,request_digest) "
         "VALUES(%s,%s,'bi_00000000000000000000','listening','x','save_idea',%s,'cross-tenant-1',%s)", (wid2, edition_row, USERS["other"], "0" * 64), "foreign_key_violation"),
        ("UPDATE public.pr_proof_revisions SET reason='initial' WHERE workspace_id=%s", (wid,), "insufficient_privilege"),
        ("UPDATE public.pr_strategy_decisions SET statement='changed' WHERE workspace_id=%s", (wid,), "insufficient_privilege"),
        ("UPDATE public.pr_brief_editions SET items='[]' WHERE id=%s", (edition_id,), "insufficient_privilege"),
        ("INSERT INTO public.pr_brief_editions(workspace_id,recipient_user_id,edition_key,revision,period_start,period_end,time_zone,material_digest,data_state,items) "
         "VALUES(%s,%s,'2030-W01',1,now(),now()+interval '7 days','UTC',%s,'available','[1,2,3,4]')", (wid, USERS["owner"], "a" * 64), "check_violation")):
    try:
        sql(statement, *args)
    except psycopg.Error as error:
        assert error.sqlstate == {"foreign_key_violation": "23503", "insufficient_privilege": "42501", "check_violation": "23514"}[expected], (statement, error.sqlstate)
    else:
        raise AssertionError("accepted: " + statement)


def as_user(user, query, *args):
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (user,))
        rows = db.execute(query, args).fetchall()
        db.rollback()
        return rows


assert as_user(USERS["owner"], "SELECT count(*) FROM public.pr_brief_editions")[0][0] == sql("SELECT count(*) FROM public.pr_brief_editions WHERE recipient_user_id=%s", USERS["owner"])[0][0]
assert as_user(USERS["editor"], "SELECT count(*) FROM public.pr_brief_editions WHERE recipient_user_id<>%s", USERS["editor"])[0][0] == 0
assert as_user(USERS["owner"], "SELECT count(*) FROM public.pr_proof_revisions WHERE workspace_id=%s", wid)[0][0] > 0
assert as_user(USERS["editor"], "SELECT count(*) FROM public.pr_proof_revisions")[0][0] == 0                  # cost-bearing rows: owners only
assert as_user(USERS["editor"], "SELECT count(*) FROM public.pr_strategy_decisions WHERE workspace_id=%s", wid)[0][0] > 0
assert as_user(USERS["other"], "SELECT count(*) FROM public.pr_strategy_decisions WHERE workspace_id=%s", wid)[0][0] == 0
for table in ("pr_brief_schedule", "pr_proof_schedule"):
    try:
        as_user(USERS["owner"], f"SELECT count(*) FROM public.{table}")
    except psycopg.errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError(table + " readable by a browser role")
try:
    as_user(USERS["owner"], "INSERT INTO public.pr_strategy_decisions(workspace_id,decision_id,revision,status,kind,statement) VALUES(%s,'sd_00000000000000000000',9,'proposed','brief_topic','forged')", wid)
except psycopg.errors.InsufficientPrivilege:
    pass
else:
    raise AssertionError("browser insert accepted")
passed("migration re-applies; forced RLS (own briefs, owner-only proof, member decisions, service-only schedules), composite FKs, append-only versions")

proof_run = proofs.cron(time.monotonic() + 60)
assert proof_run["status"] == "ok" and proof_run["workspaces"] >= 1, proof_run
assert proofs.cron(time.monotonic() + 60)["workspaces"] == 0                                            # bounded re-check interval
assert not PAID.called
passed("proof cron recomputes recent periods for Growth Loop workspaces, bounded and without paid I/O")

clock[0] += 7 * 3600                           # everyone is due again; every run now fails
with mock.patch.object(type(proofs), "recompute_workspace", side_effect=RuntimeError("fixture failure")):
    failed = proofs.cron(time.monotonic() + 60)
assert failed["workspaces"] == 0 and failed["skipped"].get("RuntimeError", 0) >= 1, failed
assert float(sql("SELECT extract(epoch from checked_at) FROM public.pr_proof_schedule WHERE workspace_id=%s", wid)[0][0]) == clock[0]
assert proofs.cron(time.monotonic() + 60)["workspaces"] == 0                    # a failure waits the normal interval, never heads the queue
with mock.patch.object(type(briefs), "run_recipient", side_effect=RuntimeError("fixture failure")):
    failed = briefs.cron(time.monotonic() + 60)
assert failed["recipients"] == 0 and failed["skipped"].get("RuntimeError", 0) >= 4, failed
assert briefs.cron(time.monotonic() + 60)["recipients"] == 0
passed("failed cron runs are spaced like successful ones, so a persistent failure never starves other workspaces or recipients")
print(json.dumps({"execution": "disposable PostgreSQL; stored fixtures; trends not allow-listed; paid paths patched to fail", "result": "PASS"}), flush=True)
