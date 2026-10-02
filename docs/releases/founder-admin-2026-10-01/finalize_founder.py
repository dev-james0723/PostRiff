"""Finish the owner-approved Founder activation using the original target and safety checks.

Read-only by default. Runs in the same non-serving, deliberately failed Vercel build as activate_founder.py.
--evidence applies ONLY the separately pinned 071 migration, atomically with its checksum ledger row.
--logins provisions/rotates the three existing restricted logins and the separate CI-ingest login atomically;
only SCRAM verifiers are accepted. No password, privileged DSN, customer content or email is printed.
The original twenty migration pins and the founder-enrollment/MFA boundary are not modified.
"""
from __future__ import annotations

import argparse
import os
import sys
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

import activate_founder as a

EVIDENCE = (('071_founder_engineering_evidence.sql', '05b5acdf89f167d702fd44caa7ed5c4c6f755c278766a4055ea4e2d30a068720'),)
INGEST_LOGIN = 'rafii_engineering_ingest'
SERVING_ROLES = ('rafii_control_session', 'rafii_control_reader', 'rafii_control_watchdog', 'rafii_control_ingest')


def verify_evidence(cur):
    name, sha, _ = a.checked(EVIDENCE)[0]
    if a.ledger(cur).get(name) != sha:
        raise a.Refused('migration 071 ledger checksum missing or different')
    for table in ('engineering_evidence', 'github_check_snapshots'):
        relation = 'rafii_control.' + table
        cur.execute('SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=%s::regclass', (relation,))
        if cur.fetchone() != (True,):
            raise a.Refused('CI evidence forced RLS missing')
        for role in ('anon', 'authenticated', 'rafii_control_session', 'rafii_control_reader'):
            cur.execute("SELECT has_table_privilege(%s,%s,'INSERT,UPDATE,DELETE,TRUNCATE')", (role, relation))
            if cur.fetchone()[0]:
                raise a.Refused('unexpected CI evidence writer')
        cur.execute("SELECT has_table_privilege('rafii_control_ingest',%s,'INSERT'), has_table_privilege('rafii_control_ingest',%s,'UPDATE,DELETE,TRUNCATE')", (relation, relation))
        if cur.fetchone() != (True, False):
            raise a.Refused('CI ingest table privileges differ')
    cur.execute("SELECT attname FROM pg_attribute WHERE attrelid='rafii_control.engineering_evidence'::regclass AND attnum>0 AND NOT attisdropped "
                "AND has_column_privilege('rafii_control_ingest',attrelid,attnum,'UPDATE')")
    if {row[0] for row in cur.fetchall()} != {'state', 'conclusion', 'failure_class', 'attested', 'observed_at'}:
        raise a.Refused('CI ingest update-column boundary differs')
    cur.execute("SELECT count(*) FROM pg_policies WHERE schemaname='rafii_control' AND policyname IN ('rc_github_ci_insert','control_ingest_insert','control_ingest_update')")
    if cur.fetchone()[0] != 3:
        raise a.Refused('CI evidence policies missing')
    return True


def apply_evidence(con, environment):
    with con.transaction():
        cur = con.cursor()
        cur.execute("SET LOCAL lock_timeout='5s'")
        cur.execute("SET LOCAL statement_timeout='60s'")
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('postriff-migrations',0))")
        a.verify(cur, environment)
        name, sha, path = a.checked(EVIDENCE)[0]
        previous = a.ledger(cur).get(name)
        if previous is not None and previous != sha:
            raise a.Refused('migration 071 checksum drift; refusing adoption')
        if previous is None:
            cur.execute(a.body(path), prepare=False)
            cur.execute('INSERT INTO postriff_private.schema_migrations(name,sha256) VALUES(%s,%s)', (name, sha))
        verify_evidence(cur)
        a.verify(cur, environment)
    return previous is None


def provision_ingest(con, verifier):
    if not isinstance(verifier, str) or not a.SCRAM.fullmatch(verifier):
        raise a.Refused('FOUNDER_INGEST_SCRAM must be a SCRAM-SHA-256 verifier')
    with con.transaction():
        cur = con.cursor()
        cur.execute("DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='rafii_engineering_ingest') THEN "
                    "CREATE ROLE rafii_engineering_ingest LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 5; END IF; END $$")
        cur.execute('SELECT rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication FROM pg_roles WHERE rolname=%s', (INGEST_LOGIN,))
        if cur.fetchone()[0]:
            raise a.Refused('existing ingest login is privileged; refusing to repurpose it')
        cur.execute('SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid WHERE m.member=%s::regrole', (INGEST_LOGIN,))
        if {row[0] for row in cur.fetchall()} - {'rafii_control_ingest'}:
            raise a.Refused('existing ingest login has unrelated memberships')
        cur.execute(sql.SQL('ALTER ROLE rafii_engineering_ingest LOGIN NOINHERIT CONNECTION LIMIT 5 PASSWORD {}').format(sql.Literal(verifier)))
        cur.execute('GRANT rafii_control_ingest TO rafii_engineering_ingest WITH INHERIT FALSE, SET TRUE')
        cur.execute('SELECT r.rolname,m.inherit_option,m.set_option FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid WHERE m.member=%s::regrole', (INGEST_LOGIN,))
        if cur.fetchall() != [('rafii_control_ingest', False, True)]:
            raise a.Refused('ingest login is not an exact SET-only member')


def probe(con, environment, dsn, environ):
    with con.transaction():
        con.execute('SET TRANSACTION READ ONLY')
        cur = con.cursor()
        result = a.verify(cur, environment)
        evidence = a.ledger(cur).get(EVIDENCE[0][0])
        result['evidence_071_verified'] = verify_evidence(cur) if evidence is not None else False
        cur.execute("SELECT c.relname, array(SELECT g FROM unnest(%s::text[]) g WHERE has_table_privilege(g,c.oid,'SELECT')) "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rafii_control' AND c.relkind='v' ORDER BY 1", (list(SERVING_ROLES),))
        views = cur.fetchall()
        reads = 0
        for view, roles in views:
            if not roles:
                raise a.Refused('a Control view has no serving reader')
            for role in roles:
                cur.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                cur.execute("SELECT set_config('rafii_control.environment',%s,true)", (environment,))
                cur.execute(sql.SQL('SELECT * FROM rafii_control.{} LIMIT 0').format(sql.Identifier(view)))
                cur.execute('RESET ROLE')
                reads += 1
        result['restricted_view_read_checks'] = reads
        params = conninfo_to_dict(dsn)
        result['database_host'] = params.get('host')
        result['session_port'] = 5432
        # The approved PRD identifies James's UUID in this existing owner-managed setting. It is independent of
        # the rejected-sign-in audit candidates. Return only the one verified UUID, never emails or auth contents.
        ids = [item.strip() for item in environ.get('RAFII_AI_UNLIMITED_USER_IDS', '').split(',') if item.strip()]
        result['configured_founder_id_count'] = len(ids)
        if len(ids) == 1:
            try:
                expected = UUID(ids[0])
            except ValueError:
                raise a.Refused('configured founder identity is not a UUID') from None
            cur.execute('SELECT EXISTS(SELECT 1 FROM auth.users WHERE id=%s)', (expected,))
            if not cur.fetchone()[0]:
                raise a.Refused('configured founder identity does not exist in this project')
            cur.execute("SELECT count(*) FROM auth.mfa_factors WHERE user_id=%s AND status='verified'", (expected,))
            result.update(founder_user_id=str(expected), verified_mfa_factors=cur.fetchone()[0])
        return result


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--evidence', dest='mode', action='store_const', const='evidence')
    modes.add_argument('--logins', dest='mode', action='store_const', const='logins')
    parser.set_defaults(mode='probe')
    parser.add_argument('--rehearsal', action='store_true')
    return parser.parse_args(argv)


def main(argv=None, environ=None):
    args = arguments(argv)
    environ = os.environ if environ is None else environ
    try:
        environment, dsn = a.target(args, environ)
        a.say(step='finalizer_target', environment=environment, mode=args.mode)
        with psycopg.connect(dsn, autocommit=True, prepare_threshold=None, connect_timeout=15, application_name='founder-finalization') as con:
            if args.mode == 'evidence':
                applied = apply_evidence(con, environment)
                a.say(step='evidence_committed', applied=applied, migration=EVIDENCE[0][0])
            elif args.mode == 'logins':
                with con.transaction():
                    a.logins(con, environ)
                    provision_ingest(con, environ.get('FOUNDER_INGEST_SCRAM'))
                a.say(step='restricted_logins_committed', count=4)
            else:
                a.say(step='finalizer_probe', environment=environment, **probe(con, environment, dsn, environ))
        return 0
    except a.Refused as error:
        a.say(step='refused', reason=str(error))
        return 2
    except psycopg.Error as error:
        a.say(step='database_error', error=type(error).__name__, sqlstate=error.sqlstate)
        return 3


if __name__ == '__main__':
    sys.exit(main())
