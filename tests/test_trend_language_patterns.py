import copy
import unittest
from postriff_phase2.growth.trends import contracts, language_patterns as L, advanced_pipeline as A
import test_trend_text_context as F


class LanguagePatterns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        F.TextContextTests.setUpClass(); cls.f=F.TextContextTests()

    def inputs(self):
        x=self.f.inputs(); x['history_windows']=[]; start=contracts.instant(x['frame']['window_start'])
        from datetime import timedelta
        for i,s in enumerate(x['common']['sources']):
            s['language']='yue'; s['event_at']=contracts.iso(start+timedelta(seconds=i+1))
            x['facts'][s['source_id']]['text']='慢啲 Practiceee？🎹 #練琴\n唔好急！'
        return x

    def test_actual_builder_native_types_and_no_missing_baseline_zero(self):
        x=self.inputs(); result=A.build_projection('language_pattern',x,now=F.NOW)
        raw=result['details']; self.assertTrue(raw['phrase_recurrence'])
        self.assertTrue({'phrase','collocation','emoji','punctuation','hashtag','opening_template'} <= {p['kind'] for p in raw['patterns']})
        self.assertTrue(all(p['baseline_count'] is None and p['change'] is None for p in raw['patterns']))
        self.assertTrue(any(p['expression']=='Practiceee' for p in raw['patterns']))
        self.assertTrue(any(p['expression']=='🎹' for p in raw['patterns']))
        self.assertTrue(all(p['meaning'] is None and p['origin'] is None for p in raw['patterns']))
        self.assertTrue(all(p['meaning']=='Not interpreted; original wording only.' for p in result['payload']['patterns']))

    def test_current_display_and_creative_denials(self):
        x=self.inputs()
        for s in x['common']['sources']: s['rights']['display']=False
        self.assertEqual(L.wire(L.project(x)),[])
        for s in x['common']['sources']: s['rights']['creative']=False
        self.assertEqual(L.project(x)['patterns'],[])

    def test_late_outside_current_and_reordered_input_do_not_inflate_patterns(self):
        x=self.inputs(); expected=L.project(x)
        x['common']['sources'].reverse()
        self.assertEqual(L.project(x),expected)
        for s in x['common']['sources']: s['event_at']=x['frame']['window_end']
        self.assertEqual(L.project(x)['patterns'],[])

    def test_equal_complete_windows_allow_measured_zero_baseline(self):
        x=self.inputs(); start=contracts.instant(x['frame']['window_start']); end=contracts.instant(x['frame']['window_end'])
        x['history_windows']=[{'comparison_digest':x['frame']['frame_id'],'window_start':contracts.iso(a),
            'window_end':contracts.iso(b),'data_state':'qualified','coverage':{'completeness':'complete_within_scope'}}
            for a,b in ((start-(end-start),start),(start,end))]
        raw=L.project(x); phrases=[p for p in raw['patterns'] if p['kind']=='phrase']
        self.assertTrue(phrases)
        self.assertTrue(all(p['baseline_count']==0 and p['change']==p['observation_count'] for p in phrases))
        x['history_windows'][0]['coverage']['completeness']='partial'
        self.assertTrue(all(p['baseline_count'] is None for p in L.project(x)['patterns']))


if __name__=='__main__': unittest.main()
