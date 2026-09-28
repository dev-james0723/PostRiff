"""Actual PostgreSQL synthetic joins; no live provider/model calls or auto-adoption."""
import copy
import json
import os
import time
import unittest
import uuid
from unittest.mock import patch

from postriff_phase2.growth.trends import contracts, learning, opportunities
from postriff_phase2.growth.trends.store import TrendStore, TrendStorageError
from test_trend_integration import DurableServiceTests


@unittest.skipUnless(os.environ.get("TREND_SERVICE_TEST_DSN"), "explicit disposable PostgreSQL required")
class LearningSQL(unittest.TestCase):
    def setUp(self):
        # Reuse the actual non-owner/NOSUPERUSER/NOBYPASSRLS service fixture, but
        # not its tests or server. Every case has fresh tenant/policy/receipt IDs.
        DurableServiceTests.setUpClass.__func__(type(self))
        self.store = TrendStore(self.connect, offline_replay=True)
        self.now = time.time()
        self.scope = "workspace:" + self.wid
        self.created = []
        with self.connect() as db:
            self.state = db.execute("SELECT state FROM pr_workspaces WHERE id=%s", (self.wid,)).fetchone()[0]
        self.state["phase2"]["channels"].append({"id": "owned-account", "platform": "Threads", "language": "en", "revoked": False})
        self.state["phase2"]["jobs"] = []

    def save(self):
        with self.connect() as db:
            db.execute("UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(self.state), self.wid))

    def view(self, **kwargs):
        self.save()
        with self.connect() as db, db.cursor() as cur:
            return learning.report(cur, self.wid, self.actor, self.now, store=self.store, **kwargs)

    def event(self, decision=None, *, exposure=True, days=30):
        oid, eid = str(uuid.uuid4()), str(uuid.uuid4())
        at = self.now - days * 86400
        with self.connect() as db, db.cursor() as cur:
            old = self.store.get_opportunity(self.wid, self.actor, self.oid, cursor=cur)
            manifest = self.store.put_manifest(self.scope, [{"scope_key": old["scope_key"], "node_id": old["projection_id"]}],
                decision_cutoff=opportunities.iso(self.now), available_at=opportunities.iso(self.now),
                retention_until=old["expires_at"], cursor=cur)
            common = {"scope_key": self.scope, "manifest_id": manifest["manifest_id"], "method_id": old["method_bundle"]["method_id"],
                "method_version": old["method_bundle"]["version"], "decision_cutoff": opportunities.iso(self.now),
                "available_at": opportunities.iso(self.now), "retention_until": old["expires_at"], "receipt_id": self.rid}
            op = {**old["payload"], "id": oid, "platform_targets": ["threads"]}
            self.store.put_projection({**common, "kind": "opportunity", "object_id": oid, "revision": 1, "payload": op}, cursor=cur)
            if exposure:
                self.store.put_projection({**common, "kind": "exposure", "object_id": eid, "revision": 1, "payload": {
                    "workspace_id": self.wid, "actor_id": self.actor, "exposure_id": eid,
                    "opportunity_id": oid, "opportunity_revision": 1, "trust_receipt_id": self.rid,
                    "context_digest": op["context_digest"],
                    "recorded_at": opportunities.iso(at), "measurement": "client_reported_view", "eligible_candidate_count": 3}}, cursor=cur)
            sid = "source-" + oid
            binding = {"opportunity_id": oid, "opportunity_revision": 1, "trust_receipt_id": self.rid, "angle_id": "angle-1",
                "selection_digest": contracts.digest([oid, "angle-1"]), "channel_id": "owned-account", "platform": "Threads",
                "context_digest": op["context_digest"],
                "accepted_at": opportunities.iso(at + 1), "goal": "Go viral and make money"}
            if exposure:
                binding["exposure_id"] = eid
            if decision:
                result = {"source_id": sid, "exposure_id": eid if exposure else None}
                cur.execute("""INSERT INTO pr_trend_opportunity_decisions(workspace_id,scope_key,object_id,revision,idempotency_key,decision,actor_id,result,created_at)
                    VALUES(%s,%s,%s,1,%s,%s,%s,%s::jsonb,to_timestamp(%s))""",
                    (self.wid, self.scope, oid, oid, decision, self.actor, json.dumps(result), at + 1))
            self.state["sources"].append({"id": sid, "active": True, "origin": {"trendLineage": copy.deepcopy(binding)}})
        self.created.append((oid, eid))
        return binding

    def publication(self, binding, *, days=2, value=50, choose=True, measured=True, changed=False, text="What changed?", paid=False):
        stamp = self.now - days * 86400
        jid = "job-" + uuid.uuid4().hex
        manifest = {"channelId": "owned-account", "platform": "Threads", "variantId": jid, "payload": {"text": text, "language": "en"},
            "contentType": {"id": "opinion"}, "timing": {"timestamp": stamp}, "paidPromotion": paid,
            "trendLineage": [copy.deepcopy(binding)],
            "trendPublication": {"variantRevision": 2, "textDigest": contracts.digest(text), "channelId": "owned-account", "platform": "Threads", "treatmentChanged": changed}}
        job = {"id": jid, "state": "verified", "providerReference": "native-" + jid, "verifiedAt": stamp, "manifest": manifest}
        self.state["phase2"]["jobs"].append(job)
        if choose:
            learning.record_metric_choice(self.state, self.actor, {"selection_digest": binding["selection_digest"], "channel_id": "owned-account",
                "provider": "threads", "metric": "views", "definition_version": "2026-09", "window": "24h", "objective": "reach"}, stamp - 60)
        if measured:
            self.metric(job, value, stamp + 86400)
        return job

    def metric(self, published_job, value, observed, **changes):
        p = {"wid": self.wid, "account": "owned-account", "provider": "threads", "post": published_job["providerReference"], "job": published_job["id"],
             "metric": "views", "definition": "2026-09", "value": value, "unit": "count", "availability": "available",
             "observed": observed, "ingested": observed + 1, "window": "24h"} | changes
        with self.connect() as db:
            db.execute("""INSERT INTO pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,
                value,unit,availability,observed_at,ingested_at,read_offset) VALUES(%(wid)s,%(account)s,%(provider)s,%(post)s,%(job)s,%(metric)s,
                %(definition)s,%(value)s,%(unit)s,%(availability)s,to_timestamp(%(observed)s),to_timestamp(%(ingested)s),%(window)s)""", p)

    def test_denominator_joins_persisted_exposure_decision_and_exact_publication(self):
        self.event(); self.event("dismiss"); self.event("save")
        accepted = self.event("accept"); self.publication(accepted)
        self.event("accept", exposure=False)
        result = self.view()
        self.assertEqual(result["denominator"], {"exposures": 4, "accepted": 1, "dismissed": 1, "unaccepted": 1, "unknown": 1,
            "accepted_without_exposure": 1, "dismissed_without_exposure": 0, "unknown_without_exposure": 0})
        observed = next(e for e in result["exposures"] if e["decision"] == "accepted")["outcomes"][0]
        self.assertEqual((observed["state"], observed["value"], observed["publication"]["variant_revision"]), ("measured", 50, 2))
        self.assertFalse(result["causal"]); self.assertFalse(result["durable_strategy"])
        self.assertFalse(result["coverage"]["historical_denominator_complete"])

    def test_missing_delayed_unpublished_and_unselected_never_zero(self):
        self.event("accept")
        self.publication(self.event("accept"), choose=False)
        self.publication(self.event("accept"), days=.5, measured=False)
        self.publication(self.event("accept"), measured=False)
        job = self.publication(self.event("accept"), measured=False)
        self.metric(job, None, self.now - 100, availability="unavailable")
        result = self.view()
        self.assertEqual(result["outcome_states"], {"objective_unselected": 1, "pending_horizon": 1, "delayed": 1, "unavailable": 1})
        self.assertTrue(all(o["value"] is None for e in result["exposures"] for o in e["outcomes"]))
        self.assertIn("not_published", [e.get("publication_coverage") for e in result["exposures"]])

    def test_same_published_revision_native_identity_definition_and_cutoff_guards(self):
        job = self.publication(self.event("accept"), measured=False)
        for changes in ({"post": "different"}, {"job": "other-job"}, {"account": "foreign-account"},
                        {"definition": "foreign-definition"}, {"window": "7d"}, {"ingested": self.now + 1}):
            self.metric(job, 999, self.now - 10, **changes)
        self.assertEqual(self.view()["outcome_states"], {"delayed": 1})
        self.metric(job, 42, self.now - 100)
        self.assertEqual(self.view()["exposures"][0]["outcomes"][0]["value"], 42)
        job["manifest"]["payload"]["text"] = "A later corrected text"
        self.assertEqual(self.view()["outcome_states"], {"invalid_published_revision": 1})

    def test_unchosen_freeform_goal_and_posthoc_metric_choice_do_not_measure(self):
        binding = self.event("accept")
        job = self.publication(binding, choose=False)
        result = self.view(); self.assertEqual(result["outcome_states"], {"objective_unselected": 1})
        learning.record_metric_choice(self.state, self.actor, {"selection_digest": binding["selection_digest"], "channel_id": "owned-account",
            "provider": "threads", "metric": "views", "definition_version": "2026-09", "window": "24h", "objective": "reach"}, self.now)
        self.assertEqual(self.view()["outcome_states"], {"objective_unselected": 1})
        job["manifest"]["trendLineage"][0]["goal"] = "views"
        self.assertEqual(self.view()["outcome_states"], {"objective_unselected": 1})

    def test_changed_and_unknown_treatment_not_credited_to_original_hypothesis(self):
        changed = self.publication(self.event("accept"), changed=True)
        unknown = self.publication(self.event("accept")); del unknown["manifest"]["trendPublication"]["treatmentChanged"]
        mismatch = self.publication(self.event("accept")); mismatch["manifest"]["trendLineage"][0]["angle_id"] = "changed-angle"
        result = self.view(); self.assertEqual(Counter(o["treatment_state"] for e in result["exposures"] for o in e["outcomes"]), Counter(changed=2, unknown=1))
        self.assertEqual(learning.hypotheses(result, self.now), [])

    def test_native_rate_requires_explicit_denominator_and_matching_observations(self):
        binding = self.event("accept"); job = self.publication(binding, measured=False, choose=False)
        payload = {"selection_digest": binding["selection_digest"], "channel_id": "owned-account", "provider": "threads", "metric": "replies",
            "denominator_metric": "views", "definition_version": "2026-09", "window": "24h", "objective": "conversation"}
        learning.record_metric_choice(self.state, self.actor, payload, job["verifiedAt"] - 60)
        self.metric(job, 10, self.now-10, metric="replies")
        self.metric(job, 0, self.now-10)
        self.assertEqual(self.view()["exposures"][0]["outcomes"][0]["reason"], "zero_denominator")
        self.metric(job, 100, self.now-5)
        self.assertEqual(self.view()["exposures"][0]["outcomes"][0]["value"], .1)

    def test_current_rights_revocation_and_tenant_membership_are_read_gates(self):
        self.publication(self.event("accept"))
        self.assertEqual(self.view()["denominator"]["exposures"], 1)
        with self.connect() as db:
            db.execute("UPDATE pr_trend_source_policies SET revoked_at=now() WHERE scope_key=%s", (self.scope,))
        self.assertEqual(self.view()["denominator"]["exposures"], 0)
        with self.connect() as db, db.cursor() as cur:
            with self.assertRaises(TrendStorageError):
                learning.report(cur, self.wid, str(uuid.uuid4()), self.now, store=self.store)

    def test_account_deletion_blocks_report_and_revoked_channel_suppresses_metric(self):
        self.publication(self.event("accept"))
        self.state["phase2"]["channels"][-1]["revoked"] = True
        self.assertEqual(self.view()["outcome_states"], {"account_unavailable": 1})
        self.state["accountDeletion"] = {"requested": True}
        with self.assertRaises(TrendStorageError): self.view()

    def test_reuses_existing_hypotheses_without_persistence_or_adoption(self):
        for n in range(12):
            self.publication(self.event("accept", days=40), days=n+2,
                text="Why this?" if n%2 else "Observed statement", value=900 if n%2 else 400)
        before = copy.deepcopy(self.state)
        result = self.view(); found = learning.hypotheses(result, self.now)
        self.assertTrue(any(h["sample_a"] == h["sample_b"] == 6 for h in found))
        self.assertTrue(all(h["dimension"].startswith("trend_") and "not causal" in h["statement"] for h in found))
        self.assertEqual(before, self.state)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_strategy_hypotheses WHERE workspace_id=%s", (self.wid,)).fetchone()[0], 0)
        recent = min((o for e in result["exposures"] for o in e["outcomes"]), key=lambda o: self.now-o["publication"]["published_at"])
        self.assertGreater(recent["baseline"]["count"], 0)

    def test_baseline_excludes_future_availability_and_unknown_promotion(self):
        self.publication(self.event("accept"), days=2)
        old = self.publication(self.event("accept"), days=4, paid=None)
        self.publication(self.event("accept"), days=5, measured=False)
        result = self.view()
        self.assertTrue(all(o.get("baseline", {}).get("count", 0) == 0 for e in result["exposures"] for o in e["outcomes"]))

    def test_same_native_post_under_two_jobs_is_not_double_attributed(self):
        job = self.publication(self.event("accept"))
        duplicate = copy.deepcopy(job); duplicate["id"] = "corrected-job-alias"
        self.state["phase2"]["jobs"].append(duplicate)
        result = self.view()
        self.assertEqual(result["outcome_states"], {"ambiguous_native_publication": 2})
        self.assertTrue(all(o["value"] is None for e in result["exposures"] for o in e["outcomes"]))
        self.assertEqual(learning.hypotheses(result, self.now), [])


from collections import Counter

if __name__ == "__main__":
    unittest.main()
