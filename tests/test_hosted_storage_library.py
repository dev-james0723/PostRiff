import email.message,unittest
from urllib.request import BaseHandler,build_opener
from urllib.response import addinfourl
from postriff_phase2.hosted_storage import SupabaseStorage,_NoRedirect
PROJECT="https://abcd1234.supabase.co";KEY="sb_secret_"+"x"*30;WS="5b2e7c1a-0000-4000-8000-000000000001";OBJ="0f3c0e3a9d5b4c1e8f7a6b5c4d3e2f10.pdf"
class FakeHTTPS(BaseHandler):
 handler_order=100
 def __init__(self,script):self.script=list(script);self.requests=[]
 def https_open(self,req):
  self.requests.append((req.get_method(),req.full_url,dict(req.header_items())));status,headers,body=self.script.pop(0);m=email.message.Message()
  for k,v in headers.items():m[k]=v
  r=addinfourl(__import__("io").BytesIO(body),m,req.full_url,code=status);r.msg="scripted";return r
class LibraryStorageTests(unittest.TestCase):
 def make(self,script):
  h=FakeHTTPS(script);return SupabaseStorage(PROJECT,KEY,file_bucket="postriff-library",opener=build_opener(_NoRedirect(),h)),h
 def test_file_path_uses_separate_private_bucket(self):
  s,h=self.make([(200,{"Content-Length":"3","Content-Type":"application/pdf","ETag":"e"},b"")]);self.assertEqual(s.object_info(WS,"file",OBJ)["bytes"],3);self.assertIn("/postriff-library/",h.requests[0][1]);self.assertIn(f"/{WS}/file/{OBJ}",h.requests[0][1])
 def test_bounded_file_read(self):
  s,h=self.make([(200,{"Content-Length":"3"},b"abc")]);self.assertEqual(s.get_bounded(WS,"file",OBJ,10),b"abc")
 def test_invalid_file_object_name_fails_closed(self):
  s,_=self.make([])
  with self.assertRaises(Exception):s.object_info(WS,"file","../evil.pdf")
if __name__=="__main__":unittest.main()
