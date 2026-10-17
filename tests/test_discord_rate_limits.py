"""Offline P4 contracts. SQL here is a storage double, not concurrency/RLS proof.

Full execution belongs to approved cloud CI. PostgreSQL17 fixture covers the
real SQL/locks. No credentials, real provider, sockets or capacity claims.
"""
import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import PropertyMock, patch
from postriff_alpha.domain import AlphaError

from postriff_phase2.discord.rate_limits import (
    SharedPostgresBudget, RequestIdentity, SafetyPolicy, Permit, RateDelayed,
    RateCoordinatorUnavailable, route_identity, seconds, retry_hint,
    classify_response, publish_binding, _digest, observation_remaining,
)
from postriff_phase2.social_connectors import DiscordProvider

APP='123456789012345678'
A='111111111111111111'
B='222222222222222222'


def synthetic_policy(now=1000):
    return {'version':1,'revision':'synthetic-p4-v1','issued_at':now-10,'expires_at':now+3600,
            'egress_scope':'synthetic-egress','app_capacity':100,'app_window_seconds':10,
            'unknown_window_seconds':1,'invalid_capacity':3,'invalid_window_seconds':60,
            'failure_threshold':2,'circuit_seconds':30,'permit_ttl_seconds':2,'read_attempts':2}


class MemoryLedger:
    """Shared, rollback-capable storage double for the production algorithm.

    Optional workspace double lets worker guard tests use the same transaction.
    It does not emulate PostgreSQL lock ordering, roles or isolation levels.
    """
    def __init__(self,now=1000,workspace=None):
        self.now,self.workspace=now,workspace
        self.lock=threading.RLock()
        self.states,self.maps,self.admissions={},{},{}
        self.result=[];self.rowcount=1;self.serial=0;self.active=0;self.insert_delay=0
        self.scope_calls=[];self.lock_fault=None;self.store_fault=None;self.scope_lock_delay=0
        self.admission_lock_delay=0;self.connection_calls=0
    @contextmanager
    def connection(self):
        self.connection_calls+=1
        with self.lock:
            before=copy.deepcopy((self.states,self.maps,self.admissions))
            workspace_before=copy.deepcopy(self.workspace.state) if self.workspace else None
            self.active+=1
            try:yield self
            except BaseException:
                self.states,self.maps,self.admissions=before
                if self.workspace:self.workspace.state=workspace_before
                raise
            finally:self.active-=1
    @contextmanager
    def cursor(self):yield self
    def execute(self,query,params=()):
        sql=' '.join(query.split())
        self.result=[];self.rowcount=1
        if sql.startswith('SET LOCAL') or sql.startswith("SELECT set_config('lock_timeout'"):return
        if sql.startswith('SELECT extract(epoch from clock_timestamp()'):
            self.result=[(self.workspace.now if self.workspace else self.now,)];return
        workspace_selector = (sql == "SELECT to_regclass('public.pr_discord_worker_projection')"
            or sql.startswith('SELECT w.id::text,w.revision,w.state')
               and 'JOIN public.pr_discord_worker_projection' in sql)
        if self.workspace and ('public.pr_discord_' not in sql or workspace_selector):
            self.workspace.execute(query,params)
            self.result=self.workspace.fetchall();self.rowcount=self.workspace.rowcount;return
        if sql.startswith('INSERT INTO public.pr_discord_route_buckets'):
            self.maps.setdefault(tuple(params),[None,0])
            if 'RETURNING bucket_key,observation_seq' in sql:self.result=[tuple(self.maps[tuple(params)])]
        elif sql.startswith('SELECT bucket_key,observation_seq'):
            row=self.maps.get(tuple(params))
            self.result=[tuple(row)] if row is not None else []
        elif sql.startswith('WITH scope_seed('):
            ordered=[];self.rowcount=0
            for index in range(0,len(params),7):
                key,kind,cap,left,window,revision,_expires=params[index:index+7];ordered.append(key)
                if key not in self.states:
                    self.rowcount+=1
                    self.states[key]=dict(kind=kind,cap=cap,left=left,window=window,reset=self.now,
                        blocked=None,circuit=None,streak=0,hold=False,seq=0,policy=revision,policyExpires=_expires,learned=False,freshAfter=None)
            self.scope_calls.append(('seed',tuple(ordered)))
        elif sql.startswith('WITH scope_lock AS MATERIALIZED'):
            self.now+=self.scope_lock_delay
            if self.workspace:self.workspace.now+=self.scope_lock_delay
            ordered=sorted(set(params[0])|set(params[1])) if 'FOR SHARE' in sql else params[0]
            self.scope_calls.append(('lock',tuple(ordered)))
            self.result=[(key,)+tuple(self.states[key][k] for k in
                ('kind','cap','left','window','reset','blocked','circuit','streak','hold','seq','policy','policyExpires','learned','freshAfter')) for key in ordered if key in self.states]
            if self.lock_fault=='missing':self.result=self.result[1:]
            elif self.lock_fault=='extra':self.result=self.result+[(('99:'+'0'*64),)+self.result[0][1:]]
            elif self.lock_fault=='duplicate':self.result=[self.result[0]]+self.result[:-1]
            elif self.lock_fault=='reordered':self.result.reverse()
        elif sql.startswith('WITH scope_store('):
            ordered=[];self.result=[]
            for index in range(0,len(params),14):
                cap,left,window,reset,blocked,circuit,streak,hold,seq,revision,_expiry,learned,fresh_after,key=params[index:index+14]
                ordered.append(key)
                if key in self.states:
                    self.states[key].update(cap=cap,left=left,window=window,reset=reset,blocked=blocked,
                        circuit=circuit,streak=streak,hold=hold,seq=seq,policy=revision,policyExpires=_expiry,learned=learned,freshAfter=fresh_after)
                    self.result.append((key,))
            self.scope_calls.append(('store',tuple(ordered)));self.rowcount=len(self.result)
            if self.store_fault=='count':self.rowcount-=1
            elif self.store_fault=='key':self.result[0]=('99:'+'0'*64,)
            elif self.store_fault=='duplicate':self.result=[self.result[0]]+self.result[:-1]
        elif sql.startswith('WITH locked_pending AS MATERIALIZED'):
            key,now=params
            self.result=[(sum(key in r['keys'] and (r['state'] in ('sent','uncertain') or
                r['state'] in ('reserved','sealed') and r['expires']>now) for r in self.admissions.values()),)]
        elif sql.startswith('WITH locked_alias AS MATERIALIZED'):
            pid,alias,auth,route,major,_alias,now=params
            pending=[r for r in self.admissions.values() if r['id']!=pid and
                (alias in r['keys'] or (r['auth'],r['route'],r['major'])==(auth,route,major)) and
                (r['state'] in ('sent','uncertain') or r['state'] in ('reserved','sealed') and r['expires']>now)]
            self.result=[(len(pending),sum(alias not in r['keys'] for r in pending))]
        elif sql.startswith('WITH reservation_clock AS MATERIALIZED'):
            self.now+=self.insert_delay
            moment=self.workspace.now if self.workspace else self.now
            if params[-1]<=moment:
                self.rowcount=0;return
            self.serial+=1
            names=('id','application','auth','credential','kind','method','path','route','major','bucket','keys',
                'publish','binding','workspace','publication','manifest','authorization','approval','worker','lease','channel','expires')
            row=dict(zip(names,params[:-1]));row.update(seq=self.serial,state='sent' if ',state,sent_at)' in sql else 'reserved',intent=None,reserved=moment)
            if row['publish'] and any(r['binding']==row['binding'] for r in self.admissions.values()):
                raise ValueError('Duplicate synthetic binding')
            self.admissions[row['id']]=row
        elif sql.startswith('SELECT request_seq,application_key'):
            self.now+=self.admission_lock_delay
            if self.workspace:self.workspace.now+=self.admission_lock_delay
            r=self.admissions.get(params[0])
            if r:self.result=[tuple(r[k] for k in ('seq','application','auth','credential','kind','method','path',
                'route','major','bucket','keys','binding','state','intent','expires','reserved'))]
        elif sql.startswith('SELECT route_key,major_key'):
            r=self.admissions.get(params[0]);self.result=[(r['route'],r['major'])] if r else []
        elif sql.startswith('SELECT scope_keys'):
            self.result=[(self.admissions[params[0]]['keys'],)]
        elif sql.startswith('UPDATE public.pr_discord_route_buckets'):
            bucket,seq,auth,route,major=params;self.maps[(auth,route,major)]=[bucket,seq]
        elif 'SET bucket_key=' in sql:
            bucket,key,auth,route,major,_key=params
            for r in self.admissions.values():
                if (r['auth'],r['route'],r['major'])==(auth,route,major) and r['state'] in ('reserved','sealed','sent','uncertain') and key not in r['keys']:
                    r['bucket']=bucket;r['keys']=r['keys']+[key]
        elif "SET state='sealed'" in sql:
            intent,pid=params;r=self.admissions[pid]
            self.rowcount=int(r['state']=='reserved')
            if self.rowcount:r.update(state='sealed',intent=intent)
        elif "SET state='sent'" in sql:
            pid,expected=params;r=self.admissions[pid];self.rowcount=int(r['state']==expected)
            if self.rowcount:r['state']='sent'
        elif "SET state='blocked',outcome_at=clock_timestamp() WHERE id=" in sql:
            r=self.admissions[params[0]];self.rowcount=int(r['state']=='sent' and r['method']=='GET' and not r['publish'])
            if self.rowcount:r['state']='blocked'
        elif "SET state='blocked'" in sql:
            for r in self.admissions.values():
                if r['state'] in ('reserved','sealed') and params[0] in r['keys']:r['state']='blocked'
        elif 'SET state=%s,status_code=' in sql:
            state,status,scope,pid=params;r=self.admissions[pid];self.rowcount=int(r['state']=='sent')
            if self.rowcount:r.update(state=state,status=status,scope=scope)
        else:raise AssertionError('Unrecognized synthetic SQL contract: '+sql[:110])
    def fetchone(self):return self.result.pop(0) if self.result else None
    def fetchall(self):result,self.result=self.result,[];return result


class ScopeBatchRegression(unittest.TestCase):
    """Inert exact-set/rollback controls; SQL locking requires the remote gate."""
    def setUp(self):
        self.db=MemoryLedger()
        self.s=SharedPostgresBudget(self.db.connection,APP,policy=synthetic_policy())
        self.identity=RequestIdentity.make(APP,'bot','inert-batch-bot')
        self.path='/channels/'+A+'/messages/'+B

    def reserve(self):return self.s.reserve('GET',self.path,identity=self.identity)

    def test_reservation_uses_three_sorted_scope_operations_for_the_exact_set(self):
        self.reserve()
        self.assertEqual([kind for kind,_ in self.db.scope_calls],['seed','lock','store'])
        ordered=self.db.scope_calls[0][1]
        self.assertEqual(len(ordered),7)
        self.assertEqual(ordered,tuple(sorted(ordered)))
        self.assertEqual(self.db.scope_calls[1][1],ordered)
        stored=self.db.scope_calls[2][1]
        self.assertEqual(stored,tuple(key for key in ordered if self.db.states[key]['kind'] in ('policy','invalid','discovery','route')))
        for row in self.db.states.values():
            if row['kind'] in ('global','credential','resource'):
                self.assertEqual((row['cap'],row['left'],row['window']),(None,None,None))

    def test_observation_uses_three_operations_and_retains_first_learning(self):
        permit=self.reserve();self.s.consume(permit,'GET',self.path);self.db.scope_calls.clear()
        self.s.observe(permit,{'status':200,'headers':{'X-RateLimit-Bucket':'batch-window',
            'X-RateLimit-Limit':'3','X-RateLimit-Remaining':'2','X-RateLimit-Reset-After':'1'}})
        self.assertEqual([kind for kind,_ in self.db.scope_calls],['seed','lock','store'])
        ordered=self.db.scope_calls[0][1]
        self.assertEqual(self.db.scope_calls[1][1],ordered)
        self.assertEqual(self.db.scope_calls[2][1],tuple(key for key in ordered
            if self.db.states[key]['kind'] in ('discovery','route')))
        self.assertEqual(max(row['left'] for row in self.db.states.values() if row['kind']=='route'),2)

    def test_cold_observation_preserves_unchanged_guards_and_route_ordering(self):
        permit=self.reserve();self.s.consume(permit,'GET',self.path)
        guards={key:copy.deepcopy(row) for key,row in self.db.states.items()
                if row['kind'] in ('policy','global','credential','invalid','resource')}
        self.s.observe(permit,{'status':200,'headers':{'X-RateLimit-Bucket':'new-cold-alias',
            'X-RateLimit-Limit':'3','X-RateLimit-Remaining':'2','X-RateLimit-Reset-After':'1'}})
        self.assertEqual({key:self.db.states[key] for key in guards},guards)
        self.assertEqual(self.db.admissions[permit.id]['state'],'observed')
        self.assertTrue(all(row['seq']==self.db.admissions[permit.id]['seq']
            for row in self.db.states.values() if row['kind']=='route'))

    def test_partial_observation_store_rolls_back_alias_guards_and_outcome(self):
        permit=self.reserve();self.s.consume(permit,'GET',self.path)
        before=copy.deepcopy((self.db.states,self.db.maps,self.db.admissions))
        self.db.store_fault='count'
        with self.assertRaises(RateCoordinatorUnavailable):
            self.s.observe(permit,{'status':429,'headers':{'X-RateLimit-Bucket':'new-failing-alias',
                'X-RateLimit-Global':'true','Retry-After':'2'},'body':{'retry_after':2,'global':True}})
        self.assertEqual((self.db.states,self.db.maps,self.db.admissions),before)

    def test_bad_locked_row_set_or_order_rolls_back_seed_and_mapping(self):
        for fault in ('missing','extra','duplicate','reordered'):
            with self.subTest(fault=fault):
                self.db.lock_fault=fault
                with self.assertRaises(RateCoordinatorUnavailable):self.reserve()
                self.assertFalse(self.db.states or self.db.maps or self.db.admissions)

    def test_partial_store_count_or_returned_scope_rolls_back_every_debit(self):
        for fault in ('count','key','duplicate'):
            with self.subTest(fault=fault):
                self.db.store_fault=fault
                with self.assertRaises(RateCoordinatorUnavailable):self.reserve()
                self.assertFalse(self.db.states or self.db.maps or self.db.admissions)

    def test_store_rejects_missing_or_extra_unlocked_scope_before_sql(self):
        template,major=route_identity('GET',self.path)
        keys=self.s._keys(self.identity,_digest(template),major,None)
        for fault in ('missing','extra'):
            with self.subTest(fault=fault),self.assertRaises(RateCoordinatorUnavailable):
                with self.s._transaction() as cur:
                    rows=self.s._locked(cur,keys)
                    if fault=='missing':rows.pop(next(iter(rows)))
                    else:rows['99:'+'0'*64]=copy.deepcopy(next(iter(rows.values())))
                    before=len(self.db.scope_calls)
                    try:self.s._store_batch(cur,rows,locked_keys=keys)
                    finally:self.assertEqual(len(self.db.scope_calls),before)
            self.assertFalse(self.db.states or self.db.maps or self.db.admissions)

    def test_store_preserves_late_observation_policy_and_expiry_merge(self):
        template,major=route_identity('GET',self.path);keys=self.s._keys(self.identity,_digest(template),major,None)
        with self.s._transaction() as cur:
            rows=self.s._locked(cur,keys)
            for row in rows.values():row.update(policy='older-policy',policyExpires=self.db.now+1)
            self.s._store_batch(cur,rows,locked_keys=keys,forward=False)
        self.assertTrue(all(row['policy']=='older-policy' and row['policyExpires']==self.db.now+1 for row in self.db.states.values()))
        with self.s._transaction() as cur:
            rows=self.s._locked(cur,keys)
            self.s._store_batch(cur,rows,locked_keys=keys,forward=True)
        self.assertTrue(all(row['policy']==self.s.policy.revision and row['policyExpires']==self.s.policy.expires_at for row in self.db.states.values()))

    def test_post_lock_clock_check_still_rejects_expired_policy(self):
        self.db.scope_lock_delay=3601
        with self.assertRaises(RateCoordinatorUnavailable):self.reserve()
        self.assertFalse(self.db.states or self.db.maps or self.db.admissions)

    def test_unbound_consume_rechecks_policy_after_admission_lock(self):
        permit=self.reserve()
        self.db.admission_lock_delay=3601
        with self.assertRaises(RateCoordinatorUnavailable):self.s.consume(permit,'GET',self.path)
        self.assertEqual(self.db.admissions[permit.id]['state'],'reserved')


class BotIdentityCacheRegression(unittest.TestCase):
    """Identity caching never supplies guild/channel permission evidence."""
    def setUp(self):
        from test_discord_publish_authorization import SyntheticWire, APP as fixture_app, BOT, USER, GUILD
        self.bot,self.user,self.guild=BOT,USER,GUILD
        self.wire=SyntheticWire()
        self.p=DiscordProvider(fixture_app,'synthetic-secret','synthetic-bot','https://rafii.invalid')
        self.p.authorization_v2_enabled=self.p.connections_v2_enabled=self.p.rate_v1_enabled=True
        self.p.rate_limiter=SharedPostgresBudget(MemoryLedger().connection,fixture_app,policy=synthetic_policy())
        self.p._bot=lambda method,path,**kwargs:self.wire(method,self.p.API+path)
        self.now=100.
        clock=patch('postriff_phase2.social_connectors.time.monotonic',side_effect=lambda:self.now)
        clock.start();self.addCleanup(clock.stop)
        network=patch('socket.socket.connect',side_effect=AssertionError('Real network forbidden'))
        network.start();self.addCleanup(network.stop)

    def identity_calls(self):
        return sum(path in ('/oauth2/applications/@me','/users/@me') for _,path,_ in self.wire.calls)

    def test_verified_identity_is_reused_without_storing_the_token(self):
        self.assertEqual(self.p._bot_identity(),self.bot)
        self.assertEqual(self.p._bot_identity(),self.bot)
        self.assertEqual(self.identity_calls(),2)
        self.assertNotIn('synthetic-bot',repr(self.p._bot_identity_cache))

    def test_expiry_and_monotonic_rollback_force_fresh_verification(self):
        self.p._bot_identity();self.now+=60;self.p._bot_identity()
        self.assertEqual(self.identity_calls(),4)
        self.now-=1;self.p._bot_identity()
        self.assertEqual(self.identity_calls(),6)

    def test_token_and_application_changes_cannot_reuse_the_cached_identity(self):
        self.p._bot_identity();self.p.bot_token='rotated-synthetic-bot';self.p._bot_identity()
        self.assertEqual(self.identity_calls(),4)
        self.p.client_id='999999'
        with self.assertRaises(AlphaError):self.p._bot_identity()
        self.assertEqual(self.identity_calls(),6)
        self.assertNotEqual(self.p._bot_identity_cache[0],self.p.client_id)

    def test_missing_or_degraded_coordinator_cannot_use_cached_identity(self):
        self.p._bot_identity();budget=self.p.rate_limiter
        for broken in ('degraded','missing','policy'):
            with self.subTest(broken=broken):
                self.p.rate_coordinator_degraded=broken=='degraded'
                self.p.rate_limiter=None if broken=='missing' else budget
                original=budget.policy
                if broken=='policy':budget.policy=None
                try:
                    with self.assertRaises(RateCoordinatorUnavailable):self.p._bot_identity()
                finally:budget.policy=original
        self.assertEqual(self.identity_calls(),2)

    def test_cached_identity_does_not_keep_removed_channel_permissions(self):
        session=json.dumps({'v':2,'applicationId':self.p.client_id,'botUserId':self.bot,
                            'user':self.user,'guild':self.guild})
        self.assertTrue(self.p.destinations(session))
        self.wire.allowed.clear()
        self.assertEqual(self.p.destinations(session),[])
        self.assertEqual(self.identity_calls(),2)
        self.assertEqual(sum(path=='/guilds/'+self.guild+'/channels' for _,path,_ in self.wire.calls),2)


class SharedObservationRegression(unittest.TestCase):
    """Rollback/eligibility controls; shared-lock proof requires real PG17."""
    def setUp(self):
        self.db=MemoryLedger()
        self.s=SharedPostgresBudget(self.db.connection,APP,policy=synthetic_policy())
        self.identity=RequestIdentity.make(APP,'bot','inert-shared-observer')
        self.path='/channels/'+A+'/messages/'+B
        self.response={'status':200,'headers':{'X-RateLimit-Bucket':'shared-observer',
            'X-RateLimit-Limit':'100','X-RateLimit-Remaining':'99','X-RateLimit-Reset-After':'30'}}
        p=self.s.reserve_read('GET',self.path,identity=self.identity)
        self.s.observe(p,self.response)

    def permit(self):return self.s.reserve_read('GET',self.path,identity=self.identity)

    def test_warm_success_writes_only_route_and_preserves_common_guards(self):
        p=self.permit()
        common={k:copy.deepcopy(v) for k,v in self.db.states.items() if k[:3] in ('00:','10:','11:','20:','40:')}
        self.db.scope_calls.clear()
        with patch.object(self.s,'_locked',wraps=self.s._locked) as locked:
            self.s.observe(p,self.response)
        self.assertTrue(locked.call_args.kwargs['shared_keys'])
        self.assertEqual(common,{k:self.db.states[k] for k in common})
        self.assertTrue(all(k.startswith('50:') for k in self.db.scope_calls[-1][1]))
        self.assertEqual(self.db.admissions[p.id]['state'],'observed')

    def test_each_scope_hold_block_or_circuit_rolls_back_then_restarts_exclusively(self):
        for kind in ('policy','global','credential','invalid','resource','route'):
            for field,value in (('hold',True),('blocked',1005),('circuit',1005)):
                with self.subTest(kind=kind,field=field):
                    self.setUp();p=self.permit();waiting=self.s.reserve('GET',self.path,identity=self.identity)
                    key=next(k for k in self.db.admissions[p.id]['keys'] if self.db.states[k]['kind']==kind)
                    self.db.states[key][field]=value
                    with patch.object(self.s,'_observe_once',wraps=self.s._observe_once) as observed:
                        self.s.observe(p,self.response)
                    self.assertEqual([call.args[-1] for call in observed.call_args_list],[True,False])
                    self.assertEqual(self.db.states[key][field],value)
                    self.assertEqual(self.db.admissions[waiting.id]['state'],'blocked')

    def test_bad_numeric_hint_restarts_before_alias_scan_and_retains_hold(self):
        p=self.permit();response=copy.deepcopy(self.response)
        response['headers']['X-RateLimit-Remaining']='invalid'
        with patch.object(self.s,'_alias_pending',wraps=self.s._alias_pending) as pending:
            with patch.object(self.s,'_observe_once',wraps=self.s._observe_once) as observed:
                self.s.observe(p,response)
        self.assertEqual([call.args[-1] for call in observed.call_args_list],[True,False])
        self.assertEqual(pending.call_count,1)
        self.assertTrue(any(v['hold'] for v in self.db.states.values() if v['kind']=='route'))

    def test_discovery_historical_membership_forces_original_exclusive_path(self):
        p=self.permit();discovery='30:'+_digest(self.identity.auth_key+':historical')
        self.db.admissions[p.id]['keys'].append(discovery)
        self.db.states[discovery]=dict(copy.deepcopy(next(v for v in self.db.states.values() if v['kind']=='route')),kind='discovery')
        with patch.object(self.s,'_locked',wraps=self.s._locked) as locked:self.s.observe(p,self.response)
        self.assertNotIn('shared_keys',locked.call_args.kwargs)

    def test_error_publish_and_unsupported_outcomes_are_never_shared(self):
        p=self.permit()
        for status,scope,glob,transport,method,binding in ((401,None,False,False,'GET',None),
                (429,None,True,False,'GET',None),(429,'shared',False,False,'GET',None),
                (503,None,False,True,'GET',None),(200,None,False,False,'POST','frozen')):
            classification={'status':status,'scope':scope,'global':glob,'invalid':status in (401,429)}
            self.assertFalse(self.s._share_get_observation(replace(p,method=method,binding_hash=binding),
                classification,_digest('bucket'),transport))


class AliasLearningRegression(unittest.TestCase):
    """Targeted inert algorithm checks; real locking/RLS remains a SQL gate."""
    def setUp(self):
        self.db=MemoryLedger()
        self.s=SharedPostgresBudget(self.db.connection,APP,policy=synthetic_policy())
        self.identity=RequestIdentity.make(APP,'bot','inert-alias-bot')
        self.path='/channels/'+A+'/messages/'+B

    def response(self,left=249):
        return {'status':200,'headers':{'X-RateLimit-Bucket':'alias-regression',
            'X-RateLimit-Limit':'250','X-RateLimit-Remaining':str(left),'X-RateLimit-Reset-After':'1'}}

    def send(self,path=None,response=None):
        target=path or self.path
        p=self.s.reserve('GET',target,identity=self.identity)
        self.s.consume(p,'GET',target);self.s.observe(p,response or self.response());return p

    def alias(self):
        _,major=route_identity('GET',self.path)
        return '50:'+_digest(self.identity.auth_key+':'+_digest('alias-regression')+':'+major)

    def test_first_learning_replaces_probe_zero_with_available_provider_quota(self):
        self.send()
        self.assertEqual(self.db.states[self.alias()]['left'],249)
        self.assertIsInstance(self.s.reserve('GET',self.path,identity=self.identity),Permit)

    def test_new_route_into_known_alias_charges_the_observer_exactly_once(self):
        self.send()
        self.send(self.path.rsplit('/',1)[0],self.response(248))
        self.assertEqual(self.db.states[self.alias()]['left'],248)

    def test_pending_union_does_not_double_count_already_mapped_requests(self):
        self.send()
        waiting=self.s.reserve('GET',self.path,identity=self.identity)
        probe=self.path.rsplit('/',1)[0]
        p=self.s.reserve('GET',probe,identity=self.identity);self.s.consume(p,'GET',probe)
        template,major=route_identity('GET',probe)
        pending,unmapped=self.s._alias_pending(self.db,self.alias(),p,(_digest(template),major),self.db.now)
        self.assertEqual((pending,unmapped),(1,0))
        self.s.observe(p,self.response(248))
        self.assertEqual(self.db.states[self.alias()]['left'],247)
        self.assertEqual(self.db.admissions[waiting.id]['keys'].count(self.alias()),1)

    def test_known_quota_cannot_refill_from_a_higher_remaining_header(self):
        self.send();p=self.s.reserve('GET',self.path,identity=self.identity)
        self.s.consume(p,'GET',self.path);self.s.observe(p,self.response(249))
        self.assertEqual(self.db.states[self.alias()]['left'],248)

    def test_tightened_stable_bucket_keeps_other_reserved_request_charged(self):
        first=self.response(5);first['headers']['X-RateLimit-Limit']='6'
        self.send(response=first)
        sent=self.s.reserve_read('GET',self.path,identity=self.identity)
        waiting=self.s.reserve('GET',self.path,identity=self.identity)
        tightened=self.response(1);tightened['headers']['X-RateLimit-Limit']='2'
        self.s.observe(sent,tightened)
        self.assertEqual(self.db.states[self.alias()]['left'],0)
        self.assertEqual(self.db.admissions[waiting.id]['state'],'reserved')
        with self.assertRaises(RateDelayed):self.s.reserve_read('GET',self.path,identity=self.identity)

    def test_expired_insert_rolls_back_all_debits_and_creates_no_admission(self):
        self.db.insert_delay=2
        with self.assertRaises(RateDelayed) as caught:self.s.reserve('GET',self.path,identity=self.identity)
        self.assertEqual((caught.exception.rate_cause,caught.exception.rate_scope_kind),('permit_expired','permit'))
        self.assertFalse(self.db.states or self.db.maps or self.db.admissions)
        self.db.insert_delay=0
        self.assertIsInstance(self.s.reserve('GET',self.path,identity=self.identity),Permit)

    def test_short_positive_window_is_usable_but_consume_never_extends_expiry(self):
        self.send()
        deadline=self.db.now+.01
        self.db.states[self.alias()]['reset']=deadline
        permit=self.s.reserve('GET',self.path,identity=self.identity)
        self.assertAlmostEqual(permit.expires_at,deadline,places=6)
        self.assertLess(permit.expires_at-self.db.now,.025)
        self.db.now=deadline
        with self.assertRaises(RateDelayed):self.s.consume(permit,'GET',self.path)
        self.assertEqual(self.db.admissions[permit.id]['state'],'reserved')
        self.assertEqual(self.db.admissions[permit.id]['expires'],permit.expires_at)

    def test_short_window_that_expires_during_insert_rolls_back_exactly(self):
        self.send()
        self.db.states[self.alias()]['reset']=self.db.now+.01
        before=copy.deepcopy((self.db.states,self.db.maps,self.db.admissions))
        self.db.insert_delay=.02
        with self.assertRaises(RateDelayed) as caught:self.s.reserve('GET',self.path,identity=self.identity)
        self.assertEqual(caught.exception.rate_cause,'permit_expired')
        self.assertEqual((self.db.states,self.db.maps,self.db.admissions),before)

    def test_remaining_formula_and_denial_symbols_reject_untrusted_values(self):
        self.assertEqual(observation_remaining(0,249,first=True,pending=3),246)
        self.assertEqual(observation_remaining(200,249,first=False,pending=5,newly_mapped=2,current_unmapped=1),197)
        self.assertEqual(RateDelayed(1,scope='private-key').rate_scope_kind,'unknown')
        with self.assertRaises(RateCoordinatorUnavailable):observation_remaining(0,249,first=True,pending=True)

    def test_fresh_bucket_after_roll_replaces_policy_deadline_with_provider_reset(self):
        self.send()
        self.db.now+=1.1
        p=self.s.reserve('GET',self.path,identity=self.identity);self.s.consume(p,'GET',self.path)
        self.assertEqual(self.db.states[self.alias()]['reset'],synthetic_policy()['expires_at'])
        response=self.response(2)
        response['headers'].update({'X-RateLimit-Bucket':'fresh-after-roll','X-RateLimit-Limit':'3'})
        self.s.observe(p,response)
        _,major=route_identity('GET',self.path)
        key='50:'+_digest(self.identity.auth_key+':'+_digest('fresh-after-roll')+':'+major)
        row=self.db.states[key]
        self.assertEqual(row['reset'],self.db.now+1)
        self.assertIsNone(row['freshAfter'])
        self.assertEqual(row['left'],2)
        self.db.now+=1.1
        self.assertIsInstance(self.s.reserve('GET',self.path,identity=self.identity),Permit)

    def test_expired_sent_admission_still_counts_once_but_expired_unused_does_not(self):
        self.send()
        sent,unused=[self.s.reserve('GET',self.path,identity=self.identity) for _ in range(2)]
        self.s.consume(sent,'GET',self.path)
        self.db.now=sent.expires_at+.1
        template,major=route_identity('GET',self.path)
        self.assertEqual(self.s._alias_pending(self.db,self.alias(),unused,(_digest(template),major),self.db.now),(1,0))
        self.assertEqual(self.s._pending(self.db,self.alias(),self.db.now),1)


class RateLimits(unittest.TestCase):
    def setUp(self):
        self.db=MemoryLedger()
        self.policy=synthetic_policy()
        self.s=SharedPostgresBudget(self.db.connection,APP,policy=self.policy)
        self.identity=RequestIdentity.make(APP,'bot','synthetic-bot')
        self.path='/channels/'+A+'/messages/'+B
        self.calls=[]
        self.response={'status':200,'headers':{},'body':{'id':B}}
        def transport(method,url,**kwargs):
            self.assertEqual(self.db.active,0,'Provider I/O under SQL transaction')
            self.calls.append((method,url,kwargs));return copy.deepcopy(self.response)
        self.p=DiscordProvider(APP,'synthetic-secret','synthetic-bot','https://rafii.invalid',transport=transport)
        self.p.rate_v1_enabled=True;self.p.rate_limiter=self.s
        self.network=patch('socket.socket.connect',side_effect=AssertionError('Real network forbidden'))
        self.network.start();self.addCleanup(self.network.stop)
    def reserve(self,path=None,**kwargs):
        return self.s.reserve('GET',path or self.path,identity=self.identity,**kwargs)
    def send(self,response=None,path=None):
        p=self.reserve(path);self.s.consume(p,'GET',path or self.path)
        self.s.observe(p,response or {'status':200,'headers':{}});return p
    def learn(self,path=None,bucket='learned',cap=3):
        return self.send({'status':200,'headers':{'X-RateLimit-Bucket':bucket,
            'X-RateLimit-Limit':str(cap),'X-RateLimit-Remaining':str(cap-1),'X-RateLimit-Reset-After':'1'}},path)
    def test_route_and_numeric_parsing_are_bounded(self):
        self.assertEqual(route_identity('GET',self.path),route_identity('GET','/channels/'+A+'/messages/'+A))
        self.assertNotEqual(route_identity('GET',self.path),route_identity('GET','/channels/'+B+'/messages/'+B))
        for path in ('/channels/no/messages','//channels/'+A,'/webhooks/'+A+'/SECRET','/users/@me?code=SECRET','/users/@me/guilds?limit=200&limit=200','/users/@me/guilds?broken'):
            with self.subTest(path=path),self.assertRaises(RateCoordinatorUnavailable):route_identity('GET',path)
        route_identity('GET','/users/@me/guilds?limit=200&after='+A)
        for raw in ('nan','inf','-1',True):self.assertIsNone(seconds(raw))
        self.assertEqual(retry_hint({'headers':{'Retry-After':'2.75'},'body':{'retry_after':4.125}},1000),(4.125,False))
    def test_budget_denial_sends_no_http_and_does_not_refund(self):
        self.p._bot('GET',self.path)
        with self.assertRaises(RateDelayed):self.p._bot('GET',self.path)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(self.db.admissions),1)
    def test_first_publish_header_learns_shared_quota_without_refilling_known_windows(self):
        path='/channels/'+A+'/messages'
        def binding(publication):
            return {'workspaceId':'00000000-0000-0000-0000-000000000001','publicationId':publication,
                'manifestDigest':'a'*64,'authorizationDigest':'b'*64,'approvalDigest':'c'*64,
                'workerKey':'d'*64,'leaseKey':_digest(publication),'channelKey':_digest(A),
                'applicationKey':_digest(APP)}
        first=binding('first-workspace-publication')
        permit=self.s.reserve('POST',path,identity=self.identity,binding=first)
        with self.db.connection() as db,db.cursor() as cur:
            self.s.seal(cur,permit,first,'synthetic-intent',self.db.now+2)
        self.s.consume(permit,'POST',path,binding=first,intent_id='synthetic-intent',
            authorize=lambda cur:self.db.now+2)
        self.s.observe(permit,{'status':200,'headers':{'X-RateLimit-Bucket':'publish-window',
            'X-RateLimit-Limit':'100','X-RateLimit-Remaining':'99','X-RateLimit-Reset-After':'30'}})
        replica=SharedPostgresBudget(self.db.connection,APP,policy=self.policy)
        for index in range(99):
            replica.reserve('POST',path,identity=self.identity,binding=binding('distinct-publication-'+str(index)))
        with self.assertRaises(RateDelayed) as caught:
            replica.reserve('POST',path,identity=self.identity,binding=binding('second-publication'))
        self.assertEqual(caught.exception.retry_after_seconds,30)
        self.db.now+=30.1  # advance the established mock reset, once
        for index in range(5):
            replica.reserve('POST',path,identity=self.identity,binding=binding('guarded-'+str(index)))
        self.assertEqual(len(self.db.admissions),105)
        self.assertEqual(self.calls,[],'Storage-only regression must never call provider transport')
    def test_learned_three_slots_cannot_be_multiplied_by_workers(self):
        for count in (1,8,16):
            self.setUp();self.learn();self.db.now+=1.1
            def claim(_):
                limiter=SharedPostgresBudget(self.db.connection,APP,policy=self.policy)
                try:return limiter.reserve('GET',self.path,identity=self.identity)
                except RateDelayed:return None
            with ThreadPoolExecutor(max_workers=count) as pool:results=list(pool.map(claim,range(16)))
            self.assertEqual(sum(isinstance(r,Permit) for r in results),3)
    def test_get_admission_is_one_committed_transaction_before_transport(self):
        def transport(method,url,**kwargs):
            self.assertEqual(self.db.active,0)
            self.assertEqual(self.db.connection_calls,1)
            self.assertEqual([r['state'] for r in self.db.admissions.values()],['sent'])
            self.calls.append((method,url));return {'status':200,'headers':{},'body':{'id':B}}
        self.p.transport=transport;self.p._bot('GET',self.path)
        self.assertEqual(self.db.connection_calls,2)  # atomic admission, then observation
        self.assertEqual([r['state'] for r in self.db.admissions.values()],['observed'])
        self.assertEqual(len(self.calls),1)

    def test_atomic_read_admission_rejects_mutation_and_reuse(self):
        with self.assertRaises(RateCoordinatorUnavailable):self.s.reserve_read('POST','/channels/'+A+'/messages',identity=self.identity)
        self.assertFalse(self.db.admissions)
        permit=self.s.reserve_read('GET',self.path,identity=self.identity)
        with self.assertRaises(RateCoordinatorUnavailable):self.s.consume(permit,'GET',self.path)
        self.s.note_transport_failure(permit);self.db.now+=3
        with self.assertRaises(RateDelayed):self.s.reserve_read('GET','/channels/'+A,identity=self.identity)

    def test_atomic_read_late_insert_rolls_back_all_debits_before_transport(self):
        self.db.insert_delay=2
        with self.assertRaises(RateDelayed):self.p._bot('GET',self.path)
        self.assertFalse(self.db.admissions or self.db.maps or self.db.states or self.calls)

    def test_cold_resource_probes_are_independent_but_same_major_aliases_serialize(self):
        first=self.reserve()
        second=self.reserve('/channels/'+B+'/messages/'+A)
        self.assertNotEqual(first.id,second.id)
        with self.assertRaises(RateDelayed):self.reserve('/channels/'+A)
        self.assertFalse(self.calls)

    def test_majorless_cold_routes_share_one_probe(self):
        self.reserve('/users/@me')
        with self.assertRaises(RateDelayed):self.reserve('/oauth2/applications/@me')
        self.assertFalse(self.calls)

    def test_independent_cold_resources_still_share_application_limit(self):
        self.s=SharedPostgresBudget(self.db.connection,APP,policy={**self.policy,'app_capacity':2})
        self.reserve();self.reserve('/channels/'+B+'/messages/'+A)
        with self.assertRaises(RateDelayed) as caught:self.reserve('/channels/333333333333333333/messages/'+A)
        self.assertEqual(caught.exception.rate_scope_kind,'application')

    def test_global_rejection_stops_another_cold_major_permit(self):
        first=self.reserve();other_path='/channels/'+B+'/messages/'+A;second=self.reserve(other_path)
        self.s.consume(first,'GET',self.path)
        self.s.observe(first,{'status':429,'headers':{'X-RateLimit-Scope':'global','Retry-After':'172800.25'},'body':{'global':True}})
        with self.assertRaises((RateDelayed,RateCoordinatorUnavailable)):self.s.consume(second,'GET',other_path)
        with self.assertRaises(RateDelayed):self.reserve('/guilds/333333333333333333')

    def test_ambiguous_cold_probe_keeps_its_major_blocked(self):
        first=self.reserve();self.s.consume(first,'GET',self.path)
        self.s.note_transport_failure(first);self.db.now+=3
        with self.assertRaises(RateDelayed):self.reserve('/channels/'+A)
        self.assertIsInstance(self.reserve('/channels/'+B+'/messages/'+A),Permit)

    def test_route_aliases_share_budget_and_major_resources_stay_separate(self):
        other='/channels/'+A+'/messages'
        self.learn();self.learn(other);self.db.now+=1.1
        self.reserve();self.reserve(other);self.reserve()
        with self.assertRaises(RateDelayed):self.reserve(other)
        self.assertIsInstance(self.reserve('/channels/'+B+'/messages/'+B),Permit)
    def test_global_and_shared_embargo_stop_already_reserved_permits(self):
        for scope in ('global','shared'):
            self.setUp();self.learn();self.db.now+=1.1
            waiting=self.reserve();sent=self.reserve();self.s.consume(sent,'GET',self.path)
            self.s.observe(sent,{'status':429,'headers':{'X-RateLimit-Scope':scope,'Retry-After':'172800.25'},'body':{}})
            with self.assertRaises((RateDelayed,RateCoordinatorUnavailable)):self.s.consume(waiting,'GET',self.path)
            if scope=='shared':
                invalid=next(r for r in self.db.states.values() if r['kind']=='invalid');self.assertEqual(invalid['left'],3)
                other=RequestIdentity.make(APP,'user','other-grant',B)
                with self.assertRaises(RateDelayed):self.s.reserve('GET',self.path,identity=other)
            else:
                with self.assertRaises(RateDelayed) as caught:self.reserve('/channels/'+B+'/messages/'+B)
                self.assertGreaterEqual(caught.exception.retry_after_seconds,172800.25)
    def test_malformed_headers_and_policy_expiry_fail_closed(self):
        self.send({'status':429,'headers':{'Retry-After':'NaN'},'body':{}})
        with self.assertRaises(RateCoordinatorUnavailable):self.reserve()
        for policy in (None,{**self.policy,'expires_at':self.db.now-1},{**self.policy,'app_capacity':True}):
            with self.subTest(policy=policy),self.assertRaises(RateCoordinatorUnavailable):
                SharedPostgresBudget(self.db.connection,APP,policy=policy).reserve('GET',self.path,identity=self.identity)
    def test_reordered_observation_cannot_inflate_budget_or_erase_embargo(self):
        self.learn();self.db.now+=1.1
        early,later=self.reserve(),self.reserve()
        self.s.consume(early,'GET',self.path);self.s.consume(later,'GET',self.path)
        self.s.observe(later,{'status':429,'headers':{'Retry-After':'20','X-RateLimit-Bucket':'learned'},'body':{}})
        self.s.observe(early,{'status':200,'headers':{'X-RateLimit-Bucket':'older','X-RateLimit-Limit':'99','X-RateLimit-Remaining':'99','X-RateLimit-Reset-After':'1'}})
        with self.assertRaises(RateDelayed) as caught:self.reserve()
        self.assertGreaterEqual(caught.exception.retry_after_seconds,20)
        self.assertNotIn(_digest('older'),[r[0] for r in self.db.maps.values()])
    def test_ambiguous_timeout_keeps_spent_slot_and_never_calls_post_twice(self):
        self.learn();self.db.now+=1.1
        p=self.reserve();self.s.consume(p,'GET',self.path);self.s.note_transport_failure(p)
        self.assertEqual(self.db.admissions[p.id]['state'],'uncertain')
        self.db.now+=1.1
        self.reserve();self.reserve()
        with self.assertRaises(RateDelayed):self.reserve()
    def test_bot401_circuit_is_shared_user401_does_not_disable_bot(self):
        self.send({'status':401,'headers':{}})
        replica=SharedPostgresBudget(self.db.connection,APP,policy=self.policy)
        with self.assertRaises(RateCoordinatorUnavailable):replica.reserve('GET','/channels/'+B,identity=self.identity)
        renewed={**self.policy,'revision':'synthetic-renewed','issued_at':self.db.now,'expires_at':self.db.now+3600}
        with self.assertRaises(RateCoordinatorUnavailable):SharedPostgresBudget(self.db.connection,APP,policy=renewed).reserve('GET','/channels/'+B,identity=self.identity)
        fresh=RequestIdentity.make(APP,'bot','explicitly-rotated-synthetic-bot')
        self.assertIsInstance(replica.reserve('GET','/channels/'+B,identity=fresh),Permit)
        self.assertTrue(classify_response({'status':404},'webhook')['webhookInvalid'])
        self.assertFalse(classify_response({'status':429,'headers':{'x-ratelimit-scope':'shared'}})['invalid'])
        self.setUp()
        user=RequestIdentity.make(APP,'user','synthetic-user-grant',A)
        permit=self.s.reserve('GET','/users/@me',identity=user)
        self.s.consume(permit,'GET','/users/@me');self.s.observe(permit,{'status':401,'headers':{}})
        with self.assertRaises(RateCoordinatorUnavailable):self.s.reserve('GET','/oauth2/@me',identity=user)
        self.p._bot('GET',self.path)
        self.assertEqual(len(self.calls),1)
    def test_identity_transport_uses_shared_coordinator_without_storing_secrets(self):
        from postriff_phase2.discord.oauth import DiscordConnections
        connections=DiscordConnections(None)
        with patch.object(DiscordConnections,'adapter',new_callable=PropertyMock,return_value=self.p):
            connections._response('GET','/users/@me','SYNTHETIC-BEARER',user_id=A)
            with self.assertRaises(RateDelayed):connections._response('GET','/users/@me','OTHER-BEARER',user_id=A)
        data=json.dumps([self.db.states,self.db.admissions])
        for secret in ('SYNTHETIC-BEARER','OTHER-BEARER','synthetic-bot',A,APP):self.assertNotIn(secret,data)
        self.assertEqual(len(self.calls),1)
    def test_permit_is_durable_single_use_and_forged_or_expired_permits_fail(self):
        p=self.reserve();self.s.consume(p,'GET',self.path)
        with self.assertRaises(RateCoordinatorUnavailable):self.s.consume(p,'GET',self.path)
        with self.assertRaises(RateCoordinatorUnavailable):self.s.consume(replace(p,path_key=_digest('/channels/'+B)),'GET','/channels/'+B)
        # A sent GET without a response must retain discovery capacity; first
        # record a definite response before testing a fresh permit's expiry.
        self.s.observe(p,{'status':200,'headers':{}})
        self.db.now+=2;p=self.reserve();self.db.now=p.expires_at
        with self.assertRaises(RateDelayed):self.s.consume(p,'GET',self.path)
    def test_message_create_cannot_get_an_implicit_or_unbound_permit(self):
        with self.assertRaises(RateCoordinatorUnavailable):self.p._bot('POST','/channels/'+A+'/messages',body={'content':'synthetic'})
        self.assertEqual(self.calls,[])
    def test_coordinator_outage_prevents_transport_and_response_evidence_survives(self):
        self.p.rate_coordinator_degraded=True
        with self.assertRaises(RateCoordinatorUnavailable):self.p._bot('GET',self.path)
        self.assertFalse(self.calls)
    def test_http_date_retry_uses_database_now_without_epoch_length_delay(self):
        from datetime import datetime,timezone
        from email.utils import format_datetime
        self.response={'status':429,'headers':{'Retry-After':format_datetime(datetime.fromtimestamp(self.db.now+4,timezone.utc),usegmt=True)},'body':{}}
        with self.assertRaises(RateDelayed) as caught:self.p._bot('GET',self.path)
        self.assertEqual(caught.exception.retry_after_seconds,4)
    def test_late429_after_policy_expiry_still_blocks_renewed_replicas(self):
        for scope in ('global','shared'):
            self.setUp();self.learn();self.db.now+=1.1
            permit=self.reserve();self.s.consume(permit,'GET',self.path)
            self.db.now=self.policy['expires_at']+.1
            self.s.observe(permit,{'status':429,'headers':{'X-RateLimit-Scope':scope,'Retry-After':'20'},'body':{}})
            renewed={**self.policy,'revision':'renewed','issued_at':self.db.now-1,'expires_at':self.db.now+3600}
            replica=SharedPostgresBudget(self.db.connection,APP,policy=renewed)
            identity=self.identity if scope=='global' else RequestIdentity.make(APP,'user','late-user',B)
            target=self.path if scope=='shared' else '/channels/'+B+'/messages/'+B
            with self.assertRaises(RateDelayed) as caught:replica.reserve('GET',target,identity=identity)
            self.assertGreaterEqual(caught.exception.retry_after_seconds,20)
    def test_new_bucket_alias_inherits_durable_manual_hold_and_circuit(self):
        for stop in ('manual','circuit'):
            self.setUp();self.learn();self.db.now+=1.1
            first,later=self.reserve(),self.reserve()
            self.s.consume(first,'GET',self.path);self.s.consume(later,'GET',self.path)
            if stop=='manual':
                self.s.observe(first,{'status':200,'headers':{'X-RateLimit-Limit':'NaN'}})
            else:
                self.s.observe(first,{'status':503,'headers':{}})
                old=next(r for r in self.db.states.values() if r['kind']=='route' and r['streak'])
                old['circuit']=self.db.now+60  # fixture models an already open circuit
            self.s.observe(later,{'status':200,'headers':{'X-RateLimit-Bucket':'replacement',
                'X-RateLimit-Limit':'3','X-RateLimit-Remaining':'3','X-RateLimit-Reset-After':'1'}})
            self.db.now+=2
            with self.assertRaises(RateCoordinatorUnavailable if stop=='manual' else RateDelayed):self.reserve()
    def test_alias_failure_is_counted_once_regardless_of_hash_lock_order(self):
        for old_first in (True,False):
            self.setUp();self.policy['failure_threshold']=3
            self.s=SharedPostgresBudget(self.db.connection,APP,policy=self.policy)
            _,major=route_identity('GET',self.path)
            old_key='50:'+_digest(self.identity.auth_key+':'+_digest('initial')+':'+major)
            choices=['replacement-'+str(i) for i in range(100)]
            new_bucket=next(b for b in choices if ((old_key < '50:'+_digest(self.identity.auth_key+':'+_digest(b)+':'+major))==old_first))
            new_key='50:'+_digest(self.identity.auth_key+':'+_digest(new_bucket)+':'+major)
            self.learn(bucket='initial');self.db.now+=1.1
            first,later=self.reserve(),self.reserve()
            for permit in (first,later):self.s.consume(permit,'GET',self.path)
            self.s.observe(first,{'status':503,'headers':{}})
            self.s.observe(later,{'status':503,'headers':{'X-RateLimit-Bucket':new_bucket,
                'X-RateLimit-Limit':'3','X-RateLimit-Remaining':'1','X-RateLimit-Reset-After':'1'}})
            self.assertEqual(self.db.states[new_key]['streak'],2)
            self.assertIsNone(self.db.states[new_key]['circuit'])
            self.db.now+=2
            self.assertIsInstance(self.reserve(),Permit)
    def test_reset_after_is_not_reused_as_a_permanent_window_period(self):
        self.learn();self.db.now+=1.1
        for _ in range(3):self.send()  # fake responses intentionally have no headers
        self.db.now+=5
        with self.assertRaises(RateDelayed):self.reserve()
        # Current request headers can restore a real next deadline, whereas an
        # older response only tightens and cannot release the fresh-hint guard.
        _,major=route_identity('GET',self.path)
        row=self.db.states['50:'+_digest(self.identity.auth_key+':'+_digest('learned')+':'+major)]
        self.assertIsNotNone(row['freshAfter'])
    def test_flag_contract_is_default_off_and_legacy_flag_does_not_activate(self):
        values={'POSTRIFF_OAUTH_DISCORD_CLIENT_ID':APP,'POSTRIFF_OAUTH_DISCORD_CLIENT_SECRET':'valid-synthetic-secret',
            'POSTRIFF_DISCORD_BOT_TOKEN':'valid-synthetic-bot','POSTRIFF_PUBLIC_BASE_URL':'https://rafii.invalid',
            'POSTRIFF_DISCORD_RATE_V1_ENABLED':'true'}
        p,_=DiscordProvider.mount(values);self.assertIsNotNone(p);self.assertFalse(p.rate_v1_enabled)
        values['POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED']='true';values['POSTRIFF_DISCORD_RATE_POLICY']=json.dumps(self.policy)
        p,_=DiscordProvider.mount(values);self.assertTrue(p.rate_v1_enabled)
