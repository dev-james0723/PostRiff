"""Stored, local whitespace admission. No retrieval, model call or acceptance authority.

Parent hooks: WhitespaceAdmission(store, values=...).plan_current() on a bounded
worker tick; current_result(..., cursor=cur) on an authenticated stored read.
A lexical question candidate never establishes unmet demand or missing supply.

Optional operator review: kind=whitespace at review_id(wid, trend_id, candidate_id),
with REVIEW_SCHEMA and a qualified method whose config.whitespace_admission is
{state: production, role: gap_review, schema_version: REVIEW_SCHEMA}. The method
must be promoted outside this module; neither a request nor generated output can
supply that authority. Review payloads bind candidate/receipt/frame/context/facts/
semantic digests, contain reviewed_by/review_ref/evaluation_digest/fixture:false,
and explicit demand, supply, credibility, originality and risk assessments.
"""
from copy import deepcopy
from datetime import timedelta
import inspect
import json
import sys
import uuid

from ... import memory, source_policy
from ...coworker import flags
from . import config, context, contracts, generation, opportunities, relevance, semantic_admission, text_context, whitespace
from postriff_alpha.domain import AlphaError
from .advanced_pipeline import AdvancedPipeline
from .store import TrendStorageError, trust_lock, utcnow

SCHEMA = 'rafii.trend-whitespace-admission.v1'
REVIEW_SCHEMA = 'rafii.trend-whitespace-review.v1'
SCAN_PROVIDER = 'rafii.local.whitespace-admission'
SCAN_PARTITION = 'workspace-scan-v1'
MAX_CANDIDATES = 20


def review_id(workspace_id, trend_id, candidate_id):
    return str(uuid.uuid5(uuid.UUID(workspace_id), contracts.canonical(
        ['trend-whitespace-review-v1', trend_id, candidate_id])))


def workspace_facts(state):
    """Use the existing local public-draft policy projection, not social claims."""
    private = deepcopy(state)
    ids = [s['id'] for s in private.get('sources', []) if s.get('active') and s.get('selected')
           and s.get('kind') != 'voice_sample' and (s.get('origin') or {}).get('kind') != 'trend_opportunity'][:6]
    projected = source_policy.project_context(private, 'draft', 'local', ids)
    facts = [f for s in projected['sources'] if not s['candidateOnly'] for f in s['facts']][:20]
    # Never put approved fact text or private boundary text in an analytics payload.
    binding = {'context_digest': relevance.context_revision(state),
        'facts_digest': contracts.digest({'projection': {k:v for k,v in projected.items() if k != 'policyEpoch'}, 'selection': ids,
                                          'boundaries': memory.boundary_fields(private)})}
    return {**binding, 'approved_fact_refs': [f['id'] for f in facts],
        'boundaries_present': any(str(f.get('value', '')).strip() for f in memory.boundary_fields(private))}


def _strings(value, *, limit=20, chars=200):
    return (isinstance(value, list) and len(value) <= limit
            and all(isinstance(v, str) and 0 < len(v) <= chars for v in value) and len(set(value)) == len(value))


def assess(inputs, *, candidate_payload, reviews, selected, semantic_bindings, state,
           workspace_id, trend_id, receipt_id, receipt_revision, candidate_revision, now):
    """Pure adapter for authenticated storage inputs; deliberately not an HTTP API."""
    facts = workspace_facts(state)
    semantic = semantic_admission.adapt(inputs, selected, now)
    qualified_refs = {ref for annotation in semantic['annotations'] for ref in annotation['evidence_refs']}
    expiry = min([inputs['expires_at'], semantic['expires_at']], key=contracts.instant)
    common = {**inputs['common'], 'decision_cutoff': now}
    indexed = context.source_index(common, 'creative', originals=True)
    comparison = {sid for sid, s in indexed.items()
        if context.timestamp(inputs['frame']['window_start']) <= context.timestamp(s['event_at'])
        < context.timestamp(inputs['frame']['window_end'])}
    rebuilt = {c['candidate_id']: c for c in text_context.question_candidates(inputs)['candidates']}
    offered = candidate_payload.get('candidates', [])
    if (not isinstance(offered, list) or len(offered) > MAX_CANDIDATES
            or any(not isinstance(c, dict) or not isinstance(c.get('candidate_id'), str) for c in offered)
            or len({c['candidate_id'] for c in offered}) != len(offered)):
        raise TrendStorageError('whitespace_candidate_bound')
    bundles, _ = text_context.reconstruct(inputs)
    complete_roots = {b['root_id'] for b in bundles['bundles'] if b['context_completeness'] == 'complete'}
    rows, gaps, extra = [], [], {}
    for offered_candidate in offered:
        cid = offered_candidate.get('candidate_id')
        candidate = rebuilt.get(cid)
        if (not candidate or offered_candidate.get('literal_question_digest') != candidate['literal_question_digest']
                or offered_candidate.get('supply_frame') != inputs['frame']
                or offered_candidate.get('evidence_refs') != candidate['evidence_refs'][:20]):
            raise TrendStorageError('whitespace_candidate_changed')
        review = reviews.get(cid)
        p = review['payload'] if review else {}
        expected = {'workspace_id': workspace_id, 'trend_id': trend_id, 'candidate_id': cid,
            'candidate_revision': candidate_revision, 'trust_receipt_id': receipt_id,
            'receipt_revision': receipt_revision, 'frame_id': inputs['frame']['frame_id'],
            **{k: facts[k] for k in ('context_digest', 'facts_digest')},
            'semantic_bindings_digest': contracts.digest(semantic_bindings)}
        bound = bool(review) and all(p.get(k) == v for k, v in expected.items())
        demand = p.get('demand_evidence_refs', [])
        support = p.get('supporting_supply_refs', [])
        oppose = p.get('opposing_supply_refs', [])
        confirmed = p.get('confirmed_user_fact_refs', [])
        if not all(_strings(v) for v in (demand, support, oppose, confirmed)):
            raise TrendStorageError('whitespace_review_refs_invalid')
        demand_ok = (bool(demand) and set(demand) <= set(candidate['evidence_refs']) & comparison
            and len({context.creator_key(indexed[r]) for r in demand if r in indexed and context.creator_key(indexed[r])}) >= 2)
        semantic_ok = bool(qualified_refs) and bool(demand) and set(demand + support + oppose) <= qualified_refs
        supply = p.get('supply_comparison') or {}
        expected_units = supply.get('expected_units')
        compared = supply.get('evidence_refs', [])
        supply_ok = (bound and _strings(compared, limit=1000) and set(compared) == comparison
            and type(expected_units) is int and len(comparison) <= expected_units <= 1000
            and expected_units > 0 and supply.get('frame_id') == inputs['frame']['frame_id']
            and supply.get('scope') == 'observed_comparison_sample'
            and set(support + oppose) <= comparison and not set(support) & set(oppose))
        # Numerator is the actual retained sample, not a caller/model supplied count.
        ratio = len(comparison) / expected_units if supply_ok else 0
        fact_ok = bool(confirmed) and set(confirmed) <= set(facts['approved_fact_refs'])
        reason = []
        if not bound: reason.append('current_candidate_review_required')
        if not semantic_ok: reason.append('reviewed_semantic_support_required')
        if not fact_ok: reason.append('approved_workspace_facts_required')
        if facts['boundaries_present']: reason.append('workspace_boundaries_require_review')
        if len(candidate['evidence_refs']) > 20: reason.append('candidate_evidence_bound')
        contribution = p.get('proposed_contribution')
        if not isinstance(contribution, str) or not 0 < len(contribution) <= 800:
            reason.append('reviewed_contribution_required'); contribution = None
        risk = p.get('risk_assessment')
        risks, disconfirming = p.get('risks', []), p.get('disconfirming_evidence', [])
        if not all(_strings(v, limit=8, chars=400) for v in (risks, disconfirming)):
            raise TrendStorageError('whitespace_review_text_bound')
        supported = {'available_at': now, 'expires_at': expiry, 'evidence_refs': sorted(set(demand))}
        gate = not reason and bound and semantic_ok
        rows.append({**supported, 'candidate_id': cid, 'gap_type': p.get('gap_type', 'unanswered_question'),
            'demand_evidence_refs': demand, 'demand_strength': 'supported' if gate and demand_ok
                and p.get('demand_strength') == 'supported' else 'unknown',
            'supply_search_scope': {**supported, 'evidence_refs': compared if supply_ok else [],
                'frame_id': inputs['frame']['frame_id'], 'qualified': gate and supply_ok,
                'retrieval_coverage': ratio, 'observed_units': len(comparison),
                'expected_units': expected_units if supply_ok else None,
                'scope': 'observed_comparison_sample',
                # A reviewed sample still cannot invent uncollected reply context.
                'context_complete': supply.get('context_complete') is True and bool(demand)
                    and set(demand) <= complete_roots},
            'supporting_supply_refs': support, 'opposing_supply_refs': oppose,
            'angle_occupancy': {'supporting_count': len(support), 'opposing_count': len(oppose), 'scope': 'observed_comparison_sample'},
            'credibility': {**supported, 'workspace_id': workspace_id, 'approved': gate and fact_ok
                and p.get('credibility') == 'supported', 'approved_fact_refs': confirmed if fact_ok else []},
            'requires_user_fact': True, 'confirmed_user_fact_refs': confirmed,
            'risk_blocked': risk != 'clear' or not gate, 'originality_review': p.get('originality_review', 'unknown'),
            'proposed_contribution': contribution, 'risks': risks, 'disconfirming_evidence': disconfirming})
        extra[cid] = reason
        gaps.append({k: deepcopy(candidate[k]) for k in ('candidate_id', 'platform', 'language',
            'observed_original_count', 'known_creator_count')})
    result = whitespace.find_whitespace({**common, 'workspace_id': workspace_id, 'candidates': rows,
                                         'approved_user_fact_refs': facts['approved_fact_refs']})
    for rejected in result['rejected']:
        rejected['reasons'] = sorted(set(rejected['reasons'] + extra[rejected['candidate_id']]))
    rejected = {r['candidate_id']: r['reasons'] for r in result['rejected']}
    for gap in gaps:
        gap.update(state='review_required' if gap['candidate_id'] in rejected else 'admitted',
                   reasons=rejected.get(gap['candidate_id'], []),
                   summary=('Repeated question wording in '+str(gap['observed_original_count'])+' retained original posts from '
                       +str(gap['known_creator_count'])+' known creators. '
                       +('Demand, supply and workspace contribution still require current review.' if gap['candidate_id'] in rejected
                         else 'A reviewed contribution is supported within this comparison sample.')))
    return {'schema_version': SCHEMA, 'state': 'admitted' if result['opportunities'] else 'review_required' if gaps else 'unavailable',
        'workspace_id': workspace_id, 'trend_id': trend_id, 'trust_receipt_id': receipt_id,
        'context_digest': facts['context_digest'], 'facts_digest': facts['facts_digest'],
        'opportunities': result['opportunities'], 'rejected': result['rejected'], 'gaps': gaps,
        'claim_scope': 'observed_comparison_sample', 'semantic_qualification': 'unqualified',
        'expires_at': expiry, 'truncated': candidate_payload.get('truncated') is True,
        'limitations': ['A gap assessment is not an accepted idea, factual approval or publishing instruction.',
            'Supply coverage concerns only the reviewed observed comparison sample.',
            'Uncollected reply context cannot establish that a question is unanswered.']}


def _option_candidates(data, state, trend, inputs, selected, now):
    """Validate a stored reviewed contribution with the existing original-option contract.

    This is local validation, not generation. Reuse the existing generation_context
    lineage guard so fact/use/egress changes invalidate later drafting and publishing.
    """
    chosen = next((e for e in selected if e['qualified'] and e['task'] == 'semantic_label_generate'), None)
    if not chosen or not data['opportunities']:
        return []
    try:
        model = chosen['result']['executed_model']
        facts = generation.workspace_context(state, {'model': model})
    except (AlphaError, ValueError, KeyError, TypeError):
        data['limitations'].append('Current approved facts and their existing drafting permissions are required for an executable option.')
        return []
    bound = {'schema_version':'rafii.trend-generation-context.v1', 'context_digest':facts['revision'],
             'model':model, 'source_ids':facts['source_ids']}
    platform = inputs['frame']['platform'].lower()
    channels = [c for c in (state.get('phase2') or {}).get('channels', [])
                if not c.get('revoked') and str(c.get('platform', '')).lower() == platform]
    if not channels:
        data['limitations'].append('An active account on the observed platform is required before creating an opportunity.')
        return []
    result = []
    for gap in data['opportunities'][:3]:
        refs = gap['demand_evidence_refs']
        if len(refs) > 12:
            continue
        evidence = [{'observation_id':sid, 'text':inputs['facts'][sid]['text'][:800]} for sid in refs]
        spans = [{'observation_id':e['observation_id'], 'start':0, 'end':min(240,len(e['text'])),
                  'text':e['text'][:240]} for e in evidence]
        item = {'title':'Reviewed '+gap['gap_type'].replace('_',' '), 'contribution':gap['proposed_contribution'],
            'format_reason':'Use a creator-owned example; keep unverified social claims separate.',
            'factual_requirements':['Use only the bound approved creator facts; confirm any additional experience.'],
            'premise_fact_ids':gap['credibility']['approved_fact_refs'], 'language':inputs['frame']['language'],
            'uncertainties':['This reviewed comparison sample does not qualify cultural meaning, popularity or future outcomes.'],
            'evidence_spans':spans, 'fit':{'assessment':'unknown','reason':'Workspace fit remains a hypothesis.'},
            'risk':{'assessment':'unknown','reason':'A current review cleared this proposed contribution; outcome risk remains unknown.'}}
        try:
            angle = generation.validate_output({'items':[item]}, 'angle_generate',
                {'evidence':evidence,'workspace_context':facts,'input_digest':data['input_digest']})[0]
        except (AlphaError, ValueError, KeyError, TypeError):
            data['limitations'].append('A reviewed contribution did not satisfy the existing bounded original-option contract.')
            continue
        angle.update(semantic_qualification='unqualified', review_state='reviewed_contribution',
            evidence_refs=refs, whitespace_candidate_id=gap['candidate_id'])
        wid = data['workspace_id']
        oid = str(uuid.uuid5(uuid.UUID(wid), contracts.canonical(
            ['trend-whitespace-opportunity-v1',data['trend_id'],gap['candidate_id'],data['context_digest']])))
        shown = {**trend['payload'],'id':trend['object_id'],'trust_receipt_id':data['trust_receipt_id'],
                 'expires_at':data['expires_at']}
        op = opportunities.candidate(shown,relevance.evaluate(shown,state),state,wid,
            opportunities.epoch(now),angles=[angle],platform_targets=[platform])
        op.update(id=oid,state='suggested',executable_ready=True,qualified=False,semantic_qualification='unqualified',
            generation_context=deepcopy(bound),whitespace_candidate_id=gap['candidate_id'],
            title=angle['title'],contribution=angle['contribution'],
            uncertainty='Review-backed original contribution within the observed sample; no empirical outcome qualification.')
        result.append(op)
    return result


def _validate_binding(store, cursor, workspace_id, actor_id, state, binding, *, mutation=False):
    """Check current heads and independent review authority, not only retained DAG nodes."""
    if (not isinstance(binding,dict) or binding.get('schema_version') != 'rafii.trend-whitespace-binding.v1'
            or binding.get('workspace_id') != workspace_id or not isinstance(binding.get('nodes'),list)
            or not 1 <= len(binding['nodes']) <= 100):
        raise TrendStorageError('whitespace_binding_invalid')
    facts = workspace_facts(state)
    if any(facts[k] != binding.get(k) for k in ('context_digest','facts_digest')):
        raise TrendStorageError('whitespace_context_changed')
    for bound in binding.get('fact_bindings',[]):
        generation.validate_context_binding(state,bound)
    refs = [{k:n[k] for k in ('kind','object_id','revision')} for n in binding['nodes']]
    trust_lock(cursor)
    if mutation:
        store.lock_dependencies(workspace_id,actor_id,refs,cursor=cursor)
    for node in binding['nodes']:
        row = store.get_projection(workspace_id,actor_id,node['kind'],node['object_id'],cursor=cursor)
        if (not row or row['validity'] != 'valid' or row['scope_key'] != node['scope_key']
                or row['revision'] != node['revision'] or contracts.digest(row['payload']) != node['payload_digest']):
            raise TrendStorageError('whitespace_dependency_changed')
        if node['kind'] in ('trend','receipt') and row['verification_state'] != 'verified':
            raise TrendStorageError('whitespace_dependency_unverified')
        if node.get('review_authority'):
            cursor.execute('SELECT qualification,revoked_at,config FROM public.pr_trend_method_versions WHERE method_id=%s AND version=%s FOR SHARE',
                           tuple(row['method_bundle'][k] for k in ('method_id','version')))
            method=cursor.fetchone()
            if not method or method[0] != 'qualified' or method[1] is not None or not isinstance(method[2],dict):
                raise TrendStorageError('whitespace_review_unavailable')
            payload = row['payload']
            if payload.get('schema_version') == REVIEW_SCHEMA:
                admitted = method[2].get('whitespace_admission') == {
                    'state':'production','role':'gap_review','schema_version':REVIEW_SCHEMA}
            elif node['kind'] in ('model_qualification','task_qualification','cohort_qualification'):
                gate = method[2].get('semantic_admission')
                admitted = (isinstance(gate,dict) and gate.get('state') == 'production'
                    and gate.get('role') == node['kind'] and all(payload.get(k) and
                        gate.get(k) == payload[k] for k in ('model_id','task','cohort')))
            else:
                admitted = False
            if not admitted:
                raise TrendStorageError('whitespace_review_unavailable')
            store._actor(cursor,workspace_id,payload['reviewed_by'],write=True)


def validate_opportunity(store, *, cursor, workspace_id, actor_id, opportunity, state, mutation=False):
    """Parent read/accept/apply/queue hook. No-op for ordinary opportunities; no writes.

    Existing source/Ideas/FactPack acceptance remains the only transition authority.
    This guard intentionally has no rollout flag: accepted lineage still needs its
    current rights, review heads and facts if a feature is later disabled.
    """
    binding = opportunity.get('whitespace_binding')
    if binding is None:
        return
    if opportunity.get('workspace_id') != workspace_id or opportunity.get('state') in ('expired','retracted','dismissed'):
        raise TrendStorageError('whitespace_opportunity_unavailable')
    if contracts.instant(opportunity['expires_at']) <= contracts.instant(utcnow()):
        raise TrendStorageError('whitespace_opportunity_expired')
    _validate_binding(store,cursor,workspace_id,actor_id,state,binding,mutation=mutation)


class WhitespaceAdmission:
    def __init__(self, store, *, values=None, clock=utcnow):
        self.store, self.values, self.clock = store, values, clock

    def _enabled(self, wid):
        return config.workspace_allowed(wid, self.values) and all(config.enabled(n, self.values)
            for n in ('RADAR', 'TRUST_RECEIPTS', 'WHITESPACE'))

    def _method(self):
        artifact = contracts.digest({m.__name__: inspect.getsource(m) for m in
            (sys.modules[__name__], whitespace, context, text_context, semantic_admission, source_policy, relevance, generation)})
        return {'method_id': 'trend.whitespace.admission', 'version': 'local-' + artifact[:16], 'artifact_digest': artifact}

    def _review(self, cur, wid, actor, trend_id, cid):
        value = self.store.get_projection(wid, actor, 'whitespace', review_id(wid, trend_id, cid), cursor=cur)
        if not value or value['validity'] != 'valid' or value['scope_key'] != 'workspace:' + wid:
            return None
        p = value['payload']
        if (p.get('schema_version') != REVIEW_SCHEMA or p.get('fixture') is not False
                or not all(p.get(k) for k in ('review_ref', 'reviewed_by', 'evaluation_digest'))):
            return None
        cur.execute('SELECT qualification,revoked_at,config FROM public.pr_trend_method_versions WHERE method_id=%s AND version=%s FOR SHARE',
                    tuple(value['method_bundle'][k] for k in ('method_id', 'version')))
        status = cur.fetchone()
        if (not status or status[0] != 'qualified' or status[1] is not None
                or status[2].get('whitespace_admission') != {'state': 'production', 'role': 'gap_review', 'schema_version': REVIEW_SCHEMA}):
            return None
        self.store._actor(cur, wid, p['reviewed_by'], write=True)
        return value

    def _load(self, cur, wid, actor, trend_id, *, write=False):
        trust_lock(cur)
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR ' + ('UPDATE' if write else 'SHARE'), (wid,))
        found = cur.fetchone()
        if not found: raise TrendStorageError('workspace_access_denied')
        self.store._actor(cur, wid, actor, write=write)
        state = json.loads(found[0]) if isinstance(found[0], str) else found[0]
        if (state.get('workspace') or {}).get('sample') or 'accountDeletion' in state:
            raise TrendStorageError('workspace_access_denied')
        advanced = AdvancedPipeline(self.store, values=self.values, clock=self.clock)
        trend, receipt, manifest, inputs = advanced._load(cur, wid, actor, trend_id)
        saved = self.store.get_projection(wid, actor, 'whitespace_candidate', trend_id, cursor=cur)
        if (not saved or saved['validity'] != 'valid' or saved['scope_key'] != 'workspace:' + wid
                or saved['payload'].get('trust_receipt_id') != receipt['object_id']):
            raise TrendStorageError('whitespace_candidate_unavailable')
        offered = saved['payload'].get('candidates', [])
        if not isinstance(offered, list) or len(offered) > MAX_CANDIDATES:
            raise TrendStorageError('whitespace_candidate_bound')
        selected, bindings, semantic_refs = ([], [], [])
        if config.enabled('MODEL_ENRICHMENT', self.values):
            selected, bindings, semantic_refs = semantic_admission.load(self.store, cur, workspace_id=wid,
                actor_id=actor, receipt_id=receipt['object_id'], state=state, inputs=inputs, values=self.values)
        reviews = {c['candidate_id']: r for c in offered
                   if (r := self._review(cur, wid, actor, trend_id, c['candidate_id']))}
        dependencies = [trend, receipt, saved, *reviews.values()]
        self.store.lock_dependencies(wid, actor, [{k:r[k] for k in ('kind','object_id','revision')} for r in dependencies], cursor=cur)
        expiry = min([inputs['expires_at'], *(r['expires_at'] for r in dependencies),
                      *(s['expires_at'] for s in selected)], key=contracts.instant)
        now = contracts.iso(contracts.instant(self.clock()))
        expiry = min(contracts.instant(expiry), contracts.instant(now) + timedelta(hours=6))
        inputs = {**inputs, 'expires_at': contracts.iso(expiry)}
        data = assess(inputs, candidate_payload=saved['payload'], reviews=reviews, selected=selected,
            semantic_bindings=bindings, state=state, workspace_id=wid, trend_id=trend_id,
            receipt_id=receipt['object_id'], receipt_revision=receipt['revision'], candidate_revision=saved['revision'], now=now)
        method = self._method()
        fingerprint = contracts.digest({'method': method, 'dependencies': [{k:r[k] for k in
            ('scope_key','kind','object_id','revision')} for r in dependencies], 'semantic_bindings': bindings,
            'context_digest': data['context_digest'], 'facts_digest': data['facts_digest']})
        refs = [{'scope_key':r['scope_key'], 'node_id':r['projection_id']} for r in dependencies] + semantic_refs
        data.update(input_digest=fingerprint, source_decision_cutoff=manifest['recipe']['decision_cutoff'], computed_at=now)
        options = _option_candidates(data,state,trend,inputs,selected,now)
        bound_rows = list(dependencies)
        for b in bindings:
            for kind,oid,revision in [('model_judgment',b['object_id'],b['revision'])] + [
                    (r['kind'],r['object_id'],r['revision']) for r in b['qualification_refs']]:
                row = self.store.get_projection(wid,actor,kind,oid,revision=revision,cursor=cur)
                if not row or row['validity'] != 'valid': raise TrendStorageError('whitespace_annotation_unavailable')
                bound_rows.append(row)
        binding = {'schema_version':'rafii.trend-whitespace-binding.v1','workspace_id':wid,
            'context_digest':data['context_digest'],'facts_digest':data['facts_digest'],
            'fact_bindings':[op['generation_context'] for op in options],
            'nodes':[{**{k:r[k] for k in ('scope_key','kind','object_id','revision')},
                'payload_digest':contracts.digest(r['payload']),
                'review_authority':r['kind'] in ('model_qualification','task_qualification','cohort_qualification')
                    or r['payload'].get('schema_version') == REVIEW_SCHEMA} for r in bound_rows]}
        data['input_digest'] = contracts.digest({'source':fingerprint,'fact_bindings':binding['fact_bindings']})
        data['_admission_binding'] = binding
        data['opportunity_refs'] = []
        for op in options:
            op.update(whitespace_binding=deepcopy(binding),whitespace_input_digest=data['input_digest'])
        return data, method, refs, options

    def refresh(self, workspace_id, actor_id, trend_id, *, cursor=None):
        wid, actor, tid = map(contracts.uuid, (workspace_id, actor_id, trend_id))
        if not self._enabled(wid): return {'state': 'disabled'}
        with self.store.transaction(cursor) as cur:
            data, method, refs, options = self._load(cur, wid, actor, tid, write=True)
            scope = 'workspace:' + wid
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (scope+'|projection|whitespace|'+tid,))
            prior = self.store.get_projection(wid, actor, 'whitespace', tid, cursor=cur)
            if prior and prior['validity'] == 'valid' and prior['payload'].get('input_digest') == data['input_digest']:
                return {'state': 'reused', 'object_id': tid, 'revision': prior['revision']}
            cur.execute('SELECT coalesce(max(revision),0) FROM public.pr_trend_projections WHERE scope_key=%s AND kind=%s AND object_id=%s', (scope,'whitespace',tid))
            previous = cur.fetchone()[0]
            for op in sorted(options,key=lambda v:v['id']):
                cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(scope+'|projection|opportunity|'+op['id'],))
                cur.execute("SELECT coalesce(max(revision),0) FROM public.pr_trend_projections WHERE scope_key=%s AND kind='opportunity' AND object_id=%s",(scope,op['id']))
                op['revision'] = cur.fetchone()[0]+1
                data['opportunity_refs'].append({'candidate_id':op['whitespace_candidate_id'],
                    'opportunity_id':op['id'],'revision':op['revision']})
            now = contracts.iso(contracts.instant(self.clock()))
            if contracts.instant(data['expires_at']) <= contracts.instant(now):
                raise TrendStorageError('whitespace_inputs_expired')
            self.store.ensure_scope(scope, cursor=cur)
            self.store.put_method(method['method_id'], method['version'], method['artifact_digest'],
                {'execution':'local_deterministic','semantic_qualification':'unqualified','schema_version':SCHEMA}, cursor=cur)
            manifest = self.store.put_manifest(scope, refs, decision_cutoff=now, available_at=now,
                retention_until=data['expires_at'], recipe={'input_digest':data['input_digest'],
                    'trust_receipt_id':data['trust_receipt_id'], 'context_digest':data['context_digest']}, cursor=cur)
            if len(contracts.canonical(data).encode()) > 60000: raise TrendStorageError('whitespace_payload_bound')
            gap_node = self.store.put_projection({'scope_key':scope,'kind':'whitespace','object_id':tid,'revision':previous+1,
                'manifest_id':manifest['manifest_id'],'method_id':method['method_id'],'method_version':method['version'],
                'decision_cutoff':now,'available_at':now,'retention_until':data['expires_at'],
                'context_digest':data['context_digest'],'payload':data}, expected_revision=previous, cursor=cur)
            for op in options:
                validate_opportunity(self.store,cursor=cur,workspace_id=wid,actor_id=actor,
                                     opportunity=op,state=self._workspace_state(cur,wid),mutation=True)
                # The gap has a DB-stamped availability later than the earlier cutoff.
                cur.execute('SELECT clock_timestamp()'); op_now=contracts.iso(cur.fetchone()[0])
                linked = self.store.put_manifest(scope,refs+[{'scope_key':scope,'node_id':gap_node}],
                    decision_cutoff=op_now,available_at=op_now,retention_until=data['expires_at'],
                    recipe={'whitespace_id':tid,'whitespace_revision':previous+1,'input_digest':data['input_digest']},cursor=cur)
                self.store.put_projection({'scope_key':scope,'kind':'opportunity','object_id':op['id'],'revision':op['revision'],
                    'manifest_id':linked['manifest_id'],'method_id':method['method_id'],'method_version':method['version'],
                    'decision_cutoff':op_now,'available_at':op_now,'retention_until':data['expires_at'],
                    'context_digest':data['context_digest'],'payload':op},expected_revision=op['revision']-1,cursor=cur)
            return {'state':'stored','object_id':tid,'revision':previous+1}

    @staticmethod
    def _workspace_state(cur, workspace_id):
        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR SHARE',(workspace_id,))
        found=cur.fetchone()
        if not found: raise TrendStorageError('workspace_access_denied')
        return json.loads(found[0]) if isinstance(found[0],str) else found[0]

    def current_result(self, workspace_id, actor_id, trend_id, *, cursor):
        wid, actor, tid = map(contracts.uuid, (workspace_id, actor_id, trend_id))
        if not self._enabled(wid): return None
        saved = self.store.get_projection(wid, actor, 'whitespace', tid, cursor=cursor)
        if (not saved or saved['validity'] != 'valid' or saved['scope_key'] != 'workspace:'+wid
                or saved['payload'].get('schema_version') != SCHEMA
                or saved.get('policy', {}).get('display_excerpt') is not True): return None
        try:
            state=self._workspace_state(cursor,wid)
            _validate_binding(self.store,cursor,wid,actor,state,saved['payload'].get('_admission_binding'))
        except (AlphaError,ValueError,KeyError,TypeError):
            return None
        return {k:deepcopy(v) for k,v in saved['payload'].items() if not k.startswith('_')}

    def plan_current(self, *, max_workspaces=1, trend_limit=2):
        if type(max_workspaces) is not int or not 1 <= max_workspaces <= 2 or type(trend_limit) is not int or not 1 <= trend_limit <= 2:
            raise TrendStorageError('whitespace_plan_bound')
        result = {'state':'disabled','workspaces':0,'stored':0,'reused':0,'unavailable':0}
        if not all(config.enabled(n,self.values) for n in ('INTELLIGENCE','RADAR','TRUST_RECEIPTS','WHITESPACE')): return result
        allowed = config.admitted_workspaces(self.values)
        if not allowed: return result
        with self.store.transaction() as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('trend-whitespace-plan-v1',0))")
            if not cur.fetchone()[0]: return {**result,'state':'busy'}
            cur.execute("""SELECT w.id::text,a.user_id::text FROM public.pr_workspaces w
                LEFT JOIN public.pr_trend_provider_cursors r ON r.scope_key='workspace:'||w.id::text AND r.provider_id=%s AND r.partition_key=%s
                JOIN LATERAL(SELECT m.user_id FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id
                    WHERE m.workspace_id=w.id AND m.status='active' AND m.role IN ('owner','editor') AND p.deleted_at IS NULL
                    ORDER BY(m.role='owner') DESC,m.user_id LIMIT 1) a ON true
                WHERE w.id=ANY(%s::uuid[]) AND NOT w.state ? 'accountDeletion'
                    AND coalesce(w.state->'workspace'->>'sample','false')<>'true'
                ORDER BY r.updated_at NULLS FIRST,w.id LIMIT %s""", (SCAN_PROVIDER,SCAN_PARTITION,allowed,max_workspaces))
            for wid, actor in cur.fetchall():
                if not self._enabled(wid): continue
                scope='workspace:'+wid
                self.store.ensure_scope(scope,cursor=cur)
                cur.execute('INSERT INTO public.pr_trend_provider_cursors(scope_key,provider_id,partition_key) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(scope,SCAN_PROVIDER,SCAN_PARTITION))
                cur.execute('SELECT cursor_value FROM public.pr_trend_provider_cursors WHERE scope_key=%s AND provider_id=%s AND partition_key=%s FOR UPDATE',(scope,SCAN_PROVIDER,SCAN_PARTITION))
                saved=cur.fetchone()[0] or {}; after=saved.get('after_object_id')
                now=contracts.iso(contracts.instant(self.clock()))
                cur.execute("""SELECT DISTINCT object_id::text FROM public.pr_trend_projections
                    WHERE scope_key=%s AND kind='whitespace_candidate' AND available_at<=%s AND retention_until>%s
                        AND (%s::uuid IS NULL OR object_id>%s::uuid) ORDER BY object_id::text LIMIT %s""",(scope,now,now,after,after,trend_limit+1))
                identities=[r[0] for r in cur.fetchall()]
                for tid in identities[:trend_limit]:
                    cur.execute('SAVEPOINT trend_whitespace_candidate')
                    try:
                        response=self.refresh(wid,actor,tid,cursor=cur)
                        if response['state'] in ('stored','reused'): result[response['state']]+=1
                    except (ValueError,KeyError,TypeError):
                        cur.execute('ROLLBACK TO SAVEPOINT trend_whitespace_candidate');result['unavailable']+=1
                    finally: cur.execute('RELEASE SAVEPOINT trend_whitespace_candidate')
                checkpoint={'after_object_id':identities[trend_limit-1] if len(identities)>trend_limit else None}
                cur.execute('UPDATE public.pr_trend_provider_cursors SET cursor_value=%s::jsonb,generation=generation+1,updated_at=clock_timestamp() WHERE scope_key=%s AND provider_id=%s AND partition_key=%s',(json.dumps(checkpoint),scope,SCAN_PROVIDER,SCAN_PARTITION))
                result['workspaces']+=1
        return {**result,'state':'local_only'}
