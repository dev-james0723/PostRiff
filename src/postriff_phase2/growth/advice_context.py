"""Bounded, explicit creator context. No audience inference or metric-derived facts."""
from .questions import digest

GOALS = ('conversation', 'shareability', 'authority', 'reach', 'general')


def build(creator, *, goal='general', format_id='text'):
    if goal not in GOALS:
        raise ValueError('Choose an available advice goal')
    if not isinstance(format_id, str) or not 1 <= len(format_id) <= 80:
        raise ValueError('A bounded format identifier is required')
    source = creator if isinstance(creator, dict) else {}
    bounded = {k: v.strip()[:2000] for k in ('audience', 'purpose', 'subject')
               if isinstance((v := source.get(k)), str) and v.strip()}
    if isinstance(source.get('genome'), (list, tuple)):
        bounded['genome'] = [s.strip()[:1000] for s in source['genome'][:12] if isinstance(s, str) and s.strip()]
    value = {'version': 1, 'goal': goal, 'format': format_id, 'creator': bounded}
    return {**value, 'digest': digest(value)}


def missing(qs, state):
    def present(path):
        value = state
        for part in path.split('.'):
            value = value.get(part) if isinstance(value, dict) else None
        return isinstance(value, str) and bool(value.strip())
    return {dim: paths for dim, spec in qs.dimensions.items()
            if (paths := tuple(p for p in spec.get('needs', ()) if not present(p)))}
