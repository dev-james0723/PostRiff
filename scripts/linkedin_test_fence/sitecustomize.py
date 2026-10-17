"""Opt-in cloud test fence; never imported by the production application.

Fake provider transports remain responsible for responses. This additional
boundary refuses real remote sockets and any non-disposable psycopg database.
An unexpected attempt fails the entire process even if application code catches
the exception. Dependency installation occurs before this fence is enabled.
"""
import atexit
import ipaddress
import json
import os
import sys


if (os.environ.get('RAFII_LINKEDIN_SYNTHETIC_FENCE') == '1'
        or os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE') == '1'):
    if sys.platform != 'linux' or os.environ.get('CI') != 'true':
        raise SystemExit('Synthetic transport fence requires cloud Linux CI')

    _probe = False
    _expected = 0
    _unexpected = 0
    _loopback = 0

    def _deny():
        global _expected, _unexpected
        if _probe:
            _expected += 1
        else:
            _unexpected += 1
        raise RuntimeError('Synthetic fence refused a real transport or foreign database')

    def _local(host):
        if host == 'localhost':
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except (ValueError, TypeError):
            return False

    def _audit(event, args):
        global _loopback
        if event == 'socket.getaddrinfo':
            if not _local(args[0]):
                _deny()
        elif event == 'socket.connect':
            address = args[1]
            if isinstance(address, tuple):
                if not _local(address[0]):
                    _deny()
                _loopback += 1

    sys.addaudithook(_audit)

    try:
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
    except Exception:
        print('Synthetic fence unavailable: psycopg dependency did not load', file=sys.stderr, flush=True)
        os._exit(78)

    def _database(conninfo, kwargs):
        options = {k: v for k, v in kwargs.items() if k not in {
            'autocommit', 'prepare_threshold', 'context', 'row_factory', 'cursor_factory'}}
        values = conninfo_to_dict(conninfo, **options)
        host = values.get('host', os.environ.get('PGHOST', ''))
        port = values.get('port', os.environ.get('PGPORT', ''))
        name = values.get('dbname', os.environ.get('PGDATABASE', ''))
        user = values.get('user', os.environ.get('PGUSER', ''))
        if (host != '127.0.0.1' or str(port) != '55438' or name != 'postgres'
                or user != 'postriff_test' or values.get('password')
                or values.get('service') or values.get('hostaddr', '127.0.0.1') != '127.0.0.1'):
            _deny()

    _connect = psycopg.connect
    _class_connect = psycopg.Connection.connect.__func__

    def _checked_connect(conninfo='', **kwargs):
        _database(conninfo, kwargs)
        return _connect(conninfo, **kwargs)

    def _checked_class_connect(cls, conninfo='', **kwargs):
        _database(conninfo, kwargs)
        return _class_connect(cls, conninfo, **kwargs)

    psycopg.connect = _checked_connect
    psycopg.Connection.connect = classmethod(_checked_class_connect)

    def self_check():
        """Prove all three provider write methods are denied before network I/O."""
        global _probe
        from urllib.request import Request, urlopen
        _probe = True
        before = _expected
        try:
            for method in ('POST', 'PATCH', 'DELETE'):
                try:
                    urlopen(Request('https://discord.com/api/v10/channels/123456/messages' if os.environ.get('RAFII_DISCORD_SYNTHETIC_FENCE') == '1' else 'https://api.linkedin.com/rest/posts', data=b'{}', method=method), timeout=1)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Provider write was not fenced')
            try:
                psycopg.connect('host=production.example.invalid port=5432 dbname=postgres user=foreign')
            except RuntimeError:
                pass
            else:
                raise AssertionError('Foreign database was not fenced')
        finally:
            _probe = False
        assert _expected - before == 4 and _unexpected == 0
        print('RAFII_SYNTHETIC_FENCE_PROOF ' + json.dumps({
            'blockedMethods': ['POST', 'PATCH', 'DELETE'], 'foreignDatabaseBlocked': True,
            'realProviderRequests': 0, 'realLinkedInPosts': 0, 'realConsent': False}))

    def _receipt():
        print('RAFII_SYNTHETIC_FENCE_JSON ' + json.dumps({
            'active': True, 'expectedBlockedProbes': _expected,
            'unexpectedTransportAttempts': _unexpected, 'loopbackSockets': _loopback,
            'realProviderRequests': 0, 'realLinkedInPosts': 0,
            'database': 'disposable 127.0.0.1:55438/postgres/postriff_test'}), flush=True)
        if _unexpected:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(78)

    atexit.register(_receipt)
