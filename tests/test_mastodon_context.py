"""Synthetic bounded context/agent contracts only; no live Mastodon calls."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.mastodon_context import page
from postriff_phase2.mastodon_management import MastodonManagement


def post(identifier, **changes):
    return {'id': str(identifier), 'account': {'id': '10'}, 'visibility': 'public',
            'sensitive': False, 'spoiler_text': '', 'content': '<p>Public text</p>', **changes}


class ContextTests(unittest.TestCase):
    def manager(self, target=None, context=None):
        manager = object.__new__(MastodonManagement)
        provider = SimpleNamespace(api=Mock(side_effect=[
            {'status': 200, 'body': target or post(123)},
            {'status': 200, 'body': context or {'ancestors': [], 'descendants': []},
             'headers': {'Mastodon-Async-Refresh': 'https://unsafe.invalid/do-not-follow'}}]))
        manager._grant = Mock(return_value=(provider, {'scopes': ['read:statuses']}, {'instance': 'social.example'}))
        manager._read_fence = Mock()
        return manager, provider

    def test_public_snapshot_paging_never_skips_long_excerpts_or_exports_private_data(self):
        rows = [post(i, content='<p>' + '漢' * 1000 + '</p>') for i in range(1, 41)]
        rows += [post(50, visibility='private', content='PRIVATE'), post(51, visibility='direct', content='DIRECT'),
                 post(52, visibility=None, content='UNKNOWN'), post(53, spoiler_text='CW', content='CW_BODY'),
                 post(54, sensitive=True, content='SENSITIVE')]
        context = {'ancestors': [], 'descendants': rows}
        seen, cursor = [], None
        for _ in range(50):
            result = page(post(123), context, cursor)
            self.assertLessEqual(len(result['posts']), 20)
            self.assertLessEqual(len(json.dumps(result['posts'], ensure_ascii=False).encode()), 9002)
            seen += [r['postId'] for r in result['posts']]
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertNotIn('CW_BODY', json.dumps(result))
            cursor = result['nextCursor']
            if cursor is None:
                break
        self.assertIsNone(cursor)
        self.assertEqual(seen, [str(i) for i in range(1, 41)])

    def test_root_visibility_defaults_deny_and_cw_sensitive_roots_are_excluded(self):
        missing = post(123)
        missing.pop('visibility')
        for target in (missing, post(123, visibility=None), post(123, visibility='private'),
                       post(123, visibility='direct'), post(123, sensitive=True), post(123, spoiler_text='CW')):
            with self.subTest(target=target), self.assertRaises(AlphaError):
                page(target, {'ancestors': [], 'descendants': []})

    def test_cw_metadata_requires_an_explicit_empty_string(self):
        missing = post(1)
        missing.pop('spoiler_text')
        malformed = [missing] + [post(1, spoiler_text=value) for value in (None, False, 0, [], {}, 'CW', ' ')]
        for target in malformed:
            with self.subTest(target=target):
                with self.assertRaises(AlphaError):
                    page(target, {'ancestors': [], 'descendants': []})
                result = page(post(123), {'ancestors': [], 'descendants': [target]})
                self.assertEqual(result['posts'], [])
        result = page(post(123), {'ancestors': [], 'descendants': [post(1, spoiler_text='')]})
        self.assertEqual([row['postId'] for row in result['posts']], ['1'])

    def test_cursor_is_snapshot_tenant_connection_and_instance_bound(self):
        context = {'ancestors': [], 'descendants': [post(i) for i in range(1, 30)]}
        result = page(post(123), context, binding=['workspace', 'connection', 'social.example'])
        self.assertIsNotNone(result['nextCursor'])
        with self.assertRaises(AlphaError):
            page(post(123), context, result['nextCursor'], binding=['foreign', 'connection', 'social.example'])
        context['descendants'][0]['content'] = 'Changed'
        with self.assertRaises(AlphaError):
            page(post(123), context, result['nextCursor'], binding=['workspace', 'connection', 'social.example'])

    def test_scan_bounds_and_untrusted_url_cursors(self):
        result = page(post(123), {'ancestors': [], 'descendants': [post(i) for i in range(1, 102)]})
        self.assertTrue(result['truncated'])
        for cursor in ('https://127.0.0.1', 'a' * 64 + ':999', '', 0):
            with self.subTest(cursor=cursor), self.assertRaises(AlphaError):
                page(post(123), {'ancestors': [], 'descendants': []}, cursor)

    def test_cross_workspace_and_unsafe_target_fail_before_provider_io(self):
        manager, provider = self.manager()
        manager._grant.side_effect = AlphaError('Forbidden', 403)
        with self.assertRaises(AlphaError):
            manager.thread_context('foreign', 'actor', 'connection', '123')
        provider.api.assert_not_called()
        manager._grant.reset_mock()
        with self.assertRaises(AlphaError):
            manager.thread_context('workspace', 'actor', 'connection', 'https://127.0.0.1/statuses/123')
        manager._grant.assert_not_called()

    def test_private_target_stops_before_context_and_revocation_fences_return(self):
        manager, provider = self.manager(target=post(123, visibility='private', content='PRIVATE'))
        with self.assertRaises(AlphaError):
            manager.thread_context('w', 'actor', 'connection', '123')
        self.assertEqual(provider.api.call_count, 1)
        manager, provider = self.manager()
        manager._read_fence.side_effect = AlphaError('Connection changed', 409)
        with self.assertRaises(AlphaError):
            manager.thread_context('w', 'actor', 'connection', '123')
        self.assertEqual(provider.api.call_count, 2)

    def test_same_instance_read_does_not_follow_async_refresh_header(self):
        manager, provider = self.manager()
        result = manager.thread_context('w', 'actor', 'connection', '123')
        self.assertTrue(result['upstreamRefreshPending'])
        self.assertNotIn('unsafe.invalid', json.dumps(result))
        self.assertEqual([call.args[2] for call in provider.api.call_args_list],
                         ['/api/v1/statuses/123', '/api/v1/statuses/123/context'])
        manager._read_fence.assert_called_once()

    def test_agent_requires_current_human_thread_request_and_exact_post_id(self):
        from postriff_phase2.mastodon_agent_tools import thread_context
        ctx = SimpleNamespace(request_text='', service=object(), workspace_id='w', token='actor',
                              modality='text', check_cancelled=lambda: None)
        with patch.object(MastodonManagement, '__init__', return_value=None), \
                patch.object(MastodonManagement, 'thread_context', return_value={'posts': []}) as read:
            for text in ('Connect my Mastodon account', 'Show Mastodon thread 124',
                         'Do not show Mastodon thread 123', 'How to read Mastodon thread 123?',
                         '"Show Mastodon thread 123"'):
                ctx.request_text = text
                with self.subTest(text=text), self.assertRaises(AlphaError):
                    thread_context(ctx, {'connectionId': 'connection', 'postId': '123'})
            read.assert_not_called()
            ctx.request_text = 'Show Mastodon thread context for post 123'
            result = thread_context(ctx, {'connectionId': 'connection', 'postId': '123'})
            self.assertFalse(result['externalActionsExecuted'])
            read.assert_called_once_with('w', 'actor', 'connection', '123', None)
