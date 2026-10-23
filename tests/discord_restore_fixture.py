"""Throw-away, restorable PostgreSQL clusters and a mock Discord with channel history, for the restore drill.

Builds on the W-02 real-PostgreSQL fixtures (tests/discord_lane_fixture.py): the same repository schema, provider,
shared request coordinator, synthetic tenants and lane loops. What this adds:

- ArchivedCluster: a cluster configured like a production primary for point-in-time recovery (wal_level=replica,
  archive_mode=on, an archive_command that copies each WAL segment into a local archive directory, a short
  archive_timeout), base backups with pg_basebackup, and restore() into a NEW data directory with restore_command,
  recovery_target_time and recovery_target_action='promote'. It listens on 127.0.0.1 only (no unix socket, so the long
  scratchpad path does not hit the socket-name limit). When run as root, the server programs run inside a user
  namespace that maps root to the postgres uid: PostgreSQL refuses to run as root, and the root-only scratchpad
  directory stays reachable (runuser could not traverse it).
- RestoreMockDiscord: the W-02 MockDiscord plus what a restore drill needs: message ids are real-shaped snowflakes that
  encode their creation time, messages carry `timestamp` and `edited_timestamp`, `GET /channels/{id}/messages?limit=50`
  (and `before=`) answers channel history newest first, a moderator can delete a message and someone can edit one,
  other people can post, and an optional nonce window models Discord's `enforce_nonce` (off by default, as in W-02).

Nothing here reads application credentials or reaches a network beyond 127.0.0.1. Every id, name and text is synthetic.
"""
import hashlib
import json
import os
import pwd
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import discord_lane_fixture as F

PG_BIN = Path(os.environ.get('POSTRIFF_PG_BIN') or '/usr/lib/postgresql/16/bin')
DISCORD_EPOCH_MS = 1420070400000
SCHEMA = (F.ROOT / 'tests/phase2/rls.sql', *(F.ROOT / 'migrations/postriff' / name for name in F.MIGRATIONS))


def available():
    return bool(F.psycopg and (PG_BIN / 'initdb').exists() and (PG_BIN / 'pg_basebackup').exists())


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


_PREFIX = None


def server_prefix():
    """How to run initdb/pg_ctl: unchanged as a normal user; as root, inside a user namespace mapped to postgres."""
    global _PREFIX
    if _PREFIX is not None:
        return _PREFIX
    if os.geteuid() != 0:
        _PREFIX = []
        return _PREFIX
    account = pwd.getpwnam('postgres')
    candidate = ['unshare', '--user', '--map-user=%d' % account.pw_uid, '--map-group=%d' % account.pw_gid, '--']
    probe = subprocess.run([*candidate, 'true'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode == 0:
        _PREFIX = candidate
    else:  # no user namespaces: the base directory must then be reachable by the postgres user
        _PREFIX = ['runuser', '-u', 'postgres', '--']
    return _PREFIX


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(sep=' ')


def _run(args, *, server=False, check=True, timeout=600):
    done = subprocess.run([*(server_prefix() if server else []), *map(str, args)], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, timeout=timeout)
    if check and done.returncode:
        raise RuntimeError('%s failed (%d): %s' % (Path(str(args[0])).name, done.returncode,
                                                  (done.stderr or done.stdout).strip()[-2000:]))
    return done


class ArchivedCluster:
    """One PostgreSQL cluster in `root`, on 127.0.0.1:`port`. Same connect/factory/now shape as F.Cluster."""

    def __init__(self, root, *, port=None, archive=None, wal_segsize=1, archive_timeout=2, fsync=False,
                 max_connections=150, initialize=True, extra=None):
        self.root = Path(root)
        self.data = self.root / 'data'
        self.log = self.root / 'postgres.log'
        self.port = port or free_port()
        self.archive = Path(archive) if archive else None
        self.dsn = 'host=127.0.0.1 port=%d dbname=postgres user=postgres connect_timeout=5' % self.port
        self.root.mkdir(parents=True, exist_ok=True)
        if initialize:
            _run([PG_BIN / 'initdb', '-D', self.data, '-A', 'trust', '--no-locale', '-E', 'UTF8', '-U', 'postgres',
                  '--wal-segsize=%d' % wal_segsize], server=True)
            settings = {'listen_addresses': "'127.0.0.1'", 'unix_socket_directories': "''",
                        'max_connections': str(max_connections), 'shared_buffers': "'48MB'", 'wal_level': 'replica',
                        'max_wal_senders': '4', 'fsync': 'on' if fsync else 'off', 'log_min_messages': 'warning',
                        'log_line_prefix': "'%m [%p] '", 'log_checkpoints': 'off'}
            if self.archive:
                self.archive.mkdir(parents=True, exist_ok=True)
                settings.update(archive_mode='on', archive_timeout=str(archive_timeout),
                                archive_command="'test ! -f \"%s/%%f\" && cp \"%%p\" \"%s/%%f\"'" % (self.archive, self.archive))
            settings.update(extra or {})
            self.configure(settings)

    def configure(self, settings):
        with open(self.data / 'postgresql.auto.conf', 'a') as conf:
            for key, value in settings.items():
                conf.write('%s = %s\n' % (key, value))

    def start(self, timeout=180):
        _run([PG_BIN / 'pg_ctl', '-D', self.data, '-l', self.log, '-o', '-p %d' % self.port, '-w', '-t', str(timeout),
              'start'], server=True, timeout=timeout + 30)
        return self

    def stop(self, mode='fast'):
        if (self.data / 'postmaster.pid').exists():
            _run([PG_BIN / 'pg_ctl', '-D', self.data, '-m', mode, '-w', '-t', '120', 'stop'], server=True, check=False)

    def running(self):
        return (self.data / 'postmaster.pid').exists()

    def destroy(self):
        try:
            self.stop('immediate')
        finally:
            shutil.rmtree(self.root, ignore_errors=True)

    # The F.Cluster surface the W-02 helpers use.
    def connect(self, **options):
        return F.psycopg.connect(self.dsn, **options)

    def factory(self, tracker=None):
        def open_connection():
            connection = F.psycopg.connect(self.dsn, prepare_threshold=None)
            return tracker.wrap(connection) if tracker else connection
        return open_connection

    def now(self):
        with self.connect(autocommit=True) as db:
            return float(db.execute('SELECT extract(epoch from clock_timestamp())').fetchone()[0])

    def sql(self, statement, params=None):
        with self.connect(autocommit=True) as db:
            cursor = db.execute(statement, params)
            return cursor.fetchall() if cursor.description else cursor.rowcount

    def apply_schema(self):
        for script in SCHEMA:
            done = subprocess.run([str(PG_BIN / 'psql'), self.dsn, '-v', 'ON_ERROR_STOP=1', '-q', '-f', str(script)],
                                  cwd=script.parent, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if done.returncode:
                raise RuntimeError('%s failed: %s' % (script.name, done.stderr.strip()[-2000:]))

    def base_backup(self, target):
        """pg_basebackup in plain format with the WAL it needs streamed in; returns (path, seconds)."""
        started = time.monotonic()
        _run([PG_BIN / 'pg_basebackup', '-h', '127.0.0.1', '-p', self.port, '-U', 'postgres', '-D', target,
              '-X', 'stream', '-c', 'fast', '--no-sync'])
        return Path(target), time.monotonic() - started

    def flush_archive(self, timeout=60):
        """Switch WAL and wait until the archiver holds every segment up to the switch point."""
        with self.connect(autocommit=True) as db:
            segment = db.execute('SELECT pg_walfile_name(pg_switch_wal())').fetchone()[0]
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                last, failed = db.execute('SELECT last_archived_wal, failed_count FROM pg_stat_archiver').fetchone()
                if last and last[8:] >= segment[8:]:  # same timeline; compare log and segment numbers
                    return segment, failed
                time.sleep(.2)
        raise RuntimeError('the WAL archive did not catch up within %d s' % timeout)


def restore(base, archive, target_time, root, *, port=None, inclusive=True, timeout=300):
    """Point-in-time recovery of `base` + `archive` up to `target_time` (epoch) into a NEW data directory under
    `root`, promoted at the target. Never touches the source cluster or the base backup. Returns (cluster, report)."""
    root = Path(root)
    if root.exists():
        raise RuntimeError('refusing to restore over an existing directory: %s' % root)
    started = time.monotonic()
    cluster = ArchivedCluster(root, port=port, initialize=False)
    shutil.copytree(base, cluster.data, symlinks=True)
    os.chmod(cluster.data, 0o700)
    copied = time.monotonic() - started
    cluster.configure({'port': str(cluster.port), 'archive_mode': 'off',
                       'restore_command': "'cp \"%s/%%f\" \"%%p\"'" % Path(archive),
                       'recovery_target_time': "'%s'" % iso(target_time),
                       'recovery_target_inclusive': 'on' if inclusive else 'off',
                       'recovery_target_timeline': "'current'", 'recovery_target_action': "'promote'"})
    (cluster.data / 'recovery.signal').touch()
    cluster.start(timeout=timeout)
    deadline = time.monotonic() + timeout
    while True:
        try:
            if not cluster.sql('SELECT pg_is_in_recovery()')[0][0]:
                break
        except F.psycopg.OperationalError:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError('recovery did not promote within %d s' % timeout)
        time.sleep(.1)
    seconds = time.monotonic() - started
    stopped = [line.split(']', 1)[-1].strip() for line in cluster.log.read_text(errors='replace').splitlines()
               if 'recovery stopping' in line]
    return cluster, {'targetTime': iso(target_time), 'copySeconds': round(copied, 3), 'wallSeconds': round(seconds, 3),
                     'recoveryStopping': stopped[-1][:200] if stopped else None}


def snowflake_at(epoch, sequence):
    return str(((int(epoch * 1000) - DISCORD_EPOCH_MS) << 22) | (sequence & 0x3FFFFF))


def snowflake_time(message_id):
    return ((int(message_id) >> 22) + DISCORD_EPOCH_MS) / 1000.0


def content_digest(text):
    return hashlib.sha256((text or '').encode()).hexdigest()


class RestoreMockDiscord(F.MockDiscord):
    """F.MockDiscord with channel history, deletion, edits, other authors and an optional nonce window.

    `creates` (by nonce, as in W-02) and `log` (every create: nonce, channel, content digest, wall time, message id,
    whether Discord returned an existing message for the nonce) are the ground truth of what customers saw.
    """

    def __init__(self, tenants, *, nonce_window=None, **options):
        super().__init__(tenants, **options)
        self.nonce_window = nonce_window
        self.history = {}  # channel -> [message ids], oldest first, only messages still visible
        self.log, self.deleted, self.nonces = [], set(), {}
        self.counter = 0

    def reset_requests(self):
        with self.lock:
            self.calls.clear()

    def _new_message(self, channel, content, author, nonce=None):
        self.counter += 1
        created = time.time()
        message = {'id': snowflake_at(created, self.counter), 'channel_id': channel, 'content': content,
                   'author': author, 'type': 0, 'timestamp': datetime.fromtimestamp(created, timezone.utc).isoformat(),
                   'edited_timestamp': None, 'mention_everyone': False, 'mentions': [], 'mention_roles': [],
                   'attachments': [], 'embeds': [], 'pinned': False, 'tts': False}
        self.messages[message['id']] = message
        self.history.setdefault(channel, []).append(message['id'])
        return message, created

    def _answer(self, method, path, body, now):
        route, _, query = path.partition('?')
        parts = route.strip('/').split('/')
        if method == 'POST' and len(parts) == 3 and parts[0] == 'channels' and parts[2] == 'messages':
            ok, headers = self._bucket('create', parts[1], *self.LIMITS['create'], now)
            if not ok:
                self.route429 += 1
                return {'status': 429, 'headers': headers, 'body': {'message': 'You are being rate limited.',
                                                                    'retry_after': float(headers['retry-after']), 'global': False}}
            body = body or {}
            nonce = body.get('nonce')
            prior = self.nonces.get((parts[1], F.BOT, nonce)) if nonce and body.get('enforce_nonce') else None
            if (prior and self.nonce_window is not None and time.time() - prior[1] <= self.nonce_window
                    and prior[0] in self.messages):
                # Discord: "If another message was created by the same author with the same nonce, that message
                # will be returned and no new message will be created" (within a window of a few minutes).
                self.log.append({'nonce': nonce, 'channel': parts[1], 'digest': content_digest(body.get('content')),
                                 'at': time.time(), 'id': prior[0], 'deduplicated': True})
                return {'status': 200, 'headers': headers, 'body': {**self.messages[prior[0]], 'nonce': nonce}}
            message, created = self._new_message(parts[1], body.get('content'), {'id': F.BOT, 'bot': True}, nonce)
            if nonce:
                self.nonces[(parts[1], F.BOT, nonce)] = (message['id'], created)
            self.creates[nonce].append((now, parts[1], created))
            self.log.append({'nonce': nonce, 'channel': parts[1], 'digest': content_digest(body.get('content')),
                             'at': created, 'id': message['id'], 'deduplicated': False})
            return {'status': 200, 'headers': headers, 'body': {**message, 'nonce': nonce}}
        if method == 'GET' and len(parts) == 3 and parts[0] == 'channels' and parts[2] == 'messages':
            ok, headers = self._bucket('history', parts[1], *self.read_limit, now)
            if not ok:
                self.route429 += 1
                return {'status': 429, 'headers': headers, 'body': {'message': 'You are being rate limited.',
                                                                    'retry_after': float(headers['retry-after']), 'global': False}}
            if parts[1] not in self.channels and parts[1] not in self.history:
                return {'status': 404, 'headers': headers, 'body': {'message': 'Unknown Channel', 'code': 10003}}
            options = dict(item.split('=', 1) for item in query.split('&') if '=' in item)
            limit = max(1, min(100, int(options.get('limit', 50))))
            visible = [m for m in self.history.get(parts[1], []) if m in self.messages]
            if 'before' in options:
                visible = [m for m in visible if int(m) < int(options['before'])]
            page = [dict(self.messages[m]) for m in reversed(visible)][:limit]  # newest first, like Discord
            return {'status': 200, 'headers': headers, 'body': page}
        if method == 'GET' and len(parts) == 4 and parts[0] == 'channels' and parts[2] == 'messages':
            if parts[3] in self.deleted:
                ok, headers = self._bucket('message', parts[1], *self.read_limit, now)
                return {'status': 404, 'headers': headers, 'body': {'message': 'Unknown Message', 'code': 10008}}
        return super()._answer(method, path, body, now)

    # What happens in Discord outside Rafii ------------------------------------------------------------------------

    def delete(self, message_id):
        """A moderator deletes a message: it leaves history and its lookup answers 404."""
        with self.lock:
            self.messages.pop(message_id, None)
            self.deleted.add(message_id)

    def edit(self, message_id, content):
        with self.lock:
            message = self.messages[message_id]
            message.update(content=content, edited_timestamp=datetime.now(timezone.utc).isoformat())

    def post_as_user(self, channel, content, user='5550001'):
        with self.lock:
            return self._new_message(channel, content, {'id': user, 'bot': False})[0]['id']

    def messages_for(self, nonce):
        return [entry for entry in self.log if entry['nonce'] == nonce]

    def visible_creates(self):
        """Distinct messages Rafii's bot created (a nonce-deduplicated answer is not a new message)."""
        return [entry for entry in self.log if not entry['deduplicated']]

    def snapshot(self):
        return json.loads(json.dumps({'log': self.log, 'deleted': sorted(self.deleted)}))
