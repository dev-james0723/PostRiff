"""The alpha template writer's own actions (generate, preview_update) are refused on the hosted HTTP route, so no
customer draft comes from templates behind Rafii's writer; every other action still reaches the service."""
import unittest

from postriff_phase2.hosted_app import HostedApplication, RETIRED_WRITING_ACTIONS
from test_postriff_account_security import AUTH, WORKSPACE, invoke


class Service:
    def __init__(self):
        self.calls = []

    def mutate(self, workspace_id, token, revision, action, payload):
        self.calls.append(action)
        return {"revision": revision + 1, "state": {}}


class RetiredWritingActionsTest(unittest.TestCase):
    def test_template_writer_actions_are_refused_and_others_pass(self):
        service = Service()
        app = HostedApplication(service, None, {"provider": "supabase"}, "c" * 24)
        for action in sorted(RETIRED_WRITING_ACTIONS):
            status, body = invoke(app, "POST", f"/api/workspaces/{WORKSPACE}/actions", {"action": action, "payload": {"platform": "LinkedIn"}, "expectedRevision": 1}, AUTH)
            self.assertEqual(status, 410, body)
        self.assertEqual(service.calls, [])
        status, _ = invoke(app, "POST", f"/api/workspaces/{WORKSPACE}/actions", {"action": "accept_update", "payload": {}, "expectedRevision": 1}, AUTH)
        self.assertEqual((status, service.calls), (200, ["accept_update"]))
        self.assertEqual(RETIRED_WRITING_ACTIONS, {"generate", "preview_update"})


if __name__ == "__main__":
    unittest.main()
