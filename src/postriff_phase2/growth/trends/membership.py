"""Append-only temporal assignment events with optimistic stream revision checks.

Event operations: assign/reassign/remove, merge (from_episode_id/to_episode_id),
split (parent_episode_id/child_episode_ids). Merge/split require explicit new
assignments; history is never resolved through a future alias.
"""
from copy import deepcopy
from .metrics import canonical_digest, instant, latest_revisions, source_policy_allowed


def _visible(events, cutoff):
    return sorted((e for e in events if instant(e['available_at']) <= instant(cutoff)),
                  key=lambda e: (instant(e['available_at']), e['revision_sequence'], e['event_id']))


def resolve_memberships(events, decision_cutoff, *, observations=None, source_policies=None):
    selected = {}
    for event in _visible(events, decision_cutoff):
        if event['operation'] not in ('assign', 'reassign', 'remove'):
            continue
        key = (event['scope_key'], event['observation_id'])
        old = selected.get(key)
        if old and old['revision_sequence'] == event['revision_sequence'] and old != event:
            raise ValueError('conflicting membership revision')
        if old is None or event['revision_sequence'] > old['revision_sequence']:
            selected[key] = event
    rows = [deepcopy(e) for _,e in sorted(selected.items()) if e['operation'] != 'remove']
    if observations is None:
        return rows  # Historical graph only; measurement must gate source rights.
    sources = {r['observation_id']: r for r in latest_revisions(observations, decision_cutoff)}
    return [e for e in rows if e['observation_id'] in sources
            and sources[e['observation_id']]['operation'] != 'delete'
            and e['input_revision_identity'] == sources[e['observation_id']]['revision_identity']
            and e['scope_key'] == sources[e['observation_id']]['scope_key']
            and instant(sources[e['observation_id']]['retention_until']) > instant(decision_cutoff)
            and source_policy_allowed(sources[e['observation_id']], source_policies, decision_cutoff)]


def resolve_episode_alias(episode_id, events, decision_cutoff, *, scope_key):
    aliases = {}
    for event in _visible(events, decision_cutoff):
        if event['operation'] == 'merge' and event['scope_key'] == scope_key:
            aliases[event['from_episode_id']] = event['to_episode_id']
    seen = set()
    while episode_id in aliases:
        if episode_id in seen:
            raise ValueError('cyclic episode aliases')
        seen.add(episode_id)
        episode_id = aliases[episode_id]
    return episode_id


def append_membership_events(events, proposals, *, expected_revision, observations, source_policies):
    """Return a new log or reject an optimistic conflict; caller persists atomically."""
    current = max((e['revision_sequence'] for e in events), default=0)
    if type(expected_revision) is not int or current != expected_revision:
        raise ValueError('membership_revision_conflict')
    result = deepcopy(events)
    ids = {e['event_id'] for e in result}
    for offset, proposal in enumerate(proposals, 1):
        item = deepcopy(proposal)
        available = instant(item['available_at'])
        if result and available < max(instant(e['available_at']) for e in result):
            raise ValueError('membership_cannot_backdate_knowledge')
        if item['operation'] not in ('assign', 'reassign', 'remove', 'merge', 'split'):
            raise ValueError('unknown membership operation')
        for key in ('scope_key', 'method_version', 'feature_digest'):
            if not item.get(key): raise ValueError('missing membership ' + key)
        if item['operation'] in ('assign', 'reassign', 'remove'):
            for key in ('observation_id', 'input_revision_identity'):
                if not item.get(key): raise ValueError('missing membership ' + key)
            if item['operation'] != 'remove' and not item.get('episode_id'):
                raise ValueError('missing episode_id')
        if item['operation'] in ('assign', 'reassign'):
            sources = {r['observation_id']: r for r in latest_revisions(observations, item['available_at'])}
            row = sources.get(item['observation_id'])
            if (not row or row['scope_key'] != item['scope_key'] or row['revision_identity'] != item['input_revision_identity']
                or row['operation'] == 'delete' or instant(row['retention_until']) <= instant(item['available_at'])
                or not source_policy_allowed(row, source_policies, item['available_at'])):
                raise ValueError('membership_source_not_permitted')
        item['revision_sequence'] = current + offset
        item['event_id'] = item.get('event_id') or 'membership_' + canonical_digest(item)
        if item['event_id'] in ids: raise ValueError('duplicate membership event')
        ids.add(item['event_id'])
        result.append(item)
    return result


def merge_episodes(events, *, from_episode_id, to_episode_id, scope_key, available_at, method_version, expected_revision, observations, source_policies):
    if from_episode_id == to_episode_id: raise ValueError('self merge')
    target = resolve_episode_alias(to_episode_id, events, available_at, scope_key=scope_key)
    if target == from_episode_id: raise ValueError('cyclic episode aliases')
    common = {'scope_key': scope_key, 'available_at': available_at, 'method_version': method_version,
              'feature_digest': canonical_digest([from_episode_id, target])}
    proposals = [{**common, 'operation': 'merge', 'from_episode_id': from_episode_id, 'to_episode_id': target}]
    for row in resolve_memberships(events, available_at):
        if row['scope_key'] == scope_key and row['episode_id'] == from_episode_id:
            proposals.append({**common, 'operation': 'reassign', 'episode_id': target,
                              'observation_id': row['observation_id'], 'input_revision_identity': row['input_revision_identity']})
    return append_membership_events(events, proposals, expected_revision=expected_revision, observations=observations, source_policies=source_policies)


def split_episode(events, *, parent_episode_id, assignments, scope_key, available_at, method_version, expected_revision, observations, source_policies):
    current = {r['observation_id']: r for r in resolve_memberships(events, available_at) if r['scope_key'] == scope_key and r['episode_id'] == parent_episode_id}
    if set(assignments) != set(current) or parent_episode_id in assignments.values() or len(set(assignments.values())) < 2:
        raise ValueError('split must explicitly reassign every parent member to >=2 children')
    common = {'scope_key': scope_key, 'available_at': available_at, 'method_version': method_version, 'feature_digest': canonical_digest(assignments)}
    proposals = [{**common, 'operation': 'split', 'parent_episode_id': parent_episode_id, 'child_episode_ids': sorted(set(assignments.values()))}]
    proposals += [{**common, 'operation': 'reassign', 'episode_id': child, 'observation_id': oid,
                   'input_revision_identity': current[oid]['input_revision_identity']} for oid,child in sorted(assignments.items())]
    return append_membership_events(events, proposals, expected_revision=expected_revision, observations=observations, source_policies=source_policies)
