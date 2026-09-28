"""Immutable JSON method registry. Registration never promotes a method.

Executable digests are supplied by the build/loader from the actual code artifact;
this pure registry does not read files or execute formula strings.
"""
from copy import deepcopy
import re
from .metrics import canonical_digest


def make_method(name, version, *, implementation_digest, config, algorithm_id):
    if not name or not version or not algorithm_id or not re.fullmatch(r'[0-9a-f]{64}', implementation_digest):
        raise ValueError('method requires name/version/algorithm and SHA256 executable digest')
    artifact = {'name': name, 'version': version, 'algorithm_id': algorithm_id,
                'implementation_digest': implementation_digest, 'config': deepcopy(config),
                'publication_state': 'shadow_only', 'qualification': 'unqualified'}
    artifact['artifact_digest'] = canonical_digest(artifact)
    return artifact


def validate_method(artifact):
    body = {k: v for k,v in artifact.items() if k != 'artifact_digest'}
    if canonical_digest(body) != artifact.get('artifact_digest'):
        raise ValueError('method artifact digest mismatch')
    if artifact.get('publication_state') != 'shadow_only' or artifact.get('qualification') != 'unqualified':
        raise ValueError('this candidate registry cannot promote methods')
    if not re.fullmatch(r'[0-9a-f]{64}', artifact.get('implementation_digest', '')):
        raise ValueError('missing executable digest')
    return True


def register_method(registry, artifact):
    validate_method(artifact)
    key = artifact['name'] + ':' + artifact['version']
    if key in registry and registry[key] != artifact:
        raise ValueError('immutable method version conflict')
    return {**deepcopy(registry), key: deepcopy(artifact)}


def resolve_method(registry, name, version, artifact_digest=None):
    artifact = registry.get(name + ':' + version)
    if artifact is None:
        return None
    validate_method(artifact)
    if artifact_digest is not None and artifact['artifact_digest'] != artifact_digest:
        return None
    return deepcopy(artifact)


def metric_definitions():
    formulas = {
        'mention_rate': ('eligible_original_count / window_hours', 'posts/hour', 1),
        'rate_change': ('current_rate - previous_rate', 'posts/hour', 2),
        'velocity': ('rate_change / center_elapsed_hours', 'posts/hour^2', 2),
        'acceleration': ('(velocity - previous_velocity) / center_elapsed_hours', 'posts/hour^3', 3),
        'growth_pct': ('100 * (current_rate / baseline_rate - 1)', 'percent_vs_baseline', 4),
        'burst_ratio': ('current_rate / baseline_rate', 'ratio', 4),
        'robust_anomaly': ('(current_rate - median) / max(1.4826 * MAD, scale_floor)', 'robust_scale_units', 4),
    }
    return {key: {'id': key, 'display_name': key.replace('_', ' '), 'formula': formula,
                  'units': unit, 'eligible_source_types': ['raw_post', 'owned_post'],
                  'current_window': 'explicit_half_open_utc', 'baseline_rule': 'preceding_28_days_same_hour_of_week',
                  'minimum_sample_windows': n, 'missing_data_behavior': 'null_with_reason',
                  'cap_behavior': 'unclamped_finite', 'version': 'candidate-1',
                  'test_vectors': 'synthetic_60_90_150_baseline_50'}
            for key, (formula, unit, n) in formulas.items()}
