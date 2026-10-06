import tempfile
import unittest
from pathlib import Path
from agent_team.events import Journal
from agent_team.native import collect_codex_metadata


class NativeTests(unittest.TestCase):
    def test_read_only_view_never_becomes_recovery_proof_or_task_completion(self):
        with tempfile.TemporaryDirectory() as d:
            class Client:
                def rpc(self,method,params):
                    self_method=method
                    if method!='thread/list':raise AssertionError('mutation')
                    return {'data':[{'id':'private-native-id','cwd':d,'updatedAt':1791240000,'status':{'type':'notLoaded'},'preview':'private prompt'}]}
                def close(self):pass
            j=Journal(Path(d)/'journal.db');r=collect_codex_metadata(j,d,client_factory=Client)
            self.assertEqual(r['writerOwnership'],'unproven')
            self.assertEqual(next(e for e in j.all() if e['source']=='codex')['payload']['reportedState'],'notLoaded')
            self.assertNotIn('private',str(j.all()));j.close()
