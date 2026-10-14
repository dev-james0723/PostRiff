"""Actual disposable PostgreSQL, synthetic Pinterest transport, no live credentials."""
import concurrent.futures
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.pinterest_quota import PinterestQuota
from postriff_phase2.wave3_connectors import PinterestProvider

DSN = os.environ['POSTRIFF_TEST_DSN']
assert '127.0.0.1' in DSN and '55438' in DSN
USERS = {'p1':'00000000-0000-0000-0000-000000000501','p2':'00000000-0000-0000-0000-000000000502'}
clock = [time.time()]
def connection(): return psycopg.connect(DSN)
def verify(token): return USERS[token]
verify.session_id = lambda token, principal:'synthetic-pinterest-'+token
verify.auth_time = lambda token, principal:clock[0]
with connection() as db:
    for uid in USERS.values(): db.execute('INSERT INTO auth.users VALUES(%s)',(uid,))
    db.execute(Path('migrations/postriff/20261014_pinterest_rate_budgets.sql').read_text())
refreshes, lock = 0, threading.Lock()
def transport(method,url,**kw):
    global refreshes
    if url.endswith('/oauth/token'):
        if kw['form']['grant_type']=='refresh_token':
            with lock: refreshes+=1
            time.sleep(.05)
        return {'status':200,'body':{'access_token':'MOCK-AT','refresh_token':'MOCK-RT','expires_in':3600,
            'scope':'user_accounts:read boards:read pins:read pins:write'}}
    if url.endswith('/user_account'):
        return {'status':200,'body':{'id':'1234567','username':'synthetic','account_type':'BUSINESS'}}
    if '/boards?' in url: return {'status':200,'body':{'items':[]}}
    raise AssertionError('Unexpected synthetic provider request')
provider = PinterestProvider('1615884','MOCK-SECRET',sandbox=True,transport=transport)
service = HostedWorkspaceService(connection,verify,clock=lambda:clock[0],vault=CredentialVault(CredentialVault.generate_key()),
    providers={'pinterest':provider},public_base_url='https://synthetic.invalid')
workspaces = {token:service.bootstrap(token,'studio')['workspaceId'] for token in USERS}
from consumer_fixtures import approve_budgets
for workspace in workspaces.values(): approve_budgets(connection,workspace)
connections={}
for token,wid in workspaces.items():
    start=service.oauth.start(wid,token,'pinterest','publish')
    state=parse_qs(urlparse(start['authorizeUrl']).query)['state'][0]
    done=service.oauth.complete(wid,token,'pinterest',state,'MOCK-CODE')
    assert done['connected']
    connections[token]=done['connectionId']
    try: service.oauth.complete(wid,token,'pinterest',state,'MOCK-CODE')
    except AlphaError as error: assert error.status==404
    else: raise AssertionError('Replay accepted')
    with connection() as db:
        row=db.execute('SELECT access_ciphertext,refresh_ciphertext FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',(wid,done['connectionId'])).fetchone()
        assert 'MOCK-AT' not in row[0] and 'MOCK-RT' not in row[1]
    assert 'MOCK-AT' not in json.dumps(service.get(wid,token))
wid,cid=workspaces['p1'],connections['p1']
try: service.oauth.destinations(wid,'p2',cid)
except AlphaError as error: assert error.status in (403,404)
else: raise AssertionError('Cross-tenant destination read accepted')
with connection() as db:
    db.execute('UPDATE public.pr_encrypted_credentials SET access_expires_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s',(clock[0]-1,wid,cid))
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
    grants=list(pool.map(lambda _:service.oauth.token_for_worker(wid,cid),range(12)))
assert refreshes==1,refreshes
assert len({g['accessToken'] for g in grants})==1
assert json.loads(grants[0]['accessToken'])['accountId']=='1234567'
result=service.oauth.disconnect(wid,'p1',cid)
assert result['disconnected'] and not result['remoteRevoked']
with connection() as db:
    row=db.execute('SELECT access_ciphertext,refresh_ciphertext,revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',(wid,cid)).fetchone()
    assert row==('',None,True),row
try: service.oauth.token_for_worker(wid,cid)
except AlphaError: pass
else: raise AssertionError('Disconnected token returned')
assert service.oauth.token_for_worker(workspaces['p2'],connections['p2'])['accessToken']
quota= PinterestQuota(connection,'1615884','synthetic',clock=lambda:clock[0])
def reserve(_):
    try: quota('POST','/v5/pins','1234567'); return True
    except AlphaError as error:
        assert error.status==429,error
        return False
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
    outcomes=list(pool.map(reserve,range(120)))
assert sum(outcomes)==100,sum(outcomes)
clock[0]+=60
quota('POST','/v5/pins','1234567')
with connection() as db:
    db.execute('SET ROLE authenticated')
    try: db.execute('SELECT * FROM public.pr_pinterest_rate_budgets')
    except psycopg.errors.InsufficientPrivilege: pass
    else: raise AssertionError('Client can read server rate budgets')
print('PINTEREST_POSTGRES_PASS '+json.dumps({'execution':'disposable_postgres_synthetic_provider','oauthReplayDenied':True,
    'encryptedCustody':True,'tenantNegativeRead':True,'refreshConcurrentCallers':12,'providerRefreshes':refreshes,
    'disconnectStopsTokenAccess':True,'otherTenantUnaffected':True,'quotaConcurrentReservations':120,
    'quotaAccepted':100,'quotaDenied':20,'quotaNextWindowRecovered':True,'clientBudgetAccessDenied':True}))
