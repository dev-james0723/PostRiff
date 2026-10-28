#!/usr/bin/env python3
"""One cron invocation for the W-02 capacity harness, in its own OS process, through the real WSGI entry.

The process is the harness's stand-in for one Vercel function instance serving one cron request. It imports the tested
source tree's api/index.py (the Vercel entry point, `app`), then sleeps until its scheduled start, then serves exactly
one `GET <path>` with the cron secret, the way Vercel's runtime calls a WSGI app, and exits. Nothing is shared with
any other invocation: its own connections, provider, caches and coordinator state.

Before the application is imported, two fences are installed in this process only:
  - network: Python sockets may reach only 127.0.0.1/::1 and unix sockets, and name resolution only localhost;
    anything else is refused and recorded (a clean run records none);
  - Discord transport: providers.build_opener (the hook the repository's own tests use) returns an opener that sends
    https://discord.com/api/v10/... to the mock Discord on 127.0.0.1 over plain HTTP with no proxy; the application's
    own http_transport (its HTTPS check, headers, JSON, 20 s timeout, 256 KB cap and error handling) is unchanged.
Everything else is the tested code.

Writes one JSON result: timings (spawn, import, start, handler start/end, exit), status, response body, CPU and
memory, the request log lines the application emitted, and any refused egress.
"""
import argparse
import functools
import io
import json
import logging
import os
import re
import resource
import socket
import sys
import time

BLOCKED = []
# The permit the shared coordinator last admitted in this process. The next request this process sends carries it as
# X-Cap-Permit, so the analysis can join an admission to its arrival at the mock exactly (not by path and order).
CURRENT = {'permit': None}
# The shared coordinators this process called (id -> object): at the end of the invocation their own counters (booking_stats:
# bookings, seconds booked, horizonRefusals, gateStops) go into the invocation result.
COORDINATORS = {}


def coordinator_totals():
    """The sum of booking_stats() of every coordinator this process called, or None when none had it (a tree without booking)."""
    total = {}
    for coordinator in list(COORDINATORS.values()):
        getter = getattr(coordinator, 'booking_stats', None)
        if getter is None:
            continue
        try:
            for key, value in getter().items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    total[key] = total.get(key, 0) + value
        except Exception:
            continue
    return total or None


def fence_network():
    allowed_hosts = {'127.0.0.1', '::1', 'localhost'}
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def check(sock, address):
        if sock.family == getattr(socket, 'AF_UNIX', None):
            return
        host = address[0] if isinstance(address, tuple) else address
        if host not in allowed_hosts:
            BLOCKED.append({'kind': 'connect', 'host': str(host)[:80], 'at': time.time()})
            raise OSError(101, 'capacity harness: no network beyond localhost')

    def connect(self, address):
        check(self, address)
        return real_connect(self, address)

    def connect_ex(self, address):
        check(self, address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host not in allowed_hosts and host is not None:
            BLOCKED.append({'kind': 'resolve', 'host': str(host)[:80], 'at': time.time()})
            raise socket.gaierror(socket.EAI_NONAME, 'capacity harness: name resolution is fenced')
        return real_getaddrinfo(host, *args, **kwargs)
    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, getaddrinfo


def source_tag(path):
    """Which cron route an invocation serves, as a short tag the mock logs on every request it forwards."""
    if path.startswith('/api/cron/discord-worker/'):
        return 'lane' + path.rsplit('/', 1)[1][:6]
    return 'minute' if path == '/api/cron/worker' else 'other'


def shim_discord_transport(mock_port, source='other'):
    import urllib.request
    from urllib.error import URLError
    from postriff_phase2 import providers
    real_build_opener = urllib.request.build_opener
    origin = 'https://discord.com/api/v10'
    local = 'http://127.0.0.1:%d/api/v10' % mock_port
    counts = {'discord': 0, 'refused': 0, 'misrouted': 0}
    misroute_every = int(os.environ.get('CAP_MISROUTE_EVERY') or 0)

    def build_opener(*handlers):
        keep = [h for h in handlers if not isinstance(h, (urllib.request.HTTPSHandler, urllib.request.ProxyHandler))]
        opener = real_build_opener(urllib.request.ProxyHandler({}), *keep)

        class Opener:
            def open(self, request, timeout=None):
                url = request.full_url
                if not url.startswith(origin + '/'):
                    counts['refused'] += 1
                    BLOCKED.append({'kind': 'provider_url', 'host': url.split('/')[2][:80] if '//' in url else '?',
                                    'at': time.time()})
                    raise URLError('capacity harness: only the mock Discord is reachable')
                counts['discord'] += 1
                path = url[len(origin):]
                if misroute_every and request.get_method() == 'POST' and path.startswith('/channels/') \
                        and path.endswith('/messages') and request.data:
                    # Negative control only (scenario Nmisroute): send this create to the next tenant's channel.
                    import hashlib
                    if int(hashlib.sha256(request.data).hexdigest(), 16) % misroute_every == 0:
                        channel = path.split('/')[2]
                        path = '/channels/%d/messages' % (int(channel) + 1)
                        counts['misrouted'] += 1
                headers = dict(request.header_items())
                headers['X-Cap-Source'] = source
                if CURRENT['permit']:
                    headers['X-Cap-Permit'] = CURRENT['permit']
                    CURRENT['permit'] = None
                headers['X-Cap-Call-At'] = repr(time.time())  # the last thing before the call: the wire time's lower bound
                rewritten = urllib.request.Request(local + path, data=request.data, headers=headers,
                                                   method=request.get_method())
                return opener.open(rewritten, timeout=timeout)
        return Opener()
    providers.build_opener = build_opener
    return counts


GUILD0, CHANNEL0 = 1392000000000000000, 1393000000000000000  # the mock world's id bases (discord_lane_cap_mock)


def instrument_coordinator(path, source):
    """Record every call of the shared request coordinator in this process, and change nothing.

    reserve_read (a witness read, the grant check, the bot identity), reserve (the create permit), consume (the create
    leaving for the wire) and, after the request, observe (the answer recorded), note_transport_failure and
    abandon_unsent_read are wrapped: each call is logged as one JSON array [time, seconds the call took, operation (read,
    reserve, consume, observe, note_failure, abandon), method, route with ids masked, credential kind, workspace index where
    the path names a server or channel, outcome (A admitted, R refused with a wait, E error), the wait the coordinator quoted,
    its scope, its cause, the permit id when admitted, the cron source of this process, seconds booked, seconds slept, book-ahead
    room the caller allowed]. For an error that is not a refusal with a wait (outcome E) the scope column holds the class of the
    error (RateCoordinatorUnavailable) and the cause column the class and SQLSTATE of the failure the coordinator hid
    (LockNotAvailable:55P03 is a lock timeout). A refused reservation leaves no row in the database, so this log is the only
    record of the wait it was quoted. The wrapped methods return and raise exactly what the originals do.

    Booking (rate_limits.booking(), the lane's own): a reserve or reserve_read that finds the application window full may
    book the next free slot and SLEEP INSIDE THE CALL until it comes, up to a second, and then return the permit. So an
    admitted call is a slot reached, and the seconds it took include that sleep. The last three columns separate it: the
    seconds the coordinator booked for this call (the difference of its own booking_stats(), 0 when it did not book), the
    seconds the call actually spent in the wait for the slot and the gate after it (a wrapper around _wait_for_slot, 0 when
    that does not exist in the tree), and the room the caller allowed (`book_ahead`, None when it did not pass one, as
    outside booking()). A tree without booking leaves all three at 0, 0, None. Older logs have the first 13 columns only.

    Events go in the same file as rows with operation `event` and outcome V: a release of a post (the worker's
    release_discord_unsent: the reason, the seconds it was released for, the rate scope and cause; a coordinator that is
    unavailable releases for 300 s) and the moment `rate_coordinator_degraded` is set on the Discord provider of this process
    (after that every request of the process is refused before transport), with the coordinator call that failed just before.
    From 0cb19962 a failed outcome record degrades the process for 45 seconds (`DiscordProvider._coordinator_failed`, a timed
    event 'timed 45.0 s, from ...') and only a policy that does not parse sets the flag for good ('permanent, set at ...'). A
    reservation that met a lock or statement timeout is answered 'coordinator_busy' (the cause column then holds
    'coordinator_busy:' and the SQLSTATE of the hidden failure: 55P03 a lock timeout, 57014 a statement timeout)."""
    import threading
    from postriff_phase2.discord import rate_limits as limits
    COORDINATORS.clear()
    handle = open(path, 'a', buffering=1)
    cls = limits.SharedPostgresBudget
    waited = threading.local()  # seconds this thread spent in _wait_for_slot since the wrapped call began
    last_failed = threading.local()  # the coordinator call that failed last on this thread: (operation, outer class, cause)
    routes = {}  # permit id -> (method, target): an observation names its permit only

    def workspace(target):
        match = re.match(r'/(guilds|channels)/([0-9]{5,25})', target)
        if not match:
            return None
        number = int(match.group(2)) - (GUILD0 if match.group(1) == 'guilds' else CHANNEL0)
        return number if 0 <= number < 10 ** 9 else None

    def booked_total(coordinator):
        """The coordinator's own total of seconds booked so far (booking_stats), or None when the tree has none."""
        getter = getattr(coordinator, 'booking_stats', None)
        if getter is None:
            return None
        try:
            return float(getter().get('bookedWaitSeconds', 0.0))
        except Exception:
            return None

    def sqlstate_of(error):
        return getattr(error, 'sqlstate', None) or getattr(getattr(error, 'diag', None), 'sqlstate', None) or ''

    def hidden_cause(error):
        """The coordinator turns any failure inside its transaction into RateCoordinatorUnavailable (or, for a lock or statement
        timeout, its subclass RateCoordinatorBusy) and hides the cause (`raise ... from None`); the context is still on the
        exception. Its class and SQLSTATE go in the cause column. A reservation told 'coordinator_busy' (RateDelayed, raised in
        place of RateCoordinatorBusy) carries the same chain one step further down: the SQLSTATE is looked for along it."""
        if error is None or (isinstance(error, limits.RateDelayed) and getattr(error, 'rate_cause', None) != 'coordinator_busy'):
            return None
        chain, inner = [], error
        while len(chain) < 8:
            inner = getattr(inner, '__context__', None) or getattr(inner, '__cause__', None)
            if inner is None:
                break
            chain.append(inner)
        if not chain:
            return type(error).__name__
        for item in chain:
            if sqlstate_of(item):
                return '%s:%s' % (type(item).__name__, sqlstate_of(item))
        return '%s:' % type(chain[0]).__name__

    def cause_of(error):
        """The cause column: the coordinator's own for a refusal, with the SQLSTATE of the hidden failure behind a 'coordinator_busy'
        (55P03 a lock timeout, 57014 a statement timeout); the hidden failure's class and SQLSTATE for an error."""
        cause = getattr(error, 'rate_cause', None)
        if cause == 'coordinator_busy':
            return 'coordinator_busy:' + (hidden_cause(error) or '').rpartition(':')[2]
        return cause or hidden_cause(error)

    def emit(operation, method, target, identity, started, took, outcome, error=None, permit=None, booked=0.0, slept=0.0,
             room=None):
        failed = outcome == 'E'
        row = [round(started, 4), round(took, 4), operation, method, re.sub(r'/[0-9]{5,25}', '/{id}', target.split('?')[0]),
               getattr(identity, 'kind', None), workspace(target), outcome,
               round(error.retry_after_seconds, 4) if isinstance(error, limits.RateDelayed) else None,
               getattr(error, 'rate_scope_kind', None) or (type(error).__name__ if failed else None),
               cause_of(error),
               getattr(permit, 'id', None), source, round(booked, 4), round(slept, 4),
               round(float(room), 3) if isinstance(room, (int, float)) else None]
        handle.write(json.dumps(row, separators=(',', ':')) + '\n')
        if failed:
            last_failed.value = (operation, row[9], row[10])

    def emit_event(kind, detail, retry_after=None, scope=None, cause=None):
        row = [round(time.time(), 4), 0.0, 'event', kind, str(detail)[:160], None, None, 'V',
               round(float(retry_after), 3) if isinstance(retry_after, (int, float)) else None, scope, cause, None, source,
               0.0, 0.0, None]
        handle.write(json.dumps(row, separators=(',', ':')) + '\n')

    if hasattr(cls, '_wait_for_slot'):
        original_wait = cls._wait_for_slot

        @functools.wraps(original_wait)
        def timed_wait(self, *args, **kwargs):
            began = time.monotonic()
            try:
                return original_wait(self, *args, **kwargs)
            finally:
                waited.seconds = getattr(waited, 'seconds', 0.0) + (time.monotonic() - began)
        cls._wait_for_slot = timed_wait

    def wrap(name, operation):
        original = getattr(cls, name)

        @functools.wraps(original)
        def wrapper(self, *args, **kwargs):
            CURRENT['permit'] = None  # an earlier admission whose request never left must not stamp the next one
            COORDINATORS.setdefault(id(self), self)
            started, began = time.time(), time.monotonic()
            waited.seconds = 0.0
            before = booked_total(self)
            consuming = operation == 'consume'
            permit_arg = args[0] if consuming and args else None
            method, target = (args[1:3] if consuming else args[:2]) if len(args) >= 2 else ('?', '')
            if consuming and len(args) < 3:
                method, target = '?', ''
            identity = kwargs.get('identity') or getattr(permit_arg, 'identity', None)
            room = kwargs.get('book_ahead')

            def booked_by_this_call():
                after = booked_total(self)
                return max(0.0, after - before) if before is not None and after is not None else 0.0
            try:
                result = original(self, *args, **kwargs)
            except BaseException as error:
                emit(operation, method, target, identity, started, time.monotonic() - began,
                     'R' if isinstance(error, limits.RateDelayed) else 'E', error, None, booked_by_this_call(),
                     getattr(waited, 'seconds', 0.0), room)
                raise
            permit = permit_arg if consuming else result
            emit(operation, method, target, identity, started, time.monotonic() - began, 'A', None, permit,
                 booked_by_this_call(), getattr(waited, 'seconds', 0.0), room)
            if getattr(permit, 'id', None) and len(routes) < 4096:
                routes[permit.id] = (method, target)
            if operation != 'reserve':  # a create permit is stamped when it is consumed, just before the POST
                CURRENT['permit'] = getattr(permit, 'id', None)  # the slot has come: the next request is this admission's
            return result
        setattr(cls, name, wrapper)

    def wrap_after(name, operation):
        """A call made after the request left (the permit is its first argument): timed and logged, never stamping a permit."""
        original = getattr(cls, name)

        @functools.wraps(original)
        def wrapper(self, *args, **kwargs):
            started, began = time.time(), time.monotonic()
            permit = args[0] if args else kwargs.get('permit')
            method, target = routes.get(getattr(permit, 'id', None), (getattr(permit, 'method', '?'), ''))
            identity = getattr(permit, 'identity', None)
            try:
                result = original(self, *args, **kwargs)
            except BaseException as error:
                emit(operation, method, target, identity, started, time.monotonic() - began,
                     'R' if isinstance(error, limits.RateDelayed) else 'E', error, permit)
                raise
            emit(operation, method, target, identity, started, time.monotonic() - began, 'A', None, permit)
            return result
        setattr(cls, name, wrapper)
    for name, operation in (('reserve_read', 'read'), ('reserve', 'reserve'), ('consume', 'consume')):
        if hasattr(cls, name):
            wrap(name, operation)
    for name, operation in (('observe', 'observe'), ('note_transport_failure', 'note_failure'),
                            ('abandon_unsent_read', 'abandon'), ('abandon_unsent_nickname', 'abandon')):
        if hasattr(cls, name):
            wrap_after(name, operation)

    # Events. Each hook is evidence, not part of the system under test: if the tree has no such place, it is left out.
    try:
        from postriff_phase2 import hosted_worker
        worker_class = hosted_worker.PostgresWorker
        original_release = worker_class.release_discord_unsent

        @functools.wraps(original_release)
        def release(self, claimed, *args, **kwargs):
            result = original_release(self, claimed, *args, **kwargs)
            if result:
                emit_event('release', kwargs.get('reason', 'shutdown'), kwargs.get('retry_after_seconds'),
                           kwargs.get('rate_scope'), kwargs.get('rate_cause'))
            return result
        worker_class.release_discord_unsent = release
    except (ImportError, AttributeError):
        pass
    try:
        from postriff_phase2 import social_connectors
        provider_class = social_connectors.DiscordProvider
        installed = provider_class.__dict__.get('rate_coordinator_degraded')
        if installed is None:
            # A tree where the flag is a plain attribute (set for good by the first failed observation): make it a property that says so.
            def degraded_get(self):
                return self.__dict__.get('_cap_degraded', False)

            def degraded_set(self, value):
                was = self.__dict__.get('_cap_degraded', False)
                self.__dict__['_cap_degraded'] = bool(value)
                if value and not was:
                    frame = sys._getframe(1)
                    failed = getattr(last_failed, 'value', None)
                    emit_event('degraded', '%s:%d after %s' % (frame.f_code.co_name, frame.f_lineno, failed[0] if failed else 'no failed call'),
                               None, failed[1] if failed else None, failed[2] if failed else None)
            provider_class.rate_coordinator_degraded = property(degraded_get, degraded_set)
        elif isinstance(installed, property) and installed.fset is not None:
            # From 0cb19962 the flag is a property of the class: set for good by the OAuth service when the reviewed policy does not
            # parse, and for DiscordProvider.DEGRADED_SECONDS (45 s) by _coordinator_failed() when the coordinator could not record an
            # outcome. Both are logged as events; the second is the one a database under load meets.
            original_set = installed.fset

            def permanent_set(self, value):
                if value:
                    frame = sys._getframe(1)
                    emit_event('degraded', 'permanent, set at %s:%d' % (frame.f_code.co_name, frame.f_lineno), None, None, None)
                return original_set(self, value)
            provider_class.rate_coordinator_degraded = property(installed.fget, permanent_set, installed.fdel, installed.__doc__)
        timed = getattr(provider_class, '_coordinator_failed', None)
        if timed is not None:
            @functools.wraps(timed)
            def coordinator_failed(self, *args, **kwargs):
                frame = sys._getframe(1)
                failed = getattr(last_failed, 'value', None)
                emit_event('degraded', 'timed %s s, from %s:%d after %s' % (
                    getattr(self, 'DEGRADED_SECONDS', '?'), frame.f_code.co_name, frame.f_lineno, failed[0] if failed else 'no failed call'),
                    None, failed[1] if failed else None, failed[2] if failed else None)
                return timed(self, *args, **kwargs)
            provider_class._coordinator_failed = coordinator_failed
    except (ImportError, AttributeError):
        pass
    return handle


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        try:
            text = record.getMessage()
        except Exception:
            text = '<unformattable>'
        if len(self.lines) < 400:
            self.lines.append({'logger': record.name, 'level': record.levelname, 'at': record.created,
                               'message': text[:4000]})


def main(argv=None):
    spawned = float(os.environ.get('CAP_SPAWNED_AT') or time.time())
    child_started = time.time()
    parser = argparse.ArgumentParser(description='One cron invocation through the real WSGI entry.')
    parser.add_argument('--source-tree', required=True)
    parser.add_argument('--path', required=True)
    parser.add_argument('--env', required=True)
    parser.add_argument('--mock-port', type=int, required=True)
    parser.add_argument('--start-at', type=float, default=0.0, help='wall-clock time to serve the request')
    parser.add_argument('--out', required=True)
    parser.add_argument('--warm', action='store_true', help='build the runtime before the request (a warm instance)')
    parser.add_argument('--nice', type=int, default=0)
    parser.add_argument('--attempts', help='write the coordinator attempt log (one JSON array per line) to this file')
    args = parser.parse_args(argv)
    if args.nice:
        os.nice(args.nice)
    env = json.loads(open(args.env).read())
    for key in list(os.environ):
        if key.startswith('POSTRIFF_') or key in ('CRON_SECRET', 'VERCEL', 'VERCEL_ENV'):
            del os.environ[key]
    os.environ.update(env)
    fence_network()
    tree = os.path.abspath(args.source_tree)
    sys.path[:0] = [tree, os.path.join(tree, 'src')]
    capture = Capture()
    logging.getLogger().addHandler(capture)
    logging.getLogger().setLevel(logging.INFO)
    result = {'path': args.path, 'pid': os.getpid(), 'spawnedAt': spawned, 'childStartedAt': child_started,
              'scheduledAt': args.start_at, 'mode': 'warm' if args.warm else 'cold'}
    try:
        import api.index as entry
        counts = shim_discord_transport(args.mock_port, source_tag(args.path))
        if args.attempts:
            try:
                instrument_coordinator(args.attempts, source_tag(args.path))
            except Exception as error:  # the log is evidence, not part of the system under test: say so and carry on
                result['attemptLogError'] = '%s: %s' % (type(error).__name__, error)
        app = entry.app
        result['importedAt'] = time.time()
        if args.warm:
            app._runtime()
            result['warmedAt'] = time.time()
        usage = resource.getrusage(resource.RUSAGE_SELF)
        result['cpuBeforeRequest'] = round(usage.ru_utime + usage.ru_stime, 3)
        delay = args.start_at - time.time()
        if delay > 0:
            time.sleep(delay)
        status = {}

        def start_response(line, headers, exc_info=None):
            status['line'] = line
            status['headers'] = headers
            return lambda data: None
        environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': args.path, 'QUERY_STRING': '', 'SERVER_NAME': 'rafii.example.invalid',
                   'SERVER_PORT': '443', 'SERVER_PROTOCOL': 'HTTP/1.1', 'HTTP_HOST': 'rafii.example.invalid',
                   'HTTP_AUTHORIZATION': 'Bearer ' + env['CRON_SECRET'], 'HTTP_USER_AGENT': 'vercel-cron/1.0',
                   'HTTP_X_FORWARDED_PROTO': 'https', 'HTTP_X_FORWARDED_FOR': '127.0.0.1', 'REMOTE_ADDR': '127.0.0.1',
                   'wsgi.version': (1, 0), 'wsgi.url_scheme': 'https', 'wsgi.input': io.BytesIO(b''),
                   'wsgi.errors': sys.stderr, 'wsgi.multithread': False, 'wsgi.multiprocess': True,
                   'wsgi.run_once': True, 'CONTENT_LENGTH': '0'}
        result['handlerStartedAt'] = time.time()
        body = b''.join(app(environ, start_response))
        result['handlerEndedAt'] = time.time()
        result['status'] = int(status.get('line', '0 none').split()[0])
        try:
            result['body'] = json.loads(body)
        except ValueError:
            result['body'] = {'raw': body[:2000].decode('utf-8', 'replace')}
        result['discordRequests'] = counts['discord']
        result['misroutedByHarness'] = counts['misrouted']
        result['bookingStats'] = coordinator_totals()
        setup_error = getattr(app, 'setup_error', None)
        if setup_error is not None:
            result['setupError'] = type(setup_error).__name__ + ': ' + str(setup_error)[:500]
    except BaseException as error:  # recorded, never hidden: the parent counts every failed invocation
        result['exception'] = type(error).__name__ + ': ' + str(error)[:1000]
        result.setdefault('handlerEndedAt', time.time())
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result.update(cpuUser=round(usage.ru_utime, 3), cpuSystem=round(usage.ru_stime, 3), maxRssKb=usage.ru_maxrss,
                  blockedEgress=BLOCKED[:50], blockedEgressCount=len(BLOCKED), logs=capture.lines,
                  exitedAt=time.time())
    temporary = args.out + '.tmp'
    with open(temporary, 'w') as handle:
        json.dump(result, handle)
    os.replace(temporary, args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
