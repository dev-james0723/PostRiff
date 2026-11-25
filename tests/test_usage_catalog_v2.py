"""Task6 ModelCatalog producer contract; no image generation or provider calls."""
import unittest
from types import SimpleNamespace
from postriff_phase2.ideas import IdeasService
from postriff_phase2.agent_runtime import FixtureAgentRuntime
from postriff_phase2 import billing
from postriff_phase2.credit_meter import V2_POLICY_VERSION


class CatalogSanitization(unittest.TestCase):
    def test_only_typed_customer_caps_cross_projection(self):
        project = getattr(billing, 'customer_entitlements', None)
        self.assertTrue(callable(project), 'Catalog needs an explicit sanitized customer projection')
        caps = {'monthlyCredits': 3500, 'members': 1, 'brands': True,
                'connectedAccounts': {'providerSecret': 'private'}, 'storageMb': -1,
                'provider_price_id': 'private', 'budgetUsdMicro': 9000, 'cohort': ['private'],
                'creditPolicy': V2_POLICY_VERSION, 'overage': 'stop'}
        self.assertEqual(project(caps), {'monthlyCredits': 3500, 'members': 1,
                                        'creditPolicy': V2_POLICY_VERSION, 'overage': 'stop'})
        self.assertEqual(project({'creditPolicy': {'providerSecret': 'private'}}), {})


class ImageCreditContract(unittest.TestCase):
    def test_legacy_image_available_but_credit_estimate_unqualified(self):
        service = IdeasService(SimpleNamespace(), SimpleNamespace(), runtimes=[FixtureAgentRuntime()],
                               image_runtime=SimpleNamespace(model='synthetic-image', provider='synthetic'), assets=object())
        value = service.model_catalog()['imageGeneration']
        self.assertTrue(value['available'])
        self.assertIs(value.get('creditEstimateAvailable'), False)
        self.assertNotIn('one managed media credit', value['detail'])

    def test_unconfigured_image_has_stable_false_estimate(self):
        service = IdeasService(SimpleNamespace(), SimpleNamespace(), runtimes=[FixtureAgentRuntime()])
        value = service.model_catalog()['imageGeneration']
        self.assertFalse(value['available'])
        self.assertIs(value.get('creditEstimateAvailable'), False)


if __name__ == '__main__':
    unittest.main()
