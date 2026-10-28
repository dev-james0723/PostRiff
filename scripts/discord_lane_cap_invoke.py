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
import io
import json
import logging
import os
import resource
import socket
import sys
import time

BLOCKED = []


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
                headers['X-Cap-Call-At'] = repr(time.time())  # the last thing before the call: the wire time's lower bound
                rewritten = urllib.request.Request(local + path, data=request.data, headers=headers,
                                                   method=request.get_method())
                return opener.open(rewritten, timeout=timeout)
        return Opener()
    providers.build_opener = build_opener
    return counts


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
