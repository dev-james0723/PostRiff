"""Offline binding regressions. Never contact a production or staging database."""
import unittest
import runpy
from pathlib import Path
from postriff_phase2.social_release import (PRODUCTION_PROJECT, PRODUCTION_REF, PRODUCTION_URL,
                                          FORBIDDEN_PROJECT, FORBIDDEN_REF,
                                          reject_forbidden_bindings, require_production_binding)
from postriff_phase2.deployment import isolated_environment


class SocialReleaseBinding(unittest.TestCase):
    def values(self):
        return {'VERCEL_ENV': 'production', 'VERCEL_PROJECT_ID': PRODUCTION_PROJECT,
                'POSTRIFF_SUPABASE_URL': PRODUCTION_URL, 'NEXT_PUBLIC_SUPABASE_URL': PRODUCTION_URL,
                'POSTRIFF_DATABASE_URL': 'postgresql://postgres.' + PRODUCTION_REF + ':synthetic@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require'}

    def test_correct_binding_preserves_existing_production_configuration(self):
        values = self.values()
        self.assertEqual(require_production_binding(values)['databaseRef'], PRODUCTION_REF)
        self.assertEqual(isolated_environment(values), values)

    def test_runtime_alias_and_unknown_production_reject_before_backend_access(self):
        values = self.values()
        values['POSTRIFF_VERCEL_PROJECT_ID'] = values.pop('VERCEL_PROJECT_ID')
        self.assertEqual(isolated_environment(values), values)
        for patch in ({'POSTRIFF_DATABASE_URL': '[SENSITIVE]'},
                      {'POSTRIFF_VERCEL_PROJECT_ID': 'unknown'}):
            with self.subTest(patch=list(patch)), self.assertRaises(ValueError):
                isolated_environment({**values, **patch})
        with self.assertRaises(ValueError):
            isolated_environment({'VERCEL_ENV': 'production'})

    def test_standalone_storage_guard_preserves_release_validation(self):
        path = Path(__file__).resolve().parents[1] / 'src/postriff_phase2/deployment.py'
        guard = runpy.run_path(str(path))['isolated_environment']
        self.assertEqual(guard(self.values()), self.values())
        with self.assertRaises(ValueError):
            guard({**self.values(), 'VERCEL_PROJECT_ID': FORBIDDEN_PROJECT})

    def test_forbidden_project_urls_encoded_or_keyword_dsn_fail_closed(self):
        for name, value in (
                ('VERCEL_PROJECT_ID', FORBIDDEN_PROJECT),
                ('NEXT_PUBLIC_SUPABASE_URL', 'https://' + FORBIDDEN_REF + '.supabase.co'),
                ('POSTRIFF_DATABASE_URL', 'host=db.' + FORBIDDEN_REF + '.supabase.co password=never-print'),
                ('POSTRIFF_DATABASE_URL', 'postgresql://postgres.%6Fxacvkhpfgytkepxcaqh:never-print@aws-0-us-east-1.pooler.supabase.com/postgres')):
            with self.subTest(name=name), self.assertRaises(ValueError) as error:
                isolated_environment({**self.values(), name: value})
            self.assertNotIn('never-print', str(error.exception))

    def test_unknown_mismatched_and_non_tls_production_bindings_are_rejected(self):
        for patch in ({'VERCEL_PROJECT_ID': ''}, {'POSTRIFF_SUPABASE_URL': ''},
                      {'NEXT_PUBLIC_SUPABASE_URL': 'https://other.supabase.co'},
                      {'POSTRIFF_DATABASE_URL': '[SENSITIVE]'},
                      {'POSTRIFF_DATABASE_URL': self.values()['POSTRIFF_DATABASE_URL'].replace('require', 'disable')}):
            with self.subTest(patch=list(patch)), self.assertRaises(ValueError):
                require_production_binding({**self.values(), **patch})

    def test_keyword_tls_dsn_and_disposable_ci_do_not_need_secrets_exported(self):
        values = {**self.values(), 'POSTRIFF_DATABASE_URL': 'host=db.' + PRODUCTION_REF + '.supabase.co user=postgres password=synthetic sslmode=verify-full'}
        self.assertEqual(require_production_binding(values)['status'], 'PASS_BINDING_ONLY')
        self.assertIsNone(reject_forbidden_bindings({'CI': 'true', 'POSTRIFF_TEST_DSN': 'host=127.0.0.1'}))
