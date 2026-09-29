"""A staged (v3) automation drafts through a copy of the writing pipeline bound to the worker's repository. Its credit
checks must use that same repository: the shared `credit_requests` would open the service's session repository with
the worker capability, which the Supabase session verifier cannot read ('Bearer ' + object() raises TypeError)."""
import contextlib
import unittest
from unittest import mock

from postriff_phase2 import automation_runs


class Ideas:
    def __init__(self, repository):
        from postriff_phase2.credit_requests import CreditRequests
        self.repository = repository
        self.credit_requests = CreditRequests(self)
        self.seen = None

    def turn(self, workspace_id, token, conversation_id, request):
        self.seen = {"self": self, "credit_ideas": self.credit_requests.ideas, "repository": self.credit_requests.ideas.repository, "token": token}
        return {}


class StagedAutomationCreditTest(unittest.TestCase):
    def test_the_writer_copy_checks_credits_through_the_worker_repository(self):
        session_repository, worker_repository = object(), object()
        shared = Ideas(session_repository)
        copy_holder = {}
        real_copy = automation_runs.copy.copy

        def tracking_copy(value):
            made = real_copy(value)
            if value is shared:
                copy_holder["ideas"] = made
            return made

        @contextlib.contextmanager
        def connection():
            cur = mock.Mock()
            cur.fetchone.return_value = None
            db = mock.Mock()
            db.cursor.return_value = contextlib.nullcontext(cur)
            yield db

        service = type("Service", (), {"ideas": shared, "connection_factory": staticmethod(connection)})()
        worker = type("Worker", (), {"service": service, "clock": staticmethod(lambda: 1_790_000_000)})()
        claim = {"workspaceId": "w1", "actor": "owner-1", "binding": {}, "destinations": [{"platform": "LinkedIn", "language": "en"}], "sources": [], "context": {},
                 "task": {"workflow": {"research": False}, "contextSourceIds": [], "route": None, "schedule": {"timeZone": "UTC"}},
                 "campaign": {"goal": "g", "audience": "a", "facts": []}, "occurrence": {"id": "o1", "idempotencyKey": "k1", "conversationId": "c1", "research": None}}
        with mock.patch.object(automation_runs, "principal_repository", return_value=(worker_repository, "capability")), \
                mock.patch.object(automation_runs, "_update_run", return_value={}), \
                mock.patch.object(automation_runs, "_end_run", return_value={"ended": True}), \
                mock.patch.object(automation_runs, "lead", return_value="Write: "), \
                mock.patch.object(automation_runs.copy, "copy", side_effect=tracking_copy):
            automation_runs.generate(worker, claim)
        seen = copy_holder["ideas"].seen
        self.assertIs(seen["credit_ideas"], seen["self"])
        self.assertIs(seen["repository"], worker_repository)
        self.assertEqual(seen["token"], "capability")
        # The shared pipeline is untouched.
        self.assertIs(shared.credit_requests.ideas, shared)
        self.assertIs(shared.repository, session_repository)


if __name__ == "__main__":
    unittest.main()
