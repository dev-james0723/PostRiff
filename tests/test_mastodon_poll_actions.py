"""Native poll contract tests with synthetic provider data; no live voting."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.mastodon_management import MastodonManagement, action_spec
from postriff_phase2.mastodon_poll_actions import choices, snapshot, view, vote_binding


def poll(**changes):
    return {'id': '42', 'expires_at': '2030-01-01T00:00:00Z', 'expired': False, 'multiple': False,
            'voted': False, 'own_votes': [], 'votes_count': 7, 'voters_count': None,
            'options': [{'title': 'First answer', 'votes_count': None}, {'title': 'Second answer', 'votes_count': None}],
            **changes}


class PollActionTests(unittest.TestCase):
    def test_choices_are_distinct_in_range_integers_with_exact_write_and_read_scopes(self):
        self.assertEqual(choices([1, 0]), [0, 1])
        spec = action_spec('poll_vote', {'targetId': '42', 'pollChoices': [1]}, {'polls': True}, now=0)
        self.assertEqual(spec, ('POST', '/api/v1/polls/42/votes', {'choices': [1]}, ('read:statuses', 'write:statuses'), 'approve'))
        for value in (None, '1', [], [True], ['1'], [-1], [64], [0, 0], [0.0], list(range(65))):
            with self.subTest(value=value), self.assertRaises(AlphaError):
                choices(value)
        with self.assertRaises(AlphaError):
            action_spec('poll_vote', {'targetId': '42', 'pollChoices': [1]}, {'polls': False}, now=0)
        with self.assertRaises(AlphaError):
            action_spec('poll_vote', {'targetId': '../admin', 'pollChoices': [1]}, {'polls': True}, now=0)

    def test_read_preserves_unknown_counts_and_discards_unrequested_data(self):
        result = view(poll(votes_count=True, voters_count=-1, content='PRIVATE_STATUS_BODY', own_votes=None), '42')
        self.assertIsNone(result['votesCount']); self.assertIsNone(result['votersCount'])
        self.assertIsNone(result['options'][0]['votes']); self.assertIsNone(result['ownVotes'])
        self.assertNotIn('PRIVATE_STATUS_BODY', json.dumps(result))
        self.assertEqual(view(poll(expires_at=None), '42')['expiresAt'], None)
        self.assertEqual(view(poll(votes_count=0), '42')['votesCount'], 0)

    def test_read_rejects_wrong_poll_identity_invalid_expiry_and_unbounded_answers(self):
        for changes in ({'id': '43'}, {'id': 42}, {'expired': 0}, {'multiple': 'false'},
                {'expires_at': '2030-01-01'}, {'expires_at': 'nonsense'}, {'expires_at': 0},
                {'options': [{'title': 'Only answer'}]}, {'options': [{'title': 'A'}] * 65},
                {'options': [{'title': 'A'}, {'title': ''}]}):
            with self.subTest(changes=changes), self.assertRaises(AlphaError):
                view(poll(**changes), '42')
        missing = poll(); del missing['expires_at']
        with self.assertRaises(AlphaError): view(missing, '42')

    def test_preparation_requires_unexpired_unvoted_poll_and_valid_answer_count(self):
        self.assertEqual(vote_binding(poll(), '42', [1], 0)['id'], '42')
        self.assertTrue(vote_binding(poll(multiple=True), '42', [0, 1], 0)['multiple'])
        for value, selected in [(poll(expired=True), [0]), (poll(expires_at='2000-01-01T00:00:00Z'), [0]),
                (poll(voted=True), [0]), (poll(voted=None), [0]), (poll(), [0, 1]), (poll(), [2])]:
            with self.subTest(value=value, selected=selected), self.assertRaises(AlphaError):
                vote_binding(value, '42', selected, 1792281600)

    def test_approval_binds_option_text_order_and_rules_but_not_other_peoples_votes(self):
        initial = vote_binding(poll(), '42', [1], 0)
        counts_changed = poll(votes_count=999, voters_count=555)
        counts_changed['options'][0]['votes_count'] = 500
        self.assertEqual(initial, vote_binding(counts_changed, '42', [1], 0))
        for changed in (poll(options=list(reversed(poll()['options']))), poll(multiple=True),
                poll(expires_at='2030-01-02T00:00:00Z')):
            self.assertNotEqual(digest(initial), digest(vote_binding(changed, '42', [1], 0)))
        equivalent = poll(expires_at='2030-01-01T01:00:00+01:00')
        self.assertEqual(initial, vote_binding(equivalent, '42', [1], 0))

    def receipt(self, response, *, scopes=('read:statuses',), write=None):
        provider = SimpleNamespace(api=Mock(return_value=response))
        prepared = {'action': 'poll_vote', 'targetId': '42', 'body': {'choices': [1]},
                    'pollSnapshot': vote_binding(poll(), '42', [1], 0)}
        result = MastodonManagement._receipt(provider, {'instance': 'mastodon.social'}, prepared,
            write or {'status': 200, 'body': poll(voted=True, own_votes=[1])}, granted_scopes=scopes)
        return result, provider.api

    def test_only_independent_exact_own_vote_proves_vote(self):
        result, api = self.receipt({'status': 200, 'body': poll(voted=True, own_votes=[1])})
        self.assertEqual(result['state'], 'verified')
        self.assertEqual(result['verification'], 'provider_poll_lookup')
        self.assertEqual(result['readback']['ownVotes'], [1])
        self.assertNotIn('First answer', json.dumps(result))
        api.assert_called_once_with({'instance': 'mastodon.social'}, 'GET', '/api/v1/polls/42')
        for value in (poll(voted=False, own_votes=[1]), poll(voted=1, own_votes=[1]),
                poll(voted=True, own_votes=None), poll(voted=True, own_votes=[0]),
                poll(voted=True, own_votes=[True]), poll(voted=True, own_votes=[1, 1]),
                poll(voted=True, own_votes=[1], options=list(reversed(poll()['options'])))):
            with self.subTest(value=value):
                result, _ = self.receipt({'status': 200, 'body': value})
                self.assertEqual(result['state'], 'accepted')
                self.assertEqual(result['verification'], 'unavailable')

    def test_failed_confirmation_or_missing_scope_never_resubmits(self):
        for status in (403, 404, 429, 500):
            result, api = self.receipt({'status': status, 'body': {}})
            self.assertEqual(result['state'], 'accepted'); self.assertEqual(api.call_count, 1)
        result, api = self.receipt({'status': 200, 'body': poll(voted=True, own_votes=[1])}, scopes=['write:statuses'])
        self.assertEqual(result['state'], 'accepted'); api.assert_not_called()
        result, api = self.receipt({'status': 200, 'body': poll(voted=True, own_votes=[1])},
            write={'status': 200, 'body': {'id': '999'}})
        self.assertEqual(result['state'], 'uncertain'); api.assert_not_called()
        result, api = self.receipt({'status': 200, 'body': poll(voted=True, own_votes=[1])},
            write={'status': 422, 'body': {'error': 'Already voted'}})
        self.assertEqual(result['state'], 'rejected'); api.assert_not_called()

    def test_poll_read_enforces_grant_before_io_and_fences_result_after_io(self):
        manager = object.__new__(MastodonManagement)
        provider = SimpleNamespace(api=Mock(return_value={'status': 200, 'body': poll()}))
        manager._grant = Mock(return_value=(provider, {'scopes': ['read:statuses']}, {'instance': 'mastodon.social'}))
        manager._read_fence = Mock(side_effect=AlphaError('Credential changed', 409))
        with self.assertRaises(AlphaError): manager.poll('workspace', 'actor', 'connection', 'https://other.example/poll')
        manager._grant.assert_not_called(); provider.api.assert_not_called()
        with self.assertRaises(AlphaError): manager.poll('workspace', 'actor', 'connection', '42')
        self.assertEqual(provider.api.call_count, 1); self.assertEqual(manager._read_fence.call_count, 1)
        provider.api.reset_mock()
        manager._grant.return_value = (provider, {'scopes': ['write:statuses']}, {'instance': 'mastodon.social'})
        with self.assertRaises(AlphaError): manager.poll('workspace', 'actor', 'connection', '42')
        provider.api.assert_not_called()

    def test_agent_vote_preparation_never_discloses_private_poll_answers_or_votes(self):
        from postriff_phase2.mastodon_agent_tools import action_prepare
        private = vote_binding(poll(options=[{'title': 'PRIVATE_OPTION_ONE'}, {'title': 'PRIVATE_OPTION_TWO'}]), '42', [1], 0)
        saved = {'actionId': 'action', 'expiresAt': 600, 'preview': {'action': 'poll_vote',
            'targetId': '42', 'body': {'choices': [1]}, 'pollSnapshot': private}}
        ctx = SimpleNamespace(request_text='Prepare my Mastodon vote in poll 42 for answer 1.', modality='text',
            check_cancelled=lambda: None, service=object(), workspace_id='workspace', token='actor')
        with patch.object(MastodonManagement, '__init__', return_value=None), \
                patch.object(MastodonManagement, 'preview', return_value=copy.deepcopy(saved)) as prepare, \
                patch.object(MastodonManagement, 'execute') as execute:
            result = action_prepare(ctx, {'connectionId': 'connection', 'action': 'poll_vote', 'targetId': '42', 'pollChoices': [1]})
            self.assertTrue(result['needsUser']); self.assertFalse(result['executed'])
            self.assertNotIn('PRIVATE_OPTION', json.dumps(result)); self.assertNotIn('pollSnapshot', result['preview'])
            self.assertEqual(prepare.call_count, 1); execute.assert_not_called()
            prepare.reset_mock()
            for request in ('Show my Mastodon poll.', 'How to vote on my Mastodon poll?', 'Do not vote on my Mastodon poll.'):
                ctx.request_text = request
                with self.assertRaises(AlphaError):
                    action_prepare(ctx, {'connectionId': 'connection', 'action': 'poll_vote', 'targetId': '42', 'pollChoices': [1]})
            prepare.assert_not_called(); execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
