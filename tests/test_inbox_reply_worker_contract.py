"""The hosted worker exposes a fenced Inbox reply worker, disabled by default."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_phase2.hosted_worker import AudienceReplyWorker


class ReplyWorkerContract(unittest.TestCase):
    def test_default_disabled(self):
        class Audience:
            reply_sender_enabled = False

        worker = AudienceReplyWorker(Audience())
        self.assertEqual(worker.tick(), {"processed": 0, "execution": "disabled"})


if __name__ == "__main__":
    unittest.main()
