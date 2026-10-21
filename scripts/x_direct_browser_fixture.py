"""LOCAL ONLY: real Rafii HTTP/OAuth/SQL/worker, synthetic identity and X provider.

This launcher never connects to X, Supabase, billing or an LLM. It wraps the
existing disposable harness; it is not mounted by production entrypoints.
Use POSTRIFF_DEV_WEB_ORIGIN=http://127.0.0.1:<web-port> and --port/--pg-port.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import html
import io
import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import postriff_dev_hosted as harness
from postriff_phase2.social_connectors import XProvider
from postriff_phase2.x_direct_cost import PRICES, MEDIA_PRICE_KEYS, XCostController
from postriff_phase2.x_direct_service import XDirectService
from postriff_phase2.oauth import OAuthService
from test_x_direct_cost import policy
from test_x_media_service_pg import MediaWire

BASE = os.environ.get('POSTRIFF_DEV_WEB_ORIGIN', '')
parsed = urlsplit(BASE)
if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
        or parsed.path or parsed.query or parsed.fragment or parsed.username):
    raise SystemExit('Explicit local loopback web origin is required.')
FIXTURE_SECRET = secrets.token_urlsafe(24)
CONTEXT = {}


class SyntheticXWire(MediaWire):
    def __init__(self):
        super().__init__()
        self.consents, self.codes, self.tokens, self.refreshes = {}, {}, {}, {}
        self.auth_events = []
    def __call__(self, method, url, **kwargs):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname != 'api.x.com':
            raise AssertionError('Fixture denies unexpected provider destination')
        path = parts.path
        if path == '/2/oauth2/token':
            form = kwargs.get('form') or {}
            if form.get('grant_type') == 'authorization_code':
                consent = self.codes.pop(form.get('code'), None)
                verifier = form.get('code_verifier', '')
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                if not consent or not hmac.compare_digest(challenge, consent['challenge']):
                    return {'status': 400, 'body': {'error': 'invalid_grant'}}
                scopes = consent['scopes']
                self.auth_events.append({'event': 'pkce_exchange', 's256Verified': True, 'scopeCount': len(scopes)})
            else:
                scopes = self.refreshes.pop(form.get('refresh_token'), None)
                if not scopes: return {'status': 400, 'body': {'error': 'invalid_grant'}}
                self.auth_events.append({'event': 'refresh'})
            at, rt = 'synthetic-at-' + secrets.token_hex(12), 'synthetic-rt-' + secrets.token_hex(12)
            self.tokens[at], self.refreshes[rt] = scopes, scopes
            return {'status': 200, 'body': {'access_token': at, 'refresh_token': rt, 'expires_in': 7200, 'scope': ' '.join(scopes)}}
        if path == '/2/oauth2/revoke':
            value = (kwargs.get('form') or {}).get('token')
            self.tokens.pop(value, None); self.refreshes.pop(value, None)
            self.auth_events.append({'event': 'revoke'})
            return {'status': 200, 'body': {'revoked': True}}
        token = (kwargs.get('headers') or {}).get('Authorization', '').removeprefix('Bearer ')
        if token not in self.tokens:
            return {'status': 401, 'body': {'title': 'Synthetic token is not authorized'}}
        if path == '/2/users/me':
            self.auth_events.append({'event': 'identity_read'})
            return {'status': 200, 'body': {'data': {'id': '123', 'username': 'synthetic_x_customer', 'name': 'Synthetic X customer'}}}
        return super().__call__(method, url, **kwargs)


class SyntheticXProvider(XProvider):
    def authorize_url(self, redirect, state, challenge, scopes):
        # Exercise the real official URL builder, then substitute only consent's
        # origin. No real customer identity or actual X authorization is claimed.
        official = super().authorize_url(redirect, state, challenge, scopes)
        query = parse_qs(urlsplit(official).query)
        assert query['code_challenge_method'] == ['S256'] and query['state'] == [state]
        wire.consents[state] = {'challenge': challenge, 'scopes': list(scopes), 'createdAt': time.time()}
        return BASE + '/dev/x/consent?' + urlencode({'state': state})


wire = SyntheticXWire()
original_service = harness.HostedWorkspaceService
original_worker = harness.PostgresWorker
original_application = harness.HostedApplication


def service_factory(connection, verifier, assets, **kwargs):
    # Only this new disposable harness's connection is ever used.
    with connection() as db:
        host = db.info.host
        if host not in ('127.0.0.1', 'localhost') and not host.startswith('/tmp/'):
            raise RuntimeError('Synthetic fixture requires disposable local PostgreSQL')
        for name in ('131_x_direct_cost.sql', '132_x_direct_operations.sql', '133_x_cost_approval_grants.sql', '134_x_resource_evidence.sql', '135_x_oauth_provider_identifier.sql'):
            db.execute((ROOT / 'migrations/postriff' / name).read_text())
    provider = SyntheticXProvider('synthetic-x-browser', 'synthetic-not-real-secret', transport=wire)
    provider.public_connect_enabled = True
    provider.direct_management_enabled = True
    provider.publishing_release_enabled = True
    provider.daily_identity_limit = 100
    provider.x_access_evidence = {'entitlements': frozenset(('x_api_v2', 'self_thread_reply')),
        'publicCustomerVerified': True, 'expiresAt': time.time() + 7200, 'evidenceRef': 'synthetic:local-fixture-not-provider-acceptance'}
    kwargs['providers'] = {**kwargs['providers'], 'x': provider}
    service = original_service(connection, verifier, assets, **kwargs)
    prices = tuple((key, 17) for key in sorted(MEDIA_PRICE_KEYS))  # synthetic, NOT provider prices
    cost = XCostController(connection, policy(app_budget_micros=100_000_000, workspace_budget_micros=20_000_000,
        app_request_limit=1000, workspace_request_limit=500,
        allowed_price_keys=frozenset(PRICES) | MEDIA_PRICE_KEYS, media_prices=prices), 'synthetic-x-browser')
    cost.activate('synthetic:local-browser-only')
    service.x_direct = XDirectService(service, cost)
    CONTEXT['service'] = service
    # Seed one decoded test image through existing private-storage and command
    # paths when the actual signup verifier creates a workspace. The browser can
    # also upload more via the normal media endpoint.
    return service


def worker_factory(connection, **kwargs):
    kwargs['x_maintenance'] = CONTEXT['service'].x_direct
    worker = original_worker(connection, **kwargs)
    CONTEXT['worker'] = worker
    return worker


class FixtureApplication(original_application):
    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        method = environ.get('REQUEST_METHOD', 'GET')
        if path == '/dev/x/consent':
            query = {k: v[0] for k, v in parse_qs(environ.get('QUERY_STRING', '')).items()}
            if method == 'POST':
                length = int(environ.get('CONTENT_LENGTH') or 0)
                if not 0 <= length <= 4096: return self._json(start_response, 413, {'error': 'Fixture form too large'})
                query = {k: v[0] for k, v in parse_qs(environ['wsgi.input'].read(length).decode()).items()}
            state = query.get('state', ''); consent = wire.consents.get(state)
            if not consent or consent['createdAt'] < time.time() - 600:
                return self._json(start_response, 404, {'error': 'Synthetic consent expired'})
            if method == 'POST':
                result = {'state': state}
                if query.get('decision') == 'allow':
                    code = 'synthetic-code-' + secrets.token_hex(12); wire.codes[code] = wire.consents.pop(state)
                    result['code'] = code
                else: result['error'] = 'access_denied'
                target = BASE + '/api/oauth/x/callback?' + urlencode(result)
                start_response('302 Found', [('Location', target), ('Cache-Control', 'no-store')]); return [b'']
            safe = html.escape(state, quote=True)
            raw = (f'<!doctype html><html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1">'
                   f'<title>Synthetic X consent</title><body><h1>Synthetic X consent — no real X account</h1>'
                   f'<p>Local fixture. Real PKCE and database flow; provider identity and responses are synthetic.</p>'
                   f'<form method="post"><input type="hidden" name="state" value="{safe}">'
                   '<button name="decision" value="allow">Allow synthetic X account</button>'
                   '<button name="decision" value="deny">Deny synthetic X account</button></form></body></html>').encode()
            start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8'), ('Content-Length', str(len(raw)))]); return [raw]
        if path == '/api/oauth/x/callback' and method == 'GET':
            query = {k: v[0] for k, v in parse_qs(environ.get('QUERY_STRING', '')).items()}
            target = OAuthService.callback_redirect(BASE, 'x', query)
            start_response('302 Found', [('Location', target), ('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer')]); return [b'']
        if path.startswith('/api/x-fixture/'):
            if environ.get('HTTP_X_FIXTURE_SECRET') != FIXTURE_SECRET:
                return self._json(start_response, 403, {'error': 'Fixture only'})
            if path == '/api/x-fixture/tick' and method == 'POST':
                return self._json(start_response, 200, CONTEXT['service'].x_direct.dispatch_one())
            if path == '/api/x-fixture/stats' and method == 'GET':
                return self._json(start_response, 200, {'authEvents': wire.auth_events,
                    'calls': [{k: v for k, v in call.items() if k in ('method', 'path', 'bytes')} for call in wire.calls],
                    'posts': len(wire.posts), 'media': len(wire.media), 'realProviderCalls': 0})
        return super().__call__(environ, start_response)


# The generic harness owns /dev/*; intercept only our dedicated fixture prefix
# before it chooses a static file. Production code is never modified for this.
original_make_server = harness.make_server
def make_server(host, port, application, **kwargs):
    def router(environ, start_response):
        if environ.get('PATH_INFO') == '/dev/x/consent':
            return CONTEXT['app'](environ, start_response)
        return application(environ, start_response)
    return original_make_server(host, port, router, **kwargs)

original_init = FixtureApplication.__init__
def app_init(self, *args, **kwargs):
    original_init(self, *args, **kwargs); CONTEXT['app'] = self
FixtureApplication.__init__ = app_init

harness.HostedWorkspaceService = service_factory
harness.PostgresWorker = worker_factory
harness.HostedApplication = FixtureApplication
harness.make_server = make_server
if __name__ == '__main__':
    output = os.environ.get('RAFII_X_FIXTURE_CONTROL_FILE')
    if not output: raise SystemExit('Explicit local fixture control file required')
    path = Path(output); path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'x', encoding='utf8') as f:
        os.chmod(path, 0o600)
        json.dump({'secret': FIXTURE_SECRET, 'base': BASE, 'classification': 'synthetic-local-only'}, f)
    harness.main()
