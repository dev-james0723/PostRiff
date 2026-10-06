"""Synthetic network responses for real ACK timing; no live requests."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from agent_team.events import Event, Journal
from agent_team.transport import send_pending


class Response:
    status = 200

    def __init__(self, accepted):
        self.raw = json.dumps({'accepted': accepted}).encode()

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit): return self.raw[:limit]


class IngressAcknowledgmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.token = root/'token'
        self.token.write_text('synthetic-scoped-token-for-transport-test')
        self.token.chmod(0o600)
        self.journal = Journal(root/'journal.sqlite3')
        self.event = Event('claude', 'fixture-native-turn', 'v1',
            '2026-10-06T21:00:02Z', '2026-10-06T21:00:25Z', {})
        self.journal.ingest([self.event])
        self.endpoint = 'https://fixture.example/api/internal/james-agent-team/events'

    def tearDown(self):
        self.journal.close()
        self.directory.cleanup()

    def send(self, accepted, second=30):
        with patch('agent_team.transport.build_opener') as opener:
            opener.return_value.open.return_value = Response(accepted)
            return send_pending(self.journal, self.endpoint, self.token,
                '2026-10-06T21:00:00Z',
                clock=lambda: datetime(2026, 10, 6, 21, 0, second, tzinfo=timezone.utc))

    def test_slow_scan_uses_actual_ack_time_after_observation(self):
        self.assertEqual(self.send([self.event.key]), {'state':'acknowledged', 'count':1})
        delivered = self.journal.db.execute('SELECT delivered_at FROM observations').fetchone()[0]
        self.assertEqual(delivered, '2026-10-06T21:00:30+00:00')
        self.assertEqual(self.journal.pending(), [])

    def test_clock_before_observation_leaves_delivery_unacknowledged(self):
        with self.assertRaisesRegex(ValueError, 'ingress_ack_clock_precedes_observation'):
            self.send([self.event.key], second=20)
        self.assertEqual(len(self.journal.pending()), 1)

    def test_invalid_server_ack_never_becomes_local_delivery(self):
        with self.assertRaisesRegex(ValueError, 'ingress_ack_invalid'):
            self.send(['unknown-event'])
        self.assertEqual(len(self.journal.pending()), 1)

    def test_partial_ack_keeps_unaccepted_event_pending(self):
        self.assertEqual(self.send([]), {'state':'acknowledged', 'count':0})
        self.assertEqual(len(self.journal.pending()), 1)
