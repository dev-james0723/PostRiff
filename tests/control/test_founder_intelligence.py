"""Preview services consume the coordinator's one Demo seed, never a second fixture."""
import copy
import importlib
import importlib.util
import json
import os
import socket
import sys
import unittest
import uuid
from unittest.mock import patch

from rafii_control.auth import ControlError

try:
    service = importlib.import_module('rafii_control.founder_intelligence')
except ModuleNotFoundError as error:
    if error.name != 'rafii_control.founder_intelligence': raise
    service = None

try:
    from rafii_control import demo_dataset as dataset
except ImportError:
    source = os.environ.get('RAFII_FOUNDER_DEMO_MODULE')
    if not source:
        raise RuntimeError('Run on the integrated Demo commit or set RAFII_FOUNDER_DEMO_MODULE to the coordinator-owned seed.')
    spec = importlib.util.spec_from_file_location('coordinator_demo_dataset', source)
    dataset = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dataset)
    sys.modules['rafii_control.demo_dataset'] = dataset


class FounderIntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = dataset.sample_data()

    def setUp(self):
        self.assertIsNotNone(service, 'Founder contextual service has not been implemented')
        self.data = copy.deepcopy(self.seed)
        self.principal = dict(operator=dict(user_id='00000000-0000-0000-0000-000000000001',
                                           role='founder', status='active', environment='local', auth_epoch=1,
                                           capabilities=['control.read', 'copilot.use', 'metrics.query','customers.read','workspaces.read']),
                              session=dict(id=str(uuid.uuid4()), environment='local', assurance='aal2', auth_epoch=1,
                                           revoked_at=None, expires_at=4102444800))

    def action(self, kind, payload=None, target='new'):
        request = dict(action=kind, targetId=target, value=json.dumps({} if payload is None else payload),
                       revision=self.data['revision'], requestId=str(uuid.uuid4()))
        return service.reduce_action(self.data, request, self.principal, now='2026-10-01T12:00:00Z')

    def turn(self, message='Which plan has the most subscribers?', conversation=None):
        return self.action('founder_turn', dict(message=message, conversationId=conversation,
                           chartContext=dict(chartId='plan-distribution', viewVersion=1,
                                             queryReceiptId=dataset.receipt(self.data)['id'],
                                             mode='demo', environment='local')))

    def test_exact_chart_receipt_and_10000_population_survive_persisted_conversation(self):
        run = self.turn()
        self.assertEqual(run['namespace'], 'founder')
        self.assertEqual(run['queryReceiptIds'], [dataset.receipt(self.data)['id']])
        self.assertEqual(run['evidenceRows'], self.data['analytics']['planDistribution'])
        self.assertIn('4,500', run['answerText'])
        self.assertIn('4,000', run['answerText'])
        self.assertIn('1,500', run['answerText'])
        self.assertEqual(run['usage']['providerCalls'], 0)
        restored = json.loads(json.dumps(self.data))
        view = service.preview_state(restored, self.principal)
        self.assertEqual(view['conversations'][0]['id'], run['conversationId'])
        self.assertEqual(view['conversations'][0]['turns'][0]['runId'], run['runId'])
        self.assertLess(len(json.dumps(view)), 60000)

    def test_cantonese_and_unknown_question_are_truthfully_labeled(self):
        run = self.turn('而家邊個 plan 最多 subscribers？列出每個 plan 嘅人數。')
        self.assertIn('4,500', run['answerText'])
        self.assertEqual(run['mode'], 'demo_simulation')
        unknown = self.turn('Predict next year profit and refund everyone', run['conversationId'])
        self.assertEqual(unknown['state'], 'blocked')
        self.assertEqual(unknown['changedEntities'], [])
        self.assertEqual(unknown['usage']['providerCalls'], 0)

    def test_context_receipt_environment_and_unknown_fields_cannot_override_evidence(self):
        good = dict(message='Explain this chart', conversationId=None,
                    chartContext=dict(chartId='plan-distribution', viewVersion=1,
                                      queryReceiptId='wrong-receipt', mode='demo', environment='local'))
        for payload in [good, {**good, 'operatorId':'attacker'}, {**good, 'chartContext':{**good['chartContext'], 'environment':'production'}}]:
            with self.subTest(payload=payload), self.assertRaises(ControlError):
                self.action('founder_turn', payload)
        self.assertNotIn('founderIntelligence', self.data)

    def test_founder_aal2_capability_and_actor_environment_isolation(self):
        self.turn()
        for change in ('role','assurance','capability','actor','environment','epoch','revoked'):
            principal = copy.deepcopy(self.principal)
            if change == 'role': principal['operator']['role']='workspace_admin'
            if change == 'assurance': principal['session']['assurance']='aal1'
            if change == 'capability': principal['operator']['capabilities'].remove('copilot.use')
            if change == 'actor': principal['operator']['user_id']=str(uuid.uuid4())
            if change == 'environment': principal['session']['environment']='staging'
            if change == 'epoch': principal['session']['auth_epoch']=2
            if change == 'revoked': principal['session']['revoked_at']=1
            with self.subTest(change=change), self.assertRaises(ControlError):
                service.preview_state(self.data, principal)
        live = {**self.data, 'mode':'live'}
        with self.assertRaises(ControlError): service.preview_state(live, self.principal)

    def test_reminder_draft_exact_confirmation_persistence_and_duplicate_identity(self):
        run = self.turn()
        draft = self.action('founder_reminder', dict(conversationId=run['conversationId'], intent='Review plan distribution',
                            dueLocal=None, timeZone='America/Indiana/Indianapolis', confirmed=False))
        self.assertEqual(draft['state'], 'draft')
        scheduled = self.action('founder_reminder', dict(conversationId=run['conversationId'], intent='Review plan distribution',
                                dueLocal='2026-10-02T09:00:00', timeZone='America/Indiana/Indianapolis', confirmed=True))
        self.assertEqual(scheduled['state'], 'scheduled')
        self.assertEqual(scheduled['dueAt'], '2026-10-02T13:00:00+00:00')
        self.assertFalse(scheduled['externalDelivery'])
        again = self.action('founder_reminder', dict(conversationId=run['conversationId'], intent='Review plan distribution',
                            dueLocal='2026-10-02T09:00:00', timeZone='America/Indiana/Indianapolis', confirmed=True))
        self.assertEqual(again['id'], scheduled['id'])
        self.assertEqual(len(self.data['founderIntelligence']['followUps']), 2)

    def test_connected_report_call_follow_up_and_durable_summary(self):
        run = self.turn()
        schedule = self.action('founder_report_schedule', dict(conversationId=run['conversationId'], kind='daily',
                              dueLocal='2026-10-02T09:00:00', timeZone='America/Indiana/Indianapolis', confirmed=True))
        self.assertEqual(schedule['state'], 'scheduled')
        report = service.preview_state(self.data,self.principal)['reports'][0]
        self.assertEqual(report['queryReceiptIds'],run['queryReceiptIds'])
        attempt = self.action('founder_delivery', dict(operation='start',channel='call',sourceId=report['id']))
        attempt = self.action('founder_delivery', dict(operation='advance',channel='call',sourceId=report['id'],
                             attemptId=attempt['id'],outcome='live'))
        follow = self.action('founder_follow_up',dict(attemptId=attempt['id'],message='Explain this chart'))
        self.assertEqual(follow['conversationId'],run['conversationId'])
        self.assertEqual(follow['queryReceiptIds'],run['queryReceiptIds'])
        self.action('founder_delivery',dict(operation='advance',channel='call',sourceId=report['id'],
                    attemptId=attempt['id'],outcome='completed'))
        summary = self.action('founder_summary',dict(conversationId=run['conversationId']))
        self.assertFalse(summary['humanAcknowledged'])
        restored = json.loads(json.dumps(self.data))
        self.assertEqual(service.preview_state(restored,self.principal)['summaries'][0]['id'],summary['id'])

    def test_stale_scenario_never_becomes_business_decline(self):
        run = self.turn()
        self.data.update(scenario='stale_data',dataState='stale')
        response = self.turn('What changed?',run['conversationId'])
        self.assertIn('stale',response['answerText'].lower())
        self.assertNotIn('decline',response['answerText'].lower())
        view=service.preview_state(self.data,self.principal)
        self.assertTrue(view['conversations'][0]['turns'][0]['historicalContext'])

    def test_sandbox_actions_have_no_real_egress_and_no_customer_debit(self):
        before = copy.deepcopy(self.data['credits'])
        with patch.object(socket,'create_connection',side_effect=AssertionError('real egress')):
            run=self.turn('Explain this chart')
            self.action('founder_voice',dict(conversationId=run['conversationId'],operation='start'))
            stopped=self.action('founder_voice',dict(conversationId=run['conversationId'],operation='stop'))
            self.assertEqual(stopped['state'],'stopped')
            self.assertFalse(stopped['liveVoiceConnected'])
        self.assertEqual(self.data['credits'],before)
        view=service.preview_state(self.data,self.principal)
        self.assertFalse(view['voiceReadiness']['live'])
        self.assertEqual(view['operationsCost']['costState'],'not_applicable')

    def test_workspace_extension_returns_false_only_for_an_unowned_action(self):
        unknown=dict(action='rename_workspace',targetId='workspace-1',value='A name',revision=1,requestId=str(uuid.uuid4()))
        self.assertFalse(service.apply_demo_action(self.data,unknown,self.principal))
        run=self.turn()
        snapshot=service.demo_snapshot(self.data,self.principal)['intelligence']
        self.assertEqual(snapshot['messages'][0]['role'],'user')
        self.assertEqual(snapshot['messages'][1]['role'],'assistant')
        self.assertEqual(snapshot['messages'][1]['receiptId'],run['queryReceiptIds'][0])

    def test_local_dst_fold_gap_and_no_unspecified_report_time(self):
        self.assertEqual(service.resolve_local_time('2026-03-08T02:30:00','America/New_York'),'2026-03-08T07:00:00+00:00')
        self.assertEqual(service.resolve_local_time('2026-11-01T01:30:00','America/New_York'),'2026-11-01T05:30:00+00:00')
        run=self.turn()
        with self.assertRaisesRegex(ControlError,'TIME_NOT_SELECTED'):
            self.action('founder_report_schedule',dict(conversationId=run['conversationId'],kind='daily',
                        dueLocal=None,timeZone='America/Indiana/Indianapolis',confirmed=True))
        self.assertEqual(service.preview_state(self.data,self.principal)['schedules'],[])

    def test_malformed_payloads_are_safe_validation_failures_without_partial_writes(self):
        run=self.turn()
        cases=[('founder_delivery',[]),('founder_voice',{'conversationId':run['conversationId'],'operation':[]}),
               ('founder_report_schedule',{'conversationId':run['conversationId'],'kind':[],
                  'dueLocal':None,'timeZone':'UTC','confirmed':False}),
               ('founder_turn',{'message':'Explain this chart','conversationId':None,'chartContext':{
                  'chartId':[],'viewVersion':1,'queryReceiptId':dataset.receipt(self.data)['id'],
                  'mode':'demo','environment':'local'}})]
        before=copy.deepcopy(self.data['founderIntelligence'])
        for kind,payload in cases:
            with self.subTest(kind=kind), self.assertRaises(ControlError): self.action(kind,payload)
        self.assertEqual(self.data['founderIntelligence'],before)

    def test_old_scenario_report_cannot_be_spoken_as_current_evidence(self):
        run=self.turn()
        schedule=self.action('founder_report_schedule',dict(conversationId=run['conversationId'],kind='daily',
                     dueLocal='2026-10-02T09:00:00',timeZone='America/Indiana/Indianapolis',confirmed=True))
        report=service.preview_state(self.data,self.principal)['reports'][0]
        call=self.action('founder_delivery',dict(operation='start',channel='call',sourceId=report['id']))
        self.action('founder_delivery',dict(operation='advance',channel='call',sourceId=report['id'],attemptId=call['id'],outcome='live'))
        self.data['scenario']='payment_failure'
        follow=self.action('founder_follow_up',dict(attemptId=call['id'],message='Explain this chart'))
        self.assertTrue(follow['historicalContext'])
        self.assertIn('historical',follow['answerText'].lower())
        self.assertEqual(follow['queryReceiptIds'],run['queryReceiptIds'])

    def test_scenario_outbox_preview_retry_recovery_share_one_incident(self):
        def scenario(value):
            action=dict(action='set_scenario',targetId='scenario',value=value,
                        revision=self.data['revision'],requestId=str(uuid.uuid4()))
            service.reduce_action(self.data,action,self.principal,now='2026-10-01T12:00:00Z')
        scenario('outage')
        view=service.preview_state(self.data,self.principal)
        self.assertEqual(view['incident']['affectedCount'],3)
        self.assertIn('DEMO',view['notifications'][0]['subject'])
        self.assertIn('simulated',view['notifications'][0]['html'].lower())
        self.assertNotIn('<img',view['notifications'][0]['html'])
        incident_id=view['incident']['id']
        scenario('notification_failure')
        view=service.preview_state(self.data,self.principal)
        self.assertEqual(view['notifications'][0]['state'],'failed')
        scenario('recovery')
        view=service.preview_state(self.data,self.principal)
        self.assertEqual(view['incident']['id'],incident_id)
        self.assertEqual(view['incident']['state'],'resolved')
        self.assertEqual(sum(n['kind']=='recovery' for n in view['notifications']),1)
        self.assertEqual(self.data['summary']['currentPaidSubscriptions'],10000)

    def test_read_snapshot_denies_intelligence_without_breaking_workspace_read(self):
        self.turn()
        principal=copy.deepcopy(self.principal)
        principal['operator']['capabilities'].remove('copilot.use')
        denied=service.demo_snapshot(self.data,principal)['intelligence']
        self.assertEqual(denied['code'],'SCOPE_DENIED')
        self.assertNotIn('conversations',denied)
        self.assertNotIn('messages',denied)

    def test_public_history_is_bounded_while_durable_history_is_preserved(self):
        conversation=None
        for i in range(60):
            if i==50: conversation=None
            run=self.turn('Explain this chart. '+'x'*1500,conversation)
            conversation=run['conversationId']
        raw=self.data['founderIntelligence']
        self.assertEqual(sum(len(c['turns']) for c in raw['conversations']),60)
        view=service.demo_snapshot(self.data,self.principal)
        combined={**dataset.bounded_snapshot(self.data),**view}
        self.assertLess(len(json.dumps(combined).encode()),480*1024)
        self.assertTrue(view['intelligence']['historyTruncated'])
        self.assertEqual(sum(len(c['turns']) for c in raw['conversations']),60)

    def test_replay_authorization_rechecks_current_grants_before_cached_output(self):
        run=self.turn()
        action=dict(action='founder_turn',targetId='founder',value='{}',revision=1,requestId=run['runId'])
        self.assertTrue(service.authorize_demo_action(self.data,action,self.principal))
        principal=copy.deepcopy(self.principal)
        principal['operator']['capabilities'].remove('copilot.use')
        with self.assertRaises(ControlError):service.authorize_demo_action(self.data,action,principal)

    def test_selected_customer_is_server_resolved_and_grant_rechecked_on_retrieval(self):
        payload=dict(message='Explain this customer',conversationId=None,chartContext=dict(
            chartId='plan-distribution',viewVersion=1,queryReceiptId=dataset.receipt(self.data)['id'],
            mode='demo',environment='local',selectedEntity={'collection':'customers','id':'customer-1'}))
        run=self.action('founder_turn',payload)
        self.assertIn('Maya Chen',run['answerText'])
        self.assertEqual(run['selectedEntityFacts']['id'],'customer-1')
        self.assertNotIn('email',run['selectedEntityFacts'])
        self.assertEqual(run['queryReceiptIds'],[dataset.receipt(self.data)['id']])
        for selection in ({'collection':'customers','id':'customer-missing'},
                          {'collection':'auth.users','id':'customer-1'},
                          {'collection':'customers','id':'customer-1','amountMinor':0}):
            with self.subTest(selection=selection),self.assertRaises(ControlError):
                self.action('founder_turn',{**payload,'chartContext':{**payload['chartContext'],'selectedEntity':selection}})
        principal=copy.deepcopy(self.principal)
        principal['operator']['capabilities'].remove('customers.read')
        with self.assertRaises(ControlError):service.preview_state(self.data,principal)
        replay=dict(action='founder_turn',targetId='founder',value=json.dumps(payload),
                    revision=self.data['revision'],requestId=run['runId'])
        with self.assertRaises(ControlError):service.authorize_demo_action(self.data,replay,principal)
        summary=dict(action='founder_summary',targetId='founder',value=json.dumps({'conversationId':run['conversationId']}),
                     revision=self.data['revision'],requestId=str(uuid.uuid4()))
        with self.assertRaises(ControlError):service.reduce_action(self.data,summary,principal)


if __name__ == '__main__': unittest.main()
