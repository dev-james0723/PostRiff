"""Injected-provider regressions. These are not real OAuth/publishing acceptance."""
import copy
import base64
import hashlib
import json
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.atproto_oauth import BlueskyProvider, generate_jwk
from postriff_phase2.bluesky_history import fetch_owned_page
from postriff_phase2.contracts import digest
from postriff_phase2.oauth import OAuthService
from test_hosted_wave1_connectors import BASE, DID, PUBLIC, Wire, ok, client_jwk, Grants, manifest
import test_hosted_wave1_connectors as fixtures
from postriff_phase2.hosted_social import HostedSocial
from test_youtube_worker_refresh import worker_for, NOW


class OAuthSecurity(unittest.TestCase):
    def provider(self, responses=()):
        self.wire = Wire(responses)
        return BlueskyProvider(client_jwk(), BASE, transport=self.wire, resolver=PUBLIC)

    def context(self, provider):
        return {'did': DID, 'issuer': 'https://auth.example.com', 'pds': 'https://pds.example.com',
                'tokenEndpoint': 'https://auth.example.com/oauth/token', 'dpopJwk': generate_jwk(),
                'clientId': provider.client_id, 'clientKeyId': provider.client_jwk['kid'],
                'clientKeyThumbprint': provider._client_thumbprint(), 'verifier': 'V'}

    def grant(self, provider):
        return provider._session({'access_token': 'AT', 'refresh_token': 'RT', 'token_type': 'DPoP',
                                 'scope': 'atproto', 'sub': DID, 'expires_in': 900}, self.context(provider), 'as-nonce')

    def test_identity_is_minimal_and_metadata_allows_progressive_publish(self):
        provider = self.provider()
        self.assertEqual(provider.capability_scopes('identity'), ['atproto'])
        self.assertEqual(provider.capability_scopes('posts_read'), ['atproto'])
        self.assertNotIn('transition:generic', provider.client_metadata()['scope'])
        self.assertIn(provider.POST_CREATE, provider.client_metadata()['scope'])
        self.assertFalse(provider.grants_capability('publish', ['atproto']))
        self.assertTrue(provider.grants_capability('publish', provider.capability_scopes('publish')))
        self.assertTrue(provider.grants_capability('publish', ['atproto', 'transition:generic']))
        matrix = OAuthService._capabilities(provider, 'publish', provider.capability_scopes('publish'), [], NOW)
        self.assertEqual(matrix['publish']['level'], 'Assisted')  # Deployment review is still gated.
        provider.production_reviewed = True
        matrix = OAuthService._capabilities(provider, 'publish', provider.capability_scopes('publish'), [], NOW)
        self.assertEqual(matrix['schedule']['level'], 'Direct')

    def test_did_input_skips_mutable_handle_resolution(self):
        responses = fixtures.BlueskyAdapter().resolution()[1:] + [ok({'request_uri': 'urn:x'}, 201)]
        provider = self.provider(responses)
        begun = provider.begin(BASE + '/cb', 'S', 'V', 'C', ['atproto'], DID)
        self.assertEqual(begun['context']['did'], DID)
        self.assertEqual(self.wire.calls[-1]['form']['login_hint'], DID)
        self.assertFalse(any('resolveHandle' in c['url'] or 'atproto-did' in c['url'] for c in self.wire.calls))

    def test_malformed_did_never_calls_provider(self):
        provider = self.provider()
        for identifier in ('did:key:abc', 'did:web:localhost', 'did:plc:short', 'did:plc:' + 'a' * 24 + '?x=1'):
            with self.subTest(identifier=identifier), self.assertRaises(AlphaError):
                provider.begin(BASE + '/cb', 'S', 'V', 'C', ['atproto'], identifier)
        self.assertEqual(self.wire.calls, [])

    def test_missing_atproto_or_invalid_lifetime_is_not_custodied(self):
        provider = self.provider()
        base = {'access_token': 'AT', 'token_type': 'DPoP', 'scope': 'atproto', 'sub': DID}
        for change in ({'scope': ''}, {'scope': None}, {'expires_in': 0}, {'expires_in': -1},
                       {'expires_in': True}, {'expires_in': '900'}, {'expires_in': 901}, {'expires_in': float('nan')}):
            with self.subTest(change=change), self.assertRaises(AlphaError):
                provider._session({**base, **change}, self.context(provider), None)

    def test_client_origin_or_signing_key_change_blocks_exchange_and_refresh(self):
        provider = self.provider()
        grant, context = self.grant(provider), self.context(provider)
        for changed in (BlueskyProvider(provider.client_jwk, 'https://rafii.io', transport=self.wire, resolver=PUBLIC),
                        BlueskyProvider(client_jwk(), BASE, transport=self.wire, resolver=PUBLIC)):
            with self.assertRaises(AlphaError):
                changed.refresh(grant['refreshToken'])
            with self.assertRaises(AlphaError):
                changed.exchange('CODE', json.dumps(context), BASE + '/cb', iss=context['issuer'])
        self.assertEqual(self.wire.calls, [])

    def test_legacy_refresh_requires_new_bound_consent(self):
        provider = self.provider()
        stored = json.loads(self.grant(provider)['refreshToken'])
        stored.pop('clientId')
        with self.assertRaises(AlphaError) as caught:
            provider.refresh(json.dumps(stored))
        self.assertEqual(caught.exception.code, 'reauthorization_required')
        self.assertEqual(self.wire.calls, [])

    def test_key_id_change_requires_new_consent_even_for_same_public_key(self):
        provider = self.provider()
        grant = self.grant(provider)
        key = {**provider.client_jwk, 'kid': 'changed-key-id'}
        changed = BlueskyProvider(key, BASE, transport=self.wire, resolver=PUBLIC)
        with self.assertRaises(AlphaError) as caught:
            changed.refresh(grant['refreshToken'])
        self.assertEqual(caught.exception.code, 'reauthorization_required')
        self.assertEqual(self.wire.calls, [])

    def test_revoked_identity_requires_reconnect_but_outage_preserves_scopes(self):
        provider = self.provider([ok({'error': 'ExpiredToken'}, 401)])
        with self.assertRaises(AlphaError) as caught:
            provider.inspect_scopes(self.grant(provider)['accessToken'], DID)
        self.assertEqual(caught.exception.code, 'reauthorization_required')
        provider = self.provider([ok({}, 503)])
        self.assertIsNone(provider.inspect_scopes(self.grant(provider)['accessToken'], DID))

    def test_invalid_token_with_nonce_does_not_replay_a_write(self):
        provider = self.provider([ok({'error': 'invalid_token'}, 401, {'dpop-nonce': 'fresh'})])
        session = json.loads(self.grant(provider)['accessToken'])
        response = provider.xrpc_post(session, 'com.atproto.repo.createRecord', body={})
        self.assertEqual(response['status'], 401)
        self.assertEqual(len(self.wire.calls), 1)
        self.assertEqual(session['pdsNonce'], 'fresh')

    def test_get_nonce_is_reused_by_next_request(self):
        provider = self.provider([ok({'error': 'use_dpop_nonce'}, 401, {'dpop-nonce': 'n1'}), ok({}), ok({})])
        session = json.loads(self.grant(provider)['accessToken'])
        provider.xrpc_get(session, 'com.atproto.server.getSession', {})
        provider.xrpc_get(session, 'com.atproto.server.getSession', {})
        from test_hosted_wave1_connectors import jwt
        self.assertEqual(jwt(self.wire.calls[-1]['headers']['DPoP'])[1]['nonce'], 'n1')

    def test_refresh_rate_limit_and_outage_are_not_revocation(self):
        for status in (429, 500, 503):
            provider = self.provider([fixtures.BlueskyAdapter().resolution()[1], ok({'error': 'temporarily_unavailable'}, status)])
            with self.subTest(status=status), self.assertRaises(AlphaError) as caught:
                provider.refresh(self.grant(provider)['refreshToken'])
            self.assertEqual(caught.exception.code, 'bluesky_refresh_unavailable')

    def test_refresh_invalid_grant_requires_reconnect(self):
        provider = self.provider([fixtures.BlueskyAdapter().resolution()[1], ok({'error': 'invalid_grant'}, 400)])
        with self.assertRaises(AlphaError) as caught:
            provider.refresh(self.grant(provider)['refreshToken'])
        self.assertEqual(caught.exception.code, 'reauthorization_required')

    def test_rotated_session_keeps_binding_and_dpop_key(self):
        provider = self.provider([fixtures.BlueskyAdapter().resolution()[1], ok({'access_token': 'AT2', 'refresh_token': 'RT2', 'token_type': 'DPoP',
                                     'scope': 'atproto', 'sub': DID, 'expires_in': 900})])
        previous = self.grant(provider)
        fresh = provider.refresh(previous['refreshToken'])
        old, new = json.loads(previous['accessToken']), json.loads(fresh['accessToken'])
        self.assertEqual(new['jwk'], old['jwk'])
        self.assertEqual(new['clientId'], old['clientId'])
        self.assertEqual((new['at'], new['rt']), ('AT2', 'RT2'))

    def test_pds_migration_does_not_forward_old_credentials(self):
        document = copy.deepcopy(fixtures.BlueskyAdapter().resolution()[1])
        document['body']['service'][0]['serviceEndpoint'] = 'https://new-pds.example.com'
        provider = self.provider([document])
        with self.assertRaises(AlphaError) as caught:
            provider.refresh(self.grant(provider)['refreshToken'])
        self.assertEqual(caught.exception.code, 'reauthorization_required')
        self.assertFalse(any('new-pds' in c['url'] for c in self.wire.calls))
        self.assertFalse(any(c['method'] == 'POST' for c in self.wire.calls))

    def test_omitted_refresh_token_remains_revocable(self):
        provider = self.provider([fixtures.BlueskyAdapter().resolution()[1], ok({'access_token': 'AT2', 'token_type': 'DPoP',
                                     'scope': 'atproto', 'sub': DID, 'expires_in': 900})])
        fresh = provider.refresh(self.grant(provider)['refreshToken'])
        self.assertEqual(json.loads(fresh['accessToken'])['rt'], 'RT')
        self.assertEqual(json.loads(fresh['refreshToken'])['rt'], 'RT')

    def test_only_first_valid_did_handle_claim_is_authoritative(self):
        responses = fixtures.BlueskyAdapter().resolution()
        responses[1]['body']['alsoKnownAs'].insert(0, 'at://other.bsky.social')
        provider = self.provider(responses)
        with self.assertRaises(AlphaError):
            provider.begin(BASE + '/cb', 'S', 'V', 'C', ['atproto'], 'alice.example.com')
        self.assertFalse(any(c['method'] == 'POST' for c in self.wire.calls))

    def test_resource_or_pds_origin_mismatch_is_rejected(self):
        for resource in ('https://other.example.com', 'https://pds.example.com/path'):
            provider = self.provider([ok({'resource': resource, 'authorization_servers': ['https://auth.example.com']})])
            with self.assertRaises(AlphaError):
                provider.authorization_server('https://pds.example.com')
        with self.assertRaises(AlphaError):
            BlueskyProvider.pds_endpoint({'service': [{'id': '#atproto_pds', 'type': 'AtprotoPersonalDataServer',
                                                       'serviceEndpoint': 'https://pds.example.com/path'}]})

    def test_mismatched_manifest_did_never_posts(self):
        provider = self.provider()
        provider.production_reviewed = True
        session = json.loads(self.grant(provider)['accessToken'])
        session['scope'] = provider.capability_scopes('publish')
        social = HostedSocial(Grants(json.dumps(session), session['scope']), {'bluesky': provider})
        result = social.submit(manifest('Bluesky', 'did:plc:' + 'z' * 24))
        self.assertEqual(result['state'], 'held')
        self.assertEqual(self.wire.calls, [])


class OwnedHistory(unittest.TestCase):
    def post(self, did=DID):
        return {'post': {'uri': 'at://' + did + '/app.bsky.feed.post/3aaaaaaaaaaaa', 'author': {'did': did},
                         'record': {'$type': 'app.bsky.feed.post', 'text': 'My original', 'createdAt': '2026-10-10T12:00:00Z'},
                         'likeCount': 4, 'replyCount': 2, 'repostCount': 1, 'quoteCount': 0, 'impressions': 1000}}

    def test_filters_others_reposts_duplicates_and_reports_only_public_counts(self):
        original = self.post()
        repost = {**self.post(), 'reason': {'$type': 'app.bsky.feed.defs#reasonRepost'}}
        wire = Wire([ok({'feed': [original, self.post('did:plc:' + 'z' * 24), repost, original], 'cursor': '2026-10-10T12:00:00Z::cid'})])
        provider = BlueskyProvider(client_jwk(), BASE, transport=wire, resolver=PUBLIC)
        page = fetch_owned_page(provider, json.dumps({'did': DID}), DID)
        self.assertEqual(len(page['posts']), 1)
        self.assertEqual(page['posts'][0]['publicEngagement'], {'likeCount': 4, 'replyCount': 2, 'repostCount': 1, 'quoteCount': 0})
        self.assertTrue(page['partialCoverage'])
        self.assertEqual(wire.calls[0]['headers'], {})

    def test_other_account_refused_before_network(self):
        wire = Wire([])
        provider = BlueskyProvider(client_jwk(), BASE, transport=wire, resolver=PUBLIC)
        with self.assertRaises(AlphaError):
            fetch_owned_page(provider, json.dumps({'did': DID}), 'did:plc:' + 'z' * 24)
        self.assertEqual(wire.calls, [])

    def test_rate_limit_or_invalid_page_is_not_empty_history(self):
        for response in (ok({}, 429), ok({'feed': None}), ok({'feed': [], 'cursor': '../bad'})):
            provider = BlueskyProvider(client_jwk(), BASE, transport=Wire([response]), resolver=PUBLIC)
            with self.assertRaises(AlphaError):
                fetch_owned_page(provider, json.dumps({'did': DID}), DID)


class PublicationEvidence(unittest.TestCase):
    def social(self, responses, raw=b'approved-decoded-image'):
        wire = Wire(responses)
        provider = BlueskyProvider(client_jwk(), BASE, transport=wire, resolver=PUBLIC, production_reviewed=True)
        session = json.dumps({'did': DID, 'pds': 'https://pds.example.com', 'at': 'AT', 'jwk': generate_jwk()})
        assets = SimpleNamespace(storage=SimpleNamespace(get=Mock(return_value=raw)))
        return HostedSocial(Grants(session, provider.capability_scopes('publish')), {'bluesky': provider}, assets=assets), wire

    def image(self):
        raw = b'approved-decoded-image'
        asset = {'id': 'approved-media', 'mime': 'image/jpeg', 'bytes': len(raw), 'hash': hashlib.sha256(raw).hexdigest(), 'alt': 'A piano'}
        cid = 'b' + base64.b32encode(b'\x01\x55\x12\x20' + hashlib.sha256(raw).digest()).decode().lower().rstrip('=')
        return asset, {'$type': 'blob', 'ref': {'$link': cid}, 'size': len(raw), 'mimeType': 'image/jpeg'}

    def test_changed_storage_bytes_never_upload_or_publish(self):
        social, wire = self.social([], raw=b'changed')
        asset, _ = self.image()
        result = social.submit(manifest('Bluesky', DID, media=[asset]))
        self.assertEqual(result['state'], 'held')
        self.assertEqual(wire.calls, [])

    def test_image_blob_must_match_approved_hash_before_record_creation(self):
        asset, blob = self.image()
        social, wire = self.social([ok({'blob': {**blob, 'ref': {'$link': 'wrong-cid'}}})])
        result = social.submit(manifest('Bluesky', DID, media=[asset]))
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(len(wire.calls), 1)
        self.assertIn('uploadBlob', wire.calls[0]['url'])

    def test_readback_checks_links_and_images_instead_of_only_text(self):
        asset, blob = self.image()
        job = manifest('Bluesky', DID, media=[asset])
        reference = f'at://{DID}/app.bsky.feed.post/{HostedSocial.bluesky_rkey(job)}'
        record = {'$type': 'app.bsky.feed.post', 'text': job['payload']['text'],
            'facets': HostedSocial._bluesky_facets(job['payload']['text']),
            'embed': {'$type': 'app.bsky.embed.images', 'images': [{'image': blob, 'alt': asset['alt']}]}}
        for changed in ('none', 'link', 'image', 'alt', 'reply'):
            value = copy.deepcopy(record)
            if changed == 'link': value['facets'][0]['features'][0]['uri'] = 'https://wrong.example/'
            if changed == 'image': value['embed']['images'][0]['image']['ref']['$link'] = 'wrong-cid'
            if changed == 'alt': value['embed']['images'][0]['alt'] = 'Not approved'
            if changed == 'reply': value['reply'] = {'root': {}, 'parent': {}}
            social, wire = self.social([ok({'value': value})])
            result = social.reconcile(job, {'providerReference': reference})
            with self.subTest(changed=changed):
                self.assertEqual(result['state'], 'verified' if changed == 'none' else 'uncertain')
                self.assertEqual(len(wire.calls), 1)

    def test_missing_embed_is_not_confirmed_and_valid_upload_creates_once(self):
        asset, blob = self.image()
        job = manifest('Bluesky', DID, media=[asset])
        self.assertFalse(HostedSocial._bluesky_record_matches(job, {'$type': 'app.bsky.feed.post', 'text': job['payload']['text']}))
        reference = f'at://{DID}/app.bsky.feed.post/{HostedSocial.bluesky_rkey(job)}'
        social, wire = self.social([ok({'blob': blob}), ok({'uri': reference})])
        self.assertEqual(social.submit(job)['state'], 'provider_accepted')
        self.assertEqual([c['url'].split('/')[-1] for c in wire.calls], ['com.atproto.repo.uploadBlob', 'com.atproto.repo.createRecord'])


class BlueskyWorker(unittest.TestCase):
    def worker(self):
        worker, db, now, order, verify = worker_for(1)
        for channel in db.state['phase2']['channels']:
            channel.update(platform='Bluesky', scopes=BlueskyProvider.SCOPES['publish'], providerAccountId=DID)
        for job in db.state['phase2']['jobs']:
            job['manifest'].update(platform='Bluesky', providerAccountId=DID)
            job['manifest']['capability']['scopes'] = list(BlueskyProvider.SCOPES['publish'])
            job['approvalDigest'] = digest(job['manifest'])
        worker.social.oauth = worker.social.youtube.oauth
        return worker, db, now, order, verify

    @patch('postriff_phase2.billing.require_publishing')
    def test_expired_session_reverifies_outside_lock_before_scheduled_post(self, _billing):
        worker, db, _, order, _ = self.worker()
        self.assertTrue(worker.step())
        self.assertEqual(order, [('verify', 'connection-0'), ('submit', 'connection-0')])
        self.assertEqual(len(db.state['phase2']['jobs'][0]['attempts']), 1)

    @patch('postriff_phase2.billing.require_publishing')
    def test_transient_verification_defers_without_an_attempt(self, _billing):
        worker, db, now, _, _ = self.worker()
        worker.social.oauth.reverify_for_worker = Mock(return_value={'state': 'verification_unavailable', 'ready': False})
        self.assertTrue(worker.step())
        job = db.state['phase2']['jobs'][0]
        self.assertEqual((job['state'], job['attempts']), ('approved', []))
        self.assertTrue(NOW + 60 <= job['nextAt'] <= NOW + 75)
        first = job['nextAt'] - now[0]
        now[0] = job['nextAt']
        worker.step()
        job = db.state['phase2']['jobs'][0]
        self.assertGreater(job['nextAt'] - now[0], first)
        self.assertEqual(job['attempts'], [])
        worker.social.submit.assert_not_called()

    @patch('postriff_phase2.billing.require_publishing')
    def test_cancel_during_verification_never_posts(self, _billing):
        worker, db, _, _, verify = self.worker()
        def canceled(workspace, connection):
            db.state['phase2']['jobs'][0]['cancelRequested'] = True
            return verify(workspace, connection)
        worker.social.oauth.reverify_for_worker = Mock(side_effect=canceled)
        worker.step()
        worker.social.submit.assert_not_called()
        self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'canceled')

    @patch('postriff_phase2.billing.require_publishing')
    def test_scope_loss_holds_without_post(self, _billing):
        worker, db, _, _, verify = self.worker()
        def lost(workspace, connection):
            result = verify(workspace, connection)
            db.state['phase2']['channels'][0]['scopes'] = ['atproto']
            return result
        worker.social.oauth.reverify_for_worker = Mock(side_effect=lost)
        worker.step()
        worker.social.submit.assert_not_called()
        self.assertEqual(db.state['phase2']['jobs'][0]['state'], 'held')


if __name__ == '__main__':
    unittest.main()
