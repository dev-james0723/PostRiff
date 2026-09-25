import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2 import ideas

class ContextSelectionTests(unittest.TestCase):
    def choose(self, state, ids):
        self.assertTrue(hasattr(ideas, 'checked_context_ids'))
        return ideas.checked_context_ids(state, ids)

    def setUp(self):
        self.state={'sources':[{'id':'a','active':True,'kind':'text'}, {'id':'b','active':False,'kind':'text'}, {'id':'voice','active':True,'kind':'voice_sample'}]}

    def test_explicit_selection_is_deduplicated(self):
        self.assertEqual(self.choose(self.state,['a','a']),['a'])
        self.assertEqual(self.choose(self.state,[]),[])

    def test_other_workspace_inactive_and_voice_sources_are_rejected(self):
        for ids in [['foreign'],['b'],['voice']]:
            with self.subTest(ids=ids), self.assertRaises(AlphaError): self.choose(self.state,ids)

    def test_malformed_or_oversized_input_is_rejected(self):
        for ids in ['a',[{}],['a']*21]:
            with self.subTest(ids=ids), self.assertRaises(AlphaError): self.choose(self.state,ids)
