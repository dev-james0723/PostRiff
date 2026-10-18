"""Private Trial containment only. All accounts/resources and provider traffic are synthetic."""
import copy
import json
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from types import SimpleNamespace
from postriff_alpha.domain import AlphaError
from postriff_phase2.pinterest_pilot import PinterestExecutionTrialPolicy, PinterestTrialPolicy
from postriff_phase2.pinterest_quota import PinterestQuota
from postriff_phase2.providers import registry_from_environment
from postriff_phase2.oauth import OAuthService
from postriff_phase2.wave3_connectors import PinterestProvider
from test_hosted_wave1_connectors import Wire, ok

W='00000000-0000-0000-0000-000000000501'
A='00000000-0000-0000-0000-000000000502'
I='00000000-0000-0000-0000-000000000503'
ACCOUNT,BOARD,PIN='7654321','1234567','9876543'
CAPS='identity,boards_read,publish,schedule,analytics'


def values():
    return {'POSTRIFF_OAUTH_PINTEREST_CLIENT_ID':'1615884','POSTRIFF_OAUTH_PINTEREST_CLIENT_SECRET':'MOCK',
            'POSTRIFF_PINTEREST_SANDBOX':'false','POSTRIFF_PINTEREST_PRIVATE_TRIAL':'1',
            'POSTRIFF_PINTEREST_TRIAL_API_ENVIRONMENT':'production','POSTRIFF_PINTEREST_ANALYTICS_ENABLED':'1',
            'POSTRIFF_PINTEREST_TRIAL_WORKSPACE_ID':W,'POSTRIFF_PINTEREST_TRIAL_ACTOR_ID':A,
            'POSTRIFF_PINTEREST_TRIAL_USERNAME':'mock','POSTRIFF_PINTEREST_TRIAL_ACCOUNT_ID':ACCOUNT,
            'POSTRIFF_PINTEREST_TRIAL_BOARD_IDS':BOARD,'POSTRIFF_PINTEREST_TRIAL_CAPABILITIES':CAPS,
            'POSTRIFF_PINTEREST_TRIAL_ID':I,'POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT':str(int(time.time())+3600)}


def fixture(responses=()):
    registry=registry_from_environment(values(),transport=Wire(responses));p=registry['pinterest']
    p.rate_gate=lambda *args:None
    p.private_trial_pin_gate=lambda pin:pin==PIN
    p.private_trial_create_gate=lambda *args:None
    p.private_trial_ack_gate=lambda *args:None
    p.private_trial_media_gate=lambda m,url:url=='https://example.com/synthetic.png'
    token=p._grant({'access_token':'MOCK','scope':'user_accounts:read boards:read pins:read pins:write'})['accessToken']
    token=json.dumps(json.loads(token)|{'accountId':ACCOUNT})
    return registry,p,token


def manifest():
    return {'workspaceId':W,'actor':A,'providerAccountId':ACCOUNT,'platform':'Pinterest','channelId':'connection',
            'idempotencyKey':'synthetic-intent','payload':{'text':'Synthetic approved description'},
            'media':[{'id':'synthetic-asset','alt':'Synthetic image'}],
            'timing':{'timestamp':time.time()+120},'publishOptions':{'boardId':BOARD,'title':'Title','link':'https://example.com/'}}


def pin(m):
    return {'board_id':BOARD,'description':m['payload']['text'],'title':'Title','link':'https://example.com/','alt_text':'Synthetic image',
            'media_source':{'source_type':'image_url','url':'https://example.com/synthetic.png'}}


class BudgetDB:
    """Transaction-aware synthetic fixture; real concurrency/constraints live in disposable PG."""
    def __init__(self):
        self.saved={};self.pending={};self.journal={};self.pending_journal={};self.commits=0;self.schema=True
    @contextmanager
    def factory(self):
        self.pending=copy.deepcopy(self.saved);self.pending_journal=copy.deepcopy(self.journal)
        try:
            yield self
        except Exception:raise
        else:
            self.saved=self.pending;self.journal=self.pending_journal;self.commits+=1
    @contextmanager
    def cursor(self):yield self
    def execute(self,sql,args):
        if 'pr_pinterest_trial_intents' in sql:
            if not self.schema:raise RuntimeError('Synthetic journal schema unavailable')
            if sql.startswith('INSERT'):
                authority,intent,expiry=args;lookup=(authority,intent)
                if lookup in self.pending_journal:raise RuntimeError('Synthetic duplicate prepared row')
                self.pending_journal[lookup]={'pin':None,'expiry':expiry};self.result=None
            elif sql.startswith('UPDATE'):
                pin_id,authority,intent,expiry,expected=args;row=self.pending_journal.get((authority,intent))
                self.result=None
                if row and row['expiry']==expiry and row['pin'] in (None,expected):
                    row['pin']=pin_id;self.result=(pin_id,)
            elif sql.startswith('SELECT'):
                authority,intent,expiry=args;row=self.pending_journal.get((authority,intent))
                self.result=(row['pin'],row['expiry']>time.time()) if row and row['expiry']==expiry else None
            else:raise AssertionError('Unexpected synthetic journal SQL')
        else:
            key,window,limit=args;lookup=(key,window);prior=self.pending.get(lookup,0)
            self.result=(prior+1,) if prior<limit else None
            if self.result:self.pending[lookup]=prior+1
    def fetchone(self):return self.result


class PrivateTrial(unittest.TestCase):
    def test_all_four_capabilities_private_and_public_review_stays_false(self):
        registry,p,t=fixture()
        service=OAuthService.__new__(OAuthService);service.providers=registry;service.vault=SimpleNamespace(fernet=True)
        service.public_base_url='https://rafii.test';service.youtube_public_base_url=None
        entry=next(e for e in service.provider_catalog() if e['id']=='pinterest')
        self.assertTrue(entry['connectReady']);self.assertTrue(entry['privateTrial'])
        self.assertFalse(entry['publicConnectionReady']);self.assertFalse(entry['productionReviewed'])
        self.assertFalse(entry['readinessChecklist']['productionEnabled'])
        for cap in ('publish','schedule','analytics'):self.assertTrue(p.capability_scopes(cap))
        matrix=service._capabilities(p,'publish',list(p.publish_required),[],time.time())
        for cap in ('publish','schedule','analytics'):self.assertEqual(matrix[cap]['level'],'Direct')
        self.assertIn('Private',matrix['publish']['evidence'])
        self.assertEqual(set(entry['readinessChecklist']['requestedScopes']),set(p.publish_required))

    def test_analytics_internal_scope_formats_preserve_trial_ceiling(self):
        _, provider, token = fixture()
        approved = ['user_accounts:read', 'boards:read', 'pins:read']
        for collection in (list, tuple, set, frozenset):
            with self.subTest(collection=collection.__name__):
                scopes = collection(approved)
                provider.assert_trial_context(W, A, scopes=scopes)
                provider.trial_policy.require_scopes(scopes)
                PinterestTrialPolicy.require_scopes(collection(approved[:2]))
                with self.assertRaises(AlphaError):
                    PinterestTrialPolicy.require_scopes(scopes)  # read-only must still deny Pin scopes
                with self.assertRaises(AlphaError):
                    provider.trial_policy.require_scopes(collection(approved + ['boards:write']))
        for malformed in (None, [], (), '', 'user_accounts:read,boards:read,pins:read',
                          {'user_accounts:read': True}, [None], [True], [123], [''],
                          ('pins:write', 'ads:read')):
            with self.subTest(malformed=repr(malformed)):
                with self.assertRaises(AlphaError):
                    provider.trial_policy.require_scopes(malformed)
        self.assertEqual(provider.transport.calls, [])  # no provider action from scope normalization

    def test_policy_identity_board_expiry_and_time_never_broaden_authority(self):
        _,p,t=fixture();m=manifest();p.trial_policy.require_manifest(m)
        for key,value in [('workspaceId','other'),('actor','other'),('actor',None),('providerAccountId','9999999')]:
            with self.subTest(key=key),self.assertRaises(AlphaError):p.trial_policy.require_manifest(m|{key:value})
        for at in (None,float('nan'),True,p.trial_policy.expires_at):
            with self.subTest(at=at),self.assertRaises(AlphaError):p.trial_policy.require_manifest(m|{'timing':{'timestamp':at}})
        with self.assertRaises(AlphaError):p.trial_policy.require_manifest(m|{'publishOptions':{'boardId':'9999999'}})
        with self.assertRaises(AlphaError):p.trial_policy.require_identity({'handle':'@mock','providerAccountId':'9999999'})
        with self.assertRaises(AlphaError):p.trial_policy.require_scopes(['boards:write'])
        for extra in ({'POSTRIFF_PINTEREST_TRIAL_READONLY':'1'},{'POSTRIFF_PINTEREST_TRIAL_ACCOUNT_ID':'*'},
                      {'POSTRIFF_PINTEREST_TRIAL_BOARD_IDS':BOARD+',*'},{'POSTRIFF_PINTEREST_TRIAL_BOARD_IDS':None},{'POSTRIFF_PINTEREST_TRIAL_CAPABILITIES':None},{'POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT':str(int(time.time())-1)},
                      {'POSTRIFF_OAUTH_PINTEREST_CLIENT_ID':'9999999'},
                      {'POSTRIFF_PINTEREST_TRIAL_CAPABILITIES':'identity,boards_read,publish'},
                      {'POSTRIFF_PINTEREST_TRIAL_CAPABILITIES':'identity,boards_read,schedule'}):
            self.assertNotIn('pinterest',registry_from_environment(values()|extra,transport=Wire([])))
        self.assertEqual(p.transport.calls,[])

    def test_transport_requires_exact_fenced_body_and_recorded_pin(self):
        _,p,t=fixture([ok({'id':PIN},201),ok({'id':PIN})]);m=manifest();body=pin(m)
        with self.assertRaises(AlphaError):p.api(t,'POST','/v5/pins',body=body)
        with p.private_trial_dispatch(m,body):
            with self.assertRaises(AlphaError):p.api(t,'POST','/v5/pins',body=body|{'title':'Changed'})
            self.assertEqual(p.api(t,'POST','/v5/pins',body=body)['status'],201)
        with self.assertRaises(AlphaError):p.api(t,'POST','/v5/pins',body=body)
        unbound=json.loads(t);unbound.pop('accountId')
        with self.assertRaises(AlphaError):p.api(json.dumps(unbound),'GET','/v5/boards')
        with self.assertRaises(AlphaError):p.api(t,'GET','/v5/pins/1111111/analytics')
        with self.assertRaises(AlphaError):p.api(t,'DELETE','/v5/pins/'+PIN)
        with self.assertRaises(AlphaError):p.api(t,'POST','/v5/boards',body={'name':'not approved'})
        with self.assertRaises(AlphaError):p.api(t,'POST','/v5/oauth/token',form={'grant_type':'refresh_token'})
        self.assertEqual(p.api(t,'GET','/v5/pins/'+PIN)['status'],200)
        self.assertEqual(len(p.transport.calls),2)

    def test_context_entry_rejects_changed_section_alt_source_and_unreviewed_fields(self):
        _,p,t=fixture();m=manifest();body=pin(m)
        changed_bodies=[body|{'board_section_id':'1111111'},body|{'alt_text':'Changed'},
            body|{'media_source':{'source_type':'image_url','url':'https://example.com/other.png'}},
            body|{'media_source':{'source_type':'image_base64','url':'https://example.com/synthetic.png'}},
            body|{'unreviewed_field':'extra'}]
        for changed in changed_bodies:
            with self.subTest(changed=changed),self.assertRaises(AlphaError):
                with p.private_trial_dispatch(m,changed):
                    raise AssertionError('Unreviewed Pin body entered the provider dispatch context')
        self.assertEqual(p.transport.calls,[])

    def test_tokens_cannot_cross_pilot_configuration_or_public_mode(self):
        _,p,t=fixture();raw=json.loads(t)
        with self.assertRaises(AlphaError):p.bearer(json.dumps(raw|{'accountId':'9999999'}))
        p.private_trial=False
        with self.assertRaises(AlphaError):p.bearer(t)
        p.private_trial=True;v=values();v['POSTRIFF_PINTEREST_TRIAL_ID']='00000000-0000-0000-0000-000000000504'
        p.trial_policy=PinterestExecutionTrialPolicy.from_environment(v)
        with self.assertRaises(AlphaError):p.bearer(t)
        self.assertEqual(p.transport.calls,[])

    def test_independent_durable_reservations_survive_unknown_outcome_and_reconnect(self):
        _,p,t=fixture();db=BudgetDB();q=PinterestQuota(db.factory,'1615884','production',trial=True)
        q.reserve_trial_create(p.trial_policy,'immediate')
        with self.assertRaises(AlphaError) as used:q.reserve_trial_create(p.trial_policy,'immediate')
        self.assertEqual(used.exception.code,'pinterest_trial_intent_consumed')
        q2=PinterestQuota(db.factory,'1615884','production',trial=True)
        q2.reserve_trial_create(p.trial_policy,'scheduled')
        with self.assertRaises(AlphaError):q2.reserve_trial_create(p.trial_policy,'third')
        self.assertEqual(db.commits,2)
        self.assertEqual(sorted(db.saved.values()),[1,1,2])
        self.assertEqual(len(db.journal),2);self.assertTrue(all(row['pin'] is None for row in db.journal.values()))

    def test_known_response_journal_recovers_same_id_and_never_overwrites_or_creates(self):
        _,p,t=fixture();db=BudgetDB();q=PinterestQuota(db.factory,'1615884','production',trial=True)
        self.assertIsNone(q.recovered_trial_pin(p.trial_policy,'immediate'))
        with self.assertRaises(AlphaError) as missing:q.acknowledge_trial_create(p.trial_policy,'missing',PIN)
        self.assertEqual(missing.exception.code,'pinterest_trial_journal_conflict')
        q.reserve_trial_create(p.trial_policy,'immediate')
        self.assertIsNone(q.recovered_trial_pin(p.trial_policy,'immediate'))
        self.assertEqual(q.acknowledge_trial_create(p.trial_policy,'immediate',PIN),PIN)
        self.assertEqual(q.acknowledge_trial_create(p.trial_policy,'immediate',PIN),PIN)
        q2=PinterestQuota(db.factory,'1615884','production',trial=True)
        self.assertEqual(q2.recovered_trial_pin(p.trial_policy,'immediate'),PIN)
        with self.assertRaises(AlphaError) as changed:q2.acknowledge_trial_create(p.trial_policy,'immediate','1111111')
        self.assertEqual(changed.exception.code,'pinterest_trial_journal_conflict')
        self.assertEqual(q2.recovered_trial_pin(p.trial_policy,'immediate'),PIN)
        self.assertIsNone(PinterestQuota(db.factory,'1615884','sandbox',trial=True).recovered_trial_pin(p.trial_policy,'immediate'))
        with self.assertRaises(AlphaError) as invalid:q.acknowledge_trial_create(p.trial_policy,'immediate','../PRIVATE')
        self.assertEqual(invalid.exception.code,'pinterest_trial_journal_invalid')
        self.assertNotIn('PRIVATE',str(invalid.exception))

    def test_known_response_can_be_recorded_after_expiry_without_granting_recovery_authority(self):
        _,p,t=fixture();db=BudgetDB();q=PinterestQuota(db.factory,'1615884','production',trial=True)
        q.reserve_trial_create(p.trial_policy,'late-response')
        before=copy.deepcopy(db.saved)
        with patch('postriff_phase2.pinterest_pilot.time.time',return_value=p.trial_policy.expires_at+1):
            self.assertEqual(q.acknowledge_trial_create(p.trial_policy,'late-response',PIN),PIN)
            with self.assertRaises(AlphaError) as expired:q.recovered_trial_pin(p.trial_policy,'late-response')
            self.assertEqual(expired.exception.code,'pinterest_trial_denied')
            with self.assertRaises(AlphaError):q.reserve_trial_create(p.trial_policy,'late-response')
        self.assertEqual(db.saved,before)
        self.assertEqual(q.recovered_trial_pin(p.trial_policy,'late-response'),PIN)

    def test_missing_journal_rolls_back_reservations_and_fails_closed_for_response_operations(self):
        _,p,t=fixture();db=BudgetDB();db.schema=False;q=PinterestQuota(db.factory,'1615884','production',trial=True)
        for operation in (lambda:q.reserve_trial_create(p.trial_policy,'missing-schema'),
                          lambda:q.acknowledge_trial_create(p.trial_policy,'missing-schema',PIN),
                          lambda:q.recovered_trial_pin(p.trial_policy,'missing-schema')):
            with self.assertRaises(AlphaError) as missing:operation()
            self.assertEqual((missing.exception.status,missing.exception.code),(503,'pinterest_quota_unavailable'))
        self.assertEqual(db.saved,{})
        self.assertEqual(db.journal,{})
        self.assertEqual(db.commits,0)

    def test_pin_read_guard_requires_current_pilot_recorded_job_and_account(self):
        _,p,t=fixture();m=manifest();job={'manifest':m,'providerReference':PIN,'pinterestTrialPilot':I,'state':'verified'}
        state={'phase2':{'channels':[{'id':'connection','providerAccountId':ACCOUNT,'revoked':False}],'jobs':[job]}}
        class Repo:
            @contextmanager
            def connection_factory(self):yield self
            @contextmanager
            def cursor(self):yield self
            def execute(self,sql,args):self.args=args
            def fetchone(self):return (state,)
        service=OAuthService.__new__(OAuthService);service.providers={'pinterest':p};service.repository=Repo();service.clock=time.time
        self.assertTrue(service._pinterest_private_pin_allowed(PIN));self.assertFalse(service._pinterest_private_pin_allowed('1111111'))
        self.assertEqual(service.repository.args,(W,))
        for key,value in [('pinterestTrialPilot','other'),('state','canceled')]:
            old=job[key];job[key]=value
            self.assertFalse(service._pinterest_private_pin_allowed(PIN));job[key]=old
        state['phase2']['channels'][0]['revoked']=True
        self.assertFalse(service._pinterest_private_pin_allowed(PIN))
