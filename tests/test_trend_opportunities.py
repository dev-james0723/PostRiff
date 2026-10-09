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


USER = {"revision": 1, "user_angle": {"title": "My own two-loaf test", "contribution": "Bake both hydrations and show my crumb."},
        "channel_id": "channel-1", "goal": "Share a real baking experiment", "idempotency_key": "user-accept-1"}


class UserAuthoredAngleTests(unittest.TestCase):
    """Option A: save a verified production-shaped candidate with a person's own angle (no model)."""

    def setUp(self):
        self.svc, self.repo, self.store = make_service()
        op = self.store.rows["opportunity", OID]["payload"]
        # Production shape (persist_workspace_candidates): candidate, no angles, unqualified.
        op.update(state="candidate", angles=[], qualified=False)
        op.pop("executable_ready", None)

    def test_candidate_user_angle_accept_binds_receipt_context(self):
        read = self.svc.opportunity(WID, "session", OID)["data"]
        self.assertEqual((read["state"], read["angles"], read["workspace_fit"]["sufficient"]), ("candidate", [], False))
        result = self.svc.accept(WID, "session", OID, USER)
        assert_schema(self, "accepted_opportunity_response", result)
        self.assertFalse(result["data"]["existing"])
        sources = self.repo.state["sources"]
        self.assertEqual(len(sources), 1)
        binding = sources[0]["origin"]["trendLineage"]
        self.assertEqual((binding["opportunity_id"], binding["opportunity_revision"], binding["trust_receipt_id"]), (OID, 1, RID))
        self.assertEqual(binding["context_digest"], relevance.context_revision(self.repo.state))
        self.assertEqual(binding["angle_authorship"], "user_authored")
        self.assertEqual(binding["angle"]["title"], USER["user_angle"]["title"])
        self.assertEqual(binding["angle"]["semantic_qualification"], "unqualified")
        self.assertTrue(binding["selection_digest"])
        decision = self.store.decisions[USER["idempotency_key"]]["result"]
        self.assertEqual(decision["source_id"], result["data"]["source_id"])
        self.assertTrue(decision["selection_digest"])
        self.assertEqual(self.store.rows["opportunity", OID]["payload"]["state"], "candidate", "no promotion or model call")
        after = self.svc.opportunity(WID, "session", OID)["data"]
        self.assertEqual((after["state"], after["source_id"]), ("accepted", result["data"]["source_id"]))

    def test_refresh_and_double_click_never_duplicate(self):
        one = self.svc.accept(WID, "session", OID, USER)
        two = self.svc.accept(WID, "session", OID, USER)
        self.assertEqual(one["data"]["source_id"], two["data"]["source_id"])
        self.assertTrue(two["data"]["existing"])
        for changed in ({**USER, "user_angle": {**USER["user_angle"], "title": "Different"}},
                        {**USER, "user_angle": {**USER["user_angle"], "title": "Different"}, "idempotency_key": "user-accept-2"}):
            with self.assertRaises(AlphaError) as raised:
                self.svc.accept(WID, "session", OID, changed)
            self.assertEqual(raised.exception.status, 409)
        self.assertEqual(len(self.repo.state["sources"]), 1)

    def test_invalid_or_ambiguous_angle_input_is_refused(self):
        for payload in ({**USER, "angle_id": "angle-1"}, {k: v for k, v in USER.items() if k != "user_angle"},
                        {**USER, "user_angle": {"title": " ", "contribution": "x"}},
                        {**USER, "user_angle": {"title": "t", "contribution": "x", "evidence": "copied"}},
                        {**USER, "user_angle": {"title": "t" * 201, "contribution": "x"}},
                        {**USER, "user_angle": "my angle"}):
            with self.assertRaises(AlphaError) as raised:
                self.svc.accept(WID, "session", OID, payload)
            self.assertEqual(raised.exception.status, 400, payload)
        # A model-angle selection still needs an eligible/suggested opportunity.
        with self.assertRaises(AlphaError) as raised:
            self.svc.accept(WID, "session", OID, PAYLOAD)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.repo.state["sources"], [])

    def test_unverified_or_viewer_cannot_save(self):
        self.store.rows["receipt", RID]["verification_state"] = "pending"
        with self.assertRaises(AlphaError) as raised:
            self.svc.accept(WID, "session", OID, USER)
        self.assertEqual(raised.exception.status, 410)
        self.store.rows["receipt", RID]["verification_state"] = "verified"
        self.repo.role = "viewer"
        with self.assertRaises(AlphaError) as raised:
            self.svc.accept(WID, "session", OID, USER)
        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(self.repo.state["sources"], [])

    def test_saved_idea_becomes_draft_with_lineage_and_lab_still_works(self):
        from postriff_phase2.growth.trends.service import validate_stored_bindings
        source_id = self.svc.accept(WID, "session", OID, USER)["data"]["source_id"]
        bindings = opportunities.lineage(self.repo.state, [source_id])
        self.assertEqual(len(bindings), 1)
        # The Ideas writer validates these exact bindings in its own transaction.
        validate_stored_bindings(self.repo.connection_factory, self.repo, WID, ACTOR, self.repo.state, bindings, NOW,
                                 store_factory=lambda _: self.store)
        draft = {"id": "draft-user-angle", "text": "My own two loaves: what changed and what I learned.", "revision": 1,
                 "platform": "Bluesky", "language": "en", "sourceIds": [source_id], "trendLineage": bindings}
        self.repo.state["variants"] = [draft]
        manifest = {"platform": "Bluesky", "channelId": "channel-1"}
        opportunities.freeze_manifest(self.repo.state, draft, manifest, NOW)
        self.assertTrue(opportunities.manifest_current(self.repo.state, draft, manifest, NOW))
        self.assertEqual(manifest["trendLineage"][0]["angle_authorship"], "user_authored")
        # Reopen: the opportunity reports the saved source and the one linked draft.
        read = self.svc.opportunity(WID, "session", OID)["data"]
        self.assertEqual((read["source_id"], read["draft_id"]), (source_id, "draft-user-angle"))
        self.svc.values["RAFII_TREND_MODEL_ENRICHMENT_ENABLED"] = "0"  # deterministic local Lab only
        lab = self.svc.lab_create(WID, "session", {"draft_id": "draft-user-angle", "draft_revision": 1, "opportunity_id": OID,
                                                   "opportunity_revision": 1, "target_platform": "bluesky", "idempotency_key": "lab-user"})
        self.assertEqual(lab["data"]["draft_id"], "draft-user-angle")
        self.assertEqual(lab["data"]["trust_receipt_id"], RID)


class CandidateRefreshAdmissionTests(unittest.TestCase):
    """The local candidate producer (no model, no provider) follows read admission."""

    class Cursor:
        def __init__(self, enrolled):
            self.enrolled, self.queries, self.result = enrolled, [], []
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, sql, args=()):
            q = " ".join(sql.split())
            self.queries.append((q, args))
            if q.startswith("SELECT to_regclass"):
                self.result = [(True,)]
            elif q.startswith("SELECT workspace_id::text FROM public.pr_feature_enrollments"):
                self.result = [(w,) for w in self.enrolled]
            elif q.startswith("SELECT w.id::text, m.user_id::text"):
                self.result = []
            else:
                raise AssertionError("unexpected SQL " + q[:80])
        def fetchone(self): return self.result[0] if self.result else None
        def fetchall(self): return list(self.result)

    def hosted(self, cursor):
        from contextlib import contextmanager
        from types import SimpleNamespace
        @contextmanager
        def connect():
            yield SimpleNamespace(cursor=lambda: cursor)
        return SimpleNamespace(repository=SimpleNamespace(connection_factory=connect))

    def test_enrolled_workspaces_join_only_while_self_serve_is_open(self):
        on = {"RAFII_TREND_INTELLIGENCE_ENABLED": "1", "RAFII_TREND_RADAR_ENABLED": "1"}
        cursor = self.Cursor([WID])
        self.assertEqual(opportunities.refresh_workspace_candidates(self.hosted(cursor), values=on)["workspaces"], 0)
        self.assertEqual(cursor.queries, [], "closed cohort, no allowlist: no database read")
        opened = {**on, "RAFII_TREND_SELF_SERVE_ENABLED": "1", "RAFII_TREND_SELF_SERVE_MAX_WORKSPACES": "3"}
        opportunities.refresh_workspace_candidates(self.hosted(cursor), values=opened)
        targets = next(args for q, args in cursor.queries if q.startswith("SELECT w.id::text, m.user_id::text"))
        self.assertEqual(targets[0], [WID])
        denied = {**opened, "RAFII_FEATURE_WORKSPACE_DENYLIST": WID}
        cursor = self.Cursor([WID])
        opportunities.refresh_workspace_candidates(self.hosted(cursor), values=denied)
        self.assertFalse([q for q, _ in cursor.queries if q.startswith("SELECT w.id::text, m.user_id::text")])
