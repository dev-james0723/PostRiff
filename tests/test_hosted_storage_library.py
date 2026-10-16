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
 def test_every_viewer_page_uses_real_private_storage_object_grammar(self):
  from postriff_phase2.library_assets import UniversalLibrary
  asset={'id':OBJ.split('.')[0],'sha256':'a'*64}
  storage,handler=self.make([])
  names=[UniversalLibrary._preview_object(asset,n) for n in (1,2,12345)]
  self.assertEqual(len(set(names)),3)
  for name in names:
   self.assertEqual(storage._path(WS,'media',name),f'{WS}/media/{name}')
  self.assertFalse(handler.requests)
 def test_file_path_uses_separate_private_bucket(self):
  s,h=self.make([(200,{"Content-Length":"3","Content-Type":"application/pdf","ETag":"e"},b"")]);self.assertEqual(s.object_info(WS,"file",OBJ)["bytes"],3);self.assertIn("/postriff-library/",h.requests[0][1]);self.assertIn(f"/{WS}/file/{OBJ}",h.requests[0][1])
 def test_html_safe_download_mime_keeps_declared_identity(self):
  for ext in ("html","htm"):
   with self.subTest(ext=ext):
    obj="0f3c0e3a9d5b4c1e8f7a6b5c4d3e2f10."+ext
    s,_=self.make([(200,{"Content-Length":"121","Content-Type":"text/plain","ETag":"e"},b"")])
    self.assertEqual(s.object_info(WS,"file",obj),{"bytes":121,"mime":"text/html","etag":"e"})
 def test_text_files_keep_plain_text_identity(self):
  s,_=self.make([(200,{"Content-Length":"3","Content-Type":"text/plain","ETag":"e"},b"")])
  self.assertEqual(s.object_info(WS,"file","0f3c0e3a9d5b4c1e8f7a6b5c4d3e2f10.txt")["mime"],"text/plain")
 def test_bounded_file_read(self):
  s,h=self.make([(200,{"Content-Length":"3"},b"abc")]);self.assertEqual(s.get_bounded(WS,"file",OBJ,10),b"abc")
 def test_invalid_file_object_name_fails_closed(self):
  s,_=self.make([])
  with self.assertRaises(Exception):s.object_info(WS,"file","../evil.pdf")
 def test_delete_absent_object_with_wrapped_storage_404_is_success(self):
  body=b'{"statusCode":"404","error":"not_found","message":"Object not found","code":"NoSuchKey"}'
  s,h=self.make([(400,{"Content-Type":"application/json"},body)])
  self.assertIsNone(s.delete(WS,"file",OBJ))
  self.assertEqual(len(h.requests),1)
  self.assertEqual(h.requests[0][0],"DELETE")
  self.assertIn("/postriff-library/",h.requests[0][1])
 def test_delete_existing_object_preserves_normal_success(self):
  s,h=self.make([(204,{},b"")])
  self.assertIsNone(s.delete(WS,"file",OBJ))
  self.assertEqual(len(h.requests),1)
 def test_delete_other_400_responses_fail_closed(self):
  cases=(
   b'{"code":"NoSuchBucket","message":"Bucket not found","statusCode":"404"}',
   b'{"code":"InvalidRequest","message":"Malformed object path","statusCode":"400"}',
   b'{"code":"NoSuchKey","message":"Unknown failure","statusCode":"404"}',
   b'{"error":"not_found","message":"Object not found","statusCode":"404"}',
   b'{"code":"NoSuchKey","message":""}',
   b'not-json',
   b'',
  )
  for body in cases:
   with self.subTest(body=body):
    s,h=self.make([(400,{"Content-Type":"application/json"},body)])
    with self.assertRaisesRegex(Exception,"Private storage could not delete this object"):
     s.delete(WS,"file",OBJ)
    self.assertEqual(len(h.requests),1)
 def test_delete_other_status_with_no_such_key_body_still_fails(self):
  body=b'{"code":"NoSuchKey","message":"Object not found"}'
  s,_=self.make([(403,{"Content-Type":"application/json"},body)])
  with self.assertRaisesRegex(Exception,"Private storage could not delete this object"):
   s.delete(WS,"file",OBJ)
if __name__=="__main__":unittest.main()
