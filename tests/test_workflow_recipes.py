"""Bounded template validation and content-free notification decisions."""
import copy
import time
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from postriff_alpha.domain import AlphaError
from postriff_phase2.workflow_recipes import catalog
from postriff_phase2.agent_runtime_v2.task_engine.notifications import recipe_baseline


class RecipeRules(unittest.TestCase):
    def settings(self, **extra):
        return dict(templateId='library_review', expiresAt=time.time()+86400, **extra)

    def test_only_server_owned_free_templates(self):
        for extra in ({'templateId':'publish'}, {'steps':['send']}, {'usdMicroPerDay':1}, {'usdMicroPerDay':False}, {'actionsPerDay':True}, {'actionsTotal':51}):
            body = self.settings(); body.update(extra)
            with self.assertRaises(AlphaError): catalog.validate(body,time.time())
        self.assertEqual(catalog.validate(self.settings(),time.time())['usdMicroPerDay'],0)

    def test_time_scope_and_expiry_are_bounded(self):
        for extra in ({'timeZone':'Not/AZone'}, {'expiresAt':0}, {'expiresAt':float('nan')}, {'expiresAt':time.time()+31*86400}, {'collectionId':'foreign-invalid'}, {'planningDay':7}, {'notificationPolicy':'sms'}):
            body=self.settings();body.update(extra)
            with self.assertRaises(AlphaError):catalog.validate(body,time.time())
        with self.assertRaises(AlphaError):catalog.validate(self.settings(connectionId='account'),time.time())
        body=self.settings();body.update(templateId='weekly_performance')
        with self.assertRaises(AlphaError):catalog.validate(body,time.time())

    def test_notification_none_and_failure_modes_record_baseline(self):
        task={'origin':'recipe','workspaceId':'w','createdBy':'u','autopilotPolicyId':'12345678-1234-4234-8234-123456789012','state':'completed'}
        for mode,state,expected in [('none','failed',True),('failures_and_approvals','completed',True),('failures_and_approvals','failed',False),('failures_and_approvals','awaiting_approval',False),('all','completed',False),(None,'failed',True)]:
            cur=Mock();cur.fetchone.side_effect=[('pr_workflow_recipes',), (mode,) if mode else None]
            self.assertEqual(recipe_baseline(cur,{**task,'state':state}),expected)
        cur=Mock()
        self.assertFalse(recipe_baseline(cur,{'origin':'chat'}));cur.execute.assert_not_called()
        self.assertTrue(recipe_baseline(cur,{**task,'autopilotPolicyId':None}));cur.execute.assert_not_called()


class TaskServiceCopy(unittest.TestCase):
    def test_cron_service_copy_preserves_creator_repository(self):
        from postriff_phase2.agent_runtime_v2.task_engine.executor import _ActingService
        base = SimpleNamespace(repository=object(), marker=object())
        creator_repository = object()
        acting = _ActingService(base, creator_repository)
        copied = copy.copy(acting)
        self.assertIs(copied.repository, creator_repository)
        self.assertIs(copied.marker, base.marker)
        copied.repository = object()
        self.assertIs(acting.repository, creator_repository)
        self.assertIs(copied._service, base)

    def test_spend_bound_service_copy_preserves_bound_ledger(self):
        from postriff_phase2.agent_runtime_v2.task_engine.spend import bind_service
        base = SimpleNamespace(repository=object(), ideas=SimpleNamespace(), ledger=object())
        ctx = SimpleNamespace(service=base, step_binding={'effectKey':'test-effect'})
        bind_service(ctx)
        copied = copy.copy(ctx.service)
        self.assertIs(copied.repository, base.repository)
        self.assertIs(copied.ledger, ctx.service.ledger)
        self.assertIs(copied.ideas.ledger, copied.ledger)
        self.assertIsNot(copied.ledger, base.ledger)


if __name__=='__main__':unittest.main()
