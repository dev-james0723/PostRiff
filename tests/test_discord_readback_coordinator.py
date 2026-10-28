"""A created post's read-back waits for the request coordinator; it is never lost to it (the ops review's N-1, offline).

A post that Discord already accepted keeps its receipt and waits for a read-back that confirms it. That read has to be admitted by
the shared request coordinator like every other. When the coordinator cannot admit anything (none attached because the reviewed
policy does not parse, one marked degraded, a policy that ended, its database down) the read-back used to take the refusal for an
answer it could not read: the post became `uncertain`, the claim kept the check it had spent, and five claims later it was parked
for a day ("Manual provider review required") and stayed parked after the coordinator came back. Nothing about the post had
changed. Now the exact lookup waits, as a read refused by a hold does (B4): the receipt is kept, the check is refunded, the post is
tried again in five minutes. Everything that creates stays fail-closed. Synthetic state only; the PostgreSQL proof is
test_discord_readback_coordinator_postgres.py.
"""
import copy
import importlib.util
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord.rate_limits import (COORDINATOR_WAIT_SECONDS, HOLD_WAIT_SECONDS, RateCoordinatorUnavailable, RateDelayed,
                                                 ReadAdmissionDelayed, SharedPostgresBudget)
from postriff_phase2.outcomes import normalize_result
from test_discord_publish_authorization import APP, FIRST, NOW, approve, claimed_job, fixture, review, transport_and_worker

ROOT = Path(__file__).resolve().parents[1]


def policy():
    spec = importlib.util.spec_from_file_location('discord_rate_policy', ROOT / 'scripts/discord_rate_policy.py')
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return json.dumps(tool.build(time.time(), days=1, revision='n1-test'))


def broken_database():
    raise OSError('the coordinator\'s database is not reachable')


class Created(unittest.TestCase):
    """One approved post with a receipt, five checks spent, and a worker that claimed its read-back."""

    def setUp(self):
        engine, self.state, channel, variant = fixture()
        self.job = approve(engine, self.state, review(engine, self.state, channel, variant))
        self.job.update(providerReference=FIRST + '/4444444', checks=5)
        self.claimed = claimed_job(self.job)
        self.claimed['reconciliation'] = True
        self.wire, self.grants, self.social, self.db, self.worker = transport_and_worker(self.state)
        self.provider = self.social.providers['discord']

    def reconcile(self):
        before = copy.deepcopy(self.job)
        result = self.social.reconcile(self.job['manifest'], self.job)
        self.assertEqual(self.job, before, 'a lookup that waits changes nothing about the post')
        return result

    def completed(self, result):
        self.assertTrue(self.worker.complete(self.claimed, result))
        return self.db.state['phase2']['jobs'][0]

    def waits_as_a_refused_read_does(self, result):
        """The deferral, normalized as the worker does, and what completing it does to the post."""
        normalized = normalize_result(result, self.job, True)
        self.assertEqual(normalized['state'], 'provider_accepted', 'not uncertain')
        self.assertTrue(normalized['discordReadDeferred'])
        self.assertTrue(normalized['discordReadAdmissionDenied'], 'nothing reached Discord, so the check comes back')
        self.assertEqual(normalized['retryAfterSeconds'], int(COORDINATOR_WAIT_SECONDS))
        self.assertEqual(normalized['reference'], self.job['providerReference'], 'the receipt is kept')
        current = self.completed(result)
        self.assertEqual(current['state'], 'provider_accepted')
        self.assertEqual(current['checks'], 4, 'the check the claim spent was refunded')
        self.assertNotIn('Manual provider review', current.get('nextAction') or '')
        self.assertEqual(current['providerReference'], self.job['providerReference'])
        self.assertEqual(current['discordReadDeferrals'], 1)
        self.assertFalse(self.wire.calls, 'nothing was sent')
        return current


class AnUnavailableCoordinatorMakesTheLookupWait(Created):
    def test_whatever_part_of_the_lookup_meets_it(self):
        for attribute in ('_bot_identity', '_bot'):
            with self.subTest(refused=attribute):
                self.setUp()
                with patch.object(self.provider, attribute, side_effect=RateCoordinatorUnavailable()):
                    self.waits_as_a_refused_read_does(self.reconcile())

    def test_it_waits_exactly_as_long_as_a_read_refused_by_a_hold(self):
        with patch.object(self.provider, '_bot', side_effect=ReadAdmissionDelayed(RateDelayed(HOLD_WAIT_SECONDS, cause='hold', scope='embargo'))):
            held = self.waits_as_a_refused_read_does(self.reconcile())
        self.setUp()
        with patch.object(self.provider, '_bot', side_effect=RateCoordinatorUnavailable()):
            unavailable = self.waits_as_a_refused_read_does(self.reconcile())
        self.assertEqual(unavailable['nextAt'], held['nextAt'])
        self.assertEqual(COORDINATOR_WAIT_SECONDS, HOLD_WAIT_SECONDS)

    def test_a_process_with_no_coordinator_at_all(self):
        """What oauth.py leaves behind when SharedPostgresBudget refuses the reviewed policy: no limiter, degraded."""
        self.provider.rate_v1_enabled, self.provider.rate_limiter, self.provider.rate_coordinator_degraded = True, None, True
        self.waits_as_a_refused_read_does(self.reconcile())

    def test_a_degraded_coordinator(self):
        self.provider.rate_v1_enabled = True
        self.provider.rate_limiter = SharedPostgresBudget(broken_database, APP, policy=policy())
        self.provider.rate_coordinator_degraded = True
        self.waits_as_a_refused_read_does(self.reconcile())

    def test_a_coordinator_whose_database_is_down(self):
        self.provider.rate_v1_enabled = True
        self.provider.rate_limiter = SharedPostgresBudget(broken_database, APP, policy=policy())
        self.waits_as_a_refused_read_does(self.reconcile())

    def test_it_goes_on_waiting_however_many_claims_there_are_and_then_verifies(self):
        """Eight claims, more than the five checks a post has: none costs a check, the post is never parked."""
        self.provider.rate_v1_enabled, self.provider.rate_limiter, self.provider.rate_coordinator_degraded = True, None, True
        for attempt in range(1, 9):
            result = self.reconcile()
            self.assertTrue(self.worker.complete(self.claimed, result))
            current = self.db.state['phase2']['jobs'][0]
            self.assertEqual((current['state'], current['checks'], current.get('discordReadDeferrals')), ('provider_accepted', 4, attempt), attempt)
            self.assertNotIn('Manual provider review', current.get('nextAction') or '')
            current['checks'] += 1                                  # the next claim spends one, as every claim does
            self.claimed = claimed_job(current)
            self.claimed['reconciliation'] = True
        self.provider.rate_v1_enabled, self.provider.rate_coordinator_degraded = False, False   # the coordinator is back (or never needed)
        self.assertEqual(self.reconcile()['state'], 'verified')


class OnlyTheCoordinatorIsAWaitNotEveryFailure(Created):
    def test_a_lookup_that_fails_for_another_reason_is_still_uncertain(self):
        for error in (AlphaError('Synthetic: the connection changed.', 409), KeyError('x'), ValueError('x')):
            with self.subTest(error=type(error).__name__):
                with patch.object(self.provider, '_bot', side_effect=error):
                    self.assertEqual(self.reconcile()['state'], 'uncertain')

    def test_a_create_is_still_refused_when_there_is_no_coordinator(self):
        self.provider.rate_v1_enabled, self.provider.rate_limiter, self.provider.rate_coordinator_degraded = True, None, True
        with self.assertRaises(RateCoordinatorUnavailable):
            self.provider.admit_bot_request('POST', '/channels/%s/messages' % FIRST)
        with self.assertRaises(RateCoordinatorUnavailable):   # and a read made for anything else keeps its 503 for the person asking
            self.provider._bot('GET', '/guilds/555555')
        self.assertFalse(self.wire.calls)


class ShippedConstants(unittest.TestCase):
    def test_the_wait(self):
        self.assertEqual(COORDINATOR_WAIT_SECONDS, 300.0)


if __name__ == '__main__':
    unittest.main()
