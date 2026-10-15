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
from postriff_phase2.hosted import SIGN_IN_ALERT_BATCH, HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_app import HostedApplication, supabase_verifier  # noqa: E402
from postriff_phase2.notifications import webhooks  # noqa: E402
from postriff_phase2.notifications.service import NotificationService  # noqa: E402

# Rows whose expected result the shipped code does not meet (recorded FAIL, see the module docstring).
KNOWN_GAPS = {
    # RAPv2 P1 as shipped (5e4f4e13) against the matrix; product decisions, not fixed in this tests-only PR.
    "RAP-013": "an unrecordable security state refuses the protected capability with 403 step-up, not 503",
    "RAP-021": "a copied device cookie plus an AAL1 bearer reads as a known browser: sensitive capabilities need no fresh proof",
    "RAP-033": "only four capabilities are gated (tokens, connections, Agent grants, exports); private drafts stay readable",
    "RAP-039": "the step-up gate does not consult account holds: a held account's interactive session can still export",
    "RAP-045": "an account with no second factor is told to complete MFA it cannot complete (no enrolment/recovery next step)",
    "RAP-046": "a fresh TOTP proof from before the factor was removed still satisfies step-up",
    "RAP-064": "risk decisions and incidents queue no mandatory notice",
    "RAP-104": "turning RAFII_SECURITY_INCIDENT_HOLD off stops enforcing existing holds",
    "RAP-114": "an incident report sends no notice to any contact channel",
    "RAP-138": "a browser idle for 200 days still reads as known (no inactivity expiry)",
}

results = {}


def check(row, description):
    def wrap(fn):
        try:
            fn()
            results[row] = {"status": "PASS", "check": description}
        except Exception as error:  # noqa: BLE001 - every row is recorded, the run decides at the end
            # Only an assertion about the expected result is a finding; any other exception is a harness or code error.
            results[row] = {"status": "FAIL", "check": description, "detail": f"{type(error).__name__}: {str(error)[:300]}",
                            "assertion": isinstance(error, AssertionError)}
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

    def __getattr__(self, kind):
        # Welcome, invitation and billing mail are not under test: accept and discard them.
        return lambda *args, **kwargs: {"sent": False, "kind": kind}


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
class IdentityAdmin:
    """Production configures the Supabase identity admin; a fake one keeps logout and revoke-others on their real paths."""
    def logout(self, access_token):
        return True

    def logout_others(self, access_token):
        return True

    def verified_factors(self, principal):
        return []


service = HostedWorkspaceService(connection, verify, public_base_url="https://app.rafii.example", mailer=mailer, identity=IdentityAdmin(),
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
    LAST_HEADERS[:] = list(captured.get("headers") or [])
    try:
        parsed = json.loads(body_out or b"{}")
    except ValueError:
        parsed = {"_bytes": len(body_out)}  # an export archive
    return int(captured["status"].split()[0]), parsed


LAST_HEADERS = []


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


def cron_alerts(hosted=None):
    """The /api/cron/worker step that sends observe mode's new-sign-in mail, run to completion on its own thread
    (production runs it in a separate cron invocation, never inside the sign-in request)."""
    def drain():
        while (hosted or service).deliver_sign_in_alerts().get("pending", 0) >= SIGN_IN_ALERT_BATCH:
            pass
    worker = threading.Thread(target=drain, name="cron-worker")
    worker.start()
    worker.join(60)


def mails_to(user):
    cron_alerts()
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
            # A valid body, so the refusal comes from authentication and not from input validation.
            status, body = call(method, path, access, {"displayName": "Signed out"} if method == "PATCH" else {} if method in ("POST", "DELETE") else None)
            assert status == 401, (method, path, status)
            assert set(body) <= {"error", "code", "requestId"}, body
    assert sql("SELECT coalesce(display_name,'') FROM public.pr_profiles WHERE user_id=%s", user)[0][0] != "Signed out"


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
    # A refresh token Supabase still honours mints a new access JWT for the same session id: still denied (RAP-057 backend).
    assert call("GET", f"/api/workspaces/{workspace}", token(user, other, iat=int(time.time()) + 600, refreshed=True))[0] == 401


@check("RAP-058", "revoking the current session through the API takes effect at once (the UI offers no revoke button for it)")
def revoke_current():
    observe_mode()
    user, workspace = person()
    current = signed_in(user)
    status, body = call("DELETE", f"/api/auth/sessions/{current}", token(user, current), {})
    assert status == 200 and body["current"] is True, body
    assert call("GET", f"/api/workspaces/{workspace}", token(user, current))[0] == 401


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
    # Order 1: the session writes, then it is revoked. The write is its last.
    status, body = call("POST", f"/api/workspaces/{workspace}/actions", token(user, other), {"expectedRevision": revision, "action": "mode", "payload": {"mode": "personal"}})
    assert status == 200, ("write before revoke", status, body)
    written = sql("SELECT revision FROM public.pr_workspaces WHERE id=%s", workspace)[0][0]
    assert written > revision, (revision, written)
    status, body = call("PATCH", "/api/me", token(user, other), {"displayName": "Before revoke"})
    assert status == 200, ("profile before revoke", status, body)
    assert call("DELETE", f"/api/auth/sessions/{other}", token(user, current), {})[0] == 200
    # Order 2: revoked first, then the same still-valid JWT tries both writes.
    status, body = call("POST", f"/api/workspaces/{workspace}/actions", token(user, other), {"expectedRevision": written, "action": "mode", "payload": {"mode": "studio"}})
    assert status == 401, ("write after revoke", status, body)
    assert call("PATCH", "/api/me", token(user, other), {"displayName": "After revoke"})[0] == 401, "profile after revoke"
    assert sql("SELECT display_name FROM public.pr_profiles WHERE user_id=%s", user)[0][0] == "Before revoke"
    assert sql("SELECT revision FROM public.pr_workspaces WHERE id=%s", workspace)[0][0] == written, "a write committed after the revocation"


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
    return notifications.cron(max_items=500)


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
            cron_alerts(v2_hosted)
            assert len([m for m in transport.sent if m["to"].startswith(legacy_user[:8])]) == 1
            assert notifications.cron(max_items=500) == {"status": "disabled"}
        finally:
            verify.on_first_sighting = lambda p, s, label, alert: service._alert_new_device(p, s, label, alert)


def emit_security(notifications):
    """The security step of NotificationService.cron alone (no delivery tick), so the checks below drive the worker."""
    from postriff_phase2.notifications import detector
    with connection() as db:
        cur = db.cursor()
        for event in detector.security_events(cur):
            event.pop("legacy_sent", None)
            notifications.emit(cur, workspace_id=None, **event)


def v2_sign_in(transport):
    observe_mode(v2=True)
    v2_hosted, notifications = v2_service(transport)
    user, _ = person(alerts=True)
    with connection() as db:
        from postriff_phase2.hosted import observe_session
        observe_session(db.cursor(), user, new_session(), "Safari on iPhone")
    emit_security(notifications)
    assert [row[1] for row in security_deliveries(user)] == ["pending"], security_deliveries(user)
    return user, notifications


def due(user):
    # Only this person's delivery is due, so the ticks below cannot be spent on other checks' notices.
    sql("UPDATE public.pr_notification_deliveries SET next_attempt_at=now()+interval '1 day' WHERE user_id<>%s AND status='pending'", user)
    sql("UPDATE public.pr_notification_deliveries SET next_attempt_at=now()-interval '1 second' WHERE user_id=%s AND status='pending'", user)


@check("RAP-068", "transport failure: the event and audit stay, retries are bounded with backoff, then the delivery is dead (not dropped)")
def transport_failure():
    transport = Transport()
    transport.fail = True
    user, notifications = v2_sign_in(transport)
    worker = notifications.worker()
    [(delivery, status, attempts, max_attempts, _)] = security_deliveries(user)
    assert (status, attempts) == ("pending", 0), (status, attempts)
    for attempt in range(1, max_attempts + 1):
        due(user)
        worker.tick()
        _, status, attempts, _, _ = security_deliveries(user)[0]
        assert attempts == attempt, (attempt, attempts)
        if attempt < max_attempts:
            assert status == "pending", (attempt, status)
            assert sql("SELECT next_attempt_at > now() + interval '30 seconds' FROM public.pr_notification_deliveries WHERE id::text=%s", delivery)[0][0], "no backoff"
    assert status == "dead" and max_attempts <= 10, (status, attempts, max_attempts)
    due(user)
    worker.tick()
    assert security_deliveries(user)[0][1:3] == ("dead", max_attempts), "a dead delivery was retried"
    assert observed(user) == 1 and transport.sent == []
    assert sql("SELECT count(*) FROM public.pr_notification_events e JOIN public.pr_notification_deliveries d ON d.event_id=e.id WHERE d.id::text=%s", delivery)[0][0] == 1


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

SECURITY_TABLES = ("pr_sessions", "pr_session_revocations", "pr_audit_events", "pr_mfa_enforcement", "pr_account_tombstones",
                   # RAPv2 P1 (migrations 120-122)
                   "pr_security_devices", "pr_session_security", "pr_security_login_events", "pr_security_account_controls", "pr_security_incidents")


@check("RAP-079", "anon: no SELECT/INSERT/UPDATE/DELETE on any session-security table (P0 and P1)")
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
        for table in ("pr_sessions", "pr_session_revocations", "pr_mfa_enforcement", "pr_account_tombstones", *SECURITY_TABLES[5:]):
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


@check("RAP-082", "every session-security table has RLS enabled and FORCED (a table with no policy is deny-all to non-bypass roles)")
def forced_rls():
    rows = sql("SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, (SELECT count(*) FROM pg_policy p WHERE p.polrelid=c.oid) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname = ANY(%s)", list(SECURITY_TABLES))
    assert len(rows) == len(SECURITY_TABLES), rows
    assert all(enabled and forced for _, enabled, forced, _policies in rows), rows


@check("RAP-086", "user A cannot read or command workspace B through the hosted API (membership check)")
def cross_tenant():
    observe_mode()
    alice, _ = person()
    bob, bob_workspace = person()
    access = token(alice, signed_in(alice))
    status, body = call("GET", f"/api/workspaces/{bob_workspace}", access)
    assert status in (403, 404), status
    revision = sql("SELECT revision FROM public.pr_workspaces WHERE id=%s", bob_workspace)[0][0]
    assert call("POST", f"/api/workspaces/{bob_workspace}/actions", access, {"expectedRevision": revision, "action": "mode", "payload": {"mode": "personal"}})[0] in (403, 404)
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


@check("RAP-088", "account deletion removes the person's session inventory and redacts their sign-in history (no session id or browser label)")
def deletion_purge():
    observe_mode()

    class Identity:
        def delete_user(self, principal):
            return True

    deleting = HostedWorkspaceService(connection, verify, identity=Identity(), public_base_url="https://app.rafii.example", mailer=FakeMailer())
    user, workspace = person()
    session = signed_in(user)
    deleting.delete_account(workspace, token(user, session, iat=int(time.time())), "DELETE")
    # Policy (owner decision A+B, 2026-10-15): the inventory goes; the history stays with no identifying field left.
    assert sql("SELECT count(*) FROM public.pr_sessions WHERE user_id=%s", user)[0][0] == 0
    history = sql("SELECT subject, meta FROM public.pr_audit_events WHERE actor=%s AND kind LIKE 'session.%%'", user)
    assert history, "the sign-in history was dropped instead of redacted"
    identifying = [(subject, meta) for subject, meta in history if subject or {"client", "device"} & set(meta)]
    assert identifying == [] and all(meta.get("privacyErased") for _, meta in history), history


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


# --- RAPv2 P1 (device registry 120, risk engine and step-up, holds 121, incidents 122, erasure 123) ------------------
# Flags are set here only, per check: RAFII_ACCOUNT_PROTECTION_V2_MODE, RAFII_DEVICE_TRUST_V2 (+ synthetic HMAC keys)
# and RAFII_SECURITY_INCIDENT_HOLD. Production leaves the last two unset.

from postriff_phase2 import device_trust, security_holds  # noqa: E402
from postriff_phase2.automation_runs import principal_repository  # noqa: E402

KEY_NEW, KEY_OLD = "k" * 32, "o" * 32
# API tokens (migration 016) are not part of the base harness; tests/phase2/postgres_api_tokens.py loads it the same way.
with connection() as _db:
    if not _db.execute("SELECT to_regclass('public.pr_api_tokens')").fetchone()[0]:
        _db.execute((Path(__file__).resolve().parents[2] / "migrations" / "postriff" / "016_api_tokens.sql").read_text())
DEVICE_KEYS = f"2:{KEY_NEW},1:{KEY_OLD}"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


def p1(mode="observe", device=True, hold=False, keys=DEVICE_KEYS):
    values = {"RAFII_ACCOUNT_PROTECTION_V2_MODE": mode}
    if device:
        values.update(RAFII_DEVICE_TRUST_V2="1", RAFII_DEVICE_COOKIE_KEYS=keys)
    if hold:
        values["RAFII_SECURITY_INCIDENT_HOLD"] = "1"
    flags.attach(values)
    verify.seen.__init__()


def amr(method, at=None):
    return [{"method": method, "timestamp": int(time.time() if at is None else at)}]


def set_cookie():
    return next((value for name, value in LAST_HEADERS if name.lower() == "set-cookie" and value.startswith(device_trust.COOKIE + "=")), None)


def cookie_value(header):
    return header.split(";", 1)[0].split("=", 1)[1] if header else None


def browse(user, session=None, cookie=None, aal="aal1", method="password", path="/api/me", extra=None, **claims):
    """A same-origin browser request; returns (status, body, the device cookie the browser now holds, session)."""
    session = session or new_session()
    headers = {**SAME_ORIGIN, **({"Cookie": f"{device_trust.COOKIE}={cookie}"} if cookie else {}), **(extra or {})}
    status, body = call("GET", path, token(user, session, aal=aal, amr=amr(method), **claims), headers=headers)
    return status, body, cookie_value(set_cookie()) or cookie, session


def devices(user):
    return sql("SELECT id::text,state,hmac_key_version,surface,display_label FROM public.pr_security_devices WHERE user_id=%s ORDER BY first_seen_at", user)


def ledger(user, kind=None):
    query = "SELECT event_type,session_id,device_id::text,details FROM public.pr_security_login_events WHERE user_id=%s" + (" AND event_type=%s" if kind else "")
    return sql(query, *((user, kind) if kind else (user,)))


def known_browser(user):
    """A browser this person used in an earlier session: (cookie, a new session on it already observed as 'known')."""
    _, _, cookie, _ = browse(user)
    status, _, _, session = browse(user, cookie=cookie)
    assert status == 200
    return cookie, session


def export(user, session, cookie=None, aal="aal1", method="password", at=None, extra=None):
    """The `exports` sensitive capability (GET /api/workspaces/{id}/export) from this session and browser."""
    workspace = sql("SELECT workspace_id::text FROM public.pr_memberships WHERE user_id=%s AND role='owner' LIMIT 1", user)[0][0]
    headers = {**SAME_ORIGIN, **({"Cookie": f"{device_trust.COOKIE}={cookie}"} if cookie else {}), **(extra or {})}
    return call("GET", f"/api/workspaces/{workspace}/export", token(user, session, aal=aal, amr=amr(method, at)), headers=headers)


def step_up(result):
    status, body = result
    return status == 403 and body.get("code") == "security_step_up_required"


@check("RAP-014", "first authenticated browser request without a device cookie: the server issues an opaque host-only cookie and records an `observed` device")
def cookie_absent():
    p1()
    user, workspace = person()
    status, _, cookie, _ = browse(user, path=f"/api/workspaces/{workspace}")
    assert status == 200 and cookie and len(cookie) == 43, (status, cookie)
    [(_, state, version, surface, _)] = devices(user)
    assert (state, version, surface) == ("observed", 2, "web")
    assert not sql("SELECT count(*) FROM public.pr_security_devices WHERE token_hash=%s", cookie)[0][0], "raw cookie stored"


for row in ("RAP-135", "RAP-023"):
    @check(row, "the device Set-Cookie is __Host- prefixed, Secure, HttpOnly, SameSite=Lax, Path=/ and has no Domain (never shared with a parent or old domain)")
    def cookie_attributes():
        p1()
        user, _ = person()
        browse(user)
        header = set_cookie()
        assert header, LAST_HEADERS
        attributes = [part.strip().lower() for part in header.split(";")[1:]]
        assert header.startswith("__Host-rafii_device=") and {"secure", "httponly", "samesite=lax", "path=/"} <= set(attributes), header
        assert not any(a.startswith("domain") for a in attributes), header


@check("RAP-017", "same browser, new session: the session is new, the device is the existing one; no new device claim")
def existing_browser_new_session():
    p1()
    user, _ = person(alerts=True)
    cookie, session = known_browser(user)
    assert len(devices(user)) == 1 and len(ledger(user, "device.first_observed")) == 1
    [(_, _, _, details)] = [e for e in ledger(user, "session.observed") if e[1] == session]
    assert details["device"] == "known", details


@check("RAP-018", "a new browser profile for an existing account: a new device record, a device.first_observed event and an eligible alert")
def new_browser():
    p1()
    user, _ = person(alerts=True)
    first, _ = known_browser(user)
    _, _, second, session = browse(user)
    assert second and second != first and len(devices(user)) == 2 and len(ledger(user, "device.first_observed")) == 2
    assert sql("SELECT meta->>'alert' FROM public.pr_audit_events WHERE actor=%s AND kind='session.observed' AND subject=%s", user, session) == [("true",)]


@check("RAP-019", "person B signs in on person A's browser: B gets an unrelated device record; A's device and trust are untouched")
def same_browser_other_person():
    p1()
    alice, _ = person()
    bob, _ = person()
    cookie, _ = known_browser(alice)
    before = devices(alice)
    _, _, _, bob_session = browse(bob, cookie=cookie)
    [(bob_device, state, *_)] = devices(bob)
    assert state == "observed" and bob_device not in {d[0] for d in before} and devices(alice) == before
    [(_, _, _, details)] = [e for e in ledger(bob, "session.observed") if e[1] == bob_session]
    assert details["device"] == "new", details  # A's history never makes B's browser known


@check("RAP-020", "a copied device cookie without a JWT: 401, no device row, no data")
def cookie_without_token():
    p1()
    user, workspace = person()
    cookie, _ = known_browser(user)
    rows = devices(user)
    for path in ("/api/me", f"/api/workspaces/{workspace}", "/api/auth/sessions"):
        status, body = call("GET", path, None, headers={**SAME_ORIGIN, "Cookie": f"{device_trust.COOKIE}={cookie}"})
        assert status == 401 and set(body) <= {"error", "code", "requestId"}, (path, status)
    assert devices(user) == rows


@check("RAP-021", "a stolen device cookie plus a valid AAL1 JWT still needs fresh proof for a sensitive action (trust alone is not sufficient)")
def stolen_cookie_and_token():
    p1(mode="enforce")
    user, _ = person()
    cookie, session = known_browser(user)
    # The attacker replays the victim's bearer and cookie from their own machine: to the server it is the known browser.
    assert step_up(export(user, session, cookie=cookie)), "a known cookie plus an AAL1 bearer reached a sensitive capability without fresh proof"


@check("RAP-022", "malformed or overlong device cookies: no crash, treated as no cookie, a fresh one is issued, no trust")
def malformed_cookie():
    p1()
    user, _ = person()
    for bad in ("!!!not-base64!!!", "A" * 5000, "a" * 42, "a" * 44, "x;y=z"):
        status, _, issued, _ = browse(user, cookie=bad)
        assert status == 200 and issued and issued != bad and len(issued) == 43, (bad[:10], status, issued)
    assert all(state == "observed" for _, state, *_ in devices(user))


@check("RAP-024", "a client claiming a native surface gains nothing: the device stays surface=web, state=observed")
def native_spoof():
    p1()
    user, _ = person()
    browse(user, extra={"X-Rafii-Surface": "native", "X-Rafii-Attestation": "trusted"})
    call("PATCH", "/api/me", token(user, new_session()), {"surface": "native", "trusted": True}, headers=SAME_ORIGIN)
    assert {(state, surface) for _, state, _, surface, _ in devices(user)} == {("observed", "web")}


@check("RAP-025", "a private window (no cookie) on a known account: a separate observed device with a clear browser label")
def private_window():
    p1()
    user, _ = person()
    known_browser(user)
    browse(user)
    labels = [label for *_, label in devices(user)]
    assert len(labels) == 2 and all(label == "Safari on iPhone" for label in labels), labels


@check("RAP-026", "the browser's cookie expired: the next session is an unknown browser and a sensitive capability needs fresh proof")
def cookie_expired():
    p1(mode="enforce")
    user, _ = person()
    known_browser(user)
    _, _, _, session = browse(user)  # no cookie any more
    assert step_up(export(user, session))


@check("RAP-027", "HMAC key rotation: a cookie hashed under the old key is recognised, re-hashed under the new key, and not trusted")
def key_rotation():
    p1(keys=f"1:{KEY_OLD}")
    user, _ = person()
    _, _, cookie, _ = browse(user)
    [(device, _, version, _, _)] = devices(user)
    assert version == 1
    p1(keys=DEVICE_KEYS)
    browse(user, cookie=cookie)
    [(same, state, version, _, _)] = devices(user)
    assert (same, state, version) == (device, "observed", 2), devices(user)
    assert sql("SELECT token_hash FROM public.pr_security_devices WHERE id=%s", device)[0][0] == device_trust.token_hash(KEY_NEW.encode(), user, cookie)


@check("RAP-028", "a revoked device's cookie replayed after a new sign-in: the old record stays revoked and a new untrusted record is made")
def revoked_device_replay():
    p1()
    user, _ = person()
    cookie, _ = known_browser(user)
    [(device, *_)] = devices(user)
    sql("UPDATE public.pr_security_devices SET state='revoked',revoked_at=now(),revoke_reason='acceptance' WHERE id=%s", device)
    _, _, issued, _ = browse(user, cookie=cookie)
    rows = {d[0]: d[1] for d in devices(user)}
    assert rows[device] == "revoked" and len(rows) == 2 and issued != cookie and set(rows.values()) == {"revoked", "observed"}, rows


@check("RAP-083", "pr_session_security cannot link person A's session to person B's device (composite foreign key)")
def cross_user_device_fk():
    p1()
    alice, _ = person()
    bob, _ = person()
    _, _, _, alice_session = browse(alice)
    browse(bob)
    [(bob_device, *_)] = devices(bob)
    with connection() as db:
        try:
            db.execute("UPDATE public.pr_session_security SET device_id=%s WHERE user_id=%s AND session_id=%s", (bob_device, alice, alice_session))
            raise AssertionError("cross-user device link accepted")
        except psycopg.errors.ForeignKeyViolation:
            pass


@check("RAP-090", "re-evaluations with new event keys are all kept; the same key twice is one row")
def repeating_risk_events():
    p1()
    user, _ = person()
    _, _, _, session = browse(user)
    with connection() as db, db.cursor() as cur:
        for key in ("session.risk_reassessed:acceptance-0001", "session.risk_reassessed:acceptance-0002", "session.risk_reassessed:acceptance-0002"):
            device_trust.record(cur, user, "session.risk_reassessed", key, session_id=session, risk_level="medium")
    assert len(ledger(user, "session.risk_reassessed")) == 2
    try:
        sql("UPDATE public.pr_security_login_events SET risk_level='low' WHERE user_id=%s", user)
        raise AssertionError("ledger row changed")
    except psycopg.errors.InsufficientPrivilege:
        pass


# Risk engine and step-up (enforce mode is set in-test only)

@check("RAP-031", "known browser, no recent change, AAL2: an ordinary view and a sensitive capability are both allowed")
def known_low_risk():
    p1(mode="enforce")
    user, workspace = person()
    cookie, session = known_browser(user)
    assert call("GET", f"/api/workspaces/{workspace}", token(user, session, aal="aal2"), headers={**SAME_ORIGIN, "Cookie": f"{device_trust.COOKIE}={cookie}"})[0] == 200
    assert export(user, session, cookie=cookie, aal="aal2")[0] == 200


@check("RAP-032", "unknown browser: account security and ordinary views stay open, a sensitive capability asks for proof")
def unknown_low():
    p1(mode="enforce")
    user, workspace = person()
    _, _, _, session = browse(user)
    for path in ("/api/me", "/api/auth/sessions", "/api/me/security-events", f"/api/workspaces/{workspace}"):
        assert call("GET", path, token(user, session), headers=SAME_ORIGIN)[0] == 200, path
    result = export(user, session)
    assert step_up(result) and result[1]["nextAction"] == "complete_mfa" and "unknown_device" in result[1]["security"]["reasonCodes"], result


@check("RAP-033", "unknown browser right after a sensitive account change: the private drafts list answers 403 security_step_up_required")
def unknown_medium_private_drafts():
    p1(mode="enforce")
    user, workspace = person()
    _, _, _, session = browse(user)
    sql("INSERT INTO public.pr_audit_events(actor,kind,subject,meta) VALUES(%s,'mfa.disabled','','{}')", user)
    status, body = call("GET", f"/api/workspaces/{workspace}", token(user, session), headers=SAME_ORIGIN)
    assert status == 403 and body.get("code") == "security_step_up_required", f"private workspace state served with {status}"


@check("RAP-034", "a fresh same-inbox email OTP is not an independent factor: step-up still required")
def same_email_otp():
    p1(mode="enforce")
    user, _ = person()
    _, _, _, session = browse(user)
    for method in ("otp", "magiclink", "email/signup", "password", "oauth"):
        assert step_up(export(user, session, method=method)), method


@check("RAP-035", "a fresh verified TOTP on an AAL2 session: allowed, and the step-up is recorded on this session")
def fresh_totp():
    p1(mode="enforce")
    user, _ = person()
    _, _, _, session = browse(user)
    assert export(user, session, aal="aal2", method="totp")[0] == 200
    assert sql("SELECT step_up_method FROM public.pr_session_security WHERE user_id=%s AND session_id=%s", user, session) == [("totp",)]
    assert len(ledger(user, "session.step_up_verified")) == 1


@check("RAP-036", "TOTP older than the step-up window: refused; a refreshed token (new iat) is not new proof")
def stale_totp():
    p1(mode="enforce")
    user, _ = person()
    _, _, _, session = browse(user)
    old = time.time() - 1200
    status, body = call("GET", sql("SELECT '/api/workspaces/'||workspace_id::text||'/export' FROM public.pr_memberships WHERE user_id=%s LIMIT 1", user)[0][0],
                        token(user, session, aal="aal2", amr=amr("totp", old), iat=int(time.time())), headers=SAME_ORIGIN)
    assert status == 403 and body.get("code") == "security_step_up_required", status


@check("RAP-037", "a WebAuthn MFA ceremony is verified from the signed token; a client boolean proves nothing")
def webauthn_mfa():
    p1(mode="enforce")
    user, _ = person()
    _, _, _, session = browse(user)
    assert step_up(export(user, session, extra={"X-Step-Up-Verified": "true"}))
    assert export(user, session, aal="aal2", method="mfa/webauthn")[0] == 200
    assert sql("SELECT step_up_method FROM public.pr_session_security WHERE user_id=%s AND session_id=%s", user, session) == [("webauthn_mfa",)]


@check("RAP-038", "a passkey first-factor sign-in (AAL1) is not treated as AAL2 step-up")
def passkey_aal1():
    p1(mode="enforce")
    user, _ = person()
    _, _, _, session = browse(user)
    for method in ("webauthn", "passkey", "mfa/webauthn", "totp"):
        assert step_up(export(user, session, aal="aal1", method=method)), method


@check("RAP-039", "an account hold blocks a sensitive capability even from a known browser with fresh AAL2 proof")
def hold_blocks_sensitive():
    p1(mode="enforce", hold=True)
    user, _ = person()
    cookie, session = known_browser(user)
    with connection() as db, db.cursor() as cur:
        security_holds.place(cur, user, "acceptance.check")
    status, body = export(user, session, cookie=cookie, aal="aal2", method="totp")
    assert status == 403 and body.get("code") in ("security_account_hold", "security_step_up_required"), f"export served under an active hold ({status})"


@check("RAP-040", "riskLevel=low / trusted=true in the request is ignored: the challenge stands")
def spoofed_allow_json():
    p1(mode="enforce")
    user, workspace = person()
    _, _, _, session = browse(user)
    status, body = call("POST", f"/api/workspaces/{workspace}/tokens", token(user, session),
                        {"name": "acceptance", "riskLevel": "low", "trusted": True, "deviceState": "trusted", "security": {"outcome": "allow"}}, headers=SAME_ORIGIN)
    assert status == 403 and body.get("code") == "security_step_up_required", (status, body)
    assert sql("SELECT risk_level,enforcement FROM public.pr_session_security WHERE user_id=%s AND session_id=%s", user, session) == [("medium", "challenge")]


@check("RAP-041", "a different country header on a known browser never locks the account; ordinary reads continue")
def travel():
    p1(mode="enforce", hold=True)
    user, workspace = person()
    cookie, session = known_browser(user)
    geo = {"Cf-Ipcountry": "JP", "X-Vercel-Ip-Country": "JP", "X-Forwarded-For": "198.51.100.23"}
    status = call("GET", f"/api/workspaces/{workspace}", token(user, session), headers={**SAME_ORIGIN, "Cookie": f"{device_trust.COOKIE}={cookie}", **geo})[0]
    assert status == 200
    assert sql("SELECT count(*) FROM public.pr_security_account_controls WHERE user_id=%s AND hold_active", user)[0][0] == 0


@check("RAP-042", "spoofed X-Forwarded-For / geo headers are never stored or used in a decision")
def spoofed_proxy():
    p1(mode="enforce")
    user, _ = person()
    spoof = {"X-Forwarded-For": "203.0.113.99", "X-Real-Ip": "203.0.113.99", "Cf-Ipcountry": "KP"}
    _, _, _, session = browse(user, extra=spoof)
    plain = export(user, session)
    spoofed = export(user, session, extra=spoof)
    assert plain[0] == spoofed[0] == 403 and plain[1]["security"] == spoofed[1]["security"]
    stored = json.dumps(sql("SELECT row_to_json(e) FROM public.pr_security_login_events e WHERE user_id=%s", user) + sql("SELECT row_to_json(s) FROM public.pr_session_security s WHERE user_id=%s", user), default=str)
    assert "203.0.113.99" not in stored and "KP" not in stored


@check("RAP-043", "a stale stored decision is never reused: the request is re-evaluated under the current policy first")
def policy_version():
    p1(mode="enforce")
    user, _ = person()
    _, _, _, session = browse(user)
    sql("UPDATE public.pr_session_security SET risk_level='low',enforcement='allow',risk_reasons='[]',policy_version=1 WHERE user_id=%s AND session_id=%s", user, session)
    assert step_up(export(user, session))
    assert sql("SELECT enforcement FROM public.pr_session_security WHERE user_id=%s AND session_id=%s", user, session) == [("challenge",)]


def security_state_unavailable(path_for):
    """Make the gate's security read fail (the table is briefly renamed), then restore it."""
    p1(mode="enforce", device=False)
    user, workspace = person()
    session = signed_in(user)
    sql("ALTER TABLE public.pr_session_security RENAME TO pr_session_security_offline")
    try:
        sensitive = call(*path_for(workspace), token(user, session), {} if path_for(workspace)[0] == "POST" else None, headers=SAME_ORIGIN)
        safe = [call("GET", p, token(user, session))[0] for p in ("/api/me", f"/api/workspaces/{workspace}")]
    finally:
        sql("ALTER TABLE public.pr_session_security_offline RENAME TO pr_session_security")
    return sensitive, safe


@check("RAP-044", "security state unreadable: the sensitive capability fails closed with 503; ordinary and help routes still work")
def risk_db_unavailable():
    (status, body), safe = security_state_unavailable(lambda w: ("GET", f"/api/workspaces/{w}/export"))
    assert status == 503 and body.get("code") == "security_state_unavailable", (status, body)
    assert safe == [200, 200], safe


@check("RAP-144", "security state unreadable: connecting an account (the step before any connected publish) fails closed with 503")
def risk_db_timeout_connected():
    (status, body), safe = security_state_unavailable(lambda w: ("POST", f"/api/workspaces/{w}/channels/threads/oauth/start"))
    assert status == 503 and body.get("code") == "security_state_unavailable", (status, body)
    assert safe == [200, 200]


@check("RAP-045", "an account with no second factor gets a deterministic enrolment/recovery next step, not an unsatisfiable MFA prompt")
def mfa_unsupported():
    p1(mode="enforce")
    user, _ = person()
    _, _, _, session = browse(user)
    status, body = export(user, session)
    assert status == 403 and body.get("nextAction") in ("enroll_mfa", "set_up_mfa", "recovery", "contact_support"), f"nextAction={body.get('nextAction')} for an account with no factor"


@check("RAP-046", "a second factor removed after the proof: the old proof no longer authorizes a sensitive action")
def factor_removed_after_proof():
    p1(mode="enforce")
    user, _ = person()
    cookie, session = known_browser(user)
    proved = time.time() - 60
    sql("INSERT INTO public.pr_audit_events(actor,kind,subject,meta) VALUES(%s,'mfa.disabled','','{}')", user)
    assert step_up(export(user, session, cookie=cookie, aal="aal2", method="totp", at=proved)), "a TOTP proof from before the factor was removed still authorized the export"


@check("RAP-047", "a direct API client with no Security Center code meets the same challenge")
def no_ui_reliance():
    p1(mode="enforce")
    user, workspace = person()
    session = new_session()
    status, body = call("GET", f"/api/workspaces/{workspace}/export", token(user, session), agent="curl/8.7.1")
    assert status == 403 and body.get("code") == "security_step_up_required", (status, body)


@check("RAP-048", "proof made in session B never satisfies session A")
def wrong_session_proof():
    p1(mode="enforce")
    user, _ = person()
    _, _, _, session_a = browse(user)
    _, _, _, session_b = browse(user)
    assert export(user, session_b, aal="aal2", method="totp")[0] == 200
    assert step_up(export(user, session_a))
    assert sql("SELECT session_id FROM public.pr_session_security WHERE user_id=%s AND step_up_method IS NOT NULL", user) == [(session_b,)]


@check("RAP-141", "enforce mode turns the gate on for protected operations; observe mode leaves them as before")
def enforce_gated():
    p1(mode="observe")
    user, _ = person()
    _, _, _, session = browse(user)
    assert export(user, session)[0] == 200
    p1(mode="enforce")
    assert step_up(export(user, session))


@check("RAP-013", "the session's security record cannot be written: no allowed state, and the protected route answers 503")
def observation_fails():
    p1(mode="enforce")
    user, _ = person()
    original = device_trust.observe
    device_trust.observe = lambda *args, **kwargs: (_ for _ in ()).throw(psycopg.errors.CheckViolation("injected"))
    try:
        session = new_session()
        status, body = export(user, session)
    finally:
        device_trust.observe = original
    assert status != 200, "allowed without a security record"
    assert status == 503, f"refused with {status} {body.get('code')} instead of 503"


@check("RAP-096", "reconnecting a social account from a challenged session needs fresh proof")
def reconnect_needs_proof():
    p1(mode="enforce")
    user, workspace = person()
    _, _, _, session = browse(user)
    status, body = call("POST", f"/api/workspaces/{workspace}/channels/threads/oauth/start", token(user, session), {}, headers=SAME_ORIGIN)
    assert status == 403 and body.get("code") == "security_step_up_required", (status, body)


@check("RAP-138", "a browser unused for more than 180 days is no longer silently known")
def inactive_browser():
    p1(mode="enforce")
    user, _ = person()
    cookie, _ = known_browser(user)
    sql("UPDATE public.pr_security_devices SET first_seen_at=now()-interval '400 days', last_seen_at=now()-interval '200 days' WHERE user_id=%s", user)
    _, _, _, session = browse(user, cookie=cookie)
    assert step_up(export(user, session, cookie=cookie)), "a browser idle for 200 days still counted as known"


# Account holds (RAFII_SECURITY_INCIDENT_HOLD in-test only)

def api_token(user, workspace):
    p1(mode="observe", device=False)
    status, body = call("POST", f"/api/workspaces/{workspace}/tokens", token(user, signed_in(user), iat=int(time.time())), {"name": "acceptance", "scopes": ["read"], "expiresDays": 30})
    assert status in (200, 201), (status, body)
    return body.get("secret")


for row in ("RAP-061", "RAP-101"):
    @check(row, "a valid API token is refused at the action gateway while the account is held")
    def token_on_hold():
        user, workspace = person()
        secret = api_token(user, workspace)
        assert secret and secret.startswith("prt_"), secret
        p1(device=False, hold=True)
        assert call("GET", f"/api/workspaces/{workspace}", secret)[0] == 200
        with connection() as db, db.cursor() as cur:
            security_holds.place(cur, user, "acceptance.check")
        status, body = call("GET", f"/api/workspaces/{workspace}", secret)
        assert status == 403 and body.get("code") == "security_account_hold", (status, body)


def worker_transaction(user, workspace, **fence):
    repository, capability = principal_repository(service, workspace, user, "edit", **fence)
    with repository.transaction(capability, workspace):
        return True


def refused_with(code, fn):
    try:
        fn()
    except security_holds.AccountHeld as error:
        assert error.code == code, error.code
        return
    raise AssertionError("the worker transaction ran")


@check("RAP-093", "work approved before the hold (and the hold since released) is refused at worker claim")
def preapproved_after_hold():
    p1(device=False, hold=True)
    user, workspace = person()
    approved_at = time.time() - 30
    with connection() as db, db.cursor() as cur:
        security_holds.place(cur, user, "acceptance.check")
        security_holds.release(cur, user, "acceptance.check")
    refused_with("security_hold_changed", lambda: worker_transaction(user, workspace, authorized_at=approved_at))
    assert worker_transaction(user, workspace, authorized_at=time.time() + 1)


@check("RAP-094", "a hold placed after the worker claimed (epoch captured) stops the final pre-publish check")
def hold_after_claim():
    p1(device=False, hold=True)
    user, workspace = person()
    with connection() as db, db.cursor() as cur:
        epoch = security_holds.snapshot(cur, user)
    with connection() as db, db.cursor() as cur:
        security_holds.place(cur, user, "acceptance.check")
    refused_with("security_account_hold", lambda: worker_transaction(user, workspace, hold_epoch=epoch))


@check("RAP-095", "hold set, released and set again: a job holding the old epoch is refused (no ABA)")
def hold_epoch_aba():
    p1(device=False, hold=True)
    user, workspace = person()
    with connection() as db, db.cursor() as cur:
        epoch = security_holds.snapshot(cur, user)
        security_holds.place(cur, user, "acceptance.check")
        security_holds.release(cur, user, "acceptance.check")
    refused_with("security_hold_changed", lambda: worker_transaction(user, workspace, hold_epoch=epoch))
    with connection() as db, db.cursor() as cur:
        security_holds.place(cur, user, "acceptance.check")
        security_holds.release(cur, user, "acceptance.check")
        current = security_holds.snapshot(cur, user)
    assert current == epoch + 4 and worker_transaction(user, workspace, hold_epoch=current)


@check("RAP-098", "an Agent/worker run prepared before the owner removed the grant is denied on the refreshed membership")
def grant_revoked():
    p1(device=False)
    owner, workspace = person()
    editor, _ = person()
    sql("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", workspace, editor)
    repository, capability = principal_repository(service, workspace, editor, "edit")
    sql("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s", workspace, editor)
    try:
        with repository.transaction(capability, workspace):
            raise AssertionError("ran on the old grant")
    except AlphaError as error:
        assert error.status in (403, 404), error.status


@check("RAP-097", "a viewer's direct publish/approve call is refused by role, whatever the browser")
def viewer_publish():
    p1(device=True)
    owner, workspace = person()
    viewer, _ = person()
    sql("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active')", workspace, viewer)
    cookie, session = known_browser(viewer)
    revision = sql("SELECT revision FROM public.pr_workspaces WHERE id=%s", workspace)[0][0]
    status, body = call("POST", f"/api/workspaces/{workspace}/actions", token(viewer, session, aal="aal2"),
                        {"expectedRevision": revision, "action": "p2_approve", "payload": {"draftId": "draft-acceptance"}},
                        headers={**SAME_ORIGIN, "Cookie": f"{device_trust.COOKIE}={cookie}"})
    assert status == 403, (status, body)
    assert sql("SELECT revision FROM public.pr_workspaces WHERE id=%s", workspace)[0][0] == revision


@check("RAP-099", "a held account's scheduled/proactive phone call is refused before any provider call")
def phone_on_hold():
    from postriff_phase2.phone.runtime import principal_phone
    from postriff_phase2.phone.service import PhoneService
    from postriff_phase2.phone.providers.fake import FakeTelephonyProvider
    p1(device=False, hold=True)
    user, workspace = person()
    provider = FakeTelephonyProvider()
    phone = PhoneService(service, {"RAFII_PHONE_ENABLED": "1"}, provider=provider)
    with connection() as db, db.cursor() as cur:
        security_holds.place(cur, user, "acceptance.check")
    scoped, capability = principal_phone(phone, workspace, user)
    try:
        scoped.request(workspace, capability, {"idempotencyKey": "schedule:acceptance:1"}, kind="scheduled", reason_key="schedule:acceptance")
        raise AssertionError("a scheduled call was admitted under a hold")
    except AlphaError as error:
        assert error.code == "security_account_hold", (error.status, error.code, str(error))
    assert sql("SELECT count(*) FROM public.pr_phone_calls WHERE user_id=%s", user)[0][0] == 0
    assert provider.create_count == 0, provider.create_count


@check("RAP-104", "turning the incident/hold feature flag off after an incident keeps the core hold enforced")
def rollback_keeps_hold():
    user, workspace = person()
    secret = api_token(user, workspace)
    p1(device=False, hold=True)
    with connection() as db, db.cursor() as cur:
        security_holds.place(cur, user, "acceptance.check")
    p1(device=False, hold=False)  # the rollback lever
    status, body = call("GET", f"/api/workspaces/{workspace}", secret)
    assert status == 403, f"the held account's API token worked again ({status}) once RAFII_SECURITY_INCIDENT_HOLD was off"


# "This wasn't me" incidents

def report(user, session, body=None, key=None, method="password", at=None, origin=None, access=None):
    headers = {**({"Idempotency-Key": key} if key else {}), **({"Origin": origin} if origin else {})}
    return call("POST", "/api/auth/security/incidents", access if access is not None else token(user, session, amr=amr(method, at)),
                body if body is not None else {"type": "not_me", "confirmed": True, "revokeOtherSessions": True}, headers=headers)


def hold_row(user):
    return sql("SELECT hold_active,hold_epoch FROM public.pr_security_account_controls WHERE user_id=%s", user)


@check("RAP-106", "an unconfirmed (cancelled) report changes nothing: no hold, no revocation")
def incident_not_confirmed():
    p1(hold=True)
    user, _ = person()
    current, other = signed_in(user), signed_in(user)
    for body in ({"type": "not_me", "confirmed": False, "revokeOtherSessions": True}, {"type": "not_me", "revokeOtherSessions": True}):
        assert report(user, current, body)[0] == 400
    assert hold_row(user) == [] and sql("SELECT count(*) FROM public.pr_session_revocations WHERE user_id=%s", user)[0][0] == 0


@check("RAP-107", "a confirmed report with fresh proof: one incident, the hold epoch moves, a receipt says what was done")
def incident_confirmed():
    p1(hold=True)
    user, workspace = person()
    current, other = signed_in(user), signed_in(user)
    status, body = report(user, current)
    assert status == 201 and body["accountHold"] is True and body["holdEpoch"] == 1, (status, body)
    assert body["sessions"]["rafiiApiRevoked"] >= 1 and body["connectedAccounts"] == "not_disconnected", body
    assert hold_row(user) == [(True, 1)] and sql("SELECT count(*) FROM public.pr_security_incidents WHERE user_id=%s", user)[0][0] == 1
    assert call("GET", f"/api/workspaces/{workspace}", token(user, other))[0] == 401
    assert call("GET", "/api/me", token(user, current))[0] == 200  # the reporting session stays


@check("RAP-108", "an anonymous or forged report: 401 and no hold")
def incident_anonymous():
    p1(hold=True)
    user, _ = person()
    for access in ("", "not-a-jwt-" + "x" * 30, token(user, new_session(), expired=True)):
        status, _ = report(user, None, access=access)
        assert status == 401, status
    assert hold_row(user) == []


@check("RAP-109", "reporting another person's sign-in event: the same 404 as an unknown id, no incident, no hold")
def incident_foreign_event():
    p1(hold=True)
    alice, _ = person()
    bob, _ = person()
    _, _, _, bob_session = browse(bob)
    [(bob_event,)] = sql("SELECT id::text FROM public.pr_security_login_events WHERE user_id=%s AND event_type='session.observed' AND session_id=%s", bob, bob_session)
    session = signed_in(alice)
    body = {"type": "not_me", "confirmed": True, "revokeOtherSessions": False}
    foreign = report(alice, session, {**body, "sourceEventId": bob_event})
    unknown = report(alice, session, {**body, "sourceEventId": str(uuid.uuid4())})
    strip = lambda result: (result[0], {k: v for k, v in result[1].items() if k != "requestId"})
    assert strip(foreign) == strip(unknown) and foreign[0] == 404, (foreign, unknown)
    assert hold_row(alice) == [] and hold_row(bob) == [] and sql("SELECT count(*) FROM public.pr_security_incidents WHERE user_id IN (%s,%s)", alice, bob)[0][0] == 0


@check("RAP-110", "a repeated report with the same Idempotency-Key returns the same receipt; no second hold")
def incident_idempotent():
    p1(hold=True)
    user, _ = person()
    session = signed_in(user)
    key = f"acceptance-{uuid.uuid4().hex}"
    first = report(user, session, key=key)
    second = report(user, session, key=key)
    assert first[0] == 201 and second[0] == 200 and first[1]["incidentId"] == second[1]["incidentId"] and second[1]["holdEpoch"] == 1, (first, second)
    assert hold_row(user) == [(True, 1)] and sql("SELECT count(*) FROM public.pr_security_incidents WHERE user_id=%s", user)[0][0] == 1


@check("RAP-115", "the incident receipt says already-executed actions are not reversible and connected accounts were not disconnected")
def incident_disclosure():
    p1(hold=True)
    user, _ = person()
    status, body = report(user, signed_in(user))
    assert status == 201 and body["agents"] == {"newSensitiveActions": "held", "alreadyExecutedActions": "not_reversible"}, body
    assert "recall" not in json.dumps(body).lower() and "undo" not in json.dumps(body).lower()


@check("RAP-116", "following an email link (GET) without confirming in the app changes nothing")
def email_only():
    p1(hold=True)
    user, _ = person()
    session = signed_in(user)
    before = (hold_row(user), sql("SELECT count(*) FROM public.pr_session_revocations WHERE user_id=%s", user))
    for path in ("/api/auth/security/incidents", "/api/me", "/api/auth/sessions", "/api/me/security-events"):
        assert call("GET", path, token(user, session))[0] == 200, path
    assert (hold_row(user), sql("SELECT count(*) FROM public.pr_session_revocations WHERE user_id=%s", user)) == before


@check("RAP-085", "person A never sees person B's incidents, and B's incident is unchanged")
def incident_cross_user():
    p1(hold=True)
    alice, _ = person()
    bob, _ = person()
    _, bob_report = report(bob, signed_in(bob))
    listed = call("GET", "/api/auth/security/incidents", token(alice, signed_in(alice)))[1]["incidents"]
    assert bob_report["incidentId"] not in json.dumps(listed)
    assert sql("SELECT state FROM public.pr_security_incidents WHERE id=%s", bob_report["incidentId"]) == [("user_confirmed",)]


@check("RAP-132", "probing the incident route with foreign or random ids gives one generic 404 body")
def enumeration():
    p1(hold=True)
    alice, _ = person()
    bob, _ = person()
    browse(bob)
    session = signed_in(alice)
    # Three reports per person per hour: one foreign event id and one random id.
    bob_event = sql("SELECT id::text FROM public.pr_security_login_events WHERE user_id=%s AND event_type='session.observed'", bob)[0][0]
    bodies = set()
    for target in (bob_event, str(uuid.uuid4())):
        status, body = report(alice, session, {"type": "not_me", "confirmed": True, "revokeOtherSessions": False, "sourceEventId": target})
        assert status == 404, status
        bodies.add(json.dumps({k: v for k, v in body.items() if k != "requestId"}, sort_keys=True))
    assert len(bodies) == 1, bodies


@check("RAP-134", "a report from a hostile Origin is refused by the origin guard before anything changes")
def incident_csrf():
    p1(hold=True)
    user, _ = person()
    status, _ = report(user, signed_in(user), origin="https://evil.example")
    assert status == 403 and hold_row(user) == []


@check("RAP-064", "a high-risk security event queues a mandatory notice even with routine alerts off")
def mandatory_notice():
    p1(hold=True)
    user, _ = person(alerts=False)
    report(user, signed_in(user))
    from postriff_phase2.notifications import detector
    with connection() as db:
        events = [e for e in detector.security_events(db.cursor()) if e["user_id"] == user]
    assert events, "an incident report (hold placed, sessions revoked) produced no security notice for the person"


@check("RAP-114", "an incident notifies previously verified contact channels")
def incident_notice_recipients():
    p1(hold=True)
    user, _ = person(alerts=True)
    report(user, signed_in(user))
    from postriff_phase2.notifications import detector
    with connection() as db:
        kinds = [e["payload"].get("title") for e in detector.security_events(db.cursor()) if e["user_id"] == user]
    assert any("report" in (k or "").lower() or "hold" in (k or "").lower() for k in kinds), kinds


@check("RAP-102", "a consumer session reaches no founder/operator API on the consumer app")
def founder_boundary():
    p1(device=False)
    user, _ = person()
    session = signed_in(user)
    for path in ("/api/founder/overview", "/api/control/overview", "/api/admin/users", "/api/founder/accounts/block"):
        assert call("GET", path, token(user, session, aal="aal2"))[0] in (403, 404), path


@check("RAP-092", "the P1 migrations (120-123) apply to a disposable database: every table and function exists, RLS forced")
def migrations_dry_run():
    tables = ("pr_security_devices", "pr_session_security", "pr_security_login_events", "pr_security_account_controls", "pr_security_incidents")
    rows = sql("SELECT relname, relrowsecurity AND relforcerowsecurity FROM pg_class WHERE relnamespace='public'::regnamespace AND relname = ANY(%s)", list(tables))
    assert sorted(rows) == sorted((t, True) for t in tables), rows
    for function in ("public.pr_security_purge(uuid)", "public.pr_security_set_hold(uuid,boolean,text)", "public.pr_erase_session_history(uuid)"):
        assert sql("SELECT to_regprocedure(%s) IS NOT NULL", function)[0][0], function


# --- Verdict ---------------------------------------------------------------------------------------------------------

regressions = {row: r for row, r in results.items() if r["status"] == "FAIL" and (row not in KNOWN_GAPS or not r["assertion"])}
closed = sorted(row for row in KNOWN_GAPS if results.get(row, {}).get("status") == "PASS")
for row, gap in KNOWN_GAPS.items():
    if row in results and results[row]["status"] == "FAIL":
        results[row]["knownGap"] = gap
print(json.dumps({"suite": "postgres_rapv2_acceptance", "execution": "disposable-local-postgres; fake mail/push; synthetic tokens",
                  "counts": {s: sum(1 for r in results.values() if r["status"] == s) for s in ("PASS", "FAIL")},
                  "rows": dict(sorted(results.items())), "regressions": sorted(regressions), "closedGaps": closed}, indent=1))
sys.exit(1 if regressions or closed else 0)
