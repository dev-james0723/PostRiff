"""Founder Admin browser harness (CONTRACTS §8.G): embedded Control inside the local dev harness.

Disposable loopback PostgreSQL only, refused on Vercel. Identity is synthetic: three opaque tokens map to fixed
fictional users (two founder operators, one non-founder) and every one of them is still checked by the real
Boundary (operator row, AAL2, TOTP freshness, cookie, CSRF, capabilities, budgets, content-free audit). Control
reads through the same restricted roles it uses when hosted (SET ROLE rafii_control_session / rafii_control_reader).
Nothing here talks to Supabase, a model provider, a phone provider or a mail service.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOUNDER = '00000000-0000-4000-8000-00000000f001'
MOBILE_FOUNDER = '00000000-0000-4000-8000-00000000f002'
NON_FOUNDER = '00000000-0000-4000-8000-00000000f0ff'
TOKENS = {'synthetic-founder-aal2': FOUNDER, 'synthetic-founder-mobile-aal2': MOBILE_FOUNDER, 'synthetic-non-founder-aal2': NON_FOUNDER}


def founder_migrations(root=ROOT):
    """049, 051–053, then every founder migration from 054 on in number order (the PG harness's rule)."""
    base = root / 'migrations/postriff'
    files = [base / name for name in ('049_rafii_control_foundation.sql', '051_rafii_control_read_workflow.sql',
                                      '052_rafii_control_investigations.sql', '053_rafii_control_business_workspace.sql')]
    files += [path for path in sorted(base.glob('0[5-9][0-9]_*.sql')) if int(path.name[:3]) >= 54]
    return files


def attach(app, service, dsn, pg_bin, web_origins):
    """Mount Control on `app` (a HostedApplication) with synthetic founder identities; returns the ops workspace id."""
    if os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV'):
        raise RuntimeError('The founder browser fixture runs on the local harness only')
    if not dsn.startswith('host=127.0.0.1 port='):
        raise RuntimeError('The founder browser fixture needs the disposable loopback database')
    import psycopg
    from rafii_control.auth import CAPABILITIES, Boundary, Config, ControlError, VerifiedIdentity
    from rafii_control.http import ControlApplication
    from rafii_control.intelligence import QueryService
    from rafii_control.store import PostgresStore, connection_factory

    for path in founder_migrations():
        subprocess.run([str(Path(pg_bin) / 'psql'), dsn, '-v', 'ON_ERROR_STOP=1', '-q', '-f', str(path)], check=True, stdout=subprocess.DEVNULL)
    with psycopg.connect(dsn, autocommit=True) as owner:
        # Supabase's actual auth source includes email. Keep the disposable
        # schema compatible so explicit support reveal exercises the real SQL.
        owner.execute('ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS email text')
        for user in TOKENS.values():
            owner.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING', (user,))
            owner.execute('INSERT INTO public.pr_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING', (user,))
        for user in (FOUNDER, MOBILE_FOUNDER):
            owner.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s) "
                          "ON CONFLICT(user_id,environment) DO UPDATE SET status='active',capabilities=excluded.capabilities", (user, sorted(CAPABILITIES)))
    # Preserve a customer workspace and provision separate internal tenants through
    # the actual Ops state machine. Fixture identities remain local and synthetic.
    service.bootstrap('dev:' + FOUNDER, 'studio')
    values = {'RAFII_CONTROL_ENABLED': '1', 'RAFII_CONTROL_MOUNT': 'embedded', 'RAFII_CONTROL_ENVIRONMENT': 'local',
              # Synthetic QA model only; these are not production owner approvals.
              'RAFII_FOUNDER_AI_REQUEST_MAX_USD_MICRO': '1000000',
              'RAFII_FOUNDER_AI_DAY_MAX_USD_MICRO': '100000000',
              'RAFII_FOUNDER_AI_TASK_MAX_USD_MICRO': '100000000',
              'RAFII_FOUNDER_BUDGET_APPROVAL_REF': 'SYNTHETIC-NO-PROVIDER',
              # Two distinct strings for the two logins the cron's control_store expects; locally both SET ROLE from the owner.
              'RAFII_CONTROL_SESSION_DSN': dsn + ' application_name=rafii-control-session',
              'RAFII_CONTROL_READER_DSN': dsn + ' application_name=rafii-control-reader'}
    os.environ.update(values)
    store = PostgresStore(connection_factory(dsn, 'rafii_control_session', 'local'), connection_factory(dsn, 'rafii_control_reader', 'local'), 'local')

    def verify(token):
        user = TOKENS.get(token)
        if not user:
            raise ControlError('AUTH_REQUIRED', 401)
        return VerifiedIdentity(user, 'aal2', 'synthetic-founder-session-' + user[-4:], time.time())

    config = Config(True, 'local', web_origins[0], 'embedded', tuple(dict.fromkeys(web_origins)))
    flags = {key: value for key, value in values.items() if key.startswith('RAFII_FOUNDER_')}
    app.control_app = ControlApplication(Boundary(config, store, verify), QueryService(store), runtime=app._runtime, flags=flags)
    from rafii_control.founder_ops import create_ops
    ops = None
    for user in (FOUNDER, MOBILE_FOUNDER):
        created = create_ops(app.control_app, {'operator': {'user_id': user}, 'session': {'environment': 'local'}}, {'mode': 'live'})
        if user == FOUNDER:
            ops = created['workspaceId']
    return ops
