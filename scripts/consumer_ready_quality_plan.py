"""Build a reviewable, priced evaluation packet. Offline only; has no execute mode."""
import hashlib
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from postriff_phase2.model_runtime import DEFAULT_ENDPOINT, DEFAULT_MODEL, DEFAULT_PRICES, ServerModelRuntime
from postriff_phase2.skills import SkillLibrary, budget_for

def forbidden(*args,**kwargs):raise AssertionError('Offline evaluation preparation cannot call a provider')

runtime=ServerModelRuntime('synthetic-quote-only',transport=forbidden)
library=SkillLibrary()
facts_en=['This is a fictional community music workshop used only for evaluation.', 'The workshop is on 10 April 2027, from 14:00 to 15:00 at Example Community Room.', 'The workshop teaches beginners to listen for rhythm and practise a four-bar phrase.', 'Registration and ticket prices have not been decided.']
facts_zh=['這是僅用於評測的虛構社區音樂工作坊。','工作坊於 2027 年 4 月 10 日下午 2 時至 3 時在示例社區活動室舉行。','內容是讓初學者聆聽節奏，並練習四小節樂句。','報名方法及票價尚未決定。']
cases=[]
for locale,facts in [('en-GB',facts_en),('zh-Hant-HK',facts_zh)]:
 for platform in ['LinkedIn','Threads','Instagram']:
  variants=['neutral','personalized'] if platform in ('LinkedIn','Threads') else ['neutral']
  for mode in variants:
   identifier=f'{locale}-{platform}-{mode}'
   source={'id':identifier,'policy':'public_quote','candidateOnly':False,'hash':hashlib.sha256(json.dumps(facts).encode()).hexdigest(),'facts':[{'id':f'f{i}','sourceId':identifier,'text':text,'locator':f'authored-evaluation:{i}'} for i,text in enumerate(facts)]}
   destinations=[{'platform':platform,'language':locale}]
   request={'context':{'schema':'postriff.context.v1','operation':'draft','providerClass':'cloud','policyEpoch':'evaluation-only','candidateOnly':False,'sources':[source],'excluded':[]},'idea':'Write a clearly fictional workshop announcement using only these facts. Do not invent a booking link, teacher name, price or participant quote.','tone':'warm and plain','destinations':destinations,'reasoning':'standard','model':DEFAULT_MODEL,'memory':[], 'styleDirectives':{'shortOpenings':True,'shortParagraphs':True,'usesEmoji':False,'usesHashtags':False} if mode=='personalized' else {},'skills':library.bind(destinations,None,'draft',None,max_chars=budget_for('paid'))}
   quote=math.ceil(runtime.price_quote(request)*1_000_000)
   cases.append({'id':identifier,'mode':mode,'sourceRights':'Original synthetic text authored for this evaluation; no user/private/customer source','request':request,'requestSha256':hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'maximumReservationUsdMicro':quote})
result={'status':'AWAITING_APPROVAL','execution':'offline preparation; zero external calls','endpoint':DEFAULT_ENDPOINT,'model':DEFAULT_MODEL,'priceUsdPerMillionTokens':DEFAULT_PRICES[DEFAULT_MODEL],'priceVerification':'Recheck official model catalogue immediately before approved execution','cases':cases,'calls':len(cases),'maximumProviderAttempts':len(cases)*2,'totalMaximumReservationUsdMicro':sum(c['maximumReservationUsdMicro'] for c in cases),'authorization':'Exact model, endpoint, corpus hash and total ceiling require user approval. No retries outside the runtime bound. Unknown usage remains reserved.','humanEvaluation':'NOT_RUN'}
out=ROOT/'docs/consumer-ready/quality-evaluation.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('status','execution','model','calls','maximumProviderAttempts','totalMaximumReservationUsdMicro')}))
