"""Lexical-only retrieval baseline on the FROZEN relevance set, with real SQL (acceptance A026 first clause, A027 multilingual).

Cloud CI only (scripts/library-intelligence-validation.sh runs every postgres_library_intelligence*.py in both
LIBRARY_PG_PHASE=no_vector and =vector). Data: tests/fixtures/library_intelligence/eval/{corpus,queries}.json, never
modified, plus the 940 deterministic distractors from scripts/library-intelligence-eval.py (1,004 documents) in one
workspace. A second workspace holds near-copies of the 64 corpus documents, and the first workspace's rankings are
compared before and after it exists, so isolation cannot change the results.

Seeding: each document is a normalized Library row carrying the corpus filename and title (the corpus files are plain-text
stand-ins, some named .pdf/.xlsx, so the filenames are kept as metadata), and its segments come from the production
segment path: structure.extract_raw on the text, media.write_media, then segments.write_segments (search_terms,
normalizer version, text hashes). Search runs through api.search -> search_library, lexical mode only.

Reported: Recall@10 per query type and overall as a LEXICAL-ONLY BASELINE. This is not the A026 semantic target, which needs
real embeddings (scripts/library-intelligence-eval.py). The suite asserts only that the run completed, that isolation
held, and that exact/lexical queries (type 'lexical') reach Recall@10 >= 0.90 (the engineering threshold for A026's exact
strength); misses are printed either way. In the vector phase it also checks kNN plumbing with SYNTHETIC deterministic
vectors, which proves the SQL path only and says nothing about semantic quality.
"""
import hashlib
import importlib.util
import json
import math
import os
import random
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.library_intelligence import api, index, media, providers, search, segments, structure, textnorm, versions  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
PHASE = os.environ.get("LIBRARY_PG_PHASE", "no_vector")
assert PHASE in ("no_vector", "vector"), PHASE
os.environ["RAFII_LIBRARY_RETRIEVAL_ENABLED"] = "1"
ONE = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000077"  # fresh user: rls.sql deletes ...0002
LEXICAL_THRESHOLD = 0.90
checks = []
spec = importlib.util.spec_from_file_location("library_eval", ROOT / "scripts/library-intelligence-eval.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)
index._reserve = lambda *a, **k: {"status": "reserved", "reservationId": "synthetic-fixture"}  # labelled synthetic budget admission (vector phase)
index._settle = lambda *a, **k: None


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in ("one", "other"):
        raise AlphaError("Verified session required.", 401)
    return ONE if token == "one" else OTHER


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: time.time()


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    checks.append(name)


MIMES = {"md": "text/markdown", "txt": "text/plain", "pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "csv": "text/csv", "json": "application/json"}
ROW_SQL = ("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,display_title,title_source,kind,mime,extension,bytes,sha256,"
           "bucket,object_name,processing_status,analysis_status,indexing_status,source_kind,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,'user','document',"
           "%s,%s,%s,%s,'postriff-library',%s,'ready','not_applicable','ready','upload',to_timestamp(%s),now())")


def seed(ws, owner, documents, base):
    """Rows with the corpus metadata; segments via the production path. Returns {asset key: document id}."""
    keys = {}
    with connection() as db, db.cursor() as cur:
        for n, d in enumerate(documents):
            aid = uuid.uuid5(uuid.NAMESPACE_URL, f"rli-eval/{ws}/{d['id']}")
            ext = d["filename"].rsplit(".", 1)[-1].lower()
            raw = d["text"].encode("utf-8")
            sha = hashlib.sha256(raw).hexdigest()
            cur.execute(ROW_SQL, (aid, ws, owner, d["filename"], d["title"], MIMES.get(ext, "text/plain"), ext, len(raw), sha, f"{aid.hex}.{ext}", base + n))
            version = {"assetId": aid.hex, "versionId": aid.hex, "sha256": sha, "legacy": False, "media": {}, "kind": "document", "extension": "txt"}
            batch = structure.extract_raw(version, raw)  # every corpus file is a text stand-in
            assert batch["state"] in ("ready", "partial") and batch["segments"], (d["id"], batch.get("detail"))
            media.write_media(cur, ws, version, batch["media"])
            segments.write_segments(cur, ws, version, batch["segments"], extractor=batch["extractor"], extractor_version=batch["extractorVersion"])
            keys[aid.hex] = d["id"]
    return keys


def run(ws, query, *, principal=ONE, modes=("lexical",), embedder=None):
    service = SimpleNamespace(library_intelligence=SimpleNamespace(providers=embedder or Embedder(None)))
    with connection() as db, db.cursor() as cur:
        return api.search(cur, principal, ws, {"query": query, "modes": list(modes), "limit": 10}, service=service)


class Embedder:
    """Synthetic fixture provider for kNN plumbing: returns a fixed vector; never a semantic embedding."""

    def __init__(self, vector):
        self.vector = vector

    def model(self, capability):
        return "fixture/plumbing-1024"

    def require(self, capability):
        if self.vector is None:
            raise providers.ProviderUnavailable(capability, "embeddings_disabled")

    def estimate(self, capability, *, units):
        return 1

    def embed(self, texts, *, dims=1024):
        return providers.ProviderResult([list(self.vector) for _ in texts], "fixture", "fixture/plumbing-1024", 0)


def fixture_vector(seed_text, dims=1024):
    rnd = random.Random(hashlib.sha256(seed_text.encode()).hexdigest())
    v = [rnd.gauss(0, 1) for _ in range(dims)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


# --- fixture ---------------------------------------------------------------------------------------------------------
corpus = json.loads((ROOT / "tests/fixtures/library_intelligence/eval/corpus.json").read_text(encoding="utf-8"))
qset = json.loads((ROOT / "tests/fixtures/library_intelligence/eval/queries.json").read_text(encoding="utf-8"))
documents = corpus["documents"] + evaluation.distractors()
check("frozen set sizes", len(corpus["documents"]) == 64 and len(qset["queries"]) == 100 and len(documents) == 1004, (len(corpus["documents"]), len(qset["queries"])))
with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (OTHER,))
    has_vector = db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_library_embeddings' "
                            "AND column_name='embedding'").fetchone() is not None
check(f"{PHASE}: pgvector column {'present' if PHASE == 'vector' else 'absent'}", has_vector == (PHASE == "vector"), has_vector)
service = HostedWorkspaceService(connection, verify)
wid = service.bootstrap("one", "studio")["workspaceId"]
other = service.bootstrap("other", "studio")["workspaceId"]
started = time.monotonic()
doc_of = seed(wid, ONE, documents, time.time() - 400 * 86400)
seed_seconds = round(time.monotonic() - started, 1)
check("1,004 documents seeded with segments", len(doc_of) == 1004)


def evaluate(ws):
    rows, started = [], time.monotonic()
    for q in qset["queries"]:
        result = run(ws, q["query"])
        top = [doc_of.get(h["assetRef"]["versionId"], "?") for h in result["hits"]][:10]
        rows.append({"id": q["id"], "type": q["type"], "relevant": q["relevant"], "top10": top, "modesApplied": result["coverage"]["modesApplied"],
                     "indexGeneration": result["coverage"]["indexGeneration"], "ranking": result["ranking"]["version"]})
    return rows, round(time.monotonic() - started, 2)


first, first_seconds = evaluate(wid)
check("every query ran in lexical mode", all(r["modesApplied"] == ["lexical"] for r in first))
summary = evaluation.summarize(first, "top10")
lexical_recall = summary["lexical"]["recallAt10"]

# --- isolation: near-copies in another workspace change nothing here ---------------------------------------------------------
copies = [{**d, "text": d["text"] + " (archived copy)", "title": d["title"] + " (copy)"} for d in corpus["documents"]]
other_keys = seed(other, OTHER, copies, time.time() - 300 * 86400)
second, _ = evaluate(wid)
check("A004 another workspace's near-copies never change this workspace's rankings", [r["top10"] for r in first] == [r["top10"] for r in second],
      [r["id"] for r, s in zip(first, second) if r["top10"] != s["top10"]])
theirs = run(other, "Harbour Sound Studio", principal=OTHER)
check("A004 the other workspace only finds its own copies", theirs["hits"] and all(h["assetRef"]["versionId"] in other_keys for h in theirs["hits"])
      and theirs["coverage"]["accessibleAssetCount"] == 64, theirs["coverage"])

# --- vector phase: kNN plumbing with synthetic vectors (never semantic quality) ----------------------------------------------
plumbing = None
if PHASE == "vector":
    by_doc = {v: k for k, v in doc_of.items()}
    targets = [d["id"] for d in corpus["documents"][:10]]
    with connection() as db, db.cursor() as cur:
        cur.execute("SELECT replace(id::text,'-',''),version_key FROM public.pr_library_segments WHERE workspace_id=%s AND superseded_at IS NULL "
                    "ORDER BY version_key,ordinal", (wid,))
        first_segment = {}
        for sid, vk in cur.fetchall():
            first_segment.setdefault(vk, sid)
        for key, doc_id in doc_of.items():
            index.write_embeddings(cur, wid, {"assetId": key, "versionId": key},
                                   [{"modality": "text", "modelId": "fixture/plumbing-1024", "dims": 1024, "vector": fixture_vector(doc_id), "segmentId": first_segment[key]}],
                                   consent_revision=0, index_generation=1)
    ranks = {}
    for doc_id in targets:
        result = run(wid, f"plumbing probe {doc_id}", modes=("semantic",), embedder=Embedder(fixture_vector(doc_id)))
        found = [doc_of.get(h["assetRef"]["versionId"]) for h in result["hits"]]
        ranks[doc_id] = (found.index(doc_id) + 1 if doc_id in found else None, result["coverage"]["modesApplied"])
    check("vector plumbing: kNN over 1,004 fixture vectors returns each probed document first (synthetic vectors, not semantic quality)",
          all(rank == 1 and modes == ["semantic"] for rank, modes in ranks.values()), ranks)
    plumbing = {"probes": len(targets), "rankOfTarget": {k: v[0] for k, v in ranks.items()}, "label": "synthetic fixture vectors: SQL/HNSW plumbing only"}

report = {
    "status": "pass" if lexical_recall >= LEXICAL_THRESHOLD else "fail",
    "phase": PHASE, "label": "LEXICAL-ONLY BASELINE: not the A026 semantic/hybrid target (that needs real embeddings: scripts/library-intelligence-eval.py)",
    "sets": {"corpus": corpus["version"], "queries": qset["version"], "distractors": evaluation.DISTRACTOR_VERSION, "documents": len(documents)},
    "indexGeneration": first[0]["indexGeneration"], "normalizerVersion": textnorm.NORMALIZER_VERSION, "rankingVersion": search.RANKING_VERSION,
    "recallAt10": summary, "lexicalThreshold": LEXICAL_THRESHOLD,
    "misses": [{"id": r["id"], "type": r["type"], "relevant": r["relevant"], "top10": r["top10"]} for r in first
               if evaluation.recall_at(r["top10"], r["relevant"]) < 1.0],
    "timing": {"seedSeconds": seed_seconds, "hundredQueriesSeconds": first_seconds, "note": "functional observation, not the A031 benchmark"},
    "isolation": "unchanged with 64 near-copies in a second workspace", "plumbing": plumbing, "checks": checks,
}
print(json.dumps(report, indent=2, ensure_ascii=False))
check(f"A026 exact/lexical queries reach Recall@10 >= {LEXICAL_THRESHOLD}", lexical_recall >= LEXICAL_THRESHOLD,
      {"recall": lexical_recall, "misses": [m["id"] for m in report["misses"] if m["type"] == "lexical"]})
