"""G2E-A-09 (P14): a connection handed back with autocommit switched on must not reach the next borrower in that mode.

account_deletion.delete_account sets connection.autocommit = True on its lock connection. With the pool on, the next
borrower inherited it and every `SELECT ... FOR UPDATE` lock was released at the end of its statement. The real-database
proof is tests/phase2/postgres_discord_custody.py; this test pins the order of effects on a stand-in connection."""
import unittest

from postriff_phase2.postgres_pool import PooledPostgresFactory


class Connection:
    def __init__(self, autocommit):
        self.autocommit, self.log = autocommit, []

    def transaction(self):
        owner = self

        class Block:
            def __enter__(self_inner):
                owner.log.append(('transaction', owner.autocommit))

            def __exit__(self_inner, *exc):
                owner.log.append(('end', owner.autocommit))
        return Block()

    def execute(self, statement):
        self.log.append((statement, self.autocommit))


class ResetRestoresTransactionMode(unittest.TestCase):
    def factory(self):
        return PooledPostgresFactory('host=127.0.0.1 dbname=synthetic', max_size=1, max_waiting=1, timeout=1)

    def test_a_connection_returned_in_autocommit_mode_is_reset_to_transactional(self):
        connection = Connection(autocommit=True)
        self.factory()._reset(connection)
        self.assertIs(connection.autocommit, False)
        # the mode is restored before the reset statements run
        self.assertEqual(connection.log, [('transaction', False), ('RESET ROLE', False), ('RESET ALL', False), ('end', False)])

    def test_an_ordinary_connection_is_unchanged(self):
        connection = Connection(autocommit=False)
        self.factory()._reset(connection)
        self.assertIs(connection.autocommit, False)


if __name__ == '__main__':
    unittest.main()
