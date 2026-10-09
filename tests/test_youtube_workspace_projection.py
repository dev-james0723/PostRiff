"""Ordinary workspace presentation omits server-only YouTube authority and attribution."""
import copy
import json
import unittest
from postriff_phase2.hosted import HostedPhase2Commands, HostedWorkspaceService
from postriff_phase2.youtube.agent import prepare_draft
from test_youtube_agent import NOW, CONNECTION, body, state


class YouTubeWorkspaceProjectionTests(unittest.TestCase):
    def test_hosted_workspace_presentation_keeps_stored_provenance_and_hides_internal_branch(self):
        value = state()
        draft = prepare_draft(value, CONNECTION, body(), 'owner', NOW)
        private = {'traceId': 'internal-trace-marker', 'agentRunId': 'internal-run-marker', 'specialist': 'content'}
        draft['metadataProvenance'] = copy.deepcopy(private)
        value['variants'][-1]['metadataProvenance'] = copy.deepcopy(private)
        value['youtubeAgent']['fleetLease'] = {'id': 'internal-lease-marker', 'authorization': {'grantedBy': 'internal-owner-marker'}}
        value['youtubeAgent']['policies'] = [{'id': 'policy', 'authorizationGeneration': 'internal-generation-marker'}]
        before = copy.deepcopy(value)
        service = HostedWorkspaceService.__new__(HostedWorkspaceService)
        service.commands = HostedPhase2Commands(clock=lambda: NOW)
        result = service._present({'state': value, 'revision': 7, 'membership': {'role': 'owner'}})
        self.assertEqual(result['revision'], 7)
        self.assertEqual(result['membership']['role'], 'owner')
        self.assertNotIn('youtubeAgent', result['state'])
        self.assertNotIn('metadataProvenance', result['state']['variants'][-1])
        self.assertNotIn('internal-', json.dumps(result))
        self.assertEqual(result['state']['variants'][-1]['text'], 'Approved description')
        self.assertEqual(result['state']['phase2']['channels'][0]['providerAccountId'], before['phase2']['channels'][0]['providerAccountId'])
        self.assertEqual(value.get('youtubeAgent'), before.get('youtubeAgent'))
        self.assertEqual(value['variants'], before['variants'])

    def test_presentation_of_legacy_workspace_without_internal_youtube_state_is_unchanged(self):
        value = state()
        value['variants'].append({'id': 'other-platform', 'platform': 'Instagram', 'text': 'Keep this draft',
                                  'metadataProvenance': {'origin': 'other-provider-existing'}})
        before = copy.deepcopy(value)
        result = HostedPhase2Commands(clock=lambda: NOW).present(value, 3)
        self.assertEqual(len(result['state']['variants']), len(before['variants']))
        for key, expected in before['variants'][-1].items():
            self.assertEqual(result['state']['variants'][-1][key], expected)
        self.assertEqual(result['state']['workspace']['id'], before['workspace']['id'])
        self.assertEqual(value['variants'], before['variants'])
        self.assertEqual(value['phase2']['channels'], before['phase2']['channels'])


if __name__ == '__main__':
    unittest.main()
