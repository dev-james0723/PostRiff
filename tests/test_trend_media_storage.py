"""No live transport: actual child lifetime/protocol, explicit adapter fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from postriff_phase2.growth.trends import media_storage as M
from postriff_phase2.hosted_storage import SupabaseStorage

SECRET='synthetic-stdin-only-not-a-real-key-0123456789'
WID=str(uuid.uuid4()); OBJECT=uuid.uuid4().hex+'.mp4'
CONFIG={'project_url':'https://fixture.supabase.co','secret_key':SECRET,'bucket':'postriff-private','video_bucket':'postriff-video'}


class Storage(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect','socket.create_connection','socket.getaddrinfo','urllib.request.urlopen','urllib.request.OpenerDirector.open'):
            guard=patch(name,side_effect=AssertionError('no live storage calls'))
            mock=guard.start(); self.addCleanup(guard.stop); self.addCleanup(mock.assert_not_called)

    def request(self,**changes):
        return {**{'configuration':dict(CONFIG),'operation':'head','workspace_id':WID,'object_name':OBJECT,'length':None},**changes}

    def test_only_canonical_production_adapter_no_custom_send_or_subclass(self):
        class Custom(SupabaseStorage): pass
        for storage in (SimpleNamespace(),Custom(**CONFIG),SupabaseStorage(**CONFIG,send=lambda *a:None),
                        SupabaseStorage(**CONFIG,opener=SimpleNamespace())):
            with self.assertRaisesRegex(ValueError,'unsupported_transport'): M.BoundedStorage(storage,deadline=time.monotonic()+10)
        M.BoundedStorage(SupabaseStorage(**CONFIG),deadline=time.monotonic()+10)

    def test_invalid_operation_path_byte_range_or_expired_deadline_never_spawns(self):
        with patch.object(M.subprocess,'Popen',side_effect=AssertionError('invalid spawn')):
            for change in ({'operation':'delete'},{'object_name':'../video.mp4'},{'object_name':'https://attacker.invalid/x'},
                           {'operation':'range','length':M.MAX_BYTES+1},{'operation':'range','length':True},{'extra':'command'}):
                with self.assertRaises(ValueError): M._communicate(self.request(**change),time.monotonic()+10)
            with self.assertRaisesRegex(ValueError,'deadline'): M._communicate(self.request(),time.monotonic()-1)

    def test_actual_fresh_child_receives_secret_only_on_stdin_and_leaves_no_files(self):
        real=subprocess.Popen; observed={}
        code="import sys,json; q=json.load(sys.stdin); assert len(q['configuration']['secret_key'])>20; print(json.dumps({'head':{'bytes':8,'mime':'video/mp4','etag':'fixture'}}))"
        with tempfile.TemporaryDirectory() as tmp:
            def spawn(argv,**kwargs):
                observed.update(argv=argv,kwargs=kwargs)
                process=real([sys.executable,'-c',code],cwd=tmp,**kwargs); observed['process']=process; return process
            with patch.dict(os.environ,{'PRIVATE_MEDIA_CANARY':SECRET}),patch.object(M.subprocess,'Popen',side_effect=spawn):
                result=M._communicate(self.request(),time.monotonic()+3)
            self.assertEqual(list(Path(tmp).iterdir()),[])
        self.assertEqual(result['head']['bytes'],8)
        self.assertNotIn(SECRET,repr(observed['argv'])+repr(observed['kwargs']))
        self.assertNotIn('PRIVATE_MEDIA_CANARY',observed['kwargs']['env'])
        self.assertEqual(observed['kwargs']['stderr'],subprocess.DEVNULL)
        self.assertTrue(observed['kwargs']['close_fds']); self.assertTrue(observed['kwargs']['start_new_session'])
        self.assertFalse(observed['kwargs']['shell']); self.assertEqual(observed['process'].returncode,0)

    def test_actual_hanging_child_is_killed_reaped_and_no_credential_artifact_remains(self):
        real=subprocess.Popen; spawned=[]
        with tempfile.TemporaryDirectory() as tmp:
            def spawn(argv,**kwargs):
                process=real([sys.executable,'-c','import sys,time; sys.stdin.buffer.read(); time.sleep(60)'],cwd=tmp,**kwargs)
                spawned.append(process); return process
            start=time.monotonic()
            with patch.object(M.subprocess,'Popen',side_effect=spawn),self.assertRaisesRegex(ValueError,'media_storage_deadline') as error:
                M._communicate(self.request(),start+.15)
            self.assertLess(time.monotonic()-start,3)
            self.assertEqual(list(Path(tmp).iterdir()),[])
        self.assertEqual(len(spawned),1); self.assertLess(spawned[0].returncode,0)
        with self.assertRaises(ProcessLookupError): os.kill(spawned[0].pid,0)
        self.assertNotIn(SECRET,str(error.exception))

    def test_real_module_child_rejects_invalid_configuration_without_live_io_or_details(self):
        # Invalid host is rejected by the existing adapter constructor before I/O.
        request=self.request(configuration={**CONFIG,'project_url':'https://127.0.0.1/'})
        with self.assertRaisesRegex(ValueError,'transport_failed') as error:
            M._communicate(request,time.monotonic()+5)
        self.assertNotIn(SECRET,str(error.exception)); self.assertNotIn('127.0.0.1',str(error.exception))

    def test_dispatch_reuses_only_head_and_bounded_range_existing_methods(self):
        calls=[]
        class Adapter:
            def __init__(self,**configuration): self.configuration=configuration
            def object_info(self,*a): calls.append(('head',a)); return {'bytes':4,'mime':'video/mp4','etag':'test'}
            def read_range(self,*a): calls.append(('range',a)); return {'data':b'abcd','ranged':True}
        self.assertEqual(M._dispatch(self.request(),adapter_factory=Adapter)['head']['bytes'],4)
        self.assertEqual(M._dispatch(self.request(operation='range',length=4),adapter_factory=Adapter)['data'],'YWJjZA==')
        self.assertEqual(calls,[('head',(WID,'video',OBJECT)),('range',(WID,'video',OBJECT,0,4))])

    def test_two_objects_six_calls_and_per_object_order_are_bounded(self):
        adapter=M.BoundedStorage(SupabaseStorage(**CONFIG),deadline=time.monotonic()+10)
        def answer(request,deadline):
            M.remaining(deadline)
            return {'head':{'bytes':4,'mime':'video/mp4','etag':'test'}} if request['operation']=='head' else {'data':'YWJjZA==','ranged':True}
        with patch.object(M,'_communicate',side_effect=answer) as called:
            with self.assertRaisesRegex(ValueError,'call_bound'): adapter.read_range(WID,'video',OBJECT,0,4)
            for name in (OBJECT,uuid.uuid4().hex+'.mov'):
                adapter.object_info(WID,'video',name)
                self.assertEqual(adapter.read_range(WID,'video',name,0,4)['data'],b'abcd')
                adapter.object_info(WID,'video',name)
            with self.assertRaisesRegex(ValueError,'call_bound'): adapter.object_info(WID,'video',uuid.uuid4().hex+'.mp4')
            self.assertEqual(called.call_count,6)

    def test_response_bytes_headers_and_range_start_cannot_exceed_contract(self):
        adapter=M.BoundedStorage(SupabaseStorage(**CONFIG),deadline=time.monotonic()+10)
        with self.assertRaises(ValueError): adapter.read_range(WID,'video',OBJECT,1,1)
        with patch.object(M,'_communicate',return_value={'head':{'bytes':M.MAX_BYTES+1,'mime':'video/mp4','etag':'x'}}):
            with self.assertRaisesRegex(ValueError,'head_response'): adapter.object_info(WID,'video',OBJECT)
        with patch.object(M,'_communicate',return_value={'data':'YWJjZA==','ranged':True}):
            with self.assertRaisesRegex(ValueError,'byte_bound'): adapter.read_range(WID,'video',OBJECT,0,1)


if __name__=='__main__': unittest.main()
