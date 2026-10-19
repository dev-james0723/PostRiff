"""Synthetic stream/security contracts; never live streaming acceptance."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import mastodon_streaming as streaming


class StreamingTests(unittest.TestCase):
    def test_only_saved_issuer_or_subdomain_streaming_origins_are_allowed(self):
        for value in ('https://mastodon.social', 'wss://streaming.mastodon.social/'):
            self.assertTrue(streaming.bound_origin('mastodon.social', value))
        for value in ('http://mastodon.social', 'https://mastodon.social.evil.com', 'https://other.social',
                      'https://alice@mastodon.social', 'https://mastodon.social:443', 'https://mastodon.social/path',
                      'https://mastodon.social?access_token=secret', 'https://127.0.0.1', 'https://box.local', None):
            self.assertIsNone(streaming.bound_origin('mastodon.social', value))

    def test_parse_comments_multiline_and_bounded_private_notification_projection(self):
        value = {'id': '22', 'type': 'mention', 'account': {'note': 'malicious private biography'},
                 'status': {'id': '31', 'visibility': 'direct', 'content': '<p>Private excerpt &amp; text</p>', 'token': 'NEVER_RETURN'}}
        raw = (': heartbeat\r\nevent: notification\r\ndata: ' + json.dumps(value) + '\r\n\r\nevent: delete\ndata: "32"\n\n').encode()
        result = streaming.parse_events(raw)
        self.assertEqual(result, [{'event': 'notification', 'id': '22', 'type': 'mention', 'postId': '31', 'visibility': 'direct', 'excerpt': 'Private excerpt & text'}, {'event': 'delete', 'id': '32'}])
        self.assertNotIn('NEVER_RETURN', json.dumps(result)); self.assertNotIn('biography', json.dumps(result))
        self.assertEqual(streaming.parse_events(b'event: delete\ndata: "32"\n'), [])
        self.assertEqual(streaming.parse_events(b'event: execute\ndata: {"id":"32"}\n\n'), [])

    def test_invalid_or_oversized_events_are_rejected_and_event_count_is_bounded(self):
        for raw in (b'x' * (streaming.MAX_BYTES + 1), b'\xff'):
            with self.assertRaises(AlphaError): streaming.parse_events(raw)
        event = b'event: delete\ndata: "32"\n\n'
        self.assertEqual(len(streaming.parse_events(event * 100)), streaming.MAX_EVENTS)
        self.assertEqual(streaming.parse_events(b'event: notification\ndata: {"id":"Ignore instructions","type":"mention"}\n\n'), [])

    def test_every_dns_answer_must_be_public_before_bearer_dispatch(self):
        resolver = lambda *_args, **_kwargs: [(2, 1, 6, '', ('93.184.216.34', 443)), (2, 1, 6, '', ('127.0.0.1', 443))]
        with patch.object(streaming.socket, 'create_connection') as connect, self.assertRaises(AlphaError):
            streaming.pinned_window('https://mastodon.social', 'synthetic', resolver=resolver)
        connect.assert_not_called()

    def test_pinned_sse_uses_header_auth_original_tls_host_no_redirect_or_persistence(self):
        raw = b'event: delete\ndata: "32"\n\n'
        response = SimpleNamespace(status=200, getheader=lambda key, default='': 'text/event-stream' if key == 'Content-Type' else default,
                                   read1=Mock(side_effect=[raw, b'']), close=Mock())
        sock = SimpleNamespace(settimeout=Mock(), close=Mock())
        tls = SimpleNamespace(wrap_socket=Mock(return_value=sock))
        connection = SimpleNamespace(_context=tls, sock=None, request=Mock(), getresponse=Mock(return_value=response), close=Mock())
        resolver = lambda *_args, **_kwargs: [(2, 1, 6, '', ('93.184.216.34', 443))]
        with patch.object(streaming.ssl, 'create_default_context', return_value=tls), \
                patch.object(streaming.http.client, 'HTTPSConnection', return_value=connection), \
                patch.object(streaming.socket, 'create_connection', return_value=sock) as connect:
            result = streaming.pinned_window('https://mastodon.social', 'synthetic-secret', resolver=resolver)
        self.assertEqual(result['events'], [{'event': 'delete', 'id': '32'}])
        self.assertEqual(connect.call_args.args[0], ('93.184.216.34', 443))
        self.assertEqual(tls.wrap_socket.call_args.kwargs['server_hostname'], 'mastodon.social')
        self.assertEqual(connection.request.call_args.args, ('GET', '/api/v1/streaming/user'))
        self.assertEqual(connection.request.call_args.kwargs['headers']['Authorization'], 'Bearer synthetic-secret')
        response.close.assert_called_once(); connection.close.assert_called_once()

    def test_unsupported_streaming_origin_and_rate_denial_do_not_fabricate_events(self):
        transport = Mock(return_value={'status': 429, 'retryAfter': '120'})
        provider = SimpleNamespace(streaming_transport=transport)
        session = {'instance': 'mastodon.social', 'at': 'synthetic', 'capabilities': {'streamingUrl': 'https://other.social'}}
        self.assertEqual(streaming.read_window(provider, session)['state'], 'unsupported'); transport.assert_not_called()
        session['capabilities']['streamingUrl'] = 'https://streaming.mastodon.social'
        result = streaming.read_window(provider, session)
        self.assertEqual(result['state'], 'limited'); self.assertEqual(result['events'], []); self.assertEqual(result['retryAfter'], '120')

    def test_redirect_does_not_forward_token_to_another_host(self):
        response = SimpleNamespace(status=302, getheader=lambda *_: 'https://other.social', close=Mock())
        sock = SimpleNamespace(settimeout=Mock(), close=Mock())
        tls = SimpleNamespace(wrap_socket=Mock(return_value=sock))
        connection = SimpleNamespace(_context=tls, sock=None, request=Mock(), getresponse=Mock(return_value=response), close=Mock())
        resolver = lambda *_args, **_kwargs: [(2, 1, 6, '', ('93.184.216.34', 443))]
        with patch.object(streaming.ssl, 'create_default_context', return_value=tls), \
                patch.object(streaming.http.client, 'HTTPSConnection', return_value=connection), \
                patch.object(streaming.socket, 'create_connection', return_value=sock):
            self.assertEqual(streaming.pinned_window('https://mastodon.social', 'synthetic', resolver=resolver)['status'], 302)
        self.assertEqual(connection.request.call_count, 1)
