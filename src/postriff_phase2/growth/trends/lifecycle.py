"""Frozen shadow-only lifecycle candidate with non-overlap and dwell hysteresis.

Inputs are window dictionaries from aggregate_window enriched with ``momentum``,
``baseline`` and optional measured ``episode_context``. No method promotion API.
"""
from copy import deepcopy
from .metrics import canonical_digest, instant

CANDIDATE_CONFIG = {
    'version': 'lifecycle-shadow-1', 'primary_hours': 1, 'minimum_dwell_hours': 1,
    'entry_windows': 2, 'known_author_floor': .8, 'largest_creator_share_ceiling': .35,
    'rising_entry_ratio': 1.5, 'rising_sustain_ratio': 1.2, 'breaking_ratio': 3,
    'breaking_anomaly': 4, 'hot_ratio': 2, 'peaking_ratio': 1.5,
    'declining_high_fraction': .7, 'evergreen_days': 28,
    'precedence': ['declining','saturated','breaking','peaking','hot','rising','emerging','evergreen']}
ALLOWED = {
    'emerging': {'rising','breaking'}, 'rising': {'hot','breaking','peaking','declining'},
    'breaking': {'hot','peaking','declining'}, 'hot': {'peaking','saturated','declining'},
    'peaking': {'hot','saturated','declining'}, 'saturated': {'declining'},
    'declining': {'emerging','rising'}, 'evergreen': {'emerging','rising'}}


def candidate_config():
    return deepcopy(CANDIDATE_CONFIG)


def _value(window, name):
    return window.get('momentum', {}).get(name, {}).get('value')


def _qualified(window, config):
    obs = window['observed']
    return (window.get('data_state') == 'qualified' and window['coverage'].get('availability') == 'available'
            and window['coverage'].get('completeness') == 'complete_within_scope'
            and window['window_hours'] == config['primary_hours']
            and window['mention_rate']['value'] is not None
            and obs['unknown_author_fraction'] is not None and 1-obs['unknown_author_fraction'] >= config['known_author_floor']
            and obs['largest_creator_share'] is not None and obs['largest_creator_share'] <= config['largest_creator_share_ceiling']
            and not window.get('episode_context', {}).get('duplication_surge_unresolved', False))


def evaluate_lifecycle(previous, windows, *, config=None):
    config = deepcopy(config or CANDIDATE_CONFIG)
    if config != CANDIDATE_CONFIG:
        raise ValueError('freeze another executable candidate version before changing thresholds')
    if not windows: raise ValueError('at least one window required')
    rows = sorted(windows, key=lambda w: (instant(w['window_end']), instant(w['window_start'])))
    current = rows[-1]
    prior = deepcopy(previous or {})
    if prior.get('as_of') and instant(prior['as_of']) > instant(current['decision_cutoff']):
        raise ValueError('future_lifecycle_state')
    if any(instant(w['window_end']) > instant(w['decision_cutoff']) for w in rows):
        raise ValueError('future_lifecycle_window')
    old = prior.get('candidate_stage')
    state = {**prior, 'stage': None, 'publication_state': 'shadow_only', 'method_version': config['version'],
             'method_config_digest': canonical_digest(config), 'candidate_stage': old,
             'data_state': current.get('data_state', 'insufficient'), 'stage_basis': [],
             'last_qualified_stage': prior.get('last_qualified_stage'), 'last_qualified_at': prior.get('last_qualified_at'),
             'as_of': current['decision_cutoff'], 'episode_id': current.get('episode_id', prior.get('episode_id'))}
    if not _qualified(current, config):
        state.update(candidate_stage=None, data_state=current.get('data_state') if current.get('data_state') != 'qualified' else 'insufficient',
                     stage_basis=['data_qualification_failed'], pending_stage=None)
        state['last_candidate_stage'] = old or prior.get('last_candidate_stage')
        return state
    state['data_state'] = 'provisional'  # Candidate method has not qualified for public claims.
    independent = []
    for row in reversed(rows):
        if not independent or instant(row['window_end']) <= instant(independent[-1]['window_start']): independent.append(row)
        if len(independent) == 2: break
    recent = list(reversed(independent))
    continuous = (len(recent) == 2 and all(_qualified(w,config) for w in recent)
                  and recent[0]['comparison_digest'] == current['comparison_digest']
                  and instant(recent[0]['window_end']) == instant(current['window_start']))
    context = current.get('episode_context', {})
    rate = current['mention_rate']['value']
    high = max(rate, prior.get('episode_high_rate', rate))
    state['episode_high_rate'] = high
    def predicate(stage, w):
        obs = w['observed']; ctx = w.get('episode_context', {})
        ratio, velocity, acc, anomaly = (_value(w,k) for k in ('burst_ratio','velocity','acceleration','robust_anomaly'))
        n, creators = obs['qualifying_original_count'], obs['known_creator_count']
        if stage == 'emerging': return ctx.get('first_episode') is True and n >= 10 and creators >= 5 and velocity is not None and velocity > 0
        if stage == 'rising': return n >= 20 and creators >= 10 and ratio is not None and ratio >= config['rising_entry_ratio'] and velocity is not None and velocity > 0
        if stage == 'breaking': return n >= 50 and creators >= 20 and ratio is not None and ratio >= 3 and anomaly is not None and anomaly >= 4 and acc is not None and acc > 0 and ctx.get('independent_community_count',0) >= 2
        if stage == 'hot': return ratio is not None and ratio >= 2 and ctx.get('historical_p90_qualified') is True and ctx.get('historical_p90') is not None and w['mention_rate']['value'] > ctx['historical_p90'] and velocity is not None and velocity >= 0
        if stage == 'peaking': return old in ('hot','breaking','peaking') and ratio is not None and ratio >= 1.5 and acc is not None and acc <= 0
        if stage == 'saturated': return False  # Reserved: duplicate ratio does not qualify topic saturation.
        if stage == 'declining': return old in ('rising','breaking','hot','peaking','saturated','declining') and velocity is not None and velocity < 0 and w['mention_rate']['value'] < .7*prior.get('episode_high_rate',high)
        if stage == 'evergreen': return ctx.get('recurrence_days',0) >= 28 and ratio is not None and .8 <= ratio <= 1.2 and anomaly is not None and abs(anomaly) < 1
        return False
    possible = [s for s in config['precedence'] if predicate(s,current) and (old is None or s == old or s in ALLOWED.get(old,set()))]
    if old in ('declining','evergreen'):
        possible = [s for s in possible if s == old or (context.get('new_episode') is True and state['episode_id'] != prior.get('episode_id'))]
    target = next((s for s in possible if continuous and all(predicate(s,w) for w in recent)), None)
    dwell_ok = not prior.get('entered_at') or (instant(current['window_end'])-instant(prior['entered_at'])).total_seconds() >= config['minimum_dwell_hours']*3600
    if target and target != old and dwell_ok:
        state.update(candidate_stage=target, entered_at=current['window_end'], pending_stage=None,
                     stage_basis=['two_nonoverlapping_qualified_windows', target + '_entry_predicate'])
        if state['episode_id'] != prior.get('episode_id'): state['episode_high_rate'] = rate
    elif (old == 'rising' and target is None and continuous and dwell_ok
          and all(_value(w, 'burst_ratio') is not None and _value(w, 'burst_ratio') < config['rising_sustain_ratio'] for w in recent)):
        state.update(candidate_stage=None, last_candidate_stage=old, pending_stage=None,
                     stage_basis=['two_windows_below_rising_sustain'])
    elif target == old and old is not None:
        state.update(stage_basis=[old + '_sustained'], pending_stage=None)
    else:
        ratio = _value(current,'burst_ratio')
        sustain = old == 'rising' and ratio is not None and ratio >= config['rising_sustain_ratio']
        # Stay through a pending exit; absence of a predicate never means Declining.
        state['stage_basis'] = ['rising_sustain_hysteresis' if sustain else 'awaiting_qualified_transition']
        state['pending_stage'] = possible[0] if possible else None
    state['last_window_end'] = current['window_end']
    state['repetition_heavy'] = continuous and all(w['observed']['qualifying_original_count'] >= 50 and w.get('episode_context',{}).get('redundancy_ratio',0) >= .6 for w in recent)
    return state
