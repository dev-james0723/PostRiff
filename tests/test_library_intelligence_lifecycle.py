"""T12 — lifecycle, cost and operational readiness (acceptance A008, A009, A041/A072, A071, A073, A074).

Unit tests of the Python orchestration over an in-memory fake that emulates each tagged statement (`/*lil:*/` lifecycle,
`/*lit:*/` telemetry, `/*lij:*/` jobs). Real SQL is covered by tests/phase2/postgres_library_intelligence_lifecycle.py.
"""
import contextlib
from datetime import datetime, timezone
import io
import json
import logging
import os
import re
import sys
import uuid
from types import ModuleType, SimpleNamespace
from unittest import mock
import unittest

import test_library_intelligence_jobs as jt
from library_intelligence_fakes import ACTOR, WS, FakeCursor, grant
from postriff_alpha.domain import AlphaError
from postriff_phase2.permissions import Membership
from postriff_phase2.library_intelligence import capabilities, contracts as c, cursors, jobs, lifecycle, policy, telemetry
from postriff_phase2.library_intelligence import providers as providers_module
from postriff_phase2.library_assets import UniversalLibrary

PKG = "postriff_phase2.library_intelligence"
A, B, C2, D3, OTHER = "a" * 32, "b" * 32, "c" * 32, "d" * 32, "e" * 32
LEGACY = "f" * 32
ALL_FLAGS = {name: "1" for name in policy.FLAGS.values()}
NO_FLAGS = {name: "" for name in policy.FLAGS.values()}


def _hex(value):
    return jt._hex(value)


def _keys(value):
    return [_hex(v) for v in (value or [])]


class LCDB(jt.FakeDB):
    """The jobs fake plus every derivative table the lifecycle cascade reaches."""

    def __init__(self):
        super().__init__()
        self.index_generation = 1
        self.segments, self.chunks, self.annotations, self.embeddings = [], [], [], []
        self.relations, self.packs, self.suggestions, self.usage = [], [], [], []
        self.items, self.overrides, self.metrics, self.audits = [], [], [], []
        self.paused = False
        self.frozen_schema = False  # True emulates an environment before migration 097

    def connect(self):
        return LCConnection(self)

    def cursor(self):
        return LCCursor(self)

    def add_asset(self, key=jt.DOC, *, created=None, dup=None, summary="Brahms rehearsal", **kw):
        super().add_asset(key, **kw)
        self.seq += 1
        self.assets[key].update(created=created if created is not None else 1000.0 + self.seq, dup=dup, summary=summary, bucket="postriff-library",
                                ws=WS)
        return key


class LCConnection(jt.FakeConnection):
    def cursor(self):
        return LCCursor(self.db)


LTAG = re.compile(r"/\*(lil|lit):([a-z_.]+)\*/")


def iso(epoch):
    return datetime.fromtimestamp(float(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def from_iso(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


class LCCursor(jt.FakeDBCursor):
    def execute(self, sql, args=()):
        db = self.db
        tag = LTAG.search(sql)
        if tag:
            db.statements.append(sql)
            return getattr(self, "_lc_" + tag.group(2).replace(".", "_"))(sql, tuple(args))
        if "lib:embeddings-tombstone" in sql:
            db.statements.append(sql)
            keys, n = set(args["keys"]), 0
            for e in db.embeddings:
                if e["status"] == "active" and (e["asset"] in keys or e["key"] in keys):
                    e["status"] = args["status"]
                    n += 1
            return self._set([], n)
        if "INSERT INTO public.pr_library_policy" in sql:
            db.statements.append(sql)
            grant_inc, index_inc, org_inc = args[4], args[5], args[6]
            db.grant_revision += grant_inc
            db.index_generation += index_inc
            return self._set([(db.grant_revision, db.index_generation, 0)])
        if "FROM public.pr_library_policy" in sql and "grant_revision,index_generation" in sql:
            db.statements.append(sql)
            return self._set([(db.grant_revision, db.index_generation, 0)])
        if "INSERT INTO public.pr_audit_events" in sql:
            db.statements.append(sql)
            db.audits.append(args)
            return self._set([], 1)
        if "SELECT replace(id::text,'-',''),processing_status FROM public.pr_library_assets" in sql:
            db.statements.append(sql)
            return self._set([(k, a["status"]) for k, a in db.assets.items() if a["status"] not in ("deleting", "duplicate")])
        return super().execute(sql, args)

    def _lc_metrics_insert(self, sql, args):
        ws, feature, event, value, dims = args
        self.db.metrics.append({"ws": ws, "feature": feature, "event": event, "value": value, "dims": json.loads(dims), "id": len(self.db.metrics) + 1})
        self._set([], 1)

    # assets ---------------------------------------------------------------------------------------------------------------
    def _lc_asset_lock(self, sql, args):
        a = self.db.assets.get(_hex(args[1]))
        self._set([(a["object"], a["bucket"], a["etag"], a["bytes"], a["mime"], a["ext"], a["kind"], a["status"])] if a else [])

    def _lc_asset_siblings(self, sql, args):
        key = _hex(args[1])
        rows = sorted((a for a in self.db.assets.values() if a.get("dup") == key and a["status"] == "duplicate"), key=lambda a: (a["created"], a["id"]))
        self._set([(a["id"], a["object"]) for a in rows])

    def _lc_asset_rename(self, sql, args):
        name, ws, key = args
        if any(a["object"] == name and a["id"] != _hex(key) for a in self.db.assets.values()):
            raise AssertionError("unique (workspace_id, object_name) violated")
        self.db.assets[_hex(key)]["object"] = name
        self._set([], 1)

    def _lc_asset_promote(self, sql, args):
        name, bucket, etag, size, mime, ext, kind, _kind2, ws, key = args
        if any(a["object"] == name and a["id"] != _hex(key) for a in self.db.assets.values()):
            raise AssertionError("unique (workspace_id, object_name) violated")
        self.db.assets[_hex(key)].update(object=name, bucket=bucket, etag=etag, bytes=size, mime=mime, ext=ext, kind=kind, dup=None, status="queued")
        self._set([], 1)

    def _lc_asset_repoint(self, sql, args):
        new, ws, old, new2 = args
        n = 0
        for a in self.db.assets.values():
            if a.get("dup") == _hex(old) and a["status"] == "duplicate" and a["id"] != _hex(new2):
                a["dup"] = _hex(new)
                n += 1
        self._set([], n)

    def _lc_asset_clear(self, sql, args):
        n = 0
        for k in _keys(args[1]):
            a = self.db.assets.get(k)
            if a and (a["media"] or a.get("summary")):
                a["media"], a["summary"] = {}, None
                n += 1
        self._set([], n)

    def _lc_installed(self, sql, args):
        self._set([(not self.db.frozen_schema,)])

    def _lc_chunks_delete(self, sql, args):
        keys = set(_keys(args[1]))
        before = len(self.db.chunks)
        self.db.chunks = [x for x in self.db.chunks if x["asset"] not in keys]
        self._set([], before - len(self.db.chunks))

    # jobs/capabilities --------------------------------------------------------------------------------------------------
    def _lc_jobs_cancel(self, sql, args):
        code, ws, keys = args
        n = 0
        for j in self.db.jobs.values():
            if j["key"] in keys and j["status"] in ("queued", "processing"):
                j.update(status="cancelled", category="cancelled", code=code, lease=None, lease_exp=None)
                n += 1
        self._set([], n)

    def _lc_caps_delete(self, sql, args):
        ws, keys = args
        gone = [k for k in self.db.caps if k[1] in keys]
        for k in gone:
            del self.db.caps[k]
        self._set([], len(gone))

    def _lc_caps_withdraw(self, sql, args):
        code, detail, ws, keys = args
        n = 0
        for (w, k, cap), row in self.db.caps.items():
            if k in keys and row["state"] != "not_requested":
                row.update(state="blocked_permission", error_code=code, detail=detail, retryable=False, progress=None)
                n += 1
        self._set([], n)

    # derivatives ----------------------------------------------------------------------------------------------------------
    def _drop(self, table, keys, field="key"):
        rows = getattr(self.db, table)
        kept = [r for r in rows if r[field] not in keys]
        setattr(self.db, table, kept)
        self._set([], len(rows) - len(kept))

    def _lc_segments_delete(self, sql, args):
        self._drop("segments", args[1])

    def _lc_segments_supersede(self, sql, args):
        n = 0
        for s in self.db.segments:
            if s["key"] in args[1] and not s["superseded"]:
                s["superseded"] = True
                n += 1
        self._set([], n)

    def _lc_annotations_delete(self, sql, args):
        self._drop("annotations", args[1])

    def _lc_annotations_deactivate(self, sql, args):
        n = 0
        for a in self.db.annotations:
            if a["key"] in args[1] and a["active"]:
                a["active"] = False
                n += 1
        self._set([], n)

    def _lc_embeddings_delete(self, sql, args):
        self._drop("embeddings", args[1])

    def _lc_embeddings_revoke(self, sql, args):
        n = 0
        for e in self.db.embeddings:
            if e["key"] in args[1] and e["status"] == "active":
                e["status"] = "revoked"
                n += 1
        self._set([], n)

    def _lc_lineage_others(self, sql, args):
        ws, lineages, keys = args
        lineages = set(_keys(lineages))
        n = sum(1 for a in self.db.assets.values() if a.get("lineage") in lineages and a["id"] not in keys and a["status"] not in ("deleting", "duplicate"))
        self._set([(n,)])

    def _touches(self, r, keys):
        return r["from_version"] in keys or (r["to_kind"] == "asset" and r["to_version"] in keys)

    def _lc_relations_drop(self, sql, args):
        ws, keys, _ = args
        before = len(self.db.relations)
        self.db.relations = [r for r in self.db.relations if not (r["relation"] == "similar_to" and self._touches(r, keys))]
        self._set([], before - len(self.db.relations))

    def _lc_relations_stale(self, sql, args):
        evidence, ws, keys, _ = args
        n = 0
        for r in self.db.relations:
            if r["relation"] != "similar_to" and r["status"] in ("active", "suggested") and self._touches(r, keys):
                r["status"] = "stale"
                r["evidence"] = {**r["evidence"], **json.loads(evidence)}
                n += 1
        self._set([], n)

    def _lc_packs_revoke(self, sql, args):
        warning, ws, needle, _ = args
        n = 0
        for p in self.db.packs:
            if p["status"] in ("draft", "attached") and (needle in json.dumps(p["evidence_refs"]) or needle in json.dumps(p["style_refs"])):
                p["status"] = "revoked"
                p["rights_warnings"] = p["rights_warnings"] + json.loads(warning)
                n += 1
        self._set([], n)

    def _lc_suggestions_suppress(self, sql, args):
        ws, keys, _ = args
        n = 0
        for s in self.db.suggestions:
            text = json.dumps(s["candidate_refs"]) + json.dumps(s["affected"])
            if s["state"] in ("new", "seen", "snoozed") and any(re.search(k, text) for k in keys):
                s["state"] = "suppressed"
                n += 1
        self._set([], n)

    def _lc_collections_items(self, sql, args):
        self._drop("items", args[1])

    def _lc_collections_overrides(self, sql, args):
        self._drop("overrides", args[1])

    def _lc_usage_anonymize(self, sql, args):
        source, ws, keys, _ = args
        n = 0
        for u in self.db.usage:
            if u["key"] in keys or (u["key"] is None and u["asset"] in keys):
                u.update(segment=None, source=json.loads(source))
                n += 1
        self._set([], n)

    # revocation -----------------------------------------------------------------------------------------------------------
    def _lc_rev_keys(self, sql, args):
        ws, key, _ = args
        self._set([(k,) for k, a in self.db.assets.items() if k == key or a.get("lineage") == key])

    def _scope(self, sql, args, first, *, both=False):
        rest = list(args[first:])
        keys = None
        if both and "AND (asset_key=ANY(%s) OR version_key=ANY(%s))" in sql:
            keys = rest.pop(0)
            rest.pop(0)
        elif not both and "AND asset_key=ANY(%s)" in sql:
            keys = rest.pop(0)
        excluded = rest.pop(0) if "AND NOT (" in sql else []
        return keys, set(excluded)

    def _lc_rev_jobs(self, sql, args):
        caps, (keys, excluded) = args[1], self._scope(sql, args, 2)
        n = 0
        for j in self.db.jobs.values():
            if j["status"] in ("queued", "processing") and j["capability"] in caps and (keys is None or j["key"] in keys) and j["key"] not in excluded:
                j.update(status="cancelled", category="permission", code="grant_revoked", lease=None)
                n += 1
        self._set([], n)

    def _lc_rev_caps(self, sql, args):
        caps, (keys, excluded) = args[1], self._scope(sql, args, 2)
        n = 0
        for (w, k, cap), row in self.db.caps.items():
            if row["state"] in ("queued", "processing") and cap in caps and (keys is None or k in keys) and k not in excluded:
                row.update(state="blocked_permission", error_code="grant_revoked", retryable=False)
                n += 1
        self._set([], n)

    def _lc_rev_embeddings(self, sql, args):
        modality, (keys, excluded) = args[1], self._scope(sql, args, 2, both=True)
        out = []
        for e in self.db.embeddings:
            if (e["status"] == "active" and e["modality"] in modality and not e["model"].startswith("local/")
                    and (keys is None or e["asset"] in keys or e["key"] in keys) and e["key"] not in excluded):
                e["status"] = "revoked"
                out.append((e["key"], e["modality"]))
        self._set(out)

    def _lc_rev_ready(self, sql, args):
        detail, ws, keys, capability, modality = args
        n = 0
        for (w, k, cap), row in self.db.caps.items():
            if (k in keys and cap == capability and row["state"] in ("ready", "partial")
                    and not any(e["key"] == k and e["modality"] == modality and e["status"] == "active" for e in self.db.embeddings)):
                row.update(state="blocked_permission", error_code="grant_revoked", detail=detail, retryable=False)
                n += 1
        self._set([], n)

    def _lc_rev_packs(self, sql, args):
        keys = list(args[1]) if len(args) > 1 else None
        n = 0
        for p in self.db.packs:
            text = json.dumps(p["evidence_refs"]) + json.dumps(p["style_refs"])
            if p["status"] in ("draft", "attached") and (keys is None or any(re.search(k, text) for k in keys)):
                p["status"] = "revoked"
                n += 1
        self._set([], n)

    def _lc_rev_suggestions(self, sql, args):
        keys = list(args[1]) if len(args) > 1 else None
        n = 0
        for s in self.db.suggestions:
            if s["state"] in ("new", "seen", "snoozed") and (keys is None or any(re.search(k, json.dumps(s["candidate_refs"])) for k in keys)):
                s["state"] = "suppressed"
                n += 1
        self._set([], n)

    # backfill and generations -------------------------------------------------------------------------------------------
    def _lc_backfill_workspaces(self, sql, args):
        only, _, after, _, limit = args
        self._set([(WS,)] if (only in (None, WS)) and (after is None or WS >= after) and not self.db.frozen else [])

    def _lc_backfill_normalized(self, sql, args):
        ws, after_at, after_id, limit = args
        rows = sorted((a for a in self.db.assets.values() if a["status"] in ("ready", "unsupported")), key=lambda a: (a["created"], a["id"]))
        rows = [a for a in rows if (a["created"], a["id"]) > (from_iso(after_at), _hex(after_id))]
        self._set([(a["id"], iso(a["created"])) for a in rows[:limit]])

    def _lc_backfill_queued(self, sql, args):
        self._set([(sum(1 for j in self.db.jobs.values() if j["status"] == "queued"),)])

    def _lc_backfill_checkpoint(self, sql, args):
        found = [m for m in self.db.metrics if m["feature"] == "library.backfill" and m["event"] == "checkpoint" and m["dims"].get("scope") == args[0]]
        self._set([(found[-1]["dims"],)] if found else [])

    def _lc_generation_set(self, sql, args):
        self.db.index_generation = args[0]
        self._set([(self.db.grant_revision, self.db.index_generation, 0)])

    def _lc_generation_vectors(self, sql, args):
        counts = {}
        for e in self.db.embeddings:
            if e["status"] == "active":
                counts[e["gen"]] = counts.get(e["gen"], 0) + 1
        self._set(sorted(counts.items()))

    # status ---------------------------------------------------------------------------------------------------------------
    def _lc_status_queue(self, sql, args):
        jobs_ = list(self.db.jobs.values())
        queued = [j for j in jobs_ if j["status"] == "queued"]
        oldest = (self.db.now - min(j["created"] for j in queued)) if queued else None
        stale = sum(1 for j in jobs_ if j["status"] == "processing" and (j["lease_exp"] or 0) < self.db.now)
        self._set([(len(queued), sum(1 for j in jobs_ if j["status"] == "processing"), sum(1 for j in jobs_ if j["status"] == "failed"), oldest, stale)])

    def _lc_status_caps(self, sql, args):
        self._set([(k, cap, row["state"]) for (w, k, cap), row in self.db.caps.items()])

    def _lc_status_costs(self, sql, args):
        actual = estimated = unknown = 0
        for j in self.db.jobs.values():
            for entry in ((j["cost"] or {}).get("byAttempt") or {}).values():
                if entry.get("kind") == "actual":
                    actual += entry["usdMicro"]
                elif entry.get("kind") == "estimated":
                    estimated += entry["usdMicro"]
                elif entry.get("kind") == "unknown":
                    unknown += 1
        self._set([(actual, estimated, unknown)])

    def _lc_status_ai_table(self, sql, args):
        self._set([(False,)])


def ctx_for(db, role="owner", service=None, state=None):
    return c.LibraryContext(workspace_id=WS, actor=ACTOR, membership=Membership(role), state=state if state is not None else db.state,
                            cur=db.cursor(), now=db.now, service=service)


class FakeVoice:
    def __init__(self):
        self.calls = []

    def module(self):
        voice = ModuleType(PKG + ".voice")

        def withdraw_for_keys(ctx, keys, *, force=False):
            self.calls.append((None if keys is None else list(keys), force))
            return 0 if keys is None else len(keys)
        voice.withdraw_for_keys = withdraw_for_keys
        return voice


class Base(unittest.TestCase):
    flags = ALL_FLAGS

    def setUp(self):
        self.db = LCDB()
        self.storage = jt.FakeStorage(self.db)
        self.library = jt.FakeLibrary(self.storage)
        self.service = SimpleNamespace(library=self.library, library_intelligence=SimpleNamespace(providers=providers_module.Providers(environ={})))
        self.intel = SimpleNamespace(service=self.service, providers=SimpleNamespace(name="fake-providers"))
        self.voice = FakeVoice()
        self.writer_calls, modules = jt.writer_modules()
        modules[PKG + ".voice"] = self.voice.module()
        patches = [mock.patch.dict(capabilities.PROCESSORS, clear=True), mock.patch.object(capabilities, "PROCESSOR_MODULES", ()),
                   mock.patch.object(capabilities, "_loaded", True), mock.patch.dict(os.environ, self.flags), mock.patch.dict(sys.modules, modules)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("RAFII_LIBRARY_BACKFILL_PAUSED", None)

    def tick(self):
        return jobs.tick(self.intel, self.db.connect, max_jobs=10, max_seconds=30.0)


def seed_derivatives(db, key, *, asset=None, tag=""):
    asset = asset or key
    db.segments += [{"key": key, "asset": asset, "superseded": False, "text": "Brahms " + tag}, {"key": key, "asset": asset, "superseded": True, "text": "old"}]
    db.chunks.append({"asset": key, "text": "Brahms rehearsal notes " + tag})
    db.annotations += [{"key": key, "active": True, "field": "topic"}, {"key": key, "active": True, "field": "user_title"}]
    db.embeddings += [{"key": key, "asset": asset, "modality": "visual", "model": "local/visual-perceptual-v1", "status": "active", "gen": 1},
                      {"key": key, "asset": asset, "modality": "text", "model": "openai/text-embedding-3-large", "status": "active", "gen": 1}]


class Deletion(Base):
    def seed(self):
        self.db.add_asset(A, created=1.0)
        self.db.assets[A]["media"] = {"peaks": [0.1, 0.9], "peaksSource": "server_decoded", "durationMs": 1200}
        self.db.add_asset(C2, created=2.0, lineage=A)  # a newer version of the same asset stays untouched
        seed_derivatives(self.db, A)
        seed_derivatives(self.db, C2, asset=A, tag="v2")
        for cap, state in (("extract", "ready"), ("preview", "ready")):
            capabilities.set_state(self.db.cursor(), WS, A, cap, state)
        capabilities.set_state(self.db.cursor(), WS, C2, "extract", "ready")
        for status in ("queued", "processing", "completed"):
            jid = uuid.uuid4().hex
            self.db.jobs[jid] = {"id": jid, "ws": WS, "key": A, "capability": "extract", "pv": "v", "consent": 0, "idem": jid, "status": status,
                                 "attempts": 1, "max": 3, "lease": "x" if status == "processing" else None, "lease_exp": self.db.now + 99,
                                 "next_at": self.db.now, "reservation": None, "cost": None, "category": None, "code": None, "requested_by": None,
                                 "created": self.db.now, "finished": None, "timings": {}, "cleanup": None}
        self.db.relations += [
            {"from_version": A, "to_kind": "draft", "to_version": None, "relation": "used_in", "status": "active", "evidence": {}},
            {"from_version": A, "to_kind": "asset", "to_version": C2, "relation": "similar_to", "status": "suggested", "evidence": {}},
            {"from_version": C2, "to_kind": "asset", "to_version": A, "relation": "version_of", "status": "active", "evidence": {}},
            {"from_version": C2, "to_kind": "draft", "to_version": None, "relation": "used_in", "status": "active", "evidence": {}}]
        ref = {"assetRef": {"assetId": A, "versionId": A, "sha256": jt.SHA}}
        self.db.packs += [{"status": "attached", "evidence_refs": [ref], "style_refs": [], "rights_warnings": []},
                          {"status": "draft", "evidence_refs": [{"assetRef": {"assetId": A, "versionId": C2, "sha256": jt.SHA}}], "style_refs": [], "rights_warnings": []}]
        self.db.suggestions += [{"state": "new", "candidate_refs": [ref], "affected": []}, {"state": "new", "candidate_refs": [], "affected": []}]
        self.db.items += [{"key": A, "collection": "x"}, {"key": C2, "collection": "x"}]
        self.db.overrides += [{"key": A, "mode": "exclude"}]
        self.db.usage += [{"key": A, "asset": A, "segment": "s1", "source": {"title": "Spring recital notes"}},
                          {"key": C2, "asset": A, "segment": "s2", "source": {"title": "kept"}}]

    def test_delete_cascades_segments_vectors_previews(self):
        self.seed()
        receipt = lifecycle.on_source_deleted(self.db.cursor(), WS, A, actor=ACTOR, service=self.service)
        self.assertEqual([s for s in self.db.segments if s["key"] == A], [], "segments of the deleted version are gone")
        self.assertEqual(len([s for s in self.db.segments if s["key"] == C2]), 2, "another version keeps its segments")
        self.assertEqual([x for x in self.db.chunks if x["asset"] == A], [])
        self.assertEqual([x for x in self.db.annotations if x["key"] == A], [])
        self.assertEqual([e for e in self.db.embeddings if e["key"] == A], [], "local and cloud vectors are removed")
        self.assertEqual(sorted(e["status"] for e in self.db.embeddings if e["key"] == C2), ["active", "active"])
        self.assertEqual(self.db.assets[A]["media"], {}, "cached peaks/preview facts are cleared")
        self.assertIsNone(self.db.assets[A]["summary"])
        self.assertIsNone(self.db.cap(A, "extract"))
        self.assertEqual(self.db.cap(C2, "extract")["state"], "ready")
        self.assertEqual(sorted(j["status"] for j in self.db.jobs.values()), ["cancelled", "cancelled", "completed"])
        self.assertTrue(all(j["code"] == "library_source_deleted" for j in self.db.jobs.values() if j["status"] == "cancelled"))
        relations = {(r["from_version"], r["relation"]): r for r in self.db.relations}
        self.assertNotIn((A, "similar_to"), relations, "similarity suggestions to a deleted item are dropped")
        self.assertEqual(relations[(A, "used_in")]["status"], "stale")
        self.assertTrue(relations[(A, "used_in")]["evidence"]["sourceDeleted"])
        self.assertEqual(relations[(C2, "version_of")]["status"], "stale", "lineage stays recorded, marked stale")
        self.assertEqual(relations[(C2, "used_in")]["status"], "active")
        self.assertEqual(self.db.packs[0]["status"], "revoked")
        self.assertEqual(self.db.packs[0]["evidence_refs"][0]["assetRef"]["versionId"], A, "pack refs are never rewritten")
        self.assertEqual(self.db.packs[0]["rights_warnings"], [{"code": "source_deleted", "versionId": A}])
        self.assertEqual(self.db.packs[1]["status"], "draft")
        self.assertEqual([s["state"] for s in self.db.suggestions], ["suppressed", "new"])
        self.assertEqual([i["key"] for i in self.db.items], [C2])
        self.assertEqual(self.db.overrides, [])
        self.assertEqual(self.db.usage[0], {"key": A, "asset": A, "segment": None, "source": {"sourceDeleted": True}})
        self.assertEqual(self.db.usage[1]["segment"], "s2")
        self.assertEqual(self.voice.calls, [([A], True)], "voice spans are withdrawn with force on deletion")
        for name, expected in (("segmentsDeleted", 2), ("embeddingsDeleted", 2), ("annotationsDeleted", 2), ("jobsCancelled", 2),
                               ("packsRevoked", 1), ("suggestionsSuppressed", 1), ("collectionItemsRemoved", 1), ("overridesRemoved", 1),
                               ("usageAnonymized", 1), ("relationsRemoved", 1), ("relationsStale", 2), ("previewsCleared", 1), ("voiceSpansWithdrawn", 1)):
            self.assertEqual(receipt[name], expected, name)
        self.assertIn("300", receipt["residual"])
        metric = [m for m in self.db.metrics if m["feature"] == "library.lifecycle"]
        self.assertEqual(metric[0]["event"], "deleted")
        self.assertNotIn("Brahms", json.dumps(metric))

    def test_duplicate_sibling_survives(self):
        self.db.add_asset(A, created=1.0)
        self.db.add_asset(B, created=2.0, dup=A, status="duplicate")
        self.db.add_asset(D3, created=3.0, dup=A, status="duplicate")
        original = self.db.assets[A]["object"]
        b_old = self.db.assets[B]["object"]
        self.storage.objects[(WS, original)] = (jt.RAW, "text/markdown")
        self.storage.objects[(WS, b_old)] = (jt.RAW, "text/markdown")
        receipt = lifecycle.on_source_deleted(self.db.cursor(), WS, A, actor=ACTOR, service=self.service)
        sibling = receipt["sibling"]
        self.assertEqual(sibling["promoted"], B)
        self.assertTrue(sibling["originalKept"])
        self.assertEqual(sibling["objectToDelete"], b_old)
        self.assertEqual(self.db.assets[B]["object"], original, "the surviving copy keeps the original bytes")
        self.assertEqual((self.db.assets[B]["status"], self.db.assets[B]["dup"]), ("queued", None))
        self.assertEqual(self.db.assets[A]["object"], b_old, "the deleted row now names only the redundant copy")
        self.assertEqual(self.db.assets[D3]["dup"], B, "other duplicates point at the new canonical copy")
        # The patched library_assets.delete removes only the object the receipt names.
        self.storage.delete(WS, "file", sibling["objectToDelete"])
        self.assertIn((WS, original), self.storage.objects, "original bytes survive while a sibling references them")
        # Without siblings the item's own object is the one to delete.
        self.db.add_asset(OTHER, created=4.0)
        alone = lifecycle.on_source_deleted(self.db.cursor(), WS, OTHER, actor=ACTOR, service=self.service)["sibling"]
        self.assertEqual((alone["promoted"], alone["objectToDelete"], alone["originalKept"]), (None, self.db.assets[OTHER]["object"], False))

    def test_legacy_media_cascade_keyed_by_id(self):
        self.db.state["phase2"]["assets"].append({"id": LEGACY, "mime": "image/jpeg", "hash": "f" * 64, "objectName": f"{LEGACY}-{'f' * 64}.jpg"})
        seed_derivatives(self.db, LEGACY)
        capabilities.set_state(self.db.cursor(), WS, LEGACY, "embed_visual", "ready")
        receipt = lifecycle.on_source_deleted(self.db.cursor(), WS, LEGACY, actor=ACTOR, service=self.service)
        self.assertEqual((receipt["embeddingsDeleted"], receipt["sibling"]["objectToDelete"]), (2, None))
        self.assertIsNone(self.db.cap(LEGACY, "embed_visual"))

    def test_revoke_mode_withdraws_without_deleting(self):
        self.seed()
        receipt = lifecycle.revoke_or_delete_source(ctx_for(self.db, service=self.service), {"assetId": A, "versionId": C2, "sha256": jt.SHA}, mode="revoke")
        self.assertEqual(receipt["mode"], "revoke")
        self.assertTrue(all(s["superseded"] for s in self.db.segments if s["key"] == C2), "segments are tombstoned, not deleted")
        self.assertEqual(sorted(e["status"] for e in self.db.embeddings if e["key"] == C2), ["revoked", "revoked"])
        self.assertEqual(sorted(e["status"] for e in self.db.embeddings if e["key"] == A), ["active", "active"], "the other version is untouched")
        self.assertEqual(self.db.cap(C2, "extract")["state"], "blocked_permission")
        self.assertEqual([i["key"] for i in self.db.items], [A, C2], "storage organization stays")

    def test_before_migration_097_only_handoff_runs(self):
        self.db.add_asset(A, created=1.0)
        self.db.add_asset(B, created=2.0, dup=A, status="duplicate")
        self.db.frozen_schema = True
        receipt = lifecycle.on_source_deleted(self.db.cursor(), WS, A, actor=ACTOR, service=self.service)
        self.assertEqual((receipt["intelligence"], receipt["sibling"]["promoted"]), ("not_installed", B))
        self.assertEqual(self.voice.calls, [])

    def test_voice_import_guarded(self):
        self.db.add_asset(A)
        with mock.patch.dict(sys.modules, {PKG + ".voice": None}):
            receipt = lifecycle.on_source_deleted(self.db.cursor(), WS, A, actor=ACTOR, service=self.service)
        self.assertEqual(receipt["voiceSpansWithdrawn"], "unavailable")


class Revocation(Base):
    def test_grant_revocation_during_job(self):
        """A008: the grant is revoked after the claim and before finalize; nothing is written."""
        self.db.add_asset(A)
        self.db.grants.append(grant(location="cloud", category="embedding"))
        cloud_grant = {"grantType": "processing", "location": "cloud", "category": "embedding", "purpose": None, "scope": {"kind": "workspace"}}

        def revoke_mid_job(job):
            self.db.grants.clear()
            self.db.grant_revision += 1
            lifecycle.propagate_revocation(ctx_for(self.db), cloud_grant)
            return {"state": "ready", "embeddings": [{"modality": "text", "modelId": "m", "dims": 8, "vector": [1.0] * 8}],
                    "provider": {"provider": "gateway", "model": "m", "cost": {"kind": "actual", "usdMicro": 50}}}
        jt.processor("embed_text", "cloud-text-1", location="cloud", category="embedding", run=revoke_mid_job, estimate=lambda job: 100)
        settle = mock.Mock(return_value={"state": "actual"})
        with mock.patch.object(providers_module, "reserve", mock.Mock(return_value={"status": "reserved", "reservationId": "r1", "duplicate": False})), \
                mock.patch.object(providers_module, "settle", settle):
            jobs.enqueue_capability(ctx_for(self.db, service=self.service), {"assetId": A, "versionId": A, "sha256": jt.SHA}, "embed_text", "cloud-text-1")
            self.tick()
        self.assertEqual(self.writer_calls["embeddings"], [], "no derivative after the revocation")
        self.assertEqual(self.db.cap(A, "embed_text")["state"], "blocked_permission")
        self.assertEqual(self.db.job_by_cap("embed_text")["status"], "cancelled")
        settle.assert_called_once()
        self.assertEqual(self.db.job_by_cap("embed_text")["cost"]["byAttempt"]["1"], {"kind": "actual", "usdMicro": 50},
                         "the provider still ran; its cost is recorded, not hidden")

    def test_revoked_embeddings_move_ready_capability(self):
        self.db.add_asset(A)
        seed_derivatives(self.db, A)
        capabilities.set_state(self.db.cursor(), WS, A, "embed_text", "ready")
        capabilities.set_state(self.db.cursor(), WS, A, "embed_visual", "ready")
        receipt = lifecycle.propagate_revocation(ctx_for(self.db), {"grantType": "processing", "location": "cloud", "category": "embedding",
                                                                   "purpose": None, "scope": {"kind": "workspace"}})
        self.assertEqual(receipt["embeddingsRevoked"], 1)
        self.assertEqual(self.db.cap(A, "embed_text")["state"], "blocked_permission")
        self.assertEqual(self.db.cap(A, "embed_visual")["state"], "ready", "local perceptual vectors are not cloud egress and stay")
        self.assertEqual(receipt["capabilitiesWithdrawn"], 1)

    def test_cached_views_packs_and_voice_stop(self):
        """A009: cursors issued before a revocation are refused, packs stop, voice retrieval withdraws; residual window documented."""
        request = {"query": "brahms", "scope": {"kind": "workspace"}, "purpose": "answer"}
        before = cursors.binding(workspace_id=WS, actor=ACTOR, request=request, index_generation=1, grant_revision=1, normalizer_version=1, ranking_version="r")
        token = cursors.encode(binding_digest=before, snapshot=self.db.now, offset=30, fingerprint_value="f" * 24, query_id="q1")
        after = cursors.binding(workspace_id=WS, actor=ACTOR, request=request, index_generation=1, grant_revision=2, normalizer_version=1, ranking_version="r")
        with self.assertRaises(AlphaError) as stale:
            cursors.decode(token, binding_digest=after, now=self.db.now)
        self.assertEqual(stale.exception.code, "library_cursor_stale")
        self.db.add_asset(A)
        ref = {"assetRef": {"assetId": A, "versionId": A, "sha256": jt.SHA}}
        self.db.packs += [{"status": "attached", "evidence_refs": [ref], "style_refs": [], "rights_warnings": []},
                          {"status": "draft", "evidence_refs": [], "style_refs": [ref], "rights_warnings": []}]
        self.db.suggestions.append({"state": "seen", "candidate_refs": [ref], "affected": []})
        answer = lifecycle.propagate_revocation(ctx_for(self.db), {"grantType": "purpose", "purpose": "answer", "location": None, "category": None,
                                                                  "scope": {"kind": "asset", "key": A, "members": []}})
        self.assertEqual([p["status"] for p in self.db.packs], ["revoked", "revoked"])
        self.assertEqual((answer["packsRevoked"], answer["suggestionsSuppressed"]), (2, 1))
        voice = lifecycle.propagate_revocation(ctx_for(self.db), {"grantType": "purpose", "purpose": "voice", "location": None, "category": None,
                                                                 "scope": {"kind": "workspace"}})
        self.assertEqual(self.voice.calls[-1], (None, False), "a voice grant revocation withdraws spans no other grant covers")
        self.assertIn("300", voice["residual"])


class ReviewFixes(Base):
    """Shared security review #4, #5, #9, #10, #12."""

    def cloud_job(self, run, category="embedding", capability="embed_text"):
        self.db.add_asset(A)
        self.db.grants.append(grant(location="cloud", category=category))
        jt.processor(capability, "cloud-1", location="cloud", category=category, run=run, estimate=lambda job: 100)
        return mock.patch.object(providers_module, "reserve", mock.Mock(return_value={"status": "reserved", "reservationId": "r1", "duplicate": False})), \
            mock.patch.object(providers_module, "settle", mock.Mock(return_value={"state": "released"}))

    def test_recheck_before_provider_call(self):
        """#4: a processor re-authorizes immediately before each provider call; a revocation in between stops it."""
        seen, calls = {}, []

        def run(job):
            seen["first"] = job.recheck()
            self.db.grants.clear()
            self.db.grant_revision += 1
            seen["second"] = job.recheck()
            if seen["second"]:
                calls.append("provider")
            return {"state": "failed", "errorCode": "library_grant_revoked", "charged": False} if not seen["second"] else {"state": "ready"}
        reserve, settle = self.cloud_job(run)
        with reserve, settle:
            jobs.enqueue_capability(ctx_for(self.db, service=self.service), {"assetId": A, "versionId": A, "sha256": jt.SHA}, "embed_text", "cloud-1")
            self.tick()
        self.assertEqual((seen["first"], seen["second"], calls), (True, False, []))
        self.assertEqual(self.db.cap(A, "embed_text")["state"], "blocked_permission")
        self.assertGreater(jobs.LEASE_SECONDS, jobs.LONGEST_PROVIDER_TIMEOUT, "a long ASR call can never outlive its lease")

    def test_recheck_heartbeats_and_fails_when_cancelled(self):
        seen = {}

        def run(job):
            self.db.now += 100
            seen["ok"] = job.recheck()
            seen["lease"] = self.db.job_by_cap("extract")["lease_exp"]
            jobs.cancel(ctx_for(self.db, service=self.service), A, ["extract"])
            seen["after_cancel"] = job.recheck()
            return {"state": "ready"}
        self.db.add_asset(A)
        jt.processor(run=run)
        jobs.enqueue_capability(ctx_for(self.db, service=self.service), {"assetId": A, "versionId": A, "sha256": jt.SHA}, "extract", "test-extract-1")
        self.tick()
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["lease"], self.db.now + jobs.LEASE_SECONDS)
        self.assertFalse(seen["after_cancel"])

    def test_collection_scope_matches_version_keys(self):
        """#5: collection members are VERSION keys; embeddings carry the lineage in asset_key."""
        self.db.add_asset(A)
        self.db.add_asset(C2, lineage=A)
        seed_derivatives(self.db, A)
        seed_derivatives(self.db, C2, asset=A, tag="v2")
        capabilities.set_state(self.db.cursor(), WS, C2, "embed_text", "ready")
        receipt = lifecycle.propagate_revocation(ctx_for(self.db), {"grantType": "processing", "location": "cloud", "category": "embedding", "purpose": None,
                                                                   "scope": {"kind": "collection", "key": "1" * 32, "members": [C2]}})
        status = {(e["key"], e["model"]): e["status"] for e in self.db.embeddings}
        self.assertEqual(status[(C2, "openai/text-embedding-3-large")], "revoked")
        self.assertEqual(status[(A, "openai/text-embedding-3-large")], "active", "the other version of the lineage is not in the collection grant")
        self.assertEqual(receipt["embeddingsRevoked"], 1)
        self.assertEqual(self.db.cap(C2, "embed_text")["state"], "blocked_permission")

    def test_revocation_skips_keys_still_covered(self):
        """#10: revoking one grant narrows the scope; items another active grant still covers keep their derivatives."""
        self.db.add_asset(A)
        self.db.add_asset(B)
        seed_derivatives(self.db, A)
        seed_derivatives(self.db, B)
        for key in (A, B):
            capabilities.set_state(self.db.cursor(), WS, key, "embed_text", "ready")
        self.db.grants.append(grant(location="cloud", category="embedding", scope="asset", key=B, members=[B], gid="2" * 32))
        receipt = lifecycle.propagate_revocation(ctx_for(self.db), {"grantType": "processing", "location": "cloud", "category": "embedding", "purpose": None,
                                                                   "scope": {"kind": "workspace"}})
        self.assertEqual(self.db.cap(A, "embed_text")["state"], "blocked_permission")
        self.assertEqual(self.db.cap(B, "embed_text")["state"], "ready", "B is still covered by its own grant")
        self.assertEqual({e["key"] for e in self.db.embeddings if e["status"] == "revoked"}, {A})
        self.assertEqual(receipt["stillCovered"], 1)
        self.db.grants.append(grant(location="cloud", category="embedding", gid="3" * 32))
        none = lifecycle.propagate_revocation(ctx_for(self.db), {"grantType": "processing", "location": "cloud", "category": "embedding", "purpose": None,
                                                                "scope": {"kind": "workspace"}})
        self.assertEqual((none["embeddingsRevoked"], none["jobsCancelled"], none["stillCovered"]), (0, 0, "all"))

    def test_finalize_rechecks_without_policy_lock(self):
        """#12 (resolved by e54fc518): finalize rechecks the committed grant revision with a plain read right before writing
        derivatives and takes no policy row lock, so a slow job can never block a revocation."""
        self.db.add_asset(A)
        jt.processor()
        jobs.enqueue_capability(ctx_for(self.db, service=self.service), {"assetId": A, "versionId": A, "sha256": jt.SHA}, "extract", "test-extract-1")
        self.db.statements.clear()
        self.tick()
        self.assertFalse([s for s in self.db.statements if "FOR SHARE" in s])
        rechecks = [i for i, s in enumerate(self.db.statements) if s.startswith("SELECT grant_revision FROM public.pr_library_policy")]
        locked = [i for i, s in enumerate(self.db.statements) if "lij:job.get" in s]
        self.assertTrue(rechecks and locked and locked[0] < rechecks[-1], "the recheck runs inside finalize, after the lease check")
        self.assertEqual(len(self.writer_calls["segments"]), 1)

    def test_link_fetch_holds_no_write_lock(self):
        """#9: the fetch and the object upload run with no workspace lock; only the quota check and insert run under it."""
        events = []

        @contextlib.contextmanager
        def open_write():
            events.append("lock")
            yield ctx_for(self.db, service=self.service)
            events.append("unlock")
        read_ctx = ctx_for(self.db, service=self.service)
        read_ctx.open_write = open_write
        net = jt.Net([jt.response(200, b"<html><title>T</title><p>Programme</p></html>", content_type="text/html")])
        original_put = self.storage.put_immutable

        def put(*args, **kw):
            events.append("put")
            return original_put(*args, **kw)

        def connector(*args):
            events.append("fetch")
            return net.connector(*args)
        with mock.patch.object(jt.intake, "RESOLVER", net.resolver), mock.patch.object(jt.intake, "CONNECTOR", connector), \
                mock.patch.object(self.storage, "put_immutable", put):
            out = jt.intake.link_http(read_ctx, {"params": {}, "query": {}, "body": {"url": "https://news.example.org/a", "idempotencyKey": "link-key-0000000009"}})
        self.assertEqual(events, ["fetch", "put", "lock", "unlock"])
        self.assertEqual(out["status"], "queued")
        self.assertEqual(len(self.db.inserted_assets), 1)
        note_ctx = ctx_for(self.db, service=self.service)
        note_ctx.open_write = open_write
        events.clear()
        jt.intake.note_http(note_ctx, {"params": {}, "query": {}, "body": {"text": "idea", "authoredByMe": True, "idempotencyKey": "note-key-0000000009"}})
        self.assertEqual(events, ["lock", "unlock"])

    def test_link_whole_request_deadline(self):
        """#9: slow headers or a trickling body cannot outlive the 10 s budget (shortened here); slow DNS neither."""
        import socket
        import threading
        import time as time_module
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        port = server.getsockname()[1]
        stop = threading.Event()

        def serve():
            conns = []
            while not stop.is_set():
                try:
                    server.settimeout(0.2)
                    conn, _ = server.accept()
                except OSError:
                    continue
                conns.append(conn)
                try:
                    conn.recv(4096)
                    for byte in b"HTTP/1.1 200 OK\r\nX-Slow: " + b"a" * 200:
                        if stop.is_set():
                            break
                        conn.send(bytes([byte]))
                        time_module.sleep(0.05)  # each read succeeds, so per-read timeouts alone never fire
                except OSError:
                    pass
            for conn in conns:
                conn.close()
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            started = time_module.monotonic()
            with self.assertRaises(AlphaError) as slow:
                jt.intake.pinned_get("http", "slow.example.org", "127.0.0.1", port, "/", 0.6, started + 0.6, time_module.monotonic)
            elapsed = time_module.monotonic() - started
        finally:
            stop.set()
            server.close()
        self.assertEqual(slow.exception.code, "library_link_timeout")
        self.assertLess(elapsed, 2.0, "the whole request is bounded by the deadline")

        def slow_dns(host, port, type=None):
            time_module.sleep(1.5)
            return [(None, None, None, "", ("93.184.216.34", port))]
        with mock.patch.object(jt.intake, "LINK_TIMEOUT", 0.3):
            started = time_module.monotonic()
            with self.assertRaises(AlphaError) as dns:
                jt.intake.fetch_link("https://news.example.org/", resolver=slow_dns, connector=lambda *a: self.fail("no fetch after a DNS timeout"))
            self.assertLess(time_module.monotonic() - started, 1.2)
        self.assertEqual(dns.exception.code, "library_link_timeout")


class Observability(Base):
    def test_no_secret_log(self):
        secrets = ("sk-live-SECRET123", "Bearer abc.def", "https://evil.example/x?token=abc", "dear diary my private text", "james@example.com")
        self.db.add_asset(A)

        def leaky(job):
            raise RuntimeError(" ".join(secrets))
        jt.processor(run=leaky)
        jobs.enqueue_capability(ctx_for(self.db, service=self.service), {"assetId": A, "versionId": A, "sha256": jt.SHA}, "extract", "test-extract-1")
        out, records = io.StringIO(), []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            with contextlib.redirect_stdout(out):
                self.tick()
                telemetry.log("library_intelligence.test", error=RuntimeError(secrets[0]), detail=secrets[3], url=secrets[2], token=secrets[0],
                              code="library_ok", count=2, workspace=WS)
                self.assertFalse(telemetry.record(self.db.cursor(), "library.test", "probe", 1, {"title": secrets[3], "url": secrets[2], "email": secrets[4],
                                                                                                 "note": secrets[3], "capability": "extract"},
                                                  workspace_id=WS) and False)
                with mock.patch.object(jobs, "_write", side_effect=RuntimeError(secrets[0])):
                    jt.processor("preview", "test-preview-1")
                    jobs.enqueue_capability(ctx_for(self.db, service=self.service), {"assetId": A, "versionId": A, "sha256": jt.SHA}, "preview", "test-preview-1")
                    self.tick()
        finally:
            root.removeHandler(handler)
        emitted = out.getvalue() + "\n".join(records) + json.dumps([m["dims"] for m in self.db.metrics])
        for secret in secrets + ("SECRET123", "diary", "token=abc", "evil.example"):
            self.assertNotIn(secret, emitted)
        self.assertIn("RuntimeError", out.getvalue(), "the error class is kept for operators")
        probe = [m for m in self.db.metrics if m["event"] == "probe"]
        self.assertEqual(probe[0]["dims"], {"capability": "extract"}, "content-like dims are dropped, safe ones kept")
        self.assertNotIn("SECRET123", json.dumps(list(self.db.caps.values()), default=str), "user-facing state carries no internals")

    def test_job_metrics_are_content_free(self):
        self.db.add_asset(A)
        jt.processor()
        jobs.enqueue_capability(ctx_for(self.db, service=self.service), {"assetId": A, "versionId": A, "sha256": jt.SHA}, "extract", "test-extract-1")
        self.tick()
        events = {(m["feature"], m["event"]) for m in self.db.metrics}
        self.assertIn(("library.jobs", "outcome"), events)
        self.assertIn(("library.jobs", "queue_age_seconds"), events)
        outcome = next(m for m in self.db.metrics if m["event"] == "outcome")
        self.assertEqual((outcome["dims"]["capability"], outcome["dims"]["state"], outcome["value"]), ("extract", "ready", 1))
        self.assertNotIn("Brahms", json.dumps([m["dims"] for m in self.db.metrics]))

    def test_status_http_scoped_and_costs_editor_only(self):
        self.db.add_asset(A)
        self.db.add_asset(C2)
        capabilities.set_state(self.db.cursor(), WS, A, "extract", "ready")
        capabilities.set_state(self.db.cursor(), WS, C2, "extract", "failed")
        jid = uuid.uuid4().hex
        self.db.jobs[jid] = {"id": jid, "ws": WS, "key": A, "capability": "understand", "pv": "v", "consent": 0, "idem": jid, "status": "queued", "attempts": 0,
                             "max": 3, "lease": None, "lease_exp": None, "next_at": self.db.now, "reservation": None,
                             "cost": {"byAttempt": {"1": {"kind": "actual", "usdMicro": 70}, "2": {"kind": "unknown", "usdMicro": None},
                                                    "3": {"kind": "estimated", "usdMicro": 9}}},
                             "category": None, "code": None, "requested_by": None, "created": self.db.now - 42, "finished": None, "timings": {}, "cleanup": None}
        owner = telemetry.status_http(ctx_for(self.db, service=self.service), {"params": {}, "query": {}, "body": {}})
        self.assertEqual(owner["costs"]["actualUsdMicro"], 70)
        self.assertEqual(owner["costs"]["estimatedUsdMicro"], 9)
        self.assertEqual(owner["costs"]["unknownCount"], 1)
        self.assertEqual((owner["queue"]["queued"], owner["queue"]["oldestQueuedSeconds"]), (1, 42))
        self.assertEqual((owner["coverage"]["indexed"], owner["coverage"]["failed"], owner["coverage"]["accessible"]), (1, 1, 2))
        self.assertEqual(set(owner["providers"]), {"embedding", "asr", "vision", "llm"})
        self.assertEqual(owner["revisions"]["indexGeneration"], 1)
        self.assertNotIn("sk-", json.dumps(owner))
        viewer = telemetry.status_http(ctx_for(self.db, role="viewer", service=self.service), {"params": {}, "query": {}, "body": {}})
        self.assertIsNone(viewer["costs"])
        self.assertFalse(viewer["costsVisible"])

    def test_cost_not_double_charged(self):
        """A071: a crashed attempt, a retry and a late duplicate finalize settle each reservation once; spend counts each provider call once."""
        ledger = FakeLedger()
        self.db.add_asset(A)
        self.db.grants.append(grant(location="cloud", category="llm"))
        def run(job):
            cost = 400 if job.attempt == 1 else 500
            return {"state": "ready", "provider": {"provider": "gateway", "model": "m", "cost": {"kind": "actual", "usdMicro": cost}}}
        jt.processor("understand", "cloud-understand-1", location="cloud", category="llm", run=run, estimate=lambda job: 1000)
        with mock.patch.object(providers_module, "reserve", ledger.reserve), mock.patch.object(providers_module, "settle", ledger.settle):
            jobs.enqueue_capability(ctx_for(self.db, service=self.service), {"assetId": A, "versionId": A, "sha256": jt.SHA}, "understand", "cloud-understand-1")
            crashed = jobs.claim_next(self.intel, self.db.connect)  # attempt 1 reserves, then the worker dies
            self.db.now += jobs.LEASE_SECONDS + 1
            self.tick()  # attempt 2: the stale reservation settles as unknown, a new one is reserved and settled with the receipt
            late = jobs.run_claimed(self.intel, self.db.connect, crashed)  # attempt 1 finally returns: no derivative, cost reconciled
            replay = jobs.run_claimed(self.intel, self.db.connect, crashed)  # a duplicate finalize changes nothing
        job = self.db.job_by_cap("understand")
        self.assertEqual(ledger.keys, [f"job:{job['id']}:1", f"job:{job['id']}:2"], "one reservation per attempt, never two for one attempt")
        self.assertEqual(ledger.terminal_counts(), {"r1": 1, "r2": 1})
        self.assertEqual(ledger.spent, 900, "each provider call is charged exactly once")
        self.assertEqual((late, replay), ("completed", "completed"))
        self.assertEqual(job["cost"]["byAttempt"], {"1": {"kind": "actual", "usdMicro": 400}, "2": {"kind": "actual", "usdMicro": 500}})
        self.assertEqual(len(self.writer_calls["annotations"]) + len(self.writer_calls["segments"]), 0)
        self.assertEqual(self.db.cap(A, "understand")["state"], "ready")


class FakeLedger:
    """Ledger.settle's terminal semantics: unknown keeps the hold; actual/released is terminal and happens once."""

    def __init__(self):
        self.keys, self.spent, self.events = [], 0, []
        self.reservations = {}

    def reserve(self, cur, ws, member, *, capability, estimate_usd_micro, key, model, job_id=None):
        if key in self.keys:
            return {"status": "reserved", "reservationId": self.reservations[key], "duplicate": True}
        rid = f"r{len(self.keys) + 1}"
        self.keys.append(key)
        self.reservations[key] = rid
        return {"status": "reserved", "reservationId": rid, "duplicate": False}

    def settle(self, cur, ws, reservation, result, failed=False):
        rid = reservation["reservationId"]
        if any(e[0] == rid and e[1] in ("actual", "released") for e in self.events):
            return {"duplicate": True}
        cost = getattr(result, "cost", None) or {}
        if failed:
            self.events.append((rid, "released"))
        elif cost.get("kind") == "actual":
            self.events.append((rid, "actual"))
            self.spent += cost["usdMicro"]
        else:
            self.events.append((rid, "unknown"))
        return {"state": self.events[-1][1]}

    def terminal_counts(self):
        out = {}
        for rid, state in self.events:
            if state in ("actual", "released"):
                out[rid] = out.get(rid, 0) + 1
        return out


class Telemetry(Base):
    def test_record_validates_and_never_raises(self):
        cur = self.db.cursor()
        self.assertTrue(telemetry.record(cur, "library.jobs", "outcome", 1, {"capability": "extract", "attempt": 2, "model": "openai/text-embedding-3-large"}, workspace_id=WS))
        self.assertFalse(telemetry.record(cur, "Library Jobs!", "outcome", 1))
        self.assertFalse(telemetry.record(cur, "library.jobs", "outcome", float("nan")))
        broken = FakeCursor()
        broken.execute = mock.Mock(side_effect=RuntimeError("db down"))
        self.assertFalse(telemetry.record(broken, "library.jobs", "outcome", 1))
        self.assertEqual(self.db.metrics[0]["dims"], {"capability": "extract", "attempt": 2, "model": "openai/text-embedding-3-large"})


class Backfill(Base):
    def seed(self):
        for n, key in enumerate((A, B, C2), start=1):
            self.db.add_asset(key, created=float(n))
        self.db.state["phase2"]["assets"].append({"id": LEGACY, "mime": "image/jpeg", "hash": "f" * 64, "objectName": f"{LEGACY}-{'f' * 64}.jpg", "createdAt": 5.0})
        jt.processor()  # local extract for documents
        jt.processor("embed_visual", "local/visual-perceptual-v1", category="embedding", kinds=("image",))
        jt.processor("embed_text", "cloud-text-1", location="cloud", category="embedding", kinds=("document", "image"), estimate=lambda job: 10)

    def fill(self, **kw):
        return lifecycle.backfill(self.intel, self.db.connect, **{"workspace_id": WS, "limit": 10, "dry_run": False, **kw})

    def test_backfill_resumable(self):
        self.seed()
        dry = self.fill(dry_run=True)
        self.assertEqual((dry["status"], dry["candidates"], dry["enqueued"]), ("dry_run", 4, 0))
        self.assertEqual(dry["byCapability"], {"extract": 3, "embed_visual": 1})
        self.assertEqual(dry["cloudSkipped"], 4, "cloud capabilities are counted, never enqueued without grants")
        self.assertEqual(self.db.jobs, {})
        self.assertEqual([m for m in self.db.metrics if m["event"] == "checkpoint"], [], "a dry run writes nothing")
        first = self.fill(limit=2)
        self.assertEqual((first["status"], first["enqueued"], first["done"]), ("partial", 2, False))
        self.assertEqual({j["key"] for j in self.db.jobs.values()}, {A, B})
        # Interruption: the next call resumes from the persisted cursor rather than from the start.
        second = self.fill(limit=1)
        self.assertEqual(second["enqueued"], 1)
        self.assertEqual({j["key"] for j in self.db.jobs.values()}, {A, B, C2})
        third = self.fill(limit=5)
        self.assertEqual((third["status"], third["enqueued"], third["done"]), ("complete", 1, True))
        self.assertEqual({j["key"] for j in self.db.jobs.values()}, {A, B, C2, LEGACY})
        self.assertEqual({j["capability"] for j in self.db.jobs.values()}, {"extract", "embed_visual"})
        again = self.fill()
        self.assertEqual((again["status"], again["scanned"]), ("complete", 0))
        restarted = self.fill(restart=True)
        self.assertEqual((restarted["enqueued"], restarted["status"]), (0, "complete"), "already queued or ready work is not repeated")
        self.assertEqual(len(self.db.jobs), 4)
        checkpoint = [m for m in self.db.metrics if m["event"] == "checkpoint"]
        self.assertTrue(checkpoint and all(set(m["dims"]) <= {"scope", "ws", "phase", "at", "id", "done"} for m in checkpoint))

    def test_backfill_pause_admission_and_flags(self):
        self.seed()
        with mock.patch.dict(os.environ, {"RAFII_LIBRARY_BACKFILL_PAUSED": "1"}):
            self.assertEqual(self.fill()["status"], "paused")
        self.assertEqual(self.db.jobs, {})
        throttled = self.fill(max_queue=1)
        self.assertEqual((throttled["status"], throttled["enqueued"]), ("throttled", 1), "queue admission bounds each run")
        with mock.patch.dict(os.environ, {"RAFII_LIBRARY_ENRICHMENT_ENABLED": ""}):
            self.assertEqual(self.fill()["status"], "disabled")

    def test_generation_bump_and_rollback(self):
        self.db.add_asset(A)
        self.db.embeddings += [{"key": A, "asset": A, "modality": "text", "model": "m1", "status": "active", "gen": 1}]
        bumped = lifecycle.bump_index_generation(ctx_for(self.db, service=self.service), reason="model_change")
        self.assertEqual(bumped["indexGeneration"], 2)
        self.assertEqual(bumped["activeVectors"], {"1": 1})
        rolled = lifecycle.rollback_index_generation(ctx_for(self.db, service=self.service), 1)
        self.assertEqual((rolled["indexGeneration"], rolled["activeVectorsInGeneration"]), (1, 1))
        self.assertEqual(policy.revisions(ctx_for(self.db), fresh=True)["indexGeneration"], 1, "search reads only the active generation")
        with self.assertRaises(AlphaError):
            lifecycle.rollback_index_generation(ctx_for(self.db, service=self.service), 5)
        with self.assertRaises(AlphaError) as editor:
            lifecycle.rollback_index_generation(ctx_for(self.db, role="editor", service=self.service), 1)
        self.assertEqual(editor.exception.status, 403)
        self.assertEqual(len(self.db.audits), 2)


class Rollback(Base):
    flags = NO_FLAGS

    def test_flag_rollback_preserves_original(self):
        """A074: every RAFII_LIBRARY_* flag off — originals process and download, the old list/search works, nothing fails."""
        self.assertFalse(any(policy.flag_state().values()))
        key = "9" * 32
        raw = b"# Notes\nBrahms."
        row = {"id": str(uuid.UUID(hex=key)), "object_name": key + ".md", "bytes": len(raw), "mime": "text/markdown", "etag": "e1", "kind": "document",
               "extension": "md", "attempts": 1, "created_by": ACTOR, "processing_status": "processing", "original_filename": "notes.md",
               "display_title": "notes", "title_source": "filename", "summary": "Brahms.", "tags": [], "sha256": "0" * 64, "analysis_status": "not_applicable",
               "indexing_status": "ready", "provenance": {}, "extraction_error": None, "epoch": 1.0}
        live = {"token": None, "status": "processing"}

        def claim(sql, args):
            live["token"] = args[0]
            return [(row,)]

        def finished(sql, args):
            live["status"] = args[1]
            return []
        cur = FakeCursor()
        cur.on(r"SET processing_status='processing'", claim)
        cur.on(r"SET sha256=%s,processing_status=%s", finished)
        cur.on(r"FROM public.pr_workspaces WHERE id=%s FOR UPDATE", [({},)])
        cur.on(r"to_jsonb\(a\)", lambda sql, args: [({**row, "lease_token": live["token"], "processing_status": live["status"]},)])
        cur.on(r"AND sha256=%s AND id<>%s", [])
        cur.on(r"SELECT count\(\*\) FROM public.pr_library_assets a", [(1,)])
        cur.on(r"coalesce\(sum\(bytes\),0\)", [(len(raw),)])

        @contextlib.contextmanager
        def connect():
            yield SimpleNamespace(cursor=lambda: contextlib.nullcontext(cur))

        @contextlib.contextmanager
        def transaction(token, workspace_id):
            yield cur, (1, {}, "owner", False, False, False, False), ACTOR
        storage = SimpleNamespace(object_info=lambda w, c_, n: {"bytes": len(raw), "mime": "text/markdown", "etag": "e1"}, get_bounded=lambda w, c_, n, m: raw,
                                  signed_url=lambda w, c_, n, expires_in=300: f"https://storage.invalid/{n}?token=t")
        service = SimpleNamespace(repository=SimpleNamespace(transaction=transaction, connection_factory=connect),
                                  ideas=SimpleNamespace(_state=lambda r: {"phase2": {"assets": []}}))
        library = UniversalLibrary(service=service, storage=storage)
        self.assertEqual(library.process(connect, WS, key), "ready", "the original is still processed by the existing pipeline")
        self.assertTrue(library.url(WS, "token", key, download=True)["url"].startswith("https://storage.invalid/"), "the original still downloads")
        listed = library.list(WS, "token", "Brahms")
        self.assertEqual([a["id"] for a in listed["assets"]], [key], "the old list/search still finds it")
        self.assertEqual(jobs.tick(self.intel, self.db.connect)["status"], "disabled")
        self.assertEqual(jobs.on_asset_processed(self.db.connect, WS, key)["status"], "disabled")
        self.assertEqual(lifecycle.backfill(self.intel, self.db.connect, dry_run=False, limit=5)["status"], "disabled")
        self.db.add_asset(A)
        caps = capabilities.capabilities_http(ctx_for(self.db), {"params": {"key": A}, "query": {}, "body": {}})
        self.assertFalse(caps["enrichmentEnabled"])
        status = telemetry.status_http(ctx_for(self.db, service=self.service), {"params": {}, "query": {}, "body": {}})
        self.assertFalse(any(status["flags"].values()))
        from postriff_phase2.library_intelligence import search
        with self.assertRaises(AlphaError) as off:
            search.search_library(ctx_for(self.db), {"query": "Brahms"})
        self.assertEqual((off.exception.status, off.exception.code), (503, "library_retrieval_disabled"), "new retrieval says so honestly")


if __name__ == "__main__":
    unittest.main()
