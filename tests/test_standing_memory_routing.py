"""Offline regression for the observed standing-memory misroute; no provider calls."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from postriff_phase2 import intent
from postriff_phase2.ideas import IdeasService
from postriff_phase2.learning_chat import instruction_to_proposal
from postriff_phase2.permissions import Membership

TEXT = 'From now on, keep my LinkedIn posts under 30 words.'


class ReachedDraftPath(Exception):
    pass


class StandingMemoryRouting(unittest.TestCase):
    def setUp(self):
        self.service = IdeasService.__new__(IdeasService)
        self.service.clock = lambda: 1800000000
        self.runtime = SimpleNamespace(supported_platforms=lambda: ('LinkedIn',), owns=lambda _: True)
        self.service.resolve_writer = Mock(return_value=(self.runtime, 'offline-writer', None))
        self.service.credit_requests = SimpleNamespace(authorize=Mock(return_value=None))
        self.service._wants_image = Mock(return_value=False)
        self.service._understand = Mock(side_effect=AssertionError('Standing memory must not call a model helper.'))
        self.service._orchestration_turn = Mock(side_effect=AssertionError('Standing memory must not enter orchestration.'))
        self.service._memory_turn = Mock(return_value={'status': 'memory', 'usage': {'modelRequests': 0, 'costUsd': 0}})
        self.service._member = lambda _: Membership('owner')
        self.service._conversation = Mock()
        self.service._keyed_run = Mock(return_value=None)
        self.service._research = Mock(side_effect=ReachedDraftPath)

        @contextmanager
        def transaction(*args):
            yield Mock(), (1, {}, 'owner'), 'offline-actor'

        self.service.repository = SimpleNamespace(transaction=transaction, get=Mock(return_value={'state': {}}))
        self.payload = {'text': TEXT, 'research': False, 'destinations': [{'platform': 'LinkedIn', 'language': 'English'}]}

    def test_observed_input_is_memory_not_publish_now(self):
        parsed = intent.parse_request(TEXT, self.service.clock(), 'UTC')
        self.assertEqual(parsed['intent'], 'memory')
        proposal = instruction_to_proposal(TEXT)
        self.assertEqual((proposal['ruleKey'], proposal['scope']['platform'], proposal['statement']), ('length.target', 'LinkedIn', TEXT))

    def test_standing_memory_routes_before_understanding_or_orchestration(self):
        result = self.service.turn('offline-workspace', 'offline-session', 'offline-conversation', self.payload)
        self.assertEqual(result, {'status': 'memory', 'usage': {'modelRequests': 0, 'costUsd': 0}})
        self.service._understand.assert_not_called()
        self.service._orchestration_turn.assert_not_called()
        self.service._research.assert_not_called()
        self.service._memory_turn.assert_called_once()
        args = self.service._memory_turn.call_args.args
        self.assertEqual((args[3], args[4]['intent'], args[5][0]['platform']), (TEXT, 'memory', 'LinkedIn'))

    def test_one_off_immediate_post_and_scheduling_keep_existing_routes(self):
        for text, expected in (
            ('For this post, keep LinkedIn under 30 words.', 'draft'),
            ('Post this to LinkedIn now.', 'publish_now'),
            ('Remember: post to LinkedIn tomorrow at 4pm.', 'schedule'),
            ('Every Monday draft a LinkedIn post.', 'automation'),
        ):
            with self.subTest(text=text):
                self.assertEqual(intent.parse_request(text, self.service.clock(), 'UTC')['intent'], expected)

    def test_handed_in_rework_is_not_silently_saved_as_memory(self):
        with self.assertRaises(ReachedDraftPath):
            self.service.turn('offline-workspace', 'offline-session', 'offline-conversation', {**self.payload, 'material': 'Existing draft to rework.'})
        self.service._memory_turn.assert_not_called()

    def test_reference_chip_is_not_silently_saved_as_memory(self):
        with patch('postriff_phase2.turn_references.early', return_value={'rework': None, 'destinations': []}), \
                self.assertRaises(ReachedDraftPath):
            self.service.turn('offline-workspace', 'offline-session', 'offline-conversation',
                              {**self.payload, 'references': [{'kind': 'source', 'id': 'offline-source'}]})
        self.service._memory_turn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
