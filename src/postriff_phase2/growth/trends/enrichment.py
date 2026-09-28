"""Bounded, admitted model judgments over verified stored trend evidence.

No HTTP GET invokes this executor. Accounting commits before result attachment;
revocation can discard a judgment but cannot erase the external attempt's cost.
"""
from __future__ import annotations

import copy
from dataclasses import fields
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import time
import uuid

from postriff_alpha.domain import AlphaError
from ...automation_runs import principal_repository
from ...coworker import flags
from ..jev import JevService, EVALUATE_ENDPOINT, DEFAULT_MODEL
from ..router import AIModelRouter
from ..usage import MemoryUsageSink, UsageEvent
from ..questions import estimate_tokens, load
from . import config, contracts, evidence_pack, judge, judgment_cache, relevance
from .jobs import TrendJobs
from .policy import SourcePolicy
from .store import TrendStore, row, rows, utcnow

KIND = "trend.model_enrichment"
REQUIRED_FLAGS = ("INTELLIGENCE", "RADAR", "TRUST_RECEIPTS", "MODEL_ENRICHMENT")


def method_identity():
    paths = [Path(__file__), Path(evidence_pack.__file__), Path(judge.__file__), Path(judgment_cache.__file__),
             Path(__file__).parents[1]/"router.py", Path(__file__).parents[1]/"judgments.py", Path(__file__).parents[1]/"jev.py"]
    artifact = contracts.digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    return "trend.model_enrichment", "bounded-v1-"+artifact[:16], artifact


def reviewed_config(policy, task, workspace_id):
    p = policy["manifest"]
    value = p.get("model_enrichment")
    required = {"schema_version", "approved", "endpoint", "model", "tasks", "price_ref", "approved_attempt_cap_microusd",
                "max_attempts", "timeout_seconds", "max_evidence", "max_chars_per_evidence", "max_pack_tokens", "cache_ttl_seconds", "budget_keys"}
    if not isinstance(value, dict) or set(value) != required or not p.get("reviewed_by") or not p.get("review_ref"):
        raise contracts.ContractError("model_policy_review_required")
    if (value["schema_version"] != "1" or value["approved"] is not True or value["endpoint"] != EVALUATE_ENDPOINT
            or value["model"] != DEFAULT_MODEL or value["max_attempts"] != 1 or value["timeout_seconds"] != 3
            or value["max_evidence"] != 12 or value["max_chars_per_evidence"] != 800 or value["max_pack_tokens"] != 8000):
        raise contracts.ContractError("model_policy_bounds")
    if (not isinstance(value["tasks"], list) or task not in value["tasks"] or not set(value["tasks"]) <= set(judge.TASK_NAMES)
            or not isinstance(value["price_ref"], str) or not 1 <= len(value["price_ref"]) <= 256
            or type(value["approved_attempt_cap_microusd"]) is not int or not 0 < value["approved_attempt_cap_microusd"] <= 1_000_000
            or type(value["cache_ttl_seconds"]) is not int or not 1 <= value["cache_ttl_seconds"] <= 3600):
        raise contracts.ContractError("model_policy_bounds")
    keys = value["budget_keys"]
    if not isinstance(keys, list) or not 3 <= len(keys) <= 5 or any(not isinstance(k, str) or not 1 <= len(k) <= 160 for k in keys):
        raise contracts.ContractError("model_budget_keys_required")
    result = copy.deepcopy(value)
    result["budget_keys"] = [k.replace("{workspace_id}", workspace_id) for k in keys]
    if len(set(result["budget_keys"])) != len(keys) or any("{" in k or "}" in k for k in result["budget_keys"]):
        raise contracts.ContractError("model_budget_keys_required")
    return result


class TrendEnrichment:
    kind = KIND
    tasks = judge.TASK_NAMES
    policy_key = "model_enrichment"
    execution_kind = "native_evaluation"

    def reviewed_config(self, policy, task, workspace_id):
        return reviewed_config(policy, task, workspace_id)

    def method_identity(self):
        return method_identity()

    def question_digest(self, task):
        return load(Path(__file__).parents[1]/"question_sets"/("trend_"+task+".v1.json")).digest

    def execute(self, model, loaded, task, workspace_id, usage):
        router=AIModelRouter(jev=model,usage=usage,tasks={"trend."+task:("evaluate",loaded["config"]["model"],(),3.0,1000)})
        return judge.evaluate(router,task,loaded["pack"],workspace_id=workspace_id,authorized=True,
                              reserved_microusd=loaded["config"]["approved_attempt_cap_microusd"])

    def prepare_model(self, model, loaded):
        """Pure preflight before claim/reservation; no external attempt."""

    def attach(self, cursor, workspace_id, actor_id, state, loaded, result, projection):
        """Optional bounded domain attachment in the same fenced output transaction."""

    def __init__(self, hosted, *, store=None, values=None, jev_factory=None, monotonic=time.monotonic):
        self.hosted = hosted
        self.store = store or TrendStore(hosted.repository.connection_factory)
        self.jobs = TrendJobs(self.store)
        self.values = values
        self.jev_factory = jev_factory
        self.monotonic = monotonic
        self.worker_id = "trend-enrichment-"+str(uuid.uuid4())

    def enabled(self, workspace_id=None):
        return (all(config.enabled(name, self.values) for name in REQUIRED_FLAGS)
                and (workspace_id is None or config.workspace_allowed(workspace_id, self.values)))

    def _context(self, state, *, reviewed=None):
        hub = state.get("brandHub") or {}
        # Only an explicitly admitted workspace's own brief enters its private
        # evaluation pack; raw shared observation scopes are never rewritten.
        return {"revision": relevance.context_revision(state), "brand": {
            key: str(hub.get(key, ""))[:500] for key in ("purpose", "subject", "audience")}}

    def _load(self, cur, workspace_id, actor_id, receipt_id, task, state):
        if not self.enabled(workspace_id) or task not in self.tasks:
            raise contracts.ContractError("model_enrichment_disabled")
        self.store.authorized_scopes(workspace_id, actor_id, cursor=cur)
        receipt = self.store.get_receipt(workspace_id, actor_id, receipt_id, cursor=cur)
        if (not receipt or receipt["validity"] != "valid" or receipt["verification_state"] != "verified"
                or receipt["policy"].get("llm_process") is not True):
            raise contracts.ContractError("model_receipt_unavailable")
        if receipt["scope_key"].startswith("shared:"):
            cur.execute("""SELECT 1 FROM pr_trend_entitlements WHERE workspace_id=%s AND scope_key=%s
                AND revoked_at IS NULL AND expires_at>clock_timestamp() AND 'derive_metrics'=ANY(operations)
                AND 'share_across_workspaces'=ANY(operations) FOR SHARE""", (workspace_id, receipt["scope_key"]))
            if cur.fetchone() is None:
                raise contracts.ContractError("model_scope_entitlement_required")
        trend_id = contracts.uuid(receipt["payload"].get("trend_id"))
        self.store.lock_dependencies(workspace_id, actor_id, [{"kind": "receipt", "object_id": receipt_id, "revision": receipt["revision"]},
                                                           {"kind": "trend", "object_id": trend_id}], cursor=cur)
        trend = self.store.get_projection(workspace_id, actor_id, "trend", trend_id, cursor=cur)
        if (not trend or trend["validity"] != "valid" or trend["policy"].get("llm_process") is not True
                or (trend.get("receipt_id") or trend["payload"].get("trust_receipt_id")) != receipt_id):
            raise contracts.ContractError("model_receipt_superseded")
        cur.execute("SELECT manifest_id FROM pr_trend_projections WHERE scope_key=%s AND kind='receipt' AND object_id=%s AND revision=%s",
                    (receipt["scope_key"], receipt_id, receipt["revision"]))
        manifest_id = str(cur.fetchone()[0])
        stored = self.store.get_manifest(receipt["scope_key"], manifest_id, cursor=cur)
        from .pipeline import decode_manifest, representative_evidence
        manifest = decode_manifest(stored)
        if receipt["payload"].get("input_manifest_digest") != manifest["manifest_digest"]:
            raise contracts.ContractError("model_manifest_mismatch")
        at = utcnow(); source_scope = receipt["scope_key"]
        policies, reviewed, policy_rows = {}, None, {}
        native = manifest["source_revisions"]
        if not native or len(native) > 10000:
            raise contracts.ContractError("model_source_bound")
        for observation in native:
            if (observation["scope_key"] != source_scope or observation["operation"] == "delete"
                    or not contracts.permits(observation["rights"], "llm_process", source_scope, at)):
                raise contracts.ContractError("model_source_rights_denied")
            key = (source_scope, observation["provider_id"], observation["source_policy_version"])
            if key not in policy_rows:
                current = self.store._policy(cur, *key, permission="llm_process", at=at)
                limits = self.reviewed_config(current, task, workspace_id)
                if reviewed is not None and reviewed != limits:
                    raise contracts.ContractError("model_policy_conflict")
                reviewed = limits; policy_rows[key] = current
                names = {f.name for f in fields(SourcePolicy)}
                policy = SourcePolicy(**{k:v for k,v in current["manifest"].items() if k in names})
                if policy.version in policies and policies[policy.version] != policy:
                    raise contracts.ContractError("ambiguous_model_policy_binding")
                policies[policy.version] = policy
        candidate_ids = {item["id"] for item in representative_evidence(manifest, limit=12)}
        candidates = [o for o in native if o["observation_id"] in candidate_ids]
        context = self._context(state, reviewed=reviewed); cutoff = manifest["recipe"]["decision_cutoff"]
        pack = None
        while candidates:
            try:
                raw = evidence_pack.build(candidates, scope_key=source_scope, cutoff=cutoff, at=at, policies=policies,
                    receipt={"verification_state": "verified", "scope_key": source_scope, "digest": contracts.digest(receipt["payload"]),
                             "coverage": receipt["payload"].get("coverage", {})})
                raw.pop("input_digest")
                raw.update(scope_key="workspace:"+workspace_id, evidence_scope=source_scope, workspace_context=context,
                           input_manifest_digest=manifest["manifest_digest"], receipt_id=receipt_id)
                for evidence in raw["evidence"]:
                    evidence["source_scope_key"] = source_scope
                raw["input_digest"] = contracts.digest(raw)
                if raw["selected_count"] and estimate_tokens(raw) <= 8000:
                    pack = raw; break
            except contracts.ContractError as exc:
                if exc.code != "model_pack_token_limit": raise
            candidates.pop()
        if pack is None:
            raise contracts.ContractError("model_evidence_unavailable")
        method_id, version, artifact = self.method_identity()
        question_digest = self.question_digest(task)
        policy_digest = contracts.digest({"source_policies": [v["manifest"] for _,v in sorted(policy_rows.items())], "review": reviewed,
                                         "entitlements": self.store.scope_signature(workspace_id,actor_id,cursor=cur)})
        identity = judgment_cache.cache_identity(scope_key="workspace:"+workspace_id, input_digest=pack["input_digest"],
            source_revisions=[o["observation_id"]+":"+o["revision_identity"] for o in native], question_digest=question_digest,
            requested_model=reviewed["model"], policy_digest=policy_digest, context_revision=context["revision"], method_version=version)
        expires = min(contracts.instant(receipt["expires_at"]), contracts.instant(trend["expires_at"]),
                      *(contracts.instant(p["expires_at"]) for p in policy_rows.values()),
                      *(contracts.instant(p["rights"]["llm_process"]["expires_at"]) for p in policy_rows.values()),
                      *(contracts.instant(o["rights"]["llm_process"]["expires_at"]) for o in native))
        return {"pack": pack, "receipt": receipt, "trend": trend, "manifest_id": manifest_id, "context_revision": context["revision"],
                "policy_digest": policy_digest, "config": reviewed, "key": identity, "result_id": str(uuid.uuid5(uuid.UUID(workspace_id),identity)),
                "expires_at": contracts.iso(expires), "method_id": method_id, "method_version": version, "artifact": artifact,
                "question_digest": question_digest, "source_ids": [o["observation_id"] for o in native]}

    def _cached(self, cur, workspace_id, actor, loaded):
        cached = self.store.get_projection(workspace_id, actor, "model_judgment", loaded["result_id"], cursor=cur)
        if not cached or cached["validity"] != "valid": return None
        return judgment_cache.read(cached["payload"], at=utcnow(), scope_key="workspace:"+workspace_id,
            context_revision=loaded["context_revision"], policy_digest=loaded["policy_digest"], revoked_ids=[], membership_current=True)

    def enqueue(self, workspace_id, actor_id, receipt_id, task, *, idempotency_key):
        workspace_id, actor_id, receipt_id = map(contracts.uuid, (workspace_id,actor_id,receipt_id))
        if not self.enabled(workspace_id):
            return {"status": "disabled", "provider_attempts": 0}
        if not isinstance(idempotency_key,str) or not 1 <= len(idempotency_key) <= 200:
            raise contracts.ContractError("model_idempotency_required")
        repository, capability = principal_repository(self.hosted,workspace_id,actor_id,"edit")
        with repository.transaction(capability,workspace_id) as (cur,record,actor):
            state = json.loads(record[1]) if isinstance(record[1],str) else record[1]
            self.store.ensure_scope("workspace:"+workspace_id,cursor=cur)
            loaded = self._load(cur,workspace_id,actor,receipt_id,task,state)
            cached = self._cached(cur,workspace_id,actor,loaded)
            if cached: return {"status":"cached","result_id":loaded["result_id"],"provider_attempts":0}
            return self._enqueue_loaded(cur,workspace_id,actor,receipt_id,task,loaded,idempotency_key)

    def _enqueue_loaded(self, cur, workspace_id, actor, receipt_id, task, loaded, idempotency_key):
        scope = "workspace:"+workspace_id
        # The authenticated workspace row serializes this bound with other
        # producers, including explicit enqueue requests and cron retries.
        cur.execute("""SELECT job_id,state FROM pr_trend_jobs WHERE scope_key=%s AND kind=%s
            AND payload->>'cache_key'=%s AND state IN ('queued','leased','running') ORDER BY due_at LIMIT 1""",
                    (scope,self.kind,loaded["key"]))
        existing = cur.fetchone()
        if existing:
            return {"status":existing[1],"job_id":str(existing[0]),"result_id":loaded["result_id"],"existing":True,"provider_attempts":0}
        cur.execute("SELECT count(*) FROM pr_trend_jobs WHERE scope_key=%s AND kind=%s AND state IN ('queued','leased','running')",(scope,self.kind))
        if cur.fetchone()[0] >= 2:
            return {"status":"queue_full","provider_attempts":0}
        cur.execute("""SELECT dimension,cap_micro_usd-settled_micro_usd-reserved_micro_usd-unknown_micro_usd AS remaining,
            period_start<=clock_timestamp() AND period_end>clock_timestamp() AS active
            FROM pr_trend_budget_limits WHERE budget_key=ANY(%s)""",(loaded["config"]["budget_keys"],))
        budgets=cur.fetchall()
        if (len(budgets)!=len(loaded["config"]["budget_keys"]) or not {"system","provider","workspace"}<={b[0] for b in budgets}
                or any(not b[2] or b[1]<loaded["config"]["approved_attempt_cap_microusd"] for b in budgets)):
            return {"status":"budget_unavailable","provider_attempts":0}
        controls = {"workspace_id":workspace_id,"actor_id":actor,"receipt_id":receipt_id,"task":task,
                    "cache_key":loaded["key"],"result_id":loaded["result_id"],"context_revision":loaded["context_revision"],
                    "policy_digest":loaded["policy_digest"]}
        self.store.ensure_scope(scope,cursor=cur)
        key = "enrich:"+contracts.digest({"request":idempotency_key,"controls":controls})
        job = self.jobs.enqueue(scope,self.kind,controls,idempotency_key=key,max_attempts=1,cursor=cur)
        return {"status":job["state"],"job_id":job["job_id"],"result_id":loaded["result_id"],"provider_attempts":0}

    def plan_current(self, *, max_jobs=2, max_workspaces=2):
        """Local producer after receipt verification; zero model/provider calls.

        At most two current receipts per admitted workspace are examined, and
        at most two tasks are queued per tick or outstanding per workspace.
        Only tasks explicitly listed in every current source's reviewed policy
        are eligible. Terminal attempt identities never automatically retry.
        """
        if type(max_jobs) is not int or not 1 <= max_jobs <= 2 or type(max_workspaces) is not int or not 1 <= max_workspaces <= 2:
            raise contracts.ContractError("model_planner_bounds")
        result={"status":"disabled","queued":0,"existing":0,"cached":0,"unavailable":0,"provider_attempts":0}
        if not self.enabled(): return result
        result["status"]="stored_only"
        allowed=[contracts.uuid(w.strip()) for w in str(flags._source(self.values).get("RAFII_TREND_WORKSPACE_ALLOWLIST","")).split(",") if w.strip()]
        if not allowed:return result
        with self.store.transaction() as cur:
            cur.execute("""SELECT w.id::text,m.user_id::text FROM pr_workspaces w JOIN LATERAL
                (SELECT user_id FROM pr_memberships WHERE workspace_id=w.id AND status='active' AND role IN ('owner','editor')
                 ORDER BY (role='owner') DESC,user_id LIMIT 1) m ON true WHERE w.id=ANY(%s::uuid[])
                ORDER BY COALESCE((SELECT max(created_at) FROM pr_trend_jobs WHERE scope_key='workspace:'||w.id::text AND kind=%s),
                '-infinity'::timestamptz),w.id LIMIT %s""",(allowed,self.kind,max_workspaces))
            targets=cur.fetchall()
        from .pipeline import decode_manifest
        for wid,actor in targets:
            if result["queued"]>=max_jobs:break
            counts={"queued":0,"existing":0,"cached":0,"unavailable":0}
            try:
                repository,capability=principal_repository(self.hosted,wid,actor,"edit")
                with repository.transaction(capability,wid) as (cur,record,principal):
                    state=json.loads(record[1]) if isinstance(record[1],str) else record[1]
                    self.store.ensure_scope("workspace:"+wid,cursor=cur)
                    page=self.store.list_projections(wid,principal,kind="trend",limit=2,cursor=cur)
                    for trend in page["items"]:
                        if result["queued"]+counts["queued"]>=max_jobs:break
                        rid=trend.get("receipt_id") or (trend.get("payload") or {}).get("trust_receipt_id")
                        receipt=self.store.get_receipt(wid,principal,rid,cursor=cur) if rid else None
                        if not receipt or receipt["validity"]!="valid" or receipt["verification_state"]!="verified":continue
                        cur.execute("SELECT manifest_id FROM pr_trend_projections WHERE scope_key=%s AND kind='receipt' AND object_id=%s AND revision=%s",
                                    (receipt["scope_key"],rid,receipt["revision"]))
                        manifest=decode_manifest(self.store.get_manifest(receipt["scope_key"],str(cur.fetchone()[0]),cursor=cur))
                        if not manifest["source_revisions"]:continue
                        source=manifest["source_revisions"][0]
                        policy=self.store._policy(cur,source["scope_key"],source["provider_id"],source["source_policy_version"],permission="llm_process",at=utcnow())
                        tasks=policy["manifest"].get(self.policy_key,{}).get("tasks",[])
                        if not isinstance(tasks,list) or not set(tasks)<=set(self.tasks):continue
                        for task in sorted(set(tasks)):
                            if result["queued"]+counts["queued"]>=max_jobs:break
                            loaded=self._load(cur,wid,principal,rid,task,state)
                            if self._cached(cur,wid,principal,loaded):counts["cached"]+=1;continue
                            item=self._enqueue_loaded(cur,wid,principal,rid,task,loaded,"planner:"+loaded["key"])
                            if item["status"]=="queued" and not item.get("existing"):counts["queued"]+=1
                            elif item["status"]=="budget_unavailable":counts["unavailable"]+=1
                            elif item["status"]!="queue_full":counts["existing"]+=1
                for key,value in counts.items():result[key]+=value
            except (contracts.ContractError,AlphaError,KeyError,TypeError,ValueError):
                result["unavailable"]+=1
        return result

    def _model(self, reviewed):
        model = self.jev_factory(reviewed) if self.jev_factory else JevService(
            flags._source(self.values).get("AI_GATEWAY_API_KEY"),endpoint=reviewed["endpoint"],model=reviewed["model"])
        if model.endpoint != reviewed["endpoint"] or model.model != reviewed["model"]:
            raise contracts.ContractError("model_binding_mismatch")
        return model

    def _discard(self, claim, code, *, dispatched):
        try: self.jobs.fail(claim,code=code,retry_after_seconds=None,proven_unbilled=not dispatched)
        except contracts.ContractError: pass  # Expiry/revocation owns terminal cleanup.

    def tick(self, *, max_jobs=1, max_seconds=6):
        if type(max_jobs) is not int or not 1 <= max_jobs <= 2 or not 1 <= max_seconds <= 10:
            raise contracts.ContractError("model_worker_bounds")
        output = {"status":"disabled","provider_attempts":0,"attached":0,"cached":0,"discarded":0,"blocked":0}
        if not self.enabled(): return output
        output["status"] = "bounded"
        allowed=["workspace:"+contracts.uuid(w.strip()) for w in str(flags._source(self.values).get("RAFII_TREND_WORKSPACE_ALLOWLIST","")).split(",") if w.strip()]
        if not allowed:return output
        with self.store.transaction() as cur:
            cur.execute("SELECT * FROM pr_trend_jobs WHERE kind=%s AND scope_key=ANY(%s) AND state='queued' AND due_at<=clock_timestamp() AND NOT cancellation_requested ORDER BY due_at,job_id LIMIT %s", (self.kind,allowed,max_jobs*3))
            pending = rows(cur)
        started = self.monotonic()
        for pending_job in pending:
            if output["provider_attempts"] >= max_jobs or self.monotonic()-started+3 > max_seconds: break
            controls = pending_job["payload"]; claim = None; dispatched = False
            try:
                wid, actor, rid = (contracts.uuid(controls[k]) for k in ("workspace_id","actor_id","receipt_id"))
                if pending_job["scope_key"] != "workspace:"+wid: raise contracts.ContractError("model_job_scope_mismatch")
                repository, capability = principal_repository(self.hosted,wid,actor,"edit")
                with repository.transaction(capability,wid) as (cur,record,principal):
                    state = json.loads(record[1]) if isinstance(record[1],str) else record[1]
                    loaded = self._load(cur,wid,principal,rid,controls["task"],state)
                    if any(controls[k] != loaded[{"cache_key":"key"}.get(k,k)] for k in ("cache_key","context_revision","policy_digest","result_id")):
                        raise contracts.ContractError("model_job_snapshot_changed")
                    cached = self._cached(cur,wid,principal,loaded)
                    if cached:
                        claim=self.jobs.claim(self.worker_id,job_id=pending_job["job_id"],kind=self.kind,cursor=cur)
                        if claim: self.jobs.finish_local(claim,cursor=cur)
                        output["cached"] += 1; continue
                    cur.execute("""SELECT 1 FROM pr_trend_jobs WHERE scope_key=%s AND kind=%s
                        AND state IN ('leased','running') AND lease_until>clock_timestamp() AND payload->>'cache_key'=%s LIMIT 1""",
                                (pending_job["scope_key"],self.kind,loaded["key"]))
                    if cur.fetchone() is not None:
                        continue
                    model = self._model(loaded["config"])
                    self.prepare_model(model, loaded)
                    claim=self.jobs.claim(self.worker_id,job_id=pending_job["job_id"],kind=self.kind,lease_seconds=30,
                        budget_keys=loaded["config"]["budget_keys"],amount_micro_usd=loaded["config"]["approved_attempt_cap_microusd"],cursor=cur)
                    if not claim: continue
                    claim=self.jobs.start(claim,cursor=cur)
                # Recheck after claim commit: a wait to commit may have allowed
                # revocation/context changes. Release this transaction before I/O.
                with repository.transaction(capability,wid) as (cur,record,principal):
                    state=json.loads(record[1]) if isinstance(record[1],str) else record[1]
                    fresh=self._load(cur,wid,principal,rid,controls["task"],state)
                    if fresh["key"]!=loaded["key"]:raise contracts.ContractError("model_job_snapshot_changed")
                    loaded=fresh
                if not self.enabled(wid) or self.monotonic()-started+3 > max_seconds:
                    self._discard(claim,"model_dispatch_gate_or_deadline",dispatched=False)
                    output["blocked"]+=1;continue
                usage=MemoryUsageSink(); result=None; failure=None; dispatched=True
                output["provider_attempts"] += 1
                try:
                    result=self.execute(model,loaded,controls["task"],wid,usage)
                except Exception:
                    failure="model_evaluation_failed"
                if not usage.events:
                    usage.record(UsageEvent(task="trend."+controls["task"],model=loaded["config"]["model"],route="primary",
                        status="outcome_unknown",latency_ms=0,workspace_id=wid))
                # Mandatory independent COMMIT; output failures cannot erase usage.
                accounting=self.jobs.account_attempt(claim["scope_key"],claim["reservation_id"],usage.events[0])
                if (failure or len(usage.events)!=1 or accounting["actual_micro_usd"] is None or
                        accounting["actual_micro_usd"]>loaded["config"]["approved_attempt_cap_microusd"] or not result or
                        result.get("status")!="ok" or result.get("invalid") or result.get("executed_model")!=loaded["config"]["model"]):
                    self._discard(claim,failure or "model_result_or_cost_unavailable",dispatched=True)
                    output["discarded"] += 1; continue
                with repository.transaction(capability,wid) as (cur,record,principal):
                    state=json.loads(record[1]) if isinstance(record[1],str) else record[1]
                    current=self._load(cur,wid,principal,rid,controls["task"],state)
                    if current["key"]!=loaded["key"]: raise contracts.ContractError("model_job_snapshot_changed")
                    cached=self._cached(cur,wid,principal,current)
                    if not cached:
                        at=utcnow(); expiry=contracts.iso(min(contracts.instant(current["expires_at"]),contracts.instant(at)+timedelta(seconds=current["config"]["cache_ttl_seconds"])))
                        result.update(calibration_state="unqualified",domain_calibration_ref=None,interpretation_only=True)
                        payload=judgment_cache.envelope(current["key"],result,scope_key=claim["scope_key"],expires_at=expiry,
                            dependency_ids=current["source_ids"]+[rid],context_revision=current["context_revision"],policy_digest=current["policy_digest"])
                        refs=[{"scope_key":r["scope_key"],"node_id":r["projection_id"]} for r in (current["receipt"],current["trend"],*current.get("dependencies",[]))]
                        sealed=self.store.put_manifest(claim["scope_key"],refs,decision_cutoff=at,available_at=at,retention_until=expiry,
                            recipe={"input_digest":current["pack"]["input_digest"],"context_revision":current["context_revision"],"policy_digest":current["policy_digest"],
                                    "question_digest":current["question_digest"],"model":current["config"]["model"],"usage_event_id":str(accounting["usage_event_id"])},cursor=cur)
                        self.store.put_method(current["method_id"],current["method_version"],current["artifact"],{"semantic_qualification":"unqualified","execution":self.execution_kind},cursor=cur)
                        previous=self.store.get_projection(wid,principal,"model_judgment",current["result_id"],cursor=cur)
                        revision=previous["revision"]+1 if previous else 1
                        self.store.put_projection({"scope_key":claim["scope_key"],"kind":"model_judgment","object_id":current["result_id"],"revision":revision,
                            "manifest_id":sealed["manifest_id"],"method_id":current["method_id"],"method_version":current["method_version"],"decision_cutoff":at,
                            "available_at":at,"retention_until":expiry,"context_digest":current["context_revision"],"payload":payload},expected_revision=previous["revision"] if previous else None,cursor=cur)
                        projection=self.store.get_projection(wid,principal,"model_judgment",current["result_id"],cursor=cur)
                        self.attach(cur,wid,principal,state,current,result,projection)
                    self.jobs.finish_external(claim,actual_micro_usd=accounting["actual_micro_usd"],usage_event_id=accounting["usage_event_id"],cursor=cur)
                output["attached"] += 1
            except (contracts.ContractError,AlphaError,KeyError,TypeError,ValueError) as exc:
                if claim: self._discard(claim,"model_admission_or_attachment_failed",dispatched=dispatched)
                elif getattr(exc,"code",None) not in {"budget_exhausted","budget_period_inactive","budget_dimensions_required","workspace_budget_required"}:
                    # Retire invalid queued controls without racing a different
                    # worker's claim. A fresh context/policy creates a new key.
                    with self.store.transaction() as cur:
                        cur.execute("SELECT state FROM pr_trend_jobs WHERE scope_key=%s AND job_id=%s FOR UPDATE",
                                    (pending_job["scope_key"],pending_job["job_id"]))
                        status=cur.fetchone()
                        if status and status[0]=="queued":self.jobs.cancel(pending_job["scope_key"],pending_job["job_id"],cursor=cur)
                output["discarded" if dispatched else "blocked"] += 1
        return output
