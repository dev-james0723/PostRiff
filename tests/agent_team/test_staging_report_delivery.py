"""Synthetic exact-staging in-app outbox tests. No provider or model calls."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_team_cutover import STAGING_PROJECT_ID
from postriff_phase2.agent_team_delivery import EVENT_TYPE, READY_TITLE, READY_DETAIL, TeamDeliveryService, delivery_plan
from postriff_phase2.notifications.service import NotificationService
from datetime import datetime, timezone

# Reuse the existing transactional SQL fixture; do not reproduce its planner.
_spec=importlib.util.spec_from_file_location('team_delivery_sql_fixture',Path(__file__).with_name('test_team_delivery.py'))
_fixture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture)
USER=_fixture.USER
OTHER=_fixture.OTHER


class StagingReportDeliveryTests(unittest.TestCase):
    def setup_delivery(self,**changes):
        document=_fixture.document();db=_fixture.FakeDatabase();db.seed(document);db.subscribed=False
        now=datetime.fromisoformat(document['generatedAt']).timestamp()
        values={'VERCEL_PROJECT_ID':STAGING_PROJECT_ID,'VERCEL_ENV':'production','JAMES_AGENT_TEAM_ENABLED':'0',
                'RAFII_NOTIFICATIONS_V2_ENABLED':'0','RAFII_WEB_PUSH_ENABLED':'0',**changes}
        service=SimpleNamespace(connection_factory=db,clock=lambda:now,public_base_url='https://rafii-consumer-staging.vercel.app',
            repository=SimpleNamespace(connection_factory=db),
            james_daily_call=SimpleNamespace(cfg=SimpleNamespace(user_id=USER,workspace_id=OTHER)))
        forbidden=Mock(side_effect=AssertionError('No transport may be called for in-app fallback'))
        transport=SimpleNamespace(send=forbidden)
        notifications=NotificationService(service,values,email_transport=transport,push_transport=transport,sms_transport=transport,clock=service.clock)
        service.notifications=notifications
        return document,db,service,notifications,forbidden

    def test_exact_staging_fallback_persists_real_in_app_receipt_and_preserves_public_switch(self):
        document,db,service,notifications,send=self.setup_delivery()
        with patch.object(notifications,'enabled',return_value=False):
            receipt=TeamDeliveryService(service).queue(document)
            reconciled=TeamDeliveryService(service).receipt(document)
            self.assertEqual(notifications.cron(),{'status':'disabled'})
            with self.assertRaises(AlphaError) as raised:notifications.center(OTHER,'human-session')
        self.assertEqual(raised.exception.code,'feature_disabled')
        self.assertEqual(receipt['deliveryState'],'in_app_available')
        self.assertFalse(receipt['generalNotificationCenterEnabled'])
        self.assertEqual(receipt['inAppReceiptSurface'],'private_agent_team_report')
        self.assertEqual(receipt['deliveries'][0]['proof'],'in_app_persisted')
        self.assertEqual(receipt['deliveries'][0]['status'],'delivered')
        self.assertFalse(receipt['notificationAcknowledged']);self.assertEqual(receipt['reportViewState'],'unverified')
        self.assertEqual(reconciled['eventId'],receipt['eventId'])
        self.assertEqual(len(db.data['events']),1);self.assertEqual(len(db.data['deliveries']),1)
        self.assertFalse(any(row['channel']!='in_app' for row in db.data['deliveries'].values()))
        send.assert_not_called()

    def test_preview_other_projects_and_emergency_disabled_remain_disabled(self):
        for changes in ({'VERCEL_ENV':'preview','JAMES_AGENT_TEAM_ENABLED':'1'},
                        {'VERCEL_PROJECT_ID':'prj_founder_production','JAMES_AGENT_TEAM_ENABLED':'1'},
                        {'VERCEL_PROJECT_ID':''},{'VERCEL_ENV':'development'},
                        {'JAMES_AGENT_TEAM_EMERGENCY_DISABLE':'1'},
                        {'JAMES_AGENT_TEAM_EMERGENCY_DISABLE':'true','JAMES_AGENT_TEAM_ENABLED':'1'}):
            with self.subTest(changes=changes):
                document,db,service,notifications,send=self.setup_delivery(**changes)
                with patch.object(notifications,'enabled',return_value=False):receipt=TeamDeliveryService(service).queue(document)
                self.assertEqual(receipt['effectState'],'disabled');self.assertEqual(receipt['failureClass'],'notifications_disabled')
                self.assertEqual(db.data['events'],{});self.assertEqual(db.data['deliveries'],{})
                send.assert_not_called()

    def test_whole_day_report_is_private_in_app_only(self):
        _document,db,service,notifications,send=self.setup_delivery()
        document=_fixture.document('whole_day');db.seed(document)
        service.clock=lambda:datetime.fromisoformat(document['generatedAt']).timestamp()
        notifications.clock=service.clock
        with patch.object(notifications,'enabled',return_value=False):
            receipt=TeamDeliveryService(service).queue(document)
        self.assertEqual(receipt['deliveryState'],'in_app_available')
        self.assertEqual([row['channel'] for row in receipt['deliveries']],['in_app'])
        self.assertEqual(receipt['inAppReceiptSurface'],'private_agent_team_report')
        send.assert_not_called()

    def test_normal_notification_enablement_retains_existing_emit_behavior(self):
        document,db,_service,notifications,send=self.setup_delivery(VERCEL_PROJECT_ID='prj_other')
        result={'eventId':'existing-normal-path','created':True}
        with patch.object(notifications,'enabled',return_value=True),patch.object(notifications,'emit',return_value=result) as normal_emit:
            self.assertEqual(notifications.emit_james_report_in_app(object(),document=document,event_type=EVENT_TYPE),result)
        normal_emit.assert_called_once();self.assertEqual(normal_emit.call_args.kwargs,{'event_type':EVENT_TYPE})
        self.assertEqual(db.history,[]);send.assert_not_called()

    def test_existing_in_app_opt_out_and_inactive_profile_are_not_overridden(self):
        for inactive in (False,True):
            document,db,service,notifications,send=self.setup_delivery()
            if inactive:db.profile=False
            else:db.prefs=[('*','automation',False,'off','off','off',None,None,'America/Indiana/Indianapolis',None,False,'off',False)]
            with patch.object(notifications,'enabled',return_value=False):receipt=TeamDeliveryService(service).queue(document)
            self.assertNotEqual(receipt['deliveryState'],'in_app_available')
            self.assertFalse(receipt['notificationAcknowledged'])
            if inactive:self.assertEqual(receipt['failureClass'],'notification_recipient_unavailable')
            else:self.assertEqual(receipt['deliveries'][0]['status'],'suppressed')
            send.assert_not_called()

    def test_disabled_effect_retries_once_but_submitted_unknown_and_confirmed_never_reemit(self):
        document,db,service,notifications,send=self.setup_delivery(JAMES_AGENT_TEAM_EMERGENCY_DISABLE='1')
        with patch.object(notifications,'enabled',return_value=False):disabled=TeamDeliveryService(service).queue(document)
        self.assertEqual(disabled['effectState'],'disabled')
        notifications.values['JAMES_AGENT_TEAM_EMERGENCY_DISABLE']='0'
        with patch.object(notifications,'enabled',return_value=False):
            first=TeamDeliveryService(service).queue(document);second=TeamDeliveryService(service).queue(document)
        self.assertEqual(first['eventId'],second['eventId']);self.assertEqual(len(db.data['events']),1)
        for state in ('submitted','unknown','confirmed'):
            document,db,service,notifications,send=self.setup_delivery()
            plan=delivery_plan(document,datetime.fromtimestamp(service.clock(),timezone.utc))
            db.data['effects'][plan['effectKey']]={'report_key':plan['reportKey'],'kind':'notification','state':state,'external_id':None,'failure_class':None}
            with patch.object(notifications,'enabled',return_value=False),patch.object(notifications,'emit_james_report_in_app',side_effect=AssertionError('Unknown effect must never fallback')):
                receipt=TeamDeliveryService(service).queue(document)
            self.assertEqual(receipt['deliveryState'],'reconciliation_required')
            self.assertEqual(db.data['events'],{});send.assert_not_called()

    def event(self,document,service):
        plan=delivery_plan(document,datetime.fromtimestamp(service.clock(),timezone.utc))
        return {'workspace_id':None,'user_id':USER,'actor':USER,'event_type':EVENT_TYPE,'dedupe_key':plan['dedupeKey'],
            'grouping_key':plan['groupingKey'],'entity_type':'agent_team_report','entity_id':document['fingerprint'],
            'payload':{'title':READY_TITLE,'detail':READY_DETAIL,'href':plan['href'],'count':document['version']},
            'channel_filter':plan['channels'],'expires_at':plan['expiresAt']}

    def test_fallback_rejects_changed_actor_workspace_event_entity_channels_and_manifest(self):
        document,db,service,notifications,send=self.setup_delivery()
        event=self.event(document,service)
        changes=({'actor':OTHER},{'user_id':OTHER},{'workspace_id':OTHER},{'event_type':'security.phone_call'},
                 {'entity_type':'other'},{'entity_id':'f'*64},{'channel_filter':('in_app','email')},
                 {'payload':{**event['payload'],'detail':'arbitrary private text'}})
        with patch.object(notifications,'enabled',return_value=False):
            for changed in changes:
                with db() as connection,connection.cursor() as cur,self.assertRaises(AlphaError) as raised:
                    notifications.emit_james_report_in_app(cur,document=document,**{**event,**changed})
                self.assertEqual(raised.exception.code,'agent_team_delivery_scope_mismatch')
            changed=copy.deepcopy(document);changed['summary']='Unstored report content'
            with db() as connection,connection.cursor() as cur,self.assertRaises(AlphaError) as raised:
                notifications.emit_james_report_in_app(cur,document=changed,**event)
            self.assertEqual(raised.exception.code,'agent_team_delivery_report_mismatch')
        self.assertEqual(db.data['events'],{});send.assert_not_called()

    def test_direct_fallback_requires_reserved_effect_and_exact_configured_james(self):
        document,db,service,notifications,send=self.setup_delivery()
        event=self.event(document,service)
        with patch.object(notifications,'enabled',return_value=False):
            with db() as connection,connection.cursor() as cur,self.assertRaises(AlphaError) as raised:
                notifications.emit_james_report_in_app(cur,document=document,**event)
            self.assertEqual(raised.exception.code,'agent_team_delivery_reconciliation_required')
            service.james_daily_call.cfg.user_id=None
            with db() as connection,connection.cursor() as cur:
                result=notifications.emit_james_report_in_app(cur,document=document,**event)
            self.assertTrue(result['disabled'])
        self.assertEqual(db.data['events'],{});send.assert_not_called()


if __name__=='__main__':unittest.main()
