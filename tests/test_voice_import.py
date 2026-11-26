"""Voice import service and HTTP surface (spec 5.1, 5.2; IMP-1 … IMP-7). No database and no network: the batch rules
are pure, the flow tests use a scripted cursor and fake transports. Every account and post text here is synthetic.
The statements themselves run on PostgreSQL in tests/phase2/postgres_voice_import.py."""
import io
import json
import sys
import unittest
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import voice_evidence as E
from postriff_phase2 import voice_import as V
from postriff_phase2 import voice_import_http as H
from postriff_phase2 import voice_import_readers as R

WS = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
CONSENT = {"ownership": "mine", "voiceScope": "brand", "confirmed": True}
A = "We moved the launch to Friday so the beta group gets one more week to test."
B = "Our autumn timetable is out and the Saturday classes are already half full."
C = "A short note on why we stopped sending the weekly newsletter on Mondays."
FLAGS = {V.FLAG: "1", V.PROVIDERS_FLAG: "threads,instagram,bluesky,mastodon"}


def run_context(**changes):
    base = {"id": "run-1", "workspaceId": WS, "provider": "threads", "accountKey": "t1", "route": "official_api", "connectionId": "conn-t1",
            "consent": {"version": "voice-import.v1", "ownership": "mine", "voiceScope": "brand", "retainText": True}}
    return {**base, **changes}


def item(external_id, text=A, **fields):
    return {"externalId": external_id, "text": text, "kind": "original", **fields}


class Store:
    """The posts table in memory: applies a plan the way the importer's statements do."""
    def __init__(self):
        self.rows = {}

    def batch(self, items, run=None, journal=frozenset(), now=NOW, skipped=None):
        run = run or run_context()
        prepared = V.prepare(items, run=run, journal=set(journal))
        ids = {post["externalId"] for post in prepared["posts"]}
        by_key = {row["provider_post_id"]: dict(row) for row in self.rows.values()
                  if (row["provider"], row["account_key"]) == (run["provider"], run["accountKey"]) and row["provider_post_id"] in ids}
        hashes = V.sibling_hashes(prepared["posts"], by_key)
        siblings = [dict(row) for row in self.rows.values() if row["norm_hash"] in hashes]
        plan = V.plan_batch(prepared["posts"], by_key, siblings, run=run, now=now)
        for row in plan["inserts"] + plan["seen"] + plan["regrouped"]:
            self.rows[row["id"]] = row
        counts = V.batch_counts(len(items), prepared, plan, skipped or {})
        return plan, counts

    def post(self, provider_post_id, provider="threads"):
        return next(row for row in self.rows.values() if (row["provider"], row["provider_post_id"]) == (provider, provider_post_id))


class FlagTests(unittest.TestCase):
    def test_off_unless_exactly_one(self):
        for values in ({}, None, {V.FLAG: "0"}, {V.FLAG: "true"}, {V.FLAG: ""}):
            self.assertFalse(V.enabled(values))
        self.assertTrue(V.enabled({V.FLAG: "1"}))
        self.assertEqual((V.FLAG, V.PROVIDERS_FLAG), ("POSTRIFF_VOICE_IMPORT", "POSTRIFF_VOICE_IMPORT_PROVIDERS"))

    def test_official_reads_are_named_one_by_one(self):
        self.assertEqual(V.allowed_providers({}), frozenset())               # exports only until a provider is named
        self.assertEqual(V.allowed_providers({V.PROVIDERS_FLAG: " Threads, bluesky x  tiktok,,"}), frozenset({"threads", "bluesky"}))
        self.assertEqual(V.allowed_providers({V.PROVIDERS_FLAG: "*"}), frozenset())
        self.assertEqual(V.allowed_providers(None), frozenset())

    def test_workspace_admission_is_optional_and_exact(self):
        self.assertIsNone(V.allowed_workspaces({}))                           # no list: every workspace
        self.assertEqual(V.allowed_workspaces({V.WORKSPACES_FLAG: WS.upper()}), frozenset({WS}))
        self.assertEqual(V.allowed_workspaces({V.WORKSPACES_FLAG: "not-a-uuid"}), frozenset())   # malformed admits nobody

    def test_fixed_values(self):
        self.assertEqual((V.CONSENT_VERSION, V.REQUESTS_PER_HOUR, V.LEASE_SECONDS, V.PAGES_PER_TICK, V.RUNS_PER_TICK, V.MAX_ATTEMPTS,
                          V.MAX_ITEMS, V.MAX_BATCH_BYTES), ("voice-import.v1", 5, 120, 3, 2, 5, 200, 512 * 1024))

    def test_mount_does_nothing_while_the_flag_is_off(self):
        service = SimpleNamespace(oauth=SimpleNamespace())
        self.assertIsNone(V.mount(service, lambda: None, {}, transport=Mock()))
        self.assertFalse(hasattr(service, "voice_import") or hasattr(service.oauth, "voice_import"))
        importer = V.mount(service, lambda: None, FLAGS, transport=Mock())
        self.assertIs(service.voice_import, importer)
        self.assertIs(service.oauth.voice_import, importer)                   # disconnect removes what was read through a connection
        self.assertEqual(importer.providers, frozenset({"threads", "instagram", "bluesky", "mastodon"}))


class RequestShapeTests(unittest.TestCase):
    def test_consent_must_be_confirmed(self):
        for consent in (None, {}, {**CONSENT, "confirmed": False}, {**CONSENT, "confirmed": "true"}, {**CONSENT, "confirmed": 1},
                        {"ownership": "mine", "voiceScope": "brand"}):
            with self.subTest(consent=consent):
                with self.assertRaises(AlphaError) as caught:
                    V.parse_request({"route": "platform_export", "provider": "x", "consent": consent})
                self.assertEqual((caught.exception.status, caught.exception.code), (400, "consent_required"))

    def test_ownership_and_scope_are_asked_once_and_must_be_known_values(self):
        for change in ({"ownership": "everyone"}, {"voiceScope": "blend"}, {"ownership": None}):
            with self.assertRaises(AlphaError) as caught:
                V.parse_request({"route": "platform_export", "provider": "x", "consent": {**CONSENT, **change}})
            self.assertEqual(caught.exception.status, 400)
        wanted = V.parse_request({"route": "platform_export", "provider": "x", "consent": {**CONSENT, "ownership": "mixed_authors", "voiceScope": "separate"}})
        self.assertEqual(wanted["consent"], {"ownership": "mixed_authors", "voiceScope": "separate"})
        self.assertEqual((wanted["accountKey"], wanted["accountLabel"], wanted["connectionId"], wanted["since"]), ("export", "X export", None, None))

    def test_route_provider_account_and_since(self):
        good = {"route": "official_api", "provider": "threads", "connectionId": "conn-t1", "consent": CONSENT}
        self.assertEqual(V.parse_request({**good, "since": "2026-01-01"})["since"], datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(V.parse_request({**good, "since": "2026-01-01T08:00:00+08:00"})["since"], datetime(2026, 1, 1, tzinfo=timezone.utc))
        for bad in ({"route": "scrape"}, {"provider": "Threads!"}, {"provider": "myspace"}, {"connectionId": ""}, {"connectionId": 5},
                    {"since": "yesterday"}, {"since": "2026-01-01T08:00:00"}, {"since": 5}):
            with self.subTest(bad=bad):
                with self.assertRaises(AlphaError) as caught:
                    V.parse_request({**good, **bad})
                self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(AlphaError):
            V.parse_request(None)
        export = V.parse_request({"route": "platform_export", "provider": "linkedin", "accountKey": " urn:li:person:abc ", "accountLabel": " Studio ", "consent": CONSENT,
                                  "connectionId": "ignored"})
        self.assertEqual((export["accountKey"], export["accountLabel"], export["connectionId"]), ("urn:li:person:abc", "Studio", None))
        for bad in ("", "x" * 201, "line\nbreak", 7):
            with self.assertRaises(AlphaError):
                V.parse_request({"route": "platform_export", "provider": "linkedin", "accountKey": bad, "consent": CONSENT})

    def test_batch_shape_limits(self):
        batch = V.parse_batch({"items": [item("1")], "skipped": {"unsupported": 2, "empty": 1}, "final": True, "seq": 3})
        self.assertEqual((len(batch["items"]), batch["skipped"], batch["final"], batch["seq"]), (1, {"unsupported": 2, "empty": 1}, True, 3))
        self.assertEqual(V.parse_batch({"items": []})["skipped"], {"unsupported": 0, "empty": 0})
        for bad in (None, {}, {"items": "x"}, {"items": [item(str(n)) for n in range(201)]}, {"items": [], "skipped": {"unsupported": -1}},
                    {"items": [], "skipped": {"other": 1}}, {"items": [], "skipped": {"empty": "3"}}, {"items": [], "final": "yes"}, {"items": [], "seq": 0}):
            with self.subTest(bad=str(bad)[:40]):
                with self.assertRaises(AlphaError) as caught:
                    V.parse_batch(bad)
                self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(AlphaError) as caught:
            V.parse_batch({"items": [item("big", "字" * 20_000) for _ in range(9)]})      # 540 kB of text
        self.assertEqual(caught.exception.status, 413)


class BatchRuleTests(unittest.TestCase):
    def test_a_new_post_is_stored_with_its_facts(self):
        store = Store()
        plan, counts = store.batch([item("p1", published="ignored", publishedAt="2026-09-20T10:00:00+00:00", permalink="https://www.threads.net/@studio/post/p1", contentType="text")])
        row = plan["inserts"][0]
        self.assertEqual((row["provider"], row["account_key"], row["provider_post_id"], row["routes"], row["connection_id"], row["import_id"]),
                         ("threads", "t1", "p1", ["official_api"], "conn-t1", "run-1"))
        self.assertEqual((row["body"], row["language"], row["originality"], row["authorship"], row["generation_origin"], row["voice_scope"]),
                         (A, "en", "original", "self", "unknown", "brand"))
        self.assertEqual((row["status"], row["exclusion_reason"], row["duplicate_of"], row["revision"], row["label"]), ("eligible", None, None, 1, None))
        self.assertEqual((row["published_at"], row["permalink"], row["content_type"]), (datetime(2026, 9, 20, 10, tzinfo=timezone.utc), "https://www.threads.net/@studio/post/p1", "text"))
        self.assertEqual((row["body_hash"], row["norm_hash"]), (E.body_hash(A), E.norm_hash(A)))
        self.assertRegex(row["id"], r"^[0-9a-f-]{36}$")
        self.assertEqual(counts, {"discovered": 1, "retrieved": 1, "duplicates": 0, "excluded": 0, "unsupported": 0, "failed": 0})
        self.assertEqual(plan["observed"], (datetime(2026, 9, 20, 10, tzinfo=timezone.utc), datetime(2026, 9, 20, 10, tzinfo=timezone.utc)))

    def test_an_export_keeps_only_links_to_its_own_platform(self):
        cases = {
            "x": (["https://x.com/a/status/1", "https://twitter.com/a/status/1", "https://mobile.twitter.com/a/status/1"],
                  ["https://evil.example/x.com", "https://x.com.evil.example/a", "http://x.com/a/status/1"]),
            "instagram": (["https://instagram.com/p/1", "https://www.instagram.com/p/1"], ["https://instagram.com.evil.example/p/1", "https://cdn.instagram.com/p/1"]),
            "facebook": (["https://facebook.com/1", "https://www.facebook.com/1", "https://m.facebook.com/1"], ["https://facebook.example/1", "https://l.facebook.com/l.php"]),
            "threads": (["https://threads.net/@a/post/1", "https://www.threads.net/@a/post/1", "https://threads.com/@a/post/1", "https://www.threads.com/@a/post/1"],
                        ["https://threads.example/@a/post/1"]),
            "linkedin": (["https://linkedin.com/feed/update/1", "https://www.linkedin.com/feed/update/1"], ["https://lnkd.in/abc", "https://linkedin.com.evil.example/1"]),
            "bluesky": (["https://bsky.app/profile/a/post/1"], ["https://bsky.social/profile/a", "https://staging.bsky.app/profile/a/post/1"]),
            "mastodon": (["https://mastodon.social/@a/1", "https://social.example.org/@a/1"], ["http://mastodon.social/@a/1", "javascript:alert(1)", "data:text/html,x"]),
        }
        for provider, (kept, refused) in cases.items():
            with self.subTest(provider=provider):
                run = run_context(provider=provider, route="platform_export", connectionId=None, accountKey="export")
                items = [item(f"k{index}", permalink=link) for index, link in enumerate(kept)] + [item(f"r{index}", permalink=link) for index, link in enumerate(refused)]
                links = {post["externalId"]: post["permalink"] for post in V.prepare(items, run=run, journal=set())["posts"]}
                self.assertEqual([links[f"k{index}"] for index in range(len(kept))], kept)
                self.assertEqual([links[f"r{index}"] for index in range(len(refused))], [None] * len(refused))
        # A connector's reader builds its own links; that route is unchanged.
        self.assertEqual(V.prepare([item("o1", permalink="https://www.threads.net/@a/post/1")], run=run_context(), journal=set())["posts"][0]["permalink"],
                         "https://www.threads.net/@a/post/1")

    def test_the_same_post_from_api_then_export_is_one_row_with_two_routes(self):
        store = Store()
        store.batch([item("p1")])
        export = run_context(id="run-2", route="platform_export", connectionId=None)
        plan, counts = store.batch([item("p1")], run=export)
        self.assertEqual((plan["inserts"], len(store.rows)), ([], 1))
        row = store.post("p1")
        self.assertEqual((row["routes"], row["connection_id"], row["import_id"], row["revision"]), (["official_api", "platform_export"], "conn-t1", "run-2", 1))
        self.assertEqual(counts, {"discovered": 1, "retrieved": 1, "duplicates": 1, "excluded": 0, "unsupported": 0, "failed": 0})
        # Seen again later by the same route: refreshed, not a duplicate.
        again = store.batch([item("p1")], run=run_context(id="run-3"))[1]
        self.assertEqual((again["retrieved"], again["duplicates"], store.post("p1")["routes"]), (1, 0, ["official_api", "platform_export"]))

    def test_changed_text_is_a_new_revision_and_corrections_survive(self):
        store = Store()
        store.batch([item("p1")])
        store.post("p1").update(authorship="team", label="representative")
        plan, _ = store.batch([item("p1", B)], run=run_context(id="run-2"))
        row = store.post("p1")
        self.assertEqual((row["revision"], row["body"], row["body_hash"], row["norm_hash"]), (2, B, E.body_hash(B), E.norm_hash(B)))
        self.assertEqual((row["authorship"], row["label"], row["status"]), ("team", "representative", "eligible"))
        self.assertEqual(len(plan["seen"]), 1)
        store.batch([item("p1", B)], run=run_context(id="run-3"))
        self.assertEqual(store.post("p1")["revision"], 2)                      # unchanged text: no new revision
        # The person's own exclusion is not undone by a re-read either.
        store.post("p1").update(status="excluded", exclusion_reason="manual")
        store.batch([item("p1", B)], run=run_context(id="run-4"))
        self.assertEqual((store.post("p1")["status"], store.post("p1")["exclusion_reason"]), ("excluded", "manual"))

    def test_counters_are_exact_for_a_mixed_batch(self):
        store = Store()
        store.batch([item("old", B, publishedAt="2026-01-01T00:00:00Z")], run=run_context(id="run-0", provider="instagram", accountKey="i1", connectionId="conn-i1"))
        items = [
            item("n1"),                                                        # new and eligible
            item("n2", "Someone else's words.", kind="repost"),                # excluded: repost
            item("n3", "Out now!"),                                            # excluded: too short
            item("n4", B + " #autumn", publishedAt="2026-02-01T00:00:00Z"),    # the Instagram caption again, later: duplicate
            item("n1"),                                                        # listed twice by the provider: duplicate
            item("n5", "   "),                                                 # no words: unsupported
            item("n6", None),                                                  # unsupported
            {"text": "no id"}, "junk", item("", "empty id"), item("n7", "x" * 20_001), item(8, A),   # failed
            item("n9", C, kind="quote"),                                       # new and eligible
        ]
        plan, counts = store.batch(items, journal={("conn-t1", "n10")}, skipped={"unsupported": 3, "empty": 2})
        self.assertEqual(counts, {"discovered": len(items) + 5, "retrieved": 6, "duplicates": 2, "excluded": 2, "unsupported": 7, "failed": 5})
        self.assertEqual(counts["discovered"], counts["retrieved"] + counts["unsupported"] + counts["failed"])
        self.assertEqual(sorted(row["provider_post_id"] for row in plan["inserts"]), ["n1", "n2", "n3", "n4", "n9"])
        self.assertEqual((store.post("n2")["status"], store.post("n2")["exclusion_reason"]), ("excluded", "repost"))
        self.assertEqual((store.post("n3")["status"], store.post("n3")["exclusion_reason"]), ("excluded", "too_short"))
        self.assertEqual((store.post("n4")["status"], store.post("n4")["exclusion_reason"]), ("excluded", "duplicate"))
        self.assertEqual(store.post("n9")["originality"], "quote")

    def test_a_repost_is_recorded_without_the_other_authors_words(self):
        store = Store()
        store.batch([item("r1", "Another person's announcement that is long enough to keep.", kind="repost"),
                     item("r2", "Another person's announcement that is long enough to keep.", kind="repost")])
        first, second = store.post("r1"), store.post("r2")
        self.assertEqual((first["body"], first["originality"], first["language"]), (V.REPOST_BODY, "repost", "und"))
        self.assertNotIn("announcement", json.dumps(first, default=str))
        self.assertNotEqual(first["norm_hash"], second["norm_hash"])           # reposts are never grouped with each other
        self.assertEqual((second["duplicate_of"], second["exclusion_reason"]), (None, "repost"))

    def test_a_cross_post_points_at_the_earliest_copy(self):
        store = Store()
        store.batch([item("ig", A + "\n.\n#launch #beta", publishedAt="2026-09-20T10:05:00Z")],
                    run=run_context(id="run-ig", provider="instagram", accountKey="i1", connectionId="conn-i1"))
        store.batch([item("th", A, publishedAt="2026-09-20T10:00:00Z")])       # the Threads copy was published first
        store.batch([item("li", A.upper(), publishedAt="2026-09-21T09:00:00Z")], run=run_context(id="run-li", provider="linkedin", accountKey="export", route="platform_export", connectionId=None))
        threads, instagram, linkedin = store.post("th"), store.post("ig", "instagram"), store.post("li", "linkedin")
        self.assertEqual((threads["duplicate_of"], threads["status"]), (None, "eligible"))
        self.assertEqual((instagram["duplicate_of"], instagram["status"], instagram["exclusion_reason"]), (threads["id"], "excluded", "duplicate"))
        self.assertEqual((linkedin["duplicate_of"], linkedin["exclusion_reason"]), (threads["id"], "duplicate"))
        self.assertEqual(len(store.rows), 3)                                   # lineage kept: three rows, one piece of evidence
        self.assertEqual(sum(row["status"] == "eligible" for row in store.rows.values()), 1)

    def test_undated_copies_fall_back_to_the_order_they_were_seen(self):
        store = Store()
        store.batch([item("a1")], now=NOW)
        store.batch([item("b1")], run=run_context(id="run-b", provider="mastodon", accountKey="m1@social.example.org", connectionId="conn-m1"), now=NOW + timedelta(minutes=5))
        self.assertEqual(store.post("b1", "mastodon")["duplicate_of"], store.post("a1")["id"])

    def test_a_separate_voice_is_never_deduplicated_against_the_brand(self):
        store = Store()
        store.batch([item("brand-1")])
        founder = run_context(id="run-f", provider="mastodon", accountKey="m1@social.example.org", connectionId="conn-m1",
                              consent={"ownership": "mine", "voiceScope": "separate"})
        store.batch([item("founder-1")], run=founder)
        row = store.post("founder-1", "mastodon")
        self.assertEqual((row["voice_scope"], row["duplicate_of"], row["status"]), ("separate", None, "eligible"))

    def test_short_texts_are_not_grouped(self):
        store = Store()
        plan, counts = store.batch([item("s1", "Thanks!"), item("s2", "Thanks!")])
        self.assertEqual([row["exclusion_reason"] for row in plan["inserts"]], ["too_short", "too_short"])
        self.assertEqual((counts["duplicates"], counts["excluded"]), (0, 2))

    def test_lineage_and_unknown_authors(self):
        store = Store()
        _, counts = store.batch([item("pub", C), item("own", B)], journal={("conn-t1", "pub")})
        self.assertEqual((store.post("pub")["generation_origin"], store.post("pub")["exclusion_reason"], counts["excluded"]), ("rafii_published", "rafii_published", 1))
        self.assertEqual(store.post("own")["generation_origin"], "unknown")
        mixed = run_context(id="run-m", provider="x", accountKey="export", route="platform_export", connectionId=None,
                            consent={"ownership": "mixed_authors", "voiceScope": "brand"})
        store.batch([item("x1", A + " And one more thing.")], run=mixed)
        self.assertEqual((store.post("x1", "x")["authorship"], store.post("x1", "x")["status"], store.post("x1", "x")["connection_id"]), ("unknown", "retrieved", None))

    def test_survivors_of_a_removed_original_get_a_new_one(self):
        store = Store()
        store.batch([item("th", A, publishedAt="2026-09-20T10:00:00Z")])
        store.batch([item("ig", A, publishedAt="2026-09-20T10:05:00Z")], run=run_context(id="run-ig", provider="instagram", accountKey="i1", connectionId="conn-i1"))
        store.batch([item("li", A, publishedAt="2026-09-21T10:05:00Z")], run=run_context(id="run-li", provider="linkedin", accountKey="export", route="platform_export", connectionId=None))
        original = store.rows.pop(store.post("th")["id"])
        changed = V.regroup([dict(row) for row in store.rows.values()])
        by_id = {row["provider_post_id"]: row for row in changed}
        self.assertEqual(set(by_id), {"ig", "li"})
        self.assertEqual((by_id["ig"]["duplicate_of"], by_id["ig"]["status"], by_id["ig"]["exclusion_reason"]), (None, "eligible", None))
        self.assertEqual(by_id["li"]["duplicate_of"], by_id["ig"]["id"])
        self.assertNotEqual(by_id["li"]["duplicate_of"], original["id"])
        self.assertEqual(V.regroup([dict(row) for row in by_id.values()]), [])   # already consistent: nothing to write


class ProposalTests(unittest.TestCase):
    def state(self, **proposal):
        return {"speaker": {"provisional": {"analysisMethod": "voice_import", "status": "proposed",
                                             "dimensions": [{"id": "tone", "evidence": {"postIds": ["p1", "p2"], "count": 40, "counter": ["p9"]}},
                                                            {"id": "structure", "evidence": {"postIds": ["p3"], "count": 12, "counter": 2}}, "junk"],
                                             **proposal}}}

    def test_a_proposal_citing_removed_posts_goes_stale(self):
        for removed in (["p2"], ["zz", "p9"], {"p3"}):
            state = self.state()
            self.assertTrue(V.stale_proposal(state, removed, 1_800_000_000.0))
            self.assertEqual((state["speaker"]["provisional"]["status"], state["speaker"]["provisional"]["staleReason"]), ("stale", "imported_posts_removed"))
            self.assertEqual(state["speaker"]["provisional"]["staleAt"], 1_800_000_000.0)

    def test_a_post_cited_only_as_counter_evidence_makes_the_proposal_stale_too(self):
        # The shape voice_corpus stores: `counter` is a count, the counter-example ids are `counterPostIds`.
        state = {"speaker": {"provisional": {"analysisMethod": "voice_import", "status": "proposed",
                                             "dimensions": [{"id": "emoji", "evidence": {"postIds": ["p1"], "count": 1, "counter": 1, "counterPostIds": ["p7"]}}]}}}
        self.assertTrue(V.stale_proposal(state, ["p7"], 1.0))
        self.assertEqual(state["speaker"]["provisional"]["status"], "stale")

    def test_everything_else_is_left_alone(self):
        untouched = self.state()
        self.assertFalse(V.stale_proposal(untouched, ["other"], 1.0))
        self.assertEqual(untouched, self.state())
        self.assertFalse(V.stale_proposal(self.state(), [], 1.0))
        self.assertFalse(V.stale_proposal(self.state(status="stale"), ["p1"], 1.0))
        manual = self.state(analysisMethod="user-authored")
        self.assertFalse(V.stale_proposal(manual, ["p1"], 1.0))
        for state in (None, {}, {"speaker": None}, {"speaker": {"provisional": None}}, {"speaker": {"provisional": "junk"}}):
            self.assertFalse(V.stale_proposal(state, ["p1"], 1.0))


# --- flow tests: scripted cursor, fake repository, fake transport ------------------------------------------------------
class Cursor:
    """Records statements. `answers` is a list of (substring, rows); the first matching entry answers the statement
    (entries marked once=True are used up)."""
    def __init__(self, answers=()):
        self.answers, self.statements, self.rows, self.rowcount = [list(a) for a in answers], [], [], 0

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.statements.append((flat, params))
        self.rows, self.rowcount = [], 0
        for answer in self.answers:
            if answer[0] in flat:
                self.rows = list(answer[1])
                self.rowcount = len(self.rows)
                if len(answer) > 2 and answer[2] == "once":
                    self.answers.remove(answer)
                return

    def executemany(self, sql, rows):
        for row in rows:
            self.execute(sql, row)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def sql(self, needle):
        return [(text, params) for text, params in self.statements if needle in text]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Database:
    """connection_factory() double: one shared scripted cursor; commit and rollback are counted."""
    def __init__(self, cursor):
        self.cur, self.commits, self.rollbacks = cursor, 0, 0

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class Repository:
    def __init__(self, cursor, role="owner", state=None, flags=(False, False, False, False)):
        self.cur, self.role, self.state, self.flags = cursor, role, state if state is not None else {}, flags
        self.connection_factory = Database(cursor)

    @contextmanager
    def transaction(self, token, workspace_id):
        if token == "stranger":
            raise AlphaError("Workspace unavailable.", 403)
        yield self.cur, (7, self.state, self.role, *self.flags), "user-1"


READY = ("to_regclass", [(True,)])
THROTTLE = ("pr_auth_throttle", [(1,)])
CREDENTIAL = ("FROM public.pr_encrypted_credentials", [("threads", "t1", ["threads_basic"], "sealed", "k1")])
RUN_ROW = ("run-1", WS, "official_api", "threads", "conn-t1", "t1", "@studio", "pending", {"version": "voice-import.v1", "ownership": "mine", "voiceScope": "brand", "at": "2026-11-25T12:00:00+00:00", "by": "user-1"},
           None, None, None, 0, 0, 0, 0, 0, 0, 0, 0, None, False, None, None, 0, None, None, None, NOW, NOW, None)


def importer(cursor, *, role="owner", state=None, values=FLAGS, providers=None, transport=None, flags=(False, False, False, False)):
    repository = Repository(cursor, role, state, flags)
    adapters = providers if providers is not None else {name: SimpleNamespace(platform=name.title(), history_approved=False) for name in ("threads", "instagram", "bluesky", "mastodon", "linkedin")}
    oauth = SimpleNamespace(repository=repository, providers=adapters, token_for_worker=Mock(return_value={"accessToken": "tok", "scopes": ["threads_basic"], "provider": "threads"}),
                            vault=SimpleNamespace(decrypt=lambda ciphertext, key: ciphertext))
    made = V.VoiceImporter(repository.connection_factory, oauth, transport=transport or Mock(), values=values, worker_id="worker-a", rand=lambda: 0.0,
                           resolver=lambda host, port, type=None: [(2, 1, 6, "", ("93.184.216.34", 443))])
    return made


class RouteTableTests(unittest.TestCase):
    def test_one_row_per_platform_with_reasons(self):
        rows = {row["provider"]: row for row in importer(Cursor()).routes()}
        self.assertEqual(list(rows), ["threads", "instagram", "bluesky", "mastodon", "linkedin", "facebook", "x"])
        self.assertEqual(set(rows["threads"]), {"provider", "platform", "official", "export"})
        self.assertEqual(rows["threads"]["official"], {"available": True, "reason": None, "detail": None})
        self.assertEqual((rows["threads"]["export"]["available"], rows["threads"]["export"]["files"]), (True, ["your_instagram_activity/threads/threads_and_replies.json"]))
        self.assertEqual((rows["bluesky"]["official"]["available"], rows["bluesky"]["export"]["available"], rows["bluesky"]["export"]["reason"]), (True, False, "deferred"))
        self.assertEqual((rows["linkedin"]["official"]["available"], rows["linkedin"]["official"]["reason"]), (False, "not_enabled"))
        self.assertEqual(rows["linkedin"]["export"]["files"], ["Shares.csv"])
        self.assertEqual((rows["facebook"]["official"]["reason"], rows["x"]["official"]["reason"]), ("scope_not_requested", "billed_reads"))
        self.assertEqual(rows["x"]["export"]["files"], ["data/tweets.js", "data/note-tweet.js"])
        self.assertEqual(rows["mastodon"]["export"]["files"], ["outbox.json"])
        for row in rows.values():
            self.assertTrue(row["official"]["available"] or (row["official"]["reason"] and row["official"]["detail"]))

    def test_deployment_decides_what_can_work(self):
        nothing = {row["provider"]: row for row in importer(Cursor(), values={V.FLAG: "1"}).routes()}
        self.assertEqual({nothing[name]["official"]["reason"] for name in ("threads", "instagram", "bluesky", "mastodon")}, {"not_enabled"})
        self.assertTrue(nothing["threads"]["export"]["available"])            # exports need no provider permission
        unmounted = {row["provider"]: row for row in importer(Cursor(), providers={}).routes()}
        self.assertEqual(unmounted["threads"]["official"]["reason"], "not_configured")
        listed = {**FLAGS, V.PROVIDERS_FLAG: "linkedin"}
        closed = {row["provider"]: row for row in importer(Cursor(), values=listed).routes()}
        self.assertEqual(closed["linkedin"]["official"]["reason"], "closed_permission")
        approved = {row["provider"]: row for row in importer(Cursor(), values=listed, providers={"linkedin": SimpleNamespace(platform="LinkedIn", history_approved=True)}).routes()}
        self.assertTrue(approved["linkedin"]["official"]["available"])


class RequestTests(unittest.TestCase):
    BODY = {"route": "official_api", "provider": "threads", "connectionId": "conn-t1", "consent": CONSENT}

    def test_an_unsupported_route_is_refused_with_the_tables_reason(self):
        cursor = Cursor()
        made = importer(cursor)
        table = {row["provider"]: row for row in made.routes()}
        for provider in ("x", "facebook", "linkedin"):
            with self.assertRaises(AlphaError) as caught:
                made.request(WS, "session", {**self.BODY, "provider": provider})
            self.assertEqual((caught.exception.status, caught.exception.code, str(caught.exception)),
                             (409, "voice_import_route_unavailable", table[provider]["official"]["detail"]))
        with self.assertRaises(AlphaError) as caught:
            made.request(WS, "session", {"route": "platform_export", "provider": "bluesky", "consent": CONSENT})
        self.assertEqual(str(caught.exception), table["bluesky"]["export"]["detail"])
        self.assertEqual(cursor.statements, [])                                # refused before any statement

    def test_a_consent_that_is_not_confirmed_never_reaches_the_database(self):
        cursor = Cursor()
        with self.assertRaises(AlphaError) as caught:
            importer(cursor).request(WS, "session", {**self.BODY, "consent": {"ownership": "mine", "voiceScope": "brand"}})
        self.assertEqual((caught.exception.code, cursor.statements), ("consent_required", []))

    def test_an_api_token_cannot_request_an_import(self):
        cursor = Cursor()
        with self.assertRaises(AlphaError) as caught:
            importer(cursor).request(WS, "prt_synthetic_token", self.BODY)
        self.assertEqual((caught.exception.status, caught.exception.code, cursor.statements), (403, "interactive_required", []))

    def test_only_someone_who_manages_connections_may_request(self):
        for role in ("viewer", "editor", "approver"):
            cursor = Cursor([READY, THROTTLE, CREDENTIAL])
            with self.assertRaises(AlphaError) as caught:
                importer(cursor, role=role).request(WS, "session", self.BODY)
            self.assertEqual(caught.exception.status, 403)
            self.assertEqual(cursor.sql("INSERT INTO public.pr_voice_imports"), [])
        cursor = Cursor([READY, THROTTLE, CREDENTIAL, ("INSERT INTO public.pr_voice_imports", [("run-1",)]), ("FROM public.pr_voice_imports", [RUN_ROW])])
        result = importer(cursor, role="editor", flags=(False, False, False, True)).request(WS, "session", self.BODY)   # can_manage_connections
        self.assertEqual(result["import"]["status"], "pending")

    def test_a_request_records_the_consent_and_returns_the_run(self):
        state = {"phase2": {"channels": [{"id": "conn-t1", "platform": "Threads", "account": "@studio"}]}}
        cursor = Cursor([READY, THROTTLE, CREDENTIAL, ("INSERT INTO public.pr_voice_imports", [("run-1",)]), ("FROM public.pr_voice_imports", [RUN_ROW])])
        made = importer(cursor, state=state)
        made.clock = lambda: NOW.timestamp()
        result = made.request(WS, "session", self.BODY)
        insert, params = cursor.sql("INSERT INTO public.pr_voice_imports")[0]
        self.assertIn("ON CONFLICT (workspace_id, provider, account_key) WHERE status IN ('pending','receiving','running') DO NOTHING", insert)
        consent = json.loads(next(p for p in params if isinstance(p, str) and p.startswith("{")))
        self.assertEqual(consent, {"version": "voice-import.v1", "ownership": "mine", "voiceScope": "brand", "retainText": True, "by": "user-1", "at": "2026-11-25T12:00:00+00:00"})
        self.assertIn("@studio", params)                                       # the label people see comes from the connected channel
        self.assertIn("t1", params)                                            # the account key is the provider's account id
        self.assertEqual(cursor.sql("pr_auth_throttle")[0][1][1:], (3600, 3600))
        audit = cursor.sql("INSERT INTO public.pr_audit_events")[0][1]
        self.assertEqual((audit[2], json.loads(audit[4])), ("voice_import.requested", {"consentVersion": "voice-import.v1", "route": "official_api", "provider": "threads",
                                                                                     "ownership": "mine", "voiceScope": "brand"}))
        run = result["import"]
        self.assertEqual(set(run), {"id", "route", "provider", "connectionId", "accountKey", "accountLabel", "status", "consent", "requestedSince", "observed", "counts",
                                    "pages", "moreRemaining", "totalKnown", "failure", "retryAt", "lastSyncAt", "createdAt", "updatedAt"})
        self.assertEqual(run["counts"], {"discovered": 0, "retrieved": 0, "duplicates": 0, "excluded": 0, "unsupported": 0, "failed": 0, "removedAtSource": 0})
        self.assertEqual(run["consent"], {"ownership": "mine", "voiceScope": "brand", "at": "2026-11-25T12:00:00+00:00"})
        self.assertEqual((run["moreRemaining"], run["totalKnown"], run["createdAt"]), (None, False, "2026-11-25T12:00:00+00:00"))
        self.assertNotIn("tok", json.dumps(result))

    def test_a_second_active_run_for_the_account_is_refused(self):
        cursor = Cursor([READY, THROTTLE, CREDENTIAL])                         # the insert returns no row: one is already active
        with self.assertRaises(AlphaError) as caught:
            importer(cursor).request(WS, "session", self.BODY)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "voice_import_active"))
        self.assertEqual(cursor.sql("INSERT INTO public.pr_audit_events"), [])

    def test_connection_permission_and_scope_are_checked(self):
        missing = Cursor([READY, THROTTLE])
        with self.assertRaises(AlphaError) as caught:
            importer(missing).request(WS, "session", self.BODY)
        self.assertEqual((caught.exception.status, caught.exception.code), (404, "connection_unavailable"))
        other = Cursor([READY, THROTTLE, ("FROM public.pr_encrypted_credentials", [("instagram", "i1", ["instagram_business_basic"], "sealed", "k1")])])
        with self.assertRaises(AlphaError) as caught:
            importer(other).request(WS, "session", self.BODY)
        self.assertEqual(caught.exception.code, "connection_unavailable")
        unscoped = Cursor([READY, THROTTLE, ("FROM public.pr_encrypted_credentials", [("threads", "t1", ["threads_content_publish"], "sealed", "k1")])])
        with self.assertRaises(AlphaError) as caught:
            importer(unscoped).request(WS, "session", self.BODY)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "voice_import_permission_required"))

    def test_one_account_belongs_to_one_voice(self):
        cursor = Cursor([READY, THROTTLE, CREDENTIAL, ("SELECT voice_scope FROM public.pr_voice_posts", [("separate",)])])
        with self.assertRaises(AlphaError) as caught:
            importer(cursor).request(WS, "session", self.BODY)
        self.assertEqual((caught.exception.status, caught.exception.code), (409, "voice_scope_conflict"))

    def test_before_the_migration_and_outside_the_workspace_list_the_feature_does_not_exist(self):
        cursor = Cursor([("to_regclass", [(False,)])])
        with self.assertRaises(AlphaError) as caught:
            importer(cursor).request(WS, "session", self.BODY)
        self.assertEqual((caught.exception.status, caught.exception.code), (404, "feature_disabled"))
        self.assertEqual(len(cursor.statements), 1)
        elsewhere = Cursor()
        with self.assertRaises(AlphaError) as caught:
            importer(elsewhere, values={**FLAGS, V.WORKSPACES_FLAG: "22222222-2222-2222-2222-222222222222"}).status(WS, "session")
        self.assertEqual((caught.exception.code, elsewhere.statements), ("feature_disabled", []))

    def test_uploads_have_their_own_looser_limit(self):
        export = {"route": "platform_export", "provider": "x", "consent": CONSENT}
        cursor = Cursor([READY, THROTTLE, ("INSERT INTO public.pr_voice_imports", [("run-9",)]), ("FROM public.pr_voice_imports", [RUN_ROW])])
        importer(cursor).request(WS, "session", export)
        self.assertEqual(cursor.sql("FROM public.pr_encrypted_credentials"), [])   # an upload reads no connection
        insert, params = cursor.sql("INSERT INTO public.pr_voice_imports")[0]
        self.assertIn("receiving", params)
        limited = Cursor([READY, ("pr_auth_throttle", [(V.UPLOADS_PER_HOUR + 1,)])])
        with self.assertRaises(AlphaError) as caught:
            importer(limited).request(WS, "session", export)
        self.assertEqual((caught.exception.status, caught.exception.code), (429, "voice_import_throttled"))
        official = Cursor([READY, ("pr_auth_throttle", [(V.REQUESTS_PER_HOUR + 1,)])])
        with self.assertRaises(AlphaError) as caught:
            importer(official).request(WS, "session", self.BODY)
        self.assertEqual(caught.exception.code, "voice_import_throttled")


class RoleTests(unittest.TestCase):
    def test_reading_is_for_members_and_correcting_is_for_editors(self):
        for role, allowed in (("viewer", False), ("approver", False), ("editor", True), ("admin", True)):
            cursor = Cursor([READY])
            call = lambda: importer(cursor, role=role).correct_post(WS, "session", "33333333-3333-3333-3333-333333333333", {"authorship": "guest"})
            if allowed:
                with self.assertRaises(AlphaError) as caught:
                    call()
                self.assertEqual(caught.exception.status, 404)                 # allowed in; the scripted post does not exist
            else:
                with self.assertRaises(AlphaError) as caught:
                    call()
                self.assertEqual(caught.exception.status, 403)
        for method, args in (("cancel", ("run-1",)), ("refresh", ("run-1", {})), ("delete", ("run-1",)), ("items", ("run-1", {"items": []}))):
            cursor = Cursor([READY])
            with self.subTest(method=method):
                with self.assertRaises(AlphaError) as caught:
                    getattr(importer(cursor, role="editor"), method)(WS, "session", *args)
                self.assertEqual(caught.exception.status, 403)
        with self.assertRaises(AlphaError) as caught:
            importer(Cursor([READY])).status(WS, "stranger")
        self.assertEqual(caught.exception.status, 403)

    def test_corrections_are_validated_before_anything_is_read(self):
        cursor = Cursor()
        made = importer(cursor)
        for bad in (None, {}, {"authorship": "me"}, {"label": "sponsored"}, {"excluded": "yes"}, {"authorship": "self", "other": 1}):
            with self.assertRaises(AlphaError) as caught:
                made.correct_post(WS, "session", "33333333-3333-3333-3333-333333333333", bad)
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(AlphaError) as caught:
            made.correct_post(WS, "session", "not-a-post-id", {"authorship": "self"})
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(cursor.statements, [])


class WorkerTests(unittest.TestCase):
    RUN = {"id": "run-1", "workspaceId": WS, "provider": "threads", "connectionId": "conn-t1", "accountKey": "t1", "route": "official_api", "cursor": None,
           "pages": 0, "attempts": 1, "requestedSince": None, "discovered": 0, "createdAt": NOW,
           "consent": {"version": "voice-import.v1", "ownership": "mine", "voiceScope": "brand"}}

    def worker(self, transport, cursor=None):
        made = importer(cursor or Cursor(), transport=transport)
        made._eligible = Mock(return_value={"scopes": ["threads_basic"], "journal": set(), "stored": "sealed"})
        made._live = Mock(return_value=True)
        made._store_page = Mock(return_value={"retrieved": 1})
        made._finish = Mock()
        made._handback = Mock()
        return made

    def page(self, cursor):
        body = {"data": [{"id": "1", "text": A}]}
        if cursor:
            body["paging"] = {"next": "https://n", "cursors": {"after": cursor}}
        return {"status": 200, "headers": {}, "body": body}

    def test_three_pages_a_tick_then_the_run_is_handed_back(self):
        transport = Mock(side_effect=[self.page("c1"), self.page("c2"), self.page("c3"), self.page("c4")])
        made = self.worker(transport)
        self.assertEqual(made.run_one(dict(self.RUN), deadline=10**9), "continued")
        self.assertEqual((transport.call_count, made._store_page.call_count), (3, 3))
        self.assertIn("after=c2", transport.call_args_list[2].args[1])
        made._handback.assert_called_once()
        made._finish.assert_not_called()

    def test_the_last_page_finishes_the_run(self):
        transport = Mock(side_effect=[self.page("c1"), self.page(None)])
        made = self.worker(transport)
        self.assertEqual(made.run_one(dict(self.RUN), deadline=10**9), "done")
        self.assertEqual([call.args[2] for call in made._store_page.call_args_list], [False, True])   # done flag of each stored page
        made._handback.assert_not_called()

    def test_cancel_stops_the_next_page(self):
        transport = Mock(side_effect=[self.page("c1"), self.page("c2")])
        made = self.worker(transport)
        made._live = Mock(side_effect=[True, False])                           # cancelled after the first page
        self.assertEqual(made.run_one(dict(self.RUN), deadline=10**9), "cancelled")
        self.assertEqual((transport.call_count, made._store_page.call_count), (1, 1))

    def test_a_lost_lease_stores_nothing_more(self):
        transport = Mock(side_effect=[self.page("c1"), self.page("c2")])
        made = self.worker(transport)
        made._store_page = Mock(return_value=None)
        self.assertEqual(made.run_one(dict(self.RUN), deadline=10**9), "lost_lease")
        self.assertEqual(transport.call_count, 1)

    def test_retry_after_sets_retry_at(self):
        cursor = Cursor()
        made = importer(cursor, transport=Mock(return_value={"status": 429, "headers": {"retry-after": "90"}, "body": {}}))
        made._eligible = Mock(return_value={"scopes": ["threads_basic"], "journal": set(), "stored": "sealed"})
        made._live = Mock(return_value=True)
        self.assertEqual(made.run_one(dict(self.RUN), deadline=10**9), "retry")
        sql, params = cursor.sql("UPDATE public.pr_voice_imports")[0]
        self.assertIn("retry_at=now() + make_interval(secs => %s::float8)", sql)
        self.assertIn("lease_owner=%s AND status='running'", sql)             # only the worker that holds the lease may reschedule
        self.assertEqual((params[0], params[1]), ("http_429", 90))            # the provider's wait, not the shorter default
        without = Cursor()
        made = importer(without, transport=Mock(return_value={"status": 503, "headers": {}, "body": {}}))
        made._eligible = Mock(return_value={"scopes": ["threads_basic"], "journal": set(), "stored": "sealed"})
        made._live = Mock(return_value=True)
        made.run_one({**self.RUN, "attempts": 3}, deadline=10**9)
        self.assertEqual(without.sql("UPDATE public.pr_voice_imports")[0][1][1], 120)   # 30 s doubled twice

    def test_five_attempts_then_failed(self):
        made = self.worker(Mock(return_value={"status": 429, "headers": {"retry-after": "90"}, "body": {}}))
        self.assertEqual(made.run_one({**self.RUN, "attempts": 5}, deadline=10**9), "failed")
        made._finish.assert_called_once_with({**self.RUN, "attempts": 5}, "failed", "http_429")
        made._handback.assert_not_called()

    def test_a_refused_read_fails_at_once_and_an_unreachable_provider_is_retried(self):
        for status in (400, 401, 403, 404):
            made = self.worker(Mock(return_value={"status": status, "headers": {}, "body": {}}))
            self.assertEqual(made.run_one(dict(self.RUN), deadline=10**9), "failed")
            self.assertEqual(made._finish.call_args.args[1:], ("failed", f"http_{status}"))
        made = self.worker(Mock(side_effect=AlphaError("The provider is temporarily unreachable.", 503)))
        self.assertEqual(made.run_one(dict(self.RUN), deadline=10**9), "retry")
        self.assertEqual(made._handback.call_args.kwargs["failure"], "transport")
        made = self.worker(Mock(side_effect=RuntimeError("secret-bearing failure")))
        with self.assertLogs("postriff.voice_import", "WARNING") as logs:
            self.assertEqual(made.run_one(dict(self.RUN), deadline=10**9), "retry")
        self.assertNotIn("secret-bearing", "".join(logs.output))

    def test_paging_that_cannot_continue_fails_and_says_more_remains(self):
        made = self.worker(Mock(return_value={"status": 200, "headers": {}, "body": {"data": [], "paging": {"next": "https://n", "cursors": {}}}}))
        self.assertEqual(made.run_one(dict(self.RUN), deadline=10**9), "failed")
        made._finish.assert_called_once()
        self.assertEqual((made._finish.call_args.args[1:], made._finish.call_args.kwargs), (("failed", "incomplete_paging"), {"more": True}))

    def test_an_account_that_is_no_longer_eligible_is_cancelled_without_a_read(self):
        transport = Mock()
        made = self.worker(transport)
        made._eligible = Mock(return_value=None)
        self.assertEqual(made.run_one(dict(self.RUN), deadline=10**9), "cancelled")
        made._finish.assert_called_once_with(self.RUN, "cancelled", "not_eligible")
        transport.assert_not_called()

    def test_a_revoked_grant_fails_the_run(self):
        made = self.worker(Mock())
        made.oauth.token_for_worker = Mock(side_effect=AlphaError("Connection unavailable.", 404))
        self.assertEqual(made.run_one(dict(self.RUN), deadline=10**9), "failed")
        self.assertEqual(made._finish.call_args.args[1:], ("failed", "credential"))

    def test_the_deadline_is_respected(self):
        transport = Mock(side_effect=[self.page("c1")])
        made = self.worker(transport)
        ticks = iter([0.0, 100.0, 100.0])
        made.monotonic = lambda: next(ticks)
        self.assertEqual(made.run_one(dict(self.RUN), deadline=50.0), "continued")
        self.assertEqual(transport.call_count, 1)

    def test_bluesky_needs_no_token_and_only_did_and_server_reach_the_reader(self):
        stored = json.dumps({"v": 1, "did": "did:plc:abcdefghijklmnopqrstuvwx", "pds": "https://pds.example.com", "at": "access-must-stay", "jwk": {"d": "private-must-stay"}})
        transport = Mock(return_value={"status": 200, "headers": {}, "body": {"records": []}})
        made = self.worker(transport)
        made._eligible = Mock(return_value={"scopes": ["atproto"], "journal": set(), "stored": stored})
        made.run_one({**self.RUN, "provider": "bluesky", "accountKey": "did:plc:abcdefghijklmnopqrstuvwx"}, deadline=10**9)
        made.oauth.token_for_worker.assert_not_called()                        # a public read never refreshes the account's session
        self.assertTrue(transport.call_args.args[1].startswith("https://pds.example.com/xrpc/com.atproto.repo.listRecords?"))
        self.assertNotIn("must-stay", json.dumps([list(call.args) + [call.kwargs] for call in transport.call_args_list]))
        self.assertEqual(transport.call_args.kwargs, {})

    def test_mastodon_sends_its_token_only_when_the_grant_can_read_statuses(self):
        session = json.dumps({"v": 1, "at": "bearer-1", "instance": "social.example.org"})
        for scopes, expected in ((["read:accounts"], {}), (["read:accounts", "read:statuses"], {"headers": {"Authorization": "Bearer bearer-1"}})):
            transport = Mock(return_value={"status": 200, "headers": {}, "body": []})
            made = self.worker(transport)
            made.oauth.token_for_worker = Mock(return_value={"accessToken": session, "scopes": scopes})
            made.run_one({**self.RUN, "provider": "mastodon", "accountKey": "109@social.example.org"}, deadline=10**9)
            self.assertEqual(transport.call_args.kwargs, expected)

    def test_tick_never_raises_and_is_inert_before_the_migration(self):
        def broken():
            raise RuntimeError("database down")
        made = V.VoiceImporter(broken, SimpleNamespace(), transport=Mock(), values=FLAGS)
        with self.assertLogs("postriff.voice_import", "WARNING"):
            self.assertEqual(made.tick()["status"], "unavailable")
        cursor = Cursor([("to_regclass", [(False,)])])
        self.assertEqual(importer(cursor).tick(), {"status": "not_migrated"})
        self.assertEqual(len(cursor.statements), 1)

    def test_tick_claims_at_most_two_runs_with_a_lease(self):
        cursor = Cursor([READY])
        made = importer(cursor)
        made.run_one = Mock(return_value="done")
        result = made.tick()
        self.assertEqual((result["status"], result["claimed"]), ("ok", 0))
        sql, params = next((text, params) for text, params in cursor.statements if "FOR UPDATE SKIP LOCKED" in text)
        self.assertIn("route='official_api'", sql)
        self.assertIn("(retry_at IS NULL OR retry_at <= now())", sql)
        self.assertEqual(params[:2], ("worker-a", 120))
        self.assertEqual(params[-1], 2)


class DisconnectTests(unittest.TestCase):
    def test_purge_never_breaks_the_disconnect(self):
        class Failing(Cursor):
            def execute(self, sql, params=None):
                super().execute(sql, params)
                if "DELETE FROM public.pr_voice_posts" in sql:
                    raise RuntimeError("secret-bearing failure")
        cursor = Failing([READY])
        with self.assertLogs("postriff.voice_import", "WARNING") as logs:
            self.assertFalse(importer(cursor).purge_connection(cursor, WS, "conn-t1", {}))
        self.assertTrue(any(text.startswith("ROLLBACK TO SAVEPOINT") for text, _ in cursor.statements))
        self.assertIn('"event": "voice_import.purge_failed"', logs.output[0])
        self.assertNotIn("secret-bearing", logs.output[0])

    def test_purge_deletes_official_posts_and_marks_a_citing_proposal_stale(self):
        state = {"speaker": {"provisional": {"analysisMethod": "voice_import", "status": "proposed", "dimensions": [{"evidence": {"postIds": ["post-1"]}}]}}}
        cursor = Cursor([READY, ("DELETE FROM public.pr_voice_posts", [("post-1", "hash-1")])])
        self.assertTrue(importer(cursor).purge_connection(cursor, WS, "conn-t1", state))
        self.assertEqual(state["speaker"]["provisional"]["status"], "stale")
        delete = cursor.sql("DELETE FROM public.pr_voice_posts")[0][0]
        self.assertIn("NOT ('platform_export' = ANY(routes))", delete)        # a post the person also uploaded stays, as an upload
        self.assertTrue(cursor.sql("array_remove(routes,'official_api')"))
        cancelled = cursor.sql("UPDATE public.pr_voice_imports SET status='cancelled'")[0]
        self.assertIn("status IN ('pending','running')", cancelled[0])
        self.assertEqual(cancelled[1][-2:], (WS, "conn-t1"))

    def test_before_the_migration_nothing_is_touched(self):
        cursor = Cursor([("to_regclass", [(False,)])])
        self.assertFalse(importer(cursor).purge_connection(cursor, WS, "conn-t1", {}))
        self.assertEqual([text for text, _ in cursor.statements if "pr_voice" in text and "to_regclass" not in text], [])

    def test_the_sweep_purges_accounts_disconnected_while_the_flag_was_off(self):
        state = {"speaker": {"provisional": {"analysisMethod": "voice_import", "status": "proposed", "dimensions": [{"evidence": {"postIds": ["post-1"]}}]}}}
        cursor = Cursor([READY, ("SELECT DISTINCT i.workspace_id", [(WS, "conn-t1")]), ("SELECT state FROM public.pr_workspaces", [(json.dumps(state),)]),
                         ("DELETE FROM public.pr_voice_posts", [("post-1", "hash-1")])])
        database = Database(cursor)
        self.assertEqual(V.sweep_revoked(database, clock=lambda: 5.0), {"status": "ok", "purged": 1})
        orphans = cursor.sql("SELECT DISTINCT i.workspace_id")[0][0]
        self.assertIn("route='official_api'", orphans)
        self.assertIn("c.revoked_at IS NULL", orphans)
        self.assertEqual(cursor.sql("DELETE FROM public.pr_voice_posts")[0][1], (WS, "conn-t1"))
        saved = cursor.sql("UPDATE public.pr_workspaces SET state")
        self.assertEqual((json.loads(saved[0][1][0])["speaker"]["provisional"]["status"], json.loads(saved[0][1][0])["speaker"]["provisional"]["staleAt"]), ("stale", 5.0))
        self.assertEqual(database.commits, 2)

    def test_the_sweep_is_inert_before_the_migration_and_never_raises(self):
        cursor = Cursor([("to_regclass", [(False,)])])
        self.assertEqual(V.sweep_revoked(Database(cursor)), {"status": "not_migrated"})
        self.assertEqual(len(cursor.statements), 1)

        def broken():
            raise RuntimeError("database down")
        with self.assertLogs("postriff.voice_import", "WARNING"):
            self.assertEqual(V.sweep_revoked(broken)["status"], "unavailable")


class HttpTests(unittest.TestCase):
    def service(self):
        made = Mock()
        made.status.return_value = {"imports": [], "coverage": {}, "routes": []}
        for name in ("request", "items", "cancel", "refresh"):
            getattr(made, name).return_value = {"import": {"id": "run-1"}}
        made.delete.return_value = {"deleted": True, "posts": 3}
        made.posts.return_value = {"posts": [], "nextCursor": None}
        made.correct_post.return_value = {"post": {"id": "p"}}
        return SimpleNamespace(voice_import=made), made

    def test_feature_disabled_when_the_importer_is_not_mounted(self):
        for method, parts in (("GET", []), ("POST", []), ("POST", ["run-1", "items"]), ("DELETE", ["run-1"]), ("GET", ["posts"]), ("POST", ["analysis"])):
            with self.assertRaises(AlphaError) as caught:
                H.handle(SimpleNamespace(), WS, "session", parts, method, {}, {})
            self.assertEqual((caught.exception.status, caught.exception.code), (404, "feature_disabled"))

    def test_every_route_reaches_its_method(self):
        service, made = self.service()
        self.assertEqual(H.handle(service, WS, "session", [], "GET", None, {}), {"imports": [], "coverage": {}, "routes": [], "analysis": None})
        made.status.assert_called_once_with(WS, "session")
        body = {"route": "platform_export"}
        self.assertEqual(H.handle(service, WS, "session", [], "POST", body, {}), {"import": {"id": "run-1"}})
        made.request.assert_called_once_with(WS, "session", body)
        H.handle(service, WS, "session", ["run-1", "items"], "POST", {"items": []}, {})
        made.items.assert_called_once_with(WS, "session", "run-1", {"items": []})
        H.handle(service, WS, "session", ["run-1", "cancel"], "POST", {}, {})
        made.cancel.assert_called_once_with(WS, "session", "run-1")
        H.handle(service, WS, "session", ["run-1", "refresh"], "POST", {"full": True}, {})
        made.refresh.assert_called_once_with(WS, "session", "run-1", {"full": True})
        self.assertEqual(H.handle(service, WS, "session", ["run-1"], "DELETE", {}, {}), {"deleted": True, "posts": 3})
        made.delete.assert_called_once_with(WS, "session", "run-1")
        query = {"provider": ["threads"], "accountKey": ["t1"], "status": ["eligible"], "cursor": ["abc"], "ids": ["a,b"], "extra": ["ignored"]}
        H.handle(service, WS, "session", ["posts"], "GET", None, query)
        made.posts.assert_called_once_with(WS, "session", {"provider": "threads", "accountKey": "t1", "status": "eligible", "cursor": "abc", "ids": "a,b"})
        H.handle(service, WS, "session", ["posts", "post-1"], "POST", {"authorship": "guest"}, {})
        made.correct_post.assert_called_once_with(WS, "session", "post-1", {"authorship": "guest"})

    def test_unknown_paths_and_methods_are_not_routes(self):
        service, made = self.service()
        for method, parts in (("PUT", []), ("DELETE", []), ("GET", ["run-1"]), ("GET", ["run-1", "items"]), ("POST", ["run-1", "explode"]), ("POST", ["posts"]),
                              ("GET", ["posts", "post-1"]), ("POST", ["a", "b", "c"]), ("GET", ["analysis"]), ("DELETE", ["posts", "post-1"])):
            with self.subTest(method=method, parts=parts):
                self.assertIsNone(H.handle(service, WS, "session", parts, method, {}, {}))
        self.assertEqual(made.method_calls, [])

    def test_status_codes(self):
        self.assertEqual(H.status_code([], "POST", {"import": {}}), 202)
        self.assertEqual(H.status_code(["run-1", "refresh"], "POST", {"import": {}}), 202)
        self.assertEqual(H.status_code(["analysis"], "POST", {"analysis": {}}), 202)
        self.assertEqual(H.status_code(["analysis"], "POST", {"quote": {}}), 200)
        for parts, method in (([], "GET"), (["run-1", "items"], "POST"), (["run-1", "cancel"], "POST"), (["run-1"], "DELETE"), (["posts"], "GET"), (["posts", "p"], "POST")):
            self.assertEqual(H.status_code(parts, method, {}), 200)

    def test_analysis_goes_to_the_corpus_analysis_service_when_one_is_mounted(self):
        service, made = self.service()
        with self.assertRaises(AlphaError) as caught:
            H.handle(service, WS, "session", ["analysis"], "POST", {"quote": True}, {})
        self.assertEqual((caught.exception.status, caught.exception.code), (404, "voice_analysis_unavailable"))
        analysis = Mock()
        # The shapes VoiceCorpusAnalysis returns: status {analysis, analyses}, a bare quote, start {analysis}.
        analysis.status.return_value = {"analysis": {"id": "a0", "status": "running"}, "analyses": [{"id": "a0", "status": "running"}]}
        analysis.quote.return_value = {"id": "q1", "status": "quoted", "estimatedMicroUsd": 1200}
        analysis.start.return_value = {"analysis": {"id": "a1", "status": "queued"}}
        setattr(service, H.ANALYSIS_ATTRIBUTE, analysis)
        listed = H.handle(service, WS, "session", [], "GET", None, {})
        self.assertEqual(listed, {"imports": [], "coverage": {}, "routes": [], "analysis": {"id": "a0", "status": "running"},
                                  "analyses": [{"id": "a0", "status": "running"}]})   # the panel reads analysis.status directly
        analysis.status.assert_called_once_with(WS, "session")
        quoted = H.handle(service, WS, "session", ["analysis"], "POST", {"groupKey": "brand", "quote": True}, {})
        self.assertEqual(quoted, {"quote": {"id": "q1", "status": "quoted", "estimatedMicroUsd": 1200}})
        self.assertEqual(H.status_code(["analysis"], "POST", quoted), 200)
        analysis.quote.assert_called_once_with(WS, "session", "brand")
        started = H.handle(service, WS, "session", ["analysis"], "POST", {"quoteId": "q1"}, {})
        self.assertEqual((started, H.status_code(["analysis"], "POST", started)), ({"analysis": {"id": "a1", "status": "queued"}}, 202))
        analysis.start.assert_called_once_with(WS, "session", None, "q1")
        for bad in ({}, {"quote": False}, {"quote": True, "quoteId": "q1"}, {"quoteId": 5}, {"groupKey": 5, "quote": True}):
            with self.assertRaises(AlphaError) as caught:
                H.handle(service, WS, "session", ["analysis"], "POST", bad, {})
            self.assertEqual(caught.exception.status, 400)


class HostedRouteTests(unittest.TestCase):
    """The block in hosted_app.py: dispatch, status codes, the upload size limit and the 404 while the flag is off."""
    def call(self, service, method, path, body=None, raw=None):
        from postriff_phase2.hosted_app import HostedApplication
        app = HostedApplication(service, public_auth={})
        raw = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "provider=threads", "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
                   "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "https", "HTTP_HOST": "rafii.example", "HTTP_ORIGIN": "https://rafii.example",
                   "HTTP_AUTHORIZATION": "Bearer " + "i" * 32, "HTTP_X_POSTRIFF_REQUEST": "founder-alpha"}
        captured = {}
        result = b"".join(app(environ, lambda status, headers: captured.update(status=status))).decode()
        return captured["status"], json.loads(result)

    def test_routes_statuses_and_the_flag(self):
        made = Mock()
        made.status.return_value = {"imports": [], "coverage": {}, "routes": []}
        made.request.return_value = {"import": {"id": "run-1"}}
        made.refresh.return_value = {"import": {"id": "run-2"}}
        made.items.return_value = {"import": {"id": "run-1"}}
        made.delete.return_value = {"deleted": True, "posts": 0}
        made.posts.return_value = {"posts": [], "nextCursor": None}
        service = SimpleNamespace(oauth=SimpleNamespace(), voice_import=made)
        base = f"/api/workspaces/{WS}/voice-imports"
        self.assertEqual(self.call(service, "GET", base), ("200 OK", {"imports": [], "coverage": {}, "routes": [], "analysis": None}))
        made.request.assert_not_called()                                       # reading never starts an import
        self.assertEqual(self.call(service, "POST", base, {"route": "platform_export"}), ("202 Accepted", {"import": {"id": "run-1"}}))
        made.request.assert_called_once_with(WS, "i" * 32, {"route": "platform_export"})
        self.assertEqual(self.call(service, "POST", base + "/run-1/refresh", {"full": True})[0], "202 Accepted")
        self.assertEqual(self.call(service, "POST", base + "/run-1/items", {"items": []})[0], "200 OK")
        self.assertEqual(self.call(service, "DELETE", base + "/run-1", {}), ("200 OK", {"deleted": True, "posts": 0}))
        self.assertEqual(self.call(service, "GET", base + "/posts")[0], "200 OK")
        made.posts.assert_called_once_with(WS, "i" * 32, {"provider": "threads"})
        status, body = self.call(service, "POST", base + "/run-1/items", raw=b'{"items": [], "pad": "' + b"x" * (V.MAX_BATCH_BYTES + 1) + b'"}')
        self.assertEqual((status, body["code"]), ("413 Payload Too Large", "voice_import_batch_too_large"))
        made.items.assert_called_once()                                        # the oversized batch never reached the importer
        self.assertEqual(self.call(service, "GET", base + "/run-1/unknown")[0], "404 Not Found")
        del service.voice_import
        for method, path in (("GET", base), ("POST", base), ("POST", base + "/run-1/items"), ("DELETE", base + "/run-1")):
            status, body = self.call(service, method, path, {} if method != "GET" else None)
            self.assertEqual((status, body["code"]), ("404 Not Found", "feature_disabled"))

    def test_the_cron_step_runs_only_when_mounted(self):
        from postriff_phase2.hosted_app import HostedApplication
        from test_postriff_phase2_hosted import FakeService, FakeWorker, invoke
        cron = {"Authorization": "Bearer " + "c" * 24}
        service = FakeService()
        status, _, result = invoke(HostedApplication(service, FakeWorker(), {}, "c" * 24), "GET", "/api/cron/worker", headers=cron)
        self.assertEqual((status, "voiceImport" in result), (200, False))      # flag off: no step, no table access
        service.voice_import = Mock()
        service.voice_import.tick.return_value = {"status": "ok", "claimed": 1, "done": 1}
        status, _, result = invoke(HostedApplication(service, FakeWorker(), {}, "c" * 24), "GET", "/api/cron/worker", headers=cron)
        self.assertEqual((status, result["voiceImport"]), (200, {"status": "ok", "claimed": 1, "done": 1}))
        service.voice_import.tick.assert_called_once_with()

    def test_the_runtime_mounts_the_importer_only_with_the_flag(self):
        import inspect
        from postriff_phase2 import hosted_app
        self.assertIn("voice_import.mount(service, database, values, transport=http_transport)", inspect.getsource(hosted_app.runtime_from_environment))

    def test_the_runtime_mounts_the_importer_and_its_analysis_only_with_the_flag(self):
        from postriff_phase2 import hosted_app
        from postriff_phase2.voice_corpus import VoiceCorpusAnalysis

        def factory(url):
            def connect():
                raise AssertionError("building the runtime opens no database connection")
            return connect
        env = {"POSTRIFF_DATABASE_URL": "host=127.0.0.1 port=1 dbname=none", "POSTRIFF_SUPABASE_URL": "https://synthetic.supabase.co",
               "POSTRIFF_SUPABASE_PUBLISHABLE_KEY": "synthetic-publishable-key-for-tests", "POSTRIFF_SUPABASE_SECRET_KEY": "synthetic-secret-key-for-tests",
               "POSTRIFF_LOCAL_CLI": "0"}
        for flags, mounted in (({}, False), ({V.FLAG: "0"}, False), ({V.FLAG: "1"}, True)):
            with self.subTest(flags=flags), patch.object(hosted_app, "postgres_factory", side_effect=factory):
                service, _, _ = hosted_app.runtime_from_environment({**env, **flags})
                importer, analysis = getattr(service, "voice_import", None), getattr(service, H.ANALYSIS_ATTRIBUTE, None)
                self.assertEqual((importer is not None, analysis is not None, getattr(service.oauth, "voice_import", None) is importer),
                                 (mounted, mounted, True))
                if mounted:
                    self.assertIsInstance(analysis, VoiceCorpusAnalysis)
                    self.assertEqual((analysis.repository, analysis.ledger), (service.repository, service.ledger))
                    self.assertEqual(analysis._runtime, service.ideas._managed_writer)   # the managed writer, looked up per use

    def test_the_corpus_analysis_cron_step_runs_last_one_batch_a_tick_and_never_breaks_the_cron(self):
        from postriff_phase2.hosted_app import HostedApplication
        from test_postriff_phase2_hosted import FakeService, FakeWorker, invoke
        cron, order = {"Authorization": "Bearer " + "c" * 24}, []
        service = FakeService()
        app = HostedApplication(service, FakeWorker(), {}, "c" * 24)
        self.assertNotIn("voiceCorpusAnalysis", invoke(app, "GET", "/api/cron/worker", headers=cron)[2])   # not mounted: no step
        service.voice_import, service.voice_corpus_analysis = Mock(), Mock()
        service.voice_import.tick.side_effect = lambda: order.append("import") or {"status": "ok", "claimed": 0}
        service.voice_corpus_analysis.tick.side_effect = lambda **limits: order.append("analysis") or {"claimed": 1, "calls": 1, "done": 0}
        with patch("postriff_phase2.growth.trends.worker.cron", side_effect=lambda service: order.append("trends") or {"status": "ok"}):
            status, _, result = invoke(app, "GET", "/api/cron/worker", headers=cron)
        self.assertEqual((status, result["voiceCorpusAnalysis"], order), (200, {"claimed": 1, "calls": 1, "done": 0}, ["import", "trends", "analysis"]))
        self.assertEqual(list(result)[-1], "voiceCorpusAnalysis", "the paid model calls wait until every other cron step has run")
        service.voice_corpus_analysis.tick.assert_called_once_with(max_calls=1)
        service.voice_corpus_analysis.tick.side_effect = RuntimeError("secret-bearing failure")
        status, _, result = invoke(app, "GET", "/api/cron/worker", headers=cron)
        self.assertEqual((status, result["voiceCorpusAnalysis"]), (200, {"status": "unavailable", "error": "RuntimeError"}))
        self.assertNotIn("secret-bearing", json.dumps(result))

    def test_the_cron_sweeps_disconnected_accounts_whatever_the_flag_says(self):
        from postriff_phase2.hosted_app import HostedApplication
        from test_postriff_phase2_hosted import FakeService, FakeWorker, invoke
        service = FakeService()                                                 # no importer mounted
        service.repository = SimpleNamespace(connection_factory=Database(Cursor()))
        with patch("postriff_phase2.growth.history_import.sweep_pending_purges", return_value={"status": "ok"}), \
                patch("postriff_phase2.voice_import.sweep_revoked", return_value={"status": "ok", "purged": 1}) as sweep:
            status, _, result = invoke(HostedApplication(service, FakeWorker(), {}, "c" * 24), "GET", "/api/cron/worker", headers={"Authorization": "Bearer " + "c" * 24})
        self.assertEqual((status, result["voicePurges"], "voiceImport" in result), (200, {"status": "ok", "purged": 1}, False))
        sweep.assert_called_once_with(service.repository.connection_factory)

    def test_a_delete_needs_no_body(self):
        made = Mock()
        made.delete.return_value = {"deleted": True, "posts": 2}
        service = SimpleNamespace(oauth=SimpleNamespace(), voice_import=made)
        # The web client (web/src/lib/api/voice-import.ts) sends DELETE without a body.
        self.assertEqual(self.call(service, "DELETE", f"/api/workspaces/{WS}/voice-imports/run-1"), ("200 OK", {"deleted": True, "posts": 2}))
        made.delete.assert_called_once_with(WS, "i" * 32, "run-1")
        status, body = self.call(service, "DELETE", f"/api/workspaces/{WS}/voice-imports/run-1", raw=b"[1]")
        self.assertEqual((status, made.delete.call_count), ("400 Bad Request", 1))   # a body that is sent must still be a JSON object


class DisconnectFlowTests(unittest.TestCase):
    """oauth.disconnect, the block beside revoke_connection_samples: the importer purges inside the disconnect's own
    transaction (which holds the workspace row) and a proposal it marks stale is saved there; without the importer, or
    before migration 140, nothing of voice import runs."""
    CONNECTION = "conn-t1"
    LISTED = ("SELECT provider,access_ciphertext,key_id", [("threads", "sealed", "k1")])

    def disconnect(self, cursor, state, voice=None):
        from postriff_phase2.oauth import OAuthService
        oauth = OAuthService.__new__(OAuthService)
        repository = Repository(cursor, state=state)
        repository.assert_fresh = Mock()
        repository.get = Mock(return_value={"revision": 8, "state": state})
        repository.mutate = Mock(return_value={"revision": 9})
        oauth.repository, oauth.clock = repository, lambda: NOW.timestamp()
        oauth.vault = SimpleNamespace(decrypt=lambda value, key: value)
        oauth.commands = SimpleNamespace(engine=SimpleNamespace(invalidate=Mock()))
        oauth._shared_elsewhere = Mock(return_value=False)
        oauth._provider_for_access = Mock(return_value=SimpleNamespace(revoke=lambda access: True))
        if voice is not None:
            oauth.voice_import = voice
        with ExitStack() as stack:
            for target in ("postriff_phase2.hosted.audit", "postriff_phase2.account_pictures.guarded", "postriff_phase2.growth.history_import.mark_for_purge",
                           "postriff_phase2.growth.history_import.purge_after_disconnect", "postriff_phase2.product_events.record"):
                stack.enter_context(patch(target))
            return oauth.disconnect(WS, "session", self.CONNECTION)

    @staticmethod
    def first(cursor, prefix):
        return next(index for index, (text, _) in enumerate(cursor.statements) if text.startswith(prefix))

    def test_imported_posts_go_inside_the_disconnect_transaction(self):
        state = {"speaker": {"provisional": {"analysisMethod": "voice_import", "status": "proposed", "dimensions": [{"evidence": {"postIds": ["post-1"]}}]}}}
        cursor = Cursor([self.LISTED, READY, ("DELETE FROM public.pr_voice_posts", [("post-1", "hash-1")])])
        result = self.disconnect(cursor, state, importer(cursor))
        self.assertTrue(result["disconnected"])
        revoked = self.first(cursor, "UPDATE public.pr_encrypted_credentials SET revoked_at")
        purged = self.first(cursor, "DELETE FROM public.pr_voice_posts")
        saved = self.first(cursor, "UPDATE public.pr_workspaces SET state")
        self.assertLess(revoked, purged)
        self.assertLess(purged, saved)                                         # the stale proposal is saved with the disconnect
        self.assertEqual(cursor.statements[purged][1], (WS, self.CONNECTION))
        self.assertEqual(json.loads(cursor.statements[saved][1][0])["speaker"]["provisional"]["status"], "stale")

    def test_nothing_of_voice_import_runs_without_the_importer_or_its_tables(self):
        for voice in (None, "unmigrated"):
            cursor = Cursor([self.LISTED, ("to_regclass", [(False,)])])
            result = self.disconnect(cursor, {}, importer(cursor) if voice else None)
            self.assertTrue(result["disconnected"])
            self.assertEqual([text for text, _ in cursor.statements if "pr_voice" in text and "to_regclass" not in text], [])
            self.assertEqual(cursor.sql("UPDATE public.pr_workspaces SET state"), [])

    def test_a_disconnect_purges_imported_posts_even_where_the_importer_is_not_mounted(self):
        # POSTRIFF_VOICE_IMPORT off (rolled back) while posts read through this account are still stored.
        state = {"speaker": {"provisional": {"analysisMethod": "voice_import", "status": "proposed", "dimensions": [{"evidence": {"postIds": ["post-1"]}}]}}}
        cursor = Cursor([self.LISTED, READY, ("DELETE FROM public.pr_voice_posts", [("post-1", "hash-1")])])
        self.assertTrue(self.disconnect(cursor, state, None)["disconnected"])
        purged = self.first(cursor, "DELETE FROM public.pr_voice_posts")
        self.assertEqual(cursor.statements[purged][1], (WS, self.CONNECTION))
        self.assertIn("NOT ('platform_export' = ANY(routes))", cursor.statements[purged][0])
        self.assertTrue(cursor.sql("UPDATE public.pr_voice_imports SET status='cancelled'"))
        saved = self.first(cursor, "UPDATE public.pr_workspaces SET state")
        self.assertLess(purged, saved)
        self.assertEqual(json.loads(cursor.statements[saved][1][0])["speaker"]["provisional"]["status"], "stale")

    def test_the_importer_gets_the_disconnect_cursor_and_workspace_state(self):
        voice = Mock()
        voice.purge_connection.return_value = False                            # nothing cited: the state is not saved for it
        cursor = Cursor([self.LISTED])
        self.assertTrue(self.disconnect(cursor, {}, voice)["disconnected"])
        voice.purge_connection.assert_called_once_with(cursor, WS, self.CONNECTION, {})
        self.assertEqual(cursor.sql("UPDATE public.pr_workspaces SET state"), [])


class HarnessFixtureTests(unittest.TestCase):
    """tests/voice_import_fixtures.py, which scripts/postriff_dev_hosted.py --voice-import-fixture mounts: canned
    history served to the real readers, dev accounts that grant only the read scope, no network."""
    @classmethod
    def setUpClass(cls):
        import voice_import_fixtures
        cls.F = voice_import_fixtures
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from postriff_dev_hosted import DevProvider
        cls.accounts = cls.F.providers(DevProvider, "http://127.0.0.1:4331")

    def grant(self, provider, code="good-code"):
        account = self.accounts[provider]
        grant = account.exchange(code, "verifier", "https://dev.postriff.invalid/callback")
        return grant, account.identity(grant["accessToken"])

    def token(self, provider, grant):
        """What VoiceImporter._token hands the reader for this stored grant."""
        if provider == "bluesky":
            session = json.loads(grant["accessToken"])
            return json.dumps({"did": session["did"], "pds": session["pds"]})
        return grant["accessToken"]

    def history(self, provider, code="good-code"):
        grant, identity = self.grant(provider, code)
        transport, items, skipped, cursor, pages = self.F.HistoryTransport(), [], 0, None, 0
        while True:
            page = R.read_page(provider, token=self.token(provider, grant), account=identity["providerAccountId"], cursor=cursor, since=None,
                               transport=transport, resolver=self.F.resolve)
            items, skipped, pages = items + page.items, skipped + page.skipped, pages + 1
            if not page.more:
                return items, skipped, pages
            cursor = page.next_cursor

    def test_four_platforms_of_synthetic_history_over_several_pages(self):
        everything, kinds, languages = [], set(), set()
        # Left out by the readers: Instagram media without a caption, another author's Bluesky record, a followers-only toot.
        for provider, left_out in (("threads", 0), ("instagram", 2), ("bluesky", 1), ("mastodon", 1)):
            items, skipped, pages = self.history(provider)
            self.assertGreater(pages, 1, provider)                             # read over several pages, like a real account
            self.assertEqual(skipped, left_out, provider)
            self.assertTrue(all(item["publishedAt"] for item in items), provider)
            everything += items
            kinds |= {item["kind"] for item in items}
            languages |= {E.detect_language(item["text"]) for item in items if item["text"]}
        written = [item for item in everything if item["text"]]
        self.assertGreaterEqual(len(written), 40)
        self.assertLessEqual({"original", "reply", "quote", "repost"}, kinds)
        self.assertLessEqual({"en", "yue", "zh-Hant"}, languages)
        self.assertEqual(self.history("threads", "good-code-2")[0], [])         # the second dev account has no history

    def test_one_canned_post_is_the_harness_first_threads_publication(self):
        items, _, _ = self.history("threads")
        run = run_context(connectionId="conn-threads", accountKey=self.F.ACCOUNTS["threads"][0])
        journal = E.journal({"phase2": {"jobs": [{"providerReference": self.F.PUBLISHED_ID, "manifest": {"platform": "Threads", "channelId": "conn-elsewhere"}}]}})
        posts = {post["externalId"]: post for post in V.prepare(items, run=run, journal=journal)["posts"]}
        self.assertEqual((posts[self.F.PUBLISHED_ID]["generation_origin"], posts[self.F.PUBLISHED_ID]["exclusion_reason"]), ("rafii_published", "rafii_published"))
        self.assertEqual(sum(post["generation_origin"] == "rafii_published" for post in posts.values()), 1)

    def test_dev_accounts_grant_the_read_scope_and_nothing_to_publish(self):
        from postriff_phase2 import voice_import as importer_module
        for provider in ("threads", "instagram", "bluesky", "mastodon"):
            grant, identity = self.grant(provider)
            needed = importer_module._PLATFORM[provider][2]
            if needed:
                self.assertIn(needed, grant["scopes"])
            self.assertFalse(set(grant["scopes"]) & {"threads_content_publish", "instagram_business_content_publish", "write", "write:statuses"})
            self.assertEqual(identity["providerAccountId"], self.F.ACCOUNTS[provider][0])
            self.assertEqual(self.grant(provider, "good-code-2")[1]["providerAccountId"], self.F.ACCOUNTS[provider][1])
        self.assertEqual(self.grant("threads")[1]["providerAccountId"], "17841400000000")   # the harness's own Threads dev identity
        bluesky = json.loads(self.grant("bluesky")[0]["accessToken"])
        self.assertEqual((bluesky["did"], bluesky["pds"]), (self.F.ACCOUNTS["bluesky"][0], "https://pds.example.com"))
        self.assertIsNone(self.grant("mastodon")[0]["expiresIn"])               # never refreshed into a plain string

    def test_nothing_leaves_the_machine(self):
        transport = self.F.HistoryTransport()
        for url in ("https://graph.threads.net/v24.0/me/insights", "https://example.org/", "https://graph.instagram.com/v24.0/me"):
            self.assertEqual(transport("GET", url)["status"], 404)
        self.assertEqual(transport("POST", "https://graph.threads.net/v24.0/me/threads")["status"], 404)
        self.assertTrue(self.F.resolve("pds.example.com", 443, type=1))
        with self.assertRaises(OSError):
            self.F.resolve("mastodon.social", 443, type=1)

    def test_mount_applies_migration_140_on_loopback_only_and_switches_the_feature_on(self):
        class Db:
            def __init__(self, host):
                self.info, self.sql = SimpleNamespace(host=host), []

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                self.sql.append(sql)
        local = Db("127.0.0.1")
        service = SimpleNamespace(oauth=SimpleNamespace(providers={}))
        made = self.F.mount(service, lambda: local)
        self.assertIs(service.voice_import, made)
        self.assertIs(service.oauth.voice_import, made)
        self.assertIs(made.resolver, self.F.resolve)
        self.assertIsInstance(made.transport, self.F.HistoryTransport)
        self.assertEqual(made.providers, frozenset({"threads", "instagram", "bluesky", "mastodon"}))
        self.assertIn("create table if not exists public.pr_voice_posts", local.sql[0])
        with self.assertRaises(RuntimeError):
            self.F.mount(SimpleNamespace(oauth=SimpleNamespace(providers={})), lambda: Db("db.example.com"))


if __name__ == "__main__":
    unittest.main()
