"""Adapt actual generation envelopes to evidence maps; qualification is independent."""
from copy import deepcopy
import uuid
from . import contracts, text_context
from .generation import current_annotations
from .store import TrendStorageError

TASKS = ('semantic_label_generate', 'culture_explain')


def review_id(workspace_id, kind, model, task, cohort):
    return str(uuid.uuid5(uuid.UUID(workspace_id), contracts.canonical(['trend-semantic-review-v1', kind, model, task, cohort])))


def load(store, cur, *, workspace_id, actor_id, receipt_id, state, inputs, values, expected=None):
    """No generation call. Freeze exact current cached outputs and reviewed gates.

    Review records are separate operator-controlled, production-method artifacts;
    generated prose, native probability and a verified source receipt cannot
    create any of these qualifications. All absence paths remain lexical.
    """
    results, bindings, refs = [], [], []
    cohort = inputs['frame']['platform'] + ':' + inputs['frame']['language']
    for task in TASKS:
        found = current_annotations(store, workspace_id=workspace_id, actor_id=actor_id,
            receipt_id=receipt_id, state=state, task=task, cursor=cur, values=values)
        if not found:
            continue
        projection, result = found['projection'], found['result']
        # The generation envelope contains no computation timestamp. Use actual
        # immutable storage availability, including later qualification records.
        current = store.get_projection(workspace_id, actor_id, 'model_judgment', projection['object_id'],
            revision=projection['revision'], cursor=cur)
        if (not current or current['validity'] != 'valid'
                or current['projection_id'] != projection['projection_id'] or not current.get('available_at')):
            raise TrendStorageError('advanced_annotation_availability_missing')
        projection = current
        reviewed = []
        for kind in ('model_qualification', 'task_qualification', 'cohort_qualification'):
            oid = review_id(workspace_id, kind, result['executed_model'], task, cohort)
            review = store.get_projection(workspace_id, actor_id, kind, oid, cursor=cur)
            p = review.get('payload', {}) if review else {}
            if (not review or review['validity'] != 'valid' or review['scope_key'] != 'workspace:' + workspace_id
                    or p.get('state') != 'qualified' or not p.get('review_ref') or not p.get('reviewed_by')
                    or not p.get('evaluation_digest') or p.get('fixture') is not False
                    or any(p.get(k) != v for k,v in {'model_id':result['executed_model'], 'task':task, 'cohort':cohort}.items())):
                break
            cur.execute('SELECT qualification,revoked_at,config FROM public.pr_trend_method_versions WHERE method_id=%s AND version=%s FOR SHARE',
                        tuple(review['method_bundle'][k] for k in ('method_id','version')))
            status = cur.fetchone()
            gate = (status[2].get('semantic_admission') or {}) if status else {}
            if (not status or status[0] != 'qualified' or status[1] is not None
                    or gate.get('state') != 'production' or gate.get('role') != kind
                    or any(gate.get(k) != v for k,v in {'model_id':result['executed_model'], 'task':task, 'cohort':cohort}.items())):
                break
            reviewed.append(review)
        if len(reviewed) != 3:
            reviewed = []
        all_rows = [projection] + reviewed
        binding = {'task':task, 'cohort':cohort, 'projection_digest':contracts.digest(projection['payload']), 'object_id':projection['object_id'], 'revision':projection['revision'],
            'result_digest':contracts.digest(result), 'qualification_refs':[
                {'kind':r['kind'], 'object_id':r['object_id'], 'revision':r['revision'], 'digest':contracts.digest(r['payload'])} for r in reviewed]}
        bindings.append(binding)
        store.lock_dependencies(workspace_id, actor_id, [
            {k:r[k] for k in ('kind','object_id','revision')} for r in all_rows], cursor=cur)
        refs.extend({'scope_key':r['scope_key'], 'node_id':r['projection_id']} for r in all_rows)
        results.append({'task':task, 'result':result, 'qualified':bool(reviewed),
            'available_at':contracts.iso(max((contracts.instant(r['available_at']) for r in all_rows))),
            'expires_at':min([r['expires_at'] for r in all_rows], key=contracts.instant)})
    if expected is not None and bindings != expected:
        raise TrendStorageError('advanced_annotation_binding_changed')
    return results, bindings, refs


def adapt(inputs, selected, now):
    """Current interpretation, with order-independent abstention on conflicts.

    Original source eligibility stays at the receipt cutoff. Model knowledge has
    its own real timestamp: no later interpretation is backdated into the seal.
    Candidates retain all interpretations; only unambiguous reviewed evidence
    becomes an annotation or a genome dimension.
    """
    reconstructed, _ = text_context.reconstruct(inputs)
    sources = {s['source_id']:s for s in inputs['common']['sources']}
    annotations, dimensions, candidates, conflicts = [], {}, [], []
    expiry = inputs['expires_at']
    seed_options, dimension_options = {}, {}
    at = contracts.instant(now)
    for entry in selected:
        result = entry['result']
        if result.get('task') != 'trend.' + entry['task'] or result.get('status') != 'ok':
            raise TrendStorageError('advanced_annotation_result_invalid')
        computed = result.get('computed_at')
        available = entry.get('available_at', computed)
        # Missing knowledge time cannot support a qualified current claim.
        current = bool(available and (computed is None or contracts.instant(computed) <= at)
            and contracts.instant(available) <= at and contracts.instant(entry['expires_at']) > at)
        expiry = min([expiry, entry['expires_at']], key=contracts.instant)
        for item in result['items']:
            spans = item['evidence_spans']; refs = sorted({s['observation_id'] for s in spans})
            for span in spans:
                sid = span['observation_id']; text = inputs['facts'].get(sid, {}).get('text')
                source = sources.get(sid, {})
                if (sid not in sources or any(source.get('rights', {}).get(op) is not True for op in ('analysis','llm','creative'))
                        or source.get('language') != item.get('language')
                        or source.get('platform') != inputs['frame']['platform']
                        or contracts.instant(source['available_at']) > contracts.instant(inputs['common']['decision_cutoff'])
                        or contracts.instant(source['expires_at']) <= at
                        or not isinstance(text,str) or type(span['start']) is not int or type(span['end']) is not int
                        or not 0<=span['start']<span['end']<=len(text) or text[span['start']:span['end']] != span['text']):
                    raise TrendStorageError('advanced_annotation_span_mismatch')
            qualified = entry['qualified'] is True and current
            candidate = {**deepcopy(item), 'task':entry['task'], 'model_id':result['executed_model'],
                'qualification':'cohort_qualified' if qualified else 'unqualified',
                'available_at':available, 'computed_at':computed,
                'origin':'unknown', 'derivation_kind':'model_interpretation'}
            candidates.append(candidate)
            if not qualified:
                continue
            support = {'evidence_refs':refs, 'available_at':max([v for v in (computed,available) if v],key=contracts.instant),
                'expires_at':expiry, 'derivation_kind':'model_interpretation', 'method_version':result['input_digest'],
                'confidence_basis':'Reviewed model/task/language cohort. ' + ' '.join(item['uncertainties']),
                'review_status':'cohort_reviewed'}
            if entry['task'] == 'culture_explain':
                dimension_options.setdefault('language_cultural_usage', []).append(
                    {**support, 'value':item['explanation'], 'contradictions':item['alternatives']})
                continue
            dimension_options.setdefault('topic_narrative', []).append(
                {**support, 'value':item['claim'], 'concept':item['concept'], 'stance':item['stance'], 'contradictions':[]})
            if len(item['concept']) > 500 or len(item['claim']) > 500:
                continue
            for seed in reconstructed['seeds']:
                if not set(seed['evidence_refs']) <= set(refs):
                    continue
                # A span elsewhere in the same post cannot label this seed.
                if not all(any(p['observation_id']==s['source_id'] and p['start']<=s['start']
                        and p['end']>=s['end'] for p in spans) for s in seed['original_spans']):
                    continue
                seed_options.setdefault(seed['seed_id'], []).append({**deepcopy(seed), **support,
                    'evidence_refs':seed['evidence_refs'], 'concept':item['concept'], 'claim':item['claim'],
                    'stance':{'supports':'support','opposes':'oppose','mixed':'mixed'}.get(item['stance'],'unknown')})
    def merged(rows):
        value = deepcopy(sorted(rows,key=contracts.canonical)[0])
        value['evidence_refs'] = sorted({r for row in rows for r in row['evidence_refs']})
        value['available_at'] = max((r['available_at'] for r in rows),key=contracts.instant)
        value['expires_at'] = min((r['expires_at'] for r in rows),key=contracts.instant)
        value['method_version'] = contracts.digest(sorted({r['method_version'] for r in rows}))
        return value
    for seed_id, rows in sorted(seed_options.items()):
        labels = {(r['concept'],r['claim'],r['stance']) for r in rows}
        if len(labels) != 1:
            conflicts.append({'seed_id':seed_id,'reason':'conflicting_reviewed_interpretations',
                'evidence_refs':sorted({x for r in rows for x in r['evidence_refs']})})
        else:
            annotations.append(merged(rows))
    for name, rows in sorted(dimension_options.items()):
        labels = {(r['value'],r.get('concept'),r.get('stance')) for r in rows}
        if len(labels) == 1:
            dimensions[name] = merged(rows)
        else:
            conflicts.append({'dimension':name,'reason':'multiple_reviewed_interpretations',
                'evidence_refs':sorted({x for r in rows for x in r['evidence_refs']})})
    return {'dimensions':dimensions, 'annotations':annotations,
        'candidates':sorted(candidates,key=contracts.canonical), 'conflicts':conflicts,
        'expires_at':expiry, 'source_decision_cutoff':inputs['common']['decision_cutoff'], 'decision_cutoff':now}


def validate_current(store, cur, workspace_id, actor_id, state, bindings):
    """Read-only current review-head/registry/context check, including viewers.

    Does not reconstruct prompts or call the generation worker's edit-only lock.
    Durable generic DAG validity alone does not imply production qualification.
    """
    from .generation import workspace_context
    if not isinstance(bindings,list) or len(bindings)>len(TASKS):
        raise TrendStorageError('advanced_annotation_binding_invalid')
    for bound in bindings:
        if bound.get('task') not in TASKS:
            raise TrendStorageError('advanced_annotation_binding_invalid')
        projection=store.get_projection(workspace_id,actor_id,'model_judgment',bound['object_id'],cursor=cur)
        if (not projection or projection['validity']!='valid' or projection['scope_key']!='workspace:'+workspace_id
                or projection['revision']!=bound['revision'] or projection.get('policy',{}).get('llm_process') is not True
                or contracts.digest(projection['payload'])!=bound['projection_digest']):
            raise TrendStorageError('advanced_annotation_binding_changed')
        result=projection['payload']['result']
        context=workspace_context(state,{'model':result['executed_model']})
        if projection['payload'].get('context_revision')!=context['revision']:
            raise TrendStorageError('advanced_annotation_context_changed')
        reviews=bound.get('qualification_refs')
        if not isinstance(reviews,list) or len(reviews) not in (0,3):
            raise TrendStorageError('advanced_annotation_binding_invalid')
        expected={'model_qualification','task_qualification','cohort_qualification'}
        if reviews and {r['kind'] for r in reviews}!=expected:
            raise TrendStorageError('advanced_annotation_binding_invalid')
        for ref in reviews:
            review=store.get_projection(workspace_id,actor_id,ref['kind'],ref['object_id'],cursor=cur)
            if (not review or review['validity']!='valid' or review['scope_key']!='workspace:'+workspace_id
                    or review['revision']!=ref['revision'] or contracts.digest(review['payload'])!=ref['digest']):
                raise TrendStorageError('advanced_annotation_review_changed')
            payload=review['payload']
            if (payload.get('state')!='qualified' or payload.get('fixture') is not False
                    or not all(payload.get(k) for k in ('reviewed_by','review_ref','evaluation_digest'))):
                raise TrendStorageError('advanced_annotation_review_changed')
            store._actor(cur,workspace_id,payload['reviewed_by'],write=True)
            cur.execute('SELECT qualification,revoked_at,config FROM public.pr_trend_method_versions WHERE method_id=%s AND version=%s FOR SHARE',
                tuple(review['method_bundle'][k] for k in ('method_id','version')))
            status=cur.fetchone();gate=(status[2].get('semantic_admission') or {}) if status else {}
            identity={'model_id':result['executed_model'],'task':bound['task'],'cohort':bound['cohort']}
            if (not status or status[0]!='qualified' or status[1] is not None
                    or gate.get('state')!='production' or gate.get('role')!=ref['kind']
                    or any(payload.get(k)!=v or gate.get(k)!=v for k,v in identity.items())):
                raise TrendStorageError('advanced_annotation_review_changed')
