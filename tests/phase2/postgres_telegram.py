"""Disposable, socket-only PostgreSQL. Synthetic Telegram transport, never external E2E."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.telegram.service import TelegramService
from postriff_phase2.telegram.updates import ingest, save_message
from postriff_phase2.telegram.publishing import receipt
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.hosted import HostedPhase2Commands
from cryptography.fernet import Fernet
ROOT=Path(__file__).resolve().parents[2]
PG=Path(os.environ['POSTRIFF_PG_BIN'])
TEST_NOW=int(time.time())
W1,W2,A1,A2=[str(uuid.uuid4()) for _ in range(4)]
CHAT={'id':-100123,'type':'channel','username':'rafii_test'}
checks=[]
def passed(name):checks.append({'name':name,'passed':True,'execution':'cloud_postgresql_synthetic_telegram'})
with tempfile.TemporaryDirectory(prefix='rafii-telegram-pg-') as tmp:
 data=Path(tmp)/'data';sock=Path(tmp)/'socket';sock.mkdir()
 subprocess.run([str(PG/'initdb'),'-D',str(data),'-A','trust','--no-locale','-E','UTF8'],check=True,stdout=subprocess.DEVNULL)
 subprocess.run([str(PG/'pg_ctl'),'-D',str(data),'-l',str(Path(tmp)/'log'),'-o',f'-k {sock} -h "" -p 56597','-w','start'],check=True,stdout=subprocess.DEVNULL)
 try:
  def conn():return psycopg.connect(f'host={sock} port=56597 dbname=postgres',client_encoding='utf8')
  with conn() as db:
   db.execute("create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;")
   db.execute("create table public.pr_workspaces(id uuid primary key,revision bigint not null default 0,state jsonb not null);")
   db.execute("create table public.pr_encrypted_credentials(workspace_id uuid references pr_workspaces(id) on delete cascade,connection_id text,access_ciphertext text,key_id text,provider text,revoked_at timestamptz,provider_account_id text,scopes text[],primary key(workspace_id,connection_id));")
   db.execute("create table public.pr_channel_capabilities(workspace_id uuid,connection_id text,capability text,level text,evidence text,updated_at timestamptz);")
   db.execute("create table public.pr_audit_events(id uuid default gen_random_uuid(),workspace_id uuid,actor uuid,kind text,subject text,meta jsonb);")
  with conn() as db:
   oauth_sql=(ROOT/'migrations/postriff/006_consumer_web_channels.sql').read_text()
   db.execute(oauth_sql[oauth_sql.index('create table public.pr_oauth_transactions'):oauth_sql.index('-- Encrypted provider tokens')])
   db.execute('create table public.pr_auth_throttle(bucket text primary key,window_start timestamptz,count integer)')
  with conn() as db:db.execute((ROOT/'migrations/postriff/117_telegram_capabilities.sql').read_text())
  with conn() as db:db.execute((ROOT/'migrations/postriff/116_telegram_identity_controls.sql').read_text())
  passed('Migrations 116 and 117 apply on disposable real PostgreSQL')
  vault=CredentialVault(Fernet.generate_key().decode())
  class Repo:
   connection_factory=staticmethod(conn)
   clock=staticmethod(lambda:TEST_NOW+50)
   @contextmanager
   def transaction(self,token,workspace):
    if (workspace,token) not in ((W1,A1),(W2,A2)):raise AlphaError('Connection unavailable',404)
    with conn() as db:
     with db.cursor() as cur:
      row=cur.execute('select revision,state from pr_workspaces where id=%s for update',(workspace,)).fetchone()
      yield cur,(row[0],row[1],'owner',True,True,True,True),token
   def assert_fresh(self,*a):pass
   def get(self,workspace,token):
    with self.transaction(token,workspace) as (cur,row,_):return {'revision':row[0],'state':row[1]}
   def command(self,workspace,token,revision,fn,requirement=None,after=None):
    with self.transaction(token,workspace) as (cur,row,_):
     assert row[0]==revision
     state=row[1];fn(state,token)
     if after:after(cur,state,token)
     cur.execute('update pr_workspaces set state=%s::jsonb,revision=revision+1 where id=%s',(json.dumps(state),workspace))
     return {'revision':revision+1,'state':state}
  repo=Repo()
  class Bot:
   production_reviewed=True;acceptance={};bot_ref=None
   def me(self):return {'id':999,'username':'Rafii_testbot'}
   def for_session(self,s):return self
   def session(self,s):return json.loads(s)
   def qualified(self,*a):return {'identity','publish','text','reply','edit_own','delete_own','pin','schedule','poll','forward','copy','comments_read','engagement','reactions'}
   def call(self,m,p=None):
    if m=='getChat':return {'id':-100444,'type':'supergroup','is_direct_messages':True,'parent_chat':CHAT,'title':'Synthetic Channel DM'} if p['chat_id']==-100444 else copy.deepcopy(CHAT)
    if m=='getChatMember':return {'status':'administrator','can_post_messages':True,'can_edit_messages':True,'can_manage_direct_messages':True}
    if m=='getBusinessConnection':return {'id':p['business_connection_id'],'user':{'id':5},'is_enabled':False,'rights':{}}
    raise AssertionError(m)
   calls=[]
   def request(self,m,p):
    self.calls.append((m,p))
    return {'status':200,'body':{'ok':True,'result':True if m in ('deleteMessage','pinChatMessage','unpinChatMessage') else {'message_id':p['message_id'],'date':TEST_NOW,'edit_date':TEST_NOW+50,'chat':CHAT,'text':p.get('text','hello')}}}
  bot=Bot()
  oauth=SimpleNamespace(repository=repo,vault=vault,providers={'telegram':bot},_provider=lambda _:bot,public_base_url='https://synthetic.example',commands=HostedPhase2Commands(repo.clock))
  service=TelegramService(oauth,clock=repo.clock)
  for w,a in ((W1,A1),(W2,A2)):
   state={'phase2':{'channels':[{'id':'telegram-connection','platform':'Telegram','capabilityVerified':True}],'jobs':[],'reviews':[]},'workspace':{'id':w}}
   encrypted,key=vault.encrypt(json.dumps({'v':1,'workspace':w,'chat':CHAT['id']}))
   with conn() as db:
    db.execute('insert into pr_workspaces(id,state) values(%s,%s::jsonb)',(w,json.dumps(state)))
    db.execute("insert into pr_encrypted_credentials(workspace_id,connection_id,access_ciphertext,key_id,provider,revoked_at) values(%s,'telegram-connection',%s,%s,'telegram',NULL)",(w,encrypted,key))
    db.execute("insert into pr_telegram_destinations values(%s,'telegram-connection',999,%s,'bot',%s::jsonb,now(),NULL)",(w,CHAT['id'],json.dumps({'connectionType':'bot','chat':CHAT})))
  with conn() as db:
   db.execute('set local role authenticated')
   for table in ('pr_telegram_destinations','pr_telegram_bot_grants','pr_telegram_messages','pr_telegram_business_inbox','pr_telegram_operations','pr_telegram_identities','pr_telegram_automation_controls'):
    try:
     with db.transaction():db.execute('select * from public.'+table).fetchall()
    except psycopg.errors.InsufficientPrivilege:pass
    else:raise AssertionError('Browser role read '+table)
  passed('Browser/database roles cannot read Telegram credentials, sessions, inbox or operations')
  update={'update_id':1,'channel_post':{'message_id':21,'date':TEST_NOW,'chat':CHAT,'text':'hello'}}
  raw=json.dumps(update).encode()
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:ingest(service,bot,update,raw),range(2)))
  assert sum(r.get('duplicate',False) for r in results)==1
  with conn() as db:assert db.execute('select count(*) from pr_telegram_messages').fetchone()[0]==2
  passed('Concurrent webhook duplicate is processed once and independently routes authorized workspaces')
  with conn() as db:
   row=db.execute('select message_ciphertext,key_id from pr_telegram_messages limit 1').fetchone();assert 'hello' not in row[0];assert json.loads(vault.decrypt(*row))['text']=='hello'
  passed('Inbox bodies encrypted at rest')
  try:ingest(service,bot,update,b'{"conflicting":true}')
  except AlphaError as e:assert e.status==409
  else:raise AssertionError('Replay changed payload')
  passed('Conflicting replay rejected')
  try:service.inbox(W2,A1,'telegram-connection')
  except AlphaError:pass
  else:raise AssertionError('Cross-workspace access')
  passed('Cross-workspace API access fails closed')
  # Channel publishing does not silently authorize its customer conversations.
  dm_message={'message_id':80,'date':TEST_NOW,'chat':{'id':-100444,'type':'supergroup','is_direct_messages':True},'direct_messages_topic':{'topic_id':77},'text':'accessible only after consent'}
  early={'update_id':400,'message':dm_message};ingest(service,bot,early,json.dumps(early).encode())
  with conn() as db:assert db.execute('select count(*) from pr_telegram_dm_inbox').fetchone()[0]==0
  preview=service.channel_dms.authorize(W1,A1,'telegram-connection',{})
  assert preview['requiresConfirmation'] is True
  with conn() as db:assert db.execute('select count(*) from pr_telegram_dm_access').fetchone()[0]==0
  service.channel_dms.authorize(W1,A1,'telegram-connection',{'confirmed':True})
  observed={'update_id':401,'message':dm_message};ingest(service,bot,observed,json.dumps(observed).encode())
  assert len(service.channel_dms.list(W1,A1)['conversations'])==1 and not service.channel_dms.list(W2,A2)['conversations']
  selected=service.channel_dms.select(W1,A1,'telegram-connection',{'chatId':-100444,'topicId':77,'confirmed':True});dm_connection=selected['connectionId']
  with conn() as db:assert db.execute('select count(*) from pr_telegram_messages where workspace_id=%s and connection_id=%s',(W1,dm_connection)).fetchone()[0]==1
  outside={'update_id':402,'message':dict(dm_message,message_id=81,direct_messages_topic={'topic_id':78})};ingest(service,bot,outside,json.dumps(outside).encode())
  with conn() as db:assert db.execute('select count(*) from pr_telegram_messages where workspace_id=%s and connection_id=%s',(W1,dm_connection)).fetchone()[0]==1
  passed('Channel DM consent, encrypted discovery, selected-topic routing and workspace isolation use real PostgreSQL')
  # Business edits arrive independently; a delayed original cannot overwrite an edit.
  with conn() as db:db.execute("insert into pr_telegram_business_connections(workspace_id,bot_id,business_connection_id,user_id,identity,enabled,rafii_consented) values(%s,999,'business-test',5,'{}',true,true)",(W1,))
  for uid,edit,text in ((100,TEST_NOW+30,'newest'),(101,None,'original')):
   message={'message_id':50,'date':TEST_NOW,'chat':{'id':5,'type':'private'},'business_connection_id':'business-test','text':text}
   if edit:message['edit_date']=edit
   update={'update_id':uid,'edited_business_message' if edit else 'business_message':message}
   ingest(service,bot,update,json.dumps(update).encode())
  with conn() as db:
   row=db.execute("select message_ciphertext,key_id from pr_telegram_business_inbox where workspace_id=%s and message_id=50",(W1,)).fetchone()
   assert json.loads(vault.decrypt(*row))['text']=='newest'
   db.execute("update pr_workspaces set state=jsonb_set(state,'{accountBlock}','{}') where id=%s",(W1,))
  blocked={'update_id':102,'business_message':dict(message,message_id=51)}
  ingest(service,bot,blocked,json.dumps(blocked).encode())
  with conn() as db:
   assert db.execute('select count(*) from pr_telegram_business_inbox where workspace_id=%s and message_id=51',(W1,)).fetchone()[0]==0
   db.execute("update pr_workspaces set state=state-'accountBlock' where id=%s",(W1,))
  passed('Business edits resist stale delivery and blocked workspaces receive no inbox data')
  # A delayed enable webhook must not restore a currently revoked Business grant.
  with conn() as db:db.execute("update pr_telegram_destinations set snapshot=jsonb_set(snapshot,'{telegramUserId}','\"5\"'::jsonb) where workspace_id=%s and connection_id='telegram-connection'",(W1,))
  for uid,enabled in ((300,False),(299,True)):
   update={'update_id':uid,'business_connection':{'id':'business-test','user':{'id':5},'is_enabled':enabled,'rights':{'can_reply':enabled}}}
   ingest(service,bot,update,json.dumps(update).encode())
  with conn() as db:assert db.execute("select enabled from pr_telegram_business_connections where workspace_id=%s and business_connection_id='business-test'",(W1,)).fetchone()[0] is False
  passed('Delayed Business enable updates re-read current Telegram state and cannot restore revoked permission')
  with conn() as db:save_message(db.cursor(),vault,W1,'telegram-connection',999,{'message_id':30,'date':TEST_NOW,'chat':CHAT,'text':'my post'},job={'id':'job-1'})
  op=service.prepare(W1,A1,'telegram-connection',{'action':'edit_text','messageId':30,'text':'new text'})
  assert not bot.calls
  approved={'operationId':op['operationId'],'digest':op['digest'],'confirmed':True}
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:service.execute(W1,A1,'telegram-connection',approved),range(2)))
  assert len(bot.calls)==1 and any(r['state']=='confirmed' for r in results)
  assert service.execute(W1,A1,'telegram-connection',approved)['state']=='confirmed' and len(bot.calls)==1
  with conn() as db:row=db.execute('select message_ciphertext,key_id from pr_telegram_messages where workspace_id=%s and message_id=30',(W1,)).fetchone();assert json.loads(vault.decrypt(*row))['text']=='new text'
  passed('Lifecycle preview makes no outbound request; concurrent/replayed execution sends once and reconciles edits')
  from postriff_phase2.telegram.login import TelegramLogin,ISSUER
  from test_telegram_login import TelegramLoginSecurity
  from urllib.parse import urlparse,parse_qs
  import base64,hashlib
  TelegramLoginSecurity.setUpClass()
  fixture_login=TelegramLoginSecurity()
  requests=[]
  def oidc_transport(method,url,headers=None,data=None):
   requests.append((method,url))
   if url.endswith('/.well-known/jwks.json'):return {'status':200,'body':fixture_login.jwks}
   assert url==ISSUER+'/token' and method=='POST'
   fields=parse_qs(data.decode());assert len(fields['code_verifier'][0])>=43
   actual=base64.urlsafe_b64encode(hashlib.sha256(fields['code_verifier'][0].encode()).digest()).decode().rstrip('=')
   assert actual==login_challenge
   return {'status':200,'body':{'id_token':fixture_login.token({'iat':TEST_NOW,'exp':TEST_NOW+600})}}
  login=TelegramLogin(service,{'POSTRIFF_TELEGRAM_LOGIN_CLIENT_ID':'123456','POSTRIFF_TELEGRAM_LOGIN_CLIENT_SECRET':'synthetic-secret'},transport=oidc_transport,clock=repo.clock)
  started=login.start(W1,A1);params=parse_qs(urlparse(started['authorizeUrl']).query)
  login_challenge=params['code_challenge'][0];login_state=params['state'][0]
  assert params['scope']==['openid profile'] and params['code_challenge_method']==['S256']
  try:login.complete(W2,A2,{'state':login_state,'code':'synthetic-code'})
  except AlphaError as error:assert error.status==404
  else:raise AssertionError('Cross-tenant OIDC state accepted')
  assert not requests
  linked=login.complete(W1,A1,{'state':login_state,'code':'synthetic-code'})
  assert linked['managementGranted'] is False and len(login.list(W1,A1)['identities'])==1
  try:login.complete(W1,A1,{'state':login_state,'code':'synthetic-code'})
  except AlphaError as error:assert error.status==404
  else:raise AssertionError('Consumed OIDC state replayed')
  assert len(requests)==2
  login.disconnect(W1,A1,linked['identity']['id']);assert not login.list(W1,A1)['identities']
  second=login.start(W1,A1);params=parse_qs(urlparse(second['authorizeUrl']).query);login_challenge=params['code_challenge'][0]
  assert login.complete(W1,A1,{'state':params['state'][0],'code':'synthetic-reconnect'})['status']=='connected'
  third=login.start(W2,A2);params=parse_qs(urlparse(third['authorizeUrl']).query);login_challenge=params['code_challenge'][0]
  try:login.complete(W2,A2,{'state':params['state'][0],'code':'synthetic-other-owner'})
  except AlphaError as error:assert error.status==409
  else:raise AssertionError('Linked identity claimed by another member')
  passed('OIDC PKCE, tenant/member binding, replay rejection, minimal identity, disconnect/reconnect and owner fence on PostgreSQL; synthetic provider')
  from postriff_phase2.telegram.managed import observe
  from unittest.mock import patch
  with patch.object(bot,'me',return_value={'id':123456,'username':'SyntheticManagerBot','can_manage_bots':True}):
   request={'username':'OwnedSyntheticBot','name':'Synthetic owner bot','identityId':linked['identity']['id'],'confirmed':True}
   link=service.managed.start(W1,A1,request)
   assert link['botCreated'] is False and link['creationUrl'].startswith('https://t.me/newbot/SyntheticManagerBot/OwnedSyntheticBot?')
   try:service.managed.start(W2,A2,request)
   except AlphaError as error:assert error.status==403
   else:raise AssertionError('Another tenant requested an owned bot')
   try:service.managed.connect(W1,A1,{'username':request['username'],'confirmed':True})
   except AlphaError as error:assert error.status==409
   else:raise AssertionError('Managed creation accepted before owner update')
   managed={'user':{'id':778899,'is_bot':False},'bot':{'id':222333,'username':request['username'],'is_bot':True}}
   with conn() as db:observe(db.cursor(),123456,700,managed)
   access_state={'is_access_restricted':False,'added_users':[]}
   access_mutations=[]
   def managed_access(method,payload):
    assert_managed_event_waits()
    assert payload['user_id']==222333
    if method=='getManagedBotAccessSettings':return copy.deepcopy(access_state)
    assert method=='setManagedBotAccessSettings'
    access_mutations.append(copy.deepcopy(payload))
    access_state.update(is_access_restricted=payload['is_access_restricted'],added_users=[{'id':i} for i in payload['added_user_ids']])
    return True
   def assert_managed_event_waits():
    with conn() as db:
     assert db.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))',('rafii-managed:123456:222333',)).fetchone()[0] is False
   def managed_token(*args,**kwargs):
    assert_managed_event_waits()
    return '222333:'+('a'*32)
   def managed_connection(*args,**kwargs):
    assert_managed_event_waits()
    return {'botRef':str(uuid.uuid4()),'status':'webhook_confirmed'}
   with patch.object(bot,'call',side_effect=managed_access):
    assert service.managed.access(W1,A1,'222333')['restricted'] is False
    preview=service.managed.prepare_access(W1,A1,'222333',{'restricted':True,'addedUserIds':[501]})
    assert not access_mutations
    confirmation={'proof':preview['proof'],'keyId':preview['keyId'],'confirmed':True}
    for w,a,body in ((W2,A2,confirmation),(W1,A1,dict(confirmation,confirmed=False)),(W1,A1,dict(confirmation,proof='tampered'))):
     try:service.managed.execute_access(w,a,'222333',body)
     except AlphaError:pass
     else:raise AssertionError('Unauthorized managed access mutation')
    with ThreadPoolExecutor(max_workers=2) as pool:
     results=list(pool.map(lambda _:service.managed.execute_access(W1,A1,'222333',confirmation),range(2)))
    assert all(r['state']=='confirmed' for r in results) and len(access_mutations)==1
    next_preview=service.managed.prepare_access(W1,A1,'222333',{'restricted':False,'addedUserIds':[]})
    next_confirmation={'proof':next_preview['proof'],'keyId':next_preview['keyId'],'confirmed':True}
    access_state['added_users']=[{'id':502}]
    try:service.managed.execute_access(W1,A1,'222333',next_confirmation)
    except AlphaError as error:assert error.status==409
    else:raise AssertionError('Overwrote externally changed access settings')
    access_state['added_users']=[{'id':501}]
    with patch.object(service,'clock',return_value=TEST_NOW+500):
     try:service.managed.execute_access(W1,A1,'222333',next_confirmation)
     except AlphaError as error:assert error.status==409
     else:raise AssertionError('Accepted expired managed access preview')
    with conn() as db:observe(db.cursor(),123456,701,managed)
    try:service.managed.execute_access(W1,A1,'222333',next_confirmation)
    except AlphaError as error:assert error.status==409
    else:raise AssertionError('Accepted access preview after owner/token event')
   passed('Managed access preview, verified owner/tenant, proof integrity/expiry, external-change and concurrent idempotency fences; synthetic provider')
   with patch.object(bot,'call',side_effect=managed_token) as token_request, patch.object(service,'connect_bot',side_effect=managed_connection) as connect:
    service.managed.connect(W1,A1,{'username':request['username'],'confirmed':True})
    token_request.assert_called_once_with('getManagedBotToken',{'user_id':222333})
    assert connect.call_args.args[2]['botId']=='222333'
   with conn() as db:
    assert db.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))',('rafii-managed:123456:222333',)).fetchone()[0] is True
    changed=copy.deepcopy(managed);changed['user']['id']=999111
    observe(db.cursor(),123456,702,changed);observe(db.cursor(),123456,701,managed)
    assert db.execute('select owner_user_id from pr_telegram_managed_bots where bot_id=222333').fetchone()[0]==999111
   try:service.managed.connect(W1,A1,{'username':request['username'],'confirmed':True})
   except AlphaError as error:assert error.status==409
   else:raise AssertionError('Earlier owner regained managed bot')
  passed('Official managed creation link, verified owner/tenant binding, authenticated event requirement and stale owner update fence; synthetic provider')
  from postriff_phase2.telegram.controls import TelegramControls
  controls=TelegramControls(service)
  assert controls.get(W1,A1)['paused'] is True
  settings=controls.set(W1,A1,{'paused':False,'confirmed':True,'approvalPolicy':'always','allowedConnections':['telegram-connection'],'allowedActions':['publish'],'retentionDays':7,'revision':0})
  try:
   with controls.dispatch_guard(W1,'telegram-connection','publish'):pass
  except AlphaError as error:assert error.status==403
  else:raise AssertionError('Missing human approval')
  with controls.dispatch_guard(W1,'telegram-connection','publish',human_approved=True):pass
  settings=controls.set(W1,A1,{**settings,'paused':True})
  try:
   with controls.dispatch_guard(W1,'telegram-connection','publish',human_approved=True):pass
  except AlphaError as error:assert error.status==409
  else:raise AssertionError('Pause bypass')
  try:controls.set(W1,A1,{**settings,'revision':0,'paused':True})
  except AlphaError as error:assert error.status==409
  else:raise AssertionError('Stale consent overwrite')
  passed('Automation defaults paused, human approval, pause fence and stale revision checks')
  # 1,000 concurrent simulated user tasks enter a bounded worker lane. No real API requests.
  import asyncio
  import statistics
  users=[str(uuid.uuid4()) for _ in range(1000)]
  with conn() as db:
   with db.cursor() as cur:
    cur.executemany('insert into pr_workspaces(id,state) values(%s,%s::jsonb)',[(w,json.dumps({'workspace':{'id':w},'phase2':{'channels':[],'jobs':[],'reviews':[]}})) for w in users])
    credentials=[]
    for w in users:
     ciphertext,key=vault.encrypt(json.dumps({'v':1,'workspace':w}))
     credentials.append((w,ciphertext,key))
    cur.executemany("insert into pr_encrypted_credentials(workspace_id,connection_id,access_ciphertext,key_id,provider) values(%s,'load-connection',%s,%s,'telegram')",credentials)
    cur.executemany("insert into pr_telegram_destinations(workspace_id,connection_id,bot_id,chat_id,mode,snapshot,verified_at) values(%s,'load-connection',999,%s,'bot','{}',now())",[(w,-1000000-i) for i,w in enumerate(users)])
  latencies=[]
  def load_user(pair):
   i,w=pair
   started=time.monotonic()
   u={'update_id':10000+i,'message':{'message_id':1,'date':TEST_NOW,'chat':{'id':-1000000-i,'type':'supergroup'},'text':'synthetic tenant '+str(i)}}
   assert not ingest(service,bot,u,json.dumps(u).encode()).get('duplicate',False)
   with conn() as db:
    rows=db.execute('select workspace_id::text from pr_telegram_messages where chat_id=%s',(-1000000-i,)).fetchall()
    assert rows==[(w,)]
   latencies.append(time.monotonic()-started)
  async def concurrent_load():
   loop=asyncio.get_running_loop()
   with ThreadPoolExecutor(max_workers=32) as executor:
    await asyncio.gather(*(loop.run_in_executor(executor,load_user,pair) for pair in enumerate(users)))
  started=time.monotonic();asyncio.run(concurrent_load());elapsed=time.monotonic()-started
  load={'execution':'cloud_postgresql_synthetic_telegram','realTelegramE2E':False,'simulatedConnectedUsers':1000,'concurrentSubmittedTasks':1000,'maxActiveWorkers':32,'successfulUsers':len(latencies),'durationSeconds':round(elapsed,3),'usersPerSecond':round(1000/elapsed,2),'p95WorkerSeconds':round(sorted(latencies)[949],3),'scope':'tenant routing, encrypted webhook processing and isolation; provider throughput is not measured'}
  evidence_dir = ROOT/'.jcb-artifacts/telegram'
  evidence_dir.mkdir(parents=True, exist_ok=True)
  (evidence_dir/'load-tests.json').write_text(json.dumps(load,indent=2)+'\n')
  passed('1,000 simulated connected users and concurrent tasks route only to their tenants with bounded 32 workers')
  event={'update_id':2,'my_chat_member':{'chat':CHAT,'date':TEST_NOW+1,'new_chat_member':{'status':'left'}}}
  ingest(service,bot,event,json.dumps(event).encode())
  with conn() as db:state=db.execute('select state from pr_workspaces where id=%s',(W1,)).fetchone()[0];assert state['phase2']['channels'][0]['capabilityVerified'] is False
  passed('Membership revocation immediately downgrades shared connection state')
  # Worker completion uses real row locks/lease fences. No bypass of live dispatch authorization is claimed.
  manifest={'platform':'Telegram','channelId':'telegram-connection','variantId':'draft-1','workspaceId':W1,'payload':{'text':'hello'},'idempotencyKey':'a'*64}
  job={'id':'job-2','manifest':manifest,'state':'sending','leaseOwner':'worker-a','leaseId':'lease-1','leaseUntil':TEST_NOW+200,'attempts':[{'number':1}],'events':[]}
  with conn() as db:db.execute("update pr_workspaces set state=jsonb_set(state,'{phase2,jobs}',%s::jsonb) where id=%s",(json.dumps([job]),W1))
  worker=PostgresWorker(conn,social=SimpleNamespace(oauth=oauth),clock=repo.clock,worker_id='worker-a')
  claimed={'workspaceId':W1,'job':copy.deepcopy(job),'reconciliation':False}
  outcome=receipt({'status':200,'body':{'ok':True,'result':{'message_id':40,'date':TEST_NOW,'chat':CHAT,'text':'hello'}}},CHAT['id'],'sendMessage',{'text':'hello'},{'chat_id':CHAT['id'],'text':'hello'})
  outcome['_telegramBotId']=999
  from unittest.mock import patch
  with patch('postriff_phase2.hosted_worker.record_published',lambda *a:None):
   assert worker.complete(claimed,outcome) is True
   assert worker.complete(claimed,outcome) is False
  with conn() as db:
   j=db.execute('select state from pr_workspaces where id=%s',(W1,)).fetchone()[0]['phase2']['jobs'][0]
   assert j['state']=='verified' and j['telegramReceipt']['messages'][0]['messageId']==40
   assert db.execute('select count(*) from pr_telegram_messages where workspace_id=%s and message_id=40',(W1,)).fetchone()[0]==1
  passed('Worker atomically persists publishing receipt/inbox; repeated completion fails lease fence')
  from postriff_phase2.telegram.privacy import erase_identity
  with conn() as db:
   db.execute("INSERT INTO pr_telegram_identities(workspace_id,member_id,bot_id,subject,telegram_user_id,identity) VALUES(%s,%s,'123456','other-member',999111,'{}')",(W2,A2))
   db.execute("INSERT INTO pr_telegram_identity_owners(bot_id,subject,member_id) VALUES('123456','other-member',%s)",(A2,))
   db.execute("INSERT INTO pr_telegram_managed_bots VALUES(123456,222444,778899,'deleting_owner_bot',800)")
   erase_identity(db.cursor(),A1)
   assert db.execute('SELECT count(*) FROM pr_telegram_identities WHERE member_id=%s',(A1,)).fetchone()[0]==0
   assert db.execute('SELECT count(*) FROM pr_telegram_identity_owners WHERE member_id=%s',(A1,)).fetchone()[0]==0
   assert db.execute('SELECT count(*) FROM pr_telegram_managed_requests WHERE member_id=%s',(A1,)).fetchone()[0]==0
   assert db.execute('SELECT count(*) FROM pr_telegram_managed_bots WHERE bot_id=222444').fetchone()[0]==0
   assert db.execute('SELECT count(*) FROM pr_telegram_managed_bots WHERE bot_id=222333').fetchone()[0]==1
   assert db.execute('SELECT count(*) FROM pr_telegram_identities WHERE member_id=%s',(A2,)).fetchone()[0]==1
   assert db.execute('SELECT count(*) FROM pr_telegram_identity_owners WHERE member_id=%s',(A2,)).fetchone()[0]==1
  passed('Account erasure removes person-keyed Telegram identity and managed requests without erasing another tenant owner')
 finally:subprocess.run([str(PG/'pg_ctl'),'-D',str(data),'-m','fast','-w','stop'],check=True,stdout=subprocess.DEVNULL)
evidence_dir = Path(os.environ.get('TELEGRAM_EVIDENCE_DIR', str(ROOT/'.jcb-artifacts/telegram')))
evidence_dir.mkdir(parents=True, exist_ok=True)
(evidence_dir/'postgres-tests.json').write_text(json.dumps({'execution':'cloud_postgresql_synthetic_telegram','realTelegramE2E':False,'checks':checks},indent=2)+'\n')
print(json.dumps({'passed':len(checks),'realTelegramE2E':False}))
