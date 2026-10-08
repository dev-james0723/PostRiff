"""T08 — task source packs, attaching to real Ideas drafts and final-artifact return (R12, R13; A049–A053).

Real logic on in-memory state: policy.authorize_source/recheck, the canonical voice system and voice.style_exemplars, the
hosted command router's domain `source` action (Ideas fact review), D's relations.record_used_in and usage.record_usage,
and the artifact registration rules. C's search_library is replaced by a small term matcher that keeps only items the
real policy allows for the requested purpose; real search SQL runs in tests/phase2/postgres_library_intelligence_creation.py.
"""
import copy
import hashlib
import json
import os
import re
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from library_intelligence_fakes import ACTOR, WS
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.library_intelligence import actions, api, artifacts, contracts as c, policy, search, source_packs, versions, voice
from postriff_phase2.permissions import Membership
from test_library_intelligence_voice import NOW, USES, WROTE, VoiceCursor, VoiceDB

ENV = {"RAFII_LIBRARY_VOICE_ENABLED": "1", "RAFII_LIBRARY_RETRIEVAL_ENABLED": "1", "RAFII_LIBRARY_TASK_UI_ENABLED": "1", "RAFII_LIBRARY_ARTIFACTS_ENABLED": "1"}
DOC, USED, REVIEW, NOTE, OLD, NEW, PHOTO, POSTER_VIDEO = ("a1" * 16, "a2" * 16, "a3" * 16, "b1" * 16, "c1" * 16, "c2" * 16, "d1" * 16, "d2" * 16)
RUN, OTHER_RUN, FAILED_RUN = "11111111-2222-4333-8444-555555555555", "11111111-2222-4333-8444-666666666666", "11111111-2222-4333-8444-777777777777"
NOTE_TEXT = "I practise Brahms slowly before every recital."
DRAFT_TEXT = "Join me for an evening of Brahms at City Hall."


def source(sid, facts, *, policy_name="rewrite_approval", egress=("local", "cloud"), active=True, use_approved=False):
    out = {"id": sid, "kind": "text", "title": sid, "text": " ".join(f for f, _ in facts), "active": active, "sourcePolicy": policy_name,
           "egressConsent": list(egress), "useApprovals": [], "fingerprint": "fp-" + sid, "createdAt": NOW, "visibility": "private-local",
           "facts": [{"id": f"{sid}-{n}", "text": text, "approved": ok, "sourceId": sid} for n, (text, ok) in enumerate(facts)]}
    if use_approved:
        from postriff_phase2.source_policy import facts_digest
        out["useApprovals"] = [{"actor": ACTOR, "at": NOW, "factsDigest": facts_digest(out)}]
    return out


class Storage:
    def __init__(self):
        self.objects = {}

    def put_immutable(self, ws, category, name, raw, content_type="application/octet-stream"):
        if (ws, category, name) in self.objects:
            raise AlphaError("This immutable object already exists.", 409)
        self.objects[(ws, category, name)] = (raw, content_type)
        return f"{ws}/{category}/{name}"

    def object_info(self, ws, category, name):
        if (ws, category, name) not in self.objects:
            raise AlphaError("missing", 404)
        raw, mime = self.objects[(ws, category, name)]
        return {"bytes": len(raw), "mime": mime, "etag": hashlib.sha256(raw).hexdigest()[:24]}

    def get_bounded(self, ws, category, name, limit):
        return self.get(ws, category, name)

    def get(self, ws, category, name):
        if (ws, category, name) not in self.objects:
            raise AlphaError("missing", 404)
        return self.objects[(ws, category, name)][0]


class CreationDB(VoiceDB):
    def __init__(self):
        super().__init__()
        self.packs, self.relations, self.usage, self.artifacts, self.runs = {}, [], [], [], {}
        self.inserted_assets = []
        self.storage = Storage()

    def asset(self, key, *, source_id=None, lineage=None, version_no=1, created=1.0, object_name=None, **kw):
        ref = super().asset(key, **kw)
        self.assets[key].update(sourceId=source_id, lineage=lineage, versionNo=version_no, created=created, objectName=object_name or f"{key}.md")
        return ref

    def row(self, key):
        a = self.assets[key]
        mime = {"image": "image/jpeg", "video": "video/mp4"}.get(a["kind"], "text/markdown")
        return (uuid.UUID(hex=key), uuid.UUID(hex=a["lineage"]) if a.get("lineage") else None, a.get("versionNo", 1), WS, a["title"] + ".md", a["title"],
                "filename", None, [], a["kind"], mime, mime.split("/")[-1], 100, a["sha"], a["status"], "ready", "ready", "not_applicable",
                a.get("sourceId"), a["sourceKind"], a["media"], None, a["provenance"], a.get("created", 1.0))

    def cursor(self):
        return CreationCursor(self)


PACK_FIELDS = ("id", "revision", "status", "task_context", "evidence_refs", "style_refs", "rationale", "gaps", "rights_warnings", "grant_revision",
               "draft_id", "created_by", "created_at", "updated_at")
ART_FIELDS = ("id", "run_id", "output_id", "idempotency_key", "content_sha256", "asset_key", "source_pack_id", "status", "error_code", "attempts")


class CreationCursor(VoiceCursor):
    def execute(self, sql, args=()):
        db = self.db
        tag = re.search(r"/\*(lis|lia|lio|lij|lil):([a-z_.]+)\*/", sql)
        handler = getattr(self, "_" + tag.group(2).replace(".", "_"), None) if tag else None
        if handler is not None:
            db.executed.append((sql, args))
            self._set([])
            return handler(args)
        if re.match(r"\s*(SAVEPOINT|RELEASE SAVEPOINT|ROLLBACK TO SAVEPOINT)", sql) or "pg_advisory_xact_lock" in sql:
            db.executed.append((sql, args))
            self._set([])
            if sql.startswith("ROLLBACK TO SAVEPOINT"):
                db.rolled_back = getattr(db, "rolled_back", 0) + 1
            return None
        if "SELECT w.revision,w.state," in sql:
            db.executed.append((sql, args))
            return self._set([(db.revision, json.dumps(db.state), "owner", False, False, False, False)])
        if "(id=%s OR lineage_id=%s) AND processing_status NOT IN" in sql:
            db.executed.append((sql, args))
            root = args[1].hex
            rows = [db.row(k) for k, a in db.assets.items() if k == root or a.get("lineage") == root]
            return self._set(sorted(rows, key=lambda r: r[2]))
        if sql.startswith("SELECT replace(id::text,'-',''),processing_status FROM public.pr_library_assets"):
            db.executed.append((sql, args))
            return self._set([(k, a["status"]) for k, a in db.assets.items() if a["status"] not in ("deleting", "duplicate")])
        return super().execute(sql, args)

    # --- source packs -------------------------------------------------------------------------------------------------
    def _pack_insert(self, args):
        pid, _, task, evidence, style, rationale, gaps, notes, revision, actor = args
        self.db.packs[pid] = {"id": pid, "revision": 1, "status": "draft", "task_context": json.loads(task), "evidence_refs": json.loads(evidence),
                              "style_refs": json.loads(style), "rationale": json.loads(rationale), "gaps": json.loads(gaps),
                              "rights_warnings": json.loads(notes), "grant_revision": revision, "draft_id": None, "created_by": actor,
                              "created_at": NOW, "updated_at": NOW}

    def _pack_get(self, args):
        row = self.db.packs.get(args[1])
        self._set([tuple(str(row[f]) if f == "id" else row[f] for f in PACK_FIELDS)] if row else [])

    _pack_lock = _pack_get

    def _pack_attach(self, args):
        draft, extra, _, pid, revision = args
        row = self.db.packs.get(pid)
        if row and row["revision"] == revision:
            row.update(status="attached", draft_id=draft, revision=revision + 1, task_context={**row["task_context"], **json.loads(extra)})
            self._set([(row["revision"],)])

    def _usage_recent(self, args):
        _, keys, _days = args
        counts = {}
        for u in self.db.usage:
            if u["asset_key"] in keys:
                counts[u["asset_key"]] = counts.get(u["asset_key"], 0) + 1
        self._set(sorted(counts.items()))

    def _segment_get(self, args):
        _, version, sid = args
        self._set([(s["id"], s["kind"], s["text"], json.dumps(s["locator"]), s["language"], s["speaker"], s["origin"], s["superseded"])
                   for s in self.db.segments if s["version"] == version and s["id"] == sid])

    # --- A's lifecycle: packs citing withdrawn items stop ------------------------------------------------------------
    def _revoke_packs(self, keys):
        changed = 0
        for row in self.db.packs.values():
            cited = json.dumps([row["evidence_refs"], row["style_refs"]])
            if row["status"] in ("draft", "attached") and (keys is None or any(k in cited for k in keys)):
                row["status"] = "revoked"
                changed += 1
        self.rowcount = changed

    def _rev_packs(self, args):
        self._revoke_packs(list(args[1]) if len(args) > 1 else None)

    def _packs_revoke(self, args):
        self._revoke_packs([args[2]])

    # --- D's relations and usage --------------------------------------------------------------------------------------
    def _rel_find(self, args):
        _, from_version, relation, to_kind, to_key, to_version = args
        self._set([(str(r["id"]), r["status"], r["evidence"]) for r in self.db.relations if (r["from_version"], r["relation"], r["to_kind"], r["to_key"],
                   r["to_version"] or "") == (from_version, relation, to_kind, to_key, to_version) and r["from_segment"] is None][:1])

    def _rel_insert(self, args):
        rid, _, from_key, from_version, segment, to_kind, to_key, to_version, relation, status, origin, evidence, _actor = args
        identity = (from_version, relation, to_kind, to_key, to_version or "", segment)
        if any((r["from_version"], r["relation"], r["to_kind"], r["to_key"], r["to_version"] or "", r["from_segment"]) == identity for r in self.db.relations):
            return self._set([])
        self.db.relations.append({"id": rid, "from_key": from_key, "from_version": from_version, "from_segment": segment, "to_kind": to_kind,
                                  "to_key": to_key, "to_version": to_version, "relation": relation, "status": status, "origin": origin,
                                  "evidence": json.loads(evidence)})
        self._set([(str(rid),)])

    def _rel_set(self, args):
        status, evidence, _, rid = args
        for r in self.db.relations:
            if r["id"] == rid:
                r.update(status=status, evidence={**r["evidence"], **json.loads(evidence)})

    def _rel_out(self, args):
        self._set([])

    def _usage_put(self, args):
        uid_, _, asset_key, version_key, segment, event_type, draft_id, _post, _channel, dedup, src, _metrics, _at = args
        if any(u["dedup_key"] == dedup for u in self.db.usage):
            return self._set([])
        self.db.usage.append({"id": uid_, "asset_key": asset_key, "version_key": version_key, "segment_id": segment, "event_type": event_type,
                              "draft_id": draft_id, "dedup_key": dedup, "source": json.loads(src)})
        self._set([(str(uid_),)])

    def _coll_smart(self, args):
        self._set([])

    def _ws_state(self, args):
        self._set([(json.dumps(self.db.state),)])

    # --- artifacts ----------------------------------------------------------------------------------------------------
    def _run_get(self, args):
        run = self.db.runs.get(str(args[1]))
        self._set([(run,)] if run else [])

    def _art_find(self, args):
        _, run_id, output_id, key = args
        rows = [a for a in self.db.artifacts if (a["run_id"] == run_id and a["output_id"] == output_id) or a["idempotency_key"] == key]
        self._set([tuple(str(a[f]) if f in ("id", "source_pack_id") and a[f] is not None else a[f] for f in ART_FIELDS) for a in rows])

    def _art_insert(self, args):
        aid, _, run_id, output_id, key, sha, pack = args
        if any((a["run_id"], a["output_id"]) == (run_id, output_id) or a["idempotency_key"] == key for a in self.db.artifacts):
            return self._set([])
        self.db.artifacts.append({"id": aid, "run_id": run_id, "output_id": output_id, "idempotency_key": key, "content_sha256": sha, "asset_key": None,
                                  "source_pack_id": pack, "status": "registering", "error_code": None, "attempts": 1})
        self._set([(str(aid),)])

    def _find_art(self, aid):
        return next(a for a in self.db.artifacts if str(a["id"]) == str(aid))

    def _art_retry(self, args):
        sha, pack, _, aid = args
        self._find_art(aid).update(status="registering", attempts=self._find_art(aid)["attempts"] + 1, error_code=None, content_sha256=sha, source_pack_id=pack)

    def _art_done(self, args):
        asset_key, _, aid = args
        self._find_art(aid).update(status="registered", asset_key=asset_key, error_code=None)

    def _art_fail(self, args):
        code, _, aid = args
        self._find_art(aid).update(status="failed", error_code=code)

    def _object_owned(self, args):
        _, name = args
        self._set([(k, a["sourceKind"]) for k, a in self.db.assets.items() if a.get("objectName") == name][:1])

    def _sha_owned(self, args):
        _, sha = args
        self._set([(k,) for k, a in self.db.assets.items() if a["sha"] == sha and a["sourceKind"] != "artifact"][:1])

    def _asset_insert(self, args):
        (aid, _, _actor, filename, title, kind, mime, ext, size, _bucket, name, _etag, provenance) = args
        key = aid.hex
        self.db.inserted_assets.append(key)
        self.db.assets[key] = {"key": key, "kind": kind, "sourceKind": "artifact", "provenance": json.loads(provenance), "status": "queued", "media": {},
                               "title": title, "sha": json.loads(provenance)["contentSha256"], "objectName": name, "sourceId": None, "created": NOW}

    def _pack_refs(self, args):
        row = self.db.packs.get(args[1])
        self._set([(row["evidence_refs"], row["style_refs"])] if row else [])


def fake_search(db, calls):
    """Keeps exactly what the real policy allows for the purpose; one query term, case-insensitive substring match."""
    def run(ctx, request):
        request = c.search_request(request)
        calls.append(request)
        term = request["query"].lower()
        scope = request["scope"]
        newest = {}
        for key, a in db.assets.items():
            root = a.get("lineage") or key
            if root not in newest or a.get("versionNo", 1) > db.assets[newest[root]].get("versionNo", 1):
                newest[root] = key
        keys = [r["versionId"] for r in scope["assetRefs"]] if scope["kind"] == "selection" else list(newest.values())
        loaded = versions.load(ctx, keys)
        hits = []
        for key, version in loaded.items():
            decision = policy.authorize_source(ctx, version, request["purpose"])
            if not decision.allowed:
                continue
            for s in sorted((s for s in db.segments if s["version"] == key and not s["superseded"]), key=lambda s: s["ordinal"]):
                if term in s["text"].lower():
                    hits.append({"assetRef": versions.ref(version), "displayTitle": version["title"], "kind": version["kind"], "segmentId": s["id"].hex,
                                 "locator": s["locator"], "locatorLabel": c.locator_label(s["locator"]), "snippet": s["text"][:80],
                                 "matchReasons": [{"kind": "lexical", "detail": term}], "createdAt": version["createdAt"],
                                 "sourceStatus": {"purpose": request["purpose"], "allowed": True, "reason": None, "candidateOnly": decision.candidate_only}})
                    break
        hits.sort(key=lambda h: (-h["createdAt"], h["assetRef"]["versionId"]))
        return {"hits": hits[:request["limit"]], "warnings": [], "coverage": {}}
    return run


def service(db):
    return SimpleNamespace(commands=HostedPhase2Commands(clock=lambda: NOW), repository=SimpleNamespace(effects=[]), clock=lambda: NOW,
                           library=SimpleNamespace(storage=db.storage, bucket="postriff-library", assert_capacity=lambda cur, state, w, size=0: None),
                           assets=SimpleNamespace(storage=db.storage))


def make_ctx(db, *, role="owner"):
    return c.LibraryContext(workspace_id=WS, actor=ACTOR, membership=Membership(role), state=copy.deepcopy(db.state), cur=db.cursor(), now=NOW,
                            service=service(db))


def task(goal, *, scope=None, selected=(), channels=None, locale="en", persona=None):
    out = {"userGoal": goal, "scope": scope if scope is not None else {"kind": "workspace"}, "selectedSourceRefs": list(selected), "locale": locale}
    if channels:
        out["channels"] = channels
    if persona:
        out["personaId"] = persona
    return out


def fixture():
    db = CreationDB()
    db.state["sources"] += [source("srcfacts", [("Brahms Op.118 recital at City Hall", True), ("Tickets from 200 HKD", False)]),
                            source("srcused", [("Brahms phrasing masterclass notes", True)]),
                            source("srcreview", [("A review of the Brahms recital", True)], policy_name="public_quote")]
    refs = {"doc": db.asset(DOC, title="Recital programme", source_id="srcfacts", created=10.0),
            "used": db.asset(USED, title="Masterclass notes", source_id="srcused", created=30.0),
            "review": db.asset(REVIEW, title="Recital review", source_id="srcreview", created=20.0),
            "note": db.asset(NOTE, source_kind="note", provenance={"source": "note", "authoredByMe": True}, title="Practice diary", created=5.0),
            "old": db.asset(OLD, title="Concert poster", created=1.0),
            "new": db.asset(NEW, title="Concert poster", lineage=OLD, version_no=2, created=2.0),
            "photo": db.asset(PHOTO, kind="image", title="Hall photo", created=3.0)}
    db.add_segments(DOC, [{"kind": "text", "text": "Brahms recital at City Hall with Op.118.", "locator": {"kind": "text", "start": 0, "end": 40}},
                          {"kind": "text", "text": "The programme pairs Intermezzi with Ballades.", "locator": {"kind": "text", "start": 42, "end": 87}}])
    db.add_segments(USED, [{"kind": "text", "text": "Brahms phrasing masterclass notes.", "locator": {"kind": "text", "start": 0, "end": 34}}])
    db.add_segments(REVIEW, [{"kind": "text", "text": "A review of the Brahms recital.", "locator": {"kind": "text", "start": 0, "end": 31}}])
    db.add_segments(NOTE, [{"kind": "text", "text": NOTE_TEXT, "locator": {"kind": "text", "start": 0, "end": len(NOTE_TEXT)}},
                           {"kind": "text", "text": "Then I play it once at tempo.", "locator": {"kind": "text", "start": len(NOTE_TEXT) + 2, "end": len(NOTE_TEXT) + 31}}])
    for key in (OLD, NEW):
        db.add_segments(key, [{"kind": "text", "text": "Concert poster for the Brahms recital.", "locator": {"kind": "text", "start": 0, "end": 38}}])
    for n in range(3):  # USED was cited in recent drafts: it should yield to fresher material
        db.usage.append({"id": uuid.uuid4(), "asset_key": USED, "version_key": USED, "segment_id": None, "event_type": "draft_attached",
                         "draft_id": f"old-draft-{n}", "dedup_key": f"seed-usage-{n}-padding", "source": {}})
    db.state["variants"].append({"id": "f" * 32, "revision": 1, "text": DRAFT_TEXT, "platform": "Instagram", "language": "English", "sourceIds": [],
                                 "voiceSourceIds": [], "runId": RUN, "needsReview": True, "blockedByRetraction": False, "unknowns": [],
                                 "revisions": [{"revision": 1, "text": DRAFT_TEXT, "origin": "ideas-candidate"}], "provenance": {"runId": RUN}})
    db.runs.update({RUN: "applied", OTHER_RUN: "completed", FAILED_RUN: "failed"})
    return db, refs


def voice_span(db, refs):
    """An approved positive voice span on the practice diary (the real T07 path)."""
    db.grant("voice", NOTE)
    return voice.approve_voice_span(make_ctx(db), refs["note"], {"kind": "text", "start": 0, "end": len(NOTE_TEXT)}, "default", WROTE,
                                    uses=USES, confirmed=True, select=True)


class Base(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db, self.refs = fixture()
        self.calls = []
        search_patch = mock.patch.object(search, "search_library", fake_search(self.db, self.calls))
        search_patch.start()
        self.addCleanup(search_patch.stop)
        api.mount(service(self.db))  # as LibraryIntelligence does; repository effects build their context through it
        self.addCleanup(api.mount, None)

    def refused(self, fn, code, status=None):
        with self.assertRaises(AlphaError) as raised:
            fn()
        self.assertEqual(raised.exception.code, code, str(raised.exception))
        if status is not None:
            self.assertEqual(raised.exception.status, status)
        return raised.exception

    def recommend(self, goal, return_to=None, **kw):
        return source_packs.recommend_sources(make_ctx(self.db), task(goal, **kw), return_to=return_to)


class SourcePackTests(Base):
    def test_evidence_style_separate(self):
        """A049: evidence comes from approved Library facts, style only from approved voice spans; they never mix, and on
        attach evidence enters Ideas for fact review while style reaches only the drafting voice context."""
        db, refs = self.db, self.refs
        span = voice_span(db, refs)
        pack = self.recommend("Announce my Brahms recital", selected=[{"assetRef": refs["note"]}])
        evidence = {e["assetRef"]["versionId"]: e for e in pack["evidenceRefs"]}
        self.assertTrue({DOC, REVIEW} <= set(evidence), evidence.keys())
        self.assertEqual({e["purpose"] for e in pack["evidenceRefs"]}, {"evidence"})
        self.assertEqual([s["sampleId"] for s in pack["styleRefs"]], [span["sampleId"]])
        self.assertEqual({s["purpose"] for s in pack["styleRefs"]}, {"style"})
        self.assertTrue(all("text" not in s for s in pack["styleRefs"]), "style refs carry references, not prose")
        self.assertEqual(evidence[NOTE]["review"], "needs_review", "an explicitly selected item without approved facts is evidence pending review")
        self.assertEqual(evidence[DOC]["review"], "approved")
        stored = db.packs[uuid.UUID(hex=pack["packId"])]
        self.assertEqual((len(stored["evidence_refs"]), len(stored["style_refs"]), stored["revision"]), (len(pack["evidenceRefs"]), 1, 1))
        self.assertEqual(stored["grant_revision"], db.grant_revision)
        result = source_packs.attach_pack_to_draft(make_ctx(db), pack["packId"], "f" * 32, 1)
        self.assertEqual(result["status"], "applied", result)
        draft = next(v for v in db.state["variants"] if v["id"] == "f" * 32)
        attached = draft["librarySources"]
        self.assertEqual({e["purpose"] for e in attached["evidence"]}, {"evidence"})
        self.assertEqual([s["sampleId"] for s in attached["style"]], [span["sampleId"]])
        self.assertEqual(draft["sourceIds"], [], "attaching never rewrites what the draft was written from")
        self.assertEqual(draft["text"], DRAFT_TEXT)
        imported = {s["id"]: s for s in db.state["sources"] if (s.get("origin") or {}).get("kind") == "library"}
        self.assertEqual({s["origin"]["assetId"] for s in imported.values()}, {NOTE}, "only items without an Ideas source are imported")
        note_source = next(iter(imported.values()))
        self.assertEqual(note_source["text"], NOTE_TEXT + "\n\nThen I play it once at tempo.")
        self.assertFalse(any(f["approved"] for f in note_source["facts"]), "facts are never auto-approved")
        self.assertEqual((note_source["sourcePolicy"], note_source["egressConsent"]), ("rewrite_approval", ["local"]))
        ideas_ids = {e["assetRef"]["versionId"]: e["ideasSourceId"] for e in attached["evidence"]}
        self.assertEqual(ideas_ids[DOC], "srcfacts", "an item already reviewed in Ideas keeps its reviewed source")
        self.assertEqual(result["composer"]["voiceSourceIds"], [span["voiceSourceId"]])
        self.assertEqual(result["composer"]["voiceMode"], "personalized")
        self.assertNotIn(span["voiceSourceId"], result["composer"]["sourceIds"], "a voice sample never becomes evidence")
        self.assertEqual(sorted(result["composer"]["sourceIds"]), sorted(set(ideas_ids.values())))
        self.assertTrue(all(s.get("kind") != "voice_sample" for s in db.state["sources"] if s["id"] in result["composer"]["sourceIds"]))

    def test_no_whole_library_prompt(self):
        """A050/R12: a pack needs an explicit scope and caps its evidence; attaching imports only the pack's refs."""
        db, refs = self.db, self.refs
        self.refused(lambda: source_packs.recommend_sources(make_ctx(db), {"userGoal": "Announce my Brahms recital", "locale": "en"}),
                     "library_pack_scope_required", 422)
        for n in range(40):
            key = f"{n:032x}"
            db.state["sources"].append(source(f"bulk{n}", [(f"Brahms fact {n}", True)]))
            db.asset(key, title=f"Brahms file {n}", source_id=f"bulk{n}", created=100.0 + n)
            db.add_segments(key, [{"kind": "text", "text": f"Brahms recital fact number {n}.", "locator": {"kind": "text", "start": 0, "end": 30}}])
        pack = self.recommend("Brahms recital programme")
        self.assertLessEqual(len(pack["evidenceRefs"]), source_packs.MAX_RECOMMENDED)
        self.assertEqual(len({e["assetRef"]["assetId"] for e in pack["evidenceRefs"]}), len(pack["evidenceRefs"]), "one passage per item")
        self.assertLessEqual(len(self.calls), source_packs.MAX_QUERIES)
        self.assertTrue(all(call["limit"] <= source_packs.QUERY_LIMIT and call["purpose"] == "draft_evidence" for call in self.calls))
        self.assertTrue(any(r["code"] == "cap" for r in pack["rationale"]))
        too_many = [{"assetRef": versions.ref(v)} for v in versions.load(make_ctx(db), [f"{n:032x}" for n in range(source_packs.MAX_EVIDENCE + 1)]).values()]
        self.refused(lambda: source_packs.recommend_sources(make_ctx(db), task("Brahms", selected=too_many)), "library_pack_too_many", 422)
        before = len(db.state["sources"])
        source_packs.attach_pack_to_draft(make_ctx(db), pack["packId"], "f" * 32, 1)
        self.assertEqual(len(db.state["sources"]), before, "every recommended item already had a reviewed Ideas source; nothing else was imported")
        attached = next(v for v in db.state["variants"] if v["id"] == "f" * 32)["librarySources"]
        self.assertEqual(len(attached["evidence"]), len(pack["evidenceRefs"]))

    def test_source_pack_survives_navigation(self):
        """A049/A051: the Library state to return to travels with the pack and the draft, validated and URL-free."""
        db, refs = self.db, self.refs
        back = {"query": "brahms", "scope": {"kind": "workspace"}, "filters": {"kinds": ["document"]}, "sort": "newest", "density": "compact",
                "selection": [DOC, NOTE], "anchor": DOC, "view": "grid"}
        pack = source_packs.recommend_sources(make_ctx(db), task("Announce my Brahms recital"), return_to=back)
        self.assertEqual(pack["returnTo"], back)
        read = source_packs.pack_http(make_ctx(db, role="viewer"), {"params": {"key": pack["packId"]}, "query": {}, "body": {}})
        self.assertEqual(read["returnTo"], back)
        result = source_packs.attach_pack_to_draft(make_ctx(db), pack["packId"], "f" * 32, 1)
        self.assertEqual(result["returnTo"], back)
        self.assertEqual(next(v for v in db.state["variants"] if v["id"] == "f" * 32)["librarySources"]["returnTo"], back)
        for bad in ({"query": "see https://example.com"}, {"selection": ["not-a-key"]}, {"href": "/library"}, {"query": "x" * 5000}):
            with self.assertRaises(AlphaError):
                source_packs.recommend_sources(make_ctx(db), task("Announce my Brahms recital"), return_to=bad)
        # An item deleted since leaving the Library is dropped from the selection without naming it.
        db.assets[NOTE]["status"] = "deleting"
        read = source_packs.pack_http(make_ctx(db), {"params": {"key": pack["packId"]}, "query": {}, "body": {}})
        self.assertEqual(read["returnTo"]["selection"], [DOC])
        self.assertEqual(read["returnToRemoved"], 1)
        self.assertNotIn(NOTE, json.dumps(read["returnTo"]))

    def test_missing_inputs_named(self):
        """A050: missing inputs are specific gaps; unknown rights are warnings and never shown as cleared."""
        db, refs = self.db, self.refs
        pack = self.recommend("Announce my Brahms recital concert and ticket prices", channels=["Instagram"], selected=[{"assetRef": refs["photo"]}],
                              persona="teacher")
        codes = {g["code"]: g["message"] for g in pack["gaps"]}
        self.assertIn("missing_fact_date", codes)
        self.assertIn("date", codes["missing_fact_date"])
        self.assertIn("recital", codes["missing_fact_date"])
        self.assertIn("missing_fact_price", codes)
        self.assertEqual(codes.get("missing_public_image"), "No image approved for public use for Instagram.")
        self.assertIn("missing_voice_examples", codes)
        self.assertNotIn("missing_fact_venue", codes, "City Hall is an approved fact")
        rights = {w["assetRef"]["versionId"]: w["code"] for w in pack["rightsWarnings"] if w.get("assetRef")}
        self.assertEqual(rights[PHOTO], "rights_unknown")
        self.assertEqual(rights[DOC], "public_use_not_approved")
        self.assertNotIn(REVIEW, rights, "public_quote material needs no rights warning")
        photo = next(e for e in pack["evidenceRefs"] if e["assetRef"]["versionId"] == PHOTO)
        self.assertEqual(photo["rights"], "unknown")
        self.assertNotIn("cleared", json.dumps(pack).lower())
        # A dated, approved fact closes the date gap.
        db.state["sources"][0]["facts"].append({"id": "srcfacts-9", "text": "The recital is on 12 October 2026", "approved": True, "sourceId": "srcfacts"})
        pack = self.recommend("Announce my Brahms recital concert", channels=["LinkedIn"])
        self.assertNotIn("missing_fact_date", {g["code"] for g in pack["gaps"]})

    def test_recommendations_rank_currency_and_freshness(self):
        """A050: one passage per item, recently used material yields to fresh material, older versions are flagged."""
        db, refs = self.db, self.refs
        pack = self.recommend("Brahms", selected=[{"assetRef": refs["old"]}])
        order = [e["assetRef"]["versionId"] for e in pack["evidenceRefs"] if e["selection"] == "recommended"]
        self.assertLess(order.index(REVIEW), order.index(USED), "USED was cited in three recent drafts")
        old = next(e for e in pack["evidenceRefs"] if e["assetRef"]["versionId"] == OLD)
        self.assertFalse(old["current"])
        self.assertTrue(any(w["code"] == "older_version" and w["assetRef"]["versionId"] == OLD for w in pack["rightsWarnings"]))
        self.assertTrue(all(isinstance(e["why"], list) and e["why"] for e in pack["evidenceRefs"]))
        self.assertFalse(re.search(r"score|percent|confidence", json.dumps(pack), re.I))


class AttachTests(Base):
    def _pack(self):
        voice_span(self.db, self.refs)
        return self.recommend("Announce my Brahms recital", selected=[{"assetRef": self.refs["note"]}])

    def test_changed_grant_blocks_draft_attach(self):
        """A grant or source decision that narrowed since the snapshot blocks the attach with what changed; nothing is written."""
        db = self.db
        pack = self._pack()
        state_before = copy.deepcopy(db.state)
        stale = self.refused(lambda: source_packs.attach_pack_to_draft(make_ctx(db), pack["packId"], "f" * 32, 9), "library_pack_conflict", 409)
        self.assertIn("changed", str(stale))
        voice_grant = next(g for g in db.grants if g["purpose"] == "voice")
        policy.revoke(make_ctx(db), voice_grant["id"].hex)
        self.assertEqual(db.packs[uuid.UUID(hex=pack["packId"])]["status"], "revoked", "lifecycle stops packs citing the withdrawn item")
        db.state["sources"][0]["egressConsent"] = ["local"]  # the reviewed facts source is no longer shared with cloud writers
        state_before = copy.deepcopy(db.state)
        result = source_packs.attach_pack_to_draft(make_ctx(db), pack["packId"], "f" * 32, 1)
        self.assertEqual((result["status"], result["packStatus"]), ("conflict", "revoked"))
        changes = {(ch["purpose"], ch["assetRef"]["versionId"], ch["change"]) for ch in result["changes"]}
        self.assertIn(("style", NOTE, "permission_narrowed"), changes)
        self.assertIn(("evidence", DOC, "permission_narrowed"), changes)
        doc_change = next(ch for ch in result["changes"] if ch["assetRef"]["versionId"] == DOC)
        self.assertEqual(doc_change["after"]["reason"], "egress_consent_required")
        self.assertEqual(db.state, state_before, "a blocked attach writes nothing")
        self.assertNotEqual(db.packs[uuid.UUID(hex=pack["packId"])]["status"], "attached")
        outcome = actions.apply(make_ctx(db), {"actionId": "attach1", "uiInstanceId": "ui", "actionType": "source_pack.attach", "targetRefs": [],
                                               "expectedRevision": 1, "idempotencyKey": "attach-key-000000001",
                                               "payload": {"packId": pack["packId"], "draftId": "f" * 32}})
        self.assertEqual(outcome["status"], "conflict")
        self.assertTrue(outcome["result"]["changes"])

    def test_attach_records_lineage_usage_and_is_idempotent(self):
        db = self.db
        pack = self._pack()
        envelope = {"actionId": "attach2", "uiInstanceId": "ui", "actionType": "source_pack.attach", "targetRefs": [], "expectedRevision": 1,
                    "idempotencyKey": "attach-key-000000002", "payload": {"packId": pack["packId"], "draftId": "f" * 32}}
        held = getattr(db, "held", 0)
        first = actions.apply(make_ctx(db), envelope)
        self.assertEqual((first["status"], first["revision"]), ("applied", 2), first)
        self.assertGreater(getattr(db, "held", 0), held, "attach locks the workspace row before its final recheck")
        replay = actions.apply(make_ctx(db), envelope)
        self.assertTrue(replay.get("replayed"))
        self.assertEqual(db.packs[uuid.UUID(hex=pack["packId"])]["revision"], 2)
        drafts = {(r["from_version"], r["to_kind"], r["to_key"]) for r in db.relations if r["relation"] == "used_in"}
        self.assertIn((DOC, "draft", "f" * 32), drafts)
        self.assertIn((NOTE, "draft", "f" * 32), drafts)
        self.assertIn((DOC, "source_pack", pack["packId"]), drafts)
        self.assertTrue(any(to_kind == "idea" for _, to_kind, _ in drafts))
        events = [(u["event_type"], u["version_key"]) for u in db.usage]
        self.assertIn(("source_pack", DOC), events)
        self.assertIn(("draft_attached", DOC), events)
        again = source_packs.attach_pack_to_draft(make_ctx(db), pack["packId"], "f" * 32, 2)
        self.assertTrue(again["alreadyAttached"])
        db.state["variants"].append({**copy.deepcopy(db.state["variants"][0]), "id": "e" * 32})
        self.refused(lambda: source_packs.attach_pack_to_draft(make_ctx(db), pack["packId"], "e" * 32, 2), "library_pack_attached", 409)
        self.refused(lambda: source_packs.attach_pack_to_draft(make_ctx(db), self._pack()["packId"], "9" * 32, 1), "library_draft_unavailable", 404)

    def test_create_and_select_actions_use_explicit_refs(self):
        db, refs = self.db, self.refs
        span = voice_span(db, refs)
        selected = actions.apply(make_ctx(db, role="viewer"), {"actionId": "sel", "uiInstanceId": "ui", "actionType": "sources.select",
                                                               "targetRefs": [refs["doc"], refs["note"]], "idempotencyKey": "select-key-0000000001",
                                                               "payload": {}})
        self.assertEqual([x["review"] for x in selected["result"]["candidates"]], ["approved", "needs_review"])
        self.assertEqual(db.packs, {}, "selection is read-only")
        envelope = {"actionId": "create", "uiInstanceId": "ui", "actionType": "source_pack.create", "targetRefs": [refs["doc"]],
                    "idempotencyKey": "create-key-000000001",
                    "payload": {"taskContext": task("Announce my Brahms recital"), "evidence": [{"assetRef": refs["doc"]}], "styleSampleIds": [span["sampleId"]]}}
        created = actions.apply(make_ctx(db), envelope)
        self.assertEqual(created["status"], "applied", created)
        self.assertEqual([e["assetRef"]["versionId"] for e in created["result"]["evidenceRefs"]], [DOC])
        self.assertEqual([e["selection"] for e in created["result"]["evidenceRefs"]], ["user"])
        self.assertEqual(self.calls, [], "an explicit pack never searches")
        undeclared = {**envelope, "idempotencyKey": "create-key-000000002", "targetRefs": []}
        with self.assertRaises(AlphaError):
            actions.apply(make_ctx(db), undeclared)


class ArtifactTests(Base):
    def _review(self, variant_id="f" * 32):
        variant = next(v for v in self.db.state["variants"] if v["id"] == variant_id)
        variant.update(needsReview=False, uncertaintyReview={"revision": variant["revision"], "excludedFromDraft": [], "actor": ACTOR, "at": NOW})
        return variant

    def _request(self, raw, **over):
        key = over.pop("key", "9" * 32)
        req = {"runId": RUN, "outputId": "f" * 32 + ":r1", "contentSha256": hashlib.sha256(raw).hexdigest(),
               "storageRef": {"category": "file", "objectName": f"{key}.md"}, "mime": "text/markdown", "displayTitle": "Recital post",
               "originalFilename": "recital-post.md", "artifactRole": "final", "parentRefs": [], "idempotencyKey": "artifact-key-000000001"}
        req.update(over)
        return req

    def test_replayed_output_registered_once(self):
        """A052: an accepted draft registers once; replayed completion events return the same AssetRef and no second asset."""
        db = self.db
        self._review()
        first = artifacts.store_text_deliverable(make_ctx(db), RUN, "f" * 32)
        self.assertEqual(first["status"], "registered", first)
        second = artifacts.store_text_deliverable(make_ctx(db), RUN, "f" * 32)
        self.assertTrue(second["replayed"])
        self.assertEqual(second["assetRef"], first["assetRef"])
        self.assertEqual(len(db.inserted_assets), 1)
        self.assertEqual([a["status"] for a in db.artifacts], ["registered"])
        asset = db.assets[first["assetRef"]["assetId"]]
        self.assertEqual((asset["sourceKind"], asset["status"]), ("artifact", "queued"), "the normal Library worker processes it next")
        self.assertEqual((asset["provenance"]["runId"], asset["provenance"]["outputId"]), (RUN, "f" * 32 + ":r1"))
        raw = db.storage.get(WS, "file", f"{first['assetRef']['assetId']}.md")
        self.assertEqual(raw.decode().strip(), DRAFT_TEXT)
        # Another key for the same run/output is the same registration; different content for it is a conflict.
        replay = artifacts.register_final_artifact(make_ctx(db), self._request(raw, key=first["assetRef"]["assetId"], idempotencyKey="artifact-key-other-0001"))
        self.assertEqual((replay["assetRef"], replay["replayed"]), (first["assetRef"], True))
        self.refused(lambda: artifacts.register_final_artifact(make_ctx(db), self._request(b"different", key=first["assetRef"]["assetId"],
                                                                                            idempotencyKey="artifact-key-other-0002")),
                     "library_artifact_conflict", 409)
        # The repository effect fires once per acceptance, not per command.
        before = copy.deepcopy(db.state)
        self.assertEqual(artifacts.capture_effect(make_ctx(db).cur, WS, before, before, ACTOR), [])
        self.assertEqual(len(db.inserted_assets), 1)

    def test_scratch_not_ingested(self):
        """A053: temporary, scratch, tool-output and external storage refs, working drafts and failed runs never register."""
        db = self.db
        raw = (DRAFT_TEXT + "\n").encode()
        db.storage.put_immutable(WS, "file", "9" * 32 + ".md", raw, "text/markdown")
        self.refused(lambda: artifacts.register_final_artifact(make_ctx(db), self._request(raw, artifactRole="scratch")), "library_artifact_not_final", 422)
        for ref in ({"category": "file", "objectName": "tmp/run-1.md"}, {"category": "scratch", "objectName": "9" * 32 + ".md"},
                    {"category": "file", "objectName": "https://cdn.example/x.md"}):
            self.refused(lambda ref=ref: artifacts.register_final_artifact(make_ctx(db), self._request(raw, storageRef=ref)), "library_artifact_storage", 422)
        for over in ({"originalFilename": "agent-run.log"}, {"mime": "application/x-ndjson", "originalFilename": "trace.jsonl"},
                     {"originalFilename": "tmp-draft.md"}):
            self.refused(lambda over=over: artifacts.register_final_artifact(make_ctx(db), self._request(raw, **over)), "library_artifact_scratch", 422)
        self.refused(lambda: artifacts.register_final_artifact(make_ctx(db), self._request(raw)), "library_artifact_not_final", 409)  # still a working draft
        self.refused(lambda: artifacts.register_final_artifact(make_ctx(db), self._request(raw, outputId="candidate-1")), "library_artifact_not_final", 409)
        self._review()
        self.refused(lambda: artifacts.register_final_artifact(make_ctx(db), self._request(raw, runId=FAILED_RUN)), "library_artifact_not_final", 409)
        self.refused(lambda: artifacts.register_final_artifact(make_ctx(db), self._request(raw, runId="22222222-2222-4222-8222-222222222222")),
                     "library_artifact_run_unavailable", 404)
        self.assertEqual((db.inserted_assets, [a for a in db.artifacts if a["status"] == "registered"]), ([], []))

    def test_ingest_loop_guard(self):
        """A053: Library objects, copies of ingested items, ingestion previews and extracted passages are never re-registered."""
        db = self.db
        self._review()
        variant = db.state["variants"][0]
        # 1. The output points at an object the Library already owns.
        db.assets[DOC]["objectName"] = "9" * 32 + ".md"
        raw = (DRAFT_TEXT + "\n").encode()
        db.storage.put_immutable(WS, "file", "9" * 32 + ".md", raw, "text/markdown")
        self.refused(lambda: artifacts.register_final_artifact(make_ctx(db), self._request(raw)), "library_artifact_loop", 422)
        db.assets[DOC]["objectName"] = DOC + ".md"
        # 2. Identical bytes to an ingested upload.
        db.assets[REVIEW]["sha"] = hashlib.sha256(raw).hexdigest()
        self.refused(lambda: artifacts.register_final_artifact(make_ctx(db), self._request(raw)), "library_artifact_loop", 422)
        db.assets[REVIEW]["sha"] = hashlib.sha256(REVIEW.encode()).hexdigest()
        # 3. A draft that only repeats a Library passage it was given.
        passage = next(s for s in db.segments if s["version"] == DOC)
        variant.update(text=passage["text"], revisions=[{"revision": 1, "text": passage["text"], "origin": "ideas-candidate"}])
        copied = (passage["text"] + "\n").encode()
        db.storage.put_immutable(WS, "file", "8" * 32 + ".md", copied, "text/markdown")
        self.refused(lambda: artifacts.register_final_artifact(make_ctx(db), self._request(copied, key="8" * 32, parentRefs=[
            {"assetRef": self.refs["doc"], "segmentId": passage["id"].hex}])), "library_artifact_loop", 422)
        # 4. A video poster or frame (an ingestion preview) is not an image Rafii made.
        poster = POSTER_VIDEO + "-" + "ab" * 32 + ".jpg"
        db.state["phase2"]["assets"].append({"id": POSTER_VIDEO, "mime": "video/mp4", "objectName": POSTER_VIDEO + ".mp4", "hash": "cd" * 32,
                                             "poster": {"objectName": poster}, "frames": [{"objectName": poster}]})
        db.storage.put_immutable(WS, "media", poster, b"jpeg-bytes")
        self.refused(lambda: artifacts.register_final_artifact(make_ctx(db), self._request(b"jpeg-bytes", storageRef={"category": "media", "objectName": poster},
                                                                                            mime="image/jpeg", outputId=POSTER_VIDEO,
                                                                                            originalFilename="poster.jpg")), "library_artifact_loop", 422)
        self.assertEqual((db.inserted_assets, [a for a in db.artifacts if a["status"] == "registered"]), ([], []))

    def test_generated_image_registered_without_second_asset(self):
        db = self.db
        image_id, raw = "4" * 32, b"generated-jpeg"
        digest_ = hashlib.sha256(raw).hexdigest()
        asset = {"id": image_id, "objectName": f"{image_id}-{digest_}.jpg", "hash": digest_, "mime": "image/jpeg", "origin": "rafii_agent",
                 "alt": "A poster for the Brahms recital", "lineage": {"runId": RUN, "parentAssetId": None, "sourceAssetIds": [], "operation": "generated"}}
        db.state["phase2"]["assets"].append(asset)
        db.storage.put_immutable(WS, "media", asset["objectName"], raw)
        first = artifacts.register_generated_image(make_ctx(db), RUN, asset)
        self.assertEqual((first["status"], first["assetRef"]["assetId"]), ("registered", image_id))
        self.assertTrue(artifacts.register_generated_image(make_ctx(db), RUN, asset)["replayed"])
        self.assertEqual((db.inserted_assets, len(db.artifacts)), ([], 1), "the saved image is the Library item; no second asset")
        self.refused(lambda: artifacts.register_generated_image(make_ctx(db), OTHER_RUN, asset), "library_artifact_loop", 422)

    def test_failed_registration_stays_retryable(self):
        db = self.db
        self._review()
        raw = (DRAFT_TEXT + "\n").encode()
        failed = artifacts.register_final_artifact(make_ctx(db), self._request(raw))
        self.assertEqual((failed["status"], failed["errorCode"], failed["retryable"], failed["archived"]),
                         ("failed", "library_artifact_bytes_missing", True, False))
        self.assertIsNone(failed["assetRef"])
        self.assertEqual([(a["status"], a["attempts"]) for a in db.artifacts], [("failed", 1)])
        db.storage.put_immutable(WS, "file", "9" * 32 + ".md", raw, "text/markdown")
        retried = artifacts.register_final_artifact(make_ctx(db), self._request(raw))
        self.assertEqual(retried["status"], "registered")
        self.assertEqual([(a["status"], a["attempts"]) for a in db.artifacts], [("registered", 2)])

    def test_capture_effect_registers_on_acceptance_with_pack_lineage(self):
        db = self.db
        voice_span(db, self.refs)
        pack = self.recommend("Announce my Brahms recital", selected=[{"assetRef": self.refs["note"]}])
        source_packs.attach_pack_to_draft(make_ctx(db), pack["packId"], "f" * 32, 1)
        before = copy.deepcopy(db.state)
        self._review()
        registered = artifacts.capture_effect(make_ctx(db).cur, WS, before, db.state, ACTOR)
        self.assertEqual([r["status"] for r in registered], ["registered"], registered)
        artifact_key = registered[0]["assetRef"]["assetId"]
        parents = {r["to_version"] for r in db.relations if r["relation"] == "derived_from" and r["from_version"] == artifact_key}
        self.assertTrue({DOC, NOTE} <= parents, parents)
        self.assertEqual(str(db.artifacts[0]["source_pack_id"]).replace("-", ""), pack["packId"])
        with mock.patch.dict(os.environ, {"RAFII_LIBRARY_ARTIFACTS_ENABLED": ""}):
            self.assertEqual(artifacts.capture_effect(make_ctx(db).cur, WS, before, db.state, ACTOR), [], "off unless enabled")


if __name__ == "__main__":
    unittest.main()
