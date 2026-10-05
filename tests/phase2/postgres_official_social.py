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
