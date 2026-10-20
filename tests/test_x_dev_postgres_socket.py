"""Regression: the synthetic X browser PostgreSQL must boot on unprivileged Linux."""
import unittest
from unittest.mock import patch

from scripts import postriff_dev_hosted as harness


class XDevPostgresSocket(unittest.TestCase):
    @patch.object(harness.subprocess, 'run')
    @patch.object(harness.tempfile, 'mkdtemp', return_value='/tmp/postriff-dev-pg-x-test')
    def test_disposable_pgctl_uses_own_writable_socket_directory(self, mkdtemp, run):
        dsn, data = harness.start_postgres(55392)
        pgctl_calls = [call.args[0] for call in run.call_args_list
                       if len(call.args[0]) > 0 and str(call.args[0][0]).endswith('/pg_ctl')]
        self.assertEqual(len(pgctl_calls), 1)
        options = pgctl_calls[0][pgctl_calls[0].index('-o') + 1]
        self.assertIn('-h 127.0.0.1', options)
        self.assertIn('-p 55392', options)
        self.assertIn('-k /tmp/postriff-dev-pg-x-test', options,
                      'Do not default to root-owned /var/run/postgresql on Ubuntu.')
        self.assertEqual(dsn, 'host=127.0.0.1 port=55392 dbname=postgres')
        self.assertEqual(str(data), '/tmp/postriff-dev-pg-x-test/data')

if __name__ == '__main__':
    unittest.main()
