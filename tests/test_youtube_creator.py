"""Official-contract and crash-recovery tests. All transports are synthetic, never real E2E."""
import copy
import hashlib
import io
import json
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image
from postriff_alpha.domain import AlphaError
from postriff_phase2.youtube.api import YouTubeApi, validate_caption, validate_image
from postriff_phase2.youtube.model import (READ, UPLOAD, MANAGE, ANALYTICS, MONEY, MEMBERS, METHODS,
    capability_matrix, lifecycle, merged_update, project_public_gate, validate_video, api_error, quota_reset)
from postriff_phase2.youtube.provider import YouTubeProvider
from postriff_phase2.youtube.uploads import UploadEngine, CHUNK_SIZE, session_url
from postriff_phase2.youtube.notifications import feed_entries, verified_signature
from postriff_phase2.youtube.service import YouTubeCreatorService
from postriff_phase2.youtube.journal import UploadJournal
from postriff_phase2.youtube.model import upload_body
from postriff_phase2.outcomes import normalize_result

CHANNEL, OTHER, VIDEO = 'UC' + 'a' * 22, 'UC' + 'b' * 22, 'abcdefghijk'
OPTIONS = {'title': 'Exact title', 'description': 'Line one\nLine two https://example.com', 'privacyStatus': 'private', 'madeForKids': False, 'containsSyntheticMedia': False}
MEDIA = {'id': 'a' * 32, 'mime': 'video/mp4', 'bytes': CHUNK_SIZE + 7, 'width': 1080, 'height': 1920, 'duration': 180}


class Journal:
    def __init__(self):
        self.states = {}; self.saves = []
        self.generation, self.locked_generation, self.revoked = 1, None, False
    @contextmanager
    def lock(self, _):
        self.locked_generation = self.generation
        try:
            yield
        finally:
            self.locked_generation = None
    def assert_current(self, _key):
        if self.revoked or self.generation != self.locked_generation:
            raise UploadJournal._authorization_error(changed=not self.revoked)
    def load(self, key): return copy.deepcopy(self.states.get(key))
    def save(self, key, state):
        self.assert_current(key)
        self.states[key] = copy.deepcopy(state); self.saves.append(copy.deepcopy(state))
    def seal(self, value): return ('encrypted:' + value, 'test-key')
    def unseal(self, value, _): return value.removeprefix('encrypted:')


class Wire:
    def __init__(self, journal=None):
        self.calls, self.offset, self.journal = [], 0, journal
        self.fault = None
    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == 'POST' and 'uploadType=resumable' in url:
            if self.journal: assert self.journal.saves[-1]['stage'] == 'session_open_attempted'
            if self.fault == 'initial-timeout': raise AlphaError('Network unavailable.', 503)
            return {'status': 200, 'headers': {'location': 'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=synthetic'}, 'body': {}}
        if 'upload_id=' in url:
            if self.journal: assert self.journal.saves[-1].get('sessionCiphertext', '').startswith('encrypted:')
            content_range = kwargs['headers']['Content-Range']
            if content_range.startswith('bytes */'):
                if self.offset == MEDIA['bytes']:
                    return {'status': 200, 'headers': {}, 'body': {'id': VIDEO}}
                return {'status': 308, 'headers': {'range': 'bytes=0-' + str(self.offset - 1)} if self.offset else {}, 'body': {}}
            self.offset += len(kwargs['data'])
            if self.fault == 'chunk-timeout':
                self.fault = None; raise AlphaError('Network unavailable.', 503)
            if self.offset == MEDIA['bytes']:
                return {'status': 200, 'headers': {}, 'body': {'id': VIDEO}}
            return {'status': 308, 'headers': {'range': 'bytes=0-' + str(self.offset - 1)}, 'body': {}}
        raise AssertionError('Unexpected synthetic method: ' + url)


def api(wire, scopes=(READ, UPLOAD, MANAGE, ANALYTICS)):
    provider = YouTubeProvider('test-client', 'test-secret', transport=wire, creator_enabled=True)
    grant = {'accessToken': json.dumps({'v': 1, 'at': 'synthetic-token'}), 'scopes': list(scopes)}
    return YouTubeApi(provider, grant, CHANNEL, clock=lambda: 1_000_000_000)


def manifest():
    return {'workspaceId': 'one', 'channelId': 'connection-one', 'providerAccountId': CHANNEL, 'idempotencyKey': 'exact-key', 'publishOptions': copy.deepcopy(OPTIONS), 'media': [copy.deepcopy(MEDIA)], 'payload': {'text': OPTIONS['description']}}


class ContractTests(unittest.TestCase):
    def test_schedule_lead_is_rechecked_after_authorization_fence_wait(self):
        calls, reservations, now = [], [], [1_000_000_000]
        a = api(lambda *args, **kwargs: calls.append((args, kwargs)))
        a.clock = lambda: now[0]
        a.account_usage = lambda *args: reservations.append(args)
        a.before_request = lambda: now.__setitem__(0, now[0] + 45)
        target = datetime.fromtimestamp(now[0] + 90, timezone.utc).isoformat().replace('+00:00', 'Z')
        with self.assertRaises(AlphaError) as expired:
            a.call('videos.update', {'part': 'status'}, {'id': VIDEO, 'status': {'privacyStatus': 'private', 'publishAt': target}})
        self.assertEqual(expired.exception.code, 'youtube_invalid_scheduling_state')
        self.assertEqual(calls, [])
        self.assertEqual(len(reservations), 1)

    def test_upload_quota_current_separate_bucket(self):
        self.assertEqual((METHODS['videos.insert']['bucket'], METHODS['videos.insert']['cost']), ('videoUploads', 1))
        self.assertEqual(METHODS['captions.insert']['cost'], 400)
        self.assertEqual(METHODS['captions.update']['cost'], 450)
        self.assertNotIn('communityPosts.insert', METHODS)

    def test_incremental_oauth_has_no_unrequested_sensitive_scope(self):
        p = api(Wire()).provider
        self.assertEqual(p.capability_scopes('publish'), [READ, UPLOAD])
        self.assertNotIn(MONEY, p.capability_scopes('publish'))
        self.assertNotIn(MEMBERS, p.capability_scopes('live'))
        self.assertNotIn('https://www.googleapis.com/auth/youtube', p.capability_scopes('manage_video'))
        q = parse_qs(urlsplit(p.authorize_url('https://example.com/callback', 'state', 'challenge', [READ])).query)
        self.assertEqual(q['prompt'], ['consent select_account'])
        self.assertEqual(q['access_type'], ['offline'])
        self.assertEqual(q['code_challenge_method'], ['S256'])

    def test_identity_success_never_means_full_access(self):
        p = api(Wire()).provider
        matrix = capability_matrix(p, [READ], {'id': CHANNEL})
        self.assertEqual(matrix['identity']['state'], 'IMPLEMENTED / E2E NOT PROVEN')
        self.assertFalse(matrix['upload']['canExecute'])
        self.assertEqual(matrix['community_posts']['state'], 'UNSUPPORTED BY OFFICIAL API')
        self.assertEqual(matrix['monetary_analytics']['state'], 'NOT AUTHORIZED')
        monetary_grant = capability_matrix(p, [READ, MONEY], {'id': CHANNEL})
        self.assertTrue(monetary_grant['analytics']['canExecute'])
        self.assertEqual(monetary_grant['monetary_analytics']['state'], 'NOT AUTHORIZED')

    def test_project_and_real_evidence_are_independent(self):
        p = api(Wire()).provider; p.production_reviewed = True
        self.assertFalse(project_public_gate(p))
        m = capability_matrix(p, [READ, UPLOAD, MANAGE], {'id': CHANNEL})
        self.assertEqual(m['public_publish']['state'], 'BLOCKED — GOOGLE APPROVAL')
        p.project_evidence = {'projectId': 'test-project', 'clientId': p.client_id, **{k: {'status': 'verified', 'source': 'google_platform', 'reference': 'test-evidence', 'observedAt': '2026-10-05'} for k in ('oauthVerification', 'youtubeComplianceAudit', 'publicUploadEligibility')}}
        m = capability_matrix(p, [READ, UPLOAD, MANAGE], {'id': CHANNEL}, {'public_publish': {'status': 'PASS', 'execution': 'mock', 'channelId': CHANNEL, 'reference': VIDEO, 'verifiedAt': 1}})
        self.assertTrue(m['public_publish']['canExecute']); self.assertNotEqual(m['public_publish']['state'], 'READY')
        m = capability_matrix(p, [READ], {'id': CHANNEL}, {'identity': {'status': 'PASS', 'execution': 'real', 'channelId': OTHER, 'reference': VIDEO, 'verifiedAt': 1}})
        self.assertNotEqual(m['identity']['state'], 'READY')
        m = capability_matrix(p, [READ], {'id': CHANNEL}, {'identity': {'status': 'PASS', 'execution': 'real', 'channelId': CHANNEL, 'reference': CHANNEL, 'verifiedAt': 1}})
        self.assertNotEqual(m['identity']['state'], 'READY')
        p.project_evidence['oauthVerification']['observedAt'] = '2001-01-01'
        self.assertFalse(project_public_gate(p))

    def test_declarations_and_exact_content(self):
        options = validate_video(OPTIONS, [MEDIA]); self.assertEqual(options['description'], OPTIONS['description'])
        for field in ('madeForKids', 'containsSyntheticMedia'):
            missing = {k: v for k, v in OPTIONS.items() if k != field}
            with self.assertRaises(AlphaError): validate_video(missing, [MEDIA])
        with self.assertRaises(AlphaError): validate_video(OPTIONS | {'title': 'x' * 101}, [MEDIA])
        with self.assertRaises(AlphaError): validate_video(OPTIONS | {'description': '界' * 1667}, [MEDIA])
        with self.assertRaises(AlphaError): validate_video(OPTIONS | {'tags': ['x' * 501]}, [MEDIA])
        with self.assertRaises(AlphaError): validate_video(OPTIONS, [{'mime': 'image/jpeg'}])

    def test_shorts_square_and_vertical_boundary_no_synthetic_flag(self):
        self.assertEqual(validate_video(OPTIONS | {'mode': 'short'}, [MEDIA])['mode'], 'short')
        validate_video(OPTIONS | {'mode': 'short'}, [MEDIA | {'height': 1080}])
        for invalid in ({'height': 720}, {'duration': 181}, {'duration': None}):
            with self.assertRaises(AlphaError): validate_video(OPTIONS | {'mode': 'short'}, [MEDIA | invalid])
        with self.assertRaises(AlphaError): validate_video(OPTIONS | {'short': True}, [MEDIA])

    def test_scheduling_timezone_future_public_constraints(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        good = OPTIONS | {'privacyStatus': 'public', 'publishAt': '2026-10-06T12:00:00+08:00'}
        self.assertEqual(validate_video(good, [MEDIA], now=now)['publishAt'], '2026-10-06T04:00:00Z')
        for patch in ({'privacyStatus': 'private'}, {'publishAt': '2026-10-04T00:00:00Z'}, {'publishAt': '2026-10-06T04:00:00'}):
            with self.assertRaises(AlphaError): validate_video(good | patch, [MEDIA], now=now)

    def test_merge_preserves_omitted_fields_and_drops_read_only_fields(self):
        old = {'id': VIDEO, 'snippet': {'title': 'Old', 'description': 'Keep', 'tags': ['one'], 'categoryId': '22', 'channelId': CHANNEL}, 'status': {'privacyStatus': 'private', 'publishAt': '2099-01-01T00:00:00Z', 'uploadStatus': 'processed', 'selfDeclaredMadeForKids': False}}
        updated = merged_update('videos', old, {'snippet': {'title': 'New'}, 'status': {'publishAt': None}})
        self.assertEqual(updated['snippet']['description'], 'Keep'); self.assertEqual(updated['snippet']['tags'], ['one'])
        self.assertNotIn('channelId', updated['snippet']); self.assertNotIn('publishAt', updated['status']); self.assertNotIn('uploadStatus', updated['status'])

    def test_processing_is_not_publication(self):
        self.assertEqual(lifecycle({'status': {'uploadStatus': 'uploaded', 'privacyStatus': 'public'}})['stage'], 'processing')
        self.assertEqual(lifecycle({'status': {'uploadStatus': 'processed', 'privacyStatus': 'private'}})['stage'], 'processed_private')
        self.assertEqual(lifecycle({'status': {'uploadStatus': 'processed', 'privacyStatus': 'private', 'publishAt': '2099-01-01T00:00:00Z'}})['stage'], 'native_scheduled')
        self.assertEqual(lifecycle({'status': {'uploadStatus': 'rejected', 'rejectionReason': 'copyright'}})['errorCategory'], 'rejection')

    def test_podcast_square_image_and_caption_validation(self):
        image = io.BytesIO(); Image.new('RGB', (800, 800)).save(image, 'PNG'); self.assertEqual(validate_image(image.getvalue(), True), 'image/png')
        image = io.BytesIO(); Image.new('RGB', (800, 600)).save(image, 'JPEG')
        with self.assertRaises(AlphaError): validate_image(image.getvalue(), True)
        raw, _ = validate_caption({'language': 'en', 'name': 'English', 'text': '1\n00:00:00,000 --> 00:00:01,000\nHello', 'format': 'srt'})
        self.assertIn(b'Hello', raw)
        with self.assertRaises(AlphaError): validate_caption({'text': 'not timed'})

    def test_quota_errors_never_become_generic_retry(self):
        error = api_error({'status': 403, 'body': {'error': {'errors': [{'reason': 'quotaExceeded'}]}}}, 'videos.insert', 1_000_000_000)
        self.assertEqual(error.category, 'quota'); self.assertFalse(error.retryable); self.assertGreater(error.retry_at, 1_000_000_000)
        self.assertFalse(api_error({'status': 429}, 'comments.insert', 1_000_000_000).retryable)
        self.assertTrue(api_error({'status': 503}, 'videos.insert', 1_000_000_000).ambiguous)
        for invalid in ('https://evil.example/upload?upload_id=x', 'http://www.googleapis.com/upload/youtube/v3/videos?upload_id=x', 'https://www.googleapis.com/youtube/v3/videos?upload_id=x'):
            with self.assertRaises(AlphaError): session_url(invalid)

    def test_immediate_publishing_cannot_carry_a_native_schedule(self):
        with self.assertRaises(AlphaError):
            validate_video(OPTIONS | {'privacyStatus': 'public', 'publicationMode': 'now', 'publishAt': '2099-01-01T00:00:00Z'}, [MEDIA])

    def test_signed_push_feed_cannot_change_channel_or_expand_entities(self):
        import hashlib, hmac
        feed = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:channelId>'
                + CHANNEL + '</yt:channelId><yt:videoId>' + VIDEO + '</yt:videoId><updated>2026-10-05T00:00:00Z</updated></entry></feed>').encode()
        self.assertEqual(feed_entries(feed, CHANNEL)[0]['videoId'], VIDEO)
        signature = 'sha1=' + hmac.new(b'synthetic-secret', feed, hashlib.sha1).hexdigest()
        self.assertTrue(verified_signature(feed, signature, 'synthetic-secret'))
        self.assertFalse(verified_signature(feed + b' ', signature, 'synthetic-secret'))
        with self.assertRaises(AlphaError): feed_entries(feed, OTHER)
        for bad in (b'<!DOCTYPE feed [<!ENTITY x "expanded">]><feed/>', b'\x00<feed/>'):
            with self.assertRaises(AlphaError): feed_entries(bad, CHANNEL)

    def test_interactive_analytics_pages_are_complete_or_explicitly_bounded(self):
        seen = []
        def wire(_, url, **__):
            start = int(parse_qs(urlsplit(url).query)['startIndex'][0]); seen.append(start)
            return {'status': 200, 'body': {'columnHeaders': [{'name': 'views'}], 'rows': [[start + n] for n in range(200)]}}
        report = api(wire).analytics('daily', '2026-01-01', '2026-10-01')
        self.assertEqual(seen, [1, 201, 401, 601, 801]); self.assertEqual(len(report['data']['rows']), 1000)
        self.assertFalse(report['coverage']['complete']); self.assertIn('1,000', report['limitation'])

    def test_mutator_error_callback_receives_revocation(self):
        errors = []
        a = api(lambda *_args, **_kwargs: {'status': 401, 'body': {}})
        a.on_error = lambda error, method: errors.append((error.category, method))
        with self.assertRaises(AlphaError): a.call('videos.list', {'id': VIDEO, 'part': 'id'})
        self.assertEqual(errors, [('revoked_oauth', 'videos.list')])


class UploadTests(unittest.TestCase):
    def setup_engine(self):
        self.journal = Journal(); self.wire = Wire(self.journal); self.clock = [1_000_000_000]
        self.a = api(self.wire)
        self.video = {'id': VIDEO, 'snippet': {'channelId': CHANNEL, 'title': OPTIONS['title'], 'description': OPTIONS['description']}, 'status': {'privacyStatus': 'private', 'uploadStatus': 'processed'}}
        self.a.owned = lambda *_: copy.deepcopy(self.video)
        self.engine = UploadEngine(self.journal, lambda _: self.a, lambda _, offset, size: b'x' * size, clock=lambda: self.clock[0])
        self.m = manifest()
    def advance(self): self.clock[0] += 100; return self.engine.step(self.m)
    def test_multichunk_upload_commits_session_and_probes_before_every_chunk(self):
        self.setup_engine(); first = self.advance(); self.assertEqual(first['progress']['stage'], 'uploading')
        second = self.advance(); self.assertEqual(second['reference'], VIDEO); self.assertEqual(second['progress']['stage'], 'uploaded_private')
        final = self.advance(); self.assertEqual(final['state'], 'verified'); self.assertEqual(final['progress']['stage'], 'processed_private')
        ranges = [x[2]['headers']['Content-Range'] for x in self.wire.calls if 'upload_id=' in x[1]]
        self.assertEqual(ranges, [f'bytes */{MEDIA["bytes"]}', f'bytes 0-{CHUNK_SIZE - 1}/{MEDIA["bytes"]}', f'bytes */{MEDIA["bytes"]}', f'bytes {CHUNK_SIZE}-{MEDIA["bytes"] - 1}/{MEDIA["bytes"]}'])
        self.assertNotIn('sessionCiphertext', json.dumps(final)); self.assertNotIn('synthetic-token', json.dumps(final))
        self.assertEqual(sum(x[0] == 'POST' for x in self.wire.calls), 1)

    def test_chunk_timeout_reconciles_acknowledged_offset_without_duplicate(self):
        self.setup_engine(); self.wire.fault = 'chunk-timeout'
        first = self.advance(); self.assertEqual(first['state'], 'uncertain'); self.assertEqual(self.wire.offset, CHUNK_SIZE)
        second = self.advance(); self.assertEqual(second['reference'], VIDEO); self.assertEqual(self.wire.offset, MEDIA['bytes'])
        self.assertEqual(sum(x[0] == 'POST' for x in self.wire.calls), 1)

    def test_uncertain_initialization_never_creates_replacement_upload(self):
        self.setup_engine(); self.wire.fault = 'initial-timeout'
        self.assertEqual(self.advance()['state'], 'uncertain')
        self.assertEqual(self.advance()['state'], 'uncertain')
        self.assertEqual(sum(x[0] == 'POST' for x in self.wire.calls), 1)

    def test_idempotency_key_rejects_changed_content(self):
        self.setup_engine(); self.advance(); self.m['publishOptions']['title'] = 'Different'
        with self.assertRaises(AlphaError): self.advance()

    def test_cancellation_stops_bytes_without_deletion(self):
        self.setup_engine(); self.advance(); before = len(self.wire.calls)
        result = self.engine.step(self.m, cancel=True)
        self.assertEqual(result['state'], 'canceled'); self.assertEqual(len(self.wire.calls), before)
        normalized = normalize_result(result, {'manifest': {'platform': 'YouTube'}, 'cancelRequested': True}, True)
        self.assertEqual(normalized['state'], 'canceled')

    def test_no_legacy_container_required_for_durable_progress(self):
        self.setup_engine(); result = self.advance()
        normalized = normalize_result(result, {'manifest': {'platform': 'YouTube'}}, True)
        self.assertEqual(normalized['progress']['version'], 2)
        self.assertEqual(normalized['state'], 'provider_accepted')
        result['progress']['bytesSent'] = MEDIA['bytes'] + 1
        self.assertEqual(normalize_result(result, {'manifest': {'platform': 'YouTube'}}, True)['state'], 'uncertain')

    def test_missing_journal_reconciliation_never_opens_a_session(self):
        self.setup_engine()
        result = self.engine.step(self.m, allow_initialize=False)
        self.assertEqual(result['state'], 'held'); self.assertEqual(self.wire.calls, [])
        self.assertEqual(self.journal.saves, [])

    def test_upload_revocation_purge_is_not_recreated_by_error_handling(self):
        self.setup_engine()
        self.a.provider.transport = lambda *_args, **_kwargs: {'status': 401}
        self.a.on_error = lambda *_: self.journal.states.clear()
        result = self.advance()
        self.assertEqual(result['state'], 'held'); self.assertEqual(self.journal.states, {})
        self.assertEqual(result['progress']['errorCategory'], 'revoked_oauth')

    def test_disconnect_during_initialization_never_restores_session_or_sends_bytes(self):
        self.setup_engine()
        original = self.a.provider.transport
        def disconnect_after_response(*args, **kwargs):
            response = original(*args, **kwargs)
            self.journal.revoked = True
            self.journal.states.clear()
            return response
        self.a.provider.transport = disconnect_after_response
        errors = []
        self.a.on_error = lambda *_: errors.append('provider revocation')
        result = self.advance()
        self.assertEqual(result['state'], 'held')
        self.assertEqual(result['progress']['errorCategory'], 'revoked_oauth')
        self.assertEqual(self.journal.states, {})
        self.assertEqual([item[0] for item in self.wire.calls], ['POST'])
        self.assertEqual(errors, [])

    def test_reconnect_during_initialization_preserves_new_authority_and_purge(self):
        self.setup_engine()
        original = self.a.provider.transport
        def reconnect_after_response(*args, **kwargs):
            response = original(*args, **kwargs)
            self.journal.generation += 1
            self.journal.states.clear()
            return response
        self.a.provider.transport = reconnect_after_response
        errors = []
        self.a.on_error = lambda *_: errors.append('purged new grant')
        result = self.advance()
        self.assertEqual(result['progress']['errorCategory'], 'authorization_changed')
        self.assertEqual(self.journal.states, {})
        self.assertEqual([item[0] for item in self.wire.calls], ['POST'])
        self.assertEqual(errors, [])

    def test_disconnect_during_status_probe_stops_the_next_chunk(self):
        self.setup_engine(); self.advance()
        before = len(self.wire.calls)
        original = self.a.provider.transport
        def disconnect_after_response(*args, **kwargs):
            response = original(*args, **kwargs)
            self.journal.revoked = True
            self.journal.states.clear()
            return response
        self.a.provider.transport = disconnect_after_response
        result = self.advance()
        self.assertEqual(result['state'], 'held')
        self.assertEqual(self.journal.states, {})
        self.assertEqual(len(self.wire.calls), before + 1)
        self.assertTrue(self.wire.calls[-1][2]['headers']['Content-Range'].startswith('bytes */'))

    def test_disconnect_during_media_read_stops_chunk_dispatch(self):
        self.setup_engine()
        def reader(_manifest, _offset, size):
            self.journal.revoked = True
            self.journal.states.clear()
            return b'x' * size
        self.engine.media_reader = reader
        result = self.advance()
        self.assertEqual(result['state'], 'held')
        self.assertEqual(self.journal.states, {})
        self.assertEqual([item[0] for item in self.wire.calls], ['POST', 'PUT'])
        self.assertTrue(self.wire.calls[-1][2]['headers']['Content-Range'].startswith('bytes */'))

    def test_disconnect_during_quota_admission_stops_initialization(self):
        self.setup_engine()
        def usage(*_):
            self.journal.revoked = True
            self.journal.states.clear()
        self.a.account_usage = usage
        result = self.advance()
        self.assertEqual(result['state'], 'held')
        self.assertEqual(self.journal.states, {})
        self.assertEqual(self.wire.calls, [])

    def test_finalization_write_rechecks_authority_after_its_own_admission(self):
        self.setup_engine()
        self.engine.finalize = lambda _key, _state, _video, api, _save: api.call(
            'videos.update', {'part': 'status'}, {'id': VIDEO, 'status': {'privacyStatus': 'public'}})
        self.journal.states[('one', 'connection-one', 'exact-key')] = {
            'manifestDigest': hashlib.sha256(json.dumps(self.m, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'stage': 'uploaded_private', 'videoId': VIDEO, 'bytesSent': MEDIA['bytes'], 'totalBytes': MEDIA['bytes']}
        def usage(*_):
            self.journal.revoked = True
            self.journal.states.clear()
        self.a.account_usage = usage
        result = self.advance()
        self.assertEqual(result['state'], 'held')
        self.assertEqual(self.journal.states, {})
        self.assertEqual(self.wire.calls, [])

    def test_cancellation_write_rechecks_authority_after_its_own_admission(self):
        self.setup_engine()
        self.video['status']['publishAt'] = '2099-01-01T00:00:00Z'
        self.journal.states[('one', 'connection-one', 'exact-key')] = {
            'manifestDigest': hashlib.sha256(json.dumps(self.m, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'stage': 'native_scheduled', 'videoId': VIDEO, 'bytesSent': MEDIA['bytes'],
            'totalBytes': MEDIA['bytes'], 'steps': {}}
        def usage(*_):
            self.journal.revoked = True
            self.journal.states.clear()
        self.a.account_usage = usage
        result = self.engine.step(self.m, cancel=True)
        self.assertEqual(result['state'], 'held')
        self.assertEqual(self.journal.states, {})
        self.assertEqual(self.wire.calls, [])

    def test_normal_access_token_refresh_retains_generation_and_resumes_session(self):
        self.setup_engine(); self.advance()
        self.a.grant['accessToken'] = json.dumps({'v': 1, 'at': 'synthetic-refreshed-token'})
        result = self.advance()
        self.assertEqual(result['reference'], VIDEO)
        self.assertEqual(result['progress']['stage'], 'uploaded_private')
        self.assertEqual(sum(item[0] == 'POST' for item in self.wire.calls), 1)

    def test_known_session_rate_limit_is_backed_off_without_new_initialization(self):
        self.setup_engine(); self.advance()
        original = self.a.provider.transport
        self.a.provider.transport = lambda *_args, **_kwargs: {'status': 429}
        result = self.advance()
        self.assertEqual(result['state'], 'uncertain'); self.assertGreater(result['progress']['retryAt'], self.clock[0])
        self.a.provider.transport = original
        self.advance()
        self.assertEqual(sum(x[0] == 'POST' for x in self.wire.calls), 1)


class PublicationGuards(unittest.TestCase):
    def setup_finalizer(self):
        self.calls = []
        self.state = {'options': copy.deepcopy(OPTIONS) | {'privacyStatus': 'public'}, 'videoId': VIDEO,
                      'stage': 'processed_private', 'steps': {}}
        self.current = upload_body(self.state['options']) | {'id': VIDEO}
        self.current['status'].update(uploadStatus='processed')
        self.current['processingDetails'] = {'processingStatus': 'succeeded'}
        class DB:
            def __enter__(this): return this
            def __exit__(this, *_): return False
            def cursor(this): return this
            def execute(this, *_): pass
            def fetchone(this): return ({'phase2': {'assets': []}},)
        self.service = YouTubeCreatorService.__new__(YouTubeCreatorService)
        self.service.service = SimpleNamespace(connection_factory=DB)
        self.service.clock = lambda: 1_000_000_000
        self.a = api(Wire())
        def call(method, params=None, body=None):
            self.calls.append(method)
            if method == 'videos.update':
                self.current['status'].update(body['status'])
                return copy.deepcopy(self.current)
            raise AssertionError(method)
        self.a.call = call
        self.a.owned = lambda *_: copy.deepcopy(self.current)
        self.finish = lambda: self.service.finalize_upload(('one', 'conn', 'key'), self.state, self.current, self.a, lambda *_: None)

    def test_declaration_mismatch_holds_before_publication(self):
        self.setup_finalizer()
        self.current['status']['containsSyntheticMedia'] = True
        result = self.finish()
        self.assertEqual(result['errorCategory'], 'youtube_declaration_readback_mismatch')
        self.assertEqual(result['stage'], 'held'); self.assertEqual(self.calls, [])

    def test_title_mismatch_holds_before_publication(self):
        self.setup_finalizer(); self.current['snippet']['title'] = 'Externally changed'
        result = self.finish()
        self.assertEqual(result['errorCategory'], 'youtube_metadata_readback_mismatch')
        self.assertEqual(self.calls, [])

    def test_missing_thumbnail_receipt_never_repeats_upload_or_publishes(self):
        self.setup_finalizer(); self.state['options']['thumbnailAssetId'] = 'image'
        self.state['steps']['thumbnail'] = {'status': 'accepted'}
        result = self.finish()
        self.assertEqual(result['stage'], 'held')
        self.assertEqual(result['errorCategory'], 'thumbnail_receipt_unavailable')
        self.assertEqual(self.calls, [])

    def test_caption_processing_precedes_visibility(self):
        self.setup_finalizer(); self.state['options']['captionTracks'] = [{'language': 'en'}]
        self.state['steps']['caption:0'] = {'status': 'accepted', 'resourceId': 'track'}
        self.a.call = lambda method, *_: self.calls.append(method) or {'items': [{'snippet': {'status': 'syncing'}}]}
        result = self.finish()
        self.assertEqual(result['stage'], 'processing'); self.assertEqual(self.calls, ['captions.list'])

    def test_exact_declarations_and_metadata_can_release_visibility(self):
        self.setup_finalizer(); result = self.finish()
        self.assertEqual(result['stage'], 'published')
        self.assertEqual(self.calls, ['videos.update'])
        self.assertEqual(self.current['status']['selfDeclaredMadeForKids'], OPTIONS['madeForKids'])


class FinancialReportGuards(unittest.TestCase):
    def service(self):
        from postriff_phase2.youtube.reporting import NON_MONETARY_TYPES
        ordinary = sorted(NON_MONETARY_TYPES)[0]
        self.calls = []
        a = api(Wire())
        def call(method, params=None, *_):
            self.calls.append(method)
            if method == 'reporting.jobs.list': return {'jobs': [{'id': 'ordinary', 'reportTypeId': ordinary}, {'id': 'financial', 'reportTypeId': 'financial-type'}]}
            if method == 'reporting.jobs.get': return {'id': 'financial', 'reportTypeId': 'financial-type'}
            raise AssertionError(method)
        a.call = call
        service = YouTubeCreatorService.__new__(YouTubeCreatorService)
        service._read_guard = lambda *_: a
        service._allow = lambda *_args, **_kwargs: None
        service._member = lambda *_args, **_kwargs: None
        service.settings = lambda *_: ({'monetary': False}, {})
        return service

    def test_default_report_jobs_hide_financial_and_unclassified_types(self):
        body = self.service().read('workspace', 'token', 'conn', 'report_jobs')
        self.assertEqual([x['id'] for x in body['jobs']], ['ordinary'])

    def test_financial_report_content_never_requested_without_permission(self):
        with self.assertRaises(AlphaError): self.service().read('workspace', 'token', 'conn', 'reports', {'jobId': 'financial'})
        self.assertEqual(self.calls, ['reporting.jobs.get'])

    def test_explicit_financial_list_requires_separate_authorization(self):
        with self.assertRaises(AlphaError): self.service().read('workspace', 'token', 'conn', 'report_jobs', {'includeMonetary': True})
        self.assertEqual(self.calls, [])


class RecoveryApprovalGuards(unittest.TestCase):
    def test_only_exact_original_youtube_approver_can_extend_dispatch_window(self):
        from postriff_phase2.contracts import digest
        from postriff_phase2.hosted_worker import PostgresWorker
        worker = PostgresWorker.__new__(PostgresWorker)
        worker.clock = lambda: 1000
        worker.commands = SimpleNamespace(engine=SimpleNamespace(current=lambda *_: True, channel_state=lambda *_: 'Ready for posting'))
        cur = SimpleNamespace(execute=lambda *_: None, fetchone=lambda: ('owner', True))
        state = {'phase2': {'channels': [{'id': 'conn'}]}}
        manifest = {'platform': 'YouTube', 'channelId': 'conn', 'actor': 'owner', 'expiresAt': 999}
        job = {'manifest': manifest, 'approvedBy': 'owner', 'approvalDigest': digest(manifest)}
        lease = {'approvedBy': 'owner', 'digest': job['approvalDigest'], 'approvedAt': 1000, 'expiresAt': 2000}
        with patch('postriff_phase2.billing.require_publishing'):
            self.assertFalse(worker._approved(cur, 'workspace', state, job))
            job['youtubeRecoveryApproval'] = lease
            self.assertTrue(worker._approved(cur, 'workspace', state, job))
            for mutation in ({'digest': 'different'}, {'approvedBy': 'another-owner'}, {'expiresAt': 999}, {'expiresAt': 1000 + 37 * 3600}):
                job['youtubeRecoveryApproval'] = lease | mutation
                self.assertFalse(worker._approved(cur, 'workspace', state, job))
            job['youtubeRecoveryApproval'] = lease
            manifest['platform'] = 'Threads'; job['approvalDigest'] = digest(manifest); job['youtubeRecoveryApproval']['digest'] = job['approvalDigest']
            self.assertFalse(worker._approved(cur, 'workspace', state, job))


class OwnershipTests(unittest.TestCase):
    def test_review_plan_survives_jsonb_object_key_reordering(self):
        from postriff_phase2.youtube.service import fingerprint
        a = api(Wire())
        a.owned = lambda *_: {'id': VIDEO, 'snippet': {'channelId': CHANNEL, 'title': 'Old', 'description': 'Keep', 'categoryId': '22'},
                             'status': {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False, 'containsSyntheticMedia': False}}
        snippet, status = {'title': 'New'}, {'privacyStatus': 'private'}
        first = a.plan('video.edit', {'id': VIDEO, 'patch': {'snippet': snippet, 'status': status}})
        second = a.plan('video.edit', {'id': VIDEO, 'patch': {'status': status, 'snippet': snippet}})
        self.assertEqual(fingerprint(first), fingerprint(second))

    def test_owned_resource_requires_connected_channel_id(self):
        def wire(*_, **__): return {'status': 200, 'body': {'items': [{'id': VIDEO, 'snippet': {'channelId': OTHER}}]}}
        with self.assertRaises(AlphaError): api(wire).owned('videos', VIDEO)

    def test_unsupported_method_and_partner_impersonation_fail_before_network(self):
        wire = Wire(); a = api(wire)
        with self.assertRaises(AlphaError): a.call('communityPosts.insert')
        with self.assertRaises(AlphaError): a.call('videos.list', {'part': 'snippet', 'id': VIDEO, 'onBehalfOfContentOwner': 'foreign'})
        with self.assertRaises(AlphaError): a.call('videos.list', {'part': 'snippet', 'maxResults': 999999})
        self.assertEqual(wire.calls, [])

    def test_upload_scope_alone_cannot_edit_or_moderate(self):
        wire = Wire(); a = api(wire, scopes=(READ, UPLOAD))
        with self.assertRaises(AlphaError): a.call('videos.update', {'part': 'snippet'}, {'id': VIDEO})
        with self.assertRaises(AlphaError): a.call('comments.insert', {'part': 'snippet'}, {})
        self.assertEqual(wire.calls, [])

    def test_chat_delete_and_poll_close_require_observed_same_chat_resource(self):
        a = api(Wire())
        a.owned_chat = lambda *_: {'id': VIDEO}
        for action in ('chat.delete', 'chat.close_poll', 'chat.remove_moderator', 'chat.unban'):
            with self.assertRaises(AlphaError): a.plan(action, {'id': 'foreign', 'liveChatId': 'chat', 'broadcastId': VIDEO})
        a.chat_resource = lambda _kind, ident, chat: ident == 'observed' and chat == 'chat'
        self.assertEqual(a.plan('chat.delete', {'id': 'observed', 'liveChatId': 'chat', 'broadcastId': VIDEO})['method'], 'liveChatMessages.delete')

    def test_stream_metadata_preserves_immutable_ingestion_and_rejects_mutation(self):
        a = api(Wire())
        stream = {'id': 'stream-one', 'snippet': {'channelId': CHANNEL, 'title': 'Keep', 'description': 'Keep description'},
                  'cdn': {'ingestionType': 'rtmp', 'resolution': '1080p', 'frameRate': '30fps'}, 'contentDetails': {'isReusable': True}}
        a.owned = lambda *_: copy.deepcopy(stream)
        plan = a.plan('stream.edit', {'id': 'stream-one', 'patch': {'snippet': {'title': 'New'}}})
        self.assertEqual(plan['body']['cdn'], stream['cdn'])
        self.assertEqual(plan['body']['snippet']['description'], 'Keep description')
        with self.assertRaises(AlphaError): a.plan('stream.edit', {'id': 'stream-one', 'patch': {'cdn': {'ingestionType': 'dash'}}})

    def test_live_transition_requires_an_active_bound_stream(self):
        a = api(Wire())
        a.owned = lambda *_: {'id': VIDEO, 'status': {'lifeCycleStatus': 'ready'}, 'contentDetails': {}}
        with self.assertRaises(AlphaError): a.plan('broadcast.transition', {'id': VIDEO, 'broadcastStatus': 'live'})


if __name__ == '__main__': unittest.main()
