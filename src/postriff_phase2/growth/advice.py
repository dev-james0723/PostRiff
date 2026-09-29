"""Deterministic advice selection and conservative, order-checked comparison."""
from .advice_context import GOALS

PRIORITIES = {
    'conversation': ('conversation','audience','clarity','evidence','hook'),
    'shareability': ('shareability','specificity','clarity','evidence','hook'),
    'authority': ('evidence','specificity','novelty','clarity','audience'),
    'reach': ('hook','clarity','shareability','audience','specificity'),
    'general': ('clarity','evidence','specificity','hook','audience'),
}


def prioritize(dimensions, *, goal='general', missing_context=None, limit=3, lang='en'):
    if goal not in GOALS:raise ValueError('Unknown advice goal')
    limit = max(0, min(3, limit))
    zh = lang.startswith('zh')
    actions = [{'dimension':d,'kind':'context',
                'concern':'未有足夠觀眾背景，暫時無法評估。' if zh else 'Audience context is missing; this dimension is unassessed.',
                'change':'喺 Brand & voice 填寫目標觀眾，並確認容許 AI 使用呢份背景。' if zh else 'Describe your audience in Brand & voice and allow AI to use that context.'}
               for d in (missing_context or {})]
    priority=PRIORITIES[goal]
    ordered=sorted(enumerate(dimensions),key=lambda pair:(priority.index(pair[1]['id']) if pair[1]['id'] in priority else len(priority),pair[1].get('level') if pair[1].get('level') is not None else 4,pair[0]))
    seen={a['dimension'] for a in actions}
    for _, dim in ordered:
        if dim['id'] in seen or dim.get('level') is None or not dim.get('fixes'):continue
        actions.append({'dimension':dim['id'],'kind':'improve',
                        'concern':f"{dim['label']}: {dim['levelName']}",'change':dim['fixes'][0]})
        seen.add(dim['id'])
    return actions[:limit]


def comparison_state(original, candidate, *, context, facts, order):
    if order not in ('original_first','candidate_first'):raise ValueError('Invalid comparison order')
    a,b=(original,candidate) if order=='original_first' else (candidate,original)
    return {'versions':{'a':a,'b':b},'context':context,'creatorFacts':facts,
            'identical':original.strip()==candidate.strip()}


def decide(judgment, *, grounded, voice_preserved, swapped=None):
    def result(value, reason):
        return {'recommended':value,'status':'recommended' if value=='candidate' else 'review',
                'reasons':[reason],'orderChecked':swapped is not None}
    def pick(j, reverse=False):
        answer=j.answers.get('preferred')
        if j.status!='ok' or answer is None or answer.abstained:return 'unsure'
        mapping={'a':'candidate' if reverse else 'original','b':'original' if reverse else 'candidate',
                 'equivalent':'equivalent','unsure':'unsure'}
        return mapping.get(answer.value,'unsure')
    if not grounded:return result('original','unsupported_claims')
    if not voice_preserved:return result('unsure','voice_not_preserved')
    first=pick(judgment)
    if swapped is not None and pick(swapped,True)!=first:return result('unsure','order_disagreement')
    return result(first,{'candidate':'criterion_improved','original':'original_preferred','equivalent':'no_material_difference','unsure':'insufficient_evidence'}[first])
