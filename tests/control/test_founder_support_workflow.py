"""Synthetic PostgreSQL workflow acceptance; no provider or customer traffic."""
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from control import test_founder_support_refunds as support_baseline
from postriff_phase2 import support
from rafii_control import founder_support
from rafii_control.auth import ControlError


class SupportWorkflowTests(unittest.TestCase):
    setUp = support_baseline.SupportRefundPostgresTests.setUp
    tearDown = support_baseline.SupportRefundPostgresTests.tearDown
    request = support_baseline.SupportRefundPostgresTests.request
    def create(self, message='Synthetic private body synthetic@example.test'):
        return support.customer(self.service, self.primary, self.user, 'POST', body={
            'requestId': str(uuid.uuid4()), 'category': 'technical', 'message': message})['ticket']

    def command(self, ticket, operation, **body):
        return self.request(operation, ticket['id'], {'requestId': str(uuid.uuid4()), 'revision': ticket['revision'], **body})

    def test_triage_is_idempotent_cas_guarded_content_free_and_immutable(self):
        ticket = self.create()
        body = {'requestId': str(uuid.uuid4()), 'revision': ticket['revision'], 'priority': 'urgent', 'assignee': 'me'}
        changed = self.request('triage', ticket['id'], body)
        self.assertEqual((changed['ticket']['priority'], changed['ticket']['assigneeId']), ('urgent', self.user))
        self.assertTrue(self.request('triage', ticket['id'], body)['duplicate'])
        with self.assertRaises(ControlError):
            self.request('triage', ticket['id'], {**body, 'priority': 'low'})
        with self.assertRaises(ControlError):
            self.request('triage', ticket['id'], {**body, 'requestId': str(uuid.uuid4())})
        events = founder_support.history(self.app, self.principal, {'match': (ticket['id'],)})['events']
        self.assertEqual([e['kind'] for e in events], ['created', 'triage'])
        self.assertNotIn('Synthetic private body', str(events))
        self.assertNotIn('synthetic@example.test', str(events))
        kept = self.command(changed['ticket'], 'triage', priority='high', assignee='keep')['ticket']
        self.assertEqual((kept['priority'], kept['assigneeId']), ('high', self.user))
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT has_table_privilege('service_role','public.pr_support_workflow_events','UPDATE'),has_table_privilege('service_role','public.pr_support_workflow_events','DELETE')").fetchone(), (False, False))
            self.assertTrue(db.execute("SELECT relforcerowsecurity FROM pg_class WHERE oid='public.pr_support_workflow_events'::regclass").fetchone()[0])
            db.execute('SET LOCAL ROLE rafii_control_reader')
            with self.assertRaises(Exception):
                db.execute('SELECT fingerprint FROM public.pr_support_workflow_events')
        with self.connect() as db:
            with self.assertRaises(Exception):
                db.execute('UPDATE public.pr_support_workflow_events SET to_priority=%s WHERE workspace_id=%s', ('low', self.primary))

    def test_duplicate_link_status_retry_cycle_and_reopen_preserve_original_messages(self):
        first, second = self.create(), self.create('Synthetic second original')
        body = {'requestId': str(uuid.uuid4()), 'revision': first['revision'], 'relation': 'duplicate', 'targetTicketId': second['id']}
        linked = self.request('link', first['id'], body)['ticket']
        self.assertEqual((linked['status'], linked['duplicateOfTicketId']), ('duplicate', second['id']))
        self.assertTrue(self.request('link', first['id'], body)['duplicate'])
        with self.assertRaises(ControlError):
            self.command(second, 'link', relation='duplicate', targetTicketId=first['id'])
        self.assertEqual(founder_support.list_tickets(self.app, self.principal, {})['metrics']['openTickets'], 1)
        reopened = support.customer(self.service, self.primary, self.user, 'POST', first['id'],
            {'requestId': str(uuid.uuid4()), 'message': 'Synthetic follow-up'})['ticket']
        self.assertEqual((reopened['status'], reopened['duplicateOfTicketId']), ('open', None))
        read = support.customer(self.service, self.primary, self.user, 'GET', first['id'])
        self.assertEqual(len(read['messages']), 2)
        self.assertEqual([e['kind'] for e in read['history']], ['created', 'duplicate_link', 'message'])
        self.assertEqual(founder_support.list_tickets(self.app, self.principal, {})['metrics']['openTickets'], 2)

    def test_concurrent_reciprocal_links_allow_only_one_acyclic_result(self):
        first, second = self.create(), self.create()
        def link(pair):
            source, target = pair
            try:
                self.command(source, 'link', relation='duplicate', targetTicketId=target['id'])
                return 'linked'
            except ControlError:
                return 'refused'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(link, [(first, second), (second, first)]))
        self.assertEqual(sorted(results), ['linked', 'refused'])
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM public.pr_support_workflow_events WHERE workspace_id=%s AND kind=%s', (self.primary, 'duplicate_link')).fetchone()[0], 1)

    def test_status_request_retry_and_verified_recurrence_are_distinct_source_events(self):
        first = self.create()
        body = {'requestId': str(uuid.uuid4()), 'revision': first['revision'], 'status': 'resolved'}
        resolved = self.request('status', first['id'], body)['ticket']
        self.assertIsNotNone(resolved['resolvedAt'])
        self.assertTrue(self.request('status', first['id'], body)['duplicate'])
        second = self.create()
        linked = self.command(second, 'link', relation='verified_recurrence', targetTicketId=first['id'])['ticket']
        self.assertEqual(linked['status'], 'open')
        self.assertIsNone(linked['duplicateOfTicketId'])
        events = founder_support.history(self.app, self.principal, {'match': (second['id'],)})['events']
        self.assertEqual(events[-1]['kind'], 'verified_recurrence')
        self.assertEqual(events[-1]['relatedTicketId'], first['id'])
        self.assertEqual(support.customer(self.service, self.primary, self.user, 'GET', first['id'])['ticket']['status'], 'resolved')

    def test_cross_tenant_links_and_internal_history_are_denied(self):
        first = self.create()
        with self.connect() as db:
            other_user = str(uuid.uuid4())
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (other_user,))
            other_workspace = str(db.execute("SELECT public.pr_bootstrap(%s,'studio')", (other_user,)).fetchone()[0])
        try:
            other = support.customer(self.service, other_workspace, other_user, 'POST', body={
                'requestId': str(uuid.uuid4()), 'category': 'other', 'message': 'Synthetic foreign original'})['ticket']
            with self.assertRaises(ControlError):
                self.command(first, 'link', relation='duplicate', targetTicketId=other['id'])
            from rafii_control import founder_ops
            ops = founder_ops.create_ops(self.app, self.principal, {'mode': 'live'})['workspaceId']
            internal = support.customer(self.service, ops, self.user, 'POST', body={
                'requestId': str(uuid.uuid4()), 'category': 'other', 'message': 'Synthetic internal original'})['ticket']
            with self.assertRaises(ControlError):
                founder_support.history(self.app, self.principal, {'match': (internal['id'],)})
        finally:
            with self.connect() as db:
                db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (other_workspace,))

    def test_linked_support_does_not_prevent_original_tenant_deletion(self):
        first, second = self.create(), self.create()
        self.command(first, 'link', relation='duplicate', targetTicketId=second['id'])
        with self.connect() as db:
            db.execute('DELETE FROM public.pr_workspaces WHERE id=%s', (self.primary,))
        with self.connect() as db:
            for table in ('pr_support_tickets', 'pr_support_messages', 'pr_support_workflow_events'):
                self.assertEqual(db.execute('SELECT count(*) FROM public.'+table+' WHERE workspace_id=%s', (self.primary,)).fetchone()[0], 0)

    def test_bounded_reads_show_latest_messages_and_history_and_disclose_earlier_records(self):
        ticket = self.create()
        for index in range(202):
            support.customer(self.service, self.primary, self.user, 'POST', ticket['id'],
                {'requestId': str(uuid.uuid4()), 'message': f'Synthetic recent message {index}'})
        customer = support.customer(self.service, self.primary, self.user, 'GET', ticket['id'])
        self.assertEqual(len(customer['messages']), 200)
        self.assertEqual(customer['messages'][-1]['body'], 'Synthetic recent message 201')
        self.assertTrue(customer['hasEarlierMessages'])
        self.assertEqual(len(customer['history']), 100)
        self.assertTrue(customer['hasEarlierEvents'])
        history = founder_support.history(self.app, self.principal, {'match': (ticket['id'],)})
        self.assertEqual(len(history['events']), 100)
        self.assertTrue(history['hasEarlierEvents'])
        self.assertEqual(history['events'][-1]['revision'], customer['ticket']['revision'])
        self.assertNotIn('Synthetic recent message', str(history))
        revealed = self.request('reveal', ticket['id'], {'confirmation': 'REVEAL', 'reasonCode': 'support_investigation'})
        self.assertEqual(revealed['messages'][-1]['body'], 'Synthetic recent message 201')
        self.assertEqual(len(revealed['messages']), 200)
        self.assertTrue(revealed['hasEarlierMessages'])


if __name__ == '__main__':
    unittest.main()
