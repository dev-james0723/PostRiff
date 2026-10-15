"""Disposable PostgreSQL: the RAPv2 acceptance matrix rows that the shipped P0/H-1/A1 code can answer.

Each check is one matrix row (tests/acceptance-matrix.json in the RAPv2 delivery packet), run against real SQL, the real
token verifier (hosted_app.supabase_verifier, with an injected getUser that trusts these synthetic unsigned tokens), the
real HostedApplication routes, the Notification V2 worker and the Resend webhook ingest. Mail and push are fakes; no
provider is called, no real account or credential exists here.

A row whose expected result the code does not meet is recorded FAIL and stays in KNOWN_GAPS, so CI stays green while the
gap is open and turns red the day the behaviour changes (the row must then be re-classified). Any other failure is a
regression and fails the run. The JSON summary at the end is the evidence for docs/rapv2/acceptance-results-*.json.
"""
import base64
import io
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")


def guard_target(dsn):
    """RAP-147: refuse to touch anything but the dedicated disposable local cluster this runner starts."""
    parts = dict(item.split("=", 1) for item in dsn.split() if "=" in item) if "://" not in dsn else {}
    if "://" in dsn:
        url = urlparse(dsn)
        parts = {"host": url.hostname or "", "port": str(url.port or ""), "dbname": url.path.lstrip("/")}
    if parts.get("host") not in ("127.0.0.1", "localhost") or parts.get("port") != "55438" or parts.get("dbname") != "postgres":
        raise SystemExit("refusing: not the disposable local test cluster")
    return dsn


guard_target(DSN)

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import hosted_app, operator_actions  # noqa: E402
from postriff_phase2.coworker import flags  # noqa: E402
from postriff_phase2.email import Mailer  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_app import HostedApplication, supabase_verifier  # noqa: E402
from postriff_phase2.notifications import webhooks  # noqa: E402
from postriff_phase2.notifications.service import NotificationService  # noqa: E402

# Rows whose expected result the shipped code does not meet (recorded FAIL, see the module docstring).
KNOWN_GAPS = {
    "RAP-051": "a repeated DELETE of an already revoked session writes another session.revoked audit row",
    "RAP-088": "account deletion leaves pr_sessions rows (browser label, first/last seen) and person-level session.* audit events",
    "RAP-133": "200 first sightings with alerts on send 200 new-sign-in emails; no per-person cap on the legacy path",
    "RAP-143": "the legacy new-sign-in mail is sent synchronously inside the request after commit",
}

results = {}


def check(row, description):
    def wrap(fn):
        try:
            fn()
            results[row] = {"status": "PASS", "check": description}
        except Exception as error:  # noqa: BLE001 - every row is recorded, the run decides at the end
            results[row] = {"status": "FAIL", "check": description, "detail": f"{type(error).__name__}: {str(error)[:300]}"}
        return fn
    return wrap


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def sql(query, *args):
    with connection() as db:
        cur = db.execute(query, args)
        return cur.fetchall() if cur.description else []


def b64(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def token(user, session, aal="aal1", **claims):
    """A synthetic Supabase-shaped access token. getUser below is the only trust boundary, as in production."""
    payload = {"sub": user, "aal": aal, "iat": int(time.time()), "exp": int(time.time()) + 3600, **claims}
    if session is not None:
        payload["session_id"] = session
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(payload)}.sig-{uuid.uuid4().hex}"


def claims_of(access_token):
    encoded = access_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))


EXPIRED = set()


def get_user(url, access_token):
    try:
        claims = claims_of(access_token)
    except Exception:  # noqa: BLE001
        return {"status": 401, "body": {}}
    if claims.get("expired") or access_token in EXPIRED:
        return {"status": 401, "body": {}}
    return {"status": 200, "body": {"id": claims["sub"], "email_confirmed_at": "2026-10-01T00:00:00Z"}}


class FakeMailer:
    def __init__(self):
        self.calls = []

    def new_device(self, to, device_label, at, profile_url, time_zone=""):
        self.calls.append({"to": to, "device": device_label, "url": profile_url, "thread": threading.current_thread().name})
        return {"sent": True}


class Transport:
    """Fake Resend: accepts (an id, never `delivered`) or raises like an unreachable service."""
    def __init__(self):
        self.sent, self.fail = [], False

    def send(self, message):
        if self.fail:
            raise AlphaError("The email service is temporarily unavailable.", 503)
        self.sent.append(message)
        return {"id": f"re_{uuid.uuid4().hex}"}


# Founder blocks (migration 062) are not part of this harness; the verifier skips the probe while it is not installed.
operator_actions._STATE.update(status="not_installed", checked=float("inf"))
verify = supabase_verifier("https://project.supabase.co", "p" * 24, connection, get_user=get_user)
mailer = FakeMailer()
service = HostedWorkspaceService(connection, verify, public_base_url="https://app.rafii.example", mailer=mailer,
                                 email_lookup=lambda principal: f"{principal[:8]}@example.invalid")
verify.on_first_sighting = lambda principal, session_id, label, alert: service._alert_new_device(principal, session_id, label, alert)
app = HostedApplication(service, None, {"provider": "supabase"}, "c" * 24)
SAFARI = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"


def call(method, path, access_token=None, body=None, agent=SAFARI, headers=None):
    raw = json.dumps(body).encode() if body is not None else b""
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
               "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "https", "HTTP_HOST": "app.rafii.example", "HTTP_ORIGIN": "https://app.rafii.example",
               "HTTP_X_POSTRIFF_REQUEST": "founder-alpha", "HTTP_USER_AGENT": agent}
    if access_token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + access_token
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured = {}
    body_out = b"".join(app(environ, lambda status, values, *_: captured.update(status=status, headers=values)))
    return int(captured["status"].split()[0]), json.loads(body_out or b"{}")


def observe_mode(on=True, v2=False):
    values = {"RAFII_ACCOUNT_PROTECTION_V2_MODE": "observe"} if on else {}
    if v2:
        values["RAFII_NOTIFICATIONS_V2_ENABLED"] = "1"
    flags.attach(values)
    verify.seen.__init__()  # a fresh process: nothing seen yet


def person(alerts=False):
    user = str(uuid.uuid4())
    sql("INSERT INTO auth.users(id) VALUES(%s)", user)
    workspace = service.bootstrap(token(user, f"bootstrap-{uuid.uuid4().hex}"), "studio")["workspaceId"]
    if alerts:
        sql("UPDATE public.pr_profiles SET alert_new_device=true WHERE user_id=%s", user)
    sql("DELETE FROM public.pr_audit_events WHERE actor=%s AND kind LIKE 'session.%%'", user)
    return user, workspace


def new_session():
    return f"sess-{uuid.uuid4().hex}"


def observed(user, session=None):
    query = "SELECT count(*) FROM public.pr_audit_events WHERE actor=%s AND kind='session.observed'" + (" AND subject=%s" if session else "")
    return sql(query, *((user, session) if session else (user,)))[0][0]


def mails_to(user):
    return [m for m in mailer.calls if m["to"].startswith(user[:8])]


# --- Auth session observation (G1) ---------------------------------------------------------------------------------

for row, method, label in (("RAP-001", ["oauth"], "Google OAuth (amr oauth)"), ("RAP-002", ["otp"], "email OTP (amr otp)"), ("RAP-003", ["webauthn"], "passkey (amr webauthn)")):
    @check(row, f"{label}: first protected request records one session.observed for the verified subject and one alert decision")
    def first_sign_in(method=method):
        observe_mode()
        user, workspace = person(alerts=True)
        session = new_session()
        access = token(user, session, amr=[{"method": method[0], "timestamp": int(time.time())}])
        assert call("GET", f"/api/workspaces/{workspace}", access)[0] == 200
        assert call("GET", "/api/me", access)[0] == 200
        rows = sql("SELECT actor::text, meta FROM public.pr_audit_events WHERE kind='session.observed' AND subject=%s", session)
        assert len(rows) == 1 and rows[0][0] == user, rows
        assert rows[0][1]["alert"] is True, rows  # the durable decision recorded with the event
        assert len(mails_to(user)) == 1, mails_to(user)


@check("RAP-004", "POST /api/auth/verify (bootstrap) before GET /api/me: exactly one observation and one alert")
def bootstrap_first():
    observe_mode()
    user, _ = person(alerts=True)
    session = new_session()
    access = token(user, session)
    assert call("POST", "/api/auth/verify", access, {"plan": "studio"})[0] == 201
    assert call("GET", "/api/me", access)[0] == 200
    assert (observed(user, session), len(mails_to(user))) == (1, 1), (observed(user, session), mails_to(user))


@check("RAP-005", "GET /api/me then POST bootstrap: a single first-observed event across both routes")
def me_first():
    observe_mode()
    user, _ = person(alerts=True)
    session = new_session()
    access = token(user, session)
    assert call("GET", "/api/me", access)[0] == 200
    assert call("POST", "/api/auth/verify", access, {"plan": "studio"})[0] == 201
    assert (observed(user, session), len(mails_to(user))) == (1, 1)


@check("RAP-006", "GET /api/auth/sessions before /api/me: exactly one observation")
def sessions_first():
    observe_mode()
    user, _ = person(alerts=True)
    session = new_session()
    access = token(user, session)
    status, listed = call("GET", "/api/auth/sessions", access)
    assert status == 200 and [s["sessionId"] for s in listed["sessions"] if s["current"]] == [session], listed
    assert call("GET", "/api/me", access)[0] == 200
    assert (observed(user, session), len(mails_to(user))) == (1, 1)


@check("RAP-007", "a workspace API as the very first request: the verifier observes it, and its session checks run before any data")
def direct_api_first():
    observe_mode()
    user, workspace = person()
    session = new_session()
    assert call("GET", f"/api/workspaces/{workspace}", token(user, session))[0] == 200
    assert observed(user, session) == 1
    revoked = new_session()
    sql("INSERT INTO public.pr_session_revocations(user_id,session_id) VALUES(%s,%s)", user, revoked)
    status, body = call("GET", f"/api/workspaces/{workspace}", token(user, revoked))
    assert status == 401 and "workspace" not in json.dumps(body).lower().replace("workspaces", ""), (status, body)


@check("RAP-008", "GET /api/me ten times (cold process each time): one first-sighting event, one mail")
def repeated_me():
    observe_mode()
    user, _ = person(alerts=True)
    session = new_session()
    for _ in range(10):
        verify.seen.__init__()
        assert call("GET", "/api/me", token(user, session))[0] == 200
    assert (observed(user, session), len(mails_to(user))) == (1, 1)


@check("RAP-009", "parallel first requests (verifier, /api/me, sessions list, workspace) on one new session: one event, no deadlock")
def parallel_first():
    observe_mode()
    user, workspace = person(alerts=True)
    session = new_session()
    paths = ["/api/me", "/api/auth/sessions", f"/api/workspaces/{workspace}", "/api/me", "/api/me/security-events", "/api/auth/sessions"]
    statuses, barrier = [], threading.Barrier(len(paths))

    def hit(path):
        barrier.wait()
        statuses.append(call("GET", path, token(user, session))[0])

    threads = [threading.Thread(target=hit, args=(path,)) for path in paths]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not any(thread.is_alive() for thread in threads), "a request did not finish (deadlock?)"
    assert statuses.count(200) == len(paths), statuses
    assert (observed(user, session), len(mails_to(user))) == (1, 1), (observed(user, session), mails_to(user))


@check("RAP-010", "a refreshed JWT (new iat, same session_id) records no new sign-in")
def refresh_same_session():
    observe_mode()
    user, _ = person(alerts=True)
    session = new_session()
    assert call("GET", "/api/me", token(user, session))[0] == 200
    verify.seen.__init__()
    assert call("GET", "/api/me", token(user, session, iat=int(time.time()) + 3000, refreshed=True))[0] == 200
    assert (observed(user, session), len(mails_to(user))) == (1, 1)


@check("RAP-011", "a verified JWT without a session_id claim: 401 on every session route, zero rows, no substitute session")
def no_session_claim():
    observe_mode()
    user, workspace = person()
    access = token(user, None)
    for method, path in (("GET", "/api/me"), ("GET", "/api/auth/sessions"), ("POST", "/api/auth/verify"), ("GET", f"/api/workspaces/{workspace}")):
        assert call(method, path, access, {"plan": "studio"} if method == "POST" else None)[0] == 401, path
    assert sql("SELECT count(*) FROM public.pr_sessions WHERE user_id=%s AND session_id NOT LIKE 'bootstrap-%%'", user)[0][0] == 0
    assert observed(user) == 0


@check("RAP-012", "a forged userId/sessionId in a request body is ignored: the row belongs to the verified subject only")
def forged_body():
    observe_mode()
    victim, _ = person()
    attacker, _ = person()
    session = new_session()
    status, _ = call("PATCH", "/api/me", token(attacker, session), {"userId": victim, "sessionId": "forged-session-0000000001", "displayName": "Mallory"})
    assert status == 200
    assert sql("SELECT user_id::text FROM public.pr_sessions WHERE session_id=%s", session) == [(attacker,)]
    assert sql("SELECT count(*) FROM public.pr_sessions WHERE session_id='forged-session-0000000001'")[0][0] == 0
    assert observed(victim) == 0
    assert sql("SELECT coalesce(display_name,'') FROM public.pr_profiles WHERE user_id=%s", victim)[0][0] != "Mallory"


@check("RAP-015", "no token, an expired token and a token getUser refuses: every security endpoint answers 401, no data")
def signed_out():
    observe_mode()
    user, workspace = person()
    expired = token(user, new_session(), expired=True)
    routes = [("GET", "/api/me"), ("PATCH", "/api/me"), ("GET", "/api/auth/sessions"), ("POST", "/api/auth/sessions/revoke-others"),
              ("DELETE", f"/api/auth/sessions/{new_session()}"), ("GET", "/api/me/security-events"), ("POST", "/api/auth/mfa"),
              ("DELETE", "/api/auth/mfa"), ("POST", "/api/auth/logout"), ("GET", f"/api/workspaces/{workspace}")]
    for method, path in routes:
        for access in (None, expired, "not-a-jwt-" + "x" * 30):
            status, body = call(method, path, access, {} if method in ("POST", "PATCH", "DELETE") else None)
            assert status == 401, (method, path, status)
            assert set(body) <= {"error", "code", "requestId"}, body


# --- Session revocation (G4) ----------------------------------------------------------------------------------------

def signed_in(user):
    session = new_session()
    assert call("GET", "/api/me", token(user, session, aal="aal1", iat=int(time.time())))[0] == 200
    return session


@check("RAP-049", "DELETE /api/auth/sessions/{own other}: that session is denied, the current one keeps working")
def revoke_own_other():
    observe_mode()
    user, workspace = person()
    current, other = signed_in(user), signed_in(user)
    status, body = call("DELETE", f"/api/auth/sessions/{other}", token(user, current), {})
    assert status == 200 and body["revoked"] is True and body["current"] is False, body
    assert call("GET", f"/api/workspaces/{workspace}", token(user, other))[0] == 401
    assert call("GET", f"/api/workspaces/{workspace}", token(user, current))[0] == 200


@check("RAP-050", "DELETE of another person's session id: the same 404 as an unknown id, and B's session unchanged")
def revoke_foreign():
    observe_mode()
    alice, _ = person()
    bob, bob_workspace = person()
    mine, bobs = signed_in(alice), signed_in(bob)
    foreign = call("DELETE", f"/api/auth/sessions/{bobs}", token(alice, mine), {})
    unknown = call("DELETE", f"/api/auth/sessions/{new_session()}", token(alice, mine), {})
    strip = lambda result: (result[0], {k: v for k, v in result[1].items() if k != "requestId"})
    assert strip(foreign) == strip(unknown) and foreign[0] == 404, (foreign, unknown)
    assert sql("SELECT count(*) FROM public.pr_session_revocations WHERE session_id=%s", bobs)[0][0] == 0
    assert call("GET", f"/api/workspaces/{bob_workspace}", token(bob, bobs))[0] == 200


@check("RAP-051", "repeating DELETE on an already revoked session: same safe response, no second audit row")
def revoke_twice():
    observe_mode()
    user, _ = person()
    current, other = signed_in(user), signed_in(user)
    first = call("DELETE", f"/api/auth/sessions/{other}", token(user, current), {})
    second = call("DELETE", f"/api/auth/sessions/{other}", token(user, current), {})
    assert first[0] == second[0] == 200, (first, second)
    audit_rows = sql("SELECT count(*) FROM public.pr_audit_events WHERE actor=%s AND kind='session.revoked' AND subject=%s", user, other)[0][0]
    assert audit_rows == 1, f"{audit_rows} session.revoked rows for one session"


@check("RAP-052", "a revoked session's still-valid access JWT: 401 on the next hosted API request, no data")
def revoked_hosted():
    observe_mode()
    user, workspace = person()
    current, other = signed_in(user), signed_in(user)
    stolen = token(user, other)
    assert call("GET", f"/api/workspaces/{workspace}", stolen)[0] == 200
    call("DELETE", f"/api/auth/sessions/{other}", token(user, current), {})
    for path in (f"/api/workspaces/{workspace}", "/api/me", "/api/auth/sessions", "/api/me/security-events"):
        status, body = call("GET", path, stolen)
        assert status == 401 and set(body) <= {"error", "code", "requestId"}, (path, status, body)


@check("RAP-053", "the same revoked JWT straight through the Data API (authenticated role + JWT claims): reads no workspace row")
def revoked_direct():
    observe_mode()
    user, workspace = person()
    current, other = signed_in(user), signed_in(user)
    call("DELETE", f"/api/auth/sessions/{other}", token(user, current), {})

    def reads(session):
        with connection() as db:
            db.execute("SET ROLE authenticated")
            db.execute("SELECT set_config('request.jwt.claim.session_id','',false)")
            db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (user,))
            db.execute("SELECT set_config('request.jwt.claims',%s,false)", (json.dumps({"sub": user, "session_id": session, "aal": "aal1", "role": "authenticated"}),))
            return db.execute("SELECT count(*) FROM public.pr_workspaces WHERE id=%s", (workspace,)).fetchone()[0]

    assert (reads(current), reads(other)) == (1, 0), (reads(current), reads(other))


@check("RAP-054", "the revoked JWT cannot list private Storage objects (the signing step reads storage.objects under the same guard)")
def revoked_storage():
    observe_mode()
    user, workspace = person()
    current, other = signed_in(user), signed_in(user)
    sql("INSERT INTO storage.objects(bucket_id,name) VALUES('postriff-private',%s)", f"{workspace}/synthetic/{uuid.uuid4().hex}.bin")
    call("DELETE", f"/api/auth/sessions/{other}", token(user, current), {})

    def objects(session):
        with connection() as db:
            db.execute("SET ROLE authenticated")
            db.execute("SELECT set_config('request.jwt.claim.session_id','',false)")
            db.execute("SELECT set_config('request.jwt.claims',%s,false)", (json.dumps({"sub": user, "session_id": session, "aal": "aal1"}),))
            db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (user,))
            return db.execute("SELECT count(*) FROM storage.objects WHERE bucket_id='postriff-private' AND name LIKE %s", (workspace + "/%",)).fetchone()[0]

    assert (objects(current) >= 1, objects(other)) == (True, 0)


@check("RAP-055", "POST revoke-others: every other session denied, the current one valid, the count exact")
def revoke_others():
    observe_mode()
    user, workspace = person()
    current = signed_in(user)
    others = [signed_in(user) for _ in range(3)]
    status, body = call("POST", "/api/auth/sessions/revoke-others", token(user, current), {})
    assert status == 200 and body["current"] == current, body
    # The bootstrap session person() used is another session of this person and is revoked too.
    expected = sql("SELECT count(*) FROM public.pr_sessions WHERE user_id=%s AND session_id<>%s", user, current)[0][0]
    assert body["revoked"] == expected == len(others) + 1, (body, expected)
    assert all(call("GET", f"/api/workspaces/{workspace}", token(user, s))[0] == 401 for s in others)
    assert call("GET", f"/api/workspaces/{workspace}", token(user, current))[0] == 200


@check("RAP-059", "revocation fence in both orders: a write after the revocation commits nothing; a write before it stands alone")
def revoke_race_orders():
    observe_mode()
    user, workspace = person()
    current, other = signed_in(user), signed_in(user)
    revision = call("GET", f"/api/workspaces/{workspace}", token(user, other))[1]["revision"]
    # Order 1: write first, then revoke. The write is the session's last.
    assert call("PATCH", "/api/me", token(user, other), {"displayName": "Before revoke"})[0] == 200
    call("DELETE", f"/api/auth/sessions/{other}", token(user, current), {})
    # Order 2: revoked, then the same token tries a profile write and a workspace command.
    assert call("PATCH", "/api/me", token(user, other), {"displayName": "After revoke"})[0] == 401
    assert call("POST", f"/api/workspaces/{workspace}/actions", token(user, other), {"expectedRevision": revision, "action": "rename_workspace", "payload": {"name": "After revoke"}})[0] == 401
    assert sql("SELECT display_name FROM public.pr_profiles WHERE user_id=%s", user)[0][0] == "Before revoke"
    assert sql("SELECT revision FROM public.pr_workspaces WHERE id=%s", workspace)[0][0] == revision


@check("RAP-060", "one revocation applies to the person in every workspace they belong to")
def revoke_across_workspaces():
    observe_mode()
    user, home = person()
    owner, shared = person()
    sql("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", shared, user)
    current, other = signed_in(user), signed_in(user)
    assert [call("GET", f"/api/workspaces/{w}", token(user, other))[0] for w in (home, shared)] == [200, 200]
    call("DELETE", f"/api/auth/sessions/{other}", token(user, current), {})
    assert [call("GET", f"/api/workspaces/{w}", token(user, other))[0] for w in (home, shared)] == [401, 401]


for row, what in (("RAP-062", "account protection flag off"), ("RAP-142", "the experimental v2 flag turned off after the revocation")):
    @check(row, f"{what}: a revoked session stays denied (core revocation does not depend on RAPv2)")
    def revoked_with_flag_off():
        observe_mode()
        user, workspace = person()
        current, other = signed_in(user), signed_in(user)
        call("DELETE", f"/api/auth/sessions/{other}", token(user, current), {})
        observe_mode(on=False)
        assert call("GET", f"/api/workspaces/{workspace}", token(user, other))[0] == 401
        assert call("GET", "/api/me", token(user, other))[0] == 401
        assert call("GET", f"/api/workspaces/{workspace}", token(user, current))[0] == 200


# --- Notifications (G2, G7) -----------------------------------------------------------------------------------------

for row, alerts in (("RAP-063", False), ("RAP-066", False), ("RAP-065", True)):
    @check(row, f"alert preference {'on' if alerts else 'off'}: the sign-in is in the account history, and {'exactly one' if alerts else 'no'} routine mail")
    def preference(alerts=alerts):
        observe_mode()
        user, _ = person(alerts=alerts)
        session = new_session()
        call("GET", "/api/me", token(user, session))
        verify.seen.__init__()
        call("GET", "/api/auth/sessions", token(user, session))
        history = call("GET", "/api/me/security-events", token(user, session))[1]["events"]
        assert [e["subject"] for e in history if e["kind"] == "session.observed"] == [session], history
        assert len(mails_to(user)) == (1 if alerts else 0), mails_to(user)


def v2_service(transport):
    real_mailer = Mailer(transport, "Rafii <security@rafii.example>", "https://app.rafii.example")
    v2_hosted = HostedWorkspaceService(connection, verify, public_base_url="https://app.rafii.example", mailer=real_mailer,
                                       email_lookup=lambda principal: f"{principal[:8]}@example.invalid")
    notifications = NotificationService(v2_hosted, {"RAFII_NOTIFICATIONS_V2_ENABLED": "1", "POSTRIFF_PUBLIC_BASE_URL": "https://app.rafii.example"}, email_transport=transport)
    return v2_hosted, notifications


def run_v2(notifications):
    # Not the service's very first run: that one baselines legacy-delivered alerts (covered by the P0 unit tests).
    sql("INSERT INTO public.pr_notification_scan(workspace_id,revision) SELECT id,0 FROM public.pr_workspaces LIMIT 1 ON CONFLICT DO NOTHING")
    return notifications.cron()


def security_deliveries(user):
    return sql("""SELECT d.id::text,d.status,d.attempts,d.max_attempts,d.provider_ref FROM public.pr_notification_deliveries d
                  JOIN public.pr_notification_events e ON e.id=d.event_id WHERE d.user_id=%s AND e.event_type='security.new_device' AND d.channel='email'""", user)


for row in ("RAP-067", "RAP-146"):
    @check(row, "one eligible sign-in with Notification V2 on: the legacy mailer stands down and V2 sends exactly one email; with V2 off the legacy mailer sends exactly one")
    def single_owner():
        transport = Transport()
        observe_mode(v2=True)
        v2_hosted, notifications = v2_service(transport)
        verify.on_first_sighting = lambda p, s, label, alert: v2_hosted._alert_new_device(p, s, label, alert)
        try:
            user, _ = person(alerts=True)
            call("GET", "/api/me", token(user, new_session()))
            assert sql("SELECT meta->>'sent' FROM public.pr_audit_events WHERE actor=%s AND kind='session.alerted'", user) in ([], [("false",)])
            run_v2(notifications)
            run_v2(notifications)  # a second cron finds nothing new
            assert len(security_deliveries(user)) == 1, security_deliveries(user)
            assert len([m for m in transport.sent if m["to"].startswith(user[:8])]) == 1, transport.sent
            # V2 off: the legacy path owns it, once.
            observe_mode(v2=False)
            legacy_user, _ = person(alerts=True)
            call("GET", "/api/me", token(legacy_user, new_session()))
            assert len([m for m in transport.sent if m["to"].startswith(legacy_user[:8])]) == 1
            assert notifications.cron() == {"status": "disabled"}
        finally:
            verify.on_first_sighting = lambda p, s, label, alert: service._alert_new_device(p, s, label, alert)


def v2_sign_in(transport):
    observe_mode(v2=True)
    v2_hosted, notifications = v2_service(transport)
    user, _ = person(alerts=True)
    with connection() as db:
        from postriff_phase2.hosted import observe_session
        observe_session(db.cursor(), user, new_session(), "Safari on iPhone")
    run_v2(notifications)
    return user, notifications


def due(user):
    sql("UPDATE public.pr_notification_deliveries SET next_attempt_at=now()-interval '1 second' WHERE user_id=%s AND status='pending'", user)


@check("RAP-068", "transport failure: the event and audit stay, retries are bounded with backoff, then the delivery is dead (not dropped)")
def transport_failure():
    transport = Transport()
    transport.fail = True
    user, notifications = v2_sign_in(transport)
    worker = notifications.worker()
    [(delivery, status, attempts, max_attempts, _)] = security_deliveries(user)
    for attempt in range(1, max_attempts + 1):
        due(user)
        worker.tick()
        _, status, attempts, _, _ = security_deliveries(user)[0]
        if attempt < max_attempts:
            assert status == "pending" and attempts == attempt, (status, attempts)
            assert sql("SELECT next_attempt_at > now() FROM public.pr_notification_deliveries WHERE id::text=%s", delivery)[0][0]
    assert status == "dead" and attempts == max_attempts and max_attempts <= 10, (status, attempts, max_attempts)
    assert observed(user) == 1 and transport.sent == []


@check("RAP-069", "provider accepted is `sent`, never `delivered`, until the provider's delivered webhook arrives")
def accepted_not_delivered():
    transport = Transport()
    user, notifications = v2_sign_in(transport)
    due(user)
    notifications.worker().tick()
    [(delivery, status, _, _, ref)] = security_deliveries(user)
    assert status == "sent" and ref, status
    event = {"type": "email.delivered", "created_at": "2026-10-15T00:00:00Z", "data": {"email_id": ref, "tags": [{"name": "delivery_id", "value": delivery}]}}
    with connection() as db:
        assert webhooks.ingest(db.cursor(), f"msg_{uuid.uuid4().hex}", event, json.dumps(event).encode())["outcome"] == "applied"
    assert security_deliveries(user)[0][1] == "delivered"


@check("RAP-070", "the same provider callback twice (and concurrently): applied once, no second email")
def webhook_duplicate():
    transport = Transport()
    user, notifications = v2_sign_in(transport)
    due(user)
    notifications.worker().tick()
    [(delivery, _, _, _, ref)] = security_deliveries(user)
    event = {"type": "email.delivered", "created_at": "2026-10-15T00:00:00Z", "data": {"email_id": ref, "tags": [{"name": "delivery_id", "value": delivery}]}}
    msg_id, outcomes = f"msg_{uuid.uuid4().hex}", []

    def deliver():
        with connection() as db:
            outcomes.append(webhooks.ingest(db.cursor(), msg_id, event, json.dumps(event).encode())["outcome"])

    threads = [threading.Thread(target=deliver) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(outcomes) == ["applied", "duplicate", "duplicate"], outcomes
    assert sql("SELECT count(*) FROM public.pr_notification_provider_events WHERE event_id=%s", msg_id)[0][0] == 1
    assert len([m for m in transport.sent if m["to"].startswith(user[:8])]) == 1


@check("RAP-071", "two delivery workers ticking at once: one lease, one send, one idempotency key")
def worker_race():
    transport = Transport()
    user, notifications = v2_sign_in(transport)
    due(user)
    workers, barrier = [notifications.worker(), notifications.worker()], threading.Barrier(2)

    def tick(worker):
        barrier.wait()
        worker.tick()

    threads = [threading.Thread(target=tick, args=(w,)) for w in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    mine = [m for m in transport.sent if m["to"].startswith(user[:8])]
    assert len(mine) == 1 and mine[0]["idempotencyKey"], mine
    assert security_deliveries(user)[0][1] == "sent"


@check("RAP-078", "a bounce receipt: the delivery is failed and email suppressed (visible to operations), never delivered")
def bounce():
    transport = Transport()
    user, notifications = v2_sign_in(transport)
    due(user)
    notifications.worker().tick()
    [(delivery, _, _, _, ref)] = security_deliveries(user)
    event = {"type": "email.bounced", "created_at": "2026-10-15T00:00:00Z", "data": {"email_id": ref, "tags": [{"name": "delivery_id", "value": delivery}]}}
    with connection() as db:
        webhooks.ingest(db.cursor(), f"msg_{uuid.uuid4().hex}", event, json.dumps(event).encode())
    assert security_deliveries(user)[0][1] == "failed"
    assert sql("SELECT failure_class FROM public.pr_notification_deliveries WHERE id::text=%s", delivery) == [("permanent",)]
    assert sql("SELECT bool_or(email_unsubscribed) FROM public.pr_notification_preferences WHERE user_id=%s", user) == [(True,)]
    with connection() as db:
        from postriff_phase2.notifications.delivery import backlog
        assert set(backlog(db.cursor())) >= {"due", "dead24h"}


# --- Database / RLS / tenancy (G5) ---------------------------------------------------------------------------------

SECURITY_TABLES = ("pr_sessions", "pr_session_revocations", "pr_audit_events", "pr_mfa_enforcement", "pr_account_tombstones")


@check("RAP-079", "anon: no SELECT/INSERT/UPDATE/DELETE on any session-security table (P0 tables; the P1 tables do not exist yet)")
def anon_tables():
    for table in SECURITY_TABLES:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not sql("SELECT has_table_privilege('anon', %s, %s)", f"public.{table}", privilege)[0][0], (table, privilege)


@check("RAP-080", "authenticated: no direct write on any session-security table, and no read of other people's or person-level rows")
def authenticated_tables():
    for table in SECURITY_TABLES:
        for privilege in ("INSERT", "UPDATE", "DELETE"):
            assert not sql("SELECT has_table_privilege('authenticated', %s, %s)", f"public.{table}", privilege)[0][0], (table, privilege)
    observe_mode()
    user, _ = person()
    signed_in(user)
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claims',%s,false)", (json.dumps({"sub": user, "session_id": "harness-session-000000000001", "aal": "aal1"}),))
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (user,))
        for table in ("pr_sessions", "pr_session_revocations", "pr_mfa_enforcement", "pr_account_tombstones"):
            try:
                db.execute(f"SELECT count(*) FROM public.{table}")
                raise AssertionError(f"authenticated could read {table}")
            except psycopg.errors.InsufficientPrivilege:
                db.rollback()
                db.execute("SET ROLE authenticated")
                db.execute("SELECT set_config('request.jwt.claims',%s,false)", (json.dumps({"sub": user, "session_id": "harness-session-000000000001"}),))
                db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (user,))
        # Person-level audit rows (sign-ins have no workspace) are never readable directly.
        assert db.execute("SELECT count(*) FROM public.pr_audit_events WHERE kind LIKE 'session.%%'").fetchone()[0] == 0


@check("RAP-081", "the service role performs the expected session writes and reads")
def service_writes():
    user = str(uuid.uuid4())
    with connection() as db:
        db.execute("SET ROLE service_role")
        db.execute("INSERT INTO public.pr_sessions(user_id,session_id,client_label) VALUES(%s,%s,'Chrome on Mac')", (user, "service-role-session-0001"))
        db.execute("INSERT INTO public.pr_session_revocations(user_id,session_id) VALUES(%s,%s)", (user, "service-role-session-0001"))
        db.execute("INSERT INTO public.pr_audit_events(actor,kind,subject,meta) VALUES(%s,'session.observed','service-role-session-0001','{}')", (user,))
        assert db.execute("SELECT count(*) FROM public.pr_sessions WHERE user_id=%s", (user,)).fetchone()[0] == 1


@check("RAP-082", "every session-security table has RLS enabled and FORCED, with policies")
def forced_rls():
    rows = sql("SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, (SELECT count(*) FROM pg_policy p WHERE p.polrelid=c.oid) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname = ANY(%s)", list(SECURITY_TABLES))
    assert len(rows) == len(SECURITY_TABLES), rows
    assert all(enabled and forced and policies > 0 for _, enabled, forced, policies in rows), rows


@check("RAP-086", "user A cannot read or command workspace B through the hosted API (membership check)")
def cross_tenant():
    observe_mode()
    alice, _ = person()
    bob, bob_workspace = person()
    access = token(alice, signed_in(alice))
    status, body = call("GET", f"/api/workspaces/{bob_workspace}", access)
    assert status in (403, 404), status
    revision = sql("SELECT revision FROM public.pr_workspaces WHERE id=%s", bob_workspace)[0][0]
    assert call("POST", f"/api/workspaces/{bob_workspace}/actions", access, {"expectedRevision": revision, "action": "rename_workspace", "payload": {"name": "Hijacked"}})[0] in (403, 404)
    assert sql("SELECT revision FROM public.pr_workspaces WHERE id=%s", bob_workspace)[0][0] == revision


@check("RAP-087", "sign-in events are append-only: no role (authenticated, service_role) may UPDATE or DELETE pr_audit_events")
def audit_append_only():
    for role in ("authenticated", "service_role", "anon"):
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not sql("SELECT has_table_privilege(%s, 'public.pr_audit_events', %s)", role, privilege)[0][0], (role, privilege)
    with connection() as db:
        db.execute("SET ROLE service_role")
        try:
            db.execute("UPDATE public.pr_audit_events SET kind='tampered' WHERE kind='session.observed'")
            raise AssertionError("service_role could update the audit log")
        except psycopg.errors.InsufficientPrivilege:
            pass


@check("RAP-088", "account deletion removes the person's session inventory and sign-in history per policy")
def deletion_purge():
    observe_mode()

    class Identity:
        def delete_user(self, principal):
            return True

    deleting = HostedWorkspaceService(connection, verify, identity=Identity(), public_base_url="https://app.rafii.example", mailer=FakeMailer())
    user, workspace = person()
    session = signed_in(user)
    deleting.delete_account(workspace, token(user, session, iat=int(time.time())), "DELETE")
    leftovers = {"pr_sessions": sql("SELECT count(*) FROM public.pr_sessions WHERE user_id=%s", user)[0][0],
                 "session_audit": sql("SELECT count(*) FROM public.pr_audit_events WHERE actor=%s AND kind LIKE 'session.%%'", user)[0][0]}
    assert leftovers == {"pr_sessions": 0, "session_audit": 0}, leftovers


@check("RAP-089", "two concurrent first-sighting inserts of one session: exactly one first observation")
def first_sighting_unique():
    observe_mode()
    user, _ = person()
    session, firsts, barrier = new_session(), [], threading.Barrier(4)
    from postriff_phase2.hosted import observe_session

    def insert():
        with connection() as db:
            barrier.wait()
            firsts.append(observe_session(db.cursor(), user, session, "Chrome on Mac")[0])

    threads = [threading.Thread(target=insert) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(firsts) == [False, False, False, True] and observed(user, session) == 1, (firsts, observed(user, session))


@check("RAP-091", "the user id written for a session or revocation is always the verified token subject")
def server_side_user():
    observe_mode()
    alice, _ = person()
    bob, _ = person()
    current, other = signed_in(alice), signed_in(alice)
    call("DELETE", f"/api/auth/sessions/{other}", token(alice, current), {"userId": bob})
    assert sql("SELECT user_id::text FROM public.pr_session_revocations WHERE session_id=%s", other) == [(alice,)]
    assert sql("SELECT count(*) FROM public.pr_sessions WHERE user_id=%s AND session_id IN (%s,%s)", bob, current, other)[0][0] == 0


# --- Agent / incident / privacy rows the current system already answers ------------------------------------------

@check("RAP-105", "GETs of the Security Center's data (me, sessions, security events) never revoke, hold or change factors")
def get_is_harmless():
    observe_mode()
    user, _ = person()
    session = signed_in(user)
    before = sql("SELECT (SELECT count(*) FROM public.pr_session_revocations WHERE user_id=%s),(SELECT count(*) FROM public.pr_mfa_enforcement WHERE user_id=%s)", user, user)
    for path in ("/api/me", "/api/auth/sessions", "/api/me/security-events"):
        assert call("GET", path, token(user, session))[0] == 200
    assert sql("SELECT (SELECT count(*) FROM public.pr_session_revocations WHERE user_id=%s),(SELECT count(*) FROM public.pr_mfa_enforcement WHERE user_id=%s)", user, user) == before


@check("RAP-133", "200 sign-ins in a burst with alerts on: notices are bounded, every event is retained")
def alert_flood():
    observe_mode()
    user, _ = person(alerts=True)
    for _ in range(200):
        call("GET", "/api/me", token(user, new_session()))
    assert observed(user) == 200
    assert len(mails_to(user)) <= 20, f"{len(mails_to(user))} new-sign-in emails for one burst"


@check("RAP-143", "notification provider outage: the sign-in request does not wait on mail transport and the event is durable")
def provider_outage():
    observe_mode()
    user, _ = person(alerts=True)
    session = new_session()
    request_thread = threading.current_thread().name
    call("GET", "/api/me", token(user, session))
    assert observed(user, session) == 1
    in_request = [m for m in mails_to(user) if m["thread"] == request_thread]
    assert in_request == [], "the legacy mailer ran inside the request"


# --- Rollout (G11) --------------------------------------------------------------------------------------------------

@check("RAP-139", "flag absent (default off): legacy behaviour — sessions recorded as before, no session.observed, no new friction")
def default_off():
    observe_mode(on=False)
    user, workspace = person()
    session = new_session()
    assert call("GET", "/api/me", token(user, session))[0] == 200
    assert call("GET", f"/api/workspaces/{workspace}", token(user, new_session()))[0] == 200
    assert sql("SELECT count(*) FROM public.pr_sessions WHERE session_id=%s", session)[0][0] == 1 and observed(user) == 0


@check("RAP-140", "observe mode: sign-ins are recorded and an ordinary read is not challenged; existing guards unchanged (AAL1 still refused under 2FA)")
def observe_only():
    observe_mode()
    user, workspace = person()
    session = new_session()
    assert call("GET", f"/api/workspaces/{workspace}", token(user, session))[0] == 200 and observed(user, session) == 1
    sql("INSERT INTO public.pr_mfa_enforcement(user_id) VALUES(%s)", user)
    assert call("GET", f"/api/workspaces/{workspace}", token(user, new_session(), aal="aal1"))[0] == 403
    assert call("GET", f"/api/workspaces/{workspace}", token(user, new_session(), aal="aal2"))[0] == 200


@check("RAP-150", "rollback (observe → off): revoked sessions stay revoked and recorded sign-ins stay in the history")
def rollback():
    observe_mode()
    user, workspace = person()
    current, other = signed_in(user), signed_in(user)
    call("DELETE", f"/api/auth/sessions/{other}", token(user, current), {})
    before = observed(user)
    observe_mode(on=False)
    assert call("GET", f"/api/workspaces/{workspace}", token(user, other))[0] == 401
    history = call("GET", "/api/me/security-events", token(user, current))[1]["events"]
    assert observed(user) == before and len([e for e in history if e["kind"] == "session.observed"]) == before, history


@check("RAP-147", "the harness refuses any target but the dedicated local disposable cluster")
def cleanup_guard():
    for dsn in ("postgresql://postgres@db.buoyhkbodnhzngaotoel.supabase.co:5432/postgres", "host=127.0.0.1 port=5432 dbname=postgres",
                "host=db.oxacvkhpfgytkepxcaqh.supabase.co port=55438 dbname=postgres", "host=127.0.0.1 port=55438 dbname=rafii"):
        try:
            guard_target(dsn)
            raise AssertionError(f"accepted {dsn}")
        except SystemExit:
            pass
    assert guard_target(DSN) == DSN


# --- Verdict ---------------------------------------------------------------------------------------------------------

regressions = {row: r for row, r in results.items() if r["status"] == "FAIL" and row not in KNOWN_GAPS}
closed = sorted(row for row in KNOWN_GAPS if results.get(row, {}).get("status") == "PASS")
for row, gap in KNOWN_GAPS.items():
    if row in results and results[row]["status"] == "FAIL":
        results[row]["knownGap"] = gap
print(json.dumps({"suite": "postgres_rapv2_acceptance", "execution": "disposable-local-postgres; fake mail/push; synthetic tokens",
                  "counts": {s: sum(1 for r in results.values() if r["status"] == s) for s in ("PASS", "FAIL")},
                  "rows": dict(sorted(results.items())), "regressions": sorted(regressions), "closedGaps": closed}, indent=1))
sys.exit(1 if regressions or closed else 0)
