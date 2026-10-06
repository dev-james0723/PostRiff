import unittest
from agent_team.periods import period, latest_due, next_due, aware
from agent_team.events import Event
from agent_team.reports import EXPECTED_SOURCES, report, svg


class ReportTests(unittest.TestCase):
    def event(self,source,identity,payload,at='2026-10-05T13:00:00+00:00',observed='2026-10-05T13:01:00+00:00'):
        return Event(source,identity,'v1',at,observed,payload,'mission1','project1').cloud()

    def test_boundaries_and_dst(self):
        p=period('2026-10-05','half_day')
        self.assertEqual(p.start.hour,5);self.assertEqual(p.cutoff.hour,21)
        self.assertEqual(latest_due('2026-10-06T05:00:00Z').workday,'2026-10-05')
        self.assertEqual(latest_due('2026-10-06T05:00:00Z').kind,'whole_day')
        self.assertEqual(next_due('2026-10-05T21:00:00Z').kind,'whole_day')
        self.assertEqual(period('2026-03-08','whole_day').as_dict()['actualSeconds'],23*3600)
        self.assertEqual(period('2026-11-01','whole_day').as_dict()['actualSeconds'],25*3600)
        with self.assertRaises(ValueError):aware('2026-10-05T17:00:00')

    def test_agent_stop_is_not_done_and_future_observation_excluded(self):
        events=[self.event('codex','turn1',{'state':'completed'}),self.event('mission','future',{'state':'running'},observed='2026-10-05T22:00:00Z')]
        r=report(period('2026-10-05','half_day'),events,'2026-10-05T21:03:00Z')
        self.assertEqual(r['counts']['completed'],0)
        self.assertIsNone(r['counts']['running']);self.assertEqual(len(r['evidence']),1)

    def test_acceptance_requires_scope_and_existing_refs(self):
        ev=self.event('git','sha1',{'sha':'a'*40})
        acceptance=self.event('acceptance','test1',{'kind':'completed','scopeVersion':'v1','requirements':[{'id':'production','status':'passed','scopeVersion':'v1','evidenceRefs':[ev['key']]}]})
        r=report(period('2026-10-05','half_day'),[ev,acceptance],'2026-10-05T21:03:00Z')
        self.assertEqual(r['counts']['completed'],1)
        acceptance['payload']['requirements'][0]['scopeVersion']='v2'
        self.assertEqual(report(period('2026-10-05','half_day'),[ev,acceptance],'2026-10-05T21:03:00Z')['counts']['completed'],0)

    def test_deterministic_and_escaping(self):
        e=self.event('mission','task1',{'state':'waiting_human'})
        args=(period('2026-10-05','half_day'),[e],'2026-10-05T21:03:00Z')
        a=report(*args);self.assertEqual(a,report(*args));self.assertEqual(svg(a),svg(a))
        a['period']['workday']='<script>'
        self.assertNotIn('<script>',svg(a));self.assertIn('&lt;script&gt;',svg(a))

    def test_healthy_source_metadata_never_erases_full_day_capture_gaps(self):
        sources={source:{'status':'ok','freshAt':'2026-10-05T20:59:00Z','gaps':[],'complete':True}
                 for source in EXPECTED_SOURCES}
        events=[self.event('luci','metadata1',{'kind':'metadata'}),self.event('mission','task1',{'state':'running'})]
        for kind,generated in (('half_day','2026-10-05T21:03:00Z'),('whole_day','2026-10-06T05:03:00Z')):
            with self.subTest(kind=kind):
                data=report(period('2026-10-05',kind),events,generated,sources)
                self.assertTrue(all(c['complete'] and not c['gaps'] for c in data['coverage']))
                self.assertEqual(data['gaps'],['bounded_metadata_only','full_day_screen_audio_unverified'])
                self.assertIn('未取得全日連續電腦畫面與系統音訊的擷取、儲存及回放證據',data['summary'])
                self.assertEqual(data['screenshots'],[])
                self.assertTrue(all(e['captureMode']=='metadata' for e in data['evidence']))
                self.assertEqual(data['counts']['completed'],0)
                self.assertEqual(data['counts']['running'],1)
