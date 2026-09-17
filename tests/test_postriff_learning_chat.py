"""Phase B, pure parts: a chat instruction read as a proposal, the prompt slice chosen per destination,
the run binding, and the owner-only settings and reset actions."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha import learning  # noqa: E402
from postriff_alpha.domain import AlphaError, Store  # noqa: E402
from postriff_phase2 import memory  # noqa: E402
from postriff_phase2.learning_chat import instruction_to_proposal  # noqa: E402
from postriff_phase2.permissions import classify  # noqa: E402

NOW = "2026-09-16T10:00:00+00:00"


def workspace():
    return {"speaker": {"id": "spk", "label": "Kiln & Quiet", "activeRevision": 1, "revisions": [{"revision": 1, "approvedAt": "2026-09-01T00:00:00+00:00", "reason": "approved", "profile": {"tone": "plain", "observations": [], "writingExample": "", "unknowns": []}}]},
            "brandHub": {"subject": "Ceramics"}, "variants": [], "preferences": []}


def item(state, statement, scope=None, rule="other", source="chat", **extra):
    return learning.remember(state, {"type": "writing_preference", "ruleKey": rule, "polarity": "do", "scope": scope or {}, "statement": statement, "source": source, **extra}, now=NOW)


class Instructions(unittest.TestCase):
    def test_known_rules_get_templates_scope_and_polarity(self):
        cases = {
            "以後 LinkedIn 唔好用 emoji": ("emoji.use", "avoid", "LinkedIn", None, "No emoji."),
            "Remember: no hashtags on Instagram for Chinese posts.": ("hashtags.use", "avoid", "Instagram", "zh", "No hashtags."),
            "From now on, don't end my posts with a call to action.": ("closing.cta", "avoid", None, None, "Don't end with a call to action."),
            "Always put the point in the first sentence.": ("opening.style", "do", None, None, "Put the point in the first sentence."),
            "Never use bullet lists on Threads": ("lists.use", "avoid", "Threads", None, "No bullet lists."),
        }
        for text, (rule, polarity, platform, language, statement) in cases.items():
            with self.subTest(text=text):
                p = instruction_to_proposal(text)
                self.assertEqual((p["ruleKey"], p["polarity"], p["scope"]["platform"], p["scope"]["language"], p["statement"], p["source"]), (rule, polarity, platform, language, statement, "chat"))

    def test_length_and_unknown_rules_keep_the_persons_words(self):
        p = instruction_to_proposal("From now on keep LinkedIn posts to 120-180 words.")
        self.assertEqual((p["ruleKey"], p["statement"], p["scope"]["platform"]), ("length.target", "From now on keep LinkedIn posts to 120-180 words.", "LinkedIn"))
        self.assertEqual(learning.lint(p["statement"], p["ruleKey"]), p["statement"])
        other = instruction_to_proposal("以後用多啲比喻")
        self.assertEqual((other["ruleKey"], other["statement"], other["type"]), ("other", "以後用多啲比喻", "writing_preference"))
        working = instruction_to_proposal("Stop asking me questions before drafting.")
        self.assertEqual(working["type"], "working_style")
        short = instruction_to_proposal("以後開頭短啲")
        self.assertEqual((short["ruleKey"], short["params"], short["statement"]), ("opening.style", {"shortOpenings": True}, "Use shorter openings."))


class PromptSlice(unittest.TestCase):
    def test_only_matching_scopes_reach_a_turn_most_specific_first(self):
        state = workspace()
        everywhere = item(state, "Put the point in the first sentence.", {}, "opening.style")
        linkedin = item(state, "No emoji.", {"platform": "LinkedIn"}, "emoji.use")
        instagram = item(state, "No hashtags.", {"platform": "Instagram", "language": "繁體中文"}, "hashtags.use")
        chosen, omitted = learning.select(state, [{"platform": "LinkedIn", "language": "English"}])
        self.assertEqual([i["id"] for i in chosen], [linkedin["id"], everywhere["id"]])
        self.assertEqual(omitted, [])
        chosen, _ = learning.select(state, [{"platform": "Instagram", "language": "English"}])
        self.assertEqual([i["id"] for i in chosen], [everywhere["id"]], "the language does not match")
        chosen, _ = learning.select(state, [{"platform": "Instagram", "language": "繁體中文"}, {"platform": "LinkedIn", "language": "English"}])
        self.assertEqual({i["id"] for i in chosen}, {everywhere["id"], linkedin["id"], instagram["id"]})
        voice = next(f["body"] for f in memory.render_files(state, destinations=[{"platform": "LinkedIn", "language": "English"}]) if f["name"] == "VOICE.md")
        self.assertIn("No emoji.", voice)
        self.assertNotIn("No hashtags.", voice)
        full = next(f["body"] for f in memory.render_files(state) if f["name"] == "VOICE.md")
        self.assertIn("No hashtags.", full, "the Memory page still shows everything")

    def test_slice_is_bounded_and_paused_items_leave_it(self):
        state = workspace()
        # One active item per scope key, so spread the fifteen across rule keys and polarities.
        combos = [(rule, polarity) for rule in learning.RULE_KEYS for polarity in learning.POLARITIES][:15]
        ids = [item(state, f"Prefer the {chr(97 + n)}-style closing.", {}, rule, polarity=polarity)["id"] for n, (rule, polarity) in enumerate(combos)]
        chosen, omitted = learning.select(state, [{"platform": "LinkedIn", "language": "English"}])
        self.assertEqual((len(chosen), len(omitted)), (12, 3))
        self.assertTrue(learning.set_status(state, ids[0], "paused", NOW))
        self.assertEqual(learning.revision(state), 16)
        self.assertNotIn(ids[0], [i["id"] for i in learning.select(state, [{"platform": "LinkedIn", "language": "English"}])[0]])
        self.assertIn(ids[0], [i["id"] for i in learning.all_items(state)])
        self.assertTrue(learning.set_status(state, ids[0], "active", NOW))
        self.assertFalse(learning.set_status(state, ids[0], "active", NOW), "already active")
        with self.assertRaises(ValueError):
            learning.set_status(state, ids[0], "gone", NOW)

    def test_projection_records_the_binding_and_a_cloud_route_without_consent_gets_none(self):
        state = workspace()
        kept = item(state, "No emoji.", {"platform": "LinkedIn"}, "emoji.use")
        local = memory.projection(state, "local", [{"platform": "LinkedIn", "language": "English"}])
        self.assertEqual((local["learned"]["used"], local["learned"]["statements"], local["learned"]["styleRevision"]), ([kept["id"]], ["No emoji."], 1))
        cloud = memory.projection(state, "cloud", [{"platform": "LinkedIn", "language": "English"}])
        self.assertEqual((cloud["files"], cloud["learned"]["used"], cloud["learned"]["omitted"]), ([], [], [kept["id"]]))


class SettingsAndReset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "alpha.sqlite3")
        created = self.store.create()
        self.wid, self.token, self.revision = created["workspaceId"], created["token"], created["revision"]

    def tearDown(self):
        self.tmp.cleanup()

    def act(self, action, **payload):
        saved = self.store.mutate(self.wid, self.token, self.revision, action, payload)
        self.revision = saved["revision"]
        return saved["state"]

    def test_settings_and_reset_are_owner_actions_with_explicit_choices(self):
        self.assertEqual((classify("learning_settings"), classify("learning_reset")), ("owner", "owner"))
        with self.assertRaises(AlphaError):
            self.act("learning_settings", enabled="yes")
        with self.assertRaises(AlphaError):
            self.act("learning_settings")
        state = self.act("learning_settings", enabled=False, teamEdits=True)
        self.assertEqual((state["learning"]["enabled"], state["learning"]["teamEdits"], state["learning"]["cloudExtraction"]), (False, True, False))
        with self.assertRaises(AlphaError):
            self.act("learning_reset")
        with self.store.connect() as db:
            row = db.execute("SELECT state FROM workspaces WHERE id=?", (self.wid,)).fetchone()
        state = self.act("learning_settings", enabled=True)
        learning.remember(state, {"ruleKey": "emoji.use", "polarity": "avoid", "statement": "No emoji.", "source": "chat"}, now=NOW)
        self.assertEqual(learning.revision(state), 1)
        reset = self.act("learning_reset", confirmed=True)
        self.assertEqual((reset["learning"]["active"], reset["learning"]["retired"], reset["learning"]["revision"] > 0, bool(reset["learning"]["resetAt"])), ([], [], True, True))
        self.assertEqual(learning.summary(reset)["items"], [])


if __name__ == "__main__":
    unittest.main()
