import copy
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2 import suggestions
from postriff_phase2.agent_runtime_v2 import creator_pipeline as pipeline


def seed():
    state = {'workspace': {'id': 'w'}, 'phase2': {'jobs': [], 'assets': [], 'channels': []}, 'variants': [], 'raffi': {'campaignPlanning': {'campaigns': [
        {'id': 'campaign-1', 'version': 2, 'status': 'draft', 'items': [], 'goal': 'Recital', 'audience': 'Neighbours', 'facts': {'venue': 'Studio'}}]}}}
    item = suggestions.refresh(state, 100)[0]
    return state, {'suggestionId': item['id'], 'platforms': ['Threads'], 'budgetCeilingUsdMicro': 0}


class CreatorPlan(unittest.TestCase):
    def test_preview_uses_real_facts_and_has_no_side_effects(self):
        state, body = seed(); before = copy.deepcopy(state)
        result = pipeline.plan(state, 'w', body, 100)
        self.assertEqual(state, before)
        self.assertEqual(result['source']['facts'], {'venue': 'Studio'})
        self.assertEqual(result['cost']['state'], 'unknown')
        self.assertIsNone(result['cost']['estimateUsdMicro'])
        self.assertEqual(result['expectedBenefit']['kind'], 'estimate')
        self.assertNotIn('publish', result['inputs'])

    def test_any_fact_change_invalidates_exact_preview_even_without_revision_bump(self):
        state, body = seed(); first = pipeline.plan(state, 'w', body, 100)
        state['raffi']['campaignPlanning']['campaigns'][0]['facts']['venue'] = 'Different venue'
        self.assertNotEqual(first['digest'], pipeline.plan(state, 'w', body, 100)['digest'])

    def test_source_removed_or_revised_is_unavailable(self):
        state, body = seed(); state['raffi']['campaignPlanning']['campaigns'][0]['version'] += 1
        with self.assertRaises(AlphaError): pipeline.plan(state, 'w', body, 100)

    def test_unread_asset_is_not_claimed_as_draft_material(self):
        state, _ = seed(); state['phase2']['assets'].append({'id':'image','processing':'decoded','deleted':False})
        item = next(i for i in suggestions.refresh(state,100) if i['kind']=='unused_asset')
        with self.assertRaises(AlphaError) as e: pipeline.plan(state,'w',{'suggestionId':item['id'],'platforms':['Threads'],'budgetCeilingUsdMicro':0},100)
        self.assertEqual(e.exception.code, 'creator_source_unsupported')

    def test_no_facts_and_incomplete_preview_refused(self):
        state, body = seed(); campaign = state['raffi']['campaignPlanning']['campaigns'][0]
        for facts in ({}, {'tooLarge': 'x'*13000}):
            campaign['facts'] = facts
            with self.assertRaises(AlphaError): pipeline.plan(state,'w',body,100)

    def test_unverified_jobs_never_claim_success_and_entities_resolve_drafts(self):
        state, _ = seed(); state['variants']=[{'id':'v','platform':'Threads','revision':1}]
        steps=[{'entities':[{'type':'draft','id':'v'}]}]
        for status in ('queued','provider_accepted','uncertain','published','verified'):
            state['phase2']['jobs']=[{'id':'j','state':status,'manifest':{'variantId':'v','platform':'Threads'}}]
            out=pipeline.result(state,steps);self.assertEqual(out['publication'],'not_verified');self.assertEqual(len(out['drafts']),1)
        state['phase2']['jobs'][0].update(providerConfirmed=True,providerReference='native-id',verification={'at':123})
        self.assertEqual(pipeline.result(state,steps)['publication'],'verified')
        state['phase2']['jobs'][0]['manifest']['platform']='YouTube'
        self.assertEqual(pipeline.result(state,steps)['publication'],'not_verified')

    def test_invalid_selection_and_ceiling(self):
        state, body = seed()
        for changes in ({'platforms':['Threads','Threads']},{'platforms':['YouTube']},{'budgetCeilingUsdMicro':True},{'budgetCeilingUsdMicro':-1}):
            with self.assertRaises(AlphaError):pipeline.plan(state,'w',{**body,**changes},100)

if __name__ == '__main__': unittest.main()
