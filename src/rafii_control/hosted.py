"""Control entrypoints; imports no consumer worker, executor, payment or provider runtime.

Two mounts share this module (``rafii_control.auth.Config.mount``):

* separate — the dedicated Vercel project (``api/control.py``) builds ``app`` eagerly at import so misconfiguration
  fails at cold start, exactly as before the embedded mount existed.
* embedded — the consumer API (``postriff_phase2.hosted_app``) delegates ``/api/control/v2/*`` to
  ``embedded_app()`` and its cron tick to ``founder_tick()``. Both are built lazily and never raise into the
  consumer process; a misconfigured Control answers 503 on its own prefix and leaves every consumer route alone.
"""
import json
import logging
import os
import re
import ssl
import uuid
from psycopg.conninfo import conninfo_to_dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler
from postriff_phase2.hosted_identity import _NoAuthRedirect
from .auth import Boundary, Config, ControlError, boolean, supabase_identity
from .http import ControlApplication, founder_module
from .intelligence import QueryService
from .store import PostgresStore, connection_factory

# Consumer/privileged variables the separate mount refuses to coexist with. The embedded mount shares a process
# with them by design and therefore skips this list entirely: nothing below ever reads these names.
PROHIBITED = ('POSTRIFF_DATABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'OPENAI_API_KEY', 'STRIPE_SECRET_KEY')


def admit_databases(session_dsn, reader_dsn, values, config):
    if config.environment == 'local': return
    ref = values.get('RAFII_CONTROL_PRODUCTION_PROJECT_REF' if config.environment == 'production' else 'RAFII_CONTROL_STAGING_PROJECT_REF')
    if not isinstance(ref,str) or not re.fullmatch('[a-z0-9-]{3,80}',ref) or values.get('RAFII_CONTROL_SUPABASE_URL') != f'https://{ref}.supabase.co':
        raise ValueError('Verified database and identity project binding required')
    if config.environment == 'staging' and ref == values.get('RAFII_CONTROL_PRODUCTION_PROJECT_REF'):
        raise ValueError('Staging cannot use production authority')
    try: identities = [conninfo_to_dict(dsn) for dsn in (session_dsn,reader_dsn)]
    except Exception: raise ValueError('Invalid restricted database configuration') from None
    allowed = {'host','port','dbname','user','password','sslmode','sslrootcert','connect_timeout','channel_binding'}
    for identity in identities:
        host, user = identity.get('host',''), identity.get('user','')
        direct = host == f'db.{ref}.supabase.co'
        pooler = re.fullmatch('[a-z0-9-]+\\.pooler\\.supabase\\.com',host) and user.endswith('.'+ref)
        if not set(identity) <= allowed or not (direct or pooler) or not user or identity.get('dbname') != 'postgres':
            raise ValueError('Restricted database project mismatch or redirect options')
        if identity.get('sslmode') != 'verify-full' or identity.get('port','5432') != '5432':
            raise ValueError('Verified TLS and session-mode database connection required')
    if identities[0]['user'] == identities[1]['user']:
        raise ValueError('Distinct restricted database logins required')


def create_app(values=None, runtime=None):
    """Build the Control WSGI app from ``values`` (defaults to the process environment).

    ``runtime`` is only meaningful for the embedded mount: a zero-argument callable returning the consumer
    ``HostedWorkspaceService`` (``HostedApplication._runtime``), which the founder agent and test-call routes
    reach through ``ControlApplication.runtime``. Control's own data access still uses only the restricted
    ``RAFII_CONTROL_*`` logins and identity project.
    """
    values = values if values is not None else os.environ
    config = Config.from_environment(values)
    # Disabled deployments are safe to build without any identity/database credentials.
    if not config.enabled:
        return ControlApplication(Boundary(config, None, None), runtime=runtime)
    if config.mount == 'separate':
        for prohibited in PROHIBITED:
            if values.get(prohibited): raise ValueError('Consumer/privileged credentials forbidden in Control')
    session_dsn, reader_dsn = values.get('RAFII_CONTROL_SESSION_DSN'), values.get('RAFII_CONTROL_READER_DSN')
    if not session_dsn or not reader_dsn or session_dsn == reader_dsn: raise ValueError('Separate restricted database logins required')
    admit_databases(session_dsn, reader_dsn, values, config)
    store = PostgresStore(connection_factory(session_dsn,'rafii_control_session',config.environment), connection_factory(reader_dsn,'rafii_control_reader',config.environment), config.environment)
    key = values.get('RAFII_CONTROL_SUPABASE_PUBLISHABLE_KEY')
    if not key or len(key)<20: raise ValueError('Control identity publishable key required')
    opener = build_opener(_NoAuthRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    def get_user(url, token):
        request = Request(url, headers={'Authorization':'Bearer '+token,'apikey':key,'Accept':'application/json'})
        try:
            with opener.open(request, timeout=5) as response:
                raw = response.read(65537)
                if len(raw)>65536: raise ControlError('SOURCE_UNAVAILABLE',503)
                if response.status != 200:
                    raise ControlError('RATE_LIMITED',429) if response.status == 429 else ControlError('AUTH_REQUIRED',401) if response.status in (401,403) else ControlError('SOURCE_UNAVAILABLE',503)
                body = json.loads(raw)
                if not isinstance(body,dict) or not isinstance(body.get('id'),str): raise ControlError('SOURCE_UNAVAILABLE',503)
                try: uuid.UUID(body['id'])
                except ValueError: raise ControlError('SOURCE_UNAVAILABLE',503) from None
                return {'status':200,'body':body}
        except HTTPError as error:
            status = error.code
            error.close()  # Do not read, retain or surface the provider body/headers.
            if status in (401,403): raise ControlError('AUTH_REQUIRED',401) from None
            if status == 429: raise ControlError('RATE_LIMITED',429) from None
            raise ControlError('SOURCE_UNAVAILABLE',503) from None
        except (URLError, TimeoutError, OSError, ValueError): raise ControlError('SOURCE_UNAVAILABLE',503)
    boundary = Boundary(config,store,supabase_identity(values.get('RAFII_CONTROL_SUPABASE_URL'),get_user))
    # Founder deployment flags (RAFII_FOUNDER_CALLS_ENABLED, RAFII_FOUNDER_OPS_WORKSPACE_ID, ...) are the only other
    # variables Control hands to its routes; no consumer credential is ever selected here.
    flags = {key: values[key] for key in values if key.startswith('RAFII_FOUNDER_')}
    return ControlApplication(boundary,QueryService(store),runtime=runtime,flags=flags)


def _closed_app(status, code, message):
    """A WSGI app that answers every request with one fixed Control error envelope (fail closed, content free)."""
    reason = {404: 'Not Found', 503: 'Unavailable'}[status]
    def respond(environ, start_response):
        start_response(f'{status} {reason}', [('Content-Type', 'application/json'), ('Cache-Control', 'private, no-store'), ('Vary', 'Cookie, Origin'),
                                              ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer')])
        return [json.dumps({'requestId': str(uuid.uuid4()), 'code': code, 'message': message}).encode()]
    return respond


def embedded_app(values=None, runtime=None):
    """Build Control for mounting inside the consumer API process. Never raises.

    Only ``RAFII_CONTROL_MOUNT=embedded`` activates Control here; any other mount keeps the prefix dark (404) so
    a consumer deployment cannot enable Control by copying the separate project's variables. A build failure
    (misconfiguration, missing pack, missing module) answers 503 SOURCE_UNAVAILABLE on every control request and
    logs only the exception class, never its text, so no DSN, key or path fragment can leak into logs.
    """
    values = values if values is not None else os.environ
    try:
        if values.get('RAFII_CONTROL_MOUNT', 'separate') != 'embedded':
            return _closed_app(404, 'SOURCE_UNAVAILABLE', 'Control is not mounted here')
        return create_app(values, runtime)
    except Exception as error:
        logging.getLogger('rafii_control.mount').error(json.dumps({'event': 'control_mount_unavailable', 'reason': type(error).__name__}, sort_keys=True))
        return _closed_app(503, 'SOURCE_UNAVAILABLE', 'Control source unavailable')


def founder_tick(service, values=None):
    """Founder cron step for the consumer worker tick (CONTRACTS §1). Never raises and never breaks the tick.

    Runs ``rafii_control.founder_cron.tick(service, values)`` only when Control is enabled and embedded; the module
    is imported lazily so an unfinished or failing founder slice reports ``{'status': 'unavailable'}`` instead of
    failing the consumer cron. The outcome must be JSON-serialisable because the cron response embeds it.
    """
    values = values if values is not None else os.environ
    try:
        if not boolean(values.get('RAFII_CONTROL_ENABLED')) or values.get('RAFII_CONTROL_MOUNT', 'separate') != 'embedded':
            return {'status': 'disabled'}
        outcome = founder_module('founder_cron').tick(service, values)
        json.dumps(outcome, allow_nan=False)
        return outcome
    except Exception:
        return {'status': 'unavailable'}


# The separate project builds eagerly so misconfiguration fails at cold start; the embedded mount builds lazily
# through embedded_app() on the first control request instead (api/control.py never ships in that deployment).
app = create_app() if os.environ.get('RAFII_CONTROL_MOUNT', 'separate') != 'embedded' else None
