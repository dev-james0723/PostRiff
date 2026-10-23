"""scripts/impact_compare.py: normalisation, verdicts, input formats, privacy, and a real two-build fixture.

The synthetic part serves two copies of a small app from this process (one per "build") and checks that volatile
differences are ignored while a real difference is flagged (negative controls). The real part materialises the hosted
API of the live commit and of the candidate from git objects (`git archive`, read-only), serves each on 127.0.0.1 with
the same offline configuration (fake credentials, no database, Production's Discord and worker variables), and pins
which public and unauthenticated answers differ. Set IMPACT_LIVE_REV / IMPACT_RC_REV to compare other revisions.
"""
import base64
import contextlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import impact_compare  # noqa: E402

LIVE_REV = os.environ.get('IMPACT_LIVE_REV', 'c5fc1fd10350f3142ec6f34b2c373139e85abb39')
RC_REV = os.environ.get('IMPACT_RC_REV', 'HEAD')

PAGE = '''<!DOCTYPE html><html lang="en"><head><title>Rafii</title>
<meta name="description" content="Publish with approval">
<meta name="sentry-trace" content="{trace}"><link rel="canonical" href="https://rafii.io/">
<script nonce="{nonce}" src="/_next/static/chunks/main-{hash}.js?dpl={dpl}"></script>
<link rel="stylesheet" href="/_next/static/css/{hash}.css"></head>
<body><main><h1>{heading}</h1><p>Built {when} from {sha}. Request {uuid}.</p>
<p>Read the <a href="/privacy">privacy notice</a> before you connect.</p>{extra}</main>
<script>self.__next_f.push([1,"{{\\"b\\":\\"{build}\\"}}"])</script></body></html>'''


def page(build, **change):
    values = {'trace': build * 4, 'nonce': build * 12, 'hash': (build * 16)[:16], 'dpl': 'dpl_' + build * 12,
              'heading': 'Approve every post', 'when': '2026-10-2%sT12:00:00Z' % (len(build) % 9),
              'sha': (build * 40)[:40], 'uuid': '%s-1111-4111-8111-111111111111' % (build * 8)[:8],
              'build': build * 10, 'extra': ''}
    values.update(change)
    return PAGE.format(**values)


class App:
    """One build of a tiny site: a page, a privacy page, a JSON API, an image and a refused route."""

    def __init__(self, build, *, page_change=None, privacy_extra='', headers_drop=(), status_change=None,
                 cookie='rafii_session', cookie_flags='Path=/; HttpOnly; Secure; SameSite=Lax', json_value='ok',
                 image=b'\x89PNG\r\n\x1a\nfixed-bytes'):
        self.build, self.page_change, self.privacy_extra = build, page_change or {}, privacy_extra
        self.headers_drop, self.status_change, self.cookie, self.cookie_flags = headers_drop, status_change or {}, cookie, cookie_flags
        self.json_value, self.image = json_value, image

    def __call__(self, environ, start_response):
        path = environ['PATH_INFO']
        common = [('Date', time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime())), ('X-Request-ID', os.urandom(16).hex()),
                  ('X-Vercel-Id', 'iad1::' + self.build), ('X-Frame-Options', 'DENY'), ('X-Content-Type-Options', 'nosniff'),
                  ('Content-Security-Policy', "script-src 'self' 'nonce-%s'" % (self.build * 12)),
                  ('ETag', '"%s"' % self.build)]
        if path == '/':
            common = [(k, v) for k, v in common if k not in self.headers_drop]
        status = self.status_change.get(path)
        if path == '/':
            body, kind = page(self.build, **self.page_change).encode(), 'text/html; charset=utf-8'
            common.append(('Set-Cookie', '%s=cookie-secret-%s; %s' % (self.cookie, self.build, self.cookie_flags)))
        elif path == '/privacy':
            body, kind = page(self.build, heading='Privacy', extra=self.privacy_extra).encode(), 'text/html; charset=utf-8'
        elif path == '/api/health':
            body = json.dumps({'status': self.json_value, 'sourceRevision': (self.build * 40)[:40],
                               'at': '2026-10-23T0%s:00:00Z' % (len(self.build) % 9)}).encode()
            kind = 'application/json'
        elif path == '/icon':
            body, kind = self.image, 'image/png'
        else:
            body, kind, status = json.dumps({'error': 'Sign in.', 'requestId': os.urandom(16).hex()}).encode(), 'application/json', status or 401
        start_response('%d X' % (status or 200), [('Content-Type', kind), ('Cache-Control', 'no-store')] + common)
        return [body]


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@contextlib.contextmanager
def served(app):
    server = make_server('127.0.0.1', 0, app, handler_class=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:%d' % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


ROUTES = '''GET /            kind=page
GET /privacy     kind=page expect=(?i)discord
GET /api/health  kind=api
GET /icon        kind=asset
GET /api/me      kind=shape
'''


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.routes_file = os.path.join(self.tmp, 'routes.txt')
        Path(self.routes_file).write_text(ROUTES)
        self.routes = impact_compare.parse_routes(self.routes_file)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def capture(self, app, name):
        out = os.path.join(self.tmp, name)
        with served(app) as base, contextlib.redirect_stdout(io.StringIO()):
            impact_compare.capture(self.routes, base, out, {'Authorization': 'Bearer never-stored-0000', 'X-Note': 'kept-out'}, 10)
        return out

    def verdicts(self, a, b):
        return {r['route']: r['verdict'] for r in impact_compare.compare(self.routes, a, b)}

    def test_volatile_differences_are_ignored(self):
        a, b = self.capture(App('aaaa'), 'a'), self.capture(App('bbbb'), 'b')
        verdicts = self.verdicts(a, b)
        self.assertEqual(verdicts['GET /'], 'SAME', 'nonce, build id, asset hash, dpl id, time, sha, uuid, trace, cookie value')
        self.assertEqual(verdicts['GET /privacy'], 'SAME')
        self.assertEqual(verdicts['GET /api/health'], 'SAME')
        self.assertEqual(verdicts['GET /icon'], 'SAME')
        self.assertEqual(verdicts['GET /api/me'], 'SAME', 'request ids in error bodies are volatile')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(impact_compare.main(['compare', '--routes', self.routes_file, '--a', a, '--b', b]), 0)

    def test_negative_controls_flag_real_differences(self):
        base = self.capture(App('aaaa'), 'base')
        cases = {
            'visible text': (App('bbbb', page_change={'heading': 'Approve most posts'}), 'GET /'),
            'security header removed': (App('bbbb', headers_drop=('X-Frame-Options',)), 'GET /'),
            'csp changed': (App('bbbb', headers_drop=('Content-Security-Policy',)), 'GET /'),
            'status': (App('bbbb', status_change={'/api/me': 200}), 'GET /api/me'),
            'new cookie name': (App('bbbb', cookie='rafii_tracker'), 'GET /'),
            'cookie flag dropped': (App('bbbb', cookie_flags='Path=/; Secure; SameSite=Lax'), 'GET /'),
            'json value': (App('bbbb', json_value='degraded'), 'GET /api/health'),
            'binary bytes': (App('bbbb', image=b'\x89PNG\r\n\x1a\nother-bytes'), 'GET /icon'),
            'link target': (App('bbbb', page_change={'extra': '<p><a href="/terms">Terms</a></p>'}), 'GET /'),
        }
        for name, (app, route) in cases.items():
            with self.subTest(name):
                other = self.capture(app, name.replace(' ', '-'))
                verdicts = self.verdicts(base, other)
                self.assertEqual(verdicts[route], 'DIFF')
                self.assertEqual([r for r, v in verdicts.items() if v != 'SAME' and r != route], [],
                                 'only the changed route may differ')
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(impact_compare.main(['compare', '--routes', self.routes_file, '--a', base, '--b', other]), 1)

    def test_expected_change_passes_only_when_every_change_matches(self):
        base = self.capture(App('aaaa'), 'base')
        discord = '<h3>Discord</h3><p>Rafii posts to a Discord channel only what you approve. See the ' \
                  '<a href="https://discord.com/terms">Discord Terms</a>.</p>'
        intended = self.capture(App('bbbb', privacy_extra=discord), 'intended')
        self.assertEqual(self.verdicts(base, intended)['GET /privacy'], 'EXPECTED')
        broader = self.capture(App('bbbb', privacy_extra=discord + '<p>We may share data with partners.</p>'), 'broader')
        self.assertEqual(self.verdicts(base, broader)['GET /privacy'], 'DIFF', 'a non-Discord sentence is not covered')

    def test_saved_formats_missing_and_unreadable(self):
        a, b = os.path.join(self.tmp, 'fa'), os.path.join(self.tmp, 'fb')
        os.makedirs(a)
        os.makedirs(b)
        route = next(r for r in self.routes if r['path'] == '/api/health')
        body = json.dumps({'status': 'ok'})
        Path(a, route['slug'] + '.json').write_text(json.dumps({'status': 200, 'headers': {'Content-Type': 'application/json',
                                                                                           'Cache-Control': 'no-store'}, 'body': body}))
        raw = ('HTTP/1.1 301 Moved\r\nLocation: /api/health\r\n\r\nHTTP/2 200\r\ncontent-type: application/json\r\n'
               'cache-control: no-store\r\ndate: Fri, 23 Oct 2026 04:00:00 GMT\r\n\r\n' + body).encode()
        Path(b, route['slug'] + '.http').write_bytes(raw)
        icon = next(r for r in self.routes if r['path'] == '/icon')
        Path(a, icon['slug'] + '.json').write_text(json.dumps({'status': 200, 'headers': [['content-type', 'image/png']],
                                                               'bodyBase64': base64.b64encode(b'png-bytes').decode()}))
        Path(b, icon['slug'] + '.headers').write_bytes(b'HTTP/2 200\r\ncontent-type: image/png\r\n\r\n')
        Path(b, icon['slug'] + '.body').write_bytes(b'png-bytes')
        privacy = next(r for r in self.routes if r['path'] == '/privacy')
        Path(a, privacy['slug'] + '.http').write_bytes(b'not an http response')
        verdicts = self.verdicts(a, b)
        self.assertEqual(verdicts['GET /api/health'], 'SAME', 'json file versus curl -i output with a redirect hop')
        self.assertEqual(verdicts['GET /icon'], 'SAME', 'base64 json versus a headers/body pair')
        self.assertEqual(verdicts['GET /'], 'MISSING')
        self.assertEqual(verdicts['GET /privacy'], 'UNREADABLE')

    def test_capture_never_stores_secrets(self):
        out = self.capture(App('aaaa'), 'a')
        text = ''.join(Path(out, name).read_text() for name in os.listdir(out))
        self.assertNotIn('never-stored-0000', text, 'request headers are not written')
        self.assertNotIn('cookie-secret-', text, 'cookie values are redacted')
        self.assertIn('rafii_session=<redacted>', text)
        self.assertNotIn('kept-out', text)

    def test_route_file_rejects_writes_and_unknown_options(self):
        bad = os.path.join(self.tmp, 'bad.txt')
        for line in ('POST /api/discord/interactions', 'GET /x kind=wild', 'GET relative'):
            with self.subTest(line):
                Path(bad).write_text(line + '\n')
                with self.assertRaises(SystemExit):
                    impact_compare.parse_routes(bad)

    def test_repository_route_list_parses(self):
        routes = impact_compare.parse_routes(str(ROOT / 'docs' / 'impact-routes.txt'))
        self.assertGreaterEqual(len(routes), 50)
        self.assertTrue(all(r['method'] in ('GET', 'HEAD') for r in routes))
        self.assertIn('/api/workspaces/00000000-0000-4000-8000-000000000000/discord/identities/x/guilds',
                      [r['path'] for r in routes])


# --- the real hosted API of both builds, offline ----------------------------------------------------------------------

def _rev(rev):
    done = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--verify', rev + '^{commit}'], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


SERVE = r'''
import os, sys
from wsgiref.simple_server import make_server, WSGIRequestHandler
sys.path.insert(0, os.path.join(sys.argv[1], 'src'))
from postriff_phase2.hosted_app import HostedApplication
class Quiet(WSGIRequestHandler):
    def log_message(self, *a): pass
app = HostedApplication()
def https(environ, start_response):
    environ['wsgi.url_scheme'] = 'https'
    return app(environ, start_response)
server = make_server('127.0.0.1', 0, https, handler_class=Quiet)
print(server.server_address[1], flush=True)
server.serve_forever()
'''


def offline_environment(policy):
    """Fake, offline values only: the database port is closed and the Supabase host is never contacted without a token."""
    return {'PATH': '/usr/bin:/bin', 'HOME': tempfile.gettempdir(), 'PYTHONDONTWRITEBYTECODE': '1',
            'POSTRIFF_DATABASE_URL': 'postgresql://impact:impact@127.0.0.1:1/impact?connect_timeout=1',
            'POSTRIFF_SUPABASE_URL': 'https://impactfixture.supabase.co',
            'POSTRIFF_SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_' + 'x' * 24,
            'POSTRIFF_SUPABASE_SECRET_KEY': 'sb_secret_' + 'y' * 24,
            'POSTRIFF_CREDENTIAL_KEY': base64.urlsafe_b64encode(b'k' * 32).decode(),
            'POSTRIFF_PUBLIC_BASE_URL': 'https://app.impact.invalid', 'CRON_SECRET': 'c' * 32, 'VERCEL_ENV': 'production',
            'POSTRIFF_OAUTH_DISCORD_CLIENT_ID': '123456789012345678',
            'POSTRIFF_OAUTH_DISCORD_CLIENT_SECRET': 'synthetic-discord-client-secret-0001',
            'POSTRIFF_DISCORD_BOT_TOKEN': 'synthetic-discord-bot-token-000000000001',
            # The seven variables Production carries since 2026-10-23 (values as approved; the policy is generated).
            'POSTRIFF_DISCORD_AUTHORIZATION_V2_ENABLED': 'true', 'POSTRIFF_DISCORD_CONNECTIONS_V2_ENABLED': 'true',
            'POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED': 'true', 'POSTRIFF_DISCORD_WORKER_V1_ENABLED': 'true',
            'POSTRIFF_DISCORD_RATE_POLICY': policy, 'POSTRIFF_WORKER_MAX_JOBS': '25', 'POSTRIFF_WORKER_MAX_SECONDS': '40'}


@unittest.skipUnless(_rev(LIVE_REV) and _rev(RC_REV), 'both revisions must be present in this clone')
class RealBuilds(unittest.TestCase):
    """Pins every difference a stranger without a session can see on the hosted API between live and the candidate."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.trees, cls.servers, cls.bases = {}, [], {}
        policy = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'discord_rate_policy.py'), 'generate'],
                                capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
        for name, rev in (('live', LIVE_REV), ('rc', RC_REV)):
            tree = os.path.join(cls.tmp, name)
            os.makedirs(tree)
            archive = subprocess.run(['git', '-C', str(ROOT), 'archive', _rev(rev), 'src', 'api'], capture_output=True, check=True)
            subprocess.run(['tar', '-x', '-C', tree], input=archive.stdout, check=True)
            process = subprocess.Popen([sys.executable, '-c', SERVE, tree], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       env=offline_environment(policy), text=True)
            cls.servers.append(process)
            port = process.stdout.readline().strip()
            if not port.isdigit():
                raise RuntimeError('the %s API did not start' % name)
            cls.bases[name] = 'http://127.0.0.1:' + port
        routes = os.path.join(cls.tmp, 'routes.txt')
        lines = [line for line in (ROOT / 'docs' / 'impact-routes.txt').read_text().splitlines() if 'kind=api' in line or 'kind=shape' in line]
        Path(routes).write_text('\n'.join(lines) + '\n')
        cls.routes = impact_compare.parse_routes(routes)
        with contextlib.redirect_stdout(io.StringIO()):
            for name in ('live', 'rc'):
                impact_compare.capture(cls.routes, cls.bases[name], os.path.join(cls.tmp, 'cap-' + name), {}, 20)
        cls.results = {r['route']: r for r in impact_compare.compare(cls.routes, os.path.join(cls.tmp, 'cap-live'), os.path.join(cls.tmp, 'cap-rc'))}

    @classmethod
    def tearDownClass(cls):
        for process in cls.servers:
            process.terminate()
            process.wait(timeout=10)
        shutil.rmtree(cls.tmp)

    def test_unauthenticated_shapes_are_refused_alike_including_new_discord_routes(self):
        shapes = [r for r in self.routes if r['kind'] == 'shape' and r['path'] != '/api/discord/interactions']
        for route in shapes:
            with self.subTest(route['path']):
                result = self.results['GET ' + route['path']]
                self.assertEqual(result['verdict'], 'SAME', result['findings'])
                self.assertIn(result['status'][0], (401, 403, 404), result['status'])

    def test_public_api_differs_only_where_intended(self):
        expected = {'GET /api/privacy/notice': 'EXPECTED'}
        for route, result in self.results.items():
            if route.startswith('GET /api/discord/interactions') or not route.startswith('GET /api/') or '/workspaces' in route or route in ('GET /api/me', 'GET /api/cron/worker'):
                continue
            with self.subTest(route):
                self.assertEqual(result['verdict'], expected.get(route, 'SAME'), result['findings'] + result['textChanges'][:5])

    def test_the_new_interactions_route_answers_get_before_authentication(self):
        result = self.results['GET /api/discord/interactions']
        self.assertEqual(result['verdict'], 'DIFF')
        self.assertEqual(result['status'][1], 404, 'POST-only in the candidate; a GET is refused before the bearer check')
        self.assertNotEqual(result['status'][0], 404)


if __name__ == '__main__':
    unittest.main()
