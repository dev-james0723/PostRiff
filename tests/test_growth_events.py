"""R-MET-03 event taxonomy: allowlisted properties, dedupe shape, never raising into the caller."""
import json
import unittest

from postriff_phase2 import growth_events


class Cursor:
    def __init__(self, fail_on_insert=False):
        self.statements, self.rowcount, self.fail = [], 1, fail_on_insert

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        if self.fail and sql.startswith("INSERT"):
            raise RuntimeError("relation does not exist")


class GrowthEventsTest(unittest.TestCase):
    def test_taxonomy_names_match_shared_writer_rules(self):
        for event in growth_events.TAXONOMY:
            self.assertRegex(event, r"^[a-z][a-z_]{0,39}\.[a-z][a-z_]{0,39}$")
            self.assertLessEqual(len(event), 60)

    def test_properties_allow_only_enums_and_counts(self):
        props = growth_events.properties("visual_pack.exported", {
            "handoff": "assisted_export", "slides": 6, "revision": 3,
            "caption": "Spring sale 20% off", "email": "a@example.com", "slidesFloat": 6.0,
            "url": "https://example.com/x", "handoffBad": "Has Spaces"})
        self.assertEqual(props, {"handoff": "assisted_export", "slides": 6, "revision": 3})
        self.assertEqual(growth_events.properties("draft.accepted", {"revision": True, "origin": "Continuation"}), {})
        self.assertEqual(growth_events.properties("week.completed", {"slots": 2_000_000}), {})

    def test_emit_dedupes_on_entity_revision_and_uses_savepoint(self):
        cur = Cursor()
        self.assertTrue(growth_events.emit(cur, workspace_id="w", event="draft.accepted", entity_id="v_1", revision=2,
                                           user_id="u", values={"origin": "continuation", "revision": 2}))
        insert = next(p for s, p in cur.statements if s.startswith("INSERT"))
        self.assertEqual(insert[4], "draft.accepted:v_1:2")
        self.assertEqual(json.loads(insert[3]), {"origin": "continuation", "revision": 2})
        self.assertEqual(cur.statements[0][0], "SAVEPOINT growth_event")

    def test_failure_never_raises_into_the_product_action(self):
        cur = Cursor(fail_on_insert=True)
        self.assertFalse(growth_events.emit(cur, workspace_id="w", event="result.ingested", entity_id="r", values={}))
        self.assertIn("ROLLBACK TO SAVEPOINT growth_event", [s for s, _ in cur.statements])

    def test_unknown_event_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            growth_events.emit(Cursor(), workspace_id="w", event="made.up", entity_id="x")


if __name__ == "__main__":
    unittest.main()
