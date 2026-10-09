"""Synthetic scoped paging and authorized archive-route regressions; no Google calls."""
import copy
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.youtube.agent import YouTubePublishingAgent, prepare_policy
from postriff_phase2.youtube.http import handle
from postriff_phase2.youtube.pagination import live_page, projection
from test_youtube_agent import NOW, CONNECTION, CHANNEL, state, draft_and_policy


class PagingTests(unittest.TestCase):
    def records(self):
        return [{'id': 'draft-' + str(i), 'connectionId': CONNECTION, 'createdAt': i,
                 'digest': 'd' * 64, 'status': 'proposed', 'timing': {'timestamp': NOW + 900},
                 'createdBy': 'private-owner', 'authorizationGeneration': 'private-generation'} for i in range(80)]

    def test_pages_are_bounded_and_complete_with_equal_timestamps(self):
        records = self.records()
        for item in records: item['createdAt'] = 1
        records.append({'id': 'foreign', 'connectionId': 'another-channel', 'createdAt': 999})
        seen, cursor = [], None
        while True:
            page = live_page(records, 'workspace', CONNECTION, 'draft', NOW, cursor=cursor)
            self.assertLessEqual(len(page['items']), 25)
            seen.extend(item['id'] for item in page['items'])
            cursor = page['nextCursor']
            if cursor is None: break
        self.assertEqual(set(seen), {r['id'] for r in records[:-1]})
        self.assertEqual(len(seen), 80)
        self.assertNotIn('private-owner', str(page))
        self.assertNotIn('authorizationGeneration', str(page))

    def test_foreign_wrong_kind_tampered_and_changed_anchors_fail_closed(self):
        records = self.records()
        cursor = live_page(records, 'workspace', CONNECTION, 'draft', NOW)['nextCursor']
        for workspace, connection, kind, token in [('foreign', CONNECTION, 'draft', cursor),
                ('workspace', 'other-channel', 'draft', cursor), ('workspace', CONNECTION, 'policy', cursor),
                ('workspace', CONNECTION, 'draft', '!bad'), ('workspace', CONNECTION, 'draft', '')]:
            with self.subTest(scope=(workspace,connection,kind)), self.assertRaises(AlphaError):
                live_page(records, workspace, connection, kind, NOW, cursor=token)
        records[55]['status'] = 'queued'
        with self.assertRaises(AlphaError):
            live_page(records, 'workspace', CONNECTION, 'draft', NOW, cursor=cursor)

    def test_expired_authority_and_drafts_are_read_only_without_mutating_storage(self):
        value = state(); draft, policy = draft_and_policy(value)
        before = copy.deepcopy((draft, policy))
        self.assertTrue(projection(draft, 'draft', NOW + 9000)['readOnly'])
        self.assertEqual(projection(policy, 'policy', NOW + 90000)['status'], 'expired')
        self.assertNotIn('grantedBy', projection(policy, 'policy', NOW))
        self.assertEqual((draft,policy), before)
        self.assertTrue(projection({'status':'proposed','timing':None}, 'draft', NOW)['readOnly'])
        for limit in (0, 51, True, '25'):
            with self.assertRaises(AlphaError): live_page([], 'w', CONNECTION, 'draft', NOW, limit=limit)

    def test_only_known_proposal_origin_is_public_without_private_provenance(self):
        record = self.records()[0] | {'metadataOrigin': 'chat_model_proposal_requires_video_review',
            'metadataProvenance': {'traceId': 'server-private-trace', 'agentRunId': 'server-private-run'}}
        projected = projection(record, 'draft', NOW)
        self.assertEqual(projected['metadataOrigin'], 'chat_model_proposal_requires_video_review')
        self.assertNotIn('metadataProvenance', projected)
        self.assertNotIn('server-private', str(projected))
        record['metadataOrigin'] = 'unknown-origin'
        self.assertNotIn('metadataOrigin', projection(record, 'draft', NOW))

    def test_erased_tombstone_markers_survive_display_without_private_erasure_details(self):
        value = state(); draft, policy = draft_and_policy(value)
        for record, kind in ((draft, 'draft'), (policy, 'policy')):
            with self.subTest(kind=kind):
                record.update(privacyErased=True, privacyErasedAt=NOW,
                              privacyErasureReason='disconnect',
                              privateErasureEvidence={'authorizationGeneration': 'server-private'})
                before = copy.deepcopy(record)
                projected = live_page([record], 'workspace', CONNECTION, kind, NOW)['items'][0]
                self.assertIs(projected['privacyErased'], True)
                if kind == 'draft':
                    self.assertTrue(projected['readOnly'], 'Erasure fences a plan even before its status changes.')
                for key in ('privacyErasedAt', 'privacyErasureReason', 'privateErasureEvidence', 'authorizationGeneration',
                            'createdBy', 'grantedBy'):
                    self.assertNotIn(key, projected)
                self.assertNotIn('server-private', str(projected))
                self.assertEqual(record, before)
                record['privacyErased'] = {'private': 'server-private'}
                self.assertNotIn('privacyErased', projection(record, kind, NOW),
                                 'Only the canonical content-free boolean is public.')

    def test_policy_preview_rejects_changed_off_page_selection(self):
        value = state(); draft, _ = draft_and_policy(value)
        body = {'draftIds': [draft['id']], 'draftDigests': {draft['id']: 'changed-off-page'},
                'maxDaily': 1, 'timeZone': 'UTC', 'endsAt': NOW + 86400}
        with self.assertRaises(AlphaError) as caught:
            prepare_policy(value, CONNECTION, body, 'owner', NOW)
        self.assertEqual(caught.exception.code, 'youtube_agent_selection_changed')
        body['draftDigests'] = {draft['id']: draft['digest']}
        prepared = prepare_policy(value, CONNECTION, body, 'owner', NOW)
        self.assertEqual(prepared['drafts'], [{'id': draft['id'], 'digest': draft['digest']}])

    def test_overview_never_projects_fleet_lease_or_other_channel(self):
        value = state(); draft, policy = draft_and_policy(value)
        value['youtubeAgent']['fleetLease'] = {'id':'private-lease', 'authorization': {'grantedBy':'private-owner'}}
        value['youtubeAgent']['drafts'].append(copy.deepcopy(draft) | {'id':'foreign', 'connectionId':'other-channel'})
        before = copy.deepcopy(value)
        cursor, require_policy = Mock(), Mock()
        @contextmanager
        def transaction(token, workspace):
            self.assertEqual((token, workspace), ('token', 'workspace'))
            yield cursor, (1, copy.deepcopy(value), 'owner', False, False, False, False), 'owner'
        creator = SimpleNamespace(service=SimpleNamespace(),repository=SimpleNamespace(transaction=transaction),clock=lambda:NOW,
                                  oauth=SimpleNamespace(provider_for_connection=Mock(return_value=None),
                                                        youtube_policy=SimpleNamespace(require_user=require_policy)))
        agent = YouTubePublishingAgent(creator); agent._member = Mock(return_value=('owner',CHANNEL,value))
        overview = agent.overview('workspace','token',CONNECTION)
        self.assertEqual(len(overview['drafts']), 1)
        self.assertNotIn('fleetLease', overview)
        self.assertNotIn('grantedBy', str(overview))
        self.assertIn('pagination', overview)
        self.assertFalse(overview['autopilotGate']['canActivate'])
        require_policy.assert_called_once_with(cursor, 'workspace', 'owner', 'token', None, force=True)
        self.assertEqual(value, before, 'Reading overview cannot mutate standing authority or another channel.')


class HistoryRouteTests(unittest.TestCase):
    def route(self, method, tail, query='', body=None):
        app = SimpleNamespace(_body=Mock(return_value=body or {}),_json=Mock(side_effect=lambda _response,_status,data:data))
        service = SimpleNamespace(youtube=Mock())
        with patch('postriff_phase2.youtube.agent.YouTubePublishingAgent') as constructor:
            agent = constructor.return_value
            handle(app,{'QUERY_STRING':query},Mock(),service,'session',method,
                   ['api','workspaces','workspace','youtube',CONNECTION,'agent'] + tail)
            return agent

    def test_overview_and_history_queries_are_bounded_and_explicit(self):
        agent = self.route('GET', [], 'draftCursor=opaque&limit=30')
        agent.overview.assert_called_once_with('workspace','session',CONNECTION,draft_cursor='opaque',policy_cursor=None,limit=30)
        agent = self.route('GET', ['history','draft'], 'cursor=opaque&limit=25')
        agent.history.assert_called_once_with('workspace','session',CONNECTION,'draft',limit=25,cursor='opaque')
        self.route('POST',['history','archive'],body={'revision':5}).archive_history.assert_called_once_with(
            'workspace','session',CONNECTION,{'revision':5})
        for query in ('limit=0','limit=51','limit=large','limit=25&limit=50','unknown=1'):
            with self.subTest(query=query),self.assertRaises(AlphaError): self.route('GET',[],query)

    def agent(self, role='owner', revision=5):
        @contextmanager
        def transaction(*_args):
            yield Mock(), (revision, {}, role, False, False, False, False), 'owner'
        creator=SimpleNamespace(service=Mock(),repository=SimpleNamespace(transaction=transaction),clock=lambda:NOW)
        agent=YouTubePublishingAgent(creator);agent._member=Mock()
        return agent

    def test_archive_requires_locked_owner_and_revision_and_has_content_free_audit(self):
        expected={'revision':6,'archived':4,'draftsArchived':2,'policiesArchived':2}
        with patch('postriff_phase2.youtube.history.archive_and_compact',return_value=expected) as compact, \
                patch('postriff_phase2.hosted.throttle'),patch('postriff_phase2.hosted.audit') as audit:
            result=self.agent().archive_history('workspace','session',CONNECTION,{'revision':5})
            self.assertEqual(result['revision'],6)
            self.assertFalse(result['providerVerified'])
            self.assertEqual(audit.call_args.args[-1],{'archived':4,'draftsArchived':2,'policiesArchived':2})
            compact.reset_mock()
            for role,revision in [('editor',5),('viewer',5),('owner',4),('owner',True)]:
                with self.subTest(role=role,revision=revision),self.assertRaises(AlphaError):
                    self.agent(role).archive_history('workspace','session',CONNECTION,{'revision':revision})
                compact.assert_not_called()


if __name__=='__main__': unittest.main()
