"""Inspectable claim-specific support; never an outcome probability."""
from copy import deepcopy
from .metrics import metric


def assess_confidence(window, *, cluster_cohesion=None, provider_reliability=None, corroboration=None, interpretation=None, workspace_fit=None):
    for value in (cluster_cohesion, provider_reliability):
        if value is not None:
            metric(value, 'support_component')
            if not 0 <= value <= 1: raise ValueError('support_component_out_of_range')
    obs, coverage = window['observed'], window['coverage']
    components = {'source_coverage': deepcopy(coverage), 'sample_size': obs['qualifying_original_count'],
                  'known_creator_count': obs['known_creator_count'],
                  'unknown_author_fraction': obs['unknown_author_fraction'], 'largest_creator_share': obs['largest_creator_share'],
                  'cluster_cohesion': cluster_cohesion, 'freshness': coverage.get('availability', 'unknown'),
                  'metric_completeness': window['mention_rate']['value'] is not None,
                  'cross_source_corroboration': corroboration, 'provider_reliability': provider_reliability,
                  'historical_calibration': 'unqualified'}
    caps = []
    if window.get('data_state') != 'qualified': caps.append('coverage_or_measurement_gap')
    if obs['qualifying_original_count'] < 20: caps.append('small_sample')
    if obs['known_creator_count'] < 10: caps.append('creator_diversity_low')
    if obs['unknown_author_fraction'] is None or obs['unknown_author_fraction'] > .2: caps.append('author_coverage_low')
    if obs['largest_creator_share'] is None or obs['largest_creator_share'] > .35: caps.append('highly_concentrated')
    if cluster_cohesion is None or cluster_cohesion < .8: caps.append('semantic_support_unqualified')
    if provider_reliability is None or provider_reliability < .8: caps.append('provider_reliability_unqualified')
    return {'measurement_quality': {'level': 'low' if caps else 'moderate', 'components': components, 'cap_reasons': caps},
            'lifecycle_support': {'level': 'unqualified', 'calibration_state': 'unqualified', 'probability': None},
            'semantic_interpretation': deepcopy(interpretation), 'workspace_fit': deepcopy(workspace_fit)}
