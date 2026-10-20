"""No-egress diagnostics for the source-bound synthetic X CI gate."""
import tempfile
import unittest
from pathlib import Path
from scripts.x_direct_acceptance import wait_http


class DeadChild:
    def poll(self):
        return 1


class AcceptanceDriverDiagnostics(unittest.TestCase):
    def test_exited_fixture_surfaces_bounded_redacted_startup_error(self):
        with tempfile.TemporaryDirectory() as folder:
            logfile = Path(folder) / 'api.log'
            logfile.write_text('Starting fixture\nModuleNotFoundError: No module named safe_test_module\naccess_token=should-never-log\n')
            with self.assertRaises(RuntimeError) as caught:
                wait_http('http://127.0.0.1:1/irrelevant', DeadChild(), log_path=logfile)
            message = str(caught.exception)
            self.assertIn('ModuleNotFoundError', message)
            self.assertNotIn('should-never-log', message)
            self.assertLess(len(message), 5000)

    def test_missing_log_keeps_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, 'Fixture server exited before readiness'):
            wait_http('http://127.0.0.1:1/irrelevant', DeadChild(), log_path=Path('/nonexistent/x-acceptance-log'))


if __name__ == '__main__':
    unittest.main()
