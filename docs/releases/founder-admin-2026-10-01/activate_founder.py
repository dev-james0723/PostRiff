"""Founder Admin activation runner (PRD v2.0 P0-7 and D3; docs/releases/FOUNDER_ADMIN_RELEASE_2026-10-01.md).

Approved by James on 2026-10-01 (staging first, then production). Pinned and read-only by default. Like the 045 runner
it runs only inside a Vercel build of the PostRiff project, a CLI deployment whose build command ends in `exit 1` so it
is never served or aliased, against the database that build's own POSTRIFF_DATABASE_URL names. That URL never leaves
Vercel and is never printed. Targets:

    VERCEL_ENV=production -> Supabase project buoyhkbodnhzngaotoel (production)
    VERCEL_ENV=preview    -> Supabase project oxacvkhpfgytkepxcaqh (staging)

Modes (one per run; output is JSON lines prefixed FOUNDER-ACTIVATION, ids and booleans only):

    (none)       preflight: ledger, pinned checksums, dependencies, partial state. Writes nothing.
    --apply      one transaction: on staging only, the phone migrations production already runs (042, 043, 045) when
                 missing; then the Founder migrations 049 and 051-070 in order, each with its ledger row. The three roles
                 that take view ownership are created exactly as the migrations create them. Supabase's postgres role is
                 not a superuser, so PostgreSQL lets it hand a view or function to another role only when it can SET to
                 that role and the role may CREATE in the object's schema (049 does the latter for its own role; 053 and
                 later rely on a superuser), and the migrations' GRANTs on those objects after the hand-over only take
                 effect while it also inherits the owner's privileges (otherwise PostgreSQL warns and grants nothing).
                 Inside this transaction only, the runner's role holds SET and INHERIT membership in the three roles and
                 those roles hold CREATE on rafii_control; all of it is revoked before the checks run, and the checks
                 fail if any remains or if a Control view or function is left without its grants. Any failed check
                 rolls everything back.
    --repair     the same transaction around the Founder migrations once they are recorded as applied: re-runs them
                 (each is idempotent and CI applies them twice) without new ledger rows, so grants an earlier apply could
                 not make take effect. Used once on 2026-10-01 after the first apply held SET without INHERIT (approved
                 by James in manual-approval mode).
    --logins     create or rotate the three restricted logins from SCRAM verifiers passed as build environment
                 (FOUNDER_SESSION_SCRAM, FOUNDER_READER_SCRAM, FOUNDER_WATCHDOG_SCRAM); plaintext passwords never reach
                 Vercel's build. Each login may SET to exactly one NOLOGIN Control role and inherits nothing.
    --enroll-pending-founder
                 enrol only the independently verified FOUNDER_EXPECTED_USER_ID, supplied through secure build
                 configuration, when the one recent FOUNDER_REQUIRED refusal matches that exact identity. Refuses
                 missing/invalid pins, no candidate, multiple candidates, mismatches, another active founder, or
                 a revoked operator. Never derive the pin from the refusal row: Vercel team membership and a
                 successful Supabase sign-in do not establish founder ownership. MFA/session checks remain unchanged.
    --rehearsal  CI only: a loopback disposable database instead of a Vercel target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / 'migrations/postriff'
VERCEL_PROJECT = 'prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L'
PROJECTS = {'production': 'buoyhkbodnhzngaotoel', 'staging': 'oxacvkhpfgytkepxcaqh'}
PREFIX = 'FOUNDER-ACTIVATION'

# Already applied in production with these checksums; staging lacks them and 054 reads pr_phone_calls.direction (042).
PARITY = (
    ('042_phone_inbound.sql', '78a23c99f1b876426fa4aa5193da67f2e9941901baee89502004ae84f9131554'),
    ('043_phone_duration.sql', 'a798b67d66a3664cb9010c7ae15d38707d537fd494591b336805058e326a9a7a'),
    ('045_phone_caller_identity.sql', '1d672f5df62ae9209671d1b8505fe3729a6e6713e22a840b8db8edb0f76e1014'),
)
FOUNDER = (
    ('049_rafii_control_foundation.sql', 'b4cdabf7cc9b8f63d83fd7897a5214f147c3a08d0bdd6e235507f82b12a7f322'),
    ('051_rafii_control_read_workflow.sql', '67731fae74a5c0d4fcb1750318467ec8e2678efd5b7498aff3cb744340fea3e2'),
    ('052_rafii_control_investigations.sql', '27736fa262bcd341161b7dcdd7b41860d27fa73682f8d140d8da9543232544d5'),
    ('053_rafii_control_business_workspace.sql', 'a1c475adeadecaabb6c4a69ce5ae84ba5beec525d2458de11975ae6011e8d60e'),
    ('054_rafii_control_founder_views.sql', 'd848748bf0f1c8f198979ac367522e3d9665be503d5d6a22279f1a5f5c1033d3'),
    ('055_rafii_control_founder_contact.sql', '80155f9b67b774bc4a2ed7b9ef867c1d5fb1e2a64208ccfcc0e405d1c98983c1'),
    ('056_rafii_control_founder_capabilities.sql', 'e3410d4c920ec4c02da8e609bdec7a1fdfdbaeb89ceca489d7bb5a2a22646714'),
    ('057_founder_billing_events.sql', '92b2c3f1ebb860ce769a6f76d0a059a120cabdfc04a9723a1748d68ef63cdcd3'),
    ('058_founder_ai_usage.sql', '117d83f3c0a2e5ff9bc8223dd97e6be023cd89ee695ffad296aeb0419e4dd53e'),
    ('059_founder_product.sql', 'd3b733d493f946fd3b92643180209ae138bab7b93a8d8f6c801a4864fe3f1f77'),
    ('060_founder_reliability.sql', '9be2086bfc10433025f62663911580a6bc67b3c46c9ac385226657b28e3d6532'),
    ('062_founder_admin_actions.sql', '0826d0d1c5e6a90e64731e183f980e17babcd1c0bff3c22ec82e492b7d6ab7f7'),
    ('063_founder_revenue_views.sql', '89008cf43248e3947f43b567870d77845e7493916121c5bf6c495c38a5f99541'),
    ('064_founder_ai_views.sql', '856508ca28d016190ed7fcccb76d8a72bfb63abd4ecfaa8b6aeda94f7623b14d'),
    ('065_founder_product_views.sql', '6a5a58e3af954e0f986660e595995cbdbea08be15f3539ca6cd026ec8f6d2c7a'),
    ('066_founder_ops_views.sql', '98b48430f52d008672cc7b4e409b3305249364a33142df2d437f22fa223c41b7'),
    ('067_founder_comms_views.sql', '5fdb3ee0b46054567d57e64dd0e3577c51d1eb5a70f30420f624d774ee912514'),
    ('068_founder_actions_views.sql', '456f712ddf568d0c059d15b4701294a425794aaa065e4f785a245fa1a64163dc'),
    ('069_founder_ops_bootstrap.sql', '0e6cf0780bed232cee33871985897b8252714cc5821b1a8d8be7772e3120dfc3'),
    ('070_founder_ops_settings.sql', 'b874c083f6a906b4332a84bb723f1371ffc5f04f7a9a3337b935e7c83f9c4a2c'),
)
# The roles that take ownership of views and one function, created exactly as 049 and 053 create them.
OWNER_ROLES = (
    ('rafii_control_projection', 'NOLOGIN NOSUPERUSER BYPASSRLS'),
    ('rafii_control_business_projection', 'NOLOGIN NOSUPERUSER BYPASSRLS'),
    ('rafii_control_test_writer', 'NOLOGIN NOSUPERUSER BYPASSRLS'),
)
NOLOGIN_ROLES = ('rafii_control_session', 'rafii_control_reader', 'rafii_control_ingest', 'rafii_control_watchdog') + tuple(r for r, _ in OWNER_ROLES)
BYPASS_ROLES = {r for r, _ in OWNER_ROLES}
LOGINS = (
    ('session', 'rafii_control_session_login', 'rafii_control_session', 'FOUNDER_SESSION_SCRAM'),
    ('reader', 'rafii_control_reader_login', 'rafii_control_reader', 'FOUNDER_READER_SCRAM'),
    ('watchdog', 'rafii_control_watchdog_login', 'rafii_control_watchdog', 'FOUNDER_WATCHDOG_SCRAM'),
)
SCRAM = re.compile(r'SCRAM-SHA-256\$4096:[A-Za-z0-9+/]{22}==\$[A-Za-z0-9+/]{43}=:[A-Za-z0-9+/]{43}=')
CAPABILITIES = ('control.read', 'metrics.query', 'customers.read', 'workspaces.read', 'engineering.read', 'audit.read', 'copilot.use',
                'workspaces.test.rename', 'incidents.ack', 'followups.write', 'control.settings', 'founder.agent.turn',
                'founder.call.request', 'usage.reconcile', 'credits.adjust', 'accounts.block', 'refunds.prepare', 'founder.export')
# Public tables the Founder migrations create: each must keep row level security on and give the browser roles nothing.
NEW_PUBLIC = re.compile(r'create (?:unlogged )?table (?:if not exists )?public\.(\w+)', re.I)
DEPENDENCIES = (('pr_phone_calls', 'direction'), ('pr_phone_calls', 'duration_seconds'), ('pr_credit_subscription_grants', 'billing_reason'),
                ('pr_usage_ledger', 'reservation_id'), ('pr_notification_deliveries', 'failure_class'), ('pr_product_events', 'properties'))


class Refused(Exception):
    """A precondition or check failed; the transaction (if any) rolls back."""


def say(**data):
    print(PREFIX + ': ' + json.dumps(data, sort_keys=True, default=str), flush=True)


def body(path):
    # Same rule as scripts/postriff_migrate.py: drop whole unindented BEGIN/COMMIT lines; function bodies stay untouched.
    return re.sub(r'(?im)^(?:begin|commit);\s*$', '', path.read_text())


def checked(items):
    out = []
    for name, sha in items:
        path = MIGRATIONS / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise Refused(f'checksum mismatch for {name}')
        out.append((name, sha, path))
    return out


def target(args, environ):
    """(environment, dsn) after proving the build, the project and the database all match. Nothing here is printed."""
    dsn = environ.get('POSTRIFF_DATABASE_URL') or ''
    if not dsn:
        raise Refused('POSTRIFF_DATABASE_URL missing')
    params = conninfo_to_dict(dsn)
    if args.rehearsal:
        host = str(params.get('host', ''))
        if host not in ('127.0.0.1', 'localhost', '::1') and not host.startswith('/'):
            raise Refused('rehearsal needs a loopback disposable database')
        return 'local', dsn
    if environ.get('VERCEL_PROJECT_ID') != VERCEL_PROJECT:
        raise Refused('unexpected Vercel project')
    environment = {'production': 'production', 'preview': 'staging'}.get(environ.get('VERCEL_ENV', ''))
    if environment is None:
        raise Refused('runner needs a production or preview Vercel build')
    ref = PROJECTS[environment]
    host, user = str(params.get('host', '')), str(params.get('user', ''))
    direct = host == f'db.{ref}.supabase.co'
    pooled = bool(re.fullmatch(r'[a-z0-9-]+\.pooler\.supabase\.com', host)) and user.endswith('.' + ref)
    if not (direct or pooled):
        raise Refused(f'database is not the {environment} project')
    return environment, dsn


def ledger(cur):
    cur.execute("SELECT to_regclass('postriff_private.schema_migrations') IS NOT NULL")
    if not cur.fetchone()[0]:
        raise Refused('migration ledger missing')
    cur.execute('SELECT name, sha256 FROM postriff_private.schema_migrations')
    return dict(cur.fetchall())


def state(cur, environment):
    rows = ledger(cur)
    for name, sha, _ in checked(PARITY + FOUNDER):
        if name in rows and rows[name] != sha:
            raise Refused(f'applied checksum differs for {name}')
    applied = [name for name, _ in FOUNDER if name in rows]
    cur.execute("SELECT to_regnamespace('rafii_control') IS NOT NULL")
    schema = cur.fetchone()[0]
    missing = []
    for table, column in DEPENDENCIES:
        cur.execute('SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name=%s)',
                    ('public', table, column))
        if not cur.fetchone()[0]:
            missing.append(f'{table}.{column}')
    cur.execute('SELECT r.rolsuper, r.rolcreaterole, r.rolbypassrls FROM pg_roles r WHERE r.rolname=current_user')
    superuser, createrole, bypass = cur.fetchone()
    report = {'environment': environment, 'founder_applied': len(applied), 'founder_total': len(FOUNDER), 'control_schema': schema,
              'parity_missing': [name for name, _ in PARITY if name not in rows], 'dependencies_missing': missing,
              'runner_superuser': superuser, 'runner_createrole': createrole, 'runner_bypassrls': bypass}
    report['partial'] = bool((applied and len(applied) != len(FOUNDER)) or (schema and not applied))
    return report


def own_set_option(cur, role):
    """Whether the runner's role may still SET to, or inherits from, an owner role."""
    cur.execute('SELECT coalesce(bool_or(m.set_option OR m.inherit_option), false) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid '
                'WHERE r.rolname=%s AND m.member=(SELECT oid FROM pg_roles WHERE rolname=current_user)', (role,))
    return cur.fetchone()[0]


CONTROL_GRANTEES = ('rafii_control_session', 'rafii_control_reader', 'rafii_control_watchdog', 'rafii_control_ingest', 'rafii_control_test_writer')


def ungranted(cur):
    """Control views no Control role may read, and owner-role functions the session role may not execute."""
    cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rafii_control' AND c.relkind='v' "
                "AND NOT EXISTS (SELECT 1 FROM unnest(%s::text[]) g WHERE has_table_privilege(g, c.oid, 'SELECT')) ORDER BY 1", (list(CONTROL_GRANTEES),))
    views = [row[0] for row in cur.fetchall()]
    cur.execute("SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='rafii_control' "
                "AND pg_get_userbyid(p.proowner) = ANY(%s) AND NOT has_function_privilege('rafii_control_session', p.oid, 'EXECUTE') ORDER BY 1",
                ([r for r, _ in OWNER_ROLES],))
    functions = [row[0] for row in cur.fetchall()]
    # The browser roles must not execute Control's functions (049/053 revoke PUBLIC; they only bite with owner privileges).
    cur.execute("SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='rafii_control' "
                "AND (has_function_privilege('anon', p.oid, 'EXECUTE') OR has_function_privilege('authenticated', p.oid, 'EXECUTE')) ORDER BY 1")
    functions += ['public-execute:' + row[0] for row in cur.fetchall()]
    return views, functions


def verify(cur, environment):
    """Checks that must hold before commit; each failure raises Refused and rolls everything back."""
    rows = ledger(cur)
    for name, sha, _ in checked(FOUNDER):
        if rows.get(name) != sha:
            raise Refused(f'ledger row missing for {name}')
    if environment == 'staging':
        for name, sha in PARITY:
            if rows.get(name) != sha:
                raise Refused(f'parity ledger row missing for {name}')
    cur.execute('SELECT rolname, rolsuper, rolcanlogin, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication FROM pg_roles WHERE rolname = ANY(%s)',
                (list(NOLOGIN_ROLES),))
    roles = {row[0]: row[1:] for row in cur.fetchall()}
    for role in NOLOGIN_ROLES:
        if role not in roles:
            raise Refused(f'role missing: {role}')
        superuser, login, bypass, createrole, createdb, replication = roles[role]
        if superuser or login or createrole or createdb or replication or bypass != (role in BYPASS_ROLES):
            raise Refused(f'role attributes differ: {role}')
    for role, _ in OWNER_ROLES:
        if own_set_option(cur, role):
            raise Refused(f'runner still holds SET on {role}')
        cur.execute("SELECT has_schema_privilege(%s, 'rafii_control', 'CREATE')", (role,))
        if cur.fetchone()[0]:
            raise Refused(f'{role} can still create in rafii_control')
    views, functions = ungranted(cur)
    if views or functions:
        raise Refused('control objects without their grants: ' + ','.join(views + functions))
    # Control's own tables: row level security on and forced; the browser-facing roles have no schema usage.
    cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rafii_control' AND c.relkind='r' "
                'AND NOT (c.relrowsecurity AND c.relforcerowsecurity) ORDER BY 1')
    loose = [row[0] for row in cur.fetchall()]
    if loose:
        raise Refused('control tables without forced row level security: ' + ','.join(loose))
    cur.execute("SELECT bool_or(has_schema_privilege(r.rolname, 'rafii_control', 'USAGE')) FROM pg_roles r WHERE r.rolname IN ('anon','authenticated')")
    if cur.fetchone()[0]:
        raise Refused('browser roles can use the rafii_control schema')
    created = sorted({m.group(1) for _, _, path in checked(FOUNDER) for m in NEW_PUBLIC.finditer(path.read_text())})
    exposed = []
    for table in created:
        cur.execute('SELECT c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s', ('public', table))
        row = cur.fetchone()
        if row is None:
            raise Refused(f'public table missing: {table}')
        if not row[0]:
            exposed.append(table + ':rls_off')
        cur.execute("SELECT r.rolname FROM pg_roles r WHERE r.rolname IN ('anon','authenticated') AND has_table_privilege(r.rolname, %s, 'SELECT,INSERT,UPDATE,DELETE')",
                    ('public.' + table,))
        exposed.extend(f'{table}:{row[0]}' for row in cur.fetchall())
    if exposed:
        raise Refused('new public tables exposed: ' + ','.join(exposed))
    cur.execute("SELECT count(*) FILTER (WHERE c.relkind='r'), count(*) FILTER (WHERE c.relkind='v') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='rafii_control'")
    tables, views = cur.fetchone()
    return {'control_tables': tables, 'control_views': views, 'new_public_tables': created}


def owners_on(cur):
    for role, attributes in OWNER_ROLES:
        cur.execute(sql.SQL('DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname={name}) THEN CREATE ROLE {role} {attributes}; END IF; END $$')
                    .format(name=sql.Literal(role), role=sql.Identifier(role), attributes=sql.SQL(attributes)))
        cur.execute(sql.SQL('GRANT {role} TO CURRENT_USER WITH INHERIT TRUE, SET TRUE').format(role=sql.Identifier(role)))


def schema_create(cur, grant):
    for role, _ in OWNER_ROLES:
        statement = 'GRANT CREATE ON SCHEMA rafii_control TO {role}' if grant else 'REVOKE CREATE ON SCHEMA rafii_control FROM {role}'
        cur.execute(sql.SQL(statement).format(role=sql.Identifier(role)))


def owners_off(cur):
    schema_create(cur, False)
    for role, _ in OWNER_ROLES:
        cur.execute(sql.SQL('REVOKE INHERIT OPTION FOR {role} FROM CURRENT_USER').format(role=sql.Identifier(role)))
        cur.execute(sql.SQL('REVOKE SET OPTION FOR {role} FROM CURRENT_USER').format(role=sql.Identifier(role)))


def repair(con, environment):
    with con.transaction():
        cur = con.cursor()
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('postriff-migrations',0))")
        before = state(cur, environment)
        say(step='before', **before)
        if before['founder_applied'] != len(FOUNDER):
            raise Refused('repair needs every Founder migration recorded as applied')
        views, functions = ungranted(cur)
        say(step='ungranted_before', views=len(views), functions=len(functions))
        owners_on(cur)
        for name, _sha, path in checked(FOUNDER):
            cur.execute(body(path), prepare=False)
            say(step='reapplied', migration=name)
            if name.startswith('049_'):
                schema_create(cur, True)
        owners_off(cur)
        say(step='verified', **verify(cur, environment))
    say(step='committed', repaired=len(FOUNDER))


def apply(con, environment):
    with con.transaction():
        cur = con.cursor()
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('postriff-migrations',0))")
        before = state(cur, environment)
        say(step='before', **before)
        if before['founder_applied'] == len(FOUNDER):
            say(step='already_applied', **verify(cur, environment))
            return
        if before['partial']:
            raise Refused('partial Founder schema present; inspect before applying')
        if before['parity_missing']:
            if environment == 'production':
                raise Refused('production is missing migrations it already runs')
            for name, sha, path in checked(PARITY):
                if name in ledger(cur):
                    continue
                cur.execute(body(path), prepare=False)
                cur.execute('INSERT INTO postriff_private.schema_migrations(name, sha256) VALUES (%s, %s)', (name, sha))
                say(step='parity_applied', migration=name)
        if state(cur, environment)['dependencies_missing']:
            raise Refused('dependencies missing')
        owners_on(cur)
        for name, sha, path in checked(FOUNDER):
            cur.execute(body(path), prepare=False)
            cur.execute('INSERT INTO postriff_private.schema_migrations(name, sha256) VALUES (%s, %s)', (name, sha))
            say(step='applied', migration=name)
            if name.startswith('049_'):
                # The schema exists from here on; the owner roles may create in it until the end of this transaction.
                schema_create(cur, True)
        owners_off(cur)
        say(step='verified', **verify(cur, environment))
    say(step='committed', founder_migrations=len(FOUNDER))


def logins(con, environ):
    verifiers = {}
    for kind, _login, _granted, variable in LOGINS:
        value = environ.get(variable) or ''
        if not SCRAM.fullmatch(value):
            raise Refused(f'{variable} is not a SCRAM-SHA-256 verifier')
        verifiers[kind] = value
    with con.transaction():
        cur = con.cursor()
        for kind, login, granted, _variable in LOGINS:
            cur.execute(sql.SQL('DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname={name}) THEN '
                                'CREATE ROLE {login} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT CONNECTION LIMIT 20; END IF; END $$')
                        .format(name=sql.Literal(login), login=sql.Identifier(login)))
            # A non-superuser may only name the attributes it may change: SUPERUSER and REPLICATION stay as CREATE ROLE set
            # them (and the check below proves it); rotation touches login, inheritance, the limit and the password.
            cur.execute(sql.SQL('ALTER ROLE {login} WITH LOGIN NOINHERIT CONNECTION LIMIT 20 PASSWORD {verifier}')
                        .format(login=sql.Identifier(login), verifier=sql.Literal(verifiers[kind])))
            cur.execute(sql.SQL('GRANT {granted} TO {login} WITH INHERIT FALSE, SET TRUE').format(granted=sql.Identifier(granted), login=sql.Identifier(login)))
            cur.execute('SELECT r.rolcanlogin, r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication, '
                        '(SELECT array_agg(g.rolname ORDER BY g.rolname) FROM pg_auth_members m JOIN pg_roles g ON g.oid=m.roleid WHERE m.member=r.oid), '
                        '(SELECT bool_and(m.set_option AND NOT m.inherit_option) FROM pg_auth_members m WHERE m.member=r.oid) '
                        'FROM pg_roles r WHERE r.rolname=%s', (login,))
            can_login, privileged, memberships, set_only = cur.fetchone()
            if not can_login or privileged or memberships != [granted] or not set_only:
                raise Refused(f'login {login} is not restricted as required')
            say(step='login', login=login, member_of=granted, set_without_inherit=True)


def enroll(con, environment, environ=None):
    # A successful upstream sign-in (or Vercel team membership) does not identify the owner. Pin the independently
    # verified founder before reading refusal candidates; never derive this value from the candidate query itself.
    from uuid import UUID
    environ = os.environ if environ is None else environ
    try:
        expected = UUID((environ.get('FOUNDER_EXPECTED_USER_ID') or '').strip())
        if not expected.int:
            raise ValueError('nil identity')
    except (ValueError, TypeError, AttributeError):
        raise Refused('FOUNDER_EXPECTED_USER_ID must be an independently verified, non-nil user UUID') from None
    with con.transaction():
        cur = con.cursor()
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('rafii-founder-enrollment:' || %s,0))", (environment,))
        cur.execute("SELECT DISTINCT actor FROM rafii_control.admin_audit_log WHERE action='session.exchange' AND result='denied' "
                    "AND error_code='FOUNDER_REQUIRED' AND environment=%s AND actor IS NOT NULL AND occurred_at > now() - interval '20 minutes'",
                    (environment,))
        candidates = [str(row[0]) for row in cur.fetchall()]
        if len(candidates) != 1:
            raise Refused(f'expected exactly one refused founder sign-in in the last 20 minutes, found {len(candidates)}')
        user = candidates[0]
        if user != str(expected):
            raise Refused('the refused identity is not the independently verified founder')
        cur.execute("SELECT count(*) FROM rafii_control.platform_operators WHERE environment=%s AND status='active' AND user_id<>%s", (environment, user))
        if cur.fetchone()[0]:
            raise Refused('another active founder exists in this environment')
        cur.execute('SELECT EXISTS(SELECT 1 FROM auth.users WHERE id=%s)', (user,))
        if not cur.fetchone()[0]:
            raise Refused('the refused identity is not a user of this project')
        cur.execute('SELECT status FROM rafii_control.platform_operators WHERE user_id=%s AND environment=%s FOR UPDATE', (user, environment))
        existing = cur.fetchone()
        if existing is not None and existing[0] != 'active':
            raise Refused('founder access was revoked; enrollment does not reactivate it')
        cur.execute("INSERT INTO rafii_control.platform_operators(user_id, environment, role, status, capabilities) VALUES (%s, %s, 'founder', 'active', %s) "
                    "ON CONFLICT (user_id, environment) DO UPDATE SET capabilities=excluded.capabilities",
                    (user, environment, list(CAPABILITIES)))
        cur.execute("SELECT count(*) FROM rafii_control.platform_operators WHERE environment=%s AND status='active'", (environment,))
        say(step='enrolled', environment=environment, active_founders=cur.fetchone()[0], capabilities=len(CAPABILITIES))


def main(argv=None, environ=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--logins', action='store_true')
    mode.add_argument('--enroll-pending-founder', action='store_true')
    mode.add_argument('--repair', action='store_true')
    parser.add_argument('--rehearsal', action='store_true')
    args = parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    try:
        environment, dsn = target(args, environ)
        say(step='target', environment=environment, mode='apply' if args.apply else 'repair' if args.repair else 'logins' if args.logins else 'enroll' if args.enroll_pending_founder else 'preflight')
        with psycopg.connect(dsn, prepare_threshold=None, connect_timeout=15, application_name='founder-activation') as con:
            if args.apply:
                apply(con, environment)
            elif args.repair:
                repair(con, environment)
            elif args.logins:
                logins(con, environ)
            elif args.enroll_pending_founder:
                enroll(con, environment, environ)
            else:
                with con.transaction():
                    con.execute('SET TRANSACTION READ ONLY')
                    say(step='preflight', **state(con.cursor(), environment))
        return 0
    except Refused as error:
        say(step='refused', reason=str(error))
        return 2
    except psycopg.Error as error:
        # The class and SQLSTATE only: a server message can quote values.
        say(step='database_error', error=type(error).__name__, sqlstate=getattr(error, 'sqlstate', None))
        return 3


if __name__ == '__main__':
    sys.exit(main())
