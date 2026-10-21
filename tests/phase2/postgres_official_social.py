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

    def test_linkedin_optional_analytics_denial_preserves_verified_member_publication(self):
        from unittest.mock import Mock
        from test_linkedin_publishing_recovery import approved_member_app
        adapter = approved_member_app()
        adapter.approved_scopes = {'r_member_postAnalytics'}
        adapter.exchange = Mock(return_value={'accessToken':'synthetic-token','scopes':['openid','profile','w_member_social'],'expiresIn':3600})
        adapter.identity = Mock(return_value={'providerAccountId':'urn:li:person:ordinary-synthetic','handle':'Synthetic ordinary member','accountType':'member'})
        oauth = OAuthService(service.repository, service.commands, CredentialVault(CredentialVault.generate_key()), {'linkedin':adapter}, adapter.public_origin, clock=lambda:self.now)
        oauth._keep_picture = Mock()
        first = oauth.start(wid, 'fixture-one', 'linkedin', 'publish')
        state = parse_qs(urlsplit(first['authorizeUrl']).query)['state'][0]
        connected = oauth.complete(wid, 'fixture-one', 'linkedin', state, 'code')
        upgrade = oauth.start(wid, 'fixture-one', 'linkedin', 'analytics', {'connectionId':connected['connectionId']})
        requested = set(parse_qs(urlsplit(upgrade['authorizeUrl']).query)['scope'][0].split())
        self.assertEqual(requested, {'openid','profile','w_member_social','r_member_postAnalytics'})
        state = parse_qs(urlsplit(upgrade['authorizeUrl']).query)['state'][0]
        result = oauth.complete(wid, 'fixture-one', 'linkedin', state, 'code')
        self.assertEqual(result['connectionId'], connected['connectionId'])
        self.assertEqual(result['missingScopes'], ['r_member_postAnalytics'])
        self.assertEqual(result['capabilities']['publish']['level'], 'Direct')
        self.assertNotEqual(result['capabilities']['analytics']['level'], 'Direct')
        persisted = service.repository.get(wid,'fixture-one')['state']['phase2']['channels']
        channel = next(c for c in persisted if c['id'] == result['connectionId'])
        self.assertTrue(channel['capabilityVerified'])
        with connection() as db:
            stored = db.execute('SELECT access_ciphertext,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s',(wid,result['connectionId'])).fetchone()
        self.assertNotEqual(stored[0], 'synthetic-token')
        self.assertEqual(set(stored[1]), {'openid','profile','w_member_social'})

    def test_connection_state_failure_rolls_back_credentials_and_capabilities(self):
        from unittest.mock import Mock, patch
        adapter = ThreadsProvider('app', 'secret')
        adapter.exchange = Mock(return_value={'accessToken':'synthetic-atomic','scopes':['threads_basic'],'expiresIn':3600})
        adapter.identity = Mock(return_value={'providerAccountId':'atomic-failure','accountType':'profile'})
        oauth = OAuthService(service.repository,service.commands,CredentialVault(CredentialVault.generate_key()),{'threads':adapter},'https://example.invalid',clock=lambda:self.now)
        begun = oauth.start(wid,'fixture-one','threads','identity')
        state = parse_qs(urlsplit(begun['authorizeUrl']).query)['state'][0]
        with patch.object(service.commands,'upsert_verified_channel',side_effect=AlphaError('Synthetic save failure',500)):
            with self.assertRaises(AlphaError): oauth.complete(wid,'fixture-one','threads',state,'code')
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND provider_account_id='atomic-failure'",(wid,)).fetchone()[0],0)
            self.assertTrue(db.execute('SELECT consumed_at IS NOT NULL FROM public.pr_oauth_transactions WHERE id=%s',(begun['transactionId'],)).fetchone()[0])
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
                with connection() as db: expiry=db.execute('SELECT extract(epoch from expires_at) FROM public.pr_oauth_transactions WHERE id=%s',(begun['transactionId'],)).fetchone()[0]
                oauth.clock=lambda:float(expiry)+1  # Synthetic expiry boundary, never live aging evidence.
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


class ScopedWorkerPersistence(unittest.TestCase):
    """Real SQL fences around one user-selected job; every transport is synthetic."""
    def setUp(self):
        self.now = fixture.clock[0]
        self.state = copy.deepcopy(BASE)
        target = self.state['phase2']['jobs'][0]
        target.update(state='scheduled', attempts=[], checks=0, events=[], leaseOwner=None, leaseUntil=0,
                      cancelRequested=False, nextAt=self.now - 1)
        for key in ('providerReference', 'providerConfirmed', 'verification', 'progress', 'providerAssets',
                    'providerUpload', 'container', 'providerThread', 'nextAction'):
            target.pop(key, None)
        target['approvalDigest'] = digest(target['manifest'])
        self.target = target
        other = copy.deepcopy(target)
        other['id'] = 'unrelated-due-job'
        other['manifest']['expiresAt'] = self.now - 1
        other['approvalDigest'] = digest(other['manifest'])
        self.state['phase2']['jobs'] = [other, target]
        foreign = copy.deepcopy(self.state)
        foreign['workspace']['id'] = fixture.foreign
        with connection() as db:
            self.foreign_before = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (fixture.foreign,)).fetchone()[0]
            db.execute("UPDATE public.pr_memberships SET role='owner',status='active' WHERE user_id=%s AND workspace_id=%s", (fixture.one, wid))
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(foreign), fixture.foreign))
        self.save()

    def tearDown(self):
        with connection() as db:
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(self.foreign_before), fixture.foreign))
            db.execute("UPDATE public.pr_memberships SET role='owner',status='active' WHERE user_id=%s AND workspace_id=%s", (fixture.one, wid))

    def save(self):
        with connection() as db:
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(self.state), wid))

    def saved(self):
        with connection() as db:
            return db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (wid,)).fetchone()[0]

    def worker(self, social, binding=None):
        return PostgresWorker(connection, social=social, clock=lambda: self.now, worker_binding=binding)

    def run_job(self, worker):
        return worker.execute_job(service.repository, wid, 'fixture-one', self.target['id'], self.target['approvalDigest'])

    def test_concurrent_and_repeated_requests_cannot_create_twice_or_touch_other_jobs(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        started, release = Event(), Event()
        calls = []
        class Social:
            def submit(_, manifest):
                calls.append(('create', manifest['idempotencyKey']))
                started.set()
                if not release.wait(10): raise AssertionError('Synthetic concurrent dispatch timed out')
                return {'state':'provider_accepted', 'reference':'urn:li:share:123', 'confirmed':'Synthetic201 receipt'}
            def reconcile(_, manifest, job):
                calls.append(('reconcile', job.get('providerReference')))
                return {'state':'provider_accepted', 'reference':job['providerReference'], 'confirmed':'Known receipt; no restricted read; do not resubmit'}
        before_other = copy.deepcopy(self.state['phase2']['jobs'][0])
        with connection() as db:
            before_foreign = db.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s', (fixture.foreign,)).fetchone()
        social = Social()
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.run_job, self.worker(social))
            try:
                self.assertTrue(started.wait(10))
                self.assertEqual(self.run_job(self.worker(social))['processed'], 0, 'A live lease is never dispatched again')
            finally:
                release.set()
            self.assertEqual(first.result(timeout=10)['processed'], 1)
        self.assertEqual([kind for kind, _ in calls], ['create'])
        self.now += 6  # Synthetic queue eligibility; not provider token-aging evidence.
        self.state = self.saved()
        known = next(j for j in self.state['phase2']['jobs'] if j['id'] == self.target['id'])
        known['state'] = 'scheduled'  # A stale state label cannot erase a known create receipt.
        self.save()
        self.assertEqual(self.run_job(self.worker(social))['processed'], 1)
        self.assertEqual([kind for kind, _ in calls], ['create', 'reconcile'])
        saved = self.saved()
        self.assertEqual(saved['phase2']['jobs'][0], before_other, 'Do not invalidate even an unrelated expired job')
        target = next(j for j in saved['phase2']['jobs'] if j['id'] == self.target['id'])
        self.assertEqual(target['state'], 'provider_accepted')
        self.assertEqual(len(target['attempts']), 1)
        with connection() as db:
            self.assertEqual(db.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s', (fixture.foreign,)).fetchone(), before_foreign)

    def test_not_due_canceled_stale_or_unentitled_job_never_submits(self):
        from unittest.mock import Mock, patch
        original = copy.deepcopy(self.state)
        for condition in ('future', 'canceled', 'stale-content', 'billing'):
            with self.subTest(condition=condition):
                self.state = copy.deepcopy(original)
                target = self.state['phase2']['jobs'][1]
                if condition == 'future': target['nextAt'] = self.now + 600
                if condition == 'canceled': target['cancelRequested'] = True
                if condition == 'stale-content': target['manifest']['expiresAt'] = self.now - 1; target['approvalDigest'] = digest(target['manifest'])
                self.target = target
                self.save()
                social = SimpleNamespace(submit=Mock(side_effect=AssertionError('No create authorized')))
                if condition == 'billing':
                    with patch('postriff_phase2.billing.require_publishing', side_effect=AlphaError('Publishing entitlement unavailable', 402)):
                        self.run_job(self.worker(social))
                else:
                    self.run_job(self.worker(social))
                social.submit.assert_not_called()
                saved = self.saved()['phase2']['jobs']
                self.assertEqual(saved[0], original['phase2']['jobs'][0])
                self.assertEqual(len(saved[1]['attempts']), 0)

    def test_lost_membership_between_request_and_claim_cannot_dispatch(self):
        from unittest.mock import Mock, patch
        social = SimpleNamespace(submit=Mock(side_effect=AssertionError('Revoked member cannot publish')))
        worker = self.worker(social)
        claim = worker.claim
        def revoke_before_claim(**scope):
            with connection() as db:
                db.execute("UPDATE public.pr_memberships SET role='viewer',can_publish=false WHERE workspace_id=%s AND user_id=%s", (wid, fixture.one))
            return claim(**scope)
        with patch.object(worker, 'claim', side_effect=revoke_before_claim), self.assertRaises(AlphaError) as error:
            self.run_job(worker)
        self.assertEqual(error.exception.status, 403)
        social.submit.assert_not_called()
        self.assertEqual(self.saved()['phase2']['jobs'], self.state['phase2']['jobs'])

    def test_preview_hold_is_released_atomically_only_by_matching_scoped_worker(self):
        from unittest.mock import Mock
        preview = {'environment':'preview', 'origin':'https://preview.example.invalid'}
        self.target['manifest']['workerBinding'] = preview
        self.target['approvalDigest'] = digest(self.target['manifest'])
        self.target.update(state='held', previewDispatchPending=True,
                           events=[{'at':self.now, 'state':'held', 'message':'Approved preview post; choose Publish approved post when due.'}])
        # The global worker may touch its own unbound job, but cannot invalidate or claim this preview job.
        self.save()
        before = copy.deepcopy(self.target)
        self.assertIsNone(self.worker(SimpleNamespace()).claim())
        saved = next(j for j in self.saved()['phase2']['jobs'] if j['id'] == self.target['id'])
        self.assertEqual(saved, before)
        wrong = self.worker(SimpleNamespace(), {**preview, 'origin':'https://other.example.invalid'})
        with self.assertRaises(AlphaError) as error:
            self.run_job(wrong)
        self.assertEqual(error.exception.status, 409)
        social = SimpleNamespace(submit=Mock(return_value={'state':'provider_accepted','reference':'urn:li:share:456','confirmed':'Synthetic201 receipt'}))
        worker = self.worker(social, preview)
        self.assertIsNone(worker.claim(), 'A preview hold is not a global-cron release')
        self.assertEqual(self.run_job(worker)['processed'], 1)
        social.submit.assert_called_once_with(before['manifest'])
        saved = next(j for j in self.saved()['phase2']['jobs'] if j['id'] == self.target['id'])
        self.assertEqual(saved['state'], 'provider_accepted')
        self.assertEqual(saved['manifest'], before['manifest'])
        self.assertEqual(saved['approvalDigest'], before['approvalDigest'])
        self.assertNotIn('previewDispatchPending', saved)
        self.assertEqual(len(saved['attempts']), 1)
        self.assertEqual(len(self.saved()['phase2']['jobs']), 2, 'No replacement job is created')

    def test_definitive_legacy_no_submit_recovers_original_job_without_rearming_unknown_outcome(self):
        from unittest.mock import Mock
        preview = {'environment':'preview', 'origin':'https://preview.example.invalid'}
        message = 'Live provider transport is not configured; nothing was submitted'
        self.target.update(state='held', resultSchema='postriff.result.v1', providerConfirmed=message,
                           events=[{'state':'held','at':self.now,'message':message}],
                           attempts=[{'number':1,'startedAt':self.now-10,'endedAt':self.now-9}])
        self.save()
        original = copy.deepcopy(self.state)
        social = SimpleNamespace(submit=Mock(return_value={'state':'provider_accepted','reference':'urn:li:share:789','confirmed':'Synthetic201 receipt'}))
        for change in ({'providerConfirmed':'Provider response unknown'}, {'providerReference':'urn:li:share:777'},
                       {'nextAt':self.now+600}, {'cancelRequested':True}):
            with self.subTest(change=change):
                self.state = copy.deepcopy(original)
                self.target = self.state['phase2']['jobs'][1]
                self.target.update(change)
                self.save()
                try:
                    self.run_job(self.worker(social, preview))
                except AlphaError as error:
                    self.assertEqual(error.status, 409)
                social.submit.assert_not_called()
                self.assertEqual(self.saved()['phase2']['jobs'], self.state['phase2']['jobs'])
        self.state = copy.deepcopy(original)
        self.target = self.state['phase2']['jobs'][1]
        self.save()
        before = copy.deepcopy(self.target)
        self.assertEqual(self.run_job(self.worker(social, preview))['processed'], 1)
        social.submit.assert_called_once_with(before['manifest'])
        saved = self.saved()['phase2']['jobs']
        self.assertEqual(saved[0], original['phase2']['jobs'][0])
        self.assertEqual(saved[1]['manifest'], before['manifest'])
        self.assertEqual(saved[1]['approvalDigest'], before['approvalDigest'])
        self.assertEqual(saved[1]['workerBinding'], preview)
        self.assertEqual(saved[1]['attempts'][0], before['attempts'][0])
        self.assertEqual(len(saved[1]['attempts']), 2, 'Original definitive no-submit attempt remains in history')
        self.assertEqual(saved[1]['state'], 'provider_accepted')
        self.assertEqual(len(saved), 2)


if __name__=='__main__': unittest.main()
