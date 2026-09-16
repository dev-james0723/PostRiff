"""Transport-neutral state machine. Call only inside an authorized transaction."""
import copy
import hashlib
import hmac
import json
import re
import secrets
from postriff_alpha.domain import AlphaError, uid, clean
from postriff_alpha.templates import catalog
from postriff_phase2.content_types import ensure_content_state

TERMINAL = {'completed', 'interrupted', 'revoked', 'expired', 'failed', 'applied'}
ROUTES = {
 'fixture': ('Local conformance preview', 'ready', 'Synthetic text only; zero provider requests.'),
 'codex': ('Codex', 'limited', 'Exec JSON implemented; isolated file access, native auth and paid execution unqualified.'),
 'claude': ('Claude Code', 'limited', 'Bare/no-tools API route implemented; API credentials and bounded execution consent required.'),
 'gemini': ('Gemini', 'limited', 'Structured adapter present; supported API/enterprise auth and isolation unqualified.'),
 'managed': ('Managed writing', 'blocked', 'DeepInfra server adapter prepared; credentials, exact model/cost approval and live qualification pending.'),
}

def digest(value):
 return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def require(condition, message='This item is unavailable.', status=404):
 if not condition: raise AlphaError(message, status)

def initial():
 return {'schema': 1, 'selected': 'fixture', 'devices': [], 'enrollments': [], 'jobs': [], 'operations': [], 'sourceVisibility': {}, 'templateId': None, 'cloudVoiceRevision': None, 'enrollmentAttempts': []}

def item(items, key):
 result=next((x for x in items if x['id']==key),None)
 require(result is not None)
 return result

def snapshot(s, data, source_ids, operation='draft', cloud=False):
 require(isinstance(source_ids,list) and len(source_ids)<=20 and len(set(source_ids))==len(source_ids),'Select at most 20 distinct sources.',400)
 sources=[]
 for source_id in source_ids:
  source=item(s['sources'],source_id)
  require(source['active'],'A selected source was retracted. Select current sources.',409)
  visibility=data['sourceVisibility'].get(source_id,'local_only')
  require(not cloud or visibility=='provider_allowed','A source is local-only. Explicitly synchronize it or use a local route.',409)
  facts=[{'id':f['id'],'text':f['text'],'sourceId':source_id} for f in source['facts'] if f['approved']]
  require(bool(facts),'Approve selected source facts first.',409)
  sources.append({'id':source_id,'visibility':visibility,'facts':facts,'hash':digest(facts)})
 profile=next((v for v in s['speaker']['revisions'] if v['revision']==s['speaker']['activeRevision']),None)
 require(profile is not None,'Approve a voice revision first.',409)
 require(not cloud or data.get('cloudVoiceRevision')==s['speaker']['activeRevision'],'This voice revision is local-only. Explicitly approve it for a managed request.',409)
 skills=[]
 released={t['id']:t for t in catalog()}
 for inst in s['skillInstances']:
  template=released.get(inst['templateId'])
  require(template and template['version']==inst['templateVersion'],'A selected skill version needs review.',409)
  skills.append({'id':template['id'],'version':template['version'],'instructions':template['instructions'],'overrides':copy.deepcopy(inst['overrides'])})
 system=ensure_content_state(s)
 selection=copy.deepcopy(system['selection'])
 template=None
 if data.get('templateId'):
  chosen=item(system['templates'],data['templateId'])
  require(not chosen['archived'] and chosen['contentTypeId']==selection['contentTypeId'] and chosen['contentTypeVersion']==selection['contentTypeVersion'],'Selected template changed or does not match this type.',409)
  template={k:copy.deepcopy(chosen[k]) for k in ('id','revision','contentTypeId','contentTypeVersion','overrides')}
 # Exact approved revision only, not account/profileSetup/history or private original skills.
 approved_profile={k:copy.deepcopy(profile['profile'][k]) for k in ('tone','observations','preferences','writingExample') if k in profile['profile']}
 value={'schema':'postriff.run-input.v1','workspaceId':s['workspace']['id'],'operation':operation,'brief':copy.deepcopy(s['brief']), 'speakerId':s['speaker']['id'],'voiceRevision':s['speaker']['activeRevision'],'voice':approved_profile,'sources':sources,'skills':skills,'selection':selection,'template':template,'destinations':[{'platform':'LinkedIn','language':'English'},{'platform':'Instagram','language':'繁體中文'}],'permissions':{'tools':[],'publish':False,'network':'selected-model-only','files':[]}}
 if operation=='profile':
  request=s['profileSetup'].get('request')
  require(request is not None,'Prepare the portable profile request first.',409)
  value['profileRequestHash']=request['sha256']
  value['requestedScope']=request['manifest']['allowed_source_scope']
  value['actualAccess']={'selectedSourceIds':source_ids,'history':False,'memory':False,'files':False}
 require(len(json.dumps(value).encode())<=60000,'Selected context exceeds the 60 kB run limit.',413)
 return value

def event(job, kind, at, text=''):
 require(kind in {'waiting','running','text','completed','interrupted','expired','revoked','failed','applied','permission_denied','uncertain'},'Unsupported event.',400)
 seq=len(job['events'])+1
 require(seq<=2000,'Event limit reached.',413)
 record={'id':job['id']+':'+str(seq),'seq':seq,'type':kind,'at':at}
 if text: record['text']=clean(text,12000)
 job['events'].append(record)

def reconcile(data, now):
 for job in data['jobs']:
  if job['status'] in TERMINAL: continue
  if job['expiresAt']<=now:
   job['status']='expired';event(job,'expired',now)
  elif job['status']=='running' and job['leaseUntil']<=now:
   job['status']='interrupted';event(job,'interrupted',now,'Host disconnected. Reconcile the previous request before starting a new run.')

def projection(data, now):
 result=copy.deepcopy(data)
 result.pop('enrollments',None); result.pop('enrollmentAttempts',None)
 for d in result['devices']:
  d.pop('credentialHash',None)
  d['connection']='revoked' if d['status']=='revoked' else ('online' if d['lastSeen']+45>now else 'offline')
 result['routes']=[{'id':key,'label':v[0],'status':v[1],'detail':v[2],'authenticated':'unverified','qualified':key=='fixture','usage':'Unavailable' if key!='fixture' else 'Measured locally: no model request'} for key,v in ROUTES.items()]
 result['execution']='local-contracts';result['hostedAcceptance']='pending'
 return result

def artifact(value, manifest):
 require(isinstance(value,dict) and set(value)=={'variants'},'Expected only structured draft variants.',400)
 require(isinstance(value['variants'],list) and len(value['variants'])==2,'Expected two destination variants.',400)
 output=[]; seen=set(); allowed={s['id'] for s in manifest['sources']}
 for variant in value['variants']:
  require(isinstance(variant,dict) and set(variant)=={'platform','language','text','sourceIds','unknowns'},'Unexpected artifact fields or authority.',400)
  pair=(variant['platform'],variant['language'])
  require(pair in {('LinkedIn','English'),('Instagram','繁體中文')} and pair not in seen,'Invalid destination.',400);seen.add(pair)
  require(isinstance(variant['sourceIds'],list) and set(variant['sourceIds'])<=allowed,'Unknown source reference.',400)
  require(isinstance(variant['unknowns'],list) and len(variant['unknowns'])<=20,'Invalid unknowns.',400)
  output.append({**variant,'text':clean(variant['text'],12000),'unknowns':[clean(x,1000) for x in variant['unknowns']]})
 require(all(v['text'] for v in output),'No usable draft returned.',400)
 return {'variants':output}

def apply(s,data,actor,action,p,now,desktop=False):
 reconcile(data,now)
 if action=='select':
  require(p.get('route') in ROUTES,'Choose an available route.',400);data['selected']=p['route']
 elif action=='profile_visibility':
  require(p.get('confirmed') is True and p.get('voiceRevision')==s['speaker']['activeRevision'],'Confirm the current voice revision.',409)
  data['cloudVoiceRevision']=p['voiceRevision'] if p.get('allowCloud') is True else None
 elif action=='select_template':
  if p.get('templateId') is None:data['templateId']=None
  else:
   chosen=item(ensure_content_state(s)['templates'],p['templateId'])
   require(not chosen['archived'] and (chosen['ownerUserId']==actor or chosen['visibility']=='workspace'))
   data['templateId']=chosen['id']
 elif action=='source_visibility':
  source=item(s['sources'],p.get('sourceId'));require(source['active'])
  require(p.get('visibility') in ('local_only','provider_allowed') and p.get('confirmed') is True,'Confirm this source visibility change.',400)
  data['sourceVisibility'][source['id']]=p['visibility']
 elif action=='enroll':
  require(len([e for e in data['enrollments'] if e['expiresAt']>now and e['actor']==actor])<5,'Too many enrollment requests. Wait five minutes.',429)
  code=secrets.token_hex(8).upper()
  entry={'id':uid(),'actor':actor,'name':clean(p.get('name','My desktop'),60),'codeHash':digest(code),'expiresAt':now+300,'used':False}
  data['enrollments'].append(entry)
  return {'enrollment':{'id':entry['id'],'code':code,'name':entry['name'],'workspaceId':s['workspace']['id'],'expiresAt':entry['expiresAt']}}
 elif action=='pair':
  require(desktop,'Confirm enrollment in the signed-in desktop app.',403)
  attempts=[x for x in data['enrollmentAttempts'] if x['at']>now-300 and x['actor']==actor]
  require(len(attempts)<5,'Too many attempts. Wait five minutes.',429)
  data['enrollmentAttempts'].append({'actor':actor,'at':now})
  entry=next((x for x in data['enrollments'] if x['actor']==actor and x['id']==p.get('enrollmentId') and x['codeHash']==digest(p.get('code')) and not x['used'] and x['expiresAt']>now),None)
  # Return a failure result so the attempt counter commits even on rejection.
  if entry is None: return {'pairingRejected':True}
  require(p.get('confirmedWorkspace')==s['workspace']['id'] and p.get('confirmedName')==entry['name'],'Desktop confirmation changed.',409)
  secret=secrets.token_urlsafe(32);entry['used']=True
  device={'id':uid(),'actor':actor,'name':entry['name'],'credentialHash':digest(secret),'status':'active','lastSeen':now,'capabilities':['draft','profile'],'createdAt':now}
  data['devices'].append(device)
  return {'deviceId':device['id'],'deviceCredential':secret}
 elif action=='revoke':
  d=item(data['devices'],p.get('deviceId'));require(d['actor']==actor)
  d['status']='revoked'
  for job in data['jobs']:
   if job['deviceId']==d['id'] and job['status'] not in TERMINAL:
    job['status']='revoked';event(job,'revoked',now,'New claims and writes stopped; already-started provider requests may still incur usage.')
 elif action=='prepare':
  route=p.get('route',data['selected']);require(route in ROUTES,'Unknown runtime.',400)
  operation=p.get('operation','draft');require(operation in ('draft','profile'),'Unsupported operation.',400)
  if data.get('templateId'):
   chosen=item(ensure_content_state(s)['templates'],data['templateId'])
   require(chosen['ownerUserId']==actor or chosen['visibility']=='workspace')
  manifest=snapshot(s,data,p.get('sourceIds',[]),operation,route=='managed')
  key=clean(p.get('idempotencyKey',''),100);require(bool(key),'An idempotency key is required.',400)
  binding={'manifest':manifest,'route':route,'deviceId':p.get('deviceId'),'actor':actor}
  existing=next((j for j in data['jobs'] if j['key']==key),None)
  if existing:
   require(existing['bindingHash']==digest(binding),'This request key belongs to different content.',409)
   return {'runId':existing['id']}
  require(len(data['jobs'])<100,'Export retained work before creating more runs.',409)
  if p.get('deviceId'):
   d=item(data['devices'],p['deviceId']);require(d['status']=='active' and d['actor']==actor)
  job={'id':uid(),'key':key,'bindingHash':digest(binding),'actor':actor,'deviceId':p.get('deviceId'),'route':route,'manifest':manifest,'inputHash':digest(manifest),'status':'prepared','createdAt':now,'expiresAt':now+900,'leaseUntil':0,'attempt':None,'events':[],'artifact':None,'usage':{'provenance':'Unavailable'},'allowanceCharged':False}
  data['jobs'].append(job);return {'runId':job['id']}
 elif action=='start':
  job=item(data['jobs'],p.get('runId'));require(job['actor']==actor)
  require(p.get('inputHash')==job['inputHash'] and p.get('consent') is True,'Review and approve the exact input first.',409)
  require(job['status'] not in ('expired','revoked','interrupted','failed'),'This run cannot restart. Prepare a new request after reconciliation.',409)
  if job['status']!='prepared': return {'runId':job['id']}
  require(job['route']=='fixture','Real runtime requires server-side qualification and exact provider/cost authorization.',409)
  require(job['inputHash']==digest(snapshot(s,data,[x['id'] for x in job['manifest']['sources']],job['manifest']['operation'])),'The approved input changed; prepare again.',409)
  job['status']='waiting';event(job,'waiting',now)
 elif action=='cancel':
  job=item(data['jobs'],p.get('runId'));require(job['actor']==actor)
  if job['status'] not in TERMINAL:
   job['status']='interrupted';event(job,'interrupted',now,'Canceled. Partial text retained; no automatic retry.')
 elif action=='apply':
  job=item(data['jobs'],p.get('runId'));require(job['actor']==actor)
  require(job['status'] in ('completed','applied') and job['artifact'] is not None,'No completed candidate to review.',409)
  require(p.get('artifactHash')==digest(job['artifact']),'Review the exact candidate.',409)
  if job['status']=='applied': return
  require(job['inputHash']==digest(snapshot(s,data,[x['id'] for x in job['manifest']['sources']],job['manifest']['operation'],job['route']=='managed')),'Sources, voice or type changed. Preserve the candidate and prepare current context.',409)
  if job['manifest']['operation']=='profile':
   from postriff_alpha import profiles
   profiles.apply(None,s,'profile_import',{'content':job['artifact']})
  else:
   for candidate in job['artifact']['variants']:
    old=next((v for v in s['variants'] if v['platform']==candidate['platform'] and v['language']==candidate['language']),None)
    m=job['manifest']; values={**candidate,'openings':[],'voiceRevision':m['voiceRevision'],'briefRevision':m['brief']['revision'],'runId':job['id']}
    if old:
     old['proposedUpdate']={**values,'baseVariantRevision':old['revision']};old['needsReview']=True
    else:
     s['variants'].append({**values,'id':uid(),'revision':1,'speakerId':m['speakerId'],'customized':False,'needsReview':True,'blockedByRetraction':False,'selectedOpening':0,'warnings':['Synthetic runtime candidate. Review facts and language.'] if job['route']=='fixture' else ['Agent candidate; review facts and language.'],'revisions':[{'revision':1,'text':candidate['text'],'origin':'runtime-candidate'}],'localPreferences':{},**m['selection'],'provenance':{'inputHash':job['inputHash'],'skills':m['skills']}})
  job['status']='applied';event(job,'applied',now)
 elif action=='sync_edit':
  key=clean(p.get('idempotencyKey',''),100);require(key,'Idempotency key required.',400)
  binding=digest(p);previous=next((x for x in data['operations'] if x['id']==key),None)
  if previous: require(previous['hash']==binding,'Operation key changed.',409);return
  variant=item(s['variants'],p.get('variantId'))
  require(type(p.get('variantRevision')) is int and variant['revision']==p['variantRevision'],'Conflict: your local text is retained. Review the current saved variant.',409)
  text=clean(p.get('text'),12000);variant.update({'text':text,'revision':variant['revision']+1,'customized':True,'needsReview':True})
  variant['revisions'].append({'revision':variant['revision'],'text':text,'origin':'explicit-sync'})
  data['operations'].append({'id':key,'hash':binding,'actor':actor,'variantId':variant['id'],'variantRevision':variant['revision']})
 else: raise AlphaError('Unsupported runtime action.',404)


def device_action(s,data,device_id,credential,action,p,now):
 reconcile(data,now)
 d=next((x for x in data['devices'] if x['id']==device_id),None)
 require(d and d['status']=='active' and hmac.compare_digest(d['credentialHash'],digest(credential)))
 # Caller must separately verify the owning actor is still an active workspace member.
 d['lastSeen']=now
 if action=='heartbeat': return {'deviceId':d['id'],'status':'online'}
 if action=='discover': return {'jobs':[{'id':j['id'],'route':j['route'],'status':j['status']} for j in data['jobs'] if j['deviceId']==device_id and j['actor']==d['actor'] and j['status'] in ('waiting','running')]}
 job=item(data['jobs'],p.get('runId'))
 require(job['deviceId']==device_id and job['actor']==d['actor'])
 if action=='events':
  cursor=p.get('cursor',0);require(type(cursor) is int and cursor>=0,'Invalid event cursor.',400)
  return {'events':[e for e in job['events'] if e['seq']>cursor],'status':job['status']}
 require(job['expiresAt']>now and job['status'] not in TERMINAL,'This run is no longer writable.',409)
 require(job['inputHash']==digest(snapshot(s,data,[x['id'] for x in job['manifest']['sources']],job['manifest']['operation'],job['route']=='managed')),'Run context changed.',409)
 if action=='claim':
  if job['status']=='running': return {'start':False,'runId':job['id'],'status':'reconcile-required'}
  require(job['status']=='waiting','Run is not waiting.',409)
  job.update({'status':'running','attempt':uid(),'leaseUntil':now+60});event(job,'running',now)
  return {'start':True,'attempt':job['attempt'],'input':job['manifest'],'route':job['route']}
 require(p.get('attempt')==job['attempt'] and job['status']=='running' and job['leaseUntil']>now,'Obsolete attempt.',409)
 if action=='renew': job['leaseUntil']=min(now+60,job['expiresAt']);return {'status':'running'}
 if action=='partial':
  seq=p.get('sequence');require(type(seq) is int and seq>=1,'Invalid sequence.',400)
  previous=next((e for e in job['events'] if e.get('nativeSequence')==seq),None)
  text=clean(p.get('text'),12000)
  if previous: require(previous.get('text')==text,'Event replay changed.',409);return {'duplicate':True}
  event(job,'text',now,text);job['events'][-1]['nativeSequence']=seq
  return {'cursor':len(job['events'])}
 if action=='complete':
  value=artifact(p.get('artifact'),job['manifest'])
  job['artifact']=value;job['status']='completed';job['artifactHash']=digest(value)
  # Model usage must be reported by trusted worker code, never trusted from external agents.
  job['usage']={'provenance':'measured_locally','modelRequests':0} if job['route']=='fixture' else {'provenance':'Unavailable'}
  event(job,'completed',now);return {'artifactHash':job['artifactHash']}
 raise AlphaError('Unsupported device operation.',404)
