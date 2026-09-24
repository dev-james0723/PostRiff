import unittest

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2 import suggestions


class RaffiSuggestionTests(unittest.TestCase):
    def setUp(self):
        self.state = initial_state("workspace-one")
        self.state.setdefault("phase2", {"assets": [], "jobs": []})
        self.state["phase2"].setdefault("assets", [])
        self.state["phase2"].setdefault("jobs", [])

    def test_empty_context_creates_no_suggestions(self):
        self.assertEqual(suggestions.refresh(self.state, 100), [])

    def test_unused_asset_campaign_gap_and_held_job_are_evidence_linked_and_deduplicated(self):
        self.state["phase2"]["assets"].append({"id": "asset-1", "processing": "decoded", "deleted": False, "revision": 2})
        self.state["phase2"]["jobs"].append({"id": "job-1", "state": "held", "manifest": {"media": []}, "events": [{"state": "held"}]})
        self.state.setdefault("raffi", {})["campaignPlanning"] = {"campaigns": [{"id": "campaign-1", "version": 3, "status": "draft", "items": []}], "recurringTasks": [], "occurrences": []}
        first = suggestions.refresh(self.state, 100)
        second = suggestions.refresh(self.state, 101)
        self.assertEqual(len(first), 3)
        self.assertEqual([item["id"] for item in first], [item["id"] for item in second])
        self.assertTrue(all(item["evidence"] for item in first))

    def test_accept_is_idempotent_and_cannot_publish_or_activate_recurrence(self):
        self.state["phase2"]["assets"].append({"id": "asset-1", "processing": "decoded", "deleted": False})
        suggestion = suggestions.refresh(self.state, 100)[0]
        first = suggestions.apply_action(self.state, "raffi_suggestion_accept", {"suggestionId": suggestion["id"]}, "editor", 101)
        second = suggestions.apply_action(self.state, "raffi_suggestion_accept", {"suggestionId": suggestion["id"]}, "editor", 102)
        self.assertEqual(first["actionRef"], second["actionRef"])
        self.assertEqual(first["actionRef"]["authority"], "open_for_review")
        self.assertEqual(first["actionRef"]["targetId"], "asset-1")
        self.assertEqual(first["actionRef"]["workspaceId"], self.state["workspace"]["id"])
        self.assertEqual(self.state["phase2"]["jobs"], [])
        self.assertEqual(self.state.get("raffi", {}).get("campaignPlanning"), None)

    def test_expired_snooze_reopens_but_stale_accepted_target_is_refused(self):
        self.state["phase2"]["assets"].append({"id":"asset-1","processing":"decoded","deleted":False})
        item=suggestions.refresh(self.state,100)[0]
        suggestions.apply_action(self.state,"raffi_suggestion_snooze",{"suggestionId":item["id"],"until":110},"editor",101)
        suggestions.refresh(self.state,111)
        self.assertEqual(item["status"],"open")
        suggestions.apply_action(self.state,"raffi_suggestion_accept",{"suggestionId":item["id"]},"editor",112)
        self.state["phase2"]["assets"][0]["deleted"]=True
        with self.assertRaises(AlphaError):
            suggestions.apply_action(self.state,"raffi_suggestion_accept",{"suggestionId":item["id"]},"editor",113)

    def test_removed_evidence_stales_open_suggestion(self):
        self.state["phase2"]["assets"].append({"id": "asset-1", "processing": "decoded", "deleted": False})
        suggestion = suggestions.refresh(self.state, 100)[0]
        self.state["phase2"]["assets"][0]["deleted"] = True
        suggestions.refresh(self.state, 101)
        self.assertEqual(suggestion["status"], "stale")


if __name__ == "__main__":
    unittest.main()
