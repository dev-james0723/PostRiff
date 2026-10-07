"""Real disposable PostgreSQL transactions; synthetic providers; never live qualification."""
import copy
import json
import unittest
from types import SimpleNamespace
from postriff_alpha.domain import AlphaError
from postriff_phase2.official_operations import SocialActionsService
from urllib.parse import parse_qs, urlsplit
import postgres_repository as fixture
from postriff_phase2.oauth import OAuthService, CredentialVault
from postriff_phase2.providers import ThreadsProvider
from postriff_phase2.contracts import digest
from postriff_phase2.hosted_worker import PostgresWorker

connection, wid, service = fixture.connection, fixture.wid, fixture.service
with connection() as db:
    BASE = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]


class OfficialPersistence(unittest.TestCase):
    def setUp(self):
        self.now=fixture.clock[0];self.state=copy.deepcopy(BASE)
        with connection() as db:
            db.execute("UPDATE public.pr_memberships SET status='active',role='owner' WHERE user_id=%s",(fixture.one,))
            db.execute('DELETE FROM public.pr_oauth_transactions WHERE workspace_id=%s',(wid,))
        self.save()
    def save(self):
        with connection() as db: db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(self.state),wid))
    def test_progressive_oauth_retains_only_explicit_enabled_groups(self):
        channel=self.state['phase2']['channels'][0]
        channel.update(platform='Threads',providerAccountId='123',scopes=['threads_basic','threads_content_publish'],enabledPermissionGroups=['identity','publish'])
        self.save()
        oauth=OAuthService(service.repository,service.commands,CredentialVault(CredentialVault.generate_key()),{'threads':ThreadsProvider('app','secret')},'https://example.invalid',clock=lambda:self.now)
        begun=oauth.start(wid,'fixture-one','threads','analytics',{'connectionId':channel['id']})
        granted=set(parse_qs(urlsplit(begun['authorizeUrl']).query)['scope'][0].split(','))
        self.assertEqual(granted,{'threads_basic','threads_content_publish','threads_manage_insights'})
        self.assertNotIn('threads_manage_replies',granted)
        with connection() as db:
            saved=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]
        requests=saved['phase2']['oauthFeatureRequests'];intent=list(requests.values())[-1]
        self.assertEqual(intent['expectedAccountId'],'123');self.assertEqual(intent['groups'],['analytics','identity','publish'])
        # A genuinely initial identity connect remains least privilege, even if
        # another connection has write access in this workspace.
        initial=oauth.start(wid,'fixture-one','threads','identity')
        self.assertEqual(parse_qs(urlsplit(initial['authorizeUrl']).query)['scope'][0],'threads_basic')
    def test_failed_exchange_is_single_use_and_foreign_user_cannot_claim(self):
        from unittest.mock import Mock
        adapter = ThreadsProvider('app', 'secret')
        adapter.exchange = Mock(side_effect=AlphaError('Exchange outcome unknown', 503))
        oauth = OAuthService(service.repository, service.commands, CredentialVault(CredentialVault.generate_key()), {'threads': adapter}, 'https://example.invalid', clock=lambda: self.now)
        begun = oauth.start(wid, 'fixture-one', 'threads', 'identity')
        state = parse_qs(urlsplit(begun['authorizeUrl']).query)['state'][0]
        self.assertEqual(oauth.completion_context('fixture-one', 'threads', state)['workspaceId'], wid)
        with self.assertRaises(AlphaError): oauth.completion_context('fixture-two', 'threads', state)
        with self.assertRaises(AlphaError):
            oauth.complete(wid, 'fixture-two', 'threads', state, 'code')
        adapter.exchange.assert_not_called()
        with self.assertRaises(AlphaError):
            oauth.complete(wid, 'fixture-one', 'threads', state, 'code')
        with self.assertRaises(AlphaError):
            oauth.complete(wid, 'fixture-one', 'threads', state, 'code')
        self.assertEqual(adapter.exchange.call_count, 1)
        with connection() as db:
            row = db.execute('SELECT consumed_at IS NOT NULL,outcome FROM public.pr_oauth_transactions WHERE id=%s', (begun['transactionId'],)).fetchone()
        self.assertEqual(row, (True, None))

    def test_x_onboarding_reservation_survives_outer_rollback_and_has_shared_cap(self):
        from postriff_phase2.social_budget import XRequestBudget
        from postriff_phase2.social_connectors import XProvider
        adapter = XProvider('app', 'secret')
        adapter.onboarding_budget_policy = {'appId':'app','purpose':'connection_identity','currency':'USD','approvalRef':'synthetic-only','limitMicros':20,'appLimitMicros':30,'perRequestMicros':10,'expiresAt':self.now+600,'allowedEndpoints':['GET /2/users/me']}
        oauth = OAuthService(service.repository, service.commands, CredentialVault(CredentialVault.generate_key()), {'x':adapter}, 'https://example.invalid', clock=lambda:self.now)
        with self.assertRaises(AlphaError):
            with service.repository.transaction('fixture-one', wid) as (cur, _, _):
                XRequestBudget(oauth,wid,'oauth',cursor=cur).reserve('GET','/2/users/me')
                raise AlphaError('Synthetic provider timeout',503)
        XRequestBudget(oauth,wid,'oauth').reserve('GET','/2/users/me')
        with self.assertRaises(AlphaError): XRequestBudget(oauth,wid,'oauth').reserve('GET','/2/users/me')
        XRequestBudget(oauth,fixture.foreign,'oauth').reserve('GET','/2/users/me')
        with self.assertRaises(AlphaError): XRequestBudget(oauth,fixture.foreign,'oauth').reserve('GET','/2/users/me')
        with self.assertRaises(AlphaError): XRequestBudget(oauth,fixture.foreign,'oauth').reserve('POST','/2/tweets')

    def test_partial_consent_persists_basic_identity_without_publishing(self):
        from unittest.mock import Mock
        adapter = ThreadsProvider('app', 'secret')
        adapter.exchange = Mock(return_value={'accessToken':'synthetic-token','scopes':['threads_basic'],'expiresIn':3600})
        adapter.identity = Mock(return_value={'providerAccountId':'ordinary-synthetic','handle':'Synthetic ordinary account','accountType':'profile'})
        oauth = OAuthService(service.repository, service.commands, CredentialVault(CredentialVault.generate_key()), {'threads':adapter}, 'https://example.invalid', clock=lambda:self.now)
        oauth._keep_picture = Mock()
        begun = oauth.start(wid,'fixture-one','threads','publish')
        state = parse_qs(urlsplit(begun['authorizeUrl']).query)['state'][0]
        result = oauth.complete(wid,'fixture-one','threads',state,'code')
        self.assertTrue(result['connected'])
        self.assertEqual(result['missingScopes'], ['threads_content_publish'])
        self.assertNotEqual(result['capabilities']['publish']['level'], 'Direct')
        persisted = service.repository.get(wid,'fixture-one')['state']['phase2']['channels']
        channel = next(c for c in persisted if c['id'] == result['connectionId'])
        self.assertEqual(channel['scopes'], ['threads_basic'])
        with connection() as db:
            stored = db.execute('SELECT access_ciphertext,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',(wid,result['connectionId'])).fetchone()
        self.assertNotEqual(stored[0],'synthetic-token')
        self.assertEqual(stored[1], ['threads_basic'])
        with self.assertRaises(AlphaError): oauth.complete(fixture.foreign,'fixture-two','threads',state,'code')
        with self.assertRaises(AlphaError): oauth.complete(wid,'fixture-one','threads',state,'code')
        self.assertEqual(adapter.exchange.call_count,1)

    def test_denied_and_expired_requests_never_exchange(self):
        from unittest.mock import Mock
        adapter = ThreadsProvider('app','secret'); adapter.exchange = Mock()
        oauth = OAuthService(service.repository,service.commands,CredentialVault(CredentialVault.generate_key()),{'threads':adapter},'https://example.invalid',clock=lambda:self.now)
        for expired in (False,True):
            begun=oauth.start(wid,'fixture-one','threads','identity')
            state=parse_qs(urlsplit(begun['authorizeUrl']).query)['state'][0]
            if expired:
                with connection() as db: db.execute("UPDATE public.pr_oauth_transactions SET expires_at=now()-interval '1 hour' WHERE id=%s",(begun['transactionId'],))
                with self.assertRaises(AlphaError): oauth.complete(wid,'fixture-one','threads',state,'code')
            else:
                self.assertFalse(oauth.complete(wid,'fixture-one','threads',state,None,'access_denied')['connected'])
        adapter.exchange.assert_not_called()

    def test_processing_forward_intent_survives_crash_without_duplicate(self):
        j=self.state['phase2']['jobs'][0];m=j['manifest'];j.update(state='processing',progress={'version':1,'stage':'thread_ready'},providerThread=['123456'],container='123456',cancelRequested=False,leaseUntil=0,leaseOwner=None,nextAt=0,checks=0)
        j['approvalDigest']=digest(m);self.save()
        class Social:
            forwards=0
            def official_enabled(self,*args): return True
            def advance_official(self,*args): self.forwards+=1;return {'state':'processing','container':'123456','providerThread':['123456','234567'],'progress':{'version':1,'stage':'thread_ready'},'confirmed':'Synthetic child'}
            def reconcile(self,*args):return {'state':'uncertain','confirmed':'Interrupted native thread; never create again'}
        social=Social();worker=PostgresWorker(connection,social,clock=lambda:self.now)
        worker.step(crash='after_provider');self.now+=46
        worker=PostgresWorker(connection,social,clock=lambda:self.now);worker.step()
        with connection() as db: saved=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]['phase2']['jobs'][0]
        self.assertEqual(social.forwards,1);self.assertEqual(saved['state'],'uncertain')
    def test_exact_native_reply_intent_is_durable_and_cannot_be_sent_twice(self):
        channel=self.state['phase2']['channels'][0]
        channel.update(platform='Instagram',providerAccountId='1789',evidenceSource='live_provider',scopes=['instagram_business_basic','instagram_business_manage_comments'])
        self.save();calls=[]
        def transport(*args,**kwargs):
            calls.append(args);raise TimeoutError('Synthetic ambiguous submission')
        adapter=SimpleNamespace(id='instagram',production_reviewed=True,official_social_enabled=True,identity=lambda _: {'providerAccountId':'1789'},transport=transport)
        grant={'accessToken':'synthetic','scopes':channel['scopes']}
        oauth=SimpleNamespace(repository=service.repository,clock=lambda:self.now,_member_grant=lambda *_:(adapter,grant))
        actions=SocialActionsService(oauth)
        preview=actions.preview(wid,'fixture-one',channel['id'],'reply','comment-7',{'text':'Approved exact reply'})
        self.assertEqual(actions.approve(wid,'fixture-one',preview['id'],preview['digest'],True)['executionState'],'uncertain')
        with self.assertRaises(AlphaError): actions.approve(wid,'fixture-one',preview['id'],preview['digest'],True)
        self.assertEqual(len(calls),1)
        with connection() as db: saved=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]['phase2']['nativeSocialActions'][-1]
        self.assertEqual(saved['manifest']['payload']['text'],'Approved exact reply');self.assertEqual(saved['state'],'uncertain')


if __name__=='__main__': unittest.main()
