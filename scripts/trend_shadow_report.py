#!/usr/bin/env python3
"""Pair verified sealed replay decisions; label measured outcomes in a separate pass."""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import sys

from trend_verify_receipt import (OperatorError, bounded_list, contracts, envelope, finish,
    packs, pairing_digest, parser, read_json, refuse_network, rights_snapshot, run, verify_pack)
sys.addaudithook(refuse_network)
from postriff_phase2.growth.trends import backtest, calibration


def read_decisions(path, args, trust):
    document = read_json(path)
    if document.get('schema') != 'rafii.trend-replay-report.v1' or document.get('scope_key') != args.scope:
        raise OperatorError('sealed_replay_report_required')
    results = []
    for decision in bounded_list(document.get('decisions'), 'decisions', 48):
        if decision.get('state') != 'verified':
            results.append({'state': decision.get('state', 'pending')})
            continue
        if backtest.seal_decision(decision) != decision:
            raise OperatorError('sealed_decision_digest_mismatch')
        checked, pack = verify_pack(decision['bundle'], args, trust)
        if checked['state'] != 'verified':
            results.append({'state': checked['state'], 'reason': checked.get('reason', checked['state'])})
            continue
        receipt = pack['receipt']
        if (receipt['decision_cutoff'] != decision['decision_cutoff'] or receipt['trend_id'] != decision['trend_id']
                or receipt['episode_id'] != decision['episode_id'] or receipt['inferred']['candidate_stage'] != decision['candidate_stage']
                or contracts.digest(pack['manifest']['method_artifacts']) != decision['method_bundle_digest']
                or not decision.get('group_ids')):
            raise OperatorError('decision_receipt_binding_mismatch')
        if decision.get('pairing_digest') != pairing_digest(pack):
            raise OperatorError('pairing_digest_mismatch')
        results.append({**decision, 'bundle': pack})
    return results


def future_windows(path, args, trust):
    selected = packs(read_json(path))
    if len(selected) > 200:
        raise OperatorError('outcome_bundle_bound')
    windows = {}
    unavailable = Counter()
    for pack in selected:
        checked, pack = verify_pack(pack, args, trust)
        if checked['state'] != 'verified':
            unavailable[checked['state']] += 1
            continue
        receipt, manifest = pack['receipt'], pack['manifest']
        for window in manifest['normalized_inputs']['windows']:
            key = (receipt['episode_id'], window['comparison_digest'], window['window_start'], window['window_end'])
            current = windows.get(key)
            row = {**window, 'available_at': receipt['computed_at'], 'verification_state': 'verified'}
            if current is None or contracts.instant(row['available_at']) > contracts.instant(current['available_at']):
                windows[key] = row
            elif row['available_at'] == current['available_at'] and row != current:
                raise OperatorError('ambiguous_outcome_revision')
    return windows, dict(sorted(unavailable.items()))


def side_report(decisions, outcome_windows, args):
    valid = [d for d in decisions if d['state'] == 'verified']
    partitions = [{'prediction_id': d['decision_digest'], 'decision_cutoff': d['decision_cutoff'],
                   'group_ids': d['group_ids']} for d in valid]
    if len({r['prediction_id'] for r in partitions}) != len(partitions):
        raise OperatorError('duplicate_prediction')
    split = backtest.time_embargo_split(partitions, holdout_start=args.holdout_start,
                                       longest_horizon_hours=12, embargo_hours=args.embargo_hours)
    holdout = {r['prediction_id'] for r in split['holdout']}
    outcome_rows = []
    stage_counts = Counter(d['candidate_stage'] or 'abstain' for d in valid)
    for d in valid:
        if d['decision_digest'] not in holdout or d['candidate_stage'] != 'rising':
            continue
        manifest = d['bundle']['manifest']
        current = manifest['normalized_inputs']['windows'][-1]
        scope = current['comparison_scope']
        prediction = backtest.seal_decision({'decision_cutoff': d['decision_cutoff'],
            'baseline': manifest['normalized_inputs']['baseline'], 'comparison_digest': current['comparison_digest'],
            'method_version': d['method_bundle_digest']})
        # Receipt availability includes current rights/revisions. No caller-authored
        # success labels, engagement totals or model judgements enter this list.
        future = [w for key, w in outcome_windows.items() if key[0] == d['episode_id'] and key[1] == current['comparison_digest']]
        label = calibration.label_rising_outcome(prediction, future, evaluated_at=args.at)
        outcome_rows.append({**label, 'decision_digest': d['decision_digest'],
            'group_id': contracts.digest(sorted(d['group_ids'])),
            'cohort': {'platform': scope['platform'], 'language': scope['language'], 'niche': scope.get('community'),
                       'region': None, 'discovery_route': scope.get('sampling_method'), 'stage': 'rising',
                       'provider_mix': [scope['provider_id']]}})
    by_method = defaultdict(list)
    for result in outcome_rows:
        by_method[result['method_version']].append(result)
    return {'selected_decisions': len(decisions), 'verified_decisions': len(valid),
            'unavailable_states': dict(sorted(Counter(d['state'] for d in decisions if d['state'] != 'verified').items())),
            'candidate_stage_counts': dict(sorted(stage_counts.items())),
            'partition': {k: len(split[k]) for k in ('train', 'holdout', 'purged')},
            'embargo_hours': split['embargo_hours'], 'split_digest': split['split_digest'],
            'calibration_population': 'verified_rising_candidate_calls_in_untouched_holdout',
            'outcomes': outcome_rows,
            'methods': [{'method_bundle_digest': method, **calibration.calibrate_outcomes(rows, seed=0)}
                        for method, rows in sorted(by_method.items())],
            'cohorts': calibration.calibrate_cohorts(outcome_rows, seed=0)}


def main():
    p = parser('Offline shadow comparison with sealed decisions, verified future windows and time/group embargo.')
    p.add_argument('--baseline', required=True, type=Path, help='Baseline replay-report JSON')
    p.add_argument('--candidate', required=True, type=Path, help='Candidate replay-report JSON')
    p.add_argument('--outcomes', required=True, type=Path, help='Complete future receipt bundles; never prelabelled outcomes')
    p.add_argument('--holdout-start', required=True)
    p.add_argument('--embargo-hours', type=int, default=12)
    args = p.parse_args()
    trust = rights_snapshot(args)
    if contracts.instant(args.holdout_start) > contracts.instant(args.at):
        raise OperatorError('future_holdout_boundary')
    baseline = read_decisions(args.baseline, args, trust)
    candidate = read_decisions(args.candidate, args, trust)
    if not baseline or not candidate:
        raise OperatorError('both_shadow_sides_required')
    outcome_windows, unavailable_outcomes = future_windows(args.outcomes, args, trust)
    def indexed(decisions):
        result = {}
        for d in decisions:
            if d['state'] != 'verified':
                continue
            key = (d['trend_id'], d['episode_id'], d['decision_cutoff'])
            if key in result:
                raise OperatorError('duplicate_shadow_decision')
            result[key] = d
        return result
    left, right = indexed(baseline), indexed(candidate)
    comparisons = []
    for key in sorted(left.keys() & right.keys()):
        a, b = left[key], right[key]
        comparable = a['pairing_digest'] == b['pairing_digest']
        comparisons.append({'decision_cutoff': key[2], 'comparable_inputs': comparable,
            'same_method_artifacts': a['method_bundle_digest'] == b['method_bundle_digest'],
            'stage_changed': a['candidate_stage'] != b['candidate_stage'] if comparable else None,
            'baseline_stage': a['candidate_stage'] if comparable else None,
            'candidate_stage': b['candidate_stage'] if comparable else None})
    blocked = any(d['state'] != 'verified' for d in baseline + candidate)
    report = {**envelope(args, 'rafii.trend-shadow-report.v1'), 'status': 'blocked' if blocked else 'ok',
              'baseline': side_report(baseline, outcome_windows, args), 'candidate': side_report(candidate, outcome_windows, args),
              'comparisons': comparisons, 'unmatched_baseline': len(left.keys() - right.keys()),
              'unmatched_candidate': len(right.keys() - left.keys()), 'unavailable_outcome_bundles': unavailable_outcomes,
              'promotion': 'not_attempted', 'limitations': ['Candidate stages are internal shadow calls only.',
                  'Unknown outcomes are excluded from the precision denominator.',
                  'No measured negative population: FPR and recall remain null.',
                  'One report cannot establish consecutive shadow coverage, native-language review or production qualification.',
                  'Unsupported historical executors are reported unavailable; the current method is never substituted.']}
    return finish(args, report, inputs=[args.baseline, args.candidate, args.outcomes])


if __name__ == '__main__':
    sys.exit(run(main))
