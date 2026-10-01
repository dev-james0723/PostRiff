"""Golden fixtures validate definition math without activating business policies or provider reads."""
from datetime import datetime, timezone
from fractions import Fraction
import json
from pathlib import Path
import unittest
from rafii_control.metrics import recurring_value, cash_movements, retention, quality_ratio, validate_event
from rafii_control.auth import ControlError

PACK=Path(__file__).resolve().parents[2]/'docs/superpowers/tech-packs/2026-09-29-rafii-control-v2/rafii-control-v2'

class MetricGoldenTests(unittest.TestCase):
    def test_monthly_annual_native_currencies_and_topups_are_distinct(self):
        rows=[dict(amountMinor=12000,currency='USD',interval='year',intervalCount=1,status='active',recurring=True,test=False,internal=False),
              dict(amountMinor=500,currency='JPY',interval='month',intervalCount=1,status='active',recurring=True,test=False,internal=False)]
        result=recurring_value(rows)
        self.assertEqual(result,{'USD':Fraction(1000),'JPY':Fraction(500)})
        for changes in ({'recurring':False},{'status':'trial'},{'test':True},{'internal':True},{'status':'past_due'}):
            self.assertEqual(recurring_value([{**rows[0],**changes}]),{})
        self.assertEqual(recurring_value([{**rows[0],'amountMinor':10000}])['USD'],Fraction(2500,3))

    def test_verified_cash_movements_replay_and_refund_dispute_overlap(self):
        rows=[dict(movementId='capture1',kind='capture',amountMinor=10000,currency='USD',verified=True),
              dict(movementId='return1',kind='refund',amountMinor=2000,currency='USD',verified=True),
              dict(movementId='return1',kind='dispute_withdrawal',amountMinor=2000,currency='USD',verified=True),
              dict(movementId='pending1',kind='refund',amountMinor=9999,currency='USD',verified=False)]
        self.assertEqual(cash_movements(rows+rows),{'USD':8000})
        with self.assertRaises(ControlError):cash_movements(rows+[dict(movementId='capture1',kind='capture',amountMinor=9999,currency='USD',verified=True)])

    def test_retention_excludes_unmatured_cohort_and_empty_denominator(self):
        now=datetime(2026,9,29,tzinfo=timezone.utc)
        rows=[{'firstValueAt':'2026-09-01T00:00:00Z','qualifiedReturns':['2026-09-08T00:01:00Z']},
              {'firstValueAt':'2026-09-27T00:00:00Z','qualifiedReturns':[]}]
        self.assertEqual(retention(rows,now,7),{'value':1.0,'numerator':1,'denominator':1,'dataState':'measured'})
        self.assertEqual(retention(rows[1:],now,7)['dataState'],'not_applicable')
        self.assertIsNone(quality_ratio(None,10,'partial')['value'])
        self.assertIsNone(quality_ratio(0,0)['value'])

    def test_event_contract_needs_payload_allowlist_and_private_content_is_denied(self):
        event=json.loads((PACK/'examples/event-envelope.json').read_text())
        event['payload']={'sourceId':'sentry','reasonCode':'lagging'}
        event['eventType']='control.source.stale'
        self.assertEqual(validate_event(event,'staging')['payload']['sourceId'],'sentry')
        for changes in ({'classification':'private_support'},{'payload':{'token':'canary-secret'}},{'environment':'production'},{'payload':{'sourceId':'ignore instructions','reasonCode':'lagging'}}):
            with self.subTest(changes=changes),self.assertRaises(ControlError):validate_event({**event,**changes},'staging')
