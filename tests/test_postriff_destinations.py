"""Account identity in destinations (Rafii v9 §4/§5): two accounts on one platform stay distinct."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import agent_runtime, ideas, intent  # noqa: E402

NOW = 1_789_000_000.0
HK = "Asia/Hong_Kong"
SUPPORTED = ("LinkedIn", "Instagram", "Threads", "Xiaohongshu")


def parse(text):
    return intent.parse_request(text, NOW, HK, SUPPORTED)


class ResolveDestinationsTest(unittest.TestCase):
    def test_two_accounts_same_platform_are_two_destinations(self):
        requested = [{"platform": "Instagram", "language": "en-US", "channelId": "ig-1"}, {"platform": "Instagram", "language": "en-US", "channelId": "ig-2"}, {"platform": "LinkedIn", "language": "en-GB"}]
        out = intent.resolve_destinations(parse("A post about practice"), requested, None, ())
        self.assertEqual(out, [{"platform": "Instagram", "language": "en-US", "channelId": "ig-1"}, {"platform": "Instagram", "language": "en-US", "channelId": "ig-2"}, {"platform": "LinkedIn", "language": "en-GB"}])

    def test_same_account_selected_twice_collapses_and_languages_merge(self):
        requested = [{"platform": "Instagram", "language": "en-US", "channelId": "ig-1"}, {"platform": "Instagram", "language": "zh-Hant-HK", "channelId": "ig-1"}, {"platform": "Instagram", "language": "en-US", "channelId": "ig-1"}]
        out = intent.resolve_destinations(parse("A post"), requested, None, ())
        self.assertEqual(out, [{"platform": "Instagram", "language": "en-US", "channelId": "ig-1"}, {"platform": "Instagram", "language": "zh-Hant-HK", "channelId": "ig-1"}])

    def test_platform_named_in_message_keeps_every_selected_account(self):
        requested = [{"platform": "Instagram", "language": "en-US", "channelId": "ig-1"}, {"platform": "Instagram", "language": "en-US", "channelId": "ig-2"}, {"platform": "LinkedIn", "language": "en-US", "channelId": "li-1"}]
        out = intent.resolve_destinations(parse("Post this on Instagram at 4pm today"), requested, None, ())
        self.assertEqual([d.get("channelId") for d in out], ["ig-1", "ig-2"])  # message wins over LinkedIn, both IG accounts kept
        plan = intent.build_plan(parse("Post this on Instagram at 4pm today"), out)
        self.assertEqual([r["channelId"] for r in plan["destinations"]], ["ig-1", "ig-2"])

    def test_platform_only_requests_are_unchanged(self):
        out = intent.resolve_destinations(parse("A post"), [{"platform": "Threads", "language": "en-GB"}], None, ())
        self.assertEqual(out, [{"platform": "Threads", "language": "en-GB"}])
        self.assertNotIn("channelId", out[0])


class BindAccountsTest(unittest.TestCase):
    def state(self):
        return {"phase2": {"channels": [{"id": "ig-1", "platform": "Instagram", "account": "@studio"}, {"id": "ig-2", "platform": "Instagram", "account": "@festival", "revoked": True}]}}

    def test_attaches_account_label_and_rejects_unknown_or_revoked(self):
        bound = intent.bind_accounts([{"platform": "Instagram", "language": "en-US", "channelId": "ig-1"}, {"platform": "LinkedIn", "language": "en-US"}], self.state())
        self.assertEqual(bound[0]["account"], "@studio")
        self.assertNotIn("account", bound[1])
        for bad in ("ig-2", "missing"):
            with self.assertRaises(AlphaError) as ctx:
                intent.bind_accounts([{"platform": "Instagram", "language": "en-US", "channelId": bad}], self.state())
            self.assertEqual(ctx.exception.status, 409)
        with self.assertRaises(AlphaError):  # a connection id used under the wrong platform is refused too
            intent.bind_accounts([{"platform": "LinkedIn", "language": "en-US", "channelId": "ig-1"}], self.state())


class RuntimeIdentityTest(unittest.TestCase):
    def test_check_destinations_keys_on_account(self):
        agent_runtime.check_destinations([{"platform": "Instagram", "language": "en", "channelId": "a"}, {"platform": "Instagram", "language": "en", "channelId": "b"}, {"platform": "Instagram", "language": "en"}])
        with self.assertRaises(AlphaError):
            agent_runtime.check_destinations([{"platform": "Instagram", "language": "en", "channelId": "a"}, {"platform": "Instagram", "language": "en", "channelId": "a"}])
        self.assertEqual(agent_runtime.identity_fields({"platform": "X", "channelId": "a", "account": "@a", "token": "never"}), {"channelId": "a", "account": "@a"})

    def test_fixture_runtime_carries_identity_into_variants(self):
        runtime = agent_runtime.FixtureAgentRuntime() if hasattr(agent_runtime, "FixtureAgentRuntime") else None
        if runtime is None:
            self.skipTest("fixture runtime lives elsewhere")
        events = []
        context = {"sources": [], "excluded": [], "candidateOnly": False, "policyEpoch": 0}
        result = runtime.start_turn({"context": context, "idea": "Practice every day", "destinations": [{"platform": "Instagram", "language": "en-US", "channelId": "ig-1", "account": "@studio"}, {"platform": "Instagram", "language": "en-US", "channelId": "ig-2", "account": "@festival"}]}, events.append)
        self.assertEqual([v["channelId"] for v in result["artifact"]["variants"]], ["ig-1", "ig-2"])
        self.assertEqual([v["account"] for v in result["artifact"]["variants"]], ["@studio", "@festival"])

    def test_apply_slot_matching_separates_accounts(self):
        self.assertTrue(ideas.same_slot({"platform": "Instagram", "language": "en-US", "channelId": "a"}, {"platform": "Instagram", "language": "en-US", "channelId": "a"}))
        self.assertFalse(ideas.same_slot({"platform": "Instagram", "language": "en-US", "channelId": "a"}, {"platform": "Instagram", "language": "en-US", "channelId": "b"}))
        self.assertFalse(ideas.same_slot({"platform": "Instagram", "language": "en-US"}, {"platform": "Instagram", "language": "en-US", "channelId": "b"}))
        self.assertTrue(ideas.same_slot({"platform": "Instagram", "language": "en-US"}, {"platform": "Instagram", "language": "en-US"}))


if __name__ == "__main__":
    unittest.main()
