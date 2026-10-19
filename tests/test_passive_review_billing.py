"""Passive review/paid publication boundary; in-memory SQL, no DB or provider I/O."""
import copy
import json
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.discord.authorization import destination_id
from postriff_phase2.hosted import HostedPhase2Commands, PostgresWorkspaceRepository
from postriff_phase2.hosted_worker import PostgresWorker
from test_discord_publish_authorization import ACTOR, FIRST, GUILD, NOW, WORKSPACE, fixture

TOKEN = 'synthetic-passive-review-session'


class NoProvider:
    def __getattr__(self, name):
        raise AssertionError('Passive review or denied approval must not call a provider: ' + name)


class Cursor:
    """Only workspace persistence and the real billing guard's SQL are allowed."""
    def __init__(self, pending, queries):
        self.pending, self.queries, self.result = pending, queries, None

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        if sql.startswith('UPDATE public.pr_workspaces SET state='):
            self.pending['state'] = json.loads(params[0])
            self.pending['revision'] += 1
        elif sql == "SELECT state->'founderOps' FROM public.pr_workspaces WHERE id=%s":
            self.result = (self.pending['state'].get('founderOps'),)
        elif sql.startswith('SELECT status,extract(epoch from grace_until)'):
            sub = self.pending['subscription']
            self.result = (sub['status'], None, False, sub['currentPeriodEnd'])
        elif sql.startswith('UPDATE public.pr_subscriptions SET status='):
            self.pending['subscription']['status'] = params[0]
        else:
            raise AssertionError('Unexpected SQL, including any admission/credit write: ' + sql)

    def fetchone(self):
        return self.result


class Transaction:
    def __init__(self, state):
        self.saved = {'state': state, 'revision': 7,
                      'subscription': {'status': 'trial', 'currentPeriodEnd': NOW - 3600}}
        self.role, self.queries = 'owner', []

    @contextmanager
    def __call__(self, token, workspace_id):
        if token != TOKEN or workspace_id != WORKSPACE:
            raise AlphaError('Workspace unavailable.', 403)
        pending = copy.deepcopy(self.saved)
        cursor = Cursor(pending, self.queries)
        yield cursor, [pending['revision'], pending['state'], self.role, False, False, False, False], ACTOR
        # An exception from the command/after hook skips commit, just like the real connection context.
        self.saved = pending


class PassiveReviewBilling(unittest.TestCase):
    def setUp(self):
        _, state, self.channel, self.variant = fixture()
        state['phase2']['trial'] = {'expiresAt': NOW - 3600}
        self.commands = HostedPhase2Commands(clock=lambda: NOW)
        self.commands.engine.social = NoProvider()
        self.db = Transaction(state)
        self.repository = PostgresWorkspaceRepository(None, lambda _: ACTOR, self.commands, clock=lambda: NOW)
        self.repository.transaction = self.db
        self.payload = {'variantId': self.variant['id'], 'channelId': self.channel['id'],
                        'destinationId': destination_id(WORKSPACE, self.channel['id'], GUILD, FIRST),
                        'localTime': datetime.fromtimestamp(NOW + 300, timezone.utc).strftime('%Y-%m-%dT%H:%M'),
                        'timeZone': 'UTC', 'rightsConfirmed': True, 'acknowledgedWarnings': []}

    def prepare(self):
        result = self.repository.mutate(WORKSPACE, TOKEN, self.db.saved['revision'], 'p2_review', self.payload)
        return result['state']['phase2']['reviews'][-1]

    def test_expired_plan_persists_only_a_passive_frozen_review_without_billing_changes(self):
        before = copy.deepcopy(self.db.saved)
        review = self.prepare()
        saved = self.db.saved
        self.assertEqual(saved['revision'], before['revision'] + 1)
        self.assertEqual(saved['state']['phase2']['reviews'], [review])
        self.assertEqual(review['status'], 'needs_review')
        self.assertNotIn('jobId', review)
        self.assertNotIn('approvedAt', review)
        self.assertEqual(review['manifest']['actor'], ACTOR)
        self.assertEqual(review['manifest']['payload']['text'], self.variant['text'])
        self.assertEqual(review['manifest']['discord']['target']['channelId'], FIRST)
        self.assertEqual(review['digest'], digest(review['manifest']))
        self.assertEqual(saved['state']['phase2']['jobs'], [])
        self.assertEqual(saved['subscription'], before['subscription'])
        self.assertEqual(saved['state']['phase2']['trial'], before['state']['phase2']['trial'])
        self.assertNotIn('founderOps', saved['state'])
        self.assertEqual(len(self.db.queries), 1)
        self.assertTrue(self.db.queries[0][0].startswith('UPDATE public.pr_workspaces SET state='))
        frozen = copy.deepcopy(review['manifest'])
        saved['state']['variants'][0]['text'] = 'Later author edit'
        self.assertEqual(review['manifest'], frozen)
        self.assertEqual(review['digest'], digest(frozen))

    def test_expired_plan_rejects_single_and_bulk_approval_and_rolls_back_any_job(self):
        review = self.prepare()
        before = copy.deepcopy(self.db.saved)
        single = {'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True}
        for action, payload in [('p2_approve', single),
                                ('p2_approve_many', {'reviews': [single], 'confirmed': True})]:
            with self.subTest(action=action), self.assertRaises(AlphaError) as denied:
                self.repository.mutate(WORKSPACE, TOKEN, before['revision'], action, payload)
            self.assertEqual((denied.exception.status, denied.exception.code), (402, 'publishing_plan_inactive'))
            self.assertEqual(self.db.saved, before)
            self.assertEqual(self.db.saved['state']['phase2']['jobs'], [])
        self.assertTrue(any(sql.startswith('SELECT status,extract(epoch from grace_until)') for sql, _ in self.db.queries))

    def test_review_keeps_permission_revision_and_exact_destination_guards(self):
        before = copy.deepcopy(self.db.saved)
        for role in ['viewer', 'editor', 'admin']:
            self.db.role = role
            with self.subTest(role=role), self.assertRaises(AlphaError) as denied:
                self.prepare()
            self.assertEqual(denied.exception.status, 403)
        self.db.role = 'owner'
        with self.assertRaises(AlphaError) as stale:
            self.repository.mutate(WORKSPACE, TOKEN, before['revision'] - 1, 'p2_review', self.payload)
        self.assertEqual(stale.exception.code, 'workspace_revision_conflict')
        with self.assertRaises(AlphaError):
            self.repository.mutate(WORKSPACE, TOKEN, before['revision'], 'p2_review',
                                   {**self.payload, 'destinationId': 'another-workspace-destination'})
        self.assertEqual(self.db.saved, before)
        self.assertEqual(self.db.queries, [])

    def test_expired_plan_still_blocks_worker_authority_for_an_existing_approved_job(self):
        review = self.prepare()
        state = copy.deepcopy(self.db.saved['state'])
        self.commands.engine.apply_phase2(None, state, 'approve',
            {'reviewId': review['id'], 'digest': review['digest'], 'confirmed': True}, {'user_id': ACTOR})
        job = state['phase2']['jobs'][0]  # Already-approved fixture; checks the worker's live billing gate only.
        worker = PostgresWorker(None, social=NoProvider(), clock=lambda: NOW)
        with self.db(TOKEN, WORKSPACE) as (cursor, _, _), \
             patch('postriff_phase2.security_holds.assert_clear'):
            self.assertFalse(worker._approved(cursor, WORKSPACE, state, job, now=NOW))
        self.assertEqual(self.db.saved['state']['phase2']['jobs'], [])
        self.assertFalse(any('pr_discord_request_admissions' in sql for sql, _ in self.db.queries))


if __name__ == '__main__':
    unittest.main()
