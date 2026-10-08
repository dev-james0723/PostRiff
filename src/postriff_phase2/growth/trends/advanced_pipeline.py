"""Durable local advanced consumers. No provider, model, download or publishing I/O.

Parent hooks: AdvancedPipeline(store, values=...).enqueue(workspace_id, actor_id,
trend_id, kinds=(...)); .tick(limit=2) consumes only this module's typed jobs.
enqueue_from_receipts accepts the receipts list returned by TrendPipeline.consume.
All inputs are loaded from authenticated stored projections and sealed manifests.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import timedelta
import inspect
import json
import math
import time
import uuid

from . import config, context, contracts, copy_density, forecast, genome, graph, membership, metrics, narratives, narrative_periods, text_context, semantic_admission, semantic_saturation, semantic_graph, language_patterns, culture, interpretation_context
from .jobs import TrendJobs
from .pipeline import decode_manifest
from .store import TrendStorageError, row, rows, trust_lock, utcnow

KINDS = ("genome", "graph", "saturation", "creative_pattern", "forecast_candidate", "whitespace_candidate", "language_pattern")
FLAGS = {"genome": "GRAPH_GENOME", "graph": "GRAPH_GENOME", "saturation": "SATURATION",
         "creative_pattern": "GRAPH_GENOME", "forecast_candidate": "FORECASTS", "whitespace_candidate": "WHITESPACE", "language_pattern":"MODEL_ENRICHMENT"}
JOB_PREFIX = "trend.advanced.local."
SEMANTIC_KINDS = {'genome', 'graph', 'saturation'}
SCAN_PROVIDER = 'rafii.local.advanced'
SCAN_PARTITION = 'workspace-scan-v1'
MAX_SOURCES = 1000


def _id(scope, kind, value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, contracts.canonical(["advanced-local-v1", scope, kind, value])))


def _iso(value):
    return contracts.iso(contracts.instant(value))


def _method(kind):
    modules = {"genome": genome, "graph": graph, "saturation": copy_density,
               "creative_pattern": context, "forecast_candidate": forecast, "whitespace_candidate": text_context, "language_pattern":language_patterns}
    implementation = contracts.digest({"consumer": inspect.getsource(__import__(__name__, fromlist=["*"])),
        "builder": inspect.getsource(modules[kind]), "context": inspect.getsource(context),
        "metrics": inspect.getsource(metrics), "membership": inspect.getsource(membership),
        "text_context": inspect.getsource(text_context), "narratives": inspect.getsource(narratives),
        "narrative_periods": inspect.getsource(narrative_periods), "semantic_admission": inspect.getsource(semantic_admission),
        "culture":inspect.getsource(culture), "semantic_saturation":inspect.getsource(semantic_saturation),
        "semantic_graph":inspect.getsource(semantic_graph),
        "interpretation_context":interpretation_context.runtime_digest()})
    return {"method_id": "trend." + kind + ".local", "method_version": "candidate-" + implementation[:16],
            "artifact_digest": implementation}


def _fingerprint(manifest_digest, kind, artifact_digest, forecast_options, judgment_id, annotation_bindings=None, interpretation_bindings=None):
    return contracts.digest({"manifest_digest": manifest_digest, "kind": kind, "artifact_digest": artifact_digest,
        "forecast_options": forecast_options if kind == "forecast_candidate" else None,
        "judgment_id": judgment_id if kind == "genome" else None,
        "annotation_bindings": annotation_bindings if kind in SEMANTIC_KINDS else None,
        "interpretation_bindings": interpretation_bindings if kind == "genome" else None})


def build_inputs(manifest, *, now, current_policies, current_source_rights):
    """Adapt a VERIFIED sealed receipt manifest, with explicit per-source grants.

    This pure adapter never grants rights: both observation and policy must
    permit each operation at the receipt cutoff AND the current execution time.
    Current policy/source grants are separate authoritative inputs, never inferred
    from the historical seal or written back into it.
    The durable caller additionally checks current SQL policy/deletion closure.
    """
    cutoff = _iso(manifest["recipe"]["decision_cutoff"])
    now = _iso(now)
    if contracts.instant(cutoff) > contracts.instant(now):
        raise TrendStorageError("advanced_future_cutoff")
    scope = contracts.scope(manifest["scope_key"])
    originals = manifest["source_revisions"]
    if not isinstance(originals, list) or len(originals) > MAX_SOURCES:
        raise TrendStorageError("advanced_source_bound")
    if len(contracts.canonical(manifest).encode()) > 16_000_000:
        raise TrendStorageError("advanced_manifest_byte_bound")
    policies = manifest["policy_versions"]
    members = membership.resolve_memberships(manifest["membership_revisions"], cutoff,
                                             observations=originals, source_policies=policies)
    selected = {m["observation_id"] for m in members if m["episode_id"] == manifest["recipe"]["episode_id"]}
    specs = manifest["recipe"]["window_specs"]
    if not specs or len(specs) > 168:
        raise TrendStorageError("advanced_window_bound")
    spec = max(specs, key=lambda s: contracts.instant(s['end']))
    comparison = spec["comparison_scope"]
    sources, facts = [], {}
    for o in metrics.latest_revisions(originals, cutoff):
        p = o["payload"]
        if (o["observation_id"] not in selected or o["operation"] == "delete" or o["kind"] not in ("raw_post", "owned_post")
                or o["scope_key"] != scope or not o.get("event_at") or contracts.instant(o["event_at"]) > contracts.instant(cutoff)
                or contracts.instant(o["retention_until"]) <= contracts.instant(now)
                or o["coverage_epoch"] != comparison["coverage_epoch"]
                or o['provider_id'] != comparison['provider_id']
                or any(p.get(k, 'unknown' if k == 'community' else None) != comparison[k]
                       for k in ("platform", "language", "community"))):
            continue
        def permitted(permission):
            return (metrics.source_policy_allowed(o, policies, cutoff, permission)
                    and metrics.source_policy_allowed(o, current_policies, now, permission)
                    and contracts.permits(current_source_rights.get(o['observation_id'], {}), permission, scope, now))
        analysis = permitted("derive_metrics") and permitted("retain_derivatives")
        if not analysis:
            continue
        creative = permitted("store_raw")
        # raw_post is a representation, not affirmative evidence of originality.
        original = p.get("is_repost") is False and p.get("post_type") != "repost"
        source = {"source_id": o["observation_id"], "scope_key": scope, "platform": p["platform"],
            "language": p["language"], "event_at": o["event_at"], "available_at": o["available_at"],
            "expires_at": o["retention_until"], "original": original,
            "creator_key": o["provider_id"] + ":" + p["author_key"] if p.get("author_status") == "known" and p.get("author_key") else None,
            "rights": {"analysis": analysis, "creative": creative, "display": permitted("display_excerpt"),
                       "llm": permitted("llm_process"), "visual": False, "audio": False}}
        sources.append(source)
        # Facts stay in memory; job controls contain only opaque refs and digests.
        facts[o["observation_id"]] = {"provider_id": o["provider_id"], "source_identity": o["source_identity"],
            "access_method": o.get("provenance", {}).get("access_method"),
            "text": p.get("text") if creative and isinstance(p.get("text"), str) else None,
            "relations": deepcopy(p.get("relations", [])) if creative else []}
    expiry = min((s["expires_at"] for s in sources), key=contracts.instant, default=now)
    common = {"scope_key": scope, "decision_cutoff": cutoff, "sources": sources,
              "coverage": deepcopy(spec["coverage"])}
    frame = {"frame_id": metrics.comparison_digest(comparison), "platform": comparison["platform"],
        "language": comparison["language"], "window_start": spec["start"], "window_end": spec["end"],
        "acquisition_policy": comparison["sampling_method"], "classifier_version": "literal_text_structure_v1"}
    if not frame["frame_id"]:
        raise TrendStorageError("advanced_comparison_frame_required")
    return {"common": common, "facts": facts, "frame": frame, "expires_at": expiry,
            "history_windows": deepcopy(manifest.get("baseline_snapshots", []) + manifest["normalized_inputs"]["windows"]),
            "episode_id": manifest["recipe"]["episode_id"]}


def _support(inputs, refs):
    return {"evidence_refs": refs, "available_at": inputs["common"]["decision_cutoff"],
            "expires_at": inputs["expires_at"], "derivation_kind": "deterministic_extraction",
            "method_version": "literal_text_structure_v1", "confidence_basis": "direct source metadata; semantic interpretation unqualified"}


def local_text_patterns(inputs):
    items = []
    for source in inputs["common"]["sources"]:
        text = inputs["facts"][source["source_id"]]["text"]
        if text is None or not source["original"]:
            continue
        lines = text.splitlines() or [""]
        items.append({"source_id": source["source_id"], "text_digest": contracts.digest(text),
            "opening_digest": contracts.digest(lines[0]) if lines[0] else None,
            "character_count": len(text), "line_count": len(lines), "language": source["language"],
            **_support(inputs, [source["source_id"]])})
    return {"state": "available" if items else "unavailable", "items": items,
            "semantic_qualification": "unqualified", "modalities": {"visual": "unknown", "audio": "unknown", "ocr": "unknown"},
            "media_downloaded": False, "full_video_understanding": False}


def _genome_input(inputs):
    sources = [s for s in inputs["common"]["sources"] if s["rights"]["creative"]]
    refs = [s["source_id"] for s in sources]
    dimensions = {}
    if refs:
        languages = Counter(s["language"] for s in sources)
        platforms = sorted({s["platform"] for s in sources})
        dimensions["language_cultural_usage"] = {**_support(inputs, refs),
            "value": "Declared source language counts: " + ", ".join(f"{k}={v}" for k,v in sorted(languages.items())) + ". Cultural meaning is unknown."}
        dimensions["platform_timing"] = {**_support(inputs, refs),
            "value": "Observed sample on " + ", ".join(platforms) + "; first observed " + min(s["event_at"] for s in sources) + ". No timing recommendation or origin inference."}
    patterns = local_text_patterns(inputs)["items"]
    if patterns:
        dimensions["format_social_function"] = {**_support(inputs, [p["source_id"] for p in patterns]),
            "value": f"{len(patterns)} permitted text records; {sum(p['line_count'] > 1 for p in patterns)} contain multiple lines. Social function is unknown."}
    return {**inputs["common"], "dimensions": dimensions}


def _graph_input(inputs):
    nodes, edges, identities = {}, [], {}
    sources = {s["source_id"]: s for s in inputs["common"]["sources"] if s["rights"]["creative"]}
    for sid, source in sources.items():
        fact = inputs["facts"][sid]
        identities[(fact["provider_id"], fact["source_identity"])] = sid
        platform = "platform:" + source["platform"]
        nodes.setdefault(platform, {"node_id": platform, "node_type": "platform", "label": source["platform"],
                                   "scope_key": inputs["common"]["scope_key"], **_support(inputs, [sid])})
        if source.get("creator_key") and source["rights"]["display"]:
            identity = "creator:" + contracts.digest([source["platform"], source["creator_key"]])
            nodes.setdefault(identity, {"node_id": identity, "node_type": "creator", "label": "Platform-scoped creator",
                "platform": source["platform"], "creator_key": source["creator_key"],
                "scope_key": inputs["common"]["scope_key"], **_support(inputs, [sid])})
    for sid, source in sources.items():
        fact = inputs["facts"][sid]
        if not isinstance(fact["relations"], list) or len(fact["relations"]) > 20:
            raise TrendStorageError("advanced_relation_bound")
        for relation in fact["relations"]:
            target_id = identities.get((fact["provider_id"], relation.get("target")))
            target = sources.get(target_id)
            if relation.get("type") not in {"reply", "quote", "link"} or not target or not source.get("creator_key") or not target.get("creator_key"):
                continue
            a = "creator:" + contracts.digest([source["platform"], source["creator_key"]])
            b = "creator:" + contracts.digest([target["platform"], target["creator_key"]])
            if a not in nodes or b not in nodes:
                continue
            edges.append({"edge_id": contracts.digest([sid, target_id, relation["type"]]),
                "edge_type": relation["type"], "source_id": a, "target_id": b,
                "scope_key": inputs["common"]["scope_key"], "evidence_kind": "provider_relation",
                "event_start": min(source["event_at"], target["event_at"]), "event_end": max(source["event_at"], target["event_at"]),
                "uncertainty": "Provider-declared relation within this sample; no causal or origin claim.", **_support(inputs, [sid, target_id])})
    return {**inputs["common"], "nodes": list(nodes.values()), "edges": edges, "claims": []}


def _saturation_input(inputs):
    assignments, grouped = [], defaultdict(list)
    for item in local_text_patterns(inputs)["items"]:
        sid = item["source_id"]
        for dimension, pattern in (("hook", item["opening_digest"]), ("format", "multiline" if item["line_count"] > 1 else "single_line")):
            if pattern is None:
                continue
            assignments.append({"source_id": sid, "dimension": dimension, "pattern_id": pattern, **_support(inputs, [sid])})
            # Equality measures only. A shared structural class alone is NOT copying.
            group = item["opening_digest"] if dimension == "hook" else item["text_digest"]
            grouped[(dimension, group)].append(sid)
    copies = [{"dimension": d, "member_ids": ids, **_support(inputs, ids)} for (d, _), ids in grouped.items() if len(ids) > 1]
    return {**inputs["common"], "frame": inputs["frame"], "assignments": assignments, "copy_groups": copies,
        "copy_comparisons": {d:{"complete":True,"member_ids":sorted({a['source_id'] for a in assignments if a['dimension']==d}),
            **_support(inputs,sorted({a['source_id'] for a in assignments if a['dimension']==d}))} for d in ('hook','format')}}


def _interpretation_dimensions(value):
    """Translate already-admitted records without inventing a new qualification.

    All bounded hypotheses and conditional priors remain individually inspectable;
    their structured form, native support and review bindings stay in the seal.
    """
    fields=value['projection_fields']; spread=fields['spread']; dna=fields['platform_dna']
    hypotheses=spread.get('hypotheses',[])
    lines=[]; uncertainty=[]
    for h in hypotheses:
        lines.append('Hypothesis: '+h['mechanism'].replace('_',' ')+'. Alternatives: '+'; '.join(h['alternatives'])+'.')
        uncertainty.append(h['uncertainty']+' Contradictions: '+('; '.join(h['contradictions']) or 'None recorded')+'.')
    result=[{'dimension':'Why it may spread','finding':'\n'.join(lines) or None,
        'evidence_refs':sorted({ref for h in hypotheses for ref in h['evidence_refs']}),
        'uncertainty':' '.join(uncertainty) if hypotheses else 'No current reviewed explanation. Cause, origin and viewer psychology remain unknown.'}]
    lines=[]; uncertainty=[]; refs=set()
    for group,label in (('shared_priors','Shared hypothesis'),('private_adjustments','Your observed outcomes')):
        for p in dna.get(group,[]):
            cohort=', '.join(str(p[k]) for k in interpretation_context.COHORT_KEYS)
            lines.append(label+' ('+cohort+'; version '+p['prior_version']+'): '+p['finding'])
            uncertainty.append(p['uncertainty']);refs.update(p['evidence_refs'])
    caution='Conditional on the stated cohort and period; this is not a causal claim or a permanent voice change.'
    if dna.get('conflict'): caution+=' Shared and private findings disagree.'
    result.append({'dimension':'Platform patterns','finding':'\n'.join(lines) or None,'evidence_refs':sorted(refs),
        'uncertainty':(' '.join(uncertainty)+' '+caution) if lines else 'No current reviewed pattern for this exact platform, format, language, niche and period.'})
    return result


def build_projection(kind, inputs, *, now, forecast_options=None, semantic_dimensions=None, semantic=None, semantic_selected=None, interpretation=None):
    """Pure bounded builders. Semantic dimensions enter only after durable admission."""
    if kind == "genome":
        payload = _genome_input(inputs)
        payload["dimensions"].update(semantic_dimensions or {})
        if semantic_dimensions:
            payload["decision_cutoff"] = _iso(now)
        raw = genome.build_genome(payload); wire = genome.to_stored_projection(raw)["payload"]
        reconstructed, displayable_seeds = text_context.reconstruct(inputs)
        raw['context_and_seeds'] = reconstructed
        raw['period_membership'] = {period: narrative_periods.project(inputs, reconstructed, period=period)
                                    for period in ('day', 'week')}
        if semantic:
            raw['semantic_candidates'] = semantic['candidates']
            raw['period_membership'] = {period: narrative_periods.project(inputs, reconstructed, period=period,
                annotations=semantic['annotations'], semantic_qualified=bool(semantic['annotations']), at=now)
                for period in ('day','week')}
        if interpretation is not None:
            raw['interpretation_context'] = deepcopy(interpretation)
            wire['dimensions'].extend(_interpretation_dimensions(interpretation))
        wire['narrative_variants'] = ['Observed wording (meaning and stance unreviewed): ' +
            seed['original_spans'][0]['text'] for seed in displayable_seeds[:3]]
        for dimension in wire['dimensions']:
            if len(dimension['evidence_refs']) > 100:
                count = len(dimension['evidence_refs'])
                dimension['evidence_refs'] = dimension['evidence_refs'][:100]
                dimension['uncertainty'] += f' Displaying 100 of {count} evidence references; full support is in the bound manifest.'
    elif kind == "graph":
        base = _graph_input(inputs)
        reconstructed, _visible = text_context.reconstruct(inputs)
        meaning = semantic_graph.build_graph_input(inputs,reconstructed,semantic,now=now)
        # Preserve original provider relation edges. Both input sets have their
        # own stable namespaces; no identity or causal edge is manufactured.
        graph_input = {**base,'sources':meaning['sources'],'decision_cutoff':meaning['decision_cutoff'],
            'source_decision_cutoff':meaning['source_decision_cutoff'],
            'nodes':base['nodes']+meaning['nodes'],'edges':base['edges']+meaning['edges']}
        raw = graph.project_graph(graph_input)
        raw['source_decision_cutoff'] = inputs['common']['decision_cutoff']
        raw['truncated'] = raw.get('truncated',False) or meaning['truncated']
        raw['semantic_support'] = meaning  # Full typed node/edge support remains sealed and inspectable.
        wire = graph.to_stored_projection(raw)["payload"]
        wire['nodes'] = wire['nodes'][:40]
        nodes = {n['id'] for n in wire['nodes']}
        wire['edges'] = [e for e in wire['edges'] if e['from'] in nodes and e['to'] in nodes][:80]
        wire['truncated'] = raw.get('truncated',False) or len(wire['nodes']) != len(raw['nodes']) or len(wire['edges']) != len(raw['edges'])
    elif kind == "saturation":
        measurement = _saturation_input(inputs)
        interpreted = semantic_saturation.build_assignments(inputs,semantic_selected or [],now=now,adapted=semantic)
        measurement['assignments'].extend(interpreted['assignments'])
        measurement['decision_cutoff'] = interpreted['decision_cutoff']
        raw = copy_density.measure_saturation(measurement)
        raw['source_decision_cutoff'] = interpreted['source_decision_cutoff']
        raw['semantic_assignment_support'] = interpreted
        wire = copy_density.to_stored_projection(raw)["payload"]
        for d in wire["dimensions"]:
            d['uncertainty'] += (' Topic/narrative prevalence uses current reviewed native-language annotations; '
                'semantic copying is unassessed. Hook/format copying uses exact retained text equality. No fatigue claim.')
    elif kind == "creative_pattern":
        raw = local_text_patterns(inputs)
        wire = {**raw, 'items': raw['items'][:20], 'total_items': len(raw['items']),
                'truncated': len(raw['items']) > 20}
    elif kind == "whitespace_candidate":
        raw = text_context.question_candidates(inputs)
        wire = {**raw, 'candidates': [{**c, 'evidence_refs': c['evidence_refs'][:20],
                    'evidence_count': len(c['evidence_refs'])} for c in raw['candidates'][:20]]}
        wire['truncated'] = raw['truncated'] or len(raw['candidates']) > 20
    elif kind == 'language_pattern':
        raw = language_patterns.project(inputs)
        wire = {'patterns':language_patterns.wire(raw),'derivation_kind':'deterministic_extraction',
                'semantic_qualification':'lexical_only','method_version':language_patterns.VERSION}
    elif kind == "forecast_candidate":
        options = {"horizon_steps": 1, "bin_hours": 1, "embargo_hours": 0, "seasonal_period": 24, **(forecast_options or {})}
        if set(options) != {"horizon_steps", "bin_hours", "embargo_hours", "seasonal_period"}:
            raise TrendStorageError("advanced_forecast_options")
        bin_seconds = context.finite(options["bin_hours"], minimum=0.001)*3600
        issued = contracts.instant(now)
        target_start = issued + timedelta(seconds=(math.ceil(issued.timestamp()/bin_seconds)*bin_seconds-issued.timestamp()))
        target = {"population": "observed_sample", "frame_id": inputs["frame"]["frame_id"],
            "cohort": inputs["frame"]["platform"] + ":" + inputs["frame"]["language"], "metric_definition": "qualifying_original_count",
            "horizon_steps": options["horizon_steps"], "bin_hours": options["bin_hours"],
            "supported_horizon_hours": max(0,(contracts.instant(inputs["expires_at"])-target_start).total_seconds()/3600)}
        history, seen = [], set()
        source_ids = {s["source_id"] for s in inputs["common"]["sources"]}
        for w in inputs["history_windows"]:
            key = (w["window_start"], w["window_end"])
            if key in seen or w.get("comparison_digest") != target["frame_id"]:
                continue
            seen.add(key)
            refs = [r["observation_id"] for r in w["source_revision_refs"]]
            if not refs or not set(refs) <= source_ids:
                continue
            history.append({"frame_id": target["frame_id"], "metric_definition": target["metric_definition"],
                "cohort": target["cohort"],
                "window_start": w["window_start"], "window_end": w["window_end"],
                # A window ending is not proof its observations were known then.
                # These values were sealed at the receipt's knowledge cutoff.
                "available_at": inputs['common']['decision_cutoff'], "expires_at": inputs["expires_at"], "episode_id": inputs["episode_id"],
                "evidence_refs": refs, "complete": w["data_state"] == "qualified", "coverage": "stable" if w["coverage"].get("completeness") == "complete_within_scope" else "unknown",
                "value": w["observed"]["qualifying_original_count"]})
        raw = forecast.predict_candidates({**inputs["common"], "decision_cutoff": _iso(now), "target_start": contracts.iso(target_start),
            "target": target, "history": history, "embargo_hours": options["embargo_hours"], "seasonal_period": options["seasonal_period"],
            "fixture": not bool(inputs["facts"]) or any(f.get("access_method") not in
                {"official_public_stream", "official_instance_public_timeline", "existing_public_web_research"}
                for f in inputs["facts"].values())})
        # The sealed pure result is immutable. Runtime provenance belongs outside
        # its prediction digest; never rewrite execution_state after sealing.
        wire = {k: v for k, v in raw.items() if k != "prediction_recipe"}
        wire.update(state="candidate", execution_kind="local_computation", forecast_wording_enabled=False, qualification="unqualified")
    else:
        raise TrendStorageError("advanced_kind_unsupported")
    return {"payload": wire, "details": raw}


class AdvancedPipeline:
    def __init__(self, store, *, values=None, clock=utcnow):
        self.store, self.values, self.clock = store, values, clock
        self.jobs = TrendJobs(store)

    def _enabled(self, workspace_id, kind):
        return (kind in KINDS and config.workspace_allowed(workspace_id, self.values)
                and all(config.enabled(n, self.values) for n in ("RADAR", "TRUST_RECEIPTS", FLAGS[kind])))

    def _load(self, cur, workspace_id, actor_id, trend_id, *, read_only=False):
        trust_lock(cur)
        now = _iso(self.clock())
        trend = self.store.get_projection(workspace_id, actor_id, "trend", contracts.uuid(trend_id), as_of=now, cursor=cur)
        if not trend or trend["validity"] != "valid" or trend["verification_state"] != "verified":
            raise TrendStorageError("advanced_trend_unverified")
        receipt_id = trend.get("receipt_id") or trend["payload"].get("trust_receipt_id")
        receipt = self.store.get_projection(workspace_id, actor_id, "receipt", contracts.uuid(receipt_id), as_of=now, cursor=cur)
        if (not receipt or receipt["scope_key"] != trend["scope_key"] or receipt["validity"] != "valid"
                or receipt["verification_state"] != "verified" or receipt["payload"].get("trend_id") != trend_id):
            raise TrendStorageError("advanced_receipt_unverified")
        refs = [{"kind": r["kind"], "object_id": r["object_id"], "revision": r["revision"]} for r in (trend, receipt)]
        if not read_only:
            self.store.lock_dependencies(workspace_id, actor_id, refs, cursor=cur)
        cur.execute("SELECT manifest_id::text FROM public.pr_trend_projections WHERE scope_key=%s AND projection_id=%s", (receipt["scope_key"], receipt["projection_id"]))
        found = cur.fetchone()
        if not found:
            raise TrendStorageError("advanced_receipt_manifest_missing")
        saved = self.store.get_manifest(receipt["scope_key"], found[0], cursor=cur)
        manifest = decode_manifest(saved)
        if receipt["payload"].get("input_manifest_digest") != manifest["manifest_digest"]:
            raise TrendStorageError("advanced_receipt_manifest_mismatch")
        # Derivative permission alone does not grant fresh access to retained
        # source text. Re-read each operation's current grants under this tx.
        current_policies = []
        for provider, version in sorted({(o['provider_id'],o['source_policy_version']) for o in manifest['source_revisions']}):
            policy = self.store._policy(cur, trend['scope_key'], provider, version, 'derive_metrics', at=now)
            grants = deepcopy(policy['rights'])
            for operation, grant in grants.items():
                if operation not in policy['contract_operations']:
                    grant['state'] = 'unknown'
            current_policies.append({**policy['manifest'], 'scope_key': trend['scope_key'], 'provider_id': provider,
                'version': version, 'rights': grants, 'effective_at': policy['valid_from'], 'expires_at': policy['expires_at'],
                'readiness': policy['readiness'], 'revoked_at': policy['revoked_at']})
        cur.execute('SELECT observation_id::text,rights FROM public.pr_trend_observations WHERE scope_key=%s AND observation_id=ANY(%s::uuid[]) FOR SHARE',
                    (trend['scope_key'],[o['observation_id'] for o in manifest['source_revisions']]))
        source_rights = dict(cur.fetchall())
        inputs = build_inputs(manifest, now=now, current_policies=current_policies, current_source_rights=source_rights)
        if not inputs["common"]["sources"]:
            raise TrendStorageError("advanced_sources_unavailable")
        inputs["expires_at"] = min([inputs["expires_at"], trend["expires_at"], receipt["expires_at"]], key=contracts.instant)
        if contracts.instant(inputs["expires_at"]) <= contracts.instant(now):
            raise TrendStorageError("advanced_inputs_expired")
        return trend, receipt, manifest, inputs

    def enqueue(self, workspace_id, actor_id, trend_id, *, kinds=("genome", "graph", "saturation", "creative_pattern"),
                forecast_options=None, judgment_id=None, cursor=None):
        workspace_id, actor_id, trend_id = map(contracts.uuid, (workspace_id, actor_id, trend_id))
        if (not isinstance(kinds, (list, tuple)) or not kinds or len(kinds) > len(KINDS)
                or any(k not in KINDS for k in kinds) or len(set(kinds)) != len(kinds)):
            raise TrendStorageError("advanced_kind_bound")
        admitted = [k for k in dict.fromkeys(kinds) if self._enabled(workspace_id, k)]
        if not admitted:
            return {"state": "disabled", "jobs": []}
        with self.store.transaction(cursor) as cur:
            trend, receipt, manifest, inputs = self._load(cur, workspace_id, actor_id, trend_id)
            # Derived workspace/model context must never enter a shared projection.
            output_scope = 'workspace:' + workspace_id
            self.store.ensure_scope(output_scope, cursor=cur)
            annotations, annotation_bindings, _refs = self._annotations(cur, workspace_id, actor_id, receipt['object_id'], inputs) if SEMANTIC_KINDS.intersection(admitted) else ([], [], [])
            interpretation = self._interpretation(cur,workspace_id,actor_id,receipt['object_id'],inputs) if 'genome' in admitted else None
            result = []
            for kind in admitted:
                method = _method(kind)
                frozen_annotations = annotation_bindings if kind in SEMANTIC_KINDS else None
                frozen_interpretation = interpretation['bindings'] if kind == 'genome' else None
                fingerprint = _fingerprint(manifest["manifest_digest"], kind, method["artifact_digest"], forecast_options, judgment_id, frozen_annotations, frozen_interpretation)
                control = {"workspace_id": workspace_id, "actor_id": actor_id, "trend_id": trend_id,
                    "trend_revision": trend["revision"], "receipt_id": receipt["object_id"], "receipt_revision": receipt["revision"],
                    "input_manifest_digest": manifest["manifest_digest"], "input_digest": fingerprint, "artifact_kind": kind,
                    "artifact_digest": method["artifact_digest"], "forecast_options": forecast_options if kind == "forecast_candidate" else None,
                    "judgment_id": contracts.uuid(judgment_id) if judgment_id and kind == "genome" else None,
                    "annotation_bindings": frozen_annotations, "interpretation_bindings": frozen_interpretation}
                key = "advanced:" + contracts.digest([workspace_id, actor_id, fingerprint, trend["revision"], receipt["object_id"]])
                job = self.jobs.enqueue(output_scope, JOB_PREFIX+kind, control, idempotency_key=key, cursor=cur)
                result.append({"job_id": job["job_id"], "kind": kind, "state": job["state"], "input_digest": fingerprint})
            return {"state": "stored", "jobs": result}

    def enqueue_from_receipts(self, cursor, workspace_id, actor_id, receipts, **kwargs):
        if not isinstance(receipts, list) or len(receipts) > 20:
            raise TrendStorageError("advanced_receipt_bound")
        return [self.enqueue(workspace_id, actor_id, r["trend_id"], cursor=cursor, **kwargs)
                for r in receipts if r.get("verification_state") == "verified"]

    def _annotations(self, cur, workspace_id, actor_id, receipt_id, inputs, expected=None):
        if not config.enabled('MODEL_ENRICHMENT', self.values):
            if expected:
                raise TrendStorageError('advanced_annotation_gate_closed')
            return [], [], []
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR SHARE', (workspace_id,))
        found = cur.fetchone()
        if not found:
            raise TrendStorageError('advanced_workspace_unavailable')
        state = json.loads(found[0]) if isinstance(found[0], str) else found[0]
        return semantic_admission.load(self.store, cur, workspace_id=workspace_id, actor_id=actor_id,
            receipt_id=receipt_id, state=state, inputs=inputs, values=self.values, expected=expected)

    def _interpretation(self,cur,workspace_id,actor_id,receipt_id,inputs,expected=None):
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR SHARE',(workspace_id,))
        found=cur.fetchone()
        if not found:
            raise TrendStorageError('advanced_workspace_unavailable')
        state=json.loads(found[0]) if isinstance(found[0],str) else found[0]
        cohort=(state.get('coworker') or {}).get('trendPlatformCohort')
        return interpretation_context.load(cur,self.store,workspace_id,actor_id,inputs,receipt_id=receipt_id,
            state=state,values=self.values,cohort=cohort,expected=expected,now=_iso(self.clock()))

    def _forecast_workspace_inputs(self, cur, workspace_id, inputs, now):
        """Adapt authorized source metadata to the private computation scope.

        Original source scope/node bindings stay in the sealed document. This
        copy only provides the pure evaluator's scope after current sharing and
        workspace entitlement checks; no historical seal is rewritten.
        """
        output_scope = 'workspace:' + contracts.uuid(workspace_id)
        source_scope = inputs['common']['scope_key']
        expiry = inputs['expires_at']
        if source_scope != output_scope:
            if not source_scope.startswith('shared:'):
                raise TrendStorageError('forecast_source_scope')
            cur.execute('SELECT operations,expires_at,revoked_at FROM public.pr_trend_entitlements\n                WHERE workspace_id=%s AND scope_key=%s FOR SHARE', (workspace_id,source_scope))
            entitlement = row(cur)
            if (not entitlement or entitlement['revoked_at'] or contracts.instant(entitlement['expires_at']) <= contracts.instant(now)
                    or not {'retrieve','derive_metrics','share_across_workspaces'} <= set(entitlement['operations'])):
                raise TrendStorageError('forecast_source_entitlement')
            expiries = [expiry,entitlement['expires_at']]
            sources = inputs['common']['sources']
            cur.execute('SELECT observation_id::text,provider_id,source_policy_version,rights\n                FROM public.pr_trend_observations WHERE scope_key=%s AND observation_id=ANY(%s::uuid[]) FOR SHARE',
                (source_scope,[source['source_id'] for source in sources]))
            current = rows(cur)
            if {o['observation_id'] for o in current} != {source['source_id'] for source in sources}:
                raise TrendStorageError('forecast_source_binding')
            checked = {}
            for observation in current:
                key = (observation['provider_id'],observation['source_policy_version'])
                if key not in checked:
                    checked[key] = self.store._policy(cur,source_scope,*key,permission='share_across_workspaces',at=now)
                policy = checked[key]
                if not contracts.permits(observation['rights'],'share_across_workspaces',source_scope,now):
                    raise TrendStorageError('forecast_source_sharing_denied')
                expiries.extend([policy['expires_at'],policy['contract_end'],policy['rights']['share_across_workspaces']['expires_at'],
                    observation['rights']['share_across_workspaces']['expires_at']])
            expiry = _iso(min(expiries,key=contracts.instant))
        private = deepcopy(inputs)
        private['expires_at'] = expiry
        private['common']['scope_key'] = output_scope
        for source in private['common']['sources']:
            source['scope_key'] = output_scope
            source['expires_at'] = _iso(min([source['expires_at'],expiry],key=contracts.instant))
        return private

    def run(self, scope_key, job_id, *, cursor=None):
        """Claim, revalidate, compute and finish atomically; failed commits leave no result."""
        with self.store.transaction(cursor) as cur:
            trust_lock(cur)
            cur.execute("SELECT * FROM public.pr_trend_jobs WHERE scope_key=%s AND job_id=%s", (contracts.scope(scope_key), contracts.uuid(job_id)))
            saved = row(cur)
            if not saved or not saved["kind"].startswith(JOB_PREFIX):
                raise TrendStorageError("advanced_job_missing")
            if saved["state"] == "succeeded":
                return {"state": "succeeded", "replayed": True, "job_id": job_id}
            control = saved["payload"]
            kind = control["artifact_kind"]
            if saved["kind"] != JOB_PREFIX+kind or not self._enabled(control["workspace_id"], kind):
                return {"state": "disabled", "job_id": job_id}
            trend, receipt, manifest, inputs = self._load(cur, control["workspace_id"], control["actor_id"], control["trend_id"])
            method = _method(kind)
            if (scope_key != 'workspace:' + control['workspace_id'] or trend["revision"] != control["trend_revision"]
                    or receipt["object_id"] != control["receipt_id"] or receipt["revision"] != control["receipt_revision"]
                    or manifest["manifest_digest"] != control["input_manifest_digest"] or method["artifact_digest"] != control["artifact_digest"]
                    or control["input_digest"] != _fingerprint(manifest["manifest_digest"], kind, method["artifact_digest"], control["forecast_options"], control["judgment_id"], control.get("annotation_bindings"), control.get("interpretation_bindings"))):
                raise TrendStorageError("advanced_frozen_input_changed")
            claim = self.jobs.claim("advanced-local", scope_key=scope_key, kind=saved["kind"], job_id=job_id, lease_seconds=60, cursor=cur)
            if not claim:
                return {"state": "busy", "job_id": job_id}
            claim = self.jobs.start(claim, cursor=cur)
            now = _iso(self.clock())
            selected, _bindings, model_refs = self._annotations(cur, control['workspace_id'], control['actor_id'],
                control['receipt_id'], inputs, expected=control.get('annotation_bindings') or []) if kind in SEMANTIC_KINDS else ([], [], [])
            interpretation = self._interpretation(cur,control['workspace_id'],control['actor_id'],control['receipt_id'],
                inputs,expected=control.get('interpretation_bindings')) if kind == 'genome' else None
            semantic = semantic_admission.adapt(inputs, selected, now) if selected else None
            if semantic:
                inputs['expires_at'] = semantic['expires_at']
            if interpretation:
                inputs['expires_at'] = min((inputs['expires_at'],interpretation['expires_at']),key=contracts.instant)
            computation = self._forecast_workspace_inputs(cur,control['workspace_id'],inputs,now) if kind == 'forecast_candidate' else inputs
            if kind == 'forecast_candidate':
                inputs['expires_at'] = computation['expires_at']
            output = build_projection(kind, computation, now=now, forecast_options=control["forecast_options"],
                semantic_dimensions=semantic['dimensions'] if semantic else None, semantic=semantic,semantic_selected=selected,interpretation=interpretation)
            self.store.put_method(method["method_id"], method["method_version"], method["artifact_digest"],
                {"execution": "local_deterministic", "semantic_qualification": "unqualified", "kind": kind}, cursor=cur)
            refs = [{"scope_key": r["scope_key"], "node_id": r["projection_id"]} for r in (trend, receipt)] + model_refs
            if interpretation:
                refs += interpretation['refs']
            refs = list({(r['scope_key'],r['node_id']):r for r in refs}.values())
            # Retain the complete computed evidence in bounded chunks. The base
            # receipt remains the authority for source text and current deletion.
            from .pipeline import encode_manifest
            details = ({'artifact': output['details']} if kind == 'forecast_candidate' else
                       {'input_digest': control['input_digest'], 'details': output['details']})
            if kind == 'forecast_candidate':
                required = set(output['details']['evidence_refs'])
                required.update(ref for window in output['details']['prediction_recipe']['history'] for ref in window['evidence_refs'])
                details['source_bindings'] = [{'source_id': s['source_id'], 'scope_key': s['scope_key'], 'node_id': s['source_id']}
                    for s in inputs['common']['sources'] if s['source_id'] in required]
            details['manifest_digest'] = contracts.digest(details)
            detail_recipe, chunks = encode_manifest(details)
            sealed = self.store.put_manifest(scope_key, refs, decision_cutoff=now, available_at=now, retention_until=inputs["expires_at"],
                recipe={"input_digest": control["input_digest"], "receipt_id": receipt["object_id"], "method": method,
                        "source_manifest_digest": manifest["manifest_digest"], 'detail_codec': detail_recipe,
                        **(detail_recipe if kind == 'forecast_candidate' else {})},
                chunks=chunks, document_digest=details['manifest_digest'], cursor=cur)
            object_id = _id(scope_key, kind, control["input_digest"]) if kind == "forecast_candidate" else control["trend_id"]
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (scope_key+'|projection|'+kind+'|'+object_id,))
            cur.execute("SELECT coalesce(max(revision),0) FROM public.pr_trend_projections WHERE scope_key=%s AND kind=%s AND object_id=%s", (scope_key, kind, object_id))
            previous = cur.fetchone()[0]
            payload = {**output["payload"], "input_digest": control["input_digest"], "trust_receipt_id": receipt["object_id"],
                       "source_decision_cutoff": manifest["recipe"]["decision_cutoff"], "computed_at": now}
            if kind in SEMANTIC_KINDS:
                payload['_semantic_bindings'] = _bindings
            if kind == 'genome':
                payload['_interpretation_bindings'] = interpretation['bindings']
            if kind == 'forecast_candidate':
                payload.update(schema_version='trend.forecast.candidate.v1', trend_id=control['trend_id'],
                    prediction_ref={'manifest_id': sealed['manifest_id'], 'document_digest': details['manifest_digest']},
                    source_bindings_ref={'manifest_id': sealed['manifest_id'], 'document_digest': details['manifest_digest']})
                if len(contracts.canonical(payload).encode()) > 60_000:
                    raise TrendStorageError('forecast_candidate_payload_bound')
            self.store.put_projection({"scope_key": scope_key, "kind": kind, "object_id": object_id, "revision": previous+1,
                "manifest_id": sealed["manifest_id"], "method_id": method["method_id"],
                "method_version": method["method_version"], "decision_cutoff": now, "available_at": now,
                "retention_until": inputs["expires_at"], "payload": payload}, expected_revision=previous, cursor=cur)
            self.jobs.finish_local(claim, cursor=cur)
            return {"state": "succeeded", "job_id": job_id, "kind": kind, "object_id": object_id, "revision": previous+1}

    def tick(self, *, limit=2, max_seconds=8):
        if type(limit) is not int or not 1 <= limit <= 5:
            raise TrendStorageError("advanced_tick_bound")
        if not all(config.enabled(n, self.values) for n in ("INTELLIGENCE", "RADAR", "TRUST_RECEIPTS")):
            return {"state": "disabled", "results": []}
        if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or not 0 < max_seconds <= 20:
            raise TrendStorageError('advanced_time_bound')
        deadline = time.monotonic() + max_seconds
        with self.store.transaction() as cur:
            cur.execute("""SELECT scope_key,job_id::text FROM public.pr_trend_jobs
                WHERE kind=ANY(%s) AND state IN ('queued','retry_wait') AND due_at<=clock_timestamp()
                  AND NOT cancellation_requested ORDER BY due_at,job_id LIMIT %s""", ([JOB_PREFIX+k for k in KINDS if config.enabled(FLAGS[k], self.values)], limit))
            pending = cur.fetchall()
        results = []
        for scope, identity in pending:
            if time.monotonic() >= deadline:
                break
            try:
                results.append(self.run(scope, identity))
            except (ValueError, KeyError, TypeError):
                # Stale/withdrawn work cannot pin the head of the local queue.
                self.jobs.cancel(scope, identity)
                results.append({"state": "cancelled", "job_id": identity, "reason": "current_inputs_unavailable"})
        return {"state": "local_only", "results": results}

    def plan_current(self, *, max_workspaces=1, trend_limit=2):
        """Rotate through allowed workspaces and stored trends; never a read-side effect.

        Cursor controls share the service-only trend cursor table, without retaining
        source text. Every candidate is authenticated and rechecked on execution.
        No model or external operation can be dispatched by this planner.
        """
        from ...coworker import flags
        if type(max_workspaces) is not int or not 1 <= max_workspaces <= 2 or type(trend_limit) is not int or not 1 <= trend_limit <= 2:
            raise TrendStorageError('advanced_plan_bound')
        result = {'state': 'disabled', 'workspaces': 0, 'planned': 0, 'unavailable': 0}
        kinds = tuple(k for k in KINDS if config.enabled(FLAGS[k], self.values))
        if not kinds or not all(config.enabled(n, self.values) for n in ('INTELLIGENCE', 'RADAR', 'TRUST_RECEIPTS')):
            return result
        allowed = config.admitted_workspaces(self.values)
        if not allowed:
            return result
        with self.store.transaction() as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('trend-advanced-plan-v1',0))")
            if not cur.fetchone()[0]:
                return {**result, 'state': 'busy'}
            cur.execute("""SELECT w.id::text,actor.user_id::text FROM public.pr_workspaces w
                LEFT JOIN public.pr_trend_provider_cursors runtime
                    ON runtime.scope_key='workspace:'||w.id::text AND runtime.provider_id=%s AND runtime.partition_key=%s
                JOIN LATERAL (SELECT m.user_id FROM public.pr_memberships m
                    JOIN public.pr_profiles p ON p.user_id=m.user_id
                    WHERE m.workspace_id=w.id AND m.status='active' AND m.role IN ('owner','editor') AND p.deleted_at IS NULL
                    ORDER BY (m.role='owner') DESC,m.user_id LIMIT 1) actor ON true
                WHERE w.id=ANY(%s::uuid[]) AND NOT w.state ? 'accountDeletion'
                  AND coalesce(w.state->'workspace'->>'sample','false')<>'true'
                ORDER BY runtime.updated_at NULLS FIRST,w.id LIMIT %s""",
                (SCAN_PROVIDER, SCAN_PARTITION, allowed, max_workspaces))
            targets = cur.fetchall()
            for wid, actor in targets:
                if not config.workspace_allowed(wid, self.values):
                    continue
                cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (wid,)); cur.fetchone()
                scopes = self.store.authorized_scopes(wid, actor, cursor=cur)
                scan_scope = 'workspace:' + wid
                self.store.ensure_scope(scan_scope, cursor=cur)
                cur.execute('INSERT INTO public.pr_trend_provider_cursors(scope_key,provider_id,partition_key) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (scan_scope,SCAN_PROVIDER,SCAN_PARTITION))
                cur.execute('SELECT cursor_value FROM public.pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s FOR UPDATE', (scan_scope,SCAN_PROVIDER,SCAN_PARTITION))
                saved = cur.fetchone()[0]
                after = saved.get('after_object_id') if isinstance(saved, dict) else None
                after = contracts.uuid(after) if after else None
                now = _iso(self.clock())
                cur.execute("""SELECT DISTINCT p.object_id::text FROM public.pr_trend_projections p
                    WHERE p.scope_key=ANY(%s) AND p.kind='trend' AND p.available_at<=%s AND p.retention_until>%s
                      AND (%s::uuid IS NULL OR p.object_id>%s::uuid)
                    ORDER BY p.object_id::text LIMIT %s""", (scopes,now,now,after,after,trend_limit+1))
                identities = [r[0] for r in cur.fetchall()]
                for identity in identities[:trend_limit]:
                    cur.execute('SAVEPOINT trend_advanced_candidate')
                    try:
                        planned = self.enqueue(wid, actor, identity, kinds=kinds, cursor=cur)
                        result['planned'] += len(planned['jobs'])
                    except (contracts.ContractError, KeyError, TypeError):
                        cur.execute('ROLLBACK TO SAVEPOINT trend_advanced_candidate')
                        result['unavailable'] += 1
                    finally:
                        cur.execute('RELEASE SAVEPOINT trend_advanced_candidate')
                checkpoint = {'scanned_at': now, 'after_object_id': identities[trend_limit-1] if len(identities)>trend_limit else None}
                cur.execute('UPDATE public.pr_trend_provider_cursors SET cursor_value=%s::jsonb,generation=generation+1,updated_at=clock_timestamp() WHERE scope_key=%s AND provider_id=%s AND partition_key=%s', (json.dumps(checkpoint),scan_scope,SCAN_PROVIDER,SCAN_PARTITION))
                result['workspaces'] += 1
        return {**result, 'state': 'local_only'}
