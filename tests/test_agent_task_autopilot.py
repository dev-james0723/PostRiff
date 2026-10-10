"""Bound recipe policies narrow authority; registration and metadata cannot widen it."""
import unittest
from dataclasses import replace
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import agent_permissions as ap, authz
from postriff_phase2.agent_runtime_v2.task_engine import autopilot

PID='00000000-0000-0000-0000-000000001111'


class ExactPolicyTest(unittest.TestCase):
    def setUp(self):
        self.task={'workspaceId':'w','createdBy':'u','origin':'recipe','autonomyMode':'autopilot','autopilotPolicyId':PID}
        self.policy=ap.AutopilotPolicy(PID,frozenset({'tool.help_search'}),{'recipeVersion':1},{'actionsTotal':2},{'actionsTotal':1},100)
        self.grants=ap.from_scopes('w','u',{'category:read_analyze':'assist'},preset='custom',autopilot=(self.policy,))
        self.cur=Mock();self.cur.fetchone.return_value=(1,)
        self.addCleanup(autopilot.register_policy_validator,None)

    def test_missing_named_policy_or_validator_refuses(self):
        for grants in (self.grants,replace(self.grants,autopilot=())):
            with self.assertRaises(AlphaError):autopilot.for_step(self.cur,self.task,{},grants,10)

    def test_reservation_discount_keeps_exact_policy(self):
        autopilot.register_policy_validator(lambda c,t,s,p,n:replace(p,usage={'actionsTotal':0}))
        bound=autopilot.for_step(self.cur,self.task,{},self.grants,10)
        self.assertEqual([p.id for p in bound.autopilot],[PID])
        self.assertEqual(bound.autopilot[0].usage,{'actionsTotal':0})
        self.assertEqual(self.grants.autopilot[0].usage,{'actionsTotal':1})

    def test_callback_cannot_change_scope_or_mutate_original(self):
        def altered(c,t,s,p,n):
            p.constraints['recipeVersion']=2
            return p
        autopilot.register_policy_validator(altered)
        with self.assertRaises(AlphaError):autopilot.for_step(self.cur,self.task,{},self.grants,10)
        self.assertEqual(self.policy.constraints,{'recipeVersion':1})

    def test_policy_epoch_lookup_and_expiry_refuse(self):
        autopilot.register_policy_validator(lambda c,t,s,p,n:p)
        self.cur.fetchone.return_value=None
        with self.assertRaises(AlphaError):autopilot.for_step(self.cur,self.task,{},self.grants,10)
        self.cur.fetchone.return_value=(1,)
        with self.assertRaises(AlphaError):autopilot.for_step(self.cur,self.task,{},self.grants,100)

    def test_provenance_adds_only_typed_source_domains(self):
        cap=authz.Capability('tool.draft_create',1,'tool','draft_create','create_edit','R1','none','edit',data_grants=('content','memory_brand'))
        enriched=authz.capability_for_refs(cap,[{'type':'campaign','id':'c'}])
        self.assertEqual(enriched.required_domains(),('campaigns','content','memory_brand'))
        self.assertEqual(authz.capability_for_refs(cap,[{'id':'legacy'}]),cap)
        with self.assertRaises(ValueError):authz.capability_for_refs(cap,[{'type':'unknown','id':'x'}])
