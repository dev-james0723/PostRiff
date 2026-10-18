"""Bounded, optional connection reuse behind Rafii's existing DB interface.

Construction performs no I/O. Each checkout commits or rolls back before the
role and session settings are reset; a failed reset discards the connection.
"""
import atexit
import math
import os
import threading
import time
from contextlib import contextmanager

from postriff_alpha.domain import AlphaError


def unavailable():
    return AlphaError('Database capacity is temporarily unavailable. Try again shortly.', 503,
                      code='database_capacity_unavailable')


class PooledPostgresFactory:
    def __init__(self, dsn, *, max_size=20, max_waiting=64, timeout=8, options=None, observer=None):
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError('A server-side database connection is required.')
        if (type(max_size) is not int or not 1 <= max_size <= 32
                or type(max_waiting) is not int or not 1 <= max_waiting <= 256
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or not .01 <= timeout <= 30
                or options is not None and (not isinstance(options, str) or len(options) > 200 or '\x00' in options)):
            raise ValueError('Database pool limits are invalid.')
        self._dsn, self._options, self._observer = dsn, options, observer
        self._max_size, self._max_waiting, self._timeout = max_size, max_waiting, timeout
        self._lock, self._pool, self._closed, self._pid = threading.RLock(), None, False, os.getpid()
        atexit.register(self.close)

    def _reset(self, connection):
        # The pool has already committed/rolled back the borrower's transaction.
        # Reset also protects against accidental session-scoped settings/roles.
        with connection.transaction():
            for statement in ('RESET ROLE', 'RESET ALL'):
                started, failure = time.monotonic(), None
                try:
                    connection.execute(statement)
                except Exception as error:
                    failure = type(error).__name__
                    raise
                finally:
                    if self._observer is not None:
                        self._observer('pool_reset', time.monotonic()-started, failure)

    def _ready(self):
        # An opened connection/lock must never be inherited into another worker.
        # Construct this factory within the serving process, after any fork.
        if os.getpid() != self._pid:
            raise unavailable()
        with self._lock:
            if self._closed:
                raise unavailable()
            if self._pool is None:
                try:
                    from psycopg_pool import ConnectionPool
                except ImportError as error:
                    raise RuntimeError('Install the pinned hosted PostgreSQL pool dependency.') from error
                kwargs = {'client_encoding': 'utf8', 'prepare_threshold': None, 'connect_timeout': 8}
                if self._options is not None:
                    kwargs['options'] = self._options
                pool = ConnectionPool(self._dsn, kwargs=kwargs, min_size=0, max_size=self._max_size,
                    max_waiting=self._max_waiting, timeout=self._timeout, max_idle=30, max_lifetime=300,
                    num_workers=2, open=False, reset=self._reset, name='rafii-postgres')
                pool.open(wait=False)
                self._pool = pool
            return self._pool

    @contextmanager
    def __call__(self):
        pool = self._ready()
        from psycopg_pool import PoolClosed, PoolTimeout, TooManyRequests
        try:
            with pool.connection(timeout=self._timeout) as connection:
                yield connection
        except (PoolClosed, PoolTimeout, TooManyRequests):
            raise unavailable() from None

    def stats(self):
        with self._lock:
            raw = self._pool.get_stats() if self._pool is not None else {}
            return {'enabled': True, 'opened': self._pool is not None, 'closed': self._closed,
                'maxConnections': self._max_size, 'maxWaiting': self._max_waiting,
                'checkoutTimeoutSeconds': self._timeout,
                'counters': {key: value for key, value in raw.items()
                             if isinstance(key, str) and type(value) in (int, float) and math.isfinite(value)}}

    def close(self):
        # No cross-process pool operations during child/parent shutdown.
        if os.getpid() != self._pid:
            return
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._pool is not None:
                self._pool.close(timeout=5)
