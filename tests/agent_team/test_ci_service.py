"""Synthetic CI metadata registration contracts; no GitHub requests."""
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_team.service import ServicePolicy, ServiceConfig, collect_registered_evidence


class CiServiceTests(unittest.TestCase):
    def inputs(self):
        root=Path('/registered/agent-team')
        work=Path('/registered/postriff')
        policy={'version':1,'canonical_root':str(root),
                'approved_native_projects':{str(work):'raffi'},'allowed_upload_hosts':[],
                'approved_git_repositories':{str(work):{'repository':'owner/repo','gh_binary':'/registered/bin/gh'}}}
        config={'version':1,'journal_path':str(root/'.runtime/journal.sqlite3'),
                'interval_seconds':300,'window_seconds':600,'typeless':False,'luci':False,
                'native_workspaces':[],'upload':None,
                'evidence_workspaces':[{'workspace':str(work),'project_id':'raffi'}]}
        return root,work,policy,config

    def test_ci_needs_explicit_config_and_exact_policy_registration(self):
        root,work,policy,data=self.inputs()
        registered=ServicePolicy.from_mapping(policy,canonical_root=root)
        self.assertEqual(ServiceConfig.from_mapping(data,registered).ci_workspaces,())
        data['ci_workspaces']=[str(work)]
        config=ServiceConfig.from_mapping(data,registered).validate()
        self.assertEqual(config.ci_workspaces,(work,))
        data['ci_workspaces']=['/registered/other']
        with self.assertRaisesRegex(ValueError,'ci_workspace_not_approved'):
            ServiceConfig.from_mapping(data,registered)

    def test_ci_requires_existing_selected_evidence_workspace(self):
        root,work,policy,data=self.inputs()
        data.update(ci_workspaces=[str(work)],evidence_workspaces=[])
        with self.assertRaisesRegex(ValueError,'ci_workspace_not_approved'):
            ServiceConfig.from_mapping(data,ServicePolicy.from_mapping(policy,canonical_root=root))

    def test_repository_is_scoped_and_cannot_supply_cli_arguments(self):
        root,work,policy,_=self.inputs()
        for value in ('owner/repo --method POST','../repo','owner/..','https://github.com/owner/repo'):
            policy['approved_git_repositories'][str(work)]['repository']=value
            with self.assertRaisesRegex(ValueError,'git_repository_identity_required'):
                ServicePolicy.from_mapping(policy,canonical_root=root)

    def test_old_policy_remains_ci_disabled(self):
        root,_,policy,data=self.inputs()
        del policy['approved_git_repositories']
        config=ServiceConfig.from_mapping(data,ServicePolicy.from_mapping(policy,canonical_root=root))
        self.assertEqual(config.policy.approved_git_repositories,())
        self.assertEqual(config.ci_workspaces,())

    def test_collector_passes_only_registered_ci_get_authority(self):
        root,work,policy,data=self.inputs();data['ci_workspaces']=[str(work)]
        config=ServiceConfig.from_mapping(data,ServicePolicy.from_mapping(policy,canonical_root=root))
        with patch('agent_team.service.read_git_metadata',return_value=SimpleNamespace()) as read_git, \
             patch('agent_team.service.read_token_pilot_metadata',return_value=SimpleNamespace()):
            list(collect_registered_evidence(config,datetime.now(timezone.utc)))
        selected=read_git.call_args.args[0]
        self.assertTrue(selected.gh_authorized);self.assertTrue(selected.ci)
        self.assertFalse(selected.deployments)
        self.assertEqual(selected.repository,'owner/repo')
        self.assertEqual(selected.gh_binary,selected.allowed_gh_binary)
        self.assertEqual(selected.remote_limit,2)


if __name__=='__main__':unittest.main()
