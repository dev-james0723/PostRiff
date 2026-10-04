"""LOCAL TEST ONLY: selected loopback PostgreSQL target; no I/O on import.

Contract for parent/Socrates/Dalton fixtures:
    target = selected_target()  # POSTRIFF_TEST_PG_PORT, default55438, 1024..65535
    DSN = target.dsn()          # fixed127.0.0.1/postgres, implicit local OS user
    target.validate_dsn(raw)   # exact selected port and exact known DB names

POSTRIFF_TEST_PG_PORT is authoritative: a DSN never selects or overrides it.
POSTRIFF_TEST_DSN, when present, must match the canonical postgres target.
URI/credentials/user/service/options/host redirects are forbidden, including
libpq connection environment overrides (presence, even empty, is rejected).
POSTRIFF_PG_PORT is a legacy compatibility assertion only, never a selector.
No application DATABASE_URL is read. No common PG environment variable is set.
Dedicated TREND_*_TEST_DSN inputs also assert this same selected postgres target.
Nested admission guards with historical dedicated targets may set
validate_fixture_dsns=False: the runner DSN and environment are still checked,
and each caller must retain its original dedicated alias/host/database guard.
Runner entry points always use the default strict alias validation.
Role, grant-policy, schema, lease, and business assertions belong to the caller.
New parent fixtures should use this helper before any connection or psql call;
they must not add database names without reviewing the exact allowlist below.
"""
from dataclasses import dataclass
import os
import re
import socket
from typing import Mapping

DEFAULT_PORT = 55438
HOST = '127.0.0.1'
DATABASES = frozenset({
    'postgres', 'migration_candidate', 'migration_restore', 'migration_fresh',
    'pricing_catalog_v2_fresh', 'pricing_catalog_v2_upgraded',
    'pricing_catalog_v2_old_packs', 'trend_restore',
})
# Do not silently sanitize these: refusal retains the existing admission gates.
FIXTURE_DSN_KEYS = frozenset({
    'TREND_TEST_DSN', 'TREND_PIPELINE_TEST_DSN', 'TREND_ADVANCED_TEST_DSN',
    'TREND_PLANNER_TEST_DSN', 'TREND_SERVICE_TEST_DSN', 'TREND_ENRICHMENT_TEST_DSN',
    'TREND_NOTIFICATIONS_TEST_DSN', 'TREND_EXPOSURE_TEST_DSN',
    'TREND_GENERATION_TEST_DSN', 'TREND_LAB_TEST_DSN',
    'TREND_INTERPRETATION_TEST_DSN', 'TREND_WHITESPACE_TEST_DSN',
})
LIBPQ_OVERRIDES = frozenset({
    'PGHOST', 'PGHOSTADDR', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD',
    'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS', 'PGSYSCONFDIR',
    # PG17 libpq-envars: every documented connection parameter default,
    # including deprecated requiressl and service configuration directories.
    'PGSSLNEGOTIATION', 'PGREQUIREAUTH', 'PGCHANNELBINDING', 'PGAPPNAME',
    'PGSSLMODE', 'PGREQUIRESSL', 'PGSSLCOMPRESSION', 'PGSSLCERT', 'PGSSLKEY',
    'PGSSLCERTMODE', 'PGSSLROOTCERT', 'PGSSLCRL', 'PGSSLCRLDIR', 'PGSSLSNI',
    'PGREQUIREPEER', 'PGSSLMINPROTOCOLVERSION', 'PGSSLMAXPROTOCOLVERSION',
    'PGGSSENCMODE', 'PGKRBSRVNAME', 'PGGSSLIB', 'PGGSSDELEGATION',
    'PGCONNECT_TIMEOUT', 'PGCLIENTENCODING', 'PGTARGETSESSIONATTRS', 'PGLOADBALANCEHOSTS',
})
PSQL_OVERRIDES = frozenset({'PSQLRC'})


def bounded_port(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,4}', value):
        raise ValueError('POSTRIFF_TEST_PG_PORT must be a decimal integer in1024..65535')
    port = int(value)
    if not 1024 <= port <= 65535:
        raise ValueError('POSTRIFF_TEST_PG_PORT must be in1024..65535')
    return port


@dataclass(frozen=True)
class LocalPGTarget:
    port: int

    def __post_init__(self):
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ValueError('invalid local test PostgreSQL port')

    def dsn(self, dbname: str = 'postgres') -> str:
        if dbname not in DATABASES:
            raise ValueError('only exact known disposable fixture databases are allowed')
        return f'host={HOST} port={self.port} dbname={dbname}'

    def label(self, dbname: str = 'postgres') -> str:
        self.dsn(dbname)
        return f'{HOST}:{self.port}/{dbname}'

    def validate_dsn(self, raw: str, *, dbnames=('postgres',)) -> str:
        # Deliberately smaller than libpq's grammar. No implicit/default params,
        # duplicate keys, arbitrary usernames, quoted credentials, or URIs.
        if not isinstance(raw, str):
            raise ValueError('explicit selected local test DSN required')
        params = {}
        for part in raw.split():
            match = re.fullmatch(r'(host|port|dbname)=([A-Za-z0-9_.]+)', part)
            if not match or match[1] in params:
                raise ValueError('only explicit host/port/dbname test DSN fields are allowed')
            params[match[1]] = match[2]
        if (set(params) != {'host', 'port', 'dbname'}
                or params['host'] != HOST or params['port'] != str(self.port)
                or params['dbname'] not in DATABASES or params['dbname'] not in dbnames):
            raise ValueError('DSN must match the selected loopback port and exact fixture database')
        return self.dsn(params['dbname'])

    def child_env(self, environ: Mapping[str, str]) -> dict[str, str]:
        if selected_target(environ).port != self.port:
            raise ValueError('child environment conflicts with selected local test target')
        return {**environ, 'POSTRIFF_TEST_PG_PORT': str(self.port),
                'POSTRIFF_TEST_DSN': self.dsn()}

    def assert_available(self) -> None:
        """Bind-only ownership preflight; never connect to a foreign listener."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                # Match the owned postmaster's bind policy: its stopped socket
                # may remain in TIME_WAIT. A live listener still refuses bind.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind((HOST, self.port))
        except OSError as error:
            raise RuntimeError(f'selected local PostgreSQL target {self.label()} is occupied or unavailable') from error


def selected_target(environ: Mapping[str, str] | None = None, *, require_dsn=False,
                    validate_fixture_dsns=True) -> LocalPGTarget:
    env = os.environ if environ is None else environ
    target = LocalPGTarget(bounded_port(env.get('POSTRIFF_TEST_PG_PORT', str(DEFAULT_PORT))))
    if (LIBPQ_OVERRIDES | PSQL_OVERRIDES).intersection(env):
        raise ValueError('libpq/psql connection or startup environment overrides forbidden for local test target')
    if 'POSTRIFF_PG_PORT' in env and bounded_port(env['POSTRIFF_PG_PORT']) != target.port:
        raise ValueError('legacy POSTRIFF_PG_PORT conflicts with POSTRIFF_TEST_PG_PORT')
    if 'POSTRIFF_TEST_DSN' in env:
        target.validate_dsn(env['POSTRIFF_TEST_DSN'])
    elif require_dsn:
        raise ValueError('explicit POSTRIFF_TEST_DSN required for this fixture')
    # Child wrappers/fixtures may prefer dedicated env keys. Conflicting values
    # must fail before the runner opens a socket or invokes psql, never redirect.
    if validate_fixture_dsns:
        for key in FIXTURE_DSN_KEYS.intersection(env):
            target.validate_dsn(env[key])
    return target
