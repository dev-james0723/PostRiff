"""Bounded Lab diagnostics; injected JEV transport, actual isolated PostgreSQL."""
import copy
from datetime import datetime,timezone
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from postriff_phase2.growth.trends import contracts,lab_enrichment,opportunities
from postriff_phase2.growth.judgments import validate_answers
from postriff_phase2.growth.jev import JevService,DEFAULT_MODEL,EVALUATE_ENDPOINT
import test_trend_generation as generation_tests
import test_trend_enrichment as enrichment_tests


def sample_pack():
    text="香港麵包焗爐溫度實驗，今次記錄發酵時間同麵糰水份。"
    return {"evidence":[{"observation_id":"e1","text":text}],"draft":{"id":"d","revision":1,"text":text+" 原創實驗構思"},
        "draft_spans":lab_enrichment.spans(text+" 原創實驗構思"),"workspace_context":{"approved_facts":[]},
        "own_history":{"comparable":False,"observations":[],"reason":"explicit_comparison_frame_missing"}}


def answers(qs,choice="supported"):
    return {q.name:{"type":"choice","choice":(choice if choice in q.criteria else "r0" if "r0" in q.criteria else "unsure"),
        "probabilities":{v:1.0 if v==(choice if choice in q.criteria else "r0" if "r0" in q.criteria else "unsure") else 0.0 for v in q.criteria}} for q in qs.questions}


class LabEnrichmentUnitTests(unittest.TestCase):
    def test_typed_all_dimensions_native_support_and_abstention(self):
        pack=sample_pack();qs=lab_enrichment.question_set(pack)
        parsed,invalid=validate_answers(qs,answers(qs));self.assertEqual(invalid,())
        findings=lab_enrichment.diagnostics(SimpleNamespace(answers=parsed),pack,{})
        self.assertEqual({d["dimension"] for d in findings},set(lab_enrichment.opportunity_lab.DIAGNOSTICS))
        for d in findings:
            if d["dimension"] in ("hook_crowding","timing","historical_similarity"):self.assertEqual(d["assessment"],"unknown")
            else:self.assertEqual(d["evidence_refs"],["e1"])
        raw=answers(qs);raw["trend_relevance_source"]={"type":"choice","choice":"unsure","probabilities":{"r0":0,"unsure":1}}
        parsed,_=validate_answers(qs,raw)
        self.assertEqual(lab_enrichment.diagnostics(SimpleNamespace(answers=parsed),pack,{})[0]["assessment"],"unknown")
        self.assertTrue(all(d["suggested_edit"] is None for d in findings))

    def test_personal_claim_never_creates_experience_or_edit(self):
        pack=sample_pack();pack["draft"]["text"]="我測試過最新產品，效果最好。";pack["draft_spans"]=lab_enrichment.spans(pack["draft"]["text"])
        qs=lab_enrichment.question_set(pack);parsed,_=validate_answers(qs,answers(qs,"concern"))
        out=lab_enrichment.diagnostics(SimpleNamespace(answers=parsed),pack,{})
        self.assertTrue(all(x["requires_user_fact"] for x in out));self.assertTrue(all(x["suggested_edit"] is None for x in out))

    def test_only_exact_same_explicit_owned_cohort_is_comparable(self):
        frame=dict(account="a",provider="bluesky",language="yue",format="text",window="24h",objective="conversation",definition="v1",metric="replies")
        rows=[{"job_id":str(i),"state":"measured","cohort":copy.deepcopy(frame),"paid_promotion":False,"observed_at":20,"available_at":30,
            "publication":{"published_at":10},"metric_receipts":[str(i)],"value":i} for i in range(3)]
        self.assertTrue(lab_enrichment.comparable_history(rows,frame,40)["comparable"])
        for field in frame:
            bad=copy.deepcopy(rows);bad[0]["cohort"][field]="different"
            self.assertFalse(lab_enrichment.comparable_history(bad,frame,40)["comparable"],field)
        for change in (lambda r:r.update(paid_promotion=None),lambda r:r.update(available_at=50),lambda r:r.update(state="unpublished"),lambda r:r.update(metric_receipts=[])):
            bad=copy.deepcopy(rows);change(bad[0]);self.assertFalse(lab_enrichment.comparable_history(bad,frame,40)["comparable"])
        self.assertFalse(lab_enrichment.comparable_history(rows,{},40)["comparable"])

    def test_injected_native_evaluator_records_one_attempt_and_only_validated_edit(self):
        from postriff_phase2.growth.usage import MemoryUsageSink
        pack=sample_pack();pack["input_digest"]=contracts.digest(pack)
        qs=lab_enrichment.question_set(pack);raw=answers(qs,"concern");calls=[]
        def transport(method,url,*,headers,body,timeout):
            calls.append(body)
            return {"status":200,"body":{"model":DEFAULT_MODEL,"answers":raw,"providerMetadata":{"gateway":{"cost":"0.0001","routing":{"finalProvider":"synthetic"}}}}}
        worker=lab_enrichment.TrendLabEnrichment(SimpleNamespace(repository=SimpleNamespace(connection_factory=lambda:None)))
        model=JevService("synthetic",transport=transport);sink=MemoryUsageSink()
        old={"dimension":"originality","evidence_refs":["e1"],"suggested_edit":{"id":"remove-copy","before":pack["evidence"][0]["text"],"after":"","reason":"Remove literal copy"}}
        loaded={"pack":pack,"config":{"model":DEFAULT_MODEL},"receipt":{"object_id":"receipt"},"lab":{"object_id":"run","payload":{"frozen_run":{"diagnostics":[old]}}}}
        result=worker.execute(model,loaded,"draft_diagnostic:run",str(uuid.uuid4()),sink)
        self.assertEqual(result["status"],"ok");self.assertEqual(result["calibration_state"],"unqualified")
        self.assertEqual(len(calls),1);self.assertEqual(len(sink.events),1)
        finding=next(d for d in result["diagnostics"] if d["dimension"]=="originality")
        self.assertEqual(finding["suggested_edit"],old["suggested_edit"])
        self.assertTrue(all(d["suggested_edit"] is None for d in result["diagnostics"] if d["dimension"]!="originality"))

    def test_disabled_never_constructs_model_or_database(self):
        worker=lab_enrichment.TrendLabEnrichment(SimpleNamespace(repository=SimpleNamespace(connection_factory=lambda:self.fail("DB"))),values={})
        self.assertEqual(worker.enqueue_run(str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4()),idempotency_key="x")["status"],"disabled")
        self.assertEqual(worker.tick()["provider_attempts"],0)


@unittest.skipUnless(os.environ.get("TREND_LAB_TEST_DSN"),"explicit disposable Lab DSN required")
class LabEnrichmentPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ,{"TREND_ENRICHMENT_TEST_DSN":os.environ["TREND_LAB_TEST_DSN"]}):
            enrichment_tests.EnrichmentPostgresTests.setUpClass.__func__(cls)

    def usage(self):return enrichment_tests.EnrichmentPostgresTests.usage(self)

    def setUp(self):
        from postriff_phase2.growth.trends.store import TrendStore
        original=TrendStore.register_policy
        def policy(store,value,**kwargs):
            value=copy.deepcopy(value)
            value["model_lab"]={**enrichment_tests.model_policy(self.prefix),"tasks":["draft_diagnostic"],"include_owned_history":False}
            return original(store,value,**kwargs)
        with patch.object(TrendStore,"register_policy",policy):generation_tests.GenerationPostgresTests.setUp(self)
        self.values["RAFII_TREND_OPPORTUNITY_LAB_ENABLED"]="1"
        self.svc.values["RAFII_TREND_OPPORTUNITY_LAB_ENABLED"]="1"
        self.generator.enqueue(self.wid,self.actor,self.rid,"angle_generate",idempotency_key="fixture-angle")
        self.assertEqual(self.generator.tick()["attached"],1)
        op=self.store.get_opportunity(self.wid,self.actor,self.oid)
        accepted=self.svc.accept(self.wid,"fixture",self.oid,{"revision":2,"angle_id":op["payload"]["angles"][0]["id"],"channel_id":"bake","goal":"A careful notebook","idempotency_key":"fixture-accept"})
        state=self.hosted.repository.get(self.wid,"fixture")["state"]
        native=self.svc.get(self.wid,"fixture",self.tid)["data"]["evidence"][0]["excerpt"]
        self.did=str(uuid.uuid4())
        state["variants"]=[{"id":self.did,"revision":1,"text":native+"\n原創：記錄下一次實驗嘅問題。","platform":"Bluesky","contentType":{"id":"text"},
            "sourceIds":[accepted["data"]["source_id"]],"trendLineage":opportunities.lineage(state,[accepted["data"]["source_id"]])}]
        with self.connect() as db:db.execute("UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s",(json.dumps(state),self.wid))
        self.request={"draft_id":self.did,"draft_revision":1,"opportunity_id":self.oid,"opportunity_revision":2,"target_platform":"Bluesky","idempotency_key":"fixture-lab"}
        self.run=self.svc.lab_create(self.wid,"fixture",self.request)["data"]["id"]
        self.lab_calls=[];self.lab_side_effect=None;self.lab_cost="0.0001"
        def transport(method,url,*,headers,body,timeout):
            self.lab_calls.append(copy.deepcopy(body));self.assertEqual(url,EVALUATE_ENDPOINT);self.assertLessEqual(timeout,3)
            if self.lab_side_effect:self.lab_side_effect()
            result={}
            for k,q in body["questions"].items():
                value="concern" if k=="originality" else "supported" if "supported" in q["criteria"] else "r0" if "r0" in q["criteria"] else "unsure"
                result[k]={"type":"choice","choice":value,"probabilities":{v:float(v==value) for v in q["criteria"]}}
            gateway={"routing":{"finalProvider":"synthetic"}}
            if self.lab_cost is not None:gateway["cost"]=self.lab_cost
            return {"status":200,"body":{"model":DEFAULT_MODEL,"answers":result,"providerMetadata":{"gateway":gateway}}}
        self.lab=lab_enrichment.TrendLabEnrichment(self.hosted,store=self.store,values=self.values,monotonic=lambda:0,
            jev_factory=lambda cfg:JevService("synthetic",endpoint=cfg["endpoint"],model=cfg["model"],transport=transport))

    def enqueue(self):return self.lab.enqueue_run(self.wid,self.actor,self.run,idempotency_key="semantic-pass")

    def current(self):
        with self.hosted.repository.transaction("fixture",self.wid) as (cur,row,actor):
            return self.lab.current_result(cur,self.wid,actor,self.run,row[1])

    def test_durable_semantic_pass_existing_lab_read_replay_and_no_apply(self):
        before=copy.deepcopy(self.hosted.repository.get(self.wid,"fixture")["state"])
        one=self.enqueue();self.assertEqual(one["status"],"queued")
        result=self.lab.tick();self.assertEqual(result["attached"],1,result)
        stored=self.store.get_projection(self.wid,self.actor,"lab_run",self.run)
        self.assertEqual(stored["revision"],2);self.assertEqual(len(stored["payload"]["diagnostics"]),9)
        self.assertEqual(self.current()["calibration_state"],"unqualified")
        self.assertEqual(self.enqueue()["status"],"cached");self.assertEqual(self.lab.tick()["provider_attempts"],0)
        after=self.hosted.repository.get(self.wid,"fixture")["state"]
        self.assertEqual(before,after);self.assertEqual(len(self.lab_calls),1)
        self.assertEqual(self.usage(),[("ok",100),("ok",100)])
        from test_trend_service import assert_schema
        wire=self.svc.stored(self.wid,"fixture","lab",self.run)
        assert_schema(self,"lab_run_response",wire)
        findings={d["dimension"]:d for d in self.current()["diagnostics"]}
        self.assertEqual(findings["historical_similarity"]["assessment"],"unknown")
        self.assertEqual(findings["originality"]["assessment"],"concern")
        self.assertEqual(self.svc.lab_create(self.wid,"fixture",self.request)["data"]["draft_revision"],1)

    def test_draft_edit_during_attempt_keeps_usage_without_result(self):
        queued=self.enqueue()
        def change():
            with self.connect() as db:db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{variants,0,revision}','2') WHERE id=%s",(self.wid,))
        self.lab_side_effect=change
        outcome=self.lab.tick();self.assertEqual(outcome["discarded"],1,outcome)
        self.assertEqual(self.usage(),[("ok",100),("ok",100)])
        self.assertIsNone(self.store.get_projection(self.wid,self.actor,"model_judgment",queued["result_id"]))
        self.assertEqual(self.store.get_projection(self.wid,self.actor,"lab_run",self.run)["revision"],1)

    def test_revocation_during_attempt_preserves_cost_suppresses_diagnostics(self):
        from postriff_phase2.growth.trends.revocation import revoke_policy
        self.enqueue();self.lab_side_effect=lambda:revoke_policy(self.store,self.scope,self.provider,"1")
        outcome=self.lab.tick();self.assertEqual(outcome["discarded"],1,outcome)
        self.assertEqual(self.usage(),[("ok",100),("ok",100)]);self.assertIsNone(self.current())

    def test_stale_context_or_disabled_or_foreign_actor_never_reads_diagnostics(self):
        self.enqueue();self.assertEqual(self.lab.tick()["attached"],1)
        self.lab.values={};self.assertIsNone(self.current());self.lab.values=self.values
        with self.hosted.repository.transaction("fixture",self.wid) as (cur,row,actor):
            self.assertIsNone(self.lab.current_result(cur,self.wid,str(uuid.uuid4()),self.run,row[1]))
        with self.connect() as db:db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{memoryEgress,cloud}','false') WHERE id=%s",(self.wid,))
        self.assertIsNone(self.current())

    def test_second_linked_draft_blocks_queued_pass_without_dispatch(self):
        self.enqueue()
        state=self.hosted.repository.get(self.wid,"fixture")["state"]
        other=copy.deepcopy(state["variants"][0]);other["id"]=str(uuid.uuid4());state["variants"].append(other)
        with self.connect() as db:db.execute("UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s",(json.dumps(state),self.wid))
        result=self.lab.tick();self.assertEqual(result["provider_attempts"],0,result)
        self.assertEqual(self.lab_calls,[]);self.assertEqual(self.usage(),[("ok",100)])

    def test_unknown_cost_has_no_semantic_revision_and_no_retry(self):
        self.lab_cost=None;self.enqueue();self.assertEqual(self.lab.tick()["discarded"],1)
        self.assertEqual(self.usage(),[("ok",100),("ok",None)])
        self.assertEqual(self.store.get_projection(self.wid,self.actor,"lab_run",self.run)["revision"],1)
        self.assertEqual(self.lab.tick()["provider_attempts"],0)
