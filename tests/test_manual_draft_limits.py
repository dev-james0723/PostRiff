"""G2E-C-03 (poc_manual_draft_growth): manual_draft_create had no cap or throttle. 100 saves of 10,000 characters to 20
destinations made 2,000 variants and 42 MB of workspace state, and every later request of that workspace slowed with it."""
import json
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import creation_capabilities as cc, manual_drafts
from postriff_phase2.hosted import HostedPhase2Commands, PostgresWorkspaceRepository
from test_manual_drafts import ACTOR, NOW, TOKEN, WORKSPACE, state

MAX_ALLOWED_REQUEST = manual_drafts.MAX_REQUEST_CHARS


def destinations(count):
    """`count` distinct valid (platform, language) destinations that need no connected account."""
    commands, found = HostedPhase2Commands(clock=lambda: NOW), []
    projection = cc.projection()
    for platform in projection.by_platform:
        for language in ('en', 'zh-Hant', 'zh-Hans', 'ja', 'ko', 'es', 'fr', 'de', 'pt'):
            probe = state()
            try:
                commands(probe, ACTOR, manual_drafts.ACTION, {'text': 'x', 'requestId': str(uuid.uuid4()),
                                                              'destinations': [{'platform': platform, 'language': language}]})
            except Exception:
                continue
            found.append({'platform': platform, 'language': language})
            if len(found) == count:
                return found
    raise AssertionError(f'only {len(found)} valid destinations exist')


class TheRepeatedSaveCannotGrowTheWorkspaceWithoutBound(unittest.TestCase):
    def setUp(self):
        self.state = state()
        self.commands = HostedPhase2Commands(clock=lambda: NOW)
        self.twenty = destinations(20)

    def save(self, text, count, request=None):
        return self.commands(self.state, ACTOR, manual_drafts.ACTION,
                             {'text': text, 'requestId': request or str(uuid.uuid4()), 'destinations': self.twenty[:count]})

    def test_one_save_cannot_fan_out_a_long_text_to_every_destination(self):
        before = json.dumps(self.state, sort_keys=True)
        for length, count in ((10000, 20), (10000, 7), (3001, 20)):
            with self.assertRaises(AlphaError) as raised:
                self.save('x' * length, count)
            self.assertEqual((raised.exception.status, raised.exception.code), (413, 'manual_draft_too_large'), (length, count))
        self.assertEqual(json.dumps(self.state, sort_keys=True), before)  # nothing was stored

    def test_normal_use_is_far_below_the_ceilings(self):
        for length, count in ((10000, 6), (3000, 20), (280, 20), (1200, 5)):
            self.save('x' * length, count)
        self.assertLessEqual(10000 * 6, MAX_ALLOWED_REQUEST)

    def test_the_proof_of_concept_growth_now_stops(self):
        """100 saves of 3,000 characters to 20 destinations (the largest single save allowed): growth ends before the state
        reaches the ceiling, with a clear error, and the workspace stays usable."""
        accepted, refusal = 0, None
        for _ in range(150):
            try:
                self.save('x' * 3000, 20)
                accepted += 1
            except AlphaError as error:
                refusal = error
                break
        self.assertIsNotNone(refusal, 'the workspace grew without bound')
        self.assertEqual((refusal.status, refusal.code), (409, 'manual_draft_limit'))
        self.assertLess(accepted, 150)
        self.assertLessEqual(len(json.dumps(self.state, default=str)), manual_drafts.MAX_STATE_BYTES)
        self.assertLessEqual(sum(1 for v in self.state['variants'] if v.get('manualRequestId')), manual_drafts.MAX_MANUAL_VARIANTS)

    def test_the_variant_count_has_its_own_ceiling(self):
        with patch.object(manual_drafts, 'MAX_MANUAL_VARIANTS', 40):
            self.save('short', 20)
            self.save('short', 20)
            with self.assertRaises(AlphaError) as raised:
                self.save('short', 1)
            self.assertEqual(raised.exception.code, 'manual_draft_limit')

    def test_an_idempotent_retry_is_never_refused_for_room(self):
        request = str(uuid.uuid4())
        with patch.object(manual_drafts, 'MAX_MANUAL_VARIANTS', 20):
            self.save('short', 20, request)
            self.save('short', 20, request)  # the same save again: answered from what exists, not counted twice
            self.assertEqual(sum(1 for v in self.state['variants'] if v.get('manualRequestId') == request), 20)
            with self.assertRaises(AlphaError):
                self.save('different', 1)


class SavesAreThrottledPerWorkspace(unittest.TestCase):
    def test_the_transaction_counts_each_save_against_the_workspace(self):
        commands, current = HostedPhase2Commands(clock=lambda: NOW), state()
        repository = PostgresWorkspaceRepository(None, lambda _: ACTOR, commands)
        cursor, counts = Mock(), {}

        def execute(sql, params=()):
            if 'pr_auth_throttle' in sql:
                scope_hash = params[0]
                counts[scope_hash] = counts.get(scope_hash, 0) + 1
                cursor.fetchone.return_value = (counts[scope_hash],)
        cursor.execute.side_effect = execute

        @contextmanager
        def transaction(token, workspace_id):
            yield cursor, [7, current, 'owner', True, True, True, True], ACTOR
        repository.transaction = transaction
        body = {'text': 'synthetic text', 'requestId': str(uuid.uuid4()), 'destinations': [{'platform': 'LinkedIn', 'language': 'en'}]}
        repository.mutate(WORKSPACE, TOKEN, 7, manual_drafts.ACTION, body)
        import hashlib
        self.assertIn(hashlib.sha256(f'manual-draft:{WORKSPACE}'.encode()).hexdigest(), counts)
        counts[hashlib.sha256(f'manual-draft:{WORKSPACE}'.encode()).hexdigest()] = 30  # a thirty-first save inside the minute
        with self.assertRaises(AlphaError) as raised:
            repository.mutate(WORKSPACE, TOKEN, 7, manual_drafts.ACTION, {**body, 'requestId': str(uuid.uuid4())})
        self.assertEqual(raised.exception.status, 429)

    def test_other_actions_are_not_counted(self):
        commands = HostedPhase2Commands(clock=lambda: NOW)
        repository = PostgresWorkspaceRepository(None, lambda _: ACTOR, commands)
        cursor = Mock()

        @contextmanager
        def transaction(token, workspace_id):
            yield cursor, [7, state(), 'owner', True, True, True, True], ACTOR
        repository.transaction = transaction
        with self.assertRaises(Exception):
            repository.mutate(WORKSPACE, TOKEN, 7, 'p2_cancel', {'jobId': 'none'})
        self.assertFalse(any('pr_auth_throttle' in str(call) for call in cursor.execute.call_args_list))


if __name__ == '__main__':
    unittest.main()
