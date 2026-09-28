"""Advisory semantic pass over an existing authenticated, saved local Lab run.

The existing enrichment executor owns admission, one JEV attempt and independent
accounting. This module cannot edit a draft, approve, publish or qualify a cohort.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import uuid

from postriff_alpha.domain import AlphaError
from ...automation_runs import principal_repository
from ..judgments import JudgmentService
from ..questions import load, parse, estimate_tokens
from ..router import AIModelRouter
from . import config, contracts, enrichment, generation, opportunity_lab, opportunities, relevance
from .store import utcnow

TASK = "draft_diagnostic"
SCHEMA = "rafii.trend-lab-semantic.v1"
RUBRIC = Path(__file__).parents[1]/"question_sets/trend_draft_diagnostic.v1.json"


def fail(code):
    raise contracts.ContractError(code)


def spans(text):
    """Exact, bounded Unicode spans; no translation or invented snippets."""
    if not isinstance(text,str) or not text.strip() or len(text)>12000:fail("lab_draft_bound")
    return [{"start":i,"end":min(i+160,len(text)),"text":text[i:i+160]} for i in range(0,min(len(text),1920),160)]


def question_set(pack):
    raw=copy.deepcopy(load(RUBRIC).raw)
    raw.update(id="trend_lab_supported_diagnostic",version=1)
    raw["state_rules"] += " Every support answer must independently support that dimension. Unsure is complete. Never invent user facts, metrics, performance, calibration or authority."
    for dimension in opportunity_lab.DIAGNOSTICS:
        for suffix,rows in (("source",pack["evidence"]),("span",pack["draft_spans"])):
            raw["questions"][dimension+"_"+suffix]={"type":"choice","instructions":
                "For "+dimension+", select the exact native "+suffix+" that independently supports a specific assessment. Select unsure when evidence is insufficient; this answer does not see other answers.",
                "criteria":{**{"r"+str(i):("Observation "+r["observation_id"] if suffix=="source" else "Draft Unicode span "+str(r["start"])+":"+str(r["end"])) for i,r in enumerate(rows)},"unsure":"No specific permitted support"}}
    return parse(raw)


def comparable_history(outcomes, frame, cutoff):
    """Only explicit, identical native cohorts; no goal-text inference or zero fill."""
    keys=("account","provider","language","format","window","objective","definition","metric")
    if not isinstance(frame,dict) or any(not frame.get(k) for k in keys):
        return {"comparable":False,"observations":[],"reason":"explicit_comparison_frame_missing"}
    found=[];seen=set()
    for o in outcomes[:30]:
        if (o.get("state")!="measured" or any(o.get("cohort",{}).get(k)!=frame[k] for k in keys)
                or o.get("paid_promotion") is not False or o.get("job_id") in seen
                or any(type(o.get(k)) not in (int,float) or o[k]>cutoff for k in ("observed_at","available_at"))
                or not o.get("metric_receipts") or not o.get("publication",{}).get("published_at",cutoff+1)<cutoff):continue
        seen.add(o["job_id"])
        found.append({k:copy.deepcopy(o[k]) for k in ("job_id","value","cohort","metric_receipts","observed_at","available_at","features") if k in o})
    return {"comparable":len(found)>=3,"observations":found[:10],"frame":copy.deepcopy(frame),
            "reason":"same_explicit_cohort" if len(found)>=3 else "fewer_than_three_comparable_owned_posts","causal":False}


def diagnostics(judgment, pack, frozen):
    findings=[]
    for dimension in opportunity_lab.DIAGNOSTICS:
        answers=[judgment.answers.get(dimension+suffix) for suffix in ("","_source","_span")]
        valid=all(a and not a.abstained for a in answers)
        assessment=answers[0].value if valid else "unknown"
        src=span=None
        try:
            if valid:src=pack["evidence"][int(answers[1].value[1:])];span=pack["draft_spans"][int(answers[2].value[1:])]
        except (ValueError,IndexError,TypeError):valid=False;assessment="unknown"
        if assessment not in ("supported","concern","mixed"):assessment="unknown"
        reason="Unqualified semantic assessment of the selected native evidence and saved draft span."
        if dimension=="historical_similarity" and not pack["own_history"]["comparable"]:
            assessment="unknown";reason=pack["own_history"]["reason"]
        if dimension=="hook_crowding":
            assessment="unknown";reason="No measured hook-assignment denominator; semantic impressions cannot establish crowding."
        if dimension=="timing":
            assessment="unknown";reason="No qualified timing method; model judgments cannot qualify lifecycle or popularity."
        requires_fact=bool(span and opportunity_lab.PERSONAL_CLAIM.search(span["text"]) and not any(
            f["text"] in span["text"] for f in pack["workspace_context"]["approved_facts"]))
        edit=None
        # Reuse only an already-proven deterministic exact-copy deletion. Typed
        # evaluation cannot originate replacement prose or personal experience.
        if assessment=="concern" and dimension=="originality" and not requires_fact and src:
            for old in frozen.get("diagnostics",[]):
                proposed=old.get("suggested_edit")
                if (old.get("dimension")==dimension and src["observation_id"] in old.get("evidence_refs",[]) and proposed
                        and proposed.get("after")=="" and pack["draft"]["text"].count(proposed.get("before",""))==1):
                    edit=copy.deepcopy(proposed);break
        findings.append({"dimension":dimension,"assessment":assessment,
            "claim":("The evaluator marked this dimension "+assessment+" for the cited native sample and saved draft span.") if assessment!="unknown" else "",
            "evidence_refs":[src["observation_id"]] if src and assessment!="unknown" else [],
            "comparison_frame":"Frozen permitted sample; semantic qualification unavailable. "+(
                "Draft Unicode span "+str(span["start"])+":"+str(span["end"])+"." if span else ""),
            "uncertainty":reason,"requires_user_fact":requires_fact,"suggested_edit":edit})
    return findings


class TrendLabEnrichment(enrichment.TrendEnrichment):
    kind="trend.lab_enrichment"
    tasks=(TASK,)
    policy_key="model_lab"

    def enabled(self, workspace_id=None):
        return super().enabled(workspace_id) and config.enabled("OPPORTUNITY_LAB",self.values)

    def reviewed_config(self, policy, task, workspace_id):
        wrapped=copy.deepcopy(policy);value=wrapped["manifest"].get("model_lab")
        if not isinstance(value,dict):fail("lab_policy_review_required")
        history=value.pop("include_owned_history",False)
        if type(history) is not bool or value.get("tasks")!=[TASK]:fail("lab_policy_bounds")
        wrapped["manifest"]["model_enrichment"]=value
        cfg=enrichment.reviewed_config(wrapped,task,workspace_id)
        return {**cfg,"include_owned_history":history}

    def method_identity(self):
        artifact=contracts.digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),Path(enrichment.__file__),Path(generation.__file__),Path(opportunity_lab.__file__),RUBRIC)})
        return "trend.lab_enrichment","bounded-v1-"+artifact[:16],artifact

    def question_digest(self, task):
        return contracts.digest({"rubric":load(RUBRIC).raw,"semantic_schema":SCHEMA})

    def _context(self, state, *, reviewed=None):
        return generation.workspace_context(state,reviewed)

    def _history(self, cur, wid, actor, state, bound, draft, cfg, cutoff):
        empty={"comparable":False,"observations":[],"reason":"owned_history_not_admitted"}
        if not cfg["include_owned_history"]:return empty,[]
        from . import learning
        from .service import validate_stored_bindings
        choices=((state.get("coworker") or {}).get("trendLearning") or {}).get("metricChoices",[])
        selected=[c for c in choices[-100:] if c.get("confirmed") is True and c.get("selected_by")
            and c.get("selection_digest")==bound.get("selection_digest") and c.get("channel_id")==bound.get("channel_id")
            and c.get("provider")==str(draft["platform"]).lower() and c.get("window") in learning.WINDOWS
            and (learning._stamp(c.get("selected_at")) or cutoff+1)<=cutoff]
        if not selected:return {**empty,"reason":"explicit_comparison_frame_missing"},[]
        choice=max(selected,key=lambda c:(learning._stamp(c["selected_at"]),c.get("id","")))
        frame={"account":choice["channel_id"],"provider":choice["provider"],"language":bound.get("language"),
               "format":(draft.get("contentType") or {}).get("id"),"window":choice["window"],"objective":choice.get("objective"),
               "definition":choice.get("definition_version"),"metric":"/".join([choice["metric"]]+([choice["denominator_metric"]] if choice.get("denominator_metric") else []))}
        if any(not v for v in frame.values()):return {**empty,"reason":"explicit_comparison_frame_missing"},[]
        outcomes=[];deps=[]
        for job in ((state.get("phase2") or {}).get("jobs") or [])[-10:]:
            manifest=job.get("manifest") or {};bindings=manifest.get("trendLineage") or []
            if (len(bindings)!=1 or job.get("state")!="verified" or manifest.get("channelId")!=frame["account"]
                    or str(manifest.get("platform","")).lower()!=frame["provider"]):continue
            b=bindings[0]
            try:
                validate_stored_bindings(self.store.connection_factory,cur,wid,actor,state,bindings,cutoff,model_visible=True,store_factory=lambda _:self.store)
                outcome=learning._publication(cur,wid,state,b,b,job,cutoff,choice["window"])
                if comparable_history([outcome],frame,cutoff)["observations"]:
                    outcomes.append(outcome)
                    deps.extend(self.store.get_projection(wid,actor,kind,b[key],cursor=cur) for kind,key in
                        (("opportunity","opportunity_id"),("receipt","trust_receipt_id"),("trend","trend_id")))
            except (AlphaError,contracts.ContractError,KeyError,TypeError,ValueError):continue
        return comparable_history(outcomes,frame,cutoff),deps

    def _load(self, cur, workspace_id, actor_id, receipt_id, task, state):
        name,separator,run_id=task.partition(":")
        if name!=TASK or not separator:fail("lab_run_required")
        run_id=contracts.uuid(run_id)
        base=self.store.get_projection(workspace_id,actor_id,"lab_run",run_id,revision=1,cursor=cur)
        if (not base or base["validity"]!="valid" or base["scope_key"]!="workspace:"+workspace_id
                or base["policy"].get("llm_process") is not True):fail("lab_run_unavailable")
        frozen=base["payload"].get("frozen_run") or {}
        if frozen.get("state")!="completed" or frozen.get("execution_state")!="pure_deterministic" or frozen.get("trust_receipt_id")!=receipt_id:fail("lab_local_pass_required")
        loaded=super()._load(cur,workspace_id,actor_id,receipt_id,name,state)
        if any(r["policy"].get("display_excerpt") is not True for r in (base,loaded["receipt"],loaded["trend"])):fail("lab_display_rights_required")
        op=self.store.get_opportunity(workspace_id,actor_id,frozen["opportunity_id"],cursor=cur)
        if not op or op["validity"]!="valid" or op["revision"]!=frozen["opportunity_revision"] or op["policy"].get("llm_process") is not True:fail("lab_opportunity_changed")
        opportunities.check_current(op["payload"],state,opportunities.epoch(utcnow()),workspace_id=workspace_id)
        linked=[d for d in state.get("variants",[]) if any(b.get("opportunity_id")==op["object_id"] for b in d.get("trendLineage",[]))]
        if len(linked)!=1 or linked[0].get("id")!=frozen["draft_id"]:fail("lab_linkage_changed")
        draft=linked[0]
        if (not draft or draft.get("revision")!=frozen["draft_revision"] or contracts.digest(draft.get("text"))!=frozen["draft_digest"]
                or str(draft.get("platform","")).lower()!=frozen["target_platform"]
                or relevance.context_revision(state)!=frozen["context_revision"]):fail("lab_saved_inputs_changed")
        bindings=opportunities.lineage(state,[b.get("sourceId") for b in draft.get("trendLineage",[])])
        from .service import validate_stored_bindings
        validate_stored_bindings(self.store.connection_factory,cur,workspace_id,actor_id,state,draft.get("trendLineage",[]),opportunities.epoch(utcnow()),model_visible=True,store_factory=lambda _:self.store)
        bound=[b for b in bindings if b.get("opportunity_id")==op["object_id"] and b.get("trust_receipt_id")==receipt_id]
        if len(bound)!=1:fail("lab_saved_lineage_required")
        self.store.lock_dependencies(workspace_id,actor_id,[{"kind":"lab_run","object_id":run_id},{"kind":"opportunity","object_id":op["object_id"],"revision":op["revision"]}],cursor=cur)
        cur.execute("SELECT manifest_id FROM pr_trend_projections WHERE scope_key=%s AND kind='lab_run' AND object_id=%s AND revision=1",(base["scope_key"],run_id))
        manifest=self.store.get_manifest(base["scope_key"],str(cur.fetchone()[0]),cursor=cur)
        inputs=manifest["recipe"].get("inputs") or {}
        native={s["source_id"]:s.get("text") for s in inputs.get("sources",[]) if s.get("text")}
        pack=copy.deepcopy(loaded["pack"])
        pack["evidence"]=[e for e in pack["evidence"] if e["observation_id"] in native and native[e["observation_id"]]==e["text"]]
        if not pack["evidence"]:fail("lab_native_support_unavailable")
        history,deps=self._history(cur,workspace_id,actor_id,state,bound[0],draft,loaded["config"],opportunities.epoch(frozen["decision_cutoff"]))
        pack.update(draft={"id":draft["id"],"revision":draft["revision"],"text":draft["text"]},draft_spans=spans(draft["text"]),
            lab_run_id=run_id,opportunity={"id":op["object_id"],"revision":op["revision"],"selected_angle":bound[0]["angle"]},own_history=history)
        pack["lab_selection"]={"before":pack["selected_count"],"after":len(pack["evidence"]),"basis":"exact_native_support_from_frozen_local_run"}
        pack["selected_count"]=len(pack["evidence"])
        pack["input_digest"]=contracts.digest({k:v for k,v in pack.items() if k!="input_digest"})
        qs=question_set(pack)
        if estimate_tokens({"state":pack,"questions":qs.raw})>8000:fail("lab_pack_bound")
        identity=contracts.digest({"base":loaded["key"],"pack":pack["input_digest"],"question_digest":qs.digest,"run":run_id})
        loaded.update(pack=pack,key=identity,result_id=str(uuid.uuid5(uuid.UUID(workspace_id),identity)),question_digest=qs.digest,
            context_revision=contracts.digest({"context":loaded["context_revision"],"pack":pack["input_digest"]}),lab=base,opportunity=op,
            dependencies=list({(r["scope_key"],r["projection_id"]):r for r in [base,op,*deps]}.values()),expires_at=contracts.iso(min(contracts.instant(r["expires_at"]) for r in [base,op,*deps,loaded["receipt"],loaded["trend"]])))
        return loaded

    def execute(self, model, loaded, task, workspace_id, usage):
        router=AIModelRouter(jev=model,usage=usage,tasks={"trend."+TASK:("evaluate",loaded["config"]["model"],(),3.0,1000)})
        pack=loaded["pack"];qs=question_set(pack)
        judgment=JudgmentService(router.evaluator("trend."+TASK)).judge(qs,pack,subject=contracts.digest(pack),scope="personal:"+workspace_id,model=loaded["config"]["model"],workspace_id=workspace_id)
        return {"schema_version":SCHEMA,"status":judgment.status,"invalid":list(judgment.invalid),"executed_model":judgment.model,
            "task":"trend."+TASK,"evaluation_kind":"native_evaluation","calibration_state":"unqualified","interpretation_only":True,
            "domain_calibration_ref":None,"input_digest":pack["input_digest"],"run_id":loaded["lab"]["object_id"],
            "draft_id":pack["draft"]["id"],"draft_revision":pack["draft"]["revision"],"trust_receipt_id":loaded["receipt"]["object_id"],
            "diagnostics":diagnostics(judgment,pack,loaded["lab"]["payload"]["frozen_run"]),
            "own_history":{k:v for k,v in pack["own_history"].items() if k!="observations"},
            "native_support":[{"observation_id":e["observation_id"],"text":e["text"]} for e in pack["evidence"]]}

    def attach(self, cursor, workspace_id, actor_id, state, loaded, result, projection):
        base=loaded["lab"];current=self.store.get_projection(workspace_id,actor_id,"lab_run",base["object_id"],cursor=cursor)
        frozen={**base["payload"]["frozen_run"],"diagnostics":copy.deepcopy(result["diagnostics"]),"qualification":"unqualified",
            "execution_state":"bounded_native_evaluation","expires_at":projection["expires_at"]}
        wire=opportunity_lab.to_stored_projection(frozen)["payload"]
        refs=[{"scope_key":r["scope_key"],"node_id":r["projection_id"]} for r in [projection,*loaded["dependencies"]]]
        at=utcnow();manifest=self.store.put_manifest(base["scope_key"],refs,decision_cutoff=at,available_at=at,retention_until=projection["expires_at"],
            recipe={"model_result_id":projection["object_id"],"input_digest":loaded["pack"]["input_digest"]},cursor=cursor)
        self.store.put_projection({"scope_key":base["scope_key"],"kind":"lab_run","object_id":base["object_id"],"revision":current["revision"]+1,
            "manifest_id":manifest["manifest_id"],"method_id":loaded["method_id"],"method_version":loaded["method_version"],"decision_cutoff":at,
            "available_at":at,"retention_until":projection["expires_at"],"context_digest":relevance.context_revision(state),
            "draft_id":frozen["draft_id"],"draft_revision":frozen["draft_revision"],"payload":{**wire,"frozen_run":frozen,
                "request_digest":base["payload"]["request_digest"],"model_result_id":projection["object_id"],"semantic_input_digest":loaded["pack"]["input_digest"]}},
            expected_revision=current["revision"],cursor=cursor)

    def enqueue_run(self, workspace_id, actor_id, run_id, *, idempotency_key):
        if not self.enabled(workspace_id):return {"status":"disabled","provider_attempts":0}
        repository,capability=principal_repository(self.hosted,workspace_id,actor_id,"edit")
        with repository.transaction(capability,workspace_id) as (cur,row,actor):
            return self.enqueue_stored(cur,workspace_id,actor,run_id,row[1],idempotency_key=idempotency_key)

    def enqueue_stored(self, cursor, workspace_id, actor_id, run_id, state, *, idempotency_key):
        """Parent POST can queue after its cheap pass in the SAME authenticated tx."""
        if not self.enabled(workspace_id):return {"status":"disabled","provider_attempts":0}
        if not isinstance(idempotency_key,str) or not 1<=len(idempotency_key)<=200:fail("lab_idempotency_required")
        run=self.store.get_projection(workspace_id,actor_id,"lab_run",contracts.uuid(run_id),revision=1,cursor=cursor)
        if not run or run["validity"]!="valid":fail("lab_run_unavailable")
        task=TASK+":"+run_id;rid=run["payload"]["trust_receipt_id"]
        loaded=self._load(cursor,workspace_id,actor_id,rid,task,state)
        if self._cached(cursor,workspace_id,actor_id,loaded):return {"status":"cached","provider_attempts":0,"result_id":loaded["result_id"]}
        return self._enqueue_loaded(cursor,workspace_id,actor_id,rid,task,loaded,idempotency_key)

    def current_result(self, cursor, workspace_id, actor_id, run_id, state):
        """Stored-only parent read adapter; None suppresses stale semantic findings."""
        try:
            run=self.store.get_projection(workspace_id,actor_id,"lab_run",run_id,cursor=cursor)
            if not run or run["validity"]!="valid" or not run["payload"].get("model_result_id"):return None
            loaded=self._load(cursor,workspace_id,actor_id,run["payload"]["trust_receipt_id"],TASK+":"+run_id,state)
            result=self._cached(cursor,workspace_id,actor_id,loaded)
            return result if result and loaded["result_id"]==run["payload"]["model_result_id"] else None
        except (contracts.ContractError,AlphaError,KeyError,TypeError,ValueError):return None

    def plan_current(self, *, max_jobs=2, max_workspaces=2):
        # Lab is explicitly requested; never turn background trend discovery into
        # paid draft review. Parent POST calls enqueue_stored, cron only tick().
        return {"status":"explicit_lab_request_required" if self.enabled() else "disabled","queued":0,"provider_attempts":0}
