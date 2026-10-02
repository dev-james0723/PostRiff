"""R-OUT-01..03 pure rules: provenance classes, money, association window (AC16, AC18, AC19 pure cases)."""
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.results import model

NOW = 1_790_870_000.0          # 2026-10-01T15:53:20Z
DAY = 86400


class FirstPartyNormalizationTest(unittest.TestCase):
    def test_minimal_booking(self):
        event = model.normalize_first_party({"eventId": "bk_1", "type": "booking", "occurredAt": "2026-10-01T15:00:00Z"}, NOW)
        self.assertEqual(event["type"], "booking")
        self.assertIsNone(event["amount"])          # unavailable, not zero
        self.assertIsNone(event["ref"])
        self.assertFalse(event["test"])

    def test_money_only_on_booking_or_sale_and_currency_lowercased(self):
        sale = model.normalize_first_party({"eventId": "s1", "type": "sale", "occurredAt": NOW - 60, "amount": {"minor": 12000, "currency": "USD"}}, NOW)
        self.assertEqual(sale["amount"], {"minor": 12000, "currency": "usd"})
        with self.assertRaises(AlphaError) as caught:
            model.normalize_first_party({"eventId": "l1", "type": "lead", "occurredAt": NOW, "amount": {"minor": 1, "currency": "usd"}}, NOW)
        self.assertEqual(caught.exception.code, "result_amount_not_allowed")
        for bad in ({"minor": 1.5, "currency": "usd"}, {"minor": -1, "currency": "usd"}, {"minor": True, "currency": "usd"}, {"minor": 1, "currency": "dollars"}):
            with self.assertRaises(AlphaError):
                model.normalize_first_party({"eventId": "s2", "type": "sale", "occurredAt": NOW, "amount": bad}, NOW)

    def test_rejects_bad_ids_types_times(self):
        cases = [
            {"type": "lead", "occurredAt": NOW},
            {"eventId": "has space", "type": "lead", "occurredAt": NOW},
            {"eventId": "e", "type": "purchase", "occurredAt": NOW},
            {"eventId": "e", "type": "lead", "occurredAt": "yesterday"},
            {"eventId": "e", "type": "lead", "occurredAt": "2026-10-01T15:00:00"},       # no offset
            {"eventId": "e", "type": "lead", "occurredAt": NOW + 3600},                  # future
            {"eventId": "e", "type": "lead", "occurredAt": NOW, "reversalOf": "e"},      # cannot reverse itself
        ]
        for payload in cases:
            with self.assertRaises(AlphaError, msg=repr(payload)):
                model.normalize_first_party(payload, NOW)

    def test_malformed_ref_is_kept_as_unmatched_not_guessed(self):
        event = model.normalize_first_party({"eventId": "e", "type": "lead", "occurredAt": NOW, "rafii_ref": "alice@example.com"}, NOW)
        self.assertEqual(event["ref"], "invalid")
        self.assertEqual(model.associate(event["ref"], event["occurredAt"], {})["attribution"], "unattributed")

    def test_unknown_fields_are_not_carried(self):
        event = model.normalize_first_party({"eventId": "e", "type": "lead", "occurredAt": NOW, "email": "x@example.com", "name": "X"}, NOW)
        self.assertNotIn("email", event)
        self.assertNotIn("name", event)


class DeclarationTest(unittest.TestCase):
    def test_declared_result(self):
        value = model.normalize_declaration({"type": "sale", "occurredAt": "2026-09-30T10:00:00+08:00", "amount": {"minor": 280000, "currency": "twd"},
                                             "note": "  workshop   seat  ", "quantity": 2}, NOW)
        self.assertEqual(value["amount"], {"minor": 280000, "currency": "twd"})
        self.assertEqual(value["note"], "workshop seat")
        self.assertEqual(value["quantity"], 2)

    def test_declaration_cannot_be_click_or_future(self):
        with self.assertRaises(AlphaError):
            model.normalize_declaration({"type": "click", "occurredAt": NOW}, NOW)
        with self.assertRaises(AlphaError):
            model.normalize_declaration({"type": "lead", "occurredAt": NOW + 7200}, NOW)
        with self.assertRaises(AlphaError):
            model.normalize_declaration({"type": "lead", "occurredAt": NOW, "quantity": 0}, NOW)


class AssociationTest(unittest.TestCase):
    links = {"AbCdEfGhIj01": {"id": "link-1", "campaignRef": "cmp_1"}}

    def test_associated_inside_window(self):
        ref = model.make_ref("AbCdEfGhIj01", NOW - 3 * DAY)
        result = model.associate(ref, NOW, self.links)
        self.assertEqual(result["attribution"], "associated")
        self.assertEqual(result["linkId"], "link-1")
        self.assertEqual(result["definition"], model.ASSOCIATION_DEFINITION)

    def test_expired_window_and_before_click(self):
        old = model.make_ref("AbCdEfGhIj01", NOW - 31 * DAY)
        self.assertEqual(model.associate(old, NOW, self.links)["attribution"], "expired_window")
        future_click = model.make_ref("AbCdEfGhIj01", NOW + 2 * DAY)
        self.assertEqual(model.associate(future_click, NOW, self.links)["attribution"], "expired_window")
        edge = model.make_ref("AbCdEfGhIj01", NOW - 30 * DAY)
        self.assertEqual(model.associate(edge, NOW, self.links)["attribution"], "associated")

    def test_other_workspace_link_never_associates(self):
        ref = model.make_ref("ZZZZZZZZZZZZ", NOW)
        self.assertEqual(model.associate(ref, NOW, self.links)["attribution"], "not_this_workspace")

    def test_missing_or_bad_ref(self):
        for ref in (None, "invalid", "AbCdEfGhIj01", "AbCdEfGhIj01.20261399"):
            self.assertEqual(model.associate(ref, NOW, self.links)["attribution"], "unattributed", ref)


class SummaryTest(unittest.TestCase):
    def test_classes_stay_separate_reversals_net_and_currencies_do_not_mix(self):
        rows = [
            {"id": "a", "provenance": "first_party_reported", "type": "booking", "kind": "event", "quantity": 1,
             "amount": {"minor": 5000, "currency": "usd"}, "attribution": "associated"},
            {"id": "b", "provenance": "first_party_reported", "type": "booking", "kind": "event", "quantity": 1,
             "amount": {"minor": 9000, "currency": "twd"}, "attribution": "unattributed"},
            {"id": "c", "provenance": "first_party_reported", "type": "sale", "kind": "event", "quantity": 1,
             "amount": {"minor": 7000, "currency": "usd"}, "attribution": "associated"},
            {"id": "r", "provenance": "first_party_reported", "type": "sale", "kind": "reversal", "correctsId": "c", "quantity": 1},
            {"id": "d", "provenance": "user_declared", "type": "lead", "kind": "event", "quantity": 3, "amount": None, "attribution": "unattributed"},
        ]
        out = model.summarize(rows)
        first = out["first_party_reported"]
        self.assertEqual(first["counts"], {"booking": 2})
        self.assertEqual(first["reversed"], 1)
        self.assertEqual(first["money"], {"usd": {"minor": 5000, "events": 1}, "twd": {"minor": 9000, "events": 1}})
        self.assertEqual(out["user_declared"]["counts"], {"lead": 3})
        self.assertIsNone(out["provider_native"])        # unavailable, not zero

    def test_amendment_replaces_its_original_and_the_latest_amendment_wins(self):
        rows = [
            {"id": "o", "provenance": "user_declared", "type": "sale", "kind": "event", "quantity": 1,
             "amount": {"minor": 1000, "currency": "usd"}, "attribution": "unattributed"},
            {"id": "a1", "provenance": "user_declared", "type": "sale", "kind": "amendment", "correctsId": "o", "quantity": 2,
             "amount": {"minor": 2000, "currency": "usd"}, "attribution": "unattributed"},
            {"id": "a2", "provenance": "user_declared", "type": "booking", "kind": "amendment", "correctsId": "o", "quantity": 1,
             "amount": {"minor": 3000, "currency": "eur"}, "attribution": "associated"},
        ]
        out = model.summarize(rows)["user_declared"]
        self.assertEqual(out["counts"], {"booking": 1})                 # one result, never three
        self.assertEqual(out["money"], {"eur": {"minor": 3000, "events": 1}})
        self.assertEqual(out["associated"], 1)
        self.assertEqual(out["unattributed"], 0)

    def test_reversal_of_an_amended_result_withdraws_the_current_version(self):
        rows = [
            {"id": "o", "provenance": "user_declared", "type": "lead", "kind": "event", "quantity": 1, "amount": None, "attribution": "unattributed"},
            {"id": "a", "provenance": "user_declared", "type": "lead", "kind": "amendment", "correctsId": "o", "quantity": 4, "amount": None, "attribution": "unattributed"},
            {"id": "r", "provenance": "user_declared", "type": "lead", "kind": "reversal", "correctsId": "o", "quantity": 1},
        ]
        out = model.summarize(rows)["user_declared"]
        self.assertEqual(out["counts"], {})
        self.assertEqual(out["reversed"], 4)

    def test_grouped_rows_carry_their_own_reversed_flag_and_event_counts(self):
        """Aggregated rows (one per group, as the database returns them) summarize like the rows they stand for."""
        rows = [
            {"id": "g1", "provenance": "first_party_reported", "type": "booking", "kind": "event", "quantity": 5,
             "amount": {"minor": 25000, "currency": "usd"}, "events": 4, "attribution": "associated"},
            {"id": "g2", "provenance": "first_party_reported", "type": "booking", "kind": "event", "quantity": 2,
             "amount": None, "attribution": "unattributed"},
            {"id": "g3", "provenance": "first_party_reported", "type": "booking", "kind": "event", "quantity": 3,
             "amount": {"minor": 900, "currency": "usd"}, "events": 3, "attribution": "associated", "reversed": True},
        ]
        out = model.summarize(rows)["first_party_reported"]
        self.assertEqual(out["counts"], {"booking": 7})
        self.assertEqual(out["money"], {"usd": {"minor": 25000, "events": 4}})
        self.assertEqual(out["reversed"], 3)
        self.assertEqual((out["associated"], out["unattributed"]), (5, 2))

    def test_zero_is_not_unavailable(self):
        # A class whose only results were reversed is measured (all withdrawn), not unavailable.
        rows = [{"id": "o", "provenance": "user_declared", "type": "lead", "kind": "event", "quantity": 1, "amount": None, "attribution": "unattributed"},
                {"id": "r", "provenance": "user_declared", "type": "lead", "kind": "reversal", "correctsId": "o"}]
        out = model.summarize(rows)
        self.assertEqual(out["user_declared"]["counts"], {})
        self.assertEqual(out["user_declared"]["reversed"], 1)
        self.assertIsNone(out["first_party_reported"])


if __name__ == "__main__":
    unittest.main()
