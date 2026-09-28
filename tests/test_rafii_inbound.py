"""No network: keypad admission never leaks pre-auth audio into the Live transport."""
import asyncio
import base64
import json
import unittest

from postriff_phase2.phone.config import PhoneConfig
from postriff_phase2.phone import inbound
from postriff_phase2.phone.code_speech import RESERVE_USD_MICRO
from postriff_phase2.phone.providers.dial import DialMediaTransport
from postriff_phase2.deployment import isolated_environment


class Socket:
    def __init__(self):
        self.frames, self.sent = asyncio.Queue(), []

    async def receive_text(self):
        return await self.frames.get()

    async def send_json(self, event):
        self.sent.append(event)

    async def event(self, **event):
        await self.frames.put(json.dumps(event))


class InboundMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_code_reset_keepalive_and_private_audio_gate(self):
        socket = Socket()
        transport = DialMediaTransport(socket, collect_code=True)
        try:
            await socket.event(type='media', payload=base64.b64encode(b'private speech before login').decode())
            await socket.event(type='ping_pong', timestamp=13)
            for digit in '12#987654321012*':
                await socket.event(type='dtmf', digit=digit)
            self.assertEqual(await transport.read_code(timeout=.1), '987654321012')
            self.assertFalse(transport.accepted)
            self.assertTrue(transport.audio.empty())
            self.assertIn({'type': 'ping_pong', 'timestamp': 13}, socket.sent)
            self.assertTrue(await transport.authorize_inbound())
            await socket.event(type='media', payload=base64.b64encode(b'authenticated audio').decode())
            self.assertEqual(await transport.receive_audio(), base64.b64encode(b'authenticated audio').decode())
        finally:
            await transport.close()

    async def test_timeout_and_caller_hangup_do_not_authorize(self):
        socket = Socket()
        transport = DialMediaTransport(socket, collect_code=True)
        try:
            self.assertIsNone(await transport.read_code(timeout=.01))
            self.assertFalse(transport.accepted)
            await socket.event(type='call_ended')
            self.assertIsNone(await transport.read_code(timeout=.1))
            self.assertFalse(await transport.authorize_inbound())
        finally:
            await transport.close()

    async def test_short_code_submission_and_bounded_digit_queue(self):
        socket = Socket()
        transport = DialMediaTransport(socket, collect_code=True)
        try:
            for digit in '123*':
                await socket.event(type='dtmf', digit=digit)
            self.assertEqual(await transport.read_code(timeout=.1), '123')
            for _ in range(40):
                await socket.event(type='dtmf', digit='1')
            await asyncio.wait_for(transport.stopped.wait(), .2)
            self.assertFalse(transport.accepted)
        finally:
            await transport.close()

    async def test_twelve_digits_wait_for_star_and_overlong_code_is_not_truncated(self):
        socket = Socket()
        transport = DialMediaTransport(socket, collect_code=True)
        try:
            pending = asyncio.create_task(transport.read_code(timeout=1))
            for digit in '123456789012':
                await socket.event(type='dtmf', digit=digit)
            await asyncio.sleep(.02)
            self.assertFalse(pending.done())
            self.assertFalse(transport.accepted)
            await socket.event(type='dtmf', digit='*')
            self.assertEqual(await pending, '123456789012')
            for digit in '1234567890129*':
                await socket.event(type='dtmf', digit=digit)
            self.assertEqual(len(await transport.read_code(timeout=.1)), 13)
            self.assertFalse(transport.accepted)
        finally:
            await transport.close()

    async def test_generic_prompt_is_audio_not_a_model_request(self):
        socket = Socket()
        transport = DialMediaTransport(socket, collect_code=True)
        try:
            await transport.play_prompt('dial-inbound')
            self.assertTrue(any(e['type'] == 'media' for e in socket.sent))
            self.assertFalse(transport.accepted)
            with self.assertRaises(ValueError):
                await transport.play_prompt('../private')
        finally:
            await transport.close()


class InboundDeploymentTests(unittest.TestCase):
    def test_current_dial_rate_admits_sixth_greeting_then_stops_at_daily_boundary(self):
        budget = 1_000_000
        stale_rate = inbound.auth_exposure_usd_micro(5, 9, 170_000, RESERVE_USD_MICRO)
        current_rate = inbound.auth_exposure_usd_micro(5, 9, 130_000, RESERVE_USD_MICRO)
        after_another_failure = inbound.auth_exposure_usd_micro(6, 10, 130_000, RESERVE_USD_MICRO)
        self.assertEqual(stale_rate, 1_120_000)
        self.assertGreater(stale_rate, budget)
        self.assertEqual(current_rate, 880_000)
        self.assertLessEqual(current_rate, budget)
        self.assertEqual(after_another_failure, 1_020_000)
        self.assertGreater(after_another_failure, budget)

    def test_disabled_by_default_and_preview_rejects_enabled(self):
        from test_consumer_deployment import PreviewIsolation
        self.assertFalse(PhoneConfig().enabled('RAFII_PHONE_INBOUND_ENABLED'))
        values = isolated_environment(PreviewIsolation().env())
        self.assertFalse(PhoneConfig(values).enabled('RAFII_PHONE_INBOUND_ENABLED'))
        with self.assertRaisesRegex(ValueError, 'must remain disabled'):
            isolated_environment({**PreviewIsolation().env(), 'RAFII_PHONE_INBOUND_ENABLED': '1'})


if __name__ == '__main__':
    unittest.main()
