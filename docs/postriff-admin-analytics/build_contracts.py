"""Authoring helper for candidate contracts. No app mutation, network, or live data."""
from pathlib import Path
import json
P=Path(__file__).parent/'contracts'
def write(name,obj): (P/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
rows=[]
def metric(key,label,unit,kind,native,provider='postriff',grains=None,docs=True,phase='D1',formula=None):
 rows.append(dict(key=key,version=1,label=label,provider=provider,nativeMetric=native,unit=unit,aggregationKind=kind,
                  allowedGrains=grains or ['period'],documentationVerified=docs,liveQualified=False,releasePhase=phase,
                  crossPlatformSum=False,crossTenantSocialAggregate=False,derivedAllowed=provider=='postriff',
                  formula=formula,missing='null_with_reason',policyGate=provider+'.native-only.v1' if provider!='postriff' else 'postriff.first-party.v1'))
for native,label,unit,kind in [('views','YouTube 觀看次數','count','flow'),('engagedViews','YouTube engaged views','count','flow'),('estimatedMinutesWatched','原生觀看分鐘','minutes','flow'),('averageViewDuration','原生平均觀看時間','seconds','provider_ratio'),('averageViewPercentage','原生平均觀看百分比','percent','provider_ratio'),('likes','YouTube likes','count','flow'),('comments','YouTube comments','count','flow'),('shares','YouTube shares','count','flow'),('subscribersGained','原生新增訂閱','count','flow'),('subscribersLost','原生減少訂閱','count','flow')]:
 metric('youtube.'+native,label,unit,kind,native,'youtube',['day','period'])
for native in ['views','reach','likes','comments','saved','shares','follower_count']:
 metric('instagram.'+native,'Instagram '+native,'count','non_additive' if native in ('reach','follower_count') else 'native_unqualified',native,'instagram',['candidate_only'],False,'D2')
for native in ['IMPRESSION','MEMBERS_REACHED','REACTION','COMMENT','RESHARE','POST_SAVE','LINK_CLICKS']:
 metric('linkedin.'+native,'LinkedIn '+native,'count','non_additive' if native=='MEMBERS_REACHED' else 'native_total',native,'linkedin',['period','lifetime'],True,'D2')
first=[('useful_users','有用內容用戶','count','distinct'),('activation','激活 n/d','ratio','ratio'),('d7_return','成熟D7 n/d','ratio','ratio'),('repeat_3_of_4','四週3週有用','ratio','ratio'),('edit_reduction','配對編輯時間下降中位數','ratio','paired_median'),('task_time','完整task時間','seconds','median'),('offer_selected','選擇同一方案','count','distinct'),('paid_workspaces','實付workspace','count','stock'),('mrr','MRR','currency','stock'),('cash_received','已收現金','currency','flow'),('refunds','退款','currency','flow'),('direct_contribution','直接貢獻','currency','derived'),('full_result','完整經濟結果','currency','derived'),('cost_per_useful_batch','每有用批次成本','currency','ratio'),('full_cac','全成本CAC','currency','ratio'),('support_minutes','客服時間','minutes','flow'),('sync_lag','同步延遲','seconds','p95'),('unknown_publish','發布結果未知','count','stock')]
formulas={
 'useful_users':'count distinct participants with user useful=yes in selected complete window',
 'activation':'activated participants / eligible material-providing trial starters in fixed cohort',
 'd7_return':'mature activated participants completing a useful new-material task in (activation, activation+7d] / all mature activated participants',
 'repeat_3_of_4':'mature activated participants useful in >=3 of four consecutive 7-day windows / all 28-day mature activated participants; report gate requires denominator>=10',
 'edit_reduction':'median per-participant (baseline_edit_seconds-trial_edit_seconds)/baseline_edit_seconds; paired, baseline>0',
 'task_time':'median complete-task elapsed seconds including preparation, waiting, editing, checking and export; measurement method disclosed',
 'offer_selected':'count distinct activated participants selecting the same offered price version; exposure and all activated denominators shown separately',
 'paid_workspaces':'distinct workspaces with settled payment and valid paid entitlement at asOf; refunded/void transactions reconciled',
 'mrr':'sum normalized active recurring subscription net amounts in one currency at asOf; excludes service fees and creator platform revenue',
 'cash_received':'sum settled incoming payments by settlement date in one currency; refunds separately shown',
 'refunds':'sum settled refund amounts by settlement date in one currency',
 'direct_contribution':'earned net subscription revenue - direct variable paid-service costs; report measured/estimated coverage',
 'full_result':'direct contribution - trial costs - acquisition costs - unallocated fixed operations - unpaid founder opportunity cost; each ledger line allocated once',
 'cost_per_useful_batch':'all attributable successful and failed cohort operation costs, analytics and support / user-accepted batches; zero denominator undefined',
 'full_cac':'attributable acquisition cash and labor cost / new paid customers of the same mature acquisition cohort; zero denominator undefined',
 'support_minutes':'sum non-overlapping categorized support work minutes in window',
 'sync_lag':'p95 ingestion time minus scheduled eligible sync time; blocked jobs separately counted',
 'unknown_publish':'count publish intents currently outcome_unknown at asOf; never infer confirmed publication from HTTP success',
}
for n,label,u,k in first: metric('postriff.'+n,label,u,k,None,phase='D3' if n not in ('mrr','cash_received','refunds','full_cac') else 'D4',formula=formulas[n])
write('metric-registry.json',{'schema':'postriff.metric-registry.v1','status':'candidate','selectedProviders':['youtube','instagram','linkedin'],'metrics':rows})
S=lambda **x:dict(type='string',**x)
N={'type':['integer','null'],'minimum':0}
def obj(props,required=None): return {'type':'object','properties':props,'required':required or list(props),'additionalProperties':False}
status=['measured','not_connected','scope_missing','not_supported','not_applicable','pending_provider','suppressed','stale','error','deleted','unavailable']
decimal=S(pattern=r'^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$')
coverage=obj({'expected':N,'observed':{'type':'integer','minimum':0},'definition':S(),'complete':{'type':'boolean'}})
period=obj({'grain':S(enum=['day','period','lifetime','snapshot']),'start':{'type':['string','null'],'format':'date-time'},'end':{'type':['string','null'],'format':'date-time'},'timezone':S(),'nativePeriodKey':S()})
point=obj({'metricKey':S(),'definitionVersion':{'type':'integer','minimum':1},'accountId':S(),'objectKey':S(),'value':{'oneOf':[decimal,{'type':'null'}]},'valueStatus':S(enum=status),'unit':S(),'sourceKind':S(enum=['provider_api','native_export','manual_entry','first_party']),'execution':S(enum=['live','synthetic']),'freshness':S(enum=['fresh','stale','unknown']),'period':period,'observedAt':S(format='date-time'),'availableThrough':{'type':['string','null'],'format':'date-time'},'coverage':coverage,'evidenceRef':S(),'policyVersion':S(),'derived':{'type':'boolean'},'lastKnownValue':{'oneOf':[decimal,{'type':'null'}]}})
point['allOf']=[{'if':{'properties':{'valueStatus':{'const':'measured'}}},'then':{'properties':{'value':decimal}},'else':{'properties':{'value':{'type':'null'}}}}]
point['properties'].update({'dataDomain':S(enum=['first_party','social']), 'workspaceId':{'type':['string','null']}, 'accountId':{'type':['string','null']}, 'currency':{'type':['string','null'],'pattern':'^[A-Z]{3}$'}})
point['required']=list(point['properties'])
point['allOf'] += [
 {'if':{'properties':{'dataDomain':{'const':'social'}}},'then':{'properties':{'workspaceId':S(minLength=1),'accountId':S(minLength=1),'sourceKind':S(enum=['provider_api','native_export','manual_entry'])}},'else':{'properties':{'accountId':{'type':'null'},'sourceKind':{'const':'first_party'}}}},
 {'if':{'properties':{'unit':{'const':'currency'}}},'then':{'properties':{'currency':S(pattern='^[A-Z]{3}$')}},'else':{'properties':{'currency':{'type':'null'}}}},
]
write('metric-point.schema.json',{'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:postriff:candidate:metric-point:v1',**point})
event=obj({'eventId':S(),'schemaVersion':{'const':1},'workspaceId':S(),'operationId':S(),'aggregateId':S(),'aggregateRevision':{'type':'integer','minimum':1},'participantPseudonym':{'type':['string','null']},'taskId':{'type':['string','null']},'kind':S(enum=['source.accepted','generation.requested','generation.started','generation.completed','generation.failed','draft.saved','draft.usefulness_decided','memory.decided','memory.revoked','export.completed','connector.capability_changed','offer.selected','payment.succeeded','payment.refunded']),'occurredAt':S(format='date-time'),'receivedAt':S(format='date-time'),'assisted':S(enum=['self_serve','assisted','unknown']),'execution':S(enum=['live','synthetic']),'emitter':S(enum=['domain_server','billing_verified_handler'])})
write('product-event.schema.json',{'$schema':'https://json-schema.org/draft/2020-12/schema',**event})
example={'metricKey':'youtube.views','definitionVersion':1,'accountId':'synthetic-youtube-account','objectKey':'channel','value':'1200','valueStatus':'measured','unit':'count','sourceKind':'provider_api','execution':'synthetic','freshness':'fresh','period':{'grain':'period','start':'2026-09-01T07:00:00Z','end':'2026-09-08T07:00:00Z','timezone':'America/Los_Angeles','nativePeriodKey':'2026-09-01/2026-09-08'},'observedAt':'2026-09-09T12:00:00Z','availableThrough':'2026-09-08T07:00:00Z','coverage':{'expected':7,'observed':7,'definition':'complete requested native dates','complete':True},'evidenceRef':'synthetic-fetch-1','policyVersion':'youtube.native-only.v1','derived':False,'lastKnownValue':None}
missing={**example,'metricKey':'instagram.reach','accountId':'synthetic-ig-account','value':None,'valueStatus':'scope_missing','freshness':'unknown','availableThrough':None,'coverage':{'expected':None,'observed':0,'definition':'capability not qualified','complete':False},'policyVersion':'instagram.unqualified.v1'}
for p in (example,missing):p.update(dataDomain='social',workspaceId='synthetic-workspace',currency=None)
admin={**example,'metricKey':'postriff.mrr','dataDomain':'first_party','workspaceId':None,'accountId':None,'objectKey':'platform','value':None,'valueStatus':'unavailable','unit':'currency','currency':'USD','sourceKind':'first_party','freshness':'unknown','availableThrough':None,'coverage':{'expected':None,'observed':0,'definition':'billing not integrated; unknown is not zero','complete':False},'policyVersion':'postriff.first-party.v1','derived':True}
write('examples.json',{'status':'synthetic_contract_examples','measured':example,'missing':missing,'zero':{**example,'value':'0'},'stale':{**example,'value':None,'valueStatus':'stale','lastKnownValue':'1200','freshness':'stale'},'admin_unavailable':admin})
# OpenAPI deliberately covers the first vertical slice, not implemented routes.
R=lambda name:{'$ref':'#/components/schemas/'+name}
arr=lambda item:{'type':'array','items':item}
error=obj({'code':S(),'message':S(),'requestId':S(),'retryable':{'type':'boolean'},'retryAt':{'type':['string','null'],'format':'date-time'}})
ctx=obj({'principalId':S(),'view':S(enum=['platform_operations','workspace_analytics']),'workspaceId':{'type':['string','null']},'capabilities':arr(S()),'accountIds':arr(S()),'readiness':obj({'billing':S(),'productEvents':S(),'socialAnalytics':S()}),'execution':S(enum=['live','synthetic'])})
overview=obj({'requestId':S(),'asOf':S(format='date-time'),'scopeHash':S(),'points':arr(R('MetricPoint')),'warnings':arr(S())})
post=obj({'id':S(),'accountId':S(),'provider':S(enum=['youtube','instagram','linkedin']),'providerPostId':S(),'publishedAt':{'type':['string','null'],'format':'date-time'},'origin':S(enum=['postriff_published','postriff_export_linked','native_imported','unknown']),'availability':S(),'linkConfidence':S(enum=['verified','user_reported','unlinked']),'title':S(),'metrics':arr(R('MetricPoint'))})
job=obj({'id':S(),'state':S(enum=['queued','claimed','running','succeeded','partial','retry_wait','auth_blocked','policy_blocked','budget_blocked','dead_letter','canceled']),'consentEpoch':{'type':'integer','minimum':1},'retryAt':{'type':['string','null'],'format':'date-time'},'requestId':S()})
planIn=obj({'accountId':S(),'metricKeys':{'type':'array','items':S(),'minItems':1,'maxItems':12},'since':S(format='date'),'untilExclusive':S(format='date'),'expectedConsentEpoch':{'type':'integer','minimum':1}})
planOut=obj({'planId':S(),'planHash':S(),'maxRequests':{'type':'integer','minimum':0},'maxBillableResources':{'type':'integer','minimum':0},'maxCostMicros':{'type':['integer','null'],'minimum':0},'currency':S(),'consentEpoch':{'type':'integer','minimum':1},'expiresAt':S(format='date-time'),'blockReasons':arr(S())})
submit=obj({'planId':S(),'planHash':S(),'expectedConsentEpoch':{'type':'integer','minimum':1}})
exportIn=obj({'accountId':S(),'metricKeys':{'type':'array','items':S(),'minItems':1,'maxItems':12},'since':S(format='date'),'untilExclusive':S(format='date'),'format':S(enum=['csv','json']),'expectedConsentEpoch':{'type':'integer','minimum':1}})
schemas={'MetricPoint':point,'Error':error,'Context':ctx,'Overview':overview,'Post':post,'Posts':obj({'items':arr(R('Post')),'nextCursor':{'type':['string','null']},'snapshotId':S()}),'SyncPlanInput':planIn,'SyncPlan':planOut,'SyncSubmit':submit,'Job':job,'ExportInput':exportIn,'ExportTicket':obj({'id':S(),'state':S(enum=['queued','running','ready','failed','revoked']),'expiresAt':S(format='date-time'),'requestId':S()})}
paths={}
def endpoint(path,method,operation,permission,response,body=None):
 params=[]
 for token in ['workspaceId','postId','jobId','exportId']:
  if '{'+token+'}' in path: params.append({'name':token,'in':'path','required':True,'schema':S()})
 if method=='get' and operation in ('workspaceOverview','listPosts'):
  params += [{'name':'accountId','in':'query','required':True,'schema':S()},{'name':'since','in':'query','required':True,'schema':S(format='date')},{'name':'untilExclusive','in':'query','required':True,'schema':S(format='date')}]
 if operation=='listPosts': params += [{'name':'limit','in':'query','schema':{'type':'integer','minimum':1,'maximum':200,'default':50}},{'name':'cursor','in':'query','schema':S()}]
 if method=='post' and operation in ('submitSync','createExport'):params.append({'name':'Idempotency-Key','in':'header','required':True,'schema':S(minLength=8,maxLength=128)})
 code='202' if operation in ('submitSync','createExport') else '200'
 responses={code:{'description':'Candidate successful response','content':{'application/json':{'schema':R(response)}}}}
 for c in ['401','403','404','409','422','429','503']:responses[c]={'description':'Structured failure; no private resource leakage','content':{'application/json':{'schema':R('Error')}}}
 op={'operationId':operation,'summary':permission,'x-required-permission':permission,'x-execution-state':'candidate_not_implemented','parameters':params,'responses':responses}
 if body:op['requestBody']={'required':True,'content':{'application/json':{'schema':R(body)}}}
 paths.setdefault(path,{})[method]=op
endpoint('/api/admin/v1/context','get','adminContext','active_admin','Context')
endpoint('/api/admin/v1/overview','get','adminOverview','product.read; finance fields require finance.read','Overview')
b='/api/workspaces/{workspaceId}/analytics/v1'
endpoint(b+'/context','get','workspaceContext','membership AND account_grant','Context')
endpoint(b+'/overview','get','workspaceOverview','analytics.read AND provider_policy','Overview')
endpoint(b+'/posts','get','listPosts','analytics.read AND provider_policy','Posts')
endpoint(b+'/posts/{postId}','get','postDetail','analytics.read; title requires permitted metadata','Post')
endpoint(b+'/sync-plans','post','planSync','analytics.refresh; plan only, no provider call','SyncPlan','SyncPlanInput')
endpoint(b+'/sync-jobs','post','submitSync','analytics.refresh AND approved_budget AND current_consent','Job','SyncSubmit')
endpoint(b+'/sync-jobs/{jobId}','get','getSync','analytics.read','Job')
endpoint(b+'/exports','post','createExport','analytics.export AND current_consent','ExportTicket','ExportInput')
write('openapi.json',{'openapi':'3.1.0','info':{'title':'PostRiff Analytics candidate vertical-slice contract','version':'0.1.0','description':'Design-only. Ten core paths; not a deployed API. Other planned routes in ENGINEERING.md.'},'security':[{'sessionBearer':[]}],'paths':paths,'components':{'securitySchemes':{'sessionBearer':{'type':'http','scheme':'bearer','description':'Existing server-verified session; client metadata grants no roles'}},'schemas':schemas}})
write('provider-capabilities.json',{'schema':'postriff.analytics-capabilities.v1','status':'candidate','providers':[{'provider':p,'selectedByUser':True,'implementationOrder':i+1,'identityVerified':False,'insightsVerified':False,'publishVerified':False,'derivedQualified':False,'crossOwnerAggregateQualified':False,'billingBudgetAuthorizedMicros':0,'documentationState':'partial_source_unavailable' if p=='instagram' else 'official_readable_live_qualification_pending','defaultRecipient':'explicit_authorizing_user_or_permitted_agent','defaultScope':'single_account'} for i,p in enumerate(['youtube','instagram','linkedin'])]})
print(f'Wrote candidate registry ({len(rows)} metrics), schemas, examples and {len(paths)} API paths')
