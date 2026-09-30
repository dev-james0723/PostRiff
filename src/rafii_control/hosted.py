"""Separate Control entrypoint; imports no consumer worker, executor, payment or provider runtime."""
import json
import os
import re
import ssl
import uuid
from psycopg.conninfo import conninfo_to_dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler
from postriff_phase2.hosted_identity import _NoAuthRedirect
from .auth import Boundary, Config, ControlError, supabase_identity
from .http import ControlApplication
from .intelligence import QueryService
from .store import PostgresStore, connection_factory


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


def create_app(values=None):
    values = values if values is not None else os.environ
    config = Config.from_environment(values)
    # Disabled deployments are safe to build without any identity/database credentials.
    if not config.enabled:
        return ControlApplication(Boundary(config, None, None))
    for prohibited in ('POSTRIFF_DATABASE_URL','SUPABASE_SERVICE_ROLE_KEY','OPENAI_API_KEY','STRIPE_SECRET_KEY'):
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
    return ControlApplication(boundary,QueryService(store))


app = create_app()
