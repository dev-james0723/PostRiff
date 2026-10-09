"""Lane B against the REAL generated assets (lane C, D-A30) and the REAL capability manifests (lane D) for every journey:
the presenter plan builds for J01-J08 (consumer) and J09 (founder), its validator policy equals C's precomputed component set,
its read bindings equal D's manifest, every binding is described with its argument schema and result shape, the prompt files
match their recorded hashes, and the deterministic ceiling stays inside a normal Manager turn's room. No provider call.
"""
import unittest

from postriff_phase2.agent_runtime_v2 import ui_capabilities, ui_contracts as contracts, ui_presenter as p
from postriff_phase2.agent_runtime_v2.ui_http import UiAuth
from postriff_phase2.permissions import Membership

from test_agent_ui_stream_fakes import ME, WS, make_cfg

FOUNDER_KEY = "founder:operator:production"


def _auth(scope="workspace"):
    return UiAuth(workspace_id=WS, principal=ME, member=Membership("owner"), role="owner", scope=scope, scope_key=FOUNDER_KEY if scope == "founder" else "")


class RealAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = p.load_assets()
        cls.cfg = make_cfg()

    def projection(self, journey):
        return {"journey_ids": [journey], "component_group_ids": list(self.assets.data["journeys"][journey]["groups"]), "allowed_context": {"counts": {"items": 2}},
                "egress_decision": {"allowed": True, "provider": "openai"}}

    def check(self, journey, scope, library):
        projection = self.projection(journey)
        manifest = ui_capabilities.build_manifest(None, _auth(scope), projection, scope=scope)
        plan = p.build_plan(self.cfg, self.assets, projection, manifest)
        self.assertEqual(plan.library, library)
        self.assertEqual(plan.prompt_key, f"{library}:{journey}:generate")
        expected_components = self.assets.data["prompts"][plan.prompt_key].get("components")
        if expected_components:
            self.assertEqual(sorted(plan.policy["allowedComponents"]), sorted(expected_components))
        self.assertEqual(plan.policy["rootName"], self.assets.library(library)["root"])
        self.assertEqual(plan.policy["founder"], library == "founder")
        self.assertEqual(plan.policy["readBindings"], [q["name"] for q in manifest["queries"]])
        self.assertEqual(plan.policy["actionIds"], [a["actionId"] for a in manifest["actions"]])
        self.assertEqual(plan.library_hash, self.assets.library(library)["libraryHash"])
        for query in manifest["queries"]:
            self.assertIn(f"- {query['name']}: ", plan.instructions)
            # D-A52: every real binding carries its call line, generated from its argument schema.
            self.assertIn(f"    call: {p.statement_name(query['name'])} = Query(\"{query['name']}\", {{", plan.instructions)
            self.assertIn(" ".join(str(query.get("description") or "").split()), plan.instructions, f"{query['name']} description is whole")
            shape = p.data_shape(query)
            self.assertIsNotNone(shape, query["name"])
            for rows in (shape.get("lists") or {}):
                self.assertIn(f'rowsField "{rows}"', plan.instructions)
        for action in manifest["actions"]:
            self.assertIn(f"- {action['actionId']}: ", plan.instructions)
        for secret in ("principal", "actionTargets", "queryConstraints", ME):
            self.assertNotIn(secret, plan.instructions + plan.input_text)
        self.assertLessEqual(len(plan.instructions.encode("utf-8")), 64 * 1024, "prompt stays bounded")
        # A normal Manager turn (gpt-6-sol ceiling 88 000 µUSD) leaves room for an attempt and its repair.
        self.assertLess(2 * plan.ceiling_usd_micro, 88_000 - 40_000)
        return plan, manifest

    def test_every_consumer_journey_builds_a_grounded_plan(self):
        for journey in contracts.CONSUMER_JOURNEYS:
            with self.subTest(journey=journey):
                self.check(journey, "workspace", "consumer")

    def test_no_registered_binding_description_is_cut(self):
        from postriff_phase2.agent_runtime_v2 import ui_domain
        for name, binding in ui_domain.QUERIES.items():
            self.assertLessEqual(len(" ".join(binding.description.split())), p.DESCRIPTION_CHARS, name)

    def test_j02_collision_contract(self):
        # Run 3 J02-b "do any time slots collide?": the agenda answers it (data.derived.closeTogether); slot_check checks one proposed
        # time and is empty until one is picked. Both descriptions now say so, whole (D-A52).
        plan, _manifest = self.check("J02", "workspace", "consumer")
        agenda = plan.instructions.split("- calendar_agenda: ", 1)[1].split("\n", 1)[0]
        slot = plan.instructions.split("- slot_check: ", 1)[1].split("\n", 1)[0]
        self.assertIn("collide", agenda)
        self.assertIn("data.derived.closeTogether.pairs", agenda)
        self.assertIn("ONE proposed local time", slot)
        self.assertIn("for posts that already collide, use calendar_agenda", slot)
        self.assertIn('call: calendarAgendaData = Query("calendar_agenda", {}, null)', plan.instructions)
        self.assertIn('optional keys: start "YYYY-MM-DD"; end "YYYY-MM-DD"; zone "Area/City"', plan.instructions)

    def test_founder_journey_uses_the_founder_library_and_is_read_only(self):
        plan, manifest = self.check("J09", "founder", "founder")
        self.assertEqual(manifest["actions"], [])
        self.assertNotIn("ActionButton", plan.policy["allowedComponents"])

    def test_founder_journey_is_refused_on_a_consumer_manifest(self):
        projection = self.projection("J09")
        with self.assertRaises(Exception):
            p.build_plan(self.cfg, self.assets, projection, ui_capabilities.build_manifest(None, _auth(), projection, scope="workspace"))

    def test_patch_prompts_exist_for_every_journey(self):
        for journey in contracts.JOURNEYS:
            library = "founder" if journey == "J09" else "consumer"
            key, text = self.assets.prompt(library, [journey], "patch")
            self.assertEqual(key, f"{library}:{journey}:patch")
            self.assertTrue(text.strip())


if __name__ == "__main__":
    unittest.main()
