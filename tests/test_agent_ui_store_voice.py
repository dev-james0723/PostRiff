"""Lane F: text/voice selection continuity through the turn seam, and the shared phone runtime left untouched (G19).

`service.ui_turn_context` is the one place a turn (typed, panel or browser voice — the same `uiContext` field) reads a generated
view's stored selection through `ui_store.selection_context`. These tests pin that a disabled feature, a malformed reference or
a foreign/stale view never fails or slows a turn, that the selection reaches the Manager as ids/kinds plus a refs entry (never
titles), and that the phone runtime has no generated-view dependency at all (no outbound call is made by any test here).
"""
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    from postriff_alpha.domain import AlphaError
    from postriff_phase2.agent_runtime_v2 import config, service, ui_store
    AVAILABLE = True
except ImportError:      # service imports the Agents SDK; cloud CI installs it
    AVAILABLE = False

ROOT = Path(__file__).resolve().parents[1]
ART = "22222222-2222-4222-8222-222222222222"
WID = "11111111-1111-4111-8111-111111111111"
ME = "44444444-4444-4444-8444-444444444444"


class NoSql:
    def execute(self, *_a, **_k):
        raise AssertionError("no SQL expected")


def cfg(enabled=True):
    values = {"RAFII_AGENT_V2_ENABLED": "1", **({"RAFII_GENUI_ENABLED": "1"} if enabled else {})}
    return config.RuntimeConfig.from_environment(values)


class Member:
    role = "owner"

    def allows(self, _need):
        return True


@unittest.skipUnless(AVAILABLE, "agent runtime service needs the Agents SDK (cloud CI)")
class TurnSeam(unittest.TestCase):
    def setUp(self):
        self.original = ui_store.selection_context
        self.addCleanup(setattr, ui_store, "selection_context", self.original)

    def test_disabled_or_absent_context_touches_nothing(self):
        self.assertEqual(service.ui_turn_context(cfg(enabled=False), NoSql(), WID, ME, Member(), {"artifactId": ART}), (None, None))
        self.assertEqual(service.ui_turn_context(cfg(), NoSql(), WID, ME, Member(), None), (None, None))

    def test_malformed_reference_is_ignored_not_a_failed_turn(self):
        ui_store.selection_context = lambda *_a: self.fail("must not read a malformed reference")
        for raw in ({"artifactId": "nope"}, {"artifactId": ART, "extra": 1}, "x", {"artifactId": ART, "artifactRevision": -1}):
            self.assertEqual(service.ui_turn_context(cfg(), NoSql(), WID, ME, Member(), raw), (None, None), raw)

    def test_foreign_or_revoked_view_yields_no_selection(self):
        def missing(*_a):
            raise AlphaError("That view is unavailable.", 404, code="ui_artifact")
        ui_store.selection_context = missing
        context, selection = service.ui_turn_context(cfg(), NoSql(), WID, ME, Member(), {"artifactId": ART, "artifactRevision": 2, "stateRevision": 3})
        self.assertEqual(context, {"artifactId": ART, "artifactRevision": 2, "stateRevision": 3})
        self.assertIsNone(selection)

    def test_same_selection_for_text_and_voice(self):
        seen = []

        def selection(_cur, auth, ui_context):
            seen.append((auth.workspace_id, auth.principal, auth.scope, ui_context))
            return {"references": [{"type": "draft", "kind": "post", "id": "d2", "title": "Spring"}], "note": "1. draft d2"}
        ui_store.selection_context = selection
        raw = {"artifactId": ART, "artifactRevision": 2, "stateRevision": 3}
        typed = service.ui_turn_context(cfg(), NoSql(), WID, ME, Member(), raw)
        spoken = service.ui_turn_context(cfg(), NoSql(), WID, ME, Member(), dict(raw))
        self.assertEqual(typed, spoken)
        self.assertEqual(seen[0], (WID, ME, "workspace", raw))

    def test_selection_reaches_the_manager_as_ids_and_kinds_never_titles(self):
        source = (ROOT / "src/postriff_phase2/agent_runtime_v2/service.py").read_text()
        # The chips the Manager sees are built from kind/id/role only, and the selection note is a refs entry (a list item).
        self.assertIn('app_state["chips"] = [{"kind": c["kind"], "id": c["id"]', source)
        self.assertIn('"phrase": "selection in the interactive view"', source)
        refs = [{"type": "draft", "kind": "post", "id": "d2", "title": "Private title"}]
        chips = [{"kind": c["kind"], "id": c["id"], **({"role": c["role"]} if c.get("role") else {})} for c in refs]
        self.assertEqual(chips, [{"kind": "post", "id": "d2"}])


class PhoneRuntimeUntouched(unittest.TestCase):
    def test_phone_runtime_has_no_generated_view_dependency(self):
        phone = ROOT / "src/postriff_phase2/phone"
        if not phone.exists():
            self.skipTest("no phone runtime in this checkout")
        offenders = [str(p.relative_to(ROOT)) for p in phone.rglob("*.py")
                     if re.search(r"\bui_(store|stream|presenter|http|queries|actions)\b", p.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [], "phone mode shares the agent runtime but never mounts or calls generated views")

    def test_ui_store_imports_no_provider_or_phone_module(self):
        text = (ROOT / "src/postriff_phase2/agent_runtime_v2/ui_store.py").read_text(encoding="utf-8")
        for forbidden in ("import openai", "from agents", "from .phone", "from ..phone", "urllib.request", "import requests"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
