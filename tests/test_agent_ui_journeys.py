"""Lane E — the journey index, examples and browser fixtures agree with lane D's real registry (rafii-genui/1).

The journey components (web/src/features/agent/generative-ui/components/journeys) read the `data` of lane D's bindings;
D's `ui_domain/shapes.py` is that contract. These tests fail on drift between:

- `generated/journey-examples/journeys.json` (which bindings/actions each journey's components and examples use) and
  D's per-journey allowlists (`JOURNEY_QUERIES` / `JOURNEY_ACTIONS`), including founder scope only in J09;
- the browser test snapshots `web/tests/agent-ui-journeys/fixtures/d-catalog.json` / `d-shapes.json` and D's live
  `catalog()` / `SHAPES` (the web tests check every view key and every example argument against those snapshots);
- every scenario fixture the web tests render and the keys D's handlers return.

    PYTHONPATH=src:tests python -m unittest tests.test_agent_ui_journeys
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from postriff_phase2.agent_runtime_v2 import ui_contracts, ui_domain
from postriff_phase2.agent_runtime_v2.ui_domain import shapes

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "src" / "postriff_phase2" / "agent_runtime_v2" / "generated" / "journey-examples"
FIXTURES = ROOT / "web" / "tests" / "agent-ui-journeys" / "fixtures"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _roundtrip(value):
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False))


class JourneyIndexAgreesWithDomainRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = _json(EXAMPLES / "journeys.json")
        cls.journeys = cls.index["journeys"]

    def test_all_nine_journeys_are_indexed_with_examples_and_an_edit_case(self):
        self.assertEqual(sorted(self.journeys), list(ui_contracts.JOURNEYS))
        for journey, entry in self.journeys.items():
            self.assertTrue(entry["examples"], journey)
            for example in entry["examples"]:
                self.assertTrue((EXAMPLES / example["file"]).is_file(), example["file"])
                self.assertTrue(example["file"].startswith(journey + "-"), example["file"])
            edit = entry["editCase"]
            self.assertTrue((EXAMPLES / edit["base"]).is_file(), edit["base"])
            self.assertTrue((EXAMPLES / edit["patch"]).is_file(), edit["patch"])
            self.assertTrue(edit["patch"].startswith("edits/"), "patches never sit beside full-program examples")
            self.assertIn({"patch": edit["patch"], "base": edit["base"]}, self.index["edits"])
            self.assertEqual(entry["scenarios"], ["normal", "empty", "denied", "partial", "failure"])

    def test_bindings_and_actions_are_in_each_journeys_manifest_allowlist(self):
        for journey, entry in self.journeys.items():
            for name in entry["bindings"]:
                self.assertIn(name, ui_domain.QUERIES, f"{journey}: {name} is not a D binding")
                self.assertIn(name, ui_domain.JOURNEY_QUERIES[journey], f"{journey}: {name} is not in its manifest")
            for action_id in entry["actions"]:
                self.assertIn(action_id, ui_domain.ACTIONS, f"{journey}: {action_id} is not a D action")
                self.assertIn(action_id, ui_domain.JOURNEY_ACTIONS[journey], f"{journey}: {action_id} is not in its manifest")

    def test_founder_bindings_only_in_j09_and_j09_is_read_only(self):
        for journey, entry in self.journeys.items():
            scopes = {ui_domain.QUERIES[name].scope for name in entry["bindings"]}
            if journey in ui_contracts.FOUNDER_JOURNEYS:
                self.assertEqual(scopes, {"founder"})
                self.assertEqual(entry["actions"], [])
                self.assertEqual(entry["library"], "founder")
            else:
                self.assertNotIn("founder", scopes, journey)
                self.assertEqual(entry["library"], "consumer")

    def test_prepare_only_actions_are_never_described_as_applied(self):
        prepared = {aid for aid, b in ui_domain.ACTIONS.items() if b.prepare_only}
        composite = self.index["composite"]["steps"]
        for step in composite:
            if step.get("action") in prepared:
                self.assertEqual(step["outcome"], "prepared", step)

    def test_composite_flow_runs_library_to_draft_to_campaign_and_calendar_in_one_conversation(self):
        steps = self.index["composite"]["steps"]
        self.assertEqual([s["journey"] for s in steps], ["J03", "J01", "J05", "J05"])
        self.assertEqual({s.get("action") for s in steps if s.get("action")}, {"campaign_link", "schedule_prepare"})
        for step in steps:
            self.assertIn(step["example"], [e["file"] for e in self.journeys[step["journey"]]["examples"]])
            if step.get("action"):
                self.assertIn(step["action"], self.journeys[step["journey"]]["actions"])
        self.assertIn("uiContext", self.index["composite"]["retains"])


class BrowserSnapshotsMatchDomain(unittest.TestCase):
    def test_catalog_snapshot_equals_the_live_registry(self):
        self.assertEqual(_json(FIXTURES / "d-catalog.json"), _roundtrip(ui_domain.catalog()),
                         "D's catalog changed: regenerate web/tests/agent-ui-journeys/fixtures/d-catalog.json and update the journey views")

    def test_shapes_snapshot_equals_the_live_contract(self):
        self.assertEqual(_json(FIXTURES / "d-shapes.json"),
                         _roundtrip({"shapes": shapes.SHAPES, "optional": shapes.OPTIONAL, "open": sorted(shapes.OPEN_SHAPES)}),
                         "D's data shapes changed: regenerate d-shapes.json and update the journey views")

    def test_every_rendered_fixture_has_only_keys_d_handlers_return(self):
        checked = 0
        for path in sorted(FIXTURES.glob("J0*-*.json")):
            for binding, scenarios in _json(path).items():
                if binding == "actions":
                    for action in scenarios:
                        self.assertIn(action["actionId"], ui_domain.ACTIONS, f"{path.name}: {action['actionId']}")
                    continue
                self.assertIn(binding, shapes.SHAPES, f"{path.name}: {binding}")
                shape = shapes.SHAPES[binding]
                required = shapes.required(binding)
                for scenario, envelope in scenarios.items():
                    self.assertIn(envelope["state"], ui_contracts.DATA_STATES, f"{path.name}:{binding}:{scenario}")
                    data = envelope["data"]
                    if scenario == "invalid" or not isinstance(data, dict) or binding in shapes.OPEN_SHAPES:
                        continue
                    extra = set(data) - set(shape["keys"])
                    self.assertFalse(extra, f"{path.name}:{binding}:{scenario} has keys D never returns: {sorted(extra)}")
                    if envelope["state"] not in ("denied", "unavailable"):
                        missing = set(required["keys"]) - set(data)
                        self.assertFalse(missing, f"{path.name}:{binding}:{scenario} lacks keys D always returns: {sorted(missing)}")
                    for list_key, row_keys in shape["lists"].items():
                        for row in data.get(list_key) or []:
                            row_extra = set(row) - set(row_keys)
                            self.assertFalse(row_extra, f"{path.name}:{binding}.{list_key} rows have unknown keys: {sorted(row_extra)}")
                            row_missing = set(required["lists"].get(list_key) or []) - set(row)
                            self.assertFalse(row_missing, f"{path.name}:{binding}.{list_key} rows lack keys D always returns: {sorted(row_missing)}")
                    checked += 1
        self.assertGreater(checked, 25)


if __name__ == "__main__":
    unittest.main()
