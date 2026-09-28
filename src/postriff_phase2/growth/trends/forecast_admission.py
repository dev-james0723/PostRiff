"""Authenticated durable forecast admission; no jobs, models or promotion writes.

All public inputs are exact stored projection references, never prediction data
or approval booleans. `admit` locks/rechecks/replays in the caller's transaction;
`persist` also attaches the complete DAG and writes one idempotent projection.
The caller must roll back its transaction on error and must not expose the
internal dependency list as a public forecast response.

Producer contract (all four projections in the requesting workspace):
* forecast_candidate: {schema_version:'trend.forecast.candidate.v1', prediction,
  source_bindings:[{source_id,scope_key,node_id}]}. prediction is the unmodified
  predict_candidates result, not its display wrapper.
* forecast_evaluation: {schema_version:'trend.forecast.evaluation.v1', report,
  source_bindings:[...]}. report is the unmodified rolling_origin_evaluate result.
  Either artifact may instead use prediction_ref/report_ref={manifest_id,
  document_digest}; the existing json-fragments-v1 manifest document is
  {artifact:<complete result>,manifest_digest:<digest excluding itself>} and
  must already be an ancestor of that projection. Large reports stay out of
  the 64KiB projection payload while retaining current retention checks.
  A document may additionally contain source_bindings (at most 1000 exact refs)
  only when root source_bindings_ref exactly matches prediction_ref/report_ref.
  Inline bindings and a bindings ref cannot coexist. Bindings are hydrated only
  in trusted memory; admission still abstains beyond its 996-source DAG limit.
* forecast_preregistration: {schema_version:'trend.forecast.preregistration.v1',
  plan:{all forecast.PREREGISTERED_FIELDS}, preregistration_digest, provenance}.
  Its durable available_at must be no later than the plan's preregistered_at,
  strictly before holdout_opened_at. It cannot be created retroactively.
* forecast_qualification: {schema_version:'trend.forecast.qualification.v1',
  candidate:{object_id,revision}, evaluation:{object_id,revision},
  preregistration:{object_id,revision}, prediction_digest, report_digest,
  dataset_digest, target_digest, method_digest, evaluation_plan_digest,
  preregistration_digest, provenance}. Review must depend on its three subjects.
  provenance={reviewer_id,authority,reviewed_at,decision:'approved',evidence_ref}.
  evidence_ref is an opaque review-record reference, not a URL to fetch.

Registry: 040 supports qualification='qualified', NOT a 'production' enum.
Every producer additionally needs config.forecast_admission with state=production,
role matching its kind suffix (candidate/evaluation/qualification/preregistration),
runtime_digest=runtime_digest(). Review/preregistration require review_authority
and reviewer_ids; evaluation requires evidence_class='retained_observed_data'
and allowed_access_methods. The output method needs the descriptor returned by
method_descriptor(). A separate operator workflow must approve/promote methods;
this module cannot do so. A stored fixture=False alone never grants admission.
"""
from __future__ import annotations

from copy import deepcopy
import inspect
import sys
import uuid as uuidlib

from . import config, context, contracts, forecast
from . import store as store_module
from .store import STORAGE_PERMISSION_SQL, TrendStorageError, bounded_json, row, rows, trust_lock
from .pipeline import decode_manifest

MAX_SOURCES = 996  # Four subject/review nodes + all sources fit 040's 1000 refs.
ROLES = ("candidate", "evaluation", "qualification", "preregistration")


def runtime_digest():
    return contracts.digest({**{m.__name__: inspect.getsource(m) for m in
                             (sys.modules[__name__], forecast, context, contracts, store_module)},
                             "manifest_decoder": inspect.getsource(decode_manifest)})


def method_descriptor():
    artifact = runtime_digest()
    return {"method_id": "trend.forecast.admission", "method_version": "admission-" + artifact[:16],
            "artifact_digest": artifact, "config": {"forecast_admission": {
                "state": "production", "role": "admission", "runtime_digest": artifact}}}


def _deny(code):
    raise TrendStorageError("forecast_admission_" + code)


def _ref(value, kind):
    if not isinstance(value, dict) or set(value) != {"object_id", "revision"}:
        _deny("exact_revision_required")
    if type(value["revision"]) is not int or value["revision"] < 1:
        _deny("exact_revision_required")
    return {"kind": kind, "object_id": contracts.uuid(value["object_id"]), "revision": value["revision"]}


def _bare(binding):
    return {k: binding[k] for k in ("object_id", "revision")}


def _node(record):
    return {"scope_key": record["scope_key"], "node_id": record["projection_id"]}


def _output_id(scope, binding):
    return str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, "trend.forecast.admission:" + scope + ":" + binding))


def _now(cur):
    cur.execute("/* forecast_admission:clock */ SELECT clock_timestamp() AS now")
    return row(cur)["now"]


class ForecastAdmission:
    def __init__(self, store, *, values=None):
        self.store, self.values = store, values

    def _enabled(self, workspace_id):
        if (not config.workspace_allowed(workspace_id, self.values)
                or not all(config.enabled(k, self.values) for k in ("INTELLIGENCE", "TRUST_RECEIPTS", "RADAR", "FORECASTS"))):
            _deny("disabled")

    def _load(self, cur, wid, actor, binding, now):
        found = self.store.get_projection(wid, actor, binding["kind"], binding["object_id"],
                                          revision=binding["revision"], as_of=now, cursor=cur)
        if (not found or found["scope_key"] != "workspace:" + wid or found["validity"] != "valid"
                or found["revision"] != binding["revision"] or not isinstance(found.get("payload"), dict)
                or any(found.get("policy", {}).get(p) is not True for p in ("derive_metrics", "retain_derivatives"))
                or contracts.instant(found["available_at"]) > contracts.instant(now)
                or contracts.instant(found["expires_at"]) <= contracts.instant(now)):
            _deny("projection_unavailable")
        role = binding["kind"].removeprefix("forecast_")
        bounded_json(found['payload'])
        if found["payload"].get("schema_version") != "trend.forecast." + role + ".v1":
            _deny("projection_schema")
        return found

    def _method(self, cur, bundle, role, artifact):
        cur.execute("""/* forecast_admission:method */ SELECT method_id,version,artifact_digest,config,qualification,revoked_at
            FROM public.pr_trend_method_versions WHERE method_id=%s AND version=%s FOR SHARE""",
                    (bundle["method_id"], bundle["version"]))
        saved = row(cur)
        control = saved.get("config", {}).get("forecast_admission", {}) if saved else {}
        if (not saved or saved["qualification"] != "qualified" or saved["revoked_at"] is not None
                or control.get("state") != "production" or control.get("role") != role
                or control.get("runtime_digest") != artifact):
            _deny("production_method_required")
        return saved, control

    def _hydrate(self, cur, record, key):
        payload = record["payload"]
        ref = payload.get(key + "_ref")
        if ref is None:
            if "source_bindings_ref" in payload:
                _deny("artifact_reference")
            return
        if key in payload or not isinstance(ref, dict) or set(ref) != {"manifest_id", "document_digest"}:
            _deny("artifact_reference")
        binding_ref = payload.get('source_bindings_ref')
        if 'source_bindings_ref' in payload and (binding_ref != ref or 'source_bindings' in payload):
            _deny('binding_reference')
        manifest_id = contracts.uuid(ref["manifest_id"])
        cur.execute("""/* forecast_admission:artifact_ancestry */ WITH RECURSIVE a(scope_key,node_id) AS (
            SELECT %s::text,%s::uuid UNION SELECT d.input_scope_key,d.input_node_id
            FROM public.pr_trend_dependencies d JOIN a USING(scope_key,node_id))
            SELECT EXISTS(SELECT 1 FROM a WHERE scope_key=%s AND node_id=%s) AS attached""",
                    (record["scope_key"], record["projection_id"], record["scope_key"], manifest_id))
        if not row(cur)["attached"]:
            _deny("artifact_dag_missing")
        saved = self.store.get_manifest(record["scope_key"], manifest_id, cursor=cur)
        if (saved["document_digest"] != ref["document_digest"] or len(saved["chunks"]) > 512
                or sum(len(contracts.canonical(c["payload"]).encode()) for c in saved["chunks"]) > 8_000_000):
            _deny("artifact_document")
        document = decode_manifest(saved)
        expected_keys = {'artifact','manifest_digest','source_bindings'} if binding_ref is not None else {'artifact','manifest_digest'}
        if set(document) != expected_keys or not isinstance(document["artifact"], dict):
            _deny("artifact_document")
        if binding_ref is not None:
            bindings=document['source_bindings']
            if not isinstance(bindings,list) or not 1<=len(bindings)<=1000:
                _deny('binding_document_bound')
            seen=set()
            for binding in bindings:
                if not isinstance(binding,dict) or set(binding)!={'source_id','scope_key','node_id'}:
                    _deny('binding_document')
                sid=contracts.uuid(binding['source_id']);s=contracts.scope(binding['scope_key'])
                if (sid!=contracts.uuid(binding['node_id']) or sid in seen
                        or (s!=record['scope_key'] and not s.startswith('shared:'))):
                    _deny('binding_document')
                seen.add(sid)
            payload['source_bindings']=deepcopy(bindings)
        payload[key] = document["artifact"]

    def _provenance(self, cur, wid, record, control, now):
        p = record["payload"].get("provenance", {})
        required = {"reviewer_id", "authority", "reviewed_at", "decision", "evidence_ref"}
        if (not isinstance(p, dict) or set(p) != required or p["decision"] != "approved"
                or not isinstance(p["authority"], str) or not p["authority"]
                or p["authority"] != control.get("review_authority")
                or p["reviewer_id"] not in control.get("reviewer_ids", [])
                or not isinstance(p["evidence_ref"], str) or not 1 <= len(p["evidence_ref"]) <= 256
                or not contracts.instant(p["reviewed_at"]) <= contracts.instant(record["available_at"]) <= contracts.instant(now)):
            _deny("review_provenance")
        # Registry-approved identity must still be an active workspace editor.
        self.store._actor(cur, wid, contracts.uuid(p["reviewer_id"]), write=True)
        return p

    def _ancestors(self, cur, records):
        cur.execute("""/* forecast_admission:ancestors */ WITH RECURSIVE a(root,scope_key,node_id) AS (
            SELECT n,s,n FROM unnest(%s::text[],%s::uuid[]) r(s,n) UNION
            SELECT a.root,d.input_scope_key,d.input_node_id FROM public.pr_trend_dependencies d JOIN a USING(scope_key,node_id))
            SELECT root::text,scope_key,node_id::text FROM a WHERE node_id=ANY(%s::uuid[])""",
                    ([r["scope_key"] for r in records], [r["projection_id"] for r in records],
                     [r["projection_id"] for r in records]))
        return {(r["root"], r["scope_key"], r["node_id"]) for r in rows(cur)}

    def _sources(self, cur, wid, actor, candidate, evaluation, controls, now, horizon_end):
        scope = "workspace:" + wid
        declared, root_sources = {}, {}
        for record, artifact_key in ((candidate, "prediction"), (evaluation, "report")):
            payload = record["payload"]
            artifact = payload.get(artifact_key, {})
            bindings = payload.get("source_bindings")
            if not isinstance(bindings, list) or not 1 <= len(bindings) <= MAX_SOURCES:
                _deny("source_bound")
            expected = set(artifact.get("evidence_refs", []))
            recipe = artifact.get("prediction_recipe" if artifact_key == "prediction" else "evaluation_recipe", {})
            for window in context.bounded(recipe.get("history", [])):
                expected.update(window.get("evidence_refs", []))
            own = {}
            for b in bindings:
                if not isinstance(b, dict) or set(b) != {"source_id", "scope_key", "node_id"}:
                    _deny("source_binding")
                sid = contracts.uuid(b["source_id"])
                if sid != contracts.uuid(b["node_id"]) or sid in own:
                    _deny("source_binding")
                own[sid] = {"scope_key": contracts.scope(b["scope_key"]), "node_id": sid}
                if sid in declared and declared[sid] != own[sid]:
                    _deny("source_binding")
            if set(own) != expected:
                _deny("source_binding")
            declared.update(own)
            root_sources[record["projection_id"]] = own
        if len(declared) > MAX_SOURCES:
            _deny("source_bound")
        cur.execute("""/* forecast_admission:receipts */ WITH RECURSIVE a(root,scope_key,node_id) AS (
            SELECT n,s,n FROM unnest(%s::text[],%s::uuid[]) r(s,n) UNION
            SELECT a.root,d.input_scope_key,d.input_node_id FROM public.pr_trend_dependencies d JOIN a USING(scope_key,node_id))
            SELECT a.root::text,r.receipt_id::text,r.verification_state FROM a JOIN public.pr_trend_trust_receipts r
            ON(r.scope_key,r.receipt_id)=(a.scope_key,a.node_id) LIMIT %s FOR SHARE OF r""",
                    ([candidate["scope_key"], evaluation["scope_key"]], list(root_sources), MAX_SOURCES*2+1))
        receipts = rows(cur)
        if (len(receipts) > MAX_SOURCES*2 or {r["root"] for r in receipts} != set(root_sources)
                or any(r["verification_state"] != "verified" for r in receipts)):
            _deny("verified_receipt_required")
        # Proof that evidence was already attached to each immutable artifact.
        cur.execute("""/* forecast_admission:source_ancestry */ WITH RECURSIVE a(root,scope_key,node_id) AS (
            SELECT n,s,n FROM unnest(%s::text[],%s::uuid[]) r(s,n) UNION
            SELECT a.root,d.input_scope_key,d.input_node_id FROM public.pr_trend_dependencies d JOIN a USING(scope_key,node_id))
            SELECT a.root::text,o.scope_key,o.observation_id::text AS node_id FROM a
            JOIN public.pr_trend_observations o ON(o.scope_key,o.observation_id)=(a.scope_key,a.node_id)
            LIMIT %s""", ([candidate["scope_key"], evaluation["scope_key"]], list(root_sources), MAX_SOURCES*2+1))
        actual = rows(cur)
        if len(actual) > MAX_SOURCES*2:
            _deny("source_bound")
        actual = {(r["root"], r["scope_key"], r["node_id"]) for r in actual}
        for root, bindings in root_sources.items():
            if not {(root, b["scope_key"], b["node_id"]) for b in bindings.values()} <= actual:
                _deny("source_dag_missing")
        allowed = set(self.store.authorized_scopes(wid, actor, cursor=cur))
        source_rows, dependencies, expiry = [], [], []
        access = controls.get("allowed_access_methods")
        if (controls.get("evidence_class") != "retained_observed_data" or not isinstance(access, list)
                or not access or len(access) > 32 or any(not isinstance(a, str) or not a for a in access)):
            _deny("observed_evidence_review_required")
        for sid, binding in sorted(declared.items()):
            source_scope = binding["scope_key"]
            if source_scope not in allowed or (source_scope != scope and not source_scope.startswith("shared:")):
                _deny("source_scope")
            if source_scope != scope:
                cur.execute("""/* forecast_admission:entitlement */ SELECT operations,expires_at,revoked_at
                    FROM public.pr_trend_entitlements WHERE workspace_id=%s AND scope_key=%s FOR SHARE""", (wid, source_scope))
                entitlement = row(cur)
                if (not entitlement or entitlement["revoked_at"] or not {"retrieve", "derive_metrics", "share_across_workspaces"} <= set(entitlement["operations"])
                        or contracts.instant(entitlement["expires_at"]) < contracts.instant(horizon_end)):
                    _deny("entitlement")
                expiry.append(entitlement["expires_at"])
            # No source text/URL/author data leaves this query.
            cur.execute(f"""/* forecast_admission:observation */ SELECT o.observation_id::text AS source_id,o.scope_key,
                o.provider_id,o.source_policy_version,o.provider_contract_version,o.rights,o.provenance,o.operation,o.purged_at,
                o.event_at,o.aggregate_end,o.available_at,o.retention_until,o.payload->>'platform' AS platform,
                (o.payload->>'is_repost'='false') AS original,{STORAGE_PERMISSION_SQL} AS storage_permission,
                postriff_private.trend_node_valid(o.scope_key,o.observation_id) AS valid
                FROM public.pr_trend_observations o WHERE o.scope_key=%s AND o.observation_id=%s FOR SHARE OF o""", (source_scope, sid))
            o = row(cur)
            method = o.get("provenance", {}).get("access_method", "") if o else ""
            if (not o or not o["valid"] or o["operation"] == "delete" or o["purged_at"] is not None
                    or not isinstance(method, str) or method not in access
                    or any(tag in method.lower() for tag in ("fixture", "synthetic", "simulation", "offline", "mock"))):
                _deny("observation_unavailable")
            operations = {"retrieve", "derive_metrics", "retain_derivatives", o["storage_permission"]}
            if len(declared) > 1:
                operations.add("cross_source_combine")
            if source_scope != scope:
                operations.add("share_across_workspaces")
            p, grant_expiry = None, []
            for permission in sorted(operations):
                p = self.store._policy(cur, source_scope, o["provider_id"], o["source_policy_version"], permission, at=now)
                if (permission not in p["operations"] or p["provider_contract_version"] != o["provider_contract_version"]
                        or not contracts.permits(o["rights"], permission, source_scope, now)):
                    _deny("source_rights")
                grant_expiry.extend(g[permission]["expires_at"] for g in (p["rights"], o["rights"]) if g[permission].get("expires_at"))
            expires = min([o["retention_until"], p["expires_at"], p["contract_end"]] + grant_expiry, key=contracts.instant)
            if contracts.instant(expires) < contracts.instant(horizon_end):
                _deny("source_retention")
            event = o["event_at"] or o["aggregate_end"]
            if not event or not o["platform"]:
                _deny("source_time_or_platform")
            # Mapping shared evidence into this workspace is permitted only by
            # the checked entitlement + explicit sharing grants above.
            source_rows.append({"source_id": sid, "scope_key": scope, "platform": o["platform"],
                "event_at": event, "available_at": max((o["available_at"], p["available_at"], p["contract_available_at"], p["valid_from"], p["contract_start"]), key=contracts.instant), "expires_at": expires,
                "original": o["original"] is True, "rights": {"analysis": True}})
            dependencies.append(binding); expiry.append(expires)
        return source_rows, dependencies, expiry

    def admit(self, workspace_id, actor_id, *, candidate, evaluation, review, cursor):
        if cursor is None:
            _deny("authenticated_transaction_required")
        wid, actor = contracts.uuid(workspace_id), contracts.uuid(actor_id)
        self._enabled(wid)
        if self.store.offline_replay:
            _deny("offline_store")
        cur = cursor
        trust_lock(cur)
        self.store._actor(cur, wid, actor, write=True)
        now = _now(cur)
        bindings = [_ref(candidate, "forecast_candidate"), _ref(evaluation, "forecast_evaluation"), _ref(review, "forecast_qualification")]
        records = [self._load(cur, wid, actor, b, now) for b in bindings]
        pre = _ref(records[2]["payload"].get("preregistration"), "forecast_preregistration")
        bindings.append(pre)
        self.store.lock_dependencies(wid, actor, bindings, cursor=cur)
        # Heads may have advanced while acquiring locks. Never use pre-lock payloads.
        records = [self._load(cur, wid, actor, b, now) for b in bindings]
        cand, evaluation_row, review_row, registration = records
        self._hydrate(cur, cand, "prediction")
        self._hydrate(cur, evaluation_row, "report")
        runtime = runtime_digest()
        controls, methods = [], []
        for record, role in zip(records, ROLES):
            method, control = self._method(cur, record["method_bundle"], role, runtime)
            methods.append(method); controls.append(control)
        descriptor = method_descriptor()
        output_method, _ = self._method(cur, {"method_id": descriptor["method_id"], "version": descriptor["method_version"]}, "admission", runtime)
        if output_method["artifact_digest"] != descriptor["artifact_digest"]:
            _deny("runtime_artifact")
        review_p = self._provenance(cur, wid, review_row, controls[2], now)
        self._provenance(cur, wid, registration, controls[3], now)
        cp, ep, rp, pp = (r["payload"] for r in records)
        prediction, report, plan = cp.get("prediction", {}), ep.get("report", {}), pp.get("plan", {})
        if (not all(isinstance(v, dict) for v in (prediction, report, plan))
                or set(plan) != set(forecast.PREREGISTERED_FIELDS) or rp.get("candidate") != _bare(bindings[0])
                or rp.get("evaluation") != _bare(bindings[1]) or rp.get("preregistration") != _bare(bindings[3])
                or prediction.get("scope_key") != "workspace:" + wid or report.get("scope_key") != "workspace:" + wid
                or prediction.get("fixture") is not False or report.get("fixture") is not False
                or prediction.get("method_bundle") != report.get("method_bundle")):
            _deny("artifact_binding")
        expected = {"prediction_digest": prediction.get("prediction_digest"), "report_digest": report.get("report_digest"),
            "dataset_digest": report.get("dataset_digest"), "target_digest": contracts.digest(prediction.get("target")),
            "method_digest": contracts.digest(prediction.get("method_bundle")),
            "evaluation_plan_digest": report.get("evaluation_plan_digest"),
            "preregistration_digest": forecast.preregistration_digest(plan)}
        if (any(rp.get(k) != v or not isinstance(v, str) or len(v) != 64 for k, v in expected.items())
                or pp.get("preregistration_digest") != expected["preregistration_digest"]
                or any(plan.get(k) != expected[k] for k in ("target_digest", "method_digest", "evaluation_plan_digest"))):
            _deny("review_binding")
        if (not contracts.instant(registration["available_at"]) <= contracts.instant(plan["preregistered_at"])
                < contracts.instant(plan["holdout_opened_at"])
                or any(contracts.instant(r["available_at"]) > contracts.instant(review_p["reviewed_at"]) for r in (cand, evaluation_row, registration))
                or contracts.instant(report["decision_cutoff"]) > contracts.instant(evaluation_row["available_at"])
                or contracts.instant(prediction["issued_at"]) > contracts.instant(cand["available_at"])):
            _deny("review_timing")
        ancestors = self._ancestors(cur, records)
        if any((review_row["projection_id"], r["scope_key"], r["projection_id"]) not in ancestors for r in (cand, evaluation_row, registration)):
            _deny("review_dag_missing")
        sources, refs, source_expiry = self._sources(cur, wid, actor, cand, evaluation_row, controls[1], now, prediction["horizon_end"])
        bundle = prediction["method_bundle"]
        gate = {**plan, **{k: expected[k] for k in ("dataset_digest", "report_digest", "preregistration_digest")},
                "reviewer": review_p["reviewer_id"], "operator_approved": True, "rights_verified": True, "reproducible": True}
        current = {"scope_key": "workspace:" + wid, "decision_cutoff": now, "target": prediction["target"],
            "sources": sources, "report": report, "gate": gate, "enabled": True,
            **{k: bundle[k] for k in ("seasonal_period", "trend_window", "embargo_hours")}}
        wire = forecast.to_stored_projection(prediction, qualification_payload=current)
        if wire["payload"]["state"] != "qualified":
            _deny("replay_or_qualification_failed")
        expiry = min([r["expires_at"] for r in records] + source_expiry + [prediction["horizon_end"]], key=contracts.instant)
        completed_at = _now(cur)
        if contracts.instant(expiry) <= contracts.instant(completed_at):
            _deny("expired_during_replay")
        self._enabled(wid)
        refs += [_node(r) for r in records]
        refs = sorted(refs, key=lambda r: (r["scope_key"], r["node_id"]))
        binding_digest = contracts.digest({"workspace_id": wid, "bindings": bindings, "artifacts": expected,
            "methods": [{k: m[k] for k in ("method_id", "version", "artifact_digest")} for m in methods], "runtime": runtime})
        payload = deepcopy(wire["payload"])
        payload["admission"] = {"schema_version": "trend.forecast.admission.v1", "binding_digest": binding_digest,
            "candidate": _bare(bindings[0]), "evaluation": _bare(bindings[1]), "review": _bare(bindings[2]),
            "preregistration": _bare(bindings[3]), "runtime_digest": runtime}
        return {"state": "qualified", "scope_key": "workspace:" + wid, "payload": payload,
            "dependencies": refs, "retention_until": expiry, "decision_cutoff": completed_at,
            "binding_digest": binding_digest, "method": descriptor}

    def persist(self, workspace_id, actor_id, *, candidate, evaluation, review, cursor):
        admitted = self.admit(workspace_id, actor_id, candidate=candidate, evaluation=evaluation, review=review, cursor=cursor)
        scope, binding = admitted["scope_key"], admitted["binding_digest"]
        object_id = _output_id(scope, binding)
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (scope + "|projection|forecast|" + object_id,))
        previous = self.store.get_projection(workspace_id, actor_id, "forecast", object_id, cursor=cursor)
        if previous:
            if (previous["validity"] != "valid" or previous["scope_key"] != scope or previous["revision"] != 1
                    or previous.get("method_bundle") != {"method_id": admitted["method"]["method_id"], "version": admitted["method"]["method_version"]}
                    or (previous.get("payload") or {}).get("admission", {}).get("binding_digest") != binding):
                _deny("idempotency_conflict")
            return {**previous, "payload": admitted["payload"]}
        manifest = self.store.put_manifest(scope, admitted["dependencies"], decision_cutoff=admitted["decision_cutoff"],
            available_at=admitted["decision_cutoff"], retention_until=admitted["retention_until"],
            recipe={"schema_version": "trend.forecast.admission.v1", "binding_digest": binding,
                    "runtime_digest": admitted["method"]["artifact_digest"]}, cursor=cursor)
        self.store.put_projection({"scope_key": scope, "kind": "forecast", "object_id": object_id, "revision": 1,
            "manifest_id": manifest["manifest_id"], "method_id": admitted["method"]["method_id"],
            "method_version": admitted["method"]["method_version"], "decision_cutoff": admitted["decision_cutoff"],
            "available_at": admitted["decision_cutoff"], "retention_until": admitted["retention_until"],
            "payload": admitted["payload"], "context_digest": binding}, expected_revision=0, cursor=cursor)
        return self.store.get_projection(workspace_id, actor_id, "forecast", object_id, revision=1, cursor=cursor)

    def read(self, workspace_id, actor_id, object_id, *, revision, cursor):
        """Service gate: registry downgrade/reviewer loss also closes reads.

        The general store validity check alone does not require production
        promotion. This method must precede exposing a stored qualified forecast.
        Like admit/persist it requires owner/editor: the canonical dependency
        lock is currently an authenticated mutation lock.
        """
        if cursor is None:
            _deny("authenticated_transaction_required")
        self._enabled(contracts.uuid(workspace_id))
        ref = _ref({"object_id": object_id, "revision": revision}, "forecast")
        saved = self.store.get_projection(workspace_id, actor_id, "forecast", ref["object_id"], revision=revision, cursor=cursor)
        if not saved or saved["scope_key"] != "workspace:" + workspace_id or saved["validity"] != "valid":
            _deny("projection_unavailable")
        marker = (saved.get("payload") or {}).get("admission", {})
        current = self.admit(workspace_id, actor_id, candidate=marker.get("candidate"), evaluation=marker.get("evaluation"),
                             review=marker.get("review"), cursor=cursor)
        if (marker.get("binding_digest") != current["binding_digest"] or revision != 1
                or saved.get("method_bundle") != {"method_id": current["method"]["method_id"], "version": current["method"]["method_version"]}
                or ref["object_id"] != _output_id(current["scope_key"], current["binding_digest"])):
            _deny("stored_binding_mismatch")
        # Return replayed numeric values, never an unverified cached payload.
        return {**saved, "payload": current["payload"]}
