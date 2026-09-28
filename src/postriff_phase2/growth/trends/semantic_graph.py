"""Pure, bounded graph input from retained literal spans and reviewed annotations.

build_graph_input(inputs, reconstructed, semantic=None, *, now) returns the
input contract of graph.project_graph. `reconstructed` is the first result of
text_context.reconstruct; `semantic` is semantic_admission.adapt's result.
The caller owns authenticated current SQL rights, model/task/cohort reviews,
artifact dependencies and method registration. This adapter cannot grant them.

Source knowledge stays pinned to source_decision_cutoff. The projection cutoff
is now; reviewed interpretation availability is retained separately, never
backdated to source acquisition. No retrieval, model call, identity resolution,
causal inference, origin inference, translation or semantic clustering occurs.
"""
from copy import deepcopy

from . import context, contracts, text_context

VERSION = 'semantic_graph_v1'
MAX_SOURCES = 1000
MAX_SEEDS = 1000
MAX_ANNOTATIONS = 1000
MAX_NODES = 100
MAX_EDGES = 200
STANCES = {'support', 'oppose', 'question', 'mixed', 'unknown'}


def _time(value):
    return contracts.instant(value)


def _id(kind, *parts):
    return 'semantic-graph:' + kind + ':' + contracts.digest(parts)


def _refs(value):
    if (not isinstance(value, list) or not value or len(value) > MAX_SOURCES
            or any(not isinstance(v, str) or not v for v in value) or len(set(value)) != len(value)):
        return None
    return sorted(value)


def _label(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 500


def _native(seed, sources, facts, scope, episode, bundles):
    refs = _refs(seed.get('evidence_refs'))
    spans = seed.get('original_spans')
    links = seed.get('bundle_ids')
    if (not isinstance(seed.get('seed_id'), str) or not seed['seed_id'] or not refs
            or not set(refs) <= sources.keys() or not isinstance(spans, list) or not 1 <= len(spans) <= 20
            or not isinstance(links, list) or not links or len(links) > 20
            or any(not isinstance(v, str) for v in links) or not set(links) <= bundles.keys()
            or not set(refs) <= {sid for bid in links for sid in bundles[bid].get('member_ids', [])}):
        return None
    cohort = {(sources[s]['platform'], sources[s].get('language')) for s in refs}
    if len(cohort) != 1:
        return None
    platform, language = next(iter(cohort))
    if not isinstance(language, str) or not language or seed.get('language') != language:
        return None
    native = []
    for span in spans:
        if not isinstance(span, dict) or set(span) != {'source_id', 'start', 'end', 'text'}:
            return None
        sid = span['source_id']; text = facts.get(sid, {}).get('text')
        if (sid not in refs or not isinstance(text, str) or type(span['start']) is not int or type(span['end']) is not int
                or not 0 <= span['start'] < span['end'] <= len(text)
                or span['end'] - span['start'] > text_context.MAX_SPAN
                or text[span['start']:span['end']] != span['text']):
            return None
        native.append(deepcopy(span))
    if {s['source_id'] for s in native} != set(refs):
        return None
    native.sort(key=contracts.canonical)
    if len({contracts.canonical(s) for s in native}) != len(native):
        return None
    return {'seed_id': seed['seed_id'], 'refs': refs, 'spans': native, 'platform': platform,
            'language': language, 'scope_key': scope, 'episode_id': episode}


def build_graph_input(inputs, reconstructed, semantic=None, *, now):
    """Return <=100 scoped nodes/200 edges; abstention never becomes a merge.

    Platform anchors are cohort-specific; phrase IDs identify exact source
    spans. Topic/episode IDs retain seed context instead of merging independently
    reviewed interpretations merely because their labels happen to match.
    `truncated` reports adapter selection; parent must propagate it to the wire.
    """
    common = inputs['common']; scope = contracts.scope(common['scope_key'])
    cutoff = common['decision_cutoff']; at = _time(now); source_at = _time(cutoff)
    if at < source_at:
        raise ValueError('semantic_graph_current_cutoff_precedes_source_cutoff')
    if (not isinstance(reconstructed, dict) or reconstructed.get('scope_key') != scope
            or _time(reconstructed['decision_cutoff']) != source_at
            or reconstructed.get('episode_id') != inputs['episode_id']):
        raise ValueError('semantic_graph_reconstruction_binding')
    context.bounded(common.get('sources', []), MAX_SOURCES)
    eligible = context.source_index(common, 'creative')
    sources = {sid: deepcopy(s) for sid, s in sorted(eligible.items())
               if s.get('rights', {}).get('display') is True and s.get('expires_at') and _time(s['expires_at']) > at}
    if _time(inputs['expires_at']) <= at:
        sources = {}
    bundles, ambiguous_bundles = {}, set()
    for bundle in context.bounded(reconstructed.get('bundles', []), MAX_SEEDS):
        if (isinstance(bundle, dict) and bundle.get('scope_key') == scope
                and isinstance(bundle.get('bundle_id'), str) and _refs(bundle.get('member_ids'))):
            bid = bundle['bundle_id']
            if bid in bundles and bundles[bid] != bundle:
                ambiguous_bundles.add(bid)
            bundles[bid] = bundle
    for bid in ambiguous_bundles:
        bundles.pop(bid, None)
    seeds, duplicate_ids = {}, set()
    for seed in context.bounded(reconstructed.get('seeds', []), MAX_SEEDS):
        if not isinstance(seed, dict):
            continue
        valid = _native(seed, sources, inputs['facts'], scope, inputs['episode_id'], bundles)
        if valid:
            sid = valid['seed_id']
            if sid in seeds and valid != seeds[sid]: duplicate_ids.add(sid)
            seeds[sid] = valid
    for sid in duplicate_ids: seeds.pop(sid, None)
    semantic = semantic or {}
    if not isinstance(semantic, dict):
        raise ValueError('semantic_graph_annotations_required')
    semantic_time_bound = (not semantic.get('revoked') and not semantic.get('deleted')
                           and semantic.get('source_decision_cutoff', cutoff) == cutoff
                           and ('decision_cutoff' not in semantic or _time(semantic['decision_cutoff']) <= at))
    blocked = {r['seed_id'] for r in context.bounded(semantic.get('conflicts', []), MAX_ANNOTATIONS)
               if isinstance(r, dict) and isinstance(r.get('seed_id'), str)}
    choices = {}
    for annotation in context.bounded(semantic.get('annotations', []), MAX_ANNOTATIONS):
        if not isinstance(annotation, dict) or not semantic_time_bound:
            continue
        seed = seeds.get(annotation.get('seed_id')); refs = _refs(annotation.get('evidence_refs'))
        if (not seed or seed['seed_id'] in blocked or refs != seed['refs']
                or annotation.get('review_status') != 'cohort_reviewed'
                or annotation.get('derivation_kind') != 'model_interpretation'
                or annotation.get('revoked') or annotation.get('deleted')
                or annotation.get('language') != seed['language'] or annotation.get('stance') not in STANCES
                or not _label(annotation.get('concept')) or not _label(annotation.get('claim'))
                or not _label(annotation.get('method_version'))
                or annotation.get('scope_key', scope) != scope
                or any(sources[r]['rights'].get('llm') is not True for r in refs)
                or not isinstance(annotation.get('original_spans'), list)
                or len(annotation['original_spans']) != len(seed['spans'])
                or sorted(annotation.get('original_spans', []), key=contracts.canonical) != seed['spans']):
            continue
        try:
            available = _time(annotation['available_at']); end = _time(annotation['expires_at'])
            if (available > at or end <= at or available >= end
                    or ('expires_at' in semantic and _time(semantic['expires_at']) <= at)):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        choices.setdefault(seed['seed_id'], []).append(annotation)
    accepted = {}
    for sid, annotations in sorted(choices.items()):
        if len({(a['concept'], a['claim'], a['stance']) for a in annotations}) != 1:
            blocked.add(sid)
            continue
        accepted[sid] = sorted(annotations, key=contracts.canonical)
    nodes, edges = {}, {}

    def support(refs, annotations=()):
        availability = [cutoff] + [sources[s]['available_at'] for s in refs] + [a['available_at'] for a in annotations]
        expiry = [inputs['expires_at']] + [sources[s]['expires_at'] for s in refs] + [a['expires_at'] for a in annotations]
        if annotations and semantic.get('expires_at'): expiry.append(semantic['expires_at'])
        versions = sorted({a['method_version'] for a in annotations})
        return {'evidence_refs': sorted(refs), 'available_at': max(availability, key=_time), 'expires_at': min(expiry, key=_time),
                'computed_at': now, 'source_decision_cutoff': cutoff,
                'method_version': VERSION if not versions else VERSION + ':' + contracts.digest(versions),
                'annotation_method_versions': versions}

    def edge(a, b, seed, refs, annotations=()):
        kind = 'model_hypothesis' if annotations else 'calculated_association'
        eid = _id('edge', scope, a, b, 'co_occurrence', kind)
        edges[eid] = {'edge_id': eid, 'source_id': a, 'target_id': b, 'edge_type': 'co_occurrence',
            'scope_key': scope, 'platform': seed['platform'], 'language': seed['language'], 'evidence_kind': kind,
            'event_start': min((sources[s]['event_at'] for s in refs), key=_time),
            'event_end': max((sources[s]['event_at'] for s in refs), key=_time),
            'uncertainty': ('Reviewed interpretation of this retained context; association only, no causal or origin claim.'
                            if annotations else 'Exact retained wording observed on this platform; no meaning, stance or origin inferred.'),
            **support(refs, annotations)}

    for sid, seed in sorted(seeds.items()):
        cohort = [scope, seed['platform'], seed['language']]
        base = {'scope_key': scope, 'platform': seed['platform'], 'language': seed['language'], 'origin': 'unknown'}
        platform_id = _id('platform', *cohort)
        if platform_id not in nodes:
            nodes[platform_id] = {**base, 'node_id': platform_id, 'node_type': 'platform', 'label': seed['platform'],
                                  'derivation_kind': 'deterministic_extraction', **support(seed['refs'])}
        else:
            refs = sorted(set(nodes[platform_id]['evidence_refs']) | set(seed['refs']))
            nodes[platform_id].update(support(refs))
        phrases = []
        for span in seed['spans']:
            pid = _id('phrase', *cohort, span)
            refs = [span['source_id']]
            nodes[pid] = {**base, 'node_id': pid, 'node_type': 'phrase', 'label': span['text'], 'original_spans': [deepcopy(span)],
                          'interpretation_state': 'literal_unreviewed', 'derivation_kind': 'deterministic_extraction', **support(refs)}
            phrases.append(pid); edge(pid, platform_id, seed, refs)
        annotations = accepted.get(sid)
        if not annotations:
            continue
        annotation = annotations[0]
        topic_id = _id('topic', *cohort, sid, annotation['concept'])
        narrative_id = _id('narrative_episode', *cohort, seed['episode_id'], sid, annotation['concept'], annotation['claim'], annotation['stance'])
        metadata = {**base, 'seed_id': sid, 'concept': annotation['concept'], 'claim': annotation['claim'],
                    'stance': annotation['stance'], 'episode_id': seed['episode_id'], 'review_status': 'cohort_reviewed',
                    'derivation_kind': 'model_interpretation', **support(seed['refs'], annotations)}
        nodes[topic_id] = {**metadata, 'node_id': topic_id, 'node_type': 'topic', 'label': annotation['concept']}
        nodes[narrative_id] = {**metadata, 'node_id': narrative_id, 'node_type': 'narrative_episode',
                               'label': annotation['claim'] + ' [' + annotation['stance'] + ']'}
        edge(topic_id, narrative_id, seed, seed['refs'], annotations)
        for pid in phrases: edge(pid, narrative_id, seed, seed['refs'], annotations)
    # Stable IDs determine truncation, never input arrival order or model rank.
    chosen = sorted(nodes)[:MAX_NODES]; chosen_set = set(chosen)
    kept_edges = sorted((e for e in edges.values() if e['source_id'] in chosen_set and e['target_id'] in chosen_set),
                        key=lambda e: e['edge_id'])[:MAX_EDGES]
    return {**deepcopy(common), 'sources': list(sources.values()), 'decision_cutoff': now, 'source_decision_cutoff': cutoff,
            'nodes': [nodes[n] for n in chosen], 'edges': kept_edges, 'claims': [], 'origin': 'unknown', 'causal_claims': False,
            'method_version': VERSION, 'conflicted_seed_ids': sorted(blocked),
            'semantic_state': 'reviewed_interpretations' if accepted else 'literal_only',
            'candidate_node_count': len(nodes), 'candidate_edge_count': len(edges),
            'truncated': bool(reconstructed.get('truncated')) or len(chosen) < len(nodes) or len(kept_edges) < len(edges)}
