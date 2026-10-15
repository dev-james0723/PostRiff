"""Only proven pre-send denials may resume; no external transport is retried."""
import copy
import unittest
from unittest.mock import patch

from postriff_phase2.discord.rate_limits import Permit, RateDelayed, SharedPostgresBudget, UnconsumedPublishPermit, ReadAdmissionDelayed, _digest
from postriff_phase2.social_connectors import DiscordProvider
from test_discord_rate_limits import MemoryLedger, synthetic_policy, APP, A, B


class PreSendRecovery(unittest.TestCase):
    def setUp(self):
        self.db, self.sent, self.waits, self.monotonic = MemoryLedger(), [], [], 100.
        policy = synthetic_policy(); policy['read_attempts'] = 3
        self.budget = SharedPostgresBudget(self.db.connection, APP, policy=policy)
        self.response = {'status': 200, 'body': {'id': B}, 'headers': {}}
        def transport(method, url, **kwargs):
            self.sent.append((method, url))
            return copy.deepcopy(self.response)
        self.p = DiscordProvider(APP, 'synthetic-secret', 'synthetic-bot', 'https://rafii.invalid', transport=transport)
        self.p.rate_v1_enabled = True; self.p.rate_limiter = self.budget
        def wait(seconds):
            self.waits.append(seconds); self.monotonic += seconds; self.db.now += seconds
        for target, value in [('postriff_phase2.social_connectors.time.monotonic', lambda: self.monotonic),
                              ('postriff_phase2.social_connectors.time.sleep', wait),
                              ('postriff_phase2.social_connectors.secrets.randbelow', lambda _: 0)]:
            context = patch(target, side_effect=value); context.start(); self.addCleanup(context.stop)
        network = patch('socket.socket.connect', side_effect=AssertionError('Real network forbidden'))
        network.start(); self.addCleanup(network.stop)

    def first_denial(self):
        original = self.budget.reserve
        self.reservations = 0
        def reserve(*args, **kwargs):
            self.reservations += 1
            if self.reservations == 1: raise RateDelayed(.05)
            return original(*args, **kwargs)
        return patch.object(self.budget, 'reserve', side_effect=reserve)

    def test_get_waits_without_restarting_the_operation_and_sends_once(self):
        with self.first_denial(): self.p._bot('GET', '/channels/' + A + '/messages/' + B)
        self.assertEqual((self.reservations, len(self.sent), self.waits), (2, 1, [.05]))

    def test_oauth_post_admission_delay_never_reexchanges_a_sent_code(self):
        with self.first_denial():
            self.p._discord_http('POST', '/oauth2/token', credential_kind='oauth', form={'code': 'synthetic-one-use'})
        self.assertEqual((self.reservations, len(self.sent)), (2, 1))

    def test_long_wait_is_not_shortened_or_polled_aggressively(self):
        with patch.object(self.budget, 'reserve', side_effect=RateDelayed(172800.25)) as reserve:
            with self.assertRaises(RateDelayed) as caught: self.p._bot('GET', '/users/@me')
        self.assertEqual(caught.exception.retry_after_seconds, 172800.25)
        self.assertIsInstance(caught.exception, ReadAdmissionDelayed)
        self.assertEqual(reserve.call_count, 1)
        self.assertFalse(self.sent or self.waits)

    def test_local_attempts_are_bounded_and_never_reach_transport_when_denied(self):
        with patch.object(self.budget, 'reserve', side_effect=RateDelayed(.05)) as reserve:
            with self.assertRaises(RateDelayed): self.p._bot('GET', '/users/@me')
        self.assertEqual((reserve.call_count, len(self.waits), len(self.sent)), (3, 2, 0))

    def test_expired_publication_permit_is_not_reallocated(self):
        path = '/channels/' + A + '/messages'
        permit = Permit('synthetic-permit', self.budget.application_key, 'POST', _digest(path),
                        self.p._rate_identity('bot'), 'f' * 64, self.db.now + 1)
        with patch.object(self.budget, 'reserve') as reserve, patch.object(self.budget, 'consume', side_effect=RateDelayed(.05)) as consume:
            with self.assertRaises(RateDelayed):
                self.p._bot('POST', path, rate_permit=permit, rate_binding={'synthetic': True},
                            rate_intent_id='synthetic-intent', rate_authorize=lambda cur: self.db.now + 1)
        reserve.assert_not_called(); self.assertEqual(consume.call_count, 1)
        self.assertFalse(self.waits or self.sent)

    def test_transport_failure_and_provider_response_are_never_retried(self):
        calls = []
        def failed(method, url, **kwargs):
            calls.append((method, url)); raise TimeoutError('Synthetic ambiguous delivery')
        self.p.transport = failed
        with self.assertRaises(TimeoutError):
            self.p._discord_http('POST', '/oauth2/token', credential_kind='oauth')
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.waits)

    def test_http_429_does_not_mint_a_presend_read_denial(self):
        self.response = {'status':429,'body':{'retry_after':2,'global':True},'headers':{'Retry-After':'2'}}
        with self.assertRaises(RateDelayed) as caught:
            self.p._bot('GET','/channels/' + A + '/messages/' + B)
        self.assertNotIsInstance(caught.exception, ReadAdmissionDelayed)
        self.assertEqual(caught.exception.rate_cause,'provider_429')
        self.assertEqual(len(self.sent),1)

    def test_only_consume_expiry_mints_the_unsent_publication_signal(self):
        path = '/channels/' + A + '/messages'
        permit = Permit('synthetic-permit', self.budget.application_key, 'POST', _digest(path),
                        self.p._rate_identity('bot'), 'f' * 64, self.db.now + 1)
        arguments = dict(rate_permit=permit, rate_binding={'synthetic': True},
                         rate_intent_id='synthetic-intent', rate_authorize=lambda cur: self.db.now + 1)
        with patch.object(self.budget, 'consume', side_effect=RateDelayed(.05, cause='permit_expired')):
            with self.assertRaises(UnconsumedPublishPermit) as caught:
                self.p._bot('POST', path, **arguments)
        self.assertEqual(caught.exception.permit_id, permit.id)
        self.assertFalse(self.sent)
        self.p.transport = lambda *args, **kw: (_ for _ in ()).throw(RateDelayed(.05, cause='permit_expired'))
        with patch.object(self.budget, 'consume'):
            with self.assertRaises(RateDelayed) as caught:
                self.p._bot('POST', path, **arguments)
        self.assertNotIsInstance(caught.exception, UnconsumedPublishPermit)
        self.assertFalse(self.waits)
