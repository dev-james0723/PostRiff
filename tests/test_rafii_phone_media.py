"""Actual installed Live SDK over loopback; no paid model, PSTN call or production data."""
import asyncio
import base64
import json
from http import HTTPStatus
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from openai import AsyncOpenAI
from openai.types.live.instructions_append_event_param import InstructionsAppendEventParam
from openai.types.live.commentary_append_event_param import CommentaryAppendEventParam
from pydantic import TypeAdapter
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.server import serve

from postriff_phase2.agent_runtime_v2 import live
from postriff_phase2.phone.asgi import create_lazy_app
from postriff_phase2.phone.diagnostics import MediaFailure, metadata, report_failure
from postriff_phase2.phone.providers.twilio import TwilioMediaTransport
from postriff_phase2.phone.session import bridge


CALL_ID = '00000000-0000-4000-8000-000000000001'
PRIVATE = 'private +14155550111 Authorization Bearer secret-key transcript words'
AUDIO_IN = base64.b64encode(b'\xff' * 160).decode()
AUDIO_OUT = base64.b64encode(b'\xfe' * 160).decode()


class MediaDiagnosticTest(unittest.TestCase):
    def test_exception_and_event_diagnostics_drop_private_payloads(self):
        error = RuntimeError(PRIVATE)
        error.code = PRIVATE
        error.response = SimpleNamespace(status_code=401, body=PRIVATE, headers={'Authorization': PRIVATE})
        with self.assertLogs('rafii.phone.media', level='WARNING') as logs:
            report_failure(CALL_ID, 'live_connect', error)
            report_failure(PRIVATE, PRIVATE, event={'error': {'code': 'invalid_request_error', 'message': PRIVATE,
                'type': PRIVATE, 'param': PRIVATE}})
        output = '\n'.join(logs.output)
        self.assertNotIn(PRIVATE, output)
        self.assertNotIn('Authorization', output)
        self.assertIn('"httpStatus": 401', output)
        self.assertIn('"errorCode": "other"', output)
        self.assertIn('"errorCode": "invalid_request_error"', output)
        self.assertIn('"errorType": "other"', output)
        self.assertIn('"errorParam": "other"', output)
        self.assertIn('"phase": "unknown"', output)
        self.assertEqual(output.count(CALL_ID), 1)
        self.assertEqual(metadata('live_event', event={'error': {'code': 'missing_required_parameter', 'param': 'delegation_id'}}),
                         {'phase': 'live_event', 'errorCode': 'missing_required_parameter', 'errorParam': 'delegation_id'})
        self.assertEqual(metadata('live_event', event={'error': {'code': {'secret': PRIVATE}}}),
                         {'phase': 'live_event', 'errorCode': 'other'})

    def test_lazy_runtime_failure_stays_closed_and_reports_only_safe_metadata(self):
        def unavailable():
            raise TypeError(PRIVATE)
        app = create_lazy_app(values={'RAFII_PHONE_ENABLED': '1'}, application_factory=unavailable)
        with self.assertLogs('rafii.phone.media', level='WARNING') as logs, TestClient(app) as client:
            with self.assertRaises(WebSocketDisconnect) as caught:
                with client.websocket_connect('/api/phone/media/' + CALL_ID):
                    self.fail('Unavailable runtime accepted a stream')
        self.assertEqual(caught.exception.code, 1008)
        self.assertIn('"phase": "runtime_init"', logs.output[0])
        self.assertIn('"errorClass": "TypeError"', logs.output[0])
        self.assertNotIn(PRIVATE, logs.output[0])


class Controller:
    def __init__(self):
        self.call_id, self.closed = CALL_ID, False
        self.call = {'workspace_id': 'local-workspace', 'kind': 'explicit', 'max_seconds': 10}
        self.capability = 'local-capability'
        self.runtime = SimpleNamespace(service=SimpleNamespace(get=lambda *_: None))
        self.media_failures = []
        self.service = SimpleNamespace(hangup=self.hangup, finish=self.finish, record_live_usage=self.record,
                                       record_media_failure=self.media_failures.append)
        self.started_ids, self.hangups, self.finishes, self.transcripts = [], [], [], []
        self.user_text = ''
        self.opening_greeting = 'Greet the caller now in Cantonese and pause to listen.'

    def guard(self):
        return self.runtime.service.get(self.call['workspace_id'],self.capability)

    def configuration(self):
        config = live.session_config('gpt-live-1', 'yue', 'marin', history='Synthetic previous conversation.')
        config['audio']['format'] = {'type': 'audio/pcmu', 'rate': 8000}
        return config

    def started(self, value):
        self.started_ids.append(value)

    def transcript(self, event):
        self.transcripts.append(event)

    def hangup(self, call_id, **kwargs):
        self.hangups.append((call_id, kwargs))
        return {'ended': True}

    def finish(self, call_id, reason, **kwargs):
        self.finishes.append((call_id, reason, kwargs))

    def record(self, *_):
        raise AssertionError('Confirmed local hangup must settle through finish')


class Socket:
    def __init__(self):
        self.incoming, self.outgoing = asyncio.Queue(), []

    async def receive_json(self):
        return await self.incoming.get()

    async def send_json(self, event):
        self.outgoing.append(event)
        if event['event'] == 'media':
            await self.incoming.put({'event': 'media', 'media': {'payload': AUDIO_IN}})


class LiveSDKMediaTest(unittest.IsolatedAsyncioTestCase):
    async def test_actual_sdk_and_twilio_transport_exchange_pcmu_and_final_usage(self):
        controller, socket, received = Controller(), Socket(), []
        async def server(ws):
            received.append(json.loads(await ws.recv()))
            await ws.send(json.dumps({'type': 'session.started', 'session': {'id': 'local-live-session'}}))
            received.append(json.loads(await ws.recv()))
            await ws.send(json.dumps({'type': 'session.output_audio.delta', 'delta': AUDIO_OUT}))
            received.append(json.loads(await ws.recv()))
            await ws.send(json.dumps({'type': 'session.closed', 'usage': {'seconds': 2.5}}))
        async with serve(server, '127.0.0.1', 0) as local:
            port = local.sockets[0].getsockname()[1]
            async with AsyncOpenAI(api_key='local-test', base_url=f'http://127.0.0.1:{port}/v1', max_retries=0) as client:
                async with client.live.connect() as connection:
                    with patch('postriff_phase2.phone.diagnostics.LOG.warning') as warning:
                        await asyncio.wait_for(bridge(controller, TwilioMediaTransport(socket, 'MZ-local'), connection), 8)
                    warning.assert_not_called()
        self.assertEqual(received[0]['type'], 'session.start')
        self.assertEqual(received[0]['session']['audio']['format'], {'type': 'audio/pcmu', 'rate': 8000})
        self.assertFalse(received[0]['session']['store'])
        TypeAdapter(InstructionsAppendEventParam).validate_python(received[1])
        self.assertIsNone(received[1]['delegation_id'])
        self.assertEqual(received[2], {'type': 'session.input_audio.append', 'audio': AUDIO_IN})
        self.assertEqual(socket.outgoing, [{'event': 'media', 'streamSid': 'MZ-local', 'media': {'payload': AUDIO_OUT}}])
        self.assertEqual(controller.started_ids, ['local-live-session'])
        self.assertEqual(controller.hangups, [(CALL_ID, {'live_seconds': 2.5, 'reason': 'completed'})])
        self.assertEqual(controller.finishes, [(CALL_ID, 'completed', {'live_seconds': 2.5})])

    async def test_delegation_failure_commentary_matches_required_nullable_sdk_field(self):
        controller, socket, received = Controller(), Socket(), []
        controller.last_input_at = 0
        def unavailable(_event):
            raise RuntimeError(PRIVATE)
        controller.delegate = unavailable
        async def server(ws):
            await ws.recv()
            await ws.send(json.dumps({'type': 'session.started', 'session': {'id': 'local-live-session'}}))
            greeting = json.loads(await ws.recv())
            TypeAdapter(InstructionsAppendEventParam).validate_python(greeting)
            await ws.send(json.dumps({'type': 'session.delegation.created',
                                      'delegation': {'id': 'local-delegation', 'target': 'client'}}))
            received.append(json.loads(await ws.recv()))
            await ws.send(json.dumps({'type': 'session.closed', 'usage': {'seconds': 1}}))
        async with serve(server, '127.0.0.1', 0) as local:
            port = local.sockets[0].getsockname()[1]
            async with AsyncOpenAI(api_key='local-test', base_url=f'http://127.0.0.1:{port}/v1', max_retries=0) as client:
                async with client.live.connect() as connection:
                    await asyncio.wait_for(bridge(controller, TwilioMediaTransport(socket, 'MZ-local'), connection), 8)
        TypeAdapter(CommentaryAppendEventParam).validate_python(received[0])
        self.assertIsNone(received[0]['delegation_id'])
        self.assertNotIn(PRIVATE, json.dumps(received))

    async def test_sdk_admission_error_has_safe_code_and_retains_unknown_usage(self):
        controller, socket = Controller(), Socket()
        async def server(ws):
            await ws.recv()
            await ws.send(json.dumps({'type': 'error', 'error': {'code': 'insufficient_quota', 'message': PRIVATE}}))
            await ws.wait_closed()
        async with serve(server, '127.0.0.1', 0) as local:
            port = local.sockets[0].getsockname()[1]
            async with AsyncOpenAI(api_key='local-test', base_url=f'http://127.0.0.1:{port}/v1', max_retries=0) as client:
                async with client.live.connect() as connection:
                    with self.assertLogs('rafii.phone.media', level='WARNING') as logs:
                        await asyncio.wait_for(bridge(controller, TwilioMediaTransport(socket, 'MZ-local'), connection), 8)
        self.assertIn('"phase": "live_event"', logs.output[0])
        self.assertIn('"errorCode": "insufficient_quota"', logs.output[0])
        self.assertNotIn(PRIVATE, '\n'.join(logs.output))
        self.assertEqual(controller.hangups, [(CALL_ID, {'live_seconds': None, 'reason': 'failed'})])
        self.assertEqual(socket.outgoing, [])
        self.assertEqual(controller.started_ids, [])
        self.assertEqual(controller.media_failures, [CALL_ID])

    async def test_real_sdk_upgrade_rejection_is_reported_without_response_body(self):
        attempts = []
        async def reject(ws, request):
            attempts.append(request.path)
            return ws.respond(HTTPStatus.UNAUTHORIZED, PRIVATE)
        async with serve(lambda _: None, '127.0.0.1', 0, process_request=reject) as local:
            port = local.sockets[0].getsockname()[1]
            async with AsyncOpenAI(api_key='local-test', base_url=f'http://127.0.0.1:{port}/v1', max_retries=0) as client:
                try:
                    async with client.live.connect():
                        self.fail('Unauthorized WebSocket accepted')
                except Exception as error:
                    with self.assertLogs('rafii.phone.media', level='WARNING') as logs:
                        report_failure(CALL_ID, 'live_connect', error)
        self.assertEqual(attempts, ['/v1/live/sessions'])
        self.assertIn('"httpStatus": 401', logs.output[0])
        self.assertIn('"errorClass": "InvalidStatus"', logs.output[0])
        self.assertNotIn(PRIVATE, logs.output[0])

    async def test_sdk_stream_closed_before_started_is_not_a_success(self):
        controller, socket = Controller(), Socket()
        async def server(ws):
            await ws.recv()
            await ws.close()
        async with serve(server, '127.0.0.1', 0) as local:
            port = local.sockets[0].getsockname()[1]
            async with AsyncOpenAI(api_key='local-test', base_url=f'http://127.0.0.1:{port}/v1', max_retries=0) as client:
                async with client.live.connect() as connection:
                    with self.assertLogs('rafii.phone.media', level='WARNING') as logs:
                        await asyncio.wait_for(bridge(controller, TwilioMediaTransport(socket, 'MZ-local'), connection), 8)
        self.assertIn('"phase": "live_receive"', logs.output[0])
        self.assertIn('"errorCode": "stream_closed"', logs.output[0])
        self.assertEqual(controller.hangups, [(CALL_ID, {'live_seconds': None, 'reason': 'failed'})])
        self.assertEqual(socket.outgoing, [])

    async def test_started_callback_failure_reports_its_phase_and_still_hangs_up(self):
        class BrokenController(Controller):
            def started(self, value):
                raise TypeError(PRIVATE)
        controller, socket = BrokenController(), Socket()
        async def server(ws):
            await ws.recv()
            await ws.send(json.dumps({'type': 'session.started', 'session': {'id': 'local-live-session'}}))
            await ws.wait_closed()
        async with serve(server, '127.0.0.1', 0) as local:
            port = local.sockets[0].getsockname()[1]
            async with AsyncOpenAI(api_key='local-test', base_url=f'http://127.0.0.1:{port}/v1', max_retries=0) as client:
                async with client.live.connect() as connection:
                    with self.assertRaises(MediaFailure) as caught:
                        await asyncio.wait_for(bridge(controller, TwilioMediaTransport(socket, 'MZ-local'), connection), 8)
        with self.assertLogs('rafii.phone.media', level='WARNING') as logs:
            report_failure(CALL_ID, 'live_bridge', caught.exception)
        self.assertIn('"phase": "live_started"', logs.output[0])
        self.assertIn('"errorClass": "TypeError"', logs.output[0])
        self.assertNotIn(PRIVATE, logs.output[0])
        self.assertEqual(controller.hangups, [(CALL_ID, {'live_seconds': None, 'reason': 'failed'})])
        self.assertEqual(socket.outgoing, [])


if __name__ == '__main__':
    unittest.main()
