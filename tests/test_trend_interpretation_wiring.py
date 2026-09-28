"""Pure integration presentation remains bounded and preserves uncertainty."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from postriff_phase2.growth.trends import advanced_pipeline as A

class InterpretationWiring(unittest.TestCase):
    def setUp(self):
        for n in ('socket.socket.connect','socket.create_connection','urllib.request.urlopen'):
            p=patch(n,side_effect=AssertionError('no egress'));p.start();self.addCleanup(p.stop)
        self.value={'projection_fields':{'spread':{'hypotheses':[]},'platform_dna':{'shared_priors':[],'private_adjustments':[],'conflict':False}},
            'evidence':[],'bindings':{'schema_version':'test'},'refs':[],'limitations':['unqualified'],'expires_at':'2027-01-01T00:00:00Z'}
    def test_unknown_never_becomes_supported_or_zero(self):
        rows=A._interpretation_dimensions(self.value)
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['finding'] is None and r['evidence_refs']==[] for r in rows))
        self.assertIn('unknown',rows[0]['uncertainty'])
    def test_spread_retains_multiple_labels_alternatives_and_contradictions(self):
        self.value['projection_fields']['spread']['hypotheses']=[{'mechanism':'practical_utility','evidence_refs':['native-a'],
            'alternatives':['Identity rather than usefulness'],'contradictions':['One disagreement'],'uncertainty':'Not causal'},
            {'mechanism':'humor','evidence_refs':['native-b'],'alternatives':['Surprise'],'contradictions':[],'uncertainty':'Sample only'}]
        before=deepcopy(self.value);row=A._interpretation_dimensions(self.value)[0]
        self.assertIn('Hypothesis: practical utility',row['finding']);self.assertIn('Hypothesis: humor',row['finding'])
        self.assertIn('Identity rather than usefulness',row['finding']);self.assertIn('One disagreement',row['uncertainty'])
        self.assertEqual(row['evidence_refs'],['native-a','native-b']);self.assertEqual(before,self.value)
    def test_versioned_private_and_shared_priors_remain_separate_and_conditional(self):
        p={'platform':'bluesky','format':'short text','language':'yue','niche':'piano','period':'frozen-period',
            'prior_version':'review-v1','finding':'Native wording matters','uncertainty':'Small cohort','evidence_refs':['id-a']}
        self.value['projection_fields']['platform_dna'].update(shared_priors=[p],private_adjustments=[{**p,'finding':'Different outcome','evidence_refs':['id-b']}],conflict=True)
        row=A._interpretation_dimensions(self.value)[1]
        for term in ('Shared hypothesis','Your observed outcomes','bluesky','yue','frozen-period','version review-v1'):
            self.assertIn(term,row['finding'])
        self.assertIn('disagree',row['uncertainty']);self.assertIn('not a causal claim',row['uncertainty'])
        self.assertEqual(row['evidence_refs'],['id-a','id-b'])
    def test_fingerprint_freezes_interpretation_independently(self):
        args=('a','genome','b',None,None,[])
        self.assertNotEqual(A._fingerprint(*args,{'review':'a'}),A._fingerprint(*args,{'review':'b'}))
        args=('a','graph','b',None,None,[])
        self.assertEqual(A._fingerprint(*args,{'review':'a'}),A._fingerprint(*args,{'review':'b'}))

if __name__=='__main__':unittest.main()
