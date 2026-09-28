"""Deterministic rate/velocity/acceleration with explicit comparability gates."""
from .metrics import instant, metric


def compute_momentum(windows, baseline=None, *, minimum_baseline_rate=1.0):
    if not windows:
        raise ValueError('at least one window required')
    if minimum_baseline_rate < 0:
        raise ValueError('negative baseline floor')
    rows = sorted(windows, key=lambda w: instant(w['window_start']))
    current = rows[-1]
    rate = current['mention_rate']['value']
    result = {'mention_rate': dict(current['mention_rate']), 'window_hours': current['window_hours'],
              'comparison_digest': current['comparison_digest'], 'baseline_id': baseline.get('baseline_id') if baseline else None}
    for key, unit in [('rate_change', 'posts/hour'), ('velocity', 'posts/hour^2'), ('acceleration', 'posts/hour^3')]:
        result[key] = metric(None, unit, 'insufficient_windows')
    def comparable(items):
        return (all(w.get('comparison_digest') and w['comparison_digest'] == current['comparison_digest'] and w['mention_rate']['value'] is not None and w['window_hours'] == current['window_hours'] and instant(w['decision_cutoff']) <= instant(current['decision_cutoff']) for w in items)
                and all(instant(a['window_end']) == instant(b['window_start']) for a,b in zip(items, items[1:])))
    if len(rows) >= 2:
        if comparable(rows[-2:]):
            change = rate - rows[-2]['mention_rate']['value']
            result['rate_change'] = metric(change, 'posts/hour')
            result['velocity'] = metric(change/current['window_hours'], 'posts/hour^2')
        else:
            result['rate_change'] = metric(None, 'posts/hour', 'incomparable_windows')
            result['velocity'] = metric(None, 'posts/hour^2', 'incomparable_windows')
    if len(rows) >= 3:
        if comparable(rows[-3:]):
            older_velocity = (rows[-2]['mention_rate']['value']-rows[-3]['mention_rate']['value'])/current['window_hours']
            result['acceleration'] = metric((result['velocity']['value']-older_velocity)/current['window_hours'], 'posts/hour^3')
        else:
            result['acceleration'] = metric(None, 'posts/hour^3', 'incomparable_windows')
    reason = None
    if rate is None:
        reason = current['mention_rate'].get('reason') or 'missing_rate'
    elif not baseline or baseline.get('sample_windows', 0) < 4 or baseline.get('qualification') not in ('provisional', 'qualified'):
        reason = 'insufficient_base'
    elif instant(baseline['decision_cutoff']) > instant(current['decision_cutoff']):
        reason = 'future_baseline'
    elif baseline.get('comparison_digest') != current['comparison_digest']:
        reason = 'incomparable_baseline'
    elif baseline.get('baseline_rate') is None or baseline['baseline_rate'] <= 0 or baseline['baseline_rate'] < minimum_baseline_rate:
        reason = 'insufficient_base'
    b = baseline['baseline_rate'] if not reason else None
    result['growth_pct'] = metric(100*(rate/b-1) if b else None, 'percent_vs_baseline', reason)
    result['burst_ratio'] = metric(rate/b if b else None, 'ratio', reason)
    result['robust_anomaly'] = metric((rate-baseline['median'])/baseline['scale'] if b and baseline.get('scale', 0)>0 else None, 'robust_scale_units', reason or (None if baseline and baseline.get('scale', 0)>0 else 'insufficient_scale'))
    result['baseline_rate'] = {**metric(b, 'posts/hour', reason),
                               'sample_windows': baseline.get('sample_windows', 0) if baseline else 0,
                               'qualification': baseline.get('qualification', 'insufficient') if baseline else 'insufficient'}
    result['growth_pct'].update(numerator=rate-b if b else None, denominator=b)
    result['robust_anomaly'].update(median=baseline.get('median') if b else None,
                                   mad=baseline.get('mad') if b else None,
                                   scale_floor=baseline.get('scale_floor') if b else None)
    result['current_window'] = {'start':current['window_start'], 'end':current['window_end']}
    result['comparison_window'] = {'start':rows[-2]['window_start'], 'end':rows[-2]['window_end']} if len(rows)>1 else None
    result['minimum_baseline_rate'] = minimum_baseline_rate
    return result
