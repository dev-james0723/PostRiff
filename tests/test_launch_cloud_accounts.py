"""Account-safe cloud drafting: external transport is never used by these tests."""
import json
import unittest
from postriff_phase2.model_runtime import ServerModelRuntime, _Retry

DESTINATIONS = [
    {"platform": "Instagram", "language": "en-US", "channelId": "account-a", "account": "@a"},
    {"platform": "Instagram", "language": "en-US", "channelId": "account-b", "account": "@b"},
]

def item(account, text):
    return {"platform": "Instagram", "language": "en-US", "channelId": account, "text": text, "sourceIds": []}

class CloudAccountTests(unittest.TestCase):
    def test_request_preserves_account_identity(self):
        data = ServerModelRuntime._user_payload({"context": {"sources": []}, "destinations": DESTINATIONS})
        self.assertEqual([d.get("channelId") for d in data["destinations"]], ["account-a", "account-b"])

    def test_reordered_response_is_matched_to_account(self):
        raw = json.dumps({"variants": [item("account-b", "Second account."), item("account-a", "First account.")]})
        result = ServerModelRuntime._parse(raw, DESTINATIONS)
        self.assertEqual([v["text"] for v in result], ["First account.", "Second account."])

    def test_ambiguous_unkeyed_response_is_rejected(self):
        raw = json.dumps({"variants": [{"platform": "Instagram", "language": "en-US", "text": "Ambiguous."}]})
        with self.assertRaises(_Retry):
            ServerModelRuntime._parse(raw, DESTINATIONS)

    def test_foreign_account_is_rejected(self):
        raw = json.dumps({"variants": [item("foreign", "Wrong account.")]})
        with self.assertRaises(_Retry):
            ServerModelRuntime._parse(raw, DESTINATIONS[:1])

    def test_duplicate_account_response_is_rejected(self):
        raw = json.dumps({"variants": [item("account-a", "First."), item("account-a", "Duplicate."), item("account-b", "Second.")]})
        with self.assertRaises(_Retry):
            ServerModelRuntime._parse(raw, DESTINATIONS)

    def test_single_legacy_destination_remains_supported(self):
        raw = json.dumps({"variants": [{"platform": "Instagram", "language": "en-US", "text": "One account."}]})
        result = ServerModelRuntime._parse(raw, DESTINATIONS[:1])
        self.assertEqual(result[0]["channelId"], "account-a")

if __name__ == "__main__":
    unittest.main()
