"""Explicit creator assessment of a saved draft, never inferred semantic sameness."""
from . import contracts, opportunities


def record(state, actor_id, payload, now):
    required = {'variant_id', 'variant_revision', 'selection_digest', 'treatment_changed'}
    if not isinstance(payload, dict) or set(payload) != required or type(payload['treatment_changed']) is not bool:
        raise ValueError('treatment_assessment_required')
    variant = next((v for v in state.get('variants', []) if v['id'] == payload['variant_id']), None)
    if not variant or type(payload['variant_revision']) is not int or variant['revision'] != payload['variant_revision']:
        raise ValueError('treatment_saved_revision_required')
    bindings = variant.get('trendLineage', [])
    opportunities.validate_lineage(state, bindings, now)
    if not any(b.get('selection_digest') == payload['selection_digest'] for b in bindings):
        raise ValueError('treatment_selection_required')
    assessment = {**payload, 'text_digest': contracts.digest(variant.get('text', '')),
                  'lineage_digest': contracts.digest(bindings), 'reviewed_by': contracts.uuid(actor_id),
                  'reviewed_at': opportunities.iso(now), 'basis': 'creator_confirmed'}
    existing = [a for a in variant.get('trendTreatmentAssessments', [])
                if a.get('selection_digest') != payload['selection_digest']]
    variant['trendTreatmentAssessments'] = (existing + [assessment])[-6:]
    return assessment


def frozen(variant, now):
    """An edit/revision/selection change makes old assessments inapplicable."""
    bindings = variant.get('trendLineage', [])
    valid = {a.get('selection_digest'): a for a in variant.get('trendTreatmentAssessments', [])
             if a.get('variant_id') == variant.get('id') and a.get('variant_revision') == variant['revision']
             and a.get('text_digest') == contracts.digest(variant.get('text', ''))
             and a.get('lineage_digest') == contracts.digest(bindings)
             and a.get('basis') == 'creator_confirmed' and a.get('reviewed_by')
             and type(a.get('treatment_changed')) is bool
             and opportunities.epoch(a.get('reviewed_at')) <= now}
    states = [valid.get(b.get('selection_digest'), {}).get('treatment_changed') for b in bindings]
    if not states or any(value is None for value in states):
        return {}
    return {'treatmentChanged': any(states), 'treatmentAssessmentBasis': 'creator_confirmed',
            'treatmentAssessmentDigest': contracts.digest([valid[b['selection_digest']] for b in bindings])}
