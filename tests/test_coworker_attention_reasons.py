"""A01: "What needs my attention?" explains every item. A source campaign that couldn't finish its drafts is surfaced
by the notification detector as `research.needs_input`; attention must give it a reason (an empty `why` failed A01 on
real PostgreSQL once a campaign was left needing input)."""
import re
import unittest
from pathlib import Path

from postriff_phase2.coworker import attention

ROOT = Path(__file__).resolve().parents[1]


class AttentionReasonTest(unittest.TestCase):
    def test_a_source_campaign_needing_input_is_explained(self):
        detector = (ROOT / "src/postriff_phase2/notifications/detector.py").read_text()
        self.assertIn("research.needs_input", set(re.findall(r'"event_type":\s*"([a-z_]+\.[a-z_]+)"', detector)))
        self.assertNotIn("research.needs_input", attention.SKIP)
        self.assertTrue(attention.WHY.get("research.needs_input"))


if __name__ == "__main__":
    unittest.main()
