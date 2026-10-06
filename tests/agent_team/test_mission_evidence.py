"""Synthetic association contracts; no native activity or model invocation."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import tempfile
import unittest

from agent_team.events import Event
from agent_team.evidence_sources import EvidenceBatch
from agent_team.mission_evidence import MissionEvidenceBinding, associate_mission
from agent_team.recovery import NativeOwner, Registration, RecoveryStore
from agent_team.service import ServicePolicy, ServiceConfig

SESSION='11111111-2222-3333-4444-555555555555'


class MissionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.root.chmod(0o700)
        self.workspace=self.root/'workspace';self.workspace.mkdir()
        self.tp=self.workspace/'.token-pilot';self.tp.mkdir(mode=0o700)
        self.registration=Registration('fixture-mission',str(self.workspace),str(self.workspace),SESSION,
            'claude-code',NativeOwner('fixture-owner',str(self.root/'owner.sock'),os.getpid(),'synthetic-start'),
            'fixture-task','fixture-task',None,'fixture-approved','a'*64,'fixture-v1',
            ('verify actual continuation',),('fixture-ledger',))
        self.store=RecoveryStore(str(self.root/'recovery.sqlite3'));self.addCleanup(self.store.db.close)
        self.fingerprint=self.store.register(self.registration)
        (self.root/'recovery.sqlite3').chmod(0o600)
        self.binding=MissionEvidenceBinding(self.root/'recovery.sqlite3','fixture-mission',self.fingerprint,SESSION)
        self.state={'schema_version':2,'project':str(self.workspace),'sessions':{SESSION:{'binding':{
            'task_id':'fixture-task','root_task_id':'fixture-task','phase_id':None}}},
            'workspace':{'tasks':{'fixture-task':{'status':'active','actions':{}}}}}
        self.save_state()
        event=Event('claude','fixture-observation','fixture-revision','2026-10-06T14:00:00Z',
            '2026-10-06T14:01:00Z',{'kind':'claude_usage_input_tokens','count':3},project_id='fixture-project')
        self.batch=EvidenceBatch('claude','ok',(event,),fresh_at=event.happened_at)

    def save_state(self):
        p=self.tp/'state.json';p.write_text(json.dumps(self.state));p.chmod(0o600)

    def associate(self,binding=None):
        return associate_mission(self.batch,binding or self.binding,workspace=self.workspace,project_id='fixture-project')

    def test_real_source_records_are_associated_without_execution_authority(self):
        linked=self.associate()
        self.assertEqual(linked.events[0].mission_id,'fixture-mission')
        self.assertEqual(linked.events[0].payload,self.batch.events[0].payload)
        self.assertNotEqual(linked.events[0].revision,self.batch.events[0].revision)
        self.assertEqual(linked.as_dict()['writerOwnership'],'unproven')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM recovery_checkpoints').fetchone()[0],0)

    def test_unbound_sources_remain_unassigned(self):
        self.assertIs(associate_mission(self.batch,None,workspace=self.workspace,project_id='fixture-project'),self.batch)
        empty=replace(self.batch,events=())
        self.assertFalse(associate_mission(empty,self.binding,workspace=self.workspace,project_id='fixture-project').events)

    def test_wrong_registration_session_or_workspace_never_labels_events(self):
        for binding in (replace(self.binding,registration_sha256='b'*64),
                        replace(self.binding,session_id='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')):
            linked=self.associate(binding);self.assertFalse(linked.events);self.assertEqual(linked.status,'unavailable')
        linked=associate_mission(self.batch,self.binding,workspace=self.root,project_id='fixture-project')
        self.assertFalse(linked.events)

    def test_unknown_actions_and_changed_continuity_never_grant_association(self):
        self.state['workspace']['tasks']['fixture-task']['actions']={'fixture-effect':{'status':'outcome_unknown'}}
        self.save_state();self.assertFalse(self.associate().events)
        self.state['workspace']['tasks']['fixture-task']['actions']={}
        self.state['sessions'][SESSION]['binding']['task_id']='other-task'
        self.save_state();self.assertFalse(self.associate().events)

    def test_mutated_registration_body_and_public_state_fail_closed(self):
        data=asdict(self.registration);data['native_session_id']='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        self.store.db.execute('UPDATE recovery_bindings SET body=?',(json.dumps(data),))
        self.assertFalse(self.associate().events)
        self.store.db.execute('UPDATE recovery_bindings SET body=?',(json.dumps(asdict(self.registration)),))
        (self.tp/'state.json').chmod(0o644);self.assertFalse(self.associate().events)

    def test_policy_roundtrip_preserves_explicit_binding_and_does_not_read_sources(self):
        log=self.root/'not-yet-created.jsonl'
        policy=ServicePolicy.from_mapping({'version':1,'canonical_root':str(self.root),
            'approved_native_projects':{str(self.workspace):'fixture-project'},'allowed_upload_hosts':[],
            'approved_claude_logs':{str(log):{'workspace':str(self.workspace),'project_id':'fixture-project',
                'mission_binding':self.binding.as_dict()}}},canonical_root=self.root)
        config=ServiceConfig.from_mapping({'version':1,'journal_path':str(self.root/'.runtime/journal.sqlite3'),
            'interval_seconds':300,'window_seconds':600,'typeless':False,'luci':False,'native_workspaces':[],
            'upload':None,'claude_logs':[str(log)]},policy)
        self.assertEqual(config.validate().claude_logs[0].mission_binding,self.binding)
        self.assertFalse(log.exists())

if __name__=='__main__':unittest.main()
