"""media_consent: owner-only, processor-bound consent for showing workspace photos and frames to a model (SPEC §5.12, §8.1)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import media_consent as mc  # noqa: E402
from postriff_phase2 import permissions  # noqa: E402
from postriff_phase2.permissions import Membership  # noqa: E402

VISION = {"id": "openai:gpt-6", "label": "OpenAI"}
IMAGE = {"id": "openai:gpt-image-2.5", "label": "OpenAI"}
NEW_VISION = {"id": "gateway:gemini-4", "label": "Vercel AI Gateway"}


def turn_on(state, processors=(VISION, IMAGE), actor="owner-1", now=100.0):
    return mc.apply_action(state, "media_egress", {"cloud": True, "confirmed": True}, actor, now, processors=list(processors))


class PermissionTests(unittest.TestCase):
    def test_owner_only(self):
        self.assertEqual(permissions.ACTION_CLASSES["media_egress"], "owner")
        self.assertEqual(permissions.classify("media_egress"), "owner")
        permissions.require_action(Membership("owner"), "media_egress")
        for role in ("admin", "editor", "approver", "viewer"):
            with self.subTest(role=role), self.assertRaises(AlphaError) as caught:
                permissions.require_action(Membership(role, {"can_publish": True, "can_reply": True, "can_moderate": True, "can_manage_connections": True}), "media_egress")
            self.assertEqual(caught.exception.status, 403)


class ProcessorTests(unittest.TestCase):
    def test_family_and_label(self):
        self.assertEqual(mc.processor("openai", "openai/gpt-6-sol"), {"id": "openai:gpt-6", "label": "OpenAI"})
        self.assertEqual(mc.processor("gateway", "google/gemini-4-flash"), {"id": "gateway:gemini-4", "label": "Vercel AI Gateway"})
        self.assertEqual(mc.processor("openai", "gpt"), {"id": "openai:gpt", "label": "OpenAI"})
        self.assertIsNone(mc.processor("", "x"))
        self.assertIsNone(mc.processor("openai", None))


class ActionTests(unittest.TestCase):
    def test_stamping(self):
        state = {}
        self.assertTrue(turn_on(state))
        self.assertEqual(state["mediaEgress"], {"cloud": True, "decidedBy": "owner-1", "decidedAt": 100.0, "processors": [VISION, IMAGE], "scope": ["photo", "video_frames", "photo_edit"]})
        self.assertTrue(mc.allowed(state, VISION))
        self.assertTrue(mc.allowed(state, "openai:gpt-image-2.5"))
        self.assertFalse(mc.allowed(state, NEW_VISION))

    def test_other_actions_not_consumed(self):
        self.assertFalse(mc.apply_action({}, "memory_egress", {"cloud": True, "confirmed": True}, "o", 1.0, processors=[VISION]))

    def test_confirmation_and_shape(self):
        for payload in ({"cloud": True}, {"cloud": True, "confirmed": "yes"}, {"cloud": "on", "confirmed": True}, {"cloud": True, "confirmed": True, "extra": 1}, None):
            with self.subTest(payload=payload), self.assertRaises(AlphaError) as caught:
                mc.apply_action({}, "media_egress", payload, "o", 1.0, processors=[VISION])
            self.assertEqual(caught.exception.status, 400)

    def test_client_processors_refused(self):
        state = {}
        with self.assertRaises(AlphaError) as caught:
            mc.apply_action(state, "media_egress", {"cloud": True, "confirmed": True, "processors": [NEW_VISION]}, "o", 1.0, processors=[VISION])
        self.assertEqual(caught.exception.status, 400)
        self.assertNotIn("mediaEgress", state)

    def test_no_reader_configured(self):
        with self.assertRaises(AlphaError) as caught:
            turn_on({}, processors=[])
        self.assertEqual(caught.exception.code, "reader_unavailable")

    def test_processor_change_needs_reconfirm(self):
        state = {}
        turn_on(state)
        before = mc.summary(state, {"vision": VISION, "image": IMAGE})
        self.assertFalse(before["reconfirm"])
        changed = mc.summary(state, {"vision": NEW_VISION, "image": IMAGE})
        self.assertTrue(changed["reconfirm"])
        self.assertFalse(mc.allowed(state, NEW_VISION))
        turn_on(state, processors=[NEW_VISION, IMAGE], now=200.0)
        self.assertEqual([p["id"] for p in state["mediaEgress"]["processors"]], [VISION["id"], IMAGE["id"], NEW_VISION["id"]])
        self.assertFalse(mc.summary(state, {"vision": NEW_VISION, "image": IMAGE})["reconfirm"])

    def test_revoke_clears_processors(self):
        state = {}
        turn_on(state)
        mc.apply_action(state, "media_egress", {"cloud": False, "confirmed": True}, "owner-1", 300.0)
        self.assertEqual(state["mediaEgress"]["processors"], [])
        self.assertFalse(mc.allowed(state, VISION))
        turn_on(state, processors=[IMAGE], now=400.0)
        self.assertEqual(state["mediaEgress"]["processors"], [IMAGE])   # a revoke is not remembered as consent

    def test_require(self):
        state = {}
        with self.assertRaises(AlphaError) as caught:
            mc.require(state, "vision", VISION)
        self.assertEqual((caught.exception.code, caught.exception.status), ("consent_required", 403))
        self.assertEqual(str(caught.exception), "The workspace owner hasn't allowed Rafii to look at photos and videos.")
        turn_on(state)
        mc.require(state, "vision", VISION)
        with self.assertRaises(AlphaError):
            mc.require(state, "audio", VISION)


class SummaryTests(unittest.TestCase):
    def test_absent_is_off(self):
        self.assertEqual(mc.summary({}, {"vision": VISION, "image": IMAGE}),
                         {"cloud": False, "decidedAt": None, "decidedBy": None, "processors": [], "current": {"vision": VISION, "image": IMAGE}, "reconfirm": False, "available": True})
        self.assertFalse(mc.summary({}, {"vision": None, "image": None})["available"])

    def test_on(self):
        state = {}
        turn_on(state)
        summary = mc.summary(state, {"vision": VISION, "image": IMAGE})
        self.assertEqual((summary["cloud"], summary["decidedBy"], summary["processors"]), (True, "owner-1", [VISION, IMAGE]))


if __name__ == "__main__":
    unittest.main()
