"""Actual installed Live SDK over loopback; no paid model, PSTN call or production data."""
import asyncio
import base64
import json
import os
import socket
from http import HTTPStatus
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from openai import AsyncOpenAI
from openai import BadRequestError
import httpx2
from openai.types.live.client_event_param import ClientEventParam
from openai.types.live.instructions_append_event_param import InstructionsAppendEventParam
from openai.types.live.commentary_append_event_param import CommentaryAppendEventParam
from pydantic import TypeAdapter
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.server import serve
from websockets.datastructures import Headers

from postriff_phase2.agent_runtime_v2 import live
from postriff_phase2.phone.asgi import create_lazy_app
from postriff_phase2.phone.diagnostics import MediaFailure, metadata, report_failure, handshake_request_id
from postriff_phase2.phone.providers.twilio import TwilioMediaTransport
from postriff_phase2.phone.session import bridge


CALL_ID = '00000000-0000-4000-8000-000000000001'
PRIVATE = 'private +14155550111 Authorization Bearer secret-key transcript words'
AUDIO_IN = base64.b64encode(b'\xff' * 160).decode()
AUDIO_OUT = base64.b64encode(b'\xfe' * 160).decode()


class MediaDiagnosticTest(unittest.TestCase):
    def test_rejected_commands_are_classified_without_logging_echoed_ids(self):
        commands = {'start': 'session_start', 'opening': 'greeting', 'commentary': 'delegation_result',
                    'input': 'input_audio', 'close': 'session_close'}
        for prefix, expected in commands.items():
            with self.subTest(command=expected):
                event = {'error': {'type': 'invalid_request_error', 'code': PRIVATE,
                                  'message': PRIVATE, 'client_event_id': 'phone-' + prefix + '-12'}}
                result = metadata('live_event', event=event)
                self.assertEqual(result.get('rejectedCommand'), expected)
                self.assertNotIn(PRIVATE, json.dumps(result))
                self.assertNotIn('client_event_id', json.dumps(result))
        self.assertEqual(metadata('live_event', event={'client_event_id': 'phone-start-1', 'error': {}}).get('rejectedCommand'),
                         'session_start')

    def test_private_or_malformed_command_correlation_stays_unknown(self):
        for value in (PRIVATE, 'phone-input-0', 'phone-input-12/' + PRIVATE, 'phone-start-1\n' + PRIVATE,
                      {'secret': PRIVATE}, None):
            with self.subTest(value_type=type(value).__name__):
                result = metadata('live_event', event={'error': {'client_event_id': value, 'message': PRIVATE}})
                self.assertEqual(result.get('rejectedCommand'), 'unknown')
                self.assertNotIn(PRIVATE, json.dumps(result))

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
                         {'phase': 'live_event', 'errorCode': 'missing_required_parameter', 'errorParam': 'delegation_id',
                          'rejectedCommand': 'unknown', 'commandEchoState': 'missing',
                          'errorCategory': 'other', 'reasonBasis': 'unclassified'})
        self.assertEqual(metadata('live_event', event={'error': {'code': {'secret': PRIVATE}}}),
                         {'phase': 'live_event', 'errorCode': 'other', 'rejectedCommand': 'unknown',
                          'commandEchoState': 'missing', 'errorCategory': 'other', 'reasonBasis': 'unclassified'})

    def test_actual_sdk_exception_preserves_known_details_and_opaque_request_id(self):
        request_id = 'req_' + 'a' * 32
        response = httpx2.Response(400, request=httpx2.Request('GET', 'https://api.openai.com/v1/live/sessions'),
                                   headers={'x-request-id': request_id, 'Authorization': PRIVATE})
        error = BadRequestError(PRIVATE, response=response, body={'code': 'unsupported_sample_rate',
            'type': 'invalid_request_error', 'param': 'audio.format.rate', 'message': PRIVATE})
        result = metadata('live_connect', error)
        self.assertEqual((result['errorCode'], result['errorType'], result['errorParam']),
                         ('unsupported_sample_rate', 'invalid_request_error', 'audio.format.rate'))
        self.assertEqual((result['errorCategory'], result['reasonBasis']), ('audio_format', 'exact_code'))
        self.assertEqual((result['httpStatus'], result['providerRequestId']), (400, request_id))
        self.assertNotIn(PRIVATE, json.dumps(result))
        self.assertNotIn('Authorization', json.dumps(result))

    def test_exception_attributes_and_bounded_upgrade_body_are_reduced_to_enums(self):
        error = RuntimeError(PRIVATE)
        error.code, error.type, error.param = 'invalid_value', 'invalid_request_error', 'audio.format.type'
        result = metadata('live_event', error, live_started=False, greeting_sent=False)
        self.assertEqual((result['errorParam'], result['errorCategory'], result['reasonBasis']),
                         ('audio.format.type', 'audio_format', 'code_param'))
        self.assertEqual((result['rejectedCommand'], result['commandEchoState']), ('unknown', 'missing'))
        self.assertNotIn(PRIVATE, json.dumps(result))
        error = RuntimeError(PRIVATE)
        error.response = SimpleNamespace(status_code=400, body=bytearray(json.dumps({'error': {
            'code': 'unknown_parameter', 'type': 'invalid_request_error', 'param': 'session.model',
            'client_event_id': 'phone-start-1', 'message': PRIVATE}}).encode()), headers={})
        result = metadata('live_connect', error)
        self.assertEqual((result['errorCode'], result['errorParam']), ('unknown_parameter', 'session.model'))
        self.assertEqual((result['rejectedCommand'], result['commandEchoState']), ('session_start', 'known'))
        error.response.body = bytearray(b'a' * 8193)
        self.assertNotIn('errorCode', metadata('live_connect', error))

    def test_request_id_rejects_pii_nonhex_wrong_length_and_other_headers(self):
        for value in (PRIVATE, 'req_' + 'a' * 31, 'req_' + 'a' * 33, 'req_' + 'z' * 32,
                      'req_' + 'A' * 32, {'private': PRIVATE}, None):
            error = RuntimeError(PRIVATE)
            error.request_id = value
            error.response = SimpleNamespace(headers={'x-request-id': value, 'Authorization': PRIVATE})
            result = metadata('live_connect', error)
            self.assertNotIn('providerRequestId', result)
            self.assertNotIn(PRIVATE, json.dumps(result))
        error.response.headers['x-request-id'] = 'req_' + 'b' * 32
        self.assertEqual(metadata('live_connect', error)['providerRequestId'], 'req_' + 'b' * 32)

    def test_finite_audio_capacity_codes_and_quota_require_exact_code_evidence(self):
        for code, category in (('unsupported_audio_format', 'audio_format'), ('invalid_audio_format', 'audio_format'),
                ('unsupported_sample_rate', 'audio_format'), ('invalid_sample_rate', 'audio_format'),
                ('too_many_concurrent_sessions', 'live_capacity'), ('too_many_concurrent_live_sessions', 'live_capacity'),
                ('concurrent_session_limit_exceeded', 'live_capacity'), ('live_session_concurrency_limit', 'live_capacity'),
                ('insufficient_quota', 'quota'), ('credit_balance_exhausted', 'credits_exhausted'),
                ('organization_spend_limit_exceeded', 'spend_limit'), ('project_spend_limit_exceeded', 'spend_limit'),
                ('organization_usage_limit_exceeded', 'usage_limit'), ('slow_down', 'rate_limit'),
                ('server_is_overloaded', 'provider_capacity')):
            result = metadata('live_event', event={'error': {'code': code, 'message': PRIVATE}})
            self.assertEqual((result['errorCode'], result['errorCategory'], result['reasonBasis']),
                             (code, category, 'exact_code'))
            self.assertNotIn(PRIVATE, json.dumps(result))
        error = RuntimeError(PRIVATE)
        error.response = SimpleNamespace(status_code=429)
        result = metadata('live_event', error, event={'error': {
            'code': 'invalid_request_error', 'type': 'invalid_request_error', 'message': 'Insufficient quota. ' + PRIVATE}},
            live_started=False, greeting_sent=False)
        self.assertEqual((result['errorCategory'], result['reasonBasis']), ('other', 'unclassified'))
        self.assertEqual(result['httpStatus'], 429)
        self.assertNotIn(PRIVATE, json.dumps(result))

    def test_server_event_id_never_substitutes_for_missing_command_echo(self):
        result = metadata('live_event', event={'type': 'error', 'event_id': 'phone-start-1',
            'error': {'type': 'invalid_request_error', 'code': PRIVATE}}, live_started=False, greeting_sent=False)
        self.assertEqual((result['rejectedCommand'], result['commandEchoState']), ('unknown', 'missing'))
        self.assertFalse(result['liveStarted'])
        self.assertFalse(result['greetingSent'])
        for value, state in ((PRIVATE, 'unrecognized'), ({'private': PRIVATE}, 'invalid_type')):
            result = metadata('live_event', event={'error': {'client_event_id': value}})
            self.assertEqual((result['rejectedCommand'], result['commandEchoState']), ('unknown', state))
            self.assertNotIn(PRIVATE, json.dumps(result))

    def test_upgrade_request_id_comes_only_from_single_sdk_socket_header(self):
        request_id = 'req_' + 'c' * 32
        connection = SimpleNamespace(_connection=SimpleNamespace(response=SimpleNamespace(headers=Headers(
            [('x-request-id', request_id), ('Authorization', PRIVATE), ('x-session-id', PRIVATE)]))),
            request_id=PRIVATE, event_id=PRIVATE, session_id=PRIVATE)
        self.assertEqual(handshake_request_id(connection), request_id)
        with self.assertLogs('rafii.phone.media', level='WARNING') as logs:
            report_failure(CALL_ID, 'live_event', event={'error': {'type': 'invalid_request_error', 'code': PRIVATE}},
                live_started=False, greeting_sent=False, provider_request_id=handshake_request_id(connection))
        self.assertIn(request_id, logs.output[0])
        self.assertIn('"rejectedCommand": "unknown"', logs.output[0])
        self.assertIn('"commandEchoState": "missing"', logs.output[0])
        self.assertNotIn(PRIVATE, logs.output[0])
        connection._connection.response.headers['x-request-id'] = 'req_' + 'd' * 32
        self.assertIsNone(handshake_request_id(connection))  # Duplicate headers are ambiguous, not a new failure.
        error = RuntimeError(PRIVATE)
        error.response = connection._connection.response
        self.assertNotIn('providerRequestId', metadata('live_connect', error))
        connection._connection.response.headers = Headers([('x-request-id', PRIVATE)])
        self.assertIsNone(handshake_request_id(connection))
        self.assertIsNone(handshake_request_id(SimpleNamespace(response=SimpleNamespace(headers={'x-request-id': request_id}))))
        for value in (PRIVATE, 'req_' + 'z' * 32, 'req_' + 'a' * 31, None):
            result = metadata('live_event', request_id=value)
            self.assertNotIn('providerRequestId', result)
        failure = MediaFailure('live_receive', RuntimeError(PRIVATE), provider_request_id=request_id)
        self.assertEqual(failure.diagnostic['providerRequestId'], request_id)
        self.assertNotIn(PRIVATE, json.dumps(failure.diagnostic))

    def test_actual_sdk_manager_exposes_only_upgrade_request_id_without_network(self):
        from openai.lib import _websocket
        request_id = 'req_' + 'e' * 32
        class FakeSocket:
            def __init__(self):
                self.response = SimpleNamespace(headers=Headers([('x-request-id', request_id), ('Authorization', PRIVATE)]))
                self.closed = False
            async def close(self, **_kwargs):
                self.closed = True
        captured = FakeSocket()
        async def connect(_url, **_kwargs):
            return captured
        async def inspect():
            with patch.dict(os.environ, {}, clear=True), patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')), \
                    patch.object(_websocket, '_WebSocketConnect', connect):
                async with AsyncOpenAI(api_key='sk-offline-private-placeholder', max_retries=0) as client:  # pragma: allowlist secret -- synthetic key; WebSocket mocked and socket.connect blocked
                    async with client.live.connect() as connection:
                        self.assertEqual(handshake_request_id(connection), request_id)
                        result = metadata('live_event', event={'error': {'type': 'invalid_request_error'}},
                                          live_started=False, request_id=handshake_request_id(connection))
                        self.assertEqual(result['providerRequestId'], request_id)
                        self.assertEqual(result['rejectedCommand'], 'unknown')
                        self.assertNotIn(PRIVATE, json.dumps(result))
        asyncio.run(inspect())
        self.assertTrue(captured.closed)

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
        for event in received:
            TypeAdapter(ClientEventParam).validate_python(event)
            self.assertRegex(event.get('event_id', ''), r'^phone-[a-z]+-[1-9][0-9]*$')
        self.assertEqual(len({event['event_id'] for event in received}), len(received))
        TypeAdapter(InstructionsAppendEventParam).validate_python(received[1])
        self.assertIsNone(received[1]['delegation_id'])
        self.assertIn('Speak first now.', received[1]['content'])
        self.assertEqual(received[2]['type'], 'session.input_audio.append')
        self.assertEqual(received[2]['audio'], AUDIO_IN)
        self.assertEqual(socket.outgoing, [{'event': 'media', 'streamSid': 'MZ-local', 'media': {'payload': AUDIO_OUT}}])
        self.assertEqual(controller.started_ids, ['local-live-session'])
        self.assertEqual(controller.hangups, [(CALL_ID, {'live_seconds': 2.5, 'reason': 'completed'})])
        self.assertEqual(controller.finishes, [(CALL_ID, 'completed', {'live_seconds': 2.5})])

    async def test_server_initiated_daily_briefing_uses_one_short_speak_first_directive(self):
        controller, socket, received = Controller(), Socket(), []
        controller.last_input_at = 0
        controller.call['destination_ref'] = 'james_env'
        controller.delegate = lambda _event: {
            'type': 'session.commentary.append',
            'delegation_id': 'james-daily-briefing',
            'content': 'Verified daily briefing result.'
        }
        async def server(ws):
            received.append(json.loads(await ws.recv()))
            await ws.send(json.dumps({'type': 'session.started', 'session': {'id': 'local-live-session'}}))
            received.append(json.loads(await ws.recv()))
            await ws.send(json.dumps({'type': 'session.closed', 'usage': {'seconds': 1}}))
        async with serve(server, '127.0.0.1', 0) as local:
            port = local.sockets[0].getsockname()[1]
            async with AsyncOpenAI(api_key='local-test', base_url=f'http://127.0.0.1:{port}/v1', max_retries=0) as client:
                async with client.live.connect() as connection:
                    await asyncio.wait_for(bridge(controller, TwilioMediaTransport(socket, 'MZ-local'), connection), 8)
        self.assertEqual([event['type'] for event in received],
                         ['session.start', 'session.instructions.append'])
        TypeAdapter(InstructionsAppendEventParam).validate_python(received[1])
        self.assertIsNone(received[1]['delegation_id'])
        self.assertIn('Speak first now.', received[1]['content'])
        self.assertIn('personal daily briefing', received[1]['content'])
        self.assertNotIn('james-daily-briefing', json.dumps(received[1]))

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

    async def test_sdk_validates_every_correlated_command_and_repeated_audio_has_unique_ids(self):
        controller, socket, received = Controller(), Socket(), []
        controller.last_input_at = 0
        controller.delegate = lambda _: {'type': 'session.commentary.append', 'delegation_id': 'local-delegation',
                                         'content': 'Synthetic result.'}
        async def server(ws):
            received.append(json.loads(await ws.recv()))
            await ws.send(json.dumps({'type': 'session.started', 'session': {'id': 'local-live-session'}}))
            received.append(json.loads(await ws.recv()))
            await socket.incoming.put({'event': 'media', 'media': {'payload': AUDIO_IN}})
            await socket.incoming.put({'event': 'media', 'media': {'payload': AUDIO_IN}})
            received.append(json.loads(await ws.recv()))
            received.append(json.loads(await ws.recv()))
            await ws.send(json.dumps({'type': 'session.delegation.created',
                                      'delegation': {'id': 'local-delegation', 'target': 'client'}}))
            received.append(json.loads(await ws.recv()))
            await socket.incoming.put({'event': 'stop'})
            received.append(json.loads(await ws.recv()))
            await ws.send(json.dumps({'type': 'session.closed', 'usage': {'seconds': 2}}))
        async with serve(server, '127.0.0.1', 0) as local:
            port = local.sockets[0].getsockname()[1]
            async with AsyncOpenAI(api_key='local-test', base_url=f'http://127.0.0.1:{port}/v1', max_retries=0) as client:
                async with client.live.connect() as connection:
                    await asyncio.wait_for(bridge(controller, TwilioMediaTransport(socket, 'MZ-local'), connection), 8)
        self.assertEqual([event['type'] for event in received], ['session.start', 'session.instructions.append',
            'session.input_audio.append', 'session.input_audio.append', 'session.commentary.append', 'session.close'])
        for event in received:
            TypeAdapter(ClientEventParam).validate_python(event)
        self.assertEqual(len({event['event_id'] for event in received}), len(received))
        self.assertEqual(controller.hangups, [(CALL_ID, {'live_seconds': 2, 'reason': 'completed'})])
        self.assertEqual(controller.finishes, [(CALL_ID, 'completed', {'live_seconds': 2})])

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

    async def test_rejected_start_greeting_result_and_audio_classify_and_still_settle_failed(self):
        for rejected in ('session_start', 'greeting', 'delegation_result', 'input_audio'):
            with self.subTest(rejected=rejected):
                controller, socket = Controller(), Socket()
                controller.last_input_at = 0
                controller.delegate = lambda _: {'type': 'session.commentary.append', 'delegation_id': 'local-delegation',
                                                 'content': 'Synthetic result.'}
                async def server(ws):
                    command = json.loads(await ws.recv())
                    if rejected != 'session_start':
                        await ws.send(json.dumps({'type': 'session.started', 'session': {'id': 'local-live-session'}}))
                        command = json.loads(await ws.recv())
                    if rejected == 'delegation_result':
                        await ws.send(json.dumps({'type': 'session.delegation.created',
                                                  'delegation': {'id': 'local-delegation', 'target': 'client'}}))
                        command = json.loads(await ws.recv())
                    elif rejected == 'input_audio':
                        await socket.incoming.put({'event': 'media', 'media': {'payload': AUDIO_IN}})
                        command = json.loads(await ws.recv())
                    TypeAdapter(ClientEventParam).validate_python(command)
                    await ws.send(json.dumps({'type': 'error', 'error': {'type': 'invalid_request_error',
                        'code': PRIVATE, 'message': PRIVATE, 'client_event_id': command.get('event_id')}}))
                    await ws.wait_closed()
                async with serve(server, '127.0.0.1', 0) as local:
                    port = local.sockets[0].getsockname()[1]
                    async with AsyncOpenAI(api_key='local-test', base_url=f'http://127.0.0.1:{port}/v1', max_retries=0) as client:
                        async with client.live.connect() as connection:
                            with self.assertLogs('rafii.phone.media', level='WARNING') as logs:
                                await asyncio.wait_for(bridge(controller, TwilioMediaTransport(socket, 'MZ-local'), connection), 8)
                failure = next(line for line in logs.output if '"phase": "live_event"' in line)
                self.assertIn('"rejectedCommand": "' + rejected + '"', failure)
                self.assertIn('"liveStarted": ' + ('false' if rejected == 'session_start' else 'true'), failure)
                self.assertIn('"greetingSent": ' + ('false' if rejected == 'session_start' else 'true'), failure)
                self.assertNotIn(PRIVATE, '\n'.join(logs.output))
                self.assertNotIn('client_event_id', failure)
                self.assertEqual(controller.hangups, [(CALL_ID, {'live_seconds': None, 'reason': 'failed'})])
                self.assertEqual(controller.finishes, [(CALL_ID, 'failed', {'live_seconds': None})])
                self.assertEqual(controller.media_failures, [CALL_ID])
                self.assertTrue(controller.closed)

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
