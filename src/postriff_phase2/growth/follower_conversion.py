"""Provider-native conversion only. No currently admitted ingestion contract.

This registry is code-reviewed capability, never request data or a feature flag.
Adding a contract requires native ingestion, approved rights and scope evidence.
"""
from .scout_evidence import number

REVIEWED_CONTRACTS = {}


def qualified(provider, definition):
    return (provider, definition) in REVIEWED_CONTRACTS


def valid_choice(choice):
    return (choice.get('objective') != 'follower_conversion' or
            (qualified(choice.get('provider'), choice.get('definition_version'))
             and choice.get('metric') == 'follows' and choice.get('denominator_metric') == 'profile_visits'))


def measure(row):
    out = {'value': None, 'availability': 'unavailable', 'reason': 'native_contract_unavailable'}
    provider, version = row.get('provider'), row.get('definition')
    contract = REVIEWED_CONTRACTS.get((provider, version))
    if not contract:
        return out
    metrics = row.get('metrics') or {}
    pair = [metrics.get(n) for n in ('follows', 'profile_visits')]
    for name, metric in zip(('follows', 'profile_visits'), pair):
        if (not isinstance(metric, dict) or metric.get('coverage') != 'available'
                or not number(metric.get('value')) or metric['value'] < 0
                or not metric.get('receipt') or not number(metric.get('observedAt'))):
            return {**out, 'reason': 'native_metric_unavailable'}
        expected = {'provider': provider, 'account': row.get('account'), 'window': row.get('window'),
                    'definition': f'{provider}:{version}:{name}', 'attributionScope': contract['scope'],
                    'scopeId': row.get('providerPostId'), 'sourceEndpoint': contract['endpoint'], 'unit': 'count'}
        if any(not value or metric.get(key) != value for key, value in expected.items()):
            return {**out, 'reason': 'incompatible_native_contract'}
        if (not number(metric.get('periodStart')) or not number(metric.get('periodEnd'))
                or metric['periodEnd'] <= metric['periodStart'] or metric['observedAt'] < metric['periodEnd']):
            return {**out, 'reason': 'measurement_window_unavailable'}
    numerator, denominator = pair
    if any(numerator[k] != denominator[k] for k in ('periodStart', 'periodEnd')):
        return {**out, 'reason': 'incompatible_measurement_window'}
    if denominator['value'] <= 0:
        return {**out, 'reason': 'zero_denominator'}
    value = numerator['value'] / denominator['value']
    if not number(value):
        return {**out, 'reason': 'incompatible_native_contract'}
    return {'value': value, 'availability': 'available', 'reason': None}
