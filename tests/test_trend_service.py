"""Offline service tests: authenticated boundary, current trust and one wire schema."""
import copy
import json
import socket
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.ideas import IdeasService
from postriff_phase2.coworker.service import CoworkerService
from postriff_phase2.growth.trends import contracts, opportunities, relevance
from postriff_phase2.growth.trends.service import TrendService, coverage, build_trend_payload, build_receipt_payload

NOW = 1800000000
WID = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
ACTOR = "00000000-0000-4000-8000-000000000003"
TID = "00000000-0000-4000-8000-000000000004"
RID = "00000000-0000-4000-8000-000000000005"
OID = "00000000-0000-4000-8000-000000000006"
EID = "00000000-0000-4000-8000-000000000007"
END = opportunities.iso(NOW + 3600)
SCOPE = "workspace:" + WID
METHOD = {"method_id": "receipt-bundle", "version": "candidate-1"}


def grant():
    return {k: {"state": "allow", "policy_ref": "fixture-policy.v1", "audience_scope": SCOPE, "expires_at": END} for k in contracts.PERMISSIONS}


def fixture_row(kind, oid, payload, *, receipt_id=RID):
    return {"scope_key": SCOPE, "kind": kind, "object_id": oid, "revision": 1, "available_at": opportunities.iso(NOW-10),
            "expires_at": END, "validity": "valid", "verification_state": "verified", "method_bundle": METHOD,
            "receipt_id": receipt_id, "projection_id": oid, "policy": {"display_excerpt": True, "display_link": True, "derive_metrics": True, "retain_derivatives": True, "llm_process": True}, "payload": payload}


class Repository:
    def __init__(self):
        self.state = initial_phase2_state(WID, ACTOR, "Fixture", "studio", NOW)
        self.state["phase2"]["channels"] = [{"id": "channel-1", "platform": "Bluesky", "language": "en", "revoked": False}]
        self.role = "owner"
        self.effects = []
        self.queries = []
        self.revision = 1
        self.connection_factory = lambda: (_ for _ in ()).throw(AssertionError("unexpected independent connection"))

    @contextmanager
    def transaction(self, token, wid):
        if token != "session":
            raise AlphaError("bad session", 401)
        if wid != WID:
            raise AlphaError("foreign private title", 403)
        old = copy.deepcopy(self.state)
        try:
            yield self, (self.revision, self.state, self.role, False, False, False, False), ACTOR
        except Exception:
            self.state = old
            raise

    def execute(self, sql, args):
        self.queries.append(sql)
        if sql.startswith("UPDATE public.pr_workspaces"):
            self.state = json.loads(args[0])
            self.revision += 1


    def fetchone(self):
        return None


class Storage:
    def __init__(self):
        self.rows = {}
        self.calls = []
        self.scope_epoch = "epoch1"
        self.decisions = {}
        self.watches = []

    def authorized_scopes(self, wid, actor, *, cursor):
        assert wid == WID and actor == ACTOR
        return [SCOPE]

    def scope_signature(self, wid, actor, *, cursor):
        return self.scope_epoch

    def get_projection(self, wid, actor, kind, object_id, *, revision=None, cursor=None, as_of=None):
        self.calls.append(("get", kind, object_id, cursor))
        row = copy.deepcopy(self.rows.get((kind, object_id)))
        return row if row and (revision is None or row["revision"] == revision) else None

    def list_projections(self, wid, actor, *, kind="trend", limit=20, before=None, as_of=None, filters=None, method_bundle=None, cursor=None):
        self.calls.append(("list", kind, copy.deepcopy(filters), cursor))
        found = [copy.deepcopy(r) for r in self.rows.values() if r["kind"] == kind and r["validity"] == "valid"]
        key = lambda r: [r["available_at"], r["object_id"], r["revision"], r["scope_key"]]
        found = sorted([r for r in found if not before or key(r) < before], key=key, reverse=True)
        return {"items": found[:limit], "next_key": key(found[limit-1]) if len(found) > limit else None, "as_of": as_of}

    def lock_dependencies(self, wid, actor, bindings, *, cursor):
        self.calls.append(("lock", bindings, cursor))

    def decide_opportunity(self, wid, actor, oid, *, revision, decision, idempotency_key, result, cursor):
        prior = self.decisions.get(idempotency_key)
        if prior and prior["result"] != result:
            raise AlphaError("conflict", 409, code="revision_conflict")
        saved = {"result": result}
        self.decisions[idempotency_key] = saved
        return saved

    def put_watch(self, wid, actor, payload, *, idempotency_key, cursor, **kwargs):
        saved = {"watch_id": EID, "revision": 1, "enabled": True, "payload": payload}
        self.watches = [saved]
        return saved

    def list_watches(self, wid, actor, *, cursor):
        return self.watches

    def delete_watch(self, wid, actor, watch_id, *, expected_revision, idempotency_key, cursor):
        self.watches[0].update(enabled=False, revision=2)
        return self.watches[0]


    def ensure_scope(self, scope_key, *, cursor):
        return scope_key

    def put_method(self, *args, cursor):
        return None

    def put_manifest(self, scope_key, refs, **kwargs):
        return {"manifest_id": EID}

    def put_projection(self, value, *, cursor):
        self.rows[value["kind"], value["object_id"]] = fixture_row(value["kind"], value["object_id"], value["payload"], receipt_id=value.get("receipt_id"))
        return value["object_id"]


class Jobs:
    def __init__(self, store):
        self.store = store
    def enqueue(self, scope, kind, payload, **kwargs):
        self.store.calls.append(("enqueue", kind))
        return {"job_id": EID}
    def claim(self, worker_id, **kwargs):
        return {"job_id": kwargs["job_id"]}
    def start(self, claim, *, cursor):
        return claim
    def finish_local(self, claim, *, cursor):
        self.store.calls.append(("finish_local", claim["job_id"]))
        return claim


def make_service():
    repo, store = Repository(), Storage()
    values = {"RAFII_TREND_"+name+"_ENABLED": "1" for name in ("INTELLIGENCE", "RADAR", "TRUST_RECEIPTS", "STAGE_CLAIMS", "MODEL_ENRICHMENT", "OPPORTUNITY_LAB")}
    values["RAFII_TREND_WORKSPACE_ALLOWLIST"] = WID
    hosted = SimpleNamespace(repository=repo, connection_factory=repo.connection_factory, ideas=SimpleNamespace(_state=IdeasService._state, _member=IdeasService._member), commands=HostedPhase2Commands(clock=lambda: NOW))
    cw = CoworkerService(hosted, values=values, clock=lambda: NOW)
    cw._store_evidence = lambda *a: "fixture-evidence"
    svc = TrendService(cw, store_factory=lambda factory: store, cursor_secret=b"fixture-cursor-signing-key-32-byte!", jobs_factory=Jobs, platform_states_reader=lambda *a, **kw: {})
    cw._trends = svc
    metric = {"value": 10, "unit": "posts/hour", "definition_id": "mention_rate", "definition_version": "candidate-1", "window": {"start": opportunities.iso(NOW-3600), "end": opportunities.iso(NOW)}, "baseline_ref": None, "denominator": None, "null_reason": None}
    payload = {"canonical_topic": "Baking experiments", "observed": {"metrics": {"count": metric}, "timeline": []}, "calculated": {"mention_rate": metric}, "inferred": {"stage": "hot"},
               "coverage": {**coverage(scope=SCOPE), "availability": "available", "completeness": "partial"}, "trust_receipt_id": RID,
               "evidence": [{"id": EID, "platform": "bluesky", "language": "en", "excerpt": "We tested three bread recipes with different hydration levels.", "url": "https://example.test/post", "observed_at": opportunities.iso(NOW-100), "expires_at": END, "rights": grant(), "scope_key": SCOPE}]}
    store.rows["trend", TID] = fixture_row("trend", TID, payload)
    store.rows["receipt", RID] = fixture_row("receipt", RID, {"trend_id": TID, "method": {"id": "bundle", "version": "1", "formula": "count / hours", "calibration_cohort": None, "snapshot_refs": []}})
    fit = relevance.evaluate(payload, repo.state)
    op = opportunities.candidate({**payload, "id": TID, "expires_at": END}, fit, repo.state, WID, NOW,
                                angles=[{"id": "angle-1", "title": "Your own experiment", "contribution": "Compare results", "factual_requirements": ["Your real recipe and outcome"], "format_reason": "Explain the method"}], platform_targets=["bluesky"])
    op.update(id=OID, state="suggested")
    store.rows["opportunity", OID] = fixture_row("opportunity", OID, op)
    return svc, repo, store


def assert_schema(test, name, value):
    from jsonschema import Draft202012Validator, FormatChecker
    schema = json.loads((Path(__file__).parents[1]/"docs/design/social-trend-intelligence/api.schema.json").read_text())
    Draft202012Validator(schema["$defs"][name], format_checker=FormatChecker()).validate(value)


@contextmanager
def fixture_interpretation_read(store):
    """Isolate the SQL adapter in service unit tests; real SQL is tested separately."""
    from postriff_phase2.growth.trends import advanced_pipeline as A, interpretation_context as I
    def inputs(cur,wid,actor,tid,*,read_only=False):
        if not read_only:
            raise AssertionError('GET must not acquire edit dependency locks')
        trend=store.rows['trend',tid];receipt=store.rows['receipt',trend['payload']['trust_receipt_id']]
        return trend,receipt,{},{}
    with patch.object(A.AdvancedPipeline,'_load',side_effect=inputs), patch.object(I,'validate_current',return_value=True) as gate:
        yield gate


class TrendServiceTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.repo, self.store = make_service()
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def status(self, status, fn):
        with self.assertRaises(AlphaError) as raised:
            fn()
        self.assertEqual(raised.exception.status, status)

    def test_disabled_does_not_construct_store_or_require_migration(self):
        self.svc.values["RAFII_TREND_INTELLIGENCE_ENABLED"] = "0"
        self.svc.store_factory = lambda *_: self.fail("constructed disabled store")
        self.status(403, lambda: self.svc.list(WID, "session"))
        self.assertEqual(self.repo.queries, [])

    def test_authenticated_membership_and_viewer_read(self):
        self.status(401, lambda: self.svc.list(WID, ""))
        self.status(401, lambda: self.svc.list(WID, "bad"))
        self.status(404, lambda: self.svc.list(OTHER, "session"))
        self.repo.role = "viewer"
        self.assertEqual(len(self.svc.list(WID, "session")["data"]), 1)
        self.status(403, lambda: self.svc.watches(WID, "session", payload={}))

    def test_actual_schema_trend_list_receipt_opportunity(self):
        for schema, result in [("trends_response", self.svc.list(WID, "session")), ("trend_response", self.svc.get(WID, "session", TID)),
                               ("receipt_response", self.svc.get(WID, "session", TID, "receipts", RID)), ("opportunity_response", self.svc.opportunity(WID, "session", OID)),
                               ("opportunities_response", self.svc.list(WID, "session", kind="opportunity"))]:
            assert_schema(self, schema, result)
        self.assertIsNone(self.svc.get(WID, "session", TID)["data"]["inferred"]["stage"])

    def test_current_revocation_overrides_verified_projection_and_list(self):
        self.store.rows["receipt", RID].update(validity="revoked", verification_state="policy_revoked", payload=None)
        self.status(410, lambda: self.svc.get(WID, "session", TID))
        self.assertEqual(self.svc.list(WID, "session")["data"], [])

    def test_pending_cannot_publish_calculation_or_stage(self):
        self.store.rows["receipt", RID]["verification_state"] = "pending"
        data = self.svc.get(WID, "session", TID)["data"]
        self.assertEqual(data["calculated"], {})
        self.assertIsNone(data["inferred"]["stage"])
        self.assertTrue(data["observed"]["metrics"])

    def test_dna_profile_requires_current_receipt_and_qualified_interpretation(self):
        ids = ("momentum", "acceleration", "spread", "audience", "adaptability", "gap")
        profile = {
            "method_id": "trend-dna.fixture", "method_version": "1", "scale_ref": "fixture-scale-v1",
            "reference_population": "Fixture comparison population", "trust_receipt_id": RID,
            "expires_at": END, "limitations": ["Fixture geometry only"],
            "dimensions": [{"id": name, "state": "Moderate", "value": .5,
                "display_value": "Moderate fixture state",
                "layer": "interpretation" if name in ("audience", "adaptability") else "calculated",
                "definition": "Fixture display coordinate", "reason": "Receipt-bound fixture basis",
                "evidence_refs": [RID], "null_reason": None} for name in ids]}
        payload = self.store.rows["trend", TID]["payload"]
        payload.update(dna_profile=profile, interpretation_qualified=True)
        result = self.svc.get(WID, "session", TID)
        self.assertEqual(result["data"]["dna_profile"]["dimensions"][0]["value"], .5)
        payload["dna_profile"]["trust_receipt_id"] = OTHER
        self.assertNotIn("dna_profile", self.svc.get(WID, "session", TID)["data"])
        payload["dna_profile"]["trust_receipt_id"] = RID
        self.svc.values["RAFII_TREND_MODEL_ENRICHMENT_ENABLED"] = "0"
        self.assertNotIn("dna_profile", self.svc.get(WID, "session", TID)["data"])

    def test_display_and_model_rights_are_independent(self):
        row = self.store.rows["trend", TID]
        row["policy"]["llm_process"] = False
        self.status(403, lambda: self.svc.get(WID, "session", TID, model_visible=True))
        row["payload"]["evidence"][0]["rights"]["display_excerpt"]["state"] = "deny"
        row["payload"]["evidence"][0]["rights"]["display_link"]["state"] = "deny"
        evidence = self.svc.get(WID, "session", TID)["data"]["evidence"][0]
        self.assertEqual(set(evidence), {"id", "display_state", "reason"})

    def test_keyset_binds_filter_scope_actor_asof_and_signature(self):
        second = copy.deepcopy(self.store.rows["trend", TID]); second["object_id"] = OTHER
        self.store.rows["trend", OTHER] = second
        first = self.svc.list(WID, "session", {"limit": 1})
        cursor = first["next_cursor"]
        self.assertTrue(cursor)
        self.svc.list(WID, "session", {"limit": 1, "cursor": cursor})
        self.status(400, lambda: self.svc.list(WID, "session", {"limit": 1, "cursor": cursor, "query": "changed"}))
        self.status(400, lambda: self.svc.list(WID, "session", {"limit": 1, "cursor": "x" + cursor[1:]}))
        self.store.scope_epoch = "revoked-entitlement"
        self.status(400, lambda: self.svc.list(WID, "session", {"limit": 1, "cursor": cursor}))

    def test_ui_aliases_normalize_and_invalid_limits_refused(self):
        self.svc.list(WID, "session", {"view": "rising", "platform": "bluesky", "language": "en", "niche": "baking"})
        selected = next(c[2] for c in self.store.calls if c[0] == "list")
        self.assertEqual(selected["platforms"], ["bluesky"])
        self.assertEqual(selected["stages"], ["rising"])
        for query in ({"limit": 101}, {"unknown": "x"}, {"since": "2026-01-01"}, {"platform": "invalid"}):
            self.status(400, lambda: self.svc.list(WID, "session", query))

    def test_builder_is_wire_compatible_and_does_not_promote_shadow(self):
        metric = {"value": None, "unit": "posts/hour", "reason": "coverage_gap"}
        receipt = {"receipt_id": "receipt_digest", "observed": {"received_count": 3}, "calculated": {"mention_rate": metric, "current_window": {"start": opportunities.iso(NOW-3600), "end": opportunities.iso(NOW)}},
                   "inferred": {"candidate_stage": "hot"}, "coverage": coverage(scope=SCOPE), "snapshot_refs": ["snapshot_1"]}
        payload = build_trend_payload(receipt, trend_id=TID, episode_id=EID, scope_key=SCOPE, evidence=[], canonical_topic="Topic", expires_at=END, method_bundle=METHOD)
        self.store.rows["trend", TID]["payload"] = payload
        self.store.rows["receipt", RID]["payload"] = build_receipt_payload(receipt, trend_id=TID, method_bundle=METHOD)
        result = self.svc.get(WID, "session", TID, "receipts", RID)
        assert_schema(self, "receipt_response", result)
        self.assertIsNone(result["data"]["inferred"]["stage"])
        self.assertEqual(result["data"]["calculated"]["mention_rate"]["null_reason"], "coverage_gap")

    def test_historical_receipt_uses_its_frozen_snapshot_and_current_rights(self):
        historic = copy.deepcopy(self.store.rows["receipt", RID])
        historic["object_id"] = OTHER
        historic["payload"] = {**copy.deepcopy(self.store.rows["trend", TID]["payload"]),
                               **historic["payload"], "canonical_topic": "Historical topic", "trust_receipt_id": OTHER}
        historic["payload"]["calculated"]["mention_rate"]["value"] = 7
        self.store.rows["receipt", OTHER] = historic
        result = self.svc.get(WID, "session", TID, "receipts", OTHER)
        assert_schema(self, "receipt_response", result)
        self.assertEqual(result["data"]["canonical_topic"], "Historical topic")
        self.assertEqual(result["data"]["calculated"]["mention_rate"]["value"], 7)
        self.assertEqual(result["data"]["trust_receipt_id"], OTHER)
        historic.update(validity="revoked", payload=None)
        self.status(410, lambda: self.svc.get(WID, "session", TID, "receipts", OTHER))

    def test_model_tool_also_requires_independent_receipt_model_permission(self):
        self.store.rows["receipt", RID]["policy"]["llm_process"] = False
        self.status(403, lambda: self.svc.get(WID, "session", TID, model_visible=True))
        self.assertTrue(self.svc.get(WID, "session", TID)["data"]["observed"]["metrics"])


    def test_advanced_artifact_requires_current_verified_receipt_binding(self):
        self.svc.values["RAFII_TREND_GRAPH_GENOME_ENABLED"]="1"
        payload={"version":"fixture-v1","dimensions":[],"narrative_variants":[],"trust_receipt_id":RID,"_semantic_bindings":[],"_interpretation_bindings":{"fixture":"unit"}}
        self.store.rows["genome",TID]=fixture_row("genome",TID,payload,receipt_id=None)
        from postriff_phase2.growth.trends.advanced_pipeline import _method
        method=_method('genome')
        self.store.rows['genome',TID]['method_bundle']={'method_id':method['method_id'],'version':method['method_version']}
        with fixture_interpretation_read(self.store) as interpretation_guard:
            response=self.svc.get(WID,"session",TID,"genome")
            assert_schema(self,"genome_response",response)
            corrected=copy.deepcopy(self.store.rows["receipt",RID]);corrected["object_id"]=OTHER
            self.store.rows["receipt",OTHER]=corrected
            self.store.rows["trend",TID]["receipt_id"]=OTHER
            self.store.rows["trend",TID]["payload"]["trust_receipt_id"]=OTHER
            self.status(503,lambda:self.svc.get(WID,"session",TID,"genome"))
            payload["trust_receipt_id"]=OTHER
            self.assertEqual(self.svc.get(WID,"session",TID,"genome")["data"]["version"],"fixture-v1")
            self.store.rows["receipt",OTHER]["verification_state"]="pending"
            self.status(503,lambda:self.svc.get(WID,"session",TID,"genome"))

    def test_advanced_model_read_requires_artifacts_own_model_permission(self):
        self.svc.values["RAFII_TREND_GRAPH_GENOME_ENABLED"]="1"
        self.store.rows["genome",TID]=fixture_row("genome",TID,{"version":"v1","dimensions":[],"narrative_variants":[],"trust_receipt_id":RID})
        self.store.rows["genome",TID]["policy"]["llm_process"]=False
        self.status(403,lambda:self.svc.get(WID,"session",TID,"genome",model_visible=True))


    def test_related_platform_adapter_preserves_cutoff_expiry_and_independent_stages(self):
        inferred={"stage":"hot","data_state":"qualified","confidence":"high","calibration_state":"qualified","evidence_refs":[],"explanation":"fixture"}
        states=[{"platform":p,"coverage":coverage(scope=SCOPE),"inferred":inferred} for p in ("bluesky","youtube")]
        refs=[{"platform":p,"trend_id":tid,"trust_receipt_id":rid,"scope_key":SCOPE,"verification_state":"verified",
               "cohort_qualified":False,"method_state":"production"} for p,tid,rid in (("bluesky",TID,RID),("youtube",OID,EID))]
        response={"as_of":opportunities.iso(NOW),"expires_at":opportunities.iso(NOW+100),"snapshots":refs,"platform_states":states,
                  "limitations":["Lexical only; youtube snapshot receipt "+EID],"truncated":False}
        reader=unittest.mock.Mock(return_value=response);self.svc.platform_states_reader=reader
        value=self.svc.list(WID,"session");assert_schema(self,"trends_response",value)
        self.assertEqual(reader.call_args.kwargs["as_of"],value["as_of"])
        trend=value["data"][0];self.assertEqual([p["platform"] for p in trend["platform_states"]],["bluesky","youtube"])
        self.assertTrue(all(p["inferred"]["stage"] is None for p in trend["platform_states"]))
        self.assertIsNone(trend["inferred"]["stage"]);self.assertEqual(trend["expires_at"],opportunities.iso(NOW+100))
        self.assertIn(response["limitations"][0],trend["limitations"])
        reader.reset_mock()
        self.svc.get(WID,"session",TID,"receipts",RID)
        self.svc.get(WID,"session",TID,model_visible=True)
        reader.assert_not_called()
        refs[0]["trust_receipt_id"]=OTHER
        self.status(503,lambda:self.svc.get(WID,"session",TID))

    def test_related_primary_loss_is_not_rendered_from_previous_in_memory_row(self):
        from postriff_phase2.growth.trends.store import TrendStorageError
        self.svc.platform_states_reader=unittest.mock.Mock(side_effect=TrendStorageError("platform_primary_unavailable"))
        self.status(410,lambda:self.svc.get(WID,"session",TID))


class WhitespaceCurrentBoundary(unittest.TestCase):
    def test_review_artifacts_never_escape_and_read_never_refreshes(self):
        svc,repo,store=make_service();svc.values['RAFII_TREND_WHITESPACE_ENABLED']='1'
        from postriff_phase2.growth.trends import whitespace_admission as W
        store.rows['whitespace',TID]=fixture_row('whitespace',TID,{'schema_version':W.SCHEMA})
        store.rows['whitespace',OID]=fixture_row('whitespace',OID,{'schema_version':W.REVIEW_SCHEMA,'reviewed_by':ACTOR})
        wire={'schema_version':W.SCHEMA,'state':'review_required','workspace_id':WID,'trend_id':TID,
            'trust_receipt_id':RID,'context_digest':'a'*64,'facts_digest':'b'*64,'opportunities':[],
            'opportunity_refs':[],'rejected':[],'gaps':[],'claim_scope':'observed_comparison_sample',
            'semantic_qualification':'unqualified','expires_at':END,'truncated':False,'limitations':[],
            'source_decision_cutoff':opportunities.iso(NOW-10),'computed_at':opportunities.iso(NOW)}
        with patch.object(W.WhitespaceAdmission,'current_result',return_value=wire) as read, \
                patch.object(W.WhitespaceAdmission,'refresh',side_effect=AssertionError('GET wrote')):
            self.assertEqual(svc.stored(WID,'session','whitespace')['data'],[wire])
            read.assert_called_once()
            self.assertEqual(svc.get(WID,'session',TID,'whitespace')['data'],wire)
            read.return_value=None
            self.assertEqual(svc.stored(WID,'session','whitespace')['data'],[])
            with self.assertRaises(AlphaError):svc.get(WID,'session',TID,'whitespace')
        store.rows['whitespace',TID]['policy']['llm_process']=False
        with self.assertRaises(AlphaError):svc.stored(WID,'session','whitespace',TID,model_visible=True)

    def test_existing_accept_runs_current_whitespace_review_guard(self):
        svc,repo,store=make_service()
        from postriff_phase2.growth.trends import whitespace_admission as W
        with patch.object(W,'validate_opportunity',side_effect=contracts.ContractError('whitespace_dependency_changed')) as guard:
            with self.assertRaises(AlphaError):svc.accept(WID,'session',OID,{'revision':1,'angle_id':'angle-1',
                'channel_id':'channel-1','goal':'Explain','idempotency_key':'one'})
            self.assertTrue(guard.call_args.kwargs['mutation'])
            self.assertEqual(store.decisions,{})


class SemanticProducerReadGuard(unittest.TestCase):
    def test_unknown_producer_and_malformed_empty_markers_cannot_bypass_guard(self):
        svc,repo,store=make_service();svc.values['RAFII_TREND_GRAPH_GENOME_ENABLED']='1'
        from postriff_phase2.growth.trends.advanced_pipeline import _method
        method=_method('genome')
        payload={'version':'1','dimensions':[],'narrative_variants':[],'trust_receipt_id':RID,'_semantic_bindings':[],'_interpretation_bindings':{'fixture':'unit'}}
        saved=fixture_row('genome',TID,payload);store.rows['genome',TID]=saved
        with fixture_interpretation_read(store) as interpretation_guard:
            with self.assertRaises(AlphaError):svc.get(WID,'session',TID,'genome')
            saved['method_bundle']={'method_id':method['method_id'],'version':method['method_version']}
            self.assertEqual(svc.get(WID,'session',TID,'genome')['data']['dimensions'],[])
            for marker in ({},'',False,None):
                payload['_semantic_bindings']=marker
                with self.assertRaises(AlphaError):svc.get(WID,'session',TID,'genome')

    def test_interpretation_read_gate_failure_blocks_canonical_genome(self):
        svc,repo,store=make_service();svc.values['RAFII_TREND_GRAPH_GENOME_ENABLED']='1'
        from postriff_phase2.growth.trends.advanced_pipeline import _method
        method=_method('genome')
        payload={'version':'1','dimensions':[],'narrative_variants':[],'trust_receipt_id':RID,
            '_semantic_bindings':[],'_interpretation_bindings':{'fixture':'unit'}}
        saved=fixture_row('genome',TID,payload);store.rows['genome',TID]=saved
        saved['method_bundle']={'method_id':method['method_id'],'version':method['method_version']}
        with fixture_interpretation_read(store) as gate:
            gate.side_effect=contracts.ContractError('interpretation_read_artifact_changed')
            with self.assertRaises(AlphaError):svc.get(WID,'session',TID,'genome')
            self.assertEqual(gate.call_count,1)
            self.assertEqual(gate.call_args.kwargs['bindings'],payload['_interpretation_bindings'])
            self.assertEqual(gate.call_args.kwargs['now'],opportunities.iso(NOW))
