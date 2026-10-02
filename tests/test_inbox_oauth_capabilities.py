"""Reconnects preserve independently verified capabilities when the new grant still has their scopes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_phase2.oauth import OAuthService


class Provider:
    platform = "Threads"
    production_reviewed = True
    assisted_fallback = False
    native_schedule = False
    capability_version = 1
    SCOPES = {
        "publish": ["basic", "publish"],
        "schedule": ["basic", "publish"],
        "analytics": ["basic", "insights"],
        "comments_read": ["basic", "read_replies"],
        "reply": ["basic", "manage_replies"],
    }

    def capability_scopes(self, capability):
        return self.SCOPES.get(capability, [])


def verified(level="Direct"):
    return {"level": level, "evidence": "Previously verified", "capabilityVersion": 1, "verifiedAt": 100.0}


class CapabilityReconnect(unittest.TestCase):
    def test_comments_reconnect_preserves_publish_and_analytics(self):
        old = {"publish": verified(), "analytics": verified(), "schedule": verified("Assisted")}
        granted = ["basic", "publish", "insights", "read_replies"]
        matrix = OAuthService._capabilities(Provider(), "comments_read", granted, [], 200.0, existing=old)
        self.assertEqual(matrix["publish"], old["publish"])
        self.assertEqual(matrix["analytics"], old["analytics"])
        self.assertEqual(matrix["schedule"], old["schedule"])
        self.assertEqual(matrix["comments_read"]["level"], "Direct")

    def test_reply_reconnect_preserves_comments(self):
        old = {"comments_read": verified()}
        matrix = OAuthService._capabilities(Provider(), "reply", ["basic", "read_replies", "manage_replies"], [], 200.0, existing=old)
        self.assertEqual(matrix["comments_read"], old["comments_read"])
        self.assertEqual(matrix["reply"]["level"], "Direct")

    def test_authoritative_scope_loss_downgrades_with_evidence(self):
        old = {"publish": verified()}
        matrix = OAuthService._capabilities(Provider(), "comments_read", ["basic", "read_replies"], [], 200.0, existing=old)
        self.assertEqual(matrix["publish"]["level"], "Unsupported")
        self.assertIn("scope", matrix["publish"]["evidence"].lower())


if __name__ == "__main__":
    unittest.main()
