import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.skills import CORE_SKILL, SkillLibrary  # noqa: E402


class SkillPreviewTests(unittest.TestCase):
    def test_picker_visible_skill_returns_primary_markdown(self):
        library = SkillLibrary()
        preview = library.preview(CORE_SKILL)
        self.assertIsNotNone(preview)
        self.assertEqual(preview["id"], CORE_SKILL)
        self.assertTrue(preview["body"].strip())
        self.assertEqual(preview["files"][0]["path"], "SKILL.md")
        self.assertNotIn("references", preview)

    def test_unknown_or_private_package_is_not_previewable(self):
        library = SkillLibrary()
        self.assertIsNone(library.preview("not-a-real-skill"))
        self.assertIsNone(library.preview("private-customer-skill"))

    def test_hosted_service_authenticates_before_returning_skill(self):
        calls = []

        class Repository:
            def get(self, workspace_id, token):
                calls.append((workspace_id, token))
                return {"state": {}, "revision": 1}

        service = HostedWorkspaceService.__new__(HostedWorkspaceService)
        service.repository = Repository()
        service.ideas = type("Ideas", (), {"skills": SkillLibrary()})()

        preview = service.skill_preview("workspace-1", "token-1", CORE_SKILL)
        self.assertEqual(calls, [("workspace-1", "token-1")])
        self.assertEqual(preview["id"], CORE_SKILL)

        with self.assertRaises(AlphaError) as caught:
            service.skill_preview("workspace-1", "token-1", "not-a-real-skill")
        self.assertEqual(caught.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
