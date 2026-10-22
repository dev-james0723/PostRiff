"""Synthetic Mastodon Inbox contracts: reply ingestion and one approved reply. No live Mastodon calls."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from postriff_phase2 import mastodon_inbox
from postriff_phase2.audience import AudienceService

OWNER = '10@social.example'


def status(identifier, account_id='20', acct='alice', **changes):
    return {'id': str(identifier), 'account': {'id': account_id, 'acct': acct}, 'visibility': 'public', 'sensitive': False,
            'spoiler_text': '', 'content': '<p>Nice &amp; clear</p>', 'created_at': '2026-10-21T22:00:00.000Z', **changes}


def provider(*responses):
    return SimpleNamespace(session=lambda token: {'at': 'T', 'instance': 'social.example'}, api=Mock(side_effect=list(responses)))


class Replies(unittest.TestCase):
    def test_only_other_peoples_public_uncautioned_replies_are_kept(self):
        rows = [status(1), status(2, acct='bob@remote.example', visibility='unlisted'),
                status(3, visibility='private'), status(4, visibility='direct'), status(5, sensitive=True),
                status(6, spoiler_text='CW'), status(7, account_id='10', acct='me'), status('bad')]
        adapter = provider({'status': 200, 'body': {'ancestors': [], 'descendants': rows}})
        ok, items = mastodon_inbox.replies(adapter, 'token', '123', OWNER)
        self.assertTrue(ok)
        self.assertEqual([i['id'] for i in items], ['1', '2'])
        self.assertEqual([i['author'] for i in items], ['alice@social.example', 'bob@remote.example'])
        self.assertEqual(items[0]['text'], 'Nice & clear')
        adapter.api.assert_called_once_with({'at': 'T', 'instance': 'social.example'}, 'GET', '/api/v1/statuses/123/context')

    def test_bad_ids_and_failed_reads_ingest_nothing(self):
        adapter = provider({'status': 503, 'body': {}})
        self.assertEqual(mastodon_inbox.replies(adapter, 'token', '123', OWNER), (False, []))
        self.assertEqual(mastodon_inbox.replies(provider(), 'token', '../1', OWNER), (False, []))

    def test_reply_mentions_the_author_once(self):
        self.assertEqual(mastodon_inbox.addressed('Thanks!', 'alice@social.example'), '@alice@social.example Thanks!')
        self.assertEqual(mastodon_inbox.addressed('@Alice@social.example thanks', 'alice@social.example'), '@Alice@social.example thanks')


class Send(unittest.TestCase):
    TEXT = '@alice@social.example Thanks!'

    def test_verified_only_when_read_back_matches_account_parent_and_text(self):
        readback = {'id': '900', 'account': {'id': '10'}, 'in_reply_to_id': '1', 'content': '<p>@alice@social.example Thanks!</p>'}
        adapter = provider({'status': 200, 'body': {'id': '900'}}, {'status': 200, 'body': readback})
        outcome = mastodon_inbox.send(adapter, 'token', '1', self.TEXT, 'inbox-draft', OWNER)
        self.assertEqual((outcome['state'], outcome['reference']), ('verified', '900'))
        method, path = adapter.api.call_args_list[0].args[1:3]
        kwargs = adapter.api.call_args_list[0].kwargs
        self.assertEqual((method, path), ('POST', '/api/v1/statuses'))
        self.assertEqual(kwargs['headers'], {'Idempotency-Key': 'inbox-draft'})
        self.assertEqual(kwargs['body'], {'status': self.TEXT, 'in_reply_to_id': '1', 'visibility': 'public'})

    def test_mismatched_read_back_stays_submitted_and_errors_never_claim_success(self):
        other = {'id': '900', 'account': {'id': '99'}, 'in_reply_to_id': '1', 'content': self.TEXT}
        self.assertEqual(mastodon_inbox.send(provider({'status': 200, 'body': {'id': '900'}}, {'status': 200, 'body': other}),
                                             'token', '1', self.TEXT, 'k', OWNER)['state'], 'submitted')
        self.assertEqual(mastodon_inbox.send(provider({'status': 500, 'body': {}}), 'token', '1', self.TEXT, 'k', OWNER)['state'], 'uncertain')
        self.assertEqual(mastodon_inbox.send(provider({'status': 403, 'body': {}}), 'token', '1', self.TEXT, 'k', OWNER)['state'], 'failed')


class Preview(unittest.TestCase):
    def preview(self, provider, level, sender_enabled):
        from contextlib import contextmanager
        cur = Mock()
        cur.fetchone.side_effect = [('Thanks!', 'draft', 'conn', provider, '123', '1', 'alice@social.example'), (OWNER,), (level,)]
        @contextmanager
        def transaction(token, workspace):
            yield cur, None, None
        service = AudienceService(SimpleNamespace(transaction=transaction), None, lambda: 1, reply_sender_enabled=sender_enabled)
        return service.reply_preview('ws', 'token', 'draft')

    def test_preview_says_whether_approval_sends_and_includes_the_mention(self):
        sent = self.preview('mastodon', 'Direct', True)
        self.assertTrue(sent['sendsOnApproval'])
        self.assertEqual(sent['manifest']['text'], '@alice@social.example Thanks!')
        for provider, level, enabled in (('mastodon', 'Direct', False), ('mastodon', 'Unsupported', True), ('threads', 'Direct', True)):
            with self.subTest(provider=provider, level=level, enabled=enabled):
                self.assertFalse(self.preview(provider, level, enabled)['sendsOnApproval'])


class Ingestion(unittest.TestCase):
    def test_audience_ingests_mastodon_replies_when_comments_read_is_direct(self):
        adapter = provider({'status': 200, 'body': {'ancestors': [], 'descendants': [status(1), status(3, visibility='private')]}})
        oauth = SimpleNamespace(providers={'mastodon': adapter},
                                token_for_worker=Mock(return_value={'accessToken': 'token', 'providerAccountId': OWNER}))
        cur = Mock()
        cur.fetchone.return_value = ('Direct',)
        result = AudienceService(None, oauth, lambda: 1).ingest_replies(cur, 'ws', 'conn', 'mastodon', '123', 1)
        self.assertEqual(result, {'availability': 'available', 'ingested': 1})
        inserts = [c for c in cur.execute.call_args_list if 'INSERT INTO public.pr_audience_threads' in c.args[0]]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0].args[1][:7], ('ws', 'conn', 'mastodon', '123', '1', 'alice@social.example', 'Nice & clear'))

    def test_nothing_is_read_unless_comments_read_is_direct(self):
        oauth = SimpleNamespace(providers={'mastodon': provider()}, token_for_worker=Mock())
        cur = Mock()
        cur.fetchone.return_value = ('Unsupported',)
        result = AudienceService(None, oauth, lambda: 1).ingest_replies(cur, 'ws', 'conn', 'mastodon', '123', 1)
        self.assertEqual(result['availability'], 'unavailable')
        oauth.token_for_worker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
