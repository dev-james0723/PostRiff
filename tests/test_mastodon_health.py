"""Restricted identity and deadline contracts; no provider network traffic."""
import json
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.mastodon_health import delay
from postriff_phase2.net_guard import request_deadline, _request_remaining
from postriff_phase2 import net_guard
from postriff_phase2.social_connectors import MastodonProvider
from test_hosted_wave1_connectors import Wire, ok, PUBLIC, BASE


class HealthTests(unittest.TestCase):
    def test_verification_cooldown_preserves_bounded_retry_headers(self):
        from postriff_alpha.domain import AlphaError
        from postriff_phase2.social_connectors import MastodonProvider
        with self.assertRaises(AlphaError) as caught:
            MastodonProvider._verification_cooldown({'status': 429, 'headers': {
                'Retry-After': '120', 'X-RateLimit-Reset': '2026-10-11T10:00:00Z', 'Authorization': 'do-not-retain'}})
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.mastodon_retry_headers,
            {'retry-after': '120', 'x-ratelimit-reset': '2026-10-11T10:00:00Z'})
        MastodonProvider._verification_cooldown({'status': 200})

    def test_migration_suspension_and_memorial_never_switch_account_or_call_another_instance(self):
        for restriction, body in [('account_moved', {'moved': {'id': '222', 'url': 'http://127.0.0.1'}}),
                                  ('account_suspended', {'suspended': True}), ('account_memorialized', {'memorial': True})]:
            wire = Wire([ok({'id': '100', 'username': 'old', **body})] * 2)
            provider = MastodonProvider(BASE, transport=wire, resolver=PUBLIC)
            token = json.dumps({'v': 1, 'instance': 'mastodon.social', 'at': 'synthetic', 'scope': ['read:accounts', 'write:statuses']})
            self.assertEqual(provider.identity(token)['restriction'], restriction)
            self.assertEqual(provider.inspect_scopes(token, '100@mastodon.social'), [])
            self.assertEqual(len(wire.calls), 2)
            self.assertTrue(all(c['url'] == 'https://mastodon.social/api/v1/accounts/verify_credentials' for c in wire.calls))

    def test_limited_account_does_not_invent_a_publication_ban(self):
        provider = MastodonProvider(BASE, transport=Wire([ok({'id': '100', 'limited': True})]), resolver=PUBLIC)
        token = json.dumps({'v': 1, 'instance': 'mastodon.social', 'at': 'synthetic', 'scope': ['read:accounts']})
        self.assertNotIn('restriction', provider.identity(token))

    def test_definitive_401_requires_reconnect_but_server_outage_is_transient(self):
        token = json.dumps({'v': 1, 'instance': 'mastodon.social', 'at': 'synthetic', 'scope': ['read:accounts']})
        for status in (401, 403, 503):
            provider = MastodonProvider(BASE, transport=Wire([ok({}, status)]), resolver=PUBLIC)
            with self.assertRaises(AlphaError) as caught: provider.identity(token)
            self.assertEqual(caught.exception.code == 'mastodon_authorization_revoked', status == 401)

    def test_health_retry_has_bounded_backoff_and_success_jitter(self):
        self.assertEqual(delay('read_verified', 10, lambda a, b: a), 3000)
        self.assertEqual(delay('reauthorization_required', 0), 21600)
        self.assertEqual(delay('verification_unavailable', 1, lambda a, b: a), 120)
        self.assertEqual(delay('verification_unavailable', 10, lambda a, b: b), 21630)

    def test_nested_deadline_never_extends_outer_and_resets_without_cross_request_leak(self):
        with patch('postriff_phase2.net_guard.time.monotonic', return_value=100):
            with request_deadline(3):
                self.assertEqual(_request_remaining(), 3)
                with request_deadline(8): self.assertEqual(_request_remaining(), 3)
                with patch('postriff_phase2.net_guard.time.monotonic', return_value=104):
                    with self.assertRaises(AlphaError): _request_remaining()
            self.assertEqual(_request_remaining(), 20)

    def test_deadline_rejects_invalid_unbounded_values(self):
        for seconds in (0, -1, 21, True, '8'):
            with self.assertRaises(ValueError), request_deadline(seconds): pass

    def test_dns_timeout_keeps_running_capacity_reserved_until_os_call_finishes(self):
        slots = Mock(acquire=Mock(return_value=True))
        future = Mock(result=Mock(side_effect=TimeoutError), cancel=Mock(return_value=False))
        pool = Mock(submit=Mock(return_value=future))
        with patch.object(net_guard, '_DNS_EXECUTOR', pool), patch.object(net_guard, '_DNS_SLOTS', slots):
            with self.assertRaises(AlphaError): net_guard._public_answers(net_guard._SYSTEM_RESOLVER, 'mastodon.social')
        slots.release.assert_not_called(); future.cancel.assert_called_once()
        self.assertTrue(0 < future.result.call_args.kwargs['timeout'] <= 5)
        future.add_done_callback.call_args.args[0](future)
        slots.release.assert_called_once()

    def test_exhausted_dns_capacity_does_not_spawn_another_lookup(self):
        slots, pool = Mock(acquire=Mock(return_value=False)), Mock()
        with patch.object(net_guard, '_DNS_EXECUTOR', pool), patch.object(net_guard, '_DNS_SLOTS', slots):
            with self.assertRaises(AlphaError): net_guard._public_answers(net_guard._SYSTEM_RESOLVER, 'mastodon.social')
        pool.submit.assert_not_called()

    def test_default_transport_has_one_absolute_deadline_even_for_small_drip_chunks(self):
        readings = iter((100, 100, 119, 121))
        @net_guard._bounded_public_transport
        def transport():
            first = _request_remaining()
            second = _request_remaining()
            self.assertEqual(first, 20); self.assertEqual(second, 1)
            _request_remaining()
        with patch('postriff_phase2.net_guard.time.monotonic', side_effect=lambda: next(readings)):
            with self.assertRaises(AlphaError): transport()
