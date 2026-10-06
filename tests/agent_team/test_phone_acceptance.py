"""Synthetic staged HTTP/owner/observer fixtures. No real call or network."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from agent_team.phone_acceptance import BASE, PhoneAcceptance, delivered_native_event
from agent_team.events import Event, Journal

AID='11111111-2222-3333-4444-555555555555'
CALL='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
NOW=1791315000.0


class PhoneAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        runtime=self.root/'.runtime';runtime.mkdir(mode=0o700)
        p=runtime/'cloud-verifier.token';p.write_text('synthetic-verifier-credential-00000');p.chmod(0o600)
        p=self.root/'native-result.json';p.write_text(json.dumps({'nativeState':'finished','observedAt':NOW-20}));p.chmod(0o600)
        self.request=Mock(side_effect=[{'state':'generated','executionMode':'staging_acceptance','reportKey':
            'agent-team:acceptance:v1:2026-10-06:'+AID+':half_day','reportId':'a'*64,'version':1,'evidenceCount':1},
            {'id':CALL,'state':'dialing'}])
        self.evidence=Mock(return_value='e'*64)
    def runner(self, **kwargs):
        options=dict(request=self.request,evidence=self.evidence,clock=lambda:NOW);options.update(kwargs)
        return PhoneAcceptance(self.root,self.root,AID,'mission-1',**options)
    def test_one_real_request_path_per_identity_and_no_resend_or_completion_claim(self):
        runner=self.runner();result=runner.once()
        self.assertEqual(result['state'],'call_submitted');self.assertFalse(result['humanAnswered'])
        self.assertFalse(result['nativeResumed']);self.assertEqual(self.request.call_count,2)
        self.assertEqual(self.request.call_args.args[0],BASE+'/acceptance/'+AID+'/call')
        self.assertEqual(self.request.call_args.args[2],{'missionId':'mission-1'})
        self.assertEqual(runner.once()['callRunId'],CALL);self.assertEqual(self.request.call_count,2)
    def test_normal_ingress_and_quiet_hours_precede_all_network_effects(self):
        self.evidence.return_value=None
        self.assertEqual(self.runner().once()['state'],'waiting_for_normal_native_ingress')
        self.request.assert_not_called()
        self.assertEqual(self.runner(clock=lambda:1791349200).once()['state'],'quiet_hours_deferred')
        self.request.assert_not_called();self.assertFalse((self.root/'phone-acceptance-intent.json').exists())
    def test_unknown_call_and_generation_failures_hold_intent_without_resend(self):
        self.request.side_effect=[self.request.side_effect.__next__(),TimeoutError('private provider body')]
        runner=self.runner();result=runner.once()
        self.assertEqual(result['state'],'call_outcome_unknown_no_resend')
        runner.once();self.assertEqual(self.request.call_count,2)
        self.assertNotIn('private provider', (self.root/'phone-acceptance-intent.json').read_text())
    def test_invalid_snapshot_cannot_contact_phone_route(self):
        self.request.side_effect=None;self.request.return_value={'state':'generated','reportKey':'historical-report'}
        self.assertEqual(self.runner().once()['state'],'report_outcome_unverified_no_call')
        self.assertEqual(self.request.call_count,1)
    def test_existing_other_identity_cannot_be_reused(self):
        runner=self.runner();runner.once()
        other=PhoneAcceptance(self.root,self.root,CALL,'mission-1',request=self.request)
        with self.assertRaisesRegex(Exception,'intent_changed'):other.once()
        self.assertEqual(self.request.call_count,2)
    def test_delivered_native_evidence_requires_exact_mission_and_normal_ack(self):
        j=Journal(self.root/'.runtime/journal.sqlite3');self.addCleanup(j.close)
        at='2026-10-06T19:30:00Z';observed='2026-10-06T19:30:10Z';delivered='2026-10-06T19:30:11Z'
        event=Event('claude','native','v1',at,observed,{'kind':'claude_usage_counters'},mission_id='mission-1')
        j.ingest([event])
        now=1791315020
        self.assertIsNone(delivered_native_event(self.root,'mission-1',now-30,now))
        j.acknowledge([event.key],delivered)
        self.assertEqual(delivered_native_event(self.root,'mission-1',now-30,now),event.key)
        self.assertIsNone(delivered_native_event(self.root,'other',now-30,now))
        self.assertIsNone(delivered_native_event(self.root,'mission-1',now,now))


if __name__=='__main__':unittest.main()
