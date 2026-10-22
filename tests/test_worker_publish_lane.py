"""Extra publishing lanes run only publishing steps; maintenance stays on the main cron lane."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from postriff_phase2.hosted_worker import PostgresWorker


class PublishLane(unittest.TestCase):
    def worker(self):
        youtube = Mock()
        youtube.maintenance.return_value = {'enabled': True}
        social = SimpleNamespace(providers={'mastodon': object()}, youtube=youtube, oauth=None)
        worker = PostgresWorker(None, social=social)
        worker.step = Mock(side_effect=[True, True, False])
        return worker, youtube

    @patch('postriff_phase2.youtube.fleet.enabled', lambda: False)
    def test_publish_lane_skips_youtube_and_mastodon_maintenance(self):
        worker, youtube = self.worker()
        with patch('postriff_phase2.mastodon_management.maintain', side_effect=AssertionError('maintenance on a publish lane')):
            result = worker.tick(max_jobs=25, max_seconds=45, publish_only=True)
        self.assertEqual(result['processed'], 2)
        self.assertEqual(result['youtubeMaintenance'], {'enabled': False, 'scheduler': 'publish_lane'})
        self.assertNotIn('mastodonMaintenance', result)
        youtube.maintenance.assert_not_called()

    @patch('postriff_phase2.youtube.fleet.enabled', lambda: False)
    def test_a_lane_waits_out_a_busy_claim_lock_instead_of_ending(self):
        worker, _ = self.worker()
        worker.sleep = Mock()
        outcomes = iter([(False, True), (True, False), (False, True), (True, False), (False, False)])
        def step(*_a, **_k):
            claimed, busy = next(outcomes)
            worker.last_claim_busy = busy
            return claimed
        worker.step = step
        result = worker.tick(max_jobs=25, max_seconds=45, publish_only=True)
        self.assertEqual(result['processed'], 2)
        self.assertEqual(worker.sleep.call_count, 2)

    @patch('postriff_phase2.youtube.fleet.enabled', lambda: False)
    def test_busy_waits_are_bounded(self):
        worker, _ = self.worker()
        worker.sleep = Mock()
        def step(*_a, **_k):
            worker.last_claim_busy = True
            return False
        worker.step = step
        self.assertEqual(worker.tick(max_jobs=25, max_seconds=45, publish_only=True)['processed'], 0)
        self.assertEqual(worker.sleep.call_count, 50)

    @patch('postriff_phase2.youtube.fleet.enabled', lambda: False)
    def test_main_lane_still_runs_maintenance(self):
        worker, youtube = self.worker()
        with patch('postriff_phase2.mastodon_management.maintain', return_value={'ok': True}) as maintain:
            result = worker.tick(max_jobs=25, max_seconds=3)
        maintain.assert_called_once()
        youtube.maintenance.assert_called_once()
        self.assertEqual(result['mastodonMaintenance'], {'ok': True})


if __name__ == '__main__':
    unittest.main()
