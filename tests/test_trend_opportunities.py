import copy
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.trends import opportunities, relevance
from test_trend_service import make_service, assert_schema, WID, TID, RID, OID, ACTOR, NOW

PAYLOAD = {"revision": 1, "angle_id": "angle-1", "channel_id": "channel-1", "goal": "Share a real baking experiment", "idempotency_key": "accept-1"}


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.repo, self.store = make_service()

    def test_accept_reuses_existing_source_and_factpack_without_approving_claims(self):
        one = self.svc.accept(WID, "session", OID, PAYLOAD)
        two = self.svc.accept(WID, "session", OID, PAYLOAD)
        assert_schema(self, "accepted_opportunity_response", one)
        self.assertEqual(one["data"]["source_id"], two["data"]["source_id"])
        self.assertTrue(two["data"]["existing"])
        self.assertEqual(len(self.repo.state["sources"]), 1)
        source = self.repo.state["sources"][0]
        self.assertEqual(source["facts"], [])
        self.assertTrue(source["origin"]["factPack"]["claims"])
        self.assertFalse(any(c["usableForDraft"] for c in source["origin"]["factPack"]["claims"]))
        self.assertEqual(source["origin"]["trendLineage"]["trust_receipt_id"], RID)
        self.assertEqual(source["origin"]["canonicalBrief"]["goal"], PAYLOAD["goal"])

    def test_duplicate_expiry_revocation_context_and_selection_rechecked(self):
        self.svc.accept(WID, "session", OID, PAYLOAD)
        old = copy.deepcopy(self.store.rows)
        for mutate, expected in [
            (lambda: self.store.rows["opportunity", OID].update(expires_at=opportunities.iso(NOW)), 410),
            (lambda: self.store.rows["receipt", RID].update(validity="revoked", payload=None), 410),
            (lambda: self.repo.state["brandHub"].update(audience="changed"), 409),
        ]:
            mutate()
            with self.assertRaises(AlphaError) as raised:
                self.svc.accept(WID, "session", OID, PAYLOAD)
            self.assertEqual(raised.exception.status, expected)
            self.store.rows = copy.deepcopy(old)
        self.repo.state["brandHub"]["audience"] = ""
        with self.assertRaises(AlphaError) as raised:
            self.svc.accept(WID, "session", OID, {**PAYLOAD, "angle_id": "wrong"})
        self.assertEqual(raised.exception.status, 400)

    def test_wrong_role_revision_and_channel_never_create(self):
        for role in ("viewer", "approver"):
            self.repo.role = role
            with self.assertRaises(AlphaError) as raised:
                self.svc.accept(WID, "session", OID, PAYLOAD)
            self.assertEqual(raised.exception.status, 403)
        self.repo.role = "editor"
        for payload in ({**PAYLOAD, "revision": 2}, {**PAYLOAD, "channel_id": "foreign"}):
            with self.assertRaises(AlphaError):
                self.svc.accept(WID, "session", OID, payload)
        self.assertEqual(self.repo.state["sources"], [])

    def test_seven_dimensions_remain_separate_and_context_does_not_self_invalidate(self):
        state = self.repo.state
        initial = relevance.context_revision(state)
        result = relevance.evaluate({"canonical_topic": "baking"}, state)
        self.assertEqual(set(result["dimensions"]), set(relevance.DIMENSIONS))
        self.assertFalse(result["qualified"])
        self.svc.accept(WID, "session", OID, PAYLOAD)
        self.assertEqual(initial, relevance.context_revision(self.repo.state))

    def test_lineage_frozen_and_tampering_invalidates(self):
        source_id = self.svc.accept(WID, "session", OID, PAYLOAD)["data"]["source_id"]
        lineage = opportunities.lineage(self.repo.state, [source_id])
        variant = {"revision": 1, "text": "Our own experiment", "trendLineage": lineage, "scoutLineage": [{"executionPlan": {"id": "old-plan"}}]}
        manifest = {"platform": "Bluesky", "channelId": "channel-1"}
        opportunities.freeze_manifest(self.repo.state, variant, manifest, NOW)
        self.assertTrue(opportunities.manifest_current(self.repo.state, variant, manifest, NOW))
        variant["scoutLineage"][0]["executionPlan"]["id"] = "mutated"
        self.assertEqual(manifest["scoutLineage"][0]["executionPlan"]["id"], "old-plan")
        self.assertFalse(opportunities.manifest_current(self.repo.state, variant, manifest, NOW))
        self.assertFalse(opportunities.manifest_current(self.repo.state, variant, manifest, NOW+7200))

    def test_weekly_only_attaches_explicit_selected_trend_source(self):
        sid = self.svc.accept(WID, "session", OID, PAYLOAD)["data"]["source_id"]
        recipe = {"sourceIds": [sid]}
        week = {"slots": [{"channelId": "channel-1", "platform": "Bluesky", "sourceIds": ["factual-source"], "state": "blocked"},
                          {"channelId": "other", "platform": "Bluesky", "sourceIds": []}]}
        opportunities.attach_weekly_intent(self.repo.state, recipe, week, NOW)
        self.assertEqual(week["slots"][0]["sourceIds"], ["factual-source", sid])
        self.assertEqual(week["slots"][0]["state"], "blocked")
        self.assertEqual(week["slots"][0]["trendLineage"][0]["trust_receipt_id"], RID)
        self.assertEqual(week["slots"][1]["sourceIds"], [])
        untouched = {"slots": [{"channelId": "channel-1", "platform": "Bluesky", "sourceIds": []}]}
        opportunities.attach_weekly_intent(self.repo.state, {"sourceIds": []}, untouched, NOW)
        self.assertEqual(untouched["slots"][0]["sourceIds"], [])

    def test_disabled_candidate_adapter_never_reads_database(self):
        from types import SimpleNamespace
        self.assertEqual(opportunities.refresh_workspace_candidates(SimpleNamespace(), values={})["status"], "disabled")

    def test_distinct_opportunities_do_not_collide_with_ordinary_source_deduplication(self):
        import uuid
        first = self.svc.accept(WID, "session", OID, PAYLOAD)
        other_id = str(uuid.uuid4())
        other = copy.deepcopy(self.store.rows["opportunity", OID])
        other.update(object_id=other_id, projection_id=other_id)
        other["payload"]["id"] = other_id
        self.store.rows["opportunity", other_id] = other
        second = self.svc.accept(WID, "session", other_id, {**PAYLOAD, "idempotency_key": "distinct-choice"})
        self.assertNotEqual(first["data"]["source_id"], second["data"]["source_id"])
        self.assertEqual(len(self.repo.state["sources"]), 2)
