"""Control-only WSGI boundary. No effectful customer/financial routes are mounted."""
import json
import logging
import uuid
from time import monotonic
from .deadlines import deadline, remaining
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from urllib.parse import urlsplit
from .auth import COOKIE, CAPABILITIES, ControlError
from .workspace import WorkspaceService


class ControlApplication:
    def __init__(self, boundary, queries=None):
        self.boundary, self.queries = boundary, queries
        self.workspace = WorkspaceService(queries.store) if queries and hasattr(queries,'store') else None

    def __call__(self, environ, start_response):
        request_id = str(uuid.uuid4())
        deadline_token = deadline.set(monotonic()+10)
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
                principal = self.boundary.authorize(token, capability, origin=origin, csrf=environ.get('HTTP_X_CSRF_TOKEN'), unsafe=method != 'GET', step_up=path == '/workspace/live/rename', request_id=request_id)
                if path == '/session':
                    data = {'assurance': 'aal2', 'capabilities': sorted(set(principal['operator']['capabilities']) & CAPABILITIES), 'csrfToken': principal['csrfToken']}
                elif path == '/session/logout':
                    self.boundary.logout(token)
                    headers.append(('Set-Cookie', f'{COOKIE}=; Secure; HttpOnly; Path=/; SameSite=Strict; Max-Age=0'))
                    data = {'loggedOut': True}
                elif path.startswith('/workspace/') and self.workspace:
                    data = self.workspace.dispatch(path, body, principal, request_id)
                elif self.queries:
                    if path == '/copilot/turns':
                        key = environ.get('HTTP_IDEMPOTENCY_KEY')
                        if key != body.get('requestId') or not key: raise ControlError('VALIDATION_FAILED', 400)
                    data = self.queries.dispatch(path, body, principal, request_id)
                else: raise ControlError('SOURCE_UNAVAILABLE', 503)
            if path in ('/metrics/query','/engineering/checks/query'): result = data
            elif path == '/copilot/turns':
                status = 202
                result = dict(requestId=body['requestId'], authorizationRequestId=request_id, jobId=data['runId'], state=data.get('state','blocked'), statusPath='/api/control/v2/copilot/runs/'+data['runId'])
            else:
                result = dict(requestId=request_id, environment=config.environment, asOf=datetime.now(timezone.utc).isoformat(),
                              dataState=data.pop('_dataState', 'measured'), receiptIds=data.pop('_receiptIds', []), data=data)
            remaining()
            json.dumps(result,allow_nan=False)
            if principal and not self.terminal_audit(capability,'succeeded',principal,request_id):
                raise ControlError('SOURCE_UNAVAILABLE',503)
        except ControlError as error:
            if principal:
                self.terminal_audit(capability,'denied',principal,request_id,error.code)
            status, result = error.status, {'requestId': request_id, 'code': error.code, 'message': error.code.replace('_', ' ').capitalize()}
        except (ValueError, TypeError, KeyError):
            if principal:
                self.terminal_audit(capability,'failed',principal,request_id,'SOURCE_UNAVAILABLE')
            status, result = (503 if principal else 400), {'requestId': request_id, 'code': 'SOURCE_UNAVAILABLE' if principal else 'VALIDATION_FAILED', 'message': 'Control request unavailable'}
        except Exception:
            # Never return upstream exceptions, DB errors, tokens or private bodies.
            if principal:
                self.terminal_audit(capability,'failed',principal,request_id,'SOURCE_UNAVAILABLE')
            status, result = 503, {'requestId': request_id, 'code': 'SOURCE_UNAVAILABLE', 'message': 'Control source unavailable'}
        except BaseException:
            if principal:self.terminal_audit(capability,'failed',principal,request_id,'SOURCE_UNAVAILABLE')
            raise
        finally:
            deadline.reset(deadline_token)
        start_response(f'{status} ' + {200: 'OK', 202: 'Accepted', 400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden', 404: 'Not Found', 409: 'Conflict', 429: 'Too Many Requests', 503: 'Unavailable'}.get(status, 'Error'), headers)
        return [json.dumps(result, allow_nan=False).encode()]

    def terminal_audit(self, action, result, principal, request_id, code=None):
        token=deadline.set(monotonic()+2)
        try:
            self.boundary._audit(action,result,principal['operator']['user_id'],principal['session']['id'],request_id,code)
            return True
        except Exception:
            logging.getLogger("rafii_control.audit").error(json.dumps({"event":"terminal_audit_unavailable","requestId":request_id,"action":action,"result":result,"code":"SOURCE_UNAVAILABLE"},sort_keys=True))
            return False
        finally:
            deadline.reset(token)

    @staticmethod
    def _capability(path, method):
        if method == 'GET':
            if path in ('/workspace/live','/workspace/demo'): return 'control.read'
            if path.startswith('/users'): return 'customers.read'
            if path.startswith('/workspaces'): return 'workspaces.read'
            if path.startswith('/engineering'): return 'engineering.read'
            if path.startswith('/copilot/runs/'): return 'copilot.use'
            if path == '/audit': return 'audit.read'
            if path in ('/session', '/overview', '/sources/health', '/dashboards', '/recommendations') or path.startswith('/metrics/receipts/'): return 'control.read'
        if method == 'POST':
            if path in ('/workspace/live/query','/workspace/demo/query'): return 'control.read'
            if path == '/workspace/demo/action': return 'control.read'
            if path == '/workspace/live/rename': return 'workspaces.test.rename'
            if path == '/engineering/checks/query': return 'engineering.read'
            if path == '/metrics/query': return 'metrics.query'
            if path == '/copilot/turns': return 'copilot.use'
            if path == '/session/logout': return 'control.read'
        raise ControlError('SCOPE_DENIED', 404)
