"""The documented results test producer (scripts/results_test_producer.py): signs exact bytes, marks test, keeps secrets out
of argv and output, refuses plain http to remote hosts. No network."""
import contextlib
import importlib.util
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from postriff_phase2.results import signing

SPEC = importlib.util.spec_from_file_location("results_test_producer", Path(__file__).resolve().parents[1] / "scripts/results_test_producer.py")
producer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(producer)
CONNECTION = "6f1c0f5e-7b0c-4c39-a4a5-6b8c2b0c9d11"


class TestProducerTest(unittest.TestCase):
    def setUp(self):
        self.secret = signing.new_secret()

    def test_signed_request_verifies_and_is_marked_test(self):
        args = producer.argparse.Namespace(event_id="test-1", type="sale", occurred_at=None, amount=4500, currency="USD", ref="AbCdEfGhIj01.20261001",
                                           campaign="spring", reversal_of=None)
        event = producer.build_event(args, 1_790_870_000)
        url, headers, body = producer.build_request("http://127.0.0.1:4331", CONNECTION, self.secret, event, 1_790_870_000)
        self.assertEqual(url, f"http://127.0.0.1:4331/api/results/webhook/{CONNECTION}")
        self.assertEqual(signing.verify(headers["X-Rafii-Signature"], body, [self.secret], 1_790_870_010)["keyIndex"], 0)
        sent = json.loads(body)
        self.assertEqual((sent["test"], sent["amount"], sent["rafii_ref"]), (True, {"minor": 4500, "currency": "usd"}, "AbCdEfGhIj01.20261001"))

    def test_refuses_plain_http_to_remote_hosts_and_bad_inputs(self):
        event = {"eventId": "e", "type": "lead", "occurredAt": "2026-10-01T00:00:00Z", "test": True}
        for base, secret, connection in (("http://example.org", self.secret, CONNECTION), ("ftp://127.0.0.1", self.secret, CONNECTION),
                                         ("https://example.org", "", CONNECTION), ("https://example.org", "not-a-secret", CONNECTION),
                                         ("https://example.org", self.secret, "nope")):
            with self.assertRaises(ValueError):
                producer.build_request(base, connection, secret, event, 1)

    def test_secret_comes_from_the_environment_and_is_never_printed(self):
        out = io.StringIO()
        with patch.dict(os.environ, {"RAFII_RESULTS_SECRET": self.secret}), contextlib.redirect_stdout(out):
            code = producer.main([CONNECTION, "--dry-run", "--type", "lead"])
        self.assertEqual(code, 0)
        self.assertNotIn(self.secret, out.getvalue())
        printed = json.loads(out.getvalue())
        self.assertTrue(printed["body"]["test"])
        with patch.dict(os.environ, {"RAFII_RESULTS_SECRET": ""}), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(producer.main([CONNECTION, "--dry-run"]), 2)


if __name__ == "__main__":
    unittest.main()
