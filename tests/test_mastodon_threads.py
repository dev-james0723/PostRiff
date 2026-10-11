"""Synthetic failure injection for the real durable thread publisher; no live acceptance."""
import copy
import html
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.mastodon_publishing import advance, can_resume, checked_progress
from postriff_phase2.mastodon_threads import parts, reconcile
from postriff_phase2.outcomes import normalize_result


class ThreadPublishingTests(unittest.TestCase):
    def setUp(self):
        self.now = 1791690000
        self.calls, self.saved, self.posts = [], [], {}
        self.write_fault = None; self.read_fault = None; self.max_characters = 500
        self.grant = {'accessToken': 'synthetic', 'providerAccountId': '10@mastodon.social', 'scopes': ['write:statuses', 'write:media']}
        self.manifest = {'platform': 'Mastodon', 'workspaceId': 'w', 'channelId': 'c', 'providerAccountId': '10@mastodon.social',
                         'idempotencyKey': 'approved-thread', 'payload': {'text': 'First paragraph\n\nSecond paragraph', 'threadParts': ['Second part', 'Third part']},
                         'publishOptions': {'visibility': 'unlisted', 'spoiler_text': 'Preview warning', 'sensitive': True, 'language': 'en'}, 'media': []}
        def api(session, method, path, **kwargs):
            self.calls.append((method, path, copy.deepcopy(kwargs)))
            if method == 'GET':
                if self.read_fault:
                    fault, self.read_fault = self.read_fault, None
                    return fault
                return {'status': 200, 'body': copy.deepcopy(self.posts[path.rsplit('/', 1)[-1]])}
            self.assertEqual(self.saved[-1][0]['stage'], 'publish_attempted' if not self.posts else 'thread_publish_attempted')
            self.assertTrue(self.saved[-1][1]['before_external'])
            if self.write_fault:
                fault, self.write_fault = self.write_fault, None
                if isinstance(fault, Exception): raise fault
                return fault
            body = kwargs['body']; identifier = str(100 + len(self.posts))
            self.posts[identifier] = {'id': identifier, 'account': {'id': '10'},
                'content': '<p>' + html.escape(body['status']).replace('\n\n', '</p><p>').replace('\n', '<br>') + '</p>',
                'visibility': body['visibility'], 'spoiler_text': body['spoiler_text'], 'sensitive': body['sensitive'],
                'language': body.get('language'), 'in_reply_to_id': body.get('in_reply_to_id'), 'media_attachments': [],
                'url': 'https://mastodon.social/@alice/' + identifier}
            return {'status': 200, 'body': {'id': identifier}}
        self.provider = SimpleNamespace(publish_required={'write:statuses', 'write:media'}, session=lambda _: {'instance': 'mastodon.social'}, api=api,
            transport=lambda method, url, **kw: {'status': 404} if '/.well-known/' in url else {'status': 200, 'body': {'version': '4.5.7', 'configuration': {'statuses': {'max_characters': self.max_characters}}}})
        self.social = SimpleNamespace(_provider=lambda _: self.provider, oauth=SimpleNamespace(token_for_worker=lambda *_: self.grant), assets=None)

    def checkpoint(self, progress, **kwargs): self.saved.append((copy.deepcopy(progress), kwargs))
    def publish(self, progress=None, checkpoint=None):
        return advance(self.social, self.manifest, {'progress': progress}, checkpoint or self.checkpoint, lambda: self.now)
    def lookup(self, progress): return reconcile(self.provider, self.grant, self.manifest, checked_progress(progress, self.manifest), self.checkpoint, lambda: self.now)
    def all_parts(self):
        result = self.publish()
        for _ in self.manifest['payload']['threadParts']: result = self.publish(result['progress'])
        return result

    def test_each_child_has_committed_intent_distinct_key_and_saved_parent(self):
        root = self.publish(); self.assertEqual(root['state'], 'processing')
        self.assertTrue(can_resume({'state': 'processing', 'manifest': self.manifest, 'progress': root['progress']}))
        second = self.publish(root['progress']); final = self.publish(second['progress'])
        writes = [kwargs for method, _, kwargs in self.calls if method == 'POST']
        self.assertEqual([w['body'].get('in_reply_to_id') for w in writes], [None, '100', '101'])
        self.assertEqual(len({w['headers']['Idempotency-Key'] for w in writes}), 3)
        self.assertEqual(final['state'], 'provider_accepted'); self.assertEqual(final['progress']['threadReferences'], ['100', '101', '102'])
        verified = self.lookup(final['progress'])
        self.assertEqual(verified['state'], 'processing')
        self.assertEqual(normalize_result(verified, {'manifest': self.manifest}, True)['state'], 'processing')
        verified = self.lookup(verified['progress']); self.assertEqual(verified['state'], 'processing')
        verified = self.lookup(verified['progress']); self.assertEqual(verified['state'], 'verified')
        self.assertEqual(verified['progress']['threadVerified'], 3)
        self.assertEqual(normalize_result(verified, {'manifest': self.manifest}, True)['state'], 'verified')
        self.assertEqual(len([m for m, _, _ in self.calls if m == 'POST']), 3)

    def test_unknown_child_write_blocks_all_resends_after_restart(self):
        root = self.publish(); self.write_fault = TimeoutError('synthetic interruption')
        with self.assertRaises(TimeoutError): self.publish(root['progress'])
        progress = self.saved[-1][0]; calls = len(self.calls)
        self.assertEqual(progress['stage'], 'thread_publish_attempted')
        self.assertFalse(can_resume({'state': 'submitting', 'manifest': self.manifest, 'progress': progress}))
        self.assertEqual(self.publish(progress)['state'], 'uncertain')
        self.assertEqual(self.lookup(progress)['state'], 'uncertain'); self.assertEqual(len(self.calls), calls)
        self.assertEqual(progress['threadReferences'], ['100'])

    def test_cancel_or_revocation_at_intent_prevents_child_write(self):
        root = self.publish(); calls = len(self.calls)
        def denied(progress, **kwargs):
            if kwargs.get('before_external'): raise AlphaError('Approval canceled', 409)
        with self.assertRaises(AlphaError): self.publish(root['progress'], denied)
        self.assertEqual(len(self.calls), calls + 1)  # only the read-only parent lookup
        self.assertEqual(len(self.posts), 1)

    def test_rate_refusal_keeps_ids_and_cooldown_then_sends_only_unsent_child(self):
        root = self.publish(); self.write_fault = {'status': 429, 'headers': {'Retry-After': '120'}}
        waiting = self.publish(root['progress']); calls = len(self.calls)
        self.assertEqual(waiting['progress']['threadReferences'], ['100'])
        self.assertEqual(waiting['progress']['stage'], 'thread_wait')
        self.assertEqual(self.publish(waiting['progress'])['state'], 'processing'); self.assertEqual(len(self.calls), calls)
        self.now = waiting['progress']['retryAt'] + 1
        next_part = self.publish(waiting['progress']); self.assertEqual(next_part['progress']['threadReferences'], ['100', '101'])
        self.assertEqual(len(self.posts), 2)

    def test_edited_or_wrong_account_parent_stops_before_any_child(self):
        root = self.publish()
        for update in ({'content': '<p>Edited without this approval</p>'}, {'account': {'id': '11'}}, {'sensitive': False}):
            original = copy.deepcopy(self.posts['100']); self.posts['100'].update(update)
            self.assertEqual(self.publish(root['progress'])['state'], 'held'); self.assertEqual(len(self.posts), 1)
            self.posts['100'] = original
        self.grant['providerAccountId'] = '11@mastodon.social'
        calls = len(self.calls); self.assertEqual(self.publish(root['progress'])['state'], 'held'); self.assertEqual(len(self.calls), calls)

    def test_all_children_obey_server_limit_before_root_write(self):
        self.max_characters = 60; self.manifest['payload']['threadParts'] = ['x' * 61]
        with self.assertRaises(AlphaError): self.publish()
        self.assertEqual(self.calls, [])
        self.manifest['publishOptions']['scheduled_at'] = '2026-10-11T08:00:00Z'
        with self.assertRaises(AlphaError): parts(self.manifest)

    def test_readback_mismatch_or_partial_evidence_never_verifies_whole_thread(self):
        result = self.all_parts(); self.posts['101']['in_reply_to_id'] = '999'
        first = self.lookup(result['progress']); second = self.lookup(first['progress'])
        self.assertEqual(second['state'], 'uncertain'); self.assertEqual(second['progress']['threadVerified'], 1)
        forged = {**first, 'state': 'verified', 'verification': 'provider_lookup'}
        self.assertEqual(normalize_result(forged, {'manifest': self.manifest}, True)['state'], 'uncertain')

    def test_lookup_throttle_saves_progress_and_never_writes(self):
        result = self.all_parts(); self.read_fault = {'status': 429, 'headers': {'Retry-After': '120'}}
        waiting = self.lookup(result['progress']); writes = len([m for m, _, _ in self.calls if m == 'POST'])
        self.assertEqual(waiting['state'], 'processing'); self.assertGreaterEqual(waiting['progress']['retryAt'], self.now + 120)
        self.lookup(waiting['progress']); self.assertEqual(len([m for m, _, _ in self.calls if m == 'POST']), writes)

    def test_invalid_duplicate_or_unhashable_thread_ids_are_rejected(self):
        result = self.all_parts()
        for refs in (['100', '100', '102'], ['100', {}, '102']):
            with self.assertRaises(AlphaError): checked_progress({**result['progress'], 'threadReferences': refs}, self.manifest)


class ThreadPlanningTests(unittest.TestCase):
    def test_agent_prepares_only_existing_review_with_no_automatic_warning_acknowledgment(self):
        from postriff_phase2.mastodon_agent_tools import action_prepare
        state = {'phase2': {'channels': [{'id': 'connection', 'platform': 'Mastodon'}]},
                 'variants': [{'id': 'draft', 'platform': 'Mastodon', 'text': 'Reviewed root', 'warnings': []}]}
        mutate = Mock(return_value={'state': {'phase2': {'reviews': [{'id': 'review'}]}}})
        ctx = SimpleNamespace(request_text='Prepare my Mastodon thread', check_cancelled=lambda: None,
                              service=SimpleNamespace(repository=SimpleNamespace(get=lambda *_: {'state': state, 'revision': 12}), mutate=mutate),
                              workspace_id='w', token='t')
        args = {'action': 'thread_prepare', 'connectionId': 'connection', 'variantId': 'draft', 'threadParts': ['Explicit second'],
                'localTime': '2026-10-12T12:00', 'timeZone': 'UTC'}
        result = action_prepare(ctx, args)
        self.assertFalse(result['executed']); self.assertEqual(result['reviewId'], 'review')
        self.assertEqual(mutate.call_args.args[3], 'p2_review'); self.assertEqual(mutate.call_args.args[4]['threadParts'], ['Explicit second'])
        state['variants'][0]['warnings'] = ['Confirm unsupported claim']; mutate.reset_mock()
        self.assertTrue(action_prepare(ctx, args)['needsUser']); mutate.assert_not_called()
        ctx.request_text = 'Prepare my Mastodon post'
        with self.assertRaises(AlphaError): action_prepare(ctx, args)
