"""Relationship follow-ups (PRD R-REL-01/02, G2-REL): pure rules, routing, flags, notification/attention wiring and agent
tools. Offline; the database paths are covered by tests/phase2/postgres_relationships*.py. Test names carry the PRD
acceptance ids they evidence (AC13–AC15, AC28–AC30).
"""
import json
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from postriff_alpha.domain import AlphaError
from postriff_phase2 import contracts as core_contracts
from postriff_phase2 import growth_events
from postriff_phase2.coworker import attention, flags
from postriff_phase2.notifications import catalog, detector, email_render, planner
from postriff_phase2.permissions import Membership
from postriff_phase2.relationships import agent_tools, http, jobs
from postriff_phase2.relationships import service as rel

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=ZoneInfo("UTC")).timestamp()
RID = "11111111-1111-4111-8111-111111111111"
TID = "22222222-2222-4222-8222-222222222222"


def on():
    flags.attach({rel.FLAG: "1"})


def row(**changes):
    base = {"id": RID, "state": "waiting", "stateChangedAt": NOW - 7200, "dueAt": NOW - 60, "dueTimeZone": "America/New_York", "dueFold": 0,
            "dueRevision": 2, "snoozedUntil": None, "followupDismissedKey": None, "suggestionDismissedKey": None}
    base.update(changes)
    return base


class DueTimeTest(unittest.TestCase):
    """Due times are UTC instants chosen in an IANA zone, resolved with the publishing scheduler's DST rule."""

    def test_dst_gap_is_refused_like_the_scheduler(self):
        with self.assertRaises(AlphaError) as caught:
            rel.resolve_due({"local": "2027-03-14T02:30", "timeZone": "America/New_York"}, NOW)
        self.assertEqual((caught.exception.status, caught.exception.code), (400, "due_time_nonexistent"))
        with self.assertRaises(AlphaError):   # the scheduler refuses the same wall time
            core_contracts.resolve_time("2027-03-14T02:30", "America/New_York", None, NOW)

    def test_repeated_local_time_needs_an_explicit_occurrence(self):
        with self.assertRaises(AlphaError) as caught:
            rel.resolve_due({"local": "2026-11-01T01:30", "timeZone": "America/New_York"}, NOW)
        self.assertEqual(caught.exception.code, "due_time_ambiguous")
        first = rel.resolve_due({"local": "2026-11-01T01:30", "timeZone": "America/New_York", "fold": 0}, NOW)
        second = rel.resolve_due({"local": "2026-11-01T01:30", "timeZone": "America/New_York", "fold": 1}, NOW)
        self.assertEqual(second["at"] - first["at"], 3600)
        self.assertEqual(datetime.fromtimestamp(first["at"], ZoneInfo("UTC")).strftime("%H:%M"), "05:30")   # EDT
        self.assertEqual(datetime.fromtimestamp(second["at"], ZoneInfo("UTC")).strftime("%H:%M"), "06:30")  # EST
        for fold, resolved in ((0, first), (1, second)):
            scheduled = core_contracts.resolve_time("2026-11-01T01:30", "America/New_York", fold, NOW)
            self.assertEqual(scheduled["timestamp"], resolved["at"])          # identical to the scheduler's instant
            view = rel.due_view(resolved["at"], "America/New_York", resolved["fold"], 1)
            self.assertEqual((view["local"], view["fold"]), ("2026-11-01T01:30", fold))

    def test_ordinary_times_ignore_fold_and_round_trip_in_their_zone(self):
        due = rel.resolve_due({"local": "2026-10-20T09:00", "timeZone": "Asia/Hong_Kong", "fold": 1}, NOW)
        self.assertEqual(due["fold"], 0)
        view = rel.due_view(due["at"], "Asia/Hong_Kong", 0, 3)
        self.assertEqual((view["local"], view["offset"], view["revision"]), ("2026-10-20T09:00", "+0800", 3))
        self.assertEqual(view["utc"], "2026-10-20T01:00:00+00:00")

    def test_instant_input_bounds_and_zone_validation(self):
        due = rel.resolve_due({"at": "2026-10-02T13:00:00Z", "timeZone": "Europe/London"}, NOW)
        self.assertEqual(rel.due_view(due["at"], "Europe/London", due["fold"], 1)["local"], "2026-10-02T14:00")
        self.assertIsNone(rel.resolve_due(None, NOW))
        for raw in ({"local": "2030-01-01T09:00", "timeZone": "UTC"}, {"local": "2026-10-02T09:00", "timeZone": "Mars/Base"},
                    {"local": "2026-10-02 09:00", "timeZone": "UTC"}, {"at": "2026-10-02T13:00:00", "timeZone": "UTC"}, "tomorrow", {"timeZone": "UTC"}):
            with self.assertRaises(AlphaError, msg=repr(raw)) as caught:
                rel.resolve_due(raw, NOW)
            self.assertEqual(caught.exception.status, 400)
        overdue = rel.resolve_due({"local": "2026-09-01T09:00", "timeZone": "UTC"}, NOW)   # logging an overdue follow-up is allowed
        self.assertLess(overdue["at"], NOW)


class ValidationTest(unittest.TestCase):
    def test_text_limits_count_characters(self):
        self.assertEqual(rel.text("  Mei   Chan ", 120, "a name"), "Mei Chan")
        self.assertEqual(rel.text("陳" * 120, 120, "a name"), "陳" * 120)
        with self.assertRaises(AlphaError):
            rel.text("x" * 121, 120, "a name")
        with self.assertRaises(AlphaError):
            rel.text("", 120, "a name", required=True)
        self.assertIsNone(rel.text("   ", 300, "the stated interest"))
        self.assertEqual(rel.text("line one\r\n  line   two ", 500, "the note", multiline=True), "line one\nline two")
        with self.assertRaises(AlphaError):
            rel.text("bad\x00", 500, "the note")

    def test_contact_reference_is_scoped_to_one_provider(self):
        self.assertEqual(rel.contact({"provider": "threads", "accountId": "conn-1", "ref": "mei"}), {"provider": "threads", "accountId": "conn-1", "ref": "mei"})
        self.assertIsNone(rel.contact({}))
        for raw in ({"ref": "mei"}, {"provider": "Threads!", "ref": "mei"}, "mei@example.com"):
            with self.assertRaises(AlphaError):
                rel.contact(raw)

    def test_ids_keys_and_revisions(self):
        self.assertEqual(rel.ident(RID.upper()), RID)
        with self.assertRaises(AlphaError) as caught:
            rel.ident("../../etc")
        self.assertEqual((caught.exception.status, caught.exception.code), (404, "relationship_not_found"))
        self.assertEqual(rel.idempotency_key("rel-create-abc123", required=True), "rel-create-abc123")
        for key in ("short", "x" * 81, "has space here", None):
            with self.assertRaises(AlphaError):
                rel.idempotency_key(key, required=True)
        self.assertIsNone(rel.idempotency_key(None, required=False))
        for payload in ({}, {"expectedRevision": "2"}, {"expectedRevision": 0}, {"expectedRevision": True}):
            with self.assertRaises(AlphaError) as caught:
                rel.expected_revision(payload)
            self.assertEqual(caught.exception.code, "revision_required")

    def test_ac29_pagination_bounds_and_cursor_tampering(self):
        self.assertEqual(rel.page_limit(None), 25)
        self.assertEqual(rel.page_limit("50"), 50)
        for bad in ("0", "51", "ten", -1):
            with self.assertRaises(AlphaError):
                rel.page_limit(bad)
        cursor = rel.encode_cursor({"dueSort": "1790000000.000000", "createdSort": "1789990000.123456", "id": RID})
        self.assertEqual(rel.decode_cursor(cursor), ("1790000000.000000", "1789990000.123456", RID))
        self.assertEqual(rel.decode_cursor(rel.encode_cursor({"dueSort": None, "createdSort": "1", "id": RID}))[0], None)
        for bad in ("@@@", cursor[:-3] + "AAA", rel.encode_cursor({"dueSort": "1; DROP", "createdSort": "1", "id": RID}), "x" * 400):
            with self.assertRaises(AlphaError) as caught:
                rel.decode_cursor(bad)
            self.assertEqual(caught.exception.code, "cursor_invalid")

    def test_history_and_audit_meta_cannot_carry_text(self):
        meta = rel.clean_meta({"fields": ["display_name", "next_action"], "threadId": TID, "until": 1790000000, "hasDue": True,
                               "note": "call Mei about pricing", "displayName": "Mei Chan", "reason": "Mei asked twice", "suggested": "replied"})
        self.assertEqual(meta, {"fields": ["display_name", "next_action"], "threadId": TID, "until": 1790000000, "hasDue": True, "suggested": "replied"})


class ReminderTest(unittest.TestCase):
    def test_cosmetic_edits_keep_the_reminder_identity_and_due_changes_move_it(self):
        base = row()
        token = rel.reminder_token(base)
        self.assertEqual(token, f"2:{int(NOW - 60)}")
        self.assertEqual(rel.reminder_token({**base, "displayName": "Renamed", "nextAction": "Other", "notes": [1]}), token)
        self.assertNotEqual(rel.reminder_token({**base, "dueRevision": 3}), token)
        self.assertNotEqual(rel.reminder_token({**base, "snoozedUntil": NOW + 3600}), token)   # the end of a snooze is a new reminder
        self.assertEqual(rel.reminder_token({**base, "snoozedUntil": NOW - 3600}), token)      # a snooze that ended before the due time changes nothing
        self.assertEqual(rel.dedupe_key(RID, token), f"relationship.follow_up_due:{RID}:{token}")

    def test_followup_status(self):
        self.assertEqual(rel.followup(row(dueAt=None), NOW)["status"], "none")
        self.assertEqual(rel.followup(row(dueAt=NOW + 60), NOW)["status"], "scheduled")
        self.assertEqual(rel.followup(row(snoozedUntil=NOW + 60), NOW)["status"], "snoozed")
        self.assertEqual(rel.followup(row(state="closed"), NOW)["status"], "inactive")
        self.assertEqual(rel.followup(row(state="won"), NOW)["status"], "inactive")
        due = rel.followup(row(), NOW)
        self.assertEqual((due["status"], due["dueNow"]), ("due", True))
        dismissed = row(followupDismissedKey=rel.reminder_token(row()))
        self.assertEqual(rel.followup(dismissed, NOW)["status"], "dismissed")
        # A dismissal suppresses only until the due revision (or the reminder instant) changes.
        self.assertTrue(rel.followup({**dismissed, "dueRevision": 3}, NOW)["dueNow"])
        self.assertTrue(rel.followup({**dismissed, "snoozedUntil": NOW - 30}, NOW)["dueNow"])


class SuggestionTest(unittest.TestCase):
    def thread(self, **changes):
        base = {"threadId": TID, "at": NOW - 86400, "tombstoned": False, "lastSentAt": None}
        base.update(changes)
        return base

    def test_suggestions_carry_evidence_and_are_never_applied_or_a_purchase(self):
        sent = rel.suggest(row(state="new", dueAt=None), [self.thread(lastSentAt=NOW - 600)], NOW)
        self.assertEqual((sent["state"], sent["reason"], sent["evidence"]), ("replied", "reply_sent", {"threadId": TID, "at": NOW - 600}))
        newer = rel.suggest(row(state="replied", dueAt=None), [self.thread(at=NOW - 60)], NOW)
        self.assertEqual((newer["state"], newer["reason"]), ("follow_up_due", "new_message"))
        due = rel.suggest(row(state="waiting"), [self.thread()], NOW)
        self.assertEqual((due["state"], due["reason"], due["evidence"]), ("follow_up_due", "due_passed", {"dueAt": NOW - 60}))
        self.assertIsNone(rel.suggest(row(state="waiting", snoozedUntil=NOW + 60), [self.thread()], NOW))
        self.assertIsNone(rel.suggest(row(state="won"), [self.thread(lastSentAt=NOW)], NOW))
        self.assertIsNone(rel.suggest(row(state="closed"), [self.thread(at=NOW)], NOW))
        for state in rel.OPEN_STATES:
            for threads in ([], [self.thread(lastSentAt=NOW - 5)], [self.thread(at=NOW - 5)]):
                suggestion = rel.suggest(row(state=state), threads, NOW)
                self.assertNotIn((suggestion or {}).get("state"), ("won", "closed"))
        self.assertIsNone(rel.suggest(row(state="new", dueAt=None), [self.thread(lastSentAt=NOW - 7300)], NOW))   # older than the state

    def test_a_dismissed_suggestion_stays_quiet_until_its_evidence_changes(self):
        suggestion = rel.suggest(row(state="waiting"), [], NOW)
        self.assertIsNone(rel.suggest(row(state="waiting", suggestionDismissedKey=suggestion["key"]), [], NOW))
        moved = rel.suggest(row(state="waiting", suggestionDismissedKey=suggestion["key"], dueAt=NOW - 30), [], NOW)
        self.assertIsNotNone(moved)


class ReplyRouteTest(unittest.TestCase):
    def test_ac15_only_a_direct_threads_reply_is_direct_everything_else_is_assisted(self):
        direct = rel.reply_route("threads", "Direct", False, "https://www.threads.net/@mei/post/1")
        self.assertEqual(direct, {"kind": "direct", "provider": "threads", "approval": "exact"})
        not_direct = rel.reply_route("threads", "Assisted", False, "https://www.threads.net/@mei/post/1")
        self.assertEqual((not_direct["kind"], not_direct["reason"], not_direct["href"]), ("assisted", "not_direct", "https://www.threads.net/@mei/post/1"))
        for provider in ("instagram", "facebook", "linkedin", "x"):
            route = rel.reply_route(provider, "Direct", False, "https://example.com/c/1")   # a Direct level alone is not a reply adapter
            self.assertEqual((route["kind"], route["reason"]), ("assisted", "unsupported_provider"), provider)
        removed = rel.reply_route("threads", "Direct", True, None)
        self.assertEqual((removed["kind"], removed["reason"], removed["href"]), ("assisted", "source_removed", None))
        for unsafe in ("javascript:alert(1)", "http://www.threads.net/x", "https://evil.example/x", "https://user:pw@threads.net/x"):
            self.assertIsNone(rel.reply_route("threads", "Assisted", False, unsafe)["href"], unsafe)
        self.assertIsNone(rel.reply_route("instagram", "Assisted", False, "http://instagram.com/p/1")["href"])


class FlagTest(unittest.TestCase):
    def setUp(self):
        flags.attach({})

    def tearDown(self):
        flags.attach(None)

    def test_feature_off_answers_feature_disabled_everywhere(self):
        self.assertFalse(rel.enabled())
        with self.assertRaises(AlphaError) as caught:
            http.handle(None, {}, None, SimpleNamespace(), "token", "GET", ["api", "workspaces", RID, "relationships"])
        self.assertEqual((caught.exception.status, caught.exception.code), (404, "feature_disabled"))
        self.assertEqual(jobs.tick(SimpleNamespace(), time.monotonic() + 5), {"status": "disabled"})

        class Untouchable:
            def execute(self, *_args):
                raise AssertionError("no SQL while the feature is off")
        self.assertEqual(rel.detector_events(Untouchable(), RID, NOW), [])

    def test_unrelated_flag_values_never_switch_it_on(self):
        for value in ("0", "false", "", "off", "maybe"):
            flags.attach({rel.FLAG: value})
            self.assertFalse(rel.enabled(), value)
        flags.attach({rel.FLAG: "true"})
        self.assertTrue(rel.enabled())


class FakeApp:
    def __init__(self, body=None):
        self.body = body or {}
        self.sent = None

    def _body(self, _environ):
        return self.body

    def _json(self, _start, status, value):
        self.sent = (status, value)
        return [b""]


class HttpRoutingTest(unittest.TestCase):
    def setUp(self):
        on()

    def tearDown(self):
        flags.attach(None)

    def route(self, method, rest, body=None, query=""):
        calls = []

        class Service:
            def __getattr__(self, name):
                def call(*args):
                    calls.append((name, args))
                    return {"relationship": {"id": RID}, "replayed": name == "create" and bool(body and body.get("replay"))}
                return call
        hosted = SimpleNamespace(relationships=Service())
        app = FakeApp(body)
        http.handle(app, {"QUERY_STRING": query}, None, hosted, "token", method, ["api", "workspaces", RID, "relationships", *rest])
        return calls, app.sent

    def test_routes_map_to_one_service_operation_each(self):
        cases = [("GET", [], "list"), ("POST", [], "create"), ("GET", [RID], "detail"), ("PATCH", [RID], "update"),
                 ("POST", [RID, "transition"], "transition"), ("POST", [RID, "reopen"], "reopen"), ("POST", [RID, "snooze"], "snooze"),
                 ("POST", [RID, "unsnooze"], "unsnooze"), ("POST", [RID, "assign"], "assign"), ("POST", [RID, "threads"], "link_thread"),
                 ("DELETE", [RID, "threads", TID], "unlink_thread"), ("POST", [RID, "notes"], "add_note"), ("DELETE", [RID, "notes", TID], "remove_note"),
                 ("POST", [RID, "dismiss-followup"], "dismiss_followup"), ("POST", [RID, "restore-followup"], "restore_followup"),
                 ("POST", [RID, "dismiss-suggestion"], "dismiss_suggestion")]
        for method, rest, name in cases:
            calls, _sent = self.route(method, rest, {"expectedRevision": 1})
            self.assertEqual(calls[0][0], name, (method, rest))
        self.assertEqual(self.route("POST", [], {"idempotencyKey": "k" * 10})[1][0], 201)
        self.assertEqual(self.route("POST", [], {"replay": True})[1][0], 200)
        calls, _ = self.route("GET", [], query="state=open&due=due_now&owner=me&cursor=abc&limit=10&secret=x")
        self.assertEqual(calls[0][1][2], {"state": "open", "due": "due_now", "owner": "me", "cursor": "abc", "limit": "10"})
        for method, rest in (("PUT", []), ("POST", [RID, "send"]), ("GET", [RID, "threads"]), ("POST", [RID, "notes", "x", "y"])):
            with self.assertRaises(AlphaError) as caught:
                self.route(method, rest)
            self.assertEqual(caught.exception.status, 404)


class NotificationWiringTest(unittest.TestCase):
    def tearDown(self):
        flags.attach(None)

    def test_catalog_event_is_a_quiet_engagement_action_for_people_who_can_reply(self):
        spec = catalog.spec("relationship.follow_up_due")
        self.assertEqual((spec["category"], spec["severity"], spec["audience"], spec["email"], spec["push"], spec["sms"]),
                         ("engagement", "action", "reply", "digest", "off", "off"))
        self.assertIn(spec["template"], email_render.TEMPLATES)
        self.assertFalse(catalog.transactional("relationship.follow_up_due"))
        self.assertNotEqual(catalog.CATALOG_VERSION, "2026-09-26.2")
        self.assertIn("relationship.follow_up_due", catalog.public()["events"])

    def test_planner_keeps_quiet_hours_preferences_and_never_pushes(self):
        zone = "America/New_York"
        night = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo(zone)).timestamp()
        prefs = {("*", "*"): {"quiet_start": 22 * 60, "quiet_end": 7 * 60, "time_zone": zone}}
        plan = {r["channel"]: r for r in planner.plan({"event_type": "relationship.follow_up_due", "workspace_id": "ws"}, {"userId": "u"}, prefs, night, push_available=True)}
        self.assertEqual(plan["email"]["mode"], "digest")
        self.assertNotIn("push", plan)
        muted = {r["channel"]: r for r in planner.plan({"event_type": "relationship.follow_up_due", "workspace_id": "ws"}, {"userId": "u"},
                                                        {("*", "engagement"): {"email_mode": "off"}}, night)}
        self.assertEqual((muted["email"]["status"], muted["in_app"]["status"]), ("suppressed", "delivered"))
        members = [{"userId": "viewer", "membership": Membership("viewer"), "active": True},
                   {"userId": "editor", "membership": Membership("editor"), "active": True},
                   {"userId": "replier", "membership": Membership("editor", {"can_reply": True}), "active": True},
                   {"userId": "owner", "membership": Membership("owner"), "active": True}]
        self.assertEqual({m["userId"] for m in planner.audience(members, {"event_type": "relationship.follow_up_due"})}, {"replier", "owner"})

    def test_detector_emits_content_free_due_events_with_the_reminder_identity(self):
        on()
        cursor = RecordingCursor({"FROM public.pr_relationships r": [(RID, NOW - 60, "Asia/Hong_Kong", 2, f"2:{int(NOW - 60)}", TID)]})
        events = rel.detector_events(cursor, RID, NOW)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event_type"], "relationship.follow_up_due")
        self.assertEqual(event["dedupe_key"], f"relationship.follow_up_due:{RID}:2:{int(NOW - 60)}")
        self.assertEqual(event["payload"], {"title": "A follow-up is due", "reason": "Follow-up due",
                                            "href": f"/app/inbox?filter=follow_ups&relationship=u{RID.replace('-', '')}&thread=u{TID.replace('-', '')}"})
        self.assertIn("SAVEPOINT relationship_followups", cursor.sql[0])
        self.assertTrue(any(s.startswith("RELEASE SAVEPOINT") for s in cursor.sql))

    def test_stored_follow_up_links_survive_the_phone_number_redaction(self):
        from postriff_phase2.notifications.store import _clean_payload
        digits, thread = "11111111-1111-4111-8111-111111111111", "3f2a0000-1234-4567-8901-abcdefabcdef"   # groups that are digit runs
        hyphenated = f"/app/inbox?filter=follow_ups&relationship={digits}&thread={thread}"
        self.assertNotEqual(_clean_payload({"href": hyphenated})["href"], hyphenated)   # why stored links use compact ids
        event = rel.followup_event({"id": digits, "threadId": thread, "dedupeKey": "k"})
        self.assertEqual(event["payload"]["href"],
                         "/app/inbox?filter=follow_ups&relationship=u11111111111141118111111111111111&thread=u3f2a0000123445678901abcdefabcdef")
        self.assertEqual(_clean_payload(event["payload"]), event["payload"])
        self.assertEqual(rel.ident(rel.link_id(digits)), digits)   # the API accepts the compact form back

    def test_detector_survives_a_database_without_the_relationship_tables(self):
        on()
        cursor = RecordingCursor({}, fail_on="FROM public.pr_relationships r")
        self.assertEqual(rel.detector_events(cursor, RID, NOW), [])
        self.assertIn("ROLLBACK TO SAVEPOINT relationship_followups", cursor.sql)
        everything = detector.from_database(RecordingCursor({}, fail_on="FROM public.pr_relationships r"), RID, NOW)
        self.assertEqual([e for e in everything if e["event_type"] == "relationship.follow_up_due"], [])

    def test_from_database_includes_follow_ups_when_on(self):
        on()
        cursor = RecordingCursor({"FROM public.pr_relationships r": [(RID, NOW - 60, "UTC", 1, f"1:{int(NOW - 60)}", None)]})
        kinds = [e["event_type"] for e in detector.from_database(cursor, RID, NOW)]
        self.assertIn("relationship.follow_up_due", kinds)


class RecordingCursor:
    """Answers every detector query with nothing, except the scripted relationship rows."""

    def __init__(self, scripted, fail_on=None):
        self.scripted, self.fail_on, self.sql, self.rows = scripted, fail_on, [], []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("relation does not exist")
        self.rows = next((rows for marker, rows in self.scripted.items() if marker in sql), [])

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class AttentionTest(unittest.TestCase):
    def tearDown(self):
        flags.attach(None)

    def build(self, member, items=None):
        on()
        cursor = RecordingCursor({})
        due = [{"id": RID, "dueAt": NOW - 60, "timeZone": "UTC", "threadId": TID, "dueRevision": 1, "dedupeKey": rel.dedupe_key(RID, f"1:{int(NOW - 60)}")}]
        engagement = {"event_type": "engagement.needs_attention", "dedupe_key": "engagement:t", "entity_type": "audience_thread", "entity_id": "t",
                      "payload": {"platform": "threads", "reason": "question", "href": "/app/inbox"}}
        learning = {"event_type": "learning.preference_proposed", "dedupe_key": "pref:1", "entity_type": "memory_proposal", "entity_id": "p", "payload": {}}

        def enrich(cur, workspace_id, items_, now):
            for item in items_:
                if item["type"] == "relationship.follow_up_due":
                    item["context"] = {"relationshipId": RID, "exchange": [{"direction": "inbound", "excerpt": "How much is a lesson?"}]}
            return items_
        with mock.patch.object(rel, "due_followups", return_value=due), \
                mock.patch.object(detector, "from_state", return_value=[engagement, learning]), \
                mock.patch.object(rel, "attention_context", side_effect=enrich):
            return attention.build(cursor, RID, "u", member, {}, NOW)

    def test_follow_up_sits_between_engagement_and_learning_and_is_never_urgent(self):
        result = self.build(Membership("owner"))
        types = [item["type"] for item in result["items"]]
        self.assertEqual(types, ["engagement.needs_attention", "relationship.follow_up_due", "learning.preference_proposed"])
        item = result["items"][1]
        self.assertFalse(item["urgent"])
        self.assertEqual(item["priority"], 65)
        self.assertIn("never contact anyone", item["why"])
        self.assertTrue(item["href"].startswith("/app/inbox?filter=follow_ups&relationship="))
        self.assertEqual(item["context"]["exchange"][0]["direction"], "inbound")
        self.assertEqual(result["counts"]["urgent"], 0)

    def test_only_people_who_may_reply_see_it(self):
        self.assertNotIn("relationship.follow_up_due", [i["type"] for i in self.build(Membership("editor"))["items"]])
        self.assertNotIn("relationship.follow_up_due", [i["type"] for i in self.build(Membership("viewer", {"can_reply": True}))["items"]])
        self.assertIn("relationship.follow_up_due", [i["type"] for i in self.build(Membership("editor", {"can_reply": True}))["items"]])

    def test_enrichment_never_breaks_attention(self):
        class Broken:
            def execute(self, sql, params=None):
                if "pr_relationships" in sql:
                    raise RuntimeError("boom")

            def fetchall(self):
                return []
        items = [{"type": "relationship.follow_up_due", "evidence": {"entityId": RID}, "title": "t"}]
        self.assertEqual(rel.attention_context(Broken(), RID, items, NOW), items)
        self.assertNotIn("context", items[0])


class AgentToolsTest(unittest.TestCase):
    def setUp(self):
        from postriff_phase2.agent_runtime_v2 import contracts, tool_adapter
        self.contracts, self.adapter = contracts, tool_adapter
        agent_tools.register()
        agent_tools.register()   # idempotent

    def tearDown(self):
        flags.attach(None)

    def ctx(self, role="owner", **extra):
        from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
        return RafiiRunContext(service=SimpleNamespace(), workspace_id=RID, token="t", principal="u", membership=Membership(role, extra),
                               conversation_id="c", trace_id="trace_" + "0" * 32, run_id="run-1")

    def test_ac28_tool_contracts_are_typed_reversible_and_voice_equal(self):
        expected = {"relationship_list": (self.contracts.READ, "read"), "relationship_upsert": (self.contracts.MUTATE_REVERSIBLE, "edit"),
                    "followup_transition": (self.contracts.MUTATE_REVERSIBLE, "edit")}
        for name, (effect, permission) in expected.items():
            spec = self.adapter.REGISTRY[name].spec
            self.assertEqual((spec.effect, spec.permission, spec.voice, spec.approval), (effect, permission, True, False), name)
            for word in ("publish", "approve", "reply", "delete", "send"):
                self.assertNotIn(word, name)

    def test_ac28_flag_off_and_permissions_are_enforced_by_the_gate(self):
        flags.attach({})
        out = self.adapter.execute(self.ctx(), self.adapter.REGISTRY["relationship_list"], {})
        self.assertEqual(out["code"], "feature_disabled")
        on()
        viewer = self.adapter.execute(self.ctx("viewer"), self.adapter.REGISTRY["followup_transition"],
                                      {"relationshipId": RID, "expectedRevision": 1, "action": "reopen"})
        self.assertEqual(viewer["code"], "tool_forbidden")
        bad = self.adapter.execute(self.ctx(), self.adapter.REGISTRY["followup_transition"], {"relationshipId": RID, "expectedRevision": 1, "action": "send"})
        self.assertEqual(bad["code"], "tool_input")

    def test_tools_call_the_same_service_with_revision_and_idempotency(self):
        on()
        calls = []

        class Service:
            def create(self, w, t, payload):
                calls.append(("create", payload))
                return {"relationship": {"id": RID, "displayName": "Mei", "state": "new", "revision": 1}, "replayed": False}

            def transition(self, w, t, rid, payload):
                calls.append(("transition", payload))
                if payload["to"] == "won" and not payload.get("wonResultId"):
                    raise AlphaError("needs a declared result", 400, code="result_required")
                return {"relationship": {"id": rid, "displayName": "Mei", "state": payload["to"], "revision": 2}, "changed": True}
        with mock.patch.object(agent_tools, "_service", return_value=Service()):
            created = self.adapter.execute(self.ctx(), self.adapter.REGISTRY["relationship_upsert"], {"displayName": "Mei", "threadId": TID})
            again = self.adapter.execute(self.ctx(), self.adapter.REGISTRY["relationship_upsert"], {"displayName": "Mei", "threadId": TID})
            won = self.adapter.execute(self.ctx(), self.adapter.REGISTRY["followup_transition"],
                                       {"relationshipId": RID, "expectedRevision": 1, "action": "set_state", "state": "won"})
            moved = self.adapter.execute(self.ctx(), self.adapter.REGISTRY["followup_transition"],
                                         {"relationshipId": RID, "expectedRevision": 1, "action": "set_state", "state": "waiting"})
        self.assertTrue(created["ok"])
        self.assertEqual(calls[0][1]["idempotencyKey"], calls[1][1]["idempotencyKey"])   # a retried call in one run is one create
        self.assertEqual(calls[0][1]["threadId"], TID)
        self.assertEqual((won["ok"], won["code"]), (False, "result_required"))
        self.assertTrue(moved["ok"] and moved["changed"])
        self.assertEqual(calls[-1][1], {"expectedRevision": 1, "to": "waiting"})


class GrowthEventTest(unittest.TestCase):
    def test_outcome_event_is_registered_and_strips_text(self):
        props = growth_events.properties("relationship.followup_outcome", {"state": "follow_up_due", "previous": "waiting", "name": "Mei Chan", "note": "x"})
        self.assertEqual(props, {"state": "follow_up_due", "previous": "waiting"})


if __name__ == "__main__":
    unittest.main()
