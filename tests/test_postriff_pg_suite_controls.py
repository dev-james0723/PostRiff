"""Inert catalog routing control; no SQL, network or subprocess execution."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pg_suite_controls',ROOT/'scripts/postriff_pg_suite.py')
suite=importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


class PostgreSQLCatalogControls(unittest.TestCase):
    def test_guarded_fixtures_use_explicit_owned_routes_without_changing_ordinary_selection(self):
        self.assertEqual(set(suite.OWNED_CLOUD_ONLY),{'postgres_discord_authorization.py',
            'postgres_discord_connections.py','postgres_discord_worker.py',
            'postgres_discord_rate_limits.py','postgres_discord_capacity.py',
            'postgres_discord_admission_index_probe.py','postgres_discord_engagement.py',
            'postgres_discord_multimode.py'})
        ordinary=[Path('postgres_alpha.py'),Path('postgres_beta.py')]
        guarded=[Path(name) for name in suite.OWNED_CLOUD_ONLY]
        self.assertEqual(suite.select_scripts(ordinary+guarded,[]),ordinary)
        self.assertEqual(suite.select_scripts(ordinary+guarded,['postgres_beta']),ordinary[1:])
        for path in guarded:
            with self.assertRaisesRegex(ValueError,'guarded cloud route'):
                suite.select_scripts(ordinary+guarded,[path.stem])
        workflow=(ROOT/'.github/workflows/consumer-ready.yml').read_text()
        guarded=(ROOT/'scripts/discord-validation-cloud.sh').read_text()
        self.assertIn('discord_validation_gate engagement-sql python scripts/postriff_disposable_postgres.py tests/phase2/postgres_discord_engagement.py',guarded)
        self.assertIn('ci-postgres python scripts/postriff_pg_suite.py',workflow)
        self.assertIn('ci-discord-p0-p4 timeout --signal=TERM --kill-after=60s 15m bash scripts/discord-p4-validation-cloud.sh',workflow)


if __name__=='__main__':unittest.main()
