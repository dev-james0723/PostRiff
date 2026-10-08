"""T11 — quiet suggestions and descriptive usage feedback (acceptance A054–A058; PRD R14, R15, D6).

`SuggDB` extends the organization suite's in-memory database with the tagged statements of suggestions.py and usage.py
(and insights.latest_observations). It proves logic only; real SQL is covered by
tests/phase2/postgres_library_intelligence_suggestions.py in cloud CI. Library search is replaced by a recorded fake in
these unit tests (the PG suite uses the real search); ranking, caps, dedup, debounce and wording are the real code.
"""
import copy
import json
import os
import re
import unittest
import uuid
from pathlib import Path
from unittest import mock

from library_intelligence_fakes import ACTOR, WS
from postriff_alpha.domain import AlphaError
from postriff_phase2.library_intelligence import actions, collections, relations, suggestions, usage, versions
from test_library_intelligence_organization import OrgDB, context, envelope, k, ref

FLAGS = {"RAFII_LIBRARY_SUGGESTIONS_ENABLED": "1", "RAFII_LIBRARY_RETRIEVAL_ENABLED": "1"}
EDITOR = "00000000-0000-0000-0000-0000000000e2"
STRANGER = "00000000-0000-0000-0000-0000000000f9"
DAY = 86400.0
A, B, C2, D2 = k(0x5A1), k(0x5B1), k(0x5C1), k(0x5D1)
FAILED = [k(0xFA0 + n) for n in range(5)]
CAUSAL = re.compile(r"\b(caused?|causes|causing|drove|driven by|led to|leads to|resulted in|results in|thanks to|boost(ed|s)?|because of (this|the) "
                    r"(asset|item|image|photo|file)|made (the|this|your) post)\b", re.I)


class SuggDB(OrgDB):
    def __init__(self):
        super().__init__()
        self.workspace_members = [ACTOR, EDITOR]
        self.prefs = {}
        self.metrics = []
        self.observations = []
        self.usage_rows = []
        self.fail_on = None

    # --- coordinator statements used by usage (insights.latest_observations) -------------------------------------------
    def _coordinator(self, sql, args):
        if "FROM pg_attribute WHERE attrelid='public.pr_metric_observations'" in sql:
            return []
        if "FROM public.pr_metric_observations o WHERE workspace_id=%s" in sql:
            return [(o["provider"], o["post"], o["job"], o["metric"], "v1", o["value"], "count", o["availability"], o["observed"], o["observed"] + 5,
                     "conn-1", None) for o in self.observations]
        return super()._coordinator(sql, args)

    # --- suggestions ------------------------------------------------------------------------------------------------------
    def _sugg_debounce(self, target, seconds):
        return any(m["target"] == target and m["at"] > self.now - seconds for m in self.metrics)

    def _sugg_recent(self, args):
        return [(1,)] if self._sugg_debounce(args[1], args[2]) else []

    def _sugg_stamp(self, args):
        self.metrics.append({"target": json.loads(args[2])["target"], "at": self.now})
        return []

    def _sugg_history(self, args):
        return [(copy.deepcopy(s["candidates"]), s["created"], s["state"]) for s in self.suggestions
                if s["recipient"] == args[1] and s["category"] == "unused_relevant" and s["created"] > self.now - args[2] * DAY]

    def _row(self, s):
        return (s["id"], s["category"], s["critical"], copy.deepcopy(s["trigger"]), copy.deepcopy(s["candidates"]), copy.deepcopy(s["affected"]),
                s["reason"], s["state"], s["snooze"], s["created"], s["expires"])

    def _visible(self, s):
        return (s["state"] in ("new", "seen") or (s["state"] == "snoozed" and s["snooze"] <= self.now)) and (s["expires"] is None or s["expires"] > self.now)

    def _sugg_inbox(self, args):
        rows = [s for s in self.suggestions if s["recipient"] == args[1] and self._visible(s)]
        rows.sort(key=lambda s: (not s["critical"], -s["created"]))
        return [self._row(s) for s in rows[:args[2]]]

    def _find(self, sid):
        return next((s for s in self.suggestions if s["id"] == sid), None)

    def _sugg_get(self, args):
        s = self._find(args[1].hex)
        return [self._row(s) + (s["recipient"],)] if s and s["recipient"] == args[2] else []

    def _sugg_set(self, args):
        s = self._find(args[2].hex)
        s.update(state=args[0], snooze=None)
        return [(s["state"], None)]

    def _sugg_snooze(self, args):
        s = self._find(args[2].hex)
        s.update(state="snoozed", snooze=self.now + args[0] * DAY)
        return [(s["state"], s["snooze"])]

    def _sugg_pref_put(self, args):
        _, recipient, category, disabled, snooze_days, _, _ = args
        row = self.prefs.setdefault((recipient, category), {"disabled": False, "snooze_days": 7, "external_opt_in": False})
        if disabled is not None:
            row["disabled"] = disabled
        if snooze_days is not None:
            row["snooze_days"] = snooze_days
        return [(row["disabled"], row["snooze_days"], row["external_opt_in"])]

    def _sugg_suppress_category(self, args):
        for s in self.suggestions:
            if s["recipient"] == args[1] and s["category"] == args[2] and s["state"] in ("new", "seen", "snoozed") and not s["critical"]:
                s["state"] = "suppressed"
        return []

    def _sugg_failed(self, args):
        return [(key, cap, "library_processing_failed") for (key, cap), state in self.caps.items() if state == "failed"][:args[1]]

    def _sugg_capability(self, args):
        state = self.caps.get((args[1], args[2]))
        return [(state, "library_processing_failed")] if state else []

    def _sugg_stale(self, args):
        return [(r["from_version"], r["to_kind"], r["to_key"], copy.deepcopy(r["evidence"])) for r in self.relations
                if r["relation"] == "used_in" and r["status"] == "stale"][:args[1]]

    def _sugg_open(self, args):
        return [(s["id"], copy.deepcopy(s["candidates"])) for s in self.suggestions if s["state"] in ("new", "seen", "snoozed")][:args[1]]

    def _sugg_suppress(self, args):
        ids = {uuid.UUID(str(x)).hex for x in args[1]}
        for s in self.suggestions:
            if s["id"] in ids:
                s["state"] = "suppressed"
        return []

    def _sugg_expire(self, args):
        for s in self.suggestions:
            if s["state"] in ("new", "seen", "snoozed") and s["expires"] is not None and s["expires"] <= self.now:
                s["state"] = "expired"
        return []

    def _sugg_tags(self, args):
        counts = {}
        for a in self.assets.values():
            if a["status"] in ("ready", "unsupported"):
                for t in a["tags"]:
                    counts[t] = counts.get(t, 0) + 1
        rows = sorted(((t, n) for t, n in counts.items() if n >= args[1]), key=lambda x: (-x[1], x[0]))
        return rows[:args[2]]

    def _sugg_collections(self, args):
        return [(x["name"],) for x in self.collections.values()]

    def _sugg_due(self, args):
        return [] if self._sugg_debounce(args[0], args[1]) else [(WS,)]

    # --- usage --------------------------------------------------------------------------------------------------------------
    def _usage_put(self, args):
        row = dict(zip(("id", "ws", "asset", "version", "segment", "type", "draft", "post", "channel", "dedup", "source", "metrics", "metrics_at"), args))
        if any(u["dedup"] == row["dedup"] for u in self.usage_rows):
            return []
        row["at"] = self.now
        self.usage_rows.append(row)
        self.usage.append((row["asset"], row["version"]))
        return [(str(row["id"]),)]

    def _usage_list(self, args):
        akeys, vkeys = set(args[1]), set(args[2])
        rows = [u for u in self.usage_rows if u["asset"] in akeys or u["version"] in vkeys]
        return [(u["type"], u["asset"], u["version"], u["segment"], u["draft"], u["post"], u["channel"], json.loads(u["source"]),
                 json.loads(u["metrics"]) if u["metrics"] else None, u["metrics_at"], u["at"]) for u in rows][:args[3]]

    def _usage_cited(self, args):
        keys = set(args[1])
        return [(r["from_version"], r["from_segment"], r["to_kind"], r["to_key"], r["status"]) for r in self.relations
                if r["relation"] == "used_in" and r["from_version"] in keys][:args[2]]


class FakeSearch:
    """Records calls; returns hits for each query term from a tiny index of {term: [version keys]}."""

    def __init__(self, db, index):
        self.db, self.index, self.calls = db, index, []

    def __call__(self, ctx, request):
        self.calls.append(request)
        assert request["purpose"] == "browse" and request["filters"].get("usage") == "unused" and request["modes"] == ["lexical"], request
        keys = [key for key in self.index.get(request["query"].lower(), []) if key not in {u[0] for u in self.db.usage} | {u[1] for u in self.db.usage}]
        return {"hits": [{"assetRef": ref(self.db, key), "displayTitle": self.db.assets[key]["title"] or "Untitled", "kind": self.db.assets[key]["kind"],
                          "matchReasons": [{"kind": "lexical", "detail": "passage"}], "createdAt": self.db.assets[key]["created"]} for key in keys]}


def draft(did, text, source_ids=(), platform="instagram"):
    return {"id": did, "platform": platform, "language": "en", "text": text, "sourceIds": list(source_ids), "revision": 1,
            "revisions": [{"revision": 1, "at": 1_789_000_000.0}]}


def source(sid, *, approved=False, active=True, asset=None):
    return {"id": sid, "kind": "document", "title": f"Source {sid}", "active": active, "sourcePolicy": "rewrite_approval", "egressConsent": ["local"],
            "useApprovals": [], "facts": [{"id": "f1", "text": "A fact", "approved": approved}],
            "origin": {"kind": "library", "assetId": asset, "sha256": None} if asset else {"kind": "text"}, "createdAt": 1789600000.0}


def mine(db, recipient=ACTOR):
    return [s for s in db.suggestions if s["recipient"] == recipient]


class Base(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, FLAGS)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db = SuggDB()
        self.db.add(A, kind="image", title="Brahms poster", tags=["concert"])
        self.db.add(B, kind="image", title="Hall photo", tags=["concert"])
        self.ctx = context(self.db)
        self.search = FakeSearch(self.db, {"concert": [A, B], "brahms": [A]})
        patcher = mock.patch.object(suggestions, "_search", self.search)
        patcher.start()
        self.addCleanup(patcher.stop)

    def evaluate(self, event, ctx=None):
        return suggestions.evaluate_suggestions(ctx or self.ctx, event)


# ======================================================================================================================
class Suggestions(Base):
    def test_digest_three_noncritical_per_day(self):
        db = self.db
        for key in FAILED:
            db.add(key, kind="document", title=f"Report {key[-3:]}")
            db.caps[(key, "extract")] = "failed"
        created = self.evaluate({"type": "sweep"})
        self.assertEqual(len([s for s in mine(db) if not s["critical"]]), 3, "at most three new noncritical suggestions per day")
        self.assertTrue(all(s["reason"] and s["affected"] for s in mine(db)), "every suggestion has a reason and the affected work")
        self.assertEqual({s["category"] for s in mine(db)}, {"failed_processing"})
        self.assertTrue(all("original file is safe" in s["reason"] for s in mine(db)))
        self.assertEqual(len(created), 6, "three for each of the two editors")
        inbox = suggestions.inbox_http(self.ctx, {"params": {}, "query": {}, "body": {}})
        self.assertEqual(inbox["cap"], {"noncriticalPerDay": 3, "shownToday": 3})
        self.assertEqual(len(inbox["suggestions"]), 3)
        # A critical source-integrity warning bypasses the cap but is still deduplicated.
        warning = {"type": "source_integrity", "assetKey": A, "affected": [{"kind": "draft", "key": "draft-9"}]}
        self.assertEqual(len(self.evaluate(warning)), 2)
        self.assertEqual(len(self.evaluate(warning)), 0)
        self.assertEqual(sum(1 for s in mine(db) if s["critical"]), 1)
        self.assertEqual(suggestions.inbox_http(self.ctx, {"params": {}, "query": {}, "body": {}})["suggestions"][0]["critical"], True)
        # Deferred suggestions come back on a later day; nothing is lost and nothing is repeated.
        db.now += DAY + 1
        db.metrics.clear()
        self.evaluate({"type": "sweep"})
        failed = [s for s in mine(db) if s["category"] == "failed_processing"]
        self.assertEqual(len(failed), 5)
        self.assertEqual(len({s["dedup"] for s in failed}), 5)

    def test_event_replay_dedup(self):
        db = self.db
        db.state["sources"].append(source("src-1"))
        db.state["variants"].append(draft("draft-1", "Brahms recital this Saturday #concert", ["src-1"]))
        first = self.evaluate({"type": "draft_changed", "draftId": "draft-1"})
        self.assertEqual({x["category"] for x in first}, {"missing_input", "unused_relevant"})
        self.assertEqual({x["category"] for x in mine(db)}, {"missing_input", "unused_relevant"}, "the editing member is the recipient")
        calls = len(self.search.calls)
        self.assertEqual(self.evaluate({"type": "draft_changed", "draftId": "draft-1"}), [], "a burst is debounced")
        self.assertEqual(len(self.search.calls), calls, "a debounced replay runs no search")
        db.now += suggestions.DEBOUNCE_SECONDS + 1
        self.assertEqual(self.evaluate({"type": "draft_changed", "draftId": "draft-1"}), [], "a later replay is deduplicated")
        self.assertGreater(len(self.search.calls), calls)
        self.assertEqual(len(mine(db)), 2, "the same draft revision keeps one suggestion per identity, whatever ranks first now")
        self.assertEqual(len(db.suggestions), len({(x["recipient"], x["dedup"]) for x in db.suggestions}))
        old, new = self.db.add(C2, kind="document", title="Notes"), self.db.add(D2, kind="document", title="Notes v2", lineage=C2, version_no=2)
        event = {"type": "version_linked", "old": ref(db, old), "new": ref(db, new), "affected": [{"kind": "draft", "key": "draft-1"}]}
        self.assertEqual(len(self.evaluate(event)), 1)
        self.assertEqual(len(self.evaluate(event)), 0, "an explicit event replay is deduplicated too")
        with self.assertRaises(AlphaError):
            self.evaluate({"type": "send_email", "to": "x"})

    def test_dismiss_and_snooze_persist(self):
        db = self.db
        db.state["variants"].append(draft("draft-1", "Brahms recital #concert"))
        self.evaluate({"type": "draft_changed", "draftId": "draft-1"})
        target = next(s for s in mine(db) if s["category"] == "unused_relevant")
        dismissed = actions.apply(self.ctx, envelope("suggestion.set_state", payload={"suggestionId": target["id"], "action": "dismiss"}))
        self.assertEqual((dismissed["status"], target["state"]), ("applied", "dismissed"))
        db.now += suggestions.DEBOUNCE_SECONDS + 1
        self.evaluate({"type": "draft_changed", "draftId": "draft-1"})
        self.assertEqual(sum(1 for s in mine(db) if s["dedup"] == target["dedup"]), 1, "a dismissed identity is never recreated")
        fresh = context(db)  # a new request/session reads the persisted state
        self.assertNotIn(target["id"], [s["id"] for s in suggestions.inbox_http(fresh, {"params": {}, "query": {}, "body": {}})["suggestions"]])
        # Snooze: 7-day default, editable default in preferences, and a per-action override.
        warning = self.evaluate({"type": "source_integrity", "assetKey": A, "affected": [{"kind": "draft", "key": "draft-1"}]})
        mine_warning = next(s for s in mine(db) if s["critical"])
        suggestions.set_suggestion_state(self.ctx, mine_warning["id"], "snooze")
        self.assertAlmostEqual(mine_warning["snooze"], db.now + 7 * DAY)
        suggestions.set_suggestion_state(self.ctx, None, "preferences", category="source_integrity", snooze_days=3)
        suggestions.set_suggestion_state(self.ctx, mine_warning["id"], "snooze")
        self.assertAlmostEqual(mine_warning["snooze"], db.now + 3 * DAY)
        out = actions.apply(self.ctx, envelope("suggestion.set_state", payload={"suggestionId": mine_warning["id"], "action": "snooze", "snoozeDays": 14}))
        self.assertEqual(out["status"], "applied")
        self.assertAlmostEqual(mine_warning["snooze"], db.now + 14 * DAY)
        visible = lambda: [s["id"] for s in suggestions.inbox_http(context(db), {"params": {}, "query": {}, "body": {}})["suggestions"]]  # noqa: E731
        self.assertNotIn(mine_warning["id"], visible())
        db.now += 15 * DAY
        self.assertIn(mine_warning["id"], visible(), "a snoozed suggestion returns after the snooze")
        # Only the recipient may change a suggestion; others get the same answer as a missing one.
        other = context(db, actor=EDITOR)
        denied = actions.apply(other, envelope("suggestion.set_state", payload={"suggestionId": mine_warning["id"], "action": "dismiss"}))
        self.assertEqual(denied["status"], "denied")
        self.assertEqual(mine_warning["state"], "snoozed")
        for bad in ({"suggestionId": mine_warning["id"], "action": "snooze", "snoozeDays": 0}, {"suggestionId": mine_warning["id"], "action": "explode"}):
            with self.assertRaises(AlphaError):
                actions.apply(self.ctx, envelope("suggestion.set_state", payload=bad))
        self.assertTrue(warning)

    def test_category_disable(self):
        db = self.db
        db.state["sources"].append(source("src-1"))
        db.state["variants"].append(draft("draft-1", "Brahms recital #concert", ["src-1"]))
        self.evaluate({"type": "draft_changed", "draftId": "draft-1"})
        unused = next(s for s in mine(db) if s["category"] == "unused_relevant")
        out = actions.apply(self.ctx, envelope("suggestion.set_state", payload={"suggestionId": unused["id"], "action": "disable_category"}))
        self.assertEqual(out["status"], "applied")
        self.assertTrue(db.prefs[(ACTOR, "unused_relevant")]["disabled"], "the preference persists")
        self.assertEqual(unused["state"], "suppressed")
        db.state["variants"].append(draft("draft-2", "Hall photo #concert"))
        self.evaluate({"type": "draft_changed", "draftId": "draft-2"})
        self.evaluate({"type": "draft_changed", "draftId": "draft-2"}, context(db, actor=EDITOR))
        self.assertEqual([s for s in mine(db) if s["category"] == "unused_relevant" and s["state"] == "new"], [])
        self.assertTrue([s for s in mine(db, EDITOR) if s["category"] == "unused_relevant"], "another member's preference is separate")
        self.assertTrue(any(s["category"] == "missing_input" for s in mine(db)), "other categories still arrive")
        inbox = suggestions.inbox_http(context(db), {"params": {}, "query": {}, "body": {}})
        self.assertTrue(inbox["preferences"]["unused_relevant"]["disabled"])
        with self.assertRaises(AlphaError) as safety:
            suggestions.set_suggestion_state(self.ctx, None, "disable_category", category="permission")
        self.assertEqual(safety.exception.status, 400)
        suggestions.set_suggestion_state(self.ctx, None, "enable_category", category="unused_relevant")
        self.assertFalse(db.prefs[(ACTOR, "unused_relevant")]["disabled"])

    def test_external_opt_in_required(self):
        db = self.db
        db.prefs[(ACTOR, "failed_processing")] = {"disabled": False, "snooze_days": 7, "external_opt_in": True}
        db.add(FAILED[0], kind="document", title="Report")
        db.caps[(FAILED[0], "extract")] = "failed"
        imported = set()
        real_import = __import__

        def watch(name, *args, **kwargs):
            imported.add(name)
            return real_import(name, *args, **kwargs)
        with mock.patch("builtins.__import__", side_effect=watch):
            self.evaluate({"type": "sweep"})
            suggestions.inbox_http(self.ctx, {"params": {}, "query": {}, "body": {}})
        self.assertTrue(mine(db), "the suggestion is delivered in-app")
        outbound = r"(?i)(notification|email|push|sms|schedule|campaign|publish|webhook|pr_jobs\b|queue)"
        self.assertFalse([s for s, _ in db.executed if re.search(outbound, s)], "no outbound, scheduling or publishing statement")
        self.assertFalse([n for n in imported if re.search(r"(notifications|email|publisher|campaign|social|phone)", n)])
        source_text = "\n".join(Path(m.__file__).read_text() for m in (suggestions, usage))
        self.assertFalse(re.search(r"^\s*(from|import)\s+\S*(notifications|email|publisher|campaigns|hosted_social|phone)", source_text, re.M))
        inbox = suggestions.inbox_http(self.ctx, {"params": {}, "query": {}, "body": {}})
        self.assertEqual(inbox["delivery"]["channels"], ["in_app"])
        self.assertFalse(inbox["delivery"]["external"], "an opt-in flag alone sends nothing: no external channel exists here")

    def test_diversity_avoids_repeated_winner(self):
        now = 1_790_000_000.0
        candidates = [{"key": A, "positions": [0, 0], "kind": "image", "createdAt": now - 10},
                      {"key": B, "positions": [1], "kind": "image", "createdAt": now - 20},
                      {"key": C2, "positions": [2], "kind": "video", "createdAt": now - 30}]
        self.assertEqual(suggestions.rank_candidates(candidates, {}, now)[0]["key"], A)
        recent = {A: {"count": 1, "lastAt": now - 3600}}
        self.assertNotEqual(suggestions.rank_candidates(candidates, recent, now)[0]["key"], A, "a just-surfaced winner yields")
        old = {A: {"count": 1, "lastAt": now - 90 * DAY}}
        self.assertEqual(suggestions.rank_candidates(candidates, old, now)[0]["key"], A, "the penalty fades with time")
        picked = [c["key"] for c in suggestions.rank_candidates(candidates, {}, now, limit=2)]
        self.assertEqual(picked, [A, C2], "a second pick prefers a different kind over a near-duplicate kind")
        # End to end: two drafts that both match the same top asset do not get it twice.
        db = self.db
        db.state["variants"] += [draft("draft-1", "Brahms recital #concert"), draft("draft-2", "Brahms encore #concert")]
        self.evaluate({"type": "draft_changed", "draftId": "draft-1"})
        db.now += 3600
        self.evaluate({"type": "draft_changed", "draftId": "draft-2"})
        winners = [s["candidates"][0]["versionId"] for s in mine(db) if s["category"] == "unused_relevant"]
        self.assertEqual(winners, [A, B])
        why = next(s for s in mine(db) if s["category"] == "unused_relevant")["trigger"]["why"]
        self.assertTrue(why["matchedTerms"] and why["method"] == "lexical", "the reason for a recommendation is exposed")

    def test_draft_terms_and_times(self):
        self.assertEqual(suggestions.draft_terms("Brahms recital this Saturday! #concert 週末演奏會 tickets"), ["concert", "Brahms", "週末演奏"])
        self.assertEqual(suggestions.draft_terms("the and of #a"), [], "stopwords and one-letter tags are not search terms")
        self.assertNotIn("https", " ".join(suggestions.draft_terms("Visit https://example.com today #https://x")))
        self.assertEqual(suggestions._epoch("2026-10-01T00:00:00+00:00"), 1790812800.0, "domain drafts store ISO times")
        self.assertEqual(suggestions._epoch(1790812800), 1790812800.0)
        self.assertEqual(suggestions._epoch("not a time"), 0.0)

    def test_item_cited_by_a_draft_counts_as_used(self):
        db = self.db
        db.state["sources"].append(source("src-a", asset=A, approved=True))
        db.state["variants"] += [draft("draft-1", "Brahms notes", ["src-a"]), draft("draft-2", "Brahms recital #concert")]
        self.evaluate({"type": "draft_changed", "draftId": "draft-2"})
        picks = [s["candidates"][0]["versionId"] for s in mine(db) if s["category"] == "unused_relevant"]
        self.assertEqual(picks, [B], "an item another draft already cites is not recommended as unused")

    def test_revoked_or_deleted_suppressed(self):
        db = self.db
        db.state["variants"].append(draft("draft-1", "Brahms recital #concert"))
        self.evaluate({"type": "draft_changed", "draftId": "draft-1"})
        suggestion = next(s for s in mine(db) if s["category"] == "unused_relevant")
        db.assets[A]["status"] = "deleting"
        self.assertNotIn(suggestion["id"], [s["id"] for s in suggestions.inbox_http(context(db), {"params": {}, "query": {}, "body": {}})["suggestions"]])
        db.now += 2 * DAY
        db.metrics.clear()
        self.evaluate({"type": "sweep"})
        self.assertEqual(suggestion["state"], "suppressed")

    def test_outdated_source_through_relations(self):
        db = self.db
        db.add(C2, kind="document", title="Programme")
        db.add(D2, kind="document", title="Programme v2")
        db.state["sources"].append(source("src-old", asset=C2))
        db.state["variants"].append(draft("draft-1", "Concert text", ["src-old"]))
        with mock.patch.dict(os.environ, {"RAFII_LIBRARY_SUGGESTIONS_ENABLED": ""}):
            linked = relations.link_versions(self.ctx, {"relation": "version_of", "from": ref(db, D2), "to": ref(db, C2)})
        outdated = [s for s in db.suggestions if s["category"] == "outdated_source"]
        self.assertEqual(len(outdated), 1, "one warning per recipient for the whole link, even with proactive suggestions off")
        self.assertEqual({(a["kind"], a["key"]) for a in outdated[0]["affected"]}, {("idea", "src-old"), ("draft", "draft-1")})
        self.assertEqual(linked["flagged"]["suggestions"], 1)
        self.assertIn("cite version 1", outdated[0]["reason"])
        # The periodic pass re-derives the warning for the other editor from the stale relations, without duplicating it.
        db.metrics.clear()
        self.evaluate({"type": "sweep"})
        self.assertEqual(sorted(s["recipient"] for s in db.suggestions if s["category"] == "outdated_source"), sorted([ACTOR, EDITOR]))

    def test_apply_organization_proposal(self):
        db = self.db
        for n in range(3):
            db.add(k(0x7700 + n), kind="audio", tags=["rehearsal"])
        self.evaluate({"type": "sweep"})
        proposal = next(s for s in mine(db) if s["category"] == "organization")
        self.assertIn("Nothing changes until you apply it", proposal["reason"])
        viewer = context(db, role="viewer")
        self.assertEqual(actions.apply(viewer, envelope("suggestion.set_state", payload={"suggestionId": proposal["id"], "action": "apply"}))["status"],
                         "denied")
        applied = actions.apply(self.ctx, envelope("suggestion.set_state", payload={"suggestionId": proposal["id"], "action": "apply"}))
        self.assertEqual(applied["status"], "applied", applied)
        self.assertEqual(proposal["state"], "applied")
        created = next(x for x in db.collections.values() if x["kind"] == "smart")
        self.assertEqual(len(db.members(next(cid for cid, x in db.collections.items() if x is created))), 3)

    def test_evaluate_due_never_raises(self):
        db = self.db
        with mock.patch.dict(os.environ, {"RAFII_LIBRARY_SUGGESTIONS_ENABLED": ""}):
            self.assertEqual(suggestions.evaluate_due(None, db.connect)["status"], "disabled")
            self.assertEqual(self.evaluate({"type": "sweep"}), [], "proactive triggers are off with the flag")
        db.add(FAILED[0], kind="document")
        db.caps[(FAILED[0], "extract")] = "failed"
        summary = suggestions.evaluate_due(None, db.connect)
        self.assertEqual((summary["status"], summary["workspaces"]), ("ok", 1), summary)
        self.assertTrue(mine(db))
        self.assertEqual(suggestions.evaluate_due(None, db.connect)["workspaces"], 0, "a swept workspace waits for the next interval")
        db.fail_on = "lio:sugg.due"
        self.assertEqual(suggestions.evaluate_due(None, db.connect)["status"], "error")
        db.fail_on = None
        db.metrics.clear()
        db.fail_on = "lio:sugg.failed"
        self.assertEqual(suggestions.evaluate_due(None, db.connect)["errors"], 1)


# ======================================================================================================================
class Usage(Base):
    def setUp(self):
        super().setUp()
        db = self.db
        db.state["phase2"]["assets"].append({"id": X_LEGACY, "mime": "image/jpeg", "hash": "a" * 64, "createdAt": 1.0})
        db.state["phase2"]["jobs"] = [
            {"id": "job-1", "state": "published", "providerReference": "ig-post-1", "createdAt": 1_789_500_000.0,
             "manifest": {"platform": "instagram", "account": "studio", "media": [{"id": X_LEGACY}], "idempotencyKey": "m-1"}},
            {"id": "job-2", "state": "scheduled", "createdAt": 1_789_600_000.0,
             "manifest": {"platform": "threads", "account": "studio", "media": [{"id": X_LEGACY}], "idempotencyKey": "m-2"}}]
        db.observations = [{"provider": "instagram", "post": "ig-post-1", "job": "job-1", "metric": "likes", "value": None, "availability": "unavailable",
                            "observed": 1_789_700_000.0},
                           {"provider": "instagram", "post": "ig-post-1", "job": "job-1", "metric": "views", "value": 0, "availability": "available",
                            "observed": 1_789_700_000.0}]

    def test_metrics_unknown_not_zero(self):
        out = usage.asset_usage(self.ctx, {"assetId": X_LEGACY, "versionId": X_LEGACY, "sha256": ""})
        posts = {u.get("jobId"): u for u in out["uses"] if u["source"] == "post_job"}
        self.assertEqual(set(posts), {"job-1", "job-2"})
        likes, views = posts["job-1"]["metrics"]["likes"], posts["job-1"]["metrics"]["views"]
        self.assertEqual((likes["value"], likes["display"], likes["availability"]), (None, "unknown", "unavailable"))
        self.assertEqual((views["value"], views["display"]), (0, "0"), "a real recorded zero stays zero")
        self.assertEqual(likes["observedAt"], 1_789_700_000.0, "metric source time is shown")
        self.assertIsNone(posts["job-2"]["metrics"], "no observations: unknown, never zero")
        self.assertEqual(posts["job-2"]["metricsStatus"], "unknown")
        self.assertEqual(out["summary"]["metricsStatus"], "partial")
        self.assertEqual(out["summary"]["channels"], ["instagram", "threads"])

    def test_no_causal_claim(self):
        db = self.db
        db.state["sources"].append(source("src-1", asset=A))
        db.state["variants"].append(draft("draft-1", "Concert post", ["src-1"]))
        usage.record_usage(db, WS, A, A, "post_published", post_id="post-77", channel="instagram", dedup_key="publish:post-77:" + A, source={"path": "publish"})
        texts = [json.dumps(usage.asset_usage(self.ctx, ref(db, A)), ensure_ascii=False),
                 json.dumps(usage.asset_usage(self.ctx, {"assetId": X_LEGACY, "versionId": X_LEGACY, "sha256": ""}), ensure_ascii=False)]
        db.state["variants"].append(draft("draft-2", "Brahms recital #concert"))
        self.evaluate({"type": "draft_changed", "draftId": "draft-2"})
        texts += [s["reason"] for s in db.suggestions]
        for text in texts:
            self.assertIsNone(CAUSAL.search(text), text)
        note = usage.asset_usage(self.ctx, ref(db, A))["note"]
        self.assertIn("correlation", note)
        self.assertIn("not causation", note)

    def test_usage_traces_are_real(self):
        db = self.db
        db.state["sources"].append(source("src-1", asset=A))
        db.state["variants"].append(draft("draft-1", "Concert post", ["src-1"], platform="threads"))
        first = usage.record_usage(db, WS, A, A, "draft_attached", draft_id="draft-1", dedup_key="attach:draft-1:" + A, source={"pack": "p1"})
        again = usage.record_usage(db, WS, A, A, "draft_attached", draft_id="draft-1", dedup_key="attach:draft-1:" + A, source={"pack": "p1"})
        self.assertEqual((first["recorded"], again["recorded"]), (True, False), "idempotent by dedup key")
        self.assertEqual(usage.record_usage(db, WS, k(0xFEED), k(0xFEED), "downloaded", dedup_key="dl:feed:000001", source={})["recorded"], False,
                         "a key outside this workspace is never recorded")
        with self.assertRaises(AlphaError):
            usage.record_usage(db, WS, A, A, "went_viral", dedup_key="bad:event:0001", source={})
        out = usage.usage_http(self.ctx, {"params": {"key": A}, "query": {}, "body": {}})
        kinds = {(u["source"], u.get("draftId")) for u in out["uses"]}
        self.assertIn(("library_event", "draft-1"), kinds)
        self.assertIn(("ideas_draft", "draft-1"), kinds)
        event = next(u for u in out["uses"] if u["source"] == "library_event")
        self.assertEqual(event["version"]["versionId"], A)
        self.assertIsNone(event["metrics"])
        self.assertEqual(event["metricsStatus"], "unknown")
        with self.assertRaises(AlphaError) as foreign:
            usage.usage_http(self.ctx, {"params": {"key": k(0xFEED)}, "query": {}, "body": {}})
        self.assertEqual(foreign.exception.status, 404)


X_LEGACY = k(0x1E6)

if __name__ == "__main__":
    unittest.main()
