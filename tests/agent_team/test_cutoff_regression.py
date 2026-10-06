import unittest
from agent_team.events import Event
from agent_team.periods import period
from agent_team.reports import report


class CutoffTests(unittest.TestCase):
    def test_late_observation_can_add_pre_cutoff_version(self):
        e=Event('typeless','a','1','2026-10-05T20:30:00Z','2026-10-05T22:00:00Z',{'sourceFreshAt':'2026-10-05T20:40:00Z'})
        d=report(period('2026-10-05','half_day'),[e.cloud()],'2026-10-05T22:01:00Z')
        self.assertEqual(len(d['evidence']),1);self.assertEqual(d['lateObservationCount'],1)

    def test_edit_effective_after_cutoff_does_not_rewrite_report(self):
        old=Event('typeless','a','1','2026-10-05T20:30:00Z','2026-10-05T20:40:00Z',{'sourceFreshAt':'2026-10-05T20:40:00Z'})
        new=Event('typeless','a','2','2026-10-05T20:30:00Z','2026-10-05T22:00:00Z',{'sourceFreshAt':'2026-10-05T21:30:00Z'})
        d=report(period('2026-10-05','half_day'),[old.cloud(),new.cloud()],'2026-10-05T22:01:00Z')
        self.assertEqual(d['evidence'][0]['revision'],'1')

    def test_nonfinite_input_and_future_update_rejected(self):
        for payload in ({'count':float('nan')},{'sourceFreshAt':'2026-10-05T22:00:00Z'}):
            with self.assertRaises(ValueError):Event('luci','a','1','2026-10-05T20:00:00Z','2026-10-05T21:00:00Z',payload).cloud()
