"""Behavior fences for v2 context; deterministic provider, no paid calls."""
import unittest
from dataclasses import replace
from postriff_phase2.growth import questions as Q, post_doctor as P
from postriff_phase2.growth.judgments import JudgmentService
from postriff_phase2.growth.router import RouterEvaluation
from postriff_phase2.growth.service import serialize
from test_growth_post_doctor import profile

class ContextContract(unittest.TestCase):
    def setUp(self):
        self.states = []
        def evaluate(qs, state, **kwargs):
            self.states.append(state)
            return RouterEvaluation({n:{'type':'boolean','probability':.95} for n in qs.names},
                                    'primary','typesafe-ai/jev',True,0,'fixture',None,1)
        self.judgments = JudgmentService(evaluate)

    def doctor(self, v2=True):
        return P.PostDoctorService(self.judgments, env={P.FLAG:'1','POSTRIFF_POST_DOCTOR_V2':'1' if v2 else '0'})

    def check(self, service, **kw):
        return service.check(workspace_id='ws',draft_text='I practise slowly.',platform='Threads',lang='en',**kw)

    def test_missing_or_blank_audience_cannot_be_overridden_by_confident_model(self):
        for creator in ({},{'audience':'   '},{'audience':[]},{'audience':{'guess':'everyone'}}):
            with self.subTest(creator=creator):
                result=self.check(self.doctor(),creator=creator)
                audience=next(d for d in result.dimensions if d.id=='audience')
                self.assertIsNone(audience.level)
                self.assertIsNone(audience.score)
                self.assertEqual(audience.missing_context,('creator.audience',))
                self.assertIn('missing_context',result.confidence_reasons)
                self.assertNotIn('audience',serialize(result,'en')['_scores'])

    def test_explicit_v2_and_context_cache_identity(self):
        svc=self.doctor()
        a=self.check(svc,creator={'audience':'piano beginners'},goal='conversation')
        same=self.check(svc,creator={'audience':'piano beginners'},goal='conversation')
        b=self.check(svc,creator={'audience':'piano beginners'},goal='authority')
        c=self.check(svc,creator={'audience':'teachers'},goal='authority')
        self.assertEqual(a.question_set,'postdoctor.v2')
        self.assertTrue(same.judgment.cached)
        self.assertEqual(len(self.states),3)
        self.assertEqual(len({a.context['digest'],b.context['digest'],c.context['digest']}),3)
        self.assertEqual(serialize(a,'en')['goal'],'conversation')
        self.assertIsNotNone(next(d.level for d in a.dimensions if d.id=='audience'))

    def test_v1_behavior_and_serialization_remain_pinned(self):
        result=self.check(self.doctor(False))
        self.assertEqual(result.question_set,'postdoctor.v1')
        self.assertIsNotNone(next(d.level for d in result.dimensions if d.id=='audience'))
        self.assertEqual(serialize(result,'en')['questionSet'],'postdoctor.v1')
        # A foreign result must fail closed rather than borrow the latest rubric.
        with self.assertRaises(KeyError):serialize(replace(result,question_set='postdoctor.v999'),'en')

    def test_v1_profile_never_applies_to_v2(self):
        with self.assertRaisesRegex(ValueError,'different question set'):
            P.PostDoctorService(self.judgments,env={P.FLAG:'1','POSTRIFF_POST_DOCTOR_V2':'1'},profile=profile(['en']))

    def test_bad_goal_rejected_before_provider(self):
        with self.assertRaises(ValueError):self.check(self.doctor(),goal='go viral guaranteed')
        self.assertEqual(self.states,[])

    def test_publication_fences_current_rubric_goal_and_context(self):
        from postriff_phase2.growth import advice_context
        from postriff_phase2.growth.service import context_fingerprint
        from postriff_phase2.contracts import digest
        state={'brandHub':{'audience':'beginners'}}
        variant={'revision':2,'text':'A post.','postDoctorGoal':'conversation'}
        saved={'revision':2,'textDigest':digest('A post.'),'questionSet':'postdoctor.v2','goal':'conversation',
               'inputContextFingerprint':context_fingerprint(state),'evaluation':{'rubricDigest':Q.get('postdoctor',2).digest}}
        self.assertTrue(advice_context.prediction_current(saved,state,variant))
        self.assertFalse(advice_context.prediction_current({**saved,'goal':'authority'},state,variant))
        self.assertFalse(advice_context.prediction_current({**saved,'evaluation':{'rubricDigest':'old'}},state,variant))
        state['brandHub']['audience']='experts'
        self.assertFalse(advice_context.prediction_current(saved,state,variant))

    def test_context_identity_includes_language_and_platform(self):
        svc=self.doctor()
        a=self.check(svc)
        b=svc.check(workspace_id='ws',draft_text='I practise slowly.',platform='Bluesky',lang='zh-Hant')
        self.assertNotEqual(a.context['digest'],b.context['digest'])
