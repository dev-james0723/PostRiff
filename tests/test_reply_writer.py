"""Replies are written by Rafii's managed AI writer from the comment, the post, approved facts, the channel skill and the
consented memory; never fixed text. The call is reserved before it leaves and settled after."""
import json
import unittest
from contextlib import contextmanager
from unittest import mock

from postriff_alpha.domain import AlphaError
from postriff_phase2 import reply_writer
from postriff_phase2.learning_model import ModelResponse
from postriff_phase2.model_runtime import ServerModelRuntime

STATE = {"phase2": {"jobs": [{"providerReference": "post-1", "manifest": {"payload": {"text": "Spring recital on 12 April at the Town Hall."}}}]}, "sources": []}


class Cursor:
    comment = "Is it free to attend?"

    def execute(self, sql, params=None):
        self.last = sql

    def fetchone(self):
        return (self.comment, "ana", "threads", "post-1")


class Ledger:
    def __init__(self, refuse=None):
        self.reserved, self.settled, self.refuse = [], [], refuse

    def reserve(self, cur, workspace_id, principal, dimension, estimate, key, **kwargs):
        if self.refuse:
            raise self.refuse
        self.reserved.append((dimension, estimate, kwargs.get("model")))
        return {"reservationId": "r1"}

    def settle(self, cur, workspace_id, reservation_id, outcome, actual=None):
        self.settled.append((outcome, actual))


def service(runtime, ledger=None, state=None):
    class Skills:
        def bind(self, destinations, **kwargs):
            self.destinations = destinations
            return {"bindings": [{"id": "postriff-channel-threads", "version": "1", "sha256": "a" * 64}], "text": "THREADS ADAPTER: keep replies short."}

    class Ideas:
        skills = Skills()

        def __init__(self):
            self.ledger = ledger or Ledger()

        def default_runtime(self):
            return runtime

        def _member(self, row):
            return mock.Mock(allows=lambda permission: True)

        def _state(self, row):
            return state or STATE

    @contextmanager
    def transaction(token, workspace_id):
        yield Cursor(), ({},), "user-1"
    return type("Service", (), {"ideas": Ideas(), "repository": type("Repo", (), {"transaction": staticmethod(transaction)})()})()


def managed():
    return ServerModelRuntime("key", model="openai/gpt-6-sol", models=["openai/gpt-6-sol"])


PATCHES = (mock.patch("postriff_phase2.reply_writer.require"),
           mock.patch("postriff_phase2.source_policy.project_context", return_value={"sources": [
               {"id": "brief", "facts": [{"text": "Entry is free."}]},
               # A research find (or a rewritten source) whose public use the owner has not approved yet.
               {"id": "found", "candidateOnly": True, "facts": [{"text": "Tickets sell out every year."}]}]}),
           mock.patch("postriff_phase2.memory.projection", return_value={"files": [{"name": "VOICE.md", "body": "Warm, brief, no exclamation marks."}]}))


class ReplyWriterTest(unittest.TestCase):
    def setUp(self):
        for patch in PATCHES:
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_reply_is_the_models_text_from_comment_post_facts_skill_and_memory(self):
        seen = {}

        def call(system, user, schema):
            seen.update(system=system, user=json.loads(user))
            return ModelResponse({"reply": "Yes, entry is free. See you at the Town Hall on 12 April.", "needs": [], "language": "en"}, 1200)
        svc = service(managed())
        written = reply_writer.write(svc, "ws", "tok", "th1", call=call)
        self.assertEqual(written["text"], "Yes, entry is free. See you at the Town Hall on 12 April.")
        self.assertEqual(seen["user"]["post"], "Spring recital on 12 April at the Town Hall.")
        self.assertEqual(seen["user"]["approvedFacts"], ["Entry is free."])
        self.assertIn("THREADS ADAPTER", seen["system"])
        self.assertIn("Warm, brief", seen["system"])
        self.assertEqual(svc.ideas.ledger.reserved[0][0], "text_model")
        self.assertEqual(svc.ideas.ledger.settled, [("completed", 1200)])
        self.assertEqual(written["provenance"]["route"]["model"], "openai/gpt-6-sol")

    def test_no_managed_writer_means_no_reply_and_no_reservation(self):
        svc = service(runtime=mock.Mock(cost_class="none", provider_class="local"))
        with self.assertRaises(AlphaError) as caught:
            reply_writer.write(svc, "ws", "tok", "th1", call=lambda *a: self.fail("no call"))
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "reply_writer_unavailable"))
        self.assertEqual(svc.ideas.ledger.reserved, [])

    def test_a_refused_budget_stops_before_any_call(self):
        svc = service(managed(), Ledger(refuse=AlphaError("Paid AI drafting is not switched on yet.", 402)))
        with self.assertRaises(AlphaError) as caught:
            reply_writer.write(svc, "ws", "tok", "th1", call=lambda *a: self.fail("no call"))
        self.assertEqual(caught.exception.status, 402)

    def test_placeholders_or_a_failed_call_are_refused_and_still_settled(self):
        svc = service(managed())
        with self.assertRaises(AlphaError) as caught:
            reply_writer.write(svc, "ws", "tok", "th1", call=lambda *a: ModelResponse({"reply": "Thanks! [ANSWER: price]"}, 900))
        self.assertEqual(caught.exception.code, "reply_writer_unusable")
        self.assertEqual(svc.ideas.ledger.settled, [("completed", 900)])

        def broken(*a):
            raise AlphaError("The extraction model call failed.", 502)
        svc = service(managed())
        with self.assertRaises(AlphaError) as caught:
            reply_writer.write(svc, "ws", "tok", "th1", call=broken)
        self.assertEqual(caught.exception.code, "reply_writer_failed")
        self.assertEqual(svc.ideas.ledger.settled, [("unknown", None)])

    def test_a_long_answer_is_cut_at_a_sentence(self):
        text = "Yes, entry is free. " * 40
        self.assertLessEqual(len(reply_writer._fit(text)), reply_writer.REPLY_LIMIT)
        self.assertTrue(reply_writer._fit(text).endswith("."))


class ReviewFixesTest(unittest.TestCase):
    def setUp(self):
        for patch in PATCHES:
            patch.start()
            self.addCleanup(patch.stop)

    def reply(self, text):
        return lambda *a: ModelResponse({"reply": text, "needs": [], "language": "en"}, 700)

    def test_only_sources_cleared_for_public_use_supply_facts_and_they_are_recorded(self):
        seen = {}

        def call(system, user, schema):
            seen["user"] = json.loads(user)
            return ModelResponse({"reply": "Yes, entry is free.", "needs": []}, 800)
        written = reply_writer.write(service(managed()), "ws", "tok", "th1", call=call)
        self.assertEqual(seen["user"]["approvedFacts"], ["Entry is free."])
        self.assertEqual(written["provenance"]["factSourceIds"], ["brief"])

    def test_any_failure_of_the_call_is_settled_unknown_and_refused(self):
        import http.client

        def cut(*a):
            raise http.client.IncompleteRead(b"partial")
        svc = service(managed())
        with self.assertRaises(AlphaError) as caught:
            reply_writer.write(svc, "ws", "tok", "th1", call=cut)
        self.assertEqual((caught.exception.status, caught.exception.code), (502, "reply_writer_failed"))
        self.assertEqual(svc.ideas.ledger.settled, [("unknown", None)])

    def test_the_reply_method_is_sent_and_the_provenance_says_only_what_was_sent(self):
        seen = {}

        def call(system, user, schema):
            seen["system"] = system
            return ModelResponse({"reply": "Yes, entry is free.", "needs": []}, 800)
        written = reply_writer.write(service(managed()), "ws", "tok", "th1", call=call)
        self.assertIn("REPLY METHOD", seen["system"])
        self.assertIn("Engagement triage and reply drafts", seen["system"])
        self.assertNotIn("leave a clear placeholder", seen["system"])
        skills = {(s["id"], s["via"]) for s in written["provenance"]["skills"]}
        self.assertIn(("rafii-engagement-triage", "compiler"), skills)
        self.assertIn(("postriff-channel-threads", "writer"), skills)
        self.assertNotIn("postriff-channel-threads", [s["id"] for s in written["provenance"]["skills"] if s["via"] == "compiler"], "the channel skill is sent once")
        self.assertEqual(written["provenance"]["evaluators"], [], "no evaluator runs on a reply")
        self.assertTrue(written["provenance"]["route"]["methodApplied"])

    def test_workspace_preferences_reach_the_writer_only_with_memory_consent(self):
        def view(state, scope, cloud_allowed=True, now=None):
            return {"text": "WORKSPACE PREFERENCES:\n- PRIVATE-PREFERENCE" if cloud_allowed else "WORKSPACE PREFERENCES: withheld", "items": [], "revisions": {}}
        for egress, shared in ((None, False), ({"cloud": False}, False), ({"cloud": True}, True)):
            seen = {}

            def call(system, user, schema):
                seen["system"] = system
                return ModelResponse({"reply": "Yes, entry is free.", "needs": []}, 800)
            state = {**STATE, **({"memoryEgress": egress} if egress is not None else {})}
            with mock.patch("postriff_phase2.coworker.overlays.effective_view", side_effect=view):
                reply_writer.write(service(managed(), state=state), "ws", "tok", "th1", call=call)
            self.assertEqual("PRIVATE-PREFERENCE" in seen["system"], shared, egress)

    def test_the_reply_language_follows_the_comment_and_the_workspace(self):
        state = {**STATE, "languageSettings": {"default": "zh-Hant-HK", "channels": {}}}
        svc = service(managed(), state=state)
        with mock.patch.object(Cursor, "comment", "幾時開始？要唔要買飛？"):
            written = reply_writer.write(svc, "ws", "tok", "th1", call=self.reply("唔使買飛，入場免費。"))
        self.assertEqual(svc.ideas.skills.destinations[0]["language"], "zh-Hant-HK")
        self.assertEqual(written["provenance"]["language"], "zh-Hant-HK")
        self.assertIn("rafii-humanizer-zh", [s["id"] for s in written["provenance"]["skills"]])
        # An English comment in the same workspace is answered in English.
        svc = service(managed(), state=state)
        reply_writer.write(svc, "ws", "tok", "th1", call=self.reply("Yes, entry is free."))
        self.assertEqual(svc.ideas.skills.destinations[0]["language"].split("-")[0], "en")

    def test_placeholders_are_refused_and_ordinary_brackets_are_not(self):
        for text in ("DM us: [link]", "Book now at [insert link].", "Thanks, [Your name]", "It costs [PRICE].", "Doors open {{time}}.", "票價係【價錢】。",
                     "Thanks! [ANSWER: price]"):
            svc = service(managed())
            with self.assertRaises(AlphaError, msg=text) as caught:
                reply_writer.write(svc, "ws", "tok", "th1", call=self.reply(text))
            self.assertEqual(caught.exception.code, "reply_writer_unusable", text)
            self.assertEqual(svc.ideas.ledger.settled, [("completed", 700)], text)
        for text in ("Thanks! [Edit: typo fixed]", "As we said [sic], entry is free.", "See note [1] on the poster."):
            self.assertEqual(reply_writer.write(service(managed()), "ws", "tok", "th1", call=self.reply(text))["text"], text)

    def test_a_long_answer_with_line_breaks_is_cut_at_a_sentence(self):
        text = "Thanks so much for coming!\n" * 30
        fitted = reply_writer._fit(text)
        self.assertLessEqual(len(fitted), reply_writer.REPLY_LIMIT)
        self.assertTrue(fitted.endswith("!"), fitted[-20:])


class RepliesAreNeverFixedTextTest(unittest.TestCase):
    def test_the_engagement_copilot_has_no_template(self):
        from postriff_phase2.coworker import engagement
        self.assertFalse(hasattr(engagement, "_starter"))

    def test_inbox_suggestions_need_the_writer(self):
        from postriff_phase2.audience import AudienceService
        audience = AudienceService(None, None, lambda: 0)
        with self.assertRaises(AlphaError) as caught:
            audience.draft_reply("ws", "tok", "th1", {"origin": "ai_fixture"})
        self.assertEqual(caught.exception.code, "reply_writer_unavailable")


if __name__ == "__main__":
    unittest.main()
