"""Control-only WSGI boundary. No effectful customer/financial routes are mounted."""
import json
import uuid
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from urllib.parse import urlsplit
from .auth import COOKIE, CAPABILITIES, ControlError


class ControlApplication:
    def __init__(self, boundary, queries=None):
        self.boundary, self.queries = boundary, queries

    def __call__(self, environ, start_response):
        request_id = str(uuid.uuid4())
        headers = [('Content-Type', 'application/json'), ('Cache-Control', 'private, no-store'), ('Vary', 'Cookie, Origin'),
                   ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer')]
        status = 200
        principal, capability = None, None
        try:
            config = self.boundary.config
            if environ.get('HTTP_HOST') != urlsplit(config.origin).netloc: raise ControlError('SCOPE_DENIED', 404)
            self.boundary.gate()
            method, path = environ.get('REQUEST_METHOD', 'GET'), environ.get('PATH_INFO', '')
            prefix = '/api/control/v2'
            if not path.startswith(prefix + '/'): raise ControlError('SCOPE_DENIED', 404)
            path = path[len(prefix):]
            origin = environ.get('HTTP_ORIGIN')
            cookie = SimpleCookie()
            try: cookie.load(environ.get('HTTP_COOKIE', ''))
            except Exception: raise ControlError('AUTH_REQUIRED', 401)
            token = cookie[COOKIE].value if COOKIE in cookie else ''
            body = {}
            if method != 'GET':
                length = int(environ.get('CONTENT_LENGTH') or '0')
                if not 0 <= length <= 32768 or environ.get('CONTENT_TYPE', '').split(';')[0] != 'application/json': raise ControlError('VALIDATION_FAILED', 400)
                body = json.loads(environ['wsgi.input'].read(length) or b'{}')
                if not isinstance(body, dict): raise ControlError('VALIDATION_FAILED', 400)
            if path == '/session/exchange' and method == 'POST':
                if environ.get('HTTP_X_CONTROL_EXCHANGE') != '1' or origin != config.origin: raise ControlError('SCOPE_DENIED')
                upstream = environ.get('HTTP_AUTHORIZATION', '')
                if not upstream.startswith('Bearer '): raise ControlError('AUTH_REQUIRED', 401)
                token, data = self.boundary.exchange(upstream[7:], origin, request_id=request_id)
                headers.append(('Set-Cookie', f'{COOKIE}={token}; Secure; HttpOnly; Path=/; SameSite=Strict; Max-Age=28800'))
            else:
                try: capability = self._capability(path, method)
                except ControlError:
                    # Record prohibited attempts using a fixed action name, never the raw path.
                    try: self.boundary.authorize(token, 'prohibited', origin=origin, unsafe=method != 'GET', request_id=request_id)
                    except ControlError: pass
                    raise
                principal = self.boundary.authorize(token, capability, origin=origin, csrf=environ.get('HTTP_X_CSRF_TOKEN'), unsafe=method != 'GET', request_id=request_id)
                if path == '/session':
                    data = {'assurance': 'aal2', 'capabilities': sorted(set(principal['operator']['capabilities']) & CAPABILITIES), 'csrfToken': principal['csrfToken']}
                elif path == '/session/logout':
                    self.boundary.logout(token)
                    headers.append(('Set-Cookie', f'{COOKIE}=; Secure; HttpOnly; Path=/; SameSite=Strict; Max-Age=0'))
                    data = {'loggedOut': True}
                elif self.queries:
                    if path == '/copilot/turns':
                        key = environ.get('HTTP_IDEMPOTENCY_KEY')
                        if key != body.get('requestId') or not key: raise ControlError('VALIDATION_FAILED', 400)
                    data = self.queries.dispatch(path, body, principal, request_id)
                else: raise ControlError('SOURCE_UNAVAILABLE', 503)
            if path == '/metrics/query': result = data
            elif path == '/copilot/turns':
                status = 202
                result = dict(requestId=body['requestId'], jobId=data['runId'], state='blocked', statusPath='/api/control/v2/copilot/runs/'+data['runId'])
            else:
                result = dict(requestId=request_id, environment=config.environment, asOf=datetime.now(timezone.utc).isoformat(),
                              dataState=data.pop('_dataState', 'measured'), receiptIds=data.pop('_receiptIds', []), data=data)
        except ControlError as error:
            if principal:
                self.boundary._audit(capability, 'denied', principal['operator']['user_id'], principal['session']['id'], request_id)
            status, result = error.status, {'requestId': request_id, 'code': error.code, 'message': error.code.replace('_', ' ').capitalize()}
        except (ValueError, TypeError, KeyError):
            status, result = 400, {'requestId': request_id, 'code': 'VALIDATION_FAILED', 'message': 'Invalid control request'}
        except Exception:
            # Never return upstream exceptions, DB errors, tokens or private bodies.
            status, result = 503, {'requestId': request_id, 'code': 'SOURCE_UNAVAILABLE', 'message': 'Control source unavailable'}
        start_response(f'{status} ' + {200: 'OK', 202: 'Accepted', 400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden', 404: 'Not Found', 409: 'Conflict', 429: 'Too Many Requests', 503: 'Unavailable'}.get(status, 'Error'), headers)
        return [json.dumps(result, allow_nan=False).encode()]

    @staticmethod
    def _capability(path, method):
        if method == 'GET':
            if path.startswith('/users'): return 'customers.read'
            if path.startswith('/workspaces'): return 'workspaces.read'
            if path.startswith('/engineering'): return 'engineering.read'
            if path.startswith('/copilot/runs/'): return 'copilot.use'
            if path == '/audit': return 'audit.read'
            if path in ('/session', '/overview', '/sources/health', '/dashboards', '/recommendations') or path.startswith('/metrics/receipts/'): return 'control.read'
        if method == 'POST':
            if path == '/metrics/query': return 'metrics.query'
            if path == '/copilot/turns': return 'copilot.use'
            if path == '/session/logout': return 'control.read'
        raise ControlError('SCOPE_DENIED', 404)
