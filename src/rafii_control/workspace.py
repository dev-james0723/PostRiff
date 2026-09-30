"""Founder business workspace. Canonical reads and isolated, per-founder Demo state.

No provider SDKs, customer messages or financial executors are imported here.
"""
from datetime import datetime, timezone
import copy
import re
import uuid
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from .auth import ControlError
from .store import serial


def sample_data():
    customers = [dict(id=f'customer-{i}', name=name, status='active', workspaceIds=[f'workspace-{i}'])
                 for i, name in enumerate(('Maya Chen', 'Leo Martins', 'Aisha Patel'), 1)]
    workspaces = [dict(id=f'workspace-{i}', name=name, ownerId=f'customer-{i}', memberCount=count,
                       revision=1, plan=plan, status=status, renameAllowed=True)
                  for i, name, count, plan, status in ((1,'Fern Studio',3,'Studio','active'),(2,'Northline Stories',1,'Studio Assist','past_due'),(3,'Aisha Creates',1,'Trial','trial'))]
    return dict(mode='demo', revision=1, customers=customers, workspaces=workspaces,
                subscriptions=[dict(id=w['id'], workspaceId=w['id'], plan=w['plan'], status=w['status'],
                                    amountMinor=amount, currency='USD', termsStatus='sample', renewsAt='2026-10-15T00:00:00Z') for w,amount in zip(workspaces,(1900,3900,0))],
                payments=[dict(id='payment-1',workspaceId='workspace-1',amountMinor=1900,currency='USD',status='funded',at='2026-09-28T10:00:00Z'),
                          dict(id='payment-2',workspaceId='workspace-2',amountMinor=3900,currency='USD',status='pending',at='2026-09-29T10:00:00Z')],
                usage=[dict(id=f'usage-{i}',workspaceId=f'workspace-{i}',kind='settle',dimension='text_model',quantity=n,unit='request',costState='actual',actualUsdMicro=n*1000,at='2026-09-30T08:00:00Z') for i,n in ((1,18),(2,7),(3,2))],
                tickets=[dict(id='ticket-1',workspaceId='workspace-2',title='Payment needs attention',status='open',kind='billing',at='2026-09-29T12:00:00Z'),
                         dict(id='ticket-2',workspaceId='workspace-1',title='Help with a channel connection',status='open',kind='support',at='2026-09-30T09:00:00Z')],
                activity=[dict(id='activity-1',workspaceId='workspace-3',label='Aisha created a workspace',at='2026-09-30T08:00:00Z')],
                connections=[dict(id='database',label='Sample workspace',state='demo',required=True,detail='Isolated sample data for this founder. Reset at any time.')],
                summary=dict(customers=3,workspaces=3,activeSubscriptions=1,openRequests=2),
                limits=dict(pageSize=200,truncated=False), paymentState='demo', supportState='demo', usageState='demo')


class WorkspaceService:
    def __init__(self, store): self.store = store

    def dispatch(self, path, body, principal, request_id):
        try:
            if path == '/workspace/live': return self.live(principal)
            if path == '/workspace/demo': return self.demo(principal)
            if path == '/workspace/demo/action': return self.demo(principal, body)
            if path == '/workspace/live/rename': return self.rename(principal, body)
            if path in ('/workspace/live/query','/workspace/demo/query'): return self.query(principal,body,'demo' if '/demo/' in path else 'live')
            raise ControlError('SCOPE_DENIED',404)
        except (psycopg.errors.UndefinedTable,psycopg.errors.UndefinedColumn,psycopg.errors.InvalidSchemaName):
            raise ControlError('WORKSPACE_CONFIGURATION_REQUIRED',503) from None
        except psycopg.errors.InsufficientPrivilege:
            raise ControlError('WORKSPACE_ACCESS_REQUIRED',503) from None

    @staticmethod
    def identity(principal): return principal['operator']['user_id']

    def demo(self, principal, action=None):
        # Isolation is enforced by RLS and the verified principal, never a browser-supplied actor.
        with self.store.transaction() as con:
            actor = self.identity(principal)
            con.execute("SELECT set_config('rafii_control.operator',%s,true)",(actor,))
            con.execute('INSERT INTO rafii_control.demo_workspaces(operator_id,environment,payload) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                        (actor,self.store.environment,Jsonb(sample_data())))
            row = con.execute('SELECT payload,replays FROM rafii_control.demo_workspaces WHERE operator_id=%s AND environment=%s FOR UPDATE',
                              (actor,self.store.environment)).fetchone()
            data, replays = copy.deepcopy(row['payload']), row['replays']
            if action is None: return data
            if set(action) != {'action','targetId','value','revision','requestId'}: raise ControlError('VALIDATION_FAILED',400)
            if (not isinstance(action['action'],str) or not isinstance(action['targetId'],str) or
                not re.fullmatch('[A-Za-z0-9-]{1,80}',action['targetId']) or not isinstance(action['value'],str) or
                (action['action']!='rename_workspace' and action['value']!='') or
                (action['action']=='reset' and action['targetId']!='all')): raise ControlError('VALIDATION_FAILED',400)
            try: key = str(uuid.UUID(action['requestId']))
            except (ValueError,TypeError,AttributeError): raise ControlError('VALIDATION_FAILED',400) from None
            replay = replays.get(key)
            if replay:
                if replay['request'] != action: raise ControlError('IDEMPOTENCY_CONFLICT',409)
                return replay['response']
            if type(action['revision']) is not int or action['revision'] != data['revision']: raise ControlError('STALE_PREVIEW',409)
            kind = action['action']
            if kind == 'reset':
                data = sample_data()
                data['revision'] = row['payload']['revision']
            elif kind == 'rename_workspace':
                target = self.target(data,'workspaces',action['targetId'])
                target['name'] = self.name(action['value'])
                target['revision'] += 1
            elif kind in ('resolve_ticket','reopen_ticket'):
                self.target(data,'tickets',action['targetId'])['status'] = 'completed' if kind=='resolve_ticket' else 'open'
            elif kind == 'simulate_payment':
                target = self.target(data,'payments',action['targetId'])
                if target['status'] != 'pending': raise ControlError('STALE_PREVIEW',409)
                target['status'] = 'funded'
                self.target(data,'workspaces',target['workspaceId'])['status'] = 'active'
                self.target(data,'subscriptions',target['workspaceId'])['status'] = 'active'
            else: raise ControlError('SCOPE_DENIED')
            data['revision'] += 1
            data['summary']['activeSubscriptions'] = sum(s['status']=='active' for s in data['subscriptions'])
            data['summary']['openRequests'] = sum(t['status']=='open' for t in data['tickets'])
            data['activity'].insert(0,dict(id=key,workspaceId=action['targetId'] if kind=='rename_workspace' else None,
                                         label={'reset':'Demo reset','rename_workspace':'Sample workspace renamed','resolve_ticket':'Sample request resolved','reopen_ticket':'Sample request reopened','simulate_payment':'Sample payment recorded'}[kind],
                                         at=datetime.now(timezone.utc).isoformat()))
            data['activity'] = data['activity'][:50]
            replays[key] = dict(request=action,response=data)
            replays = dict(list(replays.items())[-20:])
            con.execute('UPDATE rafii_control.demo_workspaces SET payload=%s,replays=%s WHERE operator_id=%s AND environment=%s',
                        (Jsonb(data),Jsonb(replays),actor,self.store.environment))
            con.execute('INSERT INTO rafii_control.workspace_actions(operator_id,environment,mode,request_id,action,target_id) VALUES(%s,%s,\'demo\',%s,%s,%s)',
                        (actor,self.store.environment,key,kind,str(action['targetId'])[:160]))
            return data

    @staticmethod
    def target(data, collection, identifier):
        row = next((r for r in data[collection] if r['id']==identifier),None)
        if row is None: raise ControlError('VALIDATION_FAILED',400)
        return row

    @staticmethod
    def name(value):
        if not isinstance(value,str) or not 1 <= len(value.strip()) <= 80 or any(ord(c)<32 for c in value):
            raise ControlError('VALIDATION_FAILED',400)
        return value.strip()

    def query(self, principal, body, mode):
        """Bounded, literal global search over fixed projections; never arbitrary SQL."""
        collections={'customers':'business_customers','workspaces':'business_workspaces','subscriptions':'business_subscriptions',
                     'payments':'business_payments','usage':'business_usage','tickets':'business_requests'}
        if set(body)!={'collection','search','status','page','recordId'}: raise ControlError('VALIDATION_FAILED',400)
        collection,search,status,page,record= (body[k] for k in ('collection','search','status','page','recordId'))
        if (not isinstance(collection,str) or collection not in collections or not isinstance(search,str) or len(search)>160 or
            not isinstance(status,str) or len(status)>40 or type(page) is not int or not 1<=page<=100000 or
            not isinstance(record,str) or len(record)>80): raise ControlError('VALIDATION_FAILED',400)
        size=50
        if mode=='demo':
            data=self.demo(principal)
            workspaces={w['id']:w for w in data['workspaces']}
            all_rows=data[collection]
            statuses=sorted({str(r.get('status',r.get('costState',''))) for r in all_rows})
            def matches(row):
                text=' '.join(str(row.get(k,'')) for k in ('id','name','title','plan','dimension','kind'))+' '+str(workspaces.get(row.get('workspaceId'),{}).get('name',''))
                return search.casefold() in text.casefold()
            rows=[r for r in all_rows if (not record or r['id']==record) and
                  (status=='all' or r.get('status',r.get('costState'))==status) and matches(r)]
            total=len(rows); rows=rows[(page-1)*size:page*size]
            return dict(mode=mode,rows=rows,workspaces=data['workspaces'],total=total,page=page,pageSize=size,statuses=statuses)
        if not {'customers.read','workspaces.read'} <= set(principal['operator']['capabilities']): raise ControlError('SCOPE_DENIED')
        if record:
            try: uuid.UUID(record)
            except ValueError: raise ControlError('VALIDATION_FAILED',400) from None
        view=sql.Identifier('rafii_control',collections[collection])
        status_column=sql.Identifier('costState' if collection=='usage' else 'status')
        # All identifiers and searchable expressions are chosen on the server.
        expressions={'customers':'concat_ws(\' \',r.id,r.name,r."workspaceIds"::text)',
                     'workspaces':'concat_ws(\' \',r.id,r.name,r.plan)',
                     'subscriptions':'concat_ws(\' \',r.id,r.plan,w.name)',
                     'payments':'concat_ws(\' \',r.id,w.name)',
                     'usage':'concat_ws(\' \',r.id,r.kind,r.dimension,w.name)',
                     'tickets':'concat_ws(\' \',r.id,r.title,w.name)'}
        join=sql.SQL('') if collection in ('customers','workspaces') else sql.SQL(' LEFT JOIN rafii_control.business_workspaces w ON w.id=r."workspaceId"')
        where=sql.SQL(' WHERE (%s=\'\' OR r.id=%s) AND (%s=\'all\' OR r.{}=%s) AND strpos(lower({}),lower(%s))>0').format(status_column,sql.SQL(expressions[collection]))
        values=(record,record,status,status,search)
        with self.store.transaction(read=True) as con:
            if collection=='payments' and not con.execute("SELECT to_regclass('rafii_control.business_payments') IS NOT NULL AS ready").fetchone()['ready']:
                raise ControlError('WORKSPACE_CONFIGURATION_REQUIRED',503)
            source=sql.SQL(' FROM {} r').format(view)+join+where
            total=con.execute(sql.SQL('SELECT count(*) AS total')+source,values).fetchone()['total']
            rows=serial(con.execute(sql.SQL('SELECT r.*')+source+sql.SQL(' ORDER BY r.id LIMIT %s OFFSET %s'),values+(size,(page-1)*size)).fetchall())
            statuses=[r['status'] for r in con.execute(sql.SQL('SELECT DISTINCT {} AS status FROM {} ORDER BY status').format(status_column,view)).fetchall()]
            linked=set()
            for r in rows:
                linked.update(r.get('workspaceIds',[]))
                if r.get('workspaceId'): linked.add(r['workspaceId'])
            workspaces=serial(con.execute('SELECT * FROM rafii_control.business_workspaces WHERE id=ANY(%s::text[]) ORDER BY id',(list(linked),)).fetchall()) if linked else []
        if collection=='workspaces' or workspaces:
            with self.store.transaction() as con:
                grants=con.execute('SELECT workspace_id FROM rafii_control.test_workspace_grants WHERE operator_id=%s AND environment=%s AND expires_at>now()',
                                   (self.identity(principal),self.store.environment)).fetchall()
            permitted={str(g['workspace_id']) for g in grants} if 'workspaces.test.rename' in principal['operator']['capabilities'] else set()
            for row in rows if collection=='workspaces' else workspaces: row['renameAllowed']=row['id'] in permitted
        return dict(mode=mode,rows=rows,workspaces=workspaces,total=total,page=page,pageSize=size,statuses=statuses)

    def live(self, principal):
        if not {'customers.read','workspaces.read'} <= set(principal['operator']['capabilities']): raise ControlError('SCOPE_DENIED')
        # All views below are fixed, column-allowlisted canonical projections.
        with self.store.transaction(read=True) as con:
            customers = serial(con.execute('SELECT * FROM rafii_control.business_customers ORDER BY id LIMIT 201').fetchall())
            workspaces = serial(con.execute("SELECT * FROM rafii_control.business_workspaces ORDER BY CASE WHEN status IN ('past_due','grace') THEN 0 ELSE 1 END,id LIMIT 201").fetchall())
            subscriptions = serial(con.execute('SELECT * FROM rafii_control.business_subscriptions ORDER BY id LIMIT 201').fetchall())
            usage = serial(con.execute('SELECT * FROM rafii_control.business_usage ORDER BY at DESC,id LIMIT 201').fetchall())
            requests = serial(con.execute('SELECT * FROM rafii_control.business_requests ORDER BY at DESC,id LIMIT 201').fetchall())
            counts = con.execute('SELECT (SELECT count(*) FROM rafii_control.business_customers) AS customers,(SELECT count(*) FROM rafii_control.business_workspaces) AS workspaces,(SELECT count(*) FROM rafii_control.business_workspaces WHERE status IN (\'past_due\',\'grace\')) AS "billingReviews",(SELECT count(*) FROM rafii_control.business_subscriptions WHERE status=\'active\') AS "activeSubscriptions",(SELECT count(*) FROM rafii_control.business_requests WHERE status=\'requested\') AS "openRequests"').fetchone()
            payments_ready = con.execute("SELECT to_regclass('rafii_control.business_payments') IS NOT NULL AS ready").fetchone()['ready']
            payments = serial(con.execute('SELECT * FROM rafii_control.business_payments ORDER BY at DESC,id LIMIT 201').fetchall()) if payments_ready else []
        with self.store.transaction() as con:
            grants = con.execute('SELECT workspace_id FROM rafii_control.test_workspace_grants WHERE operator_id=%s AND environment=%s AND expires_at>now()',
                                 (self.identity(principal),self.store.environment)).fetchall()
            activity = serial(con.execute('SELECT id,action AS label,target_id AS "workspaceId",at FROM rafii_control.workspace_actions WHERE environment=%s AND mode=\'live\' ORDER BY at DESC LIMIT 50',(self.store.environment,)).fetchall())
        permitted={str(g['workspace_id']) for g in grants} if 'workspaces.test.rename' in principal['operator']['capabilities'] else set()
        for w in workspaces: w['renameAllowed'] = w['id'] in permitted
        result = dict(mode='live',revision=0,customers=customers[:200],workspaces=workspaces[:200],subscriptions=subscriptions[:200],payments=payments[:200],usage=usage[:200],tickets=requests[:200],activity=activity,
                      summary=dict(counts),limits=dict(pageSize=200,truncated=any(len(r)>200 for r in (customers,workspaces,subscriptions,usage,requests,payments))),
                      paymentState='connected' if payments_ready else 'not_configured',supportState='metadata_only',usageState='connected')
        result['connections']=[dict(id='database',label='Rafii database',state='connected',required=True,detail='Canonical customer, workspace, subscription and usage metadata.'),
                               dict(id='payments',label='Payment records',state=result['paymentState'],required=True,detail='Stored credit-purchase receipts. Required billing connection; no charges or refunds from Control.'),
                               dict(id='credits',label='Credit balance',state='not_qualified',required=True,detail='Usage metadata is connected. Approved credit definitions and a balance projection are required before Live billing is qualified.'),
                               dict(id='support',label='Support',state='metadata_only',required=True,detail='Canonical data-request status is connected. Approved ticket access is required before the Live support workflow is qualified.')]
        return result

    def rename(self, principal, body):
        if set(body) != {'workspaceId','name','revision','requestId'} or type(body['revision']) is not int: raise ControlError('VALIDATION_FAILED',400)
        try:
            workspace, request = str(uuid.UUID(body['workspaceId'])),str(uuid.UUID(body['requestId']))
        except (ValueError,TypeError,AttributeError): raise ControlError('VALIDATION_FAILED',400) from None
        name = self.name(body['name'])
        try:
            with self.store.transaction() as con:
                return con.execute('SELECT rafii_control.rename_test_workspace(%s,%s,%s,%s,%s,%s,%s) AS result',
                                   (self.identity(principal),principal['session']['id'],self.store.environment,workspace,name,body['revision'],request)).fetchone()['result']
        except psycopg.errors.RaiseException as error:
            code = error.diag.message_primary
            if code in ('SCOPE_DENIED','STEP_UP_REQUIRED','STALE_PREVIEW','IDEMPOTENCY_CONFLICT'):
                raise ControlError(code,409 if code in ('STALE_PREVIEW','IDEMPOTENCY_CONFLICT') else 403) from None
            raise ControlError('SOURCE_UNAVAILABLE',503) from None
