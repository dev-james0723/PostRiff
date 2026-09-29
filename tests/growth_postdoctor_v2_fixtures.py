"""Deterministic v2 test models; no external calls."""
from growth_phase2_fixtures import Models, ENV as BASE_ENV
from growth_phase1_fixtures import Writer
ENV={**BASE_ENV,"POSTRIFF_POST_DOCTOR_V2":"1"}

class ComparisonModels(Models):
    def __init__(self):super().__init__();self.compare_hook=None
    def evaluate(self,state,questions,**kwargs):
        raw=super().evaluate(state,questions,**kwargs)
        if 'preferred' in questions:
            winner=next((k for k,v in state['versions'].items() if v.startswith('A clearer')),'equivalent')
            raw.answers['preferred']={'type':'choice','choice':winner,'probabilities':{k:float(k==winner) for k in ('a','b','equivalent','unsure')}}
            if self.compare_hook:
                hook,self.compare_hook=self.compare_hook,None;hook()
        return raw

Models=ComparisonModels
