"""Inert pool contracts; actual connection/RLS/backpressure proof is remote."""
import os
import sys
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.postgres_pool import PooledPostgresFactory


class PoolControls(unittest.TestCase):
    def setUp(self):
        self.instances = []
        instances = self.instances
        class Busy(Exception): pass
        class Connection:
            def __init__(self): self.statements = []
            @contextmanager
            def transaction(self): yield self
            def execute(self, statement): self.statements.append(statement)
        class Pool:
            def __init__(self, dsn, **kwargs):
                self.kwargs, self.opened, self.closed, self.failure = kwargs, 0, 0, None
                self.connection_value = Connection()
                instances.append(self)
            def open(self, **kwargs): self.opened += 1
            @contextmanager
            def connection(self, **kwargs):
                if self.failure: raise self.failure
                try: yield self.connection_value
                finally: self.kwargs['reset'](self.connection_value)
            def close(self, **kwargs): self.closed += 1
            def get_stats(self): return {'pool_size': 1, 'requests_num': 2, 'private_dsn': 'never emit'}
        self.Busy = Busy
        self.fake = SimpleNamespace(ConnectionPool=Pool, PoolTimeout=Busy, TooManyRequests=Busy, PoolClosed=Busy)
        module = patch.dict(sys.modules, {'psycopg_pool': self.fake})
        module.start(); self.addCleanup(module.stop)
        sockets = patch('socket.socket.connect', side_effect=AssertionError('Real network forbidden'))
        sockets.start(); self.addCleanup(sockets.stop)

    def factory(self, **kwargs):
        result = PooledPostgresFactory('synthetic-owned-test', **kwargs)
        self.addCleanup(result.close)
        return result

    def test_construction_is_lazy_and_limits_are_bounded(self):
        factory = self.factory()
        self.assertFalse(self.instances)
        self.assertFalse(factory.stats()['opened'])
        for values in ({'max_size': True}, {'max_size': 33}, {'max_waiting': 0},
                       {'timeout': float('nan')}, {'timeout': 0}, {'options': '\x00'}):
            with self.subTest(values=values), self.assertRaises(ValueError): self.factory(**values)

    def test_one_pool_is_reused_and_prepared_statements_stay_disabled(self):
        factory = self.factory()
        with factory(): pass
        with factory(): pass
        self.assertEqual(len(self.instances), 1)
        pool = self.instances[0]
        self.assertEqual(pool.opened, 1)
        self.assertEqual((pool.kwargs['min_size'], pool.kwargs['max_size'], pool.kwargs['max_waiting']), (0, 20, 64))
        self.assertIsNone(pool.kwargs['kwargs']['prepare_threshold'])
        self.assertFalse(pool.kwargs['open'])

    def test_role_and_session_reset_is_applied_on_normal_and_exceptional_return(self):
        observed = []
        factory = self.factory(observer=lambda *args: observed.append(args))
        with factory(): pass
        with self.assertRaises(RuntimeError):
            with factory(): raise RuntimeError('synthetic rollback')
        self.assertEqual(self.instances[0].connection_value.statements, ['RESET ROLE', 'RESET ALL'] * 2)
        self.assertEqual(len(observed), 4)
        self.assertTrue(all(event[0] == 'pool_reset' and event[2] is None for event in observed))

    def test_capacity_errors_are_safe_503_without_connection_details(self):
        factory = self.factory()
        with factory(): pass
        self.instances[0].failure = self.Busy('private connection details')
        with self.assertRaises(AlphaError) as caught:
            with factory(): pass
        self.assertEqual((caught.exception.status, caught.exception.code), (503, 'database_capacity_unavailable'))
        self.assertNotIn('private connection', str(caught.exception))

    def test_close_is_idempotent_and_prevents_reopening(self):
        factory = self.factory()
        with factory(): pass
        factory.close(); factory.close()
        self.assertEqual(self.instances[0].closed, 1)
        with self.assertRaises(AlphaError):
            with factory(): pass
        self.assertTrue(factory.stats()['closed'])

    def test_opened_factory_cannot_cross_processes(self):
        factory = self.factory()
        with factory(): pass
        pid = os.getpid()
        with patch('postriff_phase2.postgres_pool.os.getpid', return_value=pid + 1):
            with self.assertRaises(AlphaError):
                with factory(): pass
        self.assertEqual(len(self.instances), 1)

    def test_stats_only_include_numeric_aggregates(self):
        factory = self.factory()
        with factory(): pass
        self.assertEqual(factory.stats()['counters'], {'pool_size': 1, 'requests_num': 2})
