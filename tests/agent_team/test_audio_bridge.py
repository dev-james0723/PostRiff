import hashlib
import io
import tempfile
import unittest
import wave
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from agent_team.audio_bridge import produce_pending
from agent_team.events import canonical
from agent_team.periods import period
from agent_team.reports import report


class AudioBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();runtime=self.root/'.runtime';runtime.mkdir(mode=0o700)
        self.token=runtime/'cloud-ingress.token';self.token.write_text('x'*40);self.token.chmod(0o600)
        p=period('2026-10-04','whole_day');self.now=p.cutoff+timedelta(minutes=2)
        self.doc=report(p,[],self.now);self.doc['version']=1
        stable={k:v for k,v in self.doc.items() if k not in {'generatedAt','fingerprint','version','supplementOf','initialGeneratedAt'}}
        self.doc['fingerprint']=hashlib.sha256(canonical(stable).encode()).hexdigest()
        self.job={'reportKey':p.key,'fingerprint':self.doc['fingerprint'],'version':1,
                  'summaryHash':hashlib.sha256(self.doc['summary'].encode()).hexdigest()}
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(b'\x01\x00'*160)
        self.raw=buffer.getvalue();self.requests=[];self.generated=0

    def generator(self,document,*,canonical_root):
        self.generated+=1;target=canonical_root/'.runtime/audio'/f"{document['fingerprint']}.wav"
        target.parent.mkdir(mode=0o700,exist_ok=True);target.write_bytes(self.raw)
        return SimpleNamespace(delivery_eligible=True,execution_state='generated_local_audio',file_path=str(target))

    def request(self,url,token,payload=None):
        self.requests.append((url,payload))
        self.assertEqual(token,'x'*40)
        if payload is None:return {'state':'ready','job':self.job,'report':self.doc}
        return {'reportKey':payload['reportKey'],'fingerprint':payload['fingerprint'],'sha256':payload['sha256']}

    def invoke(self,**kw):
        return produce_pending('https://team.example/api/internal/james-agent-team/events',self.token,self.root,
                               now=self.now,request=kw.get('request',self.request),generate=kw.get('generate',self.generator))

    def test_exact_authenticated_job_and_immutable_asset_contract(self):
        result=self.invoke();self.assertEqual(result['state'],'stored');self.assertEqual(result['playback'],'not_verified')
        self.assertEqual([r[0] for r in self.requests],['https://team.example/api/internal/james-agent-team/audio-work','https://team.example/api/internal/james-agent-team/audio'])
        payload=self.requests[-1][1];self.assertEqual(payload['producer'],'macos_say_sinji')
        self.assertIn('narrationHash',payload);self.assertNotIn('summary',payload)

    def test_idle_does_not_generate_or_upload(self):
        result=self.invoke(request=lambda *a,**k:{'state':'idle'})
        self.assertEqual(result['state'],'idle');self.assertEqual(self.generated,0)

    def test_report_identity_mismatch_blocks_before_generation(self):
        self.job['fingerprint']='0'*64
        with self.assertRaisesRegex(ValueError,'identity_mismatch'):self.invoke()
        self.assertEqual(self.generated,0)

    def test_preview_never_becomes_cloud_audio(self):
        self.doc.pop('version');self.doc['fingerprint']=hashlib.sha256(canonical({k:v for k,v in self.doc.items() if k!='fingerprint'}).encode()).hexdigest()
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.generated,0)

    def test_synthetic_provenance_cannot_upload(self):
        def fake(*a,**k):return SimpleNamespace(delivery_eligible=False,execution_state='synthetic_audio_fixture')
        with self.assertRaisesRegex(ValueError,'not_real'):self.invoke(generate=fake)
        self.assertEqual(len(self.requests),1)

    def test_bad_acknowledgment_is_unverified(self):
        def wrong(url,token,payload=None):
            return self.request(url,token,payload) if payload is None else {'sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'acknowledgment'):self.invoke(request=wrong)

    def test_wrong_token_or_ingress_never_uses_network(self):
        for endpoint in ('http://team.example/api/internal/james-agent-team/events',
                         'https://team.example/api/internal/james-agent-team/events?token=x',
                         'https://other:secret@team.example/api/internal/james-agent-team/events'):
            with self.assertRaises(ValueError):produce_pending(endpoint,self.token,self.root,request=self.request)
        self.token.chmod(0o644)
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.requests,[])
