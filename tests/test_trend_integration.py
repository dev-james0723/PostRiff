import copy
import os
import json
import time
import uuid
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.trends import opportunities
from postriff_phase2.growth.trends.service import validate_stored_bindings, validate_changed_variants
from postriff_phase2.growth import scout_runtime, scout_outcomes
from test_trend_service import make_service, assert_schema, WID, ACTOR, RID, TID, OID, NOW
from test_trend_opportunities import PAYLOAD


@unittest.skipUnless(os.environ.get("TREND_SERVICE_TEST_DSN"), "explicit disposable service PostgreSQL DSN required")
class DurableServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        from postriff_phase2.hosted import PostgresWorkspaceRepository, HostedPhase2Commands
        from postriff_phase2.ideas import IdeasService
        from postriff_phase2.coworker.service import CoworkerService
        from postriff_phase2.growth.trends.store import TrendStore
        from postriff_phase2.growth.trends import contracts, relevance
        from postriff_phase2.growth.trends.service import TrendService
        from test_trend_service import END, EID, SCOPE, fixture_row
        dsn = os.environ["TREND_SERVICE_TEST_DSN"]
        params = conninfo_to_dict(dsn)
        permitted = (params.get("host") == "/private/tmp" and params.get("port") == "56447" and params.get("dbname", "").startswith("trend_pipeline_service_")) or (params.get("host") == "127.0.0.1" and params.get("port") == "56451" and params.get("dbname", "").startswith("trend_exposure_")) or (params.get("host"), params.get("port"), params.get("dbname")) == ("127.0.0.1", "55438", "postgres")
        if not permitted or set(params)-{"host","port","dbname","user"} or any(k in os.environ for k in ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR", "PGOPTIONS")):
            raise ValueError("Only explicit disposable service/exposure databases on approved local ports are allowed")
        cls.dsn = dsn
        root = Path(__file__).parents[1]
        with psycopg.connect(dsn) as db:
            if not db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]:
                harness = (root/"tests/phase2/rls.sql").read_text()
                setup = harness[harness.index("create schema auth;"):harness.index("\\ir ")]
                db.execute(setup)
                for line in harness.splitlines():
                    if line.startswith("\\ir "):
                        db.execute((root/"tests/phase2"/line[4:]).resolve().read_text())
            if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
                db.execute((root/"migrations/postriff/040_social_trend_intelligence.sql").read_text())
        ids = {key: str(uuid.uuid4()) for key in (WID, ACTOR, TID, RID, OID, EID)}
        cls.wid, cls.actor, cls.tid, cls.rid, cls.oid = (ids[k] for k in (WID, ACTOR, TID, RID, OID))
        at = time.time(); expiry = opportunities.iso(at+3600); start = opportunities.iso(at-86400)
        # This fixture is explicitly synthetic; all durable writes use real PostgreSQL APIs.
        fixture_svc, fixture_repo, fixture_store = make_service()
        def convert(value):
            raw = json.dumps(value)
            for old,new in ids.items(): raw = raw.replace(old,new)
            for old,new in ((END,expiry), (opportunities.iso(NOW-3600), opportunities.iso(at-3600)),
                            (opportunities.iso(NOW-100), opportunities.iso(at-100)), (opportunities.iso(NOW), opportunities.iso(at)),
                            (opportunities.iso(NOW-10), opportunities.iso(at-10))): raw=raw.replace(old,new)
            return json.loads(raw)
        state = convert(fixture_repo.state)
        role = "trend_service_" + uuid.uuid4().hex[:10]
        with psycopg.connect(dsn) as db:
            db.execute("CREATE ROLE " + role + " NOSUPERUSER NOBYPASSRLS INHERIT")
            db.execute("GRANT service_role TO " + role)
            for table in ("pr_workspaces", "pr_profiles", "pr_memberships"):
                db.execute("CREATE POLICY " + role + " ON " + table + " FOR ALL TO " + role + " USING(true) WITH CHECK(true)")
            db.execute("INSERT INTO auth.users(id) VALUES(%s)",(cls.actor,))
            db.execute("INSERT INTO pr_profiles(user_id) VALUES(%s)",(cls.actor,))
            db.execute("INSERT INTO pr_workspaces(id,state) VALUES(%s,%s::jsonb)",(cls.wid,json.dumps(state)))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')",(cls.wid,cls.actor))
        def connect():
            db=psycopg.connect(dsn);db.execute("SET ROLE " + role);return db
        cls.connect=staticmethod(connect)
        store=TrendStore(connect,offline_replay=True)
        scope="workspace:"+cls.wid;store.ensure_scope(scope)
        provider="service-fixture-"+uuid.uuid4().hex[:8]
        rights={name:{"state":"allow","policy_ref":"synthetic-v1","audience_scope":scope,"expires_at":expiry} for name in contracts.PERMISSIONS}
        store.register_contract(provider,"1",list(contracts.PERMISSIONS),start,expiry)
        store.register_policy({"scope_key":scope,"provider_id":provider,"version":"1","rights":rights,"effective_at":start,"expires_at":expiry,"retention_seconds":86400,"readiness":"ready"},provider_contract_version="1")
        source_payload={"platform":"bluesky","native_id":"fixture","author_status":"known","author_key":"author-1","text":"A synthetic baking observation.","canonical_url":"https://example.test/post","language":"en"}
        obs={"observation_id":ids[EID],"scope_key":scope,"provider_id":provider,"provider_contract_version":"1","source_policy_version":"1","source_identity":"fixture-post","revision_identity":"r1","revision_sequence":1,"kind":"raw_post","operation":"create","event_at":opportunities.iso(at-100),"received_at":opportunities.iso(at-90),"available_at":opportunities.iso(at-80),"time_basis":"provider_event","coverage_epoch":"fixture","provenance":{"access_method":"fixture"},"retention_until":expiry,"rights":rights,"deletion_key":"fixture-post","payload":source_payload,"payload_digest":contracts.digest(source_payload),"schema_version":contracts.SCHEMA_VERSION}
        store.put_observation(obs)
        manifest=store.put_manifest(scope,[{"scope_key":scope,"node_id":ids[EID]}],decision_cutoff=opportunities.iso(at-10),available_at=opportunities.iso(at-10),retention_until=expiry)
        method="fixture-"+uuid.uuid4().hex[:12];artifact=contracts.digest({"fixture":True})
        store.put_method(method,"1",artifact,{"fixture":True})
        common={"scope_key":scope,"manifest_id":manifest["manifest_id"],"method_id":method,"method_version":"1","decision_cutoff":opportunities.iso(at-10),"available_at":opportunities.iso(at-10),"retention_until":expiry,"receipt_id":cls.rid}
        receipt=convert(fixture_store.rows["receipt",RID]["payload"]);receipt["schema"]="rafii.trend-trust-receipt.v2"
        store.put_receipt({**common,"payload":receipt})
        store.record_verification(scope,cls.rid,recomputed_digest=contracts.digest(receipt),input_manifest_digest=manifest["digest"],method_artifact_digest=artifact)
        trend=convert(fixture_store.rows["trend",TID]["payload"])
        trend["evidence"][0]["rights"]=rights
        store.put_projection({**common,"kind":"trend","object_id":cls.tid,"revision":1,"payload":trend})
        op=convert(fixture_store.rows["opportunity",OID]["payload"]);op["context_digest"]=relevance.context_revision(state)
        store.put_projection({**common,"kind":"opportunity","object_id":cls.oid,"revision":1,"payload":op})
        commands=HostedPhase2Commands(clock=time.time)
        def verify(token):
            if token!="fixture-session": raise AlphaError("Unauthenticated",401)
            return cls.actor
        repository=PostgresWorkspaceRepository(connect,verify,commands)
        hosted=SimpleNamespace(repository=repository,connection_factory=connect,commands=commands,ideas=SimpleNamespace(_state=IdeasService._state,_member=IdeasService._member))
        values={**fixture_svc.values,"RAFII_TREND_WORKSPACE_ALLOWLIST":cls.wid}
        cw=CoworkerService(hosted,values=values,clock=time.time)
        cls.svc=TrendService(cw,cursor_secret=b"disposable-test-signing-key-32-bytes")

    def test_real_authenticated_reads_accept_and_local_lab_transaction(self):
        from postriff_phase2.growth.trends import contracts
        assert_schema(self,"trend_response",self.svc.get(self.wid,"fixture-session",self.tid))
        with self.assertRaises(AlphaError) as error:
            self.svc.get(self.wid,"wrong-session",self.tid)
        self.assertEqual(error.exception.status,401)
        accepted=self.svc.accept(self.wid,"fixture-session",self.oid,PAYLOAD)
        assert_schema(self,"accepted_opportunity_response",accepted)
        again=self.svc.accept(self.wid,"fixture-session",self.oid,PAYLOAD)
        self.assertTrue(again["data"]["existing"])
        with self.svc.repository.transaction("fixture-session",self.wid) as (cur,row,actor):
            state=copy.deepcopy(row[1]);sid=accepted["data"]["source_id"]
            draft_id=uuid.uuid4().hex
            state["variants"]=[{"id":draft_id,"text":"An original synthetic draft.","revision":1,"platform":"Bluesky","trendLineage":opportunities.lineage(state,[sid])}]
            cur.execute("UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s",(json.dumps(state),self.wid))
        payload={"draft_id":draft_id,"draft_revision":1,"opportunity_id":self.oid,"opportunity_revision":1,"target_platform":"Bluesky","idempotency_key":"local-lab-1"}
        lab=self.svc.lab_create(self.wid,"fixture-session",payload)
        assert_schema(self,"lab_run_response",lab)
        self.assertEqual(lab["data"]["state"],"completed")
        self.assertEqual(lab["data"]["id"],self.svc.lab_create(self.wid,"fixture-session",payload)["data"]["id"])
        with self.connect() as db:
            saved=db.execute("SELECT state,provider_id,reservation_id FROM pr_trend_jobs WHERE scope_key=%s AND kind='trend.opportunity_lab.local'",("workspace:"+self.wid,)).fetchall()
        self.assertEqual(saved,[("succeeded",None,None)])


    def test_real_stored_episode_projects_private_unknown_workspace_candidate(self):
        from postriff_phase2.growth.trends.store import TrendStore
        with self.svc.repository.transaction("fixture-session", self.wid) as (cur, row, actor):
            state = copy.deepcopy(row[1])
            now = time.time()
            store = TrendStore(self.connect)
            result = opportunities.persist_workspace_candidates(store, cur, self.wid, actor, state, [self.tid], now)
            replay = opportunities.persist_workspace_candidates(store, cur, self.wid, actor, state, [self.tid], time.time())
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["existing"])
        self.assertTrue(replay[0]["existing"])
        candidate = self.svc.opportunity(self.wid, "fixture-session", result[0]["id"])
        assert_schema(self, "opportunity_response", candidate)
        self.assertEqual(candidate["data"]["state"], "candidate")
        self.assertEqual(candidate["data"]["angles"], [])
        self.assertFalse(candidate["data"]["workspace_fit"]["sufficient"])
        self.assertEqual(candidate["data"]["trust_receipt_id"], self.rid)
        with self.connect() as db:
            refs = db.execute("SELECT input_scope_key,input_node_id FROM pr_trend_manifest_inputs m JOIN pr_trend_projections p USING(scope_key,manifest_id) WHERE p.kind='opportunity' AND p.object_id=%s", (result[0]["id"],)).fetchall()
        self.assertEqual(len(refs), 2)
        adapter = opportunities.refresh_workspace_candidates(self.svc.hosted, values=self.svc.values)
        self.assertEqual(adapter["unavailable"], 0)
        self.assertGreaterEqual(adapter["existing"], 1)



    def test_real_selective_lab_patch_uses_existing_revision_checked_variant_edit(self):
        from postriff_phase2.growth.trends import opportunity_lab
        from postriff_phase2.growth.trends.store import TrendStore
        sid = self.svc.accept(self.wid, "fixture-session", self.oid, PAYLOAD)["data"]["source_id"]
        phrase = self.svc.get(self.wid, "fixture-session", self.tid)["data"]["evidence"][0]["excerpt"]
        did = "lab-selective-" + uuid.uuid4().hex
        with self.svc.repository.transaction("fixture-session", self.wid) as (cur, row, actor):
            state = copy.deepcopy(row[1])
            state["variants"] = [{"id": did, "text": "My independently supplied observation. " + phrase, "revision": 1,
                "platform": "Bluesky", "language": "en", "sourceIds": [sid], "unknowns": [], "warnings": [], "revisions": [],
                "needsReview": False, "trendLineage": opportunities.lineage(state, [sid])}]
            cur.execute("UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), self.wid))
        request = {"draft_id": did, "draft_revision": 1, "opportunity_id": self.oid, "opportunity_revision": 1,
                   "target_platform": "Bluesky", "idempotency_key": "selective-local-1"}
        result = self.svc.lab_create(self.wid, "fixture-session", request)
        assert_schema(self, "lab_run_response", result)
        finding = next(f for f in result["data"]["diagnostics"] if f["dimension"] == "originality")
        self.assertEqual(finding["assessment"], "concern")
        self.assertIsNotNone(finding["suggested_edit"])
        with self.svc.repository.transaction("fixture-session", self.wid) as (cur, row, actor):
            store = TrendStore(self.connect); state = row[1]
            op_row = store.get_opportunity(self.wid, actor, self.oid, cursor=cur)
            op, trend = self.svc._opportunity_read(store, cur, self.wid, actor, op_row, state, time.time())
            receipt = store.get_receipt(self.wid, actor, self.rid, cursor=cur)
            run = store.get_projection(self.wid, actor, "lab_run", result["data"]["id"], cursor=cur)
            draft = state["variants"][0]
            inputs = self.svc._lab_inputs(self.wid, state, op, op_row, receipt, draft, trend, time.time(), cursor=cur)
            proposal = opportunity_lab.select_patches({**inputs, "run": run["payload"]["frozen_run"], "selected_edit_ids": [finding["suggested_edit"]["id"]]})
            text = draft["text"]
            for edit in proposal["patches"]: text = text.replace(edit["before"], edit["after"], 1)
            revision = row[0]
        def edit(state, actor):
            return self.svc.hosted.commands(state, actor, "variant_edit", {"variantId": did, "variantRevision": proposal["expected_revision"], "text": text})
        saved = self.svc.repository.command(self.wid, "fixture-session", revision, edit)
        draft = saved["state"]["variants"][0]
        self.assertNotIn(phrase, draft["text"])
        self.assertEqual(draft["revision"], 2)
        self.assertTrue(draft["needsReview"])
        self.assertEqual(draft["trendLineage"][0]["trust_receipt_id"], self.rid)
        self.assertEqual(self.svc.stored(self.wid, "fixture-session", "lab", result["data"]["id"])["data"]["state"], "stale")
        with self.assertRaises(AlphaError) as stale:
            self.svc.repository.command(self.wid, "fixture-session", saved["revision"], edit)
        self.assertEqual(stale.exception.status, 409)



    def test_z_existing_performance_baseline_and_owner_experiment_preserve_lineage(self):
        from postriff_phase2.growth.trends import relevance
        from postriff_phase2.growth.trends.store import TrendStore
        from postriff_phase2.coworker import performance
        store = TrendStore(self.connect); oid = str(uuid.uuid4()); channel = "threads-test"
        with self.svc.repository.transaction("fixture-session", self.wid) as (cur, row, actor):
            state = copy.deepcopy(row[1]); state["phase2"]["channels"].append({"id": channel, "platform": "Threads", "language": "en", "revoked": False})
            cur.execute("UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), self.wid))
            old = store.get_opportunity(self.wid, actor, self.oid, cursor=cur)
            trend = store.get_projection(self.wid, actor, "trend", self.tid, cursor=cur)
            receipt = store.get_receipt(self.wid, actor, self.rid, cursor=cur)
            now = time.time(); expiry = opportunities.iso(min(opportunities.epoch(trend["expires_at"]), opportunities.epoch(receipt["expires_at"])))
            manifest = store.put_manifest("workspace:"+self.wid, [{"scope_key": r["scope_key"], "node_id": r["projection_id"]} for r in (trend,receipt)],
                decision_cutoff=opportunities.iso(now), available_at=opportunities.iso(now), retention_until=expiry, cursor=cur)
            op = {**old["payload"], "id": oid, "context_digest": relevance.context_revision(state), "platform_targets": ["threads"]}
            store.put_projection({"scope_key": "workspace:"+self.wid, "kind": "opportunity", "object_id": oid, "revision": 1,
                "manifest_id": manifest["manifest_id"], "receipt_id": self.rid, "method_id": old["method_bundle"]["method_id"], "method_version": old["method_bundle"]["version"],
                "decision_cutoff": opportunities.iso(now), "available_at": opportunities.iso(now), "retention_until": expiry, "payload": op}, cursor=cur)
        page = self.svc.list(self.wid, "fixture-session", kind="opportunity")
        shown = next(p for p in page["data"] if p["id"] == oid)
        view = self.svc.exposure(self.wid, "fixture-session", {"event_id":str(uuid.uuid4()),"exposure_token":page["exposure_token"],
            "opportunity_id":oid,"opportunity_revision":shown["revision"],"trust_receipt_id":shown["trust_receipt_id"],"context_digest":shown["context_digest"],
            "eligible_candidates":[{"opportunity_id":p["id"],"revision":p["revision"]} for p in page["data"] if p["state"] in ("candidate","ready") and p["verification_state"]=="verified"]})
        selected = self.svc.accept(self.wid, "fixture-session", oid, {**PAYLOAD, "channel_id": channel, "idempotency_key": "learning-accept", "exposure_id":view["data"]["exposure_id"]})
        with self.svc.repository.transaction("fixture-session", self.wid) as (cur, row, actor):
            state = copy.deepcopy(row[1]); before_learning = copy.deepcopy(state.get("learning")); before_brand = copy.deepcopy(state["brandHub"])
            binding = opportunities.lineage(state, [selected["data"]["source_id"]]); jobs = []
            for n in range(12):
                text = "What changed in your bake?" if n%2 == 0 else "A measured bake can teach us."
                manifest = {"channelId": channel, "platform": "Threads", "variantId": "owned-"+str(n), "payload": {"text": text, "language": "en"},
                            "contentType": {"id": "opinion"}, "timing": {"timestamp": now-86400*(n+1), "timeZone": "UTC"}}
                opportunities.freeze_manifest(state, {"text": text, "revision": 1, "trendLineage": binding}, manifest, now)
                job = {"id": "owned-"+str(n), "state": "verified", "providerReference": "owned-post-"+str(n), "verifiedAt": now-86400*(n+1), "manifest": manifest}
                jobs.append(job)
                cur.execute("""INSERT INTO pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at,read_offset)
                    VALUES(%s,%s,'threads',%s,%s,'views','2026-09',%s,'count','available',to_timestamp(%s),'24h')""", (self.wid,channel,job["providerReference"],job["id"],900+n if n%2==0 else 400+n,now-100))
            state["phase2"]["jobs"] = jobs
            cur.execute("UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), self.wid))
            result = performance.refresh(cur, self.wid, state, now)
            self.assertGreaterEqual(result["created"], 1)
            # Ordinary free-text goals never become a fabricated objective metric.
            observed = scout_outcomes.refresh(cur, self.wid, state, now)
            self.assertEqual(len(observed), 12)
            self.assertTrue(all(r["trendLineage"]["trust_receipt_id"] == self.rid for r in observed))
            self.assertTrue(all(r["objective"] == "unmeasured" for r in observed))
            self.assertTrue(all(r["trendLineage"]["exposure_id"] == view["data"]["exposure_id"] for r in observed))
            self.assertEqual({r["publication"]["textDigest"] for r in observed}, {j["manifest"]["trendPublication"]["textDigest"] for j in jobs})
            cur.execute("SELECT id::text,sample_a,sample_b,causal,status FROM pr_strategy_hypotheses WHERE workspace_id=%s AND dimension='opening'", (self.wid,))
            hypothesis = cur.fetchone()
            self.assertEqual(hypothesis[1:], (6,6,False,"candidate"))
        with patch.object(self.svc.coworker, "_require"):
            with self.connect() as db:
                db.execute("UPDATE pr_memberships SET role='editor' WHERE workspace_id=%s AND user_id=%s", (self.wid,self.actor))
            try:
                with self.assertRaises(AlphaError) as denied:
                    self.svc.coworker.hypothesis_decide(self.wid,"fixture-session",hypothesis[0],"experiment")
                self.assertEqual(denied.exception.status,403)
            finally:
                with self.connect() as db:
                    db.execute("UPDATE pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s", (self.wid,self.actor))
            decision = self.svc.coworker.hypothesis_decide(self.wid,"fixture-session",hypothesis[0],"experiment")
        self.assertTrue(decision["verified"])
        self.assertFalse(decision["causal"])
        state = self.svc.repository.get(self.wid,"fixture-session")["state"]
        self.assertEqual(state.get("learning"), before_learning)
        self.assertEqual(state["brandHub"], before_brand)



class TrendIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.repo, self.store = make_service()

    def test_coworker_optional_effect_protocol_preserves_durable_hook(self):
        from postriff_phase2.coworker.service import CoworkerService
        from postriff_phase2.hosted import PostgresWorkspaceRepository
        for host in (SimpleNamespace(), SimpleNamespace(repository=SimpleNamespace())):
            CoworkerService(host, values={})
        repository = PostgresWorkspaceRepository(lambda: None, lambda token: ACTOR, SimpleNamespace())
        coworker = CoworkerService(SimpleNamespace(repository=repository, connection_factory=lambda: None))
        self.assertIn(coworker._trend_edit_effect, repository.effects)
        from postriff_phase2.growth.trends.media_jobs import capture_asset_changes
        self.assertIn(capture_asset_changes, repository.effects)
        self.assertEqual(len(repository.effects), 2)

    def test_existing_scout_yields_to_durable_worker_without_egress(self):
        with patch.object(scout_runtime.research, "TOTAL_BUDGET_SECONDS", 0), patch.object(scout_runtime, "reserve", side_effect=AssertionError("legacy work")):
            result = scout_runtime.run_workspace(self.svc.coworker, WID, 0)
        self.assertEqual(result["status"], "stored_trend_mode")

    def test_current_lineage_rechecks_policy_in_mutation_cursor(self):
        sid = self.svc.accept(WID, "session", OID, PAYLOAD)["data"]["source_id"]
        bindings = opportunities.lineage(self.repo.state, [sid])
        validate_stored_bindings(self.repo.connection_factory, self.repo, WID, ACTOR, self.repo.state, bindings, NOW, store_factory=lambda _: self.store)
        self.assertTrue(all(c[-1] is self.repo for c in self.store.calls if c[0] == "get"))
        self.store.rows["receipt", RID].update(validity="revoked", payload=None)
        with self.assertRaises(AlphaError) as raised:
            validate_stored_bindings(self.repo.connection_factory, self.repo, WID, ACTOR, self.repo.state, bindings, NOW, store_factory=lambda _: self.store)
        self.assertEqual(raised.exception.status, 410)

    def test_existing_variant_edit_effect_rechecks_receipt_before_commit(self):
        sid = self.svc.accept(WID, "session", OID, PAYLOAD)["data"]["source_id"]
        bindings = opportunities.lineage(self.repo.state, [sid])
        before = copy.deepcopy(self.repo.state)
        before["variants"] = [{"id": "draft-1", "text": "Before", "revision": 1, "trendLineage": bindings}]
        after = copy.deepcopy(before)
        after["variants"][0].update(text="After", revision=2)
        self.store.rows["receipt", RID].update(validity="revoked", payload=None)
        with patch("postriff_phase2.growth.trends.store.TrendStore", return_value=self.store):
            with self.assertRaises(AlphaError):
                validate_changed_variants(self.repo.connection_factory, self.repo, WID, before, after, ACTOR, NOW)

    def test_lab_rejects_arbitrary_or_changed_draft_link(self):
        payload = {"draft_id": "invented", "draft_revision": 1, "opportunity_id": OID, "opportunity_revision": 1, "target_platform": "bluesky", "idempotency_key": "lab-1"}
        with self.assertRaises(AlphaError) as raised:
            self.svc.lab_create(WID, "session", payload)
        self.assertEqual(raised.exception.status, 404)
        self.repo.state["variants"] = [{"id": "invented", "text": "Changed", "revision": 1, "platform": "Bluesky", "trendLineage": [{"opportunity_id": OID}]}]
        with self.assertRaises(AlphaError) as raised:
            self.svc.lab_create(WID, "session", {**payload, "draft_revision": 2})
        self.assertEqual(raised.exception.status, 409)

    def test_outcomes_use_approved_manifest_not_mutated_live_source(self):
        plan = {"id": "frozen-plan", "primaryObjective": "shareability", "platform": "Bluesky", "account": "channel-1", "opportunityId": OID}
        job = {"id": "job-1", "state": "verified", "verifiedAt": NOW, "manifest": {"variantId": "draft-1", "channelId": "channel-1", "scoutLineage": [{"executionPlan": plan}]}}
        self.repo.state["phase2"]["jobs"] = [job]
        self.repo.state["variants"] = [{"id": "draft-1", "sourceIds": [], "scoutLineage": [{"executionPlan": {**plan, "id": "mutated-plan", "primaryObjective": "reach"}}]}]
        post = {"jobId": "job-1", "platform": "Bluesky", "provider": "bluesky", "connectionId": "channel-1", "language": "en", "definitionVersion": "v1", "metrics": {}}
        with patch("postriff_phase2.insights.summary", return_value={"posts": [post]}):
            rows = scout_outcomes.refresh(None, WID, self.repo.state, NOW)
        self.assertEqual({r["executionPlanId"] for r in rows}, {"frozen-plan"})
        self.assertEqual({r["objective"] for r in rows}, {"shareability"})


    def test_lab_executes_durable_local_evaluation_and_replays_exact_run(self):
        # This test owns the deterministic path. Semantic admission has separate
        # savepoint and real-SQL tests, and must never run through a fake cursor.
        self.svc.values["RAFII_TREND_MODEL_ENRICHMENT_ENABLED"] = "false"
        sid = self.svc.accept(WID, "session", OID, PAYLOAD)["data"]["source_id"]
        self.repo.state["variants"] = [{"id": "draft-1", "text": "An original creator-supplied example", "revision": 1, "platform": "Bluesky", "trendLineage": opportunities.lineage(self.repo.state, [sid])}]
        payload = {"draft_id": "draft-1", "draft_revision": 1, "opportunity_id": OID, "opportunity_revision": 1, "target_platform": "Bluesky", "idempotency_key": "lab-real-local"}
        result = self.svc.lab_create(WID, "session", payload)
        assert_schema(self, "lab_run_response", result)
        self.assertEqual(result["data"]["state"], "completed")
        self.assertEqual(len(result["data"]["diagnostics"]), 9)
        self.assertTrue(all(d["assessment"] == "unknown" for d in result["data"]["diagnostics"]))
        again = self.svc.lab_create(WID, "session", payload)
        self.assertEqual(result["data"]["id"], again["data"]["id"])
        self.assertEqual(sum(c[0] == "enqueue" for c in self.store.calls), 1)
        self.assertEqual(sum(c[0] == "finish_local" for c in self.store.calls), 1)
        self.repo.state["variants"][0].update(text="Changed draft", revision=2)
        stale = self.svc.stored(WID, "session", "lab", result["data"]["id"])
        self.assertEqual(stale["data"]["state"], "stale")
        self.assertEqual(stale["data"]["diagnostics"], [])

    def test_semantic_lab_queue_uses_savepoint_and_never_executes_model(self):
        from contextlib import contextmanager
        from unittest.mock import Mock
        from postriff_phase2.growth.trends.contracts import ContractError
        boundaries = []
        @contextmanager
        def savepoint():
            boundaries.append('begin')
            try:
                yield
            except ContractError:
                boundaries.append('rollback')
                raise
            else:
                boundaries.append('commit')
        cur = SimpleNamespace(connection=SimpleNamespace(transaction=savepoint))
        evaluator = Mock()
        evaluator.enqueue_stored.return_value = {'status': 'queued'}
        with patch('postriff_phase2.growth.trends.lab_enrichment.TrendLabEnrichment', return_value=evaluator):
            result = self.svc._queue_lab_semantic(self.store,cur,WID,ACTOR,self.repo.state,'run','request')
            self.assertIn('queued',result)
            evaluator.enqueue_stored.assert_called_once_with(cur,WID,ACTOR,'run',self.repo.state,idempotency_key='semantic:request')
            evaluator.tick.assert_not_called()
            self.assertEqual(boundaries,['begin','commit'])
            evaluator.enqueue_stored.side_effect = ContractError('current_rights_denied')
            result = self.svc._queue_lab_semantic(self.store,cur,WID,ACTOR,self.repo.state,'run','request')
            self.assertIn('unavailable',result)
            self.assertEqual(boundaries[-2:],['begin','rollback'])
            evaluator.tick.assert_not_called()
            self.svc.values['RAFII_TREND_MODEL_ENRICHMENT_ENABLED']='false'
            evaluator.enqueue_stored.reset_mock()
            self.assertIn('disabled',self.svc._queue_lab_semantic(self.store,cur,WID,ACTOR,self.repo.state,'run','request'))
            evaluator.enqueue_stored.assert_not_called()

    def test_trend_tool_registration_and_accept_ledger_are_truthful(self):
        from postriff_phase2.growth.trends import tools as trend_tools
        from postriff_phase2.agent_runtime_v2 import tool_adapter
        from postriff_phase2.agent_runtime_v2.context import EffectLedger
        from postriff_phase2.coworker import runtime
        trend_tools.register()
        names = {"trend_search", "trend_detail", "trend_receipt", "trend_opportunities", "trend_opportunity_accept"}
        self.assertTrue(names <= tool_adapter.REGISTRY.keys())
        context = SimpleNamespace(service=SimpleNamespace(coworker=self.svc.coworker, notifications=SimpleNamespace()), workspace_id=WID, token="session", ledger=EffectLedger())
        with patch.object(runtime, "ensure", side_effect=lambda service: service):
            first = tool_adapter.REGISTRY["trend_opportunity_accept"].executor(context, {"opportunity_id": OID, **PAYLOAD})
            again = tool_adapter.REGISTRY["trend_opportunity_accept"].executor(context, {"opportunity_id": OID, **PAYLOAD})
        self.assertTrue(first["ok"] and again["ok"])
        self.assertEqual(len(context.ledger.changed), 1)
        self.assertEqual(context.ledger.changed[0]["type"], "source")
        self.assertEqual(context.ledger.references[0]["id"], self.repo.state["sources"][0]["id"])
