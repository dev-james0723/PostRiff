"""Connection Health Center on disposable PostgreSQL (rls.sql chain): the read endpoint never shows another workspace.

Connection ids are sha256(provider:account), so the same Threads account connected in two workspaces has the same id in
both. Workspace B gets newer, failing and running facts for that id; workspace A's reading must show only its own. Also:
foreign members get the same 403 as any foreign workspace, an unlisted workspace gets the unknown-route 404, viewers see
health but no reconnect, and the hosted route serves the same reading. Real records only: the channel is saved through
`upsert_verified_channel` and its capability rows come from `OAuthService._capabilities`.

    POSTRIFF_PG_BIN=... python scripts/postriff_pg_suite.py postgres_connection_health
"""
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2 import connection_health as health
from postriff_phase2.growth.metric_schedule import MetricScheduler
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.providers import ThreadsProvider

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-00000000c101"
TWO = "00000000-0000-0000-0000-00000000c102"
VIEWER = "00000000-0000-0000-0000-00000000c109"
TOKENS = {"one": ONE, "two": TWO, "viewer": VIEWER}
HTTP_TOKENS = {name: name + "-health-session-000000000000000000" for name in TOKENS}
TOKENS.update({HTTP_TOKENS[name]: principal for name, principal in list(TOKENS.items())})
NOW = time.time()
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required.", 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: NOW


def check(name, ok, detail=None):
    checks.append(name)
    assert ok, (name, detail)


def denied(call):
    try:
        call()
    except AlphaError as error:
        return error.status, str(error)
    raise AssertionError("accepted")


adapter = ThreadsProvider("synthetic-id", "synthetic-secret")
adapter.production_reviewed = True
service = HostedWorkspaceService(connection, verify, clock=lambda: NOW, vault=CredentialVault(CredentialVault.generate_key()),
                                 providers={"threads": adapter}, public_base_url="https://app.postriff.example")
with connection() as db:
    # The shared RLS fixture deliberately tombstones its second account. Use independent identities.
    for user in (ONE, TWO, VIEWER):
        db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (user,))
wid_a = service.bootstrap("one", "studio")["workspaceId"]
wid_b = service.bootstrap("two", "assist")["workspaceId"]
service.bootstrap("viewer", "studio")
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active')", (wid_a, VIEWER))
assert wid_a != wid_b

# The same Threads account, connected in both workspaces with every scope (a real record and a real matrix).
scopes = sorted({scope for values in adapter.SCOPES.values() for scope in values})
connection_id = OAuthService._connection_id("threads", "same-account")
matrix = OAuthService._capabilities(adapter, "publish", scopes, [], NOW, "synthetic-access")
for wid, token in ((wid_a, "one"), (wid_b, "two")):
    record = {"id": connection_id, "platform": "Threads", "account": "@same", "accountType": "professional", "scopes": scopes,
              "verifiedAt": NOW, "expiresAt": NOW + 30 * 86400, "capabilityVersion": adapter.capability_version, "providerAccountId": "same-account"}
    snapshot = service.get(wid, token)
    service.repository.command(wid, token, snapshot["revision"], lambda state, actor, record=record: service.commands.upsert_verified_channel(state, actor, record), requirement="manage_connections")
    with connection() as db:
        for name, value in matrix.items():
            db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level,evidence,capability_version,verified_at) VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s))",
                       (wid, connection_id, name, value["level"], value["evidence"], value["capabilityVersion"], value["verifiedAt"] or NOW))


def observation(db, wid, post, ingested):
    db.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,metric,definition_version,value,unit,availability,observed_at,ingested_at) "
               "VALUES(%s,%s,'threads',%s,'views','2026-09',10,'count','available',to_timestamp(%s),to_timestamp(%s))", (wid, connection_id, post, ingested, ingested))


with connection() as db:
    observation(db, wid_a, "post-a", NOW - 3600)                  # A: one reading an hour ago
    db.execute("INSERT INTO public.pr_history_imports(workspace_id,connection_id,provider,status,created_at,updated_at) VALUES(%s,%s,'threads','done',to_timestamp(%s),to_timestamp(%s))",
               (wid_a, connection_id, NOW - 3 * 86400, NOW - 2 * 86400))
    observation(db, wid_b, "post-b", NOW - 60)                    # B: newer data, a running import, a dead read
    db.execute("INSERT INTO public.pr_history_imports(workspace_id,connection_id,provider,status,created_at,updated_at) VALUES(%s,%s,'threads','running',to_timestamp(%s),to_timestamp(%s))",
               (wid_b, connection_id, NOW - 120, NOW - 30))
    db.execute("INSERT INTO public.pr_metric_reads(workspace_id,connection_id,provider,provider_post_id,read_offset,source,anchor_at,due_at,status,attempts,updated_at) "
               "VALUES(%s,%s,'threads','post-b','24h','verification',to_timestamp(%s),to_timestamp(%s),'dead',5,to_timestamp(%s))",
               (wid_b, connection_id, NOW - 86400, NOW - 3600, NOW - 10))

ENV = {health.FLAG: "1", health.WORKSPACES: f"{wid_a},{wid_b}"}
service.connection_health_env = ENV
service.metric_reads = MetricScheduler(connection, service.oauth, transport=None, workspace_allowlist=[wid_a, wid_b])
service.publishing_live = True   # what runtime_from_environment sets when hosted publishing transport is mounted


def account(result):
    found = [a for p in result["platforms"] for a in p["accounts"]]
    assert len(found) == 1, found
    return found[0]


# 1. Workspace A sees only its own facts for the shared connection id.
a = account(health.ConnectionHealth(service).read(wid_a, "one"))
check("A: the shared connection id reads A's last analytics, not B's newer one",
      abs(a["sync"]["lastSuccessAt"] - (NOW - 3600)) < 2 and a["sync"]["lastSuccessKind"] == "analytics", a["sync"])
check("A: B's running import and dead read do not leak", a["sync"]["status"] == "idle" and a["sync"]["lastProblemAt"] is None and a["state"] != "syncing", a)
check("A: freshness is A's newest data", abs(a["freshness"]["latestDataAt"] - (NOW - 3600)) < 2 and a["freshness"]["band"] == "recent", a["freshness"])
check("A: a reviewed, fully granted, collected Threads account reads ready",
      a["state"] == "ready" and a["lines"]["publishing"]["status"] == "available" and a["lines"]["analytics"]["status"] == "available", a)
check("A: the owner may reconnect through the existing OAuth flow", a["reconnect"]["available"] and a["reconnect"]["providerId"] == "threads", a["reconnect"])

# 2. Workspace B sees its own running import and failure; never A's.
b = account(health.ConnectionHealth(service).read(wid_b, "two"))
check("B: its own running import shows as syncing", b["state"] == "syncing" and b["sync"]["status"] == "running", b)
check("B: its own newest reading", abs(b["sync"]["lastSuccessAt"] - (NOW - 60)) < 2, b["sync"])

# 3. Membership, admission and roles.
status, message = denied(lambda: health.ConnectionHealth(service).read(wid_a, "two"))
foreign = denied(lambda: service.oauth.channels(wid_a, "two"))
check("a member of B reading A gets the Channels page's own foreign-workspace answer", (status, message) == foreign == (403, "Workspace unavailable."), (status, message, foreign))
service.connection_health_env = {health.FLAG: "1", health.WORKSPACES: wid_b}
status, message = denied(lambda: health.ConnectionHealth(service).read(wid_a, "one"))
check("an unlisted workspace gets the unknown-route answer", (status, message) == (404, "This hosted route is unavailable."), (status, message))
service.connection_health_env = {health.FLAG: "1"}
check("an empty list admits nobody", denied(lambda: health.ConnectionHealth(service).read(wid_a, "one"))[0] == 404)
service.connection_health_env = ENV
viewer = health.ConnectionHealth(service).read(wid_a, "viewer")
check("a viewer reads health but is offered no reconnect", not viewer["canManage"] and account(viewer)["reconnect"] == {"available": False, "reason": "manage_required"}, viewer)
check("a viewer reads the same facts as the owner", account(viewer)["sync"] == a["sync"], account(viewer)["sync"])

# 4. The hosted route serves the same reading; with the flag off it is the unknown route and Channels is unchanged.
def call(path, token="one"):
    captured = {}
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "wsgi.input": io.BytesIO(b""), "wsgi.url_scheme": "https",
               "HTTP_HOST": "app.postriff.example", "HTTP_AUTHORIZATION": "Bearer " + HTTP_TOKENS[token]}
    body = b"".join(HostedApplication(service, None)(environ, lambda status, headers: captured.update(status=status)))
    return captured["status"], json.loads(body)


status, body = call(f"/api/workspaces/{wid_a}/connection-health")
check("route: the hosted reading matches the service", status.startswith("200") and account(body)["sync"] == a["sync"] and body["contract"] == health.CONTRACT, (status, body))
status, body = call(f"/api/workspaces/{wid_a}/channels")
check("route: Channels names the Health Center only while enabled", body.get("connectionHealth") == {"available": True, "href": health.HREF}, body.get("connectionHealth"))
service.connection_health_env = {}
off = call(f"/api/workspaces/{wid_a}/connection-health")
unknown = call(f"/api/workspaces/{wid_a}/no-such-route")
check("route: flag off answers exactly like an unknown route", off == unknown and off[0].startswith("404"), (off, unknown))
status, body = call(f"/api/workspaces/{wid_a}/channels")
check("route: flag off leaves Channels byte-for-byte as the service returns it", body == json.loads(json.dumps(service.oauth.channels(wid_a, "one"), ensure_ascii=False)) and "connectionHealth" not in body)

# 5. The read wrote nothing: no capability row, credential or workspace revision changed.
with connection() as db:
    revisions = {str(w): r for w, r in db.execute("SELECT id,revision FROM public.pr_workspaces WHERE id = ANY(%s::uuid[])", ([wid_a, wid_b],)).fetchall()}
service.connection_health_env = ENV
health.ConnectionHealth(service).read(wid_a, "one")
with connection() as db:
    after = {str(w): r for w, r in db.execute("SELECT id,revision FROM public.pr_workspaces WHERE id = ANY(%s::uuid[])", ([wid_a, wid_b],)).fetchall()}
check("reading health changes no workspace revision", revisions == after, (revisions, after))

print(json.dumps({"status": "PASS", "checks": checks}))
