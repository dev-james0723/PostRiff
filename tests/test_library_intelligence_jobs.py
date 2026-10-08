"""T02 — durable progressive processing and safe intake (acceptance A001–A003, A012, A015, A071).

Unit tests of the Python orchestration. `FakeDB` emulates each tagged statement (`/*lij:...*/`) of jobs, capabilities and
intake plus the coordinator queries they rely on; it proves logic only. Real SQL (SKIP LOCKED, constraints, leases
against a real clock) is covered by tests/phase2/postgres_library_intelligence_jobs.py in cloud CI.
"""
import email.utils
import hashlib
import io
import json
import os
import re
import sys
import time
import unittest
import uuid
import zipfile
from types import ModuleType, SimpleNamespace
from unittest import mock

from library_intelligence_fakes import ACTOR, WS, FakeCursor, grant
from postriff_alpha.domain import AlphaError
from postriff_phase2.permissions import Membership
from postriff_phase2.library_intelligence import capabilities, contracts as c, intake, jobs, policy, providers as providers_module
from postriff_phase2 import library_extract
from postriff_phase2.library_assets import UniversalLibrary

PKG = "postriff_phase2.library_intelligence"
FLAG = {"RAFII_LIBRARY_ENRICHMENT_ENABLED": "1"}
DOC = "a" * 32
OTHER = "d" * 32
LEGACY = "e" * 32
RAW = b"Brahms rehearsal notes. Fingering for bar 12."
SHA = hashlib.sha256(RAW).hexdigest()


def _hex(value):
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value.hex
    return str(value).replace("-", "").lower()


class FakeDB:
    """In-memory tables for the statements jobs/capabilities/intake issue. Single-threaded; no rollback emulation."""

    def __init__(self):
        self.now = 1_790_000_000.0
        self.seq = 0
        self.jobs = {}
        self.caps = {}
        self.assets = {}
        self.receipts = {}
        self.inserted_assets = []
        self.grants = []
        self.grant_revision = 1
        self.state = {"sources": [], "phase2": {"assets": []}}
        self.frozen = False
        self.statements = []

    # --- connection protocol ------------------------------------------------------------------------------------------
    def connect(self):
        return FakeConnection(self)

    def cursor(self):
        return FakeDBCursor(self)

    # --- fixtures --------------------------------------------------------------------------------------------------------
    def add_asset(self, key=DOC, *, kind="document", status="ready", sha=SHA, ext="md", mime="text/markdown", raw=RAW, lineage=None):
        self.assets[key] = {"id": key, "lineage": lineage, "kind": kind, "status": status, "sha": sha, "ext": ext, "mime": mime,
                            "bytes": len(raw), "object": f"{key}.{ext}", "etag": "etag-" + key[:6], "media": {}, "raw": raw}
        return key

    def job_by_cap(self, capability):
        found = [j for j in self.jobs.values() if j["capability"] == capability]
        return found[-1] if found else None

    def cap(self, key, capability):
        return self.caps.get((WS, key, capability))

    # --- rows ------------------------------------------------------------------------------------------------------------
    def job_row(self, j):
        return (str(uuid.UUID(hex=j["id"])), j["ws"], j["key"], j["capability"], j["pv"], j["consent"], j["idem"], j["status"], j["attempts"],
                j["max"], j["lease"], j["lease_exp"], j["next_at"], j["reservation"], j["cost"], j["category"], j["code"], j["requested_by"],
                j["created"], j["finished"])

    def version_row(self, a):
        return (uuid.UUID(hex=a["id"]), uuid.UUID(hex=a["lineage"]) if a["lineage"] else None, 1, WS, f"notes.{a['ext']}", "Notes", "filename", None, [],
                a["kind"], a["mime"], a["ext"], a["bytes"], a["sha"], a["status"], "not_applicable", "ready", "not_applicable", None, "upload",
                a["media"], None, {}, 1.0)


class FakeConnection:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return FakeDBCursor(self.db)


TAG = re.compile(r"/\*lij:([a-z_.]+)\*/")


class FakeDBCursor:
    def __init__(self, db):
        self.db = db
        self.rowcount = 0
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def _set(self, rows, count=None):
        self._rows = list(rows)
        self.rowcount = len(self._rows) if count is None else count

    def execute(self, sql, args=()):
        db = self.db
        db.statements.append(sql)
        tag = TAG.search(sql)
        if tag:
            return getattr(self, "_" + tag.group(1).replace(".", "_"))(sql, tuple(args))
        if re.match(r"\s*(SAVEPOINT|RELEASE SAVEPOINT|ROLLBACK TO SAVEPOINT)", sql):
            return self._set([])
        if "FROM public.pr_library_policy" in sql:
            return self._set([(db.grant_revision, 1, 0)])
        if "FROM public.pr_library_grants" in sql:
            return self._set([(g["id"], g["grantType"], g["scopeKind"], g["scopeKey"], g["memberKeys"], g["purpose"], g["location"], g["category"],
                               g["attestation"], g["grantedBy"], g["grantedRevision"], g["grantedAt"]) for g in db.grants])
        if "FROM public.pr_library_assets WHERE workspace_id=%s AND id=ANY" in sql:
            keys = {_hex(k) for k in args[1]}
            return self._set([db.version_row(a) for k, a in db.assets.items() if k in keys and args[0] == WS])
        if "FROM public.pr_library_labels" in sql:
            return self._set([])
        raise AssertionError("FakeDB does not know this statement: " + sql[:120])

    # --- jobs ------------------------------------------------------------------------------------------------------------
    def _job_lock(self, sql, args):
        self._set([(None,)])

    def _job_active(self, sql, args):
        ws, key, capability, pv = args
        found = [j for j in self.db.jobs.values() if (j["ws"], j["key"], j["capability"], j["pv"]) == (ws, key, capability, pv) and j["status"] in ("queued", "processing")]
        self._set([self.db.job_row(found[-1])] if found else [])

    def _job_insert(self, sql, args):
        jid, ws, key, capability, pv, consent, idem, max_attempts, requested_by = args
        if any(j["ws"] == ws and j["idem"] == idem for j in self.db.jobs.values()):
            return self._set([])
        self.db.seq += 1
        job = {"id": _hex(jid), "ws": ws, "key": key, "capability": capability, "pv": pv, "consent": consent, "idem": idem, "status": "queued",
               "attempts": 0, "max": max_attempts, "lease": None, "lease_exp": None, "next_at": self.db.now, "reservation": None, "cost": None,
               "category": None, "code": None, "requested_by": requested_by, "created": self.db.now + self.db.seq / 1000, "finished": None,
               "timings": {}, "cleanup": None}
        self.db.jobs[job["id"]] = job
        self._set([self.db.job_row(job)])

    def _job_by_key(self, sql, args):
        ws, idem = args
        found = [j for j in self.db.jobs.values() if j["ws"] == ws and j["idem"] == idem]
        self._set([self.db.job_row(found[0])] if found else [])

    def _job_revive(self, sql, args):
        requested_by, ws, jid = args
        job = self.db.jobs.get(_hex(jid))
        if not job or job["status"] not in ("failed", "cancelled", "blocked"):
            return self._set([])
        job.update(status="queued", attempts=0, next_at=self.db.now, lease=None, lease_exp=None, category=None, code=None, finished=None,
                   requested_by=requested_by or job["requested_by"])
        self._set([self.db.job_row(job)])

    def _job_get(self, sql, args):
        ws, jid = args
        job = self.db.jobs.get(_hex(jid))
        self._set([self.db.job_row(job)] if job and job["ws"] == ws else [])

    def _job_claim(self, sql, args):
        lease, seconds = args
        db = self.db
        due = [j for j in db.jobs.values() if ((j["status"] == "queued" and j["next_at"] <= db.now) or (j["status"] == "processing" and j["lease_exp"] < db.now))
               and j["attempts"] < j["max"] and not db.frozen]
        if not due:
            return self._set([])
        job = sorted(due, key=lambda j: (j["next_at"], j["created"]))[0]
        job.update(status="processing", lease=str(lease), lease_exp=db.now + seconds, attempts=job["attempts"] + 1)
        self._set([db.job_row(job)])

    def _job_reserve(self, sql, args):
        payload, jid, lease = args
        job = self.db.jobs[_hex(jid)]
        if job["lease"] == str(lease):
            job["reservation"] = json.loads(payload)
            return self._set([], 1)
        self._set([], 0)

    def _job_heartbeat(self, sql, args):
        seconds, jid, lease = args
        job = self.db.jobs[_hex(jid)]
        if job["lease"] == str(lease) and job["status"] == "processing":
            job["lease_exp"] = self.db.now + seconds
            return self._set([(1,)])
        self._set([])

    def _job_finish(self, sql, args):
        status, category, code, cost, reservation, cleanup, timings, jid = args
        job = self.db.jobs[_hex(jid)]
        job.update(status=status, category=category, code=code, cost=json.loads(cost) if cost else None,
                   reservation=json.loads(reservation) if reservation else None, cleanup=cleanup, lease=None, lease_exp=None, finished=self.db.now)
        job["timings"].update(json.loads(timings))
        self._set([], 1)

    def _job_requeue(self, sql, args):
        category, code, reservation, timings, delay, jid = args
        job = self.db.jobs[_hex(jid)]
        job.update(status="queued", category=category, code=code, reservation=json.loads(reservation) if reservation else None, lease=None,
                   lease_exp=None, next_at=self.db.now + delay)
        job["timings"].update(json.loads(timings))
        self._set([], 1)

    def _job_settled(self, sql, args):
        payload, jid, reservation_id = args
        job = self.db.jobs.get(_hex(jid))
        if job and (job["reservation"] or {}).get("reservationId") == reservation_id:
            job["reservation"] = json.loads(payload)
        self._set([])

    def _job_cancel(self, sql, args):
        ws, key, caps = args
        out = []
        for job in self.db.jobs.values():
            if job["ws"] == ws and job["key"] == key and job["status"] in ("queued", "processing") and job["capability"] in caps:
                job.update(status="cancelled", category="cancelled", code="library_cancelled", lease=None, lease_exp=None, finished=self.db.now)
                out.append((str(uuid.UUID(hex=job["id"])), job["capability"]))
        self._set(out)

    def _job_recover(self, sql, args):
        out = []
        for job in self.db.jobs.values():
            if job["status"] == "processing" and job["lease_exp"] < self.db.now and job["attempts"] >= job["max"]:
                job.update(status="failed", category="timeout", code="library_job_timeout", lease=None, lease_exp=None, finished=self.db.now)
                out.append(self.db.job_row(job))
        self._set(out)

    def _job_orphans(self, sql, args):
        out = [self.db.job_row(j) for j in self.db.jobs.values()
               if j["status"] in ("cancelled", "failed", "blocked", "completed", "partial") and j["reservation"]
               and j["reservation"].get("status") == "reserved" and not j["reservation"].get("settled") and (j["finished"] or 0) < self.db.now - 15 * 60]
        self._set(out)

    # --- workspace, assets, receipts -------------------------------------------------------------------------------------
    def _ws_state(self, sql, args):
        self._set([] if args[0] != WS else [(dict(self.db.state, **({"accountBlock": True} if self.db.frozen else {})),)])

    def _asset_object(self, sql, args):
        a = self.db.assets.get(_hex(args[1]))
        self._set([(a["object"], a["bytes"], a["mime"], a["etag"], a["sha"])] if a and args[0] == WS else [])

    def _asset_media(self, sql, args):
        payload, ws, key = args
        self.db.assets[_hex(key)]["media"].update(json.loads(payload))
        self._set([], 1)

    def _receipt_get(self, sql, args):
        found = self.db.receipts.get(args)
        self._set([found] if found else [])

    def _receipt_put(self, sql, args):
        ws, key, actor, action_type, request_hash, result = args
        self.db.receipts.setdefault((ws, key), (actor, action_type, request_hash, json.loads(result)))
        self._set([], 1)

    def _intake_insert(self, sql, args):
        names = ("id", "ws", "created_by", "filename", "title", "title_source", "kind", "mime", "ext", "bytes", "bucket", "object", "etag", "provenance", "source_kind")
        row = dict(zip(names, args))
        row["provenance"] = json.loads(row["provenance"])
        self.db.inserted_assets.append(row)
        self._set([], 1)

    # --- capabilities ----------------------------------------------------------------------------------------------------
    def _cap_set(self, sql, args):
        (ws, key, capability, state, progress, error_code, detail, retryable, job_id, pv, provider, completed, guard, _guard2, keep) = args
        current = self.db.caps.get((ws, key, capability))
        if current is not None:
            if guard is not None and current["job_id"] not in (None, _hex(guard)):
                return self._set([], 0)
            if current["state"] in (keep or []):
                return self._set([], 0)
        row = {"state": state, "progress": json.loads(progress) if progress else None, "error_code": error_code, "detail": detail,
               "retryable": bool(retryable), "job_id": _hex(job_id) or (current or {}).get("job_id"), "pv": pv or (current or {}).get("pv"),
               "provider": json.loads(provider) if provider else None, "updated": self.db.now, "completed": self.db.now if completed else None}
        self.db.caps[(ws, key, capability)] = row
        self._set([(state,)])

    def _cap_list(self, sql, args):
        ws, key = args
        self._set([(cap, r["state"], r["progress"], r["error_code"], r["detail"], r["retryable"], r["job_id"], r["pv"], r["provider"], r["updated"], r["completed"])
                   for (w, k, cap), r in self.db.caps.items() if w == ws and k == key])


class FakeStorage:
    def __init__(self, db):
        self.db = db
        self.objects = {}
        self.puts = []
        self.deleted = []
        self.reads = 0

    def object_info(self, ws, category, name):
        for a in self.db.assets.values():
            if a["object"] == name:
                return {"bytes": a["bytes"], "mime": a["mime"], "etag": a["etag"]}
        if (ws, name) in self.objects:
            raw, mime = self.objects[(ws, name)]
            return {"bytes": len(raw), "mime": mime, "etag": "etag-" + hashlib.sha256(raw).hexdigest()[:12]}
        raise AlphaError("missing", 404)

    def get_bounded(self, ws, category, name, max_bytes):
        self.reads += 1
        for a in self.db.assets.values():
            if a["object"] == name:
                return a["raw"]
        raise AlphaError("missing", 404)

    def get(self, ws, category, name):
        self.reads += 1
        return self.objects[(ws, name)][0]

    def put_immutable(self, ws, category, name, raw, content_type="image/jpeg"):
        assert category == "file"
        self.puts.append((ws, name, raw, content_type))
        self.objects[(ws, name)] = (raw, content_type)
        return f"{ws}/{category}/{name}"

    def delete(self, ws, category, name):
        self.deleted.append((ws, category, name))
        self.objects.pop((ws, name), None)


class FakeLibrary:
    def __init__(self, storage, *, full=False):
        self.storage = storage
        self.bucket = "postriff-library"
        self.full = full
        self.capacity_checks = []

    def assert_capacity(self, cur, state, w, size=0):
        self.capacity_checks.append(size)
        if self.full:
            raise AlphaError("This workspace has reached its Library storage limit. Remove unused files first.", 413, code="library_storage_limit")


def make_ctx(db, role="owner", state=None, service=None):
    return c.LibraryContext(workspace_id=WS, actor=ACTOR, membership=Membership(role), state=state if state is not None else db.state,
                            cur=db.cursor(), now=db.now, service=service)


def processor(capability="extract", version="test-extract-1", *, location="local", category="extract", kinds=("document",), run=None, estimate=None, name=None):
    calls = []

    def default_run(job):
        return {"state": "ready", "segments": [{"text": "Brahms", "locator": {"kind": "text", "start": 0, "end": 6}}]}

    def runner(job):
        calls.append(job)
        return (run or default_run)(job)

    entry = {"capability": capability, "version": version, "location": location, "category": category,
             "applies": lambda v, kinds=kinds: v["kind"] in kinds, "run": runner, "estimate": estimate}
    if name:
        entry["name"] = name
    capabilities.register(entry)
    return calls


def writer_modules():
    """Fake writer modules for workers B and C; records calls."""
    calls = {"segments": [], "embeddings": [], "annotations": []}
    seg = ModuleType(PKG + ".segments")
    seg.write_segments = lambda cur, ws, version, items, **kw: calls["segments"].append((version["versionId"], list(items), kw)) or len(items)
    idx = ModuleType(PKG + ".index")
    idx.write_embeddings = lambda cur, ws, version, items, **kw: calls["embeddings"].append((version["versionId"], list(items), kw)) or len(items)
    und = ModuleType(PKG + ".understanding")
    und.write_annotations = lambda cur, ws, version, items, **kw: calls["annotations"].append((version["versionId"], list(items), kw)) or len(items)
    return calls, {PKG + ".segments": seg, PKG + ".index": idx, PKG + ".understanding": und}


class Base(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.db.add_asset(DOC)
        self.storage = FakeStorage(self.db)
        self.library = FakeLibrary(self.storage)
        self.service = SimpleNamespace(library=self.library)
        self.intel = SimpleNamespace(service=self.service, providers=SimpleNamespace(name="fake-providers"))
        patches = [mock.patch.dict(capabilities.PROCESSORS, clear=True), mock.patch.object(capabilities, "PROCESSOR_MODULES", ()),
                   mock.patch.object(capabilities, "_loaded", True), mock.patch.dict(os.environ, FLAG)]
        self.writer_calls, modules = writer_modules()
        patches.append(mock.patch.dict(sys.modules, modules))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def ref(self, key=DOC):
        a = self.db.assets[key]
        return {"assetId": a["lineage"] or key, "versionId": key, "sha256": a["sha"]}

    def enqueue(self, capability="extract", version="test-extract-1", key=DOC, **kw):
        return jobs.enqueue_capability(make_ctx(self.db, service=self.service), self.ref(key), capability, version, **kw)

    def tick(self, **kw):
        return jobs.tick(self.intel, self.db.connect, max_jobs=kw.pop("max_jobs", 10), max_seconds=kw.pop("max_seconds", 30.0), **kw)


class Idempotency(Base):
    def test_duplicate_event_one_job(self):
        processor()
        first = jobs.on_asset_processed(self.db.connect, WS, DOC)
        second = jobs.on_asset_processed(self.db.connect, WS, DOC)
        self.assertEqual(len(self.db.jobs), 1, (first, second))
        job = next(iter(self.db.jobs.values()))
        self.assertEqual(self.db.cap(DOC, "extract")["state"], "queued")
        direct1 = self.enqueue()
        direct2 = self.enqueue()
        self.assertEqual(len(self.db.jobs), 1)
        self.assertEqual(direct1["job"]["jobId"], job["id"])
        self.assertEqual(direct2["job"]["jobId"], job["id"])
        self.assertTrue(direct2["duplicate"])
        # The key binds workspace, version, capability, processor version and consent revision.
        self.assertEqual(job["idem"], jobs.idempotency_key(WS, DOC, "extract", "test-extract-1", self.db.grant_revision))
        self.assertNotEqual(job["idem"], jobs.idempotency_key(WS, DOC, "extract", "test-extract-2", self.db.grant_revision))
        self.assertNotEqual(job["idem"], jobs.idempotency_key(WS, DOC, "extract", "test-extract-1", self.db.grant_revision + 1))

    def test_on_asset_processed_flag_off_and_never_raises(self):
        processor()
        with mock.patch.dict(os.environ, {"RAFII_LIBRARY_ENRICHMENT_ENABLED": ""}):
            called = []
            self.assertEqual(jobs.on_asset_processed(lambda: called.append(1), WS, DOC)["status"], "disabled")
            # Only the deterministic smart-collection re-evaluation runs (one connection); nothing is enqueued.
            self.assertEqual(called, [1])
            self.assertEqual(self.db.jobs, {})

        def broken():
            raise RuntimeError("database unavailable")
        self.assertEqual(jobs.on_asset_processed(broken, WS, DOC)["status"], "error")
        self.assertEqual(self.db.jobs, {})

    def test_on_asset_processed_enqueues_only_local_defaults(self):
        processor()
        processor("transcribe", "cloud-asr-1", location="cloud", category="asr", kinds=("document",))
        jobs.on_asset_processed(self.db.connect, WS, DOC)
        self.assertEqual({j["capability"] for j in self.db.jobs.values()}, {"extract"})
        self.assertIsNone(self.db.cap(DOC, "transcribe"), "cloud work is never enqueued automatically")

    def test_request_http_idempotent_on_key(self):
        processor()
        ctx = make_ctx(self.db, service=self.service)
        body = {"capabilities": ["extract"], "idempotencyKey": "request-key-000000001"}
        first = jobs.request_http(ctx, {"params": {"key": DOC}, "body": body, "query": {}})
        again = jobs.request_http(make_ctx(self.db, service=self.service), {"params": {"key": DOC}, "body": body, "query": {}})
        self.assertEqual(len(self.db.jobs), 1)
        self.assertTrue(again.get("replayed"))
        self.assertEqual(first["results"][0]["jobId"], again["results"][0]["jobId"])
        with self.assertRaises(AlphaError) as conflict:
            jobs.request_http(make_ctx(self.db, service=self.service), {"params": {"key": DOC}, "body": {"capabilities": ["extract", "preview"], "idempotencyKey": body["idempotencyKey"]}, "query": {}})
        self.assertEqual(conflict.exception.status, 409)
        with self.assertRaises(AlphaError) as viewer:
            jobs.request_http(make_ctx(self.db, role="viewer", service=self.service), {"params": {"key": DOC}, "body": body, "query": {}})
        self.assertEqual(viewer.exception.status, 403)


class Capabilities(Base):
    def test_capability_partial_independent(self):
        def partial(job):
            raw = job.raw()
            self.assertEqual(raw, RAW)
            return {"state": "partial", "errorCode": "library_partial_pages", "detail": "2 of 3 pages had readable text.",
                    "segments": [{"text": "Brahms"}, {"text": "bar 12"}]}

        def damaged(job):
            raise AlphaError("This document is damaged.", 422, code="library_corrupt")
        processor(run=partial)
        processor("preview", "test-preview-1", run=damaged)
        self.enqueue()
        self.enqueue("preview", "test-preview-1")
        summary = self.tick()
        self.assertEqual((summary["partial"], summary["failed"]), (1, 1), summary)
        self.assertEqual(self.db.cap(DOC, "extract")["state"], "partial")
        self.assertEqual(self.db.cap(DOC, "preview")["state"], "failed")
        self.assertFalse(self.db.cap(DOC, "preview")["retryable"])
        self.assertEqual(len(self.writer_calls["segments"]), 1)
        self.assertEqual(len(self.writer_calls["segments"][0][1]), 2)
        self.assertEqual(self.writer_calls["segments"][0][2], {"extractor": "extract", "extractor_version": "test-extract-1"})
        states = {s["capability"]: s for s in capabilities.states_for(make_ctx(self.db), self.version())}
        self.assertEqual(states["extract"]["state"], "partial")
        self.assertEqual(states["preview"]["state"], "failed")
        self.assertEqual(states["embed_text"]["state"], "not_requested")
        self.assertEqual(states["understand"]["state"], "not_requested")
        self.assertNotIn("transcribe", states, "audio capabilities do not apply to a document")
        self.assertTrue(all("progress" not in s for s in states.values()))
        self.assertEqual(self.db.job_by_cap("extract")["status"], "partial")
        self.assertEqual(self.db.job_by_cap("preview")["status"], "failed")
        self.assertEqual(self.db.job_by_cap("preview")["category"], "corrupt")

    def version(self, key=DOC):
        from postriff_phase2.library_intelligence import versions
        return versions.get(make_ctx(self.db), key)

    def test_states_for_no_fake_progress(self):
        processor()
        capabilities.set_state(self.db.cursor(), WS, DOC, "extract", "processing", progress={"percent": 50})
        states = {s["capability"]: s for s in capabilities.states_for(make_ctx(self.db), self.version())}
        self.assertNotIn("progress", states["extract"], "an unmeasured percentage is never shown")
        capabilities.set_state(self.db.cursor(), WS, DOC, "extract", "processing", progress={"done": 3, "total": 10, "unit": "pages"})
        states = {s["capability"]: s for s in capabilities.states_for(make_ctx(self.db), self.version())}
        self.assertEqual(states["extract"]["progress"], {"done": 3, "total": 10, "unit": "pages"})
        capabilities.set_state(self.db.cursor(), WS, DOC, "extract", "ready")
        states = {s["capability"]: s for s in capabilities.states_for(make_ctx(self.db), self.version())}
        self.assertNotIn("progress", states["extract"])
        with self.assertRaises(AlphaError):
            capabilities.set_state(self.db.cursor(), WS, DOC, "extract", "understood")

    def test_capabilities_http_foreign_key_404_and_legacy_photo(self):
        processor("embed_visual", "local-visual-1", category="vision", kinds=("image",))
        self.db.state["phase2"]["assets"].append({"id": LEGACY, "mime": "image/jpeg", "hash": "f" * 64, "objectName": f"{LEGACY}-{'f' * 64}.jpg", "bytes": 10})
        ctx = make_ctx(self.db)
        out = capabilities.capabilities_http(ctx, {"params": {"key": LEGACY}, "query": {}, "body": {}})
        self.assertEqual(out["assetRef"]["versionId"], LEGACY)
        states = {s["capability"]: s for s in out["capabilities"]}
        self.assertEqual(states["embed_visual"], {"capability": "embed_visual", "state": "not_requested", "available": True})
        self.assertEqual(states["visual"]["available"], False)
        jobs.on_asset_processed(self.db.connect, WS, LEGACY)
        self.assertEqual(self.db.cap(LEGACY, "embed_visual")["state"], "queued", "legacy media rows are keyed by their 32-hex id")
        with self.assertRaises(AlphaError) as foreign:
            capabilities.capabilities_http(make_ctx(self.db), {"params": {"key": OTHER}, "query": {}, "body": {}})
        self.assertEqual((foreign.exception.status, foreign.exception.code), (404, "library_unavailable"))

    def test_measurable_progress_and_heartbeat_during_run(self):
        seen = {}

        def run(job):
            self.assertTrue(job.progress(1, 4, "pages"))
            self.db.now += 100
            self.assertTrue(job.heartbeat())
            seen["lease_exp"] = self.db.job_by_cap("extract")["lease_exp"]
            seen["states"] = {s["capability"]: s for s in capabilities.states_for(make_ctx(self.db), self.version())}
            return {"state": "ready"}
        processor(run=run)
        self.enqueue()
        self.tick()
        self.assertEqual(seen["states"]["extract"]["state"], "processing")
        self.assertEqual(seen["states"]["extract"]["progress"], {"done": 1, "total": 4, "unit": "pages"})
        self.assertEqual(seen["lease_exp"], self.db.now + jobs.LEASE_SECONDS)
        self.assertEqual(self.db.cap(DOC, "extract")["state"], "ready")
        self.assertIsNone(self.db.cap(DOC, "extract")["progress"])

    def test_request_retries_failed_capability(self):
        outcomes = [AlphaError("Damaged.", 422, code="library_corrupt"), None]

        def run(job):
            error = outcomes.pop(0)
            if error:
                raise error
            return {"state": "ready"}
        calls = processor(run=run)
        self.enqueue()
        self.tick()
        job = self.db.job_by_cap("extract")
        self.assertEqual(job["status"], "failed")
        out = jobs.request_http(make_ctx(self.db, service=self.service), {"params": {"key": DOC}, "query": {},
                                                                         "body": {"capabilities": ["extract"], "idempotencyKey": "retry-key-00000000001"}})
        self.assertEqual(out["results"][0]["jobId"], job["id"])
        self.assertEqual((job["status"], job["attempts"]), ("queued", 0), "an explicit retry revives the same job")
        self.tick()
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.db.cap(DOC, "extract")["state"], "ready")
        with mock.patch.dict(os.environ, {"RAFII_LIBRARY_ENRICHMENT_ENABLED": ""}):
            with self.assertRaises(AlphaError) as off:
                jobs.request_http(make_ctx(self.db, service=self.service), {"params": {"key": DOC}, "query": {},
                                                                            "body": {"capabilities": ["extract"], "idempotencyKey": "retry-key-00000000002"}})
            self.assertEqual(off.exception.code, "library_enrichment_disabled")
            self.assertEqual(self.tick()["status"], "disabled")

    def test_loader_tolerates_missing_workstreams(self):
        with mock.patch.object(capabilities, "PROCESSOR_MODULES", ("no_such_workstream_module",)), mock.patch.object(capabilities, "_loaded", False):
            self.assertEqual(capabilities.processors_for(self.version()), [])
            self.assertEqual(capabilities.applicable(self.version()), ["preview", "extract", "embed_text", "understand"])

    def test_register_validates_processor_shape(self):
        with self.assertRaises(ValueError):
            capabilities.register({"capability": "extract", "version": "x", "location": "moon", "category": "extract", "applies": bool, "run": bool})
        with self.assertRaises(ValueError):
            capabilities.register({"capability": "summarize", "version": "x", "location": "local", "category": "extract", "applies": bool, "run": bool})
        processor()
        processor()  # re-registration of the same version replaces, never duplicates
        self.assertEqual(len(capabilities.PROCESSORS["extract"]), 1)


class Leases(Base):
    def test_restart_recovers_lease(self):
        processor()
        self.enqueue()
        crashed = jobs.claim_next(self.intel, self.db.connect)
        job = self.db.job_by_cap("extract")
        self.assertEqual((job["status"], job["attempts"]), ("processing", 1))
        self.assertEqual(self.tick()["claimed"], 0, "a live lease is not stolen")
        self.db.now += jobs.LEASE_SECONDS + 1
        summary = self.tick()
        self.assertEqual(summary["completed"], 1, summary)
        self.assertEqual((job["status"], job["attempts"]), ("completed", 2))
        self.assertEqual(self.db.cap(DOC, "extract")["state"], "ready")
        self.assertEqual(len(self.writer_calls["segments"]), 1)
        # The crashed worker comes back late: its lease is gone, so it writes nothing.
        late = jobs.run_claimed(self.intel, self.db.connect, crashed)
        self.assertIn(late, ("lost", "completed"))
        self.assertEqual(len(self.writer_calls["segments"]), 1)

    def test_stale_lease_at_ceiling_fails_honestly(self):
        processor()
        self.enqueue()
        job = self.db.job_by_cap("extract")
        job.update(status="processing", attempts=3, lease="dead", lease_exp=self.db.now - 1)
        summary = self.tick()
        self.assertEqual(summary["recovered"], 1)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["code"], "library_job_timeout")
        self.assertEqual(self.db.cap(DOC, "extract")["state"], "failed")
        self.assertTrue(self.db.cap(DOC, "extract")["retryable"], "the user may retry a timed-out capability")

    def test_retry_ceiling_three(self):
        def flaky(job):
            raise jobs.RetryableError("The provider is busy.")
        calls = processor(run=flaky)
        self.enqueue()
        job = self.db.job_by_cap("extract")
        for attempt in (1, 2, 3):
            summary = self.tick()
            self.assertEqual(summary["claimed"], 1, (attempt, summary))
            if attempt < 3:
                self.assertEqual(job["status"], "queued")
                self.assertEqual(self.db.cap(DOC, "extract")["state"], "queued")
                delay = job["next_at"] - self.db.now
                base = min(jobs.BACKOFF_CAP, jobs.BACKOFF_BASE * 2 ** (attempt - 1))
                self.assertTrue(base <= delay <= base * (1 + jobs.JITTER) + 1, (attempt, delay))
                self.assertEqual(self.tick()["claimed"], 0, "backoff is respected")
                self.db.now = job["next_at"]
        self.assertEqual(len(calls), 3)
        self.assertEqual((job["status"], job["attempts"]), ("failed", 3))
        self.assertEqual(self.db.cap(DOC, "extract")["state"], "failed")
        self.db.now += 10_000
        self.assertEqual(self.tick()["claimed"], 0)
        self.assertEqual(len(calls), 3)

    def test_retry_after_respected(self):
        def limited(job):
            raise jobs.RetryableError("Slow down.", retry_after=600)
        processor(run=limited)
        self.enqueue()
        self.tick()
        job = self.db.job_by_cap("extract")
        self.assertGreaterEqual(job["next_at"] - self.db.now, 600)
        when = email.utils.formatdate(time.time() + 1200, usegmt=True)
        self.assertGreaterEqual(jobs.retry_after_seconds(when), 1100)
        self.assertEqual(jobs.retry_after_seconds("garbage"), None)
        self.assertEqual(jobs.retry_after_seconds(10 ** 9), jobs.RETRY_AFTER_CAP)

    def test_permission_and_unsupported_errors_are_terminal(self):
        def forbidden(job):
            raise AlphaError("Not allowed.", 403, code="library_forbidden")
        calls = processor(run=forbidden)
        self.enqueue()
        self.tick()
        self.db.now += 10_000
        self.tick()
        self.assertEqual(len(calls), 1, "a permission failure is a state, never a retry")
        self.assertEqual(self.db.cap(DOC, "extract")["state"], "blocked_permission")


class Cancellation(Base):
    def test_cancel_before_finalization(self):
        def run(job):
            jobs.cancel_http(make_ctx(self.db, service=self.service), {"params": {"key": DOC}, "body": {"capabilities": ["extract"]}, "query": {}})
            return {"state": "ready", "segments": [{"text": "late"}], "media": {"pages": 3}}
        processor(run=run)
        self.enqueue()
        summary = self.tick()
        self.assertEqual(summary["cancelled"], 1, summary)
        self.assertEqual(self.writer_calls["segments"], [], "no derivative after cancellation")
        self.assertEqual(self.db.assets[DOC]["media"], {})
        self.assertEqual(self.db.job_by_cap("extract")["status"], "cancelled")
        self.assertEqual(self.db.cap(DOC, "extract")["state"], "cancelled")

    def test_cancel_queued_job(self):
        calls = processor()
        self.enqueue()
        out = jobs.cancel_http(make_ctx(self.db, service=self.service), {"params": {"key": DOC}, "body": {}, "query": {}})
        self.assertEqual(out["cancelled"], 1)
        self.assertEqual(self.tick()["claimed"], 0)
        self.assertEqual(calls, [])
        self.assertEqual(self.db.cap(DOC, "extract")["state"], "cancelled")
        with self.assertRaises(AlphaError) as foreign:
            jobs.cancel_http(make_ctx(self.db, service=self.service), {"params": {"key": OTHER}, "body": {}, "query": {}})
        self.assertEqual(foreign.exception.status, 404)


class Costs(Base):
    def cloud(self, run=None, estimate=lambda job: 500):
        self.db.grants.append(grant(location="cloud", category="llm"))
        return processor("understand", "cloud-understand-1", location="cloud", category="llm", run=run, estimate=estimate)

    def test_budget_denial_no_call(self):
        calls = self.cloud()
        reserve = mock.Mock(return_value={"status": "blocked_budget", "reason": "Paid AI drafting is not switched on yet.", "httpStatus": 402})
        settle = mock.Mock()
        with mock.patch.object(providers_module, "reserve", reserve), mock.patch.object(providers_module, "settle", settle):
            self.enqueue("understand", "cloud-understand-1")
            summary = self.tick()
        self.assertEqual(calls, [], "the provider is never called without a reservation")
        self.assertEqual(summary["blocked"], 1)
        self.assertEqual(self.db.cap(DOC, "understand")["state"], "blocked_budget")
        job = self.db.job_by_cap("understand")
        self.assertEqual((job["status"], job["category"]), ("blocked", "budget"))
        kwargs = reserve.call_args.kwargs
        self.assertEqual(kwargs["capability"], "llm")
        self.assertEqual(kwargs["estimate_usd_micro"], 500)
        self.assertEqual(kwargs["key"], f"job:{job['id']}:1")
        settle.assert_not_called()

    def test_unknown_estimate_blocks_paid_work(self):
        calls = self.cloud(estimate=lambda job: None)
        reserve = mock.Mock()
        with mock.patch.object(providers_module, "reserve", reserve):
            self.enqueue("understand", "cloud-understand-1")
            self.tick()
        reserve.assert_not_called()
        self.assertEqual(calls, [])
        self.assertEqual(self.db.cap(DOC, "understand")["state"], "blocked_budget")

    def test_cloud_without_grant_blocked_permission_no_job(self):
        processor("understand", "cloud-understand-1", location="cloud", category="llm", estimate=lambda job: 500)
        out = self.enqueue("understand", "cloud-understand-1")
        self.assertIsNone(out["job"])
        self.assertEqual(out["state"], "blocked_permission")
        self.assertEqual(self.db.jobs, {})
        self.assertEqual(self.db.cap(DOC, "understand")["state"], "blocked_permission")

    def test_settlement_once_per_attempt(self):
        attempts = []

        def flaky_then_ok(job):
            attempts.append(job.attempt)
            if len(attempts) == 1:
                raise AlphaError("The provider could not be reached.", 503, code="library_provider_timeout")
            return {"state": "ready", "annotations": [{"field": "topic", "value": "Brahms"}],
                    "provider": {"provider": "gateway", "model": "m", "cost": {"kind": "actual", "usdMicro": 321}}}
        self.cloud(run=flaky_then_ok)
        reservations = []
        reserve = mock.Mock(side_effect=lambda cur, ws, member, **kw: reservations.append(kw["key"]) or {"status": "reserved", "reservationId": "r-" + kw["key"], "duplicate": False})
        settle = mock.Mock(return_value={"state": "actual"})
        with mock.patch.object(providers_module, "reserve", reserve), mock.patch.object(providers_module, "settle", settle):
            self.enqueue("understand", "cloud-understand-1")
            self.tick()
            job = self.db.job_by_cap("understand")
            self.db.now = job["next_at"]
            self.tick()
        self.assertEqual(reservations, [f"job:{job['id']}:1", f"job:{job['id']}:2"])
        self.assertEqual(settle.call_count, 2, "each attempt's reservation is settled exactly once")
        first, second = settle.call_args_list
        self.assertTrue(first.kwargs.get("failed") is None or first.kwargs.get("failed") is False)
        self.assertEqual(second.args[3].cost, {"kind": "actual", "usdMicro": 321})
        self.assertEqual(self.db.cap(DOC, "understand")["state"], "ready")
        self.assertEqual(len(self.writer_calls["annotations"]), 1)
        self.assertEqual(job["reservation"]["settled"], True)

    def test_revocation_during_job_writes_nothing(self):
        def revoke_mid_job(job):
            self.db.grants.clear()
            self.db.grant_revision += 1
            return {"state": "ready", "segments": [{"text": "x"}], "annotations": [{"field": "topic", "value": "y"}],
                    "provider": {"provider": "gateway", "model": "m", "cost": {"kind": "unknown", "usdMicro": None}}}
        self.cloud(run=revoke_mid_job)
        reserve = mock.Mock(return_value={"status": "reserved", "reservationId": "r1", "duplicate": False})
        settle = mock.Mock(return_value={"state": "estimated_unknown"})
        with mock.patch.object(providers_module, "reserve", reserve), mock.patch.object(providers_module, "settle", settle):
            self.enqueue("understand", "cloud-understand-1")
            summary = self.tick()
        self.assertEqual(summary["blocked"], 1, summary)
        self.assertEqual(self.writer_calls, {"segments": [], "embeddings": [], "annotations": []})
        self.assertEqual(self.db.cap(DOC, "understand")["state"], "blocked_permission")
        self.assertEqual(self.db.job_by_cap("understand")["status"], "blocked")
        settle.assert_called_once()  # the provider ran; its cost is settled even though nothing is kept

    def test_revocation_cancelled_job_writes_nothing(self):
        def lifecycle_cancels(job):
            # lifecycle.propagate_revocation's effect on an in-flight job, inside the revoking transaction.
            row = self.db.job_by_cap("understand")
            row.update(status="cancelled", lease=None, category="permission", code="grant_revoked")
            self.db.caps[(WS, DOC, "understand")]["state"] = "blocked_permission"
            self.db.grants.clear()
            self.db.grant_revision += 1
            return {"state": "ready", "segments": [{"text": "x"}]}
        self.cloud(run=lifecycle_cancels)
        with mock.patch.object(providers_module, "reserve", mock.Mock(return_value={"status": "reserved", "reservationId": "r1", "duplicate": False})), \
                mock.patch.object(providers_module, "settle", mock.Mock()):
            self.enqueue("understand", "cloud-understand-1")
            self.tick()
        self.assertEqual(self.writer_calls["segments"], [])
        self.assertEqual(self.db.cap(DOC, "understand")["state"], "blocked_permission")

    def test_writer_absent_fails_capability_unavailable(self):
        processor()
        self.enqueue()
        with mock.patch.dict(sys.modules, {PKG + ".segments": None}):
            self.tick()
        cap = self.db.cap(DOC, "extract")
        self.assertEqual((cap["state"], cap["error_code"]), ("failed", "library_capability_unavailable"))


# --- intake ------------------------------------------------------------------------------------------------------------
PUBLIC = {"news.example.org": "93.184.216.34", "docs.example.org": "93.184.216.35", "rebind.example.net": "127.0.0.1",
          "meta.example.net": "169.254.169.254", "ula.example.net": "fd00::1", "cgnat.example.net": "100.64.0.1",
          "mapped.example.net": "::ffff:127.0.0.1", "nat64.example.net": "64:ff9b::7f00:1", "zero.example.net": "0.0.0.0"}


class Net:
    def __init__(self, responses=None, answers=None):
        self.responses = list(responses or [])
        self.answers = dict(PUBLIC, **(answers or {}))
        self.resolved = []
        self.connected = []

    def resolver(self, host, port, type=None):
        self.resolved.append(host)
        found = self.answers.get(host)
        if found is None:
            raise OSError("no such host")
        values = found if isinstance(found, list) else [found]
        return [(None, None, None, "", (v, port)) for v in values]

    def connector(self, scheme, host, address, port, path, timeout, deadline, clock):
        self.connected.append((scheme, host, address, port, path))
        if not self.responses:
            raise AssertionError("unexpected fetch")
        return self.responses.pop(0)


def response(status=200, body=b"", **headers):
    return {"status": status, "headers": {k.replace("_", "-").lower(): v for k, v in headers.items()}, "body": body}


class Links(Base):
    def fetch(self, url, net):
        return intake.fetch_link(url, resolver=net.resolver, connector=net.connector)

    def blocked(self, url, net, code="library_link_blocked"):
        with self.assertRaises(AlphaError) as caught:
            self.fetch(url, net)
        self.assertEqual(caught.exception.code, code, (url, str(caught.exception)))
        return caught.exception

    def test_link_ssrf_redirect_blocked(self):
        net = Net([response(302, location="http://169.254.169.254/latest/meta-data/")])
        self.blocked("https://news.example.org/story", net)
        self.assertEqual(len(net.connected), 1, "the metadata address is never contacted")
        net = Net([response(301, location="http://rebind.example.net/admin")])
        self.blocked("https://news.example.org/story", net)
        self.assertEqual([c[2] for c in net.connected], ["93.184.216.34"])
        net = Net([response(302, location="file:///etc/passwd")])
        self.blocked("https://news.example.org/story", net, "library_link_scheme")
        for url in ("http://localhost/", "http://[::1]/", "http://10.0.0.5/", "http://2130706433/", "http://metadata.google.internal/",
                    "http://meta.example.net/", "http://ula.example.net/", "http://cgnat.example.net/", "http://mapped.example.net/",
                    "http://nat64.example.net/", "http://zero.example.net/", "http://user:pw@news.example.org/", "http://news.example.org:8080/"):
            net = Net()
            with self.assertRaises(AlphaError) as caught:
                self.fetch(url, net)
            self.assertIn(caught.exception.code, ("library_link_blocked", "library_link_credentials", "library_link_port"), url)
            self.assertEqual(net.connected, [], url)
        net = Net(answers={"mixed.example.org": ["93.184.216.34", "10.1.2.3"]})
        self.blocked("https://mixed.example.org/", net)
        loop = [response(302, location=f"https://news.example.org/{n}") for n in range(5)]
        net = Net(loop)
        self.blocked("https://news.example.org/0", net, "library_link_redirects")
        self.assertEqual(len(net.connected), 4, "initial request plus at most 3 redirects")
        # Through the route: nothing is stored when the fetch is refused.
        with mock.patch.object(intake, "RESOLVER", Net().resolver), mock.patch.object(intake, "CONNECTOR", Net().connector):
            with self.assertRaises(AlphaError):
                intake.link_http(make_ctx(self.db, service=self.service), {"params": {}, "query": {}, "body": {"url": "http://localhost:80/", "idempotencyKey": "link-key-0000000001"}})
        self.assertEqual((self.storage.puts, self.db.inserted_assets), ([], []))

    def test_link_pins_vetted_ip(self):
        net = Net([response(200, b"<html><title>Recital</title><body><p>Hello</p></body></html>", content_type="text/html; charset=utf-8")])
        self.fetch("https://news.example.org/a?b=1#frag", net)
        self.assertEqual(net.resolved, ["news.example.org"], "resolved exactly once per hop")
        self.assertEqual(net.connected, [("https", "news.example.org", "93.184.216.34", 443, "/a?b=1")])

    def test_link_capture_provenance_sanitized_and_idempotent(self):
        html = (b"<html><head><title>Spring recital</title><script>steal()</script></head><body><h1>Programme</h1>"
                b"<p>Brahms Op. 118</p><style>p{}</style></body></html>")
        net = Net([response(302, location="/final"), response(200, html, content_type="text/html; charset=utf-8")])
        body = {"url": "https://news.example.org/start", "idempotencyKey": "link-key-0000000002"}
        with mock.patch.object(intake, "RESOLVER", net.resolver), mock.patch.object(intake, "CONNECTOR", net.connector):
            out = intake.link_http(make_ctx(self.db, service=self.service), {"params": {}, "query": {}, "body": body})
            again = intake.link_http(make_ctx(self.db, service=self.service), {"params": {}, "query": {}, "body": body})
        self.assertEqual(out["_status"], 201)
        self.assertEqual(len(self.storage.puts), 1, "a replayed key neither refetches nor stores twice")
        self.assertEqual(len(net.connected), 2)
        self.assertTrue(again["replayed"])
        self.assertEqual(again["asset"]["assetRef"], out["asset"]["assetRef"])
        stored = self.storage.puts[0][2].decode()
        self.assertIn("Brahms Op. 118", stored)
        self.assertNotIn("steal", stored)
        self.assertEqual(self.storage.puts[0][3], "text/plain")
        row = self.db.inserted_assets[0]
        self.assertEqual((row["source_kind"], row["kind"], row["mime"], row["title"]), ("link", "document", "text/plain", "Spring recital"))
        prov = row["provenance"]
        self.assertEqual(prov["sourceUrl"], "https://news.example.org/start")
        self.assertEqual(prov["finalUrl"], "https://news.example.org/final")
        self.assertRegex(prov["retrievedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(prov["redirects"], 1)
        self.assertEqual(self.library.capacity_checks, [len(stored.encode())], "same quota path as uploads")
        self.assertEqual(out["status"], "queued")
        with self.assertRaises(AlphaError) as conflict:
            with mock.patch.object(intake, "RESOLVER", net.resolver), mock.patch.object(intake, "CONNECTOR", net.connector):
                intake.link_http(make_ctx(self.db, service=self.service), {"params": {}, "query": {}, "body": {"url": "https://news.example.org/other", "idempotencyKey": body["idempotencyKey"]}})
        self.assertEqual(conflict.exception.status, 409)

    def test_link_login_wall_and_unavailable_are_honest(self):
        net = Net([response(401)])
        self.blocked("https://news.example.org/private", net, "library_link_login_required")
        wall = b"<html><body><form><input name=user><input type='password' name=pw></form></body></html>"
        net = Net([response(200, wall, content_type="text/html")])
        self.blocked("https://news.example.org/login", net, "library_link_login_required")
        net = Net([response(404)])
        self.blocked("https://news.example.org/gone", net, "library_link_unavailable")
        net = Net([response(200, b"<html><body><script>app()</script></body></html>", content_type="text/html")])
        self.blocked("https://news.example.org/spa", net, "library_link_empty")
        net = Net([response(200, b"fake", content_type="application/pdf")])
        self.blocked("https://docs.example.org/x.pdf", net, "library_link_type")

    def test_link_quota_and_storage_paths(self):
        self.library.full = True
        net = Net([response(200, b"plain words", content_type="text/plain")])
        with mock.patch.object(intake, "RESOLVER", net.resolver), mock.patch.object(intake, "CONNECTOR", net.connector):
            with self.assertRaises(AlphaError) as full:
                intake.link_http(make_ctx(self.db, service=self.service), {"params": {}, "query": {}, "body": {"url": "https://news.example.org/t.txt", "idempotencyKey": "link-key-0000000003"}})
        self.assertEqual(full.exception.code, "library_storage_limit")
        self.assertEqual(self.storage.puts, [])
        with self.assertRaises(AlphaError) as viewer:
            intake.link_http(make_ctx(self.db, role="viewer", service=self.service), {"params": {}, "query": {}, "body": {"url": "https://news.example.org/", "idempotencyKey": "link-key-0000000004"}})
        self.assertEqual(viewer.exception.status, 403)
        with self.assertRaises(AlphaError) as missing:
            intake.link_http(make_ctx(self.db, service=SimpleNamespace(library=None)), {"params": {}, "query": {}, "body": {"url": "https://news.example.org/", "idempotencyKey": "link-key-0000000005"}})
        self.assertEqual(missing.exception.code, "library_storage_not_configured")


class Notes(Base):
    def note(self, body, role="owner"):
        return intake.note_http(make_ctx(self.db, role=role, service=self.service), {"params": {}, "query": {}, "body": body})

    def test_note_authorship_provenance_and_idempotency(self):
        body = {"text": "Idea: pair the Brahms intermezzo with a short story about rain.", "authoredByMe": True, "idempotencyKey": "note-key-00000000001"}
        out = self.note(body)
        again = self.note(body)
        self.assertEqual(len(self.storage.puts), 1)
        self.assertEqual(again["asset"]["assetRef"], out["asset"]["assetRef"])
        row = self.db.inserted_assets[0]
        self.assertEqual(row["source_kind"], "note")
        self.assertIs(row["provenance"]["authoredByMe"], True)
        self.assertEqual(row["provenance"]["author"], ACTOR)
        self.assertEqual(self.storage.puts[0][2].decode(), body["text"])
        self.assertTrue(row["filename"].endswith(".txt"))
        third = self.note({"text": "Quoted from a reviewer.", "authoredByMe": False, "idempotencyKey": "note-key-00000000002"})
        self.assertIs(self.db.inserted_assets[1]["provenance"]["authoredByMe"], False)
        self.assertNotIn("author", self.db.inserted_assets[1]["provenance"])
        self.assertEqual(third["status"], "queued")
        with self.assertRaises(AlphaError) as unstated:
            self.note({"text": "who wrote me?", "idempotencyKey": "note-key-00000000003"})
        self.assertEqual(unstated.exception.code, "library_note_authorship")
        with self.assertRaises(AlphaError) as conflict:
            self.note({**body, "text": "different"})
        self.assertEqual(conflict.exception.status, 409)
        with self.assertRaises(AlphaError) as viewer:
            self.note({**body, "idempotencyKey": "note-key-00000000004"}, role="viewer")
        self.assertEqual(viewer.exception.status, 403)


class Archives(Base):
    def test_oversized_archive_rejected(self):
        # A zip bomb in Office clothing stays rejected by the existing extractor guard (expansion ratio and size).
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml", b"<w:document>" + b"A" * (8 * 1024 * 1024) + b"</w:document>")
        bomb = out.getvalue()
        self.assertLess(len(bomb), 1024 * 1024)
        with self.assertRaises(AlphaError) as expanded:
            library_extract.extract_text(bomb, "docx")
        self.assertIn("safe limit", str(expanded.exception))
        with self.assertRaises(AlphaError):
            library_extract.extract_text(b"x" * (library_extract.MAX_FILE_BYTES + 1), "docx")
        # Declared oversize uploads are refused before any storage call (storage=None would raise otherwise).
        with self.assertRaises(AlphaError) as declared:
            UniversalLibrary(service=None, storage=None).begin(WS, "token", {"filename": "huge.zip", "mime": "application/zip", "bytes": library_extract.MAX_FILE_BYTES + 1})
        self.assertIn("50 MB", str(declared.exception))
        # Link capture refuses archives and anything above 2 MB, declared or actual.
        net = Net([response(200, b"PK\x03\x04", content_type="application/zip")])
        with self.assertRaises(AlphaError) as archive:
            intake.fetch_link("https://docs.example.org/a.zip", resolver=net.resolver, connector=net.connector)
        self.assertEqual(archive.exception.code, "library_link_type")
        net = Net([response(200, b"x" * (intake.LINK_MAX_BYTES + 1), content_type="text/plain")])
        with self.assertRaises(AlphaError) as big:
            intake.fetch_link("https://docs.example.org/a.txt", resolver=net.resolver, connector=net.connector)
        self.assertEqual(big.exception.code, "library_link_too_large")
        net = Net([response(200, b"", content_type="text/plain", content_length=str(50 * 1024 * 1024), too_large="1")])
        with self.assertRaises(AlphaError) as declared_big:
            intake.fetch_link("https://docs.example.org/b.txt", resolver=net.resolver, connector=net.connector)
        self.assertEqual(declared_big.exception.code, "library_link_too_large")
        net = Net([response(200, b"\x1f\x8b", content_type="text/plain", content_encoding="gzip")])
        with self.assertRaises(AlphaError) as encoded:
            intake.fetch_link("https://docs.example.org/c.txt", resolver=net.resolver, connector=net.connector)
        self.assertEqual(encoded.exception.code, "library_link_encoding")


class Hook(unittest.TestCase):
    def test_library_assets_hook_calls_on_asset_processed_and_never_raises(self):
        key = "b" * 32
        raw = b"# Notes\nBrahms."
        row = {"id": str(uuid.UUID(hex=key)), "object_name": key + ".md", "bytes": len(raw), "mime": "text/markdown", "etag": "e1", "kind": "document",
               "extension": "md", "attempts": 1, "created_by": ACTOR, "processing_status": "processing"}
        lease = {}

        def claim(sql, args):
            lease["token"] = args[0]
            return [(row,)]
        cur = FakeCursor()
        cur.on(r"SET processing_status='processing'", claim)
        cur.on(r"FROM public.pr_workspaces WHERE id=%s FOR UPDATE", [({},)])
        cur.on(r"to_jsonb\(a\)", lambda sql, args: [({**row, "lease_token": lease["token"]},)])
        cur.on(r"AND sha256=%s AND id<>%s", [])

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def cursor(self):
                return Conn.Cur()

            class Cur:
                def __enter__(self):
                    return cur

                def __exit__(self, *exc):
                    return False

        storage = SimpleNamespace(object_info=lambda w, c, n: {"bytes": len(raw), "mime": "text/markdown", "etag": "e1"},
                                  get_bounded=lambda w, c, n, m: raw)
        library = UniversalLibrary(service=None, storage=storage)
        hook = mock.Mock(side_effect=RuntimeError("intelligence down"))
        with mock.patch.object(jobs, "on_asset_processed", hook):
            status = library.process(Conn, WS, key)
        self.assertEqual(status, "ready")
        hook.assert_called_once_with(Conn, WS, key)


if __name__ == "__main__":
    unittest.main()
