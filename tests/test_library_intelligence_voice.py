"""T07 — consented Library voice spans through the canonical voice system (A007, A044–A048).

Real logic, not mocks: `voice_sources` (import, grant, select, revoke, project, retrieve), `voice_analysis.build_proposal`
and the domain `profile_decide` via the hosted command router (`HostedPhase2Commands`), `memory.render_files`
(VOICE.md), `GrowthService.invalidate`, `policy` grants/recheck and `lifecycle.propagate_revocation` all run on an
in-memory workspace state. Only SQL is answered by `VoiceDB`, a small in-memory stand-in for the tables these modules
touch. Real PostgreSQL behaviour is covered by tests/phase2/postgres_library_intelligence_voice.py (cloud).
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
from postriff_phase2 import memory, voice_sources
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.growth.service import GrowthService
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.library_intelligence import actions, contracts as c, policy, versions, voice
from postriff_phase2.permissions import Membership

NOW = 1_790_000_000.0
ENV = {"RAFII_LIBRARY_VOICE_ENABLED": "1"}
WRITER = "cloud:vercel-ai-gateway:openai/gpt-5.1"
USES = [{"purpose": "analysis", "route": "local-rules"}, {"purpose": "generation", "route": voice_sources.MANAGED_WRITER_ROUTE}]
WROTE = {"authoredByMe": True, "method": "written_by_me"}

ESSAY, INTERVIEW, LINK, GUEST_NOTE, ARTIFACT, STORAGE, ZH, MIXED = ("e" * 32, "f" * 32, "1" * 32, "2" * 32, "3" * 32, "4" * 32, "5" * 32, "6" * 32)
P0 = "Every morning I practise scales slowly, then I play the piece once at tempo."
P1 = "“Slow practice is fast learning.”"
P2 = "Tonight's programme opens with Brahms, and I can't wait to share it with you!!! Don't miss out!!!"
ZH_TEXT = "我每朝都會慢慢練琴，然後先至彈一次正常速度。"
LINK_TEXT = "A famous pianist explains why she never practises slowly."
GUEST_TEXT = "My guest told me she memorises away from the piano first."
ARTIFACT_TEXT = "Join me for an unforgettable evening of Brahms."
STORAGE_TEXT = "I agree to perform on the date above."
OWN_LINE, AI_LINE = "I wrote this opening line myself.", "Rafii suggested this closing line."


def whole(text):
    return {"kind": "text", "start": 0, "end": len(text)}


def text_segments(*paragraphs):
    out, offset = [], 0
    for paragraph in paragraphs:
        out.append({"kind": "text", "text": paragraph, "locator": {"kind": "text", "start": offset, "end": offset + len(paragraph)}})
        offset += len(paragraph) + 2
    return out


def span(index, paragraphs):
    start = sum(len(p) + 2 for p in paragraphs[:index])
    return {"kind": "text", "start": start, "end": start + len(paragraphs[index])}


# --- in-memory SQL ---------------------------------------------------------------------------------------------------
class VoiceDB:
    def __init__(self):
        self.state = initial_phase2_state(WS, ACTOR, "Owner", "studio", NOW)
        self.revision = 7
        self.assets, self.segments, self.grants, self.voice = {}, [], [], []
        self.grant_revision = 0
        self.audits, self.receipts, self.executed = [], {}, []
        self.genome_stale = 0
        self.on_share = None
        self.clock = 0

    # fixtures
    def asset(self, key, *, kind="document", source_kind="upload", provenance=None, status="ready", media=None, title="Notes"):
        sha = hashlib.sha256(key.encode()).hexdigest()
        self.assets[key] = {"key": key, "kind": kind, "sourceKind": source_kind, "provenance": provenance or {"source": source_kind},
                            "status": status, "media": media or {}, "title": title, "sha": sha}
        return {"assetId": key, "versionId": key, "sha256": sha}

    def add_segments(self, key, items):
        for n, item in enumerate(items):
            self.segments.append({"id": uuid.uuid4(), "version": key, "ordinal": n, "kind": item.get("kind", "text"), "text": item["text"],
                                  "language": item.get("language", "en"), "locator": item["locator"], "speaker": item.get("speaker"),
                                  "origin": item.get("origin", "extracted"), "superseded": False})

    def grant(self, purpose, key=None):
        self.grant_revision += 1
        gid = uuid.uuid4()
        self.grants.append({"id": gid, "type": "purpose", "scope": "asset" if key else "workspace", "key": key or "*", "members": [],
                            "purpose": purpose, "attestation": WROTE if purpose == "voice" else {}, "revision": self.grant_revision, "revoked": False})
        return gid.hex

    def cursor(self):
        return VoiceCursor(self)

    def row(self, key):
        a = self.assets[key]
        return (uuid.UUID(hex=key), None, 1, WS, a["title"] + ".md", a["title"], "filename", None, [], a["kind"], "text/markdown", "md", 100, a["sha"],
                a["status"], "ready", "ready", "not_applicable", None, a["sourceKind"], a["media"], None, a["provenance"], 1.0)


SAMPLE_FIELDS = ("id", "voice_source_id", "asset_key", "version_key", "source_sha256", "locator", "text", "text_hash", "persona_id", "brand", "language",
                 "polarity", "attestation", "consent_revision", "status", "revision", "created_by", "created_at", "revoked_at")


class VoiceCursor:
    def __init__(self, db):
        self.db, self.rowcount, self._rows = db, 0, []

    def _set(self, rows):
        self._rows = list(rows)
        self.rowcount = len(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    @staticmethod
    def _sample(row):
        return tuple(row[f] for f in SAMPLE_FIELDS)

    def execute(self, sql, args=()):
        db = self.db
        db.executed.append((sql, args))
        self._set([])
        tag = re.search(r"/\*voice\.([a-z_]+)\*/", sql)
        if tag:
            return getattr(self, "_voice_" + tag.group(1))(args)
        if "FROM public.pr_library_assets WHERE workspace_id=%s AND id=ANY" in sql:
            return self._set([db.row(uuid.UUID(k).hex) for k in args[1] if uuid.UUID(k).hex in db.assets])
        if "SELECT media FROM public.pr_library_assets" in sql:
            key = args[1].hex
            return self._set([(db.assets[key]["media"],)] if key in db.assets else [])
        if "SELECT replace(id::text,'-','') FROM public.pr_library_assets" in sql:
            return self._set([(k,) for k in db.assets if k in (args[1], args[2])])
        if "FROM public.pr_library_segments WHERE workspace_id=%s AND version_key=%s" in sql:
            _, key, history, after, same, after_id, limit = args
            rows = sorted((s for s in db.segments if s["version"] == key and (history or not s["superseded"])
                           and (s["ordinal"] > after or (s["ordinal"] == same and s["id"] > after_id))), key=lambda s: (s["ordinal"], s["id"]))
            return self._set([(s["id"], s["ordinal"], s["kind"], s["text"], s["language"], json.dumps(s["locator"]), s["speaker"], s["origin"], None,
                               "fixture", "1", None, s["superseded"], 1.0) for s in rows[:limit]])
        if sql.startswith("SELECT grant_revision,index_generation,organization_revision FROM public.pr_library_policy"):
            return self._set([(db.grant_revision, 1, 0)])
        if sql.startswith("SELECT grant_revision FROM public.pr_library_policy"):  # policy.recheck (no lock)
            if db.on_share:
                hook, db.on_share = db.on_share, None
                hook(db)
            return self._set([(db.grant_revision,)])
        if sql.startswith("INSERT INTO public.pr_library_policy"):
            db.grant_revision += args[4]
            return self._set([(db.grant_revision, 1, 0)])
        if "FROM public.pr_library_grants WHERE workspace_id=%s AND revoked_at IS NULL ORDER BY" in sql:
            return self._set([(str(g["id"]), g["type"], g["scope"], g["key"], g["members"], g["purpose"], None, None, g["attestation"], ACTOR,
                               g["revision"], 1.0) for g in db.grants if not g["revoked"]])
        if sql.startswith("INSERT INTO public.pr_library_grants"):
            gid, _, gtype, scope, key, members, purpose, _loc, _cat, attestation, _actor, revision = args
            db.grants.append({"id": gid, "type": gtype, "scope": scope, "key": key, "members": members, "purpose": purpose,
                              "attestation": json.loads(attestation), "revision": revision, "revoked": False})
            return self._set([])
        if sql.startswith("SELECT grant_type,scope_kind,scope_key,member_keys,purpose,location,category FROM public.pr_library_grants"):
            return self._set([(g["type"], g["scope"], g["key"], g["members"], g["purpose"], None, None) for g in db.grants
                              if g["id"] == args[1] and not g["revoked"]])
        if sql.startswith("UPDATE public.pr_library_grants SET revoked_at"):
            for g in db.grants:
                if g["id"] == args[3]:
                    g["revoked"] = True
            return self._set([])
        if "pr_audit_events" in sql:
            db.audits.append((args[2], args[3], json.loads(args[4])))
            return self._set([])
        if "FROM public.pr_library_action_receipts" in sql:
            prior = db.receipts.get(args[1])
            return self._set([prior] if prior else [])
        if sql.startswith("INSERT INTO public.pr_library_action_receipts"):
            db.receipts.setdefault(args[1], (args[2], args[4], args[5], json.loads(args[6])))
            return self._set([])
        if "to_regclass('public.pr_post_history')" in sql:
            return self._set([("pr_post_history",)])
        if "to_regclass(" in sql:
            return self._set([(None,)])
        if sql.startswith("UPDATE public.pr_genome_versions SET status='stale'"):
            db.genome_stale += 1
        return None

    # --- voice index -----------------------------------------------------------------------------------------------
    def _voice_insert(self, args):
        (sid, _ws, source_id, asset_key, version_key, sha, locator, text, text_hash, persona, brand, language, polarity, attestation,
         consent, actor) = args
        self.db.clock += 1
        self.db.voice.append({"id": sid, "voice_source_id": source_id, "asset_key": asset_key, "version_key": version_key, "source_sha256": sha,
                              "locator": json.loads(locator), "text": text, "text_hash": text_hash, "persona_id": persona, "brand": brand,
                              "language": language, "polarity": polarity, "attestation": json.loads(attestation), "consent_revision": consent,
                              "status": "approved", "revision": 1, "created_by": actor, "created_at": NOW + self.db.clock, "revoked_at": None})

    def _voice_by_id(self, args):
        self._set([self._sample(r) for r in self.db.voice if r["id"] == args[1]])

    def _voice_by_asset(self, args):
        self._set([self._sample(r) for r in self.db.voice if r["asset_key"] == args[1]])

    def _voice_same_span(self, args):
        _, version_key, locator, persona, brand, language = args
        self._set([self._sample(r) for r in self.db.voice if r["status"] == "approved" and r["version_key"] == version_key
                   and r["locator"] == json.loads(locator) and r["persona_id"] == persona and (r["brand"] or "") == brand and r["language"] == language])

    def _voice_scope(self, args):
        _, persona, brand, languages, limit = args
        rows = [r for r in self.db.voice if r["status"] == "approved" and r["persona_id"] == persona and (r["brand"] or "") == brand and r["language"] in languages]
        self._set([self._sample(r) for r in sorted(rows, key=lambda r: -r["created_at"])[:limit]])

    def _voice_approved(self, args):
        self._set([self._sample(r) for r in self.db.voice if r["status"] == "approved"])

    def _voice_for_keys(self, args):
        keys = None if len(args) == 1 else set(args[1]) | set(args[2])
        self._set([self._sample(r) for r in self.db.voice if r["status"] == "approved" and (keys is None or r["asset_key"] in keys or r["version_key"] in keys)])

    def _voice_revoke(self, args):
        text, actor, _, ids = args
        changed = 0
        for r in self.db.voice:
            if str(r["id"]) in ids and r["status"] == "approved":
                r.update(status="revoked", text=text, revoked_at=NOW, revision=r["revision"] + 1)
                changed += 1
        self.rowcount = changed

    def _voice_workspace_lock(self, args):
        self._set([(self.db.revision, json.dumps(self.db.state))])

    def _voice_workspace_save(self, args):
        self.db.state = json.loads(args[0])
        self.db.revision += 1
        self._set([(self.db.revision,)])


def service(*, growth=False):
    svc = SimpleNamespace(commands=HostedPhase2Commands(clock=lambda: NOW), repository=SimpleNamespace(effects=[]), clock=lambda: NOW)
    if growth:
        svc.growth = GrowthService(svc, env={})  # appends its invalidate hook to repository.effects, as in hosted_app
    return svc


def make_ctx(db, *, role="owner", growth=False):
    return c.LibraryContext(workspace_id=WS, actor=ACTOR, membership=Membership(role), state=copy.deepcopy(db.state), cur=db.cursor(), now=NOW,
                            service=service(growth=growth))


def fixture():
    db = VoiceDB()
    refs = {}
    refs["essay"] = db.asset(ESSAY, title="Practice diary")
    db.add_segments(ESSAY, text_segments(P0, P1, P2))
    refs["interview"] = db.asset(INTERVIEW, kind="audio", media={"durationMs": 20000}, title="Radio interview")
    db.add_segments(INTERVIEW, [
        {"kind": "transcript", "text": "So tell us how you prepare.", "locator": {"kind": "time", "startMs": 0, "endMs": 4000}, "speaker": "Speaker 1", "origin": "transcript"},
        {"kind": "transcript", "text": "I always start with slow practice, hands separately, before I think about tempo.",
         "locator": {"kind": "time", "startMs": 4000, "endMs": 9000}, "speaker": "Speaker 2", "origin": "transcript"},
        {"kind": "transcript", "text": "And on the day itself?", "locator": {"kind": "time", "startMs": 9000, "endMs": 12000}, "speaker": "Speaker 1", "origin": "transcript"},
        {"kind": "transcript", "text": "I keep the morning quiet and play through once.", "locator": {"kind": "time", "startMs": 12000, "endMs": 16000},
         "speaker": "Speaker 2", "origin": "transcript"},
    ])
    refs["link"] = db.asset(LINK, source_kind="link", provenance={"source": "link", "retrievedAt": "2026-10-08T00:00:00Z"}, title="Pianist blog")
    db.add_segments(LINK, text_segments(LINK_TEXT))
    refs["guest"] = db.asset(GUEST_NOTE, source_kind="note", provenance={"source": "note", "authoredByMe": False}, title="Guest quote")
    db.add_segments(GUEST_NOTE, text_segments(GUEST_TEXT))
    refs["artifact"] = db.asset(ARTIFACT, source_kind="artifact", provenance={"source": "artifact", "runId": "run-1"}, title="Rafii draft")
    db.add_segments(ARTIFACT, text_segments(ARTIFACT_TEXT))
    refs["storage"] = db.asset(STORAGE, title="Contract scan")
    db.add_segments(STORAGE, text_segments(STORAGE_TEXT))
    refs["zh"] = db.asset(ZH, source_kind="note", provenance={"source": "note", "authoredByMe": True}, title="練琴筆記")
    db.add_segments(ZH, [{"kind": "text", "text": ZH_TEXT, "language": "yue", "locator": {"kind": "text", "start": 0, "end": len(ZH_TEXT)}}])
    refs["mixed"] = db.asset(MIXED, title="Edited post")
    mixed = text_segments(OWN_LINE, AI_LINE)
    mixed[1]["origin"] = "ai_suggested"
    db.add_segments(MIXED, mixed)
    return db, refs


def approve(db, ref, locator, *, role="owner", persona="default", attestation=WROTE, **kw):
    kw.setdefault("uses", USES)
    kw.setdefault("confirmed", True)
    return voice.approve_voice_span(make_ctx(db, role=role, growth=kw.pop("growth", False)), ref, locator, persona, attestation, **kw)


def envelope(action, ref, payload, key, expected=None):
    return {"actionId": "act-" + key[:8], "uiInstanceId": "library-ui", "actionType": action, "targetRefs": [ref] if ref else [],
            "expectedRevision": expected, "idempotencyKey": "voice-key-" + key, "payload": payload}


def voice_samples(state):
    return [s for s in state.get("sources", []) if s.get("kind") == "voice_sample"]


class Base(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db, self.refs = fixture()

    def refused(self, fn, code, status=None):
        with self.assertRaises(AlphaError) as raised:
            fn()
        self.assertEqual(raised.exception.code, code, str(raised.exception))
        if status is not None:
            self.assertEqual(raised.exception.status, status)
        return raised.exception

    def nothing_admitted(self):
        self.assertEqual(voice_samples(self.db.state), [])
        self.assertEqual(self.db.voice, [])


class AdmissionTests(Base):
    def test_reference_not_voice(self):
        """A044/A007: third-party links, notes the user said they did not write, storage-only files and items whose only
        grant is for another purpose never become voice samples — not even with an authorship claim in the request."""
        db, refs = self.db, self.refs
        self.refused(lambda: approve(db, refs["link"], whole(LINK_TEXT), grant_voice=True), "library_voice_reference", 403)
        self.refused(lambda: approve(db, refs["guest"], whole(GUEST_TEXT), grant_voice=True), "library_voice_reference", 403)
        self.assertEqual([g for g in db.grants if g["purpose"] == "voice"], [], "a refused reference does not create a voice grant")
        # Storage-only: uploaded and browsable, but no voice purpose grant. An answer grant is a different purpose.
        db.grant("answer", STORAGE)
        self.refused(lambda: approve(db, refs["storage"], whole(STORAGE_TEXT)), "library_grant_required", 403)
        # The authorship attestation is required and must be explicit.
        db.grant("voice", ESSAY)
        self.refused(lambda: approve(db, refs["essay"], span(0, [P0, P1, P2]), attestation={"authoredByMe": False, "method": "written_by_me"}),
                     "library_voice_attestation", 422)
        self.refused(lambda: approve(db, refs["essay"], span(0, [P0, P1, P2]), attestation={"authoredByMe": True}), "library_voice_attestation", 422)
        self.nothing_admitted()
        # An explicit claim of own publication is the one way a linked page becomes the user's voice.
        sample = approve(db, refs["link"], whole(LINK_TEXT), grant_voice=True,
                         attestation={"authoredByMe": True, "method": "published_by_me"})
        self.assertEqual(sample["status"], "approved")
        self.assertEqual([g["attestation"]["method"] for g in db.grants if g["purpose"] == "voice" and g["key"] == LINK], ["published_by_me"])

    def test_quoted_guest_speaker_refused(self):
        """A044/A045: only the speaker the user identifies as themselves is admitted; guests and quotations are not."""
        db, refs = self.db, self.refs
        db.grant("voice", INTERVIEW)
        db.grant("voice", ESSAY)
        me = {"authoredByMe": True, "method": "spoken_by_me", "speakerLabel": "Speaker 2"}
        self.refused(lambda: approve(db, refs["interview"], {"kind": "time", "startMs": 0, "endMs": 4000}, attestation=me), "library_voice_other_speaker", 403)
        self.refused(lambda: approve(db, refs["interview"], {"kind": "time", "startMs": 0, "endMs": 9000}, attestation=me), "library_voice_mixed_speakers", 403)
        self.refused(lambda: approve(db, refs["interview"], {"kind": "time", "startMs": 4000, "endMs": 9000},
                                     attestation={"authoredByMe": True, "method": "spoken_by_me"}), "library_voice_speaker_required", 422)
        self.refused(lambda: approve(db, refs["essay"], span(1, [P0, P1, P2])), "library_voice_quoted", 403)
        self.nothing_admitted()
        sample = approve(db, refs["interview"], {"kind": "time", "startMs": 4000, "endMs": 9000}, attestation=me)
        self.assertEqual(sample["text"], "I always start with slow practice, hands separately, before I think about tempo.")
        self.assertEqual(sample["attestation"]["speakerLabel"], "Speaker 2")
        self.assertEqual(sample["locatorLabel"], "0:04–0:09")

    def test_span_not_whole_document(self):
        """A045: a passage at an exact locator is admitted; a missing locator, the whole document or a cut through a
        passage is refused, and nothing outside the span reaches the canonical sample."""
        db, refs = self.db, self.refs
        db.grant("voice", ESSAY)
        db.grant("voice", INTERVIEW)
        self.refused(lambda: approve(db, refs["essay"], None), "library_contract", 400)
        whole = {"kind": "text", "start": 0, "end": sum(len(p) + 2 for p in (P0, P1, P2)) - 2}
        self.refused(lambda: approve(db, refs["essay"], whole), "library_voice_whole_document", 422)
        me = {"authoredByMe": True, "method": "spoken_by_me", "speakerLabel": "Speaker 2"}
        self.refused(lambda: approve(db, refs["interview"], {"kind": "time", "startMs": 5000, "endMs": 9000}, attestation=me), "library_voice_partial", 422)
        self.refused(lambda: approve(db, refs["essay"], {"kind": "sheet", "sheetName": "A", "cellRange": "B4"}), "library_voice_locator", 422)
        self.refused(lambda: approve(db, refs["essay"], {"kind": "text", "start": 5000, "end": 5010}), "library_voice_no_passage", 422)
        self.nothing_admitted()
        # A sentence inside the first paragraph: only that sentence is retained.
        sentence = P0.split(",")[0]
        sample = approve(db, refs["essay"], {"kind": "text", "start": 0, "end": len(sentence)})
        self.assertEqual(sample["text"], sentence)
        [canonical] = voice_samples(db.state)
        self.assertEqual(canonical["text"], sentence)
        self.assertEqual(canonical["voiceOrigin"], "user_provided")
        self.assertEqual(canonical["libraryOrigin"]["assetId"], ESSAY)
        self.assertEqual(canonical["libraryOrigin"]["versionId"], ESSAY)
        self.assertEqual(canonical["libraryOrigin"]["sha256"], refs["essay"]["sha256"])
        self.assertEqual(canonical["libraryOrigin"]["locator"], {"kind": "text", "start": 0, "end": len(sentence)})
        self.assertEqual(sorted(canonical["purposeGrants"]), ["analysis", "generation"], "granted through voice_sample_grant")
        self.assertFalse(canonical["selected"], "selection for the workspace writer stays a separate choice")
        self.assertNotIn(P2, json.dumps(db.state, ensure_ascii=False))
        self.assertEqual(len(db.voice), 1)
        self.assertEqual(db.voice[0]["voice_source_id"], canonical["id"])
        self.assertEqual(db.voice[0]["text_hash"], canonical["contentHash"])
        # Approving the same span again is idempotent: no second canonical sample or index row.
        again = approve(db, refs["essay"], {"kind": "text", "start": 0, "end": len(sentence)})
        self.assertTrue(again["alreadyApproved"])
        self.assertEqual((len(voice_samples(db.state)), len(db.voice)), (1, 1))

    def test_generated_text_requires_approval(self):
        """A044: agent-written text needs its own explicit owner approval; it is labelled as AI-generated if admitted."""
        db, refs = self.db, self.refs
        db.grant("voice", ARTIFACT)
        db.grant("voice", MIXED)
        loc = whole(ARTIFACT_TEXT)
        self.refused(lambda: approve(db, refs["artifact"], loc), "library_voice_generated_needs_approval", 409)
        self.refused(lambda: approve(db, refs["mixed"], span(1, [OWN_LINE, AI_LINE])), "library_voice_generated_needs_approval", 409)
        payload = {"locator": loc, "attestation": WROTE, "uses": USES, "confirmed": True}
        outcome = actions.apply(make_ctx(db), envelope("voice.approve_span", refs["artifact"], payload, "gen-0000000001"))
        self.assertEqual(outcome["status"], "requires_confirmation")
        editor = actions.apply(make_ctx(db, role="editor"), envelope("voice.approve_span", refs["artifact"], {**payload, "approveGeneratedText": True}, "gen-0000000002"))
        self.assertEqual(editor["status"], "denied")
        self.nothing_admitted()
        applied = actions.apply(make_ctx(db), envelope("voice.approve_span", refs["artifact"], {**payload, "approveGeneratedText": True}, "gen-0000000003"))
        self.assertEqual(applied["status"], "applied", applied)
        self.assertTrue(applied["result"]["attestation"]["generatedTextApproved"])
        [canonical] = voice_samples(db.state)
        self.assertEqual(canonical["label"], "ai_generated")
        # The user's own opening line in the edited post is admitted without that approval.
        own = approve(db, refs["mixed"], whole(OWN_LINE))
        self.assertFalse(own["attestation"].get("generatedTextApproved", False))

    def test_toctou_revoke_before_admit(self):
        """A008 path: a revocation committed between the voice check and the write wins; nothing is admitted."""
        db, refs = self.db, self.refs
        db.grant("voice", ESSAY)

        def concurrent_revoke(d):
            for g in d.grants:
                g["revoked"] = True
            d.grant_revision += 1

        db.on_share = concurrent_revoke
        self.refused(lambda: approve(db, refs["essay"], span(0, [P0, P1, P2])), "library_grant_required", 403)
        self.nothing_admitted()

    def test_page_and_slide_locators(self):
        """Structural locators: part of a PDF page passage with exact offsets, a whole page, a slide; a page passage
        without trustworthy inner offsets must be taken whole."""
        db = self.db
        pdf, deck = "7" * 32, "8" * 32
        pdf_ref = db.asset(pdf, title="Programme notes")
        first, second, only = "I chose this sonata for its quiet ending.", "The slow movement is where I breathe.", "Page two text I also wrote."
        db.add_segments(pdf, [{"kind": "page", "text": first, "locator": {"kind": "page", "page": 1, "textStart": 0, "textEnd": len(first)}},
                              {"kind": "page", "text": second, "locator": {"kind": "page", "page": 1, "textStart": len(first) + 1, "textEnd": len(first) + 1 + len(second)}},
                              {"kind": "page", "text": only, "locator": {"kind": "page", "page": 2}}])
        deck_ref = db.asset(deck, title="Talk slides")
        db.add_segments(deck, [{"kind": "slide", "text": "Why I practise slowly", "locator": {"kind": "slide", "slide": 1}},
                               {"kind": "slide", "text": "What I listen for", "locator": {"kind": "slide", "slide": 2}}])
        db.grant("voice", pdf)
        db.grant("voice", deck)
        part = approve(db, pdf_ref, {"kind": "page", "page": 1, "textStart": 0, "textEnd": 21})
        self.assertEqual((part["text"], part["locatorLabel"]), (first[:21], "page 1"))
        page = approve(db, pdf_ref, {"kind": "page", "page": 1})
        self.assertEqual(page["text"], first + "\n\n" + second)
        self.refused(lambda: approve(db, pdf_ref, {"kind": "page", "page": 2, "textStart": 0, "textEnd": 4}), "library_voice_partial", 422)
        slide = approve(db, deck_ref, {"kind": "slide", "slide": 2})
        self.assertEqual((slide["text"], slide["locatorLabel"]), ("What I listen for", "slide 2"))

    def test_reapprove_after_revoke_in_voice_settings(self):
        """A span whose canonical sample was revoked from Brand → Voice is retired, so the owner can approve it afresh."""
        db, refs = self.db, self.refs
        db.grant("voice", ESSAY)
        first = approve(db, refs["essay"], span(0, [P0, P1, P2]))
        db.state = HostedPhase2Commands(clock=lambda: NOW)(db.state, ACTOR, "voice_sample_revoke", {"sourceId": first["voiceSourceId"], "confirmed": True})
        second = approve(db, refs["essay"], span(0, [P0, P1, P2]))
        self.assertFalse(second["alreadyApproved"])
        self.assertNotEqual(second["voiceSourceId"], first["voiceSourceId"])
        self.assertEqual([r["status"] for r in db.voice], ["revoked", "approved"])
        self.assertEqual([s["active"] for s in voice_samples(db.state)], [False, True])

    def test_voice_admission_flag_and_owner_only(self):
        db, refs = self.db, self.refs
        db.grant("voice", ESSAY)
        self.refused(lambda: approve(db, refs["essay"], span(0, [P0, P1, P2]), role="editor"), "library_forbidden", 403)
        with mock.patch.dict(os.environ, {"RAFII_LIBRARY_VOICE_ENABLED": ""}):
            self.refused(lambda: approve(db, refs["essay"], span(0, [P0, P1, P2])), "library_voice_disabled", 403)
        self.refused(lambda: approve(db, refs["essay"], span(0, [P0, P1, P2]), uses=[]), "library_voice_uses", 422)
        self.refused(lambda: approve(db, refs["essay"], span(0, [P0, P1, P2]), confirmed=False), "library_voice_confirm", 422)
        self.refused(lambda: approve(db, refs["essay"], span(0, [P0, P1, P2]), expected_revision=0), "library_grant_conflict", 409)
        self.nothing_admitted()


class IsolationTests(Base):
    def test_brand_language_isolation(self):
        """A046: persona, brand and language scope the examples; another language needs an explicit allowance."""
        db, refs = self.db, self.refs
        for key in (ESSAY, INTERVIEW, ZH):
            db.grant("voice", key)
        mine = approve(db, refs["essay"], span(0, [P0, P1, P2]), language="en")
        teacher = approve(db, refs["interview"], {"kind": "time", "startMs": 12000, "endMs": 16000}, persona="teacher", brand="Studio Au",
                          attestation={"authoredByMe": True, "method": "spoken_by_me", "speakerLabel": "Speaker 2"})
        cantonese = approve(db, refs["zh"], {"kind": "text", "start": 0, "end": len(ZH_TEXT)}, select=True)
        self.assertEqual(cantonese["language"], "yue", "detected from the passage when not given")
        self.refused(lambda: approve(db, refs["interview"], {"kind": "time", "startMs": 4000, "endMs": 9000}, persona="teacher", select=True,
                                     attestation={"authoredByMe": True, "method": "spoken_by_me", "speakerLabel": "Speaker 2"}),
                     "library_voice_select_default_only", 422)
        ctx = make_ctx(db)

        def ids(result):
            return [x["sampleId"] for x in result["positive"]]

        self.assertEqual(ids(voice.style_exemplars(ctx, "default", "en", 6)), [mine["sampleId"]])
        self.assertEqual(ids(voice.style_exemplars(ctx, "teacher", "en", 6)), [], "a brand-scoped persona needs its brand")
        self.assertEqual(ids(voice.style_exemplars(ctx, "teacher", "en", 6, brand="Studio Au")), [teacher["sampleId"]])
        self.assertEqual(ids(voice.style_exemplars(ctx, "default", "yue", 6)), [cantonese["sampleId"]])
        # Explicitly allowed extra languages follow the requested language.
        self.assertEqual(ids(voice.style_exemplars(ctx, "default", "yue", 6, allow_languages=["en"])), [cantonese["sampleId"], mine["sampleId"]])
        self.assertEqual(ids(voice.style_exemplars(ctx, "other", "en", 6)), [])
        example = voice.style_exemplars(ctx, "teacher", "en", 6, brand="Studio Au")["positive"][0]
        self.assertEqual(example["assetRef"], refs["interview"])
        self.assertEqual(example["locator"], {"kind": "time", "startMs": 12000, "endMs": 16000})
        self.assertEqual(example["provenance"]["method"], "spoken_by_me")
        # The workspace writer's default selection (canonical drafting path) only sees what was explicitly selected.
        selected = [s["id"] for s in voice_samples(db.state) if s.get("active") and s.get("selected")]
        self.assertEqual(selected, [cantonese["voiceSourceId"]])
        retrieved = voice_sources.retrieve(db.state, selected, "generation", WRITER)
        self.assertEqual([s["id"] for s in retrieved["samples"]], [cantonese["voiceSourceId"]])
        # A route the sample was not granted for is excluded by the canonical route check.
        self.assertEqual(ids(voice.style_exemplars(ctx, "default", "en", 6, purpose="analysis", route="cloud:other:model")), [])

    def test_negative_example_preserved(self):
        """A045: a "don't write like this" example is kept only in the Library index, never as a canonical sample."""
        db, refs = self.db, self.refs
        db.grant("voice", ESSAY)
        negative = approve(db, refs["essay"], span(2, [P0, P1, P2]), polarity="negative", uses=None)
        self.assertEqual((negative["polarity"], negative["voiceSourceId"]), ("negative", None))
        self.assertEqual(voice_samples(db.state), [], "negatives never enter state.sources")
        self.assertEqual([(r["polarity"], r["voice_source_id"], r["text"]) for r in db.voice], [("negative", None, P2)])
        self.refused(lambda: approve(db, refs["essay"], span(2, [P0, P1, P2])), "library_voice_polarity_conflict", 409)
        positive = approve(db, refs["essay"], span(0, [P0, P1, P2]))
        result = voice.style_exemplars(make_ctx(db), "default", "en", 6)
        self.assertEqual([x["sampleId"] for x in result["negative"]], [negative["sampleId"]])
        self.assertEqual(result["negative"][0]["text"], P2)
        self.assertEqual(result["negative"][0]["locator"], span(2, [P0, P1, P2]))
        self.assertEqual([x["sampleId"] for x in result["positive"]], [positive["sampleId"]])
        self.assertNotIn(P2, [s["text"] for s in voice_samples(db.state)])
        voice.revoke_voice_sample(make_ctx(db), negative["sampleId"], 1)
        self.assertEqual(voice.style_exemplars(make_ctx(db), "default", "en", 6)["negative"], [])


class RevocationTests(Base):
    def _profile_from(self, source_id):
        """Build and approve a derived speaker profile through the canonical commands (Brand → Voice)."""
        commands = HostedPhase2Commands(clock=lambda: NOW)
        state = commands(self.db.state, ACTOR, "voice_profile_analyze", {"sourceIds": [source_id], "route": "local-rules"})
        state["speaker"]["provisional"]["dimensions"][0].setdefault("quotes", []).append({"sourceId": source_id, "text": "slow practice"})
        state = commands(state, ACTOR, "profile_decide", {"decision": "approve"})
        self.db.state = state
        return state

    def test_revoked_sample_removed_from_persistent_summary(self):
        """A047: revocation runs the canonical revoke (speaker profile stale, quotes and example removed, drafts flagged,
        growth genome staled through the repository effect), withdraws the span and future retrieval excludes it."""
        db, refs = self.db, self.refs
        db.grant("voice", INTERVIEW)
        me = {"authoredByMe": True, "method": "spoken_by_me", "speakerLabel": "Speaker 2"}
        sample = approve(db, refs["interview"], {"kind": "time", "startMs": 4000, "endMs": 9000}, attestation=me, select=True)
        source_id = sample["voiceSourceId"]
        state = self._profile_from(source_id)
        revision = memory.active_profile(state)
        self.assertIn(source_id, revision["profile"]["evidenceSourceIds"])
        self.assertEqual(next(f for f in memory.render_files(state) if f["name"] == "VOICE.md")["source"], "From your active voice profile")
        self.assertEqual([s["id"] for s in voice_sources.retrieve(state, [source_id], "generation", WRITER)["samples"]], [source_id])
        summary = voice.summary_http(make_ctx(db), {"params": {}, "query": {}, "body": {}})
        default = next(p for p in summary["personas"] if p["personaId"] == "default")
        self.assertEqual(default["profile"]["status"], "current")

        self.refused(lambda: voice.revoke_voice_sample(make_ctx(db), sample["sampleId"], 9), "library_voice_revision_conflict", 409)
        receipt = voice.revoke_voice_sample(make_ctx(db, growth=True), sample["sampleId"], 1)
        self.assertEqual(receipt["status"], "revoked")
        self.assertEqual(receipt["invalidated"]["speakerRevisions"], [revision["revision"]])
        self.assertTrue(receipt["invalidated"]["activeProfileStale"])
        self.assertEqual(receipt["retrieval"]["canonicalReason"], "revoked")
        self.assertTrue(receipt["retrieval"]["excludedFromFutureRetrieval"])
        self.assertGreaterEqual(receipt["effectsRun"], 1)
        self.assertEqual(db.genome_stale, 1, "GrowthService.invalidate ran in the same command")

        after = db.state
        canonical = next(s for s in voice_samples(after) if s["id"] == source_id)
        self.assertEqual((canonical["active"], canonical["text"], canonical["useGrants"]), (False, "", []))
        stale = memory.active_profile(after)
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["profile"]["writingExample"], "")
        quotes = [q for d in stale["profile"]["dimensions"] for q in d.get("quotes", [])]
        self.assertFalse(any(q.get("sourceId") == source_id for q in quotes))
        voice_file = next(f for f in memory.render_files(after) if f["name"] == "VOICE.md")
        self.assertIn("No active voice profile yet", voice_file["body"])
        self.assertEqual(voice_sources.retrieve(after, [source_id], "generation", WRITER)["samples"], [])
        row = db.voice[0]
        self.assertEqual((row["status"], row["text"], row["revision"]), ("revoked", "(withdrawn)", 2))
        self.assertEqual(voice.style_exemplars(make_ctx(db), "default", "en", 6)["positive"], [])
        summary = voice.summary_http(make_ctx(db), {"params": {}, "query": {}, "body": {}})
        default = next((p for p in summary["personas"] if p["personaId"] == "default"), None)
        self.assertEqual(default["profile"]["status"], "stale")
        self.assertEqual(sum(g["positiveCount"] for g in default["groups"]), 0)
        again = voice.revoke_voice_sample(make_ctx(db), sample["sampleId"], None)
        self.assertTrue(again["alreadyRevoked"])

    def test_withdraw_for_keys_on_voice_grant_revoke(self):
        """Revoking the Library 'voice' grant withdraws every span of that asset the same way (lifecycle hook)."""
        db, refs = self.db, self.refs
        grant_id = db.grant("voice", ESSAY)
        positive = approve(db, refs["essay"], span(0, [P0, P1, P2]), select=True)
        approve(db, refs["essay"], span(2, [P0, P1, P2]), polarity="negative", uses=None)
        receipt = policy.revoke(make_ctx(db), grant_id)
        self.assertEqual(receipt["propagation"]["voiceSpansWithdrawn"], 2)
        self.assertEqual({r["status"] for r in db.voice}, {"revoked"})
        canonical = next(s for s in voice_samples(db.state) if s["id"] == positive["voiceSourceId"])
        self.assertFalse(canonical["active"])
        self.assertEqual(voice_sources.retrieve(db.state, [canonical["id"]], "generation", WRITER)["samples"], [])

    def test_withdraw_keeps_spans_still_covered_by_another_voice_grant(self):
        db, refs = self.db, self.refs
        asset_grant = db.grant("voice", ESSAY)
        db.grant("voice")  # workspace-wide voice permission remains
        approve(db, refs["essay"], span(0, [P0, P1, P2]))
        receipt = policy.revoke(make_ctx(db), asset_grant)
        self.assertEqual(receipt["propagation"]["voiceSpansWithdrawn"], 0)
        self.assertEqual(db.voice[0]["status"], "approved")
        self.assertEqual(voice.withdraw_for_keys(make_ctx(db), [ESSAY], force=True), 1, "deletion withdraws regardless of grants")
        self.assertEqual(db.voice[0]["status"], "revoked")

    def test_revoke_action_envelope(self):
        db, refs = self.db, self.refs
        db.grant("voice", ESSAY)
        sample = approve(db, refs["essay"], span(0, [P0, P1, P2]))
        unconfirmed = envelope("voice.revoke", refs["essay"], {"sampleId": sample["sampleId"]}, "rev-0000000001", expected=1)
        self.refused(lambda: actions.apply(make_ctx(db), unconfirmed), "library_voice_confirm", 422)
        outcome = actions.apply(make_ctx(db), envelope("voice.revoke", refs["essay"], {"sampleId": sample["sampleId"], "confirmed": True}, "rev-0000000002", expected=1))
        self.assertEqual(outcome["status"], "applied", outcome)
        self.assertEqual(outcome["result"]["status"], "revoked")
        other = actions.apply(make_ctx(db), envelope("voice.revoke", refs["storage"], {"sampleId": sample["sampleId"], "confirmed": True}, "rev-0000000003"))
        self.assertEqual(other["status"], "denied", "a sample is revoked only through its own asset")


class ReadTests(Base):
    def test_asset_voice_and_summary_handlers(self):
        db, refs = self.db, self.refs
        db.grant("voice", ESSAY)
        positive = approve(db, refs["essay"], span(0, [P0, P1, P2]))
        negative = approve(db, refs["essay"], span(2, [P0, P1, P2]), polarity="negative", uses=None)
        view = voice.asset_voice_http(make_ctx(db, role="viewer"), {"params": {"key": ESSAY}, "query": {}, "body": {}})
        self.assertEqual([s["sampleId"] for s in view["samples"]], [positive["sampleId"]])
        self.assertEqual([s["sampleId"] for s in view["negatives"]], [negative["sampleId"]])
        self.assertEqual(view["samples"][0]["status"], "approved")
        self.assertTrue(view["voicePermission"]["allowed"])
        self.assertFalse(view["admission"]["canApprove"], "viewers can see but not approve")
        self.assertEqual(view["sourceRole"]["role"], "unattested")
        artifact = voice.asset_voice_http(make_ctx(db), {"params": {"key": ARTIFACT}, "query": {}, "body": {}})
        self.assertEqual(artifact["sourceRole"]["role"], "generated")
        # A sample revoked in Brand → Voice (outside Library) shows as revoked here too.
        commands = HostedPhase2Commands(clock=lambda: NOW)
        db.state = commands(db.state, ACTOR, "voice_sample_revoke", {"sourceId": positive["voiceSourceId"], "confirmed": True})
        view = voice.asset_voice_http(make_ctx(db), {"params": {"key": ESSAY}, "query": {}, "body": {}})
        self.assertEqual((view["samples"][0]["status"], view["samples"][0]["statusReason"]), ("revoked", "revoked_in_voice_settings"))
        summary = voice.summary_http(make_ctx(db), {"params": {}, "query": {}, "body": {}})
        default = next(p for p in summary["personas"] if p["personaId"] == "default")
        group = default["groups"][0]
        self.assertEqual((group["language"], group["positiveCount"], group["negativeCount"]), ("en", 0, 1))
        self.assertEqual(group["examples"][0]["assetRef"]["assetId"], ESSAY)
        self.assertEqual(default["profile"]["status"], "not_built")

    def test_no_unvalidated_voice_score(self):
        """A048: examples, provenance and coverage only — no match percentage, score or confidence anywhere."""
        db, refs = self.db, self.refs
        db.grant("voice", ESSAY)
        outputs = [approve(db, refs["essay"], span(0, [P0, P1, P2])), approve(db, refs["essay"], span(2, [P0, P1, P2]), polarity="negative", uses=None)]
        ctx = make_ctx(db)
        outputs.append(voice.asset_voice_http(ctx, {"params": {"key": ESSAY}, "query": {}, "body": {}}))
        outputs.append(voice.summary_http(ctx, {"params": {}, "query": {}, "body": {}}))
        outputs.append(voice.style_exemplars(ctx, "default", "en", 6))
        outputs.append(voice.revoke_voice_sample(make_ctx(db), outputs[0]["sampleId"], 1))
        banned = re.compile(r"score|percent|match|confidence|similarity|probability|likelihood", re.I)

        def walk(value, path="$"):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertIsNone(banned.search(str(key)), f"{path}.{key}")
                    walk(item, f"{path}.{key}")
            elif isinstance(value, list):
                for n, item in enumerate(value):
                    walk(item, f"{path}[{n}]")
            elif isinstance(value, str):
                self.assertIsNone(re.search(r"\d\s*%", value), f"{path}: {value}")
            elif isinstance(value, float) and path.split(".")[-1] not in ("createdAt", "revokedAt", "approvedAt"):
                self.fail(f"{path}: unexpected fractional value {value}")

        for output in outputs:
            walk(output)
        self.assertNotIn("trained", json.dumps(outputs[-1]).lower().replace("not trained", ""))


if __name__ == "__main__":
    unittest.main()
