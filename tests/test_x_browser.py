import tempfile, time, unittest
from pathlib import Path
from james_au_social.x_browser import Store, Stop, digest, execute, manifest, permalink, validate

class FakeUI:
    def __init__(self, fail=False): self.fail=fail; self.calls=[]
    def identity(self,p): self.calls.append(('identity',p)); return ['menu','profile']
    def links(self,p): return {'https://x.com/jamesaucreates/status/1'}
    def compose(self,t,a): self.calls.append(('compose',t,a))
    def submit(self,s): self.calls.append(('submit',s));
    def find_new(self,b,v):
        if self.fail: raise Stop('publication_unresolved')
        return {'permalink':'https://x.com/jamesaucreates/status/2'}
    def verify_scheduled(self,v):
        if self.fail: raise Stop('scheduled_post_unresolved')
        return {'scheduledAt':v['scheduledAt'],'nativeQueueMatch':True}

class XBrowserTests(unittest.TestCase):
    def test_manifest_hash_and_bounds(self):
        m=manifest('@jamesaucreates','hello'); self.assertEqual(validate(m),m); self.assertEqual(len(digest(m)),64)
        with self.assertRaises(Stop): manifest('bad handle','hello')
        with self.assertRaises(Stop): manifest('jamesaucreates','x'*281)
    def test_schedule_requires_future_timezone(self):
        with self.assertRaises(Stop): manifest('jamesaucreates','hello','2026-09-14T12:00:00')
        m=manifest('jamesaucreates','hello','2099-01-01T12:00:00Z'); self.assertEqual(m['timing'],'scheduled')
    def test_exact_approval_and_duplicate_claim(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'private'); m=manifest('jamesaucreates','hello'); ui=FakeUI()
            with self.assertRaises(Stop): execute(s,m,'wrong',ui)
            one=execute(s,m,digest(m),ui); two=execute(s,m,digest(m),FakeUI())
            self.assertEqual(one['state'],'published_verified'); self.assertEqual(two,one); s.close()
    def test_ambiguous_submit_is_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'private'); m=manifest('jamesaucreates','hello'); ui=FakeUI(True)
            one=execute(s,m,digest(m),ui); second=FakeUI(); two=execute(s,m,digest(m),second)
            self.assertEqual(one['state'],'unknown'); self.assertEqual(two,one); self.assertEqual(second.calls,[]); s.close()
    def test_permalink_rejects_query(self):
        self.assertEqual(permalink('https://x.com/jamesaucreates/status/123'),'https://x.com/jamesaucreates/status/123')
        with self.assertRaises(Stop): permalink('https://x.com/jamesaucreates/status/123?x=1')

if __name__=='__main__': unittest.main()
