import io
import json
import os
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from agent_team.periods import period
from agent_team.reports import report
from postriff_alpha.domain import AlphaError
from postriff_phase2.james_agent_team import PREFIX,route


VALUES={'JAMES_AGENT_TEAM_ENABLED':'1','JAMES_AGENT_TEAM_OBSERVER_TOKEN':'o'*40,
        'JAMES_AGENT_TEAM_READER_TOKEN':'r'*40,'JAMES_AGENT_TEAM_VERIFIER_TOKEN':'v'*40}


class AudioRouteTests(unittest.TestCase):
    def setUp(self):
        p=period('2026-10-04','whole_day');self.now=p.cutoff+timedelta(minutes=1)
        self.doc=report(p,[],self.now);self.doc['version']=1
        self.service=SimpleNamespace(clock=lambda:self.now.timestamp(),connection_factory=MagicMock())
        self.app=SimpleNamespace(_runtime=lambda:self.service,_json=lambda start,status,value,**kw:value)
        self.audio=MagicMock();self.store=MagicMock();self.store.get_report.return_value=self.doc
        self.headers=[]

    def invoke(self,tail,method='GET',token='o',payload=None):
        encoded=json.dumps(payload or {}).encode()
        environ={'HTTP_AUTHORIZATION':'Bearer '+token*40,'CONTENT_LENGTH':str(len(encoded)),
                 'wsgi.input':io.BytesIO(encoded),'QUERY_STRING':'version=1' if '/reports/' in tail else ''}
        with patch.dict(os.environ,VALUES,clear=True),patch('postriff_phase2.james_agent_team.TeamStore',return_value=self.store),patch('postriff_phase2.agent_team_audio.TeamAudioStore',return_value=self.audio):
            return route(self.app,environ,lambda status,headers:self.headers.extend(headers),method,PREFIX+tail)

    def test_observer_work_returns_exact_version_only_when_pending(self):
        self.audio.work.return_value={'state':'pending','reportKey':self.doc['period']['key'],
                                     'version':1,'fingerprint':self.doc['fingerprint']}
        result=self.invoke('/audio-work')
        self.assertEqual(result['state'],'ready');self.assertEqual(result['report'],self.doc)
        self.store.get_report.assert_called_once_with(self.doc['period']['key'],1)

    def test_idle_does_not_access_a_report_or_call(self):
        self.audio.work.return_value={'state':'no_due_report','audioState':'unavailable'}
        self.assertEqual(self.invoke('/audio-work')['state'],'idle');self.store.get_report.assert_not_called()

    def test_wrong_job_fingerprint_requires_reconciliation(self):
        self.audio.work.return_value={'state':'pending','reportKey':self.doc['period']['key'],
                                     'version':1,'fingerprint':'0'*64}
        with self.assertRaises(AlphaError) as caught:self.invoke('/audio-work')
        self.assertEqual(caught.exception.status,409)

    def test_reader_cannot_upload_or_fetch_observer_job(self):
        for tail,method in [('/audio','POST'),('/audio-work','GET')]:
            with self.assertRaises(AlphaError):self.invoke(tail,method,token='r')
        self.audio.put.assert_not_called();self.audio.work.assert_not_called()

    def test_reader_stream_is_private_and_binds_report_identity(self):
        self.audio.get.return_value=({'sha256':'a'*64,'narrationHash':'b'*64},b'fixture-wav')
        result=self.invoke('/reports/2026-10-04/whole_day/wav',token='r')
        self.assertEqual(result,[b'fixture-wav']);headers=dict(self.headers)
        self.assertEqual(headers['Cache-Control'],'private, no-store')
        self.assertEqual(headers['X-Agent-Team-Report-Fingerprint'],self.doc['fingerprint'])
        self.assertEqual(headers['X-Agent-Team-Report-Version'],'1')
        self.assertEqual(headers['X-Agent-Team-Audio-Sha256'],'a'*64)
        self.assertEqual(headers['X-Agent-Team-Audio-Narration-Sha256'],'b'*64)

    def test_missing_audio_is_404_without_affecting_report(self):
        self.audio.get.return_value=None
        with self.assertRaises(AlphaError) as caught:self.invoke('/reports/2026-10-04/whole_day/wav',token='r')
        self.assertEqual(caught.exception.status,404)

    def test_body_only_reaches_scoped_audio_store(self):
        self.audio.put.return_value={'state':'stored'}
        self.assertEqual(self.invoke('/audio','POST',payload={'fixture':'candidate'}),{'state':'stored'})
        self.audio.put.assert_called_once_with({'fixture':'candidate'})
