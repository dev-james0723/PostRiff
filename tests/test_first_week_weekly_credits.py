"""Weekly drafting under Pricing v2 (R-COM-02/03) and first-week destinations (R-FWR-02), without a database."""
import contextlib
import types
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker import weekly_operator
from postriff_phase2.coworker.service import CoworkerService

NOW = 1_790_870_000.0


class Repo:
    @contextlib.contextmanager
    def transaction(self, token, workspace_id):
        yield object(), (7, {}), "owner-1"


class Ledger:
    def __init__(self, mode, policy):
        self.mode, self.credits = mode, types.SimpleNamespace(policy=lambda cur, wid: policy)

    def ensure_entitlement(self, cur, wid, plan):
        return None

    def growth_mode(self, cur, wid):
        return self.mode


class Requests:
    def __init__(self, ceiling, available=10_000_000):
        self.ceiling, self.available, self.issued = ceiling, available, []

    def estimate(self, wid, token, body):
        assert "idempotencyKey" not in body["request"]
        return {"ceilingMilliCredits": self.ceiling, "availableMilliCredits": self.available, "stateRevision": 7}

    def issue(self, wid, token, body):
        self.issued.append(body)
        return {"quoteId": "q-1", "maxMilliCredits": body["maxMilliCredits"]}


def ideas(mode="managed_credits", policy="credits-v2-2026-09-28", paid=True, ceiling=40_000):
    return types.SimpleNamespace(repository=Repo(), ledger=Ledger(mode, policy), credit_requests=Requests(ceiling),
                                 _select_runtime=lambda model: types.SimpleNamespace(cost_class="paid" if paid else "local"))


class SlotQuoteTest(unittest.TestCase):
    def service(self, spent=0):
        svc = CoworkerService.__new__(CoworkerService)
        svc._week_spend = lambda wid, week_id: spent
        return svc

    recipe = {"maxCostUsdMicroPerWeek": 2_000_000}
    week = {"id": "wk_1", "conversationId": "c-1"}
    payload = {"text": "t", "idempotencyKey": "weekly:wk_1:sl_1:0", "research": False, "model": None}

    def test_free_never_drafts_with_ai(self):
        out = self.service()._slot_credit_quote(ideas(mode="free", policy=None), "w", "tok", self.recipe, self.week, dict(self.payload))
        self.assertEqual(out["costState"], "requires_upgrade")

    def test_legacy_or_unpaid_writer_needs_no_quote(self):
        self.assertEqual(self.service()._slot_credit_quote(ideas(mode="legacy", policy=None), "w", "tok", self.recipe, self.week, dict(self.payload)), {})
        self.assertEqual(self.service()._slot_credit_quote(ideas(paid=False), "w", "tok", self.recipe, self.week, dict(self.payload)), {})

    def test_managed_credits_issue_a_quote_for_the_exact_request(self):
        writer = ideas(ceiling=40_000)
        out = self.service(spent=0)._slot_credit_quote(writer, "w", "tok", self.recipe, self.week, dict(self.payload))
        self.assertEqual(out["quoteId"], "q-1")
        issued = writer.credit_requests.issued[0]
        self.assertEqual((issued["operation"], issued["conversationId"], issued["expectedRevision"], issued["maxMilliCredits"]), ("turn", "c-1", 7, 40_000))
        self.assertEqual(issued["request"]["idempotencyKey"], "weekly:wk_1:sl_1:0")   # same request the turn sends

    def test_week_limit_and_wallet_bound_the_quote(self):
        # $2.00 limit = 600,000 milli-credits; $1.99 spent leaves 3,000 — below a 40,000 ceiling.
        out = self.service(spent=1_990_000)._slot_credit_quote(ideas(ceiling=40_000), "w", "tok", self.recipe, self.week, dict(self.payload))
        self.assertEqual(out["costState"], "over_limit")
        poor = ideas(ceiling=40_000)
        poor.credit_requests.available = 10
        out = self.service()._slot_credit_quote(poor, "w", "tok", self.recipe, self.week, dict(self.payload))
        self.assertEqual(out["costState"], "insufficient_credits")
        self.assertEqual(poor.credit_requests.issued, [])


class FirstWeekRecipeTest(unittest.TestCase):
    state = {"phase2": {"channels": [{"id": "ch1", "platform": "LinkedIn", "account": "A"}]}, "sources": []}

    def recipe(self, **values):
        payload = {"goals": ["Teach one skill"], "timeZone": "Asia/Hong_Kong", **values}
        return weekly_operator.validate_recipe(payload, self.state)

    def test_first_week_may_plan_one_platform_without_an_account(self):
        value = self.recipe(firstWeek=True, destinations=[{"channelId": None, "platform": "Threads", "postsPerWeek": 3}])
        self.assertEqual(value["destinations"][0]["channelId"], None)
        self.assertTrue(value["firstWeek"])
        week = weekly_operator.plan_week({**self.state, "sources": []}, {**value, "id": "wr_1", "version": 1}, NOW)
        self.assertEqual(len(week["slots"]), 3)
        self.assertTrue(all(s["publishBlocker"] == "channel_not_connected" for s in week["slots"]))
        self.assertTrue(all(s["status"] in ("needs_source", "planned") for s in week["slots"]))

    def test_unconnected_destination_is_refused_outside_the_first_week(self):
        for values in ({"destinations": [{"channelId": None, "platform": "Threads"}]},
                       {"firstWeek": True, "destinations": [{"channelId": None, "platform": "Myspace"}]},
                       {"firstWeek": True, "destinations": [{"channelId": None, "platform": "Threads"}, {"channelId": "ch1"}]}):
            with self.assertRaises(AlphaError, msg=repr(values)):
                self.recipe(**values)

    def test_connected_recipes_are_unchanged(self):
        value = self.recipe(destinations=[{"channelId": "ch1", "postsPerWeek": 2}])
        self.assertNotIn("firstWeek", value)
        week = weekly_operator.plan_week(self.state, {**value, "id": "wr_2", "version": 1}, NOW)
        self.assertTrue(all("publishBlocker" not in s for s in week["slots"]))


class FirstWeekAuthorityTest(unittest.TestCase):
    """The first week's limit authorises one frozen week, never a weekly habit (PRD R-COM-02; R-FWR-02)."""

    def state(self):
        return {"phase2": {"channels": [{"id": "ch1", "platform": "Threads", "account": "A"}]}, "sources": []}

    def first_week(self, state):
        payload = {"goals": ["Teach one skill"], "timeZone": "UTC", "firstWeek": True, "maxCostUsdMicroPerWeek": 1_000_000,
                   "destinations": [{"channelId": None, "platform": "Threads", "postsPerWeek": 3}]}
        return weekly_operator.save_recipe(state, payload, "owner", NOW)

    def test_a_first_week_recipe_is_never_due_however_late(self):
        state = self.state()
        recipe = self.first_week(state)
        self.assertEqual(recipe["status"], "active")
        for later in (0, 2, 9, 30, 365):   # NOW is a Thursday; +2 and +9 days are past Friday's planning moment
            self.assertFalse(weekly_operator.due(recipe, NOW + later * 86400))
        ordinary = weekly_operator.save_recipe(state, {"goals": ["Teach"], "timeZone": "UTC", "destinations": [{"channelId": "ch1", "postsPerWeek": 2}]}, "owner", NOW)
        self.assertTrue(weekly_operator.due(ordinary, NOW + 2 * 86400))

    def test_it_stays_one_time_until_the_owner_saves_it_in_weekly_plan(self):
        state = self.state()
        recipe = self.first_week(state)
        recipe["firstWeekId"] = "wk_first"
        # First Week Ready re-saving its own recipe (planning again, setting this week's limit) keeps it one-time.
        weekly_operator.save_recipe(state, {"goals": ["Teach"], "timeZone": "UTC", "firstWeek": True, "maxCostUsdMicroPerWeek": 2_000_000,
                                            "destinations": [{"channelId": None, "platform": "Threads", "postsPerWeek": 3}]}, "owner", NOW, recipe["id"])
        self.assertEqual((recipe["firstWeek"], recipe["firstWeekId"]), (True, "wk_first"))
        self.assertEqual(weekly_operator.first_week_id(state, recipe), "wk_first")
        self.assertFalse(weekly_operator.due(recipe, NOW + 30 * 86400))
        # Pausing and resuming is not a choice to draft every week.
        weekly_operator.set_recipe_status(state, recipe["id"], "paused", NOW)
        weekly_operator.set_recipe_status(state, recipe["id"], "active", NOW)
        self.assertTrue(weekly_operator.first_week_only(recipe))
        # The Weekly plan form (which never sends `firstWeek`) saved by the owner turns on recurring drafting.
        weekly_operator.save_recipe(state, {"goals": ["Teach"], "timeZone": "UTC", "maxCostUsdMicroPerWeek": 1_500_000,
                                            "destinations": [{"channelId": "ch1", "postsPerWeek": 3}]}, "owner", NOW, recipe["id"])
        self.assertNotIn("firstWeek", recipe)
        self.assertNotIn("firstWeekId", recipe)
        self.assertTrue(weekly_operator.due(recipe, NOW + 2 * 86400))

    def test_the_journey_names_the_week_for_recipes_saved_before_the_week_id_was_kept(self):
        state = self.state()
        recipe = self.first_week(state)
        state["coworker"]["firstWeek"] = {"recipeId": recipe["id"], "weekId": "wk_journey"}
        self.assertEqual(weekly_operator.first_week_id(state, recipe), "wk_journey")
        state["coworker"]["firstWeek"] = {"recipeId": "wr_other", "weekId": "wk_journey"}
        self.assertIsNone(weekly_operator.first_week_id(state, recipe))


class WeeklyPrepareFirstWeekGuardTest(unittest.TestCase):
    """`weekly_prepare` (the Weekly route, the agent tool and cron) never plans another week from a first-week recipe."""

    def test_only_the_first_week_is_prepared(self):
        from unittest import mock
        state = {"phase2": {"channels": []}, "sources": []}
        recipe = weekly_operator.save_recipe(state, {"goals": ["Teach"], "timeZone": "UTC", "firstWeek": True,
                                                     "destinations": [{"channelId": None, "platform": "Threads", "postsPerWeek": 2}]}, "owner", NOW)
        first = weekly_operator.plan_week(state, recipe, NOW)
        recipe["firstWeekId"] = first["id"]
        repo = types.SimpleNamespace(get=lambda wid, token: {"state": state, "revision": 1}, effects=[])
        svc = CoworkerService.__new__(CoworkerService)
        svc.hosted, svc.values, svc.clock = types.SimpleNamespace(repository=repo), {}, lambda: NOW + 14 * 86400
        advanced = []
        with mock.patch.object(CoworkerService, "_require", lambda self, flag: None), \
                mock.patch.object(CoworkerService, "_command_as", lambda *a, **k: advanced.append("planned")), \
                mock.patch.object(CoworkerService, "_advance", lambda self, *a, **k: advanced.append("advanced") or {"week": first}):
            with self.assertRaises(AlphaError) as caught:
                svc.weekly_prepare("w", "tok", recipe["id"])   # two weeks later: "next week" is not the first week
            self.assertEqual((caught.exception.status, caught.exception.code), (409, "weekly_drafting_not_enabled"))
            self.assertEqual(advanced, [])
            import datetime
            svc.weekly_prepare("w", "tok", recipe["id"], week_of=datetime.date.fromisoformat(first["weekOf"]))
            self.assertEqual(advanced, ["planned", "advanced"])


if __name__ == "__main__":
    unittest.main()
