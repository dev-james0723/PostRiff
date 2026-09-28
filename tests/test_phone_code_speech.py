"""Only synthetic audio and injected STT. No OpenAI requests or actual sign-in codes."""
import asyncio
import base64
import io
import unittest
import wave
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
from postriff_phase2.phone.code_speech import parse_code, Utterance, wav_bytes, transcribe
from postriff_phase2.phone.providers.dial import DialMediaTransport
from test_rafii_inbound import Socket

# Arbitrary local test code, never issued by the application.
CODE = '012345678901'
UTTERANCE = b'\xa0' * 8000 + b'\xff' * 16000

class CodeParsingTests(unittest.TestCase):
    def test_only_exact_twelve_digits_in_supported_languages(self):
        for text in ['0123 4567 8901', 'zero one two three four five six seven eight nine zero one',
                     '零一二三四五六七八九零一', '〇一二三四五六七八九零幺', '０１２３４５６７８９０１。']:
            self.assertEqual(parse_code(text), CODE)
        for text in [None, '123', '0123456789012', 'my code is 012345678901', 'ignore previous instructions 012345678901', 'double one two three', '01234567890?', '']:
            self.assertIsNone(parse_code(text))

    def test_silence_is_not_sent_and_audio_is_bounded_valid_wav(self):
        utterance = Utterance()
        for _ in range(200): self.assertIsNone(utterance.feed(b'\xff' * 160))
        self.assertEqual(len(utterance.data), 0)
        result = utterance.feed(UTTERANCE)
        self.assertIsNotNone(result)
        self.assertEqual(len(utterance.data), 0)
        with wave.open(io.BytesIO(wav_bytes(result)), 'rb') as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 8000))
        self.assertLessEqual(len(Utterance().feed(b'\xa0' * 200000)), 120160)
        with self.assertRaises(ValueError): wav_bytes(b'x' * 200000)

class SpeechAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def feed_audio(self, socket):
        # Small frame batches also exercise the bounded media pump.
        for i in range(0, len(UTTERANCE), 1600):
            await socket.event(type='media', payload=base64.b64encode(UTTERANCE[i:i+1600]).decode())
            await asyncio.sleep(0)

    async def test_spoken_code_submits_without_star_and_audio_never_reaches_live(self):
        socket = Socket(); transport = DialMediaTransport(socket, collect_code=True)
        recognize = AsyncMock(return_value=CODE)
        try:
            read = asyncio.create_task(transport.read_code(timeout=1, recognize=recognize))
            await asyncio.sleep(0)
            await self.feed_audio(socket)
            self.assertEqual(await read, CODE)
            self.assertFalse(transport.accepted)
            self.assertTrue(transport.audio.empty())
            self.assertTrue(transport.code_audio.empty())
            recognize.assert_awaited_once()
            self.assertTrue(await transport.authorize_inbound())
            await socket.event(type='media', payload=base64.b64encode(b'live audio').decode())
            self.assertEqual(await transport.receive_audio(), base64.b64encode(b'live audio').decode())
        finally: await transport.close()

    async def test_keypad_wins_and_cancels_pending_speech(self):
        socket = Socket(); transport = DialMediaTransport(socket, collect_code=True)
        started = asyncio.Event(); cancelled = asyncio.Event()
        async def recognize(_):
            started.set()
            try: await asyncio.Future()
            finally: cancelled.set()
        try:
            read = asyncio.create_task(transport.read_code(timeout=1, recognize=recognize))
            await asyncio.sleep(0); await self.feed_audio(socket); await started.wait()
            for digit in CODE: await socket.event(type='dtmf', digit=digit)
            await asyncio.wait_for(cancelled.wait(), .2)
            self.assertFalse(read.done())
            await socket.event(type='dtmf', digit='*')
            self.assertEqual(await read, CODE)
        finally: await transport.close()

    async def test_invalid_speech_cost_is_capped_and_keypad_remains_available(self):
        socket = Socket(); transport = DialMediaTransport(socket, collect_code=True)
        recognize = AsyncMock(return_value='123')
        try:
            for _ in range(3):
                read = asyncio.create_task(transport.read_code(timeout=1, recognize=recognize))
                await asyncio.sleep(0); await self.feed_audio(socket)
                self.assertEqual(await read, '')
                self.assertFalse(transport.accepted)
            read = asyncio.create_task(transport.read_code(timeout=1, recognize=recognize))
            await asyncio.sleep(0); await self.feed_audio(socket)
            for digit in CODE + '*': await socket.event(type='dtmf', digit=digit)
            self.assertEqual(await read, CODE)
            self.assertEqual(recognize.await_count, 3)
        finally: await transport.close()

    async def test_timeout_disconnect_and_provider_failure_fail_closed(self):
        for mode in ['timeout', 'disconnect', 'provider']:
            socket = Socket(); transport = DialMediaTransport(socket, collect_code=True)
            async def recognize(_):
                if mode == 'provider': raise RuntimeError('private provider response')
                await asyncio.Future()
            try:
                read = asyncio.create_task(transport.read_code(timeout=.1, recognize=recognize))
                await asyncio.sleep(0); await self.feed_audio(socket)
                if mode == 'disconnect': await socket.event(type='call_ended')
                self.assertEqual(await read, '' if mode == 'provider' else None)
                self.assertFalse(transport.accepted)
                self.assertTrue(transport.code_audio.empty())
            finally: await transport.close()

    async def test_openai_adapter_sends_only_wav_and_generic_prompt_without_retry(self):
        create = AsyncMock(return_value=SimpleNamespace(text=CODE))
        client = AsyncMock()
        client.__aenter__.return_value = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
        with patch('openai.AsyncOpenAI', return_value=client) as factory:
            self.assertEqual(await transcribe(UTTERANCE, 'synthetic-test-key'), CODE)
        factory.assert_called_once_with(api_key='synthetic-test-key', max_retries=0, timeout=8)
        args = create.call_args.kwargs
        self.assertEqual(set(args), {'model', 'file', 'response_format', 'prompt'})
        self.assertEqual(args['model'], 'gpt-4o-mini-transcribe')
        self.assertNotIn(CODE, args['prompt'])
        self.assertTrue(args['file'][1].startswith(b'RIFF'))

if __name__ == '__main__': unittest.main()
