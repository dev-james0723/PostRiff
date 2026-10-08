"""T04 — complete-scope hybrid and visual search (acceptance A023, A025–A030; A004 count isolation; A031 bench script).

FakeLibraryDB answers this module's SQL by its `/* lib:<name> */` marker and the named parameters the real statements
use. These tests prove the Python retrieval logic: scope, purpose filtering before ranking, exact-first RRF fusion,
signed cursors, server-side coverage/facets and honest degradation. They do not prove PostgreSQL behaviour (tsvector,
CJK tokens, pgvector kNN); tests/phase2/postgres_library_intelligence_search.py does that in cloud CI. Synthetic vectors
here are fixtures, never evidence of semantic quality.
"""
import hashlib
import io
import json
import math
import os
import re
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from library_intelligence_fakes import ACTOR, WS, grant
from postriff_alpha.domain import AlphaError
from postriff_phase2.permissions import Membership
from postriff_phase2.library_intelligence import contracts as c
from postriff_phase2.library_intelligence import policy, providers, textnorm
from postriff_phase2.library_intelligence import cursors, index, search
from postriff_phase2.site_agent import library_reads
from postriff_phase2.site_agent.tools import Context as ToolContext

ROOT = Path(__file__).resolve().parents[1]
OTHER_WS = "22222222-2222-2222-2222-222222222222"
BASE = 1_780_000_000.0
NOW = 1_790_000_000.0
ENV = {"RAFII_LIBRARY_RETRIEVAL_ENABLED": "1"}
TEXT_MODEL = "openai/text-embedding-3-large"


def key(n, ws=WS):
    return format(n + (0 if ws == WS else 10**9), "032x")


def sha(n, ws=WS):
    return hashlib.sha256(f"{ws}:{n}".encode()).hexdigest()


def unit(dims, hot):
    """Synthetic deterministic fixture vector (not a semantic embedding)."""
    v = [0.0] * dims
    for i, w in hot.items():
        v[i] = float(w)
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def vec_text(v):
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def parse_vec(text):
    return [float(x) for x in text.strip("[]").split(",")]


def tokens(text):
    return set(textnorm.search_terms(text).split())


class FakeLibraryDB:
    def __init__(self):
        self.assets, self.labels, self.collections, self.items, self.overrides = [], [], [], [], []
        self.segments, self.chunks, self.embeddings, self.capabilities, self.usage, self.grants = [], [], [], [], [], []
        self.revision = {WS: 0, OTHER_WS: 0}
        self.generation = {WS: 1, OTHER_WS: 1}
        self.vector = True
        self.now = NOW
        self.fail = set()
        self._n = 0

    # --- seeding ---------------------------------------------------------------------------------------------------
    def add_asset(self, n, *, ws=WS, filename=None, title=None, kind="document", created=None, status="ready", sha256=None,
                  source_id=None, media=None, tags=(), lineage=None, version_no=1, indexing="ready", mime=None):
        a = {"ws": ws, "key": key(n, ws), "lineage": lineage or key(n, ws), "versionNo": version_no, "filename": filename or f"file-{n:05d}.md",
             "title": title, "tags": list(tags), "kind": kind, "mime": mime or {"document": "text/markdown", "audio": "audio/mpeg", "file": "application/octet-stream"}.get(kind, "text/markdown"),
             "bytes": 100 + n, "sha": sha256 if sha256 is not None else sha(n, ws), "status": status, "indexing": indexing,
             "transcription": "not_applicable", "sourceId": source_id, "media": dict(media or {}), "created": BASE + n if created is None else created}
        self.assets.append(a)
        return a

    def add_segment(self, asset, text, *, ordinal=0, kind="text", language=None, locator=None, created=None, superseded=None, nv=None):
        self._n += 1
        sid = format(self._n, "032x")
        self.segments.append({"ws": asset["ws"], "id": sid, "ak": asset["lineage"], "vk": asset["key"], "ordinal": ordinal, "kind": kind, "text": text,
                              "language": language, "locator": locator, "created": asset["created"] + 1 if created is None else created,
                              "superseded": superseded, "nv": textnorm.NORMALIZER_VERSION if nv is None else nv, "terms": tokens(text)})
        return sid

    def add_chunk(self, asset, text, ordinal=0):
        self.chunks.append({"ws": asset["ws"], "key": asset["key"], "ordinal": ordinal, "text": text})

    def add_embedding(self, asset, vector, *, modality="text", model=TEXT_MODEL, gen=1, segment=None, status="active", created=None):
        self.embeddings.append({"ws": asset["ws"], "ak": asset.get("lineage", asset["key"]), "vk": asset["key"], "sid": segment, "modality": modality,
                                "model": model, "dims": len(vector), "gen": gen, "status": status, "consent": 0,
                                "created": (asset.get("created") or 0) + 2 if created is None else created, "vector": list(vector)})

    def add_capability(self, asset, capability, state):
        self.capabilities.append({"ws": asset["ws"], "key": asset["key"], "capability": capability, "state": state})

    def cursor(self):
        return FakeCur(self)

    # --- statements --------------------------------------------------------------------------------------------------
    def _active_segments(self, a):
        return [s for s in self.segments if s["ws"] == a["w"] and s["superseded"] is None and s["created"] <= a["t"]]

    def q_clock(self, a):
        return [(self.now,)]

    def q_universe(self, a):
        return [(x["key"], x["lineage"], x["versionNo"], x["filename"], x["title"], list(x["tags"]), x["kind"], x["mime"], x["bytes"], x["sha"],
                 x["status"], x["indexing"], x["transcription"], x["sourceId"], dict(x["media"]), x["created"])
                for x in self.assets if x["ws"] == a["w"] and x["status"] not in ("deleting", "duplicate")]

    def q_labels(self, a):
        return [(l["key"], l["title"], l["tags"]) for l in self.labels if l["ws"] == a["w"] and l["key"] in a["keys"]]

    def q_collection(self, a):
        return [(x["name"],) for x in self.collections if x["ws"] == a["w"] and x["id"] == str(a["id"]).replace("-", "")]

    def q_collection_members(self, a):
        cid = str(a["id"]).replace("-", "")
        excluded = {o["key"] for o in self.overrides if o["ws"] == a["w"] and o["collection"] == cid and o["mode"] == "exclude"}
        return [(i["key"],) for i in self.items if i["ws"] == a["w"] and i["collection"] == cid and i["key"] not in excluded]

    def q_segment_stats(self, a):
        out = {}
        for s in self._active_segments(a):
            cur, count = out.get(s["vk"], (False, 0))
            out[s["vk"]] = (cur or s["nv"] == a["nv"], count + 1)
        return [(k, v[0], v[1]) for k, v in out.items()]

    def q_embedding_stats(self, a):
        out = {}
        for e in self.embeddings:
            if e["ws"] == a["w"] and e["status"] == "active" and e["created"] <= a["t"]:
                k = (e["vk"], e["modality"], e["model"], e["dims"], e["gen"])
                out[k] = out.get(k, 0) + 1
        return [(*k, n) for k, n in out.items()]

    def q_capability_stats(self, a):
        return [(x["key"], x["capability"], x["state"]) for x in self.capabilities if x["ws"] == a["w"] and x["state"] in ("queued", "processing", "failed")]

    def q_capability_filter(self, a):
        return [(x["key"], x["state"]) for x in self.capabilities if x["ws"] == a["w"] and x["capability"] == a["cap"]]

    def q_usage(self, a):
        return [(k,) for ws, k in self.usage if ws == a["w"]]

    def q_languages(self, a):
        langs = set(a["langs"])
        return [(s["vk"],) for s in self.segments if s["ws"] == a["w"] and s["superseded"] is None and s["language"]
                and (s["language"] in langs or s["language"].split("-")[0] in langs)]

    def q_lexical_segments(self, a):
        terms = a["tsq"].split(" & ")
        best = {}
        for s in self._active_segments(a):
            if s["nv"] != a["nv"] or s["vk"] not in a["keys"] or not set(terms) <= s["terms"]:
                continue
            rank = len(terms) / (1 + math.log(1 + len(s["terms"])))
            if s["vk"] not in best or (rank, -s["ordinal"]) > (best[s["vk"]][0], -best[s["vk"]][2]):
                best[s["vk"]] = (rank, s["id"], s["ordinal"])
        ordered = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0]))
        return [(k, v[1], v[0], len(ordered)) for k, v in ordered][: a["k"]]

    def q_lexical_chunks(self, a):
        ids = {str(i).replace("-", "") for i in a["ids"]}
        latin = a["tsq"].split(" & ") if a["tsq"] else []
        best = {}
        for ch in self.chunks:
            if ch["ws"] != a["w"] or ch["key"] not in ids:
                continue
            words = set(re.findall(r"[0-9a-z]+", ch["text"].lower()))
            if not set(latin) <= words or not all(re.search(rx, ch["text"]) for rx in a["rx"]):
                continue
            if ch["key"] not in best or ch["ordinal"] < best[ch["key"]]:
                best[ch["key"]] = ch["ordinal"]
        ordered = sorted(best.items())
        return [(k, o, 1.0, len(ordered)) for k, o in ordered][: a["k"]]

    def q_vector_column(self, a):
        return [(1,)] if self.vector else []

    def _active_segment(self, sid):
        return any(s["id"] == sid and s["superseded"] is None for s in self.segments)

    def q_knn(self, a):
        if "knn" in self.fail:
            raise RuntimeError("synthetic vector failure")
        q = parse_vec(a["vec"])
        rows = []
        for e in self.embeddings:
            if (e["ws"] == a["w"] and e["status"] == "active" and e["modality"] == a["modality"] and e["model"] == a["model"] and e["dims"] == a["dims"]
                    and e["gen"] == a["gen"] and e["created"] <= a["t"] and e["vk"] in a["keys"] and (e["sid"] is None or self._active_segment(e["sid"]))):
                rows.append((e["vk"], e["sid"], 1 - sum(x * y for x, y in zip(q, e["vector"]))))
        rows.sort(key=lambda r: (r[2], r[0]))
        return rows[: a["k"]]

    def q_visual_reference(self, a):
        for e in self.embeddings:
            if (e["ws"] == a["w"] and e["vk"] == a["key"] and e["status"] == "active" and e["modality"] == "visual" and e["model"] == a["model"]
                    and e["dims"] == a["dims"] and e["gen"] == a["gen"]):
                return [(vec_text(e["vector"]),)]
        return []

    def q_passages(self, a):
        terms = set(a["tsq"].split(" & "))
        out = []
        for s in self._active_segments(a):
            if s["vk"] in a["keys"] and s["nv"] == a["nv"] and terms <= s["terms"]:
                out.append((s["vk"], s["id"], s["text"], s["locator"], s["kind"], s["language"], len(terms) / (1 + math.log(1 + len(s["terms"]))), s["ordinal"]))
        return out

    def q_segments_by_id(self, a):
        ids = {str(i).replace("-", "") for i in a["ids"]}
        return [(s["vk"], s["id"], s["text"], s["locator"], s["kind"], s["language"], s["ordinal"]) for s in self.segments
                if s["ws"] == a["w"] and s["id"] in ids and s["superseded"] is None]

    def q_segments_for_read(self, a):
        rows = [s for s in self.segments if s["ws"] == a["w"] and s["vk"] == a["key"] and s["superseded"] is None]
        rows.sort(key=lambda s: s["ordinal"])
        return [(s["id"], s["text"], s["locator"], s["kind"], s["language"], s["ordinal"]) for s in rows][: a["n"]]

    def q_chunk_passages(self, a):
        ids = {str(i).replace("-", "") for i in a["ids"]}
        return [(ch["key"], ch["ordinal"], ch["text"]) for ch in self.chunks if ch["ws"] == a["w"] and ch["key"] in ids]

    def q_hit_capabilities(self, a):
        return [(x["key"], x["capability"], x["state"], None, None, False, None, None, NOW) for x in self.capabilities if x["ws"] == a["w"] and x["key"] in a["keys"]]

    def q_embeddings_supersede(self, a):
        n = 0
        for e in self.embeddings:
            if e["ws"] == a["w"] and e["vk"] == a["vk"] and e["modality"] == a["modality"] and e["model"] == a["model"] and e["status"] == "active":
                e["status"] = "superseded"
                n += 1
        return n

    def q_embeddings_insert(self, a):
        self.embeddings.append({"ws": a["w"], "ak": a["ak"], "vk": a["vk"], "sid": a["sid"], "modality": a["modality"], "model": a["model"], "dims": a["dims"],
                                "gen": a["gen"], "status": "active", "consent": a["consent"], "created": self.now, "vector": parse_vec(a["vec"])})
        return 1

    def q_embeddings_inactive_segments(self, a):
        n = 0
        for e in self.embeddings:
            if e["ws"] == a["w"] and e["vk"] == a["vk"] and e["status"] == "active" and e["sid"] and not self._active_segment(e["sid"]):
                e["status"] = "superseded"
                n += 1
        return n

    def q_embeddings_tombstone(self, a):
        n = 0
        for e in self.embeddings:
            if e["ws"] == a["w"] and e["status"] == "active" and (e["ak"] in a["keys"] or e["vk"] in a["keys"]) and (a["modality"] is None or e["modality"] == a["modality"]) \
                    and (not a["cloud_only"] or not e["model"].startswith("local/")):
                e["status"] = a["status"]
                n += 1
        return n

    def versions_load(self, args):
        ws, ids = args
        wanted = {str(i).replace("-", "") for i in ids}
        rows = []
        for x in self.assets:
            if x["ws"] == ws and x["key"] in wanted:
                rows.append((uuid.UUID(hex=x["key"]), uuid.UUID(hex=x["lineage"]), x["versionNo"], ws, x["filename"], x["title"], "filename", None, list(x["tags"]),
                             x["kind"], x["mime"], "md", x["bytes"], x["sha"], x["status"], "not_applicable", x["indexing"], x["transcription"], x["sourceId"],
                             "upload", dict(x["media"]), None, {}, x["created"]))
        return rows

    def grant_rows(self, ws):
        return [(g["id"], g["grantType"], g["scopeKind"], g["scopeKey"], g["memberKeys"], g["purpose"], g["location"], g["category"], {}, ACTOR, 1, 1.0)
                for g in self.grants]


class FakeCur:
    def __init__(self, db):
        self.db, self.executed, self._rows, self.rowcount = db, [], [], 0

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        marker = re.search(r"/\* lib:([a-z\-]+) \*/", sql)
        if marker:
            name = marker.group(1)
            if name in self.db.fail and name != "knn":
                raise RuntimeError("synthetic database failure")
            rows = getattr(self.db, "q_" + name.replace("-", "_"))(args)
        elif "FOR SHARE" in sql and "pr_library_policy" in sql:
            rows = [(self.db.revision.get(args[0], 0),)]
        elif "grant_revision,index_generation,organization_revision FROM public.pr_library_policy" in sql:
            rows = [(self.db.revision.get(args[0], 0), self.db.generation.get(args[0], 1), 0)]
        elif "FROM public.pr_library_grants" in sql:
            rows = self.db.grant_rows(args[0])
        elif re.search(r"FROM public.pr_library_assets WHERE workspace_id=%s AND id=ANY", sql):
            rows = self.db.versions_load(args)
        elif "FROM public.pr_library_labels" in sql:
            rows = self.db.q_labels({"w": args[0], "keys": args[1]})
        elif re.match(r"\s*(SAVEPOINT|RELEASE|ROLLBACK|SET LOCAL)", sql):
            rows = []
        elif "to_regclass" in sql:
            rows = [("public.pr_library_segments",)]
        else:
            raise AssertionError("unexpected SQL: " + sql[:160])
        if isinstance(rows, int):
            self._rows, self.rowcount = [], rows
        else:
            self._rows = list(rows or [])
            self.rowcount = len(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def statements(self, marker):
        return [(s, a) for s, a in self.executed if f"/* lib:{marker} */" in s]


class FakeEmbedder:
    def __init__(self, vector=None, *, unavailable=None, fail=False, model=TEXT_MODEL):
        self.vector, self.unavailable, self.fail, self._model, self.calls = vector, unavailable, fail, model, 0

    def model(self, capability):
        return self._model

    def require(self, capability):
        if self.unavailable:
            raise providers.ProviderUnavailable(capability, self.unavailable)

    def estimate(self, capability, *, units):
        return 1

    def embed(self, texts, *, dims=1024):
        self.calls += 1
        self.require("embedding")
        if self.fail:
            raise AlphaError("The provider refused the request.", 502, code="library_provider_failed")
        return providers.ProviderResult([list(self.vector) for _ in texts], "fake-gateway", self._model, 1)


def make_ctx(db, *, ws=WS, role="owner", state=None, grants=(), revision=None, generation=None, embedder=None, prefill=True):
    cur = db.cursor()
    ctx = c.LibraryContext(workspace_id=ws, actor=ACTOR, membership=Membership(role), state=state or {"sources": [], "phase2": {"assets": [], "jobs": [], "reviews": []}},
                           cur=cur, now=db.now, service=SimpleNamespace(library_intelligence=SimpleNamespace(providers=embedder or FakeEmbedder(unavailable="embeddings_disabled"))))
    if prefill:
        ctx.caches["policy"] = {"grantRevision": db.revision.get(ws, 0) if revision is None else revision,
                                "indexGeneration": db.generation.get(ws, 1) if generation is None else generation, "organizationRevision": 0}
        ctx.caches["grants"] = list(grants)
    return ctx


def run(ctx, **request):
    with mock.patch.dict(os.environ, ENV):
        return search.search_library(ctx, request)


def reasons(hit):
    return {r["kind"] for r in hit["matchReasons"]}


def free_budget():
    """Synthetic budget admission for unit tests: no ledger, nothing charged."""
    return mock.patch.multiple(index, _reserve=lambda *a, **k: {"status": "reserved", "reservationId": "synthetic"}, _settle=lambda *a, **k: None)


def png(colour, *, stripes=None, size=(96, 64)):
    from PIL import Image, ImageDraw
    image = Image.new("RGB", size, colour)
    if stripes:
        draw = ImageDraw.Draw(image)
        for x in range(0, size[0], 12):
            draw.rectangle([x, 0, x + 5, size[1]], fill=stripes)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def legacy_photo(n, *, width=1080, height=1920, created=None, mime="image/jpeg", name=None, duration=None):
    item = {"id": key(n), "mime": mime, "width": width, "height": height, "originalFilename": name or f"photo-{n}.jpg", "hash": sha(n),
            "createdAt": BASE + n if created is None else created, "bytes": 2000}
    if duration is not None:
        item["duration"] = duration
    return item


class CompleteScope(unittest.TestCase):
    def test_asset_1001_exact_match(self):
        db = FakeLibraryDB()
        assets = [db.add_asset(i, filename=f"brief-{i:04d}.pdf", kind="document") for i in range(1, 1102)]
        photo = legacy_photo(5000, created=BASE - 10)
        ctx = make_ctx(db, state={"sources": [], "phase2": {"assets": [photo], "jobs": [], "reviews": []}})
        newest_first = sorted(assets, key=lambda a: -a["created"])
        p201, p1001 = newest_first[200], newest_first[1000]

        by_id = run(ctx, query=p1001["key"])
        self.assertEqual(by_id["hits"][0]["assetRef"]["versionId"], p1001["key"])
        self.assertIn("id", reasons(by_id["hits"][0]))
        dashed = run(ctx, query=str(uuid.UUID(hex=p1001["key"])))
        self.assertEqual(dashed["hits"][0]["assetRef"]["versionId"], p1001["key"])

        by_hash = run(ctx, query=p201["sha"][:10])
        self.assertEqual(by_hash["hits"][0]["assetRef"]["versionId"], p201["key"])
        self.assertIn("hash", reasons(by_hash["hits"][0]))

        by_name = run(ctx, query=p1001["filename"])
        self.assertEqual(by_name["hits"][0]["assetRef"]["versionId"], p1001["key"])
        self.assertIn("filename", reasons(by_name["hits"][0]))

        unnamed = {"id": key(6000), "mime": "image/jpeg", "createdAt": BASE + 3}
        generic = run(make_ctx(db, state={"sources": [], "phase2": {"assets": [photo, unnamed], "jobs": [], "reviews": []}}), query="Photo")
        self.assertNotIn(unnamed["id"], [h["assetRef"]["versionId"] for h in generic["hits"]], "a fallback label is neither a title nor a name match")
        self.assertNotIn("exact title", [r.get("detail") for h in generic["hits"] for r in h["matchReasons"]])

        by_dims = run(ctx, query="1080x1920")
        self.assertEqual(by_dims["hits"][0]["assetRef"]["versionId"], photo["id"])
        self.assertIn("dimensions", reasons(by_dims["hits"][0]))
        self.assertEqual(by_dims["coverage"]["accessibleAssetCount"], 1102)

        universe_sql = [s for s, _ in ctx.cur.statements("universe")]
        self.assertTrue(universe_sql)
        for statement in universe_sql:
            self.assertNotIn("LIMIT", statement.upper(), "the candidate universe has no newest-N cap")

    def test_old_segment_retrieval(self):
        db = FakeLibraryDB()
        assets = [db.add_asset(i) for i in range(1, 401)]
        oldest = assets[0]
        for a in assets[1:]:
            db.add_segment(a, f"Rehearsal log {a['key'][-4:]} with general notes.")
        db.add_segment(oldest, "Brahms sonata fingering from the 2019 masterclass, bars 12 to 20.", ordinal=3,
                       locator={"kind": "page", "page": 3, "section": "Masterclass"})
        db.add_segment(oldest, "Obsolete wording about Brahms masterclass fingering.", ordinal=4, superseded=NOW - 5)
        ctx = make_ctx(db)
        result = run(ctx, query="Brahms masterclass fingering")
        self.assertEqual([h["assetRef"]["versionId"] for h in result["hits"]], [oldest["key"]])
        hit = result["hits"][0]
        self.assertEqual(hit["locator"], {"kind": "page", "page": 3, "section": "Masterclass"})
        self.assertEqual(hit["locatorLabel"], "page 3, Masterclass")
        self.assertIn("Brahms", hit["snippet"])
        self.assertNotIn("Obsolete", hit["snippet"])
        self.assertIn("lexical", reasons(hit))
        self.assertTrue(hit["segmentId"])
        self.assertEqual(result["coverage"]["modesApplied"], ["lexical"])

    def test_legacy_chunk_fallback_is_labelled(self):
        db = FakeLibraryDB()
        segmented = db.add_asset(1)
        db.add_segment(segmented, "Harbour concert programme notes")
        legacy = db.add_asset(2)
        db.add_chunk(legacy, "Old extracted text: 維港音樂會 harbour concert in 2021.")
        ctx = make_ctx(db)
        result = run(ctx, query="harbour concert")
        hits = {h["assetRef"]["versionId"]: h for h in result["hits"]}
        self.assertEqual(set(hits), {segmented["key"], legacy["key"]})
        detail = " ".join(r.get("detail") or "" for r in hits[legacy["key"]]["matchReasons"])
        self.assertIn("not yet segmented", detail)
        self.assertIn("harbour concert", hits[legacy["key"]]["snippet"])
        chunk_sql = ctx.cur.statements("lexical-chunks")
        self.assertEqual(len(chunk_sql), 1)
        self.assertEqual({str(i).replace("-", "") for i in chunk_sql[0][1]["ids"]}, {legacy["key"]}, "only unsegmented assets use the legacy index")
        cjk = run(ctx, query="维港音乐会")
        self.assertEqual([h["assetRef"]["versionId"] for h in cjk["hits"]], [legacy["key"]], "Simplified query finds Traditional legacy text")


class Permissions(unittest.TestCase):
    def setUp(self):
        self.db = db = FakeLibraryDB()
        self.granted = db.add_asset(1)
        self.collection_member = db.add_asset(2)
        self.ungranted = db.add_asset(3)
        self.prohibited = db.add_asset(4, source_id="src-prohibited")
        self.pending = db.add_asset(5, status="processing")
        for a in (self.granted, self.collection_member, self.ungranted, self.prohibited, self.pending):
            db.add_segment(a, "Victoria harbour sunset rehearsal")
        self.state = {"sources": [{"id": "src-prohibited", "active": True, "sourcePolicy": "prohibited", "egressConsent": ["local", "cloud"], "facts": [],
                                   "origin": {"kind": "library", "sha256": self.prohibited["sha"]}}], "phase2": {"assets": [], "jobs": [], "reviews": []}}
        self.grants = [grant("answer", scope="asset", key=self.granted["key"], gid="1" * 32),
                       grant("answer", scope="collection", key="9" * 32, members=[self.collection_member["key"]], gid="2" * 32),
                       grant("answer", scope="asset", key=self.prohibited["key"], gid="3" * 32),
                       grant("answer", scope="asset", key=self.pending["key"], gid="4" * 32)]

    def test_permission_filtered_before_rank(self):
        ctx = make_ctx(self.db, state=self.state, grants=self.grants)
        result = run(ctx, query="harbour", purpose="answer")
        allowed = {self.granted["key"], self.collection_member["key"]}
        self.assertEqual({h["assetRef"]["versionId"] for h in result["hits"]}, allowed)
        self.assertEqual(result["coverage"]["accessibleAssetCount"], 2)
        for hit in result["hits"]:
            self.assertEqual(hit["sourceStatus"]["purpose"], "answer")
            self.assertTrue(hit["sourceStatus"]["allowed"])
            self.assertTrue(hit["sourceStatus"]["attributionOnly"], "answers attribute; they never approve facts")
        ranked = ctx.cur.statements("lexical-segments")
        self.assertEqual(len(ranked), 1)
        self.assertEqual(set(ranked[0][1]["keys"]), allowed, "denied items never reach ranking SQL")
        browse = run(make_ctx(self.db, state=self.state, grants=self.grants), query="harbour")
        self.assertEqual(len(browse["hits"]), 5, "browse sees every stored item, including ones still processing")

    def test_fast_eligibility_matches_policy(self):
        linked = self.db.add_asset(6, lineage=self.granted["key"], version_no=2)  # linked into a granted lineage after the grant
        unreviewed = self.db.add_asset(7, source_id="src-unreviewed")
        local_only = self.db.add_asset(8, source_id="src-local")
        for a in (linked, unreviewed, local_only):
            self.db.add_segment(a, "Victoria harbour sunset rehearsal")
        sources = self.state["sources"] + [
            {"id": "src-unreviewed", "active": True, "sourcePolicy": None, "egressConsent": ["local", "cloud"], "facts": [], "origin": {"kind": "library"}},
            {"id": "src-local", "active": True, "sourcePolicy": "rewrite_approval", "egressConsent": ["local"], "facts": [{"id": "f", "text": "x", "approved": True}],
             "origin": {"kind": "library", "sha256": local_only["sha"]}}]
        state = dict(self.state, sources=sources, memoryEgress={"cloud": False})
        grants = [grant("answer", scope="asset", key=self.granted["key"], members=[self.granted["key"]], gid="1" * 32)] + self.grants[1:] + [
            grant("answer", scope="asset", key=key(6), gid="8" * 32),  # no snapshot: covers exactly the named version
            grant("answer", scope="asset", key=key(7), members=[key(7)], gid="9" * 32), grant("answer", scope="asset", key=key(8), members=[key(8)], gid="d" * 32),
            grant(location="cloud", category="llm", scope="asset", key=self.granted["key"], members=[self.granted["key"]], gid="5" * 32),
            grant(location="cloud", category="llm", scope="workspace", gid="e" * 32), grant(location="cloud", category="embedding", scope="asset",
                                                                                     key=key(2), members=[key(2)], gid="f" * 32),
            grant("memory", gid="6" * 32), grant("voice", scope="asset", key=self.ungranted["key"], members=[self.ungranted["key"]], gid="7" * 32)]
        ctx = make_ctx(self.db, state=state, grants=grants)
        items = {v["versionId"]: v for v in self.db_versions(ctx)}
        items.update(search.versions.load(ctx, [self.granted["key"]]))  # the superseded first version (selection scopes reach it)
        for purpose in c.PURPOSES:
            for processing in (None, {"location": "cloud", "category": "llm"}, {"location": "local", "category": "extract"},
                               {"location": "cloud", "category": "embedding"}):
                fast = set(search.eligible_items(ctx, purpose, items, processing))
                slow = {k for k, v in items.items() if policy.authorize_source(ctx, v, purpose, processing).allowed}
                self.assertEqual(fast, slow, (purpose, processing))

    def db_versions(self, ctx):
        with mock.patch.dict(os.environ, ENV):
            current, _ = search.universe(ctx)
        return list(current.values())


class ReviewedPolicy(unittest.TestCase):
    """Shared security review (d06cc4b7): search eligibility mirrors policy exactly."""

    def test_asset_grant_covers_only_snapshotted_versions(self):
        db = FakeLibraryDB()
        v1 = db.add_asset(1)
        db.add_segment(v1, "Harbour concert notes")
        v2 = db.add_asset(2, lineage=v1["key"], version_no=2)  # a later version linked into the granted lineage
        db.add_segment(v2, "Harbour concert notes, revised")
        pinned = [grant("answer", scope="asset", key=v1["key"], members=[v1["key"]])]
        whole = run(make_ctx(db, grants=pinned), query="harbour", purpose="answer")
        self.assertEqual(whole["hits"], [], "linking a new version into a granted lineage does not widen the grant")
        old = run(make_ctx(db, grants=pinned), query="harbour", purpose="answer",
                  scope={"kind": "selection", "assetRefs": [{"assetId": v1["key"], "versionId": v1["key"], "sha256": v1["sha"]}]})
        self.assertEqual([h["assetRef"]["versionId"] for h in old["hits"]], [v1["key"]])
        named = run(make_ctx(db, grants=[grant("answer", scope="asset", key=v2["key"])]), query="harbour", purpose="answer")
        self.assertEqual([h["assetRef"]["versionId"] for h in named["hits"]], [v2["key"]], "without a snapshot an asset grant covers the named version")
        lineage_only = run(make_ctx(db, grants=[grant("answer", scope="asset", key=v1["key"])]), query="harbour", purpose="answer")
        self.assertEqual(lineage_only["hits"], [], "no lineage fallback: the lineage key never covers its later versions")

    def test_cloud_processing_honours_source_review_and_egress(self):
        db = FakeLibraryDB()
        reviewed = db.add_asset(1, source_id="src-ok")
        unreviewed = db.add_asset(2, source_id="src-unreviewed")
        local_only = db.add_asset(3, source_id="src-local")
        for a in (reviewed, unreviewed, local_only):
            db.add_segment(a, "Harbour concert notes")
        source = lambda sid, policy_name, egress, a: {"id": sid, "active": True, "sourcePolicy": policy_name, "egressConsent": egress, "facts": [],
                                                     "origin": {"kind": "library", "sha256": a["sha"]}}
        state = {"sources": [source("src-ok", "rewrite_approval", ["local", "cloud"], reviewed), source("src-unreviewed", None, ["local", "cloud"], unreviewed),
                             source("src-local", "rewrite_approval", ["local"], local_only)], "phase2": {"assets": [], "jobs": [], "reviews": []}}
        grants = [grant("answer", gid="1" * 32), grant(location="cloud", category="llm", gid="2" * 32)]
        with mock.patch.dict(os.environ, ENV):
            cloud = search.search_library(make_ctx(db, state=state, grants=grants), {"query": "harbour", "purpose": "answer"}, processing={"location": "cloud", "category": "llm"})
            local = search.search_library(make_ctx(db, state=state, grants=grants), {"query": "harbour", "purpose": "answer"})
        self.assertEqual({h["assetRef"]["versionId"] for h in cloud["hits"]}, {reviewed["key"]},
                         "an unreviewed source or one without cloud sharing never goes to a cloud model")
        self.assertEqual({h["assetRef"]["versionId"] for h in local["hits"]}, {reviewed["key"], unreviewed["key"], local_only["key"]})
        ctx = make_ctx(db, state=state, grants=grants)
        current, _ = search.universe(ctx)
        reasons = {k: policy.authorize_source(ctx, v, "answer", {"location": "cloud", "category": "llm"}).reason for k, v in current.items()}
        self.assertEqual((reasons[unreviewed["key"]], reasons[local_only["key"]]), ("policy_review_required", "egress_consent_required"))

    def test_browse_with_cloud_processing_is_not_a_bypass(self):
        db = FakeLibraryDB()
        allowed = db.add_asset(1)
        stored_only = db.add_asset(2)
        for a in (allowed, stored_only):
            db.add_segment(a, "Harbour concert notes")
        grants = [grant("answer", scope="asset", key=allowed["key"], members=[allowed["key"]], gid="1" * 32), grant(location="cloud", category="llm", gid="2" * 32)]
        with mock.patch.dict(os.environ, ENV):
            cloud = search.search_library(make_ctx(db, grants=grants), {"query": "harbour"}, processing={"location": "cloud", "category": "llm"})
            local = search.search_library(make_ctx(db, grants=grants), {"query": "harbour"}, processing={"location": "local", "category": "extract"})
            plain = search.search_library(make_ctx(db, grants=grants), {"query": "harbour"})
        self.assertEqual([h["assetRef"]["versionId"] for h in cloud["hits"]], [allowed["key"]], "browse + cloud processing is answer + processing")
        self.assertTrue(cloud["hits"][0]["sourceStatus"]["attributionOnly"])
        self.assertEqual(len(local["hits"]), 2)
        self.assertEqual(len(plain["hits"]), 2)

    def test_superseded_passages_never_resurface(self):
        db = FakeLibraryDB()
        a = db.add_asset(1)
        old = db.add_segment(a, "Original transcript wording")
        db.add_embedding(a, unit(1024, {4: 1.0}), segment=old)
        db.segments[-1]["superseded"] = NOW - 10  # a person corrected it
        fresh = db.add_segment(a, "Corrected transcript wording", created=NOW - 9)
        other = db.add_asset(2)
        other_sid = db.add_segment(other, "Unrelated words")
        db.add_embedding(other, unit(1024, {5: 1.0}), segment=other_sid)
        index._QUERY_CACHE.clear()
        with free_budget():
            result = run(make_ctx(db, embedder=FakeEmbedder(unit(1024, {4: 1.0}))), query="zzz-no-lexical-match", modes=["semantic"])
        self.assertNotIn(a["key"], {h["assetRef"]["versionId"] for h in result["hits"]}, "the superseded passage's vector is never a match")
        cur = db.cursor()
        cur.execute(search.SEGMENTS_BY_ID_SQL, {"w": WS, "ids": [str(uuid.UUID(hex=old)), str(uuid.UUID(hex=fresh))]})
        self.assertEqual([r[1] for r in cur.fetchall()], [fresh], "hydration never returns superseded text")
        self.assertEqual(index.tombstone_inactive_segments(db.cursor(), WS, a["key"]), 1)
        self.assertEqual(db.embeddings[0]["status"], "superseded")
        self.assertEqual(db.embeddings[1]["status"], "active")

    def test_corrections_and_reextraction_supersede_embeddings(self):
        from library_intelligence_fakes import FakeCursor, ctx as fake_ctx
        from postriff_phase2.library_intelligence import segments
        vk = "a" * 32
        row = (uuid.UUID(hex=vk), None, 1, WS, "talk.mp3", "Talk", "filename", None, [], "audio", "audio/mpeg", "mp3", 10, "b" * 64, "ready",
               "not_applicable", "ready", "ready", None, "upload", {}, None, {}, 1.0)
        cur = FakeCursor()
        cur.on(r"FROM public.pr_library_segments WHERE workspace_id=%s AND id=%s FOR UPDATE",
               [(uuid.UUID(int=5), vk, vk, 0, "transcript", "old words", "en", None, "asr", "1", None, None, "transcript", False)])
        cur.on(r"FROM public.pr_library_assets WHERE workspace_id=%s AND id=ANY", [row])
        cur.on(r"SELECT media FROM public.pr_library_assets", [({},)])
        cur.on(r"UPDATE public.pr_library_segments SET superseded_at=now\(\) WHERE workspace_id=%s AND id=ANY", [(1,)])
        segments.correct(fake_ctx(cur), uuid.UUID(int=5).hex, "new words")
        tombstones = [args for sql, args in cur.executed if "lib:embeddings-inactive-segments" in sql]
        self.assertEqual(tombstones, [{"w": WS, "vk": vk}], "a correction supersedes the old wording's embeddings")
        cur2 = FakeCursor().on(r"SELECT media FROM public.pr_library_assets", [({},)])
        version = {"assetId": vk, "versionId": vk, "sha256": "b" * 64, "legacy": False, "media": {}}
        segments.write_segments(cur2, WS, version, [{"kind": "transcript", "text": "re-extracted", "origin": "transcript"}], extractor="asr", extractor_version="2")
        self.assertTrue(cur2.sql(r"lib:embeddings-inactive-segments"), "re-extraction supersedes embeddings of replaced passages")
        broken = FakeCursor()
        original = broken.execute

        def failing(sql, args=()):
            if "lib:embeddings-inactive-segments" in sql:
                raise RuntimeError("synthetic failure")
            return original(sql, args)
        broken.execute = failing
        self.assertEqual(index.tombstone_inactive_segments(broken, WS, vk), 0, "cleanup failure never aborts the caller")
        self.assertTrue(broken.sql(r"ROLLBACK TO SAVEPOINT lib_tombstone"))


class ModelBound(unittest.TestCase):
    def seeded(self):
        db = FakeLibraryDB()
        self.allowed = db.add_asset(1)
        self.storage_only = db.add_asset(2)
        for a in (self.allowed, self.storage_only):
            db.add_segment(a, "Harbour concert notes")
        self.grants = [grant("answer", scope="asset", key=key(1), members=[key(1)], gid="1" * 32), grant(location="cloud", category="llm", gid="2" * 32)]
        return db

    def test_for_model_search_and_read(self):
        from postriff_phase2.library_intelligence import api, understanding
        db = self.seeded()
        ctx_for = lambda: make_ctx(db, grants=self.grants)
        with mock.patch.dict(os.environ, ENV), mock.patch.object(api, "context", lambda *a, **k: ctx_for()):
            model = api.search(None, ACTOR, WS, {"query": "harbour", "purpose": "browse"}, for_model=True)
            people = api.search(None, ACTOR, WS, {"query": "harbour"})
            card = {"assetRef": {}, "displayTitle": "Notes", "summary": {"text": "private summary"}, "topics": [{"value": "x"}], "suggestedUses": [],
                    "annotations": [{"value": "y"}], "usefulSegments": [{"id": "s", "text": "Harbour concert notes", "locator": None}]}
            with mock.patch.object(understanding, "card", lambda ctx, ref: dict(card)):
                denied = api.read(None, ACTOR, WS, {"assetRef": {"assetId": key(2), "versionId": key(2), "sha256": ""}}, for_model=True)
                allowed = api.read(None, ACTOR, WS, {"assetRef": {"assetId": key(1), "versionId": key(1), "sha256": ""}}, for_model=True)
                plain = api.read(None, ACTOR, WS, {"assetRef": {"assetId": key(2), "versionId": key(2), "sha256": ""}})
        self.assertEqual([h["assetRef"]["versionId"] for h in model["hits"]], [key(1)], "storage-only items never reach a model")
        self.assertEqual(len(people["hits"]), 2, "people still browse everything")
        self.assertEqual(model["hits"][0]["sourceStatus"]["purpose"], "answer")
        self.assertFalse(denied["modelAccess"]["allowed"])
        self.assertEqual(denied["modelAccess"]["reason"], "grant_required")
        self.assertNotIn("Harbour", json.dumps(denied))
        self.assertNotIn("private summary", json.dumps(denied))
        self.assertEqual(denied["usefulSegments"], [{"id": "s", "locator": None}])
        self.assertTrue(allowed["modelAccess"]["allowed"])
        self.assertEqual(allowed["usefulSegments"][0]["text"], "Harbour concert notes")
        self.assertNotIn("modelAccess", plain)


class Multilingual(unittest.TestCase):
    def test_chinese_and_code_switch(self):
        db = FakeLibraryDB()
        trad = db.add_asset(1)
        simp = db.add_asset(2)
        eng = db.add_asset(3)
        mixed = db.add_asset(4)
        hair = db.add_asset(5)
        db.add_segment(trad, "我哋喺演奏會之後去飲茶，好開心。", language="yue")
        db.add_segment(simp, "演奏会门票已经售完，请关注下一场。", language="zh-Hans")
        db.add_segment(eng, "The concert tickets sold out; rehearsal moved to Friday.", language="en")
        db.add_segment(mixed, "今晚 rehearsal 喺 City Hall，記得帶樂譜。", language="yue")
        db.add_segment(hair, "新的头发造型照片", language="zh-Hans")
        ctx = make_ctx(db)

        def found(query):
            return {h["assetRef"]["versionId"] for h in run(ctx, query=query)["hits"]}

        self.assertEqual(found("演奏会"), {trad["key"], simp["key"]})
        self.assertEqual(found("演奏會"), {trad["key"], simp["key"]})
        self.assertEqual(found("演奏會 門票"), {simp["key"]})
        self.assertEqual(found("rehearsal 喺"), {mixed["key"]})
        self.assertEqual(found("REHEARSAL"), {eng["key"], mixed["key"]})
        self.assertEqual(found("飲茶"), {trad["key"]})
        self.assertEqual(found("頭髮"), {hair["key"]})
        self.assertEqual(found("city hall"), {mixed["key"]})
        cantonese = run(ctx, query="演奏會", filters={"languages": ["yue"]})
        self.assertEqual({h["assetRef"]["versionId"] for h in cantonese["hits"]}, {trad["key"]})

    def test_normalization_keeps_meaning(self):
        for source, target in textnorm.S2T.items():
            self.assertEqual(textnorm.fold(target), textnorm.fold(textnorm.fold(target)), source)
            self.assertEqual(textnorm.fold(source), textnorm.fold(target), (source, target))
        self.assertEqual(textnorm.fold("头发"), textnorm.fold("頭髮"))
        self.assertEqual(textnorm.fold("干部"), textnorm.fold("幹部"))
        self.assertEqual(textnorm.fold("关系"), textnorm.fold("關係"))
        terms = textnorm.tokens("今晚 rehearsal 喺 City Hall 2026 號")
        for expected in ("rehearsal", "city", "hall", "2026", "今晚", "喺"):
            self.assertIn(expected, terms)
        self.assertNotEqual(textnorm.fold("演奏會"), textnorm.fold("演唱會"), "folding never merges different words")
        self.assertEqual(textnorm.tsquery("don't stop"), "don & t & stop", "apostrophes split like PostgreSQL's parser")
        self.assertIsNone(textnorm.tsquery("!!! ???"))


class Visual(unittest.TestCase):
    def test_visual_not_caption_only(self):
        red, red2, blue = png((200, 30, 30)), png((190, 40, 35), stripes=(170, 20, 20)), png((20, 40, 200), stripes=(240, 240, 240))
        v_red, v_red2, v_blue = index.visual_features(red), index.visual_features(red2), index.visual_features(blue)
        self.assertEqual(len(v_red), 256)
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in v_red)), 1.0, places=5)
        self.assertEqual(v_red, index.visual_features(red), "deterministic")
        dist = lambda a, b: 1 - sum(x * y for x, y in zip(a, b))
        self.assertLess(dist(v_red, v_red2), dist(v_red, v_blue))

        db = FakeLibraryDB()
        photos = [legacy_photo(n) for n in (1, 2, 3, 4)]
        state = {"sources": [], "phase2": {"assets": photos, "jobs": [], "reviews": []}}
        refs = [{"key": p["id"], "lineage": p["id"], "ws": WS, "created": p["createdAt"]} for p in photos]
        for ref, vector in zip(refs[:3], (v_red, v_red2, v_blue)):
            db.add_embedding(ref, vector, modality="visual", model=index.VISUAL_MODEL)
        db.add_segment(refs[3], "a red sunset over the harbour", kind="caption")
        ctx = make_ctx(db, state=state)

        text_only = run(ctx, query="red", modes=["visual"])
        self.assertEqual(text_only["coverage"]["modesApplied"], [])
        self.assertTrue(text_only["coverage"]["partial"])
        self.assertFalse(any("visual" in reasons(h) for h in text_only["hits"]))
        self.assertTrue(any("multimodal" in w for w in text_only["warnings"]))

        caption = run(ctx, query="red", modes=["lexical", "visual"])
        self.assertEqual(caption["coverage"]["modesApplied"], ["lexical"])
        self.assertEqual([h["assetRef"]["versionId"] for h in caption["hits"]], [photos[3]["id"]])
        self.assertEqual(reasons(caption["hits"][0]), {"lexical"}, "a caption match is lexical, never visual")

        similar = run(ctx, similarTo={"assetId": photos[0]["id"], "versionId": photos[0]["id"], "sha256": photos[0]["hash"]})
        self.assertEqual(similar["coverage"]["modesApplied"], ["visual"])
        order = [h["assetRef"]["versionId"] for h in similar["hits"]]
        self.assertEqual(order, [photos[1]["id"], photos[2]["id"]], "nearest first; the example itself and unindexed photos are not similar results")
        self.assertIn(index.VISUAL_MODEL, " ".join(r.get("detail") or "" for r in similar["hits"][0]["matchReasons"]))
        self.assertTrue(similar["coverage"]["partial"], "a photo without a visual index makes visual coverage partial")

        db.vector = False
        degraded = run(make_ctx(db, state=state), similarTo={"assetId": photos[0]["id"], "versionId": photos[0]["id"], "sha256": photos[0]["hash"]})
        self.assertEqual(degraded["coverage"]["modesApplied"], [])
        self.assertEqual(degraded["hits"], [])
        self.assertTrue(degraded["warnings"])

    def test_visual_processor_uses_poster_for_video(self):
        poster = png((10, 200, 10))
        job = SimpleNamespace(version={"assetId": key(9), "versionId": key(9), "kind": "video", "mime": "video/mp4", "legacy": True, "media": {}},
                              poster=lambda: poster, raw=lambda: b"not an image")
        outcome = index.EMBED_VISUAL["run"](job)
        self.assertEqual(outcome["state"], "ready")
        self.assertEqual(outcome["embeddings"][0]["modelId"], index.VISUAL_MODEL)
        self.assertEqual(outcome["embeddings"][0]["vector"], index.visual_features(poster))
        no_poster = SimpleNamespace(version=dict(job.version), poster=lambda: None, raw=lambda: b"")
        self.assertEqual(index.EMBED_VISUAL["run"](no_poster)["state"], "unsupported")
        broken = SimpleNamespace(version={**job.version, "kind": "image", "mime": "image/png"}, raw=lambda: b"\x89PNG broken")
        self.assertEqual(index.EMBED_VISUAL["run"](broken)["state"], "failed")


class Cursors(unittest.TestCase):
    def seeded(self, n=60):
        db = FakeLibraryDB()
        for i in range(1, n + 1):
            db.add_asset(i)
        return db

    def test_cursor_revision_refresh(self):
        db = self.seeded()
        first = run(make_ctx(db), limit=20)
        self.assertIsNotNone(first["nextCursor"])
        second = run(make_ctx(db), limit=20, cursor=first["nextCursor"])
        self.assertEqual(second["queryId"], first["queryId"])
        self.assertFalse({h["assetRef"]["versionId"] for h in first["hits"]} & {h["assetRef"]["versionId"] for h in second["hits"]})
        db.revision[WS] = 1
        with self.assertRaises(AlphaError) as stale:
            run(make_ctx(db), limit=20, cursor=first["nextCursor"])
        self.assertEqual((stale.exception.status, stale.exception.code), (409, "library_cursor_stale"))
        self.assertIn("Refresh", str(stale.exception))
        self.assertTrue(getattr(stale.exception, "refresh", False))
        db.revision[WS] = 0
        db.generation[WS] = 2
        with self.assertRaises(AlphaError) as regenerated:
            run(make_ctx(db), limit=20, cursor=first["nextCursor"])
        self.assertEqual(regenerated.exception.code, "library_cursor_stale")

    def test_cursor_tamper_and_rebinding(self):
        db = self.seeded()
        first = run(make_ctx(db), limit=20, query="")
        token = first["nextCursor"]
        body, mac = token.split(".")
        forged = body[:-2] + ("A" if body[-2] != "A" else "B") + body[-1] + "." + mac
        for cursor, request in ((forged, {}), (token + "x", {}), ("not-a-cursor", {}), (token, {"query": "other"}),
                                (token, {"purpose": "answer"}), (token, {"filters": {"kinds": ["audio"]}})):
            with self.assertRaises(AlphaError) as refused:
                run(make_ctx(db), limit=20, cursor=cursor, **request)
            self.assertEqual(refused.exception.code, "library_cursor_stale", request)
        with self.assertRaises(AlphaError) as other_actor:
            ctx = make_ctx(db)
            ctx.actor = "00000000-0000-0000-0000-000000000099"
            run(ctx, limit=20, cursor=token)
        self.assertEqual(other_actor.exception.code, "library_cursor_stale")
        with mock.patch.dict(os.environ, {"RAFII_LIBRARY_CURSOR_SECRET": "another-secret-value-for-tests-only"}):
            with self.assertRaises(AlphaError) as rotated:
                run(make_ctx(db), limit=20, cursor=token)
        self.assertEqual(rotated.exception.code, "library_cursor_stale")
        db.now = NOW + 2 * 3600
        with self.assertRaises(AlphaError) as expired:
            run(make_ctx(db), limit=20, cursor=token)
        self.assertEqual(expired.exception.code, "library_cursor_stale")

    def test_paging_without_skips_or_duplicates(self):
        db = self.seeded(95)
        seen, cursor, pages = [], None, 0
        while True:
            request = {"limit": 30}
            if cursor:
                request["cursor"] = cursor
            page = run(make_ctx(db), **request)
            pages += 1
            seen += [h["assetRef"]["versionId"] for h in page["hits"]]
            self.assertEqual(page["coverage"]["accessibleAssetCount"], 95)
            if pages == 1:
                db.now = NOW + 50
                db.add_asset(500, created=NOW + 10)  # arrives mid-paging; the snapshot excludes it
            cursor = page["nextCursor"]
            if not cursor:
                break
        self.assertEqual(pages, 4)
        self.assertEqual(len(seen), 95)
        self.assertEqual(len(set(seen)), 95)
        self.assertNotIn(key(500), seen)
        fresh = run(make_ctx(db), limit=30)
        self.assertEqual(fresh["coverage"]["accessibleAssetCount"], 96)

        deleting = run(make_ctx(db), limit=30)
        db.assets[0]["status"] = "deleting"
        with self.assertRaises(AlphaError) as changed:
            run(make_ctx(db), limit=30, cursor=deleting["nextCursor"])
        self.assertEqual(changed.exception.code, "library_cursor_stale", "a removed item makes offsets unsafe; refresh instead of skipping")

    def test_cursor_module_binding(self):
        request = c.search_request({"query": "harbour", "filters": {"kinds": ["audio"]}})
        common = dict(workspace_id=WS, actor=ACTOR, index_generation=1, grant_revision=3, normalizer_version=1, ranking_version="rrf-60-v1")
        digest = cursors.binding(request=request, **common)
        self.assertEqual(digest, cursors.binding(request=dict(request, limit=99, cursor="x"), **common), "page size and the cursor itself are not bound")
        for change in ({"grant_revision": 4}, {"index_generation": 2}, {"actor": "someone"}, {"workspace_id": OTHER_WS}, {"ranking_version": "rrf-60-v2"}):
            self.assertNotEqual(digest, cursors.binding(request=request, **{**common, **change}), change)
        fp = cursors.fingerprint(["b", "a"], 3, 0)
        self.assertEqual(fp, cursors.fingerprint(["a", "b"], 3, 0))
        self.assertNotEqual(fp, cursors.fingerprint(["a", "b"], 2, 0), "a superseded passage changes the watermark")
        token = cursors.encode(binding_digest=digest, snapshot=NOW, offset=30, fingerprint_value=fp, query_id="q" * 32)
        self.assertLessEqual(len(token), 2000)
        for leaked in ("harbour", WS, ACTOR):
            self.assertNotIn(leaked, token)
            self.assertNotIn(leaked, __import__("base64").urlsafe_b64decode(token.split(".")[0] + "==").decode())
        state = cursors.decode(token, binding_digest=digest, now=NOW + 5)
        self.assertEqual((state["offset"], state["snapshot"], state["queryId"]), (30, NOW, "q" * 32))
        cursors.check_fingerprint(state, fp)
        with self.assertRaises(cursors.CursorStale):
            cursors.check_fingerprint(state, "0" * 24)

    def test_lexical_paging_is_stable(self):
        db = FakeLibraryDB()
        for i in range(1, 76):
            db.add_segment(db.add_asset(i), f"Concert programme draft {i}")
        seen, cursor = [], None
        for _ in range(4):
            page = run(make_ctx(db), query="concert programme", limit=25, **({"cursor": cursor} if cursor else {}))
            seen += [h["assetRef"]["versionId"] for h in page["hits"]]
            cursor = page["nextCursor"]
            if not cursor:
                break
        self.assertEqual(len(seen), 75)
        self.assertEqual(len(set(seen)), 75)


class Coverage(unittest.TestCase):
    def test_no_count_leak(self):
        db = FakeLibraryDB()
        mine = [db.add_asset(i, ws=OTHER_WS) for i in range(1, 6)]
        theirs = [db.add_asset(i) for i in range(1, 301)]
        for a in mine + theirs:
            db.add_segment(a, "shared rehearsal keyword")
        db.add_capability(theirs[0], "extract", "failed")
        db.add_capability(theirs[1], "transcribe", "queued")
        ctx = make_ctx(db, ws=OTHER_WS)
        result = run(ctx, query="rehearsal")
        self.assertEqual({h["assetRef"]["versionId"] for h in result["hits"]}, {a["key"] for a in mine})
        cov = result["coverage"]
        self.assertEqual((cov["accessibleAssetCount"], cov["indexedAssetCount"], cov["pendingAssetCount"], cov["failedAssetCount"]), (5, 5, 0, 0))
        self.assertEqual(sum(result["facets"]["kinds"].values()), 5)
        for sql, args in ctx.cur.executed:
            if isinstance(args, dict) and "w" in args:
                self.assertEqual(args["w"], OTHER_WS, sql[:80])
            elif isinstance(args, (tuple, list)) and args:
                self.assertEqual(args[0], OTHER_WS, sql[:80])
        self.assertEqual(run(make_ctx(db, ws=OTHER_WS), query=theirs[0]["key"])["hits"], [])
        with self.assertRaises(AlphaError) as foreign:
            run(make_ctx(db, ws=OTHER_WS), scope={"kind": "selection", "assetRefs": [{"assetId": theirs[0]["key"], "versionId": theirs[0]["key"], "sha256": ""}]})
        with self.assertRaises(AlphaError) as missing:
            run(make_ctx(db, ws=OTHER_WS), scope={"kind": "selection", "assetRefs": [{"assetId": "f" * 32, "versionId": "f" * 32, "sha256": ""}]})
        self.assertEqual((foreign.exception.status, str(foreign.exception), foreign.exception.code),
                         (missing.exception.status, str(missing.exception), missing.exception.code))
        own = run(make_ctx(db), query="rehearsal")["coverage"]
        self.assertEqual((own["accessibleAssetCount"], own["pendingAssetCount"], own["failedAssetCount"]), (300, 1, 1))

    def test_loaded_count_not_total(self):
        db = FakeLibraryDB()
        for i in range(1, 251):
            db.add_asset(i, kind=("document", "audio", "file")[i % 3], tags=["lesson"] if i % 2 else [])
        result = run(make_ctx(db), limit=30)
        self.assertEqual(len(result["hits"]), 30)
        self.assertEqual(result["coverage"]["accessibleAssetCount"], 250)
        self.assertEqual(result["totalHits"], {"value": 250, "relation": "eq"})
        self.assertEqual(sum(result["facets"]["kinds"].values()), 250)
        self.assertEqual(result["facets"]["tags"], {"lesson": 125})
        self.assertIsNotNone(result["nextCursor"])
        narrowed = run(make_ctx(db), limit=30, filters={"kinds": ["audio"]})
        self.assertEqual(narrowed["coverage"]["accessibleAssetCount"], sum(1 for i in range(1, 251) if i % 3 == 1))
        self.assertEqual(sum(narrowed["facets"]["kinds"].values()), 250, "a facet ignores its own filter so other choices stay visible")

    def test_candidate_bound_is_reported(self):
        db = FakeLibraryDB()
        for i in range(1, 13):
            db.add_segment(db.add_asset(i), f"Season brochure draft {i}")
        with mock.patch.object(search, "LEXICAL_K", 5), mock.patch.dict(search.CANDIDATE_LIMITS, {"lexical": 5}):
            result = run(make_ctx(db), query="season brochure", modes=["lexical"])
        self.assertEqual(result["totalHits"], {"value": 12, "relation": "gte"})
        self.assertEqual(result["ranking"]["boundsReached"], ["lexical"])
        self.assertEqual(len(result["hits"]), 5)
        self.assertIsNone(result["nextCursor"], "only the ranked candidates are pageable; the rest are reported, not faked")
        self.assertTrue(result["coverage"]["partial"])
        self.assertTrue(any("top 5 lexical" in w for w in result["warnings"]))

    def test_filters_with_explicit_time_zone(self):
        db = FakeLibraryDB()
        # 2026-10-07T15:59:59Z is 23:59:59 on 7 Oct in Hong Kong; 16:00:00Z is midnight on 8 Oct.
        before = db.add_asset(1, created=1791388799.0)
        start = db.add_asset(2, created=1791388800.0)
        end = db.add_asset(3, created=1791475199.0)
        after = db.add_asset(4, created=1791475200.0)
        db.now = 1791500000.0
        ctx = make_ctx(db)
        result = run(ctx, filters={"createdFrom": "2026-10-08", "createdTo": "2026-10-08", "timeZone": "Asia/Hong_Kong"})
        self.assertEqual({h["assetRef"]["versionId"] for h in result["hits"]}, {start["key"], end["key"]})
        utc = run(make_ctx(db), filters={"createdFrom": "2026-10-08", "createdTo": "2026-10-08"})
        self.assertEqual({h["assetRef"]["versionId"] for h in utc["hits"]}, {end["key"], after["key"]})
        self.assertNotIn(before["key"], {h["assetRef"]["versionId"] for h in utc["hits"]})
        with self.assertRaises(AlphaError):
            run(make_ctx(db), filters={"createdFrom": "2026-10-08", "timeZone": "Mars/Olympus_Mons"})

    def test_rights_usage_and_capability_filters(self):
        db = FakeLibraryDB()
        public = db.add_asset(1, source_id="src-public")
        review = db.add_asset(2, source_id="src-review")
        plain = db.add_asset(3)
        used_by_job = db.add_asset(4)
        used_by_event = db.add_asset(5)
        db.usage.append((WS, used_by_event["key"]))
        db.add_capability(plain, "transcribe", "failed")
        source = lambda sid, policy_name, asset: {"id": sid, "kind": "document", "active": True, "sourcePolicy": policy_name, "egressConsent": ["local"],
                                                  "useApprovals": [], "facts": [], "origin": {"kind": "library", "sha256": asset["sha"]}, "createdAt": 1789600000.0}
        state = {"sources": [source("src-public", "public_quote", public), source("src-review", "rewrite_approval", review)],
                 "phase2": {"assets": [], "reviews": [], "jobs": [{"id": "j1", "state": "queued", "manifest": {"media": [{"id": used_by_job["key"]}]}}]}}

        def found(filters):
            return {h["assetRef"]["versionId"] for h in run(make_ctx(db, state=state), filters=filters)["hits"]}

        self.assertEqual(found({"rights": "approved_public"}), {public["key"]})
        self.assertEqual(found({"rights": "needs_review"}), {review["key"]})
        self.assertEqual(found({"rights": "unknown"}), {plain["key"], used_by_job["key"], used_by_event["key"]}, "no source record is unknown, never cleared")
        self.assertEqual(found({"usage": "used"}), {used_by_job["key"], used_by_event["key"]})
        self.assertEqual(found({"usage": "unused"}), {public["key"], review["key"], plain["key"]})
        self.assertEqual(found({"capability": "transcribe", "capabilityState": "failed"}), {plain["key"]})
        self.assertEqual(len(found({"capability": "transcribe", "capabilityState": "not_requested"})), 4)

    def test_media_filters_and_collection_scope(self):
        db = FakeLibraryDB()
        doc = db.add_asset(1)
        audio = db.add_asset(2, kind="audio", media={"durationMs": 90_000})
        excluded = db.add_asset(3)
        portrait, landscape = legacy_photo(10, width=1080, height=1920), legacy_photo(11, width=1920, height=1080)
        video = legacy_photo(12, width=1280, height=720, mime="video/mp4", duration=30)
        cid = "c" * 32
        db.collections.append({"ws": WS, "id": cid, "name": "Season launch"})
        db.items += [{"ws": WS, "collection": cid, "key": k, "origin": o} for k, o in ((doc["key"], "manual"), (audio["key"], "rule"), (excluded["key"], "rule"), (portrait["id"], "manual"))]
        db.overrides.append({"ws": WS, "collection": cid, "key": excluded["key"], "mode": "exclude"})
        state = {"sources": [], "phase2": {"assets": [portrait, landscape, video], "jobs": [], "reviews": []}}
        ctx = make_ctx(db, state=state)
        scoped = run(ctx, scope={"kind": "collection", "collectionId": cid})
        self.assertEqual({h["assetRef"]["versionId"] for h in scoped["hits"]}, {doc["key"], audio["key"], portrait["id"]})
        self.assertIn("Season launch", scoped["coverage"]["scopeDescription"])
        self.assertEqual({h["assetRef"]["versionId"] for h in run(make_ctx(db, state=state), filters={"orientation": "portrait"})["hits"]}, {portrait["id"]})
        self.assertEqual({h["assetRef"]["versionId"] for h in run(make_ctx(db, state=state), filters={"minDurationMs": 60_000})["hits"]}, {audio["key"]})
        self.assertEqual({h["assetRef"]["versionId"] for h in run(make_ctx(db, state=state), filters={"kinds": ["video", "image"], "maxDurationMs": 40_000})["hits"]}, {video["id"]})
        with self.assertRaises(AlphaError) as foreign:
            run(make_ctx(db, state=state), scope={"kind": "collection", "collectionId": "d" * 32})
        self.assertEqual(foreign.exception.status, 404)

    def test_selection_scope_keeps_old_version(self):
        db = FakeLibraryDB()
        v1 = db.add_asset(1)
        v2 = db.add_asset(2, lineage=v1["key"], version_no=2)
        db.add_segment(v1, "Original wording about the harbour")
        db.add_segment(v2, "Revised wording about the harbour")
        whole = run(make_ctx(db), query="harbour")
        self.assertEqual([h["assetRef"]["versionId"] for h in whole["hits"]], [v2["key"]], "workspace scope searches current versions")
        self.assertEqual(whole["hits"][0]["assetRef"]["assetId"], v1["key"])
        selected = run(make_ctx(db), query="harbour", scope={"kind": "selection", "assetRefs": [{"assetId": v1["key"], "versionId": v1["key"], "sha256": v1["sha"]}]})
        self.assertEqual([h["assetRef"]["versionId"] for h in selected["hits"]], [v1["key"]], "a selection bound to an old version stays on it")
        self.assertIn("Original", selected["hits"][0]["snippet"])


class Degradation(unittest.TestCase):
    def setUp(self):
        index._QUERY_CACHE.clear()

    def seeded(self):
        db = FakeLibraryDB()
        self.lexical = db.add_asset(1)
        self.semantic = db.add_asset(2)
        self.other_model = db.add_asset(3)
        s1 = db.add_segment(self.lexical, "Quarterly piano recital budget")
        s2 = db.add_segment(self.semantic, "Money planned for the spring concert season")
        s3 = db.add_segment(self.other_model, "Unrelated words")
        db.add_embedding(self.lexical, unit(1024, {0: 1.0}), segment=s1)
        db.add_embedding(self.semantic, unit(1024, {1: 1.0, 2: 0.2}), segment=s2)
        db.add_embedding(self.other_model, unit(1024, {1: 1.0}), segment=s3, model="other/model")
        return db

    def assert_lexical_only(self, result):
        self.assertEqual(result["coverage"]["modesApplied"], ["lexical"])
        self.assertTrue(result["coverage"]["partial"])
        self.assertTrue(result["warnings"])
        for hit in result["hits"]:
            self.assertNotIn("semantic", reasons(hit))
        self.assertEqual([h["assetRef"]["versionId"] for h in result["hits"]], [self.lexical["key"]])

    def test_vector_failure_lexical_label(self):
        db = self.seeded()
        with free_budget():
            unavailable = FakeEmbedder(unavailable="embeddings_disabled")
            self.assert_lexical_only(run(make_ctx(db, embedder=unavailable), query="recital budget"))
            self.assertEqual(unavailable.calls, 0)
            self.assert_lexical_only(run(make_ctx(db, embedder=FakeEmbedder(unit(1024, {1: 1.0}), fail=True)), query="recital budget"))
            db.fail.add("knn")
            failed = make_ctx(db, embedder=FakeEmbedder(unit(1024, {1: 1.0})))
            self.assert_lexical_only(run(failed, query="recital budget"))
            self.assertTrue(any(re.match(r"\s*ROLLBACK TO SAVEPOINT", s) for s, _ in failed.cur.executed), "a vector failure never poisons the transaction")
            db.fail.clear()
            db.vector = False
            no_column = FakeEmbedder(unit(1024, {1: 1.0}))
            result = run(make_ctx(db, embedder=no_column), query="recital budget")
            self.assert_lexical_only(result)
            self.assertEqual(no_column.calls, 0, "no paid query embedding when the index cannot be searched")
            self.assertTrue(any("not installed" in w for w in result["warnings"]))

    def test_semantic_success_never_mixes_models(self):
        db = self.seeded()
        embedder = FakeEmbedder(unit(1024, {1: 1.0}))
        with free_budget():
            result = run(make_ctx(db, embedder=embedder), query="recital budget")
        self.assertEqual(result["coverage"]["modesApplied"], ["lexical", "semantic"])
        found = {h["assetRef"]["versionId"]: reasons(h) for h in result["hits"]}
        self.assertIn("semantic", found[self.semantic["key"]])
        self.assertNotIn(self.other_model["key"], found, "a vector from another model is never compared")
        self.assertEqual(result["hits"][0]["assetRef"]["versionId"], self.lexical["key"])
        knn = make_ctx(db, embedder=embedder)
        with free_budget():
            run(knn, query="recital budget")
        args = knn.cur.statements("knn")[0][1]
        self.assertEqual((args["model"], args["dims"], args["gen"], args["modality"]), (TEXT_MODEL, 1024, 1, "text"))
        self.assertEqual(embedder.calls, 1, "the query embedding is cached for the next page")
        index._QUERY_CACHE.clear()
        budget = make_ctx(db, embedder=FakeEmbedder(unit(1024, {1: 1.0})))
        with mock.patch.multiple(index, _reserve=lambda *a, **k: {"status": "blocked_budget"}, _settle=lambda *a, **k: None):
            blocked = run(budget, query="recital budget")
        self.assertEqual(blocked["coverage"]["modesApplied"], ["lexical"])
        self.assertTrue(any("budget" in w for w in blocked["warnings"]))


class Fusion(unittest.TestCase):
    def test_rrf_equal_weights_and_exact_first(self):
        self.assertEqual(search.rrf([["a", "b", "c"], ["c", "a"]]), ["a", "c", "b"])
        self.assertEqual(search.rrf([["x"], ["y"]]), ["x", "y"], "ties keep list order deterministically")
        db = FakeLibraryDB()
        titled = db.add_asset(1, title="Harbour")
        strong = db.add_asset(2)
        db.add_segment(strong, "harbour harbour harbour")
        db.add_segment(titled, "A long text that also mentions the harbour once among many other words to dilute it")
        result = run(make_ctx(db), query="Harbour")
        self.assertEqual(result["hits"][0]["assetRef"]["versionId"], titled["key"])
        self.assertIn("title", reasons(result["hits"][0]))
        self.assertEqual(result["ranking"]["version"], "rrf-60-v1")
        self.assertEqual(result["ranking"]["k"], 60)
        for hit in result["hits"]:
            self.assertFalse({"score", "confidence", "relevance"} & set(hit), "scores are never presented as confidence")

    def test_snippet_sanitized(self):
        text = "<b>Intro</b>\x00\x07 " + "filler " * 80 + "the Brahms <script>alert(1)</script> passage " + "tail " * 80
        out = search.snippet(text, "brahms")
        self.assertIn("Brahms", out)
        for bad in ("<b>", "<script>", "\x00", "\x07"):
            self.assertNotIn(bad, out)
        self.assertLessEqual(len(out), 242)
        self.assertEqual(search.snippet("短句演奏會", "演奏会"), "短句演奏會")


class Surface(unittest.TestCase):
    def test_flag_and_http(self):
        db = FakeLibraryDB()
        db.add_asset(1)
        with mock.patch.dict(os.environ, {"RAFII_LIBRARY_RETRIEVAL_ENABLED": ""}):
            with self.assertRaises(AlphaError) as off:
                search.search_library(make_ctx(db), {"query": ""})
        self.assertEqual((off.exception.status, off.exception.code), (503, "library_retrieval_disabled"))
        with mock.patch.dict(os.environ, ENV):
            via_http = search.search_http(make_ctx(db), {"params": {}, "query": {}, "body": {"query": "", "limit": 5}})
        self.assertEqual(via_http["contractVersion"], c.CONTRACT_VERSION)
        self.assertEqual(len(via_http["hits"]), 1)
        with mock.patch.dict(os.environ, ENV), self.assertRaises(AlphaError) as bad:
            search.search_http(make_ctx(db), {"params": {}, "query": {}, "body": {"query": "x", "workspaceId": WS}})
        self.assertEqual(bad.exception.status, 400)

    def test_write_embeddings_and_degrade(self):
        db = FakeLibraryDB()
        a = db.add_asset(1)
        version = {"assetId": a["lineage"], "versionId": a["key"]}
        cur = db.cursor()
        item = {"modality": "visual", "modelId": index.VISUAL_MODEL, "dims": 256, "vector": [2.0] + [0.0] * 255, "segmentId": None}
        first = index.write_embeddings(cur, WS, version, [item], consent_revision=4, index_generation=3)
        self.assertEqual((first["stored"], first["vector"]), (1, True))
        stored = db.embeddings[-1]
        self.assertEqual((stored["consent"], stored["gen"], stored["status"]), (4, 3, "active"))
        self.assertAlmostEqual(stored["vector"][0], 1.0)
        second = index.write_embeddings(cur, WS, version, [item], consent_revision=5, index_generation=3)
        self.assertEqual(second["superseded"], 1)
        self.assertEqual([e["status"] for e in db.embeddings], ["superseded", "active"])
        self.assertEqual(index.tombstone(cur, WS, [a["key"]], status="revoked"), 1)
        with self.assertRaises(AlphaError):
            index.write_embeddings(cur, WS, version, [dict(item, dims=255)], consent_revision=5, index_generation=3)
        with self.assertRaises(AlphaError):
            index.write_embeddings(cur, WS, version, [dict(item, vector=[float("nan")] * 256)], consent_revision=5, index_generation=3)
        db.vector = False
        honest = index.write_embeddings(db.cursor(), WS, version, [item], consent_revision=5, index_generation=3)
        self.assertEqual((honest["stored"], honest["vector"], honest["reason"]), (0, False, "vector_unavailable"))
        self.assertEqual(len(db.embeddings), 2)

    def test_processors_are_declared(self):
        by_capability = {p["capability"]: p for p in index.PROCESSORS}
        visual, text = by_capability["embed_visual"], by_capability["embed_text"]
        self.assertEqual((visual["version"], visual["location"], visual["category"]), ("local/visual-perceptual-v1", "local", "embedding"))
        self.assertIn((visual["location"], visual["category"]), policy.LOCAL_DEFAULTS, "local perceptual vectors need no cloud grant")
        self.assertEqual((text["location"], text["category"]), ("cloud", "embedding"))
        self.assertNotIn((text["location"], text["category"]), policy.LOCAL_DEFAULTS)
        for p in (visual, text):
            for field in ("applies", "estimate", "run"):
                self.assertTrue(callable(p[field]))
        self.assertTrue(visual["applies"]({"kind": "image"}))
        self.assertFalse(visual["applies"]({"kind": "document"}))
        self.assertEqual(visual["estimate"](SimpleNamespace(version={"kind": "image"})), 0)

    def test_embed_text_processor(self):
        version = {"assetId": key(1), "versionId": key(1), "kind": "document", "bytes": 3000}
        segments = [{"id": "a" * 32, "text": "First passage"}, {"id": "b" * 32, "text": "Second passage"}]
        refused = SimpleNamespace(version=version, providers=FakeEmbedder(unavailable="gateway_credential_missing"), segments=lambda: segments)
        outcome = index.EMBED_TEXT["run"](refused)
        self.assertEqual((outcome["state"], outcome["retryable"], outcome["errorCode"]), ("failed", False, "provider_unavailable"))
        job = SimpleNamespace(version=version, providers=FakeEmbedder(unit(1024, {3: 1.0})), segments=lambda: segments)
        done = index.EMBED_TEXT["run"](job)
        self.assertEqual(done["state"], "ready")
        self.assertEqual([e["segmentId"] for e in done["embeddings"]], ["a" * 32, "b" * 32])
        self.assertEqual({(e["modality"], e["dims"], e["modelId"]) for e in done["embeddings"]}, {("text", 1024, TEXT_MODEL)})
        empty = SimpleNamespace(version=version, providers=FakeEmbedder(unit(1024, {3: 1.0})), segments=lambda: [])
        self.assertEqual(index.EMBED_TEXT["run"](empty)["state"], "unsupported")
        revoked_embedder = FakeEmbedder(unit(1024, {3: 1.0}))
        revoked = SimpleNamespace(version=version, providers=revoked_embedder, segments=lambda: segments, recheck=lambda: False, heartbeat=lambda: True)
        stopped = index.EMBED_TEXT["run"](revoked)
        self.assertEqual((stopped["state"], stopped["embeddings"], revoked_embedder.calls), ("blocked_permission", [], 0))
        many = [{"id": format(n, "032x"), "text": f"Passage {n}"} for n in range(index.EMBED_BATCH + 1)]
        answers = iter([True, False])
        midway_embedder = FakeEmbedder(unit(1024, {3: 1.0}))
        midway = index.EMBED_TEXT["run"](SimpleNamespace(version=version, providers=midway_embedder, segments=lambda: many, recheck=lambda: next(answers)))
        self.assertEqual((midway["state"], midway["embeddings"], midway_embedder.calls), ("blocked_permission", [], 1),
                         "a revoke between batches stops further calls and keeps nothing")
        lease_lost = index.EMBED_TEXT["run"](SimpleNamespace(version=version, providers=FakeEmbedder(unit(1024, {3: 1.0})), segments=lambda: segments,
                                                             heartbeat=lambda: False))
        self.assertEqual(lease_lost["state"], "blocked_permission", "without recheck, a lost heartbeat also stops the job")

    def test_cloud_scripts_compile(self):
        for path in ("tests/phase2/postgres_library_intelligence_search.py", "scripts/library-intelligence-bench.py"):
            source = (ROOT / path).read_text(encoding="utf-8")
            compile(source, path, "exec")
            self.assertIn("LIBRARY_PG_PHASE" if "phase2" in path else "p95", source)


class AgentAdapter(unittest.TestCase):
    def setUp(self):
        self.db = db = FakeLibraryDB()
        self.assets = [db.add_asset(i) for i in range(1, 321)]
        self.old = self.assets[19]  # newest-first position 301: outside the former newest-200 window
        self.passage_asset = self.assets[1]
        db.add_segment(self.old, "Concert on 12 October at the City Hall.")
        db.add_segment(self.passage_asset, "Harbour concert rehearsal notes, page two.", locator={"kind": "page", "page": 2})
        self.state = {"sources": [{"id": "src1", "kind": "document", "active": True, "sourcePolicy": "rewrite_approval", "egressConsent": ["local", "cloud"],
                                   "useApprovals": [], "facts": [{"id": "f1", "text": "Concert on 12 October", "approved": True},
                                                                 {"id": "f2", "text": "Unreviewed claim", "approved": False}],
                                   "origin": {"kind": "library", "assetId": self.old["key"], "sha256": self.old["sha"]}, "createdAt": 1789600000.0}],
                      "phase2": {"assets": [], "jobs": [], "reviews": []}}
        self.old["sourceId"] = "src1"

    def tool_ctx(self):
        return ToolContext(state=self.state, membership=Membership("owner"), principal=ACTOR, workspace_id=WS, cur=self.db.cursor(),
                           service=SimpleNamespace(library_intelligence=SimpleNamespace(providers=FakeEmbedder(unavailable="embeddings_disabled"))), now=NOW)

    def test_no_newest_200_window_and_contract_shape(self):
        with mock.patch.dict(os.environ, ENV):
            out = library_reads.library_search(self.tool_ctx(), "concert")
        data = out["data"]
        found = {r["assetId"]: r for r in data["results"]}
        self.assertIn(self.old["key"], found)
        hit = found[self.old["key"]]
        for field in ("assetId", "sourceId", "title", "sha256", "facts", "passages"):
            self.assertIn(field, hit)
        self.assertEqual([f["id"] for f in hit["facts"]], ["f1"], "approved facts only")
        self.assertEqual(hit["passages"], [], "no answer grant, no passages")
        self.assertNotIn(self.passage_asset["key"], found)
        self.assertTrue(data["approvedFactsOnly"])
        self.assertIn("coverage", data)

    def test_passages_need_answer_and_cloud_processing(self):
        self.db.grants = [dict(grant("answer"), id=str(uuid.UUID(int=1)))]
        with mock.patch.dict(os.environ, ENV):
            no_cloud = library_reads.library_search(self.tool_ctx(), "harbour concert")["data"]
        self.assertNotIn(self.passage_asset["key"], {r["assetId"] for r in no_cloud["results"]}, "answer alone does not allow cloud egress")
        self.db.grants.append(dict(grant(location="cloud", category="llm"), id=str(uuid.UUID(int=2))))
        with mock.patch.dict(os.environ, ENV):
            data = library_reads.library_search(self.tool_ctx(), "harbour concert")["data"]
            read = library_reads.library_read(self.tool_ctx(), self.passage_asset["key"])["data"]
        found = {r["assetId"]: r for r in data["results"]}
        passage = found[self.passage_asset["key"]]["passages"][0]
        self.assertEqual(passage["locator"], {"kind": "page", "page": 2})
        self.assertIn("Harbour concert", passage["text"])
        self.assertTrue(found[self.passage_asset["key"]]["attributionOnly"])
        self.assertEqual(found[self.passage_asset["key"]]["facts"], [])
        self.assertEqual(read["passages"][0]["locatorLabel"], "page 2")
        self.assertEqual(read["facts"], [])

    def test_legacy_path_without_flag_is_uncapped(self):
        with mock.patch.dict(os.environ, {"RAFII_LIBRARY_RETRIEVAL_ENABLED": ""}):
            ctx = self.tool_ctx()
            ctx.cur.db = self.db
            original = FakeCur.execute

            def legacy_execute(cur, sql, args=None):
                if "FROM public.pr_library_assets a WHERE a.workspace_id=%s AND a.source_id=ANY" in sql:
                    cur.executed.append((sql, args))
                    cur._rows = [(str(uuid.UUID(hex=x["key"])), x["sourceId"], x["title"], x["filename"], x["sha"]) for x in self.db.assets if x["sourceId"] in args[1]]
                    return
                return original(cur, sql, args)

            with mock.patch.object(FakeCur, "execute", legacy_execute):
                out = library_reads.library_search(ctx, "concert")
        self.assertEqual([r["assetId"] for r in out["data"]["results"]], [self.old["key"]])
        self.assertFalse(any("LIMIT 200" in s for s, _ in ctx.cur.executed))

    def test_read_denies_unadmitted(self):
        with mock.patch.dict(os.environ, ENV):
            with self.assertRaises(AlphaError) as denied:
                library_reads.library_read(self.tool_ctx(), self.passage_asset["key"])
            self.assertEqual(denied.exception.status, 404)
            read = library_reads.library_read(self.tool_ctx(), self.old["key"])["data"]
        self.assertEqual(read["sourceId"], "src1")
        self.assertEqual([f["id"] for f in read["facts"]], ["f1"])


if __name__ == "__main__":
    unittest.main()
