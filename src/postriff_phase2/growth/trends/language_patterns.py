"""Native phrase-change evidence, separate from narrative or cultural interpretation."""
from collections import Counter, defaultdict
from . import context, contracts, culture

VERSION = 'native-pattern-windows-v1'


def project(inputs):
    frame = inputs['frame']; start = context.timestamp(frame['window_start']); end = context.timestamp(frame['window_end'])
    prior = start-(end-start)
    sources = context.source_index(inputs['common'], 'creative', originals=True)
    current, before, seen = [], [], set()
    for sid,s in sorted(sources.items()):
        text = inputs['facts'][sid].get('text'); at = context.timestamp(s['event_at'])
        key = context.canonical_key(s)
        if not isinstance(text,str) or len(text)>16000 or key in seen:
            continue
        seen.add(key)
        item = {'observation_id':sid,'payload':{'text':text}}
        if start<=at<end: current.append(item)
        elif prior<=at<start: before.append(item)
    def complete(a,b):
        return any(w.get('comparison_digest')==frame['frame_id']
            and context.timestamp(w['window_start'])==a and context.timestamp(w['window_end'])==b
            and w.get('data_state')=='qualified' and w.get('coverage',{}).get('completeness')=='complete_within_scope'
            for w in inputs['history_windows'])
    comparable = complete(prior,start) and complete(start,end)
    baseline = Counter()
    for o in before:
        baseline.update(culture.extract(o['payload']['text'])['features'])
    if comparable:
        for o in current:
            for feature in culture.extract(o['payload']['text'])['features']:
                baseline.setdefault(feature,0)
    # Existing native detection runs before any gloss or semantic explanation.
    recurrence = culture.repeated_patterns(current, baseline=dict(baseline) if comparable else None)
    groups = defaultdict(set); examples = {}
    for o in current:
        sid = o['observation_id']; text = o['payload']['text']; x = culture.extract(text)
        features = [('phrase',f) for f in x['features']]
        features += [('emoji',s['text']) for s in x['emoji']]
        features += [('punctuation',f) for f in x['punctuation']]
        features += [('hashtag',f) for f in x['hashtags']]
        spans = x['spans']
        for size in (2,3):
            for i in range(max(0,len(spans)-size+1)):
                a,b = spans[i]['start'], spans[i+size-1]['end']
                if b-a<=120: features.append(('collocation',text[a:b]))
        opening = text.splitlines()[0] if text else ''
        if 3<=len(opening)<=120: features.append(('opening_template',opening))
        for kind,feature in sorted(set(features))[:128]:
            key = (sources[sid]['language'],kind,feature)
            groups[key].add(sid)
            # Keep the first exact native instance even for casefolded lexical features.
            if feature in text:
                examples.setdefault(key,feature)
            elif kind=='phrase':
                native=next((s['text'] for s in x['spans'] if s['text'].casefold()==feature),None)
                if native: examples.setdefault(key,native)
    patterns=[]
    for (language,kind,feature),refs in sorted(groups.items()):
        if len(refs)<3: continue
        refs=sorted(refs); creators={context.creator_key(sources[r]) for r in refs if context.creator_key(sources[r])}
        old = baseline.get(feature,0) if comparable and kind=='phrase' else None
        patterns.append({'id':contracts.digest([VERSION,frame['frame_id'],language,kind,feature]),
            'kind':kind,'expression':examples.get((language,kind,feature),feature),'language':language,
            'observation_count':len(refs),'known_creators':len(creators),'evidence_refs':refs,
            'baseline_count':old,'change':len(refs)-old if old is not None else None,
            'current_window':{'start':frame['window_start'],'end':frame['window_end']},
            'baseline_window':{'start':contracts.iso(prior),'end':frame['window_start']},
            'coverage_comparable':comparable,'semantic_qualification':'lexical_only','meaning':None,'origin':None,
            'displayable':all(sources[r]['rights'].get('display') is True for r in refs)})
    return {'method_version':VERSION,'frame':frame,'patterns':patterns[:100],'truncated':len(patterns)>100,
        'phrase_recurrence':recurrence[:100],'counts_are':'unique_retained_original_posts',
        'interpretation':'unknown','comparison':'same platform, declared language, community and acquisition frame',
        'limitations':['Lexical recurrence does not establish cultural meaning, intent or origin.',
                       'Missing or incomplete comparable history produces no burst/change claim.']}


def wire(raw):
    return [{'id':p['id'],'expression':p['expression'],'language':p['language'],
        'context':f"Observed in {p['observation_count']} retained original posts during {p['current_window']['start']} to {p['current_window']['end']}.",
        'meaning':'Not interpreted; original wording only.',
        'uncertainty':'Native meaning is unreviewed. '+('Comparable history is available in measurement details.' if p['coverage_comparable'] else 'Comparable history is unavailable.'),
        'evidence':[{'id':r,'display_state':'restricted','reason':'Inspect the current trend receipt for permitted evidence.'} for r in p['evidence_refs'][:20]],
        'derivation_kind':'deterministic_extraction','empirically_qualified':False}
        for p in raw['patterns'] if p['displayable']][:20]
