"""Cross-surface CF2 permission boundaries: no provider calls or paid fixtures."""
import copy
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

import test_agent_permissions as f
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import authz, capability_registry, ui_capabilities, ui_domain
from postriff_phase2.agent_runtime_v2.ui_http import UiAuth
from postriff_phase2.site_agent import tools as site_tools


class PermissionSurfaces(unittest.TestCase):
    def ctx(self, mode='enforce', scopes=None):
        ctx = f.ctx_for(mode)
        ctx.authz_mode = mode
        ctx.authz_state = f.workspace_state()
        ctx.grants = f.grants('custom', scopes or {})
        return ctx

    def ui(self, mode, scopes=None):
        c = self.ctx(mode, scopes)
        return UiAuth(f.WS, f.ME, f.OWNER, 'owner', grants=c.grants, config=c.config,
                      authz_mode=mode, authz_state=c.authz_state, now=f.NOW)

    def test_manifest_shadow_is_identical_including_private_fields_and_revision(self):
        projection = {'journeyIds': ['J01','J02','J03','J04','J05','J06','J07','J09']}
        narrowed = {'category:create_edit':'ask','domain:analytics':False,'domain:content':False}
        with mock.patch.object(ui_capabilities, '_now', return_value=f.NOW):
            # The generated ID is incidental; all authority-bearing fields must match.
            off = ui_capabilities.build_manifest(None, self.ui('off', narrowed), projection, flags={'actions':True})
            with self.assertLogs('postriff.agent_runtime', 'INFO'):
                shadow = ui_capabilities.build_manifest(None, self.ui('shadow', narrowed), projection, flags={'actions':True})
            off.pop('manifestId'); shadow.pop('manifestId')
            self.assertEqual(off, shadow)
            enforced = ui_capabilities.build_manifest(None, self.ui('enforce', narrowed), projection, flags={'actions':True})
            self.assertNotEqual(enforced['permissionRevision'], off['permissionRevision'])
            self.assertLess(len(enforced['queries']), len(off['queries']))

    def test_every_ui_binding_resolves_shadow_and_enforced_decisions(self):
        for kind, bindings in [('query', ui_domain.QUERIES.values()), ('action', ui_domain.ACTIONS.values())]:
            for binding in bindings:
                if binding.scope != 'workspace':
                    continue
                with self.subTest(kind=kind, binding=binding):
                    self.assertIsNone(ui_capabilities.permission_decision(self.ui('off'), binding, kind=kind))
                    decision = ui_capabilities.permission_decision(self.ui('shadow'), binding, kind=kind)
                    self.assertEqual(decision.outcome, 'allow')
                    self.assertIsNotNone(ui_capabilities.permission_decision(self.ui('enforce'), binding, kind=kind))

    def test_revoked_view_cannot_replay_source_or_reuse_selection(self):
        from postriff_phase2.agent_runtime_v2 import ui_store
        auth = self.ui('enforce', {'domain:content':False})
        name = next(name for name, binding in ui_domain.QUERIES.items()
                    if binding.scope == 'workspace' and 'content' in (capability_registry.for_query(binding).data_grants or ()))
        record = {'artifactId':'33333333-3333-4333-8333-333333333333','manifest':{'queries':[{'name':name}]},'nextSeq':10,'revision':1}
        cur = mock.Mock()
        with mock.patch.object(ui_store, '_load', return_value=record):
            self.assertEqual(ui_store.events_after(cur,auth,record['artifactId'],0,10),[])
            replay = ui_store.replay_view(cur,auth,record['artifactId'],0)
            self.assertTrue(replay['done'])
            self.assertEqual(replay['cursor'],9)
            self.assertIsNone(ui_store.selection_context(cur,auth,{'artifactId':record['artifactId']}))
            with self.assertRaises(AlphaError):
                ui_store.persist_ui_state(cur,auth,record['artifactId'],0,{})
        cur.execute.assert_not_called()
        self.assertFalse(ui_store.permission_revoked(replace(auth,authz_mode='shadow'),record['manifest']))

    def test_executor_rechecks_current_grants_in_effect_transaction(self):
        ctx = self.ctx()
        tool = f.tool_adapter.REGISTRY['campaign_link']
        with authz.active_tool(ctx, tool.spec, {}, 'campaign'):
            with mock.patch.object(authz, 'load_grants', return_value=f.ap.from_scopes(f.WS, f.ME, {}, preset='none')), \
                 mock.patch.object(authz, 'provider_view_current', return_value=authz.ProviderView(())):
                with self.assertRaises(AlphaError) as caught:
                    authz.recheck(object(), ctx, state=f.workspace_state(), member=f.OWNER)
                self.assertEqual(caught.exception.code, 'agent_permission_revoked')
        self.assertIsNone(ctx.active_capability)

    def test_grounded_site_call_is_gated_and_shadow_result_matches_off(self):
        def context(mode):
            c = self.ctx(mode, {'domain:content':False})
            c.state, c.cur, c.page, c.now = c.authz_state, None, {}, f.NOW
            return c
        with mock.patch.dict(site_tools.EXECUTORS, {'queue.summary': lambda ctx: {'ok':True,'verified':True,'data':{'private':'facts'}}}):
            _, off = site_tools.run('queue.summary', {}, context('off'))
            _, shadow = site_tools.run('queue.summary', {}, context('shadow'))
            record, denied = site_tools.run('queue.summary', {}, context('enforce'))
        self.assertEqual(off, shadow)
        self.assertEqual(record['code'], 'agent_permission_denied')
        self.assertFalse(denied['ok'])
        self.assertNotIn('private', str(denied))

    def test_private_style_and_raw_screen_are_removed_before_manager_instructions(self):
        ctx = self.ctx('enforce', {'domain:memory_brand':False, 'domain:screen':False})
        ctx.style = {'personal':'private preference'}
        ctx.page = {'route':'/app','outline':[{'text':'private label'}],'visibleState':{'selection':'private'}}
        ctx.page_raw = copy.deepcopy(ctx.page)
        authz.filter_context(ctx)
        self.assertIsNone(ctx.style)
        self.assertEqual(ctx.page, {'route':'/app'})
        self.assertEqual(ctx.page_raw, {'route':'/app'})
        ctx.authz_mode = 'shadow'; ctx.config.permissions_for = lambda w:'shadow'
        ctx.style = {'personal':'same value'}
        authz.filter_context(ctx)
        self.assertEqual(ctx.style, {'personal':'same value'})

    def test_context_adapter_fails_closed_for_every_non_allow_decision(self):
        # Current context policies are R0; defend the shared adapter protocol if
        # a future provider/confirmation floor returns another decision.
        for outcome in ('confirm', 'approve', 'step_up', 'deny'):
            with self.subTest(outcome=outcome), mock.patch.object(authz, 'gate', return_value=SimpleNamespace(outcome=outcome)):
                ctx = self.ctx('enforce')
                ctx.style = {'personal':'private preference'}
                ctx.attachments = [{'assetId':'private-asset'}]
                ctx.chip_refs = [{'id':'private-reference'}]
                authz.filter_context(ctx)
                self.assertIsNone(ctx.style)
                self.assertEqual(ctx.attachments, [])
                self.assertEqual(ctx.chip_refs, [])
                state = {'page':{'title':'private'},'memoryLayers':'private','attachedThisTurn':['private']}
                filtered = authz.filter_app_state(ctx, state)
                self.assertIsNone(filtered['page'])
                self.assertIsNone(filtered['memoryLayers'])
                self.assertEqual(filtered['attachedThisTurn'], [])
                cur = mock.Mock()
                cur.fetchone.return_value = ({'capabilities':['context.memory_layers']},)
                self.assertFalse(authz.history_eligible(cur, ctx, 'assistant', {'runId':'old-run'}))

    def test_provider_scope_is_bound_to_exact_connection_argument(self):
        scope = authz.ProviderScope('YouTube',scopes=('analytics',))
        view = authz.ProviderView(({'id':'permitted','platform':'YouTube','connectionState':'connected','scopes':['analytics'],'capabilities':{}},))
        self.assertEqual(authz.provider_check(view,scope,{'connectionId':'other'},now=f.NOW),'provider_not_connected')

    def test_app_state_narrows_without_enabling_context_lens(self):
        state = {'page':{'title':'Home'},'screen':{'private':'label'},'visibleState':'visible private',
                 'memoryLayers':'private style','activeTask':{'title':'private task'},'attachedThisTurn':['asset'],
                 'connections':'account'}
        narrowed = {'domain:screen':False,'domain:memory_brand':False,'domain:content':False,'domain:connections':False}
        self.assertEqual(authz.filter_app_state(self.ctx('shadow', narrowed), state), state)
        reduced = authz.filter_app_state(self.ctx('enforce', narrowed), state)
        for key in ('screen','visibleState','memoryLayers','activeTask','connections'):
            self.assertIsNone(reduced[key])
        self.assertEqual(reduced['attachedThisTurn'], [])
        self.assertEqual(state['screen'], {'private':'label'}, 'no source mutation')

    def test_historical_derived_prose_is_not_replayed_after_domain_revoke(self):
        cur = mock.Mock()
        cur.fetchone.return_value = ({'capabilities':['tool.campaign_items'], 'token':'older'},)
        body = {'runId':'run-id','text':'private facts'}
        c = self.ctx('enforce', {'domain:content':False})
        self.assertFalse(authz.history_eligible(cur, c, 'assistant', body))
        self.assertTrue(authz.history_eligible(cur, c, 'user', body))
        self.assertTrue(authz.history_eligible(cur, self.ctx('shadow', {'domain:content':False}), 'assistant', body))
        cur.fetchone.return_value = (None,)
        self.assertFalse(authz.history_eligible(cur, c, 'assistant', body), 'unknown old provenance fails closed after a choice')

    def test_manager_and_specialist_tool_reach_only_narrows_in_enforce(self):
        names = ['help_search','campaign_items']
        narrowed = {'domain:content':False}
        self.assertEqual(authz.filter_tools(self.ctx('shadow', narrowed), names, agent='campaign'), names)
        self.assertEqual(authz.filter_tools(self.ctx('enforce', narrowed), names, agent='campaign'), ['help_search'])

    def test_current_human_youtube_matcher_rejects_quotes_and_negations(self):
        self.assertTrue(authz._youtube_requested('Read my YouTube analytics.', analytics=True))
        for text in ['hi', 'Explain YouTube analytics', 'Do not read my YouTube analytics.', '"Read my YouTube analytics"']:
            self.assertFalse(authz._youtube_requested(text, analytics=True), text)

    def test_background_capability_absence_keeps_human_automations_unchanged(self):
        cur = mock.Mock()
        authz.recheck_principal(cur, workspace_id=f.WS, principal=f.ME, member=f.OWNER, state={}, capability=None)
        cur.execute.assert_not_called()
        with mock.patch.object(authz, 'load_grants', return_value=f.ap.from_scopes(f.WS, f.ME, {}, preset='none')):
            with self.assertRaises(AlphaError):
                authz.recheck_principal(cur, workspace_id=f.WS, principal=f.ME, member=f.OWNER, state={}, capability='tool.campaign_link', config=self.ctx().config)

    def test_proposal_gate_uses_creator_current_rights_not_decider(self):
        creator = 'creator-user'
        with mock.patch.object(authz, '_step_member', return_value=f.VIEWER) as member, \
             mock.patch.object(authz, 'load_grants', return_value=f.grants('full')) as load:
            with self.assertRaises(AlphaError) as caught:
                authz.gate_proposal(object(), f.WS, {}, {'type':'schedule_draft','createdBy':creator}, config=self.ctx().config, now=f.NOW)
            self.assertEqual(caught.exception.code, 'agent_permission_revoked')
            self.assertEqual(member.call_args.args[-1], creator)
            self.assertEqual(load.call_args.args[-1], creator)
