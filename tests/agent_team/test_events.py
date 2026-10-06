import tempfile
import unittest
from pathlib import Path
from agent_team.events import Event, Journal, projection, safe_url


class JournalTests(unittest.TestCase):
    def test_incremental_outbox_transaction_and_immutable_version(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'journal.db')
            e=Event('typeless','record1','v1','2026-10-05T14:00:00Z','2026-10-05T14:01:00Z',{'status':'pending'})
            self.assertEqual(j.ingest([e],'typeless',{'last':'record1'}),1)
            self.assertEqual(j.ingest([e]),0)
            conflicting=Event('typeless','record1','v1',e.happened_at,e.observed_at,{'status':'completed'})
            with self.assertRaises(ValueError):j.ingest([conflicting],'typeless',{'last':'lost'})
            self.assertEqual(j.cursor('typeless'),{'last':'record1'})
            self.assertEqual(len(j.pending()),1)
            j.acknowledge([e.key],'2026-10-05T14:02:00Z');self.assertEqual(j.pending(),[])
            j.close()

    def test_cloud_boundary(self):
        for field in ['raw_text','refined_text','audio_local_path','credentials','hidden_reasoning','tool_output']:
            with self.assertRaises(ValueError):projection({field:'private'})
        self.assertEqual(safe_url('https://site.example/page?token=private#fragment'),'https://site.example/page')
        with self.assertRaises(ValueError):safe_url('http://localhost/secret')

    def test_source_time_and_identity_validation(self):
        with self.assertRaises(ValueError):Event('typeless','/Users/private','v1','2026-10-05T14:00:00Z','2026-10-05T14:01:00Z',{}).cloud()
        with self.assertRaises(ValueError):Event('typeless','id','v1','2026-10-05T15:00:00Z','2026-10-05T14:01:00Z',{}).cloud()
