"""Explicit SQL projections; no generic table/SQL interface or production superuser fallback."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .auth import ControlError


def serial(value):
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, dict): return {key: serial(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)): return [serial(item) for item in value]
    # UUID and Decimal must not force raw row serialization at endpoint boundaries.
    return str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value


class PostgresStore:
    def __init__(self, session_factory, reader_factory, environment):
        self.session_factory, self.reader_factory, self.environment = session_factory, reader_factory, environment

    @contextmanager
    def transaction(self, read=False):
        factory = self.reader_factory if read else self.session_factory
        with factory() as con:
            con.row_factory = dict_row
            with con.transaction():
                if read: con.execute('SET TRANSACTION READ ONLY')
                con.execute("SET LOCAL statement_timeout='5s'")
                role = con.execute("SELECT current_user AS name, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
                expected = 'rafii_control_reader' if read else 'rafii_control_session'
                if role['name'] != expected or role['rolsuper'] or role['rolbypassrls']:
                    raise ControlError('SOURCE_UNAVAILABLE', 503)
                con.execute("SELECT set_config('rafii_control.environment',%s,true)", (self.environment,))
                yield con

    def operator(self, user, environment):
        with self.transaction() as con:
            row = con.execute('SELECT user_id,environment,role,status,capabilities,auth_epoch FROM rafii_control.platform_operators WHERE user_id=%s AND environment=%s', (user, environment)).fetchone()
            return serial(row) if row else None

    def identity_active(self, user, session):
        with self.transaction() as con:
            return con.execute('SELECT rafii_control.identity_active(%s,%s) AS active', (user, session)).fetchone()['active']

    def create_session(self, row):
        keys = ('id','user_id','environment','token_hash','auth_epoch','assurance','upstream_session','mfa_at','created_at','last_seen_at','expires_at','revoked_at')
        with self.transaction() as con:
            con.execute('INSERT INTO rafii_control.founder_sessions(id,user_id,environment,token_hash,auth_epoch,assurance,upstream_session,mfa_at,created_at,last_seen_at,expires_at,revoked_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', tuple(row[key] for key in keys))

    def session(self, token_hash):
        with self.transaction() as con:
            row = con.execute('SELECT id,user_id,environment,token_hash,auth_epoch,assurance,upstream_session,mfa_at,created_at,last_seen_at,expires_at,revoked_at FROM rafii_control.founder_sessions WHERE token_hash=%s', (token_hash,)).fetchone()
            return serial(row) if row else None

    def touch(self, token_hash, now):
        with self.transaction() as con: con.execute('UPDATE rafii_control.founder_sessions SET last_seen_at=greatest(last_seen_at,%s) WHERE token_hash=%s AND revoked_at IS NULL', (now, token_hash))

    def revoke(self, token_hash, now):
        with self.transaction() as con: con.execute('UPDATE rafii_control.founder_sessions SET revoked_at=%s WHERE token_hash=%s', (now, token_hash))

    def audit(self, **event):
        keys = ('request_id','actor','session','environment','action','result')
        with self.transaction() as con:
            con.execute('INSERT INTO rafii_control.admin_audit_log(request_id,actor,session,environment,action,result) VALUES(%s,%s,%s,%s,%s,%s)', tuple(event[key] for key in keys))

    def budget(self, purpose, actor, limit):
        bucket = hashlib.sha256((purpose+':'+actor).encode()).hexdigest()
        with self.transaction() as con:
            row = con.execute('INSERT INTO rafii_control.request_budgets(bucket,environment,window_start,attempts) VALUES(%s,%s,floor(extract(epoch from now())/60),1) ON CONFLICT(bucket,environment) DO UPDATE SET window_start=excluded.window_start, attempts=CASE WHEN request_budgets.window_start=excluded.window_start THEN request_budgets.attempts+1 ELSE 1 END RETURNING attempts', (bucket,self.environment)).fetchone()
        if row['attempts'] > limit: raise ControlError('RATE_LIMITED', 429)

    def read(self, kind, identifier=None):
        # Static templates only. The caller cannot supply SQL, table names, fields or joins.
        templates = {
            'users': 'SELECT user_id,deleted,workspace_count,last_seen_at FROM rafii_control.safe_users ORDER BY user_id LIMIT 200',
            'user': 'SELECT user_id,deleted,workspace_count,last_seen_at FROM rafii_control.safe_users WHERE user_id=%s',
            'user_memberships': 'SELECT workspace_id,role,status FROM rafii_control.safe_memberships WHERE user_id=%s ORDER BY workspace_id LIMIT 200',
            'workspaces': 'SELECT id,created_at,member_count,subscription_status,plan,terms_version FROM rafii_control.safe_workspaces ORDER BY id LIMIT 200',
            'sources': 'SELECT source_id,state,watermark,checked_at,reason_code FROM rafii_control.source_health ORDER BY source_id LIMIT 100',
            'engineering': 'SELECT id,kind,provider,external_id,exact_sha,state,conclusion,failure_class,attested,required,observed_at FROM rafii_control.engineering_evidence ORDER BY observed_at DESC LIMIT 200',
            'receipt': 'SELECT id,query_digest,metric_versions,data_state,source_watermarks,row_count,created_at,expires_at FROM rafii_control.query_receipts WHERE id=%s',
            'recommendations': 'SELECT id,evidence_ids,proposal,state,created_at,expires_at FROM rafii_control.recommendations ORDER BY created_at DESC LIMIT 100',
        }
        if kind not in templates: raise ControlError('VALIDATION_FAILED', 400)
        with self.transaction(read=True) as con:
            return serial(con.execute(templates[kind], (identifier,) if identifier else ()).fetchall())

    def audit_read(self):
        with self.transaction() as con:
            return serial(con.execute('SELECT id,request_id,actor,environment,action,result,occurred_at FROM rafii_control.admin_audit_log ORDER BY occurred_at DESC LIMIT 200').fetchall())

    def receipt(self, receipt):
        with self.transaction() as con:
            con.execute('INSERT INTO rafii_control.query_receipts(id,operator_id,environment,request_id,query_digest,metric_versions,data_state,source_watermarks,row_count) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (receipt['id'], receipt['operator'], self.environment, receipt['requestId'], receipt['queryDigest'], Jsonb(receipt['metricVersions']), receipt['dataState'], Jsonb(receipt['sourceWatermarks']), receipt['rowCount']))

    def reserve_run(self, request, principal, request_digest):
        with self.transaction() as con:
            row = con.execute('INSERT INTO rafii_control.founder_runs(id,operator_id,environment,conversation_id,request_id,request_digest,result) VALUES(gen_random_uuid(),%s,%s,%s,%s,%s,%s) ON CONFLICT(operator_id,environment,request_id) DO NOTHING RETURNING id',
                              (principal['operator']['user_id'], self.environment, request['conversationId'], request['requestId'], request_digest, Jsonb({'state':'running'}))).fetchone()
            if row: return str(row['id']), None
            cached = con.execute('SELECT id,request_digest,result FROM rafii_control.founder_runs WHERE operator_id=%s AND request_id=%s', (principal['operator']['user_id'],request['requestId'])).fetchone()
            if not cached or cached['request_digest'] != request_digest: raise ControlError('IDEMPOTENCY_CONFLICT', 409)
            return str(cached['id']), cached['result']

    def save_run(self, run, principal, conversation):
        with self.transaction() as con:
            con.execute('UPDATE rafii_control.founder_runs SET result=%s WHERE id=%s AND operator_id=%s', (Jsonb(run),run['runId'],principal['operator']['user_id']))

    def run(self, identifier, operator):
        with self.transaction() as con:
            row = con.execute('SELECT result FROM rafii_control.founder_runs WHERE id=%s AND operator_id=%s', (identifier, operator)).fetchone()
            return row['result'] if row else None


def connection_factory(dsn, role, environment):
    """Dedicated non-superuser logins must be enrolled separately; role membership is checked by PostgreSQL."""
    def connect():
        con = psycopg.connect(dsn, prepare_threshold=None, connect_timeout=5)
        try:
            login = con.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=session_user').fetchone()
            if environment != 'local' and (login[0] or login[1]): raise ControlError('SOURCE_UNAVAILABLE', 503)
            con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
            con.commit()
            return con
        except Exception:
            con.close()
            raise
    return connect
