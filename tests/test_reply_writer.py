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
    def execute(self, sql, params=None):
        self.last = sql

    def fetchone(self):
        return ("Is it free to attend?", "ana", "threads", "post-1")


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


def service(runtime, ledger=None):
    class Skills:
        def bind(self, destinations, **kwargs):
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
            return STATE

    @contextmanager
    def transaction(token, workspace_id):
        yield Cursor(), ({},), "user-1"
    return type("Service", (), {"ideas": Ideas(), "repository": type("Repo", (), {"transaction": staticmethod(transaction)})()})()


def managed():
    return ServerModelRuntime("key", model="openai/gpt-6-sol", models=["openai/gpt-6-sol"])


PATCHES = (mock.patch("postriff_phase2.reply_writer.require"),
           mock.patch("postriff_phase2.source_policy.project_context", return_value={"sources": [{"facts": [{"text": "Entry is free."}]}]}),
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
