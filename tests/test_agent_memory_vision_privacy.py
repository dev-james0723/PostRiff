"""Optional brand rules may never widen an otherwise authorized image read."""
import unittest
from unittest import mock

import test_agent_permissions as permissions
from postriff_phase2.agent_runtime_v2 import authz, creative, memory_layers


class VisionMemoryPrivacyTests(unittest.TestCase):
    def context(self, allowed=True, mode='enforce'):
        ctx = permissions.ctx_for(mode)
        grants = permissions.grants(scopes={'domain:memory_brand': allowed})
        with mock.patch.object(authz, 'load_grants', return_value=grants), mock.patch.object(authz, 'load_provider_view', return_value={}):
            authz.bind_context(ctx)
        ctx.authz_state['memoryEgress'] = {'cloud': True}
        return ctx

    def test_narrowed_grants_withhold_brand_before_projection(self):
        ctx = self.context(False)
        with mock.patch.object(memory_layers, 'read') as project:
            self.assertIsNone(creative._vision_brand_rules(ctx, ctx.authz_state))
        project.assert_not_called()

    def test_allowed_brand_records_current_memory_provenance_and_revoke_blocks_history(self):
        ctx = self.context()
        with mock.patch.object(memory_layers, 'read', return_value={'layers': {'brand': {'files': {'brand.md': 'Quiet typography'}}}}):
            self.assertEqual(creative._vision_brand_rules(ctx, ctx.authz_state), 'Quiet typography')
        trace = authz.trace_for(ctx)
        self.assertIn('context.memory_layers', trace['capabilities'])
        self.assertEqual(trace['memoryContextRevision'], memory_layers.context_revision(ctx.authz_state))
        cur = mock.Mock(); cur.fetchone.return_value = (trace,)
        ctx.grants = permissions.grants(scopes={'domain:memory_brand': False})
        self.assertFalse(authz.history_eligible(cur, ctx, 'assistant', {'runId': 'vision-result'}))

    def test_cloud_revoke_withholds_brand_even_with_domain_grant(self):
        ctx = self.context()
        ctx.authz_state['memoryEgress']['cloud'] = False
        with mock.patch.object(memory_layers, 'read') as project:
            self.assertIsNone(creative._vision_brand_rules(ctx, ctx.authz_state))
        project.assert_not_called()

    def test_shadow_keeps_existing_projection(self):
        ctx = self.context(False, 'shadow')
        with mock.patch.object(memory_layers, 'read', return_value={'layers': {'brand': {'files': {'brand.md': 'Quiet typography'}}}}):
            self.assertEqual(creative._vision_brand_rules(ctx, ctx.authz_state), 'Quiet typography')

    def test_later_workspace_rebind_cannot_relabel_an_earlier_memory_read(self):
        ctx = self.context()
        with mock.patch.object(memory_layers, 'read', return_value={'layers': {'brand': {'files': {'brand.md': 'Original rule'}}}}):
            creative._vision_brand_rules(ctx, ctx.authz_state)
        original = authz.trace_for(ctx)['memoryContextRevision']
        ctx.authz_state['learning'] = {'revision':99, 'active':[], 'retired':[]}
        authz.record_memory_context(ctx, ctx.authz_state)
        trace = authz.trace_for(ctx)
        self.assertEqual(trace['memoryContextRevision'], original)
        self.assertNotEqual(trace['memoryContextRevision'], memory_layers.context_revision(ctx.authz_state))
        cur = mock.Mock(); cur.fetchone.return_value = (trace,)
        self.assertFalse(authz.history_eligible(cur, ctx, 'assistant', {'runId':'mixed-revision'}))
