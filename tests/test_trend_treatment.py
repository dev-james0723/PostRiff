import copy
import unittest
from unittest.mock import patch
from postriff_phase2.growth.trends import treatment, opportunities
from postriff_phase2.coworker import performance
from test_trend_service import make_service, WID, OID, ACTOR, NOW
from test_trend_opportunities import PAYLOAD


class TreatmentTests(unittest.TestCase):
    def setUp(self):
        self.svc,self.repo,_=make_service()
        sid=self.svc.accept(WID,'session',OID,PAYLOAD)['data']['source_id']
        self.variant={'id':'saved-draft','revision':3,'text':'My original draft','trendLineage':opportunities.lineage(self.repo.state,[sid])}
        self.repo.state['variants']=[self.variant]
        self.payload={'variant_id':'saved-draft','variant_revision':3,
            'selection_digest':self.variant['trendLineage'][0]['selection_digest'],'treatment_changed':False}

    def test_no_assessment_stays_unknown_and_current_creator_review_freezes(self):
        self.assertEqual(treatment.frozen(self.variant,NOW),{})
        treatment.record(self.repo.state,ACTOR,self.payload,NOW)
        manifest={'platform':'Bluesky','channelId':'channel-1'}
        opportunities.freeze_manifest(self.repo.state,self.variant,manifest,NOW)
        self.assertIs(manifest['trendPublication']['treatmentChanged'],False)
        self.assertEqual(manifest['trendPublication']['treatmentAssessmentBasis'],'creator_confirmed')
        treatment.record(self.repo.state,ACTOR,{**self.payload,'treatment_changed':True},NOW)
        self.assertTrue(treatment.frozen(self.variant,NOW)['treatmentChanged'])
        self.assertIs(manifest['trendPublication']['treatmentChanged'],False)

    def test_edits_revisions_lineage_and_future_review_never_reuse_assessment(self):
        treatment.record(self.repo.state,ACTOR,self.payload,NOW)
        for change in ({'text':'edited'}, {'revision':4}, {'trendLineage':[]}):
            self.assertEqual(treatment.frozen({**self.variant,**change},NOW),{})
        future=copy.deepcopy(self.variant)
        future['trendTreatmentAssessments'][0]['reviewed_at']=opportunities.iso(NOW+1)
        self.assertEqual(treatment.frozen(future,NOW),{})

    def test_requires_exact_saved_selection_bool_and_current_lineage(self):
        for change in ({'variant_revision':True},{'variant_revision':4},{'selection_digest':'other'}, {'treatment_changed':'false'}, {'extra':1}):
            with self.assertRaises(ValueError): treatment.record(self.repo.state,ACTOR,{**self.payload,**change},NOW)
        self.assertNotIn('trendTreatmentAssessments',self.variant)

    def test_performance_uses_existing_persistence_and_never_adopts_trend_hypotheses(self):
        from postriff_phase2.growth.trends import learning
        from unittest.mock import Mock
        cur=Mock();cur.rowcount=0
        with patch.object(performance,'observations',return_value=[]),patch.object(performance,'hypotheses_from',return_value=[]),\
             patch.object(learning,'hypotheses',return_value=[]) as adapt,patch('postriff_phase2.coworker.flags.enabled',return_value=False):
            result=performance.refresh(cur,WID,{},NOW,trend_report={'exposures':[]})
        adapt.assert_called_once_with({'exposures':[]},NOW)
        self.assertEqual(result['hypotheses'],0)
        self.assertFalse(any('supported' in str(call) and 'UPDATE' not in str(call) for call in cur.execute.call_args_list))
