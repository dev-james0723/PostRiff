"""Focused deterministic Demo contract checks; no network, provider or canonical writes."""
from collections import Counter
from contextlib import contextmanager
import copy
import hashlib
import json
import unittest
import uuid
from unittest.mock import patch

from rafii_control.auth import ControlError
from rafii_control.demo_dataset import (sample_data, bounded_snapshot, COLLECTIONS,
                                       SCHEMA_VERSION, seed_manifest, refresh_summary)
from rafii_control.workspace import WorkspaceService


class Cursor:
    def __init__(self, value): self.value=value
    def fetchone(self): return self.value


class DemoStore:
    """Transaction-shaped test double for only the isolated persistent JSONB boundary."""
    environment='local'

    def __init__(self): self.rows={}; self.actions=[]; self.actor=None; self.writes=0

    @contextmanager
    def transaction(self, **kwargs): yield self

    def execute(self, statement, values=()):
        statement=str(statement)
        if 'set_config' in statement:
            self.actor=values[0]
        elif statement.startswith('SELECT payload,replays'):
            assert values[0]==self.actor
            return Cursor(self.rows.get(tuple(values)))
        elif statement.startswith('INSERT INTO rafii_control.demo_workspaces'):
            assert values[0]==self.actor
            self.rows.setdefault(tuple(values[:2]),dict(payload=values[2].obj,replays={}))
            self.writes+=1
        elif statement.startswith('UPDATE rafii_control.demo_workspaces'):
            assert values[2]==self.actor
            self.rows[tuple(values[2:])]=dict(payload=values[0].obj,replays=values[1].obj)
            self.writes+=1
        elif statement.startswith('INSERT INTO rafii_control.workspace_actions'):
            self.actions.append(values)
        else:
            raise AssertionError('Demo service attempted an unexpected/canonical statement: '+statement)
        return Cursor(None)


class DemoDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.data=sample_data()

    def service(self):
        store=DemoStore()
        principal=dict(operator=dict(user_id='fictional-founder-1',capabilities=['control.read']))
        # New namespace fixtures share immutable baseline records in query-only tests.
        store.rows[(principal['operator']['user_id'],'local')]=dict(payload=self.data,replays={})
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
        other=sample_data()
        digest=lambda data:hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(digest(self.data),digest(other))
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
        with patch('rafii_control.workspace.sample_data',side_effect=AssertionError('read reseeded')):
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
        # Mutating tests use a fresh private payload, matching JSONB deserialization isolation.
        service.store.rows[(principal['operator']['user_id'],'local')]=dict(payload=copy.deepcopy(self.data),replays={})
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
        with patch('rafii_control.workspace.sample_data',return_value=copy.deepcopy(self.data)) as seed:
            service.demo(other)
            service.demo(other)
            self.assertEqual(seed.call_count,1)
        self.assertEqual(service.demo(other)['revision'],1)
        for stored in service.store.rows.values():
            for replay in stored['replays'].values():
                self.assertLess(len(json.dumps(replay['response']).encode()),512*1024)
                self.assertTrue(all(len(replay['response'][key])<=50 for key in COLLECTIONS))


if __name__ == '__main__': unittest.main()
