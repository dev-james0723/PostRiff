"""Real local PostgreSQL token lifecycle and HTTP permission boundaries; no external calls."""
import io
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_app import HostedApplication
ONE='00000000-0000-0000-0000-000000000001'
clock=[time.time()]
fresh=[clock[0]]
def connection():return psycopg.connect('host=127.0.0.1 port=55438 dbname=postgres',client_encoding='utf8')
def verify(raw):
    if raw != 'fixture-one':raise AlphaError('Verified session required',401)
    return ONE
verify.auth_time=lambda token,principal:fresh[0]

def denied(call,status):
    try:call()
    except AlphaError as error:assert error.status==status,(error.status,str(error))
    else:raise AssertionError('Expected refusal')

with connection() as db:
    db.execute(Path('migrations/postriff/016_api_tokens.sql').read_text())
    wid=str(db.execute('select workspace_id from public.pr_memberships where user_id=%s',(ONE,)).fetchone()[0])
    foreign=str(db.execute('select id from public.pr_workspaces where id<>%s limit 1',(wid,)).fetchone()[0])
    db.execute("update public.pr_memberships set role='owner',status='active' where user_id=%s",(ONE,))
    db.execute("update public.pr_workspaces set state='{}'::jsonb where id=%s",(wid,))
service=HostedWorkspaceService(connection,verify,clock=lambda:clock[0])
service.bootstrap('fixture-one','studio')
tokens=service.repository.api_tokens
payload={'name':'Local security test','scopes':['read','draft'],'expiresDays':30}
fresh[0]=clock[0]-10000
denied(lambda:tokens.create(wid,'fixture-one',payload),403)
fresh[0]=clock[0]
for bad in [{'scopes':['read','publish']},{'expiresDays':0},{'expiresDays':True}]:denied(lambda:tokens.create(wid,'fixture-one',{**payload,**bad}),400)
created=tokens.create(wid,'fixture-one',payload);raw=created['secret'];item=created['item']
read=tokens.create(wid,'fixture-one',{**payload,'name':'Read only','scopes':['read']})
listed=tokens.list(wid,'fixture-one');assert len(listed['tokens'])==2
assert raw not in json.dumps(listed) and 'token_hash' not in json.dumps(listed)
assert tokens.resolve(raw)['createdBy']==ONE
assert service.repository.get(wid,raw)['membership']['role']=='owner'
denied(lambda:service.repository.get(foreign,raw),403)
denied(lambda:tokens.list(wid,raw),403)
denied(lambda:service.repository.assert_fresh(raw,ONE),403)
app=HostedApplication(service=service,public_auth={'provider':'dev'})
def http(method,tail,token=raw,body=None):
    data=json.dumps(body or {}).encode();status=[]
    result=app({'REQUEST_METHOD':method,'PATH_INFO':tail,'HTTP_AUTHORIZATION':'Bearer '+token,'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(data)),'wsgi.input':io.BytesIO(data)},lambda s,h:status.append(s))
    return int(status[0].split()[0]),json.loads(b''.join(result))
assert http('GET',f'/api/workspaces/{wid}')[0]==200
assert http('POST',f'/api/workspaces/{wid}/ideas/conversations',body={'title':'Synthetic token draft'})[0]==201
assert http('POST',f'/api/workspaces/{wid}/ideas/conversations',token=read['secret'])[0]==403
revision=service.repository.get(wid,raw)['revision']
status,quick=http('POST',f'/api/workspaces/{wid}/ideas/quick-start',body={'expectedRevision':revision,'text':'A synthetic community workshop opens on Saturday.','ownContent':True,'confirmUse':True,'destinations':[{'platform':'LinkedIn','language':'English'}]})
assert status==201,(status,quick)
assert quick['status']=='completed',quick
assert quick['usage']['modelRequests']==0,quick
assert service.repository.get(wid,raw)['state']['phase2']['jobs']==[]

for path in [f'/api/workspaces/{wid}/actions',f'/api/workspaces/{wid}/tokens',f'/api/workspaces/{wid}/billing/checkout','/api/billing/webhook','/api/auth/verify']:
    assert http('POST',path)[0]==403,path
with connection() as db:
    assert db.execute('select last_used_at is not null from public.pr_api_tokens where id=%s',(item['tokenId'],)).fetchone()[0]
    db.execute("update public.pr_memberships set role='viewer' where user_id=%s",(ONE,))
assert http('GET',f'/api/workspaces/{wid}')[0]==200
assert http('POST',f'/api/workspaces/{wid}/ideas/conversations')[0]==403
with connection() as db:db.execute("update public.pr_memberships set status='revoked' where user_id=%s",(ONE,))
assert http('GET',f'/api/workspaces/{wid}')[0]==401
with connection() as db:db.execute("update public.pr_memberships set role='owner',status='active' where user_id=%s",(ONE,))
clock[0]+=31*86400
assert http('GET',f'/api/workspaces/{wid}')[0]==401
clock[0]-=31*86400
tokens.revoke(wid,'fixture-one',item['tokenId'])
assert http('GET',f'/api/workspaces/{wid}')[0]==401
with connection() as db:
    db.execute('begin');db.execute('set local role authenticated')
    try:db.execute('select * from public.pr_api_tokens')
    except psycopg.errors.InsufficientPrivilege:db.rollback()
    else:raise AssertionError('Authenticated role read token custody')
print(json.dumps({'status':'pass','execution':'disposable local PostgreSQL','checks':['fresh session creation','trial creation allowed','invalid scopes and expiry denied','secret only in creation','read and draft routes work without browser guard','sensitive routes denied','cross workspace denied','live downgrade and removal enforced','expiry and revocation enforced','RLS denies authenticated reads']}))
