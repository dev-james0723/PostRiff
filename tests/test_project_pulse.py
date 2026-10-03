import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_phase2.project_pulse import ProjectPulseClient


BASE = {
    "JAMES_PROJECT_PULSE_ENABLED": "1",
    "JAMES_PROJECT_PULSE_URL": "https://open-remote-computer.example/internal/project-pulse",
    "JAMES_PROJECT_PULSE_TOKEN": "project-pulse-test-secret-0123456789abcdef",
}


class ProjectPulseClientTests(unittest.TestCase):
    def test_disabled_never_calls_transport(self):
        transport = Mock()
        client = ProjectPulseClient({}, transport=transport)
        self.assertEqual(client.fetch(), {"status": "disabled", "items": []})
        transport.assert_not_called()

    def test_valid_payload_is_bounded_and_metadata_only(self):
        transport = Mock(return_value={
            "version": 1,
            "generatedAt": "2026-10-03T21:00:00Z",
            "missions": [{
                "title": "Kynlo orchestration review",
                "projectKey": "kynlo-orchestration",
                "branch": "fix/orc-orchestration-20261003",
                "state": "running",
                "verificationState": "tests passing",
                "nextAction": "Finish bounded acceptance",
                "client": "codex",
                "updatedAt": "2026-10-03T20:59:00Z",
                "workspacePath": "/Users/private/repo",
                "deviceId": "dev-secret",
                "recentEvents": [{"command": "cat ~/.ssh/id_rsa"}],
            }],
        })
        client = ProjectPulseClient(BASE, transport=transport)
        result = client.fetch()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["items"], [{
            "title": "Kynlo orchestration review",
            "project": "kynlo-orchestration",
            "branch": "fix/orc-orchestration-20261003",
            "state": "running",
            "verification": "tests passing",
            "nextAction": "Finish bounded acceptance",
            "client": "codex",
            "updatedAt": "2026-10-03T20:59:00Z",
        }])
        encoded = str(result)
        self.assertNotIn("/Users/private/repo", encoded)
        self.assertNotIn("dev-secret", encoded)
        self.assertNotIn("id_rsa", encoded)

    def test_invalid_endpoint_or_token_fails_closed_without_transport(self):
        for values in (
            dict(BASE, JAMES_PROJECT_PULSE_URL="http://example.test/internal/project-pulse"),
            dict(BASE, JAMES_PROJECT_PULSE_URL="https://example.test/other"),
            dict(BASE, JAMES_PROJECT_PULSE_TOKEN="short"),
        ):
            with self.subTest(values=values):
                transport = Mock()
                result = ProjectPulseClient(values, transport=transport).fetch()
                self.assertEqual(result, {"status": "unavailable", "items": []})
                transport.assert_not_called()

    def test_unauthorized_is_distinct_but_nonfatal(self):
        error = urllib.error.HTTPError(
            BASE["JAMES_PROJECT_PULSE_URL"], 401, "unauthorized", hdrs=None, fp=None
        )
        result = ProjectPulseClient(BASE, transport=Mock(side_effect=error)).fetch()
        self.assertEqual(result, {"status": "unauthorized", "items": []})


if __name__ == "__main__":
    unittest.main()
