import copy
import unittest
from unittest import mock
from postriff_phase2 import suggestions
from postriff_phase2.agent_runtime_v2 import opportunity_feed as feed
from test_creator_pipeline import seed


class OpportunityProjection(unittest.TestCase):
    def test_current_suggestion_maps_to_review_without_task_or_provider_side_effect(self):
        state, body = seed(); before = copy.deepcopy(state)
        item = feed._suggestions(state, 100, {})[0]
        self.assertEqual(item['action']['kind'], 'prepare_task')
        self.assertEqual(item['action']['suggestionId'], body['suggestionId'])
        self.assertEqual(item['expectedBenefit']['kind'], 'estimate')
        self.assertEqual(state, before)

    def test_existing_task_replaces_duplicate_proposal_and_keeps_receipt_link(self):
        state, body = seed()
        item = feed._suggestions(state, 100, {body['suggestionId']: {'taskId': 'saved-task', 'state': 'awaiting_approval'}})[0]
        self.assertEqual(item['action'], {'kind': 'open', 'label': 'Inspect existing task', 'href': '/app/tasks?task=saved-task'})
        self.assertEqual(item['state'], 'awaiting_approval')

    def test_stale_dismissed_and_snoozed_sources_never_reappear(self):
        for status in ('stale', 'dismissed', 'snoozed'):
            state, _ = seed(); state['raffi']['suggestions'][0]['status'] = status
            self.assertEqual(feed._suggestions(state, 100, {}), [])

    def test_unavailable_facts_and_asset_metadata_offer_only_native_review(self):
        state, _ = seed(); state['raffi']['campaignPlanning']['campaigns'][0]['facts'] = {}
        self.assertEqual(feed._suggestions(state, 100, {})[0]['action']['kind'], 'open')
        state['phase2']['assets'].append({'id': 'image', 'processing': 'decoded', 'deleted': False})
        suggestions.refresh(state, 100)
        item = next(i for i in feed._suggestions(state, 100, {}) if i['evidence'][0]['type'] == 'asset')
        self.assertEqual(item['action']['href'], '/app/library')
        self.assertIn('not asset content', item['preview'])

    def test_listening_needs_current_consent_expiry_and_original_panel_for_scout(self):
        state = {'coworker': {'listening': {'watchlists': [], 'opportunities': [
            {'id':'lead','title':'Current source lead','why':'Matches selected topic','status':'open','expiresAt':200,'createdAt':90,'evidence':[]},
            {'id':'old','title':'Expired','why':'Old','status':'open','expiresAt':99,'evidence':[]},
            {'id':'scout','version':'scout.v1.2','title':'Original plan','why':'Native only','status':'open','expiresAt':200,'evidence':[]}]}}}
        with mock.patch.object(feed.flags, 'enabled', return_value=True), mock.patch.object(feed.research, 'allowed', return_value=True):
            with mock.patch.object(feed.listening, 'view', return_value={'opportunities': state['coworker']['listening']['opportunities']}):
                self.assertEqual([i['sourceId'] for i in feed._listening(state, 100)], ['lead'])
        with mock.patch.object(feed.flags, 'enabled', return_value=True), mock.patch.object(feed.research, 'allowed', return_value=False):
            self.assertEqual(feed._listening(state, 100), [])

    def test_source_digest_changes_when_measurement_or_permission_preview_changes(self):
        kwargs = {'source':'Performance','action':{'kind':'experiment','label':'Define experiment'}}
        a = feed._item('performance','p','Pattern','Observe',measurement={'window':'24h'},**kwargs)
        b = feed._item('performance','p','Pattern','Observe',measurement={'window':'7d'},**kwargs)
        self.assertNotEqual(a['digest'], b['digest'])

    def test_native_routes_are_bounded(self):
        for value in ('https://external.test', '//external.test', '/app/../api/admin', '/app/founder', '/app/queue?job=<script>'):
            self.assertEqual(feed._href(value), '/app/weekly')
        self.assertEqual(feed._href('/app/workspace/personalization'), '/app/workspace/personalization')


if __name__ == '__main__': unittest.main()
