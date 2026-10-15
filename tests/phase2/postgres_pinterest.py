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
from postriff_phase2.pinterest_pilot import PinterestTrialPolicy
from postriff_phase2.pinterest_trial_evidence import SandboxReadOnlyEvidenceTransport
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
provider_calls, grant_scopes = [], ['user_accounts:read boards:read pins:read pins:write']
def transport(method,url,**kw):
    global refreshes
    provider_calls.append((method,url))
    if url.endswith('/oauth/token'):
        if kw['form'].get('code')=='MOCK-FAIL': return {'status':503,'body':{}}
        if kw['form']['grant_type']=='refresh_token':
            with lock: refreshes+=1
            time.sleep(.05)
        return {'status':200,'body':{'access_token':'MOCK-AT','refresh_token':'MOCK-RT','expires_in':3600,
            'scope':grant_scopes[0]}}
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
# Switch only this disposable service to the bounded pilot. Old broader custody cannot be reused.
pilot_wid, pilot_cid = workspaces['p2'], connections['p2']
provider.trial_readonly = True
provider.trial_policy = PinterestTrialPolicy(pilot_wid, USERS['p2'], 'synthetic', int(clock[0])+600)
provider.transport = SandboxReadOnlyEvidenceTransport(lambda _:None, mock_transport=transport)
provider.quota_required = True
provider.rate_gate = PinterestQuota(connection,'1615884','sandbox',clock=lambda:clock[0],trial=True)
before = len(provider_calls)
try: service.oauth.token_for_worker(pilot_wid,pilot_cid)
except AlphaError as error: assert error.code=='pinterest_trial_readonly'
else: raise AssertionError('Broader old grant reused in read-only pilot')
try: service.oauth.start(workspaces['p1'],'p1','pinterest','boards_read')
except AlphaError as error: assert error.code=='pinterest_trial_denied'
else: raise AssertionError('Wrong pilot workspace admitted')
# Even another valid owner of the same tenant is outside the exact operator authority.
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_publish) VALUES(%s,%s,'owner','active',true)",(pilot_wid,USERS['p1']))
for action in [lambda:service.oauth.start(pilot_wid,'p1','pinterest','boards_read'),
               lambda:service.oauth.destinations(pilot_wid,'p1',pilot_cid),
               lambda:service.oauth.verify(pilot_wid,'p1',pilot_cid)]:
    try: action()
    except AlphaError as error: assert error.code=='pinterest_trial_denied',error
    else: raise AssertionError('Other same-tenant owner admitted to pilot')
assert len(provider_calls)==before
# The intended actor can complete exactly the two read scopes; no broad token is persisted.
grant_scopes[0] = 'user_accounts:read boards:read'
started = service.oauth.start(pilot_wid,'p2','pinterest','boards_read')
assert set(started['scopes'])=={'user_accounts:read','boards:read'}
pilot_state=parse_qs(urlparse(started['authorizeUrl']).query)['state'][0]
provider.trial_policy = PinterestTrialPolicy(pilot_wid, USERS['p1'], 'synthetic', int(clock[0])+600)
try: service.oauth.complete(pilot_wid,'p2','pinterest',pilot_state,'MOCK-CODE')
except AlphaError as error: assert error.code=='pinterest_trial_denied'
else: raise AssertionError('Callback ignored changed operator authority')
assert len(provider_calls)==before
provider.trial_policy = PinterestTrialPolicy(pilot_wid, USERS['p2'], 'synthetic', int(clock[0])+600)
connected = service.oauth.complete(pilot_wid,'p2','pinterest',pilot_state,'MOCK-CODE')
assert connected['connected'] and connected['connectionId']==pilot_cid
assert service.oauth.destinations(pilot_wid,'p2',pilot_cid)['destinations']==[]
failed_start=service.oauth.start(pilot_wid,'p2','pinterest','boards_read')
failed_state=parse_qs(urlparse(failed_start['authorizeUrl']).query)['state'][0]
try: service.oauth.complete(pilot_wid,'p2','pinterest',failed_state,'MOCK-FAIL')
except AlphaError: pass
else: raise AssertionError('Failed exchange accepted')
with connection() as db:
    consumed=db.execute('SELECT consumed_at IS NOT NULL FROM public.pr_oauth_transactions WHERE id=%s',(failed_start['transactionId'],)).fetchone()[0]
    assert consumed, 'Failed exchange rolled back one-time state consumption'
before_failed_replay=len(provider_calls)
try: service.oauth.complete(pilot_wid,'p2','pinterest',failed_state,'MOCK-CODE')
except AlphaError as error: assert error.status==404
else: raise AssertionError('Failed exchange callback replayed')
assert len(provider_calls)==before_failed_replay
# Force disconnect into the exact committed-claim → exchange gap, using the real DB.
cancel_start=service.oauth.start(pilot_wid,'p2','pinterest','boards_read')
cancel_state=parse_qs(urlparse(cancel_start['authorizeUrl']).query)['state'][0]
original_complete=service.oauth._complete
before_canceled_callback=len(provider_calls)
def disconnect_before_exchange(*args,**kwargs):
    assert service.oauth.disconnect(pilot_wid,'p2',pilot_cid)['disconnected']
    return original_complete(*args,**kwargs)
service.oauth._complete=disconnect_before_exchange
try:
    try: service.oauth.complete(pilot_wid,'p2','pinterest',cancel_state,'MOCK-CODE')
    except AlphaError as error: assert error.status==409
    else: raise AssertionError('Claimed callback restored a disconnected account')
finally: service.oauth._complete=original_complete
assert len(provider_calls)==before_canceled_callback
# Reconnection needs a fresh explicit intent and succeeds after the old callback was canceled.
again=service.oauth.start(pilot_wid,'p2','pinterest','boards_read')
again_state=parse_qs(urlparse(again['authorizeUrl']).query)['state'][0]
assert service.oauth.complete(pilot_wid,'p2','pinterest',again_state,'MOCK-CODE')['connected']

with connection() as db:
    scopes=db.execute('SELECT scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',(pilot_wid,pilot_cid)).fetchone()[0]
    assert set(scopes)=={'user_accounts:read','boards:read'}
# Expiry blocks token custody/refresh, but never blocks the member's disconnect cleanup.
provider.trial_policy = PinterestTrialPolicy(pilot_wid, USERS['p2'], 'synthetic', int(clock[0])-1)
before = len(provider_calls)
try: service.oauth.token_for_worker(pilot_wid,pilot_cid)
except AlphaError as error: assert error.code=='pinterest_trial_denied'
else: raise AssertionError('Expired pilot token returned')
assert service.oauth.disconnect(pilot_wid,'p2',pilot_cid)['disconnected']
assert len(provider_calls)==before
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
trial_quota= PinterestQuota(connection,'1615884','synthetic-trial-cap',clock=lambda:clock[0],trial=True)
def trial_reserve(index):
    try:
        trial_quota('POST' if index%2 else 'GET','/v5/oauth/token' if index%2 else '/v5/boards')
        return True
    except AlphaError as error:
        assert error.status==429,error
        return False
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
    trial_outcomes=list(pool.map(trial_reserve,range(120)))
assert sum(trial_outcomes)==100,sum(trial_outcomes)
clock[0]+=60
assert not trial_reserve(0), 'Minute change reset daily pilot budget'
clock[0]+=86400
assert trial_reserve(1), 'Daily pilot budget did not recover'
print('PINTEREST_POSTGRES_PASS '+json.dumps({'execution':'disposable_postgres_synthetic_provider','oauthReplayDenied':True,
    'encryptedCustody':True,'tenantNegativeRead':True,'refreshConcurrentCallers':12,'providerRefreshes':refreshes,
    'disconnectCancelsClaimedCallback':True,'canceledCallbackNoNetwork':True,'freshExplicitReconnectPassed':True,
    'failedExchangeStateConsumed':True,'failedExchangeReplayNoNetwork':True,'pilotTenantAndActorFences':True,'pilotBroadGrantDenied':True,'pilotCallbackAuthorityRechecked':True,
    'pilotTwoReadScopesConnected':True,'pilotExpiryStopsCustody':True,'pilotDisconnectAfterExpiry':True,
    'trialDailyConcurrentReservations':120,'trialDailyAccepted':100,'trialDailyDenied':20,
    'trialMinuteCannotResetDaily':True,'trialDailyRecovery':True,'disconnectStopsTokenAccess':True,'otherTenantUnaffected':True,'quotaConcurrentReservations':120,
    'quotaAccepted':100,'quotaDenied':20,'quotaNextWindowRecovered':True,'clientBudgetAccessDenied':True}))
