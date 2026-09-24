"""Real configured-runtime path with synthetic gateway transport; no live provider calls."""
import json
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted_app import ideas_runtime_from_environment

class ProviderRouteTests(unittest.TestCase):
    def test_multiple_model_vendors_keep_the_exact_selected_route(self):
        models = ['anthropic/fixture', 'openai/fixture', 'google/fixture', 'qwen/fixture']
        runtime = ideas_runtime_from_environment({'AI_GATEWAY_API_KEY':'synthetic-not-a-secret',
            'POSTRIFF_MODEL_ID':models[0], 'POSTRIFF_MODEL_IDS':','.join(models),
            'POSTRIFF_MODEL_PRICES':json.dumps({model:[2,8] for model in models})})
        calls=[]
        def transport(method, url, headers=None, body=None):
            calls.append(body['model'])
            return {'status':200,'body':{'choices':[{'message':{'content':json.dumps({'variants':[{'platform':'LinkedIn','language':'en-US','text':'Launch update.','sourceIds':[]}]})}}], 'usage':{'prompt_tokens':10,'completion_tokens':20,'cost':0.01}}}
        runtime.transport=transport
        for model in models:
            with self.subTest(model=model):
                events=[]
                result=runtime.start_turn({'model':model,'reasoning':'quick','idea':'Launch update.',
                    'destinations':[{'platform':'LinkedIn','language':'en-US'}],
                    'context':{'providerClass':'cloud','sources':[],'excluded':[],'candidateOnly':False}},events.append)
                self.assertEqual(calls[-1],model)
                self.assertEqual(result['usage']['model'],model)
                self.assertNotIn('synthetic-not-a-secret',json.dumps(events))
        self.assertEqual(calls,models)

    def test_missing_key_does_not_create_a_paid_route(self):
        self.assertIsNone(ideas_runtime_from_environment({}))

    def test_unpriced_model_never_reaches_transport(self):
        runtime=ideas_runtime_from_environment({'AI_GATEWAY_API_KEY':'synthetic-not-a-secret','POSTRIFF_MODEL_ID':'vendor/unpriced-fixture'})
        calls=[]
        runtime.transport=lambda *args,**kwargs:calls.append(args)
        with self.assertRaises(AlphaError):
            runtime.start_turn({'model':'vendor/unpriced-fixture','reasoning':'quick','idea':'Test.',
                'destinations':[{'platform':'LinkedIn','language':'en-US'}],
                'context':{'providerClass':'cloud','sources':[],'excluded':[],'candidateOnly':False}},lambda event:None)
        self.assertEqual(calls,[])
