"""Release closeout: authenticated enqueue, current-source handoff and metadata. Offline only."""
import copy
import unittest
from unittest.mock import patch
from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.trends.contracts import ContractError
from test_trend_service import make_service, WID, OID, RID, NOW, assert_schema
from test_trend_opportunities import PAYLOAD

class CloseoutTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.repo, self.store = make_service()
        self.body = {"revision": 1, "idempotency_key": "explicit-angle-request", "confirmed": True}

    def test_angle_details_survive_read_and_accepted_source(self):
        angle = self.store.rows["opportunity", OID]["payload"]["angles"][0]
        angle.update(evidence_refs=["evidence-1"], fit={"assessment":"mixed", "reason":"Audience may find a measured experiment useful."},
                     risk={"assessment":"unknown", "reason":"Response is unmeasured."}, uncertainties=["No originality qualification."])
        result = self.svc.opportunity(WID, "session", OID)
        assert_schema(self, "opportunity_response", result)
        shown = result["data"]["angles"][0]
        self.assertEqual(shown["evidence_refs"], angle["evidence_refs"])
        self.assertEqual(shown["relevance"], angle["fit"])
        self.assertEqual(shown["risk"], angle["risk"])
        self.assertEqual(shown["uncertainties"], angle["uncertainties"])
        self.assertEqual(shown["recheck_at"], result["data"]["expires_at"])
        self.svc.accept(WID, "session", OID, PAYLOAD)
        lineage = self.repo.state["sources"][0]["origin"]["trendLineage"]
        self.assertEqual(lineage["angle"], angle)
        self.assertEqual(lineage["channel_id"], PAYLOAD["channel_id"])
        self.assertIn("Do not copy", lineage["do_not_copy"])

    def test_disabled_generation_has_no_model_or_queue_effect(self):
        self.svc.values["RAFII_TREND_MODEL_ENRICHMENT_ENABLED"] = "0"
        before = copy.deepcopy(self.repo.state)
        with patch("postriff_phase2.growth.trends.generation.TrendGeneration._load", side_effect=AssertionError("disabled work")):
            result = self.svc.generate_angles(WID, "session", OID, self.body)
        self.assertEqual(result["data"], {"status":"disabled", "reason":"generation_disabled", "provider_attempts":0})
        self.assertEqual(before, self.repo.state)

    def test_generation_rejects_roles_revision_expiry_and_unknown_input_before_load(self):
        with patch("postriff_phase2.growth.trends.generation.TrendGeneration._load", side_effect=AssertionError("invalid work")):
            for body in ({**self.body,"revision":True}, {**self.body,"text":"untrusted"}, {**self.body,"revision":2}, {**self.body,"confirmed":False}):
                with self.assertRaises(AlphaError): self.svc.generate_angles(WID,"session",OID,body)
            self.repo.role = "viewer"
            with self.assertRaises(AlphaError): self.svc.generate_angles(WID,"session",OID,self.body)
            self.repo.role = "editor"
            self.svc.clock = lambda: NOW+7200
            with self.assertRaises(AlphaError): self.svc.generate_angles(WID,"session",OID,self.body)

    def test_enqueues_only_the_exact_current_opportunity_on_existing_generator(self):
        with patch("postriff_phase2.growth.trends.generation.TrendGeneration") as cls:
            engine = cls.return_value
            engine.enabled.return_value = True
            loaded = {"opportunity":{"object_id":OID,"revision":1}}
            engine._load.return_value = loaded
            engine._cached.return_value = None
            engine._enqueue_loaded.return_value = {"status":"queued","job_id":RID,"provider_attempts":0}
            result = self.svc.generate_angles(WID,"session",OID,self.body)
            self.assertEqual(result["data"]["status"],"queued")
            self.assertEqual(engine._enqueue_loaded.call_args.args[-1], self.body["idempotency_key"])
            self.assertEqual(engine.execute.call_count,0)
            loaded["opportunity"]["revision"] = 2
            with self.assertRaises(AlphaError): self.svc.generate_angles(WID,"session",OID,self.body)
            self.assertEqual(engine._enqueue_loaded.call_count,1)

    def test_missing_facts_does_not_enqueue_or_leak_policy(self):
        with patch("postriff_phase2.growth.trends.generation.TrendGeneration") as cls:
            engine = cls.return_value
            engine.enabled.return_value = True
            engine._load.side_effect = ContractError("generation_approved_facts_required")
            result = self.svc.generate_angles(WID,"session",OID,self.body)
            self.assertEqual(result["data"]["status"],"needs_facts")
            engine._enqueue_loaded.assert_not_called()

    def test_job_status_is_scoped_and_never_runs_provider(self):
        with patch.object(self.repo,"fetchone",return_value=("succeeded",)):
            result = self.svc.generation_status(WID,"session",RID)
            self.assertEqual(result["data"]["status"],"succeeded")
        self.assertIn("scope_key=%s AND kind=%s AND job_id=%s",self.repo.queries[-1])
        with self.assertRaises(AlphaError): self.svc.generation_status(WID,"session",RID)

    def test_exact_campaign_handoff_preserves_context_but_edit_or_source_change_invalidates(self):
        from postriff_phase2.growth.trends import opportunities, relevance
        sid = self.svc.accept(WID,"session",OID,PAYLOAD)["data"]["source_id"]
        state = self.repo.state
        before = relevance.context_revision(state)
        campaign = {"id":"campaign","version":1,"goal":PAYLOAD["goal"],"audience":state["brandHub"]["audience"],"facts":{}}
        opportunities.bind_campaign_handoff(state,campaign,[sid],NOW)
        self.assertIn("trendHandoff",campaign)
        state.setdefault("raffi", {}).setdefault("campaignPlanning", {"campaigns": []})["campaigns"].append(campaign)
        self.assertEqual(relevance.context_revision(state), before)
        opportunities.validate_lineage(state,opportunities.lineage(state,[sid]),NOW)
        campaign["goal"] = "A different goal"
        self.assertNotEqual(relevance.context_revision(state), before)
        with self.assertRaises(AlphaError): opportunities.validate_lineage(state,opportunities.lineage(state,[sid]),NOW)
        campaign["goal"] = PAYLOAD["goal"]
        state["sources"][0]["text"] += "edited"
        self.assertNotEqual(relevance.context_revision(state), before)

    def test_changed_campaign_brief_and_expired_source_never_get_exception(self):
        from postriff_phase2.growth.trends import opportunities
        sid = self.svc.accept(WID,"session",OID,PAYLOAD)["data"]["source_id"]
        c = {"id":"campaign","version":1,"goal":"new goal","audience":self.repo.state["brandHub"]["audience"],"facts":{}}
        opportunities.bind_campaign_handoff(self.repo.state,c,[sid],NOW)
        self.assertNotIn("trendHandoff",c)
        c["goal"] = PAYLOAD["goal"]
        with self.assertRaises(AlphaError): opportunities.bind_campaign_handoff(self.repo.state,c,[sid],NOW+7200)
        self.assertNotIn("trendHandoff",c)

    def test_campaign_command_creates_draft_with_source_and_no_self_invalidation(self):
        from postriff_phase2 import campaigns
        from postriff_phase2.growth.trends import opportunities, relevance
        self.repo.state["brandHub"]["audience"] = "Baking students"
        self.repo.state["phase2"]["channels"][0]["platform"] = "Threads"
        self.store.rows["opportunity",OID]["payload"]["platform_targets"] = ["Threads"]
        self.store.rows["opportunity",OID]["payload"]["context_digest"] = relevance.context_revision(self.repo.state)
        sid = self.svc.accept(WID,"session",OID,PAYLOAD)["data"]["source_id"]
        state = self.repo.state
        saved = campaigns.apply_action(state,"raffi_recurrence_save",{
            "name":"Original experiment", "goal":PAYLOAD["goal"], "audience":"Baking students", "facts":{},
            "schedule":{"kind":"weekly","weekdays":["Monday"],"localTime":"09:00","timeZone":"UTC"},
            "destinations":[{"platform":"Threads","channelId":"channel-1","language":"en"}],
            "route":"offline-fixture", "maxCostUsdMicro":0, "sourceIds":[sid]
        },"owner",NOW)
        self.assertEqual(saved["status"],"draft")
        self.assertEqual(state["raffi"]["campaignPlanning"]["recurringTasks"][0]["contextSourceIds"],[sid])
        opportunities.validate_lineage(state,opportunities.lineage(state,[sid]),NOW)
        self.assertEqual(state["variants"],[])
