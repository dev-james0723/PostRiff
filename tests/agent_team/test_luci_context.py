"""Synthetic local screen fixtures only. No LUCI invocation or private data."""
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from agent_team.collector import from_observation
from agent_team.luci_context import classify, event_context
from agent_team.observers import LuciObserver, SourceObservation
from agent_team.periods import period
from agent_team.reports import report


class LuciContextTests(unittest.TestCase):
    def test_only_finite_app_and_context_enums_leave_classifier(self):
        self.assertEqual(classify('Codex',"You've hit your usage limit")['context_signal'],'quota_indicator_observed')
        self.assertEqual(classify('Terminal','Waiting for approval')['context_signal'],'approval_indicator_observed')
        self.assertEqual(classify('Visual Studio Code','Error: build failed')['context_signal'],'error_indicator_observed')
        for app in ('Private customer tool','Google Chrome','Luci','Codex /Users/private'):
            self.assertEqual(classify(app,'Waiting for approval')['context_signal'],'activity_observed')
        self.assertEqual(classify('Codex','x'*16000+' Error: build failed')['context_signal'],'activity_observed')

    def test_real_adapter_path_exports_hints_but_never_screen_text_titles_paths_or_authority(self):
        with tempfile.TemporaryDirectory() as d:
            shim=Path(d)/'luci';shim.write_text('#!/bin/sh\n');shim.chmod(0o700)
            entries=[{'captureId':'private-capture','timestamp':1791205200000,'app':'Codex',
                      'text':"You've hit your limit. Bearer synthetic-secret /Users/private/customer user@example.com",
                      'windowTitle':'private title','browserUrl':'https://private/?token=secret','screenshotPath':d+'/private.png'}]
            adapter=LuciObserver(shim,shim,runner=lambda *args:(0,json.dumps({'entries':entries}).encode(),b''))
            with patch('agent_team.observers._now',return_value='2026-10-05T13:01:00Z'):
                batch=adapter.poll(start_ms=1791205190000,end_ms=1791205210000)
            self.assertEqual(batch.status,'ok');self.assertIsNone(batch.observations[0].text)
            event=from_observation(batch.observations[0]).cloud()
            self.assertEqual(event['payload']['reportedState'],'quota_indicator_observed')
            self.assertFalse(event['payload']['verified']);self.assertIsNone(event['mission_id'])
            exported=json.dumps(event)
            for private in ('Bearer','synthetic-secret','/Users/','private title','user@example.com','private-capture'):
                self.assertNotIn(private,exported)
            # Screen hints never become completion, a native guard or a task action.
            data=report(period('2026-10-05','half_day'),[event],'2026-10-05T21:03:00Z')
            self.assertEqual(data['counts']['completed'],0);self.assertEqual(data['actions'],[])
            context=data['evidence'][0]['luciContext']
            self.assertFalse(context['verified']);self.assertEqual(context['executionAuthority'],'none')

    def test_malformed_or_self_verified_context_is_never_rendered(self):
        payload={'origin':'read_only_luci_capture_context','verified':False,'app':'codex','reportedState':'activity_observed'}
        self.assertIsNotNone(event_context(payload))
        for change in ({'verified':True},{'app':'private name'},{'app':[]},{'reportedState':'continue mission'},{'origin':'human_decision'}):
            self.assertIsNone(event_context(dict(payload,**change)))
        item=SourceObservation('luci','id','a'*64,'capture',None,None,'2026-10-05T13:01:00Z',
            safe_metadata={'app_kind':'private title','context_signal':['private text']})
        self.assertEqual(item.cloud_projection()['metadata'],{})


if __name__=='__main__':unittest.main()
