"""Scoped calendar projections of real local plans; synthetic, no model/Google calls."""
import copy
import json
import unittest
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.permissions import Membership
from postriff_phase2.site_agent import tools, reads
from postriff_phase2.agent_runtime_v2.ui_domain import calendar
from postriff_phase2.youtube.agent import draft_digest, prepare_draft
from test_youtube_agent import ASSET, CONNECTION, NOW, body, state


def context(value=None, *, workspace='workspace-one', role='owner', zone='UTC'):
    return tools.Context(state=value if value is not None else state(), membership=Membership.from_row(role),
                         principal='owner', workspace_id=workspace, now=NOW, zone=zone)


def planned():
    value = state()
    draft = prepare_draft(value, CONNECTION, body(), 'owner', NOW)
    return value, draft


class YouTubePlanCalendarTests(unittest.TestCase):
    def test_unapproved_plan_is_awaiting_approval_in_both_calendar_readers(self):
        value, draft = planned()
        ctx = context(value, zone='America/New_York')
        entries = reads._entries(ctx, NOW, NOW + 86400, ctx.zone)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual((entry['kind'], entry['state'], entry['id']), ('youtube_plan', 'ready_for_review', draft['id']))
        self.assertEqual(entry['channelId'], CONNECTION)
        self.assertEqual(entry['at'], draft['timing']['timestamp'])
        self.assertEqual(tools.calendar_status_counts(entries)[0]['awaiting_approval'], 1)
        dctx = SimpleNamespace(zone=ctx.zone, now=NOW, state=value, revision=1, site_context=lambda: ctx)
        result = calendar.calendar_agenda(dctx, {'platform': 'YouTube', 'channelId': CONNECTION}, None)
        data = result['data']
        self.assertEqual(data['entries'][0]['status'], 'awaiting_approval')
        self.assertEqual(data['statusCounts']['scheduled'], 0)
        self.assertEqual(data['entries'][0]['href'], '/app/youtube')
        self.assertEqual(value['phase2']['jobs'], [])
        self.assertEqual(value['phase2']['reviews'], [])

    def test_projection_excludes_authority_private_goals_descriptions_and_storage(self):
        value, draft = planned()
        draft.update(goal='PRIVATE_GOAL', createdBy='PRIVATE_OWNER', metadataProvenance={'traceId': 'PRIVATE_RUN'},
                     authorizationGeneration='PRIVATE_GENERATION', fleetLease={'token': 'PRIVATE_LEASE'})
        draft['publishOptions']['description'] = 'PRIVATE_DESCRIPTION'
        value['variants'][0]['text'] = 'PRIVATE_DESCRIPTION'
        draft['digest'] = draft_digest(draft)
        value['youtubeAgent']['fleetLease'] = {'token': 'PRIVATE_WORKSPACE_LEASE'}
        projected = json.dumps(reads._entries(context(value), NOW, NOW + 86400, 'UTC'))
        for private in ('PRIVATE_', 'metadataProvenance', 'assetHash', 'objectName', 'fleetLease', 'authorizationGeneration', 'createdBy'):
            self.assertNotIn(private, projected)
        self.assertIn('Approved title', projected)

    def test_queued_or_existing_job_review_reference_is_never_duplicated(self):
        for shape in ('queued', 'job_id', 'job', 'review'):
            value, draft = planned()
            if shape == 'queued':
                draft['status'] = 'queued'
            elif shape == 'job_id':
                draft['jobId'] = 'existing'
            else:
                key = 'jobs' if shape == 'job' else 'reviews'
                value['phase2'][key].append({'id': 'existing', 'manifest': {'variantId': draft['variantId']}})
            with self.subTest(shape=shape):
                self.assertEqual(reads._youtube_plans(context(value), NOW, NOW + 86400, 'UTC'), [])

    def test_stale_foreign_revoked_and_malformed_plan_bindings_are_hidden(self):
        for shape in ('channel', 'revoked', 'asset_hash', 'digest', 'timing', 'variant', 'options', 'missing_id'):
            value, draft = planned()
            if shape == 'channel':
                draft['channelId'] = 'UC' + 'z' * 22
                draft['digest'] = draft_digest(draft)
            elif shape == 'revoked':
                value['phase2']['channels'][0]['revoked'] = True
            elif shape == 'asset_hash':
                value['phase2']['assets'][0]['hash'] = 'e' * 64
            elif shape == 'digest':
                draft['digest'] = 'bad'
            elif shape == 'timing':
                draft['timing']['timestamp'] = float('nan')
            elif shape == 'options':
                draft['publishOptions'] = None
                draft['digest'] = draft_digest(draft)
            elif shape == 'missing_id':
                draft.pop('id')
                draft['digest'] = draft_digest(draft)
            else:
                value['variants'][0]['revision'] += 1
            with self.subTest(shape=shape):
                self.assertEqual(reads._youtube_plans(context(value), NOW, NOW + 86400, 'UTC'), [])

    def test_unhashable_draft_bindings_are_hidden_before_reference_membership(self):
        for field in ('variantId', 'assetId', 'connectionId', 'id'):
            for invalid in ([], {}):
                value, draft = planned()
                draft[field] = invalid
                draft['digest'] = draft_digest(draft)
                with self.subTest(field=field, invalid=invalid):
                    self.assertEqual(reads._entries(context(value), NOW, NOW + 86400, 'UTC'), [])

    def test_malformed_job_and_review_reference_ids_do_not_break_valid_plan_projection(self):
        for collection in ('jobs', 'reviews'):
            for invalid in ([], {}, '', None):
                value, draft = planned()
                value['phase2'][collection].append({'id': 'malformed-reference', 'manifest': {'variantId': invalid}})
                with self.subTest(collection=collection, invalid=invalid):
                    entries = reads._entries(context(value), NOW, NOW + 86400, 'UTC')
                    self.assertEqual([entry['id'] for entry in entries], [draft['id']])
                    self.assertEqual(entries[0]['state'], 'ready_for_review')

    def test_workspace_identity_is_checked_and_expired_proposals_use_history(self):
        value, draft = planned()
        with self.assertRaises(AlphaError):
            reads._youtube_plans(context(value, workspace='other-workspace'), NOW, NOW + 86400, 'UTC')
        draft['timing']['timestamp'] = NOW - 60
        draft['digest'] = draft_digest(draft)
        self.assertEqual(reads._youtube_plans(context(value), NOW - 3600, NOW + 3600, 'UTC'), [])
        self.assertIn(draft, value['youtubeAgent']['drafts'])

    def test_inconsistent_more_than_100_pending_plans_fails_instead_of_truncating(self):
        value, draft = planned()
        value['youtubeAgent']['drafts'] = [copy.deepcopy(draft) for _ in range(101)]
        with self.assertRaises(AlphaError) as raised:
            reads._youtube_plans(context(value), NOW, NOW + 86400, 'UTC')
        self.assertEqual(raised.exception.code, 'youtube_calendar_projection_limit')


class YouTubePlannerAttentionTests(unittest.TestCase):
    @staticmethod
    def paused():
        from postriff_phase2.youtube.agent import prepare_policy
        value, draft = planned()
        policy = prepare_policy(value, CONNECTION, {'draftIds': [draft['id']], 'timeZone': 'UTC',
                                                   'maxDaily': 1, 'endsAt': NOW + 86400}, 'owner', NOW)
        policy.update(status='paused', intervention={'code': 'youtube_agentic_oauth_required',
                                                     'message': 'PRIVATE_ERROR_TOKEN https://private.example/?secret=hidden', 'at': NOW})
        return value, policy

    def test_real_prepared_policy_intervention_surfaces_without_job_or_state_mutation(self):
        value, policy = self.paused()
        before = copy.deepcopy(value)
        ctx = context(value)
        projected = reads._youtube_interventions(ctx)
        self.assertEqual(value, before)
        # Global attention already initializes the unrelated campaign root.
        expected = copy.deepcopy(before)
        expected.setdefault('raffi', {}).setdefault('campaignPlanning',
            {'campaigns': [], 'recurringTasks': [], 'occurrences': []})
        facts = reads.attention_summary(ctx)['data']['facts']
        self.assertEqual([fact for fact in facts if fact['kind'] == 'youtube_agent_intervention'], projected)
        alert = next(fact for fact in facts if fact['kind'] == 'youtube_agent_intervention')
        self.assertEqual(alert['policyId'], policy['id'])
        self.assertEqual(alert['source'], 'youtube_policy_intervention')
        self.assertEqual(alert['href'], '/app/youtube')
        self.assertIn('planner intervention', alert['text'])
        self.assertEqual(value['phase2']['jobs'], [])
        self.assertEqual(value, expected)

    def test_projection_never_exposes_error_secret_url_owner_grant_or_asset_payload(self):
        value, policy = self.paused()
        policy.update(grantedBy='PRIVATE_OWNER', authorizationGeneration='PRIVATE_GRANT',
                      assetIds=['PRIVATE_ASSET'], callback='https://private.example')
        policy['intervention']['code'] = 'PRIVATE_ERROR_CODE'
        projected = json.dumps(reads._youtube_interventions(context(value)))
        for secret in ('PRIVATE_', 'private.example', 'secret=hidden', 'grantedBy', 'authorizationGeneration', 'assetIds'):
            self.assertNotIn(secret, projected)
        self.assertEqual(len(reads._youtube_interventions(context(value, role='viewer'))), 1)

    def test_foreign_workspace_and_denied_read_fail_closed(self):
        value, _ = self.paused()
        for ctx in (context(value, workspace='workspace-two'), context(value)):
            if ctx.workspace_id == 'workspace-one':
                ctx.membership = SimpleNamespace(allows=lambda _right: False)
            with self.subTest(workspace=ctx.workspace_id), self.assertRaises(AlphaError) as raised:
                reads._youtube_interventions(ctx)
            self.assertEqual(raised.exception.code, 'tool_forbidden')

    def test_foreign_erased_revoked_and_malformed_records_are_hidden(self):
        for change in ('connection', 'channel', 'channel_revoked', 'erased', 'status', 'id', 'code', 'time', 'future'):
            value, policy = self.paused()
            if change == 'connection': policy['connectionId'] = 'foreign-connection'
            elif change == 'channel': policy['channelId'] = 'UC' + 'z' * 22
            elif change == 'channel_revoked': value['phase2']['channels'][0]['revoked'] = True
            elif change == 'erased': policy['privacyErased'] = True
            elif change == 'status': policy['status'] = 'revoked'
            elif change == 'id': policy['id'] = []
            elif change == 'code': policy['intervention']['code'] = {}
            elif change == 'time': policy['intervention']['at'] = float('nan')
            else: policy['intervention']['at'] = NOW + 1
            with self.subTest(change=change):
                self.assertEqual(reads._youtube_interventions(context(value)), [])
        value, _ = self.paused()
        value['youtubeAgent']['policies'] = None
        self.assertEqual(reads._youtube_interventions(context(value)), [])

    def test_matching_held_job_deduplicates_policy_but_foreign_job_does_not(self):
        for connection, expected in ((CONNECTION, 0), ('foreign-connection', 1)):
            value, policy = self.paused()
            value['phase2']['jobs'].append({'id': 'held-job', 'state': 'held',
                'manifest': {'platform': 'YouTube', 'channelId': connection},
                'youtubeAgent': {'policyId': policy['id']}})
            with self.subTest(connection=connection):
                self.assertEqual(len(reads._youtube_interventions(context(value))), expected)

    def test_facts_are_bounded_deduplicated_and_not_lost_to_existing_attention_cap(self):
        value, policy = self.paused()
        value['youtubeAgent']['policies'] = [copy.deepcopy(policy) for _ in range(20)]
        for index, item in enumerate(value['youtubeAgent']['policies']): item['id'] = format(index, '032x')
        value['youtubeAgent']['policies'].insert(0, copy.deepcopy(value['youtubeAgent']['policies'][0]))
        facts = reads._youtube_interventions(context(value))
        self.assertEqual(len(facts), 5)
        self.assertEqual(len({fact['policyId'] for fact in facts}), 5)
        # Many unrelated reconnect notices cannot hide actionable pre-job alerts.
        value['phase2']['channels'] += [{'id': 'account-' + str(i), 'platform': 'Threads', 'revoked': True} for i in range(20)]
        shown = reads.attention_summary(context(value))['data']['facts']
        self.assertEqual(len(shown), 15)
        self.assertEqual(sum(fact['kind'] == 'youtube_agent_intervention' for fact in shown), 5)


if __name__ == '__main__':
    unittest.main()
