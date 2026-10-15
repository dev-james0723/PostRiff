"""Content-free task notifications; no providers or database required."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_phase2.agent_runtime_v2.task_engine import notifications
from postriff_phase2.notifications.store import _clean_payload

TASK = '12345678-1234-4234-8234-123456789012'
ACTOR = '00000000-0000-0000-0000-00000000d101'


class TaskNotificationRules(unittest.TestCase):
    def task(self, **values):
        return dict(taskId=TASK, createdBy=ACTOR, workspaceId=ACTOR, state='completed',
                    version=2, updatedAt=1, title='PRIVATE TITLE', **values)

    def test_only_actionable_or_terminal_states(self):
        task = self.task()
        for state in ('created', 'running', 'queued', 'cancelled'):
            self.assertIsNone(notifications.event_for({**task, 'state': state}))
        for state in notifications.STATES:
            self.assertIsNotNone(notifications.event_for({**task, 'state': state}))

    def test_no_private_content_or_external_channels(self):
        event = notifications.event_for(self.task())
        self.assertNotIn('PRIVATE', str(event))
        self.assertEqual(event['channel_filter'], ('in_app',))
        self.assertEqual(event['actor'], ACTOR)
        self.assertEqual(event['payload']['href'], '/app/tasks?task=' + TASK)
        for spec in notifications.EVENTS.values():
            self.assertEqual((spec['audience'], spec['email'], spec['push'], spec['sms']), ('actor', 'off', 'off', 'off'))

    def test_authoritative_version_and_identity_required(self):
        task = self.task()
        for value in (None, True, -1, '2'):
            self.assertIsNone(notifications.event_for({**task, 'version': value}))
        for field in ('createdBy', 'taskId'):
            self.assertIsNone(notifications.event_for({**task, field: 'bad'}))
        a = notifications.event_for(task)['dedupe_key']
        self.assertEqual(a, notifications.event_for(task)['dedupe_key'])
        self.assertNotEqual(a, notifications.event_for({**task, 'version': 3})['dedupe_key'])

    def test_exact_task_link_survives_phone_redaction(self):
        href = '/app/tasks?task=' + TASK
        self.assertEqual(_clean_payload({'href': href})['href'], href)
        self.assertIn('[redacted phone]', _clean_payload({'detail': 'Call 1234567890'})['detail'])
        self.assertIn('[redacted phone]', _clean_payload({'href': href + '&phone=1234567890'})['href'])

    def test_disabled_or_shadow_never_connects(self):
        service = SimpleNamespace(notifications=Mock(), repository=Mock())
        runtime = SimpleNamespace(service=service, cfg=None)
        with patch.object(notifications.flags, 'anywhere', return_value=False):
            self.assertEqual(notifications.scan(runtime)['status'], 'disabled')
        service.notifications.enabled.return_value = False
        self.assertEqual(notifications.scan(runtime)['status'], 'disabled')
        service.repository.connection_factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
