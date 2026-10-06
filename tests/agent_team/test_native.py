import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from agent_team.events import Journal
from agent_team.native import collect_codex_metadata, conductor_read_source


class NativeTests(unittest.TestCase):
    def test_unreviewed_installed_dependency_is_never_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            module=root/'src/agent_team/native.py';module.parent.mkdir(parents=True);module.touch()
            source=root/'.agents/skills/james-daily-conductor/scripts/daily_conductor.py'
            source.parent.mkdir(parents=True);source.write_text('raise RuntimeError("unreviewed code")')
            with patch('agent_team.native.__file__',str(module)),patch('agent_team.native.Path.home',return_value=root):
                with self.assertRaisesRegex(ValueError,'reviewed_conductor_dependency_changed'):
                    conductor_read_source()

    def test_missing_private_dependency_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();module=root/'src/agent_team/native.py'
            module.parent.mkdir(parents=True);module.touch()
            with patch('agent_team.native.__file__',str(module)),patch('agent_team.native.Path.home',return_value=root):
                with self.assertRaisesRegex(ValueError,'reviewed_conductor_dependency_missing'):
                    conductor_read_source()

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
