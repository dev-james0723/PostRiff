"""Real disposable credential transactions; synthetic LinkedIn, no live access."""
import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import postgres_repository as fixture
from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted import PostgresWorkspaceRepository
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.official_operations import SocialActionsService
from test_linkedin_publishing_recovery import approved_member_app

BASE = fixture.service.repository.get(fixture.wid, 'fixture-one')['state']


class LinkedInCustodySQL(unittest.TestCase):
    def setUp(self):
        self.now = fixture.clock[0]
        self.state = copy.deepcopy(BASE)
        self.channel = self.state['phase2']['channels'][0]['id']
        self.vault = CredentialVault(CredentialVault.generate_key())
        self.provider = approved_member_app()
        self.calls = []
        self.refresh_body = {'access_token': 'synthetic-refreshed', 'expires_in': 1234}
        self.refresh_status = 200
        self.introspection = {'active': True, 'client_id': self.provider.client_id, 'scope': 'w_member_social'}
        self.identity_status = 200
        self.identity_subject = self.state['phase2']['channels'][0]['providerAccountId'].rsplit(':', 1)[-1]
        self.during_identity = None
        self.lock = threading.Lock()
        def transport(method, url, **kwargs):
            with self.lock:
                self.calls.append((method, url))
            if url.endswith('/accessToken'):
                return {'status': self.refresh_status, 'body': self.refresh_body, 'headers': {}}
            if url.endswith('/introspectToken'):
                return {'status': 200, 'body': self.introspection, 'headers': {}}
            if url == self.provider.USERINFO:
                self.assertEqual(method, 'GET')
                if self.during_identity:
                    self.during_identity()
                return {'status': self.identity_status, 'headers': {}, 'body': {'sub': self.identity_subject, 'name': 'Synthetic member'}}
            raise AssertionError('Unexpected synthetic endpoint: ' + url)
        self.provider.transport = transport
        self.oauth = OAuthService(fixture.service.repository, fixture.service.commands, self.vault,
                                  {'linkedin': self.provider}, self.provider.public_origin, clock=lambda: self.now)
        self.access, key = self.vault.encrypt('synthetic-old-access')
        refresh, _ = self.vault.encrypt('synthetic-original-refresh')
        job = self.state['phase2']['jobs'][0]
        for field in ('providerReference', 'container', 'progress', 'providerUpload', 'providerAssets', 'providerThread', 'verification', 'url', 'providerConfirmed', 'checks', 'nextAction'):
            job.pop(field, None)  # The prototype contains reconciled fixture receipts; this is a fresh unsent approval.
        manifest = job['manifest']
        manifest['expiresAt'] = self.now + 3600
        job.update(state='approved', nextAt=self.now - 1, leaseUntil=0, leaseOwner=None,
                   approvalDigest=digest(manifest), attempts=[], events=[])
        with fixture.connection() as db:
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(self.state), fixture.wid))
            db.execute('''INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,
                access_ciphertext,refresh_ciphertext,key_id,scopes,access_expires_at,refresh_supported)
                VALUES(%s,%s,'linkedin',%s,%s,%s,%s,%s,to_timestamp(%s),true)
                ON CONFLICT(workspace_id,connection_id) DO UPDATE SET access_ciphertext=excluded.access_ciphertext,
                refresh_ciphertext=excluded.refresh_ciphertext,key_id=excluded.key_id,scopes=excluded.scopes,
                access_expires_at=excluded.access_expires_at,refresh_supported=true,revoked_at=NULL''',
                (fixture.wid, self.channel, self.state['phase2']['channels'][0]['providerAccountId'],
                 self.access, refresh, key, ['w_member_social'], self.now + 120))
            db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'publish','Direct') ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level='Direct'", (fixture.wid, self.channel))

    def saved(self):
        with fixture.connection() as db:
            credential = db.execute('''SELECT access_ciphertext,refresh_ciphertext,key_id,
                extract(epoch from access_expires_at)::float8,refresh_supported,revoked_at IS NOT NULL,scopes
                FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s''', (fixture.wid, self.channel)).fetchone()
            state = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (fixture.wid,)).fetchone()[0]
        return credential, state

    def test_concurrent_renewal_rotates_once_and_all_workers_receive_same_grant(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            grants = list(pool.map(lambda _: self.oauth.token_for_worker(fixture.wid, self.channel), range(8)))
        self.assertTrue(all(grant['accessToken'] == 'synthetic-refreshed' for grant in grants))
        self.assertEqual(sum(url.endswith('/accessToken') for _, url in self.calls), 1)
        credential, _ = self.saved()
        self.assertAlmostEqual(credential[3], self.now + 1234, places=5)
        self.assertEqual(self.vault.decrypt(credential[1], credential[2]), 'synthetic-original-refresh')
        self.assertNotIn('synthetic-refreshed', credential[0])

    def test_revoked_refresh_persists_reconnect_and_holds_only_unpublished_work(self):
        self.refresh_body, self.refresh_status = {'error': 'invalid_grant'}, 400
        with self.assertRaises(AlphaError) as raised:
            self.oauth.token_for_worker(fixture.wid, self.channel)
        self.assertEqual(raised.exception.code, 'reauthorization_required')
        credential, state = self.saved()
        self.assertEqual((credential[4], credential[5]), (False, True))
        self.assertTrue(state['phase2']['channels'][0]['revoked'])
        self.assertEqual(state['phase2']['jobs'][0]['state'], 'held')
        self.assertEqual(state['variants'], self.state['variants'])
        self.assertEqual(state['sources'], self.state['sources'])
        self.assertEqual(credential[0], self.access)

    def test_transient_failure_preserves_custody_scopes_and_approvals(self):
        self.refresh_body, self.refresh_status = {}, 503
        with self.assertRaises(AlphaError):
            self.oauth.token_for_worker(fixture.wid, self.channel)
        credential, state = self.saved()
        self.assertEqual((credential[0], credential[4], credential[5], credential[6]),
                         (self.access, True, False, ['w_member_social']))
        self.assertEqual(state, self.state)

    def test_malformed_refresh_cannot_create_a_default_or_nonexpiring_credential(self):
        self.refresh_body = {'access_token': 'synthetic-refreshed'}
        with self.assertRaises(AlphaError):
            self.oauth.token_for_worker(fixture.wid, self.channel)
        credential, _ = self.saved()
        self.assertEqual((credential[0], credential[5]), (self.access, False))
        self.assertAlmostEqual(credential[3], self.now + 120, places=5)

    def test_delayed_revocation_cannot_overwrite_concurrent_reconnection(self):
        replacement, _ = self.vault.encrypt('synthetic-new-consent')
        with fixture.connection() as db:
            db.execute('UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s WHERE workspace_id=%s AND connection_id=%s', (replacement, fixture.wid, self.channel))
        self.assertFalse(self.oauth.mark_linkedin_reauthorization(fixture.wid, self.channel, expected_ciphertext=self.access))
        credential, state = self.saved()
        self.assertEqual((credential[0], credential[5]), (replacement, False))
        self.assertEqual(state, self.state)

    def test_self_serve_expiry_requires_consent_without_attempting_partner_refresh(self):
        with fixture.connection() as db:
            db.execute('UPDATE public.pr_encrypted_credentials SET access_expires_at=to_timestamp(%s),refresh_supported=false,refresh_ciphertext=NULL WHERE workspace_id=%s AND connection_id=%s', (self.now - 1, fixture.wid, self.channel))
        with self.assertRaises(AlphaError) as raised:
            self.oauth.token_for_worker(fixture.wid, self.channel)
        self.assertEqual(raised.exception.code, 'reauthorization_required')
        self.assertEqual(self.calls, [])
        self.assertTrue(self.saved()[0][5])

    def test_unavailable_introspection_keeps_the_last_verified_permission_set(self):
        self.introspection = {}
        with fixture.connection() as db:
            db.execute('UPDATE public.pr_encrypted_credentials SET access_expires_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s', (self.now + 7200, fixture.wid, self.channel))
        with self.assertRaises(AlphaError) as raised:
            self.oauth.token_for_worker(fixture.wid, self.channel)
        self.assertEqual(raised.exception.status, 503)
        credential, state = self.saved()
        self.assertEqual((credential[5], credential[6]), (False, ['w_member_social']))
        self.assertEqual(state, self.state)

    def test_foreign_workspace_cannot_obtain_this_encrypted_connection(self):
        with self.assertRaises(AlphaError):
            self.oauth.token_for_worker(fixture.foreign, self.channel)
        self.assertEqual(self.calls, [])

    def aged_worker(self, *, expired=False, scoped=False, approval_seconds=None):
        self.provider.official_social_enabled = True
        state = self.saved()[1]
        channel = state['phase2']['channels'][0]
        channel['verifiedAt'] = self.now - 3601
        if approval_seconds is not None:
            job = state['phase2']['jobs'][0]
            job['manifest']['expiresAt'] = self.now + approval_seconds
            job['approvalDigest'] = digest(job['manifest'])
        if expired:
            channel['expiresAt'] = self.now - 1
        with fixture.connection() as db:
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), fixture.wid))
        self.posts = []
        def publish(method, url, **kwargs):
            self.assertEqual((method, url), ('POST', 'https://api.linkedin.com/rest/posts'))
            self.posts.append(kwargs['body'])
            return {'status': 201, 'headers': {'x-restli-id': 'urn:li:share:123456789'}, 'body': {}}
        worker = PostgresWorker(fixture.connection, social=HostedSocial(self.oauth, {'linkedin': self.provider}, transport=publish), clock=lambda: self.now)
        job = state['phase2']['jobs'][0]
        scope = dict(workspace_id=fixture.wid, job_id=job['id'], approval_digest=job['approvalDigest'], dispatch_principal=job['manifest']['actor']) if scoped else {}
        return worker, scope

    def test_scheduled_post_reverifies_aged_identity_without_renewing_approval(self):
        worker, scope = self.aged_worker()
        approved = self.saved()[1]['phase2']['jobs'][0]['manifest']
        self.assertTrue(worker.step(**scope))
        state = self.saved()[1]
        self.assertEqual(state['phase2']['jobs'][0]['state'], 'provider_accepted')
        self.assertEqual(state['phase2']['jobs'][0]['manifest'], approved)
        self.assertEqual(len(state['phase2']['jobs'][0]['attempts']), 1)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(state['phase2']['channels'][0]['verifiedAt'], self.now)

    def test_scoped_dispatch_reverifies_expired_cached_partner_access(self):
        worker, scope = self.aged_worker(expired=True, scoped=True)
        self.assertTrue(worker.step(**scope))
        self.assertEqual(self.saved()[1]['phase2']['jobs'][0]['state'], 'provider_accepted')
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(sum(url.endswith('/accessToken') for _, url in self.calls), 1)

    def test_transient_identity_failure_defers_without_consuming_create_attempt(self):
        worker, scope = self.aged_worker()
        self.identity_status = 503
        approved = self.saved()[1]['phase2']['jobs'][0]['manifest']
        self.assertTrue(worker.step(**scope))
        job = self.saved()[1]['phase2']['jobs'][0]
        self.assertEqual(job['state'], 'approved')
        self.assertEqual(job['attempts'], [])
        self.assertEqual(job['manifest'], approved)
        self.assertEqual(job['nextAt'], self.now + 60)
        self.assertEqual(self.posts, [])
        self.now += 61
        self.identity_status = 200
        self.assertTrue(worker.step(**scope))
        self.assertEqual(len(self.posts), 1)

    def test_permission_loss_during_scheduled_reverification_holds_without_post(self):
        worker, scope = self.aged_worker()
        self.introspection['scope'] = 'openid,profile'
        self.assertTrue(worker.step(**scope))
        state = self.saved()[1]
        self.assertEqual(state['phase2']['jobs'][0]['state'], 'held')
        self.assertFalse(state['phase2']['channels'][0]['capabilityVerified'])
        self.assertEqual(self.posts, [])

    def test_identity_drift_during_reverification_never_posts_to_replacement_account(self):
        worker, scope = self.aged_worker()
        self.identity_subject = 'different-member'
        self.assertTrue(worker.step(**scope))
        state = self.saved()[1]
        self.assertEqual(state['phase2']['jobs'][0]['state'], 'held')
        self.assertTrue(state['phase2']['channels'][0]['revoked'])
        self.assertEqual(self.posts, [])

    def test_cancellation_during_identity_check_wins_before_provider_intent(self):
        worker, scope = self.aged_worker()
        def cancel():
            snapshot = fixture.service.get(fixture.wid, 'fixture-one')
            fixture.service.mutate(fixture.wid, 'fixture-one', snapshot['revision'], 'p2_cancel', {'jobId': snapshot['state']['phase2']['jobs'][0]['id']})
        self.during_identity = cancel
        self.assertTrue(worker.step(**scope))
        self.assertEqual(self.saved()[1]['phase2']['jobs'][0]['state'], 'canceled')
        self.assertEqual(self.posts, [])

    def test_approval_expiring_during_identity_check_is_never_extended(self):
        worker, scope = self.aged_worker(approval_seconds=10)
        self.during_identity = lambda: setattr(self, 'now', self.now + 11)
        self.assertTrue(worker.step(**scope))
        self.assertEqual(self.saved()[1]['phase2']['jobs'][0]['state'], 'held')
        self.assertEqual(self.posts, [])

    def test_composer_reverification_requires_reload_and_creates_no_new_approval(self):
        self.aged_worker()
        before = self.saved()[1]
        job = before['phase2']['jobs'][0]
        snapshot = fixture.service.repository.get(fixture.wid, 'fixture-one')
        with self.assertRaises(AlphaError) as raised:
            self.oauth.refresh_for_composer(fixture.wid, 'fixture-one', snapshot['revision'], 'p2_review',
                {'variantId': job['manifest']['variantId'], 'channelId': self.channel})
        self.assertEqual(raised.exception.code, 'linkedin_connection_refreshed')
        after = self.saved()[1]
        self.assertEqual(after['phase2']['jobs'], before['phase2']['jobs'])
        self.assertEqual(after['phase2']['reviews'], before['phase2']['reviews'])
        self.assertEqual(self.posts, [])

    def test_rate_limit_retry_waits_and_creates_only_after_definite_rejection(self):
        self.provider.official_social_enabled = True
        posts = []
        def publish(method, url, **kwargs):
            self.assertEqual((method, url), ('POST', 'https://api.linkedin.com/rest/posts'))
            posts.append(kwargs['body'])
            return ({'status': 429, 'body': {}, 'headers': {'Retry-After': '120'}} if len(posts) == 1
                    else {'status': 201, 'body': {}, 'headers': {'x-restli-id': 'urn:li:share:123456789'}})
        social = HostedSocial(self.oauth, {'linkedin': self.provider}, transport=publish)
        worker = PostgresWorker(fixture.connection, social=social, clock=lambda: self.now)
        self.assertTrue(worker.step())
        _, state = self.saved()
        job = state['phase2']['jobs'][0]
        self.assertEqual(job['state'], 'scheduled')
        self.assertEqual(job['nextAt'], self.now + 120)
        self.assertFalse(worker.step())
        self.now += 121
        self.assertTrue(worker.step())
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0], posts[1])
        self.assertEqual(self.saved()[1]['phase2']['jobs'][0]['state'], 'provider_accepted')
        self.now += 10
        restarted = PostgresWorker(fixture.connection, social=social, clock=lambda: self.now)
        self.assertTrue(restarted.step())
        self.assertEqual(len(posts), 2, 'Accepted creates must never be retried')

    def test_lost_create_response_is_never_replayed_after_worker_restart(self):
        self.provider.official_social_enabled = True
        posts = []
        def lost_response(method, url, **kwargs):
            posts.append((method, url))
            raise TimeoutError('Synthetic lost response after possible acceptance')
        social = HostedSocial(self.oauth, {'linkedin': self.provider}, transport=lost_response)
        self.assertTrue(PostgresWorker(fixture.connection, social=social, clock=lambda: self.now).step())
        self.assertEqual(self.saved()[1]['phase2']['jobs'][0]['state'], 'uncertain')
        self.now += 10
        self.assertTrue(PostgresWorker(fixture.connection, social=social, clock=lambda: self.now).step())
        self.assertEqual(len(posts), 1)

    def test_linkedin_cron_lane_preserves_other_platform_jobs_and_reviews(self):
        worker, _ = self.aged_worker()
        state = self.saved()[1]
        foreign_job = copy.deepcopy(state['phase2']['jobs'][0])
        foreign_job['id'] = 'other-platform-job'
        foreign_job['manifest']['platform'] = 'Threads'
        foreign_job['manifest']['expiresAt'] = self.now - 1
        foreign_review = {'id': 'other-platform-review', 'manifest': copy.deepcopy(foreign_job['manifest']), 'status': 'needs_review'}
        state['phase2']['jobs'].append(foreign_job)
        state['phase2']['reviews'].append(foreign_review)
        with fixture.connection() as db:
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), fixture.wid))
        self.assertEqual(worker.tick_linkedin(1, 1)['processed'], 1)
        saved = self.saved()[1]
        self.assertEqual(saved['phase2']['jobs'][1], foreign_job)
        self.assertEqual(saved['phase2']['reviews'][-1], foreign_review)
        self.assertEqual(len(self.posts), 1)

    def posted_actions(self, *, lost=False):
        self.provider.official_social_enabled = True
        state = self.saved()[1]
        state['phase2']['channels'][0]['evidenceSource'] = 'live_provider'
        job = state['phase2']['jobs'][0]
        job.update(state='provider_accepted', providerReference='urn:li:share:123456789')
        with fixture.connection() as db:
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), fixture.wid))
        self.edits = []
        original = self.provider.transport
        def transport(method, url, **kwargs):
            if url.startswith('https://api.linkedin.com/rest/posts/'):
                self.assertEqual(method, 'POST')
                self.assertEqual(url, 'https://api.linkedin.com/rest/posts/urn%3Ali%3Ashare%3A123456789')
                self.assertEqual(kwargs['headers']['X-RestLi-Method'], 'PARTIAL_UPDATE')
                self.edits.append(kwargs['body'])
                if lost:
                    raise TimeoutError('Synthetic lost edit response')
                return {'status': 204, 'headers': {}, 'body': {}}
            return original(method, url, **kwargs)
        self.provider.transport = transport
        return SocialActionsService(self.oauth), copy.deepcopy(job)

    def text_edit_preview(self, actions):
        return actions.preview(fixture.wid, 'fixture-one', self.channel, 'edit', 'urn:li:share:123456789',
                               {'text': 'Updated synthetic test commentary'})

    def test_owned_post_edit_records_204_without_changing_original_create_approval(self):
        actions, original = self.posted_actions()
        preview = self.text_edit_preview(actions)
        self.assertEqual(self.edits, [], 'Review cannot execute an edit')
        result = actions.approve(fixture.wid, 'fixture-one', preview['id'], preview['digest'], True, connection_id=self.channel)
        self.assertEqual((result['executionState'], result['httpStatus']), ('submitted', 204))
        job = self.saved()[1]['phase2']['jobs'][0]
        self.assertEqual(job['manifest'], original['manifest'])
        self.assertEqual(job['approvalDigest'], original['approvalDigest'])
        self.assertEqual(job['publishedEdit']['text'], 'Updated synthetic test commentary')
        self.assertEqual(len(self.edits), 1)
        with self.assertRaises(AlphaError):
            actions.approve(fixture.wid, 'fixture-one', preview['id'], preview['digest'], True)
        self.assertEqual(len(self.edits), 1)

    def test_same_linkedin_identity_in_another_workspace_cannot_edit_this_receipt(self):
        self.posted_actions()
        other_user, other_workspace = str(uuid4()), str(uuid4())
        foreign = json.loads(json.dumps(self.saved()[1]).replace(fixture.wid, other_workspace).replace(fixture.one, other_user))
        foreign['phase2']['jobs'], foreign['phase2']['reviews'] = [], []
        with fixture.connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (other_user,))
            db.execute('INSERT INTO public.pr_profiles(user_id,display_name) VALUES(%s,%s)', (other_user, 'Second synthetic owner'))
            db.execute('INSERT INTO public.pr_workspaces(id,state) VALUES(%s,%s::jsonb)', (other_workspace, json.dumps(foreign)))
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')", (other_workspace, other_user))
        def verify(token):
            if token != 'synthetic-second-owner':
                raise AlphaError('Verified session required.', 401)
            return other_user
        repository = PostgresWorkspaceRepository(fixture.connection, verify, fixture.service.commands)
        oauth = OAuthService(repository, fixture.service.commands, self.vault, {'linkedin': self.provider}, self.provider.public_origin, clock=lambda: self.now)
        actions = SocialActionsService(oauth)
        with self.assertRaises(AlphaError) as error:
            actions.preview(other_workspace, 'synthetic-second-owner', self.channel, 'edit', 'urn:li:share:123456789', {'text': 'Foreign edit'})
        self.assertEqual(error.exception.code, 'linkedin_post_scope')
        self.assertEqual(self.edits, [])

    def test_native_action_route_cannot_substitute_another_connection(self):
        actions, _ = self.posted_actions()
        preview = self.text_edit_preview(actions)
        with self.assertRaises(AlphaError):
            actions.approve(fixture.wid, 'fixture-one', preview['id'], preview['digest'], True, connection_id='different-connection')
        self.assertEqual(self.edits, [])
        self.assertEqual(self.saved()[1]['phase2']['nativeSocialActions'][-1]['state'], 'preview')

    def test_later_edit_invalidates_an_older_exact_post_edit_preview(self):
        actions, _ = self.posted_actions()
        preview = self.text_edit_preview(actions)
        state = self.saved()[1]
        state['phase2']['jobs'][0]['publishedEdit'] = {'actionId': 'other-completed-edit', 'text': 'Changed meanwhile'}
        with fixture.connection() as db:
            db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(state), fixture.wid))
        with self.assertRaises(AlphaError):
            actions.approve(fixture.wid, 'fixture-one', preview['id'], preview['digest'], True)
        self.assertEqual(self.edits, [])

    def test_lost_edit_response_blocks_new_preview_and_never_replays(self):
        actions, _ = self.posted_actions(lost=True)
        preview = self.text_edit_preview(actions)
        self.assertEqual(actions.approve(fixture.wid, 'fixture-one', preview['id'], preview['digest'], True)['executionState'], 'uncertain')
        with self.assertRaises(AlphaError):
            actions.approve(fixture.wid, 'fixture-one', preview['id'], preview['digest'], True)
        with self.assertRaises(AlphaError) as error:
            self.text_edit_preview(actions)
        self.assertEqual(error.exception.code, 'linkedin_action_unresolved')
        self.assertEqual(len(self.edits), 1)

    def test_reconnection_before_edit_can_recover_with_a_new_review_without_replay(self):
        actions, _ = self.posted_actions()
        preview = self.text_edit_preview(actions)
        with fixture.connection() as db:
            db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=now() WHERE workspace_id=%s AND connection_id=%s', (fixture.wid, self.channel))
        self.assertEqual(actions.approve(fixture.wid, 'fixture-one', preview['id'], preview['digest'], True)['executionState'], 'held')
        self.assertEqual(self.edits, [])
        with fixture.connection() as db:
            db.execute('UPDATE public.pr_encrypted_credentials SET revoked_at=NULL WHERE workspace_id=%s AND connection_id=%s', (fixture.wid, self.channel))
        fresh = self.text_edit_preview(actions)
        self.assertNotEqual(fresh['id'], preview['id'])
        self.assertEqual(actions.approve(fixture.wid, 'fixture-one', fresh['id'], fresh['digest'], True)['executionState'], 'submitted')
        self.assertEqual(len(self.edits), 1)


result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LinkedInCustodySQL))
if not result.wasSuccessful():
    raise SystemExit(1)
