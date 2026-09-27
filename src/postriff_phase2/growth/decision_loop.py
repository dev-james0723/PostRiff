"""Bounded decisions over host-approved IDs. A selector never supplies actions or permissions."""
from dataclasses import dataclass, field


@dataclass
class DecisionLoop:
    limit: int
    events: list = field(default_factory=list)
    seen: set = field(default_factory=set)

    def choose(self, candidates, selected=None):
        if len(self.events) >= self.limit:
            return None
        legal = [c for c in candidates if c not in self.seen]
        if not legal:
            return None
        # Unknown/abstained selector output cannot expand the legal action set.
        choice = selected if selected in legal else legal[0]
        self.seen.add(choice)
        self.events.append({'step':len(self.events)+1,'actionId':choice,
                            'selection':'selector' if selected in legal else 'deterministic',
                            'status':'prepared'})
        return choice

    def finish(self, action_id, status):
        if status not in ('completed','failed','abstained'):
            raise ValueError('Unknown decision status')
        event = next(e for e in self.events if e['actionId']==action_id)
        event['status'] = status
