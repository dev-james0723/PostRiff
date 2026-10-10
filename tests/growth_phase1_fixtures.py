"""Deterministic zero-network test adapters. Never imported by the production runtime."""
import json
from postriff_phase2.agent_runtime import FixtureAgentRuntime
from postriff_phase2.growth import jev, router, rewrite

MODEL='fixture/writer'


class Writer(FixtureAgentRuntime):
    provider='vercel-ai-gateway'
    provider_class='cloud'
    cost_class='paid'  # Test the paid-route permission gates without reaching a paid service.
    model=MODEL

    def list_supported_models(self):
        return [{'id':MODEL,'label':'Fixture writer','qualified':True,'costClass':'paid','detail':'Zero-network test writer.'}]


class Models:
    def __init__(self):
        self.calls=[];self.messages=[];self.before=None;self.before_chat=None;self.ungrounded=False

    def evaluate(self,state,questions,*,timeout_s):
        self.calls.append(('evaluate',state))
        if self.before:
            before,self.before=self.before,None
            before()
        answers={}
        for name,question in questions.items():
            question={**question,'name':name}
            if question['type']=='boolean':
                p=.01 if question['name'].startswith('risk_') or (self.ungrounded and question['name']=='claims_supported') else .95
                answers[question['name']]={'type':'boolean','probability':p}
            elif question['type']=='choice':
                options=question.get('choices',question.get('criteria',question.get('options',{})))
                # Evaluation payload uses {name,description} choice records.
                options=[o['name'] if isinstance(o,dict) else o for o in options]
                value=next(o for o in options if o!='unsure')
                answers[question['name']]={'type':'choice','choice':value,'probabilities':{o:float(o==value) for o in options}}
        return jev.RawEvaluation('typesafe-ai/jev',answers,100,0,None,'unknown','fixture-eval','fixture',1)

    def chat(self,messages,model,max_tokens,timeout_s):
        self.calls.append(('chat',model))
        self.messages.append(messages)
        if self.before_chat:
            before,self.before_chat=self.before_chat,None
            before()
        data=json.loads(messages[-1]['content'])
        spans=rewrite.sentences(data['original'])
        changes=[{'index':0,'text':'A clearer opening.','dimension':'hook','usesFacts':[]}]
        if len(spans)>1:changes.append({'index':1,'text':' Keep one practical takeaway.','dimension':'clarity','usesFacts':[]})
        return json.dumps({'changes':changes,'missingFacts':[],'notes':'Fixture rewrite.'}),{}

    def router(self,sink,writer=None):
        tasks=dict(router.TASKS)
        tasks['postdoctor.rewrite']=('chat',writer or MODEL,(),45,4000)
        return router.AIModelRouter(jev=self,chat=self.chat,usage=sink,tasks=tasks,sleep=lambda _:None)


ENV={'POSTRIFF_GROWTH':'1','POSTRIFF_POST_DOCTOR':'1','POSTRIFF_GENOME':'1','POSTRIFF_PUBLIC_POST_DOCTOR':'1',
     'POSTRIFF_GROWTH_DAILY_USD_CAP':'50','POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP':'5',
     'POSTRIFF_PUBLIC_DAILY_USD_CAP':'3','POSTRIFF_PUBLIC_HASH_KEY':'fixture-only-unique-key-not-a-secret-12345'}
