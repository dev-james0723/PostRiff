"""Synthetic Radar providers and models; no credentials or network access."""
import time,json
from growth_phase2_fixtures import ENV as BASE, Models as BaseModels, Writer
from postriff_phase2.growth import jev
from postriff_phase2.radar.sources import rights
ENV={**BASE,'POSTRIFF_RADAR':'1','POSTRIFF_RADAR_QUICK_USD_CAP':'1','POSTRIFF_RADAR_DEEP_USD_CAP':'3','POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP':'50','POSTRIFF_RADAR_MONITORING':'1'}
TITLES=['A quieter practice routine for busy adults','Why a piano practice journal makes room for discovery','Slow practice and the art of listening','A fresh approach to beginner piano lessons','Practice with a friend, one small step at a time','Can a shorter practice session change your focus?']
class Sources:
    def __init__(self,clock=time.time):self.clock=clock;self.calls=[];self.before=None;self.failure=False
    def ceiling(self,source):return 0
    def catalog(self):return [{'id':s,'name':n,'status':'ready','maxRequestUsdMicro':0,'note':'Synthetic official-shaped test evidence'} for s,n in [('news','News · GDELT'),('bluesky','Bluesky'),('youtube','YouTube charts')]]
    def verify(self,item):
        self.calls.append(('verify',item['id'],1));return {'status':'present','costUsdMicro':0}
    def search(self,source,query,limit):
        self.calls.append((source,query,limit))
        if self.before:fn,self.before=self.before,None;fn()
        if self.failure:raise TimeoutError('Synthetic source timeout')
        return {'items':[{'url':f'https://source{i}.example.org/{source}/practice','nativeId':source+str(i),'title':title,'excerpt':'A practice question supported by a small original demonstration.','author':f'creator-{i}',
                          'publishedAt':self.clock()-i*3600,'rights':rights(derive=source!='youtube',metrics=source!='youtube'),'metrics':{'likes':12+i},'coverage':'official_post' if source=='bluesky' else 'search_lead'} for i,title in enumerate(TITLES)][:limit], 'costUsdMicro':0,'costSource':'synthetic'}
class Models(BaseModels):
    def evaluate(self,state,questions,*,timeout_s):
        if 'useful' not in questions:return super().evaluate(state,questions,timeout_s=timeout_s)
        self.calls.append(('radar',state))
        if self.before:fn,self.before=self.before,None;fn()
        return jev.RawEvaluation('typesafe-ai/jev',{n:{'type':'boolean','probability':.01 if n=='sensitive' else .95} for n in questions},100,0,0.00001,'table:synthetic','fixture-radar','fixture',1)
    def chat(self,messages,model,max_tokens,timeout_s):
        data=json.loads(messages[-1]['content'])
        if 'topic' not in data:return super().chat(messages,model,max_tokens,timeout_s)
        self.calls.append(('analysis',model))
        return json.dumps({'angle':'What can a small practice experiment teach your audience?','evidenceIds':[data['evidence'][0]['id']]}),{'cost':.001}
