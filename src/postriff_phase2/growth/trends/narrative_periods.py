"""Causal period membership and bounded continuity over retained native seeds.

The default groups exact wording within a language/platform and period. These
are lexical patterns, not inferred semantic narratives. Semantic annotations
may add concepts/claims only through the caller's current evidence admission;
unqualified annotations never merge different wording or infer endorsement.
"""
from collections import defaultdict
from datetime import timedelta

from . import context, contracts, narratives

METHOD = 'native-period-lineage-v1'


def _start(at, period):
    value = context.timestamp(at).replace(hour=0, minute=0, second=0, microsecond=0)
    return value - timedelta(days=value.weekday()) if period == 'week' else value


def project(inputs, reconstruction, *, period='day', annotations=(), semantic_qualified=False, at=None):
    if period not in {'day', 'week'} or type(semantic_qualified) is not bool:
        raise ValueError('narrative_period_contract')
    common = inputs['common']
    source_cutoff = common['decision_cutoff']
    at = at or source_cutoff
    cutoff = context.timestamp(at)
    if cutoff < context.timestamp(source_cutoff):
        raise ValueError('narrative_decision_before_sources')
    sources = context.source_index(common, 'creative', originals=True)
    base = {s['seed_id']: s for s in context.bounded(reconstruction['seeds'], 20)}
    annotation_map = {}
    for annotation in context.bounded(list(annotations), 20):
        sid = annotation.get('seed_id')
        if sid not in base or sid in annotation_map:
            raise ValueError('narrative_annotation_seed_binding')
        seed = base[sid]
        if (annotation.get('bundle_ids') != seed['bundle_ids']
                or annotation.get('evidence_refs') != seed['evidence_refs']
                or annotation.get('original_spans') != seed['original_spans']
                or annotation.get('stance') not in {'support', 'oppose', 'question', 'mixed', 'unknown'}):
            raise ValueError('narrative_annotation_evidence_binding')
        if not context.supported(annotation, sources, cutoff):
            continue
        if not all(sources[r]['rights'].get('llm') is True for r in annotation['evidence_refs']):
            continue
        if any(not isinstance(annotation.get(k), str) or not 1 <= len(annotation[k]) <= 500
               for k in ('concept', 'claim', 'method_version')):
            raise ValueError('narrative_annotation_shape')
        annotation_map[sid] = annotation

    groups = defaultdict(list)
    for seed in base.values():
        refs = seed['evidence_refs']
        if not refs or any(r not in sources for r in refs):
            continue
        # Source text is primary; annotations cannot introduce or alter a quote.
        for span in seed['original_spans']:
            text = inputs['facts'][span['source_id']]['text']
            if (span['source_id'] not in refs or type(span['start']) is not int or type(span['end']) is not int
                    or not 0 <= span['start'] < span['end'] <= len(text)
                    or text[span['start']:span['end']] != span['text']):
                raise ValueError('narrative_span_mismatch')
        annotation = annotation_map.get(seed['seed_id'])
        mode = 'reviewed_claim' if annotation and semantic_qualified else 'exact_native_wording'
        # A quoted claim with an unknown stance cannot silently become support.
        stance = annotation['stance'] if annotation else 'unknown'
        meaning = annotation['claim'] if mode == 'reviewed_claim' else [s['text'] for s in seed['original_spans']]
        for language, platform in sorted({(sources[r]['language'], sources[r]['platform']) for r in refs}):
            cohort_refs = [r for r in refs if (sources[r]['language'], sources[r]['platform']) == (language, platform)]
            for start in sorted({_start(sources[r]['event_at'], period) for r in cohort_refs}):
                period_refs = [r for r in cohort_refs if _start(sources[r]['event_at'], period) == start]
                key = (contracts.iso(start), language, platform, mode, context.digest(meaning), stance)
                groups[key].append((seed, period_refs, annotation))
    clusters = []
    for key, members in sorted(groups.items()):
        start, language, platform, mode, meaning_digest, stance = key
        refs = sorted({r for _, ids, _ in members for r in ids})
        seeds = sorted({s['seed_id'] for s, _, _ in members})
        pattern_id = context.digest([common['scope_key'], inputs['episode_id'], language, platform, mode, meaning_digest, stance])
        cid = context.digest([pattern_id, period, start])
        original_count = len({context.canonical_key(sources[r]) for r in refs})
        creators = {context.creator_key(sources[r]) for r in refs if context.creator_key(sources[r])}
        clusters.append({'cluster_id': cid, 'pattern_id': pattern_id, 'period': period,
            'period_start': start, 'period_end': contracts.iso(_start(start, period) + timedelta(days=7 if period == 'week' else 1)),
            'first_observed': min(sources[r]['event_at'] for r in refs), 'last_observed': max(sources[r]['event_at'] for r in refs),
            'language': language, 'platform': platform, 'mode': mode, 'stance': stance,
            'semantic_qualification': 'cohort_qualified' if mode == 'reviewed_claim' else 'unqualified',
            'membership_revision': context.digest([cid, seeds, refs]), 'seed_ids': seeds,
            'evidence_refs': refs, 'unique_original_posts': original_count, 'known_creators': len(creators),
            'unknown_creator_posts': len({context.canonical_key(sources[r]) for r in refs
                                          if context.creator_key(sources[r]) is None}),
            'provisional': len(creators) < 2, 'origin': 'unknown', 'trajectory': None})
    chains, links, decisions = defaultdict(list), [], []
    for cluster in clusters:
        chains[cluster['pattern_id']].append(cluster)
    for pattern_id, chain in sorted(chains.items()):
        ordered = sorted(chain, key=lambda c: (c['first_observed'], c['cluster_id']))
        episode = None
        previous = None
        for cluster in ordered:
            if previous:
                gap = (context.timestamp(cluster['first_observed']) - context.timestamp(previous['last_observed'])).total_seconds()
                relation = 'continuation' if 0 < gap <= 48*3600 else 'recurrence'
                refs = sorted(set(previous['evidence_refs'] + cluster['evidence_refs']))
                link = {'parent_id': previous['cluster_id'], 'child_id': cluster['cluster_id'], 'relation': relation,
                    'parent_end': previous['last_observed'], 'child_start': cluster['first_observed'],
                    'evidence_refs': refs, 'available_at': at, 'expires_at': inputs['expires_at'],
                    'method_version': METHOD, 'evidence_kind': 'calculated_association', 'gap_seconds': gap,
                    'uncertainty': 'Same retained wording or reviewed claim across periods; this does not establish causation or universal origin.'}
                # Periods are disjoint. Defensive refusal keeps temporal cycles out.
                if gap <= 0:
                    raise ValueError('narrative_period_time_conflict')
                links.append(link)
                decisions.append({'kind': relation, 'input_membership_revisions': [previous['membership_revision'], cluster['membership_revision']],
                                  'decision_at': at, 'feature_digest': context.digest(link), 'method_version': METHOD})
                prior_count = previous['unique_original_posts']
                cluster['trajectory'] = {'previous_unique_original_posts': prior_count,
                    'current_unique_original_posts': cluster['unique_original_posts'],
                    'difference': cluster['unique_original_posts'] - prior_count,
                    'comparison': 'observed_counts_only', 'equal_coverage_established': False,
                    'rate': None, 'limitation': 'No comparable period coverage is asserted.'}
                if relation == 'recurrence':
                    episode = None
            episode = episode or context.digest([pattern_id, cluster['cluster_id']])
            cluster['episode_id'] = episode
            previous = cluster
    lineage = narratives.link_episodes({**common, 'decision_cutoff': at, 'links': links})
    return {'method_version': METHOD, 'scope_key': common['scope_key'], 'source_cutoff': source_cutoff,
        'decision_cutoff': at, 'period': period, 'clusters': clusters, 'links': lineage['links'], 'decisions': decisions,
        'size_definition': 'unique_deduplicated_original_posts', 'history_rewritten': False,
        'automatic_semantic_merges': semantic_qualified, 'cross_language_merges': False,
        'unknowns': ['embedding_cohort_unavailable', 'lexical_continuity_is_not_semantic_or_causal_proof', 'origin_unknown']}
