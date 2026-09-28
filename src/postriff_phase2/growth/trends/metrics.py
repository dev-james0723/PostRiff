"""Pure sampled-post measurements. No I/O, model calls, or population estimates.

Rights use canonical strict PermissionGrant objects. Unknown is denied.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from .contracts import validate_observation as _validate_observation, permits

OBSERVATION_KEYS = frozenset('observation_id scope_key provider_id source_identity revision_identity revision_sequence kind operation event_at received_at available_at coverage_epoch source_policy_version provider_contract_version retention_until rights payload payload_digest'.split())
COMPARABILITY_KEYS = ('scope_key', 'provider_id', 'metric_definition_id', 'query_digest', 'evidence_kind', 'audience_scope', 'sampling_method', 'platform', 'language', 'community', 'inclusion_rules_digest', 'time_basis', 'coverage_epoch', 'baseline_timezone')


def instant(value):
    """Parse an explicit UTC ISO instant; never infer a local timezone."""
    if not isinstance(value, str) or 'T' not in value:
        raise ValueError('expected ISO UTC instant')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError('expected ISO UTC instant')
    return dt.astimezone(timezone.utc)


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def metric(value, unit, reason=None):
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
        raise ValueError('metric must be finite numeric or null')
    return {'value': value, 'unit': unit, 'reason': reason}


def right_allowed(rights, operation, at, scope_key=None):
    return permits(rights, operation, scope_key, at)


def source_policy_allowed(observation, source_policies, at, permission='derive_metrics'):
    """Policies are JSON objects (e.g. dataclasses.asdict(SourcePolicy)).

    Historical selection checks then-effective/available policy snapshots;
    revocation on the current read path independently overrides history.
    """
    candidates = [p for p in source_policies or [] if
                  p.get('provider_id') == observation['provider_id'] and
                  p.get('version') == observation['source_policy_version'] and
                  p.get('scope_key') == observation['scope_key']]
    for p in candidates:
        if (p.get('readiness') == 'ready' and (not p.get('revoked_at') or instant(p['revoked_at']) > instant(at))
            and instant(p['effective_at']) <= instant(at) < instant(p['expires_at'])
            and instant(p.get('available_at', p['effective_at'])) <= instant(at)
            and right_allowed(p.get('rights', {}), permission, at, observation['scope_key'])
            and right_allowed(observation['rights'], permission, at, observation['scope_key'])):
            return True
    return False


def comparison_digest(scope):
    if any(key not in scope or scope[key] is None for key in COMPARABILITY_KEYS):
        return None
    return canonical_digest({key: scope[key] for key in COMPARABILITY_KEYS})


def validate_observation(row):
    return _validate_observation(row)


def latest_revisions(observations, decision_cutoff):
    """Resolve provider-scoped identities by source sequence, retaining tombstones.

    A lower-sequence late create cannot resurrect a delete. Conflicting revisions
    at the same source sequence fail closed, except a delete always wins a tie.
    """
    cutoff = instant(decision_cutoff)
    grouped = {}
    seen = {}
    for row in observations:
        if instant(row['available_at']) > cutoff:
            continue
        validate_observation(row)
        identity = (row['scope_key'], row['provider_id'], row['source_identity'])
        if not all(identity):
            raise ValueError('unresolved source identity')
        revision = identity + (row['revision_identity'],)
        content = canonical_digest({k: v for k, v in row.items() if k not in ('received_at', 'available_at', 'observation_id', 'stable_ingestion_sequence')})
        if revision in seen and seen[revision] != content:
            raise ValueError('conflicting immutable source revision')
        seen[revision] = content
        current = grouped.get(identity)
        if current and current['revision_sequence'] == row['revision_sequence'] and current['revision_identity'] != row['revision_identity'] and current['operation'] != 'delete' and row['operation'] != 'delete':
            raise ValueError('ambiguous source revision sequence')
        rank = lambda item: (item['revision_sequence'], item['operation'] == 'delete', item['revision_identity'], -instant(item['available_at']).timestamp(), item['observation_id'])
        if current is None or rank(row) > rank(current):
            grouped[identity] = row
    return [deepcopy(grouped[k]) for k in sorted(grouped)]


def creator_metrics(observations):
    authors = Counter((r['provider_id'], r['payload']['author_key']) for r in observations if r['payload'].get('author_status') == 'known' and r['payload'].get('author_key'))
    known = sum(authors.values())
    total = len(observations)
    shares = [n / known for n in authors.values()] if known else []
    entropy = -sum(p * math.log(p) for p in shares) if shares else None
    return {'known_creator_count': len(authors), 'known_author_post_count': known,
            'unknown_author_fraction': (total - known) / total if total else None,
            'creator_entropy': entropy, 'effective_creators': math.exp(entropy) if entropy is not None else None,
            'concentration_effective_creators': 1 / sum(p*p for p in shares) if shares else None,
            'largest_creator_share': max(shares) if shares else None}


def aggregate_window(observations, *, start, end, decision_cutoff, coverage, comparison_scope, memberships=None, episode_id=None, source_policies=None):
    """Return a half-open event-time window; partial coverage preserves counts.

    For episode measurements pass cutoff-resolved membership rows, each carrying
    observation_id, input_revision_identity, episode_id and available_at.
    """
    left, right, cutoff = instant(start), instant(end), instant(decision_cutoff)
    if not left < right <= cutoff:
        raise ValueError('window must finish by decision cutoff')
    hours = (right - left).total_seconds() / 3600
    members = {}
    for m in memberships or []:
        if instant(m['available_at']) <= cutoff and m.get('episode_id') == episode_id and m.get('scope_key') == comparison_scope.get('scope_key'):
            members[m['observation_id']] = m
    accepted, discovery, exclusions = [], [], Counter()
    rows = latest_revisions(observations, decision_cutoff)
    considered = []
    for row in rows:
        event = instant(row['event_at']) if row['event_at'] else None
        retrieval = instant(row['received_at'])
        if not ((event is not None and left <= event < right) or (event is None and left <= retrieval < right)):
            continue
        considered.append(row)
        reason = None
        if row['operation'] == 'delete':
            reason = 'deleted'
        elif not source_policy_allowed(row, source_policies, decision_cutoff):
            reason = 'rights_blocked'
        elif instant(row['retention_until']) <= cutoff:
            reason = 'inputs_expired'
        elif row['kind'] not in ('raw_post', 'owned_post'):
            reason = 'not_raw_original'
        elif row['scope_key'] != comparison_scope.get('scope_key'):
            reason = 'outside_scope'
        elif row['coverage_epoch'] != comparison_scope.get('coverage_epoch'):
            reason = 'coverage_epoch_mismatch'
        elif row['provider_id'] != comparison_scope.get('provider_id') or row['kind'] != comparison_scope.get('evidence_kind'):
            reason = 'incomparable_evidence'
        elif any(row['payload'].get(k, 'unknown' if k == 'community' else None) != comparison_scope.get(k) for k in ('platform', 'language', 'community')):
            reason = 'outside_cohort'
        elif row['payload'].get('is_repost') or row['payload'].get('post_type') == 'repost' or row['payload'].get('excluded'):
            reason = 'repost_or_excluded'
        elif episode_id is not None and (row['observation_id'] not in members or members[row['observation_id']].get('input_revision_identity') != row['revision_identity']):
            reason = 'membership_unavailable'
        if reason:
            exclusions[reason] += 1
        elif event is None:
            discovery.append(row)
        else:
            accepted.append(row)
    signature = comparison_digest(comparison_scope)
    unavailable = None
    frame_permitted = any(source_policy_allowed(
        {'provider_id': p.get('provider_id'), 'source_policy_version': p.get('version'),
         'scope_key': p.get('scope_key'), 'rights': p.get('rights', {})}, [p], decision_cutoff)
        for p in source_policies or [] if p.get('scope_key') == comparison_scope.get('scope_key')
        and p.get('provider_id') == comparison_scope.get('provider_id'))
    if not frame_permitted:
        unavailable = 'source_policy_unavailable'
    elif not signature:
        unavailable = 'incomplete_comparison_scope'
    elif coverage.get('availability') != 'available':
        unavailable = 'coverage_' + coverage.get('availability', 'unknown')
    elif coverage.get('completeness') != 'complete_within_scope':
        unavailable = 'coverage_' + coverage.get('completeness', 'unknown')
    elif coverage.get('coverage_epoch') != comparison_scope.get('coverage_epoch'):
        unavailable = 'coverage_epoch_mismatch'
    elif coverage.get('representation') not in ('raw_posts', 'sampled_posts', 'owned_posts'):
        unavailable = 'incompatible_representation'
    elif exclusions['coverage_epoch_mismatch'] or exclusions['incomparable_evidence']:
        unavailable = 'incomparable_evidence'
    elif exclusions['rights_blocked'] or exclusions['inputs_expired']:
        unavailable = 'rights_or_retention_gap'
    copies = Counter(r['payload'].get('copy_family_id', r['source_identity']) for r in accepted)
    result = {'window_start': start, 'window_end': end, 'decision_cutoff': decision_cutoff,
              'window_hours': hours, 'comparison_scope': deepcopy(comparison_scope), 'comparison_digest': signature,
              'coverage': deepcopy(coverage), 'data_state': 'qualified' if unavailable is None else 'insufficient',
              'observed': {'received_count': len(considered), 'qualifying_original_count': len(accepted),
                           'discovery_count': len(discovery), 'excluded_count': sum(exclusions.values()),
                           'exclusions': dict(sorted(exclusions.items())), 'copy_redundancy_count': sum(n-1 for n in copies.values()),
                           **creator_metrics(accepted)},
              'mention_rate': metric(len(accepted)/hours if unavailable is None else None, 'posts/hour', unavailable),
              'discovery_rate': metric(len(discovery)/hours if unavailable is None else None, 'discoveries/hour', unavailable),
              'source_revision_refs': [{'observation_id': r['observation_id'], 'revision_identity': r['revision_identity'], 'payload_digest': r['payload_digest']} for r in accepted + discovery]}
    result['snapshot_id'] = 'snapshot_' + canonical_digest(result)
    return result


def engagement_velocity(old, new):
    """Counter snapshots must declare identity/metric/epoch/platform and time basis."""
    unit = 'engagements/hour'
    for key in ('source_identity', 'provider_id', 'platform', 'metric_definition_id', 'counter_epoch'):
        if not old.get(key) or old.get(key) != new.get(key):
            return {**metric(None, unit, 'incomparable_counter'), 'flags': []}
    for row in (old, new):
        if row.get('value') is None:
            return {**metric(None, unit, row.get('missing_reason', 'missing')), 'flags': []}
        metric(row['value'], unit)
    provider_time = bool(old.get('provider_observed_at') and new.get('provider_observed_at'))
    if bool(old.get('provider_observed_at')) != bool(new.get('provider_observed_at')):
        return {**metric(None, unit, 'time_basis_changed'), 'flags': []}
    time_key = 'provider_observed_at' if provider_time else 'received_at'
    hours = (instant(new[time_key])-instant(old[time_key])).total_seconds()/3600
    if hours <= 0:
        return {**metric(None, unit, 'nonpositive_elapsed_time'), 'flags': []}
    delta = new['value'] - old['value']
    return {**metric(delta/hours, unit), 'delta': delta, 'elapsed_hours': hours,
            'time_basis': 'provider_measurement' if provider_time else 'retrieval_time',
            'latency_uncertainty': not provider_time, 'positive_growth_eligible': delta >= 0,
            'flags': ['counter_decreased'] if delta < 0 else []}


def pattern_occupancy(eligible_ids, assignments, *, dimension):
    """One classified assignment/copy group per original; no topic-fatigue claim."""
    eligible = set(eligible_ids)
    classified = {}
    for a in assignments:
        if a['observation_id'] not in eligible or a.get('dimension') != dimension:
            continue
        if a['observation_id'] in classified:
            raise ValueError('duplicate dimension assignment')
        if a.get('pattern_id') is not None:
            classified[a['observation_id']] = a
    n = len(classified)
    counts = Counter(a['pattern_id'] for a in classified.values())
    groups = Counter(a.get('copy_group_id', key) for key, a in classified.items())
    return {'dimension': dimension, 'eligible_count': len(eligible), 'classified_count': n,
            'unclassified_count': len(eligible)-n, 'classification_coverage': n/len(eligible) if eligible else None,
            'pattern_shares': {k: v/n for k, v in sorted(counts.items())},
            'redundancy_ratio': sum(v-1 for v in groups.values())/n if n else None,
            'saturation': None, 'audience_fatigue': None}
