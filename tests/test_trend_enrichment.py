"""Local-only G07 checks. JEV transport is injected; live dispatch is prohibited."""
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from postriff_phase2.growth.trends import contracts, enrichment
from postriff_phase2.growth.jev import JevService, DEFAULT_MODEL, EVALUATE_ENDPOINT


def model_policy(prefix="fixture"):
    return {"schema_version":"1","approved":True,"endpoint":EVALUATE_ENDPOINT,"model":DEFAULT_MODEL,
            "tasks":["workspace_fit","originality","execution_risk"],"price_ref":"synthetic-test-price","approved_attempt_cap_microusd":1000,
            "max_attempts":1,"timeout_seconds":3,"max_evidence":12,"max_chars_per_evidence":800,"max_pack_tokens":8000,
            "cache_ttl_seconds":300,"budget_keys":[prefix+":system",prefix+":provider",prefix+":workspace:{workspace_id}"]}


class EnrichmentUnitTests(unittest.TestCase):
    def test_disabled_tick_and_enqueue_construct_no_database_or_model(self):
        bad=lambda: self.fail("database opened while disabled")
        worker=enrichment.TrendEnrichment(SimpleNamespace(repository=SimpleNamespace(connection_factory=bad)),values={},jev_factory=lambda _: self.fail("model constructed"))
        self.assertEqual(worker.tick()["provider_attempts"],0)
        self.assertEqual(worker.plan_current()["provider_attempts"],0)
        self.assertEqual(worker.enqueue(str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4()),"workspace_fit",idempotency_key="x")["status"],"disabled")

    def test_reviewed_policy_pins_route_caps_price_and_scope_budget(self):
        wid=str(uuid.uuid4());policy={"manifest":{"reviewed_by":"fixture","review_ref":"fixture-review","model_enrichment":model_policy()}}
        cfg=enrichment.reviewed_config(policy,"workspace_fit",wid)
        self.assertIn(wid,cfg["budget_keys"][2])
        for key,value in (("endpoint","https://unreviewed.invalid/evaluate"),("model","other/model"),("max_attempts",2),
                          ("approved",False),("approved_attempt_cap_microusd",0),("price_ref",""),("max_pack_tokens",9000)):
            altered=copy.deepcopy(policy);altered["manifest"]["model_enrichment"][key]=value
            with self.assertRaises(contracts.ContractError): enrichment.reviewed_config(altered,"workspace_fit",wid)


@unittest.skipUnless(os.environ.get("TREND_ENRICHMENT_TEST_DSN"),"explicit disposable enrichment DSN required")
class EnrichmentPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from local_pg_target import selected_target
        target = selected_target(validate_fixture_dsns=False)
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        cls.psycopg=psycopg; cls.dsn=os.environ["TREND_ENRICHMENT_TEST_DSN"]
        params=conninfo_to_dict(cls.dsn)
        allowed = params.get("host") == "127.0.0.1" and ((params.get("port") == "56451" and params.get("dbname", "").startswith("trend_enrichment_"))
            or (params.get("port"), params.get("dbname")) == (str(target.port), "postgres"))
        if (not allowed or set(params)-{"host","port","dbname","user"}
                or any(k in os.environ for k in ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR", "PGOPTIONS"))):
            raise ValueError("only explicit disposable enrichment or exact local CI database allowed")
        root=Path(__file__).parents[1]; role="trend_enrichment_"+uuid.uuid4().hex[:10]
        with psycopg.connect(cls.dsn) as db:
            if not db.execute("SELECT to_regclass('pr_trend_jobs')").fetchone()[0]:
                db.execute((root/"migrations/postriff/040_social_trend_intelligence.sql").read_text())
            db.execute("CREATE ROLE "+role+" NOSUPERUSER NOBYPASSRLS INHERIT")
            db.execute("GRANT service_role TO "+role)
            for table in ("pr_workspaces","pr_memberships","pr_profiles"):
                db.execute("CREATE POLICY "+role+" ON "+table+" FOR ALL TO "+role+" USING(true) WITH CHECK(true)")
        def connect():
            db=psycopg.connect(cls.dsn);db.execute("SET ROLE "+role);return db
        cls.connect=staticmethod(connect)

    def setUp(self):
        from postriff_phase2.auth import initial_phase2_state
        from postriff_phase2.hosted import PostgresWorkspaceRepository, HostedPhase2Commands
        from postriff_phase2.growth.trends.store import TrendStore, utcnow
        from postriff_phase2.growth.trends.jobs import TrendJobs
        from postriff_phase2.growth.trends.pipeline import TrendPipeline
        self.wid=str(uuid.uuid4());self.actor=str(uuid.uuid4());self.scope="shared:enrichment-"+uuid.uuid4().hex[:10]
        self.provider="fixture-source-"+uuid.uuid4().hex[:10];self.prefix=uuid.uuid4().hex
        self.at=datetime.now(timezone.utc);self.start=contracts.iso(self.at-timedelta(hours=1));self.end=contracts.iso(self.at+timedelta(hours=1))
        self.state=initial_phase2_state(self.wid,self.actor,"Enrichment fixture","studio",self.at.timestamp())
        self.state["brandHub"].update(subject="香港麵包實驗",audience="香港烘焙新手")
        with self.psycopg.connect(self.dsn) as db:
            db.execute("INSERT INTO auth.users(id) VALUES(%s)",(self.actor,))
            db.execute("INSERT INTO pr_profiles(user_id) VALUES(%s)",(self.actor,))
            db.execute("INSERT INTO pr_workspaces(id,state) VALUES(%s,%s::jsonb)",(self.wid,json.dumps(self.state)))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')",(self.wid,self.actor))
        self.store=TrendStore(self.connect);self.store.ensure_scope(self.scope)
        self.store.grant_entitlement(self.wid,self.scope,["retrieve","derive_metrics","share_across_workspaces"],self.end)
        rights={p:{"state":"allow","policy_ref":"reviewed-fixture","audience_scope":self.scope,"expires_at":self.end} for p in contracts.PERMISSIONS}
        self.policy={"id":"fixture-policy","version":"1","provider_id":self.provider,"operation":"read","scope_key":self.scope,
                     "rights":rights,"reviewed_by":"synthetic-reviewer","review_ref":"synthetic-local-only","effective_at":self.start,
                     "expires_at":self.end,"retention_seconds":7200,"readiness":"ready","revoked_at":None,"model_enrichment":model_policy(self.prefix)}
        self.store.register_contract(self.provider,"1",list(contracts.PERMISSIONS),self.start,self.end)
        self.store.register_policy(self.policy,provider_contract_version="1")
        observations=[]
        for n in range(4):
            payload={"platform":"bluesky","native_id":"synthetic-"+str(n),"author_key":"original-author-"+str(n),"author_status":"known",
                     "text":"香港麵包焗爐溫度實驗，今次記錄發酵時間同麵糰水份。"+str(n),"language":"yue","canonical_url":"https://example.test/native/"+str(n)}
            obs={"schema_version":contracts.SCHEMA_VERSION,"observation_id":str(uuid.uuid4()),"scope_key":self.scope,"provider_id":self.provider,
                 "provider_contract_version":"1","source_policy_version":"1","source_identity":"fixture-post-"+str(n),"revision_identity":"r1","revision_sequence":1,
                 "kind":"raw_post","operation":"create","event_at":contracts.iso(self.at.replace(minute=0,second=0,microsecond=0)-timedelta(minutes=10+n)),"received_at":utcnow(),"available_at":utcnow(),
                 "time_basis":"provider_event","coverage_epoch":"fixture-epoch","provenance":{"access_method":"synthetic"},"retention_until":self.end,
                 "rights":rights,"deletion_key":"fixture-post-"+str(n),"payload":payload,"payload_digest":contracts.digest(payload)}
            self.store.put_observation(obs);observations.append(obs)
        with self.store.transaction() as cur:
            cutoff=utcnow()
            event={"event_id":str(uuid.uuid4()),"event_type":"trend.ingested","scope_key":self.scope,"payload":{"provider_id":self.provider,
                "observation_ids":[o["observation_id"] for o in observations],"decision_cutoff":cutoff,"coverage_epoch":"fixture-epoch","completeness":"partial",
                "coverage_interval":{"start":contracts.iso(self.at-timedelta(hours=1)),"end":cutoff}}}
            result=TrendPipeline(self.store).consume(cur,event)
        self.assertTrue(result.get("receipts"),result)
        self.rid=result["receipts"][0]["receipt_id"]
        self.assertEqual(self.store.get_receipt(self.wid,self.actor,self.rid)["verification_state"],"verified")
        for dimension,key in zip(("system","provider","workspace"),enrichment.reviewed_config({"manifest":self.policy},"workspace_fit",self.wid)["budget_keys"]):
            TrendJobs(self.store).configure_budget(key,dimension,100000,self.start,self.end)
        self.hosted=SimpleNamespace(repository=PostgresWorkspaceRepository(self.connect,lambda token:self.actor,HostedPhase2Commands()),
                                    billing=SimpleNamespace(pricing_v2_enabled=False),
                                    clock=lambda:datetime.now(timezone.utc).timestamp())
        self.store.hosted=self.hosted
        self.values={"RAFII_TREND_"+n+"_ENABLED":"1" for n in enrichment.REQUIRED_FLAGS};self.values["RAFII_TREND_WORKSPACE_ALLOWLIST"]=self.wid
        self.calls=[];self.side_effect=None;self.cost="0.0001"
        def transport(method,url,*,headers,body,timeout):
            self.calls.append(copy.deepcopy(body));self.assertEqual(url,EVALUATE_ENDPOINT);self.assertLessEqual(timeout,3)
            if self.side_effect:self.side_effect()
            answers={}
            for key,value in body["questions"].items():
                choice="supported" if "supported" in value["criteria"] else next(iter(value["criteria"]))
                answers[key]={"type":"choice","choice":choice,"probabilities":{option:1.0 if option==choice else 0.0 for option in value["criteria"]}}
            gateway={"generationId":"synthetic-generation","routing":{"finalProvider":"synthetic"}}
            if self.cost is not None: gateway["cost"]=self.cost
            return {"status":200,"body":{"model":DEFAULT_MODEL,"answers":answers,"usage":{"inputTokens":100,"outputTokens":20},"providerMetadata":{"gateway":gateway}}}
        # Keep dispatch-budget timing deterministic while PostgreSQL validity and
        # acquisition cutoffs use the real database clock. A separate case tests expiry.
        self.worker=enrichment.TrendEnrichment(self.hosted,store=self.store,values=self.values,monotonic=lambda:0,
            jev_factory=lambda cfg:JevService("synthetic-local-key",endpoint=cfg["endpoint"],model=cfg["model"],transport=transport))

    def enqueue(self,key="run-1"):
        return self.worker.enqueue(self.wid,self.actor,self.rid,"workspace_fit",idempotency_key=key)

    def usage(self):
        with self.connect() as db:
            return db.execute("SELECT status,cost_usd_micro FROM pr_model_usage_events WHERE workspace_id=%s ORDER BY created_at",(self.wid,)).fetchall()

    def test_native_bounded_private_projection_and_persistent_cache(self):
        with patch.dict(os.environ,{"POSTRIFF_JEV_MODEL":"forbidden/model","AI_GATEWAY_EVALUATE_ENDPOINT":"https://forbidden.invalid"}):
            queued=self.enqueue();result=self.worker.tick()
        self.assertEqual(result["attached"],1,result);self.assertEqual(len(self.calls),1)
        pack=self.calls[0]["state"]
        self.assertEqual(pack["scope_key"],"workspace:"+self.wid);self.assertEqual(pack["evidence_scope"],self.scope)
        self.assertTrue(all(e["source_scope_key"]==self.scope and "麵包" in e["text"] and len(e["text"])<=800 for e in pack["evidence"]))
        self.assertLessEqual(len(pack["evidence"]),12);self.assertLessEqual(enrichment.estimate_tokens(pack),8000)
        self.assertEqual(self.usage(),[("ok",100)])
        row=self.store.get_projection(self.wid,self.actor,"model_judgment",queued["result_id"])
        self.assertEqual(row["scope_key"],"workspace:"+self.wid)
        judged=row["payload"]["result"];self.assertEqual(judged["calibration_state"],"unqualified")
        self.assertIsNone(judged["domain_calibration_ref"]);self.assertTrue(judged["interpretation_only"])
        self.assertFalse({"angles","stage","calculated"}&judged.keys())
        self.assertEqual(self.enqueue("new-idempotency")["status"],"cached")
        self.assertEqual(len(self.calls),1)
        with self.connect() as db:
            job=db.execute("SELECT provider_id,payload,state FROM pr_trend_jobs WHERE job_id=%s",(queued["job_id"],)).fetchone()
            nodes=db.execute("SELECT DISTINCT input_scope_key FROM pr_trend_manifest_inputs m JOIN pr_trend_projections p USING(scope_key,manifest_id) WHERE p.object_id=%s",(queued["result_id"],)).fetchall()
        self.assertEqual(job,(None,{},"succeeded"));self.assertEqual(nodes,[(self.scope,)])

    def test_revocation_during_call_accounts_before_discard_without_output(self):
        from postriff_phase2.growth.trends.revocation import revoke_policy
        queued=self.enqueue();self.side_effect=lambda:revoke_policy(self.store,self.scope,self.provider,"1")
        result=self.worker.tick();self.assertEqual(result["discarded"],1,result)
        self.assertEqual(self.usage(),[("ok",100)])
        self.assertIsNone(self.store.get_projection(self.wid,self.actor,"model_judgment",queued["result_id"]))
        with self.connect() as db:
            settled=db.execute("SELECT r.state,r.actual_micro_usd,r.usage_event_id IS NOT NULL,j.state FROM pr_trend_budget_reservations r JOIN pr_trend_jobs j USING(scope_key,reservation_id) WHERE j.job_id=%s",(queued["job_id"],)).fetchone()
        self.assertEqual(settled,("settled",100,True,"outcome_unknown"))

    def test_unknown_cost_retains_exposure_and_never_caches(self):
        queued=self.enqueue();self.cost=None;result=self.worker.tick()
        self.assertEqual(result["discarded"],1);self.assertEqual(self.usage(),[("ok",None)])
        with self.connect() as db:
            reservation=db.execute("SELECT r.state,r.actual_micro_usd,r.amount_micro_usd FROM pr_trend_budget_reservations r JOIN pr_trend_jobs j USING(scope_key,reservation_id) WHERE j.job_id=%s",(queued["job_id"],)).fetchone()
        self.assertEqual(reservation,("unknown",None,1000))
        self.assertIsNone(self.store.get_projection(self.wid,self.actor,"model_judgment",queued["result_id"]))
        self.worker.tick();self.assertEqual(len(self.calls),1)

    def test_queued_context_change_and_cross_tenant_actor_never_dispatch(self):
        self.enqueue()
        with self.connect() as db:
            db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{brandHub,audience}','\"Changed audience\"'::jsonb) WHERE id=%s",(self.wid,))
        self.assertEqual(self.worker.tick()["blocked"],1);self.assertEqual(self.calls,[])
        with self.assertRaises(Exception):
            self.worker.enqueue(self.wid,str(uuid.uuid4()),self.rid,"workspace_fit",idempotency_key="foreign")
        self.values["RAFII_TREND_MODEL_ENRICHMENT_ENABLED"]="0"
        self.assertEqual(self.worker.tick()["provider_attempts"],0)

    def test_context_changed_during_call_keeps_usage_but_no_stale_projection(self):
        queued=self.enqueue()
        def change():
            with self.connect() as db:
                db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{brandHub,subject}','\"Changed subject\"'::jsonb) WHERE id=%s",(self.wid,))
        self.side_effect=change
        self.assertEqual(self.worker.tick()["discarded"],1);self.assertEqual(self.usage(),[("ok",100)])
        self.assertIsNone(self.store.get_projection(self.wid,self.actor,"model_judgment",queued["result_id"]))


    def test_planner_queues_only_two_reviewed_tasks_and_replays_without_filling_queue(self):
        first=self.worker.plan_current();self.assertEqual(first["queued"],2,first);self.assertEqual(self.calls,[])
        again=self.worker.plan_current();self.assertEqual(again["queued"],0,again);self.assertEqual(again["existing"],2)
        with self.connect() as db:
            jobs=db.execute("SELECT payload,provider_id,reservation_id FROM pr_trend_jobs WHERE scope_key=%s AND kind=%s",
                            ("workspace:"+self.wid,enrichment.KIND)).fetchall()
        self.assertEqual(len(jobs),2)
        for payload,provider,reservation in jobs:
            self.assertEqual(set(payload),{"workspace_id","actor_id","receipt_id","task","cache_key","result_id","context_revision","policy_digest"})
            self.assertIsNone(provider);self.assertIsNone(reservation)
        result=self.worker.tick();self.assertEqual(result["attached"],1,result);self.assertEqual(len(self.calls),1)
        self.assertLessEqual(self.worker.plan_current()["queued"],1)

    def test_budget_denial_never_dispatches_or_writes_usage(self):
        queued=self.enqueue()
        with self.connect() as db:
            db.execute("UPDATE pr_trend_budget_limits SET cap_micro_usd=0 WHERE budget_key=%s",(self.prefix+":system",))
        result=self.worker.tick();self.assertEqual(result["provider_attempts"],0,result);self.assertEqual(self.calls,[]);self.assertEqual(self.usage(),[])
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT state,reservation_id FROM pr_trend_jobs WHERE job_id=%s",(queued["job_id"],)).fetchone(),("queued",None))

    def test_revocation_before_dispatch_retires_queue_with_no_cost(self):
        from postriff_phase2.growth.trends.revocation import revoke_policy
        queued=self.enqueue();revoke_policy(self.store,self.scope,self.provider,"1")
        result=self.worker.tick();self.assertEqual(result["provider_attempts"],0);self.assertEqual(self.calls,[]);self.assertEqual(self.usage(),[])
        with self.connect() as db:
            saved=db.execute("SELECT state,payload FROM pr_trend_jobs WHERE job_id=%s",(queued["job_id"],)).fetchone()
        self.assertEqual(saved,("cancelled",{}))

    def test_cache_context_change_creates_distinct_identity_and_tenant_cannot_read(self):
        old=self.enqueue();self.assertEqual(self.worker.tick()["attached"],1)
        with self.connect() as db:
            db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{brandHub,audience}','\"A new private audience\"'::jsonb) WHERE id=%s",(self.wid,))
        new=self.enqueue("fresh-context");self.assertNotEqual(new["result_id"],old["result_id"]);self.assertEqual(new["status"],"queued")
        with self.assertRaises(contracts.ContractError):self.store.get_projection(str(uuid.uuid4()),self.actor,"model_judgment",old["result_id"])
        self.assertEqual(len(self.calls),1)


    def test_unfunded_planner_and_independent_flags_create_no_jobs(self):
        with self.connect() as db:
            db.execute("UPDATE pr_trend_budget_limits SET cap_micro_usd=0 WHERE budget_key=%s",(self.prefix+":system",))
        result=self.worker.plan_current();self.assertEqual(result["queued"],0);self.assertGreater(result["unavailable"],0)
        for flag in enrichment.REQUIRED_FLAGS:
            name="RAFII_TREND_"+flag+"_ENABLED"
            with patch.dict(self.values,{name:"0"}):
                self.assertEqual(self.worker.plan_current()["status"],"disabled")
                self.assertEqual(self.worker.tick()["provider_attempts"],0)
        with patch.dict(self.values,{"RAFII_TREND_WORKSPACE_ALLOWLIST":""}):
            self.assertEqual(self.worker.plan_current()["queued"],0)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_trend_jobs WHERE scope_key=%s AND kind=%s",("workspace:"+self.wid,enrichment.KIND)).fetchone()[0],0)
        self.assertEqual(self.calls,[])


    def test_dispatch_deadline_releases_reservation_without_attempt(self):
        queued=self.enqueue();ticks=iter([0,0,4]);self.worker.monotonic=lambda:next(ticks)
        result=self.worker.tick(max_seconds=6)
        self.assertEqual(result["provider_attempts"],0);self.assertEqual(result["blocked"],1)
        self.assertEqual(self.calls,[]);self.assertEqual(self.usage(),[])
        with self.connect() as db:
            result=db.execute("SELECT j.state,r.state,r.actual_micro_usd FROM pr_trend_jobs j JOIN pr_trend_budget_reservations r USING(scope_key,reservation_id) WHERE j.job_id=%s",(queued["job_id"],)).fetchone()
        self.assertEqual(result,("failed_terminal","released",None))


    def test_cached_old_policy_revocation_hides_result_but_preserves_settled_usage(self):
        from postriff_phase2.growth.trends.revocation import revoke_policy
        from postriff_phase2.growth.trends.store import utcnow
        queued=self.enqueue();self.assertEqual(self.worker.tick()["attached"],1)
        self.assertEqual(self.enqueue("cache-hit")["status"],"cached")
        self.assertEqual(self.usage(),[("ok",100)]);self.assertEqual(len(self.calls),1)
        cutoff=utcnow()
        cached=self.store.get_projection(self.wid,self.actor,"model_judgment",queued["result_id"])
        self.assertEqual(cached["validity"],"valid");self.assertIsNotNone(cached["payload"])
        revoke_policy(self.store,self.scope,self.provider,"1")
        for as_of in (None,cutoff):
            denied=self.store.get_projection(self.wid,self.actor,"model_judgment",queued["result_id"],as_of=as_of)
            self.assertIsNotNone(denied);self.assertNotEqual(denied["validity"],"valid");self.assertIsNone(denied["payload"])
        with self.assertRaises(contracts.ContractError):self.enqueue("after-revocation")
        self.assertEqual(self.worker.tick()["provider_attempts"],0)
        self.assertEqual(self.usage(),[("ok",100)]);self.assertEqual(len(self.calls),1)
        with self.connect() as db:
            settled=db.execute("SELECT r.state,r.actual_micro_usd,r.usage_event_id IS NOT NULL,j.state FROM pr_trend_budget_reservations r JOIN pr_trend_jobs j USING(scope_key,reservation_id) WHERE j.job_id=%s",(queued["job_id"],)).fetchone()
        self.assertEqual(settled,("settled",100,True,"succeeded"))
