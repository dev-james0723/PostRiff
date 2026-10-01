"""Explicit SQL projections; no generic table/SQL interface or production superuser fallback."""
from collections import namedtuple
from contextlib import contextmanager
from .deadlines import remaining
from datetime import datetime
import hashlib
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .auth import ControlError

# A metric statement is composed only by live_metrics from its fixed per-metric registry
# (server-chosen views, columns, joins and aggregates). Browser input reaches it as parameters.
MetricStatement = namedtuple('MetricStatement', 'metric_id sql')


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
                con.execute("SELECT set_config('statement_timeout',%s,true)", (str(max(1,int(remaining()*1000))),))
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
        keys = ('request_id','actor','session','environment','action','result','error_code')
        with self.transaction() as con:
            con.execute('INSERT INTO rafii_control.admin_audit_log(request_id,actor,session,environment,action,result,error_code) VALUES(%s,%s,%s,%s,%s,%s,%s)', tuple(event[key] for key in keys))

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
            'receipt': 'SELECT id,operator_id,query_digest,metric_versions,data_state,source_watermarks,row_count,created_at,expires_at,result_rows,execution_state,normalized_query,calculated_at,source_versions,coverage FROM rafii_control.query_receipts WHERE id=%s',
            'recommendations': 'SELECT id,evidence_ids,proposal,state,created_at,expires_at FROM rafii_control.recommendations ORDER BY created_at DESC LIMIT 100',
        }
        if kind not in templates: raise ControlError('VALIDATION_FAILED', 400)
        with self.transaction(read=True) as con:
            return serial(con.execute(templates[kind], (identifier,) if identifier else ()).fetchall())

    def metric_rows(self, statement, params, limit=1000):
        """Reader-role execution of one fixed activated-metric statement (054 views only).

        The caller supplies a MetricStatement built by live_metrics plus bound parameters
        (interval bounds, timezone, filter values, limit); never SQL text, identifiers or joins.
        The reader transaction is read-only, environment-scoped and deadline-bounded.
        """
        if not isinstance(statement, MetricStatement) or not isinstance(statement.sql, str): raise ControlError('VALIDATION_FAILED', 400)
        with self.transaction(read=True) as con:
            rows = con.execute(statement.sql, tuple(params)).fetchall()
        if len(rows) > limit: raise ControlError('BUDGET_EXCEEDED', 400)
        return serial(rows)

    def audit_read(self):
        with self.transaction() as con:
            return serial(con.execute('SELECT id,request_id,actor,environment,action,result,error_code,occurred_at FROM rafii_control.admin_audit_log ORDER BY occurred_at DESC LIMIT 200').fetchall())

    def receipt(self, receipt):
        with self.transaction() as con:
            con.execute('INSERT INTO rafii_control.query_receipts(id,operator_id,environment,request_id,query_digest,metric_versions,data_state,source_watermarks,row_count,result_rows,execution_state,normalized_query,calculated_at,source_versions,coverage) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (receipt['id'], receipt['operator'], self.environment, receipt['requestId'], receipt['queryDigest'], Jsonb(receipt['metricVersions']), receipt['dataState'], Jsonb(receipt['sourceWatermarks']), receipt['rowCount'], Jsonb(receipt['rows']), receipt['executionState'], Jsonb(receipt['normalizedQuery']), receipt['calculatedAt'], Jsonb(receipt['sourceVersions']), Jsonb(receipt['coverage'])))

    def query_check_rollups(self, query, version):
        # Fixed metric/fixture policy, parameterized dimensions, SQL aggregation and capped output.
        # No row scan or query text supplied by the browser; reader transaction has a 5s timeout.
        filters = ''.join(' AND r.dimensions ->> %s = ANY(%s)' for _ in query['filters'])
        args = [version,query['interval']['start'],query['interval']['end']]
        for item in query['filters']: args.extend([item['dimension'],item['values']])
        args.extend([query['groupBy'],query['limit']+1])
        sql = """WITH bounded AS MATERIALIZED (
          SELECT r.* FROM rafii_control.metric_rollups r
          WHERE r.environment='local' AND r.fixture AND r.metric_id='check_failures' AND r.definition_version=%s
            AND r.policy_approval_ref IS NULL AND r.interval_start >= %s AND r.interval_end <= %s"""+filters+"""
          ORDER BY r.interval_start,r.dimension_digest LIMIT 1001)
          SELECT grouped.dimensions, sum(r.value) AS value, sum(r.sample_count) AS sample_count,
            array_agg(DISTINCT r.data_state) AS states, min(r.source_watermark) AS source_watermark,
            array_agg(r.source_receipt_ids[1] ORDER BY r.interval_start) AS source_receipt_ids,
            count(*) AS projected_count, (SELECT count(*) FROM bounded) AS input_count
          FROM bounded r CROSS JOIN LATERAL
            (SELECT coalesce(jsonb_object_agg(key,value),'{}'::jsonb) AS dimensions FROM jsonb_each(r.dimensions) WHERE key=ANY(%s)) grouped
          GROUP BY grouped.dimensions ORDER BY grouped.dimensions::text LIMIT %s"""
        with self.transaction(read=True) as con:
            rows = con.execute(sql,args).fetchall()
        if len(rows)>query['limit']: raise ControlError('BUDGET_EXCEEDED',400)
        if any(row['input_count']>1000 for row in rows): raise ControlError('BUDGET_EXCEEDED',400)
        return serial(rows)

    def reserve_run(self, request, principal, request_digest):
        with self.transaction() as con:
            row = con.execute('INSERT INTO rafii_control.founder_runs(id,operator_id,environment,conversation_id,request_id,request_digest,result) VALUES(gen_random_uuid(),%s,%s,%s,%s,%s,%s) ON CONFLICT(operator_id,environment,request_id) DO NOTHING RETURNING id',
                              (principal['operator']['user_id'], self.environment, request['conversationId'], request['requestId'], request_digest, Jsonb({'state':'running'}))).fetchone()
            if row: return str(row['id']), None
            cached = con.execute('SELECT id,request_digest,result FROM rafii_control.founder_runs WHERE operator_id=%s AND request_id=%s', (principal['operator']['user_id'],request['requestId'])).fetchone()
            if not cached or cached['request_digest'] != request_digest: raise ControlError('IDEMPOTENCY_CONFLICT', 409)
            self._expire_running(con, cached['id'], principal['operator']['user_id'])
            current = con.execute('SELECT result FROM rafii_control.founder_runs WHERE id=%s', (cached['id'],)).fetchone()
            return str(cached['id']), current['result']

    def save_run(self, run, principal, conversation):
        with self.transaction() as con:
            return con.execute("UPDATE rafii_control.founder_runs SET result=%s WHERE id=%s AND operator_id=%s AND result->>'state'='running'", (Jsonb(run),run['runId'],principal['operator']['user_id'])).rowcount==1

    def run(self, identifier, operator):
        with self.transaction() as con:
            self._expire_running(con, identifier, operator)
            row = con.execute('SELECT result FROM rafii_control.founder_runs WHERE id=%s AND operator_id=%s', (identifier, operator)).fetchone()
            return row['result'] if row else None


    @staticmethod
    def _expire_running(con, identifier, operator):
        rows=con.execute("UPDATE rafii_control.founder_runs SET result=jsonb_build_object('runId',id,'state','blocked','code','SOURCE_UNAVAILABLE','answerText','Interrupted read; outcome unknown. No action was performed.','queryReceiptIds','[]'::jsonb,'changedEntities','[]'::jsonb) WHERE id=%s AND operator_id=%s AND result->>'state'='running' AND created_at < now()-interval '2 minutes' RETURNING request_id,operator_id,environment", (identifier,operator)).fetchall()
        for row in rows:
            con.execute("INSERT INTO rafii_control.admin_audit_log(request_id,actor,environment,action,result,error_code) VALUES(%s,%s,%s,'copilot.use','failed','SOURCE_UNAVAILABLE')",(row['request_id'],row['operator_id'],row['environment']))


    def check_snapshots(self):
        with self.transaction(read=True) as con:
            return serial(con.execute('SELECT id,exact_sha,provenance,observed_at,payload FROM rafii_control.github_check_snapshots ORDER BY observed_at DESC,id LIMIT 20').fetchall())

    def check_snapshot(self, identifier):
        with self.transaction(read=True) as con:
            row=con.execute('SELECT payload FROM rafii_control.github_check_snapshots WHERE id=%s',(identifier,)).fetchone()
            return row['payload'] if row else None


def connection_factory(dsn, role, environment):
    """Dedicated non-superuser logins must be enrolled separately; role membership is checked by PostgreSQL."""
    def connect():
        budget=remaining();millis=max(1,int(budget*1000))
        con = psycopg.connect(dsn, prepare_threshold=None, connect_timeout=max(1, int(budget)), options=f'-c statement_timeout={millis} -c lock_timeout={millis}',keepalives_idle=1,keepalives_interval=1,keepalives_count=1,tcp_user_timeout=millis)
        try:
            remaining()
            login = con.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=session_user').fetchone()
            if environment != 'local' and (login[0] or login[1]): raise ControlError('SOURCE_UNAVAILABLE', 503)
            con.execute(f'SET statement_timeout={max(1,int(remaining()*1000))}')
            remaining()
            con.execute(psycopg.sql.SQL('SET ROLE {}').format(psycopg.sql.Identifier(role)))
            remaining()
            con.commit()
            remaining()
            return con
        except Exception:
            con.close()
            raise
    return connect
