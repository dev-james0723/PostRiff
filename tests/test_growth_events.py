"""R-MET-03 event taxonomy: allowlisted properties, dedupe shape, never raising into the caller."""
import json
import unittest
from unittest import mock

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

    W, U = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"

    def setUp(self):
        if growth_events._shared is not None:
            growth_events._shared.reset()   # a suspension from another test must not hide this one's write

    def check_written(self, cur, savepoint):
        insert = next(p for s, p in cur.statements if s.startswith("INSERT INTO public.pr_product_events"))
        self.assertEqual((insert[0], insert[1], insert[2], insert[4]), (self.W, self.U, "draft.accepted", "draft.accepted:v_1:2"))
        self.assertEqual(json.loads(insert[3]), {"origin": "continuation", "revision": 2})
        self.assertTrue(cur.statements[0][0].startswith(savepoint), cur.statements[0][0])

    def test_emit_goes_through_the_shared_founder_writer_when_present(self):
        self.assertIsNotNone(growth_events._shared, "Founder's product_events is part of production now")
        cur = Cursor()
        self.assertTrue(growth_events.emit(cur, workspace_id=self.W, event="draft.accepted", entity_id="v_1", revision=2,
                                           user_id=self.U, values={"origin": "continuation", "revision": 2}))
        self.check_written(cur, "SAVEPOINT product_event_")

    def test_emit_falls_back_to_the_identical_local_write(self):
        cur = Cursor()
        with mock.patch.object(growth_events, "_shared", None):
            self.assertTrue(growth_events.emit(cur, workspace_id=self.W, event="draft.accepted", entity_id="v_1", revision=2,
                                               user_id=self.U, values={"origin": "continuation", "revision": 2}))
        self.check_written(cur, "SAVEPOINT growth_event")

    def test_failure_never_raises_into_the_product_action(self):
        for shared in (growth_events._shared, None):
            cur = Cursor(fail_on_insert=True)
            with mock.patch.object(growth_events, "_shared", shared):
                self.assertFalse(growth_events.emit(cur, workspace_id=self.W, event="result.ingested", entity_id="r", values={}))
            self.assertTrue(any(s.startswith("ROLLBACK TO SAVEPOINT") for s, _ in cur.statements), shared)

    def test_non_uuid_workspace_is_never_written(self):
        self.assertFalse(growth_events.emit(Cursor(), workspace_id="w", event="result.ingested", entity_id="r"))

    def test_unknown_event_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            growth_events.emit(Cursor(), workspace_id="w", event="made.up", entity_id="x")


if __name__ == "__main__":
    unittest.main()
