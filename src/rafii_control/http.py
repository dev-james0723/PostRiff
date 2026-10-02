"""Control-only WSGI boundary. No effectful customer/financial routes are mounted."""
import importlib
import json
import logging
import re
import uuid
from time import monotonic
from .deadlines import deadline, remaining
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit
from .auth import COOKIE, CAPABILITIES, ControlError
from .workspace import WorkspaceService

# Path identifiers accepted by Founder Admin v2 routes. Anything else is a prohibited route, never a lookup.
ID = '[A-Za-z0-9_-]{1,80}'
# Founder Admin v2 prefixes (CONTRACTS §3) served by lazily imported slice modules; '/overview' joins only with ?mode=.
FOUNDER_PREFIXES = ('/incidents', '/follow-ups', '/contact-policy', '/briefing-schedules', '/calls/', '/agent/', '/usage/')
# Founder Admin P1/P2 slices add routes here from their own modules (CONTRACTS §8) instead of editing the dispatch below:
# (method, path regex, capability, module, function, options). options: step_up (fresh MFA <=300 s), budget (BUDGETS purpose),
# demo_ok (Demo mode allowed; otherwise ?mode=demo is refused for writes). The handler is
# module.function(app, principal, request) with request = {method, path, body, query, match, mode, now, requestId, environ}.
EXTENSION_ROUTES = []


def register_route(method, pattern, capability, module, function, **options):
    """Register one founder route. The capability must exist in auth.CAPABILITIES; patterns are full-match regexes."""
    if method not in ('GET', 'POST', 'PUT', 'DELETE') or capability not in CAPABILITIES or set(options) - {'step_up', 'budget', 'demo_ok'}:
        raise ValueError('invalid founder route')
    compiled = re.compile(pattern)
    if any(route[0] == method and route[1].pattern == compiled.pattern for route in EXTENSION_ROUTES):
        raise ValueError('duplicate founder route ' + method + ' ' + pattern)
    EXTENSION_ROUTES.append((method, compiled, capability, module, function, dict(options)))


def extension_route(path, method):
    for route in EXTENSION_ROUTES:
        if route[0] == method and (match := route[1].fullmatch(path)): return route, match
    return None, None


STATUS = {200: 'OK', 201: 'Created', 202: 'Accepted', 400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden', 404: 'Not Found', 409: 'Conflict', 429: 'Too Many Requests', 503: 'Unavailable'}


def founder_module(name):
    """Import a founder slice lazily so a module another slice has not finished fails only its own routes."""
    try: return importlib.import_module('rafii_control.' + name)
    except ImportError: raise ControlError('SOURCE_UNAVAILABLE', 503) from None


class ControlApplication:
    def __init__(self, boundary, queries=None, runtime=None, flags=None):
        """``runtime``: embedded mount only, a zero-argument callable returning the consumer HostedWorkspaceService
        for the founder agent and test-call routes; ``None`` (separate mount) makes those routes SOURCE_UNAVAILABLE.
        ``flags``: the RAFII_FOUNDER_* deployment flags handed to founder_contact (never any other variable)."""
        self.boundary, self.queries, self.runtime, self.flags = boundary, queries, runtime, dict(flags or {})
        # Founder P1/P2 slices register their routes, metrics and cron stages at import (rafii_control.slices). A disabled
        # Control (every consumer deployment where it is dark) answers 404 before any route, so it never loads them.
        if getattr(getattr(boundary, 'config', None), 'enabled', False):
            from . import slices
            slices.load()
        self.workspace = WorkspaceService(queries.store) if queries and hasattr(queries,'store') else None
        self._founder_store = None

    @staticmethod
    def deadline_seconds(path):
        """The request's wall-clock budget. Ordinary reads keep 10 s. A founder agent turn runs the model inside the request
        (agent_runtime_v2.TURN_BUDGET_SECONDS = 240), so agent routes get 270 s, under the function's 300 s limit. The
        Overview composes sixteen receipted metrics in one call, so it gets 30 s. Each statement stays capped at 5 s."""
        tail = path[len('/api/control/v2'):] if path.startswith('/api/control/v2/') else path
        if tail.startswith('/agent/'): return 270
        if tail == '/overview': return 30
        return 10

    def __call__(self, environ, start_response):
        request_id = str(uuid.uuid4())
        deadline_token = deadline.set(monotonic()+self.deadline_seconds(environ.get('PATH_INFO', '')))
        headers = [('Content-Type', 'application/json'), ('Cache-Control', 'private, no-store'), ('Vary', 'Cookie, Origin'),
                   ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer')]
        status = 200
        principal, capability = None, None
        try:
            config = self.boundary.config
            if self.request_host(environ, config) not in {urlsplit(origin).netloc for origin in config.allowed_origins}: raise ControlError('SCOPE_DENIED', 404)
            self.boundary.gate()
            method, path = environ.get('REQUEST_METHOD', 'GET'), environ.get('PATH_INFO', '')
            prefix = '/api/control/v2'
            if not path.startswith(prefix + '/'): raise ControlError('SCOPE_DENIED', 404)
            path = path[len(prefix):]
            query = parse_qs(environ.get('QUERY_STRING', ''))
            origin = environ.get('HTTP_ORIGIN')
            cookie = SimpleCookie()
            try: cookie.load(environ.get('HTTP_COOKIE', ''))
            except Exception: raise ControlError('AUTH_REQUIRED', 401)
            token = cookie[COOKIE].value if COOKIE in cookie else ''
            body = {}
            if method != 'GET':
                length = int(environ.get('CONTENT_LENGTH') or '0')
                if not 0 <= length <= 32768: raise ControlError('VALIDATION_FAILED', 400)
                # Only a bodiless DELETE may omit the JSON content type; every other non-GET request must declare it.
                if length or method != 'DELETE':
                    if environ.get('CONTENT_TYPE', '').split(';')[0] != 'application/json': raise ControlError('VALIDATION_FAILED', 400)
                    body = json.loads(environ['wsgi.input'].read(length) or b'{}')
                    if not isinstance(body, dict): raise ControlError('VALIDATION_FAILED', 400)
            if path == '/session/exchange' and method == 'POST':
                if environ.get('HTTP_X_CONTROL_EXCHANGE') != '1' or origin not in config.allowed_origins: raise ControlError('SCOPE_DENIED')
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
                route, _ = extension_route(path, method)
                principal = self.boundary.authorize(token, capability, origin=origin, csrf=environ.get('HTTP_X_CSRF_TOKEN'), unsafe=method != 'GET', step_up=path == '/workspace/live/rename' or capability == 'control.settings' or bool(route and route[5].get('step_up')), ending_session=path == '/session/logout', ending_preview=self.preview_cleanup(path,body), request_id=request_id, purpose=(route[5].get('budget') if route else None) or self.budget_purpose(path, method))
                if path == '/session':
                    data = {'assurance': 'aal2', 'capabilities': sorted(set(principal['operator']['capabilities']) & CAPABILITIES), 'csrfToken': principal['csrfToken']}
                elif path == '/session/logout':
                    self.boundary.logout(token)
                    headers.append(('Set-Cookie', f'{COOKIE}=; Secure; HttpOnly; Path=/; SameSite=Strict; Max-Age=0'))
                    data = {'loggedOut': True}
                elif path.startswith('/workspace/') and self.workspace:
                    data = self.workspace.dispatch(path, body, principal, request_id)
                elif self.founder_route(path, query):
                    data = self.founder(path, method, body, principal, request_id, query, environ)
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
                if path == '/agent/turns': status = 201
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
            # Founder errors name a fixed blocker code (CONTRACTS §4, e.g. ops_workspace_not_configured); never free text.
            blocker = getattr(error, 'blocker', None)
            if isinstance(blocker, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,63}', blocker): result['blocker'] = blocker
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
        start_response(f'{status} ' + STATUS.get(status, 'Error'), headers)
        return [json.dumps(result, allow_nan=False).encode()]

    @staticmethod
    def request_host(environ, config):
        """The separate mount trusts only the socket Host. The embedded mount sits behind Vercel's proxy, where the
        browser-facing host arrives as X-Forwarded-Host (first value); it must still match an allowed origin."""
        if config.mount == 'embedded' and environ.get('HTTP_X_FORWARDED_HOST'):
            return environ['HTTP_X_FORWARDED_HOST'].split(',')[0].strip()
        return environ.get('HTTP_HOST')

    @staticmethod
    def budget_purpose(path, method):
        """Founder agent turns/cancels and test calls get their own per-minute buckets; everything else keeps the capability's."""
        if method == 'POST' and path.startswith('/agent/'): return 'founder.agent.turn'
        if method == 'POST' and path == '/calls/test': return 'founder.call.request'
        return None

    @staticmethod
    def founder_route(path, query):
        return path.startswith(FOUNDER_PREFIXES) or (path == '/overview' and 'mode' in query) or any(route[1].fullmatch(path) for route in EXTENSION_ROUTES)

    @staticmethod
    def query_mode(query):
        """Demo is a data mode selected explicitly by the client; it is never a fallback for Live."""
        mode = query.get('mode', ['live'])[0]
        if mode not in ('demo', 'live'): raise ControlError('VALIDATION_FAILED', 400)
        return mode

    @staticmethod
    def query_period(query):
        period = query.get('period', ['30d'])[0]
        if not re.fullmatch(r'[1-9][0-9]{0,2}d', period): raise ControlError('VALIDATION_FAILED', 400)
        return period

    @staticmethod
    def query_int(query, key, default, upper=1000):
        value = query.get(key, [None])[0]
        if value is None: return default
        if not value.isdigit() or not 1 <= int(value) <= upper: raise ControlError('VALIDATION_FAILED', 400)
        return int(value)

    def consumer(self):
        """The consumer HostedWorkspaceService (embedded mount only), for routes that run the founder agent."""
        if self.runtime is None: raise ControlError('SOURCE_UNAVAILABLE', 503)
        return self.runtime()

    def founder_store(self):
        """Founder tables (054/055) through the restricted session role: the contact/cron slice's store class over this
        app's PostgresStore, built once on first use (``founder_cron.PostgresFounderStore(store, environment)``)."""
        if self._founder_store is None:
            self._founder_store = founder_module('founder_cron').PostgresFounderStore(self.queries.store, self.boundary.config.environment)
        return self._founder_store

    def phone_calls(self, principal):
        """Live phone adapter for a founder test call, or None (which founder_contact answers 409 POLICY_DISABLED) unless the
        embedded consumer runtime, its phone product and the ops workspace flag all exist. Never raises."""
        try:
            ops, _source = founder_module('founder_ops').resolve(self.flags, getattr(self.queries, 'store', None), principal['operator']['user_id'])
        except ControlError:
            return None
        if self.runtime is None or not ops: return None
        try: phone = getattr(self.runtime(), 'phone', None)
        except Exception: return None
        return founder_module('founder_contact').PhoneCalls(phone, ops, principal['operator']['user_id']) if phone else None

    def demo_incidents(self, principal):
        """Demo incidents are part of the founder's own Demo dataset (founder_preview_scenarios); the live store is never a fallback."""
        data = self.queries.demo_data(principal)
        return dict(mode='demo', incidents=list(data.get('incidents', [])), _dataState='synthetic', _receiptIds=[data['receipt']['id']] if data.get('receipt') else [])

    def founder(self, path, method, body, principal, request_id, query, environ):
        """Founder Admin v2 routes (CONTRACTS §3). Capability, CSRF, step-up and budget were already enforced by
        ``authorize``; this only maps a route to its slice module, each imported lazily. Call shapes follow the landed
        slices: ``live_metrics.<fn>(principal, mode, ..., queries)``, founder record modules
        ``<fn>(fstore, principal, ..., *, now)`` with ``now`` in epoch seconds from the boundary clock, and
        ``founder_agent.<fn>(consumer_service, principal, ..., request_id)`` as CONTRACTS §4."""
        if not self.queries: raise ControlError('SOURCE_UNAVAILABLE', 503)
        queries, mode, now, operator = self.queries, self.query_mode(query), self.boundary.clock(), principal['operator']['user_id']
        route, match = extension_route(path, method)
        if route:
            if mode == 'demo' and method != 'GET' and not route[5].get('demo_ok'): raise ControlError('VALIDATION_FAILED', 400)
            handler = getattr(founder_module(route[3]), route[4], None)
            if handler is None: raise ControlError('SOURCE_UNAVAILABLE', 503)
            return handler(self, principal, dict(method=method, path=path, body=body, query=query, match=match.groups(), mode=mode, now=now, requestId=request_id, environ=environ))
        if path == '/overview': return founder_module('live_metrics').overview(principal, mode, self.query_period(query), queries, request_id=request_id)
        if path == '/usage/unknown': return founder_module('live_metrics').unknown_reservations(principal, mode, queries, limit=self.query_int(query, 'limit', 200))
        if path == '/incidents':
            if mode == 'demo': return self.demo_incidents(principal)
            return founder_module('founder_incidents').list_incidents(self.founder_store(), principal, limit=self.query_int(query, 'limit', 50, 200), include_resolved=query.get('includeResolved', ['1'])[0] != '0')
        if match := re.fullmatch(f'/incidents/({ID})/ack', path):
            if mode == 'demo': raise ControlError('VALIDATION_FAILED', 400)   # Demo acknowledgements are Demo workspace actions, never live writes
            return founder_module('founder_incidents').acknowledge(self.founder_store(), match[1], body.get('version'), operator, now=now, channel='web')
        if path == '/follow-ups' and method == 'GET': return founder_module('founder_follow_ups').list_follow_ups(self.founder_store(), principal, now=now)
        if path == '/follow-ups': return founder_module('founder_follow_ups').create(self.founder_store(), principal, body, now=now)
        if match := re.fullmatch(f'/follow-ups/({ID})', path): return founder_module('founder_follow_ups').update(self.founder_store(), principal, match[1], body, now=now)
        if path == '/contact-policy' and method == 'GET': return founder_module('founder_contact').get_policy(self.founder_store(), principal, now=now, flags=self.flags)
        if path == '/contact-policy': return founder_module('founder_contact').put_policy(self.founder_store(), principal, body, now=now)
        if path == '/calls/test': return founder_module('founder_contact').test_call(self.founder_store(), principal, body, now=now, flags=self.flags, calls=self.phone_calls(principal))
        if path == '/briefing-schedules' and method == 'GET': return founder_module('founder_schedules').list_schedules(self.founder_store(), principal, now=now)
        if path == '/briefing-schedules': return founder_module('founder_schedules').create(self.founder_store(), principal, body, now=now)
        if match := re.fullmatch(f'/briefing-schedules/({ID})', path): return founder_module('founder_schedules').delete(self.founder_store(), principal, match[1], now=now)
        if path == '/agent/turns':
            key = environ.get('HTTP_IDEMPOTENCY_KEY')
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{8,200}', key) or body.get('idempotencyKey', key) != key: raise ControlError('VALIDATION_FAILED', 400)
            body['idempotencyKey'] = key
            # control=self: the turn reuses this app's QueryService/WorkspaceService instead of opening a second control store.
            return founder_module('founder_agent').turn(self.consumer(), principal, body, request_id, control=self)
        if match := re.fullmatch(f'/agent/runs/({ID})', path): return founder_module('founder_agent').run(self.consumer(), principal, match[1], request_id, control=self)
        if match := re.fullmatch(f'/agent/runs/({ID})/cancel', path): return founder_module('founder_agent').cancel(self.consumer(), principal, match[1], request_id, control=self)
        if match := re.fullmatch(f'/agent/conversations/({ID})/state', path): return founder_module('founder_agent').conversation_state(self.consumer(), principal, match[1], request_id, control=self)
        raise ControlError('SCOPE_DENIED', 404)

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
    def preview_cleanup(path, body):
        """Only terminal Demo operations have a budget independent of dashboard reads.

        This changes throttling only. Auth, capability, CSRF and the strict reducer
        still validate the complete action before any persisted effect.
        """
        if path!='/workspace/demo/action' or body.get('action') not in ('founder_voice','founder_delivery'):
            return False
        value=body.get('value')
        if not isinstance(value,str) or len(value.encode())>4000: return False
        try: payload=json.loads(value)
        except (ValueError,TypeError): return False
        if not isinstance(payload,dict): return False
        if body['action']=='founder_voice': return payload.get('operation') in ('stop','interrupt','text')
        return payload.get('channel')=='call' and (payload.get('operation')=='cancel' or
               payload.get('operation')=='advance' and payload.get('outcome') in ('ending','completed','cancelled'))

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
            # Founder Admin v2 (CONTRACTS §3)
            if path in ('/incidents', '/follow-ups', '/contact-policy', '/briefing-schedules'): return 'control.read'
            if path == '/usage/unknown': return 'metrics.query'
            if re.fullmatch(f'/agent/runs/{ID}', path) or re.fullmatch(f'/agent/conversations/{ID}/state', path): return 'copilot.use'
        if method == 'POST':
            if path in ('/workspace/live/query','/workspace/demo/query'): return 'control.read'
            if path == '/workspace/demo/action': return 'control.read'
            if path == '/workspace/live/rename': return 'workspaces.test.rename'
            if path == '/engineering/checks/query': return 'engineering.read'
            if path == '/metrics/query': return 'metrics.query'
            if path == '/copilot/turns': return 'copilot.use'
            if path == '/session/logout': return 'control.read'
            # Founder Admin v2 (CONTRACTS §3)
            if re.fullmatch(f'/incidents/{ID}/ack', path): return 'incidents.ack'
            if path == '/follow-ups' or re.fullmatch(f'/follow-ups/{ID}', path): return 'followups.write'
            if path in ('/briefing-schedules', '/calls/test'): return 'control.settings'
            if path == '/agent/turns' or re.fullmatch(f'/agent/runs/{ID}/cancel', path): return 'copilot.use'
        if method == 'PUT' and path == '/contact-policy': return 'control.settings'
        if method == 'DELETE' and re.fullmatch(f'/briefing-schedules/{ID}', path): return 'control.settings'
        route, _ = extension_route(path, method)
        if route: return route[2]
        raise ControlError('SCOPE_DENIED', 404)
