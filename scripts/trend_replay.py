#!/usr/bin/env python3
"""Run the actual causal replay, receipt arithmetic and shadow lifecycle over explicit JSON files."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

from trend_verify_receipt import (OperatorError, bounded_list, contracts, envelope, finish,
    implementation_methods, metrics, pairing_digest, parser, read_json, refuse_network, rights_snapshot, run,
    source_status, verify_pack)
sys.addaudithook(refuse_network)
from postriff_phase2.growth.trends import backtest, receipts


def main():
    p = parser('Seal then-known observations and memberships with the existing receipt/lifecycle algorithms.')
    p.add_argument('--input', required=True, type=Path, help='Observation/window fixture or replay input JSON')
    p.add_argument('--cutoff', action='append', required=True, help='Repeat for multiple UTC decision instants')
    p.add_argument('--method', required=True, choices=('current',), help='Only the installed executable is supported')
    p.add_argument('--method-available-at', required=True, help='Explicit operator-declared method knowledge time')
    p.add_argument('--trend-id', required=True)
    p.add_argument('--episode-id', required=True)
    p.add_argument('--group-id', action='append', required=True, help='Explicit topic/recurrence/duplicate leakage groups')
    args = p.parse_args()
    trust = rights_snapshot(args)
    data = read_json(args.input)
    observations = bounded_list(data.get('observations'), 'observations', 2000)
    memberships = bounded_list(data.get('membership_events'), 'membership_events', 10000)
    policies = bounded_list(data.get('source_policies'), 'source_policies', 100)
    windows = bounded_list(data.get('window_specs'), 'window_specs', 200)
    baselines = bounded_list(data.get('baseline_window_specs'), 'baseline_window_specs', 200)
    cutoffs = bounded_list(args.cutoff, 'cutoffs', 48)
    if not observations or not windows or len(observations) * len(cutoffs) > 50000:
        raise OperatorError('replay_work_bound_or_empty_input')
    for collection in (observations, memberships, policies):
        if any(r.get('scope_key') != args.scope for r in collection):
            raise OperatorError('replay_scope_mismatch')
    for spec in windows + baselines:
        if spec['comparison_scope']['scope_key'] != args.scope:
            raise OperatorError('window_scope_mismatch')
    for cutoff in cutoffs:
        if contracts.instant(cutoff) > contracts.instant(args.at):
            raise OperatorError('future_decision_cutoff')
    method_available = contracts.iso(contracts.instant(args.method_available_at))
    if not 1 <= len(args.group_id) <= 20 or any(not g or len(g) > 160 for g in args.group_id):
        raise OperatorError('explicit_leakage_groups_required')
    groups = sorted(set(args.group_id))
    artifacts = implementation_methods()
    timeline = [{**a, 'available_at': method_available} for a in artifacts]
    withdrawn = {(m['name'], m['version']) for m in trust['withdrawn_methods']}

    def decide(**context):
        cutoff = context['decision_cutoff']
        visible = metrics.latest_revisions(context['observations'], cutoff)
        status = source_status(visible, trust, args.at)
        base = {'trend_id': args.trend_id, 'episode_id': args.episode_id, 'group_ids': groups}
        if status['state'] != 'verified':
            return {**base, 'state': status['state'], 'reason': status.get('reason', status['state'])}
        available = [{k: v for k, v in a.items() if k != 'available_at'} for a in context['method_artifacts']]
        if len(available) != len(artifacts) or any((a['name'], a['version']) in withdrawn for a in available):
            return {**base, 'state': 'method_unavailable', 'reason': 'method_not_available_at_cutoff_or_withdrawn'}
        selected = [deepcopy(w) for w in windows if contracts.instant(w['end']) <= contracts.instant(cutoff)]
        historical = [deepcopy(w) for w in baselines if contracts.instant(w['end']) <= contracts.instant(cutoff)]
        if not selected:
            return {**base, 'state': 'pending', 'reason': 'no_completed_window'}
        pack = receipts.create_receipt(observations=context['observations'], membership_events=context['memberships'],
            window_specs=selected, baseline_window_specs=historical, source_policies=context['source_policies'],
            method_artifacts=available, scope_key=args.scope, trend_id=args.trend_id, episode_id=args.episode_id,
            decision_cutoff=cutoff, computed_at=cutoff,
            execution_state='synthetic_fixture' if args.execution == 'fixture' else 'offline_replay')
        verified, pack = verify_pack(pack, args, trust)
        if verified['state'] != 'verified':
            return {**base, **verified}
        return {**base, 'state': 'verified', 'pairing_digest': pairing_digest(pack), 'bundle': pack,
                'method_bundle_digest': contracts.digest(available), 'candidate_stage': pack['receipt']['inferred']['candidate_stage']}

    decisions = backtest.replay(observations, memberships, cutoffs, decide=decide,
                               method_artifacts=timeline, source_policies=policies)
    # Invalidated data must not leave input fingerprints or raw sources in exported evidence.
    safe = [d if d['state'] == 'verified' else {k: v for k, v in d.items()
            if k in ('state', 'reason', 'decision_cutoff')} for d in decisions]
    report = {**envelope(args, 'rafii.trend-replay-report.v1'),
              'status': 'ok' if all(d['state'] == 'verified' for d in safe) else 'blocked',
              'mode': 'historical_live_decision_replay', 'method_availability_basis': 'operator_declared',
              'method_available_at': method_available, 'decisions': safe,
              'limitations': ['No future outcome labels are used in this pass.',
                  'Exported full manifests remain subject to source retention and deletion obligations.',
                  'Local verification does not establish current production rights or qualification.']}
    return finish(args, report, inputs=[args.input])


if __name__ == '__main__':
    sys.exit(run(main))
