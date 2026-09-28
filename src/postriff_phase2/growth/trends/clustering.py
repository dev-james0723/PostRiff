"""Bounded original-language lexical/CJK conversation candidates.

This fallback is explicitly unqualified semantic inference. Shared entities alone
never imply a shared event; uncertain pairs abstain. No translation or geo guess.
"""
from copy import deepcopy
import re
import unicodedata
from .metrics import canonical_digest, instant, right_allowed, source_policy_allowed
from .embeddings import cosine_similarity, qualified_embedding

METHOD_VERSION = 'lexical-cjk-candidate-1'
_CJK = re.compile(r'[\u3400-\u9fff]+')
_LATIN = re.compile(r'[a-z0-9]+(?:[\x27’-][a-z0-9]+)*', re.I)


def text_features(text, language=None):
    normalized = unicodedata.normalize('NFC', text).casefold()
    words = _LATIN.findall(normalized)
    cjk = _CJK.findall(normalized)
    tokens = set(words)
    for run in cjk:
        tokens.update(run[i:i+2] for i in range(len(run)-1))
        if len(run) == 1: tokens.add(run)
    spans = [{'start': m.start(), 'end': m.end(), 'text': m.group(), 'script': 'Han' if _CJK.fullmatch(m.group()) else 'Latin'}
             for m in re.finditer(r'[\u3400-\u9fff]+|[A-Za-z]+', text)]
    inferred = language
    uncertainty = []
    if inferred is None:
        if any(c in text for c in '嘅咁喺唔啲佢哋咗'): inferred = 'yue'
        elif cjk:
            inferred = 'zh-Hant' if any(c in text for c in '體學國這個為與說') else 'zh-Hans' if any(c in text for c in '体学国这个为与说') else 'zh'
            uncertainty.append('script_language_heuristic')
        else: inferred = 'en' if words else 'und'
    return {'original_text': text, 'normalized_text': normalized, 'language': inferred,
            'tokens': sorted(tokens), 'hashtags': re.findall(r'#[\w\u3400-\u9fff]+', text),
            'code_switch_spans': spans if cjk and words else [],
            'emoji': [c for c in text if unicodedata.category(c) == 'So'],
            'punctuation': [c for c in text if unicodedata.category(c).startswith('P')],
            'uncertainty': uncertainty, 'geography': None}


def _jaccard(a,b):
    return len(a & b)/len(a | b) if a or b else 0.0


def conversation_ids(*, entity_keys, topic_key, episode_anchor, pattern_text, language, scope_key):
    def ident(kind, value): return kind + '_' + canonical_digest([scope_key, value])[:24]
    return {'entity_ids': [ident('entity', e) for e in sorted(set(entity_keys))],
            'topic_id': ident('topic', topic_key), 'episode_id': ident('episode', [topic_key, episode_anchor]),
            'pattern_id': ident('pattern', [language, unicodedata.normalize('NFC', pattern_text)])}


def compare_pair(left, right, *, decision_cutoff, max_gap_hours=48, high_band=.65, low_band=.2, embedding_pair=None, qualification=None, source_policies=None):
    if not 0 <= low_band < high_band <= 1: raise ValueError('invalid similarity bands')
    reason = None
    for row in (left,right):
        if instant(row['available_at']) > instant(decision_cutoff): reason = 'future_input'
        elif row['operation'] == 'delete' or instant(row['retention_until']) <= instant(decision_cutoff): reason = 'unavailable_input'
        elif not source_policy_allowed(row, source_policies, decision_cutoff): reason = 'rights_blocked'
    if left['scope_key'] != right['scope_key']: reason = 'scope_mismatch'
    if reason:
        return {'decision': 'unsure', 'reason': reason, 'method_version': METHOD_VERSION,
                'mode': 'abstained', 'features': None, 'feature_digest': None,
                'decision_at': decision_cutoff, 'input_revision_refs': [],
                'original_features': [], 'semantic_qualification': 'unqualified'}
    a,b = left['payload'], right['payload']
    fa,fb = text_features(a.get('text',''), a.get('language')), text_features(b.get('text',''), b.get('language'))
    entity = _jaccard(set(a.get('entity_keys',[])), set(b.get('entity_keys',[])))
    lexical = _jaccard(set(fa['tokens']), set(fb['tokens']))
    gap = abs((instant(left['event_at'])-instant(right['event_at'])).total_seconds())/3600 if left['event_at'] and right['event_at'] else None
    contradictory = bool(a.get('event_type') and b.get('event_type') and a['event_type'] != b['event_type']) or bool(set(a.get('contradictory_event_markers',[])) & set(b.get('event_markers',[]))) or bool(set(b.get('contradictory_event_markers',[])) & set(a.get('event_markers',[])))
    embedding = None
    mode = 'lexical_only'
    if embedding_pair and a.get('language') == b.get('language'):
        cohort = a.get('language')
        valid = all(qualified_embedding(e, decision_cutoff=decision_cutoff, scope_key=left['scope_key'], cohort=cohort, qualification=qualification, source_policies=source_policies) and e.get('input_revision_identity') == row['revision_identity'] for e,row in zip(embedding_pair,(left,right)))
        if valid and len(embedding_pair) == 2:
            embedding = cosine_similarity(embedding_pair[0]['vector'], embedding_pair[1]['vector'])
            mode = 'qualified_embedding' if embedding is not None else mode
    same_source = left['provider_id'] == right['provider_id'] and left['source_identity'] == right['source_identity']
    if reason: decision = 'unsure'
    elif same_source: decision,reason = 'same_conversation','same_source_identity'
    elif contradictory or (gap is not None and gap > max_gap_hours): decision,reason = 'different_conversation','different_event_or_episode'
    elif gap is None: decision,reason = 'unsure','event_time_unknown'
    elif lexical >= high_band: decision,reason = 'same_conversation','lexical_high_band'
    elif embedding is not None and embedding >= .9 and lexical >= low_band: decision,reason = 'same_conversation','qualified_embedding_high_band'
    elif lexical <= low_band and (embedding is None or embedding < .5): decision,reason = 'different_conversation','lexical_low_band'
    else: decision,reason = 'unsure','uncertainty_band'
    features = {'entity_overlap': entity, 'lexical_similarity': lexical, 'embedding_similarity': embedding,
                'event_gap_hours': gap, 'same_platform': a.get('platform') == b.get('platform'),
                'same_community': a.get('community') == b.get('community'), 'contradictory_event': contradictory}
    return {'decision': decision, 'reason': reason, 'method_version': METHOD_VERSION, 'mode': mode,
            'features': features, 'feature_digest': canonical_digest(features), 'decision_at': decision_cutoff,
            'input_revision_refs': [left['revision_identity'],right['revision_identity']],
            'original_features': [fa,fb], 'semantic_qualification': 'unqualified' if mode == 'lexical_only' else 'cohort_qualified'}


def candidate_pairs(observation, candidates, *, decision_cutoff, limit=20, source_policies=None):
    if not 1 <= limit <= 100: raise ValueError('bounded candidate limit required')
    results = []
    for candidate in candidates:
        pair = compare_pair(observation, candidate, decision_cutoff=decision_cutoff, source_policies=source_policies)
        if pair['reason'] in ('future_input','scope_mismatch','rights_blocked','unavailable_input'): continue
        if pair['features']['lexical_similarity'] or pair['features']['entity_overlap'] or pair['reason'] == 'same_source_identity':
            results.append({'candidate_id': candidate['observation_id'], **pair})
    return sorted(results, key=lambda r: (-r['features']['lexical_similarity'], r['candidate_id']))[:limit]


def apply_semantic_choice(pair, *, choice, existing_candidate_ids):
    """Only uncertain proposals accept an existing candidate ID; no model authority."""
    result = deepcopy(pair)
    if pair['decision'] != 'unsure' or pair['reason'] != 'uncertainty_band':
        result['semantic_choice'] = 'not_applicable'
    elif choice in existing_candidate_ids:
        result['semantic_choice'] = choice
    else:
        result['semantic_choice'] = 'unsure'
    return result
