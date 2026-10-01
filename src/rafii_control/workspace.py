"""Founder business workspace. Canonical reads and isolated, per-founder Demo state.

No provider SDKs, customer messages or financial executors are imported here.
"""
from datetime import datetime, timezone
import copy
import re
import uuid
import json
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from .auth import ControlError
from .store import serial
from .demo_dataset import (sample_data, SCHEMA_VERSION, COLLECTIONS, PAGE_SIZE,
                           bounded_snapshot, linked_records, refresh_summary, receipt)


class WorkspaceService:
    def __init__(self, store): self.store = store

    def dispatch(self, path, body, principal, request_id):
        try:
            if path == '/workspace/live': return self.live(principal)
            if path == '/workspace/demo': return self.snapshot(principal)
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

    def snapshot(self, principal):
        return self._snapshot(self.demo(principal), principal)

    @staticmethod
    def _snapshot(data, principal):
        result = bounded_snapshot(data)
        # The separately owned Founder Intelligence slice remains a pure Demo extension.
        try:
            from .founder_intelligence import demo_snapshot
        except ModuleNotFoundError as error:
            if error.name != 'rafii_control.founder_intelligence': raise
        else:
            extension = demo_snapshot(data, principal)
            if isinstance(extension, dict):
                protected = set(result) | set(COLLECTIONS)
                result.update({key:value for key,value in extension.items() if key not in protected})
        if len(json.dumps(result, allow_nan=False).encode()) > 480 * 1024:
            raise ControlError('DEMO_RESPONSE_LIMIT',503)
        return result

    @staticmethod
    def _extension_action(data, action, principal):
        try:
            from .founder_intelligence import apply_demo_action
        except ModuleNotFoundError as error:
            if error.name != 'rafii_control.founder_intelligence': raise
            return False
        return bool(apply_demo_action(data, action, principal))

    def demo(self, principal, action=None):
        # Isolation is enforced by RLS and the verified principal, never a browser-supplied actor.
        with self.store.transaction() as con:
            actor = self.identity(principal)
            con.execute("SELECT set_config('rafii_control.operator',%s,true)",(actor,))
            # Reads take no row lock: a page fires several Demo reads at once, and a FOR UPDATE on this one large row made them
            # queue behind each other until the 10 s Control deadline answered 503. Actions and the one-time upgrade still lock.
            read = action is None
            select = ('SELECT payload,replays FROM rafii_control.demo_workspaces WHERE operator_id=%s AND environment=%s' if read else
                      'SELECT payload,replays FROM rafii_control.demo_workspaces WHERE operator_id=%s AND environment=%s FOR UPDATE')
            locked = 'SELECT payload,replays FROM rafii_control.demo_workspaces WHERE operator_id=%s AND environment=%s FOR UPDATE'
            row = con.execute(select, (actor,self.store.environment)).fetchone()
            # Do not generate or serialize all 10,000 records on each read.
            if row is None:
                con.execute('INSERT INTO rafii_control.demo_workspaces(operator_id,environment,payload) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                            (actor,self.store.environment,Jsonb(sample_data())))
                row = con.execute(select, (actor,self.store.environment)).fetchone()
            if read and row['payload'].get('schemaVersion') != SCHEMA_VERSION:
                row = con.execute(locked, (actor,self.store.environment)).fetchone()
            data, replays = row['payload'], row['replays']
            if data.get('schemaVersion') != SCHEMA_VERSION:
                previous_revision = data.get('revision', 0)
                data, replays = sample_data(), {}
                data['revision'] = previous_revision + 1
                data['manifest']['upgradedFromLegacyDemo'] = True
                con.execute('UPDATE rafii_control.demo_workspaces SET payload=%s,replays=%s WHERE operator_id=%s AND environment=%s',
                            (Jsonb(data),Jsonb(replays),actor,self.store.environment))
            data['receipt'] = receipt(data)
            if action is None: return data
            if set(action) != {'action','targetId','value','revision','requestId'}: raise ControlError('VALIDATION_FAILED',400)
            if (not isinstance(action['action'],str) or not isinstance(action['targetId'],str) or
                not re.fullmatch('[A-Za-z0-9-]{1,80}',action['targetId']) or not isinstance(action['value'],str) or len(action['value'].encode())>4000 or
                (action['action'] in ('reset','resolve_ticket','reopen_ticket','simulate_payment') and action['value']!='') or
                (action['action']=='reset' and action['targetId']!='all')): raise ControlError('VALIDATION_FAILED',400)
            try: key = str(uuid.UUID(action['requestId']))
            except (ValueError,TypeError,AttributeError): raise ControlError('VALIDATION_FAILED',400) from None
            # A replay remains subject to today's grants, even when its source revision is old.
            if action['action'].startswith('founder_') or action['action']=='set_scenario':
                from .founder_intelligence import authorize_demo_action
                authorize_demo_action(data, action, principal)
            replay = replays.get(key)
            if replay:
                if replay['request'] != action: raise ControlError('IDEMPOTENCY_CONFLICT',409)
                # Ordinary Demo mutations may also have cached optional AI history.
                # Keep their replay available, but redact that history after revocation.
                if replay['response'].get('intelligence'):
                    from .founder_intelligence import demo_snapshot
                    current = demo_snapshot(data, principal)['intelligence']
                    if current.get('code'):
                        response = copy.deepcopy(replay['response'])
                        response['intelligence'] = current
                        return response
                return replay['response']
            if type(action['revision']) is not int or action['revision'] != data['revision']: raise ControlError('STALE_PREVIEW',409)
            kind = action['action']
            if kind == 'reset':
                revision = data['revision']
                data = sample_data()
                data['revision'] = revision
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
                subscription = next((s for s in data['subscriptions'] if s['workspaceId']==target['workspaceId']), None)
                if subscription: subscription['status'] = 'active'
                if target.get('invoiceId'): self.target(data,'invoices',target['invoiceId'])['status'] = 'paid'
            elif not self._extension_action(data, action, principal): raise ControlError('SCOPE_DENIED')
            data['revision'] += 1
            refresh_summary(data)
            data['receipt'] = receipt(data)
            data['activity'].insert(0,dict(id=key,workspaceId=action['targetId'] if kind=='rename_workspace' else None,
                                         label={'reset':'Demo reset','rename_workspace':'Sample workspace renamed','resolve_ticket':'Sample request resolved','reopen_ticket':'Sample request reopened','simulate_payment':'Sample payment recorded'}.get(kind,'Demo sandbox action'),
                                         at=datetime.now(timezone.utc).isoformat(),dataState='simulated'))
            # Keep each customer's seeded timeline while bounding newly added activity.
            if len(data['activity'])>10050:
                next((data['activity'].pop(i) for i in range(len(data['activity'])-1,-1,-1)
                      if not str(data['activity'][i]['id']).startswith('activity-')), None)
            response = self._snapshot(data, principal)
            replays[key] = dict(request=action,response=copy.deepcopy(response))
            replays = dict(list(replays.items())[-20:])
            con.execute('UPDATE rafii_control.demo_workspaces SET payload=%s,replays=%s WHERE operator_id=%s AND environment=%s',
                        (Jsonb(data),Jsonb(replays),actor,self.store.environment))
            con.execute('INSERT INTO rafii_control.workspace_actions(operator_id,environment,mode,request_id,action,target_id) VALUES(%s,%s,\'demo\',%s,%s,%s)',
                        (actor,self.store.environment,key,kind,str(action['targetId'])[:160]))
            return response

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
        required = {'collection','search','status','page','recordId'}
        optional = {'plan','billingCycle','sort','direction'}
        if (not required <= set(body) or set(body)-required-optional or
            (mode!='demo' and set(body)!=required)): raise ControlError('VALIDATION_FAILED',400)
        collection,search,status,page,record= (body[k] for k in ('collection','search','status','page','recordId'))
        permitted_collections = COLLECTIONS if mode=='demo' else collections
        if (not isinstance(collection,str) or collection not in permitted_collections or not isinstance(search,str) or len(search)>160 or
            not isinstance(status,str) or len(status)>40 or type(page) is not int or not 1<=page<=100000 or
            not isinstance(record,str) or len(record)>80): raise ControlError('VALIDATION_FAILED',400)
        size=PAGE_SIZE
        if mode=='demo':
            data=self.demo(principal)
            workspaces={w['id']:w for w in data['workspaces']}
            customers={c['id']:c for c in data['customers']}
            plan,cycle,sort,direction=(body.get(k, default) for k,default in
                                      (('plan','all'),('billingCycle','all'),('sort','id'),('direction','asc')))
            plans = {p['id'] for p in data['catalog']['plans']} | {p['name'] for p in data['catalog']['plans']} | {'all'}
            sorts = {'id','name','company','email','status','plan','amountMinor','at','createdAt','renewsAt','creditsUsed','quantity'}
            if (not isinstance(plan,str) or plan not in plans or not isinstance(cycle,str) or cycle not in ('all','monthly') or
                not isinstance(sort,str) or sort not in sorts or direction not in ('asc','desc')):
                raise ControlError('VALIDATION_FAILED',400)
            all_rows=data[collection]
            statuses=sorted({str(r.get('status',r.get('costState',''))) for r in all_rows})
            def matches(row):
                workspace = row if collection=='workspaces' else workspaces.get(row.get('workspaceId'),{})
                customer = row if collection=='customers' else customers.get(row.get('customerId') or workspace.get('ownerId'),{})
                text=' '.join(str(row.get(k,'')) for k in ('id','name','company','email','number','title','plan','planId','dimension','kind'))
                text+=' '+' '.join(str(customer.get(k,'')) for k in ('id','name','company','email'))+' '+str(workspace.get('name',''))
                return search.casefold() in text.casefold()
            def filters(row):
                workspace = row if collection=='workspaces' else workspaces.get(row.get('workspaceId'),{})
                plan_id, plan_name = row.get('planId',workspace.get('planId')), row.get('plan',workspace.get('plan'))
                billing_cycle = row.get('billingCycle',workspace.get('billingCycle'))
                return (plan=='all' or plan in (plan_id,plan_name)) and (cycle=='all' or billing_cycle==cycle)
            rows=[r for r in all_rows if (not record or r['id']==record) and
                  (status=='all' or r.get('status',r.get('costState',''))==status) and matches(r) and filters(r)]
            numeric = sort in ('amountMinor','creditsUsed','quantity')
            def sort_key(row):
                if sort=='id':
                    return tuple((1,int(part)) if part.isdigit() else (0,part.casefold())
                                 for part in re.split(r'(\d+)',str(row['id'])))
                return (row.get(sort,0) or 0) if numeric else str(row.get(sort,'')).casefold()
            rows.sort(key=sort_key, reverse=direction=='desc')
            total=len(rows); rows=rows[(page-1)*size:page*size]
            linked=set()
            for row in rows:
                linked.update(row.get('workspaceIds',[]))
                if row.get('workspaceId'): linked.add(row['workspaceId'])
                if collection=='workspaces': linked.add(row['id'])
            response = dict(mode=mode,rows=copy.deepcopy(rows),workspaces=[copy.deepcopy(workspaces[key]) for key in sorted(linked) if key in workspaces][:size],
                            total=total,page=page,pageSize=size,statuses=statuses,revision=data['revision'],
                            scenario=data.get('scenario','normal'),asOf=receipt(data)['asOf'],receipt=receipt(data),
                            filters=dict(plan=plan,billingCycle=cycle,sort=sort,direction=direction),
                            _dataState='stale' if receipt(data)['dataState']=='stale' else 'synthetic',_receiptIds=[receipt(data)['id']])
            if record: response['linkedRecords']=linked_records(data,collection,rows)
            if len(json.dumps(response,allow_nan=False).encode())>480*1024: raise ControlError('DEMO_RESPONSE_LIMIT',503)
            return response
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
        result['connections']=[dict(id='database',label='Rafii database',state='connected',required=True,detail='Customer, workspace, subscription and usage records from Rafii.'),
                               dict(id='payments',label='Payment records',state=result['paymentState'],required=True,detail='Stored credit-purchase receipts. Required billing connection; no charges or refunds from Control.'),
                               dict(id='credits',label='Credit balance',state='not_qualified',required=True,detail='Usage records are connected. Credit balances need approved credit terms and a verified calculation before they can be shown.'),
                               dict(id='support',label='Support',state='metadata_only',required=True,detail='Account requests are connected. Customer conversations and replies need an approved support connection.')]
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
