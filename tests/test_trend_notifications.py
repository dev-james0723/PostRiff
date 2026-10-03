"""T28 offline adapter tests. Real emit + planner, deterministic in-memory DB double.

Default tests are offline. NotificationPostgres separately exercises real local SQL with
an explicit disposable DSN; synthetic admission is not model qualification.
"""
import copy
import json
from pathlib import Path
import sys
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from postriff_phase2.permissions import Membership
from postriff_phase2.coworker import flags
from postriff_phase2.notifications import delivery, planner, store as notification_store
from postriff_phase2.growth.trends import notifications as N, opportunities, relevance

NOW = 1800000000.0
WID = "00000000-0000-4000-8000-000000000001"
ACTOR = "00000000-0000-4000-8000-000000000002"
WATCH = "00000000-0000-4000-8000-000000000003"
TID = "00000000-0000-4000-8000-000000000004"
OID = "00000000-0000-4000-8000-000000000005"
RID = "00000000-0000-4000-8000-000000000006"
SCOPE = "workspace:" + WID


def row(kind, identity, payload, revision=1):
    # Explicit synthetic verified projection, not a manufactured source-policy grant.
    return {"kind": kind, "object_id": identity, "scope_key": SCOPE, "revision": revision,
            "projection_id": str(uuid.uuid5(uuid.NAMESPACE_URL, kind+identity+str(revision))),
            "available_at": opportunities.iso(NOW-10), "expires_at": opportunities.iso(NOW+86400),
            "validity": "valid", "verification_state": "verified", "receipt_id": RID,
            "policy": {"derive_metrics": True, "retain_derivatives": True},
            "method_bundle": {"method_id": "fixture", "version": "1"}, "payload": payload}


class Cursor:
    def __init__(self, storage):
        self.storage, self.result = storage, []

    def __enter__(self): return self
    def __exit__(self, *_): return False
    def fetchone(self): return self.result.pop(0) if self.result else None
    def fetchall(self): result, self.result = self.result, []; return result

    def execute(self, sql, args=()):
        s = self.storage
        q = " ".join(sql.split())
        s.queries.append((q, args)); self.result = []
        if q.startswith("SELECT pg_try_advisory_xact_lock"):
            self.result = [(s.tick_lock,)]; return
        if "pg_advisory_xact_lock" in q:
            return
        if q.startswith("SELECT w.id::text,actor.created_by::text"):
            provider, partition, allowed, limit = args
            found = [(wid, actor) for wid, actor in s.tick_workspaces.items() if wid in allowed
                     and s.creator_active and s.actor_active and s.creator_role in {"owner", "editor"}
                     and any(w["enabled"] and w["payload"].get("notification_policy") == "in_app" for w in s.watches)]
            found.sort(key=lambda r: (s.cursors.get(("workspace:"+r[0],provider,partition), {}).get("cursor_value", {}).get("scanned_at", ""), r[0]))
            self.result = found[:limit]; return
        if q.startswith("INSERT INTO public.pr_trend_provider_cursors"):
            s.cursors.setdefault(tuple(args), {"generation":0,"cursor_value":{},"coverage_state":"partial"}); return
        if q.startswith("SELECT generation,cursor_value FROM public.pr_trend_provider_cursors"):
            saved=s.cursors[tuple(args)]
            self.result = [(saved["generation"],copy.deepcopy(saved["cursor_value"]))]; return
        if q.startswith("UPDATE public.pr_trend_provider_cursors"):
            payload,coverage,scope,provider,partition,generation=args
            saved=s.cursors[(scope,provider,partition)]
            if saved["generation"]==generation and not s.cursor_conflict:
                saved.update(generation=generation+1,cursor_value=json.loads(payload),coverage_state=coverage)
                self.result=[(generation+1,)]
            return
        if q.startswith("SELECT p.object_id::text FROM public.pr_trend_projections p"):
            scope, cutoff, now, after, _, _, wid, limit = args
            if s.tick_candidates is not None:
                ids = s.tick_candidates.get(wid, [])
            else:
                records = [r for (k, _, _), r in s.projections.items() if k == "opportunity"
                           and r["scope_key"] == scope and opportunities.epoch(r["available_at"]) <= cutoff
                           and opportunities.epoch(r["expires_at"]) > now]
                ids = [r["object_id"] for r in records
                       if not any(p["revision"] > r["revision"] and p["kind"] == "opportunity"
                                  and p["object_id"] == r["object_id"] and opportunities.epoch(p["available_at"]) <= now
                                  for p in s.projections.values())]
            self.result = [(oid,) for oid in sorted(ids) if after is None or oid > after][:limit]; return
        if q.startswith("SAVEPOINT"):
            s.saved_page = (copy.deepcopy(s.events), copy.deepcopy(s.deliveries)); return
        if q.startswith("ROLLBACK TO SAVEPOINT"):
            s.events, s.deliveries = s.saved_page; return
        if q.startswith("RELEASE SAVEPOINT"):
            return
        if q.startswith("SELECT manifest_id::text FROM public.pr_trend_projections"):
            self.result = [(OID,)]; return
        if q.startswith("SELECT state FROM public.pr_workspaces"):
            self.result = [(s.state,)] if args[0] in s.tick_workspaces else []
        elif q.startswith("SELECT w.watch_id::text"):
            w = next((w for w in s.watches if str(w["watch_id"]) == args[1]), None)
            if w and args[0] == WID:
                self.result = [(w["watch_id"], w["revision"], w["enabled"], copy.deepcopy(w["payload"]), ACTOR, w["created_at"])]
        elif q.startswith("SELECT 1 FROM public.pr_memberships m JOIN"):
            self.result = [(1,)] if s.creator_active else []
        elif q.startswith("SELECT 1 FROM public.pr_memberships WHERE"):
            self.result = [(1,)] if s.actor_active else []
        elif q.startswith("SELECT 1 FROM public.pr_notification_events"):
            self.result = [(1,)] if (args[0], args[1]) in s.events else []
        elif q.startswith("SELECT count(*),count(*) FILTER"):
            group, cooldown, workspace, start = args
            events = [e for e in s.events.values() if e["workspace"] == workspace and e["at"] > start]
            self.result = [(len(events), sum(e["group"] == group and e["at"] > cooldown for e in events))]
        elif q.startswith("INSERT INTO public.pr_notification_events"):
            key = (args[1], args[9])
            if key not in s.events:
                eid = "event_" + str(len(s.events)+1)
                s.events[key] = {"id": eid, "workspace": args[0], "type": args[2], "entity_type": args[4], "entity_id": args[5],
                                 "payload": json.loads(args[8]), "group": args[10], "at": args[12], "expires_at": args[13]}
                self.result = [(eid,)]
        elif q.startswith("INSERT INTO public.pr_notification_deliveries"):
            key = (args[0], args[2], args[3])
            if key not in s.deliveries:
                did = "delivery_" + str(len(s.deliveries)+1)
                s.deliveries[key] = {"id": did, "event_id": args[0], "user_id": args[2], "channel": args[3], "status": args[5], "reason": args[10]}
                self.result = [(did,)]
        elif q.startswith("SELECT e.event_type, e.payload"):
            e = next((e for e in s.events.values() if e["id"] == args[1]), None)
            if e:
                self.result = [(e["type"], e["payload"], "info", False, "en", "Fixture", e["group"], e["entity_type"], e["entity_id"])]
        else:
            raise AssertionError("Unexpected SQL: " + q)


class Storage:
    def __init__(self):
        self.state = {"workspace": {"id": WID}, "brandHub": {"subject": "synthetic fixture"}}
        self.watches = [{"watch_id": WATCH, "revision": 1, "enabled": True, "created_at": opportunities.iso(NOW-1000),
                         "payload": {"trend_id": TID, "platforms": ["bluesky"], "threshold": "stage_change", "notification_policy": "in_app"}}]
        coverage = {"availability": "available", "completeness": "complete_within_scope", "coverage_epoch": "stable"}
        def trend(stage):
            return {"platform": "bluesky", "episode_id": TID, "coverage": coverage,
                    "inferred": {"stage": stage, "data_state": "qualified"}, "canonical_topic": "DO NOT COPY PRIVATE SOURCE EXCERPT"}
        self.projections = {("trend", TID, 1): row("trend", TID, trend("emerging")),
                            ("trend", TID, 2): row("trend", TID, trend("rising"), 2),
                            ("receipt", RID, 1): row("receipt", RID, {"trend_id": TID, "private_excerpt": "DO NOT STORE"}),
                            ("opportunity", OID, 1): row("opportunity", OID,
                                {"state": "eligible", "qualified": True, "trend_id": TID, "platform_targets": ["bluesky"],
                                 "trust_receipt_id": RID, "context_digest": relevance.context_revision(self.state), "title": "PRIVATE TOPIC"})}
        self.creator_active = self.actor_active = True
        self.creator_role = "owner"
        self.events, self.deliveries, self.queries = {}, {}, []
        self.cursors, self.tick_workspaces = {}, {WID: ACTOR}
        self.cursor_conflict = False
        self.tick_candidates, self.tick_lock = None, True
        self.manifest_inputs = None
        self.locked = []
        self.cur = Cursor(self)

    def __enter__(self): return self
    def __exit__(self, *_): return False
    def cursor(self): return self.cur
    @contextmanager
    def transaction(self, cursor=None): yield cursor or self.cur

    def ensure_scope(self, scope, *, cursor): return scope

    def list_watches(self, wid, actor, *, cursor):
        if wid != WID or actor != ACTOR or not self.actor_active: raise ValueError("membership denied")
        return copy.deepcopy(self.watches)

    def get_projection(self, wid, actor, kind, oid, *, revision=None, cursor=None):
        if wid != WID or actor != ACTOR or not self.actor_active: raise ValueError("membership denied")
        candidates = [r for (k, key, rev), r in self.projections.items() if k == kind and key == oid and (revision is None or rev == revision)]
        return copy.deepcopy(max(candidates, key=lambda r: r["revision"])) if candidates else None

    def get_opportunity(self, wid, actor, oid, **kw): return self.get_projection(wid, actor, "opportunity", oid, **kw)
    def get_receipt(self, wid, actor, oid, **kw): return self.get_projection(wid, actor, "receipt", oid, **kw)
    def get_manifest(self, scope, identity, *, cursor):
        inputs = self.manifest_inputs
        if inputs is None:
            rows = [self.get_projection(WID, ACTOR, kind, oid) for kind, oid in (("trend", TID), ("receipt", RID))]
            inputs = [{"scope_key": r["scope_key"], "node_id": r["projection_id"]} for r in rows]
        return {"inputs": copy.deepcopy(inputs)}
    def lock_dependencies(self, wid, actor, bindings, *, cursor):
        if not self.actor_active: raise ValueError("membership lost")
        self.locked.append(copy.deepcopy(bindings))


class TrendNotifications(unittest.TestCase):
    def setUp(self):
        # Other discovered CLI tests can prepend scripts/, which also contains
        # postriff_phase3.py. Resolve application packages for this test only;
        # patch cleanup restores the incoming search path without global edits.
        search_path = patch.object(sys, "path", [str(Path(__file__).resolve().parents[1]/"src"), *sys.path])
        search_path.start(); self.addCleanup(search_path.stop)
        self.store = Storage()
        self.values = {"RAFII_NOTIFICATIONS_V2_ENABLED": "1", "RAFII_TREND_WORKSPACE_ALLOWLIST": WID,
                       **{"RAFII_TREND_"+n+"_ENABLED": "1" for n in ("INTELLIGENCE", "RADAR", "TRUST_RECEIPTS", "NOTIFICATIONS", "STAGE_CLAIMS")}}
        self.prefs = {}
        self.member = {"userId": ACTOR, "membership": Membership("owner"), "active": True}
        for p in (patch.object(flags, "_values", self.values),
                  patch.object(notification_store, "members", side_effect=lambda *_: [self.member]),
                  patch.object(notification_store, "preference_rows", side_effect=lambda *_: self.prefs),
                  patch.object(notification_store, "recent_counts", return_value={}),
                  patch("socket.socket", side_effect=AssertionError("no egress")),
                  patch("socket.create_connection", side_effect=AssertionError("no egress")),
                  patch("urllib.request.urlopen", side_effect=AssertionError("no egress"))):
            p.start(); self.addCleanup(p.stop)

    def sweep(self, **kw):
        return N.sweep(self.store, workspace_id=WID, actor_id=ACTOR, opportunity_ids=[OID], now=NOW, values=self.values, **kw)

    def verdict(self, **kw):
        event = next(iter(self.store.events.values()))
        return N.delivery_eligibility(self.store, cursor=self.store.cur, workspace_id=WID, actor_id=ACTOR,
                                      entity_id=event["entity_id"], now=NOW, values=self.values, **kw)

    def test_real_emit_and_planner_persist_only_generic_in_app(self):
        self.assertEqual(self.sweep()["created"], 1)
        event = next(iter(self.store.events.values()))
        self.assertEqual(event["type"], "opportunity.detected")
        self.assertEqual(event["entity_type"], "trend_opportunity")
        self.assertEqual(event["payload"], {"title": N.TITLE, "href": "/app/trends"})
        self.assertNotIn("PRIVATE", json.dumps(event, default=str))
        self.assertEqual([r["channel"] for r in self.store.deliveries.values()], ["in_app"])
        self.assertTrue(self.store.locked)
        self.assertTrue(self.verdict()["eligible"])

    def test_repeated_sweep_dedupes_and_always_rechecks_rights(self):
        self.sweep()
        self.assertEqual(self.sweep()["duplicates"], 1)
        self.assertEqual(len(self.store.events), 1)
        self.store.projections[("receipt", RID, 1)]["policy"]["retain_derivatives"] = False
        self.assertEqual(self.sweep()["created"], 0)
        self.assertFalse(self.verdict()["eligible"])

    def test_workspace_allowlist_and_all_flags_fail_closed(self):
        for name in self.values:
            values = {**self.values, name: ""}
            result = N.sweep(self.store, workspace_id=WID, actor_id=ACTOR, opportunity_ids=[OID], now=NOW, values=values)
            with self.subTest(flag=name): self.assertEqual(result["created"], 0)
        self.assertEqual(self.store.events, {})

    def test_watch_creation_is_opt_in_no_extra_boolean(self):
        self.assertNotIn("notifications", self.store.watches[0]["payload"])
        self.assertEqual(self.sweep()["created"], 1)

    def test_no_watch_disabled_watch_wrong_policy_wrong_platform(self):
        for mutation in ("missing", "disabled", "policy", "platform"):
            self.store = Storage()
            if mutation == "missing": self.store.watches = []
            if mutation == "disabled": self.store.watches[0]["enabled"] = False
            if mutation == "policy": self.store.watches[0]["payload"].pop("notification_policy")
            if mutation == "platform": self.store.watches[0]["payload"]["platforms"] = ["youtube"]
            with self.subTest(mutation=mutation): self.assertEqual(self.sweep()["created"], 0)

    def test_baseline_and_pre_watch_history_do_not_alert(self):
        self.store.projections.pop(("trend", TID, 2))
        self.assertEqual(self.sweep()["created"], 0)
        self.store = Storage()
        self.store.watches[0]["created_at"] = opportunities.iso(NOW-5)
        self.assertEqual(self.sweep()["created"], 0)

    def test_future_or_unverified_receipt_and_foreign_opportunity_fail_closed(self):
        for mutation in ("future", "expired", "unverified", "scope", "rights", "context", "unqualified", "binding"):
            self.store = Storage()
            r = self.store.projections[("receipt", RID, 1)]
            op = self.store.projections[("opportunity", OID, 1)]
            if mutation == "future": r["available_at"] = opportunities.iso(NOW+1)
            if mutation == "expired": r["expires_at"] = opportunities.iso(NOW)
            if mutation == "unverified": r["verification_state"] = "pending"
            if mutation == "scope": op["scope_key"] = "shared:other"
            if mutation == "rights": r["policy"]["derive_metrics"] = False
            if mutation == "context": self.store.state["brandHub"]["subject"] = "changed"
            if mutation == "unqualified": op["payload"]["qualified"] = False
            if mutation == "binding": op["payload"]["trust_receipt_id"] = WATCH
            with self.subTest(mutation=mutation): self.assertEqual(self.sweep()["created"], 0)

    def test_outage_is_not_declining_stage_change(self):
        current = self.store.projections[("trend", TID, 2)]["payload"]
        current["coverage"] = {"availability": "unavailable", "completeness": "gap", "coverage_epoch": "changed"}
        current["inferred"]["stage"] = "declining"
        self.assertEqual(self.sweep()["created"], 0)

    def test_unqualified_prior_stage_is_not_a_transition(self):
        self.store.projections[("trend", TID, 1)]["payload"]["inferred"]["data_state"] = "screening"
        self.assertEqual(self.sweep()["created"], 0)

    def test_explicit_coverage_watch_can_notice_changed_scope(self):
        self.store.watches[0]["payload"]["threshold"] = "coverage_change"
        self.store.projections[("trend", TID, 2)]["payload"]["coverage"] = {"availability": "available", "completeness": "partial", "coverage_epoch": "changed"}
        self.assertEqual(self.sweep()["created"], 1)

    def test_current_watch_and_opportunity_revision_bound_for_delivery(self):
        self.sweep()
        self.store.watches[0]["revision"] += 1
        self.assertEqual(self.verdict()["reason"], "watch_revision_changed")
        self.store.watches[0]["revision"] -= 1
        op = copy.deepcopy(self.store.projections[("opportunity", OID, 1)]); op["revision"] = 2
        self.store.projections[("opportunity", OID, 2)] = op
        self.assertEqual(self.verdict()["reason"], "opportunity_revision_changed")

    def test_shared_receipt_requires_authenticated_projection_and_explicit_manifest(self):
        op = self.store.projections[("opportunity", OID, 1)]
        op["receipt_id"], op["verification_state"] = None, "pending"
        for kind, identity, revision in (("trend", TID, 1), ("trend", TID, 2), ("receipt", RID, 1)):
            self.store.projections[(kind, identity, revision)]["scope_key"] = "shared:fixture"
        self.assertEqual(self.sweep()["created"], 1)
        self.assertTrue(self.verdict()["eligible"])
        self.store.manifest_inputs = []
        self.assertEqual(self.verdict()["reason"], "opportunity_manifest_binding_changed")

    def test_shared_receipt_cannot_name_a_different_trend_or_be_unverified(self):
        op = self.store.projections[("opportunity", OID, 1)]
        op["receipt_id"], op["verification_state"] = None, "pending"
        receipt = self.store.projections[("receipt", RID, 1)]
        receipt["payload"]["trend_id"] = WATCH
        self.assertEqual(self.sweep()["created"], 0)
        receipt["payload"]["trend_id"] = TID
        receipt["verification_state"] = "pending"
        self.assertEqual(self.sweep()["created"], 0)

    def test_retry_rechecks_watch_creator_recipient_source_and_flags(self):
        for mutation in ("watch", "creator", "recipient", "source", "flag"):
            self.store = Storage(); self.sweep()
            if mutation == "watch": self.store.watches[0]["enabled"] = False
            if mutation == "creator": self.store.creator_active = False
            if mutation == "recipient": self.store.actor_active = False
            if mutation == "source": self.store.projections[("opportunity", OID, 1)]["validity"] = "revoked"
            if mutation == "flag": self.values["RAFII_TREND_NOTIFICATIONS_ENABLED"] = ""
            with self.subTest(mutation=mutation): self.assertFalse(self.verdict()["eligible"])
            self.values["RAFII_TREND_NOTIFICATIONS_ENABLED"] = "1"

    def test_existing_planner_quiet_hours_keeps_only_noninterruptive_center(self):
        minute = datetime.fromtimestamp(NOW, timezone.utc).hour*60 + datetime.fromtimestamp(NOW, timezone.utc).minute
        prefs = {"quiet_start": (minute-10)%1440, "quiet_end": (minute+10)%1440, "time_zone": "UTC", "email_mode": "immediate", "push_mode": "immediate"}
        self.prefs[(WID, "opportunities")] = prefs
        self.assertTrue(planner.in_quiet_hours(NOW, prefs))
        plan = planner.plan({"workspace_id": WID, "event_type": N.EVENT_TYPE}, self.member, self.prefs, NOW, push_available=True)
        self.assertTrue(all(r["next_attempt_at"] > NOW for r in plan if r["channel"] in {"email", "push"}))
        self.sweep()
        self.assertEqual([(r["channel"], r["status"]) for r in self.store.deliveries.values()], [("in_app", "delivered")])

    def test_in_app_preference_off_suppressed_by_existing_planner(self):
        self.prefs[(WID, "opportunities")] = {"in_app": False}
        self.sweep()
        self.assertEqual([r["status"] for r in self.store.deliveries.values()], ["suppressed"])
        self.assertEqual([r["reason"] for r in self.store.deliveries.values()], ["in_app_off"])

    def test_preference_and_stage_flag_changed_after_emit_cancel_revalidation(self):
        self.sweep()
        self.prefs[(WID, "opportunities")] = {"in_app": False}
        self.assertEqual(self.verdict()["reason"], "in_app_off")
        self.prefs.clear()
        self.values["RAFII_TREND_STAGE_CLAIMS_ENABLED"] = "0"
        self.assertEqual(self.verdict()["reason"], "stage_claims_disabled")

    def test_input_bound_returns_unprocessed_ids_and_uses_existing_transaction(self):
        result = N.sweep(self.store, workspace_id=WID, actor_id=ACTOR, opportunity_ids=[OID, OID, TID],
                         values=self.values, now=NOW, limit=1, cursor=self.store.cur)
        self.assertEqual((result["checked"], result["created"]), (1, 1))
        self.assertEqual(result["remaining_opportunity_ids"], [TID])

    def test_append_conflict_at_dependency_lock_cannot_emit(self):
        from postriff_phase2.growth.trends.store import TrendStorageError
        with patch.object(self.store, "lock_dependencies", side_effect=TrendStorageError("projection_revision_conflict")):
            self.assertEqual(self.sweep()["created"], 0)
        self.assertEqual(self.store.events, {})

    def test_new_transition_same_topic_obeys_cooldown(self):
        self.sweep()
        current = copy.deepcopy(self.store.projections[("trend", TID, 2)])
        current["revision"] = 3; current["payload"]["inferred"]["stage"] = "hot"
        self.store.projections[("trend", TID, 3)] = current
        result = self.sweep()
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["skipped"]["topic_cooldown"], 1)

    def test_two_per_rolling_day_limit_and_input_bound(self):
        self.store.events = {("w",str(i)): {"workspace": WID,"at":NOW-100,"group":"other"} for i in range(2)}
        self.assertIn("workspace_rate_limit", self.sweep()["skipped"])
        with self.assertRaises(ValueError): self.sweep(limit=101)

    def test_delivery_hook_scoped_to_trend_entity_and_never_sends(self):
        self.sweep()
        event = next(iter(self.store.events.values()))
        claimed = {"id": "d", "eventId": event["id"], "workspaceId": WID, "userId": ACTOR, "channel": "email", "attempts": 2, "maxAttempts": 3}
        worker = delivery.DeliveryWorker(lambda: self.store, clock=lambda: NOW)
        with patch("postriff_phase2.growth.trends.store.TrendStore", return_value=self.store), \
             patch.object(worker, "claim", side_effect=[[claimed], []]), \
             patch.object(worker, "complete", return_value=True) as complete, \
             patch.object(worker, "send_email", side_effect=AssertionError("external send prohibited")):
            result = worker.tick()
            self.assertEqual(result["cancelled"], 1)
            self.assertEqual(complete.call_args.args[1]["state"], "expired")
        event["entity_type"] = "ordinary_opportunity"
        with patch("postriff_phase2.growth.trends.notifications.delivery_eligibility", side_effect=AssertionError("must not intercept ordinary events")):
            self.assertFalse(worker._context(claimed)["expired"])

    def test_tick_uses_only_reserved_provider_cursor_namespace(self):
        other=(SCOPE,"actual-provider","feed")
        other_partition=(SCOPE,N.SCAN_PROVIDER,"other-purpose")
        seed={"generation":17,"cursor_value":{"opaque":"provider cursor"},"coverage_state":"partial"}
        self.store.cursors[other]=copy.deepcopy(seed)
        self.store.cursors[other_partition]=copy.deepcopy(seed)
        with patch.object(N.time, "time", return_value=NOW):
            result = N.tick(self.store, self.values)
        self.assertEqual((result["workspaces"], result["checked"], result["created"]), (1, 1, 1))
        self.assertEqual(self.store.cursors[other],seed)
        self.assertEqual(self.store.cursors[other_partition],seed)
        saved=self.store.cursors[(SCOPE,N.SCAN_PROVIDER,N.SCAN_PARTITION)]
        self.assertEqual(saved["generation"],1)
        self.assertIsNone(saved["cursor_value"]["after_object_id"])
        self.assertEqual(set(saved["cursor_value"]),{"cycle_cutoff","after_object_id","scanned_at"})
        self.assertNotIn("pr_runtime", " ".join(q for q,_ in self.store.queries))
        self.assertEqual([d["channel"] for d in self.store.deliveries.values()], ["in_app"])

    def test_tick_generation_conflict_fails_closed(self):
        self.store.cursor_conflict=True
        with self.assertRaisesRegex(N.contracts.ContractError,"generation_conflict"):
            N.tick(self.store,self.values)
        # Transaction rollback is proved by the real SQL fixture, not this double.

    def test_tick_disabled_or_empty_allowlist_has_zero_database_effects(self):
        for key in self.values:
            if key.endswith("STAGE_CLAIMS_ENABLED"): continue  # Coverage watches are independent.
            result = N.tick(self.store, {**self.values, key: ""})
            self.assertEqual(result["status"], "disabled")
        self.assertEqual(self.store.queries, [])
        with self.assertRaises(ValueError): N.tick(self.store, self.values, limit=0)

    def test_tick_requires_active_edit_watch_creator(self):
        for mutation in ("creator", "role", "watch"):
            self.store = Storage()
            if mutation == "creator": self.store.creator_active = False
            if mutation == "role": self.store.creator_role = "viewer"
            if mutation == "watch": self.store.watches[0]["enabled"] = False
            self.assertEqual(N.tick(self.store, self.values)["workspaces"], 0)
            self.assertEqual(self.store.cursors, {})

    def test_tick_advances_past_twenty_ineligible_rows_then_wraps(self):
        base = self.store.projections.pop(("opportunity", OID, 1))
        ids = [f"00000000-0000-4000-8000-{100+i:012d}" for i in range(27)]
        for i, oid in enumerate(ids):
            op = copy.deepcopy(base); op["object_id"] = oid
            op["payload"]["qualified"] = i == 26
            self.store.projections[("opportunity", oid, 1)] = op
        with patch.object(N.time, "time", return_value=NOW):
            first = N.tick(self.store, self.values)
        self.assertEqual((first["checked"], first["created"], first["partial_workspaces"]), (20, 0, 1))
        self.assertEqual(self.store.cursors[(SCOPE,N.SCAN_PROVIDER,N.SCAN_PARTITION)]["cursor_value"]["after_object_id"], ids[19])
        # A later insertion is deferred to the next cycle, without resetting progress.
        late = copy.deepcopy(base); late["object_id"] = RID; late["available_at"] = opportunities.iso(NOW+1)
        self.store.projections[("opportunity", RID, 1)] = late
        with patch.object(N.time, "time", return_value=NOW+2):
            second = N.tick(self.store, self.values)
        self.assertEqual((second["checked"], second["created"], second["partial_workspaces"]), (7, 1, 0))
        self.assertIsNone(self.store.cursors[(SCOPE,N.SCAN_PROVIDER,N.SCAN_PARTITION)]["cursor_value"]["after_object_id"])
        with patch.object(N.time, "time", return_value=NOW+3):
            third = N.tick(self.store, self.values)
        self.assertEqual(third["checked"], 20)
        self.assertEqual(len(self.store.events), 1)

    def test_tick_rotates_two_workspaces_and_caps_total_examined(self):
        ids = [f"00000000-0000-4000-8000-{500+i:012d}" for i in range(5)]
        self.store.tick_workspaces = dict.fromkeys(ids, ACTOR)
        self.store.tick_candidates = {wid: [OID, TID, RID] for wid in ids}
        values = {**self.values, "RAFII_TREND_WORKSPACE_ALLOWLIST": ",".join(ids)}
        seen = []
        def ineligible_page(store, **kw):
            seen.append(kw["workspace_id"])
            return {"checked": len(kw["opportunity_ids"]), "created": 0, "duplicates": 0,
                    "skipped": {"opportunity_not_eligible": len(kw["opportunity_ids"])}}
        with patch.object(N, "sweep", side_effect=ineligible_page):
            for offset in range(3):
                with patch.object(N.time, "time", return_value=NOW+offset):
                    result = N.tick(self.store, values, limit=3)
                self.assertEqual(result["workspaces"], 2)
                self.assertLessEqual(result["checked"], 3)
        self.assertEqual(set(seen), set(ids))
        self.assertEqual(seen[:5], ids)

    def test_tick_failed_page_rolls_back_emission_and_advances(self):
        self.store.tick_candidates = {WID: [OID, TID]}
        def broken_page(*args, **kw):
            self.store.events[(WID, "must-rollback")] = {"partial": True}
            raise RuntimeError("private detail must not escape")
        with patch.object(N, "sweep", side_effect=broken_page), patch.object(N.time, "time", return_value=NOW):
            result = N.tick(self.store, self.values, limit=1)
        self.assertEqual(result["skipped"], {"page_unavailable": 1})
        self.assertEqual(self.store.events, {})
        self.assertEqual(self.store.cursors[(SCOPE,N.SCAN_PROVIDER,N.SCAN_PARTITION)]["cursor_value"]["after_object_id"], min(OID, TID))
        self.assertNotIn("private", json.dumps(result))

    def test_tick_busy_does_not_scan_or_mutate(self):
        self.store.tick_lock = False
        self.assertEqual(N.tick(self.store, self.values)["status"], "busy")
        self.assertEqual(self.store.cursors, {})


class ImportIsolation(unittest.TestCase):
    def test_scripts_shadow_isolated_and_incoming_path_restored(self):
        scripts = str(Path(__file__).resolve().parents[1]/"scripts")
        incoming = [scripts, *sys.path]
        with patch.object(sys, "path", incoming), patch.dict(sys.modules):
            # Exercise first import as well as test discovery with cached modules.
            for name in list(sys.modules):
                if name == "postriff_phase3" or name.startswith("postriff_phase3."):
                    del sys.modules[name]
            case = TrendNotifications("test_tick_advances_past_twenty_ineligible_rows_then_wraps")
            result = unittest.TestResult()
            case.run(result)
            self.assertEqual(result.errors, [])
            self.assertEqual(result.failures, [])
            self.assertIs(sys.path, incoming)
            self.assertNotIn("postriff_phase3", sys.modules)




# Explicitly opt-in real SQL acceptance. No imports or connections by default.
class NotificationPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        from local_pg_target import selected_target
        target = selected_target(validate_fixture_dsns=False)
        dsn = os.environ.get('TREND_NOTIFICATIONS_TEST_DSN')
        if not dsn:
            raise unittest.SkipTest('explicit disposable notifications PostgreSQL DSN required')
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        params = conninfo_to_dict(dsn)
        allocated = (params.get('host') == '127.0.0.1' and params.get('port') == '56451'
                     and params.get('dbname','').startswith('trend_notifications_'))
        portable = (params.get('host') == '127.0.0.1' and params.get('port') == str(target.port)
                    and params.get('dbname') == 'postgres')
        if (set(params)-{'host','port','dbname','user'} or not (allocated or portable)
                or any(os.environ.get(k) for k in ('PGSERVICE','PGHOSTADDR'))):
            raise ValueError('explicit allocated notification DB or exact disposable CI runner required')
        cls.psycopg, cls.dsn = psycopg, dsn
        role = 'trend_notifications_' + uuid.uuid4().hex[:10]
        with psycopg.connect(dsn) as db:
            for table in ('pr_trend_jobs','pr_trend_provider_cursors','pr_notification_events'):
                if not db.execute('SELECT to_regclass(%s)', (table,)).fetchone()[0]:
                    raise RuntimeError('disposable database must have canonical repository migrations through040')
            if db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0] is not None:
                raise RuntimeError('notification proof requires a canonical database WITHOUT003/pr_runtime')
            db.execute('CREATE ROLE ' + role + ' NOSUPERUSER NOBYPASSRLS INHERIT')
            db.execute('GRANT service_role TO ' + role)
            for table in ('pr_workspaces','pr_memberships','pr_profiles'):
                db.execute('CREATE POLICY ' + role + ' ON ' + table + ' FOR ALL TO ' + role + ' USING(true) WITH CHECK(true)')
        def connect():
            db = psycopg.connect(dsn)
            db.execute('SET ROLE ' + role)
            return db
        cls.connect = staticmethod(connect)

    def setUp(self):
        import time
        from postriff_phase2.auth import initial_phase2_state
        from postriff_phase2.growth.trends import contracts
        from postriff_phase2.growth.trends.store import TrendStore, utcnow
        path = patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1]/'src'), *sys.path])
        path.start(); self.addCleanup(path.stop)
        # libpq talks only to the validated local DSN; every Python transport is blocked.
        for target in ('socket.create_connection','socket.socket.connect','socket.socket.connect_ex','urllib.request.urlopen'):
            blocker = patch(target, side_effect=AssertionError('external transport forbidden'))
            blocker.start(); self.addCleanup(blocker.stop)
        self.wid, self.actor, self.foreign_wid, self.foreign_actor = [str(uuid.uuid4()) for _ in range(4)]
        self.scope = 'shared:notification-' + uuid.uuid4().hex[:10]
        self.provider = 'synthetic-notification-' + uuid.uuid4().hex[:10]
        self.at = time.time(); self.end = opportunities.iso(self.at+3600)
        self.state = initial_phase2_state(self.wid,self.actor,'Notification SQL fixture','studio',self.at)
        self.state['brandHub'].update(subject='Bread experiments',audience='Home bakers')
        with self.psycopg.connect(self.dsn) as db:
            for wid, actor, state in ((self.wid,self.actor,self.state),(self.foreign_wid,self.foreign_actor,{})):
                db.execute('INSERT INTO auth.users(id) VALUES(%s)',(actor,))
                db.execute('INSERT INTO pr_profiles(user_id) VALUES(%s)',(actor,))
                db.execute('INSERT INTO pr_workspaces(id,state) VALUES(%s,%s::jsonb)',(wid,json.dumps(state)))
                db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')",(wid,actor))
        self.store = TrendStore(self.connect)
        self.store.ensure_scope(self.scope); self.store.ensure_scope('workspace:'+self.wid)
        self.store.grant_entitlement(self.wid,self.scope,['retrieve','derive_metrics','share_across_workspaces'],self.end)
        rights = {p:{'state':'allow','policy_ref':'synthetic-local-only','audience_scope':self.scope,'expires_at':self.end} for p in contracts.PERMISSIONS}
        start = opportunities.iso(self.at-3600)
        self.store.register_contract(self.provider,'1',list(contracts.PERMISSIONS),start,self.end)
        self.store.register_policy({'scope_key':self.scope,'provider_id':self.provider,'version':'1','rights':rights,
            'reviewed_by':'synthetic-test','review_ref':'fixture-only','effective_at':start,'expires_at':self.end,
            'retention_seconds':7200,'readiness':'ready'},provider_contract_version='1')
        self.sources=[]
        for n in range(2):
            payload={'platform':'bluesky','native_id':'fixture-'+str(n),'author_key':'fixture-author-'+str(n),'author_status':'known',
                'text':'Synthetic bread experiment oven temperature fermentation water comparison '+str(n),'language':'en',
                'canonical_url':'https://fixture.invalid/post/'+str(n)}
            obs={'schema_version':contracts.SCHEMA_VERSION,'observation_id':str(uuid.uuid4()),'scope_key':self.scope,
                'provider_id':self.provider,'provider_contract_version':'1','source_policy_version':'1','source_identity':'fixture-'+str(n),
                'revision_identity':'r1','revision_sequence':1,'kind':'raw_post','operation':'create','event_at':opportunities.iso(self.at-600-n),
                'received_at':utcnow(),'available_at':utcnow(),'time_basis':'provider_event','coverage_epoch':'notification-fixture',
                'provenance':{'access_method':'synthetic'},'retention_until':self.end,'rights':rights,'deletion_key':'fixture-'+str(n),
                'payload':payload,'payload_digest':contracts.digest(payload)}
            self.store.put_observation(obs); self.sources.append(obs['observation_id'])
        first = self.ingest('partial')
        self.tid = first['trend_id']
        self.watch = self.store.put_watch(self.wid,self.actor,{'trend_id':self.tid,'platforms':['bluesky'],
            'threshold':'coverage_change','notification_policy':'in_app'},idempotency_key='sql-watch')
        second = self.ingest('gap')
        self.assertEqual(second['trend_id'],self.tid)
        self.rid = second['receipt_id']
        self.trend = self.store.get_projection(self.wid,self.actor,'trend',self.tid)
        self.assertEqual(self.trend['revision'],2)
        self.assertEqual(self.trend['verification_state'],'verified')
        self.receipt = self.store.get_receipt(self.wid,self.actor,self.rid)
        self.values = {'RAFII_NOTIFICATIONS_V2_ENABLED':'1','RAFII_TREND_WORKSPACE_ALLOWLIST':self.wid,
            **{'RAFII_TREND_'+n+'_ENABLED':'1' for n in ('INTELLIGENCE','RADAR','TRUST_RECEIPTS','NOTIFICATIONS','STAGE_CLAIMS')}}
        flagpatch=patch.object(flags,'_values',self.values); flagpatch.start(); self.addCleanup(flagpatch.stop)
        self.oid = self.put_opportunity()

    def ingest(self, completeness):
        from postriff_phase2.growth.trends.pipeline import TrendPipeline
        from postriff_phase2.growth.trends.store import utcnow
        with self.store.transaction() as cur:
            result = TrendPipeline(self.store).consume(cur,{'event_id':str(uuid.uuid4()),'event_type':'trend.ingested','scope_key':self.scope,
                'payload':{'provider_id':self.provider,'observation_ids':self.sources,'decision_cutoff':utcnow(),
                'coverage_epoch':'notification-fixture','completeness':completeness,
                'coverage_interval':{'start':opportunities.iso(self.at-3600),'end':utcnow()}}})
        self.assertTrue(result.get('receipts'),result)
        self.assertEqual(result['receipts'][0]['verification_state'],'verified')
        return result['receipts'][0]

    def put_opportunity(self, *, identity=None, revision=1, qualified=True, include_receipt=True):
        from postriff_phase2.growth.trends.store import utcnow
        identity = identity or str(uuid.uuid4()); cutoff=utcnow()
        refs=[{'scope_key':self.scope,'node_id':self.trend['projection_id']}]
        if include_receipt: refs.append({'scope_key':self.scope,'node_id':self.receipt['projection_id']})
        manifest=self.store.put_manifest('workspace:'+self.wid,refs,decision_cutoff=cutoff,available_at=cutoff,retention_until=self.end)
        # Synthetic admission fixture only: production candidate creation never grants qualification.
        payload={'id':identity,'state':'eligible' if qualified else 'candidate','qualified':qualified,'trend_id':self.tid,
            'platform_targets':['bluesky'],'trust_receipt_id':self.rid,'context_digest':relevance.context_revision(self.state),
            'title':'PRIVATE SOURCE EXCERPT MUST NOT APPEAR','execution_state':'synthetic-notification-admission'}
        self.store.put_projection({'scope_key':'workspace:'+self.wid,'kind':'opportunity','object_id':identity,'revision':revision,
            'manifest_id':manifest['manifest_id'],'method_id':self.trend['method_bundle']['method_id'],
            'method_version':self.trend['method_bundle']['version'],'decision_cutoff':utcnow(),'available_at':utcnow(),
            'retention_until':self.end,'payload':payload})
        return identity

    def sweep(self, **kw):
        return N.sweep(self.store,workspace_id=self.wid,actor_id=self.actor,opportunity_ids=[self.oid],values=self.values,**kw)

    def events(self):
        with self.connect() as db:
            return db.execute('SELECT id::text,entity_id,payload FROM pr_notification_events WHERE workspace_id=%s',(self.wid,)).fetchall()

    def verdict(self, **kw):
        binding=self.events()[0][1]
        with self.store.transaction() as cur:
            return N.delivery_eligibility(self.store,cursor=cur,workspace_id=kw.pop('workspace_id',self.wid),
                actor_id=kw.pop('actor_id',self.actor),entity_id=binding,values=self.values,**kw)

    def test_real_sweep_commit_duplicate_and_safe_in_app_delivery(self):
        self.assertEqual(self.sweep()['created'],1)
        self.assertEqual(self.sweep()['duplicates'],1)
        event=self.events(); self.assertEqual(len(event),1)
        self.assertEqual(event[0][2],{'title':N.TITLE,'href':'/app/trends'})
        with self.connect() as db:
            rows=db.execute('SELECT channel,status,user_id::text FROM pr_notification_deliveries WHERE workspace_id=%s',(self.wid,)).fetchall()
            self.assertEqual(rows,[('in_app','delivered',self.actor)])
            self.assertIsNone(db.execute("SELECT receipt_id FROM pr_trend_projections WHERE kind='opportunity' AND object_id=%s",(self.oid,)).fetchone()[0])
            self.assertEqual(db.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone(),(False,False))
        self.assertTrue(self.verdict()['eligible'])
        self.assertFalse(self.verdict(channel='email')['eligible'])
        worker=delivery.DeliveryWorker(self.connect)
        row={'eventId':event[0][0],'userId':self.actor,'workspaceId':self.wid}
        self.assertFalse(worker._context(row,channel='in_app')['expired'])
        self.assertTrue(worker._context(row,channel='email')['expired'])

    def test_real_watch_revision_and_disable_cancel_delivery(self):
        self.assertEqual(self.sweep()['created'],1)
        with self.connect() as db:
            db.execute('UPDATE pr_trend_watches SET revision=revision+1 WHERE workspace_id=%s AND watch_id=%s',(self.wid,self.watch['watch_id']))
        self.assertEqual(self.verdict()['reason'],'watch_revision_changed')
        self.store.delete_watch(self.wid,self.actor,self.watch['watch_id'],expected_revision=2)
        self.assertEqual(self.verdict()['reason'],'watch_disabled_or_missing')
        self.assertEqual(self.sweep()['created'],0)

    def test_real_policy_revocation_cancels_retry_before_transport(self):
        from postriff_phase2.growth.trends.revocation import revoke_policy
        self.assertEqual(self.sweep()['created'],1)
        event=self.events()[0]
        revoke_policy(self.store,self.scope,self.provider,'1')
        self.assertFalse(self.verdict()['eligible'])
        self.assertEqual(self.sweep()['created'],0)
        # Even a legacy erroneously queued outbound retry cannot acquire authority.
        with self.connect() as db:
            db.execute("UPDATE pr_notification_deliveries SET channel='email',mode='immediate',status='pending',next_attempt_at=now() WHERE event_id=%s",(event[0],))
        worker=delivery.DeliveryWorker(self.connect,email_transport=lambda **_:self.fail('external send attempted'),from_address='fixture@invalid.test')
        worker.tick(max_items=1)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM pr_notification_deliveries WHERE event_id=%s',(event[0],)).fetchone()[0],'cancelled')
        self.assertEqual(len(self.events()),1)

    def test_real_membership_and_tenant_isolation(self):
        self.assertEqual(self.sweep()['created'],1)
        self.assertFalse(self.verdict(workspace_id=self.foreign_wid,actor_id=self.foreign_actor)['eligible'])
        self.assertIsNone(self.store.get_opportunity(self.foreign_wid,self.foreign_actor,self.oid))
        with self.assertRaises(Exception):
            N.sweep(self.store,workspace_id=self.wid,actor_id=self.foreign_actor,opportunity_ids=[self.oid],values=self.values)
        with self.connect() as db:
            db.execute("UPDATE pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s",(self.wid,self.actor))
        self.assertFalse(self.verdict()['eligible'])
        self.assertEqual(N.tick(self.store,self.values)['workspaces'],0)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_notification_events WHERE workspace_id=%s',(self.foreign_wid,)).fetchone()[0],0)

    def test_real_manifest_binding_and_opportunity_revision_are_current(self):
        bad=self.put_opportunity(include_receipt=False)
        result=N.sweep(self.store,workspace_id=self.wid,actor_id=self.actor,opportunity_ids=[bad],values=self.values)
        self.assertEqual(result['created'],0); self.assertIn('opportunity_manifest_binding_changed',result['skipped'])
        self.assertEqual(self.sweep()['created'],1)
        self.put_opportunity(identity=self.oid,revision=2)
        self.assertEqual(self.verdict()['reason'],'opportunity_revision_changed')

    def test_real_preferences_quiet_hours_and_current_opt_out(self):
        with self.connect() as db:
            db.execute("INSERT INTO pr_notification_preferences(user_id,scope_key,category,in_app,email_mode,push_mode,quiet_start,quiet_end,time_zone) VALUES(%s,%s,'opportunities',true,'immediate','immediate',0,1439,'UTC')",(self.actor,self.wid))
        self.assertEqual(self.sweep()['created'],1)
        self.assertTrue(self.verdict()['eligible'])
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT channel,status FROM pr_notification_deliveries WHERE workspace_id=%s',(self.wid,)).fetchall(),[('in_app','delivered')])
            db.execute("UPDATE pr_notification_preferences SET in_app=false WHERE user_id=%s AND scope_key=%s",(self.actor,self.wid))
        self.assertEqual(self.verdict()['reason'],'in_app_off')

    def test_real_tick_advances_ineligible_catalogue_and_wraps_without_duplicates(self):
        # Stable ordered IDs ensure the eligible row is behind >20 ineligible ones.
        with self.connect() as db:
            db.execute("UPDATE pr_trend_projections SET payload=jsonb_set(payload,'{qualified}','false') WHERE kind='opportunity' AND object_id=%s",(self.oid,))
        for n in range(21): self.put_opportunity(identity=str(uuid.UUID(int=n+1)),qualified=False)
        self.oid=self.put_opportunity(identity='ffffffff-ffff-4fff-8fff-ffffffffffff')
        first=N.tick(self.store,self.values,limit=20)
        self.assertEqual(first['checked'],20,first); self.assertEqual(first['created'],0,first)
        self.assertEqual(first['partial_workspaces'],1)
        second=N.tick(self.store,self.values,limit=20)
        self.assertEqual(second['created'],1,second)
        with self.connect() as db:
            saved=db.execute("SELECT cursor_value FROM pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s",("workspace:"+self.wid,N.SCAN_PROVIDER,N.SCAN_PARTITION)).fetchone()[0]
            self.assertIsNone(saved['after_object_id'])
        N.tick(self.store,self.values,limit=20)
        replay=N.tick(self.store,self.values,limit=20)
        self.assertEqual(replay['duplicates'],1,replay); self.assertEqual(len(self.events()),1)

    def test_real_reserved_cursor_isolation_generation_and_atomic_rollback_without003(self):
        from contextlib import contextmanager
        scope='workspace:'+self.wid
        original={'opaque':'synthetic unrelated provider position'}
        with self.connect() as db:
            self.assertIsNone(db.execute("SELECT to_regclass('public.pr_runtime')").fetchone()[0])
            for provider,partition in (('synthetic-existing-provider','feed'),(N.SCAN_PROVIDER,'other-purpose')):
                db.execute('INSERT INTO pr_trend_provider_cursors(scope_key,provider_id,partition_key,generation,cursor_value) VALUES(%s,%s,%s,11,%s::jsonb)',(scope,provider,partition,json.dumps(original)))
        with self.assertRaisesRegex(RuntimeError,'abort fixture transaction'):
            with self.store.transaction() as cur:
                @contextmanager
                def same_transaction(cursor=None): yield cursor or cur
                with patch.object(self.store,'transaction',same_transaction):
                    result=N.tick(self.store,self.values)
                    self.assertEqual(result['created'],1,result)
                raise RuntimeError('abort fixture transaction')
        self.assertEqual(self.events(),[])
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s',(scope,N.SCAN_PROVIDER,N.SCAN_PARTITION)).fetchone()[0],0)
        self.assertEqual(N.tick(self.store,self.values)['created'],1)
        self.assertEqual(N.tick(self.store,self.values)['duplicates'],1)
        with self.connect() as db:
            rows=db.execute('SELECT provider_id,partition_key,generation,cursor_value FROM pr_trend_provider_cursors WHERE scope_key=%s',(scope,)).fetchall()
            own=next(r for r in rows if r[:2]==(N.SCAN_PROVIDER,N.SCAN_PARTITION))
            self.assertEqual(own[2],2)
            self.assertEqual(set(own[3]),{'cycle_cutoff','after_object_id','scanned_at'})
            for row in rows:
                if row is not own:
                    self.assertEqual(row[2:],(11,original))
            self.assertEqual(db.execute('SELECT count(*) FROM pr_trend_source_policies WHERE provider_id=%s',(N.SCAN_PROVIDER,)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM pr_trend_jobs WHERE provider_id=%s',(N.SCAN_PROVIDER,)).fetchone()[0],0)
