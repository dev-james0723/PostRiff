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

    @contextmanager
    def connection(self):
        yield self

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=()):
        if sql.startswith('SELECT to_regclass'):
            self.row = ('present',)
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
