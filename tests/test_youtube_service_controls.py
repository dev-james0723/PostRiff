"""Synthetic integration controls; these are not Google provider acceptance."""
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.youtube.capacity import CapacityController, CapacityPolicy
from postriff_phase2.youtube.service import YouTubeCreatorService


class MaintenanceDatabase:
    def __init__(self):
        self.row = None
        self.retention_scans = []

    @contextmanager
    def connection(self):
        yield self

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=()):
        if sql.startswith('SELECT to_regclass'):
            self.row = ('present',)
        elif sql.startswith('SELECT DISTINCT workspace_id::text FROM (SELECT workspace_id FROM public.pr_messages'):
            self.retention_scans.append('agent_context')
            self.row = None  # This focused maintenance fixture has no expired chat context.
        elif sql.startswith("SELECT id::text FROM public.pr_workspaces w WHERE (EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(w.state#>'{phase2,jobs}','[]'::jsonb)) j"):
            expected = (
                "j#>>'{manifest,platform}'='YouTube' AND NOT j ? 'youtubeProviderDataRemoved'",
                "j ? 'youtubeProviderOutput' AND jsonb_typeof(j#>'{youtubeProviderOutput,expiresAt}') IS DISTINCT FROM 'number'",
                "c->>'platform'='YouTube' AND c->>'evidenceSource'='live_provider' AND NOT c ? 'youtubeProviderDataRemoved'",
                "SELECT 1 FROM public.pr_youtube_uploads u WHERE u.workspace_id=w.id AND NOT u.state ? %s",
                "u.updated_at<=to_timestamp(%s)",
            )
            assert all(clause in sql for clause in expected) and sql.endswith(' ORDER BY id LIMIT 100'), sql
            assert len(params) == sql.count('%s') == 7, params
            now, cutoff = params[:2]
            assert params == (now, cutoff, cutoff, 'youtubeProviderDataRemoved', cutoff, cutoff, cutoff), params
            assert now - cutoff == 30 * 86400, params
            self.retention_scans.append('workspace_provider_data')
            self.row = None
        elif sql.startswith('SELECT w.id::text FROM public.pr_workspaces w WHERE EXISTS(SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof('):
            expected = (
                '{phase2,reviews}', '{phase2,jobs}', '{youtubeAgent,drafts}', '{youtubeAgent,policies}',
                "r#>>'{manifest,platform}'='YouTube'", "r#>>'{manifest,workspaceId}'=w.id::text",
                "r->>'privacyErased' IS DISTINCT FROM 'true'",
                'a.workspace_id=w.id AND a.privacy_erased_at IS NULL AND a.created_at<=to_timestamp(%s)',
                "c.workspace_id=w.id AND c.provider='youtube' AND c.revoked_at IS NOT NULL",
                "c.workspace_id=w.id AND c.provider='youtube' AND c.revoked_at IS NULL AND coalesce(c.youtube_identity_ingested_at,c.created_at)<=to_timestamp(%s)",
            )
            assert all(clause in sql for clause in expected) and sql.endswith(' ORDER BY w.id LIMIT 100'), sql
            assert len(params) == sql.count('%s') == 2 and params[0] == params[1], params
            self.retention_scans.append('privacy_erasure')
            self.row = None
        elif 'SELECT c.workspace_id' in sql:
            self.row = ('workspace', 'connection')
        elif sql.startswith(('DELETE ', 'INSERT ')):
            pass
        elif sql.startswith('UPDATE public.pr_youtube_actions SET receipt=NULL,secret_ciphertext=NULL,secret_key_id=NULL WHERE updated_at'):
            pass
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.row

    def fetchall(self):
        return [self.row] if self.row is not None else []


class CreatorControlTests(unittest.TestCase):
    def test_returned_legacy_binding_requires_intervention_without_revoking_grant(self):
        db = MaintenanceDatabase()
        creator = YouTubeCreatorService.__new__(YouTubeCreatorService)
        creator.service = SimpleNamespace(connection_factory=db.connection)
        creator.oauth = SimpleNamespace(
            providers={'youtube': SimpleNamespace(creator_enabled=True)},
            reverify_for_worker=Mock(return_value={'state': 'client_binding_missing', 'ready': False}),
            mark_youtube_revoked=Mock())
        creator.operational_error = Mock()
        creator.notifications = SimpleNamespace(renew_one=Mock(return_value=False))
        creator.agent = SimpleNamespace(dispatch_one=Mock(return_value={'dispatched': False}))
        result = creator.maintenance()
        self.assertEqual(result['reconnectionRequired'], 'youtube_oauth_binding_required')
        self.assertFalse(result['authorizationChecked'])
        creator.operational_error.assert_called_once()
        creator.oauth.mark_youtube_revoked.assert_not_called()
        self.assertEqual(db.retention_scans, ['agent_context', 'workspace_provider_data', 'privacy_erasure'])

    def test_bulk_approval_checks_final_queue_but_idempotent_retry_does_not_add_work(self):
        commands = HostedPhase2Commands.__new__(HostedPhase2Commands)
        commands.youtube_capacity = CapacityController(None, CapacityPolicy('synthetic', pending_per_workspace=1))
        state = {'phase2': {'jobs': [
            {'id': 'old', 'state': 'approved', 'manifest': {'platform': 'YouTube'}},
            {'id': 'new', 'state': 'approved', 'manifest': {'platform': 'YouTube'}}]}}
        with self.assertRaises(AlphaError) as error:
            commands._check_youtube_queue(state, {'old'})
        self.assertEqual(error.exception.code, 'youtube_queue_capacity')
        commands._check_youtube_queue(state, {'old', 'new'})

    def test_verified_channel_accepts_bound_lane_and_rejects_unknown_lane(self):
        commands = HostedPhase2Commands.__new__(HostedPhase2Commands)
        commands.engine = SimpleNamespace(invalidate=Mock())
        record = dict(id='connection', platform='YouTube', account='Channel', accountType='channel',
                      scopes=['youtube.readonly'], verifiedAt=1, expiresAt=2, capabilityVersion=1,
                      providerAccountId='UCsynthetic', authorizationLane='agentic', refreshBindingRequired=False)
        state = {'phase2': {'channels': []}}
        commands.upsert_verified_channel(state, 'owner', record)
        self.assertEqual(state['phase2']['channels'][0]['authorizationLane'], 'agentic')
        with self.assertRaises(AlphaError):
            commands.upsert_verified_channel(state, 'owner', {**record, 'authorizationLane': 'other'})


if __name__ == '__main__':
    unittest.main()
