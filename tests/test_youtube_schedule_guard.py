"""Native-schedule dispatch controls; synthetic provider only, no external requests."""
import copy
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.youtube.api import MIN_SCHEDULE_LEAD_SECONDS, YouTubeApi
from postriff_phase2.youtube.model import MANAGE


class NativeScheduleDispatchTests(unittest.TestCase):
    def setUp(self):
        self.now = [1_800_000_000.0]
        self.sent, self.admissions = [], []
        self.admission_wait = 0

        def reserve(*attempt):
            self.admissions.append(attempt)
            self.now[0] += self.admission_wait

        def transport(token, method, url, **kwargs):
            self.sent.append((token, method, url, kwargs))
            return {'status': 200, 'body': {'id': 'abcdefghijk'}}

        self.api = YouTubeApi(SimpleNamespace(api=transport),
                              {'accessToken': 'synthetic', 'scopes': [MANAGE]},
                              'UC' + 'a' * 22, clock=lambda: self.now[0], account_usage=reserve)

    def schedule_body(self, seconds):
        planned = datetime.fromtimestamp(self.now[0] + seconds, timezone.utc).isoformat().replace('+00:00', 'Z')
        return {'id': 'abcdefghijk', 'status': {'privacyStatus': 'private', 'publishAt': planned}}

    def test_admission_wait_expiring_future_schedule_sends_nothing(self):
        body = self.schedule_body(90)
        original = copy.deepcopy(body)
        self.admission_wait = 120
        with self.assertRaises(AlphaError) as caught:
            self.api.call('videos.update', {'part': 'status'}, body)
        self.assertEqual(caught.exception.code, 'youtube_invalid_scheduling_state')
        self.assertEqual(len(self.admissions), 1)  # No optimistic quota refund.
        self.assertEqual(self.sent, [])
        self.assertEqual(body, original)  # Never replace an expired schedule with immediate visibility.

    def test_admission_wait_consuming_timeout_buffer_sends_nothing(self):
        self.admission_wait = 31
        with self.assertRaises(AlphaError) as caught:
            self.api.call('videos.update', {'part': 'status'}, self.schedule_body(90))
        self.assertEqual(caught.exception.code, 'youtube_invalid_scheduling_state')
        self.assertIn('60 seconds', str(caught.exception))
        self.assertEqual(len(self.admissions), 1)
        self.assertEqual(self.sent, [])

    def test_expired_and_short_lead_rejected_before_admission(self):
        for lead in (-1, 0, MIN_SCHEDULE_LEAD_SECONDS - 0.001):
            with self.subTest(lead=lead), self.assertRaises(AlphaError):
                self.api.call('videos.update', {'part': 'status'}, self.schedule_body(lead))
        self.assertEqual(self.admissions, [])
        self.assertEqual(self.sent, [])

    def test_exact_minimum_lead_is_preserved(self):
        body = self.schedule_body(MIN_SCHEDULE_LEAD_SECONDS)
        self.api.call('videos.update', {'part': 'status'}, body)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][3]['body'], body)

    def test_metadata_and_schedule_removal_retain_behavior(self):
        for body in ({'id': 'abcdefghijk', 'snippet': {'title': 'Reviewed title'}},
                     {'id': 'abcdefghijk', 'status': {'privacyStatus': 'private'}},
                     {'id': 'abcdefghijk', 'status': {'privacyStatus': 'private', 'publishAt': None}}):
            with self.subTest(body=body):
                before = len(self.sent)
                self.api.call('videos.update', {'part': 'snippet' if 'snippet' in body else 'status'}, body)
                self.assertEqual(len(self.sent), before + 1)
                self.assertEqual(self.sent[-1][3]['body'], body)


if __name__ == '__main__':
    unittest.main()
