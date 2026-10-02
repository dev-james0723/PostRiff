"""Task5 pure boundary tests; no transport or database."""
import json
import os
import unittest
from unittest.mock import patch
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import Ledger
from postriff_phase2.growth.service import GrowthService
from postriff_phase2.growth.preview import PreviewPolicy, recent_samples

class FreeLedger(Ledger):
    def ensure_entitlement(self, *args):
        return {'planTermsId': 'free-v1', 'writingBatchesRemaining': 0, 'mediaCreditsRemaining': 0}
    def _budget(self, *args):
        return {'status': 'approved', 'spent': 0, 'reserved': 0, 'stop': 1000000, 'warn': 1000000}

class Cursor:
    def execute(self, query, values=()): self.query = query
    def fetchone(self):
        if 'count(*)' in self.query: return (0,)
        if 'RETURNING id' in self.query: return ('synthetic-reservation',)
        return None

class Boundaries(unittest.TestCase):
    def test_positive_free_cost_cannot_use_the_developer_quota_exemption(self):
        actor='b167161d-37f4-4bc3-ae22-2482c982e5a0'
        with patch.dict(os.environ, {'RAFII_AI_UNLIMITED_USER_IDS': actor, 'POSTRIFF_BUDGET_POLICY': 'paid-2026-09-24', 'POSTRIFF_AI_PAUSED': '0'}):
            with self.assertRaises(AlphaError) as caught:
                FreeLedger().reserve(Cursor(), 'workspace', actor, 'tool', 1, 'key', charge_batch=False, meta={'platformPreview': True})
            self.assertEqual(caught.exception.code, 'free_managed_writing_unavailable')

    def test_approval_and_finite_server_caps_are_required(self):
        value={'approved':True,'id':'synthetic','attemptMaxUsdMicro':20000,'dailyUsdMicro':1000000,
               'monthlyUsdMicro':2000000,'dailyRuns':20,'workspaceDailyRuns':2,'maxInputBytes':64000,'maxOutputTokens':1500}
        self.assertIsNone(PreviewPolicy.from_env({}))
        for change in ({'approved':False},{'dailyRuns':0},{'attemptMaxUsdMicro':True},{'maxInputBytes':0},
                       {'model':'forged'},{'executionProvider':'other'},{'monthlyUsdMicro':999},{'maxOutputTokens':99999}):
            with self.subTest(change=change), self.assertRaises(AlphaError):
                PreviewPolicy.from_env({'POSTRIFF_GROWTH_PLATFORM_PREVIEW':json.dumps({**value,**change})})
        self.assertEqual(PreviewPolicy.from_env({'POSTRIFF_GROWTH_PLATFORM_PREVIEW':json.dumps(value)}).maxOutputTokens,1500)

    def test_recent_selection_filters_actual_active_and_granted_sources(self):
        sources=[{'id':str(i),'kind':'voice_sample','active':True,'selected':True,'createdAt':i} for i in range(25)]
        sources.append({'id':'newer-ungranted','kind':'voice_sample','active':True,'selected':True,'createdAt':999})
        sources.append({'id':'inactive','kind':'voice_sample','active':False,'selected':True,'createdAt':1000})
        self.assertEqual(recent_samples({'sources':sources}, {str(i) for i in range(25)}|{'inactive'}), [str(i) for i in range(24,4,-1)])

    def test_a_finite_cap_must_not_round_to_zero_microdollars(self):
        service=object.__new__(GrowthService)
        service.env={'CAP': '0.00000001'}
        with self.assertRaises(AlphaError): service.cap('CAP')

if __name__=='__main__': unittest.main(verbosity=2)
