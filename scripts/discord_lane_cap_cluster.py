"""Throwaway PostgreSQL and the production schema for the W-02 capacity harness.

The cluster is created from the server binaries named by --pg-bin (POSTRIFF_PG_BIN), in a temporary directory, the
way tests/discord_lane_fixture.py does it (initdb as the postgres user when running as root, unix socket in a short
path), and listens on 127.0.0.1 only. The schema is the tested source tree's own: the minimal Supabase role harness at
the top of tests/phase2/rls.sql, then the migration set the production ledger holds (docs/launch-20261023-discord/
S-05-migration-reconciliation.md: every numbered migration except the local-only 003 and 108 to 112, which production
does not have, plus the three dated Pinterest migrations), applied with scripts/postriff_migrate.py's rule (outer
BEGIN/COMMIT lines removed, one transaction per file).

Server settings follow the production database where the facts are known (Supabase Micro: shared_buffers 224 MB,
UTC); pg_stat_statements and statement logging are on so the run can report its longest statements and errors.
"""
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

PRODUCTION_ABSENT = ('003', '108', '109', '110', '111', '112')
DATED = ('20261014_pinterest_rate_budgets.sql', '20261017_pinterest_metric_reads.sql',
         '20261017_pinterest_trial_journal.sql')


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def migration_paths(source_tree):
    folder = Path(source_tree) / 'migrations/postriff'
    paths = sorted(folder.glob('[0-9][0-9][0-9]_*.sql'))
    numbers = [p.name.split('_')[0] for p in paths]
    if len(numbers) != len(set(numbers)):
        raise RuntimeError('duplicate migration numbers in ' + str(folder))
    paths = [p for p in paths if p.name[:3] not in PRODUCTION_ABSENT]
    return paths + [folder / name for name in DATED if (folder / name).exists()]


def role_prelude(source_tree):
    """The Supabase role harness the repository's own PostgreSQL suites start from (rls.sql up to its first include)."""
    lines = []
    for line in (Path(source_tree) / 'tests/phase2/rls.sql').read_text().splitlines():
        if line.startswith('\\ir'):
            break
        if not line.startswith('\\'):
            lines.append(line)
    return '\n'.join(lines)


def apply_schema(dsn, source_tree, *, log=print):
    """The role harness (roles are cluster-wide: created once, kept) and the production migration set, on an empty
    database; refuses a database that already has a Rafii schema."""
    import psycopg
    started = time.time()
    applied = []
    with psycopg.connect(dsn, autocommit=True) as db:
        exists = db.execute("SELECT to_regclass('public.pr_workspaces')").fetchone()[0]
        if exists:
            raise RuntimeError('the target database already has a Rafii schema; use an empty database')
        roles = {row[0] for row in db.execute(
            "SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role')").fetchall()}
        if db.execute("SELECT to_regclass('auth.users')").fetchone()[0] is None:
            for statement in [part.strip() for part in role_prelude(source_tree).split(';\n') if part.strip()]:
                words = statement.split()
                if words[:2] == ['create', 'role'] and words[2] in roles:
                    continue
                db.execute(statement.rstrip(';'))
        for path in migration_paths(source_tree):
            body = re.sub(r'(?im)^(?:begin|commit);\s*$', '', path.read_text())
            with db.transaction():
                db.execute(body, prepare=False)
            applied.append(path.name)
        try:
            db.execute('CREATE EXTENSION IF NOT EXISTS pg_stat_statements')
        except Exception:
            pass
    log('schema: %d migrations in %.1f s' % (len(applied), time.time() - started))
    return applied


class LocalCluster:
    """A disposable cluster; close() stops it and removes its directory (also on failure)."""
    def __init__(self, pg_bin, *, max_connections=100, shared_buffers='224MB', log=print):
        self.pg_bin = Path(pg_bin)
        if not (self.pg_bin / 'initdb').exists():
            raise RuntimeError('no PostgreSQL server binaries at ' + str(pg_bin))
        self.log = log
        self.runas = ['runuser', '-u', 'postgres', '--'] if os.geteuid() == 0 else []
        self.tmp = tempfile.mkdtemp(prefix='prcap-', dir='/tmp')  # short path: socket names are length limited
        os.chmod(self.tmp, 0o755)
        if self.runas:
            shutil.chown(self.tmp, 'postgres', 'postgres')
        self.data, self.sock = Path(self.tmp) / 'data', Path(self.tmp) / 'sock'
        self.logfile = Path(self.tmp) / 'postgres.log'
        self.port = free_port()
        self.dsn = 'host=%s port=%d dbname=postgres user=postgres' % (self.sock, self.port)
        self.tcp_dsn = 'host=127.0.0.1 port=%d dbname=postgres user=postgres' % self.port
        self.socket_path = str(self.sock / ('.s.PGSQL.%d' % self.port))
        try:
            self._run('mkdir', str(self.sock))
            self._run(str(self.pg_bin / 'initdb'), '-D', str(self.data), '-A', 'trust', '--no-locale', '-E', 'UTF8',
                      '-U', 'postgres')
            settings = {
                'listen_addresses': "'127.0.0.1'", 'port': str(self.port), 'unix_socket_directories': "'%s'" % self.sock,
                'max_connections': str(max_connections), 'shared_buffers': "'%s'" % shared_buffers,
                'timezone': "'UTC'", 'log_timezone': "'UTC'",
                'shared_preload_libraries': "'pg_stat_statements'", 'pg_stat_statements.track': "'top'",
                'pg_stat_statements.max': '5000', 'track_activity_query_size': '2048',
                'log_line_prefix': "'%m [%p] %e '", 'log_min_messages': "'warning'",
                'log_min_error_statement': "'error'", 'log_lock_waits': 'on', 'deadlock_timeout': "'1s'",
                'log_min_duration_statement': '1000', 'log_checkpoints': 'off',
            }
            config = self.data / 'postgresql.conf'
            text = config.read_text() + '\n# capacity harness\n' + ''.join('%s = %s\n' % item for item in settings.items())
            self._write_as_postgres(config, text)
            self._run(str(self.pg_bin / 'pg_ctl'), '-D', str(self.data), '-l', str(self.logfile), '-w', '-t', '60',
                      'start')
            self.log('postgres: %s cluster on 127.0.0.1:%d (socket %s)' % (self.version(), self.port, self.sock))
        except BaseException:
            self.close()
            raise

    def _write_as_postgres(self, path, text):
        temporary = Path(self.tmp) / 'postgresql.conf.new'
        temporary.write_text(text)
        if self.runas:
            shutil.chown(temporary, 'postgres', 'postgres')
        os.replace(temporary, path)

    def _run(self, *args):
        done = subprocess.run([*self.runas, *args], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if done.returncode:
            raise RuntimeError('%s failed (%d): %s' % (args[0], done.returncode, done.stderr.strip()[-2000:]))

    def version(self):
        import psycopg
        with psycopg.connect(self.dsn, autocommit=True) as db:
            return db.execute('SHOW server_version').fetchone()[0]

    def postmaster_pid(self):
        try:
            return int((self.data / 'postmaster.pid').read_text().splitlines()[0])
        except (OSError, ValueError, IndexError):
            return None

    def close(self):
        try:
            if (self.data / 'postmaster.pid').exists():
                subprocess.run([*self.runas, str(self.pg_bin / 'pg_ctl'), '-D', str(self.data), '-m', 'immediate',
                                '-w', '-t', '30', 'stop'], check=False, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
                pid = self.postmaster_pid()
                if pid:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)


def fresh_database(admin_dsn, name):
    """CREATE DATABASE `name` on an external server and return (admin DSN, connection info) pointing at it."""
    import psycopg
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,50}', name):
        raise ValueError('unsafe database name')
    with psycopg.connect(admin_dsn, autocommit=True) as db:
        db.execute('CREATE DATABASE %s' % name)
    info = psycopg.conninfo.conninfo_to_dict(admin_dsn)
    info['dbname'] = name
    return psycopg.conninfo.make_conninfo(**info)


def drop_database(admin_dsn, name):
    import psycopg
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,50}', name):
        return
    with psycopg.connect(admin_dsn, autocommit=True) as db:
        db.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()', (name,))
        db.execute('DROP DATABASE IF EXISTS %s' % name)
