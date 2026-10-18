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
from postriff_phase2.pinterest_trial_evidence import SandboxReadOnlyEvidenceTransport, PinterestReadOnlyEvidenceTransport
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
    # Reproduce Supabase's observed broad defaults so CREATE TABLE cannot silently inherit extra authority.
    db.execute('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO service_role')
    migration = Path('migrations/postriff/20261014_pinterest_rate_budgets.sql').read_text()
    db.execute(migration)
    journal_migration = Path('migrations/postriff/20261017_pinterest_trial_journal.sql').read_text()
    journal_rollback = Path('migrations/postriff/20261017_pinterest_trial_journal.rollback.sql').read_text()
    db.execute(journal_migration)
    db.execute('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM service_role')
    # Re-applying this additive candidate must preserve the same bounded access.
    db.execute(migration)
    db.execute(journal_migration)
    assert db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.pr_pinterest_trial_intents'::regclass").fetchone()==(True,True)
    assert db.execute("SELECT count(*) FROM pg_constraint WHERE conrelid='public.pr_pinterest_trial_intents'::regclass AND contype='f'").fetchone()[0]==0
    journal_privileges = {row[0] for row in db.execute("SELECT privilege_type FROM information_schema.table_privileges WHERE table_schema='public' AND table_name='pr_pinterest_trial_intents' AND grantee='service_role'")}
    assert journal_privileges=={'SELECT','INSERT'},journal_privileges
    assert db.execute("SELECT has_column_privilege('service_role','public.pr_pinterest_trial_intents','pin_id','UPDATE'),has_column_privilege('service_role','public.pr_pinterest_trial_intents','expires_at','UPDATE')").fetchone()==(True,False)
    assert db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.pr_pinterest_rate_budgets'::regclass").fetchone()==(True,True)
    privileges = {row[0] for row in db.execute("SELECT privilege_type FROM information_schema.table_privileges WHERE table_schema='public' AND table_name='pr_pinterest_rate_budgets' AND grantee='service_role'")}
    assert privileges=={'SELECT','INSERT','UPDATE','DELETE'}, privileges
with connection() as db:
    db.execute('SET ROLE service_role')
    db.execute("INSERT INTO public.pr_pinterest_rate_budgets VALUES('permission-probe',0,1)")
    db.execute("UPDATE public.pr_pinterest_rate_budgets SET used=2 WHERE budget_key='permission-probe'")
    assert db.execute("SELECT used FROM public.pr_pinterest_rate_budgets WHERE budget_key='permission-probe'").fetchone()==(2,)
    db.execute("DELETE FROM public.pr_pinterest_rate_budgets WHERE budget_key='permission-probe'")
with connection() as db:
    db.execute('SET ROLE service_role')
    try: db.execute('TRUNCATE public.pr_pinterest_rate_budgets')
    except psycopg.errors.InsufficientPrivilege: pass
    else: raise AssertionError('Service role can erase all rate reservations')
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
# Pending callbacks cannot cross App IDs or API hosts; rejection is durably one-time.
for setting, changed in [('sandbox',False),('client_id','different-synthetic-app')]:
    start=service.oauth.start(workspaces['p2'],'p2','pinterest','publish')
    state=parse_qs(urlparse(start['authorizeUrl']).query)['state'][0]
    prior=getattr(provider,setting); setattr(provider,setting,changed)
    before=len(provider_calls)
    try:
        try: service.oauth.complete(workspaces['p2'],'p2','pinterest',state,'MOCK-CODE')
        except AlphaError as error: assert error.code=='pinterest_oauth_binding_changed',error
        else: raise AssertionError('Changed OAuth host/app accepted')
    finally: setattr(provider,setting,prior)
    with connection() as db:
        assert db.execute('SELECT consumed_at IS NOT NULL,outcome FROM public.pr_oauth_transactions WHERE id=%s',(start['transactionId'],)).fetchone()==(True,'mismatch')
    try: service.oauth.complete(workspaces['p2'],'p2','pinterest',state,'MOCK-CODE')
    except AlphaError as error: assert error.status==404,error
    else: raise AssertionError('Configuration-mismatched callback replayed')
    assert len(provider_calls)==before
wid,cid=workspaces['p1'],connections['p1']
try: service.oauth.destinations(wid,'p2',cid)
except AlphaError as error: assert error.status in (403,404)
else: raise AssertionError('Cross-tenant destination read accepted')
with connection() as db:
    db.execute('UPDATE public.pr_encrypted_credentials SET access_expires_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s',(clock[0]-1,wid,cid))
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
    grants=list(pool.map(lambda _:service.oauth.token_for_worker(wid,cid),range(12)))
assert refreshes==1,refreshes
concurrent_refreshes=refreshes
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

# Changing the selected account or expiry also invalidates a pending callback before exchange.
for policy_change in ['username','expiry']:
    start=service.oauth.start(pilot_wid,'p2','pinterest','boards_read')
    state=parse_qs(urlparse(start['authorizeUrl']).query)['state'][0]
    prior=provider.trial_policy
    provider.trial_policy= PinterestTrialPolicy(pilot_wid,USERS['p2'],
        'different-synthetic' if policy_change=='username' else prior.username,
        prior.expires_at+1 if policy_change=='expiry' else prior.expires_at)
    before=len(provider_calls)
    try:
        try: service.oauth.complete(pilot_wid,'p2','pinterest',state,'MOCK-CODE')
        except AlphaError as error: assert error.code=='pinterest_oauth_binding_changed',error
        else: raise AssertionError('Changed pilot selection accepted pending callback')
    finally: provider.trial_policy=prior
    with connection() as db:
        assert db.execute('SELECT consumed_at IS NOT NULL,outcome FROM public.pr_oauth_transactions WHERE id=%s',(start['transactionId'],)).fetchone()==(True,'mismatch')
    assert len(provider_calls)==before
# Explicit official-API Trial lane: synthetic network only, same real DB and two read scopes.
provider.sandbox=False
provider.trial_api_environment='production'
provider.transport= PinterestReadOnlyEvidenceTransport(lambda _:None,environment='production',mock_transport=transport)
provider.rate_gate= PinterestQuota(connection,'1615884','production',clock=lambda:clock[0],trial=True)
before=len(provider_calls)
try: service.oauth.token_for_worker(pilot_wid,pilot_cid)
except AlphaError as error: assert error.status==409,error
else: raise AssertionError('Sandbox custody accepted by official-API Trial lane')
assert len(provider_calls)==before
production_start=service.oauth.start(pilot_wid,'p2','pinterest','boards_read')
production_state=parse_qs(urlparse(production_start['authorizeUrl']).query)['state'][0]
assert set(production_start['scopes'])=={'user_accounts:read','boards:read'}
production_connected=service.oauth.complete(pilot_wid,'p2','pinterest',production_state,'MOCK-CODE')
assert production_connected['connected'] and production_connected['connectionId']==pilot_cid
assert service.oauth.destinations(pilot_wid,'p2',pilot_cid)['destinations']==[]
assert provider_calls[before:] and all(url.startswith('https://api.pinterest.com/v5/') for _,url in provider_calls[before:])
assert all(urlparse(url).path in ('/v5/oauth/token','/v5/user_account','/v5/boards') for _,url in provider_calls[before:])
before=len(provider_calls)
for action in [lambda:service.oauth.start(pilot_wid,'p2','pinterest','publish'),
               lambda:provider.transport('POST','https://api.pinterest.com/v5/pins',body={})]:
    try: action()
    except AlphaError as error: assert error.status==403,error
    else: raise AssertionError('Official-API read-only Trial allowed publication')
assert len(provider_calls)==before
# Explicit read-only renewal uses the same locked custody; other owners cannot force it.
before=len(provider_calls);before_refresh=refreshes
try: service.oauth.refresh_pinterest_authorization(pilot_wid,'p1',pilot_cid)
except AlphaError as error: assert error.code=='pinterest_trial_denied',error
else: raise AssertionError('Other same-tenant owner forced pilot renewal')
assert len(provider_calls)==before
renewed=service.oauth.refresh_pinterest_authorization(pilot_wid,'p2',pilot_cid)
assert renewed['authorizationRefreshed'] and renewed['identityVerified'] and renewed['connectionId']==pilot_cid
assert 'accessToken' not in renewed and 'refreshToken' not in renewed
assert refreshes-before_refresh==1,refreshes
with connection() as db:
    assert db.execute('SELECT rotated_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',(pilot_wid,pilot_cid)).fetchone()[0]
assert all(url.startswith('https://api.pinterest.com/v5/') for _,url in provider_calls[before:])
manual_refreshes=refreshes-before_refresh
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
# Private capability-Trial create reservations use real independent transactions,
# not a process-local mock ledger. Every fixture below is synthetic and sends no provider traffic.
from dataclasses import replace
from postriff_phase2.pinterest_pilot import PinterestExecutionTrialPolicy

# Empty rollback/reapply preserves the independent rate ledger. Never erase prepared outcomes.
with connection() as db:
    private_rate_before_empty_rollback = db.execute('SELECT * FROM public.pr_pinterest_rate_budgets ORDER BY budget_key,window_start').fetchall()
    db.execute(journal_rollback)
    assert db.execute("SELECT to_regclass('public.pr_pinterest_trial_intents')").fetchone()[0] is None
    assert db.execute('SELECT * FROM public.pr_pinterest_rate_budgets ORDER BY budget_key,window_start').fetchall()==private_rate_before_empty_rollback
    db.execute(journal_migration)
    db.execute(journal_migration)

private_create_provider_calls_before = len(provider_calls)
private_create_expiry = int(time.time()) + 3600
private_create_policy = PinterestExecutionTrialPolicy(
    workspace_id=workspaces['p2'], actor_id=USERS['p2'], username='synthetic',
    expires_at=private_create_expiry, provider_account_id='1234567', board_ids=('7654321',),
    capabilities=frozenset({'identity','boards_read','publish','schedule','analytics'}),
    pilot_id='00000000-0000-0000-0000-000000000601')

def private_create_connection():
    db = connection()
    db.execute('SET ROLE service_role')
    db.execute("SET LOCAL lock_timeout = '5s'")
    db.execute("SET LOCAL statement_timeout = '10s'")
    return db

def private_create_quota(label):
    return PinterestQuota(private_create_connection, '1615884', 'synthetic-private-create-' + label,
                         clock=lambda:clock[0], trial=True)

def private_create_snapshot(quota):
    with connection() as db:
        rows = db.execute('SELECT budget_key,window_start,used FROM public.pr_pinterest_rate_budgets '
                          'WHERE budget_key LIKE %s ORDER BY budget_key', (quota.app + ':%',)).fetchall()
    return {'total':[(key, window, used) for key,window,used in rows if key.startswith(quota.app + ':private:')],
            'intents':[(key, window, used) for key,window,used in rows if key.startswith(quota.app + ':intent:')]}

def private_journal_authority(quota, policy):
    import hashlib
    binding_hash = hashlib.sha256(json.dumps(policy.binding(), sort_keys=True).encode()).hexdigest()
    return hashlib.sha256((quota.app + ':' + binding_hash).encode()).hexdigest()

def private_journal_rows(quota, policy):
    with connection() as db:
        return db.execute('SELECT intent_hash,pin_id,created_at,expires_at FROM public.pr_pinterest_trial_intents '
                          'WHERE authority_hash=%s ORDER BY intent_hash',
                          (private_journal_authority(quota,policy),)).fetchall()

def private_create_reservation(quota, policy, intent):
    try:
        quota.reserve_trial_create(policy, intent)
        return True
    except AlphaError as error:
        assert (error.status,error.code)==(409,'pinterest_trial_intent_consumed'),error
        return False

# Competing callers of one exact intent consume one total slot, not all retrying callers.
private_same_quota = private_create_quota('same-intent')
private_same_barrier = threading.Barrier(8)
def private_same_reserve(_):
    private_same_barrier.wait(timeout=15)
    return private_create_reservation(private_same_quota, private_create_policy, 'synthetic-immediate-intent')
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    private_same_results = list(pool.map(private_same_reserve, range(8)))
assert sum(private_same_results)==1,private_same_results
private_same_snapshot = private_create_snapshot(private_same_quota)
assert [row[2] for row in private_same_snapshot['total']]==[1],private_same_snapshot
assert [row[2] for row in private_same_snapshot['intents']]==[1],private_same_snapshot
assert len(private_journal_rows(private_same_quota,private_create_policy))==1
assert private_journal_rows(private_same_quota,private_create_policy)[0][1] is None
assert all(row[1]==private_create_expiry for rows in private_same_snapshot.values() for row in rows)
# Duplicate intent failure must roll back its tentative total increment, leaving the second slot usable.
private_same_quota.reserve_trial_create(private_create_policy, 'synthetic-scheduled-intent')
private_full_snapshot = private_create_snapshot(private_same_quota)
assert [row[2] for row in private_full_snapshot['total']]==[2],private_full_snapshot
assert len(private_full_snapshot['intents'])==2 and all(row[2]==1 for row in private_full_snapshot['intents'])
assert not private_create_reservation(private_same_quota, private_create_policy, 'synthetic-third-intent')
assert private_create_snapshot(private_same_quota)==private_full_snapshot

# Distinct concurrent intents share the same durable two-attempt cap.
private_distinct_quota = private_create_quota('distinct-intents')
private_distinct_barrier = threading.Barrier(12)
def private_distinct_reserve(index):
    private_distinct_barrier.wait(timeout=15)
    return private_create_reservation(private_distinct_quota, private_create_policy, 'synthetic-intent-' + str(index))
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
    private_distinct_results = list(pool.map(private_distinct_reserve, range(12)))
assert sum(private_distinct_results)==2,private_distinct_results
private_distinct_snapshot = private_create_snapshot(private_distinct_quota)
assert [row[2] for row in private_distinct_snapshot['total']]==[2],private_distinct_snapshot
assert len(private_distinct_snapshot['intents'])==2 and all(row[2]==1 for row in private_distinct_snapshot['intents'])
assert len(private_journal_rows(private_distinct_quota,private_create_policy))==2

# The dispatcher can hold a workspace transaction while the separate quota transaction commits.
# Simulate an unknown outer outcome AFTER that commit: neither rollback nor a new instance refunds it.
private_unknown_quota = private_create_quota('unknown-outer-outcome')
with connection() as db:
    private_original_revision = db.execute('SELECT revision FROM public.pr_workspaces WHERE id=%s',
                                           (workspaces['p2'],)).fetchone()[0]
class SyntheticUnknownOuterOutcome(Exception):
    pass
try:
    with connection() as outer:
        outer.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspaces['p2'],))
        outer.execute('UPDATE public.pr_workspaces SET revision=revision+1 WHERE id=%s', (workspaces['p2'],))
        private_unknown_quota.reserve_trial_create(private_create_policy, 'synthetic-lost-response-intent')
        # A third connection sees this reservation while the outer transaction is still uncommitted.
        private_committed_snapshot = private_create_snapshot(private_unknown_quota)
        assert [row[2] for row in private_committed_snapshot['total']]==[1],private_committed_snapshot
        assert [row[2] for row in private_committed_snapshot['intents']]==[1],private_committed_snapshot
        assert len(private_journal_rows(private_unknown_quota,private_create_policy))==1
        raise SyntheticUnknownOuterOutcome()
except SyntheticUnknownOuterOutcome:
    pass
with connection() as db:
    assert db.execute('SELECT revision FROM public.pr_workspaces WHERE id=%s',
                      (workspaces['p2'],)).fetchone()[0]==private_original_revision
assert private_create_snapshot(private_unknown_quota)==private_committed_snapshot
private_restarted_quota = private_create_quota('unknown-outer-outcome')
assert not private_create_reservation(private_restarted_quota, private_create_policy, 'synthetic-lost-response-intent')
assert private_create_snapshot(private_restarted_quota)==private_committed_snapshot
private_restarted_quota.reserve_trial_create(private_create_policy, 'synthetic-second-approved-intent')
assert not private_create_reservation(private_restarted_quota, private_create_policy, 'synthetic-extra-intent')
assert [row[2] for row in private_create_snapshot(private_restarted_quota)['total']]==[2]

# Invalid/expired intents fail before opening budget storage; a storage failure also fails closed.
private_invalid_connections = []
def private_counted_connection():
    private_invalid_connections.append(True)
    return private_create_connection()
private_invalid_quota = PinterestQuota(private_counted_connection, '1615884', 'synthetic-private-create-invalid', trial=True)
for invalid_intent in (None, '', 'x' * 257, True):
    try:
        private_invalid_quota.reserve_trial_create(private_create_policy, invalid_intent)
        raise AssertionError('Invalid Trial intent reserved a create attempt')
    except AlphaError as error:
        assert (error.status,error.code)==(403,'pinterest_trial_denied'),error
try:
    private_invalid_quota.reserve_trial_create(replace(private_create_policy, expires_at=int(time.time()) - 1), 'synthetic-expired')
    raise AssertionError('Expired Trial reserved a create attempt')
except AlphaError as error:
    assert (error.status,error.code)==(403,'pinterest_trial_denied'),error
assert private_invalid_connections==[]
assert private_create_snapshot(private_invalid_quota)=={'total':[],'intents':[]}

def private_readonly_connection():
    db = connection()
    db.execute('SET TRANSACTION READ ONLY')
    return db
private_storage_quota = PinterestQuota(private_readonly_connection, '1615884', 'synthetic-private-create-storage-failure', trial=True)
try:
    private_storage_quota.reserve_trial_create(private_create_policy, 'synthetic-unavailable-storage')
    raise AssertionError('Read-only budget storage admitted a create attempt')
except AlphaError as error:
    assert (error.status,error.code)==(503,'pinterest_quota_unavailable'),error
assert private_create_snapshot(private_storage_quota)=={'total':[],'intents':[]}
# A known response commits independently of the workspace proof and survives its rollback.
private_ack_quota = private_create_quota('durable-ack')
private_ack_quota.reserve_trial_create(private_create_policy,'synthetic-ack-intent')
assert private_ack_quota.recovered_trial_pin(private_create_policy,'synthetic-ack-intent') is None
private_ack_before = private_journal_rows(private_ack_quota,private_create_policy)
private_ack_pin = '987654301'
try:
    with connection() as outer:
        outer.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE',(workspaces['p2'],))
        assert private_ack_quota.acknowledge_trial_create(private_create_policy,'synthetic-ack-intent',private_ack_pin)==private_ack_pin
        assert private_ack_quota.recovered_trial_pin(private_create_policy,'synthetic-ack-intent')==private_ack_pin
        raise SyntheticUnknownOuterOutcome()
except SyntheticUnknownOuterOutcome:
    pass
private_ack_after = private_journal_rows(private_ack_quota,private_create_policy)
assert private_ack_after[0][1]==private_ack_pin
assert private_ack_after[0][0]==private_ack_before[0][0] and private_ack_after[0][2:]==private_ack_before[0][2:]
assert private_create_quota('durable-ack').recovered_trial_pin(private_create_policy,'synthetic-ack-intent')==private_ack_pin
assert private_ack_quota.acknowledge_trial_create(private_create_policy,'synthetic-ack-intent',private_ack_pin)==private_ack_pin
assert private_journal_rows(private_ack_quota,private_create_policy)==private_ack_after
for changed_intent,changed_pin in (('synthetic-ack-intent','987654302'),('unprepared-intent',private_ack_pin)):
    try:
        private_ack_quota.acknowledge_trial_create(private_create_policy,changed_intent,changed_pin)
        raise AssertionError('Acknowledgement created or overwrote a prepared response')
    except AlphaError as error:
        assert (error.status,error.code)==(409,'pinterest_trial_journal_conflict'),error
assert private_journal_rows(private_ack_quota,private_create_policy)==private_ack_after
assert private_create_quota('different-app-environment').recovered_trial_pin(private_create_policy,'synthetic-ack-intent') is None
assert private_ack_quota.recovered_trial_pin(private_create_policy,'different-intent') is None

# Even direct server-role writes cannot rewrite a known ID, erase the journal, or extend authority.
for statement,params,error_type in [
    ('UPDATE public.pr_pinterest_trial_intents SET pin_id=%s WHERE authority_hash=%s',
     ('987654302',private_journal_authority(private_ack_quota,private_create_policy)),psycopg.errors.CheckViolation),
    ("UPDATE public.pr_pinterest_trial_intents SET expires_at=expires_at+interval '1day' WHERE authority_hash=%s",
     (private_journal_authority(private_ack_quota,private_create_policy),),psycopg.errors.InsufficientPrivilege),
    ('DELETE FROM public.pr_pinterest_trial_intents WHERE authority_hash=%s',
     (private_journal_authority(private_ack_quota,private_create_policy),),psycopg.errors.InsufficientPrivilege),
    ('TRUNCATE public.pr_pinterest_trial_intents',(),psycopg.errors.InsufficientPrivilege)]:
    try:
        with private_create_connection() as db:
            db.execute(statement,params)
        raise AssertionError('Server-role privileges changed durable Trial evidence')
    except error_type:
        pass
assert private_journal_rows(private_ack_quota,private_create_policy)==private_ack_after
for client_role in ('anon','authenticated'):
    try:
        with connection() as db:
            db.execute('SET ROLE ' + client_role)
            db.execute('SELECT * FROM public.pr_pinterest_trial_intents')
        raise AssertionError('Client role read server-only Trial responses')
    except psycopg.errors.InsufficientPrivilege:
        pass

# A second prepared intent cannot claim another intent's known Pin ID (database uniqueness).
private_ack_quota.reserve_trial_create(private_create_policy,'synthetic-other-ack-intent')
try:
    private_ack_quota.acknowledge_trial_create(private_create_policy,'synthetic-other-ack-intent',private_ack_pin)
    raise AssertionError('Two intents claimed the same provider Pin ID')
except AlphaError as error:
    assert (error.status,error.code)==(503,'pinterest_quota_unavailable'),error
assert private_ack_quota.recovered_trial_pin(private_create_policy,'synthetic-other-ack-intent') is None
assert private_ack_quota.recovered_trial_pin(private_create_policy,'synthetic-ack-intent')==private_ack_pin

# Historical prepared-row fixture: a response arriving after real database expiry may be recorded,
# but it never restores live authority, creates another row or changes either timestamp.
private_expired_policy = replace(private_create_policy,expires_at=int(time.time())-10,
    pilot_id='00000000-0000-0000-0000-000000000602')
private_expired_intent = 'synthetic-late-provider-response'
import hashlib
with connection() as db:
    db.execute('INSERT INTO public.pr_pinterest_trial_intents(authority_hash,intent_hash,created_at,expires_at) '
               'VALUES(%s,%s,to_timestamp(%s),to_timestamp(%s))',
               (private_journal_authority(private_ack_quota,private_expired_policy),
                hashlib.sha256(private_expired_intent.encode()).hexdigest(),
                private_expired_policy.expires_at-60,private_expired_policy.expires_at))
private_expired_before = private_journal_rows(private_ack_quota,private_expired_policy)
assert private_ack_quota.acknowledge_trial_create(private_expired_policy,private_expired_intent,'987654303')=='987654303'
private_expired_after = private_journal_rows(private_ack_quota,private_expired_policy)
assert private_expired_after[0][1]=='987654303' and private_expired_after[0][2:]==private_expired_before[0][2:]
try:
    private_ack_quota.recovered_trial_pin(private_expired_policy,private_expired_intent)
    raise AssertionError('Expired authority recovered a Pin for provider use')
except AlphaError as error:
    assert (error.status,error.code)==(403,'pinterest_trial_denied'),error

# Missing schema must not spend counters or permit acknowledgement/recovery; restore only this fixture table.
private_missing_quota = private_create_quota('schema-missing')
with connection() as db:
    db.execute('ALTER TABLE public.pr_pinterest_trial_intents RENAME TO pr_pinterest_trial_intents_unavailable_test')
try:
    for operation in (lambda:private_missing_quota.reserve_trial_create(private_create_policy,'missing-schema'),
                      lambda:private_ack_quota.acknowledge_trial_create(private_create_policy,'synthetic-ack-intent',private_ack_pin),
                      lambda:private_ack_quota.recovered_trial_pin(private_create_policy,'synthetic-ack-intent')):
        try:
            operation()
            raise AssertionError('Missing journal schema admitted a Trial operation')
        except AlphaError as error:
            assert (error.status,error.code)==(503,'pinterest_quota_unavailable'),error
finally:
    with connection() as db:
        db.execute('ALTER TABLE public.pr_pinterest_trial_intents_unavailable_test RENAME TO pr_pinterest_trial_intents')
assert private_create_snapshot(private_missing_quota)=={'total':[],'intents':[]}
assert private_ack_quota.recovered_trial_pin(private_create_policy,'synthetic-ack-intent')==private_ack_pin

# Reapplying preserves immutable outcomes; rollback refuses even prepared/unknown rows.
with connection() as db:
    private_journal_before_reapply = db.execute('SELECT * FROM public.pr_pinterest_trial_intents ORDER BY authority_hash,intent_hash').fetchall()
    db.execute(journal_migration)
    assert db.execute('SELECT * FROM public.pr_pinterest_trial_intents ORDER BY authority_hash,intent_hash').fetchall()==private_journal_before_reapply
try:
    with connection() as db:
        db.execute(journal_rollback)
    raise AssertionError('Nonempty response journal rollback erased evidence')
except psycopg.errors.RaiseException:
    pass
with connection() as db:
    assert db.execute('SELECT * FROM public.pr_pinterest_trial_intents ORDER BY authority_hash,intent_hash').fetchall()==private_journal_before_reapply
assert len(provider_calls)==private_create_provider_calls_before

print('PINTEREST_POSTGRES_PASS '+json.dumps({'execution':'disposable_postgres_synthetic_provider','oauthReplayDenied':True,
    'oauthHostAppBindingConsumed':True,'oauthHostAppBindingReplayNoNetwork':True,'pilotUsernameExpiryBindingNoNetwork':True,
    'explicitOfficialApiReadOnlyConnected':True,'oldSandboxCustodyDenied':True,'officialApiTrialWriteDenied':True,
    'encryptedCustody':True,'tenantNegativeRead':True,'refreshConcurrentCallers':12,'providerRefreshes':concurrent_refreshes,'explicitManualProviderRefreshes':manual_refreshes,'manualRefreshOtherOwnerDenied':True,'manualRefreshReturnsNoCredentials':True,
    'disconnectCancelsClaimedCallback':True,'canceledCallbackNoNetwork':True,'freshExplicitReconnectPassed':True,
    'failedExchangeStateConsumed':True,'failedExchangeReplayNoNetwork':True,'pilotTenantAndActorFences':True,'pilotBroadGrantDenied':True,'pilotCallbackAuthorityRechecked':True,
    'pilotTwoReadScopesConnected':True,'pilotExpiryStopsCustody':True,'pilotDisconnectAfterExpiry':True,
    'trialDailyConcurrentReservations':120,'trialDailyAccepted':100,'trialDailyDenied':20,
    'trialMinuteCannotResetDaily':True,'trialDailyRecovery':True,'disconnectStopsTokenAccess':True,'otherTenantUnaffected':True,'quotaConcurrentReservations':120,
    'quotaAccepted':100,'quotaDenied':20,'quotaNextWindowRecovered':True,'clientBudgetAccessDenied':True,
    'supabaseDefaultGrantsSimulated':True,'quotaForcedRls':True,'quotaServiceRolePrivilegesBounded':True,
    'quotaServiceRoleDmlPassed':True,'quotaServiceRoleTruncateDenied':True,
    'privateTrialSameIntentConcurrentReservations':8,'privateTrialSameIntentAccepted':sum(private_same_results),
    'privateTrialDistinctIntentConcurrentReservations':12,'privateTrialDistinctIntentAccepted':sum(private_distinct_results),
    'privateTrialDuplicateDoesNotBurnSecondSlot':True,'privateTrialCreateTotalCap':2,'privateTrialCreatePerIntentCap':1,
    'privateTrialIndependentCommitBeforeOuterOutcome':True,'privateTrialOuterRollbackDoesNotRefund':True,
    'privateTrialReservationSurvivesNewInstance':True,'privateTrialInvalidExpiredIntentNoStorage':True,
    'privateTrialCreateStorageFailureClosed':True,'privateTrialCreateProviderCalls':0,
    'privateTrialJournalForcedRls':True,'privateTrialJournalNoWorkspaceForeignKey':True,
    'privateTrialJournalServerPrivilegesBounded':True,'privateTrialJournalClientReadDenied':True,
    'privateTrialJournalPrepareAtomicWithReservation':True,'privateTrialJournalAckIndependentCommit':True,
    'privateTrialJournalRecoveryAfterOuterRollback':True,'privateTrialJournalAckIdempotentImmutable':True,
    'privateTrialJournalKnownIdCannotBeShared':True,'privateTrialJournalAckAfterExpiryNoNewAuthority':True,
    'privateTrialJournalAuthorityAppEnvironmentBound':True,'privateTrialJournalMissingSchemaNoBudgetSpend':True,
    'privateTrialJournalEmptyRollbackReapplyPreservesRateLedger':True,'privateTrialJournalNonemptyRollbackRefused':True}))
