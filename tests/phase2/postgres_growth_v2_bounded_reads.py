"""AC38 / R-NFR-04: the program's bounded metadata reads, measured on a disposable PostgreSQL 17 with a synthetic fixture.

This is supporting evidence, not the SLO. The PRD's p95 ≤ 1 s for 10 concurrent sessions on 50-row pages is a proposed
*staging* target, to be measured on an agreed representative fixture before it is adopted. This group records the same
shape of measurement wherever CI runs it: fixture size, payload bytes and p50/p95/max per endpoint, through the real
WSGI application with 10 concurrent sessions. It fails only on an unbounded page (more rows than requested), a non-200
read, or a pathological regression (p95 over 5 s). Synthetic identities and data only; nothing calls a provider.
"""
import io
import json
import os
import platform
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker import flags
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.oauth import CredentialVault

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
FLAGS = {name: "1" for name in ("RAFII_WEEKLY_OPERATOR_ENABLED", "RAFII_FIRST_WEEK_ENABLED", "RAFII_RESULTS_ENABLED", "RAFII_RELATIONSHIPS_ENABLED",
                                "RAFII_SERIES_ENABLED", "RAFII_VISUAL_PACK_ENABLED", "RAFII_SOURCE_UPLOADS_ENABLED",
                                "RAFII_OPPORTUNITY_BRIEF_ENABLED", "RAFII_PROOF_V2_ENABLED")}
os.environ.update(FLAGS)
flags.attach(FLAGS)
CONCURRENCY, SAMPLES, PAGE, SEEDED = 10, 50, 50, 120
CLOCK = [time.time()]
USERS = {}


def connection(**kwargs):
    return psycopg.connect(DSN, client_encoding="utf8", **kwargs)


def verify(token):
    if token not in USERS:
        raise AlphaError("Verified session required.", 401)
    return USERS[token]


verify.session_id = lambda token, principal: "bounded-" + principal
verify.auth_time = lambda token, principal: CLOCK[0]

SERVICE = HostedWorkspaceService(connection, verify, clock=lambda: CLOCK[0], vault=CredentialVault(CredentialVault.generate_key()),
                                 public_base_url="https://app.example.org")
APP = HostedApplication(service=SERVICE, public_auth={})


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def call(path, session, query=""):
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0",
               "HTTP_HOST": "app.example.org", "wsgi.url_scheme": "https", "HTTP_AUTHORIZATION": "Bearer " + session}
    seen = {}

    def start_response(status, headers, exc_info=None):
        seen["status"] = int(status.split()[0])

    started = time.perf_counter()
    body = b"".join(APP(environ, start_response))
    return seen["status"], body, time.perf_counter() - started


def rows_in(body):
    """The first list in the response: the page's rows (None when the read is not a list)."""
    data = json.loads(body)
    return next((len(value) for value in data.values() if isinstance(value, list)), None) if isinstance(data, dict) else None


# --- fixture: one workspace, its owner, 120 declared results and 120 follow-ups, through the real services -----------------
owner = str(uuid.uuid4())
with connection() as db:
    db.execute("INSERT INTO auth.users(id) VALUES(%s)", (owner,))
SESSION = "s-" + owner
USERS[SESSION] = owner
W = SERVICE.bootstrap(SESSION, "studio")["workspaceId"]

from postriff_phase2.relationships import http as relationships_http  # noqa: E402 - flags first
from postriff_phase2.results.http import ensure as results_ensure  # noqa: E402

RESULTS = results_ensure(SERVICE)
RELATIONSHIPS = relationships_http.ensure(SERVICE)
seeded_at = time.perf_counter()
for i in range(SEEDED):
    RESULTS.declare(W, SESSION, {"type": ("lead", "booking", "sale", "newsletter_signup")[i % 4], "occurredAt": iso(CLOCK[0] - 3600 * (i + 1)),
                                 "idempotencyKey": f"bounded-result-{i}", **({"amount": {"minor": 1000 + i, "currency": "usd"}} if i % 4 in (1, 2) else {})})
    RELATIONSHIPS.create(W, SESSION, {"idempotencyKey": f"bounded-rel-{i:04d}", "displayName": f"Synthetic lead {i}",
                                      "contact": {"provider": "whatsapp", "ref": f"synthetic-{i}"}})
seed_seconds = time.perf_counter() - seeded_at

ENDPOINTS = [
    ("results ledger", f"/api/workspaces/{W}/results/events", f"limit={PAGE}"),
    ("results summary", f"/api/workspaces/{W}/results/summary", ""),
    ("follow-ups", f"/api/workspaces/{W}/relationships", f"limit={PAGE}&state=all"),
    ("series", f"/api/workspaces/{W}/series", f"limit={PAGE}"),
    ("visual packs", f"/api/workspaces/{W}/visual-packs", f"limit={PAGE}"),
    ("source uploads", f"/api/workspaces/{W}/source-uploads", f"limit={PAGE}"),
    ("first week", f"/api/workspaces/{W}/first-week", ""),
    ("opportunity brief", f"/api/workspaces/{W}/briefs/current", ""),
    ("proof revisions", f"/api/workspaces/{W}/proof/proofs", f"limit={PAGE}"),
    ("feature switches", f"/api/workspaces/{W}/growth-features", ""),
]

measured, problems = [], []
with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
    for label, path, query in ENDPOINTS:
        status, body, _ = call(path, SESSION, query)   # warm the route once (imports, first-use rows)
        if status != 200:
            problems.append(f"{label}: HTTP {status} {body[:200]!r}")
            continue
        rows = rows_in(body)
        if rows is not None and query.startswith("limit=") and rows > PAGE:
            problems.append(f"{label}: {rows} rows for a {PAGE}-row page")
        runs = list(pool.map(lambda _: call(path, SESSION, query), range(SAMPLES)))
        bad = [r[0] for r in runs if r[0] != 200]
        if bad:
            problems.append(f"{label}: {len(bad)} non-200 reads under concurrency ({sorted(set(bad))})")
        latencies = sorted(r[2] * 1000 for r in runs)
        p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
        measured.append({"endpoint": label, "rows": rows, "bytes": len(body), "p50Ms": round(statistics.median(latencies), 1),
                         "p95Ms": round(p95, 1), "maxMs": round(latencies[-1], 1)})
        if p95 > 5000:
            problems.append(f"{label}: p95 {p95:.0f} ms (pathological)")

print(json.dumps({"measurement": "growth-v2-bounded-reads", "evidence": "disposable PostgreSQL 17, synthetic fixture; not the staging SLO",
                  "environment": {"python": platform.python_version(), "machine": platform.machine(), "system": platform.system()},
                  "fixture": {"workspaces": 1, "declaredResults": SEEDED, "followUps": SEEDED, "seedSeconds": round(seed_seconds, 2)},
                  "concurrentSessions": CONCURRENCY, "samplesPerEndpoint": SAMPLES, "pageSize": PAGE, "endpoints": measured}, indent=1))
assert not problems, problems
print("PASS: every program read is bounded and answered 200 under 10 concurrent sessions")
