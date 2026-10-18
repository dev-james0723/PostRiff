"""Worker safety and rejection of fictional generic Twitch publishing."""
import contextlib
import io
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.store import Phase2Store
from postriff_phase2.twitch_worker import main, production_target_allowed, tick


class RuntimeBoundaries(unittest.TestCase):
    def test_production_target_binds_sql_and_supabase_to_same_canonical_project(self):
        project = 'buoyhkbodnhzngaotoel'
        values = {'POSTRIFF_SUPABASE_URL': f'https://{project}.supabase.co'}
        for database in (f'postgresql://postgres:synthetic@db.{project}.supabase.co:5432/postgres?sslmode=require',
                         f'postgresql://postgres.{project}:synthetic@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres'):
            with self.subTest(database=database):
                self.assertTrue(production_target_allowed({**values, 'POSTRIFF_DATABASE_URL': database}))

    def test_wrong_project_or_query_routing_cannot_masquerade_as_production(self):
        project = 'buoyhkbodnhzngaotoel'
        base = f'postgresql://postgres:synthetic@db.{project}.supabase.co/postgres'
        values = {'POSTRIFF_SUPABASE_URL': f'https://{project}.supabase.co', 'POSTRIFF_DATABASE_URL': base}
        for change in ({'POSTRIFF_DATABASE_URL': 'postgresql://postgres.oxacvkhpfgytkepxcaqh:synthetic@aws-0-ap-southeast-1.pooler.supabase.com/postgres'},
                       {'POSTRIFF_DATABASE_URL': base + '?host=db.oxacvkhpfgytkepxcaqh.supabase.co'},
                       {'POSTRIFF_DATABASE_URL': base + '?hostaddr=127.0.0.1'},
                       {'POSTRIFF_DATABASE_URL': base.replace('/postgres', '/another_database')},
                       {'POSTRIFF_DATABASE_URL': 'postgresql://postgres:synthetic@localhost:abc/postgres'},
                       {'POSTRIFF_SUPABASE_URL': 'https://oxacvkhpfgytkepxcaqh.supabase.co'},
                       {'POSTRIFF_DATABASE_URL': ''}):
            with self.subTest(change=change):
                self.assertFalse(production_target_allowed({**values, **change}))

    def test_invalid_production_configuration_fails_before_runtime_initialization(self):
        with patch.dict(os.environ, {'VERCEL_ENV': 'production'}, clear=True), \
             patch('postriff_phase2.hosted_app.runtime_from_environment') as runtime, \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            main([])
        self.assertEqual(stopped.exception.code, 2)
        runtime.assert_not_called()

    def test_disabled_worker_never_starts_token_validation(self):
        twitch = SimpleNamespace(enabled=False, maintenance=Mock(return_value={'enabled': False}), validation_tick=Mock())
        self.assertEqual(tick(twitch, limit=1, startup=True), {'enabled': False})
        twitch.validation_tick.assert_not_called()

    def test_worker_stdout_excludes_provider_content_and_secrets(self):
        twitch = SimpleNamespace(enabled=True, validation_tick=Mock(return_value={'validated': 1}),
            maintenance=Mock(return_value={'enabled': True, 'actions': [{'state': 'succeeded', 'data': 'viewer-content-canary'}],
                                          'result': 'synthetic-private-key-canary'}))
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), \
             patch('postriff_phase2.hosted_app.runtime_from_environment', return_value=(SimpleNamespace(twitch=twitch), None, {})), \
             contextlib.redirect_stdout(output):
            self.assertEqual(main([]), 0)
        twitch.validation_tick.assert_called_once_with(limit=10, startup=True)
        self.assertIn('succeeded', output.getvalue())
        self.assertNotIn('canary', output.getvalue())

    def test_generic_text_publisher_rejects_twitch_even_if_fixture_claims_verified(self):
        state = {'phase2': {'channels': [{'id': 'twitch-connection', 'platform': 'Twitch',
                                        'configured': True, 'identityVerified': True}]}}
        store = object.__new__(Phase2Store)
        with patch.object(store, '_variant', return_value={'sourceIds': []}), \
             patch('postriff_phase2.store.content_preflight', return_value=[]), self.assertRaises(AlphaError) as denied:
            store.build_manifest(state, {'variantId': 'draft', 'channelId': 'twitch-connection'}, 'actor')
        self.assertEqual(denied.exception.status, 409)
        self.assertEqual(denied.exception.code, 'twitch_native_only')


if __name__ == '__main__':
    unittest.main()
