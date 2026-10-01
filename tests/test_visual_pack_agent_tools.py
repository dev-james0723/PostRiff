"""Visual Pack agent tools (AC28): typed effects and permissions, idempotent registration, voice parity, keys stable per
turn, and an export path that never publishes or queues and never accepts without the person's explicit request."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.agent_runtime_v2 import contracts, specialists, tool_adapter  # noqa: E402
from postriff_phase2.agent_runtime_v2.context import EffectLedger  # noqa: E402
from postriff_phase2.visual_pack import agent_tools  # noqa: E402


def view(state="draft", revision=1, export=None):
    slides = [{"position": i, "key": f"s{i}", "text": f"Slide {i}", "imageAssetId": None} for i in range(1, 7)]
    return {"pack": {"id": "11111111-2222-3333-4444-555555555555"}, "receipt": "r",
            "revision": {"revision": revision, "state": state, "sourceStatus": "current", "slides": slides, "export": export,
                         "checks": {"ok": True, "slides": [{"position": i, "ok": True, "findings": []} for i in range(1, 7)]}}}


class Service:
    def __init__(self, start="draft"):
        self.calls, self.state = [], start

    def _next(self, name, state):
        self.calls.append(name)
        self.state = state
        return view(state, export={"href": "/x", "handoff": "assisted_export"} if state == "export_ready" else None)

    def get(self, *_):
        self.calls.append("get")
        return view(self.state)

    def prepare(self, workspace_id, token, body):
        self.calls.append(("prepare", body["idempotencyKey"], body["variantId"], body["settings"]))
        return view()

    def edit(self, workspace_id, token, pack_id, body):
        self.calls.append(("edit", body))
        return view(revision=2)

    def render(self, *_):
        return self._next("render", "rendered")

    def accept(self, *_):
        return self._next("accept", "accepted")

    def export(self, *_):
        return self._next("export", "export_ready")

    def queue(self, *_):
        raise AssertionError("an agent tool must never queue")


class Ctx:
    def __init__(self, service):
        self.service = type("Hosted", (), {"visual_packs": service})()
        self.workspace_id, self.token, self.trace_id = "w", "t", "trace-0001"
        self.ledger = EffectLedger()


class Tools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        agent_tools.register()
        agent_tools.register()   # idempotent

    def test_typed_effects_permissions_and_voice_parity(self):
        expected = {"visual_pack_prepare": contracts.CREATE_DRAFT, "visual_pack_edit": contracts.MUTATE_REVERSIBLE, "visual_pack_export": contracts.MUTATE_REVERSIBLE}
        for name, effect in expected.items():
            spec = tool_adapter.REGISTRY[name].spec
            self.assertEqual((spec.effect, spec.permission, spec.voice, spec.approval), (effect, "edit", True, False), name)
            self.assertIn(name, specialists.EXTRA_SCOPES["creative"])
        self.assertIn("visual_pack_prepare", specialists.EXTRA_SCOPES["content"])
        self.assertFalse([n for n in tool_adapter.REGISTRY if n.startswith("visual_pack") and ("publish" in n or "queue" in n)])

    def test_prepare_uses_a_stable_per_turn_key_and_records_the_change(self):
        service, prepare = Service(), tool_adapter.REGISTRY["visual_pack_prepare"].executor
        first = prepare(Ctx(service), {"variantId": "v1", "palette": "rafii_dark"})
        prepare(Ctx(service), {"variantId": "v1", "palette": "rafii_dark"})
        self.assertTrue(first["ok"])
        self.assertEqual(first["slides"]["kind"], "APP_STATE")   # draft text reaches the model as data
        keys = [c[1] for c in service.calls]
        self.assertEqual(keys[0], keys[1])
        self.assertTrue(keys[0].startswith("agent-prep-") and 8 <= len(keys[0]) <= 80)
        self.assertEqual(service.calls[0][3], {"palette": "rafii_dark"})

    def test_edit_maps_positions_to_slide_keys(self):
        service = Service()
        ctx = Ctx(service)
        result = tool_adapter.REGISTRY["visual_pack_edit"].executor(ctx, {"packId": "p", "slides": [{"position": 2, "text": "New"}], "order": [2, 1, 3, 4, 5, 6], "weight": "bold"})
        body = service.calls[-1][1]
        self.assertTrue(result["ok"])
        self.assertEqual((body["expectedRevision"], body["slides"], body["order"][:2], body["settings"]), (1, [{"key": "s2", "text": "New"}], ["s2", "s1"], {"weight": "bold"}))
        self.assertEqual(ctx.ledger.changed[0]["type"], "visual_pack")
        bad = tool_adapter.REGISTRY["visual_pack_edit"].executor(Ctx(Service()), {"packId": "p", "order": [1, 1, 2, 3, 4, 5]})
        self.assertEqual(bad["code"], "unsupported_input")

    def test_export_renders_but_never_accepts_unless_asked_and_never_publishes(self):
        service = Service()
        held = tool_adapter.REGISTRY["visual_pack_export"].executor(Ctx(service), {"packId": "p"})
        self.assertEqual((held["ok"], held["code"]), (False, "approval_required"))
        self.assertEqual([c for c in service.calls if c != "get"], ["render"])
        done = tool_adapter.REGISTRY["visual_pack_export"].executor(Ctx(service), {"packId": "p", "accept": True})
        self.assertTrue(done["ok"])
        self.assertEqual([c for c in service.calls if c != "get"], ["render", "accept", "export"])
        self.assertIn("not published", done["note"])

    def test_service_refusals_come_back_as_typed_results(self):
        class Refusing(Service):
            def prepare(self, *_):
                raise AlphaError("This feature is not available.", 404, code="feature_disabled")
        out = tool_adapter.REGISTRY["visual_pack_prepare"].executor(Ctx(Refusing()), {"variantId": "v"})
        self.assertEqual((out["ok"], out["code"]), (False, "feature_disabled"))


if __name__ == "__main__":
    unittest.main()
