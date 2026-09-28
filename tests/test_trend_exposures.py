"""WP16: synthetic inputs, actual authenticated PostgreSQL transactions; no egress."""
import copy
import json
import os
import time
import unittest
import uuid
from unittest.mock import patch
from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.trends import exposure_events, opportunities
from test_trend_opportunities import PAYLOAD
from test_trend_service import assert_schema, make_service, WID
import test_trend_integration as integration


class ExposureBoundaryTests(unittest.TestCase):
    def test_candidates_are_bounded_unique_and_strict(self):
        oid = str(uuid.uuid4())
        for candidates in ([], [{"opportunity_id":oid,"revision":True}], [{"opportunity_id":oid,"revision":1}]*2,
                           [{"opportunity_id":str(uuid.uuid4()),"revision":1} for _ in range(21)],
                           [{"opportunity_id":oid,"revision":1,"text":"forbidden"}]):
            with self.assertRaises(AlphaError): exposure_events.parse_candidates(candidates)
        self.assertEqual(exposure_events.parse_candidates([{"opportunity_id":oid,"revision":1}]), [{"opportunity_id":oid,"revision":1}])

    def test_test_database_guards_reject_redirects_before_connect(self):
        import test_trend_enrichment as enrichment_tests
        import psycopg
        base={"host":"127.0.0.1","port":"55438","dbname":"postgres"}
        from psycopg.conninfo import make_conninfo
        for cls,key in ((integration.DurableServiceTests,"TREND_SERVICE_TEST_DSN"),
                        (enrichment_tests.EnrichmentPostgresTests,"TREND_ENRICHMENT_TEST_DSN")):
            for setting in ({"PGSERVICE":"forbidden"},{"PGHOSTADDR":"203.0.113.1"},{"PGOPTIONS":"-c role=postgres"}):
                with patch.dict(os.environ,{key:make_conninfo(**base),**setting}), patch.object(psycopg,"connect",side_effect=AssertionError("unexpected connect")):
                    with self.assertRaises(ValueError):cls.setUpClass()
            for change in ({"host":"example.invalid"},{"dbname":"production"},{"options":"-c role=postgres"}):
                with patch.dict(os.environ,{key:make_conninfo(**{**base,**change})}), patch.object(psycopg,"connect",side_effect=AssertionError("unexpected connect")):
                    with self.assertRaises(ValueError):cls.setUpClass()

    def test_disabled_list_has_no_token_or_side_effect(self):
        svc,repo,store = make_service()
        svc.values["RAFII_TREND_TRUST_RECEIPTS_ENABLED"]="0"
        page = svc.list(WID,"session",kind="opportunity")
        self.assertIsNone(page["exposure_token"])
        self.assertEqual(repo.state["sources"],[])


@unittest.skipUnless(os.environ.get("TREND_EXPOSURE_TEST_DSN"), "explicit disposable exposure PostgreSQL DSN required")
class DurableExposureTests(unittest.TestCase):
    def setUp(self):
        # Reuse the documented synthetic service seed. Each test gets new tenant,
        # actor, immutable projections and NOSUPERUSER/NOBYPASSRLS role.
        with patch.dict(os.environ, {"TREND_SERVICE_TEST_DSN":os.environ["TREND_EXPOSURE_TEST_DSN"]}):
            integration.DurableServiceTests.setUpClass.__func__(type(self))

    def page(self):
        result = self.svc.list(self.wid,"fixture-session",kind="opportunity")
        assert_schema(self,"opportunities_response",result)
        op = next(p for p in result["data"] if p["id"]==self.oid)
        payload = {"event_id":str(uuid.uuid4()),"exposure_token":result["exposure_token"],"opportunity_id":op["id"],
            "opportunity_revision":op["revision"],"trust_receipt_id":op["trust_receipt_id"],"context_digest":op["context_digest"],
            "eligible_candidates":exposure_events.candidate_ids(result["data"])}
        assert_schema(self,"exposureInputSchema",payload)
        return payload

    def view(self,payload=None):
        result=self.svc.exposure(self.wid,"fixture-session",payload or self.page())
        assert_schema(self,"exposure_response",result)
        return result["data"]

    def denied(self,status,fn):
        with self.assertRaises(AlphaError) as error:fn()
        self.assertEqual(error.exception.status,status)

    def count(self,table,where="workspace_id",value=None):
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM "+table+" WHERE "+where+"=%s",(value or self.wid,)).fetchone()[0]

    def test_view_retained_without_acceptance_and_retry_dedupes(self):
        payload=self.page()
        self.assertEqual(self.count("pr_trend_projections","scope_key","workspace:"+self.wid),3)
        with patch.object(self.svc.coworker,"_broker",side_effect=AssertionError("forbidden egress")):
            one=self.view(payload);two=self.view(payload)
        self.assertFalse(one["existing"]);self.assertTrue(two["existing"])
        self.assertEqual(one["exposure_id"],payload["event_id"])
        self.assertEqual(one["measurement"],"client_reported_view")
        self.assertEqual(self.count("pr_trend_projections","scope_key","workspace:"+self.wid),4)
        self.assertEqual(self.count("pr_trend_opportunity_decisions"),0)
        state=self.svc.repository.get(self.wid,"fixture-session")["state"]
        self.assertEqual(state["sources"],[])
        self.assertEqual(state.get("phase2",{}).get("jobs",[]),[])
        with self.connect() as db:
            saved=db.execute("SELECT payload FROM pr_trend_projections WHERE scope_key=%s AND kind='exposure'",("workspace:"+self.wid,)).fetchone()[0]
            refs=db.execute("SELECT count(*) FROM pr_trend_manifest_inputs m JOIN pr_trend_projections p USING(scope_key,manifest_id) WHERE p.scope_key=%s AND p.kind='exposure'",("workspace:"+self.wid,)).fetchone()[0]
        self.assertEqual(refs,3)
        self.assertEqual(saved["actor_id"],self.actor)
        self.assertEqual(saved["candidate_scope"],"returned_page")
        self.assertFalse({"text","excerpt","goal","draft"}&set(saved))

    def test_acceptance_keeps_real_exposure_but_no_publication_or_outcome(self):
        payload=self.page();view=self.view(payload)
        request={**PAYLOAD,"exposure_id":view["exposure_id"]}
        result=self.svc.accept(self.wid,"fixture-session",self.oid,request)
        self.assertTrue(self.svc.accept(self.wid,"fixture-session",self.oid,request)["data"]["existing"])
        self.assertTrue(self.view(payload)["existing"])
        state=self.svc.repository.get(self.wid,"fixture-session")["state"]
        binding=opportunities.lineage(state,[result["data"]["source_id"]])
        self.assertEqual(binding[0]["exposure_id"],view["exposure_id"])
        from postriff_phase2.growth.trends import learning
        from postriff_phase2.growth.trends.store import TrendStore
        with self.connect() as db:
            decision=db.execute("SELECT result FROM pr_trend_opportunity_decisions WHERE workspace_id=%s",(self.wid,)).fetchone()[0]
            self.assertEqual(decision['exposure_id'],view['exposure_id'])
            report=learning.report(db.cursor(),self.wid,self.actor,time.time(),store=TrendStore(self.connect))
        self.assertEqual(report['denominator']['exposures'],1)
        self.assertEqual(report['denominator']['accepted'],1)
        self.assertEqual(report['denominator']['accepted_without_exposure'],0)
        self.assertEqual(report['exposures'][0]['publication_coverage'],'not_published')
        self.assertEqual(report['exposures'][0]['outcomes'],[])
        self.assertEqual(state.get("phase2",{}).get("jobs",[]),[])
        from postriff_phase2.growth import scout_outcomes
        with self.connect() as db:self.assertEqual(scout_outcomes.refresh(db.cursor(),self.wid,state,time.time()),[])
        self.assertEqual(self.count("pr_trend_projections","scope_key","workspace:"+self.wid),4)
        self.denied(409,lambda:self.svc.dismiss(self.wid,"fixture-session",self.oid,{"revision":1,"idempotency_key":"late"}))

    def test_legacy_accept_does_not_invent_exposure(self):
        result=self.svc.accept(self.wid,"fixture-session",self.oid,PAYLOAD)
        state=self.svc.repository.get(self.wid,"fixture-session")["state"]
        self.assertNotIn("exposure_id",opportunities.lineage(state,[result["data"]["source_id"]])[0])
        from postriff_phase2.growth.trends import learning
        from postriff_phase2.growth.trends.store import TrendStore
        with self.connect() as db:
            decision=db.execute("SELECT result FROM pr_trend_opportunity_decisions WHERE workspace_id=%s",(self.wid,)).fetchone()[0]
            self.assertNotIn('exposure_id',decision)
            report=learning.report(db.cursor(),self.wid,self.actor,time.time(),store=TrendStore(self.connect))
        self.assertEqual(report['denominator']['exposures'],0)
        self.assertEqual(report['denominator']['accepted'],0)
        self.assertEqual(report['denominator']['accepted_without_exposure'],1)
        self.assertEqual(self.count("pr_trend_projections","scope_key","workspace:"+self.wid),3)

    def test_dismiss_is_idempotent_decision_without_revision_bump(self):
        view=self.view();request={"revision":1,"idempotency_key":"not-relevant","exposure_id":view["exposure_id"]}
        assert_schema(self,"dismissOpportunityInputSchema",request)
        first=self.svc.dismiss(self.wid,"fixture-session",self.oid,request)
        assert_schema(self,"dismissed_opportunity_response",first)
        self.assertEqual(first["data"]["revision"],1);self.assertFalse(first["data"]["existing"])
        self.assertTrue(self.svc.dismiss(self.wid,"fixture-session",self.oid,request)["data"]["existing"])
        op=self.svc.opportunity(self.wid,"fixture-session",self.oid)["data"]
        self.assertEqual((op["state"],op["revision"]),("dismissed",1))
        self.assertIsNone(self.svc.list(self.wid,"fixture-session",kind="opportunity")["exposure_token"])
        self.assertEqual(self.count("pr_trend_opportunity_decisions"),1)
        self.denied(409,lambda:self.svc.accept(self.wid,"fixture-session",self.oid,PAYLOAD))
        self.denied(400,lambda:self.svc.dismiss(self.wid,"fixture-session",self.oid,{**request,"reason":"invented"}))
        self.assertEqual(self.svc.repository.get(self.wid,"fixture-session")["state"]["sources"],[])

    def test_forged_page_receipt_context_and_event_replay_denied(self):
        payload=self.page()
        for change,status in (({"exposure_token":payload["exposure_token"]+"x"},400),
                              ({"trust_receipt_id":str(uuid.uuid4())},409),({"context_digest":"wrong"},409),
                              ({"eligible_candidates":[{"opportunity_id":str(uuid.uuid4()),"revision":1}]},400),
                              ({"opportunity_revision":2},400)):
            self.denied(status,lambda change=change:self.view({**payload,**change}))
        self.view(payload)
        self.denied(409,lambda:self.view({**payload,"trust_receipt_id":str(uuid.uuid4())}))
        self.denied(404,lambda:self.svc.accept(self.wid,"fixture-session",self.oid,{**PAYLOAD,"exposure_id":str(uuid.uuid4())}))

    def test_foreign_actor_cannot_reuse_page_or_exposure(self):
        import psycopg
        from postriff_phase2.hosted import PostgresWorkspaceRepository
        from postriff_phase2.coworker.service import CoworkerService
        from postriff_phase2.growth.trends.service import TrendService
        from types import SimpleNamespace
        payload=self.page();view=self.view(payload);other=str(uuid.uuid4())
        with psycopg.connect(self.dsn) as db:
            db.execute("INSERT INTO auth.users(id) VALUES(%s)",(other,));db.execute("INSERT INTO pr_profiles(user_id) VALUES(%s)",(other,))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')",(self.wid,other))
        host=SimpleNamespace(**vars(self.svc.hosted));host.repository=PostgresWorkspaceRepository(self.connect,lambda token:other,host.commands)
        other_svc=TrendService(CoworkerService(host,values=self.svc.values),cursor_secret=self.svc.cursor_secret)
        self.denied(403,lambda:other_svc.exposure(self.wid,"other-session",payload))
        self.denied(403,lambda:other_svc.accept(self.wid,"other-session",self.oid,{**PAYLOAD,"exposure_id":view["exposure_id"]}))
        self.denied(403,lambda:other_svc.dismiss(self.wid,"other-session",self.oid,{"revision":1,"idempotency_key":"foreign","exposure_id":view["exposure_id"]}))
        self.denied(404,lambda:self.svc.exposure(str(uuid.uuid4()),"fixture-session",payload))

    def test_stale_context_expired_page_and_viewer_fail_closed(self):
        payload=self.page();clock=self.svc.clock
        self.svc.clock=lambda:clock()+301
        self.denied(410,lambda:self.view(payload));self.svc.clock=clock
        with self.connect() as db:
            db.execute("UPDATE pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(self.wid,self.actor))
        self.denied(403,lambda:self.view(payload))
        self.denied(403,lambda:self.svc.dismiss(self.wid,"fixture-session",self.oid,{"revision":1,"idempotency_key":"viewer"}))
        with self.connect() as db:
            db.execute("UPDATE pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s",(self.wid,self.actor))
            db.execute("UPDATE pr_workspaces SET state=jsonb_set(state,'{brandHub,audience}','\"different\"') WHERE id=%s",(self.wid,))
        self.denied(409,lambda:self.view(payload))

    def test_revocation_invalidates_view_accept_dismiss_even_with_original_token(self):
        from postriff_phase2.growth.trends.store import TrendStore
        from postriff_phase2.growth.trends.revocation import revoke_policy
        payload=self.page();view=self.view(payload);store=TrendStore(self.connect)
        with self.connect() as db:
            provider=db.execute("SELECT provider_id FROM pr_trend_source_policies WHERE scope_key=%s",("workspace:"+self.wid,)).fetchone()[0]
        revoke_policy(store,"workspace:"+self.wid,provider,"1")
        self.denied(410,lambda:self.view(payload))
        self.denied(410,lambda:self.svc.accept(self.wid,"fixture-session",self.oid,{**PAYLOAD,"exposure_id":view["exposure_id"]}))
        self.denied(410,lambda:self.svc.dismiss(self.wid,"fixture-session",self.oid,{"revision":1,"idempotency_key":"revoked","exposure_id":view["exposure_id"]}))
        self.assertIsNone(store.get_projection(self.wid,self.actor,"exposure",view["exposure_id"])["payload"])

    def test_superseded_opportunity_revision_rejects_old_page(self):
        from postriff_phase2.growth.trends.store import TrendStore
        store=TrendStore(self.connect);payload=self.page()
        with self.connect() as db:
            record=db.execute("SELECT scope_key,manifest_id,method_id,method_version,decision_cutoff,retention_until,payload FROM pr_trend_projections WHERE scope_key=%s AND kind='opportunity' AND object_id=%s",("workspace:"+self.wid,self.oid)).fetchone()
        keys=("scope_key","manifest_id","method_id","method_version","decision_cutoff","retention_until","payload")
        value=dict(zip(keys,record))
        for key in ("decision_cutoff","retention_until"): value[key]=opportunities.iso(value[key])
        value["manifest_id"]=str(value["manifest_id"])
        value.update(kind="opportunity",object_id=self.oid,revision=2,available_at=opportunities.iso(time.time()),receipt_id=self.rid)
        store.put_projection(value,expected_revision=1)
        self.denied(409,lambda:self.view(payload))

    def test_ordered_page_token_rechecks_unshown_candidate_revision(self):
        from postriff_phase2.growth.trends.store import TrendStore
        store=TrendStore(self.connect);other=str(uuid.uuid4())
        with self.connect() as db:
            record=db.execute("SELECT scope_key,manifest_id,method_id,method_version,decision_cutoff,retention_until,payload FROM pr_trend_projections WHERE scope_key=%s AND kind='opportunity' AND object_id=%s",("workspace:"+self.wid,self.oid)).fetchone()
        value=dict(zip(("scope_key","manifest_id","method_id","method_version","decision_cutoff","retention_until","payload"),record))
        for key in ("decision_cutoff","retention_until"):value[key]=opportunities.iso(value[key])
        value["manifest_id"]=str(value["manifest_id"]);value["payload"]["id"]=other
        value.update(kind="opportunity",object_id=other,revision=1,available_at=opportunities.iso(time.time()),receipt_id=self.rid)
        store.put_projection(value)
        payload=self.page();self.assertEqual(len(payload["eligible_candidates"]),2)
        self.denied(400,lambda:self.view({**payload,"eligible_candidates":list(reversed(payload["eligible_candidates"]))}))
        self.denied(400,lambda:self.view({**payload,"eligible_candidates":[{"opportunity_id":self.oid,"revision":1}]}))
        value.update(revision=2,available_at=opportunities.iso(time.time()));store.put_projection(value,expected_revision=1)
        self.denied(409,lambda:self.view(payload))
        self.assertEqual(self.count("pr_trend_projections","scope_key","workspace:"+self.wid),5)
