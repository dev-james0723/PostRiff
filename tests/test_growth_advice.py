import unittest
from postriff_phase2.growth import questions as Q, jev, rewrite
from postriff_phase2.growth.judgments import Judgment, validate_answers
from postriff_phase2.growth.router import AIModelRouter, RouterError
from postriff_alpha.domain import AlphaError

class Advice(unittest.TestCase):
    def test_goal_priorities_are_unique_bounded_and_missing_is_a_request(self):
        from postriff_phase2.growth import advice
        dims=[{'id':d,'label':d.title(),'level':0,'levelName':'Weak','fixes':[f'Fix {d}',f'Another {d}']} for d in ('hook','clarity','conversation','shareability','evidence')]
        for goal,first in [('conversation','conversation'),('shareability','shareability'),('authority','evidence'),('reach','hook')]:
            actions=advice.prioritize(dims,goal=goal,missing_context={},limit=99)
            self.assertEqual(len(actions),3)
            self.assertEqual(actions[0]['dimension'],first)
            self.assertEqual(len({a['dimension'] for a in actions}),3)
        actions=advice.prioritize(dims,goal='reach',missing_context={'audience':['creator.audience']})
        self.assertEqual(actions[0]['kind'],'context')
        self.assertEqual(actions[0]['dimension'],'audience')
        self.assertNotIn('Weak',actions[0]['concern'])

    def judge(self,choice):
        qs=Q.get('postdoctor_compare',1)
        raw={'preferred':{'type':'choice','choice':choice,'probabilities':{k:float(k==choice) for k in ('a','b','equivalent','unsure')}}}
        answers,invalid=validate_answers(qs,raw)
        return Judgment(qs.key,qs.digest,'typesafe-ai/jev','primary',True,answers,invalid,0,'fixture',None,1,'key')

    def test_comparison_never_promotes_unsupported_uncertain_or_order_biased_text(self):
        from postriff_phase2.growth import advice
        candidate=self.judge('b');swapped=self.judge('a')
        self.assertEqual(advice.decide(candidate,grounded=True,voice_preserved=True,swapped=swapped)['recommended'],'candidate')
        for ground,voice,other,want in [(False,True,swapped,'original'),(True,False,swapped,'unsure'),(True,True,candidate,'unsure')]:
            self.assertEqual(advice.decide(candidate,grounded=ground,voice_preserved=voice,swapped=other)['recommended'],want)
        for choice in ('equivalent','unsure'):
            self.assertEqual(advice.decide(self.judge(choice),grounded=True,voice_preserved=True)['recommended'],choice)

    def test_comparison_is_blinded_and_noop_is_equivalent(self):
        from postriff_phase2.growth import advice
        s=advice.comparison_state('Same.','Same.',context={'goal':'general'},facts={},order='original_first')
        self.assertTrue(s['identical'])
        reverse=advice.comparison_state('Old.','New.',context={'goal':'conversation'},facts={'f':'fact'},order='candidate_first')
        self.assertEqual(reverse['versions'],{'a':'New.','b':'Old.'})
        self.assertNotIn('candidate',reverse)
        with self.assertRaises(ValueError):advice.comparison_state('a','b',context={},facts={},order='bad')

    def test_numeric_claim_and_fabricated_source_rejected_before_comparison(self):
        with self.assertRaises(AlphaError):
            rewrite.validate({'changes':[{'index':0,'text':'I gained 900 followers.','dimension':'evidence','usesFacts':[]}],'missingFacts':[],'notes':''},'I wrote a post.',{})
        with self.assertRaises(AlphaError):
            rewrite.validate({'changes':[{'index':0,'text':'A true story.','dimension':'evidence','usesFacts':['invented']}],'missingFacts':[],'notes':''},'I wrote a post.',{})

    def test_unknown_v2_dispatch_does_not_retry_or_fallback(self):
        calls=[]
        class Lost:
            def evaluate(self,*args,**kw):calls.append('jev');raise jev.JevTimeout('response lost')
        def chat(*args,**kw):calls.append('fallback');raise AssertionError('duplicate dispatch')
        router=AIModelRouter(jev=Lost(),chat=chat,sleep=lambda _:None)
        router.reconcile_unknown=True
        with self.assertRaises(RouterError) as error:
            router.evaluate('postdoctor.judge',Q.get('postdoctor',2),{'draft':'x'})
        self.assertEqual(error.exception.code,'dispatch_unknown')
        self.assertEqual(calls,['jev'])

    def test_unknown_fallback_dispatch_requires_reconciliation(self):
        def chat(*args):raise AlphaError('response lost',504)
        router=AIModelRouter(jev=None,chat=chat)
        router.reconcile_unknown=True
        with self.assertRaises(RouterError) as error:
            router.evaluate('postdoctor.judge',Q.get('postdoctor',2),{'draft':'x'})
        self.assertEqual(error.exception.code,'dispatch_unknown')
