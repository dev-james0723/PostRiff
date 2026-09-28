"""Offline outcome calibration. Unknown labels never enter precision denominator."""
from collections import Counter, defaultdict
from math import sqrt
from statistics import median
import random
from .metrics import instant, metric, canonical_digest


def wilson_interval(successes, total, z=1.959963984540054):
    if type(total) is not int or type(successes) is not int or not 0 <= successes <= total or z != 1.959963984540054:
        raise ValueError('invalid binomial counts')
    if total == 0: return None
    p = successes/total
    denominator = 1+z*z/total
    center = (p+z*z/(2*total))/denominator
    radius = z*sqrt(p*(1-p)/total+z*z/(4*total*total))/denominator
    return {'lower': max(0,center-radius), 'upper': min(1,center+radius), 'level': .95}


def label_rising_outcome(prediction, future_windows, *, horizon_hours=12, required_windows=8, ratio_threshold=1.5, evaluated_at):
    """Separate post-seal pass using the frozen decision-time baseline and epoch."""
    from datetime import timedelta
    if prediction.get('decision_digest') != canonical_digest({k:v for k,v in prediction.items() if k != 'decision_digest'}):
        raise ValueError('seal decision before labelling outcomes; digest mismatch')
    if type(horizon_hours) is not int or not 1 <= required_windows <= horizon_hours or ratio_threshold <= 0:
        raise ValueError('invalid outcome method')
    cutoff = instant(prediction['decision_cutoff'])
    baseline = prediction['baseline']['baseline_rate']
    result = {'decision_digest': prediction['decision_digest'], 'method_version': prediction['method_version'],
              'outcome_method': {'version': 'rising-outcome-candidate-1', 'horizon_hours': horizon_hours,
                                 'required_windows': required_windows, 'ratio_threshold': ratio_threshold},
              'label': 'not_evaluable', 'reason': None, 'selected_windows': 0, 'qualifying_windows': 0}
    if baseline is None or baseline <= 0:
        return {**result, 'reason': 'insufficient_frozen_baseline'}
    if instant(evaluated_at) < cutoff+timedelta(hours=horizon_hours):
        return {**result, 'reason': 'incomplete_horizon'}
    slots = {}
    for row in future_windows:
        start = instant(row['window_start'])
        if not cutoff <= start < cutoff+timedelta(hours=horizon_hours): continue
        if instant(row.get('available_at',row['decision_cutoff'])) > instant(evaluated_at): continue
        if start in slots: return {**result, 'reason': 'ambiguous_future_revision'}
        slots[start] = row
    expected = [cutoff+timedelta(hours=i) for i in range(horizon_hours)]
    result['selected_windows'] = len(slots)
    if any(start not in slots for start in expected): return {**result, 'reason': 'incomplete_horizon'}
    for start in expected:
        row = slots[start]
        if (instant(row['window_end']) != start+timedelta(hours=1) or row.get('data_state') != 'qualified'
                or row['coverage'].get('availability') != 'available' or row['coverage'].get('completeness') != 'complete_within_scope'
                or row.get('comparison_digest') != prediction['comparison_digest'] or row['mention_rate']['value'] is None
                or row.get('verification_state') in ('inputs_deleted','policy_revoked','inputs_expired')
                or row.get('retention_until') and instant(row['retention_until']) <= instant(evaluated_at)):
            return {**result, 'reason': 'coverage_rights_or_comparability_gap'}
    count = sum(slots[start]['mention_rate']['value'] >= ratio_threshold*baseline for start in expected)
    hot = any(w.get('qualified_hot_threshold_crossed') is True for w in slots.values())
    return {**result, 'label': 'success' if count >= required_windows or hot else 'failure',
            'qualifying_windows': count, 'reason': 'qualified_hot_crossing' if hot else 'frozen_baseline_persistence'}


def _bootstrap(rows, *, iterations, seed):
    groups = defaultdict(list)
    for row in rows: groups[row['group_id']].append(row['label'] == 'success')
    if len(groups) < 2: return None
    rng = random.Random(seed); keys = sorted(groups); estimates = []
    for _ in range(iterations):
        sample = [v for _ in keys for v in groups[rng.choice(keys)]]
        estimates.append(sum(sample)/len(sample))
    estimates.sort()
    return {'lower': estimates[int(.025*(iterations-1))], 'upper': estimates[int(.975*(iterations-1))],
            'unit': 'group_block', 'groups': len(groups), 'iterations': iterations, 'seed': seed}


def calibrate_outcomes(rows, *, minimum_evaluable=50, bootstrap_iterations=500, seed=0, actual_negatives=None):
    if minimum_evaluable < 1 or bootstrap_iterations < 100: raise ValueError('invalid calibration settings')
    if any(r['label'] not in ('success','failure','not_evaluable') for r in rows): raise ValueError('unknown outcome label')
    if len({r['decision_digest'] for r in rows}) != len(rows): raise ValueError('duplicate prediction')
    if len({r.get('method_version') for r in rows}) > 1:
        raise ValueError('calibrate method versions separately')
    invalid_states = {'inputs_deleted','inputs_expired','policy_revoked','mismatch','method_unavailable'}
    invalidated = sum(r.get('verification_state') in invalid_states for r in rows)
    rows = [{**r, 'label': 'not_evaluable'} if r.get('verification_state') in invalid_states else r for r in rows]
    counts = Counter(r['label'] for r in rows)
    evaluated = [r for r in rows if r['label'] != 'not_evaluable']
    n = len(evaluated); successes = counts['success']
    precision = successes/n if n else None
    enough = n >= minimum_evaluable
    leads = [r['lead_time_hours'] for r in evaluated if r['label'] == 'success' and r.get('lead_time_hours') is not None]
    for v in leads: metric(v,'hours')
    fpr = None
    if actual_negatives is not None:
        negatives = actual_negatives['total']; fp = actual_negatives['false_positives']
        if type(negatives) is not int or type(fp) is not int or not 0 <= fp <= negatives: raise ValueError('invalid negative population')
        fpr = fp/negatives if negatives else None
    sensitivity = _bootstrap(evaluated,iterations=bootstrap_iterations,seed=seed) if evaluated and all(r.get('group_id') for r in evaluated) else None
    return {'selected': len(rows), 'invalidated': invalidated, 'evaluable': n, 'success': successes, 'failure': counts['failure'], 'unknown': counts['not_evaluable'],
            'precision': precision, 'precision_denominator': 'evaluable_positive_calls', 'wilson_95': wilson_interval(successes,n),
            'false_discovery_rate': 1-precision if precision is not None else None, 'false_positive_rate': fpr, 'recall': None,
            'clustered_bootstrap': sensitivity, 'median_lead_time_hours': median(leads) if leads else None, 'lead_time_sample_count': len(leads),
            'display_accuracy': {'precision': precision,'interval': wilson_interval(successes,n),'sample_size':n} if enough else None,
            'calibration_state': 'candidate_only' if enough else 'insufficient_sample', 'publication_state': 'shadow_only'}


def calibrate_cohorts(rows, *, cohort_keys=('platform','niche','language','region','discovery_route','stage','provider_mix'), **kwargs):
    from .metrics import canonical_digest
    groups = defaultdict(list)
    for row in rows:
        cohort = {k: row.get('cohort',{}).get(k) for k in cohort_keys}
        cohort['method_version'] = row.get('method_version')
        cohort['outcome_method_digest'] = canonical_digest(row.get('outcome_method'))
        groups[canonical_digest(cohort)].append((cohort,row))
    return [{'cohort': entries[0][0], **calibrate_outcomes([e[1] for e in entries],**kwargs)} for _,entries in sorted(groups.items())]
