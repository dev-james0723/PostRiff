import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from postriff_alpha.domain import AlphaError
from postriff_phase3.store import Phase3Store
from postriff_phase3 import contracts as c
from postriff_phase3.adapters import RuntimeAdapter,ManagedWriting,FixtureRuntime,ExecutionPermit,read_approved_file
from test_postriff_phase2 import P2Journey

class RuntimeAcceptance(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.now=1800000000.;self.store=Phase3Store(Path(self.tmp.name)/'p3.db',clock=lambda:self.now)
  self.j=P2Journey(self.store).setup();self.other=P2Journey(self.store).setup()
 def tearDown(self):self.tmp.cleanup()
 def command(self,action,**p):
  self.j.refresh();self.j.snapshot=self.store.runtime_action(self.j.id,self.j.token,self.j.snapshot['revision'],action,p)
  return self.j.snapshot.get('runtimeResult',{})
 def prepare(self,key='run-one',route='fixture',device=None):
  result=self.command('prepare',route=route,sourceIds=[s['id'] for s in self.j.state['sources'] if s['active']],operation='draft',idempotencyKey=key,deviceId=device)
  return next(j for j in self.j.state['phase3']['jobs'] if j['id']==result['runId'])
 def pair(self):
  e=self.command('enroll',name='Test desktop')['enrollment'];self.j.refresh()
  response=self.store.runtime_action(self.j.id,self.j.token,self.j.snapshot['revision'],'pair',{'enrollmentId':e['id'],'code':e['code'],'confirmedWorkspace':self.j.id,'confirmedName':e['name']},desktop=True)
  self.j.snapshot=response;return response['runtimeResult'],e
 def start(self,job):self.command('start',runId=job['id'],inputHash=job['inputHash'],consent=True)
 def test_manifest_approved_voice_skills_sources_and_no_private_founder(self):
  j=self.prepare();m=j['manifest'];self.assertEqual(len(m['skills']),3);self.assertEqual(m['voice']['tone'],'warm');self.assertFalse(m['permissions']['publish'])
  raw=json.dumps(m);self.assertNotIn('credentialHash',raw);self.assertNotIn('james-au',raw);self.assertNotIn('profileSetup',raw)
  self.assertEqual([d['language'] for d in m['destinations']],['English','繁體中文'])
 def test_two_workspace_all_runtime_read_write_and_device_isolation(self):
  device,_=self.pair();job=self.prepare(device=device['deviceId']);self.start(job)
  for call in [lambda:self.store.get(self.j.id,self.other.token),lambda:self.store.runtime_action(self.j.id,self.other.token,1,'revoke',{'deviceId':device['deviceId']}),lambda:self.store.device(self.other.id,device['deviceId'],device['deviceCredential'],'heartbeat',{}),lambda:self.store.device(self.j.id,device['deviceId'],'forged','claim',{'runId':job['id']}),lambda:self.store.export(self.j.id,self.other.token)]:
   with self.assertRaises(AlphaError):call()
 def test_pair_single_use_wrong_user_and_browser_rejected(self):
  device,e=self.pair();self.j.refresh()
  p={'enrollmentId':e['id'],'code':e['code'],'confirmedWorkspace':self.j.id,'confirmedName':e['name']}
  with self.assertRaises(AlphaError):self.store.runtime_action(self.j.id,self.j.token,self.j.snapshot['revision'],'pair',p)
  result=self.store.runtime_action(self.j.id,self.j.token,self.j.snapshot['revision'],'pair',p,desktop=True)
  self.assertTrue(result['runtimeResult']['pairingRejected']);self.assertNotIn(device['deviceCredential'],json.dumps(self.store.get(self.j.id,self.j.token)))
 def test_bruteforce_attempts_commit(self):
  for i in range(5):
   self.j.refresh();r=self.store.runtime_action(self.j.id,self.j.token,self.j.snapshot['revision'],'pair',{'code':'wrong'},desktop=True);self.assertTrue(r['runtimeResult']['pairingRejected'])
  self.j.refresh()
  with self.assertRaises(AlphaError):self.store.runtime_action(self.j.id,self.j.token,self.j.snapshot['revision'],'pair',{'code':'wrong'},desktop=True)
 def test_duplicate_prepare_and_changed_request_key(self):
  job=self.prepare();self.assertEqual(self.prepare()['id'],job['id'])
  with self.assertRaises(AlphaError):self.prepare(route='claude')
  self.assertEqual(len(self.j.state['phase3']['jobs']),1)
 def test_claim_replay_events_fencing_and_revocation(self):
  d,_=self.pair();job=self.prepare(device=d['deviceId']);self.start(job)
  def run(action,**p):return self.store.device(self.j.id,d['deviceId'],d['deviceCredential'],action,{'runId':job['id'],**p})
  claim=run('claim');self.assertTrue(claim['start']);self.assertFalse(run('claim')['start'])
  run('partial',attempt=claim['attempt'],sequence=1,text='partial')
  self.assertTrue(run('partial',attempt=claim['attempt'],sequence=1,text='partial')['duplicate'])
  with self.assertRaises(AlphaError):run('partial',attempt='old',sequence=2,text='forged')
  events=run('events',cursor=0)['events'];self.assertEqual(len({e['id'] for e in events}),len(events))
  self.command('revoke',deviceId=d['deviceId'])
  with self.assertRaises(AlphaError):run('complete',attempt=claim['attempt'],artifact=FixtureRuntime().generate(job['manifest']))
  self.assertEqual(self.j.state['phase3']['jobs'][0]['status'],'revoked')
 def test_restart_lease_expiry_never_restarts(self):
  d,_=self.pair();job=self.prepare(device=d['deviceId']);self.start(job)
  self.store.device(self.j.id,d['deviceId'],d['deviceCredential'],'claim',{'runId':job['id']})
  self.now+=61;restarted=Phase3Store(self.store.path,clock=lambda:self.now)
  with self.assertRaises(AlphaError):restarted.device(self.j.id,d['deviceId'],d['deviceCredential'],'claim',{'runId':job['id']})
  self.assertEqual(restarted.get(self.j.id,self.j.token)['state']['phase3']['jobs'][0]['status'],'interrupted')
 def test_expired_job_and_source_retraction_rejected(self):
  job=self.prepare();self.now+=901
  with self.assertRaises(AlphaError):self.command('start',runId=job['id'],inputHash=job['inputHash'],consent=True)
  job=self.prepare('new');self.j.act('retract_source',sourceId=self.j.state['sources'][0]['id'])
  with self.assertRaises(AlphaError):self.start(job)
 def test_fixture_stream_apply_preserves_custom_variant_and_trial(self):
  self.j.act('generate',platform='LinkedIn',language='English');old=self.j.state['variants'][0]
  self.j.act('variant_edit',variantId=old['id'],variantRevision=old['revision'],text='My independent edit')
  before=copy.deepcopy(self.j.state['phase2']['trial']);job=self.prepare();self.start(job)
  for _ in range(3):self.store.fixture_step()
  self.j.refresh();job=self.j.state['phase3']['jobs'][0];self.assertEqual(job['status'],'completed');self.assertTrue(any(e['type']=='text' for e in job['events']))
  self.command('apply',runId=job['id'],artifactHash=job['artifactHash'])
  self.assertEqual(self.j.state['variants'][0]['text'],'My independent edit');self.assertTrue(self.j.state['variants'][0]['proposedUpdate'])
  self.assertEqual(self.j.state['phase2']['trial'],before)
  self.command('apply',runId=job['id'],artifactHash=job['artifactHash']);self.assertEqual(len(self.j.state['variants']),2)
 def test_managed_local_only_exclusion_and_real_execution_block(self):
  with self.assertRaises(AlphaError):self.prepare(route='managed')
  job=self.prepare(route='claude')
  with self.assertRaises(AlphaError):self.start(job)
 def test_sync_conflict_and_idempotency(self):
  self.j.act('generate',platform='LinkedIn',language='English');v=self.j.state['variants'][0]
  p={'idempotencyKey':'edit-1','variantId':v['id'],'variantRevision':v['revision'],'text':'Unsent local text'}
  self.command('sync_edit',**p);self.command('sync_edit',**p)
  with self.assertRaises(AlphaError):self.command('sync_edit',**{**p,'idempotencyKey':'edit-2','text':'other device'})
  self.assertEqual(self.j.state['variants'][0]['text'],p['text'])
 def test_artifact_cannot_grant_actions_or_forge_source(self):
  j=self.prepare();value=FixtureRuntime().generate(j['manifest'])
  for changed in [{**value,'publish':True},{'variants':[{**value['variants'][0],'sourceIds':['foreign']},value['variants'][1]]}]:
   with self.assertRaises(AlphaError):c.artifact(changed,j['manifest'])
 def test_parser_ignores_reasoning_and_tools(self):
  for route in ['codex','claude','gemini']:
   adapter=RuntimeAdapter(route);self.assertIsNone(adapter.normalize({'type':'reasoning','text':'hidden'}));self.assertIsNone(adapter.normalize({'type':'tool_call','arguments':'secret'}))
   with self.assertRaises(ValueError):adapter.resume('native')
  self.assertEqual(RuntimeAdapter('codex').normalize({'type':'item.completed','item':{'type':'agent_message','text':'visible'}})['text'],'visible')
 def test_injection_and_file_boundary(self):
  adapter=RuntimeAdapter('claude')
  with self.assertRaises(AlphaError):adapter.argv('/safe/executable','$(touch /tmp/owned)',Path(self.tmp.name))
  root=Path(self.tmp.name);(root/'source').write_text('approved');h=hashlib.sha256(b'approved').hexdigest()
  self.assertEqual(read_approved_file(root,'source',h),b'approved')
  (root/'escape').symlink_to('/etc/passwd')
  for path in ['../passwd','/etc/passwd','escape']:
   with self.assertRaises(AlphaError):read_approved_file(root,path,h)
 def test_managed_adapter_no_implicit_retry_or_unauthorized_request(self):
  j=self.prepare();calls=[]
  model=ManagedWriting(transport=lambda body:calls.append(body))
  with self.assertRaises(AlphaError):model.start(j['manifest'],None,lambda e:None)
  self.assertEqual(calls,[])
 def test_profile_builder_candidate_review(self):
  # Existing onboarding continues through the same profile importer.
  self.j.act('profile_import',content={'schema':'postriff.personal-voice.v1','fields':[{'key':'voiceTraits','value':'Clear','evidence':'agent_proposed_needs_confirmation','privacy':'local_only','sourceIds':[],'confidence':'low'}]})
  self.assertEqual(self.j.state['profileSetup']['stage'],'review')
  self.assertNotEqual(self.j.state['profileSetup']['candidate'][0]['decision'],'approved')

 def managed_job(self):
  self.command('profile_visibility',voiceRevision=self.j.state['speaker']['activeRevision'],allowCloud=True,confirmed=True)
  for s in self.j.state['sources']:self.command('source_visibility',sourceId=s['id'],visibility='provider_allowed',confirmed=True)
  return self.prepare(route='managed')
 def test_durable_managed_start_and_accounting_exactly_once(self):
  from postriff_phase3.worker import AuthorizedWorker
  job=self.managed_job();calls=[]
  class SyntheticTransport:
   def start(inner,m,permit,emit):
    calls.append(1)
    persisted=self.store.get(self.j.id,self.j.token)['state']['phase3']['jobs'][0]
    self.assertEqual(persisted['status'],'running')
    return {'artifact':FixtureRuntime().generate(m),'usage':{'provenance':'provider_reported','values':{'total_tokens':42}}}
  worker=AuthorizedWorker(self.store,SyntheticTransport());permit=ExecutionPermit('managed','synthetic-parser',job['inputHash'],self.now+60,.01,'fixture-only')
  before=self.j.state['phase2']['trial']['writingUsed'];result=worker.execute(self.j.id,self.j.token,job['id'],permit)
  self.assertTrue(result['allowanceCharged']);self.j.refresh();self.assertEqual(self.j.state['phase2']['trial']['writingUsed'],before+1)
  with self.assertRaises(AlphaError):worker.execute(self.j.id,self.j.token,job['id'],permit)
  self.assertEqual(len(calls),1)
 def test_failed_managed_request_no_allowance_no_retry(self):
  from postriff_phase3.worker import AuthorizedWorker
  job=self.managed_job();calls=[]
  class BrokenTransport:
   def start(inner,*_):calls.append(1);raise TimeoutError('ambiguous')
  before=self.j.state['phase2']['trial']['writingUsed']
  worker=AuthorizedWorker(self.store,BrokenTransport());permit=ExecutionPermit('managed','synthetic-parser',job['inputHash'],self.now+60,.01,'fixture-only')
  result=worker.execute(self.j.id,self.j.token,job['id'],permit);self.assertFalse(result['allowanceCharged']);self.assertEqual(result['status'],'interrupted')
  self.j.refresh();self.assertEqual(self.j.state['phase2']['trial']['writingUsed'],before)
  with self.assertRaises(AlphaError):worker.execute(self.j.id,self.j.token,job['id'],permit)
  self.assertEqual(len(calls),1)
 def test_outbound_discovery_scope_and_no_duplicate_start(self):
  from postriff_phase3.transport import OutboundHost
  d,_=self.pair();job=self.prepare(device=d['deviceId']);self.start(job)
  host=OutboundHost(lambda action,p:self.store.device(self.j.id,d['deviceId'],d['deviceCredential'],action,p))
  host.tick();host.tick();self.j.refresh();self.assertEqual(self.j.state['phase3']['jobs'][0]['status'],'completed')
  self.assertEqual(sum(e['type']=='running' for e in self.j.state['phase3']['jobs'][0]['events']),1)
 def test_profile_scope_manifest_to_untrusted_review(self):
  self.j.act('profile_transfer',route='portable')
  self.j.act('profile_scope',scope={'currentConversation':False,'memory':False,'conversations':[],'files':[],'examples':[],'questions':True,'retention':'references_only','confirmed':True})
  self.command('prepare',route='fixture',operation='profile',sourceIds=[self.j.state['sources'][0]['id']],idempotencyKey='profile')
  job=self.j.state['phase3']['jobs'][0];self.assertEqual(job['manifest']['actualAccess']['history'],False)
  self.start(job)
  for _ in range(3):self.store.fixture_step()
  self.j.refresh();job=self.j.state['phase3']['jobs'][0]
  self.command('apply',runId=job['id'],artifactHash=job['artifactHash'])
  self.assertEqual(self.j.state['profileSetup']['stage'],'review')
  self.assertTrue(all(f['decision']!='approved' for f in self.j.state['profileSetup']['candidate']))
 def test_each_structured_parser_excludes_hidden_context(self):
  cases=[('codex',{'type':'item.completed','item':{'type':'agent_message','text':'answer'}}),('claude',{'type':'assistant','message':{'content':[{'type':'thinking','thinking':'secret reasoning'},{'type':'text','text':'answer'}]}}),('gemini',{'type':'message','role':'assistant','content':'answer'})]
  for route,event in cases:self.assertEqual(RuntimeAdapter(route).normalize(event),{'type':'text','text':'answer'})
 def test_bounded_process_fixture_output_and_timeout_cleanup(self):
  import time
  job=self.prepare();value=FixtureRuntime().generate(job['manifest'])
  class FakeProcess(RuntimeAdapter):
   def inspect(inner):return {'versionSupported':True}
   def argv(inner,*_):return [sys.executable,'-c',inner.script,'--max-budget-usd','0.01']
  adapter=FakeProcess('claude');adapter.script='import json,sys;sys.stdin.read();print(json.dumps('+repr({'type':'result','structured_output':value})+'))'
  permit=ExecutionPermit('claude','synthetic-process',job['inputHash'],time.time()+60,.01,'claude-bare-api-reviewed')
  result=adapter.start(job['manifest'],permit,lambda e:None,credential='synthetic-not-a-provider-key');self.assertEqual(result['artifact']['variants'][0]['platform'],'LinkedIn')
  adapter=FakeProcess('claude',timeout_seconds=.05);adapter.script='import sys,time;sys.stdin.read();time.sleep(3)'
  with self.assertRaises(TimeoutError):adapter.start(job['manifest'],permit,lambda e:None,credential='synthetic-not-a-provider-key')
  self.assertFalse(adapter.health()['running'])
 def test_managed_real_http_adapter_with_synthetic_response(self):
  import time
  job=self.managed_job();calls=[];value=FixtureRuntime().generate(job['manifest'])
  def response(body):calls.append(body);return {'choices':[{'message':{'content':json.dumps(value)}}],'usage':{'prompt_tokens':50,'completion_tokens':80,'hidden':'excluded'}}
  adapter=ManagedWriting(transport=response,price_quote={'model':'synthetic-model','expiresAt':time.time()+60,'inputUsdPerMillion':.1,'outputUsdPerMillion':.2})
  permit=ExecutionPermit('managed','synthetic-model',job['inputHash'],time.time()+60,.01,'deepinfra-bounded-preview')
  result=adapter.start(job['manifest'],permit,lambda e:None);self.assertEqual(len(calls),1);self.assertEqual(calls[0]['max_tokens'],2048);self.assertNotIn('tools',calls[0]);self.assertNotIn('hidden',result['usage']['values'])
  adapter.cancel()
  with self.assertRaises(AlphaError):adapter.start(job['manifest'],permit,lambda e:None)
  self.assertEqual(len(calls),1)
 def test_export_does_not_include_device_secret_or_hash(self):
  import io,zipfile
  device,_=self.pair()
  with zipfile.ZipFile(io.BytesIO(self.store.export(self.j.id,self.j.token))) as z:
   runtime=z.read('runtime-review.json').decode();self.assertNotIn(device['deviceCredential'],runtime);self.assertNotIn('credentialHash',runtime)
 def test_skill_personalization_and_plan_mode_continuity(self):
  for mode in ('personal','niche','business','hybrid'):
   self.j.act('mode',mode=mode)
   self.j.act('template_config',templateId='content-craft',overrides={'tone':'direct'})
   job=self.prepare('mode-'+mode);self.assertEqual(job['manifest']['skills'][-1]['overrides'],{'tone':'direct'})
   other=self.store.get(self.other.id,self.other.token)['state'];self.assertEqual(other['skillInstances'][-1]['overrides'],{})

 def test_revocation_during_provider_call_records_usage_without_accepting_output(self):
  from postriff_phase3.worker import AuthorizedWorker
  job=self.managed_job()
  class Response:
   def start(inner,m,permit,emit):
    with self.store.connect() as db:
     db.execute("UPDATE alpha_memberships SET status='revoked' WHERE workspace_id=?",(self.j.id,))
    return {'artifact':FixtureRuntime().generate(m),'usage':{'provenance':'provider_reported','values':{'total_tokens':42}}}
  result=AuthorizedWorker(self.store,Response()).execute(self.j.id,self.j.token,job['id'],ExecutionPermit('managed','fixture',job['inputHash'],self.now+60,.01,'fixture'))
  self.assertEqual(result,{'status':'revoked','allowanceCharged':False})
  with self.store.connect() as db:stored=self.store.load_runtime(db,self.j.id)['jobs'][0]
  self.assertEqual(stored['status'],'revoked');self.assertEqual(stored['usage']['values']['total_tokens'],42);self.assertFalse(stored.get('artifact'))

 def test_expired_session_during_call_finalizes_without_recreating_access(self):
  from postriff_phase3.worker import AuthorizedWorker
  job=self.managed_job()
  class Response:
   def start(inner,m,permit,emit):
    with self.store.connect() as db:db.execute('UPDATE p2_sessions SET expires=0')
    return {'artifact':FixtureRuntime().generate(m)}
  result=AuthorizedWorker(self.store,Response()).execute(self.j.id,self.j.token,job['id'],ExecutionPermit('managed','fixture',job['inputHash'],self.now+60,.01,'fixture'))
  self.assertEqual(result['status'],'revoked')
  with self.store.connect() as db:self.assertEqual(self.store.load_runtime(db,self.j.id)['jobs'][0]['status'],'revoked')

 def test_invalid_artifact_finalizes_with_usage_without_allowance(self):
  from postriff_phase3.worker import AuthorizedWorker
  job=self.managed_job()
  class Response:
   def start(inner,*_):return {'artifact':{'publish':True},'usage':{'provenance':'provider_reported','values':{'total_tokens':42}}}
  worker=AuthorizedWorker(self.store,Response());permit=ExecutionPermit('managed','fixture',job['inputHash'],self.now+60,.01,'fixture')
  result=worker.execute(self.j.id,self.j.token,job['id'],permit)
  self.assertEqual(result['status'],'interrupted');self.assertFalse(result['allowanceCharged']);self.assertEqual(result['usage']['values']['total_tokens'],42)
  with self.assertRaises(AlphaError):worker.execute(self.j.id,self.j.token,job['id'],permit)

 def test_managed_malformed_or_truncated_response_retains_usage(self):
  import time
  job=self.managed_job();permit=ExecutionPermit('managed','fixture',job['inputHash'],time.time()+60,.01,'deepinfra-bounded-preview')
  for content,finish in [('broken','stop'),(json.dumps(FixtureRuntime().generate(job['manifest'])),'length')]:
   adapter=ManagedWriting(transport=lambda body:{'choices':[{'finish_reason':finish,'message':{'content':content}}],'usage':{'total_tokens':99}},price_quote={'model':'fixture','expiresAt':time.time()+60,'inputUsdPerMillion':.1,'outputUsdPerMillion':.2})
   result=adapter.start(job['manifest'],permit,lambda e:None)
   self.assertEqual(result['status'],'interrupted');self.assertEqual(result['usage']['values']['total_tokens'],99);self.assertNotIn('artifact',result)

 def test_expired_prepared_job_never_calls_provider(self):
  from postriff_phase3.worker import AuthorizedWorker
  job=self.managed_job();self.now+=901
  class Never:
   def start(inner,*_):self.fail('Expired run called provider')
  with self.assertRaises(AlphaError):AuthorizedWorker(self.store,Never()).execute(self.j.id,self.j.token,job['id'],ExecutionPermit('managed','fixture',job['inputHash'],self.now+60,.01,'fixture'))

 def test_claude_process_envelope_through_durable_worker(self):
  import time
  from postriff_phase3.worker import AuthorizedWorker
  job=self.prepare(route='claude');value=FixtureRuntime().generate(job['manifest'])
  class FakeProcess(RuntimeAdapter):
   def inspect(inner):return {'versionSupported':True}
   def argv(inner,*_):return [sys.executable,'-c','import json,sys;sys.stdin.read();print(json.dumps('+repr({'type':'result','structured_output':value,'usage':{'input_tokens':20,'output_tokens':30}})+'))','--max-budget-usd','0.01']
  adapter=FakeProcess('claude',credential='synthetic-not-a-key')
  permit=ExecutionPermit('claude','synthetic-process',job['inputHash'],max(time.time(),self.now)+60,.01,'claude-bare-api-reviewed')
  result=AuthorizedWorker(self.store,adapter).execute(self.j.id,self.j.token,job['id'],permit)
  self.assertEqual(result['status'],'completed');self.assertEqual(result['usage']['values']['output_tokens'],30);self.assertFalse(result['allowanceCharged'])
  self.j.refresh();job=self.j.state['phase3']['jobs'][0]
  self.command('apply',runId=job['id'],artifactHash=job['artifactHash'])
  variant=self.j.state['variants'][0]
  self.j.act('variant_edit',variantId=variant['id'],variantRevision=variant['revision'],text='Independently edited after candidate acceptance.')
  restarted=Phase3Store(self.store.path,clock=lambda:self.now)
  self.assertEqual(restarted.get(self.j.id,self.j.token)['state']['variants'][0]['text'],'Independently edited after candidate acceptance.')

 def test_lost_sync_response_receipt_survives_restart_and_remote_conflict(self):
  self.j.act('generate',platform='LinkedIn',language='English');v=self.j.state['variants'][0]
  payload={'idempotencyKey':'lost-response','variantId':v['id'],'variantRevision':v['revision'],'text':'First device edit'}
  self.command('sync_edit',**payload)
  restarted=Phase3Store(self.store.path,clock=lambda:self.now)
  current=restarted.get(self.j.id,self.j.token)
  receipt=current['state']['phase3']['operations'][-1]
  self.assertEqual(receipt['variantRevision'],v['revision']+1);self.assertEqual(receipt['variantId'],v['id'])
  replay=restarted.runtime_action(self.j.id,self.j.token,current['revision'],'sync_edit',payload)
  self.assertEqual(replay['state']['variants'][0]['revision'],v['revision']+1)
  with self.assertRaises(AlphaError):restarted.runtime_action(self.j.id,self.j.token,replay['revision'],'sync_edit',{**payload,'idempotencyKey':'second-device','text':'Conflicting remote edit'})
  self.assertEqual(restarted.get(self.j.id,self.j.token)['state']['variants'][0]['text'],'First device edit')
