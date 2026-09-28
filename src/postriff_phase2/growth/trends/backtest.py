"""Sealed availability-time replay and leakage-resistant time/group partitions."""
from copy import deepcopy
from datetime import timedelta
from .metrics import canonical_digest, instant


def seal_decision(decision):
    body = {k:v for k,v in decision.items() if k != 'decision_digest'}
    return {**deepcopy(body), 'decision_digest': canonical_digest(body)}


def replay(observations, memberships, cutoffs, *, decide, method_artifacts, source_policies):
    """Invoke a supplied pure decision function on then-visible inputs only.

    ``decide`` receives observations/memberships/decision_cutoff/method_artifacts/
    source_policies keyword args. It must use this isolated context, not a closure
    containing future data. Returned decisions are frozen before outcome labels.
    """
    decisions = []
    for cutoff in sorted(set(cutoffs), key=instant):
        visible = sorted((deepcopy(r) for r in observations if instant(r['available_at']) <= instant(cutoff)),
                         key=lambda r: (instant(r['available_at']), r.get('stable_ingestion_sequence',r['revision_sequence']), r['observation_id']))
        members = sorted((deepcopy(m) for m in memberships if instant(m['available_at']) <= instant(cutoff)),
                         key=lambda m: (instant(m['available_at']),m['revision_sequence'],m['event_id']))
        policies = [deepcopy(p) for p in source_policies if instant(p.get('available_at',p['effective_at'])) <= instant(cutoff)]
        methods = [deepcopy(m) for m in method_artifacts if instant(m['available_at']) <= instant(cutoff)]
        context = {'observations': visible, 'memberships': members, 'decision_cutoff': cutoff,
                   'method_artifacts': methods, 'source_policies': policies}
        result = decide(**deepcopy(context))
        if result.get('decision_cutoff',cutoff) != cutoff: raise ValueError('decision cutoff changed')
        decisions.append(seal_decision({**result, 'decision_cutoff': cutoff, 'replay_input_digest': canonical_digest(context)}))
    return decisions


def time_embargo_split(rows, *, holdout_start, longest_horizon_hours=12, embargo_hours=12):
    """Untouched final time block; purge all train groups connected to holdout.

    Each row requires group_ids containing topic, recurrence and known duplicate
    family IDs; these are benchmark partition metadata, never decision features.
    """
    if embargo_hours < longest_horizon_hours or longest_horizon_hours <= 0: raise ValueError('embargo shorter than outcome horizon')
    boundary = instant(holdout_start); train_end = boundary-timedelta(hours=embargo_hours)
    if any(not r.get('group_ids') for r in rows): raise ValueError('leakage grouping required')
    holdout = [r for r in rows if instant(r['decision_cutoff']) >= boundary]
    protected = {g for r in holdout for g in r['group_ids']}
    # Connected groups can leak transitively via another topic/creator family.
    changed = True
    while changed:
        size = len(protected)
        for row in rows:
            if protected.intersection(row['group_ids']): protected.update(row['group_ids'])
        changed = size != len(protected)
    train, purged = [], []
    for row in rows:
        if instant(row['decision_cutoff']) >= boundary: continue
        if instant(row['decision_cutoff']) >= train_end or protected.intersection(row['group_ids']): purged.append(row)
        else: train.append(row)
    order = lambda r: (instant(r['decision_cutoff']),r['prediction_id'])
    return {'train': deepcopy(sorted(train,key=order)), 'holdout': deepcopy(sorted(holdout,key=order)),
            'purged': deepcopy(sorted(purged,key=order)), 'embargo_hours': embargo_hours,
            'split_digest': canonical_digest({'rows': sorted(rows,key=order),'holdout_start':holdout_start,'embargo_hours':embargo_hours})}
