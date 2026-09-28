"""Availability-time, scope and hour-of-week matched robust baselines."""
from copy import deepcopy
from datetime import timedelta
from statistics import median
from zoneinfo import ZoneInfo
from .metrics import canonical_digest, instant, metric


def build_baseline(history, *, current_window, decision_cutoff, minimum_windows=4, scale_floor=1.0, lookback_days=28, match_hour_of_week=True):
    if minimum_windows < 4 or scale_floor <= 0:
        raise ValueError('candidate baseline requires >=4 windows and positive scale_floor')
    metric(scale_floor, 'posts/hour')
    left = instant(current_window['window_start'])
    cutoff = instant(decision_cutoff)
    timezone = ZoneInfo(current_window['comparison_scope']['baseline_timezone'])
    local = left.astimezone(timezone)
    selected = {}
    signature = current_window['comparison_digest']
    for row in history:
        start, end = instant(row['window_start']), instant(row['window_end'])
        if end > left or start < left-timedelta(days=lookback_days) or instant(row.get('available_at', row['decision_cutoff'])) > cutoff:
            continue
        if not signature or row.get('comparison_digest') != signature or row.get('data_state') != 'qualified' or row['mention_rate']['value'] is None:
            continue
        if row['window_hours'] != current_window['window_hours']:
            continue
        local_start = start.astimezone(timezone)
        if match_hour_of_week and (local_start.weekday(), local_start.hour) != (local.weekday(), local.hour):
            continue
        key = (start, end)
        if key in selected and canonical_digest(selected[key]) != canonical_digest(row):
            raise ValueError('multiple baseline revisions; resolve snapshots at cutoff first')
        selected[key] = row
    rows = [selected[k] for k in sorted(selected)]
    # Overlapping windows are not independent historical samples.
    independent = []
    for row in rows:
        if not independent or instant(row['window_start']) >= instant(independent[-1]['window_end']):
            independent.append(row)
    rates = [r['mention_rate']['value'] for r in independent]
    for rate in rates:
        metric(rate, 'posts/hour')
    sufficient = len(rates) >= minimum_windows
    center = median(rates) if sufficient else None
    mad = median(abs(v-center) for v in rates) if sufficient else None
    result = {'baseline_rate': center, 'median': center, 'mad': mad, 'scale_floor': scale_floor,
              'scale': max(1.4826*mad, scale_floor) if sufficient else None,
              'sample_windows': len(rates), 'rates': rates, 'snapshot_refs': [r['snapshot_id'] for r in independent],
              'qualification': 'provisional' if sufficient else 'insufficient', 'reason': None if sufficient else 'insufficient_base',
              'comparison_digest': signature, 'comparison_scope': deepcopy(current_window['comparison_scope']),
              'decision_cutoff': decision_cutoff, 'lookback_days': lookback_days, 'match_hour_of_week': match_hour_of_week,
              'minimum_windows': minimum_windows}
    result['baseline_id'] = 'baseline_' + canonical_digest(result)
    return result
