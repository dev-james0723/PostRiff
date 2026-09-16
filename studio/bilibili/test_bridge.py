import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import server
import upload_task

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name).resolve() / 'private'
        server.IDENTITY = None
        server.ACTIVE = False
        self.client = TestClient(server.app, base_url='http://127.0.0.1:4387', raise_server_exceptions=False)
        self.headers = {'Origin': 'http://127.0.0.1:4387', 'X-Studio-Request': '1'}
        self.client.get('/')

    def tearDown(self):
        server.DATA = self.old
        self.tmp.cleanup()

    def post(self, path, data):
        return self.client.post(path, json=data, headers=self.headers)

    def test_owner_boundary(self):
        outsider = TestClient(server.app, base_url='http://127.0.0.1:4387')
        self.assertEqual(outsider.get('/status').status_code, 401)
        self.assertEqual(self.client.post('/verify', json={}).status_code, 403)
        self.assertEqual(self.client.get('/status', headers={'Host':'evil.test'}).status_code,403)

    def test_wrong_account_never_saved_and_provider_error_redacted(self):
        with patch.object(server.user,'get_self_info',return_value={'mid':'999','isLogin':True}):
            r=self.post('/connect',{'sessdata':'fixture-secret','bili_jct':'fixture-csrf'})
        self.assertEqual(r.status_code,400)
        self.assertNotIn('fixture-secret',r.text)
        self.assertFalse((server.DATA/'session.enc').exists())

    def test_encrypted_connection_and_fresh_identity(self):
        with patch.object(server.user,'get_self_info',return_value={'mid':server.UID,'isLogin':True,'uname':'James'}), patch.object(server.user,'get_user_info',return_value={'mid':server.UID,'name':'James'}):
            r=self.post('/connect',{'sessdata':'fixture-secret','bili_jct':'fixture-csrf'})
        self.assertEqual(r.status_code,200)
        self.assertNotIn(b'fixture-secret',(server.DATA/'session.enc').read_bytes())
        self.assertEqual((server.DATA/'session.enc').stat().st_mode&0o777,0o600)
        self.assertNotIn('fixture-secret',self.client.get('/status').text)
        self.assertEqual(server.credential().sessdata,'fixture-secret')

    def preview(self):
        assets=[]
        for kind,name in [('video','a.mp4'),('cover','a.jpg')]:
            r=self.client.post('/asset/'+kind,files={'file':(name,b'fixture bytes')},headers=self.headers)
            self.assertEqual(r.status_code,200)
            assets.append(r.json()['id'])
        with patch.object(server,'probe'):
            r=self.post('/preview',dict(video=assets[0],cover=assets[1],title='Exact title',description='Exact description',tags='music',category=31,copyright=1,source=''))
        self.assertEqual(r.status_code,200)
        return r.json()

    def test_approval_replay_and_tampering(self):
        j=self.preview()
        self.assertEqual(self.post('/submit/'+j['id'],{'hash':'wrong','approvePublicUpload':True}).status_code,400)
        with patch.object(server,'launch') as start:
            payload={'hash':j['hash'],'approvePublicUpload':True}
            self.assertEqual(self.post('/submit/'+j['id'],payload).status_code,200)
            self.assertEqual(self.post('/submit/'+j['id'],payload).status_code,200)
            start.assert_called_once()

    def test_upstream_payload_preserves_original_and_does_not_update(self):
        j=self.preview()
        j['state']='upload_started'
        server.write_job(j)
        with patch.object(server,'credential',return_value=object()), patch.object(server,'verified'), patch.object(upload_task,'video_upload',return_value='remote-file'), patch.object(upload_task,'video_cover_upload',return_value='cover'), patch.object(upload_task,'video_submit',return_value={'bvid':'BV1234567890'}) as submit, patch.object(server.video,'get_video_info',return_value={'owner':{'mid':server.UID},'title':'Exact title'}):
            server.execute(j)
            data=submit.call_args.args[0]
            self.assertEqual(data['title'],'Exact title')
            self.assertEqual(data['copyright'],1)
            self.assertEqual(server.read_job(j['id'])['state'],'published_verified')

    def test_uncertain_submission_not_marked_success(self):
        j=self.preview();j['state']='upload_started';server.write_job(j)
        with patch.object(server,'credential',return_value=object()),patch.object(server,'verified'),patch.object(upload_task,'video_upload',return_value='remote'),patch.object(upload_task,'video_cover_upload',return_value='cover'),patch.object(upload_task,'video_submit',side_effect=RuntimeError('fixture-secret')):
            server.execute(j)
        saved=server.read_job(j['id'])
        self.assertEqual(saved['state'],'submission_unknown')
        self.assertNotIn('fixture-secret',json.dumps(saved))

if __name__=='__main__': unittest.main()
