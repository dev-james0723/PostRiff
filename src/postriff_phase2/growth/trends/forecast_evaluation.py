"""Operator-only durable rolling evaluation from current stored forecast histories.

ForecastEvaluation(store, values=...).evaluate(wid, actor, prereg_ref,
candidate_refs, cursor=authenticated_cursor) creates no jobs or approvals.
The output is always unqualified; review/admission remains a separate action.

In addition to forecast_admission's preregistration contract, the preregistration
payload must contain evaluation_plan with target, method_bundle, origins,
holdout_episode_ids, excluded_training_episode_ids, holdout_group_ids,
evaluation_cutoff and candidate_selection. Selection is either
{candidate_refs:[{object_id,revision}]} or
{slots:[{trend_id,target_start,target_digest,cohort,horizon_steps,bin_hours}]}; all declared slots must be present exactly
once. This permits planning before future opaque candidate IDs exist without
allowing an operator to supply arbitrary history. The plan's target, method and
origin/group split must match the preregistered digests. Candidate histories
merge only identical measurements/labels/source refs, retaining the earliest
proven availability and earliest expiry. Conflicting measurements fail closed.

The method_descriptor is a registration candidate, never a promotion. Its
registry row must already be qualified, with an explicit production release,
retained_observed_data evidence class and reviewed allowed_access_methods.
No request parameter can set fixture=False or provide sources/window values.
"""
from copy import deepcopy
import inspect
import sys
import uuid as uuidlib

from . import contracts, context, forecast, forecast_admission as admission
from .pipeline import encode_manifest
from .store import STORAGE_PERMISSION_SQL, TrendStorageError, bounded_json, row, rows, trust_lock

MAX_CANDIDATES = 32
MAX_SOURCES = 1000


def _deny(reason):
    raise TrendStorageError("forecast_evaluation_" + reason)


def runtime_digest():
    return contracts.digest({"evaluator": inspect.getsource(sys.modules[__name__]),
        "admission": admission.runtime_digest(), "manifest_encoder": inspect.getsource(encode_manifest)})


def method_descriptor(*, allowed_access_methods=()):
    artifact = runtime_digest()
    return {"method_id": "trend.forecast.evaluation", "method_version": "evaluation-" + artifact[:16],
        "artifact_digest": artifact, "config": {"forecast_admission": {"state": "production", "role": "evaluation",
            "runtime_digest": admission.runtime_digest(), "evidence_class": "retained_observed_data",
            "allowed_access_methods": list(allowed_access_methods)}}}


class ForecastEvaluation:
    def __init__(self, store, *, values=None):
        self.store = store
        self.admission = admission.ForecastAdmission(store, values=values)

    def _selection(self, plan, bindings, candidates):
        selection = plan["candidate_selection"]
        if not isinstance(selection, dict):
            _deny("candidate_selection")
        if set(selection) == {"candidate_refs"}:
            declared = context.bounded(selection["candidate_refs"], MAX_CANDIDATES)
            expected = [admission._ref(b, "forecast_candidate") for b in declared]
            expected_keys={(b['object_id'],b['revision']) for b in expected}
            actual_keys={(b['object_id'],b['revision']) for b in bindings}
            if not expected or len(expected_keys)!=len(expected) or not actual_keys<=expected_keys:
                _deny("candidate_selection")
            return {'missing_candidate_refs':[admission._bare(b) for b in expected if (b['object_id'],b['revision']) not in actual_keys]}
        elif set(selection) == {"slots"}:
            slots = context.bounded(selection["slots"], MAX_CANDIDATES)
            expected = []
            for s in slots:
                if not isinstance(s, dict) or set(s) != {"trend_id", "target_start", "target_digest", "cohort", "horizon_steps", "bin_hours"}:
                    _deny("candidate_selection")
                if (type(s['horizon_steps']) is not int or type(s['bin_hours']) not in (int,float)
                        or s['target_digest']!=contracts.digest(plan['target']) or any(s[k]!=plan['target'][k] for k in ('cohort','horizon_steps','bin_hours'))):
                    _deny('slot_target_binding')
                expected.append((contracts.uuid(s["trend_id"]), contracts.iso(contracts.instant(s["target_start"]))))
            actual = [(contracts.uuid(c["payload"].get("trend_id")),
                       contracts.iso(contracts.instant(c["payload"]["prediction"]["target_start"]))) for c in candidates]
            if not expected or len(set(expected)) != len(expected) or len(set(actual))!=len(actual) or not set(actual)<=set(expected):
                _deny("candidate_selection")
            return {'missing_slots':[deepcopy(s) for s,key in zip(slots,expected) if key not in set(actual)]}
        else:
            _deny("candidate_selection")

    def _history(self, candidates, plan):
        windows, declared, source_roots = {}, {}, {}
        for c in candidates:
            p = c["payload"].get("prediction", {})
            if (not isinstance(p, dict) or not forecast._intact(p, "prediction_digest")
                    or p.get("scope_key") != c["scope_key"] or p.get("target") != plan["target"]
                    or p.get("method_bundle") != plan["method_bundle"]
                    or contracts.instant(p["issued_at"]) > contracts.instant(c["available_at"])
                    or contracts.instant(c["available_at"]) > contracts.instant(plan["evaluation_cutoff"])):
                _deny("candidate_binding")
            history = context.bounded(p.get("prediction_recipe", {}).get("history", []))
            expected = set(p.get("evidence_refs", []))
            for window in history:
                expected.update(window.get("evidence_refs", []))
                key = (context.timestamp(window["window_start"]), context.timestamp(window["window_end"]))
                if key in windows:
                    prior=windows[key];timing={'available_at','expires_at'}
                    if contracts.digest({k:v for k,v in prior.items() if k not in timing})!=contracts.digest({k:v for k,v in window.items() if k not in timing}):
                        _deny("conflicting_history")
                    prior['available_at']=min(prior['available_at'],window['available_at'],key=contracts.instant)
                    ends=[r['expires_at'] for r in (prior,window) if r.get('expires_at')]
                    if ends:prior['expires_at']=min(ends,key=contracts.instant)
                else:windows[key] = deepcopy(window)
                if len(windows) > context.MAX_ROWS:
                    _deny("history_bound")
            bindings = context.bounded(c["payload"].get("source_bindings", []), MAX_SOURCES)
            own = {}
            for b in bindings:
                if not isinstance(b, dict) or set(b) != {"source_id", "scope_key", "node_id"}:
                    _deny("source_binding")
                sid = contracts.uuid(b["source_id"])
                ref = {"scope_key": contracts.scope(b["scope_key"]), "node_id": contracts.uuid(b["node_id"])}
                if sid != ref["node_id"] or sid in own or (sid in declared and declared[sid] != ref):
                    _deny("source_binding")
                own[sid] = ref
            if set(own) != expected:
                _deny("source_binding")
            source_roots[c["projection_id"]] = own
            declared.update(own)
        if len(declared) > MAX_SOURCES:
            _deny("source_bound")
        return [windows[k] for k in sorted(windows)], declared, source_roots

    def _sources(self, cur, wid, actor, candidates, declared, root_sources, control, now):
        scope = "workspace:" + wid
        cur.execute("""/* forecast_evaluation:ancestors */ WITH RECURSIVE a(root,scope_key,node_id) AS (
            SELECT n,s,n FROM unnest(%s::text[],%s::uuid[]) r(s,n) UNION
            SELECT a.root,d.input_scope_key,d.input_node_id FROM public.pr_trend_dependencies d JOIN a USING(scope_key,node_id))
            SELECT a.root::text,a.scope_key,a.node_id::text,o.observation_id::text,r.verification_state
            FROM a LEFT JOIN public.pr_trend_observations o ON(o.scope_key,o.observation_id)=(a.scope_key,a.node_id)
            LEFT JOIN public.pr_trend_trust_receipts r ON(r.scope_key,r.receipt_id)=(a.scope_key,a.node_id)
            WHERE o.observation_id IS NOT NULL OR r.receipt_id IS NOT NULL LIMIT %s""",
                    ([c["scope_key"] for c in candidates], list(root_sources), MAX_SOURCES*MAX_CANDIDATES+1))
        found = rows(cur)
        if len(found) > MAX_SOURCES*MAX_CANDIDATES:
            _deny("ancestor_bound")
        ancestry = {(r["root"],r["scope_key"],r["node_id"]) for r in found if r["observation_id"]}
        receipts = [r for r in found if r["verification_state"] is not None]
        if ({r["root"] for r in receipts} != set(root_sources) or any(r["verification_state"] != "verified" for r in receipts)):
            _deny("verified_receipts_required")
        receipt_refs=sorted({(r['scope_key'],r['node_id']) for r in receipts})
        cur.execute("""/* forecast_evaluation:receipt_lock */ SELECT r.scope_key,r.receipt_id::text,r.verification_state
            FROM unnest(%s::text[],%s::uuid[]) q(s,n) JOIN public.pr_trend_trust_receipts r
            ON(r.scope_key,r.receipt_id)=(q.s,q.n) ORDER BY r.scope_key,r.receipt_id FOR SHARE OF r""",
                    ([r[0] for r in receipt_refs],[r[1] for r in receipt_refs]))
        locked=rows(cur)
        if len(locked)!=len(receipt_refs) or any(r['verification_state']!='verified' for r in locked):_deny('verified_receipts_required')
        for root, refs in root_sources.items():
            if not {(root,r["scope_key"],r["node_id"]) for r in refs.values()} <= ancestry:
                _deny("source_dag_missing")
        allowed = set(self.store.authorized_scopes(wid, actor, cursor=cur))
        access = control.get("allowed_access_methods")
        if (control.get("evidence_class") != "retained_observed_data" or not isinstance(access, list)
                or not access or len(access)>32 or any(not isinstance(a,str) or not a for a in access)):
            _deny("observed_evidence_review_required")
        sources, expiry = [], []
        for sid, ref in sorted(declared.items()):
            s = ref["scope_key"]
            if s not in allowed or (s != scope and not s.startswith("shared:")):
                _deny("source_scope")
            if s != scope:
                cur.execute("""/* forecast_evaluation:entitlement */ SELECT operations,expires_at,revoked_at
                    FROM public.pr_trend_entitlements WHERE workspace_id=%s AND scope_key=%s FOR SHARE""", (wid,s))
                e=row(cur)
                if (not e or e['revoked_at'] or not {'retrieve','derive_metrics','share_across_workspaces'} <= set(e['operations'])
                        or contracts.instant(e['expires_at'])<=contracts.instant(now)):
                    _deny('entitlement')
                expiry.append(e['expires_at'])
            cur.execute(f"""/* forecast_evaluation:observation */ SELECT o.observation_id::text AS source_id,o.rights,o.provenance,
                o.provider_id,o.source_policy_version,o.provider_contract_version,o.operation,o.purged_at,o.event_at,o.aggregate_end,
                o.available_at,o.retention_until,o.payload->>'platform' AS platform,(o.payload->>'is_repost'='false') AS original,
                {STORAGE_PERMISSION_SQL} AS storage_permission,postriff_private.trend_node_valid(o.scope_key,o.observation_id) AS valid
                FROM public.pr_trend_observations o WHERE o.scope_key=%s AND o.observation_id=%s FOR SHARE OF o""",(s,sid))
            o=row(cur); access_method=o.get('provenance',{}).get('access_method','') if o else ''
            if (not o or not o['valid'] or o['operation']=='delete' or o['purged_at'] or access_method not in access
                    or any(t in access_method.lower() for t in ('fixture','synthetic','simulation','offline','mock'))):
                _deny('observation_unavailable')
            operations={'retrieve','derive_metrics','retain_derivatives',o['storage_permission']}
            if len(declared)>1: operations.add('cross_source_combine')
            if s!=scope: operations.add('share_across_workspaces')
            grant_expiry=[]
            for permission in sorted(operations):
                policy=self.store._policy(cur,s,o['provider_id'],o['source_policy_version'],permission,at=now)
                if (permission not in policy['operations'] or policy['provider_contract_version']!=o['provider_contract_version']
                        or not contracts.permits(o['rights'],permission,s,now)):
                    _deny('source_rights')
                grant_expiry.extend(g[permission]['expires_at'] for g in (policy['rights'],o['rights']))
            end=min([o['retention_until'],policy['expires_at'],policy['contract_end']]+grant_expiry,key=contracts.instant)
            event=o['event_at'] or o['aggregate_end']
            if not event or not o['platform'] or contracts.instant(end)<=contracts.instant(now):_deny('source_unavailable')
            sources.append({'source_id':sid,'scope_key':scope,'platform':o['platform'],'event_at':event,
                'available_at':max((o['available_at'],policy['available_at'],policy['contract_available_at'],policy['valid_from'],policy['contract_start']),key=contracts.instant),
                'expires_at':end,'original':o['original'] is True,'rights':{'analysis':True}})
            expiry.append(end)
        return sources,expiry

    def evaluate(self, workspace_id, actor_id, prereg_ref, candidate_refs, *, cursor):
        if cursor is None:_deny('authenticated_transaction_required')
        wid,actor=contracts.uuid(workspace_id),contracts.uuid(actor_id)
        self.admission._enabled(wid)
        if self.store.offline_replay:_deny('offline_store')
        cur=cursor;trust_lock(cur);self.store._actor(cur,wid,actor,write=True);now=admission._now(cur)
        pre_ref=admission._ref(prereg_ref,'forecast_preregistration')
        refs=[admission._ref(r,'forecast_candidate') for r in context.bounded(candidate_refs,MAX_CANDIDATES)]
        refs.sort(key=lambda b:(b['object_id'],b['revision']))
        if len({(r['object_id'],r['revision']) for r in refs})!=len(refs):_deny('candidate_bound')
        self.store.lock_dependencies(wid,actor,[pre_ref]+refs,cursor=cur)
        pre=self.admission._load(cur,wid,actor,pre_ref,now)
        candidates=[self.admission._load(cur,wid,actor,r,now) for r in refs]
        for c in candidates:self.admission._hydrate(cur,c,'prediction')
        _,pre_control=self.admission._method(cur,pre['method_bundle'],'preregistration',admission.runtime_digest())
        self.admission._provenance(cur,wid,pre,pre_control,now)
        for c in candidates:self.admission._method(cur,c['method_bundle'],'candidate',admission.runtime_digest())
        descriptor=method_descriptor()
        method,control=self.admission._method(cur,{'method_id':descriptor['method_id'],'version':descriptor['method_version']},'evaluation',admission.runtime_digest())
        if method['artifact_digest']!=descriptor['artifact_digest']:_deny('runtime_artifact')
        plan=pre['payload'].get('evaluation_plan');gate=pre['payload'].get('plan',{})
        keys={'target','method_bundle','origins','holdout_episode_ids','excluded_training_episode_ids','holdout_group_ids','evaluation_cutoff','candidate_selection'}
        if (not isinstance(plan,dict) or set(plan)!=keys or set(gate)!=set(forecast.PREREGISTERED_FIELDS)
                or pre['payload'].get('preregistration_digest')!=forecast.preregistration_digest(gate)):_deny('preregistration_plan')
        forecast._integer(gate['min_pairs'],2,1000);forecast._integer(gate['min_episodes'],2,1000)
        if not 0<=context.finite(gate['coverage_tolerance'])<.8:_deny('preregistration_plan')
        split={k:deepcopy(plan[k]) for k in ('target','method_bundle','origins','holdout_episode_ids','excluded_training_episode_ids','holdout_group_ids')}
        split['origins']=sorted(context.timestamp(o).isoformat() for o in context.bounded(split['origins'],1000))
        split['holdout_episode_ids']=sorted(set(split['holdout_episode_ids']))
        split['excluded_training_episode_ids']=sorted(set(split['excluded_training_episode_ids'])|set(split['holdout_episode_ids']))
        split['holdout_group_ids']=sorted(set(split['holdout_group_ids']))
        if (gate['evaluation_plan_digest']!=contracts.digest(split) or gate['target_digest']!=contracts.digest(plan['target'])
                or gate['method_digest']!=contracts.digest(plan['method_bundle'])
                or not contracts.instant(pre['available_at'])<=contracts.instant(gate['preregistered_at'])<contracts.instant(gate['holdout_opened_at'])
                or any(context.timestamp(o)<contracts.instant(gate['holdout_opened_at']) for o in split['origins'])):_deny('preregistration_binding')
        missing=self._selection(plan,refs,candidates)
        if any(missing.values()):
            return {'state':'insufficient_history','reason':'missing_preregistered_candidates',**missing,'forecast_wording_enabled':False}
        if contracts.instant(now)<contracts.instant(plan['evaluation_cutoff']):
            return {'state':'insufficient_history','reason':'evaluation_cutoff_not_reached','forecast_wording_enabled':False}
        history,declared,roots=self._history(candidates,plan)
        if not history or not declared:
            return {'state':'insufficient_history','reason':'no_retained_history','forecast_wording_enabled':False}
        if len(history)*len(split['origins'])>forecast.MAX_ROLLING_WORK:_deny('rolling_work_bound')
        sources,source_expiry=self._sources(cur,wid,actor,candidates,declared,roots,control,now)
        for c in candidates:
            prediction=c['payload']['prediction']
            replay=forecast.predict_candidates({**prediction['prediction_recipe'],'sources':sources})
            if replay['prediction_digest']!=prediction['prediction_digest']:_deny('candidate_replay_mismatch')
        bundle=plan['method_bundle']
        payload={'scope_key':'workspace:'+wid,'decision_cutoff':plan['evaluation_cutoff'],'target':plan['target'],
            'history':history,'sources':sources,'fixture':False,
            **{k:plan[k] for k in ('origins','holdout_episode_ids','excluded_training_episode_ids','holdout_group_ids')},
            **{k:bundle[k] for k in ('seasonal_period','trend_window','embargo_hours')}}
        report=forecast.rolling_origin_evaluate(payload)
        if report['evaluation_plan_digest']!=gate['evaluation_plan_digest']:_deny('executed_plan_mismatch')
        tables=[{r['prediction_id']:r for r in report['losses'].get(m,[])} for m in ('last_value','seasonal_naive',forecast.CANDIDATE)]
        shared=set.intersection(*(set(t) for t in tables));episodes={tables[-1][i]['episode_id'] for i in shared}
        enough=(len(shared)>=gate['min_pairs'] and len(episodes)>=gate['min_episodes'] and report['cohort_labels_explicit'])
        state='evaluated' if enough else 'insufficient_history'
        completed=admission._now(cur);expiry=min([r['expires_at'] for r in [pre]+candidates]+source_expiry,key=contracts.instant)
        if contracts.instant(expiry)<=contracts.instant(completed):_deny('expired_during_evaluation')
        self.admission._enabled(wid)
        identity=contracts.digest({'preregistration':pre_ref,'candidates':refs,'runtime':descriptor['artifact_digest']})
        oid=str(uuidlib.uuid5(uuidlib.NAMESPACE_URL,'trend.forecast.evaluation:'+wid+':'+identity))
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('workspace:'+wid+'|projection|forecast_evaluation|'+oid,))
        prior=self.store.get_projection(wid,actor,'forecast_evaluation',oid,cursor=cur)
        if prior:
            if (prior['validity']!='valid' or prior['revision']!=1 or prior['scope_key']!='workspace:'+wid
                    or prior['payload'].get('evaluation_identity')!=identity or prior['payload'].get('report_digest')!=report['report_digest']):_deny('idempotency_conflict')
            return prior
        document={'artifact':report,'source_bindings':[{'source_id':sid,**ref} for sid,ref in sorted(declared.items())]}
        document['manifest_digest']=contracts.digest(document)
        recipe,chunks=encode_manifest(document)
        # Every source was proven to be an ancestor of a selected candidate.
        # Retaining these exact candidate roots preserves all 1000 source edges
        # transitively without overflowing 040's direct-manifest input bound.
        dependencies=sorted([admission._node(r) for r in [pre]+candidates],key=lambda r:(r['scope_key'],r['node_id']))
        manifest_id=str(uuidlib.uuid4())
        wire={'schema_version':'trend.forecast.evaluation.v1','state':state,'qualification':'unqualified','forecast_wording_enabled':False,
            'report_ref':{'manifest_id':manifest_id,'document_digest':document['manifest_digest']},
            'source_bindings_ref':{'manifest_id':manifest_id,'document_digest':document['manifest_digest']},
            'report_digest':report['report_digest'],'dataset_digest':report['dataset_digest'],'evaluation_identity':identity,
            'preregistration':admission._bare(pre_ref),'candidate_refs':[admission._bare(r) for r in refs],
            'paired_count':len(shared),'episode_count':len(episodes),'censored_count':report['censored_count']}
        # Full artifacts are chunked, but binding metadata must still fit 040's
        # projection contract. Fail before any write; never trim evidence IDs.
        bounded_json(wire)
        sealed=self.store.put_manifest('workspace:'+wid,dependencies,decision_cutoff=completed,available_at=completed,
            retention_until=expiry,recipe=recipe,chunks=chunks,document_digest=document['manifest_digest'],manifest_id=manifest_id,cursor=cur)
        self.store.put_projection({'scope_key':'workspace:'+wid,'kind':'forecast_evaluation','object_id':oid,'revision':1,
            'manifest_id':sealed['manifest_id'],'method_id':descriptor['method_id'],'method_version':descriptor['method_version'],
            'decision_cutoff':completed,'available_at':completed,'retention_until':expiry,'payload':wire,'context_digest':identity},expected_revision=0,cursor=cur)
        return self.store.get_projection(wid,actor,'forecast_evaluation',oid,revision=1,cursor=cur)
