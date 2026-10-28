"""What one cron invocation can do for Discord, from the loop itself (synthetic; no database, no network).

The launch plan sizes Discord posting from these facts: one invocation runs at most `max_jobs` steps, stops at its time
budget, and gives Discord every step only when no other provider has work.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_phase2 import hosted_worker
from postriff_phase2.hosted_worker import PostgresWorker


def worker(step, *, discord=False):
    instance = object.__new__(PostgresWorker)
    instance._stopping = False
    instance._ensure_lifecycle = lambda: None
    instance.social = SimpleNamespace()
    instance.discord_workers = discord
    instance.discord_report = lambda: {}
    instance.step = step
    return instance


class Clock:
    def __init__(self, seconds_per_reading):
        self.now, self.seconds = 0.0, seconds_per_reading

    def __call__(self):
        self.now += self.seconds
        return self.now


class OneInvocation(unittest.TestCase):
    def test_the_default_budget_is_ten_steps(self):
        calls = []
        result = worker(lambda **kw: calls.append(kw) or True).tick()
        self.assertEqual((result['processed'], len(calls)), (10, 10))
        self.assertEqual(result['budget'], {'maxJobs': 10, 'maxSeconds': 20})

    def test_the_largest_budget_is_twenty_five_steps(self):
        calls = []
        result = worker(lambda **kw: calls.append(kw) or True).tick(25, 45)
        self.assertEqual((result['processed'], len(calls)), (25, 25))

    def test_a_larger_budget_is_refused_before_any_step_runs(self):
        calls = []
        for jobs, seconds in ((26, 20), (10, 46), (0, 20), (10, 0)):
            with self.assertRaises(Exception, msg=(jobs, seconds)):
                worker(lambda **kw: calls.append(kw) or True).tick(jobs, seconds)
        self.assertEqual(calls, [])

    def test_the_time_budget_stops_the_loop_before_the_job_budget(self):
        calls = []
        with patch.object(hosted_worker.time, 'monotonic', Clock(5)):
            result = worker(lambda **kw: calls.append(kw) or True).tick(25, 20)
        self.assertLess(result['processed'], 25)
        self.assertEqual(result['processed'], len(calls))

    def test_an_empty_queue_ends_the_invocation_at_once(self):
        result = worker(lambda **kw: False).tick()
        self.assertEqual(result['processed'], 0)

    def test_a_post_that_needs_two_steps_makes_five_posts_per_default_invocation(self):
        steps_per_post = 2  # create, then read-back (reconciliation); each is its own claim
        self.assertEqual(10 // steps_per_post, 5)
        self.assertEqual(25 // steps_per_post, 12)


class LanesWhenDiscordWorkersAreOn(unittest.TestCase):
    def test_busy_lanes_split_the_steps_evenly(self):
        seen = []

        def step(**kw):
            seen.append('discord' if kw.get('discord_only') else 'other')
            return True
        worker(step, discord=True).tick()
        self.assertEqual((seen.count('discord'), seen.count('other')), (5, 5))

    def test_an_idle_other_lane_gives_discord_every_step(self):
        seen = []

        def step(**kw):
            lane = 'discord' if kw.get('discord_only') else 'other'
            seen.append(lane)
            return lane == 'discord'
        result = worker(step, discord=True).tick()
        self.assertEqual(result['processed'], 10)
        self.assertEqual(seen.count('discord'), 10)

    def test_an_idle_discord_lane_does_not_hold_back_the_rest(self):
        def step(**kw):
            return not kw.get('discord_only')
        self.assertEqual(worker(step, discord=True).tick()['processed'], 10)

    def test_the_dedicated_discord_lane_never_runs_another_provider(self):
        seen = []
        worker(lambda **kw: seen.append(kw) or True).tick_discord(4, 20)
        self.assertEqual(len(seen), 4)
        self.assertTrue(all(kw == {'discord_only': True} for kw in seen))


if __name__ == '__main__':
    unittest.main()
