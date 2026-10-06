"""Synthetic security checks; no native process, credential read or model call."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent_team.recovery import RecoveryBlocked
from agent_team.restricted_owner import (native_argv, parse_native_result, private,
    sandbox_profile, verify_ancestry, workspace_snapshot, authenticated_envelope, authenticated_body,
    parse_quota_rejection)

SESSION='11111111-2222-3333-4444-555555555555'
TURN='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


class RestrictedOwnerTests(unittest.TestCase):
    def test_responses_require_authentication_and_exact_request_identity(self):
        token=b'synthetic-owner-token';body={'requestId':'a'*32,'result':{'state':'finished'}}
        signed=authenticated_envelope(token,body)
        self.assertEqual(authenticated_body(token,signed,request_id='a'*32),body)
        with self.assertRaisesRegex(RecoveryBlocked,'request_mismatch'):
            authenticated_body(token,signed,request_id='b'*32)
        changed=copy.deepcopy(signed);changed['body']['result']['state']='unverified'
        with self.assertRaisesRegex(RecoveryBlocked,'authentication'):authenticated_body(token,changed)
        with self.assertRaisesRegex(RecoveryBlocked,'authentication'):authenticated_body(b'other',signed)

    def setUp(self):
        self.rows=[{'type':'system','subtype':'init','session_id':SESSION,'model':'native-selected-model',
                    'tools':[],'mcp_servers':[]},
            {'type':'result','subtype':'success','session_id':SESSION,'is_error':False,
             'num_turns':1,'uuid':TURN,'usage':{'input_tokens':5,'output_tokens':4},'total_cost_usd':.001}]

    def test_actual_native_identity_tools_and_bounded_turn_are_required(self):
        parsed=parse_native_result(self.rows,session=SESSION)
        self.assertEqual(parsed['turnId'],TURN)
        for index,key,value in [(0,'tools',['Bash']),(0,'mcp_servers',[{'name':'unregistered'}]),
                (1,'uuid',None),(1,'num_turns',2),(1,'is_error',True),(1,'session_id',TURN)]:
            rows=copy.deepcopy(self.rows);rows[index][key]=value
            with self.assertRaises(RecoveryBlocked):parse_native_result(rows,session=SESSION)

    def test_resume_cannot_change_model_or_run_a_tool(self):
        with self.assertRaisesRegex(RecoveryBlocked,'configuration_changed'):
            parse_native_result(self.rows,session=SESSION,expected_model='other')
        rows=copy.deepcopy(self.rows)
        rows.insert(1,{'type':'assistant','message':{'content':[{'type':'tool_use','name':'Write'}]}})
        with self.assertRaisesRegex(RecoveryBlocked,'tool_dispatch'):parse_native_result(rows,session=SESSION)

    def rejected_rows(self):
        return [copy.deepcopy(self.rows[0]),
            {'type':'rate_limit_event','session_id':SESSION,'rate_limit_info':{
                'status':'rejected','isUsingOverage':False,'overageStatus':'rejected','resetsAt':2000000000}},
            {'type':'result','session_id':SESSION,'uuid':TURN,'is_error':True,'api_error_status':429,
             'terminal_reason':'api_error','num_turns':1,'total_cost_usd':0,'modelUsage':{},
             'permission_denials':[],'usage':{'input_tokens':0,'output_tokens':0,
                 'cache_creation_input_tokens':0,'cache_read_input_tokens':0}}]

    def test_proven_zero_usage_quota_rejection_never_becomes_a_successful_turn(self):
        rows=self.rejected_rows();receipt=parse_quota_rejection(rows,session=SESSION)
        self.assertFalse(receipt['successfulNativeTurn'])
        self.assertEqual(receipt['terminalState'],'provider_quota_rejected')
        self.assertEqual(receipt['providerUsageTokens'],0)
        with self.assertRaises(RecoveryBlocked):parse_native_result(rows,session=SESSION)

    def test_reconciliation_rejects_usage_tools_partial_result_and_other_errors(self):
        for index,key,value in [(0,'tools',['Bash']),(0,'mcp_servers',[{'name':'unexpected'}]),
                (2,'is_error',False),(2,'api_error_status',500),(2,'num_turns',2),
                (2,'total_cost_usd',.01),(2,'modelUsage',{'model':{'inputTokens':1}}),
                (2,'uuid',None),(2,'session_id',TURN),(2,'permission_denials',[{'tool':'Bash'}])]:
            rows=self.rejected_rows();rows[index][key]=value
            with self.subTest(key=key),self.assertRaises(RecoveryBlocked):parse_quota_rejection(rows,session=SESSION)
        rows=self.rejected_rows();rows[-1]['usage']['input_tokens']=1
        with self.assertRaises(RecoveryBlocked):parse_quota_rejection(rows,session=SESSION)
        rows=self.rejected_rows();rows.insert(1,{'type':'assistant','message':{'content':[{'type':'tool_use'}]}})
        with self.assertRaises(RecoveryBlocked):parse_quota_rejection(rows,session=SESSION)
        rows=self.rejected_rows();rows[1]['rate_limit_info']['isUsingOverage']=True
        with self.assertRaises(RecoveryBlocked):parse_quota_rejection(rows,session=SESSION)
        with self.assertRaises(RecoveryBlocked):parse_quota_rejection(self.rejected_rows()[:-1],session=SESSION)

    def test_native_argv_preserves_session_and_removes_all_tool_authority(self):
        args=native_argv('/installed/claude','/private/native-settings.json',SESSION,resume=True)
        self.assertEqual(args[:2],['/usr/bin/sandbox-exec','-f'])
        self.assertEqual(args[args.index('--tools')+1],'')
        self.assertEqual(args[args.index('--disallowedTools')+1],'*')
        self.assertEqual(args[args.index('--mcp-config')+1],'{"mcpServers":{}}')
        self.assertEqual(args[-2:],['--resume',SESSION])
        self.assertNotIn('--dangerously-skip-permissions',args)
        self.assertNotIn('--fork-session',args)

    def test_kernel_profile_never_grants_worktree_or_home_writes(self):
        profile=sandbox_profile('/private/owner','/exact/project','/installed/claude','/installed/python')
        self.assertIn('(deny default)',profile)
        self.assertIn('(subpath "/exact/project/.token-pilot")',profile)
        self.assertNotIn('(subpath "/exact/project")',profile)
        self.assertNotIn('(subpath "/Users")',profile)
        self.assertNotIn('/bin/sh',profile)

    def test_orc_bootstrap_uses_actual_ancestry_and_rejects_pid_reuse(self):
        with patch('agent_team.restricted_owner.process_identity',side_effect=lambda p:{90:(80,'child'),80:(1,'agent-start')}[p]):
            verify_ancestry(80,'agent-start',pid=90)
            with self.assertRaisesRegex(RecoveryBlocked,'pid_reused'):verify_ancestry(80,'old-start',pid=90)
        with patch('agent_team.restricted_owner.process_identity',return_value=(1,'other')):
            with self.assertRaisesRegex(RecoveryBlocked,'bootstrap_required'):verify_ancestry(80,'agent-start',pid=90)

    def test_private_state_cannot_be_symlink_or_public(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'state';p.write_text('x');p.chmod(0o600);self.assertEqual(private(p),p)
            q=Path(directory)/'alias';q.symlink_to(p)
            with self.assertRaises(RecoveryBlocked):private(q)
            p.chmod(0o644)
            with self.assertRaises(RecoveryBlocked):private(p)

    def test_untracked_content_is_part_of_workspace_identity(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            subprocess.run(['git','init','-q',str(p)],check=True)
            subprocess.run(['git','-C',str(p),'-c','user.name=fixture','-c','user.email=fixture@example.invalid',
                'commit','--allow-empty','-qm','fixture'],check=True)
            q=p/'untracked.txt';q.write_text('first');a=workspace_snapshot(p)
            q.write_text('second');b=workspace_snapshot(p)
            self.assertEqual(a.head,b.head);self.assertNotEqual(a.dirty_sha256,b.dirty_sha256)

if __name__=='__main__':unittest.main()
