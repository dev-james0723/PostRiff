#!/usr/bin/env python3
"""A031 Library search load bench (cloud Linux CI only; never on the Mac control plane).

Starts its own disposable PostgreSQL cluster (POSTRIFF_PG_BIN, port 55439), applies tests/phase2/rls.sql (all migrations
through 097), seeds 10,000 mixed assets in one workspace (7,000 normalized documents/audio with multilingual segments,
3,000 legacy photos/videos in workspace JSON) plus a second workspace, then measures the shared search_library:

- cold: the first request after the cluster starts, reported separately;
- warm: 100 measured requests per kind at 8 concurrent scoped searches, after a warm-up;
- lexical = exact + lexical modes; hybrid = lexical + semantic (+ visual similarTo for a share of requests).

Budgets (acceptance A031): lexical p95 <= 2,000 ms, hybrid p95 <= 3,000 ms. Hybrid uses a SYNTHETIC fixture query vector
and fixture document vectors, so it measures database retrieval and fusion, not provider network latency or semantic
quality; the receipt says so. Exit code 0 = within budget, 1 = over budget, 64 = refused (not cloud CI), 3 = no Postgres.
"""
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
PORT = 55439
DSN = f"host=127.0.0.1 port={PORT} dbname=postgres"
BUDGET_MS = {"lexical": 2000.0, "hybrid": 3000.0}
MEASURED, CONCURRENCY, WARMUP = 100, 8, 16
DOCUMENTS, MEDIA = 7000, 3000
ONE = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000055"
MODEL = "openai/text-embedding-3-large"
PHRASES = ["Brahms sonata fingering notes", "演奏會門票已經售完", "演奏会排练时间表", "今晚 rehearsal 喺 City Hall", "spring concert season budget",
           "我哋喺錄音室試咪", "harbour sunset photo shoot plan", "piano recital programme draft", "學生考試曲目清單", "masterclass feedback summary"]
QUERIES = ["Brahms fingering", "演奏會", "演奏会 门票", "rehearsal 喺", "concert budget", "錄音室", "harbour sunset", "recital programme", "考試曲目",
           "masterclass", "brief-03141.md", "1080x1920", "studio diary 0420"]


def refuse_outside_ci():
    if platform.system() != "Linux" or os.environ.get("CI") != "true":
        print("The Library search bench runs in cloud Linux CI only (James Cloud Build). It is not run on the Mac.", file=sys.stderr)
        sys.exit(64)


def vector(dims, seed):
    rnd = random.Random(seed)
    v = [rnd.gauss(0, 1) for _ in range(dims)]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def percentile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


class FixtureEmbedder:
    def __init__(self):
        self.vector = vector(1024, 7)

    def model(self, capability):
        return MODEL

    def require(self, capability):
        return None

    def estimate(self, capability, *, units):
        return 1

    def embed(self, texts, *, dims=1024):
        from postriff_phase2.library_intelligence import providers
        return providers.ProviderResult([list(self.vector) for _ in texts], "fixture", MODEL, 0)


def cluster(pg_bin: Path, workdir: Path):
    data = workdir / "data"
    subprocess.run([str(pg_bin / "initdb"), "-D", str(data), "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(pg_bin / "pg_ctl"), "-D", str(data), "-l", str(workdir / "postgres.log"), "-o", f"-h 127.0.0.1 -p {PORT}", "-w", "start"],
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(pg_bin / "psql"), DSN, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / "tests/phase2/rls.sql")], check=True, stdout=subprocess.DEVNULL)
    return data


def seed(connection, service):
    import psycopg  # noqa: F401
    from postriff_phase2.library_intelligence import index, textnorm
    with connection() as db:
        db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (OTHER,))
    wid = service.bootstrap("one", "studio")["workspaceId"]
    other = service.bootstrap("other", "studio")["workspaceId"]
    base = time.time() - 400 * 86400
    rows, segments, docs = [], [], []
    for i in range(DOCUMENTS):
        aid = uuid.uuid5(uuid.NAMESPACE_URL, f"bench/{i}")
        kind, mime, ext = ("audio", "audio/mpeg", "mp3") if i % 7 == 0 else ("document", "text/markdown", "md")
        sha = hashlib.sha256(f"bench-{i}".encode()).hexdigest()
        created = base + i * 3600
        rows.append((aid, wid, ONE, f"brief-{i:05d}.{ext}", kind, mime, ext, 1000 + i, sha, "postriff-library", f"{aid.hex}.{ext}", created))
        docs.append((aid.hex, sha, created))
        for ordinal in range(3):
            text = f"{PHRASES[(i + ordinal) % len(PHRASES)]} — studio diary {i:04d} part {ordinal}"
            segments.append((uuid.uuid4(), wid, aid.hex, aid.hex, ordinal, "text", text, None, hashlib.sha256(text.encode()).hexdigest(), sha,
                             textnorm.NORMALIZER_VERSION, textnorm.search_terms(text), created + 60))
    photos = [{"id": uuid.uuid5(uuid.NAMESPACE_URL, f"bench/photo/{n}").hex, "mime": "video/mp4" if n % 10 == 0 else "image/jpeg",
               "width": 1080, "height": 1920 if n % 2 else 1080, "originalFilename": f"shot-{n:05d}.jpg", "createdAt": base + n * 600, "bytes": 2000}
              for n in range(MEDIA)]
    with connection() as db, db.cursor() as cur:
        cur.executemany("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,kind,mime,extension,bytes,sha256,bucket,object_name,"
                        "processing_status,analysis_status,indexing_status,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ready','not_applicable',"
                        "'ready',to_timestamp(%s),now())", rows)
        cur.executemany("INSERT INTO public.pr_library_segments(id,workspace_id,asset_key,version_key,ordinal,kind,text,language,locator,extractor,extractor_version,"
                        "text_hash,source_sha256,origin,normalizer_version,search_terms,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,NULL,'bench','1',%s,%s,"
                        "'extracted',%s,%s,to_timestamp(%s))", segments)
        cur.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{phase2,assets}',%s::jsonb),revision=revision+1 WHERE id=%s", (json.dumps(photos), wid))
        other_rows = [(uuid.uuid5(uuid.NAMESPACE_URL, f"bench/other/{i}"), other, OTHER, f"other-{i}.md", "document", "text/markdown", "md", 10, None,
                       "postriff-library", f"{uuid.uuid5(uuid.NAMESPACE_URL, f'bench/other/{i}').hex}.md", base) for i in range(50)]
        cur.executemany("INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,kind,mime,extension,bytes,sha256,bucket,object_name,"
                        "processing_status,analysis_status,indexing_status,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ready','not_applicable',"
                        "'ready',to_timestamp(%s),now())", other_rows)
    vectors = False
    with connection() as db, db.cursor() as cur:
        if index.vector_available(cur):
            vectors = True
            for n, (key, _sha, _created) in enumerate(docs):  # SYNTHETIC fixture vectors (labelled): retrieval cost, not semantic quality
                index.write_embeddings(cur, wid, {"assetId": key, "versionId": key},
                                       [{"modality": "text", "modelId": MODEL, "dims": 1024, "vector": vector(1024, n), "segmentId": None}],
                                       consent_revision=0, index_generation=1)
            for n, photo in enumerate(photos):
                index.write_embeddings(cur, wid, {"assetId": photo["id"], "versionId": photo["id"]},
                                       [{"modality": "visual", "modelId": index.VISUAL_MODEL, "dims": 256, "vector": vector(256, 10_000 + n), "segmentId": None}],
                                       consent_revision=0, index_generation=1)
        cur.execute("ANALYZE public.pr_library_assets")
        cur.execute("ANALYZE public.pr_library_segments")
        cur.execute("ANALYZE public.pr_library_embeddings")
    return wid, docs, photos, vectors


def main():
    refuse_outside_ci()
    pg_bin = Path(os.environ.get("POSTRIFF_PG_BIN", "/usr/lib/postgresql/16/bin"))
    if not (pg_bin / "initdb").is_file():
        print(json.dumps({"status": "VALIDATION_UNAVAILABLE", "reason": f"{pg_bin}/initdb missing; set POSTRIFF_PG_BIN"}))
        return 3
    os.environ["RAFII_LIBRARY_RETRIEVAL_ENABLED"] = "1"
    import psycopg
    from postriff_alpha.domain import AlphaError
    from postriff_phase2.hosted import HostedWorkspaceService
    from postriff_phase2.library_intelligence import api, index

    index._reserve = lambda *a, **k: {"status": "reserved", "reservationId": "bench-fixture"}  # synthetic budget admission (labelled)
    index._settle = lambda *a, **k: None

    def connection():
        return psycopg.connect(DSN, client_encoding="utf8")

    def verify(token):
        if token not in ("one", "other"):
            raise AlphaError("Verified session required.", 401)
        return ONE if token == "one" else OTHER

    verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
    verify.auth_time = lambda token, principal: time.time()

    with tempfile.TemporaryDirectory(prefix="library-bench-") as tmp:
        data = cluster(pg_bin, Path(tmp))
        try:
            service = HostedWorkspaceService(connection, verify)
            seed_started = time.monotonic()
            wid, docs, photos, vectors = seed(connection, service)
            seed_seconds = round(time.monotonic() - seed_started, 1)
            provider = SimpleNamespace(library_intelligence=SimpleNamespace(providers=FixtureEmbedder()))
            lock = threading.Lock()
            errors = []

            def request(kind, n):
                query = QUERIES[n % len(QUERIES)]
                params = {"query": query, "limit": 30, "modes": ["lexical"] if kind == "lexical" else ["lexical", "semantic"]}
                if kind == "hybrid" and n % 4 == 0 and vectors:
                    photo = photos[n % len(photos)]["id"]
                    params = {"query": "", "similarTo": {"assetId": photo, "versionId": photo, "sha256": ""}, "limit": 30}
                started = time.monotonic()
                try:
                    with connection() as db, db.cursor() as cur:
                        result = api.search(cur, ONE, wid, params, service=provider)
                except Exception as error:  # recorded, never hidden
                    with lock:
                        errors.append(f"{kind}:{type(error).__name__}:{str(error)[:120]}")
                    return None
                elapsed = (time.monotonic() - started) * 1000
                return elapsed, result["coverage"]["modesApplied"], result["coverage"]["accessibleAssetCount"]

            cold = request("lexical", 0)
            for n in range(WARMUP):
                request("lexical", n)
                request("hybrid", n)
            measured = {}
            for kind in ("lexical", "hybrid"):
                started = time.monotonic()
                with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
                    outcomes = [o for o in pool.map(lambda n: request(kind, n), range(MEASURED)) if o]
                wall = time.monotonic() - started
                latencies = [o[0] for o in outcomes]
                modes = sorted({m for o in outcomes for m in o[1]})
                measured[kind] = {"requests": len(latencies), "p50Ms": round(statistics.median(latencies), 1) if latencies else None,
                                  "p95Ms": round(percentile(latencies, 0.95), 1) if latencies else None, "maxMs": round(max(latencies), 1) if latencies else None,
                                  "throughputPerSecond": round(len(latencies) / wall, 2) if wall else None, "modesApplied": modes,
                                  "accessibleAssetCount": outcomes[0][2] if outcomes else None, "budgetP95Ms": BUDGET_MS[kind]}
            with connection() as db:
                pg_version = db.execute("SHOW server_version").fetchone()[0]
                ext = db.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
            within = all(m["requests"] == MEASURED and m["p95Ms"] is not None and m["p95Ms"] <= m["budgetP95Ms"] for m in measured.values()) and not errors
            receipt = {
                "status": "pass" if within else "fail", "acceptance": "A031", "candidateSha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                                                                                           capture_output=True, text=True).stdout.strip() or "unknown",
                "dataset": {"assets": DOCUMENTS + MEDIA, "normalized": DOCUMENTS, "legacyMedia": MEDIA, "segments": DOCUMENTS * 3, "vectors": vectors,
                            "seedSeconds": seed_seconds},
                "load": {"concurrency": CONCURRENCY, "measuredPerKind": MEASURED, "warmupPerKind": WARMUP},
                "coldFirstRequestMs": round(cold[0], 1) if cold else None, "warm": measured, "errors": errors[:20],
                "hardware": {"platform": platform.platform(), "machine": platform.machine(), "cpus": os.cpu_count(),
                             "memory": next((line.split(":", 1)[1].strip() for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemTotal")), "unknown")
                             if Path("/proc/meminfo").exists() else "unknown"},
                "database": {"postgres": pg_version, "pgvector": ext[0] if ext else None, "network": "loopback (same runner)"},
                "labels": ["hybrid uses a synthetic fixture query vector and fixture document vectors: database retrieval and fusion cost only",
                           "provider network latency and semantic quality are not measured here", "budget admission is stubbed"],
            }
            print(json.dumps(receipt, indent=2, ensure_ascii=False))
            return 0 if within else 1
        finally:
            subprocess.run([str(pg_bin / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], check=False, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    sys.exit(main())
