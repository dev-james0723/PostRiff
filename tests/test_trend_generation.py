"""Existing writer + real trend job executor with injected local transport only."""
import copy
from datetime import datetime,timezone
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
from postriff_phase2.growth.trends import contracts,generation,opportunities,relevance
from postriff_phase2.growth.usage import MemoryUsageSink
from postriff_phase2.model_runtime import ServerModelRuntime,DEFAULT_ENDPOINT
import test_trend_enrichment as enrichment_tests
from test_trend_worker import ProbeStore

MODEL="openai/gpt-4.1-mini"

def review(prefix="gen"):
    return {"schema_version":"1","approved":True,"endpoint":DEFAULT_ENDPOINT,"model":MODEL,"tasks":list(generation.TASKS),
        "price_ref":"synthetic-price","approved_attempt_cap_microusd":50000,"max_attempts":1,"timeout_seconds":3,
        "max_evidence":12,"max_chars_per_evidence":800,"max_pack_tokens":8000,"cache_ttl_seconds":300,
        "budget_keys":[prefix+":system",prefix+":provider",prefix+":workspace:{workspace_id}"],"max_output_tokens":1200}

def output(task,pack):
    e=pack["evidence"][0];span={"observation_id":e["observation_id"],"start":0,"end":4,"text":e["text"][:4]}
    common={"language":"yue","uncertainties":["片段不足以確認文化含意；請人手核對。"],"evidence_spans":[span]}
    if task=="semantic_label_generate":item={**common,"concept":"焗爐實驗","claim":"作者分享麵包實驗記錄。","stance":"describes"}
    elif task=="culture_explain":item={**common,"explanation":"片段使用粵語描述烘焙記錄；語氣仍需作者核對。","alternatives":["亦可能只是個人筆記。"]}
    else:item={**common,"title":"比較自己的兩次麵糰記錄","contribution":"用已確認的作者記錄設計一個實驗筆記，先提出待驗證問題。", "format_reason":"分開列出方法與尚未確認的觀察。",
        "factual_requirements":["實驗結果需要作者確認。"],"premise_fact_ids":[pack["workspace_context"]["approved_facts"][0]["id"]],
        "fit":{"assessment":"unknown","reason":"只根據提供的品牌方向；效果未知。"},"risk":{"assessment":"unknown","reason":"不預測讀者反應。"}}
    return {"items":[item]}


def pack():
    return {"evidence":[{"observation_id":str(uuid.uuid4()),"text":"香港麵包焗爐溫度實驗，今次記錄發酵時間同麵糰水份。"}],
            "workspace_context":{"approved_facts":[{"id":"fact1","text":"I keep a baking notebook."}],"workspace_context_digest":"context"},
            "input_digest":"input","input_manifest_digest":"manifest","receipt_id":str(uuid.uuid4())}


class GenerationUnitTests(unittest.TestCase):
    def test_strict_grounding_abstention_and_no_metric_authority(self):
        p=pack()
        for task in generation.TASKS:
            good=output(task,p);self.assertEqual(len(generation.validate_output(good,task,p)),1)
            self.assertEqual(generation.validate_output({"items":[]},task,p),[])
            for mutation in (lambda v:v.update(stage="rising"),lambda v:v["items"][0].update(confidence=.9),
                             lambda v:v["items"][0]["evidence_spans"][0].update(text="翻譯"),lambda v:v.update(items=v["items"]*4)):
                bad=copy.deepcopy(good);mutation(bad)
                with self.assertRaises(contracts.ContractError):generation.validate_output(bad,task,p)
        bad=output("angle_generate",p);bad["items"][0]["premise_fact_ids"]=["invented"]
        with self.assertRaises(contracts.ContractError):generation.validate_output(bad,"angle_generate",p)
        bad=output("angle_generate",p);bad["items"][0]["contribution"]=p["evidence"][0]["text"]
        with self.assertRaises(contracts.ContractError):generation.validate_output(bad,"angle_generate",p)

    def test_malformed_paid_answer_records_usage_once_without_retry(self):
        calls=[]
        def transport(method,url,*,headers,body,timeout):
            calls.append(body)
            return {"status":200,"body":{"model":MODEL,"usage":{"cost":.001},"choices":[]}}
        runtime=ServerModelRuntime("synthetic",model=MODEL,transport=transport)
        worker=generation.TrendGeneration(SimpleNamespace(repository=SimpleNamespace(connection_factory=lambda:None)),store=ProbeStore([]))
        p=pack();loaded={"config":review(),"pack":p,"task":"culture_explain","context_revision":"context"};sink=MemoryUsageSink()
        with self.assertRaises(Exception):worker.execute(runtime,loaded,"culture_explain",str(uuid.uuid4()),sink)
        self.assertEqual(len(calls),1);self.assertEqual(len(sink.events),1);self.assertEqual(sink.events[0].cost_usd,.001)

    def test_cloud_brand_and_hard_boundaries_fail_closed(self):
        with self.assertRaises(contracts.ContractError):generation.workspace_context({},review())
        state={"memoryEgress":{"cloud":True},"profile":{"fields":[{"id":"privacy","value":"private constraint","privacy":"private"}]}}
        with self.assertRaises(contracts.ContractError):generation.workspace_context(state,review())

    def test_price_and_token_preflight_refuses_before_transport(self):
        runtime=ServerModelRuntime("synthetic",model=MODEL,transport=lambda *a,**k:self.fail("transport"))
        worker=generation.TrendGeneration(SimpleNamespace(repository=SimpleNamespace(connection_factory=lambda:None)),store=ProbeStore([]))
        loaded={"config":{**review(),"approved_attempt_cap_microusd":1},"pack":pack(),"task":"culture_explain"}
        with self.assertRaises(contracts.ContractError):worker.prepare_model(runtime,loaded)
        loaded["config"]=review();loaded["pack"]["workspace_context"]["memory"]="long "*30000
        with self.assertRaises(contracts.ContractError):worker.prepare_model(runtime,loaded)

    def test_disabled_does_not_resolve_runtime_or_database(self):
        worker=generation.TrendGeneration(SimpleNamespace(repository=SimpleNamespace(connection_factory=lambda:self.fail("DB"))))
        self.assertEqual(worker.plan_current()["status"],"disabled");self.assertEqual(worker.tick()["provider_attempts"],0)


@unittest.skipUnless(os.environ.get("TREND_GENERATION_TEST_DSN"),"explicit disposable generation DSN required")
class GenerationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ,{"TREND_ENRICHMENT_TEST_DSN":os.environ["TREND_GENERATION_TEST_DSN"]}):
            enrichment_tests.EnrichmentPostgresTests.setUpClass.__func__(cls)

    def setUp(self):
        from postriff_phase2.growth.trends.store import TrendStore
        from postriff_phase2.growth.trends.jobs import TrendJobs
        from postriff_phase2.ideas import IdeasService
        from postriff_phase2.coworker.service import CoworkerService
        from postriff_phase2.growth.trends.service import TrendService
        original=TrendStore.register_policy
        def policy(store,value,**kwargs):
            value=copy.deepcopy(value);value["model_generation"]=review(self.prefix)
            return original(store,value,**kwargs)
        with patch.object(TrendStore,"register_policy",policy):
            enrichment_tests.EnrichmentPostgresTests.setUp(self)
        self.state["memoryEgress"]={"cloud":True}
        self.state["phase2"]["channels"]=[{"id":"bake","platform":"Bluesky","language":"yue","revoked":False}]
        self.state["sources"]=[{"id":"fact-source","text":"A creator-owned baking notebook.","kind":"idea","active":True,"selected":True,"sourcePolicy":"public_quote","egressConsent":["cloud"],"useApprovals":[],
            "facts":[{"id":"fact1","approved":True,"text":"I keep a baking notebook."}]}]
        with self.connect() as db:db.execute("UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s",(json.dumps(self.state),self.wid))
        self.tid=self.store.get_receipt(self.wid,self.actor,self.rid)["payload"]["trend_id"]
        with self.hosted.repository.transaction("fixture",self.wid) as (cur,row,actor):
            self.oid=opportunities.persist_workspace_candidates(self.store,cur,self.wid,self.actor,self.state,[self.tid],datetime.now(timezone.utc).timestamp())[0]["id"]
        for dimension,key in zip(("system","provider","workspace"),generation.reviewed_generation({"manifest":{"reviewed_by":"x","review_ref":"x","model_generation":review(self.prefix)}},"angle_generate",self.wid)["budget_keys"]):
            TrendJobs(self.store).configure_budget(key,dimension,100000,self.start,self.end)
        self.generated_calls=[];self.generate_side_effect=None;self.generate_cost=.0001;self.bad_output=False;self.blocking_risk=False;self.http_status=200
        def transport(method,url,*,headers,body,timeout):
            self.generated_calls.append(copy.deepcopy(body));self.assertEqual(url,DEFAULT_ENDPOINT);self.assertLessEqual(timeout,3)
            if self.http_status!=200:return {"status":self.http_status,"body":{}}
            p=json.loads(body["messages"][1]["content"])
            task=next(t for t in generation.TASKS if "Task: trend."+t in body["messages"][0]["content"])
            if self.generate_side_effect:self.generate_side_effect()
            value=output(task,p)
            if self.bad_output:value["items"][0]["evidence_spans"][0]["text"]="forged"
            if self.blocking_risk and task=="angle_generate":value["items"][0]["risk"]["assessment"]="concern"
            response={"model":MODEL,"choices":[{"message":{"content":json.dumps(value)},"finish_reason":"stop"}],"usage":{}}
            if self.generate_cost is not None:response["usage"]={"cost":self.generate_cost}
            return {"status":200,"body":response}
        self.runtime=ServerModelRuntime("synthetic",model=MODEL,transport=transport)
        self.hosted.ideas=IdeasService(self.hosted.repository,self.hosted.repository.commands,runtime=self.runtime,runtimes=[self.runtime],researcher=False)
        self.hosted.commands=self.hosted.repository.commands;self.hosted.connection_factory=self.connect
        cw=CoworkerService(self.hosted,values=self.values)
        self.svc=TrendService(cw,cursor_secret=b"synthetic-test-signing-key-32-bytes")
        self.generator=generation.TrendGeneration(self.hosted,store=self.store,values=self.values,monotonic=lambda:0)

    def enqueue(self,task="angle_generate"):
        return self.generator.enqueue(self.wid,self.actor,self.rid,task,idempotency_key="gen-"+task)

    def usage(self):
        return enrichment_tests.EnrichmentPostgresTests.usage(self)

    def test_actual_planner_to_private_revision_existing_accept_lineage(self):
        result=self.generator.plan_current(max_jobs=1,max_workspaces=1)
        self.assertEqual(result["queued"],1,result)
        outcome=self.generator.tick();self.assertEqual(outcome["attached"],1,outcome)
        self.assertEqual(len(self.generated_calls),1)
        wire=self.svc.opportunity(self.wid,"fixture",self.oid)["data"]
        self.assertEqual(wire["revision"],2);self.assertEqual(wire["state"],"ready")
        self.assertTrue(wire["angles"])
        self.assertIsNone(self.svc.get(self.wid,"fixture",self.tid)["data"]["inferred"]["stage"])
        raw=self.store.get_opportunity(self.wid,self.actor,self.oid)
        self.assertFalse(raw["payload"]["qualified"]);self.assertTrue(raw["payload"]["executable_ready"])
        self.assertEqual(raw["payload"]["semantic_qualification"],"unqualified")
        selection={"revision":2,"angle_id":wire["angles"][0]["id"],"channel_id":"bake","goal":"Make a careful notebook experiment","idempotency_key":"generated-accept"}
        accepted=self.svc.accept(self.wid,"fixture",self.oid,selection)
        replay=self.svc.accept(self.wid,"fixture",self.oid,selection)
        self.assertEqual(accepted["data"]["source_id"],replay["data"]["source_id"])
        state=self.hosted.repository.get(self.wid,"fixture")["state"]
        bound=opportunities.lineage(state,[accepted["data"]["source_id"]])[0]
        self.assertEqual(bound["opportunity_revision"],2);self.assertEqual(bound["trust_receipt_id"],self.rid)
        self.assertEqual(bound["angle"]["semantic_qualification"],"unqualified")
        self.assertEqual(bound["generation_context"]["source_ids"],["fact-source"])
        from postriff_phase2.growth.trends.service import validate_stored_bindings
        with self.hosted.repository.transaction("fixture",self.wid) as (cur,row,actor):
            validate_stored_bindings(self.connect,cur,self.wid,actor,row[1],[bound],datetime.now(timezone.utc).timestamp())
        for mutation in self.context_mutations():
            changed=copy.deepcopy(state);mutation(changed)
            with self.subTest(mutation=mutation.__name__):
                with self.assertRaises(Exception):opportunities.validate_lineage(changed,[bound],datetime.now(timezone.utc).timestamp())
                with self.hosted.repository.transaction("fixture",self.wid) as (cur,row,actor):
                    with self.assertRaises(Exception):validate_stored_bindings(self.connect,cur,self.wid,actor,changed,[bound],datetime.now(timezone.utc).timestamp())
        self.assertEqual(self.usage(),[("ok",100)])
        self.assertEqual(state.get("phase2",{}).get("jobs",[]),[])

    @staticmethod
    def context_mutations():
        def memory_revoke(s):s["memoryEgress"]["cloud"]=False
        def fact_unapprove(s):s["sources"][0]["facts"][0]["approved"]=False
        def fact_edit(s):s["sources"][0]["facts"][0]["text"]="Changed factual premise"
        def source_revoke(s):s["sources"][0]["egressConsent"]=[]
        def source_policy_change(s):s["sources"][0]["sourcePolicy"]="rewrite_approval"
        return [memory_revoke,fact_unapprove,fact_edit,source_revoke,source_policy_change]

    def test_generated_option_rechecks_fact_and_consent_before_accept(self):
        from postriff_alpha.domain import AlphaError
        self.enqueue();self.assertEqual(self.generator.tick()["attached"],1)
        raw=self.store.get_opportunity(self.wid,self.actor,self.oid)
        choice={"revision":2,"angle_id":raw["payload"]["angles"][0]["id"],"channel_id":"bake","goal":"Review","idempotency_key":"changed-context"}
        for mutation in self.context_mutations():
            changed=copy.deepcopy(self.state);mutation(changed)
            with self.subTest(mutation=mutation.__name__):
                with self.connect() as db:db.execute("UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s",(json.dumps(changed),self.wid))
                with self.assertRaises(AlphaError) as caught:self.svc.accept(self.wid,"fixture",self.oid,choice)
                self.assertEqual(caught.exception.status,409)
                saved=self.hosted.repository.get(self.wid,"fixture")["state"]
                self.assertEqual(len(saved["sources"]),1)
        self.assertEqual(len(self.generated_calls),1);self.assertEqual(self.usage(),[("ok",100)])

    def test_source_linked_annotation_accessor_and_context_recheck(self):
        for task in ("semantic_label_generate","culture_explain"):
            self.enqueue(task);self.assertEqual(self.generator.tick()["attached"],1)
            with self.hosted.repository.transaction("fixture",self.wid) as (cur,row,actor):
                found=generation.current_annotations(self.store,workspace_id=self.wid,actor_id=actor,receipt_id=self.rid,state=row[1],task="trend."+task,cursor=cur,values=self.values)
                self.assertIsNotNone(found);self.assertEqual(found["result"]["task"],"trend."+task)
                self.assertEqual(found["result"]["calibration_state"],"unqualified")
                self.assertTrue(found["result"]["items"][0]["evidence_spans"])
        self.assertEqual(len(self.generated_calls),2)
        with self.connect() as db:db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{memoryEgress,cloud}','false') WHERE id=%s",(self.wid,))
        with self.hosted.repository.transaction("fixture",self.wid) as (cur,row,actor):
            self.assertIsNone(generation.current_annotations(self.store,workspace_id=self.wid,actor_id=actor,receipt_id=self.rid,state=row[1],task="culture_explain",cursor=cur,values=self.values))

    def test_revoked_during_generation_keeps_usage_no_annotation_or_op_revision(self):
        from postriff_phase2.growth.trends.revocation import revoke_policy
        queued=self.enqueue();self.generate_side_effect=lambda:revoke_policy(self.store,self.scope,self.provider,"1")
        result=self.generator.tick();self.assertEqual(result["discarded"],1,result)
        self.assertEqual(self.usage(),[("ok",100)])
        self.assertIsNone(self.store.get_projection(self.wid,self.actor,"model_judgment",queued["result_id"]))
        with self.connect() as db:self.assertEqual(db.execute("SELECT max(revision) FROM pr_trend_projections WHERE object_id=%s AND kind='opportunity'",(self.oid,)).fetchone()[0],1)

    def test_unknown_cost_and_invalid_span_account_before_reject(self):
        self.generate_cost=None;one=self.enqueue("semantic_label_generate")
        self.assertEqual(self.generator.tick()["discarded"],1)
        self.assertEqual(self.usage(),[("ok",None)])
        self.assertIsNone(self.store.get_projection(self.wid,self.actor,"model_judgment",one["result_id"]))
        self.generate_cost=.0001;self.bad_output=True;two=self.enqueue("culture_explain")
        self.assertEqual(self.generator.tick()["discarded"],1)
        self.assertEqual(self.usage(),[("ok",None),("malformed",100)])
        self.assertIsNone(self.store.get_projection(self.wid,self.actor,"model_judgment",two["result_id"]))

    def test_context_change_during_call_rejects_but_bills_attempt(self):
        self.enqueue()
        def change():
            with self.connect() as db:db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{brandHub,subject}','\"different\"') WHERE id=%s",(self.wid,))
        self.generate_side_effect=change
        self.assertEqual(self.generator.tick()["discarded"],1)
        self.assertEqual(self.usage(),[("ok",100)])

    def test_disabled_and_missing_fact_never_dispatch(self):
        self.generator.values={};self.assertEqual(self.generator.plan_current()["queued"],0)
        self.assertEqual(self.generator.tick()["provider_attempts"],0)
        self.generator.values=self.values
        with self.connect() as db:db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{sources}','[]') WHERE id=%s",(self.wid,))
        with self.assertRaises(contracts.ContractError):self.enqueue()
        self.assertEqual(self.generated_calls,[])

    def test_blocking_risk_remains_candidate_and_foreign_actor_has_no_annotation(self):
        from postriff_alpha.domain import AlphaError
        self.blocking_risk=True;self.enqueue();result=self.generator.tick()
        self.assertEqual(result["attached"],1,result)
        op=self.store.get_opportunity(self.wid,self.actor,self.oid)
        self.assertEqual(op["payload"]["state"],"candidate");self.assertFalse(op["payload"]["executable_ready"])
        with self.assertRaises(AlphaError):
            self.svc.accept(self.wid,"fixture",self.oid,{"revision":2,"angle_id":op["payload"]["angles"][0]["id"],"channel_id":"bake","goal":"review","idempotency_key":"risk"})
        with self.hosted.repository.transaction("fixture",self.wid) as (cur,row,actor):
            self.assertIsNone(generation.current_annotations(self.store,workspace_id=self.wid,actor_id=str(uuid.uuid4()),receipt_id=self.rid,state=row[1],task="angle_generate",cursor=cur,values=self.values))

    def test_http429_unknown_cost_passes_durable_usage_gate_without_zero_inference(self):
        self.http_status=429;queued=self.enqueue()
        outcome=self.generator.tick();self.assertEqual(outcome["discarded"],1,outcome)
        self.assertEqual(len(self.generated_calls),1)
        with self.connect() as db:
            event=db.execute("SELECT status,cost_source,cost_usd_micro FROM pr_model_usage_events WHERE workspace_id=%s",(self.wid,)).fetchone()
            reserve=db.execute("SELECT r.state,r.actual_micro_usd,r.usage_event_id IS NOT NULL FROM pr_trend_budget_reservations r JOIN pr_trend_jobs j USING(scope_key,reservation_id) WHERE j.job_id=%s",(queued["job_id"],)).fetchone()
        self.assertEqual(event,("rate_limited","unknown",None));self.assertEqual(reserve,("unknown",None,True))
        self.assertIsNone(self.store.get_projection(self.wid,self.actor,"model_judgment",queued["result_id"]))
        self.assertEqual(self.generator.tick()["provider_attempts"],0)
