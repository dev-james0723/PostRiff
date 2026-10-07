"""Focused deterministic Demo contract checks; no network, provider or canonical writes."""
from collections import Counter
from contextlib import contextmanager
import copy
import hashlib
import itertools
import json
import unittest
import uuid
from unittest.mock import patch

from rafii_control import workspace
from rafii_control.auth import ControlError
from rafii_control.demo_dataset import (sample_data, bounded_snapshot, COLLECTIONS, SCHEMA_VERSION, STORAGE, seed_manifest,
                                       refresh_summary, base, overlay, restore, own, own_records, expand_response)
from rafii_control.workspace import WorkspaceService


# Founder Intelligence actions and scenarios need an active founder with a step-up (aal2) session.
FOUNDER=dict(operator=dict(user_id='00000000-0000-0000-0000-0000000000f1',role='founder',status='active',environment='local',auth_epoch=1,
                           capabilities=['control.read','copilot.use','metrics.query','customers.read','workspaces.read']),
             session=dict(id='00000000-0000-0000-0000-0000000000e1',environment='local',assurance='aal2',auth_epoch=1,
                          revoked_at=None,expires_at=4102444800))


class Cursor:
    def __init__(self, value): self.value=value
    def fetchone(self): return self.value


class DemoStore:
    """Transaction-shaped test double for only the isolated persistent JSONB boundary. Like jsonb it keeps JSON text, every
    SELECT parses a fresh copy and every write is a new row version (xmin); `moved` counts the JSON bytes read and written."""
    environment='local'
    versions=itertools.count(1)   # never repeats across stores (like xmin), so the per-process read cache cannot mix them

    def __init__(self): self.rows={}; self.actions=[]; self.actor=None; self.writes=0; self.statements=[]; self.moved=0

    def put(self, actor, payload, replays=None):
        self.rows[(actor,self.environment)]=dict(payload=json.dumps(payload),replays=json.dumps(replays or {}),version=next(self.versions))

    def stored(self, actor):
        row=self.rows[(actor,self.environment)]
        return json.loads(row['payload']),json.loads(row['replays'])

    @contextmanager
    def transaction(self, **kwargs): yield self

    def execute(self, statement, values=()):
        statement=str(statement)
        self.statements.append(statement)
        if "set_config('rafii_control.operator'" in statement:
            self.actor=values[0]
        elif "set_config('statement_timeout'" in statement:
            assert 1 <= int(values[0]) <= 30_000, values   # the Demo row's statements stay deadline-bounded
        elif statement.startswith('SELECT xmin'):
            row=self.rows.get(tuple(values))
            return Cursor(dict(version=str(row['version'])) if row else None)
        elif statement.startswith('SELECT payload'):
            assert values[0]==self.actor
            row=self.rows.get(tuple(values))
            if row is None: return Cursor(None)
            columns=('payload','replays') if statement.startswith('SELECT payload,replays') else ('payload',)
            self.moved+=sum(len(row[column]) for column in columns)
            return Cursor({column:json.loads(row[column]) for column in columns})
        elif statement.startswith('INSERT INTO rafii_control.demo_workspaces'):
            assert values[0]==self.actor
            if tuple(values[:2]) not in self.rows:
                self.put(values[0],values[2].obj)
                self.moved+=len(self.rows[tuple(values[:2])]['payload'])
            self.writes+=1
        elif statement.startswith('UPDATE rafii_control.demo_workspaces'):
            assert values[2]==self.actor
            self.put(values[2],values[0].obj,values[1].obj)
            self.moved+=sum(len(self.rows[tuple(values[2:])][column]) for column in ('payload','replays'))
            self.writes+=1
        elif statement.startswith('INSERT INTO rafii_control.workspace_actions'):
            self.actions.append(values)
        else:
            raise AssertionError('Demo service attempted an unexpected/canonical statement: '+statement)
        return Cursor(None)


class DemoDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=sample_data()
        base()   # generated once per process; no read or action may regenerate it after this

    def setUp(self): workspace._DEMO_CACHE.clear()

    def same(self, actual, expected, message):
        # assertEqual would try to print a diff of 153,000 records on failure.
        self.assertTrue(actual==expected, message)

    @staticmethod
    def act(service, principal, kind, target, value=''):
        return service.demo(principal,dict(action=kind,targetId=target,value=value,revision=service.demo(principal)['revision'],
                                           requestId=str(uuid.uuid4())))

    def test_reads_take_no_row_lock_and_actions_do(self):
        # A page fires several Demo reads at once; a FOR UPDATE on the one large Demo row queued them past the deadline.
        store=DemoStore()
        service=WorkspaceService(store)
        principal=dict(operator=dict(user_id='fictional-founder-lock',capabilities=['control.read']))
        service.demo(principal)
        service.demo(principal)
        reads=[statement for statement in store.statements if statement.startswith('SELECT payload')]
        self.assertTrue(reads)
        self.assertFalse(any('FOR UPDATE' in statement for statement in reads), reads)
        store.statements.clear()
        revision=service.demo(principal)['revision']
        try:
            service.demo(principal, dict(action='reset', targetId='all', value='', revision=revision, requestId=str(uuid.uuid4())))
        except Exception:
            pass
        self.assertTrue(any(statement.startswith('SELECT payload') and 'FOR UPDATE' in statement for statement in store.statements), store.statements)

    def service(self):
        store=DemoStore()
        principal=dict(operator=dict(user_id='fictional-founder-1',capabilities=['control.read']))
        # A Demo that is still the shared base, exactly as a founder's first open stores it.
        store.put(principal['operator']['user_id'],overlay())
        return WorkspaceService(store),principal

    @staticmethod
    def body(**changes):
        return dict(collection='customers',search='',status='all',page=1,recordId='',**changes)

    def test_exact_paid_distribution_ids_provenance_and_fictional_addresses(self):
        data=self.data
        self.assertEqual(len(data['customers']),10000)
        self.assertEqual(len(data['subscriptions']),10000)
        self.assertEqual(Counter(s['planId'] for s in data['subscriptions']),
                         {'starter-v1':4500,'creator-v1':4000,'studio-v2':1500})
        self.assertTrue(all(s['paid'] and s['status']=='active' and s['billingCycle']=='monthly' for s in data['subscriptions']))
        for collection in COLLECTIONS:
            self.assertEqual(len(data[collection]),len({r['id'] for r in data[collection]}),collection)
        for collection in ('customers','members'):
            self.assertTrue(all(r['email'].endswith('@example.invalid') for r in data[collection]))
        self.assertFalse(data['catalog']['productionVerified'])
        self.assertEqual(data['catalog']['state'],'implemented_v2_candidate')
        self.assertEqual(data['manifest']['catalogSource']['migrationSha256'],
                         'a36357deb034fa32faac10ac9c893d5b09087f01c9689e072e8764adef792ba0')
        self.assertEqual([w['name'] for w in data['workspaces'][:3]],['Fern Studio','Northline Stories','Aisha Creates'])

    def test_all_customer_subscription_invoice_payment_usage_links_are_consistent(self):
        data=self.data
        customers={r['id']:r for r in data['customers']};workspaces={r['id']:r for r in data['workspaces']}
        subscriptions={r['id']:r for r in data['subscriptions']};invoices={r['id']:r for r in data['invoices']}
        payments={r['id']:r for r in data['payments']}
        for row in data['subscriptions']:
            customer,workspace=customers[row['customerId']],workspaces[row['workspaceId']]
            self.assertEqual(customer['subscriptionId'],row['id'])
            self.assertEqual(workspace['ownerId'],customer['id'])
            self.assertEqual(workspace['subscriptionId'],row['id'])
            self.assertIn(workspace['id'],customer['workspaceIds'])
            self.assertEqual(invoices[row['currentInvoiceId']]['status'],'paid')
        for invoice in data['invoices']:
            subscription=subscriptions[invoice['subscriptionId']]
            payment=payments[invoice['paymentId']]
            self.assertEqual(invoice['amountMinor'],subscription['amountMinor'])
            self.assertEqual(payment['invoiceId'],invoice['id'])
            self.assertEqual(payment['workspaceId'],invoice['workspaceId'])
        for collection in ('members','usage','credits','tickets','activity'):
            self.assertTrue(all(r['workspaceId'] in workspaces for r in data[collection]),collection)
        self.assertEqual(sum(r['quantity'] for r in data['credits']),data['summary']['creditsRemaining'])

    def test_seed_and_totals_are_deterministic_and_derived(self):
        # Every founder's Demo is an overlay on this dataset, so it must not depend on a clock, randomness or environment.
        other=sample_data()
        digest=lambda data:hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(digest(self.data),digest(other))
        self.assertEqual(digest(base()[0]),digest(other))
        expected=sum(s['amountMinor'] for s in self.data['subscriptions'])
        self.assertEqual(expected,59000000)
        self.assertEqual(self.data['summary']['mrrMinor'],expected)
        self.assertEqual(self.data['summary']['cashThisMonthMinor'],expected)
        self.assertEqual(sum(p['subscribers'] for p in self.data['analytics']['planDistribution']),10000)
        self.assertEqual(sum(p['mrrMinor'] for p in self.data['analytics']['planDistribution']),expected)
        self.assertTrue(all(point['revenueMinor']==expected and point['cashMinor']==expected
                            for point in self.data['analytics']['revenueTrend']))
        other['subscriptions'][0]['status']='past_due'
        refresh_summary(other)
        self.assertEqual(other['summary']['activeSubscriptions'],9999)
        self.assertEqual(other['summary']['currentPaidSubscriptions'],10000)
        self.assertEqual(other['summary']['mrrMinor'],expected-14900)

    def test_public_snapshot_is_bounded_without_reseeding_existing_state(self):
        service,principal=self.service()
        with patch('rafii_control.demo_dataset.sample_data',side_effect=AssertionError('read regenerated the dataset')):
            result=service.dispatch('/workspace/demo',{},principal,'read-only')
            second=service.dispatch('/workspace/demo',{},principal,'read-only')
        self.assertEqual(result,second)
        self.assertEqual(result['summary']['customers'],10000)
        self.assertEqual(result['limits']['collectionTotals']['invoices'],30000)
        self.assertTrue(all(len(result[key])<=50 for key in COLLECTIONS))
        self.assertLess(len(json.dumps(result).encode()),512*1024)
        self.assertEqual(result['_dataState'],'synthetic')
        self.assertEqual(result['receipt']['scenario'],'normal')
        self.assertEqual(service.store.writes,0)

    def test_stale_scenario_preserves_last_good_provenance_at_new_revision(self):
        data=copy.copy(self.data)
        last_good='2026-09-30T18:00:00Z'
        data.update(scenario='stale_data',sourceState='stale',lastGoodAsOf=last_good,
                    revision=7,asOf='2026-10-01T15:00:00Z')
        refresh_summary(data)
        snapshot=bounded_snapshot(data)
        for derived in (data['summary'],data['analytics'],*data['analytics']['revenueTrend']):
            self.assertEqual(derived['dataState'],'stale')
            self.assertEqual(derived['lastGoodAsOf'],last_good)
            self.assertEqual(derived['asOf'],last_good)
        self.assertEqual(data['summary']['mrrMinor'],self.data['summary']['mrrMinor'])
        self.assertEqual(snapshot['sourceState'],'stale')
        self.assertEqual(snapshot['_dataState'],'stale')
        self.assertEqual(snapshot['asOf'],last_good)
        self.assertEqual(snapshot['receipt']['dataState'],'stale')
        self.assertEqual(snapshot['receipt']['lastGoodAsOf'],last_good)
        self.assertEqual(snapshot['receipt']['asOf'],last_good)
        self.assertEqual(snapshot['receipt']['revision'],7)
        self.assertIn('-7-stale_data',snapshot['receipt']['id'])
        # Either stale signal is sufficient; an explicit recovery clears derived stale labels.
        data.update(scenario='normal',sourceState='stale')
        refresh_summary(data)
        self.assertEqual(data['summary']['dataState'],'stale')
        data.update(scenario='recovery',sourceState='healthy')
        refresh_summary(data)
        self.assertEqual(data['summary']['dataState'],'simulated')
        self.assertEqual(data['analytics']['asOf'],data['asOf'])
        self.assertNotIn('lastGoodAsOf',data['analytics'])

    def test_global_email_name_id_search_plan_cycle_status_sort_and_pagination(self):
        service,principal=self.service()
        query=self.body()
        first=service.query(principal,query,'demo')
        second=service.query(principal,{**query,'page':2},'demo')
        self.assertEqual(first['total'],10000)
        self.assertEqual(len(first['rows']),50)
        self.assertNotIn('customer-10000',{r['id'] for r in first['rows']})
        self.assertLessEqual(len(first['workspaces']),50)
        self.assertFalse({r['id'] for r in first['rows']} & {r['id'] for r in second['rows']})
        for search in ('subscriber.10000@example.invalid','customer-10000',self.data['customers'][-1]['company']):
            result=service.query(principal,{**query,'search':search},'demo')
            self.assertTrue(any(r['id']=='customer-10000' for r in result['rows']),search)
        creator=service.query(principal,{**query,'plan':'creator-v1','billingCycle':'monthly','status':'active'},'demo')
        self.assertEqual(creator['total'],4000)
        self.assertTrue(all(r['plan']=='Creator' for r in creator['rows']))
        invoices=service.query(principal,{**query,'collection':'invoices','sort':'amountMinor','direction':'desc'},'demo')
        self.assertEqual(invoices['rows'][0]['amountMinor'],14900)
        self.assertLess(len(json.dumps(invoices).encode()),512*1024)
        self.assertEqual(service.query(principal,{**query,'search':"%_'; DROP TABLE customers;--"},'demo')['total'],0)

    def test_customer_and_invoice_drilldowns_only_contain_related_records(self):
        service,principal=self.service()
        for collection,identifier in (('customers','customer-10000'),('invoices','invoice-10000')):
            result=service.query(principal,{**self.body(),'collection':collection,'recordId':identifier},'demo')
            linked=result['linkedRecords']
            self.assertEqual(len(result['rows']),1)
            self.assertEqual([r['id'] for r in linked['customers']],['customer-10000'])
            self.assertEqual([r['id'] for r in linked['workspaces']],['workspace-10000'])
            self.assertEqual(len(linked['invoices']),3)
            self.assertEqual(len(linked['payments']),3)
            self.assertEqual(len(linked['credits']),2)
            self.assertEqual(len(linked['tickets']),1)
            self.assertTrue(all(len(rows)<=50 for rows in linked.values()))
            self.assertLess(len(json.dumps(result).encode()),512*1024)

    def test_query_rejects_unsafe_options_and_live_authority_expansion(self):
        service,principal=self.service()
        for changes in ({'plan':'imaginary-v1'},{'billingCycle':'annual'},{'sort':'__class__'},
                        {'direction':'SIDEWAYS'},{'page':True},{'collection':'pr_workspaces'}, {'rawSql':'SELECT 1'}):
            with self.assertRaises(ControlError) as error:
                service.query(principal,{**self.body(),**changes},'demo')
            self.assertEqual(error.exception.status,400)
        for changes in ({'plan':'all'},{'billingCycle':'monthly'},{'sort':'id'},{'direction':'asc'},
                        {'collection':'invoices'}):
            with self.assertRaises(ControlError) as error:
                service.query(principal,{**self.body(),**changes},'live')
            self.assertEqual(error.exception.status,400)

    def test_seed_namespace_reset_revision_idempotency_and_bounded_replay(self):
        service,principal=self.service()
        revision=service.demo(principal)['revision']
        action=dict(action='rename_workspace',targetId='workspace-1',value='Demo renamed Fern',
                    revision=revision,requestId=str(uuid.uuid4()))
        first=service.demo(principal,action)
        self.assertEqual(first,service.demo(principal,action))
        self.assertEqual(service.demo(principal)['workspaces'][0]['name'],'Demo renamed Fern')
        with self.assertRaises(ControlError) as error: service.demo(principal,{**action,'value':'Conflicting retry'})
        self.assertEqual(error.exception.code,'IDEMPOTENCY_CONFLICT')
        with self.assertRaises(ControlError) as error: service.demo(principal,{**action,'requestId':str(uuid.uuid4())})
        self.assertEqual(error.exception.code,'STALE_PREVIEW')
        reset=dict(action='reset',targetId='all',value='',revision=first['revision'],requestId=str(uuid.uuid4()))
        result=service.demo(principal,reset)
        self.assertEqual(result['revision'],first['revision']+1)
        self.assertEqual(result['workspaces'][0]['name'],'Fern Studio')
        self.assertEqual(result['summary']['currentPaidSubscriptions'],10000)
        other=dict(operator=dict(user_id='fictional-founder-2',capabilities=['control.read']))
        writes=service.store.writes
        with patch('rafii_control.demo_dataset.sample_data',side_effect=AssertionError('regenerated for one founder')):
            service.demo(other)
            service.demo(other)
        self.assertEqual(service.store.writes,writes+1)   # one small row per founder, created on the first open
        self.assertEqual(service.demo(other)['revision'],1)
        for actor in ('fictional-founder-1','fictional-founder-2'):
            for replay in service.store.stored(actor)[1].values():
                response=expand_response(replay['response'])
                self.assertLess(len(json.dumps(response).encode()),512*1024)
                self.assertTrue(all(len(response[key])<=50 for key in COLLECTIONS))

    def test_first_open_and_actions_store_and_move_kilobytes(self):
        # The whole dataset is ~66 MB of JSON. A founder's row holds only what their actions changed.
        store=DemoStore()
        service=WorkspaceService(store)
        actor=FOUNDER['operator']['user_id']
        view=service.demo(FOUNDER)
        payload,replays=store.stored(actor)
        self.assertEqual((payload['storage'],payload['revision'],replays),(STORAGE,1,{}))
        self.assertLess(len(json.dumps(payload)),1024)
        self.assertLess(store.moved,4096)   # insert plus one read of the new row
        for key in self.data:
            if key!='receipt': self.same(view[key],self.data[key],key)
        for kind,target,value in (('rename_workspace','workspace-9999','Renamed sample'),('resolve_ticket','ticket-2',''),
                                  ('reopen_ticket','ticket-3',''),('set_scenario','scenario','payment_failure'),
                                  ('set_scenario','scenario','stale_data')):
            store.moved=0
            self.act(service,FOUNDER,kind,target,value)
            payload,replays=store.stored(actor)
            self.assertLess(len(json.dumps(payload)),200*1024,kind)
            self.assertLess(len(json.dumps(replays)),200*1024,kind)
            self.assertLess(store.moved,1024*1024,kind)
        # Another process's first read moves the founder's overlay only, never the replays.
        workspace._DEMO_CACHE.clear(); store.moved=0
        view=service.demo(FOUNDER)
        self.assertEqual(store.moved,len(store.rows[(actor,'local')]['payload']))
        self.assertEqual((view['workspaces'][9998]['name'],view['tickets'][1]['status'],view['tickets'][2]['status'],view['scenario']),
                         ('Renamed sample','completed','open','stale_data'))

    def test_reads_after_every_action_equal_the_dataset_the_action_produced(self):
        # The old row stored exactly the dataset an action produced; the overlay must restore exactly that dataset.
        store=DemoStore()
        service=WorkspaceService(store)
        actor=FOUNDER['operator']['user_id']
        produced=[]
        def record(data=None):
            if data is not None: produced[:]=[data]
            return overlay(data)
        def turn():
            context=dict(chartId='plan-distribution',viewVersion=1,queryReceiptId=service.demo(FOUNDER)['receipt']['id'],mode='demo',environment='local')
            return json.dumps(dict(message='Which plan has the most subscribers?',conversationId=None,chartContext=context))
        bounds={'cost_anomaly':512*1024,'normal':64*1024,'all':1024}   # cost_anomaly changes 1,000 usage records
        with patch('rafii_control.workspace.overlay',side_effect=record):
            for kind,target,value in (('rename_workspace','workspace-9999','Renamed sample'),('resolve_ticket','ticket-2',''),
                                      ('reopen_ticket','ticket-3',''),('founder_turn','founder',turn),
                                      ('set_scenario','scenario','payment_failure'),('set_scenario','scenario','stale_data'),
                                      ('set_scenario','scenario','outage'),('set_scenario','scenario','notification_failure'),
                                      ('set_scenario','scenario','recovery'),('set_scenario','scenario','cost_anomaly'),
                                      ('set_scenario','scenario','normal'),('reset','all','')):
                self.act(service,FOUNDER,kind,target,value() if callable(value) else value)
                view,expected=service.demo(FOUNDER),produced[0]
                self.assertEqual(set(view),set(expected),(kind,target))
                for key in expected: self.same(view[key],expected[key],(kind,value,key))
                self.assertLess(len(store.rows[(actor,'local')]['payload']),bounds.get(value or target,200*1024),(kind,value))
                if value=='normal': self.same(view['usage'],self.data['usage'],'normal restores every usage record the anomaly changed')
        for key in COLLECTIONS:   # reset restores the base; only its own activity entry is new
            self.same(view[key][1:] if key=='activity' else view[key],self.data[key],key)

    def test_shared_base_is_read_only_and_never_changed_by_any_founder(self):
        store=DemoStore()
        service=WorkspaceService(store)
        other=dict(FOUNDER,operator=dict(FOUNDER['operator'],user_id='00000000-0000-0000-0000-0000000000f2'))
        view=service.demo(FOUNDER)
        for write in (lambda: view['workspaces'][0].__setitem__('name','x'),lambda: view['workspaces'][0].update(name='x'),
                      lambda: view['activity'].insert(0,{}),lambda: view['customers'][0]['workspaceIds'].append('x'),
                      lambda: view['manifest'].pop('seed'),lambda: view['invoices'][0]['lineItems'][0].__setitem__('amountMinor',0)):
            with self.assertRaises(TypeError): write()
        row=copy.deepcopy(view['workspaces'][0])
        row['name']='A private copy'   # copies are ordinary, writable dicts again
        self.assertIs(type(row),dict)
        for kind,target,value in (('rename_workspace','workspace-1','Founder one only'),('resolve_ticket','ticket-1',''),
                                  ('set_scenario','scenario','payment_failure'),('set_scenario','scenario','cost_anomaly'),
                                  ('reset','all',''),('rename_workspace','workspace-1','Founder one only')):
            self.act(service,FOUNDER,kind,target,value)
        self.assertEqual(service.demo(FOUNDER)['workspaces'][0]['name'],'Founder one only')
        mine=service.demo(other)
        for key in COLLECTIONS: self.same(mine[key],self.data[key],key)
        self.same(base()[0],self.data,'the shared base still equals a freshly generated dataset')

    def test_overlay_round_trips_every_collection_shape(self):
        data=restore(overlay(),private=True)
        own(data['workspaces'],0)['name']='Patched'
        own(data['workspaces'],1).pop('renameAllowed')
        own(data['workspaces'],2)['extra']=dict(nested=[1,2])
        data['customers'].insert(0,dict(id='customer-new-head',name='Head'))
        data['customers'].append(dict(id='customer-new-tail',name='Tail'))
        del data['members'][100:110]
        del data['members'][-5:]
        data['tickets'].reverse()                    # a reordered collection is stored whole
        own(data['usage'],3)['$reserved']=True       # so is one whose record uses the delta's reserved key
        data['newKey']={'a':[1]}
        del data['usageState']
        payload=json.loads(json.dumps(overlay(data)))
        rows=payload['rows']
        self.assertEqual(set(rows),{'workspaces','customers','members','tickets','usage'})
        self.assertEqual(rows['workspaces'],dict(patch={'workspace-1':dict(name='Patched'),'workspace-2':{'$unset':['renameAllowed']},
                                                        'workspace-3':dict(extra=dict(nested=[1,2]))}))
        self.assertEqual((len(rows['customers']['head']),len(rows['customers']['tail'])),(1,1))
        self.assertEqual((len(rows['members']['drop']),rows['members']['stop']),(10,len(self.data['members'])-5))
        self.assertEqual((len(rows['tickets']['rows']),len(rows['usage']['rows'])),(10000,10000))
        self.assertEqual((payload['set'],payload['unset']),({'newKey':{'a':[1]}},['usageState']))
        for private in (False,True):
            restored=restore(payload,private=private)
            self.assertEqual(set(restored),set(data))
            for key in data:
                if key!='receipt': self.same(restored[key],data[key],(private,key))
        copied=restore(overlay(),private=True)
        own_records(copied)   # private copies of unchanged records are not changes
        self.assertEqual(overlay(copied),overlay())
        for broken in (dict(overlay(),seed='another-seed'),dict(overlay(),schemaVersion='rafii-admin-demo-v0'),
                       dict(overlay(),rows=dict(workspaces=dict(patch={'workspace-unknown':{}}))),self.data):
            with self.assertRaises(ValueError): restore(broken)

    def test_legacy_full_dataset_row_becomes_an_overlay_keeping_founder_changes(self):
        store=DemoStore()
        service=WorkspaceService(store)
        principal=dict(operator=dict(user_id='fictional-founder-legacy',capabilities=['control.read']))
        actor=principal['operator']['user_id']
        legacy=sample_data()
        legacy['workspaces'][0]['name']='Legacy renamed'
        legacy['tickets'][1]['status']='completed'
        legacy['payments'][0]['status']='pending'
        legacy['revision']=5
        refresh_summary(legacy)
        request=dict(action='resolve_ticket',targetId='ticket-2',value='',revision=4,requestId=str(uuid.uuid4()))
        response=bounded_snapshot(legacy)
        store.put(actor,legacy,{request['requestId']:dict(request=request,response=response)})
        del legacy
        view=service.demo(principal)
        self.assertEqual((view['revision'],view['workspaces'][0]['name'],view['tickets'][1]['status'],view['payments'][0]['status']),
                         (5,'Legacy renamed','completed','pending'))
        payload,replays=store.stored(actor)
        self.assertEqual(payload['storage'],STORAGE)
        self.assertLess(len(json.dumps(payload)),200*1024)
        self.assertTrue(all(set(replays[request['requestId']]['response'][key])=={'$page'} for key in COLLECTIONS))
        self.assertEqual(service.demo(principal,request),response)   # the legacy replay still returns its original response
        self.act(service,principal,'simulate_payment','payment-1')
        view=service.demo(principal)
        self.assertEqual([view[name][0]['status'] for name in ('payments','workspaces','subscriptions','invoices')],
                         ['funded','active','active','paid'])
        # A row of another schema version restarts from the base at its next revision, as before.
        store.put(actor,dict(mode='demo',schemaVersion='rafii-admin-demo-v0',revision=8),{request['requestId']:dict(request=request,response={})})
        view=service.demo(principal)
        self.assertEqual((view['revision'],view['manifest'].get('upgradedFromLegacyDemo'),view['workspaces'][0]['name']),(9,True,'Fern Studio'))
        self.assertEqual(store.stored(actor)[1],{})
        self.assertLess(len(store.rows[(actor,'local')]['payload']),4096)

    def test_replays_store_compact_pages_and_return_the_original_response(self):
        service,principal=self.service()
        action=dict(action='rename_workspace',targetId='workspace-3',value='Replay check',revision=service.demo(principal)['revision'],
                    requestId=str(uuid.uuid4()))
        first=service.demo(principal,action)
        stored=service.store.stored(principal['operator']['user_id'])[1][action['requestId']]['response']
        self.assertTrue(all(set(stored[key])=={'$page'} for key in COLLECTIONS))
        self.assertLess(len(json.dumps(stored)),16*1024)   # the pages are ~200 KB of the ~210 KB response
        again=service.demo(principal,action)
        self.assertEqual(again,first)
        self.assertEqual(again['workspaces'][2]['name'],'Replay check')
        again['workspaces'][2]['name']='Changed by a caller'   # a replay is the caller's own copy
        self.assertEqual(service.demo(principal,action),first)

    def test_cached_reads_follow_the_row_version(self):
        service,principal=self.service()
        first=service.demo(principal)
        reads=lambda: sum(statement.startswith('SELECT payload') for statement in service.store.statements)
        count=reads()
        self.assertEqual(service.demo(principal)['revision'],first['revision'])
        self.assertEqual(reads(),count)   # served from this process's cache while the row version is unchanged
        self.act(service,principal,'rename_workspace','workspace-1','Cache check')
        self.assertEqual(service.demo(principal)['workspaces'][0]['name'],'Cache check')
        self.assertEqual(first['workspaces'][0]['name'],'Fern Studio')   # an earlier read's view is never changed by an action


if __name__ == '__main__': unittest.main()
